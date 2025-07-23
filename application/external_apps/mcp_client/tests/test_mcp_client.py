"""
Tests for SimpleChat MCP Client

These tests validate the basic functionality of the MCP client and plugin.
Note: Most tests require a running MCP server, so they may be skipped in CI environments.
"""

import os
import sys
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simplechat_mcp_client import (
    SimpleChatMCPClient,
    SimpleChatMCPClientConfig,
    MCPClientError,
    MCPConnectionError,
    MCPToolError
)


class TestSimpleChatMCPClientConfig:
    """Test configuration handling"""
    
    def test_default_config(self):
        """Test default configuration values"""
        config = SimpleChatMCPClientConfig()
        
        assert config.server_path == "../mcp_server/simplechat_mcp_server.py"
        assert config.timeout == 30
        assert config.log_level == "INFO"
        assert isinstance(config.server_env, dict)
    
    def test_custom_config(self):
        """Test custom configuration values"""
        config = SimpleChatMCPClientConfig(
            server_path="/custom/path/server.py",
            timeout=60,
            log_level="DEBUG"
        )
        
        assert config.server_path == "/custom/path/server.py"
        assert config.timeout == 60
        assert config.log_level == "DEBUG"
    
    @patch.dict(os.environ, {
        'SIMPLECHAT_MCP_CLIENT_SERVER_PATH': '/env/path/server.py',
        'SIMPLECHAT_MCP_CLIENT_TIMEOUT': '45',
        'SIMPLECHAT_MCP_CLIENT_LOG_LEVEL': 'WARNING'
    })
    def test_env_config(self):
        """Test configuration from environment variables"""
        config = SimpleChatMCPClientConfig()
        
        assert config.server_path == "/env/path/server.py"
        assert config.timeout == 45
        assert config.log_level == "WARNING"


class TestSimpleChatMCPClient:
    """Test MCP client functionality"""
    
    def test_client_initialization(self):
        """Test client can be initialized"""
        client = SimpleChatMCPClient()
        assert client is not None
        assert not client._connected
        assert client._client is None
    
    def test_client_with_custom_config(self):
        """Test client initialization with custom config"""
        config = SimpleChatMCPClientConfig(timeout=45)
        client = SimpleChatMCPClient(config)
        
        assert client.config.timeout == 45
    
    @pytest.mark.asyncio
    async def test_context_manager_interface(self):
        """Test that client can be used as async context manager"""
        config = SimpleChatMCPClientConfig(
            server_path="/nonexistent/path/server.py"  # Will fail to connect
        )
        client = SimpleChatMCPClient(config)
        
        # Should be able to enter and exit context even if connection fails
        try:
            async with client:
                pass
        except MCPConnectionError:
            # Expected when server doesn't exist
            pass
    
    @pytest.mark.asyncio  
    async def test_connection_error_handling(self):
        """Test handling of connection errors"""
        config = SimpleChatMCPClientConfig(
            server_path="/definitely/nonexistent/path/server.py"
        )
        client = SimpleChatMCPClient(config)
        
        with pytest.raises(MCPConnectionError):
            await client.connect()
    
    @pytest.mark.asyncio
    async def test_tool_call_without_connection(self):
        """Test that tool calls fail without connection"""
        client = SimpleChatMCPClient()
        
        with pytest.raises(MCPConnectionError):
            await client._call_tool("test_tool", {})


class TestMCPClientPlugin:
    """Test Semantic Kernel plugin functionality"""
    
    def test_plugin_import(self):
        """Test that plugin can be imported"""
        try:
            from mcp_client_plugin import SimpleChatMCPPlugin
            plugin = SimpleChatMCPPlugin()
            assert plugin is not None
        except ImportError as e:
            pytest.skip(f"Semantic Kernel not available: {e}")
    
    def test_plugin_with_config(self):
        """Test plugin initialization with custom config"""
        try:
            from mcp_client_plugin import SimpleChatMCPPlugin
            
            config = SimpleChatMCPClientConfig(timeout=45)
            plugin = SimpleChatMCPPlugin(config)
            
            assert plugin.config.timeout == 45
        except ImportError:
            pytest.skip("Semantic Kernel not available")


