# json_schema_validation.py
# Utility for loading and validating JSON schemas for agents and plugins
import os
import json
import re
from functools import lru_cache
from jsonschema import validate, ValidationError, Draft7Validator, Draft6Validator, RefResolver

from functions_agent_delegation import (
    AGENT_ACTION_VALIDATION_ERROR,
    AGENT_DEFAULT_ENDPOINT,
    AGENT_PLUGIN_TYPE,
    validate_agent_action_manifest,
)
from functions_blob_storage_operations import BLOB_STORAGE_PLUGIN_TYPE, derive_blob_endpoint_from_connection_string
from functions_chart_operations import CHART_DEFAULT_ENDPOINT
from functions_databricks_operations import DATABRICKS_LEGACY_TABLE_PLUGIN_TYPE, DATABRICKS_PLUGIN_TYPE
from functions_snowflake_operations import SNOWFLAKE_DEFAULT_ENDPOINT, SNOWFLAKE_PLUGIN_TYPE

SCHEMA_DIR = os.path.join(os.path.dirname(__file__), 'static', 'json', 'schemas')
PLUGIN_ENDPOINT_DEFAULTS = {
    AGENT_PLUGIN_TYPE: AGENT_DEFAULT_ENDPOINT,
    'sql_schema': 'sql://sql_schema',
    'sql_query': 'sql://sql_query',
    'chart': CHART_DEFAULT_ENDPOINT,
    'msgraph': 'https://graph.microsoft.com',
    'simplechat': 'simplechat://internal',
    'search': 'internal://document-search',
    'document_search': 'internal://document-search',
    SNOWFLAKE_PLUGIN_TYPE: SNOWFLAKE_DEFAULT_ENDPOINT,
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


def normalize_plugin_definition_type(plugin_type):
    """Return the filesystem-safe definition name for a plugin type."""
    return re.sub(r'[^a-zA-Z0-9_]', '_', str(plugin_type or '')).lower()


@lru_cache(maxsize=64)
def get_allowed_auth_types_for_plugin_type(plugin_type):
    """Return the auth types a plugin type supports.

    The per-type ``<type>.definition.json`` file is authoritative when present. Otherwise the
    shared ``AuthType`` enum in ``plugin.schema.json`` is used, so unknown types keep working.
    """
    normalized_type = normalize_plugin_definition_type(plugin_type)
    if normalized_type:
        definition_path = os.path.join(SCHEMA_DIR, f'{normalized_type}.definition.json')
        if os.path.exists(definition_path):
            try:
                with open(definition_path, encoding='utf-8') as definition_file:
                    definition = json.load(definition_file)
                allowed_auth_types = definition.get('allowedAuthTypes')
                if isinstance(allowed_auth_types, list) and allowed_auth_types:
                    return frozenset(str(auth_type) for auth_type in allowed_auth_types)
            except (OSError, ValueError):
                pass

    schema = load_schema('plugin.schema.json')
    enum_values = schema.get('definitions', {}).get('AuthType', {}).get('enum', [])
    return frozenset(str(auth_type) for auth_type in enum_values)


def validate_plugin_auth_type_allowed(plugin):
    """Return an error message when a manifest declares an auth type its plugin type disallows.

    Without this check a caller can declare any auth type on any action type, including
    ``identity``, which makes the application authenticate with its own workload identity to a
    caller-supplied destination.

    Identity-bound manifests are exempt because their auth type is resolved server-side from a
    stored workspace identity rather than declared by the caller, and that hydration legitimately
    rewrites ``auth.type`` into values a definition file does not list.
    """
    if not isinstance(plugin, dict):
        return None

    additional_fields = plugin.get('additionalFields') if isinstance(plugin.get('additionalFields'), dict) else {}
    if str(plugin.get('identity_id') or '').strip() or str(additional_fields.get('identity_id') or '').strip():
        return None

    auth = plugin.get('auth') if isinstance(plugin.get('auth'), dict) else {}
    declared_auth_type = str(auth.get('type') or '').strip()
    if not declared_auth_type:
        return None

    plugin_type = str(plugin.get('type') or '').strip().lower()
    if plugin_type == DATABRICKS_LEGACY_TABLE_PLUGIN_TYPE:
        plugin_type = DATABRICKS_PLUGIN_TYPE

    allowed_auth_types = get_allowed_auth_types_for_plugin_type(plugin_type)
    if not allowed_auth_types or declared_auth_type in allowed_auth_types:
        return None

    return (
        f"Authentication type '{declared_auth_type}' is not supported by action type '{plugin_type}'."
    )


def apply_plugin_validation_defaults(plugin):
    plugin_copy = plugin.copy() if isinstance(plugin, dict) else {}
    plugin_type = str(plugin_copy.get('type', '') or '').strip().lower()
    if plugin_type == DATABRICKS_LEGACY_TABLE_PLUGIN_TYPE:
        plugin_type = DATABRICKS_PLUGIN_TYPE
        plugin_copy['type'] = DATABRICKS_PLUGIN_TYPE

    # Remove storage-managed fields that appear on persisted plugin documents but are not part of the schema.
    for field in PLUGIN_STORAGE_MANAGED_FIELDS:
        plugin_copy.pop(field, None)

    default_endpoint = PLUGIN_ENDPOINT_DEFAULTS.get(plugin_type)
    if default_endpoint and not str(plugin_copy.get('endpoint', '') or '').strip():
        plugin_copy['endpoint'] = default_endpoint

    if plugin_type == BLOB_STORAGE_PLUGIN_TYPE and not str(plugin_copy.get('endpoint', '') or '').strip():
        auth = plugin_copy.get('auth', {}) if isinstance(plugin_copy.get('auth'), dict) else {}
        if str(auth.get('type') or '').strip().lower() == 'connection_string':
            derived_endpoint = derive_blob_endpoint_from_connection_string(auth.get('key') or '')
            if derived_endpoint:
                plugin_copy['endpoint'] = derived_endpoint

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
    if plugin_type == AGENT_PLUGIN_TYPE:
        try:
            validate_agent_action_manifest(plugin_copy)
        except ValueError:
            return AGENT_ACTION_VALIDATION_ERROR

    # For non-SQL plugins, endpoint must not be empty
    if plugin_type not in ['sql_schema', 'sql_query']:
        endpoint = plugin_copy.get('endpoint', '')
        if not endpoint or endpoint.strip() == '':
            return 'Non-SQL plugins must have a valid endpoint'
    
    return None
