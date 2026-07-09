"""
api/v1/drafting.py — POST /api/v1/drafts/generate

Runs the full 6-stage RAG pipeline and streams the draft via SSE.
Uses GPT-4o for final generation (quality-critical task).
"""

import asyncio
import json
import os

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, engine
from app.core.rag import (
    rewrite_queries,
    retrieve_judgment_chunks,
    retrieve_statutes,
    rerank_candidates,
    assemble_prompt,
    verify_citations,
    get_openrouter_client,
)

router = APIRouter(prefix="/drafts", tags=["drafts"])

# Lazy reference to Legal-BERT — shared with search.py via the singleton there
_sentence_model = None
_model_lock = asyncio.Lock()


async def _get_embedding_fn():
    """Returns a sync callable that encodes a string to a vector using Legal-BERT."""
    global _sentence_model
    if _sentence_model is None:
        async with _model_lock:
            if _sentence_model is None:
                from sentence_transformers import SentenceTransformer
                loop = asyncio.get_event_loop()
                _sentence_model = await loop.run_in_executor(
                    None,
                    lambda: SentenceTransformer("nlpaueb/legal-bert-base-uncased")
                )
    return _sentence_model.encode


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    draft_id: Optional[int] = None
    court_level: str = "supreme"
    court_display: str = "Supreme Court of India"
    document_type: str = ""
    subject_matter: str = ""
    case_description: str = ""
    facts_of_case: str = ""
    grounds: str = ""
    relief_sought: str = ""
    interim_relief_sought: str = ""
    advocate_name: str = ""
    advocate_enrollment_no: str = ""
    petitioners: list = []
    respondents: list = []
    jurisdiction_basis: str = ""
    impugned_order_date: Optional[str] = None
    selected_judgments: Optional[list] = None
    selected_statutes: Optional[list] = None


