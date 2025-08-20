# FastMCP Server with Microsoft Entra ID OAuth

A FastMCP server that authenticates users with Microsoft Entra ID using OAuth and provides tools for making authenticated requests to backend APIs using bearer tokens.

## Features

- **OAuth Authentication**: Uses Microsoft Entra ID (Azure AD) for user authentication
- **MSAL Public Client**: Implements the public client flow for security
- **Bearer Token Management**: Automatically handles token storage, refresh, and validation
- **FastAPI Integration**: Provides OAuth callback endpoints for the authentication flow
- **Streamable HTTP Protocol**: Runs over streamable-http protocol as required
- **Simple Configuration**: No Pydantic dependencies, uses simple configuration classes
- **Authenticated API Calls**: Tools for making GET, POST, PUT, DELETE requests with bearer tokens

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your Microsoft Entra ID configuration:

```bash
cp .env.example .env
```

Required configuration:
- `AZURE_CLIENT_ID`: Your application's client ID from Entra ID
- `AZURE_TENANT_ID`: Your tenant ID from Entra ID

Optional configuration:
- `BACKEND_API_BASE_URL`: Base URL for your backend API
- `CUSTOM_API_SCOPE`: Additional API scope if needed
- `SERVER_HOST` and `SERVER_PORT`: Server configuration

### 3. Microsoft Entra ID App Registration

1. Go to Azure Portal > Microsoft Entra ID > App registrations
2. Create a new registration:
   - Name: Your MCP Server App
   - Supported account types: Accounts in this organizational directory only
   - Redirect URI: `http://localhost:8000/auth/callback` (Web platform)
3. Note the Client ID and Tenant ID
4. Configure API permissions as needed for your backend API
5. **Important**: Use public client flow (no client secret needed)

## Usage

### 1. Start the Server

```bash
python server.py
```

The server will start on `http://localhost:8000` by default.

### 2. Available MCP Tools

See COMMANDS.md file

### 4. OAuth Endpoints

The server also provides direct HTTP endpoints:

- `GET /auth/login?user_id=<id>`: Start login flow
- `GET /auth/callback`: OAuth callback (used by Microsoft)
- `GET /auth/logout?user_id=<id>`: Logout user
- `GET /auth/status?user_id=<id>`: Check auth status

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   MCP Client    │    │   FastMCP Server │    │ Microsoft Entra │
│                 │    │                  │    │      ID         │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         │ authenticate_user()    │                       │
         │──────────────────────→│                       │
         │                       │ Start OAuth Flow      │
         │                       │──────────────────────→│
         │ Return auth URL       │                       │
         │←──────────────────────│                       │
         │                       │                       │
    [User visits auth URL and completes OAuth]           │
         │                       │                       │
         │                       │←─────────────────────│
         │                       │ OAuth callback        │
         │                       │ (code + tokens)       │
         │                       │                       │
         │ api_get_request()     │                       │
         │──────────────────────→│                       │
         │                       │ Make API call with    │
         │                       │ bearer token          │
         │                       │──────────────────────→│
         │ Return API response   │                       │ Backend API
         │←──────────────────────│←──────────────────────│
```

## Security Considerations

- Uses MSAL public client flow (no client secrets)
- Tokens are stored locally in `token_cache.json`
- State parameter used for CSRF protection
- Automatic token refresh when possible
- Bearer tokens are passed securely in Authorization headers

## File Structure

```
simplechat-auth/
├── server.py          # Main FastMCP server
├── config.py          # Configuration management
├── auth.py            # OAuth/MSAL authentication
├── api_client.py      # HTTP client for API calls
├── requirements.txt   # Python dependencies
├── .env.example       # Environment configuration template
└── README.md          # This file
```

## Dependencies

- `fastmcp==2.10.*`: FastMCP framework
- `fastapi>=0.104.0`: Web framework for OAuth callbacks
- `uvicorn>=0.24.0`: ASGI server
- `msal>=1.24.0`: Microsoft Authentication Library
- `httpx>=0.25.0`: HTTP client for API calls
- `python-multipart>=0.0.6`: Form data parsing

## Troubleshooting

1. **Import errors**: Make sure all dependencies are installed with `pip install -r requirements.txt`
2. **Authentication fails**: Check your `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` configuration
3. **Redirect URI mismatch**: Ensure the redirect URI in Entra ID matches `REDIRECT_URI` in your config
4. **API calls fail**: Verify `BACKEND_API_BASE_URL` and ensure your API accepts bearer token authentication
