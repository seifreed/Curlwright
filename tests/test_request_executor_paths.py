from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.core.bypass_manager import BypassFailure
from src.core.request_executor import RequestExecutor
from src.parsers.curl_parser import CurlRequest


class _ExecutorFixtureServer(ThreadingHTTPServer):
    pass


class _ExecutorFixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = self.path.split("?", 1)[0]
        accept = self.headers.get("Accept", "")

        if route == "/json":
            self._send_json({"ok": True, "method": "GET"})
            return

        if route == "/head":
            self._send_json({"ok": True, "method": "HEAD"})
            return

        if route == "/conditional-block":
            if "text/html" in accept:
                self._send_html("<html><body>navigable page</body></html>")
            else:
                self._send_text("Sorry, you have been blocked", status=403)
            return

        self.send_response(404)
        self.end_headers()

    def do_HEAD(self):
        route = self.path.split("?", 1)[0]
        if route == "/head":
            payload = json.dumps({"ok": True, "method": "HEAD"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return

    def _send_html(self, body: str, status: int = 200):
        encoded = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_text(self, body: str, status: int = 200):
        encoded = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, payload: dict[str, object]):
        encoded = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _start_executor_server():
    server = _ExecutorFixtureServer(("127.0.0.1", 0), _ExecutorFixtureHandler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, thread


def test_domain_session_key_and_retry_user_agent_rotation():
    executor = RequestExecutor()
    request = CurlRequest(url="https://example.com/data", proxy="http://proxy:8080")

    first = executor._get_retry_user_agent(0)
    second = executor._get_retry_user_agent(1)
    executor._effective_user_agent = first

    assert first != second
    assert executor._get_domain_session_key(request) == f"example.com|http://proxy:8080|{first}"


def test_pinned_user_agent_disables_rotation():
    executor = RequestExecutor(user_agent="Custom/1.0")

    assert executor._get_retry_user_agent(0) == "Custom/1.0"
    assert executor._get_retry_user_agent(2) == "Custom/1.0"


def test_has_trusted_session_requires_state_and_cookie_presence(tmp_path):
    executor = RequestExecutor(
        cookie_file=str(tmp_path / "cookies.pkl"),
        bypass_state_file=str(tmp_path / "state.json"),
    )
    request = CurlRequest(url="https://example.com/data")

    assert executor._has_trusted_session(request) is False

    domain_key = executor._get_domain_session_key(request)
    executor.domain_state_store.mark_success(
        domain_key=domain_key,
        domain="example.com",
        user_agent=executor._effective_user_agent,
        proxy=None,
        final_url=request.url,
        cookie_names=["session"],
        artifact_dir=None,
    )
    assert executor._has_trusted_session(request) is False

    assert executor.cookie_manager is not None
    executor.cookie_manager.cookies = [{"name": "session", "domain": ".example.com", "value": "abc"}]
    assert executor._has_trusted_session(request) is True


def test_has_trusted_session_returns_false_when_cookie_persistence_is_disabled(tmp_path):
    executor = RequestExecutor(
        persist_cookies=False,
        bypass_state_file=str(tmp_path / "state.json"),
    )
    request = CurlRequest(url="https://example.com/data")
    domain_key = executor._get_domain_session_key(request)

    executor.domain_state_store.mark_success(
        domain_key=domain_key,
        domain="example.com",
        user_agent=executor._effective_user_agent,
        proxy=None,
        final_url=request.url,
        cookie_names=["session"],
        artifact_dir=None,
    )

    assert executor._has_trusted_session(request) is False


@pytest.mark.asyncio
async def test_reset_runtime_state_clears_initialized_browser():
    executor = RequestExecutor(headless=True, no_gui=True)
    request = CurlRequest(url="https://example.com")

    await executor._ensure_initialized(request, user_agent=executor._get_retry_user_agent(0))
    assert executor.initialized is True
    assert executor.browser_manager is not None

    await executor._reset_runtime_state()

    assert executor.browser_manager is None
    assert executor.initialized is False
    assert executor._browser_signature is None


@pytest.mark.asyncio
async def test_ensure_initialized_reuses_matching_signature_and_rebuilds_on_change():
    executor = RequestExecutor(headless=True, no_gui=True)
    request = CurlRequest(url="https://example.com")
    auth_request = CurlRequest(url="https://example.com", auth=("alice", "secret"))

    try:
        await executor._ensure_initialized(request, user_agent=executor._get_retry_user_agent(0))
        first_browser_manager = executor.browser_manager
        assert first_browser_manager is not None

        await executor._ensure_initialized(request, user_agent=executor._get_retry_user_agent(0))
        assert executor.browser_manager is first_browser_manager

        await executor._ensure_initialized(auth_request, user_agent=executor._get_retry_user_agent(0))
        assert executor.browser_manager is not first_browser_manager
        assert first_browser_manager.browser is None
    finally:
        await executor.close()


@pytest.mark.asyncio
async def test_perform_fetch_request_supports_head_without_body():
    server, thread = _start_executor_server()
    executor = RequestExecutor(headless=True, no_gui=True)
    request = CurlRequest(url=f"http://127.0.0.1:{server.server_port}/head", method="HEAD")

    try:
        await executor._ensure_initialized(request, user_agent=executor._get_retry_user_agent(0))
        assert executor.browser_manager is not None
        page = await executor.browser_manager.create_page()
        payload = await executor._perform_fetch_request(page, request, timeout_ms=2_000)

        assert payload["status"] == 200
        assert payload["body"] == ""
        await page.close()
    finally:
        await executor.close()
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_execute_request_marks_success_for_clear_response(tmp_path):
    server, thread = _start_executor_server()
    executor = RequestExecutor(
        headless=True,
        no_gui=True,
        cookie_file=str(tmp_path / "cookies.pkl"),
        bypass_state_file=str(tmp_path / "state.json"),
    )
    request = CurlRequest(url=f"http://127.0.0.1:{server.server_port}/json")

    try:
        await executor._ensure_initialized(request, user_agent=executor._get_retry_user_agent(0))
        payload = await executor._execute_request(request)

        domain_key = executor._get_domain_session_key(request)
        state = executor.domain_state_store.get(domain_key)

        assert payload["status"] == 200
        assert state is not None
        assert state.last_status == "verified"
        assert state.success_count == 1
    finally:
        await executor.close()
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_execute_request_marks_failure_for_blocked_final_response(tmp_path):
    server, thread = _start_executor_server()
    executor = RequestExecutor(
        headless=True,
        no_gui=True,
        bypass_state_file=str(tmp_path / "state.json"),
        artifact_dir=str(tmp_path / "artifacts"),
    )
    request = CurlRequest(
        url=f"http://127.0.0.1:{server.server_port}/conditional-block",
        headers={"Accept": "application/json"},
    )

    try:
        await executor._ensure_initialized(request, user_agent=executor._get_retry_user_agent(0))

        with pytest.raises(BypassFailure) as exc_info:
            await executor._execute_request(request)

        failure = exc_info.value
        domain_key = executor._get_domain_session_key(request)
        state = executor.domain_state_store.get(domain_key)

        assert failure.assessment.outcome == "blocked"
        assert state is not None
        assert state.last_status == "failed"
        assert state.failure_count == 1
        assert state.last_artifact_dir is not None
    finally:
        await executor.close()
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_execute_retries_and_raises_after_repeated_bypass_failures(tmp_path):
    server, thread = _start_executor_server()
    executor = RequestExecutor(
        headless=True,
        no_gui=True,
        bypass_state_file=str(tmp_path / "state.json"),
        artifact_dir=str(tmp_path / "artifacts"),
    )
    command = (
        f"curl -H 'Accept: application/json' "
        f"http://127.0.0.1:{server.server_port}/conditional-block"
    )

    try:
        with pytest.raises(BypassFailure):
            await executor.execute(command, max_retries=2, delay=0)

        assert executor.initialized is False
        assert executor.browser_manager is None
    finally:
        await executor.close()
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_execute_retries_and_raises_for_unreachable_origin(tmp_path):
    executor = RequestExecutor(
        headless=True,
        no_gui=True,
        bypass_state_file=str(tmp_path / "state.json"),
    )

    with pytest.raises(Exception):
        await executor.execute("curl http://127.0.0.1:1/unreachable", max_retries=2, delay=0)

    assert executor.initialized is False
    assert executor.browser_manager is None


def test_execute_parse_errors_are_re_raised():
    executor = RequestExecutor()

    with pytest.raises(ValueError):
        import asyncio

        asyncio.run(executor.execute("curl 'unterminated"))


def test_fetch_option_helpers_cover_existing_content_type_and_base_url():
    executor = RequestExecutor()
    request = CurlRequest(
        url="https://example.com/api/path",
        method="POST",
        data='{"ok":true}',
        headers={"Content-Type": "application/custom"},
    )

    options = executor._build_fetch_options(request)

    assert options["headers"]["Content-Type"] == "application/custom"
    assert executor._extract_base_url(request.url) == "https://example.com"
