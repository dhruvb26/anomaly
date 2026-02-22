"""Auto-ingest helper: fetch LangSmith runs and persist to Neo4j + Redis."""

from __future__ import annotations

import logging
import os
import time

from src import state

logger = logging.getLogger(__name__)


def auto_ingest(thread_id: str, max_retries: int = 3) -> bool:
    """Ingest a single thread into Neo4j + Redis without clearing existing data.

    Retries with exponential backoff when LangSmith hasn't indexed the runs yet.
    Returns True on success, False on failure.
    """
    if state.graph_db is None or state.payload_store is None:
        return False

    from src.services.ingestion import (
        fetch_runs_for_thread,
        get_langsmith_client,
        ingest_thread,
    )

    client = get_langsmith_client()
    project = os.getenv("LANGSMITH_PROJECT")

    run_dicts: list[dict] = []
    for attempt in range(max_retries):
        if attempt > 0:
            time.sleep(2**attempt)
        run_dicts = fetch_runs_for_thread(client, thread_id, project_name=project)
        if run_dicts:
            break
        logger.info(
            "Auto-ingest attempt %d/%d for thread %s: no runs yet, retrying…",
            attempt + 1,
            max_retries,
            thread_id,
        )

    if not run_dicts:
        logger.warning(
            "No runs found for thread %s after %d attempts", thread_id, max_retries
        )
        return False

    return ingest_thread(thread_id, run_dicts, state.graph_db, state.payload_store)
