"""
The foot-of-page filing block, the one date format, and the standard affidavit.

Three client changes are encoded here:

  * PLACE and DATED were printed as two empty rules on every page of every
    section. PLACE is derivable — it is the seat of the court, or the bench the
    advocate selected — and DATED is derivable down to the day, which nobody can
    know at drafting time because the paper book is filed later.
  * Every date in the draft reads DD/MM/YYYY. The form stores YYYY-MM-DD (that
    is what <input type="date"> gives), so without a filter the model was handed
    ISO dates under a rule telling it to reproduce them exactly.
  * The affidavit is standardised: the same settled paragraphs in every paper
    book, with only the case-specific paragraphs changing.
"""

from datetime import datetime

import pytest

from app.core.court_profile import deponent_terms, filing_place
from app.core.rag import assemble_prompt, to_ddmmyyyy


_BASE = dict(
    petitioners=["Pawan Kumar Kori"],
    respondents=["State of U.P."],
    facts_of_case="FIR No. 87/2026 was registered at P.S. Munshiganj.",
    relief_sought="Quash the FIR.",
    dates_and_events=[{"date": "2026-07-15", "event": "victim left her house"}],
    advocate_name="Balkeshwar Srivastava",
    advocate_enrollment_no="1983/2000",
    document_type="Writ Petition",
)


def _prompt(level="high", display="Allahabad High Court - Lucknow Bench",
            key="writ_petition_criminal", **extra):
    return assemble_prompt(
        {**_BASE, "document_type_key": key, "court_level": level,
         "court_display": display, **extra},
        [], [],
    )


def _expected_dated():
    return datetime.now().strftime("___/%m/%Y")


# ── PLACE ────────────────────────────────────────────────────────────────────

# high_court_benches.city, exactly as the rows read in the database.
@pytest.mark.parametrize("city,expected", [
    ("Prayagraj (Allahabad)",                     "Prayagraj"),
    ("Lucknow",                                   "Lucknow"),
    ("Kochi (Ernakulam)",                         "Kochi"),
    ("Ahmedabad (Sola)",                          "Ahmedabad"),
    ("Chhatrapati Sambhajinagar (Aurangabad)",    "Chhatrapati Sambhajinagar"),
    ("Port Blair (Sri Vijaya Puram)",             "Port Blair"),
    ("Srinagar / Jammu (twin wings)",             "Srinagar"),
    ("New Delhi",                                 "New Delhi"),
])
def test_the_bench_city_is_reduced_to_a_bare_city_name(city, expected):
    """The seat rows carry the city's former name in brackets and the twin-wing
    courts carry two cities. A pleading is signed at one city, under the name it
    has now."""
    assert filing_place("high", "", court_place=city) == expected


def test_the_bench_city_wins_over_the_display_string():
    """The authoritative value comes from the bench record; parsing the display
    string is only a fallback for callers that do not send one."""
    assert filing_place(
        "high",
        "High Court of Judicature at Allahabad - Lucknow Bench",
        court_place="Prayagraj (Allahabad)",
    ) == "Prayagraj"


# court_display as the frontend builds it: "<court name> - <bench name>", with
# the bench names exactly as they read in the database.
@pytest.mark.parametrize("level,display,expected", [
    ("supreme", "Supreme Court of India", "New Delhi"),
    ("high", "High Court of Judicature at Allahabad - Prayagraj (Allahabad) - Principal Seat",
     "Prayagraj"),
    ("high", "High Court of Judicature at Allahabad - Lucknow Bench",      "Lucknow"),
    ("high", "High Court of Judicature at Bombay - Nagpur Bench",          "Nagpur"),
    ("high", "High Court of Judicature at Bombay - Mumbai - Principal Seat", "Mumbai"),
    ("high", "High Court of Delhi - New Delhi - Principal Seat",           "New Delhi"),
    ("high", "High Court of Judicature for Rajasthan - Jaipur Bench",      "Jaipur"),
    ("high", "Gauhati High Court - Itanagar Bench",                        "Itanagar"),
    ("high", "High Court of Jammu & Kashmir and Ladakh - Srinagar Wing",   "Srinagar"),
    # No bench selected — fall back to the court's own name.
    ("high", "High Court of Judicature at Bombay",                         "Bombay"),
    ("high", "Allahabad High Court",                                       "Allahabad"),
    ("high", "High Court of Delhi",                                        "Delhi"),
    ("district", "Lucknow District Court, Uttar Pradesh",                  "Lucknow"),
    ("tribunal", "Lucknow Bench, Central Administrative Tribunal",         "Lucknow"),
])
def test_filing_place_is_derived_from_the_court(level, display, expected):
    assert filing_place(level, display) == expected


