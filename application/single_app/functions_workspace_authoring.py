# functions_workspace_authoring.py
"""Opt-in personal editor projections, patch intent, and conditional persistence.

Service imports stay at operation boundaries, as in functions_agent_delegation,
to avoid initializing Azure clients during schema discovery and pure draft tests.
"""

import builtins
import json
import logging
import re
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path

from flask import jsonify, request
from functions_ai_connections import filter_model_endpoints_by_capability


EDITOR_SECRET_MASK = "***REDACTED***"
EDITOR_SECRET_PLACEHOLDERS = frozenset({
    EDITOR_SECRET_MASK, "Stored_In_KeyVault", "[REDACTED]", "********", "**********",
})
_MISSING = object()
_MANAGED_FIELDS = frozenset({
    "id", "user_id", "owner_id", "owner_user_id", "group_id", "scope", "scope_type",
    "scope_id", "is_global", "is_group", "created_at", "created_by", "modified_at",
    "modified_by", "updated_at", "updated_by", "last_updated",
})
_SECRET_NAMES = frozenset({
    "key", "apikey", "clientsecret", "password", "connectionstring", "accesstoken",
    "refreshtoken", "token", "bearertoken", "subscriptionkey", "privatekey",
    "privatekeypem", "privatekeypassphrase", "accountkey", "sas", "sastoken",
    "authorization", "cookie", "setcookie", "secret",
})
_AGENT_CUSTOM_CONNECTION_FIELDS = frozenset({
    "azure_openai_gpt_endpoint", "azure_openai_gpt_key", "azure_openai_gpt_api_revision",
    "azure_agent_apim_gpt_endpoint", "azure_agent_apim_gpt_subscription_key",
    "azure_agent_apim_gpt_api_revision",
})
_AGENT_TYPES = (
    ("local", "Local agent", None),
    ("aifoundry", "Azure AI Foundry", "allow_personal_ai_foundry_agents"),
    ("new_foundry", "New Foundry", "allow_personal_new_foundry_agents"),
    ("foundry_workflow", "Foundry Workflow", "allow_personal_new_foundry_agents"),
)
_BUILTIN_ACTIONS = (
    ("time", "Time", "enable_time_plugin"),
    ("fact_memory", "Fact memory", "enable_fact_memory_plugin"),
    ("math", "Math", "enable_math_plugin"),
    ("text", "Text", "enable_text_plugin"),
    ("http", "HTTP", "enable_http_plugin"),
    ("wait", "Wait", "enable_wait_plugin"),
    ("embedding_model", "Embedding model", "enable_default_embedding_model_plugin"),
)
_OPTION_DEFAULTS = {
    "enable_semantic_kernel": False,
    "allow_user_agents": False,
    "allow_user_plugins": False,
    "per_user_semantic_kernel": False,
    "merge_global_semantic_kernel_with_workspace": False,
    "allow_user_custom_endpoints": False,
    "allow_personal_ai_foundry_agents": False,
    "allow_personal_new_foundry_agents": False,
    "allow_ai_foundry_agents": False,
    "allow_new_foundry_agents": False,
    "enable_multi_model_endpoints": False,
    "default_model_selection": {},
    "gpt_model": {},
    "enable_gpt_apim": False,
    "azure_apim_gpt_deployment": "",
    "enable_agent_template_gallery": False,
    "agent_templates_allow_user_submission": True,
    "enable_user_workspace": True,
    "enable_public_workspaces": False,
    "enable_web_search": False,
    "enable_url_access": False,
    **{flag: False for _, _, flag in _BUILTIN_ACTIONS},
}


class WorkspaceAuthoringConflict(ValueError):
    """The stored revision no longer matches the editor's revision."""


class WorkspaceAuthoringValidation(ValueError):
    """An editor request is invalid; only fixed, developer-authored messages are public."""

    def __init__(self, public_message):
        super().__init__(public_message)
        self.public_message = public_message


def _pointer(path):
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in path)


def _parse_pointer(pointer):
    if not isinstance(pointer, str) or not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise WorkspaceAuthoringValidation("Use valid JSON pointers for removed and cleared fields.")
    parts = tuple(part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/"))
    if not parts[0] or parts[0] in _MANAGED_FIELDS or parts[0].startswith("_"):
        raise WorkspaceAuthoringValidation("Ownership, scope, IDs, and audit fields cannot be changed.")
    return parts


def _get(data, path, default=_MISSING):
    current = data
    for part in path:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and str(part).isdigit() and str(int(part)) == str(part) and int(part) < len(current):
            current = current[int(part)]
        else:
            return default
    return current


def _set(data, path, value):
    parent = _get(data, path[:-1])
    if isinstance(parent, dict):
        parent[path[-1]] = value
    elif isinstance(parent, list) and str(path[-1]).isdigit() and int(path[-1]) < len(parent):
        parent[int(path[-1])] = value
    else:
        raise WorkspaceAuthoringValidation("The requested field no longer exists.")


def _walk(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, (*path, str(index)))
    else:
        yield path, value


def _is_placeholder(value):
    return isinstance(value, str) and value in EDITOR_SECRET_PLACEHOLDERS


def _is_reference(value):
    if not isinstance(value, str):
        return False
    keyvault = import_module("functions_keyvault")
    return keyvault.validate_secret_name_dynamic(value) or bool(
        re.match(r"^https://[^/]+/secrets/", value, re.IGNORECASE)
    )


def editor_secret_paths(record, kind):
    """Include canonical secrets and nested custom/legacy credentials, with KV on or off."""
    paths = set()
    if kind == "actions":
        redacted = import_module("functions_keyvault").redact_plugin_secret_values(record)
        paths.update(path for path, value in _walk(redacted) if value == EDITOR_SECRET_MASK)
    else:
        paths.update({("azure_openai_gpt_key",), ("azure_agent_apim_gpt_subscription_key",)})
    for path, value in _walk(record):
        if not path:
            continue
        name = re.sub(r"[_-]", "", path[-1]).lower()
        if (
            name in _SECRET_NAMES
            or path[-1].endswith("__Secret")
            or _is_reference(value)
            or _is_placeholder(value)
        ):
            paths.add(path)
    return {path for path in paths if _get(record, path, None) not in (None, "")}


def project_editor_record(record, kind, *, global_scope=False):
    """Project stored configuration without hydrating credentials or leaking Cosmos metadata."""
    result = {key: deepcopy(value) for key, value in record.items() if not key.startswith("_")}
    paths = editor_secret_paths(result, kind)
    for path in paths:
        _set(result, path, EDITOR_SECRET_MASK)
    metadata = result.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("key_vault_secret_reminder_sync"), dict):
        metadata["key_vault_secret_reminder_sync"] = {
            path: {
                "status": status.get("status", ""),
                "updated_at": status.get("updated_at", ""),
            }
            for path, status in metadata["key_vault_secret_reminder_sync"].items()
            if isinstance(status, dict)
        }
    result["is_global"] = global_scope
    result["is_group"] = False
    if kind == "agents":
        result.setdefault("agent_type", "local")
        result.setdefault("actions_to_load", [])
        result.setdefault("other_settings", {})
        if result.get("max_completion_tokens") is None:
            result["max_completion_tokens"] = -1
    else:
        result.setdefault("metadata", {})
        result.setdefault("additionalFields", {})
    return result


