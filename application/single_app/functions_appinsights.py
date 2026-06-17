# functions_appinsights.py

import logging
import os
import re
import threading
from typing import Any, Dict, Optional, Tuple

from azure.monitor.opentelemetry import configure_azure_monitor
import app_settings_cache

# Singleton for the logger and Azure Monitor configuration
_appinsights_logger = None
_azure_monitor_configured = False
_logging_settings_load_state = threading.local()
REDACTED_LOG_VALUE = "***REDACTED***"
MAX_LOG_STRING_LENGTH = 8192
SENSITIVE_LOG_KEY_FRAGMENTS = (
    "accesstoken",
    "accountkey",
    "apikey",
    "authorization",
    "clientsecret",
    "connectionstring",
    "cookie",
    "credential",
    "password",
    "privatekey",
    "sas",
    "secret",
    "sharedaccesssignature",
    "subscriptionkey",
    "token",
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[-_]?key|access[-_]?token|client[-_]?secret|connection[-_]?string|password|secret|subscription[-_]?key|token|sig|signature)=([^&\s,;]+)"
)
AUTHORIZATION_VALUE_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")


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


def _normalize_log_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key or "").strip().lower())


def _is_sensitive_log_key(key: Any) -> bool:
    normalized_key = _normalize_log_key(key)
    if not normalized_key:
        return False
    return any(fragment in normalized_key for fragment in SENSITIVE_LOG_KEY_FRAGMENTS)


def sanitize_log_message(message: Any) -> str:
    """Redact secret-like values from log messages while preserving diagnostic text."""
    message_text = str(message)
    message_text = SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}={REDACTED_LOG_VALUE}",
        message_text,
    )
    message_text = AUTHORIZATION_VALUE_RE.sub(
        lambda match: f"{match.group(1)} {REDACTED_LOG_VALUE}",
        message_text,
    )
    if len(message_text) > MAX_LOG_STRING_LENGTH:
        return f"{message_text[:MAX_LOG_STRING_LENGTH]}... [truncated]"
    return message_text


def sanitize_log_properties(value: Any, _depth: int = 0) -> Any:
    """Return a copy of structured log properties with secret-bearing fields redacted."""
    if _depth > 8:
        return "[truncated: nested value too deep]"

    if value is None or isinstance(value, (int, float, bool)):
        return value

    if isinstance(value, str):
        return sanitize_log_message(value)

    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_log_key(key_text):
                sanitized[key_text] = REDACTED_LOG_VALUE
            else:
                sanitized[key_text] = sanitize_log_properties(item, _depth=_depth + 1)
        return sanitized

    if isinstance(value, (list, tuple, set)):
        return [sanitize_log_properties(item, _depth=_depth + 1) for item in value]

    return sanitize_log_message(value)


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


def _get_appinsights_debug_logger() -> Optional[logging.Logger]:
    """Return a logger that can emit DEBUG traces without widening parent logger levels."""
    base_logger = get_appinsights_logger()
    if not base_logger:
        return None

    base_name = base_logger.name or 'root'
    debug_logger_name = 'appinsights.debug' if base_name == 'root' else f"{base_name}.debug"
    debug_logger = logging.getLogger(debug_logger_name)
    debug_logger.setLevel(logging.DEBUG)
    return debug_logger


def _emit_appinsights_debug_trace(
    message: str,
    category: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Send a tagged debug trace to App Insights when Azure Monitor logging is configured."""
    if not _azure_monitor_configured:
        return

    debug_logger = _get_appinsights_debug_logger()
    if not debug_logger:
        return

    trace_properties = dict(details or {})
    trace_properties.setdefault('debug_tag', '[debug]')
    trace_properties.setdefault('debug_category', category)
    trace_message = f"[debug] [{category}] {message}"

    try:
        # Use a child logger so DEBUG traces can flow to App Insights even when the
        # parent logger stays at INFO to avoid broad third-party debug noise.
        if trace_properties:
            debug_logger.debug(trace_message, extra=trace_properties, stacklevel=3)
        else:
            debug_logger.debug(trace_message, stacklevel=3)
    except Exception:
        pass


def debug_print(message: Any, *args: Any, category: str = "INFO", **kwargs: Any) -> None:
    """Emit debug-only console output and forward a tagged App Insights trace when available."""
    flush = kwargs.pop('flush', False)
    details = kwargs or None
    formatted_message = _format_message(message, args)
    settings = _load_logging_settings()

    _emit_debug_message(settings, formatted_message, category, flush, details)
    if not settings.get('enable_debug_logging', False):
        return

    _emit_appinsights_debug_trace(formatted_message, category, details)


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
        formatted_message = sanitize_log_message(_format_message(message, message_args))
        safe_extra = sanitize_log_properties(extra) if extra else None
        cache = _load_logging_settings()

        if debug_only:
            _emit_debug_message(cache, formatted_message, category, flush, safe_extra)
            return

        try:
            cache = cache or None
        except Exception:
            cache = None

        # Get logger - use Azure Monitor logger if configured, otherwise standard logger
        logger = get_appinsights_logger()
        if not logger:
            print(f"[Log] {formatted_message} -- {safe_extra}")
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
                    print(f"[DEBUG][ERROR][Log] {formatted_message} -- {safe_extra if safe_extra else 'No Extra Dimensions'}")
                # Use logger.exception() for better exception capture in Application Insights
                logger.exception(formatted_message, extra=safe_extra, stacklevel=stacklevel, stack_info=includeStack, exc_info=True)
                return
            else:
                # Fallback to standard logging with exc_info
                exc_info_to_use = True

        # Mirror structured events to stdout when debug logging is enabled.
        if cache and cache.get('enable_debug_logging', False):
            print(f"[DEBUG][Log] {formatted_message} -- {safe_extra if safe_extra else 'No Extra Dimensions'}")  # Debug print to console
        if safe_extra:
            # For modern Azure Monitor, extra properties are automatically captured
            logger.log(
                level,
                formatted_message,
                extra=safe_extra,
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
            if safe_extra:
                fallback_message += f" | Extra: {safe_extra}"

            fallback_logger.log(level, fallback_message)
        except Exception:
            # If even basic logging fails, print to console
            print(f"[LOG] {formatted_message}")
            if safe_extra:
                print(f"[LOG] Extra: {safe_extra}")

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
