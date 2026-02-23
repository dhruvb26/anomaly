"""Build the in-memory NetworkX graph from Turn instances."""

from __future__ import annotations

import networkx as nx

from src.graph.config import INCLUDE_CHAIN_RUNS
from src.graph.inference import (
    compute_run_metadata,
    infer_edges_named,
    is_boundary_key,
    make_edge_id,
    node_key,
    step_label_str,
)
from src.graph.loaders import resolve_delegation_chain_id
from src.graph.schemas import Turn


def _session_node_key(session_id: str) -> str:
    return f"__session__:{session_id or 'default'}"


def _thread_node_key(thread_id: str) -> str:
    return f"__thread__:{thread_id}"


def _trace_node_key(trace_id: str) -> str:
    return f"__trace__:{trace_id}"


def _resolve_session_id(turns: list[Turn]) -> str:
    """Extract session_id from the first turn's root chain or first node."""
    if not turns:
        return ""
    turn = turns[0]
    if turn.root_id and turn.root_id in turn.run_map:
        root_data = turn.run_map[turn.root_id].get("data") or {}
        sid = root_data.get("session_id")
        if sid:
            return str(sid)
    if turn.nodes:
        return turn.nodes[0].session_id or ""
    return ""


def _add_hierarchy_nodes(
    G: nx.MultiDiGraph,
    thread_id: str,
    session_id: str,
    turns: list[Turn],
) -> dict[str, set[str]]:
    """Add Session, Thread, Trace, and boundary nodes. Returns trace_covers map."""
    session_key = _session_node_key(session_id)
    G.add_node(session_key, type="session", session_id=session_id or "default")

    thread_key = _thread_node_key(thread_id)
    G.add_node(
        thread_key,
        type="thread",
        thread_id=thread_id,
        session_id=session_id or "default",
        turn_count=len(turns),
    )
    G.add_edge(
        session_key, thread_key,
        type="has_thread", payload={"target": thread_id},
    )

    for boundary in ("__start__", "__end__"):
        G.add_node(boundary, type="boundary", invocations=[])

    trace_covers: dict[str, set[str]] = {}
    for turn in turns:
        trace_id = turn.trace_id or turn.root_chain_id or f"turn_{turn.index}"
        trace_key = _trace_node_key(trace_id)
        if trace_key not in G:
            _add_trace_node(G, trace_key, trace_id, thread_key, turn)
        trace_covers[trace_id] = set()

    return trace_covers


def _add_trace_node(
    G: nx.MultiDiGraph,
    trace_key: str,
    trace_id: str,
    thread_key: str,
    turn: Turn,
) -> None:
    """Add a Trace container node and HAS_TRACE edge."""
    total_cost = 0.0
    total_tokens = prompt_tokens = completion_tokens = 0
    status = ""
    if turn.root_id and turn.root_id in turn.run_map:
        root_data = turn.run_map[turn.root_id].get("data") or {}
        total_cost = float(root_data.get("total_cost") or 0)
        total_tokens = int(root_data.get("total_tokens") or 0)
        prompt_tokens = int(root_data.get("prompt_tokens") or 0)
        completion_tokens = int(root_data.get("completion_tokens") or 0)
        status = str(root_data.get("status") or "")

    G.add_node(
        trace_key,
        type="trace",
        trace_id=trace_id,
        turn=turn.index,
        start_time=turn.start_time,
        end_time=turn.end_time,
        total_cost=total_cost,
        total_tokens=total_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        status=status,
    )
    G.add_edge(
        thread_key, trace_key,
        type="has_trace",
        payload={"target": trace_id},
        turn=turn.index,
        step_label=f"T{turn.index}",
        start_time=turn.start_time,
    )


def _add_chain_nodes(G: nx.MultiDiGraph, turn: Turn, thread_id: str, trace_key: str) -> None:
    """Add chain-type run nodes and contains edges (only when INCLUDE_CHAIN_RUNS is True)."""
    for cd in turn.chain_runs:
        chain_id = str(cd.get("id") or "")
        if not chain_id or chain_id in G:
            continue
        G.add_node(
            chain_id,
            type="chain",
            run_id=chain_id,
            parent_run_id=str(cd.get("parent_run_id") or ""),
            start_time=str(cd.get("start_time") or ""),
            status=cd.get("status"),
            thread_id=thread_id,
        )

    for run_id, entry in turn.run_map.items():
        parent = entry.get("parent_run_id")
        if parent and parent in G and run_id in G:
            G.add_edge(
                parent, run_id,
                type="contains",
                payload={"target": run_id},
                turn=turn.index,
                step_label="",
                start_time=entry.get("start_time", ""),
            )

    if turn.root_id and turn.root_id in G:
        G.add_edge(
            trace_key, turn.root_id,
            type="contains",
            payload={"target": turn.root_id},
            turn=turn.index,
            step_label="",
            start_time=turn.start_time,
        )


