"""
core/rag.py — Multi-Corpus Hybrid RAG Pipeline for Step 6 (Generate)

Stages:
  1. Query Rewriting       (GPT-4o-mini) — doc-type hints resolved from the
         doc_type_retrieval_hints table (see scripts/seed_retrieval_config.py)
  2 & 3. Fan-out Hybrid Retrieval  (BM25 + pgvector + RRF, parallel, 3 corpora)
         — USE_CHUNKS flag: False=judgments table, True=judgment_chunks
         — context-aware RRF weights: 'citations' mode uses balanced 1.5x each
         — subject-matter case_type + statute_code filters for citation context
  4. Reranking — cross-encoder (ms-marco-MiniLM-L-6-v2) by default, or the
         LLM listwise reranker when RAG_LLM_RERANK=1 (scores against raw facts)
         — bypassed for streaming /generate to prevent proxy timeouts
  5. Context Assembly
  6. Citation Verification (post-generation, regex + SQL)

All retrieval configuration (doc-type hints, case-type/domain maps, COI and
service-law keyword lists, act-name aliases) lives in the database, not in this
module — reseed with scripts/seed_retrieval_config.py after editing.
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
USE_CHUNKS = True


# ===========================================================================
# Runtime retrieval configuration — loaded from the DB, not hardcoded.
# Tables: retrieval_config, doc_type_retrieval_hints, legal_codes.aliases
# (seeded by scripts/seed_retrieval_config.py). Cached in-process with a TTL
# so hint/config edits go live without a deploy; on load failure the last
# good copy is kept (empty degrades to "no filters + generic hint").
# ===========================================================================
import time as _time

_RT_CFG_TTL = int(os.getenv("RAG_CONFIG_TTL_SECONDS", "300"))
_rt_cfg = {"ts": 0.0, "config": {}, "hints": [], "aliases": [], "loaded": False}


async def _get_runtime_config(engine=None) -> dict:
    now = _time.time()
    if _rt_cfg["loaded"] and now - _rt_cfg["ts"] < _RT_CFG_TTL:
        return _rt_cfg
    if engine is None:
        from app.core.database import engine as _engine
        engine = _engine
    try:
        cfg_rows = await _exec_raw(engine, "SELECT key, value FROM retrieval_config", {})
        config = {}
        for r in cfg_rows:
            v = r.value
            if isinstance(v, str):
                # Driver-dependent: jsonb may arrive already-decoded (a plain
                # string value) or as raw JSON text — only parse the latter.
                try:
                    v = json.loads(v)
                except (json.JSONDecodeError, ValueError):
                    pass
            config[r.key] = v

        hint_rows = await _exec_raw(
            engine,
            """SELECT priority, keywords_any, keywords_all, subject_keywords_any, hint_text
               FROM doc_type_retrieval_hints ORDER BY priority""",
            {},
        )
        hints = [dict(r._mapping) for r in hint_rows]

        alias_rows = await _exec_raw(
            engine, "SELECT short_code, code_name, aliases FROM legal_codes", {}
        )
        aliases = []
        for r in alias_rows:
            names = set(a.lower() for a in (r.aliases or []))
            names.add((r.code_name or "").lower().split(",")[0].strip())
            for name in names:
                if name:
                    aliases.append((name, r.short_code))
        # Longest names first so the most specific act name wins the scan
        aliases.sort(key=lambda x: len(x[0]), reverse=True)

        _rt_cfg.update(ts=now, config=config, hints=hints, aliases=aliases, loaded=True)
        global _ts_simple_abbrevs
        abbrevs = config.get("ts_simple_abbrevs")
        if abbrevs:
            _ts_simple_abbrevs = {a.upper() for a in abbrevs}
    except Exception as e:
        print(f"[rag-config] load failed (using previous copy): {e}")
        _rt_cfg["ts"] = now  # don't hammer a broken DB every call
    return _rt_cfg


def _kw_match(keywords: list, text: str) -> bool:
    """Word-boundary keyword matching — bare substring checks caused false
    positives like 'pay' matching inside 'payment' (service-law hijack)."""
    return any(re.search(r"\b" + re.escape(kw) + r"\b", text) for kw in keywords)


def _derive_case_type_filter(config: dict, document_type_key: str, subject_matter: str) -> list:
    """Return case_type values to filter judgments by, or [] for no filter."""
    base = list((config.get("doc_type_case_types") or {}).get(document_type_key, []))
    if subject_matter:
        sm_lower = subject_matter.lower()
        for keyword, types in (config.get("subject_case_type_overrides") or []):
            if _kw_match([keyword], sm_lower):
                for t in types:
                    if t not in base:
                        base.append(t)
    return base


# Subject matter -> the statute domain that actually governs it.
#
# Why this exists: 'civil' is tagged on 48 of 58 legal_codes, so a domain filter
# of ['civil','constitutional'] admits 49 codes — effectively no filter at all.
# A U.P. land-revenue writ was therefore ranked against Income Tax, IBC and the
# Contract Act purely on embedding similarity. 'criminal' by contrast admits 16
# codes and works well, which is why criminal matters retrieve far better.
#
# Matched against the subject-matter NAME only; nothing in the subject_matters,
# document_types or sub-subject-matter tables is read differently or modified.
# Ordered — the first match wins, so put the narrower signals first.
_SUBJECT_STATUTE_DOMAINS: tuple = (
    # Tax first: "Writ Tax — Stamp duty & registration fee" is a tax matter even
    # though it mentions registration.
    ("tax", ("writ tax", "income tax", " gst", "vat", "trade tax", "excise",
             "customs", "wealth tax", "gift tax", "estate duty", "sales tax",
             "tax (direct", "goods & service tax")),
    ("service", ("service matters", "service law", "service (central",
                 "departmental enquiry", "compassionate appointment", "seniority",
                 "promotion", "retiral", "pension", "probation & confirmation",
                 "compulsory retirement", "voluntary retirement")),
    ("property", ("revenue, land", "zamindari", "bhumidhari", "sirdari",
                  "consolidation", "mutation", "land revenue", "gaon sabha",
                  "ceiling on land", "patta", "land acquisition", "property",
                  "rent control", "eviction", "tenancy", "real estate",
                  "builder dispute", "rera", "stamp act")),
    ("family", ("matrimonial", "family", "probate", "testamentary", "guardian",
                "custody of minor", "succession")),
    ("corporate", ("company", "insolvency", "sarfaesi", "debt recovery",
                   "commercial", "arbitration", "amalgamation", "liquidator",
                   "money recovery")),
    ("labour", ("industrial dispute", "labour", "wages", "industrial disputes act")),
    ("transport", ("motor accident", "mact", "motor vehicles")),
    ("environment", ("environmental", "environment")),
    ("consumer", ("consumer",)),
)

# Kept alongside the narrowed domain so general civil machinery stays reachable:
# 'procedure' brings CPC and the Limitation Act, 'constitutional' brings the COI
# that every writ is founded on.
_NARROWED_COMPANION_DOMAINS = ("constitutional", "procedure")


def _subject_statute_domain(sm_lower: str) -> str:
    """The governing statute domain for this subject matter, or '' if unclear."""
    for domain, keywords in _SUBJECT_STATUTE_DOMAINS:
        if any(kw in sm_lower for kw in keywords):
            return domain
    return ""


def _derive_statute_domains(config: dict, document_type_key: str, subject_matter: str = "") -> list:
    """Return preferred statute domains for this document type and subject matter."""
    domains = list((config.get("doc_type_domains") or {}).get(document_type_key, []))
    sm_lower = subject_matter.lower() if subject_matter else ""

    # Constitutional domain when the subject touches constitutional provisions,
    # or for service matters (service writs rely heavily on COI)
    needs_coi = any(kw in sm_lower for kw in (config.get("subject_needs_coi") or []))
    is_service = _kw_match(config.get("service_law_keywords") or [], sm_lower)

    if "constitutional" not in domains and (needs_coi or is_service):
        domains.append("constitutional")

    # Replace the catch-all 'civil' with the domain the subject actually belongs
    # to. Only fires when 'civil' is present, so criminal document types — which
    # already filter well at 16/58 codes — are left untouched.
    specific = _subject_statute_domain(sm_lower)
    if specific and "civil" in domains:
        domains = [d for d in domains if d != "civil"]
        for extra in (specific,) + _NARROWED_COMPANION_DOMAINS:
            if extra not in domains:
                domains.append(extra)

    return domains


def _resolve_doc_hint(hints: list, doc_haystack: str, sm_lower: str):
    """First hint row (by priority) whose keyword conditions all hold, or None."""
    for row in hints:
        kw_all = row.get("keywords_all") or []
        kw_any = row.get("keywords_any") or []
        if not kw_all and not kw_any:
            continue
        if kw_all and not all(_kw_match([k], doc_haystack) for k in kw_all):
            continue
        if kw_any and not _kw_match(kw_any, doc_haystack):
            continue
        subj = row.get("subject_keywords_any") or []
        if subj and not _kw_match(subj, sm_lower):
            continue
        return row["hint_text"]
    return None


async def subject_needs_coi(subject_matter: str, engine=None) -> bool:
    """True when the subject matter warrants querying the COI corpus."""
    cfg = await _get_runtime_config(engine)
    sm_lower = (subject_matter or "").lower()
    return any(kw in sm_lower for kw in (cfg["config"].get("subject_needs_coi") or []))


# Fallback abbreviation set; overwritten from retrieval_config on first load
_ts_simple_abbrevs = {"IPC", "BNS", "CRPC", "BNSS", "COI", "SCC", "AIR",
                      "CPC", "SRA", "NDPS", "POCSO", "IBC", "GST", "CBI", "BSA"}


def _get_ts_config(query: str) -> str:
    """
    Return 'simple' for abbreviation-heavy queries so Indian legal terms
    (IPC, CrPC, BNSS etc.) are not stripped by the 'english' stop-word list.
    """
    words = query.strip().upper().split()
    if any(w in _ts_simple_abbrevs for w in words) or len(words) <= 3:
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
                import inspect
                from sentence_transformers import CrossEncoder
                cache_dir = os.environ.get("SENTENCE_TRANSFORMERS_HOME") or None
                # sentence-transformers <4 uses cache_dir; >=4 renamed it to
                # cache_folder — passing the wrong one raises TypeError and
                # silently disables reranking, so pick by signature.
                kwargs = {"device": "cpu"}
                if cache_dir:
                    params = inspect.signature(CrossEncoder.__init__).parameters
                    if "cache_folder" in params:
                        kwargs["cache_folder"] = cache_dir
                    elif "cache_dir" in params:
                        kwargs["cache_dir"] = cache_dir
                # Load in the main thread: HF model loading inside a worker
                # thread crashes with torch 2.6 meta-tensor errors (see search.py).
                _reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", **kwargs)
                print("Cross-encoder reranker loaded.")
    return _reranker


# ---------------------------------------------------------------------------
# Internal helper: run raw SQL on a dedicated pool connection (safe for gather)
# ---------------------------------------------------------------------------
async def _exec_raw(engine, sql: str, params: dict, presql=None) -> list:
    """presql: a SET LOCAL statement, or a list of them, run before the query."""
    async with engine.connect() as conn:
        if presql:
            for stmt in ([presql] if isinstance(presql, str) else presql):
                await conn.execute(text(stmt))
        result = await conn.execute(text(sql), params)
        return result.fetchall()


# ── Tunable retrieval knobs (env-overridable; defaults set by benchmark) ────
# ivfflat scans `probes` of the index's lists; the pgvector default (1) trades
# too much recall for speed on the 1000-list judgment_chunks index.
# 20 = accuracy-first (user accepted a 20-25s latency budget on 2026-07-25).
# hnsw.ef_search applies once the corpus indexes are HNSW (scripts/
# create_hnsw_indexes.py); both settings are harmless on the other index type.
IVFFLAT_PROBES = int(os.getenv("RAG_IVFFLAT_PROBES", "20"))
HNSW_EF_SEARCH = int(os.getenv("RAG_HNSW_EF_SEARCH", "40"))
# Iterative scan is REQUIRED for correctness, not tuning: without it pgvector
# takes the top ef_search neighbours and only then applies the WHERE clause, so
# a case-type-filtered judgment search returned ZERO semantic rows whenever the
# nearest chunks fell outside the allowed case types — the semantic half of
# retrieval was silently dead and results came from BM25 alone. strict_order
# keeps exact distance ordering; max_scan_tuples bounds the worst case.
HNSW_MAX_SCAN_TUPLES = int(os.getenv("RAG_HNSW_MAX_SCAN_TUPLES", "20000"))
_VEC_PRESQL = [
    f"SET LOCAL ivfflat.probes = {IVFFLAT_PROBES}",
    f"SET LOCAL hnsw.ef_search = {HNSW_EF_SEARCH}",
    "SET LOCAL hnsw.iterative_scan = strict_order",
    f"SET LOCAL hnsw.max_scan_tuples = {HNSW_MAX_SCAN_TUPLES}",
]

# OR-fallback for the judgments corpus: rescues keyword misses for case-name
# queries. Enabled by default, but bounded — it only fires for queries that
# look like case names (see _looks_like_case_name); unrestricted OR queries on
# common words previously caused 55-90s ts_rank_cd spikes over huge match sets.
JUDGMENT_OR_FALLBACK = os.getenv("RAG_JUDGMENT_OR_FALLBACK", "1") == "1"

# Case-name heuristic: 'Gurbaksh Singh Sibbia v. State of Punjab holding ...'
_CASE_NAME_RE = re.compile(r"\bv\.?s?\.?\b", re.IGNORECASE)


def _looks_like_case_name(query: str) -> bool:
    return bool(_CASE_NAME_RE.search(query))


# Party-name tokens: capitalised, not generic legal vocabulary. ORing every
# word of a case-name query instead matched 98.7% of the judgments corpus and
# cost ~47s; only distinctive names may widen the search.
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][A-Za-z'&.\-]{2,}\b")
MAX_OR_TERMS = int(os.getenv("RAG_MAX_OR_TERMS", "6"))
# Hard ceiling so a pathological keyword query can never eat the request budget.
# 4000 was sized for the old search_vector form, which took ~50s and therefore
# always tripped the cap — the fallback silently contributed nothing. The
# two-stage party-column query (see build_case_name_fallback_sql) costs ~1.2s
# warm and up to ~4s cold on a broad government cause title, so 4000 still cut
# off the cold path. 6000 clears it while keeping the query bounded.
OR_FALLBACK_TIMEOUT_MS = int(os.getenv("RAG_OR_FALLBACK_TIMEOUT_MS", "6000"))


def _case_name_terms(query: str, stopwords: set) -> list:
    """Distinctive proper-noun tokens from a case-name query, most-specific first."""
    terms, seen = [], set()
    for tok in _PROPER_NOUN_RE.findall(query):
        key = tok.lower().strip(".")
        if len(key) < 4 or key in stopwords or key in seen:
            continue
        seen.add(key)
        terms.append(tok)
    return terms[:MAX_OR_TERMS]


def build_case_name_fallback_sql(
    words: list, ts_config: str = "english", ct_filter_sql: str = ""
) -> tuple:
    """Build the case-name OR-fallback query. Returns (sql, params).

    Party names are matched against the PARTY COLUMNS, never against
    search_vector. search_vector spans summary + holding + full_text, so a name
    matched there whenever a judgment merely *mentioned* someone of that name.
    Measured on the live corpus (39,506 judgments):

        search_vector @@ 'Kumar | Verma'   20,698 rows (52.4%)  5.43s
        petitioner/respondent ILIKE         3,015 rows ( 7.6%)  0.13s warm

    At 5.43s the old form could not finish inside OR_FALLBACK_TIMEOUT_MS (4s), so
    it always ended in QueryCanceledError for common Indian surnames — Kumar
    appears in 49% of the corpus, Singh 59%, Sharma 30% — which is the majority
    of Indian cause titles. The stopword list catches generic legal vocabulary
    ("State", "bail") but can never keep up with surnames.

    Filtering on the party columns is also what this fallback *means*: it exists
    to find a case by its cause title. ts_rank still orders the survivors, so
    relevance ranking is unchanged — it just runs over 3k rows instead of 21k.
    """
    name_filter = " OR ".join(
        f"(j.petitioner ILIKE :nm{i} OR j.respondent ILIKE :nm{i})"
        for i in range(len(words))
    )
    params = {"or_q": " | ".join(words)}
    params.update({f"nm{i}": f"%{w}%" for i, w in enumerate(words)})
    # Two stages: rank a lean row first, then fetch the heavy text for the 20
    # winners only. Building chunk_text in the ranking pass meant detoasting
    # full_text for every matching row — measured on a government cause title
    # ("... Chief Engineer, Lucknow Zone", 3,606 matches):
    #
    #     name filter alone                    0.65s
    #     + ts_rank + ORDER BY + LIMIT         3.87s
    #     + SUBSTRING(full_text) in that pass  4.96s   -> over the 4s cap
    #     two-stage (this form)                3.28s cold / 1.41s warm
    #
    # Same columns and ordering as before; only the point at which full_text is
    # read has moved.
    sql = f"""
        WITH hits AS (
            SELECT j.id,
                   ts_rank(j.search_vector, to_tsquery('{ts_config}', :or_q)) AS rank_score
              FROM judgments j
             WHERE ({name_filter})
             {ct_filter_sql}
             ORDER BY rank_score DESC
             LIMIT 20
        )
        SELECT j.id,
               j.case_number, j.petitioner, j.respondent, j.year, j.case_type,
               COALESCE(j.summary, '') || ' ' || COALESCE(j.holding, '') || ' '
                   || SUBSTRING(j.full_text, 1, 1500) AS chunk_text,
               h.rank_score
          FROM hits h
          JOIN judgments j ON j.id = h.id
         ORDER BY h.rank_score DESC
    """
    return sql, params

# Number of rewritten queries to fan out (5-7). Benchmarked 2026-07-25
# (scripts/evaluate_step6.py): 5 beat 7 on BOTH precision and latency —
# the extra query angles mostly injected noise into the RRF fusion.
NUM_QUERIES = int(os.getenv("RAG_NUM_QUERIES", "5"))

# The case_type filter narrows the judgment corpus by ~77% for a bail matter.
# Its source data is unreliable (Bhajan Lal is filed as "Civil Appeal"), so it
# is kept switchable for A/B evaluation rather than assumed to be a net win.
CASE_TYPE_FILTER_ENABLED = os.getenv("RAG_CASE_TYPE_FILTER", "1") == "1"

# Model used for query rewriting (Stage 1).
REWRITE_MODEL = os.getenv("RAG_REWRITE_MODEL", "openai/gpt-4o-mini")


# ===========================================================================
# STAGE 1 — Query Rewriting  (GPT-4o-mini, cheap task)
# ===========================================================================
async def rewrite_queries(
    facts: str,
    doc_type: str,
    subject_matter: str,
    search_hint: str = "",
    document_type_key: str = "",
) -> list:
    """
    Generate targeted search queries for the given case facts.
    search_hint: optional user-provided refinement (e.g. 'Section 41A CrPC wrongful arrest').
    document_type_key: canonical key (e.g. 'anticipatory_bail') — included in the
    branch-matching haystack because display names are unreliable (a generic
    'APPLICATION' doc type must not route into the CAT/tribunal branch).
    """
    client = get_openrouter_client()
    if not openrouter_key:
        return [facts[:200]]

    cfg = await _get_runtime_config()
    doc_lower = f"{(document_type_key or '').replace('_', ' ')} {doc_type}".lower().strip()
    sm_lower  = subject_matter.lower()

    # Doc-type hint resolved from doc_type_retrieval_hints (DB-driven).
    # Rows are checked in priority order; a row matches when all keywords_all
    # AND any keywords_any appear as whole words in the doc-type haystack, and
    # any subject_keywords_any (if set) appear in the subject matter. This
    # replaces the old hardcoded elif chain whose bare substring checks caused
    # the appliCATion/disCHARGE routing hijacks.
    doc_hint = _resolve_doc_hint(cfg["hints"], doc_lower, sm_lower)
    if not doc_hint:
        doc_hint = cfg["config"].get("generic_doc_hint") or (
            "Document Type: {doc_type}. Subject Matter: {subject_matter}. "
            "Ensure queries are tightly focused on the specific legal issues in the subject matter. "
            "Avoid broad generic constitutional queries unless fundamental rights are directly violated."
        )
    doc_hint = (doc_hint
                .replace("{subject_matter}", subject_matter or "")
                .replace("{doc_type}", doc_type or ""))

    hint_line = f"\nUser search refinement (incorporate this): {search_hint}" if search_hint else ""

    n = NUM_QUERIES
    try:
        response = await client.chat.completions.create(
            model=REWRITE_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert Indian legal researcher. Given a case description, "
                        f"generate exactly {n} distinct, highly-optimized search queries to retrieve relevant Indian court judgments and statutes. "
                        "To maximize recall, the queries MUST target different retrieval angles, in this priority order:\n"
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
                        f"Return ONLY a JSON object with key 'queries' containing an array of exactly {n} strings."
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
        return [q for q in queries if isinstance(q, str)][:n]
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

    Post-chunking fixes applied (all active when USE_CHUNKS=True):
       vec_row_data and kw_row_data are kept separate to prevent BM25 overwriting chunk text.
      sem_ranks only records first (best-ranked) chunk per judgment_id.
      chunk_text (raw paragraph) stored separately for cross-encoder; LLM gets holding-prefixed text.
       Winner chunks are expanded with ±1 neighbouring chunks for richer LLM context.
       Holding prefix omitted when the chunk itself IS the holding paragraph.
    """
    # Derive case_type filter for citation context (config is DB-driven)
    cfg = await _get_runtime_config(engine)
    case_type_filter = _derive_case_type_filter(cfg["config"], document_type_key, subject_matter) if document_type_key else []
    sem_weight = 1.5 if context == "citations" else 1.0
    kw_weight  = 1.5 if context == "citations" else 2.0

    # ── Case-type filter clause (constant across queries) ────────────────
    ct_filter_sql = ""
    params_shared: dict = {}
    if case_type_filter and context == "citations" and CASE_TYPE_FILTER_ENABLED:
        # NULLIF: case_type is an EMPTY STRING (not NULL) on 10,577 of 39,506
        # judgments — 27% of the corpus. `IS NULL` alone therefore excluded all
        # of them from every filtered search, including Gurbaksh Singh Sibbia,
        # the leading anticipatory-bail authority. Unlabelled rows must be
        # treated as "unknown case type" and kept, exactly like NULL.
        ct_filter_sql = " AND (j.case_type = ANY(:case_types) OR NULLIF(j.case_type, '') IS NULL)"
        params_shared["case_types"] = case_type_filter

    async def _run_query(query: str):
        """Hybrid (vector + BM25) retrieval for one rewritten query."""
        if query_vectors and query in query_vectors:
            vec_list = query_vectors[query]
        elif embedding_fn:
            loop = asyncio.get_event_loop()
            vec = await loop.run_in_executor(_cpu_executor, embedding_fn, query)
            vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)
        else:
            return [], []

        # ── Vector (semantic) search ─────────────────────────────────
        if USE_CHUNKS:
            # FIX 3: Select jc.chunk_text separately (raw paragraph) so we can pass
            # it to the cross-encoder independently of the holding-prefixed LLM text.
            # FIX 1+2: We alias jc.judgment_id AS id so RRF keys on judgment level.
            #           chunk_id is preserved separately to enable context expansion.
            vector_sql = f"""
                SELECT jc.id          AS chunk_id,
                       jc.judgment_id AS id,
                       jc.chunk_index,
                       jc.chunk_text  AS raw_chunk_text,
                       j.case_number, j.petitioner, j.respondent, j.year, j.case_type,
                       COALESCE(j.holding, '')    AS holding,
                       COALESCE(j.summary, '')    AS summary,
                       jc.paragraph_number_start,
                       jc.paragraph_number_end,
                       jc.embedding <=> :q_vec AS distance
                FROM   judgment_chunks jc
                JOIN   judgments j ON j.id = jc.judgment_id
                WHERE  jc.embedding IS NOT NULL
                {ct_filter_sql}
                ORDER  BY distance
                LIMIT  30
            """
        else:
            # Phase 1 — full-doc embedding (current state)
            vector_sql = f"""
                SELECT j.id,
                       j.case_number, j.petitioner, j.respondent, j.year, j.case_type,
                       COALESCE(j.summary, '') || ' ' || COALESCE(j.holding, '') || ' '
                           || SUBSTRING(j.full_text, 1, 1500) AS chunk_text,
                       j.embedding <=> :q_vec AS distance
                FROM   judgments j
                WHERE  j.embedding IS NOT NULL
                {ct_filter_sql}
                ORDER  BY distance
                LIMIT  30
            """

        # ── Keyword (BM25) search — always queries judgments table ──
        # BM25 results give us the document-level context (summary + holding + full_text).
        ts_config = _get_ts_config(query)
        keyword_sql = f"""
            SELECT j.id,
                   j.case_number, j.petitioner, j.respondent, j.year, j.case_type,
                   COALESCE(j.summary, '') || ' ' || COALESCE(j.holding, '') || ' '
                       || SUBSTRING(j.full_text, 1, 1500) AS chunk_text,
                   ts_rank(j.search_vector,
                       to_tsquery('{ts_config}',
                           regexp_replace(
                               websearch_to_tsquery('{ts_config}', :q)::text,
                               ' & ', ' | ', 'g'
                           )
                       )
                   ) AS rank_score
            FROM   judgments j
            WHERE  j.search_vector @@ websearch_to_tsquery('{ts_config}', :q)
            {ct_filter_sql}
            ORDER  BY rank_score DESC
            LIMIT  30
        """

        vec_params = {"q_vec": str(vec_list), **params_shared}
        kw_params  = {"q": query, **params_shared}

        try:
            vec_rows, kw_rows = await asyncio.gather(
                _exec_raw(engine, vector_sql, vec_params, presql=_VEC_PRESQL),
                _exec_raw(engine, keyword_sql, kw_params)
            )

            # ── Case-name OR Fallback (bounded — see knob comment) ────────
            # Only fires for case-name-style queries, where strict AND search
            # usually finds nothing but the distinctive party names make the
            # OR query cheap. ts_rank (not ts_rank_cd) keeps ranking cheap.
            # Only PARTY NAMES are ORed: ORing every word of a long multi-case
            # query matched 98.7% of the corpus and cost ~47s per query.
            if JUDGMENT_OR_FALLBACK and len(kw_rows) < 5 and _looks_like_case_name(query):
                stopwords = set(cfg["config"].get("case_name_stopwords") or [])
                words = _case_name_terms(query, stopwords)
                if len(words) > 1:
                    # See build_case_name_fallback_sql: party names are matched
                    # against the party columns, never against search_vector.
                    fallback_sql, fallback_params = build_case_name_fallback_sql(
                        words, ts_config, ct_filter_sql
                    )
                    try:
                        # Timeout-capped: the fallback is a nice-to-have rescue,
                        # never a reason to blow the request's latency budget.
                        kw_rows = await _exec_raw(
                            engine, fallback_sql,
                            {**fallback_params, **params_shared},
                            presql=f"SET LOCAL statement_timeout = {OR_FALLBACK_TIMEOUT_MS}",
                        )
                    except Exception as fallback_err:
                        print(f"[retrieve_judgment_chunks] OR Fallback SQL error: {fallback_err}")

        except Exception as sql_err:
            print(f"[retrieve_judgments] SQL error for query '{query}': {sql_err}")
            vec_rows = await _exec_raw(engine, vector_sql, vec_params, presql=_VEC_PRESQL)
            kw_rows = []

        return vec_rows, kw_rows

    # All 7 rewritten queries run concurrently — they were previously sequential,
    # which multiplied per-query DB latency by the number of queries.
    query_results = await asyncio.gather(
        *(_run_query(q) for q in queries), return_exceptions=True
    )

    # ── RRF fusion — SUM contributions across queries ────────────────────
    # A judgment surfaced by several of the 7 query angles is far more likely
    # to be on-point than one surfaced once, so scores accumulate (previously
    # only the single best query's score was kept).
    scores: dict = {}         # judgment_id → accumulated RRF score
    best_vec_row: dict = {}   # judgment_id → (best sem rank, best chunk row)
    kw_row_data: dict = {}    # judgment_id → BM25 row (document-level context)

    for qr in query_results:
        if isinstance(qr, BaseException):
            print(f"Judgment retrieval error: {qr}")
            continue
        vec_rows, kw_rows = qr
        # FIX 2: Only the FIRST occurrence of each judgment_id per query counts.
        #        vec_rows is ORDER BY distance ASC, so first = best chunk.
        seen_this_query = set()
        for idx, r in enumerate(vec_rows):
            jid = r.id  # aliased as judgment_id
            if jid in seen_this_query:
                continue
            seen_this_query.add(jid)
            scores[jid] = scores.get(jid, 0.0) + sem_weight / (60 + idx + 1)
            if jid not in best_vec_row or (idx + 1) < best_vec_row[jid][0]:
                best_vec_row[jid] = (idx + 1, r)
        # FIX 1: kw rows stay separate — BM25 rows use judgments.id directly
        #        and must NEVER overwrite the precise chunk text from vector rows.
        for idx, r in enumerate(kw_rows):
            scores[r.id] = scores.get(r.id, 0.0) + kw_weight / (60 + idx + 1)
            kw_row_data.setdefault(r.id, r)

    all_results: dict = {}
    for jid, rrf in scores.items():
        # FIX 1: Prefer the precise chunk row; fall back to BM25 row
        row = best_vec_row[jid][1] if jid in best_vec_row else kw_row_data.get(jid)
        if row is None:
            continue

        title = f"{row.petitioner} v. {row.respondent}" if row.petitioner else "Unknown"

        if USE_CHUNKS and jid in best_vec_row:
            # FIX 3 + IMPROVEMENT 5: Build two distinct text representations:
            #   chunk_text  → raw paragraph only (for cross-encoder: precise, short)
            #   text        → holding-prefixed chunk (for LLM prompt: context-rich)
            raw_chunk  = (getattr(row, "raw_chunk_text", "") or "")
            holding    = (getattr(row, "holding", "") or "")
            para_start = getattr(row, "paragraph_number_start", None)
            para_end   = getattr(row, "paragraph_number_end", None)

            para_label = ""
            if para_start is not None:
                if para_start == para_end:
                    para_label = f"[Para {para_start}] "
                else:
                    para_label = f"[Para {para_start}-{para_end}] "

            # IMPROVEMENT 5: Only prefix holding when this chunk is NOT the holding paragraph.
            # Heuristic: if the chunk text overlaps significantly with the holding, skip prefix.
            holding_words = set(holding.lower().split()) if holding else set()
            chunk_words   = set(raw_chunk.lower().split()[:50]) if raw_chunk else set()
            is_holding_chunk = len(holding_words & chunk_words) > 20  # >20 common words = same paragraph

            if holding and not is_holding_chunk:
                holding_prefix = f"HOLDING: {holding[:250]}\n\n"
            else:
                holding_prefix = ""

            llm_text   = holding_prefix + para_label + raw_chunk[:900]
            xenc_text  = raw_chunk[:500]  # Short + precise for cross-encoder

            all_results[jid] = {
                "id":          jid,
                "score":       rrf,
                "text":        llm_text,        # For LLM prompt assembly
                "chunk_text":  xenc_text,       # For cross-encoder (Fix 3)
                "chunk_id":    getattr(row, "chunk_id", None),
                "chunk_index": getattr(row, "chunk_index", None),
                "case_number": row.case_number or "",
                "title":       title,
                "year":        row.year,
                "case_type":   getattr(row, "case_type", "") or "",
                "holding":     holding[:300],
                "corpus":      "judgment",
            }
        else:
            # Phase 1 path (USE_CHUNKS=False) or BM25-only result
            kw_row = kw_row_data.get(jid)
            all_results[jid] = {
                "id":         jid,
                "score":      rrf,
                "text":       (getattr(kw_row, "chunk_text", "") or "")[:1000] if kw_row else "",
                "chunk_text": "",
                "case_number": row.case_number or "",
                "title":       title,
                "year":        row.year,
                "case_type":   getattr(row, "case_type", "") or "",
                "corpus":      "judgment",
            }

    winners = sorted(all_results.values(), key=lambda x: x["score"], reverse=True)[:30]

    # ── IMPROVEMENT 4: Context expansion — fetch ±1 neighbouring chunks ──
    # For each winner that came from a vector chunk, expand the LLM context by
    # appending the adjacent paragraph(s) so the AI sees WHY the court ruled that way.
    if USE_CHUNKS:
        expand_inputs = [
            (w["id"], w["chunk_index"])
            for w in winners
            if w.get("chunk_index") is not None
        ]
        if expand_inputs:
            try:
                # Single batch query: fetch neighbours for all winners at once
                # using UNNEST for an IN-style multi-value lookup.
                jids    = [x[0] for x in expand_inputs]
                cidxs   = [x[1] for x in expand_inputs]
                expand_sql = """
                    SELECT jc.judgment_id,
                           jc.chunk_index,
                           jc.chunk_text
                    FROM   judgment_chunks jc
                    WHERE  jc.judgment_id = ANY(:jids)
                      AND  jc.chunk_index = ANY(:cidxs)
                    ORDER  BY jc.judgment_id, jc.chunk_index
                """
                # Build a set of (judgment_id, chunk_index) pairs to fetch: self ± 1
                neighbour_cidxs = list({ci + delta for ci in cidxs for delta in (-1, 0, 1) if ci + delta >= 0})
                expand_rows = await _exec_raw(
                    engine, expand_sql,
                    {"jids": jids, "cidxs": neighbour_cidxs}
                )

                # Group neighbour chunks by judgment_id
                from collections import defaultdict
                neighbour_map: dict = defaultdict(list)
                for nr in expand_rows:
                    neighbour_map[nr.judgment_id].append((nr.chunk_index, nr.chunk_text))

                # For each winner, splice in the neighbour text AROUND the matched chunk
                for w in winners:
                    jid    = w["id"]
                    ci     = w.get("chunk_index")
                    if ci is None or jid not in neighbour_map:
                        continue
                    neighbours = sorted(neighbour_map[jid], key=lambda x: x[0])
                    # Build: [prev_chunk] [matched_chunk_already_in_text] [next_chunk]
                    prev_text = next((t for idx, t in neighbours if idx == ci - 1), "")
                    next_text = next((t for idx, t in neighbours if idx == ci + 1), "")
                    if prev_text or next_text:
                        expanded = ""
                        if prev_text:
                            expanded += f"[...preceding context]\n{prev_text[:300]}\n\n"
                        expanded += w["text"]   # Already contains the matched chunk
                        if next_text:
                            expanded += f"\n\n[...continuing]\n{next_text[:300]}"
                        w["text"] = expanded[:1200]   # Hard cap for LLM context budget
            except Exception as expand_err:
                # Non-fatal — context expansion is best-effort
                print(f"[retrieve_judgment_chunks] Context expansion error (non-fatal): {expand_err}")

    return winners



