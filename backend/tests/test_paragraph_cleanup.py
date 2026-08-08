"""The verification gate on LLM paragraph cleanup.

The cleanup pass exists only to strip OCR artefacts from a paragraph before it is
block-quoted in a filed document. If the model paraphrases instead of tidying,
the output must be thrown away — a reworded "quotation" attributed to a judge is
the worst failure this feature could produce. These tests pin that behaviour.
"""

import asyncio

import app.core.paragraph_service as PS


ORIGINAL = (
    "43. Article 28 deals with the rights of individuals and secures to them, "
    "vide clause (3), the right not to take part in any religious instruction "
    "that may be imparted in any educational institution."
)


# ---------------------------------------------------------------------------
# fidelity()
# ---------------------------------------------------------------------------
def test_fidelity_identical_text():
    assert PS.fidelity(ORIGINAL, ORIGINAL) == 1.0


def test_fidelity_ignores_punctuation_and_case():
    """Straight vs curly quotes and spacing must not count as a rewrite."""
    variant = ORIGINAL.replace("(3)", "(3),").replace(",", "").upper()
    assert PS.fidelity(ORIGINAL, variant) >= PS.CLEANUP_MIN_FIDELITY


def test_fidelity_accepts_removal_of_a_running_header():
    """Deleting page furniture is the whole point of the cleanup pass."""
    with_header = ORIGINAL.replace(
        "secures to them",
        "secures to them 318 [2024] 11 S.C.R. Digital Supreme Court Reports",
    )
    assert PS.fidelity(with_header, ORIGINAL) >= PS.CLEANUP_MIN_FIDELITY


def test_fidelity_rejects_a_paraphrase():
    paraphrase = ("Article 28 says people cannot be forced into religious "
                  "classes at school.")
    assert PS.fidelity(ORIGINAL, paraphrase) < PS.CLEANUP_MIN_FIDELITY


def test_fidelity_alone_does_not_catch_truncation():
    """Deletion is free under fidelity by design — retention is the guard.

    Cut on a word boundary so every returned token is genuine; that is the case
    fidelity cannot see, and the one retention exists for.
    """
    clean_cut = "43. Article 28 deals with the rights of individuals"
    assert PS.fidelity(ORIGINAL, clean_cut) == 1.0
    assert PS.retention(ORIGINAL, clean_cut) < PS.CLEANUP_MIN_RETENTION


def test_retention_accepts_header_removal():
    with_header = ORIGINAL.replace(
        "secures to them",
        "secures to them 318 [2024] 11 S.C.R. Digital Supreme Court Reports",
    )
    assert PS.retention(with_header, ORIGINAL) >= PS.CLEANUP_MIN_RETENTION


def test_fidelity_handles_empty_input():
    assert PS.fidelity("", ORIGINAL) == 0.0
    assert PS.fidelity(ORIGINAL, "") == 0.0
    assert PS.retention("", ORIGINAL) == 0.0


# ---------------------------------------------------------------------------
# _clean_one — the gate itself
# ---------------------------------------------------------------------------
class _FakeClient:
    """Minimal stand-in for the OpenRouter async client."""

    def __init__(self, payload):
        self._payload = payload
        outer = self

        class _Completions:
            async def create(self, **kwargs):
                return outer._payload

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def _response(content: str):
    class _Msg:
        message = type("m", (), {"content": content})

    return type("r", (), {"choices": [_Msg()]})


def test_clean_one_accepts_a_faithful_tidy_up():
    tidied = ORIGINAL.replace("  ", " ")
    client = _FakeClient(_response('{"paragraph": %s}' % _json(tidied)))
    out = asyncio.run(PS._clean_one(client, ORIGINAL))
    assert out == tidied


def test_clean_one_discards_a_paraphrase_and_keeps_the_source():
    bad = "Article 28 means schools cannot force religion on students."
    client = _FakeClient(_response('{"paragraph": %s}' % _json(bad)))
    out = asyncio.run(PS._clean_one(client, ORIGINAL))
    assert out == ORIGINAL


def test_clean_one_falls_back_on_malformed_json():
    client = _FakeClient(_response("not json at all"))
    assert asyncio.run(PS._clean_one(client, ORIGINAL)) == ORIGINAL


def test_clean_one_discards_a_truncated_paragraph():
    """A model that returns only the first sentence must not silently shorten
    the quote — every word is genuine, but the paragraph is no longer whole."""
    clean_cut = "43. Article 28 deals with the rights of individuals"
    client = _FakeClient(_response('{"paragraph": %s}' % _json(clean_cut)))
    assert asyncio.run(PS._clean_one(client, ORIGINAL)) == ORIGINAL


def test_clean_one_accepts_header_removal():
    """The case that a symmetric similarity score used to reject."""
    with_header = ORIGINAL.replace(
        "secures to them",
        "secures to them 318 [2024] 11 S.C.R. Digital Supreme Court Reports",
    )
    client = _FakeClient(_response('{"paragraph": %s}' % _json(ORIGINAL)))
    assert asyncio.run(PS._clean_one(client, with_header)) == ORIGINAL


def test_clean_one_falls_back_on_empty_paragraph():
    client = _FakeClient(_response('{"paragraph": ""}'))
    assert asyncio.run(PS._clean_one(client, ORIGINAL)) == ORIGINAL


def test_clean_one_strips_markdown_fences():
    tidied = ORIGINAL
    client = _FakeClient(_response("```json\n{\"paragraph\": %s}\n```" % _json(tidied)))
    assert asyncio.run(PS._clean_one(client, ORIGINAL)) == tidied


def test_clean_one_survives_an_api_error():
    class _Exploding:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):
                    raise RuntimeError("upstream 503")

    assert asyncio.run(PS._clean_one(_Exploding(), ORIGINAL)) == ORIGINAL


def test_clean_paragraph_texts_is_a_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(PS, "CLEANUP_ENABLED", False)
    texts = [ORIGINAL, "2. Another paragraph."]
    assert asyncio.run(PS.clean_paragraph_texts(texts)) == texts


def _json(s: str) -> str:
    import json
    return json.dumps(s)
