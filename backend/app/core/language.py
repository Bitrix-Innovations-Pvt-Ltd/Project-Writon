"""
core/language.py — script detection and Indian-language → English translation of
OCR text.

Runs immediately after core/ocr.py, before anything else reads the document.
`ocr_text` therefore stays the English-facing column, and the four consumers of
it — core/verification.py, core/extraction.py, core/uploaded_docs.py and
citation retrieval — keep working unchanged and simply get better. The Hindi
original is preserved separately (uploaded_docs.ocr_text_original) for audit.

Design notes, because each of these looked like a cheaper option first:

  * DETECTION IS SCRIPT-BASED, not a language-ID library and not an LLM call.
    Hindi and English occupy disjoint Unicode blocks, so counting Devanagari
    letters is exact, free and instant — and an English upload, which is the
    common case, costs nothing at all. langdetect/fasttext would add a
    dependency and be *less* reliable on OCR noise.

  * SEGMENT-LEVEL, not document-level. Indian court documents are overwhelmingly
    code-mixed: a Devanagari body carrying English case numbers and section
    references, or an English petition with Hindi annexures. A document-level
    threshold has a cliff — it either round-trips the English half through the
    model (destroying the verbatim text that extraction.py's grounding check
    depends on) or leaves the Hindi half untranslated. Only Devanagari-heavy
    paragraphs are sent; English passages survive byte-identical.

  * PAGE MARKERS ARE RE-EMITTED BY CODE. "--- Page N ---" is load-bearing
    downstream, and a model told to "preserve the markers" will eventually drop
    or renumber one. The markers, the "[NOTE: ...]" truncation notices and the
    "[Scanned page not read...]" placeholders are held aside as fixed tokens and
    never reach the prompt.

  * NOTHING HERE RAISES. A failed chunk keeps its Hindi original and downgrades
    the status to 'partial'. A partly-translated document is strictly better
    than a rejected upload.

Out of scope for now: Romanised Hindi ("Hinglish" written in Latin script) is
invisible to script detection and passes through as English. It is rare in filed
court documents. Additional scripts are a one-line entry in SCRIPT_RANGES.
"""

import asyncio
import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from app.core.rag import get_openrouter_client, openrouter_key
from app.core.redis import cache_get, cache_set

# ── Configuration ────────────────────────────────────────────────────────────
# Mirrors the OCR_* block in core/ocr.py.
#
# TRANSLATION_ENABLED=0 is the kill switch: the layer becomes a pass-through and
# reports status 'disabled', so a bad rollout is one environment variable away
# from being reverted.
TRANSLATION_ENABLED = os.getenv("TRANSLATION_ENABLED", "1") == "1"

# Gemini 2.5 Flash: it reads and writes Devanagari markedly better than the
# OpenAI models at this tier (see the measurements in core/ocr.py), and at
# $0.30/$2.50 per M it is ~5x cheaper on input and ~4x on output than gpt-4o.
#
# Deliberately NO `reasoning` parameter is sent. Verified against OpenRouter:
# the default already spends zero thinking tokens, while reasoning.effort
# "minimal" *raised* output from 40 to 214 tokens on the same input — 5x the
# cost for a transcription task that needs no reasoning at all.
TRANSLATION_MODEL = os.getenv("TRANSLATION_MODEL", "google/gemini-2.5-flash")

TRANSLATION_CHUNK_CHARS = int(os.getenv("TRANSLATION_CHUNK_CHARS", "6000"))
TRANSLATION_WORKERS = int(os.getenv("TRANSLATION_WORKERS", "6"))
TRANSLATION_TIMEOUT_S = float(os.getenv("TRANSLATION_TIMEOUT_S", "60"))

# Total spend bound per document, mirroring MAX_VISION_PAGES in core/ocr.py.
# Beyond it the remaining Hindi is left in place and announced.
TRANSLATION_MAX_CHARS = int(os.getenv("TRANSLATION_MAX_CHARS", "120000"))

# Advocates re-upload the same order into several checklist slots constantly
# (dedupe_docs in core/extraction.py exists precisely because of that), so the
# second upload of a long judgment should be close to free.
TRANSLATION_CACHE_TTL = int(os.getenv("TRANSLATION_CACHE_TTL", str(7 * 24 * 3600)))

