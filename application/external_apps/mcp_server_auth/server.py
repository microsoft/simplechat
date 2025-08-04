#!/usr/bin/env python3
"""
Microsoft Entra ID Authentication MCP Server

This MCP server provides authentication capabilities for accessing custom websites
through Microsoft Entra ID on behalf of users.
"""

import requests
import json

from typing import Any, Dict
from fastmcp import FastMCP
from auth import EntraAuthenticator
from config import config
from datetime import datetime

SESSION_ID = ""

# Initialize the MCP server
mcp = FastMCP(config.server_name)

# Global authenticator instance
authenticator = EntraAuthenticator()

#########################################
#
# RESOURCES
#
#########################################

@mcp.resource("data://example/message")
def get_example_message() -> str:
    """Provides an example message."""
    return "This is a sample message from the resource."

#########################################
#
# TOOLS
#
#########################################
@mcp.tool()
def get_conversations() -> str:
    """Get conversations from SimpleChat."""
    response = private_get_conversations()
    return f"Get conversations called with session ID: {SESSION_ID}, has response: [{response}]."

@mcp.tool()
def ping() -> str:
    """ping."""
    current_datetime = datetime.now()
    print("Current date and time (raw datetime object):", current_datetime)
    formatted_datetime = current_datetime.strftime("%Y-%m-%d %H:%M:%S")
    print("Current date and time (formatted):", formatted_datetime)
    return f"MCP Server is up {formatted_datetime}."

@mcp.tool()
def authenticate_user() -> Dict[str, Any]:
    """
    Authenticate user with Microsoft Entra ID.
    
    This tool initiates the OAuth 2.0 authentication flow with Microsoft Entra ID.
    It will open a browser window for the user to sign in and grant permissions.
    
    Returns:
        Dict containing authentication status and token information
    """
    try:
        result = authenticator.authenticate_user_sync()
        return result
    except Exception as e:
        return {
            "success": False,
            "message": f"Authentication failed: {str(e)}"
        }

@mcp.tool()
def check_auth_status() -> Dict[str, Any]:
    """
    Check the current authentication status.
    
    Returns:
        Dict containing authentication status and token information if authenticated
    """
    try:
        is_auth = authenticator.is_authenticated()
        
        if is_auth:
            token_info = authenticator.get_token_info()
            return {
                "authenticated": True,
                "token_info": token_info,
                "message": "User is authenticated"
            }
        else:
            return {
                "authenticated": False,
                "message": "User is not authenticated"
            }
    except Exception as e:
        return {
            "authenticated": False,
            "message": f"Error checking authentication: {str(e)}"
        }

@mcp.tool()
def get_access_token() -> Dict[str, Any]:
    """
    Get the current access token for making authenticated requests.
    
    Returns:
        Dict containing the access token or error message
    """
    try:
        token = authenticator.get_access_token_sync()
        
        if token:
            return {
                "success": True,
                "access_token": token,
                "token_type": "Bearer"
            }
        else:
            return {
                "success": False,
                "message": "No valid access token available. Please authenticate first."
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error getting access token: {str(e)}"
        }

@mcp.tool()
def make_api_request(
    method: str,
    endpoint: str,
    headers: Dict[str, str] = None,
    data: Dict[str, Any] = None,
    params: Dict[str, str] = None
) -> Dict[str, Any]:
    """
    Make an authenticated request to the custom website/API.
    
    Args:
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        endpoint: API endpoint path (will be appended to the configured base URL)
        headers: Optional additional headers to include
        data: Optional JSON data for POST/PUT requests
        params: Optional query parameters
    
    Returns:
        Dict containing the API response or error message
    """
    try:
        # Construct full URL
        if endpoint.startswith('http'):
            url = endpoint
        else:
            # Remove leading slash if present
            endpoint = endpoint.lstrip('/')
            url = f"{config.backend_api_url.rstrip('/')}/{endpoint}"
        
        # Prepare request arguments
        kwargs = {}
        
        if headers:
            kwargs['headers'] = headers
        
        if data:
            kwargs['json'] = data
        
        if params:
            kwargs['params'] = params
        
        # Make the authenticated request
        result = authenticator.make_authenticated_request_sync(
            method=method.upper(),
            url=url,
            **kwargs
        )
        
        return result
    
    except Exception as e:
        return {
            "success": False,
            "message": f"API request failed: {str(e)}"
        }

