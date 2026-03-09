"""Interface-layer exports for CLI and report presenters."""

from curlwright.interfaces.cli_app import _resolve_curl_command, _write_result_output, main
from curlwright.interfaces.contracts import (
    EXIT_BYPASS_FAILURE,
    EXIT_IO_ERROR,
    EXIT_PARSE_ERROR,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    build_failure_payload,
    build_success_payload,
    get_exit_code,
    serialize_output_payload,
)
from curlwright.interfaces.sarif import build_sarif_report, write_sarif_report

__all__ = [
    "EXIT_BYPASS_FAILURE",
    "EXIT_IO_ERROR",
    "EXIT_PARSE_ERROR",
    "EXIT_RUNTIME_ERROR",
    "EXIT_SUCCESS",
    "EXIT_USAGE_ERROR",
    "_resolve_curl_command",
    "_write_result_output",
    "build_failure_payload",
    "build_sarif_report",
    "build_success_payload",
    "get_exit_code",
    "main",
    "serialize_output_payload",
    "write_sarif_report",
]
