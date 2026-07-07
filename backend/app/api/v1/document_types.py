from typing import Optional, List, Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.document_type import DocumentType

router = APIRouter(prefix="/document-types", tags=["document-types"])

@router.get("/")
async def get_document_types(
    court_level: Annotated[str, Query(description="Level of the court, e.g., supreme, high, district, tribunal, special_court")],
    tribunal_name: Annotated[Optional[str], Query(description="Name of the specific tribunal or special court if court_level is tribunal or special_court")] = None,
    db: AsyncSession = Depends(get_db)
):
    # First attempt: search with specific tribunal_name if provided
    stmt = select(DocumentType).where(DocumentType.court_level == court_level)
    if tribunal_name:
        stmt = stmt.where(DocumentType.tribunal_name == tribunal_name)
    elif court_level in ['tribunal', 'special_court']:
        stmt = stmt.where(DocumentType.tribunal_name.is_(None))
        
    stmt = stmt.order_by(DocumentType.sort_order.asc(), DocumentType.id.asc())
    result = await db.execute(stmt)
    doc_types = result.scalars().all()
    
    # Fallback to generic/default list if tribunal_name was provided but no specific document types exist
    if not doc_types and tribunal_name and court_level in ['tribunal', 'special_court']:
        stmt = select(DocumentType).where(
            DocumentType.court_level == court_level,
            DocumentType.tribunal_name.is_(None)
        ).order_by(DocumentType.sort_order.asc(), DocumentType.id.asc())
        result = await db.execute(stmt)
        doc_types = result.scalars().all()
        
    return [
        {
            "id": dt.id,
            "court_level": dt.court_level,
            "tribunal_name": dt.tribunal_name,
            "doc_type_name": dt.doc_type_name,
            "statutory_basis": dt.statutory_basis,
            "category": dt.category,
            "sort_order": dt.sort_order
        }
        for dt in doc_types
    ]
