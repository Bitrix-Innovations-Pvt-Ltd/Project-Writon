from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.future import select
from datetime import datetime

from app.core.database import get_db
from app.core.redis import cache_get, cache_set, cache_delete
from app.models.draft import Draft
from app.models.gapfill import ContextGapAnalytics
from app.modules.gapfill.schema_gaps import detect_schema_gaps
from app.modules.gapfill.phrasing import phrase_schema_gap_question
from app.modules.gapfill.context_gaps import detect_context_gaps

router = APIRouter(prefix="/gapfill", tags=["GapFill"])

# ── Cache key helpers ─────────────────────────────────────────────────────────
# All gapfill session data expires after 2 h of inactivity.
_TTL = 7200

def _ctx_queue_key(draft_id: int) -> str:
    return f"gapfill:{draft_id}:context_queue"

def _ctx_computed_key(draft_id: int) -> str:
    """Key that marks context gaps as already computed for this draft session."""
    return f"gapfill:{draft_id}:context_computed"


# ── Request / response models ─────────────────────────────────────────────────

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


# ── Helpers ───────────────────────────────────────────────────────────────────

async def build_summary(db, draft_id: int) -> dict:
    res = await db.execute(select(Draft).filter(Draft.id == draft_id))
    draft = res.scalar_one_or_none()
    if not draft or not draft.chatbot_gap_fill_log:
        return {"added": [], "skipped": []}
    log = draft.chatbot_gap_fill_log
    added   = [e["field"] for e in log if e.get("answered")]
    skipped = [e["field"] for e in log if e.get("skipped")]
    return {"added": added, "skipped": skipped}


async def _get_or_compute_context_gaps(draft_id: int, form_data: dict, document_type_key: str, db=None) -> list:
    """
    Returns context gaps from Redis if already computed for this session,
    otherwise calls the AI, stores the result, and returns it.
    This ensures GPT-4o is called at most ONCE per gapfill session.
    """
    cached = await cache_get(_ctx_queue_key(draft_id))
    already_computed = await cache_get(_ctx_computed_key(draft_id))

    if already_computed:
        # Gaps were computed earlier — cached queue IS the remaining list
        return cached or []

    # First time: call AI, passing db for DB-driven field labels
    gaps = await detect_context_gaps(form_data, document_type_key, db=db)

    # Mark as computed and store the full list
    await cache_set(_ctx_computed_key(draft_id), True, _TTL)
    await cache_set(_ctx_queue_key(draft_id), gaps, _TTL)
    return gaps


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/start")
async def start_gapfill(req: GapFillStartRequest, db: Session = Depends(get_db)):
    """
    Returns the FIRST question to ask, or signals completion if none needed.
    Also returns updated_form_data so the frontend stays in sync.
    """
    draft_id = req.draft_id

    # ── Upsert draft ──────────────────────────────────────────────────────────
    if not draft_id:
        draft = Draft(form_data=req.form_data, case_type=req.document_type_key)
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
            draft = Draft(id=draft_id, form_data=req.form_data, case_type=req.document_type_key)
            db.add(draft)
            await db.commit()
            await db.refresh(draft)

    # Clear any stale context-gap cache from a previous session for this draft
    await cache_delete(_ctx_queue_key(draft_id))
    await cache_delete(_ctx_computed_key(draft_id))

    # ── Schema phase ──────────────────────────────────────────────────────────
    schema_gaps = await detect_schema_gaps(db, req.form_data, req.document_type_key)
    if schema_gaps:
        question = await phrase_schema_gap_question(schema_gaps[0], req.document_type_key)
        return {
            "draft_id": draft_id,
            "phase": "schema",
            "gap": schema_gaps[0],
            "question": question,
            "why_relevant": "This is a required standard field for this document type.",
            "remaining_count": len(schema_gaps),
            "updated_form_data": req.form_data,
        }

    # ── Context phase ─────────────────────────────────────────────────────────
    context_gaps = await _get_or_compute_context_gaps(draft_id, req.form_data, req.document_type_key, db=db)
    if not context_gaps:
        return {
            "phase": "complete",
            "draft_id": draft_id,
            "summary": {"added": [], "skipped": []},
            "updated_form_data": req.form_data,
        }

    # Pop first gap and store the remainder back
    first_gap = context_gaps[0]
    await cache_set(_ctx_queue_key(draft_id), context_gaps[1:], _TTL)

    return {
        "draft_id": draft_id,
        "phase": "context",
        "question": first_gap["question"],
        "why_relevant": first_gap["why_relevant"],
        "remaining_count": len(context_gaps),
        "updated_form_data": req.form_data,
    }


