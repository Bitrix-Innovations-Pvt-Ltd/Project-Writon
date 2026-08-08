"""
core/paragraph_service.py — assembles the paragraph picker payload for Step 6.

Given a judgment and the chunk that retrieval matched, this returns the whole
numbered paragraphs behind that match, so the advocate can tick the ones to quote
verbatim in the Grounds instead of getting a chunk that starts mid-sentence.

Nothing is persisted. Segmentation costs 8 ms median (p90 21 ms) against a 63 ms
warm fetch of full_text, so a `judgment_paragraphs` table would have duplicated
~1.4 GB of `judgments.full_text` to save under 100 ms — and this Neon compute has
only ~233 MB of shared_buffers to begin with. Redis caches the assembled result
because the optional OCR cleanup costs 1-2 s, not because segmentation is slow.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import re
import time
from typing import Optional

from app.core.paragraphs import (
    MAX_SEGMENT_CHARS,
    SEGMENTER_VERSION,
    Paragraph,
    Segmentation,
    locate_chunk_tiered,
    paragraphs_for_span,
    segment,
    segment_window,
)
from app.core.redis import cache_get, cache_set

# Neighbouring chunks pulled for the windowed fallback on oversized judgments.
# +/-1 was measured best: a paragraph is smaller than one ~1,750-char chunk, so
# +/-5 tripled the token cost and scored *worse* by adding distractor paragraphs.
WINDOW_RADIUS = 2

# Cleanup is cosmetic only. It never selects the paragraph and never supplies the
# number — both come from the deterministic segmenter.
#
# It is OFF for the picker list and ON at generation time. Measured: cleanup costs
# 2.4-7.1s while segmentation costs 8-20ms, so paying it on every expand made a
# click feel broken. clean_ocr() has already stripped the margin letters, running
# headers and line breaks, so the list text is perfectly readable without it —
# the LLM pass is a final polish, and it belongs where a few seconds disappear
# behind a 60s draft generation.
CLEANUP_MODEL = os.getenv("PARA_CLEANUP_MODEL", "openai/gpt-4o-mini")
CLEANUP_ENABLED = os.getenv("PARA_CLEANUP_ENABLED", "1") not in ("0", "false", "False")
CLEANUP_MIN_FIDELITY = 0.95
# Floor on how much of the paragraph survives. Stripping a running header from a
# short paragraph legitimately drops ~20% of its words, while a truncation keeps
# a small fraction — 0.6 separates the two comfortably.
CLEANUP_MIN_RETENTION = 0.6
CLEANUP_MAX_PARAS = 4
CLEANUP_TIMEOUT_S = 20

CACHE_TTL_SECONDS = 6 * 3600


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------
_SQL_JUDGMENT = """
    SELECT id, petitioner, respondent, case_number, year, full_text
    FROM   judgments
    WHERE  id = :jid
"""

# Only the LENGTHS are needed for the arithmetic locator, and a judgment can have
# up to 624 chunks — pulling every chunk_text moved megabytes over the wire and
# dominated the request. The matched chunk's text is fetched separately.
_SQL_CHUNK_LENGTHS = """
    SELECT chunk_index, length(chunk_text) AS chunk_len
    FROM   judgment_chunks
    WHERE  judgment_id = :jid
    ORDER  BY chunk_index
"""

# Used only by the windowed fallback for oversized judgments.
_SQL_CHUNK_WINDOW = """
    SELECT chunk_index, chunk_text
    FROM   judgment_chunks
    WHERE  judgment_id = :jid AND chunk_index BETWEEN :lo AND :hi
    ORDER  BY chunk_index
"""

_SQL_CHUNK_BY_ID = """
    SELECT chunk_index, chunk_text
    FROM   judgment_chunks
    WHERE  id = :cid
