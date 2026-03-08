"""Bypass-specific analysis, retry strategy, and failure instrumentation."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from src.runtime_compat import ensure_supported_python

ensure_supported_python()

type ConsoleEvent = dict[str, str]

CHALLENGE_SELECTORS = [
    "div.cf-browser-verification",
    "div#cf-content",
    "div#challenge-running",
    "div#challenge-stage",
    "form#challenge-form",
    "iframe[src*='challenges.cloudflare.com']",
    "div.cf-turnstile",
    "input[name='cf-turnstile-response']",
]

TURNSTILE_SELECTORS = [
    "iframe[src*='turnstile']",
    "div.cf-turnstile",
    "input[name='cf-turnstile-response']",
]

BLOCK_TEXT_PATTERNS = [
    "access denied",
    "attention required",
    "attention required! | cloudflare",
    "checking if the site connection is secure",
    "forbidden",
    "temporarily blocked",
    "rate limited",
    "too many requests",
    "please enable cookies",
    "sorry, you have been blocked",
]

CHALLENGE_TEXT_PATTERNS = [
    "just a moment",
    "checking your browser",
    "checking if the site connection is secure",
    "verify you are human",
    "challenge-platform",
    "/cdn-cgi/challenge-platform/",
    "/cdn-cgi/styles/",
    "__cf_chl_",
    "cf browser verification",
    "cf-challenge",
    "cf-wrapper",
]


@dataclass
class BypassAssessment:
    """Classification of the current page or fetch response."""

    outcome: str
    final_url: str
    title: str = ""
    status_code: int | None = None
    indicators: list[str] = field(default_factory=list)
    body_excerpt: str = ""

    @property
    def is_clear(self) -> bool:
        return self.outcome == "clear"


class BypassFailure(RuntimeError):
    """Raised when the bypass flow does not reach a trusted state."""

    def __init__(
        self,
        message: str,
        *,
        assessment: BypassAssessment,
        artifact_dir: str | None = None,
    ):
        super().__init__(message)
        self.assessment = assessment
        self.artifact_dir = artifact_dir


class BypassManager:
    """Encapsulates warm-up, challenge handling, and diagnostics."""

    def __init__(
        self,
        artifact_root: str | None = None,
        max_attempts: int = 3,
    ):
        self.artifact_root = (
            Path(artifact_root)
            if artifact_root
            else Path.home() / ".curlwright" / "artifacts"
        )
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.max_attempts = max_attempts

    def attach_console_capture(self, page) -> list[ConsoleEvent]:
        """Capture console messages for failure diagnostics."""
        console_events: list[ConsoleEvent] = []

        def handle_console(message) -> None:
            console_events.append(
                {
                    "type": message.type,
                    "text": message.text,
                }
            )

        page.on("console", handle_console)
        return console_events

    async def perform_bypass(
        self,
        *,
        page,
        target_url: str,
        timeout_ms: int,
        trusted_session: bool,
        console_events: list[ConsoleEvent],
    ) -> BypassAssessment:
        """Drive the page through challenge resolution until clear or failed."""
        attempt_urls = self._build_attempt_urls(target_url, trusted_session)
        latest_assessment = BypassAssessment(outcome="challenge", final_url=target_url)

        for attempt_index, navigate_url in enumerate(attempt_urls, start=1):
            response = await page.goto(
                navigate_url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            await self._stabilize_page(page, attempt_index, timeout_ms)

            latest_assessment = await self.assess_page(page, response)
            if latest_assessment.is_clear:
                return latest_assessment

            if latest_assessment.outcome == "turnstile":
                await self._attempt_turnstile_resolution(page, timeout_ms)
            else:
                await self._attempt_challenge_progress(page, attempt_index, timeout_ms)

            latest_assessment = await self.assess_page(page, None)
            if latest_assessment.is_clear:
                return latest_assessment

        artifact_dir = await self.collect_failure_artifacts(
            page=page,
            assessment=latest_assessment,
            console_events=console_events,
            label="bypass-failure",
        )
        raise BypassFailure(
            "Bypass did not reach a trusted page state",
            assessment=latest_assessment,
            artifact_dir=str(artifact_dir),
        )

    async def assess_page(self, page, response) -> BypassAssessment:
        """Classify the currently loaded document."""
        title = ""
        html = ""
        body_text = ""
        indicators: list[str] = []
        status_code = getattr(response, "status", None) if response is not None else None

        try:
            title = await page.title()
        except Exception:
            title = ""

        try:
            html = await page.content()
        except Exception:
            html = ""

        try:
            body_text = await page.locator("body").inner_text()
        except Exception:
            body_text = ""

        lower_html = html.lower()
        lower_title = title.lower()
        lower_body = body_text.lower()

        for selector in CHALLENGE_SELECTORS:
            if await self._selector_exists(page, selector):
                indicators.append(f"selector:{selector}")

        if any(pattern in lower_html or pattern in lower_title or pattern in lower_body for pattern in CHALLENGE_TEXT_PATTERNS):
            indicators.append("challenge-text-pattern")

        if any(pattern in lower_html or pattern in lower_title or pattern in lower_body for pattern in BLOCK_TEXT_PATTERNS):
            indicators.append("block-text-pattern")

        if "cloudflare" in lower_title and "attention required" in lower_title:
            indicators.append("cloudflare-attention-title")

        if "/cdn-cgi/styles/" in lower_html and "cloudflare" in lower_html:
            indicators.append("cloudflare-interstitial-assets")

        if status_code in {403, 429, 503}:
            indicators.append(f"status:{status_code}")

        if not body_text.strip() and status_code in {403, 429, 503}:
            indicators.append("empty-body-on-block-status")

        if any(selector.endswith("turnstile-response']") or "turnstile" in selector for selector in indicators):
            outcome = "turnstile"
        elif any(
            item.startswith("selector:")
            or item in {
                "challenge-text-pattern",
                "cloudflare-attention-title",
                "cloudflare-interstitial-assets",
            }
            for item in indicators
        ):
            outcome = "challenge"
        elif "block-text-pattern" in indicators or any(item.startswith("status:") for item in indicators):
            outcome = "blocked"
        else:
            outcome = "clear"

        return BypassAssessment(
            outcome=outcome,
            final_url=page.url,
            title=title,
            status_code=status_code,
            indicators=sorted(set(indicators)),
            body_excerpt=self._compact_text(body_text or html),
        )

    def assess_response_payload(self, payload: dict[str, object]) -> BypassAssessment:
        """Classify the final fetch response to ensure bypass really held."""
        body = str(payload.get("body", ""))
        lower_body = body.lower()
        status_code = int(payload.get("status", 0))
        indicators: list[str] = []

        if status_code in {403, 429, 503}:
            indicators.append(f"status:{status_code}")
        if any(pattern in lower_body for pattern in CHALLENGE_TEXT_PATTERNS):
            indicators.append("challenge-text-pattern")
        if any(pattern in lower_body for pattern in BLOCK_TEXT_PATTERNS):
            indicators.append("block-text-pattern")
        if "attention required! | cloudflare" in lower_body:
            indicators.append("cloudflare-attention-title")
        if "/cdn-cgi/styles/" in lower_body and "cloudflare" in lower_body:
            indicators.append("cloudflare-interstitial-assets")
        if status_code in {200, 204} and not body.strip():
            indicators.append("empty-body")

        if any(
            indicator in {
                "challenge-text-pattern",
                "cloudflare-attention-title",
                "cloudflare-interstitial-assets",
            }
            for indicator in indicators
        ):
            outcome = "challenge"
        elif "block-text-pattern" in indicators or any(item.startswith("status:") for item in indicators):
            outcome = "blocked"
        else:
            outcome = "clear"

        return BypassAssessment(
            outcome=outcome,
            final_url=str(payload.get("url", "")),
            title="",
            status_code=status_code,
            indicators=indicators,
            body_excerpt=self._compact_text(body),
        )

    async def collect_failure_artifacts(
        self,
        *,
        page,
        assessment: BypassAssessment,
        console_events: list[ConsoleEvent],
        label: str,
    ) -> Path:
        """Persist screenshot, HTML, and diagnostics for failed bypasses."""
        artifact_dir = self.artifact_root / self._artifact_directory_name(page.url, label)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        html_path = artifact_dir / "page.html"
        screenshot_path = artifact_dir / "page.png"
        assessment_path = artifact_dir / "assessment.json"
        console_path = artifact_dir / "console.json"

        html_path.write_text(await page.content())
        await page.screenshot(path=str(screenshot_path), full_page=True)
        assessment_path.write_text(json.dumps(asdict(assessment), indent=2, sort_keys=True))
        console_path.write_text(json.dumps(console_events, indent=2, sort_keys=True))
        return artifact_dir

    async def _stabilize_page(self, page, attempt_index: int, timeout_ms: int) -> None:
        """Give the page enough time to execute challenge scripts and assets."""
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

    async def _attempt_turnstile_resolution(self, page, timeout_ms: int) -> None:
        """Try to advance visible turnstile-like widgets before reassessing."""
        selectors = [
            "button#solve-turnstile",
            "button[type='submit']",
            "input[type='checkbox']",
            "[role='checkbox']",
            "label",
        ]
        for frame in page.frames:
            for selector in selectors:
                try:
                    locator = frame.locator(selector)
                    if await locator.count() > 0:
                        await locator.first.click(timeout=1_000)
                        await asyncio.sleep(0.5)
                        return
                except Exception:
                    continue

        try:
            await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 2_500))
        except Exception:
            pass

    async def _attempt_challenge_progress(self, page, attempt_index: int, timeout_ms: int) -> None:
        """Advance a challenge flow using reloads and revisit patterns."""
        await asyncio.sleep(min(0.75 * attempt_index, 2.0))
        if attempt_index % 2 == 1:
            try:
                await page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
                return
            except Exception:
                return

    async def _selector_exists(self, page, selector: str) -> bool:
        try:
            return await page.locator(selector).count() > 0
        except Exception:
            return False

    def _artifact_directory_name(self, url: str, label: str) -> str:
        hostname = urlparse(url).hostname or "unknown-host"
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        safe_hostname = re.sub(r"[^a-zA-Z0-9.-]+", "-", hostname)
        return f"{timestamp}-{safe_hostname}-{label}"

    def _build_attempt_urls(self, target_url: str, trusted_session: bool) -> list[str]:
        base_url = self._base_url(target_url)
        if trusted_session:
            return [target_url, target_url, base_url]
        return [target_url, base_url, target_url]

    def _base_url(self, target_url: str) -> str:
        parsed = urlparse(target_url)
        return f"{parsed.scheme}://{parsed.netloc}/"

    def _compact_text(self, raw_text: str, limit: int = 500) -> str:
        condensed = " ".join(raw_text.split())
        return condensed[:limit]