# ── Exact section-reference extraction ─────────────────────────────────────
# When a rewritten query explicitly names a provision ("Section 438 CrPC",
# "Section 45 of the Prevention of Money Laundering Act", "Article 21"),
# that section is looked up directly and boosted above fuzzy matches —
# fuzzy hybrid search alone often ranks a neighbouring section higher.
# Act-name → short_code aliases come from legal_codes.aliases (DB-driven,
# longest-first — see _get_runtime_config), replacing a hardcoded copy of
# the legal_codes table that drifted whenever an act was added.

_SECTION_REF_RE = re.compile(
    r"[Ss]ections?\s+(\d+[A-Za-z]{0,2})(?:\s*\([0-9A-Za-z]+\))?"   # 438, 41A, 13(2)
    r"[\s,]*(?:of\s+(?:the\s+)?)?"
    r"([A-Za-z][A-Za-z ,\.\-()]{0,70})?"                            # trailing act name
)
_ARTICLE_REF_RE = re.compile(r"[Aa]rticles?\s+(\d+[A-Za-z]?(?:-[A-Za-z])?)")


def _extract_section_refs(queries: list, act_aliases: list) -> set:
    """Return {(section_number, short_code)} explicitly referenced in queries."""
    refs = set()
    for q in queries:
        for m in _SECTION_REF_RE.finditer(q):
            sec, tail = m.group(1), (m.group(2) or "").lower()
            for name, code in act_aliases:
                # Whole-word check so 'ipc' doesn't match inside another word
                if re.search(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", tail):
                    refs.add((sec, code))
                    break
        for m in _ARTICLE_REF_RE.finditer(q):
            refs.add((m.group(1), "COI"))
    return refs


async def _lookup_exact_sections(engine, refs: set, coi_only: bool) -> list:
    """Direct lookups for explicitly-referenced sections; bypasses domain filter.

    All references resolve in ONE query — this previously issued a separate
    round trip (and pool checkout) per reference, serialising up to 12 Neon
    round trips into the critical path of every request.
    """
    if coi_only:
        refs = {(s, c) for s, c in refs if c == "COI"}
    if not refs:
        return []
    pairs = list(refs)[:12]
    try:
        return await _exec_raw(
            engine,
            """
                SELECT lcs.id, lcs.section_number, lcs.title, lcs.section_text, lc.short_code
                FROM   legal_code_sections lcs
                JOIN   legal_codes lc ON lc.id = lcs.legal_code_id
                JOIN   unnest(cast(:secs as varchar[]), cast(:codes as varchar[]))
                         AS want(sec, code)
                  ON   want.code = lc.short_code AND want.sec = lcs.section_number
            """,
            {"secs": [s for s, _ in pairs], "codes": [c for _, c in pairs]},
        )
    except Exception as e:
        print(f"[retrieve_statutes] Exact lookup failed for {pairs}: {e}")
        return []


async def retrieve_statutes(
    engine,
    queries: list,
    embedding_fn=None,
    coi_only: bool = False,
    document_type_key: str = "",
    subject_matter: str = "",
    context: str = "search",
    query_vectors: dict = None,
) -> list:
    """
    Hybrid search over legal_code_sections.
    When document_type_key is provided and context='citations', filters to relevant statute codes.
    coi_only filters to the Constitution of India — takes precedence over the code filter.
    """
    sem_weight = 1.5 if context == "citations" else 1.0
    kw_weight  = 1.5 if context == "citations" else 2.0

    cfg = await _get_runtime_config(engine)

    # Build domain filter
    code_filter_sql = ""
    code_params: dict = {}
    if coi_only:
        # By short_code, not a hardcoded legal_code_id (ids differ per environment)
        code_filter_sql = " AND lc.short_code = 'COI'"
    elif document_type_key and context == "citations":
        # Pass subject_matter so constitutional domain is included when relevant
        relevant_domains = _derive_statute_domains(cfg["config"], document_type_key, subject_matter)
        if relevant_domains:
            # PostgreSQL array overlap operator &&
            code_filter_sql = " AND lc.domains && cast(:allowed_domains as varchar[])"
            code_params["allowed_domains"] = relevant_domains

    async def _run_query(query: str):
        """Hybrid (vector + BM25) retrieval for one rewritten query."""
        if query_vectors and query in query_vectors:
            vec_list = query_vectors[query]
        elif embedding_fn:
            loop = asyncio.get_event_loop()
            vec = await loop.run_in_executor(_cpu_executor, embedding_fn, query)
            vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)
        else:
            return [], []

        vector_sql = f"""
            SELECT lcs.id, lcs.section_number, lcs.title, lcs.section_text, lc.short_code,
                   lcs.embedding <=> :q_vec AS distance
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
                                    websearch_to_tsquery('{ts_config}', :q)) AS rank_score
            FROM   legal_code_sections lcs
            JOIN   legal_codes lc ON lc.id = lcs.legal_code_id
            WHERE  lcs.search_vector @@ websearch_to_tsquery('{ts_config}', :q) {code_filter_sql}
            ORDER  BY rank_score DESC
            LIMIT  30
        """

        vec_params = {"q_vec": str(vec_list), **code_params}
        kw_params  = {"q": query, **code_params}

        try:
            vec_rows, kw_rows = await asyncio.gather(
                _exec_raw(engine, vector_sql, vec_params, presql=_VEC_PRESQL),
                _exec_raw(engine, keyword_sql, kw_params)
            )

            # ── Typo / Concept OR Fallback ────────────────────────────────
            if len(kw_rows) < 5:
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
                        kw_rows = await _exec_raw(
                            engine, fallback_sql, {"or_q": or_query, **code_params},
                            presql=f"SET LOCAL statement_timeout = {OR_FALLBACK_TIMEOUT_MS}",
                        )
                    except Exception as fallback_err:
                        print(f"[retrieve_statutes] OR Fallback SQL error: {fallback_err}")
        except Exception as sql_err:
            print(f"[retrieve_statutes] SQL error for query '{query}': {sql_err}")
            vec_rows = await _exec_raw(engine, vector_sql, vec_params, presql=_VEC_PRESQL)
            kw_rows = []

        return vec_rows, kw_rows

    # All queries in parallel + exact section-reference lookups alongside
    exact_task = _lookup_exact_sections(engine, _extract_section_refs(queries, cfg["aliases"]), coi_only)
    gathered = await asyncio.gather(
        *(_run_query(q) for q in queries), exact_task, return_exceptions=True
    )
    exact_rows = gathered[-1] if not isinstance(gathered[-1], BaseException) else []
    query_results = gathered[:-1]

    # ── RRF fusion — SUM contributions across queries (consensus ranking) ──
    scores: dict = {}
    row_data: dict = {}
    for qr in query_results:
        if isinstance(qr, BaseException):
            print(f"Statute retrieval error: {qr}")
            continue
        vec_rows, kw_rows = qr
        for idx, r in enumerate(vec_rows):
            scores[r.id] = scores.get(r.id, 0.0) + sem_weight / (60 + idx + 1)
            row_data.setdefault(r.id, r)
        for idx, r in enumerate(kw_rows):
            scores[r.id] = scores.get(r.id, 0.0) + kw_weight / (60 + idx + 1)
            row_data.setdefault(r.id, r)

    # ── Exact-reference boost — a provision named in a query must surface ──
    # 0.5 is far above any achievable fused RRF score, so exact refs sort first
    # while preserving relative order among themselves via the fuzzy score.
    exact_ids = set()
    for r in exact_rows:
        scores[r.id] = scores.get(r.id, 0.0) + 0.5
        row_data.setdefault(r.id, r)
        exact_ids.add(r.id)

    all_results = {}
    for sid, rrf in scores.items():
        row = row_data[sid]
        # Constitution provisions are Articles, not Sections
        provision = "Article" if (row.short_code or "") == "COI" else "Section"
        all_results[sid] = {
            "id": sid, "score": rrf,
            "text": (row.section_text or "")[:800],
            "title": f"{provision} {row.section_number} {row.title or ''} ({row.short_code})",
            "short_code": row.short_code or "",
            "section_number": row.section_number or "",
            "exact_match": sid in exact_ids,
            "corpus": "statute"
        }

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
                           embedding <=> :q_vec AS distance
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
                    _exec_raw(engine, vector_sql, {"q_vec": str(vec_list), "cid": court_identity_id, "ch": optional_chapters}, presql=_VEC_PRESQL),
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

    # Banner from the court identity row — this function serves every court,
    # not just the one it was first built for.
    banner = "COURT RULES"
    try:
        ident = await _exec_raw(
            engine,
            "SELECT court_name, rule_book_title FROM court_identities WHERE id = :cid",
            {"cid": court_identity_id},
        )
        if ident:
            court_name = (ident[0].court_name or "").upper()
            rule_book = ident[0].rule_book_title or "Rules of the Court"
            banner = f"{court_name} — {rule_book}".strip(" —")
    except Exception as e:
        print(f"[court_rules] identity lookup failed (generic banner used): {e}")

    # Build the formatted block, grouped by chapter
    sections = []
    for ch in sorted(rules_by_chapter.keys()):
        sections.append("\n".join(rules_by_chapter[ch]))

    return (
        f"=== {banner} (MANDATORY COMPLIANCE) ===\n"
        + "\n\n".join(sections)
        + "\n=== END COURT RULES ==="
    )

