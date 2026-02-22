from __future__ import annotations

from langchain_core.tools import tool

from .sandbox import ensure_sandbox_ready, exec_command, get_sandbox


@tool
def read_file(file_path: str) -> str:
    """Read the contents of a file inside the sandbox.

    Args:
        file_path: Absolute path inside the sandbox (e.g. /workspace/data.csv).
    """
    ensure_sandbox_ready()
    content = get_sandbox().read(file_path)
    if len(content) > 50_000:
        return (
            f"File is large ({len(content):,} chars). Showing first 50,000:\n"
            + content[:50_000]
            + "\n… [truncated]"
        )
    return content


@tool
def list_directory(directory_path: str = "/workspace") -> str:
    """List files and directories inside the sandbox.

    Args:
        directory_path: Absolute path inside the sandbox. Defaults to /workspace.
    """
    return exec_command(f"ls -la {directory_path}")


@tool
def search_in_files(
    directory: str,
    pattern: str,
    file_extension: str = "",
) -> str:
    """Search for a text pattern in files inside the sandbox (recursive, case-insensitive).

    Args:
        directory: Root directory to search (e.g. /workspace).
        pattern: Text to search for.
        file_extension: Optional extension filter, e.g. ".py" or ".txt".
    """
    ext_flag = f"--include='*{file_extension}'" if file_extension else ""
    return exec_command(f"grep -rni {ext_flag} '{pattern}' {directory} 2>/dev/null | head -50")


@tool
def get_file_info(file_path: str) -> str:
    """Get metadata about a file in the sandbox (size, timestamps, permissions).

    Args:
        file_path: Absolute path inside the sandbox.
    """
    return exec_command(f"stat {file_path}")


@tool
def write_file(file_path: str, content: str) -> str:
    """Write content to a file in the sandbox. Creates parent directories if needed.

    Args:
        file_path: Absolute path inside the sandbox (e.g. /workspace/output.txt).
        content: Text content to write.
    """
    ensure_sandbox_ready()
    result = get_sandbox().write(file_path, content, overwrite=True)
    if hasattr(result, "error") and result.error:
        return f"Error: {result.error}"
    return f"Successfully wrote {len(content):,} chars to {file_path}"


FILE_SURFER_TOOLS = [
    read_file,
    list_directory,
    search_in_files,
    get_file_info,
    write_file,
]
