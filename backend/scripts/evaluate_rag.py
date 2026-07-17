import asyncio
import sys
import time
import json
import os
from dotenv import load_dotenv

sys.path.append(r"c:\Users\Shivam\OneDrive\Desktop\Project- Writon\backend")
load_dotenv()

from app.core.rag import _cpu_executor
from app.api.v1.drafting import _get_embedding_fn
from app.core.database import engine
from app.api.v1.search import classify_query, expand_query, _get_ts_config
from sqlalchemy import text
from openai import AsyncOpenAI

openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
llm_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=openrouter_key
)

SCENARIOS = [
    {
        "name": "SLP Criminal PMLA Bail (Twin Conditions)",
        "doc_type": "special_leave_petition",
        "subject_matter": "Criminal Law",
        "facts": "Special Leave Petition under Article 136 challenging the High Court's refusal to grant bail in a PMLA (money laundering) case due to the stringent twin conditions under Section 45."
    },
    {
        "name": "Writ Petition Art 32 Fundamental Rights",
        "doc_type": "writ_petition_civil",
        "subject_matter": "Constitutional Law",
        "facts": "Writ Petition under Article 32 seeking enforcement of fundamental rights under Article 21, challenging the constitutional validity of a central statute."
    },
    {
        "name": "SLP Civil Arbitration Section 11 Unstamped",
        "doc_type": "special_leave_petition",
        "subject_matter": "Arbitration Law",
        "facts": "Special Leave Petition arising out of an arbitration dispute regarding the appointment of an arbitrator under Section 11 of the Arbitration and Conciliation Act where the underlying agreement is unstamped."
    }
]

HC_SCENARIOS = [
    {
        "name": "Bail under Section 439 CrPC - Delhi High Court",
        "facts": (
            "The petitioner is seeking regular bail before the High Court of Delhi after being rejected "
            "by the Sessions Court in a case of cheating under Section 420 IPC. The charge sheet has already "
            "been filed. The petitioner has been in judicial custody for 6 months, and there is no flight risk."
        )
    },
    {
        "name": "Writ Petition (Article 226) Quashing FIR - Allahabad High Court",
        "facts": (
            "The petitioner is seeking to quash an FIR registered under Section 498A IPC before the Allahabad High Court, "
            "claiming the allegations are completely vague and inherently improbable. The FIR was lodged as a "
            "counter-blast to a divorce petition, falling under the Bhajan Lal guidelines for abuse of process."
        )
    },
    {
        "name": "Second Appeal (Section 100 CPC) - Madras High Court",
        "facts": (
            "A Second Appeal before the Madras High Court challenging concurrent findings of fact by the trial court "
            "and first appellate court in a property partition suit. The appellant argues there is a substantial "
            "question of law regarding the misinterpretation of a registered will and perversity in evidence appreciation."
        )
    }
]

async def llm_judge(query: str, results: list) -> int:
    """Uses LLM to grade if the top 5 results are relevant. Returns number of relevant results."""
    if not results:
        return 0
        
    prompt = f"""You are a strict Supreme Court judge evaluating a legal search engine.
    
    SCENARIO FACTS:
    {query}
    
    RETRIEVED PRECEDENTS / STATUTES:
    """
    
    for i, res in enumerate(results):
        text = res.get("text", "")[:800] # Take first 800 chars
        prompt += f"\n--- DOCUMENT {i+1} ---\n{text}\n"
        
    prompt += """
    EVALUATION TASK:
    For each of the documents above, decide if it is highly relevant to answering or supporting the scenario facts.
    Output ONLY a JSON array of 1s and 0s (1 = relevant, 0 = irrelevant).
    Example: [1, 0, 1, 1, 0]
    """
    
    try:
        resp = await llm_client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        content = resp.choices[0].message.content.strip()
        # Parse the JSON array
        if "[" in content and "]" in content:
            arr_str = content[content.find("["):content.find("]")+1]
            scores = json.loads(arr_str)
            return sum(scores)
    except Exception as e:
        print(f"LLM Judge error: {e}")
        return 0
    return 0


