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
