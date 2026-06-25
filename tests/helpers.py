from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from curlwright.domain import (
    AttemptRecord,
    ExecutionMetadata,
    RequestMetadata,
    RuntimeMetadata,
    StateMetadata,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_cli(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run the CurlWright CLI as a subprocess from the project root."""
    return subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class BaseFixtureHandler(BaseHTTPRequestHandler):
    """Shared response helpers for fixture HTTP handlers."""

    def log_message(self, format, *args):
        return

    def _send_html(self, body: str, status: int = 200):
        self._send(body.encode(), "text/html; charset=utf-8", status)

    def _send_text(self, body: str, status: int = 200):
        self._send(body.encode(), "text/plain; charset=utf-8", status)

    def _send_json(self, payload: dict[str, object], status: int = 200):
        self._send(json.dumps(payload).encode(), "application/json", status)

    def _send(self, encoded: bytes, content_type: str, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class FixtureHttpServer(ThreadingHTTPServer):
    def __init__(self, server_address):
        super().__init__(server_address, FixtureHttpHandler)


class FixtureHttpHandler(BaseFixtureHandler):
    def do_GET(self):
        route = self.path.split("?", 1)[0]
        if route == "/":
            self._send_html("<html><body>fixture root</body></html>")
            return
        if route == "/json":
            self._send_json({"ok": True, "path": route})
            return
        if route == "/text":
            self._send_text("fixture text response")
            return
        self.send_response(404)
        self.end_headers()


def start_fixture_server():
    server = FixtureHttpServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, thread


def assert_payload_contract(payload: dict, *, kind: str, ok: bool, exit_code: int) -> None:
    assert payload["schema_version"] == 1
    assert payload["kind"] == kind
    assert payload["ok"] is ok
    assert payload["exit_code"] == exit_code


def make_execution_meta(
    *,
    cookie_file: str | None = "cookies.pkl",
    attempts: list[AttemptRecord] | None = None,
) -> ExecutionMetadata:
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
            cookie_file=cookie_file,
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
        attempts=attempts or [],
    )