# ── Script detection ─────────────────────────────────────────────────────────
# Add a script here to support it; nothing else in this module is Hindi-specific.
# Marathi also uses Devanagari, which is why the prompt says "the Indian language
# present" rather than naming Hindi.
SCRIPT_RANGES: dict[str, tuple[int, int]] = {
    "hi": (0x0900, 0x097F),      # Devanagari
}

# Human-readable names for the prompt and for UI labels.
SCRIPT_NAMES: dict[str, str] = {
    "hi": "Hindi",
}

# Below this there is not enough text to classify — a cover page of digits and
# punctuation must not read as English.
MIN_LETTERS_FOR_DETECTION = 20

# Above this share of the letters, the document is labelled as that script
# outright rather than 'mixed'. Display only — what gets translated is decided
# per segment.
DOC_DOMINANT_RATIO = 0.60

# Segment-level translation thresholds.
#
# 0.30 rather than a majority: a genuinely Hindi paragraph carrying an FIR
# number, a list of sections and a date is easily 40% Latin characters.
# The absolute floor stops a single stray Devanagari word from dragging an
# otherwise English paragraph through the model.
SEG_MIN_RATIO = 0.30
SEG_MIN_SCRIPT_CHARS = 10

# Statuses written to uploaded_docs.translation_status.
STATUS_NOT_NEEDED = "not_needed"
STATUS_TRANSLATED = "translated"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUS_DISABLED = "disabled"

# Must not contain "failed" or "extraction failed" — is_usable_ocr() in
# core/extraction.py matches those as substrings and would drop the whole
# document.
_LENGTH_LIMIT_NOTICE = (
    "\n\n[NOTE: The remainder of this document is in {language} and was not "
    "translated (translation length limit).]"
)

# Splitting patterns. Both use a capturing group so re.split returns the
# separators too and the token stream reassembles to the exact original.
_PAGE_MARKER_RE = re.compile(r"(\n--- Page \d+ ---\n)")
_PARA_SPLIT_RE = re.compile(r"(\n[ \t]*\n\s*)")

# Bracketed notices emitted by core/ocr.py. Their exact wording is depended on
# by is_usable_ocr() and by test_ocr.py, so they are never paraphrased.
_NOTICE_RE = re.compile(r"^\s*\[.*\]\s*$", re.DOTALL)

# The prompt forbids a preamble, but models occasionally add one anyway.
_PREAMBLE_RE = re.compile(
    r"^\s*(here is|here's|the following is)?\s*(the\s+)?"
    r"(english\s+)?translation\s*(of[^\n:]*)?\s*:\s*\n+",
    re.IGNORECASE,
)

# A translation far shorter than its source means a refusal or a truncated
# response, not a translation. Hindi→English is normally 1.0–1.4x by characters.
_MIN_LENGTH_RATIO = 0.25

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


# ── Prompt ───────────────────────────────────────────────────────────────────

