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
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import httpx
from fastmcp import FastMCP
from pydantic_settings import BaseSettings, SettingsConfigDict


class SimpleChatConfig(BaseSettings):
    """Configuration for SimpleChat MCP Server"""
    
    model_config = SettingsConfigDict(env_prefix="SIMPLECHAT_MCP_", env_file=".env", extra="ignore")
    
    # SimpleChat API Configuration
    simplechat_base_url: str = "http://localhost:5000"
    simplechat_bearer_token: str = ""
    
    # Health check server
    health_port: int = 8080
    
    # Logging
    log_level: str = "INFO"


# Initialize configuration
config = SimpleChatConfig()

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# HTTP client for API calls
http_client = httpx.AsyncClient(
    base_url=config.simplechat_base_url,
    headers={
        "Authorization": f"Bearer {config.simplechat_bearer_token}",
        "Content-Type": "application/json"
    },
    timeout=30.0
)

# Health check status
_server_ready = False


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for health checks"""
    
    def do_GET(self):
        """Handle GET requests for health checks"""
        if self.path == '/health':
            # Liveness probe - server is running
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {
                "status": "healthy",
                "timestamp": datetime.utcnow().isoformat(),
                "service": "simplechat-mcp-server"
            }
            self.wfile.write(json.dumps(response).encode())
        elif self.path == '/ready':
            # Readiness probe - server is ready to accept requests
            if _server_ready and config.simplechat_bearer_token:
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                response = {
                    "status": "ready",
                    "timestamp": datetime.utcnow().isoformat(),
                    "service": "simplechat-mcp-server"
                }
                self.wfile.write(json.dumps(response).encode())
            else:
                self.send_response(503)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                response = {
                    "status": "not ready",
                    "timestamp": datetime.utcnow().isoformat(),
                    "service": "simplechat-mcp-server",
                    "reason": "Server not initialized or missing bearer token"
                }
                self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        """Override to suppress default request logging"""
        pass


def start_health_server():
    """Start the health check server in a separate thread"""
    global _server_ready
    try:
        server = HTTPServer(('0.0.0.0', config.health_port), HealthCheckHandler)
        logger.info(f"Health check server starting on port {config.health_port}")
        _server_ready = True
        server.serve_forever()
    except Exception as e:
        logger.error(f"Failed to start health server: {e}")
        _server_ready = False

# Initialize FastMCP server
mcp = FastMCP("SimpleChat MCP Server")


@mcp.tool
def send_message(
    user_id: str,
    message: str,
    hybrid_search: bool = False,
    bing_search: bool = False,
    active_group_id: Optional[str] = None,
    document_scope: Optional[List[str]] = None
) -> str:
    """Send a chat message to SimpleChat"""
    
    async def _send():
        try:
            data = {
                "user_id": user_id,
                "message": message,
                "hybrid_search": hybrid_search,
                "bing_search": bing_search,
            }
            if active_group_id:
                data["active_group_id"] = active_group_id
            if document_scope:
                data["document_scope"] = document_scope
                
            response = await http_client.post("/external/chat", json=data)
            response.raise_for_status()
            
            result = response.json()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return f"Error sending message: {str(e)}"
    
    return asyncio.run(_send())


@mcp.tool
def list_documents(
    user_id: str,
    page: int = 1,
    size: int = 10,
    search: Optional[str] = None
) -> str:
    """List user documents with pagination and search"""
    
    async def _list():
        try:
            params = {"user_id": user_id, "page": page, "size": size}
            if search:
                params["search"] = search
                
            response = await http_client.get("/external/documents/list", params=params)
            response.raise_for_status()
            
            result = response.json()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"Error listing documents: {e}")
            return f"Error listing documents: {str(e)}"
    
    return asyncio.run(_list())


@mcp.tool
def upload_document(
    user_id: str,
    file_path: str,
    filename: Optional[str] = None
) -> str:
    """Upload a document to SimpleChat"""
    
    async def _upload():
        try:
            if not os.path.exists(file_path):
                return f"File not found: {file_path}"
            
            file_name = filename or os.path.basename(file_path)
            
            # Use a separate client for file upload (without JSON content-type)
            upload_client = httpx.AsyncClient(
                base_url=config.simplechat_base_url,
                headers={
                    "Authorization": f"Bearer {config.simplechat_bearer_token}"
                },
                timeout=300.0  # Longer timeout for file uploads
            )
            
            try:
                with open(file_path, 'rb') as file:
                    files = {
                        'file': (file_name, file, 'application/octet-stream')
                    }
                    data = {
                        'user_id': user_id
                    }
                    
                    response = await upload_client.post(
                        "/external/documents/upload",
                        files=files,
                        data=data
                    )
                    response.raise_for_status()
                    
                    result = response.json()
                    return json.dumps(result, indent=2)
            finally:
                await upload_client.aclose()
                
        except Exception as e:
            logger.error(f"Error uploading document: {e}")
            return f"Error uploading document: {str(e)}"
    
    return asyncio.run(_upload())


@mcp.tool
def list_groups(
    user_id: str,
    page: int = 1,
    size: int = 10,
    search: Optional[str] = None
) -> str:
    """List user groups with pagination and search"""
    
    async def _list():
        try:
            params = {"user_id": user_id, "page": page, "size": size}
            if search:
                params["search"] = search
                
            response = await http_client.get("/external/groups", params=params)
            response.raise_for_status()
            
            result = response.json()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"Error listing groups: {e}")
            return f"Error listing groups: {str(e)}"
    
    return asyncio.run(_list())


@mcp.tool
def get_settings() -> str:
    """Get application settings"""
    
    async def _get():
        try:
            response = await http_client.get("/external/applicationsettings/get")
            response.raise_for_status()
            
            result = response.json()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"Error getting settings: {e}")
            return f"Error getting settings: {str(e)}"
    
    return asyncio.run(_get())


@mcp.tool
def update_settings(settings: Dict[str, Any]) -> str:
    """Update application settings"""
    
    async def _update():
        try:
            response = await http_client.post(
                "/external/applicationsettings/set",
                json=settings
            )
            response.raise_for_status()
            
            result = response.json()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"Error updating settings: {e}")
            return f"Error updating settings: {str(e)}"
    
    return asyncio.run(_update())


@mcp.tool
def test_token() -> str:
    """Test bearer token validity"""
    
    async def _test():
        try:
            response = await http_client.get("/external/healthcheck")
            response.raise_for_status()
            
            return f"Token is valid. Health check returned: {response.text}"
        except Exception as e:
            logger.error(f"Error testing token: {e}")
            return f"Token test failed: {str(e)}"
    
    return asyncio.run(_test())


def main():
    """Main entry point"""
    # Validate configuration
    if not config.simplechat_bearer_token:
        raise ValueError("SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN environment variable is required")
    
    logger.info(f"Starting SimpleChat MCP Server with base URL: {config.simplechat_base_url}")
    
    # Start health check server in a separate thread
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()


if __name__ == "__main__":
    main()
    mcp.run()