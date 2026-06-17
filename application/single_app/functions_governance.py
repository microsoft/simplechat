# functions_governance.py

"""Governance policy helpers for agents, actions, and endpoints."""

from copy import deepcopy
from datetime import datetime
from threading import RLock
from time import monotonic
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from flask import g, has_request_context

import app_settings_cache
from config import cosmos_governance_item_policies_container, cosmos_governance_policies_container
from functions_activity_logging import log_governance_change
from functions_group import get_user_groups
from functions_public_workspaces import get_user_public_workspaces
from functions_settings import get_settings


DEFAULT_FEATURE_POLICIES = {
    "governance_user_endpoints": "user_endpoints",
    "governance_group_endpoints": "group_endpoints",
    "governance_global_endpoints": "global_endpoints",
    "governance_user_agents": "user_agents",
    "governance_group_agents": "group_agents",
    "governance_global_agents_usage": "global_agents_usage",
    "governance_user_actions": "user_actions",
    "governance_group_actions": "group_actions",
    "governance_global_actions_usage": "global_actions_usage",
}


DEFAULT_ITEM_POLICY_ENTITY_TYPES = {
    "global_endpoint",
    "global_agent",
    "global_action",
    "personal_action_type",
    "group_action_type",
    "global_action_type",
}


ACTION_TYPE_POLICY_ENTITY_TYPES = {
    "personal": "personal_action_type",
    "user": "personal_action_type",
    "group": "group_action_type",
    "global": "global_action_type",
}


ACTION_TYPE_FEATURE_KEYS = {
    "personal": "governance_user_actions",
    "user": "governance_user_actions",
    "group": "governance_group_actions",
    "global": "governance_global_actions_usage",
}


ACTION_TYPE_ALIASES = {
    "sql_query": "sql",
    "sql_schema": "sql",
    "sql": "sql",
    "simplechat": "simplechat",
    "simple_chat": "simplechat",
    "openapi": "openapi",
    "open_api": "openapi",
    "mcp": "mcp",
    "model_context_protocol": "mcp",
    "msgraph": "msgraph",
    "microsoft_graph": "msgraph",
    "databricks_table": "databricks",
    "databricks": "databricks",
    "tableau": "tableau",
    "chart": "chart",
    "azure_maps": "azure_maps",
    "blob_storage": "blob_storage",
    "document_search": "document_search",
    "search": "document_search",
}


ACTION_TYPE_LABELS = {
    "sql": "SQL",
    "simplechat": "SimpleChat",
    "openapi": "OpenAPI",
    "mcp": "MCP",
    "msgraph": "Microsoft Graph",
    "databricks": "Databricks",
    "tableau": "Tableau",
    "chart": "Chart",
    "azure_maps": "Azure Maps",
    "blob_storage": "Blob Storage",
    "document_search": "Document Search",
}


LEGACY_ITEM_POLICY_ENTITY_TYPE_ALIASES = {
    "endpoint": "global_endpoint",
}


GOVERNANCE_CACHE_TTL_SECONDS = 60
_GOVERNANCE_REQUEST_CACHE_ATTR = "simplechat_governance_request_cache"
_GOVERNANCE_CACHE_MISS = object()
_governance_cache_lock = RLock()
_governance_cache_version = 0
_governance_process_cache: Dict[Any, Dict[str, Any]] = {}


def _clone_cache_value(value: Any) -> Any:
    return deepcopy(value)