# ---------------------------------------------------------------------------
# SSE Generator
# ---------------------------------------------------------------------------
async def _rag_stream(req: GenerateRequest):
    """
    Full RAG pipeline yielding SSE events:
      event: token   — streaming draft chunks
      event: citations — final citation verification JSON
      event: done    — signals completion
    """
    form_data = req.dict()

    # ── Stage 1: Query Rewriting & OCR Text Fetching ─────────────────────────────────────────
    ocr_texts = []
    try:
        async with engine.connect() as conn:
            from sqlalchemy import text
            res = await conn.execute(
                text("SELECT ocr_text FROM uploaded_docs WHERE draft_id = :d AND ocr_text IS NOT NULL"),
                {"d": req.draft_id}
            )
            for row in res:
                if len(row[0]) > 50:
                    ocr_texts.append(row[0])
    except Exception as e:
        print(f"Error fetching OCR text: {e}")

    uploaded_docs_context = "\n\n--- UPLOADED DOCUMENTS ---\n" + "\n\n".join(ocr_texts) if ocr_texts else ""

    if req.selected_judgments is not None and req.selected_statutes is not None:
        # User has pre-selected the citations in Phase 6, bypass Stage 1-4
        top_judgments = req.selected_judgments
        top_statutes = req.selected_statutes
    else:
        # Fallback to full RAG retrieval if not provided (old behavior)
        combined_facts = f"{req.facts_of_case}\n{req.case_description}\n{req.grounds}\n{uploaded_docs_context}".strip()
        yield "event: status\ndata: Rewriting queries...\n\n"

        queries = await rewrite_queries(combined_facts, req.document_type, req.subject_matter)
        combined_query = " ".join(queries[:3])

        # ── Stages 2 & 3: Fan-out Hybrid Retrieval (3 corpora in parallel) ──
        yield "event: status\ndata: Retrieving relevant precedents and statutes...\n\n"

        try:
            embedding_fn = await _get_embedding_fn()
            judgment_task = retrieve_judgment_chunks(engine, queries, embedding_fn)
            statute_task  = retrieve_statutes(engine, queries, embedding_fn)
            coi_task      = retrieve_statutes(engine, queries, embedding_fn, coi_only=True)

            judgment_results, statute_results, coi_results = await asyncio.gather(
                judgment_task, statute_task, coi_task
            )
            # Merge statutes + COI (deduplicate by id)
            seen_ids = set()
            merged_statutes = []
            for item in statute_results + coi_results:
                if item["id"] not in seen_ids:
                    merged_statutes.append(item)
                    seen_ids.add(item["id"])
        except Exception as e:
            print(f"Retrieval error: {e}")
            judgment_results, merged_statutes = [], []

        # ── Stage 4: Cross-Encoder Reranking ────────────────────────────────
        yield "event: status\ndata: Reranking results...\n\n"
        top_judgments  = await rerank_candidates(combined_query, judgment_results[:25], top_k=5)
        top_statutes   = await rerank_candidates(combined_query, merged_statutes[:25], top_k=5)

    # ── Stage 5: Context Assembly ────────────────────────────────────────
    prompt = assemble_prompt(form_data, top_judgments, top_statutes, uploaded_docs_context)

    # ── Generation: GPT-4o via OpenRouter (streaming) ───────────────────
    yield "event: status\ndata: Generating draft...\n\n"

    client = get_openrouter_client()
    draft_text = ""

    try:
        stream = await client.chat.completions.create(
            model="anthropic/claude-sonnet-4",
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            temperature=0.2,
            max_tokens=4096,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                draft_text += delta
                escaped = delta.replace("\n", "\\n")
                yield f"event: token\ndata: {json.dumps(delta)}\n\n"
    except Exception as e:
        print(f"Generation error: {e}")
        yield f"event: error\ndata: {json.dumps(str(e))}\n\n"
        return

    # ── Stage 6: Citation Verification (post-generation) ─────────────────
    yield "event: status\ndata: Verifying citations...\n\n"
    try:
        citation_results = await verify_citations(draft_text, engine)
        yield f"event: citations\ndata: {json.dumps(citation_results)}\n\n"
    except Exception as e:
        print(f"Citation verification error: {e}")
        yield f"event: citations\ndata: {json.dumps([])}\n\n"

    yield "event: done\ndata: complete\n\n"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@router.post("/generate")
async def generate_draft(req: GenerateRequest):
    return StreamingResponse(
        _rag_stream(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )

@router.post("/suggest-citations")
async def suggest_citations(req: GenerateRequest):
    ocr_texts = []
    try:
        async with engine.connect() as conn:
            from sqlalchemy import text
            res = await conn.execute(
                text("SELECT ocr_text FROM uploaded_docs WHERE draft_id = :d AND ocr_text IS NOT NULL"),
                {"d": req.draft_id}
            )
            for row in res:
                if len(row[0]) > 50:
                    ocr_texts.append(row[0])
    except Exception as e:
        print(f"Error fetching OCR text: {e}")

    uploaded_docs_context = "\n\n--- UPLOADED DOCUMENTS ---\n" + "\n\n".join(ocr_texts) if ocr_texts else ""
    combined_facts = f"{req.facts_of_case}\n{req.case_description}\n{req.grounds}\n{uploaded_docs_context}".strip()
    
    queries = await rewrite_queries(combined_facts, req.document_type, req.subject_matter)
    combined_query = " ".join(queries[:3])

    try:
        embedding_fn = await _get_embedding_fn()
        judgment_task = retrieve_judgment_chunks(engine, queries, embedding_fn)
        statute_task  = retrieve_statutes(engine, queries, embedding_fn)
        coi_task      = retrieve_statutes(engine, queries, embedding_fn, coi_only=True)

        judgment_results, statute_results, coi_results = await asyncio.gather(
            judgment_task, statute_task, coi_task
        )
        seen_ids = set()
        merged_statutes = []
        for item in statute_results + coi_results:
            if item["id"] not in seen_ids:
                merged_statutes.append(item)
                seen_ids.add(item["id"])
    except Exception as e:
        print(f"Retrieval error: {e}")
        judgment_results, merged_statutes = [], []
        
    print(f"DEBUG - Queries: {queries}")
    print(f"DEBUG - Judgments retrieved: {len(judgment_results)}")
    print(f"DEBUG - Statutes retrieved: {len(merged_statutes)}")

    top_judgments  = await rerank_candidates(combined_query, judgment_results[:10], top_k=5)
    top_statutes   = await rerank_candidates(combined_query, merged_statutes[:10], top_k=5)
    
    return {
        "judgments": top_judgments,
        "statutes": top_statutes
    }