@mcp.tool()
def get_user_profile() -> Dict[str, Any]:
    """
    Get the authenticated user's profile information from Microsoft Graph.
    
    Returns:
        Dict containing user profile information
    """
    try:
        # Make request to Microsoft Graph API
        result = authenticator.make_authenticated_request_sync(
            method="GET",
            url="https://graph.microsoft.com/v1.0/me"
        )
        
        if result["success"]:
            return {
                "success": True,
                "user_profile": result["data"]
            }
        else:
            return result
    
    except Exception as e:
        return {
            "success": False,
            "message": f"Error getting user profile: {str(e)}"
        }

@mcp.tool()
def refresh_token() -> Dict[str, Any]:
    """
    Refresh the access token using the refresh token.
    
    Returns:
        Dict containing the new token information or error message
    """
    try:
        token = authenticator.get_access_token_sync()
        
        if token:
            token_info = authenticator.get_token_info()
            return {
                "success": True,
                "message": "Token refreshed successfully",
                "token_info": token_info
            }
        else:
            return {
                "success": False,
                "message": "Failed to refresh token. Please re-authenticate."
            }
    
    except Exception as e:
        return {
            "success": False,
            "message": f"Error refreshing token: {str(e)}"
        }

@mcp.tool()
def logout_user() -> Dict[str, Any]:
    """
    Log out the current user and clear all authentication tokens.
    
    Returns:
        Dict containing logout status
    """
    try:
        result = authenticator.logout_sync()
        return result
    except Exception as e:
        return {
            "success": False,
            "message": f"Logout failed: {str(e)}"
        }

@mcp.tool()
def get_server_info() -> Dict[str, Any]:
    """
    Get information about the MCP server configuration.
    
    Returns:
        Dict containing server configuration information
    """
    return {
        "server_name": config.server_name,
        "server_version": config.server_version,
        "tenant_id": config.tenant_id,
        "client_id": config.client_id,
        "backend_api_url": config.backend_api_url,
        "scopes": config.api_scopes_list,
        "redirect_uri": config.redirect_uri_computed,
        "oauth_callback_port": config.oauth_callback_port,
        "mcp_server_port": config.server_port
    }

@mcp.tool()
def view_sessionid() -> str:
    """
    View session id
    
    Returns:
        returns current session id string.
    """
    global SESSION_ID
    return SESSION_ID or ""


@mcp.tool()
def get_session() -> str:
    """
    Get user session.
    
    Returns:
        session id string.
    """
    result = private_get_session()
    if result is None:
        result = ""
    return result

@mcp.tool()
def send_chat_message(conversation_id: str, message: str) -> str:
    """Send chat message to SimpleChat."""
    response = private_send_chat_message(conversation_id, message)
    return f"Get conversations called with session ID: {SESSION_ID}, has response: [{response}]."