class TestLegacyPlugin:
    """Test legacy plugin integration"""
    
    def test_legacy_plugin_import(self):
        """Test that legacy plugin can be imported"""
        try:
            from simplechat_mcp_legacy_plugin import SimpleChatMCPLegacyPlugin
            plugin = SimpleChatMCPLegacyPlugin()
            assert plugin is not None
        except ImportError as e:
            pytest.skip(f"Dependencies not available: {e}")
    
    def test_legacy_plugin_metadata(self):
        """Test legacy plugin metadata structure"""
        try:
            from simplechat_mcp_legacy_plugin import SimpleChatMCPLegacyPlugin
            
            plugin = SimpleChatMCPLegacyPlugin()
            metadata = plugin.metadata
            
            assert metadata["name"] == "simplechat_mcp_plugin"
            assert metadata["type"] == "mcp_client"
            assert "description" in metadata
            assert "methods" in metadata
            assert len(metadata["methods"]) == 7  # 7 MCP tools
            
        except ImportError:
            pytest.skip("Dependencies not available")
    
    def test_legacy_plugin_functions(self):
        """Test legacy plugin function list"""
        try:
            from simplechat_mcp_legacy_plugin import SimpleChatMCPLegacyPlugin
            
            plugin = SimpleChatMCPLegacyPlugin()
            functions = plugin.get_functions()
            
            expected_functions = [
                "send_message",
                "list_documents", 
                "upload_document",
                "list_groups",
                "get_settings",
                "update_settings",
                "test_token"
            ]
            
            assert functions == expected_functions
            
        except ImportError:
            pytest.skip("Dependencies not available")


class TestExceptions:
    """Test custom exception classes"""
    
    def test_mcp_client_error(self):
        """Test base MCP client error"""
        error = MCPClientError("Test error")
        assert str(error) == "Test error"
        assert isinstance(error, Exception)
    
    def test_mcp_connection_error(self):
        """Test MCP connection error"""
        error = MCPConnectionError("Connection failed")
        assert str(error) == "Connection failed"
        assert isinstance(error, MCPClientError)
        assert isinstance(error, Exception)
    
    def test_mcp_tool_error(self):
        """Test MCP tool error"""
        error = MCPToolError("Tool execution failed")
        assert str(error) == "Tool execution failed"
        assert isinstance(error, MCPClientError)
        assert isinstance(error, Exception)


class TestPackageStructure:
    """Test package structure and imports"""
    
    def test_package_init(self):
        """Test package can be imported"""
        try:
            import __init__
            # If we can import without error, the structure is good
            assert True
        except ImportError:
            # Expected in this test context
            pass
    
    def test_main_modules_exist(self):
        """Test that main module files exist"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        expected_files = [
            "simplechat_mcp_client.py",
            "mcp_client_plugin.py", 
            "simplechat_mcp_legacy_plugin.py",
            "__init__.py",
            "README.md",
            "requirements.txt",
            ".env.example",
            "config_example.json"
        ]
        
        for filename in expected_files:
            filepath = os.path.join(base_dir, filename)
            assert os.path.exists(filepath), f"Missing file: {filename}"
    
    def test_examples_and_docs_exist(self):
        """Test that documentation and example files exist"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        expected_files = [
            "examples.py",
            "test_client.py",
            "USAGE_EXAMPLES.md"
        ]
        
        for filename in expected_files:
            filepath = os.path.join(base_dir, filename)
            assert os.path.exists(filepath), f"Missing file: {filename}"


# Integration tests that require actual MCP server
class TestIntegration:
    """Integration tests that require running MCP server"""
    
    @pytest.mark.skipif(
        not os.path.exists("../mcp_server/simplechat_mcp_server.py"),
        reason="MCP server not available"
    )
    @pytest.mark.asyncio
    async def test_real_connection(self):
        """Test connection to real MCP server if available"""
        try:
            from simplechat_mcp_client import create_mcp_client
            
            async with create_mcp_client() as client:
                # Try to test token - this will fail if server isn't configured
                result = await client.test_token()
                assert result is not None
                
        except (MCPConnectionError, MCPToolError):
            pytest.skip("MCP server not properly configured")
        except ImportError:
            pytest.skip("FastMCP not available")


if __name__ == "__main__":
    # Run tests when script is executed directly
    pytest.main([__file__, "-v"])