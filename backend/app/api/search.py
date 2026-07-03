import os
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from app.core.database import get_db
from app.models.judgment import Judgment
from typing import Optional, List
from pinecone import Pinecone
from sentence_transformers import SentenceTransformer
from pinecone_text.sparse import BM25Encoder

router = APIRouter(prefix="/search", tags=["search"])

# Global Initialization (lazy load to not crash startup immediately if keys missing)
pc = None
index = None
model = None
bm25 = None

def init_ai():
    global pc, index, model, bm25
    if pc is None:
        api_key = os.environ.get("PINECONE_API_KEY")
        if api_key:
            pc = Pinecone(api_key=api_key)
            index = pc.Index("writon-judgments")
            # Load models
            print("Loading Legal-BERT for API...")
            model = SentenceTransformer('nlpaueb/legal-bert-base-uncased')
            print("Loading BM25 for API...")
            bm25 = BM25Encoder()
            
            # Use absolute path to backend/bm25_model.json
            bm25_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "bm25_model.json")
            if os.path.exists(bm25_path):
                bm25.load(bm25_path)
                print("BM25 loaded successfully from file.")
            else:
                print("Warning: bm25_model.json not found! Falling back to slow default.")
                bm25 = BM25Encoder().default()

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
    init_ai()
    
    # 1. Base DB Query
    base_query = select(Judgment)
    
    # 2. Apply DB Filters (used for fallback or when q is empty, and to fetch final results)
    if category:
        base_query = base_query.where(Judgment.case_type.in_(category))
    if case_type:
        base_query = base_query.where(Judgment.case_type.in_(case_type))
    if year:
        base_query = base_query.where(Judgment.year.in_(year))
        
    judgments = []
    total_items = 0
    
    # 3. Execution Path
    if q and index and model and bm25:
        # AI HYBRID SEARCH PATH
        
        # Build Pinecone Metadata Filter
        pc_filter = {}
        if category:
            pc_filter["category"] = {"$in": category}
        if case_type:
            pc_filter["case_type"] = {"$in": case_type}
        if year:
            pc_filter["year"] = {"$in": year}
            
        # Encode Query
        dense = model.encode(q).tolist()
        sparse = bm25.encode_queries(q)
        
        # Query Pinecone
        try:
            pc_res = index.query(
                vector=dense,
                sparse_vector=sparse,
                top_k=50,
                include_metadata=False,
                filter=pc_filter if pc_filter else None
            )
            
            match_ids = [int(m.id) for m in pc_res.matches]
            total_items = len(match_ids)
            
            if match_ids:
                # Paginate the match IDs manually
                start_idx = (page - 1) * limit
                paginated_ids = match_ids[start_idx : start_idx + limit]
                
                # Fetch from Neon matching these IDs
                if paginated_ids:
                    # We need to preserve the order from Pinecone!
                    db_res = await db.execute(base_query.where(Judgment.id.in_(paginated_ids)))
                    db_judgments = db_res.scalars().all()
                    
                    # Sort them exactly as Pinecone ranked them
                    id_to_judgment = {j.id: j for j in db_judgments}
                    judgments = [id_to_judgment[id] for id in paginated_ids if id in id_to_judgment]
        except Exception as e:
            print("Pinecone error:", e)
            # Fallback if pinecone fails
            q = None 
    
    if not q:
        # FALLBACK KEYWORD / DB FILTER PATH (if q is empty or AI fails)
        count_query = select(func.count()).select_from(base_query.subquery())
        total_items = (await db.execute(count_query)).scalar() or 0
        
        paginated_query = base_query.order_by(Judgment.year.desc().nulls_last(), Judgment.id.asc())
        paginated_query = paginated_query.offset((page - 1) * limit).limit(limit)
        judgments = (await db.execute(paginated_query)).scalars().all()

    # 4. Compute Live Counts (Facets)
    # We will query the DB to get the distribution of case_types and years for the CURRENT filtered base query
    # To keep it fast, we group by case_type.
    facet_case_type = {}
    facet_year = {}
    
    # We can do two quick GROUP BY queries on the DB
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