@router.post("/answer")
async def answer_gapfill(req: GapFillAnswerRequest, db=Depends(get_db)):
    res = await db.execute(select(Draft).filter(Draft.id == req.draft_id))
    draft = res.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    # ── Audit log ─────────────────────────────────────────────────────────────
    log_entry = {
        "field": req.field,
        "gap_type": req.gap_type,
        "answered": not req.skipped,
        "answer_written_to": f"form_data.{req.field}" if req.gap_type == "schema" else "additional_context",
        "skipped": req.skipped,
        "skip_reason": "user_skipped" if req.skipped else None,
        "asked_at": datetime.utcnow().isoformat(),
    }
    current_log = list(draft.chatbot_gap_fill_log) if draft.chatbot_gap_fill_log else []
    current_log.append(log_entry)
    draft.chatbot_gap_fill_log = current_log
    await db.commit()

    # ── Persist the answer ────────────────────────────────────────────────────
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

            # Analytics — track which context questions users actually answer
            db.add(ContextGapAnalytics(
                document_type_key=draft.case_type or "unknown",
                suggested_question=req.field,
                was_answered=True,
                was_skipped=False,
            ))

        await db.commit()

    elif req.skipped and req.gap_type == "context":
        db.add(ContextGapAnalytics(
            document_type_key=draft.case_type or "unknown",
            suggested_question=req.field,
            was_answered=False,
            was_skipped=True,
        ))
        await db.commit()

    # ── Decide next action ────────────────────────────────────────────────────
    form_data         = draft.form_data or {}
    document_type_key = draft.case_type or "unknown"

    if req.gap_type == "schema":
        # Check if more schema gaps remain (no AI call here)
        remaining_schema_gaps = await detect_schema_gaps(db, form_data, document_type_key)
        if remaining_schema_gaps:
            gap      = remaining_schema_gaps[0]
            question = await phrase_schema_gap_question(gap, document_type_key)
            return {
                "phase": "schema",
                "gap": gap,
                "question": question,
                "remaining_count": len(remaining_schema_gaps) - 1,
                "updated_form_data": form_data,
            }

        # Schema done → move to context phase.
        # _get_or_compute_context_gaps calls the AI ONCE and caches; subsequent
        # calls for the same draft_id return from cache.
        context_gaps = await _get_or_compute_context_gaps(req.draft_id, form_data, document_type_key, db=db)
        if not context_gaps:
            return {
                "phase": "complete",
                "summary": await build_summary(db, req.draft_id),
                "updated_form_data": form_data,
            }

        first = context_gaps[0]
        await cache_set(_ctx_queue_key(req.draft_id), context_gaps[1:], _TTL)
        return {
            "phase": "context",
            "question": first["question"],
            "why_relevant": first["why_relevant"],
            "remaining_count": len(context_gaps) - 1,
            "updated_form_data": form_data,
        }

    else:  # gap_type == 'context'
        queue = await cache_get(_ctx_queue_key(req.draft_id)) or []
        if queue:
            next_item = queue[0]
            await cache_set(_ctx_queue_key(req.draft_id), queue[1:], _TTL)
            return {
                "phase": "context",
                "question": next_item["question"],
                "why_relevant": next_item["why_relevant"],
                "remaining_count": len(queue) - 1,
                "updated_form_data": form_data,
            }

        # No more context gaps
        await cache_delete(_ctx_queue_key(req.draft_id))
        await cache_delete(_ctx_computed_key(req.draft_id))
        return {
            "phase": "complete",
            "summary": await build_summary(db, req.draft_id),
            "updated_form_data": form_data,
        }
