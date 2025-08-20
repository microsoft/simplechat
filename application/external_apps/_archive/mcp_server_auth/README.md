# Microsoft Entra ID Authentication MCP Server

This MCP (Model Context Protocol) server provides authentication capabilities for accessing custom websites through Microsoft Entra ID on behalf of users. The server runs over HTTP on port 8084 and provides 8 authentication tools.

## 🚀 Quick Start

### 1. Configuration

Copy the `.env.example` file to `.env` and fill in your Azure configuration:

```bash
cp .env.example .env
```

Required environment variables:
- `TENANT_ID`: Your Azure AD tenant ID
- `CLIENT_ID`: Your Azure app registration client ID
- `CLIENT_SECRET`: Your Azure app registration client secret (optional for public clients)
- `BACKEND_API_URL`: The URL of your custom website/API

### 2. Installation

Install the required dependencies:

```bash
pip install -r requirements.txt
```

### 3. Running the Server

Start the HTTP server on port 8084:

```bash
python server.py
```

The server will be available at: `http://127.0.0.1:8084/mcp/`

## 🛠️ Available Tools

The MCP server provides 8 authentication tools:

| Tool Name | Description |
|-----------|-------------|
| `authenticate_user` | Initiates OAuth 2.0 authentication with Microsoft Entra ID |
| `make_api_request` | Makes authenticated requests to your custom website/API |
| `check_auth_status` | Checks current authentication status |
| `refresh_auth_token` | Refreshes expired authentication tokens |
| `logout_user` | Logs out the current user |
| `get_user_info` | Gets authenticated user profile information |
| `list_api_endpoints` | Lists available API endpoints |
| `configure_api_settings` | Configures API connection settings |

## 🔧 Configuration Options

### Server Configuration

The server can be configured via environment variables:

```bash
# Server settings
SERVER_TYPE=http          # Transport type: http or stdio
SERVER_HOST=127.0.0.1     # Server host
SERVER_PORT=8084          # Server port

# Azure AD settings
TENANT_ID=your-tenant-id
CLIENT_ID=your-client-id
CLIENT_SECRET=your-client-secret  # Optional for public clients

# Backend API settings
BACKEND_API_URL=https://your-api.com/
API_SCOPES=api://your-client-id/access_as_user
```

### Azure App Registration

For the authentication to work, you need to set up an Azure App Registration:

1. Go to [Azure Portal](https://portal.azure.com) > Azure Active Directory > App registrations
2. Create a new registration or use an existing one
3. Set the redirect URI to: `http://localhost:8080` (for MSAL browser authentication)
4. Note down the `Application (client) ID` and `Directory (tenant) ID`
5. If using a confidential client, create a client secret

## 📝 Usage Examples

### Using the Test Client

Use the provided test client to interact with the server:

```bash
python test_http_client.py
```

### Direct HTTP Requests

You can also make direct HTTP requests to the server:

```bash
# List available tools
curl -X POST http://127.0.0.1:8084/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/list", "params": {}}'

# Check authentication status
curl -X POST http://127.0.0.1:8084/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "check_auth_status", "arguments": {}}}'
```

### Python Client Example

```python
import requests
import json

def call_mcp_tool(tool_name, arguments=None):
    if arguments is None:
        arguments = {}
    
    payload = {
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }
    
    response = requests.post(
        "http://127.0.0.1:8084/mcp",
        json=payload,
        headers={"Content-Type": "application/json"}
    )
    
    return response.json()

# Authenticate user
auth_result = call_mcp_tool("authenticate_user")
print(json.dumps(auth_result, indent=2))

# Make an API request
api_result = call_mcp_tool("make_api_request", {
    "method": "GET",
    "endpoint": "/api/user/profile"
})
print(json.dumps(api_result, indent=2))
```

## 🔐 Authentication Flow

1. **User Authentication**: Call the `authenticate_user` tool to start the OAuth 2.0 flow
2. **Browser Redirect**: The user will be redirected to Azure AD for authentication
3. **Token Storage**: Successfully obtained tokens are cached locally
4. **API Requests**: Use `make_api_request` to make authenticated calls to your backend
5. **Token Refresh**: Tokens are automatically refreshed when they expire

## 🚨 Security Considerations

- **Client Types**: The server supports both public and confidential Azure clients
- **Token Storage**: Tokens are cached locally using MSAL's token cache
- **HTTPS**: Consider using HTTPS in production environments
- **Secrets**: Never commit secrets to version control
- **Scopes**: Configure appropriate API scopes for your application

## 📁 Project Structure

```
mcp_server_auth/
├── server.py              # Main MCP server implementation
├── auth.py                # Azure AD authentication logic
├── config.py              # Configuration management
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables template
├── test_http_client.py   # HTTP client for testing
├── test_auth.py          # Authentication testing script
└── README.md             # This file
```

## 🐛 Troubleshooting

### Common Issues

1. **"Client is public" error**: This is normal for Azure app registrations. The server handles both public and confidential clients.

2. **Port already in use**: Change the `SERVER_PORT` in your `.env` file or stop other services using port 8084.

3. **Authentication fails**: Verify your Azure app registration settings and redirect URIs.

4. **Token expires**: The server automatically refreshes tokens, but you can manually call `refresh_auth_token`.

### Debug Mode

Set the following environment variable for detailed logging:

```bash
FASTMCP_DEBUG=true python server.py
```

## 🤝 Contributing

Feel free to submit issues and enhancement requests!

## 📄 License

This project is open source and available under the MIT License.
