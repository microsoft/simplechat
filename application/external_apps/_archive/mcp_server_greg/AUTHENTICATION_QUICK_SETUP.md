# MCP Server Authentication Configuration Example

## Quick Setup Guide for Azure Entra Authentication

### 1. Environment Configuration

Copy this template to `.env` in your MCP server directory:

```env
# Azure AD Configuration (Required)
AZURE_CLIENT_ID=12345678-1234-1234-1234-123456789012
AZURE_TENANT_ID=87654321-4321-4321-4321-210987654321
AZURE_AUTHORITY=https://login.microsoftonline.com/87654321-4321-4321-4321-210987654321

# Backend Configuration (Required)
BACKEND_URL=https://127.0.0.1:5443
BACKEND_API_SCOPE=api://12345678-1234-1234-1234-123456789012/.default

# MCP Server Configuration (Optional)
MCPSERVER_NAME=SimpleChat-MCP-Server
PORT=8080
```

### 2. Azure AD App Registration

Your Azure AD app needs these settings:

**Authentication:**
- Platform: Public client/native
- Redirect URI: `http://localhost:8080/callback`
- Advanced settings: Allow public client flows = Yes

**API Permissions:**
- Your backend API (Application ID URI)
- Scopes: User.Read, or custom scopes

**Token Configuration:**
- Access tokens: Enabled
- ID tokens: Enabled

### 3. Backend Requirements

Your backend must have these endpoints:

```
POST /api/login          # Authentication endpoint
GET  /api/user_info      # Session validation
POST /api/logout         # Session cleanup
GET  /api/conversations  # Protected resource example
```

### 4. Test Your Setup

```bash
# 1. Start your MCP server
python simplechat-mcp-server.py

# 2. Test in MCP client or directly:
# - Call health() tool - should show "Not authenticated"
# - Call login() tool - should authenticate and establish session
# - Call get_conversations() tool - should return data
# - Call logout() tool - should clear session
```

### 5. Troubleshooting Common Issues

**"Authentication required" error:**
- Check that login() was called successfully
- Verify SESSION_ID is set
- Confirm backend session endpoint is working

**"Session expired" error:**
- Session may have timed out on backend
- Call login() again to re-establish session
- Check backend session lifetime settings

**"Backend connection error":**
- Verify BACKEND_URL is correct
- Check if backend is running
- Confirm SSL/TLS settings

**"Token validation failed":**
- Check AZURE_CLIENT_ID matches app registration
- Verify AZURE_TENANT_ID is correct
- Confirm API permissions are granted

### 6. Security Notes

✅ **Do:**
- Use HTTPS in production
- Set appropriate session timeouts
- Validate all tokens server-side
- Clear sessions on logout

❌ **Don't:**
- Store tokens in plaintext
- Use HTTP in production
- Skip token validation
- Expose sensitive errors to users

### 7. Example Authentication Flow

```
1. User → MCP Client → login() tool
2. MCP Server → Azure AD → Get token
3. MCP Server → Backend → Establish session
4. Backend → Session cookie → MCP Server
5. User → MCP Client → get_conversations() tool
6. MCP Server → Backend (with session) → Return data
```

This setup provides secure, session-based authentication for your MCP server connecting to Azure Entra-enabled backends.
