"""Page and response classification helpers for Cloudflare bypass flows."""

from __future__ import annotations

from dataclasses import dataclass

from curlwright.domain import BypassAssessment, FetchResponse
from curlwright.runtime import ensure_supported_python

ensure_supported_python()

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

TURNSTILE_SUCCESS_PATTERNS = [
    "verification successful",
    "waiting for ",
    "security verification complete",
]

BLOCK_TEXT_PATTERNS = [
    "access denied",
    "attention required",
    "attention required! | cloudflare",
    "checking if the site connection is secure",
    "forbidden",
    "incompatible browser extension or network configuration",
    "blocked the security verification process",
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

TERMINAL_BLOCK_PATTERNS = [
    "incompatible browser extension or network configuration",
    "blocked the security verification process",
]


@dataclass(frozen=True)
class SignalStrategy:
    name: str
    selectors: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    statuses: tuple[int, ...] = ()
    require_empty_body_on_status: bool = False


def compact_text(raw_text: str, limit: int = 500) -> str:
    condensed = " ".join(raw_text.split())
    return condensed[:limit]


class BypassClassifier:
    """Encapsulates heuristics for Cloudflare page and payload classification."""

    PAGE_STRATEGIES = (
        SignalStrategy(
            name="challenge-selector",
            selectors=tuple(CHALLENGE_SELECTORS),
        ),
        SignalStrategy(
            name="challenge-text-pattern",
            patterns=tuple(CHALLENGE_TEXT_PATTERNS),
        ),
        SignalStrategy(
            name="block-text-pattern",
            patterns=tuple(BLOCK_TEXT_PATTERNS),
        ),
        SignalStrategy(
            name="terminal-block-pattern",
            patterns=tuple(TERMINAL_BLOCK_PATTERNS),
        ),
        SignalStrategy(
            name="block-status",
            statuses=(403, 429, 503),
        ),
        SignalStrategy(
            name="empty-body-on-block-status",
            statuses=(403, 429, 503),
            require_empty_body_on_status=True,
        ),
    )

    RESPONSE_STRATEGIES = (
        SignalStrategy(
            name="challenge-text-pattern",
            patterns=tuple(CHALLENGE_TEXT_PATTERNS),
        ),
        SignalStrategy(
            name="block-text-pattern",
            patterns=tuple(BLOCK_TEXT_PATTERNS),
        ),
        SignalStrategy(
            name="terminal-block-pattern",
            patterns=tuple(TERMINAL_BLOCK_PATTERNS),
        ),
        SignalStrategy(
            name="block-status",
            statuses=(403, 429, 503),
        ),
    )

    async def assess_page(self, page, response) -> BypassAssessment:
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

        for strategy in self.PAGE_STRATEGIES:
            indicators.extend(
                await self._apply_page_strategy(
                    strategy,
                    page=page,
                    lower_html=lower_html,
                    lower_title=lower_title,
                    lower_body=lower_body,
                    status_code=status_code,
                    body_text=body_text,
                )
            )
        if "cloudflare" in lower_title and "attention required" in lower_title:
            indicators.append("cloudflare-attention-title")
        if "/cdn-cgi/styles/" in lower_html and "cloudflare" in lower_html:
            indicators.append("cloudflare-interstitial-assets")

        return BypassAssessment(
            outcome=self._classify_outcome(indicators),
            final_url=page.url,
            title=title,
            status_code=status_code,
            indicators=sorted(set(indicators)),
            body_excerpt=compact_text(body_text or html),
        )

    def assess_response_payload(self, payload: FetchResponse | dict[str, object]) -> BypassAssessment:
        response = payload if isinstance(payload, FetchResponse) else FetchResponse.from_payload(payload)
        lower_body = response.body.lower()
        indicators: list[str] = []

        for strategy in self.RESPONSE_STRATEGIES:
            indicators.extend(
                self._apply_response_strategy(
                    strategy,
                    lower_body=lower_body,
                    status_code=response.status,
                )
            )
        if "attention required! | cloudflare" in lower_body:
            indicators.append("cloudflare-attention-title")
        if "/cdn-cgi/styles/" in lower_body and "cloudflare" in lower_body:
            indicators.append("cloudflare-interstitial-assets")
        if response.status in {200, 204} and not response.body.strip():
            indicators.append("empty-body")

        return BypassAssessment(
            outcome=self._classify_outcome(indicators),
            final_url=response.url or "",
            title="",
            status_code=response.status,
            indicators=indicators,
            body_excerpt=compact_text(response.body),
        )

    async def _selector_exists(self, page, selector: str) -> bool:
        try:
            return await page.locator(selector).count() > 0
        except Exception:
            return False

    async def _apply_page_strategy(
        self,
        strategy: SignalStrategy,
        *,
        page,
        lower_html: str,
        lower_title: str,
        lower_body: str,
        status_code: int | None,
        body_text: str,
    ) -> list[str]:
        indicators: list[str] = []
        for selector in strategy.selectors:
            if await self._selector_exists(page, selector):
                indicators.append(f"selector:{selector}")
        if strategy.patterns and any(
            pattern in lower_html or pattern in lower_title or pattern in lower_body
            for pattern in strategy.patterns
        ):
            indicators.append(strategy.name)
        if status_code in strategy.statuses:
            if strategy.require_empty_body_on_status:
                if not body_text.strip():
                    indicators.append(strategy.name)
            else:
                indicators.append(f"status:{status_code}")
        return indicators

    def _apply_response_strategy(
        self,
        strategy: SignalStrategy,
        *,
        lower_body: str,
        status_code: int,
    ) -> list[str]:
        indicators: list[str] = []
        if strategy.patterns and any(pattern in lower_body for pattern in strategy.patterns):
            indicators.append(strategy.name)
        if status_code in strategy.statuses:
            indicators.append(f"status:{status_code}")
        return indicators

    def _classify_outcome(self, indicators: list[str]) -> str:
        if "terminal-block-pattern" in indicators:
            return "blocked"
        if any(selector.endswith("turnstile-response']") or "turnstile" in selector for selector in indicators):
            return "turnstile"
        if any(
            item.startswith("selector:")
            or item in {
                "challenge-text-pattern",
                "cloudflare-attention-title",
                "cloudflare-interstitial-assets",
            }
            for item in indicators
        ):
            return "challenge"
        if "block-text-pattern" in indicators or any(item.startswith("status:") for item in indicators):
            return "blocked"
        return "clear"
