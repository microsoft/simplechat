# SimpleChat MCP Client - Usage Examples

This document provides comprehensive usage examples for the SimpleChat MCP Client, demonstrating various integration patterns and use cases.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Direct Client Usage](#direct-client-usage)
3. [Semantic Kernel Integration](#semantic-kernel-integration)
4. [Advanced Workflows](#advanced-workflows)
5. [Error Handling](#error-handling)
6. [Configuration Examples](#configuration-examples)
7. [Best Practices](#best-practices)

## Quick Start

### Installation

```bash
cd application/external_apps/mcp_client
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your configuration
```

### Basic Usage

```python
from simplechat_mcp_client import create_mcp_client

async def main():
    async with create_mcp_client() as client:
        # Test connection
        result = await client.test_token()
        print(f"Connection test: {result}")
        
        # Send a message
        response = await client.send_message(
            user_id="user123",
            message="Hello, SimpleChat!"
        )
        print(f"Response: {response}")

import asyncio
asyncio.run(main())
```

## Direct Client Usage

### 1. Connection Management

```python
from simplechat_mcp_client import SimpleChatMCPClient, SimpleChatMCPClientConfig

# Method 1: Context manager (recommended)
async with create_mcp_client() as client:
    result = await client.test_token()

# Method 2: Manual connection management
client = SimpleChatMCPClient()
await client.connect()
try:
    result = await client.test_token()
finally:
    await client.disconnect()

# Method 3: Custom configuration
config = SimpleChatMCPClientConfig(
    server_path="/custom/path/to/server.py",
    timeout=60,
    log_level="DEBUG"
)
async with create_mcp_client(config) as client:
    result = await client.test_token()
```

### 2. Chat Operations

```python
async def chat_examples():
    async with create_mcp_client() as client:
        # Basic message
        response = await client.send_message(
            user_id="user123",
            message="What is machine learning?"
        )
        
        # Message with search
        response = await client.send_message(
            user_id="user123",
            message="Find information about neural networks",
            hybrid_search=True,
            bing_search=True
        )
        
        # Group message
        response = await client.send_message(
            user_id="user123",
            message="Team update: Project completed",
            active_group_id="group_456"
        )
        
        # Message with document scope
        response = await client.send_message(
            user_id="user123",
            message="Summarize the quarterly report",
            document_scope=["doc_123", "doc_456"],
            hybrid_search=True
        )
```

### 3. Document Management

```python
async def document_examples():
    async with create_mcp_client() as client:
        # List all documents
        docs = await client.list_documents(
            user_id="user123",
            page=1,
            size=20
        )
        
        # Search documents
        docs = await client.list_documents(
            user_id="user123",
            search="quarterly report",
            page=1,
            size=10
        )
        
        # Upload document
        result = await client.upload_document(
            user_id="user123",
            file_path="/path/to/document.pdf",
            filename="Q3_Report.pdf"
        )
```

### 4. Group Management

```python
async def group_examples():
    async with create_mcp_client() as client:
        # List all groups
        groups = await client.list_groups(
            user_id="user123",
            page=1,
            size=10
        )
        
        # Search groups
        groups = await client.list_groups(
            user_id="user123",
            search="development",
            page=1,
            size=5
        )
```

### 5. Settings Management

```python
async def settings_examples():
    async with create_mcp_client() as client:
        # Get current settings
        settings = await client.get_settings()
        print(f"Current settings: {settings}")
        
        # Update settings
        new_settings = {
            "theme": "dark",
            "notifications": True,
            "language": "en"
        }
        result = await client.update_settings(new_settings)
        print(f"Update result: {result}")
```

## Semantic Kernel Integration

### 1. Basic Plugin Usage

```python
import semantic_kernel as sk
from mcp_client_plugin import add_simplechat_plugin

# Create kernel and add plugin
kernel = sk.Kernel()
plugin = add_simplechat_plugin(kernel, "simplechat")

# Use functions directly
result = await kernel.invoke("simplechat", "send_message", {
    "user_id": "user123",
    "message": "Hello from SK!",
    "hybrid_search": True
})

result = await kernel.invoke("simplechat", "list_documents", {
    "user_id": "user123",
    "page": 1,
    "size": 5
})
```

### 2. Agent Integration

```python
from semantic_kernel.agents import ChatCompletionAgent
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion

# Set up kernel with AI service
kernel = sk.Kernel()
kernel.add_service(OpenAIChatCompletion(
    ai_model_id="gpt-4",
    api_key=os.getenv("OPENAI_API_KEY")
))

# Add SimpleChat plugin
add_simplechat_plugin(kernel, "simplechat")

# Create agent
agent = ChatCompletionAgent(
    kernel=kernel,
    name="SimpleChat Assistant",
    instructions="""
    You are an assistant that can help users with SimpleChat operations.
    You have access to SimpleChat functions through the 'simplechat' plugin.
    
    Available functions:
    - simplechat.send_message: Send messages
    - simplechat.list_documents: List documents
    - simplechat.list_groups: List groups
    - simplechat.upload_document: Upload files
    - simplechat.get_settings: Get settings
    - simplechat.update_settings: Update settings
    - simplechat.test_token: Test authentication
    """
)

# Use the agent
response = await agent.invoke(
    "Please list my recent documents and send a summary to the development team group"
)
```

### 3. Planner Integration

```python
from semantic_kernel.planning.function_calling_stepwise_planner import FunctionCallingStepwisePlanner

# Create planner
planner = FunctionCallingStepwisePlanner(kernel)

# Complex multi-step workflow
result = await planner.invoke("""
1. Test if my authentication is working
2. List my documents containing 'AI' in the title
3. Get the current application settings
4. Send a message to user 'manager123' summarizing what I found
""")
```

### 4. Custom SK Functions Using MCP

```python
@kernel_function(
    description="Enhanced document search and chat workflow",
    name="search_and_chat"
)
async def search_and_chat(
    kernel: sk.Kernel,
    user_id: str,
    search_term: str,
    target_user: str
) -> str:
    """Custom workflow combining multiple MCP operations"""
    
    # Search documents
    docs = await kernel.invoke("simplechat", "list_documents", {
        "user_id": user_id,
        "search": search_term,
        "size": 5
    })
    
    # Create summary message
    summary = f"Found documents related to '{search_term}': {docs[:200]}..."
    
    # Send to target user
    result = await kernel.invoke("simplechat", "send_message", {
        "user_id": target_user,
        "message": f"Document search results: {summary}",
        "hybrid_search": False
    })
    
    return result

# Add custom function to kernel
kernel.add_function(search_and_chat)
```

## Advanced Workflows

### 1. Document Analysis Workflow

```python
async def document_analysis_workflow(user_id: str):
    """Complete document analysis and reporting workflow"""
    
    async with create_mcp_client() as client:
        # Step 1: Get recent documents
        print("1. Fetching recent documents...")
        docs_result = await client.list_documents(
            user_id=user_id,
            page=1,
            size=10
        )
        
        # Step 2: Analyze document types (parse JSON response)
        import json
        try:
            docs_data = json.loads(docs_result)
            doc_count = len(docs_data.get('documents', []))
        except:
            doc_count = 0
        
        # Step 3: Get user groups for reporting
        print("2. Fetching user groups...")
        groups_result = await client.list_groups(
            user_id=user_id,
            page=1,
            size=5
        )
        
        # Step 4: Generate and send analysis report
        print("3. Generating analysis report...")
        report = f"""
        Document Analysis Report:
        - Total documents found: {doc_count}
        - Analysis completed at: {datetime.now().isoformat()}
        - User: {user_id}
        
        Raw document data:
        {docs_result[:500]}...
        
        Groups available for sharing:
        {groups_result[:300]}...
        """
        
        # Step 5: Send report
        print("4. Sending analysis report...")
        message_result = await client.send_message(
            user_id=user_id,
            message=report,
            hybrid_search=False
        )
        
        print("✓ Workflow completed successfully")
        return message_result
```

### 2. Batch Document Processing

```python
async def batch_document_processing(user_id: str, file_paths: List[str]):
    """Upload multiple documents and create summary"""
    
    async with create_mcp_client() as client:
        uploaded_docs = []
        
        # Upload all documents
        for file_path in file_paths:
            print(f"Uploading {file_path}...")
            try:
                result = await client.upload_document(
                    user_id=user_id,
                    file_path=file_path
                )
                uploaded_docs.append(f"✓ {file_path}: {result[:100]}...")
            except Exception as e:
                uploaded_docs.append(f"✗ {file_path}: {str(e)}")
        
        # Create summary message
        summary = f"""
        Batch Upload Summary:
        Total files processed: {len(file_paths)}
        
        Results:
        """ + "\n".join(uploaded_docs)
        
        # Send summary
        await client.send_message(
            user_id=user_id,
            message=summary,
            hybrid_search=False
        )
        
        return uploaded_docs
```

### 3. Settings Backup and Restore

```python
async def settings_backup_restore():
    """Backup and restore application settings"""
    
    async with create_mcp_client() as client:
        # Backup current settings
        print("Backing up current settings...")
        current_settings = await client.get_settings()
        
        # Save backup (in real app, save to file/database)
        backup = {
            "timestamp": datetime.now().isoformat(),
            "settings": current_settings
        }
        
        # Example: Modify settings
        print("Updating settings...")
        new_settings = {
            "backup_created": backup["timestamp"],
            "mode": "maintenance"
        }
        
        update_result = await client.update_settings(new_settings)
        print(f"Settings updated: {update_result}")
        
        # Verify changes
        updated_settings = await client.get_settings()
        print(f"Verified settings: {updated_settings[:200]}...")
        
        return backup
```

## Error Handling

### 1. Comprehensive Error Handling

```python
from simplechat_mcp_client import MCPClientError, MCPConnectionError, MCPToolError

async def robust_client_usage():
    """Example of robust error handling"""
    
    try:
        async with create_mcp_client() as client:
            # Test connection first
            try:
                await client.test_token()
                print("✓ Connection established")
            except MCPConnectionError as e:
                print(f"✗ Connection failed: {e}")
                return None
            
            # Attempt operations with retry logic
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    result = await client.send_message(
                        user_id="user123",
                        message="Test message"
                    )
                    print(f"✓ Message sent successfully: {result[:100]}...")
                    break
                    
                except MCPToolError as e:
                    print(f"✗ Tool error (attempt {attempt + 1}): {e}")
                    if attempt == max_retries - 1:
                        print("Max retries reached, giving up")
                        return None
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    
                except Exception as e:
                    print(f"✗ Unexpected error: {e}")
                    return None
            
            return result
            
    except Exception as e:
        print(f"✗ Critical error: {e}")
        return None
```

### 2. Semantic Kernel Error Handling

```python
async def sk_error_handling_example():
    """Example of error handling in SK context"""
    
    kernel = sk.Kernel()
    add_simplechat_plugin(kernel, "simplechat")
    
    # The plugin handles errors gracefully and returns error messages
    result = await kernel.invoke("simplechat", "send_message", {
        "user_id": "",  # Invalid user_id
        "message": "Test"
    })
    
    # Check if result indicates an error
    if result.startswith("Error") or result.startswith("MCP Error"):
        print(f"Operation failed: {result}")
        # Handle error appropriately
    else:
        print(f"Operation succeeded: {result}")
```

### 3. Timeout Handling

```python
import asyncio

async def timeout_handling_example():
    """Example of handling timeouts"""
    
    config = SimpleChatMCPClientConfig(timeout=10)  # 10-second timeout
    
    try:
        async with asyncio.wait_for(create_mcp_client(config), timeout=15):
            # Operations here are subject to both client timeout and asyncio timeout
            result = await client.send_message(
                user_id="user123",
                message="Long processing message..."
            )
    except asyncio.TimeoutError:
        print("✗ Operation timed out")
    except Exception as e:
        print(f"✗ Other error: {e}")
```

## Configuration Examples

### 1. Environment-based Configuration

```bash
# .env file
SIMPLECHAT_MCP_CLIENT_SERVER_PATH=../mcp_server/simplechat_mcp_server.py
SIMPLECHAT_MCP_CLIENT_TIMEOUT=30
SIMPLECHAT_MCP_CLIENT_LOG_LEVEL=INFO
SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL=https://api.simplechat.com
SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN=your_token_here
```

```python
# Python code - configuration loaded automatically
config = SimpleChatMCPClientConfig()  # Loads from environment
async with create_mcp_client(config) as client:
    result = await client.test_token()
```

### 2. Programmatic Configuration

```python
config = SimpleChatMCPClientConfig(
    server_path="/custom/path/server.py",
    timeout=60,
    log_level="DEBUG",
    server_env={
        "SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL": "https://dev.simplechat.com",
        "SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN": "dev_token_123"
    }
)

async with create_mcp_client(config) as client:
    result = await client.test_token()
```

### 3. JSON Configuration File

```json
{
  "server_path": "../mcp_server/simplechat_mcp_server.py",
  "timeout": 45,
  "log_level": "INFO",
  "server_env": {
    "SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL": "https://prod.simplechat.com",
    "SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN": "prod_token_456"
  }
}
```

```python
import json

# Load configuration from file
with open("config.json") as f:
    config_data = json.load(f)

config = SimpleChatMCPClientConfig(**config_data)
async with create_mcp_client(config) as client:
    result = await client.test_token()
```

## Best Practices

### 1. Connection Management

```python
# ✓ Good: Use context managers
async with create_mcp_client() as client:
    await client.send_message(user_id="user123", message="Hello")

# ✗ Avoid: Manual connection management without proper cleanup
client = SimpleChatMCPClient()
await client.connect()
await client.send_message(user_id="user123", message="Hello")
# Forgot to disconnect!
```

### 2. Error Handling

```python
# ✓ Good: Specific error handling
try:
    async with create_mcp_client() as client:
        result = await client.send_message(user_id="user123", message="Hello")
except MCPConnectionError:
    # Handle connection issues
    print("Could not connect to MCP server")
except MCPToolError:
    # Handle tool execution issues  
    print("Tool execution failed")

# ✗ Avoid: Catching all exceptions without specificity
try:
    # ... MCP operations
except Exception as e:
    print(f"Something went wrong: {e}")  # Too generic
```

### 3. Configuration Management

```python
# ✓ Good: Environment-based configuration with fallbacks
config = SimpleChatMCPClientConfig(
    server_path=os.getenv("MCP_SERVER_PATH", "../mcp_server/simplechat_mcp_server.py"),
    timeout=int(os.getenv("MCP_TIMEOUT", "30")),
    log_level=os.getenv("MCP_LOG_LEVEL", "INFO")
)

# ✓ Good: Validate configuration
if not os.path.exists(config.server_path):
    raise ValueError(f"MCP server not found: {config.server_path}")
```

### 4. Semantic Kernel Integration

```python
# ✓ Good: Check if plugin is needed before adding
if "simplechat" not in [plugin.name for plugin in kernel.plugins]:
    add_simplechat_plugin(kernel, "simplechat")

# ✓ Good: Error handling in SK context
result = await kernel.invoke("simplechat", "send_message", args)
if result.startswith("Error"):
    # Handle the error appropriately
    return handle_error(result)
```

### 5. Performance Optimization

```python
# ✓ Good: Reuse client connections when possible
async def batch_operations(operations):
    async with create_mcp_client() as client:
        results = []
        for op in operations:
            result = await op(client)
            results.append(result)
        return results

# ✗ Avoid: Creating new connections for each operation
async def inefficient_operations(operations):
    results = []
    for op in operations:
        async with create_mcp_client() as client:  # New connection each time
            result = await op(client)
            results.append(result)
    return results
```

### 6. Logging and Monitoring

```python
import logging

# Set up proper logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def monitored_operations():
    async with create_mcp_client() as client:
        logger.info("Starting MCP operations")
        
        try:
            result = await client.send_message(
                user_id="user123", 
                message="Hello"
            )
            logger.info(f"Message sent successfully: {len(result)} chars")
            return result
        except Exception as e:
            logger.error(f"Operation failed: {e}")
            raise
```

This comprehensive guide covers all major usage patterns and best practices for the SimpleChat MCP Client. Use these examples as starting points for your own implementations.