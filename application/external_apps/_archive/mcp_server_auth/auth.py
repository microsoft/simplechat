import json
import asyncio
import webbrowser
from typing import Dict, Optional, Any
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timedelta
import aiohttp
from aiohttp import web
import msal
from config import config

class EntraAuthenticator:
    """Handles Microsoft Entra ID authentication for the MCP server."""
    
    def __init__(self):
        self.app = None
        self.token_cache = msal.SerializableTokenCache()
        self.load_token_cache()
        
        # Build MSAL app based on configuration
        if config.app_type == "confidential" and config.client_secret:
            # Use ConfidentialClientApplication for web apps with client secrets
            self.msal_app = msal.ConfidentialClientApplication(
                client_id=config.client_id,
                client_credential=config.client_secret,
                authority=config.authority_url,
                token_cache=self.token_cache
            )
        else:
            # Use PublicClientApplication for desktop/mobile apps
            self.msal_app = msal.PublicClientApplication(
                client_id=config.client_id,
                authority=config.authority_url,
                token_cache=self.token_cache
            )
        
        self.auth_server = None
        self.auth_code = None
        self.auth_result = None
        self.actual_redirect_uri = None  # Will be set when auth server starts
        
    def load_token_cache(self):
        """Load existing token cache from file."""
        try:
            with open(config.token_cache_path, 'r') as f:
                cache_data = f.read()
                if cache_data:
                    self.token_cache.deserialize(cache_data)
        except FileNotFoundError:
            pass  # Cache file doesn't exist yet
        except Exception as e:
            print(f"Error loading token cache: {e}")
    
    def save_token_cache(self):
        """Save token cache to file."""
        try:
            if self.token_cache.has_state_changed:
                with open(config.token_cache_path, 'w') as f:
                    f.write(self.token_cache.serialize())
        except Exception as e:
            print(f"Error saving token cache: {e}")
    
    async def get_auth_url(self) -> str:
        """Generate the authorization URL for user authentication."""
        # Check if we have a cached token first
        accounts = self.msal_app.get_accounts()
        if accounts:
            # Try to get token silently
            result = self.msal_app.acquire_token_silent(
                scopes=config.api_scopes_list,
                account=accounts[0]
            )
            if result and "access_token" in result:
                self.auth_result = result
                self.save_token_cache()
                return None  # Already authenticated
        
        # Need to authenticate
        auth_url = self.msal_app.get_authorization_request_url(
            scopes=config.api_scopes_list,
            redirect_uri=config.redirect_uri_computed,
            state="auth_state"
        )
        return auth_url
    
    async def start_auth_server(self) -> int:
        """Start a temporary web server to handle the OAuth callback."""
        app = web.Application()
        app.router.add_get('/auth/callback', self.handle_callback)
        
        runner = web.AppRunner(app)
        await runner.setup()
        
        # Use the dedicated OAuth callback port (separate from MCP server port)
        port = config.oauth_callback_port
        
        try:
            site = web.TCPSite(runner, 'localhost', port)
            await site.start()
            print(f"OAuth callback server started on http://localhost:{port}/auth/callback")
        except OSError as e:
            if e.errno == 10048:  # Port already in use
                # Try the next port
                port = config.oauth_callback_port + 1
                print(f"Port {config.oauth_callback_port} in use, trying {port}")
                site = web.TCPSite(runner, 'localhost', port)
                await site.start()
                print(f"OAuth callback server started on http://localhost:{port}/auth/callback")
            else:
                raise
        
        self.auth_server = runner
        return port
    
    async def handle_callback(self, request):
        """Handle the OAuth callback from Microsoft Entra ID."""
        try:
            # Extract authorization code from query parameters
            query_params = parse_qs(urlparse(str(request.url)).query)
            
            if 'code' in query_params:
                auth_code = query_params['code'][0]
                
                # Exchange authorization code for tokens
                # Use the actual redirect URI that was used in the auth request
                redirect_uri_to_use = self.actual_redirect_uri or config.redirect_uri_computed
                result = self.msal_app.acquire_token_by_authorization_code(
                    code=auth_code,
                    scopes=config.api_scopes_list,
                    redirect_uri=redirect_uri_to_use
                )
                
                if "access_token" in result:
                    self.auth_result = result
                    self.save_token_cache()
                    
                    return web.Response(
                        text="Authentication successful! You can close this window.",
                        content_type='text/html'
                    )
                else:
                    error_msg = result.get('error_description', 'Unknown error')
                    return web.Response(
                        text=f"Authentication failed: {error_msg}",
                        status=400
                    )
            
            elif 'error' in query_params:
                error = query_params['error'][0]
                error_description = query_params.get('error_description', [''])[0]
                return web.Response(
                    text=f"Authentication error: {error} - {error_description}",
                    status=400
                )
            
            else:
                return web.Response(
                    text="Invalid callback parameters",
                    status=400
                )
                
        except Exception as e:
            return web.Response(
                text=f"Error processing callback: {str(e)}",
                status=500
            )
    
    async def stop_auth_server(self):
        """Stop the temporary authentication server."""
        if self.auth_server:
            await self.auth_server.cleanup()
            self.auth_server = None
    
    async def authenticate_user(self) -> Dict[str, Any]:
        """Perform the complete authentication flow."""
        try:
            # Check if we already have a valid token first
            accounts = self.msal_app.get_accounts()
            if accounts:
                # Try to get token silently
                result = self.msal_app.acquire_token_silent(
                    scopes=config.api_scopes_list,
                    account=accounts[0]
                )
                if result and "access_token" in result:
                    self.auth_result = result
                    self.save_token_cache()
                    return {
                        "success": True,
                        "message": "Already authenticated",
                        "token_info": self.get_token_info()
                    }
            
            # Start callback server first to get the actual port
            actual_port = await self.start_auth_server()
            actual_redirect_uri = f"http://localhost:{actual_port}/auth/callback"
            
            # Generate auth URL with the correct redirect URI
            auth_url = self.msal_app.get_authorization_request_url(
                scopes=config.api_scopes_list,
                redirect_uri=actual_redirect_uri,
                state="auth_state"
            )
            
            # Store the actual redirect URI for the callback
            self.actual_redirect_uri = actual_redirect_uri
            
            # Open browser for user authentication
            print(f"Opening browser for authentication: {auth_url}")
            print(f"OAuth callback will be handled at: {actual_redirect_uri}")
            webbrowser.open(auth_url)
            
            # Wait for authentication to complete
            timeout = 300  # 5 minutes
            start_time = datetime.now()
            
            while self.auth_result is None and (datetime.now() - start_time).seconds < timeout:
                await asyncio.sleep(1)
            
            # Stop the server
            await self.stop_auth_server()
            
            if self.auth_result and "access_token" in self.auth_result:
                return {
                    "success": True,
                    "message": "Authentication successful",
                    "token_info": self.get_token_info()
                }
            else:
                return {
                    "success": False,
                    "message": "Authentication timed out or failed"
                }
                
        except Exception as e:
            await self.stop_auth_server()
            return {
                "success": False,
                "message": f"Authentication error: {str(e)}"
            }
    
    def get_token_info(self) -> Optional[Dict[str, Any]]:
        """Get current token information."""
        if not self.auth_result:
            return None
        
        return {
            "access_token": self.auth_result.get("access_token"),
            "expires_in": self.auth_result.get("expires_in"),
            "token_type": self.auth_result.get("token_type", "Bearer"),
            "scope": self.auth_result.get("scope"),
            "expires_at": datetime.now() + timedelta(seconds=self.auth_result.get("expires_in", 3600))
        }
    
    async def get_access_token(self) -> Optional[str]:
        """Get a valid access token, refreshing if necessary."""
        # Try to get token silently first
        accounts = self.msal_app.get_accounts()
        if accounts:
            result = self.msal_app.acquire_token_silent(
                scopes=config.api_scopes_list,
                account=accounts[0]
            )
            if result and "access_token" in result:
                self.auth_result = result
                self.save_token_cache()
                return result["access_token"]
        
        # If no valid token, need to authenticate
        return None
    
    async def make_authenticated_request(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """Make an authenticated request to the backend API."""
        access_token = await self.get_access_token()
        
        if not access_token:
            return {
                "success": False,
                "message": "No valid access token available. Please authenticate first."
            }
        
        headers = kwargs.get('headers', {})
        headers['Authorization'] = f'Bearer {access_token}'
        kwargs['headers'] = headers
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, **kwargs) as response:
                    response_data = await response.text()
                    
                    try:
                        response_json = json.loads(response_data)
                    except json.JSONDecodeError:
                        response_json = {"raw_response": response_data}
                    
                    return {
                        "success": response.status < 400,
                        "status_code": response.status,
                        "headers": dict(response.headers),
                        "data": response_json
                    }
                    
        except Exception as e:
            return {
                "success": False,
                "message": f"Request failed: {str(e)}"
            }
    
    def is_authenticated(self) -> bool:
        """Check if user is currently authenticated."""
        accounts = self.msal_app.get_accounts()
        if not accounts:
            return False
        
        # Try to get token silently to check if it's valid
        result = self.msal_app.acquire_token_silent(
            scopes=config.api_scopes_list,
            account=accounts[0]
        )
        
        return result is not None and "access_token" in result
    
    async def logout(self) -> Dict[str, Any]:
        """Clear authentication tokens and cache."""
        try:
            # Clear the token cache
            if hasattr(self.token_cache, '_cache'):
                self.token_cache._cache.clear()
            
            # Remove cache file
            try:
                import os
                if os.path.exists(config.token_cache_path):
                    os.remove(config.token_cache_path)
            except Exception:
                pass
            
            self.auth_result = None
            
            return {
                "success": True,
                "message": "Logged out successfully"
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Logout error: {str(e)}"
            }

    # Truly synchronous methods for use with FastMCP tools
    
    def authenticate_user_sync(self) -> Dict[str, Any]:
        """Completely synchronous authentication using threading."""
        import time
        import webbrowser
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from urllib.parse import urlparse, parse_qs
        
        try:
            # Check if we already have a valid token
            accounts = self.msal_app.get_accounts()
            if accounts:
                result = self.msal_app.acquire_token_silent(
                    scopes=config.api_scopes_list,
                    account=accounts[0]
                )
                if result and "access_token" in result:
                    self.auth_result = result
                    self.save_token_cache()
                    return {
                        "success": True,
                        "message": "Already authenticated",
                        "token_info": self.get_token_info()
                    }
            
            # Use a different port for OAuth callback to avoid conflicts
            callback_port = config.oauth_callback_port
            actual_redirect_uri = f"http://localhost:{callback_port}/auth/callback"
            
            # Generate auth URL with the correct redirect URI
            auth_url = self.msal_app.get_authorization_request_url(
                scopes=config.api_scopes_list,
                redirect_uri=actual_redirect_uri,
                state="auth_state"
            )
            
            print(f"Starting OAuth callback server on port {callback_port}")
            print(f"Opening browser for authentication: {auth_url}")
            
            # Create a simple HTTP server for the callback
            auth_code_result = {'code': None, 'error': None}
            
            class CallbackHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    try:
                        parsed_url = urlparse(self.path)
                        query_params = parse_qs(parsed_url.query)
                        
                        if 'code' in query_params:
                            auth_code_result['code'] = query_params['code'][0]
                            self.send_response(200)
                            self.send_header('Content-type', 'text/html')
                            self.end_headers()
                            self.wfile.write(b'<html><body><h1>Authentication successful!</h1><p>You can close this window.</p></body></html>')
                        elif 'error' in query_params:
                            auth_code_result['error'] = query_params['error'][0]
                            self.send_response(400)
                            self.send_header('Content-type', 'text/html')
                            self.end_headers()
                            self.wfile.write(b'<html><body><h1>Authentication failed!</h1><p>You can close this window.</p></body></html>')
                        else:
                            self.send_response(404)
                            self.end_headers()
                    except Exception:
                        self.send_response(500)
                        self.end_headers()
                
                def log_message(self, format, *args):
                    pass  # Suppress log messages
            
            # Start the callback server
            try:
                server = HTTPServer(('localhost', callback_port), CallbackHandler)
                server.timeout = 1  # 1 second timeout for serving requests
                
                # Open browser
                webbrowser.open(auth_url)
                
                # Wait for callback with timeout
                timeout = 300  # 5 minutes
                start_time = time.time()
                
                while time.time() - start_time < timeout:
                    server.handle_request()
                    if auth_code_result['code'] or auth_code_result['error']:
                        break
                    time.sleep(0.1)
                
                server.server_close()
                
                if auth_code_result['error']:
                    return {
                        "success": False,
                        "message": f"Authentication error: {auth_code_result['error']}"
                    }
                
                if not auth_code_result['code']:
                    return {
                        "success": False,
                        "message": "Authentication timed out"
                    }
                
                # Exchange authorization code for tokens
                result = self.msal_app.acquire_token_by_authorization_code(
                    code=auth_code_result['code'],
                    scopes=config.api_scopes_list,
                    redirect_uri=actual_redirect_uri
                )
                
                if "access_token" in result:
                    self.auth_result = result
                    self.save_token_cache()
                    return {
                        "success": True,
                        "message": "Authentication successful",
                        "token_info": self.get_token_info()
                    }
                else:
                    error_msg = result.get('error_description', 'Unknown error')
                    return {
                        "success": False,
                        "message": f"Token exchange failed: {error_msg}"
                    }
                    
            except OSError as e:
                if e.errno == 10048:  # Port already in use
                    return {
                        "success": False,
                        "message": f"Port {callback_port} is already in use. Please change OAUTH_CALLBACK_PORT in your .env file."
                    }
                else:
                    raise
                    
        except Exception as e:
            return {
                "success": False,
                "message": f"Authentication error: {str(e)}"
            }
    
    def get_access_token_sync(self) -> str:
        """Get access token synchronously without asyncio."""
        try:
            # First try to get from current auth result
            if self.auth_result and "access_token" in self.auth_result:
                return self.auth_result["access_token"]
            
            # Try to get token silently
            accounts = self.msal_app.get_accounts()
            if accounts:
                result = self.msal_app.acquire_token_silent(
                    scopes=config.api_scopes_list,
                    account=accounts[0]
                )
                if result and "access_token" in result:
                    self.auth_result = result
                    self.save_token_cache()
                    return result["access_token"]
            
            return None
        except Exception:
            return None
    
    def make_authenticated_request_sync(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """Make authenticated HTTP request synchronously using requests library."""
        import requests
        
        try:
            # Get access token
            token = self.get_access_token_sync()
            if not token:
                return {
                    "success": False,
                    "message": "No valid access token available. Please authenticate first."
                }
            
            # Prepare headers
            headers = kwargs.get('headers', {})
            headers['Authorization'] = f'Bearer {token}'
            headers['Content-Type'] = 'application/json'
            kwargs['headers'] = headers
            
            # Make the request
            response = requests.request(method, url, **kwargs)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                except Exception:
                    data = response.text
                
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "data": data
                }
            else:
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "message": f"HTTP {response.status_code}: {response.text}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "message": f"Request error: {str(e)}"
            }
    
    def logout_sync(self) -> Dict[str, Any]:
        """Logout synchronously."""
        try:
            # Clear the token cache
            if hasattr(self.token_cache, '_cache'):
                self.token_cache._cache.clear()
            
            # Remove cache file
            try:
                import os
                if os.path.exists(config.token_cache_path):
                    os.remove(config.token_cache_path)
            except Exception:
                pass
            
            self.auth_result = None
            
            return {
                "success": True,
                "message": "Logged out successfully"
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Logout error: {str(e)}"
            }
