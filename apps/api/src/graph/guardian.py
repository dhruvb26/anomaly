"""IBM Granite Guardian 3.3 client via Ollama local REST API."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "ibm/granite3.3-guardian:8b"
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_CONFIDENCE_THRESHOLD = 0.5

# Granite 3.3 Guardian uses extended thinking and wraps its verdict in <score> tags:
#   <score> yes </score>  →  anomalous
#   <score> no </score>   →  safe
_SCORE_RE = re.compile(r"<score>\s*(yes|no)\s*</score>", re.IGNORECASE)


def _parse_score(raw: str) -> bool:
    """Extract the yes/no verdict from Granite 3.3's <score> tag output."""
    match = _SCORE_RE.search(raw)
    if match:
        return match.group(1).lower() == "yes"
    # Fallback for models that output a bare token
    tail = raw[-80:].lower()
    return "yes" in tail and "no" not in tail.replace("yes", "")


@dataclass
class GuardianResult:
    """Result of a Granite Guardian safety check."""

    is_anomalous: bool
    confidence: float
    risk_type: str
    reason: str


class GuardianClient:
    """
    Wraps Ollama's REST API to run IBM Granite Guardian 3.3 for:
    - Jailbreak / prompt injection detection (user-facing content)
    - Function-calling hallucination detection (LLM tool invocations)

    Granite 3.3 uses the model's built-in Guardian system prompt (set via the
    Modelfile); we do NOT override the system prompt so the model's safety
    reasoning is preserved.  The risk category is injected via the prompt itself.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.confidence_threshold = confidence_threshold
        logger.info(
            "GuardianClient ready — model=%s  endpoint=%s  threshold=%.2f",
            self.model,
            self.base_url,
            self.confidence_threshold,
        )
        self._probe_ollama()

    def _probe_ollama(self) -> None:
        """Check Ollama is reachable and the model is available; log the result."""
        url = f"{self.base_url}/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            available = [m.get("name", "") for m in (data.get("models") or [])]
            if any(self.model in name for name in available):
                logger.info("Guardian ✓ Ollama reachable — model '%s' found", self.model)
            else:
                logger.warning(
                    "Guardian ⚠ Ollama reachable but model '%s' not listed. "
                    "Available: %s  — run: ollama pull %s",
                    self.model,
                    available or "(none)",
                    self.model,
                )
        except urllib.error.URLError as e:
            logger.warning(
                "Guardian ✗ Ollama not reachable at %s: %s  "
                "— Guardian checks will be skipped (start Ollama or pass --no-guardian)",
                self.base_url,
                e,
            )

    def _generate(self, prompt: str) -> str:
        """Call Ollama /api/generate; return full response text (no custom system prompt)."""
        import time

        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        logger.debug("Guardian → POST %s  model=%s  prompt_len=%d", url, self.model, len(prompt))
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            logger.warning("Guardian ✗ Ollama request failed (%.1fs): %s", time.monotonic() - t0, e)
            return ""
        except json.JSONDecodeError as e:
            logger.warning("Guardian ✗ response JSON error: %s", e)
            return ""
        elapsed = time.monotonic() - t0
        raw = (data.get("response") or "").strip()
        logger.debug("Guardian ← response in %.1fs  len=%d  tail=%r", elapsed, len(raw), raw[-60:])
        return raw

    def check_jailbreak(self, user_content: str) -> GuardianResult:
        """
        Detect jailbreak / prompt injection in user-facing input.
        Uses Guardian's built-in 'jailbreak' risk category.
        """
        if not user_content or not user_content.strip():
            return GuardianResult(
                is_anomalous=False,
                confidence=0.0,
                risk_type="jailbreak",
                reason="empty_input",
            )
        logger.info("Guardian  jailbreak check  (content_len=%d) …", len(user_content))
        # Granite Guardian prompt format: risk category label + user turn
        prompt = (
            "jailbreak\n\n"
            f"<|user|>\n{user_content[:8000]}"
        )
        raw = self._generate(prompt)
        is_anomalous = _parse_score(raw)
        confidence = self.confidence_threshold if is_anomalous else (1.0 - self.confidence_threshold)
        verdict = "ANOMALOUS" if is_anomalous else "ok"
        logger.info("Guardian  jailbreak → %s  (confidence=%.2f)", verdict, confidence)
        return GuardianResult(
            is_anomalous=is_anomalous,
            confidence=confidence,
            risk_type="jailbreak",
            reason=raw[-300:] if raw else "no_response",
        )

    def check_function_calling_hallucination(
        self,
        tool_name: str,
        tool_args: str | dict,
        context_messages: list[dict] | None = None,
    ) -> GuardianResult:
        """
        Detect hallucinated or unsafe tool invocations in LLM output.
        Uses Guardian's built-in 'function_call' risk category.
        """
        args_str = (
            json.dumps(tool_args, default=str)
            if isinstance(tool_args, dict)
            else str(tool_args)
        )
        context_str = ""
        if context_messages:
            context_str = json.dumps(context_messages[:20], default=str)[:4000]

        # Build a minimal assistant tool-call turn for Guardian to evaluate
        tool_call_repr = f'{{"name": "{tool_name}", "arguments": {args_str[:2000]}}}'
        prompt_parts = ["function_call"]
        if context_str:
            prompt_parts.append(f"<|context|>\n{context_str}")
        prompt_parts.append(f"<|assistant|>\n{tool_call_repr}")
        prompt = "\n\n".join(prompt_parts)

        logger.info("Guardian  hallucination check  tool=%s …", tool_name)
        raw = self._generate(prompt)
        is_anomalous = _parse_score(raw)
        confidence = self.confidence_threshold if is_anomalous else (1.0 - self.confidence_threshold)
        verdict = "ANOMALOUS" if is_anomalous else "ok"
        logger.info("Guardian  hallucination [%s] → %s  (confidence=%.2f)", tool_name, verdict, confidence)
        return GuardianResult(
            is_anomalous=is_anomalous,
            confidence=confidence,
            risk_type="function_calling_hallucination",
            reason=raw[-300:] if raw else "no_response",
        )
