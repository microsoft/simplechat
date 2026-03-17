#route_backlend_plugins.py

import re
import builtins
import json
from flask import Blueprint, jsonify, request, current_app
from semantic_kernel_plugins.plugin_loader import get_all_plugin_metadata
from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker, PluginErrorRecovery
from functions_settings import get_settings, update_settings
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
    get_group_action,
    save_group_action,
    delete_group_action,
    validate_group_action_payload,
)
from functions_keyvault import (
    SecretReturnType,
    redact_plugin_secret_values,
    retrieve_secret_from_key_vault_by_full_name,
    ui_trigger_word,
    validate_secret_name_dynamic,
)
#from functions_personal_actions import delete_personal_action

from functions_debug import debug_print
from json_schema_validation import validate_plugin
from functions_activity_logging import (
    log_action_creation,
    log_action_update,
    log_action_deletion,
)

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

def get_plugin_types():
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
                                'endpoint': 'https://example.databricks.com',
                                'auth': {'type': 'key', 'key': 'dummy'},
                                'additionalFields': {'table': 'example', 'columns': [], 'warehouse_id': 'dummy'},
                                'metadata': {'description': 'Example Databricks plugin'}
                            }
                        elif 'sql' in module_name.lower():
                            safe_manifest = {
                                'database_type': 'sqlite',
                                'connection_string': ':memory:',
                                'metadata': {'description': 'Example SQL plugin'}
                            }
                        elif any(x in module_name.lower() for x in ['azure_function', 'blob_storage', 'queue_storage']):
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
    print("[PLUGIN DISCOVERY DEBUG]", *debug_log, sep="\n")
    return jsonify(types)

bpap = Blueprint('admin_plugins', __name__)


def _redact_plugin_for_logging(plugin):
    """Return a plugin manifest with secret-bearing values redacted for logging."""
    if not isinstance(plugin, dict):
        return plugin
    return redact_plugin_secret_values(plugin)


def _resolve_secret_value_for_sql_test(value, field_name):
    """Resolve a Key Vault reference for SQL test-connection flows."""
    if not isinstance(value, str) or not value:
        return value
    if not validate_secret_name_dynamic(value):
        return value

    resolved_value = retrieve_secret_from_key_vault_by_full_name(value)
    if validate_secret_name_dynamic(resolved_value):
        raise ValueError(f"Unable to resolve stored Key Vault secret for SQL field '{field_name}'.")
    return resolved_value


def _load_existing_plugin_for_sql_test(plugin_context, user_id):
    """Load an existing plugin manifest with Key Vault reference names for edit-time SQL tests."""
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

# === USER PLUGINS ENDPOINTS ===
@bpap.route('/api/user/plugins', methods=['GET'])
@swagger_route(security=get_auth_security())
@login_required
def get_user_plugins():
    user_id = get_current_user_id()
    # Ensure migration is complete (will migrate any remaining legacy data)
    ensure_migration_complete(user_id)
    
    # Get plugins from the new personal_actions container
    plugins = get_personal_actions(user_id)
    
    # Always mark user plugins as is_global: False
    for plugin in plugins:
        plugin['is_global'] = False

    # Check global/merge toggles
    settings = get_settings()
    merge_global = settings.get('merge_global_semantic_kernel_with_workspace', False)
    if merge_global:
        # Import and get global actions from container
        global_plugins = get_global_actions()
        # Mark global plugins
        for plugin in global_plugins:
            plugin['is_global'] = True
        
        # Merge plugins using ID as key to avoid name conflicts
        # This allows both personal and global plugins with same name to coexist
        all_plugins = {}
        
        # Add personal plugins first
        for plugin in plugins:
            key = f"personal_{plugin.get('id', plugin['name'])}"
            all_plugins[key] = plugin
            
        # Add global plugins
        for plugin in global_plugins:
            key = f"global_{plugin.get('id', plugin['name'])}"
            all_plugins[key] = plugin
            
        return jsonify(list(all_plugins.values()))
    else:
        return jsonify(plugins)

