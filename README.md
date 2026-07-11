# INSIGHTZ 

Insightz helps you find information in your documents without doing the heavy lifting. Instead of reading through long, complex reports yourself, you upload them to the system. It reads them for you, so you can just ask it questions and get instant, accurate answers backed by proof from the original file.

A secure, multi-user RAG (Retrieval-Augmented Generation) application that transforms unstructured documents (PDFs, Images, Notes) into a searchable knowledge base using Generative AI.

## Problem Statement: 4
Yellow Ranger's doc-sage intel console

## Team Members

1. **PUSHPALATA** (20232028) - (https://github.com/Pushpalata-S)
2. **ARUSHI KHARE** (20232010) - (https://github.com/Arushikhare6)
3. **VAIBHAVI AGRAWAL** (20232055) - (https://github.com/vaibhavi466)

## Tech Stack

* **Frontend:** Vanilla HTML / JavaScript (served as static files by FastAPI)
* **Backend:** Python (FastAPI)
* **AI Engine:** Google Gemini (`gemini-2.5-flash-lite` for generation, `gemini-embedding-001` for embeddings)
* **Orchestration:** LangChain
* **Vector Database:** FAISS (per-user local indexes)
* **File Processing:** pdfplumber (PDFs), Gemini Vision (images)

## Features Implemented
* **Multi-Modal Ingestion:** Processes PDFs (page-by-page) and images (PNG, JPG, WebP) with Gemini Vision OCR.
* **Semantic Search:** Answers natural-language questions from document content with page-level citations.
* **Cross-Document Summary:** Merges insights across multiple selected files into a connection report.
* **AI Classification:** Auto-categorizes documents as Resume, Invoice, Picture, or General using zero-shot LLM classification.
* **Data Isolation:** Each user has their own FAISS index and document store — all endpoints enforce per-user ownership.
* **JWT Authentication:** Secure signup/login with bcrypt password hashing, signed JWTs with 24-hour expiry.
* **Resilient Mode:** Exponential-backoff retry logic on all embedding and LLM calls protects against API rate-limits (429 / ResourceExhausted). Classification failures gracefully fall back to rule-based labeling.
* **Upload Security:** Path-traversal protection (UUID temp filenames), file-type allow-list, and configurable size limits (default 20 MB).

## System Architecture

**Phase A — Ingestion (Write):**
User uploads a file → PDFs parsed page-by-page with pdfplumber → Images analyzed via Gemini Vision → Text is chunked (LangChain `RecursiveCharacterTextSplitter`) → Chunks embedded using `gemini-embedding-001` (configurable via `EMBEDDING_MODEL` env var) → Vectors stored in a per-user FAISS index and metadata (filename, category, summary, owner) saved in `doc_store.json`.

**Phase B — Retrieval (Read):**
User enters a query → Query is embedded and matched against the user's FAISS index → Retrieved context is inserted into an augmented prompt → `gemini-2.5-flash-lite` generates the final answer with source page citations.

## API Documentation
* **Generative Model:** `gemini-2.5-flash-lite`
* **Embedding Model:** `gemini-embedding-001` (configurable via `EMBEDDING_MODEL` env var)
* **Integration Library:** LangChain Google GenAI

## Setup Instructions

### Prerequisites
* Python 3.10+
* A Google Gemini API key ([Get one here](https://aistudio.google.com/apikey))

### Step 1: Clone & Enter the Project
```bash
git clone <repo-url>
cd Insightz
```

### Step 2: Create a Virtual Environment
```bash
cd backend
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables
```bash
cp .env.example .env
# Edit .env and set your GOOGLE_API_KEY
```

Available environment variables (see `.env.example`):
| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_API_KEY` | *(required)* | Your Gemini API key |
| `JWT_SECRET_KEY` | `insightz-super-...` | Secret for signing JWTs |
| `ALLOWED_ORIGINS` | `http://localhost:5173,...` | Comma-separated CORS origins |
| `MAX_UPLOAD_SIZE_MB` | `20` | Maximum upload file size in MB |
| `EMBEDDING_MODEL` | `models/gemini-embedding-001` | Embedding model identifier |

### Step 5: Start the Server
```bash
uvicorn main:app --reload
```

### Step 6: Open the App
Navigate to **http://127.0.0.1:8000** — the frontend is served directly by FastAPI (no separate Node.js/npm step needed).

## Working Features 
* Login Signup <img width="1781" height="889" alt="Screenshot 2025-12-09 102842" src="https://github.com/user-attachments/assets/d1b8ec4b-0dfc-475f-9b5a-01fae4a18c2b" />
* Semantic Search <img width="1183" height="420" alt="Screenshot 2025-12-09 101813" src="https://github.com/user-attachments/assets/ff99e080-0cc7-4a9c-a34a-a4fa798a0bd8" />
* Quick & deep summary <img width="754" height="635" alt="Screenshot 2025-12-09 015958" src="https://github.com/user-attachments/assets/50549e50-5dc6-49c0-947e-c74963ef1d2a" />
* Page Wise Summary <img width="1598" height="842" alt="Screenshot 2025-12-09 093510" src="https://github.com/user-attachments/assets/12d5dabb-c7de-468c-a8a7-2245340e884e" />
* Connection Report <img width="726" height="467" alt="Screenshot 2025-12-09 103048" src="https://github.com/user-attachments/assets/0e93791d-e360-46ce-a4fc-9d986cdb11c6" />

## Error Handling and Reliability Features

* **Resilient Ingestion:** Zero-crash policy — if AI classification fails, it safely falls back to rule-based labeling ("General") so every file is always saved.
* **Exponential Backoff:** All embedding and LLM API calls retry with exponential backoff on 429 / ResourceExhausted errors.
* **Atomic Writes:** JSON data files (`users.json`, `doc_store.json`) are written atomically via temp-file + `os.replace()` to prevent corruption on crashes.
* **Safe Merge:** If merging new vectors into an existing FAISS index fails, the existing index is left untouched and an explicit error is returned.

## AI/ML Integration Details
* **RAG Pipeline:** Chunking → Embeddings (`gemini-embedding-001`) → FAISS for semantic search.
* **LLM Reasoning:** `gemini-2.5-flash-lite` for summaries, Q&A, and cross-document insights.
* **Zero-Shot Classification:** Auto-detects document type (Resume, Invoice, Picture, General) using LLM — no training data needed.
* **Vision OCR:** Gemini Vision extracts text & meaning from images with proper MIME type detection.

## Future Improvements
* **Deployment:** Deploy to a cloud platform for production use.
* **Persistent Vector Store:** Migrate from local FAISS files to a managed vector database for scalability.
* **Background Processing:** Process large uploads asynchronously with progress tracking.
