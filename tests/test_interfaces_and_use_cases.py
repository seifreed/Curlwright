from __future__ import annotations

import json
from pathlib import Path

import pytest

import curlwright.contracts as contracts_facade
import curlwright.infrastructure.playwright as playwright_exports
import curlwright.sarif as sarif_facade
from curlwright.application import (
    BuildExecutionReport,
    ExecuteHttpFetch,
    PersistSessionState,
    PrepareSession,
    ResolveProtection,
)
from curlwright.domain import (
    BypassAssessment,
    BypassFailure,
    ExecutionMetadata,
    ExecutionResult,
    FetchResponse,
    RequestMetadata,
    RuntimeMetadata,
    StateMetadata,
)
from curlwright.domain.policy import (
    BypassAction,
    BypassDecision,
    BypassPolicy,
    ChallengeState,
    ProtectionSnapshot,
    TrustedSession,
)
from curlwright.interfaces.contracts import (
    build_failure_payload,
    build_success_payload,
    get_exit_code,
    serialize_output_payload,
)
from curlwright.interfaces.sarif import build_sarif_report, write_sarif_report, _level_for_error, _rule_id_for_exit_code
from curlwright.infrastructure.browser_stealth import chrome_major_version
from curlwright.infrastructure.protection_runtime import ConsoleTelemetry, PlaywrightChallengeActuator, PlaywrightPageProbe


def _execution_meta() -> ExecutionMetadata:
    return ExecutionMetadata(
        request=RequestMetadata(
            url="https://example.com",
            method="GET",
            proxy=None,
            verify_ssl=True,
            timeout=30,
            follow_redirects=False,
        ),
        runtime=RuntimeMetadata(
            headless=True,
            no_gui=True,
            persist_cookies=True,
            cookie_file="cookies.pkl",
            state_file="state.json",
            artifact_dir="artifacts",
            profile_dir="profile",
            persistent_profile=True,
            bypass_attempts=3,
            max_retries=1,
            retry_delay_seconds=0,
        ),
        state=StateMetadata(
            domain_key="example.com|direct|ua|profile",
            trusted_session_before_request=False,
        ),
    )


class FakeRuntime:
    def __init__(self, response: FetchResponse | None = None):
        self.calls: list[tuple[str, object]] = []
        self.response = response or FetchResponse(status=200, headers={}, body="ok", url="https://example.com")

    async def apply_request_context(self, page, request, extract_domain):
        self.calls.append(("apply", extract_domain(request.url)))

    async def warm_up_page(self, page, request, timeout_ms, *, cookie_manager, trusted_session):
        self.calls.append(("warmup", timeout_ms, trusted_session, cookie_manager))

    async def perform_fetch_request(self, page, request, timeout_ms):
        self.calls.append(("fetch", timeout_ms))
        return self.response


class FakeTelemetry:
    def __init__(self):
        self.events = [{"type": "log", "text": "hello"}]

    def attach_console_capture(self, page):
        return list(self.events)


class FakeArtifactStore:
    artifact_root = Path(".artifacts/test")

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def collect(self, *, page, assessment, console_events, label):
        self.calls.append((assessment.outcome, label))
        return Path("/tmp/failure-artifacts")


class FakeActuator:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []

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


class FakeProbe:
    def __init__(self, page_assessments=None, managed=None, response_assessment=None):
        self.page_assessments = list(page_assessments or [])
        self.managed = list(managed or [])
        self.response_assessment = response_assessment or BypassAssessment(
            outcome="clear",
            final_url="https://example.com",
        )

    async def assess_page(self, page, response):
        return self.page_assessments.pop(0)

    async def is_managed_challenge(self, page):
        return self.managed.pop(0)

    def assess_response_payload(self, payload):
        return self.response_assessment


class FakePage:
    def __init__(self):
        self.goto_calls: list[str] = []
        self.url = "about:blank"

    async def goto(self, url, **_kwargs):
        self.url = url
        self.goto_calls.append(url)
        return {"url": url}


