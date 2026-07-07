import asyncio
import os
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sentence_transformers import SentenceTransformer
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, engine
from app.models.judgment import Judgment

router = APIRouter(prefix="/search", tags=["search"])

# ---------------------------------------------------------------------------
# AI Model – lazily loaded, protected by an asyncio.Lock so that concurrent
# first-hit requests don't each try to load the ~400 MB model simultaneously.
# ---------------------------------------------------------------------------
_model: Optional[SentenceTransformer] = None
_model_lock = asyncio.Lock()


async def get_model() -> SentenceTransformer:
    """Return the singleton SentenceTransformer, loading it if necessary."""
    global _model
    if _model is None:
        async with _model_lock:
            # Double-checked locking: re-test inside the lock
            if _model is None:
                print("Loading Legal-BERT for API…")
                # run_in_executor keeps the blocking I/O off the event loop
                loop = asyncio.get_event_loop()
                _model = await loop.run_in_executor(
                    None,
                    lambda: SentenceTransformer("nlpaueb/legal-bert-base-uncased"),
                )
                print("Legal-BERT loaded.")
    return _model


# ---------------------------------------------------------------------------
# Helpers – run a raw SQL query on its OWN connection from the pool so that
# two coroutines can legitimately run in parallel via asyncio.gather().
# Each call acquires + releases a pooled connection independently, which is
# exactly what the connection pool is designed for.
# ---------------------------------------------------------------------------
async def _exec_query(sql: str, params: dict) -> list:
    """
    Execute *sql* with *params* on a fresh connection from the engine pool
    and return all rows.  Using engine.connect() gives us a dedicated
    connection, making it safe to call this concurrently with asyncio.gather().
    """
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        return result.fetchall()


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------
@router.get("/precedents")
async def search_precedents(
    q: Optional[str] = None,
    category: Optional[List[str]] = Query(None),
    year: Optional[List[int]] = Query(None),
    case_type: Optional[List[str]] = Query(None),
    acts_cited: Optional[List[str]] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    try:
        # ── Shared filter lists ──────────────────────────────────────────────
        filters = []
        if category:
            filters.append(Judgment.case_type.in_(category))
        if case_type:
            filters.append(Judgment.case_type.in_(case_type))
        if year:
            filters.append(Judgment.year.in_(year))

        judgments: list = []
        total_items: int = 0

        # ── Branch: semantic + keyword hybrid search ─────────────────────────
        if q:
            ai_model = await get_model()

            # Encode on the thread pool so the event loop is not blocked
            loop = asyncio.get_event_loop()
            query_vector = await loop.run_in_executor(
                None, lambda: ai_model.encode(q).tolist()
            )

            # ── Build SQL ────────────────────────────────────────────────────
            # Combined filter clause reused in both queries
            extra_sql = ""
            shared_params: dict = {}
            types: List[str] = []

            if category or case_type:
                types = (category or []) + (case_type or [])
                extra_sql += " AND case_type = ANY(:types)"
                shared_params["types"] = types
            if year:
                extra_sql += " AND year = ANY(:years)"
                shared_params["years"] = year

            # Vector (pgvector cosine distance) search
            vector_sql = f"""
                SELECT id,
                       ROW_NUMBER() OVER (ORDER BY embedding <-> :q_vec) AS rank
                FROM   judgments
                WHERE  embedding IS NOT NULL
                {extra_sql}
                ORDER  BY rank
                LIMIT  50
            """
            vector_params = {"q_vec": str(query_vector), **shared_params}

            # Full-text (tsvector / BM25-proxy) search
            keyword_sql = f"""
                SELECT id,
                       ROW_NUMBER() OVER (
                           ORDER BY ts_rank(search_vector,
                                            websearch_to_tsquery('english', :q)) DESC
                       ) AS rank
                FROM   judgments
                WHERE  search_vector @@ websearch_to_tsquery('english', :q)
                {extra_sql}
                ORDER  BY rank
                LIMIT  50
            """
            keyword_params = {"q": q, **shared_params}

            # ── True parallel execution on separate pool connections ──────────
            # Each _exec_query() call acquires its own connection from
            # engine's connection pool, so asyncio.gather() is safe here.
            vec_rows, kw_rows = await asyncio.gather(
                _exec_query(vector_sql, vector_params),
                _exec_query(keyword_sql, keyword_params),
            )

            semantic_ranks = {row.id: row.rank for row in vec_rows}
            keyword_ranks = {row.id: row.rank for row in kw_rows}

            # ── Reciprocal Rank Fusion (RRF) ─────────────────────────────────
            # Keyword results get a 2× multiplier so that exact legal citations
            # (e.g. "Section 302 IPC") always outrank purely semantic matches.
            all_ids = set(semantic_ranks) | set(keyword_ranks)
            rrf_scores: dict = {}
            for j_id in all_ids:
                score = 0.0
                if j_id in semantic_ranks:
                    score += 1.0 / (60 + semantic_ranks[j_id])
                if j_id in keyword_ranks:
                    score += 2.0 / (60 + keyword_ranks[j_id])
                rrf_scores[j_id] = score

            sorted_ids = sorted(rrf_scores, key=rrf_scores.__getitem__, reverse=True)
            total_items = len(sorted_ids)

            # ── Paginate & fetch full rows ────────────────────────────────────
            start_idx = (page - 1) * limit
            paginated_ids = sorted_ids[start_idx : start_idx + limit]

            if paginated_ids:
                db_res = await db.execute(
                    select(Judgment).where(Judgment.id.in_(paginated_ids))
                )
                db_judgments = db_res.scalars().all()
                id_to_judgment = {j.id: j for j in db_judgments}
                judgments = [
                    id_to_judgment[j_id]
                    for j_id in paginated_ids
                    if j_id in id_to_judgment
                ]

        # ── Branch: browse / filter only (no query) ──────────────────────────
        else:
            base_query = select(Judgment)
            for f in filters:
                base_query = base_query.where(f)

            count_query = select(func.count()).select_from(base_query.subquery())
            total_items = (await db.execute(count_query)).scalar() or 0

            paginated_query = (
                base_query
                .order_by(Judgment.year.desc().nulls_last(), Judgment.id.asc())
                .offset((page - 1) * limit)
                .limit(limit)
            )
            judgments = (await db.execute(paginated_query)).scalars().all()

        # ── Facet counts ──────────────────────────────────────────────────────
        facet_case_type: dict = {}
        facet_year: dict = {}

        base_query = select(Judgment)
        for f in filters:
            base_query = base_query.where(f)

        ct_query = (
            select(Judgment.case_type, func.count())
            .select_from(base_query.subquery())
            .group_by(Judgment.case_type)
        )
        for row in (await db.execute(ct_query)).all():
            if row[0]:
                facet_case_type[row[0]] = row[1]

        # ── Serialise response ────────────────────────────────────────────────
        items = []
        for j in judgments:
            title = (
                f"{j.petitioner} v. {j.respondent}"
                if j.petitioner and j.respondent
                else "Unknown v. Unknown"
            )
            items.append(
                {
                    "id": j.id,
                    "title": title,
                    "year": j.year or "N/A",
                    "case_type": j.case_type or "General",
                    "summary": j.summary or "",
                    "court": "SC",
                    "binding_on": (
                        "All High Courts & District Courts"
                        if "Constitutional" in (j.case_type or "")
                        else "Relevant Subordinate Courts"
                    ),
                }
            )

        return {
            "items": items,
            "total": total_items,
            "page": page,
            "limit": limit,
            "total_pages": (total_items + limit - 1) // limit if limit else 0,
            "facets": {
                "case_type": facet_case_type,
                "year": facet_year,
            },
        }

    except Exception as exc:
        # Surface a clean 500 with context instead of leaking stack traces
        raise HTTPException(
            status_code=500,
            detail=f"Search failed: {exc}",
        ) from exc
