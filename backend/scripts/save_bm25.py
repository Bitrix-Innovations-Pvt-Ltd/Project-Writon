import os
import asyncio
import sys
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_root_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '.env')
from dotenv import load_dotenv
load_dotenv(_root_env)

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.models.judgment import Judgment
from pinecone_text.sparse import BM25Encoder

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
if "?" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.split("?")[0]

engine = create_async_engine(DATABASE_URL, echo=False, connect_args={"ssl": True})
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def main():
    print("Fetching up to 1000 random judgments (full text)...")
    async with AsyncSessionLocal() as session:
        # Use simple limit since random ordering across 5000 is slow, just get first 1000
        result = await session.execute(
            select(Judgment.petitioner, Judgment.respondent, Judgment.summary, Judgment.full_text)
            .limit(1000)
        )
        judgments = result.all()

    print("Building text corpus...")
    texts = []
    for j in judgments:
        # Use full_text for BM25 fitting
        text = f"{j.petitioner or ''} v. {j.respondent or ''}. {j.summary or ''} {j.full_text or ''}"
        if len(text.strip()) > 10:
            texts.append(text.strip())

    print(f"Fitting BM25 on {len(texts)} documents...")
    bm25 = BM25Encoder()
    bm25.fit(texts)
    
    # Save to file
    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bm25_model.json")
    bm25.dump(out_path)
    print(f"BM25 model saved to {out_path}")

if __name__ == "__main__":
    asyncio.run(main())
