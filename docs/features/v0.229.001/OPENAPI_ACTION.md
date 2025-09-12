# OpenAPI Action/Plugin Documentation

**Version Implemented:** 0.229.001

This OpenAPI Semantic Kernel Action/Plugin allows you to expose any OpenAPI-compliant API as Semantic Kernel plugin functions. The plugin has been updated to be completely configurable - you provide your own OpenAPI specification file, base URL, and authentication details.

## Key Changes from Original

- **No longer hardcoded**: Removed dependency on SimpleChat's OpenAPI specification
- **User-configurable**: Users must provide their own OpenAPI spec file and API details
- **Flexible authentication**: Supports multiple authentication types
- **Better error handling**: Validates inputs and provides clear error messages
- **Multiple file formats**: Supports both YAML and JSON OpenAPI specifications
- **Secure file uploads**: Comprehensive security validation for uploaded OpenAPI specs
- **Multiple source types**: Supports file upload and URL download
- **Web UI integration**: Full modal interface for configuration through the web application

## Installation

No additional dependencies beyond what's already in the project. The plugin uses:
- `yaml` for YAML parsing
- `json` for JSON parsing
- `semantic_kernel` for plugin functionality
- `requests` for URL-based spec downloads
- `re` for security pattern matching

## Configuration Methods

The OpenAPI plugin can be configured in three ways:

### 1. Through Web UI (Recommended)
Use the plugin configuration modal in the web application to:
- Upload OpenAPI specification files (with security validation)
- Download specs from URLs (with security checks)
- Configure authentication settings
- Test and validate configurations before saving

### 2. File Upload via API
```python
# Upload via the secure API endpoint
POST /api/openapi/upload
Content-Type: multipart/form-data
# File is automatically validated for security threats
```

### 3. Direct Code Usage (Advanced)
```python
from openapi_plugin_factory import OpenApiPluginFactory

# Create from configuration
plugin = OpenApiPluginFactory.create_from_config({
    'openapi_source_type': 'file',  # or 'url'
    'openapi_file_id': 'uploaded_file_id',
    'base_url': 'https://api.example.com',
    'auth': {'type': 'bearer', 'token': 'your-token'}
})
```

## Usage

### Basic Setup

```python
from openapi_plugin import OpenApiPlugin

# Initialize with your API details
plugin = OpenApiPlugin(
    openapi_spec_path="/path/to/your/openapi.yaml",  # Required
    base_url="https://api.example.com",              # Required
    auth={                                           # Optional
        "type": "api_key",
        "location": "header", 
        "name": "X-API-Key",
        "value": "your-api-key"
    }
)
```

### Required Parameters

1. **openapi_spec_path**: Path to your OpenAPI specification file (YAML or JSON)
2. **base_url**: Base URL of your API (e.g., "https://api.example.com")

### Optional Parameters

3. **auth**: Authentication configuration (see authentication section below)
4. **manifest**: Additional manifest configuration

## Authentication Types

The plugin supports several authentication methods:

### API Key Authentication

```python
# Header-based API key
auth = {
    "type": "api_key",
    "location": "header",
    "name": "X-API-Key",
    "value": "your-api-key-here"
}

# Query parameter API key
auth = {
    "type": "api_key", 
    "location": "query",
    "name": "api_key",
    "value": "your-api-key-here"
}
```

### Bearer Token

```python
auth = {
    "type": "bearer",
    "token": "your-bearer-token-here"
}
```

### Basic Authentication

```python
auth = {
    "type": "basic",
    "username": "your-username",
    "password": "your-password"
}
```

### OAuth2

```python
auth = {
    "type": "oauth2",
    "access_token": "your-oauth2-access-token"
}
```

### No Authentication

```python
# Simply omit the auth parameter
plugin = OpenApiPlugin(
    openapi_spec_path="/path/to/your/openapi.yaml",
    base_url="https://api.example.com"
)
```

## Security Features

The OpenAPI plugin includes comprehensive security validation to prevent malicious attacks:

### File Upload Security
- **File size limits**: Maximum 5MB per upload
- **Content type validation**: Only YAML/JSON files accepted
- **Malicious pattern detection**: Scans for:
  - Script injection attempts (`<script>`, `javascript:`, etc.)
  - File system access patterns (`../`, `file://`, `/etc/passwd`, etc.)
  - Network exploitation attempts (`localhost`, `127.0.0.1`, private IPs)
  - Code execution patterns (`eval()`, `exec()`, `import os`, etc.)
  - SQL injection attempts (`DROP TABLE`, `UNION SELECT`, etc.)

### URL Security
- **HTTPS enforcement**: Recommends secure connections
- **Private network blocking**: Prevents access to:
  - Localhost (`127.0.0.1`, `::1`)
  - Private IP ranges (`10.x.x.x`, `192.168.x.x`, `172.16-31.x.x`)
  - Link-local addresses (`169.254.x.x`)