TRANSLATION_SYSTEM_PROMPT = """\
You are a court translator for Indian litigation. You translate text taken from
Indian legal documents (FIRs, charge sheets, orders, judgments, notices,
affidavits, agreements) from the Indian language it is written in — usually
Hindi, sometimes Marathi — into English.

Your output is read by a lawyer preparing a fresh pleading and by software that
extracts party names and dates from it. A wrong name, number or date is far
worse than an awkward sentence.

ABSOLUTE RULES
==============
1. TRANSLATE, DO NOT SUMMARISE. Every sentence in the input must appear in the
   output. Do not condense, do not expand, do not explain, do not comment.
2. OUTPUT ONLY THE TRANSLATION. No preamble, no "Here is the translation", no
   notes, no markdown fences.
3. NUMBERS AND IDENTIFIERS ARE COPIED EXACTLY. Case numbers, FIR/crime numbers,
   section numbers, dates, amounts, ages, addresses and pin codes keep their
   exact digits. Convert Devanagari numerals (०१२३४५६७८९) to ASCII digits, but
   never re-derive, complete or "correct" a value.
4. PROPER NOUNS ARE TRANSLITERATED, NOT TRANSLATED. Use the standard Roman
   spelling an Indian court would print: राम कुमार -> "Ram Kumar",
   शर्मा -> "Sharma", गाज़ियाबाद -> "Ghaziabad". Never translate the meaning of
   a name. Spell the same name the same way every time it appears.
5. TEXT ALREADY IN ENGLISH IS COPIED THROUGH UNCHANGED, character for character.
6. PRESERVE THE STRUCTURE. Keep paragraph breaks, line breaks, headings,
   numbered and lettered lists exactly as they are.
7. ILLEGIBLE OCR NOISE IS CARRIED THROUGH AS-IS. Do not invent plausible text to
   fill a gap.

LEGAL TERMINOLOGY
=================
Use these renderings consistently:
  धारा -> Section              प्राथमिकी / एफ.आई.आर. -> FIR
  थाना -> Police Station       अभियुक्त -> accused
  याचिकाकर्ता -> petitioner    प्रतिवादी -> respondent
  वादी -> plaintiff            आवेदक -> applicant
  प्रार्थी -> applicant         प्रार्थीगण -> applicants
  जमानत -> bail                आदेश -> order
  निर्णय -> judgment           डिक्री -> decree
  दिनांक -> dated              न्यायालय -> Court
  अपील -> appeal               गवाह -> witness
  शपथ पत्र -> affidavit        वकालतनामा -> Vakalatnama
  प्रार्थना पत्र -> application  सम्मन -> summons
  आरोप पत्र -> charge sheet    जब्ती -> seizure
  पुलिस उपाधीक्षक -> Deputy Superintendent of Police
  मुख्य न्यायिक मजिस्ट्रेट -> Chief Judicial Magistrate
"""


# ── Result type ──────────────────────────────────────────────────────────────

@dataclass
class TranslationResult:
    """What the upload path writes to the uploaded_docs row."""

    text: str                       # English-facing text -> ocr_text
    language: str                   # 'en' | 'hi' | 'mixed' | 'unknown'
    original: Optional[str]          # pre-translation text, None if untouched
    status: str                     # see STATUS_* above

    @property
    def was_translated(self) -> bool:
        return self.status in (STATUS_TRANSLATED, STATUS_PARTIAL)


# ── Detection ────────────────────────────────────────────────────────────────

def _script_of(ch: str) -> Optional[str]:
    """Which tracked script a character belongs to, or None."""
    cp = ord(ch)
    for code, (lo, hi) in SCRIPT_RANGES.items():
        if lo <= cp <= hi:
            return code
    return None


def _count_scripts(text: str) -> tuple[dict[str, int], int]:
    """(letters per tracked script, total letters).

    Only letters are counted. Digits, punctuation and whitespace are ignored so
    that a page of case numbers does not read as English, and so that Devanagari
    numerals (category Nd, not L) do not inflate the Hindi ratio.
    """
    counts: dict[str, int] = {}
    total = 0
    if not isinstance(text, str):
        return counts, total

    for ch in text:
        if not unicodedata.category(ch).startswith("L"):
            continue
        total += 1
        code = _script_of(ch)
        if code:
            counts[code] = counts.get(code, 0) + 1
    return counts, total


def script_profile(text: str) -> dict[str, float]:
    """Ratio of each tracked script's letters to all letters in *text*."""
    counts, total = _count_scripts(text)
    if not total:
        return {}
    return {code: n / total for code, n in counts.items()}


def detect_language(text: str) -> str:
    """Document-level label: a script code ('hi'), 'mixed', 'en' or 'unknown'.

    Drives the UI badge and the drafting-prompt annotation. What actually gets
    sent to the model is decided per segment, so this label has no cliff
    behaviour to worry about.
    """
    counts, total = _count_scripts(text)
    if total < MIN_LETTERS_FOR_DETECTION:
        # Not enough letters to say anything honest — a cover page of case
        # numbers, or an OCR failure.
        return "unknown"
    if not counts:
        return "en"

    code, n = max(counts.items(), key=lambda kv: kv[1])
    if n / total >= DOC_DOMINANT_RATIO:
        return code
    # 'mixed' is deliberately keyed on an absolute count, not a share: a 40-page
    # English petition with one Devanagari annexure paragraph is 2% Hindi by
    # letters, and that paragraph still has to be translated. The floor is the
    # same one that makes a segment translatable, so 'mixed' means exactly
    # "there may be a segment worth sending".
    if n >= SEG_MIN_SCRIPT_CHARS:
        return "mixed"
    return "en"


