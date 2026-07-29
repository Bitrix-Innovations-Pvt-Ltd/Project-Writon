"""
Corpus integrity check for the retrieval stack. Exits non-zero on failure so it
can gate a deploy.

Checks:
  - every legal_code_sections row has an embedding and a search_vector
  - no junk section numbers (amendment years ingested as sections)
  - no empty or absurdly long section_text, no bloated titles
  - no HTML left by the ingester
  - every vector column has an ANN index, and it is cosine (queries use <=>)
  - retrieval config tables are populated (hints, config keys, act aliases)

  python scripts/validate_corpus.py
"""
import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

MAX_SECTION_CHARS = 20000
MAX_TITLE_CHARS = 180

failures: list = []
warnings: list = []


def check(label: str, sql: str, limit: int = 0, warn_only: bool = False):
    cur.execute(sql)
    n = cur.fetchone()[0]
    status = "ok " if n <= limit else ("WARN" if warn_only else "FAIL")
    print(f"  [{status}] {label}: {n}")
    if n > limit:
        (warnings if warn_only else failures).append(f"{label} = {n}")


conn = psycopg2.connect(os.environ["DATABASE_URL"].strip('"'))
conn.set_session(readonly=True, autocommit=True)
cur = conn.cursor()

print("Statute corpus:")
check("sections without embedding", "SELECT count(*) FROM legal_code_sections WHERE embedding IS NULL")
check("sections without search_vector", "SELECT count(*) FROM legal_code_sections WHERE search_vector IS NULL")
check("empty section_text", "SELECT count(*) FROM legal_code_sections WHERE coalesce(section_text,'') = ''")
check("junk section numbers",
      r"SELECT count(*) FROM legal_code_sections WHERE section_number ~ '^\d+$' AND section_number::int > 999")
check(f"section_text > {MAX_SECTION_CHARS} chars",
      f"SELECT count(*) FROM legal_code_sections WHERE length(section_text) > {MAX_SECTION_CHARS}")
check(f"title > {MAX_TITLE_CHARS} chars",
      f"SELECT count(*) FROM legal_code_sections WHERE length(title) > {MAX_TITLE_CHARS}")
check("residual HTML in section_text",
      "SELECT count(*) FROM legal_code_sections WHERE section_text ~ '<[a-zA-Z/][^>]*>'")
check("codes with no sections",
      "SELECT count(*) FROM legal_codes lc WHERE NOT EXISTS "
      "(SELECT 1 FROM legal_code_sections s WHERE s.legal_code_id = lc.id)", warn_only=True)

print("Judgment corpus:")
check("chunks without embedding", "SELECT count(*) FROM judgment_chunks WHERE embedding IS NULL")

print("Indexes:")
cur.execute("""
    SELECT c.relname AS tbl,
           count(*) FILTER (WHERE i.indexdef ~* 'USING (hnsw|ivfflat)') AS ann,
           count(*) FILTER (WHERE i.indexdef ~* 'vector_cosine_ops')    AS cosine
    FROM pg_class c
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'embedding'
    LEFT JOIN pg_indexes i ON i.tablename = c.relname
    WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace
    GROUP BY c.relname ORDER BY c.relname
""")
for tbl, ann, cosine in cur.fetchall():
    ok = ann > 0 and cosine == ann
    print(f"  [{'ok ' if ok else 'FAIL'}] {tbl}: {ann} ANN index(es), {cosine} cosine")
    if not ok:
        failures.append(f"{tbl} ANN/cosine index missing (ann={ann}, cosine={cosine})")

print("Retrieval config:")
for label, sql, minimum in [
    ("doc_type_retrieval_hints rows", "SELECT count(*) FROM doc_type_retrieval_hints", 10),
    ("retrieval_config keys", "SELECT count(*) FROM retrieval_config", 5),
    ("legal_codes with aliases", "SELECT count(*) FROM legal_codes WHERE aliases IS NOT NULL", 20),
]:
    cur.execute(sql)
    n = cur.fetchone()[0]
    ok = n >= minimum
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}: {n} (min {minimum})")
    if not ok:
        failures.append(f"{label} = {n} < {minimum}")

cur.execute("SELECT count(*) FROM legal_code_sections")
total = cur.fetchone()[0]
print(f"\nTotal statute sections: {total}")
cur.close()
conn.close()

for w in warnings:
    print(f"WARNING: {w}")
if failures:
    print("\nFAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All corpus integrity checks passed.")
