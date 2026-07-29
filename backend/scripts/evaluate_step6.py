"""
Step 6 (suggest-citations) benchmark: latency + accuracy.

Runs over HTTP against a RUNNING backend (default http://localhost:8000) so no
models are loaded in this process — safe on low-RAM machines. Variant knobs
are passed per-request via the whitelisted `rag_overrides` field.

Metrics per variant:
  gold R@8   — deterministic recall of must-cite statute sections in top-8.
               Each gold item is a group of acceptable alternatives
               (e.g. S.438 CrPC OR S.482 BNSS); the group counts as hit if
               any alternative surfaces. This is the primary statute metric.
  case hit@5 — share of scenarios where at least one landmark case (matched
               by distinctive name substring) appears in the top-5 judgments.
  P@5 J / S  — LLM-judged precision@5 (secondary; comparable to old runs).

Usage:
  python scripts/evaluate_step6.py                    # all variants
  python scripts/evaluate_step6.py V4                 # subset
  STEP6_EVAL_SCENARIOS=5 python scripts/evaluate_step6.py V4   # first N scenarios
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
JUDGE_MODEL = os.getenv("STEP6_JUDGE_MODEL", "openai/gpt-4o-mini")

# NOTE: every variant states llm_rerank explicitly. Omitting it makes the
# variant inherit rag.LLM_RERANK, so flipping that default would silently
# turn the cross-encoder baselines into LLM-rerank runs and invalidate the
# comparison without any visible change to this file.
VARIANTS = {
    # Historical reference points (2026-07-25 benchmark)
    "V0": {"probes": 20, "judgment_or_fallback": True,  "num_queries": 7, "rewrite_model": "openai/gpt-4o-mini",
           "llm_rerank": False},
    "V2": {"probes": 10, "judgment_or_fallback": False, "num_queries": 5, "rewrite_model": "openai/gpt-4o-mini",
           "llm_rerank": False},
    # Cross-encoder baseline (was production until 2026-07-29)
    "V4": {"probes": 20, "judgment_or_fallback": True,  "num_queries": 5, "rewrite_model": "openai/gpt-4o-mini",
           "llm_rerank": False},
    # Current production config: V4 + LLM listwise rerank
    "V5": {"probes": 20, "judgment_or_fallback": True,  "num_queries": 5, "rewrite_model": "openai/gpt-4o-mini",
           "llm_rerank": True},
    # Accuracy of V5 at lower latency: the fan-out drives retrieval cost
    # linearly, so pay for the LLM reranker out of the retrieval budget.
    "V6": {"probes": 20, "judgment_or_fallback": True,  "num_queries": 3, "rewrite_model": "openai/gpt-4o-mini",
           "llm_rerank": True},
    # Same trade without the LLM reranker, to isolate the fan-out's own effect
    "V7": {"probes": 20, "judgment_or_fallback": True,  "num_queries": 3, "rewrite_model": "openai/gpt-4o-mini",
           "llm_rerank": False},
    # V5 with the case_type filter off entirely. The filter hides ~50% of the
    # corpus even after the empty-string fix, and its labels are demonstrably
    # wrong in places (Bhajan Lal is filed as "Civil Appeal"), so whether it
    # helps precedent recall at all is an open question worth measuring.
    "V8": {"probes": 20, "judgment_or_fallback": True,  "num_queries": 5, "rewrite_model": "openai/gpt-4o-mini",
           "llm_rerank": True, "case_type_filter": False},
}

# gold: list of groups; each group is a list of acceptable ("CODE", "section") alternatives.
# cases: list of distinctive lowercase substrings of landmark case names (any-of).
SCENARIOS = [
    {
        "name": "Anticipatory bail 438 CrPC (cheating)",
        "doc_type": "Anticipatory Bail Application", "doc_type_key": "anticipatory_bail",
        "subject": "Criminal Law - Anticipatory Bail",
        "facts": "The applicant apprehends arrest in an FIR under Sections 420, 406 IPC arising out of a business payment dispute. No criminal antecedents, permanent resident, willing to cooperate with investigation. The dispute is essentially civil in nature.",
        "gold": [[("CrPC", "438"), ("BNSS", "482")], [("IPC", "420"), ("BNS", "318")], [("IPC", "406"), ("BNS", "316")]],
        "cases": ["sibbia", "sushila aggarwal", "siddharam"],
    },
    {
        "name": "Regular bail 439 CrPC (parity)",
        "doc_type": "Bail Application", "doc_type_key": "bail_application",
        "subject": "Criminal Law - Bail",
        "facts": "The applicant seeks regular bail in a case under Section 420 IPC. Charge sheet already filed, 6 months in judicial custody, no flight risk, investigation complete, co-accused already granted bail on parity.",
        "gold": [[("CrPC", "439"), ("BNSS", "483")], [("CrPC", "437"), ("BNSS", "480")], [("IPC", "420"), ("BNS", "318")]],
        "cases": ["dataram", "prasanta kumar sarkar", "sanjay chandra"],
    },
    {
        "name": "NDPS s.37 commercial quantity bail",
        "doc_type": "Bail Application", "doc_type_key": "bail_application",
        "subject": "Criminal Law - NDPS Narcotics",
        "facts": "The applicant was arrested with alleged commercial quantity of heroin under Sections 21 and 29 of the NDPS Act. Bail is sought contending non-compliance of Section 42 and 50 NDPS Act safeguards and that the twin conditions of Section 37 NDPS Act stand satisfied after 14 months of custody with trial not commenced.",
        "gold": [[("NDPS", "37")], [("NDPS", "21")], [("NDPS", "50"), ("NDPS", "42")], [("CrPC", "439"), ("BNSS", "483")]],
        "cases": ["tofan singh", "mohd. muslim", "mohd muslim", "thamisharasi"],
    },
    {
        "name": "PMLA s.45 twin conditions bail",
        "doc_type": "Bail Application under PMLA", "doc_type_key": "bail_application",
        "subject": "Criminal Law - PMLA Money Laundering",
        "facts": "The applicant, arrested by the ED in an ECIR under Sections 3 and 4 of the Prevention of Money Laundering Act, seeks bail contending the twin conditions of Section 45 PMLA are satisfied: no direct role in layering of proceeds, 8 months custody, trial yet to commence.",
        "gold": [[("PMLA", "45")], [("PMLA", "3")], [("PMLA", "4")]],
        "cases": ["vijay madanlal", "pankaj bansal", "chidambaram"],
    },
    {
        "name": "POCSO discharge (false implication)",
        "doc_type": "Discharge Application", "doc_type_key": "writ_petition_criminal",
        "subject": "Criminal Law - POCSO",
        "facts": "The accused seeks discharge in a POCSO case under Sections 8 and 12 POCSO Act, contending the allegations arise from a property dispute between families, the victim's statement contains material contradictions, and no prima facie case is made out at the charge stage.",
        "gold": [[("POCSO", "8")], [("POCSO", "29")], [("CrPC", "227"), ("BNSS", "250")]],
        "cases": ["prafulla kumar samal", "sajjan kumar", "alakh alok"],
    },
    {
        "name": "Quash FIR 482 (498A counterblast)",
        "doc_type": "Writ Petition (Criminal) - Quashing of FIR", "doc_type_key": "writ_petition_criminal",
        "subject": "Criminal Law - Quashing of FIR",
        "facts": "Petitioner seeks quashing of an FIR under Section 498A IPC claiming the allegations are vague and inherently improbable, lodged as a counter-blast to a pending divorce petition, squarely covered by the Bhajan Lal guidelines on abuse of process.",
        "gold": [[("CrPC", "482"), ("BNSS", "528")], [("IPC", "498A"), ("BNS", "85")]],
        "cases": ["bhajan lal", "preeti gupta", "arnesh kumar"],
    },
    {
        "name": "Discharge 227 CrPC (no sufficient ground)",
        "doc_type": "Discharge Application", "doc_type_key": "writ_petition_criminal",
        "subject": "Criminal Law - Discharge at Charge Stage",
        "facts": "The accused seeks discharge under Section 227 CrPC in a sessions triable case, contending that the material in the charge sheet, taken at its highest, does not disclose the ingredients of the offence and the court should sift the evidence to find no sufficient ground to proceed.",
        "gold": [[("CrPC", "227"), ("BNSS", "250")], [("CrPC", "228"), ("BNSS", "251")]],
        "cases": ["prafulla kumar samal", "dilawar balu", "muniswamy"],
    },
    {
        "name": "Criminal appeal (perverse conviction)",
        "doc_type": "Criminal Appeal", "doc_type_key": "criminal_appeal",
        "subject": "Criminal Law - Appeal against Conviction",
        "facts": "Appeal against conviction under Section 302 IPC based solely on circumstantial evidence. The chain of circumstances is incomplete, the recovery is doubtful, and the trial court reversed the burden of proof. The appellant contends the prosecution failed to prove guilt beyond reasonable doubt.",
        "gold": [[("IPC", "302"), ("BNS", "103")], [("CrPC", "374"), ("BNSS", "415")], [("IEA", "106"), ("BSA", "109")]],
        "cases": ["sharad birdhichand", "hanumant"],
    },
    {
        "name": "Service ACP arrears writ",
        "doc_type": "Writ Petition (Civil) under Article 226", "doc_type_key": "writ_petition_civil",
        "subject": "Service Law - Pay and Arrears",
        "facts": "A government teacher was granted ACP by a valid office order in 2019 but the department never implemented the pay upgradation and arrears remain unpaid despite representations. Seeking mandamus to implement the ACP order and release arrears with interest.",
        "gold": [[("COI", "226")], [("COI", "14")], [("COI", "16")]],
        "cases": ["amar nath goyal", "shyam babu verma"],
    },
    {
        "name": "Pension withheld writ",
        "doc_type": "Writ Petition (Civil) under Article 226", "doc_type_key": "writ_petition_civil",
        "subject": "Service Law - Pension and Retiral Dues",
        "facts": "A retired state employee's pension and gratuity have been withheld for three years without any departmental proceedings, citing an audit objection. Seeking mandamus for release of pension, gratuity and arrears with interest, contending pension is a vested right and not a bounty.",
        "gold": [[("COI", "226")], [("COI", "300A"), ("COI", "300-A"), ("COI", "21")]],
        "cases": ["nakara", "deokinandan", "jitendra kumar srivastava"],
    },
    {
        "name": "Dismissal without inquiry (Art 311)",
        "doc_type": "Writ Petition (Civil) under Article 226", "doc_type_key": "writ_petition_civil",
        "subject": "Service Law - Dismissal and Reinstatement",
        "facts": "A permanent state government employee was dismissed from service without any departmental inquiry or show cause notice, on allegations of misconduct. Seeking quashing of the dismissal order as violative of Article 311(2) and principles of natural justice, with reinstatement and back wages.",
        "gold": [[("COI", "311")], [("COI", "14")], [("COI", "16")]],
        "cases": ["tulsiram patel", "maneka gandhi", "b.c. chaturvedi"],
    },
    {
        "name": "Cheque dishonour 138 NI complaint",
        "doc_type": "Criminal Complaint - Cheque Dishonour", "doc_type_key": "criminal_appeal",
        "subject": "Cheque Dishonour - Negotiable Instruments",
        "facts": "A cheque of Rs 12 lakh issued towards discharge of a business debt was dishonoured for insufficient funds. Statutory notice under Section 138 Negotiable Instruments Act was served within 30 days; the drawer failed to pay within 15 days. Complaint against the drawer company and its directors.",
        "gold": [[("NI", "138")], [("NI", "141")], [("NI", "139")]],
        "cases": ["dashrath rupsingh", "rangappa", "kusum ingots"],
    },
    {
        "name": "SLP arbitration s.11 unstamped",
        "doc_type": "Special Leave Petition (Civil)", "doc_type_key": "civil_appeal",
        "subject": "Arbitration Law",
        "facts": "SLP arising from appointment of an arbitrator under Section 11 of the Arbitration and Conciliation Act where the underlying agreement is unstamped, raising the question whether an unstamped arbitration agreement is enforceable.",
        "gold": [[("ARBITRATION", "11")], [("ARBITRATION", "7"), ("ARBITRATION", "8")]],
        "cases": ["nn global", "n n global", "interplay", "vidya drolia"],
    },
    {
        "name": "Arbitration s.34 award challenge",
        "doc_type": "Petition under Section 34 Arbitration Act", "doc_type_key": "civil_appeal",
        "subject": "Arbitration Law - Setting Aside Award",
        "facts": "Challenge to an arbitral award under Section 34 of the Arbitration and Conciliation Act on the ground of patent illegality: the arbitrator rewrote the contract, ignored vital evidence, and awarded damages contrary to the agreed limitation of liability clause.",
        "gold": [[("ARBITRATION", "34")], [("ARBITRATION", "37")]],
        "cases": ["ssangyong", "associate builders"],
    },
    {
        "name": "IBC s.7 financial creditor CIRP",
        "doc_type": "Company Petition under IBC", "doc_type_key": "civil_appeal",
        "subject": "Insolvency and Bankruptcy",
        "facts": "A financial creditor bank seeks initiation of CIRP against the corporate debtor under Section 7 IBC for default of Rs 45 crore term loan. The debtor disputes the date of default and claims the application is barred by limitation.",
        "gold": [[("IBC", "7")], [("IBC", "14")], [("LIMITATION", "18"), ("LIMITATION", "137")]],
        "cases": ["innoventive", "swiss ribbons", "dena bank"],
    },
    {
        "name": "IBC s.9 pre-existing dispute",
        "doc_type": "Company Petition under IBC", "doc_type_key": "civil_appeal",
        "subject": "Insolvency and Bankruptcy - Operational Creditor",
        "facts": "An operational creditor issued a Section 8 IBC demand notice for unpaid invoices of Rs 2.1 crore; the corporate debtor replied disputing quality of goods supplied. The creditor has filed a Section 9 application contending the dispute is moonshine and raised for the first time after the notice.",
        "gold": [[("IBC", "9")], [("IBC", "8")]],
        "cases": ["mobilox", "kirusa"],
    },
    {
        "name": "Consumer builder possession delay",
        "doc_type": "Consumer Complaint", "doc_type_key": "writ_petition_civil",
        "subject": "Consumer Protection - Real Estate",
        "facts": "Homebuyer paid 90% of consideration for a flat promised in 2021; possession is delayed by over 3 years without justification. Seeking refund with interest and compensation for deficiency of service against the builder.",
        "gold": [[("CPA", "2")], [("RERA", "18")], [("CPA", "35"), ("CPA", "34")]],
        "cases": ["ireo grace", "pioneer urban", "govindan raghavan"],
    },
    {
        "name": "Divorce cruelty + maintenance",
        "doc_type": "Divorce Petition", "doc_type_key": "writ_petition_civil",
        "subject": "Matrimonial - Divorce and Maintenance",
        "facts": "Husband seeks divorce on the ground of cruelty under the Hindu Marriage Act citing sustained mental cruelty and false criminal complaints by the wife; the wife has claimed interim maintenance for herself and the minor child.",
        "gold": [[("HMA", "13")], [("CrPC", "125"), ("BNSS", "144")], [("HMA", "24")]],
        "cases": ["samar ghosh", "rajnesh"],
    },
    {
        "name": "Child custody (welfare principle)",
        "doc_type": "Custody Petition", "doc_type_key": "writ_petition_civil",
        "subject": "Family Law - Child Custody",
        "facts": "Mother seeks custody of a 7-year-old child from the father, contending the welfare of the minor is paramount, the child has been in her primary care since birth, and the father's transferable job cannot provide a stable environment.",
        "gold": [[("GWA", "17"), ("GWA", "25")], [("HMGA", "6")]],
        "cases": ["gita hariharan", "githa hariharan", "nil ratan", "gaurav nagpal"],
    },
    {
        "name": "Transfer petition matrimonial",
        "doc_type": "Transfer Petition", "doc_type_key": "writ_petition",
        "subject": "Matrimonial - Transfer of Proceedings",
        "facts": "Wife seeks transfer of the divorce petition filed by the husband at Delhi to the family court at Lucknow where she resides with the minor child, citing financial hardship, lack of independent income, and the child's care making travel impossible.",
        "gold": [[("CPC", "25")], [("CrPC", "406")]],
        "cases": ["anita kushwaha", "surinder kaur", "sumita singh"],
    },
    {
        "name": "SARFAESI s.17 possession challenge",
        "doc_type": "Securitisation Application before DRT", "doc_type_key": "writ_petition_civil",
        "subject": "Banking - SARFAESI Debt Recovery",
        "facts": "The borrower challenges possession taken by the bank under Section 13(4) SARFAESI without deciding objections filed under Section 13(3A). Application under Section 17 SARFAESI before the DRT seeking restoration of possession and setting aside of the measures.",
        "gold": [[("SARFAESI", "17")], [("SARFAESI", "13")]],
        "cases": ["mardia chemicals", "satyawati tondon"],
    },
    {
        "name": "MACT fatal accident compensation",
        "doc_type": "Motor Accident Claim Petition", "doc_type_key": "writ_petition_civil",
        "subject": "Motor Accident Compensation",
        "facts": "Claim by the widow and two minor children of a 34-year-old salaried employee who died in a road accident caused by rash and negligent driving of a truck. Claim under Section 166 Motor Vehicles Act with future prospects, loss of dependency computed by the multiplier method, and conventional heads.",
        "gold": [[("MV", "166")], [("MV", "168"), ("MV", "173")]],
        "cases": ["pranay sethi", "sarla verma"],
    },
    {
        "name": "Specific performance of sale agreement",
        "doc_type": "Civil Suit - Specific Performance", "doc_type_key": "writ_petition_civil",
        "subject": "Civil - Specific Performance of Contract",
        "facts": "Suit for specific performance of a registered agreement to sell immovable property. The plaintiff has always been ready and willing to perform, paid 60% of consideration, and the defendant is attempting to sell to a third party at a higher price.",
        "gold": [[("SRA", "10")], [("SRA", "16")], [("TPA", "54"), ("SRA", "20")]],
        "cases": ["saradamani", "kamal kumar", "katta sujatha"],
    },
    {
        "name": "Second appeal substantial question",
        "doc_type": "Second Appeal", "doc_type_key": "civil_appeal",
        "subject": "Civil - Second Appeal",
        "facts": "Second appeal under Section 100 CPC against concurrent findings in a title suit, contending the courts below misconstrued a registered partition deed and ignored admissible documentary evidence, raising a substantial question of law.",
        "gold": [[("CPC", "100")], [("CPC", "96")]],
        "cases": ["panchugopal", "santosh hazari", "hero vinoth"],
    },
    {
        "name": "Income tax reassessment writ",
        "doc_type": "Writ Petition (Civil) under Article 226", "doc_type_key": "writ_petition_civil",
        "subject": "Tax - Income Tax Reassessment",
        "facts": "Challenge to a reassessment notice issued under Section 148 of the Income-tax Act beyond four years without any fresh tangible material, based on mere change of opinion, and without disposing of the assessee's objections.",
        "gold": [[("ITAX", "148"), ("ITAX", "147")], [("COI", "226")]],
        "cases": ["gkn driveshafts", "ashish agarwal", "kelvinator"],
    },
]

_N = os.getenv("STEP6_EVAL_SCENARIOS")
if _N:
    SCENARIOS = SCENARIOS[: int(_N)]


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


def gold_recall(statutes: list, gold: list, k: int = 8) -> tuple:
    """(#gold groups satisfied in top-k, #groups). Matches on (short_code, section_number)."""
    got = {(s.get("short_code", ""), str(s.get("section_number", ""))) for s in statutes[:k]}
    hits = sum(
        1 for group in gold
        if any((code, sec) in got for code, sec in group)
    )
    return hits, len(gold)


def case_hit(judgments: list, case_keys: list, k: int = 5) -> int:
    titles = " || ".join((j.get("title") or "").lower() for j in judgments[:k])
    return 1 if any(key in titles for key in case_keys) else 0


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
    gr_hits = gr_n = 0
    ch_hits = ch_n = 0
    pj_hits = pj_n = ps_hits = ps_n = 0

    for s in SCENARIOS:
        try:
            data, elapsed = await loop.run_in_executor(None, _post_suggest, s, cfg)
        except Exception as e:
            print(f"   {s['name'][:40]:<40} REQUEST FAILED: {e}")
            continue
        totals.append(elapsed)

        top_j = (data.get("judgments") or [])
        top_s = (data.get("statutes") or [])

        gh, gn = gold_recall(top_s, s.get("gold", []))
        gr_hits += gh; gr_n += gn
        ch = case_hit(top_j, s.get("cases", []))
        ch_hits += ch; ch_n += 1

        j_scores, s_scores = await asyncio.gather(
            llm_judge(judge_client, s["facts"], top_j[:5], "precedents"),
            llm_judge(judge_client, s["facts"], top_s[:5], "statute sections"),
        )
        pj_hits += sum(j_scores); pj_n += len(j_scores)
        ps_hits += sum(s_scores); ps_n += len(s_scores)
        print(f"   {s['name'][:40]:<40} {elapsed:5.1f}s  gold:{gh}/{gn}  case:{'Y' if ch else 'n'}  "
              f"J:{sum(j_scores)}/{len(j_scores)}  S:{sum(s_scores)}/{len(s_scores)}")

    n = max(len(totals), 1)
    return {
        "variant": vname,
        "avg_total": sum(totals) / n,
        "gold_recall": 100.0 * gr_hits / gr_n if gr_n else 0.0,
        "case_hit": 100.0 * ch_hits / ch_n if ch_n else 0.0,
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

    print(f"Target: {API_BASE} — warming up (server models + DB cache)...")
    _, warm_t = _post_suggest(SCENARIOS[0], VARIANTS[wanted[0]], timeout=600)
    print(f"Warm-up request: {warm_t:.1f}s")

    results = []
    for vname in wanted:
        print(f"\n=== {vname}: {VARIANTS[vname]} ===")
        results.append(await run_variant(vname, VARIANTS[vname], judge_client))

    print("\n" + "=" * 95)
    print(f"{'variant':<8}{'avg total':>10}{'gold R@8':>10}{'case hit':>10}{'P@5 J':>8}{'P@5 S':>8}{'ok':>4}")
    for r in results:
        print(f"{r['variant']:<8}{r['avg_total']:>9.1f}s{r['gold_recall']:>9.1f}%{r['case_hit']:>9.1f}%"
              f"{r['p5_judgments']:>7.1f}%{r['p5_statutes']:>7.1f}%{r['completed']:>4}")
    print("=" * 95)


if __name__ == "__main__":
    asyncio.run(main())
