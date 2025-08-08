# MCP Server Authentication Guide for Azure Entra Integration

This guide demonstrates how to implement robust authentication for MCP (Model Context Protocol) servers that connect to custom websites using Azure Entra (formerly Azure AD) as the identity provider.

## Overview

MCP servers need to authenticate end users against your custom website backend before providing access to tools and resources. This implementation supports multiple authentication strategies depending on your architecture.

## Authentication Strategies

### 1. Session-Based Authentication (Recommended for Web Backends)

This approach simulates the web authentication flow and establishes a session with your backend.

**Use Case**: When your MCP server connects to a Flask/Django/Express backend that uses session-based authentication.

**Implementation**: See `simplechat-mcp-server.py` for a complete example.

**Key Components**:
- Session establishment through OAuth callback simulation
- Session validation before each tool call
- Automatic session refresh when expired
- Authentication state management

### 2. Token-Based Authentication (For API-First Backends)

This approach uses Azure AD access tokens directly for API authentication.

**Use Case**: When your backend validates JWT tokens from Azure AD directly.

**Benefits**:
- No session state to manage
- Better for microservices architectures
- Supports fine-grained permissions via token claims

### 3. Hybrid Authentication (Maximum Flexibility)

Combines both session and token approaches for different endpoints.

**Use Case**: When you have both web endpoints (requiring sessions) and API endpoints (requiring tokens).

## Implementation Details

### Core Authentication Components

```python
# Global authentication state
AUTHENTICATED = False
SESSION_ID = None
ACCESS_TOKEN = None

def require_authentication(func):
    """Decorator to ensure user is authenticated before calling MCP tools"""
    def wrapper(*args, **kwargs):
        global AUTHENTICATED, SESSION_ID
        if not AUTHENTICATED or SESSION_ID is None:
            return "❌ Authentication required. Please run the 'login' tool first."
        return func(*args, **kwargs)
    return wrapper

def validate_session():
    """Validate current session with backend"""
    global SESSION_ID, BACKEND_URL
    
    if not SESSION_ID:
        return False
        
    try:
        url = f"{BACKEND_URL}/api/user_info"
        headers = {'Content-Type': 'application/json'}
        cookies = {"session": SESSION_ID}
        
        response = requests.get(url, headers=headers, cookies=cookies, verify=False, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Session validation failed: {e}")
        return False
```

### Enhanced MCP Tools with Authentication

```python
@mcp.tool()
def login() -> str:
    """Login to backend and establish authentication session."""
    global AUTHENTICATED, SESSION_ID
    
    try:
        # Simulate OAuth flow or direct authentication
        establish_session()
        
        # Validate the session was established successfully
        if SESSION_ID and validate_session():
            AUTHENTICATED = True
            return f"✅ Successfully logged in with session ID: {SESSION_ID}"
        else:
            AUTHENTICATED = False
            SESSION_ID = None
            return "❌ Login failed - could not establish valid session"
            
    except Exception as e:
        AUTHENTICATED = False
        SESSION_ID = None
        return f"❌ Login failed: {str(e)}"

@mcp.tool()
@require_authentication
def get_conversations() -> str:
    """Get conversations from backend (requires authentication)."""
    global AUTHENTICATED, SESSION_ID
    
    # Validate session before proceeding
    if not validate_session():
        AUTHENTICATED = False
        SESSION_ID = None
        return "❌ Session expired. Please login again using the 'login' tool."
    
    # Make authenticated API call
    return call_backend_api("/api/conversations")

@mcp.tool()
def logout() -> str:
    """Logout and clear authentication session."""
    global AUTHENTICATED, SESSION_ID
    
    if AUTHENTICATED and SESSION_ID:
        try:
            # Call backend logout endpoint
            url = f"{BACKEND_URL}/api/logout"
            headers = {'Content-Type': 'application/json'}
            cookies = {"session": SESSION_ID}
            requests.post(url, headers=headers, cookies=cookies, verify=False, timeout=5)
        except Exception:
            pass  # Ignore errors, clear local state anyway
    
    AUTHENTICATED = False
    SESSION_ID = None
    return "✅ Successfully logged out"
```

## Configuration Setup

### Environment Variables

Create a `.env` file in your MCP server directory:

```env
# Azure AD Configuration
AZURE_CLIENT_ID=your-client-id-here
AZURE_CLIENT_SECRET=your-client-secret-here  # Only for confidential clients
AZURE_TENANT_ID=your-tenant-id-here
AZURE_AUTHORITY=https://login.microsoftonline.com/your-tenant-id-here

# Backend Configuration
BACKEND_URL=https://127.0.0.1:5443
BACKEND_API_SCOPE=api://your-app-id/.default  # Or your custom scopes

# MCP Server Configuration
MCPSERVER_NAME=YourApp-MCP-Server
PORT=8080  # For HTTP MCP servers
```

### Azure AD App Registration Requirements

Your Azure AD app registration needs:

