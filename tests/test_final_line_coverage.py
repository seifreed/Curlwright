from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import curlwright
from curlwright.domain import CurlRequest, DomainBypassState
from curlwright.executor import RequestExecutor
from curlwright.infrastructure.parsers import CurlParser
from curlwright.infrastructure.protection_runtime import PlaywrightChallengeActuator


class _CookieCaptureServer(ThreadingHTTPServer):
    last_cookie_header: str = ""


class _CookieCaptureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.last_cookie_header = self.headers.get("Cookie", "")
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def _start_cookie_server():
    server = _CookieCaptureServer(("127.0.0.1", 0), _CookieCaptureHandler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, thread


def test_curlwright_invalid_public_attribute_raises_attribute_error():
    with pytest.raises(AttributeError, match="has no attribute"):
        getattr(curlwright, "DoesNotExist")


def test_domain_bypass_state_without_verification_is_not_trusted():
    record = DomainBypassState(
        domain_key="key",
        domain="example.com",
        user_agent="ua",
        proxy=None,
    )

    assert record.is_trusted(60) is False


def test_parser_helpers_cover_remaining_branches():
    parser = CurlParser()
    parsed = parser.parse("curl -G --data 'lonely' https://example.com")
    assert parsed.url == "https://example.com?=lonely"

    assert parser._parse_form_pairs("lonely") == [("", "lonely")]
    assert parser._append_query_pairs("https://example.com", []) == "https://example.com"


@pytest.mark.asyncio
async def test_request_executor_covers_zero_retry_runtime_guard_and_cookie_branch(tmp_path):
    executor = RequestExecutor(
        headless=True,
        no_gui=True,
        cookie_file=str(tmp_path / "cookies.pkl"),
    )

    with pytest.raises(Exception, match="Failed to execute request after all retries"):
        await executor.execute("curl https://example.com", max_retries=0, delay=0)

    with pytest.raises(RuntimeError, match="Browser manager is not initialized"):
        await executor._execute_request(CurlRequest(url="https://example.com"))

    server, thread = _start_cookie_server()
    try:
        request = CurlRequest(
            url=f"http://127.0.0.1:{server.server_port}/",
            cookies={"session": "abc", "theme": "dark"},
        )
        await executor._ensure_initialized(request, user_agent=executor._get_retry_user_agent(0))
        result = await executor._execute_request(request)
        assert result.response.status == 200
        assert "session=abc" in server.last_cookie_header
        assert "theme=dark" in server.last_cookie_header
    finally:
        await executor.close()
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_challenge_actuator_turnstile_resolution_handles_frame_click_failure():
    class BrokenLocator:
        async def count(self):
            return 1

        @property
        def first(self):
            return self

        async def click(self, **_kwargs):
            raise RuntimeError("click failure")

    class BrokenFrame:
        def locator(self, _selector):
            return BrokenLocator()

    class BrokenPage:
        frames = [BrokenFrame()]

        async def wait_for_load_state(self, *_args, **_kwargs):
            return None

    await PlaywrightChallengeActuator().resolve_turnstile(BrokenPage(), timeout_ms=100)
