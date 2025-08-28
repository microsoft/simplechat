from typing import Dict, Any, List
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel.functions import kernel_function
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger
import requests
from azure.identity import DefaultAzureCredential

class AzureFunctionPlugin(BasePlugin):
    def __init__(self, manifest: Dict[str, Any]):
        self.manifest = manifest
        self.endpoint = manifest.get('endpoint')
        self.key = manifest.get('auth', {}).get('key')
        self.auth_type = manifest.get('auth', {}).get('type', 'key')
        self._metadata = manifest.get('metadata', {})
        if not self.endpoint or not self.auth_type:
            raise ValueError("AzureFunctionPlugin requires 'endpoint' and 'auth.type' in the manifest.")
        if self.auth_type == 'identity':
            self.credential = DefaultAzureCredential()
        elif self.auth_type == 'key':
            if not self.key:
                raise ValueError("AzureFunctionPlugin requires 'auth.key' when using key authentication.")
            self.credential = None
        else:
            raise ValueError(f"Unsupported auth.type: {self.auth_type}")

    @property
    def display_name(self) -> str:
        return "Azure Function"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "name": self.manifest.get("name", "azure_function_plugin"),
            "type": "azure_function",
            "description": "Plugin for calling an Azure Function via HTTP POST or GET using function key or managed identity authentication. Use this to trigger serverless logic or workflows in Azure Functions.",
            "methods": [
                {
                    "name": "call_function_post",
                    "description": "Call the Azure Function using HTTP POST.",
                    "parameters": [
                        {"name": "payload", "type": "dict", "description": "JSON payload to send in the POST request.", "required": True}
                    ],
                    "returns": {"type": "dict", "description": "Response from the Azure Function as a JSON object."}
                },
                {
                    "name": "call_function_get",
                    "description": "Call the Azure Function using HTTP GET.",
                    "parameters": [
                        {"name": "params", "type": "dict", "description": "Query parameters for the GET request.", "required": False}
                    ],
                    "returns": {"type": "dict", "description": "Response from the Azure Function as a JSON object."}
                }
            ]
        }

    def get_functions(self) -> List[str]:
        return ["call_function_post", "call_function_get"]

    @plugin_function_logger("AzureFunctionPlugin")
    @kernel_function(description="Call the Azure Function using HTTP POST.")
    def call_function_post(self, payload: dict) -> dict:
        url = self.endpoint
        headers = {}
        if self.auth_type == 'identity':
            token = self.credential.get_token("https://management.azure.com/.default").token
            headers["Authorization"] = f"Bearer {token}"
        elif self.auth_type == 'key':
            if '?' in url:
                url += f"&code={self.key}"
            else:
                url += f"?code={self.key}"
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()

    @plugin_function_logger("AzureFunctionPlugin")
    @kernel_function(description="Call the Azure Function using HTTP GET.")
    def call_function_get(self, params: dict = None) -> dict:
        url = self.endpoint
        headers = {}
        if self.auth_type == 'identity':
            token = self.credential.get_token("https://management.azure.com/.default").token
            headers["Authorization"] = f"Bearer {token}"
        elif self.auth_type == 'key':
            if '?' in url:
                url += f"&code={self.key}"
            else:
                url += f"?code={self.key}"
        response = requests.get(url, params=params or {}, headers=headers)
        response.raise_for_status()
        return response.json()
