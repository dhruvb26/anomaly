"""Serializers for API: LangChain messages ↔ frontend shape, DB rows → thread dicts."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)


def serialize_message(msg: Any) -> dict[str, Any]:
    """Convert a LangChain message to the frontend Message shape."""
    d: dict[str, Any] = {
        "id": msg.id,
        "type": msg.type,
        "content": msg.content,
    }
    if getattr(msg, "name", None):
        d["name"] = msg.name
    if getattr(msg, "tool_calls", None):
        d["tool_calls"] = [
            {
                "id": tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None),
                "name": tc.get("name")
                if isinstance(tc, dict)
                else getattr(tc, "name", None),
                "args": (
                    tc.get("args", {})
                    if isinstance(tc, dict)
                    else getattr(tc, "args", {})
                ),
            }
            for tc in msg.tool_calls
        ]
    if getattr(msg, "tool_call_id", None):
        d["tool_call_id"] = msg.tool_call_id
    if getattr(msg, "additional_kwargs", None):
        d["additional_kwargs"] = msg.additional_kwargs
    return d


def deserialize_message(d: dict[str, Any]) -> BaseMessage:
    """Convert a frontend message dict to a LangChain message."""
    msg_type = d.get("type", "human")
    content = d.get("content", "")
    msg_id = d.get("id")
    name = d.get("name")
    additional_kwargs = d.get("additional_kwargs") or {}

    if isinstance(content, list):
        pass
    elif not isinstance(content, str):
        content = str(content) if content is not None else ""

    kwargs: dict[str, Any] = {}
    if msg_id is not None:
        kwargs["id"] = msg_id
    if name is not None:
        kwargs["name"] = name
    if additional_kwargs:
        kwargs["additional_kwargs"] = additional_kwargs

    if msg_type == "human":
        return HumanMessage(content=content, **kwargs)
    if msg_type == "ai":
        tool_calls = d.get("tool_calls")
        if tool_calls:
            kwargs["tool_calls"] = [
                {
                    "id": tc.get("id"),
                    "name": tc.get("name"),
                    "args": tc.get("args", {}),
                }
                for tc in tool_calls
            ]
        return AIMessage(content=content, **kwargs)
    if msg_type == "system":
        return SystemMessage(content=content, **kwargs)
    if msg_type == "tool":
        tool_call_id = d.get("tool_call_id", "")
        return ToolMessage(content=content, tool_call_id=tool_call_id, **kwargs)

    return HumanMessage(content=content, **kwargs)


def row_to_thread(r: tuple) -> dict[str, Any]:
    """Shape expected by app-sidebar: thread_id, created_at, updated_at, metadata."""
    return {
        "thread_id": r[0],
        "created_at": r[1].isoformat() if r[1] else None,
        "updated_at": r[2].isoformat() if r[2] else None,
        "metadata": r[3] or {},
    }
