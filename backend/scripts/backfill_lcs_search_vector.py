import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import engine


async def backfill():
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM legal_code_sections WHERE search_vector IS NULL"))
        before = result.scalar()
        print(f"Backfilling {before} rows with NULL search_vector...")
        if before == 0:
            print("Nothing to backfill.")
            return
        sql = """
            UPDATE legal_code_sections
            SET search_vector =
                setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(section_text, '')), 'B')
            WHERE search_vector IS NULL
        """
        await conn.execute(text(sql))
        print("Backfill UPDATE executed.")
        result = await conn.execute(text("SELECT COUNT(*) FROM legal_code_sections WHERE search_vector IS NULL"))
        after = result.scalar()
        print(f"Backfill complete. Remaining NULL: {after}")
        if after > 0:
            print(f"WARNING: {after} rows still NULL.")
        else:
            print("All rows successfully backfilled.")


if __name__ == '__main__':
    asyncio.run(backfill())
