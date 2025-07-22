#!/usr/bin/env python3
"""
Test script for SimpleChat MCP Server

This script tests the MCP server can be imported and initialized correctly.
"""

import os
import sys
import asyncio

# Add the mcp_server directory to the path
sys.path.insert(0, os.path.dirname(__file__))

from simplechat_mcp_server import SimpleChatConfig, SimpleChatMCPServer


async def test_server_initialization():
    """Test that the server can be initialized"""
    print("Testing SimpleChat MCP Server initialization...")
    
    # Create test config
    config = SimpleChatConfig(
        simplechat_base_url="http://localhost:5000",
        simplechat_bearer_token="test-token",
        log_level="DEBUG"
    )
    
    # Initialize server
    server = SimpleChatMCPServer(config)
    print("✓ Server initialized successfully")
    
    # Test configuration
    assert config.simplechat_base_url == "http://localhost:5000"
    assert config.simplechat_bearer_token == "test-token" 
    assert config.log_level == "DEBUG"
    print("✓ Configuration values correct")
    
    # Test server has expected attributes
    assert hasattr(server, 'server')
    assert hasattr(server, 'http_client')
    assert hasattr(server, 'config')
    assert hasattr(server, 'logger')
    print("✓ Server has expected attributes")
    
    print("✓ All tests passed!")


if __name__ == "__main__":
    asyncio.run(test_server_initialization())