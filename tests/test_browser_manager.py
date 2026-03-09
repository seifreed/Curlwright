from __future__ import annotations

import pytest

from curlwright.infrastructure.browser_manager import BrowserManager


def test_browser_manager_build_launch_options_uses_conservative_no_gui_flags():
    manager = BrowserManager(headless=True, no_gui=True, proxy="http://127.0.0.1:8080")

    launch_options = manager._build_launch_options()

    assert launch_options["headless"] is True
    assert launch_options["proxy"] == {"server": "http://127.0.0.1:8080"}
    args = launch_options["args"]
    assert isinstance(args, list)
    assert "--disable-blink-features=AutomationControlled" in args
    assert "--single-process" not in args
    assert "--disable-images" not in args
    assert "--disable-web-security" not in args


def test_browser_manager_build_context_options_sets_realistic_defaults():
    manager = BrowserManager(headless=True, no_gui=True, verify_ssl=False)

    context_options = manager._build_context_options()

    assert context_options["locale"] == "en-US"
    assert context_options["timezone_id"] == "America/New_York"
    assert context_options["color_scheme"] == "light"
    assert context_options["ignore_https_errors"] is True
    assert context_options["screen"] == {"width": 1920, "height": 1080}


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


def test_browser_manager_build_init_script_contains_native_stealth_overrides():
    manager = BrowserManager(headless=True, no_gui=True)
    script = manager._build_init_script()

    assert "Object.defineProperty(navigator, 'userAgentData'" in script
    assert "Object.defineProperty(navigator, 'vendor'" in script
    assert "WebGLRenderingContext.prototype.getParameter" in script


@pytest.mark.asyncio
async def test_browser_manager_initializes_creates_page_and_closes():
    manager = BrowserManager(headless=True, no_gui=True, verify_ssl=False, profile_dir=None)

    try:
        await manager.initialize()
        assert manager.browser is not None
        assert manager.context is not None

        page = await manager.create_page()
        hidden = await page.evaluate("document.hidden")
        visibility = await page.evaluate("document.visibilityState")
        user_agent = await page.evaluate("navigator.userAgent")
        vendor = await page.evaluate("navigator.vendor")
        platform = await page.evaluate("navigator.platform")
        hardware = await page.evaluate("navigator.hardwareConcurrency")
        ua_data = await page.evaluate("navigator.userAgentData && navigator.userAgentData.platform")

        assert hidden is False
        assert visibility == "visible"
        assert user_agent == manager.user_agent
        assert vendor == "Google Inc."
        assert platform == "Win32"
        assert hardware == 8
        assert ua_data == "Windows"
    finally:
        await manager.close()

    assert manager.page is None
    assert manager.context is None
    assert manager.browser is None
    assert manager.playwright is None


@pytest.mark.asyncio
async def test_wait_for_cloudflare_returns_true_when_no_challenge():
    manager = BrowserManager(headless=True, no_gui=True)

    try:
        await manager.initialize()
        page = await manager.create_page()
        await page.set_content("<html><body><h1>clear page</h1></body></html>")

        assert await manager.wait_for_cloudflare(page, timeout=1) is True
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_wait_for_cloudflare_detects_resolution():
    manager = BrowserManager(headless=True, no_gui=True)

    try:
        await manager.initialize()
        page = await manager.create_page()
        await page.set_content(
            """
            <html>
              <body>
                <div id="challenge-running">challenge</div>
                <script>
                  setTimeout(() => {
                    const node = document.getElementById('challenge-running');
                    if (node) node.remove();
                  }, 200);
                </script>
              </body>
            </html>
            """
        )

        assert await manager.wait_for_cloudflare(page, timeout=2) is True
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_wait_for_cloudflare_times_out_when_challenge_persists():
    manager = BrowserManager(headless=True, no_gui=True)

    try:
        await manager.initialize()
        page = await manager.create_page()
        await page.set_content("<div id='challenge-running'>challenge</div>")

        assert await manager.wait_for_cloudflare(page, timeout=1) is False
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_handle_turnstile_detects_resolution():
    manager = BrowserManager(headless=True, no_gui=True)

    try:
        await manager.initialize()
        page = await manager.create_page()
        await page.set_content(
            """
            <html>
              <body>
                <iframe id="ts" src="https://challenges.cloudflare.com/turnstile/v0/test"></iframe>
                <script>
                  setTimeout(() => {
                    const node = document.getElementById('ts');
                    if (node) node.remove();
                  }, 200);
                </script>
              </body>
            </html>
            """
        )

        assert await manager.handle_turnstile(page, timeout=2) is True
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_handle_turnstile_returns_false_when_widget_persists():
    manager = BrowserManager(headless=True, no_gui=True)

    try:
        await manager.initialize()
        page = await manager.create_page()
        await page.set_content(
            "<iframe src='https://challenges.cloudflare.com/turnstile/v0/test'></iframe>"
        )

        assert await manager.handle_turnstile(page, timeout=1) is False
    finally:
        await manager.close()
