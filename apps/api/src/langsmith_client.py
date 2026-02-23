from __future__ import annotations

_langsmith_client: object | None = None


def get_langsmith_client():
    """Return a shared LangSmith Client"""
    global _langsmith_client
    if _langsmith_client is None:
        from langsmith import Client

        _langsmith_client = Client()
    return _langsmith_client
