from __future__ import annotations

import importlib.util
import runpy
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

import curlwright.cli as package_cli
import curlwright.main as package_main
from tests.helpers import start_fixture_server


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


def test_entrypoint_exits_non_zero_on_invalid_arguments():
    result = subprocess.run(
        [sys.executable, "-m", "curlwright.main"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "usage: curlwright" in result.stderr.lower()


@pytest.mark.asyncio
async def test_package_main_runs_in_process(monkeypatch, capsys):
    server, thread = start_fixture_server()
    url = f"http://127.0.0.1:{server.server_port}/text"

    try:
        monkeypatch.setattr(sys, "argv", ["curlwright", "-c", f"curl {url}", "--headless"])
        await package_main.main()
        captured = capsys.readouterr()
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert "fixture text response" in captured.out


def test_cli_wrapper_runs_in_process(monkeypatch, capsys):
    server, thread = start_fixture_server()
    url = f"http://127.0.0.1:{server.server_port}/text"

    try:
        monkeypatch.setattr(sys, "argv", ["curlwright", "-c", f"curl {url}", "--headless"])
        package_cli.main()
        captured = capsys.readouterr()
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert "fixture text response" in captured.out


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

    assert result.returncode != 0


def test_runpy_executes_main_module_dunder_main(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["curlwright.main"])
    monkeypatch.delitem(sys.modules, "curlwright.main", raising=False)

    with pytest.raises(SystemExit):
        runpy.run_module("curlwright.main", run_name="__main__")


def test_runpy_executes_cli_module_dunder_main(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["curlwright.cli"])
    monkeypatch.delitem(sys.modules, "curlwright.cli", raising=False)

    with pytest.raises(SystemExit):
        runpy.run_module("curlwright.cli", run_name="__main__")