class FakeSessionStore:
    state_file = Path("state.json")

    def __init__(self):
        self.success_calls = []
        self.failure_calls = []

    def mark_success(self, **kwargs):
        self.success_calls.append(kwargs)

    def mark_failure(self, **kwargs):
        self.failure_calls.append(kwargs)


def test_contract_helpers_cover_success_and_failure_paths():
    result = ExecutionResult(
        response=FetchResponse(status=200, headers={"x-test": "1"}, body="body", url="https://example.com"),
        meta=_execution_meta(),
    )
    failure = BypassFailure(
        "blocked",
        assessment=BypassAssessment(outcome="blocked", final_url="https://example.com", indicators=["status:403"]),
        artifact_dir="/tmp/artifacts",
    )

    success_payload = build_success_payload(result)
    assert success_payload["kind"] == "curlwright-result"
    assert serialize_output_payload(result, json_output=False) == "body"
    assert '"schema_version": 1' in serialize_output_payload(result, json_output=True)

    failure_payload = build_failure_payload(failure)
    assert failure_payload["artifact_dir"] == "/tmp/artifacts"
    assert get_exit_code(failure) == 10
    assert get_exit_code(ValueError("bad")) == 12
    assert get_exit_code(RuntimeError("boom")) == 1

    assert contracts_facade.build_success_payload(result)["ok"] is True
    assert contracts_facade.build_failure_payload(failure)["ok"] is False


def test_sarif_helpers_cover_success_error_and_file_output(tmp_path):
    result = ExecutionResult(
        response=FetchResponse(status=204, headers={}, body="", url="https://example.com"),
        meta=_execution_meta(),
    )
    failure = BypassFailure(
        "blocked",
        assessment=BypassAssessment(outcome="blocked", final_url="https://example.com"),
        artifact_dir=str(tmp_path / "artifacts"),
    )

    report = build_sarif_report(result=result)
    assert report["runs"][0]["results"][0]["ruleId"] == "CW000"

    error_report = build_sarif_report(error=failure)
    assert error_report["runs"][0]["results"][0]["ruleId"] == "CW001"
    assert "locations" in error_report["runs"][0]["results"][0]

    output = tmp_path / "reports" / "out.sarif"
    write_sarif_report(str(output), result=result)
    assert output.exists()
    assert json.loads(output.read_text())["version"] == "2.1.0"

    assert sarif_facade.build_sarif_report(error=failure)["runs"][0]["results"][0]["level"] == "warning"

    with pytest.raises(ValueError):
        build_sarif_report()


def test_policy_covers_decision_matrix():
    policy = BypassPolicy()
    clear = ProtectionSnapshot(state=ChallengeState.CLEAR, final_url="https://example.com")
    blocked = ProtectionSnapshot(state=ChallengeState.BLOCKED, final_url="https://example.com")
    turnstile = ProtectionSnapshot(state=ChallengeState.TURNSTILE, final_url="https://example.com")
    challenge = ProtectionSnapshot(state=ChallengeState.CHALLENGE, final_url="https://example.com", signals=("x",))

    assert clear.is_clear is True
    assert policy.build_request_policy("https://example.com/path", TrustedSession(True)).navigation_targets[-1] == "https://example.com/"
    assert policy.decide_page_action(clear, managed_challenge=False).action is BypassAction.RETURN_CLEAR
    assert policy.decide_page_action(blocked, managed_challenge=False).action is BypassAction.FAIL_BLOCKED
    assert policy.decide_page_action(turnstile, managed_challenge=False).action is BypassAction.RESOLVE_TURNSTILE
    assert policy.decide_page_action(challenge, managed_challenge=True).action is BypassAction.WAIT_MANAGED_CHALLENGE
    assert policy.decide_post_action(challenge, managed_challenge=False).action is BypassAction.ADVANCE_CHALLENGE
    assert policy.decide_post_action(blocked, managed_challenge=False).action is BypassAction.FAIL_BLOCKED
    outcome = policy.evaluate_fetch_result(challenge)
    assert outcome.kind == "blocked_response"
    snapshot = ProtectionSnapshot.from_assessment(BypassAssessment(outcome="clear", final_url="https://example.com"))
    assert snapshot.state is ChallengeState.CLEAR


