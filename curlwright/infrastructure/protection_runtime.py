"""Fine-grained Playwright adapters for protection probing and actions."""

from __future__ import annotations

import asyncio
from pathlib import Path

from curlwright.infrastructure.bypass_artifacts import FailureArtifactStore
from curlwright.infrastructure.bypass_classifier import (
    TURNSTILE_SELECTORS,
    TURNSTILE_SUCCESS_PATTERNS,
    BypassClassifier,
    selector_exists,
)
from curlwright.logger import setup_logger

logger = setup_logger(__name__)

MANAGED_CHALLENGE_URL_MARKER = "__cf_chl_"
MANAGED_CHALLENGE_HTML_MARKERS = ("window._cf_chl_opt", "/cdn-cgi/challenge-platform/")

# bounding_box() defaults to Playwright's 30s actionability wait; on a
# re-rendering cross-origin Turnstile iframe that wait never settles and stalls
# the whole bypass. Cap every box probe so a missing element degrades fast.
BOX_TIMEOUT_MS = 1_500


def _html_shows_managed_challenge(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in MANAGED_CHALLENGE_HTML_MARKERS)


def _checkbox_point(box: dict[str, float]) -> tuple[float, float]:
    """Return the (x, y) of the Turnstile checkbox within a widget bounding box.

    The checkbox renders ~30px from the left edge, vertically centred; the
    offset is clamped so it stays inside narrow/compact widgets.
    """
    x = box["x"] + min(30.0, box["width"] / 2)
    y = box["y"] + box["height"] / 2
    return x, y


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

    async def save_blocked_html(self, url: str, html: str, label: str) -> str | None:
        return await self._store.save_blocked_html(url, html, label)


class PlaywrightPageProbe:
    def __init__(self):
        self.classifier = BypassClassifier()

    async def assess_page(self, page, response):
        return await self.classifier.assess_page(page, response)

    def assess_response_payload(self, payload):
        return self.classifier.assess_response_payload(payload)

    async def is_managed_challenge(self, page) -> bool:
        if MANAGED_CHALLENGE_URL_MARKER in page.url:
            return True
        try:
            html = await page.content()
        except Exception:
            return False
        return _html_shows_managed_challenge(html)