def language_display(code: str) -> str:
    """'hi' -> 'Hindi'. Used in notices and by the drafting-prompt label."""
    return SCRIPT_NAMES.get(code, "Hindi" if code == "mixed" else code)


# ── Segmentation ─────────────────────────────────────────────────────────────

@dataclass
class _Token:
    text: str
    translatable: bool

    @property
    def is_whitespace(self) -> bool:
        return not self.text.strip()


def _needs_translation(para: str) -> bool:
    """True for a paragraph that is dominated by a non-Latin Indian script."""
    if not para.strip():
        return False
    # Bracketed notices from core/ocr.py are already English and their exact
    # wording is depended on downstream.
    if _NOTICE_RE.match(para):
        return False

    counts, total = _count_scripts(para)
    if not counts or not total:
        return False
    best = max(counts.values())
    return best >= SEG_MIN_SCRIPT_CHARS and (best / total) >= SEG_MIN_RATIO


def _tokenize(text: str) -> list[_Token]:
    """Split *text* into fixed and translatable tokens.

    Concatenating every token's text reproduces the input exactly, which is what
    lets page markers and notices survive untouched.
    """
    tokens: list[_Token] = []
    for piece in _PAGE_MARKER_RE.split(text):
        if not piece:
            continue
        if _PAGE_MARKER_RE.fullmatch(piece):
            tokens.append(_Token(piece, False))     # page marker: never sent
            continue
        for part in _PARA_SPLIT_RE.split(piece):
            if not part:
                continue
            tokens.append(_Token(part, _needs_translation(part)))
    return tokens


def _plan_chunks(tokens: list[_Token]) -> list[list[int]]:
    """Group consecutive translatable tokens into chunks of token indices.

    Whitespace lying *between* two translatable paragraphs is pulled into the
    chunk so the model sees them together — cross-paragraph context is what keeps
    a party's transliteration consistent down a page. Anything else (a page
    marker, a notice, an English paragraph) ends the chunk, so English passages
    are never re-emitted by the model.

    A chunk never splits a paragraph: a boundary inside a sentence produces a
    mistranslation at the seam.
    """
    chunks: list[list[int]] = []
    i = 0
    n = len(tokens)

    while i < n:
        if not tokens[i].translatable:
            i += 1
            continue

        j = i
        last = i
        size = 0
        while j < n and (tokens[j].translatable or tokens[j].is_whitespace):
            if tokens[j].translatable:
                # Oversize single paragraph still goes alone rather than being cut.
                if size and size + len(tokens[j].text) > TRANSLATION_CHUNK_CHARS:
                    break
                size += len(tokens[j].text)
                last = j
            j += 1

        # Trailing whitespace stays outside the chunk, so it is preserved byte
        # for byte instead of being regenerated by the model.
        chunks.append(list(range(i, last + 1)))
        i = last + 1

    return chunks


# ── Translation ──────────────────────────────────────────────────────────────

def _clean_response(raw: str) -> str:
    out = _PREAMBLE_RE.sub("", raw or "")
    out = out.strip("\n")
    # Models occasionally wrap the whole answer in a code fence despite rule 2.
    if out.startswith("```"):
        lines = out.split("\n")
        if lines[-1].strip().startswith("```"):
            out = "\n".join(lines[1:-1])
    return out


def _cache_key(source: str) -> str:
    """Cache key covering the source text AND what produced the translation.

    The model and the prompt are part of the key, not just the text. Without
    them, switching TRANSLATION_MODEL or editing the glossary keeps serving
    translations produced by the old configuration for the full 7-day TTL — the
    change appears to have no effect on exactly the documents already seen.
    """
    fingerprint = "\x00".join(
        (source, TRANSLATION_MODEL, TRANSLATION_SYSTEM_PROMPT)
    ).encode("utf-8")
    return f"xlate:{hashlib.sha1(fingerprint).hexdigest()[:16]}"