def _get_request_cache() -> Optional[Dict[Any, Any]]:
    if not has_request_context():
        return None

    cache = getattr(g, _GOVERNANCE_REQUEST_CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(g, _GOVERNANCE_REQUEST_CACHE_ATTR, cache)
    return cache


def _get_request_cache_value(cache_key: Any) -> Any:
    cache = _get_request_cache()
    if cache is None or cache_key not in cache:
        return _GOVERNANCE_CACHE_MISS
    return _clone_cache_value(cache[cache_key])


def _set_request_cache_value(cache_key: Any, value: Any) -> None:
    cache = _get_request_cache()
    if cache is not None:
        cache[cache_key] = _clone_cache_value(value)


def _get_shared_governance_cache_version() -> int:
    getter = getattr(app_settings_cache, "get_governance_cache_version", None)
    if callable(getter):
        try:
            return int(getter() or 0)
        except Exception:
            return _governance_cache_version
    return _governance_cache_version


def _bump_shared_governance_cache_version() -> int:
    global _governance_cache_version

    bumper = getattr(app_settings_cache, "bump_governance_cache_version", None)
    if callable(bumper):
        try:
            _governance_cache_version = int(bumper() or 0)
            return _governance_cache_version
        except Exception:
            pass

    _governance_cache_version += 1
    return _governance_cache_version


def _get_process_cache_value(cache_key: Any) -> Any:
    now = monotonic()
    current_version = _get_shared_governance_cache_version()
    with _governance_cache_lock:
        entry = _governance_process_cache.get(cache_key)
        if not entry:
            return _GOVERNANCE_CACHE_MISS

        if entry.get("version") != current_version or entry.get("expires_at", 0) <= now:
            _governance_process_cache.pop(cache_key, None)
            return _GOVERNANCE_CACHE_MISS

        return _clone_cache_value(entry.get("value"))


def _set_process_cache_value(cache_key: Any, value: Any) -> None:
    current_version = _get_shared_governance_cache_version()
    with _governance_cache_lock:
        _governance_process_cache[cache_key] = {
            "expires_at": monotonic() + GOVERNANCE_CACHE_TTL_SECONDS,
            "version": current_version,
            "value": _clone_cache_value(value),
        }


def _get_request_cached_governance_value(cache_key: Any, loader) -> Any:
    cached_value = _get_request_cache_value(cache_key)
    if cached_value is not _GOVERNANCE_CACHE_MISS:
        return cached_value

    loaded_value = loader()
    _set_request_cache_value(cache_key, loaded_value)
    return loaded_value


def _get_cached_governance_value(cache_key: Any, loader) -> Any:
    cached_value = _get_request_cache_value(cache_key)
    if cached_value is not _GOVERNANCE_CACHE_MISS:
        return cached_value

    cached_value = _get_process_cache_value(cache_key)
    if cached_value is not _GOVERNANCE_CACHE_MISS:
        _set_request_cache_value(cache_key, cached_value)
        return cached_value

    loaded_value = loader()
    _set_process_cache_value(cache_key, loaded_value)
    _set_request_cache_value(cache_key, loaded_value)
    return loaded_value


def invalidate_governance_cache() -> None:
    _bump_shared_governance_cache_version()

    with _governance_cache_lock:
        _governance_process_cache.clear()

    request_cache = _get_request_cache()
    if request_cache is not None:
        request_cache.clear()


def _normalize_str_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    normalized: List[str] = []
    seen: Set[str] = set()
    for value in values:
        as_str = str(value or "").strip()
        if not as_str:
            continue
        if as_str in seen:
            continue
        seen.add(as_str)
        normalized.append(as_str)
    return normalized


def _normalize_item_policy_entity_type(entity_type: str) -> str:
    normalized_entity_type = str(entity_type or "").strip().lower()
    return LEGACY_ITEM_POLICY_ENTITY_TYPE_ALIASES.get(normalized_entity_type, normalized_entity_type)


def _normalize_item_policy_item_id(entity_type: str, item_id: str) -> str:
    normalized_entity_type = _normalize_item_policy_entity_type(entity_type)
    if normalized_entity_type in set(ACTION_TYPE_POLICY_ENTITY_TYPES.values()):
        return normalize_governed_action_type(item_id)
    return str(item_id or "").strip()


def _get_legacy_item_policy_entity_types(entity_type: str) -> List[str]:
    normalized_entity_type = _normalize_item_policy_entity_type(entity_type)
    return [
        legacy_entity_type
        for legacy_entity_type, current_entity_type in LEGACY_ITEM_POLICY_ENTITY_TYPE_ALIASES.items()
        if current_entity_type == normalized_entity_type
    ]


def _item_policy_document_id(entity_type: str, item_id: str, policy_id: str) -> str:
    normalized_entity_type = _normalize_item_policy_entity_type(entity_type)
    normalized_item_id = _normalize_item_policy_item_id(normalized_entity_type, item_id)
    normalized_policy_id = str(policy_id or "default").strip() or "default"
    return f"item:{normalized_entity_type}:{normalized_item_id}:{normalized_policy_id}"


def _legacy_item_policy_document_id(entity_type: str, item_id: str) -> str:
    normalized_entity_type = _normalize_item_policy_entity_type(entity_type)
    normalized_item_id = _normalize_item_policy_item_id(normalized_entity_type, item_id)
    return f"item:{normalized_entity_type}:{normalized_item_id}"


def _extract_policy_id_from_item_doc(policy: Dict[str, Any], entity_type: str, item_id: str) -> str:
    explicit_policy_id = str((policy or {}).get("policy_id") or "").strip()
    if explicit_policy_id:
        return explicit_policy_id

    doc_id = str((policy or {}).get("id") or "").strip()
    normalized_entity_type = _normalize_item_policy_entity_type(entity_type)
    normalized_item_id = _normalize_item_policy_item_id(normalized_entity_type, item_id)
    prefix = f"item:{normalized_entity_type}:{normalized_item_id}:"
    if doc_id.startswith(prefix):
        suffix = doc_id[len(prefix):].strip()
        if suffix:
            return suffix

    return "default"


def _default_item_policy_name(entity_type: str, item_id: str, resource_label: str = "") -> str:
    label = str(resource_label or "").strip() or str(item_id or "").strip() or "Resource"
    entity_label = _normalize_item_policy_entity_type(entity_type).replace("_", " ").title()
    return f"{label} {entity_label} Policy"


def _normalize_item_policy_doc(policy: Dict[str, Any]) -> Dict[str, Any]:
    normalized_policy = dict(policy)
    normalized_entity_type = _normalize_item_policy_entity_type(normalized_policy.get("entity_type", ""))
    normalized_item_id = _normalize_item_policy_item_id(normalized_entity_type, normalized_policy.get("item_id") or "")
    normalized_policy_id = _extract_policy_id_from_item_doc(normalized_policy, normalized_entity_type, normalized_item_id)
    normalized_resource_label = str(normalized_policy.get("resource_label") or "").strip()
    normalized_policy_name = str(normalized_policy.get("policy_name") or "").strip() or _default_item_policy_name(
        normalized_entity_type,
        normalized_item_id,
        normalized_resource_label,
    )
    normalized_policy["id"] = _item_policy_document_id(normalized_entity_type, normalized_item_id, normalized_policy_id)
    normalized_policy["policy_id"] = normalized_policy_id
    normalized_policy["policy_name"] = normalized_policy_name
    normalized_policy["resource_label"] = normalized_resource_label
    normalized_policy["entity_type"] = normalized_entity_type
    normalized_policy["item_id"] = normalized_item_id
    normalized_policy.update(_normalize_policy_state(normalized_policy))
    return normalized_policy


def _extract_group_ids(group_docs: Any) -> List[str]:
    if not isinstance(group_docs, list):
        return []
    group_ids: List[str] = []
    seen: Set[str] = set()
    for group_doc in group_docs:
        group_id = str((group_doc or {}).get("id") or "").strip()
        if not group_id or group_id in seen:
            continue
        seen.add(group_id)
        group_ids.append(group_id)
    return group_ids


def _extract_workspace_ids(workspace_docs: Any) -> List[str]:
    if not isinstance(workspace_docs, list):
        return []
    workspace_ids: List[str] = []
    seen: Set[str] = set()
    for workspace_doc in workspace_docs:
        workspace_id = str((workspace_doc or {}).get("id") or "").strip()
        if not workspace_id or workspace_id in seen:
            continue
        seen.add(workspace_id)
        workspace_ids.append(workspace_id)
    return workspace_ids


def _default_feature_policy_doc(feature_key: str) -> Dict[str, Any]:
    return {
        "id": f"feature:{feature_key}",
        "feature_key": feature_key,
        "allow_all": True,
        "allowed_users": [],
        "allowed_groups": [],
        "updated_at": datetime.utcnow().isoformat(),
    }


def _default_item_policy_doc(
    entity_type: str,
    item_id: str,
    policy_id: str = "default",
    policy_name: str = "",
    resource_label: str = "",
) -> Dict[str, Any]:
    normalized_entity_type = _normalize_item_policy_entity_type(entity_type)
    normalized_item_id = _normalize_item_policy_item_id(normalized_entity_type, item_id)
    normalized_policy_id = str(policy_id or "default").strip() or "default"
    normalized_resource_label = str(resource_label or "").strip()
    normalized_policy_name = str(policy_name or "").strip() or _default_item_policy_name(
        normalized_entity_type,
        normalized_item_id,
        normalized_resource_label,
    )
    return {
        "id": _item_policy_document_id(normalized_entity_type, normalized_item_id, normalized_policy_id),
        "policy_id": normalized_policy_id,
        "policy_name": normalized_policy_name,
        "resource_label": normalized_resource_label,
        "entity_type": normalized_entity_type,
        "item_id": normalized_item_id,
        "allow_all": True,
        "allowed_users": [],
        "allowed_groups": [],
        "updated_at": datetime.utcnow().isoformat(),
    }


def _normalize_policy_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    allow_all = bool(payload.get("allow_all", True))
    allowed_users = _normalize_str_list(payload.get("allowed_users", []))
    allowed_groups = _normalize_str_list(payload.get("allowed_groups", []))

    if allow_all and (allowed_users or allowed_groups):
        allow_all = False

    if allow_all:
        allowed_users = []
        allowed_groups = []

    return {
        "allow_all": allow_all,
        "allowed_users": allowed_users,
        "allowed_groups": allowed_groups,
    }


def _read_feature_policy(feature_key: str) -> Dict[str, Any]:
    try:
        return _read_stored_feature_policy(feature_key)
    except Exception:
        return _default_feature_policy_doc(feature_key)


def _read_stored_feature_policy(feature_key: str) -> Dict[str, Any]:
    policy_id = f"feature:{feature_key}"
    return cosmos_governance_policies_container.read_item(item=policy_id, partition_key=policy_id)


def _read_item_policies(entity_type: str, item_id: str, include_default: bool = True) -> List[Dict[str, Any]]:
    normalized_entity_type = _normalize_item_policy_entity_type(entity_type)
    normalized_item_id = _normalize_item_policy_item_id(normalized_entity_type, item_id)
    if not normalized_item_id:
        return [_default_item_policy_doc(normalized_entity_type, normalized_item_id)] if include_default else []

    candidate_entity_types = [normalized_entity_type] + _get_legacy_item_policy_entity_types(normalized_entity_type)
    rows = []
    query = "SELECT * FROM c WHERE c.entity_type = @entity_type AND c.item_id = @item_id"
    for candidate_entity_type in candidate_entity_types:
        parameters = [
            {"name": "@entity_type", "value": candidate_entity_type},
            {"name": "@item_id", "value": normalized_item_id},
        ]
        try:
            rows.extend(list(cosmos_governance_item_policies_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True,
            )))
        except Exception:
            pass

    try:
        legacy_policy = _read_stored_item_policy(normalized_entity_type, normalized_item_id)
        rows.append(legacy_policy)
    except Exception:
        pass

    for legacy_entity_type in _get_legacy_item_policy_entity_types(normalized_entity_type):
        try:
            rows.append(_read_stored_item_policy(legacy_entity_type, normalized_item_id))
        except Exception:
            pass

    normalized_rows_by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized_row = _normalize_item_policy_doc(row)
        row_key = (
            str(normalized_row.get("entity_type") or ""),
            str(normalized_row.get("item_id") or ""),
            str(normalized_row.get("policy_id") or ""),
        )
        normalized_rows_by_key[row_key] = normalized_row

    normalized_rows = list(normalized_rows_by_key.values())
    if not normalized_rows:
        return [_default_item_policy_doc(normalized_entity_type, normalized_item_id)] if include_default else []

    return sorted(normalized_rows, key=lambda item: (str(item.get("policy_name") or ""), str(item.get("policy_id") or "")))


