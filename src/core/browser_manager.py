"""
Browser manager module for handling Playwright browser instances
"""

import asyncio
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class BrowserManager:
    """Manages Playwright browser instances and contexts"""
    
    def __init__(self, headless: bool = False, user_agent: Optional[str] = None):
        """
        Initialize browser manager
        
        Args:
            headless: Run browser in headless mode
            user_agent: Custom user agent string
        """
        self.headless = headless
        self.user_agent = user_agent or self._get_default_user_agent()
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
    
    def _get_default_user_agent(self) -> str:
        """Get default user agent for Chrome"""
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    async def initialize(self) -> None:
        """Initialize browser and context"""
        try:
            self.playwright = await async_playwright().start()
            
            # Launch browser with anti-detection settings
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-web-security',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--start-maximized'
                ]
            )
            
            # Create context with anti-detection settings
            self.context = await self.browser.new_context(
                user_agent=self.user_agent,
                viewport={'width': 1920, 'height': 1080},
                ignore_https_errors=True,
                java_script_enabled=True,
                bypass_csp=True,
                extra_http_headers={
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache'
                }
            )
            
            # Add anti-detection scripts
            await self.context.add_init_script("""
                // Override navigator.webdriver
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false,
                });
                
                // Override chrome detection
                window.chrome = {
                    runtime: {},
                };
                
                // Override permissions
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
                
                // Override plugins
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });
                
                // Override languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en'],
                });
            """)
            
            logger.info("Browser initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize browser: {e}")
            raise
    
    async def create_page(self) -> Page:
        """Create a new page with anti-detection measures"""
        if not self.context:
            await self.initialize()
        
        page = await self.context.new_page()
        
        # Additional page-level anti-detection
        await page.evaluate("""
            // Additional anti-detection measures
            Object.defineProperty(document, 'hidden', {
                get: () => false,
            });
            
            Object.defineProperty(document, 'visibilityState', {
                get: () => 'visible',
            });
        """)
        
        return page
    
    async def close(self) -> None:
        """Close browser and cleanup resources"""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            
            logger.info("Browser closed successfully")
            
        except Exception as e:
            logger.error(f"Error closing browser: {e}")
    
    async def wait_for_cloudflare(self, page: Page, timeout: int = 30) -> bool:
        """
        Wait for Cloudflare challenge to complete
        
        Args:
            page: Page instance
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if challenge was bypassed, False otherwise
        """
        try:
            # Common Cloudflare challenge selectors
            cf_selectors = [
                'div.cf-browser-verification',
                'div#cf-content',
                'div.cf-error-details',
                'div#challenge-running',
                'div#challenge-stage',
                'div#trk_jschal_js',
                'iframe[src*="challenges.cloudflare.com"]',
                'form#challenge-form'
            ]
            
            # Check if Cloudflare challenge is present
            for selector in cf_selectors:
                if await page.locator(selector).count() > 0:
                    logger.info(f"Cloudflare challenge detected: {selector}")
                    
                    # Wait for challenge to complete
                    start_time = asyncio.get_event_loop().time()
                    while asyncio.get_event_loop().time() - start_time < timeout:
                        # Check if challenge is still present
                        still_present = False
                        for check_selector in cf_selectors:
                            if await page.locator(check_selector).count() > 0:
                                still_present = True
                                break
                        
                        if not still_present:
                            logger.info("Cloudflare challenge completed")
                            return True
                        
                        await asyncio.sleep(1)
                    
                    logger.warning(f"Cloudflare challenge timeout after {timeout} seconds")
                    return False
            
            # No Cloudflare challenge detected
            return True
            
        except Exception as e:
            logger.error(f"Error waiting for Cloudflare: {e}")
            return False
    
    async def handle_turnstile(self, page: Page, timeout: int = 30) -> bool:
        """
        Handle Cloudflare Turnstile challenges
        
        Args:
            page: Page instance
            timeout: Maximum time to wait
            
        Returns:
            True if Turnstile was handled, False otherwise
        """
        try:
            # Check for Turnstile iframe
            turnstile_selector = 'iframe[src*="challenges.cloudflare.com/turnstile"]'
            
            if await page.locator(turnstile_selector).count() > 0:
                logger.info("Turnstile challenge detected")
                
                # Wait for automatic solving (Playwright usually handles this)
                await page.wait_for_load_state('networkidle', timeout=timeout * 1000)
                
                # Check if Turnstile is gone
                if await page.locator(turnstile_selector).count() == 0:
                    logger.info("Turnstile challenge completed")
                    return True
                else:
                    logger.warning("Turnstile challenge still present")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling Turnstile: {e}")
            return False