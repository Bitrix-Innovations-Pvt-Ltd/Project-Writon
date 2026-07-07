from typing import Optional, List, Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.subject_matter import SubjectMatter

router = APIRouter(prefix="/subject-matters", tags=["subject-matters"])

@router.get("/")
async def get_subject_matters(
    court_level: Annotated[str, Query(description="Level of the court, e.g., supreme, high, district, tribunal, special_court")],
    tribunal_name: Annotated[Optional[str], Query(description="Name of the specific tribunal or special court if court_level is tribunal or special_court")] = None,
    document_type: Annotated[Optional[str], Query(description="Selected document type to cross-validate against")] = None,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(SubjectMatter).where(SubjectMatter.court_level == court_level)
    
    if tribunal_name:
        stmt = stmt.where(SubjectMatter.tribunal_name == tribunal_name)
    elif court_level in ['tribunal', 'special_court']:
        stmt = stmt.where(SubjectMatter.tribunal_name.is_(None))
        
    stmt = stmt.order_by(SubjectMatter.sort_order.asc(), SubjectMatter.id.asc())
    result = await db.execute(stmt)
    subject_matters = result.scalars().all()
    
    # Fallback to generic/default list if tribunal_name was provided but no specific subject matters exist
    if not subject_matters and tribunal_name and court_level in ['tribunal', 'special_court']:
        stmt = select(SubjectMatter).where(
            SubjectMatter.court_level == court_level,
            SubjectMatter.tribunal_name.is_(None)
        ).order_by(SubjectMatter.sort_order.asc(), SubjectMatter.id.asc())
        result = await db.execute(stmt)
        subject_matters = result.scalars().all()

    # Optional filtering by document_type (if frontend provides it)
    # Alternatively, we just return the full applicable_doc_types to the frontend and let it handle cross-validation graying-out.
    # We will return the data as is.
        
    return [
        {
            "id": sm.id,
            "court_level": sm.court_level,
            "tribunal_name": sm.tribunal_name,
            "matter_name": sm.matter_name,
            "applicable_doc_types": sm.applicable_doc_types,
            "sort_order": sm.sort_order
        }
        for sm in subject_matters
    ]
