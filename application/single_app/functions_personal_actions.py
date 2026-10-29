# functions_personal_actions.py

"""
Personal Actions (Plugins) Management

This module handles all operations related to personal actions/plugins stored in the 
personal_actions container with user_id partitioning.
"""

import logging
import uuid
import hashlib
from copy import deepcopy
from collections import Counter
from datetime import datetime, timezone
from azure.core import MatchConditions
from azure.cosmos import exceptions
import functions_settings as user_settings_service
from functions_action_manifest import (
    McpConfigurationError,
    McpStdioRemovedError,
    bind_action_origin,
    is_retired_mcp_stdio,
    resolve_action_type,
)
from functions_appinsights import log_event
from functions_keyvault import (
    SecretReturnType,
    clean_name_for_keyvault,
    keyvault_plugin_delete_helper,
    keyvault_plugin_get_helper,
    keyvault_plugin_save_helper,
    redact_plugin_secret_values,
)
from functions_legacy_action_management import (
    LEGACY_ACTION_PREFIX,
    LegacyActionConflictError,
    LegacyActionSecretConflictError,
    LegacyActionSourceUpdateError,
    action_snapshot_digest,
    authorize_scoped_mcp_secret_read,
    find_legacy_action_snapshot,
    is_unchanged_legacy_action,
    legacy_action_management_view,
    legacy_action_snapshots,
    prepare_scoped_action,
    retired_action_management_view,
    validate_action_configuration,
    validate_scoped_mcp_action,
)
from functions_workspace_identities import (
    WORKSPACE_IDENTITY_SCOPE_PERSONAL,
    hydrate_action_identity_reference,
    validate_action_identity_reference,
)
from config import cosmos_personal_actions_container, cosmos_user_settings_container
from functions_governance import ensure_action_type_access, filter_actions_by_action_type_access
from functions_chat_bootstrap_cache import bump_chat_bootstrap_user_cache_version
from json_schema_validation import (
    ACTION_MIGRATION_ID_PREFIX,
    is_legacy_msgraph_type,
    normalize_m365_action_payload,
    validate_legacy_action_update,
)


def _is_action_migration_record(action):
    return bool(action.get('_action_migration')) or str(action.get('id') or '').startswith(ACTION_MIGRATION_ID_PREFIX)


def get_governed_personal_actions(user_id, return_type=SecretReturnType.TRIGGER):
    """
    Fetch personal actions only after the current user passes governance checks.

    Args:
        user_id (str): The user's unique identifier

    Returns:
        list: List of action/plugin dictionaries
    """
    actions = get_personal_actions(user_id, return_type=return_type)
    active_actions = [action for action in actions if not is_retired_mcp_stdio(action)]
    allowed_actions = filter_actions_by_action_type_access(
        user_id, active_actions, 'governance_user_actions', 'personal'
    )
    return [action for action in actions if is_retired_mcp_stdio(action) or action in allowed_actions]


def _clean_action(action, user_id, return_type):
    if return_type == SecretReturnType.NAME:
        return bind_action_origin(
            {key: value for key, value in action.items() if not key.startswith("_")},
            "personal",
            user_id,
        )
    retired_view = retired_action_management_view(action, "personal", user_id)
    if retired_view is not None:
        return retired_view
    cleaned = {key: value for key, value in action.items() if not key.startswith("_")}
    cleaned = bind_action_origin(cleaned, "personal", user_id)
    if return_type == SecretReturnType.VALUE and cleaned["type"] == "mcp":
        ensure_action_type_access("governance_user_actions", user_id, "mcp", "personal")
        authorize_scoped_mcp_secret_read(cleaned, user_settings_service.get_settings())
    cleaned = keyvault_plugin_get_helper(
        cleaned, scope_value=user_id, scope="user", return_type=return_type
    )
    cleaned = hydrate_action_identity_reference(
        cleaned,
        WORKSPACE_IDENTITY_SCOPE_PERSONAL,
        user_id,
        return_type=return_type,
    )
    return bind_action_origin(cleaned, "personal", user_id)


def _clean_actions(actions, user_id, return_type):
    try:
        return [
            _clean_action(action, user_id, return_type)
            for action in actions if not _is_action_migration_record(action)
        ]
    except Exception as exc:
        log_event("[PLUGINS] Personal action normalization failed",
                  level=logging.WARNING, extra={"user_id": user_id, "error_type": type(exc).__name__})
        raise


def _read_personal_action_record(user_id, action_id):
    try:
        return cosmos_personal_actions_container.read_item(item=action_id, partition_key=user_id)
    except exceptions.CosmosResourceNotFoundError:
        return None


def get_personal_action_record(user_id, action_id):
    """Read an exact personal ID without secret hydration; never send this to a browser."""
    action = _read_personal_action_record(user_id, action_id)
    if action is None:
        return None
    if _is_action_migration_record(action):
        log_event(
            "[USER_SETTINGS] Internal action migration record excluded from action lookup.",
            level=logging.WARNING, extra={"user_id": user_id},
        )
        return None
    return bind_action_origin(action, "personal", user_id)


