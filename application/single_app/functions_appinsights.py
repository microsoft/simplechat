# functions_appinsights.py

import logging
import os
from opencensus.ext.azure.log_exporter import AzureLogHandler

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

def log_event(message, extra=None, level=logging.INFO):
    logger = get_appinsights_logger()
    if logger:
        # Ensure custom properties are sent as custom_dimensions for AzureLogHandler
        logger.log(level, message, extra={"custom_dimensions": extra or {}}, stacklevel=2)
