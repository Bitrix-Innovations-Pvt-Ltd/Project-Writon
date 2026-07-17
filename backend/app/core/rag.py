"""
core/rag.py — Multi-Corpus Hybrid RAG Pipeline for Step 6 (Generate)

Stages:
  1. Query Rewriting       (GPT-4o-mini) — expanded doc-type hints for all types
  2 & 3. Fan-out Hybrid Retrieval  (BM25 + pgvector + RRF, parallel, 3 corpora)
         — USE_CHUNKS flag: False=judgments table (now), True=judgment_chunks (after pipeline)
         — context-aware RRF weights: 'citations' mode uses balanced 1.5x each
         — subject-matter case_type + statute_code filters for citation context
  4. Cross-Encoder Reranking (ms-marco-MiniLM-L-6-v2)
         — re-enabled for suggest-citations (use_cross_encoder=True)
         — bypassed for streaming /generate to prevent proxy timeouts
  5. Context Assembly
  6. Citation Verification (post-generation, regex + SQL)
"""

import asyncio
import json
import os
import re
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv(os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    ".env"
))

openrouter_key = os.getenv("OPENROUTER_API_KEY")

# ---------------------------------------------------------------------------
# Shared clients — lazy-loaded singletons
# ---------------------------------------------------------------------------
_openrouter_client: Optional[AsyncOpenAI] = None
_reranker = None
_reranker_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# USE_CHUNKS flag — flip to True once judgment_chunks table is populated
# (chunking pipeline has been run). No other code change needed.
# ---------------------------------------------------------------------------
USE_CHUNKS = False


# ===========================================================================
# Subject-matter helpers — derive case_type + statute code filters
# ===========================================================================

# Maps document_type_key → likely judgment case_type values in DB
_DOC_TYPE_CASE_TYPES: dict = {
    "writ_petition_civil":    ["Writ Petition", "Civil Appeal", "Special Leave Petition", "Transfer Petition", "Petition", "Review Petition", "Curative Petition", "Original Suit", "Appeal", "Slp"],
    "writ_petition_criminal": ["Writ Petition", "Criminal Appeal", "Special Leave Petition", "Transfer Petition", "Petition", "Review Petition", "Curative Petition", "Appeal", "Slp"],
    "bail_application":       ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"],
    "anticipatory_bail":      ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"],
    "civil_appeal":           ["Civil Appeal", "Special Leave Petition", "Transfer Petition", "Appeal", "Review Petition", "Curative Petition", "Slp"],
    "criminal_appeal":        ["Criminal Appeal", "Special Leave Petition", "Transfer Petition", "Appeal", "Review Petition", "Curative Petition", "Slp"],
    "writ_petition":          ["Writ Petition", "Civil Appeal", "Criminal Appeal", "Special Leave Petition", "Transfer Petition", "Petition", "Review Petition", "Curative Petition", "Original Suit", "Appeal", "Slp"],
}

_DOC_TYPE_STATUTE_CODES: dict = {
    "writ_petition_civil":    ["COI", "CPC", "SRA", "BSA"],
    "writ_petition_criminal": ["COI", "CrPC", "BNSS", "IPC", "BNS", "BSA"],
    "bail_application":       ["CrPC", "BNSS", "IPC", "BNS", "BSA"],
    "anticipatory_bail":      ["CrPC", "BNSS", "BSA"],
    "civil_appeal":           ["CPC", "COI", "BSA"],
    "criminal_appeal":        ["CrPC", "BNSS", "IPC", "BNS", "BSA"],
    "writ_petition":          ["COI", "CPC", "CrPC", "BNSS", "BSA"],
}

