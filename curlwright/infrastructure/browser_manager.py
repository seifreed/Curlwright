"""Browser lifecycle adapter for Playwright with delegated stealth and challenge helpers."""

from pathlib import Path
from typing import TYPE_CHECKING

from curlwright.infrastructure.browser_challenge_monitor import handle_turnstile, wait_for_cloudflare
from curlwright.infrastructure.browser_stealth import build_browser_init_script, chrome_major_version
from curlwright.infrastructure.logging import setup_logger
from curlwright.runtime import ensure_supported_python

ensure_supported_python()

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page

type HttpCredentials = dict[str, str]
type ProxyConfig = dict[str, str]
type LaunchOptions = dict[str, bool | list[str] | ProxyConfig]
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
        self.user_agent = user_agent or self._get_default_user_agent()
        self.profile_dir = Path(profile_dir) if profile_dir else Path.home() / ".curlwright" / "browser-profile"
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self._persistent_context = True
        self._playwright_factory = playwright_factory

    def _get_default_user_agent(self) -> str:
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"

    def _chrome_major_version(self) -> str:
        return chrome_major_version(self.user_agent)

    async def initialize(self) -> None:
        try:
            if self._playwright_factory is None:
                from playwright.async_api import async_playwright

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
            await self.context.add_init_script(self._build_init_script())
            logger.info("Browser initialized successfully")
        except Exception as error:
            logger.error("Failed to initialize browser: %s", error)
            raise

    def _build_init_script(self) -> str:
        return build_browser_init_script(self.user_agent)

    def _build_launch_options(self) -> LaunchOptions:
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--no-first-run",
            "--password-store=basic",
            "--use-mock-keychain",
            "--disable-infobars",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-site-isolation-trials",
            "--disable-features=BlockInsecurePrivateNetworkRequests",
            "--window-size=1920,1080",
        ]

        if self.no_gui:
            browser_args.extend(
                [
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--no-zygote",
                    "--mute-audio",
                    "--disable-background-networking",
                    "--disable-background-timer-throttling",
                    "--disable-breakpad",
                    "--metrics-recording-only",
                    "--force-color-profile=srgb",
                    "--hide-scrollbars",
                ]
            )
        else:
            browser_args.append("--start-maximized")

        launch_options: LaunchOptions = {"headless": self.headless, "args": browser_args}
        if self.proxy:
            launch_options["proxy"] = {"server": self.proxy}
        return launch_options

    def _build_context_options(self) -> ContextOptions:
        return {
            "user_agent": self.user_agent,
            "viewport": {"width": 1920, "height": 1080},
            "screen": {"width": 1920, "height": 1080},
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "color_scheme": "light",
            "reduced_motion": "no-preference",
            "ignore_https_errors": not self.verify_ssl,
            "java_script_enabled": True,
            "http_credentials": self.http_credentials,
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Sec-Ch-Ua": '"Chromium";v="134", "Google Chrome";v="134", "Not-A.Brand";v="8"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
        }

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
                pass
        await page.evaluate(
            """
            Object.defineProperty(document, 'hidden', {
                get: () => false,
            });
            Object.defineProperty(document, 'visibilityState', {
                get: () => 'visible',
            });
            """
        )
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

    async def wait_for_cloudflare(self, page, timeout: int = 30) -> bool:
        result = await wait_for_cloudflare(page, timeout=timeout)
        if not result:
            logger.warning("Cloudflare challenge timeout after %s seconds", timeout)
        return result

    async def handle_turnstile(self, page, timeout: int = 30) -> bool:
        result = await handle_turnstile(page, timeout=timeout)
        if not result:
            logger.warning("Turnstile timeout after %s seconds", timeout)
        return result
