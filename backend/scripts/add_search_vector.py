import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv('../.env')
url = os.environ.get('DATABASE_URL').replace('postgresql://', 'postgresql+asyncpg://').split('?')[0]
engine = create_async_engine(url, echo=True)

async def add_search_vector():
    async with engine.connect() as conn:
        try:
            # Check if search_vector exists already
            res = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'judgments' AND column_name = 'search_vector';"))
            if not res.fetchone():
                print("Adding search_vector column...")
                await conn.execute(text("""
                    ALTER TABLE judgments
                    ADD COLUMN search_vector TSVECTOR
                    GENERATED ALWAYS AS (
                        to_tsvector('english',
                            coalesce(petitioner,'') || ' ' ||
                            coalesce(respondent,'') || ' ' ||
                            coalesce(summary,'') || ' ' ||
                            coalesce(holding,'')
                        )
                    ) STORED;
                """))
                await conn.commit()
                print("search_vector column added.")
            else:
                print("search_vector column already exists.")

            # Add GIN index
            print("Creating GIN index on search_vector...")
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_judgments_search_vector 
                ON judgments USING GIN (search_vector);
            """))
            await conn.commit()
            print("GIN index created successfully.")
            
        except Exception as e:
            print(f"Error: {e}")

asyncio.run(add_search_vector())
