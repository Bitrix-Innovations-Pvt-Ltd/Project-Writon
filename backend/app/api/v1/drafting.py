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
    retrieve_court_rules,
    get_effective_structure_rules,
    get_mandatory_paragraphs,
    rerank_candidates,
    assemble_prompt,
    verify_citations,
    get_openrouter_client,
    _SUBJECT_NEEDS_COI,
)

router = APIRouter(prefix="/drafts", tags=["drafts"])

async def _get_embedding_fn():
    """Returns a sync callable that encodes a string to a vector using Legal-BERT.

    Reuses the singleton from search.py (preloaded at startup) instead of
    loading a second ~400MB copy — the previous executor-based load here also
    risked the torch 2.6 meta-tensor crash on background-thread model loading.
    """
    from app.api.v1.search import get_model
    model = await get_model()
    return model.encode


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    draft_id: Optional[int] = None
    court_level: str = "supreme"
    court_display: str = "Supreme Court of India"
    court_identity_id: Optional[int] = None   # sent explicitly from frontend Step 1b dropdown
    document_type: str = ""
    document_type_key: Optional[str] = None   # prompt template key (e.g. 'writ_petition_civil')
    subject_matter: str = ""
    case_description: str = ""
    facts_of_case: str = ""
    grounds: str = ""
    relief_sought: str = ""
    interim_relief_sought: str = ""
    mandatory_paragraphs: str = ""
    advocate_name: str = ""
    advocate_enrollment_no: str = ""
    petitioners: list = []
    respondents: list = []
    jurisdiction_basis: str = ""
    impugned_order_date: Optional[str] = None
    dates_and_events: list = []
    selected_judgments: Optional[list] = None
    selected_statutes: Optional[list] = None
    section_format_overrides: Optional[dict] = None
    search_hint: Optional[str] = None
    # Whitelisted retrieval-knob overrides used by scripts/evaluate_step6.py
    # for A/B benchmarking against a running server (see rag.py knobs).
    rag_overrides: Optional[dict] = None


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
            if req.draft_id:
                res = await conn.execute(
                    text("SELECT ocr_text FROM uploaded_docs WHERE draft_id = :d AND ocr_text IS NOT NULL"),
                    {"d": req.draft_id}
                )
                for row in res:
                    if len(row[0]) > 50:
                        ocr_texts.append(row[0])
                        
                # Fetch additional_context from the chatbot phase
                draft_res = await conn.execute(
                    text("SELECT additional_context FROM drafts WHERE id = :d LIMIT 1"),
                    {"d": req.draft_id}
                )
                draft_row = draft_res.fetchone()
                if draft_row and draft_row[0]:
                    try:
                        add_ctx_list = draft_row[0]
                        if isinstance(add_ctx_list, str):
                            add_ctx_list = json.loads(add_ctx_list)
                        
                        if isinstance(add_ctx_list, list) and len(add_ctx_list) > 0:
                            ctx_str = "\n\n--- ADDITIONAL CONTEXT (FROM CHATBOT) ---\n"
                            for gap in add_ctx_list:
                                q = gap.get("question", "")
                                a = gap.get("answer", "")
                                if q and a:
                                    ctx_str += f"Q: {q}\nA: {a}\n\n"
                            
                            req.facts_of_case += ctx_str
                            form_data["facts_of_case"] = req.facts_of_case
                    except Exception as e:
                        print(f"Error parsing additional_context: {e}")
    except Exception as e:
        print(f"Error fetching OCR text / additional context: {e}")

    uploaded_docs_context = "\n\n--- UPLOADED DOCUMENTS ---\n" + "\n\n".join(ocr_texts) if ocr_texts else ""

    # queries populated in the RAG branch below; pre-init for court_rules scope
    queries: list = []

    if req.selected_judgments is not None and req.selected_statutes is not None:
        # User has pre-selected the citations in Phase 6, bypass Stage 1-4
        top_judgments = req.selected_judgments
        top_statutes = req.selected_statutes
    else:
        # Fallback to full RAG retrieval if not provided (old behavior)
        combined_facts = f"{req.facts_of_case}\n{req.case_description}\n{req.grounds}\n{uploaded_docs_context}".strip()
        yield "event: status\ndata: Rewriting queries...\n\n"

        queries = await rewrite_queries(
            combined_facts, req.document_type, req.subject_matter,
            document_type_key=req.document_type_key or "",
        )
        combined_query = " ".join(queries[:3])

        # ── Stages 2 & 3: Fan-out Hybrid Retrieval (3 corpora in parallel) ──
        yield "event: status\ndata: Retrieving relevant precedents and statutes...\n\n"

        try:
            embedding_fn = await _get_embedding_fn()
            
            # OPTIMIZATION: Batch compute all vectors once instead of 21 sequential runs
            loop = asyncio.get_event_loop()
            from app.core.rag import _cpu_executor
            vecs = await loop.run_in_executor(_cpu_executor, embedding_fn, queries)
            query_vectors = {q: (v.tolist() if hasattr(v, "tolist") else list(v)) for q, v in zip(queries, vecs)}

            judgment_task = retrieve_judgment_chunks(
                engine, queries,
                document_type_key=req.document_type_key or "",
                subject_matter=req.subject_matter,
                query_vectors=query_vectors
            )
            statute_task  = retrieve_statutes(
                engine, queries,
                document_type_key=req.document_type_key or "",
                subject_matter=req.subject_matter,
                query_vectors=query_vectors
            )
            # Bug 6: only retrieve COI sections when the subject matter is
            # constitutionally relevant — prevents education/panchayat Article noise.
            sm_lower_check = req.subject_matter.lower() if req.subject_matter else ""
            needs_coi = any(kw in sm_lower_check for kw in _SUBJECT_NEEDS_COI)
            coi_task = (
                retrieve_statutes(engine, queries, coi_only=True, query_vectors=query_vectors)
                if needs_coi else asyncio.sleep(0)  # no-op coroutine
            )

            judgment_results, statute_results, coi_results = await asyncio.gather(
                judgment_task, statute_task, coi_task
            )
            # coi_results is [] when coi_task was the no-op asyncio.sleep(0)
            if not isinstance(coi_results, list):
                coi_results = []
            # Merge statutes + COI by score (deduplicate by id) so COI hits
            # compete on rank instead of being appended past the slice window
            seen_ids = set()
            merged_statutes = []
            for item in sorted(statute_results + coi_results, key=lambda x: x["score"], reverse=True):
                if item["id"] not in seen_ids:
                    merged_statutes.append(item)
                    seen_ids.add(item["id"])
        except Exception as e:
            print(f"Retrieval error: {e}")
            judgment_results, merged_statutes = [], []

        # ── Stage 4: Cross-Encoder Reranking ────────────────────────────────
        yield "event: status\ndata: Reranking results...\n\n"
        top_judgments  = await rerank_candidates(combined_query, judgment_results[:25], top_k=5)
        top_statutes   = await rerank_candidates(combined_query, merged_statutes[:15], top_k=5, use_cross_encoder=True)

    # ── Stage 5: Context Assembly ────────────────────────────────────────
    # Retrieve court-specific procedural rules (AHC or other specific courts)
    court_rules_block = ""
    if req.court_identity_id:
        doc_type_key = req.document_type_key or ""
        try:
            embedding_fn = await _get_embedding_fn()
            court_rules_block = await retrieve_court_rules(
                engine,
                req.court_identity_id,
                doc_type_key,
                queries,
                embedding_fn,
            )
        except Exception as e:
            print(f"Court Rules Error: {e}")
            court_rules_block = ""
            
    # Fetch effective structure rules and mandatory paragraphs
    structure_rules = []
    mandatory_paragraphs = {}
    doc_type_key = req.document_type_key or ""
    try:
        structure_rules = await get_effective_structure_rules(
            engine,
            req.court_level,
            req.section_format_overrides or {}
        )
        mandatory_paragraphs = await get_mandatory_paragraphs(
            engine,
            req.court_level,
            doc_type_key
        )
    except Exception as e:
        print(f"Error fetching structure rules / mandatory paragraphs: {e}")
        
    # Persist user defaults if overrides were provided and we have a draft_id
    if req.section_format_overrides and req.draft_id:
        try:
            async with engine.begin() as conn:
                from sqlalchemy import text
                await conn.execute(
                    text("""
                        UPDATE users 
                        SET default_section_format_overrides = :overrides
                        WHERE id = (SELECT user_id FROM drafts WHERE id = :d LIMIT 1)
                    """),
                    {"overrides": json.dumps(req.section_format_overrides), "d": req.draft_id}
                )
        except Exception as e:
            print(f"Error persisting user defaults: {e}")

    prompt = assemble_prompt(
        form_data=form_data,
        judgment_results=top_judgments,
        statute_results=top_statutes,
        uploaded_docs_context=uploaded_docs_context,
        court_rules_block=court_rules_block,
        structure_rules=structure_rules,
        mandatory_paragraphs=mandatory_paragraphs,
    )

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
            max_tokens=8192,
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
    import hashlib
    from app.core.rag import rerank_multi
    from app.core.redis import cache_get, cache_set

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
    combined_facts = f"{req.facts_of_case}\n{req.case_description}\n{req.grounds}\n{req.mandatory_paragraphs}\n{uploaded_docs_context}".strip()

    # Benchmark/dev knob overrides — whitelisted keys only. The module attrs
    # are snapshotted here and restored in the finally-block at the end of
    # this request, so an override can never leak into other users' requests
    # (a leak here previously let benchmark variants contaminate live results).
    disable_cache = False
    knob_backup = None
    if req.rag_overrides:
        import app.core.rag as rag_module
        ov = req.rag_overrides
        knob_backup = {
            "_VEC_PRESQL": rag_module._VEC_PRESQL,
            "JUDGMENT_OR_FALLBACK": rag_module.JUDGMENT_OR_FALLBACK,
            "NUM_QUERIES": rag_module.NUM_QUERIES,
            "REWRITE_MODEL": rag_module.REWRITE_MODEL,
        }
        try:
            if "probes" in ov:
                rag_module._VEC_PRESQL = f"SET LOCAL ivfflat.probes = {max(1, min(100, int(ov['probes'])))}"
            if "judgment_or_fallback" in ov:
                rag_module.JUDGMENT_OR_FALLBACK = bool(ov["judgment_or_fallback"])
            if "num_queries" in ov:
                rag_module.NUM_QUERIES = max(3, min(7, int(ov["num_queries"])))
            rm = ov.get("rewrite_model")
            if isinstance(rm, str) and rm.startswith(("openai/", "google/", "anthropic/")):
                rag_module.REWRITE_MODEL = rm
            disable_cache = bool(ov.get("disable_cache"))
        except Exception as e:
            print(f"rag_overrides error (ignored): {e}")

    try:
        return await _suggest_citations_impl(req, combined_facts, disable_cache)
    finally:
        if knob_backup is not None:
            import app.core.rag as rag_module
            for attr, val in knob_backup.items():
                setattr(rag_module, attr, val)


