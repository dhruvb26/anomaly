"""Configuration and constants for the agent graph."""

# Known agent names from general_agent.py (system-prompt keyword → canonical name)
_AGENT_SYSTEM_PROMPT_HINTS: list[tuple[str, str]] = [
    ("FileSurfer", "file_surfer"),
    ("WebSurfer", "web_surfer"),
    ("CodeExecutor", "code_executor"),
    ("Orchestrator", "orchestrator"),
]

# Agents that are treated as "sub-agents" (get internal __start__/__end__ nodes).
# Orchestrator is the root agent and connects directly to global __start__/__end__.
_SUB_AGENTS: frozenset[str] = frozenset({"file_surfer", "web_surfer", "code_executor"})

# When True: chain-type runs are loaded as nodes in the graph and each invocation's
# parent_run_id is preserved as-is (it will resolve to a real chain node).
# When False (default): chain runs are NOT graph nodes; instead each invocation's
# parent_run_id is resolved upward through the chain hierarchy to the nearest
# agent-subgraph chain (direct child of the root turn chain) and stored as
# delegation_chain_id — the chain that "owns" this invocation.
INCLUDE_CHAIN_RUNS: bool = False
