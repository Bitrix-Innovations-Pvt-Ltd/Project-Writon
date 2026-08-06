"""
core/extraction.py — LLM field extraction from uploaded-document OCR text.

Powers the auto-populate step of the drafting wizard: after documents are
uploaded at Step 4, their OCR text is read once and turned into suggested
values for the Step 5 "Parties & Facts" form.

Scope is deliberately narrow — parties, dates, facts:
    petitioners, respondents, impugned_order_date, dates_and_events, facts_of_case

Not extracted, on purpose:
  * advocate_name / advocate_enrollment_no — the advocate shown in an old
    impugned order is frequently not the one filing the new petition.
  * jurisdiction_basis — a legal characterisation, not a fact in the record.
  * grounds / relief_sought / interim_relief_sought — legal argument, written
    by the Step 7 generation.

Mirrors core/verification.py: async OpenRouter client, strict JSON mode,
temperature 0.0, graceful degradation when OPENROUTER_API_KEY is absent or the
model returns malformed JSON. The public entry point never raises.
"""

import asyncio
import hashlib
import json
import os
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Optional

from app.core.rag import get_openrouter_client, openrouter_key

# ── Configuration ────────────────────────────────────────────────────────────
# gpt-4o, not -mini: a wrong petitioner name in a cause title is legally
# damaging, and this runs once per draft (Redis-cached thereafter).
EXTRACTION_MODEL = os.getenv("EXTRACTION_MODEL", "openai/gpt-4o")
EXTRACTION_TIMEOUT_S = float(os.getenv("EXTRACTION_TIMEOUT_S", "45"))

# Below this confidence a value goes to the low_confidence bucket for review
# and is never written into the form.
CONFIDENCE_FLOOR = 0.50

# Budgeting. ocr.py already caps PDFs at 5 pages (~10-17k chars worst case),
# so these bind only for unusually dense documents.
MAX_DOCS = 6
PER_DOC_HEAD_CHARS = 4500
PER_DOC_TAIL_CHARS = 1500
TOTAL_CHARS = 24000          # ~6k input tokens
MIN_DOC_CHARS = 80

MAX_EVENTS = 15

EXTRACTED_FIELDS = (
    "petitioners",
    "respondents",
    "impugned_order_date",
    "dates_and_events",
    "facts_of_case",
    "jurisdiction_basis",
)

LIST_FIELDS = {"petitioners", "respondents"}
DATE_FIELDS = {"impugned_order_date"}
# Free text rather than quotable values, so the verbatim grounding check in
# _is_grounded does not apply to these — a summary is not expected to appear
# word-for-word in the source.
SUMMARY_FIELDS = {"facts_of_case", "jurisdiction_basis"}

# jurisdiction_basis renders under a single-line <input> in the wizard, so a
# rambling answer would be unusable even if correct.
MAX_JURISDICTION_CHARS = 400

# ── jurisdiction_basis is overloaded ─────────────────────────────────────────
# One form field, five different meanings depending on the document type — see
# the CASE DETAILS block of each app/prompts/document_types/*.txt. Extraction
# has to be told which one it is looking for, or it answers the wrong question.
_JURISDICTION_DEFAULT = (
    "Jurisdiction Basis",
    "One sentence stating why THIS court has jurisdiction — typically where the "
    "cause of action arose, or where the authority that passed the impugned order "
    "is situated. Base it strictly on what the documents show (the seat of the "
    "authority, the place of the incident, the address of the parties). Do NOT "
    "assert a territorial link the documents do not support; return null instead.",
)

_JURISDICTION_SPECS: dict[str, tuple[str, str]] = {
    "bail_application": (
        "Crime Number / FIR No.",
        "The FIR or crime number the applicant is accused in, with the police "
        "station and the sections invoked, copied exactly as printed. Shape: "
        '"FIR No. 187 of 2026, P.S. Kavi Nagar, Ghaziabad, u/s 316(2) and 318(4) BNS". '
        "Never invent or complete a number — return null if it is not printed.",
    ),
    "anticipatory_bail": (
        "FIR / Case Reference",
        "The FIR or case reference the applicant apprehends arrest in, with the "
        "police station and the sections invoked, copied exactly as printed. Shape: "
        '"FIR No. 187 of 2026, P.S. Kavi Nagar, Ghaziabad, u/s 316(2) and 318(4) BNS". '
        "Never invent or complete a number — return null if it is not printed.",
    ),
    "civil_appeal": (
        "Court Below",
        "The exact name and designation of the court or tribunal that passed the "
        "decree or judgment under appeal, with the case/suit number if printed. "
        'Shape: "Court of the Civil Judge (Senior Division), Ghaziabad, in Suit '
        'No. 45 of 2023". Copy the designation as written.',
    ),
    "criminal_appeal": (
        "Trial Court / Sessions Court",
        "The exact name and designation of the trial or sessions court that passed "
        "the judgment under appeal, with the case/sessions trial number if printed. "
        'Shape: "Court of the Sessions Judge, Lucknow, in S.T. No. 120 of 2024". '
        "Copy the designation as written.",
    ),
}


def jurisdiction_spec(document_type_key: str) -> tuple[str, str]:
    """Return (label, extraction instruction) for this document type."""
    return _JURISDICTION_SPECS.get(document_type_key or "", _JURISDICTION_DEFAULT)


