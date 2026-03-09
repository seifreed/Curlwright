from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from curlwright.application.request_executor import RequestExecutor as ApplicationRequestExecutor
from curlwright.domain import (
    BrowserSessionConfig,
    BypassAssessment,
    CurlRequest,
    FetchResponse,
)
from curlwright.domain.policy import BypassAction
from curlwright.infrastructure.browser_manager import BrowserManager
from curlwright.infrastructure.bypass_manager import BypassManager
from curlwright.infrastructure.parsers import CurlParser
from curlwright.infrastructure.persistence import CookieManager
from curlwright.infrastructure.playwright_runtime import PlaywrightRequestRuntime
from curlwright.interfaces import cli_app
from curlwright.interfaces.sarif import _rule_id_for_exit_code, write_sarif_report


def test_cli_app_helper_and_small_contract_paths(tmp_path):
    request_file = tmp_path / "request.txt"
    request_file.write_text("curl https://example.com/from-file")
    args = type("Args", (), {"file": str(request_file), "curl": None})()

    assert cli_app._resolve_curl_command(args) == "curl https://example.com/from-file"
    cli_app._log_execution_summary({"meta": "not-a-dict"})
    assert _rule_id_for_exit_code(1) == "CW004"
    write_sarif_report(None, result={"status": 200, "headers": {}, "body": "ok"})


def test_parser_cookie_file_reference_and_empty_cookie_store(tmp_path):
    parsed = CurlParser().parse("curl -b @cookies.txt https://example.com")
    assert parsed.cookies == {}

    cookie_file = tmp_path / "cookies.pkl"
    cookie_file.write_bytes(b"\x80\x04]\x94.")
    manager = CookieManager(str(cookie_file))

    class EmptyContext:
        async def add_cookies(self, cookies):
            raise AssertionError(f"unexpected cookies: {cookies}")

    assert asyncio.run(manager.load_cookies(EmptyContext())) is False


def test_browser_manager_unit_paths_cover_remaining_branches(tmp_path):
    assert BrowserManager(user_agent="Mozilla/5.0 Chrome/131.2.3.4")._chrome_major_version() == "131"

    class FailingStarter:
        async def start(self):
            raise RuntimeError("start failure")

    manager = BrowserManager(playwright_factory=lambda: FailingStarter())
    with pytest.raises(RuntimeError, match="start failure"):
        asyncio.run(manager.initialize())

    class FakePage:
        def __init__(self, *, url="https://example.com", closed=False, goto_error=False):
            self.url = url
            self._closed = closed
            self._goto_error = goto_error
            self.evaluate_calls = 0

        def is_closed(self):
            return self._closed

        async def goto(self, *_args, **_kwargs):
            if self._goto_error:
                raise RuntimeError("goto failure")

        async def evaluate(self, *_args, **_kwargs):
            self.evaluate_calls += 1

        async def close(self):
            self._closed = True

    class FakeContext:
        def __init__(self, pages, next_page):
            self.pages = pages
            self._next_page = next_page
            self.closed = False

        async def new_page(self):
            return self._next_page

        async def close(self):
            self.closed = True

    manager = BrowserManager()
    next_page = FakePage(url="https://example.com", closed=False, goto_error=True)
    manager.context = FakeContext([FakePage(url="https://example.com", closed=False)], next_page)
    page = asyncio.run(manager.create_page())
    assert page is next_page
    assert page.evaluate_calls == 1

    manager = BrowserManager()
    blank_page = FakePage(url="about:blank", closed=False, goto_error=True)
    manager.context = FakeContext([], blank_page)
    page = asyncio.run(manager.create_page())
    assert page is blank_page

    class FakeBrowser:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    manager = BrowserManager()
    manager._persistent_context = False
    manager.browser = FakeBrowser()
    manager.context = FakeContext([], blank_page)
    manager.page = FakePage(url="https://example.com", closed=True)
    asyncio.run(manager.close())
    assert manager.browser is None


