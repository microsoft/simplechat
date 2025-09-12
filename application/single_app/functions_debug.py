# functions_debug.py

from functions_settings import get_settings

def debug_print(message):
    """
    Print debug message only if debug logging is enabled in settings.
    
    Args:
        message (str): The debug message to print
    """
    try:
        settings = get_settings()
        if settings and settings.get('enable_debug_logging', False):
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
        settings = get_settings()
        return settings and settings.get('enable_debug_logging', False)
    except Exception:
        return False