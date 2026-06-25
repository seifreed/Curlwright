"""Browser lifecycle adapter driving real Chrome through Patchright for stealth."""

from pathlib import Path
from typing import TYPE_CHECKING

from curlwright.infrastructure.logging import setup_logger
from curlwright.runtime import ensure_supported_python

ensure_supported_python()

if TYPE_CHECKING:
    from patchright.async_api import Browser, BrowserContext, Page, Playwright

type HttpCredentials = dict[str, str]
type ProxyConfig = dict[str, str]
type LaunchOptions = dict[str, str | bool | list[str] | ProxyConfig]
type ContextOptions = dict[str, object]

logger = setup_logger(__name__)


class BrowserManager:
    """Manages Playwright browser instances and contexts."""

    def __init__(
        self,
        headless: bool = False,
        user_agent: str | None = None,
        no_gui: bool = False,
        proxy: str | None = None,
        verify_ssl: bool = True,
        http_credentials: HttpCredentials | None = None,
        profile_dir: str | None = None,
        playwright_factory=None,
    ):
        self.headless = headless
        self.no_gui = no_gui
        self.proxy = proxy
        self.verify_ssl = verify_ssl
        self.http_credentials = http_credentials
        # None means "let real Chrome send its own native user agent" so the UA
        # stays consistent with the browser's real client hints.
        self.user_agent = user_agent
        self.profile_dir = (
            Path(profile_dir) if profile_dir else Path.home() / ".curlwright" / "browser-profile"
        )
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.playwright: "Playwright | None" = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self._persistent_context = True
        self._playwright_factory = playwright_factory

    async def initialize(self) -> None:
        try:
            if self._playwright_factory is None:
                from patchright.async_api import async_playwright

                factory = async_playwright
            else:
                factory = self._playwright_factory

            self.playwright = await factory().start()
            launch_options = self._build_launch_options()
            context_options = self._build_context_options()
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                **launch_options,
                **context_options,
            )
            self.browser = self.context.browser
            logger.info("Browser initialized successfully")
        except Exception as error:
            logger.error("Failed to initialize browser: %s", error)
            raise

    def _build_launch_options(self) -> LaunchOptions:
        # Keep the argument set minimal and benign: real Chrome with few flags
        # looks far more genuine than one carrying automation-flagging switches
        # (Patchright already neutralises AutomationControlled at the protocol
        # level, so we no longer pass it ourselves).
        browser_args = [
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--window-size=1920,1080",
        ]
        # channel="chrome" drives the real Google Chrome binary, and modern
        # Playwright/Patchright run it in Chrome's new headless mode (far closer
        # to headful than legacy headless) when headless is requested.
        launch_options: LaunchOptions = {
            "channel": "chrome",
            "headless": self.headless,
            "args": browser_args,
        }
        if self.proxy:
            launch_options["proxy"] = {"server": self.proxy}
        return launch_options

    def _build_context_options(self) -> ContextOptions:
        # Let real Chrome supply its own user agent, client hints and Sec-*/
        # Accept headers so everything is internally consistent; overriding them
        # (especially with a Windows fingerprint on a non-Windows host) is itself
        # a detection signal. Only set a UA when the caller explicitly asked.
        options: ContextOptions = {
            "viewport": {"width": 1920, "height": 1080},
            "screen": {"width": 1920, "height": 1080},
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "color_scheme": "light",
            "reduced_motion": "no-preference",
            "ignore_https_errors": not self.verify_ssl,
            "java_script_enabled": True,
            "http_credentials": self.http_credentials,
        }
        if self.user_agent:
            options["user_agent"] = self.user_agent
        return options

    async def create_page(self):
        if not self.context:
            await self.initialize()
        if self.context.pages:
            first_page = self.context.pages[0]
            if not first_page.is_closed() and first_page.url == "about:blank":
                page = first_page
            else:
                page = await self.context.new_page()
        else:
            page = await self.context.new_page()
        self.page = page
        if page.url == "about:blank":
            try:
                await page.goto("about:blank", wait_until="domcontentloaded")
            except Exception:
                logger.debug("about:blank navigation failed", exc_info=True)
        await page.evaluate("""
            Object.defineProperty(document, 'hidden', {
                get: () => false,
            });
            Object.defineProperty(document, 'visibilityState', {
                get: () => 'visible',
            });
            """)
        return page

    async def close(self) -> None:
        try:
            if self.page:
                if not self.page.is_closed():
                    await self.page.close()
                self.page = None
            if self.context:
                await self.context.close()
                self.context = None
            if self.browser and not self._persistent_context:
                await self.browser.close()
            self.browser = None
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None
            logger.info("Browser closed successfully")
        except Exception as error:
            logger.error("Error closing browser: %s", error)
