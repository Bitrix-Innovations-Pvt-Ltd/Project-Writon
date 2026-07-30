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

# ── PDF page limits ──────────────────────────────────────────────────────────
# Digital-text pages and scanned pages have completely different costs, so they
# get separate budgets rather than one shared cap:
#
#   * page.get_text() is local, free and fast — a 200-page digital judgment
#     extracts in well under a second. Only a high safety bound applies.
#   * A scanned page costs one gpt-4o-mini vision call. Upload is synchronous
#     (the advocate waits on the request), so this is the limit that actually
#     matters for both latency and spend.
#
# Uploads are capped at 5 MB (api/v1/uploads.py), which bounds the worst case.
# Downstream prompt budgets live in core/uploaded_docs.py and core/extraction.py,
# so a long document cannot flood the drafting prompt.
MAX_PDF_PAGES = int(os.getenv("OCR_MAX_PDF_PAGES", "300"))
MAX_VISION_PAGES = int(os.getenv("OCR_MAX_VISION_PAGES", "25"))
VISION_WORKERS = int(os.getenv("OCR_VISION_WORKERS", "8"))

# Scanned pages are rendered at this zoom before being sent to the vision model.
# PyMuPDF's default is 72 DPI, at which scanned Indian court orders are often
# barely legible and OCR quality suffers badly; 2x ≈ 144 DPI reads reliably.
VISION_ZOOM = float(os.getenv("OCR_VISION_ZOOM", "2.0"))

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

def _extract_pdf(file_bytes: bytes) -> str:
    """Extract text from every page of a PDF, within the budgets above.

    Digital text is taken from all pages. Scanned pages are rendered and sent to
    the vision model up to MAX_VISION_PAGES; any beyond that are marked in place
    so the gap is visible to the reader and to the drafting prompt rather than
    silently swallowed.
    """
    pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        total_pages = len(pdf_document)
        num_pages = min(MAX_PDF_PAGES, total_pages)

        page_tasks = []
        vision_budget = MAX_VISION_PAGES
        skipped_scanned = []

        for page_num in range(num_pages):
            page = pdf_document.load_page(page_num)
            text = page.get_text()

            if text.strip():
                page_tasks.append({"page_num": page_num, "type": "text", "text": text})
                continue

            # Scanned page — needs the vision model.
            if vision_budget <= 0:
                skipped_scanned.append(page_num + 1)
                page_tasks.append({
                    "page_num": page_num,
                    "type": "text",
                    "text": "[Scanned page not read - image OCR limit reached.]",
                })
                continue

            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(VISION_ZOOM, VISION_ZOOM))
                page_tasks.append({
                    "page_num": page_num, "type": "image", "bytes": pix.tobytes("png"),
                })
                vision_budget -= 1
            except Exception as e:
                print(f"Failed to get pixmap on PDF page {page_num}: {str(e)}")
                page_tasks.append({"page_num": page_num, "type": "text", "text": ""})
    finally:
        pdf_document.close()

    # Only scanned pages need the thread pool; digital text is already in hand.
    image_tasks = [t for t in page_tasks if t["type"] == "image"]
    if image_tasks:
        import concurrent.futures

        def run_llm_for_task(task):
            try:
                return extract_text_with_llm(task["bytes"], "image/png")
            except Exception as e:
                print(f"Failed LLM Vision on page {task['page_num']}: {e}")
                return ""

        workers = max(1, min(VISION_WORKERS, len(image_tasks)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            for task, result in zip(image_tasks, executor.map(run_llm_for_task, image_tasks)):
                task["text"] = result

    parts = [
        f"\n--- Page {t['page_num'] + 1} ---\n{t.get('text', '')}"
        for t in page_tasks
    ]

    notices = []
    if total_pages > num_pages:
        notices.append(
            f"Only the first {num_pages} of {total_pages} pages were read "
            f"(page limit)."
        )
    if skipped_scanned:
        preview = ", ".join(str(p) for p in skipped_scanned[:10])
        more = f" and {len(skipped_scanned) - 10} more" if len(skipped_scanned) > 10 else ""
        notices.append(
            f"{len(skipped_scanned)} scanned page(s) were not read by image OCR "
            f"(pages {preview}{more})."
        )
    if notices:
        parts.append("\n\n[NOTE: " + " ".join(notices) + "]")

    return "".join(parts)


def extract_text_from_bytes(file_bytes: bytes, filename: str) -> str:
    """
    Extracts text from an image, PDF or DOCX.

    PDFs: all pages of digital text (up to MAX_PDF_PAGES); scanned pages go to
    LLM Vision up to MAX_VISION_PAGES.
    Images: LLM Vision, falling back to Tesseract if it fails or is missing.
    """
    ext = filename.lower().split('.')[-1]
    extracted_text = ""

    try:
        if ext == 'pdf':
            extracted_text = _extract_pdf(file_bytes)
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
        elif ext == 'docx':
            import docx
            try:
                doc = docx.Document(io.BytesIO(file_bytes))
                extracted_text = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
            except Exception as e:
                print(f"Failed to extract text from DOCX: {str(e)}")
                extracted_text = ""
        else:
            extracted_text = "Unsupported file type for OCR."
            
    except Exception as e:
        print(f"Extraction Failed for {filename}: {str(e)}")
        extracted_text = f"[Extraction Failed. Error: {str(e)}]"

    return extracted_text.strip()
