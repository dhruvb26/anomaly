"""Agent run invocation route."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src import state
from src.helpers.ingestion import auto_ingest
from src.helpers.sentinel import run_sentinel
from src.serializers import deserialize_message, serialize_message

logger = logging.getLogger(__name__)

router = APIRouter()


class RunRequest(BaseModel):
    messages: list[dict[str, Any]] = []


@router.post("/threads/{thread_id}/runs")
async def run_thread(thread_id: str, body: RunRequest):
    """Invoke the agent to completion; return final messages and graph ingest status."""
    if state.graph is None:
        raise HTTPException(status_code=503, detail="Graph not initialised")

    deserialized = [deserialize_message(m) for m in body.messages]
    config = {"configurable": {"thread_id": thread_id}}

    try:
        await state.graph.ainvoke({"messages": deserialized}, config=config)
    except Exception as e:
        logger.exception("Run failed for thread %s", thread_id)
        raise HTTPException(status_code=500, detail=str(e))

    messages: list[dict] = []
    try:
        thread_state = await state.graph.aget_state(config)
        if thread_state and thread_state.values and "messages" in thread_state.values:
            messages = [
                serialize_message(m) for m in thread_state.values["messages"]
            ]
    except Exception:
        logger.exception("Failed to read final state for thread %s", thread_id)

    results = await asyncio.gather(
        asyncio.to_thread(auto_ingest, thread_id),
        asyncio.to_thread(run_sentinel, thread_id),
        return_exceptions=True,
    )
    graph_ready = results[0] if isinstance(results[0], bool) else False
    sentinel_result = results[1] if isinstance(results[1], dict) else None

    return {"messages": messages, "graph_ready": graph_ready, "sentinel": sentinel_result}
