import mimetypes, base64
from typing import Dict, Any, List, Optional
from semantic_kernel_plugins.base_plugin import BasePlugin
from azure.storage.blob import BlobServiceClient
from semantic_kernel.functions import kernel_function
from azure.identity import DefaultAzureCredential
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger

class BlobStoragePlugin(BasePlugin):
    def __init__(self, manifest: Dict[str, Any]):
        super().__init__(manifest)
        self.manifest = manifest
        self.endpoint = manifest.get('endpoint')
        self.key = manifest.get('auth', {}).get('key')
        self.auth_type = manifest.get('auth', {}).get('type', 'key')
        self._metadata = manifest.get('metadata', {})
        if not self.endpoint or not self.auth_type:
            raise ValueError("BlobStoragePlugin requires 'endpoint' and 'auth.type' in the manifest.")
        if self.auth_type == 'identity':
            self.service_client = BlobServiceClient(account_url=self.endpoint, credential=DefaultAzureCredential())
        elif self.auth_type == 'key':
            if not self.key:
                raise ValueError("BlobStoragePlugin requires 'auth.key' when using key authentication.")
            self.service_client = BlobServiceClient(account_url=self.endpoint, credential=self.key)
        else:
            raise ValueError(f"Unsupported auth.type: {self.auth_type}")

    @property
    def display_name(self) -> str:
        return "Blob Storage"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "name": self.manifest.get("name", "blob_storage_plugin"),
            "type": "blob_storage",
            "description": self.manifest.get("description", "Plugin for Azure Blob Storage operations that uses key or managed identity authentication allowing querying of blob storage data sources."),
            "methods": [
                {
                    "name": "list_containers",
                    "description": "List all containers in the storage account.",
                    "parameters": [],
                    "returns": {"type": "List[str]", "description": "List of container names."}
                },
                {
                    "name": "list_blobs",
                    "description": "List all blobs in a given container.",
                    "parameters": [
                        {"name": "container_name", "type": "str", "description": "Name of the container.", "required": True}
                    ],
                    "returns": {"type": "List[str]", "description": "List of blob names."}
                },
                {
                    "name": "get_blob_metadata",
                    "description": "Get metadata for a specific blob.",
                    "parameters": [
                        {"name": "container_name", "type": "str", "description": "Name of the container.", "required": True},
                        {"name": "blob_name", "type": "str", "description": "Name of the blob.", "required": True}
                    ],
                    "returns": {"type": "dict", "description": "Blob metadata as a dictionary."}
                },
                {
                    "name": "get_blob_content",
                    "description": "Read the contents of a blob as text or base64 for images to be renderable in the browser.",
                    "parameters": [
                        {"name": "container_name", "type": "str", "description": "Name of the container.", "required": True},
                        {"name": "blob_name", "type": "str", "description": "Name of the blob.", "required": True}
                    ],
                    "returns": {"type": "str", "description": "Blob content as a string."}
                },
                {
                    "name": "iterate_blobs_in_container",
                    "description": "Iterates over all blobs in a container, reads their data, and return a dict of blob_name: content. Uses text or base64 for images to be renderable in the browser.",
                    "parameters": [
                        {"name": "container_name", "type": "str", "description": "Name of the container.", "required": True}
                    ],
                    "returns": {"type": "dict", "description": "Dictionary of blob_name: content for all blobs in the container."}
                }
            ]
        }

    def get_functions(self) -> List[str]:
        return [
            "list_containers",
            "list_blobs",
            "get_blob_metadata",
            "get_blob_content",
            "iterate_blobs_in_container"
        ]

    @plugin_function_logger("BlobStoragePlugin")
    @kernel_function(description="List all containers in the storage account.")
    def list_containers(self) -> List[str]:
        containers = self.service_client.list_containers()
        return [c['name'] for c in containers]

    @plugin_function_logger("BlobStoragePlugin")
    @kernel_function(description="List all blobs in a given container.")
    def list_blobs(self, container_name: str) -> List[str]:
        container_client = self.service_client.get_container_client(container_name)
        blobs = container_client.list_blobs()
        return [b['name'] for b in blobs]

    @plugin_function_logger("BlobStoragePlugin")
    @kernel_function(description="Get metadata for a specific blob.")
    def get_blob_metadata(self, container_name: str, blob_name: str) -> dict:
        blob_client = self.service_client.get_blob_client(container=container_name, blob=blob_name)
        return blob_client.get_blob_properties().metadata

    @plugin_function_logger("BlobStoragePlugin")
    @kernel_function(description="Read the contents of a blob as text or base64 for images to be renderable in the browser.")
    def get_blob_content(self, container_name: str, blob_name: str) -> str:
        blob_client = self.service_client.get_blob_client(container=container_name, blob=blob_name)
        stream = blob_client.download_blob()
        data = stream.readall()
        content_type, _ = mimetypes.guess_type(blob_name)
        if content_type and content_type.startswith("text"):
            try:
                return data.decode('utf-8')
            except UnicodeDecodeError:
                return "[Unreadable text file]"
        elif content_type and content_type.startswith("image"):
            # Return base64 for images
            return base64.b64encode(data).decode('utf-8')
        else:
            return f"[Binary file: {blob_name}, type: {content_type or 'unknown'}]"

    @plugin_function_logger("BlobStoragePlugin")
    @kernel_function(description="Iterates over all blobs in a container, reads their data, and return a dict of blob_name: content. Uses text or base64 for images to be renderable in the browser.")
    def iterate_blobs_in_container(self, container_name: str) -> dict:
        container_client = self.service_client.get_container_client(container_name)
        result = {}
        for blob in container_client.list_blobs():
            blob_client = container_client.get_blob_client(blob)
            data = blob_client.download_blob().readall()
            content_type, _ = mimetypes.guess_type(blob['name'])
            if content_type and content_type.startswith("text"):
                try:
                    content = data.decode('utf-8')
                except UnicodeDecodeError:
                    content = "[Unreadable text file]"
            elif content_type and content_type.startswith("image"):
                content = base64.b64encode(data).decode('utf-8')
            else:
                content = f"[Binary file: {blob['name']}, type: {content_type or 'unknown'}]"
            result[blob['name']] = content
        return result
