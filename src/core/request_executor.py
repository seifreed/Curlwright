"""
Request executor module for executing parsed curl requests with Playwright
"""

import asyncio
import json
from typing import Dict, Any, Optional
from src.core.browser_manager import BrowserManager
from src.parsers.curl_parser import CurlParser, CurlRequest
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class RequestExecutor:
    """Executes curl requests using Playwright browser"""
    
    def __init__(self, headless: bool = False, timeout: int = 30, user_agent: Optional[str] = None):
        """
        Initialize request executor
        
        Args:
            headless: Run browser in headless mode
            timeout: Default timeout for requests
            user_agent: Custom user agent
        """
        self.browser_manager = BrowserManager(headless=headless, user_agent=user_agent)
        self.default_timeout = timeout
        self.parser = CurlParser()
        self.initialized = False
    
    async def _ensure_initialized(self):
        """Ensure browser is initialized"""
        if not self.initialized:
            await self.browser_manager.initialize()
            self.initialized = True
    
    async def execute(self, curl_command: str, max_retries: int = 3, delay: int = 5) -> Dict[str, Any]:
        """
        Execute a curl command using Playwright
        
        Args:
            curl_command: The curl command to execute
            max_retries: Maximum number of retries
            delay: Delay between retries in seconds
            
        Returns:
            Dictionary with response data
        """
        await self._ensure_initialized()
        
        # Parse curl command
        try:
            request = self.parser.parse(curl_command)
            logger.info(f"Parsed request: {request.method} {request.url}")
        except Exception as e:
            logger.error(f"Failed to parse curl command: {e}")
            raise
        
        # Execute request with retries
        for attempt in range(max_retries):
            try:
                result = await self._execute_request(request)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error("All retry attempts failed")
                    raise
        
        raise Exception("Failed to execute request after all retries")
    
    async def _execute_request(self, request: CurlRequest) -> Dict[str, Any]:
        """
        Execute a single request
        
        Args:
            request: CurlRequest object
            
        Returns:
            Response dictionary
        """
        page = await self.browser_manager.create_page()
        
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
            
            # Handle authentication
            if request.auth:
                username, password = request.auth
                await page.context.set_http_credentials({
                    'username': username,
                    'password': password
                })
            
            # Prepare response interceptor
            response_data = {}
            
            async def handle_response(response):
                """Capture response data"""
                if response.url == request.url or response.url.startswith(request.url.split('?')[0]):
                    response_data['status'] = response.status
                    response_data['headers'] = await response.all_headers()
                    try:
                        response_data['body'] = await response.text()
                    except:
                        response_data['body'] = await response.body()
            
            # Register response handler
            page.on('response', handle_response)
            
            # Navigate to URL for GET/HEAD requests or prepare for POST
            if request.method in ['GET', 'HEAD']:
                response = await page.goto(
                    request.url,
                    wait_until='networkidle',
                    timeout=self.default_timeout * 1000
                )
                
                # Wait for Cloudflare if present
                cf_bypassed = await self.browser_manager.wait_for_cloudflare(page, self.default_timeout)
                if not cf_bypassed:
                    logger.warning("Failed to bypass Cloudflare challenge")
                
                # Handle Turnstile if present
                await self.browser_manager.handle_turnstile(page, self.default_timeout)
                
                # Get final page content
                if not response_data:
                    response_data = {
                        'status': response.status if response else 200,
                        'headers': await response.all_headers() if response else {},
                        'body': await page.content()
                    }
                
            elif request.method == 'POST':
                # For POST requests, we need to handle them differently
                response_data = await self._handle_post_request(page, request)
                
            else:
                # For other methods, use fetch API
                response_data = await self._handle_fetch_request(page, request)
            
            logger.info(f"Request completed: Status {response_data.get('status', 'unknown')}")
            return response_data
            
        except Exception as e:
            logger.error(f"Error executing request: {e}")
            raise
        finally:
            await page.close()
    
    async def _handle_post_request(self, page, request: CurlRequest) -> Dict[str, Any]:
        """Handle POST request with form data or JSON"""
        
        # First navigate to the domain to establish context
        base_url = '/'.join(request.url.split('/')[:3])
        await page.goto(base_url, wait_until='domcontentloaded')
        
        # Wait for any Cloudflare challenges
        await self.browser_manager.wait_for_cloudflare(page, self.default_timeout)
        await self.browser_manager.handle_turnstile(page, self.default_timeout)
        
        # Prepare fetch options
        fetch_options = {
            'method': 'POST',
            'headers': request.headers or {}
        }
        
        # Add body data
        if request.data:
            # Check if it's JSON
            try:
                json.loads(request.data)
                fetch_options['headers']['Content-Type'] = 'application/json'
                fetch_options['body'] = request.data
            except:
                # Treat as form data
                if 'Content-Type' not in fetch_options['headers']:
                    fetch_options['headers']['Content-Type'] = 'application/x-www-form-urlencoded'
                fetch_options['body'] = request.data
        
        # Execute fetch
        response = await page.evaluate("""
            async (url, options) => {
                const response = await fetch(url, options);
                const body = await response.text();
                const headers = {};
                response.headers.forEach((value, key) => {
                    headers[key] = value;
                });
                return {
                    status: response.status,
                    headers: headers,
                    body: body
                };
            }
        """, request.url, fetch_options)
        
        return response
    
    async def _handle_fetch_request(self, page, request: CurlRequest) -> Dict[str, Any]:
        """Handle requests using fetch API"""
        
        # Navigate to base URL first
        base_url = '/'.join(request.url.split('/')[:3])
        await page.goto(base_url, wait_until='domcontentloaded')
        
        # Wait for any challenges
        await self.browser_manager.wait_for_cloudflare(page, self.default_timeout)
        
        # Prepare fetch options
        fetch_options = {
            'method': request.method,
            'headers': request.headers or {},
            'redirect': 'follow' if request.follow_redirects else 'manual',
        }
        
        if request.data:
            fetch_options['body'] = request.data
        
        # Execute fetch
        response = await page.evaluate("""
            async (url, options) => {
                const response = await fetch(url, options);
                const body = await response.text();
                const headers = {};
                response.headers.forEach((value, key) => {
                    headers[key] = value;
                });
                return {
                    status: response.status,
                    headers: headers,
                    body: body
                };
            }
        """, request.url, fetch_options)
        
        return response
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc
    
    async def close(self):
        """Close browser and cleanup"""
        if self.initialized:
            await self.browser_manager.close()
            self.initialized = False