def _read_item_policy(entity_type: str, item_id: str) -> Dict[str, Any]:
    return _read_item_policies(entity_type, item_id)[0]


def _read_stored_item_policy(entity_type: str, item_id: str) -> Dict[str, Any]:
    normalized_item_id = _normalize_item_policy_item_id(entity_type, item_id)
    policy_id = _legacy_item_policy_document_id(entity_type, normalized_item_id)
    return cosmos_governance_item_policies_container.read_item(item=policy_id, partition_key=policy_id)


def get_feature_policy(feature_key: str) -> Dict[str, Any]:
    normalized_feature_key = str(feature_key or "").strip()

    def load_policy() -> Dict[str, Any]:
        policy = dict(_read_feature_policy(normalized_feature_key))
        normalized = _normalize_policy_state(policy)
        policy.update(normalized)
        return policy

    return _get_cached_governance_value(("feature_policy", normalized_feature_key), load_policy)


def get_item_policy(entity_type: str, item_id: str) -> Dict[str, Any]:
    return get_item_policies(entity_type, item_id)[0]


def get_item_policies(entity_type: str, item_id: str) -> List[Dict[str, Any]]:
    normalized_entity_type = _normalize_item_policy_entity_type(entity_type)
    normalized_item_id = _normalize_item_policy_item_id(normalized_entity_type, item_id)

    def load_policies() -> List[Dict[str, Any]]:
        policies = []
        for policy in _read_item_policies(normalized_entity_type, normalized_item_id):
            normalized_policy = dict(policy)
            normalized = _normalize_policy_state(normalized_policy)
            normalized_policy.update(normalized)
            policies.append(normalized_policy)
        return policies

    return _get_cached_governance_value(
        ("item_policies", normalized_entity_type, normalized_item_id),
        load_policies,
    )


