"""SARIF 2.1.0 output helpers for the interface layer."""

import json
from pathlib import Path

from curlwright.errors import BypassFailure
from curlwright.interfaces.contracts import (
    ERROR_KIND,
    EXIT_BYPASS_FAILURE,
    EXIT_IO_ERROR,
    EXIT_PARSE_ERROR,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    SUCCESS_KIND,
    build_failure_payload,
    build_success_payload,
    get_exit_code,
)
from curlwright.models import ExecutionResult, ResponsePayload
from curlwright.runtime import ensure_supported_python

ensure_supported_python()

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/cs01/schemas/sarif-schema-2.1.0.json"


def write_sarif_report(
    output_path: str | None,
    *,
    result: ExecutionResult | ResponsePayload | None = None,
    error: Exception | None = None,
) -> None:
    if not output_path:
        return
    report = build_sarif_report(result=result, error=error)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True))


def build_sarif_report(
    *,
    result: ExecutionResult | ResponsePayload | None = None,
    error: Exception | None = None,
) -> dict[str, object]:
    if result is None and error is None:
        raise ValueError("Expected either result or error when building a SARIF report")

    invocation = _build_invocation(result=result, error=error)
    results = _build_results(result=result, error=error)
    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "CurlWright",
                        "version": "2.0.0",
                        "informationUri": "https://github.com/seifreed/Curlwright",
                        "rules": _build_rules(),
                    }
                },
                "invocations": [invocation],
                "results": results,
            }
        ],
    }


def _build_rules() -> list[dict[str, object]]:
    return [
        _rule("CW000", "Successful invocation"),
        _rule("CW001", "Bypass failure"),
        _rule("CW002", "I/O failure"),
        _rule("CW003", "Parse or validation failure"),
        _rule("CW004", "Runtime failure"),
    ]


def _rule(rule_id: str, name: str) -> dict[str, object]:
    return {
        "id": rule_id,
        "name": name,
        "shortDescription": {"text": name},
    }


def _build_invocation(
    *,
    result: ExecutionResult | ResponsePayload | None,
    error: Exception | None,
) -> dict[str, object]:
    if result is not None:
        payload = build_success_payload(result)
        return {
            "executionSuccessful": True,
            "properties": {
                "curlwrightSchemaVersion": payload["schema_version"],
                "curlwrightKind": payload["kind"],
                "curlwrightExitCode": payload["exit_code"],
            },
        }

    assert error is not None
    payload = build_failure_payload(error)
    return {
        "executionSuccessful": False,
        "exitCode": payload["exit_code"],
        "properties": {
            "curlwrightSchemaVersion": payload["schema_version"],
            "curlwrightKind": payload["kind"],
            "curlwrightErrorType": payload["error_type"],
        },
    }


def _build_results(
    *,
    result: ExecutionResult | ResponsePayload | None,
    error: Exception | None,
) -> list[dict[str, object]]:
    if result is not None:
        payload = build_success_payload(result)
        return [
            {
                "ruleId": "CW000",
                "level": "note",
                "message": {
                    "text": f"CurlWright request succeeded with HTTP {payload['response']['status']}",
                },
                "properties": {
                    "curlwrightPayloadKind": SUCCESS_KIND,
                    "curlwrightPayload": payload,
                },
            }
        ]

    assert error is not None
    payload = build_failure_payload(error)
    sarif_result: dict[str, object] = {
        "ruleId": _rule_id_for_exit_code(get_exit_code(error)),
        "level": _level_for_error(error),
        "message": {
            "text": f"{payload['error_type']}: {payload['error']}",
        },
        "properties": {
            "curlwrightPayloadKind": ERROR_KIND,
            "curlwrightPayload": payload,
        },
    }

    artifact_dir = payload.get("artifact_dir")
    if isinstance(artifact_dir, str) and artifact_dir:
        sarif_result["locations"] = [
            {
                "physicalLocation": {
                    "artifactLocation": {
                        "uri": Path(artifact_dir).as_uri(),
                    }
                }
            }
        ]

    return [sarif_result]


def _rule_id_for_exit_code(exit_code: int) -> str:
    if exit_code == EXIT_SUCCESS:
        return "CW000"
    if exit_code == EXIT_BYPASS_FAILURE:
        return "CW001"
    if exit_code == EXIT_IO_ERROR:
        return "CW002"
    if exit_code == EXIT_PARSE_ERROR:
        return "CW003"
    if exit_code == EXIT_RUNTIME_ERROR:
        return "CW004"
    return "CW004"


def _level_for_error(error: Exception) -> str:
    if isinstance(error, BypassFailure):
        return "warning"
    return "error"
