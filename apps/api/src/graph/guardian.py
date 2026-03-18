"""IBM Granite Guardian client via Ollama local REST API.

Supports both response formats:
- Granite 3.3 8b:  <score>yes</score> / <score>no</score> tags
- Granite 3.2 2b/3b: "Yes\\n<confidence> High </confidence>" plain-text
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from src.graph.config import sentinel_config

logger = logging.getLogger(__name__)

# Granite 3.3 8b: <score>yes</score> / <score>no</score>
_SCORE_TAG_RE = re.compile(r"<score>\s*(yes|no)\s*</score>", re.IGNORECASE)
# Granite 3.2 2b/3b: <confidence> High </confidence>
_CONFIDENCE_TAG_RE = re.compile(r"<confidence>\s*(high|medium|low)\s*</confidence>", re.IGNORECASE)
# Last-resort: first standalone yes/no word
_VERDICT_WORD_RE = re.compile(r"\b(yes|no)\b", re.IGNORECASE)

_CONFIDENCE_MAP = {"high": 0.9, "medium": 0.6, "low": 0.3}


def _parse_response(raw: str) -> tuple[bool | None, float | None]:
    """Extract (verdict, model_confidence) from a Guardian response.

    Returns (None, None) if the verdict cannot be determined.
    model_confidence is only populated when the model emits a <confidence> tag
    (Granite 3.2 2b/3b); callers fall back to confidence_threshold otherwise.

    Format priority:
    1. <score>yes/no</score>           — Granite 3.3 8b
    2. First word + <confidence> tag   — Granite 3.2 2b/3b ("Yes\\n<confidence> High </confidence>")
    3. First word yes/no (no tag)      — plain-text fallback
    4. First yes/no word anywhere      — last resort
    """
    if not raw:
        return None, None

    # Format 1: structured XML tag (3.3 8b) — no confidence tag in this format
    match = _SCORE_TAG_RE.search(raw)
    if match:
        return match.group(1).lower() == "yes", None

    # Format 2 & 3: plain text — first word is the verdict
    first_word = raw.strip().split()[0].rstrip(".,!?:;").lower() if raw.strip() else ""
    if first_word in ("yes", "no"):
        verdict = first_word == "yes"
        conf_match = _CONFIDENCE_TAG_RE.search(raw)
        model_confidence = _CONFIDENCE_MAP.get(conf_match.group(1).lower()) if conf_match else None
        return verdict, model_confidence

    # Format 4: yes/no anywhere as a whole word (last resort)
    match = _VERDICT_WORD_RE.search(raw)
    if match:
        logger.debug("Guardian: verdict extracted via fallback word search from: %r", raw[:80])
        return match.group(1).lower() == "yes", None

    return None, None


@dataclass(slots=True)
class GuardianResult:
    """Result of a Granite Guardian safety check."""

    is_anomalous: bool
    confidence: float
    risk_type: str
    reason: str


class GuardianClient:
    """Ollama-based IBM Granite Guardian client for jailbreak and hallucination detection.

    Compatible with both Granite Guardian model series:
    - 3.3 (e.g. ibm/granite3.3-guardian:8b) — outputs <score>yes/no</score> tags
    - 3.2 (e.g. ibm/granite3.2-guardian:3b, 2b) — outputs plain-text verdicts
    """

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        confidence_threshold: float | None = None,
    ):
        cfg = sentinel_config.guardian
        self.model = model or cfg.model
        self.base_url = (base_url or cfg.base_url).rstrip("/")
        self.confidence_threshold = (
            confidence_threshold if confidence_threshold is not None else cfg.confidence_threshold
        )
        self._probe_ollama()

    def _probe_ollama(self) -> None:
        """Check Ollama reachability and model availability at startup."""
        url = f"{self.base_url}/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            available = [m.get("name", "") for m in data.get("models") or []]
            if any(self.model in name for name in available):
                logger.info("Guardian: Ollama reachable, model '%s' found", self.model)
            else:
                logger.warning(
                    "Guardian: Ollama reachable but model '%s' not listed (available: %s). "
                    "Run: ollama pull %s",
                    self.model,
                    available or "(none)",
                    self.model,
                )
        except urllib.error.URLError as exc:
            logger.warning(
                "Guardian: Ollama not reachable at %s (%s). "
                "Guardian checks will be skipped.",
                self.base_url,
                exc,
            )

    def _generate(self, prompt: str) -> str:
        """Call Ollama /api/generate and return the response text."""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        logger.debug("Guardian POST %s model=%s prompt_len=%d", url, self.model, len(prompt))
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            logger.warning("Guardian request failed (%.1fs): %s", time.monotonic() - t0, exc)
            return ""
        except json.JSONDecodeError as exc:
            logger.warning("Guardian response JSON error: %s", exc)
            return ""
        elapsed = time.monotonic() - t0
        raw = (data.get("response") or "").strip()
        logger.debug("Guardian response in %.1fs len=%d", elapsed, len(raw))
        return raw

    def check_jailbreak(self, user_content: str) -> GuardianResult:
        """Detect jailbreak / prompt injection in user-facing input."""
        if not user_content or not user_content.strip():
            return GuardianResult(
                is_anomalous=False, confidence=0.0, risk_type="jailbreak", reason="empty_input"
            )
        prompt = f"jailbreak\n\n<|user|>\n{user_content[:8000]}"
        raw = self._generate(prompt)
        verdict, model_confidence = _parse_response(raw)
        if verdict is None:
            logger.warning(
                "Guardian: unparseable jailbreak response (len=%d) raw=%r", len(raw), raw[:80]
            )
            return GuardianResult(
                is_anomalous=False, confidence=0.0, risk_type="jailbreak", reason="unparseable_response"
            )
        is_anomalous = verdict
        confidence = model_confidence if model_confidence is not None else (
            self.confidence_threshold if is_anomalous else (1.0 - self.confidence_threshold)
        )
        logger.debug("Guardian jailbreak -> %s (conf=%.2f)", "ANOMALOUS" if is_anomalous else "ok", confidence)
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
        """Detect hallucinated or unsafe tool invocations in LLM output."""
        args_str = json.dumps(tool_args, default=str) if isinstance(tool_args, dict) else str(tool_args)
        context_str = ""
        if context_messages:
            context_str = json.dumps(context_messages[:20], default=str)[:4000]

        tool_call_repr = f'{{"name": "{tool_name}", "arguments": {args_str[:2000]}}}'
        prompt_parts = ["function_call"]
        if context_str:
            prompt_parts.append(f"<|context|>\n{context_str}")
        prompt_parts.append(f"<|assistant|>\n{tool_call_repr}")
        prompt = "\n\n".join(prompt_parts)

        raw = self._generate(prompt)
        verdict, model_confidence = _parse_response(raw)
        if verdict is None:
            logger.warning(
                "Guardian: unparseable hallucination response for tool=%s (len=%d) raw=%r",
                tool_name, len(raw), raw[:80],
            )
            return GuardianResult(
                is_anomalous=False,
                confidence=0.0,
                risk_type="function_calling_hallucination",
                reason="unparseable_response",
            )
        is_anomalous = verdict
        confidence = model_confidence if model_confidence is not None else (
            self.confidence_threshold if is_anomalous else (1.0 - self.confidence_threshold)
        )
        logger.debug("Guardian hallucination [%s] -> %s (conf=%.2f)", tool_name, "ANOMALOUS" if is_anomalous else "ok", confidence)
        return GuardianResult(
            is_anomalous=is_anomalous,
            confidence=confidence,
            risk_type="function_calling_hallucination",
            reason=raw[-300:] if raw else "no_response",
        )
