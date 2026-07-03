import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv('../.env')

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "?sslmode=" in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.split("?")[0]

engine = create_async_engine(DATABASE_URL, echo=True)

async def run():
    async with engine.begin() as conn:
        print("Creating pgvector extension...")
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        
        print("Adding columns to judgments table...")
        await conn.execute(text("ALTER TABLE judgments ADD COLUMN IF NOT EXISTS search_vector TSVECTOR"))
        await conn.execute(text("ALTER TABLE judgments ADD COLUMN IF NOT EXISTS embedding VECTOR(768)"))
        
    print("Database schema successfully updated!")

if __name__ == "__main__":
    asyncio.run(run())
