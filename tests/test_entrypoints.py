from __future__ import annotations

import importlib.util
import json
import os
import runpy
import subprocess
import sys
from argparse import Namespace
from contextlib import contextmanager
from pathlib import Path

import pytest

import curlwright.main as package_main
from tests.helpers import start_fixture_server


@contextmanager
def _argv(*args: str):
    original = list(sys.argv)
    sys.argv = list(args)
    try:
        yield
    finally:
        sys.argv = original


def test_package_main_verbose_output():
    server, thread = start_fixture_server()
    url = f"http://127.0.0.1:{server.server_port}/json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "curlwright.main",
            "-c",
            f"curl {url}",
            "--headless",
            "--verbose",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )

    server.shutdown()
    thread.join(timeout=2)

    assert result.returncode == 0
    assert "Status: 200" in result.stdout
    assert '"ok": true' in result.stdout.lower()
    assert "Attempts: 1" in result.stdout


def test_root_script_writes_output_file(tmp_path):
    server, thread = start_fixture_server()
    url = f"http://127.0.0.1:{server.server_port}/json"
    output_file = tmp_path / "result.json"

    result = subprocess.run(
        [
            sys.executable,
            "curlwright.py",
            "-c",
            f"curl {url}",
            "--headless",
            "--output",
            str(output_file),
        ],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )

    server.shutdown()
    thread.join(timeout=2)

    assert result.returncode == 0
    assert output_file.exists()
    assert '"ok": true' in output_file.read_text().lower()


def test_cli_entrypoint_prints_body():
    server, thread = start_fixture_server()
    url = f"http://127.0.0.1:{server.server_port}/text"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "curlwright.cli",
            "-c",
            f"curl {url}",
            "--headless",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )

    server.shutdown()
    thread.join(timeout=2)

    assert result.returncode == 0
    assert "fixture text response" in result.stdout


def test_cli_json_output_contains_meta():
    server, thread = start_fixture_server()
    url = f"http://127.0.0.1:{server.server_port}/json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "curlwright.main",
            "-c",
            f"curl {url}",
            "--headless",
            "--json-output",
            "--artifact-dir",
            ".artifacts/test-json",
            "--state-file",
            ".artifacts/test-json/state.json",
            "--cookie-file",
            ".artifacts/test-json/cookies.pkl",
            "--profile-dir",
            ".artifacts/test-json/profile",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )

    server.shutdown()
    thread.join(timeout=2)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["kind"] == "curlwright-result"
    assert payload["ok"] is True
    assert payload["exit_code"] == 0
    assert payload["response"]["status"] == 200
    assert os.path.normpath(payload["meta"]["runtime"]["artifact_dir"]) == os.path.normpath(".artifacts/test-json")
    assert os.path.normpath(payload["meta"]["runtime"]["cookie_file"]) == os.path.normpath(".artifacts/test-json/cookies.pkl")
    assert os.path.normpath(payload["meta"]["runtime"]["state_file"]) == os.path.normpath(".artifacts/test-json/state.json")
    assert os.path.normpath(payload["meta"]["runtime"]["profile_dir"]) == os.path.normpath(".artifacts/test-json/profile")
    assert payload["meta"]["attempts"][0]["outcome"] == "success"


