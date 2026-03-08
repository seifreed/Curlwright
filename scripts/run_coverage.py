#!/usr/bin/env python3
"""Run coverage in this environment, working around a local c-tracer import hang."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TESTS = [
    "tests/test_public_api.py",
    "tests/test_curl_parser.py",
    "tests/test_request_executor.py",
    "tests/test_utils_components.py",
    "tests/test_bypass_manager.py",
    "tests/test_browser_manager.py",
    "tests/test_bypass_manager_paths.py",
    "tests/test_core_defensive_paths.py",
    "tests/test_entrypoints.py",
    "tests/test_final_line_coverage.py",
    "tests/test_line_completion.py",
    "tests/test_request_executor_paths.py",
]


def _coverage_tracer_paths() -> tuple[Path | None, Path | None]:
    """Return the active and disabled coverage tracer paths in the current interpreter."""
    purelib = Path(
        subprocess.check_output(
            [sys.executable, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
            text=True,
        ).strip()
    )
    coverage_dir = purelib / "coverage"
    active = next(coverage_dir.glob("tracer*.so"), None)
    disabled = next(coverage_dir.glob("tracer*.so.disabled"), None)
    return active, disabled


def main() -> int:
    active, disabled = _coverage_tracer_paths()
    restored = False

    try:
        if active is not None:
            active.rename(active.with_suffix(active.suffix + ".disabled"))
            restored = True

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--cov=curlwright",
            "--cov=src",
            "--cov-report=term-missing",
            *TESTS,
        ]
        return subprocess.run(cmd, cwd=ROOT).returncode
    finally:
        if restored:
            _, disabled = _coverage_tracer_paths()
            if disabled is not None:
                disabled.rename(disabled.with_suffix(""))


if __name__ == "__main__":
    raise SystemExit(main())
