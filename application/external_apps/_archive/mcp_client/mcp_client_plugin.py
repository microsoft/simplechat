"""
SimpleChat MCP Plugin for Semantic Kernel

This plugin integrates the SimpleChat MCP client with Semantic Kernel, providing
all MCP server tools as Semantic Kernel functions that can be used by agents,
planners, and other SK components.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Annotated

import semantic_kernel as sk
from semantic_kernel.functions import kernel_function

from simplechat_mcp_client import SimpleChatMCPClient, SimpleChatMCPClientConfig, MCPClientError


class SimpleChatMCPPlugin:
    """
    Semantic Kernel plugin that provides access to SimpleChat MCP server functionality.
    
    This plugin wraps the SimpleChatMCPClient and exposes all MCP tools as SK functions
    that can be called by agents, planners, and other Semantic Kernel components.
    """
    
    def __init__(self, config: Optional[SimpleChatMCPClientConfig] = None):
        """
        Initialize the SimpleChat MCP plugin.
        
        Args:
            config: Optional MCP client configuration
        """
        self.config = config or SimpleChatMCPClientConfig()
        self.logger = logging.getLogger(__name__)
        
        # We'll create client connections as needed since SK functions should be stateless
        self._client_pool: List[SimpleChatMCPClient] = []
    
    async def _get_client(self) -> SimpleChatMCPClient:
        """Get a connected MCP client instance"""
        client = SimpleChatMCPClient(self.config)
        await client.connect()
        return client
    
    async def _execute_with_client(self, operation):
        """Execute an operation with a temporary client connection"""
        client = None
        try:
            client = await self._get_client()
            return await operation(client)
        finally:
            if client:
                await client.disconnect()
    
    @kernel_function(
        description="Send a chat message to SimpleChat with optional search and group features",
        name="send_message"
    )
    async def send_message(
        self,
        user_id: Annotated[str, "User identifier"],
        message: Annotated[str, "Message content to send"],
        hybrid_search: Annotated[bool, "Enable hybrid search functionality"] = False,
        bing_search: Annotated[bool, "Enable Bing search functionality"] = False,
        active_group_id: Annotated[Optional[str], "Optional group context ID"] = None,
        document_scope: Annotated[Optional[str], "Optional document scope limitation (JSON list)"] = None
    ) -> str:
        """Send a chat message to SimpleChat"""
        
        async def operation(client: SimpleChatMCPClient):
            # Parse document_scope if provided as JSON string
            doc_scope = None
            if document_scope:
                try:
                    doc_scope = json.loads(document_scope)
                except json.JSONDecodeError:
                    self.logger.warning(f"Invalid document_scope JSON: {document_scope}")
            
            return await client.send_message(
                user_id=user_id,
                message=message,
                hybrid_search=hybrid_search,
                bing_search=bing_search,
                active_group_id=active_group_id,
                document_scope=doc_scope
            )
        
        try:
            return await self._execute_with_client(operation)
        except MCPClientError as e:
            return f"Error sending message: {e}"
    
    @kernel_function(
        description="List user documents with pagination and search capabilities",
        name="list_documents"
    )
    async def list_documents(
        self,
        user_id: Annotated[str, "User identifier"],
        page: Annotated[int, "Page number (default: 1)"] = 1,
        size: Annotated[int, "Page size (default: 10)"] = 10,
        search: Annotated[Optional[str], "Optional search query"] = None
    ) -> str:
        """List user documents with pagination and search"""
        
        async def operation(client: SimpleChatMCPClient):
            return await client.list_documents(
                user_id=user_id,
                page=page,
                size=size,
                search=search
            )
        
        try:
            return await self._execute_with_client(operation)
        except MCPClientError as e:
            return f"Error listing documents: {e}"
    
    @kernel_function(
        description="Upload a document to SimpleChat",
        name="upload_document"
    )
    async def upload_document(
        self,
        user_id: Annotated[str, "User identifier"],
        file_path: Annotated[str, "Path to file to upload"],
        filename: Annotated[Optional[str], "Optional custom filename"] = None
    ) -> str:
        """Upload a document to SimpleChat"""
        
        async def operation(client: SimpleChatMCPClient):
            return await client.upload_document(
                user_id=user_id,
                file_path=file_path,
                filename=filename
            )
        
        try:
            return await self._execute_with_client(operation)
        except MCPClientError as e:
            return f"Error uploading document: {e}"
    
    @kernel_function(
        description="List user groups with pagination and search capabilities",
        name="list_groups"
    )
    async def list_groups(
        self,
        user_id: Annotated[str, "User identifier"],
        page: Annotated[int, "Page number (default: 1)"] = 1,
        size: Annotated[int, "Page size (default: 10)"] = 10,
        search: Annotated[Optional[str], "Optional search query"] = None
    ) -> str:
        """List user groups with pagination and search"""
        
        async def operation(client: SimpleChatMCPClient):
            return await client.list_groups(
                user_id=user_id,
                page=page,
                size=size,
                search=search
            )
        
        try:
            return await self._execute_with_client(operation)
        except MCPClientError as e:
            return f"Error listing groups: {e}"
    
    @kernel_function(
        description="Retrieve application settings from SimpleChat",
        name="get_settings"
    )
    async def get_settings(self) -> str:
        """Get application settings"""
        
        async def operation(client: SimpleChatMCPClient):
            return await client.get_settings()
        
        try:
            return await self._execute_with_client(operation)
        except MCPClientError as e:
            return f"Error getting settings: {e}"
    
    @kernel_function(
        description="Update application settings in SimpleChat",
        name="update_settings"
    )
    async def update_settings(
        self,
        settings: Annotated[str, "Settings to update (JSON format)"]
    ) -> str:
        """Update application settings"""
        
        async def operation(client: SimpleChatMCPClient):
            try:
                settings_dict = json.loads(settings)
            except json.JSONDecodeError as e:
                return f"Invalid JSON settings format: {e}"
            
            return await client.update_settings(settings_dict)
        
        try:
            return await self._execute_with_client(operation)
        except MCPClientError as e:
            return f"Error updating settings: {e}"
    
    @kernel_function(
        description="Test bearer token validity for SimpleChat authentication",
        name="test_token"
    )
    async def test_token(self) -> str:
        """Test bearer token validity"""
        
        async def operation(client: SimpleChatMCPClient):
            return await client.test_token()
        
        try:
            return await self._execute_with_client(operation)
        except MCPClientError as e:
            return f"Error testing token: {e}"


# Convenience function to add the plugin to a kernel
def add_simplechat_plugin(
    kernel: sk.Kernel, 
    plugin_name: str = "simplechat",
    config: Optional[SimpleChatMCPClientConfig] = None
) -> SimpleChatMCPPlugin:
    """
    Convenience function to add the SimpleChat MCP plugin to a Semantic Kernel instance.
    
    Args:
        kernel: Semantic Kernel instance
        plugin_name: Name to use for the plugin (default: "simplechat")
        config: Optional MCP client configuration
        
    Returns:
        The created plugin instance
    """
    plugin = SimpleChatMCPPlugin(config)
    kernel.add_plugin(plugin, plugin_name=plugin_name)
    return plugin