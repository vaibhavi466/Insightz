import os
import shutil
import json
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain.chains import RetrievalQA
from langchain_community.vectorstores import FAISS
from ingest import ingest_file

load_dotenv()

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DATA MODELS ---
class DocumentSelection(BaseModel):
    filenames: List[str]

class UserCredentials(BaseModel):
    username: str
    password: str

# --- DB HELPERS ---
def load_json_db(filename):
    if not os.path.exists(filename): return []
    try:
        with open(filename, "r") as f: return json.load(f)
    except: return []

def save_json_db(filename, data):
    with open(filename, "w") as f: json.dump(data, f, indent=4)

# --- AUTH ENDPOINTS ---
@app.post("/signup")
def signup(creds: UserCredentials):
    users = load_json_db("users.json")
    # Check if username exists
    if any(u['username'] == creds.username for u in users):
        raise HTTPException(status_code=400, detail="Username already taken")
    
    users.append(creds.dict())
    save_json_db("users.json", users)
    return {"message": "Ranger registered successfully"}

@app.post("/login")
def login(creds: UserCredentials):
    users = load_json_db("users.json")
    user = next((u for u in users if u['username'] == creds.username and u['password'] == creds.password), None)
    
    if user:
        # Return a simple token (in production, use JWT)
        return {"token": "valid_ranger_token", "username": user['username']}
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")

# --- CORE ENDPOINTS ---
@app.get("/documents")
def list_documents():
    docs = load_json_db("doc_store.json")
    return [{"filename": d["filename"], "category": d["category"], "summary": d.get("summary", "No summary.")} for d in docs]

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    temp_filename = f"temp_{file.filename}"
    with open(temp_filename, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    result = ingest_file(temp_filename)
    if os.path.exists(temp_filename): os.remove(temp_filename)
    return result

@app.get("/search")
def search_documents(query: str):
    if not os.path.exists("faiss_index"): return {"answer": "System offline. Please upload a document first."}
    
    embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")
    vector_store = FAISS.load_local("faiss_index", embeddings, allow_dangerous_deserialization=True)
    
    llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", temperature=0.3)
    
    qa_chain = RetrievalQA.from_chain_type(llm=llm, retriever=vector_store.as_retriever(), return_source_documents=True)
    response = qa_chain.invoke({"query": query})
    
    return {"answer": response['result'], "citation": f"Source: Page {response['source_documents'][0].metadata.get('page', 'Unknown')}"}

@app.post("/cross-summary")
def generate_cross_summary(selection: DocumentSelection):
    all_docs = load_json_db("doc_store.json")
    selected_docs = [d for d in all_docs if d['filename'] in selection.filenames]
    
    if not selected_docs: return {"cross_summary": "No matching documents found in selection."}

    combined_text = ""
    for d in selected_docs: combined_text += f"- File: {d['filename']} ({d['category']}): {d['summary']}\n"
    
    llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", temperature=0.3)
    prompt = f"You are an Intelligence Analyst. Write a connection report based ONLY on these documents:\n{combined_text}\nIdentify relationships and combine information."
    
    response = llm.invoke(prompt)
    return {"cross_summary": response.content}




# import os
# import shutil
# import json
# from typing import List
# from fastapi import FastAPI, UploadFile, File
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# from dotenv import load_dotenv
# from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
# from langchain.chains import RetrievalQA
# from langchain_community.vectorstores import FAISS
# from ingest import ingest_file

# load_dotenv()

# app = FastAPI()

# # Enable CORS so the HTML file can talk to this API
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # --- DATA MODELS ---
# class DocumentSelection(BaseModel):
#     filenames: List[str]

# # --- HELPER ---
# def load_db():
#     if not os.path.exists("doc_store.json"):
#         return []
#     try:
#         with open("doc_store.json", "r") as f:
#             return json.load(f)
#     except:
#         return []

# # --- 1. LIST DOCUMENTS (For the Sidebar) ---
# @app.get("/documents")
# def list_documents():
#     """Returns list of available files WITH summaries."""
#     docs = load_db()
#     # WE ADDED "summary": d.get("summary", "") HERE 👇
#     return [
#         {"filename": d["filename"], "category": d["category"], "summary": d.get("summary", "No summary.")} 
#         for d in docs
#     ]



# # --- 2. UPLOAD ---
# @app.post("/upload")
# async def upload_document(file: UploadFile = File(...)):
#     temp_filename = f"temp_{file.filename}"
#     with open(temp_filename, "wb") as buffer:
#         shutil.copyfileobj(file.file, buffer)
    
#     result = ingest_file(temp_filename)
    
#     if os.path.exists(temp_filename):
#         os.remove(temp_filename)
        
#     return result

# # --- 3. SEARCH ---
# @app.get("/search")
# def search_documents(query: str):
#     if not os.path.exists("faiss_index"):
#         return {"answer": "System offline. Please upload a document first."}

#     embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")
#     vector_store = FAISS.load_local("faiss_index", embeddings, allow_dangerous_deserialization=True)
    
#     llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", temperature=0.3)
    
#     qa_chain = RetrievalQA.from_chain_type(
#         llm=llm,
#         retriever=vector_store.as_retriever(),
#         return_source_documents=True
#     )
    
#     response = qa_chain.invoke({"query": query})
#     return {
#         "answer": response['result'],
#         "citation": f"Source: Page {response['source_documents'][0].metadata.get('page', 'Unknown')}"
#     }

# # --- 4. CROSS SUMMARY ---
# @app.post("/cross-summary")
# def generate_cross_summary(selection: DocumentSelection):
#     all_docs = load_db()
#     if not all_docs:
#         return {"cross_summary": "Database empty."}

#     selected_docs = [d for d in all_docs if d['filename'] in selection.filenames]
    
#     if not selected_docs:
#         return {"cross_summary": "No matching documents found in selection."}

#     combined_text = ""
#     for d in selected_docs:
#         combined_text += f"- File: {d['filename']} ({d['category']}): {d['summary']}\n"
    
#     llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", temperature=0.3)
    
#     prompt = f"""
#     You are an Intelligence Analyst. Write a connection report based ONLY on these documents:
#     {combined_text}
#     Identify relationships and combine information.
#     """
    
#     response = llm.invoke(prompt)
#     return {"cross_summary": response.content}




