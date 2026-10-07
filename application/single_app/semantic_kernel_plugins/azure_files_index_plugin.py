# azure_files_index_plugin.py
"""Semantic Kernel action that searches an Azure Files indexer index with live file permissions.

The action queries a customer's existing Azure AI Search index that was built by the Azure Files
indexer, then returns only results from files the signed-in user can open: each candidate file's
NTFS DACL and the share's permissions are checked against the user's directory identity before
anything reaches the model. Withheld files are never mentioned to the user; administrators see
them in the activity logs.
"""

from typing import Annotated, Any, Dict, List, Optional

from semantic_kernel.functions import kernel_function

from functions_authentication import get_current_user_id
from functions_azure_files_search import (
    AZURE_FILES_INDEX_ACTION_TYPE,
    AZURE_FILES_SEARCH_DISPLAY_NAME,
    MAX_TOP_N,
)
from functions_azure_files_search_runtime import execute_azure_files_search
from functions_settings import get_settings
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


class AzureFilesIndexPlugin(BasePlugin):
    """Search an Azure Files indexer index and keep only files the user can open."""

    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        super().__init__(manifest)
        self.manifest = manifest or {}
        metadata = self.manifest.get("metadata")
        self._metadata = metadata if isinstance(metadata, dict) else {}

    @property
    def display_name(self) -> str:
        return AZURE_FILES_SEARCH_DISPLAY_NAME

    @property
    def metadata(self) -> Dict[str, Any]:
        user_description = self._metadata.get(
            "description",
            "Searches file share content indexed by the Azure AI Search Azure Files indexer.",
        )
        api_description = (
            "Search an Azure AI Search index that was built from Azure file shares. Results include only "
            "files the signed-in user can open on the share, each with its file name and network path."
        )
        return {
            "name": self._metadata.get("name", "azure_files_index_plugin"),
            "type": AZURE_FILES_INDEX_ACTION_TYPE,
            "description": f"{user_description}\n\n{api_description}",
            "methods": [
                {
                    "name": "search_files",
                    "description": (
                        "Search the file share index for passages relevant to a question. Returns only files the "
                        "signed-in user can open, with file names and network paths to cite."
                    ),
                    "parameters": [
                        {"name": "query", "type": "str", "description": "Natural-language search query.", "required": True},
                        {"name": "top_n", "type": "int", "description": f"Maximum results to return (1-{MAX_TOP_N}).", "required": False},
                    ],
                    "returns": {"type": "dict", "description": "Matching passages with file names and network paths."},
                },
            ],
        }

    def get_functions(self) -> List[str]:
        return ["search_files"]

    # bac-check: ignore - the user is the signed-in session user; the model supplies only query text and a bounded count.
    @plugin_function_logger("AzureFilesIndexPlugin")
    @kernel_function(
        name="search_files",
        description=(
            "Search the configured file share index for passages relevant to the question. Returns only files the "
            "signed-in user can open. Cite each result by its file_name and unc_path."
        ),
    )
    def search_files(
        self,
        query: Annotated[str, "Natural-language query describing what to find in the file shares."],
        top_n: Annotated[int, f"Maximum number of results to return, 1 to {MAX_TOP_N}. Use 0 for the default."] = 0,
    ) -> Annotated[dict, "Matching passages with file names and network paths."]:
        try:
            user_id = get_current_user_id()
        except RuntimeError:
            user_id = None
        return execute_azure_files_search(self.manifest, query, top_n or None, user_id, get_settings())
