#!/usr/bin/env python3
"""API server entry point — app creation, middleware, and router registration."""

from __future__ import annotations

import logging

# To patch HfFolder before any llamafirewall import since it uses HfFolder.get_token() from an older version
# Read - apps/api/src/compat.py
import src.compat  # noqa: F401 — patches HfFolder before any llamafirewall import
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.lifespan import lifespan
from src.routes import router

load_dotenv(override=True)
logging.basicConfig(level=logging.INFO)
logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=2024, reload=True)
