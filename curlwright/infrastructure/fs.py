"""Filesystem security helpers shared across infrastructure adapters."""

from __future__ import annotations

from pathlib import Path

from curlwright.logger import setup_logger
from curlwright.runtime import ensure_supported_python

ensure_supported_python()

logger = setup_logger(__name__)


def restrict_to_owner(path: Path, mode: int = 0o600) -> None:
    """Best-effort owner-only permissions for files holding credentials or
    diagnostics. chmod is skipped silently on filesystems without POSIX modes.

    The cookie jar and bypass state hold session/clearance cookies (bearer
    credentials), and failure artifacts can capture partial-session data, so the
    default 0644 would expose them to other local users.
    """
    try:
        path.chmod(mode)
    except OSError as error:
        logger.debug("Could not restrict permissions on %s: %s", path, error)
