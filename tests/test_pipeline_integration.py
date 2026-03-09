from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.helpers import start_fixture_server


def test_pipeline_json_contract_and_artifacts_with_real_cli(tmp_path):
    server, thread = start_fixture_server()
    url = f"http://127.0.0.1:{server.server_port}/json"
    artifact_dir = tmp_path / "artifacts"
    cookie_file = tmp_path / "state" / "cookies.pkl"
    state_file = tmp_path / "state" / "bypass-state.json"
    sarif_file = tmp_path / "reports" / "result.sarif"

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "curlwright.main",
                "-c",
                f"curl {url}",
                "--headless",
                "--json-output",
                "--verbose",
                "--artifact-dir",
                str(artifact_dir),
                "--cookie-file",
                str(cookie_file),
                "--state-file",
                str(state_file),
                "--sarif-output",
                str(sarif_file),
            ],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["kind"] == "curlwright-result"
    assert payload["ok"] is True
    assert payload["exit_code"] == 0
    assert payload["response"]["status"] == 200
    assert payload["meta"]["runtime"]["artifact_dir"] == str(artifact_dir)
    assert payload["meta"]["runtime"]["cookie_file"] == str(cookie_file)
    assert payload["meta"]["runtime"]["state_file"] == str(state_file)
    assert "Status:" not in result.stdout
    assert "Execution summary:" in result.stderr
    assert sarif_file.exists()


def test_pipeline_failure_json_and_sarif_with_real_cli(tmp_path):
    sarif_file = tmp_path / "reports" / "error.sarif"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "curlwright.main",
            "-f",
            "missing-request.txt",
            "--headless",
            "--json-output",
            "--sarif-output",
            str(sarif_file),
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
    report = json.loads(sarif_file.read_text())
    assert report["runs"][0]["results"][0]["ruleId"] == "CW002"
