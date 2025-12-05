import os
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS

# Load environment variables
load_dotenv()

def ingest_file(file_path):
    # 1. Load PDF
    try:
        loader = PyPDFLoader(file_path)
        pages = loader.load()
    except Exception as e:
        return f"Error loading PDF: {e}"

    # 2. Split Text
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    chunks = text_splitter.split_documents(pages)

    if not chunks:
        return "Error: No text found in PDF."

    # 3. Create Embeddings (Using Google)
    print("Creating embeddings... this might take a moment.")
    embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")
    
    # 4. Save to Vector DB
    vector_store = FAISS.from_documents(chunks, embeddings)
    vector_store.save_local("faiss_index")
    
    return f"Success! Processed {len(chunks)} chunks."