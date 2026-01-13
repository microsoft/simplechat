# YAML OpenAPI Specification Support

**Feature implemented in version: 0.230.042**

## Overview

The swagger wrapper now supports generating OpenAPI specifications in both JSON and YAML formats, providing developers with flexible options for API documentation and integration.

## New Endpoints

### `/swagger.yaml`
- **Method**: GET
- **Authentication**: Required (login_required)
- **Content-Type**: `application/x-yaml`
- **Description**: Serves the complete OpenAPI 3.0.3 specification in YAML format
- **Features**:
  - Full caching support with TTL
  - Rate limiting protection
  - ETag-based client-side caching
  - Identical content to JSON version but human-readable format

### Enhanced `/swagger.json`
- **Method**: GET
- **Authentication**: Required (login_required)
- **Content-Type**: `application/json`
- **Description**: Existing JSON endpoint enhanced with improved caching
- **Features**:
  - Updated to work with new dual-format caching system
  - Maintains all existing functionality and performance

## UI Enhancements

### Format Selection Buttons
The interactive Swagger UI (`/swagger`) now includes convenient format selection buttons:

- **📄 JSON**: Direct download of JSON specification
- **📝 YAML**: Direct download of YAML specification  
- **📋 JSON URL**: Copy JSON endpoint URL to clipboard
- **📋 YAML URL**: Copy YAML endpoint URL to clipboard

### Button Features
- **Visual Feedback**: Buttons show "✅ Copied!" confirmation when URLs are copied
- **Accessibility**: Proper tooltips and keyboard navigation
- **Responsive Design**: Fixed positioning that works across different screen sizes

## Technical Implementation

### Caching System
- **Dual Format Support**: Separate cache entries for JSON (`*_json`) and YAML (`*_yaml`)
- **Format-Specific Keys**: Cache keys include format suffix to prevent conflicts
- **Unified TTL**: Both formats share the same 5-minute TTL
- **Memory Efficient**: YAML is generated on-demand and cached separately

### YAML Generation
- **Library**: Uses PyYAML 6.0.2 for reliable YAML generation
- **Configuration**:
  - `default_flow_style=False`: Produces readable block-style YAML
  - `sort_keys=False`: Preserves logical order of OpenAPI sections
  - `allow_unicode=True`: Supports international characters
  - `indent=2`: Standard 2-space indentation

### Cache Statistics
Enhanced cache statistics now include format-specific metrics:
```json
{
  "cached_specs": 2,
  "cache_ttl_seconds": 300,
  "rate_limit_per_minute": 30,
  "formats": {
    "json_cached": 1,
    "yaml_cached": 1,
    "supported_formats": ["json", "yaml"]
  }
}
```

## Usage Examples

### Direct Access
```bash
# Get JSON specification
curl -H "Authorization: Bearer <token>" http://localhost:5000/swagger.json

# Get YAML specification
curl -H "Authorization: Bearer <token>" http://localhost:5000/swagger.yaml
```

### Integration with Tools
```yaml
# Using YAML spec with OpenAPI Generator
openapi-generator-cli generate \
  -i http://localhost:5000/swagger.yaml \
  -g python-client \
  -o ./client-sdk
```

### Cache Management
```bash
# Clear cache for both formats
curl -X DELETE -H "Authorization: Bearer <token>" \
  http://localhost:5000/api/swagger/cache

# Force refresh of specific format
curl -H "Authorization: Bearer <token>" \
  "http://localhost:5000/swagger.yaml?refresh=true"
```

## Benefits

### Developer Experience
- **Human Readable**: YAML format is easier to read and edit manually
- **Version Control**: YAML diffs are more readable in Git
- **Tool Compatibility**: Many OpenAPI tools prefer YAML input
- **Documentation**: YAML specs are often preferred for documentation

### Performance
- **Efficient Caching**: Both formats cached separately with identical performance
- **Rate Limiting**: Same protection against abuse for both endpoints
- **Client Caching**: ETag support for both formats reduces bandwidth

### Compatibility
- **Identical Content**: JSON and YAML versions contain exactly the same information
- **Round-trip Safe**: Generated YAML can be converted back to JSON without loss
- **Standard Compliant**: Follows OpenAPI 3.0.3 specification in both formats

## Configuration

### Required Dependencies
- `PyYAML >= 6.0.0` (already included in project dependencies)

### Settings
YAML generation is automatically enabled when swagger is enabled in admin settings:
```python
settings = get_settings()
if settings.get('enable_swagger', True):  # Enables both JSON and YAML
    # Both endpoints registered automatically
```

## Error Handling

### Rate Limiting
Both endpoints share the same rate limiting pool:
- **Limit**: 30 requests per minute per IP
- **Response**: 429 Too Many Requests with retry-after header
- **Scope**: Applies to both `/swagger.json` and `/swagger.yaml`

### Error Responses
YAML endpoint returns JSON for error responses to ensure proper error handling:
```yaml
# Normal YAML response
openapi: 3.0.3
info:
  title: SimpleChat API
  ...

# Error response (JSON format)
{
  "error": "Rate limit exceeded",
  "retry_after": 60
}
```

## Monitoring

### Cache Metrics
Monitor YAML adoption and performance through cache statistics:
- Track separate cache hit rates for JSON vs YAML
- Monitor format preferences in usage patterns
- Analyze cache efficiency by format

### Access Patterns
- JSON typically used by automated tools and clients
- YAML typically used by developers for manual inspection
- Both formats should show similar content but different usage patterns

## Future Enhancements

### Potential Improvements
- **Format Negotiation**: Support `Accept: application/x-yaml` headers
- **Compressed Responses**: Add gzip compression for both formats
- **Download Filenames**: Add proper `Content-Disposition` headers
- **Format Validation**: Add YAML schema validation

### Integration Opportunities
- **CI/CD**: Use YAML specs in automated testing pipelines
- **Documentation**: Generate static docs from YAML specs
- **Client Generation**: Automated SDK generation from YAML specs

## Testing

Comprehensive test suite validates:
- ✅ YAML generation and parsing
- ✅ Cache functionality for both formats
- ✅ UI enhancements and button functionality
- ✅ Content consistency between JSON and YAML
- ✅ Error handling and rate limiting

Run tests with:
```bash
python functional_tests/test_yaml_openapi_generation.py
```

## Security Considerations

### Authentication
- Both endpoints require authentication (same as JSON endpoint)
- No additional security vectors introduced
- Rate limiting protects against abuse of both formats

### Content Security
- YAML generation uses safe parsing methods
- No user input directly affects YAML structure
- Generated content is identical to JSON version (same security model)