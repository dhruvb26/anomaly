"""LangSmith ingestion routes."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src import state

logger = logging.getLogger(__name__)

router = APIRouter()


class IngestRequest(BaseModel):
    thread_ids: list[str] = []
    project: str | None = None
    clear: bool = False


@router.post("/ingest")
async def ingest_threads(body: IngestRequest):
    """Fetch LangSmith threads and persist them to Neo4j + Redis.

    - ``thread_ids``: explicit IDs to ingest; if empty, all threads are fetched.
    - ``project``: LangSmith project name (falls back to ``LANGSMITH_PROJECT`` env var).
    - ``clear``: wipe Neo4j and Redis before ingesting.
    """
    if state.graph_db is None or state.payload_store is None:
        raise HTTPException(
            status_code=503, detail="Graph DB / payload store not initialised"
        )

    from src.services.ingestion import run_ingestion

    try:
        result = await asyncio.to_thread(
            run_ingestion,
            state.graph_db,
            state.payload_store,
            thread_ids=body.thread_ids or None,
            project=body.project,
            clear=body.clear,
        )
    except Exception as exc:
        logger.exception("Ingestion failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return result


@router.delete("/ingest")
async def clear_stores():
    """Wipe all nodes/edges from Neo4j and all run:* keys from Redis."""
    if state.graph_db is None or state.payload_store is None:
        raise HTTPException(
            status_code=503, detail="Graph DB / payload store not initialised"
        )

    from src.helpers.ingestion import clear_neo4j, clear_redis

    try:
        await asyncio.to_thread(clear_neo4j, state.graph_db)
        await asyncio.to_thread(clear_redis, state.payload_store)
    except Exception as exc:
        logger.exception("Clear failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"ok": True}


@router.delete("/ingest/{thread_id}")
async def clear_thread(thread_id: str):
    """Remove only this thread's graph data from Neo4j and associated run payloads from Redis."""
    if state.graph_db is None or state.payload_store is None:
        raise HTTPException(
            status_code=503, detail="Graph DB / payload store not initialised"
        )

    from src.helpers.ingestion import (
        _collect_run_ids_for_thread,
        clear_thread_neo4j,
        clear_thread_redis,
    )

    try:
        run_ids = await asyncio.to_thread(
            _collect_run_ids_for_thread, state.graph_db, thread_id
        )
        await asyncio.to_thread(clear_thread_neo4j, state.graph_db, thread_id)
        await asyncio.to_thread(clear_thread_redis, state.payload_store, run_ids)
    except Exception as exc:
        logger.exception("Clear thread failed for %s", thread_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"ok": True}