async def _suggest_citations_impl(req: GenerateRequest, combined_facts: str, disable_cache: bool):
    import hashlib
    from app.core.rag import rerank_multi
    from app.core.redis import cache_get, cache_set

    # Identical Step 6 input (incl. OCR context + search hint) → serve cached
    # suggestions. Users navigating back/forth re-trigger this endpoint with
    # the same payload and previously re-paid the full pipeline every time.
    cache_key = "suggest_citations:" + hashlib.md5(
        json.dumps([
            combined_facts, req.document_type, req.document_type_key,
            req.subject_matter, req.search_hint,
        ]).encode()
    ).hexdigest()
    if not disable_cache:
        try:
            cached = await cache_get(cache_key)
            if cached and isinstance(cached, dict) and cached.get("judgments") is not None:
                return cached
        except Exception as e:
            print(f"suggest-citations cache read error: {e}")

    queries = await rewrite_queries(
        combined_facts, req.document_type, req.subject_matter,
        search_hint=req.search_hint,
        document_type_key=req.document_type_key or "",
    )
    # Rerank query must stay short: the cross-encoder truncates query+passage at
    # ~512 tokens, so joining all 7 queries drowned the passage and produced
    # near-random scores. The first 3 queries carry the statutory + procedural core.
    combined_query = " ".join(queries[:3])

    try:
        embedding_fn = await _get_embedding_fn()

        # OPTIMIZATION: Batch compute all vectors once instead of sequentially
        from app.core.rag import _cpu_executor
        loop = asyncio.get_event_loop()
        vecs = await loop.run_in_executor(_cpu_executor, embedding_fn, queries)
        query_vectors = {q: (v.tolist() if hasattr(v, "tolist") else list(v)) for q, v in zip(queries, vecs)}

        judgment_task = retrieve_judgment_chunks(
            engine, queries, None,
            document_type_key=req.document_type_key,
            subject_matter=req.subject_matter,
            context="citations",
            query_vectors=query_vectors
        )
        statute_task  = retrieve_statutes(
            engine, queries, None,
            document_type_key=req.document_type_key,
            subject_matter=req.subject_matter,
            context="citations",
            query_vectors=query_vectors
        )
        # Only query the COI corpus when the subject matter is constitutionally
        # relevant (same gating as /generate) — the unconditional COI wave was
        # both wasted latency and Article noise in the suggestions.
        sm_lower_check = req.subject_matter.lower() if req.subject_matter else ""
        needs_coi = any(kw in sm_lower_check for kw in _SUBJECT_NEEDS_COI)
        coi_task = (
            retrieve_statutes(
                engine, queries, None, coi_only=True,
                document_type_key=req.document_type_key,
                context="citations",
                query_vectors=query_vectors
            )
            if needs_coi else asyncio.sleep(0)
        )

        judgment_results, statute_results, coi_results = await asyncio.gather(
            judgment_task, statute_task, coi_task
        )
        if not isinstance(coi_results, list):
            coi_results = []
        # Merge by retrieval score so COI hits compete on rank instead of being
        # appended after 30 statutes and silently cut off by the [:25] slice.
        seen_ids = set()
        merged_statutes = []
        for item in sorted(statute_results + coi_results, key=lambda x: x["score"], reverse=True):
            if item["id"] not in seen_ids:
                merged_statutes.append(item)
                seen_ids.add(item["id"])
    except Exception as e:
        print(f"Retrieval error: {e}")
        judgment_results, merged_statutes = [], []
        
    print(f"DEBUG - Queries: {queries}")
    print(f"DEBUG - Judgments retrieved: {len(judgment_results)}")
    print(f"DEBUG - Statutes retrieved: {len(merged_statutes)}")

    # Cross-encoder rerank — both lists scored in a single model call
    reranked = await rerank_multi(
        combined_query,
        groups={"judgments": judgment_results[:25], "statutes": merged_statutes[:25]},
        top_ks={"judgments": 8, "statutes": 8},
    )

    result = {
        "judgments": reranked["judgments"],
        "statutes": reranked["statutes"],
        "queries_used": queries
    }
    if not disable_cache:
        try:
            await cache_set(cache_key, result, ttl_seconds=6 * 3600)
        except Exception as e:
            print(f"suggest-citations cache write error: {e}")
    return result

