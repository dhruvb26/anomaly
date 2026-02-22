"""Route aggregation — include all sub-routers here."""

from __future__ import annotations

from fastapi import APIRouter

from src.routes import ingest, misc, runs, threads

router = APIRouter()
router.include_router(threads.router)
router.include_router(runs.router)
router.include_router(ingest.router)
router.include_router(misc.router)
