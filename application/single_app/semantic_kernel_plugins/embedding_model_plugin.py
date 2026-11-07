# embedding_model_plugin.py
"""Default shared embedding action, preserving explicitly configured action manifests."""

from typing import Dict, Any, List
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger
import requests
from functions_content import generate_embedding
from semantic_kernel.functions import kernel_function

class EmbeddingModelPlugin(BasePlugin):
    def __init__(self, manifest: Dict[str, Any] = None):
        # If manifest is provided, use it (dynamic); else, use settings (static)
        if manifest is not None:
            self.manifest = manifest
            self.endpoint = manifest.get('endpoint')
            self.api_version = manifest.get('api_version')
            self.key = manifest.get('auth', {}).get('key')
            self.deployment = manifest.get('deployment')
            self.auth_type = manifest.get('auth', {}).get('type', 'key')
        else:
            self.manifest = None

    @property
    def display_name(self) -> str:
        return "Embedding Model"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "name": "embedding_model_plugin",
            "type": "embedding_model",
            "description": "Plugin for generating text embeddings using the configured embedding model.",
            "methods": [
                {
                    "name": "embed",
                    "description": "Generate an embedding vector for the given text.",
                    "parameters": [
                        {"name": "text", "type": "str", "description": "Input text to embed.", "required": True}
                    ],
                    "returns": {"type": "List[float]", "description": "Embedding vector."}
                }
            ]
        }

    def get_functions(self) -> List[str]:
        return ["embed"]

    @plugin_function_logger("EmbeddingModelPlugin")
    @kernel_function(description="Generate an embedding vector for the given text.")
    def embed(self, text: str) -> List[float]:
        if self.manifest is None:
            vector, _ = generate_embedding(text, purpose="text")
            return vector
        if not self.endpoint or not self.key or not self.deployment:
            raise RuntimeError("Embedding model configuration is missing.")
        url = f"{self.endpoint}/openai/deployments/{self.deployment}/embeddings?api-version={self.api_version}"
        headers = {
            "Content-Type": "application/json",
            "api-key": self.key
        }
        data = {"input": text}
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        # Azure OpenAI returns embeddings in result['data'][0]['embedding']
        return result['data'][0]['embedding']
