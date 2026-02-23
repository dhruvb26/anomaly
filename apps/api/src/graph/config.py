"""Sentinel configuration loaded from config.yaml."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config.yaml"


@dataclass(slots=True)
class GuardianConfig:
    enabled: bool = True
    model: str = "ibm/granite3.3-guardian:8b"
    base_url: str = "http://localhost:11434"
    confidence_threshold: float = 0.5


@dataclass(slots=True)
class PromptGuardConfig:
    enabled: bool = True


@dataclass(slots=True)
class AlignmentCheckConfig:
    enabled: bool = True


@dataclass(slots=True)
class FirewallConfig:
    enabled: bool = True
    prompt_guard: PromptGuardConfig = field(default_factory=PromptGuardConfig)
    alignment_check: AlignmentCheckConfig = field(default_factory=AlignmentCheckConfig)


@dataclass(slots=True)
class GraphConfig:
    include_chain_runs: bool = False


@dataclass(slots=True)
class ResourceBaselineConfig:
    enabled: bool = True
    z_threshold: float = 2.5
    min_samples: int = 3


@dataclass(slots=True)
class AgentHint:
    keyword: str = ""
    name: str = ""


@dataclass(slots=True)
class SentinelConfig:
    guardian: GuardianConfig = field(default_factory=GuardianConfig)
    firewall: FirewallConfig = field(default_factory=FirewallConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)
    resource_baselines: ResourceBaselineConfig = field(default_factory=ResourceBaselineConfig)
    agent_hints: list[AgentHint] = field(default_factory=list)
    sub_agents: list[str] = field(default_factory=list)

    @property
    def agent_system_prompt_hints(self) -> list[tuple[str, str]]:
        return [(h.keyword, h.name) for h in self.agent_hints]

    @property
    def sub_agents_set(self) -> frozenset[str]:
        return frozenset(self.sub_agents)


def _load_config(path: Path = _CONFIG_PATH) -> SentinelConfig:
    """Load and validate config.yaml, returning a SentinelConfig."""
    if not path.exists():
        logger.warning("Config file not found at %s — using defaults", path)
        return SentinelConfig()

    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        logger.exception("Failed to parse %s — using defaults", path)
        return SentinelConfig()

    sentinel = raw.get("sentinel", {})

    guardian_raw = sentinel.get("guardian", {})
    guardian = GuardianConfig(
        enabled=guardian_raw.get("enabled", True),
        model=guardian_raw.get("model", GuardianConfig.model),
        base_url=guardian_raw.get("base_url", GuardianConfig.base_url),
        confidence_threshold=guardian_raw.get(
            "confidence_threshold", GuardianConfig.confidence_threshold
        ),
    )

    fw_raw = sentinel.get("firewall", {})
    pg_raw = fw_raw.get("prompt_guard", {})
    ac_raw = fw_raw.get("alignment_check", {})
    firewall = FirewallConfig(
        enabled=fw_raw.get("enabled", True),
        prompt_guard=PromptGuardConfig(enabled=pg_raw.get("enabled", True)),
        alignment_check=AlignmentCheckConfig(enabled=ac_raw.get("enabled", True)),
    )

    graph_raw = sentinel.get("graph", {})
    graph = GraphConfig(include_chain_runs=graph_raw.get("include_chain_runs", False))

    rb_raw = sentinel.get("resource_baselines", {})
    resource_baselines = ResourceBaselineConfig(
        enabled=rb_raw.get("enabled", True),
        z_threshold=float(rb_raw.get("z_threshold", 2.5)),
        min_samples=int(rb_raw.get("min_samples", 3)),
    )

    hints_raw = sentinel.get("agent_hints", [])
    agent_hints = [
        AgentHint(keyword=h.get("keyword", ""), name=h.get("name", ""))
        for h in hints_raw
        if h.get("keyword") and h.get("name")
    ]

    sub_agents = sentinel.get("sub_agents", [])

    return SentinelConfig(
        guardian=guardian,
        firewall=firewall,
        graph=graph,
        resource_baselines=resource_baselines,
        agent_hints=agent_hints,
        sub_agents=sub_agents,
    )


sentinel_config: SentinelConfig = _load_config()

# Convenience aliases used throughout the graph module
AGENT_SYSTEM_PROMPT_HINTS: list[tuple[str, str]] = sentinel_config.agent_system_prompt_hints
SUB_AGENTS: frozenset[str] = sentinel_config.sub_agents_set
INCLUDE_CHAIN_RUNS: bool = sentinel_config.graph.include_chain_runs