def editor_resource(record, kind, *, global_scope=False):
    projected = project_editor_record(record, kind, global_scope=global_scope)
    return {
        "record": projected,
        "revision": record.get("_etag") or "",
        "secret_paths": sorted(_pointer(path) for path in editor_secret_paths(projected, kind)),
        "read_only": global_scope,
    }


def clear_editor_test_secrets(record, clear_secret_paths):
    """Remove explicit clears from authorized, transient test/discovery fallback state."""
    if not isinstance(record, dict):
        raise WorkspaceAuthoringValidation("A saved action is required to clear stored test credentials.")
    if not isinstance(clear_secret_paths, list) or len(clear_secret_paths) > 1000:
        raise WorkspaceAuthoringValidation("Cleared fields must be an array of JSON pointers.")
    configured = editor_secret_paths(record, "actions")
    result = deepcopy(record)
    for pointer in clear_secret_paths:
        path = _parse_pointer(pointer)
        if path not in configured:
            raise WorkspaceAuthoringValidation("Only an existing secret can be cleared.")
        parent = _get(result, path[:-1])
        if isinstance(parent, dict):
            parent.pop(path[-1], None)
        else:
            _set(result, path, "")
    return result


def _container(kind, scope="personal"):
    if kind not in {"agents", "actions"} or scope not in {"personal", "global"}:
        raise WorkspaceAuthoringValidation("Invalid workspace resource.")
    return getattr(import_module("config"), f"cosmos_{scope}_{kind}_container")


def ensure_editor_access(kind, user_id, settings, *, operation="write"):
    if not isinstance(user_id, str) or not user_id.strip():
        raise PermissionError("An authenticated user is required.")
    if kind == "actions" and operation in {"read", "delete"}:
        # Classic action reads and cleanup are independent of authoring flags.
        # Per-item governance is checked before exposing or deleting each record.
        return
    flag = "allow_user_agents" if kind == "agents" else "allow_user_plugins"
    if (
        not settings.get("enable_semantic_kernel", False)
        or not settings.get("enable_user_workspace", True)
        or not settings.get(flag, False)
    ):
        raise PermissionError("This workspace capability is disabled.")
    governance = import_module("functions_governance")
    if kind == "agents":
        governance.ensure_governance_access("governance_user_agents", user_id)
    elif not governance.is_action_scope_access_allowed("governance_user_actions", user_id, "personal"):
        raise PermissionError("This workspace capability is unavailable.")


def ensure_editor_options_access(user_id, settings):
    """Action-only authors may read reminder defaults, but not an agent model catalogue."""
    try:
        ensure_editor_access("agents", user_id, settings)
        return True
    except PermissionError:
        ensure_editor_access("actions", user_id, settings)
        return False


def _assert_record_access(kind, user_id, record, settings, *, global_scope=False):
    governance = import_module("functions_governance")
    if global_scope:
        if not settings.get("merge_global_semantic_kernel_with_workspace", False):
            raise LookupError("This resource is unavailable.")
        if kind == "agents" and not settings.get("per_user_semantic_kernel", False):
            raise LookupError("This resource is unavailable.")
        if not record.get("is_enabled", True):
            raise LookupError("This resource is unavailable.")
        if kind == "agents":
            governance.ensure_governance_access(
                "governance_global_agents_usage", user_id, item_entity_type="global_agent",
                item_id=record["id"],
            )
        else:
            governance.ensure_global_action_access(user_id, record)
        return
    if (
        record.get("user_id") != user_id
        or record.get("is_global")
        or record.get("is_group")
        or record.get("group_id")
        or record.get("scope") not in (None, "", "personal", "user")
    ):
        raise LookupError("This resource is unavailable.")
    if kind == "actions":
        governance.ensure_action_type_access("governance_user_actions", user_id, record.get("type"), "personal")


