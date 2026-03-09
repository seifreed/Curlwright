from curlwright.infrastructure.parsers import CurlParser
import pytest


def test_redirects_default_to_curl_behavior():
    request = CurlParser().parse("curl https://example.com")

    assert request.follow_redirects is False


def test_location_flag_enables_redirects():
    request = CurlParser().parse("curl -L https://example.com")

    assert request.follow_redirects is True


def test_insecure_timeout_and_proxy_are_parsed():
    request = CurlParser().parse(
        "curl -k --max-time 7 -x http://proxy.internal:8080 https://example.com"
    )

    assert request.verify_ssl is False
    assert request.timeout == 7
    assert request.proxy == "http://proxy.internal:8080"


def test_get_with_data_urlencode_stays_get_and_moves_data_to_query():
    request = CurlParser().parse(
        "curl -G --data-urlencode 'q=hello world' https://example.com/search"
    )

    assert request.method == "GET"
    assert request.data is None
    assert request.url == "https://example.com/search?q=hello+world"


def test_get_after_data_moves_existing_body_to_query():
    request = CurlParser().parse(
        "curl --data 'page=2' -G https://example.com/items"
    )

    assert request.method == "GET"
    assert request.data is None
    assert request.url == "https://example.com/items?page=2"


def test_existing_query_params_are_preserved_when_appending_get_data():
    request = CurlParser().parse(
        "curl -G --data-urlencode 'lang=en us' 'https://example.com/search?sort=asc'"
    )

    assert request.url == "https://example.com/search?sort=asc&lang=en+us"


def test_parser_adds_https_scheme_when_missing():
    request = CurlParser().parse("curl example.com")

    assert request.url == "https://example.com"


def test_parser_reads_headers_cookies_and_auth():
    request = CurlParser().parse(
        "curl -H 'Accept: application/json' -H 'X-Test: yes' "
        "-b 'session=abc; theme=dark' -u alice:secret https://example.com"
    )

    assert request.headers == {"Accept": "application/json", "X-Test": "yes"}
    assert request.cookies == {"session": "abc", "theme": "dark"}
    assert request.auth == ("alice", "secret")


def test_data_switches_get_to_post_and_appends_multiple_segments():
    request = CurlParser().parse("curl --data 'a=1' --data-raw 'b=2' https://example.com")

    assert request.method == "POST"
    assert request.data == "a=1&b=2"


def test_data_urlencode_without_get_uses_post_body():
    request = CurlParser().parse(
        "curl --data-urlencode 'q=hello world' https://example.com/search"
    )

    assert request.method == "POST"
    assert request.data == "q=hello+world"


def test_head_flag_sets_head_method():
    request = CurlParser().parse("curl -I https://example.com")

    assert request.method == "HEAD"


def test_output_related_flags_are_ignored_for_request_shape():
    request = CurlParser().parse(
        "curl -s -v -i -o out.txt --compressed https://example.com"
    )

    assert request.method == "GET"
    assert request.url == "https://example.com"
    assert request.data is None


def test_parse_from_file_supports_multiline_commands(tmp_path):
    request_file = tmp_path / "request.txt"
    request_file.write_text(
        "curl -X POST \\\n"
        "  -H 'Content-Type: application/json' \\\n"
        "  -d '{\"ok\":true}' \\\n"
        "  https://example.com/api\n"
    )

    request = CurlParser().parse_from_file(str(request_file))

    assert request.method == "POST"
    assert request.headers["Content-Type"] == "application/json"
    assert request.data == '{"ok":true}'


def test_parse_rejects_invalid_shell_syntax():
    with pytest.raises(ValueError, match="Invalid curl command format"):
        CurlParser().parse("curl 'https://example.com")


def test_parse_rejects_missing_url():
    with pytest.raises(ValueError, match="No URL found"):
        CurlParser().parse("curl -H 'Accept: application/json'")


def test_get_flag_moves_existing_body_and_bare_values_to_query():
    request = CurlParser().parse("curl -d 'a=1' --data-urlencode 'lonely' -G https://example.com")

    assert request.method == "GET"
    assert request.data is None
    assert request.url == "https://example.com?a=1&=lonely"


def test_auth_without_password_uses_empty_password():
    request = CurlParser().parse("curl -u alice https://example.com")

    assert request.auth == ("alice", "")
