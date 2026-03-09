from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_wheel_installs_and_exports_public_api(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    dist_dir = repo_root / "dist"
    for wheel in dist_dir.glob("curlwright-*.whl"):
        wheel.unlink()

    build = subprocess.run(
        [sys.executable, "-m", "build", "--wheel"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert build.returncode == 0, build.stderr + build.stdout

    wheel_path = next(dist_dir.glob("curlwright-*.whl"))
    venv_dir = tmp_path / "wheel-venv"
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        cwd=repo_root,
        check=True,
        timeout=120,
    )
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    python_name = "python.exe" if os.name == "nt" else "python"
    python_bin = venv_dir / scripts_dir / python_name
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    install = subprocess.run(
        [str(python_bin), "-m", "pip", "install", str(wheel_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert install.returncode == 0, install.stderr + install.stdout

    verify = subprocess.run(
        [
            str(python_bin),
            "-c",
            (
                "from curlwright import RequestExecutor, CurlParser, CookieManager; "
                "print(RequestExecutor.__name__, CurlParser.__name__, CookieManager.__name__)"
            ),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert verify.returncode == 0, verify.stderr + verify.stdout
    assert "RequestExecutor CurlParser CookieManager" in verify.stdout
