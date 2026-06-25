from __future__ import annotations

import asyncio
import logging

from curlwright.domain import CurlRequest
from curlwright.infrastructure.playwright_runtime import PlaywrightRequestRuntime

RUNTIME_LOGGER = "curlwright.infrastructure.playwright_runtime"


class _FetchPage:
    async def evaluate(self, _script, payload):
        return {
            "url": payload["url"],
            "status": 200,
            "headers": {},
            "body": "ok",
        }


def test_perform_fetch_request_logs_request_and_response(caplog):
    runtime = PlaywrightRequestRuntime()
    request = CurlRequest(url="https://example.com/data")

    with caplog.at_level(logging.DEBUG, logger=RUNTIME_LOGGER):
        response = asyncio.run(runtime.perform_fetch_request(_FetchPage(), request, 1_000))

    assert response.status == 200
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("Performing in-page GET fetch to https://example.com/data" in m for m in messages)
    assert any("returned HTTP 200" in m for m in messages)
