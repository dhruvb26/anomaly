"""Redis-backed store for full run payloads (inputs/outputs) keyed by run_id."""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)


class PayloadStore:
    """Store and fetch full run payloads by run_id."""

    KEY_PREFIX = "run:"

    def __init__(self) -> None:
        self._url = os.getenv("REDIS_URL")
        self._client = None

    def _get_client(self):
        import redis

        if self._client is None:
            self._client = redis.from_url(self._url, decode_responses=True)
        return self._client

    def store(self, run_id: str, payload: dict) -> str:
        """JSON-serialize payload and SET run:{run_id}. Returns ref string."""
        key = f"{self.KEY_PREFIX}{run_id}"
        try:
            data = json.dumps(payload, default=str)
            self._get_client().set(key, data)
        except Exception as e:
            logger.exception(f"PayloadStore store failed for run_id={run_id}: {e}")
            raise

        return f"redis://{key}"

    def fetch(self, run_id: str) -> dict | None:
        """GET run:{run_id}, JSON-deserialize. Returns None if missing."""
        key = f"{self.KEY_PREFIX}{run_id}"
        try:
            raw = self._get_client().get(key)
        except Exception as e:
            logger.exception(f"PayloadStore fetch failed for run_id={run_id}: {e}")
            raise
        if raw is None:
            return None
        logger.info(f"PayloadStore fetch succeeded for run_id={run_id}")
        return json.loads(raw)

    def delete_many(self, run_ids: list[str]) -> int:
        """Delete run:{run_id} keys for the given run_ids. Returns the number deleted."""
        if not run_ids:
            return 0
        try:
            client = self._get_client()
            keys = [f"{self.KEY_PREFIX}{rid}" for rid in run_ids if rid]
            if not keys:
                return 0
            deleted = client.delete(*keys)
            logger.info("PayloadStore delete_many — %s key(s) deleted", deleted)
            return deleted
        except Exception as e:
            logger.exception("PayloadStore delete_many failed: %s", e)
            raise

    def clear(self) -> int:
        """Delete all keys matching run:*. Returns the number of keys deleted."""
        try:
            client = self._get_client()
            keys = client.keys(f"{self.KEY_PREFIX}*")
            if not keys:
                return 0
            deleted = client.delete(*keys)
            logger.info(f"PayloadStore cleared — {deleted} key(s) deleted")
            return deleted
        except Exception as e:
            logger.exception(f"PayloadStore clear failed: {e}")
            raise
