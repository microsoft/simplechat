# functions_agent_catalog.py
"""Build safe agent catalog records for chat selection and discovery."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from config import cosmos_activity_logs_container
from functions_appinsights import log_event
from functions_assigned_knowledge import get_agent_assigned_knowledge
from functions_global_actions import get_global_actions
from functions_global_agents import get_global_agents
from functions_group import get_group_model_endpoints, get_user_groups
from functions_group_actions import get_group_actions
from functions_group_agents import get_group_agents
from functions_governance import filter_actions_by_action_type_access, filter_governed_global_actions_for_user
from functions_keyvault import SecretReturnType
from functions_personal_actions import get_governed_personal_actions
from functions_personal_agents import ensure_migration_complete, get_personal_agents
from functions_settings import (
    get_settings,
    get_user_settings,
    normalize_agents_page_promoted_popular_agents,
    normalize_agents_page_promoted_popular_order,
    normalize_agents_page_promoted_popular_tag_enabled,
    normalize_agents_page_promoted_popular_tag_label,
    normalize_agents_page_promoted_popular_window,
    normalize_model_endpoints,
)


def build_agent_catalog_key(agent: Dict[str, Any]) -> str:
    """Return a stable key for matching catalog records and usage events."""
    if not isinstance(agent, dict):
        return ""

    scope_type = str(agent.get("scope_type") or "").strip().lower()
    if scope_type == "enterprise":
        scope_type = "global"
    if not scope_type:
        if agent.get("is_group"):
            scope_type = "group"
        elif agent.get("is_global"):
            scope_type = "global"
        else:
            scope_type = "personal"

    if scope_type == "group":
        scope_id = str(agent.get("group_id") or agent.get("scope_id") or "").strip()
    elif scope_type == "personal":
        scope_id = str(agent.get("user_id") or agent.get("scope_id") or "").strip()
    else:
        scope_id = "global"

    agent_id = str(agent.get("id") or agent.get("agent_id") or agent.get("name") or "").strip()
    if not agent_id:
        return ""
    return f"{scope_type}:{scope_id}:{agent_id}"


def _normalize_agent_tags(agent: Dict[str, Any]) -> List[str]:
    tags = agent.get("tags") if isinstance(agent, dict) else []
    if not isinstance(tags, list):
        return []

    cleaned = []
    seen = set()
    for tag in tags:
        if not isinstance(tag, str):
            continue
        normalized = tag.strip()
        if not normalized:
            continue
        tag_key = normalized.lower()
        if tag_key in seen:
            continue
        seen.add(tag_key)
        cleaned.append(normalized)
    return cleaned


def _normalize_agent_icon(agent: Dict[str, Any]) -> Dict[str, str]:
    icon = agent.get("icon") if isinstance(agent, dict) else {}
    if not isinstance(icon, dict):
        return {}
    kind = str(icon.get("kind") or "").strip().lower()
    value = str(icon.get("value") or "").strip()
    if kind not in {"bootstrap", "image"} or not value:
        return {}
    payload = {
        "kind": kind,
        "value": value,
    }
    if kind == "image" and icon.get("mime_type"):
        payload["mime_type"] = str(icon.get("mime_type") or "").strip()
    return payload


def _get_agent_model_label(agent: Dict[str, Any], model_labels: Optional[Dict[str, str]] = None) -> str:
    if not isinstance(agent, dict):
        return "Default"
    labels = model_labels or {}
    endpoint_id = str(agent.get("model_endpoint_id") or "").strip()
    model_id = str(agent.get("model_id") or "").strip()
    if endpoint_id and model_id:
        label = labels.get(f"{endpoint_id}:{model_id}")
        if label:
            return label
    if model_id and labels.get(model_id):
        return labels[model_id]

    raw_label = str(
        agent.get("model_id")
        or agent.get("azure_openai_gpt_deployment")
        or agent.get("azure_agent_apim_gpt_deployment")
        or "Default"
    ).strip() or "Default"
    return labels.get(raw_label, raw_label)


def _add_model_labels_from_endpoints(model_labels: Dict[str, str], endpoints: Any) -> None:
    normalized_endpoints, _ = normalize_model_endpoints(endpoints)
    for endpoint in normalized_endpoints:
        if not isinstance(endpoint, dict) or endpoint.get("enabled") is False:
            continue
        endpoint_id = str(endpoint.get("id") or "").strip()
        for model in endpoint.get("models") or []:
            if not isinstance(model, dict) or model.get("enabled") is False:
                continue
            model_id = str(
                model.get("id")
                or model.get("deploymentName")
                or model.get("deployment")
                or model.get("modelName")
                or model.get("name")
                or ""
            ).strip()
            deployment_name = str(model.get("deploymentName") or model.get("deployment") or "").strip()
            display_name = str(
                model.get("displayName")
                or model.get("modelName")
                or deployment_name
                or model.get("name")
                or model_id
                or ""
            ).strip()
            if not display_name:
                continue
            for key in (model_id, deployment_name, str(model.get("modelName") or "").strip()):
                if key:
                    model_labels.setdefault(key, display_name)
            if endpoint_id and model_id:
                model_labels.setdefault(f"{endpoint_id}:{model_id}", display_name)


def _build_model_label_map(
    user_id: str,
    settings: Dict[str, Any],
    user_groups: Iterable[Dict[str, Any]],
) -> Dict[str, str]:
    model_labels: Dict[str, str] = {}
    _add_model_labels_from_endpoints(model_labels, settings.get("model_endpoints", []) or [])
    if settings.get("allow_user_custom_endpoints", False):
        user_settings = get_user_settings(user_id).get("settings", {})
        _add_model_labels_from_endpoints(model_labels, user_settings.get("personal_model_endpoints", []) or [])
    if settings.get("enable_group_workspaces", False) and settings.get("allow_group_custom_endpoints", False):
        for group_doc in user_groups:
            group_id = group_doc.get("id")
            if group_id:
                _add_model_labels_from_endpoints(model_labels, get_group_model_endpoints(group_id))
    return model_labels


def _add_action_labels(action_labels: Dict[str, str], actions: Iterable[Dict[str, Any]]) -> None:
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        display_name = str(action.get("display_name") or action.get("displayName") or action.get("name") or "").strip()
        if not display_name:
            continue
        for key in (action.get("id"), action.get("name"), action.get("display_name"), action.get("displayName")):
            normalized_key = str(key or "").strip()
            if normalized_key:
                action_labels.setdefault(normalized_key, display_name)


def _build_action_label_map(
    user_id: str,
    settings: Dict[str, Any],
    user_groups: Iterable[Dict[str, Any]],
) -> Dict[str, str]:
    action_labels: Dict[str, str] = {}
    _add_action_labels(action_labels, filter_governed_global_actions_for_user(user_id, get_global_actions(return_type=SecretReturnType.NAME)))
    if settings.get("allow_user_plugins", False):
        try:
            _add_action_labels(action_labels, get_governed_personal_actions(user_id, return_type=SecretReturnType.NAME))
        except PermissionError:
            pass
    if settings.get("enable_group_workspaces", False) and settings.get("allow_group_plugins", False):
        for group_doc in user_groups:
            group_id = group_doc.get("id")
            if group_id:
                group_actions = get_group_actions(group_id, return_type=SecretReturnType.NAME)
                _add_action_labels(
                    action_labels,
                    filter_actions_by_action_type_access(user_id, group_actions, "governance_group_actions", "group"),
                )
    return action_labels


def _resolve_action_labels(action_ids: Iterable[str], action_labels: Optional[Dict[str, str]] = None) -> List[str]:
    labels = action_labels or {}
    resolved = []
    for action_id in action_ids or []:
        if not isinstance(action_id, str):
            continue
        normalized_id = action_id.strip()
        if not normalized_id:
            continue
        resolved.append(labels.get(normalized_id, normalized_id))
    return resolved


def _serialize_catalog_agent(
    agent: Dict[str, Any],
    *,
    scope_type: str,
    scope_id: Optional[str] = None,
    scope_name: Optional[str] = None,
    model_labels: Optional[Dict[str, str]] = None,
    action_labels: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    is_global = scope_type == "global"
    is_group = scope_type == "group"
    agent_scope = "group" if is_group else ("global" if is_global else "personal")
    group_id = scope_id if is_group else None

    actions_to_load = [item for item in agent.get("actions_to_load", []) if isinstance(item, str)]
    record = {
        "id": agent.get("id"),
        "name": agent.get("name", ""),
        "display_name": agent.get("display_name") or agent.get("displayName") or agent.get("name", ""),
        "description": agent.get("description", ""),
        "instructions": agent.get("instructions", ""),
        "agent_type": agent.get("agent_type", "local"),
        "is_global": is_global,
        "is_group": is_group,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "scope_name": scope_name,
        "group_id": group_id,
        "group_name": scope_name if is_group else None,
        "tags": _normalize_agent_tags(agent),
        "icon": _normalize_agent_icon(agent),
        "model_id": agent.get("model_id") or "",
        "model_endpoint_id": agent.get("model_endpoint_id") or "",
        "model_provider": agent.get("model_provider") or "",
        "model_label": _get_agent_model_label(agent, model_labels=model_labels),
        "actions_to_load": actions_to_load,
        "action_labels": _resolve_action_labels(actions_to_load, action_labels=action_labels),
        "assigned_knowledge": get_agent_assigned_knowledge(
            agent,
            agent_scope=agent_scope,
            group_id=group_id,
        ),
    }
    record["catalog_key"] = build_agent_catalog_key(record)
    return record


def _should_include_global_agents(settings: Dict[str, Any]) -> bool:
    return bool(settings.get("enable_semantic_kernel", False))


def build_accessible_agent_catalog(
    user_id: str,
    *,
    settings: Optional[Dict[str, Any]] = None,
    user_groups: Optional[Iterable[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Return safe catalog records for agents the user can select in chat."""
    resolved_settings = settings or get_settings()
    catalog: List[Dict[str, Any]] = []
    resolved_groups = list(user_groups) if user_groups is not None else get_user_groups(user_id)
    model_labels = _build_model_label_map(user_id, resolved_settings, resolved_groups)
    action_labels = _build_action_label_map(user_id, resolved_settings, resolved_groups)

    if resolved_settings.get("allow_user_agents", False):
        ensure_migration_complete(user_id)
        for agent in get_personal_agents(user_id):
            catalog.append(
                _serialize_catalog_agent(
                    agent,
                    scope_type="personal",
                    scope_id=user_id,
                    scope_name="Personal",
                    model_labels=model_labels,
                    action_labels=action_labels,
                )
            )

    if _should_include_global_agents(resolved_settings):
        for agent in get_global_agents():
            catalog.append(
                _serialize_catalog_agent(
                    agent,
                    scope_type="global",
                    scope_id=None,
                    scope_name="Global",
                    model_labels=model_labels,
                    action_labels=action_labels,
                )
            )

    if resolved_settings.get("enable_group_workspaces", False) and resolved_settings.get("allow_group_agents", False):
        for group_doc in resolved_groups:
            group_id = group_doc.get("id")
            if not group_id:
                continue
            group_name = group_doc.get("name", "Unnamed Group")
            for agent in get_group_agents(group_id):
                catalog.append(
                    _serialize_catalog_agent(
                        agent,
                        scope_type="group",
                        scope_id=group_id,
                        scope_name=group_name,
                        model_labels=model_labels,
                        action_labels=action_labels,
                    )
                )

    return catalog


