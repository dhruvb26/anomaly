"""FastAPI lifespan: initialise and tear down long-lived resources."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres import AsyncPostgresStore
from src import state
from src.config import check_env, get_db_uri
from src.db import ensure_sentinel_reports_table, ensure_threads_table

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from src.agent.agent import builder
    from src.stores.graph_db import GraphDB
    from src.stores.payload_store import PayloadStore

    check_env()
    await ensure_threads_table()
    await ensure_sentinel_reports_table()

    db_uri = get_db_uri()
    try:
        async with AsyncPostgresSaver.from_conn_string(db_uri) as cp:
            await cp.setup()
            state.checkpointer = cp

            async with AsyncPostgresStore.from_conn_string(db_uri) as store:
                await store.setup()
                state.store = store
                state.graph = builder.compile(checkpointer=cp, store=store)

                state.graph_db = GraphDB()
                state.graph_db.verify_connectivity()
                state.graph_db.setup_schema()
                state.payload_store = PayloadStore()

                logger.info(
                    "Server ready — graph compiled with Postgres checkpointer + store"
                )
                yield
    except Exception as e:
        logger.exception(f"Failed to start checkpointer/store or compile graph: {e}")
        raise
    finally:
        if state.graph_db is not None:
            state.graph_db.close()
        state.checkpointer = None
        state.store = None
        state.graph = None
        state.graph_db = None
        state.payload_store = None