# Keyword-based overrides for subject matter
_SUBJECT_CASE_TYPE_OVERRIDES = [
    ("service law",   ["Civil Appeal", "Writ Petition", "Special Leave Petition", "Petition", "Appeal", "Slp"]),
    ("property",      ["Civil Appeal", "Writ Petition", "Special Leave Petition", "Petition", "Original Suit", "Appeal", "Slp"]),
    ("land",          ["Civil Appeal", "Writ Petition", "Special Leave Petition", "Petition", "Original Suit", "Appeal", "Slp"]),
    ("labour",        ["Civil Appeal", "Writ Petition", "Special Leave Petition", "Petition", "Appeal", "Slp"]),
    ("employment",    ["Civil Appeal", "Writ Petition", "Special Leave Petition", "Petition", "Appeal", "Slp"]),
    ("cheque",        ["Criminal Appeal", "Civil Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]),
    ("matrimonial",   ["Civil Appeal", "Criminal Appeal", "Special Leave Petition", "Transfer Petition", "Petition", "Appeal", "Slp"]),
    ("divorce",       ["Civil Appeal", "Special Leave Petition", "Transfer Petition", "Petition", "Appeal", "Slp"]),
    ("custody",       ["Civil Appeal", "Criminal Appeal", "Special Leave Petition", "Transfer Petition", "Petition", "Appeal", "Slp"]),
    ("company",       ["Civil Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]),
    ("insolvency",    ["Civil Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]),
    ("ibc",           ["Civil Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]),
    ("tax",           ["Civil Appeal", "Writ Petition", "Special Leave Petition", "Petition", "Appeal", "Slp"]),
    ("consumer",      ["Civil Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]),
    ("rape",          ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]),
    ("murder",        ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]),
    ("dowry",         ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]),
    ("corruption",    ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]),
    ("ndps",          ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]),
    ("pocso",         ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]),
]


def _derive_case_type_filter(document_type_key: str, subject_matter: str) -> list:
    """Return case_type values to filter judgments by, or [] for no filter."""
    base = list(_DOC_TYPE_CASE_TYPES.get(document_type_key, []))
    if subject_matter:
        sm_lower = subject_matter.lower()
        for keyword, types in _SUBJECT_CASE_TYPE_OVERRIDES:
            if keyword in sm_lower:
                for t in types:
                    if t not in base:
                        base.append(t)
    return base


def _derive_statute_codes(document_type_key: str) -> list:
    """Return preferred statute short_codes for this document type."""
    return list(_DOC_TYPE_STATUTE_CODES.get(document_type_key, []))


def _get_ts_config(query: str) -> str:
    """
    Return 'simple' for abbreviation-heavy queries so Indian legal terms
    (IPC, CrPC, BNSS etc.) are not stripped by the 'english' stop-word list.
    """
    abbrevs = {"IPC", "BNS", "CRPC", "BNSS", "COI", "SCC", "AIR",
               "CPC", "SRA", "NDPS", "POCSO", "IBC", "GST", "CBI", "BSA"}
    words = query.strip().upper().split()
    if any(w in abbrevs for w in words) or len(words) <= 3:
        return "simple"
    return "english"


def get_openrouter_client() -> AsyncOpenAI:
    global _openrouter_client
    if _openrouter_client is None:
        _openrouter_client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=openrouter_key or "DUMMY"
        )
    return _openrouter_client


async def load_reranker():
    """Load the cross-encoder reranker. Called on server startup (non-blocking)."""
    global _reranker
    if _reranker is None:
        async with _reranker_lock:
            if _reranker is None:
                print("Loading cross-encoder reranker (ms-marco-MiniLM-L-6-v2)...")
                from sentence_transformers import CrossEncoder
                loop = asyncio.get_event_loop()
                import torch
                _reranker = await loop.run_in_executor(
                    None,
                    lambda: CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", device="cpu", automodel_args={"torch_dtype": torch.float32})
                )
                print("Cross-encoder reranker loaded.")
    return _reranker


# ---------------------------------------------------------------------------
# Internal helper: run raw SQL on a dedicated pool connection (safe for gather)
# ---------------------------------------------------------------------------
async def _exec_raw(engine, sql: str, params: dict) -> list:
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        return result.fetchall()


# ===========================================================================
# STAGE 1 — Query Rewriting  (GPT-4o-mini, cheap task)
# ===========================================================================
async def rewrite_queries(
    facts: str,
    doc_type: str,
    subject_matter: str,
    search_hint: str = "",
) -> list:
    """
    Generate 7 targeted search queries for the given case facts.
    search_hint: optional user-provided refinement (e.g. 'Section 41A CrPC wrongful arrest').
    """
    client = get_openrouter_client()
    if not openrouter_key:
        return [facts[:200]]

    doc_lower = doc_type.lower()
    sm_lower  = subject_matter.lower()

    # ── Build a rich, doc-type-aware hint covering all document types ─────
    doc_hint = ""

    if "anticipatory bail" in doc_lower:
        doc_hint = (
            "This is an anticipatory bail application. "
            "Ensure queries target: (a) Section 438 CrPC / Section 482 BNSS anticipatory bail grounds, "
            "(b) factors for grant/refusal (flight risk, evidence tampering, gravity of offence), "
            "(c) landmark precedents: Gurbaksh Singh Sibbia, Sushila Aggarwal, Siddharam Satlingappa, "
            "(d) conditions that may be imposed on anticipatory bail."
        )
    elif "bail" in doc_lower:
        doc_hint = (
            "This is a bail application. "
            "Ensure queries target: (a) Section 437/439 CrPC / Section 480/483 BNSS bail grounds, "
            "(b) triple-test for bail (flight risk, tampering, repeat offence), "
            "(c) parity with co-accused bail doctrine, "
            "(d) landmark bail precedents: Arnesh Kumar, Dataram Singh, Prasanta Kumar Sarkar."
        )
    elif "criminal appeal" in doc_lower:
        doc_hint = (
            "This is a criminal appeal. "
            "Ensure queries target: (a) perverse appreciation of evidence by trial court, "
            "(b) Section 374/377 CrPC / Section 415 BNSS appellate jurisdiction, "
            "(c) benefit of doubt / presumption of innocence at appellate stage, "
            "(d) re-appreciation of witness testimony and circumstantial evidence standards."
        )
    elif "civil appeal" in doc_lower:
        doc_hint = (
            "This is a civil appeal. "
            "Ensure queries target: (a) Section 96/100 CPC first and second appeal grounds, "
            "(b) question of law vs fact distinction for second appeal, "
            "(c) perversity of findings and misreading of evidence, "
            "(d) Section 115 CPC revision jurisdiction."
        )
    elif "quash" in doc_lower:
        doc_hint = (
            "This is a writ / FIR-quashing petition. "
            "Ensure queries target: (a) Section 41-A CrPC/BNSS non-compliance and wrongful arrest, "
            "(b) abuse of process / civil-vs-criminal remedy doctrine, "
            "(c) Section 482 CrPC / Section 528 BNSS inherent powers jurisprudence, "
            "(d) Bhajan Lal categories for quashing FIR."
        )
    elif "writ" in doc_lower and "criminal" in doc_lower:
        doc_hint = (
            "This is a criminal writ petition under Article 226. "
            "Ensure queries target: (a) Articles 21, 22 — personal liberty and due process, "
            "(b) illegal detention / habeas corpus, "
            "(c) Section 482 CrPC / BNSS inherent powers, "
            f"(d) the specific criminal issue: {subject_matter}."
        )
    elif "pil" in doc_lower or "public interest" in doc_lower:
        doc_hint = (
            "This is a Public Interest Litigation (PIL). "
            "Ensure queries target: (a) locus standi for PIL petitioners, "
            "(b) Article 32 / 226 scope for PILs, "
            "(c) the specific public law issue raised in facts, "
            "(d) landmark PIL precedents: Bandhua Mukti Morcha, Hussainara Khatoon, Vishaka."
        )
    elif "writ" in doc_lower or "226" in doc_lower or "32" in doc_lower:
        # Civil writ — tailor to subject matter
        doc_hint = (
            f"This is a civil writ petition (Article 226/32). Subject: {subject_matter}. "
            "Ensure queries target: (a) scope of writ jurisdiction and alternative remedy doctrine, "
            "(b) the specific relief (mandamus, certiorari, prohibition, quo warranto), "
        )
        if "service" in sm_lower or "employment" in sm_lower:
            doc_hint += (
                "(c) service law — Articles 14, 16, 311, natural justice in departmental inquiry, "
                "(d) reinstatement, back wages, wrongful termination precedents."
            )
        elif "property" in sm_lower or "land" in sm_lower:
            doc_hint += (
                "(c) property rights, Article 300-A, land acquisition compensation, "
                "(d) mutation of revenue records, adverse possession, easement rights."
            )
        elif "tax" in sm_lower:
            doc_hint += (
                "(c) Income Tax Act / GST Act assessment and recovery, stay of demand, "
                "(d) Section 220 IT Act, principles of natural justice in tax proceedings."
            )
        elif "labour" in sm_lower:
            doc_hint += (
                "(c) Industrial Disputes Act, workman reinstatement, Section 25-F retrenchment, "
                "(d) unfair labour practice, award of labour court."
            )
        elif "cheque" in sm_lower:
            doc_hint += (
                "(c) Section 138/141 Negotiable Instruments Act, statutory notice requirements, "
                "(d) Section 139 NI Act presumptions, compounding under Section 147 NI Act."
            )
        elif "matrimonial" in sm_lower or "divorce" in sm_lower:
            doc_hint += (
                "(c) Hindu Marriage Act / Special Marriage Act grounds for divorce, "
                "(d) maintenance under Section 125 CrPC / Section 144 BNSS, custody principles."
            )
        elif "consumer" in sm_lower:
            doc_hint += (
                "(c) Consumer Protection Act, deficiency of service, unfair trade practice, "
                "(d) NCDRC / State Commission jurisdiction and procedure."
            )
        else:
            doc_hint += f"(c) constitutional and statutory basis for the relief sought in {subject_matter}."
    elif "slp" in doc_lower or "special leave" in doc_lower:
        doc_hint = (
            "This is a Special Leave Petition under Article 136. "
            "Ensure queries target: (a) Article 136 scope and limitations, "
            "(b) interference with concurrent findings of fact by SC, "
            f"(c) substantial question of law for SLP admission, (d) the underlying dispute: {subject_matter}."
        )
    elif "insolvency" in doc_lower or "ibc" in doc_lower or "nclt" in doc_lower:
        doc_hint = (
            "This is an insolvency / IBC petition. "
            "Ensure queries target: (a) Section 7/9/10 IBC financial/operational creditor claims, "
            "(b) CIRP initiation thresholds and timelines, "
            "(c) moratorium under Section 14 IBC, "
            "(d) NCLT/NCLAT jurisdiction and procedure."
        )

    # Fallback for unmatched types — use subject matter directly
    if not doc_hint:
        doc_hint = (
            f"Document Type: {doc_type}. Subject Matter: {subject_matter}. "
            "Ensure queries are tightly focused on the specific legal issues in the subject matter. "
            "Avoid broad generic constitutional queries unless fundamental rights are directly violated."
        )

    # Prepend user-provided search_hint if given
    hint_line = f"\nUser search refinement (incorporate this): {search_hint}" if search_hint else ""

    try:
        response = await client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert Indian legal researcher. Given a case description, "
                        "generate exactly 7 distinct, highly-optimized search queries to retrieve relevant Indian court judgments and statutes. "
                        "To maximize recall, the queries MUST target different retrieval angles:\n"
                        "1. Statutory provisions violated (specific section + Act spelled out fully, e.g., 'Section 302 Indian Penal Code')\n"
                        "2. Procedural violations specific to this case type\n"
                        "3. Legal doctrine / principles directly applicable to the facts\n"
                        "4. Relevant Supreme Court / High Court landmark judgment names + holding\n"
                        "5. Constitutional violations (only if actually raised)\n"
                        "6. Practical filing grounds for this specific document type\n"
                        "7. Factual pattern: key parties, disputed events, and legal consequence\n"
                        "CRITICAL: Do NOT generate near-duplicate queries. "
                        "CRITICAL: Spell out full Act names in at least 3 queries for keyword search coverage. "
                        "CRITICAL: Stay focused on the subject matter — avoid broad generic queries. "
                        "Return ONLY a JSON object with key 'queries' containing an array of exactly 7 strings."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Document Type: {doc_type}\n"
                        f"Subject Matter: {subject_matter}\n"
                        f"{doc_hint}"
                        f"{hint_line}\n\n"
                        f"Facts/Description:\n{facts[:2000]}"
                    )
                }
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        result = json.loads(response.choices[0].message.content)
        queries = result.get("queries", result.get("search_queries", [facts[:200]]))
        return [q for q in queries if isinstance(q, str)][:7]
    except Exception as e:
        print(f"Query rewriting failed: {e}")
        return [facts[:200]]


# ===========================================================================
# STAGES 2 & 3 — Fan-out Hybrid Retrieval (BM25 + pgvector + RRF, parallel)
# ===========================================================================

import concurrent.futures
_cpu_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

async def retrieve_judgment_chunks(
    engine,
    queries: list,
    embedding_fn=None,
    document_type_key: str = "",
    subject_matter: str = "",
    context: str = "search",   # "search" | "citations"
    query_vectors: dict = None,
) -> list:
    """
    Hybrid search over judgments (or judgment_chunks when USE_CHUNKS=True).
    Returns up to 30 ranked candidates.

    context="citations" uses balanced RRF weights (1.5x each).
    context="search"    uses keyword-heavy weights (1x sem, 2x kw) for exact-match recall.
    """
    all_results = {}

    # Derive case_type filter for citation context
    case_type_filter = _derive_case_type_filter(document_type_key, subject_matter) if document_type_key else []
    sem_weight = 1.5 if context == "citations" else 1.0
    kw_weight  = 1.5 if context == "citations" else 2.0

    for query in queries:
        try:
            if query_vectors and query in query_vectors:
                vec_list = query_vectors[query]
            elif embedding_fn:
                loop = asyncio.get_event_loop()
                vec = await loop.run_in_executor(_cpu_executor, embedding_fn, query)
                vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)
            else:
                continue

            # ── Case-type filter clause ──────────────────────────────────
            ct_filter_sql = ""
            params_shared: dict = {}
            if case_type_filter and context == "citations":
                ct_filter_sql = " AND (j.case_type = ANY(:case_types) OR j.case_type IS NULL)"
                params_shared["case_types"] = case_type_filter

            # ── Vector (semantic) search ─────────────────────────────────
            if USE_CHUNKS:
                # Phase 2 — per-chunk embeddings (more precise)
                vector_sql = f"""
                    SELECT jc.id AS chunk_id,
                           jc.judgment_id AS id,
                           j.case_number, j.petitioner, j.respondent, j.year, j.case_type,
                           COALESCE(j.summary, '') || ' ' || COALESCE(j.holding, '') || ' '
                               || SUBSTRING(jc.chunk_text, 1, 1200) AS chunk_text,
                           jc.embedding <-> :q_vec AS distance
                    FROM   judgment_chunks jc
                    JOIN   judgments j ON j.id = jc.judgment_id
                    WHERE  jc.embedding IS NOT NULL
                    {ct_filter_sql}
                    ORDER  BY distance
                    LIMIT  30
                """
            else:
                # Phase 1 — full-doc embedding (current state)
                # Improved: surfaces summary + holding fields first for better snippets
                vector_sql = f"""
                    SELECT j.id,
                           j.case_number, j.petitioner, j.respondent, j.year, j.case_type,
                           COALESCE(j.summary, '') || ' ' || COALESCE(j.holding, '') || ' '
                               || SUBSTRING(j.full_text, 1, 1500) AS chunk_text,
                           j.embedding <-> :q_vec AS distance
                    FROM   judgments j
                    WHERE  j.embedding IS NOT NULL
                    {ct_filter_sql}
                    ORDER  BY distance
                    LIMIT  30
                """

            # ── Keyword (BM25) search — enhanced for Indian legal abbreviations ──
            ts_config = _get_ts_config(query)
            keyword_sql = f"""
                SELECT j.id,
                       j.case_number, j.petitioner, j.respondent, j.year, j.case_type,
                       COALESCE(j.summary, '') || ' ' || COALESCE(j.holding, '') || ' '
                           || SUBSTRING(j.full_text, 1, 1500) AS chunk_text,
                       ts_rank(j.search_vector,
                           to_tsquery('{{ts_config}}',
                               regexp_replace(
                                   websearch_to_tsquery('{{ts_config}}', :q)::text,
                                   ' & ', ' | ', 'g'
                               )
                           )
                       ) AS rank_score
                FROM   judgments j
                WHERE  j.search_vector @@ websearch_to_tsquery('{{ts_config}}', :q)
                {{ct_filter_sql}}
                ORDER  BY rank_score DESC
                LIMIT  30
            """.format(ts_config=ts_config, ct_filter_sql=ct_filter_sql)

            vec_params = {"q_vec": str(vec_list), **params_shared}
            kw_params  = {"q": query, **params_shared}

            try:
                vec_rows, kw_rows = await asyncio.gather(
                    _exec_raw(engine, vector_sql, vec_params),
                    _exec_raw(engine, keyword_sql, kw_params)
                )

                # ── Typo / Concept OR Fallback ────────────────────────────────
                if len(kw_rows) < 5:
                    import re
                    words = [w for w in re.split(r'\W+', query) if len(w) > 2]
                    if len(words) > 1:
                        or_query = " | ".join(words)
                        if USE_CHUNKS:
                            fallback_sql = f"""
                                SELECT jc.id AS chunk_id,
                                       jc.judgment_id AS id,
                                       j.case_number, j.petitioner, j.respondent, j.year, j.case_type,
                                       COALESCE(j.summary, '') || ' ' || COALESCE(j.holding, '') || ' '
                                           || SUBSTRING(jc.chunk_text, 1, 1200) AS chunk_text,
                                       ts_rank_cd(jc.search_vector, to_tsquery('{ts_config}', :or_q)) AS rank_score
                                FROM   judgment_chunks jc
                                JOIN   judgments j ON j.id = jc.judgment_id
                                WHERE  jc.search_vector @@ to_tsquery('{ts_config}', :or_q)
                                {ct_filter_sql}
                                ORDER  BY rank_score DESC
                                LIMIT  30
                            """
                        else:
                            fallback_sql = f"""
                                SELECT j.id,
                                       j.case_number, j.petitioner, j.respondent, j.year, j.case_type,
                                       COALESCE(j.summary, '') || ' ' || COALESCE(j.holding, '') || ' '
                                           || SUBSTRING(j.full_text, 1, 1500) AS chunk_text,
                                       ts_rank_cd(j.search_vector, to_tsquery('{ts_config}', :or_q)) AS rank_score
                                FROM   judgments j
                                WHERE  j.search_vector @@ to_tsquery('{ts_config}', :or_q)
                                {ct_filter_sql}
                                ORDER  BY rank_score DESC
                                LIMIT  30
                            """
                        try:
                            kw_rows = await _exec_raw(engine, fallback_sql, {"or_q": or_query, **params_shared})
                        except Exception as fallback_err:
                            print(f"[retrieve_judgment_chunks] OR Fallback SQL error: {fallback_err}")

            except Exception as sql_err:
                print(f"[retrieve_judgments] SQL error for query '{query}': {sql_err}")
                # Fallback: run vector-only
                vec_rows = await _exec_raw(engine, vector_sql, vec_params)
                kw_rows = []

            # ── RRF fusion ──────────────────────────────────────────────
            sem_ranks = {r.id: idx + 1 for idx, r in enumerate(vec_rows)}
            kw_ranks  = {r.id: idx + 1 for idx, r in enumerate(kw_rows)}
            all_ids   = set(sem_ranks) | set(kw_ranks)
            row_data  = {r.id: r for r in (list(vec_rows) + list(kw_rows))}

            for jid in all_ids:
                rrf = 0.0
                if jid in sem_ranks: rrf += sem_weight / (60 + sem_ranks[jid])
                if jid in kw_ranks:  rrf += kw_weight  / (60 + kw_ranks[jid])
                if jid not in all_results or rrf > all_results[jid]["score"]:
                    row = row_data[jid]
                    title = f"{row.petitioner} v. {row.respondent}" if row.petitioner else "Unknown"
                    all_results[jid] = {
                        "id": jid, "score": rrf,
                        "text": (row.chunk_text or "")[:1000],
                        "case_number": row.case_number or "",
                        "title": title,
                        "year": row.year,
                        "case_type": getattr(row, "case_type", "") or "",
                        "corpus": "judgment"
                    }
        except Exception as e:
            print(f"Judgment retrieval error for query '{query}': {e}")

    return sorted(all_results.values(), key=lambda x: x["score"], reverse=True)[:30]


