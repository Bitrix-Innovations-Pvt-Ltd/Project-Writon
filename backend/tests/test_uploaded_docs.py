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
    docs = [_doc(i, "x" * 40_000) for i in range(20)]
    block, used = build_uploaded_docs_context(docs)
    assert len(used) <= MAX_DOCS
    assert sum(u["chars_used"] for u in used) <= TOTAL_CHARS


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
