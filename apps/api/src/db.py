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
    except Exception as e:
        logger.exception(f"Failed to ensure threads table in database {db_uri}: {e}")
        raise


async def ensure_sentinel_reports_table() -> None:
    """Create the sentinel_reports table if it does not already exist."""
    db_uri = get_db_uri()
    try:
        async with await psycopg.AsyncConnection.connect(db_uri) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sentinel_reports (
                    id SERIAL PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    max_tier INTEGER NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL DEFAULT '',
                    recommendations JSONB DEFAULT '[]'::jsonb,
                    turn_analyses JSONB DEFAULT '[]'::jsonb
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sentinel_reports_thread_id
                ON sentinel_reports(thread_id)
            """)
            await conn.execute("""
                ALTER TABLE sentinel_reports
                ADD COLUMN IF NOT EXISTS resource_anomalies JSONB DEFAULT '[]'::jsonb
            """)
            await conn.commit()
    except Exception as e:
        logger.exception(
            "Failed to ensure sentinel_reports table in database %s: %s", db_uri, e
        )
        raise
