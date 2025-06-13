# functions_appinsights.py

import logging
import os
from opencensus.ext.azure.log_exporter import AzureLogHandler, AzureEventHandler


# Singleton logger for Application Insights
_appinsights_logger = None

def get_appinsights_logger():
    global _appinsights_logger
    if _appinsights_logger is not None:
        return _appinsights_logger
    connectionString = os.environ.get('APPLICATIONINSIGHTS_CONNECTION_STRING')
    if not connectionString:
        return None
    logger = logging.getLogger('appinsights')
    logger.setLevel(logging.INFO)
    if not any(isinstance(h, AzureLogHandler) for h in logger.handlers):
        logger.addHandler(AzureLogHandler(connection_string=connectionString))
    _appinsights_logger = logger
    return logger

def log_event(
    message: str,
    extra: dict = None,
    level: int = logging.INFO,
    includeStack: bool = False,
    stacklevel: int = 2,
    exceptionTraceback = None
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