@pytest.mark.asyncio
async def test_use_cases_cover_prepare_resolve_fetch_persist_and_report():
    runtime = FakeRuntime()
    page = FakePage()
    request = type("Request", (), {"url": "https://example.com/path"})()

    prepared = await PrepareSession(runtime).execute(
        page=page,
        request=request,
        timeout_ms=1500,
        trusted_session=True,
        cookie_store="cookie-store",
        extract_domain=lambda url: "example.com",
        domain_key="dk",
    )
    assert prepared.domain == "example.com"
    assert runtime.calls[0][0] == "apply"

    clear_assessment = BypassAssessment(outcome="clear", final_url="https://example.com/path")
    resolver = ResolveProtection(
        policy=BypassPolicy(),
        page_probe=FakeProbe(page_assessments=[clear_assessment], managed=[False]),
        challenge_actuator=FakeActuator(),
        artifact_store=FakeArtifactStore(),
        telemetry=FakeTelemetry(),
    )
    console_events = await resolver.execute(
        page=page,
        target_url="https://example.com/path",
        timeout_ms=1000,
        trusted_session=False,
    )
    assert console_events[0]["text"] == "hello"

    turnstile_assessment = BypassAssessment(outcome="turnstile", final_url="https://example.com/path")
    challenge_assessment = BypassAssessment(outcome="challenge", final_url="https://example.com/path")
    actuator = FakeActuator()
    resolver = ResolveProtection(
        policy=BypassPolicy(),
        page_probe=FakeProbe(
            page_assessments=[turnstile_assessment, challenge_assessment, challenge_assessment, challenge_assessment, challenge_assessment, challenge_assessment],
            managed=[False, True, False, False, False, False],
        ),
        challenge_actuator=actuator,
        artifact_store=FakeArtifactStore(),
        telemetry=FakeTelemetry(),
    )
    with pytest.raises(BypassFailure):
        await resolver.execute(
            page=FakePage(),
            target_url="https://example.com/path",
            timeout_ms=1000,
            trusted_session=False,
        )
    assert any(call[0] == "turnstile" for call in actuator.calls)
    assert any(call[0] == "managed" for call in actuator.calls)
    assert any(call[0] == "advance" for call in actuator.calls)

    resolver = ResolveProtection(
        policy=BypassPolicy(),
        page_probe=FakeProbe(
            page_assessments=[challenge_assessment, clear_assessment],
            managed=[False, False],
        ),
        challenge_actuator=FakeActuator(),
        artifact_store=FakeArtifactStore(),
        telemetry=FakeTelemetry(),
    )
    assert await resolver.execute(
        page=FakePage(),
        target_url="https://example.com/path",
        timeout_ms=1000,
        trusted_session=False,
    ) == [{"type": "log", "text": "hello"}]

    fetcher = ExecuteHttpFetch(
        http_runtime=FakeRuntime(FetchResponse(status=200, headers={}, body="ok", url="https://example.com")),
        page_probe=FakeProbe(response_assessment=BypassAssessment(outcome="clear", final_url="https://example.com")),
        artifact_store=FakeArtifactStore(),
        policy=BypassPolicy(),
    )
    response, outcome, artifact_dir = await fetcher.execute(
        page=FakePage(),
        request=request,
        timeout_ms=1000,
        console_events=[],
    )
    assert response.status == 200
    assert outcome.kind == "success"
    assert artifact_dir is None

    blocked_fetcher = ExecuteHttpFetch(
        http_runtime=FakeRuntime(FetchResponse(status=403, headers={}, body="blocked", url="https://example.com")),
        page_probe=FakeProbe(response_assessment=BypassAssessment(outcome="blocked", final_url="https://example.com")),
        artifact_store=FakeArtifactStore(),
        policy=BypassPolicy(),
    )
    with pytest.raises(BypassFailure):
        await blocked_fetcher.execute(
            page=FakePage(),
            request=request,
            timeout_ms=1000,
            console_events=[],
        )

    store = FakeSessionStore()
    persister = PersistSessionState(store)
    persister.record_success(
        domain_key="dk",
        domain="example.com",
        user_agent="ua",
        proxy=None,
        profile_dir="profile",
        final_url="https://example.com",
        cookie_names=["session"],
        artifact_dir=None,
    )
    persister.record_failure(
        domain_key="dk",
        domain="example.com",
        user_agent="ua",
        proxy=None,
        profile_dir="profile",
        final_url=None,
        artifact_dir="/tmp/a",
    )
    assert len(store.success_calls) == 1
    assert len(store.failure_calls) == 1

    report = BuildExecutionReport()
    result = ExecutionResult(response=FetchResponse(status=200, headers={}, body="ok", url="https://example.com"))
    policy = BypassPolicy()
    complete = report.complete(
        result=result,
        execution_meta=_execution_meta(),
        outcome=policy.evaluate_fetch_result(ProtectionSnapshot(state=ChallengeState.CLEAR, final_url="https://example.com", status_code=200)),
        fallback_url="https://fallback",
    )
    assert complete.meta is not None
    assert complete.meta.final is not None
    assert await resolver._apply_decision(
        page=FakePage(),
        decision=BypassDecision(BypassAction.FAIL_BLOCKED, "blocked"),
        target_url="https://example.com",
        timeout_ms=1,
        attempt_index=1,
    ) is False


