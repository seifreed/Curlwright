"""Thin facade around protection policy and Playwright-specific adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from curlwright.domain import BypassAssessment, BypassFailure, ProtectionSnapshot
from curlwright.domain.policy import BypassAction, BypassPolicy, TrustedSession
from curlwright.infrastructure.bypass_artifacts import artifact_directory_name
from curlwright.infrastructure.bypass_classifier import compact_text
from curlwright.infrastructure.protection_runtime import (
    ConsoleTelemetry,
    PlaywrightArtifactStore,
    PlaywrightChallengeActuator,
    PlaywrightPageProbe,
)


@dataclass
class BypassManager:
    artifact_root: Path
    max_attempts: int = 3

    def __init__(self, artifact_root: str | None = None, max_attempts: int = 3):
        self.artifact_root = (
            Path(artifact_root)
            if artifact_root
            else Path.home() / ".curlwright" / "artifacts"
        )
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.max_attempts = max_attempts
        self.policy = BypassPolicy()
        self.page_probe = PlaywrightPageProbe()
        self.challenge_actuator = PlaywrightChallengeActuator()
        self.telemetry = ConsoleTelemetry()
        self.artifact_store = PlaywrightArtifactStore(self.artifact_root)

    def attach_console_capture(self, page) -> list[dict[str, str]]:
        return self.telemetry.attach_console_capture(page)

    async def perform_bypass(
        self,
        *,
        page,
        target_url: str,
        timeout_ms: int,
        trusted_session: bool,
        console_events: list[dict[str, str]],
    ) -> BypassAssessment:
        request_policy = self.policy.build_request_policy(target_url, TrustedSession(trusted_session))
        latest_assessment = BypassAssessment(outcome="challenge", final_url=target_url)

        for attempt_index, navigate_url in enumerate(request_policy.navigation_targets, start=1):
            response = await page.goto(
                navigate_url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            await self.challenge_actuator.stabilize_page(page, attempt_index=attempt_index, timeout_ms=timeout_ms)
            latest_assessment = await self.assess_page(page, response)
            if await self._execute_decision(
                page=page,
                decision=self.policy.decide_page_action(
                    ProtectionSnapshot.from_assessment(latest_assessment),
                    managed_challenge=await self.page_probe.is_managed_challenge(page),
                ),
                target_url=target_url,
                timeout_ms=timeout_ms,
                attempt_index=attempt_index,
            ):
                return latest_assessment

            latest_assessment = await self.assess_page(page, None)
            if await self._execute_decision(
                page=page,
                decision=self.policy.decide_post_action(
                    ProtectionSnapshot.from_assessment(latest_assessment),
                    managed_challenge=await self.page_probe.is_managed_challenge(page),
                ),
                target_url=target_url,
                timeout_ms=timeout_ms,
                attempt_index=attempt_index,
            ):
                return latest_assessment

        artifact_dir = await self.collect_failure_artifacts(
            page=page,
            assessment=latest_assessment,
            console_events=console_events,
            label="bypass-failure",
        )
        raise BypassFailure(
            "Bypass did not reach a trusted page state",
            assessment=latest_assessment,
            artifact_dir=str(artifact_dir),
        )

    async def assess_page(self, page, response) -> BypassAssessment:
        return await self.page_probe.assess_page(page, response)

    def assess_response_payload(self, payload: dict[str, object]) -> BypassAssessment:
        return self.page_probe.assess_response_payload(payload)

    async def collect_failure_artifacts(
        self,
        *,
        page,
        assessment: BypassAssessment,
        console_events: list[dict[str, str]],
        label: str,
    ) -> Path:
        return await self.artifact_store.collect(
            page=page,
            assessment=assessment,
            console_events=console_events,
            label=label,
        )

    async def _execute_decision(
        self,
        *,
        page,
        decision,
        target_url: str,
        timeout_ms: int,
        attempt_index: int,
    ) -> bool:
        if decision.action is BypassAction.RETURN_CLEAR:
            return True
        if decision.action is BypassAction.FAIL_BLOCKED:
            return False
        if decision.action is BypassAction.RESOLVE_TURNSTILE:
            await self.challenge_actuator.resolve_turnstile(page, timeout_ms=timeout_ms)
            return False
        if decision.action is BypassAction.WAIT_MANAGED_CHALLENGE:
            await self.challenge_actuator.wait_for_managed_challenge(page, timeout_ms=timeout_ms)
            if decision.revisit_target:
                await self.challenge_actuator.revisit_target(
                    page,
                    target_url=target_url,
                    timeout_ms=timeout_ms,
                )
            return False
        await self.challenge_actuator.advance_challenge(
            page,
            attempt_index=attempt_index,
            timeout_ms=timeout_ms,
        )
        return False

    async def _stabilize_page(self, page, attempt_index: int, timeout_ms: int) -> None:
        await self.challenge_actuator.stabilize_page(page, attempt_index=attempt_index, timeout_ms=timeout_ms)

    async def _attempt_turnstile_resolution(self, page, timeout_ms: int) -> None:
        await self.challenge_actuator.resolve_turnstile(page, timeout_ms=timeout_ms)

    async def _attempt_challenge_progress(self, page, attempt_index: int, timeout_ms: int) -> None:
        await self.challenge_actuator.advance_challenge(
            page,
            attempt_index=attempt_index,
            timeout_ms=timeout_ms,
        )

    async def _selector_exists(self, page, selector: str) -> bool:
        try:
            return await page.locator(selector).count() > 0
        except Exception:
            return False

    async def _is_managed_challenge(self, page) -> bool:
        return await self.page_probe.is_managed_challenge(page)

    async def _wait_for_managed_challenge(self, page, timeout_ms: int) -> None:
        await self.challenge_actuator.wait_for_managed_challenge(page, timeout_ms=timeout_ms)

    async def _revisit_target_after_challenge(self, page, target_url: str, timeout_ms: int) -> None:
        await self.challenge_actuator.revisit_target(page, target_url=target_url, timeout_ms=timeout_ms)

    def _artifact_directory_name(self, url: str, label: str) -> str:
        return artifact_directory_name(url, label)

    def _build_attempt_urls(self, target_url: str, trusted_session: bool) -> list[str]:
        return list(
            self.policy.build_request_policy(
                target_url,
                TrustedSession(trusted_session),
            ).navigation_targets
        )

    def _base_url(self, target_url: str) -> str:
        parsed = urlparse(target_url)
        return f"{parsed.scheme}://{parsed.netloc}/"

    def _compact_text(self, raw_text: str, limit: int = 500) -> str:
        return compact_text(raw_text, limit=limit)
