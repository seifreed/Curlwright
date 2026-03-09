"""Compatibility facade for the CLI interface layer."""

from curlwright.interfaces.cli_app import _resolve_curl_command, _write_result_output, main

__all__ = ["main", "_resolve_curl_command", "_write_result_output"]