import os
import concurrent.futures
from jinja2 import Environment, FileSystemLoader, Undefined
from datetime import datetime

_reranker_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

# Initialize jinja2 env at module level
prompts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")
jinja_env = Environment(loader=FileSystemLoader(prompts_dir))


# ── Date rendering ───────────────────────────────────────────────────────────
# Every date in a filed pleading reads DD/MM/YYYY. The form stores dates as
# YYYY-MM-DD (that is what <input type="date"> produces) and the extractor
# normalises to the same, so without this filter the model was being handed ISO
# dates and told to reproduce them exactly — and it did, into the draft.

_PROMPT_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%Y/%m/%d",
    "%d %B %Y", "%d %b %Y",
    "%B %d, %Y", "%b %d, %Y",
)


def to_ddmmyyyy(value) -> str:
    """Render a date as DD/MM/YYYY. Unparseable input is passed through
    unchanged — a date the advocate typed in a form we do not recognise is
    still information, and dropping it would silently lose a row."""
    if value is None or isinstance(value, Undefined):
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    if hasattr(value, "strftime"):          # datetime.date
        return value.strftime("%d/%m/%Y")

    raw = str(value).strip()
    if not raw:
        return ""

    for fmt in _PROMPT_DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return raw


jinja_env.filters["dmy"] = to_ddmmyyyy

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
        seen_keys = set()
        if candidates:
            max_score = candidates[0].get("score", 0.0)
            for c in candidates:
                s = c.get("score", 0.0)
                if not c.get("exact_match"):
                    if s < 0.015:  # Absolute noise cutoff
                        continue
                    if s < max_score * 0.5:  # Relative drop-off (50% drop from the best result)
                        continue
                # The judgments corpus contains duplicate rows under different
                # ids — drop repeats of the same case (title + year).
                key = ((c.get("title") or "").strip().lower(), c.get("year"))
                if key[0] and key in seen_keys:
                    continue
                seen_keys.add(key)
                c["rerank_score"] = s * 100
                filtered.append(c)
        return filtered[:top_k]

    # Cross-encoder path (enabled for citation suggestion)
    try:
        reranker = await load_reranker()
        # FIX 3: Prefer chunk_text (precise raw paragraph) over text (holding-prefixed LLM text)
        # for cross-encoder input. The cross-encoder has a ~512-token window — the precise
        # matching paragraph is far more informative than 1000 chars of boilerplate.
        pairs = [
            (combined_query, c.get("chunk_text") or c.get("text", ""))
            for c in candidates
        ]
        loop = asyncio.get_event_loop()

        # Removed asyncio.wait_for because on Windows ProactorEventLoop, cancelling a thread pool
        # future causes a fatal AttributeError ('NoneType' object has no attribute 'send') when the
        # thread eventually finishes and tries to notify the closed loop.
        scores = await loop.run_in_executor(_reranker_executor, reranker.predict, pairs)

        for i, c in enumerate(candidates):
            c["rerank_score"] = float(scores[i])
        reranked = sorted(candidates, key=lambda x: x.get("rerank_score", 0), reverse=True)
        return _filter_reranked(reranked)[:top_k]
    except Exception as e:
        print(f"[reranker] Cross-encoder error: {e} — falling back to RRF order")
        return candidates[:top_k]


