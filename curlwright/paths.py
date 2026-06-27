"""Shared filesystem layout for CurlWright's per-user state."""

from __future__ import annotations

from pathlib import Path

from curlwright.runtime import ensure_supported_python

ensure_supported_python()


def curlwright_home() -> Path:
    """Root directory for CurlWright's per-user state (cookies, profiles, …)."""
    return Path.home() / ".curlwright"
