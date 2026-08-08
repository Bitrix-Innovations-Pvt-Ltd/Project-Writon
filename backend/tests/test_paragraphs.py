"""Unit tests for core/paragraphs.py — deterministic paragraph reconstruction.

Fixtures imitate the real corpus: scanned Supreme Court Reports with margin
letters A-H, running headers repeated mid-paragraph, hyphenated line breaks and
OCR digit noise. Every assertion about a paragraph *number* checks that the
number is one actually printed in the fixture — the module must never invent one.
"""

from app.core.paragraphs import (
    Paragraph,
    clean_ocr,
    find_markers,
    locate_chunk,
    paragraphs_for_span,
    segment,
    segment_window,
    _gap_fill,
    _lis_spine,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
SCR_OCR = """A
[2024] 11 S.C.R. 318
Digital Supreme Court Reports
1. This appeal arises out of the judgment of the High Court
of Judicature at Allahabad dated 12/03/2019, whereby the
peti-
tion filed by the appellant was dismissed.
B
2. The facts giving rise to this appeal lie in a narrow com-
pass. The appellant was appointed in the year 1998.
3. Having heard both sides, the three primary issues
identified were:- (a) inordinate delay; (b) non-supply of
working drawings; and (c) delay in supply of materials.
C
[2024] 11 S.C.R. 319
4. It is further submitted that the Hon'ble Supreme Court
has repeatedly emphasised this issue in our society.
5. In the result, the appeal is allowed and the impugned
order dated 12/03/2019 is set aside. No order as to costs.
"""

# Paragraph 3 is deliberately absent from the easy scan: the marker sits after a
# quotation mark, which the strict pattern skips. gap_fill must recover it.
GAP_OCR = (
    "1. The first submission is recorded. "
    "2. The second submission is recorded and the Court observed as under: "
    '"the principle is well settled" 3. The third submission follows the quote. '
    "4. The fourth submission concludes the matter."
)

NOISY_YEARS = (
    "1. The appellant relies on the Dowry Prohibition Act, 1961. "
    "The Partnership Act, 1932. Section 498A applies here. "
    "2. The respondent disputes that submission entirely. "
    "3. The Court has considered both contentions carefully."
)

# Cause title, counsel list and headnote before the first numbered paragraph.
# Measured at a median 18.8% of a real judgment, and ~19% of retrieved chunks
# land here — the source prints no paragraph number for any of it.
WITH_FRONT_MATTER = """ATMA SINGH
v.
GURMEJ KAUR (D) & ORS.
(Civil Appeal No. 11094 of 2017)
[A.K. SIKRI AND ASHOK BHUSHAN, JJ.]
Hindu Succession Act, 1956: s.8 - Intestate succession - By the mother -
To the estate of her deceased son - Permissibility - Held: The mother being
the sole class I heir would naturally succeed to the estate.
1. Leave granted. This appeal is directed against the judgment of the High
Court dated 12/03/2019.
2. The short question that arises for consideration is whether the mother
succeeds to the estate of her deceased son.
3. Having considered the rival submissions, we find no merit in the appeal.
"""

UNNUMBERED = (
    "The appellant challenges the order of the High Court. "
    "The respondent supports the impugned order. "
    "Having heard learned counsel, we are of the view that the appeal fails."
)


# ---------------------------------------------------------------------------
# clean_ocr
# ---------------------------------------------------------------------------
def test_clean_ocr_strips_running_headers_and_margin_letters():
    flat = clean_ocr(SCR_OCR)
    assert "S.C.R." not in flat
    assert "Digital Supreme Court Reports" not in flat
    # margin letters must not survive as stray tokens between sentences
    assert " B 2." not in flat
    assert " C " not in flat


def test_clean_ocr_dehyphenates_across_line_breaks():
    flat = clean_ocr(SCR_OCR)
    assert "petition filed by the appellant" in flat
    assert "narrow compass" in flat
    assert "peti- tion" not in flat


def test_clean_ocr_reflows_into_single_line():
    flat = clean_ocr(SCR_OCR)
    assert "\n" not in flat
    assert "  " not in flat


def test_clean_ocr_preserves_wording_verbatim():
    """Cleanup may delete page furniture but must never alter a word."""
    flat = clean_ocr(SCR_OCR)
    assert "inordinate delay" in flat
    assert "No order as to costs." in flat
    assert "dated 12/03/2019" in flat


def test_clean_ocr_handles_empty_input():
    assert clean_ocr("") == ""
    assert clean_ocr(None) == ""


# ---------------------------------------------------------------------------
# Marker detection and spine
# ---------------------------------------------------------------------------
def test_find_markers_locates_printed_numbers():
    numbers = [n for n, _ in find_markers(clean_ocr(SCR_OCR))]
    assert numbers[:5] == [1, 2, 3, 4, 5]


def test_find_markers_ignores_decimal_and_lowercase_continuations():
    flat = "1. The sum of Rs. 5. was paid. 2. The balance remains due."
    numbers = [n for n, _ in find_markers(flat)]
    assert numbers == [1, 2]


def test_lis_spine_discards_year_noise():
    """Years like 1961/1932 are numerically out of order and must be dropped."""
    candidates = find_markers(NOISY_YEARS)
    spine = _lis_spine(candidates)
    numbers = [n for n, _ in spine]
    assert numbers == [1, 2, 3]
    assert 1961 not in numbers and 1932 not in numbers


def test_lis_spine_empty_input():
    assert _lis_spine([]) == []


def test_gap_fill_recovers_missing_marker():
    flat = clean_ocr(GAP_OCR)
    spine = _lis_spine(find_markers(flat))
    filled = _gap_fill(flat, spine)
    numbers = [n for n, _ in filled]
    assert numbers == [1, 2, 3, 4]
    # and the recovered marker must point at real text, not a guessed offset
    offset = dict((n, o) for n, o in filled)[3]
    assert flat[offset:offset + 2] == "3."


def test_gap_fill_keeps_offsets_ascending():
    flat = clean_ocr(GAP_OCR)
    filled = _gap_fill(flat, _lis_spine(find_markers(flat)))
    offsets = [o for _, o in filled]
    assert offsets == sorted(offsets)


# ---------------------------------------------------------------------------
# segment
# ---------------------------------------------------------------------------
def test_segment_returns_numbered_paragraphs():
    result = segment(SCR_OCR)
    assert result.coverage == "full"
    assert [p.number for p in result.paragraphs] == [1, 2, 3, 4, 5]


def test_segment_paragraph_text_is_whole_and_verbatim():
    result = segment(SCR_OCR)
    para2 = next(p for p in result.paragraphs if p.number == 2)
    # starts at its own marker, not mid-sentence, and runs to the next paragraph
    assert para2.text.startswith("2. The facts giving rise to this appeal")
    assert para2.text.rstrip().endswith("appointed in the year 1998.")
    assert "3." not in para2.text


def test_segment_last_paragraph_runs_to_end():
    result = segment(SCR_OCR)
    last = result.paragraphs[-1]
    assert last.number == 5
    assert last.text.rstrip().endswith("No order as to costs.")


def test_segment_reports_consecutive_rate():
    assert segment(SCR_OCR).consecutive_rate == 1.0


def test_segment_marks_every_number_as_observed():
    """No number may be interpolated — all must come from a real marker."""
    result = segment(SCR_OCR)
    assert all(p.marker_observed for p in result.paragraphs)
    for para in result.paragraphs:
        assert result.flat_text[para.char_start:para.char_start + 2] == f"{para.number}."


def test_segment_labels_lost_marker_as_a_range():
    """When the OCR drops a marker the block holds two paragraphs.

    It must be labelled "2-3", never plain "2" — mislabelling would attribute
    half the text to the wrong paragraph of the judgment.
    """
    # No "3." anywhere: the digit is gone, exactly as seen in the corpus.
    lost = (
        "1. The first submission is recorded here. "
        "2. The second submission runs on. And this sentence really belongs to "
        "the third paragraph but its marker was lost by the scanner. "
        "4. The fourth submission concludes."
    )
    result = segment(lost)
    para2 = next(p for p in result.paragraphs if p.number == 2)
    assert para2.number_end == 3
    assert para2.number_uncertain is True
    assert para2.label == "2-3"


def test_segment_certain_paragraphs_are_not_marked_uncertain():
    result = segment(SCR_OCR)
    assert all(not p.number_uncertain for p in result.paragraphs)
    assert [p.label for p in result.paragraphs] == ["1", "2", "3", "4", "5"]


def test_paragraph_to_dict_exposes_label_and_uncertainty():
    para = next(p for p in segment(SCR_OCR).paragraphs if p.number == 3)
    data = para.to_dict()
    assert data["para_number"] == 3
    assert data["label"] == "3"
    assert data["number_uncertain"] is False
    assert data["marker_observed"] is True


# ---------------------------------------------------------------------------
# Front matter
# ---------------------------------------------------------------------------
def test_classify_span_detects_front_matter():
    """Headnote/cause-title chunks carry no printed number — ~19% of chunks."""
    result = segment(WITH_FRONT_MATTER)
    assert result.front_matter_end > 0
    assert result.classify_span((0, result.front_matter_end - 1)) == "front_matter"


def test_front_matter_is_excluded_from_paragraphs():
    """The headnote must never be offered as a numbered paragraph."""
    result = segment(WITH_FRONT_MATTER)
    assert result.paragraphs[0].number == 1
    assert "ATMA SINGH" not in result.paragraphs[0].text
    assert "Hindu Succession Act" not in result.paragraphs[0].text


def test_classify_span_detects_body():
    result = segment(WITH_FRONT_MATTER)
    para = result.paragraphs[1]
    assert result.classify_span((para.char_start + 5, para.char_end - 5)) == "body"


def test_classify_span_without_paragraphs_is_front_matter():
    assert segment(UNNUMBERED).classify_span((0, 50)) == "front_matter"


def test_segment_unnumbered_judgment_yields_no_coverage():
    result = segment(UNNUMBERED)
    assert result.coverage == "none"
    assert result.paragraphs == []


def test_segment_empty_input():
    result = segment("")
    assert result.coverage == "none"
    assert result.paragraphs == []


def test_segment_flags_suspiciously_long_paragraph():
    merged = "1. " + ("The submission is repeated at length. " * 120) + "2. Short."
    result = segment(merged + " 3. Another short one. 4. And a fourth.")
    para1 = next(p for p in result.paragraphs if p.number == 1)
    assert para1.suspect_merge is True


# ---------------------------------------------------------------------------
# locate_chunk
# ---------------------------------------------------------------------------
def test_locate_chunk_exact_match():
    flat = clean_ocr(SCR_OCR)
    chunk = flat[100:400]
    start, end = locate_chunk(flat, chunk)
    assert (start, end) == (100, 400)


def test_locate_chunk_canonical_match_when_punctuation_differs():
    """Curly quotes and spacing differ between chunk_text and full_text."""
    flat = clean_ocr(SCR_OCR)
    chunk = flat[120:420].replace("'", "’").replace(" ", "  ")
    start, end = locate_chunk(flat, chunk)
    assert abs(start - 120) < 60
    assert end > start


def test_locate_chunk_arithmetic_fallback():
    """Tier 3 must still return a plausible span for unmatchable text."""
    flat = clean_ocr(SCR_OCR)
    lengths = [200, 200, 200, 200]
    start, end = locate_chunk(
        flat, "text that appears nowhere in the judgment at all",
        chunk_index=2, sibling_lengths=lengths,
    )
    assert 0 <= start < end <= len(flat)
    # chunk 2 of 4 should land in the second half
    assert start >= len(flat) * 0.4


def test_locate_chunk_empty_inputs():
    assert locate_chunk("", "anything") == (0, 0)
    assert locate_chunk("some text", "") == (0, 0)


# ---------------------------------------------------------------------------
# paragraphs_for_span
# ---------------------------------------------------------------------------
def _paras():
    return [
        Paragraph(number=1, text="a", char_start=0, char_end=1000),
        Paragraph(number=2, text="b", char_start=1000, char_end=2000),
        Paragraph(number=3, text="c", char_start=2000, char_end=3000),
    ]


def test_paragraphs_for_span_single_paragraph():
    assert paragraphs_for_span(_paras(), (1100, 1800)) == [2]


def test_paragraphs_for_span_straddling_two():
    """Both paragraphs are covered well beyond the incidental-graze threshold."""
    assert paragraphs_for_span(_paras(), (700, 1600)) == [1, 2]


def test_paragraphs_for_span_shallow_overlap_is_dropped():
    """100 chars of a paragraph is below the 200-char slack — not a match."""
    assert paragraphs_for_span(_paras(), (900, 1600)) == [2]


def test_paragraphs_for_span_ignores_incidental_graze():
    """A 30-char spill into the next paragraph is not a match."""
    assert paragraphs_for_span(_paras(), (100, 1030)) == [1]


def test_paragraphs_for_span_empty_span():
    assert paragraphs_for_span(_paras(), (500, 500)) == []


# ---------------------------------------------------------------------------
# segment_window
# ---------------------------------------------------------------------------
def test_segment_window_marks_coverage_partial():
    chunks = [
        "1. The first paragraph of the window is here.",
        "2. The second paragraph continues the discussion.",
        "3. The third paragraph closes it out entirely.",
    ]
    result = segment_window(chunks, target_position=1)
    assert result.coverage == "partial"
    assert [p.number for p in result.paragraphs] == [1, 2, 3]
    assert result.stats["window_position"] == 1
