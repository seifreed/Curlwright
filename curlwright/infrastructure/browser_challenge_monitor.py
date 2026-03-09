"""Challenge-monitoring helpers isolated from browser bootstrapping concerns."""

from __future__ import annotations

import asyncio

from curlwright.runtime import ensure_supported_python

ensure_supported_python()


async def wait_for_cloudflare(page, timeout: int = 30) -> bool:
    """Wait for a Cloudflare challenge to complete."""
    try:
        cf_selectors = [
            "div.cf-browser-verification",
            "div#cf-content",
            "div.cf-error-details",
            "div#challenge-running",
            "div#challenge-stage",
            "div#trk_jschal_js",
            "iframe[src*='challenges.cloudflare.com']",
            "form#challenge-form",
        ]

        for selector in cf_selectors:
            if await page.locator(selector).count() > 0:
                start_time = asyncio.get_event_loop().time()
                while asyncio.get_event_loop().time() - start_time < timeout:
                    still_present = False
                    for check_selector in cf_selectors:
                        if await page.locator(check_selector).count() > 0:
                            still_present = True
                            break

                    if not still_present:
                        return True

                    await asyncio.sleep(1)

                return False

        return True
    except Exception:
        return False


async def handle_turnstile(page, timeout: int = 30) -> bool:
    """Wait for a Turnstile widget to disappear or resolve."""
    try:
        selectors = [
            "iframe[src*='turnstile']",
            "iframe[src*='challenges.cloudflare.com']",
            "div.cf-turnstile",
            "input[name='cf-turnstile-response']",
        ]
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            still_present = False
            for selector in selectors:
                if await page.locator(selector).count() > 0:
                    still_present = True
                    break

            if not still_present:
                return True

            await asyncio.sleep(0.1)

        return False
    except Exception:
        return False
