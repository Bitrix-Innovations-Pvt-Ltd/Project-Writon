"""
Unit tests for core/extraction.py — the pure helpers only.

No DB, no network, no OPENROUTER_API_KEY required. These cover the two guards
that stand between a hallucinating model and a lawyer's cause title:
normalize_date() and _is_grounded().
"""

import re

import pytest

from app.core.extraction import (
    EXTRACTED_FIELDS,
    MAX_DOCS,
    MAX_EVENTS,
    MAX_JURISDICTION_CHARS,
    MAX_SUPPORTING_DOCS,
    SUMMARY_FIELDS,
    TIER_EXCLUDED,
    TIER_PRIMARY,
    TIER_SUPPORTING,
    TOTAL_CHARS,
    build_relief_skeleton,
    classify_doc_tier,
    looks_like_template,
    _budget_docs,
    _clean_events,
    _clean_party_list,
    _is_grounded,
    _is_usable,
    _norm_for_match,
    _parse_matters,
    _postprocess,
    dedupe_docs,
    jurisdiction_spec,
    normalize_date,
)


# ── normalize_date ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("2023-03-15",      "2023-03-15"),
    ("15/03/2023",      "2023-03-15"),   # Indian DD/MM
    ("15.03.2023",      "2023-03-15"),
    ("15-03-2023",      "2023-03-15"),
    ("03/04/2023",      "2023-04-03"),   # DD/MM wins over MM/DD
    ("15 March 2023",   "2023-03-15"),
    ("15 Mar 2023",     "2023-03-15"),
    ("1st March 2020",  "2020-03-01"),
    ("23rd July 2019",  "2019-07-23"),
    ("  15/03/2023 ",   "2023-03-15"),   # whitespace
    ("March 2023",      None),           # partial — no day
    ("2023",            None),           # year only
    ("2099-01-01",      None),           # future
    ("1823-01-01",      None),           # pre-1900
    ("garbage",         None),
    ("",                None),
    (None,              None),
    (12345,             None),           # non-string
])
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected


def test_normalize_date_rejects_future_relative_to_today():
    from datetime import date, timedelta
    tomorrow = date.today() + timedelta(days=1)
    assert normalize_date(tomorrow.isoformat()) is None


# ── grounding guard ──────────────────────────────────────────────────────────

CAUSE_TITLE = """
IN THE HIGH COURT OF JUDICATURE AT ALLAHABAD
Writ - C No. 12345 of 2023
Ram Kumar, S/o Shri Mohan Lal, R/o 12 Nehru Marg, Jaipur   ... Petitioner
                              Versus
State of Uttar Pradesh, through the Principal Secretary    ... Respondent
"""


def test_grounding_accepts_real_name():
    hay = _norm_for_match(CAUSE_TITLE)
    assert _is_grounded("Ram Kumar, S/o Shri Mohan Lal, R/o 12 Nehru Marg, Jaipur", hay)
    assert _is_grounded("State of Uttar Pradesh, through the Principal Secretary", hay)


def test_grounding_rejects_hallucinated_name():
    hay = _norm_for_match(CAUSE_TITLE)
    assert not _is_grounded("Shyam Sundar Sharma", hay)
    assert not _is_grounded("State of Maharashtra", hay)


def test_grounding_survives_whitespace_and_punctuation_noise():
    """OCR mangles spacing and punctuation; the guard must not reject on that."""
    hay = _norm_for_match(CAUSE_TITLE)
    assert _is_grounded("Ram  Kumar", hay)
    assert _is_grounded("RAM KUMAR", hay)


def test_clean_party_list_splits_grounded_and_ungrounded():
    hay = _norm_for_match(CAUSE_TITLE)
    grounded, ungrounded = _clean_party_list(
        ["1. Ram Kumar, S/o Shri Mohan Lal", "2. Shyam Sundar Sharma"], hay
    )
    assert grounded == ["Ram Kumar, S/o Shri Mohan Lal"]      # serial number stripped
    assert ungrounded == ["Shyam Sundar Sharma"]


