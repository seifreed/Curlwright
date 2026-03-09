"""Structured output contracts for the interface layer."""

import json
from dataclasses import asdict

from curlwright.errors import BypassFailure
from curlwright.models import ExecutionResult, ResponsePayload
from curlwright.runtime import ensure_supported_python

ensure_supported_python()

SCHEMA_VERSION = 1
SUCCESS_KIND = "curlwright-result"
ERROR_KIND = "curlwright-error"

EXIT_SUCCESS = 0
EXIT_USAGE_ERROR = 2
EXIT_RUNTIME_ERROR = 1
EXIT_BYPASS_FAILURE = 10
EXIT_IO_ERROR = 11
EXIT_PARSE_ERROR = 12

type JsonObject = dict[str, object]


def get_exit_code(error: Exception) -> int:
    if isinstance(error, BypassFailure):
        return EXIT_BYPASS_FAILURE
    if isinstance(error, (FileNotFoundError, PermissionError, OSError)):
        return EXIT_IO_ERROR
    if isinstance(error, ValueError):
        return EXIT_PARSE_ERROR
    return EXIT_RUNTIME_ERROR


def build_success_payload(result: ExecutionResult | ResponsePayload) -> JsonObject:
    execution_result = _normalize_result(result)
    response = execution_result.response.to_payload()
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": SUCCESS_KIND,
        "ok": True,
        "exit_code": EXIT_SUCCESS,
        "response": response,
        "meta": execution_result.meta.to_payload() if execution_result.meta is not None else {},
    }


def build_failure_payload(error: Exception) -> JsonObject:
    payload: JsonObject = {
        "schema_version": SCHEMA_VERSION,
        "kind": ERROR_KIND,
        "ok": False,
        "exit_code": get_exit_code(error),
        "error": str(error),
        "error_type": error.__class__.__name__,
    }
    if isinstance(error, BypassFailure):
        payload["artifact_dir"] = error.artifact_dir
        payload["assessment"] = asdict(error.assessment)
    return payload


def serialize_output_payload(result: ExecutionResult | ResponsePayload, json_output: bool) -> str:
    execution_result = _normalize_result(result)
    if json_output:
        return json.dumps(build_success_payload(execution_result), indent=2, sort_keys=True)
    return execution_result.response.body


def _normalize_result(result: ExecutionResult | ResponsePayload) -> ExecutionResult:
    if isinstance(result, ExecutionResult):
        return result
    return ExecutionResult.from_payload(result)
