#!/usr/bin/env python3
"""Fetch LangSmith threads, build graph objects, and persist to Neo4j + Redis.

Usage (from apps/api/):
    # Ingest all threads
    uv run python -m src.scripts.ingest_threads

    # Ingest specific thread IDs
    uv run python -m src.scripts.ingest_threads <thread_id1> <thread_id2>

    # Clear Neo4j + Redis before ingesting
    uv run python -m src.scripts.ingest_threads --clear

    # Clear only, no ingest
    uv run python -m src.scripts.ingest_threads --clear --no-ingest
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest LangSmith threads into Neo4j + Redis."
    )
    parser.add_argument(
        "thread_ids",
        nargs="*",
        metavar="THREAD_ID",
        help="Thread IDs to ingest. If omitted, all threads from LangSmith are fetched.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Wipe Neo4j (all nodes/edges) and Redis (run:* keys) before ingesting.",
    )
    parser.add_argument(
        "--no-ingest",
        action="store_true",
        help="Only clear (requires --clear); skip the ingest step.",
    )
    parser.add_argument(
        "--project",
        metavar="NAME",
        help="LangSmith project name to filter runs (defaults to LANGSMITH_PROJECT env var).",
    )
    return parser.parse_args()


def main() -> None:
    from src.services.ingestion import clear_neo4j, clear_redis, run_ingestion
    from src.stores.graph_db import GraphDB
    from src.stores.payload_store import PayloadStore

    args = _parse_args()

    db = GraphDB()
    db.verify_connectivity()
    db.setup_schema()
    payload_store = PayloadStore()

    if args.clear and args.no_ingest:
        clear_neo4j(db)
        clear_redis(payload_store)
        logger.info("--no-ingest set — done.")
        db.close()
        return

    project = args.project or os.environ.get("LANGSMITH_PROJECT")
    result = run_ingestion(
        db,
        payload_store,
        thread_ids=args.thread_ids or None,
        project=project,
        clear=args.clear,
    )

    db.close()
    logger.info("Done — %d succeeded, %d failed.", result["succeeded"], result["failed"])
    if result["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
