from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.court import HighCourt, HighCourtBench

router = APIRouter(tags=["Courts"])

from sqlalchemy.orm import selectinload

@router.get("/high-courts")
async def get_high_courts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(HighCourt).options(selectinload(HighCourt.benches)).order_by(HighCourt.name)
    )
    return result.scalars().all()

@router.get("/high-courts/{court_id}/benches")
async def get_high_court_benches(court_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(HighCourtBench).where(HighCourtBench.high_court_id == court_id)
    )
    return result.scalars().all()
