# commands

## execute commands in this order

```
ping
get_server_info
authenticate_user(gregunger@M365x10036287.onmicrosoft.com)
check_auth_status
view_userid
get_session
view_sessionid
get_conversations
send_chat_message("25bf1a4e-b6f8-4bb4-957d-b345d8f43c94", "this is greg and large marge")
logout_user
```

## old code for api call

``` python
@mcp.tool()
async def api_get_request(
    user_id: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Make an authenticated GET request to the backend API.
    
    Args:
        user_id: Unique identifier for the authenticated user
        endpoint: API endpoint path (e.g., '/users/profile')
        params: Optional query parameters
        
    Returns:
        Dictionary with API response
    """
    if not api_client:
        return {
            "success": False,
            "error": "Backend API base URL not configured",
            "message": "Set BACKEND_API_BASE_URL environment variable"
        }
    
    access_token = auth_manager.get_access_token(user_id)
    if not access_token:
        return {
            "success": False,
            "error": "User not authenticated",
            "message": f"User {user_id} needs to authenticate first"
        }
    
    try:
        response = await api_client.get(endpoint, access_token, params)
        return {
            "success": True,
            "data": response,
            "endpoint": endpoint
        }
    except Exception as e:
        logger.error(f"API GET request failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to make GET request to {endpoint}"
        }


@mcp.tool()
async def api_post_request(
    user_id: str,
    endpoint: str,
    data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Make an authenticated POST request to the backend API.
    
    Args:
        user_id: Unique identifier for the authenticated user
        endpoint: API endpoint path (e.g., '/users/create')
        data: Optional request body data
        
    Returns:
        Dictionary with API response
    """
    if not api_client:
        return {
            "success": False,
            "error": "Backend API base URL not configured",
            "message": "Set BACKEND_API_BASE_URL environment variable"
        }
    
    access_token = auth_manager.get_access_token(user_id)
    if not access_token:
        return {
            "success": False,
            "error": "User not authenticated",
            "message": f"User {user_id} needs to authenticate first"
        }
    
    try:
        response = await api_client.post(endpoint, access_token, data)
        return {
            "success": True,
            "data": response,
            "endpoint": endpoint
        }
    except Exception as e:
        logger.error(f"API POST request failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to make POST request to {endpoint}"
        }


@mcp.tool()
async def api_put_request(
    user_id: str,
    endpoint: str,
    data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Make an authenticated PUT request to the backend API.
    
    Args:
        user_id: Unique identifier for the authenticated user
        endpoint: API endpoint path (e.g., '/users/123')
        data: Optional request body data
        
    Returns:
        Dictionary with API response
    """
    if not api_client:
        return {
            "success": False,
            "error": "Backend API base URL not configured",
            "message": "Set BACKEND_API_BASE_URL environment variable"
        }
    
    access_token = auth_manager.get_access_token(user_id)
    if not access_token:
        return {
            "success": False,
            "error": "User not authenticated",
            "message": f"User {user_id} needs to authenticate first"
        }
    
    try:
        response = await api_client.put(endpoint, access_token, data)
        return {
            "success": True,
            "data": response,
            "endpoint": endpoint
        }
    except Exception as e:
        logger.error(f"API PUT request failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to make PUT request to {endpoint}"
        }


@mcp.tool()
async def api_delete_request(
    user_id: str,
    endpoint: str
) -> Dict[str, Any]:
    """
    Make an authenticated DELETE request to the backend API.
    
    Args:
        user_id: Unique identifier for the authenticated user
        endpoint: API endpoint path (e.g., '/users/123')
        
    Returns:
        Dictionary with API response
    """
    if not api_client:
        return {
            "success": False,
            "error": "Backend API base URL not configured",
            "message": "Set BACKEND_API_BASE_URL environment variable"
        }
    
    access_token = auth_manager.get_access_token(user_id)
    if not access_token:
        return {
            "success": False,
            "error": "User not authenticated",
            "message": f"User {user_id} needs to authenticate first"
        }
    
    try:
        response = await api_client.delete(endpoint, access_token)
        return {
            "success": True,
            "data": response,
            "endpoint": endpoint
        }
    except Exception as e:
        logger.error(f"API DELETE request failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to make DELETE request to {endpoint}"
        }
```
