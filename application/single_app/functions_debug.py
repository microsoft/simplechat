# functions_debug.py
"""Backward-compatible debug logging shim.

The implementation now lives in functions_appinsights so new code can route all
logging behavior through a single module.
"""

from functions_appinsights import debug_print, is_debug_enabled

__all__ = ["debug_print", "is_debug_enabled"]