def _find_personal_action_record(user_id, action_id):
    action = get_personal_action_record(user_id, action_id)
    if action is not None:
        return action
    actions = [
        action for action in cosmos_personal_actions_container.query_items(
            query="SELECT * FROM c WHERE c.user_id = @user_id AND c.name = @name",
            parameters=[
                {"name": "@user_id", "value": user_id},
                {"name": "@name", "value": action_id},
            ],
            partition_key=user_id,
        ) if not _is_action_migration_record(action)
    ]
    if len(actions) > 1:
        raise LegacyActionConflictError()
    return bind_action_origin(actions[0], "personal", user_id) if actions else None

def get_personal_actions(user_id, return_type=SecretReturnType.TRIGGER):
    """
    Fetch all personal actions/plugins for a user.
    
    Args:
        user_id (str): The user's unique identifier
        
    Returns:
        list: List of action/plugin dictionaries

    NAME returns internal originals without secret or identity hydration.
    Browser callers must use TRIGGER or an explicit retired management projection.
    """
    try:
        query = "SELECT * FROM c WHERE c.user_id = @user_id"
        parameters = [{"name": "@user_id", "value": user_id}]
        
        actions = list(cosmos_personal_actions_container.query_items(
            query=query,
            parameters=parameters,
            partition_key=user_id
        ))
        
    except exceptions.CosmosResourceNotFoundError:
        return []
    except Exception as exc:
        log_event("[PLUGINS] Personal action listing failed", level=logging.ERROR,
                  extra={"user_id": user_id, "error_type": type(exc).__name__})
        raise
    return _clean_actions(actions, user_id, return_type)

def get_personal_action(user_id, action_id, return_type=SecretReturnType.TRIGGER):
    """
    Fetch a specific personal action/plugin.
    
    Args:
        user_id (str): The user's unique identifier
        action_id (str): The action's unique identifier (can be name or UUID)
        
    Returns:
        dict: Action dictionary or None if not found
    """
    try:
        action = _find_personal_action_record(user_id, action_id)
    except exceptions.CosmosResourceNotFoundError:
        return None
    except Exception as exc:
        log_event("[PLUGINS] Personal action lookup failed", level=logging.ERROR,
                  extra={"user_id": user_id, "action_id": action_id, "error_type": type(exc).__name__})
        raise
    if action is None:
        return None
    return _clean_actions([action], user_id, return_type)[0]

def save_personal_action(user_id, action_data, enforce_governance=True):
    """
    Save or update a personal action/plugin.
    
    Args:
        user_id (str): The user's unique identifier
        action_data (dict): Action configuration data
        
    Returns:
        dict: Saved action data with ID
    """
    return _save_personal_action(user_id, action_data, enforce_governance=enforce_governance)


def _save_personal_action(user_id, action_data, enforce_governance=True, migration_snapshot=None):
    try:
        submitted_action = action_data
        action_data = normalize_m365_action_payload(action_data)
        action_data = prepare_scoped_action(action_data, "personal", user_id)
        legacy_type = is_legacy_msgraph_type(action_data.get('type'))
        if action_data.get("id") and (
            not isinstance(action_data["id"], str) or action_data["id"].startswith(LEGACY_ACTION_PREFIX)
        ):
            raise ValueError("Action ID is invalid.")
        existing_action = None
        if action_data.get('id'):
            existing_action = _read_personal_action_record(user_id, action_data['id'])
        validate_legacy_action_update(submitted_action, existing_action, 'user_id', user_id)
        if legacy_type:
            action_data['type'] = 'msgraph'
        elif not action_data.get('id') and action_data.get('name'):
            existing_action = _find_personal_action_record(user_id, action_data['name'])
        if migration_snapshot is not None and existing_action is not None:
            raise LegacyActionConflictError()
        
        # Preserve existing ID if updating, or generate new ID if creating
        now = datetime.utcnow().isoformat()
        if existing_action:
            # Update existing action - preserve the original ID and creation tracking
            action_data['id'] = existing_action['id']
            action_data['created_by'] = existing_action.get('created_by', user_id)
            action_data['created_at'] = existing_action.get('created_at', now)
        elif 'id' not in action_data or not action_data['id']:
            # New action - generate UUID for ID
            action_data['id'] = str(uuid.uuid4())
            action_data['created_by'] = user_id
            action_data['created_at'] = now
        else:
            # Has an ID but no existing action found - treat as new
            action_data['created_by'] = user_id
            action_data['created_at'] = now
        action_data['modified_by'] = user_id
        action_data['modified_at'] = now

        action_data['user_id'] = user_id
        action_data['last_updated'] = now

        # Validate required fields
        required_fields = ['name', 'displayName', 'type', 'description']
        for field in required_fields:
            if field not in action_data:
                if field == 'displayName':
                    action_data[field] = action_data.get('name', '')
                else:
                    action_data[field] = ''
                    
        # Set defaults for optional fields
        action_data.setdefault('endpoint', '')
        action_data.setdefault('auth', {'type': 'identity'})
        action_data.setdefault('metadata', {})
        action_data.setdefault('additionalFields', {})
        
        # Ensure auth has default structure
        if not isinstance(action_data['auth'], dict):
            action_data['auth'] = {'type': 'identity'}
        elif 'type' not in action_data['auth']:
            action_data['auth']['type'] = 'identity'

        if enforce_governance:
            ensure_action_type_access('governance_user_actions', user_id, action_data.get('type'), 'personal')

        action_data = bind_action_origin(action_data, "personal", user_id)
        if action_data["type"] == "mcp":
            validate_scoped_mcp_action(action_data, user_id, user_settings_service.get_settings())
        if migration_snapshot is not None:
            validate_action_configuration(action_data)
        validate_action_identity_reference(
            action_data,
            WORKSPACE_IDENTITY_SCOPE_PERSONAL,
            user_id,
        )
        _ensure_personal_secret_name_available(user_id, action_data, migration_snapshot)
        configuration_digest = _action_configuration_digest(action_data)
        
        # Store secrets in Key Vault before upsert
        action_data = keyvault_plugin_save_helper(
            action_data,
            scope_value=user_id,
            scope="user",
            existing_plugin=existing_action,
        )
        if legacy_type:
            result = cosmos_personal_actions_container.replace_item(
                item=existing_action['id'],
                body=action_data,
                etag=existing_action['_etag'],
                match_condition=MatchConditions.IfNotModified,
            )
        elif migration_snapshot is not None:
            action_data["_legacy_migration"] = {
                "source_locator": migration_snapshot.locator,
                "destination_digest": _stored_action_digest(action_data),
                "configuration_digest": configuration_digest,
            }
            try:
                result = cosmos_personal_actions_container.create_item(body=action_data)
            except exceptions.CosmosHttpResponseError as exc:
                if exc.status_code == 409:
                    raise LegacyActionConflictError() from exc
                raise
        else:
            result = cosmos_personal_actions_container.upsert_item(body=action_data)
        # Remove Cosmos metadata from response
        cleaned_result = {k: v for k, v in result.items() if not k.startswith('_')}
        bump_chat_bootstrap_user_cache_version(user_id, reason="personal_action_saved")
        return bind_action_origin(cleaned_result, "personal", user_id)
        
    except Exception as exc:
        log_event("[PLUGINS] Personal action save failed", level=logging.ERROR,
                  extra={"user_id": user_id, "error_type": type(exc).__name__})
        raise

