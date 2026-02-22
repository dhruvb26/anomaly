"""LlamaFirewall client for edge-status checks: prompt injection and alignment."""

from __future__ import annotations

try:
    import src.compat  # noqa: F401 — patches HfFolder; works when running via `uv run` from apps/api/
except ModuleNotFoundError:
    import compat  # noqa: F401 — fallback when src/ is directly on sys.path

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FirewallResult:
    """Result of a LlamaFirewall edge check."""

    is_anomalous: bool
    score: float
    decision: str  # "ALLOW" | "BLOCK" | "HUMAN_IN_THE_LOOP_REQUIRED"
    risk_type: str
    reason: str


def _safe_prompt_guard():
    """Lazy-construct the best available prompt-injection firewall.

    Preference order:
    1. PROMPT_GUARD  — most accurate, needs meta-llama/Llama-Prompt-Guard-2-86M
                       (gated HF model; request access at
                        https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M)
    2. HIDDEN_ASCII  — no model download required; detects Unicode-tag steganography
                       injections reliably.
    """
    from llamafirewall import LlamaFirewall, Role, ScannerType

    try:
        fw = LlamaFirewall(scanners={Role.USER: [ScannerType.PROMPT_GUARD]})
        # Probe with a dummy scan to surface gated-model errors eagerly
        from llamafirewall import UserMessage
        fw.scan(UserMessage(content="ping"))
        logger.info("LlamaFirewall: using PromptGuard scanner")
        return fw
    except Exception as e:
        logger.warning(
            "LlamaFirewall PromptGuard unavailable (%s). "
            "Falling back to HiddenASCII scanner. "
            "For full coverage request model access at "
            "https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M",
            e,
        )

    # Fallback: HiddenASCII — works without any HF credentials
    try:
        fw = LlamaFirewall(scanners={Role.USER: [ScannerType.HIDDEN_ASCII]})
        logger.info("LlamaFirewall: using HiddenASCII scanner (fallback)")
        return fw
    except Exception as e:
        logger.warning(
            "LlamaFirewall HiddenASCII unavailable: %s. Edge prompt-injection checks disabled.", e
        )
        return None


def _safe_alignment_check():
    """Lazy-construct AlignmentCheck firewall if TOGETHER_API_KEY is set; return None otherwise."""
    if not os.environ.get("TOGETHER_API_KEY", "").strip():
        logger.info(
            "TOGETHER_API_KEY not set. LlamaFirewall AlignmentCheck disabled for edge status."
        )
        return None
    try:
        from llamafirewall import LlamaFirewall, Role, ScannerType

        return LlamaFirewall(scanners={Role.ASSISTANT: [ScannerType.AGENT_ALIGNMENT]})
    except Exception as e:
        logger.warning(
            "LlamaFirewall AlignmentCheck unavailable: %s. Edge alignment checks disabled.",
            e,
        )
        return None


