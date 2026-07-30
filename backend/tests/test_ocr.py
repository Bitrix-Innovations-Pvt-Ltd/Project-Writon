"""
Unit tests for core/ocr.py PDF page handling.

PDFs are synthesised with PyMuPDF and the vision call is stubbed, so these run
offline with no OpenRouter spend.

The regression these guard: PDFs used to be capped at 5 pages, so page 6 onward
of every uploaded document was silently unavailable to citation retrieval, field
extraction and the drafting prompt.
"""

import re

import fitz
import pytest

import app.core.ocr as ocr


@pytest.fixture
def stub_vision(monkeypatch):
    """Replace the LLM vision call; records how many pages were sent."""
    calls = []

    def _fake(img_bytes, mime_type):
        calls.append(len(img_bytes))
        return f"VISION_TEXT_{len(calls)}"

    monkeypatch.setattr(ocr, "extract_text_with_llm", _fake)
    return calls


def _digital_pdf(n: int) -> bytes:
    """Pages carrying a real text layer — no vision call needed."""
    doc = fitz.open()
    for i in range(1, n + 1):
        doc.new_page().insert_text((72, 100), f"PAGE_MARKER_{i}")
    data = doc.tobytes()
    doc.close()
    return data


def _scanned_pdf(n: int) -> bytes:
    """Pages with no text layer — forces the vision path."""
    doc = fitz.open()
    for _ in range(n):
        doc.new_page().draw_rect(fitz.Rect(50, 50, 300, 200), fill=(0.9, 0.9, 0.9))
    data = doc.tobytes()
    doc.close()
    return data


def _page_markers(text: str) -> int:
    return len(re.findall(r"--- Page \d+ ---", text))


# ── digital text: no meaningful cap ──────────────────────────────────────────

def test_reads_far_beyond_the_old_five_page_cap():
    text = ocr.extract_text_from_bytes(_digital_pdf(40), "multi.pdf")
    for page in (1, 5, 6, 20, 40):
        assert f"PAGE_MARKER_{page}" in text, f"page {page} missing"
    assert _page_markers(text) == 40
    assert "[NOTE:" not in text          # nothing was dropped, so no notice


def test_digital_pages_need_no_vision_calls(stub_vision):
    ocr.extract_text_from_bytes(_digital_pdf(30), "multi.pdf")
    assert stub_vision == []


def test_single_page_pdf():
    text = ocr.extract_text_from_bytes(_digital_pdf(1), "one.pdf")
    assert "PAGE_MARKER_1" in text and _page_markers(text) == 1


# ── page cap ─────────────────────────────────────────────────────────────────

def test_page_cap_truncates_and_announces(monkeypatch):
    monkeypatch.setattr(ocr, "MAX_PDF_PAGES", 10)
    text = ocr.extract_text_from_bytes(_digital_pdf(14), "big.pdf")
    assert _page_markers(text) == 10
    assert "PAGE_MARKER_10" in text and "PAGE_MARKER_11" not in text
    assert "Only the first 10 of 14 pages were read" in text


# ── scanned pages: bounded vision spend ──────────────────────────────────────

def test_vision_budget_caps_llm_calls(monkeypatch, stub_vision):
    monkeypatch.setattr(ocr, "MAX_VISION_PAGES", 4)
    text = ocr.extract_text_from_bytes(_scanned_pdf(9), "scan.pdf")

    assert len(stub_vision) == 4                      # spend is bounded
    assert _page_markers(text) == 9                   # every page still represented
    assert text.count("[Scanned page not read") == 5  # the gap is explicit
    assert "5 scanned page(s) were not read by image OCR" in text


def test_scanned_pages_within_budget_are_all_read(monkeypatch, stub_vision):
    monkeypatch.setattr(ocr, "MAX_VISION_PAGES", 10)
    text = ocr.extract_text_from_bytes(_scanned_pdf(6), "scan.pdf")
    assert len(stub_vision) == 6
    assert "[Scanned page not read" not in text
    assert "[NOTE:" not in text


def test_skipped_page_numbers_are_listed(monkeypatch, stub_vision):
    monkeypatch.setattr(ocr, "MAX_VISION_PAGES", 2)
    text = ocr.extract_text_from_bytes(_scanned_pdf(5), "scan.pdf")
    assert "pages 3, 4, 5" in text


def test_long_skip_list_is_abbreviated(monkeypatch, stub_vision):
    monkeypatch.setattr(ocr, "MAX_VISION_PAGES", 0)
    text = ocr.extract_text_from_bytes(_scanned_pdf(15), "scan.pdf")
    assert "and 5 more" in text


def test_vision_zoom_is_applied(monkeypatch, stub_vision):
    """Rendering at 72 DPI makes scanned court orders barely legible; the zoom
    must actually reach get_pixmap, which shows up as a larger PNG."""
    monkeypatch.setattr(ocr, "VISION_ZOOM", 1.0)
    ocr.extract_text_from_bytes(_scanned_pdf(1), "a.pdf")
    small = stub_vision[-1]

    monkeypatch.setattr(ocr, "VISION_ZOOM", 2.0)
    ocr.extract_text_from_bytes(_scanned_pdf(1), "b.pdf")
    assert stub_vision[-1] > small


# ── downstream compatibility ─────────────────────────────────────────────────

def test_notices_are_not_mistaken_for_ocr_failure(monkeypatch, stub_vision):
    """core/extraction.py drops documents whose text looks like an OCR failure.
    The truncation notices must not trip that check."""
    from app.core.extraction import is_usable_ocr

    monkeypatch.setattr(ocr, "MAX_VISION_PAGES", 1)
    assert is_usable_ocr(ocr.extract_text_from_bytes(_scanned_pdf(8), "s.pdf"))

    monkeypatch.setattr(ocr, "MAX_PDF_PAGES", 3)
    assert is_usable_ocr(ocr.extract_text_from_bytes(_digital_pdf(9), "d.pdf"))


def test_corrupt_pdf_returns_failure_marker():
    text = ocr.extract_text_from_bytes(b"not a pdf at all", "broken.pdf")
    from app.core.extraction import is_usable_ocr
    assert not is_usable_ocr(text)


def test_unsupported_extension_unchanged():
    assert ocr.extract_text_from_bytes(b"x", "notes.txt") == "Unsupported file type for OCR."
