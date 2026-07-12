import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, text
from app.core.database import engine

async def embed_statutes():
    print("Loading model...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer('nlpaueb/legal-bert-base-uncased')

    print("Fetching statutes...")
    async with engine.begin() as conn:
        res = await conn.execute(text("""
            SELECT lcs.id, lcs.section_text, lcs.title, lcs.section_number, 
                   lc.code_name, lc.short_code
            FROM legal_code_sections lcs
            JOIN legal_codes lc ON lc.id = lcs.legal_code_id
            WHERE lcs.embedding IS NULL
        """))
        rows = res.fetchall()

    if not rows:
        print("No statutes need embedding.")
        return

    print(f"Need to embed {len(rows)} statutes. Starting...")
    
    batch_size = 100
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i+batch_size]
        texts = [f"{r.code_name} ({r.short_code}) Section {r.section_number}: {r.title or ''}. {r.section_text or ''}" for r in batch]
        
        vectors = model.encode(texts).tolist()
        
        async with engine.begin() as conn:
            for idx, r in enumerate(batch):
                await conn.execute(
                    text("UPDATE legal_code_sections SET embedding = :emb WHERE id = :id"),
                    {"emb": str(vectors[idx]), "id": r.id}
                )
        print(f"Embedded batch {i//batch_size + 1}/{(len(rows) + batch_size - 1)//batch_size}")
        
    print("Done embedding statutes!")

if __name__ == '__main__':
    asyncio.run(embed_statutes())