async def evaluate():
    print("==========================================")
    print("RUNNING AUTOMATED RAG EVALUATION")
    print("==========================================")
    
    total_latency = 0
    total_relevant = 0
    total_docs = 0
    
    embedding_fn = await _get_embedding_fn()
    loop = asyncio.get_event_loop()
    
    for i, s in enumerate(SCENARIOS):
        print(f"\nScenario {i+1}: {s['name']}")
        start_time = time.time()
        
        # 1. Query rewrite
        queries = await rewrite_queries(s['facts'], s['doc_type'], s['subject_matter'])
        combined_query = " ".join(queries[:3])
        
        # 2. Batch embeddings
        vecs = await loop.run_in_executor(_cpu_executor, embedding_fn, queries)
        query_vectors = {q: (v.tolist() if hasattr(v, "tolist") else list(v)) for q, v in zip(queries, vecs)}
        
        # 3. Hybrid Retrieval
        j_task = retrieve_judgment_chunks(engine, queries, None, context="citations", query_vectors=query_vectors)
        s_task = retrieve_statutes(engine, queries, None, context="citations", query_vectors=query_vectors)
        c_task = retrieve_statutes(engine, queries, None, coi_only=True, context="citations", query_vectors=query_vectors)
        
        j_res, s_res, c_res = await asyncio.gather(j_task, s_task, c_task)
        
        merged_statutes = []
        seen = set()
        for item in s_res + c_res:
            if item["id"] not in seen:
                merged_statutes.append(item)
                seen.add(item["id"])
                
        # 4. Reranking
        top_judgments = await rerank_candidates(combined_query, j_res[:25], top_k=5)
        top_statutes = await rerank_candidates(combined_query, merged_statutes[:25], top_k=5)
        
        latency = time.time() - start_time
        total_latency += latency
        
        # We evaluate the top judgments for precision
        relevant_count = await llm_judge(s['facts'], top_judgments)
        
        print(f"   - Latency:   {latency:.2f} seconds")
        print(f"   - Precision: {relevant_count}/{len(top_judgments)} relevant cases")
        
        total_relevant += relevant_count
        total_docs += len(top_judgments)
        
    
    avg_latency = total_latency / len(SCENARIOS)
    precision = (total_relevant / total_docs) * 100 if total_docs > 0 else 0
    
    print("\n==========================================")
    print("FINAL BENCHMARK METRICS")
    print("==========================================")
    print(f"Avg Retrieval Latency : {avg_latency:.2f}s")
    print(f"Precision@5           : {precision:.1f}%")
    print("==========================================\n")

async def _exec_raw(engine, sql: str, params: dict) -> list:
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        return result.fetchall()

async def evaluate_search():
    print("==========================================")
    print("RUNNING AUTOMATED /SEARCH EVALUATION")
    print("==========================================")
    
    total_latency = 0
    total_relevant = 0
    total_docs = 0
    
    embedding_fn = await _get_embedding_fn()
    loop = asyncio.get_event_loop()
    
    for i, s in enumerate(SCENARIOS):
        print(f"\nScenario {i+1}: {s['name']}")
        start_time = time.time()
        
        q = s['facts']
        expanded_q = expand_query(q)
        vec = await loop.run_in_executor(_cpu_executor, embedding_fn, expanded_q)
        query_vector = vec.tolist() if hasattr(vec, "tolist") else list(vec)
        
        ts_config = _get_ts_config(expanded_q)
        vector_sql = f"""
            SELECT id, case_number, petitioner, respondent, year, case_type,
                   COALESCE(summary, '') || ' ' || COALESCE(holding, '') || ' '
                       || SUBSTRING(full_text, 1, 1500) AS text,
                   embedding <-> :q_vec AS distance
            FROM judgments
            WHERE embedding IS NOT NULL
            ORDER BY distance
            LIMIT 30
        """
        keyword_sql = f"""
            SELECT id, case_number, petitioner, respondent, year, case_type,
                   COALESCE(summary, '') || ' ' || COALESCE(holding, '') || ' '
                       || SUBSTRING(full_text, 1, 1500) AS text,
                   ts_rank(search_vector,
                           to_tsquery('{ts_config}',
                               regexp_replace(
                                   websearch_to_tsquery('{ts_config}', :q)::text,
                                   ' & ', ' | ', 'g'
                               )
                           )
                          ) AS rank_score
            FROM judgments
            WHERE search_vector @@ websearch_to_tsquery('{ts_config}', :q)
            ORDER BY rank_score DESC
            LIMIT 30
        """
        vec_params = {"q_vec": str(query_vector)}
        kw_params = {"q": expanded_q}
        
        vec_rows, kw_rows = await asyncio.gather(
            _exec_raw(engine, vector_sql, vec_params),
            _exec_raw(engine, keyword_sql, kw_params)
        )
        
        sem_ranks = {r.id: idx + 1 for idx, r in enumerate(vec_rows)}
        kw_ranks  = {r.id: idx + 1 for idx, r in enumerate(kw_rows)}
        all_ids   = set(sem_ranks) | set(kw_ranks)
        row_data  = {r.id: r for r in list(vec_rows) + list(kw_rows)}
        
        results = []
        for jid in all_ids:
            rrf = 0.0
            if jid in sem_ranks: rrf += 1.0 / (60 + sem_ranks[jid])
            if jid in kw_ranks:  rrf += 2.0 / (60 + kw_ranks[jid])
            results.append({"score": rrf, "text": (row_data[jid].text or "")})
            
        results = sorted(results, key=lambda x: x["score"], reverse=True)[:5]
        
        latency = time.time() - start_time
        total_latency += latency
        
        relevant_count = await llm_judge(s['facts'], results)
        
        print(f"   - Latency:   {latency:.2f} seconds")
        print(f"   - Precision: {relevant_count}/{len(results)} relevant cases")
        
        total_relevant += relevant_count
        total_docs += len(results)
        
    avg_latency = total_latency / len(SCENARIOS)
    precision = (total_relevant / total_docs) * 100 if total_docs > 0 else 0
    
    print("\n==========================================")
    print("FINAL BENCHMARK METRICS FOR /SEARCH API")
    print("==========================================")
    print(f"Avg Retrieval Latency : {avg_latency:.2f}s")
    print(f"Precision@5           : {precision:.1f}%")
    print("==========================================\n")

