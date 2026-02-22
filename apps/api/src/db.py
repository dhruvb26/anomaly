"""Database setup utilities."""

from __future__ import annotations

import logging

import psycopg

from src.config import get_db_uri

logger = logging.getLogger(__name__)


async def ensure_threads_table() -> None:
    """Create the threads table if it does not already exist."""
    db_uri = get_db_uri()
    try:
        async with await psycopg.AsyncConnection.connect(db_uri) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS threads (
                    thread_id TEXT PRIMARY KEY,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    metadata JSONB DEFAULT '{}'::jsonb
                )
            """)
            await conn.commit()
    except Exception:
        logger.exception("Failed to ensure threads table")
        raise
