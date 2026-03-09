from __future__ import annotations

from curlwright.domain import (
    AttemptRecord,
    BypassAssessment,
    ExecutionMetadata,
    ExecutionResult,
    FetchResponse,
    RequestMetadata,
    RuntimeMetadata,
    StateMetadata,
)


def test_domain_core_payload_helpers_cover_remaining_paths():
    assessment = BypassAssessment(outcome="clear", final_url="https://example.com")
    assert assessment.is_clear is True

    attempt = AttemptRecord(
        attempt=1,
        user_agent="ua",
        outcome="success",
        error=None,
        artifact_dir=None,
        assessment=None,
    )
    assert attempt.to_payload() == {
        "attempt": 1,
        "user_agent": "ua",
        "outcome": "success",
    }

    meta = ExecutionMetadata(
        request=RequestMetadata(
            url="https://example.com",
            method="GET",
            proxy=None,
            verify_ssl=True,
            timeout=30,
            follow_redirects=False,
        ),
        runtime=RuntimeMetadata(
            headless=True,
            no_gui=True,
            persist_cookies=True,
            cookie_file=None,
            state_file="state.json",
            artifact_dir="artifacts",
            profile_dir="profile",
            persistent_profile=True,
            bypass_attempts=3,
            max_retries=1,
            retry_delay_seconds=0,
        ),
        state=StateMetadata(
            domain_key="example.com|direct|ua|profile",
            trusted_session_before_request=False,
        ),
        attempts=[attempt],
    )
    payload = meta.to_payload()
    assert "final" not in payload

    result = ExecutionResult(
        response=FetchResponse(status=200, headers={"x": "1"}, body="body", url="https://example.com"),
        meta=meta,
    )
    reconstructed = ExecutionResult.from_payload(result.to_payload())
    assert reconstructed.meta is not None
    assert reconstructed.meta.attempts[0].user_agent == "ua"

    reconstructed_no_meta = ExecutionResult.from_payload(
        {"status": 204, "headers": {}, "body": "", "url": "https://example.com"}
    )
    assert reconstructed_no_meta.meta is None
