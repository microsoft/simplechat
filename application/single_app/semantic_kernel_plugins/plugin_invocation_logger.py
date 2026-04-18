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
import inspect
import threading
import uuid
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass, asdict
from functions_appinsights import log_event, get_appinsights_logger
from functions_authentication import get_current_user_id
from functions_debug import debug_print


@dataclass
class PluginInvocationStart:
    """Data class for tracking plugin invocation starts."""
    plugin_name: str
    function_name: str
    parameters: Dict[str, Any]
    user_id: Optional[str]
    timestamp: str
    conversation_id: Optional[str] = None
    invocation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return asdict(self)


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
    conversation_id: Optional[str] = None
    invocation_id: Optional[str] = None
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert to JSON string for logging."""
        return json.dumps(self.to_dict(), default=str, indent=2)


def _compact_plugin_log_value(value: Any, max_length: int = 160) -> Any:
    """Return a compact logging-safe representation for structured plugin summaries."""
    if value is None or isinstance(value, (int, float, bool)):
        return value

    if isinstance(value, str):
        return value if len(value) <= max_length else f"{value[:max_length]}... [truncated]"

    if isinstance(value, list):
        compact_items = [_compact_plugin_log_value(item, max_length=max_length) for item in value[:5]]
        if len(value) > 5:
            compact_items.append({'remaining_items': len(value) - 5})
        return compact_items

    if isinstance(value, dict):
        compact_mapping = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 8:
                compact_mapping['remaining_keys'] = len(value) - 8
                break
            compact_mapping[str(key)] = _compact_plugin_log_value(item, max_length=max_length)
        return compact_mapping

    return str(value)


def _build_plugin_result_logging_payload(plugin_name: str, function_name: str, result: Any) -> tuple:
    """Build preview and structured summary payloads for plugin invocation logs."""
    result_str = str(result)
    result_preview = result_str[:200] + "..." if len(result_str) > 200 else result_str
    result_summary = None

    if plugin_name != 'TabularProcessingPlugin' or result is None:
        return result_preview, result_summary

    try:
        result_payload = json.loads(result) if isinstance(result, str) else result
    except Exception:
        return result_preview, result_summary

    if not isinstance(result_payload, dict):
        return result_preview, result_summary

    summary = {}
    key_names = (
        'filename',
        'selected_sheet',
        'column',
        'search_value',
        'search_operator',
        'searched_columns',
        'matched_columns',
        'return_columns',
        'lookup_column',
        'target_column',
        'operation',
        'filter_applied',
        'normalize_match',
        'extract_mode',
        'extract_pattern',
        'url_path_segments',
        'distinct_count',
        'returned_values',
        'row_count',
        'rows_scanned',
        'total_matches',
        'returned_rows',
        'matched_cell_count',
        'extracted_match_count',
        'sheets_searched',
        'sheets_matched',
        'source_sheet',
        'target_sheet',
        'relationship_type',
        'source_cohort_size',
        'matched_target_row_count',
        'result',
        'error',
    )
    for key_name in key_names:
        if key_name in result_payload:
            summary[key_name] = _compact_plugin_log_value(result_payload.get(key_name))

    if isinstance(result_payload.get('values'), list):
        summary['values_sample'] = _compact_plugin_log_value(result_payload['values'][:5])
        summary['values_sample_limited'] = len(result_payload['values']) > 5

    if isinstance(result_payload.get('data'), list):
        summary['data_sample_count'] = min(len(result_payload['data']), 5)

    if summary:
        result_summary = summary

    return result_preview, result_summary


class PluginInvocationLogger:
    """Centralized logger for all Semantic Kernel plugin invocations."""
    
    def __init__(self):
        self.invocations: List[PluginInvocation] = []
        self.max_history = 1000  # Keep last 1000 invocations in memory
        self.logger = get_appinsights_logger() or logging.getLogger(__name__)
        self._callbacks: Dict[str, List[Callable[[PluginInvocation], None]]] = {}
        self._start_callbacks: Dict[str, List[Callable[[PluginInvocationStart], None]]] = {}
        self._callback_lock = threading.Lock()

    def log_invocation_start(self, invocation_start: PluginInvocationStart):
        """Fire callbacks for the start of a plugin invocation."""
        self._fire_start_callbacks(invocation_start)
        
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

        # Fire registered thought callbacks
        self._fire_callbacks(invocation)
    
    def _log_to_terminal(self, invocation: PluginInvocation):
        """Log detailed invocation information to terminal."""
        try:
            status = "SUCCESS" if invocation.success else "ERROR"
            
            # Keep minimal print for real-time monitoring
            debug_print(f"[Plugin {status}] {invocation.plugin_name}.{invocation.function_name} ({invocation.duration_ms:.1f}ms)")
            
            # Comprehensive structured logging for production
            log_data = {
                "plugin_name": invocation.plugin_name,
                "function_name": invocation.function_name,
                "duration_ms": invocation.duration_ms,
                "success": invocation.success,
                "user_id": invocation.user_id,
                "timestamp": invocation.timestamp
            }
            
            if invocation.parameters:
                log_data["parameter_count"] = len(invocation.parameters)
                # Sanitize parameters for logging
                sanitized_params = {}
                for key, value in invocation.parameters.items():
                    if isinstance(value, str) and len(value) > 100:
                        sanitized_params[key] = f"{value[:100]}... [truncated]"
                    else:
                        sanitized_params[key] = str(value)[:100]
                log_data["parameters"] = sanitized_params
            
            if invocation.success:
                if invocation.result:
                    result_preview, result_summary = _build_plugin_result_logging_payload(
                        invocation.plugin_name,
                        invocation.function_name,
                        invocation.result,
                    )
                    log_data["result_preview"] = result_preview
                    if result_summary:
                        log_data["result_summary"] = result_summary
                    log_data["result_type"] = type(invocation.result).__name__
                
                log_event(f"Plugin function executed successfully", 
                         extra=log_data, 
                         level=logging.INFO)
            else:
                log_data["error_message"] = invocation.error_message
                log_event(f"Plugin function execution failed", 
                         extra=log_data, 
                         level=logging.ERROR)
                         
        except Exception as e:
            log_event(f"[Plugin Invocation] Error logging to terminal", 
                     extra={"error_message": str(e)}, 
                     level=logging.ERROR)
    
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
                result_preview, result_summary = _build_plugin_result_logging_payload(
                    invocation.plugin_name,
                    invocation.function_name,
                    invocation.result,
                )
                if len(str(invocation.result)) > 500:
                    log_data["result_preview"] = f"{result_preview[:500]}... [truncated]"
                else:
                    log_data["result_preview"] = result_preview
                if result_summary:
                    log_data["result_summary"] = result_summary
            
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
    
    def get_invocations_for_conversation(self, user_id: str, conversation_id: str, limit: int = 50) -> List[PluginInvocation]:
        """Get recent plugin invocations for a specific user and conversation."""
        conversation_invocations = [
            inv for inv in self.invocations 
            if inv.user_id == user_id and inv.conversation_id == conversation_id
        ]
        return conversation_invocations[-limit:] if conversation_invocations else []
    
    def clear_invocations_for_conversation(self, user_id: str, conversation_id: str):
        """Clear plugin invocations for a specific user and conversation.
        
        This ensures each message only shows citations for tools executed 
        during that specific interaction, not accumulated from the entire conversation.
        """
        self.invocations = [
            inv for inv in self.invocations 
            if not (inv.user_id == user_id and inv.conversation_id == conversation_id)
        ]
    
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

    def register_callback(self, key, callback):
        """Register a callback fired on each plugin invocation for the given key.

        Args:
            key: A string key, typically f"{user_id}:{conversation_id}".
            callback: Called with the PluginInvocation after it is logged.
        """
        with self._callback_lock:
            if key not in self._callbacks:
                self._callbacks[key] = []
            self._callbacks[key].append(callback)

    def register_start_callback(self, key, callback):
        """Register a callback fired when a plugin invocation starts for the given key."""
        with self._callback_lock:
            if key not in self._start_callbacks:
                self._start_callbacks[key] = []
            self._start_callbacks[key].append(callback)

    def deregister_callbacks(self, key):
        """Remove all completion and start callbacks for the given key."""
        with self._callback_lock:
            self._callbacks.pop(key, None)
            self._start_callbacks.pop(key, None)

    def _fire_start_callbacks(self, invocation_start):
        """Fire matching callbacks for the start of a plugin invocation."""
        key = f"{invocation_start.user_id}:{invocation_start.conversation_id}"
        with self._callback_lock:
            callbacks = list(self._start_callbacks.get(key, []))
        for cb in callbacks:
            try:
                cb(invocation_start)
            except Exception as e:
                log_event(f"Plugin invocation start callback error: {e}", level="WARNING")

    def _fire_callbacks(self, invocation):
        """Fire matching callbacks for this invocation's user+conversation."""
        key = f"{invocation.user_id}:{invocation.conversation_id}"
        with self._callback_lock:
            callbacks = list(self._callbacks.get(key, []))
        for cb in callbacks:
            try:
                cb(invocation)
            except Exception as e:
                log_event(f"Plugin invocation callback error: {e}", level="WARNING")


