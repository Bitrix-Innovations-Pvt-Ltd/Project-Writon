"""
Context-gap detection for the Legal Assistant gapfill flow.

Key design decisions:
- FIELD_LABEL_MAP is loaded from the `document_field_requirements` DB table at
  runtime so adding a new document type / field requires no code change here.
- The keyword filter uses whole-word matching (not substring) to avoid false
  positives like "state" incorrectly blocking questions about the case status.
- The AI (GPT-4o) is called ONCE per gapfill session — caching is handled by
  the caller (gapfill.py / _get_or_compute_context_gaps).
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.rag import get_openrouter_client

# ── Prompt ─────────────────────────────────────────────────────────────────────

CONTEXT_GAP_DETECTION_PROMPT = """\
You are an expert Indian appellate lawyer reviewing a partially completed case \
file for a {document_type}.

Your goal: identify AT MOST 3 genuinely relevant additional facts or context \
pieces that are MISSING but would materially strengthen the draft.

CRITICAL RULES
==============
1. NEVER ask about any field listed in "Already Provided Data" below.
2. NEVER re-ask for petitioner names, respondent names, advocate name, facts,
   grounds, or relief if they are already given.
3. Only surface information that is truly absent AND non-trivial (not something
   the AI can reasonably infer or draft itself).
4. If everything important is already provided, return {{"gaps": []}}.
5. If facts are extremely sparse, ask one foundational question
   (e.g. "What are the core events of the dispute?").

Already Provided Data — DO NOT ask about any of these again:
{already_provided_summary}

Current Draft Information:
Facts   : {facts_of_case}
Grounds : {grounds}
Relief  : {relief_sought}

Respond ONLY with a JSON object with a single key "gaps" (array of objects).
Each object must have:
  "question"     : Exact conversational question to ask.
  "why_relevant" : One sentence explaining why this strengthens the draft.

