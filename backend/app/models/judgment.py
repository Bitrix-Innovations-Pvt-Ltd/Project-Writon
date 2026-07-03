from sqlalchemy import Column, String, Integer, BigInteger, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, ARRAY, TSVECTOR
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector
from app.core.database import Base

class Judgment(Base):
    __tablename__ = "judgments"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    case_number = Column(String)
    case_type = Column(String)
    year = Column(Integer)
    judgment_date = Column(String)
    bench = Column(ARRAY(String))
    petitioner = Column(String)
    respondent = Column(String)
    acts_cited = Column(ARRAY(String))
    cases_cited = Column(ARRAY(String))
    full_text = Column(String)
    content_hash = Column(String, unique=True)
    pdf_s3_key = Column(String)
    summary = Column(String)
    holding = Column(String)
    
    # For full text BM25 keyword search
    search_vector = Column(TSVECTOR)
    
    # For Legal-BERT 768-dim dense semantic search
    embedding = Column(Vector(768))

class JudgmentChunk(Base):
    __tablename__ = "judgment_chunks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    judgment_id = Column(BigInteger, ForeignKey("judgments.id", ondelete="CASCADE"))
    chunk_index = Column(Integer)
    chunk_text = Column(String)
    # embedding column removed — vectors are now stored in Pinecone
    page_number = Column(Integer)

class SearchLog(Base):
    __tablename__ = "search_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    query = Column(String)
    search_type = Column(String)
    result_count = Column(Integer)
    clicked_judgment_id = Column(BigInteger, ForeignKey("judgments.id"))
    searched_at = Column(DateTime(timezone=True), server_default=func.now())