def get_explicit_item_policies(entity_type: str, item_id: str) -> List[Dict[str, Any]]:
    normalized_entity_type = _normalize_item_policy_entity_type(entity_type)
    normalized_item_id = _normalize_item_policy_item_id(normalized_entity_type, item_id)

    def load_policies() -> List[Dict[str, Any]]:
        policies = []
        for policy in _read_item_policies(normalized_entity_type, normalized_item_id, include_default=False):
            normalized_policy = dict(policy)
            normalized = _normalize_policy_state(normalized_policy)
            normalized_policy.update(normalized)
            policies.append(normalized_policy)
        return policies

    return _get_cached_governance_value(
        ("explicit_item_policies", normalized_entity_type, normalized_item_id),
        load_policies,
    )


def _build_diff(before_doc: Dict[str, Any], after_doc: Dict[str, Any]) -> Dict[str, Any]:
    before_users = set(_normalize_str_list(before_doc.get("allowed_users", [])))
    after_users = set(_normalize_str_list(after_doc.get("allowed_users", [])))
    before_groups = set(_normalize_str_list(before_doc.get("allowed_groups", [])))
    after_groups = set(_normalize_str_list(after_doc.get("allowed_groups", [])))

    return {
        "allow_all": {
            "before": bool(before_doc.get("allow_all", True)),
            "after": bool(after_doc.get("allow_all", True)),
        },
        "users_added": sorted(list(after_users - before_users)),
        "users_removed": sorted(list(before_users - after_users)),
        "groups_added": sorted(list(after_groups - before_groups)),
        "groups_removed": sorted(list(before_groups - after_groups)),
    }