# ── Relief skeleton (deterministic — no LLM) ──────────────────────────────────
# base_rules.txt:69 copies relief_sought VERBATIM into the Prayer clause, so this
# text becomes the operative demand on the court. It is therefore assembled by
# string templating from values already in hand, never generated: a standard-form
# prayer cannot hallucinate.
#
# Two deliberate omissions:
#   * No bracket placeholders. Rule 11 would copy an unfilled "[add relief here]"
#     straight into a filed document, which rule 5 forbids. Guidance for the
#     advocate belongs in the UI, not in the field value.
#   * No statutory section or Article numbers. Whether CrPC or BNSS applies turns
#     on the date of the offence, and asserting the wrong one is worse than
#     leaving generation to phrase it.

_RESIDUARY_CLAUSE = (
    "Pass such further or other order(s) as this Hon'ble Court may deem fit and "
    "proper in the interest of justice."
)

# document_type_key -> (core relief template, which extracted value it needs)
# {ref} is the doc-type-specific jurisdiction value (FIR number, court below).
# {date} is the impugned order date, already normalised.
_RELIEF_SPECS: dict[str, tuple[str, str]] = {
    "bail_application": (
        "Release the applicant on bail in connection with {ref}, during the "
        "pendency of the trial", "ref",
    ),
    "anticipatory_bail": (
        "Direct that in the event of arrest in connection with {ref}, the "
        "applicant be released on bail", "ref",
    ),
    "civil_appeal": (
        "Set aside the judgment and decree dated {date} passed by {ref} and "
        "allow the appeal", "date",
    ),
    "criminal_appeal": (
        "Set aside the conviction and sentence dated {date} passed by {ref} and "
        "acquit the appellant", "date",
    ),
    "writ_petition_criminal": (
        "Issue a writ of certiorari, or any other appropriate writ, order or "
        "direction, quashing the impugned order dated {date}", "date",
    ),
}

_RELIEF_DEFAULT = (
    "Issue a writ of certiorari, or any other appropriate writ, order or "
    "direction, quashing the impugned order dated {date}", "date",
)


def _format_indian_date(iso: Optional[str]) -> Optional[str]:
    """YYYY-MM-DD -> DD/MM/YYYY, the one date format used in the draft."""
    if not iso:
        return None
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return None


def build_relief_skeleton(
    document_type_key: str = "",
    impugned_order_date: Optional[str] = None,
    jurisdiction_value: Optional[str] = None,
) -> Optional[str]:
    """Assemble a standard-form prayer skeleton, or None if the inputs are too
    thin for it to be more useful than an empty box.

    `jurisdiction_value` is whatever jurisdiction_basis holds for this document
    type — an FIR number for bail, the court below for an appeal.
    """
    template, required = _RELIEF_SPECS.get(document_type_key or "", _RELIEF_DEFAULT)

    date = _format_indian_date(impugned_order_date)
    ref = (jurisdiction_value or "").strip() or None

    # Without the value the clause hangs on, the skeleton says nothing useful.
    if required == "date" and not date:
        return None
    if required == "ref" and not ref:
        return None

    core = template
    if "{date}" in core:
        core = core.replace("{date}", date) if date else core.split(" dated {date}")[0]
    if "{ref}" in core:
        # An appeal template names the court below; drop the clause if unknown
        # rather than emitting "passed by None".
        core = core.replace("{ref}", ref) if ref else core.replace(" passed by {ref}", "")

    return f"a) {core};\n\nb) {_RESIDUARY_CLAUSE}"

# Documents most likely to carry the cause title and the operative dates are
# fed to the model first, so that if TOTAL_CHARS binds the useful ones survive.
_PRIORITY_HINTS = (
    "impugned", "order", "judgment", "judgement", "decree", "award",
    "fir", "charge", "notice", "agreement", "affidavit", "petition",
)

# Sentinels emitted by core/ocr.py when text extraction did not work.
_OCR_FAILURE_MARKERS = (
    "ocr failed",
    "extraction failed",
    "unsupported file type for ocr",
)


# ── Prompt ───────────────────────────────────────────────────────────────────

