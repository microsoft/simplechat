# SQL Plugin Configuration Validation Fix

**Version Implemented:** 0.229.001

## 📝 **Issue Summary**

Users were getting `400 BAD REQUEST` errors when trying to create SQL schema/query plugins through the workspace plugins interface. The error occurred because SQL plugins don't use endpoints like OpenAPI plugins do, but the plugin validation schema required all plugins to have a non-empty `endpoint` field.

## 🔧 **Root Cause**

1. **Plugin Schema Requirement**: The `plugin.schema.json` required all plugins to have an `endpoint` field
2. **SQL Plugin Behavior**: SQL plugins use connection strings in `additionalFields` rather than endpoints
3. **Frontend Configuration**: The frontend was correctly setting `endpoint = ''` for SQL plugins
4. **Backend Validation**: The backend validation was failing because empty endpoints didn't meet schema requirements

## ✅ **Solution Implemented**

### 1. **Backend Route Changes** (`route_backend_plugins.py`)

Modified the `/api/user/plugins` POST endpoint to handle SQL plugins specially:

```python
# Handle endpoint based on plugin type
plugin_type = plugin.get('type', '')
if plugin_type in ['sql_schema', 'sql_query']:
    # SQL plugins don't use endpoints, but schema validation requires one
    # Use a placeholder that indicates it's a SQL plugin
    plugin.setdefault('endpoint', f'sql://{plugin_type}')
else:
    # For other plugin types, require a real endpoint
    plugin.setdefault('endpoint', '')
```

### 2. **Validation Logic Enhancement** (`json_schema_validation.py`)

Enhanced the `validate_plugin()` function to:
- Handle SQL plugins specially during schema validation
- Add additional business logic validation for non-SQL plugins

```python
def validate_plugin(plugin):
    schema = load_schema('plugin.schema.json')
    
    # For SQL plugins, temporarily provide a dummy endpoint if none exists
    plugin_copy = plugin.copy()
    plugin_type = plugin_copy.get('type', '')
    
    if plugin_type in ['sql_schema', 'sql_query'] and not plugin_copy.get('endpoint'):
        plugin_copy['endpoint'] = f'sql://{plugin_type}'
    
    # First run schema validation
    validator = Draft7Validator(schema['definitions']['Plugin'])
    errors = sorted(validator.iter_errors(plugin_copy), key=lambda e: e.path)
    if errors:
        return '; '.join([e.message for e in errors])
    
    # Additional business logic validation
    # For non-SQL plugins, endpoint must not be empty
    if plugin_type not in ['sql_schema', 'sql_query']:
        endpoint = plugin.get('endpoint', '')
        if not endpoint or endpoint.strip() == '':
            return 'Non-SQL plugins must have a valid endpoint'
    
    return None
```

## 🧪 **Testing**

Created comprehensive tests to ensure the fix works correctly:

### 1. **SQL Plugin Validation Test** (`test_sql_plugin_validation_fix.py`)
- ✅ SQL schema plugins validate successfully
- ✅ SQL query plugins validate successfully  
- ✅ Backend processing sets appropriate placeholders
- ✅ OpenAPI plugins still require valid endpoints

### 2. **Plugin Compatibility Test** (`test_plugin_validation_compatibility.py`)
- ✅ OpenAPI plugins still validate correctly
- ✅ Generic plugins still validate correctly
- ✅ Empty endpoints are rejected for non-SQL plugins
- ✅ SQL plugins work without endpoint validation errors

## 🎯 **Plugin Types Supported**

| Plugin Type | Endpoint Required | Validation Behavior |
|-------------|------------------|-------------------|
| `openapi` | ✅ Yes | Must have valid HTTP/HTTPS endpoint |
| `custom`/`generic` | ✅ Yes | Must have valid endpoint URL |
| `sql_schema` | ❌ No | Uses placeholder `sql://sql_schema` |
| `sql_query` | ❌ No | Uses placeholder `sql://sql_query` |

## 🔍 **Key Benefits**

1. **✅ SQL Plugin Support**: Users can now create SQL plugins without validation errors
2. **✅ Backward Compatibility**: OpenAPI and other plugins continue to work exactly as before
3. **✅ Proper Validation**: Non-SQL plugins still require valid endpoints
4. **✅ Clear Error Messages**: Better error messages for invalid configurations
5. **✅ Type Safety**: Maintains schema validation for all required fields

## 📋 **Files Modified**

1. `route_backend_plugins.py` - Backend route handling
2. `json_schema_validation.py` - Validation logic
3. `config.py` - Version bump (0.226.082 → 0.226.083)
4. `functional_tests/test_sql_plugin_validation_fix.py` - SQL plugin test
5. `functional_tests/test_plugin_validation_compatibility.py` - Compatibility test

## 🚀 **User Impact**

- **Before**: SQL plugin creation would fail with `400 BAD REQUEST` error
- **After**: SQL plugins can be created successfully while maintaining validation for other plugin types

## 🔐 **Security Considerations**

- No security impact - the fix only affects validation logic
- SQL plugins still require proper authentication configuration
- Connection strings are still validated through existing mechanisms
- No changes to plugin execution or runtime behavior

## 📚 **Future Considerations**

- Consider creating separate schemas for different plugin types
- Add specific validation rules for SQL connection strings
- Enhance error messages to be more plugin-type specific