def upsert_feature_policy(
    feature_key: str,
    payload: Dict[str, Any],
    actor_user_id: str,
    actor_email: str,
) -> Dict[str, Any]:
    before_policy = _read_feature_policy(feature_key)
    policy_id = f"feature:{feature_key}"
    normalized_payload = _normalize_policy_state(payload)
    after_policy = {
        "id": policy_id,
        "feature_key": feature_key,
        "allow_all": normalized_payload["allow_all"],
        "allowed_users": normalized_payload["allowed_users"],
        "allowed_groups": normalized_payload["allowed_groups"],
        "updated_by": str(actor_user_id or "").strip(),
        "updated_at": datetime.utcnow().isoformat(),
    }

    stored = cosmos_governance_policies_container.upsert_item(body=after_policy)
    invalidate_governance_cache()

    log_governance_change(
        admin_user_id=str(actor_user_id or "").strip(),
        admin_email=str(actor_email or "").strip(),
        action="feature_policy_upsert",
        scope="feature",
        target_id=feature_key,
        before_state=before_policy,
        after_state=stored,
        change_details=_build_diff(before_policy, stored),
    )

    return stored


def upsert_item_policy(
    entity_type: str,
    item_id: str,
    payload: Dict[str, Any],
    actor_user_id: str,
    actor_email: str,
) -> Dict[str, Any]:
    normalized_entity_type = _normalize_item_policy_entity_type(entity_type)
    normalized_item_id = _normalize_item_policy_item_id(normalized_entity_type, item_id)
    incoming_policy_id = str((payload or {}).get("policy_id") or "").strip()
    normalized_policy_id = incoming_policy_id or str(uuid.uuid4())
    policy_id = _item_policy_document_id(normalized_entity_type, normalized_item_id, normalized_policy_id)
    before_policy = next(
        (
            policy for policy in _read_item_policies(normalized_entity_type, normalized_item_id)
            if str(policy.get("policy_id") or "") == normalized_policy_id
        ),
        _default_item_policy_doc(normalized_entity_type, normalized_item_id, normalized_policy_id),
    )
    normalized_payload = _normalize_policy_state(payload)
    normalized_resource_label = str((payload or {}).get("resource_label") or "").strip()
    normalized_policy_name = str((payload or {}).get("policy_name") or "").strip() or _default_item_policy_name(
        normalized_entity_type,
        normalized_item_id,
        normalized_resource_label,
    )

    after_policy = {
        "id": policy_id,
        "policy_id": normalized_policy_id,
        "policy_name": normalized_policy_name,
        "resource_label": normalized_resource_label,
        "entity_type": normalized_entity_type,
        "item_id": normalized_item_id,
        "allow_all": normalized_payload["allow_all"],
        "allowed_users": normalized_payload["allowed_users"],
        "allowed_groups": normalized_payload["allowed_groups"],
        "updated_by": str(actor_user_id or "").strip(),
        "updated_at": datetime.utcnow().isoformat(),
    }

    stored = cosmos_governance_item_policies_container.upsert_item(body=after_policy)
    legacy_current_policy_id = _legacy_item_policy_document_id(normalized_entity_type, normalized_item_id)
    if legacy_current_policy_id != policy_id:
        try:
            cosmos_governance_item_policies_container.delete_item(
                item=legacy_current_policy_id,
                partition_key=legacy_current_policy_id,
            )
        except Exception:
            pass

    for legacy_entity_type in _get_legacy_item_policy_entity_types(normalized_entity_type):
        legacy_policy_id = _legacy_item_policy_document_id(legacy_entity_type, normalized_item_id)
        try:
            cosmos_governance_item_policies_container.delete_item(
                item=legacy_policy_id,
                partition_key=legacy_policy_id,
            )
        except Exception:
            pass

    invalidate_governance_cache()

    log_governance_change(
        admin_user_id=str(actor_user_id or "").strip(),
        admin_email=str(actor_email or "").strip(),
        action="item_policy_upsert",
        scope=normalized_entity_type,
        target_id=normalized_item_id,
        before_state=before_policy,
        after_state=stored,
        change_details=_build_diff(before_policy, stored),
    )

    return stored


def _read_existing_item_policy_for_delete(entity_type: str, item_id: str, policy_id: Optional[str] = None) -> Tuple[Dict[str, Any], str, str]:
    normalized_entity_type = _normalize_item_policy_entity_type(entity_type)
    normalized_item_id = str(item_id or "").strip()
    normalized_policy_id = str(policy_id or "").strip()
    candidate_entity_types = [normalized_entity_type] + _get_legacy_item_policy_entity_types(normalized_entity_type)

    if normalized_policy_id:
        for candidate_entity_type in candidate_entity_types:
            document_id = _item_policy_document_id(candidate_entity_type, normalized_item_id, normalized_policy_id)
            try:
                return cosmos_governance_item_policies_container.read_item(item=document_id, partition_key=document_id), candidate_entity_type, document_id
            except Exception:
                pass

    if normalized_policy_id in ("", "default"):
        for candidate_entity_type in candidate_entity_types:
            legacy_document_id = _legacy_item_policy_document_id(candidate_entity_type, normalized_item_id)
            try:
                return cosmos_governance_item_policies_container.read_item(item=legacy_document_id, partition_key=legacy_document_id), candidate_entity_type, legacy_document_id
            except Exception:
                pass

    last_exception = None
    for candidate_entity_type in candidate_entity_types:
        try:
            policies = _read_item_policies(candidate_entity_type, normalized_item_id)
            if policies:
                policy = policies[0]
                document_id = str(policy.get("id") or _item_policy_document_id(candidate_entity_type, normalized_item_id, policy.get("policy_id") or "default"))
                return policy, candidate_entity_type, document_id
        except Exception as ex:
            last_exception = ex

    if last_exception:
        raise last_exception
    raise ValueError("Item governance policy not found.")


