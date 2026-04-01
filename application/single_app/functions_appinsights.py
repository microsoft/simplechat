# functions_appinsights.py

import logging
import os
import threading
from typing import Any, Dict, Optional, Tuple

from azure.monitor.opentelemetry import configure_azure_monitor
import app_settings_cache

# Singleton for the logger and Azure Monitor configuration
_appinsights_logger = None
_azure_monitor_configured = False
_logging_settings_load_state = threading.local()


def _format_message(message: Any, message_args: Optional[Tuple[Any, ...]] = None) -> str:
    """Support legacy printf-style rendering while preserving plain strings."""
    message_text = str(message)
    if not message_args:
        return message_text

    try:
        return message_text % message_args
    except Exception:
        rendered_args = ", ".join(str(arg) for arg in message_args)
        return f"{message_text} {rendered_args}"


def _load_logging_settings() -> Dict[str, Any]:
    """Read cached settings first and fall back to live settings when needed."""
    if getattr(_logging_settings_load_state, 'active', False):
        return {}

    try:
        cache = app_settings_cache.get_settings_cache()
        if isinstance(cache, dict):
            return cache
    except Exception:
        pass

    try:
        from functions_settings import get_settings

        _logging_settings_load_state.active = True
        settings = get_settings()
        if isinstance(settings, dict):
            return settings
    except Exception:
        pass
    finally:
        _logging_settings_load_state.active = False

    return {}


