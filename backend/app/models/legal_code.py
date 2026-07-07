from sqlalchemy import Column, String, Integer, BigInteger, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from pgvector.sqlalchemy import Vector
from app.core.database import Base

class LegalCode(Base):
    __tablename__ = "legal_codes"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code_name = Column(String, nullable=False)
    short_code = Column(String, nullable=False)
    year_enacted = Column(Integer)
    status = Column(String, default="active")
    replaced_by_id = Column(BigInteger, ForeignKey("legal_codes.id"))

class LegalCodeSection(Base):
    __tablename__ = "legal_code_sections"
    
    __table_args__ = (
        UniqueConstraint('legal_code_id', 'section_number'),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    legal_code_id = Column(BigInteger, ForeignKey("legal_codes.id", ondelete="CASCADE"))
    section_number = Column(String, nullable=False)
    title = Column(String)
    section_text = Column(String, nullable=False)
    embedding = Column(Vector(1536))
    corresponds_to = Column(String)
    # BM25 keyword search (title weighted A, section_text weighted B)
    search_vector = Column(TSVECTOR)
