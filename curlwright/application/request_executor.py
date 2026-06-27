"""Application-layer request execution orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse

from curlwright.application.use_cases import (
    BuildExecutionReport,
    ExecuteHttpFetch,
    PrepareSession,
    ResolveProtection,
)
from curlwright.domain import (
    ArtifactStorePort,
    AttemptRecord,
    BrowserManagerFactoryPort,
    BrowserManagerPort,
    BrowserSessionConfig,
    BypassFailure,
    ChallengeActuatorPort,
    CookieStorePort,
    CurlRequest,
    ExecutionMetadata,
    ExecutionResult,
    HttpRuntimePort,
    PageProbePort,
    PersistedSessionPort,
    ProtectionSnapshot,
    RequestMetadata,
    RequestParserPort,
    ResponsePayload,
    RuntimeMetadata,
    StateMetadata,
    TelemetryPort,
)
from curlwright.domain.policy import BypassPolicy
from curlwright.infrastructure.logging import setup_logger
from curlwright.runtime import ensure_supported_python

ensure_supported_python()

logger = setup_logger(__name__)

type HttpCredentials = dict[str, str]
type BrowserSignature = tuple[str | None, bool, tuple[str | None, str | None], str | None]


class RequestExecutor:
    """Executes curl requests through application use cases and fine-grained ports."""

    def __init__(
        self,
        *,
        parser: RequestParserPort,
        browser_manager_factory: BrowserManagerFactoryPort,
        http_runtime: HttpRuntimePort,
        page_probe: PageProbePort,
        challenge_actuator: ChallengeActuatorPort,
        artifact_store: ArtifactStorePort,
        telemetry: TelemetryPort,
        bypass_policy: BypassPolicy,
        session_store: PersistedSessionPort,
        cookie_store: CookieStorePort | None,
        headless: bool = False,
        timeout: int = 30,
        user_agent: str | None = None,
        no_gui: bool = False,
        persist_cookies: bool = True,
        bypass_attempts: int = 3,
        profile_dir: str | None = None,
        engine: str = "patchright",
        fast: bool = False,
    ):
        self.browser_manager: BrowserManagerPort | None = None
        self.default_timeout = timeout
        self.headless = headless
        self.engine = engine
        self.fast = fast
        self.user_agent = user_agent
        self.no_gui = no_gui
        self.parser = parser
        self.http_runtime = http_runtime
        self.page_probe = page_probe
        self.challenge_actuator = challenge_actuator
        self.artifact_store = artifact_store
        self.telemetry = telemetry
        self.bypass_policy = bypass_policy
        self.session_store = session_store
        self.initialized = False
        self.persist_cookies = persist_cookies
        self.cookie_manager = cookie_store if persist_cookies else None
        self._browser_signature: BrowserSignature | None = None
        # When no user agent is pinned we let real Chrome use its own native UA
        # (None), which keeps the UA consistent with the browser's client hints.
        self._effective_user_agent = user_agent
        self.browser_manager_factory = browser_manager_factory
        self.cookie_file = str(self.cookie_manager.cookie_file) if self.cookie_manager else None
        self.state_file = str(self.session_store.state_file)
        self.artifact_root = str(self.artifact_store.artifact_root)
        self.bypass_attempts = bypass_attempts
        self.profile_dir = (
            str(Path(profile_dir).expanduser())
            if profile_dir
            else str(Path.home() / ".curlwright" / "browser-profile")
        )

        self.prepare_session = PrepareSession(http_runtime)
        self.resolve_protection = ResolveProtection(
            policy=bypass_policy,
            page_probe=page_probe,
            challenge_actuator=challenge_actuator,
            artifact_store=artifact_store,
            telemetry=telemetry,
        )
        self.execute_http_fetch = ExecuteHttpFetch(
            http_runtime=http_runtime,
            page_probe=page_probe,
            artifact_store=artifact_store,
            policy=bypass_policy,
        )
        self.build_execution_report = BuildExecutionReport()

    async def _ensure_initialized(self, request: CurlRequest, *, user_agent: str | None) -> None:
        browser_signature = self._get_browser_signature(request, user_agent)
        if self.initialized and browser_signature == self._browser_signature:
            return
        logger.debug(
            "Building browser manager (headless=%s, user_agent=%s)", self.headless, user_agent
        )
        if self.browser_manager:
            await self.browser_manager.close()
        self.browser_manager = self.browser_manager_factory.create(
            BrowserSessionConfig(
                headless=self.headless,
                user_agent=user_agent,
                no_gui=self.no_gui,
                proxy=request.proxy,
                verify_ssl=request.verify_ssl,
                http_credentials=self._get_http_credentials(request),
                profile_dir=self.profile_dir,
                engine=self.engine,
            )
        )
        await self.browser_manager.initialize()
        self.initialized = True
        self._browser_signature = browser_signature
        self._effective_user_agent = user_agent

    async def execute(
        self, curl_command: str, max_retries: int = 3, delay: int = 5
    ) -> ResponsePayload:
        # The request must be attempted at least once; a non-positive retry
        # count would otherwise skip the loop and fail without ever trying.
        max_retries = max(1, max_retries)
        delay = max(0, delay)
        request = self.parser.parse(curl_command)
        execution_meta = self._build_execution_metadata(
            request=request,
            max_retries=max_retries,
            delay=delay,
        )
        logger.info(
            "Executing %s request to %s (max_retries=%s)", request.method, request.url, max_retries
        )

        for attempt in range(max_retries):
            effective_user_agent = self._get_retry_user_agent(attempt)
            attempt_record = AttemptRecord(
                attempt=attempt + 1, user_agent=effective_user_agent or "chrome-native"
            )
            try:
                await self._ensure_initialized(request, user_agent=effective_user_agent)
                result = await self._execute_request(request)
                attempt_record.outcome = "success"
                execution_meta.attempts.append(attempt_record)
                reported = self.build_execution_report.complete(
                    result=result,
                    execution_meta=execution_meta,
                    outcome=result.outcome,
                    fallback_url=request.url,
                )
                logger.info(
                    "Request to %s succeeded on attempt %s/%s (HTTP %s)",
                    request.url,
                    attempt + 1,
                    max_retries,
                    result.response.status,
                )
                return reported.to_payload()
            except BypassFailure as error:
                attempt_record.outcome = "bypass_failure"
                attempt_record.error = str(error)
                attempt_record.artifact_dir = error.artifact_dir
                attempt_record.assessment = asdict(error.assessment)
                execution_meta.attempts.append(attempt_record)
                await self._reset_runtime_state()
                if attempt < max_retries - 1:
                    logger.warning(
                        "Attempt %s/%s for %s hit a bypass failure (%s); retrying in %ss",
                        attempt + 1,
                        max_retries,
                        request.url,
                        error,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Bypass failed for %s after %s attempt(s): %s",
                        request.url,
                        max_retries,
                        error,
                    )
                    raise
            except Exception as error:
                attempt_record.outcome = "error"
                attempt_record.error = str(error)
                execution_meta.attempts.append(attempt_record)
                await self._reset_runtime_state()
                if attempt < max_retries - 1:
                    logger.warning(
                        "Attempt %s/%s for %s errored (%s); retrying in %ss",
                        attempt + 1,
                        max_retries,
                        request.url,
                        error,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Request to %s failed after %s attempt(s): %s",
                        request.url,
                        max_retries,
                        error,
                    )
                    raise
        raise Exception("Failed to execute request after all retries")

    async def _execute_request(self, request: CurlRequest) -> ExecutionResult:
        if not self.browser_manager:
            raise RuntimeError("Browser manager is not initialized")
        if self.engine == "nodriver":
            return await self._execute_request_nodriver(request)
        page = await self.browser_manager.create_page()
        effective_timeout_ms = self._get_effective_timeout(request) * 1000
        domain = self._extract_domain(request.url)
        domain_key = self._get_domain_session_key(request)
        artifact_dir: str | None = None
        try:
            prepared = await self.prepare_session.execute(
                page=page,
                request=request,
                timeout_ms=effective_timeout_ms,
                trusted_session=self._has_trusted_session(request),
                cookie_store=self.cookie_manager,
                extract_domain=self._extract_domain,
                domain_key=domain_key,
                fast=self.fast,
            )
            if page.is_closed():
                page = await self.browser_manager.create_page()
                prepared = await self.prepare_session.execute(
                    page=page,
                    request=request,
                    timeout_ms=effective_timeout_ms,
                    trusted_session=self._has_trusted_session(request),
                    cookie_store=self.cookie_manager,
                    extract_domain=self._extract_domain,
                    domain_key=domain_key,
                )
            console_events = await self.resolve_protection.execute(
                page=prepared.page,
                target_url=request.url,
                timeout_ms=prepared.timeout_ms,
                trusted_session=prepared.trusted_session,
            )
            response_data, outcome, artifact_dir = await self.execute_http_fetch.execute(
                page=prepared.page,
                request=request,
                timeout_ms=prepared.timeout_ms,
                console_events=console_events,
            )
            context_cookies = await prepared.page.context.cookies()
            self.session_store.mark_success(
                domain_key=prepared.domain_key,
                domain=prepared.domain,
                user_agent=self._effective_user_agent or "chrome-native",
                proxy=request.proxy,
                profile_dir=self.profile_dir,
                final_url=response_data.url or request.url,
                cookie_names=[
                    cookie.get("name", "") for cookie in context_cookies if cookie.get("name")
                ],
                artifact_dir=artifact_dir,
            )
            return ExecutionResult(response=response_data, outcome=outcome)
        except BypassFailure as error:
            self.session_store.mark_failure(
                domain_key=domain_key,
                domain=domain,
                user_agent=self._effective_user_agent or "chrome-native",
                proxy=request.proxy,
                profile_dir=self.profile_dir,
                final_url=error.assessment.final_url,
                artifact_dir=error.artifact_dir,
            )
            raise
        finally:
            if self.cookie_manager:
                await self.cookie_manager.save_cookies(page.context)
            if not page.is_closed():
                await page.close()

    async def _execute_request_nodriver(self, request: CurlRequest) -> ExecutionResult:
        # The nodriver engine clears the challenge on navigation and reads the
        # page back through an in-page fetch; it does not go through the
        # page/use-case pipeline. Classification and session bookkeeping are
        # reused so the outcome is identical to the Patchright path.
        if not self.browser_manager:
            raise RuntimeError("Browser manager is not initialized")
        effective_timeout_ms = self._get_effective_timeout(request) * 1000
        domain = self._extract_domain(request.url)
        domain_key = self._get_domain_session_key(request)
        response_data, cookie_names, html = await self.browser_manager.fetch(
            request, timeout_ms=effective_timeout_ms
        )
        assessment = self.page_probe.assess_response_payload(response_data.to_payload())
        outcome = self.bypass_policy.evaluate_fetch_result(
            ProtectionSnapshot.from_assessment(assessment)
        )
        if outcome.kind == "success":
            self.session_store.mark_success(
                domain_key=domain_key,
                domain=domain,
                user_agent=self._effective_user_agent or "chrome-native",
                proxy=request.proxy,
                profile_dir=self.profile_dir,
                final_url=response_data.url or request.url,
                cookie_names=cookie_names,
                artifact_dir=None,
            )
            return ExecutionResult(response=response_data, outcome=outcome)
        artifact_dir = self._save_nodriver_artifact(request.url, html)
        self.session_store.mark_failure(
            domain_key=domain_key,
            domain=domain,
            user_agent=self._effective_user_agent or "chrome-native",
            proxy=request.proxy,
            profile_dir=self.profile_dir,
            final_url=assessment.final_url,
            artifact_dir=artifact_dir,
        )
        raise BypassFailure(
            "Bypass (nodriver) did not reach a trusted page state",
            assessment=assessment,
            artifact_dir=artifact_dir,
        )

    def _save_nodriver_artifact(self, url: str, html: str) -> str | None:
        try:
            from curlwright.infrastructure.bypass_artifacts import artifact_directory_name

            artifact_dir = Path(self.artifact_root) / artifact_directory_name(
                url, "nodriver-blocked"
            )
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "page.html").write_text(html or "")
            logger.info("Saved nodriver blocked-response diagnostics to %s", artifact_dir)
            return str(artifact_dir)
        except Exception:
            logger.debug("nodriver artifact save failed", exc_info=True)
            return None

    def _extract_domain(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.hostname or parsed.netloc

    def _get_effective_timeout(self, request: CurlRequest) -> int:
        # Clamp to at least one second; a zero/negative timeout collapses the
        # navigation/fetch budget to 0ms and surfaces opaque browser errors.
        return max(1, request.timeout or self.default_timeout)

    def _get_http_credentials(self, request: CurlRequest) -> HttpCredentials | None:
        if not request.auth:
            return None
        username, password = request.auth
        return {"username": username, "password": password}

    def _get_browser_signature(
        self, request: CurlRequest, user_agent: str | None
    ) -> BrowserSignature:
        credentials = request.auth or (None, None)
        return (request.proxy, request.verify_ssl, credentials, user_agent)

    def _get_domain_session_key(self, request: CurlRequest) -> str:
        return "|".join(
            [
                self._extract_domain(request.url),
                request.proxy or "direct",
                self._effective_user_agent or "chrome-native",
                self.profile_dir,
            ]
        )

    def _has_trusted_session(self, request: CurlRequest) -> bool:
        if not self.session_store.is_trusted(self._get_domain_session_key(request)):
            return False
        if self.cookie_manager is None:
            return False
        return self.cookie_manager.has_cookies_for_domain(self._extract_domain(request.url))

    def _get_retry_user_agent(self, attempt: int) -> str | None:
        # A pinned --user-agent wins; otherwise None lets Chrome use its native
        # UA. There is no fake-UA rotation: real Chrome's UA is the stealthy one.
        return self.user_agent

    async def _reset_runtime_state(self) -> None:
        if self.browser_manager:
            await self.browser_manager.close()
        self.browser_manager = None
        self.initialized = False
        self._browser_signature = None

    async def close(self):
        if self.initialized and self.browser_manager:
            await self.browser_manager.close()
            self.initialized = False
            self.browser_manager = None
            self._browser_signature = None

    def _build_execution_metadata(
        self,
        *,
        request: CurlRequest,
        max_retries: int,
        delay: int,
    ) -> ExecutionMetadata:
        domain_key = self._get_domain_session_key(request)
        return ExecutionMetadata(
            request=RequestMetadata(
                url=request.url,
                method=request.method,
                proxy=request.proxy,
                verify_ssl=request.verify_ssl,
                timeout=self._get_effective_timeout(request),
                follow_redirects=request.follow_redirects,
            ),
            runtime=RuntimeMetadata(
                headless=self.headless,
                no_gui=self.no_gui,
                persist_cookies=self.persist_cookies,
                cookie_file=self.cookie_file,
                state_file=self.state_file,
                artifact_dir=self.artifact_root,
                profile_dir=self.profile_dir,
                persistent_profile=True,
                bypass_attempts=self.bypass_attempts,
                max_retries=max_retries,
                retry_delay_seconds=delay,
            ),
            state=StateMetadata(
                domain_key=domain_key,
                trusted_session_before_request=self._has_trusted_session(request),
            ),
        )