async def retrieve_statutes(
    engine,
    queries: list,
    embedding_fn=None,
    coi_only: bool = False,
    document_type_key: str = "",
    context: str = "search",
    query_vectors: dict = None,
) -> list:
    """
    Hybrid search over legal_code_sections.
    When document_type_key is provided and context='citations', filters to relevant statute codes.
    coi_only filters to Constitution of India (legal_code_id=7) — takes precedence over code filter.
    """
    all_results = {}
    sem_weight = 1.5 if context == "citations" else 1.0
    kw_weight  = 1.5 if context == "citations" else 2.0

    # Build statute code filter
    code_filter_sql = ""
    code_params: dict = {}
    if coi_only:
        code_filter_sql = " AND lcs.legal_code_id = 7"
    elif document_type_key and context == "citations":
        relevant_codes = _derive_statute_codes(document_type_key)
        if relevant_codes:
            code_filter_sql = " AND lc.short_code = ANY(:statute_codes)"
            code_params["statute_codes"] = relevant_codes

    for query in queries:
        try:
            if query_vectors and query in query_vectors:
                vec_list = query_vectors[query]
            elif embedding_fn:
                loop = asyncio.get_event_loop()
                vec = await loop.run_in_executor(_cpu_executor, embedding_fn, query)
                vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)
            else:
                continue

            vector_sql = f"""
                SELECT lcs.id, lcs.section_number, lcs.title, lcs.section_text, lc.short_code,
                       lcs.embedding <-> :q_vec AS distance
                FROM   legal_code_sections lcs
                JOIN   legal_codes lc ON lc.id = lcs.legal_code_id
                WHERE  lcs.embedding IS NOT NULL {code_filter_sql}
                ORDER  BY distance
                LIMIT  30
            """

            ts_config = _get_ts_config(query)
            keyword_sql = f"""
                SELECT lcs.id, lcs.section_number, lcs.title, lcs.section_text, lc.short_code,
                       ts_rank(lcs.search_vector,
                                        websearch_to_tsquery('{{ts_config}}', :q)) AS rank_score
                FROM   legal_code_sections lcs
                JOIN   legal_codes lc ON lc.id = lcs.legal_code_id
                WHERE  lcs.search_vector @@ websearch_to_tsquery('{{ts_config}}', :q) {{code_filter_sql}}
                ORDER  BY rank_score DESC
                LIMIT  30
            """.format(ts_config=ts_config, code_filter_sql=code_filter_sql)

            vec_params = {"q_vec": str(vec_list), **code_params}
            kw_params  = {"q": query, **code_params}

            try:
                vec_rows, kw_rows = await asyncio.gather(
                    _exec_raw(engine, vector_sql, vec_params),
                    _exec_raw(engine, keyword_sql, kw_params)
                )
                
                # ── Typo / Concept OR Fallback ────────────────────────────────
                if len(kw_rows) < 5:
                    import re
                    words = [w for w in re.split(r'\W+', query) if len(w) > 2]
                    if len(words) > 1:
                        or_query = " | ".join(words)
                        fallback_sql = f"""
                            SELECT lcs.id, lcs.section_number, lcs.title, lcs.section_text, lc.short_code,
                                   ts_rank_cd(lcs.search_vector, to_tsquery('{ts_config}', :or_q)) AS rank_score
                            FROM   legal_code_sections lcs
                            JOIN   legal_codes lc ON lc.id = lcs.legal_code_id
                            WHERE  lcs.search_vector @@ to_tsquery('{ts_config}', :or_q) {code_filter_sql}
                            ORDER  BY rank_score DESC
                            LIMIT  30
                        """
                        try:
                            kw_rows = await _exec_raw(engine, fallback_sql, {"or_q": or_query, **code_params})
                        except Exception as fallback_err:
                            print(f"[retrieve_statutes] OR Fallback SQL error: {fallback_err}")
            except Exception as sql_err:
                print(f"[retrieve_statutes] SQL error for query '{query}': {sql_err}")
                vec_rows = await _exec_raw(engine, vector_sql, vec_params)
                kw_rows = []

            sem_ranks = {r.id: idx + 1 for idx, r in enumerate(vec_rows)}
            kw_ranks  = {r.id: idx + 1 for idx, r in enumerate(kw_rows)}
            all_ids   = set(sem_ranks) | set(kw_ranks)
            row_data  = {r.id: r for r in (list(vec_rows) + list(kw_rows))}

            for sid in all_ids:
                rrf = 0.0
                if sid in sem_ranks: rrf += sem_weight / (60 + sem_ranks[sid])
                if sid in kw_ranks:  rrf += kw_weight  / (60 + kw_ranks[sid])
                if sid not in all_results or rrf > all_results[sid]["score"]:
                    row = row_data[sid]
                    all_results[sid] = {
                        "id": sid, "score": rrf,
                        "text": (row.section_text or "")[:800],
                        "title": f"Section {row.section_number} {row.title or ''} ({row.short_code})",
                        "short_code": row.short_code or "",
                        "section_number": row.section_number or "",
                        "corpus": "statute"
                    }
        except Exception as e:
            print(f"Statute retrieval error for query '{query}': {e}")

    return sorted(all_results.values(), key=lambda x: x["score"], reverse=True)[:30]


