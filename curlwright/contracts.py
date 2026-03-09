"""Compatibility facade for interface-layer output contracts."""

from curlwright.interfaces.contracts import (
    ERROR_KIND,
    EXIT_BYPASS_FAILURE,
    EXIT_IO_ERROR,
    EXIT_PARSE_ERROR,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    SCHEMA_VERSION,
    SUCCESS_KIND,
    build_failure_payload,
    build_success_payload,
    get_exit_code,
    serialize_output_payload,
)

__all__ = [
    "ERROR_KIND",
    "EXIT_BYPASS_FAILURE",
    "EXIT_IO_ERROR",
    "EXIT_PARSE_ERROR",
    "EXIT_RUNTIME_ERROR",
    "EXIT_SUCCESS",
    "EXIT_USAGE_ERROR",
    "SCHEMA_VERSION",
    "SUCCESS_KIND",
    "build_failure_payload",
    "build_success_payload",
    "get_exit_code",
    "serialize_output_payload",
]
