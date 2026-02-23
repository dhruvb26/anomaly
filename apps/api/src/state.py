"""Shared mutable application state set during lifespan startup."""

from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore
from src.stores.graph_db import GraphDB
from src.stores.payload_store import PayloadStore

checkpointer: AsyncPostgresSaver | None = None
store: AsyncPostgresStore | None = None
graph = None
graph_db: GraphDB | None = None
payload_store: PayloadStore | None = None
