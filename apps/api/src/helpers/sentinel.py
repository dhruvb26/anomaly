"""Sentinel detection helpers: run analysis and persist reports."""

from __future__ import annotations

import src.compat  # noqa: F401 — patches HfFolder before llamafirewall

import dataclasses
import datetime
import json
import logging
import os
from pathlib import Path

from src import state
from src.config import get_db_uri
from src.graph.config import sentinel_config

logger = logging.getLogger(__name__)

_SENTINEL_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sentinel"


def save_sentinel_report(
    thread_id: str,
    report,
    max_tier: int,
    resource_anomalies: list | None = None,
) -> None:
    """Persist a sentinel report to data/sentinel/ and to Postgres."""
    turn_analyses_data = [dataclasses.asdict(ta) for ta in report.turn_analyses]
    recommendations = report.recommendations or []
    summary = report.summary or ""
    resource_anomalies = resource_anomalies or []

    try:
        _SENTINEL_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = _SENTINEL_LOG_DIR / f"{thread_id}_{ts}.json"
        payload = {
            "thread_id": thread_id,
            "timestamp": ts,
            "max_tier": max_tier,
            "summary": summary,
            "recommendations": recommendations,
            "turn_analyses": turn_analyses_data,
            "resource_anomalies": resource_anomalies,
        }
        filename.write_text(json.dumps(payload, indent=2, default=str))
        logger.info("Sentinel report saved -> %s", filename)
    except OSError:
        logger.exception("Failed to save sentinel report for thread %s", thread_id)

    try:
        import psycopg

        with psycopg.connect(get_db_uri()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sentinel_reports (thread_id, max_tier, summary, recommendations, turn_analyses, resource_anomalies)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        thread_id,
                        max_tier,
                        summary,
                        json.dumps(recommendations),
                        json.dumps(turn_analyses_data, default=str),
                        json.dumps(resource_anomalies, default=str),
                    ),
                )
            conn.commit()
        logger.info("Sentinel report saved to Postgres for thread %s", thread_id[:16])
    except Exception:
        logger.exception(
            "Failed to save sentinel report to Postgres for thread %s", thread_id
        )


def run_sentinel(
    thread_id: str,
    turns: list | None = None,
    payload_store=None,
) -> dict | None:
    """Run sentinel detection on a thread. Returns None on failure.

    Args:
        thread_id: Thread identifier.
        turns: Pre-built Turn objects from ingest. When provided, skips
            the redundant LangSmith fetch.
        payload_store: Redis-backed PayloadStore for edge content lookups.
            Falls back to ``state.payload_store`` when not provided.
    """
    from src.graph.behavior_analyzer import BehaviorAnalyzer
    from src.graph.guardian import GuardianClient
    from src.graph.llamafirewall_client import LlamaFirewallClient

    cfg = sentinel_config
    payload_store = payload_store or state.payload_store

    try:
        if turns is None:
            from src.graph.loaders import load_turn_from_runs
            from src.services.ingestion import fetch_runs_for_thread, group_runs_by_trace

            project = os.getenv("LANGSMITH_PROJECT")
            run_dicts = fetch_runs_for_thread(thread_id, project_name=project)
            if not run_dicts:
                return None

            trace_groups = group_runs_by_trace(run_dicts)
            if not trace_groups:
                return None

            turns = [
                load_turn_from_runs(runs, turn_index=i)
                for i, runs in enumerate(trace_groups.values())
            ]

        guardian = GuardianClient() if cfg.guardian.enabled else None
        firewall = LlamaFirewallClient() if cfg.firewall.enabled else None

        if guardian is None:
            logger.warning("Guardian disabled via config -- skipping sentinel analysis")
            return None

        analyzer = BehaviorAnalyzer(
            guardian=guardian,
            llamafirewall=firewall,
            payload_store=payload_store,
        )
        report = analyzer.analyze_thread(turns, thread_id=thread_id)
        max_tier = max((ta.tier for ta in report.turn_analyses), default=0)

        resource_anomalies: list = []
        if state.graph_db is not None and cfg.resource_baselines.enabled:
            from src.graph.resource_baselines import check_resource_anomalies
            resource_anomalies = check_resource_anomalies(
                state.graph_db,
                thread_id,
                z_threshold=cfg.resource_baselines.z_threshold,
                min_samples=cfg.resource_baselines.min_samples,
            )

        save_sentinel_report(thread_id, report, max_tier, resource_anomalies=resource_anomalies)

        if state.graph_db is not None:
            from src.graph.persistence import write_sentinel_results
            write_sentinel_results(state.graph_db, thread_id, report)

        return {
            "tier": max_tier,
            "summary": report.summary,
            "recommendations": report.recommendations,
            "resource_anomalies": resource_anomalies,
        }
    except Exception:
        logger.exception("Sentinel detection failed for thread %s", thread_id)
        return None
