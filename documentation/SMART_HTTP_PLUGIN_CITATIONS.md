# Smart HTTP Plugin Agent Citation Support

## Overview

The Smart HTTP Plugin now includes comprehensive agent citation support, enabling automatic tracking of all function calls for enhanced transparency and debugging. This feature allows agents to reference specific plugin operations and their results, providing users with detailed information about data sources and API interactions.

## Version Information

- **Version**: 0.228.006
- **Enhancement**: Agent citation support with function call tracking
- **Previous Version**: 0.228.005 (PDF URL support)

## Citation Features

### 1. Automatic Function Call Tracking

The plugin automatically tracks all function calls with comprehensive metadata:

- **Function Name**: Method called (e.g., `get_web_content`, `post_web_content`)
- **Parameters**: Input arguments including URLs and request bodies
- **Results**: Response content and processing outcomes
- **Timing**: Start time, end time, and duration in milliseconds
- **URLs**: Target URLs for all HTTP requests
- **Content Types**: Detected or specified content types
- **Error Handling**: Comprehensive error tracking and categorization

### 2. Rich Metadata Capture

Each function call captures detailed metadata for better citation display:

```json
{
  "name": "SmartHttp.get_web_content",
  "arguments": {"uri": "https://example.com/data.json"},
  "result": "JSON response content...",
  "start_time": 1694524800.123,
  "end_time": 1694524800.234,
  "url": "https://example.com/data.json",
  "function_name": "get_web_content",
  "duration_ms": 111.2,
  "result_summary": "JSON content (292 chars): {\"data\": \"value\"}...",
  "params_summary": "uri: https://example.com/data.json",
  "content_type": "application/json",
  "content_length": 292,
  "plugin_type": "SmartHttpPlugin"
}
```

### 3. Multi-Content-Type Support

Citations are optimized for different content types:

- **HTML Content**: Extracts page information and content summary
- **JSON Data**: Formats structured data with proper indentation
- **PDF Documents**: Includes page count and Document Intelligence processing details
- **Error Responses**: Captures error types and diagnostic information

### 4. Performance Tracking

All function calls include precise timing information:

- **Start/End Times**: Exact timestamps for operation boundaries
- **Duration**: Millisecond precision for performance analysis
- **Timeout Handling**: Specific tracking for timeout scenarios
- **Network Performance**: Insight into HTTP request/response times

## Technical Implementation

### Citation Data Structure

The plugin maintains a `function_calls` list that tracks all operations:

```python
class SmartHttpPlugin:
    def __init__(self, max_content_size: int = 75000, extract_text_only: bool = True):
        # ... other initialization ...
        
        # Track function calls for citations
        self.function_calls = []
```

### Function Call Tracking Method

The `_track_function_call` method captures comprehensive metadata:

```python
def _track_function_call(self, function_name: str, parameters: dict, result: str, 
                        call_start: float, url: str, content_type: str = "unknown"):
    """Track function call for citation purposes with enhanced details."""
    duration = time.time() - call_start
    
    # Extract and format result summary
    result_summary = self._format_result_summary(result, content_type)
    
    # Create comprehensive call data
    call_data = {
        "name": f"SmartHttp.{function_name}",
        "arguments": parameters,
        "result": result,
        "start_time": call_start,
        "end_time": time.time(),
        "url": url,
        "function_name": function_name,
        "duration_ms": round(duration * 1000, 2),
        "result_summary": result_summary[:300],
        "params_summary": self._format_params_summary(parameters),
        "content_type": content_type,
        "content_length": len(result) if isinstance(result, str) else 0,
        "plugin_type": "SmartHttpPlugin"
    }
    
    self.function_calls.append(call_data)
```

### Integration Points

Citation tracking is integrated at all function return points:

1. **Successful Operations**: Track URL, content type, and result
2. **Error Conditions**: Track error type, message, and context
3. **Timeout Scenarios**: Specific timeout tracking
4. **Content Processing**: Track PDF, HTML, and JSON processing

## Citation Categories

### Successful Operations