EXTRACTION_SYSTEM_PROMPT = """\
You are a meticulous Indian litigation clerk. You read OCR text from documents a
lawyer has uploaded (impugned orders, judgments, FIRs, notices, agreements,
affidavits, annexures) and you extract ONLY the facts needed to fill in the cause
title and factual sections of a fresh court pleading.

You are preparing data for a form that the lawyer will review before filing.
A wrong value is far worse than a missing value.

ABSOLUTE RULES
==============
1. NEVER invent, guess, complete or "correct" a name, date, number or fact.
   If it is not in the OCR text, return null (or [] for lists) for that field.
2. Names of parties must appear VERBATIM in the OCR text. Copy them
   character-for-character (you may drop honorifics and normalise whitespace,
   nothing else). Do not expand initials. Do not translate. Do not reorder names.
3. OCR text is noisy. If a value is only partly legible, return null rather than
   a reconstruction.
4. Every field carries a "confidence" from 0.0 to 1.0 — your honest probability
   that the value is correct AND is the value the lawyer wants for a NEW pleading.
   Use below 0.5 whenever you are unsure. Do not inflate.
5. Every field carries "source_doc": the exact DOC LABEL (e.g. "Impugned Order")
   you took it from. If it came from several, name the most authoritative one.

DOCUMENT TIERS — HOW TO USE EACH GROUP
======================================
The documents arrive in two labelled groups, and they are NOT interchangeable.

PRIMARY DOCUMENTS are the factual record — the impugned order, judgment, decree,
award, FIR or charge sheet. Every field you extract must be sourced from these:
the parties, the dates, the facts, the case reference.

SUPPORTING DOCUMENTS are identity/address proofs, vakalatnamas and memos of
parties. Use them for ONE purpose only: completing the descriptor of a party who
is ALREADY named in a primary document — parentage (S/o, D/o, W/o), address
(R/o) and age. This matters because orders often name a party with no address at
all, and a cause title needs one.
  * NEVER introduce a party who appears only in a supporting document.
  * NEVER take a date, fact, case number or event from a supporting document.
  * If a supporting document names a DIFFERENT person from the primary parties,
    ignore it completely and say so in "warnings".

MULTIPLE MATTERS — CHECK THIS FIRST
===================================
The advocate may have uploaded documents belonging to more than one case: a wrong
file, a re-used upload slot, or an unrelated annexure. Two documents belong to
DIFFERENT matters when the court, case/FIR number, or the accused/parties differ.

1. Before extracting anything, group the PRIMARY documents by matter. Supporting
   documents do not define a matter — never create a matter entry for one.
2. The PRIMARY matter is whichever matter DOCUMENT 1 belongs to. Documents are
   given to you most-probative-first, so DOCUMENT 1 is the impugned order or
   judgment for the case actually being drafted.
3. Extract EVERY field below for the PRIMARY MATTER ONLY. Completely ignore the
   other matters when filling those fields — never combine parties, dates, facts
   or case references across matters. A cause title mixing two cases is a
   catastrophic error.
4. Report all matters you found in the "matters" array, including the primary one,
   so the advocate can see that a stray document was uploaded.

PARTY ROLES — READ CAREFULLY
============================
The uploaded documents come from an EARLIER round of litigation. Roles are often
INVERTED in the document you are reading versus the pleading being drafted.
- Extract parties exactly as their role is stated in the uploaded document:
  "Petitioner", "Appellant", "Applicant", "Complainant", "Plaintiff" -> petitioners;
  "Respondent", "Opposite Party", "Defendant", "Accused", "State of ..." -> respondents.
- If an order describes the party who LOST as the "Petitioner", still list them as
  petitioners. The lawyer will re-assign roles. NEVER silently swap roles.
- Keep the full descriptor as written in the cause title, e.g.
  "Ram Kumar, S/o Shri Mohan Lal, aged 42, R/o 12 Nehru Marg, Jaipur" — retain
  S/o, D/o, W/o, R/o, age and designation where present.
- Strip leading serial numbers ("1.", "2)", "(iii)").
- Government respondents keep their full official designation, e.g.
  "State of Maharashtra, through the Principal Secretary, Home Department".
- Deduplicate. Preserve the order in which they appear in the cause title.

DATES
=====
- Output EVERY date strictly as YYYY-MM-DD. No other format is acceptable.
- Indian documents use DD/MM/YYYY or DD.MM.YYYY. Read "03/04/2023" as 3 April 2023
  unless the document unambiguously indicates otherwise.
- If a date is partial ("March 2023", "in 2019") or illegible, return null for
  impugned_order_date and OMIT the entry from dates_and_events.
- Never output a date in the future.

FIELD DEFINITIONS
=================
petitioners         : list of strings, cause-title descriptors (see above).
respondents         : list of strings, cause-title descriptors (see above).
impugned_order_date : date of THE order / judgment / FIR / award being challenged.
                      If several orders appear, choose the most recent operative
                      order under challenge, NOT an interim listing or adjournment date.
dates_and_events    : chronological list of material events, OLDEST FIRST. Each entry
                      is {"date": "YYYY-MM-DD", "event": "<= 25 words, factual, third
                      person, no legal argument"}. Maximum 15 entries. Skip procedural
                      noise (adjournments, "matter listed on", filing of vakalatnama)
                      unless materially relevant.
facts_of_case       : 150-350 words. Chronological narrative of what happened, third
                      person, past tense, purely factual. NO legal grounds, NO argument,
                      NO relief sought, NO citations. Use only what the documents state.
                      If the documents are too thin to support this, return null.
jurisdiction_basis  : DEFINED PER DOCUMENT TYPE. Follow the "JURISDICTION FIELD"
                      instruction in the user message exactly — it tells you which
                      value this document type expects. One line, under 60 words,
                      no legal argument. Return null unless the documents support it.

OUTPUT
======
Respond with a single JSON object and nothing else, exactly this shape:

{
  "petitioners":         {"value": ["..."], "confidence": 0.0, "source_doc": "..."},
  "respondents":         {"value": ["..."], "confidence": 0.0, "source_doc": "..."},
  "impugned_order_date": {"value": "YYYY-MM-DD", "confidence": 0.0, "source_doc": "..."},
  "dates_and_events":    {"value": [{"date": "YYYY-MM-DD", "event": "..."}],
                          "confidence": 0.0, "source_doc": "..."},
  "facts_of_case":       {"value": "...", "confidence": 0.0, "source_doc": "..."},
  "jurisdiction_basis":  {"value": "...", "confidence": 0.0, "source_doc": "..."},
  "matters": [
    {"case_ref": "Bail Application No. 456 of 2026",
     "court": "Court of the Sessions Judge, Lucknow",
     "parties": "Amit Kumar vs State of U.P.",
     "doc_numbers": [1, 3],
     "is_primary": true}
  ],
  "warnings": []
}

"matters" must list every distinct matter you found, each with the DOCUMENT
numbers it came from, and exactly one entry marked "is_primary": true — the one
DOCUMENT 1 belongs to. If all documents are the same matter, return a single entry.

"warnings" is for problems you actually observed in THESE documents — an
unreadable page, contradictory dates, two unrelated matters in one upload.
Leave it as [] when there is nothing to report. Never invent a warning and
never copy an example.

Use null for "value" when a field is absent. Use [] for absent lists. Every key
must be present. Emit no markdown, no prose, no code fences.
"""