# Global instance
_plugin_logger = PluginInvocationLogger()


def get_plugin_logger() -> PluginInvocationLogger:
    """Get the global plugin invocation logger."""
    return _plugin_logger


def _resolve_invocation_context(conversation_id: Optional[str] = None):
    """Resolve user and conversation context for plugin invocation logging."""
    try:
        user_id = get_current_user_id()
    except Exception:
        user_id = None

    if conversation_id is None:
        try:
            from flask import g
            conversation_id = getattr(g, 'conversation_id', None)
        except Exception:
            conversation_id = None

    return user_id, conversation_id


def log_plugin_invocation_started(
    plugin_name: str,
    function_name: str,
    parameters: Dict[str, Any],
    conversation_id: Optional[str] = None,
    invocation_id: Optional[str] = None,
):
    """Convenience function to log the start of a plugin invocation."""
    user_id, resolved_conversation_id = _resolve_invocation_context(conversation_id)

    invocation_start = PluginInvocationStart(
        plugin_name=plugin_name,
        function_name=function_name,
        parameters=parameters,
        user_id=user_id,
        conversation_id=resolved_conversation_id,
        timestamp=datetime.utcnow().isoformat(),
        invocation_id=invocation_id or str(uuid.uuid4()),
    )

    _plugin_logger.log_invocation_start(invocation_start)


