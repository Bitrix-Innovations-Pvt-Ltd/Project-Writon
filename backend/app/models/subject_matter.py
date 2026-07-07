from sqlalchemy import Column, String, Integer, BigInteger
from sqlalchemy.dialects.postgresql import ARRAY
from app.core.database import Base

class SubjectMatter(Base):
    __tablename__ = "subject_matters"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    court_level = Column(String, nullable=False)   # 'supreme', 'high', 'district', 'tribunal', 'special_court'
    tribunal_name = Column(String, nullable=True)   # Name of specific tribunal/special court if applicable
    matter_name = Column(String, nullable=False)    # e.g., 'Property / Land Dispute'
    applicable_doc_types = Column(ARRAY(String), nullable=True) # e.g., ['Civil Suit', 'Civil Appeal']
    sort_order = Column(Integer, nullable=True)
