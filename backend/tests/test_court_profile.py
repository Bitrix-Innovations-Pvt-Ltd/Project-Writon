"""
Unit tests for core/court_profile.py and the prompt assembly that consumes it.

These encode the conventions taken from a filed Allahabad (Lucknow) CRLP paper
book, and — just as importantly — that no other court's output changed. The
profile is opt-in by design: a wrong house style is a listing objection, so a
court we have never seen a filing from must keep its previous behaviour.
"""

import re

import pytest

from app.core.court_profile import (
    body_section,
    court_profile,
    has_interim_relief,
    required_sections,
)
from app.core.rag import assemble_prompt


ALLAHABAD = ("high", "Allahabad High Court - Lucknow")
SUPREME = ("supreme", "Supreme Court of India")
DELHI = ("high", "Delhi High Court")

_BASE = dict(
    petitioners=["Pawan Kumar Kori"],
    respondents=["State of U.P."],
    facts_of_case="FIR No. 87/2026 was registered at P.S. Munshiganj.",
    relief_sought="Quash the FIR.",
    dates_and_events=[{"date": "15.07.2026", "event": "victim left her house"}],
    advocate_name="Balkeshwar Srivastava",
    advocate_enrollment_no="1983/2000",
    document_type="Writ Petition",
)


def _prompt(court, interim="", key="writ_petition_criminal", **extra):
    level, display = court
    form = {
        **_BASE,
        "document_type_key": key,
        "court_level": level,
        "court_display": display,
        "interim_relief_sought": interim,
        **extra,
    }
    return assemble_prompt(form, [], [])


def _sections(prompt):
    """The rendered REQUIRED SECTIONS list, in order."""
    block = prompt[prompt.find("REQUIRED SECTIONS — write these"):]
    out = []
    for line in block.splitlines()[1:]:
        m = re.match(r"^(\d+)\. ([A-Z_]+)$", line.strip())
        if not m:
            break                       # the list ends at the first non-entry
        out.append(m.group(2))
    return out


# ── Profile selection ────────────────────────────────────────────────────────

@pytest.mark.parametrize("display", [
    "Allahabad High Court - Lucknow",
    "Allahabad High Court",
    "allahabad high court - lucknow",
    "Lucknow Bench",
])
def test_allahabad_variants_all_resolve(display):
    assert court_profile("high", display).key == "allahabad"


@pytest.mark.parametrize("display", [
    "Delhi High Court", "Bombay High Court", "Madras High Court", "",
])
def test_other_courts_get_the_default_profile(display):
    assert court_profile("high", display).key == "default"


def test_supreme_court_never_takes_a_high_court_profile():
    """A Supreme Court matter that merely mentions a city must not inherit
    Allahabad's house style."""
    assert court_profile("supreme", "Supreme Court of India, Lucknow registry").key == "default"


@pytest.mark.parametrize("level,display", [
    ("district", "Lucknow District Court, Uttar Pradesh"),
    ("district", "Allahabad District Court, Uttar Pradesh"),
    ("tribunal", "Lucknow Bench, Central Administrative Tribunal"),
    ("tribunal", "Allahabad Bench, Armed Forces Tribunal"),
])
def test_city_name_alone_does_not_confer_the_high_court_profile(level, display):
    """These are Allahabad HIGH COURT conventions. court_display for a district
    court is "Lucknow District Court, Uttar Pradesh" and for a tribunal
    "Lucknow Bench, ..." — both contain the city, neither files a High Court
    paper book. A district pleading must not say "Opposite Parties" or carry a
    Code/Group/District header."""
    assert court_profile(level, display).key == "default"


def test_only_the_high_court_level_gets_allahabad():
    assert court_profile("high", "Allahabad High Court - Lucknow").key == "allahabad"
    for level in ("district", "tribunal", "supreme", "", None):
        assert court_profile(level, "Allahabad High Court - Lucknow").key == "default"


def test_default_profile_preserves_previous_behaviour():
    p = court_profile("high", "Delhi High Court")
    assert p.respondent_label == "Respondents"
    assert p.wants_synopsis and p.drafts_vakalatnama
    assert not p.wants_oath_commissioner and not p.wants_identification_block
    assert not p.filing_header_fields


