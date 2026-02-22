from __future__ import annotations

from langchain_core.tools import tool
from .sandbox import exec_command, get_sandbox


@tool
def execute_python(code: str, filename: str = "script.py") -> str:
    """Write and execute a Python script inside the Modal sandbox.

    The script is saved to /workspace/<filename> and executed with python3.
    Pre-installed packages: requests, httpx, pandas, numpy, matplotlib,
    beautifulsoup4, lxml.

    Args:
        code: The Python source code to execute.
        filename: Name for the script file (default: script.py).
    """
    filepath = f"/workspace/{filename}"
    get_sandbox().write(filepath, code, overwrite=True)
    return exec_command(f"python3 {filepath}")


@tool
def execute_shell(command: str) -> str:
    """Execute a shell command inside the Modal sandbox.

    The sandbox runs Debian Linux with Python 3.12. Files persisted to
    /workspace/ survive across commands.

    Args:
        command: The shell command to run (e.g. "ls /workspace", "pip install foo").
    """
    return exec_command(command)


CODE_EXECUTOR_TOOLS = [execute_python, execute_shell]
