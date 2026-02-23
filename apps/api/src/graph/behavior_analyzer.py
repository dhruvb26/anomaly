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
from src.graph.content_extractors import (
    context_messages_from_inputs,
    extract_edge_content,
    extract_path_sequence,
    first_genuine_user_content,
    tool_calls_from_llm_outputs,
)
from src.graph.guardian import GuardianClient
from src.graph.inference import (
    cross_boundary,
    infer_edges_named,
    is_boundary_key,
    node_key,
    source_trust,
    target_privilege,
)
from src.graph.llamafirewall_client import FirewallResult, LlamaFirewallClient
from src.graph.schemas import Node, Turn

logger = logging.getLogger(__name__)

_TIER_LABEL = {0: "CLEAN", 1: "GLOBAL ANOMALY", 2: "ANOMALY", 3: "ATTACK PATH MATCHED"}


@dataclass(slots=True)
class NodeStatus:
    """Status of a single node (agent or tool) in a turn."""

    node_key: str
    run_id: str
    is_anomalous: bool
    risk_type: str
    confidence: float
    details: str
    reasoning: str = ""


@dataclass(slots=True)
class EdgeStatus:
    """Status of an edge (cross-boundary and/or firewall check result)."""

    src_key: str
    tgt_key: str
    is_anomalous: bool
    risk_type: str
    confidence: float
    details: str
    reasoning: str = ""


@dataclass(slots=True)
class TurnAnalysis:
    """Analysis result for one turn."""

    turn_index: int
    node_statuses: list[NodeStatus] = field(default_factory=list)
    edge_statuses: list[EdgeStatus] = field(default_factory=list)
    path_matches: list[PathMatch] = field(default_factory=list)
    tier: int = 0


@dataclass(slots=True)
class AnalysisReport:
    """Aggregate report for a full thread (multiple turns)."""

    thread_id: str
    turn_analyses: list[TurnAnalysis] = field(default_factory=list)
    summary: str = ""
    recommendations: list[str] = field(default_factory=list)


