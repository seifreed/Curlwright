"""Runtime policy for the public curlwright package."""

import sys

type PythonVersion = tuple[int, int, int]

MIN_SUPPORTED_VERSION = (3, 13)
MAX_SUPPORTED_VERSION = (3, 14)


def is_supported_python(version_info: PythonVersion | None = None) -> bool:
    """Return whether the given runtime matches the supported policy."""
    version_info = version_info or sys.version_info[:3]
    major, minor, _ = version_info
    return major == 3 and MIN_SUPPORTED_VERSION[1] <= minor <= MAX_SUPPORTED_VERSION[1]


def supported_python_message(version_info: PythonVersion | None = None) -> str:
    """Build a human-readable error for unsupported runtimes."""
    version_info = version_info or sys.version_info[:3]
    major, minor, patch = version_info
    return (
        "CurlWright supports only Python 3.13 and 3.14. "
        f"Detected Python {major}.{minor}.{patch}."
    )


def ensure_supported_python(version_info: PythonVersion | None = None) -> None:
    """Fail fast when running outside the supported Python range."""
    if not is_supported_python(version_info):
        raise RuntimeError(supported_python_message(version_info))
