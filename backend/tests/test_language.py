"""
Unit tests for core/language.py — script detection and Hindi→English translation.

The LLM call is stubbed throughout, so these run offline with no OpenRouter
spend. Tested at the string level rather than through PyMuPDF: _digital_pdf in
test_ocr.py writes with the default Helvetica font, which cannot render
Devanagari at all.

The regressions these guard:
  * Hindi uploads reaching the cause title, the drafting prompt and the
    English-indexed citation retrieval untranslated.
  * The reverse — English documents silently paying for an LLM call, or having
    their verbatim text round-tripped through a model that extraction.py's
    grounding check then fails to match.
"""

import asyncio
import re

import pytest

import app.core.language as lang


# ── Fixtures ─────────────────────────────────────────────────────────────────

HINDI_PARA = (
    "प्रार्थी के विरुद्ध थाना कवि नगर, गाजियाबाद में प्राथमिकी संख्या 187/2026 "
    "अंतर्गत धारा 316(2) एवं 318(4) भारतीय न्याय संहिता पंजीकृत की गई है। "
    "प्रार्थी निर्दोष है तथा उसे झूठा फंसाया गया है।"
)

HINDI_PARA_2 = (
    "दिनांक 14.03.2026 को विद्वान मुख्य न्यायिक मजिस्ट्रेट द्वारा पारित आदेश "
    "विधि विरुद्ध है तथा निरस्त किए जाने योग्य है। अभियुक्त राम कुमार शर्मा "
    "पुत्र श्री मोहन लाल निवासी ग्राम सिकंदरपुर, जनपद गाजियाबाद है।"
)

ENGLISH_PARA = (
    "That the Applicant is a permanent resident of Ghaziabad and has deep roots "
    "in society. The Applicant undertakes to cooperate with the investigation "
    "and to appear before the Court on every date of hearing."
)


def run(coro):
    """These tests are sync; the project has no pytest-asyncio (see
    test_drafting_selection.py, which does the same)."""
    return asyncio.run(coro)


@pytest.fixture
def stub_llm(monkeypatch):
    """Replace the chunk translator; records every source it was given."""
    calls = []

    async def _fake(source):
        calls.append(source)
        return f"[EN{len(calls)}] " + "x" * len(source)

    monkeypatch.setattr(lang, "_translate_chunk", _fake)
    monkeypatch.setattr(lang, "openrouter_key", "test-key")
    monkeypatch.setattr(lang, "TRANSLATION_ENABLED", True)
    return calls


@pytest.fixture
def no_cache(monkeypatch):
    """Isolate _translate_chunk from Redis / the in-process memory store."""
    store = {}

    async def _get(key):
        return store.get(key)

    async def _set(key, value, ttl=0):
        store[key] = value

    monkeypatch.setattr(lang, "cache_get", _get)
    monkeypatch.setattr(lang, "cache_set", _set)
    return store


# ── Detection ────────────────────────────────────────────────────────────────

def test_pure_devanagari_is_hindi():
    assert lang.detect_language(HINDI_PARA) == "hi"


def test_pure_ascii_is_english():
    assert lang.detect_language(ENGLISH_PARA) == "en"


def test_half_and_half_is_mixed():
    assert lang.detect_language(HINDI_PARA + "\n\n" + ENGLISH_PARA * 2) == "mixed"


def test_english_with_a_few_hindi_words_is_mixed_not_english():
    """A cause title in Devanagari inside an English petition still has to be
    translated, so it must not classify as 'en'."""
    text = ENGLISH_PARA * 6 + "\n\nअभियुक्त राम कुमार शर्मा"
    assert lang.detect_language(text) == "mixed"


def test_digits_and_punctuation_only_is_unknown():
    """A cover page of case numbers must not read as English."""
    assert lang.detect_language("187/2026 -- 316(2) -- 14.03.2026 -- 45,000/-") == "unknown"


def test_empty_and_blank_are_unknown():
    for value in ("", "   ", "\n\n"):
        assert lang.detect_language(value) == "unknown"


def test_non_string_is_unknown():
    assert lang.detect_language(None) == "unknown"


def test_devanagari_numerals_do_not_count_as_hindi_letters():
    """U+0966-U+096F sit in the Devanagari block but are digits, not letters.
    Counting them would make an English page of Hindi-numbered paragraphs read
    as Hindi and send it to the model."""
    assert lang.detect_language(ENGLISH_PARA + " ०१२३४५६७८९") == "en"


