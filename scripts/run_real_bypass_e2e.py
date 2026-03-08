#!/usr/bin/env python3
"""Run the real Cloudflare end-to-end suite explicitly."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.e2e_real_cloudflare import run_real_cloudflare_suite


def main() -> None:
    results = run_real_cloudflare_suite()
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
