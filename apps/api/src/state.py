"""Shared mutable application state set during lifespan startup.

Import this module and access attributes directly (e.g. ``state.graph``) so
that mutations made during the lifespan are visible to all callers. Never use
``from src.state import graph`` — that captures the initial ``None`` value.
"""

from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore

checkpointer: AsyncPostgresSaver | None = None
store: AsyncPostgresStore | None = None
graph = None
graph_db = None
payload_store = None