async def evaluate_statutes():
    print("==========================================")
    print("RUNNING AUTOMATED STATUTES EVALUATION")
    print("==========================================")
    
    total_latency = 0
    total_relevant = 0
    total_docs = 0
    
    embedding_fn = await _get_embedding_fn()
    loop = asyncio.get_event_loop()
    
    for i, s in enumerate(SCENARIOS):
        print(f"\nScenario {i+1}: {s['name']}")
        start_time = time.time()
        
        q = s['facts']
        expanded_q = expand_query(q)
        vec = await loop.run_in_executor(_cpu_executor, embedding_fn, expanded_q)
        query_vector = vec.tolist() if hasattr(vec, "tolist") else list(vec)
        
        ts_config = _get_ts_config(expanded_q)
        
        vector_sql = f"""
            SELECT s.id, c.short_code, s.title, s.section_number, s.section_text AS text,
                   s.embedding <-> :q_vec AS distance
            FROM legal_code_sections s
            JOIN legal_codes c ON s.legal_code_id = c.id
            WHERE s.embedding IS NOT NULL
            ORDER BY distance
            LIMIT 30
        """
        keyword_sql = f"""
            SELECT s.id, c.short_code, s.title, s.section_number, s.section_text AS text,
                   ts_rank(s.search_vector,
                           to_tsquery('{ts_config}',
                               regexp_replace(
                                   websearch_to_tsquery('{ts_config}', :q)::text,
                                   ' & ', ' | ', 'g'
                               )
                           )
                          ) AS rank_score
            FROM legal_code_sections s
            JOIN legal_codes c ON s.legal_code_id = c.id
            WHERE s.search_vector @@ websearch_to_tsquery('{ts_config}', :q)
            ORDER BY rank_score DESC
            LIMIT 30
        """
        
        vec_params = {"q_vec": str(query_vector)}
        kw_params = {"q": expanded_q}
        
        vec_rows, kw_rows = await asyncio.gather(
            _exec_raw(engine, vector_sql, vec_params),
            _exec_raw(engine, keyword_sql, kw_params)
        )
        
        sem_ranks = {r.id: idx + 1 for idx, r in enumerate(vec_rows)}
        kw_ranks  = {r.id: idx + 1 for idx, r in enumerate(kw_rows)}
        all_ids   = set(sem_ranks) | set(kw_ranks)
        row_data  = {r.id: r for r in list(vec_rows) + list(kw_rows)}
        
        results = []
        for sid in all_ids:
            rrf = 0.0
            if sid in sem_ranks: rrf += 1.0 / (60 + sem_ranks[sid])
            if sid in kw_ranks:  rrf += 2.0 / (60 + kw_ranks[sid])
            results.append({"score": rrf, "text": (row_data[sid].text or "")[:800], "title": row_data[sid].title})
            
        from app.core.rag import rerank_candidates
        
        results = await rerank_candidates(expanded_q, results, top_k=5, use_cross_encoder=True)
        
        latency = time.time() - start_time
        total_latency += latency
        
        relevant_count = await llm_judge(s['facts'], results)
        
        print(f"   - Latency:   {latency:.2f} seconds")
        print(f"   - Precision: {relevant_count}/{len(results)} relevant statutes")
        print("   - Top Retrieved Statutes:")
        for r in results:
            print(f"      * {r['title']}")
        
        total_relevant += relevant_count
        total_docs += len(results)
        
    avg_latency = total_latency / len(SCENARIOS)
    precision = (total_relevant / total_docs) * 100 if total_docs > 0 else 0
    
    print("\n==========================================")
    print("FINAL BENCHMARK METRICS FOR STATUTES")
    print("==========================================")
    print(f"Avg Retrieval Latency : {avg_latency:.2f}s")
    print(f"Precision@5           : {precision:.1f}%")
    print("==========================================\n")

