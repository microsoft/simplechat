# functions_action_catalog.py
"""Discover governed actions without loading plugins or resolving credentials.

Storage dependencies are imported only at operation boundaries so the planner
projection remains usable without the Azure application bootstrap. The ordinary
action getters hydrate workspace-identity credentials even in NAME mode. Read
their persisted, secret-reference records directly here and reuse their governance
filters instead; identity hydration belongs exclusively to execution.
"""

import base64
import binascii
import re
from collections.abc import Iterable
from copy import deepcopy
from importlib import import_module

from functions_agent_delegation import AGENT_PLUGIN_TYPE, _identifier


_SCOPES = frozenset({"personal", "group", "global"})
_GROUP_ROLES = ("Owner", "Admin", "DocumentManager", "User")
_UNAVAILABLE = "The action is unavailable or you are not permitted to use it."
_INVALID_REFERENCE = "Select an action using its catalog reference."
_MAX_REFERENCE_LENGTH = 2048
_ENDPOINT_PATTERN = re.compile(r"\b(?:[a-z][a-z0-9+.-]*://|www\.)[^\s<>\"']+", re.IGNORECASE)
_PRIVATE_FIELD_PATTERN = re.compile(
    r"auth|identity|credential|secret|password|token|key|connection|endpoint|hostname|server|url|uri|headers",
    re.IGNORECASE,
)


def _stored_identifier(value, *, max_bytes=128):
    normalized = _identifier(value, "Action reference", max_bytes=max_bytes)
    if normalized != value:
        raise ValueError(_INVALID_REFERENCE)
    return normalized


def _require_actor(user_id):
    if not isinstance(user_id, str) or user_id.strip().lower() in {"", "system"}:
        raise PermissionError("An authenticated action execution identity is required.")
    try:
        return _stored_identifier(user_id)
    except ValueError:
        raise PermissionError("An authenticated action execution identity is required.") from None


def _encode_identifier(value):
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _action_ref(scope_type, scope_id, action_id):
    if scope_type not in _SCOPES:
        raise ValueError(_INVALID_REFERENCE)
    _stored_identifier(scope_id)
    _stored_identifier(action_id, max_bytes=1023)
    if scope_type == "global" and scope_id != "global":
        raise ValueError(_INVALID_REFERENCE)
    return f"action:v1:{scope_type}:{_encode_identifier(scope_id)}:{_encode_identifier(action_id)}"


def _parse_action_ref(action_ref):
    if not isinstance(action_ref, str) or len(action_ref) > _MAX_REFERENCE_LENGTH:
        raise ValueError(_INVALID_REFERENCE)
    parts = action_ref.split(":")
    if len(parts) != 5 or parts[:2] != ["action", "v1"] or parts[2] not in _SCOPES:
        raise ValueError(_INVALID_REFERENCE)
    try:
        scope_id, action_id = (
            base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True).decode("utf-8")
            for value in parts[3:]
        )
        if _action_ref(parts[2], scope_id, action_id) != action_ref:
            raise ValueError(_INVALID_REFERENCE)
    except (ValueError, UnicodeError, binascii.Error):
        raise ValueError(_INVALID_REFERENCE) from None
    return parts[2], scope_id, action_id


def _resolve_settings(settings):
    if settings is None:
        # Settings imports initialize application storage; defer them until discovery.
        settings = import_module("functions_settings").get_settings()
    if not isinstance(settings, dict):
        raise ValueError("Action settings are unavailable.")
    return settings


def _scope_enabled(settings, scope_type):
    if not settings.get("enable_semantic_kernel", False):
        return False
    if scope_type == "personal":
        return bool(settings.get("allow_user_plugins", False) and settings.get("enable_user_workspace", True))
    if scope_type == "group":
        return bool(settings.get("allow_group_plugins", False) and settings.get("enable_group_workspaces", False))
    return bool(
        not settings.get("per_user_semantic_kernel", False)
        or settings.get("merge_global_semantic_kernel_with_workspace", False)
    )


def _selected_group_ids(user_groups):
    if user_groups is None:
        return None
    if not isinstance(user_groups, Iterable) or isinstance(user_groups, (str, bytes, dict)):
        raise ValueError("Action workspace selection is invalid.")
    selected = set()
    for group in user_groups:
        group_id = group.get("id") if isinstance(group, dict) else group
        try:
            selected.add(_stored_identifier(group_id))
        except ValueError:
            continue
    return selected


def _current_groups(user_id, user_groups):
    selected = _selected_group_ids(user_groups)
    if selected == set():
        return []
    # Caller selections narrow a fresh membership listing; their labels/roles are not trusted.
    groups = import_module("functions_group").get_user_groups(user_id)
    current = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        try:
            group_id = _stored_identifier(group.get("id"))
        except ValueError:
            continue
        if selected is None or group_id in selected:
            current[group_id] = group
    return list(current.values())


