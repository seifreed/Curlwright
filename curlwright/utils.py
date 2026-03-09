"""Public utility exports for the curlwright package."""

from curlwright.runtime import ensure_supported_python
from curlwright.infrastructure.persistence import CookieManager

ensure_supported_python()

__all__ = ["CookieManager"]
