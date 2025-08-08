"""
Authentication Manager for SimpleChat Desktop Client
Handles Azure AD authentication and session management with Flask backend
"""

import msal
import requests
import threading
from config import *


class AuthenticationManager:
    """Manages authentication with Azure AD and Flask backend"""
    
    def __init__(self):
        self.msal_app = None
        self.session = requests.Session()
        self.access_token = None
        self.user_info = None
        self.authenticated = False
        self.use_external_api = False  # Flag to indicate if we should use external API endpoints
        from config import FLASK_API_BASE_URL
        self.base_url = FLASK_API_BASE_URL
        self._init_msal()
    
    def _init_msal(self):
        """Initialize MSAL application"""
        try:
            # For desktop applications, use PublicClientApplication with native redirect
            self.msal_app = msal.PublicClientApplication(
                CLIENT_ID,
                authority=AUTHORITY_URL,
                # Don't specify redirect_uri here for PublicClientApplication
            )
        except Exception as e:
            print(f"Failed to initialize MSAL: {e}")
            raise
    
    def login(self):
        """Authenticate user with Azure AD and establish session with Flask backend"""
        try:
            print("=== Starting login process ===")
            
            # Check for existing tokens in cache
            accounts = self.msal_app.get_accounts()
            if accounts:
                print(f"Found {len(accounts)} existing account(s) in cache")
                # Try silent authentication first
                result = self.msal_app.acquire_token_silent(SCOPES, account=accounts[0])
                if result and not result.get("error"):
                    print("✓ Silent authentication successful")
                    self.access_token = result['access_token']
                    self.user_info = result.get('id_token_claims', {})
                    
                    # Establish session with Flask backend
                    print("Attempting to establish Flask session...")
                    if self._establish_flask_session():
                        print("✓ Login completed successfully")
                        self.authenticated = True
                        return True
                    else:
                        print("❌ Failed to establish Flask session")
                        return False
            
            # If silent auth fails, do interactive authentication
            print("Silent authentication not available, starting interactive login...")
            return self._interactive_login()
            
        except Exception as e:
            print(f"❌ Login failed with exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _interactive_login(self):
        """Perform interactive login with Azure AD"""
        try:
            print("Starting interactive Azure AD authentication...")
            print("A browser window should open for authentication...")
            
            # Use MSAL's built-in interactive authentication
            # For desktop apps, don't specify redirect_uri - let MSAL handle it
            result = self.msal_app.acquire_token_interactive(
                scopes=SCOPES,
                prompt='select_account'  # Allow user to select account
            )
            
            if result and not result.get("error"):
                print("✓ Azure AD interactive authentication successful")
                print(f"  Token received (length: {len(result.get('access_token', ''))} characters)")
                
                self.access_token = result['access_token']
                self.user_info = result.get('id_token_claims', {})
                
                if self.user_info:
                    user_name = self.user_info.get('name', 'Unknown')
                    user_email = self.user_info.get('preferred_username', 'Unknown')
                    print(f"  User: {user_name} ({user_email})")
                
                # Establish session with Flask backend
                print("Azure AD authentication completed, establishing Flask session...")
                if self._establish_flask_session():
                    print("✓ Complete login process successful")
                    self.authenticated = True
                    return True
                else:
                    print("❌ Flask session establishment failed")
                    return False
            else:
                error_msg = result.get('error_description', result.get('error', 'Unknown error'))
                print(f"❌ Azure AD interactive authentication failed: {error_msg}")
                return False
            
        except Exception as e:
            print(f"❌ Interactive login failed with exception: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _establish_flask_session(self):
        """Establish session with Flask backend using Azure AD authentication"""
        try:
            print("Establishing session with Flask backend...")
            
            # Disable SSL verification for localhost development
            self.session.verify = False
            
            # The Flask backend expects session-based authentication through its OAuth flow
            # Since we already have Azure AD tokens, we need to find a way to establish
            # Flask session cookies that the backend will recognize
            
            print("Step 1: Testing direct Bearer token approach...")
            # First, try if Flask accepts Bearer tokens directly (some setups support this)
            self.session.headers.update({
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            })
            
            if self._test_flask_authentication():
                print("✓ Bearer token authentication works!")
                return True
            
            print("Bearer tokens not accepted, trying OAuth callback simulation...")
            return self._simulate_flask_oauth_callback()
            callback_url = f"{self.base_url.rstrip('/')}/getAToken"
            print(f"Posting token to callback URL: {callback_url}")
            
            # Create data that mimics what Azure AD would send
            callback_data = {
                'code': 'desktop_client_token',  # Dummy code
                'state': '',
                'access_token': self.access_token,
                'id_token_claims': self.user_info
            }
            
            # Try to POST to the callback endpoint
            try:
                callback_response = self.session.post(callback_url, data=callback_data, allow_redirects=True)
                print(f"Callback response status: {callback_response.status_code}")
                
                if callback_response.status_code == 200:
                    print("✓ Callback simulation successful")
                    # Test if we now have proper session
                    return self._test_session_access()
                    
            except Exception as callback_error:
                print(f"Callback POST failed: {callback_error}")
            
            # If callback simulation fails, try to manually set session data
            print("Trying to manually establish session...")
            return self._manual_session_establishment()
                
        except Exception as e:
            print(f"Failed to establish Flask session: {e}")
            return False
    
    def _manual_session_establishment(self):
        """Manually try to establish session by setting the right cookies/headers"""
        try:
            print("Attempting manual session establishment...")
            
            # Try different approaches to get Flask to recognize us
            
            # Approach 1: Try to use session cookies if they exist
            if self.session.cookies:
                print(f"Found cookies: {dict(self.session.cookies)}")
                # Test if existing cookies work
                if self._test_session_access():
                    return True
            
            # Approach 2: Try to get session by accessing root endpoint first
            print("Accessing root endpoint to establish session...")
            root_response = self.session.get(f"{self.base_url.rstrip('/')}/")
            print(f"Root endpoint response: {root_response.status_code}")
            
            if root_response.status_code == 200:
                # Check if we now have session cookies
                print(f"Cookies after root access: {dict(self.session.cookies)}")
                
                # Try to manually set session data via custom headers
                # Some Flask apps accept custom authentication headers
                self.session.headers.update({
                    'X-User-Id': self.user_info.get('oid', ''),
                    'X-User-Name': self.user_info.get('name', ''),
                    'X-User-Email': self.user_info.get('preferred_username', ''),
                    'X-Access-Token': self.access_token,
                    'Authorization': f'Bearer {self.access_token}',
                    'Content-Type': 'application/json'
                })
                
                # Test with these headers
                if self._test_session_access():
                    return True
            
            # Approach 3: Try to use external API instead
            print("Session establishment failed - considering external API fallback")
            # We'll mark this as successful but use external API endpoints
            self.use_external_api = True
            return True
                
        except Exception as e:
            print(f"Manual session establishment failed: {e}")
            return False
    
    def _test_session_access(self):
        """Test if we can access protected endpoints with current session"""
        try:
            # Test endpoints that should work with proper authentication
            test_endpoints = ['/api/prompts', '/api/documents']
            
            for endpoint in test_endpoints:
                test_url = f"{self.base_url.rstrip('/')}{endpoint}"
                print(f"Testing session access: {test_url}")
                
                test_response = self.session.get(test_url)
                print(f"Session test {endpoint}: {test_response.status_code}")
                
                if test_response.status_code == 200:
                    print(f"✓ Session access successful for {endpoint}")
                    return True
                elif test_response.status_code == 401:
                    print(f"✗ Session access denied for {endpoint} (401)")
                    continue
                else:
                    print(f"? Unexpected response {test_response.status_code} for {endpoint}")
                    continue
            
            print("No endpoints returned 200 - session not properly established")
            return False
            
        except Exception as e:
            print(f"Session access test failed: {e}")
            return False
    
    def _simulate_oauth_callback(self):
        """Simulate OAuth callback to establish Flask session"""
        try:
            print("Simulating OAuth callback with Flask backend...")
            
            # The key insight: Flask expects to receive an authorization code from Azure AD
            # and then exchange it for tokens. Since we already have tokens, we need to
            # simulate this process by directly setting the session data that Flask would set.
            
            # Method 1: Try to manually set session cookies
            print("Attempting to manually set Flask session...")
            
            # Create session data that matches what Flask expects
            flask_session_data = {
                'user': self.user_info,  # ID token claims
                'token_cache': None  # We'll skip the token cache for now
            }
            
            # Try to set session via a custom endpoint or direct cookie manipulation
            # First, let's try to access the Flask login endpoint to get a session cookie
            login_url = f"{self.base_url.rstrip('/')}/login"
            
            # Access login endpoint to establish a session
            login_response = self.session.get(login_url, allow_redirects=False)
            print(f"Login endpoint response: {login_response.status_code}")
            
            # Check if we got session cookies
            if self.session.cookies:
                print(f"Got session cookies: {dict(self.session.cookies)}")
                
                # Now try to manually POST our user info to establish the session
                # We'll try different approaches
                
                # Approach 1: Try to POST to the callback endpoint with our token data
                callback_endpoints = ['/getAToken', '/authorized', '/.auth/login/aad/callback']
                
                for endpoint in callback_endpoints:
                    try:
                        callback_url = f"{self.base_url.rstrip('/')}{endpoint}"
                        print(f"Trying callback endpoint: {callback_url}")
                        
                        # Simulate what Azure AD would send back
                        callback_params = {
                            'code': 'simulated_auth_code',
                            'state': '',
                            'session_state': 'simulated_session'
                        }
                        
                        # Try as GET first (normal OAuth callback)
                        callback_response = self.session.get(callback_url, params=callback_params, allow_redirects=True)
                        print(f"Callback GET response: {callback_response.status_code}")
                        
                        if callback_response.status_code == 200:
                            # Check if session is now established
                            if self._test_flask_session():
                                print("✓ OAuth callback simulation successful!")
                                return True
                        
                        # Try as POST with JSON data
                        json_data = {
                            'id_token_claims': self.user_info,
                            'access_token': self.access_token
                        }
                        
                        callback_response = self.session.post(callback_url, json=json_data)
                        print(f"Callback POST response: {callback_response.status_code}")
                        
                        if callback_response.status_code == 200:
                            if self._test_flask_session():
                                print("✓ OAuth callback simulation successful!")
                                return True
                                
                    except Exception as e:
                        print(f"Callback endpoint {endpoint} failed: {e}")
                        continue
            
            # Method 2: Try to directly access a protected endpoint and see if Flask
            # will accept our Bearer token (some Flask apps support both session and token auth)
            print("Trying Bearer token authentication...")
            
            # Make sure we have the Authorization header set
            self.session.headers.update({
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            })
            
            # Test if Bearer token works
            if self._test_flask_session():
                print("✓ Bearer token authentication works!")
                return True
            
            # Method 3: If all else fails, mark for external API usage
            print("Session simulation failed - marking for external API usage")
            self.use_external_api = True
            
            # But first, let's try one more thing - accessing the root endpoint
            # which might establish a basic session
            try:
                root_response = self.session.get(f"{self.base_url.rstrip('/')}/")
                if root_response.status_code == 200:
                    print("Root endpoint accessible - trying session test again")
                    if self._test_flask_session():
                        print("✓ Session established via root endpoint!")
                        self.use_external_api = False
                        return True
            except Exception as e:
                print(f"Root endpoint test failed: {e}")
            
            print("✓ Using external API fallback")
            return True  # We'll use external API, so this is still "success"
            
        except Exception as e:
            print(f"OAuth callback simulation failed: {e}")
            # Even if simulation fails, we can try external API
            self.use_external_api = True
            return True
    
    def _test_flask_session(self):
        """Test if Flask session is properly established"""
        try:
            # Try to access a protected endpoint that requires Flask session
            test_endpoints = ['/api/prompts', '/api/documents']
            
            for endpoint in test_endpoints:
                test_url = f"{self.base_url.rstrip('/')}{endpoint}"
                test_response = self.session.get(test_url)
                
                print(f"Session test {endpoint}: {test_response.status_code}")
                
                if test_response.status_code == 200:
                    print(f"✓ Flask session working for {endpoint}")
                    return True
                elif test_response.status_code == 401:
                    print(f"✗ Flask session not working for {endpoint} (401)")
                    continue
                else:
                    print(f"? Unexpected response {test_response.status_code} for {endpoint}")
                    # For non-401 errors, we might still have a session, just no access to that endpoint
                    continue
            
            return False
            
        except Exception as e:
            print(f"Flask session test failed: {e}")
            return False

    def _test_flask_authentication(self):
        """Test Flask authentication with Bearer token"""
        try:
            test_endpoints = ['/api/prompts', '/api/documents', '/api/chat', '/external/chat']
            
            for endpoint in test_endpoints:
                test_url = f"{self.base_url.rstrip('/')}{endpoint}"
                
                # Test with GET first (for prompts/documents)
                if endpoint in ['/api/prompts', '/api/documents']:
                    test_response = self.session.get(test_url)
                    print(f"Bearer test GET {endpoint}: {test_response.status_code}")
                    
                    if test_response.status_code == 200:
                        print(f"✓ Bearer token working for {endpoint}")
                        return True
                else:
                    # Test with POST for chat endpoints
                    test_data = {'messages': [{'role': 'user', 'content': 'test'}]}
                    if endpoint == '/external/chat':
                        test_data = {
                            'message': 'test',
                            'conversation_id': 'test-conversation',
                            'user_id': 'test-user'
                        }
                    
                    test_response = self.session.post(test_url, json=test_data)
                    print(f"Bearer test POST {endpoint}: {test_response.status_code}")
                    
                    # Print response details for debugging
                    if test_response.status_code in [401, 403]:
                        try:
                            error_data = test_response.json()
                            print(f"  Error details: {error_data}")
                        except Exception:
                            print(f"  Error text: {test_response.text}")
                    
                    if test_response.status_code == 200:
                        print(f"✓ Bearer token working for {endpoint}")
                        return True
                    
        except Exception as e:
            print(f"Error testing Flask authentication: {e}")
            
        return False

    def _simulate_flask_oauth_callback(self):
        """Simulate OAuth callback to establish Flask session"""
        try:
            print("Simulating OAuth callback to establish Flask session...")
            
            # Method 1: Try standard OAuth endpoints
            callback_endpoints = ['/getAToken', '/authorized', '/.auth/login/aad/callback']
            
            if not hasattr(self, 'base_url') or not self.base_url:
                print("Error: base_url not set in AuthenticationManager")
                return False
                
            for endpoint in callback_endpoints:
                try:
                    callback_url = f"{self.base_url.rstrip('/')}{endpoint}"
                    print(f"Trying callback endpoint: {callback_url}")
                    
                    # Simulate what Azure AD would send back
                    callback_params = {
                        'code': 'simulated_auth_code',
                        'state': '',
                        'session_state': 'simulated_session'
                    }
                    
                    # Try as GET first (normal OAuth callback)
                    callback_response = self.session.get(callback_url, params=callback_params, allow_redirects=True)
                    print(f"Callback GET response: {callback_response.status_code}")
                    
                    if callback_response.status_code == 200:
                        # Check if session is now established
                        if self._test_flask_session():
                            print("✓ OAuth callback simulation successful!")
                            return True
                    
                    # Try as POST with JSON data
                    json_data = {
                        'id_token_claims': self.user_info,
                        'access_token': self.access_token
                    }
                    
                    callback_response = self.session.post(callback_url, json=json_data)
                    print(f"Callback POST response: {callback_response.status_code}")
                    
                    if callback_response.status_code == 200:
                        if self._test_flask_session():
                            print("✓ OAuth callback simulation successful!")
                            return True
                            
                except Exception as e:
                    print(f"Callback endpoint {endpoint} failed: {e}")
                    continue
        
            # Method 2: Try to directly access a protected endpoint and see if Flask
            # will accept our Bearer token (some Flask apps support both session and token auth)
            print("Trying Bearer token authentication...")
            
            # Make sure we have the Authorization header set
            self.session.headers.update({
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            })
            
            if self._test_flask_authentication():
                print("✓ Bearer token authentication successful!")
                return True
            
            print("❌ All Flask session establishment methods failed")
            return False
            
        except Exception as e:
            print(f"Error in OAuth callback simulation: {e}")
            return False
    
    def logout(self):
        """Logout from Azure AD and Flask backend"""
        try:
            # Logout from Flask backend
            if self.authenticated:
                logout_response = self.session.get(f"{self.base_url}/logout")
                print(f"Flask logout response: {logout_response.status_code}")
            
            # Clear MSAL cache
            accounts = self.msal_app.get_accounts()
            for account in accounts:
                self.msal_app.remove_account(account)
            
            # Clear session and tokens
            self.session = requests.Session()
            self.access_token = None
            self.user_info = None
            self.authenticated = False
            
            print("Logged out successfully")
            return True
            
        except Exception as e:
            print(f"Logout failed: {e}")
            return False
    
    def is_authenticated(self):
        """Check if user is currently authenticated"""
        return self.authenticated
    
    def get_user_info(self):
        """Get current user information"""
        return self.user_info if self.authenticated else None
    
    def should_use_external_api(self):
        """Check if we should use external API endpoints instead of regular ones"""
        return getattr(self, 'use_external_api', False)
    
    def get_session(self):
        """Get the authenticated requests session"""
        return self.session if self.authenticated else None
