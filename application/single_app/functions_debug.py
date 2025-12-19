# functions_debug.py
#
from app_settings_cache import get_settings_cache
from functions_settings import *

def debug_print(message, category="INFO", **kwargs):
    """
    Print debug message only if debug logging is enabled in settings.
    
    Args:
        message (str): The debug message to print
        category (str): Optional category for the debug message
        **kwargs: Additional key-value pairs to include in debug output
    """
    #print(f"DEBUG_PRINT CALLED WITH MESSAGE: {message}")
    try:
        cache = get_settings_cache()
        if cache.get('enable_debug_logging', False):
            debug_msg = f"[DEBUG] [{category}]: {message}"
            if kwargs:
                kwargs_str = ", ".join(f"{k}={v}" for k, v in kwargs.items())
                debug_msg += f" ({kwargs_str})"
            print(debug_msg)
    except Exception:
        settings = get_settings()
        if settings.get('enable_debug_logging', False):
            debug_msg = f"[DEBUG] [{category}]: {message}"
            if kwargs:
                kwargs_str = ", ".join(f"{k}={v}" for k, v in kwargs.items())
                debug_msg += f" ({kwargs_str})"
            print(debug_msg)


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