"""Concrete factories used at the composition root to instantiate adapters."""

from curlwright.domain import BrowserSessionConfig
from curlwright.infrastructure.browser_manager import BrowserManager
from curlwright.runtime import ensure_supported_python

ensure_supported_python()


class DefaultBrowserManagerFactory:
    """Default adapter factory for browser sessions.

    Picks the engine: Patchright (default) or nodriver, the latter for hardened
    Cloudflare managed challenges that defeat Patchright's CDP fingerprint.
    """

    def create(self, config: BrowserSessionConfig):
        if config.engine == "nodriver":
            from curlwright.infrastructure.nodriver_manager import NodriverBrowserManager

            return NodriverBrowserManager(
                headless=config.headless,
                user_agent=config.user_agent,
                no_gui=config.no_gui,
                proxy=config.proxy,
                verify_ssl=config.verify_ssl,
                http_credentials=config.http_credentials,
                profile_dir=config.profile_dir,
            )
        return BrowserManager(
            headless=config.headless,
            user_agent=config.user_agent,
            no_gui=config.no_gui,
            proxy=config.proxy,
            verify_ssl=config.verify_ssl,
            http_credentials=config.http_credentials,
            profile_dir=config.profile_dir,
        )