def delete_item_policy(
    entity_type: str,
    item_id: str,
    actor_user_id: str,
    actor_email: str,
    policy_id: Optional[str] = None,
) -> Dict[str, Any]:
    normalized_entity_type = _normalize_item_policy_entity_type(entity_type)
    normalized_item_id = str(item_id or "").strip()
    stored_policy, stored_entity_type, document_id = _read_existing_item_policy_for_delete(normalized_entity_type, normalized_item_id, policy_id)
    before_policy = _normalize_item_policy_doc(stored_policy)

    cosmos_governance_item_policies_container.delete_item(
        item=document_id,
        partition_key=document_id,
    )
    invalidate_governance_cache()

    after_policy = _default_item_policy_doc(normalized_entity_type, normalized_item_id, before_policy.get("policy_id") or "default")
    log_governance_change(
        admin_user_id=str(actor_user_id or "").strip(),
        admin_email=str(actor_email or "").strip(),
        action="item_policy_delete",
        scope=normalized_entity_type,
        target_id=normalized_item_id,
        before_state=before_policy,
        after_state=after_policy,
        change_details=_build_diff(before_policy, after_policy),
    )

    return before_policy


def list_feature_policies() -> List[Dict[str, Any]]:
    query = "SELECT * FROM c"
    rows = list(cosmos_governance_policies_container.query_items(query=query, enable_cross_partition_query=True))

    rows_by_feature_key = {
        str(row.get("feature_key") or "").strip(): row
        for row in rows
        if isinstance(row, dict) and str(row.get("feature_key") or "").strip()
    }

    normalized_rows = []
    seen_feature_keys = set()

    for feature_key in DEFAULT_FEATURE_POLICIES.keys():
        row = rows_by_feature_key.get(feature_key) or _default_feature_policy_doc(feature_key)
        normalized_row = dict(row)
        normalized_row["allowed_users"] = _normalize_str_list(normalized_row.get("allowed_users", []))
        normalized_row["allowed_groups"] = _normalize_str_list(normalized_row.get("allowed_groups", []))
        normalized_row["allow_all"] = bool(normalized_row.get("allow_all", True))
        normalized_rows.append(normalized_row)

        seen_feature_keys.add(feature_key)

    for row in rows:
        feature_key = str((row or {}).get("feature_key") or "").strip()
        if not feature_key or feature_key in seen_feature_keys:
            continue
        normalized_row = dict(row)
        normalized_row["allowed_users"] = _normalize_str_list(normalized_row.get("allowed_users", []))
        normalized_row["allowed_groups"] = _normalize_str_list(normalized_row.get("allowed_groups", []))
        normalized_row["allow_all"] = bool(normalized_row.get("allow_all", True))
        normalized_rows.append(normalized_row)
        seen_feature_keys.add(feature_key)

    return sorted(normalized_rows, key=lambda item: str(item.get("feature_key") or ""))


def list_item_policies(entity_type: Optional[str] = None) -> List[Dict[str, Any]]:
    query_entity_types = []
    if entity_type:
        normalized_entity_type = _normalize_item_policy_entity_type(entity_type)
        query_entity_types = [normalized_entity_type] + _get_legacy_item_policy_entity_types(normalized_entity_type)
        query = "SELECT * FROM c WHERE c.entity_type = @entity_type"
        rows = []
        for query_entity_type in query_entity_types:
            parameters = [{"name": "@entity_type", "value": query_entity_type}]
            rows.extend(
                list(
                    cosmos_governance_item_policies_container.query_items(
                        query=query,
                        parameters=parameters,
                        enable_cross_partition_query=True,
                    )
                )
            )
    else:
        query = "SELECT * FROM c"
        rows = list(
            cosmos_governance_item_policies_container.query_items(
                query=query,
                enable_cross_partition_query=True,
            )
        )

    normalized_rows_by_key = {}
    for row in rows:
        stored_entity_type = str((row or {}).get("entity_type") or "").strip().lower()
        normalized_row = _normalize_item_policy_doc(row)
        normalized_entity_type = str(normalized_row.get("entity_type") or "")
        normalized_item_id = str(normalized_row.get("item_id") or "")
        normalized_policy_id = str(normalized_row.get("policy_id") or "")
        row_key = (normalized_entity_type, normalized_item_id, normalized_policy_id)
        existing_row = normalized_rows_by_key.get(row_key)
        if not existing_row or stored_entity_type == normalized_entity_type:
            normalized_rows_by_key[row_key] = normalized_row

    normalized_rows = list(normalized_rows_by_key.values())
    return sorted(
        normalized_rows,
        key=lambda item: (
            str(item.get("entity_type") or ""),
            str(item.get("resource_label") or item.get("item_id") or ""),
            str(item.get("policy_name") or ""),
        ),
    )