# Cross-encoder drop-off, in logits, and the number of results that survive it
# regardless. A flat 2.0 drop-off routinely cut a ranked list of 25 down to a
# single suggestion, so Step 6 offered the user one precedent to choose from.
RERANK_DROPOFF = float(os.getenv("RAG_RERANK_DROPOFF", "4.0"))
RERANK_MIN_RESULTS = int(os.getenv("RAG_RERANK_MIN_RESULTS", "5"))


def _filter_reranked(reranked: list) -> list:
    """Drop-off filter + duplicate-case removal for cross-encoder-scored lists.

    Deduplication always applies; the score drop-off only starts pruning once
    RERANK_MIN_RESULTS distinct candidates have been kept, so a confident top
    hit can no longer suppress the rest of the list.
    """
    filtered = []
    seen_keys = set()
    if reranked:
        max_score = reranked[0].get("rerank_score", 0.0)
        for c in reranked:
            # Drop duplicate cases (same title + year under different ids)
            key = ((c.get("title") or "").strip().lower(), c.get("year"))
            if key[0] and key in seen_keys:
                continue
            s = c.get("rerank_score", 0.0)
            # Cross-encoder scores are logits (roughly -10..+10), so there is no
            # meaningful absolute cutoff — only distance from the best match.
            # Explicitly-cited sections (exact_match) always survive.
            if (len(filtered) >= RERANK_MIN_RESULTS
                    and s < max_score - RERANK_DROPOFF
                    and not c.get("exact_match")):
                continue
            seen_keys.add(key)
            filtered.append(c)
    return _exact_matches_first(filtered)


