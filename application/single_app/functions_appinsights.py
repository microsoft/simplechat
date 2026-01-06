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
    
    Configures OpenTelemetry settings based on admin settings:
    - OTEL_SERVICE_NAME: Service name for telemetry
    - OTEL_TRACES_SAMPLER: Sampling strategy for traces
    - OTEL_TRACES_SAMPLER_ARG: Sampling ratio (0.0 to 1.0)
    - OTEL_PYTHON_FLASK_EXCLUDED_URLS: URLs to exclude from instrumentation
    - OTEL_PYTHON_DISABLED_INSTRUMENTATIONS: Instrumentations to disable
    - OTEL_LOGS_EXPORTER: Where to export logs
    - OTEL_METRICS_EXPORTER: Where to export metrics
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
        # Apply OpenTelemetry configuration from settings to environment variables
        # These must be set before calling configure_azure_monitor()
        
        # Service Name - defaults to "simplechat"
        otel_service_name = settings.get('otel_service_name', 'simplechat') if settings else 'simplechat'
        if otel_service_name:
            os.environ['OTEL_SERVICE_NAME'] = str(otel_service_name)
            print(f"[Azure Monitor] OTEL_SERVICE_NAME set to: {otel_service_name}")
        
        # Traces Sampler - defaults to "parentbased_always_on"
        otel_traces_sampler = settings.get('otel_traces_sampler', 'parentbased_always_on') if settings else 'parentbased_always_on'
        if otel_traces_sampler:
            os.environ['OTEL_TRACES_SAMPLER'] = str(otel_traces_sampler)
            print(f"[Azure Monitor] OTEL_TRACES_SAMPLER set to: {otel_traces_sampler}")
        
        # Traces Sampler Argument - defaults to "1.0" (100%)
        otel_traces_sampler_arg = settings.get('otel_traces_sampler_arg', '1.0') if settings else '1.0'
        if otel_traces_sampler_arg:
            os.environ['OTEL_TRACES_SAMPLER_ARG'] = str(otel_traces_sampler_arg)
            print(f"[Azure Monitor] OTEL_TRACES_SAMPLER_ARG set to: {otel_traces_sampler_arg}")
        
        # Flask Excluded URLs - defaults to health check endpoints
        otel_flask_excluded_urls = settings.get('otel_flask_excluded_urls', 'healthcheck,/health,/external/health') if settings else 'healthcheck,/health,/external/health'
        if otel_flask_excluded_urls:
            os.environ['OTEL_PYTHON_FLASK_EXCLUDED_URLS'] = str(otel_flask_excluded_urls)
            print(f"[Azure Monitor] OTEL_PYTHON_FLASK_EXCLUDED_URLS set to: {otel_flask_excluded_urls}")
        
        # Disabled Instrumentations - defaults to empty (all enabled)
        otel_disabled_instrumentations = settings.get('otel_disabled_instrumentations', '') if settings else ''
        if otel_disabled_instrumentations:
            os.environ['OTEL_PYTHON_DISABLED_INSTRUMENTATIONS'] = str(otel_disabled_instrumentations)
            print(f"[Azure Monitor] OTEL_PYTHON_DISABLED_INSTRUMENTATIONS set to: {otel_disabled_instrumentations}")
        
        # Logs Exporter - defaults to "console,otlp"
        otel_logs_exporter = settings.get('otel_logs_exporter', 'console,otlp') if settings else 'console,otlp'
        if otel_logs_exporter:
            os.environ['OTEL_LOGS_EXPORTER'] = str(otel_logs_exporter)
            print(f"[Azure Monitor] OTEL_LOGS_EXPORTER set to: {otel_logs_exporter}")
        
        # Metrics Exporter - defaults to "otlp"
        otel_metrics_exporter = settings.get('otel_metrics_exporter', 'otlp') if settings else 'otlp'
        if otel_metrics_exporter:
            os.environ['OTEL_METRICS_EXPORTER'] = str(otel_metrics_exporter)
            print(f"[Azure Monitor] OTEL_METRICS_EXPORTER set to: {otel_metrics_exporter}")
        
        # Enable Live Metrics - defaults to True
        enable_live_metrics = settings.get('otel_enable_live_metrics', True) if settings else True
        
        # Configure Azure Monitor with OpenTelemetry
        # This automatically sets up logging, tracing, and metrics
        configure_azure_monitor(
            connection_string=connectionString,
            enable_live_metrics=bool(enable_live_metrics),
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
