import os
import sys
import json
import asyncio
from typing import Dict, Any, List, Optional
from semantic_kernel.functions import kernel_function

# Add the MCP client path for imports
mcp_client_path = os.path.join(os.path.dirname(__file__), '..', '..', 'external_apps', 'mcp_client')
sys.path.insert(0, mcp_client_path)

from simplechat_mcp_client import SimpleChatMCPClient, SimpleChatMCPClientConfig, MCPClientError


class SimpleChatMCPLegacyPlugin:
    """
    Legacy SimpleChat MCP Plugin for integration with the existing plugin system.
    
    This plugin provides a bridge between the existing SimpleChat plugin architecture
    and the new MCP client functionality. It follows the patterns established in the
    existing codebase while providing access to all MCP server tools.
    """
    
    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        """Initialize the plugin with optional manifest configuration"""
        self.manifest = manifest or {}
        
        # Extract configuration from manifest
        server_path = self.manifest.get('server_path', '../external_apps/mcp_server/simplechat_mcp_server.py')
        timeout = self.manifest.get('timeout', 30)
        log_level = self.manifest.get('log_level', 'INFO')
        
        # Create MCP client configuration
        self.config = SimpleChatMCPClientConfig(
            server_path=server_path,
            timeout=timeout,
            log_level=log_level
        )
        
        # Add server environment variables from manifest
        server_env = self.manifest.get('server_env', {})
        if server_env:
            self.config.server_env.update(server_env)
    
    @property
    def metadata(self) -> Dict[str, Any]:
        """Return plugin metadata following the established schema"""
        return {
            "name": "simplechat_mcp_plugin",
            "type": "mcp_client",
            "description": "Plugin for interacting with SimpleChat functionality through MCP (Model Context Protocol). Provides access to chat, document management, group operations, and settings.",
            "methods": [
                {
                    "name": "send_message",
                    "description": "Send a chat message to SimpleChat with optional search and group features",
                    "parameters": [
                        {"name": "user_id", "type": "str", "description": "User identifier", "required": True},
                        {"name": "message", "type": "str", "description": "Message content to send", "required": True},
                        {"name": "hybrid_search", "type": "bool", "description": "Enable hybrid search functionality", "required": False},
                        {"name": "bing_search", "type": "bool", "description": "Enable Bing search functionality", "required": False},
                        {"name": "active_group_id", "type": "str", "description": "Optional group context ID", "required": False},
                        {"name": "document_scope", "type": "list", "description": "Optional document scope limitation", "required": False}
                    ],
                    "returns": {"type": "str", "description": "Chat response from SimpleChat"}
                },
                {
                    "name": "list_documents",
                    "description": "List user documents with pagination and search capabilities",
                    "parameters": [
                        {"name": "user_id", "type": "str", "description": "User identifier", "required": True},
                        {"name": "page", "type": "int", "description": "Page number (default: 1)", "required": False},
                        {"name": "size", "type": "int", "description": "Page size (default: 10)", "required": False},
                        {"name": "search", "type": "str", "description": "Optional search query", "required": False}
                    ],
                    "returns": {"type": "str", "description": "List of documents with metadata"}
                },
                {
                    "name": "upload_document",
                    "description": "Upload a document to SimpleChat",
                    "parameters": [
                        {"name": "user_id", "type": "str", "description": "User identifier", "required": True},
                        {"name": "file_path", "type": "str", "description": "Path to file to upload", "required": True},
                        {"name": "filename", "type": "str", "description": "Optional custom filename", "required": False}
                    ],
                    "returns": {"type": "str", "description": "Upload result with document metadata"}
                },
                {
                    "name": "list_groups",
                    "description": "List user groups with pagination and search capabilities",
                    "parameters": [
                        {"name": "user_id", "type": "str", "description": "User identifier", "required": True},
                        {"name": "page", "type": "int", "description": "Page number (default: 1)", "required": False},
                        {"name": "size", "type": "int", "description": "Page size (default: 10)", "required": False},
                        {"name": "search", "type": "str", "description": "Optional search query", "required": False}
                    ],
                    "returns": {"type": "str", "description": "List of groups with metadata"}
                },
                {
                    "name": "get_settings",
                    "description": "Retrieve application settings from SimpleChat",
                    "parameters": [],
                    "returns": {"type": "str", "description": "Current application settings"}
                },
                {
                    "name": "update_settings",
                    "description": "Update application settings in SimpleChat",
                    "parameters": [
                        {"name": "settings", "type": "dict", "description": "Settings to update", "required": True}
                    ],
                    "returns": {"type": "str", "description": "Update result"}
                },
                {
                    "name": "test_token",
                    "description": "Test bearer token validity for SimpleChat authentication",
                    "parameters": [],
                    "returns": {"type": "str", "description": "Token validation result"}
                }
            ]
        }
    
    def get_functions(self) -> List[str]:
        """Return list of function names this plugin exposes for SK registration"""
        return [
            "send_message",
            "list_documents", 
            "upload_document",
            "list_groups",
            "get_settings",
            "update_settings",
            "test_token"
        ]
    
    async def _execute_with_client(self, operation):
        """Execute an operation with a temporary MCP client connection"""
        client = None
        try:
            client = SimpleChatMCPClient(self.config)
            await client.connect()
            return await operation(client)
        except MCPClientError as e:
            return f"MCP Error: {e}"
        except Exception as e:
            return f"Unexpected Error: {e}"
        finally:
            if client:
                try:
                    await client.disconnect()
                except:
                    pass  # Ignore disconnect errors
    
    @kernel_function(
        description="Send a chat message to SimpleChat with optional search and group features",
        name="send_message"
    )
    async def send_message(
        self,
        user_id: str,
        message: str,
        hybrid_search: bool = False,
        bing_search: bool = False,
        active_group_id: Optional[str] = None,
        document_scope: Optional[List[str]] = None
    ) -> str:
        """Send a chat message to SimpleChat"""
        
        async def operation(client: SimpleChatMCPClient):
            return await client.send_message(
                user_id=user_id,
                message=message,
                hybrid_search=hybrid_search,
                bing_search=bing_search,
                active_group_id=active_group_id,
                document_scope=document_scope
            )
        
        return await self._execute_with_client(operation)
    
    @kernel_function(
        description="List user documents with pagination and search capabilities",
        name="list_documents"
    )
    async def list_documents(
        self,
        user_id: str,
        page: int = 1,
        size: int = 10,
        search: Optional[str] = None
    ) -> str:
        """List user documents with pagination and search"""
        
        async def operation(client: SimpleChatMCPClient):
            return await client.list_documents(
                user_id=user_id,
                page=page,
                size=size,
                search=search
            )
        
        return await self._execute_with_client(operation)
    
    @kernel_function(
        description="Upload a document to SimpleChat",
        name="upload_document"
    )
    async def upload_document(
        self,
        user_id: str,
        file_path: str,
        filename: Optional[str] = None
    ) -> str:
        """Upload a document to SimpleChat"""
        
        async def operation(client: SimpleChatMCPClient):
            return await client.upload_document(
                user_id=user_id,
                file_path=file_path,
                filename=filename
            )
        
        return await self._execute_with_client(operation)
    
    @kernel_function(
        description="List user groups with pagination and search capabilities",
        name="list_groups"
    )
    async def list_groups(
        self,
        user_id: str,
        page: int = 1,
        size: int = 10,
        search: Optional[str] = None
    ) -> str:
        """List user groups with pagination and search"""
        
        async def operation(client: SimpleChatMCPClient):
            return await client.list_groups(
                user_id=user_id,
                page=page,
                size=size,
                search=search
            )
        
        return await self._execute_with_client(operation)
    
    @kernel_function(
        description="Retrieve application settings from SimpleChat",
        name="get_settings"
    )
    async def get_settings(self) -> str:
        """Get application settings"""
        
        async def operation(client: SimpleChatMCPClient):
            return await client.get_settings()
        
        return await self._execute_with_client(operation)
    
    @kernel_function(
        description="Update application settings in SimpleChat",
        name="update_settings"
    )
    async def update_settings(self, settings: Dict[str, Any]) -> str:
        """Update application settings"""
        
        async def operation(client: SimpleChatMCPClient):
            return await client.update_settings(settings)
        
        return await self._execute_with_client(operation)
    
    @kernel_function(
        description="Test bearer token validity for SimpleChat authentication",
        name="test_token"
    )
    async def test_token(self) -> str:
        """Test bearer token validity"""
        
        async def operation(client: SimpleChatMCPClient):
            return await client.test_token()
        
        return await self._execute_with_client(operation)