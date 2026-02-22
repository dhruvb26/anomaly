"""Thread-level graph: build from samples, persist to Neo4j with Thread/Trace nodes."""

from __future__ import annotations

import logging
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
from src.stores import GraphDB

import networkx as nx

logger = logging.getLogger(__name__)


# Special node keys for Session, Thread and Trace (not mixed with agent/tool names)
def _session_node_key(session_id: str) -> str:
    return f"__session__:{session_id or 'default'}"


def _thread_node_key(thread_id: str) -> str:
    return f"__thread__:{thread_id}"


def _trace_node_key(trace_id: str) -> str:
    return f"__trace__:{trace_id}"


def _build_graph_from_turns(
    thread_id: str, turns: list
) -> tuple[nx.MultiDiGraph, str, dict[str, set[str]]]:
    """
    Build the in-memory graph (Session, Thread, Trace, agents, tools, edges) from
    a list of Turn instances. Returns (G, session_id, trace_covers).
    """
    G: nx.MultiDiGraph = nx.MultiDiGraph()
    trace_covers: dict[str, set[str]] = {}

    # Session id from first turn's root chain or first node
    session_id = ""
    if turns and turns[0].root_id and turns[0].root_id in turns[0].run_map:
        root_data = turns[0].run_map[turns[0].root_id].get("data") or {}
        session_id = str(root_data.get("session_id") or "")
    if not session_id and turns and turns[0].nodes:
        session_id = str(getattr(turns[0].nodes[0], "session_id", None) or "")

    # Global Session container node (one per session_id; create if not present in G)
    session_key = _session_node_key(session_id)
    if session_key not in G:
        G.add_node(
            session_key,
            type="session",
            session_id=session_id or "default",
        )

    # Thread container node (each session can have multiple Threads)
    thread_key = _thread_node_key(thread_id)
    G.add_node(
        thread_key,
        type="thread",
        thread_id=thread_id,
        session_id=session_id or "default",
        turn_count=len(turns),
    )
    G.add_edge(
        session_key,
        thread_key,
        type="has_thread",
        payload={"target": thread_id},
    )

    # Global boundary nodes
    for boundary in ("__start__", "__end__"):
        G.add_node(boundary, type="boundary", invocations=[])

    for turn in turns:
        # Trace container node for this turn
        trace_id = turn.trace_id or turn.root_chain_id or f"turn_{turn.index}"
        trace_key = _trace_node_key(trace_id)
        if trace_key not in G:
            # Aggregate cost/tokens from root chain if available
            total_cost = 0.0
            total_tokens = 0
            prompt_tokens = 0
            completion_tokens = 0
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
                thread_key,
                trace_key,
                type="has_trace",
                payload={"target": trace_id},
                turn=turn.index,
                step_label=f"T{turn.index}",
                start_time=turn.start_time,
            )

        nodes_covered: set[str] = set()

        # Chain nodes (only when flag is on)
        if INCLUDE_CHAIN_RUNS:
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
            # Chain-to-chain contains edges
            for run_id, entry in turn.run_map.items():
                parent = entry.get("parent_run_id")
                if parent and parent in G and run_id in G:
                    G.add_edge(
                        parent,
                        run_id,
                        type="contains",
                        payload={"target": run_id},
                        turn=turn.index,
                        step_label="",
                        start_time=entry.get("start_time", ""),
                    )
            # Trace → root chain: anchor the whole chain hierarchy to the trace
            if turn.root_id and turn.root_id in G:
                G.add_edge(
                    trace_key,
                    turn.root_id,
                    type="contains",
                    payload={"target": turn.root_id},
                    turn=turn.index,
                    step_label="",
                    start_time=turn.start_time,
                )

        # LLM / Tool nodes
        for step, node in enumerate(turn.nodes):
            key = node_key(node)
            nodes_covered.add(key)
            if key not in G:
                G.add_node(key, type=node.type, invocations=[])

            run_id = str(getattr(node, "id", None) or "")
            raw_parent = str(getattr(node, "parent_run_id", None) or "")

            if INCLUDE_CHAIN_RUNS:
                parent_ref_key = "parent_run_id"
                parent_ref_val = raw_parent
                # Connect the parent chain node to this agent/tool node
                if raw_parent and raw_parent in G:
                    G.add_edge(
                        raw_parent,
                        key,
                        type="contains",
                        payload={"target": key},
                        turn=turn.index,
                        step_label="",
                        start_time=str(getattr(node, "start_time", None) or ""),
                    )
            else:
                parent_ref_key = "delegation_chain_id"
                parent_ref_val = resolve_delegation_chain_id(
                    run_id, turn.run_map, turn.root_id
                )

            run_meta = compute_run_metadata(node)
            G.nodes[key]["invocations"].append(
                {
                    "turn": turn.index,
                    "step_label": step_label_str(turn.index, step),
                    "run_id": run_id,
                    "start_time": str(getattr(node, "start_time", None) or ""),
                    "status": getattr(node, "status", None),
                    "error": getattr(node, "error", None),
                    "session_id": str(getattr(node, "session_id", None) or ""),
                    "trace_id": str(getattr(node, "trace_id", None) or ""),
                    parent_ref_key: parent_ref_val,
                    "prompt_tokens": getattr(node, "prompt_tokens", None) or 0,
                    "completion_tokens": getattr(node, "completion_tokens", None) or 0,
                    "total_tokens": getattr(node, "total_tokens", None) or 0,
                    "prompt_cost": float(getattr(node, "prompt_cost", None) or 0),
                    "completion_cost": float(
                        getattr(node, "completion_cost", None) or 0
                    ),
                    "total_cost": float(getattr(node, "total_cost", None) or 0),
                    "inputs_hash": run_meta.get("inputs_hash", ""),
                    "outputs_hash": run_meta.get("outputs_hash", ""),
                    "inputs_len": run_meta.get("inputs_len", 0),
                    "outputs_len": run_meta.get("outputs_len", 0),
                }
            )

        # Routing edges (seq_no: 0 = __start__->first, 1..n = inferred, n+1.. = __end__)
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

        # __start__ → first agent
        if turn.nodes:
            first_node = turn.nodes[0]
            first_key = node_key(first_node)
            nodes_covered.add("__start__")
            nodes_covered.add(first_key)
            step_lbl = f"T{turn.index}.start"
            G.add_edge(
                "__start__",
                first_key,
                type="routing",
                payload={"target": first_key},
                turn=turn.index,
                step_label=step_lbl,
                start_time=str(getattr(first_node, "start_time", "") or ""),
                seq_no=0,
                edge_id=make_edge_id(
                    trace_id, step_lbl, "__start__", first_key, "routing"
                ),
                source_run_id=None,
                target_run_id=str(getattr(first_node, "id", None) or "") or None,
            )

        # source_agent → __end__
        end_seq = max_seq + 1
        for routing in turn.chain_routings:
            if routing["goto"] != "__end__":
                continue
            src = routing["source_agent"]
            nodes_covered.add("__end__")
            nodes_covered.add(src)
            if src not in G:
                G.add_node(src, type="llm", invocations=[])
            step_lbl = f"T{routing['turn_index']}.end"
            G.add_edge(
                src,
                "__end__",
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

        trace_covers[trace_id] = nodes_covered

    return G, session_id, trace_covers


class Thread:
    """Thread-level structural graph: agents/tools as nodes, invocations as edges.
    Includes optional Thread and Trace container nodes for Neo4j."""

    __slots__ = ("thread_id", "turns", "G", "session_id", "_trace_covers")

    def __init__(
        self,
        thread_id: str,
        turns: list[Turn],
        G: nx.MultiDiGraph,
        session_id: str = "",
        trace_covers: dict[str, set[str]] | None = None,
    ):
        self.thread_id = thread_id
        self.turns = turns
        self.G = G
        self.session_id = session_id or ""
        self._trace_covers = trace_covers if trace_covers is not None else {}

    @classmethod
    def from_turns(cls, thread_id: str, turns: list) -> "Thread":
        """
        Build a Thread graph from an in-memory list of Turn instances (e.g. from
        LangSmith SDK). No filesystem access.
        """
        if not turns:
            return cls(thread_id=thread_id, turns=[], G=nx.MultiDiGraph())
        G, session_id, trace_covers = _build_graph_from_turns(thread_id, turns)
        return cls(
            thread_id=thread_id,
            turns=turns,
            G=G,
            session_id=session_id,
            trace_covers=trace_covers,
        )

    def save_to_graph_db(
        self,
        db: GraphDB,
        payload_store=None,
        available_tools: dict | None = None,
    ) -> None:
        """
        Persist the thread graph to Neo4j.
        Ensures global Session node exists (MERGE), then creates Thread and Trace nodes,
        HAS_THREAD (Session->Thread), HAS_TRACE and COVERS relationships,
        then Boundary/Agent/Tool/Chain nodes and ROUTES_TO/CALLS_TOOL/CONTAINS.
        If payload_store is provided, stores full inputs/outputs keyed by run_id.
        If available_tools is provided, it is used to annotate Agent nodes with their
        configured tool list.
        """
        AGENT_AVAILABLE_TOOLS: dict = available_tools or {}

        G = self.G
        thread_id = self.thread_id
        session_id = self.session_id or "default"

        # Store full run payloads in blob store when provided
        if payload_store is not None:
            for turn in self.turns:
                for node in turn.nodes:
                    run_id = str(getattr(node, "id", None) or "")
                    if run_id:
                        payload_store.store(
                            run_id,
                            {
                                "inputs": getattr(node, "inputs", None),
                                "outputs": getattr(node, "outputs", None),
                            },
                        )

        _LABEL = {
            "session": "Session",
            "thread": "Thread",
            "trace": "Trace",
            "boundary": "Boundary",
            "llm": "Agent",
            "tool": "Tool",
            "chain": "Chain",
        }

        # Ensure global Session node exists (create if it doesn't)
        db.create(
            "MERGE (s:Session {session_id: $session_id})",
            parameters={"session_id": session_id},
        )

        # Create all nodes first (so MATCH works for relationships)
        for node_name, nd in G.nodes(data=True):
            ntype = nd.get("type", "llm")
            label = _LABEL.get(ntype, "Agent")

            if ntype == "session":
                continue  # Already MERGED above

            if ntype == "thread":
                db.create(
                    f"MERGE (n:{label} {{thread_id: $thread_id}}) "
                    f"ON CREATE SET n.session_id = $session_id, n.turn_count = $turn_count "
                    f"ON MATCH SET n.session_id = $session_id, n.turn_count = $turn_count",
                    parameters={
                        "thread_id": thread_id,
                        "session_id": session_id,
                        "turn_count": nd.get("turn_count", 0),
                    },
                )
                continue

            if ntype == "trace":
                trace_id_val = nd.get("trace_id", "")
                db.create(
                    "MERGE (n:Trace {trace_id: $trace_id, thread_id: $thread_id}) "
                    "ON CREATE SET n.name = $name, n.turn = $turn, "
                    "n.start_time = $start_time, n.end_time = $end_time, "
                    "n.total_cost = $total_cost, n.total_tokens = $total_tokens, "
                    "n.prompt_tokens = $prompt_tokens, n.completion_tokens = $completion_tokens, "
                    "n.status = $status "
                    "ON MATCH SET n.name = $name, n.turn = $turn, "
                    "n.start_time = $start_time, n.end_time = $end_time, "
                    "n.total_cost = $total_cost, n.total_tokens = $total_tokens, "
                    "n.prompt_tokens = $prompt_tokens, n.completion_tokens = $completion_tokens, "
                    "n.status = $status",
                    parameters={
                        "trace_id": trace_id_val,
                        "thread_id": thread_id,
                        "name": trace_id_val,
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
                continue

            if ntype == "chain":
                db.create(
                    f"MERGE (n:{label} {{run_id: $run_id, thread_id: $thread_id}}) "
                    f"ON CREATE SET n.name = $name, n.type = $type, "
                    f"n.parent_run_id = $parent_run_id, n.start_time = $start_time, n.status = $status "
                    f"ON MATCH SET n.name = $name, n.type = $type, "
                    f"n.parent_run_id = $parent_run_id, n.start_time = $start_time, n.status = $status",
                    parameters={
                        "run_id": nd.get("run_id", ""),
                        "thread_id": thread_id,
                        "name": node_name,
                        "type": ntype,
                        "parent_run_id": nd.get("parent_run_id", ""),
                        "start_time": nd.get("start_time", ""),
                        "status": nd.get("status") or "",
                    },
                )
                continue

            # Boundary, Agent, Tool — MERGE on (name, thread_id); aggregated counters + NodeStatus placeholders
            invocations = nd.get("invocations", [])
            invocation_count = len(invocations)
            error_count = sum(1 for iv in invocations if iv.get("error"))
            last_seen = ""
            if invocations:
                last_seen = max(str(iv.get("start_time") or "") for iv in invocations)
            total_cost = sum(iv.get("total_cost", 0) or 0 for iv in invocations)
            total_tokens = sum(iv.get("total_tokens", 0) or 0 for iv in invocations)
            prompt_tokens = sum(iv.get("prompt_tokens", 0) or 0 for iv in invocations)
            completion_tokens = sum(
                iv.get("completion_tokens", 0) or 0 for iv in invocations
            )
            prompt_cost = sum(iv.get("prompt_cost", 0) or 0 for iv in invocations)
            completion_cost = sum(
                iv.get("completion_cost", 0) or 0 for iv in invocations
            )
            available_tools = AGENT_AVAILABLE_TOOLS.get(node_name, [])

            db.create(
                f"MERGE (n:{label} {{name: $name, thread_id: $thread_id}}) "
                f"ON CREATE SET n.type = $type, n.invocation_count = $invocation_count, n.error_count = $error_count, "
                f"n.last_seen = $last_seen, n.total_cost = $total_cost, n.total_tokens = $total_tokens, "
                f"n.prompt_tokens = $prompt_tokens, n.completion_tokens = $completion_tokens, "
                f"n.prompt_cost = $prompt_cost, n.completion_cost = $completion_cost, n.available_tools = $available_tools, "
                f"n.node_risk_score = $node_risk_score, n.node_risk_label = $node_risk_label, "
                f"n.node_anomaly_types = $node_anomaly_types, n.node_last_scanned_at = $node_last_scanned_at "
                f"ON MATCH SET n.type = $type, n.invocation_count = $invocation_count, n.error_count = $error_count, "
                f"n.last_seen = $last_seen, n.total_cost = $total_cost, n.total_tokens = $total_tokens, "
                f"n.prompt_tokens = $prompt_tokens, n.completion_tokens = $completion_tokens, "
                f"n.prompt_cost = $prompt_cost, n.completion_cost = $completion_cost, n.available_tools = $available_tools, "
                f"n.node_risk_score = $node_risk_score, n.node_risk_label = $node_risk_label, "
                f"n.node_anomaly_types = $node_anomaly_types, n.node_last_scanned_at = $node_last_scanned_at",
                parameters={
                    "name": node_name,
                    "thread_id": thread_id,
                    "type": ntype,
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

        # Relationships
        _REL_TYPE = {
            "routing": "ROUTES_TO",
            "tool_call": "CALLS_TOOL",
            "contains": "CONTAINS",
            "has_trace": "HAS_TRACE",
            "has_thread": "HAS_THREAD",
        }

        for u, v, _key, data in G.edges(data=True, keys=True):
            etype = data.get("type", "routing")
            rel_type = _REL_TYPE.get(etype, "ROUTES_TO")

            if etype == "has_thread":
                db.create(
                    """MATCH (session:Session {session_id: $session_id}),
                             (thread:Thread {thread_id: $thread_id})
                     MERGE (session)-[:HAS_THREAD]->(thread)""",
                    parameters={
                        "session_id": session_id,
                        "thread_id": thread_id,
                    },
                )
                continue

            if etype == "has_trace":
                trace_nd = G.nodes.get(v, {})
                db.create(
                    """MATCH (thread:Thread {thread_id: $thread_id}),
                             (trace:Trace {trace_id: $trace_id, thread_id: $thread_id})
                     MERGE (thread)-[r:HAS_TRACE]->(trace) SET r.turn = $turn""",
                    parameters={
                        "thread_id": thread_id,
                        "trace_id": trace_nd.get("trace_id", ""),
                        "turn": trace_nd.get("turn", 0),
                    },
                )
                continue

            if u == _session_node_key(session_id) or v == _session_node_key(session_id):
                continue
            if u == _thread_node_key(thread_id) or v == _thread_node_key(thread_id):
                continue

            # Trace → root chain: CONTAINS edge anchoring the hierarchy
            if etype == "contains" and u.startswith("__trace__:"):
                trace_nd = G.nodes.get(u, {})
                chain_nd = G.nodes.get(v, {})
                db.create(
                    """MATCH (trace:Trace {trace_id: $trace_id, thread_id: $thread_id}),
                             (chain:Chain {run_id: $run_id, thread_id: $thread_id})
                     MERGE (trace)-[r:CONTAINS]->(chain) SET r.turn = $turn""",
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
                # Distinct relationship per invocation (MERGE on edge_id) + EdgeStatus/flow fields
                db.create(
                    f"""MATCH (a {{name: $src, thread_id: $thread_id}}),
                             (b {{name: $tgt, thread_id: $thread_id}})
                    MERGE (a)-[r:{rel_type} {{edge_id: $edge_id}}]->(b)
                    SET r.turn = $turn, r.start_time = $start_time, r.seq_no = $seq_no,
                        r.source_run_id = $source_run_id, r.target_run_id = $target_run_id,
                        r.inputs_hash = $inputs_hash, r.outputs_hash = $outputs_hash,
                        r.inputs_len = $inputs_len, r.outputs_len = $outputs_len,
                        r.source_trust = $source_trust, r.target_privilege = $target_privilege,
                        r.cross_boundary = $cross_boundary, r.args_hash = $args_hash,
                        r.edge_risk_score = $edge_risk_score, r.edge_risk_label = $edge_risk_label,
                        r.edge_flow_flags = $edge_flow_flags, r.edge_last_scanned_at = $edge_last_scanned_at""",
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
                # CONTAINS or other edges without edge_id
                db.create(
                    f"""MATCH (a {{name: $src, thread_id: $thread_id}}),
                             (b {{name: $tgt, thread_id: $thread_id}})
                    MERGE (a)-[r:{rel_type}]->(b)
                    SET r.turn = $turn, r.start_time = $start_time""",
                    parameters={
                        "src": u,
                        "tgt": v,
                        "thread_id": thread_id,
                        "turn": data.get("turn", 0),
                        "start_time": data.get("start_time", ""),
                    },
                )

        # Trace -[:COVERS]-> Agent/Tool/Boundary (trace has trace_id; others have name)
        for trace_id, covered in self._trace_covers.items():
            for node_name in covered:
                if node_name not in G:
                    continue
                trace_nd = G.nodes.get(_trace_node_key(trace_id))
                if not trace_nd:
                    continue
                db.create(
                    """MATCH (trace:Trace {trace_id: $trace_id, thread_id: $thread_id}),
                             (n {name: $node_name, thread_id: $thread_id})
                     MERGE (trace)-[:COVERS]->(n)""",
                    parameters={
                        "trace_id": trace_id,
                        "thread_id": thread_id,
                        "node_name": node_name,
                    },
                )

        logger.info(
            "Saved thread %s… — %s nodes, %s edges",
            thread_id[:16],
            G.order(),
            G.size(),
        )


def clear_graph_db(db: GraphDB) -> None:
    """Delete ALL nodes and relationships from the Neo4j database in batches."""
    while True:
        summary = db.create(
            "MATCH (n) WITH n LIMIT 1000 DETACH DELETE n RETURN count(*) AS deleted"
        )
        deleted = getattr(summary, "counters", None)
        nodes_deleted = getattr(deleted, "nodes_deleted", None) if deleted else None
        if nodes_deleted == 0:
            break
    logger.info("Graph DB cleared.")