- **Content validation**: Downloaded content undergoes same security checks as uploads

### Structure Validation
- **Nesting depth limits**: Prevents DoS attacks via deeply nested objects
- **OpenAPI format validation**: Ensures valid OpenAPI 2.0/3.0 structure
- **Required field checks**: Validates essential OpenAPI components

### Threat Categories Detected
1. **Script Injection**: HTML/JavaScript injection attempts
2. **File System Access**: Path traversal and file system exploitation
3. **Network Exploitation**: Internal network access attempts  
4. **Code Execution**: Attempts to execute arbitrary code
5. **SQL Injection**: Database manipulation attempts
6. **DoS Attacks**: Resource exhaustion via complex structures

## File Formats Supported

- **YAML**: `.yaml`, `.yml` extensions
- **JSON**: `.json` extension
- **Auto-detection**: If extension is unclear, tries YAML first, then JSON

## Plugin Methods

### Core Methods

- `call_operation(operation_id, **kwargs)`: Call any API operation by its operation ID
- `get_available_operations()`: List all available operations
- `get_operation_details(operation_id)`: Get details for a specific operation
- `get_functions()`: Get list of available function names

### Utility Methods

- `create_example_auth_configs()`: Get example authentication configurations
- `display_name`: Property showing the API title
- `metadata`: Property with plugin metadata including API info

## Example Usage

### Web UI Configuration (Recommended)
1. Open the plugin configuration modal
2. Select "OpenAPI" as plugin type
3. Choose your specification source:
   - **Upload File**: Drag & drop or select your OpenAPI file
   - **From URL**: Enter URL to your OpenAPI specification
4. Configure authentication settings
5. Test and save configuration

### Programmatic Usage
```python
# Using the factory (recommended for dynamic creation)
from openapi_plugin_factory import OpenApiPluginFactory

config = {
    'openapi_source_type': 'file',
    'openapi_file_id': 'abc123',  # From upload endpoint
    'base_url': 'https://api.myservice.com',
    'auth': {'type': 'bearer', 'token': 'your-token'}
}

plugin = OpenApiPluginFactory.create_from_config(config)

# Direct usage (if you have a local file)
from openapi_plugin import OpenApiPlugin

plugin = OpenApiPlugin(
    openapi_spec_path="./my-api-spec.yaml",
    base_url="https://api.myservice.com",
    auth={"type": "bearer", "token": "abc123"}
)

# List available operations
operations = plugin.get_available_operations()
print(f"Found {len(operations)} operations")

# Call an operation
result = plugin.call_operation(
    operation_id="getUserById",
    user_id="12345"
)
```

## Error Handling

The plugin includes comprehensive error handling:

- **FileNotFoundError**: If OpenAPI spec file doesn't exist
- **ValueError**: If required parameters are missing or file format is invalid
- **YAMLError/JSONDecodeError**: If spec file is malformed
- **SecurityValidationError**: If uploaded file contains malicious content
- **URLSecurityError**: If URL points to forbidden locations (localhost, private networks)
- **FileSizeError**: If uploaded file exceeds 5MB limit

## API Endpoints

The system provides secure REST endpoints for OpenAPI file management:

### Upload OpenAPI Specification
```
POST /api/openapi/upload
Content-Type: multipart/form-data

Response: {
  "success": true,
  "file_id": "abc123",
  "api_info": {
    "title": "My API",
    "version": "1.0.0",
    "endpoints_count": 25
  }
}
```

### Validate OpenAPI URL
```
POST /api/openapi/validate-url
Content-Type: application/json
Body: {"url": "https://api.example.com/openapi.yaml"}

Response: {
  "success": true,
  "file_id": "def456",
  "api_info": {...}
}
```

### Download from URL
```
POST /api/openapi/download-from-url
Content-Type: application/json
Body: {"url": "https://api.example.com/openapi.yaml"}

Response: {
  "success": true,
  "file_id": "ghi789"
}
```

## Current Limitations

- The `call_operation` method currently returns a stub response
- Actual HTTP request implementation needs to be added
- Response parsing and error handling for HTTP calls needs implementation

## Future Enhancements

To make this plugin fully functional, the following would need to be implemented:

1. **HTTP Request Logic**: Actual HTTP calls using the auth configuration
2. **URL Construction**: Building full URLs with path and query parameters
3. **Response Handling**: Parsing and returning actual API responses
4. **Error Handling**: HTTP error codes and API-specific error handling
5. **Parameter Validation**: Validate required parameters before making calls

## Migration from Original

If you were using the original plugin that referenced SimpleChat's OpenAPI spec:

**Old way:**
```python
plugin = OpenApiPlugin()  # Used hardcoded SimpleChat spec
```

**New way:**
```python
plugin = OpenApiPlugin(
    openapi_spec_path="/path/to/your/openapi.yaml",
    base_url="https://your-api.com",
    auth={"type": "bearer", "token": "your-token"}
)
```
