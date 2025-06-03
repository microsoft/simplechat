# functions_appinsights.py

import logging
import os
import threading
from opencensus.ext.azure.log_exporter import AzureLogHandler, AzureEventHandler

# Singleton for the logger and handler
_appinsights_logger = None
_appinsights_handler = None

def get_appinsights_logger():
    """
    Return the logger (root or 'appinsights') that has the AzureLogHandler attached, or None if not set up.
    This will return the logger set up by setup_appinsights_logging, or the situational logger if set up directly.
    """
    global _appinsights_logger
    if _appinsights_logger is not None:
        return _appinsights_logger
    # Try to find a logger with an AzureLogHandler
    for logger_name in ('appinsights', ''):
        logger = logging.getLogger(logger_name)
        for h in logger.handlers:
            if isinstance(h, AzureLogHandler):
                _appinsights_logger = logger
                return logger
    return None

# --- Logging function for Application Insights ---
def log_event(
    message: str,
    extra: dict = None,
    level: int = logging.INFO,
    includeStack: bool = False,
    stacklevel: int = 2,
    exceptionTraceback: bool = None
) -> None:
    """
    Log an event to Application Insights with flexible options.

    Args:
        message (str): The log message.
        extra (dict, optional): Custom properties to include in Application Insights as custom_dimensions.
        level (int, optional): Logging level (e.g., logging.INFO, logging.ERROR, etc.).
        includeStack (bool, optional): If True, includes the current stack trace in the log (even if not in an exception).
        stacklevel (int, optional): How many levels up the stack to report as the source of the log (default 2). Increase if using wrappers.
        exceptionTraceback (Any, optional): If set to True (e.g., exc_info=True or an exception tuple), includes exception traceback in the log.

    Notes:
        - Use includeStack=True to always include a stack trace, even outside of exceptions.
        - Use stacklevel to control which caller is reported as the log source (2 = immediate caller, 3 = caller's caller, etc.).
        - Use exceptionTraceback to attach exception info (set to True inside except blocks for full traceback).
    """
    logger = get_appinsights_logger()
    if logger:
        # Ensure custom properties are sent as custom_dimensions for AzureLogHandler
        logger.log(
            level,
            message,
            extra={"custom_dimensions": extra or {}},
            stacklevel=stacklevel,
            stack_info=includeStack,
            exc_info=exceptionTraceback
        )

# --- Global Application Insights logging setup ---
def setup_appinsights_logging(settings):
    """
    Set up Application Insights logging, either globally (root logger) or situationally ('appinsights' logger),
    based on the enable_appinsights_global_logging setting. Only one handler is created and attached.
    """
    global _appinsights_logger, _appinsights_handler
    try:
        enable_global = bool(settings and settings.get('enable_appinsights_global_logging', False))
    except Exception as e:
        print(f"[AppInsights] Could not check global logging setting: {e}")
        enable_global = False

    connectionString = os.environ.get('APPLICATIONINSIGHTS_CONNECTION_STRING')
    if not connectionString:
        return

    # Remove any existing AzureLogHandler from both root and 'appinsights' loggers
    for logger_name in ('', 'appinsights'):
        logger = logging.getLogger(logger_name)
        for h in list(logger.handlers):
            if isinstance(h, AzureLogHandler):
                logger.removeHandler(h)

    handler = AzureLogHandler(connection_string=connectionString)
    handler.lock = threading.RLock()
    _appinsights_handler = handler

    if enable_global:
        logger = logging.getLogger()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        _appinsights_logger = logger
    else:
        logger = logging.getLogger('appinsights')
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        _appinsights_logger = logger
