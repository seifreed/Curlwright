# CurlWright

[![Python Version](https://img.shields.io/pypi/pyversions/curlwright)](https://pypi.org/project/curlwright/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://img.shields.io/pypi/v/curlwright)](https://pypi.org/project/curlwright/)

CurlWright is a Cloudflare bypass tool that leverages Playwright to execute curl commands with full browser capabilities, allowing you to access protected websites seamlessly.

## Features

- ✅ **Automatic Cloudflare Bypass** - Handles Cloudflare challenges automatically
- ✅ **Full Curl Support** - Parse and execute complex curl commands
- ✅ **Turnstile Support** - Handles Cloudflare Turnstile challenges
- ✅ **Cookie Management** - Persistent cookie storage and session management
- ✅ **Modular Architecture** - Clean, maintainable, and extensible codebase
- ✅ **Retry Mechanism** - Automatic retries with configurable delays
- ✅ **Headless & Visual Mode** - Run in background or watch the browser

## Installation

### From PyPI

```bash
pip install curlwright
```

### From Source

```bash
# Clone the repository
git clone https://github.com/seifreed/Curlwright.git
cd Curlwright

# Install in development mode
pip install -e .

# Install Playwright browsers
playwright install chromium
```

## Quick Start

### As a Command Line Tool

```bash
# Direct curl command
curlwright -c "curl https://example.com"

# From file
curlwright -f request.txt

# With custom options
curlwright -c "curl https://example.com" --headless --timeout 60 --retries 5
```

### As a Python Library

```python
import asyncio
from curlwright import RequestExecutor

async def main():
    executor = RequestExecutor(headless=True)
    
    curl_command = 'curl -H "User-Agent: Custom" https://example.com'
    result = await executor.execute(curl_command)
    
    print(f"Status: {result['status']}")
    print(f"Body: {result['body']}")
    
    await executor.close()

asyncio.run(main())
```

## Command Line Options

```
usage: curlwright [-h] (-c CURL | -f FILE) [--headless] [--user-agent USER_AGENT]
                  [--timeout TIMEOUT] [--retries RETRIES] [--delay DELAY]
                  [-o OUTPUT] [-v]

Bypass Cloudflare protection using Playwright and execute curl commands

Required Arguments:
  -c CURL, --curl CURL        Curl command to execute
  -f FILE, --file FILE        File containing curl command

Browser Options:
  --headless                   Run browser in headless mode
  --user-agent USER_AGENT      Custom user agent string
  --timeout TIMEOUT            Request timeout in seconds (default: 30)

Retry Options:
  --retries RETRIES           Number of retries on failure (default: 3)
  --delay DELAY               Delay between retries in seconds (default: 5)

Output Options:
  -o OUTPUT, --output OUTPUT   Save response to file
  -v, --verbose               Verbose output
```

## Examples

### Simple GET Request

```bash
curlwright -c "curl https://httpbin.org/get"
```

### POST Request with JSON Data

```bash
curlwright -c 'curl -X POST -H "Content-Type: application/json" -d "{\"key\":\"value\"}" https://httpbin.org/post'
```

### Request with Headers and Authentication

```bash
curlwright -c 'curl -H "Authorization: Bearer TOKEN" -H "Accept: application/json" https://api.example.com/data'
```

### Using a Request File

Create a file `request.txt`:
```
curl -X GET \
  -H "User-Agent: MyApp/1.0" \
  -H "Accept: application/json" \
  -b "session=abc123" \
  https://protected.example.com/api/data
```

Then execute:
```bash
curlwright -f request.txt -o response.json
```

## Python API

### Basic Usage

```python
from curlwright import RequestExecutor

executor = RequestExecutor(headless=True, timeout=30)
result = await executor.execute('curl https://example.com')
```

### Advanced Usage with Cookie Management

```python
from curlwright import RequestExecutor
from curlwright.utils import CookieManager

# Initialize with cookie persistence
cookie_manager = CookieManager('cookies.pkl')
executor = RequestExecutor(headless=False)

# Execute request
result = await executor.execute('curl https://example.com')

# Save cookies for next session
await cookie_manager.save_cookies(executor.browser_manager.context)
```

### Parsing Curl Commands

```python
from curlwright.parsers import CurlParser

parser = CurlParser()
request = parser.parse('curl -X POST -H "Content-Type: application/json" https://api.example.com')

print(f"Method: {request.method}")
print(f"URL: {request.url}")
print(f"Headers: {request.headers}")
```

## Project Structure

```
curlwright/
├── curlwright.py          # CLI entry point
├── requirements.txt        # Project dependencies
├── setup.py               # Package configuration
├── LICENSE                # MIT License
├── README.md              # Documentation
├── pyproject.toml         # Modern Python packaging
└── src/
    ├── __init__.py        # Package initialization
    ├── cli.py             # Command line interface
    ├── core/
    │   ├── __init__.py
    │   ├── browser_manager.py    # Playwright browser management
    │   └── request_executor.py   # Request execution logic
    ├── parsers/
    │   ├── __init__.py
    │   └── curl_parser.py        # Curl command parser
    └── utils/
        ├── __init__.py
        ├── logger.py              # Logging configuration
        └── cookie_manager.py      # Cookie management
```

## Requirements

- Python 3.13+
- Playwright
- Modern browser (Chromium)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Author

**Marc Rivero** | [mriverolopez@gmail.com](mailto:mriverolopez@gmail.com)

GitHub: [https://github.com/seifreed/Curlwright](https://github.com/seifreed/Curlwright)

## Disclaimer

This tool is for educational and testing purposes only. Always respect website terms of service and use responsibly. The authors are not responsible for any misuse or damage caused by this tool.

## Support

If you encounter any issues or have questions, please [open an issue](https://github.com/seifreed/Curlwright/issues) on GitHub.