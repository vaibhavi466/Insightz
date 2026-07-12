import os
import re
import base64
import json
import logging
import mimetypes
import pdfplumber
import time
from typing import List
from dotenv import load_dotenv

load_dotenv()

from database import SessionLocal, DocumentMetadata

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain_core.messages import HumanMessage
from langchain.docstore.document import Document

logger = logging.getLogger("uvicorn.error")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))

def user_faiss_path(username: str) -> str:
    """Validate username to prevent path traversal and return user FAISS index absolute path."""
    if not re.match(r"^[a-zA-Z0-9_-]+$", username) or not (3 <= len(username) <= 32):
        raise ValueError("Invalid username character pattern or length constraint.")
    return os.path.join(BASE_DIR, f"faiss_index_{username}")

class PatchedGoogleGenerativeAIEmbeddings(GoogleGenerativeAIEmbeddings):
    output_dimensionality: int = EMBEDDING_DIM

    def __init__(self, **kwargs):
        out_dim = kwargs.pop("output_dimensionality", EMBEDDING_DIM)
        super().__init__(**kwargs)
        self.output_dimensionality = out_dim

    def _prepare_request(self, text: str, **kwargs):
        if "output_dimensionality" not in kwargs or kwargs["output_dimensionality"] is None:
            kwargs["output_dimensionality"] = self.output_dimensionality
        return super()._prepare_request(text, **kwargs)

    def embed_documents(self, texts: List[str], **kwargs) -> List[List[float]]:
        import time
        results = []
        batch_size = 20  # Safe batch size to avoid rate limits
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            retries = 5
            delay = 2.0
            for attempt in range(retries):
                try:
                    batch_results = super().embed_documents(batch, **kwargs)
                    results.extend(batch_results)
                    break
                except Exception as e:
                    err_str = str(e)
                    if ("429" in err_str or "ResourceExhausted" in err_str) and attempt < retries - 1:
                        time.sleep(delay)
                        delay *= 2
                    else:
                        raise e
            if i + batch_size < len(texts):
                time.sleep(1.0)
        return results

    def embed_query(self, text: str, **kwargs) -> List[float]:
        import time
        retries = 3
        delay = 2.0
        for attempt in range(retries):
            try:
                return super().embed_query(text, **kwargs)
            except Exception as e:
                err_str = str(e)
                if ("429" in err_str or "ResourceExhausted" in err_str) and attempt < retries - 1:
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise e

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")

RAG_CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "1500"))
RAG_CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "150"))

VALID_CATEGORIES = ["Resume", "Invoice", "Picture", "General"]

def _parse_category(raw: str) -> str:
    """Extract a known category from LLM output, falling back to General."""
    cleaned = raw.strip().strip("*").strip()
    for option in VALID_CATEGORIES:
        if option.lower() in cleaned.lower():
            return option
    return "General"

def process_image_with_gemini(image_path):
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0, max_retries=3)

    with open(image_path, "rb") as image_file:
        image_data = base64.b64encode(image_file.read()).decode("utf-8")

    # Detect actual MIME type instead of hardcoding image/jpeg
    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/jpeg"  # safe fallback

    message = HumanMessage(content=[
        {
            "type": "text",
            "text": (
                "Analyze this image. On the FIRST line, respond with ONLY one of these "
                "category words: Resume, Invoice, Picture, General.\n"
                "On the following lines, describe the image and transcribe any visible text."
            ),
        },
        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}},
    ])

    try:
        response = llm.invoke([message])
        lines = response.content.strip().split("\n", 1)
        category = _parse_category(lines[0]) if lines else "Picture"
        description = lines[1].strip() if len(lines) > 1 else response.content
        return category, description
    except Exception as e:
        logger.error("Image analysis failed for %s: %s", image_path, e)
        return "Picture", "Image analysis failed."