def test_the_selected_bench_beats_the_court_name():
    """A Lucknow-bench filing is signed at Lucknow, not at Allahabad."""
    assert filing_place(
        "high", "High Court of Judicature at Allahabad - Lucknow Bench") == "Lucknow"


def test_the_court_name_never_leaks_onto_the_place_line():
    """The reported bug: "Principal Seat" cleaned away to nothing, and the
    stripped remainder of the whole display string — the court's own name — was
    printed as the place of filing."""
    for display in (
        "High Court of Judicature at Allahabad - Prayagraj (Allahabad) - Principal Seat",
        "High Court of Judicature at Allahabad - Lucknow Bench",
        "Lucknow Bench, Central Administrative Tribunal",
    ):
        place = filing_place("high", display)
        assert place
        for word in ("court", "judicature", "tribunal", "bench", "seat", " - "):
            assert word not in place.lower(), (display, place)


@pytest.mark.parametrize("level,display", [
    ("tribunal", "Central Administrative Tribunal"),
    ("tribunal", ""),
    ("", ""),
])
def test_underivable_place_stays_blank(level, display):
    """A wrong city printed on every page is worse than the blank line the
    advocate had before, so an unrecognised court derives nothing."""
    assert filing_place(level, display) == ""


def test_place_and_dated_are_filled_into_the_signature_block():
    out = _prompt()
    assert "<strong>PLACE:</strong> Lucknow" in out
    assert f"<strong>DATED:</strong> {_expected_dated()}" in out
    assert "<strong>PLACE:</strong> __________________" not in out


def test_signature_block_keeps_the_blank_for_an_unrecognised_court():
    out = _prompt(level="tribunal", display="Central Administrative Tribunal")
    assert "<strong>PLACE:</strong> __________________" in out
    assert f"<strong>DATED:</strong> {_expected_dated()}" in out


def test_the_model_is_told_not_to_blank_or_reinvent_them():
    out = _prompt()
    assert "PLACE AND DATED ARE ALREADY FILLED IN" in out
    assert "Do NOT invent a day" in out
    # The place of filing is not the place the incident happened.
    assert "is NOT the place of filing" in out


# ── DD/MM/YYYY everywhere ────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("2026-07-15", "15/07/2026"),
    ("15.07.2026", "15/07/2026"),
    ("15-07-2026", "15/07/2026"),
    ("15/07/2026", "15/07/2026"),
    ("15 July 2026", "15/07/2026"),
    (datetime(2026, 7, 15), "15/07/2026"),
    (None, ""),
    ("", ""),
])
def test_dates_render_as_ddmmyyyy(raw, expected):
    assert to_ddmmyyyy(raw) == expected


def test_unparseable_dates_pass_through_untouched():
    """A row the advocate typed by hand is still information — normalising it
    away would silently drop a row from the chronology."""
    assert to_ddmmyyyy("Monsoon session, 2026") == "Monsoon session, 2026"


def test_iso_dates_from_the_form_never_reach_the_model():
    out = _prompt(impugned_order_date="2026-05-20")
    assert "2026-05-20" not in out
    assert "20/05/2026" in out
    assert "| 15/07/2026 |" in out          # the dates & events table


