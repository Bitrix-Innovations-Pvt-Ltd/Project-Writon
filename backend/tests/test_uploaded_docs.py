"""
Unit tests for core/uploaded_docs.py — the UPLOADED DOCUMENTS block that goes
into the drafting prompt.

Pure function only; the DB lookup is covered by the end-to-end check.
"""

import pytest

from app.core.uploaded_docs import (
    MAX_DOCS,
    MIN_DOC_CHARS,
    MIN_PER_DOC_CHARS,
    TOTAL_CHARS,
    build_uploaded_docs_context,
)


def _doc(i, ocr, doc_type="Annexure", filename=None, unique=True):
    """Test document.

    `unique` prefixes the text with the id so fixtures are distinct — identical
    content is collapsed by dedupe_docs, which would make the budget assertions
    below pass vacuously on a single surviving document. Pass unique=False when
    the test is specifically about duplicate uploads.
    """
    return {
        "id": i,
        "doc_type": doc_type,
        "original_filename": filename or f"file{i}.pdf",
        "ocr_text": (f"[DOC-{i}] {ocr}" if unique else ocr),
    }


def test_empty_input_yields_empty_block():
    """base_rules.txt falls back to a generic ANNEXURES line when the block is
    absent, so '' must be returned rather than a bare header."""
    assert build_uploaded_docs_context([]) == ("", [])
    assert build_uploaded_docs_context(None) == ("", [])


def test_unusable_docs_yield_empty_block():
    block, used = build_uploaded_docs_context([
        _doc(1, "OCR Failed"),
        _doc(2, "tiny"),
        _doc(3, None),
    ])
    assert block == "" and used == []


def test_each_document_is_labelled_with_type_and_filename():
    """Without labels the model cannot build the ANNEXURES list, which
    base_rules.txt requires it to do from this block."""
    block, used = build_uploaded_docs_context([
        _doc(1, "x" * 500, doc_type="Impugned Order", filename="order.pdf"),
        _doc(2, "y" * 500, doc_type="Vakalatnama", filename="vak.pdf"),
    ])
    assert '=== DOCUMENT 1: "Impugned Order" (file: order.pdf) ===' in block
    assert '=== DOCUMENT 2: "Vakalatnama" (file: vak.pdf) ===' in block
    assert "=== END DOCUMENT 1 ===" in block and "=== END DOCUMENT 2 ===" in block
    assert [u["label"] for u in used] == ["Impugned Order", "Vakalatnama"]


def test_header_instructs_annexure_use():
    block, _ = build_uploaded_docs_context([_doc(1, "x" * 500)])
    assert "--- UPLOADED DOCUMENTS ---" in block
    assert "ANNEXURES" in block


def test_same_doc_type_twice_gets_distinguishable_labels():
    """Two files under one checklist type must not share a label — the model
    reports which document a value came from by label, and ANNEXURES lists them."""
    block, used = build_uploaded_docs_context([
        _doc(26, "x" * 500, doc_type="Lower Court Judgment", filename="judge abc.pdf"),
        _doc(32, "y" * 500, doc_type="Lower Court Judgment", filename="judge 3.pdf"),
    ])
    labels = [u["label"] for u in used]
    assert len(set(labels)) == 2, labels
    assert "judge abc.pdf" in labels[0] and "judge 3.pdf" in labels[1]


def test_unique_doc_type_keeps_a_clean_label():
    _, used = build_uploaded_docs_context([
        _doc(1, "x" * 500, doc_type="Impugned Order", filename="order.pdf"),
        _doc(2, "y" * 500, doc_type="Vakalatnama", filename="vak.pdf"),
    ])
    assert [u["label"] for u in used] == ["Impugned Order", "Vakalatnama"]


def test_falls_back_to_filename_then_index_for_label():
    block, used = build_uploaded_docs_context([
        {"id": 1, "doc_type": None, "original_filename": "scan.pdf", "ocr_text": "x" * 500},
    ])
    assert used[0]["label"] == "scan.pdf"


def test_impugned_order_survives_total_cap():
    """If the budget binds, the operative document must not be the one dropped."""
    docs = [_doc(i, "a" * 40_000, doc_type="Annexure P-%d" % i) for i in range(1, 6)]
    docs.append(_doc(99, "b" * 40_000, doc_type="Impugned Order", filename="order.pdf"))
    _, used = build_uploaded_docs_context(docs)
    assert used[0]["label"] == "Impugned Order"


