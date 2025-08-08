# SimpleChat MCP Client

This is a Semantic Kernel plugin that provides a client interface to the SimpleChat MCP (Model Context Protocol) server. It enables Semantic Kernel agents and applications to interact with SimpleChat functionality through the standardized MCP protocol.

## Overview

The MCP Client acts as a bridge between Semantic Kernel and the SimpleChat MCP server, exposing all MCP server tools as Semantic Kernel functions that can be used by agents, workflows, and other SK components.

## Features

### 7 Semantic Kernel Functions
All MCP server tools are exposed as SK functions:

1. **`send_message`** - Send chat messages to SimpleChat
2. **`list_documents`** - List user documents with pagination and search
3. **`upload_document`** - Upload files to SimpleChat
4. **`list_groups`** - List user groups with pagination and search
5. **`get_settings`** - Retrieve application settings
6. **`update_settings`** - Update application settings
7. **`test_token`** - Validate bearer token authentication

### Integration Features
- **Semantic Kernel Plugin Architecture** - Follows established plugin patterns
- **Async Support** - Full async/await support for all operations
- **Error Handling** - Comprehensive error handling with detailed logging
- **Configuration Management** - Environment-based configuration
- **Connection Management** - Automatic connection handling and cleanup

## Installation

1. Install the MCP client dependencies:
```bash
cd application/external_apps/mcp_client
pip install -r requirements.txt
```

2. Configure the MCP server connection:
```bash
cp .env.example .env
# Edit .env with your MCP server details
```

## Configuration

### Environment Variables

The client supports the following environment variables:

```bash
# MCP Server Connection
SIMPLECHAT_MCP_CLIENT_SERVER_PATH=/path/to/mcp_server/simplechat_mcp_server.py
SIMPLECHAT_MCP_CLIENT_TIMEOUT=30
SIMPLECHAT_MCP_CLIENT_LOG_LEVEL=INFO

# SimpleChat API Configuration (passed to MCP server)
SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL=https://your-simplechat-instance.com
SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN=your-bearer-token
```

### Configuration File

You can also use a JSON configuration file:

```json
{
  "server_path": "/path/to/mcp_server/simplechat_mcp_server.py",
  "timeout": 30,
  "log_level": "INFO",
  "server_env": {
    "SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL": "https://your-instance.com",
    "SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN": "your-token"
  }
}
```

## Usage

### As a Semantic Kernel Plugin

```python
import semantic_kernel as sk
from mcp_client_plugin import SimpleChatMCPPlugin

# Create kernel
kernel = sk.Kernel()

# Add the MCP client plugin
mcp_plugin = SimpleChatMCPPlugin()
kernel.add_plugin(mcp_plugin, plugin_name="simplechat")

# Use the functions
result = await kernel.invoke("simplechat", "send_message", {
    "user_id": "user123",
    "message": "What is the capital of France?",
    "hybrid_search": True
})

print(result)
```

### Direct Client Usage

```python
from simplechat_mcp_client import SimpleChatMCPClient

async def main():
    async with SimpleChatMCPClient() as client:
        # Send a message
        result = await client.send_message(
            user_id="user123",
            message="Hello, SimpleChat!",
            hybrid_search=True
        )
        print(result)

        # List documents
        documents = await client.list_documents(
            user_id="user123",
            page=1,
            size=10
        )
        print(documents)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

### In Semantic Kernel Workflows

```python
from semantic_kernel import Kernel
from semantic_kernel.planning.basic_planner import BasicPlanner

kernel = Kernel()
# Add MCP plugin
kernel.add_plugin(SimpleChatMCPPlugin(), plugin_name="simplechat")

planner = BasicPlanner()

# Create a plan that uses SimpleChat functionality
goal = "Search for documents about AI, then send a summary message to user123"
plan = await planner.create_plan(goal, kernel)

