"""
core/paragraphs.py — deterministic paragraph reconstruction for judgments.

Step 6 retrieves *chunks*, not paragraphs. A chunk is an arbitrary ~1,750-char
slice: measured on the live corpus, 52% of them start mid-sentence, so quoting a
chunk verbatim in a draft produces a fragment that begins in the middle of a
sentence. This module rebuilds the whole numbered paragraph a chunk belongs to,
so the draft can quote it the way the image in the brief shows — "10. This Court
in the matter of ... has deprecated the practice of ..." — with the real
paragraph number the judgment printed.

Why the number is never produced by an LLM
------------------------------------------
Asking a model for the paragraph number was measured at 32-60% wrong or absent,
and a wrong paragraph number in a filed document is worse than no citation at
all. Instead the number is recovered deterministically from `judgments.full_text`:

  1. Scan for candidate "N." markers.
  2. Keep the longest increasing subsequence, scoring +1 steps highest. Paragraph
     numbers rise monotonically; OCR noise (years, footnote markers, section
     numbers, SCR page numbers) does not, so the LIS filters it out.
  3. Gap-fill: where the spine jumps 6 -> 8, search *only* the text between those
     two offsets for a literal "7.". Knowing which number to look for makes this
     pass high-precision.

Every number this module returns corresponds to a marker literally present in the
source text. Nothing is interpolated. Measured on 59 judgments (year >= 2015):
step (2) alone left 17% of judgments with a fully consecutive spine; step (3)
raised that to 92%.

Cost: 8 ms median per judgment (p90 30 ms), so segmentation runs on demand and
nothing is persisted — see the size guards below for the 2.9M-char outliers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Size guards. Segmentation is linear except the LIS, which is O(n^2) in the
# number of candidate markers. The five largest documents in the corpus
# (2.1-2.9M chars, ~900-1,170 markers) cost 750-1,083 ms — acceptable once, but
# not worth risking on a pathological document, so oversized inputs fall back to
# segmenting a window around the matched chunk instead of the whole judgment.
# ---------------------------------------------------------------------------
MAX_SEGMENT_CHARS = 300_000
MAX_MARKERS = 1_500

# A paragraph longer than this almost certainly means a marker was missed and two
# paragraphs got merged. Flagged rather than split — the UI warns instead of
# inventing a boundary.
SUSPECT_MERGE_CHARS = 3_000

SEGMENTER_VERSION = 1


# ---------------------------------------------------------------------------
# OCR cleanup
# ---------------------------------------------------------------------------
# The corpus is scanned Supreme Court Reports: two-column pages with margin
# letters A-H down the side, running headers repeated mid-paragraph, and line
# breaks that split sentences. Left alone, all three corrupt both the marker scan
# and the quoted text.
_RUNNING_HEADERS = [
    r"\[\d{4}\]\s*\d*\s*S\.?C\.?R\.?\s*\d*",
    r"Digital\s+Supreme\s+Court\s+Reports",
    r"SUPREME\s+COURT\s+REPORTS",
]

_RE_HEADERS = [re.compile(p, re.IGNORECASE) for p in _RUNNING_HEADERS]
_RE_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")
_RE_BACKSPACE = re.compile(r"\x08+")
_RE_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
_RE_MARGIN_LETTER_LINE = re.compile(r"(?m)^\s*[A-H]\s*$")
_RE_MARGIN_LETTER_INLINE = re.compile(r"(?<![A-Za-z])([A-H])\s+(?=[A-Z][a-z])")
_RE_LINE_BREAKS = re.compile(r"\s*\n\s*")
_RE_MULTI_SPACE = re.compile(r"\s{2,}")


def clean_ocr(raw: str) -> str:
    """Reflow raw judgment text into flowing paragraphs.

    Removes only page furniture — running headers, standalone page numbers,
    isolated margin letters — and rejoins lines. No word is altered, so text
    extracted from the result stays verbatim quotable.
    """
    if not raw:
        return ""

    text = _RE_BACKSPACE.sub(" ", raw)
    for pattern in _RE_HEADERS:
        text = pattern.sub(" ", text)
    text = _RE_PAGE_NUMBER_LINE.sub(" ", text)
    # De-hyphenate before collapsing newlines, or "juris-\ndiction" becomes
    # "juris- diction" and the word is unsearchable.
    text = _RE_HYPHEN_BREAK.sub(r"\1\2", text)
    text = _RE_MARGIN_LETTER_LINE.sub(" ", text)
    text = _RE_MARGIN_LETTER_INLINE.sub(" ", text)
    text = _RE_LINE_BREAKS.sub(" ", text)
    return _RE_MULTI_SPACE.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# Marker detection and spine recovery
# ---------------------------------------------------------------------------
# A paragraph marker is "N." following sentence-ending punctuation (or the very
# start of the text) and followed by a capital letter or an opening quote. The
# trailing lookahead is what rejects decimal figures, "Rs. 5." and list items
# that continue in lower case.
_RE_MARKER = re.compile(
    r"(?:(?<=[\.\:\?\!\”\"\)])\s+|^\s*)(\d{1,3})\.\s+(?=[A-Z“\"\(])"
)


def find_markers(flat: str) -> list[tuple[int, int]]:
    """Return every candidate ``(paragraph_number, offset)`` in cleaned text."""
    return [(int(m.group(1)), m.start(1)) for m in _RE_MARKER.finditer(flat)]


def _lis_spine(candidates: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Longest increasing subsequence over candidate markers.

    Consecutive steps score 2.0 and jumps score 1/step, so a run of 4,5,6,7 beats
    a scattered 4,19,204 of the same length. That preference is what discards
    years ("...Act, 1961. 2 The"), footnote markers and SCR page numbers, which
    are numerically out of order with respect to the real paragraph sequence.
    """
    n = len(candidates)
    if n == 0:
        return []

    score = [0.0] * n
    prev = [-1] * n
    for i in range(n):
        for j in range(i):
            if candidates[j][0] >= candidates[i][0]:
                continue
            step = candidates[i][0] - candidates[j][0]
            s = score[j] + (2.0 if step == 1 else 1.0 / step)
            if s > score[i]:
                score[i] = s
                prev[i] = j

    end = max(range(n), key=lambda i: score[i])
    out: list[tuple[int, int]] = []
    while end != -1:
        out.append(candidates[end])
        end = prev[end]
    return out[::-1]


