from fastapi import APIRouter, Depends, File, UploadFile, Form, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, Any, Optional
import hashlib
import uuid
import time
from app.core.database import get_db, AsyncSessionLocal
from app.core.r2 import upload_file_to_r2
from app.core.ocr import extract_and_normalize
from app.core.verification import verify_document
from app.core.extraction import extract_fields_from_docs
from app.core.redis import cache_get, cache_set
from app.models.draft import UploadedDoc

router = APIRouter(prefix="/uploads", tags=["uploads"])

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

# Extraction results live as long as a gapfill session (see gapfill.py::_TTL).
_EXTRACT_TTL = 7200


async def _resolve_user_uuid(db: AsyncSession, user_id: str) -> Optional[uuid.UUID]:
    """Map the incoming id to users.id.

    The frontend sends a Clerk id ("user_2ab..."), but uploaded_docs.user_id is
    a UUID FK to users.id — so the id has to be looked up via users.clerk_id.
    Accepts a raw UUID too, for callers that already have one.
    """
    if not user_id or len(user_id) < 10:
        return None

    try:
        return uuid.UUID(user_id)
    except (ValueError, AttributeError, TypeError):
        pass  # not a UUID — expected for Clerk ids, fall through to the lookup

    try:
        res = await db.execute(
            sql_text("SELECT id FROM users WHERE clerk_id = :cid LIMIT 1"),
            {"cid": user_id},
        )
        row = res.fetchone()
        return row[0] if row else None
    except Exception as e:
        print(f"[uploads] could not resolve user_id {user_id!r}: {e}")
        return None


@router.post("/")
async def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    draft_id: str = Form(""),
    user_id: str = Form(""),
    upload_session_id: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    # Validate file size by reading bytes directly
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds 5MB limit.")
        
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")
        
    # Construct secure R2 path
    ext = file.filename.split('.')[-1] if '.' in file.filename else ''
    safe_filename = f"{uuid.uuid4().hex}_{int(time.time())}.{ext}" if ext else f"{uuid.uuid4().hex}_{int(time.time())}"
    r2_path = f"drafting/Document/User/{user_id}/{safe_filename}"
    
    try:
        import io
        import asyncio
        
        # Start both heavy tasks concurrently in background threads
        r2_task = asyncio.to_thread(
            upload_file_to_r2, 
            io.BytesIO(file_bytes), 
            r2_path, 
            file.content_type or "application/octet-stream"
        )
        # OCR followed by Hindi→English translation. Already a coroutine (it
        # does its own to_thread for the blocking OCR), and it short-circuits
        # with no API call when the document is already English.
        ocr_task = extract_and_normalize(file_bytes, file.filename)

        r2_key, ocr = await asyncio.gather(r2_task, ocr_task)

        parsed_draft_id = None
        if draft_id and draft_id.isdigit() and int(draft_id) > 0:
            parsed_draft_id = int(draft_id)

        parsed_user_id = await _resolve_user_uuid(db, user_id)

        # Save record in database. upload_session_id groups the documents of a
        # single wizard session; /gapfill/start back-links them to draft_id once
        # the draft row exists, so they reach the generation prompt.
        uploaded_doc = UploadedDoc(
            draft_id=parsed_draft_id,
            upload_session_id=(upload_session_id or None),
            user_id=parsed_user_id,
            original_filename=file.filename,
            r2_key=r2_key,
            doc_type=doc_type,
            verify_status="pending"
        )
        
        db.add(uploaded_doc)
        await db.commit()
        await db.refresh(uploaded_doc)
        
        ocr_text = (ocr.text or "").replace('\x00', '')
        # NULL rather than "" when nothing was translated, so an English upload
        # costs no extra storage and the column means "there is an original
        # worth showing the advocate".
        ocr_original = ((ocr.original or "").replace('\x00', '')) or None

        # Verify against the pre-translation text. gpt-4o-mini classifies Hindi
        # perfectly well, and this way a translation that failed or was capped
        # cannot turn into a rejected upload.
        verification_result = await verify_document(doc_type, ocr_original or ocr_text)

        uploaded_doc.ocr_text = ocr_text
        uploaded_doc.ocr_text_original = ocr_original
        uploaded_doc.ocr_lang = ocr.language
        uploaded_doc.translation_status = ocr.status
        uploaded_doc.verify_status = verification_result["status"]
        uploaded_doc.verify_reason = verification_result["reason"]
        await db.commit()

        if verification_result["status"] == "rejected":
            raise HTTPException(status_code=400, detail=f"Document Rejected: {verification_result['reason']}")

        return {
            "status": "success",
            "message": "File uploaded and verified successfully.",
            "doc_id": uploaded_doc.id,
            "r2_key": r2_key,
            # Lets the wizard badge the document without a second request.
            "language": ocr.language,
            "translation_status": ocr.status,
        }
    except HTTPException:
        # Re-raise HTTP exceptions so they retain their status code
        raise
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")


