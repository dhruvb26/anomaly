"""Persist the in-memory graph to Neo4j."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import networkx as nx

from src.graph.builder import (
    _session_node_key,
    _thread_node_key,
    _trace_node_key,
)
from src.stores import GraphDB

logger = logging.getLogger(__name__)

_LABEL = {
    "session": "Session",
    "thread": "Thread",
    "trace": "Trace",
    "boundary": "Boundary",
    "llm": "Agent",
    "tool": "Tool",
    "chain": "Chain",
}

_REL_TYPE = {
    "routing": "ROUTES_TO",
    "tool_call": "CALLS_TOOL",
    "contains": "CONTAINS",
    "has_trace": "HAS_TRACE",
    "has_thread": "HAS_THREAD",
}


def _persist_session(db: GraphDB, session_id: str) -> None:
    db.create(
        "MERGE (s:Session {session_id: $session_id})",
        parameters={"session_id": session_id},
    )


def _persist_thread_node(db: GraphDB, thread_id: str, session_id: str, nd: dict) -> None:
    props = "n.session_id = $session_id, n.turn_count = $turn_count"
    db.create(
        f"MERGE (n:Thread {{thread_id: $thread_id}}) "
        f"ON CREATE SET {props} ON MATCH SET {props}",
        parameters={
            "thread_id": thread_id,
            "session_id": session_id,
            "turn_count": nd.get("turn_count", 0),
        },
    )


def _persist_trace_node(db: GraphDB, thread_id: str, nd: dict) -> None:
    trace_id = nd.get("trace_id", "")
    props = (
        "n.name = $name, n.turn = $turn, "
        "n.start_time = $start_time, n.end_time = $end_time, "
        "n.total_cost = $total_cost, n.total_tokens = $total_tokens, "
        "n.prompt_tokens = $prompt_tokens, n.completion_tokens = $completion_tokens, "
        "n.status = $status"
    )
    db.create(
        f"MERGE (n:Trace {{trace_id: $trace_id, thread_id: $thread_id}}) "
        f"ON CREATE SET {props} ON MATCH SET {props}",
        parameters={
            "trace_id": trace_id,
            "thread_id": thread_id,
            "name": trace_id,
            "turn": nd.get("turn", 0),
            "start_time": nd.get("start_time", ""),
            "end_time": nd.get("end_time", ""),
            "total_cost": nd.get("total_cost", 0),
            "total_tokens": nd.get("total_tokens", 0),
            "prompt_tokens": nd.get("prompt_tokens", 0),
            "completion_tokens": nd.get("completion_tokens", 0),
            "status": nd.get("status") or "",
        },
    )


def _persist_chain_node(
    db: GraphDB, label: str, node_name: str, thread_id: str, nd: dict
) -> None:
    props = (
        "n.name = $name, n.type = $type, "
        "n.parent_run_id = $parent_run_id, n.start_time = $start_time, n.status = $status"
    )
    db.create(
        f"MERGE (n:{label} {{run_id: $run_id, thread_id: $thread_id}}) "
        f"ON CREATE SET {props} ON MATCH SET {props}",
        parameters={
            "run_id": nd.get("run_id", ""),
            "thread_id": thread_id,
            "name": node_name,
            "type": nd.get("type", "chain"),
            "parent_run_id": nd.get("parent_run_id", ""),
            "start_time": nd.get("start_time", ""),
            "status": nd.get("status") or "",
        },
    )


def _persist_agent_tool_node(
    db: GraphDB, label: str, node_name: str, thread_id: str, nd: dict,
    available_tools: list,
) -> None:
    invocations = nd.get("invocations", [])
    invocation_count = len(invocations)
    error_count = sum(1 for iv in invocations if iv.get("error"))
    last_seen = max((str(iv.get("start_time") or "") for iv in invocations), default="")
    total_cost = sum(iv.get("total_cost", 0) or 0 for iv in invocations)
    total_tokens = sum(iv.get("total_tokens", 0) or 0 for iv in invocations)
    prompt_tokens = sum(iv.get("prompt_tokens", 0) or 0 for iv in invocations)
    completion_tokens = sum(iv.get("completion_tokens", 0) or 0 for iv in invocations)
    prompt_cost = sum(iv.get("prompt_cost", 0) or 0 for iv in invocations)
    completion_cost = sum(iv.get("completion_cost", 0) or 0 for iv in invocations)

    props = (
        "n.type = $type, n.invocation_count = $invocation_count, n.error_count = $error_count, "
        "n.last_seen = $last_seen, n.total_cost = $total_cost, n.total_tokens = $total_tokens, "
        "n.prompt_tokens = $prompt_tokens, n.completion_tokens = $completion_tokens, "
        "n.prompt_cost = $prompt_cost, n.completion_cost = $completion_cost, n.available_tools = $available_tools, "
        "n.node_risk_score = $node_risk_score, n.node_risk_label = $node_risk_label, "
        "n.node_anomaly_types = $node_anomaly_types, n.node_last_scanned_at = $node_last_scanned_at"
    )
    db.create(
        f"MERGE (n:{label} {{name: $name, thread_id: $thread_id}}) "
        f"ON CREATE SET {props} ON MATCH SET {props}",
        parameters={
            "name": node_name,
            "thread_id": thread_id,
            "type": nd.get("type", "llm"),
            "invocation_count": invocation_count,
            "error_count": error_count,
            "last_seen": last_seen,
            "total_cost": total_cost,
            "total_tokens": total_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "prompt_cost": prompt_cost,
            "completion_cost": completion_cost,
            "available_tools": available_tools,
            "node_risk_score": None,
            "node_risk_label": None,
            "node_anomaly_types": [],
            "node_last_scanned_at": None,
        },
    )


def _persist_nodes(
    db: GraphDB, G: nx.MultiDiGraph, thread_id: str, session_id: str,
    agent_available_tools: dict,
) -> None:
    """Persist all graph nodes to Neo4j."""
    _persist_session(db, session_id)

    for node_name, nd in G.nodes(data=True):
        ntype = nd.get("type", "llm")
        label = _LABEL.get(ntype, "Agent")

        if ntype == "session":
            continue
        elif ntype == "thread":
            _persist_thread_node(db, thread_id, session_id, nd)
        elif ntype == "trace":
            _persist_trace_node(db, thread_id, nd)
        elif ntype == "chain":
            _persist_chain_node(db, label, node_name, thread_id, nd)
        else:
            tools = agent_available_tools.get(node_name, [])
            _persist_agent_tool_node(db, label, node_name, thread_id, nd, tools)


def _persist_relationships(
    db: GraphDB, G: nx.MultiDiGraph, thread_id: str, session_id: str,
) -> None:
    """Persist all graph edges/relationships to Neo4j."""
    session_key = _session_node_key(session_id)
    thread_key = _thread_node_key(thread_id)

    for u, v, _key, data in G.edges(data=True, keys=True):
        etype = data.get("type", "routing")
        rel_type = _REL_TYPE.get(etype, "ROUTES_TO")

        if etype == "has_thread":
            db.create(
                "MATCH (session:Session {session_id: $session_id}), "
                "(thread:Thread {thread_id: $thread_id}) "
                "MERGE (session)-[:HAS_THREAD]->(thread)",
                parameters={"session_id": session_id, "thread_id": thread_id},
            )
            continue

        if etype == "has_trace":
            trace_nd = G.nodes.get(v, {})
            db.create(
                "MATCH (thread:Thread {thread_id: $thread_id}), "
                "(trace:Trace {trace_id: $trace_id, thread_id: $thread_id}) "
                "MERGE (thread)-[r:HAS_TRACE]->(trace) SET r.turn = $turn",
                parameters={
                    "thread_id": thread_id,
                    "trace_id": trace_nd.get("trace_id", ""),
                    "turn": trace_nd.get("turn", 0),
                },
            )
            continue

        if u in (session_key, thread_key) or v in (session_key, thread_key):
            continue

        if etype == "contains" and u.startswith("__trace__:"):
            trace_nd = G.nodes.get(u, {})
            chain_nd = G.nodes.get(v, {})
            db.create(
                "MATCH (trace:Trace {trace_id: $trace_id, thread_id: $thread_id}), "
                "(chain:Chain {run_id: $run_id, thread_id: $thread_id}) "
                "MERGE (trace)-[r:CONTAINS]->(chain) SET r.turn = $turn",
                parameters={
                    "trace_id": trace_nd.get("trace_id", ""),
                    "run_id": chain_nd.get("run_id", ""),
                    "thread_id": thread_id,
                    "turn": data.get("turn", 0),
                },
            )
            continue

        if u.startswith("__trace__:") or v.startswith("__trace__:"):
            continue

        edge_id = data.get("edge_id")
        if edge_id is not None:
            db.create(
                f"MATCH (a {{name: $src, thread_id: $thread_id}}), "
                f"(b {{name: $tgt, thread_id: $thread_id}}) "
                f"MERGE (a)-[r:{rel_type} {{edge_id: $edge_id}}]->(b) "
                f"SET r.turn = $turn, r.start_time = $start_time, r.seq_no = $seq_no, "
                f"r.source_run_id = $source_run_id, r.target_run_id = $target_run_id, "
                f"r.inputs_hash = $inputs_hash, r.outputs_hash = $outputs_hash, "
                f"r.inputs_len = $inputs_len, r.outputs_len = $outputs_len, "
                f"r.source_trust = $source_trust, r.target_privilege = $target_privilege, "
                f"r.cross_boundary = $cross_boundary, r.args_hash = $args_hash, "
                f"r.edge_risk_score = $edge_risk_score, r.edge_risk_label = $edge_risk_label, "
                f"r.edge_flow_flags = $edge_flow_flags, r.edge_last_scanned_at = $edge_last_scanned_at",
                parameters={
                    "src": u,
                    "tgt": v,
                    "thread_id": thread_id,
                    "edge_id": edge_id,
                    "turn": data.get("turn", 0),
                    "start_time": data.get("start_time", ""),
                    "seq_no": data.get("seq_no"),
                    "source_run_id": data.get("source_run_id"),
                    "target_run_id": data.get("target_run_id"),
                    "inputs_hash": data.get("inputs_hash"),
                    "outputs_hash": data.get("outputs_hash"),
                    "inputs_len": data.get("inputs_len"),
                    "outputs_len": data.get("outputs_len"),
                    "source_trust": data.get("source_trust"),
                    "target_privilege": data.get("target_privilege"),
                    "cross_boundary": data.get("cross_boundary"),
                    "args_hash": data.get("args_hash"),
                    "edge_risk_score": None,
                    "edge_risk_label": None,
                    "edge_flow_flags": [],
                    "edge_last_scanned_at": None,
                },
            )
        else:
            db.create(
                f"MATCH (a {{name: $src, thread_id: $thread_id}}), "
                f"(b {{name: $tgt, thread_id: $thread_id}}) "
                f"MERGE (a)-[r:{rel_type}]->(b) "
                f"SET r.turn = $turn, r.start_time = $start_time",
                parameters={
                    "src": u,
                    "tgt": v,
                    "thread_id": thread_id,
                    "turn": data.get("turn", 0),
                    "start_time": data.get("start_time", ""),
                },
            )


def _persist_covers(
    db: GraphDB, G: nx.MultiDiGraph, thread_id: str,
    trace_covers: dict[str, set[str]],
) -> None:
    """Persist Trace-[:COVERS]->Node relationships."""
    for trace_id, covered in trace_covers.items():
        for node_name in covered:
            if node_name not in G:
                continue
            trace_nd = G.nodes.get(_trace_node_key(trace_id))
            if not trace_nd:
                continue
            db.create(
                "MATCH (trace:Trace {trace_id: $trace_id, thread_id: $thread_id}), "
                "(n {name: $node_name, thread_id: $thread_id}) "
                "MERGE (trace)-[:COVERS]->(n)",
                parameters={
                    "trace_id": trace_id,
                    "thread_id": thread_id,
                    "node_name": node_name,
                },
            )


def save_graph_to_db(
    db: GraphDB,
    G: nx.MultiDiGraph,
    thread_id: str,
    session_id: str,
    trace_covers: dict[str, set[str]],
    turns: list,
    payload_store=None,
    available_tools: dict | None = None,
) -> None:
    """Persist the full thread graph to Neo4j."""
    if payload_store is not None:
        for turn in turns:
            for node in turn.nodes:
                run_id = node.id or ""
                if run_id:
                    payload_store.store(
                        run_id,
                        {"inputs": node.inputs, "outputs": node.outputs},
                    )

    agent_available_tools = available_tools or {}
    _persist_nodes(db, G, thread_id, session_id, agent_available_tools)
    _persist_relationships(db, G, thread_id, session_id)
    _persist_covers(db, G, thread_id, trace_covers)

    logger.info(
        "Saved thread %s -- %d nodes, %d edges",
        thread_id[:16], G.order(), G.size(),
    )


def _anomaly_types_from_details(details: str, risk_type: str) -> list[str]:
    """Extract anomaly type labels from details string (e.g. 'jailbreak:...; hallucination:...')."""
    if not details or details == "ok":
        return [risk_type] if risk_type else []
    parts = [p.strip() for p in details.split(";") if p.strip()]
    result = []
    for p in parts:
        if ":" in p:
            label = p.split(":", 1)[0].strip()
        else:
            label = p[:64] if len(p) > 64 else p
        if label and label not in result:
            result.append(label)
    return result if result else ([risk_type] if risk_type else [])


def write_sentinel_results(db: GraphDB, thread_id: str, report) -> None:
    """Write sentinel AnalysisReport risk metadata to existing Neo4j nodes and edges.

    Aggregates by node_key (resp. src_key,tgt_key): max confidence and merged anomaly types.
    Only updates Agent and Tool nodes; updates all ROUTES_TO and CALLS_TOOL edges between matched pairs.
    """
    from src.graph.behavior_analyzer import AnalysisReport, EdgeStatus, NodeStatus

    if not isinstance(report, AnalysisReport):
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    node_agg: dict[str, tuple[float, str, list[str]]] = {}
    for ta in report.turn_analyses:
        for ns in ta.node_statuses:
            if not isinstance(ns, NodeStatus):
                continue
            key = ns.node_key
            anomaly_types = _anomaly_types_from_details(ns.details, ns.risk_type or "")
            if key not in node_agg:
                node_agg[key] = (ns.confidence, ns.risk_type or "", anomaly_types)
            else:
                prev_conf, prev_label, prev_types = node_agg[key]
                new_conf = max(prev_conf, ns.confidence)
                new_label = ns.risk_type or prev_label or ""
                merged = list(dict.fromkeys(prev_types + anomaly_types))
                node_agg[key] = (new_conf, new_label, merged)

    for name, (confidence, risk_label, anomaly_types) in node_agg.items():
        try:
            db.create(
                "MATCH (n) WHERE n.name = $name AND n.thread_id = $thread_id "
                "AND (n:Agent OR n:Tool) SET n.node_risk_score = $score, "
                "n.node_risk_label = $label, n.node_anomaly_types = $types, "
                "n.node_last_scanned_at = $ts",
                parameters={
                    "name": name,
                    "thread_id": thread_id,
                    "score": confidence,
                    "label": risk_label or None,
                    "types": anomaly_types,
                    "ts": ts,
                },
            )
        except Exception:
            logger.debug("Writeback node risk for %s skipped", name)

    edge_agg: dict[tuple[str, str], tuple[float, str, list[str]]] = {}
    for ta in report.turn_analyses:
        for es in ta.edge_statuses:
            if not isinstance(es, EdgeStatus):
                continue
            key = (es.src_key, es.tgt_key)
            flow_flags = _anomaly_types_from_details(es.details, es.risk_type or "")
            if key not in edge_agg:
                edge_agg[key] = (es.confidence, es.risk_type or "", flow_flags)
            else:
                prev_conf, prev_label, prev_flags = edge_agg[key]
                new_conf = max(prev_conf, es.confidence)
                new_label = es.risk_type or prev_label or ""
                merged = list(dict.fromkeys(prev_flags + flow_flags))
                edge_agg[key] = (new_conf, new_label, merged)

    for (src_key, tgt_key), (confidence, risk_label, flow_flags) in edge_agg.items():
        try:
            db.create(
                "MATCH (a {name: $src, thread_id: $thread_id})-[r]->(b {name: $tgt, thread_id: $thread_id}) "
                "WHERE type(r) IN ['ROUTES_TO', 'CALLS_TOOL'] "
                "SET r.edge_risk_score = $score, r.edge_risk_label = $label, "
                "r.edge_flow_flags = $flags, r.edge_last_scanned_at = $ts",
                parameters={
                    "src": src_key,
                    "tgt": tgt_key,
                    "thread_id": thread_id,
                    "score": confidence,
                    "label": risk_label or None,
                    "flags": flow_flags,
                    "ts": ts,
                },
            )
        except Exception:
            logger.debug("Writeback edge risk for %s -> %s skipped", src_key, tgt_key)

    logger.info("Sentinel results written to Neo4j for thread %s", thread_id[:16])


def clear_graph_db(db: GraphDB) -> None:
    """Delete ALL nodes and relationships from Neo4j in batches."""
    while True:
        summary = db.create(
            "MATCH (n) WITH n LIMIT 1000 DETACH DELETE n RETURN count(*) AS deleted"
        )
        deleted = getattr(summary, "counters", None)
        nodes_deleted = getattr(deleted, "nodes_deleted", None) if deleted else None
        if nodes_deleted == 0:
            break
    logger.info("Graph DB cleared.")
