"""
Which citations /drafts/generate uses.

Regression guarded here: the branch used to test `selected_judgments is not None`,
but `[] is not None` is True. So whenever Step 6 produced an empty selection —
suggest-citations errored, or the user advanced before results arrived — the
"user pre-selected" branch was taken with empty lists, the RAG fallback never
ran, and the draft was generated with no authorities at all.

An empty selection now falls back to retrieval. One list empty and the other
populated is a deliberate choice and is still respected.
"""

import asyncio

import pytest

import app.api.v1.drafting as D


JUDGMENT = {"id": 1, "title": "Arnesh Kumar v. State of Bihar", "case_number": "Crl A 1277/2014",
            "year": 2014, "holding": "Arrest must not be automatic.", "text": "t", "score": 1.0}
STATUTE = {"id": 2, "title": "Section 438 CrPC", "text": "When any person...", "score": 1.0}

_FALLBACK = "REACHED_RAG_FALLBACK"
_ASSEMBLED = "REACHED_ASSEMBLE"


@pytest.fixture
def route(monkeypatch):
    """Run _rag_stream far enough to see which branch it took, without hitting
    the network: the RAG path stops at rewrite_queries, the selection path at
    assemble_prompt."""
    captured = {}

    def fake_assemble(*args, **kwargs):
        captured["judgments"] = kwargs.get("judgment_results")
        captured["statutes"] = kwargs.get("statute_results")
        raise RuntimeError(_ASSEMBLED)

    async def fake_rewrite(*args, **kwargs):
        raise RuntimeError(_FALLBACK)

    monkeypatch.setattr(D, "assemble_prompt", fake_assemble)
    monkeypatch.setattr(D, "rewrite_queries", fake_rewrite)

    def _run(selected_judgments, selected_statutes):
        req = D.GenerateRequest(
            document_type="Anticipatory Bail", document_type_key="anticipatory_bail",
            court_display="High Court", subject_matter="Criminal Law",
            facts_of_case="Facts", petitioners=["A"], respondents=["B"], relief_sought="R",
            selected_judgments=selected_judgments, selected_statutes=selected_statutes,
        )

        async def drain():
            async for _ in D._rag_stream(req):
                pass

        try:
            asyncio.run(drain())
        except RuntimeError as exc:
            if _FALLBACK in str(exc):
                return "fallback", captured
            if _ASSEMBLED in str(exc):
                return "selection", captured
            raise
        return "completed", captured

    return _run


def test_no_selection_at_all_uses_retrieval(route):
    branch, _ = route(None, None)
    assert branch == "fallback"


def test_empty_selection_falls_back_to_retrieval(route):
    """The regression: a draft must never be written with zero authorities just
    because Step 6 returned nothing."""
    branch, _ = route([], [])
    assert branch == "fallback"


def test_judgments_only_selection_is_respected(route):
    branch, captured = route([JUDGMENT], [])
    assert branch == "selection"
    assert len(captured["judgments"]) == 1
    assert captured["statutes"] == []


def test_statutes_only_selection_is_respected(route):
    branch, captured = route([], [STATUTE])
    assert branch == "selection"
    assert captured["judgments"] == []
    assert len(captured["statutes"]) == 1


def test_normal_selection_is_passed_through_untouched(route):
    branch, captured = route([JUDGMENT], [STATUTE])
    assert branch == "selection"
    assert captured["judgments"][0]["title"] == "Arnesh Kumar v. State of Bihar"
    assert captured["statutes"][0]["title"] == "Section 438 CrPC"


def test_selected_citations_render_into_the_prompt():
    """End-to-end through the real assemble_prompt: what Step 6 selected must
    appear in the RELEVANT STATUTES / PRECEDENTS blocks."""
    from app.core.rag import assemble_prompt

    prompt = assemble_prompt(
        {"document_type": "Anticipatory Bail", "document_type_key": "anticipatory_bail",
         "court_display": "High Court", "subject_matter": "Criminal Law",
         "petitioners": ["A"], "respondents": ["B"], "facts_of_case": "F",
         "grounds": "", "relief_sought": "R", "mandatory_paragraphs": "",
         "dates_and_events": []},
        [JUDGMENT], [STATUTE], uploaded_docs_context="",
    )
    assert "Arnesh Kumar v. State of Bihar" in prompt
    assert "Section 438 CrPC" in prompt
    assert "[No statute sections retrieved]" not in prompt


# ---------------------------------------------------------------------------
# Verbatim paragraph quoting (paragraph picker, Step 6)
# ---------------------------------------------------------------------------
def _prompt_for(judgment):
    from app.core.rag import assemble_prompt
    return assemble_prompt(
        {"document_type": "Anticipatory Bail", "document_type_key": "anticipatory_bail",
         "court_display": "High Court", "subject_matter": "Criminal Law",
         "petitioners": ["A"], "respondents": ["B"], "facts_of_case": "F",
         "grounds": "", "relief_sought": "R", "mandatory_paragraphs": "",
         "dates_and_events": []},
        [judgment], [STATUTE], uploaded_docs_context="",
    )


PARA_TEXT = ("43. Article 28 deals with the rights of individuals and secures to "
             "them the right not to take part in any religious instruction.")