EXTRACTION_USER_TEMPLATE = """\
The lawyer is preparing: {document_type} before {court_display}.
Subject matter: {subject_matter}

JURISDICTION FIELD — for this document type, "jurisdiction_basis" means:
{jurisdiction_label}
{jurisdiction_instruction}

Extract the fields defined in your instructions from the documents below.

{docs_block}
"""


# ── Date normalisation ───────────────────────────────────────────────────────

# DD/MM before MM/DD throughout — Indian convention.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
    "%d %B %Y", "%d %b %Y", "%d-%B-%Y", "%d-%b-%Y",
    "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
)


def normalize_date(raw: Any) -> Optional[str]:
    """Return a YYYY-MM-DD string, or None if the input cannot be parsed
    confidently. Rejects year-only values, pre-1900 dates and future dates —
    all three are hallucination or OCR-noise signatures rather than real
    document dates."""
    if not raw or not isinstance(raw, str):
        return None

    s = raw.strip().replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", s, flags=re.IGNORECASE)
    s = s.strip(" ,.")
    if not s:
        return None

    # Year alone is unusable for an <input type="date">.
    if re.fullmatch(r"\d{4}", s):
        return None

    parsed = None
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(s, fmt).date()
            break
        except ValueError:
            continue

    if parsed is None:
        return None
    if parsed.year < 1900 or parsed > date.today():
        return None
    return parsed.isoformat()


# ── Verbatim grounding guard ─────────────────────────────────────────────────

