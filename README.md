# INSIGHTZ : Poject Overview

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



## Working Features 


## Error Handling and reliability features

## AI/ML integration details

## Future Improvements




