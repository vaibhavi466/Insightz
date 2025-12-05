import os
import shutil
from fastapi import FastAPI, UploadFile, File
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain.chains import RetrievalQA
from langchain_community.vectorstores import FAISS
from ingest import ingest_file

load_dotenv()

# --- THIS IS THE LINE THAT WAS MISSING ---
app = FastAPI() 
# -----------------------------------------

# --- UPLOAD ENDPOINT ---
@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    temp_filename = f"temp_{file.filename}"
    with open(temp_filename, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    result = ingest_file(temp_filename)
    
    # Cleanup
    if os.path.exists(temp_filename):
        os.remove(temp_filename)
        
    return {"message": result}

# --- SEARCH ENDPOINT ---
@app.get("/search")
def search_documents(query: str):
    if not os.path.exists("faiss_index"):
        return {"answer": "Please upload a document first."}

    # 1. Load the DB using Google Embeddings
    embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")
    vector_store = FAISS.load_local("faiss_index", embeddings, allow_dangerous_deserialization=True)
    
    # 2. Setup Google Gemini (The Brain)
    llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", temperature=0.3)
    
    
    # 3. Ask the question
    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        retriever=vector_store.as_retriever(),
        return_source_documents=True
    )
    
    response = qa_chain.invoke({"query": query})
    return {
        "answer": response['result'],
        "citation": f"Source: Page {response['source_documents'][0].metadata.get('page', 'Unknown')}"
    }