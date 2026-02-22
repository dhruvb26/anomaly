"""Pydantic schemas for the general agent (state and orchestrator decision)."""

from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class GeneralAgentState(MessagesState):
    """State for the Magentic-One style hub-spoke general agent.

    Models the central orchestrator + shared ledger architecture from
    Section 6.2 of the SentinelAgent paper.  The task_ledger acts as
    the append-only shared memory that all agents can read while the
    orchestrator writes planning/progress entries.
    """

    messages: Annotated[list[AnyMessage], add_messages]


class OrchestratorDecision(BaseModel):
    thought: str = Field(
        description="Brief reasoning about the current situation and what to do next."
    )
    next_agent: Literal["file_surfer", "web_surfer", "code_executor", "FINISH"] = Field(
        description=(
            "Which agent to delegate to, or FINISH when the task is fully resolved."
        )
    )
    instruction: str = Field(
        description=(
            "If delegating: a clear, specific instruction for the chosen agent. "
            "If FINISH: the final answer to present to the user."
        )
    )