def _exact_matches_first(items: list) -> list:
    """Float explicitly-referenced provisions to the top, order otherwise kept.

    When a query names a provision ("Section 438 CrPC"), that section is the
    answer. The cross-encoder — a general web-relevance model — routinely
    scored a fuzzy neighbour above it and pushed the named section out of the
    visible window entirely.
    """
    if not any(c.get("exact_match") for c in items):
        return items
    return ([c for c in items if c.get("exact_match")]
            + [c for c in items if not c.get("exact_match")])


# ── LLM listwise rerank (default reranker) ─────────────────────────────────
# One gpt-4o-mini JSON call scores every candidate against the RAW case facts
# (the cross-encoder is stuck with a truncated 3-query proxy and a 2020-era
# web-search relevance notion). Benchmarked 2026-07-29 over 25 scenarios: beat
# the cross-encoder on every accuracy measure — statute gold R@8 46.9% vs
# 43.8%, landmark-case hit 24% vs 16%, P@5 judgments 39.2% vs 28.0%.
# It is also SLOWER: that run averaged 33.7s against the cross-encoder's 21.5s,
# which is why RERANK_CANDIDATES/RERANK_SNIPPET_CHARS below trim the prompt.
# Set RAG_LLM_RERANK=0 to fall back to the cross-encoder.
LLM_RERANK = os.getenv("RAG_LLM_RERANK", "1") == "1"
RERANK_LLM_MODEL = os.getenv("RAG_RERANK_LLM_MODEL", "openai/gpt-4o-mini")
# Prompt size drives rerank latency directly: 25+25 candidates at 350 chars is
# ~18k characters per call. Trimming both is the cheapest way to buy back the
# latency the LLM reranker costs over the cross-encoder.
RERANK_CANDIDATES = int(os.getenv("RAG_RERANK_CANDIDATES", "15"))
RERANK_SNIPPET_CHARS = int(os.getenv("RAG_RERANK_SNIPPET_CHARS", "250"))