"""


# ---------------------------------------------------------------------------
# OCR cleanup, with a verification gate
# ---------------------------------------------------------------------------
_RE_ONLY_ALNUM = re.compile(r"[^a-z0-9 ]+")


def _canon_words(s: str) -> list[str]:
    return _RE_ONLY_ALNUM.sub(" ", (s or "").lower()).split()


def fidelity(source: str, cleaned: str) -> float:
    """Fraction of the cleaned text's words that come from the source, in order.

    Deliberately one-sided. A symmetric similarity score punishes deletion and
    invention equally, but only invention is dangerous here: the cleanup pass is
    *supposed* to delete page furniture. Measured, a legitimate removal of a
    running header ("318 [2024] 11 S.C.R. Digital Supreme Court Reports") from a
    short paragraph scores 0.87 symmetric — it would have been thrown away.

    Under this measure deletion is free and any invented or altered word costs,
    so truncation must be caught separately — see ``retention``.

    autojunk=False is essential: with difflib's default, frequent tokens are
    treated as junk and long passages score absurdly low.
    """
    src, out = _canon_words(source), _canon_words(cleaned)
    if not src or not out:
        return 0.0
    matcher = difflib.SequenceMatcher(None, src, out, autojunk=False)
    from_source = sum(block.size for block in matcher.get_matching_blocks())
    return from_source / len(out)


def retention(source: str, cleaned: str) -> float:
    """Share of the source's words kept. Catches silent truncation."""
    src, out = _canon_words(source), _canon_words(cleaned)
    if not src:
        return 0.0
    return len(out) / len(src)


_CLEANUP_PROMPT = """Below is one paragraph from an Indian court judgment, extracted from OCR of a scanned law report. It contains stray single margin letters, running page headers spliced into the middle of sentences, and line breaks that split words.

Return the SAME paragraph, tidied for quotation in a court filing.

Rules — these are absolute:
- Reproduce every word VERBATIM. Do not paraphrase, summarise, modernise, correct spellings, or reorder anything.
- Remove ONLY: stray single margin letters, running page headers (e.g. "[2024] 11 S.C.R. 318", "Digital Supreme Court Reports"), and stray page numbers.
- Rejoin words broken across line breaks.
- Do NOT add, remove or change the paragraph number.

Reply with JSON only: {"paragraph": "<cleaned text>"}

PARAGRAPH:
\"\"\"
%s
\"\"\"
"""


async def _clean_one(client, text: str) -> str:
    """Return cleaned text, or the input unchanged if the model is unfaithful."""
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=CLEANUP_MODEL,
                temperature=0.0,
                max_tokens=2000,
                messages=[{"role": "user", "content": _CLEANUP_PROMPT % text[:6000]}],
            ),
            timeout=CLEANUP_TIMEOUT_S,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
        cleaned = (json.loads(raw).get("paragraph") or "").strip()
    except Exception as exc:
        print(f"[paragraphs] cleanup failed, using raw text: {exc}")
        return text

    if not cleaned:
        return text

    score = fidelity(text, cleaned)
    kept = retention(text, cleaned)
    if score < CLEANUP_MIN_FIDELITY or kept < CLEANUP_MIN_RETENTION:
        # The model rewrote or truncated rather than tidied. A reworded passage
        # attributed to a judge must never reach a filed document, so discard it
        # and keep the deterministic text.
        print(f"[paragraphs] cleanup rejected (fidelity {score:.2f}, "
              f"retention {kept:.2f}) — keeping raw text")
        return text
    return cleaned


async def clean_paragraph_texts(texts: list[str]) -> list[str]:
    """Tidy paragraphs for quotation, discarding any output that isn't faithful.

    Public because generation calls it directly on the paragraphs the advocate
    ticked — that is where the 2-7s cost is affordable.
    """
    if not CLEANUP_ENABLED or not texts:
        return texts
    try:
        from app.core.rag import get_openrouter_client, openrouter_key
        if not openrouter_key:
            return texts
        client = get_openrouter_client()
    except Exception as exc:
        print(f"[paragraphs] no LLM client available: {exc}")
        return texts

    return list(await asyncio.gather(*[_clean_one(client, t) for t in texts]))


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def _title(row) -> str:
    petitioner = (getattr(row, "petitioner", "") or "").strip()
    respondent = (getattr(row, "respondent", "") or "").strip()
    if petitioner and respondent:
        return f"{petitioner} v. {respondent}"
    return petitioner or respondent or "Unknown"


