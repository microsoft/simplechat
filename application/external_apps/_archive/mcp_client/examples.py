#!/usr/bin/env python3
"""
SimpleChat MCP Client Examples

This script demonstrates various usage patterns for the SimpleChat MCP client,
including direct client usage, Semantic Kernel integration, and advanced workflows.
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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def example_direct_client():
    """Example: Using the MCP client directly"""
    print("\n" + "="*60)
    print("EXAMPLE 1: Direct MCP Client Usage")
    print("="*60)
    
    async with create_mcp_client() as client:
        print("✓ Connected to SimpleChat MCP server")
        
        # Example 1: Send a simple message
        print("\n1. Sending a simple message...")
        result = await client.send_message(
            user_id="demo_user",
            message="What is artificial intelligence?",
            hybrid_search=False
        )
        print(f"Response: {result[:200]}..." if len(result) > 200 else f"Response: {result}")
        
        # Example 2: Search-enabled message
        print("\n2. Sending a message with hybrid search...")
        result = await client.send_message(
            user_id="demo_user",
            message="Find information about machine learning algorithms",
            hybrid_search=True,
            bing_search=True
        )
        print(f"Search-enabled response: {result[:200]}..." if len(result) > 200 else f"Response: {result}")
        
        # Example 3: List documents
        print("\n3. Listing user documents...")
        result = await client.list_documents(
            user_id="demo_user",
            page=1,
            size=5,
            search="AI"
        )
        print(f"Documents: {result[:300]}..." if len(result) > 300 else f"Documents: {result}")
        
        # Example 4: List groups
        print("\n4. Listing user groups...")
        result = await client.list_groups(
            user_id="demo_user",
            page=1,
            size=5
        )
        print(f"Groups: {result[:300]}..." if len(result) > 300 else f"Groups: {result}")


async def example_semantic_kernel_basic():
    """Example: Basic Semantic Kernel integration"""
    print("\n" + "="*60)
    print("EXAMPLE 2: Basic Semantic Kernel Integration")
    print("="*60)
    
    try:
        import semantic_kernel as sk
    except ImportError:
        print("⚠️  Semantic Kernel not installed. Install with: pip install semantic-kernel")
        return
    
    # Create kernel and add SimpleChat plugin
    kernel = sk.Kernel()
    plugin = add_simplechat_plugin(kernel, "simplechat")
    print("✓ Added SimpleChat plugin to Semantic Kernel")
    
    # Example 1: Call functions directly
    print("\n1. Calling MCP functions through Semantic Kernel...")
    
    # Test token
    result = await kernel.invoke("simplechat", "test_token")
    print(f"Token test: {result}")
    
    # Send message
    result = await kernel.invoke("simplechat", "send_message", {
        "user_id": "sk_demo_user",
        "message": "Hello from Semantic Kernel!",
        "hybrid_search": False
    })
    print(f"SK Message result: {result[:200]}..." if len(result) > 200 else f"Result: {result}")
    
    # List documents
    result = await kernel.invoke("simplechat", "list_documents", {
        "user_id": "sk_demo_user",
        "page": 1,
        "size": 3
    })
    print(f"SK Documents: {result[:200]}..." if len(result) > 200 else f"Documents: {result}")


async def example_semantic_kernel_agent():
    """Example: Using SimpleChat with Semantic Kernel agents"""
    print("\n" + "="*60)
    print("EXAMPLE 3: Semantic Kernel Agent Integration")
    print("="*60)
    
    try:
        import semantic_kernel as sk
        from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
    except ImportError:
        print("⚠️  Required packages not installed. This example needs:")
        print("   pip install semantic-kernel openai")
        return
    
    # Check for OpenAI API key
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️  OPENAI_API_KEY environment variable not set")
        print("   This example requires an OpenAI API key to demonstrate agent functionality")
        return
    
    try:
        # Create kernel with OpenAI service
        kernel = sk.Kernel()
        
        # Add OpenAI chat completion service
        kernel.add_service(OpenAIChatCompletion(
            ai_model_id="gpt-3.5-turbo",
            api_key=os.getenv("OPENAI_API_KEY")
        ))
        
        # Add SimpleChat plugin
        plugin = add_simplechat_plugin(kernel, "simplechat")
        print("✓ Created kernel with OpenAI service and SimpleChat plugin")
        
        # Create a prompt that uses SimpleChat functions
        prompt = """
        You are an AI assistant that can help users with SimpleChat functionality.
        You have access to SimpleChat functions through the 'simplechat' plugin.
        
        Available functions:
        - simplechat.send_message: Send messages to SimpleChat
        - simplechat.list_documents: List user documents
        - simplechat.list_groups: List user groups
        - simplechat.get_settings: Get application settings
        - simplechat.test_token: Test authentication
        
        User request: {{$request}}
        
        Please help the user by using the appropriate SimpleChat functions.
        """
        
        # Create a function from the prompt
        chat_function = kernel.create_function_from_prompt(
            prompt=prompt,
            function_name="simplechat_assistant"
        )
        
        # Example requests
        requests = [
            "Test if my authentication token is working",
            "List my first 3 documents",
            "Send a message saying 'Hello from AI agent' to user 'agent_demo_user'"
        ]
        
        for i, request in enumerate(requests, 1):
            print(f"\n{i}. Processing request: '{request}'")
            try:
                result = await kernel.invoke(chat_function, request=request)
                print(f"   Agent response: {result}")
            except Exception as e:
                print(f"   Error: {e}")
    
    except Exception as e:
        print(f"⚠️  Agent example failed: {e}")


async def example_workflow():
    """Example: Complex workflow using SimpleChat MCP client"""
    print("\n" + "="*60)
    print("EXAMPLE 4: Complex Workflow")
    print("="*60)
    
    async with create_mcp_client() as client:
        print("✓ Connected for workflow example")
        
        user_id = "workflow_demo_user"
        
        # Step 1: Validate authentication
        print("\n1. Validating authentication...")
        token_result = await client.test_token()
        print(f"   Authentication: {token_result[:100]}...")
        
        # Step 2: Get current settings
        print("\n2. Getting current settings...")
        settings_result = await client.get_settings()
        print(f"   Settings: {settings_result[:150]}...")
        
        # Step 3: List existing documents
        print("\n3. Listing existing documents...")
        docs_result = await client.list_documents(
            user_id=user_id,
            page=1,
            size=5
        )
        print(f"   Documents: {docs_result[:200]}...")
        
        # Step 4: List available groups
        print("\n4. Listing available groups...")
        groups_result = await client.list_groups(
            user_id=user_id,
            page=1,
            size=5
        )
        print(f"   Groups: {groups_result[:200]}...")
        
        # Step 5: Send a summary message
        print("\n5. Sending workflow summary message...")
        summary_message = f"""
        Workflow completed successfully! Summary:
        - Authentication: Validated
        - Settings: Retrieved
        - Documents: Listed (page 1)
        - Groups: Listed (page 1)
        - Timestamp: {asyncio.get_event_loop().time()}
        """
        
        message_result = await client.send_message(
            user_id=user_id,
            message=summary_message.strip(),
            hybrid_search=False
        )
        print(f"   Summary sent: {message_result[:150]}...")
        
        print("\n✓ Workflow completed successfully!")


async def example_error_handling():
    """Example: Error handling patterns"""
    print("\n" + "="*60)
    print("EXAMPLE 5: Error Handling")
    print("="*60)
    
    from simplechat_mcp_client import MCPClientError, MCPConnectionError, MCPToolError
    
    # Example 1: Connection error handling
    print("\n1. Testing connection error handling...")
    try:
        # Try to connect with invalid server path
        config = SimpleChatMCPClientConfig(
            server_path="/invalid/path/server.py"
        )
        client = SimpleChatMCPClient(config)
        await client.connect()
    except MCPConnectionError as e:
        print(f"   ✓ Caught connection error: {e}")
    except Exception as e:
        print(f"   ✓ Caught general error: {e}")
    
    # Example 2: Tool error handling with valid connection
    print("\n2. Testing tool error handling...")
    try:
        async with create_mcp_client() as client:
            # Try to call with invalid parameters
            result = await client.send_message(
                user_id="",  # Empty user_id might cause error
                message="Test message"
            )
            print(f"   Unexpected success: {result[:100]}...")
    except MCPToolError as e:
        print(f"   ✓ Caught tool error: {e}")
    except Exception as e:
        print(f"   ✓ Caught general error: {e}")
    
    # Example 3: Graceful error handling in SK plugin
    print("\n3. Testing Semantic Kernel plugin error handling...")
    try:
        import semantic_kernel as sk
        
        kernel = sk.Kernel()
        plugin = add_simplechat_plugin(kernel, "simplechat")
        
        # This should handle errors gracefully
        result = await kernel.invoke("simplechat", "list_documents", {
            "user_id": "",  # Invalid user_id
            "page": 1,
            "size": 5
        })
        print(f"   Plugin error handling result: {result}")
    except ImportError:
        print("   ⚠️  Semantic Kernel not available for error handling test")
    except Exception as e:
        print(f"   Error in SK plugin test: {e}")


async def main():
    """Run all examples"""
    print("SimpleChat MCP Client Examples")
    print("=" * 60)
    print("This script demonstrates various usage patterns for the SimpleChat MCP client.")
    print()
    
    # Check if MCP server is accessible
    config = SimpleChatMCPClientConfig()
    server_path = os.path.abspath(config.server_path)
    
    if not os.path.exists(server_path):
        print(f"⚠️  MCP server not found at: {server_path}")
        print("Please ensure the MCP server is installed and the configuration is correct.")
        print()
        print("To set up the server path, you can:")
        print("1. Copy .env.example to .env and configure SIMPLECHAT_MCP_CLIENT_SERVER_PATH")
        print("2. Or set the environment variable directly")
        return
    
    print(f"✓ Using MCP server at: {server_path}")
    
    # Run examples
    examples = [
        example_direct_client,
        example_semantic_kernel_basic,
        example_semantic_kernel_agent,
        example_workflow,
        example_error_handling
    ]
    
    for example in examples:
        try:
            await example()
        except KeyboardInterrupt:
            print("\n⚠️  Interrupted by user")
            break
        except Exception as e:
            print(f"\n❌ Example failed: {e}")
            logger.exception("Example failed with exception")
    
    print("\n" + "="*60)
    print("Examples completed!")
    print("="*60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Script failed: {e}")
        sys.exit(1)