def test_script_profile_ratios():
    profile = lang.script_profile(HINDI_PARA)
    assert profile["hi"] > 0.95
    assert lang.script_profile(ENGLISH_PARA) == {}


def test_script_profile_of_empty_text():
    assert lang.script_profile("") == {}


# ── Segmentation ─────────────────────────────────────────────────────────────

def test_tokens_reassemble_to_the_exact_input():
    """Everything downstream depends on this: page markers and notices survive
    only because the token stream is lossless."""
    text = (
        "\n--- Page 1 ---\n" + HINDI_PARA + "\n\n" + ENGLISH_PARA +
        "\n--- Page 2 ---\n" + HINDI_PARA_2 +
        "\n\n[NOTE: something.]"
    )
    assert "".join(t.text for t in lang._tokenize(text)) == text


def test_page_markers_are_never_translatable():
    tokens = lang._tokenize("\n--- Page 1 ---\n" + HINDI_PARA)
    markers = [t for t in tokens if "--- Page" in t.text]
    assert markers and all(not t.translatable for t in markers)


def test_ocr_notices_are_never_translatable():
    """is_usable_ocr() and test_ocr.py match these by exact wording."""
    for notice in (
        "[Scanned page not read - image OCR limit reached.]",
        "[NOTE: Only the first 10 of 14 pages were read (page limit).]",
    ):
        tokens = lang._tokenize(HINDI_PARA + "\n\n" + notice)
        assert all(not t.translatable for t in tokens if notice in t.text)


def test_english_paragraph_is_not_translatable():
    tokens = lang._tokenize(ENGLISH_PARA)
    assert all(not t.translatable for t in tokens)


def test_stray_hindi_word_does_not_drag_an_english_paragraph_in():
    tokens = lang._tokenize(ENGLISH_PARA + " (आदेश)")
    assert all(not t.translatable for t in tokens)


def test_hindi_paragraph_with_case_numbers_is_translatable():
    """~40% Latin characters from the FIR number and section list — a majority
    threshold would wrongly leave this in Hindi."""
    para = "प्राथमिकी संख्या 187/2026 u/s 316(2) BNS, P.S. Kavi Nagar, Ghaziabad " + HINDI_PARA
    tokens = lang._tokenize(para)
    assert any(t.translatable for t in tokens)


# ── Chunk planning ───────────────────────────────────────────────────────────

def test_chunks_never_split_a_paragraph(monkeypatch):
    monkeypatch.setattr(lang, "TRANSLATION_CHUNK_CHARS", 50)
    tokens = lang._tokenize("\n\n".join([HINDI_PARA] * 4))
    for chunk in lang._plan_chunks(tokens):
        for k in chunk:
            assert tokens[k].text in ("", *[t.text for t in tokens])


def test_consecutive_hindi_paragraphs_share_one_chunk():
    """Cross-paragraph context is what keeps a party's transliteration
    consistent down a page."""
    tokens = lang._tokenize(HINDI_PARA + "\n\n" + HINDI_PARA_2)
    assert len(lang._plan_chunks(tokens)) == 1


def test_an_english_paragraph_breaks_the_chunk():
    tokens = lang._tokenize(HINDI_PARA + "\n\n" + ENGLISH_PARA + "\n\n" + HINDI_PARA_2)
    assert len(lang._plan_chunks(tokens)) == 2


def test_a_page_marker_breaks_the_chunk():
    text = HINDI_PARA + "\n--- Page 2 ---\n" + HINDI_PARA_2
    assert len(lang._plan_chunks(lang._tokenize(text))) == 2


def test_chunk_char_budget_is_respected(monkeypatch):
    monkeypatch.setattr(lang, "TRANSLATION_CHUNK_CHARS", 200)
    tokens = lang._tokenize("\n\n".join([HINDI_PARA] * 5))
    chunks = lang._plan_chunks(tokens)
    assert len(chunks) == 5              # each paragraph already exceeds 200


# ── Cost guards ──────────────────────────────────────────────────────────────

def test_english_document_makes_zero_llm_calls(stub_llm):
    """The common case must stay free."""
    result = run(lang.translate_to_english(ENGLISH_PARA))
    assert stub_llm == []
    assert result.status == lang.STATUS_NOT_NEEDED
    assert result.original is None
    assert result.text == ENGLISH_PARA            # untouched, byte for byte


