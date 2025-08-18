"""
OpenAPI Semantic Kernel Plugin

This plugin exposes all OpenAPI endpoints as Semantic Kernel plugin functions.
Users must provide their own OpenAPI specification file and base URL.

Usage Example:
    # Basic usage with API key authentication
    plugin = OpenApiPlugin(
        openapi_spec_path="/path/to/your/openapi.yaml",
        base_url="https://api.example.com",
        auth={
            "type": "api_key",
            "location": "header",
            "name": "X-API-Key",
            "value": "your-api-key-here"
        }
    )
    
    # Bearer token authentication
    plugin = OpenApiPlugin(
        openapi_spec_path="/path/to/your/openapi.json",
        base_url="https://api.example.com",
        auth={
            "type": "bearer",
            "token": "your-bearer-token"
        }
    )
    
    # No authentication
    plugin = OpenApiPlugin(
        openapi_spec_path="/path/to/your/openapi.yaml",
        base_url="https://api.example.com"
    )

Authentication Types Supported:
    - api_key: API key in header or query parameter
    - bearer: Bearer token authentication
    - basic: Basic HTTP authentication
    - oauth2: OAuth2 access token
    - None: No authentication required

File Formats Supported:
    - YAML (.yaml, .yml)
    - JSON (.json)
    - Auto-detection based on content
"""

import os
import yaml
import json
from typing import Dict, Any, List, Optional, Union
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel.functions import kernel_function

