from __future__ import annotations

import logging

from curlwright.domain import FetchResponse
from curlwright.infrastructure.bypass_classifier import BypassClassifier

CLASSIFIER_LOGGER = "curlwright.infrastructure.bypass_classifier"


def test_response_assessment_logs_blocked_verdict(caplog):
    classifier = BypassClassifier()
    blocked = FetchResponse(
        status=403,
        headers={},
        body="Sorry, you have been blocked",
        url="https://example.com/data",
    )

    with caplog.at_level(logging.DEBUG, logger=CLASSIFIER_LOGGER):
        assessment = classifier.assess_response_payload(blocked)

    assert assessment.outcome != "clear"
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any(f"outcome={assessment.outcome}" in m and "status=403" in m for m in messages)


def test_response_assessment_logs_clear_verdict(caplog):
    classifier = BypassClassifier()
    clear = FetchResponse(
        status=200,
        headers={},
        body='{"ok": true}',
        url="https://example.com/data",
    )

    with caplog.at_level(logging.DEBUG, logger=CLASSIFIER_LOGGER):
        assessment = classifier.assess_response_payload(clear)

    assert assessment.outcome == "clear"
    assert any(
        "outcome=clear" in r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG
    )