async def llm_rerank_multi(facts: str, groups: dict, top_ks: dict) -> dict:
    """Listwise LLM rerank of several candidate lists in one call.

    groups: {name: candidates}; returns {name: reranked+filtered list}.
    Raises on failure — callers fall back to the cross-encoder.
    """
    if not any(groups.values()):
        return {name: [] for name in groups}

    listing = ""
    for name, cands in groups.items():
        listing += f"\n## {name.upper()}\n"
        for i, c in enumerate(cands):
            snippet = (c.get("chunk_text") or c.get("text") or "")[:RERANK_SNIPPET_CHARS]
            listing += f"[{name}-{i}] {c.get('title', '')}\n{snippet}\n\n"

    client = get_openrouter_client()
    resp = await client.chat.completions.create(
        model=RERANK_LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert Indian Supreme Court research clerk. Score how useful each "
                    "retrieved item is for drafting the document described by the case facts: "
                    "10 = directly applicable provision or squarely on-point precedent, "
                    "5 = related but generic, 0 = irrelevant. Judge statutes by whether the exact "
                    "provision governs these facts; judge precedents by whether their holding "
                    "supports the relief sought. Output ONLY JSON: "
                    '{"scores": {"<item-id>": <0-10>, ...}} with one entry per item id.'
                ),
            },
            {"role": "user", "content": f"CASE FACTS:\n{facts[:1800]}\n\nITEMS:{listing}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=2000,
    )
    scores = json.loads(resp.choices[0].message.content).get("scores", {})

    out = {}
    for name, cands in groups.items():
        for i, c in enumerate(cands):
            try:
                c["rerank_score"] = float(scores.get(f"{name}-{i}", 0))
            except (TypeError, ValueError):
                c["rerank_score"] = 0.0
        ranked = sorted(cands, key=lambda x: x.get("rerank_score", 0), reverse=True)
        # Same shape as _filter_reranked, on the 0-10 scale: dedupe always,
        # drop-off only once the minimum number of results is already kept.
        filtered, seen = [], set()
        max_s = ranked[0].get("rerank_score", 0.0) if ranked else 0.0
        for c in ranked:
            key = ((c.get("title") or "").strip().lower(), c.get("year"))
            if key[0] and key in seen:
                continue
            s = c.get("rerank_score", 0.0)
            if (len(filtered) >= RERANK_MIN_RESULTS
                    and not c.get("exact_match")
                    and (s < 3.0 or s < max_s - 4.0)):
                continue
            seen.add(key)
            filtered.append(c)
        out[name] = _exact_matches_first(filtered)[: top_ks.get(name, 10)]
    return out


