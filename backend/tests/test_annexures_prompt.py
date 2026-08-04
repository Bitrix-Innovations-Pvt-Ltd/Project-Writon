"""
The ANNEXURES instruction in base_rules.txt.

Regression guarded here: the rule used to state both cases in one sentence —
how to list uploaded documents, AND the exact fallback line to use when none
were uploaded. With a real document in the prompt the model still copied the
fallback verbatim, so a draft with an uploaded Lower Court Judgment came out as:

    Annexure No. 1 — Certified copy of the impugned order/relevant document.

Giving a model a quotable sentence invites it to quote the sentence. The rule is
now branched on has_uploads, so the fallback text is not present in the prompt
at all when documents exist.
"""

from app.core.rag import assemble_prompt

FALLBACK = "Certified copy of the impugned order/relevant document"

FORM = {
    "document_type": "Writ Petition (Civil)",
    "document_type_key": "writ_petition_civil",
    "court_display": "Allahabad High Court - Lucknow",
    "subject_matter": "Service Law",
    "petitioners": ["Ram Kumar Verma"],
    "respondents": ["State of U.P."],
    "facts_of_case": "Facts",
    "grounds": "",
    "relief_sought": "Relief",
    "mandatory_paragraphs": "",
    "dates_and_events": [],
}

DOCS_BLOCK = (
    "\n\n--- UPLOADED DOCUMENTS ---\n"
    '=== DOCUMENT 1: "Lower Court Judgment" (file: judgment.pdf) ===\n'
    "U.P. STATE PUBLIC SERVICES TRIBUNAL, LUCKNOW BENCH\n"
    "=== END DOCUMENT 1 ==="
)


def _prompt(uploaded_docs_context=""):
    return assemble_prompt(FORM, [], [], uploaded_docs_context=uploaded_docs_context)


def test_fallback_line_is_absent_when_documents_were_uploaded():
    """The core fix: the model cannot copy a sentence it never sees."""
    assert FALLBACK not in _prompt(DOCS_BLOCK)


def test_fallback_line_is_present_when_nothing_was_uploaded():
    prompt = _prompt("")
    assert FALLBACK in prompt
    assert "no documents were uploaded" in prompt


def test_uploaded_branch_points_at_the_precomputed_list():
    prompt = _prompt(DOCS_BLOCK)
    assert "ANNEXURE LIST" in prompt
    assert "Reproduce that list VERBATIM" in prompt
    assert "Add nothing, drop nothing, renumber nothing" in prompt


def test_uploaded_branch_forbids_a_generic_catch_all_entry():
    prompt = _prompt(DOCS_BLOCK)
    assert "Do NOT substitute a generic entry" in prompt


def test_only_one_annexure_rule_reaches_the_model():
    """Both branches must never render together, or the model gets contradictory
    instructions and picks whichever it likes."""
    for ctx in (DOCS_BLOCK, ""):
        assert _prompt(ctx).count("For the List of Annexures") == 1


def test_no_fabrication_instruction_survives_in_both_branches():
    assert "do NOT invent an annexure that is not on that list" in _prompt(DOCS_BLOCK)
    assert "Do NOT invent any further annexure" in _prompt("")


# ── The precomputed list ─────────────────────────────────────────────────────
# We already know which documents were filed and what each is called, so the
# model reproduces a list rather than composing one — the same treatment the
# DATES AND EVENTS table already gets.

import pytest

from app.core.uploaded_docs import build_uploaded_docs_context


def _docs(*specs):
    # No square brackets in the text: build_uploaded_docs_context drops anything
    # that looks like a blank pleading template, and a "[DOC-1]" prefix repeated
    # 30 times reads exactly like one.
    return [
        {"id": i, "doc_type": t, "original_filename": f"{i}.pdf",
         "ocr_text": f"DOC{i} IN THE COURT OF JUDICATURE, order dated 01.01.2026. " * 30}
        for i, t in enumerate(specs, start=1)
    ]


def test_annexure_list_is_generated_from_the_actual_documents():
    block, used = build_uploaded_docs_context(
        _docs("Impugned Order", "Lower Court Judgment", "Vakalatnama"))
    assert "--- ANNEXURE LIST" in block
    for n, u in enumerate(used, start=1):
        assert f"**Annexure No. {n}** — The photo/type copy of {u['label']} dated __/__/____" in block


def test_annexure_numbering_matches_document_order():
    block, used = build_uploaded_docs_context(_docs("Impugned Order", "Vakalatnama"))
    tail = block[block.index("--- ANNEXURE LIST"):]
    assert tail.index("Annexure No. 1") < tail.index("Annexure No. 2")
    # Document order and annexure order must agree, or the list mislabels files.
    assert tail.index(used[0]["label"]) < tail.index(used[1]["label"])


def test_annexure_dates_are_left_blank():
    """A document's own date is not reliably recoverable from OCR, and a wrong
    date on an annexure is worse than a blank one."""
    block, _ = build_uploaded_docs_context(_docs("Impugned Order"))
    tail = block[block.index("--- ANNEXURE LIST"):]
    assert "dated __/__/____" in tail


def test_no_annexure_list_when_nothing_usable():
    assert build_uploaded_docs_context([]) == ("", [])


@pytest.mark.parametrize("doc_type_key", [
    "writ_petition", "writ_petition_civil", "writ_petition_criminal",
    "bail_application", "anticipatory_bail", "civil_appeal", "criminal_appeal",
])
def test_every_template_renders_both_branches(doc_type_key):
    """base_rules.txt is included by all seven templates, so an unbalanced Jinja
    tag in the annexure rule breaks every document type at once."""
    form = dict(FORM, document_type_key=doc_type_key)
    for ctx in (DOCS_BLOCK, ""):
        out = assemble_prompt(form, [], [], uploaded_docs_context=ctx)
        assert "For the List of Annexures" in out
        assert "{%" not in out          # no unrendered Jinja left behind
