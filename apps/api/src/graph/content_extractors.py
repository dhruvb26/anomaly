"""Helpers for extracting content from nodes and edges for analysis."""

from __future__ import annotations

import json
import logging

from src.graph.inference import infer_edges_named, is_boundary_key
from src.graph.schemas import Node, Turn

logger = logging.getLogger(__name__)


def extract_path_sequence(turn: Turn) -> list[str]:
    """Ordered list of non-boundary agent/tool node keys from the turn."""
    trace_id = turn.trace_id or turn.root_chain_id or ""
    edges = infer_edges_named(turn, trace_id=str(trace_id))
    if not edges:
        return []
    path_keys = [edges[0][0]] + [tgt for (_, tgt, _) in edges]
    return [k for k in path_keys if not is_boundary_key(k)]


def first_genuine_user_content(messages: list) -> str:
    """Extract the first genuine user message (not an orchestrator routing message).

    LangGraph orchestrator adds HumanMessage with name="orchestrator" for routing.
    Real user queries have no name field. We iterate forward to get the original.
    """
    for m in messages:
        if isinstance(m, list):
            content = first_genuine_user_content(m)
            if content:
                return content
        if isinstance(m, dict):
            kwargs = m.get("kwargs") or m
            role = (kwargs.get("type") or kwargs.get("role") or "").lower()
            name = kwargs.get("name") or ""
            if role in ("human", "user") and not name:
                content = kwargs.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = [
                        p.get("text", p) if isinstance(p, dict) else str(p)
                        for p in content
                    ]
                    return " ".join(parts)
    return ""


def tool_calls_from_llm_outputs(node: Node) -> list[tuple[str, dict]]:
    """Extract (tool_name, args) pairs from an LLM node's outputs."""
    try:
        gens = (node.outputs or {}).get("generations") or []
        if not gens or not gens[0]:
            return []
        msg = gens[0][0].get("message", {})
        result = []
        for tc in msg.get("kwargs", {}).get("tool_calls") or []:
            name = tc.get("name") or "tool"
            args = tc.get("args") or {}
            result.append((name, args))
        return result
    except (IndexError, KeyError, TypeError):
        return []


def context_messages_from_inputs(node: Node) -> list[dict]:
    """Serialize input messages for Guardian context (truncated)."""
    msgs = (node.inputs or {}).get("messages") or []
    if not msgs:
        return []
    if isinstance(msgs[0], list):
        msgs = msgs[0]
    out = []
    for m in msgs[:15]:
        if isinstance(m, dict):
            out.append({
                "role": m.get("kwargs", m).get("type", "unknown"),
                "content": str(m)[:500],
            })
    return out


def extract_edge_content(attrs: dict, edge_type: str, payload_store=None) -> str:
    """Fetch content flowing along an edge from Redis.

    For routing edges: source node's outputs (data flowing forward).
    For tool_call edges: target node's inputs (args being passed).
    Falls back to empty string when payload_store is unavailable or the key is missing.
    """
    if payload_store is None:
        return ""

    if edge_type == "routing":
        run_id = attrs.get("source_run_id")
        field = "outputs"
    else:
        run_id = attrs.get("target_run_id")
        field = "inputs"

    if not run_id:
        return ""

    try:
        payload = payload_store.fetch(run_id)
    except Exception:
        logger.debug("Failed to fetch payload for run_id=%s", run_id)
        return ""

    if not payload:
        return ""

    content = payload.get(field) or {}
    return json.dumps(content, default=str) if content else ""