def test_the_date_format_rule_is_stated():
    out = _prompt()
    assert "DATE FORMAT — DD/MM/YYYY, EVERYWHERE" in out
    assert "05/07/2026" in out              # the worked example


def test_immutable_dates_and_the_format_rule_do_not_contradict():
    """1B(a) forbids altering a date; 1A rewrites its punctuation. The prompt
    has to say which one wins, or the model picks."""
    out = _prompt()
    assert "Immutable means the DATE is immutable, not its punctuation" in out


# ── Dates & Events depth ─────────────────────────────────────────────────────

def test_the_event_column_has_a_worked_example():
    """Prose alone was not moving the model off one-line cells. The example
    shows the depth expected and where each particular came from."""
    out = _prompt()
    assert "WORKED EXAMPLE" in out
    assert "WRONG (what you must not write)" in out
    assert "RIGHT:" in out


def test_the_worked_example_is_fenced_off_from_the_draft():
    """A quotable specimen invites the model to quote it — the same failure the
    annexure fallback line caused. The example must be marked as another case."""
    out = _prompt()
    assert "are NOT facts of this matter, and must NEVER appear in your output" in out


def test_the_event_column_has_a_floor_and_a_procedure():
    out = _prompt()
    assert "NOT FEWER THAN 40 WORDS" in out
    assert "THE PROCEDURE FOR EACH ROW" in out
    # The mining step is the one that actually produces a full row.
    assert "mark every sentence that concerns that date" in out


def test_the_depth_check_is_repeated_at_the_end_of_the_prompt():
    """Rule 1B sits thousands of tokens before the model starts writing. The
    check is restated last, next to the section list."""
    out = _prompt()
    assert "DATES & EVENTS — THE DEPTH CHECK" in out
    assert out.index("DATES & EVENTS — THE DEPTH CHECK") > out.index("EVENT COLUMN — EXPAND IT")


def test_the_depth_check_is_absent_where_there_is_no_dates_section():
    """A bail application opens straight into the application body — reminding
    the model about a section it must not write is how a stray section appears."""
    out = _prompt(key="bail_application")
    section_list = out[out.find("REQUIRED SECTIONS — write these"):]
    assert "LIST_OF_DATES" not in section_list
    assert "DATES & EVENTS — THE DEPTH CHECK" not in out


def test_expansion_still_yields_to_the_no_invention_rule():
    """The floor must not license padding a row that has no source."""
    out = _prompt()
    assert "one complete, properly worded sentence is correct and sufficient" in out
    assert "Inventing a particular to make a row look fuller" in out


def test_table_cells_are_protected_from_pipes_and_line_breaks():
    """Multi-sentence cells are only useful if the table still renders."""
    out = _prompt()
    assert "TABLE MECHANICS" in out
    assert "do NOT write a literal" in out


def test_the_filing_date_row_carries_the_current_month():
    out = _prompt(dates_and_events=[])
    assert _expected_dated() in out
    assert "___/___/" not in out


# ── Standard affidavit ───────────────────────────────────────────────────────

STANDARD_OPENING = (
    "That I am the petitioner in the above-mentioned case and am fully "
    "conversant with the facts and circumstances of the case and am competent "
    "to swear this affidavit."
)
STANDARD_CLOSING = (
    "That this petition is being filed bonafide and in the interest of "
    "justice, and not for any collateral purpose."
)


ALL_KEYS = ("writ_petition", "writ_petition_civil", "writ_petition_criminal",
            "bail_application", "anticipatory_bail", "civil_appeal",
            "criminal_appeal")


def test_standard_paragraphs_are_hardcoded_into_every_document():
    for key in ALL_KEYS:
        out = _prompt(key=key)
        assert "THE PARAGRAPHS — COPY EXACTLY" in out
        assert "WORD FOR WORD" in out
        assert "true copies of their respective originals" in out
        assert "no material fact has been concealed or suppressed" in out


