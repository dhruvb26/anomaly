"""Load turn/run data from in-memory run dicts (LangSmith); build Turn instances."""

from __future__ import annotations

import logging

from src.graph.config import INCLUDE_CHAIN_RUNS
from src.graph.schemas import Node, Turn

logger = logging.getLogger(__name__)


def _parse_iso_time(ts: str | None) -> str:
    """Return ts as-is for sorting; empty string if None."""
    return ts or ""


def _build_run_map_from_runs(run_dicts: list[dict]) -> tuple[dict[str, dict], str | None]:
    """
    Build run_map and root_id from a list of run dicts (e.g. from LangSmith).
    run_map: {run_id: {"parent_run_id", "run_type", "start_time", "status", "data"}}
    root_id: run_id of the root chain (parent_run_id is None and run_type == "chain").
    """
    run_map: dict[str, dict] = {}
    root_id: str | None = None
    for d in run_dicts:
        run_id = str(d.get("id") or "")
        if not run_id:
            continue
        parent_raw = d.get("parent_run_id")
        parent_id = str(parent_raw) if parent_raw is not None else None
        run_type = d.get("run_type", "")
        run_map[run_id] = {
            "parent_run_id": parent_id,
            "run_type": run_type,
            "start_time": str(d.get("start_time") or ""),
            "status": d.get("status"),
            "data": d,
        }
        if parent_id is None and run_type == "chain":
            root_id = run_id
    return run_map, root_id


def _extract_chain_routings_from_runs(
    run_dicts: list[dict], turn_index: int
) -> list[dict]:
    """
    Extract chain routings from run dicts (same logic as disk-based variant).
    Collects chain runs containing outputs.output.goto and returns them sorted by start_time.
    """
    routings: list[dict] = []
    for d in run_dicts:
        if d.get("run_type") != "chain":
            continue
        outputs = d.get("outputs") or {}
        output = outputs.get("output")
        if not isinstance(output, dict):
            continue
        goto = output.get("goto")
        if not goto:
            continue
        source_agent = "orchestrator"
        update_msgs = (output.get("update") or {}).get("messages") or []
        for m in reversed(update_msgs):
            if isinstance(m, dict) and m.get("type") == "ai" and m.get("name"):
                source_agent = m["name"]
                break
        ts = str(d.get("start_time") or "")
        routings.append(
            {
                "goto": goto,
                "source_agent": source_agent,
                "start_time": ts,
                "chain_id": str(d.get("id") or ""),
                "turn_index": turn_index,
            }
        )
    routings.sort(key=lambda r: r["start_time"])
    return routings


def resolve_delegation_chain_id(
    run_id: str,
    run_map: dict[str, dict],
    root_id: str | None,
) -> str:
    """
    Walk parent_run_id upward from run_id until we find the run whose parent
    is the root turn chain — i.e. the agent-subgraph chain that directly owns
    this invocation.  Returns that chain's run_id, or the original run_id as
    a fallback.
    """
    current = run_id
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        entry = run_map.get(current)
        if entry is None:
            break
        parent = entry.get("parent_run_id")
        if parent == root_id:
            return current
        if parent is None:
            break
        current = parent
    return run_id


def load_turn_from_runs(run_dicts: list[dict], turn_index: int) -> Turn:
    """Build a Turn from a list of run dicts (e.g. from LangSmith). No disk I/O."""
    run_map, root_id = _build_run_map_from_runs(run_dicts)

    nodes: list[Node] = []
    chain_runs: list[dict] = []
    for run_id, entry in run_map.items():
        rt = entry["run_type"]
        if rt in Node.SUPPORTED_TYPES:
            try:
                nodes.append(Node.from_dict(entry["data"]))
            except (ValueError, KeyError):
                pass
        elif rt == "chain" and INCLUDE_CHAIN_RUNS:
            chain_runs.append(entry["data"])

    nodes.sort(key=lambda n: _parse_iso_time(getattr(n, "start_time", None)))
    chain_runs.sort(key=lambda x: str(x.get("start_time") or ""))

    start_time = ""
    end_time = ""
    if nodes:
        first_events = getattr(nodes[0], "events", None) or []
        for e in first_events:
            if isinstance(e, dict) and e.get("name") == "start" and "time" in e:
                start_time = e["time"]
                break
        last_events = getattr(nodes[-1], "events", None) or []
        for e in reversed(last_events):
            if isinstance(e, dict) and e.get("name") == "end" and "time" in e:
                end_time = e["time"]
                break

    chain_routings = _extract_chain_routings_from_runs(run_dicts, turn_index)

    trace_id = ""
    root_chain_id = root_id or ""
    if root_id and root_id in run_map:
        root_data = run_map[root_id].get("data") or {}
        trace_id = str(root_data.get("trace_id") or root_id)
        root_chain_id = str(root_data.get("id") or root_id)

    return Turn(
        index=turn_index,
        nodes=nodes,
        start_time=start_time,
        end_time=end_time,
        chain_routings=chain_routings,
        run_map=run_map,
        root_id=root_id,
        chain_runs=chain_runs,
        trace_id=trace_id,
        root_chain_id=root_chain_id,
    )
