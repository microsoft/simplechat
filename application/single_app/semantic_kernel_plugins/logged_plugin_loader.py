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
            
            # For OpenAPI plugins, we need to wrap the dynamically created functions
            if plugin_instance:
                print(f"[Logged Plugin Loader] Wrapping dynamically created OpenAPI functions for: {plugin_name}")
                self._wrap_openapi_plugin_functions(plugin_instance)
            
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
                print(f"[Logged Plugin Loader] Detected OpenAPI function {attr_name} for enhanced logging")
            
            if is_kernel_function:
                # Create a logged wrapper
                logged_method = self._create_logged_method(attr, plugin_name, attr_name)
                
                # Replace the method on the instance
                setattr(plugin_instance, attr_name, logged_method)
                
                wrapped_count += 1
                print(f"[Logged Plugin Loader] Wrapped function {plugin_name}.{attr_name} with logging")
                log_event(f"[Logged Plugin Loader] Wrapped function {plugin_name}.{attr_name} with logging")
        
        # CRITICAL: For OpenAPI plugins, also wrap the kernel plugin functions
        if hasattr(plugin_instance, 'base_url') and hasattr(plugin_instance, 'get_kernel_plugin'):
            try:
                print(f"[Logged Plugin Loader] Wrapping kernel plugin functions for OpenAPI plugin: {plugin_name}")
                kernel_plugin = plugin_instance.get_kernel_plugin()
                print(f"[Logged Plugin Loader] Kernel plugin created with {len(kernel_plugin.functions)} functions")
                print(f"[Logged Plugin Loader] Available kernel functions: {list(kernel_plugin.functions.keys())}")
                
                # Wrap functions in the kernel plugin
                for func_name, kernel_func in kernel_plugin.functions.items():
                    print(f"[Logged Plugin Loader] Checking kernel function: {func_name}")
                    # Target the actual kernel functions that Semantic Kernel calls
                    if func_name in ['call_operation', 'get_available_operations', 'list_available_apis']:
                        print(f"[Logged Plugin Loader] Wrapping kernel function: {func_name}")
                        print(f"[Logged Plugin Loader] Kernel function type: {type(kernel_func)}")
                        print(f"[Logged Plugin Loader] Kernel function attributes: {dir(kernel_func)}")
                        
                        # Try to find the actual function method
                        original_func = None
                        if hasattr(kernel_func, 'function'):
                            original_func = kernel_func.function
                        elif hasattr(kernel_func, '_function'):
                            original_func = kernel_func._function
                        elif hasattr(kernel_func, 'method'):
                            original_func = kernel_func.method
                        elif hasattr(kernel_func, '_method'):
                            original_func = kernel_func._method
                        else:
                            # Fall back to getting the function from the plugin instance
                            original_func = getattr(plugin_instance, func_name, None)
                            
                        if original_func and callable(original_func):
                            print(f"[Logged Plugin Loader] Found original function: {type(original_func)}")
                            logged_kernel_func = self._create_logged_method(original_func, plugin_name, func_name)
                            
                            # Try to replace the function in the kernel function object
                            if hasattr(kernel_func, 'function'):
                                kernel_func.function = logged_kernel_func
                            elif hasattr(kernel_func, '_function'):
                                kernel_func._function = logged_kernel_func
                            elif hasattr(kernel_func, 'method'):
                                kernel_func.method = logged_kernel_func
                            elif hasattr(kernel_func, '_method'):
                                kernel_func._method = logged_kernel_func
                            else:
                                # Fall back to replacing on the plugin instance
                                setattr(plugin_instance, func_name, logged_kernel_func)
                            
                            # ALSO wrap the kernel function's invoke method for direct SK calls
                            if hasattr(kernel_func, 'invoke'):
                                print(f"[Logged Plugin Loader] Also wrapping kernel function invoke method for: {func_name}")
                                original_invoke = kernel_func.invoke
                                
                                # Create a wrapper for the invoke method
                                def create_invoke_wrapper(orig_invoke, plugin_nm, func_nm):
                                    async def logged_invoke(*args, **kwargs):
                                        print(f"🚀 [DEBUG] Kernel function invoke called: {plugin_nm}.{func_nm}")
                                        print(f"🚀 [DEBUG] Invoke args: {args}")
                                        print(f"🚀 [DEBUG] Invoke kwargs: {kwargs}")
                                        
                                        import time
                                        start_time = time.time()
                                        try:
                                            result = await orig_invoke(*args, **kwargs)
                                            duration = time.time() - start_time
                                            print(f"🚀 [DEBUG] Kernel invoke result: {result}")
                                            print(f"🚀 [DEBUG] Kernel invoke duration: {duration:.3f}s")
                                            return result
                                        except Exception as e:
                                            duration = time.time() - start_time
                                            print(f"🚀 [DEBUG] Kernel invoke error: {e}")
                                            print(f"🚀 [DEBUG] Kernel invoke duration: {duration:.3f}s")
                                            raise
                                    return logged_invoke
                                
                                kernel_func.invoke = create_invoke_wrapper(original_invoke, plugin_name, func_name)
                                print(f"[Logged Plugin Loader] Wrapped kernel invoke method for: {func_name}")
                                
                            wrapped_count += 1
                            print(f"[Logged Plugin Loader] Successfully wrapped kernel function {plugin_name}.{func_name}")
                        else:
                            print(f"[Logged Plugin Loader] Could not find callable function for: {func_name}")
                    else:
                        print(f"[Logged Plugin Loader] Skipping kernel function: {func_name} (not in target list)")
                        
            except Exception as e:
                print(f"[Logged Plugin Loader] Error wrapping kernel plugin functions: {e}")
                import traceback
                print(f"[Logged Plugin Loader] Traceback: {traceback.format_exc()}")
                log_event(f"[Logged Plugin Loader] Error wrapping kernel plugin functions: {e}")
        
        print(f"[Logged Plugin Loader] Wrapped {wrapped_count} functions for plugin: {plugin_name}")
        log_event(f"[Logged Plugin Loader] Wrapped {wrapped_count} functions for plugin: {plugin_name}")
    
    def _create_logged_method(self, original_method, plugin_name: str, function_name: str):
        """Create a logged wrapper for a plugin method."""
        import time
        import functools
        from semantic_kernel_plugins.plugin_invocation_logger import log_plugin_invocation
        
        @functools.wraps(original_method)
        def logged_wrapper(*args, **kwargs):
            # Add immediate debug logging to see if wrapper is called
            print(f"🚀 [DEBUG] Plugin function called: {plugin_name}.{function_name}")
            log_event(f"🚀 [DEBUG] Plugin function called: {plugin_name}.{function_name}")
            
            start_time = time.time()
            
            # Prepare parameters (skip 'self' for methods)
            parameters = {}
            if args and hasattr(args[0], '__class__'):
                # This is a method call, skip 'self'
                parameters.update({f"arg_{i}": arg for i, arg in enumerate(args[1:])})
            else:
                parameters.update({f"arg_{i}": arg for i, arg in enumerate(args)})
            parameters.update(kwargs)
            
            print(f"🔧 [DEBUG] Calling original method: {plugin_name}.{function_name} with params: {parameters}")
            
            try:
                result = original_method(*args, **kwargs)
                end_time = time.time()
                
                print(f"✅ [DEBUG] Method completed successfully: {plugin_name}.{function_name}")
                
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
                
                print(f"❌ [DEBUG] Method failed: {plugin_name}.{function_name} - {str(e)}")
                
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

    def _wrap_openapi_plugin_functions(self, plugin_instance):
        """
        Wrap OpenAPI plugin's dynamically created functions with logging.
        
        OpenAPI plugins create their functions dynamically, so we need to wrap them
        after the plugin is fully created.
        """
        plugin_name = getattr(plugin_instance, 'display_name', 'OpenAPI')
        print(f"[Logged Plugin Loader] Starting to wrap OpenAPI functions for plugin: {plugin_name}")
        
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
                
                print(f"[Logged Plugin Loader] Found OpenAPI function to wrap: {attr_name}")
                print(f"[Logged Plugin Loader] Function details: callable={callable(attr_value)}, has___sk_function__={hasattr(attr_value, '__sk_function__')}, is_bound_method={hasattr(attr_value, '__self__')}")
                
                # Create a wrapped version of the function
                original_func = attr_value
                
                def create_wrapper(func_name, original_function):
                    def wrapper(*args, **kwargs):
                        # Log the function call
                        start_time = time.time()
                        
                        # Extract user context if available
                        user_context = self._get_user_context()
                        
                        print(f"[Plugin Function Logger] === OpenAPI Function Call Start ===")
                        print(f"[Plugin Function Logger] Plugin: {plugin_name}")
                        print(f"[Plugin Function Logger] Function: {func_name}")
                        print(f"[Plugin Function Logger] User: {user_context.get('user_id', 'unknown')}")
                        print(f"[Plugin Function Logger] Timestamp: {datetime.now().isoformat()}")
                        print(f"[Plugin Function Logger] Parameters: {kwargs}")
                        
                        try:
                            # Call the original function
                            result = original_function(*args, **kwargs)
                            
                            # Calculate execution time
                            execution_time = time.time() - start_time
                            
                            print(f"[Plugin Function Logger] Result: {str(result)[:500]}{'...' if len(str(result)) > 500 else ''}")
                            print(f"[Plugin Function Logger] Execution time: {execution_time:.3f}s")
                            print(f"[Plugin Function Logger] Status: SUCCESS")
                            
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
                            print(f"[Plugin Function Logger] ERROR: {str(e)}")
                            print(f"[Plugin Function Logger] Execution time: {execution_time:.3f}s")
                            print(f"[Plugin Function Logger] Status: FAILED")
                            
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
                        finally:
                            print(f"[Plugin Function Logger] === OpenAPI Function Call End ===")
                    
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
                
        print(f"[Logged Plugin Loader] Wrapped {wrapped_count} OpenAPI functions for plugin: {plugin_name}")
        return wrapped_count


def create_logged_plugin_loader(kernel: Kernel) -> LoggedPluginLoader:
    """Factory function to create a logged plugin loader."""
    return LoggedPluginLoader(kernel)
