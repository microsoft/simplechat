# functions_appinsights.py

import logging
import os
import threading
from azure.monitor.opentelemetry import configure_azure_monitor

# Singleton for the logger and Azure Monitor configuration
_appinsights_logger = None
_azure_monitor_configured = False

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
    message: str,
    extra: dict = None,
    level: int = logging.INFO,
    includeStack: bool = False,
    stacklevel: int = 2,
    exceptionTraceback: bool = None
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
    """
    try:
        # Get logger - use Azure Monitor logger if configured, otherwise standard logger
        logger = get_appinsights_logger()
        if not logger:
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
                # Use logger.exception() for better exception capture in Application Insights
                logger.exception(message, extra=extra, stacklevel=stacklevel)
                return
            else:
                # Fallback to standard logging with exc_info
                exc_info_to_use = True
        
        # Format message with extra properties for structured logging
        if extra:
            # For modern Azure Monitor, extra properties are automatically captured
            logger.log(
                level,
                message,
                extra=extra,
                stacklevel=stacklevel,
                stack_info=includeStack,
                exc_info=exc_info_to_use
            )
        else:
            logger.log(
                level,
                message,
                stacklevel=stacklevel,
                stack_info=includeStack,
                exc_info=exc_info_to_use
            )
            
        # For Azure Monitor, ensure exception-level logs are properly categorized
        if level >= logging.ERROR and _azure_monitor_configured:
            # Add a debug print to verify exception logging is working
            print(f"[Azure Monitor] Exception logged: {message[:100]}...")
            
    except Exception as e:
        # Fallback to basic logging if anything fails
        try:
            fallback_logger = logging.getLogger('fallback')
            if not fallback_logger.handlers:
                fallback_logger.addHandler(logging.StreamHandler())
                fallback_logger.setLevel(logging.INFO)
            
            fallback_message = f"{message} | Original error: {str(e)}"
            if extra:
                fallback_message += f" | Extra: {extra}"
            
            fallback_logger.log(level, fallback_message)
        except:
            # If even basic logging fails, print to console
            print(f"[LOG] {message}")
            if extra:
                print(f"[LOG] Extra: {extra}")

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
