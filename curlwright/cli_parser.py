"""Public CLI argument parser for CurlWright."""

import argparse

from curlwright.runtime import ensure_supported_python

ensure_supported_python()


class CLI:
    """Handles command line argument parsing."""

    def __init__(self):
        self.parser = self._create_parser()

    def _create_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog="curlwright",
            description="Bypass Cloudflare protection using Playwright and execute curl commands",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  # Execute curl command directly
  python curlwright.py -c "curl https://example.com"

  # Execute curl from file
  python curlwright.py -f request.txt

  # With custom options
  python curlwright.py -c "curl https://example.com" --headless --timeout 60 --retries 5
            """,
        )

        input_group = parser.add_mutually_exclusive_group(required=True)
        input_group.add_argument("-c", "--curl", type=str, help="Curl command to execute")
        input_group.add_argument("-f", "--file", type=str, help="File containing curl command")

        browser_group = parser.add_argument_group("Browser Options")
        browser_group.add_argument("--headless", action="store_true", default=False, help="Run browser in headless mode (default: False)")
        browser_group.add_argument("--no-gui", action="store_true", default=False, help="Run in server mode without X11/display requirement (implies --headless)")
        browser_group.add_argument("--user-agent", type=str, default=None, help="Custom user agent string")
        browser_group.add_argument("--timeout", type=int, default=30, help="Request timeout in seconds (default: 30)")
        browser_group.add_argument("--cookie-file", type=str, default=None, help="Override the persistent cookie jar path (default: ~/.curlwright/cookies.pkl)")
        browser_group.add_argument("--state-file", type=str, default=None, help="Override the bypass state path (default: ~/.curlwright/bypass-state.json)")
        browser_group.add_argument("--artifact-dir", type=str, default=None, help="Directory for failure artifacts like HTML, screenshots, and diagnostics")
        browser_group.add_argument("--profile-dir", type=str, default=None, help="Override the persistent Chromium profile directory (default: ~/.curlwright/browser-profile)")
        browser_group.add_argument("--no-persist-cookies", action="store_true", default=False, help="Disable automatic cookie load/save between runs")
        browser_group.add_argument("--bypass-attempts", type=int, default=3, help="Challenge-resolution attempts per request before the retry loop continues (default: 3)")

        retry_group = parser.add_argument_group("Retry Options")
        retry_group.add_argument("--retries", type=int, default=3, help="Number of retries on failure (default: 3)")
        retry_group.add_argument("--delay", type=int, default=5, help="Delay between retries in seconds (default: 5)")

        output_group = parser.add_argument_group("Output Options")
        output_group.add_argument("-o", "--output", type=str, help="Save response to file")
        output_group.add_argument("-v", "--verbose", action="store_true", default=False, help="Verbose output")
        output_group.add_argument("--json-output", action="store_true", default=False, help="Emit a structured JSON payload with response, attempt summary, and runtime metadata")
        output_group.add_argument("--sarif-output", type=str, default=None, help="Write a SARIF 2.1.0 report for CI/security tooling to the given path")

        return parser

    def parse_arguments(self, args: list[str] | None = None):
        """Parse command line arguments."""
        return self.parser.parse_args(args)