def test_clean_party_list_deduplicates():
    hay = _norm_for_match(CAUSE_TITLE)
    grounded, _ = _clean_party_list(["Ram Kumar", "RAM  KUMAR", "ram kumar"], hay)
    assert grounded == ["Ram Kumar"]


# ── events ───────────────────────────────────────────────────────────────────

def test_clean_events_drops_bad_dates_keeps_rest_and_sorts():
    events = _clean_events([
        {"date": "15/03/2023", "event": "Impugned order passed"},
        {"date": "March 2022",  "event": "Unparseable — dropped"},
        {"date": "01/01/2021",  "event": "Notice issued"},
        {"date": "05/05/2023",  "event": ""},               # empty event — dropped
    ])
    assert [e["date"] for e in events] == ["2021-01-01", "2023-03-15"]
    assert events[0]["event"] == "Notice issued"


def test_clean_events_caps_at_max():
    raw = [{"date": f"2020-01-{d:02d}", "event": f"event {d}"} for d in range(1, 29)]
    assert len(_clean_events(raw)) == MAX_EVENTS


def test_clean_events_handles_non_list():
    assert _clean_events(None) == []
    assert _clean_events("not a list") == []


# ── document budgeting ───────────────────────────────────────────────────────

def test_is_usable_rejects_ocr_failure_sentinels():
    assert not _is_usable("OCR Failed for this document")
    assert not _is_usable("Unsupported file type for OCR.")
    assert not _is_usable("tiny")                 # below MIN_DOC_CHARS
    assert not _is_usable(None)
    assert _is_usable("x" * 200)


def test_budget_caps_doc_count_and_total_chars():
    # Content must differ per document (identical text is collapsed by
    # dedupe_docs) AND must read as a real case document, or the relevance gate
    # in classify_doc_tier excludes it before budgeting is ever exercised.
    docs = [
        {"id": i, "doc_type": "Impugned Order", "original_filename": f"{i}.pdf",
         "ocr_text": f"DOC-{i} " + REAL_ORDER + ("x" * 50_000)}
        for i in range(10)
    ]
    used, block = _budget_docs(docs)
    assert 1 < len(used) <= MAX_DOCS      # >1 proves dedupe did not collapse them
    assert sum(d["chars_used"] for d in used) <= TOTAL_CHARS


def test_budget_prioritises_the_impugned_order():
    """If the total cap binds, the document carrying the cause title must survive."""
    docs = [
        {"id": 1, "doc_type": "Annexure P-1", "original_filename": "misc.pdf",
         "ocr_text": "[DOC-1] " + "a" * 30_000},
        {"id": 2, "doc_type": "Impugned Order", "original_filename": "order.pdf",
         "ocr_text": "[DOC-2] " + "b" * 30_000},
    ]
    used, _ = _budget_docs(docs)
    assert used[0]["doc_type"] == "Impugned Order"


def test_budget_keeps_head_and_tail():
    """The cause title is on page 1 but the operative date is in the sign-off —
    a head-only slice would lose it."""
    text = "HEAD_MARKER" + ("x" * 40_000) + "TAIL_MARKER"
    used, block = _budget_docs([
        {"id": 1, "doc_type": "Order", "original_filename": "o.pdf", "ocr_text": text}
    ])
    assert "HEAD_MARKER" in block
    assert "TAIL_MARKER" in block
    assert "middle of document omitted" in block


def test_budget_returns_nothing_for_unusable_docs():
    used, block = _budget_docs([
        {"id": 1, "doc_type": "X", "original_filename": "x.pdf", "ocr_text": "OCR Failed"}
    ])
    assert used == [] and block == ""


# ── jurisdiction_basis: one field, five meanings ─────────────────────────────
# Each template renders this field under a different heading (see the CASE
# DETAILS block of app/prompts/document_types/*.txt), so extraction has to be
# told which value the document type expects.

