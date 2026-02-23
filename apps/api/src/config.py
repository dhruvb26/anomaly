"""Environment configuration and database URI helpers."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_REQUIRED_ENV = (
    "LANGSMITH_API_KEY",
    "LANGSMITH_TRACING",
    "LANGSMITH_WORKSPACE_ID",
    "LANGSMITH_PROJECT",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "COMPOSIO_API_KEY",
    "TOGETHER_API_KEY",
    "NEO4J_URI",
    "NEO4J_USERNAME",
    "NEO4J_PASSWORD",
    "NEO4J_DATABASE",
    "DB_URI",
    "REDIS_URL",
)


def check_env() -> None:
    """Warn on missing required env vars."""
    for key in _REQUIRED_ENV:
        if not os.getenv(key):
            logger.warning("Missing env var: %s", key)


def get_db_uri() -> str:
    return os.getenv("DB_URI")