async def retrieve_court_rules(
    engine,
    court_identity_id: int,
    document_type_key: str,
    queries: list,
    embedding_fn,
) -> str:
    """
    Fetches court-specific procedural rules for the given court identity and
    document type, using the court_rule_document_mapping table as the RAG rule.

    - Mandatory chapters: always fetched in full (all rules in the chapter)
    - Optional chapters: hybrid BM25 + vector search, same RRF pattern as
      retrieve_statutes(), only included when contextually relevant

    Returns a formatted court_rules_block string for prompt injection,
    or an empty string if court_identity_id is None / no mapping exists.
    """
    if not court_identity_id:
        return ""

    # Step 1: Get chapter mapping for this court + doc type
    try:
        mapping_rows = await _exec_raw(
            engine,
            """
                SELECT chapter_number, is_mandatory_source
                FROM court_rule_document_mapping
                WHERE court_identity_id = :cid AND document_type_key = :dtk
            """,
            {"cid": court_identity_id, "dtk": document_type_key},
        )
    except Exception as e:
        print(f"[court_rules] Failed to fetch chapter mapping: {e}")
        return ""

    if not mapping_rows:
        return ""

    mandatory_chapters = [r.chapter_number for r in mapping_rows if r.is_mandatory_source]
    optional_chapters  = [r.chapter_number for r in mapping_rows if not r.is_mandatory_source]

    rules_by_chapter = {}  # chapter_number -> list of formatted rule strings

    # Step 2: Mandatory chapters — fetch all rules in full
    if mandatory_chapters:
        try:
            rows = await _exec_raw(
                engine,
                """
                    SELECT chapter_number, chapter_title, rule_number,
                           rule_subsection, rule_text
                    FROM court_rule_sections
                    WHERE court_identity_id = :cid
                      AND chapter_number = ANY(:ch)
                    ORDER BY chapter_number, rule_number NULLS LAST
                """,
                {"cid": court_identity_id, "ch": mandatory_chapters},
            )
            for r in rows:
                sub = r.rule_subsection or ""
                label = f"Ch. {r.chapter_number} R.{r.rule_number or '—'}{sub}".strip()
                entry = f"[{label}] {r.rule_text}"
                rules_by_chapter.setdefault(r.chapter_number, []).append(entry)
        except Exception as e:
            print(f"[court_rules] Mandatory chapter fetch error: {e}")

    # Step 3: Optional chapters — hybrid BM25 + vector search (RRF)
    if optional_chapters and queries and embedding_fn:
        opt_results = {}
        for query in queries:
            try:
                loop = asyncio.get_event_loop()
                vec = await loop.run_in_executor(_cpu_executor, embedding_fn, query)
                vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)

                vector_sql = """
                    SELECT id, chapter_number, chapter_title,
                           rule_number, rule_subsection, rule_text,
                           embedding <-> :q_vec AS distance
                    FROM court_rule_sections
                    WHERE court_identity_id = :cid
                      AND chapter_number = ANY(:ch)
                      AND embedding IS NOT NULL
                    ORDER BY distance
                    LIMIT 10
                """
                keyword_sql = """
                    SELECT id, chapter_number, chapter_title,
                           rule_number, rule_subsection, rule_text,
                           ts_rank(search_vector, websearch_to_tsquery('english', :q)) AS rank_score
                    FROM court_rule_sections
                    WHERE court_identity_id = :cid
                      AND chapter_number = ANY(:ch)
                      AND search_vector @@ websearch_to_tsquery('english', :q)
                    ORDER BY rank_score DESC
                    LIMIT 10
                """
                vec_rows, kw_rows = await asyncio.gather(
                    _exec_raw(engine, vector_sql, {"q_vec": str(vec_list), "cid": court_identity_id, "ch": optional_chapters}),
                    _exec_raw(engine, keyword_sql, {"q": query, "cid": court_identity_id, "ch": optional_chapters}),
                )
                sem_ranks = {r.id: idx + 1 for idx, r in enumerate(vec_rows)}
                kw_ranks  = {r.id: idx + 1 for idx, r in enumerate(kw_rows)}
                all_ids   = set(sem_ranks) | set(kw_ranks)
                row_data  = {r.id: r for r in list(vec_rows) + list(kw_rows)}

                for rid in all_ids:
                    rrf = 0.0
                    if rid in sem_ranks: rrf += 1.0 / (60 + sem_ranks[rid])
                    if rid in kw_ranks:  rrf += 2.0 / (60 + kw_ranks[rid])
                    if rid not in opt_results or rrf > opt_results[rid]["score"]:
                        row = row_data[rid]
                        opt_results[rid] = {"score": rrf, "row": row}
            except Exception as e:
                print(f"[court_rules] Optional chapter retrieval error for query '{query}': {e}")

        # Include top-3 optional results if score is meaningful (> 0.01)
        for item in sorted(opt_results.values(), key=lambda x: x["score"], reverse=True)[:3]:
            if item["score"] > 0.01:
                r = item["row"]
                sub = r.rule_subsection or ""
                label = f"Ch. {r.chapter_number} R.{r.rule_number or '—'}{sub}".strip()
                entry = f"[{label}] {r.rule_text}"
                rules_by_chapter.setdefault(r.chapter_number, []).append(entry)

    if not rules_by_chapter:
        return ""

    # Build the formatted block, grouped by chapter
    sections = []
    for ch in sorted(rules_by_chapter.keys()):
        sections.append("\n".join(rules_by_chapter[ch]))

    return (
        "=== ALLAHABAD HIGH COURT — RULES OF THE COURT, 1952 (MANDATORY COMPLIANCE) ===\n"
        + "\n\n".join(sections)
        + "\n=== END COURT RULES ==="
    )

