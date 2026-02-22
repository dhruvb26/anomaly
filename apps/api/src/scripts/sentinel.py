#!/usr/bin/env python3
"""Sentinel: fetch a LangSmith thread, build the graph, and run full detection.

Runs BehaviorAnalyzer (Guardian + LlamaFirewall + attack path matching) on one
or more threads and prints a structured report.

Usage (from apps/api/):
    # Analyze a specific thread
    uv run python -m src.scripts.sentinel <thread_id>

    # Analyze multiple threads
    uv run python -m src.scripts.sentinel <thread_id1> <thread_id2>

    # Also persist results to Neo4j + Redis after detection
    uv run python -m src.scripts.sentinel <thread_id> --persist

    # Skip Guardian (useful if Ollama is not running)
    uv run python -m src.scripts.sentinel <thread_id> --no-guardian

    # Skip LlamaFirewall
    uv run python -m src.scripts.sentinel <thread_id> --no-firewall
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

# graph/ and stores/ use bare imports; src/ must be on sys.path.
_src = Path(__file__).resolve().parent.parent
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

# Patch HfFolder before llamafirewall is imported anywhere (huggingface_hub >= 1.0 removed it).
try:
    import src.compat  # noqa: F401 — works when running via `python -m src.scripts.sentinel`
except ModuleNotFoundError:
    import compat  # noqa: F401 — works when src/ is directly on sys.path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Surface logs from the ML/HF libraries so model loading and inference are visible.
# These are kept at WARNING by default to avoid noise; --verbose promotes them to INFO/DEBUG.
_LIBRARY_LOGGERS = [
    "transformers",
    "huggingface_hub",
    "llamafirewall",
    "tokenizers",
]

def _fetch_runs_for_thread(client, thread_id: str, project_name: str | None = None) -> list[dict]:
    kwargs: dict = {"filter": f'eq(thread_id, "{thread_id}")'}
    if project_name:
        kwargs["project_name"] = project_name
    runs: list[dict] = []
    for run in client.list_runs(**kwargs):
        runs.append(dict(run.__dict__) if hasattr(run, "__dict__") else dict(run))
    return runs


def _group_runs_by_trace(run_dicts: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in run_dicts:
        trace_id = str(r.get("trace_id") or r.get("id") or "")
        if trace_id:
            groups[trace_id].append(r)
    return dict(groups)


def _build_thread(thread_id: str, run_dicts: list[dict]):
    from graph.loaders import load_turn_from_runs
    from graph.thread import Thread

    trace_groups = _group_runs_by_trace(run_dicts)
    if not trace_groups:
        logger.warning("No trace groups found for thread_id=%s", thread_id)
        return None

    turns = [
        load_turn_from_runs(trace_runs, turn_index=i)
        for i, trace_runs in enumerate(trace_groups.values())
    ]
    return Thread.from_turns(thread_id, turns), turns


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

_TIER_LABEL = {0: "CLEAN", 1: "GLOBAL ANOMALY", 2: "ANOMALY", 3: "ATTACK PATH MATCHED"}
_TIER_COLOUR = {0: "\033[32m", 1: "\033[33m", 2: "\033[33m", 3: "\033[31m"}
_RESET = "\033[0m"


def _tier_str(tier: int) -> str:
    colour = _TIER_COLOUR.get(tier, "")
    label = _TIER_LABEL.get(tier, str(tier))
    return f"{colour}[{label}]{_RESET}"


def _print_report(report) -> None:
    print()
    print("=" * 70)
    print(f"  SENTINEL REPORT  —  thread_id: {report.thread_id}")
    print("=" * 70)
    print(f"  Summary : {report.summary}")
    if report.recommendations:
        for r in report.recommendations:
            print(f"  → {r}")
    print()

    for ta in report.turn_analyses:
        print(f"  Turn {ta.turn_index}  {_tier_str(ta.tier)}")

        if ta.path_matches:
            for pm in ta.path_matches:
                print(
                    f"    ⚑ Attack path matched: {pm.attack_path.name}"
                    f"  (tier {pm.attack_path.risk_tier})"
                )
                print(f"      {pm.attack_path.description}")
                print(f"      Sequence: {' → '.join(pm.matched_subsequence)}")

        anomalous_nodes = [ns for ns in ta.node_statuses if ns.is_anomalous]
        if anomalous_nodes:
            for ns in anomalous_nodes:
                print(
                    f"    ✗ Node  [{ns.node_key}]  risk={ns.risk_type}"
                    f"  conf={ns.confidence:.2f}  {ns.details}"
                )
        else:
            keys = [ns.node_key for ns in ta.node_statuses]
            if keys:
                print(f"    ✓ Nodes  {keys}  — ok")

        anomalous_edges = [es for es in ta.edge_statuses if es.is_anomalous]
        if anomalous_edges:
            for es in anomalous_edges:
                print(
                    f"    ✗ Edge  {es.src_key} → {es.tgt_key}"
                    f"  risk={es.risk_type}  conf={es.confidence:.2f}  {es.details}"
                )

        print()

    print("=" * 70)
    print()


_SENTINEL_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sentinel"


def _save_report(thread_id: str, report, max_tier: int) -> None:
    """Persist the sentinel report to data/sentinel/<thread_id>_<timestamp>.json."""
    import dataclasses
    import datetime
    import json

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
        logger.info("Report saved → %s", filename)
    except Exception:
        logger.exception("Failed to save sentinel report for thread %s", thread_id)


def run_sentinel(
    thread_id: str,
    project: str | None,
    use_guardian: bool,
    use_firewall: bool,
    persist: bool,
) -> int:
    """Run full detection on one thread. Returns max tier (0-3)."""
    import time

    from langsmith import Client

    # ------------------------------------------------------------------ #
    # Service summary                                                       #
    # ------------------------------------------------------------------ #
    logger.info("━" * 60)
    logger.info("Sentinel — thread_id=%s", thread_id)
    logger.info(
        "Services: Guardian=%s  LlamaFirewall=%s  Persist=%s",
        "enabled" if use_guardian else "DISABLED (--no-guardian)",
        "enabled" if use_firewall else "DISABLED (--no-firewall)",
        persist,
    )
    logger.info("━" * 60)

    # ------------------------------------------------------------------ #
    # Fetch runs from LangSmith                                            #
    # ------------------------------------------------------------------ #
    logger.info("[1/4] Fetching runs from LangSmith  project=%s …", project or "(env)")
    t0 = time.monotonic()
    client = Client()
    run_dicts = _fetch_runs_for_thread(client, thread_id, project_name=project)
    logger.info(
        "[1/4] ✓ Fetched %d run(s) in %.1fs",
        len(run_dicts),
        time.monotonic() - t0,
    )

    if not run_dicts:
        logger.error(
            "No runs found for thread_id=%s. "
            "Check the thread ID and the LangSmith project name.",
            thread_id,
        )
        return 0

    # ------------------------------------------------------------------ #
    # Build thread graph                                                   #
    # ------------------------------------------------------------------ #
    logger.info("[2/4] Building thread graph …")
    t0 = time.monotonic()
    result = _build_thread(thread_id, run_dicts)
    if result is None:
        return 0
    thread, turns = result
    logger.info(
        "[2/4] ✓ Thread built in %.1fs — turns=%d  nodes=%d  edges=%d",
        time.monotonic() - t0,
        len(turns),
        thread.G.number_of_nodes(),
        thread.G.number_of_edges(),
    )

    # ------------------------------------------------------------------ #
    # Initialise detector components                                       #
    # ------------------------------------------------------------------ #
    logger.info("[3/4] Initialising detector components …")
    from graph.behavior_analyzer import BehaviorAnalyzer
    from graph.guardian import GuardianClient
    from graph.llamafirewall_client import LlamaFirewallClient

    if use_guardian:
        guardian = GuardianClient()
    else:
        # Stub that never flags — lets path matching + edge checks still run
        from graph.guardian import GuardianResult
        class _NoopGuardian:
            confidence_threshold = 0.5
            def check_jailbreak(self, _): return GuardianResult(False, 0.0, "", "guardian_disabled")
            def check_function_calling_hallucination(self, *a, **kw): return GuardianResult(False, 0.0, "", "guardian_disabled")
        guardian = _NoopGuardian()
        logger.info("Guardian  DISABLED — using no-op stub")

    if use_firewall:
        firewall = LlamaFirewallClient()
    else:
        firewall = None
        logger.info("LlamaFirewall  DISABLED")

    analyzer = BehaviorAnalyzer(guardian=guardian, llamafirewall=firewall)

    # ------------------------------------------------------------------ #
    # Run detection                                                         #
    # ------------------------------------------------------------------ #
    logger.info("[4/4] Running detection across %d turn(s) …", len(turns))
    t0 = time.monotonic()
    report = analyzer.analyze_thread(turns, thread_id=thread_id)
    logger.info("[4/4] ✓ Detection complete in %.1fs", time.monotonic() - t0)
    _print_report(report)

    max_tier = max((ta.tier for ta in report.turn_analyses), default=0)
    _save_report(thread_id, report, max_tier)

    if persist:
        logger.info("Persisting thread to Neo4j + Redis …")
        from stores.graph_db import GraphDB
        from stores.payload_store import PayloadStore
        db = GraphDB()
        db.verify_connectivity()
        db.setup_schema()
        thread.save_to_graph_db(db, payload_store=PayloadStore())
        db.close()
        logger.info("Persisted.")

    return max_tier


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Sentinel detection on LangSmith threads.")
    parser.add_argument(
        "thread_ids",
        nargs="+",
        metavar="THREAD_ID",
        help="One or more LangSmith thread IDs to analyze.",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Write thread graph to Neo4j + Redis after detection.",
    )
    parser.add_argument(
        "--no-guardian",
        action="store_true",
        help="Disable Granite Guardian checks (useful if Ollama is not running).",
    )
    parser.add_argument(
        "--no-firewall",
        action="store_true",
        help="Disable LlamaFirewall edge checks.",
    )
    parser.add_argument(
        "--project",
        metavar="NAME",
        help="LangSmith project name (defaults to LANGSMITH_PROJECT env var).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "Enable DEBUG logging and surface logs from HuggingFace, transformers, "
            "and llamafirewall so model loading / inference is fully visible."
        ),
    )
    return parser.parse_args()


def main() -> None:
    import os

    args = _parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        for lib in _LIBRARY_LOGGERS:
            logging.getLogger(lib).setLevel(logging.DEBUG)
        logger.debug("Verbose mode ON — DEBUG logs enabled for: %s", _LIBRARY_LOGGERS)
    else:
        # Keep third-party ML library chatter at WARNING to avoid noise
        for lib in _LIBRARY_LOGGERS:
            logging.getLogger(lib).setLevel(logging.WARNING)

    project = args.project or os.environ.get("LANGSMITH_PROJECT")

    overall_max = 0
    for tid in args.thread_ids:
        tier = run_sentinel(
            thread_id=tid,
            project=project,
            use_guardian=not args.no_guardian,
            use_firewall=not args.no_firewall,
            persist=args.persist,
        )
        overall_max = max(overall_max, tier)

    if overall_max >= 3:
        logger.warning("ATTACK PATH DETECTED — tier %d", overall_max)
        sys.exit(2)
    elif overall_max >= 2:
        logger.warning("ANOMALY DETECTED — tier %d", overall_max)
        sys.exit(1)
    else:
        logger.info("No anomaly detected.")
        sys.exit(0)


if __name__ == "__main__":
    main()
