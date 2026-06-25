from __future__ import annotations

import logging
from pathlib import Path

import pytest

from curlwright.application.use_cases import ExecuteHttpFetch, ResolveProtection
from curlwright.domain import BypassAssessment, CurlRequest, FetchResponse
from curlwright.domain.policy import BypassAction, ExecutionOutcome
from curlwright.errors import BypassFailure

USE_CASES_LOGGER = "curlwright.application.use_cases"


def _decision(action):
    return type("Decision", (), {"action": action, "revisit_target": False})()


@pytest.mark.asyncio
async def test_resolve_protection_logs_clear_state(caplog):
    class ClearPolicy:
        def build_request_policy(self, target_url, trusted_session):
            return type("Policy", (), {"navigation_targets": [target_url]})()

        def decide_page_action(self, snapshot, *, managed_challenge):
            return _decision(BypassAction.RETURN_CLEAR)

        def decide_post_action(self, snapshot, *, managed_challenge):
            return _decision(BypassAction.FAIL_BLOCKED)

    class Probe:
        async def assess_page(self, page, response):
            return BypassAssessment(outcome="clear", final_url="https://example.com/data")

        async def is_managed_challenge(self, page):
            return False

    class Actuator:
        async def stabilize_page(self, page, *, attempt_index, timeout_ms):
            return None

    class Telemetry:
        def attach_console_capture(self, page):
            return []

    class Page:
        url = "https://example.com/data"

        async def goto(self, url, **kwargs):
            return None

    resolver = ResolveProtection(
        policy=ClearPolicy(),
        page_probe=Probe(),
        challenge_actuator=Actuator(),
        artifact_store=None,
        telemetry=Telemetry(),
    )

    with caplog.at_level(logging.INFO, logger=USE_CASES_LOGGER):
        events = await resolver.execute(
            page=Page(),
            target_url="https://example.com/data",
            timeout_ms=100,
            trusted_session=False,
        )

    assert events == []
    assert any(
        "Bypass reached a clear state for https://example.com/data" in r.getMessage()
        for r in caplog.records
        if r.levelno == logging.INFO
    )


@pytest.mark.asyncio
async def test_execute_http_fetch_logs_blocked_final_response(tmp_path, caplog):
    class Http:
        async def perform_fetch_request(self, page, request, timeout_ms):
            return FetchResponse(status=403, headers={}, body="blocked", url=request.url)

    class Probe:
        def assess_response_payload(self, payload):
            return BypassAssessment(outcome="blocked", final_url=str(payload["url"]))

    class Policy:
        def evaluate_fetch_result(self, snapshot):
            return ExecutionOutcome(kind="blocked", status=403, final_url=None)

    class Artifact:
        artifact_root = tmp_path

        async def collect(self, **kwargs):
            return Path(tmp_path / "blocked")

    fetch = ExecuteHttpFetch(
        http_runtime=Http(),
        page_probe=Probe(),
        artifact_store=Artifact(),
        policy=Policy(),
    )

    with caplog.at_level(logging.WARNING, logger=USE_CASES_LOGGER):
        with pytest.raises(BypassFailure):
            await fetch.execute(
                page=object(),
                request=CurlRequest(url="https://example.com/data"),
                timeout_ms=100,
                console_events=[],
            )

    assert any(
        "still looks blocked (HTTP 403, outcome=blocked)" in r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING
    )