Example:
{{
  "gaps": [
    {{
      "question": "Was there a prior representation made to the authority?",
      "why_relevant": "Required to establish exhaustion of remedies before approaching court."
    }}
  ]
}}
"""

# ── Keyword filter (whole-word matching, not substring) ───────────────────────
# Maps form_data field_key → list of regex patterns.
# Whole-word match prevents "state" from blocking "What is the current state of affairs?".

_FIELD_KEYWORD_PATTERNS: dict[str, list[re.Pattern]] = {}

# Raw keyword → regex with word-boundary anchors
_KEYWORD_DEFS: dict[str, list[str]] = {
    "petitioners":           [r"petitioner", r"appellant", r"applicant", r"plaintiff",
                               r"who\s+is\s+filing", r"party\s+filing"],
    "respondents":           [r"respondent", r"defendant", r"who\s+is\s+the\s+opposing"],
    "advocate_name":         [r"advocate\b", r"lawyer\b", r"counsel\b", r"attorney\b"],
    "facts_of_case":         [r"facts\s+of\s+the\s+case", r"factual\s+background",
                               r"what\s+happened", r"core\s+events"],
    "grounds":               [r"grounds\s+of", r"grounds\s+for", r"legal\s+grounds"],
    "relief_sought":         [r"relief\s+sought", r"relief\s+prayed", r"prayer\s+clause",
                               r"what\s+order\s+are\s+you", r"what\s+remedy"],
    "jurisdiction_basis":    [r"jurisdiction\s+basis", r"why\s+this\s+court\s+has",
                               r"authority\s+of\s+this\s+court"],
    "impugned_order_date":   [r"impugned\s+order", r"date\s+of\s+the\s+order",
                               r"when\s+was\s+the\s+order\s+passed"],
    "interim_relief_sought": [r"interim\s+relief", r"urgent\s+stay", r"urgent\s+injunction"],
}

def _compile_patterns():
    for field_key, raw_list in _KEYWORD_DEFS.items():
        _FIELD_KEYWORD_PATTERNS[field_key] = [
            re.compile(pattern, re.IGNORECASE) for pattern in raw_list
        ]

_compile_patterns()


# ── DB-driven field label map ─────────────────────────────────────────────────

async def _fetch_field_labels(db, document_type_key: str) -> dict[str, str]:
    """
    Load field_key → field_label from `document_field_requirements` for this
    document type, falling back to a compact hardcoded map if the table is empty
    or the DB call fails (e.g. during unit tests).
    """
    _FALLBACK: dict[str, str] = {
        "petitioners":           "Petitioner Name(s)",
        "respondents":           "Respondent Name(s)",
        "advocate_name":         "Advocate Name",
        "advocate_enrollment_no":"Advocate Enrollment No.",
        "facts_of_case":         "Facts of the Case",
        "grounds":               "Grounds",
        "relief_sought":         "Relief Sought",
        "jurisdiction_basis":    "Jurisdiction Basis",
        "impugned_order_date":   "Impugned Order Date",
        "interim_relief_sought": "Interim Relief Sought",
        "mandatory_paragraphs":  "Mandatory Paragraphs",
        "case_description":      "Case Description",
        "subject_matter":        "Subject Matter",
        "court_level":           "Court Level",
        "document_type":         "Document Type",
        "dates_and_events":      "Dates and Events",
    }

    if db is None:
        return _FALLBACK

    try:
        from sqlalchemy.future import select
        from app.models.gapfill import DocumentFieldRequirements

        result = await db.execute(
            select(DocumentFieldRequirements.field_key, DocumentFieldRequirements.field_label)
            .filter(DocumentFieldRequirements.document_type_key == document_type_key)
        )
        rows = result.all()
        if rows:
            return {r.field_key: r.field_label for r in rows}
    except Exception:
        pass  # DB unavailable — use fallback

    return _FALLBACK


# ── "Already provided" summary ────────────────────────────────────────────────

def _is_list_nonempty(value: Any) -> bool:
    if not isinstance(value, list) or len(value) == 0:
        return False
    for item in value:
        if isinstance(item, str) and item.strip():
            return True
        if isinstance(item, dict) and any(str(v).strip() for v in item.values()):
            return True
    return False


def _build_already_provided_summary(form_data: dict, field_label_map: dict[str, str]) -> str:
    lines: list[str] = []

    for field_key, label in field_label_map.items():
        value = form_data.get(field_key)
        if value is None:
            continue

        if isinstance(value, list):
            if not _is_list_nonempty(value):
                continue
            if value and isinstance(value[0], str):
                display = ", ".join(v for v in value if v.strip())
            else:
                display = f"{len(value)} entries"
            lines.append(f"- {label}: {display}")

        elif isinstance(value, str) and value.strip():
            preview = value.strip()[:100]
            if len(value.strip()) > 100:
                preview += "..."
            lines.append(f"- {label}: {preview}")

    return "\n".join(lines) if lines else "None yet"


# ── Keyword post-filter ───────────────────────────────────────────────────────

def _is_about_filled_field(question: str, form_data: dict) -> bool:
    """
    Return True if the AI question is about a field that is already filled.
    Uses whole-word regex patterns to avoid false positives.
    """
    for field_key, patterns in _FIELD_KEYWORD_PATTERNS.items():
        value = form_data.get(field_key)
        if value is None:
            continue
        if isinstance(value, list) and not _is_list_nonempty(value):
            continue
        if isinstance(value, str) and not value.strip():
            continue
        # Field is filled — check if question is about it
        if any(p.search(question) for p in patterns):
            return True
    return False


# ── Public API ────────────────────────────────────────────────────────────────

async def detect_context_gaps(
    form_data: dict,
    document_type_key: str,
    db=None,
) -> list[dict]:
    """
    Ask GPT-4o to identify at most 3 genuinely missing context gaps.

    :param form_data:          The user's current form data.
    :param document_type_key:  e.g. "writ_petition_civil".
    :param db:                 Optional async DB session (for DB-driven field labels).
    :returns:                  List of {"question": ..., "why_relevant": ...} dicts.
    """
    field_label_map        = await _fetch_field_labels(db, document_type_key)
    already_provided_summary = _build_already_provided_summary(form_data, field_label_map)

    prompt = CONTEXT_GAP_DETECTION_PROMPT.format(
        document_type=document_type_key,
        already_provided_summary=already_provided_summary,
        facts_of_case=form_data.get("facts_of_case", "Not provided"),
        grounds=form_data.get("grounds", "Not provided — AI will draft"),
        relief_sought=form_data.get("relief_sought", "Not provided"),
    )

    client = get_openrouter_client()
    response = await client.chat.completions.create(
        model="openai/gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400,
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    try:
        content = response.choices[0].message.content.strip()
        # Strip optional markdown code fences
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        parsed      = json.loads(content)
        suggestions = parsed.get("gaps", [])

        if not isinstance(suggestions, list):
            return []

        # Post-filter: drop any question about an already-filled field
        filtered = [
            s for s in suggestions
            if isinstance(s, dict)
            and s.get("question")
            and not _is_about_filled_field(s["question"], form_data)
        ]

        return filtered[:3]  # hard cap

    except (json.JSONDecodeError, TypeError, AttributeError) as exc:
        raw = getattr(response.choices[0].message, "content", "")
        print(f"[context_gaps] parse error: {exc} | raw: {raw}")
        return []
