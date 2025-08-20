import uuid
import logging
from typing import Dict, Optional, Any
from urllib.parse import urlencode
import msal

from config import Config, TokenManager

logger = logging.getLogger(__name__)


class AuthManager:
    """Handles Microsoft Entra ID OAuth authentication using MSAL public client"""
    
    def __init__(self, config: Config, token_manager: TokenManager):
        self.config = config
        self.token_manager = token_manager
        self.pending_auth_requests = {}  # Store state -> user_id mappings
        self.msal_app = None
        
        # Only initialize MSAL if we have valid configuration
        if config.client_id and config.tenant_id:
            try:
                # Initialize MSAL public client application
                self.msal_app = msal.PublicClientApplication(
                    client_id=config.client_id,
                    authority=config.authority
                )
                logger.info("MSAL application initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize MSAL: {e}")
                self.msal_app = None
        else:
            logger.warning("MSAL not initialized - missing client_id or tenant_id")
    
    def start_auth_flow(self, user_id: str) -> str:
        """Start OAuth flow and return authorization URL"""
        if not self.msal_app:
            raise RuntimeError("MSAL not initialized - check Azure configuration")
        
        # Generate random state for CSRF protection
        state = str(uuid.uuid4())
        self.pending_auth_requests[state] = user_id
        
        # Build authorization URL
        auth_url = self.msal_app.get_authorization_request_url(
            scopes=self.config.scopes,
            state=state,
            redirect_uri=self.config.redirect_uri
        )
        
        logger.info(f"Starting auth flow for user {user_id} with state {state}")
        return auth_url
    
    def handle_auth_callback(self, code: str, state: str) -> Dict[str, Any]:
        """Handle OAuth callback and exchange code for tokens"""
        if not self.msal_app:
            raise RuntimeError("MSAL not initialized - check Azure configuration")
        
        # Verify state parameter
        if state not in self.pending_auth_requests:
            raise ValueError("Invalid or expired authentication state")
        
        user_id = self.pending_auth_requests.pop(state)
        
        try:
            # Exchange authorization code for tokens
            result = self.msal_app.acquire_token_by_authorization_code(
                code=code,
                scopes=self.config.scopes,
                redirect_uri=self.config.redirect_uri
            )
            
            if "error" in result:
                error_msg = f"Token exchange failed: {result.get('error_description', result['error'])}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            # Store tokens
            self.token_manager.set_token(user_id, result)
            
            logger.info(f"Successfully authenticated user: {user_id}")
            
            return {
                "success": True,
                "user_id": user_id,
                "access_token": result.get("access_token"),
                "token_type": result.get("token_type", "Bearer"),
                "expires_in": result.get("expires_in"),
                "scope": result.get("scope")
            }
            
        except Exception as e:
            logger.error(f"Authentication failed for user {user_id}: {e}")
            raise
    
    def get_access_token(self, user_id: str) -> Optional[str]:
        """Get valid access token for user, refreshing if necessary"""
        # Try to get cached token
        token = self.token_manager.get_access_token(user_id)
        if token:
            return token
        
        # Try to refresh token
        logger.info(f"Attempting to refresh token for user: {user_id}")
        token = self.token_manager.refresh_token(user_id, self.msal_app)
        if token:
            return token
        
        logger.warning(f"No valid token available for user: {user_id}")
        return None
    
    def is_authenticated(self, user_id: str) -> bool:
        """Check if user has valid authentication"""
        return self.get_access_token(user_id) is not None
    
    def logout(self, user_id: str):
        """Logout user by clearing tokens"""
        self.token_manager.clear_token(user_id)
        logger.info(f"User logged out: {user_id}")
    
    def get_logout_url(self, user_id: str) -> str:
        """Get Microsoft logout URL"""
        logout_params = {
            "post_logout_redirect_uri": f"http://{self.config.server_host}:{self.config.server_port}/auth/logout-complete"
        }
        
        logout_url = f"{self.config.authority}/oauth2/v2.0/logout?{urlencode(logout_params)}"
        return logout_url
