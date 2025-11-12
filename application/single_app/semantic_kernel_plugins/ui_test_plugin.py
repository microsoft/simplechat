"""
UI Test Plugin for Semantic Kernel
- Provides demonstration methods for UI testing (greeting, farewell, manifest retrieval)
- Useful for testing plugin integration and UI workflows
- Does not interact with external systems or databases
"""

import json
import logging
from typing import Dict, Any, List, Optional, Union
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel.functions import kernel_function
from functions_appinsights import log_event
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger
from functions_debug import debug_print

# Helper class to wrap results with metadata
class ResultWithMetadata:
    def __init__(self, data, metadata):
        self.data = data
        self.metadata = metadata
    def __str__(self):
        return str(self.data)
    def __repr__(self):
        return f"ResultWithMetadata(data={self.data!r}, metadata={self.metadata!r})"

class UITestPlugin(BasePlugin):
    def __init__(self, manifest: Dict[str, Any]):
        super().__init__(manifest)

    @property
    def display_name(self) -> str:
        return "UI Test Plugin"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "name": "ui_test_plugin",
            "type": "ui_test",
            "description": "A plugin for UI testing and demonstration purposes.",
            "methods": [
                {
                    "name": "greet_user",
                    "description": "Returns a greeting message.",
                    "parameters": [
                        {"name": "name", "type": "str", "description": "Name to greet.", "required": True}
                    ],
                    "returns": {"type": "str", "description": "Greeting message."}
                },
                {
                    "name": "farewell_user",
                    "description": "Returns a farewell message.",
                    "parameters": [
                        {"name": "name", "type": "str", "description": "Name to bid farewell.", "required": True}
                    ],
                    "returns": {"type": "str", "description": "Farewell message."}
                },
                {
                    "name": "get_manifest",
                    "description": "Returns the plugin manifest.",
                    "parameters": [],
                    "returns": {"type": "str", "description": "Manifest as JSON string."}
                }
            ]
        }

    @kernel_function(description="A function that returns a greeting message.")
    @plugin_function_logger("UITestPlugin")
    def greet_user(self, name: str) -> str:
        return f"Hello, {name}!"

    @kernel_function(description="A function that returns a farewell message.")
    @plugin_function_logger("UITestPlugin")
    def farewell_user(self, name: str) -> str:
        return f"Goodbye, {name}!"

    @kernel_function(description="A function that returns the plugin manifest")
    @plugin_function_logger("UITestPlugin")
    def get_manifest(self) -> str:
        return json.dumps(self.manifest, indent=2)