async def rerank_multi(combined_query: str, groups: dict, top_ks: dict, facts: str = "") -> dict:
    """
    Rerank several candidate lists in ONE model call.

    Dispatches to the LLM listwise reranker when RAG_LLM_RERANK is enabled
    (using the raw facts, which carry far more signal than the query proxy),
    otherwise scores with the local cross-encoder. Falls back gracefully:
    LLM failure → cross-encoder → input order.

    groups:  {name: candidates}, top_ks: {name: top_k}
    Returns {name: reranked+filtered list}; falls back to input order on error.
    """
    if LLM_RERANK:
        try:
            return await llm_rerank_multi(facts or combined_query, groups, top_ks)
        except Exception as e:
            print(f"[reranker] LLM rerank error: {e} — falling back to cross-encoder")
    pairs, owners = [], []
    for name, cands in groups.items():
        for c in cands:
            pairs.append((combined_query, c.get("chunk_text") or c.get("text", "")))
            owners.append(c)
    if not pairs:
        return {name: [] for name in groups}

    try:
        reranker = await load_reranker()
        loop = asyncio.get_event_loop()
        scores = await loop.run_in_executor(_reranker_executor, reranker.predict, pairs)
        for c, s in zip(owners, scores):
            c["rerank_score"] = float(s)
        return {
            name: _filter_reranked(
                sorted(cands, key=lambda x: x.get("rerank_score", 0), reverse=True)
            )[:top_ks.get(name, 10)]
            for name, cands in groups.items()
        }
    except Exception as e:
        print(f"[reranker] Batched rerank error: {e} — falling back to RRF order")
        return {name: cands[:top_ks.get(name, 10)] for name, cands in groups.items()}


