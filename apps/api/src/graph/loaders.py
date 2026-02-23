"""Load turn/run data from in-memory run dicts (LangSmith); build Turn instances."""

from __future__ import annotations

from src.graph.config import INCLUDE_CHAIN_RUNS
from src.graph.schemas import Node, Turn


def _build_run_map_from_runs(run_dicts: list[dict]) -> tuple[dict[str, dict], str | None]:
    """Build run_map and identify root chain from a list of run dicts.

    Returns:
        (run_map, root_id) where run_map maps run_id to entry dict.
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
    """Extract chain routings (goto / source_agent) from chain-type runs, sorted by start_time."""
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
        routings.append(
            {
                "goto": goto,
                "source_agent": source_agent,
                "start_time": str(d.get("start_time") or ""),
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
    """Walk parent_run_id upward to find the agent-subgraph chain that owns this run.

    Returns the owning chain's run_id, or the original run_id if not resolvable.
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
    """Build a Turn from a list of LangSmith run dicts."""
    run_map, root_id = _build_run_map_from_runs(run_dicts)

    nodes: list[Node] = []
    chain_runs: list[dict] = []
    for entry in run_map.values():
        rt = entry["run_type"]
        if rt in Node.SUPPORTED_TYPES:
            try:
                nodes.append(Node.from_dict(entry["data"]))
            except (ValueError, KeyError):
                pass
        elif rt == "chain" and INCLUDE_CHAIN_RUNS:
            chain_runs.append(entry["data"])

    nodes.sort(key=lambda n: n.start_time or "")
    chain_runs.sort(key=lambda x: str(x.get("start_time") or ""))

    start_time = ""
    end_time = ""
    if nodes:
        for e in nodes[0].events or []:
            if isinstance(e, dict) and e.get("name") == "start" and "time" in e:
                start_time = e["time"]
                break
        for e in reversed(nodes[-1].events or []):
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
