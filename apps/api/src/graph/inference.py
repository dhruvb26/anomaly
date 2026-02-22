"""Edge inference: derive agent/tool names and routing edges from turn data."""

from __future__ import annotations

import hashlib
import json
import logging

from src.graph.config import _AGENT_SYSTEM_PROMPT_HINTS, _SUB_AGENTS
from src.graph.schemas import Node, Turn

logger = logging.getLogger(__name__)

PREVIEW_LEN = 512


def _agent_name_from_llm_node(node: Node) -> str:
    """Derive the agent name from an LLM run's system prompt. Falls back to 'llm'."""
    try:
        inp = getattr(node, "inputs", None) or {}
        msgs = inp.get("messages") or []
        if msgs and isinstance(msgs[0], list):
            msgs = msgs[0]
        for m in msgs:
            kwargs = {}
            if isinstance(m, dict):
                kwargs = m.get("kwargs") or m
            content = kwargs.get("content") or ""
            if not isinstance(content, str):
                continue
            for hint, name in _AGENT_SYSTEM_PROMPT_HINTS:
                if hint in content:
                    return name
    except (IndexError, KeyError, TypeError):
        pass
    return "llm"


def _tool_name_from_node(node: Node) -> str:
    """Get tool name from a tool run's outputs.output.name."""
    out = getattr(node, "outputs", None) or {}
    output = out.get("output")
    if isinstance(output, dict) and output.get("name"):
        return str(output["name"])
    return "tool"


def _next_agent_from_llm_outputs(node: Node) -> str:
    """Extract next_agent from OrchestratorDecision tool call in LLM outputs, else 'continue'."""
    out = getattr(node, "outputs", None) or {}
    try:
        gens = out.get("generations") or []
        if not gens or not gens[0]:
            return "continue"
        msg = gens[0][0].get("message", {})
        kwargs = msg.get("kwargs", {})
        for tc in kwargs.get("tool_calls") or []:
            if tc.get("name") == "OrchestratorDecision":
                return tc.get("args", {}).get("next_agent") or "continue"
    except (IndexError, KeyError, TypeError):
        pass
    return "continue"


def node_key(node: Node) -> str:
    """Canonical graph node key: agent name for LLM, tool name for tool."""
    if getattr(node, "type", None) == "llm":
        return _agent_name_from_llm_node(node)
    return _tool_name_from_node(node)


def step_label_str(turn_index: int, step: int) -> str:
    """T{turn}.{letter} — e.g. T2.a, T2.b …"""
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
    """True if a node key represents a boundary node (__start__, __end__, agent.__start__, etc.)"""
    return (
        key in ("__start__", "__end__")
        or key.endswith(".__start__")
        or key.endswith(".__end__")
    )


def make_edge_id(
    trace_id: str, step_label: str, src: str, tgt: str, etype: str
) -> str:
    """Stable edge id: sha256(trace_id + step_label + source_id + target_id + type)."""
    raw = f"{trace_id}|{step_label}|{src}|{tgt}|{etype}"
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_run_metadata(node: Node) -> dict:
    """Return inputs_hash, outputs_hash, inputs_len, outputs_len, inputs_preview, outputs_preview."""
    inp = getattr(node, "inputs", None) or {}
    out = getattr(node, "outputs", None) or {}
    inp_str = json.dumps(inp, sort_keys=True, default=str)
    out_str = json.dumps(out, sort_keys=True, default=str)
    return {
        "inputs_hash": hashlib.sha256(inp_str.encode()).hexdigest(),
        "outputs_hash": hashlib.sha256(out_str.encode()).hexdigest(),
        "inputs_len": len(inp_str),
        "outputs_len": len(out_str),
        "inputs_preview": inp_str[:PREVIEW_LEN] if inp_str else "",
        "outputs_preview": out_str[:PREVIEW_LEN] if out_str else "",
    }


def source_trust(node: Node) -> str:
    """Trust level of a node's data: system, retrieval, tool."""
    if getattr(node, "type", None) == "llm":
        return "system"
    name = _tool_name_from_node(node)
    if name in ("web_surfer", "file_surfer"):
        return "retrieval"
    if name == "code_executor":
        return "tool"
    return "tool"


def target_privilege(key: str) -> str:
    """Privilege level of a named node: high, med, low."""
    if key in ("orchestrator", "code_executor"):
        return "high"
    if key in ("file_surfer", "web_surfer"):
        return "med"
    return "low"


