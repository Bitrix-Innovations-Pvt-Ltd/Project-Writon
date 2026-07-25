import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import asyncio
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import (
    search as search_v1,
    judgment as judgment_v1,
    document_types as document_types_v1,
    subject_matters as subject_matters_v1,
    document_requirements as document_requirements_v1,
    analytics as analytics_v1,
    uploads as uploads_v1,
    drafting as drafting_v1,
    courts as courts_v1,
    hierarchy as hierarchy_v1,
    court_rules as court_rules_v1,
    gapfill as gapfill_v1,
)

app = FastAPI(title="WritOnline API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search_v1.router, prefix="/api/v1")
app.include_router(judgment_v1.router, prefix="/api/v1")
app.include_router(document_types_v1.router, prefix="/api/v1")
app.include_router(subject_matters_v1.router, prefix="/api/v1")
app.include_router(document_requirements_v1.router, prefix="/api/v1")
app.include_router(analytics_v1.router, prefix="/api/v1")
app.include_router(uploads_v1.router, prefix="/api/v1")
app.include_router(drafting_v1.router, prefix="/api/v1")
app.include_router(courts_v1.router, prefix="/api/v1/courts")
app.include_router(hierarchy_v1.router, prefix="/api/v1/hierarchy")
app.include_router(court_rules_v1.router, prefix="/api/v1")
app.include_router(gapfill_v1.router, prefix="/api/v1")


@app.on_event("startup")
async def preload_models():
    """Pre-load AI models on server start (non-blocking background tasks).
    This ensures the first real user request is not delayed by model loading."""
    from app.core.rag import load_reranker
    from app.api.v1.search import get_model
    asyncio.create_task(load_reranker())
    asyncio.create_task(get_model())


@app.on_event("startup")
async def keep_db_warm():
    """
    Periodically runs one cheap ANN query per vector corpus so Neon's compute
    never autosuspends and the ivfflat/hnsw index pages stay in page cache.

    Without this, the first Step 6 request after idle pays compute wake-up +
    cold page reads on every vector query (~7s each instead of ~0.3s) and can
    take minutes. Interval must stay below Neon's autosuspend window (5 min).

    Set RAG_KEEPWARM_INTERVAL_SECONDS=0 to disable (saves Neon compute hours
    at the cost of cold-start latency).
    """
    interval = int(os.getenv("RAG_KEEPWARM_INTERVAL_SECONDS", "240"))
    if interval <= 0:
        return

    async def _loop():
        from sqlalchemy import text
        from app.core.database import engine

        warm_sqls = [
            # ORDER BY distance forces a real index scan → warms index pages
            """SELECT jc.id FROM judgment_chunks jc
               ORDER BY jc.embedding <=> (SELECT embedding FROM judgment_chunks
                                          WHERE embedding IS NOT NULL LIMIT 1)
               LIMIT 1""",
            """SELECT j.id FROM judgments j
               ORDER BY j.embedding <=> (SELECT embedding FROM judgments
                                         WHERE embedding IS NOT NULL LIMIT 1)
               LIMIT 1""",
            """SELECT lcs.id FROM legal_code_sections lcs
               ORDER BY lcs.embedding <=> (SELECT embedding FROM legal_code_sections
                                           WHERE embedding IS NOT NULL LIMIT 1)
               LIMIT 1""",
        ]
        while True:
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SET LOCAL ivfflat.probes = 20"))
                    for sql in warm_sqls:
                        await conn.execute(text(sql))
            except Exception as e:
                print(f"[keep-warm] ping failed (non-fatal): {e}")
            await asyncio.sleep(interval)

    asyncio.create_task(_loop())


@app.get("/api/health")
def health_check():
    return {"status": "ok"}

@app.get("/api/embed-missing")
async def embed_missing():
    import sys, os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from scripts.embed_statutes import embed_statutes
    import asyncio
    asyncio.create_task(embed_statutes())
    return {"status": "Embedding started in background. Check backend console."}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