def log_plugin_invocation(plugin_name: str, function_name: str, 
                         parameters: Dict[str, Any], result: Any,
                         start_time: float, end_time: float, 
                         success: bool = True, error_message: Optional[str] = None,
                         conversation_id: Optional[str] = None,
                         invocation_id: Optional[str] = None):
    """Convenience function to log a plugin invocation."""
    user_id, resolved_conversation_id = _resolve_invocation_context(conversation_id)
    
    invocation = PluginInvocation(
        plugin_name=plugin_name,
        function_name=function_name,
        parameters=parameters,
        result=result,
        start_time=start_time,
        end_time=end_time,
        duration_ms=(end_time - start_time) * 1000,
        user_id=user_id,
        conversation_id=resolved_conversation_id,
        invocation_id=invocation_id or str(uuid.uuid4()),
        timestamp=datetime.utcnow().isoformat(),
        success=success,
        error_message=error_message
    )
    
    _plugin_logger.log_invocation(invocation)


def plugin_function_logger(plugin_name: str):
    """Decorator to automatically log plugin function invocations."""
    def decorator(func: Callable) -> Callable:
        log_event(f"[Plugin Function Logger] Decorating function for plugin", 
                 extra={"function_name": func.__name__, "plugin_name": plugin_name}, 
                 level=logging.DEBUG)

        try:
            unwrapped_func = inspect.unwrap(func)
        except Exception:
            unwrapped_func = func

        # Only skip the first positional argument when the wrapped callable
        # explicitly declares a conventional instance/class receiver.
        skip_first_positional_arg = False
        try:
            signature = inspect.signature(unwrapped_func)
            parameters = list(signature.parameters.values())
            if parameters:
                first_parameter = parameters[0]
                if (
                    first_parameter.kind in (
                        inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    )
                    and first_parameter.name in {"self", "cls"}
                ):
                    skip_first_positional_arg = True
        except (TypeError, ValueError):
            # Keep all args if the callable cannot be introspected.
            skip_first_positional_arg = False

        is_async_callable = inspect.iscoroutinefunction(unwrapped_func)
        
        def _build_parameters(args, kwargs):
            parameters = {}
            if args:
                positional_args = args[1:] if skip_first_positional_arg else args
                parameters.update({f"arg_{i}": arg for i, arg in enumerate(positional_args)})
            parameters.update(kwargs)
            return parameters

        def _log_start(function_name: str):
            log_event(
                f"[Plugin Function Logger] Function call started",
                extra={"plugin_name": plugin_name, "function_name": function_name},
                level=logging.DEBUG
            )

        def _log_parameters(function_name: str, parameters: Dict[str, Any]):
            param_str = ", ".join([f"{k}={v}" for k, v in parameters.items()]) if parameters else "no parameters"
            log_event(
                f"[Plugin Function Logger] Function parameters",
                extra={
                    "plugin_name": plugin_name,
                    "function_name": function_name,
                    "parameters": parameters,
                    "param_string": param_str
                },
                level=logging.DEBUG
            )

        def _log_success(function_name: str, result: Any, duration_ms: float):
            result_preview, result_summary = _build_plugin_result_logging_payload(
                plugin_name,
                function_name,
                result,
            )
            log_event(
                f"[Plugin Function Logger] Function completed successfully",
                extra={
                    "plugin_name": plugin_name,
                    "function_name": function_name,
                    "result_preview": result_preview,
                    "result_summary": result_summary,
                    "duration_ms": duration_ms,
                    "full_function_name": f"{plugin_name}.{function_name}"
                },
                level=logging.INFO
            )

        def _log_failure(function_name: str, error: Exception, duration_ms: float):
            log_event(
                f"[Plugin Function Logger] Function failed with error",
                extra={
                    "plugin_name": plugin_name,
                    "function_name": function_name,
                    "duration_ms": duration_ms,
                    "error_message": str(error),
                    "full_function_name": f"{plugin_name}.{function_name}"
                },
                level=logging.ERROR
            )

        def _resolve_function_name(wrapper_func: Callable) -> str:
            return (
                getattr(wrapper_func, '__kernel_function_name__', None)
                or getattr(func, '__kernel_function_name__', None)
                or getattr(func, '__name__', 'unknown')
            )

        if is_async_callable:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                invocation_id = str(uuid.uuid4())
                function_name = _resolve_function_name(wrapper)
                _log_start(function_name)
                parameters = _build_parameters(args, kwargs)
                _log_parameters(function_name, parameters)
                log_plugin_invocation_started(
                    plugin_name=plugin_name,
                    function_name=function_name,
                    parameters=parameters,
                    invocation_id=invocation_id,
                )

                try:
                    result = await func(*args, **kwargs)
                    end_time = time.time()
                    duration_ms = (end_time - start_time) * 1000
                    _log_success(function_name, result, duration_ms)

                    log_plugin_invocation(
                        plugin_name=plugin_name,
                        function_name=function_name,
                        parameters=parameters,
                        result=result,
                        start_time=start_time,
                        end_time=end_time,
                        success=True,
                        invocation_id=invocation_id,
                    )

                    return result

                except Exception as e:
                    end_time = time.time()
                    duration_ms = (end_time - start_time) * 1000
                    _log_failure(function_name, e, duration_ms)

                    log_plugin_invocation(
                        plugin_name=plugin_name,
                        function_name=function_name,
                        parameters=parameters,
                        result=None,
                        start_time=start_time,
                        end_time=end_time,
                        success=False,
                        error_message=str(e),
                        invocation_id=invocation_id,
                    )

                    raise
        else:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                start_time = time.time()
                invocation_id = str(uuid.uuid4())
                function_name = _resolve_function_name(wrapper)
                _log_start(function_name)
                parameters = _build_parameters(args, kwargs)
                _log_parameters(function_name, parameters)
                log_plugin_invocation_started(
                    plugin_name=plugin_name,
                    function_name=function_name,
                    parameters=parameters,
                    invocation_id=invocation_id,
                )

                try:
                    result = func(*args, **kwargs)
                    if inspect.isawaitable(result):
                        log_event(
                            "[Plugin Function Logger] Awaitable returned from sync wrapper; deferring completion logging",
                            extra={
                                "plugin_name": plugin_name,
                                "function_name": function_name,
                                "full_function_name": f"{plugin_name}.{function_name}",
                            },
                            level=logging.WARNING,
                        )

                        async def _await_and_log(awaitable_result):
                            try:
                                awaited_value = await awaitable_result
                                end_time = time.time()
                                duration_ms = (end_time - start_time) * 1000
                                _log_success(function_name, awaited_value, duration_ms)
                                log_plugin_invocation(
                                    plugin_name=plugin_name,
                                    function_name=function_name,
                                    parameters=parameters,
                                    result=awaited_value,
                                    start_time=start_time,
                                    end_time=end_time,
                                    success=True,
                                    invocation_id=invocation_id,
                                )
                                return awaited_value
                            except Exception as await_error:
                                end_time = time.time()
                                duration_ms = (end_time - start_time) * 1000
                                _log_failure(function_name, await_error, duration_ms)
                                log_plugin_invocation(
                                    plugin_name=plugin_name,
                                    function_name=function_name,
                                    parameters=parameters,
                                    result=None,
                                    start_time=start_time,
                                    end_time=end_time,
                                    success=False,
                                    error_message=str(await_error),
                                    invocation_id=invocation_id,
                                )
                                raise

                        return _await_and_log(result)

                    end_time = time.time()
                    duration_ms = (end_time - start_time) * 1000
                    _log_success(function_name, result, duration_ms)

                    log_plugin_invocation(
                        plugin_name=plugin_name,
                        function_name=function_name,
                        parameters=parameters,
                        result=result,
                        start_time=start_time,
                        end_time=end_time,
                        success=True,
                        invocation_id=invocation_id,
                    )

                    return result

                except Exception as e:
                    end_time = time.time()
                    duration_ms = (end_time - start_time) * 1000
                    _log_failure(function_name, e, duration_ms)

                    log_plugin_invocation(
                        plugin_name=plugin_name,
                        function_name=function_name,
                        parameters=parameters,
                        result=None,
                        start_time=start_time,
                        end_time=end_time,
                        success=False,
                        error_message=str(e),
                        invocation_id=invocation_id,
                    )

                    raise

        setattr(wrapper, '__plugin_invocation_logger_wrapped__', True)

        return wrapper
    return decorator


def wrap_kernel_function(original_func: Callable, plugin_name: str) -> Callable:
    """Wrap a kernel function to add logging."""
    return plugin_function_logger(plugin_name)(original_func)


def auto_wrap_plugin_functions(plugin_instance, plugin_name: str):
    """Automatically wrap all kernel_function decorated methods in a plugin instance."""
    for attr_name in dir(plugin_instance):
        if attr_name.startswith('_'):
            continue

        attr = getattr(plugin_instance, attr_name)

        # Check if it's a method with the kernel_function decorator
        if not callable(attr):
            continue

        if getattr(attr, '__plugin_invocation_logger_wrapped__', False):
            continue

        if getattr(attr, '__kernel_function__', False) or getattr(attr, '__sk_function__', False):
            # Wrap the method
            wrapped_method = plugin_function_logger(plugin_name)(attr)
            object.__setattr__(plugin_instance, attr_name, wrapped_method)

    return plugin_instance