def _add_invocation_nodes(
    G: nx.MultiDiGraph,
    turn: Turn,
    thread_id: str,
    nodes_covered: set[str],
) -> None:
    """Add LLM/Tool nodes with invocation metadata."""
    for step, node in enumerate(turn.nodes):
        key = node_key(node)
        nodes_covered.add(key)
        if key not in G:
            G.add_node(key, type=node.type, invocations=[])

        run_id = node.id or ""
        raw_parent = node.parent_run_id or ""

        if INCLUDE_CHAIN_RUNS:
            parent_ref_key = "parent_run_id"
            parent_ref_val = raw_parent
            if raw_parent and raw_parent in G:
                G.add_edge(
                    raw_parent, key,
                    type="contains",
                    payload={"target": key},
                    turn=turn.index,
                    step_label="",
                    start_time=node.start_time or "",
                )
        else:
            parent_ref_key = "delegation_chain_id"
            parent_ref_val = resolve_delegation_chain_id(
                run_id, turn.run_map, turn.root_id
            )

        run_meta = compute_run_metadata(node)
        G.nodes[key]["invocations"].append({
            "turn": turn.index,
            "step_label": step_label_str(turn.index, step),
            "run_id": run_id,
            "start_time": node.start_time or "",
            "status": node.status,
            "error": node.error,
            "session_id": node.session_id or "",
            "trace_id": node.trace_id or "",
            parent_ref_key: parent_ref_val,
            "prompt_tokens": node.prompt_tokens or 0,
            "completion_tokens": node.completion_tokens or 0,
            "total_tokens": node.total_tokens or 0,
            "prompt_cost": float(node.prompt_cost or 0),
            "completion_cost": float(node.completion_cost or 0),
            "total_cost": float(node.total_cost or 0),
            "inputs_hash": run_meta.inputs_hash,
            "outputs_hash": run_meta.outputs_hash,
            "inputs_len": run_meta.inputs_len,
            "outputs_len": run_meta.outputs_len,
        })


def _add_edges(
    G: nx.MultiDiGraph,
    turn: Turn,
    trace_id: str,
    nodes_covered: set[str],
) -> None:
    """Add inferred routing/tool_call edges plus __start__ and __end__ edges."""
    max_seq = 0
    for src, tgt, attrs in infer_edges_named(turn, trace_id=trace_id):
        nodes_covered.add(src)
        nodes_covered.add(tgt)
        for key in (src, tgt):
            if key not in G and is_boundary_key(key):
                G.add_node(key, type="boundary", invocations=[])
        if src in G and tgt in G:
            attrs["seq_no"] = attrs.get("seq_no", 0) + 1
            max_seq = max(max_seq, attrs["seq_no"])
            G.add_edge(src, tgt, **attrs)

    # __start__ -> first agent
    if turn.nodes:
        first_node = turn.nodes[0]
        first_key = node_key(first_node)
        nodes_covered.update({"__start__", first_key})
        step_lbl = f"T{turn.index}.start"
        G.add_edge(
            "__start__", first_key,
            type="routing",
            payload={"target": first_key},
            turn=turn.index,
            step_label=step_lbl,
            start_time=first_node.start_time or "",
            seq_no=0,
            edge_id=make_edge_id(trace_id, step_lbl, "__start__", first_key, "routing"),
            source_run_id=None,
            target_run_id=first_node.id or None,
        )

    # source_agent -> __end__
    end_seq = max_seq + 1
    for routing in turn.chain_routings:
        if routing["goto"] != "__end__":
            continue
        src = routing["source_agent"]
        nodes_covered.update({"__end__", src})
        if src not in G:
            G.add_node(src, type="llm", invocations=[])
        step_lbl = f"T{routing['turn_index']}.end"
        G.add_edge(
            src, "__end__",
            type="routing",
            payload={"target": "__end__"},
            turn=routing["turn_index"],
            step_label=step_lbl,
            start_time=routing["start_time"],
            seq_no=end_seq,
            edge_id=make_edge_id(trace_id, step_lbl, src, "__end__", "routing"),
            source_run_id=None,
            target_run_id=None,
        )
        end_seq += 1


def build_graph_from_turns(
    thread_id: str, turns: list[Turn]
) -> tuple[nx.MultiDiGraph, str, dict[str, set[str]]]:
    """Build the full in-memory graph from Turn instances.

    Returns:
        (graph, session_id, trace_covers)
    """
    G: nx.MultiDiGraph = nx.MultiDiGraph()
    session_id = _resolve_session_id(turns)
    trace_covers = _add_hierarchy_nodes(G, thread_id, session_id, turns)

    for turn in turns:
        trace_id = turn.trace_id or turn.root_chain_id or f"turn_{turn.index}"
        trace_key = _trace_node_key(trace_id)
        nodes_covered = trace_covers[trace_id]

        if INCLUDE_CHAIN_RUNS:
            _add_chain_nodes(G, turn, thread_id, trace_key)

        _add_invocation_nodes(G, turn, thread_id, nodes_covered)
        _add_edges(G, turn, trace_id, nodes_covered)

    return G, session_id, trace_covers
