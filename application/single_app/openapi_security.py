"""
OpenAPI File Security Validator

This module provides security validation for OpenAPI specification files
to prevent malicious content from being uploaded or processed.
"""

import os
import yaml
import json
import tempfile
import requests
import re
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse
from werkzeug.utils import secure_filename

class OpenApiSecurityValidator:
    """Security validator for OpenAPI specification files and URLs."""
    
    # Maximum file size for OpenAPI specs (5MB)
    MAX_FILE_SIZE = 5 * 1024 * 1024
    
    # Maximum content size when fetching from URL (10MB)
    MAX_URL_CONTENT_SIZE = 10 * 1024 * 1024
    
    # Allowed file extensions
    ALLOWED_EXTENSIONS = {'.yaml', '.yml', '.json'}
    
    # Timeout for URL requests (30 seconds)
    URL_TIMEOUT = 30
    
    # Dangerous patterns that should not appear in OpenAPI specs
    DANGEROUS_PATTERNS = [
        # Code injection attempts
        r'<\s*script\s*>',
        r'javascript\s*:',
        r'eval\s*\(',
        r'exec\s*\(',
        r'system\s*\(',
        r'__import__',
        r'subprocess',
        r'os\.system',
        r'os\.popen',
        
        # File system access
        r'\.\./',
        r'\.\.\\',
        r'/etc/passwd',
        r'/etc/shadow',
        r'C:\\Windows',
        
        # Network/protocol attacks
        r'file:///',
        r'ftp://',
        r'ldap://',
        r'gopher://',
        
        # Common malicious strings
        r'<\s*iframe',
        r'<\s*object',
        r'<\s*embed',
        r'data\s*:\s*text/html',
        
        # SQL injection patterns
        r'union\s+select',
        r'drop\s+table',
        r'insert\s+into',
        r'delete\s+from',
    ]
    
    # Required fields for a valid OpenAPI spec
    REQUIRED_OPENAPI_FIELDS = ['openapi', 'info']
    
    # Maximum depth for nested objects (prevent billion laughs attacks)
    MAX_NESTING_DEPTH = 50
    
    def __init__(self):
        self.compiled_patterns = [re.compile(pattern, re.IGNORECASE | re.MULTILINE) 
                                for pattern in self.DANGEROUS_PATTERNS]
    
    def validate_filename(self, filename: str) -> Tuple[bool, str]:
        """Validate filename for security and format."""
        if not filename:
            return False, "Filename is required"
        
        # Check file extension
        file_ext = os.path.splitext(filename.lower())[1]
        if file_ext not in self.ALLOWED_EXTENSIONS:
            return False, f"Invalid file extension. Allowed: {', '.join(self.ALLOWED_EXTENSIONS)}"
        
        # Check for dangerous characters
        dangerous_chars = ['..', '/', '\\', ':', '*', '?', '"', '<', '>', '|']
        if any(char in filename for char in dangerous_chars):
            return False, "Filename contains dangerous characters"
        
        return True, ""
    
    def validate_url(self, url: str) -> Tuple[bool, str]:
        """Validate URL for security."""
        if not url:
            return False, "URL is required"
        
        try:
            parsed = urlparse(url)
            
            # Only allow HTTP/HTTPS
            if parsed.scheme not in ['http', 'https']:
                return False, "Only HTTP and HTTPS URLs are allowed"
            
            # Block localhost and private networks
            hostname = parsed.hostname
            if not hostname:
                return False, "Invalid hostname"
            
            # Block dangerous hostnames
            blocked_hosts = [
                'localhost', '127.0.0.1', '0.0.0.0',
                '::1', '169.254.169.254'  # AWS metadata service
            ]
            
            if hostname.lower() in blocked_hosts:
                return False, "Access to localhost and metadata services is not allowed"
            
            # Block private IP ranges (basic check)
            if (hostname.startswith('10.') or 
                hostname.startswith('192.168.') or 
                hostname.startswith('172.')):
                return False, "Access to private networks is not allowed"
            
            return True, ""
            
        except Exception as e:
            return False, f"Invalid URL format: {str(e)}"
    
    def scan_content_for_threats(self, content: str) -> Tuple[bool, List[str]]:
        """Scan content for dangerous patterns."""
        threats = []
        
        for pattern in self.compiled_patterns:
            if pattern.search(content):
                threats.append(f"Dangerous pattern detected: {pattern.pattern}")
        
        return len(threats) == 0, threats
    
    def validate_file_size(self, file_size: int, is_url: bool = False) -> Tuple[bool, str]:
        """Validate file size limits."""
        max_size = self.MAX_URL_CONTENT_SIZE if is_url else self.MAX_FILE_SIZE
        
        if file_size > max_size:
            max_mb = max_size / (1024 * 1024)
            return False, f"File size exceeds maximum allowed size of {max_mb}MB"
        
        return True, ""
    
    def check_nesting_depth(self, obj: Any, current_depth: int = 0) -> bool:
        """Check for excessive nesting depth to prevent DoS attacks."""
        if current_depth > self.MAX_NESTING_DEPTH:
            return False
        
        if isinstance(obj, dict):
            for value in obj.values():
                if not self.check_nesting_depth(value, current_depth + 1):
                    return False
        elif isinstance(obj, list):
            for item in obj:
                if not self.check_nesting_depth(item, current_depth + 1):
                    return False
        
        return True
    
    def validate_openapi_structure(self, spec: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate that the spec has required OpenAPI structure."""
        if not isinstance(spec, dict):
            return False, "OpenAPI spec must be a JSON object"
        
        # Check required fields
        for field in self.REQUIRED_OPENAPI_FIELDS:
            if field not in spec:
                return False, f"Missing required field: {field}"
        
        # Validate OpenAPI version
        openapi_version = spec.get('openapi', '')
        if not openapi_version.startswith('3.'):
            return False, "Only OpenAPI 3.x versions are supported"
        
        # Check info object
        info = spec.get('info', {})
        if not isinstance(info, dict):
            return False, "info field must be an object"
        
        if 'title' not in info:
            return False, "info.title is required"
        
        # Check nesting depth
        if not self.check_nesting_depth(spec):
            return False, "OpenAPI spec has excessive nesting depth"
        
        return True, ""
    
    def validate_file_content(self, file_path: str) -> Tuple[bool, Dict[str, Any], str]:
        """Validate uploaded file content."""
        try:
            # Check file size
            file_size = os.path.getsize(file_path)
            size_valid, size_error = self.validate_file_size(file_size)
            if not size_valid:
                return False, {}, size_error
            
            # Read and validate content
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Scan for dangerous patterns
            safe, threats = self.scan_content_for_threats(content)
            if not safe:
                return False, {}, f"Security threats detected: {'; '.join(threats)}"
            
            # Parse as YAML/JSON
            file_ext = os.path.splitext(file_path)[1].lower()
            try:
                if file_ext in ['.yaml', '.yml']:
                    spec = yaml.safe_load(content)
                else:  # .json
                    spec = json.loads(content)
            except (yaml.YAMLError, json.JSONDecodeError) as e:
                return False, {}, f"Invalid file format: {str(e)}"
            
            # Validate OpenAPI structure
            structure_valid, structure_error = self.validate_openapi_structure(spec)
            if not structure_valid:
                return False, {}, structure_error
            
            return True, spec, ""
            
        except Exception as e:
            return False, {}, f"Error validating file: {str(e)}"
    
    def validate_url_content(self, url: str) -> Tuple[bool, Dict[str, Any], str]:
        """Validate OpenAPI spec from URL."""
        try:
            # Validate URL format
            url_valid, url_error = self.validate_url(url)
            if not url_valid:
                return False, {}, url_error
            
            # Fetch content with security headers
            headers = {
                'User-Agent': 'SimpleChat-OpenAPI-Validator/1.0',
                'Accept': 'application/json, application/x-yaml, text/yaml, text/plain',
                'Accept-Encoding': 'gzip, deflate'
            }
            
            response = requests.get(
                url, 
                headers=headers, 
                timeout=self.URL_TIMEOUT,
                stream=True,
                allow_redirects=True,
                verify=True  # Verify SSL certificates
            )
            
            response.raise_for_status()
            
            # Check content size before loading
            content_length = response.headers.get('content-length')
            if content_length and int(content_length) > self.MAX_URL_CONTENT_SIZE:
                return False, {}, f"Content size exceeds maximum allowed size"
            
            # Read content with size limit
            content = ""
            total_size = 0
            for chunk in response.iter_content(chunk_size=8192, decode_unicode=True):
                # chunk is already a string when decode_unicode=True
                chunk_size = len(chunk.encode('utf-8')) if isinstance(chunk, str) else len(chunk)
                total_size += chunk_size
                if total_size > self.MAX_URL_CONTENT_SIZE:
                    return False, {}, "Content size exceeds maximum allowed size"
                content += chunk
            
            # Validate content size
            size_valid, size_error = self.validate_file_size(total_size, is_url=True)
            if not size_valid:
                return False, {}, size_error
            
            # Scan for dangerous patterns
            safe, threats = self.scan_content_for_threats(content)
            if not safe:
                return False, {}, f"Security threats detected: {'; '.join(threats)}"
            
            # Parse content
            content_type = response.headers.get('content-type', '').lower()
            try:
                if 'yaml' in content_type or url.endswith(('.yaml', '.yml')):
                    spec = yaml.safe_load(content)
                else:
                    spec = json.loads(content)
            except (yaml.YAMLError, json.JSONDecodeError) as e:
                return False, {}, f"Invalid content format: {str(e)}"
            
            # Validate OpenAPI structure
            structure_valid, structure_error = self.validate_openapi_structure(spec)
            if not structure_valid:
                return False, {}, structure_error
            
            return True, spec, ""
            
        except requests.exceptions.Timeout:
            return False, {}, "Request timeout - URL took too long to respond"
        except requests.exceptions.SSLError:
            return False, {}, "SSL certificate verification failed"
        except requests.exceptions.ConnectionError:
            return False, {}, "Connection error - unable to reach URL"
        except requests.exceptions.HTTPError as e:
            return False, {}, f"HTTP error: {e.response.status_code}"
        except Exception as e:
            return False, {}, f"Error fetching URL content: {str(e)}"
    
    def create_safe_filename(self, original_filename: str) -> str:
        """Create a safe filename for storage."""
        # Use werkzeug's secure_filename but ensure we keep the extension
        safe_name = secure_filename(original_filename)
        if not safe_name:
            # Fallback if secure_filename returns empty string
            safe_name = "openapi_spec"
        
        # Ensure proper extension
        file_ext = os.path.splitext(original_filename.lower())[1]
        if file_ext in self.ALLOWED_EXTENSIONS:
            if not safe_name.endswith(file_ext):
                safe_name += file_ext
        else:
            safe_name += '.yaml'  # Default extension
        
        return safe_name


# Global validator instance
openapi_validator = OpenApiSecurityValidator()


def validate_openapi_file(file_path: str) -> Tuple[bool, Dict[str, Any], str]:
    """Convenience function to validate an OpenAPI file."""
    return openapi_validator.validate_file_content(file_path)


def validate_openapi_url(url: str) -> Tuple[bool, Dict[str, Any], str]:
    """Convenience function to validate an OpenAPI spec from URL."""
    return openapi_validator.validate_url_content(url)


def is_safe_openapi_filename(filename: str) -> bool:
    """Quick check if filename is safe for OpenAPI specs."""
    valid, _ = openapi_validator.validate_filename(filename)
    return valid
