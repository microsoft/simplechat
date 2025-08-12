#!/usr/bin/env python3
"""
FastMCP Server with Microsoft Entra ID OAuth Authentication

This MCP server authenticates users with Microsoft Entra ID and provides
tools for making authenticated requests to backend APIs using bearer tokens.

    # return {
    #     "success": True,
    #     "auth_url": auth_url,
    #     "message": f"Please visit the following URL to authenticate: {auth_url}",
    #     "instructions": "After authentication, you can use other tools with your user_id"
    # }

"""
import requests
import json
import asyncio
import logging
import sys
import httpx

from urllib import response
from typing import Any, Dict, Optional, Sequence
from contextlib import asynccontextmanager

from datetime import datetime
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
from fastmcp import FastMCP

# Local imports
from config import Config, TokenManager
from auth import AuthManager
from api_client import ApiClient

SESSION_ID = ""
USER_ID = ""
TIMEOUT = 120  # Request timeout in seconds

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global configuration and managers
config = Config()
token_manager = TokenManager(config.token_cache_file)
auth_manager = AuthManager(config, token_manager)
api_client = None
BACKEND_API_BASE_URL = f"{config.backend_api_base_url}"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan"""
    # Startup
    global api_client
    if BACKEND_API_BASE_URL:
        api_client = ApiClient(BACKEND_API_BASE_URL)
    logger.info("FastAPI server started")
    
    yield
    
    # Shutdown
    if api_client:
        await api_client.close()
    logger.info("FastAPI server shutdown")


# Initialize FastMCP first
mcp = FastMCP("entra-auth-mcp")

# Create the MCP app and get its lifespan
mcp_app = mcp.http_app()

@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    """Combined lifespan for both FastAPI and FastMCP"""
    # Start FastMCP lifespan
    async with mcp_app.lifespan(app) as mcp_lifespan:
        # Start our custom lifespan
        async with lifespan(app) as our_lifespan:
            yield

# Initialize FastAPI app for OAuth callbacks with combined lifespan  
app = FastAPI(
    title="SimpleChat MCP Server", 
    description="Interact with any SimpleChat instance using OAuth authentication.",
    lifespan=combined_lifespan
)

#########################################
#
# FAST API METHODS - SHIM LAYER
#
#########################################
# OAuth callback endpoints
@app.get("/auth/login")
async def login(user_id: str = Query(..., description="User identifier")):
    """Start OAuth login flow"""
    try:
        auth_url = auth_manager.start_auth_flow(user_id)
        return RedirectResponse(url=auth_url)
    except Exception as e:
        logger.error(f"Login failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/auth/callback")
async def auth_callback(
    code: str = Query(..., description="Authorization code"),
    state: str = Query(..., description="State parameter"),
    error: Optional[str] = Query(None, description="Error parameter")
):
    """Handle OAuth callback"""
    if error:
        logger.error(f"OAuth error: {error}")
        return HTMLResponse(
            content=f"<html><body><h1>Authentication Error</h1><p>{error}</p></body></html>",
            status_code=400
        )
    
    try:
        result = auth_manager.handle_auth_callback(code, state)
        return HTMLResponse(
            content=f"""
            <html>
            <body>
                <h1>Authentication Successful</h1>
                <p>User ID: {result['user_id']}</p>
                <p>Token Type: {result['token_type']}</p>
                <p>Expires In: {result['expires_in']} seconds</p>
                <p>You can now close this window and return to your MCP client.</p>
            </body>
            </html>
            """,
            status_code=200
        )
    except Exception as e:
        logger.error(f"Callback processing failed: {e}")
        return HTMLResponse(
            content=f"<html><body><h1>Authentication Failed</h1><p>{str(e)}</p></body></html>",
            status_code=400
        )

@app.get("/auth/logout")
async def logout(user_id: str = Query(..., description="User identifier")):
    """Logout user"""
    try:
        logout_url = auth_manager.get_logout_url(user_id)
        auth_manager.logout(user_id)
        return RedirectResponse(url=logout_url)
    except Exception as e:
        logger.error(f"Logout failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/auth/logout-complete")
async def logout_complete():
    """Handle logout completion"""
    return HTMLResponse(
        content="<html><body><h1>Logout Complete</h1><p>You have been successfully logged out.</p></body></html>"
    )

@app.get("/auth/status")
async def auth_status(user_id: str = Query(..., description="User identifier")):
    """Check authentication status"""
    is_authenticated = auth_manager.is_authenticated(user_id)
    return {
        "user_id": user_id,
        "authenticated": is_authenticated,
        "has_token": auth_manager.get_access_token(user_id) is not None
    }


#########################################
#
# MCP SERVER - BASE TOOLS
#
#########################################
@mcp.tool()
async def authenticate_user(user_id: str) -> Dict[str, Any]:
    """
    Start OAuth authentication flow for a user.
    
    Args:
        user_id: Unique identifier for the user
        
    Returns:
        Dictionary with authentication URL and instructions
    """
    try:
        auth_url = auth_manager.start_auth_flow(user_id)
        global USER_ID
        USER_ID = user_id  # Store user ID globally for session management
        return {
            "success": True,
            "auth_url": auth_url,
            "message": f"Please visit the following URL to authenticate: {auth_url}",
            "instructions": "After authentication, you can use other tools with your user_id"
        }
    except Exception as e:
        logger.error(f"Authentication start failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to start authentication flow"
        }


@mcp.tool()
async def check_auth_status() -> Dict[str, Any]:
    """
    Check if a user is authenticated and has a valid token.
    
    Args:
        user_id: Unique identifier for the user
        
    Returns:
        Dictionary with authentication status
    """
    global USER_ID
    if not USER_ID:
        return {
            "success": False,
            "error": "User ID is not set",
            "message": "Please authenticate first using authenticate_user tool"
        }
    user_id = USER_ID
    is_authenticated = auth_manager.is_authenticated(user_id)
    has_token = auth_manager.get_access_token(user_id) is not None
    
    return {
        "user_id": user_id,
        "authenticated": is_authenticated,
        "has_valid_token": has_token,
        "message": "User is authenticated" if is_authenticated else "User needs to authenticate"
    }


@mcp.tool()
async def logout_user() -> Dict[str, Any]:
    """
    Logout a user by clearing their tokens.
    
    Args:
        user_id: Unique identifier for the user
        
    Returns:
        Dictionary with logout status
    """
    global USER_ID
    if not USER_ID:
        return {
            "success": False,
            "error": "User ID is not set",
            "message": "Please authenticate first using authenticate_user tool"
        }
    user_id = USER_ID
    try:
        logout_url = auth_manager.get_logout_url(user_id)
        auth_manager.logout(user_id)
        
        return {
            "success": True,
            "logout_url": logout_url,
            "message": f"User {user_id} has been logged out. Visit {logout_url} to complete logout on Microsoft's side."
        }
    except Exception as e:
        logger.error(f"Logout failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to logout user"
        }

@mcp.tool()
def view_userid() -> str:
    """
    View user id
    
    Returns:
        returns current session id string.
    """
    global USER_ID
    if not USER_ID:
        return {
            "success": False,
            "error": "User ID is not set",
            "message": "Please authenticate first using authenticate_user tool"
        }
    return USER_ID or ""

@mcp.tool()
def view_sessionid() -> str:
    """
    View session id
    
    Returns:
        returns current session id string.
    """
    global SESSION_ID
    if not SESSION_ID:
        return {
            "success": False,
            "error": "Session ID is not set",
            "message": "Please authenticate first using authenticate_user tool"
        }
    return SESSION_ID

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
def ping() -> str:
    """ping."""
    current_datetime = datetime.now()
    print("Current date and time (raw datetime object):", current_datetime)
    formatted_datetime = current_datetime.strftime("%Y-%m-%d %H:%M:%S")
    print("Current date and time (formatted):", formatted_datetime)
    return f"MCP Server is up {formatted_datetime}."

@mcp.tool()
def get_server_info() -> Dict[str, Any]:
    """
    Get information about the MCP server configuration.
    
    Returns:
        Dict containing server configuration information
    """
    try:
        current_time = datetime.now().isoformat()
        return {
            "status": "healthy",
            "timestamp": current_time,
            "server_host": config.server_host,
            "server_port": config.server_port,
            "tenant_id": config.tenant_id,
            "client_id": config.client_id,
            "authority": config.authority,
            "backend_api_base_url": config.redirect_uri,
            "scopes": config.scopes
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

#########################################
#
# SIMPLE CHAT API TOOLS
#
#########################################
@mcp.tool()
def get_conversations() -> dict:
    """Get conversations from SimpleChat."""
    result = private_get_conversations()
    return {"success": True, "message": result, "sessionid": SESSION_ID}

#def send_chat_message(conversation_id: str, message: str) -> dict:
#def private_send_chat_message(message: str, conversation_id: str, group_id: str, model_choice: str):
@mcp.tool()
def send_chat_message(message: str, conversation_id: str, group_id: str, model_choice: str) -> dict:
    """Send chat message to SimpleChat."""
    result = private_send_chat_message(message, conversation_id, group_id, model_choice)
    return {"success": True, "message": result, "sessionid": SESSION_ID}

@mcp.tool()
def get_gpt_models() -> dict:
    """Gets the list of gpt models available in SimpleChat."""
    result = private_get_gpt_models()
    return {
        "success": True,
        "message": result
    }

@mcp.tool()
def get_embedding_models() -> dict:
    """Gets the list of embedding models available in SimpleChat."""
    result = private_get_embedding_models()
    return {
        "success": True,
        "message": result
    }

@mcp.tool()
def get_image_models() -> dict:
    """Gets the list of image models available in SimpleChat."""
    result = private_get_image_models()
    return {
        "success": True,
        "message": result
    }

@mcp.tool()
def set_application_url() -> dict:
    """Sets the SimpleChat base url."""
    result = private_set_application_url()
    return {
        "success": True,
        "message": result
    }

@mcp.tool()
def get_application_url() -> dict:
    """Gets the SimpleChat base url."""
    result = private_get_application_url()
    return {
        "success": True,
        "message": result
    }

@mcp.tool()
async def upload_file(file_content: str, filename: str, content_type: str = "application/octet-stream") -> dict[str, Any]:
    """
    Upload a file to the backend API endpoint.
    
    Args:
        file_content: Base64 encoded file content
        filename: Name of the file being uploaded
        content_type: MIME type of the file (optional, defaults to application/octet-stream)
    
    Returns:
        dict: Response from the backend API
    """
    global SESSION_ID
    try:
        import base64
        
        # Decode the base64 file content
        try:
            file_bytes = base64.b64decode(file_content)
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to decode file content: {str(e)}"
            }
        
        # Prepare the multipart form data
        files = {
            "file": (filename, file_bytes, content_type)
        }
        
        url = f"{BACKEND_API_BASE_URL}upload"
        print(f"Upload url is: {url}")

        # Send the file to the backend API
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=False) as client:
            logger.info(f"Uploading file '{filename}' to {url}")
            
            my_cookies = {
                "session": SESSION_ID
            }

            response = await client.post(
                url,
                files=files,
                cookies=my_cookies
            )
            
            response.raise_for_status()
            
            # Try to parse JSON response, fallback to text
            try:
                result = response.json()
            except Exception:
                result = {"message": response.text}
            
            logger.info(f"File upload successful: {response.status_code}")
            return {
                "success": True,
                "status_code": response.status_code,
                "response": result
            }
            
    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP error {e.response.status_code}: {e.response.text}"
        logger.error(error_msg)
        return {
            "success": False,
            "error": error_msg,
            "status_code": e.response.status_code
        }
        
    except httpx.TimeoutException:
        error_msg = f"Request timed out after {TIMEOUT} seconds"
        logger.error(error_msg)
        return {
            "success": False,
            "error": error_msg
        }
        
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(error_msg)
        return {
            "success": False,
            "error": error_msg
        }

#########################################
#
# PRIVATE FUNCTIONS
#
#########################################
def private_set_application_url(url: str) -> str:
    print("private_set_application_url called")
    print("=" * 40)
    BACKEND_API_BASE_URL = url
    return f"Set Simple Chat Application URL to: {BACKEND_API_BASE_URL}. This application instance must use the configured CLIENT_ID and TENANT_ID."

def private_get_application_url() -> str:
    print("private_get_application_url called")
    print("=" * 40)
    return f"Current Simple Chat Application URL to: {BACKEND_API_BASE_URL}"

def private_get_api_method_void(relative_url: str) -> json:
    global SESSION_ID
    print("private_get_api_method_void called")
    print("=" * 40)

    if SESSION_ID is None:
        raise Exception("Session ID is missing")

    url = f"{BACKEND_API_BASE_URL}{relative_url}"
    headers = {
        'Content-Type': 'application/json'
    }

    my_cookies = {
        "session": SESSION_ID
    }

    print(f"Making request to: {url}")

    try:
        response = requests.get(url, headers=headers, cookies=my_cookies, verify=False)
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

def private_get_gpt_models() -> str:
    print("private_get_gpt_models called")
    print("=" * 40)
    relative_url = "api/models/gpt"
    return private_get_api_method_void(relative_url)

def private_get_embedding_models() -> str:
    print("private_get_embedding_models called")
    print("=" * 40)
    relative_url = "api/models/embedding"
    return private_get_api_method_void(relative_url)

def private_get_image_models() -> str:
    print("private_get_image_models called")
    print("=" * 40)
    relative_url = "api/models/image"
    return private_get_api_method_void(relative_url)

def private_send_chat_message(message: str, conversation_id: str, group_id: str, model_choice: str):
    global SESSION_ID

    print("private_send_chat_message called")
    print("=" * 40)

    if not message:
        return "Blank message received. Nothing to send."

    if SESSION_ID is None:
        raise Exception("Session ID is missing")

    url = f"{BACKEND_API_BASE_URL}api/chat"
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
    data['model_deployment'] = model_choice
    data['active_group_id'] = group_id

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

def private_file_upload(conversation_id: str, message: str):
    global SESSION_ID

    print("private_file_upload called")
    print("=" * 40)

    if not message:
        return "Blank message received. Nothing to send."

    if SESSION_ID is None:
        raise Exception("Session ID is missing")

    url = f"{BACKEND_API_BASE_URL}upload"
    headers = {
        'Content-Type': 'application/json'
    }

    my_cookies = {
        "session": SESSION_ID
    }
    
    data = {
        'conversation_id': conversation_id,
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
    global USER_ID
    print("private_get_session() called")
    print("=" * 40)

    bearer_token = auth_manager.get_access_token(USER_ID)
    if not bearer_token:
        return {
            "success": False,
            "error": "User not authenticated",
            "message": "User needs to authenticate first"
        }

    # bearer_token = authenticator.get_access_token_sync()
    # print(f"Bearer Token: {bearer_token}")
    # if not bearer_token:
    #     raise Exception("Bearer token is missing")
    

    url = f"{BACKEND_API_BASE_URL}getASession"
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

    except Exception as e:
        return (f"Request failed: {e}")

def private_get_conversations():
    global SESSION_ID

    print("private_get_conversations() called")
    print("=" * 40)

    if SESSION_ID is None:
        raise Exception("Session ID is missing")

    url = f"{BACKEND_API_BASE_URL}api/get_conversations"
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

def create_combined_app():
    """Create combined FastAPI app with both OAuth and MCP endpoints"""
    # Mount MCP at root since it already has /mcp path
    app.mount("", mcp_app)
    return app

async def run_server():
    """Run the server with streamable HTTP protocol"""
    if not config.validate():
        logger.error("Configuration validation failed")
        sys.exit(1)
    
    logger.info("Starting FastMCP server with Microsoft Entra ID authentication")
    logger.info(f"Configuration: {config.to_dict()}")
    
    # Create combined app
    combined_app = create_combined_app()
    
    # Run with uvicorn
    config_uvicorn = uvicorn.Config(
        combined_app,
        host=config.server_host,
        port=config.server_port,
        log_level="info"
    )
    
    server = uvicorn.Server(config_uvicorn)
    await server.serve()

def main():
    """Main entry point"""
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
