from __future__ import annotations

import pytest

from src.core.browser_manager import BrowserManager
from src.core.bypass_manager import BypassManager


class FailingLocator:
    def __init__(self, *, count_error: Exception | None = None, inner_text_error: Exception | None = None):
        self._count_error = count_error
        self._inner_text_error = inner_text_error

    async def count(self):
        if self._count_error is not None:
            raise self._count_error
        return 0

    async def inner_text(self):
        if self._inner_text_error is not None:
            raise self._inner_text_error
        return ""


class DefensivePage:
    url = "https://example.com/failure"

    def __init__(
        self,
        *,
        title_error: Exception | None = None,
        content_error: Exception | None = None,
        locator_count_error: Exception | None = None,
        locator_text_error: Exception | None = None,
        wait_error: Exception | None = None,
    ):
        self._title_error = title_error
        self._content_error = content_error
        self._locator_count_error = locator_count_error
        self._locator_text_error = locator_text_error
        self._wait_error = wait_error

    async def title(self):
        if self._title_error is not None:
            raise self._title_error
        return ""

    async def content(self):
        if self._content_error is not None:
            raise self._content_error
        return ""

    def locator(self, _selector: str):
        return FailingLocator(
            count_error=self._locator_count_error,
            inner_text_error=self._locator_text_error,
        )

    async def wait_for_load_state(self, *_args, **_kwargs):
        if self._wait_error is not None:
            raise self._wait_error


class FailingCloseResource:
    async def close(self):
        raise RuntimeError("close failure")


class FailingStopResource:
    async def stop(self):
        raise RuntimeError("stop failure")


@pytest.mark.asyncio
async def test_bypass_manager_assess_page_tolerates_page_failures():
    manager = BypassManager()
    page = DefensivePage(
        title_error=RuntimeError("title"),
        content_error=RuntimeError("content"),
        locator_count_error=RuntimeError("count"),
        locator_text_error=RuntimeError("text"),
    )

    assessment = await manager.assess_page(page, response=None)

    assert assessment.outcome == "clear"
    assert assessment.title == ""
    assert assessment.body_excerpt == ""


def test_bypass_manager_assess_response_payload_marks_empty_204_body():
    assessment = BypassManager().assess_response_payload(
        {"status": 204, "url": "https://example.com/empty", "body": ""}
    )

    assert assessment.outcome == "clear"
    assert "empty-body" in assessment.indicators


@pytest.mark.asyncio
async def test_bypass_manager_selector_exists_returns_false_on_errors():
    manager = BypassManager()
    page = DefensivePage(locator_count_error=RuntimeError("boom"))

    assert await manager._selector_exists(page, "div#challenge-running") is False


@pytest.mark.asyncio
async def test_bypass_manager_stabilize_page_tolerates_wait_failures():
    manager = BypassManager()

    class PageWithFailingWait(DefensivePage):
        class Mouse:
            async def move(self, *_args, **_kwargs):
                return None

            async def wheel(self, *_args, **_kwargs):
                return None

        mouse = Mouse()

        async def evaluate(self, *_args, **_kwargs):
            return None

    page = PageWithFailingWait(wait_error=RuntimeError("networkidle"))

    await manager._stabilize_page(page, attempt_index=1, timeout_ms=100)


@pytest.mark.asyncio
async def test_bypass_manager_turnstile_resolution_falls_back_when_wait_fails():
    manager = BypassManager()
    page = DefensivePage(wait_error=RuntimeError("networkidle"))
    page.frames = []

    await manager._attempt_turnstile_resolution(page, timeout_ms=100)


@pytest.mark.asyncio
async def test_bypass_manager_challenge_progress_ignores_reload_errors():
    manager = BypassManager()

    class ReloadFailPage(DefensivePage):
        async def reload(self, *_args, **_kwargs):
            raise RuntimeError("reload failed")

    await manager._attempt_challenge_progress(ReloadFailPage(), attempt_index=1, timeout_ms=100)


@pytest.mark.asyncio
async def test_browser_manager_close_tolerates_resource_failures():
    manager = BrowserManager()
    manager.page = FailingCloseResource()
    manager.context = FailingCloseResource()
    manager.browser = FailingCloseResource()
    manager.playwright = FailingStopResource()

    await manager.close()


@pytest.mark.asyncio
async def test_browser_manager_wait_and_turnstile_return_false_on_locator_errors():
    manager = BrowserManager()
    failing_page = DefensivePage(locator_count_error=RuntimeError("locator failure"))

    assert await manager.wait_for_cloudflare(failing_page, timeout=1) is False
    assert await manager.handle_turnstile(failing_page, timeout=1) is False
