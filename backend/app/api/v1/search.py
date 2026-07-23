import asyncio
import os
import re
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
                loop = asyncio.get_event_loop()

                def _load():
                    from sentence_transformers import models as st_models
                    import os

                    # Use baked-in cache if available (set in Dockerfile),
                    # otherwise fall back to default HuggingFace cache.
                    cache_dir = os.environ.get("SENTENCE_TRANSFORMERS_HOME") or None

                    # Build via modules API — never calls .to(device) on meta tensors.
                    # low_cpu_mem_usage=False loads weights directly into CPU RAM.
                    transformer = st_models.Transformer(
                        "nlpaueb/legal-bert-base-uncased",
                        cache_dir=cache_dir,
                        model_args={"low_cpu_mem_usage": False},
                    )
                    pooling = st_models.Pooling(
                        transformer.get_word_embedding_dimension(),
                        pooling_mode_mean_tokens=True,
                    )
                    return SentenceTransformer(
                        modules=[transformer, pooling],
                        cache_folder=cache_dir,
                    )

                _model = await loop.run_in_executor(None, _load)
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


_LEGAL_ABBREVS = {"IPC", "BNS", "CRPC", "BNSS", "COI", "SCC", "AIR",
                  "CPC", "SRA", "NDPS", "POCSO", "IBC", "GST", "CBI", "PMLA", "BSA"}

def _get_ts_config(query: str) -> str:
    words = query.strip().upper().split()
    if any(w in _LEGAL_ABBREVS for w in words) or len(words) <= 3:
        return "simple"
    return "english"

LEGAL_EXPANSIONS = {
    "IPC": "Indian Penal Code",
    "CrPC": "Code of Criminal Procedure",
    "BNSS": "Bharatiya Nagarik Suraksha Sanhita",
    "BNS": "Bharatiya Nyaya Sanhita",
    "BSA": "Bharatiya Sakshya Adhiniyam",
    "CPC": "Code of Civil Procedure",
    "NI Act": "Negotiable Instruments Act",
    "POCSO": "Protection of Children from Sexual Offences",
}

def expand_query(q: str) -> str:
    expanded = q
    for abbrev, full in LEGAL_EXPANSIONS.items():
        if abbrev.lower() in q.lower() and full.lower() not in q.lower():
            expanded += f" {full}"
    return expanded

