"""
OpenAPI Semantic Kernel Plugin

This plugin exposes all OpenAPI endpoints as Semantic Kernel plugin functions.
"""

import os
import yaml
from typing import Dict, Any, List, Optional
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel.functions import kernel_function

class OpenApiPlugin(BasePlugin):
    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        # Accept manifest for dynamic config, else use default path
        self.manifest = manifest or {}
        openapi_path = self.manifest.get("openapi_path")
        if not openapi_path:
            openapi_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "../../..", "artifacts/open_api/openapi.yaml")
            )
        with open(openapi_path, "r", encoding="utf-8") as f:
            self.openapi = yaml.safe_load(f)
        # Optionally store endpoint/auth for future HTTP calls
        self.endpoint = self.manifest.get("endpoint")
        self.auth = self.manifest.get("auth", {})
        self._metadata = self._generate_metadata()

    @property
    def metadata(self) -> Dict[str, Any]:
        info = self.openapi.get("info", {})
        return {
            "name": info.get("title", "OpenAPIPlugin"),
            "type": "openapi",
            "description": info.get("description", ""),
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

    @kernel_function(
        description="Call any OpenAPI operation by operation_id and parameters. Example: call_operation(operation_id='post_chat', message='Hello')"
    )
    def call_operation(self, operation_id: str, **kwargs) -> Any:
        """
        Generic OpenAPI operation caller.
        This is a stub. Actual HTTP call logic would go here.
        """
        return {
            "operation_id": operation_id,
            "parameters": kwargs
        }