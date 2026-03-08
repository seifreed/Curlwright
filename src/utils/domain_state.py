"""Persistent domain-level state for bypass trust decisions."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.runtime_compat import ensure_supported_python

ensure_supported_python()

type CookieNames = list[str]


@dataclass
class DomainBypassState:
    """Stores the last known bypass outcome for a trust context."""

    domain_key: str
    domain: str
    user_agent: str
    proxy: str | None
    verified_at: float | None = None
    last_url: str | None = None
    last_status: str | None = None
    success_count: int = 0
    failure_count: int = 0
    cookie_names: CookieNames = field(default_factory=list)
    last_artifact_dir: str | None = None

    def is_trusted(self, max_age_seconds: int) -> bool:
        """Return whether the record is still fresh enough to trust."""
        if self.verified_at is None:
            return False
        return (time.time() - self.verified_at) <= max_age_seconds


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
            self._state = {
                key: DomainBypassState(**value)
                for key, value in raw_state.items()
            }
        self._loaded = True

    def _persist(self) -> None:
        serialized_state = {
            key: asdict(value)
            for key, value in self._state.items()
        }
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
        )
        record.domain = domain
        record.user_agent = user_agent
        record.proxy = proxy
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
        final_url: str | None,
        artifact_dir: str | None,
    ) -> None:
        self._ensure_loaded()
        record = self._state.get(domain_key) or DomainBypassState(
            domain_key=domain_key,
            domain=domain,
            user_agent=user_agent,
            proxy=proxy,
        )
        record.domain = domain
        record.user_agent = user_agent
        record.proxy = proxy
        record.last_status = "failed"
        record.failure_count += 1
        record.last_url = final_url
        record.last_artifact_dir = artifact_dir
        self._state[domain_key] = record
        self._persist()
