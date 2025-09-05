#!/usr/bin/env python3
"""
CurlWright - Main module for package
"""

import sys
import argparse
import asyncio
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.cli import CLI
from src.core.request_executor import RequestExecutor
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


async def main():
    """Main entry point for CurlWright"""
    cli = CLI()
    args = cli.parse_arguments()
    
    try:
        # Initialize request executor
        executor = RequestExecutor(
            headless=args.headless,
            timeout=args.timeout,
            user_agent=args.user_agent
        )
        
        # Get curl command
        curl_command = None
        if args.file:
            curl_command = Path(args.file).read_text().strip()
        elif args.curl:
            curl_command = args.curl
        else:
            logger.error("No curl command provided")
            sys.exit(1)
        
        # Execute request
        result = await executor.execute(
            curl_command,
            max_retries=args.retries,
            delay=args.delay
        )
        
        # Handle output
        if args.output:
            Path(args.output).write_text(result['body'])
            logger.info(f"Response saved to {args.output}")
        else:
            if args.verbose:
                print(f"Status: {result['status']}")
                print(f"Headers: {result['headers']}")
                print("-" * 50)
            print(result['body'])
            
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
    finally:
        await executor.close()


if __name__ == "__main__":
    asyncio.run(main())