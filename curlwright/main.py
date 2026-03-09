#!/usr/bin/env python3
"""Package entrypoint backed by the interface layer."""

import asyncio

from curlwright.interfaces.cli_app import _resolve_curl_command, _write_result_output, main
from curlwright.interfaces.contracts import (
    EXIT_BYPASS_FAILURE,
    EXIT_IO_ERROR,
    EXIT_PARSE_ERROR,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    EXIT_USAGE_ERROR,
    build_failure_payload,
    get_exit_code,
)

_build_failure_payload = build_failure_payload
_get_exit_code = get_exit_code
__all__ = ["main", "_resolve_curl_command", "_write_result_output"]


if __name__ == "__main__":
    asyncio.run(main())
