from __future__ import annotations

import pytest

from src.core.browser_manager import BrowserManager


@pytest.mark.asyncio
async def test_browser_manager_initializes_creates_page_and_closes():
    manager = BrowserManager(headless=True, no_gui=True, verify_ssl=False)

    try:
        await manager.initialize()
        assert manager.browser is not None
        assert manager.context is not None

        page = await manager.create_page()
        hidden = await page.evaluate("document.hidden")
        visibility = await page.evaluate("document.visibilityState")
        user_agent = await page.evaluate("navigator.userAgent")

        assert hidden is False
        assert visibility == "visible"
        assert user_agent == manager.user_agent
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