def delete_personal_action(user_id, action_id):
    """
    Delete a personal action/plugin.
    
    Args:
        user_id (str): The user's unique identifier
        action_id (str): The action's unique identifier OR name
        
    Returns:
        bool: True if deleted, False if not found
    """
    try:
        ensure_migration_complete(user_id)
        # Try to find the action first to get the correct ID
        if isinstance(action_id, str) and action_id.startswith(LEGACY_ACTION_PREFIX):
            return delete_legacy_personal_action(user_id, action_id)
        action = _find_personal_action_record(user_id, action_id)
        if not action:
            return False

        if not is_retired_mcp_stdio(action):
            ensure_action_type_access('governance_user_actions', user_id, resolve_action_type(action), 'personal')
            
        # Delete secrets from Key Vault before deleting the action
        keyvault_plugin_delete_helper(action, scope_value=user_id, scope="user")
        cosmos_personal_actions_container.delete_item(
            item=action['id'],
            partition_key=user_id
        )
        bump_chat_bootstrap_user_cache_version(user_id, reason="personal_action_deleted")
        return True
        
    except exceptions.CosmosResourceNotFoundError:
        return False
    except Exception as exc:
        log_event("[PLUGINS] Personal action deletion failed", level=logging.ERROR,
                  extra={"user_id": user_id, "action_id": action_id, "error_type": type(exc).__name__})
        raise

def _historical_msgraph_identity(user_id, plugin):
    if not isinstance(plugin, dict) or not isinstance(plugin.get("name"), str) or not plugin["name"]:
        raise ValueError("Historical action configuration is invalid.")
    source_id = plugin.get("id")
    if (
        source_id and (
            not isinstance(source_id, str)
            or source_id.startswith((ACTION_MIGRATION_ID_PREFIX, LEGACY_ACTION_PREFIX))
        )
        or plugin.get("_action_migration")
    ):
        raise ValueError("Historical action identity is invalid.")
    source_key = source_id or plugin["name"]
    digest = hashlib.sha256(source_key.encode('utf-8')).hexdigest()
    receipt_id = f"{ACTION_MIGRATION_ID_PREFIX}{digest}"
    action_id = source_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"{user_id}:legacy-action:{source_key}"))
    return action_id, receipt_id


