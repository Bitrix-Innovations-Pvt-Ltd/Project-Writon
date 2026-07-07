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
                        "extract 3-5 specific legal search queries that would retrieve the most "
                        "relevant Indian court judgments and statute sections. "
                        "Return ONLY a JSON object with key 'queries' containing an array of strings."
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

async def retrieve_judgment_chunks(engine, queries: list, embedding_fn) -> list:
    """Hybrid search over judgment_chunks. Returns up to 30 ranked candidates."""
    all_results = {}

    for query in queries:
        try:
            loop = asyncio.get_event_loop()
            vec = await loop.run_in_executor(None, embedding_fn, query)
            vec_list = vec.tolist() if hasattr(vec, "tolist") else list(vec)

            vector_sql = """
                SELECT jc.id, jc.chunk_text,
                       j.case_number, j.petitioner, j.respondent, j.year,
                       ROW_NUMBER() OVER (ORDER BY jc.embedding <-> :q_vec) AS rank
                FROM   judgment_chunks jc
                JOIN   judgments j ON j.id = jc.judgment_id
                WHERE  jc.embedding IS NOT NULL
                ORDER  BY rank
                LIMIT  30
            """
            keyword_sql = """
                SELECT jc.id, jc.chunk_text,
                       j.case_number, j.petitioner, j.respondent, j.year,
                       ROW_NUMBER() OVER (
                           ORDER BY ts_rank(j.search_vector,
                                            websearch_to_tsquery('english', :q)) DESC
                       ) AS rank
                FROM   judgment_chunks jc
                JOIN   judgments j ON j.id = jc.judgment_id
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
            vec = await loop.run_in_executor(None, embedding_fn, query)
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


# ===========================================================================
# STAGE 4 — Cross-Encoder Reranking
# ===========================================================================
async def rerank_candidates(combined_query: str, candidates: list, top_k: int = 10) -> list:
    """Rerank top 50 candidates from all corpora down to top_k using cross-encoder."""
    if not candidates:
        return []
    try:
        reranker = await load_reranker()
        pairs = [(combined_query, c["text"]) for c in candidates]
        loop = asyncio.get_event_loop()
        scores = await loop.run_in_executor(None, lambda: reranker.predict(pairs))
        for i, c in enumerate(candidates):
            c["rerank_score"] = float(scores[i])
        return sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)[:top_k]
    except Exception as e:
        print(f"Reranking failed ({e}), falling back to RRF order.")
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

    return f"""You are an expert Indian legal advocate with 40+ years of High Court and Supreme Court experience.
Draft a complete, formal, court-ready {doc_type} for filing in {court_display}.

{jurisdiction_warning}

CASE INFORMATION:
- Current Year: 2026
- Document Type: {doc_type}
- Subject Matter: {subject_matter}
- Petitioner(s): {petitioners}
- Respondent(s): {respondents}
- Advocate on Record: {form_data.get('advocate_name', '')} (Enrollment: {form_data.get('advocate_enrollment_no', '')})
- Jurisdiction Basis: {form_data.get('jurisdiction_basis', '')}
- Date of Impugned Order: {form_data.get('impugned_order_date', 'N/A')}

FACTS OF THE CASE:
{form_data.get('facts_of_case', form_data.get('case_description', ''))}

GROUNDS PROVIDED BY USER:
{form_data.get('grounds', '')}

FINAL RELIEF SOUGHT:
{form_data.get('relief_sought', '')}

INTERIM RELIEF SOUGHT:
{form_data.get('interim_relief_sought', 'Not specifically requested.')}

{uploaded_docs_context}

RELEVANT STATUTE SECTIONS (from legal corpus — cite these accurately):
{statutes_block}

RELEVANT PRECEDENTS (from judgment corpus — cite these accurately):
{judgments_block}