def test_respects_total_and_doc_caps():
    """The caps bound what is NARRATED to the model, not what is annexed."""
    docs = [_doc(i, "x" * 40_000) for i in range(20)]
    block, used = build_uploaded_docs_context(docs)
    narrated = [u for u in used if u["narrated"]]
    assert len(narrated) <= MAX_DOCS
    assert sum(u["chars_used"] for u in used) <= TOTAL_CHARS


def test_every_filed_document_is_annexed():
    """MAX_DOCS is a prompt-budget guard, not a filing limit. A document the
    advocate filed must appear in ANNEXURES even when its text never reached the
    model — an annexure list that silently omits a filed document is wrong on
    the record, and the omission is invisible in the finished draft."""
    docs = [_doc(i, "x" * 40_000) for i in range(20)]
    _, used = build_uploaded_docs_context(docs)
    assert len(used) == 20
    assert sum(1 for u in used if not u["narrated"]) == 12


def test_thin_ocr_document_is_still_annexed():
    """A poor scan is still a filed document. Its text cannot be narrated, but
    dropping it from ANNEXURES loses it from the record entirely."""
    # unique=False on the thin one: the id prefix would push it back over
    # MIN_DOC_CHARS and it would be narrated after all.
    docs = [_doc(1, "y" * 4000, doc_type="Impugned Order"),
            _doc(2, "z" * (MIN_DOC_CHARS - 1), doc_type="Identity Proof",
                 unique=False)]
    _, used = build_uploaded_docs_context(docs)
    assert len(used) == 2
    thin = next(u for u in used if u["id"] == 2)
    assert thin["narrated"] is False
    assert thin["chars_used"] == 0


def test_long_document_keeps_head_and_tail():
    """The cause title is at the start; the operative date and sign-off are at
    the very end. A head-only slice would lose the latter."""
    text = "HEAD_MARKER" + ("x" * (TOTAL_CHARS + 20_000)) + "TAIL_MARKER"
    block, _ = build_uploaded_docs_context([_doc(1, text, doc_type="Order")])
    assert "HEAD_MARKER" in block
    assert "TAIL_MARKER" in block
    assert "middle of document omitted" in block


def test_single_document_gets_the_whole_budget():
    """A lone 200-page judgment should not be clipped to a fixed slice while
    most of the budget goes unused."""
    _, used = build_uploaded_docs_context([_doc(1, "x" * 400_000, doc_type="Impugned Order")])
    assert used[0]["chars_used"] > TOTAL_CHARS * 0.9


def test_allowance_shrinks_as_documents_are_added():
    one = build_uploaded_docs_context([_doc(1, "x" * 400_000)])[1][0]["chars_used"]
    four = build_uploaded_docs_context([_doc(i, "x" * 400_000) for i in range(4)])[1][0]["chars_used"]
    assert four < one
    assert four >= MIN_PER_DOC_CHARS


def test_each_document_allowance_never_below_floor():
    docs = [_doc(i, "x" * 400_000) for i in range(MAX_DOCS)]
    _, used = build_uploaded_docs_context(docs)
    assert all(u["chars_used"] >= MIN_PER_DOC_CHARS for u in used[:-1])


def test_short_document_is_not_clipped():
    block, _ = build_uploaded_docs_context([_doc(1, "SHORT_BODY " * 20)])
    assert "middle of document omitted" not in block
    assert "SHORT_BODY" in block


def test_reuploads_of_the_same_file_appear_once():
    """Real pattern in the data: the same judgment uploaded five times. Each copy
    would otherwise take a share of the budget and add an ANNEXURES entry."""
    docs = [_doc(26 + i, "IN THE COURT OF SESSIONS JUDGE, LUCKNOW " * 30,
                 doc_type="Lower Court Judgment", filename="judge abc.pdf", unique=False)
            for i in range(5)]
    block, used = build_uploaded_docs_context(docs)
    assert len(used) == 1
    assert block.count("=== DOCUMENT ") == 1


def test_dedupe_does_not_merge_different_matters():
    docs = [
        _doc(30, "Bail Application No. 456 of 2026, Sessions Judge Lucknow " * 10),
        _doc(32, "Anticipatory Bail No. 1142 of 2026, Sessions Judge Ghaziabad " * 10),
    ]
    _, used = build_uploaded_docs_context(docs)
    assert [u["id"] for u in used] == [30, 32]


