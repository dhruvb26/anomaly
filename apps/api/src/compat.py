"""Compatibility shims for third-party libraries.

Import this module before any library that depends on the removed APIs below.
It is safe to import multiple times — each shim is idempotent.

HfFolder (huggingface_hub >= 1.0 removed it; llamafirewall still uses it):
  Injects a stub that delegates to the modern huggingface_hub token API so
  that llamafirewall can import and call HfFolder.get_token() without error.
"""

from __future__ import annotations

try:
    from huggingface_hub import (
        HfFolder as _HfFolder,  # noqa: F401 — already present, nothing to do
    )
except ImportError:
    import huggingface_hub as _hf_hub

    class _HfFolder:  # type: ignore[no-redef]
        @staticmethod
        def get_token() -> str | None:
            return _hf_hub.get_token()

        @staticmethod
        def save_token(token: str) -> None:
            _hf_hub.login(token=token)

        @staticmethod
        def delete_token() -> None:
            try:
                _hf_hub.logout()
            except Exception:
                pass

    _hf_hub.HfFolder = _HfFolder  # type: ignore[attr-defined]
