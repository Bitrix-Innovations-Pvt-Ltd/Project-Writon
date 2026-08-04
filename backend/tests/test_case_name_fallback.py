"""
Regression tests for the judgment case-name OR-fallback query.

The bug these guard: the fallback matched party names against `search_vector`,
which spans summary + holding + full_text. A name therefore matched whenever a
judgment merely *mentioned* someone of that name. Measured on the live corpus
(39,506 judgments):

    search_vector @@ 'Kumar | Verma'   20,698 rows (52.4%)  5.43s
    petitioner/respondent ILIKE         3,015 rows ( 7.6%)  0.13s warm

5.43s is over OR_FALLBACK_TIMEOUT_MS (4s), so for common Indian surnames — Kumar
49% of the corpus, Singh 59%, Sharma 30% — the fallback ALWAYS died with
QueryCanceledError. That is most Indian cause titles.

This is the second time this shape of bug has bitten (the first ORed every word
and matched 98.7% of the corpus). The stopword list is not a defence: it can
catch legal vocabulary but never every common surname.
"""

import re

import pytest

from app.core.rag import (
    _case_name_terms,
    _looks_like_case_name,
    build_case_name_fallback_sql,
)


# ── The invariant that broke ─────────────────────────────────────────────────

def test_party_names_are_matched_against_the_party_columns():
    sql, params = build_case_name_fallback_sql(["Kumar", "Verma"])
    where = sql[sql.index("WHERE"):sql.index("ORDER")]
    assert "petitioner ILIKE" in where and "respondent ILIKE" in where


def test_search_vector_is_never_used_to_filter():
    """The whole bug in one assertion: search_vector may ORDER the survivors but
    must never decide which rows survive."""
    sql, _ = build_case_name_fallback_sql(["Kumar", "Verma"])
    where = sql[sql.index("WHERE"):sql.index("ORDER")]
    assert "search_vector" not in where
    assert "@@" not in where


def test_ts_rank_still_orders_the_results():
    """Relevance ranking is unchanged — it just runs over far fewer rows.

    Matched on intent rather than exact spacing: the query is now a two-stage
    CTE, so rank_score carries the `h.` alias in the outer ORDER BY.
    """
    sql, params = build_case_name_fallback_sql(["Kumar", "Verma"])
    assert "ts_rank(j.search_vector" in sql
    assert re.search(r"ORDER\s+BY\s+(?:\w+\.)?rank_score\s+DESC", sql)
    assert params["or_q"] == "Kumar | Verma"


def test_heavy_text_is_not_built_during_ranking():
    """full_text is detoasted per row, so it must be read only for the rows that
    survive the LIMIT. Building it in the ranking pass cost ~1.1s on a 3,606-row
    match and pushed the query past the statement-timeout cap."""
    sql, _ = build_case_name_fallback_sql(["Kumar", "Verma"])
    ranking_pass = sql[:sql.index(")", sql.index("WITH"))]
    assert "full_text" not in ranking_pass, (
        "full_text must not be read in the ranking CTE — only for the 20 winners"
    )
    assert "full_text" in sql          # still selected, just later


# ── Parameterisation ─────────────────────────────────────────────────────────

def test_every_name_gets_its_own_bound_parameter():
    words = ["Gurbaksh", "Sibbia", "Punjab"]
    sql, params = build_case_name_fallback_sql(words)
    for i, w in enumerate(words):
        assert params[f"nm{i}"] == f"%{w}%"
        assert f":nm{i}" in sql


def test_names_are_never_interpolated_into_the_sql():
    """SQL injection guard: a party name is user-influenced text."""
    sql, params = build_case_name_fallback_sql(["O'Brien", "Smith'; DROP TABLE judgments;--"])
    assert "DROP TABLE" not in sql
    assert "O'Brien" not in sql
    assert params["nm1"] == "%Smith'; DROP TABLE judgments;--%"


def test_bound_parameter_count_matches_the_placeholders():
    for n in (2, 3, 6):
        words = [f"Name{i}" for i in range(n)]
        sql, params = build_case_name_fallback_sql(words)
        assert len(re.findall(r":nm\d+", sql)) == 2 * n     # petitioner + respondent
        assert sum(k.startswith("nm") for k in params) == n


def test_case_type_filter_is_spliced_in():
    sql, _ = build_case_name_fallback_sql(["A", "B"], ct_filter_sql="AND j.case_type = :ct")
    assert "AND j.case_type = :ct" in sql
    assert sql.index("case_type = :ct") < sql.index("ORDER")


def test_ts_config_is_honoured():
    sql, _ = build_case_name_fallback_sql(["A", "B"], ts_config="simple")
    assert "to_tsquery('simple'" in sql


def test_result_set_stays_bounded():
    sql, _ = build_case_name_fallback_sql(["Kumar", "Verma"])
    assert re.search(r"LIMIT\s+20", sql)


# ── Token selection (unchanged behaviour, pinned) ────────────────────────────

@pytest.mark.parametrize("query,expected", [
    ("Gurbaksh Singh Sibbia v. State of Punjab", True),
    ("Nandini Satpathy vs P.L. Dani", True),
    ("bail granted for economic offences", False),
])
def test_case_name_detection(query, expected):
    assert _looks_like_case_name(query) is expected


def test_stopwords_still_filter_generic_vocabulary():
    terms = _case_name_terms("Bhajan Lal v. State of Haryana", {"state", "haryana"})
    assert "State" not in terms and "Haryana" not in terms
    assert "Bhajan" in terms


def test_short_tokens_are_dropped():
    assert "Lal" not in _case_name_terms("Bhajan Lal v. State", set())


def test_terms_are_deduplicated():
    terms = _case_name_terms("Kumar v. Kumar Enterprises", set())
    assert terms.count("Kumar") == 1


def test_fallback_needs_at_least_two_terms_to_be_worth_running():
    """Mirrors the `len(words) > 1` guard at the call site: a single common
    surname widens the search without identifying anything."""
    assert len(_case_name_terms("Kumar v. State", {"state"})) == 1
