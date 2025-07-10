
# filename: functions_plugins.py
import os
import json
import jsonschema

def load_plugin_schema(plugin_type, schema_dir):
    """
    Loads the JSON schema for the given plugin type from the schema_dir.
    Returns the schema dict, or None if not found.
    """
    # Accept both log_analytics_plugin and log-analytics-plugin naming
    # Accept both log_analytics_plugin and log-analytics-plugin naming, and nested keys
    base_types = [plugin_type, f"{plugin_type}_plugin"]
    candidates = []
    for base in base_types:
        candidates.extend([
            f"{base}.additional_settings.schema.json",
            f"{base}.metadata.schema.json",
            f"{base}.schema.json",
        ])
    for fname in candidates:
        path = os.path.join(schema_dir, fname)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    return None

def get_default_for_schema_property(prop_schema):
    """
    Given a property schema dict, return a default value or placeholder.
    """
    if 'default' in prop_schema:
        return prop_schema['default']
    if 'enum' in prop_schema:
        # Return pipe-separated enum values as a string
        return '|'.join(str(e) for e in prop_schema['enum'])
    if prop_schema.get('type') == 'string':
        return prop_schema.get('description', '')
    if prop_schema.get('type') == 'array':
        return []
    if prop_schema.get('type') == 'object':
        return {}
    if prop_schema.get('type') == 'boolean':
        return False
    if prop_schema.get('type') == 'number' or prop_schema.get('type') == 'integer':
        return 0
    return None

def merge_settings_with_schema(current, schema):
    """
    Recursively merge current settings with schema defaults, ensuring all required fields are present.
    """
    if not schema or 'properties' not in schema:
        return current or {}
    # Clone all fields from current
    merged = dict(current) if current else {}

    required = schema.get('required', [])
    for key in required:
        prop_schema = schema['properties'].get(key)
        if prop_schema is None:
            continue
        # Only add missing required fields
        if key not in merged or merged[key] in [None, '', [], {}]:
            if 'default' in prop_schema:
                merged[key] = prop_schema['default']
            elif 'enum' in prop_schema:
                # Join all enum options with | for new/empty fields
                merged[key] = '|'.join(str(e) for e in prop_schema['enum']) if prop_schema['enum'] else None
            elif 'description' in prop_schema:
                merged[key] = prop_schema['description']
            elif prop_schema.get('type') == 'object':
                merged[key] = merge_settings_with_schema({}, prop_schema)
            elif prop_schema.get('type') == 'array':
                merged[key] = []
            elif prop_schema.get('type') == 'boolean':
                merged[key] = False
            elif prop_schema.get('type') == 'number' or prop_schema.get('type') == 'integer':
                merged[key] = 0
            else:
                merged[key] = None
        else:
            # If it's an object, recurse to fill missing subfields
            if prop_schema.get('type') == 'object' and isinstance(merged[key], dict):
                merged[key] = merge_settings_with_schema(merged[key], prop_schema)
            # If it's an array, keep as is
            # else: keep as is
    return merged

def get_merged_plugin_settings(plugin_type, current_settings, schema_dir):
    """
    Loads the schema for the plugin_type, merges with current_settings, and returns the merged dict.
    """
    result = {}
    # Use plugin_type as base for schema loading (matches actual schema filenames)
    for nested_key, schema_filename in [
        ("metadata", f"{plugin_type}_plugin.metadata.schema.json"),
        ("additionalFields", f"{plugin_type}_plugin.additional_settings.schema.json")
    ]:
        schema_path = os.path.join(schema_dir, schema_filename)
        current_val = (current_settings or {}).get(nested_key, {})
        if os.path.exists(schema_path):
            with open(schema_path, 'r', encoding='utf-8') as f:
                nested_schema = json.load(f)
            result[nested_key] = merge_settings_with_schema(current_val, nested_schema)
        else:
            result[nested_key] = current_val
    return result
