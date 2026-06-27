import base64

import pytest

from curlwright.domain import CurlRequest
from curlwright.executor import RequestExecutor
from curlwright.infrastructure.playwright_runtime import PlaywrightRequestRuntime
from curlwright.infrastructure.protection_runtime import PlaywrightPageProbe


class _WarmFakePage:
    def __init__(self):
        self.gotos = []

    async def goto(self, url, **_kwargs):
        self.gotos.append(url)

    async def bring_to_front(self):
        pass

    class _Mouse:
        async def move(self, *a, **k):
            pass

        async def wheel(self, *a, **k):
            pass

    mouse = _Mouse()

    async def evaluate(self, *a, **k):
        pass

    async def wait_for_load_state(self, *a, **k):
        pass


@pytest.mark.asyncio
async def test_fast_mode_skips_warmup_navigation():
    runtime = PlaywrightRequestRuntime()
    request = CurlRequest(url="https://example.com/path")

    slow = _WarmFakePage()
    await runtime.warm_up_page(slow, request, 100, cookie_manager=None, trusted_session=False)
    assert slow.gotos == ["https://example.com"]

    fast = _WarmFakePage()
    await runtime.warm_up_page(
        fast, request, 100, cookie_manager=None, trusted_session=False, fast=True
    )
    assert fast.gotos == []


def test_basic_auth_is_sent_preemptively_in_fetch_headers():
    executor = RequestExecutor(timeout=30)
    request = CurlRequest(url="https://example.com/private", auth=("alice", "secret"))

    options = executor.http_runtime.build_fetch_options(request)

    expected = "Basic " + base64.b64encode(b"alice:secret").decode()
    assert options["headers"]["Authorization"] == expected
    # The request's own headers must not be mutated as a side effect.
    assert "Authorization" not in request.headers


def test_explicit_authorization_header_is_not_overridden_by_auth():
    executor = RequestExecutor(timeout=30)
    request = CurlRequest(
        url="https://example.com/private",
        headers={"Authorization": "Bearer token123"},
        auth=("alice", "secret"),
    )

    options = executor.http_runtime.build_fetch_options(request)

    assert options["headers"]["Authorization"] == "Bearer token123"


def test_request_timeout_overrides_executor_default():
    executor = RequestExecutor(timeout=30)
    request = CurlRequest(url="https://example.com", timeout=7)

    assert executor._get_effective_timeout(request) == 7


def test_fetch_options_respect_redirect_and_post_defaults():
    executor = RequestExecutor(timeout=30)
    request = CurlRequest(
        url="https://example.com/api",
        method="POST",
        data="name=test",
        follow_redirects=False,
    )

    options = executor.http_runtime.build_fetch_options(request)

    assert options["redirect"] == "manual"
    assert options["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert options["body"] == "name=test"


def test_json_post_preserves_json_content_type_default():
    executor = RequestExecutor(timeout=30)
    request = CurlRequest(
        url="https://example.com/api",
        method="POST",
        data='{"hello":"world"}',
    )

    options = executor.http_runtime.build_fetch_options(request)

    assert options["headers"]["Content-Type"] == "application/json"


def test_http_credentials_and_browser_signature_include_runtime_settings():
    executor = RequestExecutor(timeout=30)
    request = CurlRequest(
        url="https://example.com/private",
        auth=("alice", "secret"),
        proxy="http://proxy.internal:8080",
        verify_ssl=False,
    )

    assert executor._get_http_credentials(request) == {
        "username": "alice",
        "password": "secret",
    }
    assert executor._get_browser_signature(
        request,
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    ) == (
        "http://proxy.internal:8080",
        False,
        ("alice", "secret"),
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    )


def test_cookie_persistence_is_enabled_by_default(tmp_path):
    cookie_file = tmp_path / "cookies.pkl"
    executor = RequestExecutor(cookie_file=str(cookie_file))

    assert executor.persist_cookies is True
    assert executor.cookie_manager is not None
    assert executor.cookie_manager.cookie_file == cookie_file


def test_cloudflare_interstitial_body_is_not_classified_as_clear():
    assessment = PlaywrightPageProbe().assess_response_payload(
        {
            "status": 200,
            "url": "https://cloudflarechallenge.com/",
            "body": "<html><head><title>Attention Required! | Cloudflare</title></head>"
            "<body>/cdn-cgi/styles/ challenge page</body></html>",
        }
    )

    assert assessment.outcome == "challenge"
