import os
import json
import logging
from uuid import uuid4
from typing import List
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chains import RetrievalQA
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import PromptTemplate
from ingest import ingest_file, PatchedGoogleGenerativeAIEmbeddings, EMBEDDING_MODEL

logger = logging.getLogger("uvicorn.error")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# In-memory cache for loaded FAISS indices to avoid expensive disk reads
_vector_store_cache = {}

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "insightz-super-secret-key-development-12345")
ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if origin.strip()
]
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

def verify_password(plain_password, hashed_password):
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        logger.warning("Password verification failed (possibly non-bcrypt hash in DB)")
        return False

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {str(exc)}"},
    )



# --- DATA MODELS ---
class DocumentSelection(BaseModel):
    filenames: List[str]

class UserCredentials(BaseModel):
    username: str
    password: str

# --- DB HELPERS ---
def load_json_db(filename):
    abs_path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(abs_path): return []
    try:
        with open(abs_path, "r") as f: return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load %s: %s", abs_path, e)
        return []

def save_json_db(filename, data):
    abs_path = os.path.join(BASE_DIR, filename)
    tmp_path = abs_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=4)
    os.replace(tmp_path, abs_path)

# --- AUTH ENDPOINTS (The Missing Piece!) ---
@app.post("/signup")
def signup(creds: UserCredentials):
    users = load_json_db("users.json")
    # Check if username exists
    if any(u['username'] == creds.username for u in users):
        raise HTTPException(status_code=400, detail="Username already taken")
    
    hashed_password = pwd_context.hash(creds.password)
    users.append({"username": creds.username, "password": hashed_password})
    save_json_db("users.json", users)
    return {"message": "Ranger registered successfully"}