def get_user_governance_group_ids(user_id: str) -> Set[str]:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return set()

    def load_group_ids() -> Set[str]:
        group_ids = set()

        try:
            user_groups = get_user_groups(normalized_user_id)
            group_ids.update(_extract_group_ids(user_groups))
        except Exception:
            pass

        try:
            user_workspaces = get_user_public_workspaces(normalized_user_id)
            group_ids.update(_extract_workspace_ids(user_workspaces))
        except Exception:
            pass

        return group_ids

    return _get_cached_governance_value(("user_governance_group_ids", normalized_user_id), load_group_ids)


def _passes_policy(policy: Dict[str, Any], user_id: str, group_ids: Set[str]) -> bool:
    if bool(policy.get("allow_all", True)):
        return True

    allowed_users = set(_normalize_str_list(policy.get("allowed_users", [])))
    allowed_groups = set(_normalize_str_list(policy.get("allowed_groups", [])))

    if not allowed_users and not allowed_groups:
        return False

    normalized_user_id = str(user_id or "").strip()
    if normalized_user_id and normalized_user_id in allowed_users:
        return True

    if group_ids.intersection(allowed_groups):
        return True

    return False


def ensure_governance_access(
    feature_key: str,
    user_id: str,
    item_entity_type: Optional[str] = None,
    item_id: Optional[str] = None,
) -> None:
    normalized_feature_key = str(feature_key or "").strip()
    normalized_user_id = str(user_id or "").strip()
    normalized_item_entity_type = _normalize_item_policy_entity_type(item_entity_type or "")
    normalized_item_id = str(item_id or "").strip()
    decision_key = (
        "governance_access_decision",
        normalized_feature_key,
        normalized_user_id,
        normalized_item_entity_type,
        normalized_item_id,
    )

    cached_decision = _get_request_cache_value(decision_key)
    if cached_decision is True:
        return

    settings = _get_request_cached_governance_value(("settings",), get_settings)
    if not bool((settings or {}).get(normalized_feature_key, False)):
        _set_request_cache_value(decision_key, True)
        return

    user_group_ids = get_user_governance_group_ids(normalized_user_id)

    feature_policy = get_feature_policy(normalized_feature_key)
    if not _passes_policy(feature_policy, normalized_user_id, user_group_ids):
        raise PermissionError(f"Governance policy blocks access for feature '{feature_key}'.")

    if normalized_item_entity_type and normalized_item_id:
        item_policies = get_item_policies(normalized_item_entity_type, normalized_item_id)
        if not any(_passes_policy(item_policy, normalized_user_id, user_group_ids) for item_policy in item_policies):
            raise PermissionError(
                f"Governance policy blocks access to {item_entity_type} '{item_id}'."
            )

    _set_request_cache_value(decision_key, True)


def is_governance_access_allowed(
    feature_key: str,
    user_id: str,
    item_entity_type: Optional[str] = None,
    item_id: Optional[str] = None,
) -> bool:
    try:
        ensure_governance_access(feature_key, user_id, item_entity_type, item_id)
        return True
    except PermissionError:
        return False


def _normalize_action_scope(scope: str) -> str:
    normalized_scope = str(scope or "").strip().lower()
    if normalized_scope == "user":
        return "personal"
    return normalized_scope


