<p align="center">
  <img src="https://img.shields.io/badge/CurlWright-Cloudflare%20Bypass-blue?style=for-the-badge" alt="CurlWright">
</p>

<h1 align="center">CurlWright</h1>

<p align="center">
  <strong>Execute curl requests through a real Playwright browser when anti-bot protection gets in the way</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/curlwright/"><img src="https://img.shields.io/pypi/v/curlwright?style=flat-square&logo=pypi&logoColor=white" alt="PyPI Version"></a>
  <a href="https://pypi.org/project/curlwright/"><img src="https://img.shields.io/pypi/pyversions/curlwright?style=flat-square&logo=python&logoColor=white" alt="Python Versions"></a>
  <a href="https://github.com/seifreed/Curlwright/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License"></a>
  <a href="https://github.com/seifreed/Curlwright/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/seifreed/Curlwright/ci.yml?style=flat-square&logo=github&label=CI" alt="CI Status"></a>
  <img src="https://img.shields.io/badge/coverage-100%25-brightgreen?style=flat-square" alt="Coverage">
</p>

<p align="center">
  <a href="https://github.com/seifreed/Curlwright/stargazers"><img src="https://img.shields.io/github/stars/seifreed/Curlwright?style=flat-square" alt="GitHub Stars"></a>
  <a href="https://github.com/seifreed/Curlwright/issues"><img src="https://img.shields.io/github/issues/seifreed/Curlwright?style=flat-square" alt="GitHub Issues"></a>
  <a href="https://buymeacoffee.com/seifreed"><img src="https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-yellow?style=flat-square&logo=buy-me-a-coffee&logoColor=white" alt="Buy Me a Coffee"></a>
</p>

---

## Overview

**CurlWright** is a Python tool that takes a curl command, opens a real Chromium browser through Playwright, resolves Cloudflare and similar browser-side friction, and returns the final HTTP response in a form that still feels close to curl-driven workflows.

It is useful when a plain HTTP client is not enough because the target requires browser execution, JavaScript, cookies, challenge handling, or a persisted trusted session.

### Key Features

| Feature | Description |
|---------|-------------|
| **Browser-backed curl execution** | Parse a curl command and execute it through Playwright |
| **Cloudflare challenge handling** | Detect and progress browser-side verification flows |
| **Turnstile support** | Includes dedicated handling for Turnstile-style flows |
| **Trusted session reuse** | Persist per-domain trust state and cookies between runs |
| **JSON and SARIF outputs** | Machine-readable output for automation and CI/security tooling |
| **Headless and server mode** | Works in local desktop mode or with `--no-gui` in CI/VPS environments |
| **Python library mode** | Use as a CLI or from Python code |
| **Clean layered architecture** | Explicit `domain`, `application`, `infrastructure`, and `interfaces` layers |

### Supported curl Inputs

```text
Methods       -X/--request, -I/--head, -G/--get
Headers       -H/--header
Body          -d/--data, --data-raw, --data-binary, --data-urlencode
Cookies       -b/--cookie
Auth          -u/--user
Network       -x/--proxy, -L/--location, -k/--insecure, --max-time
Input Forms   Direct command (-c) or file (-f)
```

---

## Installation

### From PyPI (Recommended)

```bash
pip install curlwright
python -m playwright install chromium
```

### From Source

```bash
git clone https://github.com/seifreed/Curlwright.git
cd Curlwright
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e ".[dev]"
python -m playwright install chromium
```

---

## Quick Start

```bash
# Execute a curl command directly
curlwright -c "curl https://example.com"

# Read the curl command from a file
curlwright -f request.txt

# Emit structured JSON for automation
curlwright -f request.txt --json-output
```

---

## Usage

### Command Line Interface

```bash
# Basic request
curlwright -c "curl https://httpbin.org/get"

# Save the response body to a file
curlwright -f request.txt -o response.html

# Server/CI mode
curlwright -f request.txt --no-gui --json-output

# Persist diagnostics for failures
curlwright -f request.txt --artifact-dir .artifacts/run-1 --sarif-output report.sarif

# Increase retries and timeout
curlwright -c "curl https://target.example" --timeout 60 --retries 5 --delay 3
```

### Available Options

| Option | Description |
|--------|-------------|
| `-c, --curl` | Curl command to execute |
| `-f, --file` | File containing the curl command |
| `--headless` | Run Chromium headless |
| `--no-gui` | Server-oriented mode without display requirements |
| `--user-agent` | Override the browser user agent |
| `--timeout` | Request timeout in seconds |
| `--cookie-file` | Override cookie persistence path |
| `--state-file` | Override trusted-session state path |
| `--artifact-dir` | Directory for diagnostics, screenshots, HTML and logs |
| `--profile-dir` | Override the persistent Chromium profile directory |
| `--no-persist-cookies` | Disable automatic cookie load/save |
| `--bypass-attempts` | Challenge-resolution attempts per request |
| `--retries` | Retry count after failures |
| `--delay` | Delay between retries |
| `-o, --output` | Save the rendered response output to a file |
| `-v, --verbose` | Print a runtime execution summary |
| `--json-output` | Emit the stable JSON contract |
| `--sarif-output` | Write a SARIF 2.1.0 report |

