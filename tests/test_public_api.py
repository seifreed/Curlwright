from curlwright import CookieManager, CurlParser, CurlRequest, RequestExecutor, __version__, get_version
from curlwright.application import RequestExecutor as ApplicationRequestExecutor
from curlwright.infrastructure.parsers import CurlParser as InfrastructureCurlParser
from curlwright.infrastructure.persistence import CookieManager as InfrastructureCookieManager
from curlwright.parsers import CurlParser as ParserModuleExport
from curlwright.parsers import CurlRequest as RequestModuleExport
from curlwright.utils import CookieManager as CookieModuleExport
from curlwright.runtime import ensure_supported_python, is_supported_python, supported_python_message


def test_public_exports_match_documented_api():
    assert issubclass(RequestExecutor, ApplicationRequestExecutor)
    assert CurlParser is InfrastructureCurlParser
    assert CookieManager is InfrastructureCookieManager


def test_submodule_exports_match_documented_api():
    assert ParserModuleExport is InfrastructureCurlParser
    assert RequestModuleExport is CurlRequest
    assert CookieModuleExport is InfrastructureCookieManager


def test_package_version_is_consistent():
    assert __version__ == "2.0.0"
    assert get_version() == __version__


def test_runtime_policy_only_accepts_python_313_and_314():
    assert is_supported_python((3, 13, 0)) is True
    assert is_supported_python((3, 14, 9)) is True
    assert is_supported_python((3, 12, 9)) is False
    assert is_supported_python((3, 15, 0)) is False


def test_runtime_policy_error_message_is_explicit():
    message = supported_python_message((3, 12, 4))

    assert "Python 3.13 and 3.14" in message
    assert "3.12.4" in message


def test_runtime_policy_raises_for_unsupported_versions():
    try:
        ensure_supported_python((3, 12, 4))
    except RuntimeError as exc:
        assert "3.12.4" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for unsupported Python version")