def normalize_governed_action_type(action_type: Any) -> str:
    normalized_type = str(action_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    return ACTION_TYPE_ALIASES.get(normalized_type, normalized_type)


def get_governed_action_type_label(action_type: Any) -> str:
    normalized_type = normalize_governed_action_type(action_type)
    if not normalized_type:
        return "Unknown Action Type"
    return ACTION_TYPE_LABELS.get(normalized_type, normalized_type.replace("_", " ").title())


def get_action_type_policy_entity_type(scope: str) -> str:
    normalized_scope = _normalize_action_scope(scope)
    return ACTION_TYPE_POLICY_ENTITY_TYPES.get(normalized_scope, "")


def get_action_type_feature_key(scope: str) -> str:
    normalized_scope = _normalize_action_scope(scope)
    return ACTION_TYPE_FEATURE_KEYS.get(normalized_scope, "")


def ensure_action_type_access(
    feature_key: str,
    user_id: str,
    action_type: Any,
    scope: str,
) -> None:
    normalized_feature_key = str(feature_key or "").strip()
    normalized_user_id = str(user_id or "").strip()
    normalized_scope = _normalize_action_scope(scope)
    normalized_action_type = normalize_governed_action_type(action_type)
    action_type_entity_type = get_action_type_policy_entity_type(normalized_scope)

    if not normalized_feature_key:
        raise ValueError("feature_key is required for action type governance.")
    if not normalized_action_type:
        raise PermissionError("Governance policy blocks access to an unknown action type.")
    if not action_type_entity_type:
        raise ValueError(f"Unsupported action type governance scope: {scope}")

    decision_key = (
        "action_type_access_decision",
        normalized_feature_key,
        normalized_user_id,
        normalized_scope,
        normalized_action_type,
    )
    cached_decision = _get_request_cache_value(decision_key)
    if cached_decision is True:
        return

    settings = _get_request_cached_governance_value(("settings",), get_settings)
    if not bool((settings or {}).get(normalized_feature_key, False)):
        _set_request_cache_value(decision_key, True)
        return

    user_group_ids = get_user_governance_group_ids(normalized_user_id)
    feature_policy = get_feature_policy(normalized_feature_key)
    if _passes_policy(feature_policy, normalized_user_id, user_group_ids):
        _set_request_cache_value(decision_key, True)
        return

    action_type_policies = get_explicit_item_policies(action_type_entity_type, normalized_action_type)
    if any(_passes_policy(policy, normalized_user_id, user_group_ids) for policy in action_type_policies):
        _set_request_cache_value(decision_key, True)
        return

    action_type_label = get_governed_action_type_label(normalized_action_type)
    raise PermissionError(
        f"Governance policy blocks access to {normalized_scope} action type '{action_type_label}'."
    )


def is_action_type_access_allowed(feature_key: str, user_id: str, action_type: Any, scope: str) -> bool:
    try:
        ensure_action_type_access(feature_key, user_id, action_type, scope)
        return True
    except PermissionError:
        return False


def filter_actions_by_action_type_access(
    user_id: str,
    actions: Any,
    feature_key: str,
    scope: str,
) -> List[Dict[str, Any]]:
    governed_actions = []
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        if is_action_type_access_allowed(feature_key, user_id, action.get("type"), scope):
            governed_actions.append(action)
    return governed_actions


def is_action_scope_access_allowed(feature_key: str, user_id: str, scope: str) -> bool:
    normalized_feature_key = str(feature_key or "").strip()
    normalized_user_id = str(user_id or "").strip()
    normalized_scope = _normalize_action_scope(scope)
    action_type_entity_type = get_action_type_policy_entity_type(normalized_scope)
    if not normalized_feature_key or not action_type_entity_type:
        return False

    settings = _get_request_cached_governance_value(("settings",), get_settings)
    if not bool((settings or {}).get(normalized_feature_key, False)):
        return True

    user_group_ids = get_user_governance_group_ids(normalized_user_id)
    feature_policy = get_feature_policy(normalized_feature_key)
    if _passes_policy(feature_policy, normalized_user_id, user_group_ids):
        return True

    return any(
        _passes_policy(policy, normalized_user_id, user_group_ids)
        for policy in list_item_policies(entity_type=action_type_entity_type)
    )


def ensure_global_action_access(user_id: str, action: Dict[str, Any]) -> None:
    if not isinstance(action, dict):
        raise PermissionError("Governance policy blocks access to this global action.")

    if not bool(action.get("is_enabled", True)):
        raise PermissionError("This global action is disabled.")

    normalized_user_id = str(user_id or "").strip()
    ensure_action_type_access(
        "governance_global_actions_usage",
        normalized_user_id,
        action.get("type"),
        "global",
    )

    settings = _get_request_cached_governance_value(("settings",), get_settings)
    if not bool((settings or {}).get("governance_global_actions_usage", False)):
        return

    action_id = str(action.get("id") or action.get("name") or "").strip()
    if not action_id:
        raise PermissionError("Governance policy blocks access to this global action.")

    user_group_ids = get_user_governance_group_ids(normalized_user_id)
    item_policies = get_item_policies("global_action", action_id)
    if not any(_passes_policy(policy, normalized_user_id, user_group_ids) for policy in item_policies):
        raise PermissionError(f"Governance policy blocks access to global action '{action_id}'.")


def is_global_action_access_allowed(user_id: str, action: Dict[str, Any]) -> bool:
    try:
        ensure_global_action_access(user_id, action)
        return True
    except PermissionError:
        return False


def filter_governed_global_actions_for_user(user_id: str, actions: Any) -> List[Dict[str, Any]]:
    return [
        action
        for action in actions or []
        if isinstance(action, dict) and is_global_action_access_allowed(user_id, action)
    ]


def filter_governed_model_endpoints(
    user_id: str,
    endpoints: Any,
    feature_key: str,
) -> List[Dict[str, Any]]:
    if not is_governance_access_allowed(feature_key, user_id):
        return []

    governed_endpoints = []
    for endpoint in endpoints or []:
        if not isinstance(endpoint, dict):
            continue

        endpoint_id = str(endpoint.get("id") or "").strip()
        if endpoint_id and not is_governance_access_allowed(
            feature_key,
            user_id,
            item_entity_type="global_endpoint",
            item_id=endpoint_id,
        ):
            continue

        governed_endpoints.append(endpoint)

    return governed_endpoints


def bootstrap_default_feature_policies() -> None:
    created_defaults = False
    for feature_key in DEFAULT_FEATURE_POLICIES.keys():
        try:
            _read_stored_feature_policy(feature_key)
            continue
        except Exception:
            pass

        default_policy = _default_feature_policy_doc(feature_key)
        cosmos_governance_policies_container.upsert_item(body=default_policy)
        created_defaults = True

    if created_defaults:
        invalidate_governance_cache()
