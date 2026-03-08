from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.async_api import async_playwright

from src.core.bypass_manager import BypassFailure, BypassManager


class _BypassFixtureServer(ThreadingHTTPServer):
    def __init__(self, server_address, root_mode: str = "clear"):
        super().__init__(server_address, _BypassFixtureHandler)
        self.counts: dict[str, int] = {}
        self.root_mode = root_mode


class _BypassFixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = self.path.split("?", 1)[0]
        self.server.counts[route] = self.server.counts.get(route, 0) + 1
        count = self.server.counts[route]

        if route == "/":
            if self.server.root_mode == "challenge":
                self._send_html(
                    "<html><head><title>Just a moment</title></head>"
                    "<body><div id='challenge-running'>challenge</div></body></html>"
                )
            else:
                self._send_html("<html><body>clear content</body></html>")
            return

        if route == "/challenge-then-clear":
            if count <= 2:
                self._send_html(
                    "<html><head><title>Just a moment</title></head>"
                    "<body><div id='challenge-running'>challenge</div></body></html>"
                )
            else:
                self._send_html("<html><body>clear content</body></html>")
            return

        if route == "/always-challenge":
            self._send_html(
                "<html><head><title>Just a moment</title></head>"
                "<body><div id='challenge-running'>challenge</div></body></html>"
            )
            return

        if route == "/blocked-empty":
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if route == "/clear":
            self._send_html("<html><body>clear page</body></html>")
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return

    def _send_html(self, body: str):
        encoded = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _start_bypass_server(*, root_mode: str = "clear"):
    server = _BypassFixtureServer(("127.0.0.1", 0), root_mode=root_mode)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, thread


@pytest.mark.asyncio
async def test_assess_page_classifies_blocked_empty_response():
    manager = BypassManager()
    server, thread = _start_bypass_server(root_mode="clear")

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            response = await page.goto(f"http://127.0.0.1:{server.server_port}/blocked-empty")

            assessment = await manager.assess_page(page, response)

            assert assessment.outcome == "blocked"
            assert "status:403" in assessment.indicators
            assert "empty-body-on-block-status" in assessment.indicators
            await browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_attempt_turnstile_resolution_clicks_interactive_element():
    manager = BypassManager()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(
            """
            <html>
              <body>
                <div class="cf-turnstile">widget</div>
                <button id="solve-turnstile" onclick="
                  document.querySelector('.cf-turnstile').remove();
                  this.textContent='solved';
                ">solve</button>
              </body>
            </html>
            """
        )

        await manager._attempt_turnstile_resolution(page, timeout_ms=1500)

        assert await page.locator("div.cf-turnstile").count() == 0
        assert await page.locator("#solve-turnstile").inner_text() == "solved"
        await browser.close()


@pytest.mark.asyncio
async def test_perform_bypass_reaches_clear_page_after_reload():
    manager = BypassManager()
    server, thread = _start_bypass_server(root_mode="challenge")

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()

            assessment = await manager.perform_bypass(
                page=page,
                target_url=f"http://127.0.0.1:{server.server_port}/challenge-then-clear",
                timeout_ms=4_000,
                trusted_session=False,
                console_events=[],
            )

            assert assessment.outcome == "clear"
            assert "clear content" in assessment.body_excerpt
            await browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_perform_bypass_failure_collects_artifacts(tmp_path):
    manager = BypassManager(artifact_root=str(tmp_path))
    server, thread = _start_bypass_server(root_mode="challenge")

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()

            with pytest.raises(BypassFailure) as exc_info:
                await manager.perform_bypass(
                    page=page,
                    target_url=f"http://127.0.0.1:{server.server_port}/always-challenge",
                    timeout_ms=1_500,
                    trusted_session=True,
                    console_events=[],
                )

            failure = exc_info.value
            assert failure.assessment.outcome == "challenge"
            assert failure.artifact_dir is not None
            artifact_dir = tmp_path / failure.artifact_dir.split("/")[-1]
            assert artifact_dir.exists()
            assert json.loads((artifact_dir / "assessment.json").read_text())["outcome"] == "challenge"
            await browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)
