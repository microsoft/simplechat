import os
import json

def load_plugin_schema(plugin_type, schema_dir):
    """
    Loads the JSON schema for the given plugin type from the schema_dir.
    Returns the schema dict, or None if not found.
    """
    # Accept both log_analytics_plugin and log-analytics-plugin naming
    candidates = [
        f"{plugin_type}_plugin.additional_settings.schema.json",
        f"{plugin_type}.additional_settings.schema.json",
        f"{plugin_type}_plugin.schema.json",
        f"{plugin_type}.schema.json"
    ]
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
    merged = dict(current) if current else {}
    for key, prop_schema in schema['properties'].items():
        if key in merged:
            # If it's an object or array, recurse
            if prop_schema.get('type') == 'object' and isinstance(merged[key], dict):
                merged[key] = merge_settings_with_schema(merged[key], prop_schema)
            elif prop_schema.get('type') == 'array' and isinstance(merged[key], list):
                # Optionally, could merge array items if items is object
                pass
            # else: keep as is
        else:
            merged[key] = get_default_for_schema_property(prop_schema)
    # Remove keys not in schema if you want strictness (optional)
    # merged = {k: v for k, v in merged.items() if k in schema['properties']}
    return merged

def get_merged_plugin_settings(plugin_type, current_settings, schema_dir):
    """
    Loads the schema for the plugin_type, merges with current_settings, and returns the merged dict.
    """
    schema = load_plugin_schema(plugin_type, schema_dir)
    if not schema:
        return current_settings or {}
    return merge_settings_with_schema(current_settings, schema)
