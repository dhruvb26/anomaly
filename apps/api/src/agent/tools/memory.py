from __future__ import annotations

import uuid

from langchain_core.tools import InjectedToolArg, tool
from langgraph.store.base import BaseStore
from typing_extensions import Annotated


@tool
async def save_memory(
    content: str,
    memory_type: str,
    store: Annotated[BaseStore, InjectedToolArg],
    user_id: Annotated[str, InjectedToolArg] = "default",
    namespace: Annotated[str, InjectedToolArg] = "memories",
) -> str:
    """Save a memory to the store for later retrieval.

    Use this tool to persist important information that should be remembered
    across conversations, such as user preferences, facts, or context.

    Args:
        content: The content of the memory to save.
        memory_type: The type/category of the memory (e.g., 'preference', 'fact', 'context').
    """
    memory_namespace = (user_id, namespace)
    memory_id = str(uuid.uuid4())
    await store.aput(
        memory_namespace,
        memory_id,
        {"content": content, "type": memory_type},
    )
    return f"Successfully saved memory with id '{memory_id}' of type '{memory_type}'."


@tool
async def get_memory(
    memory_id: str,
    store: Annotated[BaseStore, InjectedToolArg],
    user_id: Annotated[str, InjectedToolArg] = "default",
    namespace: Annotated[str, InjectedToolArg] = "memories",
) -> str:
    """Retrieve a specific memory by its ID.

    Args:
        memory_id: The unique identifier of the memory to retrieve.
    """
    memory_namespace = (user_id, namespace)
    item = await store.aget(memory_namespace, memory_id)
    if item is None:
        return f"No memory found with id '{memory_id}'."
    return f"Memory (id: {memory_id}): {item.value}"


@tool
async def search_memories(
    query: str,
    store: Annotated[BaseStore, InjectedToolArg],
    user_id: Annotated[str, InjectedToolArg] = "default",
    namespace: Annotated[str, InjectedToolArg] = "memories",
    limit: int = 5,
) -> str:
    """Search for memories matching a query.

    Use this tool to find relevant memories based on semantic similarity.
    This is useful for retrieving context or information related to the current conversation.

    Args:
        query: The search query to match against stored memories.
        limit: Maximum number of memories to return (default: 5).
    """
    memory_namespace = (user_id, namespace)
    results = await store.asearch(memory_namespace, query=query, limit=limit)
    if not results:
        return "No memories found matching the query."
    memories = [
        f"- [{item.key}] {item.value.get('content', item.value)}" for item in results
    ]
    return f"Found {len(memories)} memories:\n" + "\n".join(memories)


@tool
async def list_memories(
    store: Annotated[BaseStore, InjectedToolArg],
    user_id: Annotated[str, InjectedToolArg] = "default",
    namespace: Annotated[str, InjectedToolArg] = "memories",
    memory_type: str | None = None,
    limit: int = 10,
) -> str:
    """List all memories, optionally filtered by type.

    Args:
        memory_type: Optional filter for memory type (e.g., 'preference', 'fact').
        limit: Maximum number of memories to return (default: 10).
    """
    memory_namespace = (user_id, namespace)
    filter_dict = {"type": memory_type} if memory_type else None
    results = await store.asearch(memory_namespace, filter=filter_dict, limit=limit)
    if not results:
        return "No memories found."
    memories = []
    for item in results:
        value = item.value
        mem_type = value.get("type", "unknown")
        content = value.get("content", str(value))
        memories.append(f"- [{item.key}] ({mem_type}): {content}")
    return f"Found {len(memories)} memories:\n" + "\n".join(memories)


@tool
async def delete_memory(
    memory_id: str,
    store: Annotated[BaseStore, InjectedToolArg],
    user_id: Annotated[str, InjectedToolArg] = "default",
    namespace: Annotated[str, InjectedToolArg] = "memories",
) -> str:
    """Delete a memory by its ID.

    Args:
        memory_id: The unique identifier of the memory to delete.
    """
    memory_namespace = (user_id, namespace)
    item = await store.aget(memory_namespace, memory_id)
    if item is None:
        return f"No memory found with id '{memory_id}'."
    await store.adelete(memory_namespace, memory_id)
    return f"Successfully deleted memory with id '{memory_id}'."


STORE_TOOLS = [
    save_memory,
    get_memory,
    search_memories,
    list_memories,
    delete_memory,
]
