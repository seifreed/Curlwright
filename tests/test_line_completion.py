from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

import curlwright.main as package_main
from curlwright.contracts import EXIT_IO_ERROR, EXIT_PARSE_ERROR, build_failure_payload
from curlwright.infrastructure.browser_manager import BrowserManager
from curlwright.infrastructure.protection_runtime import (
    PlaywrightChallengeActuator,
    PlaywrightPageProbe,
)


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

    assert module.__all__ == ["main", "_resolve_curl_command", "_write_result_output"]


def test_package_cli_inserts_project_root_on_fresh_load():
    module, project_root = _load_module_without_project_root(
        Path(__file__).resolve().parents[1] / "curlwright" / "cli.py",
        "curlwright_cli_fresh",
    )

    assert callable(module.main)


@pytest.mark.asyncio
async def test_browser_manager_create_page_initializes_lazily(tmp_path):
    manager = BrowserManager(headless=True, no_gui=True, profile_dir=str(tmp_path / "profile"))

    try:
        page = await manager.create_page()
        assert manager.context is not None
        assert page is manager.page
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_browser_manager_initializes_with_proxy_branch(tmp_path):
    manager = BrowserManager(
        headless=True,
        no_gui=True,
        proxy="http://127.0.0.1:8888",
        profile_dir=str(tmp_path / "profile"),
    )

    try:
        await manager.initialize()
        assert manager.browser is not None
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_page_probe_assess_page_sets_cloudflare_indicators():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content("""
            <html>
              <head>
                <title>Attention Required! | Cloudflare</title>
              </head>
              <body>
                Sorry, you have been blocked
                <img src="/cdn-cgi/styles/main.css" />
              </body>
            </html>
            """)

        assessment = await PlaywrightPageProbe().assess_page(page, None)

        assert assessment.outcome == "challenge"
        assert "block-text-pattern" in assessment.indicators
        assert "cloudflare-attention-title" in assessment.indicators
        assert "cloudflare-interstitial-assets" in assessment.indicators
        await browser.close()


@pytest.mark.asyncio
async def test_challenge_actuator_defensive_internal_branches():
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

    await PlaywrightChallengeActuator().stabilize_page(Page(), attempt_index=1, timeout_ms=100)


def test_package_main_verbose_helper_lines(capsys):
    package_main._write_result_output(
        {"status": 200, "headers": {"x-test": "1"}, "body": "body"},
        None,
        True,
        False,
    )

    captured = capsys.readouterr()
    assert "Status: 200" in captured.out
    assert "Headers:" in captured.out
    assert "-" * 50 in captured.out


def test_package_main_resolve_missing_command_branch():
    with pytest.raises(ValueError, match="No curl command provided"):
        package_main._resolve_curl_command(Namespace(file=None, curl=None))


def test_package_main_failure_payload_contract():
    parse_payload = build_failure_payload(ValueError("bad curl"))
    io_payload = build_failure_payload(FileNotFoundError("missing"))

    assert parse_payload["schema_version"] == 1
    assert parse_payload["kind"] == "curlwright-error"
    assert parse_payload["ok"] is False
    assert parse_payload["exit_code"] == EXIT_PARSE_ERROR
    assert io_payload["exit_code"] == EXIT_IO_ERROR