@pytest.mark.parametrize("key,expected_label", [
    ("bail_application",      "Crime Number / FIR No."),
    ("anticipatory_bail",     "FIR / Case Reference"),
    ("civil_appeal",          "Court Below"),
    ("criminal_appeal",       "Trial Court / Sessions Court"),
    ("writ_petition_civil",   "Jurisdiction Basis"),
    ("writ_petition_criminal","Jurisdiction Basis"),
    ("",                      "Jurisdiction Basis"),
    (None,                    "Jurisdiction Basis"),
    ("some_unknown_key",      "Jurisdiction Basis"),
])
def test_jurisdiction_spec_label_per_document_type(key, expected_label):
    label, instruction = jurisdiction_spec(key)
    assert label == expected_label
    assert instruction.strip()


def test_jurisdiction_specs_are_distinct_instructions():
    """A bail FIR number and an appeal's court-below are different questions;
    the instructions must not collapse to the same text."""
    instructions = {
        jurisdiction_spec(k)[1]
        for k in ("bail_application", "civil_appeal", "criminal_appeal", "writ_petition_civil")
    }
    assert len(instructions) == 4


def test_jurisdiction_basis_is_an_extracted_field_exempt_from_grounding():
    assert "jurisdiction_basis" in EXTRACTED_FIELDS
    # It is a characterisation, not a quotable string, so the verbatim guard
    # cannot apply to it.
    assert "jurisdiction_basis" in SUMMARY_FIELDS


def _pp(value, confidence=0.9):
    fields, low, _ = _postprocess(
        {"jurisdiction_basis": {"value": value, "confidence": confidence,
                                "source_doc": "Impugned Order"}},
        haystack_norm="",
    )
    return fields, low


def test_jurisdiction_basis_passes_through_and_collapses_whitespace():
    fields, _ = _pp("FIR No. 187 of 2026,\n  P.S. Kavi Nagar,   Ghaziabad")
    assert fields["jurisdiction_basis"]["value"] == "FIR No. 187 of 2026, P.S. Kavi Nagar, Ghaziabad"


def test_jurisdiction_basis_is_capped_for_the_single_line_input():
    """The wizard renders this in an <input type=text>; a paragraph is unusable
    there even when correct."""
    fields, _ = _pp("x" * (MAX_JURISDICTION_CHARS + 500))
    assert len(fields["jurisdiction_basis"]["value"]) <= MAX_JURISDICTION_CHARS + 1
    assert fields["jurisdiction_basis"]["value"].endswith("…")


def test_low_confidence_jurisdiction_is_not_auto_filled():
    fields, low = _pp("Cause of action arose in Delhi", confidence=0.2)
    assert "jurisdiction_basis" not in fields
    assert low["jurisdiction_basis"]["reason"] == "low_confidence"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_absent_jurisdiction_is_dropped(value):
    fields, low = _pp(value)
    assert "jurisdiction_basis" not in fields and "jurisdiction_basis" not in low


# ── multiple matters in one upload set ───────────────────────────────────────
# Real failure this guards: two unrelated bail matters uploaded to the same
# "Lower Court Judgment" slot were merged into one cause title. The grounding
# guard cannot catch it — every name really is in the documents.

DOCS_USED = [
    {"id": 30, "label": "Lower Court Judgment"},
    {"id": 32, "label": "Lower Court Judgment"},
    {"id": 41, "label": "Annexure P-1"},
]


def test_single_matter_produces_no_warning():
    matters, primary_ids, warnings = _parse_matters(
        {"matters": [{"case_ref": "Bail App. 456/2026", "court": "Sessions Judge, Lucknow",
                      "parties": "Amit Kumar vs State of U.P.",
                      "doc_numbers": [1, 3], "is_primary": True}]},
        DOCS_USED,
    )
    assert len(matters) == 1
    assert primary_ids == [30, 41]
    assert warnings == []


