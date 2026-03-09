"""Single composition root for concrete CurlWright runtime wiring."""

from __future__ import annotations

from pathlib import Path

from curlwright.application import RequestExecutor as ApplicationRequestExecutor
from curlwright.domain.policy import BypassPolicy
from curlwright.infrastructure.factories import DefaultBrowserManagerFactory
from curlwright.infrastructure.parsers import CurlParser
from curlwright.infrastructure.persistence import CookieManager, DomainStateStore
from curlwright.infrastructure.playwright_runtime import PlaywrightRequestRuntime
from curlwright.infrastructure.protection_runtime import (
    ConsoleTelemetry,
    PlaywrightArtifactStore,
    PlaywrightChallengeActuator,
    PlaywrightPageProbe,
)


def create_request_executor(
    *,
    headless: bool = False,
    timeout: int = 30,
    user_agent: str | None = None,
    no_gui: bool = False,
    cookie_file: str | None = None,
    persist_cookies: bool = True,
    bypass_state_file: str | None = None,
    artifact_dir: str | None = None,
    bypass_attempts: int = 3,
    profile_dir: str | None = None,
) -> ApplicationRequestExecutor:
    cookie_store = CookieManager(cookie_file) if persist_cookies else None
    artifact_root = (
        Path(artifact_dir).expanduser()
        if artifact_dir
        else Path.home() / ".curlwright" / "artifacts"
    )
    return ApplicationRequestExecutor(
        parser=CurlParser(),
        browser_manager_factory=DefaultBrowserManagerFactory(),
        http_runtime=PlaywrightRequestRuntime(),
        page_probe=PlaywrightPageProbe(),
        challenge_actuator=PlaywrightChallengeActuator(),
        artifact_store=PlaywrightArtifactStore(artifact_root),
        telemetry=ConsoleTelemetry(),
        bypass_policy=BypassPolicy(),
        session_store=DomainStateStore(bypass_state_file),
        cookie_store=cookie_store,
        headless=headless,
        timeout=timeout,
        user_agent=user_agent,
        no_gui=no_gui,
        persist_cookies=persist_cookies,
        bypass_attempts=bypass_attempts,
        profile_dir=profile_dir,
    )
