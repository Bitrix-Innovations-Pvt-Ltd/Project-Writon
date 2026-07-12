"""
models/court_rules.py — ORM models for court-specific identity, vectorized
rulebook corpus, RAG mapping, formatting rules, and structure/paragraph rules.

Pattern mirrors legal_code.py (Vector + TSVECTOR) and hierarchy.py (BigInteger PKs).
Tables are created via ahc_rulebook_seed.sql — these models reflect that schema.
"""

from sqlalchemy import (
    Column, String, Integer, BigInteger, Boolean, Text,
    ForeignKey, UniqueConstraint, Numeric
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.core.database import Base


# ---------------------------------------------------------------------------
# 1. Court Identity — specific court (e.g. "Allahabad High Court")
#    Separate from the generic court_level used in wizard Step 1.
#    One row per court that has a sourced rulebook.
# ---------------------------------------------------------------------------
class CourtIdentity(Base):
    __tablename__ = "court_identities"

    id                   = Column(BigInteger, primary_key=True, autoincrement=True)
    court_level          = Column(String, nullable=False)       # generic: 'high_court'
    court_name           = Column(String, nullable=False, unique=True)  # 'Allahabad High Court'
    short_code           = Column(String, nullable=False, unique=True)  # 'AHC'
    state                = Column(String)                       # 'Uttar Pradesh'
    has_benches          = Column(Boolean, default=False)
    rule_book_title      = Column(String)                       # 'Rules of the Court, 1952'
    rule_book_source_url = Column(String)

    # Relationships
    benches        = relationship("CourtBench",               back_populates="court_identity", cascade="all, delete-orphan")
    rule_sections  = relationship("CourtRuleSection",         back_populates="court_identity", cascade="all, delete-orphan")
    rule_mappings  = relationship("CourtRuleDocumentMapping", back_populates="court_identity", cascade="all, delete-orphan")
    formatting_rules = relationship("CourtFormattingRule",    back_populates="court_identity", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# 2. Court Bench — e.g. "Lucknow Bench", "Allahabad (Principal Seat)"
# ---------------------------------------------------------------------------
class CourtBench(Base):
    __tablename__ = "court_benches"
    __table_args__ = (
        UniqueConstraint("court_identity_id", "bench_name"),
    )

    id                = Column(BigInteger, primary_key=True, autoincrement=True)
    court_identity_id = Column(BigInteger, ForeignKey("court_identities.id", ondelete="CASCADE"), nullable=False)
    bench_name        = Column(String, nullable=False)   # 'Lucknow Bench'

    court_identity = relationship("CourtIdentity", back_populates="benches")


# ---------------------------------------------------------------------------
# 3. Court Rule Section — vectorized rulebook corpus
#    Internal RAG only. Same pattern as LegalCodeSection.
#    embedding populated by a background job using Legal-BERT.
#    search_vector populated by DB trigger (court_rule_sections_search_update).
# ---------------------------------------------------------------------------
class CourtRuleSection(Base):
    __tablename__ = "court_rule_sections"
    __table_args__ = (
        UniqueConstraint("court_identity_id", "chapter_number", "rule_number", "rule_subsection"),
    )

    id                = Column(BigInteger, primary_key=True, autoincrement=True)
    court_identity_id = Column(BigInteger, ForeignKey("court_identities.id", ondelete="CASCADE"), nullable=False)
    part_name         = Column(String)            # 'PART IV-ENFORCEMENT OF FUNDAMENTAL RIGHTS'
    chapter_number    = Column(String, nullable=False)  # 'XXII', 'IX', 'I'
    chapter_title     = Column(String)            # 'DIRECTION, ORDER OR WRIT UNDER ARTICLE 226...'
    rule_number       = Column(String)            # '1', '7', '18'
    rule_subsection   = Column(String)            # '(3)(i)-(iv)' — for pinpoint citation
    rule_text         = Column(Text, nullable=False)
    embedding         = Column(Vector(768))       # Legal-BERT 768-dim; populated by embedding job
    search_vector     = Column(TSVECTOR)          # BM25 via DB trigger
    source_page       = Column(Integer)           # PDF page number

    court_identity = relationship("CourtIdentity", back_populates="rule_sections")


# ---------------------------------------------------------------------------
# 4. Court Rule Document Mapping — THE RAG RULE
#    Maps document_type_key -> which chapters to retrieve from
#    court_rule_sections at draft-generation time.
# ---------------------------------------------------------------------------
class CourtRuleDocumentMapping(Base):
    __tablename__ = "court_rule_document_mapping"
    __table_args__ = (
        UniqueConstraint("court_identity_id", "document_type_key", "chapter_number"),
    )

    id                  = Column(BigInteger, primary_key=True, autoincrement=True)
    court_identity_id   = Column(BigInteger, ForeignKey("court_identities.id", ondelete="CASCADE"), nullable=False)
    document_type_key   = Column(String, nullable=False)   # matches prompt template key
    chapter_number      = Column(String, nullable=False)   # chapter of court_rule_sections to pull
    relevance_note      = Column(Text)                     # why this chapter applies
    is_mandatory_source = Column(Boolean, default=True)    # True = always fetch; False = fetch only if contextually relevant

    court_identity = relationship("CourtIdentity", back_populates="rule_mappings")


# ---------------------------------------------------------------------------
# 5. Court Formatting Rule — sourced formatting values per court identity
#    Paper-era rules from 1952 for AHC. E-filing specs not yet sourced.
#    is_sourced_from_rulebook distinguishes sourced from assumed values.
# ---------------------------------------------------------------------------
class CourtFormattingRule(Base):
    __tablename__ = "court_formatting_rules"

    id                       = Column(BigInteger, primary_key=True, autoincrement=True)
    court_identity_id        = Column(BigInteger, ForeignKey("court_identities.id"), nullable=True)
    court_level              = Column(String)       # fallback: generic level if no court_identity_id
    font_family              = Column(String)       # NULL = not specified in rulebook
    body_font_size           = Column(String)       # NULL = not specified
    line_spacing             = Column(String)       # NULL = not specified for petitions
    margin_left_inches       = Column(Numeric)
    margin_right_inches      = Column(Numeric)
    margin_top_inches        = Column(Numeric)
    margin_bottom_inches     = Column(Numeric)
    margin_style             = Column(String)       # 'quarter_margin' (paper era) vs inch-based
    paper_finish             = Column(String)       # 'water_marked_or_foolscap'
    court_language           = Column(String)
    requires_para_numbering  = Column(Boolean, default=False)
    paper_size               = Column(String)
    is_sourced_from_rulebook = Column(Boolean, default=False)
    source_note              = Column(Text)         # e-filing gap flag, caveats, etc.

    court_identity = relationship("CourtIdentity", back_populates="formatting_rules")


# ---------------------------------------------------------------------------
# 6. Document Structure Rule — universal + court-specific structure rules
#    source_type: 'rule_mandated' | 'convention' | 'unconfirmed'
# ---------------------------------------------------------------------------
class DocumentStructureRule(Base):
    __tablename__ = "document_structure_rules"
    __table_args__ = (
        UniqueConstraint("applies_to", "rule_key"),
    )

    id               = Column(BigInteger, primary_key=True, autoincrement=True)
    applies_to       = Column(String, nullable=False, default="ALL")  # 'ALL' | 'high_court' | specific doc type key
    rule_key         = Column(String, nullable=False)
    rule_description = Column(Text, nullable=False)
    is_heading       = Column(Boolean)     # None = not a heading concept; True = labeled section heading; False = unlabeled paragraph
    source_type      = Column(String, nullable=False, default="convention")
    # 'rule_mandated'  = directly sourced from a specific chapter/rule citation
    # 'convention'     = standard Bar practice, not independently rule-cited
    # 'unconfirmed'    = genuinely ambiguous, flagged for lawyer sign-off


# ---------------------------------------------------------------------------
# 7. Mandatory Paragraph — per-doc-type mandatory paragraphs
#    source_type + source_citation set inline in seed (no UPDATE pass).
# ---------------------------------------------------------------------------
class MandatoryParagraph(Base):
    __tablename__ = "mandatory_paragraphs"
    __table_args__ = (
        UniqueConstraint("court_level", "bench_name", "document_type_key", "para_key"),
    )

    id                = Column(BigInteger, primary_key=True, autoincrement=True)
    court_level       = Column(String, nullable=False)    # 'high_court' | 'district'
    bench_name        = Column(String)                    # NULL = applies to all benches
    document_type_key = Column(String, nullable=False)    # 'writ_petition_civil' | 'bail_application' etc.
    para_key          = Column(String, nullable=False)    # unique key within doc type
    para_label        = Column(String, nullable=False)    # human-readable label shown in UI
    instruction       = Column(Text, nullable=False)      # full instruction for the LLM / drafter
    placement         = Column(String)                    # 'opening_paragraph' | 'after_grounds' | 'before_prayer'
    is_heading        = Column(Boolean, default=False)
    is_conditional    = Column(Boolean, default=False)
    condition_note    = Column(Text)                      # when to include (for conditional paragraphs)
    sort_order        = Column(Integer, default=0)
    source_type       = Column(String, nullable=False, default="convention")
    source_citation   = Column(String)                    # e.g. 'AHC Rules 1952, Ch. XXII R.1(3)(i)'