@pytest.mark.asyncio
async def test_bypass_manager_helper_paths_cover_wrappers():
    manager = BypassManager()

    class SimpleActuator:
        def __init__(self):
            self.calls = []

        async def stabilize_page(self, page, *, attempt_index, timeout_ms):
            self.calls.append(("stabilize", attempt_index, timeout_ms))

        async def resolve_turnstile(self, page, *, timeout_ms):
            self.calls.append(("turnstile", timeout_ms))

        async def advance_challenge(self, page, *, attempt_index, timeout_ms):
            self.calls.append(("advance", attempt_index, timeout_ms))

        async def wait_for_managed_challenge(self, page, *, timeout_ms):
            self.calls.append(("managed", timeout_ms))

        async def revisit_target(self, page, *, target_url, timeout_ms):
            self.calls.append(("revisit", target_url, timeout_ms))

    class SimpleProbe:
        async def is_managed_challenge(self, page):
            return True

    manager.challenge_actuator = SimpleActuator()
    manager.page_probe = SimpleProbe()

    assert await manager._execute_decision(
        page=object(),
        decision=type("Decision", (), {"action": BypassAction.FAIL_BLOCKED, "revisit_target": False})(),
        target_url="https://example.com/path",
        timeout_ms=100,
        attempt_index=2,
    ) is False
    decision = type("Decision", (), {"action": BypassAction.ADVANCE_CHALLENGE, "revisit_target": False})()
    await manager._execute_decision(
        page=object(),
        decision=decision,
        target_url="https://example.com/path",
        timeout_ms=100,
        attempt_index=2,
    )
    await manager._execute_decision(
        page=object(),
        decision=type("Decision", (), {"action": BypassAction.WAIT_MANAGED_CHALLENGE, "revisit_target": True})(),
        target_url="https://example.com/path",
        timeout_ms=100,
        attempt_index=1,
    )

    await manager._execute_decision(
        page=object(),
        decision=type("Decision", (), {"action": BypassAction.WAIT_MANAGED_CHALLENGE, "revisit_target": True})(),
        target_url="https://example.com/path",
        timeout_ms=100,
        attempt_index=1,
    )
    assert await manager._is_managed_challenge(object()) is True
    await manager._wait_for_managed_challenge(object(), 100)
    await manager._revisit_target_after_challenge(object(), "https://example.com/path", 100)
    assert manager._build_attempt_urls("https://example.com/path", True)[0] == "https://example.com/path"
    assert manager._base_url("https://example.com/path") == "https://example.com/"
    assert manager._compact_text("a   b") == "a b"
    assert any(call[0] == "managed" for call in manager.challenge_actuator.calls)