def test_two_matters_warn_and_scope_to_primary():
    matters, primary_ids, warnings = _parse_matters(
        {"matters": [
            {"case_ref": "Bail App. 456/2026", "court": "Sessions Judge, Lucknow",
             "parties": "Amit Kumar vs State of U.P.", "doc_numbers": [1], "is_primary": True},
            {"case_ref": "Bail App. 1142/2026", "court": "Sessions Judge, Ghaziabad",
             "parties": "Deepak Chaudhary vs State of U.P.", "doc_numbers": [2], "is_primary": False},
        ]},
        DOCS_USED,
    )
    assert primary_ids == [30]                       # the other matter's doc is excluded
    assert 32 not in primary_ids
    assert len(warnings) == 1
    assert "2 different matters" in warnings[0]
    assert "Bail App. 1142/2026" in warnings[0]      # names the stray so it is findable


def test_falls_back_to_first_doc_when_no_primary_marked():
    """Documents are fed most-probative-first, so document 1 decides."""
    matters, primary_ids, _ = _parse_matters(
        {"matters": [
            {"case_ref": "A", "doc_numbers": [2], "is_primary": False},
            {"case_ref": "B", "doc_numbers": [1], "is_primary": False},
        ]},
        DOCS_USED,
    )
    assert [m["case_ref"] for m in matters if m["is_primary"]] == ["B"]
    assert primary_ids == [30]


def test_multiple_primaries_are_resolved_to_one():
    matters, primary_ids, _ = _parse_matters(
        {"matters": [
            {"case_ref": "A", "doc_numbers": [1], "is_primary": True},
            {"case_ref": "B", "doc_numbers": [2], "is_primary": True},
        ]},
        DOCS_USED,
    )
    assert sum(1 for m in matters if m["is_primary"]) == 1
    assert primary_ids == [30]


def test_out_of_range_and_garbage_doc_numbers_are_ignored():
    _, primary_ids, _ = _parse_matters(
        {"matters": [{"case_ref": "A", "doc_numbers": [1, 99, "x", None], "is_primary": True}]},
        DOCS_USED,
    )
    assert primary_ids == [30]


def test_primary_with_no_attributable_docs_defaults_to_first():
    """Never return an empty filter — that would strip every document."""
    _, primary_ids, _ = _parse_matters(
        {"matters": [{"case_ref": "A", "doc_numbers": [], "is_primary": True}]},
        DOCS_USED,
    )
    assert primary_ids == [30]


@pytest.mark.parametrize("parsed", [{}, {"matters": None}, {"matters": []}, {"matters": ["junk"]}])
def test_missing_or_malformed_matters_degrade_quietly(parsed):
    matters, primary_ids, warnings = _parse_matters(parsed, DOCS_USED)
    assert matters == [] and primary_ids == [] and warnings == []


# ── conflict: same party on both sides ───────────────────────────────────────
# Roles legitimately invert between rounds of litigation, so one name can be
# picked up as petitioner from one document and respondent from another. A cause
# title with the same party on both sides is unfilable, and only the advocate can
# say which side is right.

HAY = _norm_for_match("Ram Kumar versus State of U.P. — Ram Kumar was appellant below")


def _parties(pet, res, conf=0.9):
    return _postprocess({
        "petitioners": {"value": pet, "confidence": conf, "source_doc": "Order"},
        "respondents": {"value": res, "confidence": conf, "source_doc": "FIR"},
    }, HAY)


def test_party_on_both_sides_is_withdrawn_from_both():
    fields, low, warnings = _parties(["Ram Kumar"], ["Ram Kumar", "State of U.P."])
    assert "petitioners" not in fields                    # nothing left to fill
    assert fields["respondents"]["value"] == ["State of U.P."]
    assert "role_conflict" in low["parties__role_conflict"]["reason"]
    assert low["parties__role_conflict"]["value"] == ["Ram Kumar"]
    assert any("BOTH sides" in w for w in warnings)