def test_allahabad_profile_matches_the_filed_paper_book():
    p = court_profile("high", "Allahabad High Court - Lucknow")
    assert p.respondent_label == "Opposite Parties"
    assert p.respondent_label_singular == "Opposite Party"
    assert p.uses_opposite_parties
    assert not p.wants_synopsis          # the filed CRLP has none
    assert not p.drafts_vakalatnama      # separate stamped form, index entry only
    assert p.wants_identification_block and p.wants_oath_commissioner
    assert p.filing_header_fields == ("Code", "Group", "District")
    labels = [lbl for lbl, _ in p.signature_lines]
    assert labels == ["Reg. No.", "On Roll No.", "Mobile No."]


# ── Section ordering ─────────────────────────────────────────────────────────

def test_interim_relief_comes_directly_after_dates_and_events():
    """The review point: in the filed index, Application for Interim Relief is
    item 2, immediately after Date and Events."""
    secs = _sections(_prompt(ALLAHABAD, interim="Stay the arrest pending disposal."))
    assert secs.index("INTERIM_RELIEF_APPLICATION") == secs.index("LIST_OF_DATES") + 1
    assert secs.index("INTERIM_RELIEF_APPLICATION") < secs.index("MAIN_PETITION")


def test_no_interim_section_when_none_was_requested():
    assert "INTERIM_RELIEF_APPLICATION" not in _sections(_prompt(ALLAHABAD))


@pytest.mark.parametrize("value", [
    "", "   ", "Not specifically requested", "N/A", "none", "nil", "n/a", None, 42,
])
def test_placeholder_interim_values_do_not_create_an_empty_application(value):
    assert not has_interim_relief({"interim_relief_sought": value})


def test_real_interim_text_is_detected():
    assert has_interim_relief({
        "interim_relief_sought": "Stay the arrest of the petitioners pending disposal."
    })


def test_allahabad_drops_synopsis_and_vakalatnama():
    secs = _sections(_prompt(ALLAHABAD))
    assert "SYNOPSIS" not in secs and "VAKALATNAMA" not in secs


def test_other_courts_keep_synopsis_and_vakalatnama():
    for court in (SUPREME, DELHI):
        secs = _sections(_prompt(court))
        assert "SYNOPSIS" in secs and "VAKALATNAMA" in secs


def test_bail_application_has_no_front_matter():
    secs = _sections(_prompt(ALLAHABAD, key="bail_application"))
    assert "LIST_OF_DATES" not in secs and "SYNOPSIS" not in secs
    assert "MAIN_APPLICATION" in secs


@pytest.mark.parametrize("key,expected", [
    ("bail_application", "MAIN_APPLICATION"),
    ("anticipatory_bail", "MAIN_APPLICATION"),
    ("civil_appeal", "MEMORANDUM_OF_APPEAL"),
    ("criminal_appeal", "MEMORANDUM_OF_APPEAL"),
    ("writ_petition_criminal", "MAIN_PETITION"),
    ("", "MAIN_PETITION"),
])
def test_body_section_naming(key, expected):
    assert body_section(key) == expected
    assert expected in required_sections(court_profile(), key)


def test_cover_and_index_is_always_first():
    for court in (ALLAHABAD, SUPREME, DELHI):
        for key in ("writ_petition_criminal", "bail_application", "civil_appeal"):
            assert _sections(_prompt(court, key=key))[0] == "COVER_AND_INDEX"


def test_annexures_is_always_last():
    for court in (ALLAHABAD, SUPREME, DELHI):
        assert _sections(_prompt(court, interim="Stay it pending disposal."))[-1] == "ANNEXURES"


# ── Rendered prompt content ──────────────────────────────────────────────────

def test_allahabad_prompt_uses_opposite_parties_and_never_respondent_label():
    out = _prompt(ALLAHABAD)
    assert "Opposite Parties" in out
    assert ".......Respondents" not in out


def test_other_courts_still_say_respondents():
    out = _prompt(DELHI)
    assert "Respondents" in out and "Opposite Parties" not in out


