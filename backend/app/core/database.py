import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from dotenv import load_dotenv

# Load from root .env
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', '.env')
load_dotenv(dotenv_path)

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set")

# Convert postgresql:// to postgresql+asyncpg:// for async sqlalchemy
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    # asyncpg doesn't support the ?sslmode=require string format via SQLAlchemy
    DATABASE_URL = DATABASE_URL.split("?")[0]

# Neon needs SSL requirement
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_size=30,
    max_overflow=20,
    pool_timeout=60,
    pool_pre_ping=True,    # Checks if connection is alive before using it
    pool_recycle=1800,     # Recycles connections after 30 minutes to avoid DB timeouts
)


@asynccontextmanager
async def write_transaction():
    """Transaction that is guaranteed writable — use for every INSERT/UPDATE.

    The Neon endpoint hands out sessions with default_transaction_read_only=on,
    and its pooler does not reliably carry per-connection overrides, so writes
    on a plain engine.begin() fail with ReadOnlySQLTransaction (this was
    silently swallowing the app's writes inside try/except blocks). Declaring
    the mode inside the transaction is pooling-safe because the pooler pins the
    server connection for the transaction's duration.
    """
    async with engine.begin() as conn:
        await conn.execute(text("SET TRANSACTION READ WRITE"))
        yield conn

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

Base = declarative_base()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
