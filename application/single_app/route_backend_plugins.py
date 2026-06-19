# route_backend_plugins.py

import asyncio
import re
import builtins
import json
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError
from azure.identity import DefaultAzureCredential
from flask import Blueprint, jsonify, request, current_app, session
from semantic_kernel_plugins.plugin_loader import get_all_plugin_metadata
from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker, PluginErrorRecovery
from semantic_kernel_plugins.sql_odbc_utils import (
    DEFAULT_SQL_SERVER_ODBC_DRIVER,
    build_sql_server_odbc_connection_string,
    connect_with_sql_server_odbc_fallback,
)
from functions_settings import get_settings, is_tabular_processing_enabled, update_settings
from functions_authentication import *
from functions_appinsights import log_event
from swagger_wrapper import swagger_route, get_auth_security
import logging
import os
from functions_debug import debug_print
import importlib.util
from functions_plugins import get_merged_plugin_settings
from semantic_kernel_plugins.base_plugin import BasePlugin

from functions_global_actions import *
from functions_personal_actions import *
from functions_group import require_active_group, assert_group_role
from functions_group_actions import (
    get_group_actions,
    get_governed_group_actions,
    get_group_action,
    save_group_action,
    delete_group_action,
    validate_group_action_payload,
)
from functions_keyvault import (
    resolve_secret_reference_for_context,
    SecretReturnType,
    redact_plugin_secret_values,
    retrieve_secret_from_key_vault_by_full_name,
    ui_trigger_word,
    validate_secret_name_dynamic,
)
#from functions_personal_actions import delete_personal_action

from functions_debug import debug_print
from json_schema_validation import PLUGIN_STORAGE_MANAGED_FIELDS, apply_plugin_validation_defaults, validate_plugin
from functions_activity_logging import (
    log_action_creation,
    log_action_update,
    log_action_deletion,
)
from functions_azure_maps import AZURE_MAPS_DEFAULT_ENDPOINT, AZURE_MAPS_PLUGIN_TYPE
from functions_blob_storage_operations import (
    BLOB_STORAGE_PLUGIN_TYPE,
    derive_blob_endpoint_from_connection_string,
    get_default_blob_storage_capabilities,
    get_default_blob_storage_read_file_types,
    get_default_blob_storage_upload_file_types,
)
from functions_chart_operations import CHART_DEFAULT_ENDPOINT, CHART_PLUGIN_TYPE
from functions_databricks_operations import (
    DATABRICKS_LEGACY_TABLE_PLUGIN_TYPE,
    DATABRICKS_PLUGIN_TYPE,
    normalize_databricks_additional_fields,
)
from functions_snowflake_operations import (
    SNOWFLAKE_DEFAULT_ENDPOINT,
    SNOWFLAKE_PLUGIN_TYPE,
    normalize_snowflake_additional_fields,
)
from functions_tableau_operations import (
    TABLEAU_AUTH_METHOD_PAT,
    TABLEAU_AUTH_METHOD_USERNAME_PASSWORD,
    TABLEAU_PLUGIN_TYPE,
    normalize_tableau_additional_fields,
    normalize_tableau_server_url,
)
from functions_mcp_operations import (
    MCP_PLUGIN_TYPE,
    MCP_STDIO_ENDPOINT,
    normalize_mcp_additional_fields,
)
from semantic_kernel_plugins.mcp_plugin_factory import McpPluginFactory
from functions_msgraph_operations import (
    MSGRAPH_DEFAULT_ENDPOINT,
    MSGRAPH_PLUGIN_TYPE,
    normalize_msgraph_calendar_send_options,
    normalize_msgraph_mail_send_options,
)
from functions_simplechat_operations import SIMPLECHAT_DEFAULT_ENDPOINT, SIMPLECHAT_PLUGIN_TYPE
from functions_workspace_identities import (
    WORKSPACE_IDENTITY_SCOPE_GLOBAL,
    WORKSPACE_IDENTITY_SCOPE_GROUP,
    WORKSPACE_IDENTITY_SCOPE_PERSONAL,
    hydrate_action_identity_reference,
    validate_action_identity_reference,
)
from functions_governance import (
    ensure_action_type_access,
    filter_governed_global_actions_for_user,
    is_action_type_access_allowed,
    upsert_item_policy,
)


DOCUMENT_SEARCH_INTERNAL_ENDPOINT = 'internal://document-search'


def _apply_plugin_runtime_defaults(plugin_payload):
    if not isinstance(plugin_payload, dict):
        return plugin_payload

    plugin_type = plugin_payload.get('type', '')
    if plugin_type in ['sql_schema', 'sql_query']:
        if not str(plugin_payload.get('endpoint') or '').strip():
            plugin_payload['endpoint'] = f'sql://{plugin_type}'
    elif plugin_type == CHART_PLUGIN_TYPE:
        if not str(plugin_payload.get('endpoint') or '').strip():
            plugin_payload['endpoint'] = CHART_DEFAULT_ENDPOINT
        auth = plugin_payload.get('auth') if isinstance(plugin_payload.get('auth'), dict) else {}
        auth['type'] = 'user'
        plugin_payload['auth'] = auth
    elif plugin_type == MSGRAPH_PLUGIN_TYPE:
        if not str(plugin_payload.get('endpoint') or '').strip():
            plugin_payload['endpoint'] = MSGRAPH_DEFAULT_ENDPOINT
        auth = plugin_payload.get('auth') if isinstance(plugin_payload.get('auth'), dict) else {}
        auth['type'] = 'user'
        plugin_payload['auth'] = auth
        additional_fields = plugin_payload.get('additionalFields') if isinstance(plugin_payload.get('additionalFields'), dict) else {}
        additional_fields.update(normalize_msgraph_mail_send_options(additional_fields))
        additional_fields.update(normalize_msgraph_calendar_send_options(additional_fields))
        plugin_payload['additionalFields'] = additional_fields
    elif plugin_type == MCP_PLUGIN_TYPE:
        additional_fields = plugin_payload.get('additionalFields') if isinstance(plugin_payload.get('additionalFields'), dict) else {}
        additional_fields = normalize_mcp_additional_fields(additional_fields)
        plugin_payload['additionalFields'] = additional_fields

        if additional_fields.get('transport') == 'stdio' and not str(plugin_payload.get('endpoint') or '').strip():
            plugin_payload['endpoint'] = MCP_STDIO_ENDPOINT

        auth = plugin_payload.get('auth') if isinstance(plugin_payload.get('auth'), dict) else {}
        auth_method = additional_fields.get('auth_method') or 'none'
        if auth_method == 'none':
            auth['type'] = 'NoAuth'
            auth.pop('key', None)
            auth.pop('identity', None)
        elif auth_method == 'identity':
            auth['type'] = auth.get('type') or 'identity'
        elif auth.get('type') in ['', None, 'NoAuth']:
            auth['type'] = 'key'
        plugin_payload['auth'] = auth
    elif plugin_type in ['search', 'document_search']:
        if not str(plugin_payload.get('endpoint') or '').strip():
            plugin_payload['endpoint'] = DOCUMENT_SEARCH_INTERNAL_ENDPOINT
        auth = plugin_payload.get('auth') if isinstance(plugin_payload.get('auth'), dict) else {}
        auth['type'] = 'NoAuth'
        plugin_payload['auth'] = auth
    elif plugin_type == AZURE_MAPS_PLUGIN_TYPE:
        if not str(plugin_payload.get('endpoint') or '').strip():
            plugin_payload['endpoint'] = AZURE_MAPS_DEFAULT_ENDPOINT
        auth = plugin_payload.get('auth') if isinstance(plugin_payload.get('auth'), dict) else {}
        auth['type'] = 'key'
        plugin_payload['auth'] = auth
    elif plugin_type == BLOB_STORAGE_PLUGIN_TYPE:
        auth = plugin_payload.get('auth') if isinstance(plugin_payload.get('auth'), dict) else {}
        additional_fields = plugin_payload.get('additionalFields') if isinstance(plugin_payload.get('additionalFields'), dict) else {}
        if not plugin_payload.get('endpoint') and auth.get('type') == 'connection_string':
            derived_endpoint = derive_blob_endpoint_from_connection_string(auth.get('key') or '')
            if derived_endpoint:
                plugin_payload['endpoint'] = derived_endpoint
        additional_fields.setdefault('blob_storage_capabilities', get_default_blob_storage_capabilities())
        additional_fields.setdefault('blob_storage_read_file_types', get_default_blob_storage_read_file_types())
        additional_fields.setdefault('blob_storage_upload_file_types', get_default_blob_storage_upload_file_types())
        plugin_payload['additionalFields'] = additional_fields
    elif plugin_type in {DATABRICKS_PLUGIN_TYPE, DATABRICKS_LEGACY_TABLE_PLUGIN_TYPE}:
        auth = plugin_payload.get('auth') if isinstance(plugin_payload.get('auth'), dict) else {}
        auth_type = str(auth.get('type') or 'key').strip() or 'key'
        auth['type'] = auth_type
        additional_fields = plugin_payload.get('additionalFields') if isinstance(plugin_payload.get('additionalFields'), dict) else {}
        additional_fields = normalize_databricks_additional_fields(additional_fields, auth_type=auth_type)
        if auth_type == 'servicePrincipal':
            additional_fields['auth_method'] = 'service_principal'
        elif auth_type == 'identity' and auth.get('identity') == 'managed_identity':
            additional_fields['auth_method'] = 'managed_identity'
        plugin_payload['type'] = DATABRICKS_PLUGIN_TYPE
        plugin_payload['auth'] = auth
        plugin_payload['additionalFields'] = additional_fields
    elif plugin_type == SNOWFLAKE_PLUGIN_TYPE:
        if not str(plugin_payload.get('endpoint') or '').strip():
            plugin_payload['endpoint'] = SNOWFLAKE_DEFAULT_ENDPOINT
        auth = plugin_payload.get('auth') if isinstance(plugin_payload.get('auth'), dict) else {}
        auth_type = str(auth.get('type') or 'username_password').strip() or 'username_password'
        auth['type'] = auth_type
        additional_fields = plugin_payload.get('additionalFields') if isinstance(plugin_payload.get('additionalFields'), dict) else {}
        additional_fields = normalize_snowflake_additional_fields(additional_fields, auth_type=auth_type)
        if auth_type == 'username_password':
            additional_fields['auth_method'] = 'password'
            if auth.get('identity') and not additional_fields.get('user'):
                additional_fields['user'] = auth.get('identity')
        plugin_payload['auth'] = auth
        plugin_payload['additionalFields'] = additional_fields
    elif plugin_type == TABLEAU_PLUGIN_TYPE:
        auth = plugin_payload.get('auth') if isinstance(plugin_payload.get('auth'), dict) else {}
        auth_type = str(auth.get('type') or 'key').strip() or 'key'
        auth['type'] = auth_type
        additional_fields = plugin_payload.get('additionalFields') if isinstance(plugin_payload.get('additionalFields'), dict) else {}
        additional_fields = normalize_tableau_additional_fields(additional_fields, auth_type=auth_type)
        if auth_type == 'username_password':
            additional_fields['auth_method'] = TABLEAU_AUTH_METHOD_USERNAME_PASSWORD
        elif auth_type == 'identity' and additional_fields.get('identity_auth_type') == 'username_password':
            additional_fields['auth_method'] = TABLEAU_AUTH_METHOD_USERNAME_PASSWORD
        else:
            additional_fields['auth_method'] = additional_fields.get('auth_method') or TABLEAU_AUTH_METHOD_PAT

        endpoint = normalize_tableau_server_url(plugin_payload.get('endpoint') or additional_fields.get('server_url') or '')
        if endpoint:
            plugin_payload['endpoint'] = endpoint
            additional_fields['server_url'] = endpoint
        if auth_type != 'identity' and auth.get('identity') and not additional_fields.get('pat_name') and additional_fields.get('auth_method') == TABLEAU_AUTH_METHOD_PAT:
            additional_fields['pat_name'] = auth.get('identity')

        plugin_payload['type'] = TABLEAU_PLUGIN_TYPE
        plugin_payload['auth'] = auth
        plugin_payload['additionalFields'] = additional_fields
    elif plugin_type == SIMPLECHAT_PLUGIN_TYPE:
        if not str(plugin_payload.get('endpoint') or '').strip():
            plugin_payload['endpoint'] = SIMPLECHAT_DEFAULT_ENDPOINT
        auth = plugin_payload.get('auth') if isinstance(plugin_payload.get('auth'), dict) else {}
        auth['type'] = 'user'
        plugin_payload['auth'] = auth

    return plugin_payload