@bpap.route('/api/user/plugins', methods=['POST'])
@swagger_route(security=get_auth_security())
@login_required
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
        # Remove is_global if present
        if 'is_global' in plugin:
            del plugin['is_global']
        
        # Ensure required fields have default values
        plugin.setdefault('name', '')
        plugin.setdefault('displayName', plugin.get('name', ''))
        plugin.setdefault('description', '')
        plugin.setdefault('metadata', {})
        plugin.setdefault('additionalFields', {})
        
        # Remove Cosmos DB system fields that are not part of the plugin schema
        cosmos_fields = ['_attachments', '_etag', '_rid', '_self', '_ts', 'created_at', 'updated_at', 'user_id', 'last_updated']
        for field in cosmos_fields:
            if field in plugin:
                del plugin[field]
        
        # Handle endpoint based on plugin type
        plugin_type = plugin.get('type', '')
        if plugin_type in ['sql_schema', 'sql_query']:
            # SQL plugins don't use endpoints, but schema validation requires one
            # Use a placeholder that indicates it's a SQL plugin
            plugin.setdefault('endpoint', f'sql://{plugin_type}')
        elif plugin_type == 'msgraph':
            # MS Graph plugin does not require an endpoint, but schema validation requires one
            #TODO: Update to support different clouds
            plugin.setdefault('endpoint', 'https://graph.microsoft.com')
        else:
            # For other plugin types, require a real endpoint
            plugin.setdefault('endpoint', '')
        
        # Ensure auth has default structure
        if 'auth' not in plugin:
            plugin['auth'] = {'type': 'identity'}
        elif not isinstance(plugin['auth'], dict):
            plugin['auth'] = {'type': 'identity'}
        elif 'type' not in plugin['auth']:
            plugin['auth']['type'] = 'identity'
        
        # Auto-fill type from metadata if missing or empty
        if not plugin.get('type'):
            if plugin.get('metadata', {}).get('type'):
                plugin['type'] = plugin['metadata']['type']
            else:
                plugin['type'] = 'unknown'  # Default type
        
        debug_print(f"Plugin build: {_redact_plugin_for_logging(plugin)}")
        validation_error = validate_plugin(plugin)
        if validation_error:
            return jsonify({'error': f'Plugin validation failed: {validation_error}'}), 400
        
        filtered_plugins.append(plugin)
        new_plugin_names.add(plugin['name'])
        if plugin.get('id'):
            new_plugin_ids.add(plugin['id'])
    
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
def delete_user_plugin(plugin_name):
    user_id = get_current_user_id()
    
    # Try to delete from personal_actions container
    deleted = delete_personal_action(user_id, plugin_name)
    
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

    actions = get_group_actions(active_group, return_type=SecretReturnType.TRIGGER)

    settings = get_settings()
    merge_global = bool(settings.get('merge_global_semantic_kernel_with_workspace', False)) if settings else False

    if merge_global:
        global_actions = get_global_actions(return_type=SecretReturnType.TRIGGER)
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

    # Handle endpoint based on plugin type (same logic as personal plugins)
    plugin_type = payload.get('type', '')
    if plugin_type in ['sql_schema', 'sql_query']:
        payload.setdefault('endpoint', f'sql://{plugin_type}')
    elif plugin_type == 'msgraph':
        payload.setdefault('endpoint', 'https://graph.microsoft.com')

    # Merge with schema to ensure all required fields are present (same as global actions)
    schema_dir = os.path.join(current_app.root_path, 'static', 'json', 'schemas')
    merged = get_merged_plugin_settings(payload.get('type'), payload, schema_dir)
    payload['metadata'] = merged.get('metadata', payload.get('metadata', {}))
    payload['additionalFields'] = merged.get('additionalFields', payload.get('additionalFields', {}))

    try:
        saved = save_group_action(active_group, payload, user_id=user_id)
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

    # Handle endpoint based on plugin type (same logic as personal plugins)
    plugin_type = merged.get('type', '')
    if plugin_type in ['sql_schema', 'sql_query']:
        merged.setdefault('endpoint', f'sql://{plugin_type}')
    elif plugin_type == 'msgraph':
        merged.setdefault('endpoint', 'https://graph.microsoft.com')

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
        saved = save_group_action(active_group, merged, user_id=user_id)
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
        removed = delete_group_action(active_group, action_id)
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
def get_user_plugin_types():
    return get_plugin_types()

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
        'enable_tabular_processing_plugin': bool(settings.get('enable_tabular_processing_plugin', False)),
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
        'enable_tabular_processing_plugin',
        'allow_user_plugins',
        'allow_group_plugins'
    ]
    updates = {}
    # Check for unexpected keys in the data payload
    for key in data:
        if key not in expected_keys:
            return jsonify({'error': f"Unexpected field: {key}"}), 400

    # Validate required fields and their types
    for key in expected_keys:
        if key not in data:
            return jsonify({'error': f"Missing required field: {key}"}), 400
        if not isinstance(data[key], bool):
            return jsonify({'error': f"Field '{key}' must be a boolean."}), 400
        updates[key] = data[key]
    logging.info("Validated plugin settings: %s", updates)
    # Dependency: tabular processing requires enhanced citations
    if updates.get('enable_tabular_processing_plugin', False):
        full_settings = get_settings()
        if not full_settings.get('enable_enhanced_citations', False):
            return jsonify({'error': 'Tabular Processing requires Enhanced Citations to be enabled.'}), 400
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
        plugins = get_global_actions()
        log_event("List plugins", extra={"action": "list", "user": str(getattr(request, 'user', 'unknown'))})
        return jsonify(plugins)
    except Exception as e:
        log_event(f"Error listing plugins: {e}", level=logging.ERROR)
        return jsonify({'error': 'Failed to list plugins.'}), 500

