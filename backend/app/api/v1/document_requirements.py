from typing import List, Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.document_requirement import DocumentRequirement

router = APIRouter(prefix="/document-requirements", tags=["document-requirements"])

@router.get("/")
async def get_document_requirements(
    court_level: Annotated[str, Query(description="Level of the court")],
    subject_matter: Annotated[str, Query(description="Selected subject matter")],
    db: AsyncSession = Depends(get_db)
):
    # Depending on the selected subject_matter, fetch the associated documents
    stmt = select(DocumentRequirement).where(
        DocumentRequirement.court_level == court_level,
        DocumentRequirement.subject_matter == subject_matter
    ).order_by(DocumentRequirement.requirement_type.desc(), DocumentRequirement.sort_order.asc())
    
    result = await db.execute(stmt)
    docs = result.scalars().all()
    
    # If no exact match (e.g., custom subject matter added later or weird fallback), fallback to "Other"
    if not docs:
        stmt = select(DocumentRequirement).where(
            DocumentRequirement.court_level == court_level,
            DocumentRequirement.subject_matter == "Other"
        ).order_by(DocumentRequirement.requirement_type.desc(), DocumentRequirement.sort_order.asc())
        result = await db.execute(stmt)
        docs = result.scalars().all()

    return [
        {
            "id": doc.id,
            "document_name": doc.document_name,
            "description": doc.description,
            "requirement_type": doc.requirement_type,
            "sort_order": doc.sort_order
        }
        for doc in docs
    ]