def test_mixed_document_translates_only_the_hindi(stub_llm):
    text = ENGLISH_PARA + "\n\n" + HINDI_PARA + "\n\n" + ENGLISH_PARA
    result = run(lang.translate_to_english(text))

    assert len(stub_llm) == 1
    assert HINDI_PARA in stub_llm[0]
    assert ENGLISH_PARA not in stub_llm[0]        # English never sent
    assert result.text.count(ENGLISH_PARA) == 2   # ...and comes back verbatim


def test_unknown_language_makes_no_calls(stub_llm):
    run(lang.translate_to_english("187/2026 -- 316(2)"))
    assert stub_llm == []


def test_identical_chunk_is_translated_once(monkeypatch, no_cache):
    """Advocates re-upload the same order into several checklist slots."""
    calls = []

    class _Msg:
        def __init__(self, c): self.message = type("M", (), {"content": c})()

    class _Client:
        class chat:
            class completions:
                @staticmethod
                async def create(**kw):
                    calls.append(kw)
                    return type("R", (), {"choices": [_Msg("Translated text " * 20)]})()

    monkeypatch.setattr(lang, "get_openrouter_client", lambda: _Client)
    run(lang._translate_chunk(HINDI_PARA))
    run(lang._translate_chunk(HINDI_PARA))
    assert len(calls) == 1


def test_cache_key_covers_the_model_and_the_prompt():
    """Switching TRANSLATION_MODEL or editing the glossary must invalidate the
    cache — otherwise the change silently has no effect on documents already
    seen, for the full 7-day TTL."""
    import app.core.language as m

    base = m._cache_key(HINDI_PARA)
    original_model, original_prompt = m.TRANSLATION_MODEL, m.TRANSLATION_SYSTEM_PROMPT
    try:
        m.TRANSLATION_MODEL = "some/other-model"
        assert m._cache_key(HINDI_PARA) != base
        m.TRANSLATION_MODEL = original_model

        m.TRANSLATION_SYSTEM_PROMPT = original_prompt + "\n  नया -> new"
        assert m._cache_key(HINDI_PARA) != base
    finally:
        m.TRANSLATION_MODEL, m.TRANSLATION_SYSTEM_PROMPT = original_model, original_prompt

    assert m._cache_key(HINDI_PARA) == base          # restored
    assert m._cache_key(HINDI_PARA + " x") != base   # and still keyed on text


# ── Structure preservation ───────────────────────────────────────────────────

def test_page_markers_survive_translation(stub_llm):
    text = (
        "\n--- Page 1 ---\n" + HINDI_PARA +
        "\n--- Page 2 ---\n" + HINDI_PARA_2 +
        "\n--- Page 3 ---\n" + HINDI_PARA
    )
    result = run(lang.translate_to_english(text))
    assert len(re.findall(r"--- Page \d+ ---", result.text)) == 3
    for n in (1, 2, 3):
        assert f"--- Page {n} ---" in result.text


def test_document_order_is_preserved_across_concurrent_chunks(stub_llm):
    text = "\n--- Page 1 ---\n".join([HINDI_PARA, HINDI_PARA_2, HINDI_PARA])
    result = run(lang.translate_to_english(text))
    # The stub numbers its output in call order; positions must ascend.
    positions = [result.text.index(f"[EN{i}]") for i in (1, 2, 3)]
    assert positions == sorted(positions)


def test_original_is_preserved_for_audit(stub_llm):
    result = run(lang.translate_to_english(HINDI_PARA))
    assert result.original == HINDI_PARA
    assert result.language == "hi"
    assert result.was_translated


def test_devanagari_digits_are_normalised(stub_llm):
    """extraction.py parses dates out of this text; ०१ is not a date."""
    text = HINDI_PARA + "\n\n[NOTE: page ०७ of १२.]"
    result = run(lang.translate_to_english(text))
    assert "page 07 of 12" in result.text


# ── Degradation ──────────────────────────────────────────────────────────────

def test_one_failing_chunk_keeps_its_original_and_marks_partial(monkeypatch):
    monkeypatch.setattr(lang, "openrouter_key", "test-key")
    seen = []

    async def _flaky(source):
        seen.append(source)
        if len(seen) == 2:
            raise RuntimeError("upstream 502")
        return "TRANSLATED"

    monkeypatch.setattr(lang, "_translate_chunk", _flaky)

    text = HINDI_PARA + "\n--- Page 2 ---\n" + HINDI_PARA_2
    result = run(lang.translate_to_english(text))

    assert result.status == lang.STATUS_PARTIAL
    assert "TRANSLATED" in result.text
    assert HINDI_PARA_2 in result.text        # the failed chunk kept its Hindi