def discover_plugin_types():
    # Dynamically discover allowed plugin types from available plugin classes.
    plugintypes_dir = os.path.join(current_app.root_path, 'semantic_kernel_plugins')
    types = set()
    for fname in os.listdir(plugintypes_dir):
        if fname.endswith('_plugin.py') and fname != 'base_plugin.py':
            module_name = fname[:-3]
            file_path = os.path.join(plugintypes_dir, fname)
            try:
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception:
                continue
            for attr in dir(module):
                obj = getattr(module, attr)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, BasePlugin)
                    and obj is not BasePlugin
                ):
                    # Use the type string as in the manifest (e.g., 'blob_storage')
                    # Try to get from class, fallback to module naming convention
                    type_str = getattr(obj, 'metadata', None)
                    if callable(type_str):
                        try:
                            meta = obj.metadata.fget(obj) if hasattr(obj.metadata, 'fget') else obj().metadata
                            if isinstance(meta, dict) and 'type' in meta:
                                types.add(meta['type'])
                            else:
                                types.add(module_name.replace('_plugin', ''))
                        except Exception:
                            types.add(module_name.replace('_plugin', ''))
                    else:
                        types.add(module_name.replace('_plugin', ''))
    return types

def get_plugin_types(allowed_type_filter=None):
    # Path to the plugin types directory (semantic_kernel_plugins)
    plugintypes_dir = os.path.join(current_app.root_path, 'semantic_kernel_plugins')
    types = []
    debug_log = []
    for fname in os.listdir(plugintypes_dir):
        if fname.endswith('_plugin.py') and fname != 'base_plugin.py':
            module_name = fname[:-3]
            file_path = os.path.join(plugintypes_dir, fname)
            debug_log.append(f"Checking plugin file: {fname}")
            try:
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                debug_log.append(f"Imported module: {module_name}")
            except Exception as e:
                debug_log.append(f"Failed to import {fname}: {e}")
                continue
            # Find classes that are subclasses of BasePlugin (but not BasePlugin itself)
            found = False
            for attr in dir(module):
                obj = getattr(module, attr)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, BasePlugin)
                    and obj is not BasePlugin
                ):
                    found = True
                    # Special handling for OpenAPI plugin that requires spec path
                    if 'openapi' in module_name.lower():
                        display_name = "OpenAPI"
                        description = "Plugin for integrating with external APIs using OpenAPI specifications. Supports file upload, URL download, and various authentication methods."
                        types.append({
                            'type': module_name.replace('_plugin', ''),
                            'class': attr,
                            'display': display_name,
                            'description': description
                        })
                        continue
                    
                    # Try to get display name from plugin instance
                    try:
                        # Use a more robust instantiation pattern
                        plugin_instance = None
                        instantiation_error = None
                        
                        # Try creating instance with minimal safe manifest
                        safe_manifest = {}
                        
                        # Only add minimal required fields based on plugin type
                        #TODO: This can be improved by ensuring we have additional fields from the schemas we have not created if needed. 
                        if 'databricks' in module_name.lower():
                            safe_manifest = {
                                'endpoint': 'https://adb-1234567890123456.7.azuredatabricks.net',
                                'auth': {'type': 'key', 'key': 'dummy'},
                                'additionalFields': {
                                    'cloud': 'azure_commercial',
                                    'workspace_url': 'https://adb-1234567890123456.7.azuredatabricks.net',
                                    'warehouse_id': 'dummy',
                                    'catalog': 'main',
                                    'schema': 'default',
                                },
                                'metadata': {'description': 'Example Databricks plugin'},
                            }
                        elif 'snowflake' in module_name.lower():
                            safe_manifest = {
                                'endpoint': SNOWFLAKE_DEFAULT_ENDPOINT,
                                'auth': {'type': 'username_password', 'identity': 'analyst', 'key': 'dummy'},
                                'additionalFields': {
                                    'account': 'organization-account',
                                    'user': 'analyst',
                                    'auth_method': 'password',
                                    'warehouse': 'COMPUTE_WH',
                                    'database': 'ANALYTICS',
                                    'schema': 'PUBLIC',
                                },
                                'metadata': {'description': 'Example Snowflake query action'},
                            }
                        elif 'tableau' in module_name.lower():
                            safe_manifest = {
                                'endpoint': 'https://10ax.online.tableau.com',
                                'auth': {'type': 'key', 'identity': 'pat-name', 'key': 'dummy'},
                                'additionalFields': {
                                    'server_url': 'https://10ax.online.tableau.com',
                                    'site_content_url': 'example-site',
                                    'auth_method': 'personal_access_token',
                                    'pat_name': 'pat-name',
                                    'page_size': 100,
                                    'max_results': 100,
                                    'timeout': 30,
                                },
                                'metadata': {'description': 'Example Tableau plugin'},
                            }
                        elif 'sql' in module_name.lower():
                            safe_manifest = {
                                'database_type': 'sqlite',
                                'connection_string': ':memory:',
                                'metadata': {'description': 'Example SQL plugin'}
                            }
                        elif 'cosmos' in module_name.lower():
                            safe_manifest = {
                                'endpoint': 'https://example.documents.azure.com:443/',
                                'auth': {'type': 'identity', 'identity': 'managed_identity'},
                                'additionalFields': {
                                    'database_name': 'SimpleChat',
                                    'container_name': 'documents',
                                    'partition_key_path': '/id',
                                    'field_hints': ['id', 'title', 'user_id'],
                                    'max_items': 100,
                                    'timeout': 30,
                                },
                                'metadata': {'description': 'Example Cosmos query plugin'}
                            }
                        elif 'blob_storage' in module_name.lower():
                            safe_manifest = {
                                'endpoint': 'https://example.blob.core.windows.net',
                                'auth': {
                                    'type': 'connection_string',
                                    'key': 'DefaultEndpointsProtocol=https;AccountName=example;AccountKey=ZmFrZQ==;EndpointSuffix=core.windows.net'
                                },
                                'additionalFields': {
                                    'container_name': 'content',
                                    'blob_prefix': 'docs',
                                    'blob_storage_capabilities': get_default_blob_storage_capabilities(),
                                    'blob_storage_read_file_types': get_default_blob_storage_read_file_types(),
                                    'blob_storage_upload_file_types': get_default_blob_storage_upload_file_types(),
                                },
                                'metadata': {'description': 'Example Blob Storage plugin'}
                            }
                        elif any(x in module_name.lower() for x in ['azure_function', 'queue_storage']):
                            safe_manifest = {
                                'endpoint': 'https://example.azure.com',
                                'auth': {'type': 'key', 'key': 'dummy'},
                                'metadata': {'description': f'Example {module_name} plugin'}
                            }
                        elif 'msgraph' in module_name.lower():
                            safe_manifest = {
                                'auth': {'type': 'user'},
                                'metadata': {'description': 'Microsoft Graph plugin'}
                            }
                        elif 'mcp' in module_name.lower():
                            safe_manifest = {
                                'endpoint': 'https://example.com/mcp',
                                'auth': {'type': 'NoAuth'},
                                'additionalFields': {
                                    'transport': 'streamable_http',
                                    'auth_method': 'none',
                                    'load_tools': True,
                                    'load_prompts': False,
                                    'request_timeout': 30,
                                    'connect_timeout': 10,
                                    'sse_read_timeout': 300,
                                    'allowed_tool_names': [],
                                    'mcp_tools': []
                                },
                                'metadata': {'description': 'Example MCP action'}
                            }
                        elif 'azure_maps' in module_name.lower():
                            safe_manifest = {
                                'endpoint': AZURE_MAPS_DEFAULT_ENDPOINT,
                                'auth': {'type': 'key', 'key': 'dummy'},
                                'metadata': {'description': 'Azure Maps visualization plugin'}
                            }
                        elif 'log_analytics' in module_name.lower():
                            safe_manifest = {
                                'endpoint': 'https://api.loganalytics.io',
                                'auth': {'type': 'user'},
                                'additionalFields': {'workspaceId': 'dummy', 'cloud': 'public'},
                                'metadata': {'description': 'Azure Log Analytics plugin'}
                            }
                        elif 'embedding' in module_name.lower():
                            safe_manifest = {
                                'endpoint': 'https://api.openai.com',
                                'auth': {'type': 'key', 'key': 'dummy'},
                                'metadata': {'description': 'Embedding model plugin'}
                            }
                        
                        # Try instantiation with progressively simpler approaches
                        try:
                            plugin_instance = obj(safe_manifest)
                        except (TypeError, ValueError, KeyError) as e:
                            debug_print(f"[RBEP] Failed to instantiate {attr} with safe manifest: {e}")
                            try:
                                plugin_instance = obj({})
                            except (TypeError, ValueError) as e2:
                                debug_print(f"[RBEP] Failed to instantiate {attr} with empty manifest: {e2}")
                                try:
                                    plugin_instance = obj()
                                except Exception as e3:
                                    debug_print(f"[RBEP] Failed to instantiate {attr} with no args: {e3}")
                                    instantiation_error = e3
                        except Exception as e:
                            instantiation_error = e
                        
                        if plugin_instance is None:
                            # Fallback to class name formatting
                            display_name = attr.replace('Plugin', '').replace('_', ' ')
                            description = f"Plugin for {display_name.lower()} functionality"
                            debug_log.append(f"Failed to instantiate {attr} for metadata extraction: {instantiation_error}. Using fallback display name.")
                        else:
                            try:
                                display_name = plugin_instance.display_name
                                description = plugin_instance.metadata.get("description", "")
                            except Exception as e:
                                # Fallback if display_name or metadata access fails
                                display_name = attr.replace('Plugin', '').replace('_', ' ')
                                description = f"Plugin for {display_name.lower()} functionality"
                                debug_log.append(f"Failed to get metadata from {attr}: {e}. Using fallback.")
                        
                    except Exception as e:
                        # Final fallback to class name formatting
                        display_name = attr.replace('Plugin', '').replace('_', ' ')
                        description = f"Plugin for {display_name.lower()} functionality"
                        debug_log.append(f"Complete failure to instantiate {attr}: {e}. Using final fallback.")
                    
                    types.append({
                        'type': module_name.replace('_plugin', ''),
                        'class': attr,
                        'display': display_name,
                        'description': description
                    })
            if not found:
                debug_log.append(f"No valid plugin class found in {fname}")
    # Log the debug output to the server log
    if callable(allowed_type_filter):
        types = [plugin_type for plugin_type in types if allowed_type_filter(plugin_type.get('type'))]

    print("[PLUGIN DISCOVERY DEBUG]", *debug_log, sep="\n")
    return jsonify(types)

