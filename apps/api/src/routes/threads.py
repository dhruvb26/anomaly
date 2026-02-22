"""Thread CRUD, state, and graph routes."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src import state
from src.config import get_db_uri
from src.serializers import row_to_thread, serialize_message

logger = logging.getLogger(__name__)

router = APIRouter()


class ThreadPatch(BaseModel):
    metadata: dict[str, Any] | None = None


@router.post("/threads")
async def create_thread():
    thread_id = str(uuid.uuid4())
    db_uri = get_db_uri()
    try:
        async with await psycopg.AsyncConnection.connect(db_uri) as conn:
            await conn.execute(
                "INSERT INTO threads (thread_id) VALUES (%s)",
                (thread_id,),
            )
            await conn.commit()
    except Exception:
        logger.exception("Failed to create thread")
        raise
    return {"thread_id": thread_id}


@router.get("/threads")
async def list_threads(limit: int = 50):
    """List threads for sidebar. Returns newest first."""
    db_uri = get_db_uri()
    try:
        async with await psycopg.AsyncConnection.connect(db_uri) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT thread_id, created_at, updated_at, metadata "
                    "FROM threads ORDER BY updated_at DESC, created_at DESC LIMIT %s",
                    (limit,),
                )
                rows = await cur.fetchall()
    except Exception:
        logger.exception("Failed to list threads")
        raise
    return [row_to_thread(r) for r in rows]


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str):
    """Get a single thread by id."""
    db_uri = get_db_uri()
    try:
        async with await psycopg.AsyncConnection.connect(db_uri) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT thread_id, created_at, updated_at, metadata "
                    "FROM threads WHERE thread_id = %s",
                    (thread_id,),
                )
                row = await cur.fetchone()
    except Exception:
        logger.exception("Failed to get thread %s", thread_id)
        raise
    if not row:
        raise HTTPException(status_code=404, detail="Thread not found")
    return row_to_thread(row)


@router.patch("/threads/{thread_id}")
async def patch_thread(thread_id: str, body: ThreadPatch):
    db_uri = get_db_uri()
    try:
        async with await psycopg.AsyncConnection.connect(db_uri) as conn:
            if body.metadata is not None:
                await conn.execute(
                    "UPDATE threads "
                    "SET metadata = metadata || %s::jsonb, updated_at = NOW() "
                    "WHERE thread_id = %s",
                    (json.dumps(body.metadata), thread_id),
                )
            await conn.commit()
    except Exception:
        logger.exception("Failed to patch thread %s", thread_id)
        raise
    return {"ok": True}


@router.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str):
    """Delete a thread and all its checkpoints/writes/blobs from Postgres."""
    db_uri = get_db_uri()
    try:
        async with await psycopg.AsyncConnection.connect(db_uri) as conn:
            await conn.execute(
                "DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,)
            )
            await conn.execute(
                "DELETE FROM checkpoint_blobs WHERE thread_id = %s", (thread_id,)
            )
            await conn.execute(
                "DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,)
            )
            await conn.execute(
                "DELETE FROM threads WHERE thread_id = %s", (thread_id,)
            )
            await conn.commit()
    except Exception:
        logger.exception("Failed to delete thread %s", thread_id)
        raise
    return {"ok": True}


@router.get("/threads/{thread_id}/state")
async def get_thread_state(thread_id: str):
    assert state.graph is not None
    config = {"configurable": {"thread_id": thread_id}}
    try:
        thread_state = await state.graph.aget_state(config)
        if thread_state and thread_state.values and "messages" in thread_state.values:
            return {
                "messages": [
                    serialize_message(m) for m in thread_state.values["messages"]
                ]
            }
    except Exception:
        logger.exception("Failed to load thread state for %s", thread_id)
    return {"messages": []}


@router.get("/threads/{thread_id}/graph")
def get_thread_graph(thread_id: str):
    """Return the Neo4j subgraph for a thread (nodes + edges)."""
    if state.graph_db is None:
        raise HTTPException(status_code=503, detail="Graph DB not initialised")

    rows = state.graph_db.query(
        """
        MATCH (thread:Thread {thread_id: $thread_id})
        OPTIONAL MATCH (session:Session)-[:HAS_THREAD]->(thread)
        WITH thread, session
        MATCH (thread)-[*0..5]-(n)
        WHERE n = session
           OR n = thread
           OR n.thread_id = $thread_id
        WITH DISTINCT n
        RETURN
            elementId(n) AS eid,
            labels(n) AS labels,
            properties(n) AS props
        """,
        {"thread_id": thread_id},
    )

    node_map: dict = {}
    for row in rows:
        eid = row.get("eid") or ""
        props = row.get("props") or {}
        labels = row.get("labels") or []
        label = labels[0] if labels else "Node"
        node_map[eid] = {"id": eid, "label": label, **props}

    edges_raw = state.graph_db.query(
        """
        MATCH (thread:Thread {thread_id: $thread_id})
        OPTIONAL MATCH (session:Session)-[:HAS_THREAD]->(thread)
        WITH thread, session
        MATCH (thread)-[*0..5]-(n)
        WHERE n = session OR n = thread OR n.thread_id = $thread_id
        WITH collect(DISTINCT n) AS ns
        UNWIND ns AS a
        MATCH (a)-[r]->(b)
        WHERE b IN ns
        RETURN
            elementId(r) AS reid,
            type(r) AS rtype,
            properties(r) AS props,
            elementId(a) AS from_eid,
            elementId(b) AS to_eid
        """,
        {"thread_id": thread_id},
    )

    edges = []
    seen_reids: set = set()
    for i, row in enumerate(edges_raw):
        reid = row.get("reid") or str(i)
        if reid in seen_reids:
            continue
        seen_reids.add(reid)
        props = row.get("props") or {}
        from_eid = row.get("from_eid") or ""
        to_eid = row.get("to_eid") or ""
        from_node = node_map.get(from_eid)
        to_node = node_map.get(to_eid)
        if not from_node or not to_node:
            continue
        edge_id = props.get("edge_id") or f"{reid}"
        edges.append(
            {
                "id": str(edge_id),
                "from": from_eid,
                "to": to_eid,
                "type": row.get("rtype"),
                **props,
            }
        )

    return {"nodes": list(node_map.values()), "edges": edges}