# ===========================================================================
# STAGE 5 — Context Assembly
# ===========================================================================
# Prompt templates live at prompts/document_types/<document_type_key>.txt —
# resolved by convention (writ_petition.txt is the fallback), so adding a new
# doc type only requires dropping a template file, not editing a mapping.


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



# An application to CANCEL a bail order and an application FOR bail are both
# drafted from the bail templates, and they need opposite affidavit clauses. The
# relief the advocate actually asked for is the only reliable signal.
_BAIL_CANCELLATION = re.compile(
    r"cancel\w*\b[^.]{0,80}\bbail|\bbail\b[^.]{0,80}\bcancel",
    re.IGNORECASE,
)


def _seeks_bail_cancellation(form_data: dict) -> bool:
    haystack = " ".join(
        str((form_data or {}).get(k) or "")
        for k in ("relief_sought", "document_type", "interim_relief_sought")
    )
    return bool(_BAIL_CANCELLATION.search(haystack))


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

    # Bug 1b fix: include case_number + year prominently so LLM cites the right identifier.
    # Use 'holding' field if available; fall back to raw text snippet.
    def _fmt_judgment(r):
        title = r.get('title', 'Unknown')
        case_no = r.get('case_number', '')
        year = r.get('year', '')
        # Prefer a dedicated holding field if populated
        snippet = r.get('holding') or r.get('text', '')
        snippet = snippet[:700] if snippet else ''
        block = (
            f"- {title} [{case_no}] ({year}):\n"
            f"  HOLDING (cite ONLY for this proposition): {snippet}"
        )

        # Paragraphs the advocate ticked in Step 6. These are whole numbered
        # paragraphs lifted from the judgment text itself, with the number the
        # report printed — so they must be reproduced exactly, not summarised.
        quoted = r.get('quoted_paragraph_texts') or []
        for para in quoted:
            label = para.get('label', '')
            text = (para.get('text') or '').strip()
            if not text:
                continue
            caveat = ""
            if para.get('uncertain'):
                caveat = (f"  (The scan lost a marker, so this block covers paragraphs "
                          f"{label}. Introduce it as \"paragraphs {label}\".)\n")
            block += (
                f"\n  VERBATIM QUOTE — paragraph {label} of {title}. Reproduce this "
                f"text EXACTLY as an indented block quote in the Grounds. Do NOT "
                f"paraphrase, summarise, shorten, re-number or correct it:\n"
                f"{caveat}"
                f"  \"\"\"{text}\"\"\""
            )
        return block

    judgments_block = "\n".join(
        _fmt_judgment(r) for r in judgment_results[:5]
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

    # Per-doc-type template routing by filename convention; falls back to
    # writ_petition.txt when no template exists for this doc type yet.
    doc_type_key = form_data.get("document_type_key") or ""
    try:
        template = jinja_env.get_template(f"document_types/{doc_type_key or 'writ_petition'}.txt")
    except Exception:
        template = jinja_env.get_template("document_types/writ_petition.txt")

    # Bug 4 fix: merge user-provided mandatory_paragraphs (free-text field) into body_paras.
    # This ensures the LLM's MANDATORY PARAGRAPHS list includes both DB-seeded and
    # user-typed custom paragraphs, preventing any from being silently dropped.
    user_mandatory_text = form_data.get("mandatory_paragraphs", "").strip()
    merged_body_paras = list((mandatory_paragraphs or {}).get("body_paras", []))
    if user_mandatory_text:
        # Split by newline or semicolon to support multiple custom paragraphs
        import re as _re
        custom_items = [p.strip() for p in _re.split(r'[\n;]+', user_mandatory_text) if p.strip()]
        for item in custom_items:
            merged_body_paras.append({"instruction": item, "is_conditional": False})

    # Bug 2 fix: compute has_uploads so templates can guard the ANNEXURES section.
    has_uploads = bool(uploaded_docs_context and uploaded_docs_context.strip())

    # Per-court drafting conventions ("Opposite Parties" vs "Respondents", whether
    # a synopsis belongs in the paper book, the affidavit tail, the section
    # order). Unknown courts get the default profile, which is the behaviour that
    # existed before core/court_profile.py.
    from app.core.court_profile import (
        court_profile,
        deponent_terms,
        filing_place,
        has_interim_relief,
        required_sections,
    )

    profile = court_profile(
        court_level=form_data.get("court_level", ""),
        court_display=court_display,
        document_type_key=doc_type_key,
    )
    wants_interim = has_interim_relief(form_data)

    # The filing date is not known when the draft is generated — the paper book
    # is signed and filed days later — so the day stays a blank the advocate
    # completes, while the month and year are the ones being filed in.
    now = datetime.now()

    context = {
        "current_year":        now.year,
        "filing_date":         now.strftime("___/%m/%Y"),
        "filing_place":        filing_place(
                                   court_level=form_data.get("court_level", ""),
                                   court_display=court_display,
                                   court_place=form_data.get("court_place", "") or "",
                               ),
        "deponent":            deponent_terms(doc_type_key),
        "seeks_bail_cancellation": _seeks_bail_cancellation(form_data),
        "doc_type":            doc_type,
        "doc_type_key":        doc_type_key,
        "court_display":       court_display,
        "profile":             profile,
        "has_interim_relief":  wants_interim,
        "required_sections":   required_sections(profile, doc_type_key, wants_interim),
        "jurisdiction_warning": jurisdiction_warning,
        "petitioners":         petitioners,
        "respondents":         respondents,
        "form_data":           form_data,
        "uploaded_docs_context": uploaded_docs_context,
        "has_uploads":         has_uploads,
        "statutes_block":      statutes_block,
        "judgments_block":     judgments_block,
        "court_rules_block":   court_rules_block,
        "structure_rules":     structure_rules or [],
        "opening_paras":       (mandatory_paragraphs or {}).get("opening_paras", []),
        "body_paras":          merged_body_paras,
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
    # Match patterns like Section 302 IPC / Section 21 BNS — the recognised
    # short codes come from legal_codes, so newly ingested acts are verifiable
    cfg = await _get_runtime_config(engine)
    short_codes = sorted({code for _, code in cfg["aliases"]}, key=len, reverse=True)
    if not short_codes:
        short_codes = ["IPC", "BNS", "CrPC", "BNSS", "COI", "SRA", "CPC", "BSA"]
    codes_alt = "|".join(re.escape(c) for c in short_codes)
    section_pattern = re.compile(
        r'Section\s*\d+[A-Z]?\s*(?:of\s*(?:the\s*)?)?(?:' + codes_alt + r')\b'
    )

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
        code_match = re.search(r'(' + codes_alt + r')\b', citation)
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
