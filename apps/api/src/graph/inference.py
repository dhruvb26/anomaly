"""Edge inference: derive agent/tool names and routing edges from turn data."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from src.graph.config import AGENT_SYSTEM_PROMPT_HINTS, SUB_AGENTS
from src.graph.schemas import Node, Turn

@dataclass(slots=True)
class RunMetadata:
    """Hashes and lengths of a node's inputs/outputs."""

    inputs_hash: str
    outputs_hash: str
    inputs_len: int
    outputs_len: int


def _agent_name_from_llm_node(node: Node) -> str:
    """Derive agent name from an LLM run's system prompt hints. Falls back to 'llm'."""
    try:
        msgs = (node.inputs or {}).get("messages") or []
        if msgs and isinstance(msgs[0], list):
            msgs = msgs[0]
        for m in msgs:
            kwargs = m.get("kwargs") or m if isinstance(m, dict) else {}
            content = kwargs.get("content") or ""
            if not isinstance(content, str):
                continue
            for hint, name in AGENT_SYSTEM_PROMPT_HINTS:
                if hint in content:
                    return name
    except (IndexError, KeyError, TypeError):
        pass
    return "llm"


def _tool_name_from_node(node: Node) -> str:
    """Get tool name from a tool run's outputs."""
    output = (node.outputs or {}).get("output")
    if isinstance(output, dict) and output.get("name"):
        return str(output["name"])
    return "tool"


def _next_agent_from_llm_outputs(node: Node) -> str:
    """Extract next_agent from OrchestratorDecision tool call, else 'continue'."""
    try:
        gens = (node.outputs or {}).get("generations") or []
        if not gens or not gens[0]:
            return "continue"
        msg = gens[0][0].get("message", {})
        for tc in msg.get("kwargs", {}).get("tool_calls") or []:
            if tc.get("name") == "OrchestratorDecision":
                return tc.get("args", {}).get("next_agent") or "continue"
    except (IndexError, KeyError, TypeError):
        pass
    return "continue"


def node_key(node: Node) -> str:
    """Canonical graph node key: agent name for LLM, tool name for tool."""
    if node.type == "llm":
        return _agent_name_from_llm_node(node)
    return _tool_name_from_node(node)


def step_label_str(turn_index: int, step: int) -> str:
    """Human-readable step label: T2.a, T2.b, ..., T2.aa, etc."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    result = ""
    n = step
    while True:
        result = letters[n % 26] + result
        n = n // 26 - 1
        if n < 0:
            break
    return f"T{turn_index}.{result}"


def is_boundary_key(key: str) -> bool:
    """True if a node key represents a boundary (__start__/__end__ or agent subgraph boundary)."""
    return (
        key in ("__start__", "__end__")
        or key.endswith(".__start__")
        or key.endswith(".__end__")
    )


def make_edge_id(
    trace_id: str, step_label: str, src: str, tgt: str, etype: str
) -> str:
    """Deterministic edge id via SHA-256."""
    raw = f"{trace_id}|{step_label}|{src}|{tgt}|{etype}"
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_run_metadata(node: Node) -> RunMetadata:
    """Compute hashes and lengths of a node's inputs/outputs."""
    inp_str = json.dumps(node.inputs or {}, sort_keys=True, default=str)
    out_str = json.dumps(node.outputs or {}, sort_keys=True, default=str)
    return RunMetadata(
        inputs_hash=hashlib.sha256(inp_str.encode()).hexdigest(),
        outputs_hash=hashlib.sha256(out_str.encode()).hexdigest(),
        inputs_len=len(inp_str),
        outputs_len=len(out_str),
    )


def source_trust(node: Node) -> str:
    """Trust level of a node's data: system, retrieval, or tool."""
    if node.type == "llm":
        return "system"
    name = _tool_name_from_node(node)
    if name in ("web_surfer", "file_surfer"):
        return "retrieval"
    return "tool"


def target_privilege(key: str) -> str:
    """Privilege level of a named node: high, med, or low."""
    if key in ("orchestrator", "code_executor"):
        return "high"
    if key in ("file_surfer", "web_surfer"):
        return "med"
    return "low"


