import requests
import os
import json
from auth_manager import AuthenticationManager
from config import SCOPES

from dotenv import load_dotenv
from fastmcp import FastMCP
from datetime import datetime

SESSION_ID = None
BEARER_TOKEN_OBJECT = None
ACCESS_TOKEN_VALUE = None
BACKEND_URL = os.getenv("FLASK_API_BASE_URL")
MCPSERVER_NAME = os.getenv("MCP_SERVER_NAME")
AUTHENTICATED = False
USER_INFO = None

load_dotenv()
mcp = FastMCP(name=MCPSERVER_NAME)

def check_authentication():
    """Check if user is authenticated and return error message if not"""
    global AUTHENTICATED, SESSION_ID
    if not AUTHENTICATED or SESSION_ID is None:
        return "Authentication required. Please run the 'login' tool first."
    return None

def require_authentication(func):
    """Decorator to ensure user is authenticated before calling MCP tools"""
    def wrapper(*args, **kwargs):
        global AUTHENTICATED, SESSION_ID
        if not AUTHENTICATED or SESSION_ID is None:
            return "Authentication required. Please run the 'login' tool first."
        return func(*args, **kwargs)
    return wrapper

def validate_session():
    """Validate current session with backend"""
    global SESSION_ID, BACKEND_URL, ACCESS_TOKEN_VALUE
    
    if not SESSION_ID:
        return False
        
    try:
        url = f"{BACKEND_URL}/api/user_info"  # or any authenticated endpoint
        headers = {'Content-Type': 'application/json'}
        cookies = {"session": SESSION_ID}
        
        response = requests.get(url, headers=headers, cookies=cookies, verify=False, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Session validation failed: {e}")
        return False

@mcp.tool()
def health() -> str:
    """Health check with authentication status."""
    global AUTHENTICATED, SESSION_ID
    
    current_datetime = datetime.now()
    formatted_datetime = current_datetime.strftime("%Y-%m-%d %H:%M:%S")
    
    auth_status = "Authenticated" if AUTHENTICATED and SESSION_ID else "Not authenticated"
    session_info = f" (Session: {SESSION_ID[:8]}...)" if SESSION_ID else ""
    
    # Test backend connectivity
    try:
        url = f"{BACKEND_URL}/api/chat/conversations"
        response = requests.get(url, verify=False, timeout=5)
        backend_status = f"Backend: {'OK' if response.status_code in [200, 401, 403] else f'HTTP {response.status_code}'}"
    except Exception as e:
        backend_status = f"Backend: Error - {str(e)[:50]}"
    
    return f"MCP Server is up {formatted_datetime}. {auth_status}{session_info}. {backend_status}"

@mcp.tool()
def logout() -> str:
    """Logout from SimpleChat and clear authentication session."""
    global AUTHENTICATED, SESSION_ID
    
    if AUTHENTICATED and SESSION_ID:
        # Optionally call backend logout endpoint
        try:
            url = f"{BACKEND_URL}/api/logout"
            headers = {'Content-Type': 'application/json'}
            cookies = {"session": SESSION_ID}
            requests.post(url, headers=headers, cookies=cookies, verify=False, timeout=5)
        except Exception:
            pass  # Ignore logout errors, clear local state anyway
    
    AUTHENTICATED = False
    SESSION_ID = None
    return "Successfully logged out from SimpleChat"

@mcp.tool()
def login() -> str:
    """Login to SimpleChat and establish authentication session."""
    global AUTHENTICATED, SESSION_ID
    
    try:
        get_session()
        
        # Validate the session was established successfully
        if SESSION_ID and validate_session():
            AUTHENTICATED = True
            return f"Successfully logged in to SimpleChat with session ID: {SESSION_ID}"
        else:
            AUTHENTICATED = False
            SESSION_ID = None
            return "Login failed - could not establish valid session"
            
    except Exception as e:
        AUTHENTICATED = False
        SESSION_ID = None
        return f"Login failed: {str(e)}"

@mcp.tool()
def get_conversations() -> str:
    """Get conversations from SimpleChat (requires authentication)."""
    global AUTHENTICATED, SESSION_ID
    
    # Check authentication first
    auth_error = check_authentication()
    if auth_error:
        return auth_error
    
    # Validate session before proceeding
    if not validate_session():
        AUTHENTICATED = False
        SESSION_ID = None
        return "Session expired. Please login again using the 'login' tool."
    
    response = private_get_conversations()
    return f"Get conversations called with session ID: {SESSION_ID}, has response: [{response}]."

@mcp.tool()
def send_chat_message(message: str) -> str:
    """Send chat message to SimpleChat (requires authentication)."""
    global AUTHENTICATED, SESSION_ID
    
    # Check authentication first
    auth_error = check_authentication()
    if auth_error:
        return auth_error
    
    # Validate session before proceeding
    if not validate_session():
        AUTHENTICATED = False
        SESSION_ID = None
        return "Session expired. Please login again using the 'login' tool."
    
    response = private_send_chat_message(message)
    return f"Send chat message called with session ID: {SESSION_ID}, has response: [{response}]."


@mcp.resource("data://example/message")
def get_example_message() -> str:
    """Provides an example message."""
    return "This is a sample message from the resource."

def authenticate():
    global SESSION_ID
    global BEARER_TOKEN_OBJECT
    global ACCESS_TOKEN_VALUE
    global BACKEND_URL

    # Get authentication
    auth_manager = AuthenticationManager()
    BEARER_TOKEN_OBJECT = auth_manager.msal_app.acquire_token_interactive(
        scopes=SCOPES,
        prompt='select_account'
    )
    
    if not BEARER_TOKEN_OBJECT or "access_token" not in BEARER_TOKEN_OBJECT:
        print("Authentication failed!")
        return
    
    ACCESS_TOKEN_VALUE = BEARER_TOKEN_OBJECT['access_token']
    print("Got token")


def get_session():
    global SESSION_ID
    global BEARER_TOKEN_OBJECT
    global ACCESS_TOKEN_VALUE
    global BACKEND_URL
    print("Testing get_session() Call")
    print("=" * 40)

    # authenticate to get bearer token first
    authenticate()

    url = f"{BACKEND_URL}/getASession"
    headers = {
        'Authorization': f'Bearer {ACCESS_TOKEN_VALUE}',
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
            print(f"The value of cookie '{cookie_name}' is: {SESSION_ID}")
        else:
            print(f"Cookie '{cookie_name}' not found in the response.")

        print("\nAll cookies returned:")
        for name, value in response.cookies.items():
            print(f"  {name}: {value}")

        try:
            response_data = response.json()
            print(f"Response JSON: {json.dumps(response_data, indent=2)}")
        except Exception as e:
            print(f"Response Text: {response.text}")
            print(f"JSON parse error: {e}")
            
        if response.status_code == 200:
            print("SUCCESS! Session established!")
        else:
            print("API call failed")
            
    except Exception as e:
        print(f"Request failed: {e}")


def private_get_conversations():
    global SESSION_ID
    global BEARER_TOKEN_OBJECT
    global ACCESS_TOKEN_VALUE
    global BACKEND_URL

    print("Testing private_get_conversations() Call")
    print("=" * 40)

    if SESSION_ID is None:
        raise Exception("Session ID is missing")

    url = f"{BACKEND_URL}/api/get_conversations"
    headers = {
        #'Authorization': f'Bearer {ACCESS_TOKEN_VALUE}',
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

        # cookie_name = "session"
        # if cookie_name in response.cookies:
        #     SESSION_ID = response.cookies[cookie_name]
        #     print(f"The value of cookie '{cookie_name}' is: {SESSION_ID}")
        # else:
        #     print(f"Cookie '{cookie_name}' not found in the response.")

        # print("\nAll cookies returned:")
        # for name, value in response.cookies.items():
        #     print(f"  {name}: {value}")

        try:
            response_data = response.json()
            print(f"Response JSON: {json.dumps(response_data, indent=2)}")
        except Exception as e:
            print(f"Response Text: {response.text}")
            print(f"JSON parse error: {e}")
            
        # if response.status_code == 200:
        #     print("SUCCESS! Get Conversations is working!")
        # else:
        #     print("API call failed")
            
    except Exception as e:
        return f"Request failed: {e}"

    return response_data

def private_send_chat_message(message: str):
    global SESSION_ID
    global BEARER_TOKEN_OBJECT
    global ACCESS_TOKEN_VALUE
    global BACKEND_URL

    print("Testing Internal API Direct Call")
    print("=" * 40)

    if not message:
        return "Blank message received. Nothing to send."

    if SESSION_ID is None:
        raise Exception("Session ID is missing")

    url = f"{BACKEND_URL}/api/chat"
    headers = {
        'Authorization': f'Bearer {ACCESS_TOKEN_VALUE}',
        'Content-Type': 'application/json'
    }

    my_cookies = {
        "session": SESSION_ID
    }
    
    #"message":"Hello","conversation_id":"25bf1a4e-b6f8-4bb4-957d-b345d8f43c94","hybrid_search":false,"selected_document_id":null,"classifications":"","bing_search":false,"image_generation":false,"doc_scope":"all","chat_type":"user","active_group_id":null,"model_deployment":"gpt-4.1"
    # data = {
    #     'message': 'Hello, this is a test message!',
    #     'conversation_id': 'test-conversation',
    #     'user_id': 'test-user'
    # }

    data = {
        'message':'',
        'conversation_id':'25bf1a4e-b6f8-4bb4-957d-b345d8f43c94',
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
    
    print(f"Making request to: {url}")
    print(f"Headers: {headers}")
    print(f"My Cookies: {my_cookies}")
    print(f"Data: {data}")
    
    try:
        response = requests.post(url, json=data, headers=headers, cookies=my_cookies, verify=False)
        print(f"\nResponse Status: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        
        cookie_name = "session"
        if cookie_name in response.cookies:
            SESSION_ID = response.cookies[cookie_name]
            print(f"The value of cookie '{cookie_name}' is: {SESSION_ID}")
        else:
            print(f"Cookie '{cookie_name}' not found in the response.")

        print("\nAll cookies returned:")
        for name, value in response.cookies.items():
            print(f"  {name}: {value}")

        try:
            response_data = response.json()
            print(f"Response JSON: {json.dumps(response_data, indent=2)}")
            return response_data
        except Exception as e:
            print(f"Response Text: {response.text}")
            print(f"JSON parse error: {e}")
            
        # if response.status_code == 200:
        #     print("SUCCESS! Internal chat call is working!")
        # else:
        #     print("API call failed")
            
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    mcp.run()
    #mcp.run(transport="stdio")
    # mcp.run(
    #     transport="streamable-http",  # Specify the transport type
    #     host="127.0.0.1",            # Host address (default: localhost)
    #     port=8080,                   # Port number (default: 8000)
    #     path="/mcp"
    #     # ,                 # Path for the MCP endpoint
    #     # debug=True                   # Enable debug mode (optional)
    # )
