"""Core domain entities, errors, and ports."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Protocol

from curlwright.runtime import ensure_supported_python

ensure_supported_python()

type HeaderMap = dict[str, str]
type JsonObject = dict[str, object]
type ResponsePayload = dict[str, object]
type CookieNames = list[str]
type AuthCredentials = tuple[str, str]


@dataclass
class CurlRequest:
    """Represents a parsed curl request."""

    url: str
    method: str = "GET"
    headers: HeaderMap = field(default_factory=dict)
    data: str | None = None
    cookies: dict[str, str] = field(default_factory=dict)
    auth: AuthCredentials | None = None
    follow_redirects: bool = False
    verify_ssl: bool = True
    timeout: int | None = None
    proxy: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class DomainBypassState:
    """Stores the last known bypass outcome for a trust context."""

    domain_key: str
    domain: str
    user_agent: str
    proxy: str | None
    profile_dir: str | None = None
    verified_at: float | None = None
    last_url: str | None = None
    last_status: str | None = None
    success_count: int = 0
    failure_count: int = 0
    cookie_names: CookieNames = field(default_factory=list)
    last_artifact_dir: str | None = None

    def is_trusted(self, max_age_seconds: int) -> bool:
        if self.verified_at is None:
            return False
        return (time.time() - self.verified_at) <= max_age_seconds


@dataclass
class BrowserSessionConfig:
    headless: bool
    user_agent: str
    no_gui: bool
    proxy: str | None
    verify_ssl: bool
    http_credentials: dict[str, str] | None
    profile_dir: str


@dataclass
class FetchResponse:
    status: int
    headers: HeaderMap
    body: str
    url: str | None = None

    def to_payload(self) -> ResponsePayload:
        payload: ResponsePayload = {
            "status": self.status,
            "headers": dict(self.headers),
            "body": self.body,
        }
        if self.url is not None:
            payload["url"] = self.url
        return payload

    @classmethod
    def from_payload(cls, payload: ResponsePayload) -> "FetchResponse":
        return cls(
            status=int(payload["status"]),
            headers=dict(payload.get("headers", {})),
            body=str(payload.get("body", "")),
            url=str(payload["url"]) if "url" in payload and payload["url"] is not None else None,
        )


@dataclass
class BypassAssessment:
    outcome: str
    final_url: str
    title: str = ""
    status_code: int | None = None
    indicators: list[str] = field(default_factory=list)
    body_excerpt: str = ""

    @property
    def is_clear(self) -> bool:
        return self.outcome == "clear"


class BypassFailure(RuntimeError):
    """Raised when the bypass flow does not reach a trusted state."""

    def __init__(
        self,
        message: str,
        *,
        assessment: BypassAssessment,
        artifact_dir: str | None = None,
    ):
        super().__init__(message)
        self.assessment = assessment
        self.artifact_dir = artifact_dir


@dataclass
class AttemptRecord:
    attempt: int
    user_agent: str
    outcome: str = "started"
    error: str | None = None
    artifact_dir: str | None = None
    assessment: JsonObject | None = None

    def to_payload(self) -> JsonObject:
        payload = asdict(self)
        return {key: value for key, value in payload.items() if value is not None}


@dataclass
class RequestMetadata:
    url: str
    method: str
    proxy: str | None
    verify_ssl: bool
    timeout: int
    follow_redirects: bool


@dataclass
class RuntimeMetadata:
    headless: bool
    no_gui: bool
    persist_cookies: bool
    cookie_file: str | None
    state_file: str
    artifact_dir: str
    profile_dir: str
    persistent_profile: bool
    bypass_attempts: int
    max_retries: int
    retry_delay_seconds: int


@dataclass
class StateMetadata:
    domain_key: str
    trusted_session_before_request: bool


@dataclass
class FinalMetadata:
    status: int
    url: str


@dataclass
class ExecutionMetadata:
    request: RequestMetadata
    runtime: RuntimeMetadata
    state: StateMetadata
    attempts: list[AttemptRecord] = field(default_factory=list)
    final: FinalMetadata | None = None

    def to_payload(self) -> JsonObject:
        payload = asdict(self)
        if self.final is None:
            payload.pop("final", None)
        return payload


@dataclass
class ExecutionResult:
    response: FetchResponse
    outcome: object | None = None
    meta: ExecutionMetadata | None = None

    def to_payload(self) -> ResponsePayload:
        payload = self.response.to_payload()
        if self.meta is not None:
            payload["meta"] = self.meta.to_payload()
        return payload

    @classmethod
    def from_payload(cls, payload: ResponsePayload) -> "ExecutionResult":
        meta_payload = payload.get("meta", {})
        meta = None
        if isinstance(meta_payload, dict) and meta_payload:
            attempts = [
                AttemptRecord(**item)
                for item in meta_payload.get("attempts", [])
                if isinstance(item, dict)
            ]
            final = meta_payload.get("final")
            meta = ExecutionMetadata(
                request=RequestMetadata(**meta_payload["request"]),
                runtime=RuntimeMetadata(**meta_payload["runtime"]),
                state=StateMetadata(**meta_payload["state"]),
                attempts=attempts,
                final=FinalMetadata(**final) if isinstance(final, dict) else None,
            )
        return cls(response=FetchResponse.from_payload(payload), meta=meta)


class RequestParserPort(Protocol):
    def parse(self, curl_command: str) -> CurlRequest: ...


class BrowserManagerPort(Protocol):
    context: object | None

    async def initialize(self) -> None: ...

    async def create_page(self): ...

    async def close(self) -> None: ...


class BrowserManagerFactoryPort(Protocol):
    def create(self, config: BrowserSessionConfig) -> BrowserManagerPort: ...


class CookieStorePort(Protocol):
    cookie_file: object

    async def save_cookies(self, context) -> object: ...

    async def load_cookies(self, context) -> bool: ...

    def has_cookies_for_domain(self, domain: str) -> bool: ...


class DomainStateStorePort(Protocol):
    state_file: object

    def get(self, domain_key: str) -> DomainBypassState | None: ...

    def is_trusted(self, domain_key: str, max_age_seconds: int = 3600) -> bool: ...

    def mark_success(
        self,
        *,
        domain_key: str,
        domain: str,
        user_agent: str,
        proxy: str | None,
        profile_dir: str | None,
        final_url: str,
        cookie_names: CookieNames,
        artifact_dir: str | None,
    ) -> None: ...

    def mark_failure(
        self,
        *,
        domain_key: str,
        domain: str,
        user_agent: str,
        proxy: str | None,
        profile_dir: str | None,
        final_url: str | None,
        artifact_dir: str | None,
    ) -> None: ...


class PageProbePort(Protocol):
    async def assess_page(self, page, response) -> BypassAssessment: ...

    def assess_response_payload(self, payload: FetchResponse | dict[str, object]) -> BypassAssessment: ...

    async def is_managed_challenge(self, page) -> bool: ...


class ChallengeActuatorPort(Protocol):
    async def stabilize_page(self, page, *, attempt_index: int, timeout_ms: int) -> None: ...

    async def resolve_turnstile(self, page, *, timeout_ms: int) -> None: ...

    async def advance_challenge(self, page, *, attempt_index: int, timeout_ms: int) -> None: ...

    async def wait_for_managed_challenge(self, page, *, timeout_ms: int) -> None: ...

    async def revisit_target(self, page, *, target_url: str, timeout_ms: int) -> None: ...


class ArtifactStorePort(Protocol):
    artifact_root: object

    async def collect(
        self,
        *,
        page,
        assessment: BypassAssessment,
        console_events: list[dict[str, str]],
        label: str,
    ): ...


class TelemetryPort(Protocol):
    def attach_console_capture(self, page) -> list[dict[str, str]]: ...


class PersistedSessionPort(Protocol):
    state_file: object

    def get(self, domain_key: str) -> DomainBypassState | None: ...

    def is_trusted(self, domain_key: str, max_age_seconds: int = 3600) -> bool: ...

    def mark_success(
        self,
        *,
        domain_key: str,
        domain: str,
        user_agent: str,
        proxy: str | None,
        profile_dir: str | None,
        final_url: str,
        cookie_names: CookieNames,
        artifact_dir: str | None,
    ) -> None: ...

    def mark_failure(
        self,
        *,
        domain_key: str,
        domain: str,
        user_agent: str,
        proxy: str | None,
        profile_dir: str | None,
        final_url: str | None,
        artifact_dir: str | None,
    ) -> None: ...


class HttpRuntimePort(Protocol):
    async def warm_up_page(
        self,
        page,
        request: CurlRequest,
        timeout_ms: int,
        *,
        cookie_manager: CookieStorePort | None,
        trusted_session: bool,
    ) -> None: ...

    async def perform_fetch_request(self, page, request: CurlRequest, timeout_ms: int) -> FetchResponse: ...

    async def apply_request_context(self, page, request: CurlRequest, extract_domain) -> None: ...