1. **Application Type**: Public client or Confidential client
2. **Redirect URIs**: 
   - `http://localhost:8080/callback` (for HTTP MCP servers)
   - Or custom redirect URI for your authentication flow
3. **API Permissions**:
   - Your backend API permissions
   - Microsoft Graph permissions (if needed)
4. **Token Configuration**:
   - Enable ID tokens
   - Configure optional claims if needed

### Backend Requirements

Your backend must support:

1. **Authentication Endpoints**:
   - `/api/login` or OAuth callback handling
   - `/api/logout`
   - `/api/user_info` (for session validation)

2. **Session Management**:
   - Session creation and validation
   - CSRF protection (if applicable)
   - Secure cookie handling

3. **Token Validation** (for token-based auth):
   - JWT signature validation
   - Audience validation
   - Role/scope checking

## Security Best Practices

### 1. Token Security
- Store tokens securely (avoid plaintext storage)
- Implement token refresh logic
- Use appropriate token scopes
- Validate token claims (audience, issuer, expiration)

### 2. Session Security
- Use secure session management
- Implement session timeouts
- Validate sessions on each request
- Clear sessions on logout

### 3. Network Security
- Use HTTPS in production
- Validate SSL certificates
- Implement proper CORS policies
- Use secure headers

### 4. Error Handling
- Don't expose sensitive information in error messages
- Log authentication failures for monitoring
- Implement rate limiting for authentication attempts
- Provide clear user feedback for authentication issues

## Testing Your Implementation

### 1. Authentication Flow Testing

```python
# Test the complete authentication flow
def test_authentication_flow():
    print("Testing MCP authentication flow...")
    
    # Test health check
    health_result = health()
    print(f"Health check: {health_result}")
    
    # Test unauthenticated access (should fail)
    try:
        conversations = get_conversations()
        print(f"Unauthenticated access: {conversations}")
    except Exception as e:
        print(f"Expected failure: {e}")
    
    # Test login
    login_result = login()
    print(f"Login result: {login_result}")
    
    # Test authenticated access
    conversations = get_conversations()
    print(f"Authenticated access: {conversations}")
    
    # Test logout
    logout_result = logout()
    print(f"Logout result: {logout_result}")
```

### 2. Session Validation Testing

```python
# Test session validation and refresh
def test_session_validation():
    # Login first
    login()
    
    # Test valid session
    is_valid = validate_session()
    print(f"Session valid: {is_valid}")
    
    # Simulate session expiration
    global SESSION_ID
    old_session = SESSION_ID
    SESSION_ID = "expired-session-id"
    
    # Test expired session
    is_valid = validate_session()
    print(f"Expired session valid: {is_valid}")
    
    # Restore session
    SESSION_ID = old_session
```

## Common Issues and Solutions

### Issue 1: "Authentication required" despite successful login
**Cause**: Session not properly established or validation failing
**Solution**: Check session establishment logic and validation endpoint

### Issue 2: "Session expired" errors
**Cause**: Backend session timeout or invalid session format
**Solution**: Implement session refresh logic and check session lifetime

### Issue 3: Token validation failures
**Cause**: Incorrect audience, expired tokens, or invalid signatures
**Solution**: Verify token configuration and claims validation

### Issue 4: CORS errors in browser-based flows
**Cause**: Missing CORS headers or invalid origin
**Solution**: Configure CORS policies on your backend

## Advanced Features

### 1. Automatic Token Refresh

```python
def refresh_token_if_needed():
    """Refresh access token if it's about to expire"""
    global ACCESS_TOKEN, TOKEN_EXPIRES_AT
    
    if TOKEN_EXPIRES_AT and datetime.now() >= TOKEN_EXPIRES_AT:
        # Refresh token logic here
        new_token = acquire_new_token()
        ACCESS_TOKEN = new_token
        TOKEN_EXPIRES_AT = datetime.now() + timedelta(hours=1)
```

### 2. Multi-User Support

```python
# User-specific session management
USER_SESSIONS = {}

def get_user_session(user_id):
    """Get session for specific user"""
    return USER_SESSIONS.get(user_id)

def set_user_session(user_id, session_id):
    """Set session for specific user"""
    USER_SESSIONS[user_id] = session_id
```

### 3. Role-Based Access Control

```python
def require_role(required_role):
    """Decorator to check user role before tool access"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            user_roles = get_user_roles()
            if required_role not in user_roles:
                return f"❌ Access denied. Required role: {required_role}"
            return func(*args, **kwargs)
        return wrapper
    return decorator

@mcp.tool()
@require_authentication
@require_role("admin")
def admin_function():
    """Admin-only function"""
    return "Admin access granted"
```

## Conclusion

This authentication framework provides a robust foundation for securing MCP servers that connect to Azure Entra-enabled backends. Choose the authentication strategy that best fits your architecture, and customize the implementation based on your specific security requirements.

For questions or issues, refer to the SimpleChat implementation in `simplechat-mcp-server.py` as a working example.
