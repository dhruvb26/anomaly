"""Behavior Analyzer: node/edge status and attack path matching over Turn data."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.graph.attack_paths import (
    MAGENTIC_ONE_ATTACK_PATHS,
    AttackPath,
    PathMatch,
    match_attack_paths,
)
from src.graph.guardian import GuardianClient
from src.graph.llamafirewall_client import FirewallResult, LlamaFirewallClient
from src.graph.inference import (
    cross_boundary,
    infer_edges_named,
    is_boundary_key,
    node_key,
    source_trust,
    target_privilege,
)
from src.graph.schemas import Node, Turn

logger = logging.getLogger(__name__)


@dataclass
class NodeStatus:
    """Status of a single node (agent or tool) in a turn."""

    node_key: str
    run_id: str
    is_anomalous: bool
    risk_type: str
    confidence: float
    details: str


@dataclass
class EdgeStatus:
    """Status of an edge (cross-boundary and/or LlamaFirewall prompt-injection/alignment)."""

    src_key: str
    tgt_key: str
    is_anomalous: bool
    risk_type: str
    confidence: float
    details: str


@dataclass
class TurnAnalysis:
    """Analysis result for one turn."""

    turn_index: int
    node_statuses: list[NodeStatus] = field(default_factory=list)
    edge_statuses: list[EdgeStatus] = field(default_factory=list)
    path_matches: list[PathMatch] = field(default_factory=list)
    tier: int = 0  # 0=clean, 1=global, 2=single-point, 3=multi-point


@dataclass
class AnalysisReport:
    """Aggregate report for a full thread (multiple turns)."""

    thread_id: str
    turn_analyses: list[TurnAnalysis] = field(default_factory=list)
    summary: str = ""
    recommendations: list[str] = field(default_factory=list)


def _extract_path_sequence(turn: Turn) -> list[str]:
    """Ordered list of agent/tool node keys from the turn (boundary nodes excluded)."""
    trace_id = (
        getattr(turn, "trace_id", None) or getattr(turn, "root_chain_id", None) or ""
    )
    edges = infer_edges_named(turn, trace_id=str(trace_id))
    if not edges:
        return []
    path_keys = [edges[0][0]] + [tgt for (_, tgt, _) in edges]
    return [k for k in path_keys if not is_boundary_key(k)]


def _first_genuine_user_content(messages: list) -> str:
    """
    Extract the first genuine user message (not an agent-generated routing message).

    In LangGraph, orchestrator adds HumanMessage(content=..., name="orchestrator")
    to route sub-agents. Those have a non-empty `name` field in the serialized form.
    The real user query has no `name` (or name is None/empty).
    We iterate forward to get the original user turn, not the last accumulated one.
    """
    for m in messages:
        if isinstance(m, list):
            content = _first_genuine_user_content(m)
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


def _tool_calls_from_llm_outputs(node: Node) -> list[tuple[str, dict]]:
    """(tool_name, args) for each tool call in the LLM node outputs."""
    out = getattr(node, "outputs", None) or {}
    try:
        gens = out.get("generations") or []
        if not gens or not gens[0]:
            return []
        msg = gens[0][0].get("message", {})
        kwargs = msg.get("kwargs", {})
        result = []
        for tc in kwargs.get("tool_calls") or []:
            name = tc.get("name") or "tool"
            args = tc.get("args") or {}
            result.append((name, args))
        return result
    except (IndexError, KeyError, TypeError):
        return []


def _context_messages_from_inputs(node: Node) -> list[dict]:
    """Serialize input messages for Guardian context (truncated)."""
    inp = getattr(node, "inputs", None) or {}
    msgs = inp.get("messages") or []
    if not msgs:
        return []
    if isinstance(msgs[0], list):
        msgs = msgs[0]
    out = []
    for m in msgs[:15]:
        if isinstance(m, dict):
            out.append(
                {
                    "role": m.get("kwargs", m).get("type", "unknown"),
                    "content": str(m)[:500],
                }
            )
    return out


def _extract_edge_content(attrs: dict, edge_type: str) -> str:
    """Content flowing along the edge: for routing use outputs_preview, for tool_call use inputs_preview."""
    key = "outputs_preview" if edge_type == "routing" else "inputs_preview"
    content = attrs.get(key) or ""
    return content if isinstance(content, str) else str(content)


class BehaviorAnalyzer:
    """
    Evaluates Turn(s) against Guardian (node status), LlamaFirewall (edge status),
    and attack path library (path matching).
    """

    def __init__(
        self,
        guardian: GuardianClient,
        llamafirewall: LlamaFirewallClient | None = None,
        attack_paths: list[AttackPath] | None = None,
        strict_threshold: float = 0.3,
    ):
        self.guardian = guardian
        self.llamafirewall = llamafirewall
        self.attack_paths = (
            attack_paths if attack_paths is not None else MAGENTIC_ONE_ATTACK_PATHS
        )
        self.strict_threshold = strict_threshold

    def _analyze_llm_node(self, node: Node, node_key: str) -> NodeStatus:
        """
        Guardian checks for an LLM node:
        - Jailbreak: only on the orchestrator (sole entry point for real user input).
          Uses the first nameless human message to avoid false positives from
          orchestrator routing HumanMessages (which have name="orchestrator").
        - Function-calling hallucination: on all LLM nodes that make tool calls.
        """
        run_id = str(getattr(node, "id", "") or "")
        anomalies: list[str] = []
        max_confidence = 0.0
        risk_type = ""

        # Jailbreak check — orchestrator only, first genuine user message only
        if node_key == "orchestrator":
            inp = getattr(node, "inputs", None) or {}
            msgs = inp.get("messages") or []
            if isinstance(msgs, list) and msgs and isinstance(msgs[0], list):
                msgs = msgs[0]
            user_content = _first_genuine_user_content(msgs) if msgs else ""
            if user_content:
                res = self.guardian.check_jailbreak(user_content)
                if res.is_anomalous:
                    anomalies.append(f"jailbreak:{res.reason[:100]}")
                    max_confidence = max(max_confidence, res.confidence)
                    risk_type = res.risk_type or risk_type

        # Function-calling hallucination on each tool call (all LLM nodes)
        context = _context_messages_from_inputs(node)
        for tool_name, tool_args in _tool_calls_from_llm_outputs(node):
            res = self.guardian.check_function_calling_hallucination(
                tool_name, tool_args, context
            )
            if res.is_anomalous:
                anomalies.append(f"hallucination:{tool_name}:{res.reason[:80]}")
                max_confidence = max(max_confidence, res.confidence)
                risk_type = risk_type or res.risk_type

        return NodeStatus(
            node_key=node_key,
            run_id=run_id,
            is_anomalous=len(anomalies) > 0,
            risk_type=risk_type or "llm",
            confidence=max_confidence,
            details="; ".join(anomalies) if anomalies else "ok",
        )

    def _analyze_tool_node(
        self,
        node: Node,
        node_key: str,
        prev_source_trust: str,
    ) -> NodeStatus:
        """Structural check: cross-boundary from low-trust source to high-privilege tool."""
        target_priv = target_privilege(node_key)
        cross_bnd = cross_boundary(prev_source_trust, target_priv)
        return NodeStatus(
            node_key=node_key,
            run_id=str(getattr(node, "id", "") or ""),
            is_anomalous=cross_bnd,
            risk_type="cross_boundary" if cross_bnd else "tool",
            confidence=0.8 if cross_bnd else 0.0,
            details="low_trust_to_high_privilege" if cross_bnd else "ok",
        )

    def _analyze_edge(
        self,
        src_key: str,
        tgt_key: str,
        edge_type: str,
        attrs: dict,
        user_query: str,
        history: list[dict],
    ) -> EdgeStatus:
        """Cross-boundary check plus optional LlamaFirewall prompt-injection/alignment."""
        cross_bnd = attrs.get("cross_boundary", False)
        content = _extract_edge_content(attrs, edge_type)

        if self.llamafirewall:
            pg_result: FirewallResult = self.llamafirewall.check_prompt_injection(
                content
            )
            if edge_type == "routing":
                al_result = self.llamafirewall.check_alignment(
                    user_query, history, content
                )
                lf_anomalous = pg_result.is_anomalous or al_result.is_anomalous
                lf_risk = (
                    pg_result.risk_type or al_result.risk_type or "alignment"
                    if lf_anomalous
                    else ""
                )
                lf_confidence = max(pg_result.score, al_result.score)
                lf_details = "; ".join(
                    filter(
                        None,
                        [
                            pg_result.reason if pg_result.is_anomalous else None,
                            al_result.reason if al_result.is_anomalous else None,
                        ],
                    )
                ) or "ok"
            else:
                lf_anomalous = pg_result.is_anomalous
                lf_risk = pg_result.risk_type
                lf_confidence = pg_result.score
                lf_details = pg_result.reason if pg_result.is_anomalous else "ok"
        else:
            lf_anomalous = False
            lf_risk = ""
            lf_confidence = 0.0
            lf_details = "ok"

        is_anomalous = cross_bnd or lf_anomalous
        if cross_bnd and lf_anomalous:
            risk_type = "cross_boundary; " + (lf_risk or "prompt_injection")
            details = "low_trust_source_to_high_privilege_target; " + lf_details
            confidence = max(0.8, lf_confidence)
        elif cross_bnd:
            risk_type = "cross_boundary"
            details = "low_trust_source_to_high_privilege_target"
            confidence = 0.8
        else:
            risk_type = lf_risk or "edge"
            details = lf_details
            confidence = lf_confidence

        return EdgeStatus(
            src_key=src_key,
            tgt_key=tgt_key,
            is_anomalous=is_anomalous,
            risk_type=risk_type,
            confidence=confidence,
            details=details,
        )

    def analyze_turn(self, turn: Turn) -> TurnAnalysis:
        """Run node/edge status and path matching for one turn."""
        trace_id = (
            getattr(turn, "trace_id", None)
            or getattr(turn, "root_chain_id", None)
            or ""
        )
        edges = infer_edges_named(turn, trace_id=str(trace_id))
        path_sequence = _extract_path_sequence(turn)
        path_matches = match_attack_paths(path_sequence, self.attack_paths)
        use_strict = len(path_matches) > 0
        old_threshold = self.guardian.confidence_threshold
        if use_strict:
            self.guardian.confidence_threshold = self.strict_threshold

        node_statuses: list[NodeStatus] = []
        edge_statuses: list[EdgeStatus] = []
        prev_trust = "system"

        try:
            for i, node in enumerate(turn.nodes):
                nk = node_key(node)
                if is_boundary_key(nk):
                    continue
                node_type = getattr(node, "type", None)
                logger.info("  Analyzing node [%s] (%s) …", nk, node_type or "unknown")
                if node_type == "llm":
                    ns = self._analyze_llm_node(node, nk)
                else:
                    ns = self._analyze_tool_node(node, nk, prev_trust)
                status_str = "ANOMALOUS" if ns.is_anomalous else "ok"
                logger.info(
                    "  Node [%s] → %s  risk=%s  conf=%.2f  details=%s",
                    nk,
                    status_str,
                    ns.risk_type or "-",
                    ns.confidence,
                    ns.details,
                )
                node_statuses.append(ns)
                if node_type == "tool":
                    prev_trust = source_trust(node)
                else:
                    prev_trust = "system"
        finally:
            if use_strict:
                self.guardian.confidence_threshold = old_threshold

        user_query = ""
        history: list[dict] = []
        for node in turn.nodes:
            nk = node_key(node)
            if nk == "orchestrator":
                inp = getattr(node, "inputs", None) or {}
                msgs = inp.get("messages") or []
                if isinstance(msgs, list) and msgs and isinstance(msgs[0], list):
                    msgs = msgs[0]
                user_query = _first_genuine_user_content(msgs) if msgs else ""
                history = _context_messages_from_inputs(node)
                break

        for src_key, tgt_key, attrs in edges:
            edge_type = attrs.get("type", "routing")
            logger.info("  Analyzing edge [%s → %s] (%s) …", src_key, tgt_key, edge_type)
            es = self._analyze_edge(
                src_key, tgt_key, edge_type, attrs, user_query, history
            )
            status_str = "ANOMALOUS" if es.is_anomalous else "ok"
            logger.info(
                "  Edge [%s → %s] → %s  risk=%s  conf=%.2f",
                src_key,
                tgt_key,
                status_str,
                es.risk_type or "-",
                es.confidence,
            )
            edge_statuses.append(es)

        # Tier: 3 = path match, 2 = single node/edge anomaly, 1 = global
        has_node_anomaly = any(ns.is_anomalous for ns in node_statuses)
        has_edge_anomaly = any(es.is_anomalous for es in edge_statuses)
        if path_matches:
            tier = 3
        elif has_node_anomaly or has_edge_anomaly:
            tier = 2
        else:
            tier = 0

        _TIER_LABEL = {0: "CLEAN", 1: "GLOBAL ANOMALY", 2: "ANOMALY", 3: "ATTACK PATH MATCHED"}
        logger.info(
            "Turn %d analysis complete — tier=%d (%s)  nodes=%d  edges=%d  paths=%d",
            turn.index,
            tier,
            _TIER_LABEL.get(tier, str(tier)),
            len(node_statuses),
            len(edge_statuses),
            len(path_matches),
        )
        return TurnAnalysis(
            turn_index=turn.index,
            node_statuses=node_statuses,
            edge_statuses=edge_statuses,
            path_matches=path_matches,
            tier=tier,
        )

    def analyze_thread(
        self,
        turns: list[Turn],
        thread_id: str = "",
    ) -> AnalysisReport:
        """Analyze all turns and produce an aggregate report."""
        turn_analyses = [self.analyze_turn(t) for t in turns]
        max_tier = max((t.tier for t in turn_analyses), default=0)
        if max_tier >= 3:
            summary = "Multi-point anomaly: attack path(s) matched; review path_matches and node/edge statuses."
            recommendations = [
                "Review matched attack paths and re-check node/edge status with strict threshold.",
                "Consider constraining orchestrator delegation to code_executor after retrieval.",
            ]
        elif max_tier == 2:
            summary = (
                "Single-point anomaly: one or more node/edge status anomalies detected."
            )
            recommendations = [
                "Inspect node_statuses and edge_statuses for risk_type and details.",
                "Tighten input validation or tool permissions if repeated.",
            ]
        elif max_tier == 1:
            summary = "Global anomaly: task-level or terminal failure suspected."
            recommendations = ["Review final output and terminal node behavior."]
        else:
            summary = "No anomaly detected."
            recommendations = []

        return AnalysisReport(
            thread_id=thread_id,
            turn_analyses=turn_analyses,
            summary=summary,
            recommendations=recommendations,
        )