def read_editor_record(kind, user_id, record_id, settings, *, scope="personal"):
    ensure_editor_access(kind, user_id, settings, operation="read")
    if scope not in {"personal", "global"}:
        raise WorkspaceAuthoringValidation("Invalid workspace scope.")
    if not isinstance(record_id, str) or not record_id or any(char in record_id for char in "/\\?#"):
        raise LookupError("This resource is unavailable.")
    exceptions = import_module("azure.cosmos.exceptions")
    try:
        record = _container(kind, scope).read_item(
            item=record_id, partition_key=record_id if scope == "global" else user_id,
        )
    except exceptions.CosmosResourceNotFoundError as exc:
        raise LookupError("This resource is unavailable.") from exc
    if record.get("id") != record_id:
        raise LookupError("This resource is unavailable.")
    _assert_record_access(kind, user_id, record, settings, global_scope=scope == "global")
    return deepcopy(record)


def list_editor_records(kind, user_id, settings):
    ensure_editor_access(kind, user_id, settings, operation="read")
    personal = []
    if kind != "actions" or import_module("functions_governance").is_action_scope_access_allowed(
        "governance_user_actions", user_id, "personal",
    ):
        personal = _container(kind).query_items(
            query="SELECT * FROM c WHERE c.user_id = @user_id",
            parameters=[{"name": "@user_id", "value": user_id}], partition_key=user_id,
        )
    records = []
    sources = [(False, personal)]
    if settings.get("merge_global_semantic_kernel_with_workspace", False) and (
        kind == "actions" or settings.get("per_user_semantic_kernel", False)
    ):
        sources.append((True, _container(kind, "global").query_items(
            query="SELECT * FROM c", enable_cross_partition_query=True,
        )))
    for global_scope, source in sources:
        for record in source:
            try:
                _assert_record_access(kind, user_id, record, settings, global_scope=global_scope)
            except (LookupError, PermissionError):
                continue
            records.append(project_editor_record(record, kind, global_scope=global_scope))
    return records


def merge_editor_write(existing, payload, kind, *, creating=False, resolve_stored_placeholder=None):
    """Apply changed leaves; removals and clearing configured secrets require explicit intent."""
    if not isinstance(payload, dict) or set(payload) - {
        "updates", "expected_revision", "clear_secret_paths", "removed_paths",
    }:
        raise WorkspaceAuthoringValidation("Invalid editor request.")
    updates = payload.get("updates")
    if not isinstance(updates, dict):
        raise WorkspaceAuthoringValidation("Updates must be an object.")
    if not creating:
        expected = payload.get("expected_revision")
        if not isinstance(expected, str) or not expected:
            raise WorkspaceAuthoringValidation("Reload this resource before saving; its revision is required.")
        if not existing.get("_etag") or expected != existing["_etag"]:
            raise WorkspaceAuthoringConflict("This resource changed. Reload it before saving.")
    for key in updates:
        if (key in _MANAGED_FIELDS or key.startswith("_")) and not (
            key == "id" and creating and kind == "agents"
        ):
            raise WorkspaceAuthoringValidation("Ownership, scope, IDs, and audit fields cannot be changed.")
    paths = {}
    for field in ("clear_secret_paths", "removed_paths"):
        values = payload.get(field, [])
        if not isinstance(values, list) or len(values) > 1000:
            raise WorkspaceAuthoringValidation("Cleared and removed fields must be arrays of JSON pointers.")
        paths[field] = {_parse_pointer(value) for value in values}
    if paths["clear_secret_paths"] & paths["removed_paths"]:
        raise WorkspaceAuthoringValidation("A field cannot be both removed and cleared.")
    existing = deepcopy(existing)
    existing_secrets = editor_secret_paths(existing, kind)
    if resolve_stored_placeholder:
        for path in existing_secrets - paths["clear_secret_paths"]:
            submitted = _get(updates, path)
            if _is_placeholder(_get(existing, path)) and (
                submitted is _MISSING or _is_placeholder(submitted)
            ):
                _set(existing, path, resolve_stored_placeholder(existing, path))
    result = deepcopy(existing)

    def merge(before, changes, path=(), *, replace_objects=False):
        if isinstance(changes, dict):
            previous = before if isinstance(before, dict) else {}
            merged = {} if replace_objects else deepcopy(previous)
            for key, value in changes.items():
                merged[key] = merge(
                    previous.get(key, _MISSING), value, (*path, key),
                    replace_objects=replace_objects,
                )
            return merged
        if isinstance(changes, list):
            # Array objects are replacements; only masks reuse the same stored JSON pointer.
            return [
                merge(
                    before[index] if isinstance(before, list) and index < len(before) else _MISSING,
                    value, (*path, str(index)), replace_objects=True,
                )
                for index, value in enumerate(changes)
            ]
        if _is_placeholder(changes):
            if path not in existing_secrets or before is _MISSING or _is_placeholder(before):
                raise WorkspaceAuthoringValidation("A stored secret is unavailable. Re-enter its value.")
            return deepcopy(before)
        if _is_reference(changes):
            if path not in existing_secrets or before != changes:
                raise WorkspaceAuthoringValidation("Secret references cannot be supplied by an editor.")
        if path in existing_secrets and changes in (None, "") and path not in paths["clear_secret_paths"]:
            raise WorkspaceAuthoringValidation("Use clear_secret_paths to clear a stored credential.")
        return deepcopy(changes)

    result = merge(result, updates)
    for path in paths["clear_secret_paths"]:
        if path not in existing_secrets:
            raise WorkspaceAuthoringValidation("Only an existing secret can be cleared.")
        if _get(result, path) is _MISSING:
            continue
        parent = _get(result, path[:-1])
        if isinstance(parent, dict):
            parent.pop(path[-1])
        else:
            _set(result, path, "")
    for path in paths["removed_paths"]:
        if any(secret[:len(path)] == path and secret not in paths["clear_secret_paths"] for secret in existing_secrets):
            raise WorkspaceAuthoringValidation("Clear stored credentials explicitly before removing their configuration.")
        parent = _get(result, path[:-1])
        if isinstance(parent, dict):
            parent.pop(path[-1], None)
        else:
            raise WorkspaceAuthoringValidation("Replace arrays explicitly rather than removing their elements.")
    for path in existing_secrets - paths["clear_secret_paths"]:
        if _get(result, path, None) in (None, ""):
            raise WorkspaceAuthoringValidation("Clear stored credentials explicitly before replacing their configuration.")
    if any(_is_placeholder(value) for _, value in _walk(result)):
        raise WorkspaceAuthoringValidation("A stored secret is unavailable. Re-enter its value.")
    return result