def cross_boundary(src_trust: str, tgt_privilege: str) -> bool:
    """True when low-trust source feeds high-privilege target (injection propagation risk)."""
    trust_order = {"user": 0, "retrieval": 1, "tool": 2, "system": 3}
    priv_order = {"low": 0, "med": 1, "high": 2}
    return trust_order.get(src_trust, 0) < 2 and priv_order.get(tgt_privilege, 0) >= 2


def _make_edge_attrs(
    trace_id: str,
    step_lbl: str,
    src: str,
    tgt: str,
    etype: str,
    turn_index: int,
    start_time: str,
    seq_no: int,
    src_run_id: str | None,
    tgt_run_id: str | None,
    src_trust: str,
    tgt_priv: str,
    *,
    run_meta: RunMetadata | None = None,
    args_hash: str | None = None,
) -> dict:
    """Build the standard edge attributes dict."""
    attrs = {
        "type": etype,
        "turn": turn_index,
        "step_label": step_lbl,
        "start_time": start_time,
        "seq_no": seq_no,
        "edge_id": make_edge_id(trace_id, step_lbl, src, tgt, etype),
        "source_run_id": src_run_id,
        "target_run_id": tgt_run_id,
        "source_trust": src_trust,
        "target_privilege": tgt_priv,
        "cross_boundary": cross_boundary(src_trust, tgt_priv),
    }
    if run_meta:
        attrs.update(
            inputs_hash=run_meta.inputs_hash,
            outputs_hash=run_meta.outputs_hash,
            inputs_len=run_meta.inputs_len,
            outputs_len=run_meta.outputs_len,
        )
    if args_hash:
        attrs["args_hash"] = args_hash
    return attrs


def _infer_tool_call_edge(
    trace_id: str, turn: Turn, step_lbl: str, seq_no: int,
    a: Node, b: Node, src_key: str, tgt_key: str,
    start_time: str, src_run_id: str | None, tgt_run_id: str | None,
    src_trust_val: str, tgt_priv: str,
) -> tuple[str, str, dict]:
    """LLM -> Tool: tool_call edge."""
    meta = compute_run_metadata(b)
    args_hash = hashlib.sha256(
        json.dumps(b.inputs or {}, sort_keys=True, default=str).encode()
    ).hexdigest()
    attrs = _make_edge_attrs(
        trace_id, step_lbl, src_key, tgt_key, "tool_call",
        turn.index, start_time, seq_no, src_run_id, tgt_run_id,
        src_trust_val, tgt_priv, run_meta=meta, args_hash=args_hash,
    )
    attrs["payload"] = {"tool_name": _tool_name_from_node(b), "target": tgt_key}
    return (src_key, tgt_key, attrs)


def _infer_return_edge(
    trace_id: str, turn: Turn, step_lbl: str, seq_no: int,
    a: Node, src_key: str, tgt_key: str,
    start_time: str, src_run_id: str | None, tgt_run_id: str | None,
    src_trust_val: str, tgt_priv: str,
) -> tuple[str, str, dict]:
    """Tool -> LLM: routing edge returning tool result."""
    meta = compute_run_metadata(a)
    attrs = _make_edge_attrs(
        trace_id, step_lbl, src_key, tgt_key, "routing",
        turn.index, start_time, seq_no, src_run_id, tgt_run_id,
        src_trust_val, tgt_priv, run_meta=meta,
    )
    attrs["payload"] = {"target": tgt_key}
    return (src_key, tgt_key, attrs)