import os
import concurrent.futures
from jinja2 import Environment, FileSystemLoader
from datetime import datetime

_reranker_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

# Initialize jinja2 env at module level
prompts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")
jinja_env = Environment(loader=FileSystemLoader(prompts_dir))

# ===========================================================================
# STAGE 4 — Cross-Encoder Reranking
# ===========================================================================
async def rerank_candidates(
    combined_query: str,
    candidates: list,
    top_k: int = 10,
    use_cross_encoder: bool = False,
) -> list:
    """
    Rerank candidates using cross-encoder (when enabled) or simple score-sort.

    use_cross_encoder=True  → used by suggest-citations (non-streaming, can afford latency)
    use_cross_encoder=False → used by streaming generate (bypassed to prevent proxy timeouts)
    """
    if not candidates:
        return []

    if not use_cross_encoder:
        # Fast path: use existing RRF score. 
        # RRF scores are typically ~0.04 for high relevance. Multiply by 100 to map to the 0-5 scale the UI expects.
        candidates = sorted(candidates, key=lambda x: x.get("score", 0.0), reverse=True)
        filtered = []
        if candidates:
            max_score = candidates[0].get("score", 0.0)
            for c in candidates:
                s = c.get("score", 0.0)
                if s < 0.015:  # Absolute noise cutoff
                    continue
                if s < max_score * 0.5:  # Relative drop-off (50% drop from the best result)
                    continue
                c["rerank_score"] = s * 100
                filtered.append(c)
        return filtered[:top_k]

    # Cross-encoder path (enabled for citation suggestion)
    try:
        reranker = await load_reranker()
        pairs = [(combined_query, c.get("text", "")) for c in candidates]
        loop = asyncio.get_event_loop()
        
        # Removed asyncio.wait_for because on Windows ProactorEventLoop, cancelling a thread pool 
        # future causes a fatal AttributeError ('NoneType' object has no attribute 'send') when the 
        # thread eventually finishes and tries to notify the closed loop.
        scores = await loop.run_in_executor(_reranker_executor, reranker.predict, pairs)
        
        for i, c in enumerate(candidates):
            c["rerank_score"] = float(scores[i])
        reranked = sorted(candidates, key=lambda x: x.get("rerank_score", 0), reverse=True)
        
        filtered = []
        if reranked:
            max_score = reranked[0].get("rerank_score", 0.0)
            for c in reranked:
                s = c.get("rerank_score", 0.0)
                # Cross encoder scores are usually logits (e.g. -10 to +10).
                # Removed absolute cutoff because logits can be negative even for the best match.
                if s < max_score - 3.0:  # Relative drop-off for logits
                    continue
                filtered.append(c)
                
        return filtered[:top_k]
    except Exception as e:
        print(f"[reranker] Cross-encoder error: {e} — falling back to RRF order")
        return candidates[:top_k]


