# SimpleChat FastMCP Server

This FastMCP server provides a Model Context Protocol (MCP) interface to SimpleChat's API endpoints, enabling MCP clients to interact with SimpleChat functionality through standardized tools.

## Features

The MCP server provides the following tools:

- **send_message**: Send chat messages to SimpleChat
- **list_documents**: List user documents with pagination and search
- **upload_document**: Upload documents to SimpleChat
- **list_groups**: List user groups with pagination and search  
- **get_settings**: Retrieve application settings
- **test_token**: Validate bearer token authentication

## Installation

### Prerequisites

1. Python 3.8+ installed
2. Access to a running SimpleChat instance
3. A valid bearer token with `ExternalApi` role

### Install Dependencies

```bash
cd application/mcp_server
pip install -r requirements.txt
```

## Configuration

### Environment Variables

Set the following environment variables:

- `SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL`: Base URL of your SimpleChat instance (e.g., `https://your-domain.com`)
- `SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN`: Bearer token for authentication (required)
- `SIMPLECHAT_MCP_LOG_LEVEL`: Log level (default: `INFO`)

### Example .env file

Create a `.env` file in the `mcp_server` directory:

```env
SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL=https://your-simplechat-domain.com
SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN=your-bearer-token-here
SIMPLECHAT_MCP_LOG_LEVEL=INFO
```

## MCP Client Configuration

### Claude Desktop

Add this to your Claude Desktop MCP settings (`config.json`):

```json
{
  "mcpServers": {
    "simplechat": {
      "command": "python",
      "args": ["/path/to/simplechat/application/mcp_server/simplechat_mcp_server.py"],
      "env": {
        "SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL": "https://your-simplechat-domain.com",
        "SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN": "your-bearer-token-here",
        "SIMPLECHAT_MCP_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

### Other MCP Clients

For other MCP clients, use the standard MCP protocol over stdio transport with the server executable.

## Usage Examples

Once configured, you can use these tools through your MCP client:

### Send a Chat Message

```
Use the send_message tool to send "Hello, how can you help me?" to SimpleChat for user "user123"
```

### List Documents

```
Use the list_documents tool to show all documents for user "user123" with search term "report"
```

### Upload a Document

```
Use the upload_document tool to upload "/path/to/document.pdf" for user "user123"
```

### List Groups

```
Use the list_groups tool to show all groups for user "user123"
```

### Test Authentication

```
Use the test_token tool to verify the bearer token is valid
```

## Authentication

The server uses bearer token authentication. You need:

1. A valid Microsoft Entra ID token
2. The token must include the `ExternalApi` role
3. The SimpleChat instance must have external API endpoints enabled

## Error Handling

The server provides detailed error messages for:

- Invalid or missing bearer tokens
- Network connectivity issues
- Invalid parameters
- SimpleChat API errors

## Development

### Running Locally

```bash
cd application/mcp_server
python simplechat_mcp_server.py
```

The server will start in stdio mode, ready to accept MCP protocol messages.

### Testing

You can test the server using an MCP client or by running integration tests against a SimpleChat instance.

### Logging

The server logs important events and errors. Set `SIMPLECHAT_MCP_LOG_LEVEL=DEBUG` for verbose logging.

## API Endpoints Used

The server interacts with these SimpleChat external API endpoints:

- `POST /external/chat` - Send chat messages
- `GET /external/documents?user_id=<id>` - List documents
- `POST /external/documents/upload` - Upload documents
- `GET /external/groups?user_id=<id>` - List groups
- `GET /external/applicationsettings/get` - Get settings
- `POST /external/applicationsettings/set` - Update settings
- `GET /external/healthcheck` - Health check

**Note**: Most endpoints require a `user_id` parameter since they use bearer token authentication rather than session-based authentication.

## Troubleshooting

### Common Issues

1. **"Authorization header missing"**
   - Ensure `SIMPLECHAT_MCP_SIMPLECHAT_BEARER_TOKEN` is set correctly

2. **"Forbidden: ExternalApi role required"**
   - The bearer token must include the `ExternalApi` role in its claims

3. **Connection timeouts**
   - Check network connectivity to the SimpleChat instance
   - Verify the `SIMPLECHAT_MCP_SIMPLECHAT_BASE_URL` is correct

4. **"Tool execution failed"**
   - Check the server logs for detailed error information
   - Verify the SimpleChat instance is running and accessible

### Debug Mode

Enable debug logging:

```bash
export SIMPLECHAT_MCP_LOG_LEVEL=DEBUG
python simplechat_mcp_server.py
```

## Security Considerations

- Keep bearer tokens secure and rotate them regularly
- Use HTTPS for all SimpleChat communications
- Monitor server logs for suspicious activity
- Restrict network access to authorized clients only

## Contributing

To contribute to this MCP server:

1. Follow the existing code style and patterns
2. Add appropriate error handling and logging
3. Update documentation for any new features
4. Test against a live SimpleChat instance

## License

This MCP server is part of the SimpleChat project and follows the same licensing terms.