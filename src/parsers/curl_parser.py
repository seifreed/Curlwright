"""
Curl command parser module
Parses curl commands and converts them to request objects
"""

import shlex
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.runtime_compat import ensure_supported_python

ensure_supported_python()

type HeaderMap = dict[str, str]
type CookieMap = dict[str, str]
type AuthCredentials = tuple[str, str]
type QueryPairs = list[tuple[str, str]]


@dataclass
class CurlRequest:
    """Represents a parsed curl request"""
    url: str
    method: str = "GET"
    headers: HeaderMap = field(default_factory=dict)
    data: str | None = None
    cookies: CookieMap = field(default_factory=dict)
    auth: AuthCredentials | None = None
    follow_redirects: bool = False
    verify_ssl: bool = True
    timeout: int | None = None
    proxy: str | None = None
    
    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for easy serialization"""
        return {
            'url': self.url,
            'method': self.method,
            'headers': self.headers,
            'data': self.data,
            'cookies': self.cookies,
            'auth': self.auth,
            'follow_redirects': self.follow_redirects,
            'verify_ssl': self.verify_ssl,
            'timeout': self.timeout,
            'proxy': self.proxy
        }


class CurlParser:
    """Parser for curl commands"""
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        """Reset parser state"""
        self.request = None
    
    def parse(self, curl_command: str) -> CurlRequest:
        """
        Parse a curl command string into a CurlRequest object
        
        Args:
            curl_command: The curl command string to parse
            
        Returns:
            CurlRequest object with parsed parameters
        """
        # Clean the command - handle multiline commands
        curl_command = curl_command.strip()
        # Remove backslashes used for line continuation
        curl_command = curl_command.replace('\\\n', ' ')
        curl_command = curl_command.replace('\n', ' ')
        # Clean up extra spaces
        curl_command = ' '.join(curl_command.split())
        
        if curl_command.startswith('curl'):
            curl_command = curl_command[4:].strip()
        
        # Use shlex to properly parse quoted strings
        try:
            tokens = shlex.split(curl_command)
        except ValueError as e:
            raise ValueError(f"Invalid curl command format: {e}")
        
        # Initialize request object
        request = CurlRequest(url="")
        
        append_data_to_query = False
        query_pairs: QueryPairs = []

        # Parse tokens
        i = 0
        while i < len(tokens):
            token = tokens[i]
            
            # URL (non-flag argument)
            if not token.startswith('-'):
                if not request.url:
                    request.url = token
                i += 1
                continue
            
            # Handle flags
            if token in ['-X', '--request']:
                i += 1
                if i < len(tokens):
                    request.method = tokens[i].upper()
            
            elif token in ['-H', '--header']:
                i += 1
                if i < len(tokens):
                    self._parse_header(tokens[i], request)
            
            elif token in ['-d', '--data', '--data-raw', '--data-binary']:
                i += 1
                if i < len(tokens):
                    if append_data_to_query:
                        query_pairs.extend(self._parse_form_pairs(tokens[i]))
                    else:
                        request.data = self._append_request_data(request.data, tokens[i])
                    if request.method == "GET" and not append_data_to_query:
                        request.method = "POST"
            
            elif token == '--data-urlencode':
                i += 1
                if i < len(tokens):
                    encoded_pairs = self._parse_data_urlencode(tokens[i])
                    if append_data_to_query:
                        query_pairs.extend(encoded_pairs)
                    else:
                        encoded_string = urlencode(encoded_pairs, doseq=True)
                        request.data = self._append_request_data(request.data, encoded_string)
                    if request.method == "GET" and not append_data_to_query:
                        request.method = "POST"
            
            elif token in ['-b', '--cookie']:
                i += 1
                if i < len(tokens):
                    self._parse_cookies(tokens[i], request)
            
            elif token in ['-u', '--user']:
                i += 1
                if i < len(tokens):
                    self._parse_auth(tokens[i], request)
            
            elif token in ['-L', '--location']:
                request.follow_redirects = True
            
            elif token in ['-k', '--insecure']:
                request.verify_ssl = False
            
            elif token == '--max-time':
                i += 1
                if i < len(tokens):
                    request.timeout = int(tokens[i])
            
            elif token in ['-x', '--proxy']:
                i += 1
                if i < len(tokens):
                    request.proxy = tokens[i]
            
            elif token == '-I' or token == '--head':
                request.method = "HEAD"
            
            elif token in ['-G', '--get']:
                append_data_to_query = True
                request.method = "GET"
            
            elif token == '--compressed':
                # Playwright handles compression automatically
                pass
            
            elif token in ['-i', '--include']:
                # Include headers in output - handled by the executor
                pass
            
            elif token in ['-s', '--silent', '-v', '--verbose', '-o', '--output']:
                # Skip these flags as they don't affect the request itself
                if token in ['-o', '--output']:
                    i += 1  # Skip the output file parameter
            
            i += 1
        
        # Validate parsed request
        if not request.url:
            raise ValueError("No URL found in curl command")
        
        # Ensure URL has protocol
        if not request.url.startswith(('http://', 'https://')):
            request.url = 'https://' + request.url

        if append_data_to_query:
            if request.data:
                query_pairs.extend(self._parse_form_pairs(request.data))
                request.data = None
            request.url = self._append_query_pairs(request.url, query_pairs)
        
        self.request = request
        return request
    
    def _parse_header(self, header_string: str, request: CurlRequest):
        """Parse header string and add to request"""
        if ':' in header_string:
            key, value = header_string.split(':', 1)
            request.headers[key.strip()] = value.strip()
    
    def _parse_cookies(self, cookie_string: str, request: CurlRequest):
        """Parse cookie string and add to request"""
        # Check if it's a file reference
        if not cookie_string.startswith('@'):
            # Parse cookie string
            for cookie in cookie_string.split(';'):
                if '=' in cookie:
                    key, value = cookie.split('=', 1)
                    request.cookies[key.strip()] = value.strip()
    
    def _parse_auth(self, auth_string: str, request: CurlRequest):
        """Parse authentication string"""
        if ':' in auth_string:
            username, password = auth_string.split(':', 1)
            request.auth = (username, password)
        else:
            request.auth = (auth_string, '')

    def _append_request_data(self, existing_data: str | None, new_data: str) -> str:
        """Append form-style data fragments preserving curl ordering."""
        if not existing_data:
            return new_data
        return f"{existing_data}&{new_data}"

    def _parse_form_pairs(self, raw_data: str) -> QueryPairs:
        """Parse form-like data into query parameter pairs."""
        if '=' not in raw_data:
            return [("", raw_data)]
        return parse_qsl(raw_data, keep_blank_values=True)

    def _parse_data_urlencode(self, value: str) -> QueryPairs:
        """Parse `--data-urlencode` values into structured pairs."""
        if "=" not in value:
            return [("", value)]
        key, raw_value = value.split("=", 1)
        return [(key, raw_value)]

    def _append_query_pairs(self, url: str, query_pairs: QueryPairs) -> str:
        """Append query pairs to a URL without dropping existing parameters."""
        if not query_pairs:
            return url

        parsed = urlsplit(url)
        current_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        updated_query = urlencode(current_pairs + query_pairs, doseq=True)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, updated_query, parsed.fragment))
    
    def parse_from_file(self, file_path: str) -> CurlRequest:
        """
        Parse curl command from a file
        
        Args:
            file_path: Path to file containing curl command
            
        Returns:
            CurlRequest object
        """
        with open(file_path, 'r') as f:
            curl_command = f.read().strip()
        
        # Handle multiline curl commands (with backslashes)
        curl_command = curl_command.replace('\\\n', ' ')
        curl_command = curl_command.replace('\n', ' ')
        
        return self.parse(curl_command)
