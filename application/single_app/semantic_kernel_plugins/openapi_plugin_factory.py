"""
OpenAPI Plugin Factory

Factory class for creating OpenAPI plugins from different sources:
- Stored content in user settings (preferred)
- Uploaded files (deprecated)
- URLs (deprecated)
- File paths (deprecated)
"""

import os
import tempfile
from typing import Dict, Any, Optional
from .openapi_plugin import OpenApiPlugin


class OpenApiPluginFactory:
    """Factory for creating OpenAPI plugins from various sources."""
    
    # Legacy directory for backward compatibility
    UPLOADED_FILES_DIR = "uploaded_openapi_files"
    
    @classmethod
    def create_from_config(cls, config: Dict[str, Any]) -> OpenApiPlugin:
        """
        Create an OpenAPI plugin from configuration.
        
        Args:
            config: Configuration dictionary containing source and auth info
            
        Returns:
            OpenApiPlugin instance
            
        Raises:
            ValueError: If configuration is invalid
        """
        # Try both 'base_url' and 'endpoint' fields for backward compatibility
        base_url = config.get('base_url') or config.get('endpoint', '')
        auth = cls._extract_auth_config(config)
        
        if not base_url:
            raise ValueError("base_url is required")
        
        # Check if we have OpenAPI spec content directly in the config
        openapi_spec_content = config.get('openapi_spec_content')
        
        # Also check in additionalFields for compatibility
        if not openapi_spec_content and 'additionalFields' in config:
            openapi_spec_content = config['additionalFields'].get('openapi_spec_content')
        
        if openapi_spec_content:
            return OpenApiPlugin(
                base_url=base_url,
                auth=auth,
                openapi_spec_content=openapi_spec_content
            )
        
        # Fall back to legacy file-based approach for backward compatibility
        source_type = config.get('openapi_source_type')
        
        if source_type == 'content':
            # This should be handled above, but just in case
            raise ValueError("openapi_spec_content is required for content source type")
        elif source_type == 'file':
            openapi_spec_path = cls._get_uploaded_file_path(config)
        elif source_type == 'url':
            openapi_spec_path = cls._get_downloaded_file_path(config)
        elif source_type == 'path':
            openapi_spec_path = cls._get_local_file_path(config)
        else:
            raise ValueError(f"Invalid openapi_source_type: {source_type}")
        
        return OpenApiPlugin(
            base_url=base_url,
            auth=auth,
            openapi_spec_path=openapi_spec_path
        )
    
    @classmethod
    def _get_uploaded_file_path(cls, config: Dict[str, Any]) -> str:
        """Get file path for uploaded OpenAPI spec."""
        file_id = config.get('openapi_file_id')
        if not file_id:
            raise ValueError("openapi_file_id is required for file source type")
        
        # Construct path to uploaded file
        file_path = os.path.join(cls.UPLOADED_FILES_DIR, f"{file_id}.yaml")
        if not os.path.exists(file_path):
            # Try JSON extension
            file_path = os.path.join(cls.UPLOADED_FILES_DIR, f"{file_id}.json")
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Uploaded file not found: {file_id}")
        
        return file_path
    
    @classmethod
    def _get_downloaded_file_path(cls, config: Dict[str, Any]) -> str:
        """Get file path for downloaded OpenAPI spec from URL."""
        file_id = config.get('openapi_file_id')
        if not file_id:
            raise ValueError("openapi_file_id is required for URL source type")
        
        # Construct path to downloaded file
        file_path = os.path.join(cls.UPLOADED_FILES_DIR, f"{file_id}.yaml")
        if not os.path.exists(file_path):
            # Try JSON extension
            file_path = os.path.join(cls.UPLOADED_FILES_DIR, f"{file_id}.json")
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Downloaded file not found: {file_id}")
        
        return file_path
    
    @classmethod
    def _get_local_file_path(cls, config: Dict[str, Any]) -> str:
        """Get file path for local OpenAPI spec."""
        file_path = config.get('openapi_spec_path')
        if not file_path:
            raise ValueError("openapi_spec_path is required for path source type")
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"OpenAPI specification file not found: {file_path}")
        
        return file_path
    
    @classmethod
    def _extract_auth_config(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """Extract authentication configuration from plugin config."""
        from functions_debug import debug_print
        
        auth_config = config.get('auth', {})
        debug_print(f"[Factory] Initial auth_config: {auth_config}")
        if not auth_config:
            return {}
        
        auth_type = auth_config.get('type', 'none')
        debug_print(f"[Factory] auth_type: {auth_type}")
        
        if auth_type == 'none':
            return {}
        
        # Check if this is basic auth stored in the 'key' field format
        # Simple Chat stores basic auth as: auth.type='key', auth.key='username:password', additionalFields.auth_method='basic'
        additional_fields = config.get('additionalFields', {})
        auth_method = additional_fields.get('auth_method', '')
        debug_print(f"[Factory] additionalFields.auth_method: {auth_method}")
        
        if auth_type == 'key' and auth_method == 'basic':
            # Extract username and password from the combined key
            key = auth_config.get('key', '')
            debug_print(f"[Factory] Applying basic auth transformation")
            if ':' in key:
                username, password = key.split(':', 1)
                return {
                    'type': 'basic',
                    'username': username,
                    'password': password
                }
            else:
                # Malformed basic auth key
                return {}
        
        # For bearer tokens stored as 'key' type
        if auth_type == 'key' and auth_method == 'bearer':
            token = auth_config.get('key', '')
            debug_print(
                f"[Factory] Applying bearer auth transformation - "
                f"token_present={bool(token)}, token_length={len(token)}"
            )
            return {
                'type': 'bearer',
                'token': token
            }
        
        # For OAuth2 stored as 'key' type
        if auth_type == 'key' and auth_method == 'oauth2':
            debug_print(f"[Factory] Applying OAuth2 auth transformation")
            return {
                'type': 'bearer',  # OAuth2 tokens are typically bearer tokens
                'token': auth_config.get('key', '')
            }
        
        debug_print(f"[Factory] Returning auth as-is: {auth_config}")
        # Return the auth config as-is for other auth types
        return auth_config
