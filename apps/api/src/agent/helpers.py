"""Agent helpers: prompt loading, agent_node wrapper, tool introspection."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import BaseMessage

from .schemas import GeneralAgentState

logger = logging.getLogger(__name__)


def _system_text_from_prompt(prompt_template, date: str) -> str:
    """Extract system message content from a LangSmith ChatPromptTemplate invoked with date."""
    try:
        input_vars = getattr(prompt_template, "input_variables", [])
        kwargs: dict = {v: "" for v in input_vars}
        kwargs["date"] = date
        result = prompt_template.invoke(kwargs)
        msgs = result.messages if hasattr(result, "messages") else list(result)
        for msg in msgs:
            content = getattr(msg, "content", "") or ""
            if content.strip():
                return content
        return ""
    except Exception:
        logger.debug("Failed to extract text from prompt template", exc_info=True)
        return ""


def _load_fallback_prompts(date_str: str) -> dict[str, str]:
    """Load prompts from prompts.jsonl (same dir as this module), with {date} replaced by date_str."""
    path = Path(__file__).resolve().parent / "prompts.jsonl"
    out: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                name = obj.get("name")
                template = obj.get("template", "")
                if name:
                    out[name] = template.replace("{date}", date_str)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to load fallback prompts from %s: %s", path, e)
    return out


def load_prompts() -> dict[str, str]:
    """Pull orchestrator and agent prompts from LangSmith. Returns dict of name -> system text.
    On LangSmith failure (e.g. 500, network, or missing prompts), returns fallback prompts so the app can start.
    """
    from src.langsmith_client import get_langsmith_client

    _now = datetime.now(timezone.utc)
    _date_str = _now.strftime("%A, %B %d, %Y %I:%M %p UTC")
    base_names = ("orchestrator", "file_surfer", "web_surfer", "code_executor")
    try:
        client = get_langsmith_client()
        out: dict[str, str] = {}
        workspace_id = os.environ.get("LANGSMITH_WORKSPACE_ID", "")
        prompt_index: dict[str, str] = {}
        for item in client.list_prompts(is_public=False):
            if isinstance(item, tuple) and item[0] == "repos":
                for p in item[1]:
                    if getattr(p, "tenant_id", None) == workspace_id:
                        prompt_index[p.repo_handle] = p.last_commit_hash[:8]
        for name in base_names:
            commit = prompt_index.get(name)
            if not commit:
                raise ValueError(f"Prompt {name!r} not found in workspace")
            prompt = client.pull_prompt(f"{name}")
            text = _system_text_from_prompt(prompt, _date_str)
            if not text:
                raise ValueError(f"Prompt {name!r} returned empty system text")
            out[name] = text
        return out
    except Exception:
        logger.warning(
            "Failed to load prompts from LangSmith; using fallback prompts from prompts.jsonl. "
            "Set up LangSmith and push prompts for production.",
            exc_info=True,
        )
        return _load_fallback_prompts(_date_str)


def _tool_names_from_agent(agent) -> list[str]:
    """Extract tool names from a create_agent-built CompiledStateGraph (from its tools node)."""
    try:
        tools_node = getattr(agent, "builder", None) and agent.builder.nodes.get(
            "tools"
        )
        if tools_node is None:
            return []
        runnable = getattr(tools_node, "runnable", None)
        if runnable is None:
            return []
        by_name = getattr(runnable, "_tools_by_name", None)
        if by_name is None:
            return []
        return list(by_name.keys())
    except Exception:
        return []


def _messages_with_name(messages: list[BaseMessage], name: str) -> list[BaseMessage]:
    """Set `name` on each message so LangSmith shows which agent produced them."""
    result = []
    for msg in messages:
        if isinstance(msg, BaseMessage) and hasattr(msg, "model_copy"):
            result.append(msg.model_copy(update={"name": name}))
        else:
            result.append(msg)
    return result


def agent_node(agent, agent_name: str):
    """Wrap an agent so newly produced messages are named with agent_name.

    agent.ainvoke returns the sub-graph's full state (all messages, not just
    the delta), so we filter to only messages that did not exist in the input,
    then set their name via _messages_with_name.
    """

    async def node(state: GeneralAgentState):
        input_ids: set[str | None] = {getattr(m, "id", None) for m in state["messages"]}
        update = await agent.ainvoke(state)
        if "messages" in update and update["messages"]:
            new_msgs = [
                msg
                for msg in update["messages"]
                if getattr(msg, "id", None) not in input_ids
            ]
            update = {**update, "messages": _messages_with_name(new_msgs, agent_name)}
        return update

    return node


def get_agent_available_tools(
    file_surfer, web_surfer, code_executor
) -> dict[str, list[str]]:
    """Build the programmatic mapping for Neo4j Agent.available_tools from each agent's graph."""
    from src.agent.helpers import _tool_names_from_agent

    return {
        "file_surfer": _tool_names_from_agent(file_surfer),
        "web_surfer": _tool_names_from_agent(web_surfer),
        "code_executor": _tool_names_from_agent(code_executor),
        "orchestrator": [],
    }
