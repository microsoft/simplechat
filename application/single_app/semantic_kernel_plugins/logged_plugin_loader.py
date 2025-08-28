# logged_plugin_loader.py
"""
Enhanced plugin loader that automatically wraps plugins with invocation logging.
"""

import importlib
import inspect
import logging
from typing import Dict, Any, List, Optional, Type
from semantic_kernel import Kernel
from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_plugin import KernelPlugin
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import (
    get_plugin_logger, 
    plugin_function_logger, 
    auto_wrap_plugin_functions
)
from functions_appinsights import log_event


class LoggedPluginLoader:
    """Enhanced plugin loader that automatically adds invocation logging."""
    
    def __init__(self, kernel: Kernel):
        self.kernel = kernel
        self.logger = logging.getLogger(__name__)
        self.plugin_logger = get_plugin_logger()
    
    def load_plugin_from_manifest(self, manifest: Dict[str, Any], 
                                 user_id: Optional[str] = None) -> bool:
        """
        Load a plugin from a manifest with automatic invocation logging.
        
        Args:
            manifest: Plugin manifest containing name, type, and configuration
            user_id: Optional user ID for per-user plugin loading
            
        Returns:
            bool: True if plugin loaded successfully, False otherwise
        """
        plugin_name = manifest.get('name')
        plugin_type = manifest.get('type')
        
        # Debug logging
        log_event(f"[Logged Plugin Loader] Starting to load plugin: {plugin_name} (type: {plugin_type})")
        
        if not plugin_name:
            self.logger.error("Plugin manifest missing required 'name' field")
            return False
        
        try:
            # Load the plugin instance
            plugin_instance = self._create_plugin_instance(manifest)
            if not plugin_instance:
                return False
            
            # Enable logging if the plugin supports it
            if hasattr(plugin_instance, 'enable_invocation_logging'):
                plugin_instance.enable_invocation_logging(True)
            
            # Auto-wrap plugin functions with logging
            if isinstance(plugin_instance, BasePlugin):
                print(f"[Logged Plugin Loader] Wrapping functions for BasePlugin: {plugin_name}")
                log_event(f"[Logged Plugin Loader] Wrapping functions for BasePlugin: {plugin_name}")
                self._wrap_plugin_functions(plugin_instance, plugin_name)
            else:
                print(f"[Logged Plugin Loader] Plugin {plugin_name} is not a BasePlugin: {type(plugin_instance)}")
                log_event(f"[Logged Plugin Loader] Plugin {plugin_name} is not a BasePlugin: {type(plugin_instance)}")
            
            # Register the plugin with the kernel
            self._register_plugin_with_kernel(plugin_instance, plugin_name)
            
            log_event(
                f"[Plugin Loader] Successfully loaded plugin: {plugin_name}",
                extra={
                    "plugin_name": plugin_name,
                    "plugin_type": plugin_type,
                    "user_id": user_id,
                    "logging_enabled": True
                },
                level=logging.INFO
            )
            
            return True
            
        except Exception as e:
            log_event(
                f"[Plugin Loader] Failed to load plugin: {plugin_name}",
                extra={
                    "plugin_name": plugin_name,
                    "plugin_type": plugin_type,
                    "error": str(e),
                    "user_id": user_id
                },
                level=logging.ERROR,
                exceptionTraceback=True
            )
            return False
    
    def _create_plugin_instance(self, manifest: Dict[str, Any]):
        """Create a plugin instance from manifest."""
        plugin_name = manifest.get('name')
        plugin_type = manifest.get('type')
        
        # Handle different plugin types
        if plugin_type == 'openapi':
            return self._create_openapi_plugin(manifest)
        elif plugin_type == 'python':
            return self._create_python_plugin(manifest)
        elif plugin_type == 'custom':
            return self._create_custom_plugin(manifest)
        elif plugin_type in ['sql_schema', 'sql_query']:
            return self._create_sql_plugin(manifest)
        else:
            self.logger.warning(f"Unknown plugin type: {plugin_type} for plugin: {plugin_name}")
            return None
    
    def _create_openapi_plugin(self, manifest: Dict[str, Any]):
        """Create an OpenAPI plugin instance."""
        plugin_name = manifest.get('name')
        print(f"[Logged Plugin Loader] Attempting to create OpenAPI plugin: {plugin_name}")
        
        try:
            from semantic_kernel_plugins.openapi_plugin_factory import OpenApiPluginFactory
            print(f"[Logged Plugin Loader] Successfully imported OpenApiPluginFactory")
            
            print(f"[Logged Plugin Loader] Creating OpenAPI plugin using factory with manifest: {manifest}")
            
            plugin_instance = OpenApiPluginFactory.create_from_config(manifest)
            print(f"[Logged Plugin Loader] Successfully created OpenAPI plugin instance using factory")
            return plugin_instance
        except ImportError as e:
            print(f"[Logged Plugin Loader] ImportError creating OpenAPI plugin: {e}")
            self.logger.error(f"Failed to import OpenApiPluginFactory: {e}")
            return None
        except Exception as e:
            print(f"[Logged Plugin Loader] General error creating OpenAPI plugin: {e}")
            self.logger.error(f"Failed to create OpenAPI plugin: {e}")
            return None
    
    def _create_python_plugin(self, manifest: Dict[str, Any]):
        """Create a Python plugin instance."""
        module_name = manifest.get('module')
        class_name = manifest.get('class')
        
        if not module_name or not class_name:
            self.logger.error(f"Python plugin manifest missing 'module' or 'class': {manifest}")
            return None
        
        try:
            module = importlib.import_module(f"semantic_kernel_plugins.{module_name}")
            plugin_class = getattr(module, class_name)
            return plugin_class(manifest)
        except (ImportError, AttributeError) as e:
            self.logger.error(f"Failed to create Python plugin {class_name} from {module_name}: {e}")
            return None
    
    def _create_custom_plugin(self, manifest: Dict[str, Any]):
        """Create a custom plugin instance."""
        # This is where you'd handle custom plugin types specific to your application
        self.logger.warning(f"Custom plugin type not yet implemented: {manifest}")
        return None
    
    def _create_sql_plugin(self, manifest: Dict[str, Any]):
        """Create a SQL plugin instance."""
        plugin_type = manifest.get('type')
        
        try:
            if plugin_type == 'sql_schema':
                from semantic_kernel_plugins.sql_schema_plugin import SQLSchemaPlugin
                return SQLSchemaPlugin(manifest)
            elif plugin_type == 'sql_query':
                from semantic_kernel_plugins.sql_query_plugin import SQLQueryPlugin
                return SQLQueryPlugin(manifest)
            else:
                self.logger.error(f"Unknown SQL plugin type: {plugin_type}")
                return None
        except ImportError as e:
            self.logger.error(f"Failed to import SQL plugin class for {plugin_type}: {e}")
            return None
    
    def _wrap_plugin_functions(self, plugin_instance, plugin_name: str):
        """Wrap all kernel functions in a plugin with logging."""
        print(f"[Logged Plugin Loader] Checking logging status for plugin: {plugin_name}")
        log_event(f"[Logged Plugin Loader] Checking logging status for plugin: {plugin_name}")
        
        if not hasattr(plugin_instance, 'is_logging_enabled') or not plugin_instance.is_logging_enabled():
            print(f"[Logged Plugin Loader] Plugin {plugin_name} does not have logging enabled")
            log_event(f"[Logged Plugin Loader] Plugin {plugin_name} does not have logging enabled")
            return
        
        print(f"[Logged Plugin Loader] Starting to wrap functions for plugin: {plugin_name}")
        log_event(f"[Logged Plugin Loader] Starting to wrap functions for plugin: {plugin_name}")
        wrapped_count = 0
        
        # Debug: List all attributes
        all_attrs = [attr for attr in dir(plugin_instance) if not attr.startswith('_')]
        print(f"[Logged Plugin Loader] Plugin {plugin_name} has {len(all_attrs)} public attributes: {all_attrs[:10]}...")
        
        # Find and wrap all kernel functions
        for attr_name in dir(plugin_instance):
            if attr_name.startswith('_'):
                continue
                
            attr = getattr(plugin_instance, attr_name)
            
            # Debug: Check each callable attribute
            if callable(attr):
                has_sk_function = hasattr(attr, '__sk_function__')
                sk_function_value = getattr(attr, '__sk_function__', None) if has_sk_function else None
                print(f"[Logged Plugin Loader] Function {attr_name}: callable=True, has___sk_function__={has_sk_function}, value={sk_function_value}")
            
            # Check if it's a kernel function
            if (callable(attr) and 
                hasattr(attr, '__sk_function__') and 
                attr.__sk_function__):
                
                # Create a logged wrapper
                logged_method = self._create_logged_method(attr, plugin_name, attr_name)
                
                # Replace the method on the instance
                setattr(plugin_instance, attr_name, logged_method)
                
                wrapped_count += 1
                print(f"[Logged Plugin Loader] Wrapped function {plugin_name}.{attr_name} with logging")
                log_event(f"[Logged Plugin Loader] Wrapped function {plugin_name}.{attr_name} with logging")
        
        print(f"[Logged Plugin Loader] Wrapped {wrapped_count} functions for plugin: {plugin_name}")
        log_event(f"[Logged Plugin Loader] Wrapped {wrapped_count} functions for plugin: {plugin_name}")
    
    def _create_logged_method(self, original_method, plugin_name: str, function_name: str):
        """Create a logged wrapper for a plugin method."""
        import time
        import functools
        from semantic_kernel_plugins.plugin_invocation_logger import log_plugin_invocation
        
        @functools.wraps(original_method)
        def logged_wrapper(*args, **kwargs):
            start_time = time.time()
            
            # Prepare parameters (skip 'self' for methods)
            parameters = {}
            if args and hasattr(args[0], '__class__'):
                # This is a method call, skip 'self'
                parameters.update({f"arg_{i}": arg for i, arg in enumerate(args[1:])})
            else:
                parameters.update({f"arg_{i}": arg for i, arg in enumerate(args)})
            parameters.update(kwargs)
            
            try:
                result = original_method(*args, **kwargs)
                end_time = time.time()
                
                # Log successful invocation
                log_plugin_invocation(
                    plugin_name=plugin_name,
                    function_name=function_name,
                    parameters=parameters,
                    result=result,
                    start_time=start_time,
                    end_time=end_time,
                    success=True
                )
                
                return result
                
            except Exception as e:
                end_time = time.time()
                
                # Log failed invocation
                log_plugin_invocation(
                    plugin_name=plugin_name,
                    function_name=function_name,
                    parameters=parameters,
                    result=None,
                    start_time=start_time,
                    end_time=end_time,
                    success=False,
                    error_message=str(e)
                )
                
                # Re-raise the exception
                raise
        
        return logged_wrapper
    
    def _register_plugin_with_kernel(self, plugin_instance, plugin_name: str):
        """Register the plugin with the Semantic Kernel."""
        try:
            # Try different registration methods based on SK version
            if hasattr(self.kernel, 'add_plugin'):
                # Newer SK versions
                self.kernel.add_plugin(plugin_instance, plugin_name=plugin_name)
            elif hasattr(self.kernel, 'import_plugin_from_object'):
                # Older SK versions
                self.kernel.import_plugin_from_object(plugin_instance, plugin_name)
            else:
                # Fallback method
                plugin = KernelPlugin.from_object(plugin_instance, plugin_name)
                self.kernel.plugins.add(plugin)
            
            self.logger.info(f"Registered plugin {plugin_name} with kernel")
            
        except Exception as e:
            self.logger.error(f"Failed to register plugin {plugin_name} with kernel: {e}")
            raise
    
    def load_multiple_plugins(self, manifests: List[Dict[str, Any]], 
                            user_id: Optional[str] = None) -> Dict[str, bool]:
        """
        Load multiple plugins from manifests.
        
        Returns:
            Dict[str, bool]: Plugin name -> success status
        """
        results = {}
        
        for manifest in manifests:
            plugin_name = manifest.get('name', 'unknown')
            results[plugin_name] = self.load_plugin_from_manifest(manifest, user_id)
        
        successful_count = sum(1 for success in results.values() if success)
        total_count = len(results)
        
        log_event(
            f"[Plugin Loader] Loaded {successful_count}/{total_count} plugins",
            extra={
                "successful_plugins": [name for name, success in results.items() if success],
                "failed_plugins": [name for name, success in results.items() if not success],
                "user_id": user_id
            },
            level=logging.INFO
        )
        
        return results
    
    def get_plugin_stats(self) -> Dict[str, Any]:
        """Get plugin usage statistics."""
        return self.plugin_logger.get_plugin_stats()
    
    def get_recent_invocations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent plugin invocations."""
        invocations = self.plugin_logger.get_recent_invocations(limit)
        return [inv.to_dict() for inv in invocations]


def create_logged_plugin_loader(kernel: Kernel) -> LoggedPluginLoader:
    """Factory function to create a logged plugin loader."""
    return LoggedPluginLoader(kernel)
