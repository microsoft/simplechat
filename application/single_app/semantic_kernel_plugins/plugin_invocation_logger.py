# plugin_invocation_logger.py
"""
Semantic Kernel Plugin Invocation Logger

This module provides comprehensive logging for all plugin invocations in Semantic Kernel,
capturing function calls, parameters, results, and execution times before they're sent to the model.
"""

import json
import time
import logging
import functools
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, asdict
from functions_appinsights import log_event, get_appinsights_logger
from functions_authentication import get_current_user_id


@dataclass
class PluginInvocation:
    """Data class for tracking plugin invocations."""
    plugin_name: str
    function_name: str
    parameters: Dict[str, Any]
    result: Any
    start_time: float
    end_time: float
    duration_ms: float
    user_id: Optional[str]
    timestamp: str
    success: bool
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert to JSON string for logging."""
        return json.dumps(self.to_dict(), default=str, indent=2)


class PluginInvocationLogger:
    """Centralized logger for all Semantic Kernel plugin invocations."""
    
    def __init__(self):
        self.invocations: List[PluginInvocation] = []
        self.max_history = 1000  # Keep last 1000 invocations in memory
        self.logger = get_appinsights_logger() or logging.getLogger(__name__)
        
    def log_invocation(self, invocation: PluginInvocation):
        """Log a plugin invocation to Application Insights and local history."""
        # Add to local history
        self.invocations.append(invocation)
        
        # Trim history if needed
        if len(self.invocations) > self.max_history:
            self.invocations = self.invocations[-self.max_history:]
        
        # Enhanced terminal logging
        self._log_to_terminal(invocation)
        
        # Log to Application Insights
        self._log_to_appinsights(invocation)
        
        # Log to standard logging
        self._log_to_standard(invocation)
    
    def _log_to_terminal(self, invocation: PluginInvocation):
        """Log detailed invocation information to terminal."""
        try:
            status = "SUCCESS" if invocation.success else "ERROR"
            print(f"[Plugin Invocation {status}] {invocation.plugin_name}.{invocation.function_name}")
            
            # Show parameters
            if invocation.parameters:
                print(f"  Parameters: {invocation.parameters}")
            else:
                print(f"  Parameters: none")
            
            # Show result or error
            if invocation.success:
                result_str = str(invocation.result)
                if len(result_str) > 300:
                    print(f"  Result: {result_str[:300]}... [truncated to 300 chars]")
                else:
                    print(f"  Result: {result_str}")
            else:
                print(f"  Error: {invocation.error_message}")
            
            print(f"  Duration: {invocation.duration_ms:.2f}ms")
            print(f"  User: {invocation.user_id or 'unknown'}")
            print(f"  Timestamp: {invocation.timestamp}")
            print("") # Empty line for readability
            
        except Exception as e:
            print(f"[Plugin Invocation] Error logging to terminal: {e}")
    
    def _log_to_appinsights(self, invocation: PluginInvocation):
        """Log invocation to Application Insights."""
        try:
            # Prepare sanitized data for Application Insights
            log_data = {
                "plugin_name": invocation.plugin_name,
                "function_name": invocation.function_name,
                "duration_ms": invocation.duration_ms,
                "success": invocation.success,
                "user_id": invocation.user_id,
                "timestamp": invocation.timestamp,
                "parameter_count": len(invocation.parameters) if invocation.parameters else 0,
                "result_type": type(invocation.result).__name__ if invocation.result is not None else "None",
                "error_message": invocation.error_message
            }
            
            # Add sanitized parameters (truncate large values)
            if invocation.parameters:
                sanitized_params = {}
                for key, value in invocation.parameters.items():
                    if isinstance(value, str) and len(value) > 200:
                        sanitized_params[key] = f"{value[:200]}... [truncated]"
                    elif isinstance(value, (dict, list)):
                        sanitized_params[key] = f"<{type(value).__name__}> length: {len(value)}"
                    else:
                        sanitized_params[key] = str(value)[:100]
                log_data["parameters"] = sanitized_params
            
            # Add sanitized result
            if invocation.result is not None:
                result_str = str(invocation.result)
                if len(result_str) > 500:
                    log_data["result_preview"] = f"{result_str[:500]}... [truncated]"
                else:
                    log_data["result_preview"] = result_str
            
            log_event(
                f"[Plugin Invocation] {invocation.plugin_name}.{invocation.function_name}",
                extra=log_data,
                level=logging.INFO if invocation.success else logging.ERROR
            )
            
        except Exception as e:
            self.logger.error(f"Failed to log plugin invocation to Application Insights: {e}")
    
    def _log_to_standard(self, invocation: PluginInvocation):
        """Log invocation to standard Python logging."""
        try:
            if invocation.success:
                self.logger.info(
                    f"[Plugin] {invocation.plugin_name}.{invocation.function_name} "
                    f"executed successfully in {invocation.duration_ms:.2f}ms"
                )
            else:
                self.logger.error(
                    f"[Plugin] {invocation.plugin_name}.{invocation.function_name} "
                    f"failed after {invocation.duration_ms:.2f}ms: {invocation.error_message}"
                )
        except Exception as e:
            self.logger.error(f"Failed to log plugin invocation to standard logging: {e}")
    
    def get_recent_invocations(self, limit: int = 50) -> List[PluginInvocation]:
        """Get recent plugin invocations."""
        return self.invocations[-limit:] if self.invocations else []
    
    def get_invocations_for_user(self, user_id: str, limit: int = 50) -> List[PluginInvocation]:
        """Get recent plugin invocations for a specific user."""
        user_invocations = [inv for inv in self.invocations if inv.user_id == user_id]
        return user_invocations[-limit:] if user_invocations else []
    
    def get_plugin_stats(self) -> Dict[str, Any]:
        """Get statistics about plugin usage."""
        if not self.invocations:
            return {}
        
        stats = {
            "total_invocations": len(self.invocations),
            "successful_invocations": sum(1 for inv in self.invocations if inv.success),
            "failed_invocations": sum(1 for inv in self.invocations if not inv.success),
            "average_duration_ms": sum(inv.duration_ms for inv in self.invocations) / len(self.invocations),
            "plugins": {},
        }
        
        # Per-plugin stats
        for invocation in self.invocations:
            plugin_name = invocation.plugin_name
            if plugin_name not in stats["plugins"]:
                stats["plugins"][plugin_name] = {
                    "total_calls": 0,
                    "successful_calls": 0,
                    "failed_calls": 0,
                    "average_duration_ms": 0,
                    "functions": {}
                }
            
            plugin_stats = stats["plugins"][plugin_name]
            plugin_stats["total_calls"] += 1
            
            if invocation.success:
                plugin_stats["successful_calls"] += 1
            else:
                plugin_stats["failed_calls"] += 1
            
            # Function-level stats
            func_name = invocation.function_name
            if func_name not in plugin_stats["functions"]:
                plugin_stats["functions"][func_name] = {
                    "total_calls": 0,
                    "successful_calls": 0,
                    "failed_calls": 0,
                    "total_duration_ms": 0
                }
            
            func_stats = plugin_stats["functions"][func_name]
            func_stats["total_calls"] += 1
            func_stats["total_duration_ms"] += invocation.duration_ms
            
            if invocation.success:
                func_stats["successful_calls"] += 1
            else:
                func_stats["failed_calls"] += 1
        
        # Calculate averages
        for plugin_name, plugin_stats in stats["plugins"].items():
            if plugin_stats["total_calls"] > 0:
                plugin_durations = [inv.duration_ms for inv in self.invocations 
                                  if inv.plugin_name == plugin_name]
                plugin_stats["average_duration_ms"] = sum(plugin_durations) / len(plugin_durations)
            
            for func_name, func_stats in plugin_stats["functions"].items():
                if func_stats["total_calls"] > 0:
                    func_stats["average_duration_ms"] = func_stats["total_duration_ms"] / func_stats["total_calls"]
        
        return stats
    
    def clear_history(self):
        """Clear the invocation history."""
        self.invocations.clear()


# Global instance
_plugin_logger = PluginInvocationLogger()


def get_plugin_logger() -> PluginInvocationLogger:
    """Get the global plugin invocation logger."""
    return _plugin_logger


def log_plugin_invocation(plugin_name: str, function_name: str, 
                         parameters: Dict[str, Any], result: Any,
                         start_time: float, end_time: float, 
                         success: bool = True, error_message: Optional[str] = None):
    """Convenience function to log a plugin invocation."""
    try:
        user_id = get_current_user_id()
    except Exception:
        user_id = None
    
    invocation = PluginInvocation(
        plugin_name=plugin_name,
        function_name=function_name,
        parameters=parameters,
        result=result,
        start_time=start_time,
        end_time=end_time,
        duration_ms=(end_time - start_time) * 1000,
        user_id=user_id,
        timestamp=datetime.utcnow().isoformat(),
        success=success,
        error_message=error_message
    )
    
    _plugin_logger.log_invocation(invocation)


def plugin_function_logger(plugin_name: str):
    """Decorator to automatically log plugin function invocations."""
    def decorator(func: Callable) -> Callable:
        print(f"[Plugin Function Logger] Decorating function: {func.__name__} for plugin: {plugin_name}")
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            function_name = func.__name__
            
            print(f"[Plugin Function Logger] CALLING: {plugin_name}.{function_name}")
            
            # Prepare parameters (combine args and kwargs)
            parameters = {}
            if args:
                # Handle 'self' parameter for methods
                if hasattr(args[0], '__class__'):
                    parameters.update({f"arg_{i}": arg for i, arg in enumerate(args[1:])})
                else:
                    parameters.update({f"arg_{i}": arg for i, arg in enumerate(args)})
            parameters.update(kwargs)
            
            # Enhanced logging: Show parameters
            param_str = ", ".join([f"{k}={v}" for k, v in parameters.items()]) if parameters else "no parameters"
            print(f"[Plugin Function Logger] PARAMETERS: {plugin_name}.{function_name}({param_str})")
            
            try:
                result = func(*args, **kwargs)
                end_time = time.time()
                duration_ms = (end_time - start_time) * 1000
                
                # Enhanced logging: Show result and timing
                result_preview = str(result)[:200] + "..." if len(str(result)) > 200 else str(result)
                print(f"[Plugin Function Logger] RESULT: {plugin_name}.{function_name} -> {result_preview}")
                print(f"[Plugin Function Logger] TIMING: {plugin_name}.{function_name} completed in {duration_ms:.2f}ms")
                
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
                duration_ms = (end_time - start_time) * 1000
                
                # Enhanced logging: Show error and timing
                print(f"[Plugin Function Logger] ERROR: {plugin_name}.{function_name} failed after {duration_ms:.2f}ms: {str(e)}")
                
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
                
                raise  # Re-raise the exception
        
        return wrapper
    return decorator


def wrap_kernel_function(original_func: Callable, plugin_name: str) -> Callable:
    """Wrap a kernel function to add logging."""
    return plugin_function_logger(plugin_name)(original_func)


def auto_wrap_plugin_functions(plugin_instance, plugin_name: str):
    """Automatically wrap all kernel_function decorated methods in a plugin instance."""
    for attr_name in dir(plugin_instance):
        attr = getattr(plugin_instance, attr_name)
        
        # Check if it's a method with the kernel_function decorator
        if (callable(attr) and 
            hasattr(attr, '__annotations__') and 
            hasattr(attr, '__sk_function__')):  # SK functions have this attribute
            
            # Wrap the method
            wrapped_method = plugin_function_logger(plugin_name)(attr)
            setattr(plugin_instance, attr_name, wrapped_method)