def test_playwright_wrapper_exports_are_public():
    assert playwright_exports.BrowserManager is not None
    assert playwright_exports.BypassManager is not None
    assert playwright_exports.DefaultBrowserManagerFactory is not None
    assert chrome_major_version("Mozilla/5.0 Safari/537.36") == "124"


def test_sarif_internal_mappings_cover_remaining_branches():
    assert _rule_id_for_exit_code(0) == "CW000"
    assert _rule_id_for_exit_code(10) == "CW001"
    assert _rule_id_for_exit_code(11) == "CW002"
    assert _rule_id_for_exit_code(12) == "CW003"
    assert _rule_id_for_exit_code(999) == "CW004"
    assert _level_for_error(BypassFailure("blocked", assessment=BypassAssessment(outcome="blocked", final_url="x"))) == "warning"
    assert _level_for_error(FileNotFoundError("missing")) == "error"
    assert _level_for_error(ValueError("bad")) == "error"
    assert _level_for_error(RuntimeError("boom")) == "error"


@pytest.mark.asyncio
async def test_protection_runtime_components_cover_remaining_branches():
    class ConsolePage:
        def __init__(self):
            self.handler = None

        def on(self, event, handler):
            assert event == "console"
            self.handler = handler

    page = ConsolePage()
    events = ConsoleTelemetry().attach_console_capture(page)
    page.handler(type("Msg", (), {"type": "warning", "text": "hello"})())
    assert events == [{"type": "warning", "text": "hello"}]

    probe = PlaywrightPageProbe()

    class ContentErrorPage:
        url = "https://example.com"

        async def content(self):
            raise RuntimeError("boom")

    assert await probe.is_managed_challenge(type("ManagedPage", (), {"url": "https://example.com/__cf_chl_x"})()) is True
    assert await probe.is_managed_challenge(ContentErrorPage()) is False

    actuator = PlaywrightChallengeActuator()

    class WaitPage:
        def __init__(self, url, html, *, wait_error=False, goto_error=False):
            self.url = url
            self.html = html
            self.wait_error = wait_error
            self.goto_error = goto_error
            self.goto_calls = []

        async def content(self):
            return self.html

        async def wait_for_load_state(self, *_args, **_kwargs):
            if self.wait_error:
                raise RuntimeError("wait failure")

        async def goto(self, url, **_kwargs):
            self.goto_calls.append(url)
            if self.goto_error:
                raise RuntimeError("goto failure")
            self.url = url

    await actuator.wait_for_managed_challenge(
        WaitPage("https://example.com/clear", "<html></html>"),
        timeout_ms=10,
    )
    await actuator.wait_for_managed_challenge(
        WaitPage("https://example.com/__cf_chl_x", "<script>window._cf_chl_opt = 1</script>", wait_error=True),
        timeout_ms=10,
    )

    same_page = WaitPage("https://example.com/target", "<html></html>")
    await actuator.revisit_target(same_page, target_url="https://example.com/target", timeout_ms=10)
    assert same_page.goto_calls == []
    failing_page = WaitPage("https://example.com/other", "<html></html>", goto_error=True)
    await actuator.revisit_target(failing_page, target_url="https://example.com/target", timeout_ms=10)

    class BoxLocator:
        def __init__(self, boxes):
            self.boxes = boxes

        async def count(self):
            return len(self.boxes)

        def nth(self, index):
            box = self.boxes[index]
            class Nth:
                async def bounding_box(self_inner):
                    return box

            return Nth()

    class Mouse:
        def __init__(self):
            self.clicks = []

        async def click(self, x, y):
            self.clicks.append((x, y))

    class IframePage:
        def __init__(self, boxes=None, locator_error=False):
            self.mouse = Mouse()
            self.boxes = boxes or []
            self.locator_error = locator_error

        def locator(self, _selector):
            if self.locator_error:
                raise RuntimeError("locator failure")
            return BoxLocator(self.boxes)

    assert await actuator._click_turnstile_iframe_center(IframePage(locator_error=True)) is False
    success_page = IframePage(boxes=[{"x": 1, "y": 2, "width": 10, "height": 20}])
    assert await actuator._click_turnstile_iframe_center(success_page) is True
    assert success_page.mouse.clicks

    class InputLocator:
        def __init__(self, *, count=1, value="token", error=False):
            self._count = count
            self._value = value
            self._error = error

        async def count(self):
            if self._error:
                raise RuntimeError("count failure")
            return self._count

        @property
        def first(self):
            class First:
                async def input_value(self_inner, timeout=0):
                    return self._value

            return First()

    class BodyLocator:
        def __init__(self, *, text="", error=False):
            self.text = text
            self.error = error

        async def count(self):
            return 1

        async def inner_text(self):
            if self.error:
                raise RuntimeError("inner_text failure")
            return self.text

    class TurnstilePage:
        def __init__(self, *, wait_error=False, ready=False, has_selectors=True):
            self.wait_error = wait_error
            self.ready = ready
            self.has_selectors = has_selectors

        def locator(self, selector):
            if selector == "input[name='cf-turnstile-response']":
                return InputLocator(count=1 if self.ready else 0, value="token" if self.ready else "")
            if selector == "body":
                return BodyLocator(text="verification successful")
            return BodyLocator(text="", error=not self.has_selectors)

        async def title(self):
            return "Verification successful"

        async def wait_for_load_state(self, *_args, **_kwargs):
            if self.wait_error:
                raise RuntimeError("wait failure")

    await actuator._wait_for_turnstile_progress(TurnstilePage(ready=True), timeout_ms=10, expect_interaction=False)
    await actuator._wait_for_turnstile_progress(TurnstilePage(wait_error=True, ready=False, has_selectors=False), timeout_ms=10, expect_interaction=True)
    assert await actuator._turnstile_response_ready(type("ReadyPage", (), {"locator": lambda self, _sel: InputLocator(error=True)})()) is False

    class PageAny:
        async def title(self):
            return "X"

        def locator(self, _selector):
            return BodyLocator(text="hello")

    class SelectorPage:
        def locator(self, _selector):
            class FailingLocator:
                async def count(self_inner):
                    raise RuntimeError("boom")

            return FailingLocator()

    assert await actuator._page_contains_any(PageAny(), ["hello"]) is True
    assert await actuator._selector_exists(SelectorPage(), "div") is False