def _norm_for_match(s: str) -> str:
    """Fold to a comparison form that survives OCR noise: strip accents, drop
    everything that is not a letter or digit, lowercase."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _is_grounded(value: str, haystack_norm: str, min_len: int = 6) -> bool:
    """True if a party name actually occurs in the OCR text.

    Compares only the core name — the part before the first comma or bracket —
    since the rest of a cause-title descriptor (S/o, R/o, age) is often
    reformatted by the model even when the name itself is correct.
    """
    if not isinstance(value, str) or not value.strip():
        return False
    core = _norm_for_match(re.split(r"[,(]", value)[0])
    if len(core) < min_len:
        # Too short to test meaningfully (e.g. initials) — fall back to the
        # full descriptor rather than rejecting outright.
        core = _norm_for_match(value)
        if len(core) < min_len:
            return False
    return core in haystack_norm


# ── Document budgeting ───────────────────────────────────────────────────────

def is_usable_ocr(ocr_text: Any, min_chars: int = MIN_DOC_CHARS) -> bool:
    """False for OCR that failed or produced too little to be worth sending."""
    if not isinstance(ocr_text, str):
        return False
    stripped = ocr_text.strip()
    if len(stripped) < min_chars:
        return False
    lowered = stripped.lower()
    return not any(marker in lowered for marker in _OCR_FAILURE_MARKERS)


# ── Document tiers ───────────────────────────────────────────────────────────
# Uploads do not all play the same role. Feeding every file to every field lets a
# brochure or a blank template pollute the cause title, while dropping everything
# except the judgment loses the parentage/address particulars a cause title needs
# (a bail order routinely names "Amit Kumar" with no S/o or R/o at all).
#
#   primary    — impugned order, judgment, decree, award, FIR, charge sheet.
#                The factual record: parties, dates, facts, jurisdiction.
#   supporting — identity/address proof, vakalatnama, memo of parties.
#                Used ONLY to complete a party's descriptor, never to introduce
#                a new party, date or fact.
#   excluded   — blank templates, brochures, anything with no case content.
TIER_PRIMARY = "primary"
TIER_SUPPORTING = "supporting"
TIER_EXCLUDED = "excluded"

MAX_SUPPORTING_DOCS = 3
SUPPORTING_DOC_CHARS = 1500

_PRIMARY_TYPE_HINTS = (
    "impugned", "order", "judgment", "judgement", "decree", "award",
    "fir", "charge", "complaint", "notice", "agreement", "petition", "application",
)
_SUPPORTING_TYPE_HINTS = (
    "identity", "address", "aadhaar", "aadhar", "pan card", "photograph",
    "vakalatnama", "vakalat", "memo of parties", "proof",
)

# A blank pleading template carries court headings, party roles and "versus", so
# it reads as a real document — but its "parties" are placeholders. Measured on
# real uploads: genuine documents score 0 per 1k chars, a template 11.4.
_PLACEHOLDER_RE = re.compile(r"\[[^\]\n]{1,40}\]|_{4,}|<[A-Za-z /]{2,30}>")
_TEMPLATE_MIN_HITS = 3
_TEMPLATE_PER_1K = 2.0

_CASE_MARKER_RES = (
    re.compile(r"IN THE (COURT|HIGH COURT|SUPREME COURT|TRIBUNAL)", re.I),
    re.compile(r"(FIR|Crime|Case|Bail Application|Suit|S\.T\.)\s*(No\.?)?\s*\d+\s*of\s*\d{4}", re.I),
    re.compile(r"\b(versus|vs\.?|v/s)\b", re.I),
    re.compile(r"(Petitioner|Respondent|Applicant|Appellant|Accused|Opposite Party|Complainant)", re.I),
)


def looks_like_template(text: str) -> bool:
    """True for blank pleading templates and fill-in-the-blank forms."""
    if not isinstance(text, str) or not text.strip():
        return False
    hits = len(_PLACEHOLDER_RE.findall(text))
    per_1k = hits / max(1.0, len(text) / 1000.0)
    return hits >= _TEMPLATE_MIN_HITS and per_1k >= _TEMPLATE_PER_1K


def case_marker_count(text: str) -> int:
    if not isinstance(text, str):
        return 0
    return sum(1 for rx in _CASE_MARKER_RES if rx.search(text))


def classify_doc_tier(doc: dict) -> str:
    """Assign a document to primary / supporting / excluded."""
    text = doc.get("ocr_text") or ""
    if looks_like_template(text):
        return TIER_EXCLUDED

    label = f"{doc.get('doc_type') or ''} {doc.get('original_filename') or ''}".lower()
    if any(h in label for h in _SUPPORTING_TYPE_HINTS):
        return TIER_SUPPORTING
    if any(h in label for h in _PRIMARY_TYPE_HINTS):
        return TIER_PRIMARY

    # Generic checklist slots ("Documents specific to the subject-matter") carry
    # no signal in the type, so fall back to what the content actually looks like.
    return TIER_PRIMARY if case_marker_count(text) >= 2 else TIER_EXCLUDED


def unique_labels(docs: list[dict]) -> list[str]:
    """A distinct display label per document, in the order given.

    Advocates upload several files under one checklist type ("Lower Court
    Judgment" twice), so doc_type alone is ambiguous — and the model reports
    which document a value came from by label. Where a type repeats, the
    filename is appended so the attribution stays traceable to one file.
    """
    types = [(d.get("doc_type") or "").strip() for d in docs]
    labels: list[str] = []
    for i, doc in enumerate(docs):
        doc_type = types[i]
        filename = (doc.get("original_filename") or "").strip()
        if doc_type and types.count(doc_type) > 1 and filename:
            labels.append(f"{doc_type} ({filename})")
        else:
            labels.append(doc_type or filename or f"Document {i + 1}")
    return labels


def dedupe_docs(docs: list[dict]) -> list[dict]:
    """Drop re-uploads of the same content, keeping the first occurrence.

    Advocates re-upload the same file into several checklist slots (or the same
    slot repeatedly). Without this the identical text is sent to the model
    several times, consuming the budget that other documents need, and the
    ANNEXURES section — which base_rules.txt builds from this list — ends up
    with one entry per copy.

    Keyed on content, not filename, so the same order saved under two names is
    still recognised as one document.
    """
    seen: set[str] = set()
    unique: list[dict] = []
    for doc in docs or []:
        text = doc.get("ocr_text")
        if not isinstance(text, str):
            unique.append(doc)
            continue
        key = hashlib.sha1(re.sub(r"\s+", " ", text).strip().encode("utf-8", "ignore")).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        unique.append(doc)
    return unique


def doc_priority(doc: dict) -> int:
    """Lower sorts first. Documents whose type or filename hints at the
    impugned order / judgment / FIR carry the cause title and operative dates."""
    label = f"{doc.get('doc_type') or ''} {doc.get('original_filename') or ''}".lower()
    for idx, hint in enumerate(_PRIORITY_HINTS):
        if hint in label:
            return idx
    return len(_PRIORITY_HINTS)


def clip_head_tail(text: str, head_chars: int, tail_chars: int) -> str:
    """Head + tail, not head-only. The cause title is on page 1, but the
    operative date and the sign-off sit at the very end of an order — a pure
    head slice loses them."""
    text = text.strip()
    if len(text) <= head_chars + tail_chars:
        return text
    return (
        text[:head_chars]
        + "\n\n[... middle of document omitted ...]\n\n"
        + text[-tail_chars:]
    )


# Backwards-compatible private aliases used within this module.
_is_usable = is_usable_ocr
_doc_priority = doc_priority


def _clip(text: str) -> str:
    return clip_head_tail(text, PER_DOC_HEAD_CHARS, PER_DOC_TAIL_CHARS)


def _budget_docs(docs: list[dict]) -> tuple[list[dict], str]:
    """Select and clip the documents that go into the prompt.

    Returns (docs_used_metadata, labelled_docs_block).
    """
    usable = [d for d in dedupe_docs(docs) if _is_usable(d.get("ocr_text"))]

    tiers = {d["id"] if d.get("id") is not None else id(d): classify_doc_tier(d) for d in usable}

    def tier_of(doc: dict) -> str:
        return tiers[doc["id"] if doc.get("id") is not None else id(doc)]

    primary = [d for d in usable if tier_of(d) == TIER_PRIMARY]
    supporting = [d for d in usable if tier_of(d) == TIER_SUPPORTING]

    # Fallback: no judgment/order/FIR was uploaded, so promote the most
    # case-like remaining document rather than extracting nothing at all.
    if not primary:
        candidates = sorted(
            supporting,
            key=lambda d: case_marker_count(d.get("ocr_text") or ""),
            reverse=True,
        )
        if candidates and case_marker_count(candidates[0].get("ocr_text") or "") >= 1:
            promoted = candidates[0]
            primary = [promoted]
            supporting = [d for d in supporting if d is not promoted]

    # Supporting documents may only complete a party already named in a primary
    # document, so without one there is nothing they can contribute. Bail out
    # rather than spend an LLM call that cannot produce a field.
    if not primary:
        return [], ""

    primary.sort(key=_doc_priority)
    primary = primary[:MAX_DOCS]
    supporting = supporting[:MAX_SUPPORTING_DOCS]

    ordered = primary + supporting

    # Labels are computed over the final ordering so they match the DOC numbers
    # the model sees and reports back in source_doc.
    labels = unique_labels(ordered)

    used: list[dict] = []
    primary_blocks: list[str] = []
    supporting_blocks: list[str] = []
    total = 0

    for i, doc in enumerate(ordered, start=1):
        is_primary = i <= len(primary)
        body = (_clip(doc["ocr_text"]) if is_primary
                else doc["ocr_text"].strip()[:SUPPORTING_DOC_CHARS])
        if total + len(body) > TOTAL_CHARS:
            remaining = TOTAL_CHARS - total
            if remaining < MIN_DOC_CHARS:
                break
            body = body[:remaining]
        total += len(body)

        label = labels[i - 1]
        block = (
            f'=== DOC {i} | type: "{label}" | file: "{doc.get("original_filename") or "unknown"}" ===\n'
            f"{body}\n"
            f"=== END DOC {i} ==="
        )
        (primary_blocks if is_primary else supporting_blocks).append(block)
        used.append({
            "id": doc.get("id"),
            "doc_type": doc.get("doc_type"),
            "filename": doc.get("original_filename"),
            "label": label,
            "tier": TIER_PRIMARY if is_primary else TIER_SUPPORTING,
            "chars_used": len(body),
        })

    sections = []
    if primary_blocks:
        sections.append(
            "--- PRIMARY DOCUMENTS (the factual record for this matter) ---\n"
            + "\n\n".join(primary_blocks)
        )
    if supporting_blocks:
        sections.append(
            "--- SUPPORTING DOCUMENTS (party particulars ONLY — see rules) ---\n"
            + "\n\n".join(supporting_blocks)
        )

    return used, "\n\n".join(sections)


# ── Response post-processing ─────────────────────────────────────────────────

def _parse_json(content: str) -> dict:
    """Parse the model's reply, tolerating markdown code fences."""
    content = (content or "").strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return json.loads(content.strip())


def _coerce_confidence(raw: Any) -> float:
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.0


def _clean_party_list(raw: Any, haystack_norm: str) -> tuple[list[str], list[str]]:
    """Returns (grounded_names, ungrounded_names), deduplicated, order preserved."""
    if not isinstance(raw, list):
        return [], []

    grounded: list[str] = []
    ungrounded: list[str] = []
    seen: set[str] = set()

    for item in raw:
        if not isinstance(item, str):
            continue
        name = re.sub(r"^\s*[\(\[]?\s*\d+\s*[\.\)\]]\s*", "", item).strip()
        name = re.sub(r"\s+", " ", name)
        if not name:
            continue
        key = _norm_for_match(name)
        if not key or key in seen:
            continue
        seen.add(key)
        (grounded if _is_grounded(name, haystack_norm) else ungrounded).append(name)

    return grounded, ungrounded


def _clean_events(raw: Any) -> list[dict]:
    """Normalise dates, drop unparseable entries individually, sort ascending,
    cap at MAX_EVENTS."""
    if not isinstance(raw, list):
        return []

    cleaned: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for item in raw:
        if not isinstance(item, dict):
            continue
        iso = normalize_date(item.get("date"))
        event = item.get("event")
        if not iso or not isinstance(event, str) or not event.strip():
            continue
        event = re.sub(r"\s+", " ", event.strip())
        key = (iso, event.lower())
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"date": iso, "event": event})

    cleaned.sort(key=lambda e: e["date"])
    return cleaned[:MAX_EVENTS]


