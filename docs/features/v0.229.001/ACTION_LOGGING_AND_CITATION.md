# Semantic Kernel Action/Plugin Invocation Logging

**Version Implemented:** 0.229.001

This system provides comprehensive logging for all Semantic Kernel actions/plugin invocations, capturing function calls, parameters, results, and execution times before they're sent to the model.

## Features

- **Automatic Logging**: Automatically logs all plugin function invocations
- **Comprehensive Data**: Captures function name, parameters, results, execution time, and success/failure status
- **User Tracking**: Associates invocations with specific users
- **Application Insights Integration**: Logs to Azure Application Insights for centralized monitoring
- **Statistics**: Provides detailed usage statistics and analytics
- **API Access**: RESTful API endpoints for accessing logs and statistics
- **Error Handling**: Robust error handling that doesn't interfere with plugin functionality

## Components

### 1. Plugin Invocation Logger (`plugin_invocation_logger.py`)

The core logging system that captures and stores plugin invocations.

**Key Classes:**
- `PluginInvocation`: Data class representing a single plugin invocation
- `PluginInvocationLogger`: Main logger that handles storage and retrieval

**Key Functions:**
- `log_plugin_invocation()`: Log a single plugin invocation
- `plugin_function_logger()`: Decorator for automatic logging
- `get_plugin_logger()`: Get the global logger instance

### 2. Logged Plugin Loader (`logged_plugin_loader.py`)

Enhanced plugin loader that automatically wraps plugins with logging capabilities.

**Key Classes:**
- `LoggedPluginLoader`: Loads plugins with automatic logging integration

**Key Features:**
- Automatic wrapping of plugin functions
- Fallback to original loading method if needed
- Support for different plugin types (OpenAPI, Python, custom)

### 3. API Endpoints (`route_plugin_logging.py`)

RESTful API endpoints for accessing plugin logs and statistics.

**Available Endpoints:**
- `GET /api/plugins/invocations` - Get user's plugin invocations
- `GET /api/plugins/stats` - Get plugin usage statistics
- `GET /api/plugins/invocations/recent` - Get recent invocations (admin)
- `GET /api/plugins/invocations/<plugin_name>` - Get plugin-specific invocations
- `POST /api/plugins/clear-logs` - Clear logs (admin)
- `GET /api/plugins/export-logs` - Export user's logs

## Usage Examples

### 1. Using the Decorator Approach

```python
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger
from semantic_kernel.functions import kernel_function

class MyPlugin(BasePlugin):
    @plugin_function_logger("MyPlugin")
    @kernel_function(description="Sample function")
    def my_function(self, input_text: str) -> str:
        return f"Processed: {input_text}"
```

### 2. Manual Logging

```python
from semantic_kernel_plugins.plugin_invocation_logger import log_plugin_invocation
import time

def my_function(self, input_text: str) -> str:
    start_time = time.time()
    
    try:
        result = f"Processed: {input_text}"
        
        log_plugin_invocation(
            plugin_name="MyPlugin",
            function_name="my_function",
            parameters={"input_text": input_text},
            result=result,
            start_time=start_time,
            end_time=time.time(),
            success=True
        )
        
        return result
        
    except Exception as e:
        log_plugin_invocation(
            plugin_name="MyPlugin",
            function_name="my_function",
            parameters={"input_text": input_text},
            result=None,
            start_time=start_time,
            end_time=time.time(),
            success=False,
            error_message=str(e)
        )
        raise
```

### 3. Auto-Wrapping Existing Plugins

```python
from semantic_kernel_plugins.plugin_invocation_logger import auto_wrap_plugin_functions

# Wrap an existing plugin instance
plugin_instance = SomeExistingPlugin()
auto_wrap_plugin_functions(plugin_instance, "SomeExistingPlugin")
```

### 4. Using the Logged Plugin Loader

```python
from semantic_kernel_plugins.logged_plugin_loader import create_logged_plugin_loader

# Create logged plugin loader
logged_loader = create_logged_plugin_loader(kernel)

# Load plugins with automatic logging
manifests = [
    {
        "name": "MyPlugin",
        "type": "python",
        "module": "my_plugin",
        "class": "MyPlugin"
    }
]

results = logged_loader.load_multiple_plugins(manifests, user_id="user123")
```

## API Usage

### Get Plugin Invocations

```javascript
// Get user's recent plugin invocations
fetch('/api/plugins/invocations?limit=50')
  .then(response => response.json())
  .then(data => {
    console.log('Invocations:', data.invocations);
    console.log('Total count:', data.total_count);
  });
```

### Get Plugin Statistics

```javascript
// Get plugin usage statistics
fetch('/api/plugins/stats')
  .then(response => response.json())
  .then(data => {
    console.log('Overall stats:', data.overall_stats);
    console.log('User stats:', data.user_stats);
  });
```

