"""
Embed legal_code_sections rows that have no vector yet.

Uses psycopg2 against the DIRECT (non-pooler) Neon endpoint with an explicit
read-write session: the pooler endpoint hands out sessions with
default_transaction_read_only=on and does not reliably carry per-client
startup settings, so batch UPDATEs there fail with ReadOnlySQLTransaction
partway through a run.

  python scripts/embed_statutes.py            # embed everything missing
  python scripts/embed_statutes.py --limit 500
"""
import os
import sys

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

BATCH = 100
# Legal-BERT truncates at 512 tokens; sending more just wastes CPU
MAX_CHARS = 2000


def _connect():
    url = os.environ["DATABASE_URL"].strip('"').replace("-pooler", "")
    conn = psycopg2.connect(url)
    conn.set_session(readonly=False, autocommit=False)
    return conn


def embed_statutes():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """SELECT lcs.id, lcs.section_text, lcs.title, lcs.section_number,
                  lc.code_name, lc.short_code
           FROM legal_code_sections lcs
           JOIN legal_codes lc ON lc.id = lcs.legal_code_id
           WHERE lcs.embedding IS NULL
           ORDER BY lcs.id""" + (f" LIMIT {limit}" if limit else "")
    )
    rows = cur.fetchall()
    if not rows:
        print("No statutes need embedding.")
        return

    print(f"Need to embed {len(rows)} statutes. Loading model...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("nlpaueb/legal-bert-base-uncased")

    total = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        texts = [
            f"{code_name} ({short_code}) Section {section_number}: {title or ''}. {(section_text or '')[:MAX_CHARS]}"
            for _id, section_text, title, section_number, code_name, short_code in batch
        ]
        vectors = model.encode(texts, batch_size=16).tolist()
        psycopg2.extras.execute_batch(
            cur,
            "UPDATE legal_code_sections SET embedding = %s WHERE id = %s",
            [(str(v), r[0]) for v, r in zip(vectors, batch)],
            page_size=BATCH,
        )
        conn.commit()
        total += len(batch)
        print(f"Embedded batch {i // BATCH + 1}/{(len(rows) + BATCH - 1) // BATCH} ({total}/{len(rows)})")

    cur.execute("SELECT count(*) FROM legal_code_sections WHERE embedding IS NULL")
    print(f"Done. Remaining without embedding: {cur.fetchone()[0]}")
    cur.close()
    conn.close()


if __name__ == "__main__":
    embed_statutes()