class BehaviorAnalyzer:
    """Evaluates turns against Guardian, LlamaFirewall, and attack path library."""

    def __init__(
        self,
        guardian: GuardianClient,
        llamafirewall: LlamaFirewallClient | None = None,
        attack_paths: list[AttackPath] | None = None,
        strict_threshold: float = 0.3,
        payload_store=None,
    ):
        self.guardian = guardian
        self.llamafirewall = llamafirewall
        self.attack_paths = attack_paths if attack_paths is not None else MAGENTIC_ONE_ATTACK_PATHS
        self.strict_threshold = strict_threshold
        self.payload_store = payload_store

    def _analyze_llm_node(
        self, node: Node, nk: str, confidence_threshold: float
    ) -> NodeStatus:
        """Guardian checks: jailbreak (orchestrator only) + hallucination."""
        run_id = node.id or ""
        anomalies: list[str] = []
        reasoning_parts: list[str] = []
        max_confidence = 0.0
        risk_type = ""

        if nk == "orchestrator":
            msgs = (node.inputs or {}).get("messages") or []
            if isinstance(msgs, list) and msgs and isinstance(msgs[0], list):
                msgs = msgs[0]
            user_content = first_genuine_user_content(msgs) if msgs else ""
            if user_content:
                res = self.guardian.check_jailbreak(user_content)
                if res.reason:
                    reasoning_parts.append(f"[jailbreak] {res.reason}")
                if res.is_anomalous:
                    anomalies.append(f"jailbreak:{res.reason[:100]}")
                    max_confidence = max(max_confidence, res.confidence)
                    risk_type = res.risk_type or risk_type

        context = context_messages_from_inputs(node)
        for tool_name, tool_args in tool_calls_from_llm_outputs(node):
            res = self.guardian.check_function_calling_hallucination(
                tool_name, tool_args, context
            )
            if res.reason:
                reasoning_parts.append(f"[hallucination:{tool_name}] {res.reason}")
            if res.is_anomalous:
                anomalies.append(f"hallucination:{tool_name}:{res.reason[:80]}")
                max_confidence = max(max_confidence, res.confidence)
                risk_type = risk_type or res.risk_type

        return NodeStatus(
            node_key=nk,
            run_id=run_id,
            is_anomalous=bool(anomalies),
            risk_type=risk_type or "llm",
            confidence=max_confidence,
            details="; ".join(anomalies) if anomalies else "ok",
            reasoning="\n".join(reasoning_parts),
        )

    def _analyze_tool_node(
        self, node: Node, nk: str, prev_source_trust: str
    ) -> NodeStatus:
        """Cross-boundary check from low-trust source to high-privilege tool."""
        target_priv = target_privilege(nk)
        cross_bnd = cross_boundary(prev_source_trust, target_priv)
        return NodeStatus(
            node_key=nk,
            run_id=node.id or "",
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
        """Cross-boundary check plus optional LlamaFirewall scans."""
        cross_bnd = attrs.get("cross_boundary", False)
        content = extract_edge_content(attrs, edge_type, payload_store=self.payload_store)
        reasoning_parts: list[str] = []

        if self.llamafirewall:
            pg_result: FirewallResult = self.llamafirewall.check_prompt_injection(content)
            if pg_result.reason:
                reasoning_parts.append(f"[prompt_guard] {pg_result.reason}")
            if edge_type == "routing":
                al_result = self.llamafirewall.check_alignment(user_query, history, content)
                if al_result.reason:
                    reasoning_parts.append(f"[alignment] {al_result.reason}")
                lf_anomalous = pg_result.is_anomalous or al_result.is_anomalous
                lf_risk = (pg_result.risk_type or al_result.risk_type or "alignment") if lf_anomalous else ""
                lf_confidence = max(pg_result.score, al_result.score)
                lf_details = "; ".join(filter(None, [
                    pg_result.reason if pg_result.is_anomalous else None,
                    al_result.reason if al_result.is_anomalous else None,
                ])) or "ok"
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
            src_key=src_key, tgt_key=tgt_key, is_anomalous=is_anomalous,
            risk_type=risk_type, confidence=confidence, details=details,
            reasoning="\n".join(reasoning_parts),
        )

    def _analyze_nodes(self, turn: Turn, confidence_threshold: float) -> tuple[list[NodeStatus], str]:
        """Analyze all nodes in a turn."""
        node_statuses: list[NodeStatus] = []
        prev_trust = "system"
        for node in turn.nodes:
            nk = node_key(node)
            if is_boundary_key(nk):
                continue
            logger.debug("Analyzing node [%s] (%s)", nk, node.type or "unknown")
            if node.type == "llm":
                ns = self._analyze_llm_node(node, nk, confidence_threshold)
            else:
                ns = self._analyze_tool_node(node, nk, prev_trust)
            logger.debug(
                "Node [%s] -> %s risk=%s conf=%.2f",
                nk, "ANOMALOUS" if ns.is_anomalous else "ok",
                ns.risk_type or "-", ns.confidence,
            )
            node_statuses.append(ns)
            prev_trust = source_trust(node) if node.type == "tool" else "system"
        return node_statuses, prev_trust

    def _analyze_edges(self, turn: Turn, trace_id: str) -> list[EdgeStatus]:
        """Analyze all edges in a turn."""
        edges = infer_edges_named(turn, trace_id=str(trace_id))
        user_query = ""
        history: list[dict] = []
        for node in turn.nodes:
            if node_key(node) == "orchestrator":
                msgs = (node.inputs or {}).get("messages") or []
                if isinstance(msgs, list) and msgs and isinstance(msgs[0], list):
                    msgs = msgs[0]
                user_query = first_genuine_user_content(msgs) if msgs else ""
                history = context_messages_from_inputs(node)
                break
        edge_statuses: list[EdgeStatus] = []
        for src_key, tgt_key, attrs in edges:
            edge_type = attrs.get("type", "routing")
            logger.debug("Analyzing edge [%s -> %s] (%s)", src_key, tgt_key, edge_type)
            es = self._analyze_edge(src_key, tgt_key, edge_type, attrs, user_query, history)
            logger.debug(
                "Edge [%s -> %s] -> %s risk=%s conf=%.2f",
                src_key, tgt_key,
                "ANOMALOUS" if es.is_anomalous else "ok",
                es.risk_type or "-", es.confidence,
            )
            edge_statuses.append(es)
        return edge_statuses

    def analyze_turn(self, turn: Turn) -> TurnAnalysis:
        """Run node/edge status and path matching for one turn."""
        trace_id = turn.trace_id or turn.root_chain_id or ""
        path_sequence = extract_path_sequence(turn)
        path_matches = match_attack_paths(path_sequence, self.attack_paths)
        use_strict = len(path_matches) > 0
        threshold = self.strict_threshold if use_strict else self.guardian.confidence_threshold
        node_statuses, _ = self._analyze_nodes(turn, threshold)
        edge_statuses = self._analyze_edges(turn, trace_id)
        has_node_anomaly = any(ns.is_anomalous for ns in node_statuses)
        has_edge_anomaly = any(es.is_anomalous for es in edge_statuses)
        if path_matches:
            tier = 3
        elif has_node_anomaly or has_edge_anomaly:
            tier = 2
        else:
            tier = 0
        logger.info(
            "Turn %d analysis: tier=%d (%s) nodes=%d edges=%d paths=%d",
            turn.index, tier, _TIER_LABEL.get(tier, str(tier)),
            len(node_statuses), len(edge_statuses), len(path_matches),
        )
        return TurnAnalysis(
            turn_index=turn.index,
            node_statuses=node_statuses,
            edge_statuses=edge_statuses,
            path_matches=path_matches,
            tier=tier,
        )

    def analyze_thread(self, turns: list[Turn], thread_id: str = "") -> AnalysisReport:
        """Analyze all turns and produce an aggregate report."""
        turn_analyses = [self.analyze_turn(t) for t in turns]
        max_tier = max((t.tier for t in turn_analyses), default=0)
        if max_tier >= 3:
            summary = "Multi-point anomaly: attack path(s) matched."
            recommendations = [
                "Review matched attack paths and node/edge statuses.",
                "Consider constraining orchestrator delegation to code_executor after retrieval.",
            ]
        elif max_tier == 2:
            summary = "Single-point anomaly: node/edge status anomalies detected."
            recommendations = [
                "Inspect node_statuses and edge_statuses for details.",
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
