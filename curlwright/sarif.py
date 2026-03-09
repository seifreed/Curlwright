"""Compatibility facade for interface-layer SARIF helpers."""

from curlwright.interfaces.sarif import build_sarif_report, write_sarif_report

__all__ = ["build_sarif_report", "write_sarif_report"]
