"""Persistence adapters for cookies and domain state."""

from __future__ import annotations

import json
import os
import tempfile
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


def _restrict_to_owner(path: Path) -> None:
    """Restrict a credential file to owner read/write (0600).

    The cookie jar and bypass state hold session/clearance cookies, which are
    bearer credentials; the default 0644 would expose them to other local
    users. chmod is best-effort (filesystems without POSIX modes are ignored).
    """
    try:
        path.chmod(0o600)
    except OSError as error:
        logger.debug("Could not restrict permissions on %s: %s", path, error)


def _atomic_write_private(path: Path, data: str) -> None:
    """Write a credential file atomically with owner-only permissions.

    The data is written to a temporary file in the same directory (created
    0600 by mkstemp) and then os.replace()d into place, so an interrupted or
    concurrent write can never leave a truncated/corrupt jar or state file and
    the contents are never world-readable, even briefly.
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
        os.replace(tmp_path, path)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise


def _domains_related(target: str, cookie_domain: str) -> bool:
    """Return True when target and a cookie's domain are the same host or one
    is a subdomain of the other, matching on dot boundaries.

    This avoids the naive substring check that wrongly related, e.g.,
    ``example.com`` to ``evil-example.com``.
    """
    target = target.lstrip(".").lower()
    cookie_domain = cookie_domain.lstrip(".").lower()
    if not target or not cookie_domain:
        return False
    return (
        target == cookie_domain
        or target.endswith(f".{cookie_domain}")
        or cookie_domain.endswith(f".{target}")
    )


class CookieManager:
    """Manages browser cookies for session persistence."""

    def __init__(self, cookie_file: str | None = None):
        self.cookie_file = (
            Path(cookie_file) if cookie_file else Path.home() / ".curlwright" / "cookies.json"
        )
        self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
        self.cookies: CookieJar = []

    async def save_cookies(self, context) -> None:
        try:
            self.cookies = await context.cookies()
            _atomic_write_private(self.cookie_file, json.dumps(self.cookies))
            logger.info("Saved %s cookies to %s", len(self.cookies), self.cookie_file)
        except Exception as error:
            logger.error("Failed to save cookies: %s", error)

    async def load_cookies(self, context) -> bool:
        try:
            if not self.cookie_file.exists():
                logger.info("No cookie file found")
                return False
            with open(self.cookie_file, "r", encoding="utf-8") as file_handle:
                self.cookies = json.load(file_handle)
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
            _restrict_to_owner(Path(output_file))
            logger.info("Exported cookies to %s", output_file)
        except Exception as error:
            logger.error("Failed to export cookies: %s", error)

    def import_cookies_json(self, input_file: str) -> bool:
        try:
            with open(input_file, "r", encoding="utf-8") as file_handle:
                self.cookies = json.load(file_handle)
            _atomic_write_private(self.cookie_file, json.dumps(self.cookies))
            logger.info("Imported %s cookies from %s", len(self.cookies), input_file)
            return True
        except Exception as error:
            logger.error("Failed to import cookies: %s", error)
            return False

    def get_cookies_for_domain(self, domain: str) -> CookieJar:
        return [
            cookie
            for cookie in self.cookies
            if _domains_related(domain, str(cookie.get("domain", "")))
        ]


class DomainStateStore:
    """File-backed store for per-domain bypass state."""

    def __init__(self, state_file: str | None = None):
        self.state_file = (
            Path(state_file) if state_file else Path.home() / ".curlwright" / "bypass-state.json"
        )
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state: dict[str, DomainBypassState] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self.state_file.exists():
            try:
                raw_state = json.loads(self.state_file.read_text())
                self._state = {key: DomainBypassState(**value) for key, value in raw_state.items()}
            except (OSError, ValueError, TypeError) as error:
                logger.warning(
                    "Ignoring unreadable bypass state file %s: %s", self.state_file, error
                )
                self._state = {}
        self._loaded = True

    def _persist(self) -> None:
        serialized_state = {key: asdict(value) for key, value in self._state.items()}
        _atomic_write_private(
            self.state_file, json.dumps(serialized_state, indent=2, sort_keys=True)
        )

    def get(self, domain_key: str) -> DomainBypassState | None:
        self._ensure_loaded()
        return self._state.get(domain_key)

    def is_trusted(self, domain_key: str, max_age_seconds: int = 3600) -> bool:
        record = self.get(domain_key)
        if record is None:
            return False
        return record.is_trusted(max_age_seconds)

    def _upsert_record(
        self,
        *,
        domain_key: str,
        domain: str,
        user_agent: str,
        proxy: str | None,
        profile_dir: str | None,
    ) -> DomainBypassState:
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
        self._state[domain_key] = record
        return record

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
        record = self._upsert_record(
            domain_key=domain_key,
            domain=domain,
            user_agent=user_agent,
            proxy=proxy,
            profile_dir=profile_dir,
        )
        record.verified_at = time.time()
        record.last_url = final_url
        record.last_status = "verified"
        record.success_count += 1
        record.cookie_names = sorted(set(cookie_names))
        record.last_artifact_dir = artifact_dir
        self._persist()
        logger.info(
            "Marked %s as trusted (success_count=%s, cookies=%s)",
            domain_key,
            record.success_count,
            len(record.cookie_names),
        )

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
        record = self._upsert_record(
            domain_key=domain_key,
            domain=domain,
            user_agent=user_agent,
            proxy=proxy,
            profile_dir=profile_dir,
        )
        record.last_status = "failed"
        record.failure_count += 1
        record.last_url = final_url
        record.last_artifact_dir = artifact_dir
        self._persist()
        logger.warning("Marked %s as failed (failure_count=%s)", domain_key, record.failure_count)
