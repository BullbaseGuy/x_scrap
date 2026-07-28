from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from x_scrap.adapters.base import RateLimited, TransientUpstreamError
from x_scrap.domain.models import iso_utc
from x_scrap.security import redact_text

from .retry import RetryPolicy

_VOLATILE_NUMBER_RE = re.compile(r"\b\d{2,}\b")


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    retry: bool
    category: str
    attempt: int
    delay_seconds: float
    root_cause: str
    reset_at: str | None = None
    exhausted_reason: str | None = None


class RecoveryBudget:
    """Track bounded transient retries and reset-aware rate-limit waits per scope."""

    def __init__(self, policy: RetryPolicy):
        self.policy = policy
        self.total_transient_failures = 0
        self.rate_limit_waits = 0
        self.root_failures: Counter[str] = Counter()

    def decide(self, exc: Exception, *, now: datetime) -> RecoveryDecision:
        root = root_cause(exc)
        if isinstance(exc, RateLimited):
            self.rate_limit_waits += 1
            if self.rate_limit_waits > self.policy.rate_limit_retry_limit:
                return RecoveryDecision(
                    retry=False,
                    category="RATE_LIMIT",
                    attempt=self.rate_limit_waits,
                    delay_seconds=0,
                    root_cause=root,
                    reset_at=iso_utc(exc.reset_at),
                    exhausted_reason="RATE_LIMIT_RETRY_BUDGET_EXHAUSTED",
                )
            return RecoveryDecision(
                retry=True,
                category="RATE_LIMIT",
                attempt=self.rate_limit_waits,
                delay_seconds=self.policy.rate_limit_delay(
                    exc.reset_at,
                    now=now,
                    fallback_attempt=self.rate_limit_waits,
                ),
                root_cause=root,
                reset_at=iso_utc(exc.reset_at),
            )

        if not isinstance(exc, TransientUpstreamError):
            raise TypeError(f"unsupported recoverable error: {type(exc).__name__}")
        self.total_transient_failures += 1
        self.root_failures[root] += 1
        exhausted_reason = None
        if self.total_transient_failures > self.policy.infrastructure_retry_limit:
            exhausted_reason = "INFRASTRUCTURE_RETRY_BUDGET_EXHAUSTED"
        elif self.root_failures[root] > self.policy.same_root_cause_limit:
            exhausted_reason = "SAME_ROOT_CAUSE_RETRY_BUDGET_EXHAUSTED"
        return RecoveryDecision(
            retry=exhausted_reason is None,
            category="TRANSIENT",
            attempt=self.total_transient_failures,
            delay_seconds=(
                self.policy.delay_for_attempt(self.total_transient_failures)
                if exhausted_reason is None
                else 0
            ),
            root_cause=root,
            exhausted_reason=exhausted_reason,
        )


def root_cause(exc: Exception) -> str:
    message = redact_text(str(exc)) or type(exc).__name__
    normalized = _VOLATILE_NUMBER_RE.sub("<n>", message.strip().casefold())
    return f"{type(exc).__name__}:{normalized[:240]}"