class OpenApiPlugin(BasePlugin):
    def __init__(self, 
                 openapi_spec_path: str,
                 base_url: str,
                 auth: Optional[Dict[str, Any]] = None,
                 manifest: Optional[Dict[str, Any]] = None):
        """
        Initialize the OpenAPI plugin with user-provided configuration.
        
        Args:
            openapi_spec_path: Path to the OpenAPI specification file (YAML or JSON)
            base_url: Base URL of the API (e.g., 'https://api.example.com')
            auth: Authentication configuration (e.g., {'type': 'bearer', 'token': 'xxx'})
            manifest: Additional manifest configuration
        """
        if not openapi_spec_path:
            raise ValueError("openapi_spec_path is required")
        if not base_url:
            raise ValueError("base_url is required")
        
        self.openapi_spec_path = openapi_spec_path
        self.base_url = base_url.rstrip('/')  # Remove trailing slash
        self.auth = auth or {}
        self.manifest = manifest or {}
        
        # Load and parse the OpenAPI specification
        self.openapi = self._load_openapi_spec()
        self._metadata = self._generate_metadata()
    
    def _load_openapi_spec(self) -> Dict[str, Any]:
        """Load OpenAPI specification from YAML or JSON file."""
        if not os.path.exists(self.openapi_spec_path):
            raise FileNotFoundError(f"OpenAPI specification file not found: {self.openapi_spec_path}")
        
        try:
            with open(self.openapi_spec_path, "r", encoding="utf-8") as f:
                file_extension = os.path.splitext(self.openapi_spec_path)[1].lower()
                if file_extension in ['.yaml', '.yml']:
                    return yaml.safe_load(f)
                elif file_extension == '.json':
                    return json.load(f)
                else:
                    # Try YAML first, then JSON
                    content = f.read()
                    try:
                        f.seek(0)
                        return yaml.safe_load(f)
                    except yaml.YAMLError:
                        try:
                            return json.loads(content)
                        except json.JSONDecodeError:
                            raise ValueError(f"Unable to parse OpenAPI spec file. Ensure it's valid YAML or JSON: {self.openapi_spec_path}")
        except Exception as e:
            raise ValueError(f"Error loading OpenAPI specification: {e}")

    @property
    def display_name(self) -> str:
        api_title = self.openapi.get("info", {}).get("title", "Unknown API")
        return f"OpenAPI: {api_title}"

    @property
    def metadata(self) -> Dict[str, Any]:
        info = self.openapi.get("info", {})
        return {
            "name": info.get("title", "OpenAPIPlugin"),
            "type": "openapi",
            "description": info.get("description", ""),
            "version": info.get("version", ""),
            "base_url": self.base_url,
            "methods": self._metadata["methods"]
        }

    def _generate_metadata(self) -> Dict[str, Any]:
        info = self.openapi.get("info", {})
        paths = self.openapi.get("paths", {})
        methods = []
        for path, ops in paths.items():
            for method, op in ops.items():
                op_id = op.get("operationId", f"{method}_{path.replace('/', '_')}")
                description = op.get("description", "")
                parameters = []
                # Path/query parameters
                for param in op.get("parameters", []):
                    parameters.append({
                        "name": param.get("name"),
                        "type": param.get("schema", {}).get("type", "string"),
                        "description": param.get("description", ""),
                        "required": param.get("required", False)
                    })
                # Request body
                if "requestBody" in op:
                    req = op["requestBody"]
                    if "content" in req:
                        for content_type, content_schema in req["content"].items():
                            schema = content_schema.get("schema", {})
                            if schema.get("type") == "object":
                                for pname, pdef in schema.get("properties", {}).items():
                                    parameters.append({
                                        "name": pname,
                                        "type": pdef.get("type", "string"),
                                        "description": pdef.get("description", ""),
                                        "required": pname in schema.get("required", [])
                                    })
                # Return type (simplified)
                returns = {"type": "object", "description": ""}
                responses = op.get("responses", {})
                if "200" in responses:
                    returns["description"] = responses["200"].get("description", "")
                methods.append({
                    "name": op_id,
                    "description": description,
                    "parameters": parameters,
                    "returns": returns
                })
        return {
            "methods": methods
        }

    def get_functions(self) -> List[str]:
        # Expose all operationIds as functions (for UI listing)
        return [m["name"] for m in self._metadata["methods"]] + ["call_operation"]
    
    def get_available_operations(self) -> List[Dict[str, Any]]:
        """Get a list of all available operations with their details."""
        return self._metadata["methods"]
    
    def get_operation_details(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a specific operation."""
        for method in self._metadata["methods"]:
            if method["name"] == operation_id:
                return method
        return None
    
    @classmethod
    def create_example_auth_configs(cls) -> Dict[str, Dict[str, Any]]:
        """Return example authentication configurations for common auth types."""
        return {
            "api_key_header": {
                "type": "api_key",
                "location": "header",
                "name": "X-API-Key",
                "value": "your-api-key-here"
            },
            "api_key_query": {
                "type": "api_key",
                "location": "query",
                "name": "api_key",
                "value": "your-api-key-here"
            },
            "bearer_token": {
                "type": "bearer",
                "token": "your-bearer-token-here"
            },
            "basic_auth": {
                "type": "basic",
                "username": "your-username",
                "password": "your-password"
            },
            "oauth2": {
                "type": "oauth2",
                "access_token": "your-oauth2-access-token"
            }
        }

    @kernel_function(
        description="Call any OpenAPI operation by operation_id and parameters. Example: call_operation(operation_id='getUserById', user_id='123')"
    )
    def call_operation(self, operation_id: str, **kwargs) -> Any:
        """
        Generic OpenAPI operation caller.
        
        Args:
            operation_id: The operationId from the OpenAPI spec
            **kwargs: Parameters required by the operation
            
        Returns:
            Dict containing the operation result (implementation needed for actual HTTP calls)
        """
        # Find the operation in the spec
        operation_found = False
        for path, ops in self.openapi.get("paths", {}).items():
            for method, op in ops.items():
                if op.get("operationId") == operation_id:
                    operation_found = True
                    break
            if operation_found:
                break
        
        if not operation_found:
            raise ValueError(f"Operation '{operation_id}' not found in OpenAPI specification")
        
        # TODO: Implement actual HTTP request logic here
        # This would include:
        # 1. Building the full URL (base_url + path with parameters)
        # 2. Adding authentication headers/parameters
        # 3. Making the HTTP request
        # 4. Handling the response
        
        return {
            "operation_id": operation_id,
            "parameters": kwargs,
            "base_url": self.base_url,
            "auth_configured": bool(self.auth),
            "status": "stub_response"
        }