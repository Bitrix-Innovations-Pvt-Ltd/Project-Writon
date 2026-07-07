from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.models.subject_matter_analytics import SubjectMatterAnalytics

router = APIRouter(prefix="/analytics", tags=["analytics"])

class SubjectMatterAnalyticsRequest(BaseModel):
    court_level: str
    selected_other: bool
    case_description_snippet: str

@router.post("/subject-matter")
async def log_subject_matter(
    request: SubjectMatterAnalyticsRequest,
    db: AsyncSession = Depends(get_db)
):
    # Truncate case description to 100 chars just in case
    snippet = request.case_description_snippet[:100] if request.case_description_snippet else ""
    
    analytics = SubjectMatterAnalytics(
        court_level=request.court_level,
        selected_other=request.selected_other,
        case_description_snippet=snippet
    )
    
    db.add(analytics)
    await db.commit()
    
    return {"status": "success"}
