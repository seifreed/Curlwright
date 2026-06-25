from __future__ import annotations

from curlwright.infrastructure.browser_stealth import (
    build_browser_init_script,
    chrome_major_version,
)


def test_chrome_major_version_rejects_non_numeric_payloads():
    # A crafted user agent whose "Chrome/" segment carries JS metacharacters
    # (note: no '.' so the whole payload survives the split) must not leak
    # through as the version.
    malicious = "Mozilla/5.0 Chrome/1'};alert(document'cookie);//"
    assert chrome_major_version(malicious) == "124"
    assert chrome_major_version("Mozilla/5.0 Chrome/124.0.6998.89") == "124"
    assert chrome_major_version("Mozilla/5.0 Safari/537.36") == "124"


def test_init_script_does_not_break_out_of_js_string_literals():
    # The injection attempt must not introduce an unescaped quote into the
    # generated script; the version always lands inside '...' literals.
    script = build_browser_init_script("Mozilla/5.0 Chrome/1';alert(1);//")
    assert "alert(1)" not in script
    # Every interpolated version stays purely numeric.
    assert "version: '124'" in script
