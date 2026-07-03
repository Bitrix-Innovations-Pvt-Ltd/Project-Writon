import os
import asyncio
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from app.core.database import get_db
from app.models.judgment import Judgment
from typing import Optional, List
from sentence_transformers import SentenceTransformer

router = APIRouter(prefix="/search", tags=["search"])

# Global Initialization
model = None

def init_ai():
    global model
    if model is None:
        print("Loading Legal-BERT for API...")
        model = SentenceTransformer('nlpaueb/legal-bert-base-uncased')

@router.get("/precedents")
async def search_precedents(
    q: Optional[str] = None,
    category: Optional[List[str]] = Query(None),
    year: Optional[List[int]] = Query(None),
    case_type: Optional[List[str]] = Query(None),
    acts_cited: Optional[List[str]] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=50),
    db: AsyncSession = Depends(get_db)
):
    # Initialize the model on first request
    init_ai()
    
    # Base Filters (SQLAlchemy)
    filters = []
    if category:
        filters.append(Judgment.case_type.in_(category))
    if case_type:
        filters.append(Judgment.case_type.in_(case_type))
    if year:
        filters.append(Judgment.year.in_(year))
        
    judgments = []
    total_items = 0
    
    if q and model:
        # 1. Semantic Search (Dense Vector)
        query_vector = model.encode(q).tolist()
        
        # Build raw SQL for vector search (using pgvector)
        # We parameterize properly for safety
        vector_sql = """
            SELECT id, 
                   ROW_NUMBER() OVER(ORDER BY embedding <-> :q_vec) as rank
            FROM judgments
            WHERE embedding IS NOT NULL
        """
        # Append filters to vector SQL
        filter_params = {"q_vec": str(query_vector)}
        
        if category or case_type:
            types = (category or []) + (case_type or [])
            vector_sql += " AND case_type = ANY(:types)"
            filter_params["types"] = types
        if year:
            vector_sql += " AND year = ANY(:years)"
            filter_params["years"] = year
            
        vector_sql += " ORDER BY rank LIMIT 50"
        
        # 2. Keyword Search (BM25 TSVECTOR)
        keyword_sql = """
            SELECT id, 
                   ROW_NUMBER() OVER(ORDER BY ts_rank(search_vector, websearch_to_tsquery('english', :q)) DESC) as rank
            FROM judgments
            WHERE search_vector @@ websearch_to_tsquery('english', :q)
        """
        keyword_params = {"q": q}
        if category or case_type:
            keyword_sql += " AND case_type = ANY(:types)"
            keyword_params["types"] = types
        if year:
            keyword_sql += " AND year = ANY(:years)"
            keyword_params["years"] = year
            
        keyword_sql += " ORDER BY rank LIMIT 50"
        
        # Execute both queries concurrently
        vec_res, kw_res = await asyncio.gather(
            db.execute(text(vector_sql), filter_params),
            db.execute(text(keyword_sql), keyword_params)
        )
        
        semantic_ranks = {row.id: row.rank for row in vec_res.fetchall()}
        keyword_ranks = {row.id: row.rank for row in kw_res.fetchall()}
        
        # 3. Reciprocal Rank Fusion (RRF)
        # We give a 2.0x multiplier to Keyword Search because exact terms like 'Section 302 IPC' 
        # must always outrank purely conceptual matches that don't contain the exact legal codes.
        rrf_scores = {}
        all_ids = set(semantic_ranks.keys()).union(set(keyword_ranks.keys()))
        
        for j_id in all_ids:
            score = 0
            if j_id in semantic_ranks:
                score += 1.0 / (60 + semantic_ranks[j_id])
            if j_id in keyword_ranks:
                score += 2.0 / (60 + keyword_ranks[j_id])  # Boost exact keyword matches
            rrf_scores[j_id] = score
            
        # Sort by RRF score descending
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
        total_items = len(sorted_ids)
        
        # Pagination
        start_idx = (page - 1) * limit
        paginated_ids = sorted_ids[start_idx : start_idx + limit]
        
        if paginated_ids:
            # Fetch full judgment data
            db_res = await db.execute(select(Judgment).where(Judgment.id.in_(paginated_ids)))
            db_judgments = db_res.scalars().all()
            
            # Sort them exactly as our RRF scored them
            id_to_judgment = {j.id: j for j in db_judgments}
            judgments = [id_to_judgment[j_id] for j_id in paginated_ids if j_id in id_to_judgment]
            
    else:
        # Fallback keyword DB Filter path if no query provided
        base_query = select(Judgment)
        for f in filters:
            base_query = base_query.where(f)
            
        count_query = select(func.count()).select_from(base_query.subquery())
        total_items = (await db.execute(count_query)).scalar() or 0
        
        paginated_query = base_query.order_by(Judgment.year.desc().nulls_last(), Judgment.id.asc())
        paginated_query = paginated_query.offset((page - 1) * limit).limit(limit)
        judgments = (await db.execute(paginated_query)).scalars().all()

    # 4. Compute Live Counts (Facets)
    facet_case_type = {}
    facet_year = {}
    
    base_query = select(Judgment)
    for f in filters:
        base_query = base_query.where(f)
        
    ct_query = select(Judgment.case_type, func.count()).select_from(base_query.subquery()).group_by(Judgment.case_type)
    for row in (await db.execute(ct_query)).all():
        if row[0]:
            facet_case_type[row[0]] = row[1]
            
    # Format response
    items = []
    for j in judgments:
        title = "Unknown v. Unknown"
        if j.petitioner and j.respondent:
            title = f"{j.petitioner} v. {j.respondent}"
            
        items.append({
            "id": j.id,
            "title": title,
            "year": j.year or "N/A",
            "case_type": j.case_type or "General",
            "summary": j.summary or "",
            "court": "SC",
            "binding_on": "All High Courts & District Courts" if "Constitutional" in (j.case_type or "") else "Relevant Subordinate Courts"
        })
        
    return {
        "items": items,
        "total": total_items,
        "page": page,
        "limit": limit,
        "total_pages": (total_items + limit - 1) // limit if limit else 0,
        "facets": {
            "case_type": facet_case_type,
            "year": facet_year
        }
    }
