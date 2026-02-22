from __future__ import annotations

import contextlib
import posixpath
from typing import TYPE_CHECKING

from langchain_modal import ModalSandbox
from deepagents.backends.protocol import WriteResult
import modal

if TYPE_CHECKING:
    from modal.sandbox import ContainerProcess


class LazyResilientModalSandbox(ModalSandbox):
    """A ModalSandbox wrapper that lazily initializes and auto-recovers from termination.

    Modal resources are only created on first use, avoiding async context warnings
    during module import.
    """

    def __init__(
        self,
        app_name: str,
        volume_name: str,
        volume_path: str,
        timeout: int = 600,
        image: modal.Image | None = None,
    ):
        self._app_name = app_name
        self._volume_name = volume_name
        self._volume_path = volume_path
        self._timeout = timeout
        self._image = image
        self._initialized = False
        self._app: modal.App | None = None
        self._volume: modal.Volume | None = None
        self._sandbox: modal.Sandbox | None = None

    def _ensure_initialized(self):
        """Lazily initialize Modal resources on first use."""
        if self._initialized:
            return

        self._app = modal.App.lookup(self._app_name)
        self._volume = modal.Volume.from_name(self._volume_name, create_if_missing=True)
        self._create_sandbox()
        self._initialized = True

    def _create_sandbox(self):
        """Create a new sandbox instance."""
        kwargs: dict = {
            "app": self._app,
            "volumes": {self._volume_path: self._volume},
            "timeout": self._timeout,
        }
        if self._image is not None:
            kwargs["image"] = self._image

        self._sandbox = modal.Sandbox.create(**kwargs)
        super().__init__(sandbox=self._sandbox)

    def _ensure_sandbox_alive(self):
        """Check if sandbox is still running, recreate if terminated."""
        self._ensure_initialized()
        if self._sandbox is None:
            self._create_sandbox()
            return
        try:
            if self._sandbox.poll() is not None:
                self._create_sandbox()
        except Exception:
            self._create_sandbox()

    def execute(self, command: str) -> "ContainerProcess":
        """Execute command, recreating sandbox if needed."""
        self._ensure_sandbox_alive()
        return super().execute(command)

    def terminate(self) -> None:
        """Terminate the sandbox and commit the volume.

        Files on the volume are persisted. The next call to execute() or write()
        will transparently create a fresh sandbox.
        """
        if self._sandbox is not None:
            with contextlib.suppress(Exception):
                if self._volume is not None:
                    self._volume.commit()
            with contextlib.suppress(Exception):
                self._sandbox.terminate()
            self._sandbox = None

    def read(self, file_path: str, **kwargs: object) -> str:
        """Read a file from the sandbox."""
        self._ensure_sandbox_alive()
        try:
            f = self._sandbox.open(file_path, "r")
            try:
                return f.read()
            finally:
                with contextlib.suppress(Exception):
                    f.close()
        except Exception as e:
            return f"Error reading '{file_path}': {e}"

    def write(
        self, file_path: str, content: str, overwrite: bool = True
    ) -> WriteResult:
        """Write file using Modal's native file API to bypass ARG_MAX limits."""
        self._ensure_sandbox_alive()

        parent_dir = posixpath.dirname(file_path)
        if parent_dir:
            self.execute(f"mkdir -p {parent_dir}")

        if not overwrite:
            check = self.execute(f"test -f {file_path} && echo EXISTS")
            if "EXISTS" in check.output:
                return WriteResult(error=f"Error: File '{file_path}' already exists")

        try:
            f = self._sandbox.open(file_path, "w")
            try:
                f.write(content)
            finally:
                with contextlib.suppress(Exception):
                    f.close()
            return WriteResult(path=file_path, files_update=None)
        except Exception as e:
            return WriteResult(error=f"Failed to write file '{file_path}': {e}")
