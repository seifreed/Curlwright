"""Concrete factories used at the composition root to instantiate adapters."""

from curlwright.domain import BrowserSessionConfig
from curlwright.infrastructure.browser_manager import BrowserManager
from curlwright.runtime import ensure_supported_python

ensure_supported_python()


class DefaultBrowserManagerFactory:
    """Default adapter factory for browser sessions."""

    def create(self, config: BrowserSessionConfig) -> BrowserManager:
        return BrowserManager(
            headless=config.headless,
            user_agent=config.user_agent,
            no_gui=config.no_gui,
            proxy=config.proxy,
            verify_ssl=config.verify_ssl,
            http_credentials=config.http_credentials,
            profile_dir=config.profile_dir,
        )
