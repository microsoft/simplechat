#route_backlend_plugins.py

import re
import builtins
from flask import Blueprint, jsonify, request, current_app
from semantic_kernel_plugins.plugin_loader import get_all_plugin_metadata
from functions_settings import get_settings, update_settings
from functions_authentication import *
from functions_appinsights import log_event
import logging
import os

import importlib.util
from functions_plugins import get_merged_plugin_settings
from semantic_kernel_plugins.base_plugin import BasePlugin


from json_schema_validation import validate_plugin

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
                    types.append({
                        'type': module_name.replace('_plugin', ''),
                        'class': attr,
                        'display': attr.replace('Plugin', '').replace('_', ' ')
                    })
            if not found:
                debug_log.append(f"No valid plugin class found in {fname}")
    # Log the debug output to the server log
    print("[PLUGIN DISCOVERY DEBUG]", *debug_log, sep="\n")
    return jsonify(types)

bpap = Blueprint('admin_plugins', __name__)

# === USER PLUGINS ENDPOINTS ===
@bpap.route('/api/user/plugins', methods=['GET'])
@login_required
def get_user_plugins():
    user_id = get_current_user_id()
    user_settings = get_user_settings(user_id)
    plugins = user_settings.get('settings', {}).get('plugins', [])
    # Always mark user plugins as is_global: False
    for plugin in plugins:
        plugin['is_global'] = False

    # Check global/merge toggles
    settings = get_settings()
    merge_global = settings.get('merge_global_semantic_kernel_with_workspace', False)
    if merge_global:
        global_plugins = settings.get('semantic_kernel_plugins', [])
        # Mark global plugins
        for plugin in global_plugins:
            plugin['is_global'] = True
        # User plugins take precedence
        all_plugins = {p['name']: p for p in plugins}
        all_plugins.update({p['name']: p for p in global_plugins})
        return jsonify(list(all_plugins.values()))
    else:
        return jsonify(plugins)

@bpap.route('/api/user/plugins', methods=['POST'])
@login_required
def set_user_plugins():
    user_id = get_current_user_id()
    plugins = request.json if isinstance(request.json, list) else []
    # Get global plugin names (case-insensitive)
    settings = get_settings()
    global_plugins = settings.get('semantic_kernel_plugins', [])
    global_plugin_names = set(p['name'].lower() for p in global_plugins if 'name' in p)
    # Filter out plugins whose name matches a global plugin name
    filtered_plugins = []
    for plugin in plugins:
        if plugin.get('name', '').lower() in global_plugin_names:
            continue  # Skip global plugins
        # Remove is_global if present
        if 'is_global' in plugin:
            del plugin['is_global']
        # Auto-fill type from metadata if missing or empty
        if not plugin.get('type') and plugin.get('metadata', {}).get('type'):
            plugin['type'] = plugin['metadata']['type']
        validation_error = validate_plugin(plugin)
        if validation_error:
            return jsonify({'error': f'Plugin validation failed: {validation_error}'}), 400
        filtered_plugins.append(plugin)
    user_settings = get_user_settings(user_id)
    settings_to_update = user_settings.get('settings', {})
    settings_to_update['plugins'] = filtered_plugins
    update_user_settings(user_id, settings_to_update)
    log_event("User plugins updated", extra={"user_id": user_id, "plugins_count": len(filtered_plugins)})
    return jsonify({'success': True})

@bpap.route('/api/user/plugins/<plugin_name>', methods=['DELETE'])
@login_required
def delete_user_plugin(plugin_name):
    user_id = get_current_user_id()
    user_settings = get_user_settings(user_id)
    plugins = user_settings.get('settings', {}).get('plugins', [])
    new_plugins = [p for p in plugins if p['name'] != plugin_name]
    if len(new_plugins) == len(plugins):
        return jsonify({'error': 'Plugin not found.'}), 404
    settings_to_update = user_settings.get('settings', {})
    settings_to_update['plugins'] = new_plugins
    update_user_settings(user_id, settings_to_update)
    log_event("User plugin deleted", extra={"user_id": user_id, "plugin_name": plugin_name})
    return jsonify({'success': True})

