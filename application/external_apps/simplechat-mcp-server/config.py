import os
import json
import threading
import time
from typing import Dict, Optional, Any
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)


class Config:
    """Simple configuration class without Pydantic"""
    
    def __init__(self):
        # Microsoft Entra ID OAuth Configuration
        self.client_id = os.getenv("AZURE_CLIENT_ID", "")
        self.tenant_id = os.getenv("AZURE_TENANT_ID", "")
        self.authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        
        # OAuth Scopes - customize based on your backend API requirements
        #self.scopes = [
            # "openid",
            # "profile", 
            # "email",
            # "offline_access"
        #]
        
        # Add your custom API scope if you have one
        custom_scope = os.getenv("CUSTOM_API_SCOPE")
        self.scopes = [custom_scope]
        # if custom_scope:
        #     self.scopes.append(custom_scope)
        
        # Server Configuration
        self.redirect_uri = os.getenv("REDIRECT_URI", "http://localhost:8000/auth/callback")
        self.server_host = os.getenv("SERVER_HOST", "localhost")
        self.server_port = int(os.getenv("SERVER_PORT", "8000"))
        
        # Backend API Configuration
        self.backend_api_base_url = os.getenv("BACKEND_API_BASE_URL", "")
        
        # Token storage
        self.token_cache_file = os.getenv("TOKEN_CACHE_FILE", "token_cache.json")
        
    def validate(self) -> bool:
        """Validate required configuration"""
        required_fields = [
            ("client_id", self.client_id),
            ("tenant_id", self.tenant_id)
        ]
        
        for field_name, value in required_fields:
            if not value:
                logger.error(f"Missing required configuration: {field_name}")
                return False
        
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for logging/debugging"""
        return {
            "client_id": self.client_id[:8] + "..." if self.client_id else "",
            "tenant_id": self.tenant_id,
            "authority": self.authority,
            "scopes": self.scopes,
            "redirect_uri": self.redirect_uri,
            "server_host": self.server_host,
            "server_port": self.server_port,
            "backend_api_base_url": self.backend_api_base_url
        }


class TokenManager:
    """Manages OAuth tokens with thread-safe operations"""
    
    def __init__(self, cache_file: str):
        self.cache_file = cache_file
        self.tokens = {}
        self._lock = threading.Lock()
        self.load_tokens()
    
    def save_tokens(self):
        """Save tokens to file"""
        try:
            with self._lock:
                with open(self.cache_file, 'w') as f:
                    json.dump(self.tokens, f, indent=2)
            logger.info("Tokens saved to cache")
        except Exception as e:
            logger.error(f"Failed to save tokens: {e}")
    
    def load_tokens(self):
        """Load tokens from file"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r') as f:
                    self.tokens = json.load(f)
                logger.info("Tokens loaded from cache")
        except Exception as e:
            logger.error(f"Failed to load tokens: {e}")
            self.tokens = {}
    
    def set_token(self, user_id: str, token_data: Dict[str, Any]):
        """Store token for user"""
        with self._lock:
            self.tokens[user_id] = {
                **token_data,
                "timestamp": time.time()
            }
        self.save_tokens()
        logger.info(f"Token stored for user: {user_id}")
    
    def get_access_token(self, user_id: str) -> Optional[str]:
        """Get valid access token for user"""
        with self._lock:
            if user_id not in self.tokens:
                return None
            
            token_data = self.tokens[user_id]
            
            # Check if token is expired
            if self._is_token_expired(token_data):
                logger.info(f"Token expired for user: {user_id}")
                return None
            
            return token_data.get("access_token")
    
    def _is_token_expired(self, token_data: Dict[str, Any]) -> bool:
        """Check if token is expired"""
        if "expires_in" not in token_data or "timestamp" not in token_data:
            return True
        
        expires_at = token_data["timestamp"] + token_data["expires_in"]
        # Add 5 minute buffer
        return time.time() > (expires_at - 300)
    
    def refresh_token(self, user_id: str, msal_app) -> Optional[str]:
        """Refresh token using MSAL"""
        with self._lock:
            if user_id not in self.tokens:
                return None
            
            token_data = self.tokens[user_id]
            if "refresh_token" not in token_data:
                return None
        
        try:
            # Use MSAL to refresh token
            accounts = msal_app.get_accounts()
            if not accounts:
                return None
            
            result = msal_app.acquire_token_silent(
                scopes=msal_app.client_id,  # Adjust scopes as needed
                account=accounts[0]
            )
            
            if result and "access_token" in result:
                self.set_token(user_id, result)
                return result["access_token"]
            
        except Exception as e:
            logger.error(f"Failed to refresh token for user {user_id}: {e}")
        
        return None
    
    def clear_token(self, user_id: str):
        """Clear token for user"""
        with self._lock:
            if user_id in self.tokens:
                del self.tokens[user_id]
        self.save_tokens()
        logger.info(f"Token cleared for user: {user_id}")