### Get Plugin-Specific Invocations

```javascript
// Get invocations for a specific plugin
fetch('/api/plugins/invocations/OpenApiPlugin')
  .then(response => response.json())
  .then(data => {
    console.log('OpenAPI plugin invocations:', data.invocations);
  });
```

## Data Structure

### PluginInvocation

```python
@dataclass
class PluginInvocation:
    plugin_name: str              # Name of the plugin
    function_name: str            # Name of the function called
    parameters: Dict[str, Any]    # Function parameters
    result: Any                   # Function result
    start_time: float            # Start timestamp
    end_time: float              # End timestamp
    duration_ms: float           # Duration in milliseconds
    user_id: Optional[str]       # User who triggered the invocation
    timestamp: str               # ISO timestamp
    success: bool                # Whether the invocation succeeded
    error_message: Optional[str] # Error message if failed
```

## Configuration

### Enable/Disable Logging for Individual Plugins

```python
# For plugins that inherit from BasePlugin
plugin.enable_invocation_logging(True)   # Enable
plugin.enable_invocation_logging(False)  # Disable

# Check if logging is enabled
if plugin.is_logging_enabled():
    print("Logging is enabled")
```

### Integration with Application Insights

The system automatically integrates with your existing Application Insights setup:

- Logs are sent to Application Insights with structured data
- Custom properties include plugin name, function name, duration, success status
- Errors are logged with full exception details
- User context is preserved for tracking

## Monitoring and Analytics

### Real-time Monitoring

Use Application Insights queries to monitor plugin usage:

```kusto
// Query for plugin invocations
traces
| where message startswith "[Plugin Invocation]"
| extend plugin_name = customDimensions["plugin_name"]
| extend function_name = customDimensions["function_name"]
| extend duration_ms = todouble(customDimensions["duration_ms"])
| extend success = tobool(customDimensions["success"])
| summarize count(), avg(duration_ms), success_rate = avg(todouble(success)) by plugin_name, function_name
| order by count_ desc
```

### Performance Analysis

```kusto
// Query for slow plugin functions
traces
| where message startswith "[Plugin Invocation]"
| extend duration_ms = todouble(customDimensions["duration_ms"])
| where duration_ms > 1000  // Functions taking more than 1 second
| extend plugin_name = customDimensions["plugin_name"]
| extend function_name = customDimensions["function_name"]
| order by duration_ms desc
```

### Error Analysis

```kusto
// Query for plugin errors
traces
| where message startswith "[Plugin Invocation]"
| extend success = tobool(customDimensions["success"])
| where success == false
| extend plugin_name = customDimensions["plugin_name"]
| extend function_name = customDimensions["function_name"]
| extend error_message = customDimensions["error_message"]
| summarize error_count = count() by plugin_name, function_name, error_message
| order by error_count desc
```

## Best Practices

### 1. Parameter Sanitization

Large parameters are automatically truncated in logs to prevent performance issues:

```python
# Large strings are truncated to 200 characters
# Complex objects show type and length instead of full content
# Sensitive data should be manually redacted before logging
```

### 2. Performance Considerations

- Logging is designed to have minimal performance impact
- Large results are truncated for storage efficiency
- In-memory history is limited to 1000 invocations by default
- Use the API endpoints to retrieve logs instead of accessing them directly

### 3. Security

- User IDs are captured but no sensitive authentication data
- Parameters and results are sanitized to prevent data leaks
- API endpoints require authentication
- Consider implementing additional access controls for sensitive environments

### 4. Error Handling

- Logging failures don't interfere with plugin functionality
- Fallback mechanisms ensure plugins continue to work even if logging fails
- Comprehensive error logging helps with debugging

## Troubleshooting

### Common Issues

1. **Plugins not being logged**: Ensure plugins inherit from `BasePlugin` and logging is enabled
2. **Missing invocations**: Check that the plugin was loaded through the logged plugin loader
3. **Performance issues**: Reduce the history limit or implement log rotation
4. **API errors**: Verify authentication and user permissions

### Debug Mode

Enable debug logging to see detailed plugin loading information:

```python
import logging
logging.getLogger('semantic_kernel_plugins').setLevel(logging.DEBUG)
```

## Integration with Existing Codebase

This logging system is designed to integrate seamlessly with your existing Semantic Kernel setup:

1. **Minimal Changes**: Existing plugins continue to work without modification
2. **Backward Compatibility**: Original plugin loading still works as fallback
3. **Opt-in**: Logging can be enabled/disabled per plugin
4. **Non-intrusive**: Logging doesn't change plugin behavior or return values

The system is automatically enabled when plugins are loaded through the enhanced `load_plugins_for_kernel` function in `semantic_kernel_loader.py`.