DRAFTING INSTRUCTIONS (MUST FOLLOW STRICTLY):
1. Write a COMPLETE formal legal document in this EXACT sequential order: (1) Court Heading & Cause Title (for the cover). (2) Index. (3) Synopsis. (4) List of Dates. (5) Court Heading & Cause Title (repeated for the main petition). (6) Main Petition body (Facts, Grounds). (7) Prayer. (8) Affidavit. (9) Vakalatnama. (10) List of Annexures. Insert a markdown horizontal rule (`---`) strictly ONLY to separate these major sections->not before index , After the Index,after Synopsis, after the List of Dates, after the Prayer, after the Affidavit, and after the Vakalatnama. Do NOT insert `---` anywhere else.
2. INITIAL FORMAT & CURRENT YEAR: In the cause title, court heading, and all text throughout the petition, the filing year must be 2026 (e.g., "WRIT PETITION (CIVIL) NO. _____ OF 2026"). Ensure all initial fields are perfectly formatted. Do not miss any fields.
3. CAUSE TITLE FORMATTING: To ensure proper court-compliant layouts, you MUST write the Cause Title using HTML flexbox styling rather than markdown. This places details on the left, and roles (e.g., ".......Petitioner", ".......Opposite Party/Respondent") right-aligned, and centered "Versus". Use this exact HTML structure:
<div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 0.5rem;">
  <div><strong>[Name of Petitioner]</strong><br/>[Parentage/Details],<br/>[Address].</div>
  <div style="font-weight: bold; min-width: 150px; text-align: right;">.......Petitioner</div>
</div>
<div style="text-align: center; font-weight: bold; margin: 1rem 0;">Versus</div>
<div style="display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 0.5rem;">
  <div><strong>[Name of Respondent]</strong><br/>[Details],<br/>[Address].</div>
  <div style="font-weight: bold; min-width: 150px; text-align: right;">.......Respondent</div>
</div>
4. TRUTHFULNESS & NO HALLUCINATION: You MUST ONLY use the facts, events, and explicitly provided dates (especially the "List of Dates") from the FACTS OF THE CASE, CASE INFORMATION, and UPLOADED DOCUMENTS. Do NOT create, invent, or hallucinate any dates, facts, or events. If a date is not provided, use blank lines (e.g., "___/___/2026") instead of inventing it. Strictly format the List of Dates and Events exactly as provided without changing them.
5. PARAGRAPH NUMBERING & NARRATIVE: As per E-Filing rules, EVERY paragraph in the main body (Synopsis, Petition facts, Grounds) must be numbered sequentially. Synthesize the provided facts, grounds, and UPLOADED DOCUMENTS into a cohesive, chronological narrative. Write like a seasoned advocate (e.g., "1. That the petitioner submits that...").
6. JURISDICTION: Include a specific, numbered paragraph establishing the court's jurisdiction to hear the matter (e.g., "This Hon'ble Court has jurisdiction under...").
7. DETAILED GROUNDS: Do not write one-liners. Start each ground with "Because..." (e.g., "Because the impugned order is arbitrary and violative of Article 14..."). 
8. CITE LAW IN GROUNDS: Weave the provided statutes and precedents into the grounds explicitly. Use EXACT section numbers and case citations provided above. If no specific precedents are provided, you MUST invoke standard constitutional provisions (e.g., Articles 14, 16, 21, 32, 226) and broadly established legal principles applicable to the case. STRICT ANTI-HALLUCINATION RULE: Do NOT invent fictitious case names, case numbers, or citations. If citing a specific case, you must ONLY use the ones provided in the RELEVANT PRECEDENTS block. If that block is empty, do not cite any specific cases.
9. PRAYER: Number the final reliefs as lettered points (a, b, c). Always include standard prayers like "Pass any other order or direction as this Hon'ble Court may deem fit and proper in the interest of justice." and "Award costs".
10. COMPLETE ENDINGS (NO PLACEHOLDERS): Do NOT write simple placeholders like "[Placeholder for Affidavit]" or "[Placeholder for Vakalatnama]". You MUST draft the full, formal legal text for the Affidavit, the Vakalatnama, and the List of Annexures:
    - For the Affidavit: Write out the full solemn affirmation text for the petitioner (e.g., "I, {petitioners}, do hereby solemnly affirm and state as under: 1. That I am the Petitioner..."). Use blank lines "_________" for the Deponent's signature and the verification date. CRITICAL: Do NOT use dashes `---` for signature lines, use underscores `___`.
    - For the Vakalatnama: Write out the full authorization text (e.g., "Know all men by these presents that I, {petitioners}, do hereby appoint and constitute {form_data.get('advocate_name', '')}, Advocate (Enrollment No. {form_data.get('advocate_enrollment_no', '')}) to act, appear, and plead..."). Use blank lines "_________" for the Petitioner and Advocate signatures. CRITICAL: Do NOT use dashes `---` for signature lines.
    - For the List of Annexures: List the actual uploaded documents by their names.
11. Use standard markdown formatting. Use tables for the Index and the List of Dates. Use formal Indian legal English.
12. Begin drafting immediately without preamble."""


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
