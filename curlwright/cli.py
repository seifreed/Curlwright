#!/usr/bin/env python3
"""CLI entry point for CurlWright package."""

import asyncio

from curlwright.interfaces.cli_app import main as curlwright_main
from curlwright.runtime import ensure_supported_python

ensure_supported_python()


def main() -> None:
    """Main entry point for the CLI."""
    asyncio.run(curlwright_main())


if __name__ == "__main__":
    main()