def private_send_chat_message(conversation_id: str, message: str):
    global SESSION_ID

    print("private_send_chat_message called")
    print("=" * 40)

    if not message:
        return "Blank message received. Nothing to send."

    if SESSION_ID is None:
        raise Exception("Session ID is missing")

    url = f"{config.backend_api_url}api/chat"
    headers = {
        'Content-Type': 'application/json'
    }

    my_cookies = {
        "session": SESSION_ID
    }
    
    data = {
        'message':'',
        'conversation_id':'',
        'hybrid_search':False,
        'selected_document_id':None,
        'classifications':'',
        'bing_search':False,
        'image_generation':False,
        'doc_scope':'all',
        'chat_type':'user',
        'active_group_id':None,
        'model_deployment':'gpt-4.1'
    }
    data['message'] = message
    data['conversation_id'] = conversation_id

    print(f"Making request to: {url}")
    print(f"Headers: {headers}")
    print(f"My Cookies: {my_cookies}")
    print(f"Data: {data}")
    
    try:
        response = requests.post(url, json=data, headers=headers, cookies=my_cookies, verify=False)
        print(f"\nResponse Status: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        try:
            response_data = response.json()
            print(f"Response JSON: {json.dumps(response_data, indent=2)}")
            return response_data
        except Exception:
            return (f"Response Text: {response.text}")
            
    except Exception as e:
        return (f"Request failed: {e}")

def private_get_session():
    global SESSION_ID
    print("private_get_session() called")
    print("=" * 40)

    bearer_token = authenticator.get_access_token_sync()
    print(f"Bearer Token: {bearer_token}")
    if not bearer_token:
        raise Exception("Bearer token is missing")
    url = f"{config.backend_api_url}getASession"
    headers = {
        'Authorization': f'Bearer {bearer_token}',
        'Content-Type': 'application/json'
    }

    print(f"Making request to: {url}")
    
    try:
        response = requests.get(url, headers=headers, verify=False)
        print(f"\nResponse Status: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        cookie_name = "session"
        if cookie_name in response.cookies:
            SESSION_ID = response.cookies[cookie_name]
            return (f"The value of cookie '{cookie_name}' is: {SESSION_ID}")
        else:
            return ("Session cookie not found.")

        # print("\nAll cookies returned:")
        # for name, value in response.cookies.items():
        #     print(f"  {name}: {value}")

    except Exception as e:
        return (f"Request failed: {e}")

def private_get_conversations():
    global SESSION_ID

    print("private_get_conversations() called")
    print("=" * 40)

    if SESSION_ID is None:
        raise Exception("Session ID is missing")

    url = f"{config.backend_api_url}api/get_conversations"
    headers = {
        'Content-Type': 'application/json'
    }

    my_cookies = {
        "session": SESSION_ID
    }
    
    print(f"Making request to: {url}")
    print(f"Headers: {headers}")
    print(f"My Cookies: {my_cookies}")
    
    try:
        response = requests.get(url, headers=headers, cookies=my_cookies, verify=False)
        print(f"\nResponse Status: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")

        try:
            response_data = response.json()
            print(f"Response JSON: {json.dumps(response_data, indent=2)}")
        except Exception:
            print(f"Response Text: {response.text}")
            
    except Exception as e:
        return f"Request failed: {e}"

    return response_data

def main():
    """Main entry point for the MCP server."""
    try:
        # Validate configuration
        if not config.validate_config():
            print("Error: Invalid configuration. Please check your environment variables.")
            print("Required: TENANT_ID, CLIENT_ID, BACKEND_API_URL")
            return
        
        print(f"Starting {config.server_name} v{config.server_version}")
        print(f"Transport: {config.transport_type}")
        print(f"Tenant ID: {config.tenant_id}")
        print(f"Client ID: {config.client_id}")
        print(f"Backend API URL: {config.backend_api_url}")
        print(f"Scopes: {', '.join(config.api_scopes_list)}")
        
        # Run the MCP server with specified transport
        if config.transport_type.lower() == "http":
            print(f"Starting HTTP server on http://{config.server_host}:{config.server_port}")
            # Run HTTP server using streamable-http transport
            mcp.run(transport="streamable-http", host=config.server_host, port=config.server_port)
        else:
            print("Starting stdio server")
            mcp.run(transport="stdio")
        
    except KeyboardInterrupt:
        print("\nShutting down MCP server...")
    except Exception as e:
        print(f"Error starting MCP server: {e}")

if __name__ == "__main__":
    main()