@pytest.mark.asyncio
async def test_playwright_runtime_and_application_executor_remaining_paths(tmp_path):
    runtime = PlaywrightRequestRuntime()

    class Mouse:
        async def move(self, *_args, **_kwargs):
            raise RuntimeError("move failure")

        async def wheel(self, *_args, **_kwargs):
            raise RuntimeError("wheel failure")

    class WarmPage:
        def __init__(self):
            self.mouse = Mouse()
            self.gotos = []

        async def goto(self, url, **_kwargs):
            self.gotos.append(url)
            if len(self.gotos) == 1:
                raise RuntimeError("goto failure")

        async def bring_to_front(self):
            raise RuntimeError("front failure")

        async def evaluate(self, *_args, **_kwargs):
            raise RuntimeError("eval failure")

        async def wait_for_load_state(self, *_args, **_kwargs):
            raise RuntimeError("wait failure")

    page = WarmPage()
    await runtime._simulate_human_warmup(
        page,
        CurlRequest(url="https://example.com/path"),
        timeout_ms=100,
        trusted_session=True,
    )
    assert page.gotos == ["https://example.com", "https://example.com/path"]

    class PageContext:
        async def cookies(self):
            return []

    class FakePage:
        def __init__(self, *, closed=False):
            self._closed = closed
            self.context = PageContext()
            self.closed_count = 0

        def is_closed(self):
            return self._closed

        async def close(self):
            self.closed_count += 1
            self._closed = True

    class BrowserManager:
        def __init__(self):
            self.created = 0

        async def initialize(self):
            return None

        async def create_page(self):
            self.created += 1
            return FakePage(closed=self.created == 1)

        async def close(self):
            return None

    class Factory:
        def __init__(self, manager):
            self.manager = manager

        def create(self, config: BrowserSessionConfig):
            return self.manager

    class HttpRuntime:
        def extract_base_url(self, url):
            return "https://example.com"

        def build_fetch_options(self, request):
            return {"method": request.method}

        async def apply_request_context(self, page, request, extract_domain):
            page.applied = extract_domain(request.url)

        async def warm_up_page(self, page, request, timeout_ms, *, cookie_manager, trusted_session):
            page.warmed = True

        async def perform_fetch_request(self, page, request, timeout_ms):
            return FetchResponse(status=200, headers={}, body="ok", url=request.url)

    class Probe:
        def assess_response_payload(self, payload):
            return BypassAssessment(outcome="clear", final_url=payload["url"])

    class Actuator:
        async def stabilize_page(self, *args, **kwargs):
            return None

        async def resolve_turnstile(self, *args, **kwargs):
            return None

        async def advance_challenge(self, *args, **kwargs):
            return None

        async def wait_for_managed_challenge(self, *args, **kwargs):
            return None

        async def revisit_target(self, *args, **kwargs):
            return None

    class ArtifactStore:
        artifact_root = Path(tmp_path / "artifacts")

        async def collect(self, **kwargs):
            return self.artifact_root

    class Telemetry:
        def attach_console_capture(self, page):
            return []

    class SessionStore:
        state_file = Path(tmp_path / "state.json")

        def is_trusted(self, domain_key, max_age_seconds=3600):
            return False

        def mark_success(self, **kwargs):
            self.success = kwargs

        def mark_failure(self, **kwargs):
            self.failure = kwargs

    manager = BrowserManager()
    executor = ApplicationRequestExecutor(
        parser=CurlParser(),
        browser_manager_factory=Factory(manager),
        http_runtime=HttpRuntime(),
        page_probe=Probe(),
        challenge_actuator=Actuator(),
        artifact_store=ArtifactStore(),
        telemetry=Telemetry(),
        bypass_policy=BypassManager().policy,
        session_store=SessionStore(),
        cookie_store=None,
        headless=True,
        timeout=30,
        no_gui=True,
        profile_dir=str(tmp_path / "profile"),
    )
    executor.resolve_protection = type(
        "ResolveProtection",
        (),
        {"execute": (lambda self, **kwargs: asyncio.sleep(0, result=[]))},
    )()
    request = CurlRequest(url="https://example.com/path")
    await executor._ensure_initialized(request, user_agent=executor._get_retry_user_agent(0))
    await executor._apply_request_context(FakePage(closed=False), request)
    result = await executor._execute_request(request)
    assert result.response.status == 200
    assert manager.created == 2


@pytest.mark.asyncio
async def test_protection_runtime_remaining_defensive_paths():
    from curlwright.infrastructure.protection_runtime import PlaywrightChallengeActuator

    actuator = PlaywrightChallengeActuator()

    class ManagedPage:
        url = "https://example.com/plain"

        async def content(self):
            raise RuntimeError("content failure")

        async def wait_for_load_state(self, *_args, **_kwargs):
            return None

    await actuator.wait_for_managed_challenge(ManagedPage(), timeout_ms=10)

    class Mouse:
        async def click(self, *_args, **_kwargs):
            raise RuntimeError("click failure")

    class Locator:
        async def count(self):
            return 2

        def nth(self, index):
            class Nth:
                async def bounding_box(self_inner):
                    if index == 0:
                        return None
                    return {"x": 1, "y": 2, "width": 10, "height": 20}

            return Nth()

    class ClickPage:
        mouse = Mouse()

        def locator(self, _selector):
            return Locator()

    assert await actuator._click_turnstile_iframe_center(ClickPage()) is False

    class SelectorPage:
        async def wait_for_load_state(self, *_args, **_kwargs):
            return None

    selector_calls = {"count": 0}

    async def fake_ready(_page):
        return False

    async def fake_contains(_page, _patterns):
        return False

    async def fake_exists(_page, _selector):
        selector_calls["count"] += 1
        return True

    actuator._turnstile_response_ready = fake_ready
    actuator._page_contains_any = fake_contains
    actuator._selector_exists = fake_exists
    await actuator._wait_for_turnstile_progress(SelectorPage(), timeout_ms=10, expect_interaction=True)
    assert selector_calls["count"] >= 1
