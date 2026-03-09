from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

import pytest

from curlwright.cli_parser import CLI
from curlwright.infrastructure.logging import setup_logger
from curlwright.infrastructure.persistence import CookieManager, DomainStateStore


class FakeCookieContext:
    def __init__(self, cookies=None):
        self._cookies = cookies or []
        self.added_cookies = []

    async def cookies(self):
        return list(self._cookies)

    async def add_cookies(self, cookies):
        self.added_cookies.extend(cookies)


class FailingCookieContext:
    async def cookies(self):
        raise RuntimeError("cookie failure")


def test_domain_state_store_persists_success_and_failure(tmp_path):
    state_file = tmp_path / "state.json"
    store = DomainStateStore(str(state_file))
    domain_key = "example.com|direct|ua"

    store.mark_success(
        domain_key=domain_key,
        domain="example.com",
        user_agent="ua",
        proxy=None,
        profile_dir=str(tmp_path / "profile-a"),
        final_url="https://example.com/protected",
        cookie_names=["cf_clearance", "session"],
        artifact_dir=str(tmp_path / "artifacts"),
    )

    reloaded = DomainStateStore(str(state_file))
    record = reloaded.get(domain_key)
    assert record is not None
    assert record.last_status == "verified"
    assert record.success_count == 1
    assert record.cookie_names == ["cf_clearance", "session"]
    assert record.profile_dir == str(tmp_path / "profile-a")
    assert reloaded.is_trusted(domain_key) is True

    record.verified_at = time.time() - 7200
    reloaded._persist()
    assert DomainStateStore(str(state_file)).is_trusted(domain_key, max_age_seconds=3600) is False

    reloaded.mark_failure(
        domain_key=domain_key,
        domain="example.com",
        user_agent="ua",
        proxy=None,
        profile_dir=str(tmp_path / "profile-a"),
        final_url="https://example.com/failure",
        artifact_dir=str(tmp_path / "failure-artifacts"),
    )
    failed_record = DomainStateStore(str(state_file)).get(domain_key)
    assert failed_record is not None
    assert failed_record.last_status == "failed"
    assert failed_record.failure_count == 1


def test_cookie_manager_save_load_export_import_and_clear(tmp_path):
    cookie_file = tmp_path / "cookies.pkl"
    json_file = tmp_path / "cookies.json"
    manager = CookieManager(str(cookie_file))
    cookies = [
        {"name": "cf_clearance", "value": "ok", "domain": "example.com", "path": "/"},
        {"name": "session", "value": "abc", "domain": "api.example.com", "path": "/"},
    ]

    asyncio.run(manager.save_cookies(FakeCookieContext(cookies)))
    assert cookie_file.exists()
    assert manager.has_cookies_for_domain("example.com") is True
    assert len(manager.get_cookies_for_domain("example.com")) == 2

    second_manager = CookieManager(str(cookie_file))
    target_context = FakeCookieContext()
    assert asyncio.run(second_manager.load_cookies(target_context)) is True
    assert target_context.added_cookies == cookies

    second_manager.export_cookies_json(str(json_file))
    assert json_file.exists()

    third_manager = CookieManager(str(tmp_path / "imported.pkl"))
    assert third_manager.import_cookies_json(str(json_file)) is True
    assert third_manager.has_cookies_for_domain("example.com") is True

    third_manager.clear_cookies()
    assert third_manager.cookies == []
    assert not third_manager.cookie_file.exists()


def test_cookie_manager_handles_save_and_load_failures(tmp_path):
    cookie_file = tmp_path / "cookies.pkl"
    cookie_file.write_bytes(b"not-a-pickle")
    manager = CookieManager(str(cookie_file))

    assert asyncio.run(manager.save_cookies(FailingCookieContext())) is None
    assert asyncio.run(manager.load_cookies(FakeCookieContext())) is False


def test_cookie_manager_handles_export_import_and_clear_failures(tmp_path):
    cookie_dir = tmp_path / "cookie-dir"
    cookie_dir.mkdir()
    manager = CookieManager(str(cookie_dir))
    manager.cookies = [{"name": "session", "domain": "example.com", "value": "abc"}]

    export_target = tmp_path / "export-dir"
    export_target.mkdir()
    manager.export_cookies_json(str(export_target))

    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{bad json")
    assert manager.import_cookies_json(str(invalid_json)) is False

    manager.clear_cookies()
    assert manager.cookies == []


def test_logger_reuses_handlers_and_respects_explicit_level():
    logger_name = f"curlwright.test.{uuid.uuid4()}"
    logger = setup_logger(logger_name, logging.DEBUG)
    handler_count = len(logger.handlers)

    same_logger = setup_logger(logger_name, logging.WARNING)

    assert same_logger is logger
    assert len(same_logger.handlers) == handler_count
    assert same_logger.level == logging.WARNING


def test_cli_parses_valid_arguments():
    args = CLI().parse_arguments(
        [
            "-c",
            "curl https://example.com",
            "--headless",
            "--timeout",
            "15",
            "--retries",
            "2",
            "--delay",
            "1",
            "--output",
            "result.txt",
            "--verbose",
            "--json-output",
            "--sarif-output",
            "result.sarif",
            "--cookie-file",
            "cookies.pkl",
            "--state-file",
            "state.json",
            "--artifact-dir",
            ".artifacts",
            "--profile-dir",
            "browser-profile",
            "--bypass-attempts",
            "4",
        ]
    )

    assert args.curl == "curl https://example.com"
    assert args.file is None
    assert args.headless is True
    assert args.timeout == 15
    assert args.retries == 2
    assert args.delay == 1
    assert args.output == "result.txt"
    assert args.verbose is True
    assert args.json_output is True
    assert args.sarif_output == "result.sarif"
    assert args.cookie_file == "cookies.pkl"
    assert args.state_file == "state.json"
    assert args.artifact_dir == ".artifacts"
    assert args.profile_dir == "browser-profile"
    assert args.bypass_attempts == 4


def test_cli_supports_disabling_cookie_persistence():
    args = CLI().parse_arguments(
        ["-c", "curl https://example.com", "--no-persist-cookies"]
    )

    assert args.no_persist_cookies is True


def test_cli_rejects_missing_required_input():
    with pytest.raises(SystemExit) as exc:
        CLI().parse_arguments([])

    assert exc.value.code == 2
