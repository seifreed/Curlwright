"""
CurlWright - Cloudflare Bypass Tool using Playwright

A powerful tool that leverages Playwright to execute curl commands
with full browser capabilities, allowing you to access protected websites seamlessly.
"""

__version__ = "1.0.0"
__author__ = "Marc Rivero"
__email__ = "mriverolopez@gmail.com"
__license__ = "MIT"

# Don't import modules during package building
# Users will import directly from src modules when using the library

def get_version():
    """Return the version of CurlWright"""
    return __version__