def _parse_matters(parsed: dict, docs_used: list[dict]) -> tuple[list[dict], list[int], list[str]]:
    """Normalise the model's `matters` array.

    Returns (matters, primary_doc_ids, warnings). `primary_doc_ids` are the
    uploaded_docs row ids belonging to the primary matter — the caller passes
    these to the drafting prompt so an unrelated case's documents cannot leak
    into the generated narrative or the ANNEXURES list.
    """
    raw = parsed.get("matters")
    if not isinstance(raw, list) or not raw:
        return [], [], []

    matters: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        # DOCUMENT numbers are 1-based positions in the order we fed them.
        doc_ids = []
        for n in (entry.get("doc_numbers") or []):
            try:
                idx = int(n) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(docs_used):
                doc_ids.append(docs_used[idx]["id"])
        matters.append({
            "case_ref": (entry.get("case_ref") or "").strip() or None,
            "court": (entry.get("court") or "").strip() or None,
            "parties": (entry.get("parties") or "").strip() or None,
            "doc_ids": doc_ids,
            "is_primary": bool(entry.get("is_primary")),
        })

    if not matters:
        return [], [], []

    # Exactly one primary. If the model marked none or several, fall back to the
    # matter containing the most probative document, which is the first one fed in.
    primaries = [m for m in matters if m["is_primary"]]
    if len(primaries) != 1:
        first_id = docs_used[0]["id"] if docs_used else None
        chosen = next((m for m in matters if first_id in m["doc_ids"]), matters[0])
        for m in matters:
            m["is_primary"] = m is chosen
        primaries = [chosen]

    primary = primaries[0]
    primary_doc_ids = list(primary["doc_ids"])

    warnings: list[str] = []
    if len(matters) > 1:
        others = [m for m in matters if not m["is_primary"]]
        labels = "; ".join(
            " / ".join(x for x in (m["case_ref"], m["court"], m["parties"]) if x) or "unidentified matter"
            for m in others
        )
        warnings.append(
            f"These uploads appear to cover {len(matters)} different matters. Fields were "
            f"filled from {primary['case_ref'] or 'the primary matter'} only. Also found: {labels}. "
            f"Check whether a document was uploaded to the wrong slot."
        )

    # A primary matter with no attributable documents cannot be used to filter.
    if not primary_doc_ids and docs_used:
        primary_doc_ids = [docs_used[0]["id"]]

    return matters, primary_doc_ids, warnings


