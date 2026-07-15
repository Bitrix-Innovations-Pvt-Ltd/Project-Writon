from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.future import select
from datetime import datetime

from app.core.database import get_db
from app.models.draft import Draft
from app.models.gapfill import ContextGapAnalytics
from app.modules.gapfill.schema_gaps import detect_schema_gaps
from app.modules.gapfill.phrasing import phrase_schema_gap_question
from app.modules.gapfill.context_gaps import detect_context_gaps

import asyncio
# Assuming there is a cache_set / cache_get in app.core, if not we will define a simple memory cache for now
# or we can just store the queue in the draft's additional_context temporarily. Let's use a simple memory cache.
# In a real distributed system, we'd use Redis.
_context_queue_cache: Dict[str, List[Dict[str, str]]] = {}

router = APIRouter(prefix="/gapfill", tags=["GapFill"])


class GapFillStartRequest(BaseModel):
    draft_id: Optional[int] = None
    document_type_key: str
    form_data: dict


class GapFillAnswerRequest(BaseModel):
    draft_id: Optional[int] = None
    field: str
    gap_type: str  # 'schema' | 'context'
    answer: Optional[str] = None
    skipped: bool = False


async def cache_set(key: str, val: Any):
    _context_queue_cache[key] = val

async def cache_get(key: str) -> Any:
    return _context_queue_cache.get(key)


async def build_summary(db, draft_id: int) -> dict:
    res = await db.execute(select(Draft).filter(Draft.id == draft_id))
    draft = res.scalar_one_or_none()
    if not draft or not draft.chatbot_gap_fill_log:
        return {"added": [], "skipped": []}
    
    log = draft.chatbot_gap_fill_log
    added = [e["field"] for e in log if e.get("answered")]
    skipped = [e["field"] for e in log if e.get("skipped")]
    return {"added": added, "skipped": skipped}


@router.post("/start")
async def start_gapfill(req: GapFillStartRequest, db: Session = Depends(get_db)):
    """Returns the FIRST question to ask, or signals completion if none needed."""
    draft_id = req.draft_id
    if not draft_id:
        # Create a temporary draft to store interactions
        draft = Draft(
            form_data=req.form_data,
            case_type=req.document_type_key,
        )
        db.add(draft)
        await db.commit()
        await db.refresh(draft)
        draft_id = draft.id
    else:
        res = await db.execute(select(Draft).filter(Draft.id == draft_id))
        draft = res.scalar_one_or_none()
        if draft:
            draft.form_data = req.form_data
            draft.case_type = req.document_type_key
            await db.commit()
        else:
            # Handle case where draft_id is provided but not in DB
            draft = Draft(
                id=draft_id,
                form_data=req.form_data,
                case_type=req.document_type_key,
            )
            db.add(draft)
            await db.commit()
            await db.refresh(draft)

    schema_gaps = await detect_schema_gaps(db, req.form_data, req.document_type_key)

    if schema_gaps:
        question = await phrase_schema_gap_question(schema_gaps[0], req.document_type_key)
        return {
            "draft_id": draft_id,
            "phase": "schema",
            "gap": schema_gaps[0],
            "question": question,
            "why_relevant": "This is a required standard field for this document type.",
            "remaining_count": len(schema_gaps)
        }

    # Otherwise, check context gaps
    context_gaps = await detect_context_gaps(req.form_data, req.document_type_key)
    if not context_gaps:
        return {"phase": "complete", "draft_id": draft_id, "summary": {"added": [], "skipped": []}}

    # Store context gaps in memory cache for this draft
    _context_queue_cache[str(draft_id)] = context_gaps
    
    first_context = context_gaps.pop(0)
    return {
        "draft_id": draft_id,
        "phase": "context",
        "question": first_context["question"],
        "why_relevant": first_context["why_relevant"],
        "remaining_count": len(context_gaps) + 1
    }


@router.post("/answer")
async def answer_gapfill(req: GapFillAnswerRequest, db = Depends(get_db)):
    res = await db.execute(select(Draft).filter(Draft.id == req.draft_id))
    draft = res.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    log_entry = {
        "field": req.field,
        "gap_type": req.gap_type,
        "answered": not req.skipped,
        "answer_written_to": f"form_data.{req.field}" if req.gap_type == "schema" else "additional_context",
        "skipped": req.skipped,
        "skip_reason": "user_skipped" if req.skipped else None,
        "asked_at": datetime.utcnow().isoformat(),
    }
    
    # Append to chatbot_gap_fill_log
    current_log = list(draft.chatbot_gap_fill_log) if draft.chatbot_gap_fill_log else []
    current_log.append(log_entry)
    draft.chatbot_gap_fill_log = current_log
    await db.commit()

    if not req.skipped and req.answer:
        if req.gap_type == "schema":
            current_form_data = dict(draft.form_data) if draft.form_data else {}
            current_form_data[req.field] = req.answer
            draft.form_data = current_form_data
        else:
            current_context = list(draft.additional_context) if draft.additional_context else []
            current_context.append({
                "question": req.field,
                "answer": req.answer,
                "source": "context_gap",
                "used_in_draft": True,
            })
            draft.additional_context = current_context
            
            # Log for promotion-candidate analytics
            analytics_entry = ContextGapAnalytics(
                document_type_key=draft.case_type or "unknown",
                suggested_question=req.field,
                was_answered=True,
                was_skipped=False
            )
            db.add(analytics_entry)
            
        await db.commit()
    elif req.skipped and req.gap_type == "context":
        analytics_entry = ContextGapAnalytics(
            document_type_key=draft.case_type or "unknown",
            suggested_question=req.field,
            was_answered=False,
            was_skipped=True
        )
        db.add(analytics_entry)
        await db.commit()

    # Re-fetch form_data directly from updated draft object
    form_data = draft.form_data or {}
    document_type_key = draft.case_type or "unknown"

    if req.gap_type == "schema":
        remaining_schema_gaps = await detect_schema_gaps(db, form_data, document_type_key)
        if remaining_schema_gaps:
            gap = remaining_schema_gaps[0]
            question = await phrase_schema_gap_question(gap, document_type_key)
            return {"phase": "schema", "gap": gap, "question": question,
                    "remaining_count": len(remaining_schema_gaps) - 1}
        # Schema gaps done — move to context phase
        context_gaps = await detect_context_gaps(form_data, document_type_key)
        if context_gaps:
            first = context_gaps[0]
            await cache_set(f"gapfill:{req.draft_id}:context_queue", context_gaps[1:])
            return {"phase": "context", "question": first["question"],
                    "why_relevant": first["why_relevant"], "remaining_count": len(context_gaps) - 1}
        return {"phase": "complete", "summary": await build_summary(db, req.draft_id)}

    else:  # gap_type == 'context'
        queue = await cache_get(f"gapfill:{req.draft_id}:context_queue") or []
        if queue:
            next_item = queue[0]
            await cache_set(f"gapfill:{req.draft_id}:context_queue", queue[1:])
            return {"phase": "context", "question": next_item["question"],
                    "why_relevant": next_item["why_relevant"], "remaining_count": len(queue) - 1}
        return {"phase": "complete", "summary": await build_summary(db, req.draft_id)}
