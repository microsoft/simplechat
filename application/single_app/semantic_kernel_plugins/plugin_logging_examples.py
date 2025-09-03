# plugin_logging_examples.py
"""
Examples of how to manually wrap existing plugins with invocation logging.
"""

import time
from typing import Any, Dict
from semantic_kernel.functions import kernel_function
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import (
    plugin_function_logger, 
    log_plugin_invocation,
    auto_wrap_plugin_functions
)


# Example 1: Using the decorator approach
class ExamplePlugin(BasePlugin):
    """Example plugin showing how to use the logging decorator."""
    
    def __init__(self, manifest=None):
        super().__init__(manifest)
        self.name = "ExamplePlugin"
    
    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": "example",
            "description": "Example plugin for demonstrating logging",
            "methods": [
                {
                    "name": "sample_function",
                    "description": "A sample function for testing",
                    "parameters": [
                        {"name": "input_text", "type": "str", "description": "Input text", "required": True}
                    ],
                    "returns": {"type": "str", "description": "Processed text"}
                }
            ]
        }
    
    @plugin_function_logger("ExamplePlugin")
    @kernel_function(description="Sample function that processes text")
    def sample_function(self, input_text: str) -> str:
        """Sample function that demonstrates plugin logging."""
        # Simulate some processing time
        time.sleep(0.1)
        return f"Processed: {input_text}"
    
    @plugin_function_logger("ExamplePlugin")
    @kernel_function(description="Function that might fail")
    def risky_function(self, input_text: str) -> str:
        """Function that demonstrates error logging."""
        if "error" in input_text.lower():
            raise ValueError("Intentional error for testing")
        return f"Success: {input_text}"


# Example 2: Manual wrapping approach
class ManuallyLoggedPlugin(BasePlugin):
    """Example plugin showing manual logging integration."""
    
    def __init__(self, manifest=None):
        super().__init__(manifest)
        self.name = "ManuallyLoggedPlugin"
    
    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": "manual",
            "description": "Plugin with manual logging integration",
            "methods": [
                {
                    "name": "manual_logged_function",
                    "description": "Function with manual logging",
                    "parameters": [
                        {"name": "data", "type": "str", "description": "Input data", "required": True}
                    ],
                    "returns": {"type": "str", "description": "Processed data"}
                }
            ]
        }
    
    @kernel_function(description="Function with manual logging implementation")
    def manual_logged_function(self, data: str) -> str:
        """Function that manually logs its invocation."""
        start_time = time.time()
        plugin_name = self.name
        function_name = "manual_logged_function"
        parameters = {"data": data}
        
        try:
            # Your actual function logic here
            result = f"Manually logged: {data}"
            
            # Log successful invocation
            end_time = time.time()
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
            # Log failed invocation
            end_time = time.time()
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


# Example 3: Auto-wrapping existing plugins
def wrap_existing_plugin(plugin_instance, plugin_name: str):
    """
    Example of how to automatically wrap an existing plugin instance with logging.
    """
    # Enable logging if the plugin supports it
    if hasattr(plugin_instance, 'enable_invocation_logging'):
        plugin_instance.enable_invocation_logging(True)
    
    # Auto-wrap all kernel functions
    auto_wrap_plugin_functions(plugin_instance, plugin_name)
    
    return plugin_instance


# Example 4: Wrapping plugins during kernel registration
def register_plugin_with_logging(kernel, plugin_instance, plugin_name: str):
    """
    Example of how to register a plugin with the kernel while adding logging.
    """
    from semantic_kernel.functions.kernel_plugin import KernelPlugin
    
    # Wrap the plugin with logging
    logged_plugin = wrap_existing_plugin(plugin_instance, plugin_name)
    
    # Register with kernel
    kernel_plugin = KernelPlugin.from_object(plugin_name, logged_plugin)
    kernel.add_plugin(kernel_plugin)
    
    return logged_plugin


# Example 5: Enhancing existing plugins in your codebase
def enhance_openapi_plugin_with_logging():
    """
    Example of enhancing the existing OpenAPI plugin with additional logging.
    """
    try:
        from semantic_kernel_plugins.openapi_plugin import OpenApiPlugin
        
        # Store original method
        original_call_operation = OpenApiPlugin.call_operation
        
        def logged_call_operation(self, operation_id: str, **kwargs):
            """Enhanced call_operation with detailed logging."""
            start_time = time.time()
            
            try:
                result = original_call_operation(self, operation_id, **kwargs)
                end_time = time.time()
                
                # Log the invocation
                log_plugin_invocation(
                    plugin_name="OpenApiPlugin",
                    function_name="call_operation",
                    parameters={"operation_id": operation_id, **kwargs},
                    result=result,
                    start_time=start_time,
                    end_time=end_time,
                    success=True
                )
                
                return result
                
            except Exception as e:
                end_time = time.time()
                
                log_plugin_invocation(
                    plugin_name="OpenApiPlugin",
                    function_name="call_operation",
                    parameters={"operation_id": operation_id, **kwargs},
                    result=None,
                    start_time=start_time,
                    end_time=end_time,
                    success=False,
                    error_message=str(e)
                )
                
                raise
        
        # Replace the method
        OpenApiPlugin.call_operation = logged_call_operation
        
    except ImportError:
        pass  # OpenApiPlugin not available


# Example 6: Usage examples
def demo_plugin_logging():
    """
    Demonstrate plugin logging functionality.
    """
    from semantic_kernel import Kernel
    from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger
    
    # Create kernel and plugin
    kernel = Kernel()
    plugin = ExamplePlugin()
    
    # Register with logging
    register_plugin_with_logging(kernel, plugin, "ExamplePlugin")
    
    # Use the plugin (this would normally happen during chat completion)
    try:
        result1 = plugin.sample_function("Hello, World!")
        print(f"Result 1: {result1}")
        
        # This will fail and be logged
        result2 = plugin.risky_function("error test")
        print(f"Result 2: {result2}")
        
    except Exception as e:
        print(f"Expected error: {e}")
    
    # Get logging statistics
    logger = get_plugin_logger()
    stats = logger.get_plugin_stats()
    recent_invocations = logger.get_recent_invocations(10)
    
    print("Plugin Statistics:")
    print(f"Total invocations: {stats.get('total_invocations', 0)}")
    print(f"Successful: {stats.get('successful_invocations', 0)}")
    print(f"Failed: {stats.get('failed_invocations', 0)}")
    
    print("\nRecent Invocations:")
    for inv in recent_invocations:
        print(f"- {inv.plugin_name}.{inv.function_name}: {inv.success} ({inv.duration_ms:.2f}ms)")


if __name__ == "__main__":
    # Run the demo
    demo_plugin_logging()