# ---------------------------------------------------------------------------
# Auto-populate: extract Parties & Facts values from the uploaded documents
# ---------------------------------------------------------------------------

class ExtractFieldsRequest(BaseModel):
    upload_session_id: str
    draft_id: Optional[int] = None
    document_type: str = ""
    # Selects which meaning `jurisdiction_basis` carries — the field renders as
    # "Crime Number / FIR No.", "Court Below" etc. depending on the template.
    document_type_key: str = ""
    court_display: str = ""
    subject_matter: str = ""
    force: bool = False          # bypass the cache — powers "Re-scan documents"


class ExtractedField(BaseModel):
    value: Any = None
    confidence: float = 0.0
    source_doc: Optional[str] = None
    reason: Optional[str] = None


class ExtractFieldsResponse(BaseModel):
    status: str
    fields: dict[str, ExtractedField] = {}
    low_confidence: dict[str, ExtractedField] = {}
    docs_used: list[dict] = []
    # Distinct matters found across the uploads. More than one means a document
    # was probably uploaded to the wrong slot.
    matters: list[dict] = []
    # Row ids belonging to the primary matter — the frontend passes these to
    # /generate so an unrelated case cannot leak into the draft.
    primary_doc_ids: list[int] = []
    warnings: list[str] = []
    cached: bool = False


@router.post("/extract-fields", response_model=ExtractFieldsResponse)
async def extract_fields(req: ExtractFieldsRequest, db: AsyncSession = Depends(get_db)):
    """Read the OCR text of this session's uploads and suggest values for the
    Step 5 "Parties & Facts" form. Never fails the caller — the wizard must
    always be able to advance."""
    if not req.upload_session_id or len(req.upload_session_id) < 16:
        raise HTTPException(status_code=400, detail="upload_session_id is required")

    # Documents the classifier rejected are excluded: uploads.py commits
    # ocr_text before raising the 400, so rejected rows persist as an audit
    # trail and must be filtered at every read site.
    res = await db.execute(
        sql_text("""
            SELECT id, doc_type, original_filename, ocr_text
              FROM uploaded_docs
             -- draft_id IS NULL on the session branch: once uploads are linked
             -- to a draft they belong to that draft only. The session id is
             -- shared by every new draft in a browser tab, so without this a
             -- fresh draft would auto-populate from the previous draft's files.
             WHERE ((upload_session_id = :sid AND draft_id IS NULL)
                    OR draft_id = CAST(:did AS BIGINT))
               AND ocr_text IS NOT NULL
               AND COALESCE(verify_status, '') <> 'rejected'
             ORDER BY uploaded_at ASC
        """),
        {"sid": req.upload_session_id, "did": req.draft_id},
    )
    docs = [dict(r) for r in res.mappings().all()]

    if not docs:
        return ExtractFieldsResponse(
            status="no_docs",
            warnings=["No readable documents found for this session."],
        )

    # The fingerprint covers the doc-id set AND the document type: uploading
    # another document invalidates the extraction, and so does changing the
    # document type, since that redefines what jurisdiction_basis means.
    fingerprint = hashlib.sha1(
        (",".join(str(d["id"]) for d in docs) + "|" + (req.document_type_key or "")).encode()
    ).hexdigest()[:12]
    cache_key = f"extract:{req.upload_session_id}:{fingerprint}"

    if not req.force:
        cached = await cache_get(cache_key)
        if cached:
            return ExtractFieldsResponse(**{**cached, "cached": True})

    result = await extract_fields_from_docs(
        docs,
        document_type=req.document_type,
        court_display=req.court_display,
        subject_matter=req.subject_matter,
        document_type_key=req.document_type_key,
    )

    # Only cache successes — a transient timeout must not poison the session
    # for the full TTL.
    if result.get("status") == "ok":
        await cache_set(cache_key, result, _EXTRACT_TTL)

    return ExtractFieldsResponse(**result)
