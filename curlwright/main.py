#!/usr/bin/env python3
"""Package entrypoint backed by the interface layer."""

import asyncio

from curlwright.interfaces.cli_app import _resolve_curl_command, _write_result_output, main
from curlwright.interfaces.contracts import build_failure_payload

_build_failure_payload = build_failure_payload
__all__ = ["main", "_resolve_curl_command", "_write_result_output"]


if __name__ == "__main__":
    asyncio.run(main())
