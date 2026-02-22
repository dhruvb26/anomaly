"""Agent utilities: tool error wrapping and re-exports."""

from __future__ import annotations

import functools
from langchain_core.tools import BaseTool

def wrap_tools_with_error_handling(tools: list[BaseTool]) -> list[BaseTool]:
    """Wrap tools so exceptions return error messages instead of crashing the run."""
    for t in tools:
        original_run = t._run

        @functools.wraps(original_run)
        def _safe_run(*args, _orig=original_run, **kwargs):  # noqa: N802
            try:
                return _orig(*args, **kwargs)
            except Exception as e:
                error_type = type(e).__name__
                return f"Tool error ({error_type}): {e}"

        t._run = _safe_run
    return tools


