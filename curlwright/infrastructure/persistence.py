"""Persistence adapters for cookies and domain state."""

from __future__ import annotations

import json
import pickle
import time
from dataclasses import asdict
from pathlib import Path

from curlwright.domain import DomainBypassState
from curlwright.infrastructure.logging import setup_logger
from curlwright.runtime import ensure_supported_python

ensure_supported_python()

type CookieRecord = dict[str, object]
type CookieJar = list[CookieRecord]
type CookieNames = list[str]

logger = setup_logger(__name__)


class CookieManager:
    """Manages browser cookies for session persistence."""

    def __init__(self, cookie_file: str | None = None):
        self.cookie_file = Path(cookie_file) if cookie_file else Path.home() / ".curlwright" / "cookies.pkl"
        self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
        self.cookies: CookieJar = []

    async def save_cookies(self, context) -> None:
        try:
            self.cookies = await context.cookies()
            with open(self.cookie_file, "wb") as file_handle:
                pickle.dump(self.cookies, file_handle)
            logger.info("Saved %s cookies to %s", len(self.cookies), self.cookie_file)
        except Exception as error:
            logger.error("Failed to save cookies: %s", error)

    async def load_cookies(self, context) -> bool:
        try:
            if not self.cookie_file.exists():
                logger.info("No cookie file found")
                return False
            with open(self.cookie_file, "rb") as file_handle:
                self.cookies = pickle.load(file_handle)
            if self.cookies:
                await context.add_cookies(self.cookies)
                logger.info("Loaded %s cookies", len(self.cookies))
                return True
            return False
        except Exception as error:
            logger.error("Failed to load cookies: %s", error)
            return False

    def has_cookies_for_domain(self, domain: str) -> bool:
        return any(self.get_cookies_for_domain(domain))

    def clear_cookies(self) -> None:
        try:
            self.cookies = []
            if self.cookie_file.exists():
                self.cookie_file.unlink()
            logger.info("Cookies cleared")
        except Exception as error:
            logger.error("Failed to clear cookies: %s", error)

    def export_cookies_json(self, output_file: str) -> None:
        try:
            with open(output_file, "w") as file_handle:
                json.dump(self.cookies, file_handle, indent=2)
            logger.info("Exported cookies to %s", output_file)
        except Exception as error:
            logger.error("Failed to export cookies: %s", error)

    def import_cookies_json(self, input_file: str) -> bool:
        try:
            with open(input_file, "r") as file_handle:
                self.cookies = json.load(file_handle)
            with open(self.cookie_file, "wb") as file_handle:
                pickle.dump(self.cookies, file_handle)
            logger.info("Imported %s cookies from %s", len(self.cookies), input_file)
            return True
        except Exception as error:
            logger.error("Failed to import cookies: %s", error)
            return False

    def get_cookies_for_domain(self, domain: str) -> CookieJar:
        domain_cookies = []
        for cookie in self.cookies:
            cookie_domain = cookie.get("domain", "")
            if domain in cookie_domain or cookie_domain in domain:
                domain_cookies.append(cookie)
        return domain_cookies


class DomainStateStore:
    """File-backed store for per-domain bypass state."""

    def __init__(self, state_file: str | None = None):
        self.state_file = (
            Path(state_file)
            if state_file
            else Path.home() / ".curlwright" / "bypass-state.json"
        )
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state: dict[str, DomainBypassState] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self.state_file.exists():
            raw_state = json.loads(self.state_file.read_text())
            self._state = {key: DomainBypassState(**value) for key, value in raw_state.items()}
        self._loaded = True

    def _persist(self) -> None:
        serialized_state = {key: asdict(value) for key, value in self._state.items()}
        self.state_file.write_text(json.dumps(serialized_state, indent=2, sort_keys=True))

    def get(self, domain_key: str) -> DomainBypassState | None:
        self._ensure_loaded()
        return self._state.get(domain_key)

    def is_trusted(self, domain_key: str, max_age_seconds: int = 3600) -> bool:
        record = self.get(domain_key)
        if record is None:
            return False
        return record.is_trusted(max_age_seconds)

    def mark_success(
        self,
        *,
        domain_key: str,
        domain: str,
        user_agent: str,
        proxy: str | None,
        profile_dir: str | None,
        final_url: str,
        cookie_names: CookieNames,
        artifact_dir: str | None,
    ) -> None:
        self._ensure_loaded()
        record = self._state.get(domain_key) or DomainBypassState(
            domain_key=domain_key,
            domain=domain,
            user_agent=user_agent,
            proxy=proxy,
            profile_dir=profile_dir,
        )
        record.domain = domain
        record.user_agent = user_agent
        record.proxy = proxy
        record.profile_dir = profile_dir
        record.verified_at = time.time()
        record.last_url = final_url
        record.last_status = "verified"
        record.success_count += 1
        record.cookie_names = sorted(set(cookie_names))
        record.last_artifact_dir = artifact_dir
        self._state[domain_key] = record
        self._persist()

    def mark_failure(
        self,
        *,
        domain_key: str,
        domain: str,
        user_agent: str,
        proxy: str | None,
        profile_dir: str | None,
        final_url: str | None,
        artifact_dir: str | None,
    ) -> None:
        self._ensure_loaded()
        record = self._state.get(domain_key) or DomainBypassState(
            domain_key=domain_key,
            domain=domain,
            user_agent=user_agent,
            proxy=proxy,
            profile_dir=profile_dir,
        )
        record.domain = domain
        record.user_agent = user_agent
        record.proxy = proxy
        record.profile_dir = profile_dir
        record.last_status = "failed"
        record.failure_count += 1
        record.last_url = final_url
        record.last_artifact_dir = artifact_dir
        self._state[domain_key] = record
        self._persist()