# ===========================================================================
# STAGE 5 — Context Assembly
# ===========================================================================
# Mapping from display names / common keys to prompt template filenames.
# Add new entries as new document types are introduced.
_DOC_TYPE_KEY_TO_TEMPLATE = {
    "writ_petition_civil":    "writ_petition_civil.txt",
    "writ_petition_criminal": "writ_petition_criminal.txt",
    "bail_application":       "bail_application.txt",
    "anticipatory_bail":      "anticipatory_bail.txt",
    "civil_appeal":           "civil_appeal.txt",
    "criminal_appeal":        "criminal_appeal.txt",
    # Legacy fallback — existing writ_petition.txt kept as default
    "writ_petition":          "writ_petition.txt",
}


async def get_effective_structure_rules(engine, court_level: str, overrides: dict) -> list[dict]:
    sql = """
        SELECT rule_key, rule_description, is_heading, source_type, applies_to
        FROM document_structure_rules
        WHERE applies_to IN ('ALL', :cl)
    """
    rows = await _exec_raw(engine, sql, {"cl": court_level})
    rules = []
    for r in rows:
        rule_dict = dict(r._mapping)
        rule_dict['overridden_by_user'] = False
        if rule_dict['source_type'] != 'rule_mandated' and rule_dict['rule_key'] in overrides:
            rule_dict['is_heading'] = overrides.get(rule_dict['rule_key'])
            rule_dict['overridden_by_user'] = True
        rules.append(rule_dict)
    return rules