bpap = Blueprint('admin_plugins', __name__)


def _redact_plugin_for_logging(plugin):
    """Return a plugin manifest with secret-bearing values redacted for logging."""
    if not isinstance(plugin, dict):
        return plugin
    return redact_plugin_secret_values(plugin)


def _resolve_plugin_secret_context(plugin_manifest, fallback_scope_value, fallback_scope="user"):
    """Infer the expected Key Vault scope for SQL test-connection secret resolution."""
    if not isinstance(plugin_manifest, dict):
        return fallback_scope_value, fallback_scope

    plugin_scope = str(plugin_manifest.get("scope") or "").strip().lower()
    if plugin_scope == "group" or plugin_manifest.get("is_group"):
        return plugin_manifest.get("group_id"), "group"
    if plugin_scope == "global" or plugin_manifest.get("is_global"):
        return plugin_manifest.get("id") or fallback_scope_value, "global"
    if plugin_scope == "user" or plugin_manifest.get("user_id"):
        return plugin_manifest.get("user_id") or fallback_scope_value, "user"
    return fallback_scope_value, fallback_scope


def _resolve_action_identity_context(data, existing_plugin, user_id):
    """Resolve the authoritative identity scope for an action test or save request."""
    plugin_scope = ""
    if isinstance(existing_plugin, dict):
        plugin_scope = str(existing_plugin.get("scope") or "").strip().lower()
        if plugin_scope == "group" or existing_plugin.get("is_group"):
            active_group = require_active_group(user_id)
            assert_group_role(
                user_id,
                active_group,
                allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
            )
            return WORKSPACE_IDENTITY_SCOPE_GROUP, active_group
        if plugin_scope == "global" or existing_plugin.get("is_global"):
            if "Admin" not in session.get("user", {}).get("roles", []):
                raise PermissionError("Admin role required for global action identities")
            return WORKSPACE_IDENTITY_SCOPE_GLOBAL, WORKSPACE_IDENTITY_SCOPE_GLOBAL

    requested_scope = str((data or {}).get("action_scope") or "personal").strip().lower()
    if requested_scope in {"group", "group_action"}:
        active_group = require_active_group(user_id)
        assert_group_role(
            user_id,
            active_group,
            allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
        )
        return WORKSPACE_IDENTITY_SCOPE_GROUP, active_group
    if requested_scope in {"global", "admin"}:
        if "Admin" not in session.get("user", {}).get("roles", []):
            raise PermissionError("Admin role required for global action identities")
        return WORKSPACE_IDENTITY_SCOPE_GLOBAL, WORKSPACE_IDENTITY_SCOPE_GLOBAL
    return WORKSPACE_IDENTITY_SCOPE_PERSONAL, user_id


def _validate_action_identity_for_scope(plugin_manifest, scope_type, scope_id):
    """Validate a plugin manifest's workspace identity reference for the target action scope."""
    validate_action_identity_reference(plugin_manifest, scope_type, scope_id)


def _reject_non_admin_mcp_stdio(plugin_manifest, scope_label="personal"):
    """Block stdio MCP actions outside admin/global action management."""
    if not isinstance(plugin_manifest, dict):
        return None
    if plugin_manifest.get('type') != MCP_PLUGIN_TYPE:
        return None

    additional_fields = normalize_mcp_additional_fields(plugin_manifest.get('additionalFields', {}))
    if additional_fields.get('transport') == 'stdio':
        return f"MCP stdio transport is only available for admin-managed global actions, not {scope_label} actions."
    return None


def _hydrate_sql_test_identity(data, existing_plugin, user_id):
    """Resolve a selected workspace identity into transient SQL test credentials."""
    identity_id = str((data or {}).get("identity_id") or "").strip()
    if not identity_id:
        return None

    scope_type, scope_id = _resolve_action_identity_context(data, existing_plugin, user_id)
    test_manifest = {
        "name": "sql_connection_test",
        "type": "sql_query",
        "identity_id": identity_id,
        "auth": {"type": "identity", "identity": identity_id},
        "additionalFields": {
            "database_type": data.get("database_type"),
            "connection_string": data.get("connection_string", ""),
            "server": data.get("server", ""),
            "database": data.get("database", ""),
            "driver": data.get("driver", ""),
        },
    }
    return hydrate_action_identity_reference(
        test_manifest,
        scope_type,
        scope_id,
        return_type=SecretReturnType.VALUE,
    )


def _resolve_secret_value_for_plugin_test(value, field_name, plugin_label='plugin'):
    """Resolve a Key Vault reference for plugin test-connection flows."""
    if not isinstance(value, str) or not value:
        return value
    if not validate_secret_name_dynamic(value):
        return value

    resolved_value = retrieve_secret_from_key_vault_by_full_name(value)
    if validate_secret_name_dynamic(resolved_value):
        raise ValueError(f"Unable to resolve stored Key Vault secret for {plugin_label} field '{field_name}'.")
    return resolved_value


def _resolve_secret_value_for_sql_test(value, field_name, scope_value=None, scope="user"):
    """Resolve a Key Vault reference for SQL test-connection flows."""
    if not isinstance(value, str) or not value:
        return value
    if not validate_secret_name_dynamic(value):
        return value

    if scope_value is None:
        return _resolve_secret_value_for_plugin_test(value, field_name, plugin_label='SQL')

    return resolve_secret_reference_for_context(
        value,
        scope_value=scope_value,
        scope=scope,
        allowed_sources={"action-addset"},
        context_label=f"SQL field '{field_name}'",
    )


def _load_existing_plugin_for_test(plugin_context, user_id):
    """Load an existing plugin manifest with Key Vault reference names for edit-time plugin tests."""
    if not isinstance(plugin_context, dict):
        return None

    plugin_scope = (plugin_context.get('scope') or 'user').lower()
    plugin_identifier = plugin_context.get('id') or plugin_context.get('name')
    if not plugin_identifier:
        return None

    if plugin_scope == 'group':
        active_group = require_active_group(user_id)
        assert_group_role(
            user_id,
            active_group,
            allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
        )
        return get_group_action(active_group, plugin_identifier, return_type=SecretReturnType.NAME)

    if plugin_scope == 'global':
        return get_global_action(plugin_identifier, return_type=SecretReturnType.NAME)

    return get_personal_action(user_id, plugin_identifier, return_type=SecretReturnType.NAME)


