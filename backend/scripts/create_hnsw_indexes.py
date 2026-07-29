"""
Replace ivfflat vector indexes with HNSW (better recall at lower latency;
pgvector >= 0.8 supports iterative scans so filtered queries stop
under-returning).

Connects to the DIRECT Neon host (pooler kills long-running DDL) with
statement_timeout=0. Builds the new index first, then drops the old ivfflat
one, so there is never a moment without an ANN index.

Usage:
  python scripts/create_hnsw_indexes.py legal_code_sections
  python scripts/create_hnsw_indexes.py judgment_chunks      # long build (~1h)
"""
import os
import sys
import time

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

TARGETS = {
    "legal_code_sections": {"old_index": "idx_lcs_embedding", "new_index": "idx_lcs_embedding_hnsw"},
    "judgment_chunks": {"old_index": "idx_judgment_chunks_embedding", "new_index": "idx_judgment_chunks_embedding_hnsw"},
}


def main():
    table = sys.argv[1] if len(sys.argv) > 1 else None
    if table not in TARGETS:
        print(f"usage: create_hnsw_indexes.py [{'|'.join(TARGETS)}]")
        sys.exit(1)
    t = TARGETS[table]

    # Direct (non-pooler) host for long DDL
    url = os.environ["DATABASE_URL"].strip('"').replace("-pooler", "")
    conn = psycopg2.connect(url)
    conn.set_session(readonly=False, autocommit=True)
    cur = conn.cursor()
    cur.execute("SET statement_timeout = 0")
    # As much build memory as the compute allows; Neon clamps if too high
    for mwm in ("1GB", "512MB", "256MB"):
        try:
            cur.execute(f"SET maintenance_work_mem = '{mwm}'")
            break
        except psycopg2.Error:
            pass
    cur.execute("SET max_parallel_maintenance_workers = 2")

    cur.execute("SELECT count(*) FROM " + table + " WHERE embedding IS NOT NULL")
    n = cur.fetchone()[0]
    print(f"{table}: {n} embedded rows — building HNSW (m=16, ef_construction=64)...")

    t0 = time.time()
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS {t['new_index']} ON {table} "
        f"USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    print(f"HNSW built in {time.time() - t0:.0f}s")

    cur.execute(f"DROP INDEX IF EXISTS {t['old_index']}")
    print(f"Dropped old ivfflat index {t['old_index']}")

    cur.execute(
        "SELECT indexname, pg_size_pretty(pg_relation_size(indexname::regclass)) "
        "FROM pg_indexes WHERE tablename = %s", (table,)
    )
    for r in cur.fetchall():
        print(" ", r)
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
