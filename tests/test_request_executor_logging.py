from __future__ import annotations

import logging

import pytest

from curlwright.domain import BypassAssessment, ExecutionResult, FetchResponse
from curlwright.domain.policy import ExecutionOutcome
from curlwright.errors import BypassFailure
from curlwright.executor import RequestExecutor

LOGGER_NAME = "curlwright.application.request_executor"


def _make_executor(tmp_path):
    return RequestExecutor(
        headless=True,
        no_gui=True,
        cookie_file=str(tmp_path / "cookies.json"),
        bypass_state_file=str(tmp_path / "state.json"),
        artifact_dir=str(tmp_path / "artifacts"),
        profile_dir=str(tmp_path / "profile"),
    )


def _stub_browser_interactions(executor, on_request):
    async def _noop_init(request, *, user_agent):
        return None

    executor._ensure_initialized = _noop_init
    executor._execute_request = on_request


@pytest.mark.asyncio
async def test_execute_logs_start_and_success(tmp_path, caplog):
    executor = _make_executor(tmp_path)

    async def _succeed(request):
        return ExecutionResult(
            response=FetchResponse(status=200, headers={}, body="ok", url=request.url),
            outcome=ExecutionOutcome(kind="success", status=200, final_url=request.url),
        )

    _stub_browser_interactions(executor, _succeed)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        payload = await executor.execute("curl https://example.com/data", max_retries=2, delay=0)

    assert payload["status"] == 200
    messages = [record.getMessage() for record in caplog.records]
    assert any("Executing GET request to https://example.com/data" in m for m in messages)
    assert any("succeeded on attempt 1/2 (HTTP 200)" in m for m in messages)


@pytest.mark.asyncio
async def test_execute_logs_retry_warning_then_error_on_repeated_bypass_failure(tmp_path, caplog):
    executor = _make_executor(tmp_path)
    assessment = BypassAssessment(outcome="blocked", final_url="https://example.com/data")

    async def _always_blocked(request):
        raise BypassFailure("still blocked", assessment=assessment, artifact_dir=None)

    _stub_browser_interactions(executor, _always_blocked)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        with pytest.raises(BypassFailure):
            await executor.execute("curl https://example.com/data", max_retries=2, delay=0)

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any("Attempt 1/2" in m and "bypass failure" in m and "retrying" in m for m in warnings)
    assert any("Bypass failed for https://example.com/data after 2 attempt(s)" in m for m in errors)


@pytest.mark.asyncio
async def test_execute_logs_error_on_generic_failure(tmp_path, caplog):
    executor = _make_executor(tmp_path)

    async def _explode(request):
        raise RuntimeError("origin unreachable")

    _stub_browser_interactions(executor, _explode)

    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        with pytest.raises(RuntimeError):
            await executor.execute("curl https://example.com/data", max_retries=2, delay=0)

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any("Attempt 1/2" in m and "errored" in m for m in warnings)
    assert any("failed after 2 attempt(s): origin unreachable" in m for m in errors)
