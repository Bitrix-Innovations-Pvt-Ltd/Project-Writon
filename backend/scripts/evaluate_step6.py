"""
Step 6 (suggest-citations) benchmark: latency + LLM-judged precision.

Runs over HTTP against a RUNNING backend (default http://localhost:8000) so no
models are loaded in this process — safe on low-RAM machines. Variant knobs
are passed per-request via the whitelisted `rag_overrides` field:

  V0  baseline accuracy reference  (probes=20, judgment OR-fallback ON, 7 queries, gpt-4o-mini)
  V1  neutral latency opts         (probes=10, fallback OFF, 7 queries, gpt-4o-mini)
  V2  V1 + fewer queries           (5 queries)
  V3  V2 + fast rewrite model      (gemini-2.5-flash-lite)

Usage:
  python scripts/evaluate_step6.py             # all variants
  python scripts/evaluate_step6.py V0 V1      # subset
"""
import asyncio
import json
import os
import sys
import time
import urllib.request

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

API_BASE = os.getenv("STEP6_EVAL_API", "http://localhost:8000")
JUDGE_MODEL = "openai/gpt-4o-mini"

VARIANTS = {
    "V0": {"probes": 20, "judgment_or_fallback": True,  "num_queries": 7, "rewrite_model": "openai/gpt-4o-mini"},
    "V1": {"probes": 10, "judgment_or_fallback": False, "num_queries": 7, "rewrite_model": "openai/gpt-4o-mini"},
    "V2": {"probes": 10, "judgment_or_fallback": False, "num_queries": 5, "rewrite_model": "openai/gpt-4o-mini"},
    "V3": {"probes": 10, "judgment_or_fallback": False, "num_queries": 5, "rewrite_model": "google/gemini-2.5-flash-lite"},
}

SCENARIOS = [
    {
        "name": "Anticipatory bail 438 CrPC (cheating)",
        "doc_type": "Anticipatory Bail Application", "doc_type_key": "anticipatory_bail",
        "subject": "Criminal Law - Anticipatory Bail",
        "facts": "The applicant apprehends arrest in an FIR under Sections 420, 406 IPC arising out of a business payment dispute. No criminal antecedents, permanent resident, willing to cooperate with investigation. The dispute is essentially civil in nature.",
    },
    {
        "name": "Service law ACP arrears writ",
        "doc_type": "Writ Petition (Civil) under Article 226", "doc_type_key": "writ_petition_civil",
        "subject": "Service Law - Pay and Arrears",
        "facts": "A government teacher was granted ACP by a valid office order in 2019 but the department never implemented the pay upgradation and arrears remain unpaid despite representations. Seeking mandamus to implement the ACP order and release arrears with interest.",
    },
    {
        "name": "Regular bail 439 CrPC",
        "doc_type": "Bail Application", "doc_type_key": "bail_application",
        "subject": "Criminal Law - Bail",
        "facts": "The applicant seeks regular bail in a case under Section 420 IPC. Charge sheet already filed, 6 months in judicial custody, no flight risk, investigation complete, co-accused already granted bail on parity.",
    },
    {
        "name": "Quash FIR 482 (498A counterblast)",
        "doc_type": "Writ Petition (Criminal) - Quashing of FIR", "doc_type_key": "writ_petition_criminal",
        "subject": "Criminal Law - Quashing of FIR",
        "facts": "Petitioner seeks quashing of an FIR under Section 498A IPC claiming the allegations are vague and inherently improbable, lodged as a counter-blast to a pending divorce petition, squarely covered by the Bhajan Lal guidelines on abuse of process.",
    },
    {
        "name": "Cheque dishonour 138 NI Act",
        "doc_type": "Criminal Complaint - Cheque Dishonour", "doc_type_key": "criminal_appeal",
        "subject": "Cheque Dishonour - Negotiable Instruments",
        "facts": "A cheque of Rs 12 lakh issued towards discharge of a business debt was dishonoured for insufficient funds. Statutory notice under Section 138 Negotiable Instruments Act was served within 30 days; the drawer failed to pay within 15 days. Complaint against the drawer company and its directors.",
    },
    {
        "name": "SLP arbitration s.11 unstamped",
        "doc_type": "Special Leave Petition (Civil)", "doc_type_key": "civil_appeal",
        "subject": "Arbitration Law",
        "facts": "SLP arising from appointment of an arbitrator under Section 11 of the Arbitration and Conciliation Act where the underlying agreement is unstamped, raising the question whether an unstamped arbitration agreement is enforceable.",
    },
    {
        "name": "PMLA s.45 twin conditions bail",
        "doc_type": "Bail Application under PMLA", "doc_type_key": "bail_application",
        "subject": "Criminal Law - PMLA Money Laundering",
        "facts": "The applicant, arrested by the ED in an ECIR under Sections 3 and 4 of the Prevention of Money Laundering Act, seeks bail contending the twin conditions of Section 45 PMLA are satisfied: no direct role in layering of proceeds, 8 months custody, trial yet to commence.",
    },
    {
        "name": "Consumer builder possession delay",
        "doc_type": "Consumer Complaint", "doc_type_key": "writ_petition_civil",
        "subject": "Consumer Protection - Real Estate",
        "facts": "Homebuyer paid 90% of consideration for a flat promised in 2021; possession is delayed by over 3 years without justification. Seeking refund with interest and compensation for deficiency of service against the builder.",
    },
]


