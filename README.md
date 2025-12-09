# INSIGHTZ : Yellow Ranger's doc-sage intel console

Insightz helps you find information in your documents without doing the heavy lifting. Instead of reading through long, complex reports yourself, you upload them to the system. It reads them for you, so you can just ask it questions and get instant, accurate answers backed by proof from the original file.

A secure, multi-user RAG (Retrieval-Augmented Generation) application that transforms unstructured documents (PDFs, Images, Notes) into a searchable knowledge base using Generative AI.

## Problem Statement: 4

## Team Members

1. **PUSHPALATA** (20232028) - (https://github.com/Pushpalata-S)
2. **ARUSHI KHARE** (20232010) - (https://github.com/Arushikhare6)
3. **VAIBHAVI** (20232055) - (https://github.com/vaibhavi466)

## Tech Stack

* **Frontend:** HTML,React.js(Vite)
* **Backend:** Python (FastAPI)
* **AI Engine:** OpenAI (GEMINI-FLASH-LATEST)
* **Orchestration:** LangChain
* **Vector Database:** Pinecone,FAISS
* **File Processing**	Pdfplumber

## Features Implemented
* Multi-Modal Ingestion: Processes PDFs, text, and images with OCR.
* Semantic Search: Answers natural-language questions from document content.
* Cross-Document Summary: Merges insights across multiple files.
* Page-Wise Breakdown: Summarizes PDFs page by page.
* Data Isolation: Each user accesses only their own files securely.
* Resilient Mode: Uses cached responses if the AI API rate-limits.

## System Architecture

Phase A — Ingestion (Write):
User uploads a file → PDFs parsed with pdfplumber → Images analyzed via Gemini Vision → Text is chunked (LangChain) → Chunks embedded using text-embedding-004 → Vectors stored in FAISS and metadata (filename, owner) saved in doc_store.json.

Phase B — Retrieval (Read):
User enters a query → Query is embedded and matched against FAISS (top 3–5 chunks) → Retrieved context is inserted into an augmented prompt → Gemini-Flash-Latest generates the final answer.
## API Documentation

## SetUp Instructions
* **Step A: Create the Virtual Environment:** python -m venv venv --> .\venv\Scripts\activate
* **Step B: Install Dependencies:** Create a file named  backend/requirements.txt and paste this: fastapi
uvicorn
python-multipart
python-jose[cryptography]
passlib[bcrypt]
python-dotenv
langchain
langchain-google-genai
langchain-community
faiss-cpu
pdfplumber
pypdf
--> run pip install -r requirements.txt
* **Step C: Configure API Keys:** Create a file named backend/.env & paste your key: GOOGLE_API_KEY=AIzaSy...<YOUR_KEY_HERE>
* **Step D: Start the Server:** run uvicorn main:app --reload on backend
* **Step E: Install Node Libraries:** run npm install-->npm run dev on frontend
* **Step F: How to Use (Demo Flow):** Go to http://localhost:5173

## Working Features 
![Alt Text](<img width="1598" height="842" alt="Screenshot 2025-12-09 093510" src="https://github.com/user-attachments/assets/d06201e6-9549-4f1b-b6ee-bc536465612c" />)




## Error Handling and reliability features
* **Resilient Ingestion:** Uses a Zero-Crash policy—if AI classification fails, it safely falls back to rule-based labeling (e.g., “General” or “Picture”) so every file is always saved.
* **Optimized Model Selection (gemini-flash-latest):** While the Free Tier imposes strict Requests Per Minute (RPM) limits, the model's speed ensures single transactions complete instantly, maximizing the usable throughput.


## AI/ML integration details
* RAG Pipeline: Chunking → Embeddings (text-embedding-004) → FAISS for semantic search.
* LLM Reasoning: Gemini-Flash-Latest for summaries, Q&A, and cross-document insights
* Zero-Shot Classification: Auto-detects document type using LLM (no training needed).
* Vision OCR: Gemini Vision extracts text & meaning from images.
  
## Future Improvements
* **Asynchronous Processing:** Allow users to upload massive files (100+ pages) without the browser request timing out while the server processes the data in the background.


