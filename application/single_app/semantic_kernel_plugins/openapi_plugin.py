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
from functions_debug import debug_print

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

    def _resolve_ref(self, ref_obj: Any) -> Any:
        """Resolve $ref references in OpenAPI specification objects."""
        if isinstance(ref_obj, dict) and "$ref" in ref_obj:
            ref_path = ref_obj["$ref"]
            if ref_path.startswith("#/"):
                # Handle internal references like #/components/parameters/fields
                path_parts = ref_path[2:].split("/")  # Remove #/ prefix
                current = self.openapi
                try:
                    for part in path_parts:
                        current = current[part]
                    return current
                except (KeyError, TypeError):
                    logging.warning(f"[OpenAPI Plugin] Failed to resolve reference: {ref_path}")
                    return ref_obj
            else:
                logging.warning(f"[OpenAPI Plugin] External references not supported: {ref_path}")
                return ref_obj
        elif isinstance(ref_obj, list):
            # Recursively resolve references in lists
            return [self._resolve_ref(item) for item in ref_obj]
        elif isinstance(ref_obj, dict):
            # Recursively resolve references in dictionaries
            resolved = {}
            for key, value in ref_obj.items():
                resolved[key] = self._resolve_ref(value)
            return resolved
        else:
            # Return non-dict/list objects as-is
            return ref_obj

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
                # Path/query parameters - resolve $ref references first
                raw_parameters = op.get("parameters", [])
                resolved_parameters = self._resolve_ref(raw_parameters)
                for param in resolved_parameters:
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
        description="List all available API operations with their exact operation IDs and descriptions. Use this to see what operations you can call."
    )
    def list_available_apis(self) -> str:
        """List all available API operation names with exact operation IDs."""
        operations = [m["name"] for m in self._metadata["methods"]]
        api_info = self.openapi.get("info", {})
        api_title = api_info.get("title", "API")
        api_description = api_info.get("description", "")
        
        result = f"Available API operations for {api_title}:\n"
        if api_description:
            result += f"Description: {api_description}\n"
            result += f"**Warning**: If you want to be notified about changes in advance please join our [Slack channel](https://join.slack.com/t/mermade/shared_invite/zt-g78g7xir-MLE_CTCcXCdfJfG3CJe9qA).\n"
            result += f"Client sample: [[Demo]](https://apis.guru/simple-ui) [[Repo]](https://github.com/APIs-guru/simple-ui)\n\n"
        
        result += "Operations:\n"
        for i, op_name in enumerate(operations, 1):
            # Find the operation details
            op_details = next((m for m in self._metadata["methods"] if m["name"] == op_name), {})
            description = op_details.get("description", "")
            result += f"{i}. **{op_name}** - {description}\n"
            if op_name == "getMetrics":
                result += f"   Use this for API directory metrics and statistics\n"
            elif op_name == "listAPIs":
                result += f"   Use this to list all APIs in the directory\n"
        
        result += f"\n**Important**: Use exact operation names when calling operations. For example, use 'getMetrics' not 'getAppMetrics'."
        
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
                    # Extract parameters from OpenAPI spec and resolve $ref references
                    raw_parameters = op_data.get("parameters", [])
                    parameters = self._resolve_ref(raw_parameters)
                    
                    # Create function signature based on OpenAPI parameters
                    required_params = []
                    optional_params = []
                    param_descriptions = {}
                    
                    for param in parameters:
                        param_name = param.get("name", "")
                        param_required = param.get("required", False)
                        param_description = param.get("description", "")
                        param_type = param.get("schema", {}).get("type", "string") if "schema" in param else "string"
                        
                        # Convert kebab-case to snake_case for Python function parameters
                        python_param_name = param_name.replace("-", "_")
                        
                        param_descriptions[python_param_name] = {
                            "description": param_description,
                            "type": param_type,
                            "original_name": param_name,
                            "required": param_required
                        }
                        
                        if param_required:
                            required_params.append(python_param_name)
                        else:
                            optional_params.append(python_param_name)
                    
                    # Create the function dynamically with proper parameters
                    def operation_function(self, **kwargs):
                        # Map Python parameter names back to OpenAPI parameter names
                        mapped_kwargs = {}
                        for python_name, value in kwargs.items():
                            if python_name in param_descriptions:
                                original_name = param_descriptions[python_name]["original_name"]
                                mapped_kwargs[original_name] = value
                                logging.info(f"[OpenAPI Plugin] Mapped parameter {python_name} -> {original_name}: {value}")
                            else:
                                mapped_kwargs[python_name] = value
                        
                        return self._call_api_operation(op_id, op_path, op_method, op_data, **mapped_kwargs)
                    
                    # Set the function name to the operation ID
                    operation_function.__name__ = op_id
                    operation_function.__qualname__ = f"OpenApiPlugin.{op_id}"
                    
                    # Get operation description
                    description = op_data.get("description", op_data.get("summary", f"{op_method.upper()} {op_path}"))
                    
                    # Add parameter information to description
                    if required_params or optional_params:
                        description += "\n\nParameters:"
                        for param_name in required_params:
                            param_info = param_descriptions[param_name]
                            description += f"\n- {param_name} (required): {param_info['description']}"
                        for param_name in optional_params:
                            param_info = param_descriptions[param_name]
                            description += f"\n- {param_name} (optional): {param_info['description']}"
                    
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

    def _to_camel_case(self, name: str) -> str:
        """Convert kebab-case or snake_case to camelCase."""
        # Split on both - and _
        parts = name.replace('-', '_').split('_')
        if len(parts) <= 1:
            return name
        return parts[0] + ''.join(word.capitalize() for word in parts[1:])
    
    def _to_pascal_case(self, name: str) -> str:
        """Convert kebab-case or snake_case to PascalCase."""
        # Split on both - and _
        parts = name.replace('-', '_').split('_')
        return ''.join(word.capitalize() for word in parts)
    
    def _to_snake_case(self, name: str) -> str:
        """Convert kebab-case or camelCase to snake_case."""
        import re
        # Handle camelCase/PascalCase
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        s2 = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1)
        # Handle kebab-case
        return s2.replace('-', '_').lower()
    
    def _to_kebab_case(self, name: str) -> str:
        """Convert snake_case or camelCase to kebab-case."""
        return self._to_snake_case(name).replace('_', '-')
    
    def _get_name_variations(self, name: str) -> list:
        """Get all possible name variations for a parameter."""
        variations = []
        
        # Original name
        variations.append(name)
        
        # Basic transformations
        snake_case = self._to_snake_case(name)
        kebab_case = self._to_kebab_case(name)
        camel_case = self._to_camel_case(name)
        pascal_case = self._to_pascal_case(name)
        
        variations.extend([snake_case, kebab_case, camel_case, pascal_case])
        
        # Common variations
        if '-' in name:
            variations.append(name.replace('-', '_'))  # kebab to snake
            variations.append(name.replace('-', ''))   # remove dashes
        
        if '_' in name:
            variations.append(name.replace('_', '-'))  # snake to kebab
            variations.append(name.replace('_', ''))   # remove underscores
        
        # Common abbreviations and expansions
        common_mappings = {
            'id': ['Id', 'ID', 'identifier'],
            'url': ['URL', 'Url', 'uri', 'URI'],
            'api': ['API', 'Api'],
            'http': ['HTTP', 'Http'],
            'json': ['JSON', 'Json'],
            'xml': ['XML', 'Xml'],
            'max': ['maximum', 'Maximum'],
            'min': ['minimum', 'Minimum'],
            'num': ['number', 'Number'],
            'src': ['source', 'Source'],
            'dst': ['destination', 'Destination'],
            'auth': ['authentication', 'Authentication'],
            'config': ['configuration', 'Configuration'],
            'info': ['information', 'Information'],
            'desc': ['description', 'Description'],
            'temp': ['temporary', 'Temporary', 'template', 'Template'],
            'lang': ['language', 'Language'],
            'loc': ['location', 'Location'],
            'addr': ['address', 'Address'],
            'req': ['request', 'Request'],
            'res': ['response', 'Response'],
            'img': ['image', 'Image'],
            'pic': ['picture', 'Picture'],
            'msg': ['message', 'Message'],
            'val': ['value', 'Value'],
            'var': ['variable', 'Variable'],
            'opt': ['option', 'Option', 'optional', 'Optional'],
            'param': ['parameter', 'Parameter'],
            'arg': ['argument', 'Argument'],
            'elem': ['element', 'Element'],
            'obj': ['object', 'Object'],
            'str': ['string', 'String'],
            'int': ['integer', 'Integer'],
            'bool': ['boolean', 'Boolean'],
            'arr': ['array', 'Array'],
            'list': ['List'],
            'dict': ['dictionary', 'Dictionary'],
            'map': ['mapping', 'Mapping'],
            'set': ['Set'],
            'type': ['Type'],
            'format': ['Format'],
            'sort': ['sorting', 'Sorting'],
            'order': ['ordering', 'Ordering'],
            'dir': ['direction', 'Direction', 'directory', 'Directory'],
            'path': ['Path'],
            'file': ['File'],
            'ext': ['extension', 'Extension'],
            'size': ['Size'],
            'len': ['length', 'Length'],
            'count': ['Count'],
            'total': ['Total'],
            'sum': ['Sum'],
            'avg': ['average', 'Average'],
            'std': ['standard', 'Standard'],
            'dev': ['development', 'Development', 'device', 'Device'],
            'env': ['environment', 'Environment'],
            'sys': ['system', 'System'],
            'app': ['application', 'Application'],
            'svc': ['service', 'Service'],
            'srv': ['server', 'Server'],
            'client': ['Client'],
            'host': ['Host'],
            'port': ['Port'],
            'proto': ['protocol', 'Protocol'],
            'scheme': ['Scheme'],
            'user': ['User'],
            'pass': ['password', 'Password'],
            'key': ['Key'],
            'token': ['Token'],
            'secret': ['Secret'],
            'hash': ['Hash'],
            'code': ['Code'],
            'status': ['Status'],
            'state': ['State'],
            'flag': ['Flag'],
            'enable': ['enabled', 'Enabled'],
            'disable': ['disabled', 'Disabled'],
            'on': ['enabled', 'Enabled'],
            'off': ['disabled', 'Disabled'],
            'start': ['Start'],
            'stop': ['Stop'],
            'end': ['End'],
            'begin': ['Begin'],
            'init': ['initialize', 'Initialize', 'initial', 'Initial'],
            'final': ['Final'],
            'first': ['First'],
            'last': ['Last'],
            'next': ['Next'],
            'prev': ['previous', 'Previous'],
            'cur': ['current', 'Current'],
            'new': ['New'],
            'old': ['Old'],
            'tmp': ['temporary', 'Temporary'],
            'temp': ['temporary', 'Temporary'],
            'test': ['Test'],
            'demo': ['demonstration', 'Demonstration'],
            'example': ['Example'],
            'sample': ['Sample'],
            'default': ['Default'],
            'custom': ['Custom'],
            'std': ['standard', 'Standard'],
            'spec': ['specification', 'Specification'],
            'ref': ['reference', 'Reference'],
            'src': ['source', 'Source'],
            'target': ['Target'],
            'dest': ['destination', 'Destination'],
            'from': ['From'],
            'to': ['To'],
            'in': ['In', 'input', 'Input'],
            'out': ['Out', 'output', 'Output'],
            'data': ['Data'],
            'meta': ['metadata', 'Metadata'],
            'attr': ['attribute', 'Attribute'],
            'prop': ['property', 'Property'],
            'field': ['Field'],
            'col': ['column', 'Column'],
            'row': ['Row'],
            'table': ['Table'],
            'db': ['database', 'Database'],
            'sql': ['SQL', 'Sql'],
            'query': ['Query'],
            'cmd': ['command', 'Command'],
            'exec': ['execute', 'Execute'],
            'run': ['Run'],
            'call': ['Call'],
            'invoke': ['Invoke'],
            'trigger': ['Trigger'],
            'handle': ['Handle'],
            'process': ['Process'],
            'proc': ['process', 'Process', 'procedure', 'Procedure'],
            'func': ['function', 'Function'],
            'method': ['Method'],
            'op': ['operation', 'Operation'],
            'action': ['Action'],
            'event': ['Event'],
            'hook': ['Hook'],
            'callback': ['Callback'],
            'handler': ['Handler'],
            'listener': ['Listener'],
            'observer': ['Observer'],
            'watcher': ['Watcher'],
            'monitor': ['Monitor'],
            'tracker': ['Tracker'],
            'logger': ['Logger'],
            'log': ['Log'],
            'debug': ['Debug'],
            'trace': ['Trace'],
            'warn': ['warning', 'Warning'],
            'error': ['Error'],
            'exception': ['Exception'],
            'fail': ['failure', 'Failure'],
            'success': ['Success'],
            'ok': ['OK', 'Ok'],
            'yes': ['Yes'],
            'no': ['No'],
            'true': ['True'],
            'false': ['False'],
            'null': ['Null'],
            'none': ['None'],
            'empty': ['Empty'],
            'blank': ['Blank'],
            'void': ['Void'],
            'any': ['Any'],
            'all': ['All'],
            'some': ['Some'],
            'many': ['Many'],
            'few': ['Few'],
            'single': ['Single'],
            'multi': ['multiple', 'Multiple'],
            'one': ['One'],
            'two': ['Two'],
            'three': ['Three'],
            'four': ['Four'],
            'five': ['Five'],
            'six': ['Six'],
            'seven': ['Seven'],
            'eight': ['Eight'],
            'nine': ['Nine'],
            'ten': ['Ten'],
        }
        
        # Apply common mappings
        name_lower = name.lower()
        for short, expansions in common_mappings.items():
            if short in name_lower:
                for expansion in expansions:
                    # Replace in all case variations
                    for case_variation in [snake_case, kebab_case, camel_case, pascal_case]:
                        if short in case_variation.lower():
                            new_name = case_variation.lower().replace(short, expansion.lower())
                            variations.extend([
                                new_name,
                                self._to_snake_case(new_name),
                                self._to_kebab_case(new_name),
                                self._to_camel_case(new_name),
                                self._to_pascal_case(new_name)
                            ])
        
        # Remove duplicates and empty strings
        return list(set(filter(None, variations)))

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
            raw_parameters = operation_data.get("parameters", [])
            # Resolve $ref references in parameters
            parameters = self._resolve_ref(raw_parameters)
            
            debug_print(f"===== STARTING {operation_id} CALL =====")
            debug_print(f"Received kwargs: {kwargs}")
            
            # Extract parameters from nested kwargs if present
            if 'kwargs' in kwargs and isinstance(kwargs['kwargs'], dict):
                # Merge nested kwargs into top level
                nested_kwargs = kwargs.pop('kwargs')
                kwargs.update(nested_kwargs)
                debug_print(f"Extracted nested kwargs, now have: {kwargs}")
            
            debug_print(f"Operation has {len(parameters)} parameters: {[p.get('name') for p in parameters]}")
            debug_print(f"Base URL: {self.base_url}")
            debug_print(f"Path: {path}")
            
            logging.info(f"[OpenAPI Plugin] Processing parameters for {operation_id}")
            logging.info(f"[OpenAPI Plugin] Received kwargs: {kwargs}")
            logging.info(f"[OpenAPI Plugin] Operation parameters: {[p.get('name') for p in parameters]}")
            
            # Check for missing required parameters and add automatic parameter mapping
            for param in parameters:
                param_name = param.get("name")
                param_required = param.get("required", False)
                
                debug_print(f"Checking required param '{param_name}' (required: {param_required})")
                
                if param_required and param_name not in kwargs:
                    # Try automatic name transformations
                    snake_case_name = param_name.replace('-', '_')
                    camel_case_name = self._to_camel_case(param_name)
                    pascal_case_name = self._to_pascal_case(param_name)
                    
                    debug_print(f"Required param '{param_name}' not found, trying transformations:")
                    debug_print(f"  - snake_case: '{snake_case_name}'")
                    debug_print(f"  - camelCase: '{camel_case_name}'")
                    debug_print(f"  - PascalCase: '{pascal_case_name}'")
                    
                    # Check all possible name variations
                    if snake_case_name in kwargs:
                        kwargs[param_name] = kwargs[snake_case_name]
                        debug_print(f"Mapped {snake_case_name} -> {param_name}: {kwargs[snake_case_name]}")
                        logging.info(f"[OpenAPI Plugin] Mapped {snake_case_name} -> {param_name}: {kwargs[snake_case_name]}")
                    elif camel_case_name in kwargs:
                        kwargs[param_name] = kwargs[camel_case_name]
                        debug_print(f"Mapped {camel_case_name} -> {param_name}: {kwargs[camel_case_name]}")
                        logging.info(f"[OpenAPI Plugin] Mapped {camel_case_name} -> {param_name}: {kwargs[camel_case_name]}")
                    elif pascal_case_name in kwargs:
                        kwargs[param_name] = kwargs[pascal_case_name]
                        debug_print(f"Mapped {pascal_case_name} -> {param_name}: {kwargs[pascal_case_name]}")
                        logging.info(f"[OpenAPI Plugin] Mapped {pascal_case_name} -> {param_name}: {kwargs[pascal_case_name]}")
                    else:
                        # Try additional common variations
                        variations = self._get_name_variations(param_name)
                        mapped = False
                        for variation in variations:
                            if variation in kwargs:
                                kwargs[param_name] = kwargs[variation]
                                debug_print(f"Mapped {variation} -> {param_name}: {kwargs[variation]}")
                                logging.info(f"[OpenAPI Plugin] Mapped {variation} -> {param_name}: {kwargs[variation]}")
                                mapped = True
                                break
                        
                        if not mapped:
                            debug_print(f"WARNING - Required parameter '{param_name}' not found in any name variation!")
                            logging.warning(f"[OpenAPI Plugin] Required parameter {param_name} not found after trying all name variations")
                else:
                    if param_name in kwargs:
                        debug_print(f"Param '{param_name}' found directly")
                    else:
                        debug_print(f"Param '{param_name}' is optional and not provided (OK)")
            
            debug_print(f"After preprocessing, kwargs now: {kwargs}")
            
            for param in parameters:
                param_name = param.get("name")
                param_in = param.get("in", "query")
                param_required = param.get("required", False)
                
                debug_print(f"Processing parameter '{param_name}' (location: {param_in}, required: {param_required})")
                logging.info(f"[OpenAPI Plugin] Processing parameter: {param_name} (location: {param_in}, required: {param_required})")
                
                param_value = None
                
                # Check for exact match first
                if param_name in kwargs:
                    param_value = kwargs[param_name]
                    debug_print(f"Found exact match for '{param_name}': {param_value}")
                    logging.info(f"[OpenAPI Plugin] Found exact match for {param_name}: {param_value}")
                else:
                    # Try universal name transformations
                    variations = self._get_name_variations(param_name)
                    debug_print(f"Trying {len(variations)} name variations for '{param_name}'")
                    
                    param_value = None
                    for variation in variations:
                        if variation in kwargs:
                            param_value = kwargs[variation]
                            debug_print(f"Found variation match '{variation}' -> '{param_name}': {param_value}")
                            logging.info(f"[OpenAPI Plugin] Found variation match {variation} -> {param_name}: {param_value}")
                            break
                    
                    if param_value is None and param_required:
                        debug_print(f"WARNING - Required parameter '{param_name}' not found after trying all variations!")
                        logging.warning(f"[OpenAPI Plugin] Required parameter {param_name} not found after trying all name variations!")
                    elif param_value is None:
                        debug_print(f"Optional parameter '{param_name}' not found (OK)")
                
                if param_value is not None:
                    if param_in == "path":
                        # Replace path parameter placeholders - add safety checks for None values
                        if final_path is not None and param_name is not None:
                            final_path = final_path.replace(f"{{{param_name}}}", str(param_value))
                            path_params[param_name] = param_value
                            debug_print(f"Set path parameter '{param_name}'={param_value}")
                            logging.info(f"[OpenAPI Plugin] Set path parameter {param_name}={param_value}")
                        else:
                            debug_print(f"SAFETY CHECK: final_path={final_path}, param_name={param_name}")
                            logging.warning(f"[OpenAPI Plugin] Safety check failed: final_path={final_path}, param_name={param_name}")
                    elif param_in == "query":
                        # Add to query parameters - add safety check for param_name
                        if param_name is not None:
                            query_params[param_name] = param_value
                            debug_print(f"Set query parameter '{param_name}'={param_value}")
                            logging.info(f"[OpenAPI Plugin] Set query parameter {param_name}={param_value}")
                        else:
                            debug_print(f"SAFETY CHECK: param_name is None for query parameter")
                            logging.warning(f"[OpenAPI Plugin] Safety check failed: param_name is None for query parameter")
                else:
                    debug_print(f"Parameter '{param_name}' has no value - skipping")
            
            # Build the full URL - add safety checks for None values
            if self.base_url is None:
                raise ValueError("base_url is None - cannot construct API URL")
            if final_path is None:
                final_path = ""  # Use empty string if path is None
                debug_print("WARNING: final_path was None, using empty string")
                logging.warning("[OpenAPI Plugin] final_path was None, using empty string")
            
            full_url = f"{self.base_url}{final_path}"
            debug_print(f"Base URL + path: {full_url}")
            debug_print(f"Query params before auth: {query_params}")
            logging.info(f"[OpenAPI Plugin] Final URL: {full_url}")
            
            # Set up headers
            headers = {"Accept": "application/json", "User-Agent": "SimpleChat-OpenAPI-Plugin/1.0"}
            debug_print(f"Initial headers: {headers}")
            
            # Add authentication if configured
            debug_print(f"Auth config: {self.auth}")
            if self.auth:
                auth_type = self.auth.get("type", "none")
                debug_print(f"Auth type: {auth_type}")
                if auth_type == "api_key":
                    key_location = self.auth.get("location", "header")
                    key_name = self.auth.get("name", "X-API-Key")
                    key_value = self.auth.get("value", "")
                    
                    debug_print(f"API key auth - location: {key_location}, name: {key_name}, value: {key_value[:10]}...")
                    
                    if key_location == "header":
                        headers[key_name] = key_value
                        debug_print(f"Added API key to headers")
                    elif key_location == "query":
                        query_params[key_name] = key_value
                        debug_print(f"Added API key to query params")
                elif auth_type == "key":
                    # Handle simplified "key" auth type - auto-detect from OpenAPI spec
                    api_key = self.auth.get("key", "")
                    debug_print(f"Key auth - api_key: {api_key[:10]}...")
                    
                    # Check OpenAPI spec for security schemes
                    if self.openapi and "components" in self.openapi and "securitySchemes" in self.openapi["components"]:
                        security_schemes = self.openapi["components"]["securitySchemes"]
                        debug_print(f"Found security schemes: {list(security_schemes.keys())}")
                        
                        # Look for apiKey scheme (query parameter)
                        if "apiKey" in security_schemes:
                            scheme = security_schemes["apiKey"]
                            debug_print(f"Found apiKey scheme: {scheme}")
                            if scheme.get("type") == "apiKey" and scheme.get("in") == "query":
                                key_name = scheme.get("name", "api-key")
                                query_params[key_name] = api_key
                                debug_print(f"Added query parameter auth: {key_name}={api_key[:10]}...")
                                logging.info(f"[OpenAPI Plugin] Using query parameter auth: {key_name}")
                        
                        # Look for headerApiKey scheme as fallback
                        elif "headerApiKey" in security_schemes:
                            scheme = security_schemes["headerApiKey"]
                            debug_print(f"Found headerApiKey scheme: {scheme}")
                            if scheme.get("type") == "apiKey" and scheme.get("in") == "header":
                                key_name = scheme.get("name", "x-api-key")
                                headers[key_name] = api_key
                                debug_print(f"Added header auth: {key_name}={api_key[:10]}...")
                                logging.info(f"[OpenAPI Plugin] Using header auth: {key_name}")
                        else:
                            debug_print(f"No matching security scheme found!")
                            # Fallback if no security schemes found
                            if api_key and not any(k in query_params for k in ["api-key", "apikey"]) and not any(k.lower() in [h.lower() for h in headers.keys()] for k in ["x-api-key", "api-key"]):
                                # Default to query parameter
                                query_params["api-key"] = api_key
                                debug_print(f"Using fallback query parameter auth: api-key={api_key[:10]}...")
                                logging.info(f"[OpenAPI Plugin] Using fallback query parameter auth: api-key")
                    else:
                        debug_print(f"No security schemes found in OpenAPI spec")
                        # Fallback if no security schemes found
                        if api_key and not any(k in query_params for k in ["api-key", "apikey"]) and not any(k.lower() in [h.lower() for h in headers.keys()] for k in ["x-api-key", "api-key"]):
                            # Default to query parameter
                            query_params["api-key"] = api_key
                            debug_print(f"Using fallback query parameter auth: api-key={api_key[:10]}...")
                            logging.info(f"[OpenAPI Plugin] Using fallback query parameter auth: api-key")
                elif auth_type == "bearer":
                    token = self.auth.get("token", "")
                    headers["Authorization"] = f"Bearer {token}"
                    debug_print(f"Added bearer auth: {token[:10]}...")
                elif auth_type == "basic":
                    import base64
                    username = self.auth.get("username", "")
                    password = self.auth.get("password", "")
                    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
                    headers["Authorization"] = f"Basic {credentials}"
                    debug_print(f"Added basic auth")
                else:
                    debug_print(f"Unknown auth type: {auth_type}")
                    
                logging.info(f"[OpenAPI Plugin] Applied authentication type: {auth_type}")
            else:
                debug_print(f"No authentication configured")
            
            debug_print(f"Final query params: {query_params}")
            debug_print(f"Final headers: {headers}")
            
            # Make the HTTP request
            debug_print(f"About to make {method.upper()} request")
            debug_print(f"URL: {full_url}")
            debug_print(f"Headers: {headers}")
            debug_print(f"Query params: {query_params}")
            logging.info(f"[OpenAPI Plugin] Making {method.upper()} request to {full_url}")
            logging.info(f"[OpenAPI Plugin] Headers: {headers}")
            logging.info(f"[OpenAPI Plugin] Query params: {query_params}")
            
            if method.lower() == 'get':
                response = requests.get(full_url, headers=headers, params=query_params, timeout=30)
                # Log the actual URL that was requested
                debug_print(f"Actual GET request URL: {response.url}")
                debug_print(f"Response status: {response.status_code}")
                logging.info(f"[OpenAPI Plugin] Actual GET request URL: {response.url}")
            elif method.lower() == 'post':
                response = requests.post(full_url, headers=headers, params=query_params, json=kwargs, timeout=30)
                logging.info(f"[OpenAPI Plugin] Actual POST request URL: {response.url}")
            elif method.lower() == 'put':
                response = requests.put(full_url, headers=headers, params=query_params, json=kwargs, timeout=30)
                logging.info(f"[OpenAPI Plugin] Actual PUT request URL: {response.url}")
            elif method.lower() == 'delete':
                response = requests.delete(full_url, headers=headers, params=query_params, timeout=30)
                logging.info(f"[OpenAPI Plugin] Actual DELETE request URL: {response.url}")
            elif method.lower() == 'patch':
                response = requests.patch(full_url, headers=headers, params=query_params, json=kwargs, timeout=30)
                logging.info(f"[OpenAPI Plugin] Actual PATCH request URL: {response.url}")
            else:
                # Default to GET for unknown methods
                response = requests.get(full_url, headers=headers, params=query_params, timeout=30)
                logging.info(f"[OpenAPI Plugin] Actual GET request URL: {response.url}")
            
            debug_print(f"Response status: {response.status_code}")
            debug_print(f"Response headers: {dict(response.headers)}")
            logging.info(f"[OpenAPI Plugin] Response status: {response.status_code}")
            logging.info(f"[OpenAPI Plugin] Response headers: {dict(response.headers)}")
            
            # Check if request was successful
            if response.status_code == 200:
                debug_print(f"SUCCESS - Status 200")
                try:
                    result = response.json()
                    debug_print(f"Successfully parsed JSON response")
                    
                    # Check response size and truncate if too large to prevent context overflow
                    result_str = str(result)
                    result_size = len(result_str)
                    MAX_RESPONSE_SIZE = 100000  # Increased to ~100k characters for better news coverage
                    
                    if result_size > MAX_RESPONSE_SIZE:
                        debug_print(f"Response too large ({result_size} chars), truncating to {MAX_RESPONSE_SIZE} chars")
                        logging.warning(f"[OpenAPI Plugin] Large response ({result_size} chars) truncated to prevent context overflow")
                        
                        # If it's a list, take more items for news APIs
                        if isinstance(result, list) and len(result) > 10:
                            truncated_result = {
                                "truncated": True,
                                "original_count": len(result),
                                "showing_first": 10,
                                "data": result[:10],
                                "note": f"Response truncated - showing first 10 of {len(result)} items. Use more specific parameters to filter results.",
                                "suggestion": "Try adding filters like date, category, or country to reduce response size"
                            }
                            result = truncated_result
                        # If it's a dict with a list property, truncate the list more intelligently
                        elif isinstance(result, dict):
                            # Create a copy to avoid "dictionary changed size during iteration" error
                            result_copy = result.copy()
                            for key, value in result_copy.items():
                                if isinstance(value, list) and len(value) > 10:
                                    result[key] = value[:10]
                                    result[f"{key}_truncated"] = True
                                    result[f"{key}_original_count"] = len(value)
                            result["truncation_note"] = f"Large arrays truncated to first 10 items to prevent context overflow (original size: {result_size} chars)"
                            result["available_data"] = f"Showing 10 items from available {len(value) if 'value' in locals() else 'many'} items"
                        # If still too large, create a summary with more detail
                        if len(str(result)) > MAX_RESPONSE_SIZE:
                            result = {
                                "truncated": True,
                                "original_size_chars": result_size,
                                "summary": f"Response contains data but is too large ({result_size} chars) for context window",
                                "recommendation": "Use API parameters to filter results (e.g., date range, category, limit)",
                                "note": "The API returned valid data, but it needs to be filtered to be usable",
                                "data_available": True
                            }
                    
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
                    debug_print(f"JSON parsing error: {json_error}")
                    error_msg = f"Failed to parse JSON response from {operation_id}: {json_error}"
                    logging.error(f"[OpenAPI Plugin] {error_msg}")
                    
                    # Return raw text as fallback
                    raw_text = response.text
                    debug_print(f"Returning raw text: {raw_text[:200]}...")
                    return {"error": "JSON parse error", "raw_response": raw_text}
            else:
                debug_print(f"ERROR - Status {response.status_code}")
                error_response = response.text
                debug_print(f"Error response: {error_response}")
                
                # Create error result
                error_result = {
                    "error": f"HTTP {response.status_code}",
                    "status_code": response.status_code,
                    "response": error_response,
                    "url": response.url,
                    "method": method.upper(),
                    "operation_id": operation_id
                }
                
                debug_print(f"Returning error result: {error_result}")
                logging.error(f"[OpenAPI Plugin] HTTP {response.status_code} error from {operation_id}: {error_response}")
                
                return error_result
                
        except requests.exceptions.RequestException as req_error:
            debug_print(f"Request exception: {req_error}")
            logging.error(f"[OpenAPI Plugin] Request error for {operation_id}: {req_error}")
            error_result = {
                "error": f"Request failed: {str(req_error)}",
                "operation_id": operation_id,
                "path": path,
                "method": method.upper(),
                "parameters": kwargs,
                "base_url": self.base_url,
                "url": full_url if 'full_url' in locals() else "unknown",
            }
            return error_result
        except Exception as e:
            debug_print(f"General exception: {e}")
            logging.error(f"[OpenAPI Plugin] Unexpected error in {operation_id}: {e}")
            error_result = {
                "error": f"Unexpected error: {str(e)}",
                "operation_id": operation_id,
                "exception_type": type(e).__name__
            }
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
        
        # Try exact match first
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
        
        # If not found, try common operation name variations
        if not operation_found:
            available_ops = [op.get("operationId") for path_ops in self.openapi.get("paths", {}).values() 
                           for op in path_ops.values() if op.get("operationId")]
            
            # Try removing common prefixes/suffixes
            variations = [
                operation_id.replace("getApp", "get"),  # getAppMetrics -> getMetrics
                operation_id.replace("App", ""),        # getAppMetrics -> getMetrics
                operation_id.replace("get", ""),        # getMetrics -> Metrics
                operation_id.lower(),                   # Case insensitive
                operation_id.capitalize(),              # First letter caps
            ]
            
            # Try fuzzy matching
            for variation in variations:
                for available_op in available_ops:
                    if available_op and (variation == available_op or 
                                       variation.lower() == available_op.lower() or
                                       available_op.endswith(variation) or
                                       variation in available_op.lower()):
                        logging.info(f"[OpenAPI Plugin] Found fuzzy match: '{operation_id}' -> '{available_op}'")
                        operation_id = available_op  # Update to use the correct operation ID
                        
                        # Find the matched operation
                        for path, ops in self.openapi.get("paths", {}).items():
                            for method, op in ops.items():
                                if op.get("operationId") == available_op:
                                    operation_found = True
                                    operation_data = op
                                    operation_path = path
                                    operation_method = method
                                    break
                            if operation_found:
                                break
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