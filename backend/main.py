import os
import json
import logging
import bcrypt
import time
from uuid import uuid4
from typing import List
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chains import RetrievalQA
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import PromptTemplate
from sqlalchemy.orm import Session

from database import get_db, User, DocumentMetadata, init_db
from logger_setup import setup_json_logging

# Initialize structured JSON logging
setup_json_logging()

from ingest import ingest_file, PatchedGoogleGenerativeAIEmbeddings, EMBEDDING_MODEL, user_faiss_path, EMBEDDING_DIM

logger = logging.getLogger("uvicorn.error")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# In-memory cache for loaded FAISS indices to avoid expensive disk reads
_vector_store_cache = {}

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 32 or SECRET_KEY.startswith("insightz-super-secret-key"):
    raise RuntimeError("JWT_SECRET_KEY environment variable is missing, is too short (minimum 32 characters), or is using an insecure default value.")
ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if origin.strip()
]
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}

security = HTTPBearer()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        logger.warning("Password verification failed")
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

@app.on_event("startup")
def startup_event():
    init_db()

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
    logger.exception("Global uncaught exception occurred")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
    )



# --- DATA MODELS ---
class DocumentSelection(BaseModel):
    filenames: List[str]

class SearchRequest(BaseModel):
    query: str

class UserCredentials(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(..., min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 bytes in UTF-8 encoding.")
        return v

# --- HEALTH ENDPOINT ---
@app.get("/health")
def health_check():
    return {"status": "healthy"}

# --- AUTH ENDPOINTS ---
@app.post("/signup")
def signup(creds: UserCredentials, db: Session = Depends(get_db)):
    # Check if username exists
    existing_user = db.query(User).filter(User.username == creds.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already taken")
    
    # Hash password using bcrypt directly
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(creds.password.encode('utf-8'), salt).decode('utf-8')
    
    new_user = User(username=creds.username, password=hashed_password)
    db.add(new_user)
    db.commit()
    
    logger.info("User registered successfully", extra={"operation": "signup", "username": creds.username})
    return {"message": "Ranger registered successfully"}

@app.post("/login")
def login(creds: UserCredentials, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == creds.username).first()
    
    if user and verify_password(creds.password, user.password):
        expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS)
        token = jwt.encode({"sub": user.username, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)
        
        logger.info("User logged in successfully", extra={"operation": "login", "username": creds.username})
        return {"token": token, "username": user.username}
    else:
        logger.warning("Failed login attempt", extra={"operation": "login", "username": creds.username})
        raise HTTPException(status_code=401, detail="Invalid credentials")

# --- DOCUMENT ENDPOINTS ---
@app.get("/documents")
def list_documents(current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    docs = db.query(DocumentMetadata).filter(DocumentMetadata.username == current_user).all()
    return [{"filename": d.filename, "category": d.category, "summary": d.summary} for d in docs]

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
        temp_filename = os.path.join(BASE_DIR, f"temp_{uuid4().hex}{ext}")

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

        result = await run_in_threadpool(ingest_file, temp_filename, current_user, original_name)
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

@app.post("/search")
def search_documents(req: SearchRequest, current_user: str = Depends(get_current_user)):
    try:
        start_time = time.time()
        query = req.query
        user_db_path = user_faiss_path(current_user)
        if not os.path.exists(user_db_path): 
            return {"answer": "System offline. Please upload a document first.", "citation": "System"}
        
        # Check in-memory cache first to avoid disk reads
        vector_store = _vector_store_cache.get(current_user)
        if not vector_store:
            embeddings = PatchedGoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL, output_dimensionality=EMBEDDING_DIM, max_retries=3)
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
            retriever=vector_store.as_retriever(search_kwargs={"k": 4, "filter": {"owner": current_user}}),
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
            
        latency_ms = int((time.time() - start_time) * 1000)
        logger.info(
            "Semantic search processed successfully", 
            extra={
                "operation": "search",
                "username": current_user,
                "latency_ms": latency_ms
            }
        )
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
def generate_cross_summary(selection: DocumentSelection, current_user: str = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        start_time = time.time()
        # Query matching document metadata via SQLAlchemy
        selected_docs = db.query(DocumentMetadata).filter(
            DocumentMetadata.filename.in_(selection.filenames),
            DocumentMetadata.username == current_user
        ).all()
        
        if not selected_docs: return {"cross_summary": "No matching documents found in selection."}
    
        combined_text = ""
        for d in selected_docs: combined_text += f"- File: {d.filename} ({d.category}): {d.summary}\n"
        
        # Using gemini-2.5-flash-lite (high free tier quota)
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0.3, max_retries=3)
        
        prompt = f"You are an Intelligence Analyst. Write a connection report based ONLY on these documents:\n{combined_text}\nIdentify relationships and combine information."
        
        response = llm.invoke(prompt)
        latency_ms = int((time.time() - start_time) * 1000)
        logger.info(
            "Cross summary processed successfully", 
            extra={
                "operation": "cross_summary",
                "username": current_user,
                "doc_count": len(selected_docs),
                "latency_ms": latency_ms
            }
        )
        return {"cross_summary": response.content}
    except Exception as e:
        error_msg = str(e)
        if "API key not valid" in error_msg or "API_KEY_INVALID" in error_msg:
            return {"cross_summary": "Error: The configured Gemini API key is invalid or missing. Please set a valid GOOGLE_API_KEY in your backend/.env file."}
        elif "429" in error_msg or "ResourceExhausted" in error_msg:
            return {"cross_summary": "Error: The Gemini API rate limit has been exceeded. Please wait a moment before trying again."}
        raise HTTPException(status_code=500, detail=str(e))

from fastapi.staticfiles import StaticFiles

FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")

# Serve the static frontend files
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
