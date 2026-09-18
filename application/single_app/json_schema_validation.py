# json_schema_validation.py
# Utility for loading and validating JSON schemas for agents and plugins
import os
import json
import re
from functools import lru_cache
from copy import deepcopy
from jsonschema import validate, ValidationError, Draft7Validator, Draft6Validator, RefResolver

from functions_blob_storage_operations import BLOB_STORAGE_PLUGIN_TYPE, derive_blob_endpoint_from_connection_string
from functions_chart_operations import CHART_DEFAULT_ENDPOINT
from functions_databricks_operations import DATABRICKS_LEGACY_TABLE_PLUGIN_TYPE, DATABRICKS_PLUGIN_TYPE
from functions_snowflake_operations import SNOWFLAKE_DEFAULT_ENDPOINT, SNOWFLAKE_PLUGIN_TYPE
from functions_m365_operations import (
    M365_PLUGIN_TYPES,
    get_m365_schema_for_type,
    normalize_m365_action_config,
)

SCHEMA_DIR = os.path.join(os.path.dirname(__file__), 'static', 'json', 'schemas')
PLUGIN_ENDPOINT_DEFAULTS = {
    'sql_schema': 'sql://sql_schema',
    'sql_query': 'sql://sql_query',
    'chart': CHART_DEFAULT_ENDPOINT,
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

LEGACY_ACTION_CREATION_MESSAGE = (
    "Existing Microsoft Graph actions can be edited, but cannot be created, "
    "cloned, imported, or restored after deletion. Choose a Microsoft 365 source action."
)
ACTION_MIGRATION_ID_PREFIX = "__simplechat_action_migration__"


class LegacyActionCreationError(ValueError):
    """A caller attempted to create a retired combined Graph action."""


def is_legacy_msgraph_type(plugin_type):
    """Recognize retired type aliases before schema or runtime normalization."""
    compact_type = re.sub(r'[^a-z0-9]', '', str(plugin_type or '').lower())
    return compact_type in {
        'msgraph', 'microsoftgraph', 'msgraphplugin', 'microsoftgraphplugin',
    }


def validate_legacy_action_update(payload, existing, scope_field=None, scope_id=None):
    """Require a live, exact, scope-bound ID for every legacy write.

    The caller must obtain ``existing`` with a point read, never a name lookup.
    Legacy writes must subsequently use conditional replace, not upsert.
    """
    if not isinstance(payload, dict):
        raise ValueError("Action configuration must be an object.")
    action_id = payload.get('id')
    if (
        payload.get('_action_migration')
        or str(action_id or '').startswith(ACTION_MIGRATION_ID_PREFIX)
        or (isinstance(existing, dict) and existing.get('_action_migration'))
    ):
        raise ValueError("Action migration records are server managed.")
    metadata = payload.get('metadata')
    plugin_type = payload.get('type') or (metadata.get('type') if isinstance(metadata, dict) else None)
    if not is_legacy_msgraph_type(plugin_type):
        return
    additional = payload.get('additionalFields') or {}
    if not isinstance(additional, dict) or additional.get('maximum_sharing_acknowledgement', 'always') not in ('request', 'today', 'always'):
        raise ValueError("Invalid sharing acknowledgement policy.")
    if (
        not isinstance(action_id, str)
        or not action_id
        or not isinstance(existing, dict)
        or existing.get('id') != action_id
        or not is_legacy_msgraph_type(existing.get('type'))
        or (scope_field and existing.get(scope_field) != scope_id)
    ):
        raise LegacyActionCreationError(LEGACY_ACTION_CREATION_MESSAGE)


def validate_legacy_plugin_settings_update(existing_settings, incoming_settings):
    """Prevent settings/import arrays from introducing retired action records."""
    if not isinstance(incoming_settings, dict):
        raise ValueError("Settings must be an object.")
    existing_settings = existing_settings if isinstance(existing_settings, dict) else {}
    for key in ('plugins', 'semantic_kernel_plugins'):
        if key not in incoming_settings:
            continue
        plugins = incoming_settings[key]
        if not isinstance(plugins, list):
            raise ValueError("Plugins must be an array.")
        previous_plugins = existing_settings.get(key) or []
        existing_by_id = {
            plugin['id']: plugin
            for plugin in previous_plugins
            if isinstance(plugin, dict) and isinstance(plugin.get('id'), str)
        }
        for plugin in plugins:
            if not isinstance(plugin, dict):
                raise ValueError("Action configuration must be an object.")
            validate_legacy_action_update(plugin, existing_by_id.get(plugin.get('id')))


def normalize_m365_action_payload(plugin):
    """Validate delegated-only saved configuration before applying typed defaults."""
    plugin_type = plugin.get('type')
    if plugin_type not in M365_PLUGIN_TYPES:
        compact_type = re.sub(r'[^a-z0-9]', '', str(plugin_type or '').lower()).removesuffix('plugin')
        if compact_type.startswith('microsoft365'):
            compact_type = f"m365{compact_type[len('microsoft365'):]}"
        if compact_type in {action_type.replace('_', '') for action_type in M365_PLUGIN_TYPES}:
            raise ValueError("Microsoft 365 actions require an exact source-specific type name.")
        return plugin
    payload = deepcopy(plugin)
    payload['type'] = plugin_type
    if {'m365_capabilities', 'maximum_sharing_acknowledgement'}.intersection(payload):
        raise ValueError("Microsoft 365 action policies must be configured in additionalFields.")
    payload.setdefault('auth', {'type': 'user'})
    payload.setdefault('additionalFields', {})
    if payload.get('identity_id'):
        raise ValueError("Microsoft 365 actions cannot use a workspace identity.")
    if str(payload.get('endpoint') or '').strip():
        raise ValueError("Microsoft 365 actions inherit the deployment endpoint; leave the action endpoint empty.")
    validator = Draft7Validator(get_m365_schema_for_type(plugin_type))
    if list(validator.iter_errors(payload)):
        raise ValueError("Invalid Microsoft 365 source capabilities, sharing policy, or delegated authentication.")
    normalized = normalize_m365_action_config(plugin_type, payload)
    enabled = set(normalized['enabled_functions'])
    normalized['additionalFields']['m365_capabilities'] = {
        name: value and name in enabled
        for name, value in normalized['additionalFields']['m365_capabilities'].items()
    }
    for field in ('enabled_functions', 'm365_capabilities', 'maximum_sharing_acknowledgement'):
        normalized.pop(field, None)
    normalized['endpoint'] = ''
    return normalized


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
    if is_legacy_msgraph_type(plugin_type):
        return 'msgraph'
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
    plugin_type = normalize_plugin_definition_type(plugin.get('type'))
    if plugin_type in M365_PLUGIN_TYPES:
        if plugin.get('identity_id') or additional_fields.get('identity_id'):
            return "Microsoft 365 actions cannot use a workspace identity."
        auth = plugin.get('auth') if isinstance(plugin.get('auth'), dict) else {}
        if auth.get('type') != 'user' or set(auth) != {'type'}:
            return "Microsoft 365 actions require the data user's delegated authentication."
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
    plugin_copy = normalize_m365_action_payload(plugin_copy)
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
    try:
        plugin_copy = apply_plugin_validation_defaults(plugin)
    except ValueError:
        return "Invalid Microsoft 365 source configuration."
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
    if plugin_type not in ['sql_schema', 'sql_query', 'msgraph', *M365_PLUGIN_TYPES]:
        endpoint = plugin_copy.get('endpoint', '')
        if not endpoint or endpoint.strip() == '':
            return 'Non-SQL plugins must have a valid endpoint'
    
    return None
