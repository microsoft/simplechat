# Plugin Authentication Type Constraints

## Overview

SimpleChat now enforces authentication type constraints per plugin type. Different plugin types may support different authentication methods based on their requirements and the APIs they integrate with. This feature provides a structured way to define and retrieve allowed authentication types for each plugin type.

**Version Implemented:** v0.237.001

## Key Features

- **Per-Plugin Auth Types**: Each plugin type can define its own allowed authentication types
- **Schema-Based Defaults**: Falls back to global AuthType enum from plugin.schema.json
- **Definition File Overrides**: Plugin-specific definition files can restrict available auth types
- **API Endpoint**: RESTful endpoint to query allowed auth types for any plugin type

## How It Works

### Authentication Type Resolution

The system resolves allowed authentication types in this order:

1. **Check Plugin Definition File**: `{plugin_type}.definition.json`
   - If `allowedAuthTypes` array exists and is non-empty, use it
2. **Fallback to Global Schema**: `plugin.schema.json`
   - Use the `AuthType` enum from definitions

### API Endpoint

```
GET /api/plugins/{plugin_type}/auth-types
```

**Response:**
```json
{
  "allowedAuthTypes": ["none", "api_key", "oauth2", "basic"],
  "source": "definition"
}
```

**Response Fields:**
| Field | Description |
|-------|-------------|
| `allowedAuthTypes` | Array of allowed authentication type strings |
| `source` | Where the types came from: "definition" or "schema" |

## Configuration Files

### Plugin Schema (Global Defaults)

Location: `static/json/schemas/plugin.schema.json`

```json
{
  "definitions": {
    "AuthType": {
      "enum": ["none", "api_key", "oauth2", "basic", "bearer", "custom"]
    }
  }
}
```

### Plugin Definition Files (Per-Plugin Overrides)

Location: `static/json/schemas/{plugin_type}.definition.json`

Example for a plugin that only supports API key authentication:

```json
{
  "name": "weather_plugin",
  "displayName": "Weather API",
  "description": "Get weather information",
  "allowedAuthTypes": ["none", "api_key"]
}
```

## Technical Architecture

### Backend Implementation

Location: [route_backend_plugins.py](../../../../application/single_app/route_backend_plugins.py)

```python
@bpap.route('/api/plugins/<plugin_type>/auth-types', methods=['GET'])
@login_required
@user_required
def get_plugin_auth_types(plugin_type):
    """
    Returns allowed auth types for a plugin type. Uses definition file if present,
    otherwise falls back to AuthType enum in plugin.schema.json.
    """
    schema_dir = os.path.join(current_app.root_path, 'static', 'json', 'schemas')
    safe_type = re.sub(r'[^a-zA-Z0-9_]', '_', plugin_type).lower()

    # Try to load from plugin definition file
    definition_path = os.path.join(schema_dir, f'{safe_type}.definition.json')
    schema_path = os.path.join(schema_dir, 'plugin.schema.json')

    allowed_auth_types = []
    source = "schema"

    # Load defaults from schema
    try:
        with open(schema_path, 'r', encoding='utf-8') as schema_file:
            schema = json.load(schema_file)
        allowed_auth_types = (
            schema
            .get('definitions', {})
            .get('AuthType', {})
            .get('enum', [])
        )
    except Exception:
        allowed_auth_types = []

    # Override with definition file if present
    if os.path.exists(definition_path):
        try:
            with open(definition_path, 'r', encoding='utf-8') as definition_file:
                definition = json.load(definition_file)
            allowed_from_definition = definition.get('allowedAuthTypes')
            if isinstance(allowed_from_definition, list) and allowed_from_definition:
                allowed_auth_types = allowed_from_definition
                source = "definition"
        except Exception:
            pass

    return jsonify({
        "allowedAuthTypes": allowed_auth_types,
        "source": source
    })
```

### Security

- Plugin type is sanitized to prevent path traversal
- Only alphanumeric characters and underscores are allowed in plugin type names
- Endpoint requires user authentication

## Common Authentication Types

| Type | Description | Use Case |
|------|-------------|----------|
| `none` | No authentication required | Public APIs |
| `api_key` | API key in header or query | Most REST APIs |
| `oauth2` | OAuth 2.0 flow | Microsoft Graph, Google APIs |
| `basic` | Basic HTTP authentication | Legacy systems |
| `bearer` | Bearer token authentication | JWT-based APIs |
| `custom` | Custom authentication handler | Special requirements |

## Use Cases

### Restricting Auth for Internal Plugins

An internal plugin might only support specific authentication:

```json
{
  "name": "internal_hr_system",
  "allowedAuthTypes": ["oauth2"]
}
```

### Simple Public API Plugin

A public weather API might need no authentication:

```json
{
  "name": "public_weather",
  "allowedAuthTypes": ["none", "api_key"]
}
```

## Frontend Integration

The frontend can query auth types to:
1. Display only valid authentication options in plugin configuration UI
2. Validate user selections before saving
3. Show appropriate configuration fields based on auth type

Example usage:

```javascript
async function loadAuthTypes(pluginType) {
    const response = await fetch(`/api/plugins/${pluginType}/auth-types`);
    const data = await response.json();
    return data.allowedAuthTypes;
}
```

## Known Limitations

- Auth types must be predefined in the schema
- Custom auth implementations require additional plugin code
- Definition files must be manually created for each plugin type

## Related Features

- Plugin Management
- Action/Plugin Registration
- OpenAPI Plugin Integration