async def _segment_judgment(
    engine, judgment_id: int, full_text: str, chunk_index: Optional[int]
) -> Segmentation:
    """Segment the whole judgment, or a window when the document is oversized."""
    if full_text and len(full_text) <= MAX_SEGMENT_CHARS:
        result = segment(full_text)
        if result.paragraphs:
            return result

    # Oversized, or whole-document segmentation found no numbering: fall back to
    # a window of neighbouring chunks around the match. Only now is the
    # neighbours' text worth fetching.
    if chunk_index is not None:
        from app.core.rag import _exec_raw

        rows = await _exec_raw(engine, _SQL_CHUNK_WINDOW, {
            "jid": judgment_id,
            "lo": max(0, chunk_index - WINDOW_RADIUS),
            "hi": chunk_index + WINDOW_RADIUS,
        })
        if rows:
            texts = [r.chunk_text or "" for r in rows]
            position = next(
                (i for i, r in enumerate(rows) if r.chunk_index == chunk_index), 0)
            return segment_window(texts, position)

    return segment(full_text or "")


async def get_judgment_paragraphs(
    engine,
    judgment_id: int,
    chunk_id: Optional[int] = None,
    chunk_index: Optional[int] = None,
    include_all: bool = False,
    clean: bool = False,
    disable_cache: bool = False,
) -> dict:
    """Return the paragraphs behind a retrieved citation.

    ``include_all`` returns every paragraph of the judgment (the full dropdown);
    otherwise only the paragraphs the retrieved chunk actually overlaps, which is
    typically 1-3 and is what the picker shows by default.

    ``clean`` runs the LLM tidy-up pass. Off for the picker (it costs 2-7s), on
    at generation time where the paragraph is about to be quoted.
    """
    from app.core.rag import _exec_raw

    cache_key = (
        f"judgment_paras:{judgment_id}:{chunk_id or 'x'}:{chunk_index if chunk_index is not None else 'x'}"
        f":{int(include_all)}:{int(clean)}:v{SEGMENTER_VERSION}"
    )
    if not disable_cache:
        try:
            cached = await cache_get(cache_key)
            if cached and isinstance(cached, dict) and cached.get("paragraphs") is not None:
                return cached
        except Exception as exc:
            print(f"[paragraphs] cache read error: {exc}")

    t_start = time.time()
    judgment_rows = await _exec_raw(engine, _SQL_JUDGMENT, {"jid": judgment_id})
    if not judgment_rows:
        return {
            "judgment_id": judgment_id, "paragraphs": [], "coverage": "none",
            "reason": "judgment_not_found",
        }
    judgment = judgment_rows[0]

    length_rows = await _exec_raw(engine, _SQL_CHUNK_LENGTHS, {"jid": judgment_id})

    # Resolve chunk_index from chunk_id when only the id was supplied.
    chunk_text = ""
    if chunk_id is not None:
        by_id = await _exec_raw(engine, _SQL_CHUNK_BY_ID, {"cid": chunk_id})
        if by_id:
            chunk_index = by_id[0].chunk_index
            chunk_text = by_id[0].chunk_text or ""
    elif chunk_index is not None:
        window = await _exec_raw(engine, _SQL_CHUNK_WINDOW, {
            "jid": judgment_id, "lo": chunk_index, "hi": chunk_index})
        if window:
            chunk_text = window[0].chunk_text or ""

    t_fetch = time.time()
    seg = await _segment_judgment(engine, judgment_id, judgment.full_text or "", chunk_index)
    t_segment = time.time()

    if not seg.paragraphs:
        # The source prints no paragraph numbers (~1% of the corpus). Say so
        # rather than deriving a positional number that the judgment never had.
        return {
            "judgment_id": judgment_id,
            "case_title": _title(judgment),
            "case_number": judgment.case_number or "",
            "year": judgment.year,
            "paragraphs": [],
            "coverage": "none",
            "reason": "no_paragraph_numbering",
        }

    # Locate the retrieved chunk and decide which paragraphs it matched.
    matched: list[int] = []
    # A judgment retrieved by BM25 alone carries no chunk reference (the keyword
    # branch in rag.py selects from the judgments table, not judgment_chunks), so
    # there is nothing to match against and every paragraph is a candidate.
    zone = "unknown" if not chunk_text else "body"
    tier = "none"
    if chunk_text:
        lengths = [int(r.chunk_len or 0) for r in length_rows]
        position = chunk_index if chunk_index is not None else 0
        start, end, tier = locate_chunk_tiered(seg.flat_text, chunk_text, position, lengths)
        zone = seg.classify_span((start, end))
        matched = paragraphs_for_span(seg.paragraphs, (start, end))

    selected: list[Paragraph]
    if include_all or zone == "unknown":
        # No chunk to narrow by — offer the whole judgment rather than an
        # arbitrary opening slice the advocate would have to expand past anyway.
        selected = seg.paragraphs
    elif matched:
        selected = [p for p in seg.paragraphs if p.number in matched]
    else:
        # Front matter (headnote/cause title) — ~19% of chunks. No numbered
        # paragraph matched, so offer the opening paragraphs of the judgment
        # rather than nothing, clearly marked as not-the-match.
        selected = seg.paragraphs[:3]

    # Clean the paragraphs that will actually be quoted — the matched ones —
    # rather than an arbitrary first N. With include_all a judgment can return 67
    # paragraphs, and cleaning the first four of those was both wasted spend and
    # inconsistent (paragraph 5 tidy, paragraph 6 not).
    cleaned_by_index: dict[int, str] = {}
    if clean:
        clean_order = [i for i, p in enumerate(selected) if p.number in matched]
        if not clean_order:
            clean_order = list(range(min(len(selected), CLEANUP_MAX_PARAS)))
        clean_order = clean_order[:CLEANUP_MAX_PARAS]
        cleaned = await clean_paragraph_texts([selected[i].text for i in clean_order])
        cleaned_by_index = dict(zip(clean_order, cleaned))
    t_done = time.time()

    payload_paragraphs = []
    for idx, para in enumerate(selected):
        item = para.to_dict()
        item["is_match"] = para.number in matched
        item["cleaned"] = idx in cleaned_by_index
        if idx in cleaned_by_index:
            item["text"] = cleaned_by_index[idx]
        payload_paragraphs.append(item)

    result = {
        "judgment_id": judgment_id,
        "case_title": _title(judgment),
        "case_number": judgment.case_number or "",
        "year": judgment.year,
        "paragraphs": payload_paragraphs,
        "matched_paragraphs": matched,
        "total_paragraphs": len(seg.paragraphs),
        "coverage": seg.coverage,
        "zone": zone,
        "mapping_tier": tier,
        "segmenter_version": SEGMENTER_VERSION,
    }

    print(
        f"[paragraphs] judgment={judgment_id} chunk={chunk_id} "
        f"paras={len(payload_paragraphs)}/{len(seg.paragraphs)} zone={zone} tier={tier} "
        f"total={t_done - t_start:.2f}s fetch={t_fetch - t_start:.2f}s "
        f"segment={t_segment - t_fetch:.3f}s cleanup={t_done - t_segment:.2f}s"
    )

    if not disable_cache:
        try:
            await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
        except Exception as exc:
            print(f"[paragraphs] cache write error: {exc}")
    return result
