#!/usr/bin/env python3
"""
CLI entry point for CurlWright package
"""

import sys
import asyncio
from pathlib import Path

from src.runtime_compat import ensure_supported_python

ensure_supported_python()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from curlwright.main import main as curlwright_main


def main() -> None:
    """Main entry point for the CLI"""
    asyncio.run(curlwright_main())


if __name__ == "__main__":
    main()
