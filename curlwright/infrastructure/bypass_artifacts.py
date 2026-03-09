"""Failure artifact persistence for bypass diagnostics."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from curlwright.domain import BypassAssessment
from curlwright.runtime import ensure_supported_python

ensure_supported_python()

type ConsoleEvent = dict[str, str]


def artifact_directory_name(url: str, label: str) -> str:
    hostname = urlparse(url).hostname or "unknown-host"
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_hostname = re.sub(r"[^a-zA-Z0-9.-]+", "-", hostname)
    return f"{timestamp}-{safe_hostname}-{label}"


class FailureArtifactStore:
    def __init__(self, artifact_root: Path):
        self.artifact_root = artifact_root

    async def collect(
        self,
        *,
        page,
        assessment: BypassAssessment,
        console_events: list[ConsoleEvent],
        label: str,
    ) -> Path:
        artifact_dir = self.artifact_root / artifact_directory_name(page.url, label)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        html_path = artifact_dir / "page.html"
        screenshot_path = artifact_dir / "page.png"
        assessment_path = artifact_dir / "assessment.json"
        console_path = artifact_dir / "console.json"
        html_path.write_text(await page.content())
        await page.screenshot(path=str(screenshot_path), full_page=True)
        assessment_path.write_text(json.dumps(asdict(assessment), indent=2, sort_keys=True))
        console_path.write_text(json.dumps(console_events, indent=2, sort_keys=True))
        return artifact_dir
