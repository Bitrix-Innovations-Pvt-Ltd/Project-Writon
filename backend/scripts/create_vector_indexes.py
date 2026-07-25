"""
Creates the missing ANN / FTS indexes on the live database.

The RAG pipeline in app/core/rag.py orders by cosine distance (<=>), so all
vector indexes must use vector_cosine_ops. judgment_chunks (~1M rows) gets
ivfflat (fast to build, good recall with probes>1); legal_code_sections is
small but gets the same treatment for consistency.

Safe to re-run: uses IF NOT EXISTS / CONCURRENTLY (no table locks).
Run:  python scripts/create_vector_indexes.py
"""
import asyncio
import os
import sys
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

import asyncpg

INDEXES = [
    (
        "idx_judgment_chunks_embedding",
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_judgment_chunks_embedding
           ON judgment_chunks USING ivfflat (embedding vector_cosine_ops)
           WITH (lists = 1000)""",
    ),
    (
        "idx_lcs_embedding",
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lcs_embedding
           ON legal_code_sections USING ivfflat (embedding vector_cosine_ops)
           WITH (lists = 50)""",
    ),
    (
        "idx_lcs_search",
        """CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_lcs_search
           ON legal_code_sections USING GIN (search_vector)""",
    ),
]


async def main():
    url = os.environ["DATABASE_URL"].split("?")[0]
    conn = await asyncpg.connect(url, ssl="require")
    # Index build on ~1M vectors needs a long statement timeout
    await conn.execute("SET statement_timeout = 0")
    try:
        await conn.execute("SET maintenance_work_mem = '512MB'")
    except Exception as e:
        print(f"maintenance_work_mem not raised ({e}) — continuing with default")

    for name, ddl in INDEXES:
        t0 = time.time()
        print(f"Creating {name} ...", flush=True)
        try:
            await conn.execute(ddl)
            print(f"  done in {time.time() - t0:.1f}s")
        except Exception as e:
            print(f"  FAILED: {e}")

    rows = await conn.fetch(
        """SELECT tablename, indexname FROM pg_indexes
           WHERE tablename IN ('judgment_chunks', 'legal_code_sections')
           ORDER BY tablename, indexname"""
    )
    print("\nCurrent indexes:")
    for r in rows:
        print(f"  {r['tablename']}: {r['indexname']}")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
