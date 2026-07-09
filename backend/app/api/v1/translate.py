"""
api/v1/translate.py — Legal document OCR + translation feature.

Ported from the hindi-legal-demo proof-of-concept.
Follows the same SSE streaming pattern used in drafting.py.
Supports images (jpg/png) and PDFs (converted to images via PyMuPDF).
Auto-detects document language; if already English, no translation needed.
Includes a PDF export endpoint for the translated text.
Includes a voice recording -> transcription -> translation endpoint.
"""

import json
import re
import io
import base64

import fitz  # PyMuPDF
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

from app.core.rag import get_openrouter_client

router = APIRouter(prefix="/translate", tags=["translate"])

PRIMARY_MODEL = "google/gemini-2.5-flash"
FALLBACK_MODEL = "google/gemini-3-flash-preview"
MAX_PDF_PAGES = 15
PDF_DPI = 150

WHISPER_MODEL = "openai/whisper-large-v3-turbo"
TRANSLATE_MODEL = "openai/gpt-4o-mini"

OCR_TRANSLATE_PROMPT = """You are a legal document OCR and translation assistant.
Given the image(s) of a legal document, do the following in one response:

1. Detect the document's original language.
2. Transcribe the text exactly as it appears in its original language (original_transcription).
3. If the original language is NOT English, translate it into formal English suitable for legal use (english_translation).
   If the original language IS already English, set english_translation to the same text as original_transcription (no translation needed).
4. Preserve To/From blocks, subject lines, numbered lists, and signature blocks.
5. If multiple images are provided, treat them as pages of the same document, in order.

Respond ONLY with valid JSON in this exact shape:
{"detected_language": "...", "original_transcription": "...", "english_translation": "..."}
"""

VOICE_TRANSLATE_PROMPT = """Translate the following Hindi legal text into clear, accurate English.
Preserve all names, dates, IPC/BNS/CrPC/BNSS section references, and case numbers exactly as given.
Return only the translated English text, nothing else.

Text to translate:
{text}
"""


def _clean_and_parse_json(raw: str) -> dict:
    text = raw.strip()

    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    def _escape_control_chars(match: re.Match) -> str:
        inner = match.group(0)
        inner = inner.replace("\n", "\\n").replace("\r", "").replace("\t", "\\t")
        return inner

    repaired = re.sub(r'"(?:[^"\\]|\\.)*"', _escape_control_chars, text, flags=re.DOTALL)
    return json.loads(repaired)


def _pdf_to_images_b64(file_bytes: bytes) -> list[str]:
    images_b64 = []
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    zoom = PDF_DPI / 72
    matrix = fitz.Matrix(zoom, zoom)

    for page_number in range(min(len(doc), MAX_PDF_PAGES)):
        page = doc[page_number]
        pix = page.get_pixmap(matrix=matrix)
        png_bytes = pix.tobytes("png")
        images_b64.append(base64.b64encode(png_bytes).decode("utf-8"))

    doc.close()
    return images_b64


async def _call_vision_model(model: str, images_b64: list[str]) -> dict:
    client = get_openrouter_client()

    content = [{"type": "text", "text": OCR_TRANSLATE_PROMPT}]
    for img_b64 in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
        })

    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        temperature=0.1,
        max_tokens=4096,
    )
    raw_text = response.choices[0].message.content
    return _clean_and_parse_json(raw_text)