def _load_existing_plugin_for_sql_test(plugin_context, user_id):
    """Load an existing plugin manifest with Key Vault reference names for edit-time SQL tests."""
    return _load_existing_plugin_for_test(plugin_context, user_id)

# === USER PLUGINS ENDPOINTS ===
@bpap.route('/api/user/plugins', methods=['GET'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
def get_user_plugins():
    user_id = get_current_user_id()
    # Ensure migration is complete (will migrate any remaining legacy data)
    ensure_migration_complete(user_id)
    
    # Get plugins from the new personal_actions container
    plugins = get_governed_personal_actions(user_id)
    
    # Always mark user plugins as is_global: False
    for plugin in plugins:
        plugin['is_global'] = False

    # Check global/merge toggles
    settings = get_settings()
    merge_global = settings.get('merge_global_semantic_kernel_with_workspace', False)
    if merge_global:
        # Import and get global actions from container
        filtered_global_plugins = filter_governed_global_actions_for_user(user_id, get_global_actions())

        # Mark global plugins
        for plugin in filtered_global_plugins:
            plugin['is_global'] = True
        
        # Merge plugins using ID as key to avoid name conflicts
        # This allows both personal and global plugins with same name to coexist
        all_plugins = {}
        
        # Add personal plugins first
        for plugin in plugins:
            key = f"personal_{plugin.get('id', plugin['name'])}"
            all_plugins[key] = plugin
            
        # Add global plugins
        for plugin in filtered_global_plugins:
            key = f"global_{plugin.get('id', plugin['name'])}"
            all_plugins[key] = plugin
            
        return jsonify(list(all_plugins.values()))
    else:
        return jsonify(plugins)

@bpap.route('/api/user/plugins', methods=['POST'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
@enabled_required("allow_user_plugins")
def set_user_plugins():
    user_id = get_current_user_id()
    plugins = request.json if isinstance(request.json, list) else []
    
    # Get global plugin names (case-insensitive)
    global_plugins = get_global_actions()
    global_plugin_names = set(p['name'].lower() for p in global_plugins if 'name' in p)
    
    # Get current personal actions to determine what to delete
    current_actions = get_personal_actions(user_id, return_type=SecretReturnType.NAME)
    current_action_names = set(action['name'] for action in current_actions)
    current_action_ids = {action.get('id') for action in current_actions if action.get('id')}
    
    # Filter out plugins whose name matches a global plugin name
    filtered_plugins = []
    new_plugin_names = set()
    new_plugin_ids = set()
    
    for plugin in plugins:
        if plugin.get('name', '').lower() in global_plugin_names:
            continue  # Skip global plugins
        plugin_to_save = dict(plugin)
        # Remove is_global if present
        if 'is_global' in plugin_to_save:
            del plugin_to_save['is_global']
        
        # Ensure required fields have default values
        plugin_to_save.setdefault('name', '')
        plugin_to_save.setdefault('displayName', plugin_to_save.get('name', ''))
        plugin_to_save.setdefault('description', '')
        plugin_to_save.setdefault('metadata', {})
        plugin_to_save.setdefault('additionalFields', {})
        
        # Remove storage-managed fields that are not part of the plugin manifest schema,
        # but preserve the action ID so existing records can be updated in place.
        for field in PLUGIN_STORAGE_MANAGED_FIELDS:
            if field == 'id':
                continue
            plugin_to_save.pop(field, None)
        
        # Handle endpoint based on plugin type
        plugin_type = plugin_to_save.get('type', '')
        plugin_to_save.setdefault('endpoint', '')
        _apply_plugin_runtime_defaults(plugin_to_save)
        mcp_stdio_error = _reject_non_admin_mcp_stdio(plugin_to_save, scope_label='personal')
        if mcp_stdio_error:
            return jsonify({'error': mcp_stdio_error}), 400
        try:
            _validate_action_identity_for_scope(
                plugin_to_save,
                WORKSPACE_IDENTITY_SCOPE_PERSONAL,
                user_id,
            )
        except (ValueError, LookupError, PermissionError) as exc:
            return jsonify({'error': str(exc)}), 400
        
        # Ensure auth has default structure
        if 'auth' not in plugin_to_save:
            plugin_to_save['auth'] = {'type': 'identity'}
        elif not isinstance(plugin_to_save['auth'], dict):
            plugin_to_save['auth'] = {'type': 'identity'}
        elif 'type' not in plugin_to_save['auth']:
            plugin_to_save['auth']['type'] = 'identity'
        
        # Auto-fill type from metadata if missing or empty
        if not plugin_to_save.get('type'):
            if plugin_to_save.get('metadata', {}).get('type'):
                plugin_to_save['type'] = plugin_to_save['metadata']['type']
            else:
                plugin_to_save['type'] = 'unknown'  # Default type
        
        debug_print(f"Plugin build: {_redact_plugin_for_logging(plugin_to_save)}")
        validation_error = validate_plugin(plugin_to_save)
        if validation_error:
            return jsonify({'error': f'Plugin validation failed: {validation_error}'}), 400
        
        filtered_plugins.append(plugin_to_save)
        new_plugin_names.add(plugin_to_save['name'])
        if plugin_to_save.get('id'):
            new_plugin_ids.add(plugin_to_save['id'])
    
    # Save each plugin to the personal_actions container
    plugins_to_delete = []
    try:
        for plugin in filtered_plugins:
            save_personal_action(user_id, plugin)
        
        # Delete any plugins that are no longer in the list
        for action in current_actions:
            action_id = action.get('id')
            action_name = action.get('name')
            if action_id and action_id in new_plugin_ids:
                continue
            if action_name in new_plugin_names:
                continue
            plugins_to_delete.append(action)

        for action in plugins_to_delete:
            delete_personal_action(user_id, action.get('id') or action.get('name'))
            
    except ValueError as e:
        debug_print(f"Validation error saving personal actions for user {user_id}: {e}")
        return jsonify({'error': str(e)}), 400
    except PermissionError as e:
        debug_print(f"Governance denied saving personal actions for user {user_id}: {e}")
        return jsonify({'error': str(e)}), 403
    except Exception as e:
        debug_print(f"Error saving personal actions for user {user_id}: {e}")
        return jsonify({'error': 'Failed to save plugins'}), 500

    # Log individual action activities
    for plugin in filtered_plugins:
        p_name = plugin.get('name', '')
        p_id = plugin.get('id', '')
        p_type = plugin.get('type', '')
        if (p_id and p_id in current_action_ids) or p_name in current_action_names:
            log_action_update(user_id=user_id, action_id=p_id, action_name=p_name, action_type=p_type, scope='personal')
        else:
            log_action_creation(user_id=user_id, action_id=p_id, action_name=p_name, action_type=p_type, scope='personal')
    for action in plugins_to_delete:
        action_id = action.get('id', '')
        action_name = action.get('name', '')
        log_action_deletion(user_id=user_id, action_id=action_id, action_name=action_name, scope='personal')

    log_event("User plugins updated", extra={"user_id": user_id, "plugins_count": len(filtered_plugins)})
    return jsonify({'success': True})

@bpap.route('/api/user/plugins/<plugin_name>', methods=['DELETE'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
def delete_user_plugin(plugin_name):
    user_id = get_current_user_id()

    # Try to delete from personal_actions container
    try:
        deleted = delete_personal_action(user_id, plugin_name)
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403
    
    if not deleted:
        return jsonify({'error': 'Plugin not found.'}), 404
    
    log_action_deletion(user_id=user_id, action_id=plugin_name, action_name=plugin_name, scope='personal')
    log_event("User plugin deleted", extra={"user_id": user_id, "plugin_name": plugin_name})
    return jsonify({'success': True})


# === GROUP ACTION ENDPOINTS ===

@bpap.route('/api/group/plugins', methods=['GET'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
@enabled_required('enable_group_workspaces')
def get_group_actions_route():
    user_id = get_current_user_id()
    try:
        active_group = require_active_group(user_id)
        assert_group_role(
            user_id,
            active_group,
            allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403

    actions = get_governed_group_actions(active_group, user_id, return_type=SecretReturnType.TRIGGER)

    settings = get_settings()
    merge_global = bool(settings.get('merge_global_semantic_kernel_with_workspace', False)) if settings else False

    if merge_global:
        global_actions = filter_governed_global_actions_for_user(
            user_id,
            get_global_actions(return_type=SecretReturnType.TRIGGER),
        )
        merged_actions = _merge_group_and_global_actions(actions, global_actions)
    else:
        merged_actions = [_normalize_group_action(action) for action in actions]
        merged_actions.sort(key=lambda item: (item.get('displayName') or item.get('display_name') or item.get('name') or '').lower())

    return jsonify({'actions': merged_actions}), 200


@bpap.route('/api/group/plugins/<action_id>', methods=['GET'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
@enabled_required('enable_group_workspaces')
def get_group_action_route(action_id):
    user_id = get_current_user_id()
    try:
        active_group = require_active_group(user_id)
        assert_group_role(
            user_id,
            active_group,
            allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403

    action = get_group_action(active_group, action_id, return_type=SecretReturnType.TRIGGER)
    if not action:
        return jsonify({'error': 'Action not found'}), 404
    try:
        ensure_action_type_access('governance_group_actions', user_id, action.get('type'), 'group')
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403
    return jsonify(action), 200


@bpap.route('/api/group/plugins', methods=['POST'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
@enabled_required('enable_group_workspaces')
def create_group_action_route():
    user_id = get_current_user_id()
    try:
        active_group = require_active_group(user_id)
        app_settings = get_settings()
        allowed_roles = ("Owner",) if app_settings.get('require_owner_for_group_agent_management') else ("Owner", "Admin")
        assert_group_role(user_id, active_group, allowed_roles=allowed_roles)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403

    payload = request.get_json(silent=True) or {}
    try:
        validate_group_action_payload(payload, partial=False)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    if payload.get('is_global'):
        return jsonify({'error': 'Global actions are managed centrally and cannot be created within a group.'}), 400

    for key in ('group_id', 'last_updated', 'user_id', 'is_global', 'is_group', 'scope'):
        payload.pop(key, None)

    _apply_plugin_runtime_defaults(payload)
    mcp_stdio_error = _reject_non_admin_mcp_stdio(payload, scope_label='group')
    if mcp_stdio_error:
        return jsonify({'error': mcp_stdio_error}), 400

    # Merge with schema to ensure all required fields are present (same as global actions)
    schema_dir = os.path.join(current_app.root_path, 'static', 'json', 'schemas')
    merged = get_merged_plugin_settings(payload.get('type'), payload, schema_dir)
    payload['metadata'] = merged.get('metadata', payload.get('metadata', {}))
    payload['additionalFields'] = merged.get('additionalFields', payload.get('additionalFields', {}))

    try:
        _validate_action_identity_for_scope(
            payload,
            WORKSPACE_IDENTITY_SCOPE_GROUP,
            active_group,
        )
    except (ValueError, LookupError, PermissionError) as exc:
        return jsonify({'error': str(exc)}), 400

    try:
        saved = save_group_action(active_group, payload, user_id=user_id)
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403
    except Exception as exc:
        debug_print('Failed to save group action: %s', exc)
        return jsonify({'error': 'Unable to save action'}), 500

    log_action_creation(user_id=user_id, action_id=saved.get('id', ''), action_name=saved.get('name', ''), action_type=saved.get('type', ''), scope='group', group_id=active_group)
    return jsonify(saved), 201


@bpap.route('/api/group/plugins/<action_id>', methods=['PATCH'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
@enabled_required('enable_group_workspaces')
def update_group_action_route(action_id):
    user_id = get_current_user_id()
    try:
        active_group = require_active_group(user_id)
        app_settings = get_settings()
        allowed_roles = ("Owner",) if app_settings.get('require_owner_for_group_agent_management') else ("Owner", "Admin")
        assert_group_role(user_id, active_group, allowed_roles=allowed_roles)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403

    existing = get_group_action(active_group, action_id, return_type=SecretReturnType.NAME)
    if not existing:
        return jsonify({'error': 'Action not found'}), 404

    updates = request.get_json(silent=True) or {}
    if updates.get('is_global'):
        return jsonify({'error': 'Global actions cannot be modified within a group.'}), 400

    for key in ('id', 'group_id', 'last_updated', 'user_id', 'is_global', 'is_group', 'scope'):
        updates.pop(key, None)

    try:
        validate_group_action_payload(updates, partial=True)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    merged = dict(existing)
    merged.update(updates)
    merged['is_global'] = False
    merged['is_group'] = True
    merged['id'] = existing.get('id', action_id)

    _apply_plugin_runtime_defaults(merged)
    mcp_stdio_error = _reject_non_admin_mcp_stdio(merged, scope_label='group')
    if mcp_stdio_error:
        return jsonify({'error': mcp_stdio_error}), 400

    try:
        validate_group_action_payload(merged, partial=False)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    # Merge with schema to ensure all required fields are present (same as global actions)
    schema_dir = os.path.join(current_app.root_path, 'static', 'json', 'schemas')
    schema_merged = get_merged_plugin_settings(merged.get('type'), merged, schema_dir)
    merged['metadata'] = schema_merged.get('metadata', merged.get('metadata', {}))
    merged['additionalFields'] = schema_merged.get('additionalFields', merged.get('additionalFields', {}))

    try:
        _validate_action_identity_for_scope(
            merged,
            WORKSPACE_IDENTITY_SCOPE_GROUP,
            active_group,
        )
    except (ValueError, LookupError, PermissionError) as exc:
        return jsonify({'error': str(exc)}), 400

    try:
        saved = save_group_action(active_group, merged, user_id=user_id)
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403
    except Exception as exc:
        debug_print('Failed to update group action %s: %s', action_id, exc)
        return jsonify({'error': 'Unable to update action'}), 500

    log_action_update(user_id=user_id, action_id=action_id, action_name=saved.get('name', ''), action_type=saved.get('type', ''), scope='group', group_id=active_group)
    return jsonify(saved), 200


@bpap.route('/api/group/plugins/<action_id>', methods=['DELETE'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
@enabled_required('enable_group_workspaces')
def delete_group_action_route(action_id):
    user_id = get_current_user_id()
    try:
        active_group = require_active_group(user_id)
        app_settings = get_settings()
        allowed_roles = ("Owner",) if app_settings.get('require_owner_for_group_agent_management') else ("Owner", "Admin")
        assert_group_role(user_id, active_group, allowed_roles=allowed_roles)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403

    try:
        existing = get_group_action(active_group, action_id, return_type=SecretReturnType.NAME)
        if existing:
            ensure_action_type_access('governance_group_actions', user_id, existing.get('type'), 'group')
        removed = delete_group_action(active_group, action_id)
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403
    except Exception as exc:
        debug_print('Failed to delete group action %s: %s', action_id, exc)
        return jsonify({'error': 'Unable to delete action'}), 500

    if not removed:
        return jsonify({'error': 'Action not found'}), 404
    log_action_deletion(user_id=user_id, action_id=action_id, action_name=action_id, scope='group', group_id=active_group)
    return jsonify({'message': 'Action deleted'}), 200

@bpap.route('/api/user/plugins/types', methods=['GET'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
def get_user_plugin_types():
    user_id = get_current_user_id()
    return get_plugin_types(
        allowed_type_filter=lambda action_type: is_action_type_access_allowed(
            'governance_user_actions',
            user_id,
            action_type,
            'personal',
        )
    )

# === ADMIN PLUGINS ENDPOINTS ===

# GET: Return current core plugin toggle values
@bpap.route('/api/admin/plugins/settings', methods=['GET'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
def get_core_plugin_settings():
    settings = get_settings()
    return jsonify({
        'enable_time_plugin': bool(settings.get('enable_time_plugin', True)),
        'enable_http_plugin': bool(settings.get('enable_http_plugin', True)),
        'enable_wait_plugin': bool(settings.get('enable_wait_plugin', True)),
        'enable_math_plugin': bool(settings.get('enable_math_plugin', True)),
        'enable_text_plugin': bool(settings.get('enable_text_plugin', True)),
        'enable_default_embedding_model_plugin': bool(settings.get('enable_default_embedding_model_plugin', True)),
        'enable_fact_memory_plugin': bool(settings.get('enable_fact_memory_plugin', True)),
        'enable_tabular_processing_plugin': is_tabular_processing_enabled(settings),
        'enable_enhanced_citations': bool(settings.get('enable_enhanced_citations', False)),
        'enable_semantic_kernel': bool(settings.get('enable_semantic_kernel', False)),
        'allow_user_plugins': bool(settings.get('allow_user_plugins', True)),
        'allow_group_plugins': bool(settings.get('allow_group_plugins', True)),
    })

# POST: Update core plugin toggle values
@bpap.route('/api/admin/plugins/settings', methods=['POST'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
def update_core_plugin_settings():
    data = request.get_json(force=True)
    logging.info("Received plugin settings update request: %s", data)
    # Validate input
    expected_keys = [
        'enable_time_plugin',
        'enable_http_plugin',
        'enable_wait_plugin',
        'enable_math_plugin',
        'enable_text_plugin',
        'enable_default_embedding_model_plugin',
        'enable_fact_memory_plugin',
        'allow_user_plugins',
        'allow_group_plugins'
    ]
    deprecated_optional_keys = ['enable_tabular_processing_plugin']
    updates = {}
    # Check for unexpected keys in the data payload
    for key in data:
        if key not in expected_keys and key not in deprecated_optional_keys:
            return jsonify({'error': f"Unexpected field: {key}"}), 400

    # Validate required fields and their types
    for key in expected_keys:
        if key not in data:
            return jsonify({'error': f"Missing required field: {key}"}), 400
        if not isinstance(data[key], bool):
            return jsonify({'error': f"Field '{key}' must be a boolean."}), 400
        updates[key] = data[key]
    for key in deprecated_optional_keys:
        if key in data and not isinstance(data[key], bool):
            return jsonify({'error': f"Field '{key}' must be a boolean."}), 400
    logging.info("Validated plugin settings: %s", updates)
    # Update settings
    success = update_settings(updates)
    if success:
        # --- HOT RELOAD TRIGGER ---
        setattr(builtins, "kernel_reload_needed", True)
        return jsonify({'success': True, 'updated': updates}), 200
    else:
        return jsonify({'error': 'Failed to update settings.'}), 500

@bpap.route('/api/admin/plugins', methods=['GET'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
def list_plugins():
    try:
        plugins = get_global_actions(include_disabled=True)
        log_event("List plugins", extra={"action": "list", "user": str(getattr(request, 'user', 'unknown'))})
        return jsonify(plugins)
    except Exception as e:
        log_event(f"Error listing plugins: {e}", level=logging.ERROR)
        return jsonify({'error': 'Failed to list plugins.'}), 500


@bpap.route('/api/admin/plugins/<plugin_name>/enabled', methods=['PATCH'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
def set_plugin_enabled(plugin_name):
    try:
        data = request.get_json(silent=True) or {}
        if 'is_enabled' not in data or not isinstance(data.get('is_enabled'), bool):
            return jsonify({'error': 'Field "is_enabled" must be a boolean.'}), 400

        is_enabled = data.get('is_enabled')
        plugins = get_global_actions(include_disabled=True)
        plugin_to_update = next((plugin for plugin in plugins if plugin.get('name') == plugin_name), None)
        if plugin_to_update is None:
            log_event("Toggle plugin enabled failed: not found", level=logging.WARNING, extra={"action": "toggle-enabled", "plugin_name": plugin_name})
            return jsonify({'error': 'Plugin not found.'}), 404

        result = update_global_action_enabled(
            plugin_to_update.get('id'),
            is_enabled,
            user_id=str(get_current_user_id())
        )
        if not result:
            return jsonify({'error': 'Failed to update action enabled state.'}), 500

        log_action_update(
            user_id=str(get_current_user_id()),
            action_id=plugin_to_update.get('id', ''),
            action_name=plugin_name,
            action_type=plugin_to_update.get('type', ''),
            scope='global'
        )
        log_event(
            "Plugin enabled state updated",
            extra={
                "action": "toggle-enabled",
                "plugin_name": plugin_name,
                "plugin_id": plugin_to_update.get('id', ''),
                "is_enabled": is_enabled,
                "user": str(get_current_user_id())
            }
        )
        setattr(builtins, "kernel_reload_needed", True)
        return jsonify({'success': True})
    except Exception as e:
        log_event(f"Error updating plugin enabled state: {e}", level=logging.ERROR)
        return jsonify({'error': 'Failed to update action enabled state.'}), 500

@bpap.route('/api/admin/plugins', methods=['POST'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
def add_plugin():
    try:
        plugins = get_global_actions(include_disabled=True)
        new_plugin = request.get_json(silent=True) or {}
        governance_policy_payload = new_plugin.pop('governance_policy', None) if isinstance(new_plugin, dict) else None
        _apply_plugin_runtime_defaults(new_plugin)
        new_plugin = apply_plugin_validation_defaults(new_plugin)
        
        # Strict validation with dynamic allowed types
        allowed_types = discover_plugin_types()
        validation_error = validate_plugin(new_plugin)
        if validation_error:
            log_event("Add plugin failed: validation error", level=logging.WARNING, extra={"action": "add", "plugin": _redact_plugin_for_logging(new_plugin), "error": validation_error})
            return jsonify({'error': validation_error}), 400
        
        if allowed_types is not None and new_plugin.get('type') not in allowed_types:
            return jsonify({'error': f"Invalid plugin type: {new_plugin.get('type')}"}), 400
        
        # Enhanced manifest validation using health checker
        plugin_type = new_plugin.get('type', '')
        is_valid, validation_errors = PluginHealthChecker.validate_plugin_manifest(new_plugin, plugin_type)
        if not is_valid:
            log_event("Add plugin failed: manifest validation error", level=logging.WARNING, 
                     extra={"action": "add", "plugin": _redact_plugin_for_logging(new_plugin), "errors": validation_errors})
            return jsonify({'error': f"Manifest validation failed: {'; '.join(validation_errors)}"}), 400
        
        # Merge with schema to ensure all required fields are present
        schema_dir = os.path.join(current_app.root_path, 'static', 'json', 'schemas')
        merged = get_merged_plugin_settings(new_plugin.get('type'), new_plugin, schema_dir)
        new_plugin['metadata'] = merged.get('metadata', new_plugin.get('metadata', {}))
        new_plugin['additionalFields'] = merged.get('additionalFields', new_plugin.get('additionalFields', {}))

        try:
            _validate_action_identity_for_scope(
                new_plugin,
                WORKSPACE_IDENTITY_SCOPE_GLOBAL,
                WORKSPACE_IDENTITY_SCOPE_GLOBAL,
            )
        except (ValueError, LookupError, PermissionError) as exc:
            return jsonify({'error': str(exc)}), 400
        
        # Prevent duplicate names (case-insensitive)
        if any(p['name'].lower() == new_plugin['name'].lower() for p in plugins):
            log_event("Add plugin failed: duplicate name", level=logging.WARNING, extra={"action": "add", "plugin": _redact_plugin_for_logging(new_plugin)})
            return jsonify({'error': 'Plugin with this name already exists.'}), 400
        
        # Assign a unique ID
        plugin_id = str(uuid.uuid4())
        new_plugin['id'] = plugin_id
        
        # Save to global actions container
        save_global_action(new_plugin, user_id=str(get_current_user_id()))

        if isinstance(governance_policy_payload, dict):
            upsert_item_policy(
                entity_type='global_action',
                item_id=plugin_id,
                payload=governance_policy_payload,
                actor_user_id=str(get_current_user_id() or ''),
                actor_email=str((session.get('user') or {}).get('email') or ''),
            )
        
        log_action_creation(user_id=str(get_current_user_id()), action_id=plugin_id, action_name=new_plugin.get('name', ''), action_type=new_plugin.get('type', ''), scope='global')
        log_event("Plugin added", extra={"action": "add", "plugin": _redact_plugin_for_logging(new_plugin), "user": str(get_current_user_id())})
        
        # --- HOT RELOAD TRIGGER ---
        setattr(builtins, "kernel_reload_needed", True)
        return jsonify({'success': True})
    except Exception as e:
        log_event(f"Error adding plugin: {e}", level=logging.ERROR)
        return jsonify({'error': 'Failed to add plugin.'}), 500

@bpap.route('/api/admin/plugins/<plugin_name>', methods=['PUT'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
def edit_plugin(plugin_name):
    try:
        plugins = get_global_actions(include_disabled=True)
        updated_plugin = request.get_json(silent=True) or {}
        governance_policy_payload = updated_plugin.pop('governance_policy', None) if isinstance(updated_plugin, dict) else None
        _apply_plugin_runtime_defaults(updated_plugin)
        updated_plugin = apply_plugin_validation_defaults(updated_plugin)
        
        # Strict validation with dynamic allowed types
        allowed_types = discover_plugin_types()
        validation_error = validate_plugin(updated_plugin)
        if validation_error:
            log_event("Edit plugin failed: validation error", level=logging.WARNING, extra={"action": "edit", "plugin": _redact_plugin_for_logging(updated_plugin), "error": validation_error})
            return jsonify({'error': validation_error}), 400
        
        if allowed_types is not None and updated_plugin.get('type') not in allowed_types:
            return jsonify({'error': f"Invalid plugin type: {updated_plugin.get('type')}"}), 400
        
        # Enhanced manifest validation using health checker
        plugin_type = updated_plugin.get('type', '')
        is_valid, validation_errors = PluginHealthChecker.validate_plugin_manifest(updated_plugin, plugin_type)
        if not is_valid:
            log_event("Edit plugin failed: manifest validation error", level=logging.WARNING, 
                     extra={"action": "edit", "plugin": _redact_plugin_for_logging(updated_plugin), "errors": validation_errors})
            return jsonify({'error': f"Manifest validation failed: {'; '.join(validation_errors)}"}), 400
        
        # Merge with schema to ensure all required fields are present
        schema_dir = os.path.join(current_app.root_path, 'static', 'json', 'schemas')
        merged = get_merged_plugin_settings(updated_plugin.get('type'), updated_plugin, schema_dir)
        updated_plugin['metadata'] = merged.get('metadata', updated_plugin.get('metadata', {}))
        updated_plugin['additionalFields'] = merged.get('additionalFields', updated_plugin.get('additionalFields', {}))

        try:
            _validate_action_identity_for_scope(
                updated_plugin,
                WORKSPACE_IDENTITY_SCOPE_GLOBAL,
                WORKSPACE_IDENTITY_SCOPE_GLOBAL,
            )
        except (ValueError, LookupError, PermissionError) as exc:
            return jsonify({'error': str(exc)}), 400
        
        # Find the plugin by name and update it
        found_plugin = None
        for p in plugins:
            if p['name'] == plugin_name:
                found_plugin = p
                break
        
        if found_plugin:
            duplicate_name = updated_plugin.get('name', '').lower()
            if duplicate_name and any(
                p.get('name', '').lower() == duplicate_name and p.get('id') != found_plugin.get('id')
                for p in plugins
            ):
                log_event("Edit plugin failed: duplicate name", level=logging.WARNING, extra={"action": "edit", "plugin": _redact_plugin_for_logging(updated_plugin)})
                return jsonify({'error': 'Plugin with this name already exists.'}), 400

            # Preserve the existing ID if it exists
            if 'id' in found_plugin:
                updated_plugin['id'] = found_plugin['id']
            else:
                updated_plugin['id'] = str(uuid.uuid4())
            
            save_global_action(updated_plugin, user_id=str(get_current_user_id()))

            if isinstance(governance_policy_payload, dict):
                upsert_item_policy(
                    entity_type='global_action',
                    item_id=str(updated_plugin.get('id') or ''),
                    payload=governance_policy_payload,
                    actor_user_id=str(get_current_user_id() or ''),
                    actor_email=str((session.get('user') or {}).get('email') or ''),
                )
            
            log_action_update(user_id=str(get_current_user_id()), action_id=updated_plugin.get('id', ''), action_name=plugin_name, action_type=updated_plugin.get('type', ''), scope='global')
            log_event("Plugin edited", extra={"action": "edit", "plugin": _redact_plugin_for_logging(updated_plugin), "user": str(get_current_user_id())})
            # --- HOT RELOAD TRIGGER ---
            setattr(builtins, "kernel_reload_needed", True)
            return jsonify({'success': True})
        
        log_event("Edit plugin failed: not found", level=logging.WARNING, extra={"action": "edit", "plugin_name": plugin_name})
        return jsonify({'error': 'Plugin not found.'}), 404
    except Exception as e:
        log_event(f"Error editing plugin: {e}", level=logging.ERROR)
        return jsonify({'error': 'Failed to edit plugin.'}), 500

@bpap.route('/api/admin/plugins/types', methods=['GET'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
def get_admin_plugin_types():
    return get_plugin_types()

@bpap.route('/api/admin/plugins/<plugin_name>', methods=['DELETE'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
def delete_plugin(plugin_name):
    try:
        plugins = get_global_actions(include_disabled=True)
        
        # Find the plugin by name
        plugin_to_delete = None
        for p in plugins:
            if p['name'] == plugin_name:
                plugin_to_delete = p
                break
        
        if plugin_to_delete is None:
            log_event("Delete plugin failed: not found", level=logging.WARNING, extra={"action": "delete", "plugin_name": plugin_name})
            return jsonify({'error': 'Plugin not found.'}), 404
        
        # Delete from container if it has an ID
        if 'id' in plugin_to_delete:
            delete_global_action(plugin_to_delete['id'])
        
        log_action_deletion(user_id=str(get_current_user_id()), action_id=plugin_to_delete.get('id', ''), action_name=plugin_name, action_type=plugin_to_delete.get('type', ''), scope='global')
        log_event("Plugin deleted", extra={"action": "delete", "plugin_name": plugin_name, "user": str(get_current_user_id())})
        # --- HOT RELOAD TRIGGER ---
        setattr(builtins, "kernel_reload_needed", True)
        return jsonify({'success': True})
    except Exception as e:
        log_event(f"Error deleting plugin: {e}", level=logging.ERROR)
        return jsonify({'error': 'Failed to delete plugin.'}), 500
    

# === PLUGIN SETTINGS MERGE ENDPOINT ===
@bpap.route('/api/plugins/<plugin_type>/merge_settings', methods=['POST'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
def merge_plugin_settings(plugin_type):
    """
    Accepts current settings (JSON body), merges with schema defaults, returns merged settings.
    """
    # Accepts: { ...current settings... }
    current_settings = request.get_json(force=True)
    # Path to schemas
    schema_dir = os.path.join(current_app.root_path, 'static', 'json', 'schemas')
    merged = get_merged_plugin_settings(plugin_type, current_settings, schema_dir)
    return jsonify(merged)


@bpap.route('/api/plugins/<plugin_type>/auth-types', methods=['GET'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
def get_plugin_auth_types(plugin_type):
    """
    Returns allowed auth types for a plugin type. Uses definition file if present,
    otherwise falls back to AuthType enum in plugin.schema.json.
    """
    schema_dir = os.path.join(current_app.root_path, 'static', 'json', 'schemas')
    safe_type = re.sub(r'[^a-zA-Z0-9_]', '_', plugin_type).lower()

    definition_path = os.path.join(schema_dir, f'{safe_type}.definition.json')
    schema_path = os.path.join(schema_dir, 'plugin.schema.json')

    allowed_auth_types = []
    source = "schema"

    try:
        with open(schema_path, 'r', encoding='utf-8') as schema_file:
            schema = json.load(schema_file)
        allowed_auth_types = (
            schema
            .get('definitions', {})
            .get('AuthType', {})
            .get('enum', [])
        )
    except Exception as exc:
        debug_print(f"Failed to read plugin.schema.json: {exc}")
        allowed_auth_types = []

    if os.path.exists(definition_path):
        try:
            with open(definition_path, 'r', encoding='utf-8') as definition_file:
                definition = json.load(definition_file)
            allowed_from_definition = definition.get('allowedAuthTypes')
            if isinstance(allowed_from_definition, list) and allowed_from_definition:
                allowed_auth_types = allowed_from_definition
                source = "definition"
        except Exception as exc:
            debug_print(f"Failed to read {definition_path}: {exc}")

    if not allowed_auth_types:
        allowed_auth_types = []
        source = "schema"

    return jsonify({
        "allowedAuthTypes": allowed_auth_types,
        "source": source
    })


@bpap.route('/api/plugins/mcp/discover', methods=['POST'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
def discover_mcp_tools():
    """Discover tools from an MCP server using a transient action manifest."""
    user_id = get_current_user_id()
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({'error': 'Invalid MCP discovery payload.'}), 400

    try:
        existing_plugin = _load_existing_plugin_for_test(payload.get('plugin_context'), user_id)
        scope_type, scope_id = _resolve_action_identity_context(payload, existing_plugin, user_id)

        discovery_manifest = dict(payload)
        discovery_manifest['type'] = MCP_PLUGIN_TYPE
        discovery_manifest.setdefault('name', 'mcp_discovery')
        discovery_manifest.setdefault('displayName', 'MCP Discovery')
        discovery_manifest.setdefault('description', 'Transient MCP discovery manifest')
        discovery_manifest.setdefault('metadata', {})
        discovery_manifest.setdefault('additionalFields', {})
        _apply_plugin_runtime_defaults(discovery_manifest)
        if discovery_manifest.get('additionalFields', {}).get('transport') == 'stdio' and scope_type != WORKSPACE_IDENTITY_SCOPE_GLOBAL:
            return jsonify({'error': 'MCP stdio discovery is only available for admin-managed global actions.'}), 403

        auth = discovery_manifest.get('auth') if isinstance(discovery_manifest.get('auth'), dict) else {}
        existing_auth = existing_plugin.get('auth') if isinstance(existing_plugin, dict) and isinstance(existing_plugin.get('auth'), dict) else {}
        if auth.get('key') in ('', None, ui_trigger_word) and existing_auth.get('key'):
            auth['key'] = existing_auth.get('key')
        if auth.get('identity') in ('', None) and existing_auth.get('identity'):
            auth['identity'] = existing_auth.get('identity')
        discovery_manifest['auth'] = auth

        if discovery_manifest.get('identity_id'):
            discovery_manifest = hydrate_action_identity_reference(
                discovery_manifest,
                scope_type,
                scope_id,
                return_type=SecretReturnType.VALUE,
            )
        else:
            auth = discovery_manifest.get('auth') if isinstance(discovery_manifest.get('auth'), dict) else {}
            if auth.get('key'):
                auth['key'] = _resolve_secret_value_for_plugin_test(auth.get('key'), 'auth.key', plugin_label='MCP')
            discovery_manifest['auth'] = auth

        is_valid, validation_errors = PluginHealthChecker.validate_plugin_manifest(discovery_manifest, MCP_PLUGIN_TYPE)
        if not is_valid:
            return jsonify({
                'success': False,
                'error': 'MCP discovery manifest is invalid.',
                'errors': validation_errors,
            }), 400

        tools = asyncio.run(McpPluginFactory.discover_tools_from_config(discovery_manifest))
        log_event(
            "[MCP Discovery] Discovered MCP tools",
            extra={
                "user_id": user_id,
                "tool_count": len(tools),
                "transport": discovery_manifest.get('additionalFields', {}).get('transport'),
            },
            level=logging.INFO,
        )
        return jsonify({
            'success': True,
            'tool_count': len(tools),
            'tools': tools,
        })
    except PermissionError as exc:
        return jsonify({'error': str(exc)}), 403
    except (LookupError, ValueError) as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        log_event(
            f"[MCP Discovery] Failed to discover MCP tools: {exc}",
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return jsonify({'error': 'Failed to discover MCP tools.'}), 500

##########################################################################################################
# Dynamic Plugin Metadata Endpoint

bpdp = Blueprint('dynamic_plugins', __name__)

@bpdp.route('/api/admin/plugins/dynamic', methods=['GET'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
def list_dynamic_plugins():
    """
    Returns metadata for all available plugin types (not registrations).
    """
    plugins = get_all_plugin_metadata()
    return jsonify(plugins)

# Helper functions for group/global action merging
def _normalize_group_action(action: dict) -> dict:
    normalized = dict(action)
    normalized['is_global'] = False
    normalized['is_group'] = True
    normalized.setdefault('scope', 'group')
    return normalized


def _normalize_global_action(action: dict) -> dict:
    normalized = dict(action)
    normalized['is_global'] = True
    normalized['is_group'] = False
    normalized.setdefault('scope', 'global')
    return normalized


def _merge_group_and_global_actions(group_actions, global_actions):
    normalized_actions = []
    seen_names = set()

    for action in group_actions:
        normalized = _normalize_group_action(action)
        action_name = (normalized.get('name') or '').lower()
        if action_name:
            seen_names.add(action_name)
        normalized_actions.append(normalized)

    for action in global_actions:
        normalized = _normalize_global_action(action)
        action_name = (normalized.get('name') or '').lower()
        if action_name and action_name in seen_names:
            continue
        normalized_actions.append(normalized)

    normalized_actions.sort(key=lambda item: (item.get('displayName') or item.get('display_name') or item.get('name') or '').lower())
    return normalized_actions


@bpap.route('/api/plugins/test-sql-connection', methods=['POST'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
def test_sql_connection():
    """Test a SQL database connection using provided configuration."""
    data = request.get_json(silent=True) or {}
    user_id = get_current_user_id()
    database_type = (data.get('database_type') or 'sqlserver').lower()
    connection_method = data.get('connection_method', 'parameters')
    connection_string = data.get('connection_string', '')
    server = data.get('server', '')
    database = data.get('database', '')
    port = data.get('port', '')
    driver = data.get('driver', '')
    username = data.get('username', '')
    password = data.get('password', '')
    auth_type = data.get('auth_type', 'username_password')
    timeout = min(int(data.get('timeout', 10)), 15)  # Cap at 15 seconds for test

    try:
        existing_plugin = _load_existing_plugin_for_sql_test(data.get('existing_plugin'), user_id)
    except PermissionError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 403
    except LookupError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    existing_additional_fields = {}
    if isinstance(existing_plugin, dict) and isinstance(existing_plugin.get('additionalFields'), dict):
        existing_additional_fields = existing_plugin['additionalFields']

    if connection_string == ui_trigger_word:
        connection_string = existing_additional_fields.get('connection_string', '')
    if password == ui_trigger_word:
        password = existing_additional_fields.get('password', '')

    try:
        identity_manifest = _hydrate_sql_test_identity(data, existing_plugin, user_id)
    except PermissionError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 403
    except LookupError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    if identity_manifest:
        identity_additional_fields = identity_manifest.get('additionalFields') or {}
        identity_auth = identity_manifest.get('auth') or {}
        auth_type = identity_additional_fields.get('auth_type') or identity_additional_fields.get('identity_auth_type') or auth_type
        connection_string = identity_additional_fields.get('connection_string') or connection_string
        username = identity_additional_fields.get('username') or username
        password = identity_additional_fields.get('password') or password
        if identity_auth.get('type') == 'connection_string' or auth_type == 'connection_string':
            auth_type = 'connection_string_only'
            connection_method = 'connection_string'
        elif identity_auth.get('type') == 'identity' and identity_auth.get('identity') == 'managed_identity':
            auth_type = 'managed_identity'
        elif identity_auth.get('type') == 'user':
            auth_type = 'username_password'

    unresolved_fields = []
    if connection_string == ui_trigger_word:
        unresolved_fields.append('connection string')
    if password == ui_trigger_word:
        unresolved_fields.append('password')
    if unresolved_fields:
        field_list = ', '.join(unresolved_fields)
        return jsonify({'success': False, 'error': f"Stored SQL secret could not be resolved for testing. Re-enter the {field_list}."}), 400

    plugin_scope_value, plugin_scope = _resolve_plugin_secret_context(existing_plugin, user_id)

    try:
        connection_string = _resolve_secret_value_for_sql_test(
            connection_string,
            'connection_string',
            scope_value=plugin_scope_value,
            scope=plugin_scope,
        )
        password = _resolve_secret_value_for_sql_test(
            password,
            'password',
            scope_value=plugin_scope_value,
            scope=plugin_scope,
        )
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    # Map azure_sql to sqlserver
    if database_type in ('azure_sql', 'azuresql'):
        database_type = 'sqlserver'

    try:
        if database_type == 'sqlserver':
            import pyodbc
            if connection_method == 'connection_string' and connection_string:
                conn = connect_with_sql_server_odbc_fallback(
                    pyodbc.connect,
                    connection_string,
                    connect_kwargs={"timeout": timeout},
                    log_source="PluginSqlConnectionTest",
                )
            else:
                if not server or not database:
                    return jsonify({'success': False, 'error': 'Server and database are required for individual parameters connection.'}), 400
                conn_str = build_sql_server_odbc_connection_string(
                    server=server,
                    database=database,
                    driver=driver or DEFAULT_SQL_SERVER_ODBC_DRIVER,
                    port=port,
                    username=username if auth_type == 'username_password' else None,
                    password=password if auth_type == 'username_password' else None,
                    auth_type=auth_type,
                )
                conn = connect_with_sql_server_odbc_fallback(
                    pyodbc.connect,
                    conn_str,
                    connect_kwargs={"timeout": timeout},
                    log_source="PluginSqlConnectionTest",
                )
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            return jsonify({'success': True, 'message': f'Successfully connected to {data.get("database", "database")} on {data.get("server", "server")}.'})

        elif database_type == 'postgresql':
            import psycopg2
            if connection_method == 'connection_string' and connection_string:
                conn = psycopg2.connect(connection_string, connect_timeout=timeout)
            else:
                if not server or not database:
                    return jsonify({'success': False, 'error': 'Server and database are required.'}), 400
                conn_params = {'host': server, 'database': database, 'connect_timeout': timeout}
                if port:
                    conn_params['port'] = int(port)
                if username:
                    conn_params['user'] = username
                if password:
                    conn_params['password'] = password
                conn = psycopg2.connect(**conn_params)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            return jsonify({'success': True, 'message': f'Successfully connected to PostgreSQL database {data.get("database", "")}.'})

        elif database_type == 'mysql':
            import pymysql
            if connection_method == 'connection_string' and connection_string:
                # pymysql doesn't natively parse connection strings, so use params
                return jsonify({'success': False, 'error': 'MySQL test connection requires individual parameters, not a connection string.'}), 400
            if not server or not database:
                return jsonify({'success': False, 'error': 'Server and database are required.'}), 400
            conn_params = {'host': server, 'database': database, 'connect_timeout': timeout}
            if port:
                conn_params['port'] = int(port)
            if username:
                conn_params['user'] = username
            if password:
                conn_params['password'] = password
            conn = pymysql.connect(**conn_params)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            return jsonify({'success': True, 'message': f'Successfully connected to MySQL database {data.get("database", "")}.'})

        elif database_type == 'sqlite':
            import sqlite3
            db_path = connection_string or database
            if not db_path:
                return jsonify({'success': False, 'error': 'Database path is required for SQLite.'}), 400
            conn = sqlite3.connect(db_path, timeout=timeout)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            return jsonify({'success': True, 'message': f'Successfully connected to SQLite database.'})

        else:
            return jsonify({'success': False, 'error': f'Unsupported database type: {database_type}'}), 400

    except ImportError as e:
        if database_type == 'sqlserver' and 'libodbc' in str(e):
            return jsonify({
                'success': False,
                'error': 'Database driver not installed: the container image is missing the unixODBC runtime required for SQL Server connections.'
            }), 400
        return jsonify({'success': False, 'error': f'Database driver not installed: {str(e)}'}), 400
    except Exception as e:
        error_msg = str(e)
        if database_type == 'sqlserver' and "Can't open lib 'ODBC Driver 17 for SQL Server'" in error_msg:
            error_msg = 'The selected ODBC Driver 17 is not installed in this container image. Select ODBC Driver 18 for SQL Server or rebuild the image with Driver 17.'
        # Sanitize error message to avoid leaking sensitive details
        if 'password' in error_msg.lower() or 'pwd' in error_msg.lower():
            error_msg = 'Authentication failed. Please check your credentials.'
        return jsonify({'success': False, 'error': f'Connection failed: {error_msg}'}), 400


@bpap.route('/api/plugins/test-cosmos-connection', methods=['POST'])
@swagger_route(security=get_auth_security())
@login_required
@user_required
def test_cosmos_connection():
    """Test an Azure Cosmos DB for NoSQL connection using managed identity or an account key."""
    data = request.get_json(silent=True) or {}
    user_id = get_current_user_id()
    endpoint = (data.get('endpoint') or '').strip()
    database_name = (data.get('database_name') or '').strip()
    container_name = (data.get('container_name') or '').strip()
    auth_type = (data.get('auth_type') or 'identity').strip().lower()
    auth_key = (data.get('auth_key') or '').strip()
    timeout = min(max(int(data.get('timeout', 10)), 1), 30)

    if auth_type == 'managed_identity':
        auth_type = 'identity'

    if not endpoint:
        return jsonify({'success': False, 'error': 'Cosmos DB account endpoint is required.'}), 400
    if not database_name:
        return jsonify({'success': False, 'error': 'Database name is required.'}), 400
    if not container_name:
        return jsonify({'success': False, 'error': 'Container name is required.'}), 400

    try:
        existing_plugin = _load_existing_plugin_for_test(data.get('existing_plugin'), user_id)
    except PermissionError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 403
    except LookupError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    existing_auth = {}
    if isinstance(existing_plugin, dict) and isinstance(existing_plugin.get('auth'), dict):
        existing_auth = existing_plugin['auth']

    if auth_type == 'key':
        if auth_key == ui_trigger_word:
            auth_key = existing_auth.get('key', '')

        if auth_key == ui_trigger_word:
            return jsonify({'success': False, 'error': 'Stored Cosmos DB account key could not be resolved for testing. Re-enter the account key.'}), 400

        try:
            auth_key = _resolve_secret_value_for_plugin_test(auth_key, 'auth.key', plugin_label='Cosmos DB')
        except ValueError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 400

        if not auth_key:
            return jsonify({'success': False, 'error': 'Account key is required when using key authentication.'}), 400
    elif auth_type != 'identity':
        return jsonify({'success': False, 'error': "Cosmos DB auth_type must be either 'identity' or 'key'."}), 400

    try:
        headers = {}

        def capture_response_headers(response_headers, _):
            headers.clear()
            headers.update(response_headers)

        client = CosmosClient(
            endpoint,
            credential=DefaultAzureCredential() if auth_type == 'identity' else auth_key,
            timeout=timeout,
            connection_timeout=timeout,
        )
        database_client = client.get_database_client(database_name)
        database_client.read()
        container_client = database_client.get_container_client(container_name)
        container_client.read()
        list(
            container_client.query_items(
                query='SELECT TOP 1 VALUE c.id FROM c',
                enable_cross_partition_query=True,
                max_item_count=1,
                response_hook=capture_response_headers,
            )
        )

        log_event(
            '[Plugins] Cosmos connection test succeeded',
            extra={
                'user_id': user_id,
                'endpoint': endpoint,
                'database_name': database_name,
                'container_name': container_name,
                'auth_type': auth_type,
                'request_charge': headers.get('x-ms-request-charge'),
            },
            level=logging.INFO,
        )
        return jsonify({
            'success': True,
            'message': f'Successfully connected to Cosmos DB container {container_name} in database {database_name}.'
        })
    except CosmosHttpResponseError as exc:
        status_code = getattr(exc, 'status_code', None)
        if status_code in (401, 403):
            if auth_type == 'key':
                error_msg = 'Account key authentication failed. Verify the Cosmos DB account key and confirm key-based access is enabled for this account.'
            else:
                error_msg = 'Managed identity authentication or authorization failed. Ensure the application identity has Azure Cosmos DB built-in data reader access.'
            status = 403
        elif status_code == 404:
            error_msg = 'The configured database or container was not found at the specified account endpoint.'
            status = 404
        else:
            error_msg = f'Cosmos DB connection failed: {str(exc)}'
            status = 400

        log_event(
            f'[Plugins] Cosmos connection test failed: {exc}',
            extra={
                'user_id': user_id,
                'endpoint': endpoint,
                'database_name': database_name,
                'container_name': container_name,
                'auth_type': auth_type,
                'status_code': status_code,
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return jsonify({'success': False, 'error': error_msg}), status
    except Exception as exc:
        log_event(
            f'[Plugins] Cosmos connection test failed unexpectedly: {exc}',
            extra={
                'user_id': user_id,
                'endpoint': endpoint,
                'database_name': database_name,
                'container_name': container_name,
                'auth_type': auth_type,
            },
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return jsonify({
            'success': False,
            'error': 'Cosmos DB authentication failed or the account could not be reached. Verify the endpoint and the selected authentication settings.'
        }), 400