def _secret_scope(kind, user_id, record, path):
    return (record["id"], "agent") if kind == "agents" else (
        user_id, "action" if path[0] == "auth" else "action-addset",
    )


def _legacy_editor_secret_reference(record, path, kind, user_id, settings):
    """Recover a legacy stored trigger only from its owned, conventional Key Vault name."""
    unavailable = "A stored secret is unavailable. Re-enter its value."
    if not settings.get("enable_key_vault_secret_storage") or not settings.get("key_vault_name"):
        raise WorkspaceAuthoringValidation(unavailable)
    keyvault = import_module("functions_keyvault")
    name = record.get("name", "")
    secret_name = None
    if kind == "agents":
        for field in keyvault.AGENT_SENSITIVE_SECRET_FIELDS:
            if path == field["path"]:
                secret_name = field["secret_name"](name)
                break
    elif path == ("auth", "key"):
        secret_name = name
    elif len(path) == 2 and path[0] == "auth" and path[1] in keyvault.SQL_PLUGIN_SENSITIVE_AUTH_FIELDS:
        secret_name = f"{name}-{path[1]}"
    elif path in _supported_storage_paths(record, kind):
        if len(path) == 2 and path[0] == "additionalFields":
            field = path[1][:-8] if path[1].endswith("__Secret") else path[1]
            secret_name = keyvault._build_plugin_additional_field_secret_name(name, field)
        elif len(path) == 3 and path[:2] == ("additionalFields", keyvault.MCP_CUSTOM_HEADERS_FIELD):
            secret_name = keyvault._build_plugin_additional_field_secret_name(name, f"mcp-custom-header-{path[2]}")
    if not secret_name:
        raise WorkspaceAuthoringValidation(unavailable)
    scope_value, source = _secret_scope(kind, user_id, record, path)
    try:
        reference = keyvault.build_full_secret_name(secret_name, scope_value, source, "user")
        value = keyvault.resolve_secret_reference_for_context(
            reference, scope_value=scope_value, scope="user", allowed_sources={source},
            context_label="owned personal editor credential",
        )
        if not value or _is_placeholder(value) or _is_reference(value):
            raise ValueError("The credential is unavailable.")
    except (ValueError, RuntimeError) as exc:
        raise WorkspaceAuthoringValidation(unavailable) from exc
    return reference


def _supported_storage_paths(record, kind):
    keyvault = import_module("functions_keyvault")
    if kind == "actions":
        redacted = keyvault.redact_plugin_secret_values(record)
        return {path for path, value in _walk(redacted) if value == EDITOR_SECRET_MASK}
    return {
        ("azure_openai_gpt_key",), ("azure_agent_apim_gpt_subscription_key",),
        *(("other_settings", section, "client_secret") for section in (
            "azure_ai_foundry", "new_foundry", "foundry_workflow",
        )),
    }


def _check_stored_references(record, kind, user_id):
    keyvault = import_module("functions_keyvault")
    for path in editor_secret_paths(record, kind):
        value = _get(record, path)
        if _is_reference(value):
            scope_value, source = _secret_scope(kind, user_id, record, path)
            if not keyvault.secret_reference_matches_context(
                value, scope_value=scope_value, scope="user", allowed_sources={source},
            ):
                raise WorkspaceAuthoringValidation("A stored credential does not belong to this resource.")


def _cleanup_staged_secrets(references):
    if not references:
        return
    keyvault = import_module("functions_keyvault")
    settings = import_module("functions_settings").get_settings()
    try:
        client = keyvault.SecretClient(
            vault_url=f"https://{settings['key_vault_name']}{keyvault.KEY_VAULT_DOMAIN}",
            credential=keyvault.get_keyvault_credential(),
        )
        for reference in references:
            client.begin_delete_secret(reference)
    except Exception as exc:
        import_module("functions_appinsights").log_event(
            "[KEY_VAULT] Unable to clean up unused editor secrets.",
            level=logging.WARNING, extra={"error_type": type(exc).__name__},
        )


def _stage_editor_secrets(record, kind, user_id, settings, staged):
    """Fresh names isolate failed CAS writes from every credential in a stored manifest."""
    keyvault = import_module("functions_keyvault")
    _check_stored_references(record, kind, user_id)
    if not settings.get("enable_key_vault_secret_storage", False):
        return
    if not settings.get("key_vault_name"):
        raise RuntimeError("Key Vault is unavailable.")
    for path in _supported_storage_paths(record, kind):
        value = _get(record, path, None)
        if value in (None, "") or _is_reference(value):
            continue
        if not isinstance(value, str):
            raise WorkspaceAuthoringValidation("Credentials must be text values.")
        scope_value, source = _secret_scope(kind, user_id, record, path)
        secret_name = f"editor-{uuid.uuid4().hex}"
        reference = keyvault.store_secret_in_key_vault(
            secret_name, value, scope_value, source=source, scope="user",
        )
        if not keyvault.secret_reference_matches_context(
            reference, scope_value=scope_value, scope="user", allowed_sources={source},
        ):
            raise RuntimeError("Key Vault did not store the credential.")
        staged.append(reference)
        _set(record, path, reference)