async def _process_stream(file_bytes: bytes, mime_type: str, filename: str):
    yield "event: log\ndata: Starting OCR and translation...\n\n"

    is_pdf = mime_type == "application/pdf" or filename.lower().endswith(".pdf")

    try:
        if is_pdf:
            yield "event: log\ndata: Converting PDF pages to images...\n\n"
            images_b64 = _pdf_to_images_b64(file_bytes)
            if not images_b64:
                yield "event: error\ndata: \"Could not extract any pages from PDF\"\n\n"
                return
        else:
            images_b64 = [base64.b64encode(file_bytes).decode("utf-8")]
    except Exception as e:
        yield f"event: error\ndata: {json.dumps(str(e))}\n\n"
        return

    result = None
    engine_used = None

    try:
        yield f"event: log\ndata: Trying {PRIMARY_MODEL}...\n\n"
        result = await _call_vision_model(PRIMARY_MODEL, images_b64)
        engine_used = PRIMARY_MODEL
    except Exception as e:
        print(f"[translate] Primary model failed: {e}")
        yield f"event: log\ndata: Primary model failed ({str(e)}), trying fallback...\n\n"
        try:
            result = await _call_vision_model(FALLBACK_MODEL, images_b64)
            engine_used = FALLBACK_MODEL
        except Exception as e2:
            print(f"[translate] Fallback model failed: {e2}")
            yield f"event: error\ndata: {json.dumps(str(e2))}\n\n"
            return

    yield f"event: engine\ndata: {json.dumps(engine_used)}\n\n"
    yield f"event: language\ndata: {json.dumps(result.get('detected_language', 'unknown'))}\n\n"
    yield f"event: ocr\ndata: {json.dumps(result.get('original_transcription', ''))}\n\n"
    yield f"event: translation\ndata: {json.dumps(result.get('english_translation', ''))}\n\n"
    yield "event: done\ndata: complete\n\n"


@router.post("/process")
async def process_document(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    file_bytes = await file.read()
    mime_type = file.content_type or "image/png"

    return StreamingResponse(
        _process_stream(file_bytes, mime_type, file.filename),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Voice: record Hindi speech -> Whisper transcription -> GPT-4o-mini translation
# ---------------------------------------------------------------------------
async def _whisper_transcribe(audio_bytes: bytes, filename: str) -> str:
    client = get_openrouter_client()
    response = await client.audio.transcriptions.create(
        model=WHISPER_MODEL,
        file=(filename, audio_bytes, "audio/webm"),
    )
    return response.text


async def _gpt_translate(hindi_text: str) -> str:
    client = get_openrouter_client()
    response = await client.chat.completions.create(
        model=TRANSLATE_MODEL,
        messages=[{"role": "user", "content": VOICE_TRANSLATE_PROMPT.format(text=hindi_text)}],
        temperature=0.1,
    )
    return response.choices[0].message.content.strip()


@router.post("/voice-to-english")
async def voice_to_english(file: UploadFile = File(...)):
    audio_bytes = await file.read()

    try:
        hindi_text = await _whisper_transcribe(audio_bytes, file.filename or "recording.webm")
        english_text = await _gpt_translate(hindi_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Voice processing failed: {str(e)}")

    return {
        "hindi_text": hindi_text,
        "english_text": english_text,
    }


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------
class DownloadPdfRequest(BaseModel):
    text: str
    title: str = "Translated Legal Document"


def _build_pdf(text: str, title: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
    )

    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"], fontName="Times-Roman", fontSize=11, leading=16
    )
    label_style = ParagraphStyle(
        "Label", parent=body_style, fontName="Times-Bold"
    )
    signature_style = ParagraphStyle(
        "Signature", parent=body_style, spaceBefore=12
    )

    story = [Paragraph(title, styles["Title"]), Spacer(1, 16)]

    label_prefixes = ("to,", "from,", "subject:", "date:")
    signature_prefixes = ("yours faithfully", "yours sincerely", "thank you")

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 8))
            continue

        lower = line.lower()
        escaped = (
            line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )

        if lower.startswith(label_prefixes):
            story.append(Paragraph(escaped, label_style))
        elif lower.startswith(signature_prefixes):
            story.append(Paragraph(escaped, signature_style))
        elif re.match(r"^(\d+[.)]|\u2022)\s", line):
            story.append(Paragraph(escaped, body_style, bulletText=""))
        else:
            story.append(Paragraph(escaped, body_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


@router.post("/download-pdf")
async def download_pdf(req: DownloadPdfRequest):
    try:
        pdf_bytes = _build_pdf(req.text, req.title)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {str(e)}")

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=translated_document.pdf"},
    )