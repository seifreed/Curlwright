"""Unit tests for the nodriver engine path in the request executor.

The native nodriver flow (navigate -> auto-clear -> in-page fetch) is driven
through a fake browser manager so we exercise classification, success/failure
bookkeeping and artifact handling without launching a real browser.
"""

import pytest

from curlwright.domain import BypassFailure, CurlRequest, FetchResponse
from curlwright.executor import RequestExecutor


class FakeNodriverManager:
    def __init__(self, response: FetchResponse, *, cookie_names=None, html=""):
        self._response = response
        self._cookie_names = cookie_names or []
        self._html = html
        self.context = None

    async def initialize(self):
        return None

    async def fetch(self, request, *, timeout_ms):
        return self._response, self._cookie_names, self._html

    async def close(self):
        return None


def _executor(tmp_path):
    return RequestExecutor(
        timeout=5,
        persist_cookies=False,
        engine="nodriver",
        profile_dir=str(tmp_path / "profile"),
        artifact_dir=str(tmp_path / "artifacts"),
        bypass_state_file=str(tmp_path / "state.json"),
    )


@pytest.mark.asyncio
async def test_nodriver_success_returns_result(tmp_path):
    executor = _executor(tmp_path)
    executor.browser_manager = FakeNodriverManager(
        FetchResponse(
            status=200, headers={}, body="<html>real content</html>", url="https://example.com/"
        ),
        cookie_names=["cf_clearance"],
    )
    request = CurlRequest(url="https://example.com/")

    result = await executor._execute_request(request)

    assert result.outcome.kind == "success"
    assert result.response.status == 200
    assert "real content" in result.response.body


@pytest.mark.asyncio
async def test_nodriver_blocked_raises_bypass_failure_and_writes_artifact(tmp_path):
    executor = _executor(tmp_path)
    executor.browser_manager = FakeNodriverManager(
        FetchResponse(
            status=403,
            headers={},
            body="<title>Just a moment...</title>",
            url="https://example.com/",
        ),
        html="<title>Just a moment...</title>",
    )
    request = CurlRequest(url="https://example.com/")

    with pytest.raises(BypassFailure) as excinfo:
        await executor._execute_request(request)

    assert excinfo.value.assessment.outcome != "clear"
    assert excinfo.value.artifact_dir is not None
