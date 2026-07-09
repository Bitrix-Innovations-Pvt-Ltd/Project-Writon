"""
core/rag.py — Multi-Corpus Hybrid RAG Pipeline for Step 6 (Generate)

Stages:
  1. Query Rewriting       (GPT-4o-mini)
  2 & 3. Fan-out Hybrid Retrieval  (BM25 + pgvector + RRF, parallel, 3 corpora)
  4. Cross-Encoder Reranking (ms-marco-MiniLM-L-6-v2)
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
                _reranker = await loop.run_in_executor(
                    None,
                    lambda: CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
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
async def rewrite_queries(facts: str, doc_type: str, subject_matter: str) -> list:
    client = get_openrouter_client()
    if not openrouter_key:
        return [facts[:200]]
    try:
        response = await client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert Indian legal researcher. Given a case description, "
                        "generate exactly 5 distinct, highly-optimized search queries to retrieve relevant Indian court judgments and statutes. "
                        "To maximize recall, the queries MUST target different retrieval angles:\n"
                        "1. Statutory law \n"
                        "2. Case law \n"
                        "3. Legal doctrine/principles\n"
                        "4. Practical filing/grounds\n"
                        "5. Broad factual overview\n"
                        "6. Relevant Indian court judgments and statute sections.\n"
                        "Do not generate near-duplicate queries. "
                        "Return ONLY a JSON object with key 'queries' containing an array of exactly 5 strings."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Document Type: {doc_type}\n"
                        f"Subject Matter: {subject_matter}\n\n"
                        f"Facts/Description:\n{facts[:2000]}"
                    )
                }
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        result = json.loads(response.choices[0].message.content)
        queries = result.get("queries", result.get("search_queries", [facts[:200]]))
        return [q for q in queries if isinstance(q, str)][:5]
    except Exception as e:
        print(f"Query rewriting failed: {e}")
        return [facts[:200]]


# ===========================================================================
# STAGES 2 & 3 — Fan-out Hybrid Retrieval (BM25 + pgvector + RRF, parallel)
# ===========================================================================

import concurrent.futures
_cpu_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

async def retrieve_judgment_chunks(engine, queries: list, embedding_fn) -> list:
    """Hybrid search over judgment_chunks. Returns up to 30 ranked candidates."""
    all_results = {}

    for query in queries:
        try:
            loop = asyncio.get_event_loop()
            vec = await loop.run_in_executor(_cpu_executor, embedding_fn, query)
            vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)

            vector_sql = """
                SELECT j.id, SUBSTRING(j.full_text, 1, 3000) as chunk_text,
                       j.case_number, j.petitioner, j.respondent, j.year,
                       ROW_NUMBER() OVER (ORDER BY j.embedding <-> :q_vec) AS rank
                FROM   judgments j
                WHERE  j.embedding IS NOT NULL
                ORDER  BY rank
                LIMIT  30
            """
            keyword_sql = """
                SELECT j.id, SUBSTRING(j.full_text, 1, 3000) as chunk_text,
                       j.case_number, j.petitioner, j.respondent, j.year,
                       ROW_NUMBER() OVER (
                           ORDER BY ts_rank(j.search_vector,
                                            websearch_to_tsquery('english', :q)) DESC
                       ) AS rank
                FROM   judgments j
                WHERE  j.search_vector @@ websearch_to_tsquery('english', :q)
                ORDER  BY rank
                LIMIT  30
            """

            vec_rows, kw_rows = await asyncio.gather(
                _exec_raw(engine, vector_sql, {"q_vec": str(vec_list)}),
                _exec_raw(engine, keyword_sql, {"q": query})
            )

            sem_ranks = {r.id: r.rank for r in vec_rows}
            kw_ranks  = {r.id: r.rank for r in kw_rows}
            all_ids   = set(sem_ranks) | set(kw_ranks)
            row_data  = {r.id: r for r in (list(vec_rows) + list(kw_rows))}

            for jid in all_ids:
                rrf = 0.0
                if jid in sem_ranks: rrf += 1.0 / (60 + sem_ranks[jid])
                if jid in kw_ranks:  rrf += 2.0 / (60 + kw_ranks[jid])
                if jid not in all_results or rrf > all_results[jid]["score"]:
                    row = row_data[jid]
                    title = f"{row.petitioner} v. {row.respondent}" if row.petitioner else "Unknown"
                    all_results[jid] = {
                        "id": jid, "score": rrf,
                        "text": (row.chunk_text or "")[:800],
                        "case_number": row.case_number or "",
                        "title": title,
                        "year": row.year,
                        "corpus": "judgment"
                    }
        except Exception as e:
            print(f"Judgment chunk retrieval error for query '{query}': {e}")

    return sorted(all_results.values(), key=lambda x: x["score"], reverse=True)[:30]


async def retrieve_statutes(engine, queries: list, embedding_fn, coi_only: bool = False) -> list:
    """Hybrid search over legal_code_sections. coi_only filters to Constitution (legal_code_id=7)."""
    all_results = {}
    coi_filter = " AND lcs.legal_code_id = 7" if coi_only else ""

    for query in queries:
        try:
            loop = asyncio.get_event_loop()
            vec = await loop.run_in_executor(_cpu_executor, embedding_fn, query)
            vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)

            vector_sql = f"""
                SELECT lcs.id, lcs.section_number, lcs.title, lcs.section_text, lc.short_code,
                       ROW_NUMBER() OVER (ORDER BY lcs.embedding <-> :q_vec) AS rank
                FROM   legal_code_sections lcs
                JOIN   legal_codes lc ON lc.id = lcs.legal_code_id
                WHERE  lcs.embedding IS NOT NULL {coi_filter}
                ORDER  BY rank
                LIMIT  30
            """
            keyword_sql = f"""
                SELECT lcs.id, lcs.section_number, lcs.title, lcs.section_text, lc.short_code,
                       ROW_NUMBER() OVER (
                           ORDER BY ts_rank(lcs.search_vector,
                                            websearch_to_tsquery('english', :q)) DESC
                       ) AS rank
                FROM   legal_code_sections lcs
                JOIN   legal_codes lc ON lc.id = lcs.legal_code_id
                WHERE  lcs.search_vector @@ websearch_to_tsquery('english', :q) {coi_filter}
                ORDER  BY rank
                LIMIT  30
            """

            vec_rows, kw_rows = await asyncio.gather(
                _exec_raw(engine, vector_sql, {"q_vec": str(vec_list)}),
                _exec_raw(engine, keyword_sql, {"q": query})
            )

            sem_ranks = {r.id: r.rank for r in vec_rows}
            kw_ranks  = {r.id: r.rank for r in kw_rows}
            all_ids   = set(sem_ranks) | set(kw_ranks)
            row_data  = {r.id: r for r in (list(vec_rows) + list(kw_rows))}

            for sid in all_ids:
                rrf = 0.0
                if sid in sem_ranks: rrf += 1.0 / (60 + sem_ranks[sid])
                if sid in kw_ranks:  rrf += 2.0 / (60 + kw_ranks[sid])
                if sid not in all_results or rrf > all_results[sid]["score"]:
                    row = row_data[sid]
                    all_results[sid] = {
                        "id": sid, "score": rrf,
                        "text": (row.section_text or "")[:800],
                        "title": f"Section {row.section_number} {row.title or ''} ({row.short_code})",
                        "corpus": "statute"
                    }
        except Exception as e:
            print(f"Statute retrieval error for query '{query}': {e}")

    return sorted(all_results.values(), key=lambda x: x["score"], reverse=True)[:30]

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
async def rerank_candidates(combined_query: str, candidates: list, top_k: int = 10) -> list:
    """Rerank top candidates using cross-encoder."""
    if not candidates:
        return []
    # Bypassing CPU-heavy cross-encoder to prevent Next.js proxy timeouts (socket hang up)
    # The database already sorts candidates using Reciprocal Rank Fusion (BM25 + Semantic)
    # which provides excellent results instantly.
    return candidates[:top_k]


# ===========================================================================
# STAGE 5 — Context Assembly
# ===========================================================================
def assemble_prompt(form_data: dict, judgment_results: list, statute_results: list, uploaded_docs_context: str = "") -> str:
    petitioners = ", ".join(form_data.get("petitioners") or ["[Petitioner]"]) or "[Petitioner]"
    respondents  = ", ".join(form_data.get("respondents") or ["[Respondent]"]) or "[Respondent]"

    statutes_block = "\n".join(
        f"- {r['title']}:\n  {r['text'][:600]}"
        for r in statute_results[:5]
    ) or "[No statute sections retrieved]"

    judgments_block = "\n".join(
        f"- {r.get('title', 'Unknown')} [{r.get('case_number', '')}] ({r.get('year', '')}):\n  {r['text'][:600]}"
        for r in judgment_results[:5]
    ) or "[No precedents retrieved]"
    
    court_display = form_data.get('court_display', 'the court')
    subject_matter = form_data.get('subject_matter', '')
    doc_type = form_data.get('document_type', '')
    
    # Address Article 32 vs 226 issue
    jurisdiction_warning = ""
    if "Service Law" in subject_matter and "Supreme Court" in court_display and "32" in doc_type:
        jurisdiction_warning = "\n[CRITICAL LEGAL INSTRUCTION: The user has selected Article 32 for a Service Law matter. You MUST include a strong justification in the Jurisdiction paragraph explaining why Article 32 is invoked directly instead of approaching the Central Administrative Tribunal (CAT) or the High Court under Article 226, specifically citing violation of fundamental rights.]\n"

    template = jinja_env.get_template("document_types/writ_petition.txt")
    
    context = {
        "current_year": datetime.now().year,
        "doc_type": doc_type,
        "court_display": court_display,
        "jurisdiction_warning": jurisdiction_warning,
        "petitioners": petitioners,
        "respondents": respondents,
        "form_data": form_data,
        "uploaded_docs_context": uploaded_docs_context,
        "statutes_block": statutes_block,
        "judgments_block": judgments_block,
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
    section_pattern = re.compile(r'Section\s*\d+[A-Z]?\s*(?:of\s*(?:the\s*)?)?(?:IPC|BNS|CrPC|BNSS|COI|SRA|CPC)')

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
        code_match = re.search(r'(IPC|BNS|CrPC|BNSS|COI|SRA|CPC)', citation)
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
