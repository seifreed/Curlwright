from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

from curlwright.domain import BypassAssessment
from curlwright.infrastructure.bypass_manager import BypassManager


def test_bypass_manager_classifies_blocked_response():
    assessment = BypassManager().assess_response_payload(
        {
            "status": 403,
            "url": "https://example.com/protected",
            "body": "<html><title>Access denied</title><body>Sorry, you have been blocked</body></html>",
        }
    )

    assert assessment.outcome == "blocked"
    assert "status:403" in assessment.indicators


def test_bypass_manager_classifies_extension_configuration_blocks():
    assessment = BypassManager().assess_response_payload(
        {
            "status": 200,
            "url": "https://example.com/protected",
            "body": (
                "<html><title>Just a moment...</title><body>"
                "Incompatible browser extension or network configuration. "
                "Your browser extensions or network settings have blocked the security verification process."
                "</body></html>"
            ),
        }
    )

    assert assessment.outcome == "blocked"
    assert "block-text-pattern" in assessment.indicators


def test_bypass_manager_artifact_naming_and_attempt_strategy():
    manager = BypassManager()

    artifact_name = manager._artifact_directory_name("https://sub.example.com/path", "blocked-response")
    assert artifact_name.endswith("-sub.example.com-blocked-response")

    assert manager._build_attempt_urls("https://example.com/path", trusted_session=False) == [
        "https://example.com/path",
        "https://example.com/",
        "https://example.com/path",
    ]
    assert manager._build_attempt_urls("https://example.com/path", trusted_session=True) == [
        "https://example.com/path",
        "https://example.com/path",
        "https://example.com/",
    ]


def test_bypass_manager_compacts_text():
    compacted = BypassManager()._compact_text("a \n b   c", limit=4)
    assert compacted == "a b "


def test_bypass_manager_detects_turnstile_and_writes_artifacts(tmp_path):
    asyncio.run(_exercise_turnstile_and_artifacts(tmp_path))


async def _exercise_turnstile_and_artifacts(tmp_path: Path):
    manager = BypassManager(artifact_root=str(tmp_path))
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        console_events = manager.attach_console_capture(page)
        await page.set_content(
            """
            <html>
              <head><title>Verify you are human</title></head>
              <body>
                <div class="cf-turnstile">
                  <input type="hidden" name="cf-turnstile-response" value="" />
                </div>
                <script>console.log('turnstile-loaded')</script>
              </body>
            </html>
            """
        )

        assessment = await manager.assess_page(page, None)
        assert assessment.outcome == "turnstile"
        assert any("turnstile" in indicator for indicator in assessment.indicators)

        artifact_dir = await manager.collect_failure_artifacts(
            page=page,
            assessment=BypassAssessment(
                outcome="challenge",
                final_url=page.url,
                title="Verify you are human",
                indicators=["selector:div.cf-turnstile"],
            ),
            console_events=console_events,
            label="test-artifacts",
        )

        assert artifact_dir.exists()
        assert (artifact_dir / "page.html").exists()
        assert (artifact_dir / "page.png").exists()
        assessment_payload = json.loads((artifact_dir / "assessment.json").read_text())
        assert assessment_payload["outcome"] == "challenge"
        console_payload = json.loads((artifact_dir / "console.json").read_text())
        assert any(item["text"] == "turnstile-loaded" for item in console_payload)

        await browser.close()