def _cleanup_replaced_secrets(record, kind, user_id, settings):
    if not record or not settings.get("enable_key_vault_secret_storage") or not settings.get("key_vault_name"):
        return
    keyvault = import_module("functions_keyvault")
    references = set()
    for path in _supported_storage_paths(record, kind):
        value = _get(record, path, None)
        scope_value, source = _secret_scope(kind, user_id, record, path)
        if isinstance(value, str) and keyvault.secret_reference_matches_context(
            value, scope_value=scope_value, scope="user", allowed_sources={source},
        ):
            references.add(value)
    if not references:
        return
    try:
        # Legacy names may be shared after a classic rename. Never delete a reference
        # still used by another owned manifest (including the just-committed one).
        for stored in _container(kind).query_items(
            query="SELECT * FROM c WHERE c.user_id = @user_id",
            parameters=[{"name": "@user_id", "value": user_id}], partition_key=user_id,
        ):
            references.difference_update(value for _, value in _walk(stored) if isinstance(value, str))
        _cleanup_staged_secrets(references)
        if (record.get("metadata") or {}).get("key_vault_secret_reminders"):
            reminders = import_module("functions_keyvault_reminders")
            for reference in references:
                reminders.mark_key_vault_secret_reminder_disabled(reference)
    except Exception as exc:
        import_module("functions_appinsights").log_event(
            "[KEY_VAULT] Unable to check superseded editor secrets for cleanup.",
            level=logging.WARNING, extra={"error_type": type(exc).__name__},
        )


def _sync_editor_reminders(saved, kind, user_id, settings):
    if kind != "actions" or not settings.get("enable_key_vault_secret_storage"):
        return saved
    metadata = saved.get("metadata") or {}
    if not isinstance(metadata.get("key_vault_secret_reminders"), dict):
        return saved
    keyvault = import_module("functions_keyvault")
    updated = deepcopy(saved)
    try:
        # The main CAS already succeeded. In particular, a stale request cannot
        # update expiration on a previously stored credential or reminder inventory.
        for path in _supported_storage_paths(updated, kind):
            reference = _get(updated, path, None)
            if isinstance(reference, str) and keyvault.validate_secret_name_dynamic(reference):
                scope_value, source = _secret_scope(kind, user_id, updated, path)
                keyvault._sync_plugin_secret_reminder(updated, path, reference, scope_value, source, "user")
        sync_status = (updated.get("metadata") or {}).get("key_vault_secret_reminder_sync")
        if sync_status is not None and sync_status != metadata.get("key_vault_secret_reminder_sync"):
            return _container(kind).patch_item(
                item=saved["id"], partition_key=user_id,
                patch_operations=[{"op": "set", "path": "/metadata/key_vault_secret_reminder_sync", "value": sync_status}],
                etag=saved["_etag"], match_condition=import_module("azure.core").MatchConditions.IfNotModified,
            )
    except Exception as exc:
        # A failure to record reminder status must not report a committed action as
        # unsaved, or retry the manifest with an unconditional write.
        import_module("functions_appinsights").log_event(
            "[KEY_VAULT] Unable to finish editor reminder synchronization.",
            level=logging.WARNING, extra={"error_type": type(exc).__name__},
        )
    return saved


def _invalidate_editor_catalog(kind, user_id, operation):
    builtins.kernel_reload_needed = True
    try:
        import_module("functions_chat_bootstrap_cache").bump_chat_bootstrap_user_cache_version(
            user_id, reason=f"personal_{'agent' if kind == 'agents' else 'action'}_{operation}",
        )
    except Exception as exc:
        import_module("functions_appinsights").log_event(
            "[CHAT_BOOTSTRAP_CACHE] Unable to invalidate a committed editor change.",
            level=logging.WARNING, extra={"error_type": type(exc).__name__},
        )


def save_editor_record(kind, user_id, record, existing, settings):
    """Save one prepared manifest using a mandatory conditional Cosmos write."""
    ensure_editor_access(kind, user_id, settings)
    if existing:
        try:
            current = read_editor_record(kind, user_id, existing["id"], settings)
        except LookupError as exc:
            raise WorkspaceAuthoringConflict("This resource changed. Reload it before saving.") from exc
        if not existing.get("_etag") or existing["_etag"] != current.get("_etag"):
            raise WorkspaceAuthoringConflict("This resource changed. Reload it before saving.")
    delegation = import_module("functions_agent_delegation")
    if kind == "agents":
        delegation.validate_agent_delegation_bindings(
            record, user_id=user_id, scope_type="personal", scope_id=user_id,
            settings=settings, existing_agent=existing,
        )
    else:
        import_module("functions_governance").ensure_action_type_access(
            "governance_user_actions", user_id, record.get("type"), "personal",
        )
        record = delegation.validate_agent_action_for_scope(
            record, user_id=user_id, scope_type="personal", scope_id=user_id, settings=settings,
        )
        import_module("functions_workspace_identities").validate_action_identity_reference(record, "personal", user_id)
    result = {key: deepcopy(value) for key, value in record.items() if not key.startswith("_") and key not in _MANAGED_FIELDS}
    now = datetime.now(timezone.utc).isoformat()
    result.update({
        "id": existing["id"] if existing else record["id"], "user_id": user_id,
        "created_at": (existing or {}).get("created_at", now),
        "created_by": (existing or {}).get("created_by", user_id),
        "modified_at": now, "modified_by": user_id, "last_updated": now,
    })
    if kind == "agents":
        result.update({"is_global": False, "is_group": False})
    staged = []
    write_started = False
    exceptions = import_module("azure.cosmos.exceptions")
    try:
        _stage_editor_secrets(result, kind, user_id, settings, staged)
        container = _container(kind)
        write_started = True
        if existing:
            saved = container.replace_item(
                item=existing["id"], body=result, etag=existing["_etag"],
                match_condition=import_module("azure.core").MatchConditions.IfNotModified,
            )
        else:
            saved = container.create_item(body=result)
    except Exception as exc:
        conflict_response = isinstance(exc, exceptions.CosmosHttpResponseError) and (
            exc.status_code in (409, 412) or (existing is not None and exc.status_code == 404)
        )
        # SDK retries can turn a committed write with a lost response into 409/412.
        # Once a write starts, even a conflict cannot prove its fresh secrets are unused.
        if not write_started:
            _cleanup_staged_secrets(staged)
        if conflict_response:
            raise WorkspaceAuthoringConflict("This resource changed. Reload it before saving.") from exc
        raise
    saved = _sync_editor_reminders(saved, kind, user_id, settings)
    _cleanup_replaced_secrets(existing, kind, user_id, settings)
    _invalidate_editor_catalog(kind, user_id, "saved")
    return saved


