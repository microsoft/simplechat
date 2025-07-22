#!/usr/bin/env python3
"""
FastMCP Server for SimpleChat API Integration

This server provides a Model Context Protocol interface to SimpleChat's API endpoints,
enabling MCP clients to interact with SimpleChat functionality through standardized tools.
"""

import os
import json
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

import httpx
from mcp.server import Server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    GetToolRequestParams,
    GetToolResult,
    ListToolsResult,
    Tool,
    TextContent,
    JSONRPCError,
    ErrorCode,
    INVALID_REQUEST
)
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class SimpleChatConfig(BaseSettings):
    """Configuration for SimpleChat MCP Server"""
    
    # SimpleChat API Configuration
    simplechat_base_url: str = "http://localhost:5000"
    simplechat_bearer_token: str = ""
    
    # MCP Server Configuration
    server_name: str = "simplechat-mcp"
    server_version: str = "1.0.0"
    
    # Logging
    log_level: str = "INFO"
    
    class Config:
        env_prefix = "SIMPLECHAT_MCP_"
        env_file = ".env"


class SimpleChatMCPServer:
    def __init__(self, config: SimpleChatConfig):
        self.config = config
        self.server = Server(config.server_name)
        self.http_client = httpx.AsyncClient(
            base_url=config.simplechat_base_url,
            timeout=httpx.Timeout(30.0),
            headers={
                "Authorization": f"Bearer {config.simplechat_bearer_token}",
                "Content-Type": "application/json"
            }
        )
        
        # Configure logging
        logging.basicConfig(
            level=getattr(logging, config.log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Register tools
        self._register_tools()
    
    def _register_tools(self):
        """Register all available MCP tools"""
        
        @self.server.list_tools()
        async def list_tools() -> ListToolsResult:
            """List all available tools"""
            return ListToolsResult(
                tools=[
                    Tool(
                        name="send_message",
                        description="Send a chat message to SimpleChat",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "message": {
                                    "type": "string",
                                    "description": "The message to send"
                                },
                                "user_id": {
                                    "type": "string", 
                                    "description": "User ID for the message"
                                },
                                "conversation_id": {
                                    "type": "string",
                                    "description": "Optional conversation ID. If not provided, a new conversation will be created"
                                },
                                "chat_type": {
                                    "type": "string",
                                    "enum": ["user", "group"],
                                    "description": "Type of chat (user or group)",
                                    "default": "user"
                                },
                                "hybrid_search": {
                                    "type": "boolean",
                                    "description": "Enable hybrid search",
                                    "default": False
                                },
                                "bing_search": {
                                    "type": "boolean", 
                                    "description": "Enable Bing search",
                                    "default": False
                                },
                                "active_group_id": {
                                    "type": "string",
                                    "description": "Active group ID for group chats"
                                }
                            },
                            "required": ["message", "user_id"]
                        }
                    ),
                    Tool(
                        name="list_documents",
                        description="List user documents from SimpleChat",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "user_id": {
                                    "type": "string",
                                    "description": "User ID to list documents for"
                                },
                                "page": {
                                    "type": "integer",
                                    "description": "Page number for pagination",
                                    "default": 1
                                },
                                "page_size": {
                                    "type": "integer", 
                                    "description": "Number of documents per page",
                                    "default": 10
                                },
                                "search": {
                                    "type": "string",
                                    "description": "Search term for filtering documents"
                                }
                            },
                            "required": ["user_id"]
                        }
                    ),
                    Tool(
                        name="upload_document",
                        description="Upload a document to SimpleChat",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "user_id": {
                                    "type": "string",
                                    "description": "User ID for the document upload"
                                },
                                "file_path": {
                                    "type": "string",
                                    "description": "Local file path to upload"
                                },
                                "filename": {
                                    "type": "string",
                                    "description": "Optional filename override"
                                }
                            },
                            "required": ["user_id", "file_path"]
                        }
                    ),
                    Tool(
                        name="list_groups",
                        description="List user groups from SimpleChat",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "user_id": {
                                    "type": "string",
                                    "description": "User ID to list groups for"
                                },
                                "page": {
                                    "type": "integer",
                                    "description": "Page number for pagination",
                                    "default": 1
                                },
                                "page_size": {
                                    "type": "integer",
                                    "description": "Number of groups per page", 
                                    "default": 10
                                },
                                "search": {
                                    "type": "string",
                                    "description": "Search term for filtering groups"
                                }
                            },
                            "required": ["user_id"]
                        }
                    ),
                    Tool(
                        name="get_settings",
                        description="Get application settings from SimpleChat",
                        inputSchema={
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    ),
                    Tool(
                        name="update_settings",
                        description="Update application settings in SimpleChat",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "settings": {
                                    "type": "object",
                                    "description": "Settings object to update"
                                }
                            },
                            "required": ["settings"]
                        }
                    ),
                    Tool(
                        name="test_token",
                        description="Test the validity of the bearer token",
                        inputSchema={
                            "type": "object", 
                            "properties": {},
                            "required": []
                        }
                    )
                ]
            )
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> CallToolResult:
            """Handle tool calls"""
            try:
                if name == "send_message":
                    return await self._send_message(arguments)
                elif name == "list_documents":
                    return await self._list_documents(arguments)
                elif name == "upload_document":
                    return await self._upload_document(arguments)
                elif name == "list_groups":
                    return await self._list_groups(arguments)
                elif name == "get_settings":
                    return await self._get_settings(arguments)
                elif name == "update_settings":
                    return await self._update_settings(arguments)
                elif name == "test_token":
                    return await self._test_token(arguments)
                else:
                    raise JSONRPCError(
                        code=INVALID_REQUEST,
                        message=f"Unknown tool: {name}"
                    )
                    
            except Exception as e:
                self.logger.error(f"Error calling tool {name}: {e}")
                raise JSONRPCError(
                    code=ErrorCode.INTERNAL_ERROR,
                    message=f"Tool execution failed: {str(e)}"
                )
    
    async def _send_message(self, arguments: Dict[str, Any]) -> CallToolResult:
        """Send a chat message to SimpleChat"""
        try:
            response = await self.http_client.post(
                "/external/chat",
                json=arguments
            )
            response.raise_for_status()
            
            result = response.json()
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )],
                isError=False
            )
        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error sending message: {e}")
            return CallToolResult(
                content=[TextContent(
                    type="text", 
                    text=f"Error sending message: {str(e)}"
                )],
                isError=True
            )
    
    async def _list_documents(self, arguments: Dict[str, Any]) -> CallToolResult:
        """List user documents"""
        try:
            params = {k: v for k, v in arguments.items() if k != "user_id"}
            params["user_id"] = arguments["user_id"]
            
            response = await self.http_client.get(
                "/external/documents",
                params=params
            )
            response.raise_for_status()
            
            result = response.json()
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )],
                isError=False
            )
        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error listing documents: {e}")
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=f"Error listing documents: {str(e)}"
                )],
                isError=True
            )
    
    async def _upload_document(self, arguments: Dict[str, Any]) -> CallToolResult:
        """Upload a document to SimpleChat"""
        try:
            file_path = arguments["file_path"]
            user_id = arguments["user_id"]
            filename = arguments.get("filename", os.path.basename(file_path))
            
            if not os.path.exists(file_path):
                return CallToolResult(
                    content=[TextContent(
                        type="text",
                        text=f"File not found: {file_path}"
                    )],
                    isError=True
                )
            
            with open(file_path, "rb") as f:
                files = {"file": (filename, f, "application/octet-stream")}
                data = {"user_id": user_id}
                
                # Use a new client without JSON headers for multipart upload
                upload_client = httpx.AsyncClient(
                    base_url=self.config.simplechat_base_url,
                    timeout=httpx.Timeout(60.0),
                    headers={
                        "Authorization": f"Bearer {self.config.simplechat_bearer_token}"
                    }
                )
                
                response = await upload_client.post(
                    "/external/documents/upload",
                    files=files,
                    data=data
                )
                response.raise_for_status()
                await upload_client.aclose()
            
            result = response.json()
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )],
                isError=False
            )
        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error uploading document: {e}")
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=f"Error uploading document: {str(e)}"
                )],
                isError=True
            )
    
    async def _list_groups(self, arguments: Dict[str, Any]) -> CallToolResult:
        """List user groups"""
        try:
            # Since the external groups endpoint expects user_id from auth,
            # we need to pass it properly  
            params = {k: v for k, v in arguments.items() if k != "user_id"}
            
            response = await self.http_client.get(
                "/external/groups",
                params=params
            )
            response.raise_for_status()
            
            result = response.json()
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )],
                isError=False
            )
        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error listing groups: {e}")
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=f"Error listing groups: {str(e)}"
                )],
                isError=True
            )
    
    async def _get_settings(self, arguments: Dict[str, Any]) -> CallToolResult:
        """Get application settings"""
        try:
            response = await self.http_client.get("/external/applicationsettings/get")
            response.raise_for_status()
            
            result = response.json()
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )],
                isError=False
            )
        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error getting settings: {e}")
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=f"Error getting settings: {str(e)}"
                )],
                isError=True
            )
    
    async def _update_settings(self, arguments: Dict[str, Any]) -> CallToolResult:
        """Update application settings"""
        try:
            settings_data = arguments.get("settings", {})
            response = await self.http_client.post(
                "/external/applicationsettings/set",
                json=settings_data
            )
            response.raise_for_status()
            
            result = response.json()
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )],
                isError=False
            )
        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error updating settings: {e}")
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=f"Error updating settings: {str(e)}"
                )],
                isError=True
            )
    
    async def _test_token(self, arguments: Dict[str, Any]) -> CallToolResult:
        """Test bearer token validity"""
        try:
            response = await self.http_client.get("/external/healthcheck")
            response.raise_for_status()
            
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=f"Token is valid. Health check returned: {response.text}"
                )],
                isError=False
            )
        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error testing token: {e}")
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=f"Token test failed: {str(e)}"
                )],
                isError=True
            )
    
    async def run(self, transport_type: str = "stdio"):
        """Run the MCP server"""
        if transport_type == "stdio":
            from mcp.server.stdio import stdio_server
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    self.server.create_initialization_options()
                )
        else:
            raise ValueError(f"Unsupported transport type: {transport_type}")


async def main():
    """Main entry point"""
    config = SimpleChatConfig()
    
    # Validate configuration
    if not config.simplechat_bearer_token:
        raise ValueError("SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN environment variable is required")
    
    server = SimpleChatMCPServer(config)
    await server.run()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())