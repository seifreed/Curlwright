from __future__ import annotations

import pytest

from curlwright.infrastructure.browser_manager import BrowserManager


def test_browser_manager_build_launch_options_drives_real_chrome():
    manager = BrowserManager(headless=True, no_gui=True, proxy="http://127.0.0.1:8080")

    launch_options = manager._build_launch_options()

    assert launch_options["channel"] == "chrome"
    assert launch_options["headless"] is True
    assert launch_options["proxy"] == {"server": "http://127.0.0.1:8080"}
    args = launch_options["args"]
    assert isinstance(args, list)
    assert "--disable-dev-shm-usage" in args
    # Automation-flagging switches are no longer sent (Patchright neutralises
    # AutomationControlled at the protocol level).
    assert "--disable-blink-features=AutomationControlled" not in args
    assert "--single-process" not in args
    assert "--disable-web-security" not in args


def test_browser_manager_build_context_options_sets_realistic_defaults():
    manager = BrowserManager(headless=True, no_gui=True, verify_ssl=False)

    context_options = manager._build_context_options()

    assert context_options["locale"] == "en-US"
    assert context_options["timezone_id"] == "America/New_York"
    assert context_options["color_scheme"] == "light"
    assert context_options["ignore_https_errors"] is True
    assert context_options["screen"] == {"width": 1920, "height": 1080}
    # No forced user agent or Windows client-hint headers: real Chrome supplies
    # its own consistent values.
    assert "user_agent" not in context_options
    assert "extra_http_headers" not in context_options


def test_browser_manager_sets_explicit_user_agent_only_when_pinned():
    manager = BrowserManager(headless=True, user_agent="Custom/2.0")
    assert manager._build_context_options()["user_agent"] == "Custom/2.0"

    default_manager = BrowserManager(headless=True)
    assert default_manager.user_agent is None


def test_browser_manager_uses_default_persistent_profile_dir():
    manager = BrowserManager(headless=True, no_gui=True)

    assert manager.profile_dir.name == "browser-profile"


@pytest.mark.asyncio
async def test_browser_manager_initializes_persistent_context_with_profile_dir(tmp_path):
    manager = BrowserManager(headless=True, no_gui=True, profile_dir=str(tmp_path / "profile"))

    try:
        await manager.initialize()
        assert manager.context is not None
        assert manager.profile_dir == tmp_path / "profile"
        assert manager.profile_dir.exists()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_browser_manager_launches_real_chrome_and_closes():
    manager = BrowserManager(headless=True, no_gui=True, verify_ssl=False, profile_dir=None)

    try:
        await manager.initialize()
        assert manager.context is not None

        page = await manager.create_page()
        user_agent = await page.evaluate("navigator.userAgent")
        vendor = await page.evaluate("navigator.vendor")

        # Genuine Chrome fingerprint (not a spoofed init script).
        assert "Chrome" in user_agent
        assert vendor == "Google Inc."
    finally:
        await manager.close()

    assert manager.page is None
    assert manager.context is None
    assert manager.browser is None
    assert manager.playwright is None