def test_entrypoint_exits_non_zero_on_invalid_arguments():
    result = subprocess.run(
        [sys.executable, "-m", "curlwright.main"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 2
    assert "usage: curlwright" in result.stderr.lower()

def test_root_script_helpers_cover_file_and_verbose_branches(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location(
        "curlwright_root_script",
        Path(__file__).resolve().parent.parent / "curlwright.py",
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    request_file = tmp_path / "request.txt"
    request_file.write_text("curl https://example.com/from-file")
    args = Namespace(file=str(request_file), curl=None)

    assert module._resolve_curl_command(args) == "curl https://example.com/from-file"

    module._write_result_output(
        {"status": 200, "headers": {"content-type": "text/plain"}, "body": "body"},
        None,
        True,
        False,
    )
    captured = capsys.readouterr()

    assert "Status: 200" in captured.out
    assert "body" in captured.out


def test_package_main_helpers_cover_error_and_output_branches(tmp_path):
    request_file = tmp_path / "request.txt"
    request_file.write_text("curl https://example.com/from-file")
    args = Namespace(file=str(request_file), curl=None)

    assert package_main._resolve_curl_command(args) == "curl https://example.com/from-file"

    output_file = tmp_path / "body.txt"
    package_main._write_result_output(
        {"status": 200, "headers": {"content-type": "text/plain"}, "body": "saved body"},
        str(output_file),
        False,
        False,
    )
    assert output_file.read_text() == "saved body"

    with pytest.raises(ValueError, match="No curl command provided"):
        package_main._resolve_curl_command(Namespace(file=None, curl=None))


def test_package_main_exits_non_zero_for_missing_file():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "curlwright.main",
            "-f",
            "definitely-missing-request.txt",
            "--headless",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 11


def test_package_main_json_failure_output_for_missing_file():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "curlwright.main",
            "-f",
            "definitely-missing-request.txt",
            "--headless",
            "--json-output",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 11
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["kind"] == "curlwright-error"
    assert payload["ok"] is False
    assert payload["exit_code"] == 11
    assert payload["error_type"] == "FileNotFoundError"


def test_package_main_json_failure_output_for_parse_error():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "curlwright.main",
            "-c",
            "curl 'unterminated",
            "--headless",
            "--json-output",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 12
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["kind"] == "curlwright-error"
    assert payload["ok"] is False
    assert payload["exit_code"] == 12
    assert payload["error_type"] == "ValueError"


def test_json_output_stays_clean_when_verbose_is_enabled():
    server, thread = start_fixture_server()
    url = f"http://127.0.0.1:{server.server_port}/json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "curlwright.main",
            "-c",
            f"curl {url}",
            "--headless",
            "--verbose",
            "--json-output",
        ],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )

    server.shutdown()
    thread.join(timeout=2)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert "Status:" not in result.stdout


def test_package_main_writes_sarif_report(tmp_path):
    server, thread = start_fixture_server()
    url = f"http://127.0.0.1:{server.server_port}/json"
    sarif_path = tmp_path / "curlwright.sarif"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "curlwright.main",
            "-c",
            f"curl {url}",
            "--headless",
            "--sarif-output",
            str(sarif_path),
        ],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )

    server.shutdown()
    thread.join(timeout=2)

    assert result.returncode == 0
    report = json.loads(sarif_path.read_text())
    assert report["version"] == "2.1.0"
    run = report["runs"][0]
    assert run["tool"]["driver"]["name"] == "CurlWright"
    assert run["results"][0]["ruleId"] == "CW000"


def test_package_main_writes_sarif_report_for_failure(tmp_path):
    sarif_path = tmp_path / "curlwright-error.sarif"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "curlwright.main",
            "-f",
            "definitely-missing-request.txt",
            "--headless",
            "--sarif-output",
            str(sarif_path),
        ],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 11


def test_in_process_main_and_cli_modules_cover_dunder_main_paths(tmp_path, capsys):
    server, thread = start_fixture_server()
    url = f"http://127.0.0.1:{server.server_port}/json"
    output_file = tmp_path / "in-process.json"

    try:
        with _argv(
            "curlwright.main",
            "-c",
            f"curl {url}",
            "--headless",
            "--output",
            str(output_file),
        ):
            runpy.run_path(
                str(Path(__file__).resolve().parent.parent / "curlwright" / "main.py"),
                run_name="__main__",
            )

        assert output_file.exists()

        with _argv(
            "curlwright.cli",
            "-c",
            f"curl {url}",
            "--headless",
        ):
            runpy.run_path(
                str(Path(__file__).resolve().parent.parent / "curlwright" / "cli.py"),
                run_name="__main__",
            )

        captured = capsys.readouterr()
        assert '"ok": true' in output_file.read_text().lower()
        assert "ok" in captured.out.lower()
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_in_process_main_json_failure_for_missing_file(capsys):
    with _argv(
        "curlwright.main",
        "-f",
        "definitely-missing-request.txt",
        "--headless",
        "--json-output",
    ):
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_path(
                str(Path(__file__).resolve().parent.parent / "curlwright" / "main.py"),
                run_name="__main__",
            )

    assert exc_info.value.code == 11
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error_type"] == "FileNotFoundError"
