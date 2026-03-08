"""Public utility exports for the curlwright package."""

from src.runtime_compat import ensure_supported_python
from src.utils.cookie_manager import CookieManager

ensure_supported_python()

__all__ = ["CookieManager"]
