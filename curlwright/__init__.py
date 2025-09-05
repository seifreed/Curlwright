"""
CurlWright - Cloudflare Bypass Tool using Playwright

A powerful tool that leverages Playwright to execute curl commands
with full browser capabilities, allowing you to access protected websites seamlessly.
"""

__version__ = "1.0.0"
__author__ = "Marc Rivero"
__email__ = "mriverolopez@gmail.com"
__license__ = "MIT"

# Import main components for easy access
from src.core.request_executor import RequestExecutor
from src.core.browser_manager import BrowserManager
from src.parsers.curl_parser import CurlParser, CurlRequest
from src.utils.cookie_manager import CookieManager
from src.utils.logger import setup_logger
from src.cli import CLI

__all__ = [
    'RequestExecutor',
    'BrowserManager',
    'CurlParser',
    'CurlRequest',
    'CookieManager',
    'setup_logger',
    'CLI',
]

def get_version():
    """Return the version of CurlWright"""
    return __version__