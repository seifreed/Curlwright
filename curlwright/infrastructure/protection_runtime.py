"""Fine-grained Playwright adapters for protection probing and actions."""

from __future__ import annotations

import asyncio
from pathlib import Path

from curlwright.infrastructure.bypass_artifacts import FailureArtifactStore
from curlwright.infrastructure.bypass_classifier import (
    TURNSTILE_SELECTORS,
    TURNSTILE_SUCCESS_PATTERNS,
    BypassClassifier,
)


class ConsoleTelemetry:
    def attach_console_capture(self, page) -> list[dict[str, str]]:
        console_events: list[dict[str, str]] = []

        def handle_console(message) -> None:
            console_events.append({"type": message.type, "text": message.text})

        page.on("console", handle_console)
        return console_events


class PlaywrightArtifactStore:
    def __init__(self, artifact_root: Path):
        self.artifact_root = artifact_root
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self._store = FailureArtifactStore(self.artifact_root)

    async def collect(self, *, page, assessment, console_events: list[dict[str, str]], label: str):
        return await self._store.collect(
            page=page,
            assessment=assessment,
            console_events=console_events,
            label=label,
        )


class PlaywrightPageProbe:
    def __init__(self):
        self.classifier = BypassClassifier()

    async def assess_page(self, page, response):
        return await self.classifier.assess_page(page, response)

    def assess_response_payload(self, payload):
        return self.classifier.assess_response_payload(payload)

    async def is_managed_challenge(self, page) -> bool:
        if "__cf_chl_" in page.url:
            return True
        try:
            html = (await page.content()).lower()
        except Exception:
            return False
        return "window._cf_chl_opt" in html or "/cdn-cgi/challenge-platform/" in html


class PlaywrightChallengeActuator:
    async def stabilize_page(self, page, *, attempt_index: int, timeout_ms: int) -> None:
        await asyncio.sleep(min(0.35 + attempt_index * 0.2, 1.0))
        try:
            await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 2_500))
        except Exception:
            pass
        try:
            await page.mouse.move(120 + 20 * attempt_index, 160 + 20 * attempt_index)
            await page.mouse.wheel(0, 250)
        except Exception:
            pass
        try:
            await page.evaluate(
                """
                () => {
                    window.dispatchEvent(new Event('mousemove'));
                    window.dispatchEvent(new Event('scroll'));
                }
                """
            )
        except Exception:
            pass

    async def resolve_turnstile(self, page, *, timeout_ms: int) -> None:
        selectors = [
            "button#solve-turnstile",
            "button[type='submit']",
            "input[type='checkbox']",
            "[role='checkbox']",
            "label",
        ]
        interacted = False
        for frame in page.frames:
            for selector in selectors:
                try:
                    locator = frame.locator(selector)
                    if await locator.count() > 0:
                        await locator.first.click(timeout=1_000)
                        interacted = True
                        await asyncio.sleep(0.5)
                        break
                except Exception:
                    continue
            if interacted:
                break

        if not interacted:
            interacted = await self._click_turnstile_iframe_center(page)

        await self._wait_for_turnstile_progress(
            page,
            timeout_ms=timeout_ms,
            expect_interaction=interacted,
        )

    async def advance_challenge(self, page, *, attempt_index: int, timeout_ms: int) -> None:
        await asyncio.sleep(min(0.75 * attempt_index, 2.0))
        if attempt_index % 2 == 1:
            try:
                await page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception:
                pass

    async def wait_for_managed_challenge(self, page, *, timeout_ms: int) -> None:
        deadline = asyncio.get_event_loop().time() + min(timeout_ms / 1000, 10.0)
        while asyncio.get_event_loop().time() < deadline:
            if "__cf_chl_" not in page.url:
                try:
                    html = (await page.content()).lower()
                except Exception:
                    html = ""
                if "window._cf_chl_opt" not in html and "/cdn-cgi/challenge-platform/" not in html:
                    return
            try:
                await page.wait_for_load_state("networkidle", timeout=1_000)
            except Exception:
                pass
            await asyncio.sleep(0.5)

    async def revisit_target(self, page, *, target_url: str, timeout_ms: int) -> None:
        if page.url == target_url and "__cf_chl_" not in page.url:
            return
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass

    async def _click_turnstile_iframe_center(self, page) -> bool:
        iframe_selectors = [
            "iframe[src*='challenges.cloudflare.com']",
            "iframe[src*='turnstile']",
        ]
        for selector in iframe_selectors:
            try:
                locator = page.locator(selector)
                count = await locator.count()
            except Exception:
                continue
            for index in range(count):
                try:
                    box = await locator.nth(index).bounding_box()
                    if not box:
                        continue
                    await page.mouse.click(
                        box["x"] + box["width"] / 2,
                        box["y"] + box["height"] / 2,
                    )
                    await asyncio.sleep(0.5)
                    return True
                except Exception:
                    continue
        return False

    async def _wait_for_turnstile_progress(
        self,
        page,
        *,
        timeout_ms: int,
        expect_interaction: bool,
    ) -> None:
        deadline = asyncio.get_event_loop().time() + min(timeout_ms / 1000, 8.0)
        while asyncio.get_event_loop().time() < deadline:
            if await self._turnstile_response_ready(page):
                return
            if await self._page_contains_any(page, TURNSTILE_SUCCESS_PATTERNS):
                return
            if expect_interaction:
                selectors_remaining = False
                for selector in TURNSTILE_SELECTORS:
                    if await self._selector_exists(page, selector):
                        selectors_remaining = True
                        break
                if not selectors_remaining:
                    return
            try:
                await page.wait_for_load_state("networkidle", timeout=750)
                return
            except Exception:
                await asyncio.sleep(0.35)

    async def _turnstile_response_ready(self, page) -> bool:
        try:
            locator = page.locator("input[name='cf-turnstile-response']")
            if await locator.count() == 0:
                return False
            value = await locator.first.input_value(timeout=500)
            return bool(value.strip())
        except Exception:
            return False

    async def _page_contains_any(self, page, patterns: list[str]) -> bool:
        try:
            title = (await page.title()).lower()
        except Exception:
            title = ""
        try:
            body_text = (await page.locator("body").inner_text()).lower()
        except Exception:
            body_text = ""
        combined = f"{title}\n{body_text}"
        return any(pattern in combined for pattern in patterns)

    async def _selector_exists(self, page, selector: str) -> bool:
        try:
            return await page.locator(selector).count() > 0
        except Exception:
            return False