@bpap.route('/api/admin/plugins', methods=['POST'])
@swagger_route(security=get_auth_security())
@login_required
@admin_required
def add_plugin():
    try:
        plugins = get_global_actions()
        new_plugin = request.json
        
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
        
        # Prevent duplicate names (case-insensitive)
        if any(p['name'].lower() == new_plugin['name'].lower() for p in plugins):
            log_event("Add plugin failed: duplicate name", level=logging.WARNING, extra={"action": "add", "plugin": _redact_plugin_for_logging(new_plugin)})
            return jsonify({'error': 'Plugin with this name already exists.'}), 400
        
        # Assign a unique ID
        plugin_id = str(uuid.uuid4())
        new_plugin['id'] = plugin_id
        
        # Save to global actions container
        save_global_action(new_plugin, user_id=str(get_current_user_id()))
        
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
        plugins = get_global_actions()
        updated_plugin = request.json
        
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
        plugins = get_global_actions()
        
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

    unresolved_fields = []
    if connection_string == ui_trigger_word:
        unresolved_fields.append('connection string')
    if password == ui_trigger_word:
        unresolved_fields.append('password')
    if unresolved_fields:
        field_list = ', '.join(unresolved_fields)
        return jsonify({'success': False, 'error': f"Stored SQL secret could not be resolved for testing. Re-enter the {field_list}."}), 400

    try:
        connection_string = _resolve_secret_value_for_sql_test(connection_string, 'connection_string')
        password = _resolve_secret_value_for_sql_test(password, 'password')
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    # Map azure_sql to sqlserver
    if database_type in ('azure_sql', 'azuresql'):
        database_type = 'sqlserver'

    try:
        if database_type == 'sqlserver':
            import pyodbc
            if connection_method == 'connection_string' and connection_string:
                conn = pyodbc.connect(connection_string, timeout=timeout)
            else:
                if not server or not database:
                    return jsonify({'success': False, 'error': 'Server and database are required for individual parameters connection.'}), 400
                drv = driver or 'ODBC Driver 17 for SQL Server'
                conn_str = f"DRIVER={{{drv}}};SERVER={server};DATABASE={database}"
                if port:
                    conn_str += f",{port}"
                if auth_type == 'username_password' and username and password:
                    conn_str += f";UID={username};PWD={password}"
                elif auth_type == 'managed_identity':
                    conn_str += ";Authentication=ActiveDirectoryMsi"
                elif auth_type == 'integrated':
                    conn_str += ";Trusted_Connection=yes"
                conn = pyodbc.connect(conn_str, timeout=timeout)
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
        return jsonify({'success': False, 'error': f'Database driver not installed: {str(e)}'}), 400
    except Exception as e:
        error_msg = str(e)
        # Sanitize error message to avoid leaking sensitive details
        if 'password' in error_msg.lower() or 'pwd' in error_msg.lower():
            error_msg = 'Authentication failed. Please check your credentials.'
        return jsonify({'success': False, 'error': f'Connection failed: {error_msg}'}), 400