class LlamaFirewallClient:
    """
    Wraps LlamaFirewall scanners for edge-status checks:
    - PromptGuard 2: direct/indirect prompt injection on content flowing along edges.
    - AlignmentCheck (AGENT_ALIGNMENT): alignment of conversation between nodes.

    Degrades gracefully when TOGETHER_API_KEY is absent or scanners fail to load.
    """

    def __init__(self, confidence_threshold: float = 0.5) -> None:
        self.confidence_threshold = confidence_threshold
        self._prompt_guard = None
        self._alignment = None
        self._alignment_available: bool | None = None

    @property
    def prompt_guard(self):
        if self._prompt_guard is None:
            self._prompt_guard = _safe_prompt_guard()
        return self._prompt_guard

    @property
    def alignment(self):
        if self._alignment_available is None:
            self._alignment = _safe_alignment_check()
            self._alignment_available = self._alignment is not None
        return self._alignment

    def _result_from_scan(self, decision, score: float, reason: str) -> FirewallResult:
        from llamafirewall import ScanDecision

        decision_str = getattr(decision, "value", str(decision))
        is_anomalous = decision in (
            ScanDecision.BLOCK,
            ScanDecision.HUMAN_IN_THE_LOOP_REQUIRED,
        )
        risk_type = "prompt_injection" if is_anomalous else ""
        return FirewallResult(
            is_anomalous=is_anomalous,
            score=score,
            decision=decision_str,
            risk_type=risk_type,
            reason=reason or "default",
        )

    def check_prompt_injection(self, content: str) -> FirewallResult:
        """PromptGuard 2 scan on a single content string. Returns ALLOW if scanner unavailable."""
        if not content or not content.strip():
            return FirewallResult(
                is_anomalous=False,
                score=0.0,
                decision="allow",
                risk_type="",
                reason="empty_content",
            )
        fw = self.prompt_guard
        if fw is None:
            logger.debug("LlamaFirewall PromptGuard unavailable — skipping prompt-injection scan")
            return FirewallResult(
                is_anomalous=False,
                score=0.0,
                decision="allow",
                risk_type="",
                reason="scanner_unavailable",
            )
        try:
            from llamafirewall import UserMessage

            logger.debug("LlamaFirewall PromptGuard scanning  content_len=%d …", len(content))
            msg = UserMessage(content=content[:32000])
            result = fw.scan(msg)
            fr = self._result_from_scan(result.decision, result.score, result.reason or "default")
            verdict = "BLOCK" if fr.is_anomalous else "ALLOW"
            logger.info(
                "LlamaFirewall PromptGuard → %s  score=%.4f  reason=%s",
                verdict,
                fr.score,
                fr.reason,
            )
            return fr
        except Exception as e:
            logger.warning("LlamaFirewall PromptGuard scan failed: %s", e)
            return FirewallResult(
                is_anomalous=False,
                score=0.0,
                decision="allow",
                risk_type="",
                reason=f"scan_error:{e!s}",
            )

    def check_alignment(
        self,
        user_query: str,
        conversation_history: list[dict],
        suspicious_content: str,
    ) -> FirewallResult:
        """
        AlignmentCheck (AGENT_ALIGNMENT) scan over a trace.
        No-ops (returns ALLOW) if TOGETHER_API_KEY absent or scanner unavailable.
        """
        fw = self.alignment
        if fw is None:
            logger.debug("LlamaFirewall AlignmentCheck unavailable — skipping alignment scan")
            return FirewallResult(
                is_anomalous=False,
                score=0.0,
                decision="allow",
                risk_type="",
                reason="alignment_scanner_unavailable",
            )
        if not suspicious_content or not suspicious_content.strip():
            return FirewallResult(
                is_anomalous=False,
                score=0.0,
                decision="allow",
                risk_type="",
                reason="empty_content",
            )
        try:
            from llamafirewall import AssistantMessage, UserMessage

            logger.debug(
                "LlamaFirewall AlignmentCheck scanning  history_len=%d  content_len=%d …",
                len(conversation_history),
                len(suspicious_content),
            )
            trace: list = []
            if user_query:
                trace.append(UserMessage(content=user_query[:8000]))
            for entry in conversation_history[:20]:
                role = (entry.get("role") or entry.get("type") or "user").lower()
                content = entry.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        p.get("text", str(p)) if isinstance(p, dict) else str(p)
                        for p in content
                    )
                content = str(content)[:8000]
                if role in ("user", "human"):
                    trace.append(UserMessage(content=content))
                else:
                    trace.append(AssistantMessage(content=content))
            trace.append(AssistantMessage(content=suspicious_content[:8000]))
            result = fw.scan_replay(trace)
            fr = self._result_from_scan(result.decision, result.score, result.reason or "default")
            verdict = "BLOCK" if fr.is_anomalous else "ALLOW"
            logger.info(
                "LlamaFirewall AlignmentCheck → %s  score=%.4f  reason=%s",
                verdict,
                fr.score,
                fr.reason,
            )
            return fr
        except Exception as e:
            logger.warning("LlamaFirewall AlignmentCheck scan failed: %s", e)
            return FirewallResult(
                is_anomalous=False,
                score=0.0,
                decision="allow",
                risk_type="",
                reason=f"scan_error:{e!s}",
            )
