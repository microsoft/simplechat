# functions_legacy_action_management.py
"""Safe historical-action views, source identities, and scoped save validation."""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json

from functions_action_manifest import (
    McpConfigurationError,
    McpStdioRemovedError,
    bind_action_origin,
    get_action_execution_status,
    get_action_origin,
    is_retired_mcp_stdio,
    resolve_action_type,
)


LEGACY_ACTION_PREFIX = "legacy-action-"
LEGACY_ACTION_SOURCE = "settings.plugins"
_MANAGEMENT_FIELDS = {
    "execution_status", "is_legacy", "legacy_source", "legacy_locator",
}
_DISPLAY_FIELDS = (
    "id", "name", "displayName", "description", "created_by", "created_at",
    "modified_by", "modified_at", "last_updated", "updated_at",
)


class LegacyActionConflictError(ValueError):
    """The selected source or destination no longer matches the verified record."""

    code = "legacy_action_conflict"
    public_message = "This legacy action has changed. Refresh the action list and try again."

    def __init__(self):
        super().__init__(self.public_message)


class LegacyActionSourceUpdateError(RuntimeError):
    """A stored destination was not followed by confirmed source cleanup."""

    code = "legacy_source_update_failed"
    public_message = (
        "The legacy settings could not be updated. The original action was retained; "
        "refresh and retry."
    )

    def __init__(self):
        super().__init__(self.public_message)


class LegacyActionSecretConflictError(LegacyActionConflictError):
    """Distinct action IDs must not overwrite the same name-based secret storage."""

    code = "legacy_secret_name_conflict"
    public_message = (
        "Another action uses the same credential storage name. "
        "Choose a different action name before saving or reconfiguring it."
    )


@dataclass(frozen=True)
class LegacyActionSnapshot:
    """An internal snapshot from an authorized owner's settings, never request data."""

    owner_id: str
    locator: str
    record: object
    index: int
    duplicate_count: int


def action_snapshot_digest(value):
    """Fingerprint JSON without revealing its credential-bearing contents."""
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def legacy_action_snapshots(user_id, plugins):
    """Identify records by owner and exact content, not name or aggregate counts.

    Including identical-record multiplicity prevents replaying a deleted duplicate's
    locator against a different, indistinguishable remaining copy.
    """
    if not isinstance(plugins, list):
        raise LegacyActionConflictError()
    fingerprints = [
        action_snapshot_digest([LEGACY_ACTION_SOURCE, str(user_id), plugin])
        for plugin in plugins
    ]
    totals = Counter(fingerprints)
    occurrences = Counter()
    snapshots = []
    for index, (plugin, fingerprint) in enumerate(zip(plugins, fingerprints)):
        occurrence = occurrences[fingerprint]
        occurrences[fingerprint] += 1
        locator = f"{LEGACY_ACTION_PREFIX}{fingerprint}-{totals[fingerprint]}-{occurrence}"
        snapshots.append(LegacyActionSnapshot(
            owner_id=str(user_id),
            locator=locator,
            record=deepcopy(plugin),
            index=index,
            duplicate_count=totals[fingerprint],
        ))
    return snapshots


def find_legacy_action_snapshot(user_id, plugins, locator):
    """Resolve only a freshly derived, owner-bound source locator."""
    if not isinstance(locator, str) or not locator.startswith(LEGACY_ACTION_PREFIX):
        raise LegacyActionConflictError()
    for snapshot in legacy_action_snapshots(user_id, plugins):
        if snapshot.locator == locator:
            return snapshot
    raise LegacyActionConflictError()


def _safe_management_view(manifest, scope_type, scope_id):
    original = manifest if isinstance(manifest, dict) else {}
    view = {
        field: original[field]
        for field in _DISPLAY_FIELDS
        if isinstance(original.get(field), str)
    }
    try:
        action_type = resolve_action_type(original)
    except ValueError:
        action_type = ""
    view.setdefault("name", "")
    view.setdefault("displayName", view["name"])
    view.setdefault("description", "")
    view.update({
        "type": action_type,
        "endpoint": "",
        "auth": {"type": "NoAuth"},
        "metadata": {"type": action_type},
        "additionalFields": {},
    })
    if "is_enabled" in original:
        view["is_enabled"] = original["is_enabled"] is True
    elif scope_type == "global":
        view["is_enabled"] = True
    status = get_action_execution_status(original)
    if status:
        view["additionalFields"]["transport"] = "stdio"
    view = bind_action_origin(view, scope_type, scope_id)
    if status:
        view["execution_status"] = status
    return view


def retired_action_management_view(manifest, scope_type, scope_id):
    """Return a credential-free retired view, or None for an unrelated record."""
    if not is_retired_mcp_stdio(manifest):
        return None
    return _safe_management_view(manifest, scope_type, scope_id)


