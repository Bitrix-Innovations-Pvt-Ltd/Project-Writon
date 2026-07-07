from sqlalchemy import Column, String, BigInteger, Boolean, DateTime
from sqlalchemy.sql import func
from app.core.database import Base

class SubjectMatterAnalytics(Base):
    __tablename__ = "subject_matter_analytics"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    court_level = Column(String, nullable=True)
    selected_other = Column(Boolean, default=True)
    case_description_snippet = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
