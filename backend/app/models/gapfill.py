from sqlalchemy import Column, String, Integer, BigInteger, Boolean, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from app.core.database import Base

class ContextGapAnalytics(Base):
    __tablename__ = "context_gap_analytics"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    document_type_key = Column(String, nullable=False, index=True)
    suggested_question = Column(String, nullable=False)
    why_relevant = Column(String, nullable=True)
    was_answered = Column(Boolean, nullable=True)
    was_skipped = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class DocumentFieldRequirements(Base):
    __tablename__ = "document_field_requirements"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    document_type_key = Column(String, nullable=False)
    field_key = Column(String, nullable=False)
    field_label = Column(String, nullable=False)
    priority = Column(String, nullable=False)
    min_length = Column(Integer, default=1)
    reason = Column(String, nullable=True)
    sort_order = Column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint('document_type_key', 'field_key', name='uq_doc_field_req'),
    )