def _migrate_historical_msgraph_action(user_id, plugin):
    action_id, receipt_id = _historical_msgraph_identity(user_id, plugin)
    try:
        cosmos_personal_actions_container.read_item(item=receipt_id, partition_key=user_id)
        return 0
    except exceptions.CosmosResourceNotFoundError:
        # No receipt means this historical action has not been migrated yet.
        pass

    existing = None
    try:
        existing = cosmos_personal_actions_container.read_item(item=action_id, partition_key=user_id)
    except exceptions.CosmosResourceNotFoundError:
        # Only this trusted migration may create an absent historical action.
        pass
    payload = deepcopy(plugin)
    payload['id'] = action_id
    payload['user_id'] = user_id
    payload['type'] = 'msgraph'
    if existing:
        validate_legacy_action_update(payload, existing, 'user_id', user_id)
    else:
        name_conflicts = list(cosmos_personal_actions_container.query_items(
            query="SELECT c.id FROM c WHERE c.user_id = @user_id AND c.name = @name",
            parameters=[{"name": "@user_id", "value": user_id}, {"name": "@name", "value": plugin['name']}],
            partition_key=user_id,
        ))
        if name_conflicts:
            raise ValueError("Historical action ID conflicts require administrator review.")
        validate_action_identity_reference(payload, WORKSPACE_IDENTITY_SCOPE_PERSONAL, user_id)
        payload = keyvault_plugin_save_helper(payload, scope_value=user_id, scope="user")

    receipt = {
        'id': receipt_id,
        'user_id': user_id,
        '_action_migration': True,
        'action_id': action_id,
        'version': '0.261.029',
    }
    operations = [('create', (receipt,))]
    if not existing:
        operations.append(('create', (payload,)))
    try:
        cosmos_personal_actions_container.execute_item_batch(
            batch_operations=operations, partition_key=user_id,
        )
    except exceptions.CosmosBatchOperationError as exc:
        if exc.status_code != 409:
            raise
        cosmos_personal_actions_container.read_item(item=receipt_id, partition_key=user_id)
        return 0
    return 0 if existing else 1


def _read_legacy_settings_document(user_id):
    # The settings accessor remains the object-level authorization boundary.
    # Its request cache cannot prove that a source is unchanged before deletion.
    user_settings_service.get_user_settings(user_id)
    try:
        document = cosmos_user_settings_container.read_item(item=user_id, partition_key=user_id)
    except exceptions.CosmosResourceNotFoundError:
        document = {"id": user_id, "settings": {"plugins": []}}
    return deepcopy(document)


def _read_legacy_settings_for_preflight(user_id):
    # Reuse the settings accessor's authorization without its profile repair or
    # default-document writes; rejecting an import must leave all stored data alone.
    user_settings_service._authorize_user_settings_access(user_id, "update")
    try:
        document = cosmos_user_settings_container.read_item(item=user_id, partition_key=user_id)
    except exceptions.CosmosResourceNotFoundError:
        document = {"id": user_id, "settings": {"plugins": []}}
    return deepcopy(document)


def _document_plugins(document):
    settings = document.get("settings") or {}
    plugins = settings.get("plugins", [])
    return [] if plugins is None else plugins


def _get_legacy_snapshot(user_id, locator):
    document = _read_legacy_settings_document(user_id)
    return find_legacy_action_snapshot(user_id, _document_plugins(document), locator)


def _ensure_legacy_management_access(user_id, snapshot):
    if not is_retired_mcp_stdio(snapshot.record):
        ensure_action_type_access(
            "governance_user_actions", user_id, resolve_action_type(snapshot.record), "personal"
        )


def list_legacy_personal_actions(user_id):
    """List safe, management-only views without importing legacy actions."""
    try:
        document = _read_legacy_settings_document(user_id)
        views = []
        for snapshot in legacy_action_snapshots(user_id, _document_plugins(document)):
            try:
                _ensure_legacy_management_access(user_id, snapshot)
            except PermissionError:
                continue
            views.append(legacy_action_management_view(snapshot))
        return views
    except Exception as exc:
        log_event("[PLUGINS] Legacy action listing failed", level=logging.ERROR,
                  extra={"user_id": user_id, "error_type": type(exc).__name__})
        raise


def get_legacy_personal_action(user_id, locator):
    """Resolve an authorized legacy locator to its credential-free management view."""
    snapshot = _get_legacy_snapshot(user_id, locator)
    _ensure_legacy_management_access(user_id, snapshot)
    return legacy_action_management_view(snapshot)


def get_legacy_personal_action_record(user_id, locator):
    """Return an internal source copy for validation, never for browser serialization."""
    snapshot = _get_legacy_snapshot(user_id, locator)
    _ensure_legacy_management_access(user_id, snapshot)
    return deepcopy(snapshot.record)


def is_unchanged_legacy_personal_action(user_id, submitted):
    """Qualify an authorized unchanged management view without importing its source."""
    if not isinstance(submitted, dict):
        return False
    try:
        snapshot = _get_legacy_snapshot(user_id, submitted.get("id"))
    except LegacyActionConflictError:
        return False
    _ensure_legacy_management_access(user_id, snapshot)
    return is_unchanged_legacy_action(submitted, snapshot)


