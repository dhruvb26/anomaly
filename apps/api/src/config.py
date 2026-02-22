"""Environment configuration and database URI helpers."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_REQUIRED_ENV = (
    "ANTHROPIC_API_KEY",
    "LANGSMITH_API_KEY",
    "DB_URI",
    "REDIS_URL",
    "COMPOSIO_API_KEY",
    "NEO4J_URI",
    "NEO4J_USERNAME",
    "NEO4J_PASSWORD",
    "TOGETHER_API_KEY",
)


def check_env() -> None:
    """Warn on missing required env vars; do not hard-fail (DB_URI has default)."""
    for key in _REQUIRED_ENV:
        if not os.getenv(key):
            logger.warning("Missing env var: %s", key)


def get_db_uri() -> str:
    return os.getenv(
        "DB_URI", "postgresql://postgres:postgres@localhost:5433/langgraph"
    )
