import os
import base64
import json
import pdfplumber
from dotenv import load_dotenv
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain_core.messages import HumanMessage
from langchain.docstore.document import Document

load_dotenv()

DB_FILE = "doc_store.json"

def process_image_with_gemini(image_path):
    # Use gemini-flash-latest as requested
    llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", temperature=0)
    
    with open(image_path, "rb") as image_file:
        image_data = base64.b64encode(image_file.read()).decode("utf-8")
        
    message = HumanMessage(content=[
        {"type": "text", "text": "Describe this image and transcribe any text."},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
    ])
    
    try:
        response = llm.invoke([message])
        return "Picture", response.content
    except Exception:
        return "Picture", "Image analysis failed."

def extract_text_from_pdf(pdf_path):
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text += (page.extract_text() or "") + "\n"
    return text

def save_metadata(filename, category, summary):
    data = []
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f: data = json.load(f)
        except: pass
    
    data = [d for d in data if d['filename'] != filename]
    data.append({"filename": filename, "category": category, "summary": summary})
    
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=4)

def ingest_file(file_path):
    original_filename = os.path.basename(file_path).replace("temp_", "")
    pages = []
    category = "General"
    summary = "No summary."
    
    try:
        if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            category, raw_text = process_image_with_gemini(file_path)
            pages = [Document(page_content=raw_text, metadata={"source": file_path, "page": 1})]
            summary = raw_text[:200] + "..."
            
        elif file_path.lower().endswith('.pdf'):
            raw_text = extract_text_from_pdf(file_path)
            if not raw_text.strip(): return {"error": "PDF is empty."}
            pages = [Document(page_content=raw_text, metadata={"source": file_path, "page": 1})]
            
            # Use gemini-flash-latest
            llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", temperature=0)
            try:
                category = llm.invoke(f"Classify: [Resume, Invoice, General]. Text: {raw_text[:500]}").content.strip()
                summary = raw_text[:200].replace("\n", " ") + "..."
            except: 
                category = "General"
        else: return {"error": "Unsupported format."}
    except Exception as e: return {"error": f"Error: {e}"}

    # Embeddings
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    chunks = text_splitter.split_documents(pages)
    
    embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")
    new_db = FAISS.from_documents(chunks, embeddings)
    
    if os.path.exists("faiss_index"):
        try:
            old_db = FAISS.load_local("faiss_index", embeddings, allow_dangerous_deserialization=True)
            old_db.merge_from(new_db)
            old_db.save_local("faiss_index")
        except: new_db.save_local("faiss_index")
    else: new_db.save_local("faiss_index")
    
    save_metadata(original_filename, category, summary)
    return {"status": "Success", "category": category, "summary": summary}


# import os
# import base64
# import pdfplumber
# from dotenv import load_dotenv
# from langchain.text_splitter import RecursiveCharacterTextSplitter
# from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
# from langchain_community.vectorstores import FAISS
# from langchain_core.messages import HumanMessage
# from langchain.docstore.document import Document

# load_dotenv()

# def process_image_with_gemini(image_path):
#     print("Processing image...")
#     with open(image_path, "rb") as image_file:
#         image_data = base64.b64encode(image_file.read()).decode("utf-8")
    
#     llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", temperature=0)
    
#     prompt = """
#     Analyze this image. 
#     Step 1: Classify it: [Resume, Invoice, Email, Application, Form, Picture].
#     Step 2: Provide content.
#     Output format:
#     Category: [Your Category]
#     Content: [Your Text]
#     """
#     message = HumanMessage(content=[{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}])
#     try:
#         response = llm.invoke([message])
#         result_text = response.content
#         category = "General"
#         content = result_text
#         lines = result_text.split('\n')
#         for line in lines:
#             if line.startswith("Category:"): category = line.replace("Category:", "").strip()
#             elif line.startswith("Content:"): content = result_text.split("Content:", 1)[1].strip(); break
#         return category, content
#     except:
#         return "General", "Error reading image."

# def extract_text_from_pdf(pdf_path):
#     text = ""
#     with pdfplumber.open(pdf_path) as pdf:
#         for page in pdf.pages:
#             text += (page.extract_text() or "") + "\n"
#     return text

# def ingest_file(file_path):
#     original_filename = os.path.basename(file_path).replace("temp_", "")
#     pages = []
#     category = "General"
#     summary = "No summary."
    
#     try:
#         if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
#             category, raw_text = process_image_with_gemini(file_path)
#             pages = [Document(page_content=raw_text, metadata={"source": file_path, "page": 1})]
#             summary = raw_text[:200].replace("\n", " ") + "..."
#         elif file_path.lower().endswith('.pdf'):
#             raw_text = extract_text_from_pdf(file_path)
#             if not raw_text.strip(): return {"error": "PDF is empty."}
#             pages = [Document(page_content=raw_text, metadata={"source": file_path, "page": 1})]
#             llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0)
#             category = llm.invoke(f"Classify: [Resume, Invoice, Email, Application, Form, General]. Text: {raw_text[:500]}").content.strip()
#             summary = raw_text[:200].replace("\n", " ") + "..."
#         else: return {"error": "Unsupported format."}
#     except Exception as e: return {"error": f"Error: {e}"}

