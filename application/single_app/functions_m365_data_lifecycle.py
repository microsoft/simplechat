# functions_m365_data_lifecycle.py
"""Exclude live delegated authority and retired actions from data transfers."""

from functions_m365_action_cards import strip_pending_action_references
from json_schema_validation import (
    ACTION_MIGRATION_ID_PREFIX,
    is_legacy_msgraph_type,
    validate_legacy_action_update,
    validate_legacy_plugin_settings_update,
)


def _is_retired_action(document):
    if not isinstance(document, dict):
        return False
    metadata = document.get("metadata")
    return is_legacy_msgraph_type(
        document.get("type") or (metadata.get("type") if isinstance(metadata, dict) else None)
    )


def is_live_m365_authorization(document):
    if not isinstance(document, dict):
        return False
    return (
        _is_retired_action(document)
        or bool(document.get("_action_migration"))
        or str(document.get("id") or "").startswith(ACTION_MIGRATION_ID_PREFIX)
        or document.get("record_kind") in {"m365_user_policy", "m365_approval"}
        or document.get("type") == "m365_execution_request"
        or (document.get("type") == "msgraph_pending_action" and bool(document.get("m365_execution")))
        or (
            document.get("kind") in {"connection", "oauth_flow"}
            and ("encrypted_cache" in document or str(document.get("id", "")).startswith("m365"))
        )
    )


def validate_m365_admin_record_edit(original, document):
    """Raw admin editing must not mint subject consent or resurrect retired types."""
    for candidate in (original, document):
        if (
            candidate.get("record_kind") == "m365_audit"
            or (is_live_m365_authorization(candidate) and not _is_retired_action(candidate))
        ):
            raise ValueError("Manage Microsoft 365 consent and connections through Profile and Approvals.")
    validate_legacy_action_update(document, original)
    for previous, incoming in (
        (original, document),
        (original.get("settings") or {}, document.get("settings") or {}),
    ):
        if isinstance(incoming, dict) and any(
            isinstance(incoming.get(key), list) and any(
                _is_retired_action(item)
                for item in incoming[key]
            )
            for key in ("plugins", "semantic_kernel_plugins")
        ):
            validate_legacy_plugin_settings_update(previous, incoming)


def strip_m365_runtime_references(document, *, log_event=None):
    result = strip_pending_action_references(document)
    if "m365_binding_approval_id" in result:
        result["m365_binding_approval_id"] = None
    if "m365_run_as_user_id" in result:
        result["active_run_id"] = ""
        result["status"] = "idle"
    removed = 0
    if isinstance(result.get("settings"), dict):
        result["settings"] = strip_m365_runtime_references(result["settings"], log_event=log_event)
    for key in ("plugins", "semantic_kernel_plugins"):
        if isinstance(result.get(key), list):
            filtered = [
                item for item in result[key]
                if not _is_retired_action(item)
            ]
            removed += len(result[key]) - len(filtered)
            result[key] = filtered
    if removed:
        if log_event is None:
            raise ValueError("Retired-action transfer exclusions require a logger.")
        log_event(
            "[DATA_MANAGEMENT] Excluded retired combined Graph actions from transferred settings.",
            {"excluded_count": removed},
        )
    return result