@bpap.route('/api/user/plugins/types', methods=['GET'])
@login_required
def get_user_plugin_types():
    return get_plugin_types()

# === ADMIN PLUGINS ENDPOINTS ===

# GET: Return current core plugin toggle values
@bpap.route('/api/admin/plugins/settings', methods=['GET'])
@login_required
@admin_required
def get_core_plugin_settings():
    settings = get_settings()
    return jsonify({
        'enable_time_plugin': bool(settings.get('enable_time_plugin', True)),
        'enable_http_plugin': bool(settings.get('enable_http_plugin', True)),
        'enable_wait_plugin': bool(settings.get('enable_wait_plugin', True)),
        'enable_default_embedding_model_plugin': bool(settings.get('enable_default_embedding_model_plugin', True)),
        'enable_fact_memory_plugin': bool(settings.get('enable_fact_memory_plugin', True)),
        'enable_semantic_kernel': bool(settings.get('enable_semantic_kernel', False)),
        'allow_user_plugins': bool(settings.get('allow_user_plugins', True)),
        'allow_group_plugins': bool(settings.get('allow_group_plugins', True)),
    })

# POST: Update core plugin toggle values
@bpap.route('/api/admin/plugins/settings', methods=['POST'])
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
        'enable_default_embedding_model_plugin',
        'enable_fact_memory_plugin',
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
    # Update settings
    success = update_settings(updates)
    if success:
        # --- HOT RELOAD TRIGGER ---
        setattr(builtins, "kernel_reload_needed", True)
        return jsonify({'success': True, 'updated': updates}), 200
    else:
        return jsonify({'error': 'Failed to update settings.'}), 500

@bpap.route('/api/admin/plugins', methods=['GET'])
@login_required
@admin_required
def list_plugins():
    try:
        settings = get_settings()
        plugins = settings.get('semantic_kernel_plugins', [])
        log_event("List plugins", extra={"action": "list", "user": str(getattr(request, 'user', 'unknown'))})
        return jsonify(plugins)
    except Exception as e:
        log_event(f"Error listing plugins: {e}", level=logging.ERROR)
        return jsonify({'error': 'Failed to list plugins.'}), 500

@bpap.route('/api/admin/plugins', methods=['POST'])
@login_required
@admin_required
def add_plugin():
    try:
        settings = get_settings()
        plugins = settings.get('semantic_kernel_plugins', [])
        new_plugin = request.json
        # Strict validation with dynamic allowed types
        allowed_types = discover_plugin_types()
        validation_error = validate_plugin(new_plugin)
        if validation_error:
            log_event("Add plugin failed: validation error", level=logging.WARNING, extra={"action": "add", "plugin": new_plugin, "error": validation_error})
            return jsonify({'error': validation_error}), 400
        if allowed_types is not None and new_plugin.get('type') not in allowed_types:
            return jsonify({'error': f"Invalid plugin type: {new_plugin.get('type')}"}), 400
        # Merge with schema to ensure all required fields are present
        schema_dir = os.path.join(current_app.root_path, 'static', 'json', 'schemas')
        merged = get_merged_plugin_settings(new_plugin.get('type'), new_plugin, schema_dir)
        new_plugin['metadata'] = merged.get('metadata', new_plugin.get('metadata', {}))
        new_plugin['additionalFields'] = merged.get('additionalFields', new_plugin.get('additionalFields', {}))
        # Prevent duplicate names (case-insensitive)
        if any(p['name'].lower() == new_plugin['name'].lower() for p in plugins):
            log_event("Add plugin failed: duplicate name", level=logging.WARNING, extra={"action": "add", "plugin": new_plugin})
            return jsonify({'error': 'Plugin with this name already exists.'}), 400
        plugins.append(new_plugin)
        settings['semantic_kernel_plugins'] = plugins
        update_settings(settings)
        log_event("Plugin added", extra={"action": "add", "plugin": new_plugin, "user": str(getattr(request, 'user', 'unknown'))})
        # --- HOT RELOAD TRIGGER ---
        setattr(builtins, "kernel_reload_needed", True)
        return jsonify({'success': True})
    except Exception as e:
        log_event(f"Error adding plugin: {e}", level=logging.ERROR)
        return jsonify({'error': 'Failed to add plugin.'}), 500