def test_role_conflict_matches_despite_formatting_differences():
    """OCR and the model reformat descriptors; the check is on the folded name."""
    fields, low, _ = _parties(["RAM  KUMAR"], ["Ram Kumar"])
    assert "petitioners" not in fields and "respondents" not in fields
    assert "parties__role_conflict" in low


def test_no_conflict_leaves_both_lists_intact():
    fields, low, warnings = _parties(["Ram Kumar"], ["State of U.P."])
    assert fields["petitioners"]["value"] == ["Ram Kumar"]
    assert fields["respondents"]["value"] == ["State of U.P."]
    assert "parties__role_conflict" not in low
    assert warnings == []


# ── conflict: the same document uploaded more than once ──────────────────────

def test_dedupe_collapses_identical_content():
    docs = [{"id": 26 + i, "doc_type": "Lower Court Judgment",
             "original_filename": "judge abc.pdf", "ocr_text": "SAME TEXT " * 40}
            for i in range(5)]
    assert [d["id"] for d in dedupe_docs(docs)] == [26]


def test_dedupe_is_content_keyed_not_filename_keyed():
    """The same order saved under two names is still one document."""
    body = "IN THE COURT OF SESSIONS JUDGE " * 20
    docs = [
        {"id": 1, "doc_type": "Impugned Order", "original_filename": "order.pdf", "ocr_text": body},
        {"id": 2, "doc_type": "Annexure P-1", "original_filename": "copy.pdf", "ocr_text": body},
    ]
    assert [d["id"] for d in dedupe_docs(docs)] == [1]


def test_dedupe_ignores_whitespace_only_differences():
    docs = [
        {"id": 1, "ocr_text": "Bail Application No. 456 of 2026"},
        {"id": 2, "ocr_text": "Bail   Application    No. 456 of 2026\n\n"},
    ]
    assert [d["id"] for d in dedupe_docs(docs)] == [1]


def test_dedupe_keeps_genuinely_different_documents():
    docs = [
        {"id": 1, "ocr_text": "Bail Application No. 456 of 2026"},
        {"id": 2, "ocr_text": "FIR No. 187 of 2026"},
    ]
    assert [d["id"] for d in dedupe_docs(docs)] == [1, 2]


def test_dedupe_passes_through_non_string_ocr():
    docs = [{"id": 1, "ocr_text": None}, {"id": 2, "ocr_text": None}]
    assert len(dedupe_docs(docs)) == 2       # filtered later by is_usable_ocr


# ── relief skeleton (deterministic) ──────────────────────────────────────────
# base_rules.txt:69 reproduces relief_sought VERBATIM in the Prayer clause, so
# this text becomes the operative demand on the court. It is templated, never
# generated.

def test_relief_skeleton_per_document_type():
    bail = build_relief_skeleton("bail_application",
                                 jurisdiction_value="FIR No. 187 of 2026, P.S. Kavi Nagar")
    assert "Release the applicant on bail" in bail
    assert "FIR No. 187 of 2026" in bail

    antic = build_relief_skeleton("anticipatory_bail",
                                  jurisdiction_value="FIR No. 187 of 2026")
    assert "in the event of arrest" in antic

    crim = build_relief_skeleton("criminal_appeal", impugned_order_date="2026-05-20",
                                 jurisdiction_value="Court of the Sessions Judge, Lucknow")
    assert "conviction and sentence" in crim and "acquit the appellant" in crim
    assert "Court of the Sessions Judge, Lucknow" in crim

    civil = build_relief_skeleton("civil_appeal", impugned_order_date="2026-05-20",
                                  jurisdiction_value="Civil Judge, Ghaziabad")
    assert "judgment and decree" in civil and "allow the appeal" in civil

    writ = build_relief_skeleton("writ_petition_civil", impugned_order_date="2026-05-20")
    assert "writ of certiorari" in writ


def test_relief_skeleton_uses_indian_date_format():
    """DD/MM/YYYY — the single date format the whole draft is written in."""
    out = build_relief_skeleton("writ_petition_civil", impugned_order_date="2026-05-20")
    assert "20/05/2026" in out
    assert "2026-05-20" not in out and "20.05.2026" not in out


