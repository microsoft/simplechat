"""
OpenAPI Plugin Factory

Factory class for creating OpenAPI plugins from different sources:
- Uploaded files
- URLs 
- File paths
"""

import os
import tempfile
from typing import Dict, Any, Optional
from .openapi_plugin import OpenApiPlugin


class OpenApiPluginFactory:
    """Factory for creating OpenAPI plugins from various sources."""
    
    UPLOADED_FILES_DIR = "uploaded_openapi_files"
    
    @classmethod
    def ensure_upload_directory(cls):
        """Ensure the upload directory exists."""
        if not os.path.exists(cls.UPLOADED_FILES_DIR):
            os.makedirs(cls.UPLOADED_FILES_DIR, exist_ok=True)
    
    @classmethod
    def create_from_config(cls, config: Dict[str, Any]) -> OpenApiPlugin:
        """
        Create an OpenAPI plugin from configuration.
        
        Args:
            config: Configuration dictionary containing source type and auth info
            
        Returns:
            OpenApiPlugin instance
            
        Raises:
            ValueError: If configuration is invalid
            FileNotFoundError: If specified files don't exist
        """
        # Ensure upload directory exists
        cls.ensure_upload_directory()
        
        source_type = config.get('openapi_source_type')
        base_url = config.get('base_url', '')
        auth = cls._extract_auth_config(config)
        
        if not base_url:
            raise ValueError("base_url is required")
        
        # Determine the OpenAPI spec path based on source type
        if source_type == 'file':
            openapi_spec_path = cls._get_uploaded_file_path(config)
        elif source_type == 'url':
            openapi_spec_path = cls._get_downloaded_file_path(config)
        elif source_type == 'path':
            openapi_spec_path = cls._get_local_file_path(config)
        else:
            raise ValueError(f"Invalid openapi_source_type: {source_type}")
        
        return OpenApiPlugin(
            openapi_spec_path=openapi_spec_path,
            base_url=base_url,
            auth=auth
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
        auth_config = config.get('auth', {})
        if not auth_config:
            return {}
        
        auth_type = auth_config.get('type', 'none')
        
        if auth_type == 'none':
            return {}
        
        # Return the auth config as-is since the OpenApiPlugin already handles
        # the different auth types
        return auth_config