async def evaluate_high_court():
    print("==========================================")
    print("RUNNING AUTOMATED HIGH COURT EVALUATION")
    print("==========================================")
    
    total_latency = 0
    total_relevant = 0
    total_docs = 0
    
    for i, s in enumerate(HC_SCENARIOS):
        print(f"\nHC Scenario {i+1}: {s['name']}")
        start_time = time.time()
        
        from app.core.rag import rerank_candidates
        from app.api.v1.drafting import _get_embedding_fn
        from app.api.v1.search import expand_query, _get_ts_config
        embedding_fn = await _get_embedding_fn()
        loop = asyncio.get_event_loop()
        
        q = s['facts']
        expanded_q = expand_query(q)
        vec = await loop.run_in_executor(_cpu_executor, embedding_fn, expanded_q)
        query_vector = vec.tolist() if hasattr(vec, "tolist") else list(vec)
        
        ts_config = _get_ts_config(expanded_q)
        
        # We simulate the exact logic from search.py for hybrid judgments search
        vector_sql = f"""
            SELECT id, petitioner, respondent, year, case_type, case_number,
                   COALESCE(summary, '') || ' ' || COALESCE(holding, '') || ' ' || SUBSTRING(full_text, 1, 1500) AS text,
                   embedding <-> :q_vec AS distance
            FROM judgments
            WHERE embedding IS NOT NULL
            ORDER BY distance
            LIMIT 30
        """
        keyword_sql = f"""
            SELECT id, petitioner, respondent, year, case_type, case_number,
                   COALESCE(summary, '') || ' ' || COALESCE(holding, '') || ' ' || SUBSTRING(full_text, 1, 1500) AS text,
                   ts_rank(search_vector,
                           to_tsquery('{ts_config}',
                               regexp_replace(
                                   websearch_to_tsquery('{ts_config}', :q)::text,
                                   ' & ', ' | ', 'g'
                               )
                           )
                          ) AS rank_score
            FROM judgments
            WHERE search_vector @@ websearch_to_tsquery('{ts_config}', :q)
            ORDER BY rank_score DESC
            LIMIT 30
        """
        
        vec_params = {"q_vec": str(query_vector)}
        kw_params = {"q": expanded_q}
        
        vec_rows, kw_rows = await asyncio.gather(
            _exec_raw(engine, vector_sql, vec_params),
            _exec_raw(engine, keyword_sql, kw_params)
        )
        
        sem_ranks = {r.id: idx + 1 for idx, r in enumerate(vec_rows)}
        kw_ranks  = {r.id: idx + 1 for idx, r in enumerate(kw_rows)}
        all_ids   = set(sem_ranks) | set(kw_ranks)
        row_data  = {r.id: r for r in list(vec_rows) + list(kw_rows)}
        
        results = []
        for jid in all_ids:
            rrf = 0.0
            if jid in sem_ranks: rrf += 1.0 / (60 + sem_ranks[jid])
            if jid in kw_ranks:  rrf += 2.0 / (60 + kw_ranks[jid])
            
            row = row_data[jid]
            results.append({
                "id": jid, 
                "score": rrf, 
                "text": row.text, 
                "title": f"{row.petitioner} v. {row.respondent}",
                "year": row.year,
                "case_type": row.case_type
            })
            
        results = sorted(results, key=lambda x: x["score"], reverse=True)[:5]
        
        latency = time.time() - start_time
        total_latency += latency
        
        relevant_count = await llm_judge(s['facts'], results)
        
        print(f"   - Latency:   {latency:.2f} seconds")
        print(f"   - Precision: {relevant_count}/{len(results)} relevant judgments")
        print("   - Top Retrieved HC Judgments:")
        for r in results:
            print(f"      * {r['title']} ({r['year']})")
        
        total_relevant += relevant_count
        total_docs += len(results)
        
    avg_latency = total_latency / len(HC_SCENARIOS)
    precision = (total_relevant / total_docs) * 100 if total_docs > 0 else 0
    
    print("\n==========================================")
    print("FINAL BENCHMARK METRICS FOR HIGH COURT")
    print("==========================================")
    print(f"Avg Retrieval Latency : {avg_latency:.2f}s")
    print(f"Precision@5           : {precision:.1f}%")
    print("==========================================\n")

if __name__ == "__main__":
    asyncio.run(evaluate_high_court())
