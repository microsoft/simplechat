# SimpleChat FastMCP Server Usage Examples

This document provides comprehensive examples of using the SimpleChat FastMCP server built with **FastMCP 2.0**.

## What's New with FastMCP 2.0

This server now uses FastMCP 2.0 instead of the traditional Anthropic MCP SDK, providing:
- **47% Less Code**: Reduced from 510 to 272 lines
- **Cleaner Architecture**: Simple decorator-based tool registration
- **Better Maintainability**: Easier to understand and modify
- **Modern Python**: Leverages type hints and modern patterns

## Setup

1. **Install Dependencies:**
   ```bash
   cd application/external_apps/mcp_server
   pip install -r requirements.txt
   ```

2. **Configure Environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your SimpleChat instance details and bearer token
   ```

3. **Test Server:**
   ```bash
   python -c "from simplechat_mcp_server import SimpleChatConfig; print('✓ Server can be imported')"
   ```

## MCP Client Configuration Examples

### Claude Desktop Configuration

Add to `~/Library/Application Support/Claude/config.json` (macOS) or equivalent:

```json
{
  "mcpServers": {
    "simplechat": {
      "command": "python",
      "args": ["/absolute/path/to/simplechat/application/external_apps/mcp_server/simplechat_mcp_server.py"],
      "env": {
        "SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL": "https://your-simplechat-domain.com",
        "SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN": "your-bearer-token-here",
        "SIMPLECHAT_MCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

### Generic MCP Client Configuration

For other MCP clients supporting stdio transport:

```bash
python /path/to/simplechat/application/external_apps/mcp_server/simplechat_mcp_server.py
```

## Tool Usage Examples

### 1. Send Message

**Purpose:** Send a chat message to SimpleChat

**Usage in Claude:**
```
Use the send_message tool to send "What is the capital of France?" to SimpleChat for user "user123"
```

**Parameters:**
- `message` (required): The message text
- `user_id` (required): User ID for the message
- `conversation_id` (optional): Existing conversation ID
- `chat_type` (optional): "user" or "group"
- `hybrid_search` (optional): Enable document search
- `bing_search` (optional): Enable web search
- `active_group_id` (optional): For group chats

**Response:**
```json
{
  "conversation_id": "uuid-123",
  "response": "The capital of France is Paris.",
  "user_message": "What is the capital of France?",
  "timestamp": "2024-01-15T10:30:00Z",
  "status": "success"
}
```

### 2. List Documents

**Purpose:** List user's documents with pagination and search

**Usage in Claude:**
```
Use the list_documents tool to show all PDF documents for user "user123"
```

**Parameters:**
- `user_id` (required): User ID
- `page` (optional): Page number (default: 1)
- `page_size` (optional): Items per page (default: 10)
- `search` (optional): Search term for filtering

**Response:**
```json
{
  "documents": [
    {
      "id": "doc123",
      "file_name": "report.pdf",
      "title": "Annual Report",
      "status": "processed",
      "created_date": "2024-01-01T00:00:00Z"
    }
  ],
  "page": 1,
  "page_size": 10,
  "total_count": 1
}
```

### 3. Upload Document

**Purpose:** Upload a document to SimpleChat

**Usage in Claude:**
```
Use the upload_document tool to upload "/path/to/document.pdf" for user "user123"
```

**Parameters:**
- `user_id` (required): User ID
- `file_path` (required): Local file path
- `filename` (optional): Override filename

**Response:**
```json
{
  "message": "Processed 1 file(s). Check status periodically.",
  "document_ids": ["new-doc-uuid"],
  "processed_filenames": ["document.pdf"],
  "errors": []
}
```

### 4. List Groups

**Purpose:** List user's groups with pagination and search

**Usage in Claude:**
```
Use the list_groups tool to show all groups for user "user123"
```

**Parameters:**
- `user_id` (required): User ID
- `page` (optional): Page number
- `page_size` (optional): Items per page
- `search` (optional): Search term

**Response:**
```json
{
  "groups": [
    {
      "id": "group123",
      "name": "Research Team",
      "description": "Main research group",
      "userRole": "Admin",
      "isActive": true
    }
  ],
  "page": 1,
  "page_size": 10,
  "total_count": 1
}
```

### 5. Get Settings

**Purpose:** Retrieve application settings

**Usage in Claude:**
```
Use the get_settings tool to retrieve the current application settings
```

**Parameters:** None

**Response:**
```json
{
  "enable_chat": true,
  "enable_user_workspace": true,
  "enable_group_workspaces": true,
  "conversation_history_limit": 6,
  "enable_external_healthcheck": true
}
```

### 6. Update Settings

**Purpose:** Update application settings

**Usage in Claude:**
```
Use the update_settings tool to enable external health checks by setting enable_external_healthcheck to true
```

**Parameters:**
- `settings` (required): Settings object to update

**Example:**
```json
{
  "settings": {
    "enable_external_healthcheck": true,
    "conversation_history_limit": 10
  }
}
```

**Response:**
```json
"Application settings have been updated."
```

### 7. Test Token

**Purpose:** Validate bearer token authentication

**Usage in Claude:**
```
Use the test_token tool to check if our authentication is working
```

**Parameters:** None

**Response:**
```
Token is valid. Health check returned: 2024-01-15 10:30:00
```

## Advanced Usage Scenarios

### Workflow: Document Analysis

1. **Upload Document:**
   ```
   Upload the research paper from "/path/to/research.pdf" for user "researcher1"
   ```

2. **Wait for Processing:**
   ```
   List documents for user "researcher1" and check if "research.pdf" has status "processed"
   ```

3. **Ask Questions:**
   ```
   Send message "Summarize the key findings from the research paper" to user "researcher1" with hybrid_search enabled
   ```

### Workflow: Group Collaboration

1. **List Groups:**
   ```
   Show all groups for user "team_lead"
   ```

2. **Start Group Chat:**
   ```
   Send message "Let's review today's progress" to group chat for user "team_lead" with active_group_id "research-group-123"
   ```

3. **Upload Group Document:**
   ```
   Upload "/path/to/meeting_notes.docx" for user "team_lead" 
   ```

## Error Handling

### Common Errors and Solutions

1. **"Authorization header missing"**
   - Check bearer token is set correctly
   - Verify environment variable name

2. **"Forbidden: ExternalApi role required"**
   - Token needs ExternalApi role in claims
   - Contact admin to add role to token

3. **"invalid user_id"**
   - Ensure user_id parameter is provided
   - Use actual user ID from your system

4. **File upload errors**
   - Check file exists at specified path
   - Verify file type is supported
   - Ensure user has upload permissions

## Monitoring and Debugging

### Enable Debug Logging

Set environment variable:
```bash
export SIMPLECHAT_MCP_LOG_LEVEL=DEBUG
```

### Check Server Status

Use the test_token tool regularly to ensure connectivity.

### Monitor Document Processing

After uploading, periodically check document status with list_documents until processing completes.

## Security Best Practices

1. **Secure Token Storage:**
   - Store bearer tokens securely
   - Rotate tokens regularly
   - Use environment variables, not hardcoded values

2. **Network Security:**
   - Use HTTPS for SimpleChat instance
   - Restrict network access to authorized clients
   - Monitor for suspicious activity

3. **Access Control:**
   - Limit user_id values to authorized users only
   - Implement additional validation if needed
   - Log all API calls for audit purposes

## Troubleshooting

### Connection Issues

1. **Check Base URL:**
   ```bash
   curl -k https://your-simplechat-domain.com/external/healthcheck
   ```

2. **Verify Token:**
   Use the test_token tool to validate authentication.

3. **Network Connectivity:**
   Ensure MCP client can reach SimpleChat instance.

### Performance Optimization

1. **Use Pagination:**
   - Set appropriate page_size for list operations
   - Don't fetch all data at once

2. **Cache Results:**
   - Cache document lists between calls
   - Reuse conversation IDs when possible

3. **Monitor Timeouts:**
   - Large file uploads may take time
   - Document processing is asynchronous

This completes the comprehensive usage guide for the SimpleChat FastMCP server.