@bpap.route('/api/admin/plugins/<plugin_name>', methods=['PUT'])
@login_required
@admin_required
def edit_plugin(plugin_name):
    try:
        settings = get_settings()
        plugins = settings.get('semantic_kernel_plugins', [])
        updated_plugin = request.json
        # Strict validation with dynamic allowed types
        allowed_types = discover_plugin_types()
        validation_error = validate_plugin(updated_plugin)
        if validation_error:
            log_event("Edit plugin failed: validation error", level=logging.WARNING, extra={"action": "edit", "plugin": updated_plugin, "error": validation_error})
            return jsonify({'error': validation_error}), 400
        if allowed_types is not None and updated_plugin.get('type') not in allowed_types:
            return jsonify({'error': f"Invalid plugin type: {updated_plugin.get('type')}"}), 400
        # Merge with schema to ensure all required fields are present
        
        schema_dir = os.path.join(current_app.root_path, 'static', 'json', 'schemas')
        merged = get_merged_plugin_settings(updated_plugin.get('type'), updated_plugin, schema_dir)
        updated_plugin['metadata'] = merged.get('metadata', updated_plugin.get('metadata', {}))
        updated_plugin['additionalFields'] = merged.get('additionalFields', updated_plugin.get('additionalFields', {}))
        for i, p in enumerate(plugins):
            if p['name'] == plugin_name:
                plugins[i] = updated_plugin
                settings['semantic_kernel_plugins'] = plugins
                update_settings(settings)
                log_event("Plugin edited", extra={"action": "edit", "plugin": updated_plugin, "user": str(getattr(request, 'user', 'unknown'))})
                # --- HOT RELOAD TRIGGER ---
                setattr(builtins, "kernel_reload_needed", True)
                return jsonify({'success': True})
        log_event("Edit plugin failed: not found", level=logging.WARNING, extra={"action": "edit", "plugin_name": plugin_name})
        return jsonify({'error': 'Plugin not found.'}), 404
    except Exception as e:
        log_event(f"Error editing plugin: {e}", level=logging.ERROR)
        return jsonify({'error': 'Failed to edit plugin.'}), 500

@bpap.route('/api/admin/plugins/types', methods=['GET'])
@login_required
@admin_required
def get_admin_plugin_types():
    return get_plugin_types()

@bpap.route('/api/admin/plugins/<plugin_name>', methods=['DELETE'])
@login_required
@admin_required
def delete_plugin(plugin_name):
    try:
        settings = get_settings()
        plugins = settings.get('semantic_kernel_plugins', [])
        new_plugins = [p for p in plugins if p['name'] != plugin_name]
        if len(new_plugins) == len(plugins):
            log_event("Delete plugin failed: not found", level=logging.WARNING, extra={"action": "delete", "plugin_name": plugin_name})
            return jsonify({'error': 'Plugin not found.'}), 404
        settings['semantic_kernel_plugins'] = new_plugins
        update_settings(settings)
        log_event("Plugin deleted", extra={"action": "delete", "plugin_name": plugin_name, "user": str(getattr(request, 'user', 'unknown'))})
        # --- HOT RELOAD TRIGGER ---
        setattr(builtins, "kernel_reload_needed", True)
        return jsonify({'success': True})
    except Exception as e:
        log_event(f"Error deleting plugin: {e}", level=logging.ERROR)
        return jsonify({'error': 'Failed to delete plugin.'}), 500
    

# === PLUGIN SETTINGS MERGE ENDPOINT ===
@bpap.route('/api/plugins/<plugin_type>/merge_settings', methods=['POST'])
@login_required
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

##########################################################################################################
# Dynamic Plugin Metadata Endpoint

bpdp = Blueprint('dynamic_plugins', __name__)

@bpdp.route('/api/admin/plugins/dynamic', methods=['GET'])
@login_required
@admin_required
def list_dynamic_plugins():
    """
    Returns metadata for all available plugin types (not registrations).
    """
    plugins = get_all_plugin_metadata()
    return jsonify(plugins)
