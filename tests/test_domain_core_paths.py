from __future__ import annotations

from curlwright.domain import (
    AttemptRecord,
    ExecutionResult,
    FetchResponse,
)

from tests.helpers import make_execution_meta


def test_domain_core_payload_helpers_cover_remaining_paths():
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

    meta = make_execution_meta(cookie_file=None, attempts=[attempt])
    payload = meta.to_payload()
    assert "final" not in payload

    result = ExecutionResult(
        response=FetchResponse(
            status=200, headers={"x": "1"}, body="body", url="https://example.com"
        ),
        meta=meta,
    )
    reconstructed = ExecutionResult.from_payload(result.to_payload())
    assert reconstructed.meta is not None
    assert reconstructed.meta.attempts[0].user_agent == "ua"

    reconstructed_no_meta = ExecutionResult.from_payload(
        {"status": 204, "headers": {}, "body": "", "url": "https://example.com"}
    )
    assert reconstructed_no_meta.meta is None
