from sqlalchemy import Column, String, Integer, BigInteger, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base

class HierarchyCategory(Base):
    __tablename__ = "hierarchy_categories"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    court_level = Column(String, nullable=False)   # e.g., 'high'
    name = Column(String, nullable=False)          # e.g., 'PETITION'
    summary = Column(String, nullable=True)        # e.g., 'Writ & original'
    description = Column(String, nullable=True)    
    code = Column(String, nullable=True)           # e.g., '01'
    sort_order = Column(Integer, nullable=True)
    
    case_types = relationship("HierarchyCaseType", back_populates="category", cascade="all, delete-orphan")

class HierarchyCaseType(Base):
    __tablename__ = "hierarchy_case_types"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    category_id = Column(BigInteger, ForeignKey("hierarchy_categories.id"), nullable=False)
    name = Column(String, nullable=False)          # e.g., 'Criminal Misc. Writ Petition'
    code = Column(String, nullable=True)           # e.g., 'CRLP'
    defective = Column(Boolean, default=False)
    sort_order = Column(Integer, nullable=True)
    
    category = relationship("HierarchyCategory", back_populates="case_types")
    sub_categories = relationship("HierarchySubCategory", back_populates="case_type", cascade="all, delete-orphan")
    documents = relationship("HierarchyDocumentRequirement", back_populates="case_type", cascade="all, delete-orphan")

class HierarchySubCategory(Base):
    __tablename__ = "hierarchy_sub_categories"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    case_type_id = Column(BigInteger, ForeignKey("hierarchy_case_types.id"), nullable=False)
    name = Column(String, nullable=False)          # e.g., 'Direction to register FIR / no action on FIR'
    sort_order = Column(Integer, nullable=True)
    
    case_type = relationship("HierarchyCaseType", back_populates="sub_categories")

class HierarchyDocumentRequirement(Base):
    __tablename__ = "hierarchy_document_requirements"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    case_type_id = Column(BigInteger, ForeignKey("hierarchy_case_types.id"), nullable=False)
    document_name = Column(String, nullable=False) # e.g., 'Copy of the FIR / complaint'
    requirement_type = Column(String, nullable=False) # 'required' or 'optional'
    sort_order = Column(Integer, nullable=True)
    
    case_type = relationship("HierarchyCaseType", back_populates="documents")