async def get_mandatory_paragraphs(engine, court_level: str, document_type_key: str) -> dict:
    sql = """
        SELECT para_key, para_label, instruction, placement, is_conditional, condition_note, sort_order
        FROM mandatory_paragraphs
        WHERE court_level = :cl AND document_type_key = :dt
        ORDER BY sort_order
    """
    rows = await _exec_raw(engine, sql, {"cl": court_level, "dt": document_type_key})
    
    opening_paras = []
    body_paras = []
    for r in rows:
        d = dict(r._mapping)
        if d['placement'] == 'opening':
            opening_paras.append(d)
        else:
            body_paras.append(d)
            
    return {"opening_paras": opening_paras, "body_paras": body_paras}



def assemble_prompt(
    form_data: dict,
    judgment_results: list,
    statute_results: list,
    uploaded_docs_context: str = "",
    court_rules_block: str = "",
    structure_rules: list = None,
    mandatory_paragraphs: dict = None,
) -> str:
    petitioners = ", ".join(form_data.get("petitioners") or ["[Petitioner]"]) or "[Petitioner]"
    respondents  = ", ".join(form_data.get("respondents") or ["[Respondent]"]) or "[Respondent]"

    statutes_block = "\n".join(
        f"- {r['title']}:\n  {r['text'][:600]}"
        for r in statute_results[:5]
    ) or "[No statute sections retrieved]"

    judgments_block = "\n".join(
        f"- {r.get('title', 'Unknown')} [{r.get('case_number', '')}] ({r.get('year', '')}):\n  Actual Holding/Snippet: {r['text'][:600]}"
        for r in judgment_results[:5]
    ) or "[No precedents retrieved]"

    court_display  = form_data.get("court_display", "the court")
    subject_matter = form_data.get("subject_matter", "")
    doc_type       = form_data.get("document_type", "")

    # Article 32 vs 226 jurisdiction warning (existing logic, preserved)
    jurisdiction_warning = ""
    if "Service Law" in subject_matter and "Supreme Court" in court_display and "32" in doc_type:
        jurisdiction_warning = (
            "\n[CRITICAL LEGAL INSTRUCTION: The user has selected Article 32 for a Service Law matter. "
            "You MUST include a strong justification in the Jurisdiction paragraph explaining why Article 32 "
            "is invoked directly instead of approaching the Central Administrative Tribunal (CAT) or the High "
            "Court under Article 226, specifically citing violation of fundamental rights.]\n"
        )

    # Per-doc-type template routing (replaces hardcoded writ_petition.txt)
    # Falls back to writ_petition.txt if key is missing or template file doesn't exist.
    doc_type_key = form_data.get("document_type_key") or ""
    template_file = _DOC_TYPE_KEY_TO_TEMPLATE.get(doc_type_key, "writ_petition.txt")
    try:
        template = jinja_env.get_template(f"document_types/{template_file}")
    except Exception:
        # Graceful fallback if template file not yet created for this doc type
        template = jinja_env.get_template("document_types/writ_petition.txt")

    context = {
        "current_year":        datetime.now().year,
        "doc_type":            doc_type,
        "court_display":       court_display,
        "jurisdiction_warning": jurisdiction_warning,
        "petitioners":         petitioners,
        "respondents":         respondents,
        "form_data":           form_data,
        "uploaded_docs_context": uploaded_docs_context,
        "statutes_block":      statutes_block,
        "judgments_block":     judgments_block,
        "court_rules_block":   court_rules_block,
        "structure_rules":     structure_rules or [],
        "opening_paras":       (mandatory_paragraphs or {}).get("opening_paras", []),
        "body_paras":          (mandatory_paragraphs or {}).get("body_paras", []),
    }

    return template.render(**context)


