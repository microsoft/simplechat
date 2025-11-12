# logged_plugin_loader.py
"""
Enhanced plugin loader that automatically wraps plugins with invocation logging.
"""

import importlib
import inspect
import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Type
from semantic_kernel import Kernel
from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_plugin import KernelPlugin
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger, plugin_function_logger, auto_wrap_plugin_functions
from semantic_kernel_plugins.plugin_loader import discover_plugins
from functions_appinsights import log_event
from functions_debug import debug_print
from semantic_kernel_plugins.openapi_plugin_factory import OpenApiPluginFactory
from semantic_kernel_plugins.sql_schema_plugin import SQLSchemaPlugin
from semantic_kernel_plugins.sql_query_plugin import SQLQueryPlugin
from app_settings_cache import get_settings_cache

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
            log_event(f"[Logged Plugin Loader] Plugin manifest missing required 'name' field", level=logging.ERROR)
            return False
        
        try:
            # Load the plugin instance
            debug_print(f"[Logged Plugin Loader] Creating plugin instance for {plugin_name} of type {plugin_type}")
            plugin_instance = self._create_plugin_instance(manifest)
            debug_print(f"[Logged Plugin Loader] Created plugin instance: {plugin_instance}")
            if not plugin_instance:
                debug_print(f"[Logged Plugin Loader] Failed to create plugin instance for {plugin_name} of type {plugin_type}")
                return False
            
            # Enable logging if the plugin supports it
            if hasattr(plugin_instance, 'enable_invocation_logging'):
                debug_print(f"[Logged Plugin Loader] Enabling invocation logging for {plugin_name}")
                plugin_instance.enable_invocation_logging(True)
            
            # Auto-wrap plugin functions with logging
            if isinstance(plugin_instance, BasePlugin):
                log_event(f"[Logged Plugin Loader] Wrapping functions for BasePlugin", 
                         extra={"plugin_name": plugin_name}, 
                         level=logging.DEBUG)
                self._wrap_plugin_functions(plugin_instance, plugin_name)
            else:
                log_event(f"[Logged Plugin Loader] Plugin is not a BasePlugin", 
                         extra={"plugin_name": plugin_name, "plugin_type": type(plugin_instance).__name__}, 
                         level=logging.WARNING)
            
            # Register the plugin with the kernel
            self._register_plugin_with_kernel(plugin_instance, plugin_name)
            
            log_event(
                f"[Logged Plugin Loader] Successfully loaded plugin: {plugin_name}",
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
                f"[Logged Plugin Loader] Failed to load plugin: {plugin_name}",
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
        #elif plugin_type in ['sql_schema', 'sql_query']:
        #    return self._create_sql_plugin(manifest)
        else:
            try:
                debug_print(f"[Logged Plugin Loader] Attempting to discover plugin type: {plugin_type}")
                discovered_plugins = discover_plugins()
                plugin_type = manifest.get('type')
                name = manifest.get('name')
                description = manifest.get('description', '')
                # Normalize for matching
                def normalize(s):
                    return s.replace('_', '').replace('-', '').replace('plugin', '').lower() if s else ''
                debug_print(f"[Logged Plugin Loader] Normalizing plugin type for matching: {plugin_type}")
                normalized_type = normalize(plugin_type)
                debug_print(f"[Logged Plugin Loader] Normalized plugin type: {normalized_type}")
                matched_class = None
                for class_name, cls in discovered_plugins.items():
                    normalized_class = normalize(class_name)
                    print("[Logged Plugin Loader] Checking plugin class:", class_name, "normalized:", normalized_class)
                    if normalized_type == normalized_class or normalized_type in normalized_class:
                        matched_class = cls
                        debug_print(f"[Logged Plugin Loader] Matched class for plugin '{name}' of type '{plugin_type}': {matched_class}")
                        break
                if matched_class:
                    try:
                        plugin = matched_class(manifest) if 'manifest' in matched_class.__init__.__code__.co_varnames else matched_class()
                        log_event(f"[Logged Plugin Loader] Instanced plugin: {name} (type: {plugin_type})", {"plugin_name": name, "plugin_type": plugin_type}, level=logging.INFO)
                        return plugin
                    except Exception as e:
                        log_event(f"[Logged Plugin Loader] Failed to instantiate plugin: {name}: {e}", {"plugin_name": name, "plugin_type": plugin_type, "error": str(e)}, level=logging.ERROR, exceptionTraceback=True)
                else:
                    log_event(f"[Logged Plugin Loader] Unknown plugin type: {plugin_type} for plugin '{name}'", {"plugin_name": name, "plugin_type": plugin_type}, level=logging.WARNING)
            except Exception as e:
                log_event(f"[Logged Plugin Loader] Error discovering plugin types: {e}", {"error": str(e)}, level=logging.ERROR, exceptionTraceback=True)
    
    def _create_openapi_plugin(self, manifest: Dict[str, Any]):
        """Create an OpenAPI plugin instance."""
        plugin_name = manifest.get('name')
        log_event(f"[Logged Plugin Loader] Attempting to create OpenAPI plugin: {plugin_name}", level=logging.DEBUG)
        
        try:
            log_event(f"[Logged Plugin Loader] Creating OpenAPI plugin using factory", 
                     extra={"plugin_name": plugin_name, "manifest": manifest}, 
                     level=logging.DEBUG)
            
            plugin_instance = OpenApiPluginFactory.create_from_config(manifest)
            log_event(f"[Logged Plugin Loader] Successfully created OpenAPI plugin instance using factory", 
                     extra={"plugin_name": plugin_name}, 
                     level=logging.INFO)
            
            # For OpenAPI plugins, we need to wrap the dynamically created functions
            if plugin_instance:
                log_event(f"[Logged Plugin Loader] Wrapping dynamically created OpenAPI functions", 
                         extra={"plugin_name": plugin_name}, 
                         level=logging.DEBUG)
                self._wrap_openapi_plugin_functions(plugin_instance)
            
            return plugin_instance
        except ImportError as e:
            log_event(f"[Logged Plugin Loader] ImportError creating OpenAPI plugin", 
                     extra={"plugin_name": plugin_name, "error": str(e)}, 
                     level=logging.ERROR)
            self.logger.error(f"Failed to import OpenApiPluginFactory: {e}")
            return None
        except Exception as e:
            log_event(f"[Logged Plugin Loader] General error creating OpenAPI plugin", 
                     extra={"plugin_name": plugin_name, "error": str(e)}, 
                     level=logging.ERROR)
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
    
    def _create_sql_plugin(self, manifest: Dict[str, Any]):
        """Create a SQL plugin instance."""
        plugin_type = manifest.get('type')
        
        try:
            if plugin_type == 'sql_schema':
                return SQLSchemaPlugin(manifest)
            elif plugin_type == 'sql_query':
                return SQLQueryPlugin(manifest)
            else:
                self.logger.error(f"Unknown SQL plugin type: {plugin_type}")
                return None
        except ImportError as e:
            self.logger.error(f"Failed to import SQL plugin class for {plugin_type}: {e}")
            return None
    
    def _wrap_plugin_functions(self, plugin_instance, plugin_name: str):
        """Wrap all kernel functions in a plugin with logging."""
        log_event(f"[Logged Plugin Loader] Checking logging status for plugin", 
                 extra={"plugin_name": plugin_name}, 
                 level=logging.DEBUG)
        
        if not hasattr(plugin_instance, 'is_logging_enabled') or not plugin_instance.is_logging_enabled():
            log_event(f"[Logged Plugin Loader] Plugin does not have logging enabled", 
                     extra={"plugin_name": plugin_name}, 
                     level=logging.WARNING)
            return
        
        log_event(f"[Logged Plugin Loader] Starting to wrap functions for plugin", 
                 extra={"plugin_name": plugin_name}, 
                 level=logging.DEBUG)
        wrapped_count = 0
        
        # Debug: List all attributes
        all_attrs = [attr for attr in dir(plugin_instance) if not attr.startswith('_')]
        log_event(f"[Logged Plugin Loader] Plugin attribute analysis", 
                 extra={
                     "plugin_name": plugin_name, 
                     "total_public_attributes": len(all_attrs),
                     "sample_attributes": all_attrs[:10]
                 }, 
                 level=logging.DEBUG)
        
        # Find and wrap all kernel functions
        for attr_name in dir(plugin_instance):
            if attr_name.startswith('_'):
                continue
                
            attr = getattr(plugin_instance, attr_name)
            
            # Debug: Check each callable attribute
            if callable(attr):
                has_sk_function = hasattr(attr, '__sk_function__')
                sk_function_value = getattr(attr, '__sk_function__', None) if has_sk_function else None
                log_event(f"[Logged Plugin Loader] Function analysis", 
                         extra={
                             "plugin_name": plugin_name,
                             "function_name": attr_name,
                             "callable": True,
                             "has_sk_function": has_sk_function,
                             "sk_function_value": sk_function_value
                         }, 
                         level=logging.DEBUG)
            
            # Check if it's a kernel function
            is_kernel_function = False
            
            # Standard check for __sk_function__ attribute
            if (callable(attr) and 
                hasattr(attr, '__sk_function__') and 
                attr.__sk_function__):
                is_kernel_function = True
            
            # For OpenAPI plugins, also check if this is one of the known API operation functions
            elif (callable(attr) and 
                  attr_name in ['listAPIs', 'getMetrics', 'getProviders', 'getProvider', 'getAPI', 'getServiceAPI', 'getServices'] and
                  hasattr(plugin_instance, 'base_url')):  # OpenAPI plugins have base_url
                is_kernel_function = True
                log_event(f"[Logged Plugin Loader] Detected OpenAPI function for enhanced logging", 
                         extra={"plugin_name": plugin_name, "function_name": attr_name}, 
                         level=logging.DEBUG)
            
            if is_kernel_function:
                # Create a logged wrapper
                logged_method = self._create_logged_method(attr, plugin_name, attr_name)
                
                # Replace the method on the instance
                setattr(plugin_instance, attr_name, logged_method)
                
                wrapped_count += 1
                log_event(f"[Logged Plugin Loader] Wrapped function with logging", 
                         extra={"plugin_name": plugin_name, "function_name": attr_name}, 
                         level=logging.INFO)
        
        # DISABLED: OpenAPI kernel plugin wrapping to prevent excessive logging
        # Plugin logging is now handled by the @plugin_function_logger decorator system
        log_event(f"[Logged Plugin Loader] Skipping OpenAPI kernel function wrapping to avoid duplication with decorator logging", 
                 extra={"plugin_name": plugin_name}, 
                 level=logging.DEBUG)
        
        log_event(f"[Logged Plugin Loader] Function wrapping completed", 
                 extra={"plugin_name": plugin_name, "wrapped_count": wrapped_count}, 
                 level=logging.INFO)
    
    def _create_logged_method(self, original_method, plugin_name: str, function_name: str):
        """
        DISABLED: Plugin logging wrapper to prevent duplication.
        Plugin logging is now handled by the @plugin_function_logger decorator system.
        This method now returns the original method unchanged to avoid double-logging.
        """
        # Return the original method unchanged since logging is handled by decorators
        return original_method
    
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
            f"[Logged Plugin Loader] Loaded {successful_count}/{total_count} plugins",
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

    def _wrap_openapi_plugin_functions(self, plugin_instance):
        """
        Wrap OpenAPI plugin's dynamically created functions with logging.
        
        OpenAPI plugins create their functions dynamically, so we need to wrap them
        after the plugin is fully created.
        """
        plugin_name = getattr(plugin_instance, 'display_name', 'OpenAPI')
        log_event(f"[Logged Plugin Loader] Starting to wrap OpenAPI functions for plugin", 
                 extra={"plugin_name": plugin_name}, 
                 level=logging.DEBUG)
        
        wrapped_count = 0
        
        # Get all the dynamically created functions
        # These are methods that have the @kernel_function decorator applied
        for attr_name in dir(plugin_instance):
            if attr_name.startswith('_'):
                continue
                
            attr_value = getattr(plugin_instance, attr_name)
            
            # Check if it's a callable method and has kernel function metadata
            # For OpenAPI plugins, we need to check differently since the functions are dynamically created
            is_kernel_function = False
            
            if (callable(attr_value) and 
                hasattr(attr_value, '__self__')):  # It's a bound method
                
                # Check for SK function metadata on the underlying function
                if hasattr(attr_value, '__sk_function__'):
                    is_kernel_function = True
                elif hasattr(attr_value, '__func__') and hasattr(attr_value.__func__, '__sk_function__'):
                    is_kernel_function = True
                # For OpenAPI, also check if this is one of the known API operation functions
                elif (attr_name in ['listAPIs', 'getMetrics', 'getProviders', 'getProvider', 'getAPI', 'getServiceAPI', 'getServices'] and
                      # Make sure it's not an internal utility function
                      not attr_name.startswith('get_') and 
                      not attr_name in ['get_available_operations', 'get_functions', 'get_kernel_plugin', 'get_operation_details']):
                    is_kernel_function = True
                    
            if is_kernel_function:
                
                log_event(f"[Logged Plugin Loader] Found OpenAPI function to wrap", 
                         extra={
                             "plugin_name": plugin_name,
                             "function_name": attr_name,
                             "callable": callable(attr_value),
                             "has_sk_function": hasattr(attr_value, '__sk_function__'),
                             "is_bound_method": hasattr(attr_value, '__self__')
                         }, 
                         level=logging.DEBUG)
                
                # Create a wrapped version of the function
                original_func = attr_value
                
                def create_wrapper(func_name, original_function):
                    def wrapper(*args, **kwargs):
                        # Log the function call
                        start_time = time.time()
                        
                        # Extract user context if available
                        user_context = self._get_user_context()
                        
                        log_event(f"[Plugin Function Logger] OpenAPI Function Call Start", 
                                 extra={
                                     "plugin": plugin_name,
                                     "function": func_name,
                                     "user_id": user_context.get('user_id', 'unknown'),
                                     "timestamp": datetime.now().isoformat(),
                                     "parameters": kwargs
                                 }, 
                                 level=logging.INFO)
                        
                        try:
                            # Call the original function
                            result = original_function(*args, **kwargs)
                            
                            # Calculate execution time
                            execution_time = time.time() - start_time
                            
                            result_preview = str(result)[:500] + ('...' if len(str(result)) > 500 else '')
                            
                            log_event(f"[Plugin Function Logger] OpenAPI Function Call Success", 
                                     extra={
                                         "plugin": plugin_name,
                                         "function": func_name,
                                         "result_preview": result_preview,
                                         "execution_time": execution_time,
                                         "status": "SUCCESS"
                                     }, 
                                     level=logging.INFO)
                            
                            # Log to Application Insights if logger is available
                            if hasattr(self, 'logger'):
                                self.logger.info(
                                    f"OpenAPI function {func_name} executed successfully",
                                    extra={
                                        'plugin_name': plugin_name,
                                        'function_name': func_name,
                                        'execution_time': execution_time,
                                        'user_context': user_context,
                                        'parameters': kwargs,
                                        'result_length': len(str(result)),
                                        'status': 'success'
                                    }
                                )
                            
                            return result
                            
                        except Exception as e:
                            execution_time = time.time() - start_time
                            
                            log_event(f"[Plugin Function Logger] OpenAPI Function Call Failed", 
                                     extra={
                                         "plugin": plugin_name,
                                         "function": func_name,
                                         "error": str(e),
                                         "execution_time": execution_time,
                                         "status": "FAILED"
                                     }, 
                                     level=logging.ERROR)
                            
                            # Log error to Application Insights if logger is available
                            if hasattr(self, 'logger'):
                                self.logger.error(
                                    f"OpenAPI function {func_name} failed",
                                    extra={
                                        'plugin_name': plugin_name,
                                        'function_name': func_name,
                                        'execution_time': execution_time,
                                        'user_context': user_context,
                                        'parameters': kwargs,
                                        'error': str(e),
                                        'status': 'failed'
                                    }
                                )
                            
                            raise
                    
                    # Preserve the original function's metadata
                    wrapper.__name__ = func_name
                    wrapper.__qualname__ = original_function.__qualname__
                    wrapper.__doc__ = original_function.__doc__
                    
                    # Copy over the SK function metadata
                    if hasattr(original_function, '__sk_function__'):
                        wrapper.__sk_function__ = original_function.__sk_function__
                    
                    return wrapper
                
                # Create the wrapper and replace the original method
                wrapped_func = create_wrapper(attr_name, original_func)
                setattr(plugin_instance, attr_name, wrapped_func)
                wrapped_count += 1
                
        log_event(f"[Logged Plugin Loader] OpenAPI function wrapping completed", 
                 extra={"plugin_name": plugin_name, "wrapped_count": wrapped_count}, 
                 level=logging.INFO)
        return wrapped_count
    
    def _get_user_context(self) -> Dict[str, Any]:
        """Get current user context for logging."""
        try:
            from functions_authentication import get_current_user_id
            user_id = get_current_user_id()
            return {"user_id": user_id}
        except Exception:
            return {"user_id": "unknown"}


def create_logged_plugin_loader(kernel: Kernel) -> LoggedPluginLoader:
    """Factory function to create a logged plugin loader."""
    return LoggedPluginLoader(kernel)