def prepare_legacy_personal_actions_update(user_id, submitted_plugins):
    """Preflight a settings.plugins update without action, secret, or settings writes.

    The returned ``plugins`` list contains authoritative raw source records and is
    backend-only. Callers gate ``has_imports`` with allow_user_plugins before any
    other mutations, and can omit the plugins update entirely when ``changed`` is
    false. Existing legacy actions are reconfigured through the dedicated Actions
    operation, which stores a destination before removing its exact source.
    """
    if not isinstance(submitted_plugins, list):
        raise McpConfigurationError("Actions must be provided as a list.")
    document = _read_legacy_settings_for_preflight(user_id)
    originals = _document_plugins(document)
    snapshots = legacy_action_snapshots(user_id, originals)
    by_locator = {snapshot.locator: snapshot for snapshot in snapshots}
    by_id = {}
    for snapshot in snapshots:
        if isinstance(snapshot.record, dict) and isinstance(snapshot.record.get("id"), str):
            by_id.setdefault(snapshot.record["id"], []).append(snapshot)

    replacements = {}
    additions = []
    imported = []
    seen_ids = set()
    for submitted in submitted_plugins:
        if not isinstance(submitted, dict):
            raise McpConfigurationError("Each action must be an object.")
        submitted_id = submitted.get("id")
        if submitted_id is not None and not isinstance(submitted_id, str):
            raise McpConfigurationError("Action identifiers must be strings.")
        if submitted_id:
            if submitted_id in seen_ids:
                raise McpConfigurationError("Each action identifier must occur only once.")
            seen_ids.add(submitted_id)

        if submitted_id and submitted_id.startswith(LEGACY_ACTION_PREFIX):
            snapshot = by_locator.get(submitted_id)
            if snapshot is None:
                raise LegacyActionConflictError()
            if is_unchanged_legacy_action(submitted, snapshot):
                _ensure_legacy_management_access(user_id, snapshot)
                if snapshot.index in replacements:
                    raise LegacyActionConflictError()
                replacements[snapshot.index] = deepcopy(snapshot.record)
                continue
            if is_retired_mcp_stdio(submitted):
                raise McpStdioRemovedError()
            raise McpConfigurationError("Use Actions to reconfigure an existing legacy action.")

        if is_retired_mcp_stdio(submitted):
            raise McpStdioRemovedError()
        if any(field in submitted for field in (
            "is_legacy", "legacy_source", "legacy_locator", "execution_status",
        )):
            raise McpConfigurationError("Legacy management fields require a current action locator.")

        matches = by_id.get(submitted_id, []) if submitted_id else [
            snapshot for snapshot in snapshots if snapshot.record == submitted
        ]
        if len(matches) > 1:
            raise LegacyActionConflictError()
        snapshot = matches[0] if matches else None
        if snapshot is not None:
            if snapshot.index in replacements:
                raise LegacyActionConflictError()
            if is_retired_mcp_stdio(snapshot.record):
                raise McpConfigurationError("Use Actions to reconfigure an existing legacy action.")
            if is_legacy_msgraph_type(resolve_action_type(snapshot.record)) and submitted == snapshot.record:
                _ensure_legacy_management_access(user_id, snapshot)
                replacements[snapshot.index] = deepcopy(snapshot.record)
                continue

        payload = _prepare_personal_action_configuration(user_id, submitted)
        _ensure_personal_secret_name_available(
            user_id, payload, snapshot, legacy_sources=snapshots
        )
        if snapshot is not None and submitted == snapshot.record:
            replacements[snapshot.index] = deepcopy(snapshot.record)
        else:
            imported.append(payload)
            if snapshot is None:
                additions.append(payload)
            else:
                replacements[snapshot.index] = payload

    prepared = []
    for snapshot in snapshots:
        if snapshot.index in replacements:
            prepared.append(replacements[snapshot.index])
        elif is_retired_mcp_stdio(snapshot.record):
            prepared.append(deepcopy(snapshot.record))
        else:
            _ensure_legacy_management_access(user_id, snapshot)
    prepared.extend(additions)
    for payload in imported:
        sentinel = object()
        if redact_plugin_secret_values(payload, redaction_value=sentinel) == payload:
            continue
        secret_name = clean_name_for_keyvault(payload.get("name", "")).lower()
        for other in prepared:
            if other is payload or not isinstance(other, dict):
                continue
            name = other.get("name")
            if isinstance(name, str) and clean_name_for_keyvault(name).lower() == secret_name:
                raise LegacyActionSecretConflictError()
    return {
        "plugins": deepcopy(prepared),
        "has_imports": bool(imported),
        "changed": prepared != originals,
        "source_etag": document.get("_etag"),
    }


def prepare_legacy_personal_action_reconfiguration(user_id, locator, replacement):
    """Preflight conversion without writes; commit through the reconfiguration API.

    The result is an internal validated manifest with the destination's real ID.
    Keep the management locator separately for the later commit operation.
    """
    document = _read_legacy_settings_for_preflight(user_id)
    plugins = _document_plugins(document)
    snapshots = legacy_action_snapshots(user_id, plugins)
    snapshot = find_legacy_action_snapshot(user_id, plugins, locator)
    payload = _legacy_destination_payload(
        user_id, snapshot, replacement=replacement, legacy_sources=snapshots
    )
    _verified_legacy_destination(user_id, snapshot, payload)
    return payload


def prepare_legacy_action_settings_update(user_id, incoming_plugins):
    """Return backend-only plugins, has_imports, changed, and source_etag without writes."""
    return prepare_legacy_personal_actions_update(user_id, incoming_plugins)


def validate_legacy_personal_action_reconfiguration(user_id, locator, replacement):
    """Return the validated destination manifest without committing the conversion."""
    return prepare_legacy_personal_action_reconfiguration(user_id, locator, replacement)