# Execute the plan
result = await plan.invoke(kernel)
print(result)
```

## Function Reference

### send_message
Send a chat message to SimpleChat with advanced features.

**Parameters:**
- `user_id` (str): User identifier
- `message` (str): Message content
- `hybrid_search` (bool, optional): Enable hybrid search
- `bing_search` (bool, optional): Enable Bing search  
- `active_group_id` (str, optional): Group context ID
- `document_scope` (list, optional): Document scope limitation

**Returns:** Chat response from SimpleChat

### list_documents
List user documents with pagination and search capabilities.

**Parameters:**
- `user_id` (str): User identifier
- `page` (int, optional): Page number (default: 1)
- `size` (int, optional): Page size (default: 10)
- `search` (str, optional): Search query

**Returns:** List of documents with metadata

### upload_document
Upload a document to SimpleChat.

**Parameters:**
- `user_id` (str): User identifier
- `file_path` (str): Path to file to upload
- `filename` (str, optional): Custom filename

**Returns:** Upload result with document metadata

### list_groups
List user groups with pagination and search.

**Parameters:**
- `user_id` (str): User identifier
- `page` (int, optional): Page number (default: 1)
- `size` (int, optional): Page size (default: 10)
- `search` (str, optional): Search query

**Returns:** List of groups with metadata

### get_settings
Retrieve application settings.

**Returns:** Current application settings

### update_settings
Update application settings.

**Parameters:**
- `settings` (dict): Settings to update

**Returns:** Update result

### test_token
Test bearer token validity.

**Returns:** Token validation result

## Error Handling

The client provides comprehensive error handling:

```python
from simplechat_mcp_client import SimpleChatMCPClient, MCPClientError

async def safe_operation():
    try:
        async with SimpleChatMCPClient() as client:
            result = await client.send_message(
                user_id="user123",
                message="Test message"
            )
            return result
    except MCPClientError as e:
        print(f"MCP Client Error: {e}")
    except Exception as e:
        print(f"Unexpected Error: {e}")
```

## Testing

Run the test suite:

```bash
cd application/external_apps/mcp_client
python -m pytest tests/ -v
```

Test with the MCP server:

```bash
python test_client.py
```

## Troubleshooting

### Common Issues

1. **Connection Failed**
   - Ensure MCP server is running
   - Check server path configuration
   - Verify environment variables

2. **Authentication Errors**
   - Verify bearer token is valid
   - Check token permissions
   - Ensure server URL is correct

3. **Function Call Errors**
   - Check function parameters
   - Verify user permissions
   - Check server logs

### Debugging

Enable debug logging:

```bash
export SIMPLECHAT_MCP_CLIENT_LOG_LEVEL=DEBUG
```

View detailed logs:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Integration Examples

### With Semantic Kernel Agents

```python
from semantic_kernel.agents import ChatCompletionAgent
from semantic_kernel import Kernel

kernel = Kernel()
kernel.add_plugin(SimpleChatMCPPlugin(), plugin_name="simplechat")

agent = ChatCompletionAgent(
    kernel=kernel,
    name="SimpleChat Assistant",
    instructions="You are an assistant that can interact with SimpleChat to help users manage documents and conversations."
)

# Agent can now use SimpleChat functions automatically
response = await agent.invoke("Please list my recent documents and send a summary to my team group")
```

### With Planners

```python
from semantic_kernel.planning.function_calling_stepwise_planner import FunctionCallingStepwisePlanner

planner = FunctionCallingStepwisePlanner(kernel)

# Create complex workflows
result = await planner.invoke("Upload the Q4 report, search for related documents, and send a summary message to the executives group")
```

## Architecture

```
┌─────────────────────┐    ┌──────────────────────┐    ┌─────────────────────┐
│   Semantic Kernel   │    │   MCP Client Plugin  │    │   SimpleChat MCP    │
│                     │◄──►│                      │◄──►│      Server         │
│   - Agents          │    │   - Function Wrapper │    │                     │
│   - Planners        │    │   - Error Handling   │    │   - 7 Tools         │
│   - Workflows       │    │   - Async Support    │    │   - Authentication  │
└─────────────────────┘    └──────────────────────┘    └─────────────────────┘
```

## Development

To contribute to the MCP client:

1. Clone the repository
2. Set up development environment:
   ```bash
   cd application/external_apps/mcp_client
   pip install -r requirements-dev.txt
   ```
3. Run tests: `pytest`
4. Follow the existing code patterns and documentation standards

## License

This project follows the same license as the SimpleChat repository.