"""nodriver engine: clears Cloudflare challenges Patchright can't by driving
Chrome over a plain CDP WebSocket (no Runtime.enable/Target.setAutoAttach).

Patchright still emits the automation-protocol CDP sequence that hardened
Cloudflare "managed challenge" pages fingerprint, so it stalls on "Just a
moment…". nodriver avoids that sequence and clears the interstitial on
navigation, then we read the page back through an in-page fetch that carries the
issued cf_clearance cookie — yielding a curl-like response.

Managed challenges only clear in HEADED mode; headless is detected just like
Patchright. The manager warns when asked to run headless.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from curlwright.domain import CurlRequest, FetchResponse
from curlwright.infrastructure.logging import setup_logger
from curlwright.infrastructure.playwright_runtime import PlaywrightRequestRuntime
from curlwright.runtime import ensure_supported_python

ensure_supported_python()

logger = setup_logger(__name__)

# Markers that mean the Cloudflare interstitial is still up (not yet cleared).
CHALLENGE_MARKERS = ("just a moment", "/cdn-cgi/challenge-platform/", "cf-mitigated")

# JS that performs the same in-page fetch the Playwright runtime uses, so the
# response carries the browser's (now-cleared) cookies. Args are inlined as JSON
# because nodriver.evaluate takes a bare expression, not a function + arg. The
# result is returned as a JSON string: nodriver.evaluate(return_by_value=True)
# hands back plain scalars directly but wraps objects in a CDP RemoteObject, so
# stringifying and parsing in Python sidesteps that.
_FETCH_JS = """
(async () => {{
    const url = {url};
    const options = {options};
    const timeoutMs = {timeout_ms};
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {{
        const response = await fetch(url, {{ ...options, signal: controller.signal }});
        const body = options.method === 'HEAD' ? '' : await response.text();
        const headers = {{}};
        response.headers.forEach((value, key) => {{ headers[key] = value; }});
        return JSON.stringify({{ url: response.url, status: response.status, headers, body }});
    }} catch (err) {{
        return JSON.stringify({{ url, status: 0, headers: {{}}, body: '', error: String(err) }});
    }} finally {{
        clearTimeout(timer);
    }}
}})()
"""


def _is_challenge(html: str) -> bool:
    lowered = (html or "").lower()
    return any(marker in lowered for marker in CHALLENGE_MARKERS)


class NodriverBrowserManager:
    """Drop-in engine alternative selected via ``--engine nodriver``.

    Only the native fetch flow is implemented; the Playwright page API is not,
    because the executor branches to :meth:`fetch` for this engine instead of
    going through ``create_page``/use-cases.
    """

    context: object | None = None

    def __init__(
        self,
        *,
        headless: bool = False,
        user_agent: str | None = None,
        no_gui: bool = False,
        proxy: str | None = None,
        verify_ssl: bool = True,
        http_credentials: dict[str, str] | None = None,
        profile_dir: str | None = None,
    ):
        self.headless = headless
        self.user_agent = user_agent
        self.no_gui = no_gui
        self.proxy = proxy
        self.verify_ssl = verify_ssl
        self.http_credentials = http_credentials
        self.profile_dir = (
            Path(profile_dir).expanduser()
            if profile_dir
            else Path.home() / ".curlwright" / "browser-profile-nodriver"
        )
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._browser = None
        self._runtime = PlaywrightRequestRuntime()

    async def initialize(self) -> None:
        import nodriver as uc

        if self.headless:
            logger.warning(
                "nodriver engine is running headless; Cloudflare managed "
                "challenges typically only clear in headed mode."
            )
        browser_args = ["--window-size=1920,1080"]
        if self.proxy:
            browser_args.append(f"--proxy-server={self.proxy}")
        if not self.verify_ssl:
            browser_args.append("--ignore-certificate-errors")
        if self.user_agent:
            browser_args.append(f"--user-agent={self.user_agent}")
        self._browser = await uc.start(
            headless=self.headless,
            user_data_dir=str(self.profile_dir),
            browser_args=browser_args,
        )
        logger.info("nodriver browser initialized successfully")

    async def fetch(
        self, request: CurlRequest, *, timeout_ms: int
    ) -> tuple[FetchResponse, list[str], str]:
        """Navigate (clearing the challenge), then read the page via an in-page
        fetch. Returns (response, cf-relevant cookie names, final page HTML)."""
        if self._browser is None:
            raise RuntimeError("nodriver browser is not initialized")
        tab = await self._browser.get(request.url)
        await self._wait_until_cleared(tab, timeout_ms=timeout_ms)

        options = self._runtime.build_fetch_options(request)
        script = _FETCH_JS.format(
            url=json.dumps(request.url),
            options=json.dumps(options),
            timeout_ms=int(timeout_ms),
        )
        raw = await tab.evaluate(script, await_promise=True, return_by_value=True)
        response = FetchResponse.from_payload(self._normalize_payload(raw, request.url))

        try:
            html = await tab.get_content()
        except Exception:
            html = ""
        cookie_names = await self._cookie_names()
        return response, cookie_names, html

    async def _wait_until_cleared(self, tab, *, timeout_ms: int) -> None:
        deadline = time.monotonic() + min(timeout_ms / 1000, 40.0)
        reloaded = False
        while time.monotonic() < deadline:
            try:
                html = await tab.get_content()
            except Exception:
                html = ""
            if not _is_challenge(html):
                return
            # One mid-flight reload nudges a stalled managed challenge.
            if not reloaded and time.monotonic() > deadline - (timeout_ms / 1000) / 2:
                reloaded = True
                try:
                    await tab.reload()
                except Exception:
                    logger.debug("nodriver reload during challenge wait failed", exc_info=True)
            await asyncio.sleep(1.5)
        logger.debug("nodriver: challenge still present after wait window")

    async def _cookie_names(self) -> list[str]:
        if self._browser is None:
            return []
        try:
            cookies = await self._browser.cookies.get_all()
        except Exception:
            logger.debug("nodriver cookie read failed", exc_info=True)
            return []
        return [getattr(c, "name", "") for c in cookies if getattr(c, "name", "")]

    def _normalize_payload(self, raw, fallback_url: str) -> dict:
        payload = raw
        if isinstance(raw, str):
            try:
                payload = json.loads(raw)
            except (ValueError, TypeError):
                payload = None
        if not isinstance(payload, dict):
            logger.debug("nodriver fetch returned unexpected payload: %r", raw)
            return {"status": 0, "headers": {}, "body": "", "url": fallback_url}
        return {
            "status": payload.get("status", 0),
            "headers": payload.get("headers", {}) or {},
            "body": payload.get("body", "") or "",
            "url": payload.get("url") or fallback_url,
        }

    async def create_page(self):
        raise NotImplementedError("nodriver engine uses fetch(); create_page is unused")

    async def close(self) -> None:
        if self._browser is not None:
            try:
                self._browser.stop()
            except Exception:
                logger.debug("nodriver stop failed", exc_info=True)
            self._browser = None
        logger.info("nodriver browser closed successfully")
