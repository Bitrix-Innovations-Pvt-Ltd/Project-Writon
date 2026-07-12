"""
api/v1/court_rules.py — Read-only endpoints for court identity, formatting
rules, and document structure rules.

Used by:
  - Frontend Step 1 "Which High Court?" dropdown (GET /court-identities)
  - Export engine formatting decisions (GET /court-identities/{short_code}/formatting)
  - Debug / lawyer review (GET /court-identities/{short_code}/structure-rules)
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.court_rules import (
    CourtIdentity,
    CourtBench,
    CourtFormattingRule,
    DocumentStructureRule,
    MandatoryParagraph,
    CourtRuleSection,
    CourtRuleDocumentMapping,
)

router = APIRouter(prefix="/court-identities", tags=["Court Rules"])


# ---------------------------------------------------------------------------
# GET /court-identities
# Returns all court identities for the frontend Step 1b dropdown.
# ---------------------------------------------------------------------------
@router.get("")
async def list_court_identities(db: AsyncSession = Depends(get_db)):
    """
    List all courts that have a sourced rulebook in the system.
    Frontend uses this to populate the "Which High Court?" dropdown.
    Returns: id, court_name, short_code, state, court_level, has_benches.
    """
    result = await db.execute(
        select(CourtIdentity)
        .options(selectinload(CourtIdentity.benches))
        .order_by(CourtIdentity.court_name)
    )
    identities = result.scalars().all()
    return [
        {
            "id":            ci.id,
            "court_name":    ci.court_name,
            "short_code":    ci.short_code,
            "state":         ci.state,
            "court_level":   ci.court_level,
            "has_benches":   ci.has_benches,
            "rule_book_title": ci.rule_book_title,
            "benches":       [{"id": b.id, "bench_name": b.bench_name} for b in ci.benches],
        }
        for ci in identities
    ]


# ---------------------------------------------------------------------------
# GET /court-identities/{short_code}/formatting
# Returns sourced formatting rules for the given court.
# Export engine uses this to determine font/margin/paper values.
# ---------------------------------------------------------------------------
@router.get("/{short_code}/formatting")
async def get_court_formatting(short_code: str, db: AsyncSession = Depends(get_db)):
    """
    Returns formatting rules for a specific court.
    is_sourced_from_rulebook=false means the value is a generic assumption.
    The source_note field contains the e-filing gap disclaimer where applicable.
    """
    result = await db.execute(
        select(CourtIdentity).where(CourtIdentity.short_code == short_code.upper())
    )
    identity = result.scalar_one_or_none()
    if not identity:
        raise HTTPException(status_code=404, detail=f"Court identity '{short_code}' not found")

    fmt_result = await db.execute(
        select(CourtFormattingRule).where(CourtFormattingRule.court_identity_id == identity.id)
    )
    fmt_rules = fmt_result.scalars().all()
    return {
        "court_name":  identity.court_name,
        "short_code":  identity.short_code,
        "formatting":  [
            {
                "font_family":              r.font_family,
                "body_font_size":           r.body_font_size,
                "line_spacing":             r.line_spacing,
                "margin_style":             r.margin_style,
                "paper_finish":             r.paper_finish,
                "court_language":           r.court_language,
                "requires_para_numbering":  r.requires_para_numbering,
                "paper_size":               r.paper_size,
                "is_sourced_from_rulebook": r.is_sourced_from_rulebook,
                "source_note":              r.source_note,
            }
            for r in fmt_rules
        ],
    }


# ---------------------------------------------------------------------------
# GET /court-identities/{short_code}/structure-rules
# Returns document structure rules (source_type labeled for lawyer review).
# ---------------------------------------------------------------------------
@router.get("/{short_code}/structure-rules")
async def get_structure_rules(
    short_code: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns document structure rules filtered by short_code (applies_to in DB).
    Useful for lawyer review: shows which rules are rule_mandated vs convention vs unconfirmed.
    """
    # If "ALL" is passed as short_code, we can fallback or just query it
    result = await db.execute(
        select(DocumentStructureRule)
        .where(DocumentStructureRule.applies_to == short_code)
        .order_by(DocumentStructureRule.rule_key)
    )
    rules = result.scalars().all()
    return [
        {
            "rule_key":         r.rule_key,
            "rule_description": r.rule_description,
            "is_heading":       r.is_heading,
            "source_type":      r.source_type,
            "applies_to":       r.applies_to,
        }
        for r in rules
    ]


# ---------------------------------------------------------------------------
# GET /court-identities/{short_code}/mandatory-paragraphs
# Returns mandatory paragraphs for a given court level + document type.
# ---------------------------------------------------------------------------
@router.get("/{short_code}/mandatory-paragraphs")
async def get_mandatory_paragraphs(
    short_code: str,
    court_level: str,
    document_type_key: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns mandatory paragraphs for the given court level and document type key.
    Ordered by sort_order. source_type + source_citation shown for lawyer review.
    """
    result = await db.execute(
        select(MandatoryParagraph)
        .where(
            MandatoryParagraph.court_level == court_level,
            MandatoryParagraph.document_type_key == document_type_key,
        )
        .order_by(MandatoryParagraph.sort_order)
    )
    paras = result.scalars().all()
    return [
        {
            "para_key":        p.para_key,
            "para_label":      p.para_label,
            "instruction":     p.instruction,
            "placement":       p.placement,
            "is_conditional":  p.is_conditional,
            "condition_note":  p.condition_note,
            "sort_order":      p.sort_order,
            "source_type":     p.source_type,
            "source_citation": p.source_citation,
        }
        for p in paras
    ]


# ---------------------------------------------------------------------------
# GET /court-identities/{short_code}/rule-sections
# Returns raw rule sections for a court + optional chapter filter.
# For internal tooling / lawyer review only.
# ---------------------------------------------------------------------------
@router.get("/{short_code}/rule-sections")
async def get_rule_sections(
    short_code: str,
    chapter_number: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CourtIdentity).where(CourtIdentity.short_code == short_code.upper())
    )
    identity = result.scalar_one_or_none()
    if not identity:
        raise HTTPException(status_code=404, detail=f"Court identity '{short_code}' not found")

    query = select(CourtRuleSection).where(CourtRuleSection.court_identity_id == identity.id)
    if chapter_number:
        query = query.where(CourtRuleSection.chapter_number == chapter_number)
    query = query.order_by(CourtRuleSection.chapter_number, CourtRuleSection.rule_number)

    result = await db.execute(query)
    sections = result.scalars().all()
    return [
        {
            "chapter_number":  s.chapter_number,
            "chapter_title":   s.chapter_title,
            "rule_number":     s.rule_number,
            "rule_subsection": s.rule_subsection,
            "rule_text":       s.rule_text,
            "source_page":     s.source_page,
        }
        for s in sections
    ]
