"""
core/court_profile.py — per-court drafting conventions.

Indian courts do not share a house style. An Allahabad High Court writ petition
labels the other side "Opposite Parties", carries a Code/Group/District block at
the head of the index, has no synopsis, and ends its affidavit with an advocate
Identification and an Oath Commissioner attestation. A Supreme Court SLP does
none of those things and *requires* a synopsis.

Before this module those conventions lived nowhere: base_rules.txt hardcoded
".......Respondent" for every court in the country, and each of the seven
document templates carried its own copy of the section list.

The profile is the single seam for "how does THIS court want it". It is a plain
dict today, which keeps it diffable, testable and reviewable; if it ever needs to
be editable without a deploy, `court_profile()` is the one function that has to
change to read from a table instead.

SCOPE NOTE — the Allahabad profile is derived from one filed petition (a Lucknow
CRLP). Where the evidence only covers Allahabad, the change is scoped to
Allahabad and every other court keeps its previous behaviour. Widening a
convention to courts we have not seen a filing from would be a guess, and a
wrong house style is a listing objection.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

# ── Section names ────────────────────────────────────────────────────────────
COVER_AND_INDEX = "COVER_AND_INDEX"
SYNOPSIS = "SYNOPSIS"
LIST_OF_DATES = "LIST_OF_DATES"
INTERIM_RELIEF_APPLICATION = "INTERIM_RELIEF_APPLICATION"
PRAYER = "PRAYER"
AFFIDAVIT = "AFFIDAVIT"
VAKALATNAMA = "VAKALATNAMA"
ANNEXURES = "ANNEXURES"

# The body section is named differently per document family; the templates used
# to hardcode this alongside their own copy of the whole section list.
_BODY_SECTIONS = {
    "bail_application": "MAIN_APPLICATION",
    "anticipatory_bail": "MAIN_APPLICATION",
    "civil_appeal": "MEMORANDUM_OF_APPEAL",
    "criminal_appeal": "MEMORANDUM_OF_APPEAL",
}
_DEFAULT_BODY_SECTION = "MAIN_PETITION"

# Document families that carry a Dates & Events / Synopsis front section at all.
# A bail application does not — it opens straight into the application body.
_FRONT_MATTER_TYPES = {
    "civil_appeal",
    "criminal_appeal",
    "writ_petition",
    "writ_petition_civil",
    "writ_petition_criminal",
}


def body_section(document_type_key: str) -> str:
    """MAIN_PETITION / MAIN_APPLICATION / MEMORANDUM_OF_APPEAL."""
    return _BODY_SECTIONS.get(document_type_key or "", _DEFAULT_BODY_SECTION)


# ── Deponent terminology ─────────────────────────────────────────────────────
# The affidavit is standardised across documents, but the deponent is not called
# the same thing in each: a bail matter has an applicant, an appeal an appellant.
# The standard clauses in prompts/affidavit_clauses.txt read from here so that
# one set of hardcoded paragraphs serves every document type.

@dataclass(frozen=True)
class DeponentTerms:
    role: str          # "petitioner"  — used mid-sentence
    role_title: str    # "Petitioner"  — used at the head of a sentence
    document: str      # "petition"    — what the affidavit is filed in support of


_DEPONENT_TERMS = {
    "bail_application":  DeponentTerms("applicant", "Applicant", "application"),
    "anticipatory_bail": DeponentTerms("applicant", "Applicant", "application"),
    "civil_appeal":      DeponentTerms("appellant", "Appellant", "appeal"),
    "criminal_appeal":   DeponentTerms("appellant", "Appellant", "appeal"),
}
_DEFAULT_DEPONENT = DeponentTerms("petitioner", "Petitioner", "petition")


def deponent_terms(document_type_key: str = "") -> DeponentTerms:
    """What this document type calls the person swearing the affidavit."""
    return _DEPONENT_TERMS.get(document_type_key or "", _DEFAULT_DEPONENT)


# ── Filing place ─────────────────────────────────────────────────────────────
# "PLACE:" at the foot of every section is the city the pleading is signed and
# filed at — the seat of the court or, where the court sits in more than one
# city, the bench the advocate selected. It was previously printed as a blank
# line for the advocate to fill in by hand on every page of the paper book.

_SUPREME_COURT_SEAT = "New Delhi"

# Words that decorate a seat name without being part of the city.
_SEAT_NOISE = re.compile(
    r"\b(principal\s+seat|permanent\s+bench|circuit\s+bench|circuit\s+sitting"
    r"|bench(?:es)?|wing|seat|at)\b",
    re.IGNORECASE,
)

# A seat that still names a court is not a city — "PLACE:" takes the city alone.
_NOT_A_CITY = re.compile(
    r"\b(court|judicature|tribunal|commission|authority|forum)\b",
    re.IGNORECASE,
)

_HIGH_COURT_AT = re.compile(r"\bat\s+(.+)$", re.IGNORECASE)
_HIGH_COURT_OF = re.compile(
    r"high\s+court\s+(?:of|for)\s+(?:judicature\s+(?:of|for|at)\s+)?(.+)$",
    re.IGNORECASE,
)
_HIGH_COURT_PREFIXED = re.compile(r"^(.+?)\s+high\s+court\b", re.IGNORECASE)
_DISTRICT_COURT = re.compile(r"^(.+?)\s+district\s+court\b", re.IGNORECASE)


def _clean_seat(text: str) -> str:
    """Reduce a seat label to the bare city name.

    The seat values carry a second name in brackets — "Prayagraj (Allahabad)",
    "Kochi (Ernakulam)", "Chhatrapati Sambhajinagar (Aurangabad)" — and the twin
    -wing courts carry two cities separated by a slash. A pleading is signed at
    one city under its current name, so the bracket and everything after a slash
    are dropped rather than flattened into the line.
    """
    cleaned = re.sub(r"\(.*?\)", " ", text or "")     # drop "(Allahabad)"
    cleaned = cleaned.split("/")[0]                    # "Srinagar / Jammu" -> Srinagar
    cleaned = _SEAT_NOISE.sub(" ", cleaned)
    cleaned = re.sub(r"[(),]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip(" -–—,.")
    return "" if _NOT_A_CITY.search(cleaned) else cleaned


def filing_place(
    court_level: str = "",
    court_display: str = "",
    court_place: str = "",
) -> str:
    """The city that goes on the "PLACE:" line, or "" when it cannot be derived.

    `court_place` is the authoritative value: high_court_benches.city for the
    bench the advocate selected, sent by the frontend. Everything below it is a
    fallback for the callers that do not send one (district courts, tribunals,
    and any client still posting only a display string).

    Returning "" rather than a guess matters: the prompt keeps the fill-in blank
    for an unrecognised court, which is what the advocate had before. A wrong
    city printed on every page of a paper book is worse than an empty line.
    """
    seat = _clean_seat(court_place)
    if seat:
        return seat

    display = (court_display or "").strip()
    if not display:
        return ""

    level = (court_level or "").lower()
    if level == "supreme" or "supreme court" in display.lower():
        return _SUPREME_COURT_SEAT

    # The frontend joins the court and the selected bench with " - ", and the
    # bench label may itself contain one: "High Court of Judicature at Allahabad
    # - Prayagraj (Allahabad) - Principal Seat". Work backwards through the
    # parts — the last one that survives cleaning as a city is the seat, so
    # "Principal Seat" is skipped and "Prayagraj" is taken. The court name at
    # the front can never win: _clean_seat rejects anything naming a court.
    if " - " in display:
        for part in reversed(display.split(" - ")):
            seat = _clean_seat(part)
            if seat:
                return seat

    segments = [s.strip() for s in display.split(",") if s.strip()]

    # "Lucknow Bench, Central Administrative Tribunal" — the bench segment can
    # sit either side of the comma.
    for segment in segments:
        if re.search(r"\b(bench|seat)\b", segment, re.IGNORECASE):
            seat = _clean_seat(segment)
            if seat:
                return seat

    head = segments[0] if segments else display

    m = _DISTRICT_COURT.search(head)          # "Lucknow District Court, U.P."
    if m:
        return _clean_seat(m.group(1))

    if re.search(r"high\s+court", head, re.IGNORECASE):
        m = _HIGH_COURT_AT.search(head)       # "High Court of Judicature at Bombay"
        if m:
            return _clean_seat(m.group(1))
        m = _HIGH_COURT_OF.search(head)       # "High Court of Delhi"
        if m:
            return _clean_seat(m.group(1))
        m = _HIGH_COURT_PREFIXED.search(head)  # "Allahabad High Court"
        if m:
            return _clean_seat(m.group(1))

    return ""


@dataclass(frozen=True)
class CourtProfile:
    """How one court wants a pleading laid out."""

    key: str

    # "Opposite Parties" at Allahabad, "Respondents" almost everywhere else.
    respondent_label: str = "Respondents"
    respondent_label_singular: str = "Respondent"

    # Allahabad paper books open with a Code / Group / District block at the top
    # right of the index page.
    filing_header_fields: tuple = ()

    # The Allahabad CRLP paper book has no synopsis; a Supreme Court SLP must
    # have one.
    wants_synopsis: bool = True

    # Allahabad files the vakalatnama as a separate stamped form — it appears in
    # the index but is not drafted into the paper book.
    drafts_vakalatnama: bool = True

    # Affidavit tail. Allahabad requires the advocate Identification block and an
    # Oath Commissioner attestation after the Verification.
    wants_identification_block: bool = False
    wants_oath_commissioner: bool = False

    # Trailing lines of the advocate signature block, in order. Allahabad prints
    # Reg. No. / On Roll No. / Mobile No. rather than a single Enrollment No.
    signature_lines: tuple = (
        ("Enrollment No.", "advocate_enrollment_no"),
    )

    @property
    def uses_opposite_parties(self) -> bool:
        return self.respondent_label == "Opposite Parties"


_DEFAULT_PROFILE = CourtProfile(key="default")

_ALLAHABAD_PROFILE = CourtProfile(
    key="allahabad",
    respondent_label="Opposite Parties",
    respondent_label_singular="Opposite Party",
    filing_header_fields=("Code", "Group", "District"),
    wants_synopsis=False,
    drafts_vakalatnama=False,
    wants_identification_block=True,
    wants_oath_commissioner=True,
    signature_lines=(
        ("Reg. No.", "advocate_enrollment_no"),
        ("On Roll No.", "advocate_on_roll_no"),
        ("Mobile No.", "advocate_mobile_no"),
    ),
)

# Matched against a lowercased court_display. "lucknow" is included because the
# frontend renders the Lucknow bench as "Allahabad High Court - Lucknow", but
# advocates also select it as a bare bench name.
_ALLAHABAD_MARKERS = ("allahabad", "lucknow")


def court_profile(
    court_level: str = "",
    court_display: str = "",
    document_type_key: str = "",
) -> CourtProfile:
    """Pick the drafting conventions for this court.

    Unknown courts get the default profile, which reproduces the behaviour that
    existed before this module — so adding a profile is always opt-in and can
    never silently change a court we have no filing from.
    """
    display = (court_display or "").lower()

    # Matched on court_level == "high", not merely "not supreme". These are
    # Allahabad HIGH COURT conventions, and the city name alone is not enough:
    # court_display for a district court reads "Lucknow District Court, Uttar
    # Pradesh" and for a tribunal "Lucknow Bench, Central Administrative
    # Tribunal". Both contain "lucknow", and neither files an Allahabad High
    # Court paper book — a district pleading does not say "Opposite Parties",
    # carry a Code/Group/District header, or need an Oath Commissioner block.
    if (court_level or "").lower() == "high":
        if any(marker in display for marker in _ALLAHABAD_MARKERS):
            return _ALLAHABAD_PROFILE

    return _DEFAULT_PROFILE


def required_sections(
    profile: CourtProfile,
    document_type_key: str = "",
    has_interim_relief: bool = False,
) -> list[str]:
    """The ordered section list for this document.

    Two changes against the old hardcoded lists:

      * INTERIM_RELIEF_APPLICATION sits immediately after LIST_OF_DATES, matching
        the filed paper book, where it is a standalone C.M. Application listed in
        the index right after Dates & Events. It is emitted only when the
        advocate actually asked for interim relief.
      * SYNOPSIS and VAKALATNAMA are now conditional on the court profile rather
        than always present.
    """
    sections = [COVER_AND_INDEX]

    if (document_type_key or "") in _FRONT_MATTER_TYPES:
        if profile.wants_synopsis:
            sections.append(SYNOPSIS)
        sections.append(LIST_OF_DATES)

    if has_interim_relief:
        sections.append(INTERIM_RELIEF_APPLICATION)

    sections.append(body_section(document_type_key))
    sections.append(PRAYER)
    sections.append(AFFIDAVIT)

    if profile.drafts_vakalatnama:
        sections.append(VAKALATNAMA)

    sections.append(ANNEXURES)
    return sections


def has_interim_relief(form_data: dict) -> bool:
    """True when the advocate asked for interim relief.

    Guards against the placeholder text the template used to substitute, which
    would otherwise generate an empty C.M. Application.
    """
    value = (form_data or {}).get("interim_relief_sought")
    if not isinstance(value, str):
        return False
    cleaned = value.strip().lower()
    if len(cleaned) < 10:
        return False
    return cleaned not in {
        "not specifically requested",
        "not applicable",
        "n/a",
        "none",
        "nil",
    }