class PlaywrightChallengeActuator:
    async def stabilize_page(self, page, *, attempt_index: int, timeout_ms: int) -> None:
        await asyncio.sleep(min(0.35 + attempt_index * 0.2, 1.0))
        try:
            await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 2_500))
        except Exception:
            logger.debug("networkidle wait failed during page stabilization", exc_info=True)
        try:
            await page.mouse.move(120 + 20 * attempt_index, 160 + 20 * attempt_index)
            await page.mouse.wheel(0, 250)
        except Exception:
            logger.debug("synthetic mouse interaction failed", exc_info=True)
        try:
            await page.evaluate("""
                () => {
                    window.dispatchEvent(new Event('mousemove'));
                    window.dispatchEvent(new Event('scroll'));
                }
                """)
        except Exception:
            logger.debug("synthetic event dispatch failed", exc_info=True)

    async def resolve_turnstile(self, page, *, timeout_ms: int) -> None:
        # The human-simulation warm-up scrolls the page; a scrolled widget makes
        # the checkbox click land off-target and the token never issues. Reset to
        # the top so the widget sits where Playwright will click it.
        try:
            await page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            logger.debug("scroll-to-top before turnstile click failed", exc_info=True)

        # Primary path: click the checkbox INSIDE the Cloudflare challenge frame.
        # The widget iframe lives in a closed shadow DOM and never settles for a
        # coordinate click (its bounding_box() times out, and the wrapper div is
        # far wider than the widget so a left-offset guess misses), but Playwright
        # can still drive the real <input> inside the frame. Coordinate and
        # generic-selector clicks remain as fallbacks.
        interacted = await self._click_challenge_frame_checkbox(page, timeout_ms=timeout_ms)
        if not interacted:
            interacted = await self._click_turnstile_checkbox(page)
        if not interacted:
            interacted = await self._click_turnstile_selectors(page)

        await self._wait_for_turnstile_progress(
            page,
            timeout_ms=timeout_ms,
            expect_interaction=interacted,
        )

    async def _click_challenge_frame_checkbox(self, page, *, timeout_ms: int) -> bool:
        # Restrict to Cloudflare-owned frames so we never click a host-page
        # control (which could trigger a navigation). frame.locator(...).click()
        # resolves the element and its real coordinates internally, reaching the
        # checkbox even when the iframe element itself is not actionable.
        #
        # The click can "succeed" (Playwright dispatches it) yet not toggle the
        # box — e.g. a CSS-transformed widget shifts the real hit point. So we
        # verify the issued token after each click and keep retrying within the
        # deadline instead of trusting a single dispatch.
        deadline = asyncio.get_event_loop().time() + min(timeout_ms / 1000, 12.0)
        clicked = False
        while asyncio.get_event_loop().time() < deadline:
            did_click = False
            for frame in page.frames:
                url = getattr(frame, "url", "") or ""
                if "challenges.cloudflare.com" not in url and "turnstile" not in url:
                    continue
                for selector in ("input[type='checkbox']", "[role='checkbox']"):
                    try:
                        locator = frame.locator(selector)
                        if await locator.count() > 0:
                            await locator.first.click(timeout=3_000)
                            clicked = did_click = True
                    except Exception:
                        logger.debug(
                            "turnstile frame checkbox %s click failed", selector, exc_info=True
                        )
            # Give a fresh click up to ~3s to settle into a token before
            # re-clicking, so we never reset a widget that is mid-verification.
            if did_click:
                for _ in range(6):
                    if await self._turnstile_response_ready(page):
                        return True
                    await asyncio.sleep(0.5)
            else:
                await asyncio.sleep(0.5)
        return clicked

    async def _click_turnstile_selectors(self, page) -> bool:
        selectors = [
            "button#solve-turnstile",
            "input[type='checkbox']",
            "[role='checkbox']",
        ]
        for frame in page.frames:
            for selector in selectors:
                try:
                    locator = frame.locator(selector)
                    if await locator.count() > 0:
                        await locator.first.click(timeout=1_000)
                        await asyncio.sleep(0.5)
                        return True
                except Exception:
                    logger.debug(
                        "turnstile selector %s interaction failed", selector, exc_info=True
                    )
                    continue
        return False

    async def advance_challenge(self, page, *, attempt_index: int, timeout_ms: int) -> None:
        await asyncio.sleep(min(0.75 * attempt_index, 2.0))
        if attempt_index % 2 == 1:
            try:
                await page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception:
                logger.debug("challenge reload failed", exc_info=True)

    async def wait_for_managed_challenge(self, page, *, timeout_ms: int) -> None:
        deadline = asyncio.get_event_loop().time() + min(timeout_ms / 1000, 10.0)
        while asyncio.get_event_loop().time() < deadline:
            if MANAGED_CHALLENGE_URL_MARKER not in page.url:
                try:
                    html = await page.content()
                except Exception:
                    html = ""
                if not _html_shows_managed_challenge(html):
                    return
            try:
                await page.wait_for_load_state("networkidle", timeout=1_000)
            except Exception:
                logger.debug(
                    "networkidle wait failed while awaiting managed challenge", exc_info=True
                )
            await asyncio.sleep(0.5)

    async def revisit_target(self, page, *, target_url: str, timeout_ms: int) -> None:
        if page.url == target_url and "__cf_chl_" not in page.url:
            return
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception:
            logger.debug("revisit navigation to %s failed", target_url, exc_info=True)

    async def _click_turnstile_checkbox(self, page) -> bool:
        # The Turnstile checkbox sits on the LEFT of the widget (~30px in,
        # vertically centred). We dispatch a trusted, human-like mouse move +
        # click (CDP Input → isTrusted=True, which also reaches the cross-origin
        # challenge iframe by coordinate). Phase 1 spends the whole window on the
        # REAL widget iframe so a slow-rendering iframe is not pre-empted by
        # clicking the always-present div.cf-turnstile wrapper.
        iframe_selectors = [
            "iframe[src*='challenges.cloudflare.com']",
            "iframe[src*='turnstile']",
        ]
        deadline = asyncio.get_event_loop().time() + 6.0
        while asyncio.get_event_loop().time() < deadline:
            for selector in iframe_selectors:
                point = await self._turnstile_checkbox_point(page, selector)
                if point is None:
                    continue
                if await self._dispatch_checkbox_click(page, *point):
                    return True
            await asyncio.sleep(0.4)
        # Phase 2: container fallback ONLY if the iframe never rendered.
        box = await self._first_visible_box(page, "div.cf-turnstile")
        if box is not None:
            return await self._dispatch_checkbox_click(page, *_checkbox_point(box))
        return False

    async def _turnstile_checkbox_point(self, page, selector):
        # Best effort: descend into the (possibly nested) challenge frame and
        # target the real checkbox element. Playwright's bounding_box() on an
        # element inside an iframe is already page-relative, so no offset math.
        # Falls back to the iframe-box heuristic when the inner element is not
        # queryable (closed shadow DOM / nested cross-origin frame — the norm).
        try:
            inner = page.frame_locator(selector).locator(
                "input[type='checkbox'], [role='checkbox'], label"
            )
            if await inner.count() > 0:
                box = await inner.first.bounding_box(timeout=BOX_TIMEOUT_MS)
                if box and box["width"] > 0 and box["height"] > 0:
                    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        except Exception:
            logger.debug("turnstile inner checkbox lookup failed", exc_info=True)
        box = await self._first_visible_box(page, selector)
        if box is None:
            return None
        return _checkbox_point(box)

    async def _dispatch_checkbox_click(self, page, x: float, y: float) -> bool:
        try:
            await page.mouse.move(x, y, steps=12)
            await page.mouse.click(x, y)
            await asyncio.sleep(0.5)
            return True
        except Exception:
            logger.debug("turnstile checkbox click failed", exc_info=True)
            return False

    async def _first_visible_box(self, page, selector: str):
        try:
            locator = page.locator(selector)
            count = await locator.count()
        except Exception:
            logger.debug("turnstile anchor %s lookup failed", selector, exc_info=True)
            return None
        for index in range(count):
            try:
                box = await locator.nth(index).bounding_box(timeout=BOX_TIMEOUT_MS)
            except Exception:
                logger.debug("turnstile anchor %s box failed", selector, exc_info=True)
                continue
            if box and box["width"] > 0 and box["height"] > 0:
                return box
        return None

    async def _wait_for_turnstile_progress(
        self,
        page,
        *,
        timeout_ms: int,
        expect_interaction: bool,
    ) -> None:
        # Poll for the issued token until the deadline. The token populates
        # ~1-3s after a valid checkbox click, so we must NOT bail after a single
        # networkidle wait (the old behaviour returned almost immediately).
        deadline = asyncio.get_event_loop().time() + min(timeout_ms / 1000, 15.0)
        while asyncio.get_event_loop().time() < deadline:
            if await self._turnstile_response_ready(page):
                return
            if await self._page_contains_any(page, TURNSTILE_SUCCESS_PATTERNS):
                return
            if expect_interaction:
                selectors_remaining = False
                for selector in TURNSTILE_SELECTORS:
                    if await selector_exists(page, selector):
                        selectors_remaining = True
                        break
                if not selectors_remaining:
                    return
            try:
                await page.wait_for_load_state("networkidle", timeout=750)
            except Exception:
                logger.debug("networkidle wait failed during turnstile progress", exc_info=True)
            await asyncio.sleep(0.4)

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
