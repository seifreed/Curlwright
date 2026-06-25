"""Playwright-facing infrastructure exports."""

from curlwright.infrastructure.browser_manager import BrowserManager
from curlwright.infrastructure.factories import DefaultBrowserManagerFactory

__all__ = ["BrowserManager", "DefaultBrowserManagerFactory"]
