"""
Seeds the DB-driven retrieval configuration that replaces rag.py's hardcoded
maps and the ~440-line doc-type hint if/elif chain.

Tables:
  retrieval_config(key, value jsonb)   — small config maps (case types, domains,
                                         COI keywords, generic hint template, ...)
  doc_type_retrieval_hints             — one row per branch of the old hint chain,
                                         matched by word-boundary keywords in
                                         priority order (first match wins)
  legal_codes.aliases                  — act-name variants for exact-section
                                         extraction (replaces _ACT_NAME_TO_SHORT_CODE)

Matching semantics (resolver in app/core/rag.py):
  haystack = document_type_key.replace('_',' ') + ' ' + doc_type display, lowercased
  A row matches when ALL of keywords_all AND (ANY of keywords_any, if set) appear
  as whole words in the haystack, AND (ANY of subject_keywords_any, if set)
  appears as a whole word in subject_matter. Word-boundary matching everywhere —
  the bare-substring checks this replaces caused the appliCATion/disCHARGE
  hijack bugs.

Idempotent: wipes and reseeds both tables. Run after any hint edit:
  python scripts/seed_retrieval_config.py
"""
import json
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

# ---------------------------------------------------------------------------
# Small config maps (ported verbatim from app/core/rag.py)
# ---------------------------------------------------------------------------
RETRIEVAL_CONFIG = {
    "doc_type_case_types": {
        "writ_petition_civil":    ["Writ Petition", "Civil Appeal", "Special Leave Petition", "Transfer Petition", "Petition", "Review Petition", "Curative Petition", "Original Suit", "Appeal", "Slp"],
        "writ_petition_criminal": ["Writ Petition", "Criminal Appeal", "Special Leave Petition", "Transfer Petition", "Petition", "Review Petition", "Curative Petition", "Appeal", "Slp"],
        "bail_application":       ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"],
        "anticipatory_bail":      ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"],
        "civil_appeal":           ["Civil Appeal", "Special Leave Petition", "Transfer Petition", "Appeal", "Review Petition", "Curative Petition", "Slp"],
        "criminal_appeal":        ["Criminal Appeal", "Special Leave Petition", "Transfer Petition", "Appeal", "Review Petition", "Curative Petition", "Slp"],
        "writ_petition":          ["Writ Petition", "Civil Appeal", "Criminal Appeal", "Special Leave Petition", "Transfer Petition", "Petition", "Review Petition", "Curative Petition", "Original Suit", "Appeal", "Slp"],
    },
    "doc_type_domains": {
        "writ_petition_civil":    ["civil", "constitutional"],
        "writ_petition_criminal": ["criminal", "constitutional"],
        "bail_application":       ["criminal"],
        "anticipatory_bail":      ["criminal"],
        "civil_appeal":           ["civil", "constitutional"],
        "criminal_appeal":        ["criminal", "constitutional"],
        "writ_petition":          ["civil", "criminal", "constitutional"],
    },
    "subject_needs_coi": [
        "fundamental right", "article 14", "article 16", "article 19", "article 21",
        "article 226", "article 32", "constitutional", "equality", "liberty",
        "discrimination", "natural justice", "article 311", "article 300",
    ],
    "service_law_keywords": [
        "service", "employment", "pay", "salary", "allowance", "promotion",
        "acp", "assured career progression", "increment", "pension", "arrear",
        "seniority", "transfer", "posting", "disciplinary", "dismissal",
        "termination", "reinstatement", "back wage", "grade pay", "pay scale",
        "pay fixation", "pay revision", "dpc", "department", "government employee",
    ],
    "subject_case_type_overrides": [
        ["service law",   ["Civil Appeal", "Writ Petition", "Special Leave Petition", "Petition", "Appeal", "Slp"]],
        ["property",      ["Civil Appeal", "Writ Petition", "Special Leave Petition", "Petition", "Original Suit", "Appeal", "Slp"]],
        ["land",          ["Civil Appeal", "Writ Petition", "Special Leave Petition", "Petition", "Original Suit", "Appeal", "Slp"]],
        ["labour",        ["Civil Appeal", "Writ Petition", "Special Leave Petition", "Petition", "Appeal", "Slp"]],
        ["employment",    ["Civil Appeal", "Writ Petition", "Special Leave Petition", "Petition", "Appeal", "Slp"]],
        ["cheque",        ["Criminal Appeal", "Civil Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]],
        ["matrimonial",   ["Civil Appeal", "Criminal Appeal", "Special Leave Petition", "Transfer Petition", "Petition", "Appeal", "Slp"]],
        ["divorce",       ["Civil Appeal", "Special Leave Petition", "Transfer Petition", "Petition", "Appeal", "Slp"]],
        ["custody",       ["Civil Appeal", "Criminal Appeal", "Special Leave Petition", "Transfer Petition", "Petition", "Appeal", "Slp"]],
        ["company",       ["Civil Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]],
        ["insolvency",    ["Civil Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]],
        ["ibc",           ["Civil Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]],
        ["tax",           ["Civil Appeal", "Writ Petition", "Special Leave Petition", "Petition", "Appeal", "Slp"]],
        ["consumer",      ["Civil Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]],
        ["rape",          ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]],
        ["murder",        ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]],
        ["dowry",         ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]],
        ["corruption",    ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]],
        ["ndps",          ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]],
        ["pocso",         ["Criminal Appeal", "Special Leave Petition", "Petition", "Appeal", "Slp"]],
    ],
    # Words that must never drive the judgment OR-fallback. Generic legal
    # vocabulary ORed across the corpus matched 98.7% of all judgments and cost
    # ~47s per query; only distinctive party names should widen the search.
    "case_name_stopwords": [
        "state", "states", "union", "india", "indian", "government", "govt",
        "court", "courts", "supreme", "high", "district", "sessions", "tribunal",
        "act", "acts", "code", "section", "sections", "article", "articles",
        "rule", "rules", "order", "orders", "judgment", "judgement", "holding",
        "principles", "principle", "analysis", "doctrine", "bail", "appeal",
        "petition", "petitioner", "respondent", "applicant", "accused",
        "criminal", "civil", "law", "legal", "case", "cases", "matter",
        "anr", "ors", "another", "others", "versus", "and", "the", "for",
        "under", "with", "against", "regarding", "certain", "other",
        "ltd", "limited", "company", "corporation", "authority", "board",
        "commissioner", "officer", "director", "department", "ministry",
        "police", "cbi", "ed", "uoi", "nct",
    ],
    "ts_simple_abbrevs": [
        "IPC", "BNS", "CRPC", "BNSS", "COI", "SCC", "AIR",
        "CPC", "SRA", "NDPS", "POCSO", "IBC", "GST", "CBI", "BSA",
    ],
    "generic_doc_hint": (
        "Document Type: {doc_type}. Subject Matter: {subject_matter}. "
        "Ensure queries are tightly focused on the specific legal issues in the subject matter. "
        "Avoid broad generic constitutional queries unless fundamental rights are directly violated."
    ),
}

# ---------------------------------------------------------------------------
# Act-name aliases for exact-section extraction. Keyed by short_code;
# each alias is matched as a whole word/phrase inside query text.
# ---------------------------------------------------------------------------
CODE_ALIASES = {
    "BNSS":        ["bharatiya nagarik suraksha sanhita", "bnss"],
    "BNS":         ["bharatiya nyaya sanhita", "bns"],
    "BSA":         ["bharatiya sakshya adhiniyam", "bsa"],
    "CrPC":        ["code of criminal procedure", "criminal procedure code", "crpc"],
    "CPC":         ["code of civil procedure", "civil procedure code", "cpc"],
    "IPC":         ["indian penal code", "ipc"],
    "IEA":         ["indian evidence act", "evidence act", "iea"],
    "COI":         ["constitution of india", "coi"],
    "CONTRACT":    ["indian contract act", "contract act"],
    "SALE":        ["sale of goods act"],
    "PARTNERSHIP": ["partnership act"],
    "COMPANIES":   ["companies act"],
    "IBC":         ["insolvency and bankruptcy code", "ibc"],
    "NI":          ["negotiable instruments act", "ni act"],
    "TPA":         ["transfer of property act"],
    "REGISTRATION": ["registration act"],
    "EASEMENTS":   ["easements act"],
    "SRA":         ["specific relief act", "sra"],
    "HMA":         ["hindu marriage act", "hma"],
    "HSA":         ["hindu succession act"],
    "ARBITRATION": ["arbitration and conciliation act", "arbitration act"],
    "SARFAESI":    ["sarfaesi"],
    "RDB":         ["recovery of debts"],
    "CPA":         ["consumer protection act"],
    "ITAX":        ["income-tax act", "income tax act"],
    "CGST":        ["central goods and services tax", "cgst"],
    "IGST":        ["integrated goods and services tax"],
    "PC":          ["prevention of corruption act"],
    "PMLA":        ["prevention of money laundering act", "prevention of money-laundering act", "pmla"],
    "JJ":          ["juvenile justice"],
    "POCSO":       ["protection of children from sexual offences", "pocso"],
    "DV":          ["domestic violence act"],
    "POSH":        ["sexual harassment of women at workplace"],
    "IT":          ["information technology act"],
    "RTI":         ["right to information act"],
    "LARR":        ["land acquisition"],
    "IR":          ["industrial relations code"],
    "WAGES":       ["code on wages"],
    "NDPS":        ["narcotic drugs and psychotropic substances act", "ndps act", "ndps"],
    "LIMITATION":  ["limitation act"],
    "MV":          ["motor vehicles act", "mv act"],
    "ATA":         ["administrative tribunals act"],
    "COCA":        ["contempt of courts act"],
    "RERA":        ["real estate (regulation and development) act", "rera act", "rera"],
    "NGT":         ["national green tribunal act", "ngt act"],
    "CCA":         ["commercial courts act"],
    "IDA":         ["industrial disputes act"],
    "SMA":         ["special marriage act"],
    "GWA":         ["guardians and wards act", "guardian and wards act"],
    "HMGA":        ["hindu minority and guardianship act"],
    "HAMA":        ["hindu adoptions and maintenance act"],
}

# ---------------------------------------------------------------------------
# Doc-type hint rows, ported branch-by-branch from the old elif chain.
# (priority, keywords_any, keywords_all, subject_keywords_any, hint_text)
# First matching row (lowest priority number) wins.
# ---------------------------------------------------------------------------

_WRIT_CIVIL_BASE = (
    "This is a civil writ petition (Article 226/32). Subject: {subject_matter}. "
    "Ensure queries target: (a) scope of writ jurisdiction and alternative remedy doctrine, "
    "(b) the specific relief (mandamus, certiorari, prohibition, quo warranto), "
)
_WRIT_KW = ["writ", "226", "32"]

_SLP_BASE = (
    "This is a Special Leave Petition under Article 136 of the Constitution. "
    "{slp_sm_hint} "
    "Ensure queries target: (a) Article 136 scope — exceptional circumstances for interference, "
    "(b) interference with concurrent findings of fact by the Supreme Court — perversity standard, "
    "(c) substantial question of law required for SLP admission, "
    "(d) the specific legal error in the impugned High Court judgment."
)
_SLP_KW = ["slp", "special leave"]

HINT_ROWS = [
    # ── NDPS bail ──
    (10, ["ndps"], None, None,
     "This is a bail application under Section 37 of the NDPS Act. "
     "Ensure queries target: (a) Section 37 NDPS twin conditions — satisfaction that accused not guilty AND unlikely to commit offence, "
     "(b) gravity of commercial-quantity charge vs small-quantity distinction, "
     "(c) Section 20/21/22 NDPS Act — offence and punishment, "
     "(d) landmark NDPS bail precedents: Union of India v Thamisharasi, Tofan Singh v State of Tamil Nadu, "
     "Mohd. Muslim @ Hussain v State (NCT of Delhi)."),
    (11, None, ["bail"], ["ndps"],
     "This is a bail application under Section 37 of the NDPS Act. "
     "Ensure queries target: (a) Section 37 NDPS twin conditions — satisfaction that accused not guilty AND unlikely to commit offence, "
     "(b) gravity of commercial-quantity charge vs small-quantity distinction, "
     "(c) Section 20/21/22 NDPS Act — offence and punishment, "
     "(d) landmark NDPS bail precedents: Union of India v Thamisharasi, Tofan Singh v State of Tamil Nadu, "
     "Mohd. Muslim @ Hussain v State (NCT of Delhi)."),
    # ── PMLA bail ──
    (20, ["pmla", "money laundering", "ecir"], None, None,
     "This is a bail application under Section 45 of the Prevention of Money Laundering Act, 2002. "
     "Ensure queries target: (a) Section 45 PMLA twin conditions — reasonable grounds to believe not guilty AND not likely to commit offence, "
     "(b) Section 3/4 PMLA — offence of money laundering and attachment, "
     "(c) Enforcement Case Information Report (ECIR) vs FIR — arrest procedure, "
     "(d) landmark PMLA bail precedents: Vijay Madanlal Choudhary v UOI, Pavana Dibbur v ED, "
     "Pankaj Bansal v UOI (written grounds of arrest), P Chidambaram v ED."),
    (21, None, ["bail"], ["pmla", "money laundering"],
     "This is a bail application under Section 45 of the Prevention of Money Laundering Act, 2002. "
     "Ensure queries target: (a) Section 45 PMLA twin conditions — reasonable grounds to believe not guilty AND not likely to commit offence, "
     "(b) Section 3/4 PMLA — offence of money laundering and attachment, "
     "(c) Enforcement Case Information Report (ECIR) vs FIR — arrest procedure, "
     "(d) landmark PMLA bail precedents: Vijay Madanlal Choudhary v UOI, Pavana Dibbur v ED, "
     "Pankaj Bansal v UOI (written grounds of arrest), P Chidambaram v ED."),
    # ── POCSO ──
    (30, ["pocso"], None, None,
     "This is a POCSO-related application (bail / charge framing / discharge). "
     "Ensure queries target: (a) POCSO Act Sections 7, 8, 9, 10 — penetrative / aggravated sexual assault, "
     "(b) Section 29 POCSO — presumption of guilt, "
     "(c) Section 439 CrPC / 483 BNSS bail alongside Section 37-A POCSO restrictions, "
     "(d) charge framing standard — Section 228 CrPC / 251 BNSS prima facie test, "
     "(e) discharge — Section 227 CrPC / 250 BNSS — no sufficient grounds, "
     "(f) precedents: Alakh Alok Srivastava v UOI, Neeraj Sharma v State, State of MP v Madan Lal."),
    (31, ["bail", "charge", "discharge"], None, ["pocso"],
     "This is a POCSO-related application (bail / charge framing / discharge). "
     "Ensure queries target: (a) POCSO Act Sections 7, 8, 9, 10 — penetrative / aggravated sexual assault, "
     "(b) Section 29 POCSO — presumption of guilt, "
     "(c) Section 439 CrPC / 483 BNSS bail alongside Section 37-A POCSO restrictions, "
     "(d) charge framing standard — Section 228 CrPC / 251 BNSS prima facie test, "
     "(e) discharge — Section 227 CrPC / 250 BNSS — no sufficient grounds, "
     "(f) precedents: Alakh Alok Srivastava v UOI, Neeraj Sharma v State, State of MP v Madan Lal."),
    # ── Discharge / charge-framing (generic) ──
    (40, ["discharge", "charge sheet", "charge framing"], None, None,
     "This is a discharge / charge-framing stage application. "
     "Ensure queries target: (a) Section 227/239 CrPC / Section 250/262 BNSS — discharge when no sufficient ground, "
     "(b) Section 228/240 CrPC / Section 251/263 BNSS — charge framing prima facie standard, "
     "(c) scope of sifting evidence at charge stage — no mini-trial, "
     "(d) precedents: Union of India v Prafulla Kumar Samal, Dilawar Balu Kurane v State of Maharashtra, "
     "Sajjan Kumar v CBI, State of Karnataka v L. Muniswamy, "
     "(e) if bail is also sought, Section 437/439 CrPC / 480/483 BNSS bail grounds."),
    # ── Anticipatory bail ──
    (50, ["anticipatory bail"], None, None,
     "This is an anticipatory bail application. "
     "Ensure queries target: (a) Section 438 CrPC / Section 482 BNSS anticipatory bail grounds, "
     "(b) factors for grant/refusal (flight risk, evidence tampering, gravity of offence), "
     "(c) landmark precedents: Gurbaksh Singh Sibbia, Sushila Aggarwal, Siddharam Satlingappa, "
     "(d) conditions that may be imposed on anticipatory bail."),
    # ── Bail (generic) ──
    (60, ["bail"], None, None,
     "This is a bail application. "
     "Ensure queries target: (a) Section 437/439 CrPC / Section 480/483 BNSS bail grounds, "
     "(b) triple-test for bail (flight risk, tampering, repeat offence), "
     "(c) parity with co-accused bail doctrine, "
     "(d) landmark bail precedents: Arnesh Kumar, Dataram Singh, Prasanta Kumar Sarkar."),
    # ── Criminal appeal ──
    (70, ["criminal appeal"], None, None,
     "This is a criminal appeal. "
     "Ensure queries target: (a) perverse appreciation of evidence by trial court, "
     "(b) Section 374/377 CrPC / Section 415 BNSS appellate jurisdiction, "
     "(c) benefit of doubt / presumption of innocence at appellate stage, "
     "(d) re-appreciation of witness testimony and circumstantial evidence standards."),
    # ── Civil appeal ──
    (80, ["civil appeal"], None, None,
     "This is a civil appeal. "
     "Ensure queries target: (a) Section 96/100 CPC first and second appeal grounds, "
     "(b) question of law vs fact distinction for second appeal, "
     "(c) perversity of findings and misreading of evidence, "
     "(d) Section 115 CPC revision jurisdiction."),
    # ── Quash ──
    (90, ["quash", "quashing"], None, None,
     "This is a writ / FIR-quashing petition. "
     "Ensure queries target: (a) Section 41-A CrPC/BNSS non-compliance and wrongful arrest, "
     "(b) abuse of process / civil-vs-criminal remedy doctrine, "
     "(c) Section 482 CrPC / Section 528 BNSS inherent powers jurisprudence, "
     "(d) Bhajan Lal categories for quashing FIR."),
    # ── Criminal writ ──
    (100, None, ["writ", "criminal"], None,
     "This is a criminal writ petition under Article 226. "
     "Ensure queries target: (a) Articles 21, 22 — personal liberty and due process, "
     "(b) illegal detention / habeas corpus, "
     "(c) Section 482 CrPC / BNSS inherent powers, "
     "(d) the specific criminal issue: {subject_matter}."),
    # ── PIL ──
    (110, ["pil", "public interest"], None, None,
     "This is a Public Interest Litigation (PIL). "
     "Ensure queries target: (a) locus standi for PIL petitioners, "
     "(b) Article 32 / 226 scope for PILs, "
     "(c) the specific public law issue raised in facts, "
     "(d) landmark PIL precedents: Bandhua Mukti Morcha, Hussainara Khatoon, Vishaka."),
    # ── Civil writ, subject refinements (base + refinement, first match wins) ──
    (120, _WRIT_KW, None,
     ["pay", "salary", "acp", "assured career progression", "grade pay", "pay scale",
      "arrear", "increment", "pay fixation", "pay revision", "allowance"],
     _WRIT_CIVIL_BASE +
     "(c) ACP / MACP Assured Career Progression scheme — pay upgradation on completion of service years, "
     "(d) pay fixation rules — Fundamental Rules, CCS (RP) Rules, Pay Commission recommendations, "
     "(e) arrears release after non-implementation of a valid pay order — continuing cause of action doctrine, "
     "(f) mandamus to implement unrevoked government pay / promotion order, "
     "(g) limitation — State cannot set up laches when default is its own non-implementation of an order. "
     "Key precedents: State of Punjab v Amar Nath Goyal, Shyam Babu Verma v UOI, "
     "Bhupinder Singh v UOI, K Nagaraj v State of AP (pay protection), "
     "State of AP v Sagar Ahuja (continuing wrong in service pay)."),
    (121, _WRIT_KW, None, ["pension", "retiral", "gratuity"],
     _WRIT_CIVIL_BASE +
     "(c) pension rules — CCS Pension Rules, FR/SR, UGC/State pension schemes, "
     "(d) commutation of pension, family pension, gratuity computation, "
     "(e) right to pension as a vested right — not a bounty, "
     "(f) mandamus to release withheld pension arrears."),
    (122, _WRIT_KW, None, ["promotion", "seniority", "dpc", "selection grade", "time-bound", "time bound"],
     _WRIT_CIVIL_BASE +
     "(c) promotion criteria — DPC procedure, zone of consideration, roster system, "
     "(d) seniority fixation rules, merit-cum-seniority vs pure seniority, "
     "(e) Articles 14, 16 — equality in public employment, "
     "(f) mandamus to convene DPC or implement promotion order."),
    (123, _WRIT_KW, None, ["service", "employment", "termination", "dismissal", "reinstatement", "back wage", "back wages"],
     _WRIT_CIVIL_BASE +
     "(c) service law — Articles 14, 16, 311, natural justice in departmental inquiry, "
     "(d) reinstatement, back wages, wrongful termination precedents, "
     "(e) All India Services Rules / Central Services Rules applicable."),
    (124, _WRIT_KW, None, ["property", "land"],
     _WRIT_CIVIL_BASE +
     "(c) property rights, Article 300-A, land acquisition compensation, "
     "(d) mutation of revenue records, adverse possession, easement rights."),
    (125, _WRIT_KW, None, ["tax"],
     _WRIT_CIVIL_BASE +
     "(c) Income Tax Act / GST Act assessment and recovery, stay of demand, "
     "(d) Section 220 IT Act, principles of natural justice in tax proceedings."),
    (126, _WRIT_KW, None, ["labour"],
     _WRIT_CIVIL_BASE +
     "(c) Industrial Disputes Act, workman reinstatement, Section 25-F retrenchment, "
     "(d) unfair labour practice, award of labour court."),
    (127, _WRIT_KW, None, ["cheque"],
     _WRIT_CIVIL_BASE +
     "(c) Section 138/141 Negotiable Instruments Act, statutory notice requirements, "
     "(d) Section 139 NI Act presumptions, compounding under Section 147 NI Act."),
    (128, _WRIT_KW, None, ["matrimonial", "divorce"],
     _WRIT_CIVIL_BASE +
     "(c) Hindu Marriage Act / Special Marriage Act grounds for divorce, "
     "(d) maintenance under Section 125 CrPC / Section 144 BNSS, custody principles."),
    (129, _WRIT_KW, None, ["consumer"],
     _WRIT_CIVIL_BASE +
     "(c) Consumer Protection Act, deficiency of service, unfair trade practice, "
     "(d) NCDRC / State Commission jurisdiction and procedure."),
    (130, _WRIT_KW, None, None,
     _WRIT_CIVIL_BASE +
     "(c) constitutional and statutory basis for the relief sought in {subject_matter}."),
    # ── SLP, subject refinements ──
    (140, _SLP_KW, None, ["pay", "salary", "acp", "service", "employment", "pension", "promotion", "seniority"],
     _SLP_BASE.replace("{slp_sm_hint}",
        "Focus specifically on: service law SLP — pay fixation, ACP/MACP arrears, "
        "non-implementation of government order, Section 14/19 Administrative Tribunals Act, "
        "maintainability of SLP after CAT/High Court, scope of Article 136 in service matters.")),
    (141, _SLP_KW, None, ["cheque", "negotiable instrument", "section 138"],
     _SLP_BASE.replace("{slp_sm_hint}",
        "Focus on: Section 138/141 Negotiable Instruments Act cheque dishonour, "
        "legal notice period, Section 139 presumption, compounding under Section 147 NI Act, "
        "SLP maintainability when concurrent findings on cheque dishonour.")),
    (142, _SLP_KW, None, ["arbitration", "section 11", "award", "section 34"],
     _SLP_BASE.replace("{slp_sm_hint}",
        "Focus on: Arbitration and Conciliation Act — Section 11 appointment, "
        "Section 34 setting aside award, Section 37 appeal, scope of court interference in arbitral awards, "
        "unstamped agreement — admissibility (NN Global, In Re: Interplay).")),
    (143, _SLP_KW, None, ["land", "property", "acquisition", "revenue"],
     _SLP_BASE.replace("{slp_sm_hint}",
        "Focus on: land acquisition compensation, Section 24 Land Acquisition Act 2013 lapse, "
        "adverse possession, Article 300-A right to property, mutation of revenue records.")),
    (144, _SLP_KW, None, ["tax", "income tax", "gst", "custom"],
     _SLP_BASE.replace("{slp_sm_hint}",
        "Focus on: Income Tax Act / GST Act assessment, reassessment, penalty provisions, "
        "substantial question of law for SLP in tax matters, revenue vs capital expenditure, "
        "Section 263/271 IT Act, refund and interest.")),
    (145, _SLP_KW, None, None,
     _SLP_BASE.replace("{slp_sm_hint}", "Underlying subject: {subject_matter}.")),
    # ── IBC / insolvency ──
    (150, ["insolvency", "ibc", "nclt", "winding", "company petition"], None, None,
     "This is an insolvency / IBC / company petition. "
     "Ensure queries target: (a) Section 7/9/10 IBC financial/operational creditor claims — default and initiation, "
     "(b) CIRP initiation thresholds (Rs 1 crore), timelines and NCLT jurisdiction, "
     "(c) moratorium under Section 14 IBC — effect on pending suits, "
     "(d) Section 31 IBC resolution plan approval and Section 33 liquidation, "
     "(e) NCLAT appellate jurisdiction under Section 61 IBC, "
     "(f) pre-pack insolvency (PIRP), cross-border insolvency under Part Z IBC."),
    # ── Contempt ──
    (160, ["contempt"], None, None,
     "This is a Contempt of Court petition. "
     "Ensure queries target: (a) Contempt of Courts Act 1971 — civil contempt (wilful disobedience) vs criminal contempt, "
     "(b) Section 2(b)/2(c) CoC Act — definition and elements of contempt, "
     "(c) Article 129 (SC) / Article 215 (HC) — inherent power to punish contempt, "
     "(d) wilful disobedience of court order — deliberate and intentional act, "
     "(e) landmark contempt precedents: Re: Vinay Chandra Mishra, Prashant Bhushan contempt, "
     "Baradakanta Mishra v Bhimsen Dixit."),
    # ── Transfer petition ──
    (170, None, ["transfer", "petition"], None,
     "This is a Transfer Petition. "
     "Ensure queries target: (a) Section 25 CPC / Section 406 CrPC — grounds for transfer, "
     "(b) fair trial, apprehension of bias, convenience of parties as transfer grounds, "
     "(c) matrimonial transfer petitions — Section 25 CPC, wife's convenience principle, "
     "(d) Article 139-A Supreme Court transfer jurisdiction, "
     "(e) landmark transfer precedents: Surinder Kaur v Harbax Singh, Anita Kushwaha v Pushap Sudan."),
    # ── Review petition ──
    (180, None, ["review", "petition"], None,
     "This is a Review Petition. "
     "Ensure queries target: (a) Order 47 Rule 1 CPC / Section 114 CPC — grounds for review, "
     "(b) error apparent on the face of the record — narrow scope, "
     "(c) new evidence discovered after judgment, "
     "(d) review jurisdiction of Supreme Court under Article 137 / High Court under Article 226, "
     "(e) precedents: Northern India Caterers v Lt. Governor Delhi, Haridas Das v Usha Rani Banik."),
    # ── Curative ──
    (190, ["curative"], None, None,
     "This is a Curative Petition. "
     "Ensure queries target: (a) Rupa Hurra v Ashok Hurra — curative petition origin and grounds, "
     "(b) violation of principles of natural justice — not heard before judgment, "
     "(c) forum shopping / bias by judge, "
     "(d) curative petition as last constitutional remedy after review dismissed, "
     "(e) maintainability — certification by senior counsel, circulation before 3-judge bench."),
    # ── Civil revision / second appeal / LPA ──
    (200, ["civil revision", "second appeal", "lpa", "letters patent"], None, None,
     "This is a Civil Revision / Second Appeal / Letters Patent Appeal. "
     "Ensure queries target: (a) Section 115 CPC — revision jurisdiction — jurisdictional error, "
     "(b) Section 100 CPC — second appeal — substantial question of law, "
     "(c) Letters Patent Appeal — clause 10/15 — intra-court appeal against single judge, "
     "(d) non-interference with concurrent findings of fact, perversity standard, "
     "(e) substantial question of law — formulation at admission stage — Panchugopal Barua v Umesh Chandra Goswami."),
    # ── Article 131 original suit ──
    (210, ["131", "original suit", "inter-state", "inter state"], None, None,
     "This is an Original Suit / inter-State dispute under Article 131. "
     "Ensure queries target: (a) Article 131 — exclusive original jurisdiction of SC in Centre-State or State-State disputes, "
     "(b) legal right vs political question — justiciability, "
     "(c) water disputes (Article 262 / Inter-State River Water Disputes Act), "
     "(d) territorial boundary disputes, "
     "(e) precedents: State of Karnataka v State of Tamil Nadu, State of Rajasthan v UOI."),
    # ── CAT / administrative tribunal ──
    (220, ["cat", "administrative tribunal", "original application"], None, None,
     "This is a Service Matter Original Application before CAT / Administrative Tribunal. "
     "Subject: {subject_matter}. "
     "Ensure queries target: (a) Administrative Tribunals Act 1985 — jurisdiction, procedure, Section 14/15/19, "
     "(b) the specific service law violation: pay fixation, ACP/MACP, promotion, seniority, disciplinary proceedings, "
     "(c) Articles 14, 16 — equality in public employment, "
     "(d) limitation under Section 21 AT Act — continuing wrong doctrine for pay/allowance matters, "
     "(e) mandamus to implement government order — laches cannot be pleaded by the defaulting authority."),
    (221, None, ["service", "tribunal"], None,
     "This is a Service Matter Original Application before CAT / Administrative Tribunal. "
     "Subject: {subject_matter}. "
     "Ensure queries target: (a) Administrative Tribunals Act 1985 — jurisdiction, procedure, Section 14/15/19, "
     "(b) the specific service law violation: pay fixation, ACP/MACP, promotion, seniority, disciplinary proceedings, "
     "(c) Articles 14, 16 — equality in public employment, "
     "(d) limitation under Section 21 AT Act — continuing wrong doctrine for pay/allowance matters, "
     "(e) mandamus to implement government order — laches cannot be pleaded by the defaulting authority."),
    # ── MACT ──
    (230, ["motor accident", "mact", "motor vehicles"], None, None,
     "This is a Motor Accident Claim Petition before MACT. "
     "Ensure queries target: (a) Sections 140/163-A/166 Motor Vehicles Act — fault vs no-fault liability, "
     "(b) structured formula (Second Schedule) vs Sarla Verma formula for compensation, "
     "(c) multiplier method — loss of dependency, future prospects, non-pecuniary heads, "
     "(d) insurer's liability — policy conditions, gratuitous passenger exclusion, "
     "(e) precedents: National Insurance Co v Pranay Sethi, Sarla Verma v Delhi Transport Corp, "
     "Rani Devi v Rajasthan State RTC."),
    # ── RERA ──
    (240, ["rera", "real estate", "builder", "developer"], None, None,
     "This is a RERA / real estate complaint. "
     "Ensure queries target: (a) RERA Act 2016 — Section 18 (failure to hand over possession), "
     "Section 12 (false representation), Section 31 (complaint to authority), "
     "(b) RERA Appellate Tribunal jurisdiction — Section 43 RERA, "
     "(c) refund with interest (10.15%) — delay in possession, "
     "(d) consumer forum vs RERA — concurrent jurisdiction, "
     "(e) precedents: IREO Grace Realtech v Abhishek Khanna, Pioneer Urban Land v Govindan Raghavan."),
    # ── DRT / SARFAESI ──
    (250, ["drt", "sarfaesi", "debt recovery", "rdba"], None, None,
     "This is a Debt Recovery / SARFAESI application. "
     "Ensure queries target: (a) SARFAESI Act 2002 — Section 13(2) notice, Section 13(4) possession, "
     "Section 17 application to DRT, Section 18 appeal to DRAT, "
     "(b) Recovery of Debts and Bankruptcy Act 1993 — DRT jurisdiction, certificate of recovery, "
     "(c) Section 13(3A) SARFAESI — objection procedure and bank response obligation, "
     "(d) wrongful possession / auction — procedural defects, "
     "(e) precedents: United Bank of India v Satyawati Tondon, Mardia Chemicals v UOI."),
    # ── NGT / environment ──
    (260, ["ngt", "environment", "environmental", "green tribunal"], None, None,
     "This is an NGT / environmental matter. "
     "Ensure queries target: (a) NGT Act 2010 — Section 14/15/16 jurisdiction and compensation, "
     "(b) Environment Protection Act 1986 / Water Act 1974 / Air Act 1981 — violation, "
     "(c) precautionary principle, polluter pays principle, sustainable development, "
     "(d) Environmental Impact Assessment (EIA) notification compliance, "
     "(e) precedents: Sterlite Industries v UOI, Vellore Citizens Welfare Forum v UOI, "
     "MC Mehta v UOI (Taj Trapezium)."),
    # ── ITAT / tax appeal ──
    (270, ["itat", "tax appeal", "income tax", "gst appeal"], None, None,
     "This is a Tax Appeal before ITAT / Appellate Authority. "
     "Ensure queries target: (a) Income Tax Act 1961 — Section 143(3) assessment, Section 147/148 reassessment, "
     "Section 263 revision by CIT, Section 271 penalty, "
     "(b) GST Act — Section 73/74 demand, Section 83 provisional attachment, "
     "(c) revenue vs capital expenditure — Section 37 IT Act, "
     "(d) transfer pricing — Section 92 IT Act, arm's length price, "
     "(e) refund with interest — Section 244-A IT Act."),
    # ── Commercial suit ──
    (280, ["suit", "court"], ["commercial"], None,
     "This is a Commercial Suit under the Commercial Courts Act 2015. "
     "Ensure queries target: (a) Commercial Courts Act 2015 — specified value threshold (Rs 3 lakh+), jurisdiction, "
     "(b) mandatory pre-institution mediation — Section 12-A Commercial Courts Act, "
     "(c) Order XIII-A CPC — summary judgment in commercial disputes, "
     "(d) Section 36 Arbitration Act — enforcement of arbitral award as commercial matter, "
     "(e) expedited trial, discovery and document production under Commercial Courts regime."),
    # ── Industrial dispute ──
    (290, ["industrial dispute", "labour court", "reinstatement application"], None, None,
     "This is an Industrial Dispute / Labour Court matter. "
     "Ensure queries target: (a) Industrial Disputes Act 1947 — Section 25-F retrenchment compensation, "
     "Section 2(s) workman definition, Section 10 reference to tribunal, "
     "(b) reinstatement with back wages — unfair labour practice, "
     "(c) Section 33 ID Act — change in conditions of service during pendency, "
     "(d) jurisdiction — Industrial Tribunal vs Civil Court, "
     "(e) precedents: Workmen of Firestone Tyre v Firestone Tyre Co, "
     "Deepali Gundu Surwase v Kranti Junior Adhyapak Mahavidyalaya."),
    # ── Matrimonial / family ──
    (300, ["divorce", "custody", "maintenance petition", "maintenance application", "domestic violence", "matrimonial"], None, None,
     "This is a matrimonial / family law petition. "
     "Ensure queries target: (a) Hindu Marriage Act 1955 / Special Marriage Act 1954 — grounds for divorce (cruelty, desertion, adultery), "
     "(b) Section 125 CrPC / Section 144 BNSS — maintenance to wife and children, "
     "(c) Guardian and Wards Act 1890 / Hindu Minority and Guardianship Act 1956 — child custody, welfare principle, "
     "(d) Protection of Women from Domestic Violence Act 2005 — protection orders, residence orders, "
     "(e) irretrievable breakdown of marriage — Article 142 SC power, "
     "(f) precedents: Shilpa Sailesh v Varun Sreenivasan (irretrievable breakdown), Gita Hariharan v RBI."),
    # ── Cheque bounce ──
    (310, ["cheque", "negotiable instrument", "138"], None, None,
     "This is a Cheque Dishonour complaint under Section 138 Negotiable Instruments Act. "
     "Ensure queries target: (a) Section 138 NI Act — essential ingredients: cheque, debt, dishonour, legal notice within 30 days, "
     "(b) Section 141 NI Act — liability of directors / company officers, "
     "(c) Section 139 NI Act — presumption of debt, rebuttal, "
     "(d) Section 147 NI Act — compounding, "
     "(e) Court Metropolitan Magistrate jurisdiction, territorial jurisdiction — where cheque presented, "
     "(f) precedents: Kusum Ingots v UOI, Dashrath Rupsingh Rathod v State of Maharashtra (territorial jurisdiction)."),
    # ── Money recovery / civil suit ──
    (320, ["money recovery", "civil suit", "execution petition"], None, None,
     "This is a Civil Suit for money recovery / specific performance / partition / injunction. "
     "Ensure queries target: (a) Specific Relief Act 1963 — Section 10 specific performance, "
     "Section 38/39 permanent injunction, Section 6 suit for possession, "
     "(b) CPC Order VII Rule 11 — rejection of plaint, "
     "(c) CPC Order 39 Rules 1 & 2 — temporary injunction — prima facie case, balance of convenience, irreparable harm, "
     "(d) Section 9 CPC — civil courts jurisdiction, "
     "(e) Limitation Act 1963 — Article 54 specific performance (3 years), "
     "(f) precedents: Gujarat Bottling Co v Coca Cola Co (injunction), Adani Gas Ltd v UOI."),
    # ── Consumer complaint ──
    (330, ["consumer complaint", "consumer protection", "ncdrc", "consumer"], None, None,
     "This is a Consumer Complaint under the Consumer Protection Act 2019. "
     "Ensure queries target: (a) CPA 2019 — Section 2(7) consumer definition, Section 2(16) defect, "
     "Section 2(42) unfair trade practice, Section 2(11) deficiency in service, "
     "(b) pecuniary jurisdiction — District / State / National Commission (up to 1 Cr / 10 Cr / above), "
     "(c) CPA 2019 Section 35/47/58 complaint procedure, "
     "(d) service provider liability — builder, insurance company, hospital, "
     "(e) precedents: Spring Meadows Hospital v Harjol Ahluwalia, IREO Grace Realtech v Abhishek Khanna."),
]


def main():
    conn = psycopg2.connect(os.environ["DATABASE_URL"].strip('"'))
    conn.set_session(readonly=False, autocommit=False)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS retrieval_config (
            key   varchar PRIMARY KEY,
            value jsonb NOT NULL
        )""")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS doc_type_retrieval_hints (
            id                   serial PRIMARY KEY,
            priority             int NOT NULL,
            keywords_any         varchar[],
            keywords_all         varchar[],
            subject_keywords_any varchar[],
            hint_text            text NOT NULL
        )""")

    for key, value in RETRIEVAL_CONFIG.items():
        cur.execute(
            """INSERT INTO retrieval_config (key, value) VALUES (%s, %s)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
            (key, json.dumps(value)),
        )

    cur.execute("DELETE FROM doc_type_retrieval_hints")
    for priority, kw_any, kw_all, subj_any, hint in HINT_ROWS:
        cur.execute(
            """INSERT INTO doc_type_retrieval_hints
               (priority, keywords_any, keywords_all, subject_keywords_any, hint_text)
               VALUES (%s, %s, %s, %s, %s)""",
            (priority, kw_any, kw_all, subj_any, hint),
        )

    cur.execute("ALTER TABLE legal_codes ADD COLUMN IF NOT EXISTS aliases varchar[]")
    for short_code, aliases in CODE_ALIASES.items():
        cur.execute("UPDATE legal_codes SET aliases = %s WHERE short_code = %s", (aliases, short_code))

    conn.commit()
    cur.execute("SELECT count(*) FROM doc_type_retrieval_hints")
    print(f"Seeded {cur.fetchone()[0]} hint rows, {len(RETRIEVAL_CONFIG)} config keys, "
          f"{len(CODE_ALIASES)} alias sets.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
