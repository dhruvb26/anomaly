"""Neo4j driver wrapper for graph persistence (Session, Thread, Trace, Agent, Tool)."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv(override=True)

logger = logging.getLogger(__name__)


class GraphDB:
    """Neo4j connection and schema helpers. Uses NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD."""

    def __init__(self) -> None:
        uri = os.getenv("NEO4J_URI")
        auth = (os.getenv("NEO4J_USERNAME"), os.getenv("NEO4J_PASSWORD"))
        if not uri:
            raise RuntimeError("NEO4J_URI is required")
        self.driver = GraphDatabase.driver(uri, auth=auth)

    def close(self) -> None:
        self.driver.close()

    def verify_connectivity(self) -> None:
        try:
            self.driver.verify_connectivity()
        except Exception:
            logger.exception("Neo4j verify_connectivity failed")
            raise

    def setup_schema(self, database_: str = "neo4j") -> None:
        """Create uniqueness constraints and indexes. Idempotent (IF NOT EXISTS)."""
        constraints_and_indexes = [
            "CREATE CONSTRAINT session_session_id IF NOT EXISTS FOR (n:Session) REQUIRE n.session_id IS UNIQUE",
            "CREATE CONSTRAINT thread_thread_id IF NOT EXISTS FOR (n:Thread) REQUIRE n.thread_id IS UNIQUE",
            "CREATE CONSTRAINT trace_trace_thread IF NOT EXISTS FOR (n:Trace) REQUIRE (n.trace_id, n.thread_id) IS UNIQUE",
            "CREATE INDEX agent_node_risk_score IF NOT EXISTS FOR (n:Agent) ON (n.node_risk_score)",
            "CREATE INDEX tool_node_risk_score IF NOT EXISTS FOR (n:Tool) ON (n.node_risk_score)",
            "CREATE INDEX agent_thread_id IF NOT EXISTS FOR (n:Agent) ON (n.thread_id)",
            "CREATE INDEX tool_thread_id IF NOT EXISTS FOR (n:Tool) ON (n.thread_id)",
            "CREATE INDEX routes_to_edge_id IF NOT EXISTS FOR ()-[r:ROUTES_TO]-() ON (r.edge_id)",
            "CREATE INDEX calls_tool_edge_id IF NOT EXISTS FOR ()-[r:CALLS_TOOL]-() ON (r.edge_id)",
            "CREATE INDEX routes_to_seq_no IF NOT EXISTS FOR ()-[r:ROUTES_TO]-() ON (r.seq_no)",
            "CREATE INDEX calls_tool_seq_no IF NOT EXISTS FOR ()-[r:CALLS_TOOL]-() ON (r.seq_no)",
            "CREATE INDEX routes_to_target_run_id IF NOT EXISTS FOR ()-[r:ROUTES_TO]-() ON (r.target_run_id)",
            "CREATE INDEX calls_tool_target_run_id IF NOT EXISTS FOR ()-[r:CALLS_TOOL]-() ON (r.target_run_id)",
        ]
        for cypher in constraints_and_indexes:
            try:
                self.driver.execute_query(cypher, database_=database_)
            except Exception as e:
                logger.debug("Schema step skipped or failed: %s", e)

    def query(
        self,
        query: str,
        parameters: dict | None = None,
        database_: str = "neo4j",
    ) -> list[dict]:
        """Execute a read query; return list of record dicts."""
        parameters = parameters or {}
        try:
            records, summary, _ = self.driver.execute_query(
                query,
                parameters_=parameters,
                database_=database_,
            )
        except Exception:
            logger.exception("Neo4j query failed")
            raise
        results = [record.data() for record in records]
        logger.debug(
            "Query returned %s records in %s ms",
            len(records),
            summary.result_available_after,
        )
        return results

    def create(
        self,
        query: str,
        parameters: dict | None = None,
        database_: str = "neo4j",
    ):
        """Execute a write query; return driver summary."""
        parameters = parameters or {}
        try:
            records, summary, _ = self.driver.execute_query(
                query,
                parameters_=parameters,
                database_=database_,
            )
        except Exception:
            logger.exception("Neo4j create failed")
            raise
        return summary