# Relaxed pattern used only inside a known gap, where we already know which
# number we are looking for. Without that constraint this pattern would match far
# too much; with it, it recovered 307 markers across 59 judgments and took the
# fully-consecutive rate from 17% to 92%.
def _gap_fill(flat: str, spine: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Recover markers the LIS dropped, searching only between known offsets."""
    filled = list(spine)
    for (a_num, a_off), (b_num, b_off) in zip(spine, spine[1:]):
        if b_num - a_num <= 1:
            continue
        segment = flat[a_off:b_off]
        cursor = 0
        for missing in range(a_num + 1, b_num):
            # Inside a known gap we already know which number to look for, so the
            # lookahead only has to reject decimals ("3.1") by requiring
            # whitespace. Measured: recovers slightly more markers than an
            # uppercase-only lookahead with no increase in false short paragraphs.
            pattern = re.compile(rf"(?<![\d.]){missing}\.\s+(?=\S)")
            match = pattern.search(segment, cursor)
            if match:
                filled.append((missing, a_off + match.start()))
                cursor = match.end()

    filled.sort(key=lambda pair: pair[1])
    # Enforce monotonicity after the merge: a gap-filled marker that would break
    # the ascending order is a false positive, so drop it.
    out: list[tuple[int, int]] = []
    for num, off in filled:
        if not out or num > out[-1][0]:
            out.append((num, off))
    return out


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------
@dataclass
class Paragraph:
    number: int
    text: str
    char_start: int
    char_end: int
    # True whenever the number came from a marker found in the source. Currently
    # always True — kept so that if an interpolation mode is ever added, callers
    # can tell a printed number from a derived one instead of trusting silently.
    marker_observed: bool = True
    suspect_merge: bool = False
    # Set when the spine jumps (e.g. 5 -> 7) because the OCR lost the digit for
    # paragraph 6 entirely — verified on the corpus: the missing marker has zero
    # literal occurrences in the gap. This block therefore holds paragraphs 5 AND
    # 6, and labelling it plain "5" would attribute half the text to the wrong
    # paragraph. number_end records the true span so the UI can say "5-6".
    number_end: Optional[int] = None

    @property
    def number_uncertain(self) -> bool:
        return self.number_end is not None and self.number_end != self.number

    @property
    def label(self) -> str:
        """Human label for the paragraph number — "12" or "12-13"."""
        if self.number_uncertain:
            return f"{self.number}-{self.number_end}"
        return str(self.number)

    def to_dict(self) -> dict:
        return {
            "para_number": self.number,
            "para_number_end": self.number_end,
            "label": self.label,
            "number_uncertain": self.number_uncertain,
            "text": self.text,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "marker_observed": self.marker_observed,
            "suspect_merge": self.suspect_merge,
        }


@dataclass
class Segmentation:
    paragraphs: list[Paragraph]
    flat_text: str
    # "full"    — the whole judgment was segmented
    # "partial" — only a window around the matched chunk (oversized document)
    # "none"    — no usable paragraph numbering found in the source
    coverage: str = "full"
    consecutive_rate: float = 0.0
    stats: dict = field(default_factory=dict)

    @property
    def front_matter_end(self) -> int:
        """Offset where numbered paragraphs begin.

        Everything before it is the cause title, headnote and counsel list —
        measured at a median 18.8% of a judgment. Retrieval lands there for ~18%
        of chunks, and the source prints no paragraph number for any of it.
        """
        return self.paragraphs[0].char_start if self.paragraphs else 0

    def classify_span(self, span: tuple[int, int]) -> str:
        """Where a chunk sits: ``body`` | ``front_matter`` | ``after_body``."""
        start, end = span
        if not self.paragraphs:
            return "front_matter"
        if end <= self.front_matter_end:
            return "front_matter"
        if start >= self.paragraphs[-1].char_end:
            return "after_body"
        return "body"


def _build_paragraphs(flat: str, spine: list[tuple[int, int]]) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    for idx, (number, offset) in enumerate(spine):
        if idx + 1 < len(spine):
            next_number, end = spine[idx + 1][0], spine[idx + 1][1]
        else:
            next_number, end = None, len(flat)

        body = flat[offset:end].strip()
        if not body:
            continue

        # An unclosed gap means this block also contains the paragraphs whose
        # markers the OCR dropped, so record the real span rather than pretend
        # the block is a single numbered paragraph.
        number_end = None
        if next_number is not None and next_number > number + 1:
            number_end = next_number - 1

        paragraphs.append(
            Paragraph(
                number=number,
                text=body,
                char_start=offset,
                char_end=end,
                number_end=number_end,
                suspect_merge=len(body) > SUSPECT_MERGE_CHARS,
            )
        )
    return paragraphs


def _consecutive_rate(spine: Iterable[tuple[int, int]]) -> float:
    numbers = [n for n, _ in spine]
    steps = [b - a for a, b in zip(numbers, numbers[1:])]
    if not steps:
        return 0.0
    return sum(1 for s in steps if s == 1) / len(steps)


def segment(raw: str) -> Segmentation:
    """Segment a whole judgment into numbered paragraphs.

    Returns ``coverage="none"`` when the source carries no recoverable paragraph
    numbering — about 2% of the corpus, mostly pre-2000 scans. Callers must not
    fabricate a number in that case.
    """
    flat = clean_ocr(raw)
    if not flat:
        return Segmentation([], "", coverage="none")

    candidates = find_markers(flat)
    stats = {"candidates": len(candidates), "chars": len(flat)}

    if len(candidates) < 3:
        return Segmentation([], flat, coverage="none", stats=stats)
    if len(candidates) > MAX_MARKERS:
        # Guard, not a failure: the caller should retry with a window.
        return Segmentation([], flat, coverage="none", stats={**stats, "guard": "too_many_markers"})

    spine = _gap_fill(flat, _lis_spine(candidates))
    if len(spine) < 3:
        return Segmentation([], flat, coverage="none", stats=stats)

    return Segmentation(
        paragraphs=_build_paragraphs(flat, spine),
        flat_text=flat,
        coverage="full",
        consecutive_rate=_consecutive_rate(spine),
        stats={**stats, "spine": len(spine)},
    )


# ---------------------------------------------------------------------------
# Chunk -> paragraph mapping
# ---------------------------------------------------------------------------
# chunk_text is not reliably a verbatim substring of full_text: measured 11/50
# exact, 30/50 after whitespace normalisation. So locating a chunk is a three-tier
# fallback ending in an arithmetic estimate that cannot fail.
_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _canon(s: str) -> str:
    return _RE_NON_ALNUM.sub(" ", (s or "").lower()).strip()


def _canon_index(flat: str) -> tuple[str, list[int]]:
    """Canonical form of *flat* plus a map from canonical index -> flat index."""
    out_chars: list[str] = []
    mapping: list[int] = []
    prev_space = True
    for i, ch in enumerate(flat):
        c = ch.lower()
        if c.isalnum():
            out_chars.append(c)
            mapping.append(i)
            prev_space = False
        elif not prev_space:
            out_chars.append(" ")
            mapping.append(i)
            prev_space = True
    return "".join(out_chars), mapping


def locate_chunk_tiered(
    flat: str,
    chunk_text: str,
    chunk_index: Optional[int] = None,
    sibling_lengths: Optional[list[int]] = None,
) -> tuple[int, int, str]:
    """Locate *chunk_text* in *flat*, also reporting which tier resolved it.

    Tier 1: exact substring after cleaning.
    Tier 2: canonical (alphanumeric-only) match on an anchor from the chunk.
    Tier 3: arithmetic estimate. Chunks tile full_text at a measured ratio of
            1.00, so the offset of chunk *i* is the summed length of its
            predecessors, scaled to the cleaned text. Never fails, so a caller
            always gets a usable span.

    The tier is worth surfacing: a rising tier-3 rate means the chunk table and
    full_text have drifted apart, which would silently degrade paragraph
    attribution rather than error out.
    """
    cleaned_chunk = clean_ocr(chunk_text)
    if not cleaned_chunk or not flat:
        return (0, 0, "empty")

    # Tier 1 — exact
    pos = flat.find(cleaned_chunk)
    if pos >= 0:
        return (pos, pos + len(cleaned_chunk), "exact")

    # Tier 2 — canonical anchor. Take the anchor from the middle of the chunk:
    # chunk edges are where OCR noise and header bleed concentrate.
    canon_flat, mapping = _canon_index(flat)
    canon_chunk = _canon(cleaned_chunk)
    if canon_chunk:
        mid = max(0, len(canon_chunk) // 2 - 60)
        for anchor_len in (160, 100, 60):
            anchor = canon_chunk[mid:mid + anchor_len]
            if len(anchor) < 40:
                continue
            cpos = canon_flat.find(anchor)
            if cpos >= 0:
                start_canon = max(0, cpos - mid)
                end_canon = min(len(mapping) - 1, start_canon + len(canon_chunk))
                return (mapping[start_canon], mapping[end_canon], "canonical")

    # Tier 3 — arithmetic estimate
    if chunk_index is not None and sibling_lengths:
        preceding = sum(sibling_lengths[:chunk_index])
        total = sum(sibling_lengths) or 1
        scale = len(flat) / total
        start = int(preceding * scale)
        end = int((preceding + sibling_lengths[chunk_index]) * scale)
        start = max(0, min(start, len(flat)))
        end = max(start, min(end, len(flat)))
        return (start, end, "arithmetic")

    return (0, min(len(cleaned_chunk), len(flat)), "degenerate")


def locate_chunk(
    flat: str,
    chunk_text: str,
    chunk_index: Optional[int] = None,
    sibling_lengths: Optional[list[int]] = None,
) -> tuple[int, int]:
    """Return the ``(start, end)`` span of *chunk_text* inside cleaned *flat*."""
    start, end, _ = locate_chunk_tiered(flat, chunk_text, chunk_index, sibling_lengths)
    return (start, end)


def paragraphs_for_span(
    paragraphs: list[Paragraph],
    span: tuple[int, int],
    boundary_slack: int = 200,
) -> list[int]:
    """Paragraph numbers overlapping *span*.

    ``boundary_slack`` suppresses neighbours the chunk only grazes: a chunk that
    ends 30 chars into the next paragraph matched that paragraph incidentally,
    not substantively.
    """
    start, end = span
    if end <= start:
        return []

    hits: list[int] = []
    for para in paragraphs:
        overlap = min(end, para.char_end) - max(start, para.char_start)
        if overlap <= 0:
            continue
        # Keep it when the chunk covers a real part of the paragraph, or the
        # paragraph covers a real part of the chunk.
        para_len = max(1, para.char_end - para.char_start)
        if overlap >= min(boundary_slack, para_len) or overlap >= (end - start) * 0.25:
            hits.append(para.number)
    return hits


# Words too common in judgments to discriminate between paragraphs. Scoring on
# them ranks every paragraph equally, which is the failure mode the judgment
# OR-fallback hit in rag.py (generic terms matched 98.7% of the corpus).
_RANK_STOPWORDS = {
    "the", "of", "and", "to", "in", "a", "is", "that", "for", "it", "as", "on",
    "with", "was", "by", "be", "this", "which", "or", "an", "are", "has", "have",
    "not", "been", "from", "at", "any", "under", "shall", "would", "may", "such",
    "court", "case", "said", "learned", "counsel", "appellant", "respondent",
    "petitioner", "judgment", "order", "hon", "ble", "held", "section", "act",
}


def rank_paragraphs_by_query(
    paragraphs: list[Paragraph],
    query: str,
    top_k: int = 5,
) -> list[int]:
    """Paragraph numbers most relevant to *query*, best first.

    Used when retrieval gives no chunk to anchor to — a judgment that surfaced on
    BM25 alone has no passage reference, and listing all 112 paragraphs
    unranked leaves the advocate to find the relevant one by hand.

    Deliberately a cheap term-overlap score, not an embedding: the paragraphs are
    already in memory, so this costs nothing, and it only has to order paragraphs
    within a single judgment that retrieval has already judged relevant.
    """
    terms = {
        t for t in _RE_NON_ALNUM.sub(" ", (query or "").lower()).split()
        if len(t) > 3 and t not in _RANK_STOPWORDS
    }
    if not terms or not paragraphs:
        return []

    scored: list[tuple[float, int]] = []
    for para in paragraphs:
        words = _RE_NON_ALNUM.sub(" ", para.text.lower()).split()
        if not words:
            continue
        hits = sum(1 for w in set(words) if w in terms)
        if not hits:
            continue
        # Normalise by length so a long paragraph does not win on volume alone,
        # but keep a floor so a one-line paragraph with one hit cannot top the list.
        scored.append((hits / (1 + len(words) / 400), para.number))

    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [number for _, number in scored[:top_k]]


def segment_window(
    chunk_texts: list[str],
    target_position: int,
) -> Segmentation:
    """Segment only a window of neighbouring chunks.

    Used when a judgment is too large to segment whole. The paragraph numbers
    still come from markers found in the window, so they remain source-observed;
    only ``coverage`` degrades to "partial" because paragraphs outside the window
    are unknown.
    """
    joined = "\n".join(chunk_texts)
    result = segment(joined)
    if result.paragraphs:
        result.coverage = "partial"
    result.stats["window_position"] = target_position
    return result
