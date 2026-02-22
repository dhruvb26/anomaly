"""Miscellaneous informational routes."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/info")
async def get_info():
    return {
        "version": "0.0.1",
        "features": {
            "streaming_modes": ["values", "messages", "updates"],
        },
    }
