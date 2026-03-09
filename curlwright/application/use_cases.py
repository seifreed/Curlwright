"""Small application use cases orchestrated by the public request executor."""

from __future__ import annotations

from dataclasses import dataclass

from curlwright.domain import (
    ArtifactStorePort,
    BypassFailure,
    ChallengeActuatorPort,
    ExecutionMetadata,
    ExecutionOutcome,
    ExecutionResult,
    FetchResponse,
    FinalMetadata,
    HttpRuntimePort,
    PageProbePort,
    PersistedSessionPort,
    ProtectionSnapshot,
    RequestPolicy,
    TelemetryPort,
)
from curlwright.domain.policy import BypassAction, BypassDecision, BypassPolicy, TrustedSession


@dataclass(frozen=True)
class PreparedSession:
    page: object
    timeout_ms: int
    trusted_session: bool
    domain: str
    domain_key: str


class PrepareSession:
    def __init__(self, http_runtime: HttpRuntimePort):
        self.http_runtime = http_runtime

    async def execute(
        self,
        *,
        page,
        request,
        timeout_ms: int,
        trusted_session: bool,
        cookie_store,
        extract_domain,
        domain_key: str,
    ) -> PreparedSession:
        await self.http_runtime.apply_request_context(page, request, extract_domain)
        await self.http_runtime.warm_up_page(
            page,
            request,
            timeout_ms,
            cookie_manager=cookie_store,
            trusted_session=trusted_session,
        )
        return PreparedSession(
            page=page,
            timeout_ms=timeout_ms,
            trusted_session=trusted_session,
            domain=extract_domain(request.url),
            domain_key=domain_key,
        )


class ResolveProtection:
    def __init__(
        self,
        *,
        policy: BypassPolicy,
        page_probe: PageProbePort,
        challenge_actuator: ChallengeActuatorPort,
        artifact_store: ArtifactStorePort,
        telemetry: TelemetryPort,
    ):
        self.policy = policy
        self.page_probe = page_probe
        self.challenge_actuator = challenge_actuator
        self.artifact_store = artifact_store
        self.telemetry = telemetry

    async def execute(
        self,
        *,
        page,
        target_url: str,
        timeout_ms: int,
        trusted_session: bool,
    ) -> list[dict[str, str]]:
        console_events = self.telemetry.attach_console_capture(page)
        request_policy = self.policy.build_request_policy(target_url, TrustedSession(trusted_session))
        latest_assessment = None

        for attempt_index, navigate_url in enumerate(request_policy.navigation_targets, start=1):
            response = await page.goto(
                navigate_url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            await self.challenge_actuator.stabilize_page(page, attempt_index=attempt_index, timeout_ms=timeout_ms)
            latest_assessment = await self.page_probe.assess_page(page, response)
            initial_decision = self.policy.decide_page_action(
                ProtectionSnapshot.from_assessment(latest_assessment),
                managed_challenge=await self.page_probe.is_managed_challenge(page),
            )
            if await self._apply_decision(
                page=page,
                decision=initial_decision,
                target_url=target_url,
                timeout_ms=timeout_ms,
                attempt_index=attempt_index,
            ):
                return console_events

            latest_assessment = await self.page_probe.assess_page(page, None)
            follow_up_decision = self.policy.decide_post_action(
                ProtectionSnapshot.from_assessment(latest_assessment),
                managed_challenge=await self.page_probe.is_managed_challenge(page),
            )
            if await self._apply_decision(
                page=page,
                decision=follow_up_decision,
                target_url=target_url,
                timeout_ms=timeout_ms,
                attempt_index=attempt_index,
            ):
                return console_events

        assert latest_assessment is not None
        artifact_dir = await self.artifact_store.collect(
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

    async def _apply_decision(
        self,
        *,
        page,
        decision: BypassDecision,
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


class ExecuteHttpFetch:
    def __init__(
        self,
        *,
        http_runtime: HttpRuntimePort,
        page_probe: PageProbePort,
        artifact_store: ArtifactStorePort,
        policy: BypassPolicy,
    ):
        self.http_runtime = http_runtime
        self.page_probe = page_probe
        self.artifact_store = artifact_store
        self.policy = policy

    async def execute(
        self,
        *,
        page,
        request,
        timeout_ms: int,
        console_events: list[dict[str, str]],
    ) -> tuple[FetchResponse, ExecutionOutcome, str | None]:
        response = await self.http_runtime.perform_fetch_request(page, request, timeout_ms)
        assessment = self.page_probe.assess_response_payload(response.to_payload())
        outcome = self.policy.evaluate_fetch_result(ProtectionSnapshot.from_assessment(assessment))
        if outcome.kind == "success":
            return response, outcome, None

        artifact_dir = await self.artifact_store.collect(
            page=page,
            assessment=assessment,
            console_events=console_events,
            label="blocked-response",
        )
        raise BypassFailure(
            "Bypass succeeded superficially but final response still looks blocked",
            assessment=assessment,
            artifact_dir=str(artifact_dir),
        )


class PersistSessionState:
    def __init__(self, session_store: PersistedSessionPort):
        self.session_store = session_store

    def record_success(
        self,
        *,
        domain_key: str,
        domain: str,
        user_agent: str,
        proxy: str | None,
        profile_dir: str | None,
        final_url: str,
        cookie_names: list[str],
        artifact_dir: str | None,
    ) -> None:
        self.session_store.mark_success(
            domain_key=domain_key,
            domain=domain,
            user_agent=user_agent,
            proxy=proxy,
            profile_dir=profile_dir,
            final_url=final_url,
            cookie_names=cookie_names,
            artifact_dir=artifact_dir,
        )

    def record_failure(
        self,
        *,
        domain_key: str,
        domain: str,
        user_agent: str,
        proxy: str | None,
        profile_dir: str | None,
        final_url: str | None,
        artifact_dir: str | None,
    ) -> None:
        self.session_store.mark_failure(
            domain_key=domain_key,
            domain=domain,
            user_agent=user_agent,
            proxy=proxy,
            profile_dir=profile_dir,
            final_url=final_url,
            artifact_dir=artifact_dir,
        )


class BuildExecutionReport:
    def start(self, execution_meta: ExecutionMetadata) -> ExecutionMetadata:
        return execution_meta

    def complete(
        self,
        *,
        result: ExecutionResult,
        execution_meta: ExecutionMetadata,
        outcome: ExecutionOutcome,
        fallback_url: str,
    ) -> ExecutionResult:
        execution_meta.final = FinalMetadata(
            status=outcome.status or result.response.status,
            url=outcome.final_url or result.response.url or fallback_url,
        )
        result.meta = execution_meta
        return result