def test_standard_paragraphs_use_this_document_type_s_terminology():
    """One set of clauses serves every document, so the deponent has to be named
    correctly — a bail matter has an applicant, an appeal an appellant."""
    assert STANDARD_OPENING in _prompt(key="writ_petition_criminal")
    assert STANDARD_CLOSING in _prompt(key="writ_petition_criminal")
    assert "That I am the applicant in the above-mentioned case" in _prompt(
        key="anticipatory_bail")
    assert "That I am the appellant in the above-mentioned case" in _prompt(
        key="criminal_appeal")
    assert "this appeal is being filed bonafide" in _prompt(key="civil_appeal")


@pytest.mark.parametrize("key,role,document", [
    ("bail_application",       "applicant",  "application"),
    ("anticipatory_bail",      "applicant",  "application"),
    ("civil_appeal",           "appellant",  "appeal"),
    ("criminal_appeal",        "appellant",  "appeal"),
    ("writ_petition_criminal", "petitioner", "petition"),
    ("",                       "petitioner", "petition"),
])
def test_deponent_terms(key, role, document):
    terms = deponent_terms(key)
    assert (terms.role, terms.document) == (role, document)


def test_the_affidavit_is_a_closed_list_of_four_paragraphs():
    """The drafted affidavit ran to ten paragraphs because the model was told to
    add case-specific ones. The facts are pleaded in the body; the affidavit
    only verifies them."""
    out = _prompt()
    assert "THE NUMBERED PARAGRAPHS ARE A CLOSED LIST" in out
    assert "There are FOUR numbered paragraphs in this document — no more." in out
    assert "Do NOT add a paragraph of your own." in out


def test_the_closed_list_grows_by_exactly_one_for_a_cancellation():
    out = _prompt(
        key="anticipatory_bail",
        relief_sought="Cancel the anticipatory bail granted to the accused.",
    )
    assert "There are FIVE numbered paragraphs in this document — no more." in out
    assert "There are FOUR numbered paragraphs" not in out


def test_the_model_is_told_which_paragraphs_it_keeps_reaching_for():
    """A bare count does not stop it — the drafted affidavit's extra paragraphs
    narrated the FIR, the parties and the conduct complained of."""
    out = _prompt()
    for topic in ("the FIR", "the parties", "the impugned order", "the dates",
                  "the conduct complained of", "the urgency", "the grounds"):
        assert topic in out
    assert "If you find yourself writing a paragraph that states a fact of THIS case, delete it." in out


def test_no_document_type_asks_for_case_specific_paragraphs():
    for key in ALL_KEYS:
        out = _prompt(key=key)
        assert "case-specific paragraph" not in out.lower()


def test_verification_is_fixed_form_and_dated_like_everything_else():
    out = _prompt()
    assert "VERIFICATION — FIXED FORM" in out
    assert f"Verified at Lucknow on this {_expected_dated()}." in out


def test_bail_cancellation_clause_only_where_cancellation_is_sought():
    """The client's cancellation clause is the opposite of what an application
    FOR bail deposes to, and both are drafted from the bail templates."""
    cancellation = _prompt(
        key="anticipatory_bail",
        relief_sought="Cancel the anticipatory bail granted to the accused.",
    )
    assert "warranting cancellation of the anticipatory bail" in cancellation

    for_bail = _prompt(
        key="anticipatory_bail",
        relief_sought="Release the applicant on anticipatory bail in the event of arrest.",
    )
    assert "warranting cancellation" not in for_bail


def test_affidavit_rules_render_for_every_court_profile():
    for level, display in (("high", "Allahabad High Court - Lucknow Bench"),
                           ("supreme", "Supreme Court of India"),
                           ("high", "Delhi High Court")):
        out = _prompt(level=level, display=display)
        assert "{{" not in out and "{%" not in out
        assert "THE PARAGRAPHS — COPY EXACTLY" in out
