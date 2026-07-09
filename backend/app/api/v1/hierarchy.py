from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.hierarchy import HierarchyCategory, HierarchyCaseType, HierarchySubCategory

router = APIRouter(tags=["Hierarchy"])

@router.get("/categories")
async def get_categories(court_level: str = Query(...), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(HierarchyCategory).where(HierarchyCategory.court_level == court_level).order_by(HierarchyCategory.sort_order)
    )
    return result.scalars().all()

@router.get("/case-types")
async def get_case_types(category_id: int = Query(...), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(HierarchyCaseType).where(HierarchyCaseType.category_id == category_id).order_by(HierarchyCaseType.sort_order)
    )
    return result.scalars().all()
    
@router.get("/sub-categories")
async def get_sub_categories(case_type_id: int = Query(...), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(HierarchySubCategory).where(HierarchySubCategory.case_type_id == case_type_id).order_by(HierarchySubCategory.sort_order)
    )
    return result.scalars().all()