### Output Contracts

`--json-output` emits a stable machine-readable structure:

```json
{
  "schema_version": 1,
  "kind": "curlwright-result",
  "ok": true,
  "exit_code": 0,
  "response": {
    "status": 200,
    "url": "https://example.com/",
    "headers": {},
    "body": "..."
  },
  "meta": {}
}
```

Failure JSON includes `error`, `error_type`, `exit_code`, and for bypass failures also `artifact_dir` plus an `assessment` block.

---

## Python Library

### Basic Usage

```python
import asyncio

from curlwright import RequestExecutor


async def main() -> None:
    executor = RequestExecutor(headless=True, timeout=30)
    result = await executor.execute('curl -H "Accept: application/json" https://httpbin.org/get')

    print(result["status"])
    print(result["url"])
    print(result["body"][:120])

    await executor.close()


asyncio.run(main())
```

### Parse curl Before Execution

```python
from curlwright import CurlParser

parser = CurlParser()
request = parser.parse('curl -X POST -H "Content-Type: application/json" https://api.example.com')

print(request.method)
print(request.url)
print(request.headers)
```

### Cookie Persistence

```python
import asyncio

from curlwright import RequestExecutor
from curlwright.utils import CookieManager


async def main() -> None:
    cookies = CookieManager("cookies.pkl")
    executor = RequestExecutor(headless=True, cookie_file="cookies.pkl")
    result = await executor.execute("curl https://example.com")
    print(result["status"])
    await executor.close()


asyncio.run(main())
```

---

## Examples

### API Request Through A Browser Session

```bash
curlwright -c 'curl -H "Authorization: Bearer TOKEN" https://api.example.com/data' --json-output
```

### Request File

Create `request.txt`:

```bash
curl -X GET \
  -H "Accept: application/json" \
  -H "User-Agent: Analyst/1.0" \
  -b "session=abc123" \
  https://protected.example.com/api/data
```

Run it:

```bash
curlwright -f request.txt -o response.json
```

### CI-Friendly Execution

```bash
mkdir -p .artifacts/job-1

curlwright \
  -f request.txt \
  --no-gui \
  --json-output \
  --sarif-output .artifacts/job-1/curlwright.sarif \
  --artifact-dir .artifacts/job-1 \
  --state-file .artifacts/job-1/state.json \
  --cookie-file .artifacts/job-1/cookies.pkl \
  > .artifacts/job-1/result.json
```

### Headless Retry-Tuned Request

```bash
curlwright -c "curl https://target.example" --headless --timeout 90 --retries 5 --delay 2
```

---

## Architecture

The active codebase follows an explicit layered structure:

```text
curlwright/
  domain/           Pure models, policies and ports
  application/      Use cases and orchestration
  infrastructure/   Playwright, persistence and parser adapters
  interfaces/       CLI, JSON and SARIF presenters
  bootstrap.py      Composition root
```

This separation keeps browser automation and heuristics in infrastructure while the policy and use-case flow stay isolated from Playwright details.

---

## CI/CD

### Continuous Integration

GitHub Actions is configured in [`.github/workflows/ci.yml`](.github/workflows/ci.yml) to run tests on:

- Windows x64
- Windows ARM64
- Linux x64
- Linux ARM64
- macOS Intel
- macOS Apple Silicon

Coverage is generated in a dedicated Linux job and uploaded to Codecov.

### Publish To PyPI

Publishing is configured in [`.github/workflows/publish.yml`](.github/workflows/publish.yml) and is triggered by GitHub Releases.

The workflow:

1. Builds `sdist` and `wheel`
2. Validates them with `twine check`
3. Publishes to PyPI using Trusted Publishing (OIDC)

No `PYPI_TOKEN` secret is required for publish if PyPI Trusted Publisher is configured for this repository.

---

## Requirements

- Python `>=3.13,<3.15`
- Playwright Chromium installed via `python -m playwright install chromium`
- See [`pyproject.toml`](pyproject.toml) for the full package metadata and dependency declarations

---

## Contributing

Contributions are welcome. If you want to change behavior, add support for more curl flags, or improve challenge handling, open an issue or send a pull request.

1. Fork the repository
2. Create your branch: `git checkout -b feature/my-change`
3. Run the test suite
4. Commit your changes
5. Push the branch
6. Open a pull request

---

## Support the Project

If CurlWright is useful in your workflows, you can support the project here:

<a href="https://buymeacoffee.com/seifreed" target="_blank">
  <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="50">
</a>

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

**Attribution**
- Author: **Marc Rivero** | [@seifreed](https://github.com/seifreed)
- Repository: [github.com/seifreed/Curlwright](https://github.com/seifreed/Curlwright)

---

<p align="center">
  <sub>Built for browser-backed automation and resilient protected-request workflows</sub>
</p>
