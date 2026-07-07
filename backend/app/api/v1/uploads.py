from fastapi import APIRouter, Depends, File, UploadFile, Form, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated
import uuid
import time
from app.core.database import get_db, AsyncSessionLocal
from app.core.r2 import upload_file_to_r2
from app.core.ocr import extract_text_from_bytes
from app.core.verification import verify_document
from app.models.draft import UploadedDoc

router = APIRouter(prefix="/uploads", tags=["uploads"])

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/")
async def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    draft_id: str = Form(""),
    user_id: str = Form(""),
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
        # We need an io.BytesIO for boto3 upload
        import io
        r2_key = upload_file_to_r2(io.BytesIO(file_bytes), r2_path, file.content_type or "application/octet-stream")
        
        parsed_draft_id = None
        if draft_id and draft_id.isdigit() and int(draft_id) > 0:
            parsed_draft_id = int(draft_id)
            
        parsed_user_id = None
        if user_id and len(user_id) > 10:
            try:
                parsed_user_id = uuid.UUID(user_id)
            except:
                pass
        
        # Save record in database
        uploaded_doc = UploadedDoc(
            draft_id=parsed_draft_id,
            user_id=parsed_user_id,
            original_filename=file.filename,
            r2_key=r2_key,
            doc_type=doc_type,
            verify_status="pending"
        )
        
        db.add(uploaded_doc)
        await db.commit()
        await db.refresh(uploaded_doc)
        
        # Run OCR and Verification synchronously so frontend can alert if rejected
        ocr_text = extract_text_from_bytes(file_bytes, file.filename)
        if ocr_text:
            ocr_text = ocr_text.replace('\x00', '')
            
        verification_result = await verify_document(doc_type, ocr_text)
        
        uploaded_doc.ocr_text = ocr_text
        uploaded_doc.verify_status = verification_result["status"]
        uploaded_doc.verify_reason = verification_result["reason"]
        await db.commit()
        
        if verification_result["status"] == "rejected":
            raise HTTPException(status_code=400, detail=f"Document Rejected: {verification_result['reason']}")
        
        return {
            "status": "success",
            "message": "File uploaded and verified successfully.",
            "doc_id": uploaded_doc.id,
            "r2_key": r2_key
        }
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")
