import asyncio
import sys

sys.path.append(r"c:\Users\Shivam\OneDrive\Desktop\Project- Writon\backend")

from sqlalchemy import text
from app.core.database import engine

async def m():
    async with engine.connect() as c:
        r = await c.execute(text("SELECT holding FROM judgments WHERE holding IS NOT NULL LIMIT 1"))
        print(repr(r.scalar()))

asyncio.run(m())
