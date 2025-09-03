# plugin_health_checker.py
"""
Plugin health checking and validation utilities for Semantic Kernel plugins.
Provides comprehensive validation and error reporting for plugin instances.
"""

import logging
import traceback
from typing import Dict, Any, List, Optional, Tuple
from semantic_kernel_plugins.base_plugin import BasePlugin
from functions_appinsights import log_event


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
        if plugin_type in ['azure_function', 'blob_storage', 'queue_storage']:
            if 'endpoint' not in manifest:
                errors.append(f"Plugin type '{plugin_type}' requires 'endpoint' field")
            if 'auth' not in manifest:
                errors.append(f"Plugin type '{plugin_type}' requires 'auth' field")
        
        elif plugin_type in ['sql_query', 'sql_schema']:
            if 'database_type' not in manifest:
                errors.append(f"SQL plugin requires 'database_type' field")
            if not manifest.get('connection_string') and not (manifest.get('server') and manifest.get('database')):
                errors.append("SQL plugin requires either 'connection_string' or 'server' and 'database' fields")
        
        elif plugin_type == 'log_analytics':
            additional_fields = manifest.get('additionalFields', {})
            if 'workspaceId' not in additional_fields:
                errors.append("Log Analytics plugin requires 'workspaceId' in additionalFields")
        
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
                except:
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
