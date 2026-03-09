"""Operational Playwright runtime helpers kept out of the application use case."""

import asyncio
import json

from curlwright.domain import CurlRequest, FetchResponse
from curlwright.runtime import ensure_supported_python

ensure_supported_python()

type FetchHeaders = dict[str, str]
type FetchOptions = dict[str, str | FetchHeaders]


class PlaywrightRequestRuntime:
    """Encapsulates warmup, header/cookie application, and final fetch execution."""

    async def warm_up_page(
        self,
        page,
        request: CurlRequest,
        timeout_ms: int,
        *,
        cookie_manager,
        trusted_session: bool,
    ) -> None:
        if cookie_manager:
            await cookie_manager.load_cookies(page.context)
        await self._simulate_human_warmup(
            page,
            request,
            timeout_ms=timeout_ms,
            trusted_session=trusted_session,
        )

    async def perform_fetch_request(self, page, request: CurlRequest, timeout_ms: int) -> FetchResponse:
        fetch_options = self.build_fetch_options(request)
        response = await page.evaluate(
            """
            async ({ url, options, timeoutMs }) => {
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort(), timeoutMs);
                try {
                    const fetchOptions = { ...options, signal: controller.signal };
                    const response = await fetch(url, fetchOptions);
                    const body = options.method === 'HEAD' ? '' : await response.text();
                    const headers = {};
                    response.headers.forEach((value, key) => {
                        headers[key] = value;
                    });
                    return {
                        url: response.url,
                        status: response.status,
                        headers,
                        body
                    };
                } finally {
                    clearTimeout(timer);
                }
            }
            """,
            {"url": request.url, "options": fetch_options, "timeoutMs": timeout_ms},
        )
        return FetchResponse.from_payload(response)

    async def apply_request_context(self, page, request: CurlRequest, extract_domain) -> None:
        if request.headers:
            headers_to_set = {k: v for k, v in request.headers.items() if k.lower() != "host"}
            if headers_to_set:
                await page.set_extra_http_headers(headers_to_set)

        if request.cookies:
            cookies = [
                {
                    "name": name,
                    "value": value,
                    "domain": extract_domain(request.url),
                    "path": "/",
                }
                for name, value in request.cookies.items()
            ]
            await page.context.add_cookies(cookies)

    async def _simulate_human_warmup(
        self,
        page,
        request: CurlRequest,
        *,
        timeout_ms: int,
        trusted_session: bool,
    ) -> None:
        base_url = self.extract_base_url(request.url)
        navigation_targets = [base_url]
        if trusted_session:
            navigation_targets.append(request.url)

        for index, navigate_url in enumerate(navigation_targets, start=1):
            try:
                await page.goto(navigate_url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception:
                continue
            await self._simulate_human_interaction(page, phase=index, timeout_ms=timeout_ms)

    async def _simulate_human_interaction(self, page, *, phase: int, timeout_ms: int) -> None:
        try:
            await page.bring_to_front()
        except Exception:
            pass

        try:
            await page.mouse.move(240 + 25 * phase, 180 + 18 * phase, steps=12)
            await asyncio.sleep(0.2 + phase * 0.05)
            await page.mouse.wheel(0, 180 + phase * 40)
            await asyncio.sleep(0.25 + phase * 0.05)
            await page.mouse.move(520 + 15 * phase, 420 + 20 * phase, steps=10)
        except Exception:
            pass

        try:
            await page.evaluate(
                """
                () => {
                    window.focus();
                    document.dispatchEvent(new Event('mousemove', { bubbles: true }));
                    document.dispatchEvent(new Event('scroll', { bubbles: true }));
                }
                """
            )
        except Exception:
            pass

        try:
            await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 2_000))
        except Exception:
            pass

    def build_fetch_options(self, request: CurlRequest) -> FetchOptions:
        fetch_options: FetchOptions = {
            "method": request.method,
            "headers": request.headers or {},
            "redirect": "follow" if request.follow_redirects else "manual",
        }
        if request.data:
            fetch_options["body"] = request.data
            if request.method == "POST":
                self._ensure_post_content_type(fetch_options)
        return fetch_options

    def _ensure_post_content_type(self, fetch_options: FetchOptions) -> None:
        headers = fetch_options["headers"]
        assert isinstance(headers, dict)
        if any(header.lower() == "content-type" for header in headers):
            return
        try:
            json.loads(fetch_options["body"])
            headers["Content-Type"] = "application/json"
        except (TypeError, json.JSONDecodeError):
            headers["Content-Type"] = "application/x-www-form-urlencoded"

    def extract_base_url(self, url: str) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
