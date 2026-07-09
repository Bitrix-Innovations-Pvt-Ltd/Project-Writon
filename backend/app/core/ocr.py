import io
import pytesseract
from PIL import Image
import fitz  # PyMuPDF
import platform
import base64
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), ".env"))
openrouter_key = os.getenv("OPENROUTER_API_KEY")

# For Windows development, user might need to specify tesseract path if it's not in PATH.
if platform.system() == "Windows":
    pass

def extract_text_with_llm(file_bytes: bytes, mime_type: str) -> str:
    if not openrouter_key:
        return ""
    try:
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key)
        base64_image = base64.b64encode(file_bytes).decode('utf-8')
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all readable text from this image exactly as it appears. If there is no text, return empty."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}"
                            }
                        }
                    ]
                }
            ]
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        print(f"LLM OCR Fallback Failed: {str(e)}")
        return ""

def extract_text_from_bytes(file_bytes: bytes, filename: str) -> str:
    """
    Extracts text from an image or PDF (first 5 pages max).
    Uses PyMuPDF (fitz) for PDFs.
    Uses Tesseract for images, falling back to LLM Vision API if Tesseract fails/missing.
    """
    ext = filename.lower().split('.')[-1]
    extracted_text = ""
    
    try:
        if ext == 'pdf':
            # Open PDF from bytes using PyMuPDF
            pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
            num_pages = min(5, len(pdf_document))
            
            page_tasks = []
            for page_num in range(num_pages):
                page = pdf_document.load_page(page_num)
                # Try to extract digital text first
                text = page.get_text()
                
                if not text.strip():
                    # Fallback to LLM Vision for scanned PDF pages
                    try:
                        pix = page.get_pixmap()
                        img_bytes = pix.tobytes("png")
                        page_tasks.append({"page_num": page_num, "type": "image", "bytes": img_bytes})
                    except Exception as e:
                        print(f"Failed to get pixmap on PDF page {page_num}: {str(e)}")
                        page_tasks.append({"page_num": page_num, "type": "text", "text": ""})
                else:
                    page_tasks.append({"page_num": page_num, "type": "text", "text": text})
                    
            pdf_document.close()
            
            import concurrent.futures
            
            def run_llm_for_task(task):
                if task["type"] == "text":
                    return task["text"]
                try:
                    return extract_text_with_llm(task["bytes"], "image/png")
                except Exception as e:
                    print(f"Failed LLM Vision on page {task['page_num']}: {e}")
                    return ""
                    
            # Run OpenRouter LLM Vision concurrently for all scanned pages
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                results = list(executor.map(run_llm_for_task, page_tasks))
                
            for idx, res_text in enumerate(results):
                extracted_text += f"\n--- Page {page_tasks[idx]['page_num']+1} ---\n{res_text}"
        elif ext in ['png', 'jpg', 'jpeg', 'tiff', 'bmp']:
            # Use LLM Vision (OpenRouter) as primary for image OCR
            mime_type = f"image/{'jpeg' if ext in ['jpg', 'jpeg'] else ext}"
            try:
                extracted_text = extract_text_with_llm(file_bytes, mime_type)
                if not extracted_text.strip():
                    raise Exception("Empty result from LLM Vision")
            except Exception as e:
                print(f"LLM Vision OCR failed ({str(e)}), falling back to Tesseract.")
                try:
                    image = Image.open(io.BytesIO(file_bytes))
                    text = pytesseract.image_to_string(image)
                    extracted_text = text
                except Exception as tesseract_e:
                    print(f"Tesseract OCR also failed: {str(tesseract_e)}")
                    extracted_text = ""
        else:
            extracted_text = "Unsupported file type for OCR."
            
    except Exception as e:
        print(f"Extraction Failed for {filename}: {str(e)}")
        extracted_text = f"[Extraction Failed. Error: {str(e)}]"

    return extracted_text.strip()
