from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config(BaseSettings):
    """Configuration settings for the MCP server with Entra ID authentication."""
    
    # Microsoft Entra ID settings
    tenant_id: str = Field(default="", env="TENANT_ID")
    client_id: str = Field(default="", env="CLIENT_ID")
    client_secret: str = Field(default="", env="CLIENT_SECRET")  # Made optional for public clients
    
    # OAuth callback configuration - separate from MCP server port
    oauth_callback_port: int = Field(default=8080, env="OAUTH_CALLBACK_PORT")
    redirect_uri: str = Field(default="", env="REDIRECT_URI")  # Will be built dynamically
    
    # App type - determines whether to use public or confidential client
    app_type: str = Field(default="public", env="APP_TYPE")  # "public" or "confidential"
    
    # API scopes for the custom website
    api_scopes: str = Field(
        default="openid,profile,email",
        env="API_SCOPES"
    )
    
    # Backend API configuration
    backend_api_url: str = Field(default="", env="BACKEND_API_URL")
    
    # Token storage
    token_cache_path: str = Field(default="./token_cache.json", env="TOKEN_CACHE_PATH")
    
    # Server metadata
    server_name: str = Field(default="entra-auth-server", env="MCP_SERVER_NAME")
    server_version: str = Field(default="1.0.0", env="MCP_SERVER_VERSION")
    
    # HTTP Server configuration
    server_host: str = Field(default="127.0.0.1", env="MCP_SERVER_HOST")
    server_port: int = Field(default=8084, env="MCP_SERVER_PORT")
    transport_type: str = Field(default="http", env="MCP_TRANSPORT_TYPE")  # "http" or "stdio"
    
    # Microsoft Graph endpoints
    authority: str = Field(default="https://login.microsoftonline.com")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore"
    )
        
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
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

# Global config instance
config = Config()