def _remove_legacy_snapshot(user_id, snapshot):
    document = _read_legacy_settings_document(user_id)
    plugins = _document_plugins(document)
    current = find_legacy_action_snapshot(user_id, plugins, snapshot.locator)
    if current.owner_id != snapshot.owner_id or current.record != snapshot.record:
        raise LegacyActionConflictError()
    if not document.get("_etag"):
        raise LegacyActionSourceUpdateError()

    updated = deepcopy(document)
    updated["settings"]["plugins"] = plugins[:current.index] + plugins[current.index + 1:]
    updated["lastUpdated"] = datetime.now(timezone.utc).isoformat()
    try:
        stored = cosmos_user_settings_container.replace_item(
            item=user_id,
            body=updated,
            etag=document["_etag"],
            match_condition=MatchConditions.IfNotModified,
        )
    except exceptions.CosmosHttpResponseError as exc:
        if exc.status_code == 412:
            raise LegacyActionConflictError() from exc
        raise LegacyActionSourceUpdateError() from exc
    except Exception as exc:
        raise LegacyActionSourceUpdateError() from exc
    if not isinstance(stored, dict) or _document_plugins(stored) != updated["settings"]["plugins"]:
        raise LegacyActionSourceUpdateError()

    try:
        user_settings_service._set_request_cached_user_settings(user_id, stored)
        user_settings_service._delete_user_ui_settings_cache(user_id)
        bump_chat_bootstrap_user_cache_version(user_id, reason="legacy_action_removed")
    except Exception as exc:
        log_event("[PLUGINS] Legacy action cache refresh failed after verified source update",
                  level=logging.WARNING, extra={"user_id": user_id, "error_type": type(exc).__name__})


def delete_legacy_personal_action(user_id, locator):
    """Explicitly remove one exact source; retired cleanup is not MCP usage."""
    snapshot = _get_legacy_snapshot(user_id, locator)
    _ensure_legacy_management_access(user_id, snapshot)
    _remove_legacy_snapshot(user_id, snapshot)
    return True


def _stored_action_digest(action):
    return action_snapshot_digest({
        key: value for key, value in action.items() if not key.startswith("_")
    })


def _action_configuration_digest(action):
    audit_fields = {
        "created_by", "created_at", "modified_by", "modified_at", "last_updated", "updated_at",
    }
    return action_snapshot_digest({
        key: value for key, value in action.items()
        if not key.startswith("_") and key not in audit_fields
    })


def _ensure_personal_secret_name_available(user_id, payload, snapshot=None, *, legacy_sources=None):
    """Prevent distinct IDs from sharing Key Vault's scope-and-name secret keys."""
    sentinel = object()
    redacted = redact_plugin_secret_values(payload, redaction_value=sentinel)
    if redacted == payload:
        return
    secret_name = clean_name_for_keyvault(payload.get("name", "")).lower()
    existing = cosmos_personal_actions_container.query_items(
        query="SELECT * FROM c WHERE c.user_id = @user_id",
        parameters=[{"name": "@user_id", "value": user_id}],
        partition_key=user_id,
    )
    for action in existing:
        name = action.get("name")
        if (
            action.get("id") != payload.get("id")
            and isinstance(name, str)
            and clean_name_for_keyvault(name).lower() == secret_name
        ):
            raise LegacyActionSecretConflictError()
    if legacy_sources is None:
        document = _read_legacy_settings_document(user_id)
        legacy_sources = legacy_action_snapshots(user_id, _document_plugins(document))
    for other in legacy_sources:
        if snapshot is not None and other.locator == snapshot.locator:
            continue
        if (
            isinstance(other.record, dict)
            and isinstance(other.record.get("name"), str)
            and clean_name_for_keyvault(other.record["name"]).lower() == secret_name
        ):
            raise LegacyActionSecretConflictError()


def _prepare_personal_action_configuration(user_id, incoming):
    payload = normalize_m365_action_payload(incoming)
    payload = prepare_scoped_action(payload, "personal", user_id)
    existing = (
        get_personal_action_record(user_id, payload["id"])
        if is_legacy_msgraph_type(payload.get("type")) and payload.get("id") else None
    )
    validate_legacy_action_update(incoming, existing, "user_id", user_id)
    payload.setdefault("displayName", payload.get("name", ""))
    payload.setdefault("description", "")
    payload.setdefault("endpoint", "")
    payload.setdefault("auth", {"type": "NoAuth"})
    payload.setdefault("metadata", {})
    payload.setdefault("additionalFields", {})
    ensure_action_type_access("governance_user_actions", user_id, payload["type"], "personal")
    validate_action_configuration(payload)
    if payload["type"] == "mcp":
        validate_scoped_mcp_action(payload, user_id, user_settings_service.get_settings())
    validate_action_identity_reference(payload, WORKSPACE_IDENTITY_SCOPE_PERSONAL, user_id)
    return payload


def _legacy_destination_payload(user_id, snapshot, replacement=None, *, legacy_sources=None):
    original = snapshot.record
    if not isinstance(original, dict):
        raise ValueError("Legacy action configuration is invalid.")
    incoming = deepcopy(original if replacement is None else replacement)
    if not isinstance(incoming, dict):
        raise ValueError("Action configuration must be an object.")
    source_id = original.get("id")
    if source_id and (not isinstance(source_id, str) or source_id.startswith(LEGACY_ACTION_PREFIX)):
        raise LegacyActionConflictError()
    incoming["id"] = source_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"{user_id}:{snapshot.locator}"))
    if is_retired_mcp_stdio(original) and resolve_action_type(incoming) != "mcp":
        raise ValueError("Reconfigure this action with a supported remote MCP server.")
    payload = _prepare_personal_action_configuration(user_id, incoming)
    _ensure_personal_secret_name_available(
        user_id, payload, snapshot, legacy_sources=legacy_sources
    )
    return payload


