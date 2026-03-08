from __future__ import annotations

import importlib.util
import sys
import threading
from argparse import Namespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

import curlwright.main as package_main
from src.core.browser_manager import BrowserManager
from src.core.bypass_manager import BypassManager


def _load_module_without_project_root(module_path: Path, module_name: str):
    project_root = str(module_path.resolve().parent.parent)
    original_sys_path = list(sys.path)
    try:
        sys.path = [entry for entry in sys.path if entry != project_root]
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, project_root
    finally:
        sys.path = original_sys_path


def test_package_main_inserts_project_root_on_fresh_load():
    module, project_root = _load_module_without_project_root(
        Path(__file__).resolve().parents[1] / "curlwright" / "main.py",
        "curlwright_main_fresh",
    )

    assert project_root in sys.path or str(module.PROJECT_ROOT) == project_root


def test_package_cli_inserts_project_root_on_fresh_load():
    module, project_root = _load_module_without_project_root(
        Path(__file__).resolve().parents[1] / "curlwright" / "cli.py",
        "curlwright_cli_fresh",
    )

    assert project_root in sys.path or str(module.PROJECT_ROOT) == project_root


@pytest.mark.asyncio
async def test_package_main_handles_missing_file_in_process(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["curlwright", "-f", "definitely-missing-request.txt", "--headless"],
    )

    with pytest.raises(SystemExit) as exc_info:
        await package_main.main()

    assert exc_info.value.code == 1


class _TurnstileFixtureServer(ThreadingHTTPServer):
    pass


class _TurnstileFixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?", 1)[0] == "/turnstile-clear":
            self._send_html(
                """
                <html>
                  <head><title>Verify you are human</title></head>
                  <body>
                    <div class="cf-turnstile">widget</div>
                    <button id="solve-turnstile" onclick="
                      document.querySelector('.cf-turnstile').remove();
                      this.remove();
                    ">solve</button>
                  </body>
                </html>
                """
            )
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


def _start_turnstile_server():
    server = _TurnstileFixtureServer(("127.0.0.1", 0), _TurnstileFixtureHandler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, thread


@pytest.mark.asyncio
async def test_browser_manager_create_page_initializes_lazily():
    manager = BrowserManager(headless=True, no_gui=True)

    try:
        page = await manager.create_page()
        assert manager.context is not None
        assert page is manager.page
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_browser_manager_initializes_with_proxy_branch():
    manager = BrowserManager(
        headless=True,
        no_gui=True,
        proxy="http://127.0.0.1:8888",
    )

    try:
        await manager.initialize()
        assert manager.browser is not None
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_browser_manager_initialize_failure_path(monkeypatch):
    class FailingStarter:
        async def start(self):
            raise RuntimeError("start failed")

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: FailingStarter())

    manager = BrowserManager(headless=True, no_gui=True)
    with pytest.raises(RuntimeError, match="start failed"):
        await manager.initialize()


@pytest.mark.asyncio
async def test_browser_manager_handle_turnstile_success_branch():
    class Locator:
        def __init__(self):
            self.calls = 0

        async def count(self):
            self.calls += 1
            return 1 if self.calls == 1 else 0

    class Page:
        def __init__(self):
            self._locator = Locator()

        def locator(self, _selector):
            return self._locator

        async def wait_for_load_state(self, *_args, **_kwargs):
            return None

    manager = BrowserManager()
    assert await manager.handle_turnstile(Page(), timeout=1) is True


@pytest.mark.asyncio
async def test_bypass_manager_assess_page_sets_cloudflare_indicators():
    manager = BypassManager()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(
            """
            <html>
              <head>
                <title>Attention Required! | Cloudflare</title>
              </head>
              <body>
                Sorry, you have been blocked
                <img src="/cdn-cgi/styles/main.css" />
              </body>
            </html>
            """
        )

        assessment = await manager.assess_page(page, None)

        assert assessment.outcome == "challenge"
        assert "block-text-pattern" in assessment.indicators
        assert "cloudflare-attention-title" in assessment.indicators
        assert "cloudflare-interstitial-assets" in assessment.indicators
        await browser.close()


@pytest.mark.asyncio
async def test_bypass_manager_perform_bypass_turnstile_branch_returns_clear():
    manager = BypassManager()
    server, thread = _start_turnstile_server()

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()

            assessment = await manager.perform_bypass(
                page=page,
                target_url=f"http://127.0.0.1:{server.server_port}/turnstile-clear",
                timeout_ms=3_000,
                trusted_session=False,
                console_events=[],
            )

            assert assessment.outcome == "clear"
            await browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_bypass_manager_defensive_internal_branches():
    manager = BypassManager()

    class FailingMouse:
        async def move(self, *_args, **_kwargs):
            raise RuntimeError("move failure")

        async def wheel(self, *_args, **_kwargs):
            raise RuntimeError("wheel failure")

    class Page:
        frames = []

        def __init__(self):
            self.mouse = FailingMouse()

        async def wait_for_load_state(self, *_args, **_kwargs):
            return None

        async def evaluate(self, *_args, **_kwargs):
            raise RuntimeError("eval failure")

    await manager._stabilize_page(Page(), attempt_index=1, timeout_ms=100)


def test_package_main_verbose_helper_lines(capsys):
    package_main._write_result_output(
        {"status": 200, "headers": {"x-test": "1"}, "body": "body"},
        None,
        True,
    )

    captured = capsys.readouterr()
    assert "Status: 200" in captured.out
    assert "Headers:" in captured.out
    assert "-" * 50 in captured.out


def test_package_main_resolve_missing_command_branch():
    with pytest.raises(ValueError, match="No curl command provided"):
        package_main._resolve_curl_command(Namespace(file=None, curl=None))