def classify_query(q: str) -> str:
    if re.search(r'\d{4}\s+SCC\s+\d+|\d{4}\s+AIR\s+SC', q, re.I):
        return "citation"
    if re.search(r'section\s+\d+[A-Z]?\s+(of\s+)?\w+', q, re.I):
        return "section_ref"
    if ' v. ' in q or ' vs ' in q.lower() or ' versus ' in q.lower():
        return "party_name"
    return "concept"


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
        if acts_cited:
            # PostgreSQL ARRAY overlap: any of the selected acts must appear in acts_cited
            filters.append(Judgment.acts_cited.overlap(acts_cited))

        judgments: list = []
        total_items: int = 0
        rrf_scores: dict = {}

        # ── Branch: semantic + keyword hybrid search ─────────────────────────
        if q:
            q_type = classify_query(q)
            expanded_q = expand_query(q)

            ai_model = await get_model()

            # Encode on the thread pool so the event loop is not blocked
            loop = asyncio.get_event_loop()
            query_vector = await loop.run_in_executor(
                None, lambda: ai_model.encode(expanded_q).tolist()
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
                SELECT id, embedding <=> :q_vec AS dist
                FROM   judgments
                WHERE  embedding IS NOT NULL
                {extra_sql}
                ORDER  BY embedding <=> :q_vec
                LIMIT  50
            """
            vector_params = {"q_vec": str(query_vector), **shared_params}

            ts_cfg = _get_ts_config(expanded_q)
            # Full-text (tsvector / BM25-proxy) search
            keyword_sql = f"""
                SELECT id, 
                       ts_rank_cd(search_vector, websearch_to_tsquery('{ts_cfg}', :expanded_q)) +
                       ts_rank_cd(search_vector, phraseto_tsquery('{ts_cfg}', :original_q)) AS score
                FROM   judgments
                WHERE  search_vector @@ websearch_to_tsquery('{ts_cfg}', :expanded_q)
                {extra_sql}
                ORDER  BY score DESC
                LIMIT  50
            """
            keyword_params = {"expanded_q": expanded_q, "original_q": q, **shared_params}

            # ── Title Match ──────────────────────────────────────────────────
            pet_pat = f"%{q.strip()}%"
            res_pat = f"%{q.strip()}%"
            if " v. " in q.lower() or " vs " in q.lower() or " versus " in q.lower():
                parts = re.split(r'\s+v\.\s+|\s+vs\s+|\s+versus\s+', q, flags=re.IGNORECASE)
                pet_pat = f"%{parts[0].strip()}%"
                if len(parts) > 1:
                    res_pat = f"%{parts[1].strip()}%"
                
                title_match_sql = f"""
                    SELECT id
                    FROM judgments
                    WHERE (petitioner ILIKE :pet AND respondent ILIKE :res)
                       OR (petitioner ILIKE :res AND respondent ILIKE :pet)
                    {extra_sql}
                    LIMIT 20
                """
                title_params = {"pet": pet_pat, "res": res_pat, **shared_params}
            else:
                title_match_sql = f"""
                    SELECT id
                    FROM judgments
                    WHERE petitioner ILIKE :pat OR respondent ILIKE :pat OR case_number ILIKE :pat
                    {extra_sql}
                    LIMIT 20
                """
                title_params = {"pat": f"%{q.strip()}%", **shared_params}

            # ── True parallel execution on separate pool connections ──────────
            # Each _exec_query() call acquires its own connection from
            # engine's connection pool, so asyncio.gather() is safe here.
            vec_rows, kw_rows, title_rows = await asyncio.gather(
                _exec_query(vector_sql, vector_params),
                _exec_query(keyword_sql, keyword_params),
                _exec_query(title_match_sql, title_params),
            )
            
            # ── Typo Fallback for Keyword Search ─────────────────────────────
            # If a concept query has very few keyword matches (e.g. < 10), it's likely a typo 
            # (e.g., "warrent") or too strict. We run a relaxed OR query to rescue the search.
            if len(kw_rows) < 10 and q_type == "concept":
                words = [w for w in re.split(r'\W+', q) if len(w) > 2]
                if len(words) > 1:
                    or_query = " | ".join(words)
                    fallback_sql = f"""
                        SELECT id, ts_rank_cd(search_vector, to_tsquery('{ts_cfg}', :or_q)) AS score
                        FROM   judgments
                        WHERE  search_vector @@ to_tsquery('{ts_cfg}', :or_q)
                        {extra_sql}
                        ORDER  BY score DESC
                        LIMIT  50
                    """
                    kw_rows = await _exec_query(fallback_sql, {"or_q": or_query, **shared_params})

            # Assign ranks based on the returned order
            semantic_ranks = {row.id: i + 1 for i, row in enumerate(vec_rows)}
            keyword_ranks = {row.id: i + 1 for i, row in enumerate(kw_rows)}
            title_matches = {row.id for row in title_rows}

            # ── Adaptive Reciprocal Rank Fusion (RRF) ────────────────────────
            # Adjust weights dynamically based on query classification
            sem_weight = 1.0
            kw_weight = 2.0  # default favors keyword exact match
            
            if q_type == "citation":
                sem_weight, kw_weight = 0.5, 4.0  # Must match exact citation
            elif q_type == "party_name":
                sem_weight, kw_weight = 0.5, 3.0  # Names don't embed well
            elif q_type == "concept":
                # Since the current model is an MLM (not STS fine-tuned), it generates
                # highly anisotropic embeddings (noise). We must prioritize keyword match 
                # (especially typo-fallback OR matches) over semantic rank.
                sem_weight, kw_weight = 0.5, 3.0
            elif q_type == "section_ref":
                sem_weight, kw_weight = 1.0, 2.0  # Balanced

            all_ids = set(semantic_ranks) | set(keyword_ranks) | title_matches
            rrf_scores: dict = {}
            for j_id in all_ids:
                score = 0.0
                if j_id in semantic_ranks:
                    score += sem_weight / (60 + semantic_ranks[j_id])
                if j_id in keyword_ranks:
                    score += kw_weight / (60 + keyword_ranks[j_id])
                if j_id in title_matches:
                    score += 5.0  # Massive boost for direct title matches
                rrf_scores[j_id] = score

            sorted_ids = sorted(rrf_scores, key=rrf_scores.__getitem__, reverse=True)
            total_items = len(sorted_ids)

            # ── Paginate & fetch full rows ────────────────────────────────────
            start_idx = (page - 1) * limit
            paginated_ids = sorted_ids[start_idx : start_idx + limit]

            if paginated_ids:
                db_res = await db.execute(
                    select(
                        Judgment.id, Judgment.petitioner, Judgment.respondent,
                        Judgment.year, Judgment.case_type, Judgment.summary,
                        Judgment.case_number,
                        func.ts_headline(
                            'english', 
                            func.coalesce(Judgment.summary, '') + ' ' + func.coalesce(Judgment.holding, ''),
                            func.websearch_to_tsquery(ts_cfg, expanded_q),
                            'MaxFragments=2, MaxWords=30, MinWords=10'
                        ).label("snippet")
                    ).where(Judgment.id.in_(paginated_ids))
                )
                db_judgments = db_res.mappings().all()
                id_to_judgment = {j["id"]: j for j in db_judgments}
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

            count_query = select(func.count(Judgment.id))
            for f in filters:
                count_query = count_query.where(f)
            total_items = (await db.execute(count_query)).scalar() or 0

            paginated_ids_query = (
                base_query.with_only_columns(Judgment.id)
                .order_by(Judgment.year.desc().nulls_last(), Judgment.id.asc())
                .offset((page - 1) * limit)
                .limit(limit)
            )
            paginated_ids = (await db.execute(paginated_ids_query)).scalars().all()

            if paginated_ids:
                judgments_query = select(
                    Judgment.id, Judgment.petitioner, Judgment.respondent,
                    Judgment.year, Judgment.case_type, Judgment.summary,
                    Judgment.case_number
                ).where(Judgment.id.in_(paginated_ids))
                judgments_unsorted = (await db.execute(judgments_query)).mappings().all()
                judgments_dict = {j["id"]: j for j in judgments_unsorted}
                judgments = [judgments_dict[jid] for jid in paginated_ids if jid in judgments_dict]
            else:
                judgments = []

        # ── Facet counts ──────────────────────────────────────────────────────
        facet_case_type: dict = {}
        facet_year: dict = {}

        base_query = select(Judgment)
        for f in filters:
            base_query = base_query.where(f)

        ct_query = (
            select(Judgment.case_type, func.count())
            .group_by(Judgment.case_type)
        )
        for f in filters:
            ct_query = ct_query.where(f)

        for row in (await db.execute(ct_query)).all():
            if row[0]:
                facet_case_type[row[0]] = row[1]

        # ── Serialise response ────────────────────────────────────────────────
        items = []
        for j in judgments:
            petitioner = j["petitioner"] if isinstance(j, dict) else j.petitioner
            respondent  = j["respondent"]  if isinstance(j, dict) else j.respondent
            year        = j["year"]        if isinstance(j, dict) else j.year
            case_type   = j["case_type"]   if isinstance(j, dict) else j.case_type
            summary     = j["summary"]     if isinstance(j, dict) else j.summary
            snippet     = j.get("snippet") if isinstance(j, dict) else getattr(j, "snippet", None)
            case_number = j.get("case_number") if isinstance(j, dict) else getattr(j, "case_number", None)
            jid         = j["id"]          if isinstance(j, dict) else j.id
            
            if petitioner and respondent:
                title = f"{petitioner} v. {respondent}"
            elif case_number:
                title = case_number
            else:
                title = "Unknown v. Unknown"

            items.append(
                {
                    "id": jid,
                    "title": title,
                    "year": year or "N/A",
                    "case_type": case_type or "General",
                    "summary": summary or "",
                    "snippet": snippet or "",
                    "relevance": round(rrf_scores.get(jid, 0.0) * 10, 2) if jid in rrf_scores else None,
                    "court": "SC",
                    "binding_on": (
                        "All High Courts & District Courts"
                        if "Constitutional" in (case_type or "")
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


from fastapi import BackgroundTasks
def _do_embed_batch(model, texts):
    return model.encode(texts).tolist()

async def _embed_statutes_task():
    model = await get_model()
    from app.core.database import engine
    from sqlalchemy import text
    import concurrent.futures
    import asyncio
    
    with open("embed_log.txt", "a") as f:
        f.write("Starting background statute embedding...\n")
        f.flush()
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        try:
            async with engine.begin() as conn:
                res = await conn.execute(text("SELECT id, section_text, title FROM legal_code_sections WHERE embedding IS NULL"))
                rows = res.fetchall()
            
            if not rows:
                with open("embed_log.txt", "a") as f:
                    f.write("All statutes already embedded.\n")
                return
                
            batch_size = 50
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i+batch_size]
                texts = [f"{r.title or ''}. {r.section_text or ''}" for r in batch]
                
                # Run the blocking PyTorch encode in a thread pool so we don't hang the server!
                vectors = await loop.run_in_executor(pool, _do_embed_batch, model, texts)
                
                async with engine.begin() as conn:
                    for idx, r in enumerate(batch):
                        await conn.execute(
                            text("UPDATE legal_code_sections SET embedding = :emb WHERE id = :id"),
                            {"emb": str(vectors[idx]), "id": r.id}
                        )
                with open("embed_log.txt", "a") as f:
                    f.write(f"Embedded batch {i//batch_size + 1} / {(len(rows) + batch_size - 1) // batch_size}\n")
                    f.flush()
            with open("embed_log.txt", "a") as f:
                f.write("Done embedding all statutes!\n")
        except Exception as e:
            with open("embed_log.txt", "a") as f:
                import traceback
                f.write(f"Embedding failed: {e}\n{traceback.format_exc()}\n")

@router.post("/trigger-statute-embedding")
async def trigger_embedding(background_tasks: BackgroundTasks):
    background_tasks.add_task(_embed_statutes_task)
    return {"status": "started background task"}