def delete_editor_record(kind, user_id, record, settings):
    ensure_editor_access(kind, user_id, settings, operation="delete")
    _assert_record_access(kind, user_id, record, settings)
    if not record.get("_etag"):
        raise WorkspaceAuthoringConflict("Reload this resource before deleting it.")
    if kind == "agents" and (settings.get("global_selected_agent") or {}).get("name") == record.get("name"):
        raise WorkspaceAuthoringValidation("Choose another default agent before deleting this agent.")
    exceptions = import_module("azure.cosmos.exceptions")
    try:
        _container(kind).delete_item(
            item=record["id"], partition_key=user_id, etag=record["_etag"],
            match_condition=import_module("azure.core").MatchConditions.IfNotModified,
        )
    except exceptions.CosmosHttpResponseError as exc:
        if exc.status_code in (404, 412):
            raise WorkspaceAuthoringConflict("This resource changed. Reload it before deleting.") from exc
        raise
    _cleanup_replaced_secrets(record, kind, user_id, settings)
    _invalidate_editor_catalog(kind, user_id, "deleted")


def _validate_agent_editor_changes(record, existing, settings, user_id):
    kind = record.get("agent_type", "local")
    flag = next((flag for value, _, flag in _AGENT_TYPES if value == kind), _MISSING)
    if flag is _MISSING:
        raise WorkspaceAuthoringValidation("Select a supported agent type.")
    if flag and not settings.get(flag, False):
        raise PermissionError("This agent type is disabled for personal workspaces.")
    if kind != "local" and record.get("actions_to_load"):
        raise WorkspaceAuthoringValidation("Remove local actions explicitly before selecting a Foundry agent type.")
    if kind == "local":
        configured_connection = any(
            record.get(field) not in (None, "")
            and record.get(field) != (existing or {}).get(field)
            and not (_is_placeholder((existing or {}).get(field)) and _is_reference(record.get(field)))
            for field in _AGENT_CUSTOM_CONNECTION_FIELDS
        )
        if configured_connection and not settings.get("allow_user_custom_endpoints", False):
            raise PermissionError("Custom model connections are disabled for personal workspaces.")
        if configured_connection:
            import_module("functions_governance").ensure_governance_access("governance_user_endpoints", user_id)


def _preserve_unedited_values(original, merged, prepared, *, root=True):
    """Normalization of an edited leaf must not discard untouched legacy siblings."""
    result = deepcopy(prepared)
    for key, previous in original.items():
        if key not in merged or (root and (key in _MANAGED_FIELDS or key.startswith("_"))):
            continue
        if merged[key] == previous:
            result[key] = deepcopy(previous)
        elif isinstance(previous, dict) and isinstance(merged[key], dict) and isinstance(result.get(key), dict):
            result[key] = _preserve_unedited_values(previous, merged[key], result[key], root=False)
    return result


def validate_editor_action_manifest(plugin):
    """Validate personal editor fields that the existing embedding runtime reads at root."""
    validation_copy = dict(plugin)
    if str(plugin.get("type") or "").strip().lower() == "embedding_model":
        for field in ("api_version", "deployment"):
            if field in validation_copy:
                value = validation_copy.pop(field)
                if not isinstance(value, str) or not value.strip():
                    return f"Embedding {field} must be a non-empty string."
    return import_module("json_schema_validation").validate_plugin(validation_copy)


def _editor_validation_input(kind, merged, existing):
    """Retain old extension fields without allowing new unsupported manifest properties."""
    result = deepcopy(merged)
    for field in ("other_settings",) if kind == "agents" else ("auth", "additionalFields", "metadata"):
        if field in result and not isinstance(result[field], dict):
            raise WorkspaceAuthoringValidation("Configuration sections must be JSON objects.")
    if not existing:
        return result
    validation = import_module("json_schema_validation")
    schema = validation.load_schema("agent.schema.json" if kind == "agents" else "plugin.schema.json")
    definition = schema.get("definitions", {}).get("Agent" if kind == "agents" else "Plugin", schema)

    def retain_for_validation(value, previous, field_schema):
        if not isinstance(value, dict) or not isinstance(previous, dict):
            return
        properties = field_schema.get("properties", {})
        if field_schema.get("additionalProperties") is False:
            for key in list(value):
                if key not in properties and key in previous and value[key] == previous[key]:
                    value.pop(key)
        for key in value.keys() & properties.keys():
            retain_for_validation(value[key], previous.get(key), properties[key])

    retain_for_validation(result, existing, definition)
    return result