def _postprocess(parsed: dict, haystack_norm: str) -> tuple[dict, dict, list[str]]:
    """Split the model output into auto-fillable fields and low-confidence
    fields, applying the date and grounding guards. Returns
    (fields, low_confidence, warnings)."""
    fields: dict[str, dict] = {}
    low: dict[str, dict] = {}
    warnings: list[str] = []

    raw_warnings = parsed.get("warnings")
    if isinstance(raw_warnings, list):
        warnings.extend(str(w) for w in raw_warnings if w)

    for name in EXTRACTED_FIELDS:
        entry = parsed.get(name)
        if not isinstance(entry, dict):
            continue

        value = entry.get("value")
        confidence = _coerce_confidence(entry.get("confidence"))
        source_doc = entry.get("source_doc") if isinstance(entry.get("source_doc"), str) else None

        def _put(bucket: dict, val: Any, reason: Optional[str] = None) -> None:
            payload = {"value": val, "confidence": confidence, "source_doc": source_doc}
            if reason:
                payload["reason"] = reason
            bucket[name] = payload

        if name in LIST_FIELDS:
            grounded, ungrounded = _clean_party_list(value, haystack_norm)
            if ungrounded:
                # Surfaced for review, never auto-filled — this is the main
                # defence against a hallucinated party name reaching a cause title.
                low[f"{name}__ungrounded"] = {
                    "value": ungrounded,
                    "confidence": confidence,
                    "source_doc": source_doc,
                    "reason": "grounding_failed: not found verbatim in the uploaded documents",
                }
                warnings.append(
                    f"{len(ungrounded)} name(s) suggested for {name} could not be located "
                    f"verbatim in the documents and were not filled in."
                )
            if not grounded:
                continue
            _put(low if confidence < CONFIDENCE_FLOOR else fields, grounded,
                 "low_confidence" if confidence < CONFIDENCE_FLOOR else None)

        elif name in DATE_FIELDS:
            iso = normalize_date(value)
            if not iso:
                if value:
                    warnings.append(
                        f"Could not read a reliable date for {name} — please enter it manually."
                    )
                continue
            _put(low if confidence < CONFIDENCE_FLOOR else fields, iso,
                 "low_confidence" if confidence < CONFIDENCE_FLOOR else None)

        elif name == "dates_and_events":
            events = _clean_events(value)
            if not events:
                continue
            _put(low if confidence < CONFIDENCE_FLOOR else fields, events,
                 "low_confidence" if confidence < CONFIDENCE_FLOOR else None)

        else:  # free text (facts_of_case, jurisdiction_basis)
            if not isinstance(value, str) or not value.strip():
                continue
            text_value = re.sub(r"\s+", " ", value.strip())
            if name == "jurisdiction_basis":
                # Single-line <input> in the wizard — a paragraph is unusable
                # there even when it is correct.
                if len(text_value) > MAX_JURISDICTION_CHARS:
                    text_value = text_value[:MAX_JURISDICTION_CHARS].rstrip() + "…"
            else:
                text_value = value.strip()
            _put(low if confidence < CONFIDENCE_FLOOR else fields, text_value,
                 "low_confidence" if confidence < CONFIDENCE_FLOOR else None)

    # ── Cross-list check: nobody may appear on both sides ────────────────────
    # Roles legitimately invert between rounds of litigation, so the same name
    # can be picked up as petitioner from one document and respondent from
    # another. Which side is right is a call only the advocate can make, so the
    # name is withdrawn from both and surfaced for review rather than guessed —
    # a cause title with the same party suing itself is unfilable.
    pet = fields.get("petitioners", {}).get("value") or []
    res = fields.get("respondents", {}).get("value") or []
    overlap = {_norm_for_match(p) for p in pet} & {_norm_for_match(r) for r in res}
    overlap.discard("")

    if overlap:
        conflicted = [p for p in pet if _norm_for_match(p) in overlap]
        for key, values in (("petitioners", pet), ("respondents", res)):
            kept = [v for v in values if _norm_for_match(v) not in overlap]
            if kept:
                fields[key]["value"] = kept
            else:
                fields.pop(key, None)

        low["parties__role_conflict"] = {
            "value": conflicted,
            "confidence": 0.0,
            "source_doc": None,
            "reason": ("role_conflict: listed as both petitioner and respondent across "
                       "the documents — assign the correct side yourself"),
        }
        warnings.append(
            f"{len(conflicted)} party/parties appear on BOTH sides across the uploaded "
            f"documents ({', '.join(conflicted)}). They were left out of the cause title — "
            f"roles often invert between rounds, so please assign them yourself."
        )

    return fields, low, warnings


