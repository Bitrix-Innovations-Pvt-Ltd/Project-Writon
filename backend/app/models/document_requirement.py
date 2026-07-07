from sqlalchemy import Column, String, Integer, BigInteger
from app.core.database import Base

class DocumentRequirement(Base):
    __tablename__ = "document_requirements"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    court_level = Column(String, nullable=False)
    subject_matter = Column(String, nullable=False)
    document_name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    requirement_type = Column(String, nullable=False) # 'required' or 'optional'
    sort_order = Column(Integer, nullable=True)