def test_quoted_paragraph_reaches_the_prompt_verbatim():
    """The advocate ticked paragraph 43 — it must arrive whole, not summarised."""
    judgment = {**JUDGMENT, "quoted_paragraph_texts": [
        {"label": "43", "text": PARA_TEXT, "uncertain": False}]}
    prompt = _prompt_for(judgment)
    assert PARA_TEXT in prompt
    # The rendered marker, not the phrase "VERBATIM QUOTE" — that also appears in
    # the standing citation rules in base_rules.txt.
    assert "VERBATIM QUOTE — paragraph 43 of Arnesh Kumar v. State of Bihar" in prompt


def test_uncertain_paragraph_range_is_flagged_to_the_model():
    """A lost OCR marker means the block spans 5-6; the model must be told so it
    does not introduce the quote under a single wrong paragraph number."""
    judgment = {**JUDGMENT, "quoted_paragraph_texts": [
        {"label": "5-6", "text": PARA_TEXT, "uncertain": True}]}
    prompt = _prompt_for(judgment)
    assert "paragraphs 5-6" in prompt
    assert "scan lost a marker" in prompt


def test_multiple_quoted_paragraphs_all_render():
    judgment = {**JUDGMENT, "quoted_paragraph_texts": [
        {"label": "43", "text": "43. First selected paragraph.", "uncertain": False},
        {"label": "44", "text": "44. Second selected paragraph.", "uncertain": False}]}
    prompt = _prompt_for(judgment)
    assert "43. First selected paragraph." in prompt
    assert "44. Second selected paragraph." in prompt


_RENDERED_QUOTE_MARKER = "Reproduce this text EXACTLY"


def test_low_ranked_judgment_with_a_quote_is_never_truncated():
    """Regression: the prompt took a flat judgment_results[:5].

    Step 6 lists judgments in rerank order, so anything the advocate ticked
    beyond the fifth was silently dropped — and the casualties were exactly the
    low-relevance authorities a user deliberately went and picked a paragraph
    from. The quote must survive regardless of rank.
    """
    from app.core.rag import assemble_prompt

    filler = [{**JUDGMENT, "id": i, "title": f"Filler Case {i}"} for i in range(9)]
    picked = {**JUDGMENT, "id": 99, "title": "Low Relevance Authority",
              "quoted_paragraph_texts": [
                  {"label": "43", "text": PARA_TEXT, "uncertain": False}]}

    prompt = assemble_prompt(
        {"document_type": "Anticipatory Bail", "document_type_key": "anticipatory_bail",
         "court_display": "High Court", "subject_matter": "Criminal Law",
         "petitioners": ["A"], "respondents": ["B"], "facts_of_case": "F",
         "grounds": "", "relief_sought": "R", "mandatory_paragraphs": "",
         "dates_and_events": []},
        filler + [picked], [STATUTE], uploaded_docs_context="",
    )
    assert "Low Relevance Authority" in prompt
    assert PARA_TEXT in prompt


def test_judgment_without_quotes_is_unchanged():
    """Citations with no paragraph picked must render exactly as before."""
    prompt = _prompt_for(JUDGMENT)
    assert _RENDERED_QUOTE_MARKER not in prompt
    assert "Arnesh Kumar v. State of Bihar" in prompt


def test_empty_quoted_text_is_skipped():
    judgment = {**JUDGMENT, "quoted_paragraph_texts": [
        {"label": "43", "text": "   ", "uncertain": False}]}
    assert _RENDERED_QUOTE_MARKER not in _prompt_for(judgment)


def test_attach_quoted_paragraphs_resolves_selected_numbers(monkeypatch):
    """_attach_quoted_paragraphs keeps only the paragraphs that were ticked."""
    async def fake_get(engine, judgment_id, chunk_id, chunk_index, include_all, clean):
        return {"paragraphs": [
            {"para_number": 42, "label": "42", "text": "not selected",
             "number_uncertain": False},
            {"para_number": 43, "label": "43", "text": PARA_TEXT,
             "number_uncertain": False},
        ]}

    import app.core.paragraph_service as PS
    monkeypatch.setattr(PS, "get_judgment_paragraphs", fake_get)

    judgments = [{**JUDGMENT, "quoted_paragraphs": [43]}]
    asyncio.run(D._attach_quoted_paragraphs(judgments))

    quoted = judgments[0]["quoted_paragraph_texts"]
    assert [q["label"] for q in quoted] == ["43"]
    assert quoted[0]["text"] == PARA_TEXT


def test_attach_quoted_paragraphs_survives_a_backend_failure(monkeypatch):
    """A paragraph fetch failure must never abort the draft."""
    async def boom(**kwargs):
        raise RuntimeError("neon unavailable")

    import app.core.paragraph_service as PS
    monkeypatch.setattr(PS, "get_judgment_paragraphs", boom)

    judgments = [{**JUDGMENT, "quoted_paragraphs": [43]}]
    asyncio.run(D._attach_quoted_paragraphs(judgments))
    assert "quoted_paragraph_texts" not in judgments[0]


def test_attach_quoted_paragraphs_noop_without_selection(monkeypatch):
    def explode(**kwargs):
        raise AssertionError("must not query when nothing was ticked")

    import app.core.paragraph_service as PS
    monkeypatch.setattr(PS, "get_judgment_paragraphs", explode)
    asyncio.run(D._attach_quoted_paragraphs([dict(JUDGMENT)]))