def is_unchanged_retired_action(submitted, original, scope_type, scope_id):
    """Compare the complete server-produced view; status is never authority."""
    expected = retired_action_management_view(original, scope_type, scope_id)
    return expected is not None and isinstance(submitted, dict) and submitted == expected


def legacy_action_management_view(snapshot):
    """Expose a legacy source without hydrating credentials or process settings."""
    view = _safe_management_view(snapshot.record, "personal", snapshot.owner_id)
    view["id"] = snapshot.locator
    view["is_legacy"] = True
    view["legacy_source"] = LEGACY_ACTION_SOURCE
    view["legacy_locator"] = snapshot.locator
    status = view.get("execution_status") or {
        "state": "unavailable",
        "code": "legacy_action_requires_migration",
        "message": "This action remains in legacy settings. Reconfigure it or delete it.",
    }
    view = bind_action_origin(view, "personal", snapshot.owner_id)
    view["execution_status"] = status
    return view


def is_unchanged_legacy_action(submitted, snapshot):
    """Require an exact safe view from the currently authorized source snapshot."""
    return isinstance(submitted, dict) and submitted == legacy_action_management_view(snapshot)


def prepare_scoped_action(action, scope_type, scope_id):
    """Clone and bind an incoming action, rejecting retired transports immediately."""
    if not isinstance(action, dict):
        raise ValueError("Action configuration must be an object.")
    payload = {
        key: deepcopy(value)
        for key, value in action.items()
        if not key.startswith("_") and key not in _MANAGEMENT_FIELDS
    }
    payload = bind_action_origin(payload, scope_type, scope_id)
    if is_retired_mcp_stdio(payload):
        raise McpStdioRemovedError()
    if payload["type"] == "mcp":
        # Save-time normalization is deferred so management-only inspection never
        # loads preset catalogs or executable action dependencies during bootstrap.
        from functions_mcp_operations import (
            normalize_mcp_additional_fields,
            validate_mcp_endpoint_for_transport,
        )

        fields = payload.get("additionalFields", {})
        if not isinstance(fields, dict):
            raise McpConfigurationError("MCP additional settings must be an object.")
        payload["additionalFields"] = normalize_mcp_additional_fields(fields)
        errors = validate_mcp_endpoint_for_transport(
            payload.get("endpoint"), payload["additionalFields"]["transport"]
        )
        if errors:
            raise McpConfigurationError("A valid remote MCP endpoint is required.")
    return payload


def validate_action_configuration(action):
    """Use the normal schema and health validators before an import can write secrets."""
    # Health validation imports plugin classes and configuration-dependent modules.
    # Load it only at the save boundary, after settings/bootstrap initialization.
    from json_schema_validation import validate_plugin
    from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker

    schema_error = validate_plugin(action)
    if schema_error:
        raise McpConfigurationError("Action configuration is invalid.")
    valid, _errors = PluginHealthChecker.validate_plugin_manifest(action, resolve_action_type(action))
    if not valid:
        raise McpConfigurationError("Action configuration is invalid.")


def authorize_scoped_mcp_secret_read(action, settings):
    """Authorize value hydration using the current caller, never a manifest principal."""
    # Runtime policy imports are deferred until credential use; management-only
    # inspection must remain independent of settings and connector initialization.
    from functions_mcp_preconfigurations import authorize_mcp_action

    return authorize_mcp_action(action, settings=settings, operation="action_secret_resolution")


def validate_scoped_mcp_action(action, user_id, settings):
    """Validate MCP configuration and current policy using an already bound origin."""
    if resolve_action_type(action) != "mcp":
        return
    if is_retired_mcp_stdio(action):
        raise McpStdioRemovedError()
    origin = get_action_origin(action)
    if origin is None or not user_id:
        raise PermissionError("An authorized action scope and current user are required.")
    validate_action_configuration(action)

    # Policy modules are needed only for executable saves; management projections
    # stay independent of governance/settings initialization.
    from functions_mcp_destinations import (
        assert_mcp_destination_allowed,
        get_mcp_destination_policy_config,
    )
    from functions_mcp_preconfigurations import assert_mcp_preconfiguration_manifest_allowed

    policy = get_mcp_destination_policy_config(settings, user_id=user_id)
    assert_mcp_destination_allowed(
        action,
        scope_type=origin.scope_type,
        scope_id=origin.scope_id,
        user_id=user_id,
        policy_config=policy,
        operation="action_save",
    )
    assert_mcp_preconfiguration_manifest_allowed(
        action,
        scope_type=origin.scope_type,
        scope_id=origin.scope_id,
        user_id=user_id,
        settings=settings,
        operation="action_save",
    )
