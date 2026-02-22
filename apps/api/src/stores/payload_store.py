"""Redis-backed store for full run payloads (inputs/outputs) keyed by run_id."""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)


class PayloadStore:
    """Store and fetch full run payloads by run_id. Uses REDIS_URL env var if url not given."""

    KEY_PREFIX = "run:"

    def __init__(self, url: str | None = None) -> None:
        self._url = url or os.environ.get("REDIS_URL") or ""
        self._client = None

    def _get_client(self):
        import redis

        if self._client is None:
            if not self._url:
                raise RuntimeError("REDIS_URL or PayloadStore(url=...) is required")
            self._client = redis.from_url(self._url, decode_responses=True)
        return self._client

    def store(self, run_id: str, payload: dict) -> str:
        """JSON-serialize payload and SET run:{run_id}. Returns ref string."""
        key = f"{self.KEY_PREFIX}{run_id}"
        try:
            data = json.dumps(payload, default=str)
            self._get_client().set(key, data)
        except Exception:
            logger.exception("PayloadStore store failed for run_id=%s", run_id)
            raise
        return f"redis://{key}"

    def fetch(self, run_id: str) -> dict | None:
        """GET run:{run_id}, JSON-deserialize. Returns None if missing."""
        key = f"{self.KEY_PREFIX}{run_id}"
        try:
            raw = self._get_client().get(key)
        except Exception:
            logger.exception("PayloadStore fetch failed for run_id=%s", run_id)
            raise
        if raw is None:
            return None
        return json.loads(raw)

    def clear(self) -> int:
        """Delete all keys matching run:*. Returns the number of keys deleted."""
        try:
            client = self._get_client()
            keys = client.keys(f"{self.KEY_PREFIX}*")
            if not keys:
                return 0
            deleted = client.delete(*keys)
            logger.info("PayloadStore cleared — %s key(s) deleted", deleted)
            return deleted
        except Exception:
            logger.exception("PayloadStore clear failed")
            raise
