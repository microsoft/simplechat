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
import time
import logging
from typing import Dict, Any, List, Optional, Union
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel.functions import kernel_function
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger

class OpenApiPlugin(BasePlugin):
    def __init__(self, 
                 base_url: str,
                 auth: Optional[Dict[str, Any]] = None,
                 manifest: Optional[Dict[str, Any]] = None,
                 openapi_spec_path: Optional[str] = None,
                 openapi_spec_content: Optional[Dict[str, Any]] = None):
        """
        Initialize the OpenAPI plugin with user-provided configuration.
        
        Args:
            base_url: Base URL of the API (e.g., 'https://api.example.com')
            auth: Authentication configuration (e.g., {'type': 'bearer', 'token': 'xxx'})
            manifest: Additional manifest configuration
            openapi_spec_path: Path to the OpenAPI specification file (YAML or JSON) - DEPRECATED
            openapi_spec_content: OpenAPI specification content as parsed dict (preferred)
        """
        import logging
        logging.info(f"[OpenAPI Plugin] Initializing plugin with base_url: {base_url}")
        
        if not base_url:
            raise ValueError("base_url is required")
        if not openapi_spec_path and not openapi_spec_content:
            raise ValueError("Either openapi_spec_path or openapi_spec_content is required")
        
        self.openapi_spec_path = openapi_spec_path
        self.openapi_spec_content = openapi_spec_content
        self.base_url = base_url.rstrip('/')  # Remove trailing slash
        self.auth = auth or {}
        self.manifest = manifest or {}
        
        # Track function calls for citations
        self.function_calls = []
        
        # Load and parse the OpenAPI specification
        logging.info(f"[OpenAPI Plugin] Loading OpenAPI specification...")
        self.openapi = self._load_openapi_spec()
        logging.info(f"[OpenAPI Plugin] Generating metadata...")
        self._metadata = self._generate_metadata()
        
        # Dynamically create kernel functions for each API operation
        logging.info(f"[OpenAPI Plugin] About to create dynamic functions...")
        try:
            self._create_operation_functions()
            logging.info(f"[OpenAPI Plugin] Successfully completed initialization")
        except Exception as e:
            logging.error(f"[OpenAPI Plugin] Error creating dynamic functions: {e}")
            import traceback
            logging.error(f"[OpenAPI Plugin] Traceback: {traceback.format_exc()}")
            raise
    
    def _load_openapi_spec(self) -> Dict[str, Any]:
        """Load OpenAPI specification from content or file."""
        # If we have spec content directly, use it
        if self.openapi_spec_content:
            return self.openapi_spec_content
            
        # Fall back to file-based loading for backward compatibility
        if not self.openapi_spec_path:
            raise ValueError("No OpenAPI specification provided")
            
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
    
    @plugin_function_logger("OpenApiPlugin")
    @kernel_function(
        description="List all available API operations with their details including operation IDs, descriptions, and parameters"
    )
    def get_available_operations(self) -> List[Dict[str, Any]]:
        """Get a list of all available operations with their details."""
        return self._metadata["methods"]
    
    @plugin_function_logger("OpenApiPlugin")
    @kernel_function(
        description="List just the names of all available API operations"
    )
    def list_available_apis(self) -> str:
        """List all available API operation names."""
        operations = [m["name"] for m in self._metadata["methods"]]
        api_info = self.openapi.get("info", {})
        api_title = api_info.get("title", "API")
        api_description = api_info.get("description", "")
        
        result = f"Available API operations for {api_title}:\n"
        if api_description:
            result += f"Description: {api_description}\n\n"
        
        result += "Operations:\n"
        for i, op_name in enumerate(operations, 1):
            # Find the operation details
            op_details = next((m for m in self._metadata["methods"] if m["name"] == op_name), {})
            description = op_details.get("description", "")
            result += f"{i}. {op_name}"
            if description:
                result += f" - {description}"
            result += "\n"
        
        return result
    
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

    def _create_operation_functions(self):
        """Dynamically create kernel functions for each OpenAPI operation."""
        import types
        import logging
        
        logging.info(f"[OpenAPI Plugin] Creating dynamic functions for {len(self._metadata['methods'])} operations")
        
        paths = self.openapi.get("paths", {})
        for path, operations in paths.items():
            for method, operation in operations.items():
                if not isinstance(operation, dict):
                    continue
                    
                operation_id = operation.get("operationId")
                if not operation_id:
                    # Generate operation ID if not provided
                    operation_id = f"{method}_{path.replace('/', '_').replace('{', '').replace('}', '')}"
                
                logging.info(f"[OpenAPI Plugin] Creating function: {operation_id} for {method.upper()} {path}")
                
                # Create a dynamic function for this operation
                def create_operation_function(op_id, op_path, op_method, op_data):
                    def operation_function(self, **kwargs):
                        return self._call_api_operation(op_id, op_path, op_method, op_data, **kwargs)
                    
                    # Set the function name to the operation ID
                    operation_function.__name__ = op_id
                    operation_function.__qualname__ = f"OpenApiPlugin.{op_id}"
                    
                    # Get operation description
                    description = op_data.get("description", op_data.get("summary", f"{op_method.upper()} {op_path}"))
                    
                    # Apply plugin function logger decorator FIRST for detailed logging
                    operation_function = plugin_function_logger("OpenApiPlugin")(operation_function)
                    
                    # Then add kernel_function decorator
                    operation_function = kernel_function(description=description)(operation_function)
                    return operation_function
                
                # Create and bind the function to this instance
                func = create_operation_function(operation_id, path, method, operation)
                bound_func = types.MethodType(func, self)
                setattr(self, operation_id, bound_func)
                logging.info(f"[OpenAPI Plugin] Successfully created and bound function: {operation_id}")
        
        logging.info(f"[OpenAPI Plugin] Finished creating dynamic functions")

    def get_kernel_plugin(self, plugin_name="openapi_plugin"):
        """
        Create and return a properly configured KernelPlugin with all dynamic functions.
        
        Returns:
            KernelPlugin: A kernel plugin with all API operations as functions
        """
        from semantic_kernel.functions.kernel_plugin import KernelPlugin
        import logging
        
        logging.info(f"[OpenAPI Plugin] Creating kernel plugin for {plugin_name}")
        logging.info(f"[OpenAPI Plugin] Available methods on self: {[m for m in dir(self) if not m.startswith('_') and callable(getattr(self, m))]}")
        
        # Use from_object to create the plugin - this will automatically find all @kernel_function decorated methods
        try:
            plugin = KernelPlugin.from_object(plugin_name, self)
            logging.info(f"[OpenAPI Plugin] Successfully created kernel plugin with {len(plugin.functions)} functions")
            logging.info(f"[OpenAPI Plugin] Functions: {list(plugin.functions.keys())}")
            return plugin
        except Exception as e:
            logging.error(f"[OpenAPI Plugin] Failed to create kernel plugin: {e}")
            import traceback
            logging.error(f"[OpenAPI Plugin] Traceback: {traceback.format_exc()}")
            raise

    def _call_api_operation(self, operation_id: str, path: str, method: str, operation_data: Dict[str, Any], **kwargs) -> Any:
        """Internal method to call a specific API operation."""
        import requests
        import logging
        import datetime
        import time
        
        # Log the function call
        logging.info(f"[OpenAPI Plugin] Calling operation: {operation_id} ({method.upper()} {path})")
        logging.info(f"[OpenAPI Plugin] Parameters: {kwargs}")
        logging.info(f"[OpenAPI Plugin] Base URL: {self.base_url}")
        
        # Track function call for citations
        call_start = time.time()
        
        try:
            # Handle path parameters by replacing placeholders in the path
            final_path = path
            path_params = {}
            query_params = {}
            
            # Extract parameters from operation definition
            parameters = operation_data.get("parameters", [])
            
            for param in parameters:
                param_name = param.get("name")
                param_in = param.get("in", "query")
                
                if param_name in kwargs:
                    if param_in == "path":
                        # Replace path parameter placeholders
                        final_path = final_path.replace(f"{{{param_name}}}", str(kwargs[param_name]))
                        path_params[param_name] = kwargs[param_name]
                        logging.info(f"[OpenAPI Plugin] Set path parameter {param_name}={kwargs[param_name]}")
                    elif param_in == "query":
                        # Add to query parameters
                        query_params[param_name] = kwargs[param_name]
                        logging.info(f"[OpenAPI Plugin] Set query parameter {param_name}={kwargs[param_name]}")
            
            # Build the full URL
            full_url = f"{self.base_url}{final_path}"
            logging.info(f"[OpenAPI Plugin] Final URL: {full_url}")
            
            # Set up headers
            headers = {"Accept": "application/json", "User-Agent": "SimpleChat-OpenAPI-Plugin/1.0"}
            
            # Add authentication if configured
            if self.auth:
                auth_type = self.auth.get("type", "none")
                if auth_type == "api_key":
                    key_location = self.auth.get("location", "header")
                    key_name = self.auth.get("name", "X-API-Key")
                    key_value = self.auth.get("value", "")
                    
                    if key_location == "header":
                        headers[key_name] = key_value
                    elif key_location == "query":
                        query_params[key_name] = key_value
                elif auth_type == "bearer":
                    headers["Authorization"] = f"Bearer {self.auth.get('token', '')}"
                elif auth_type == "basic":
                    import base64
                    username = self.auth.get("username", "")
                    password = self.auth.get("password", "")
                    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
                    headers["Authorization"] = f"Basic {credentials}"
                    
                logging.info(f"[OpenAPI Plugin] Applied authentication type: {auth_type}")
            
            # Make the HTTP request
            logging.info(f"[OpenAPI Plugin] Making {method.upper()} request to {full_url}")
            logging.info(f"[OpenAPI Plugin] Headers: {headers}")
            logging.info(f"[OpenAPI Plugin] Query params: {query_params}")
            
            if method.lower() == 'get':
                response = requests.get(full_url, headers=headers, params=query_params, timeout=30)
            elif method.lower() == 'post':
                response = requests.post(full_url, headers=headers, params=query_params, json=kwargs, timeout=30)
            elif method.lower() == 'put':
                response = requests.put(full_url, headers=headers, params=query_params, json=kwargs, timeout=30)
            elif method.lower() == 'delete':
                response = requests.delete(full_url, headers=headers, params=query_params, timeout=30)
            elif method.lower() == 'patch':
                response = requests.patch(full_url, headers=headers, params=query_params, json=kwargs, timeout=30)
            else:
                # Default to GET for unknown methods
                response = requests.get(full_url, headers=headers, params=query_params, timeout=30)
            
            logging.info(f"[OpenAPI Plugin] Response status: {response.status_code}")
            logging.info(f"[OpenAPI Plugin] Response headers: {dict(response.headers)}")
            
            # Check if request was successful
            if response.status_code == 200:
                try:
                    result = response.json()
                    logging.info(f"[OpenAPI Plugin] Successfully called {operation_id} - JSON response received")
                    if isinstance(result, dict) and len(result) < 10:
                        logging.info(f"[OpenAPI Plugin] Response preview: {result}")
                    elif isinstance(result, list) and len(result) < 5:
                        logging.info(f"[OpenAPI Plugin] Response preview (list): {result}")
                    else:
                        logging.info(f"[OpenAPI Plugin] Response type: {type(result)}, length: {len(result) if hasattr(result, '__len__') else 'unknown'}")
                    
                    # Track successful function call for citations
                    self._track_function_call(operation_id, kwargs, result, call_start, full_url)
                    
                    return result
                except ValueError as json_error:
                    # If not JSON, return text
                    result = {"response": response.text, "status_code": response.status_code}
                    logging.info(f"[OpenAPI Plugin] Non-JSON response received: {response.text[:200]}...")
                    self._track_function_call(operation_id, kwargs, result, call_start, full_url)
                    return result
            else:
                logging.warning(f"[OpenAPI Plugin] HTTP error {response.status_code} for {operation_id}")
                logging.warning(f"[OpenAPI Plugin] Error response: {response.text[:500]}")
                error_result = {
                    "error": f"HTTP {response.status_code}",
                    "operation_id": operation_id,
                    "status_code": response.status_code,
                    "response": response.text[:500],  # First 500 chars
                    "url": full_url,
                    "method": method.upper()
                }
                self._track_function_call(operation_id, kwargs, error_result, call_start, full_url)
                return error_result
                
        except requests.exceptions.RequestException as req_error:
            logging.error(f"[OpenAPI Plugin] Request error for {operation_id}: {req_error}")
            error_result = {
                "error": f"Request failed: {str(req_error)}",
                "operation_id": operation_id,
                "path": path,
                "method": method.upper(),
                "parameters": kwargs,
                "base_url": self.base_url,
                "url": full_url if 'full_url' in locals() else "unknown",
                "status": "request_error"
            }
            self._track_function_call(operation_id, kwargs, error_result, call_start, full_url if 'full_url' in locals() else "unknown")
            return error_result
        except Exception as e:
            logging.error(f"[OpenAPI Plugin] Unexpected error calling {operation_id}: {e}")
            import traceback
            logging.error(f"[OpenAPI Plugin] Traceback: {traceback.format_exc()}")
            error_result = {
                "error": f"Unexpected error: {str(e)}",
                "operation_id": operation_id,
                "path": path,
                "method": method.upper(),
                "parameters": kwargs,
                "base_url": self.base_url,
                "status": "unexpected_error"
            }
            self._track_function_call(operation_id, kwargs, error_result, call_start, full_url if 'full_url' in locals() else "unknown")
            return error_result
    
    def _track_function_call(self, operation_id: str, parameters: dict, result: dict, call_start: float, url: str):
        """Track function call for citation purposes with enhanced details."""
        duration = time.time() - call_start
        
        # Extract key information from the result for better citation display
        result_summary = str(result)
        if isinstance(result, dict):
            if 'error' in result:
                result_summary = f"Error: {result['error']}"
            elif 'response' in result:
                response_data = result['response']
                if isinstance(response_data, str) and len(response_data) > 100:
                    result_summary = f"Response ({len(response_data)} chars): {response_data[:100]}..."
                else:
                    result_summary = f"Response: {response_data}"
            elif 'status_code' in result:
                result_summary = f"HTTP {result['status_code']}: {str(result)[:200]}..."
        
        # Format parameters for better display
        params_summary = ""
        if parameters:
            param_parts = []
            for key, value in parameters.items():
                if isinstance(value, str) and len(value) > 50:
                    param_parts.append(f"{key}: {value[:50]}...")
                else:
                    param_parts.append(f"{key}: {value}")
            params_summary = ", ".join(param_parts[:3])  # Limit to first 3 params
            if len(parameters) > 3:
                params_summary += f" (and {len(parameters) - 3} more)"
        
        call_data = {
            "name": f"OpenAPI.{operation_id}",
            "arguments": parameters,
            "result": result,
            "start_time": call_start,
            "end_time": time.time(),
            "url": url,
            # Enhanced display information
            "operation_id": operation_id,
            "duration_ms": round(duration * 1000, 2),
            "result_summary": result_summary[:300],  # Truncate for display
            "params_summary": params_summary,
            "base_url": self.base_url
        }
        self.function_calls.append(call_data)
        logging.info(f"[OpenAPI Plugin] Tracked function call: {operation_id} ({duration:.3f}s) -> {url}")

    @plugin_function_logger("OpenApiPlugin")
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
            Dict containing the operation result
        """
        import logging
        
        logging.info(f"[OpenAPI Plugin] call_operation called with operation_id: {operation_id}, kwargs: {kwargs}")
        
        # Find the operation in the spec
        operation_found = False
        operation_data = None
        operation_path = None
        operation_method = None
        
        for path, ops in self.openapi.get("paths", {}).items():
            for method, op in ops.items():
                if op.get("operationId") == operation_id:
                    operation_found = True
                    operation_data = op
                    operation_path = path
                    operation_method = method
                    break
            if operation_found:
                break
        
        if not operation_found:
            error_msg = f"Operation '{operation_id}' not found in OpenAPI specification"
            logging.error(f"[OpenAPI Plugin] {error_msg}")
            available_ops = [op.get("operationId") for path_ops in self.openapi.get("paths", {}).values() 
                           for op in path_ops.values() if op.get("operationId")]
            logging.error(f"[OpenAPI Plugin] Available operations: {available_ops}")
            raise ValueError(error_msg)
        
        logging.info(f"[OpenAPI Plugin] Found operation {operation_id}: {operation_method.upper()} {operation_path}")
        
        # Call the actual API operation
        return self._call_api_operation(operation_id, operation_path, operation_method, operation_data, **kwargs)