def _assert_group_access(user_id, group_id):
    import_module("functions_group").assert_group_role(
        user_id, group_id, allowed_roles=_GROUP_ROLES,
    )


def resolve_current_user_groups(user_id, user_groups=None):
    """Resolve ID/record selectors to fresh, role-checked membership records."""
    user_id = _require_actor(user_id)
    groups = []
    for group in _current_groups(user_id, user_groups):
        try:
            _assert_group_access(user_id, group["id"])
        except (PermissionError, LookupError):
            continue
        groups.append(group)
    return groups


def _container(scope_type):
    # Raw reads avoid the ordinary getters' workspace-identity credential hydration.
    return getattr(import_module("config"), f"cosmos_{scope_type}_actions_container")


def _stored_actions(scope_type, scope_id):
    if scope_type == "global":
        return _container(scope_type).query_items(
            query="SELECT * FROM c WHERE NOT IS_DEFINED(c.is_enabled) OR c.is_enabled = true",
            enable_cross_partition_query=True,
        )
    owner_field = "user_id" if scope_type == "personal" else "group_id"
    return _container(scope_type).query_items(
        query=f"SELECT * FROM c WHERE c.{owner_field} = @scope_id",
        parameters=[{"name": "@scope_id", "value": scope_id}],
        partition_key=scope_id,
    )


def _owns_record(action, scope_type, scope_id):
    if scope_type == "personal":
        return action.get("user_id") == scope_id
    if scope_type == "group":
        return action.get("group_id") == scope_id
    return True


def _eligible_record(action, scope_type, scope_id):
    if not isinstance(action, dict) or not _owns_record(action, scope_type, scope_id):
        return False
    action_type = action.get("type")
    if (
        not isinstance(action_type, str)
        or not action_type.strip()
        or action_type.strip().lower() == AGENT_PLUGIN_TYPE
        or action.get("is_enabled", True) is not True
    ):
        return False
    try:
        _action_ref(scope_type, scope_id, action.get("id"))
    except ValueError:
        return False
    return True


def _private_values(source):
    """Find credential/connection values that must not be echoed in descriptive text."""
    values = set()
    pending = [(source, False)]
    while pending:
        value, private = pending.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {"type", "auth_type"}:
                    continue
                pending.append((child, private or bool(_PRIVATE_FIELD_PATTERN.search(str(key)))))
        elif isinstance(value, (list, tuple)):
            pending.extend((child, private) for child in value)
        elif private and isinstance(value, str) and value:
            values.add(value)
    return sorted(values, key=lambda value: (-len(value), value))


def _safe_text(value, limit, private_values=()):
    if not isinstance(value, str):
        return ""
    for private in private_values:
        value = value.replace(private, "[redacted]")
    value = _ENDPOINT_PATTERN.sub("[endpoint]", value)
    return " ".join(value.split())[:limit]


def _description(action):
    description = action.get("description")
    if isinstance(description, str) and description.strip():
        return description
    metadata = action.get("metadata")
    return metadata.get("description", "") if isinstance(metadata, dict) else ""


def _descriptor(action, scope_type, scope_id, scope_label):
    private_values = _private_values(action)
    name = _safe_text(action.get("name"), 200, private_values)
    display_name = (
        _safe_text(action.get("display_name"), 200, private_values)
        or _safe_text(action.get("displayName"), 200, private_values)
        or name
        or "Action"
    )
    return {
        "action_ref": _action_ref(scope_type, scope_id, action["id"]),
        "id": action["id"],
        "name": name,
        "display_name": display_name,
        "description": _safe_text(_description(action), 1000, private_values),
        "type": _safe_text(action.get("type"), 80, private_values),
        "scope_type": scope_type,
        "scope_id": scope_id,
        "scope_label": _safe_text(scope_label, 200, private_values) or scope_type.title(),
    }


