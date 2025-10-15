# json_schema_validation.py
# Utility for loading and validating JSON schemas for agents and plugins
import os
import json
from functools import lru_cache
from jsonschema import validate, ValidationError, Draft7Validator, Draft6Validator

SCHEMA_DIR = os.path.join(os.path.dirname(__file__), 'static', 'json', 'schemas')

@lru_cache(maxsize=8)
def load_schema(schema_name):
    path = os.path.join(SCHEMA_DIR, schema_name)
    with open(path, encoding='utf-8') as f:
        schema = json.load(f)
    return schema

def validate_agent(agent):
    schema = load_schema('agent.schema.json')
    validator = Draft7Validator(schema['definitions']['Agent'])
    errors = sorted(validator.iter_errors(agent), key=lambda e: e.path)
    if errors:
        return '; '.join([e.message for e in errors])
    return None

def validate_plugin(plugin):
    schema = load_schema('plugin.schema.json')
    
    # For SQL plugins, temporarily provide a dummy endpoint if none exists
    # since SQL plugins don't use endpoints but the schema requires them
    plugin_copy = plugin.copy()
    plugin_type = plugin_copy.get('type', '')
    
    # Remove Cosmos DB system fields that are not part of the plugin schema
    cosmos_fields = ['_attachments', '_etag', '_rid', '_self', '_ts', 'created_at', 'updated_at', 'id', 'user_id', 'last_updated']
    for field in cosmos_fields:
        if field in plugin_copy:
            del plugin_copy[field]
    
    if plugin_type in ['sql_schema', 'sql_query'] and not plugin_copy.get('endpoint'):
        plugin_copy['endpoint'] = f'sql://{plugin_type}'
    
    # First run schema validation
    validator = Draft7Validator(schema['definitions']['Plugin'])
    errors = sorted(validator.iter_errors(plugin_copy), key=lambda e: e.path)
    if errors:
        return '; '.join([f"{plugin.get('name', '<Unknown>')}: {e.message}" for e in errors])
    
    # Additional business logic validation
    # For non-SQL plugins, endpoint must not be empty
    if plugin_type not in ['sql_schema', 'sql_query']:
        endpoint = plugin.get('endpoint', '')
        if not endpoint or endpoint.strip() == '':
            return 'Non-SQL plugins must have a valid endpoint'
    
    return None
