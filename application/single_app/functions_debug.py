# functions_debug.py
#
from app_settings_cache import get_settings_cache

def debug_print(message):
    """
    Print debug message only if debug logging is enabled in settings.
    
    Args:
        message (str): The debug message to print
    """
    try:
        cache = get_settings_cache()
        if cache and cache.get('enable_debug_logging', False):
            print(f"DEBUG: {message}")

    except Exception:
        # If there's any error getting settings, don't print debug messages
        # This prevents crashes in case of configuration issues
        pass

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