# ── Public API ───────────────────────────────────────────────────────────────

async def extract_fields_from_docs(
    docs: list[dict],
    document_type: str = "",
    court_display: str = "",
    subject_matter: str = "",
    document_type_key: str = "",
) -> dict:
    """Extract Parties & Facts values from uploaded-document OCR text.

    :param docs: [{"id", "doc_type", "original_filename", "ocr_text"}, ...]
    :returns: {
        "status": "ok" | "no_docs" | "unavailable" | "error",
        "fields": {field: {"value", "confidence", "source_doc"}},
        "low_confidence": {field: {..., "reason"}},
        "docs_used": [...],
        "warnings": [str],
      }

    Never raises — the wizard must always be able to advance.
    """
    def _empty(status: str, *warnings: str) -> dict:
        return {
            "status": status,
            "fields": {},
            "low_confidence": {},
            "docs_used": [],
            "matters": [],
            "primary_doc_ids": [],
            "warnings": list(warnings),
        }

    if not openrouter_key:
        return _empty("unavailable", "AI extraction is not configured on this server.")

    docs_used, docs_block = _budget_docs(docs or [])
    if not docs_used:
        return _empty("no_docs")

    jurisdiction_label, jurisdiction_instruction = jurisdiction_spec(document_type_key)
    prompt = EXTRACTION_USER_TEMPLATE.format(
        document_type=document_type or "a court pleading",
        court_display=court_display or "the appropriate court",
        subject_matter=subject_matter or "not specified",
        jurisdiction_label=jurisdiction_label,
        jurisdiction_instruction=jurisdiction_instruction,
        docs_block=docs_block,
    )

    try:
        client = get_openrouter_client()
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=EXTRACTION_MODEL,
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=1800,
            ),
            timeout=EXTRACTION_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        print(f"[extraction] timed out after {EXTRACTION_TIMEOUT_S}s")
        return _empty("error", "Reading your documents took too long. Please try again.")
    except Exception as exc:
        print(f"[extraction] LLM call failed: {exc}")
        return _empty("error", "Automatic extraction failed. Please fill in the form manually.")

    content = ""
    try:
        content = response.choices[0].message.content
        parsed = _parse_json(content)
    except (json.JSONDecodeError, TypeError, AttributeError, IndexError) as exc:
        print(f"[extraction] parse error: {exc} | raw: {content!r:.500}")
        return _empty("error", "Automatic extraction returned an unreadable result.")

    if not isinstance(parsed, dict):
        return _empty("error", "Automatic extraction returned an unreadable result.")

    # Grounding haystack is built from the same clipped text the model saw, so a
    # name quoted from an omitted middle section is correctly treated as ungrounded.
    haystack_norm = _norm_for_match(docs_block)
    fields, low_confidence, warnings = _postprocess(parsed, haystack_norm)

    matters, primary_doc_ids, matter_warnings = _parse_matters(parsed, docs_used)
    # Surfaced first: a stray upload is more urgent than any per-field note.
    warnings = matter_warnings + warnings

    # Relief skeleton: derived by templating from the values just extracted, not
    # generated, so it carries no hallucination risk. Offered only when the form
    # field is not already populated by the advocate (handled client-side).
    skeleton = build_relief_skeleton(
        document_type_key=document_type_key,
        impugned_order_date=(fields.get("impugned_order_date") or {}).get("value"),
        jurisdiction_value=(fields.get("jurisdiction_basis") or {}).get("value"),
    )
    if skeleton:
        fields["relief_sought"] = {
            "value": skeleton,
            "confidence": 1.0,          # deterministic, not a model judgement
            "source_doc": "standard form",
        }
        warnings.append(
            "Relief Sought was pre-filled with a standard-form prayer covering only "
            "the core relief. Add any consequential, ancillary or interim relief you "
            "seek — it is reproduced verbatim in the Prayer clause."
        )

    # Supporting documents belong to no matter, but the draft still needs them —
    # they carry the party particulars and they must appear in ANNEXURES.
    if primary_doc_ids:
        supporting_ids = [
            d["id"] for d in docs_used
            if d.get("tier") == TIER_SUPPORTING and d.get("id") is not None
        ]
        primary_doc_ids = primary_doc_ids + [
            i for i in supporting_ids if i not in primary_doc_ids
        ]

    return {
        "status": "ok",
        "fields": fields,
        "low_confidence": low_confidence,
        "docs_used": docs_used,
        "matters": matters,
        "primary_doc_ids": primary_doc_ids,
        "warnings": warnings,
    }
