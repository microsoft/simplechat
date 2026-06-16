# plugin_health_checker.py
"""
Plugin health checking and validation utilities for Semantic Kernel plugins.
Provides comprehensive validation and error reporting for plugin instances.
"""

import logging
import traceback
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse
from semantic_kernel_plugins.base_plugin import BasePlugin
from functions_appinsights import log_event
from functions_azure_maps import AZURE_MAPS_DEFAULT_ENDPOINT, AZURE_MAPS_PLUGIN_TYPE
from functions_blob_storage_operations import BLOB_STORAGE_PLUGIN_TYPE
from functions_databricks_operations import (
    DATABRICKS_CLOUD_AZURE_COMMERCIAL,
    DATABRICKS_LEGACY_TABLE_PLUGIN_TYPE,
    DATABRICKS_PLUGIN_TYPE,
    normalize_databricks_additional_fields,
)
from functions_tableau_operations import (
    TABLEAU_AUTH_METHOD_PAT,
    TABLEAU_AUTH_METHOD_USERNAME_PASSWORD,
    TABLEAU_DEFAULT_MAX_RESULTS,
    TABLEAU_DEFAULT_PAGE_SIZE,
    TABLEAU_DEFAULT_TIMEOUT,
    TABLEAU_MAX_MAX_RESULTS,
    TABLEAU_MAX_PAGE_SIZE,
    TABLEAU_MAX_TIMEOUT,
    TABLEAU_MIN_MAX_RESULTS,
    TABLEAU_MIN_PAGE_SIZE,
    TABLEAU_MIN_TIMEOUT,
    TABLEAU_PLUGIN_TYPE,
    normalize_tableau_additional_fields,
    normalize_tableau_server_url,
)
from functions_mcp_operations import (
    MCP_MAX_TIMEOUT_SECONDS,
    MCP_PLUGIN_TYPE,
    MCP_REMOTE_TRANSPORTS,
    MCP_SUPPORTED_AUTH_METHODS,
    MCP_SUPPORTED_TRANSPORTS,
    normalize_mcp_additional_fields,
    normalize_mcp_auth_method,
)
from functions_simplechat_operations import SIMPLECHAT_DEFAULT_ENDPOINT


