"""Sentinel detection helpers: run analysis and persist reports."""

from __future__ import annotations

import src.compat  # noqa: F401 — patches HfFolder before llamafirewall is imported

import json
import logging
import os
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

_SENTINEL_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sentinel"


def save_sentinel_report(thread_id: str, report, max_tier: int) -> None:
    """Persist a sentinel report to data/sentinel/<thread_id>_<timestamp>.json."""
    import dataclasses
    import datetime

    try:
        _SENTINEL_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = _SENTINEL_LOG_DIR / f"{thread_id}_{ts}.json"

        payload = {
            "thread_id": thread_id,
            "timestamp": ts,
            "max_tier": max_tier,
            "summary": report.summary,
            "recommendations": report.recommendations,
            "turn_analyses": [dataclasses.asdict(ta) for ta in report.turn_analyses],
        }

        filename.write_text(json.dumps(payload, indent=2, default=str))
        logger.info("Sentinel report saved → %s", filename)
    except Exception:
        logger.exception("Failed to save sentinel report for thread %s", thread_id)


def run_sentinel(thread_id: str) -> dict | None:
    """Run sentinel detection on a thread. Never raises — returns None on failure."""
    from src.graph.behavior_analyzer import BehaviorAnalyzer
    from src.graph.guardian import GuardianClient
    from src.graph.llamafirewall_client import LlamaFirewallClient
    from src.graph.loaders import load_turn_from_runs
    from src.services.ingestion import fetch_runs_for_thread, get_langsmith_client

    try:
        client = get_langsmith_client()
        project = os.getenv("LANGSMITH_PROJECT")
        run_dicts = fetch_runs_for_thread(client, thread_id, project_name=project)
        if not run_dicts:
            return None

        groups: dict = defaultdict(list)
        for r in run_dicts:
            trace_id = str(r.get("trace_id") or r.get("id") or "")
            if trace_id:
                groups[trace_id].append(r)
        if not groups:
            return None

        turns = [
            load_turn_from_runs(runs, turn_index=i)
            for i, runs in enumerate(groups.values())
        ]

        guardian = GuardianClient()
        firewall = LlamaFirewallClient()
        analyzer = BehaviorAnalyzer(guardian=guardian, llamafirewall=firewall)
        report = analyzer.analyze_thread(turns, thread_id=thread_id)
        max_tier = max((ta.tier for ta in report.turn_analyses), default=0)
        save_sentinel_report(thread_id, report, max_tier)

        return {
            "tier": max_tier,
            "summary": report.summary,
            "recommendations": report.recommendations,
        }
    except Exception:
        logger.exception("Sentinel detection failed for thread %s", thread_id)
        return None