def test_relief_skeleton_never_contains_a_placeholder():
    """Rule 11 copies this field verbatim into the Prayer; rule 5 forbids
    placeholders in the filed document. So the value must be clean."""
    for key in ("bail_application", "anticipatory_bail", "civil_appeal",
                "criminal_appeal", "writ_petition_civil", "writ_petition_criminal", ""):
        out = build_relief_skeleton(key, impugned_order_date="2026-05-20",
                                    jurisdiction_value="FIR No. 1 of 2026")
        assert out, key
        assert not re.search(r"\[|\]|_{4,}|\{|\}", out), (key, out)
        assert "None" not in out, (key, out)


def test_relief_skeleton_always_ends_with_residuary_clause():
    out = build_relief_skeleton("writ_petition_civil", impugned_order_date="2026-05-20")
    assert out.rstrip().endswith("in the interest of justice.")


@pytest.mark.parametrize("key", ["bail_application", "anticipatory_bail"])
def test_bail_skeleton_needs_the_fir_reference(key):
    assert build_relief_skeleton(key, impugned_order_date="2026-05-20") is None


@pytest.mark.parametrize("key", ["civil_appeal", "criminal_appeal",
                                 "writ_petition_civil", "writ_petition_criminal"])
def test_order_based_skeleton_needs_the_date(key):
    assert build_relief_skeleton(key, jurisdiction_value="Some Court") is None


def test_appeal_skeleton_drops_the_court_clause_when_unknown():
    """Better a shorter true sentence than 'passed by None'."""
    out = build_relief_skeleton("criminal_appeal", impugned_order_date="2026-05-20")
    assert out is not None
    assert "passed by" not in out
    assert "20/05/2026" in out


def test_relief_skeleton_with_no_inputs_is_none():
    assert build_relief_skeleton("writ_petition_civil") is None
    assert build_relief_skeleton("") is None


# ── document tiers ───────────────────────────────────────────────────────────
# Feeding every upload to every field let a blank template pollute the cause
# title; feeding only the judgment lost the S/o · R/o particulars a cause title
# needs (a bail order often names a party with no address at all).

BOMBAY_TEMPLATE = (
    "IN THE HIGH COURT OF JUDICATURE AT BOMBAY\nAPPEAL NO. _____ OF 2026\n"
    "[Petitioner] [Parentage/Details], [Address]\nversus\n[Respondent] [Details]\n"
) * 3

REAL_ORDER = (
    "IN THE COURT OF SESSIONS JUDGE, LUCKNOW\nBail Application No. 456 of 2026\n"
    "Amit Kumar ...Applicant\nVersus\nState of U.P. ...Opposite Party\n"
    "Order dated 20/05/2026 rejecting the application.\n"
) * 3

AADHAAR = "Government of India\nShashank Kumar Pathak\nS/o Ram Pathak\nDOB: 04/10/2004\nR/o 12 Nehru Marg, Jaipur\n" * 3


def test_blank_template_is_detected():
    assert looks_like_template(BOMBAY_TEMPLATE)
    assert not looks_like_template(REAL_ORDER)
    assert not looks_like_template(AADHAAR)


def test_real_order_with_a_signature_blank_is_not_a_template():
    """Orders legitimately contain a few '_____' signature lines."""
    assert not looks_like_template(REAL_ORDER + "\n_________\nSessions Judge\n")