def extract_text_from_pdf(pdf_path):
    """Return a list of (page_number, page_text) tuples — one per PDF page."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            page_text = (page.extract_text() or "").strip()
            if page_text:
                pages.append((i, page_text))
    return pages

def save_metadata(filename, category, summary, username):
    db = SessionLocal()
    try:
        # Delete existing metadata for this file + user to prevent duplicates
        db.query(DocumentMetadata).filter(
            DocumentMetadata.filename == filename,
            DocumentMetadata.username == username
        ).delete()
        
        # Insert new record
        new_doc = DocumentMetadata(
            filename=filename,
            category=category,
            summary=summary,
            username=username
        )
        db.add(new_doc)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Failed to save metadata to database", exc_info=True, extra={"filename": filename, "username": username})
        raise e
    finally:
        db.close()

def ingest_file(file_path, username, original_filename=None):
    start_time = time.time()
    if original_filename:
        original_filename = os.path.basename(original_filename)
    else:
        base = os.path.basename(file_path)
        if base.startswith("temp_"):
            original_filename = base[5:]
        else:
            original_filename = base
    pages = []
    category = "General"
    summary = "No summary."
    
    try:
        if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            category, raw_text = process_image_with_gemini(file_path)
            pages = [Document(page_content=raw_text, metadata={"source": original_filename, "page": 1, "owner": username})]
            summary = raw_text[:200].replace("\n", " ") + "..."
            
        elif file_path.lower().endswith('.pdf'):
            pdf_pages = extract_text_from_pdf(file_path)
            if not pdf_pages: return {"error": "PDF is empty."}
            pages = [Document(page_content=text, metadata={"source": original_filename, "page": page_num, "owner": username})
                     for page_num, text in pdf_pages]
            raw_text = "\n".join(text for _, text in pdf_pages)
            
            # Use gemini-2.5-flash-lite (high free tier quota)
            llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0, max_retries=3)
            try:
                # Prompt strictly to avoid preamble in category
                prompt = (
                    "Classify this text into exactly one of these categories: Resume, Invoice, General.\n"
                    "Respond with ONLY the single category word. No extra text, markdown, or punctuation.\n\n"
                    f"Text sample:\n{raw_text[:500]}"
                )
                cat_raw = llm.invoke(prompt).content.strip()
                category = _parse_category(cat_raw)
                        
                # Ask Gemini to summarize concisely
                summary_prompt = (
                    "Summarize this text in one or two concise sentences.\n\n"
                    f"Text sample:\n{raw_text[:1000]}"
                )
                summary = llm.invoke(summary_prompt).content.strip().replace("\n", " ")
            except Exception as e:
                logger.warning("AI classification/summary failed: %s", e)
                category = "General"
                summary = raw_text[:200].replace("\n", " ") + "..."
        else: return {"error": "Unsupported format."}
    except Exception as e: return {"error": f"Error: {e}"}

    # Embeddings - chunk parameters tuneable via environment variables
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=RAG_CHUNK_SIZE, chunk_overlap=RAG_CHUNK_OVERLAP)
    chunks = text_splitter.split_documents(pages)
    
    try:
        embeddings = PatchedGoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL, output_dimensionality=EMBEDDING_DIM, max_retries=3)
        new_db = FAISS.from_documents(chunks, embeddings)
        
        user_db_path = user_faiss_path(username)
        if os.path.exists(user_db_path):
            try:
                old_db = FAISS.load_local(user_db_path, embeddings, allow_dangerous_deserialization=True)
                
                # Delete existing chunks for this specific document and owner to prevent duplicate stale vectors
                ids_to_delete = [
                    doc_id for doc_id, doc in old_db.docstore._dict.items()
                    if doc.metadata.get("source") == original_filename and doc.metadata.get("owner") == username
                ]
                if ids_to_delete:
                    old_db.delete(ids_to_delete)
                    
                old_db.merge_from(new_db)
                old_db.save_local(user_db_path)
            except Exception as e:
                return {"error": f"Failed to merge into existing index: {e}. Existing index was NOT modified."}
        else:
            new_db.save_local(user_db_path)
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "ResourceExhausted" in error_msg:
            return {"error": "AI Rate Limit Exceeded: The Google Gemini API is currently busy. Please try uploading again in a minute."}
        return {"error": f"Embedding error: {error_msg}"}
    
    save_metadata(original_filename, category, summary, username)
    latency_ms = int((time.time() - start_time) * 1000)
    logger.info(
        "Document ingestion completed successfully", 
        extra={
            "operation": "ingestion",
            "username": username,
            "filename": original_filename,
            "category": category,
            "latency_ms": latency_ms
        }
    )
    return {"status": "Success", "category": category, "summary": summary}