def test_all_chunks_failing_returns_the_original_untouched(monkeypatch):
    monkeypatch.setattr(lang, "openrouter_key", "test-key")

    async def _dead(source):
        raise RuntimeError("boom")

    monkeypatch.setattr(lang, "_translate_chunk", _dead)
    result = run(lang.translate_to_english(HINDI_PARA))

    assert result.status == lang.STATUS_FAILED
    assert result.text == HINDI_PARA
    assert result.original is None


def test_translation_never_raises(monkeypatch):
    monkeypatch.setattr(lang, "openrouter_key", "test-key")

    async def _dead(source):
        raise ValueError("nope")

    monkeypatch.setattr(lang, "_translate_chunk", _dead)
    for value in (None, "", "   ", HINDI_PARA, ENGLISH_PARA, "\n--- Page 1 ---\n"):
        assert isinstance(run(lang.translate_to_english(value)), lang.TranslationResult)


def test_kill_switch_is_a_pass_through(monkeypatch, stub_llm):
    monkeypatch.setattr(lang, "TRANSLATION_ENABLED", False)
    result = run(lang.translate_to_english(HINDI_PARA))

    assert stub_llm == []
    assert result.status == lang.STATUS_DISABLED
    assert result.text == HINDI_PARA
    assert result.language == "hi"


def test_missing_api_key_is_a_pass_through(monkeypatch, stub_llm):
    monkeypatch.setattr(lang, "openrouter_key", "")
    result = run(lang.translate_to_english(HINDI_PARA))
    assert stub_llm == []
    assert result.status == lang.STATUS_DISABLED


def test_implausibly_short_response_is_rejected(monkeypatch, no_cache):
    """A refusal or a truncated response must not replace the record."""
    class _Client:
        class chat:
            class completions:
                @staticmethod
                async def create(**kw):
                    msg = type("M", (), {"content": "I cannot help."})()
                    return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    monkeypatch.setattr(lang, "get_openrouter_client", lambda: _Client)
    assert run(lang._translate_chunk(HINDI_PARA)) is None


def test_model_preamble_is_stripped(monkeypatch, no_cache):
    body = "The applicant is innocent and has been falsely implicated. " * 5

    class _Client:
        class chat:
            class completions:
                @staticmethod
                async def create(**kw):
                    msg = type("M", (), {"content": "Here is the translation:\n\n" + body})()
                    return type("R", (), {"choices": [type("C", (), {"message": msg})()]})()

    monkeypatch.setattr(lang, "get_openrouter_client", lambda: _Client)
    out = run(lang._translate_chunk(HINDI_PARA))
    assert out.startswith("The applicant")


# ── Spend cap ────────────────────────────────────────────────────────────────

def test_over_cap_translates_the_front_and_announces_the_rest(monkeypatch, stub_llm):
    monkeypatch.setattr(lang, "TRANSLATION_MAX_CHARS", len(HINDI_PARA) + 10)
    text = "\n--- Page 1 ---\n".join([HINDI_PARA] * 4)
    result = run(lang.translate_to_english(text))

    assert len(stub_llm) == 1                       # spend is bounded
    assert result.status == lang.STATUS_PARTIAL
    assert "translation length limit" in result.text


def test_length_limit_notice_is_not_mistaken_for_ocr_failure(monkeypatch, stub_llm):
    """core/extraction.py drops documents whose text matches 'failed'."""
    from app.core.extraction import is_usable_ocr

    monkeypatch.setattr(lang, "TRANSLATION_MAX_CHARS", len(HINDI_PARA) + 10)
    text = "\n--- Page 1 ---\n".join([HINDI_PARA] * 4)
    assert is_usable_ocr(run(lang.translate_to_english(text)).text)


# ── Downstream compatibility ─────────────────────────────────────────────────

def test_translated_output_is_usable_ocr(stub_llm):
    from app.core.extraction import is_usable_ocr
    result = run(lang.translate_to_english("\n\n".join([HINDI_PARA, HINDI_PARA_2])))
    assert is_usable_ocr(result.text)


def test_translation_does_not_make_a_document_look_like_a_template(stub_llm):
    """looks_like_template() counts placeholder patterns; a translation must not
    trip it, or the document is dropped from the drafting prompt entirely."""
    from app.core.extraction import looks_like_template
    result = run(lang.translate_to_english("\n\n".join([HINDI_PARA, HINDI_PARA_2])))
    assert not looks_like_template(result.text)
