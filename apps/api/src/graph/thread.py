"""Thread: thin orchestrator wrapping graph building and persistence."""

from __future__ import annotations

import networkx as nx

from src.graph.builder import build_graph_from_turns
from src.graph.persistence import clear_graph_db, save_graph_to_db
from src.graph.schemas import Turn
from src.stores import GraphDB

__all__ = ["Thread", "clear_graph_db"]


class Thread:
    """Thread-level structural graph: agents/tools as nodes, invocations as edges."""

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
        self._trace_covers = trace_covers or {}

    @classmethod
    def from_turns(cls, thread_id: str, turns: list[Turn]) -> Thread:
        """Build a Thread graph from Turn instances."""
        if not turns:
            return cls(thread_id=thread_id, turns=[], G=nx.MultiDiGraph())
        G, session_id, trace_covers = build_graph_from_turns(thread_id, turns)
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
        """Persist the thread graph to Neo4j."""
        save_graph_to_db(
            db=db,
            G=self.G,
            thread_id=self.thread_id,
            session_id=self.session_id,
            trace_covers=self._trace_covers,
            turns=self.turns,
            payload_store=payload_store,
            available_tools=available_tools,
        )