def _verified_legacy_destination(user_id, snapshot, payload):
    existing = get_personal_action_record(user_id, payload["id"])
    if existing is None:
        return None
    receipt = existing.get("_legacy_migration")
    if not isinstance(receipt, dict) or (
        receipt.get("source_locator") != snapshot.locator
        or receipt.get("configuration_digest") != _action_configuration_digest(payload)
        or receipt.get("destination_digest") != _stored_action_digest(existing)
    ):
        raise LegacyActionConflictError()
    return existing


def _store_legacy_replacement(user_id, snapshot, payload):
    current = _get_legacy_snapshot(user_id, snapshot.locator)
    if current.record != snapshot.record:
        raise LegacyActionConflictError()
    existing = _verified_legacy_destination(user_id, snapshot, payload)
    if existing is None:
        _save_personal_action(user_id, payload, migration_snapshot=snapshot)
        existing = _verified_legacy_destination(user_id, snapshot, payload)
        if existing is None:
            raise LegacyActionSourceUpdateError()
    _remove_legacy_snapshot(user_id, snapshot)
    return existing


def reconfigure_legacy_personal_action(user_id, locator, replacement):
    """Store a validated replacement before conditionally removing its exact source."""
    snapshot = _get_legacy_snapshot(user_id, locator)
    payload = _legacy_destination_payload(user_id, snapshot, replacement=replacement)
    stored = _store_legacy_replacement(user_id, snapshot, payload)
    return _clean_action(stored, user_id, SecretReturnType.TRIGGER)


def _migration_outcome(snapshot, code, retryable=False, action_id=None):
    record = snapshot.record if isinstance(snapshot.record, dict) else {}
    outcome = {
        "id": snapshot.locator,
        "name": record.get("name") if isinstance(record.get("name"), str) else "",
        "code": code,
        "retryable": retryable,
    }
    if action_id:
        outcome["action_id"] = action_id
    return outcome


def _legacy_identity_counts(snapshots):
    return Counter(
        snapshot.record["id"] for snapshot in snapshots
        if isinstance(snapshot.record, dict) and isinstance(snapshot.record.get("id"), str)
        and snapshot.record["id"]
    )


def _prepare_legacy_migration(user_id, snapshot, identity_counts):
    if is_retired_mcp_stdio(snapshot.record):
        return None, "mcp_stdio_removed"
    if (
        not isinstance(snapshot.record, dict)
        or not isinstance(snapshot.record.get("name"), str)
        or not snapshot.record["name"].strip()
    ):
        return None, "invalid_action_configuration"
    source_id = snapshot.record.get("id") if isinstance(snapshot.record, dict) else None
    if snapshot.duplicate_count > 1 or (isinstance(source_id, str) and identity_counts[source_id] > 1):
        return None, "legacy_identity_conflict"
    try:
        if isinstance(snapshot.record, dict) and is_legacy_msgraph_type(resolve_action_type(snapshot.record)):
            _ensure_legacy_management_access(user_id, snapshot)
            action_id, _receipt_id = _historical_msgraph_identity(user_id, snapshot.record)
            return {**deepcopy(snapshot.record), "id": action_id, "type": "msgraph"}, None
        payload = _legacy_destination_payload(user_id, snapshot)
        _verified_legacy_destination(user_id, snapshot, payload)
        return payload, None
    except LegacyActionConflictError as exc:
        return None, exc.code
    except PermissionError:
        return None, "action_governance_denied"
    except ValueError:
        return None, "invalid_action_configuration"


def get_action_migration_status(user_id):
    """Describe actionable work separately from records requiring manual changes."""
    document = _read_legacy_settings_document(user_id)
    snapshots = legacy_action_snapshots(user_id, _document_plugins(document))
    identity_counts = _legacy_identity_counts(snapshots)
    status = {
        "pending_count": 0, "retained_count": 0, "retired_count": 0,
        "failed_count": 0, "retained": [], "failed": [], "actions": [],
    }
    for snapshot in snapshots:
        try:
            _payload, reason = _prepare_legacy_migration(user_id, snapshot, identity_counts)
            if reason:
                status["retained"].append(_migration_outcome(snapshot, reason))
                if reason == "mcp_stdio_removed":
                    status["retired_count"] += 1
            else:
                status["pending_count"] += 1
            try:
                _ensure_legacy_management_access(user_id, snapshot)
            except (PermissionError, ValueError):
                continue
            status["actions"].append(legacy_action_management_view(snapshot))
        except Exception as exc:
            status["failed"].append(_migration_outcome(snapshot, "migration_check_failed", retryable=True))
            log_event("[PLUGINS] Legacy action migration inspection failed", level=logging.WARNING,
                      extra={"user_id": user_id, "error_type": type(exc).__name__})
    status["retained_count"] = len(status["retained"])
    status["failed_count"] = len(status["failed"])
    status["complete"] = status["pending_count"] == 0 and status["failed_count"] == 0
    status["total_count"] = len(snapshots)
    return status