# ===========================================================================
# STAGE 6 — Citation Verification (post-generation)
# ===========================================================================
async def verify_citations(draft_text: str, engine) -> list:
    """
    Extracts case and section citations from draft, verifies each against DB.
    Returns list of {citation, type, status: 'verified' | 'not_found_in_db'}.
    """
    results = []

    # Match patterns like (2019) 4 SCC 123
    case_pattern = re.compile(r'\(\d{4}\)\s*\d+\s*SCC\s*\d+')
    # Match patterns like Section 302 IPC / Section 21 BNS
    section_pattern = re.compile(r'Section\s*\d+[A-Z]?\s*(?:of\s*(?:the\s*)?)?(?:IPC|BNS|CrPC|BNSS|COI|SRA|CPC|BSA)')

    for citation in set(case_pattern.findall(draft_text)):
        try:
            async with engine.connect() as conn:
                r = await conn.execute(
                    text("SELECT 1 FROM judgments WHERE case_number ILIKE :c LIMIT 1"),
                    {"c": f"%{citation}%"}
                )
                status = "verified" if r.fetchone() else "not_found_in_db"
            results.append({"citation": citation, "type": "case", "status": status})
        except Exception:
            results.append({"citation": citation, "type": "case", "status": "error"})

    for citation in set(section_pattern.findall(draft_text)):
        sec_match  = re.search(r'(\d+[A-Z]?)', citation)
        code_match = re.search(r'(IPC|BNS|CrPC|BNSS|COI|SRA|CPC|BSA)', citation)
        if sec_match and code_match:
            try:
                async with engine.connect() as conn:
                    r = await conn.execute(
                        text("""
                            SELECT 1 FROM legal_code_sections lcs
                            JOIN legal_codes lc ON lc.id = lcs.legal_code_id
                            WHERE lcs.section_number ILIKE :s AND lc.short_code ILIKE :c
                            LIMIT 1
                        """),
                        {"s": f"%{sec_match.group(1)}%", "c": code_match.group(1)}
                    )
                    status = "verified" if r.fetchone() else "not_found_in_db"
                results.append({"citation": citation.strip(), "type": "section", "status": status})
            except Exception:
                results.append({"citation": citation.strip(), "type": "section", "status": "error"})

    return results
