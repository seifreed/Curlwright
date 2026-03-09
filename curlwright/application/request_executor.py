"""Application-layer request execution orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse

from curlwright.application.use_cases import (
    BuildExecutionReport,
    ExecuteHttpFetch,
    PersistSessionState,
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
    FetchResponse,
    HttpRuntimePort,
    PageProbePort,
    PersistedSessionPort,
    RequestMetadata,
    RequestParserPort,
    ResponsePayload,
    RuntimeMetadata,
    StateMetadata,
    TelemetryPort,
)
from curlwright.domain.policy import BypassPolicy
from curlwright.runtime import ensure_supported_python

ensure_supported_python()

type HttpCredentials = dict[str, str]
type BrowserSignature = tuple[str | None, bool, tuple[str | None, str | None], str]


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
    ):
        self.browser_manager: BrowserManagerPort | None = None
        self.default_timeout = timeout
        self.headless = headless
        self.user_agent = user_agent
        self.no_gui = no_gui
        self.parser = parser
        self.http_runtime = http_runtime
        self.request_runtime = http_runtime
        self.page_probe = page_probe
        self.challenge_actuator = challenge_actuator
        self.artifact_store = artifact_store
        self.telemetry = telemetry
        self.bypass_policy = bypass_policy
        self.session_store = session_store
        self.domain_state_store = session_store
        self.initialized = False
        self.persist_cookies = persist_cookies
        self.cookie_manager = cookie_store if persist_cookies else None
        self._browser_signature: BrowserSignature | None = None
        self._retry_user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        ]
        self._effective_user_agent = user_agent or self._retry_user_agents[0]
        self.browser_manager_factory = browser_manager_factory
        self.cookie_file = str(self.cookie_manager.cookie_file) if self.cookie_manager else None
        self.state_file = str(self.session_store.state_file)
        self.artifact_root = str(self.artifact_store.artifact_root)
        self.bypass_attempts = bypass_attempts
        self.profile_dir = str(Path(profile_dir).expanduser()) if profile_dir else str(Path.home() / ".curlwright" / "browser-profile")

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
        self.persist_session_state = PersistSessionState(session_store)
        self.build_execution_report = BuildExecutionReport()

    async def _ensure_initialized(self, request: CurlRequest, *, user_agent: str) -> None:
        browser_signature = self._get_browser_signature(request, user_agent)
        if self.initialized and browser_signature == self._browser_signature:
            return
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
            )
        )
        await self.browser_manager.initialize()
        self.initialized = True
        self._browser_signature = browser_signature
        self._effective_user_agent = user_agent

    async def execute(self, curl_command: str, max_retries: int = 3, delay: int = 5) -> ResponsePayload:
        request = self.parser.parse(curl_command)
        execution_meta = self.build_execution_report.start(
            self._build_execution_metadata(
                request=request,
                max_retries=max_retries,
                delay=delay,
            )
        )

        for attempt in range(max_retries):
            effective_user_agent = self._get_retry_user_agent(attempt)
            attempt_record = AttemptRecord(attempt=attempt + 1, user_agent=effective_user_agent)
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
                return reported.to_payload()
            except BypassFailure as error:
                attempt_record.outcome = "bypass_failure"
                attempt_record.error = str(error)
                attempt_record.artifact_dir = error.artifact_dir
                attempt_record.assessment = asdict(error.assessment)
                execution_meta.attempts.append(attempt_record)
                await self._reset_runtime_state()
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                else:
                    raise
            except Exception as error:
                attempt_record.outcome = "error"
                attempt_record.error = str(error)
                execution_meta.attempts.append(attempt_record)
                await self._reset_runtime_state()
                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                else:
                    raise
        raise Exception("Failed to execute request after all retries")

    async def _execute_request(self, request: CurlRequest) -> ExecutionResult:
        if not self.browser_manager:
            raise RuntimeError("Browser manager is not initialized")
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
            self.persist_session_state.record_success(
                domain_key=prepared.domain_key,
                domain=prepared.domain,
                user_agent=self._effective_user_agent,
                proxy=request.proxy,
                profile_dir=self.profile_dir,
                final_url=response_data.url or request.url,
                cookie_names=[cookie.get("name", "") for cookie in context_cookies if cookie.get("name")],
                artifact_dir=artifact_dir,
            )
            return ExecutionResult(response=response_data, outcome=outcome)
        except BypassFailure as error:
            self.persist_session_state.record_failure(
                domain_key=domain_key,
                domain=domain,
                user_agent=self._effective_user_agent,
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

    def _extract_domain(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.hostname or parsed.netloc

    def _extract_base_url(self, url: str) -> str:
        return self.http_runtime.extract_base_url(url)

    def _build_fetch_options(self, request: CurlRequest):
        return self.http_runtime.build_fetch_options(request)

    async def _perform_fetch_request(self, page, request: CurlRequest, timeout_ms: int) -> FetchResponse:
        return await self.http_runtime.perform_fetch_request(page, request, timeout_ms)

    async def _apply_request_context(self, page, request: CurlRequest) -> None:
        await self.http_runtime.apply_request_context(page, request, self._extract_domain)

    async def _warm_up_page(
        self,
        page,
        request: CurlRequest,
        timeout_ms: int,
        *,
        console_events: list[dict[str, str]],
    ) -> None:
        await self.http_runtime.warm_up_page(
            page,
            request,
            timeout_ms,
            cookie_manager=self.cookie_manager,
            trusted_session=self._has_trusted_session(request),
        )

    def _get_effective_timeout(self, request: CurlRequest) -> int:
        return request.timeout or self.default_timeout

    def _get_http_credentials(self, request: CurlRequest) -> HttpCredentials | None:
        if not request.auth:
            return None
        username, password = request.auth
        return {"username": username, "password": password}

    def _get_browser_signature(self, request: CurlRequest, user_agent: str) -> BrowserSignature:
        credentials = request.auth or (None, None)
        return (request.proxy, request.verify_ssl, credentials, user_agent)

    def _get_domain_session_key(self, request: CurlRequest) -> str:
        return "|".join(
            [
                self._extract_domain(request.url),
                request.proxy or "direct",
                self._effective_user_agent,
                self.profile_dir,
            ]
        )

    def _has_trusted_session(self, request: CurlRequest) -> bool:
        if not self.session_store.is_trusted(self._get_domain_session_key(request)):
            return False
        if self.cookie_manager is None:
            return False
        return self.cookie_manager.has_cookies_for_domain(self._extract_domain(request.url))

    def _get_retry_user_agent(self, attempt: int) -> str:
        if self.user_agent:
            return self.user_agent
        return self._retry_user_agents[attempt % len(self._retry_user_agents)]

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
