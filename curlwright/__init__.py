"""
CurlWright - Cloudflare Bypass Tool using Playwright

A powerful tool that leverages Playwright to execute curl commands
with full browser capabilities, allowing you to access protected websites seamlessly.
"""

from importlib import import_module
from curlwright.runtime import ensure_supported_python

ensure_supported_python()

__version__ = "2.0.0"
__author__ = "Marc Rivero"
__email__ = "mriverolopez@gmail.com"
__license__ = "MIT"

__all__ = [
    "RequestExecutor",
    "CurlParser",
    "CurlRequest",
    "CookieManager",
    "get_version",
]


_EXPORT_MAP = {
    "RequestExecutor": ("curlwright.executor", "RequestExecutor"),
    "CurlParser": ("curlwright.parsers", "CurlParser"),
    "CurlRequest": ("curlwright.parsers", "CurlRequest"),
    "CookieManager": ("curlwright.utils", "CookieManager"),
}


def __getattr__(name):
    """Load public exports lazily so package metadata stays lightweight."""
    if name not in _EXPORT_MAP:
        raise AttributeError(f"module 'curlwright' has no attribute {name!r}")

    module_name, attribute_name = _EXPORT_MAP[name]
    module = import_module(module_name)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def get_version():
    """Return the version of CurlWright"""
    return __version__
