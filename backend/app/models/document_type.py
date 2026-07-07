from sqlalchemy import Column, String, Integer, BigInteger
from app.core.database import Base

class DocumentType(Base):
    __tablename__ = "document_types"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    court_level = Column(String, nullable=False)   # 'supreme' | 'high' | 'district' | 'tribunal' | 'special_court'
    tribunal_name = Column(String, nullable=True)   # Name of the specific tribunal or special court
    doc_type_name = Column(String, nullable=False)  # e.g., 'Writ Petition (Art. 32)'
    statutory_basis = Column(String, nullable=True) # e.g., 'Art. 32'
    category = Column(String, nullable=True)        # e.g., 'Constitutional', 'Criminal', etc.
    sort_order = Column(Integer, nullable=True)