#     # Vector Logic
#     text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
#     chunks = text_splitter.split_documents(pages)
#     if not chunks: return {"error": "No content."}

#     print("Creating embeddings...")
#     embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")
#     new_db = FAISS.from_documents(chunks, embeddings)
    
#     # Merge Logic (Cumulative Memory)
#     if os.path.exists("faiss_index"):
#         try:
#             old_db = FAISS.load_local("faiss_index", embeddings, allow_dangerous_deserialization=True)
#             old_db.merge_from(new_db)
#             old_db.save_local("faiss_index")
#         except: new_db.save_local("faiss_index")
#     else: new_db.save_local("faiss_index")
    
#     # Return data to main.py (It will handle MongoDB saving)
#     return {
#         "status": "Success",
#         "filename": original_filename,
#         "category": category,
#         "summary": summary
#     }



# import os
# import base64
# import json
# import pdfplumber
# from dotenv import load_dotenv
# from langchain.text_splitter import RecursiveCharacterTextSplitter
# from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
# from langchain_community.vectorstores import FAISS
# from langchain_core.messages import HumanMessage
# from langchain.docstore.document import Document

# load_dotenv()

# DB_FILE = "doc_store.json"

# def extract_text_from_image(image_path):
#     print("Image detected. Asking Gemini to transcribe...")
#     with open(image_path, "rb") as image_file:
#         image_data = base64.b64encode(image_file.read()).decode("utf-8")
    
#     llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", temperature=0)
#     message = HumanMessage(
#         content=[
#             {"type": "text", "text": "Transcribe the text from this image exactly."},
#             {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
#         ]
#     )
#     response = llm.invoke([message])
#     return response.content

# def extract_text_from_pdf(pdf_path):
#     text = ""
#     with pdfplumber.open(pdf_path) as pdf:
#         for page in pdf.pages:
#             page_text = page.extract_text()
#             if page_text:
#                 text += page_text + "\n"
#     return text

# def save_metadata(filename, category, summary):
#     data = []
#     if os.path.exists(DB_FILE):
#         try:
#             with open(DB_FILE, "r") as f:
#                 data = json.load(f)
#         except:
#             data = []
    
#     data = [d for d in data if d['filename'] != filename]
    
#     data.append({
#         "filename": filename,
#         "category": category,
#         "summary": summary
#     })
    
#     with open(DB_FILE, "w") as f:
#         json.dump(data, f, indent=4)

# def ingest_file(file_path):
#     original_filename = os.path.basename(file_path).replace("temp_", "")
#     pages = []
    
#     try:
#         if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
#             raw_text = extract_text_from_image(file_path)
#             pages = [Document(page_content=raw_text, metadata={"source": file_path, "page": 1})]
            
#         elif file_path.lower().endswith('.pdf'):
#             raw_text = extract_text_from_pdf(file_path)
#             if not raw_text.strip():
#                 return {"error": "PDF is scanned or empty."}
#             pages = [Document(page_content=raw_text, metadata={"source": file_path, "page": 1})]
            
#         else:
#             return {"error": "Unsupported file format."}
            
#     except Exception as e:
#         return {"error": f"Error loading file: {e}"}

#     text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
#     chunks = text_splitter.split_documents(pages)

#     if not chunks:
#         return {"error": "No text extracted."}

#     # --- AI ANALYSIS ---
#     print("Analyzing document...")
#     first_page_content = pages[0].page_content[:3000]
#     llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", temperature=0)

#     # 1. Categorize
#     cat_prompt = f"""
#     Classify this text into one of: [Resume, Invoice, Email, Application, Form, General].
#     Text: "{first_page_content}"
#     Return ONLY the category name.
#     """
#     try:
#         category = llm.invoke(cat_prompt).content.strip()
#     except:
#         category = "General"

#     # 2. Summarize
#     sum_prompt = f"""
#     Summarize this text in 2 concise sentences.
#     Text: "{first_page_content}"
#     """
#     try:
#         summary = llm.invoke(sum_prompt).content.strip()
#     except:
#         summary = "No summary available."

#     # Save Metadata
#     save_metadata(original_filename, category, summary)

#     # --- 3. EMBED & MERGE (CRITICAL FIX) ---
#     print("Creating embeddings...")
#     embeddings = GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")
    
#     # Create the NEW database for just this file
#     new_db = FAISS.from_documents(chunks, embeddings)
    
#     # Check if OLD database exists
#     if os.path.exists("faiss_index"):
#         try:
#             print("Merging with existing database...")
#             old_db = FAISS.load_local("faiss_index", embeddings, allow_dangerous_deserialization=True)
#             old_db.merge_from(new_db)
#             old_db.save_local("faiss_index")
#         except Exception as e:
#             print(f"Error merging DB: {e}. Overwriting instead.")
#             new_db.save_local("faiss_index")
#     else:
#         print("Creating new database...")
#         new_db.save_local("faiss_index")
    
#     return {
#         "status": "Success",
#         "category": category,
#         "summary": summary
#     }


