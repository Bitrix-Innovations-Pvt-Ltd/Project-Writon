"""
api/v1/parties.py — Petitioner-Opponent party extraction feature.

Extracts petitioner/respondent party details (name, relation, age, address,
state) from legal documents via 3 input modes: OCR (document), Voice (audio),
Manual (typed text). Ported from the standalone Petitioner-Opponent project.

Reuses Writon's shared OpenRouter client (app.core.rag.get_openrouter_client),
same pattern as translate.py.
"""

import json
import re
import base64
from typing import Callable, Coroutine, Any, Optional, List

import fitz  # PyMuPDF
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from app.core.rag import get_openrouter_client
from app.schemas.party import Party, PartyList

router = APIRouter(prefix="/parties", tags=["parties"])

VISION_MODEL = "google/gemini-2.5-flash"
TEXT_MODEL = "google/gemini-2.5-flash"
WHISPER_MODEL = "openai/whisper-large-v3-turbo"
MAX_PDF_PAGES = 15
PDF_DPI = 200

SCHEMA_NOTE = """
Schema for each party object:
{
  "serial_no": <int>,
  "full_name": "<string>",
  "relation_type": "<one of: S/O, D/O, W/O, C/O, or empty string>",
  "relation_name": "<string>",
  "age": <int or null>,
  "address": "<string>",
  "state": "<string>",
  "country": "<string, default India>",
  "raw_text": "<the original source line/segment verbatim>"
}
Rules:
- If a field is not found, use a sensible default ("" or null). Do NOT invent data.
- If the source text is in Hindi, translate and transliterate all extracted fields to English.
"""

OCR_SYSTEM_PROMPT = f"""You are a legal-document party extraction assistant.
Extract EVERY petitioner/respondent/accused/complainant name block from the given page image(s).
Return ONLY a JSON array of party objects (no markdown fences, no explanation).
{SCHEMA_NOTE}
"""

VOICE_SYSTEM_PROMPT = f"""You are a legal-document party extraction assistant.
The user is dictating party details in English or Hindi. If Hindi, translate and
transliterate to English first, then parse.
Extract name, relation, age, address, state for each distinct party mentioned.
IMPORTANT: If the user dictates multiple names for a single party entry
(e.g. "Sujal Kumar Jitin Prasad"), the second name is typically the father or
husband. Infer the relation (usually S/O or W/O) instead of splitting them into
multiple separate party objects.
Return ONLY a JSON array of party objects (no markdown fences, no explanation).
{SCHEMA_NOTE}
"""

MANUAL_SYSTEM_PROMPT = f"""You are a legal-document party extraction assistant.
Parse the single line of text given and return ONLY a JSON object (not an array).
serial_no must always be 1. raw_text must be the full input line, verbatim.
If the text is in Hindi, translate and transliterate all fields to English first.
{SCHEMA_NOTE}
"""

LLMCall = Callable[[Optional[str]], Coroutine[Any, Any, str]]


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------
def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def _parse_json_array(text: str) -> list:
    text = _strip_fences(text)
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON array found in model output")
    return json.loads(text[start:end + 1])


def _parse_json_object(text: str) -> dict:
    text = _strip_fences(text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in model output")
    return json.loads(text[start:end + 1])


def _validate_parties(raw: list) -> PartyList:
    parties = [Party.model_validate(item) for item in raw]
    return PartyList(parties=parties)


# ---------------------------------------------------------------------------
# Core extraction engine (shared retry logic across all 3 modes)
# ---------------------------------------------------------------------------
async def extract_parties(llm_call: LLMCall) -> PartyList:
    """Calls the LLM, parses a JSON array, retries once with a correction
    instruction if parsing fails, and raises 502 if it fails twice."""
    raw_text = await llm_call(None)
    try:
        parsed = _parse_json_array(raw_text)
        return _validate_parties(parsed)
    except Exception as first_error:
        try:
            correction = (
                f"Your previous response could not be parsed as valid JSON "
                f"(error: {first_error}). Return ONLY a valid JSON array, "
                f"with no markdown fences and no explanation."
            )
            raw_text_retry = await llm_call(correction)
            parsed = _parse_json_array(raw_text_retry)
            return _validate_parties(parsed)
        except Exception as second_error:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to parse party data from model output: {second_error}",
            )


