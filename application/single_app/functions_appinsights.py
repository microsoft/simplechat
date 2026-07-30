# functions_appinsights.py

import logging
import os
import re
import threading
import hashlib
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
LOG_CONTROL_CHAR_RE = re.compile(r"[\r\n\t]+")
LOG_RECORD_RESERVED_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}
LOGGER_EVENT_MESSAGE = "[SimpleChatLogEvent]"
LOGGER_DEBUG_MESSAGE = "[SimpleChatDebugTrace]"
LOGGER_FALLBACK_MESSAGE = "[SimpleChatLogFallback]"


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
    message_text = LOG_CONTROL_CHAR_RE.sub(" ", message_text)
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


def _safe_log_hash(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def _normalize_extra_key(key: Any) -> str:
    normalized_key = re.sub(r"[^A-Za-z0-9_]", "_", str(key or "").strip())[:80]
    normalized_key = normalized_key.strip("_") or "value"
    normalized_key = f"sc_{normalized_key}"
    if normalized_key in LOG_RECORD_RESERVED_ATTRS:
        normalized_key = f"sc_property_{normalized_key}"
    return normalized_key


def _logger_safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return _safe_log_hash(value)


def _build_logger_extra(
    message: Any,
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Build log-record properties without clear-text user-controlled values."""
    logger_extra: Dict[str, Any] = {
        "sc_message_hash": _safe_log_hash(message),
        "sc_message_length": len(str(message or "")),
    }

    if isinstance(extra, dict):
        for key, value in extra.items():
            normalized_key = _normalize_extra_key(key)
            if _is_sensitive_log_key(key):
                logger_extra[f"{normalized_key}_present"] = value is not None
                continue
            if isinstance(value, dict):
                logger_extra[f"{normalized_key}_count"] = len(value)
                logger_extra[f"{normalized_key}_hash"] = _safe_log_hash(value)
            elif isinstance(value, (list, tuple, set)):
                logger_extra[f"{normalized_key}_count"] = len(value)
                logger_extra[f"{normalized_key}_hash"] = _safe_log_hash(value)
            elif isinstance(value, str):
                logger_extra[f"{normalized_key}_hash"] = _safe_log_hash(value)
                logger_extra[f"{normalized_key}_length"] = len(value)
            else:
                logger_extra[normalized_key] = _logger_safe_scalar(value)

    return logger_extra


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

    return {}


def _emit_debug_message(
    settings: Dict[str, Any],
    message: str,
    category: str,
    flush: bool,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    if settings.get('enable_debug_logging', False):
        safe_message = sanitize_log_message(message)
        debug_msg = f"[DEBUG] [{category}]: {safe_message}"
        if details:
            safe_details = sanitize_log_properties(details)
            details_str = ", ".join(f"{key}={value}" for key, value in safe_details.items())
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

    trace_properties = sanitize_log_properties(dict(details or {}))
    trace_properties.setdefault('debug_tag', '[debug]')
    trace_properties.setdefault('debug_category', category)
    trace_message = sanitize_log_message(f"[debug] [{category}] {message}")
    logger_extra = _build_logger_extra(trace_message, trace_properties)

    try:
        # Use a child logger so DEBUG traces can flow to App Insights even when the
        # parent logger stays at INFO to avoid broad third-party debug noise.
        debug_logger.debug(LOGGER_DEBUG_MESSAGE, extra=logger_extra, stacklevel=3)
    except Exception:
        pass


def debug_print(message: Any, *args: Any, category: str = "INFO", **kwargs: Any) -> None:
    """Emit debug-only console output and forward a tagged App Insights trace when available."""
    flush = kwargs.pop('flush', False)
    details = sanitize_log_properties(kwargs) if kwargs else None
    formatted_message = sanitize_log_message(_format_message(message, args))
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
                logger.exception(
                    LOGGER_EVENT_MESSAGE,
                    extra=_build_logger_extra(formatted_message, safe_extra),
                    stacklevel=stacklevel,
                    stack_info=includeStack,
                    exc_info=True,
                )
                return
            else:
                # Fallback to standard logging with exc_info
                exc_info_to_use = True

        # Mirror structured events to stdout when debug logging is enabled.
        if cache and cache.get('enable_debug_logging', False):
            print(f"[DEBUG][Log] {formatted_message} -- {safe_extra if safe_extra else 'No Extra Dimensions'}")  # Debug print to console
        logger.log(
            level,
            LOGGER_EVENT_MESSAGE,
            extra=_build_logger_extra(formatted_message, safe_extra),
            stacklevel=stacklevel,
            stack_info=includeStack,
            exc_info=exc_info_to_use,
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

            fallback_logger.log(
                level,
                LOGGER_FALLBACK_MESSAGE,
                extra=_build_logger_extra(
                    formatted_message,
                    {
                        "fallback_error_type": type(e).__name__,
                        "fallback_error": sanitize_log_message(e),
                        "extra": safe_extra or {},
                    },
                ),
            )
        except Exception:
            # If even basic logging fails, print to console
            print(LOGGER_FALLBACK_MESSAGE)
            if safe_extra:
                print("[LOG] Extra dimensions were redacted for logging safety.")

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
