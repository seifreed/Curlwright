"""Real end-to-end validation against a Cloudflare-protected environment.

This module is intentionally not named `test_*.py` so it is not auto-collected
by the default local pytest run. It is executed explicitly through
`scripts/run_real_bypass_e2e.py` against a real Cloudflare-backed test domain.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path

from curlwright.domain import BypassFailure
from curlwright.executor import RequestExecutor


@dataclass
class RealBypassConfig:
    base_url: str
    challenge_url: str
    turnstile_url: str
    blocked_url: str
    artifact_dir: Path
    cookie_file: Path
    state_file: Path

    @classmethod
    def from_env(cls) -> "RealBypassConfig":
        required_keys = {
            "CURLWRIGHT_E2E_BASE_URL": "Base protected origin behind Cloudflare",
            "CURLWRIGHT_E2E_CHALLENGE_URL": "URL that triggers the browser challenge",
            "CURLWRIGHT_E2E_TURNSTILE_URL": "URL protected by Turnstile",
            "CURLWRIGHT_E2E_BLOCKED_URL": "URL expected to remain blocked",
            "CURLWRIGHT_E2E_ARTIFACT_DIR": "Directory where diagnostics will be stored",
            "CURLWRIGHT_E2E_COOKIE_FILE": "Cookie persistence file for the real E2E run",
            "CURLWRIGHT_E2E_STATE_FILE": "Domain-state file for the real E2E run",
        }
        missing = [key for key in required_keys if not os.environ.get(key)]
        if missing:
            details = ", ".join(f"{key}: {required_keys[key]}" for key in missing)
            raise RuntimeError(
                "Missing Cloudflare E2E configuration. "
                f"Set these variables before running the real suite: {details}"
            )

        return cls(
            base_url=os.environ["CURLWRIGHT_E2E_BASE_URL"],
            challenge_url=os.environ["CURLWRIGHT_E2E_CHALLENGE_URL"],
            turnstile_url=os.environ["CURLWRIGHT_E2E_TURNSTILE_URL"],
            blocked_url=os.environ["CURLWRIGHT_E2E_BLOCKED_URL"],
            artifact_dir=Path(os.environ["CURLWRIGHT_E2E_ARTIFACT_DIR"]),
            cookie_file=Path(os.environ["CURLWRIGHT_E2E_COOKIE_FILE"]),
            state_file=Path(os.environ["CURLWRIGHT_E2E_STATE_FILE"]),
        )


def run_real_cloudflare_suite() -> dict[str, str]:
    """Execute the real bypass suite and return a small machine-readable summary."""
    config = RealBypassConfig.from_env()
    config.artifact_dir.mkdir(parents=True, exist_ok=True)
    if config.cookie_file.exists():
        config.cookie_file.unlink()
    if config.state_file.exists():
        config.state_file.unlink()

    results = asyncio.run(_run_real_cloudflare_suite(config))
    return results


async def _run_real_cloudflare_suite(config: RealBypassConfig) -> dict[str, str]:
    first_executor = RequestExecutor(
        headless=True,
        timeout=45,
        cookie_file=str(config.cookie_file),
        bypass_state_file=str(config.state_file),
        artifact_dir=str(config.artifact_dir),
        bypass_attempts=3,
    )
    try:
        challenge_first = await first_executor.execute(f"curl {config.challenge_url}", max_retries=2)
    finally:
        await first_executor.close()

    second_executor = RequestExecutor(
        headless=True,
        timeout=45,
        cookie_file=str(config.cookie_file),
        bypass_state_file=str(config.state_file),
        artifact_dir=str(config.artifact_dir),
        bypass_attempts=3,
    )
    try:
        challenge_second = await second_executor.execute(f"curl {config.challenge_url}", max_retries=2)
        turnstile_result = await second_executor.execute(f"curl {config.turnstile_url}", max_retries=2)
    finally:
        await second_executor.close()

    blocked_executor = RequestExecutor(
        headless=True,
        timeout=45,
        cookie_file=str(config.cookie_file),
        bypass_state_file=str(config.state_file),
        artifact_dir=str(config.artifact_dir),
        bypass_attempts=2,
    )
    try:
        try:
            await blocked_executor.execute(f"curl {config.blocked_url}", max_retries=1)
        except BypassFailure as exc:
            blocked_artifact_dir = exc.artifact_dir or ""
        else:
            raise AssertionError("Blocked URL unexpectedly succeeded during real E2E run")
    finally:
        await blocked_executor.close()

    state_payload = json.loads(config.state_file.read_text())
    if not any(record["success_count"] >= 2 for record in state_payload.values()):
        raise AssertionError("Trusted-session reuse was not recorded in domain state")

    return {
        "challenge_first_status": str(challenge_first["status"]),
        "challenge_second_status": str(challenge_second["status"]),
        "turnstile_status": str(turnstile_result["status"]),
        "blocked_artifact_dir": blocked_artifact_dir,
    }