- **HTML Scraping**: `text/html` content with size and processing info
- **JSON APIs**: `application/json` with structured data formatting
- **PDF Processing**: `application/pdf` with Document Intelligence details
- **Plain Text**: `text/plain` for miscellaneous content types

### Error Cases

- **HTTP Errors**: Status codes and server responses
- **Network Timeouts**: `timeout` category for slow/unresponsive servers
- **Processing Errors**: `error` category for general exceptions
- **Content Size Errors**: Large content rejection handling

## Usage Examples

### Accessing Citation Data

```python
from semantic_kernel_plugins.smart_http_plugin import SmartHttpPlugin

plugin = SmartHttpPlugin()

# Make some requests
result1 = await plugin.get_web_content_async("https://api.example.com/data.json")
result2 = await plugin.get_web_content_async("https://example.com/document.pdf")

# Access citation data
for call in plugin.function_calls:
    print(f"Function: {call['name']}")
    print(f"URL: {call['url']}")
    print(f"Duration: {call['duration_ms']}ms")
    print(f"Content Type: {call['content_type']}")
    print(f"Result Summary: {call['result_summary']}")
    print("-" * 50)
```

### Citation Display Format

Citations provide rich context for agents and users:

```
📋 SmartHttp.get_web_content
🔗 https://api.example.com/data.json
📊 application/json (89.5ms, 292 chars)
📝 JSON content: {"userId": 1, "id": 1, "title": "sunt aut facere..."}
```

## Benefits

### For Agents

1. **Source Attribution**: Clear tracking of data sources and API calls
2. **Performance Insights**: Understanding of request timing and efficiency
3. **Error Diagnosis**: Detailed error context for debugging
4. **Content Awareness**: Knowledge of content types and processing methods

### For Users

1. **Transparency**: Visibility into what data sources were accessed
2. **Trust**: Verification of information sources and processing methods
3. **Debugging**: Clear insight into failed operations and their causes
4. **Performance**: Understanding of response times and content sizes

### For Developers

1. **Monitoring**: Comprehensive tracking of plugin usage patterns
2. **Optimization**: Performance data for improving efficiency
3. **Debugging**: Detailed logs for troubleshooting issues
4. **Analytics**: Usage statistics and content type distribution

## Integration with Agent Systems

The citation data integrates seamlessly with agent citation systems:

- **Consistent Format**: Compatible with OpenAPI and SQL plugin citation patterns
- **Rich Metadata**: Comprehensive information for citation display
- **Error Handling**: Graceful degradation for failed operations
- **Performance Data**: Timing information for operational insights

## Best Practices

### Citation Optimization

1. **Result Summarization**: Automatic truncation for display purposes
2. **Parameter Sanitization**: Safe handling of sensitive data in parameters
3. **Performance Tracking**: Minimal overhead for citation capture
4. **Memory Management**: Efficient storage of citation metadata

### Error Handling

1. **Comprehensive Coverage**: All error scenarios tracked
2. **Contextual Information**: Rich error context for debugging
3. **Graceful Degradation**: Citation failures don't impact core functionality
4. **Security Awareness**: Sensitive data protection in error messages

## Future Enhancements

Potential improvements for citation support:

1. **Citation Persistence**: Long-term storage of citation data
2. **Citation Analytics**: Statistical analysis of usage patterns
3. **Citation Filtering**: User-controlled citation detail levels
4. **Citation Export**: Export functionality for analysis tools
5. **Citation Aggregation**: Cross-plugin citation correlation

## Testing

Comprehensive test coverage validates citation functionality:

```bash
# Test citation support specifically
python functional_tests/test_smart_http_plugin_citations.py

# Test citations as part of comprehensive testing
python functional_tests/test_smart_http_plugin_content_management.py
```

## Compatibility

Citation support maintains full backward compatibility:

- **Existing Functionality**: No changes to core plugin behavior
- **Performance**: Minimal impact on operation speed
- **Memory Usage**: Efficient citation data storage
- **API Consistency**: Same function signatures and return values