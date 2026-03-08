#!/usr/bin/env python3
"""
CurlWright - Cloudflare Bypass Tool using Playwright
Main entry point for the application
"""

import sys
import asyncio
from pathlib import Path

from src.runtime_compat import ensure_supported_python
from src.cli import CLI
from src.core.request_executor import RequestExecutor, ResponsePayload
from src.utils.logger import setup_logger

ensure_supported_python()

logger = setup_logger(__name__)


def _resolve_curl_command(args) -> str:
    """Resolve the curl command from CLI arguments."""
    if args.file:
        return Path(args.file).read_text().strip()
    if args.curl:
        return args.curl

    raise ValueError("No curl command provided")


def _write_result_output(result: ResponsePayload, output_path: str | None, verbose: bool) -> None:
    """Render or persist the executor response."""
    body = str(result['body'])
    if output_path:
        Path(output_path).write_text(body)
        logger.info(f"Response saved to {output_path}")
        return

    if verbose:
        print(f"Status: {result['status']}")
        print(f"Headers: {result['headers']}")
        print("-" * 50)
    print(body)


async def main() -> None:
    """Main entry point for CurlWright"""
    cli = CLI()
    args = cli.parse_arguments()
    executor: RequestExecutor | None = None
    
    try:
        # Handle no-gui mode (force headless)
        headless_mode = args.headless or args.no_gui
        
        # Initialize request executor
        executor = RequestExecutor(
            headless=headless_mode,
            timeout=args.timeout,
            user_agent=args.user_agent,
            no_gui=args.no_gui
        )
        curl_command = _resolve_curl_command(args)
        
        # Execute request
        result = await executor.execute(
            curl_command,
            max_retries=args.retries,
            delay=args.delay
        )
        _write_result_output(result, args.output, args.verbose)
            
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
    finally:
        if executor is not None:
            await executor.close()


if __name__ == "__main__":
    asyncio.run(main())
