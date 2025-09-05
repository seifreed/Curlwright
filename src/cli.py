"""
Command Line Interface module for CurlWright
"""

import argparse
from typing import Optional


class CLI:
    """Handles command line argument parsing"""
    
    def __init__(self):
        self.parser = self._create_parser()
    
    def _create_parser(self) -> argparse.ArgumentParser:
        """Create and configure argument parser"""
        parser = argparse.ArgumentParser(
            prog='curlwright',
            description='Bypass Cloudflare protection using Playwright and execute curl commands',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Execute curl command directly
  python curlwright.py -c "curl https://example.com"
  
  # Execute curl from file
  python curlwright.py -f request.txt
  
  # With custom options
  python curlwright.py -c "curl https://example.com" --headless --timeout 60 --retries 5
            """
        )
        
        # Input options
        input_group = parser.add_mutually_exclusive_group(required=True)
        input_group.add_argument(
            '-c', '--curl',
            type=str,
            help='Curl command to execute'
        )
        input_group.add_argument(
            '-f', '--file',
            type=str,
            help='File containing curl command'
        )
        
        # Browser options
        browser_group = parser.add_argument_group('Browser Options')
        browser_group.add_argument(
            '--headless',
            action='store_true',
            default=False,
            help='Run browser in headless mode (default: False)'
        )
        browser_group.add_argument(
            '--user-agent',
            type=str,
            default=None,
            help='Custom user agent string'
        )
        browser_group.add_argument(
            '--timeout',
            type=int,
            default=30,
            help='Request timeout in seconds (default: 30)'
        )
        
        # Retry options
        retry_group = parser.add_argument_group('Retry Options')
        retry_group.add_argument(
            '--retries',
            type=int,
            default=3,
            help='Number of retries on failure (default: 3)'
        )
        retry_group.add_argument(
            '--delay',
            type=int,
            default=5,
            help='Delay between retries in seconds (default: 5)'
        )
        
        # Output options
        output_group = parser.add_argument_group('Output Options')
        output_group.add_argument(
            '-o', '--output',
            type=str,
            help='Save response to file'
        )
        output_group.add_argument(
            '-v', '--verbose',
            action='store_true',
            default=False,
            help='Verbose output'
        )
        
        return parser
    
    def parse_arguments(self, args: Optional[list] = None):
        """Parse command line arguments"""
        return self.parser.parse_args(args)