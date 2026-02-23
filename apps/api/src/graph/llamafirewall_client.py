"""LlamaFirewall client for edge-status checks: prompt injection and alignment."""

from __future__ import annotations

import src.compat  # noqa: F401 — patches HfFolder before llamafirewall

import logging
import os
from dataclasses import dataclass
from enum import Enum

from src.graph.config import sentinel_config

logger = logging.getLogger(__name__)

MAX_PROMPT_GUARD_LEN = 32_000
MAX_ALIGNMENT_LEN = 8_000
MAX_CONVERSATION_HISTORY = 20


class FirewallDecision(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    HUMAN_IN_THE_LOOP = "HUMAN_IN_THE_LOOP_REQUIRED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


@dataclass(slots=True)
class FirewallResult:
    """Result of a LlamaFirewall edge check."""

    is_anomalous: bool
    score: float
    decision: str
    risk_type: str
    reason: str


def _build_prompt_guard():
    """Construct the PromptGuard scanner. Raises on failure."""
    from llamafirewall import LlamaFirewall, Role, ScannerType, UserMessage

    fw = LlamaFirewall(scanners={Role.USER: [ScannerType.PROMPT_GUARD]})
    fw.scan(UserMessage(content="ping"))
    return fw


def _build_alignment_check():
    """Construct the AlignmentCheck scanner. Raises on failure."""
    from llamafirewall import LlamaFirewall, Role, ScannerType

    return LlamaFirewall(scanners={Role.ASSISTANT: [ScannerType.AGENT_ALIGNMENT]})


def _skipped_result(reason: str, risk_type: str = "") -> FirewallResult:
    return FirewallResult(
        is_anomalous=False,
        score=0.0,
        decision=FirewallDecision.SKIPPED.value,
        risk_type=risk_type,
        reason=reason,
    )


class LlamaFirewallClient:
    """PromptGuard 2 and AlignmentCheck scanners for edge-status checks.

    Validates scanner availability at init time. Disabled scanners
    are reported via warnings — no silent fallbacks.
    """

    def __init__(self) -> None:
        cfg = sentinel_config.firewall
        self._prompt_guard = None
        self._prompt_guard_available = False
        self._alignment = None
        self._alignment_available = False

        if cfg.enabled and cfg.prompt_guard.enabled:
            try:
                self._prompt_guard = _build_prompt_guard()
                self._prompt_guard_available = True
                logger.info("LlamaFirewall: PromptGuard scanner ready")
            except Exception as exc:
                logger.warning(
                    "LlamaFirewall: PromptGuard unavailable (%s). "
                    "Request model access at https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M",
                    exc,
                )
        elif not cfg.enabled:
            logger.info("LlamaFirewall: disabled via config")
        else:
            logger.info("LlamaFirewall: PromptGuard disabled via config")

        if cfg.enabled and cfg.alignment_check.enabled:
            api_key = os.environ.get("TOGETHER_API_KEY", "").strip()
            if not api_key:
                logger.warning(
                    "LlamaFirewall: TOGETHER_API_KEY not set — AlignmentCheck disabled"
                )
            else:
                try:
                    self._alignment = _build_alignment_check()
                    self._alignment_available = True
                    logger.info("LlamaFirewall: AlignmentCheck scanner ready")
                except Exception as exc:
                    logger.warning("LlamaFirewall: AlignmentCheck unavailable (%s)", exc)
        elif cfg.enabled:
            logger.info("LlamaFirewall: AlignmentCheck disabled via config")

    def _result_from_scan(
        self, decision, score: float, reason: str, risk_type: str
    ) -> FirewallResult:
        from llamafirewall import ScanDecision

        decision_str = getattr(decision, "value", str(decision))
        is_anomalous = decision in (
            ScanDecision.BLOCK,
            ScanDecision.HUMAN_IN_THE_LOOP_REQUIRED,
        )
        return FirewallResult(
            is_anomalous=is_anomalous,
            score=score,
            decision=decision_str,
            risk_type=risk_type if is_anomalous else "",
            reason=reason or "default",
        )

    def check_prompt_injection(self, content: str) -> FirewallResult:
        """PromptGuard 2 scan on content. Returns SKIPPED if scanner unavailable."""
        if not content or not content.strip():
            return _skipped_result("empty_content")

        if not self._prompt_guard_available:
            return _skipped_result("scanner_unavailable")

        try:
            from llamafirewall import UserMessage

            msg = UserMessage(content=content[:MAX_PROMPT_GUARD_LEN])
            result = self._prompt_guard.scan(msg)
            fr = self._result_from_scan(
                result.decision, result.score, result.reason or "default",
                risk_type="prompt_injection",
            )
            logger.debug(
                "LlamaFirewall PromptGuard -> %s score=%.4f", fr.decision, fr.score
            )
            return fr
        except Exception as exc:
            logger.exception("LlamaFirewall PromptGuard scan failed")
            return FirewallResult(
                is_anomalous=False,
                score=0.0,
                decision=FirewallDecision.ERROR.value,
                risk_type="",
                reason=f"scan_error:{exc!s}",
            )

    def check_alignment(
        self,
        user_query: str,
        conversation_history: list[dict],
        suspicious_content: str,
    ) -> FirewallResult:
        """AlignmentCheck scan over a conversation trace."""
        if not suspicious_content or not suspicious_content.strip():
            return _skipped_result("empty_content")

        if not self._alignment_available:
            return _skipped_result("alignment_scanner_unavailable")

        try:
            from llamafirewall import AssistantMessage, UserMessage

            trace: list = []
            if user_query:
                trace.append(UserMessage(content=user_query[:MAX_ALIGNMENT_LEN]))
            for entry in conversation_history[:MAX_CONVERSATION_HISTORY]:
                role = (entry.get("role") or entry.get("type") or "user").lower()
                content = entry.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        p.get("text", str(p)) if isinstance(p, dict) else str(p)
                        for p in content
                    )
                content = str(content)[:MAX_ALIGNMENT_LEN]
                if role in ("user", "human"):
                    trace.append(UserMessage(content=content))
                else:
                    trace.append(AssistantMessage(content=content))
            trace.append(AssistantMessage(content=suspicious_content[:MAX_ALIGNMENT_LEN]))

            result = self._alignment.scan_replay(trace)
            fr = self._result_from_scan(
                result.decision, result.score, result.reason or "default",
                risk_type="alignment_violation",
            )
            logger.debug(
                "LlamaFirewall AlignmentCheck -> %s score=%.4f", fr.decision, fr.score
            )
            return fr
        except Exception as exc:
            logger.exception("LlamaFirewall AlignmentCheck scan failed")
            return FirewallResult(
                is_anomalous=False,
                score=0.0,
                decision=FirewallDecision.ERROR.value,
                risk_type="",
                reason=f"scan_error:{exc!s}",
            )
