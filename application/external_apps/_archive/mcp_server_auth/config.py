import os
from typing import List
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class ConfigError(Exception):
    """Exception raised for configuration errors."""
    pass

def get_required_env(var_name: str) -> str:
    """Get required environment variable or raise ConfigError."""
    value = os.getenv(var_name)
    if value is None:
        raise ConfigError(f"Required environment variable '{var_name}' is not set in .env file")
    return value

def get_required_env_int(var_name: str) -> int:
    """Get required environment variable as integer or raise ConfigError."""
    value = get_required_env(var_name)
    try:
        return int(value)
    except ValueError:
        raise ConfigError(f"Environment variable '{var_name}' must be a valid integer, got: '{value}'")

class Config:
    """Configuration settings for the MCP server with Entra ID authentication."""
    
    def __init__(self):
        # Microsoft Entra ID settings - all required
        self.tenant_id = get_required_env("TENANT_ID")
        self.client_id = get_required_env("CLIENT_ID")
        self.client_secret = get_required_env("CLIENT_SECRET")
        
        # OAuth callback configuration - required
        self.oauth_callback_port = get_required_env_int("OAUTH_CALLBACK_PORT")
        self.redirect_uri = get_required_env("REDIRECT_URI")
        
        # App type - required
        self.app_type = get_required_env("APP_TYPE")  # "public" or "confidential"
        
        # API scopes for the custom website - required
        self.api_scopes = get_required_env("API_SCOPES")
        
        # Backend API configuration - required
        self.backend_api_url = get_required_env("BACKEND_API_URL")
        
        # Token storage - required
        self.token_cache_path = get_required_env("TOKEN_CACHE_PATH")
        
        # Server metadata - required
        self.server_name = get_required_env("MCP_SERVER_NAME")
        self.server_version = get_required_env("MCP_SERVER_VERSION")
        
        # HTTP Server configuration - required
        self.server_host = get_required_env("MCP_SERVER_HOST")
        self.server_port = get_required_env_int("MCP_SERVER_PORT")
        self.transport_type = get_required_env("MCP_TRANSPORT_TYPE")  # "http" or "stdio"
        
        # Microsoft Graph endpoints
        self.authority = "https://login.microsoftonline.com"
        
        # Ensure OAuth callback port is different from MCP server port
        if self.oauth_callback_port == self.server_port:
            self.oauth_callback_port = self.server_port + 1
            print(f"Warning: OAuth callback port adjusted to {self.oauth_callback_port} to avoid conflict with MCP server port {self.server_port}")
    
    @property
    def redirect_uri_computed(self) -> str:
        """Get the redirect URI dynamically built from the OAuth callback port."""
        if self.redirect_uri:
            return self.redirect_uri
        return f"http://localhost:{self.oauth_callback_port}/auth/callback"
    
    @property
    def authority_url(self) -> str:
        """Get the full authority URL for the tenant."""
        return f"{self.authority}/{self.tenant_id}"
    
    @property
    def api_scopes_list(self) -> List[str]:
        """Get API scopes as a list."""
        return [scope.strip() for scope in self.api_scopes.split(",")]
    
    def validate_config(self) -> bool:
        """Validate that all required configuration is present."""
        required_fields = [
            self.tenant_id,
            self.client_id,
            self.backend_api_url
        ]
        
        # Check that required fields are not empty
        valid_fields = [field for field in required_fields if field and field.strip()]
        
        # For confidential clients, client_secret is also required
        if self.app_type == "confidential" and (not self.client_secret or not self.client_secret.strip()):
            return False
            
        return len(valid_fields) == len(required_fields)
    
    def __str__(self) -> str:
        """String representation of config (without sensitive data)."""
        return f"Config(server_name='{self.server_name}', server_port={self.server_port}, tenant_id='{self.tenant_id[:8]}...', app_type='{self.app_type}')"
    
    def __repr__(self) -> str:
        """Detailed representation of config (without sensitive data)."""
        return self.__str__()

# Global config instance
config = Config()
