"""
Curl command parser module
Parses curl commands and converts them to request objects
"""

import re
import shlex
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class CurlRequest:
    """Represents a parsed curl request"""
    url: str
    method: str = "GET"
    headers: Dict[str, str] = field(default_factory=dict)
    data: Optional[str] = None
    cookies: Dict[str, str] = field(default_factory=dict)
    auth: Optional[tuple] = None
    follow_redirects: bool = True
    verify_ssl: bool = True
    timeout: Optional[int] = None
    proxy: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
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
                    request.data = tokens[i]
                    if request.method == "GET":
                        request.method = "POST"
            
            elif token == '--data-urlencode':
                i += 1
                if i < len(tokens):
                    # Handle URL encoded data
                    if request.data:
                        request.data += "&" + tokens[i]
                    else:
                        request.data = tokens[i]
                    if request.method == "GET":
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