def _post_suggest(scenario: dict, overrides: dict, timeout: int = 300) -> tuple:
    body = json.dumps({
        "document_type": scenario["doc_type"],
        "document_type_key": scenario["doc_type_key"],
        "subject_matter": scenario["subject"],
        "facts_of_case": scenario["facts"],
        "case_description": "", "grounds": "", "mandatory_paragraphs": "",
        "rag_overrides": {**overrides, "disable_cache": True},
    }).encode()
    req = urllib.request.Request(
        f"{API_BASE}/api/v1/drafts/suggest-citations",
        data=body, headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    return data, time.time() - t0


async def llm_judge(client, facts: str, items: list, kind: str) -> list:
    """Return list of 0/1 relevance for each item (top-5 evaluated)."""
    if not items:
        return []
    listing = ""
    for i, r in enumerate(items):
        title = r.get("title", "")
        snippet = (r.get("text") or "")[:400]
        listing += f"\n--- ITEM {i + 1}: {title} ---\n{snippet}\n"
    prompt = (
        "You are a strict Indian Supreme Court research clerk evaluating a legal search engine.\n\n"
        f"CASE FACTS:\n{facts}\n\n"
        f"RETRIEVED {kind.upper()}:\n{listing}\n\n"
        "For each item, decide if it would genuinely support drafting this document "
        "(directly applicable provision / precedent). Output ONLY a JSON object "
        '{"scores": [1,0,...]} with one 0/1 per item, in order.'
    )
    try:
        resp = await client.chat.completions.create(
            model=JUDGE_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        scores = json.loads(resp.choices[0].message.content).get("scores", [])
        return [int(bool(s)) for s in scores][: len(items)]
    except Exception as e:
        print(f"   [judge error: {e}]")
        return [0] * len(items)


async def run_variant(vname: str, cfg: dict, judge_client) -> dict:
    loop = asyncio.get_event_loop()
    totals = []
    pj_hits = pj_n = ps_hits = ps_n = 0

    for s in SCENARIOS:
        try:
            data, elapsed = await loop.run_in_executor(None, _post_suggest, s, cfg)
        except Exception as e:
            print(f"   {s['name'][:42]:<42} REQUEST FAILED: {e}")
            continue
        totals.append(elapsed)

        top_j = (data.get("judgments") or [])[:5]
        top_s = (data.get("statutes") or [])[:5]
        j_scores, s_scores = await asyncio.gather(
            llm_judge(judge_client, s["facts"], top_j, "precedents"),
            llm_judge(judge_client, s["facts"], top_s, "statute sections"),
        )
        pj_hits += sum(j_scores); pj_n += len(j_scores)
        ps_hits += sum(s_scores); ps_n += len(s_scores)
        print(f"   {s['name'][:42]:<42} {elapsed:5.1f}s  "
              f"J:{sum(j_scores)}/{len(j_scores)}  S:{sum(s_scores)}/{len(s_scores)}")

    n = max(len(totals), 1)
    return {
        "variant": vname, **cfg,
        "avg_total": sum(totals) / n,
        "p5_judgments": 100.0 * pj_hits / pj_n if pj_n else 0.0,
        "p5_statutes": 100.0 * ps_hits / ps_n if ps_n else 0.0,
        "completed": len(totals),
    }


async def main():
    wanted = sys.argv[1:] or list(VARIANTS)
    from openai import AsyncOpenAI
    judge_client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )

    # Warm-up: one un-timed request so server-side model load + Neon page-cache
    # warm-up don't penalise the first timed variant.
    print(f"Target: {API_BASE} — warming up (server models + DB cache)...")
    _, warm_t = _post_suggest(SCENARIOS[0], VARIANTS[wanted[0]], timeout=600)
    print(f"Warm-up request: {warm_t:.1f}s")

    results = []
    for vname in wanted:
        print(f"\n=== {vname}: {VARIANTS[vname]} ===")
        results.append(await run_variant(vname, VARIANTS[vname], judge_client))

    print("\n" + "=" * 78)
    print(f"{'variant':<8}{'avg total':>11}{'P@5 judgments':>15}{'P@5 statutes':>14}{'ok':>5}")
    for r in results:
        print(f"{r['variant']:<8}{r['avg_total']:>10.1f}s{r['p5_judgments']:>14.1f}%"
              f"{r['p5_statutes']:>13.1f}%{r['completed']:>5}")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
