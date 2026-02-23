"""Graph domain models: Node, Edge, Turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Literal

SELECT_FIELDS = [
    "id",
    "start_time",
    "events",
    "error",
    "run_type",
    "inputs",
    "outputs",
    "status",
    "session_id",
    "trace_id",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "prompt_cost",
    "completion_cost",
    "total_cost",
    "parent_run_id",
]


@dataclass(slots=True)
class Node:
    """A single LLM or tool run extracted from a LangSmith trace."""

    SUPPORTED_TYPES: ClassVar[tuple[str, ...]] = ("tool", "llm")

    id: str
    type: str | None = None
    start_time: str | None = None
    events: list | None = None
    error: str | None = None
    inputs: dict | None = None
    outputs: dict | None = None
    status: str | None = None
    session_id: str | None = None
    trace_id: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_cost: float = 0.0
    completion_cost: float = 0.0
    total_cost: float = 0.0
    parent_run_id: str | None = None
    children: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.type is not None and self.type not in self.SUPPORTED_TYPES:
            raise ValueError(
                f"run_type must be one of {self.SUPPORTED_TYPES}, got {self.type!r}"
            )

    @classmethod
    def from_dict(cls, d: dict) -> Node:
        """Build a Node from a LangSmith run dict."""
        run_id = d.get("id")
        if run_id is None:
            raise ValueError("Run dict must have an 'id'")
        run_type = d.get("run_type")
        if run_type not in cls.SUPPORTED_TYPES:
            raise ValueError(
                f"Only run_type {cls.SUPPORTED_TYPES} are supported, got {run_type!r}"
            )
        return cls(
            id=str(run_id),
            type=run_type,
            start_time=d.get("start_time"),
            events=d.get("events"),
            error=d.get("error"),
            inputs=d.get("inputs"),
            outputs=d.get("outputs"),
            status=d.get("status"),
            session_id=d.get("session_id"),
            trace_id=d.get("trace_id"),
            prompt_tokens=d.get("prompt_tokens") or 0,
            completion_tokens=d.get("completion_tokens") or 0,
            total_tokens=d.get("total_tokens") or 0,
            prompt_cost=d.get("prompt_cost") or 0.0,
            completion_cost=d.get("completion_cost") or 0.0,
            total_cost=d.get("total_cost") or 0.0,
            parent_run_id=d.get("parent_run_id"),
        )


EdgeType = Literal["routing", "tool_call"]


@dataclass(slots=True)
class Edge:
    """An invocation (parent -> child run) and message passing in the agent graph."""

    EDGE_TYPES: ClassVar[tuple[EdgeType, ...]] = ("routing", "tool_call")

    source_id: str
    target_id: str
    type: EdgeType
    payload: dict = field(default_factory=dict)
    edge_id: str | None = None

    def __post_init__(self) -> None:
        if self.type not in self.EDGE_TYPES:
            raise ValueError(f"type must be one of {self.EDGE_TYPES}, got {self.type!r}")

    def __repr__(self) -> str:
        return f"Edge({self.source_id!r} -> {self.target_id!r}, type={self.type!r})"

    @classmethod
    def from_dict(cls, d: dict) -> Edge:
        source_id = d.get("source_id")
        target_id = d.get("target_id")
        if not source_id or not target_id:
            raise ValueError("Edge dict must have 'source_id' and 'target_id'")
        type_val = d.get("type")
        if type_val not in cls.EDGE_TYPES:
            raise ValueError(
                f"Edge dict 'type' must be one of {cls.EDGE_TYPES}, got {type_val!r}"
            )
        return cls(
            source_id=str(source_id),
            target_id=str(target_id),
            type=type_val,
            payload=d.get("payload") or {},
            edge_id=d.get("edge_id"),
        )


@dataclass(slots=True)
class Turn:
    """One turn's worth of meaningful runs (llm + tool only), sorted by start_time."""

    index: int
    nodes: list[Node]
    start_time: str = ""
    end_time: str = ""
    chain_routings: list[dict] = field(default_factory=list)
    run_map: dict[str, dict] = field(default_factory=dict)
    root_id: str | None = None
    chain_runs: list[dict] = field(default_factory=list)
    trace_id: str = ""
    root_chain_id: str = ""