class PluginHealthChecker:
    """Utility class for checking plugin health and validity."""
    
    @staticmethod
    def validate_plugin_manifest(manifest: Dict[str, Any], plugin_type: str) -> Tuple[bool, List[str]]:
        """
        Validate a plugin manifest against basic requirements.
        
        Args:
            manifest: The plugin manifest to validate
            plugin_type: The type of plugin being validated
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        # Basic manifest validation
        if not isinstance(manifest, dict):
            errors.append("Manifest must be a dictionary")
            return False, errors
        
        # Required fields
        required_fields = ['name', 'type']
        for field in required_fields:
            if field not in manifest:
                errors.append(f"Missing required field: {field}")
        
        # Validate specific plugin types
        if plugin_type in ['azure_function', 'queue_storage']:
            if 'endpoint' not in manifest:
                errors.append(f"Plugin type '{plugin_type}' requires 'endpoint' field")
            if 'auth' not in manifest:
                errors.append(f"Plugin type '{plugin_type}' requires 'auth' field")

        elif plugin_type == BLOB_STORAGE_PLUGIN_TYPE:
            additional_fields = manifest.get('additionalFields', {})
            if not isinstance(additional_fields, dict):
                additional_fields = {}

            auth = manifest.get('auth', {}) if isinstance(manifest.get('auth'), dict) else {}
            auth_type = (auth.get('type') or '').strip().lower()
            endpoint = (manifest.get('endpoint') or '').strip()
            container_name = str(
                manifest.get('container_name') or additional_fields.get('container_name') or ''
            ).strip()

            if not auth:
                errors.append("Blob storage plugin requires 'auth' field")
            if not container_name:
                errors.append("Blob storage plugin requires 'container_name' in additionalFields")
            if auth_type not in {'connection_string', 'identity', 'key'}:
                errors.append("Blob storage plugin requires auth.type values 'connection_string', 'identity', or 'key'")
            if auth_type == 'connection_string' and not auth.get('key'):
                errors.append("Blob storage plugin requires auth.key when auth.type='connection_string'")
            if auth_type == 'key':
                if not endpoint:
                    errors.append("Blob storage plugin requires an 'endpoint' field when auth.type='key'")
                if not auth.get('key'):
                    errors.append("Blob storage plugin requires auth.key when auth.type='key'")
            if auth_type == 'identity' and not endpoint:
                errors.append("Blob storage plugin requires an 'endpoint' field when auth.type='identity'")

        elif plugin_type in {DATABRICKS_PLUGIN_TYPE, DATABRICKS_LEGACY_TABLE_PLUGIN_TYPE}:
            auth = manifest.get('auth', {}) if isinstance(manifest.get('auth'), dict) else {}
            auth_type = str(auth.get('type') or 'key').strip()
            additional_fields = normalize_databricks_additional_fields(
                manifest.get('additionalFields', {}),
                auth_type=auth_type,
            )
            endpoint = str(manifest.get('endpoint') or additional_fields.get('workspace_url') or '').strip()
            parsed_endpoint = urlparse(endpoint)
            identity_id = str(manifest.get('identity_id') or '').strip()

            if additional_fields.get('cloud') != DATABRICKS_CLOUD_AZURE_COMMERCIAL:
                errors.append("Databricks plugin currently supports only additionalFields.cloud='azure_commercial'")
            if parsed_endpoint.scheme != 'https' or not parsed_endpoint.netloc:
                errors.append("Databricks plugin requires an HTTPS workspace endpoint")
            if not additional_fields.get('warehouse_id'):
                errors.append("Databricks plugin requires additionalFields.warehouse_id")
            if auth_type not in {'key', 'identity', 'servicePrincipal'}:
                errors.append("Databricks plugin supports auth.type values 'key', 'identity', or 'servicePrincipal'")
            if auth_type == 'key' and not auth.get('key'):
                errors.append("Databricks plugin requires auth.key for PAT or bearer-token authentication")
            if auth_type == 'identity' and not auth.get('identity') and not identity_id:
                errors.append("Databricks plugin requires auth.identity for managed identity or reusable identity authentication")
            if auth_type == 'servicePrincipal':
                if not auth.get('identity') or not auth.get('key') or not auth.get('tenantId'):
                    errors.append("Databricks service principal auth requires auth.identity, auth.key, and auth.tenantId")

        elif plugin_type == TABLEAU_PLUGIN_TYPE:
            auth = manifest.get('auth', {}) if isinstance(manifest.get('auth'), dict) else {}
            auth_type = str(auth.get('type') or 'key').strip()
            raw_additional_fields = manifest.get('additionalFields', {})
            if not isinstance(raw_additional_fields, dict):
                raw_additional_fields = {}
            additional_fields = normalize_tableau_additional_fields(raw_additional_fields, auth_type=auth_type)
            endpoint = normalize_tableau_server_url(
                manifest.get('endpoint') or additional_fields.get('server_url') or ''
            )
            parsed_endpoint = urlparse(endpoint)
            identity_id = str(manifest.get('identity_id') or '').strip()
            raw_auth_method = str(raw_additional_fields.get('auth_method') or '').strip().lower()
            auth_method = additional_fields.get('auth_method')

            if parsed_endpoint.scheme != 'https' or not parsed_endpoint.netloc:
                errors.append("Tableau plugin requires an HTTPS Tableau Server or Tableau Cloud endpoint")
            if auth_type not in {'key', 'username_password', 'identity'}:
                errors.append("Tableau plugin supports auth.type values 'key', 'username_password', or 'identity'")
            if raw_auth_method and raw_auth_method not in {TABLEAU_AUTH_METHOD_PAT, TABLEAU_AUTH_METHOD_USERNAME_PASSWORD}:
                errors.append("Tableau plugin supports additionalFields.auth_method values 'personal_access_token' or 'username_password'")
            if auth_method == TABLEAU_AUTH_METHOD_PAT:
                if auth_type == 'key' and not auth.get('key'):
                    errors.append("Tableau personal access token auth requires auth.key")
                if auth_type == 'key' and not (auth.get('identity') or additional_fields.get('pat_name')):
                    errors.append("Tableau personal access token auth requires auth.identity or additionalFields.pat_name")
                if auth_type == 'identity' and not auth.get('identity') and not identity_id:
                    errors.append("Tableau reusable identity auth requires auth.identity or identity_id")
                if auth_type == 'identity' and additional_fields.get('identity_auth_type') == 'api_key' and not additional_fields.get('pat_name'):
                    errors.append("Tableau API key reusable identity auth requires additionalFields.pat_name")
            elif auth_method == TABLEAU_AUTH_METHOD_USERNAME_PASSWORD:
                if auth_type == 'username_password' and (not auth.get('identity') or not auth.get('key')):
                    errors.append("Tableau username/password auth requires auth.identity and auth.key")
                if auth_type == 'identity' and not auth.get('identity') and not identity_id:
                    errors.append("Tableau reusable username/password identity auth requires auth.identity or identity_id")
                if auth_type == 'key':
                    errors.append("Tableau username/password auth cannot use auth.type='key'")

            range_fields = {
                'page_size': (TABLEAU_DEFAULT_PAGE_SIZE, TABLEAU_MIN_PAGE_SIZE, TABLEAU_MAX_PAGE_SIZE),
                'max_results': (TABLEAU_DEFAULT_MAX_RESULTS, TABLEAU_MIN_MAX_RESULTS, TABLEAU_MAX_MAX_RESULTS),
                'timeout': (TABLEAU_DEFAULT_TIMEOUT, TABLEAU_MIN_TIMEOUT, TABLEAU_MAX_TIMEOUT),
            }
            for field_name, (_default, minimum, maximum) in range_fields.items():
                raw_value = raw_additional_fields.get(field_name)
                if raw_value in [None, '']:
                    continue
                try:
                    parsed_value = int(raw_value)
                except (TypeError, ValueError):
                    errors.append(f"Tableau additionalFields.{field_name} must be an integer")
                    continue
                if parsed_value < minimum or parsed_value > maximum:
                    errors.append(f"Tableau additionalFields.{field_name} must be between {minimum} and {maximum}")
        
        elif plugin_type in ['sql_query', 'sql_schema']:
            additional_fields = manifest.get('additionalFields', {})
            if not isinstance(additional_fields, dict):
                additional_fields = {}

            database_type = manifest.get('database_type') or additional_fields.get('database_type')
            connection_string = manifest.get('connection_string') or additional_fields.get('connection_string')
            server = manifest.get('server') or additional_fields.get('server')
            database = manifest.get('database') or additional_fields.get('database')
            identity_uses_connection_string = (
                bool(manifest.get('identity_id'))
                and additional_fields.get('identity_auth_type') == 'connection_string'
            )

            if not database_type:
                errors.append(f"SQL plugin requires 'database_type' field")
            if not connection_string and not identity_uses_connection_string and not (server and database):
                errors.append("SQL plugin requires either 'connection_string' or 'server' and 'database' fields")

        elif plugin_type == 'cosmos_query':
            additional_fields = manifest.get('additionalFields', {})
            if not isinstance(additional_fields, dict):
                additional_fields = {}

            endpoint = manifest.get('endpoint')
            database_name = manifest.get('database_name') or additional_fields.get('database_name')
            container_name = manifest.get('container_name') or additional_fields.get('container_name')
            partition_key_path = manifest.get('partition_key_path') or additional_fields.get('partition_key_path')
            auth = manifest.get('auth', {}) if isinstance(manifest.get('auth'), dict) else {}
            auth_type = (auth.get('type') or 'identity').strip()

            if not endpoint:
                errors.append("Cosmos plugin requires an 'endpoint' field")
            if not database_name:
                errors.append("Cosmos plugin requires 'database_name' in additionalFields")
            if not container_name:
                errors.append("Cosmos plugin requires 'container_name' in additionalFields")
            if not partition_key_path:
                errors.append("Cosmos plugin requires 'partition_key_path' in additionalFields")
            if auth_type not in {'identity', 'key'}:
                errors.append("Cosmos plugin only supports auth.type values 'identity' and 'key'")
            if auth_type == 'key' and not auth.get('key'):
                errors.append("Cosmos plugin requires auth.key when auth.type='key'")
        
        elif plugin_type == 'log_analytics':
            additional_fields = manifest.get('additionalFields', {})
            if 'workspaceId' not in additional_fields:
                errors.append("Log Analytics plugin requires 'workspaceId' in additionalFields")

        elif plugin_type == 'simplechat':
            endpoint = manifest.get('endpoint')
            auth = manifest.get('auth', {}) if isinstance(manifest.get('auth'), dict) else {}
            if not endpoint:
                errors.append(f"SimpleChat plugin requires an 'endpoint' field (use {SIMPLECHAT_DEFAULT_ENDPOINT})")
            if auth.get('type') != 'user':
                errors.append("SimpleChat plugin requires auth.type='user'")

        elif plugin_type == MCP_PLUGIN_TYPE:
            additional_fields = normalize_mcp_additional_fields(manifest.get('additionalFields', {}))
            transport = additional_fields.get('transport')
            endpoint = str(manifest.get('endpoint') or '').strip()
            auth = manifest.get('auth', {}) if isinstance(manifest.get('auth'), dict) else {}
            auth_type = str(auth.get('type') or 'NoAuth').strip()
            auth_method = normalize_mcp_auth_method(additional_fields.get('auth_method'))

            if transport not in MCP_SUPPORTED_TRANSPORTS:
                errors.append("MCP plugin requires additionalFields.transport to be streamable_http, sse, websocket, or stdio")

            if transport in MCP_REMOTE_TRANSPORTS:
                if not endpoint:
                    errors.append("MCP plugin requires an endpoint for remote transports")
                else:
                    parsed_endpoint = urlparse(endpoint)
                    allowed_schemes = {'ws', 'wss'} if transport == 'websocket' else {'http', 'https'}
                    if parsed_endpoint.scheme not in allowed_schemes or not parsed_endpoint.netloc:
                        errors.append(f"MCP {transport} transport requires a valid {'/'.join(sorted(allowed_schemes))} endpoint")
            elif transport == 'stdio':
                command = str(additional_fields.get('command') or '').strip()
                if not command:
                    errors.append("MCP stdio transport requires additionalFields.command")

            if auth_type not in {'NoAuth', 'key', 'identity'}:
                errors.append("MCP plugin supports auth.type values 'NoAuth', 'key', or 'identity'")
            if auth_method not in MCP_SUPPORTED_AUTH_METHODS:
                errors.append("MCP plugin requires a supported additionalFields.auth_method")
            if auth_method in {'bearer', 'api_key', 'basic'} and auth_type != 'key':
                errors.append("MCP bearer, api_key, and basic auth methods require auth.type='key'")
            if auth_method in {'bearer', 'api_key', 'basic'} and not auth.get('key'):
                errors.append("MCP credential-based auth methods require auth.key")
            if auth_method == 'api_key' and not str(additional_fields.get('api_key_header_name') or '').strip():
                errors.append("MCP api_key auth requires additionalFields.api_key_header_name")
            if auth_method == 'basic' and not auth.get('identity'):
                errors.append("MCP basic auth requires auth.identity for the username")

            for timeout_field in ('request_timeout', 'connect_timeout', 'sse_read_timeout'):
                timeout_value = additional_fields.get(timeout_field)
                if not isinstance(timeout_value, int) or timeout_value < 1 or timeout_value > MCP_MAX_TIMEOUT_SECONDS:
                    errors.append(f"MCP {timeout_field} must be between 1 and {MCP_MAX_TIMEOUT_SECONDS} seconds")

            allowed_tool_names = additional_fields.get('allowed_tool_names')
            if not isinstance(allowed_tool_names, list):
                errors.append("MCP allowed_tool_names must be an array when provided")

            mcp_tools = additional_fields.get('mcp_tools')
            if not isinstance(mcp_tools, list):
                errors.append("MCP mcp_tools must be an array when provided")
            else:
                for tool in mcp_tools:
                    if not isinstance(tool, dict):
                        errors.append("Each MCP tool metadata entry must be an object")
                        continue
                    if not str(tool.get('original_name') or '').strip():
                        errors.append("Each MCP tool metadata entry requires original_name")
                    if not str(tool.get('function_name') or '').strip():
                        errors.append("Each MCP tool metadata entry requires function_name")

        elif plugin_type == AZURE_MAPS_PLUGIN_TYPE:
            endpoint = manifest.get('endpoint')
            auth = manifest.get('auth', {}) if isinstance(manifest.get('auth'), dict) else {}
            if not endpoint:
                errors.append(f"Azure Maps plugin requires an 'endpoint' field (use {AZURE_MAPS_DEFAULT_ENDPOINT})")
            if auth.get('type') != 'key':
                errors.append("Azure Maps plugin requires auth.type='key'")
            if not auth.get('key'):
                errors.append("Azure Maps plugin requires auth.key with an Azure Maps subscription key")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def check_plugin_health(plugin_instance: BasePlugin, plugin_name: str) -> Dict[str, Any]:
        """
        Perform comprehensive health check on a plugin instance.
        
        Args:
            plugin_instance: The plugin instance to check
            plugin_name: Name of the plugin for logging
            
        Returns:
            Health check results dictionary
        """
        health_report = {
            'plugin_name': plugin_name,
            'is_healthy': True,
            'errors': [],
            'warnings': [],
            'info': {},
            'timestamp': None
        }
        
        try:
            # Check if plugin has required attributes
            if not hasattr(plugin_instance, 'metadata'):
                health_report['errors'].append("Plugin missing 'metadata' property")
                health_report['is_healthy'] = False
            else:
                try:
                    metadata = plugin_instance.metadata
                    health_report['info']['metadata'] = metadata
                except Exception as e:
                    health_report['errors'].append(f"Failed to access metadata: {str(e)}")
                    health_report['is_healthy'] = False
            
            # Check display_name property
            if hasattr(plugin_instance, 'display_name'):
                try:
                    display_name = plugin_instance.display_name
                    health_report['info']['display_name'] = display_name
                except Exception as e:
                    health_report['warnings'].append(f"Failed to access display_name: {str(e)}")
            
            # Check get_functions method
            if hasattr(plugin_instance, 'get_functions'):
                try:
                    functions = plugin_instance.get_functions()
                    health_report['info']['function_count'] = len(functions) if functions else 0
                    health_report['info']['functions'] = functions if functions else []
                except Exception as e:
                    health_report['warnings'].append(f"get_functions() method failed: {str(e)}")
            
            # Check for kernel_function decorated methods
            kernel_functions = []
            for attr_name in dir(plugin_instance):
                try:
                    attr = getattr(plugin_instance, attr_name)
                    if hasattr(attr, '__kernel_function__') or (
                        hasattr(attr, '__annotations__') and 
                        getattr(attr, '__module__', '').startswith('semantic_kernel')
                    ):
                        kernel_functions.append(attr_name)
                except Exception as ex:
                    continue
            
            health_report['info']['kernel_functions'] = kernel_functions
            health_report['info']['kernel_function_count'] = len(kernel_functions)
            
            # Validate plugin instance type
            if not isinstance(plugin_instance, BasePlugin):
                health_report['warnings'].append("Plugin does not inherit from BasePlugin")
            
        except Exception as e:
            health_report['errors'].append(f"Health check failed with exception: {str(e)}")
            health_report['is_healthy'] = False
            
        return health_report
    
    @staticmethod
    def log_plugin_health(health_report: Dict[str, Any]):
        """Log plugin health report to application insights."""
        plugin_name = health_report.get('plugin_name', 'unknown')
        
        if health_report['is_healthy']:
            log_event(
                f"[Plugin Health] Plugin {plugin_name} is healthy",
                extra=health_report,
                level=logging.INFO
            )
        else:
            log_event(
                f"[Plugin Health] Plugin {plugin_name} has health issues",
                extra=health_report,
                level=logging.WARNING
            )
        
        # Log individual errors
        for error in health_report.get('errors', []):
            log_event(
                f"[Plugin Health] Error in {plugin_name}: {error}",
                extra={'plugin_name': plugin_name, 'error': error},
                level=logging.ERROR
            )
    
    @staticmethod
    def create_plugin_safely(plugin_class, manifest: Dict[str, Any], plugin_name: str) -> Tuple[Optional[BasePlugin], List[str]]:
        """
        Safely create a plugin instance with comprehensive error handling.
        
        Args:
            plugin_class: The plugin class to instantiate
            manifest: The plugin manifest
            plugin_name: Name of the plugin for logging
            
        Returns:
            Tuple of (plugin_instance_or_none, list_of_errors)
        """
        errors = []
        plugin_instance = None
        
        try:
            # Try manifest-based instantiation first
            try:
                plugin_instance = plugin_class(manifest)
                log_event(f"[Plugin Creation] Successfully created {plugin_name} with manifest", 
                         level=logging.DEBUG)
            except (TypeError, ValueError, KeyError) as e:
                errors.append(f"Manifest instantiation failed: {str(e)}")
                # Try empty dict
                try:
                    plugin_instance = plugin_class({})
                    log_event(f"[Plugin Creation] Created {plugin_name} with empty manifest", 
                             level=logging.INFO)
                except (TypeError, ValueError) as e2:
                    errors.append(f"Empty dict instantiation failed: {str(e2)}")
                    # Try no parameters
                    try:
                        plugin_instance = plugin_class()
                        log_event(f"[Plugin Creation] Created {plugin_name} with no parameters", 
                                 level=logging.INFO)
                    except Exception as e3:
                        errors.append(f"No-parameter instantiation failed: {str(e3)}")
            except Exception as e:
                errors.append(f"Unexpected error during instantiation: {str(e)}")
        
        except Exception as e:
            errors.append(f"Critical error in plugin creation: {str(e)}")
            log_event(f"[Plugin Creation] Critical error creating {plugin_name}: {str(e)}", 
                     level=logging.ERROR, exceptionTraceback=True)
        
        # If we got a plugin instance, run health check
        if plugin_instance:
            health_report = PluginHealthChecker.check_plugin_health(plugin_instance, plugin_name)
            PluginHealthChecker.log_plugin_health(health_report)
            
            if not health_report['is_healthy']:
                errors.extend([f"Health check: {error}" for error in health_report['errors']])
        
        return plugin_instance, errors


class PluginErrorRecovery:
    """Utilities for recovering from plugin errors and implementing fallbacks."""
    
    @staticmethod
    def create_fallback_plugin(plugin_name: str, plugin_type: str) -> Optional[BasePlugin]:
        """
        Create a minimal fallback plugin that can be used when the real plugin fails.
        
        Args:
            plugin_name: Name of the failed plugin
            plugin_type: Type of the failed plugin
            
        Returns:
            A minimal fallback plugin or None
        """
        try:
            class FallbackPlugin(BasePlugin):
                def __init__(self, manifest=None):
                    self.manifest = manifest or {}
                    self._metadata = {
                        'name': plugin_name,
                        'type': plugin_type,
                        'description': f'Fallback plugin for {plugin_name}',
                        'status': 'fallback',
                        'methods': []
                    }
                
                @property
                def metadata(self):
                    return self._metadata
                
                @property
                def display_name(self):
                    return f"{plugin_name} (Fallback)"
                
                def get_functions(self):
                    return []
            
            return FallbackPlugin()
        
        except Exception as e:
            log_event(f"[Plugin Recovery] Failed to create fallback plugin for {plugin_name}: {str(e)}", 
                     level=logging.ERROR)
            return None
    
    @staticmethod
    def attempt_plugin_repair(plugin_instance: BasePlugin, errors: List[str]) -> Tuple[BasePlugin, bool]:
        """
        Attempt to repair a plugin that has issues.
        
        Args:
            plugin_instance: The plugin with issues
            errors: List of errors found
            
        Returns:
            Tuple of (possibly_repaired_plugin, was_repaired)
        """
        was_repaired = False
        
        try:
            # Try to fix missing metadata
            if not hasattr(plugin_instance, 'metadata') or not plugin_instance.metadata:
                if hasattr(plugin_instance, '_metadata'):
                    # Try to restore from _metadata
                    plugin_instance.metadata = plugin_instance._metadata
                    was_repaired = True
                else:
                    # Create minimal metadata
                    plugin_instance._metadata = {
                        'name': getattr(plugin_instance, '__class__', {}).get('__name__', 'unknown'),
                        'type': 'unknown',
                        'description': 'Auto-generated metadata',
                        'methods': []
                    }
                    plugin_instance.metadata = plugin_instance._metadata
                    was_repaired = True
        
        except Exception as e:
            log_event(f"[Plugin Repair] Failed to repair plugin: {str(e)}", level=logging.WARNING)
        
        return plugin_instance, was_repaired