def _assert_available_name(kind, user_id, record, existing):
    name = record.get("name")
    if not isinstance(name, str) or not name.strip():
        raise WorkspaceAuthoringValidation("A name is required.")
    if existing and name == existing.get("name"):
        return
    matches = _container(kind).query_items(
        query="SELECT c.id FROM c WHERE c.user_id = @user_id AND c.name = @name",
        parameters=[{"name": "@user_id", "value": user_id}, {"name": "@name", "value": name}],
        partition_key=user_id,
    )
    if any(match.get("id") != (existing or {}).get("id") for match in matches):
        raise WorkspaceAuthoringConflict("An item with this name already exists.")
    if kind == "actions":
        matches = _container(kind, "global").query_items(
            query="SELECT c.id FROM c WHERE STRINGEQUALS(c.name, @name, true)",
            parameters=[{"name": "@name", "value": name}], enable_cross_partition_query=True,
        )
        if next(iter(matches), None):
            raise WorkspaceAuthoringConflict("An item with this name already exists.")


def editor_error_response(exc):
    if isinstance(exc, WorkspaceAuthoringConflict):
        status, message = 409, "This resource changed. Reload it before saving."
    elif isinstance(exc, PermissionError):
        status, message = 403, "You are not authorized to manage this workspace resource."
    elif isinstance(exc, LookupError):
        status, message = 404, "This workspace resource is unavailable."
    elif isinstance(exc, WorkspaceAuthoringValidation):
        status, message = 400, exc.public_message
    elif isinstance(exc, ValueError):
        status, message = 400, "Invalid workspace configuration."
    else:
        status, message = 503, "Unable to complete this workspace request. Try again."
    import_module("functions_appinsights").log_event(
        "[WORKSPACE_ROUTE] Personal editor request could not be completed.",
        level=logging.ERROR if status >= 500 else logging.WARNING,
        extra={"error_type": type(exc).__name__, "status_code": status},
        debug_only=status < 500,
    )
    response = jsonify({"error": message})
    response.headers["Cache-Control"] = "no-store"
    return response, status


def personal_editor_response(kind, user_id, prepare, record_id=None, *, migrate=None):
    """Serve only the explicitly opted-in representation on existing personal routes."""
    try:
        settings = import_module("functions_settings").get_settings()
        operation = "read" if request.method == "GET" else "delete" if request.method == "DELETE" else "write"
        ensure_editor_access(kind, user_id, settings, operation=operation)
        scope = request.args.get("scope", "personal")
        if scope not in {"personal", "global"}:
            raise WorkspaceAuthoringValidation("Invalid workspace scope.")
        if scope == "global" and (request.method != "GET" or not record_id):
            raise PermissionError("Provided resources are read-only.")
        if request.method == "GET":
            if not record_id and migrate and (
                kind != "actions" or import_module("functions_governance").is_action_scope_access_allowed(
                    "governance_user_actions", user_id, "personal",
                )
            ):
                migrate(user_id)
            result = editor_resource(
                read_editor_record(kind, user_id, record_id, settings, scope=scope), kind,
                global_scope=scope == "global",
            ) if record_id else list_editor_records(kind, user_id, settings)
            status = 200
        else:
            existing = read_editor_record(kind, user_id, record_id, settings) if record_id else None
            if request.method == "DELETE":
                delete_editor_record(kind, user_id, existing, settings)
                result, status = {"success": True}, 200
            else:
                merged = merge_editor_write(
                    existing or {}, request.get_json(silent=True), kind, creating=existing is None,
                    resolve_stored_placeholder=lambda record, path: _legacy_editor_secret_reference(
                        record, path, kind, user_id, settings,
                    ),
                )
                if not existing:
                    if kind == "agents":
                        try:
                            merged["id"] = str(uuid.UUID(merged.get("id", "")))
                        except (ValueError, TypeError, AttributeError) as exc:
                            raise WorkspaceAuthoringValidation("Allocate an agent ID before saving.") from exc
                    else:
                        merged["id"] = str(uuid.uuid4())
                    display_key = "display_name" if kind == "agents" else "displayName"
                    merged.setdefault(display_key, merged.get("name", ""))
                    merged.setdefault("description", "")
                    if kind == "agents":
                        merged.setdefault("instructions", "")
                if kind == "agents":
                    _validate_agent_editor_changes(merged, existing, settings, user_id)
                proposed = deepcopy(merged)
                prepared, error = prepare(
                    user_id, _editor_validation_input(kind, merged, existing), settings, existing,
                )
                if error:
                    status = error[1] if isinstance(error, tuple) else 400
                    if status == 403:
                        raise PermissionError("This configuration is unavailable.")
                    raise WorkspaceAuthoringValidation("Invalid agent configuration." if kind == "agents" else "Invalid action configuration.")
                if existing:
                    prepared = _preserve_unedited_values(existing, proposed, prepared)
                _assert_available_name(kind, user_id, prepared, existing)
                saved = save_editor_record(kind, user_id, prepared, existing, settings)
                result, status = editor_resource(saved, kind), 200 if existing else 201
            activity = import_module("functions_activity_logging")
            operation = "deletion" if request.method == "DELETE" else "update" if existing else "creation"
            stored = existing if request.method == "DELETE" else saved
            prefix = "agent" if kind == "agents" else "action"
            event = getattr(activity, f"log_{prefix}_{operation}")
            try:
                event(
                    user_id=user_id, scope="personal",
                    **{f"{prefix}_id": stored["id"], f"{prefix}_name": stored.get("name", "")},
                    **({"agent_display_name": stored.get("display_name", "")} if prefix == "agent" and operation != "deletion" else {}),
                    **({"action_type": stored.get("type", "")} if prefix == "action" and operation != "deletion" else {}),
                )
            except Exception as exc:
                import_module("functions_appinsights").log_event(
                    "[WORKSPACE_ACTIVITY] Unable to record a committed editor change.",
                    level=logging.WARNING, extra={"error_type": type(exc).__name__},
                )
        response = jsonify(result)
        response.headers["Cache-Control"] = "no-store"
        return response, status
    except Exception as exc:
        return editor_error_response(exc)