def _resolve_usage_catalog_key(record: Dict[str, Any]) -> str:
    key = str(record.get("agent_catalog_key") or "").strip()
    if key:
        return key

    agent = record.get("agent") if isinstance(record.get("agent"), dict) else {}
    workspace_context = record.get("workspace_context") if isinstance(record.get("workspace_context"), dict) else {}
    return build_agent_catalog_key({
        "id": agent.get("id"),
        "name": agent.get("name"),
        "scope_type": record.get("workspace_type"),
        "scope_id": workspace_context.get("group_id") or record.get("user_id"),
        "group_id": workspace_context.get("group_id"),
        "user_id": record.get("user_id"),
    })


def _load_agent_usage_counts(
    catalog_keys: Iterable[str],
    *,
    since: Optional[str] = None,
) -> Dict[str, int]:
    resolved_keys = {key for key in catalog_keys if key}
    if not resolved_keys:
        return {}

    counts: Dict[str, int] = {}
    try:
        query = """
            SELECT c.agent_catalog_key, c.agent, c.workspace_type, c.workspace_context, c.user_id
            FROM c
            WHERE c.activity_type = 'agent_run'
        """
        parameters = []
        if since:
            query += " AND c.timestamp >= @since"
            parameters.append({"name": "@since", "value": since})

        records = cosmos_activity_logs_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True,
        )
        for record in records:
            key = _resolve_usage_catalog_key(record)
            if key in resolved_keys:
                counts[key] = counts.get(key, 0) + 1
    except Exception as exc:
        log_event(
            "[AgentCatalog] Failed to load agent usage counts.",
            extra={"error": str(exc), "since": since or "all_time"},
            level=logging.WARNING,
            exceptionTraceback=True,
        )

    return counts


