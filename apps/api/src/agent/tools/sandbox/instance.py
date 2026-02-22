from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from src.scripts.deploy_modal import sandbox_image
from .client import LazyResilientModalSandbox

_sandbox = LazyResilientModalSandbox(
    app_name="my-agent-app",
    volume_name="general-agent-workspace",
    volume_path="/workspace",
    timeout=600,
    image=sandbox_image,
)

_workspace_seeded = False


def ensure_sandbox_ready() -> None:
    global _workspace_seeded
    if _workspace_seeded:
        return
    try:
        _sandbox.execute(
            "if [ -d /seed-data ] && [ \"$(ls -A /seed-data 2>/dev/null)\" ]; then "
            "cp -a /seed-data/. /workspace/; fi"
        )
    except Exception:
        pass
    _workspace_seeded = True


def exec_command(command: str) -> str:
    global _workspace_seeded
    try:
        ensure_sandbox_ready()
        result = _sandbox.execute(command)
    except Exception:
        _sandbox.terminate()
        _workspace_seeded = False
        ensure_sandbox_ready()
        result = _sandbox.execute(command)
    output = getattr(result, "output", "") or "(no output)"
    return output


def get_sandbox() -> LazyResilientModalSandbox:
    return _sandbox


def build_sandbox_tools(sandbox: LazyResilientModalSandbox) -> list[BaseTool]:
    """Create sandbox tools bound to a specific sandbox instance."""

    @tool
    def run_python(code: str, filename: str = "script.py") -> str:
        """Write and execute a Python script in the Modal sandbox.

        The script is saved to /workspace/<filename> and executed with python3.
        The sandbox has requests, httpx, pandas, numpy, matplotlib, beautifulsoup4,
        and lxml pre-installed.

        Args:
            code: The Python source code to execute.
            filename: Name for the script file (default: script.py). Saved under /workspace/.
        """
        filepath = f"/workspace/{filename}"
        sandbox.write(filepath, code, overwrite=True)
        result = sandbox.execute(f"python3 {filepath}")
        output = getattr(result, "output", "") or "(no output)"
        sandbox.terminate()
        return output

    @tool
    def execute_command(command: str) -> str:
        """Execute a shell command in the Modal sandbox.

        The sandbox runs Debian Linux with Python 3.12. Files persisted to /workspace/
        survive across commands. Use this for running scripts, installing packages,
        listing files, or any shell operation.

        Args:
            command: The shell command to run (e.g. "ls /workspace", "pip install foo").
        """
        result = sandbox.execute(command)
        output = getattr(result, "output", "") or "(no output)"
        sandbox.terminate()
        return output

    return [run_python, execute_command]
