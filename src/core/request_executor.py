"""
Request executor module for executing parsed curl requests with Playwright
"""

import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from src.runtime_compat import ensure_supported_python
from src.core.bypass_manager import BypassFailure, BypassManager
from src.core.browser_manager import BrowserManager
from src.parsers.curl_parser import CurlParser, CurlRequest
from src.utils.cookie_manager import CookieManager
from src.utils.domain_state import DomainStateStore
from src.utils.logger import setup_logger

ensure_supported_python()

type ResponsePayload = dict[str, object]
type FetchHeaders = dict[str, str]
type FetchOptions = dict[str, str | FetchHeaders]
type HttpCredentials = dict[str, str]
type BrowserSignature = tuple[str | None, bool, tuple[str | None, str | None], str]

logger = setup_logger(__name__)


class RequestExecutor:
    """Executes curl requests using Playwright browser"""
    
    def __init__(
        self,
        headless: bool = False,
        timeout: int = 30,
        user_agent: str | None = None,
        no_gui: bool = False,
        cookie_file: str | None = None,
        persist_cookies: bool = True,
        bypass_state_file: str | None = None,
        artifact_dir: str | None = None,
        bypass_attempts: int = 3,
    ):
        """
        Initialize request executor
        
        Args:
            headless: Run browser in headless mode
            timeout: Default timeout for requests
            user_agent: Custom user agent
            no_gui: Run without X11/display requirement
            cookie_file: Optional cookie persistence path
            persist_cookies: Whether to load/save cookies automatically
            bypass_state_file: Optional bypass state file
            artifact_dir: Optional diagnostics directory for failed bypasses
            bypass_attempts: Challenge-specific attempt count per request
        """
        self.browser_manager: BrowserManager | None = None
        self.default_timeout = timeout
        self.headless = headless
        self.user_agent = user_agent
        self.no_gui = no_gui
        self.parser = CurlParser()
        self.initialized = False
        self.persist_cookies = persist_cookies
        self.cookie_manager = CookieManager(cookie_file) if persist_cookies else None
        self._browser_signature: BrowserSignature | None = None
        self._retry_user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.91 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.91 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.91 Safari/537.36",
        ]
        self._effective_user_agent = user_agent or self._retry_user_agents[0]
        self.bypass_manager = BypassManager(artifact_root=artifact_dir, max_attempts=bypass_attempts)
        self.domain_state_store = DomainStateStore(bypass_state_file)
    
    async def _ensure_initialized(self, request: CurlRequest, *, user_agent: str) -> None:
        """Ensure browser is initialized with request-specific runtime settings."""
        browser_signature = self._get_browser_signature(request, user_agent)
        if self.initialized and browser_signature == self._browser_signature:
            return

        if self.browser_manager:
            await self.browser_manager.close()

        self.browser_manager = BrowserManager(
            headless=self.headless,
            user_agent=user_agent,
            no_gui=self.no_gui,
            proxy=request.proxy,
            verify_ssl=request.verify_ssl,
            http_credentials=self._get_http_credentials(request),
        )
        await self.browser_manager.initialize()
        self.initialized = True
        self._browser_signature = browser_signature
        self._effective_user_agent = user_agent
    
    async def execute(self, curl_command: str, max_retries: int = 3, delay: int = 5) -> ResponsePayload:
        """
        Execute a curl command using Playwright
        
        Args:
            curl_command: The curl command to execute
            max_retries: Maximum number of retries
            delay: Delay between retries in seconds
            
        Returns:
            Dictionary with response data
        """
        # Parse curl command
        try:
            request = self.parser.parse(curl_command)
            logger.info(f"Parsed request: {request.method} {request.url}")
        except Exception as e:
            logger.error(f"Failed to parse curl command: {e}")
            raise

        # Execute request with retries
        for attempt in range(max_retries):
            effective_user_agent = self._get_retry_user_agent(attempt)
            try:
                await self._ensure_initialized(request, user_agent=effective_user_agent)
                result = await self._execute_request(request)
                if result:
                    return result
            except BypassFailure as e:
                logger.warning(f"Bypass attempt {attempt + 1} failed: {e}")
                await self._reset_runtime_state()
                if attempt < max_retries - 1:
                    logger.info(f"Rebuilding browser context in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error("All bypass retry attempts failed")
                    raise
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                await self._reset_runtime_state()
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error("All retry attempts failed")
                    raise
        
        raise Exception("Failed to execute request after all retries")
    
    async def _execute_request(self, request: CurlRequest) -> ResponsePayload:
        """
        Execute a single request
        
        Args:
            request: CurlRequest object
            
        Returns:
            Response dictionary
        """
        if not self.browser_manager:
            raise RuntimeError("Browser manager is not initialized")

        page = await self.browser_manager.create_page()
        effective_timeout_ms = self._get_effective_timeout(request) * 1000
        console_events = self.bypass_manager.attach_console_capture(page)
        domain = self._extract_domain(request.url)
        domain_key = self._get_domain_session_key(request)
        artifact_dir: str | None = None
        
        try:
            # Set custom headers (excluding Host header which is handled by the URL)
            if request.headers:
                headers_to_set = {k: v for k, v in request.headers.items() if k.lower() != 'host'}
                if headers_to_set:
                    await page.set_extra_http_headers(headers_to_set)
            
            # Set cookies if provided
            if request.cookies:
                cookies = [
                    {
                        'name': name,
                        'value': value,
                        'domain': self._extract_domain(request.url),
                        'path': '/'
                    }
                    for name, value in request.cookies.items()
                ]
                await page.context.add_cookies(cookies)
            
            await self._warm_up_page(
                page,
                request,
                effective_timeout_ms,
                console_events=console_events,
            )
            response_data = await self._perform_fetch_request(page, request, effective_timeout_ms)
            response_assessment = self.bypass_manager.assess_response_payload(response_data)
            if not response_assessment.is_clear:
                artifact_path = await self.bypass_manager.collect_failure_artifacts(
                    page=page,
                    assessment=response_assessment,
                    console_events=console_events,
                    label="blocked-response",
                )
                artifact_dir = str(artifact_path)
                raise BypassFailure(
                    "Bypass succeeded superficially but final response still looks blocked",
                    assessment=response_assessment,
                    artifact_dir=artifact_dir,
                )

            context_cookies = await page.context.cookies()
            self.domain_state_store.mark_success(
                domain_key=domain_key,
                domain=domain,
                user_agent=self._effective_user_agent,
                proxy=request.proxy,
                final_url=str(response_data.get("url", request.url)),
                cookie_names=[cookie.get("name", "") for cookie in context_cookies if cookie.get("name")],
                artifact_dir=artifact_dir,
            )
            
            logger.info(f"Request completed: Status {response_data.get('status', 'unknown')}")
            return response_data
            
        except BypassFailure as e:
            artifact_dir = e.artifact_dir
            self.domain_state_store.mark_failure(
                domain_key=domain_key,
                domain=domain,
                user_agent=self._effective_user_agent,
                proxy=request.proxy,
                final_url=e.assessment.final_url,
                artifact_dir=artifact_dir,
            )
            raise
        except Exception as e:
            logger.error(f"Error executing request: {e}")
            raise
        finally:
            if self.cookie_manager:
                await self.cookie_manager.save_cookies(page.context)
            await page.close()
    
    async def _warm_up_page(
        self,
        page,
        request: CurlRequest,
        timeout_ms: int,
        *,
        console_events: list[dict[str, str]],
    ) -> None:
        """Warm the browser context through the actual target and resolve challenges."""
        if self.cookie_manager:
            await self.cookie_manager.load_cookies(page.context)
        trusted_session = self._has_trusted_session(request)
        await self.bypass_manager.perform_bypass(
            page=page,
            target_url=request.url,
            timeout_ms=timeout_ms,
            trusted_session=trusted_session,
            console_events=console_events,
        )

    async def _perform_fetch_request(self, page, request: CurlRequest, timeout_ms: int) -> ResponsePayload:
        """Execute the final HTTP request from inside the warmed browser context."""
        fetch_options = self._build_fetch_options(request)
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
                } catch (error) {
                    if (error && error.name === 'AbortError') {
                        throw new Error(`Request timed out after ${timeoutMs}ms`);
                    }
                    throw error;
                } finally {
                    clearTimeout(timer);
                }
            }
            """,
            {'url': request.url, 'options': fetch_options, 'timeoutMs': timeout_ms},
        )
        return response

    def _build_fetch_options(self, request: CurlRequest) -> FetchOptions:
        """Translate CurlRequest semantics into browser fetch options."""
        fetch_options: FetchOptions = {
            'method': request.method,
            'headers': request.headers or {},
            'redirect': 'follow' if request.follow_redirects else 'manual',
        }

        if request.data:
            fetch_options['body'] = request.data
            if request.method == 'POST':
                self._ensure_post_content_type(fetch_options)

        return fetch_options

    def _ensure_post_content_type(self, fetch_options: FetchOptions) -> None:
        """Apply curl-like content-type defaults for POST bodies."""
        headers = fetch_options['headers']
        assert isinstance(headers, dict)
        if any(header.lower() == 'content-type' for header in headers):
            return

        try:
            json.loads(fetch_options['body'])
            headers['Content-Type'] = 'application/json'
        except (TypeError, json.JSONDecodeError):
            headers['Content-Type'] = 'application/x-www-form-urlencoded'

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL"""
        parsed = urlparse(url)
        return parsed.hostname or parsed.netloc

    def _extract_base_url(self, url: str) -> str:
        """Extract scheme and host for browser warm-up navigation."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _get_effective_timeout(self, request: CurlRequest) -> int:
        """Use curl-specific timeout when present."""
        return request.timeout or self.default_timeout

    def _get_http_credentials(self, request: CurlRequest) -> HttpCredentials | None:
        """Convert curl basic auth into Playwright context credentials."""
        if not request.auth:
            return None
        username, password = request.auth
        return {'username': username, 'password': password}

    def _get_browser_signature(self, request: CurlRequest, user_agent: str) -> BrowserSignature:
        """Track runtime-affecting browser settings so incompatible requests reinitialize cleanly."""
        credentials = request.auth or (None, None)
        return (request.proxy, request.verify_ssl, credentials, user_agent)

    def _get_domain_session_key(self, request: CurlRequest) -> str:
        """Build the trust-context key for bypass state reuse."""
        return "|".join(
            [
                self._extract_domain(request.url),
                request.proxy or "direct",
                self._effective_user_agent,
            ]
        )

    def _has_trusted_session(self, request: CurlRequest) -> bool:
        """Return whether the current domain/proxy/UA combination looks reusable."""
        if not self.domain_state_store.is_trusted(self._get_domain_session_key(request)):
            return False
        if self.cookie_manager is None:
            return False
        return self.cookie_manager.has_cookies_for_domain(self._extract_domain(request.url))

    def _get_retry_user_agent(self, attempt: int) -> str:
        """Rotate a realistic user agent when the caller did not pin one."""
        if self.user_agent:
            return self.user_agent
        return self._retry_user_agents[attempt % len(self._retry_user_agents)]

    async def _reset_runtime_state(self) -> None:
        """Drop the current browser manager so the next retry starts fresh."""
        if self.browser_manager:
            await self.browser_manager.close()
        self.browser_manager = None
        self.initialized = False
        self._browser_signature = None
    
    async def close(self):
        """Close browser and cleanup"""
        if self.initialized and self.browser_manager:
            await self.browser_manager.close()
            self.initialized = False
            self.browser_manager = None
            self._browser_signature = None
