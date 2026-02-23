"""LangSmith → Neo4j + Redis ingestion logic.

Extracted from scripts/ingest_threads.py so the same functionality can be
served via the FastAPI endpoint in main.py as well as run from the CLI.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict

from src.langsmith_client import get_langsmith_client

logger = logging.getLogger(__name__)


def list_thread_ids(project_name: str | None = None) -> list[str]:
    """Return all unique thread_ids seen in LangSmith runs."""
    client = get_langsmith_client()
    kwargs: dict = {"is_root": True}
    if project_name:
        kwargs["project_name"] = project_name
    thread_ids: set[str] = set()
    try:
        for run in client.list_runs(**kwargs):
            tid = None
            metadata = getattr(run, "extra", {}) or {}
            if isinstance(metadata, dict):
                tid = metadata.get("metadata", {}).get("thread_id")
            if not tid:
                tid = getattr(run, "session_id", None) or str(getattr(run, "id", ""))
            if tid:
                thread_ids.add(str(tid))
    except Exception as e:
        logger.exception(f"Failed to list runs from LangSmith: {e}")
        raise
    return list(thread_ids)


def fetch_runs_for_thread(
    thread_id: str, project_name: str | None = None
) -> list[dict]:
    """Fetch all runs for a thread_id and return as plain dicts."""
    client = get_langsmith_client()
    kwargs: dict = {"filter": f'eq(thread_id, "{thread_id}")'}
    if project_name:
        kwargs["project_name"] = project_name
    runs: list[dict] = []
    try:
        for run in client.list_runs(**kwargs):
            runs.append(dict(run.__dict__) if hasattr(run, "__dict__") else dict(run))
    except Exception:
        logger.exception("Failed to fetch runs for thread_id=%s", thread_id)
        raise
    return runs


def group_runs_by_trace(run_dicts: list[dict]) -> dict[str, list[dict]]:
    """Group run dicts by their root trace_id (= trace_id or id if parent is None)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in run_dicts:
        trace_id = str(r.get("trace_id") or r.get("id") or "")
        if trace_id:
            groups[trace_id].append(r)
    return dict(groups)


def ingest_thread(
    thread_id: str,
    run_dicts: list[dict],
    db,
    payload_store,
) -> list | None:
    """Build a Thread graph from run dicts and persist to Neo4j + Redis.

    Returns the list of Turn objects on success so callers (e.g. sentinel)
    can reuse them without re-fetching. Returns None on failure.
    """
    from src.graph.loaders import load_turn_from_runs
    from src.graph.thread import Thread

    if not run_dicts:
        logger.warning("No runs found for thread_id=%s — skipping.", thread_id)
        return None

    try:
        trace_groups = group_runs_by_trace(run_dicts)
        turns = [
            load_turn_from_runs(trace_runs, turn_index=i)
            for i, trace_runs in enumerate(trace_groups.values())
        ]
        thread = Thread.from_turns(thread_id, turns)
        thread.save_to_graph_db(db, payload_store=payload_store)
        logger.info(
            "Ingested thread_id=%s  turns=%d  nodes=%d  edges=%d",
            thread_id,
            len(turns),
            thread.G.number_of_nodes(),
            thread.G.number_of_edges(),
        )
        return turns
    except Exception:
        logger.exception("Failed to ingest thread_id=%s", thread_id)
        return None


def run_ingestion(
    db,
    payload_store,
    *,
    thread_ids: list[str] | None = None,
    project: str | None = None,
    clear: bool = False,
) -> dict:
    """Orchestrate a full ingest run.

    Args:
        db: GraphDB instance.
        payload_store: PayloadStore instance.
        thread_ids: Explicit list of thread IDs to ingest. If None or empty,
            all threads are fetched from LangSmith.
        project: LangSmith project name filter (falls back to LANGSMITH_PROJECT env var).
        clear: If True, wipe Neo4j and Redis before ingesting.

    Returns:
        {"succeeded": int, "failed": int, "thread_ids": list[str]}
    """
    resolved_project = project or os.environ.get("LANGSMITH_PROJECT")

    if not thread_ids:
        logger.info(
            "Fetching all thread IDs from LangSmith (project=%s) …",
            resolved_project or "default",
        )
        thread_ids = list_thread_ids(project_name=resolved_project)
        logger.info("Found %d thread(s).", len(thread_ids))

    if not thread_ids:
        logger.warning("No threads to ingest.")
        return {"succeeded": 0, "failed": 0, "thread_ids": []}

    ok = failed = 0
    for tid in thread_ids:
        logger.info("Fetching runs for thread_id=%s …", tid)
        run_dicts = fetch_runs_for_thread(tid, project_name=resolved_project)
        success = ingest_thread(tid, run_dicts, db, payload_store)
        if success:
            ok += 1
        else:
            failed += 1

    logger.info("Ingest done — %d succeeded, %d failed.", ok, failed)
    return {"succeeded": ok, "failed": failed, "thread_ids": thread_ids}