def test_allahabad_signature_block_carries_on_roll_and_mobile():
    out = _prompt(ALLAHABAD)
    for line in ("Reg. No.", "On Roll No.", "Mobile No."):
        assert line in out
    assert "1983/2000" in out          # the enrollment value reaches Reg. No.


def test_default_signature_block_is_unchanged():
    out = _prompt(DELHI)
    assert "Enrollment No." in out
    assert "On Roll No." not in out and "Mobile No." not in out


def test_filing_header_only_for_allahabad():
    assert "Code" in _prompt(ALLAHABAD) and "Group" in _prompt(ALLAHABAD)
    assert "8C. FILING HEADER" not in _prompt(DELHI)


def test_oath_commissioner_block_only_for_allahabad():
    assert "OATH COMMISSIONER" in _prompt(ALLAHABAD)
    for court in (SUPREME, DELHI):
        out = _prompt(court)
        assert "OATH COMMISSIONER" not in out and "IDENTIFICATION" not in out


def test_interim_guidance_absent_unless_requested():
    assert "APPLICATION FOR INTERIM RELIEF" not in _prompt(ALLAHABAD)
    assert "APPLICATION FOR INTERIM RELIEF" in _prompt(
        ALLAHABAD, interim="Stay the arrest pending disposal.")


# ── Dates & Events rules ─────────────────────────────────────────────────────

def test_events_may_be_expanded_but_dates_may_not():
    """The old rule forbade altering any row, which capped event detail at
    whatever was typed into the form."""
    out = _prompt(ALLAHABAD)
    assert "DATE COLUMN — IMMUTABLE" in out
    assert "EVENT COLUMN — EXPAND IT" in out
    # The blanket prohibition must be gone, or the two rules contradict.
    assert "VERBATIM in a markdown table" not in out


def test_event_expansion_is_sourced_and_bounded():
    out = _prompt(ALLAHABAD)
    assert "appear verbatim in the FACTS OF THE CASE or UPLOADED DOCUMENTS" in out
    assert "Inventing a particular to make a row look fuller" in out


def test_every_row_is_reworded_even_without_a_source():
    """A date the advocate types in by hand has no corroborating material in the
    facts or the uploaded documents. It must still be rewritten into pleading
    prose — only the *particulars* require a source, not the wording."""
    out = _prompt(ALLAHABAD)
    assert "ALWAYS, FOR EVERY ROW WITHOUT EXCEPTION" in out
    assert "including a row the advocate typed in by hand" in out
    assert "NEVER copy a bare fragment through into the table" in out
    # ...and the two operations must stay distinguishable to the model.
    assert "REWRITE THE LANGUAGE" in out and "ADD THE PARTICULARS" in out


def test_sourceless_rows_are_not_pushed_into_invention_by_a_length_target():
    """The length target must yield to the source rule, or a hand-typed row gets
    padded with invented particulars to reach it."""
    out = _prompt(ALLAHABAD)
    assert "one complete, properly worded sentence is correct and sufficient" in out
    assert "Length is set by how much you were actually told" in out


def test_hence_this_petition_terminal_row_is_required():
    assert "Hence this Petition." in _prompt(ALLAHABAD)


# ── Regression guards ────────────────────────────────────────────────────────

def test_every_template_renders_for_every_profile():
    keys = ["writ_petition", "writ_petition_civil", "writ_petition_criminal",
            "bail_application", "anticipatory_bail", "civil_appeal", "criminal_appeal"]
    for key in keys:
        for court in (ALLAHABAD, SUPREME, DELHI):
            for interim in ("", "Stay the arrest pending disposal."):
                out = _prompt(court, interim=interim, key=key)
                assert len(out) > 2000
                assert "{{" not in out and "{%" not in out   # nothing left unrendered


def test_section_list_has_no_duplicates():
    for court in (ALLAHABAD, SUPREME, DELHI):
        secs = _sections(_prompt(court, interim="Stay it pending disposal."))
        assert len(secs) == len(set(secs))


def test_prayer_lettering_and_centred_headings_are_specified():
    out = _prompt(ALLAHABAD)
    assert "(A), (B), (C)" in out
    assert "SECTION HEADINGS ARE CENTRED" in out


def test_annexure_labelling_convention():
    assert "Annexure No. 1" in _prompt(ALLAHABAD)
