"""Graph domain models: Node, Edge, Turn."""

from __future__ import annotations

from typing import Literal

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


class Node:
    """Node built from the same Run properties selected in process_thread (SELECT_FIELDS)."""

    SUPPORTED_TYPES = ("tool", "llm")

    __slots__ = (
        "id",
        "start_time",
        "events",
        "error",
        "type",
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
        "children",
    )

    def __init__(self, id: str, *, children=None, **kwargs):
        self.id = id
        self.children = list(children) if children is not None else []
        for key in SELECT_FIELDS:
            if key == "id":
                continue
            if key == "run_type":
                self.type = kwargs.get("run_type", None) or kwargs.get("type", None)
                continue
            setattr(self, key, kwargs.get(key, None))
        if self.type is not None and self.type not in self.SUPPORTED_TYPES:
            raise ValueError(
                f"run_type must be one of {self.SUPPORTED_TYPES}, got {self.type!r}"
            )

    @classmethod
    def from_dict(cls, d: dict) -> "Node":
        """Build a Node from a run dict."""
        run_id = d.get("id")
        if run_id is None:
            raise ValueError("Run dict must have an 'id'")
        run_type = d.get("run_type")
        if run_type not in cls.SUPPORTED_TYPES:
            raise ValueError(
                f"Only run_type {cls.SUPPORTED_TYPES} are supported, got {run_type!r}"
            )
        kwargs = {k: d[k] for k in SELECT_FIELDS if k in d and k != "id"}
        kwargs["type"] = kwargs.pop("run_type", None)
        return cls(id=str(run_id), **kwargs)


EdgeType = Literal["routing", "tool_call"]


class Edge:
    """Represents an invocation (parent → child run) and message passing in the agent graph."""

    EDGE_TYPES: tuple[EdgeType, ...] = ("routing", "tool_call")

    __slots__ = ("source_id", "target_id", "type", "payload", "edge_id")

    def __init__(
        self,
        source_id: str,
        target_id: str,
        *,
        type: EdgeType,
        payload: dict | None = None,
        edge_id: str | None = None,
    ):
        if type not in self.EDGE_TYPES:
            raise ValueError(f"type must be one of {self.EDGE_TYPES}, got {type!r}")
        self.source_id = source_id
        self.target_id = target_id
        self.type = type
        self.payload = payload if payload is not None else {}
        self.edge_id = edge_id

    def __repr__(self) -> str:
        return f"Edge({self.source_id!r} -> {self.target_id!r}, type={self.type!r})"

    @classmethod
    def from_dict(cls, d: dict) -> "Edge":
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
            payload=d.get("payload"),
            edge_id=d.get("edge_id"),
        )


class Turn:
    """One turn's worth of meaningful runs (llm + tool only), sorted by start_time."""

    __slots__ = (
        "index",
        "nodes",
        "start_time",
        "end_time",
        "chain_routings",
        "run_map",
        "root_id",
        "chain_runs",
        "trace_id",
        "root_chain_id",
    )

    def __init__(
        self,
        index: int,
        nodes: list[Node],
        start_time: str,
        end_time: str,
        chain_routings: list[dict] | None = None,
        run_map: dict[str, dict] | None = None,
        root_id: str | None = None,
        chain_runs: list[dict] | None = None,
        trace_id: str | None = None,
        root_chain_id: str | None = None,
    ):
        self.index = index
        self.nodes = nodes
        self.start_time = start_time
        self.end_time = end_time
        self.chain_routings = chain_routings if chain_routings is not None else []
        self.run_map = run_map if run_map is not None else {}
        self.root_id = root_id
        self.chain_runs = chain_runs if chain_runs is not None else []
        self.trace_id = trace_id or ""
        self.root_chain_id = root_chain_id or ""