@app.post("/login")
def login(creds: UserCredentials):
    users = load_json_db("users.json")
    user = next((u for u in users if u['username'] == creds.username), None)
    
    if user and verify_password(creds.password, user['password']):
        expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS)
        token = jwt.encode({"sub": user['username'], "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)
        return {"token": token, "username": user['username']}
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")

# --- DOCUMENT ENDPOINTS ---
@app.get("/documents")
def list_documents(current_user: str = Depends(get_current_user)):
    # This reads the doc_store.json to fill your sidebar
    docs = load_json_db("doc_store.json")
    return [{"filename": d["filename"], "category": d["category"], "summary": d.get("summary", "No summary.")} 
            for d in docs if d.get("username") == current_user]

@app.post("/upload")
async def upload_document(file: UploadFile = File(...), current_user: str = Depends(get_current_user)):
    temp_filename = None
    try:
        # Validate file extension against allow-list
        original_name = file.filename or ""
        _, ext = os.path.splitext(original_name)
        ext = ext.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

        # Generate safe temp filename (prevents path traversal)
        temp_filename = f"temp_{uuid4().hex}{ext}"

        # Stream to disk in 1 MB chunks with size enforcement
        max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
        bytes_written = 0
        chunk_size = 1024 * 1024  # 1 MB
        try:
            with open(temp_filename, "wb") as buffer:
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"File exceeds {MAX_UPLOAD_SIZE_MB} MB upload limit."
                        )
                    buffer.write(chunk)
        except HTTPException:
            raise
        except OSError as e:
            logger.error("Failed to write temp upload file: %s", e)
            raise HTTPException(status_code=500, detail="Failed to save uploaded file.")

        result = await run_in_threadpool(ingest_file, temp_filename, current_user)
        if result and "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        # Invalidate FAISS in-memory cache for this user since index has changed
        if result and result.get("status") == "Success":
            _vector_store_cache.pop(current_user, None)
            
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error during upload")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if temp_filename and os.path.exists(temp_filename):
            os.remove(temp_filename)

@app.get("/search")
def search_documents(query: str, current_user: str = Depends(get_current_user)):
    try:
        user_db_path = os.path.join(BASE_DIR, f"faiss_index_{current_user}")
        if not os.path.exists(user_db_path): return {"answer": "System offline. Please upload a document first.", "citation": "System"}
        
        # Check in-memory cache first to avoid disk reads
        vector_store = _vector_store_cache.get(current_user)
        if not vector_store:
            embeddings = PatchedGoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL, output_dimensionality=768, max_retries=3)
            vector_store = FAISS.load_local(user_db_path, embeddings, allow_dangerous_deserialization=True)
            _vector_store_cache[current_user] = vector_store
        
        # Using gemini-2.5-flash-lite (high free tier quota)
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0.3, max_retries=3)
        
        # Define a grounded QA prompt to prevent hallucinations
        qa_prompt_template = (
            "You are an intelligent document analyst. Use only the following context to answer the question at the end.\n"
            "If you do not know the answer or if the context does not contain enough information, say exactly "
            "\"I cannot find the answer in the provided documents.\". Do not try to make up or hypothesize an answer.\n\n"
            "Context:\n{context}\n\n"
            "Question: {question}\n\n"
            "Answer:"
        )
        QA_CHAIN_PROMPT = PromptTemplate(input_variables=["context", "question"], template=qa_prompt_template)
        
        qa_chain = RetrievalQA.from_chain_type(
            llm=llm,
            retriever=vector_store.as_retriever(search_kwargs={"k": 4}),
            chain_type_kwargs={"prompt": QA_CHAIN_PROMPT},
            return_source_documents=True
        )
        response = qa_chain.invoke({"query": query})
        
        # Defense-in-depth: filter source docs to only those owned by the current user
        source_docs = [
            doc for doc in response.get('source_documents', [])
            if doc.metadata.get('owner') == current_user
        ]
        
        citation = "Source: Unknown"
        if source_docs:
            source_file = source_docs[0].metadata.get('source', 'Unknown')
            source_page = source_docs[0].metadata.get('page', 'Unknown')
            citation = f"Source: {source_file} (Page {source_page})"
            
        return {"answer": response['result'], "citation": citation}
    except Exception as e:
        error_msg = str(e)
        if "API key not valid" in error_msg or "API_KEY_INVALID" in error_msg:
            return {
                "answer": "Error: The configured Gemini API key is invalid or missing. Please set a valid GOOGLE_API_KEY in your backend/.env file.",
                "citation": "System Alert"
            }
        elif "429" in error_msg or "ResourceExhausted" in error_msg:
            return {
                "answer": "Error: The Gemini API rate limit has been exceeded. Please wait a moment before trying again.",
                "citation": "System Rate Limit"
            }
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/cross-summary")
def generate_cross_summary(selection: DocumentSelection, current_user: str = Depends(get_current_user)):
    try:
        all_docs = load_json_db("doc_store.json")
        selected_docs = [d for d in all_docs if d['filename'] in selection.filenames and d.get('username') == current_user]
        
        if not selected_docs: return {"cross_summary": "No matching documents found in selection."}
    
        combined_text = ""
        for d in selected_docs: combined_text += f"- File: {d['filename']} ({d['category']}): {d['summary']}\n"
        
        # Using gemini-2.5-flash-lite (high free tier quota)
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0.3, max_retries=3)
        
        prompt = f"You are an Intelligence Analyst. Write a connection report based ONLY on these documents:\n{combined_text}\nIdentify relationships and combine information."
        
        response = llm.invoke(prompt)
        return {"cross_summary": response.content}
    except Exception as e:
        error_msg = str(e)
        if "API key not valid" in error_msg or "API_KEY_INVALID" in error_msg:
            return {"cross_summary": "Error: The configured Gemini API key is invalid or missing. Please set a valid GOOGLE_API_KEY in your backend/.env file."}
        elif "429" in error_msg or "ResourceExhausted" in error_msg:
            return {"cross_summary": "Error: The Gemini API rate limit has been exceeded. Please wait a moment before trying again."}
        raise HTTPException(status_code=500, detail=str(e))

from fastapi.staticfiles import StaticFiles

# Serve the static frontend files
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
