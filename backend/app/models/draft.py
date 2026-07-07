from sqlalchemy import Column, String, Integer, BigInteger, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
from app.core.database import Base

class Draft(Base):
    __tablename__ = "drafts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    title = Column(String)
    case_type = Column(String)
    court = Column(String)
    form_data = Column(JSON)
    
    # Parties and Facts (Step 5 extensions)
    advocate_name = Column(String)
    advocate_enrollment_no = Column(String)
    petitioners = Column(JSON)
    respondents = Column(JSON)
    impugned_order_date = Column(DateTime)
    jurisdiction_basis = Column(String)
    interim_relief_sought = Column(String)
    
    draft_html = Column(String)
    draft_text = Column(String)
    citation_ids = Column(ARRAY(BigInteger))
    status = Column(String, default="draft")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class UploadedDoc(Base):
    __tablename__ = "uploaded_docs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    draft_id = Column(BigInteger, ForeignKey("drafts.id", ondelete="CASCADE"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    original_filename = Column(String)
    r2_key = Column(String)
    doc_type = Column(String)
    ocr_text = Column(String)
    verify_status = Column(String)
    verify_reason = Column(String)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