def _emit_debug_message(
    settings: Dict[str, Any],
    message: str,
    category: str,
    flush: bool,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    if settings.get('enable_debug_logging', False):
        debug_msg = f"[DEBUG] [{category}]: {message}"
        if details:
            details_str = ", ".join(f"{key}={value}" for key, value in details.items())
            debug_msg += f" ({details_str})"
        print(debug_msg, flush=flush)


def is_debug_enabled() -> bool:
    """Check if debug logging is enabled in the current settings snapshot."""
    settings = _load_logging_settings()
    return bool(settings.get('enable_debug_logging', False))


def debug_print(message: Any, *args: Any, category: str = "INFO", **kwargs: Any) -> None:
    """Emit a debug-only console message using the unified logging implementation."""
    flush = kwargs.pop('flush', False)
    details = kwargs or None
    log_event(
        message,
        extra=details,
        debug_only=True,
        category=category,
        flush=flush,
        message_args=args,
    )


def get_appinsights_logger():
    """
    Return the logger configured for Azure Monitor, or None if not set up.
    """
    global _appinsights_logger
    if _appinsights_logger is not None:
        return _appinsights_logger
    
    # Return standard logger if Azure Monitor is configured
    if _azure_monitor_configured:
        return logging.getLogger('azure_monitor')
    
    return None

# --- Logging function for Application Insights ---
def log_event(
    message: Any,
    extra: Optional[Dict[str, Any]] = None,
    level: int = logging.INFO,
    includeStack: bool = False,
    stacklevel: int = 2,
    exceptionTraceback: bool = None,
    debug_only: bool = False,
    category: str = "INFO",
    flush: bool = False,
    message_args: Optional[Tuple[Any, ...]] = None,
) -> None:
    """
    Log an event to Azure Monitor Application Insights with flexible options.

    Args:
        message (str): The log message.
        extra (dict, optional): Custom properties to include as structured logging.
        level (int, optional): Logging level (e.g., logging.INFO, logging.ERROR, etc.).
        includeStack (bool, optional): If True, includes the current stack trace in the log.
        stacklevel (int, optional): How many levels up the stack to report as the source.
        exceptionTraceback (Any, optional): If set to True, includes exception traceback.
        debug_only (bool, optional): If True, emit only debug-gated console output.
        category (str, optional): Category label used for debug-only console output.
        flush (bool, optional): Flush console output immediately for debug-only output.
        message_args (tuple, optional): Optional printf-style formatting arguments.
    """
    try:
        formatted_message = _format_message(message, message_args)
        cache = _load_logging_settings()

        if debug_only:
            _emit_debug_message(cache, formatted_message, category, flush, extra)
            return

        try:
            cache = cache or None
        except Exception:
            cache = None

        # Get logger - use Azure Monitor logger if configured, otherwise standard logger
        logger = get_appinsights_logger()
        if not logger:
            print(f"[Log] {formatted_message} -- {extra}")
            logger = logging.getLogger('standard')
            if not logger.handlers:
                logger.addHandler(logging.StreamHandler())
                logger.setLevel(logging.INFO)

        # Enhanced exception handling for Application Insights
        # When exceptionTraceback=True, ensure we capture full exception context
        exc_info_to_use = exceptionTraceback

        # For ERROR level logs with exceptionTraceback=True, always log as exception
        if level >= logging.ERROR and exceptionTraceback:
            if logger and hasattr(logger, 'exception'):
                if cache and cache.get('enable_debug_logging', False):
                    print(f"[DEBUG][ERROR][Log] {formatted_message} -- {extra if extra else 'No Extra Dimensions'}")
                # Use logger.exception() for better exception capture in Application Insights
                logger.exception(formatted_message, extra=extra, stacklevel=stacklevel, stack_info=includeStack, exc_info=True)
                return
            else:
                # Fallback to standard logging with exc_info
                exc_info_to_use = True

        # Mirror structured events to stdout when debug logging is enabled.
        if cache and cache.get('enable_debug_logging', False):
            print(f"[DEBUG][Log] {formatted_message} -- {extra if extra else 'No Extra Dimensions'}")  # Debug print to console
        if extra:
            # For modern Azure Monitor, extra properties are automatically captured
            logger.log(
                level,
                formatted_message,
                extra=extra,
                stacklevel=stacklevel,
                stack_info=includeStack,
                exc_info=exc_info_to_use
            )
        else:
            logger.log(
                level,
                formatted_message,
                stacklevel=stacklevel,
                stack_info=includeStack,
                exc_info=exc_info_to_use
            )

        # For Azure Monitor, ensure exception-level logs are properly categorized
        if level >= logging.ERROR and _azure_monitor_configured:
            # Add a debug print to verify exception logging is working
            print(f"[Azure Monitor][ERROR] Exception logged: {formatted_message[:100]}...")

    except Exception as e:
        # Fallback to basic logging if anything fails
        try:
            fallback_logger = logging.getLogger('fallback')
            if not fallback_logger.handlers:
                fallback_logger.addHandler(logging.StreamHandler())
                fallback_logger.setLevel(logging.INFO)

            fallback_message = f"{formatted_message} | Original error: {str(e)}"
            if extra:
                fallback_message += f" | Extra: {extra}"

            fallback_logger.log(level, fallback_message)
        except Exception:
            # If even basic logging fails, print to console
            print(f"[LOG] {formatted_message}")
            if extra:
                print(f"[LOG] Extra: {extra}")

# --- Modern Azure Monitor Application Insights setup ---
def setup_appinsights_logging(settings):
    """
    Set up Azure Monitor Application Insights using the modern OpenTelemetry approach.
    This replaces the deprecated opencensus implementation.
    """
    global _appinsights_logger, _azure_monitor_configured
    
    try:
        enable_global = bool(settings and settings.get('enable_appinsights_global_logging', False))
    except Exception as e:
        print(f"[Azure Monitor] Could not check global logging setting: {e}")
        enable_global = False

    connectionString = os.environ.get('APPLICATIONINSIGHTS_CONNECTION_STRING')
    if not connectionString:
        print("[Azure Monitor] No connection string found - skipping Application Insights setup")
        return

    try:
        # Configure Azure Monitor with OpenTelemetry
        # This automatically sets up logging, tracing, and metrics
        configure_azure_monitor(
            connection_string=connectionString,
            enable_live_metrics=True,  # Enable live metrics for real-time monitoring
            disable_offline_storage=True,  # Disable offline storage to prevent issues
        )
        
        _azure_monitor_configured = True
        
        # Set up logger with proper exception handling
        if enable_global:
            logger = logging.getLogger()
            logger.setLevel(logging.INFO)
            _appinsights_logger = logger
            print("[Azure Monitor] Application Insights enabled globally")
        else:
            logger = logging.getLogger('azure_monitor')
            logger.setLevel(logging.INFO)
            _appinsights_logger = logger
            print("[Azure Monitor] Application Insights enabled for 'azure_monitor' logger")
            
        # Test that exception logging is working
        print("[Azure Monitor] Testing exception capture...")
        try:
            raise Exception("Test exception for Azure Monitor validation")
        except Exception as test_e:
            logger.error("Test exception logged successfully", exc_info=True)
            print("[Azure Monitor] Exception capture test completed")
    
    except Exception as e:
        print(f"[Azure Monitor] Failed to setup Application Insights: {e}")
        _azure_monitor_configured = False
        # Don't re-raise the exception, just continue without Application Insights