def _infer_routing_edges(
    trace_id: str, turn: Turn, step_lbl: str, seq_no: int,
    a: Node, src_key: str, tgt_key: str,
    start_time: str, src_run_id: str | None, tgt_run_id: str | None,
    src_trust_val: str, tgt_priv: str,
) -> tuple[list[tuple[str, str, dict]], int]:
    """LLM -> LLM: routing edges, inserting subgraph boundary nodes as needed.

    Returns (edges, updated_seq_no).
    """
    edges: list[tuple[str, str, dict]] = []

    if src_key == tgt_key:
        return edges, seq_no

    src_is_sub = src_key in SUB_AGENTS
    tgt_is_sub = tgt_key in SUB_AGENTS
    intermediate: str | None = None

    if src_is_sub:
        src_end = f"{src_key}.__end__"
        st_priv = target_privilege(src_end)
        attrs = _make_edge_attrs(
            trace_id, step_lbl, src_key, src_end, "routing",
            turn.index, start_time, seq_no, src_run_id, None,
            src_trust_val, st_priv,
        )
        attrs["payload"] = {"target": src_end}
        edges.append((src_key, src_end, attrs))
        seq_no += 1
        intermediate = src_end

    if tgt_is_sub:
        tgt_start = f"{tgt_key}.__start__"
        from_node = intermediate or src_key
        from_trust = src_trust_val if from_node == src_key else "system"
        from_run_id = src_run_id if from_node == src_key else None
        st_priv = target_privilege(tgt_start)

        attrs = _make_edge_attrs(
            trace_id, step_lbl, from_node, tgt_start, "routing",
            turn.index, start_time, seq_no, from_run_id, None,
            from_trust, st_priv,
        )
        attrs["payload"] = {"target": tgt_start}
        edges.append((from_node, tgt_start, attrs))
        seq_no += 1

        attrs = _make_edge_attrs(
            trace_id, step_lbl, tgt_start, tgt_key, "routing",
            turn.index, start_time, seq_no, None, tgt_run_id,
            "system", tgt_priv,
        )
        attrs["payload"] = {"target": tgt_key}
        edges.append((tgt_start, tgt_key, attrs))
        seq_no += 1
    else:
        from_node = intermediate or src_key
        from_trust = src_trust_val if from_node == src_key else "system"
        from_run_id = src_run_id if from_node == src_key else None
        attrs = _make_edge_attrs(
            trace_id, step_lbl, from_node, tgt_key, "routing",
            turn.index, start_time, seq_no, from_run_id, tgt_run_id,
            from_trust, tgt_priv,
        )
        attrs["payload"] = {"target": tgt_key}
        edges.append((from_node, tgt_key, attrs))
        seq_no += 1

    return edges, seq_no


def infer_edges_named(turn: Turn, trace_id: str = "") -> list[tuple[str, str, dict]]:
    """Infer typed edges between consecutive named nodes in a turn.

    For LLM->LLM transitions across different agents, inserts subgraph boundary
    nodes (agent.__start__ / agent.__end__) mirroring LangGraph structure.
    """
    edges: list[tuple[str, str, dict]] = []
    nodes = turn.nodes
    seq_no = 0

    for i in range(len(nodes) - 1):
        a, b = nodes[i], nodes[i + 1]
        src_key = node_key(a)
        tgt_key = node_key(b)
        step_lbl = step_label_str(turn.index, i)
        start_time = a.start_time or ""
        src_trust_val = source_trust(a)
        tgt_priv = target_privilege(tgt_key)
        src_run_id = a.id or None
        tgt_run_id = b.id or None

        if a.type == "llm" and b.type == "tool":
            edges.append(_infer_tool_call_edge(
                trace_id, turn, step_lbl, seq_no,
                a, b, src_key, tgt_key,
                start_time, src_run_id, tgt_run_id,
                src_trust_val, tgt_priv,
            ))
            seq_no += 1

        elif a.type == "tool" and b.type == "llm":
            edges.append(_infer_return_edge(
                trace_id, turn, step_lbl, seq_no,
                a, src_key, tgt_key,
                start_time, src_run_id, tgt_run_id,
                src_trust_val, tgt_priv,
            ))
            seq_no += 1

        elif a.type == "llm" and b.type == "llm":
            new_edges, seq_no = _infer_routing_edges(
                trace_id, turn, step_lbl, seq_no,
                a, src_key, tgt_key,
                start_time, src_run_id, tgt_run_id,
                src_trust_val, tgt_priv,
            )
            edges.extend(new_edges)

    return edges
