#!/usr/bin/env python3
"""
SimpleChat MCP Client

A client that connects to the SimpleChat MCP server and provides access to all MCP tools
through a clean async interface. This client can be used directly or as part of the 
Semantic Kernel plugin.
"""

import os
import json
import logging
import asyncio
from typing import Any, Dict, List, Optional, Union
from contextlib import asynccontextmanager

from fastmcp import Client
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPClientError(Exception):
    """Base exception for MCP client errors"""
    pass


class MCPConnectionError(MCPClientError):
    """Exception raised when connection to MCP server fails"""
    pass


class MCPToolError(MCPClientError):
    """Exception raised when MCP tool execution fails"""
    pass


class SimpleChatMCPClientConfig(BaseSettings):
    """Configuration for SimpleChat MCP Client"""
    
    model_config = SettingsConfigDict(env_prefix="SIMPLECHAT_MCP_CLIENT_", env_file=".env")
    
    # MCP Server connection
    server_path: str = "../mcp_server/simplechat_mcp_server.py"
    server_command: Optional[str] = None
    server_args: Optional[List[str]] = None
    timeout: int = 30
    
    # Logging
    log_level: str = "INFO"
    
    # Server environment variables (passed to MCP server)
    server_env: Dict[str, str] = {}


class SimpleChatMCPClient:
    """
    Async client for interacting with the SimpleChat MCP server.
    
    This client provides a clean interface to all SimpleChat MCP tools and handles
    connection management, error handling, and logging.
    """
    
    def __init__(self, config: Optional[SimpleChatMCPClientConfig] = None):
        """
        Initialize the MCP client.
        
        Args:
            config: Optional configuration object. If not provided, will load from environment.
        """
        self.config = config or SimpleChatMCPClientConfig()
        
        # Configure logging
        logging.basicConfig(
            level=getattr(logging, self.config.log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # MCP client
        self._client: Optional[Client] = None
        self._connected = False
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.disconnect()
    
    async def connect(self):
        """Connect to the MCP server"""
        if self._connected:
            return
        
        try:
            self.logger.info(f"Connecting to MCP server: {self.config.server_path}")
            
            # Create client with server path
            self._client = Client(self.config.server_path)
            
            # Set server environment variables if provided
            if self.config.server_env:
                # Note: FastMCP Client doesn't directly support env vars
                # We'll need to set them in the current process for the server to inherit
                for key, value in self.config.server_env.items():
                    os.environ[key] = value
            
            # Enter client context
            await self._client.__aenter__()
            self._connected = True
            
            self.logger.info("Successfully connected to MCP server")
            
            # Test connection by listing tools
            await self._test_connection()
            
        except Exception as e:
            self.logger.error(f"Failed to connect to MCP server: {e}")
            raise MCPConnectionError(f"Failed to connect to MCP server: {e}")
    
    async def disconnect(self):
        """Disconnect from the MCP server"""
        if not self._connected or not self._client:
            return
        
        try:
            await self._client.__aexit__(None, None, None)
            self._connected = False
            self.logger.info("Disconnected from MCP server")
        except Exception as e:
            self.logger.error(f"Error disconnecting from MCP server: {e}")
    
    async def _test_connection(self):
        """Test connection to MCP server by listing available tools"""
        try:
            tools = await self._client.list_tools()
            tool_names = [tool.name for tool in tools.tools]
            self.logger.debug(f"Available MCP tools: {tool_names}")
        except Exception as e:
            raise MCPConnectionError(f"Failed to list tools from MCP server: {e}")
    
    async def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """
        Call an MCP tool with error handling.
        
        Args:
            tool_name: Name of the tool to call
            arguments: Arguments to pass to the tool
            
        Returns:
            Tool result
            
        Raises:
            MCPToolError: If tool execution fails
        """
        if not self._connected or not self._client:
            raise MCPConnectionError("Not connected to MCP server")
        
        try:
            self.logger.debug(f"Calling MCP tool {tool_name} with args: {arguments}")
            result = await self._client.call_tool(tool_name, arguments)
            
            if hasattr(result, 'content') and result.content:
                # Extract content from MCP result
                content = result.content[0] if isinstance(result.content, list) else result.content
                if hasattr(content, 'text'):
                    return content.text
                return str(content)
            
            return str(result)
            
        except Exception as e:
            self.logger.error(f"Error calling MCP tool {tool_name}: {e}")
            raise MCPToolError(f"Error calling tool {tool_name}: {e}")
    
    # SimpleChat MCP Tool Methods
    
    async def send_message(
        self,
        user_id: str,
        message: str,
        hybrid_search: bool = False,
        bing_search: bool = False,
        active_group_id: Optional[str] = None,
        document_scope: Optional[List[str]] = None
    ) -> str:
        """
        Send a chat message to SimpleChat.
        
        Args:
            user_id: User identifier
            message: Message content
            hybrid_search: Whether to enable hybrid search
            bing_search: Whether to enable Bing search
            active_group_id: Optional group context ID
            document_scope: Optional document scope limitation
            
        Returns:
            Chat response from SimpleChat
        """
        args = {
            "user_id": user_id,
            "message": message,
            "hybrid_search": hybrid_search,
            "bing_search": bing_search
        }
        
        if active_group_id:
            args["active_group_id"] = active_group_id
        if document_scope:
            args["document_scope"] = document_scope
        
        return await self._call_tool("send_message", args)
    
    async def list_documents(
        self,
        user_id: str,
        page: int = 1,
        size: int = 10,
        search: Optional[str] = None
    ) -> str:
        """
        List user documents with pagination and search.
        
        Args:
            user_id: User identifier
            page: Page number (default: 1)
            size: Page size (default: 10)
            search: Optional search query
            
        Returns:
            List of documents with metadata
        """
        args = {
            "user_id": user_id,
            "page": page,
            "size": size
        }
        
        if search:
            args["search"] = search
        
        return await self._call_tool("list_documents", args)
    
    async def upload_document(
        self,
        user_id: str,
        file_path: str,
        filename: Optional[str] = None
    ) -> str:
        """
        Upload a document to SimpleChat.
        
        Args:
            user_id: User identifier
            file_path: Path to file to upload
            filename: Optional custom filename
            
        Returns:
            Upload result with document metadata
        """
        args = {
            "user_id": user_id,
            "file_path": file_path
        }
        
        if filename:
            args["filename"] = filename
        
        return await self._call_tool("upload_document", args)
    
    async def list_groups(
        self,
        user_id: str,
        page: int = 1,
        size: int = 10,
        search: Optional[str] = None
    ) -> str:
        """
        List user groups with pagination and search.
        
        Args:
            user_id: User identifier
            page: Page number (default: 1)
            size: Page size (default: 10)
            search: Optional search query
            
        Returns:
            List of groups with metadata
        """
        args = {
            "user_id": user_id,
            "page": page,
            "size": size
        }
        
        if search:
            args["search"] = search
        
        return await self._call_tool("list_groups", args)
    
    async def get_settings(self) -> str:
        """
        Get application settings.
        
        Returns:
            Current application settings
        """
        return await self._call_tool("get_settings", {})
    
    async def update_settings(self, settings: Dict[str, Any]) -> str:
        """
        Update application settings.
        
        Args:
            settings: Settings to update
            
        Returns:
            Update result
        """
        return await self._call_tool("update_settings", {"settings": settings})
    
    async def test_token(self) -> str:
        """
        Test bearer token validity.
        
        Returns:
            Token validation result
        """
        return await self._call_tool("test_token", {})


# Convenience function for quick usage
@asynccontextmanager
async def create_mcp_client(config: Optional[SimpleChatMCPClientConfig] = None):
    """
    Convenience context manager for creating and managing an MCP client.
    
    Args:
        config: Optional configuration
        
    Yields:
        Connected SimpleChatMCPClient instance
    """
    client = SimpleChatMCPClient(config)
    async with client:
        yield client


# Example usage
async def main():
    """Example usage of the MCP client"""
    try:
        async with create_mcp_client() as client:
            # Test connection
            token_result = await client.test_token()
            print(f"Token test: {token_result}")
            
            # Send a message
            message_result = await client.send_message(
                user_id="example_user",
                message="Hello from MCP client!",
                hybrid_search=True
            )
            print(f"Message result: {message_result}")
            
            # List documents
            docs_result = await client.list_documents(
                user_id="example_user",
                page=1,
                size=5
            )
            print(f"Documents: {docs_result}")
            
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())