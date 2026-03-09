#!/usr/bin/env python3
"""Root script entrypoint for CurlWright."""

import asyncio

from curlwright.app import _resolve_curl_command, _write_result_output, main
from curlwright.runtime import ensure_supported_python

ensure_supported_python()

__all__ = ["main", "_resolve_curl_command", "_write_result_output"]


if __name__ == "__main__":
    asyncio.run(main())