def ensure_migration_complete(user_id):
    """Attempt only verified record-level migration; never clean up by counts."""
    return migrate_actions_from_user_settings(user_id)


def migrate_actions_from_user_settings(user_id):
    """Migrate valid records independently and report retained/failed sources safely."""
    result = {
        "migrated_count": 0, "retained_count": 0, "failed_count": 0,
        "migrated": [], "retained": [], "failed": [], "complete": False,
    }
    try:
        document = _read_legacy_settings_document(user_id)
        snapshots = legacy_action_snapshots(user_id, _document_plugins(document))
        identity_counts = _legacy_identity_counts(snapshots)
        for snapshot in snapshots:
            try:
                payload, reason = _prepare_legacy_migration(user_id, snapshot, identity_counts)
                if reason:
                    result["retained"].append(_migration_outcome(snapshot, reason))
                    continue
                if is_legacy_msgraph_type(payload.get("type")):
                    current = _get_legacy_snapshot(user_id, snapshot.locator)
                    created = _migrate_historical_msgraph_action(user_id, current.record)
                    _remove_legacy_snapshot(user_id, snapshot)
                    if created:
                        result["migrated"].append(_migration_outcome(snapshot, "migrated", action_id=payload["id"]))
                    continue
                stored = _store_legacy_replacement(user_id, snapshot, payload)
                result["migrated"].append(_migration_outcome(snapshot, "migrated", action_id=stored["id"]))
            except LegacyActionConflictError as exc:
                result["retained"].append(_migration_outcome(snapshot, exc.code))
            except (PermissionError, ValueError):
                result["retained"].append(_migration_outcome(snapshot, "action_validation_failed"))
            except Exception as exc:
                code = (
                    "legacy_source_update_failed"
                    if isinstance(exc, LegacyActionSourceUpdateError)
                    else "action_migration_failed"
                )
                result["failed"].append(_migration_outcome(snapshot, code, retryable=True))
                log_event("[PLUGINS] Legacy action migration failed", level=logging.WARNING,
                          extra={"user_id": user_id, "error_type": type(exc).__name__})
        remaining = get_action_migration_status(user_id)
        result["complete"] = remaining["complete"] and not result["failed"]
        result["pending_count"] = remaining["pending_count"]
    except PermissionError:
        raise
    except Exception as exc:
        result["failed"].append({
            "code": "legacy_source_read_failed", "retryable": True,
        })
        log_event("[PLUGINS] Legacy action source inspection failed", level=logging.ERROR,
                  extra={"user_id": user_id, "error_type": type(exc).__name__})
    for category in ("migrated", "retained", "failed"):
        result[f"{category}_count"] = len(result[category])
    return result

def get_actions_by_names(user_id, action_names, return_type=SecretReturnType.TRIGGER):
    """
    Get multiple actions by their names.
    
    Args:
        user_id (str): The user's unique identifier
        action_names (list): List of action names to retrieve
        
    Returns:
        list: List of action dictionaries
    """
    try:
        if not action_names:
            return []
            
        # Create IN clause for query
        placeholders = ", ".join([f"@name{i}" for i in range(len(action_names))])
        query = f"SELECT * FROM c WHERE c.user_id = @user_id AND c.name IN ({placeholders})"
        
        parameters = [{"name": "@user_id", "value": user_id}]
        for i, name in enumerate(action_names):
            parameters.append({"name": f"@name{i}", "value": name})
        
        actions = list(cosmos_personal_actions_container.query_items(
            query=query,
            parameters=parameters,
            partition_key=user_id
        ))
        
    except exceptions.CosmosResourceNotFoundError:
        return []
    except Exception as exc:
        log_event("[PLUGINS] Personal action name lookup failed", level=logging.ERROR,
                  extra={"user_id": user_id, "error_type": type(exc).__name__})
        raise
    return _clean_actions(actions, user_id, return_type)

def get_actions_by_type(user_id, action_type, return_type=SecretReturnType.TRIGGER):
    """
    Get all actions of a specific type for a user.
    
    Args:
        user_id (str): The user's unique identifier
        action_type (str): The type of actions to retrieve (e.g., 'openapi', 'sql_query')
        
    Returns:
        list: List of action dictionaries
    """
    try:
        effective_type = resolve_action_type({"type": action_type})
        query = "SELECT * FROM c WHERE c.user_id = @user_id AND c.type = @type"
        parameters = [
            {"name": "@user_id", "value": user_id},
            {"name": "@type", "value": effective_type}
        ]
        if effective_type == "mcp":
            query = "SELECT * FROM c WHERE c.user_id = @user_id"
            parameters = [{"name": "@user_id", "value": user_id}]
        
        actions = list(cosmos_personal_actions_container.query_items(
            query=query,
            parameters=parameters,
            partition_key=user_id
        ))
        
    except exceptions.CosmosResourceNotFoundError:
        return []
    except Exception as exc:
        log_event("[PLUGINS] Personal action type lookup failed", level=logging.ERROR,
                  extra={"user_id": user_id, "error_type": type(exc).__name__})
        raise
    matching_actions = (
        action for action in actions
        if effective_type != "mcp" or resolve_action_type(action) == effective_type
    )
    return _clean_actions(matching_actions, user_id, return_type)
