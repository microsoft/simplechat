# functions_debug.py
#
from app_settings_cache import get_settings_cache
from functions_settings import *


def _format_debug_message(message, args):
    """Support legacy printf-style debug calls while preserving plain strings."""
    message_text = str(message)
    if not args:
        return message_text

    try:
        return message_text % args
    except Exception:
        rendered_args = ", ".join(str(arg) for arg in args)
        return f"{message_text} {rendered_args}"


def _emit_debug_message(settings, message, category, flush, kwargs):
    if settings.get('enable_debug_logging', False):
        debug_msg = f"[DEBUG] [{category}]: {message}"
        if kwargs:
            kwargs_str = ", ".join(f"{k}={v}" for k, v in kwargs.items())
            debug_msg += f" ({kwargs_str})"
        print(debug_msg, flush=flush)


def debug_print(message, *args, category="INFO", **kwargs):
    """
    Print debug message only if debug logging is enabled in settings.
    
    Args:
        message (str): The debug message to print
        *args: Optional printf-style values applied to the message
        category (str): Optional category for the debug message
        **kwargs: Additional key-value pairs to include in debug output
    """
    flush = kwargs.pop('flush', False)
    formatted_message = _format_debug_message(message, args)

    try:
        cache = get_settings_cache()
        _emit_debug_message(cache, formatted_message, category, flush, kwargs)
    except Exception:
        settings = get_settings()
        _emit_debug_message(settings, formatted_message, category, flush, kwargs)


def is_debug_enabled():
    """
    Check if debug logging is enabled.
    
    Returns:
        bool: True if debug logging is enabled, False otherwise
    """
    try:
        cache = get_settings_cache()
        print(f"IS_DEBUG_ENABLED: {cache.get('enable_debug_logging', False)}")
        return cache and cache.get('enable_debug_logging', False)
    except Exception:
        return False