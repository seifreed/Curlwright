from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "curlwright"
FACADE_MODULES = {
    ROOT / "app.py",
    ROOT / "contracts.py",
    ROOT / "sarif.py",
}
PUBLIC_ADAPTER_EXPORTS = {
    ROOT / "logger.py",
    ROOT / "parsers.py",
    ROOT / "utils.py",
}


def _imports_for(package_path: Path) -> dict[Path, set[str]]:
    imports: dict[Path, set[str]] = {}
    for file_path in package_path.rglob("*.py"):
        module = ast.parse(file_path.read_text())
        names: set[str] = set()
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        imports[file_path] = names
    return imports


def test_domain_does_not_import_application_or_infrastructure():
    for file_path, imports in _imports_for(ROOT / "domain").items():
        assert not any(name.startswith("curlwright.application") for name in imports), file_path
        assert not any(name.startswith("curlwright.infrastructure") for name in imports), file_path
        assert not any(name.startswith("curlwright.interfaces") for name in imports), file_path


def test_application_does_not_import_playwright():
    for file_path, imports in _imports_for(ROOT / "application").items():
        assert "playwright" not in imports, file_path
        assert not any(name.startswith("playwright.") for name in imports), file_path
        assert not any(name.startswith("curlwright.interfaces") for name in imports), file_path


def test_domain_does_not_import_infrastructure():
    for file_path, imports in _imports_for(ROOT / "domain").items():
        assert not any(name.startswith("curlwright.infrastructure") for name in imports), file_path


def test_interfaces_do_not_import_application_or_infrastructure_directly():
    for file_path, imports in _imports_for(ROOT / "interfaces").items():
        assert not any(name.startswith("curlwright.application") for name in imports), file_path
        assert not any(name.startswith("curlwright.infrastructure") for name in imports), file_path
        assert not any(name.startswith("playwright.") for name in imports), file_path
        assert "playwright" not in imports, file_path


def test_bootstrap_is_the_only_root_module_that_wires_infrastructure():
    for file_path, imports in _imports_for(ROOT).items():
        if file_path.parent != ROOT:
            continue
        if file_path == ROOT / "bootstrap.py":
            assert any(name.startswith("curlwright.infrastructure") for name in imports), file_path
            continue
        if file_path in PUBLIC_ADAPTER_EXPORTS:
            continue
        assert not any(name.startswith("curlwright.infrastructure") for name in imports), file_path


def test_root_facades_only_forward_to_interfaces():
    for file_path in FACADE_MODULES:
        imports = _imports_for(file_path.parent)[file_path]
        assert any(name.startswith("curlwright.interfaces") for name in imports), file_path
        assert not any(name.startswith("curlwright.application") for name in imports), file_path
        assert not any(name.startswith("curlwright.infrastructure") for name in imports), file_path
