from __future__ import annotations

import logging
from typing import Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.messages import get_buffer_string
from langgraph.graph import END, START, StateGraph
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain.agents.middleware.summarization import (
    DEFAULT_SUMMARY_PROMPT,
    count_tokens_approximately,
)
from langgraph.types import Command

from src.agent.helpers import agent_node, load_prompts, get_agent_available_tools
from src.agent.tools import (
    CODE_EXECUTOR_TOOLS,
    FILE_SURFER_TOOLS,
    STORE_TOOLS,
    WEB_SURFER_TOOLS,
)
from .schemas import GeneralAgentState, OrchestratorDecision

logger = logging.getLogger(__name__)

model = ChatAnthropic(
    model_name="claude-sonnet-4-5-20250929",
    max_tokens=12000,
)

# claude-haiku-4-5-20251001 is ~3x cheaper than Sonnet for summarization tasks
summarization_model = ChatAnthropic(
    model_name="claude-haiku-4-5-20251001",
    max_tokens=4096,
)

# Shared trigger thresholds — used by both the agent middleware and the orchestrator.
_TRIGGER_TOKENS = 60_000
_TRIGGER_MESSAGES = 50
_KEEP_MESSAGES = 15

# Shared middleware for sub-agents: summarize when either threshold is crossed,
# retaining the most recent _KEEP_MESSAGES messages after summarization.
summarization_middleware = SummarizationMiddleware(
    model=summarization_model,
    trigger=[("tokens", _TRIGGER_TOKENS), ("messages", _TRIGGER_MESSAGES)],
    keep=("messages", _KEEP_MESSAGES),
)


async def _maybe_summarize_messages(
    messages: list[AnyMessage],
) -> list[AnyMessage]:
    """Summarize older messages for the orchestrator when thresholds are exceeded.

    Mirrors the same trigger/keep policy used by SummarizationMiddleware so the
    orchestrator's context is managed consistently with the sub-agents.
    """
    below_msg_threshold = len(messages) < _TRIGGER_MESSAGES
    below_token_threshold = (
        below_msg_threshold  # skip expensive count if msg count is already fine
        or count_tokens_approximately(messages) < _TRIGGER_TOKENS
    )
    if below_msg_threshold and below_token_threshold:
        return messages

    if len(messages) <= _KEEP_MESSAGES:
        return messages

    to_summarize = messages[:-_KEEP_MESSAGES]
    to_keep = messages[-_KEEP_MESSAGES:]

    formatted = get_buffer_string(to_summarize)
    prompt = DEFAULT_SUMMARY_PROMPT.format(messages=formatted).rstrip()

    try:
        response = await summarization_model.ainvoke(
            prompt, config={"metadata": {"lc_source": "summarization"}}
        )
        summary = response.text.strip()
    except Exception:
        logger.warning("Orchestrator summarization failed; using full message history")
        return messages

    summary_message = HumanMessage(
        content=f"Here is a summary of the conversation to date:\n\n{summary}",
        additional_kwargs={"lc_source": "summarization"},
    )
    return [summary_message] + to_keep


prompts = load_prompts()

file_surfer = create_agent(
    model=model,
    tools=FILE_SURFER_TOOLS + STORE_TOOLS,
    name="file_surfer",
    system_prompt=prompts["file_surfer"],
    middleware=[summarization_middleware],
)

web_surfer = create_agent(
    model=model,
    tools=WEB_SURFER_TOOLS + STORE_TOOLS,
    name="web_surfer",
    system_prompt=prompts["web_surfer"],
    middleware=[summarization_middleware],
)

code_executor = create_agent(
    model=model,
    tools=CODE_EXECUTOR_TOOLS + STORE_TOOLS,
    name="code_executor",
    system_prompt=prompts["code_executor"],
    middleware=[summarization_middleware],
)


async def orchestrator_node(
    state: GeneralAgentState,
) -> Command[Literal["file_surfer", "web_surfer", "code_executor", "__end__"]]:

    messages = await _maybe_summarize_messages(state["messages"])
    system = SystemMessage(content=prompts["orchestrator"])

    try:
        result = await model.with_structured_output(
            OrchestratorDecision, include_raw=True
        ).ainvoke([system] + messages)

        decision: OrchestratorDecision = result["parsed"]
        raw_message = result["raw"]

        thinking_blocks = [
            block
            for block in (
                raw_message.content if isinstance(raw_message.content, list) else []
            )
            if isinstance(block, dict) and block.get("type") == "thinking"
        ]

    except Exception:
        logger.exception("Orchestrator LLM call failed")
        return Command(
            update={
                "messages": [
                    AIMessage(
                        content="I encountered an error while planning. Please try again.",
                        name="orchestrator",
                    )
                ],
            },
            goto=END,
        )

    instruction_block = {"type": "text", "text": decision.instruction}
    content = thinking_blocks + [instruction_block]
    kwargs = {
        "routing": decision.next_agent,
        "thought": decision.thought,
    }

    if decision.next_agent == "FINISH":
        return Command(
            update={
                "messages": [
                    AIMessage(
                        content=content,
                        name="orchestrator",
                        additional_kwargs=kwargs,
                    )
                ],
            },
            goto=END,
        )

    return Command(
        update={
            "messages": [
                AIMessage(
                    content=content,
                    name="orchestrator",
                    additional_kwargs=kwargs,
                ),
                HumanMessage(content=decision.instruction, name="orchestrator"),
            ],
        },
        goto=decision.next_agent,
    )


builder = StateGraph(GeneralAgentState)

builder.add_node("orchestrator", orchestrator_node)
builder.add_node("file_surfer", agent_node(file_surfer, "file_surfer"))
builder.add_node("web_surfer", agent_node(web_surfer, "web_surfer"))
builder.add_node("code_executor", agent_node(code_executor, "code_executor"))

builder.add_edge(START, "orchestrator")
builder.add_edge("file_surfer", "orchestrator")
builder.add_edge("web_surfer", "orchestrator")
builder.add_edge("code_executor", "orchestrator")

graph = builder.compile()
available_tools = get_agent_available_tools(file_surfer, web_surfer, code_executor)