def apply_agent_usage_counts(
    catalog: List[Dict[str, Any]],
    *,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """Attach all-time and recent usage counts to catalog records."""
    if not catalog:
        return catalog

    catalog_keys = {agent.get("catalog_key") for agent in catalog if agent.get("catalog_key")}
    if not catalog_keys:
        for agent in catalog:
            agent["usage_count_all_time"] = 0
            agent["usage_count_30_days"] = 0
            agent["usage_count"] = 0
        return catalog

    since = (datetime.utcnow() - timedelta(days=max(1, int(days or 30)))).isoformat()
    all_time_counts = _load_agent_usage_counts(catalog_keys)
    recent_counts = _load_agent_usage_counts(catalog_keys, since=since)

    for agent in catalog:
        catalog_key = agent.get("catalog_key")
        agent["usage_count_all_time"] = all_time_counts.get(catalog_key, 0)
        agent["usage_count_30_days"] = recent_counts.get(catalog_key, 0)
        agent["usage_count"] = agent["usage_count_30_days"]

    return catalog


def _get_usage_count(agent: Dict[str, Any], usage_field: str) -> int:
    try:
        return int(agent.get(usage_field) or agent.get("usage_count") or 0)
    except (TypeError, ValueError):
        return 0


def apply_agent_popular_promotions(
    catalog: List[Dict[str, Any]],
    *,
    settings: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Annotate accessible catalog records selected by admins for the Popular page."""
    if not catalog:
        return catalog

    resolved_settings = settings or get_settings()
    promotions = normalize_agents_page_promoted_popular_agents(
        (resolved_settings or {}).get("agents_page_promoted_popular_agents")
    )
    if not promotions:
        return catalog

    promotion_map = {
        promotion["catalog_key"]: (index, promotion)
        for index, promotion in enumerate(promotions)
        if promotion.get("catalog_key")
    }
    if not promotion_map:
        return catalog

    order_mode = normalize_agents_page_promoted_popular_order(
        (resolved_settings or {}).get("agents_page_promoted_popular_order")
    )
    tag_enabled = normalize_agents_page_promoted_popular_tag_enabled(
        (resolved_settings or {}).get("agents_page_promoted_popular_tag_enabled", True)
    )
    tag_label = normalize_agents_page_promoted_popular_tag_label(
        (resolved_settings or {}).get("agents_page_promoted_popular_tag_label")
    )

    for agent in catalog:
        catalog_key = str(agent.get("catalog_key") or "").strip()
        if catalog_key not in promotion_map:
            continue
        promotion_rank, promotion = promotion_map[catalog_key]
        agent["is_promoted_popular"] = True
        agent["promoted_popular_window"] = normalize_agents_page_promoted_popular_window(promotion.get("window"))
        agent["promoted_popular_rank"] = promotion_rank
        agent["promoted_popular_order"] = order_mode
        agent["promoted_popular_tag_enabled"] = tag_enabled
        agent["promoted_popular_tag_label"] = tag_label if tag_enabled else ""

    return catalog


def _is_promoted_popular_for_window(agent: Dict[str, Any], usage_window: str) -> bool:
    if not agent.get("is_promoted_popular"):
        return False
    promoted_window = normalize_agents_page_promoted_popular_window(agent.get("promoted_popular_window"))
    if promoted_window == "both":
        return True
    normalized_window = normalize_agents_page_promoted_popular_window(usage_window)
    return promoted_window == normalized_window


def _get_promoted_popular_rank(agent: Dict[str, Any]) -> int:
    try:
        return int(agent.get("promoted_popular_rank"))
    except (TypeError, ValueError):
        return 1000000


def _get_catalog_sort_name(agent: Dict[str, Any]) -> str:
    return str(agent.get("display_name") or agent.get("name") or "").lower()


def _dedupe_catalog_agents(agents: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped_agents = []
    seen_keys = set()
    for agent in agents:
        catalog_key = str(agent.get("catalog_key") or agent.get("id") or id(agent))
        if catalog_key in seen_keys:
            continue
        seen_keys.add(catalog_key)
        deduped_agents.append(agent)
    return deduped_agents


def get_popular_agents(
    catalog: List[Dict[str, Any]],
    limit: int = 3,
    usage_window: str = "30_days",
) -> List[Dict[str, Any]]:
    """Return the most-used catalog records plus admin-promoted Popular page agents."""
    normalized_window = str(usage_window or "30_days").strip().lower().replace("-", "_")
    usage_field = "usage_count_all_time" if normalized_window in {"all", "all_time"} else "usage_count_30_days"
    normalized_promotion_window = "all_time" if usage_field == "usage_count_all_time" else "30_days"
    promoted_agents = [
        agent for agent in catalog
        if _is_promoted_popular_for_window(agent, normalized_promotion_window)
    ]
    promoted_keys = {str(agent.get("catalog_key") or "") for agent in promoted_agents}
    ranked_agents = [
        agent for agent in catalog
        if _get_usage_count(agent, usage_field) > 0
        and str(agent.get("catalog_key") or "") not in promoted_keys
    ]
    ranked_agents.sort(
        key=lambda agent: (
            -_get_usage_count(agent, usage_field),
            _get_catalog_sort_name(agent),
        )
    )
    promoted_agents.sort(
        key=lambda agent: (
            _get_promoted_popular_rank(agent),
            _get_catalog_sort_name(agent),
        )
    )

    order_mode = "mixed"
    if promoted_agents:
        order_mode = normalize_agents_page_promoted_popular_order(
            promoted_agents[0].get("promoted_popular_order")
        )

    usage_limit = max(1, int(limit or 3))
    limited_ranked_agents = ranked_agents[:usage_limit]
    if order_mode == "before":
        return _dedupe_catalog_agents([*promoted_agents, *limited_ranked_agents])
    if order_mode == "after":
        return _dedupe_catalog_agents([*limited_ranked_agents, *promoted_agents])

    mixed_agents = _dedupe_catalog_agents([*limited_ranked_agents, *promoted_agents])
    mixed_agents.sort(
        key=lambda agent: (
            -_get_usage_count(agent, usage_field),
            _get_promoted_popular_rank(agent),
            _get_catalog_sort_name(agent),
        )
    )
    return mixed_agents