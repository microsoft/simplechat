# json_schema_validation.py
# Utility for loading and validating JSON schemas for agents and plugins
import os
import json
from functools import lru_cache
from jsonschema import validate, ValidationError, Draft7Validator, Draft6Validator, RefResolver

SCHEMA_DIR = os.path.join(os.path.dirname(__file__), 'static', 'json', 'schemas')
PLUGIN_ENDPOINT_DEFAULTS = {
    'sql_schema': 'sql://sql_schema',
    'sql_query': 'sql://sql_query',
    'msgraph': 'https://graph.microsoft.com',
    'simplechat': 'simplechat://internal',
    'search': 'internal://document-search',
    'document_search': 'internal://document-search',
}

PLUGIN_STORAGE_MANAGED_FIELDS = {
    '_attachments',
    '_etag',
    '_rid',
    '_self',
    '_ts',
    'created_at',
    'created_by',
    'group_id',
    'id',
    'is_global',
    'is_group',
    'last_updated',
    'modified_at',
    'modified_by',
    'scope',
    'updated_at',
    'user_id',
}

@lru_cache(maxsize=8)
def load_schema(schema_name):
    path = os.path.join(SCHEMA_DIR, schema_name)
    with open(path, encoding='utf-8') as f:
        schema = json.load(f)
    return schema

def validate_agent(agent):
    schema = load_schema('agent.schema.json')
    if schema.get("$ref") and schema.get("definitions"):
        validator = Draft7Validator(schema, resolver=RefResolver.from_schema(schema))
    else:
        validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(agent), key=lambda e: e.path)
    if errors:
        return '; '.join([e.message for e in errors])
    return None


def apply_plugin_validation_defaults(plugin):
    plugin_copy = plugin.copy() if isinstance(plugin, dict) else {}
    plugin_type = str(plugin_copy.get('type', '') or '').strip().lower()

    # Remove storage-managed fields that appear on persisted plugin documents but are not part of the schema.
    for field in PLUGIN_STORAGE_MANAGED_FIELDS:
        plugin_copy.pop(field, None)

    default_endpoint = PLUGIN_ENDPOINT_DEFAULTS.get(plugin_type)
    if default_endpoint and not str(plugin_copy.get('endpoint', '') or '').strip():
        plugin_copy['endpoint'] = default_endpoint

    return plugin_copy

def validate_plugin(plugin):
    schema = load_schema('plugin.schema.json')
    plugin_copy = apply_plugin_validation_defaults(plugin)
    plugin_type = str(plugin_copy.get('type', '') or '').strip().lower()
    
    # First run schema validation
    if schema.get("$ref") and schema.get("definitions"):
        validator = Draft7Validator(schema, resolver=RefResolver.from_schema(schema))
    else:
        validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(plugin_copy), key=lambda e: e.path)
    if errors:
        return '; '.join([f"{plugin.get('name', '<Unknown>')}: {e.message}" for e in errors])
    
    # Additional business logic validation
    # For non-SQL plugins, endpoint must not be empty
    if plugin_type not in ['sql_schema', 'sql_query']:
        endpoint = plugin_copy.get('endpoint', '')
        if not endpoint or endpoint.strip() == '':
            return 'Non-SQL plugins must have a valid endpoint'
    
    return None