def build_agent_editor_options(user_id, settings, model_endpoints):
    can_manage_agents = ensure_editor_options_access(user_id, settings)
    settings_module = import_module("functions_settings")
    sanitized = settings_module.sanitize_settings_for_user({
        key: deepcopy(settings.get(key, default)) for key, default in _OPTION_DEFAULTS.items()
    })
    safe = {key: sanitized[key] for key in _OPTION_DEFAULTS if key in sanitized}
    safe["allow_user_agents"] = can_manage_agents
    try:
        ensure_editor_access("actions", user_id, settings)
        safe["allow_user_plugins"] = True
    except PermissionError:
        safe["allow_user_plugins"] = False
    if not can_manage_agents:
        model_endpoints = []
        safe["gpt_model"] = {}
        safe["default_model_selection"] = {}
    model_endpoints = settings_module.sanitize_settings_for_user(
        {"model_endpoints": filter_model_endpoints_by_capability(model_endpoints, preserve_empty=True)},
    ).get("model_endpoints", [])
    # These names contain "key"/"secret", but their values are strictly UI flags/defaults.
    try:
        reminder_lead_days = min(3650, max(1, int(settings.get("key_vault_secret_expiration_default_lead_days", 30))))
    except (ValueError, TypeError):
        reminder_lead_days = 30
    reminder_contact = settings.get("key_vault_secret_expiration_default_contact_email", "")
    reminder_options = settings_module.sanitize_settings_for_user({
        "storage_enabled": bool(settings.get("enable_key_vault_secret_storage", False)),
        "reminders_enabled": bool(settings.get("enable_key_vault_secret_expiration_reminders", False)),
        "lead_days": reminder_lead_days,
        "contact_email": reminder_contact[:254] if isinstance(reminder_contact, str) else "",
        "require_expiration": bool(settings.get("key_vault_secret_expiration_require_expiration", False)),
    })
    safe.update({
        "enable_key_vault_secret_storage": reminder_options["storage_enabled"],
        "enable_key_vault_secret_expiration_reminders": reminder_options["reminders_enabled"],
        "key_vault_secret_expiration_default_lead_days": reminder_options["lead_days"],
        "key_vault_secret_expiration_default_contact_email": reminder_options["contact_email"],
        "key_vault_secret_expiration_require_expiration": reminder_options["require_expiration"],
    })
    governance = import_module("functions_governance")
    if safe.get("allow_user_custom_endpoints"):
        try:
            governance.ensure_governance_access("governance_user_endpoints", user_id)
        except PermissionError:
            safe["allow_user_custom_endpoints"] = False
    globals_allowed = governance.filter_governed_model_endpoints(
        user_id, [endpoint for endpoint in model_endpoints if endpoint.get("scope") == "global"],
        "governance_global_endpoints",
    )
    allowed_ids = {endpoint.get("id") for endpoint in globals_allowed}
    endpoints = [
        deepcopy(endpoint) for endpoint in model_endpoints
        if (
            endpoint.get("scope") == "global" and endpoint.get("id") in allowed_ids
        ) or (
            endpoint.get("scope") in {"user", "personal"} and safe.get("allow_user_custom_endpoints")
        )
    ]
    for endpoint in endpoints:
        for path in editor_secret_paths(endpoint, "agents"):
            _set(endpoint, path, EDITOR_SECRET_MASK)
    safe["enable_multi_model_endpoints"] = bool(
        safe.get("enable_multi_model_endpoints") or any(endpoint.get("models") for endpoint in endpoints)
    )
    return {
        "agent_types": [
            {
                "value": value, "label": label,
                "enabled": can_manage_agents and (not flag or bool(settings.get(flag, False))),
                **({"reason": "Agent authoring is unavailable for this personal workspace."} if not can_manage_agents else (
                    {"reason": "Disabled for personal workspaces by your administrator."} if flag and not settings.get(flag, False) else {}
                )),
            }
            for value, label, flag in _AGENT_TYPES
        ],
        "settings": safe,
        "model_endpoints": endpoints,
        "builtin_actions": [
            {"id": value, "label": label}
            for value, label, flag in _BUILTIN_ACTIONS if can_manage_agents and safe.get(flag)
        ],
    }


def build_action_editor_types(discovered_types):
    """Enrich governed discovery with canonical local schemas, without example defaults."""
    validation = import_module("json_schema_validation")
    schema_root = Path(validation.SCHEMA_DIR)
    results = []
    for definition in discovered_types:
        action_type = definition["type"]
        schema_type = validation.normalize_plugin_definition_type(action_type)
        record = {
            "type": action_type,
            "display": definition.get("display") or action_type,
            "description": (
                "Connect to an API using OpenAPI JSON/YAML content and configurable authentication. "
                "Download hosted specifications before uploading them."
                if schema_type == "openapi" else definition.get("description") or ""
            ),
            "allowed_auth_types": sorted(validation.get_allowed_auth_types_for_plugin_type(action_type)),
        }
        for field, suffix in (
            ("additional_fields_schema", "additional_settings"), ("metadata_schema", "metadata"),
        ):
            path = schema_root / f"{schema_type}_plugin.{suffix}.schema.json"
            record[field] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {
                "type": "object", "additionalProperties": True, "properties": {},
            }
        results.append(record)
    return results
