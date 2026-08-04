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
