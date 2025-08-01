import requests
import json
from auth_manager import AuthenticationManager
from config import SCOPES

from fastmcp import FastMCP
from datetime import datetime

SESSION_ID = None
BEARER_TOKEN_OBJECT = None
ACCESS_TOKEN_VALUE = None
BACKEND_URL = "https://127.0.0.1:5443"

mcp = FastMCP(name="SimpleChat MCP Server")

@mcp.tool()
def health() -> str:
    """Health check."""
    current_datetime = datetime.now()
    print("Current date and time (raw datetime object):", current_datetime)
    formatted_datetime = current_datetime.strftime("%Y-%m-%d %H:%M:%S")
    print("Current date and time (formatted):", formatted_datetime)
    return f"MCP Server is up {formatted_datetime}."

@mcp.tool()
def login() -> str:
    """Login to SimpleChat."""
    get_session()
    return f"You are logged in to SimpleChat with session ID: {SESSION_ID}!"

@mcp.tool()
def get_conversations() -> str:
    """Get conversations from SimpleChat."""
    response = private_get_conversations()
    return f"Get conversations called with session ID: {SESSION_ID}, has response: [{response}]."

@mcp.tool()
def send_chat_message(message: str) -> str:
    """Send chat message to SimpleChat."""
    response = private_send_chat_message(message)
    return f"Get conversations called with session ID: {SESSION_ID}, has response: [{response}]."


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
        except:
            print(f"Response Text: {response.text}")
            
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
        except:
            print(f"Response Text: {response.text}")
            
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
        except:
            print(f"Response Text: {response.text}")
            
        # if response.status_code == 200:
        #     print("SUCCESS! Internal chat call is working!")
        # else:
        #     print("API call failed")
            
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    #mcp.run()
    mcp.run(transport="stdio")