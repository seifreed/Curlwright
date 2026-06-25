from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


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