def test_min_doc_chars_boundary():
    # unique=False: this measures raw length, so no id prefix may be added.
    assert build_uploaded_docs_context(
        [_doc(1, "x" * (MIN_DOC_CHARS - 1), unique=False)]) == ("", [])
    block, used = build_uploaded_docs_context(
        [_doc(1, "x" * (MIN_DOC_CHARS + 1), unique=False)])
    assert len(used) == 1


# ── Translated documents ─────────────────────────────────────────────────────
# A Hindi upload is translated at OCR time (core/language.py) and `ocr_text`
# holds the English. The model has to be told, or it will quote a machine
# translation as if it were the verbatim record.

def _translated(i, status="translated", ocr_lang="hi"):
    doc = _doc(i, "x" * 500, doc_type="Impugned Order", filename="order.pdf")
    doc["translation_status"] = status
    doc["ocr_lang"] = ocr_lang
    return doc


def _doc_headers(block):
    """The '=== DOCUMENT n: ... ===' lines only.

    The block header explains what the annotation means, so it contains the
    phrase too — a bare `in block` check would match that and pass vacuously.
    """
    return [ln for ln in block.splitlines() if ln.startswith("=== DOCUMENT ")]


def test_translated_document_is_annotated():
    block, _ = build_uploaded_docs_context([_translated(1)])
    assert _doc_headers(block) == [
        '=== DOCUMENT 1: "Impugned Order" (file: order.pdf) [translated from Hindi] ==='
    ]


def test_partial_translation_says_so():
    block, _ = build_uploaded_docs_context([_translated(1, status="partial")])
    assert "[translated from Hindi in part]" in _doc_headers(block)[0]


@pytest.mark.parametrize("status", ["not_needed", "disabled", "failed", "", None])
def test_untranslated_document_is_not_annotated(status):
    """These all mean the text is the original, so there is nothing to disclose."""
    block, _ = build_uploaded_docs_context([_translated(1, status=status)])
    assert "[translated from" not in _doc_headers(block)[0]


def test_legacy_rows_without_the_columns_are_not_annotated():
    """Rows predating the migration have neither key."""
    block, _ = build_uploaded_docs_context([_doc(1, "x" * 500)])
    assert "[translated from" not in _doc_headers(block)[0]


def test_header_warns_against_quoting_a_translation():
    block, _ = build_uploaded_docs_context([_translated(1)])
    assert "verbatim quotation" in block


def test_annotation_does_not_disturb_the_label():
    """unique_labels() and the ANNEXURES list key off the quoted label, which
    has to stay exactly what it was before the annotation was appended."""
    block, used = build_uploaded_docs_context([_translated(1)])
    assert used[0]["label"] == "Impugned Order"
    assert _doc_headers(block)[0].startswith('=== DOCUMENT 1: "Impugned Order" (file: order.pdf)')


# ── Upload-session isolation ─────────────────────────────────────────────────
# The session id is stored client-side under a key containing params.id, which
# is the literal "new" for every new draft. Two drafts created in one browser
# tab therefore share a session id. The SQL must not let the second draft see
# the first draft's documents: once uploads are back-linked to a draft they
# belong to that draft alone.

def _sql_of(fn):
    import inspect
    return inspect.getsource(fn)


def test_session_branch_requires_unclaimed_documents():
    """Guards the leak directly: the session-id branch must be constrained to
    rows whose draft_id IS NULL."""
    from app.core.uploaded_docs import fetch_uploaded_docs

    sql = _sql_of(fetch_uploaded_docs)
    # The session predicate and the NULL guard must appear together.
    assert "upload_session_id = CAST(:sid AS TEXT)" in sql
    session_clause_start = sql.index("upload_session_id = CAST(:sid AS TEXT)")
    tail = sql[session_clause_start:session_clause_start + 200]
    assert "draft_id IS NULL" in tail, (
        "the upload_session_id branch must require draft_id IS NULL, or a new "
        "draft in the same browser tab inherits the previous draft's uploads"
    )


def test_extract_fields_session_branch_also_guarded():
    """The same leak existed in the auto-populate query."""
    import inspect
    from app.api.v1 import uploads

    sql = inspect.getsource(uploads.extract_fields)
    assert "upload_session_id = :sid AND draft_id IS NULL" in sql
