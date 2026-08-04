"""
Statute domain narrowing for civil matters.

The problem this fixes: 'civil' is tagged on 48 of 58 legal_codes, so a civil
writ's domain filter (['civil','constitutional']) admitted 49 codes — no real
filter. A U.P. land-revenue writ was ranked against Income Tax, IBC and the
Contract Act on embedding similarity alone. 'criminal' admits 16, which is why
criminal matters always retrieved well.

The subject-matter NAME is read to pick the governing domain. Nothing in the
subject_matters / document_types tables is modified — these tests use the real
names from that taxonomy verbatim.
"""

import pytest

from app.core.rag import _derive_statute_domains, _subject_statute_domain


CONFIG = {
    "doc_type_domains": {
        "writ_petition_civil": ["civil", "constitutional"],
        "writ_petition_criminal": ["criminal", "constitutional"],
        "civil_appeal": ["civil", "constitutional"],
        "bail_application": ["criminal"],
        "anticipatory_bail": ["criminal"],
    },
    "subject_needs_coi": [],
    "service_law_keywords": [],
}


def derive(doc_type_key, subject):
    return _derive_statute_domains(CONFIG, doc_type_key, subject)


# ── real subject-matter names, copied verbatim from the taxonomy ─────────────

@pytest.mark.parametrize("subject,expected", [
    ("Writ – B · Revenue, land & consolidation — U.P. Zamindari Abolition & Land Revenue Act", "property"),
    ("Writ – B · Revenue, land & consolidation — Bhumidhari / sirdari rights", "property"),
    ("Writ – B · Revenue, land & consolidation — Consolidation of Holdings Act (chak, mutation)", "property"),
    ("Writ – B · Revenue, land & consolidation — Gaon Sabha / gram panchayat land", "property"),
    ("Writ – C · Miscellaneous civil — Land acquisition (compensation, possession)", "property"),
    ("Writ – C · Miscellaneous civil — Rent control & eviction (U.P. Act 1972)", "property"),
    ("Property / Land Dispute", "property"),
    ("Writ – A · Service matters — Promotion", "service"),
    ("Writ – A · Service matters — Retiral benefits (pension, gratuity, GPF)", "service"),
    ("Service Law", "service"),
    ("Writ Tax — Income Tax (reassessment, recovery)", "tax"),
    ("Writ Tax — GST (registration, assessment, seizure, refunds)", "tax"),
    ("Income Tax / GST", "tax"),
    ("Matrimonial / Family", "family"),
    ("Company / Insolvency", "corporate"),
    ("Debt Recovery / SARFAESI", "corporate"),
    ("Motor Accident", "transport"),
    ("Consumer Complaint", "consumer"),
    ("Industrial Dispute", "labour"),
])
def test_subject_maps_to_governing_domain(subject, expected):
    assert _subject_statute_domain(subject.lower()) == expected


def test_stamp_duty_writ_is_tax_not_property():
    """'Writ Tax — Stamp duty & registration fee' mentions registration, but it
    is a tax matter — tax patterns are checked first for exactly this reason."""
    assert _subject_statute_domain(
        "writ tax — stamp duty & registration fee") == "tax"


# ── narrowing behaviour ──────────────────────────────────────────────────────

def test_civil_is_replaced_by_the_specific_domain():
    out = derive("writ_petition_civil",
                 "Writ – B · Revenue, land & consolidation — U.P. Zamindari Abolition & Land Revenue Act")
    assert "civil" not in out          # the catch-all is gone
    assert "property" in out


def test_narrowing_keeps_constitutional_and_procedure():
    """A writ is founded on the COI, and CPC/Limitation stay reachable."""
    out = derive("writ_petition_civil", "Property / Land Dispute")
    assert "constitutional" in out and "procedure" in out


def test_unclear_subject_is_left_broad():
    """Residuary matters must not be narrowed on a guess — better to search
    everything than to exclude the governing Act."""
    out = derive("writ_petition_civil",
                 "Writ – C · Miscellaneous civil — Residuary writ petitions")
    assert out == ["civil", "constitutional"]


def test_empty_subject_is_left_broad():
    assert derive("writ_petition_civil", "") == ["civil", "constitutional"]


@pytest.mark.parametrize("doc_type_key", ["bail_application", "anticipatory_bail",
                                          "writ_petition_criminal"])
def test_criminal_document_types_are_untouched(doc_type_key):
    """Criminal already filters well (16/58). Narrowing only fires when 'civil'
    is present, so these must be byte-identical to before."""
    before = list(CONFIG["doc_type_domains"][doc_type_key])
    after = derive(doc_type_key, "Bail / Anticipatory Bail")
    assert after == before


def test_criminal_subject_on_a_criminal_doc_type_stays_criminal():
    out = derive("writ_petition_criminal",
                 "Criminal Misc. Writ Petition — Quashing of FIR under Article 226")
    assert "criminal" in out and "property" not in out


def test_civil_appeal_also_benefits():
    out = derive("civil_appeal", "First Appeal — Land acquisition reference appeals")
    assert "property" in out and "civil" not in out
