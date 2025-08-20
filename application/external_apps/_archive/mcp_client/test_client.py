#!/usr/bin/env python3
"""
Test script for SimpleChat MCP Client

This script tests both the direct MCP client and the Semantic Kernel plugin
to ensure everything is working correctly.
"""

import os
import sys
import asyncio
import json
import logging
from typing import Dict, Any

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from simplechat_mcp_client import SimpleChatMCPClient, SimpleChatMCPClientConfig, create_mcp_client
from mcp_client_plugin import SimpleChatMCPPlugin, add_simplechat_plugin

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_mcp_client_direct():
    """Test the MCP client directly"""
    logger.info("=== Testing MCP Client Direct Usage ===")
    
    try:
        async with create_mcp_client() as client:
            logger.info("✓ Successfully connected to MCP server")
            
            # Test token validation
            logger.info("Testing token validation...")
            token_result = await client.test_token()
            logger.info(f"Token test result: {token_result}")
            
            # Test getting settings
            logger.info("Testing get settings...")
            settings_result = await client.get_settings()
            logger.info(f"Settings result: {settings_result}")
            
            # Test listing documents
            logger.info("Testing list documents...")
            docs_result = await client.list_documents(
                user_id="test_user",
                page=1,
                size=5
            )
            logger.info(f"Documents result: {docs_result}")
            
            # Test listing groups
            logger.info("Testing list groups...")
            groups_result = await client.list_groups(
                user_id="test_user",
                page=1,
                size=5
            )
            logger.info(f"Groups result: {groups_result}")
            
            # Test sending a message
            logger.info("Testing send message...")
            message_result = await client.send_message(
                user_id="test_user",
                message="Hello from MCP client test!",
                hybrid_search=False,
                bing_search=False
            )
            logger.info(f"Message result: {message_result}")
            
        logger.info("✓ All direct client tests completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"✗ Direct client test failed: {e}")
        return False


async def test_semantic_kernel_plugin():
    """Test the Semantic Kernel plugin"""
    logger.info("=== Testing Semantic Kernel Plugin ===")
    
    try:
        # Import Semantic Kernel
        try:
            import semantic_kernel as sk
        except ImportError:
            logger.warning("Semantic Kernel not installed, skipping plugin tests")
            return True
        
        # Create kernel
        kernel = sk.Kernel()
        
        # Add SimpleChat plugin
        plugin = add_simplechat_plugin(kernel, "simplechat")
        logger.info("✓ Successfully added SimpleChat plugin to kernel")
        
        # Test token validation through SK
        logger.info("Testing token validation through SK...")
        result = await kernel.invoke("simplechat", "test_token")
        logger.info(f"SK Token test result: {result}")
        
        # Test get settings through SK
        logger.info("Testing get settings through SK...")
        result = await kernel.invoke("simplechat", "get_settings")
        logger.info(f"SK Settings result: {result}")
        
        # Test list documents through SK
        logger.info("Testing list documents through SK...")
        result = await kernel.invoke("simplechat", "list_documents", {
            "user_id": "test_user",
            "page": 1,
            "size": 5
        })
        logger.info(f"SK Documents result: {result}")
        
        # Test send message through SK
        logger.info("Testing send message through SK...")
        result = await kernel.invoke("simplechat", "send_message", {
            "user_id": "test_user",
            "message": "Hello from SK plugin test!",
            "hybrid_search": False,
            "bing_search": False
        })
        logger.info(f"SK Message result: {result}")
        
        logger.info("✓ All Semantic Kernel plugin tests completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"✗ Semantic Kernel plugin test failed: {e}")
        return False


async def test_configuration():
    """Test configuration loading"""
    logger.info("=== Testing Configuration ===")
    
    try:
        # Test default configuration
        config = SimpleChatMCPClientConfig()
        logger.info(f"Default server path: {config.server_path}")
        logger.info(f"Default timeout: {config.timeout}")
        logger.info(f"Default log level: {config.log_level}")
        
        # Test custom configuration
        custom_config = SimpleChatMCPClientConfig(
            server_path="/custom/path/server.py",
            timeout=60,
            log_level="DEBUG"
        )
        logger.info(f"Custom server path: {custom_config.server_path}")
        logger.info(f"Custom timeout: {custom_config.timeout}")
        logger.info(f"Custom log level: {custom_config.log_level}")
        
        logger.info("✓ Configuration tests completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"✗ Configuration test failed: {e}")
        return False


async def main():
    """Run all tests"""
    logger.info("Starting SimpleChat MCP Client Tests")
    logger.info("=" * 50)
    
    # Check if MCP server is accessible
    config = SimpleChatMCPClientConfig()
    server_path = os.path.abspath(config.server_path)
    
    if not os.path.exists(server_path):
        logger.error(f"MCP server not found at: {server_path}")
        logger.error("Please ensure the MCP server is installed and the path is correct")
        return False
    
    logger.info(f"Using MCP server at: {server_path}")
    
    # Run tests
    tests = [
        ("Configuration", test_configuration),
        ("MCP Client Direct", test_mcp_client_direct),
        ("Semantic Kernel Plugin", test_semantic_kernel_plugin),
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info(f"\nRunning {test_name} tests...")
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error(f"Test {test_name} crashed: {e}")
            results.append((test_name, False))
    
    # Print summary
    logger.info("\n" + "=" * 50)
    logger.info("TEST SUMMARY")
    logger.info("=" * 50)
    
    all_passed = True
    for test_name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        logger.info(f"{test_name}: {status}")
        if not passed:
            all_passed = False
    
    if all_passed:
        logger.info("\n🎉 All tests passed!")
        return True
    else:
        logger.error("\n❌ Some tests failed. Please check the logs above.")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)