async def _translate_chunk(source: str) -> Optional[str]:
    """Translate one chunk. Returns None if the result cannot be trusted."""
    cache_key = _cache_key(source)
    try:
        cached = await cache_get(cache_key)
        if isinstance(cached, str) and cached:
            return cached
    except Exception as e:                                  # cache is optional
        print(f"[language] cache read failed: {e}")

    client = get_openrouter_client()
    response = await asyncio.wait_for(
        client.chat.completions.create(
            model=TRANSLATION_MODEL,
            messages=[
                {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
                {"role": "user", "content": source},
            ],
            temperature=0.0,
        ),
        timeout=TRANSLATION_TIMEOUT_S,
    )
    out = _clean_response(response.choices[0].message.content or "")

    # A response far shorter than its source is a refusal or a truncation, not a
    # translation. Keeping the Hindi original is the safer outcome.
    if not out.strip() or len(out) < len(source.strip()) * _MIN_LENGTH_RATIO:
        print(f"[language] implausible translation length ({len(out)} from {len(source)}); keeping original")
        return None

    try:
        await cache_set(cache_key, out, TRANSLATION_CACHE_TTL)
    except Exception as e:
        print(f"[language] cache write failed: {e}")

    return out


async def translate_to_english(text: str) -> TranslationResult:
    """Translate the non-English parts of OCR text. Never raises.

    Returns the English-facing text plus the metadata the uploads path persists.
    When nothing was translated, `original` is None — English uploads therefore
    cost no extra storage and no API call.

    Devanagari numerals in the output are normalised to ASCII, but only for
    documents that were actually translated: a pure-English document passes
    through completely untouched.
    """
    if not isinstance(text, str) or not text.strip():
        return TranslationResult(text or "", "unknown", None, STATUS_NOT_NEEDED)

    language = detect_language(text)

    # Fast path for the common case. Safe to gate on the label because 'en' and
    # 'unknown' both mean fewer than SEG_MIN_SCRIPT_CHARS letters of any tracked
    # script in the whole document — so no segment could clear the threshold
    # either. Nothing is tokenized and no API call is made.
    if language in ("en", "unknown"):
        return TranslationResult(text, language, None, STATUS_NOT_NEEDED)

    if not TRANSLATION_ENABLED:
        return TranslationResult(text, language, None, STATUS_DISABLED)

    if not openrouter_key:
        print("[language] OPENROUTER_API_KEY not configured; skipping translation")
        return TranslationResult(text, language, None, STATUS_DISABLED)

    tokens = _tokenize(text)
    chunks = _plan_chunks(tokens)
    if not chunks:
        # The document-level label said Hindi but no single paragraph cleared the
        # segment threshold — scattered words, nothing worth a call.
        return TranslationResult(text, language, None, STATUS_NOT_NEEDED)

    # Apply the total-spend cap in document order, so the operative front of the
    # document is the part that gets translated.
    sources: list[str] = ["".join(tokens[k].text for k in c) for c in chunks]
    budget = TRANSLATION_MAX_CHARS
    attempted: list[int] = []
    over_limit = False
    for idx, src in enumerate(sources):
        if budget - len(src) < 0 and attempted:
            over_limit = True
            break
        budget -= len(src)
        attempted.append(idx)

    semaphore = asyncio.Semaphore(max(1, TRANSLATION_WORKERS))

    async def run(idx: int) -> Optional[str]:
        async with semaphore:
            try:
                return await _translate_chunk(sources[idx])
            except Exception as e:
                print(f"[language] chunk {idx} translation failed: {e}")
                return None

    results = await asyncio.gather(*(run(i) for i in attempted))

    succeeded = 0
    for idx, translated in zip(attempted, results):
        if translated is None:
            continue                       # keep the original for this chunk
        succeeded += 1
        chunk = chunks[idx]
        tokens[chunk[0]].text = translated
        for k in chunk[1:]:
            tokens[k].text = ""

    if succeeded == 0:
        return TranslationResult(text, language, None, STATUS_FAILED)

    out = "".join(t.text for t in tokens).translate(_DEVANAGARI_DIGITS)

    complete = succeeded == len(chunks) and not over_limit
    if over_limit:
        out += _LENGTH_LIMIT_NOTICE.format(language=language_display(language))

    return TranslationResult(
        text=out,
        language=language,
        original=text,
        status=STATUS_TRANSLATED if complete else STATUS_PARTIAL,
    )
