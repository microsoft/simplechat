from typing import Dict, Any, List
from semantic_kernel_plugins.base_plugin import BasePlugin
from azure.storage.queue import QueueClient
from semantic_kernel.functions import kernel_function
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger
from azure.identity import DefaultAzureCredential

class QueueStoragePlugin(BasePlugin):
    def __init__(self, manifest: Dict[str, Any]):
        super().__init__(manifest)
        self.manifest = manifest
        self.endpoint = manifest.get('endpoint')
        self.queue_name = manifest.get('queue_name')
        self.key = manifest.get('auth', {}).get('key')
        self.auth_type = manifest.get('auth', {}).get('type', 'key')
        self._metadata = manifest.get('metadata', {})
        if not self.endpoint or not self.auth_type or not self.queue_name:
            raise ValueError("QueueStoragePlugin requires 'endpoint', 'queue_name', and 'auth.type' in the manifest.")
        if self.auth_type == 'identity':
            self.queue_client = QueueClient(account_url=self.endpoint, queue_name=self.queue_name, credential=DefaultAzureCredential())
        elif self.auth_type == 'key':
            if not self.key:
                raise ValueError("QueueStoragePlugin requires 'auth.key' when using key authentication.")
            self.queue_client = QueueClient(account_url=self.endpoint, queue_name=self.queue_name, credential=self.key)
        else:
            raise ValueError(f"Unsupported auth.type: {self.auth_type}")

    @property
    def display_name(self) -> str:
        return "Queue Storage"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "name": self.manifest.get("name", "queue_storage_plugin"),
            "type": "queue_storage",
            "description": "Plugin for sending messages to an Azure Storage Queue. Use this to enqueue tasks, trigger background processing, or communicate between distributed components.",
            "methods": [
                {
                    "name": "send_message",
                    "description": "Send a message to the configured Azure Storage Queue.",
                    "parameters": [
                        {"name": "message", "type": "str", "description": "The message to send to the queue.", "required": True}
                    ],
                    "returns": {"type": "str", "description": "The message ID of the enqueued message."}
                }
            ]
        }

    def get_functions(self) -> List[str]:
        return ["send_message"]

    @plugin_function_logger("QueueStoragePlugin")
    @kernel_function(description="Send a message to the configured Azure Storage Queue.")
    def send_message(self, message: str) -> str:
        resp = self.queue_client.send_message(message)
        return resp.id