def cross_boundary(source_trust: str, target_privilege: str) -> bool:
    """True when low-trust source feeds high-privilege target (e.g. injection propagation)."""
    trust_order = {"user": 0, "retrieval": 1, "tool": 2, "system": 3}
    priv_order = {"low": 0, "med": 1, "high": 2}
    src_val = trust_order.get(source_trust, 0)
    tgt_val = priv_order.get(target_privilege, 0)
    return src_val < 2 and tgt_val >= 2


def infer_edges_named(turn: Turn, trace_id: str = "") -> list[tuple[str, str, dict]]:
    """
    Infer edges between consecutive named nodes in a turn.
    Returns (src_key, tgt_key, attrs) tuples.

    For llm→llm transitions across different agents:
      - If orchestrator routes to a sub-agent:
          orchestrator → {agent}.__start__ → {agent}
      - If a sub-agent returns to orchestrator:
          {agent} → {agent}.__end__ → orchestrator
      - If two sub-agents hand off:
          {a} → {a}.__end__ → {b}.__start__ → {b}

    This mirrors the LangGraph subgraph boundary structure shown in the graph image.
    """
    edges: list[tuple[str, str, dict]] = []
    nodes = turn.nodes
    seq_no = 0
    for i in range(len(nodes) - 1):
        a, b = nodes[i], nodes[i + 1]
        src_key = node_key(a)
        tgt_key = node_key(b)
        a_type = getattr(a, "type", None)
        b_type = getattr(b, "type", None)
        step_lbl = step_label_str(turn.index, i)
        start_time = getattr(a, "start_time", "") or ""
        src_trust = source_trust(a)
        tgt_priv = target_privilege(tgt_key)
        cross_bnd = cross_boundary(src_trust, tgt_priv)

        src_run_id = str(getattr(a, "id", None) or "") or None
        tgt_run_id = str(getattr(b, "id", None) or "") or None

        if a_type == "llm" and b_type == "tool":
            etype = "tool_call"
            edge_id = make_edge_id(trace_id, step_lbl, src_key, tgt_key, etype)
            base_attrs = {
                "turn": turn.index,
                "step_label": step_lbl,
                "start_time": start_time,
                "seq_no": seq_no,
                "edge_id": edge_id,
                "source_run_id": src_run_id,
                "target_run_id": tgt_run_id,
                "source_trust": src_trust,
                "target_privilege": tgt_priv,
                "cross_boundary": cross_bnd,
                **compute_run_metadata(b),
                "args_hash": hashlib.sha256(
                    json.dumps(
                        getattr(b, "inputs", None) or {}, sort_keys=True, default=str
                    ).encode()
                ).hexdigest(),
            }
            seq_no += 1
            tool_name = _tool_name_from_node(b)
            edges.append(
                (
                    src_key,
                    tgt_key,
                    {
                        **base_attrs,
                        "type": etype,
                        "payload": {"tool_name": tool_name, "target": tgt_key},
                    },
                )
            )

        elif a_type == "tool" and b_type == "llm":
            etype = "routing"
            edge_id = make_edge_id(trace_id, step_lbl, src_key, tgt_key, etype)
            base_attrs = {
                "turn": turn.index,
                "step_label": step_lbl,
                "start_time": start_time,
                "seq_no": seq_no,
                "edge_id": edge_id,
                "source_run_id": src_run_id,
                "target_run_id": tgt_run_id,
                "source_trust": src_trust,
                "target_privilege": tgt_priv,
                "cross_boundary": cross_bnd,
                **compute_run_metadata(a),
            }
            seq_no += 1
            edges.append(
                (
                    src_key,
                    tgt_key,
                    {
                        **base_attrs,
                        "type": etype,
                        "payload": {"target": tgt_key},
                    },
                )
            )

        elif a_type == "llm" and b_type == "llm":
            inferred_target = _next_agent_from_llm_outputs(a)
            routing_payload = {"target": inferred_target}
            etype = "routing"

            if src_key == tgt_key:
                edge_id = make_edge_id(trace_id, step_lbl, src_key, tgt_key, etype)
                base_attrs = {
                    "turn": turn.index,
                    "step_label": step_lbl,
                    "start_time": start_time,
                    "seq_no": seq_no,
                    "edge_id": edge_id,
                    "source_run_id": src_run_id,
                    "target_run_id": tgt_run_id,
                    "source_trust": src_trust,
                    "target_privilege": tgt_priv,
                    "cross_boundary": cross_bnd,
                }
                seq_no += 1
                edges.append(
                    (
                        src_key,
                        tgt_key,
                        {
                            **base_attrs,
                            "type": etype,
                            "payload": routing_payload,
                        },
                    )
                )
            else:
                # Different agents: wire up subgraph boundary nodes.
                src_is_sub = src_key in _SUB_AGENTS
                tgt_is_sub = tgt_key in _SUB_AGENTS
                intermediate: str | None = None

                if src_is_sub:
                    src_end = f"{src_key}.__end__"
                    st_priv = target_privilege(src_end)
                    edge_id = make_edge_id(trace_id, step_lbl, src_key, src_end, etype)
                    base_attrs = {
                        "turn": turn.index,
                        "step_label": step_lbl,
                        "start_time": start_time,
                        "seq_no": seq_no,
                        "edge_id": edge_id,
                        "source_run_id": src_run_id,
                        "target_run_id": None,
                        "source_trust": src_trust,
                        "target_privilege": st_priv,
                        "cross_boundary": cross_boundary(src_trust, st_priv),
                    }
                    seq_no += 1
                    edges.append(
                        (
                            src_key,
                            src_end,
                            {
                                **base_attrs,
                                "type": etype,
                                "payload": {"target": src_end},
                            },
                        )
                    )
                    intermediate = src_end

                if tgt_is_sub:
                    tgt_start = f"{tgt_key}.__start__"
                    from_node = intermediate if intermediate is not None else src_key
                    st_priv = target_privilege(tgt_start)
                    edge_id = make_edge_id(
                        trace_id, step_lbl, from_node, tgt_start, etype
                    )
                    a_trust = source_trust(a)
                    base_attrs = {
                        "turn": turn.index,
                        "step_label": step_lbl,
                        "start_time": start_time,
                        "seq_no": seq_no,
                        "edge_id": edge_id,
                        "source_run_id": src_run_id if from_node == src_key else None,
                        "target_run_id": None,
                        "source_trust": a_trust if from_node == src_key else "system",
                        "target_privilege": st_priv,
                        "cross_boundary": cross_boundary(
                            a_trust if from_node == src_key else "system",
                            st_priv,
                        ),
                    }
                    seq_no += 1
                    edges.append(
                        (
                            from_node,
                            tgt_start,
                            {
                                **base_attrs,
                                "type": etype,
                                "payload": {"target": tgt_start},
                            },
                        )
                    )
                    edge_id = make_edge_id(
                        trace_id, step_lbl, tgt_start, tgt_key, etype
                    )
                    base_attrs = {
                        "turn": turn.index,
                        "step_label": step_lbl,
                        "start_time": start_time,
                        "seq_no": seq_no,
                        "edge_id": edge_id,
                        "source_run_id": None,
                        "target_run_id": tgt_run_id,
                        "source_trust": "system",
                        "target_privilege": tgt_priv,
                        "cross_boundary": cross_boundary("system", tgt_priv),
                    }
                    seq_no += 1
                    edges.append(
                        (
                            tgt_start,
                            tgt_key,
                            {
                                **base_attrs,
                                "type": etype,
                                "payload": {"target": tgt_key},
                            },
                        )
                    )
                else:
                    from_node = intermediate if intermediate is not None else src_key
                    edge_id = make_edge_id(
                        trace_id, step_lbl, from_node, tgt_key, etype
                    )
                    base_attrs = {
                        "turn": turn.index,
                        "step_label": step_lbl,
                        "start_time": start_time,
                        "seq_no": seq_no,
                        "edge_id": edge_id,
                        "source_run_id": src_run_id if from_node == src_key else None,
                        "target_run_id": tgt_run_id,
                        "source_trust": src_trust,
                        "target_privilege": tgt_priv,
                        "cross_boundary": cross_bnd,
                    }
                    seq_no += 1
                    edges.append(
                        (
                            from_node,
                            tgt_key,
                            {
                                **base_attrs,
                                "type": etype,
                                "payload": {"target": tgt_key},
                            },
                        )
                    )

    return edges
