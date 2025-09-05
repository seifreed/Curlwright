#!/usr/bin/env python3
"""
CLI entry point for CurlWright package
"""

import sys
import asyncio
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from curlwright.main import main as curlwright_main

def main():
    """Main entry point for the CLI"""
    asyncio.run(curlwright_main())

if __name__ == "__main__":
    main()