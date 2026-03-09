"""Pure domain policy for protection-resolution decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse

from curlwright.domain.core import BypassAssessment


class ChallengeState(str, Enum):
    CLEAR = "clear"
    CHALLENGE = "challenge"
    TURNSTILE = "turnstile"
    BLOCKED = "blocked"


class BypassAction(str, Enum):
    RETURN_CLEAR = "return_clear"
    RESOLVE_TURNSTILE = "resolve_turnstile"
    WAIT_MANAGED_CHALLENGE = "wait_managed_challenge"
    ADVANCE_CHALLENGE = "advance_challenge"
    FAIL_BLOCKED = "fail_blocked"


@dataclass(frozen=True)
class TrustedSession:
    active: bool


@dataclass(frozen=True)
class ProtectionSnapshot:
    state: ChallengeState
    final_url: str
    title: str = ""
    status_code: int | None = None
    signals: tuple[str, ...] = ()
    body_excerpt: str = ""

    @property
    def is_clear(self) -> bool:
        return self.state is ChallengeState.CLEAR

    @classmethod
    def from_assessment(cls, assessment: BypassAssessment) -> "ProtectionSnapshot":
        return cls(
            state=ChallengeState(assessment.outcome),
            final_url=assessment.final_url,
            title=assessment.title,
            status_code=assessment.status_code,
            signals=tuple(assessment.indicators),
            body_excerpt=assessment.body_excerpt,
        )


@dataclass(frozen=True)
class RequestPolicy:
    navigation_targets: tuple[str, ...]


@dataclass(frozen=True)
class BypassDecision:
    action: BypassAction
    reason: str
    revisit_target: bool = False


@dataclass(frozen=True)
class ExecutionOutcome:
    kind: str
    status: int | None = None
    final_url: str | None = None
    details: tuple[str, ...] = field(default_factory=tuple)


class BypassPolicy:
    """Decides how the application should react to abstract protection signals."""

    def build_request_policy(self, target_url: str, trusted_session: TrustedSession) -> RequestPolicy:
        base_url = self._base_url(target_url)
        if trusted_session.active:
            return RequestPolicy(navigation_targets=(target_url, target_url, base_url))
        return RequestPolicy(navigation_targets=(target_url, base_url, target_url))

    def decide_page_action(
        self,
        snapshot: ProtectionSnapshot,
        *,
        managed_challenge: bool,
    ) -> BypassDecision:
        if snapshot.state is ChallengeState.CLEAR:
            return BypassDecision(BypassAction.RETURN_CLEAR, "page is already clear")
        if snapshot.state is ChallengeState.BLOCKED:
            return BypassDecision(BypassAction.FAIL_BLOCKED, "page looks terminally blocked")
        if snapshot.state is ChallengeState.TURNSTILE:
            return BypassDecision(BypassAction.RESOLVE_TURNSTILE, "turnstile detected")
        if managed_challenge:
            return BypassDecision(
                BypassAction.WAIT_MANAGED_CHALLENGE,
                "managed challenge detected",
                revisit_target=True,
            )
        return BypassDecision(BypassAction.ADVANCE_CHALLENGE, "challenge requires progression")

    def decide_post_action(
        self,
        snapshot: ProtectionSnapshot,
        *,
        managed_challenge: bool,
    ) -> BypassDecision:
        if snapshot.state is ChallengeState.CLEAR:
            return BypassDecision(BypassAction.RETURN_CLEAR, "page became clear after action")
        if managed_challenge:
            return BypassDecision(
                BypassAction.WAIT_MANAGED_CHALLENGE,
                "managed challenge still active after action",
                revisit_target=True,
            )
        if snapshot.state is ChallengeState.BLOCKED:
            return BypassDecision(BypassAction.FAIL_BLOCKED, "challenge resolved into blocked state")
        return BypassDecision(BypassAction.ADVANCE_CHALLENGE, "challenge still unresolved")

    def evaluate_fetch_result(self, snapshot: ProtectionSnapshot) -> ExecutionOutcome:
        if snapshot.state is ChallengeState.CLEAR:
            return ExecutionOutcome(
                kind="success",
                status=snapshot.status_code,
                final_url=snapshot.final_url,
                details=snapshot.signals,
            )
        return ExecutionOutcome(
            kind="blocked_response",
            status=snapshot.status_code,
            final_url=snapshot.final_url,
            details=snapshot.signals,
        )

    def _base_url(self, target_url: str) -> str:
        parsed = urlparse(target_url)
        return f"{parsed.scheme}://{parsed.netloc}/"