def test_tier_classification():
    assert classify_doc_tier({"doc_type": "Lower Court Judgment", "ocr_text": REAL_ORDER}) == TIER_PRIMARY
    assert classify_doc_tier({"doc_type": "Impugned order (if any)", "ocr_text": REAL_ORDER}) == TIER_PRIMARY
    assert classify_doc_tier(
        {"doc_type": "Identity/Address Proof of Petitioner", "ocr_text": AADHAAR}) == TIER_SUPPORTING
    # Generic checklist slot holding a blank template -> excluded
    assert classify_doc_tier(
        {"doc_type": "Documents specific to the subject-matter", "ocr_text": BOMBAY_TEMPLATE}) == TIER_EXCLUDED
    # Generic slot with real case content -> promoted to primary on content
    assert classify_doc_tier(
        {"doc_type": "Documents specific to the subject-matter", "ocr_text": REAL_ORDER}) == TIER_PRIMARY
    # Generic slot with no case content at all -> excluded
    assert classify_doc_tier(
        {"doc_type": "Misc", "ocr_text": "Our product helps lawyers draft faster. " * 20}) == TIER_EXCLUDED


def test_excluded_docs_never_reach_the_prompt():
    used, block = _budget_docs([
        {"id": 1, "doc_type": "Lower Court Judgment", "original_filename": "o.pdf", "ocr_text": REAL_ORDER},
        {"id": 2, "doc_type": "Documents specific to the subject-matter",
         "original_filename": "template.pdf", "ocr_text": BOMBAY_TEMPLATE},
    ])
    assert [d["id"] for d in used] == [1]
    assert "[Petitioner]" not in block


def test_block_separates_primary_from_supporting():
    used, block = _budget_docs([
        {"id": 11, "doc_type": "Identity/Address Proof of Petitioner",
         "original_filename": "aadhaar.jpg", "ocr_text": AADHAAR},
        {"id": 26, "doc_type": "Lower Court Judgment", "original_filename": "o.pdf", "ocr_text": REAL_ORDER},
    ])
    # Primary is listed first regardless of input order.
    assert [d["id"] for d in used] == [26, 11]
    assert [d["tier"] for d in used] == [TIER_PRIMARY, TIER_SUPPORTING]
    assert "PRIMARY DOCUMENTS" in block and "SUPPORTING DOCUMENTS" in block
    assert block.index("PRIMARY DOCUMENTS") < block.index("SUPPORTING DOCUMENTS")


def test_fallback_promotes_best_document_when_no_judgment_uploaded():
    """No order/judgment/FIR present — extract from the next-best document rather
    than returning nothing."""
    used, block = _budget_docs([
        {"id": 11, "doc_type": "Identity/Address Proof of Petitioner",
         "original_filename": "a.jpg", "ocr_text": AADHAAR + "versus State of U.P. Petitioner"},
    ])
    assert len(used) == 1
    assert used[0]["tier"] == TIER_PRIMARY          # promoted
    assert "PRIMARY DOCUMENTS" in block


def test_supporting_only_upload_extracts_nothing():
    """A bare identity proof cannot establish a matter, and supporting documents
    may only complete a party already named in a primary one — so there is
    nothing to extract and no LLM call worth making."""
    used, block = _budget_docs([
        {"id": 11, "doc_type": "Identity/Address Proof", "original_filename": "a.jpg",
         "ocr_text": AADHAAR},
    ])
    assert used == [] and block == ""


def test_supporting_docs_are_capped():
    docs = [{"id": 1, "doc_type": "Lower Court Judgment", "original_filename": "o.pdf",
             "ocr_text": REAL_ORDER}]
    docs += [{"id": 100 + i, "doc_type": "Identity/Address Proof",
              "original_filename": f"id{i}.jpg", "ocr_text": f"[ID-{i}] " + AADHAAR}
             for i in range(6)]
    used, _ = _budget_docs(docs)
    assert sum(1 for d in used if d["tier"] == TIER_SUPPORTING) == MAX_SUPPORTING_DOCS


def test_budget_dedupes_before_spending_the_allowance():
    docs = [{"id": 26 + i, "doc_type": "Lower Court Judgment",
             "original_filename": "judge abc.pdf", "ocr_text": "x" * 3000}
            for i in range(5)]
    used, block = _budget_docs(docs)
    assert len(used) == 1
    assert block.count("=== DOC ") == 1     # extraction.py's own label format