def build_accessible_action_catalog(user_id, *, settings=None, user_groups=None):
    """Return safe metadata for enabled, governed actions belonging to this actor.

    ``user_id`` must be captured from authenticated server context, never from plan
    arguments. ``user_groups`` may contain group IDs or group records and only
    narrows current membership. Global actions retain their own scope and are
    available in global mode, or when global/workspace merging is enabled.
    """
    user_id = _require_actor(user_id)
    settings = _resolve_settings(settings)
    if not settings.get("enable_semantic_kernel", False):
        return []

    # Reuse governance without importing plugin loaders or credential-hydrating getters.
    governance = import_module("functions_governance")
    scopes = []
    if _scope_enabled(settings, "personal"):
        scopes.append(("personal", user_id, "Personal"))
    if _scope_enabled(settings, "global"):
        scopes.append(("global", "global", "Global"))
    if _scope_enabled(settings, "group"):
        for group in resolve_current_user_groups(user_id, user_groups):
            group_id = group["id"]
            scopes.append(("group", group_id, group.get("name") or "Group"))

    catalog = {}
    for scope_type, scope_id, scope_label in scopes:
        actions = [
            action for action in _stored_actions(scope_type, scope_id)
            if _eligible_record(action, scope_type, scope_id)
        ]
        if scope_type == "global":
            actions = governance.filter_governed_global_actions_for_user(user_id, actions)
        else:
            feature = "governance_user_actions" if scope_type == "personal" else "governance_group_actions"
            actions = governance.filter_actions_by_action_type_access(user_id, actions, feature, scope_type)
        for action in actions:
            descriptor = _descriptor(action, scope_type, scope_id, scope_label)
            catalog.setdefault(descriptor["action_ref"], descriptor)
    return list(catalog.values())


def build_action_planner_projection(actions):
    """Project catalog descriptions only, never manifests or function schemas."""
    projection = []
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        action_ref = action.get("action_ref")
        action_type = action.get("type")
        if (
            not isinstance(action_ref, str)
            or not action_ref
            or len(action_ref) > _MAX_REFERENCE_LENGTH
            or not isinstance(action_type, str)
            or action_type.strip().lower() in {"", AGENT_PLUGIN_TYPE}
        ):
            continue
        private_values = _private_values(action)
        projection.append({
            "action_ref": action_ref,
            "display_name": _safe_text(action.get("display_name"), 200, private_values) or "Action",
            "description": _safe_text(_description(action), 1000, private_values),
            "type": _safe_text(action_type, 80, private_values),
            "scope_label": _safe_text(action.get("scope_label"), 200, private_values),
        })
    return projection


def resolve_action_manifest(user_id, action_ref, *, settings=None, user_groups=None):
    """Reauthorize an exact stored ID and return its secret-reference manifest.

    No lookup by name, plugin initialization, or workspace-identity hydration is
    performed. Execution must hydrate credentials only after this boundary.
    """
    user_id = _require_actor(user_id)
    scope_type, scope_id, action_id = _parse_action_ref(action_ref)
    if scope_type == "personal" and scope_id != user_id:
        raise PermissionError(_UNAVAILABLE)
    settings = _resolve_settings(settings)
    if not _scope_enabled(settings, scope_type):
        raise PermissionError(_UNAVAILABLE)
    scope_label = scope_type.title()
    if scope_type == "group":
        group = next(
            (group for group in _current_groups(user_id, user_groups) if group["id"] == scope_id),
            None,
        )
        if group is None:
            raise PermissionError(_UNAVAILABLE)
        try:
            _assert_group_access(user_id, scope_id)
        except (PermissionError, LookupError):
            raise PermissionError(_UNAVAILABLE) from None
        scope_label = group.get("name") or "Group"

    # Runtime-only Azure import; exact point reads cannot substitute a same-name action.
    from azure.cosmos.exceptions import CosmosResourceNotFoundError

    try:
        action = _container(scope_type).read_item(
            item=action_id,
            partition_key=action_id if scope_type == "global" else scope_id,
        )
    except CosmosResourceNotFoundError:
        raise LookupError(_UNAVAILABLE) from None
    if not isinstance(action, dict) or action.get("id") != action_id:
        raise LookupError(_UNAVAILABLE)
    if not _eligible_record(action, scope_type, scope_id):
        raise PermissionError(_UNAVAILABLE)

    governance = import_module("functions_governance")
    try:
        if scope_type == "global":
            governance.ensure_global_action_access(user_id, action)
        else:
            feature = "governance_user_actions" if scope_type == "personal" else "governance_group_actions"
            governance.ensure_action_type_access(feature, user_id, action["type"], scope_type)
    except PermissionError:
        raise PermissionError(_UNAVAILABLE) from None

    # NAME preserves stored references; do not call the identity-hydrating action getters.
    keyvault = import_module("functions_keyvault")
    manifest = keyvault.keyvault_plugin_get_helper(
        deepcopy({key: value for key, value in action.items() if not key.startswith("_")}),
        scope_value=action_id if scope_type == "global" else scope_id,
        scope="user" if scope_type == "personal" else scope_type,
        return_type=keyvault.SecretReturnType.NAME,
    )
    manifest.update({
        "user_id": scope_id if scope_type == "personal" else None,
        "group_id": scope_id if scope_type == "group" else None,
        "is_global": scope_type == "global",
        "is_group": scope_type == "group",
        "scope": "user" if scope_type == "personal" else scope_type,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "scope_label": _descriptor(action, scope_type, scope_id, scope_label)["scope_label"],
        "action_ref": action_ref,
    })
    return manifest
