"""Auto-ingest helper: fetch LangSmith runs and persist to Neo4j + Redis."""

from __future__ import annotations

import logging
import os
import time

from src import state

logger = logging.getLogger(__name__)


def clear_neo4j(db) -> None:
    """Delete all nodes and relationships from Neo4j."""
    logger.info("Clearing Neo4j — deleting all nodes and relationships …")
    db.create("MATCH (n) DETACH DELETE n")
    logger.info("Neo4j cleared.")


def clear_redis(payload_store) -> None:
    """Delete all run:* keys from Redis."""
    logger.info("Clearing Redis payload store …")
    deleted = payload_store.clear()
    logger.info("Redis cleared — %s key(s) deleted.", deleted)


def _collect_run_ids_for_thread(db, thread_id: str) -> list[str]:
    """Collect all run_ids stored in Neo4j for a thread (Chain nodes + edge props)."""
    run_ids: set[str] = set()
    # Chain nodes
    rows = db.query(
        "MATCH (n:Chain {thread_id: $thread_id}) WHERE n.run_id IS NOT NULL RETURN n.run_id AS run_id",
        {"thread_id": thread_id},
    )
    for row in rows:
        rid = row.get("run_id")
        if rid:
            run_ids.add(rid)
    # Edge source/target run_ids (nodes are same thread)
    edge_rows = db.query(
        """
        MATCH (a {thread_id: $thread_id})-[r:ROUTES_TO|CALLS_TOOL]->(b {thread_id: $thread_id})
        RETURN r.source_run_id AS src, r.target_run_id AS tgt
        """,
        {"thread_id": thread_id},
    )
    for row in edge_rows:
        for key in ("src", "tgt"):
            rid = row.get(key)
            if rid:
                run_ids.add(rid)
    return list(run_ids)


def clear_thread_neo4j(db, thread_id: str) -> None:
    """Delete only nodes and relationships belonging to the given thread."""
    logger.info("Clearing Neo4j for thread %s …", thread_id[:16])
    db.create(
        "MATCH (n) WHERE n.thread_id = $thread_id DETACH DELETE n",
        parameters={"thread_id": thread_id},
    )
    db.create(
        "MATCH (s:Session) WHERE NOT (s)-[:HAS_THREAD]->() DELETE s"
    )
    logger.info("Neo4j thread %s cleared.", thread_id[:16])


def clear_thread_redis(payload_store, run_ids: list[str]) -> None:
    """Delete specific run:* keys from Redis."""
    if not run_ids:
        return
    deleted = payload_store.delete_many(run_ids)
    logger.info("Redis thread payloads — %s key(s) deleted.", deleted)


def auto_ingest(
    thread_id: str,
    max_retries: int = 5,
    initial_delay: float = 2.0,
    stabilize_rounds: int = 2,
) -> list | None:
    """Ingest a single thread into Neo4j + Redis without clearing existing data.

    Waits for the LangSmith run count to stabilize (same count over
    ``stabilize_rounds`` consecutive fetches) before building the graph,
    so that late-indexed runs (e.g. code_executor) are not dropped.

    Returns the list of Turn objects on success (so sentinel can reuse them),
    or None on failure.
    """
    if state.graph_db is None or state.payload_store is None:
        return None

    from src.services.ingestion import fetch_runs_for_thread, ingest_thread

    project = os.getenv("LANGSMITH_PROJECT")

    time.sleep(initial_delay)

    run_dicts: list[dict] = []
    prev_count = 0
    stable = 0
    for attempt in range(max_retries):
        if attempt > 0:
            time.sleep(min(2**attempt, 8))
        run_dicts = fetch_runs_for_thread(thread_id, project_name=project)
        cur_count = len(run_dicts)
        if cur_count == 0:
            logger.info(
                "Auto-ingest attempt %d/%d for thread %s: no runs yet, retrying…",
                attempt + 1,
                max_retries,
                thread_id,
            )
            stable = 0
        elif cur_count == prev_count:
            stable += 1
            if stable >= stabilize_rounds:
                logger.info(
                    "Auto-ingest for thread %s: run count stabilized at %d",
                    thread_id[:16],
                    cur_count,
                )
                break
        else:
            logger.info(
                "Auto-ingest attempt %d/%d for thread %s: %d runs (was %d), waiting…",
                attempt + 1,
                max_retries,
                thread_id[:16],
                cur_count,
                prev_count,
            )
            stable = 0
        prev_count = cur_count

    if not run_dicts:
        logger.warning(
            "No runs found for thread %s after %d attempts", thread_id, max_retries
        )
        return None

    return ingest_thread(thread_id, run_dicts, state.graph_db, state.payload_store)
