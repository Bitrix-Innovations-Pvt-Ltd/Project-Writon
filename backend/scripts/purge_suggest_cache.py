"""
Purge cached suggest-citations results from Redis.

Run after any retrieval change (corpus, embeddings, reranker, hints) —
otherwise users keep seeing stale cached suggestions for up to 6 hours.

  python scripts/purge_suggest_cache.py [pattern]   # default suggest_citations:*
"""
import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))


async def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "suggest_citations:*"
    from app.core.redis import _get_client

    client = await _get_client()
    if client is None:
        print("Redis not configured/reachable — nothing to purge (in-memory cache dies with the server process).")
        return
    deleted = 0
    async for key in client.scan_iter(match=pattern, count=200):
        await client.delete(key)
        deleted += 1
    print(f"Deleted {deleted} keys matching {pattern}")
    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