async def extract_single_party(llm_call: LLMCall) -> Party:
    raw_text = await llm_call(None)
    try:
        parsed = _parse_json_object(raw_text)
        return Party.model_validate(parsed)
    except Exception as first_error:
        try:
            correction = (
                f"Your previous response could not be parsed as valid JSON "
                f"(error: {first_error}). Return ONLY a valid JSON object, "
                f"with no markdown fences and no explanation."
            )
            raw_text_retry = await llm_call(correction)
            parsed = _parse_json_object(raw_text_retry)
            return Party.model_validate(parsed)
        except Exception as second_error:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to parse party data from model output: {second_error}",
            )


# ---------------------------------------------------------------------------
# OpenRouter callers
# ---------------------------------------------------------------------------
async def call_openrouter_vision(
    images_b64: List[str], extra_instruction: Optional[str] = None
) -> str:
    client = get_openrouter_client()
    content = [{"type": "text", "text": OCR_SYSTEM_PROMPT + (f"\n\n{extra_instruction}" if extra_instruction else "")}]
    for img_b64 in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
        })
    response = await client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{"role": "user", "content": content}],
        temperature=0.0,
        max_tokens=4096,
    )
    return response.choices[0].message.content


async def call_openrouter_text(
    transcript: str, extra_instruction: Optional[str] = None
) -> str:
    client = get_openrouter_client()
    prompt = VOICE_SYSTEM_PROMPT + (f"\n\n{extra_instruction}" if extra_instruction else "")
    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": transcript},
        ],
        temperature=0.0,
        max_tokens=2048,
    )
    return response.choices[0].message.content


async def call_openrouter_manual(
    text: str, extra_instruction: Optional[str] = None
) -> str:
    client = get_openrouter_client()
    prompt = MANUAL_SYSTEM_PROMPT + (f"\n\n{extra_instruction}" if extra_instruction else "")
    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
        temperature=0.0,
        max_tokens=1024,
    )
    return response.choices[0].message.content


AUDIO_FORMAT_MAP = {
    "mp3": "mp3", "mpeg": "mp3",
    "wav": "wav", "x-wav": "wav",
    "m4a": "m4a", "x-m4a": "m4a", "mp4": "m4a",
    "ogg": "ogg", "webm": "webm", "flac": "flac",
}


async def transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    client = get_openrouter_client()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "webm"
    fmt = AUDIO_FORMAT_MAP.get(ext, "wav")
    response = await client.audio.transcriptions.create(
        model=WHISPER_MODEL,
        file=(filename, audio_bytes, f"audio/{fmt}"),
    )
    return response.text


def _pdf_to_images_b64(file_bytes: bytes) -> List[str]:
    images_b64 = []
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    zoom = PDF_DPI / 72
    matrix = fitz.Matrix(zoom, zoom)
    for page_number in range(min(len(doc), MAX_PDF_PAGES)):
        page = doc[page_number]
        pix = page.get_pixmap(matrix=matrix)
        images_b64.append(base64.b64encode(pix.tobytes("png")).decode("utf-8"))
    doc.close()
    return images_b64


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/extract-ocr", response_model=PartyList)
async def extract_ocr(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    file_bytes = await file.read()
    is_pdf = (file.content_type == "application/pdf") or file.filename.lower().endswith(".pdf")

    try:
        images_b64 = _pdf_to_images_b64(file_bytes) if is_pdf else [base64.b64encode(file_bytes).decode("utf-8")]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")

    if not images_b64:
        raise HTTPException(status_code=400, detail="No pages/images found in file.")

    llm_call = lambda extra: call_openrouter_vision(images_b64, extra_instruction=extra)
    return await extract_parties(llm_call)


@router.post("/extract-voice", response_model=PartyList)
async def extract_voice(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    audio_bytes = await file.read()

    try:
        transcript = await transcribe_audio(audio_bytes, file.filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

    if not transcript or not transcript.strip():
        raise HTTPException(status_code=422, detail="Transcript was empty. Please try recording again.")

    llm_call = lambda extra: call_openrouter_text(transcript, extra_instruction=extra)
    return await extract_parties(llm_call)


class ManualTextRequest(BaseModel):
    text: str


@router.post("/validate-manual", response_model=Party)
async def validate_manual(body: ManualTextRequest):
    if not body.text or not body.text.strip():
        raise HTTPException(status_code=400, detail="Text must not be empty.")

    llm_call = lambda extra: call_openrouter_manual(body.text, extra_instruction=extra)
    return await extract_single_party(llm_call)