# functions_workflow_editor.py
"""Non-secret editor choices for the existing workflow APIs."""

from functions_ai_connections import supports_model_capability
from functions_workflow_definitions import WORKFLOW_DEFINITION_VERSION
from functions_workflow_flow import FLOW_LIMITS


def build_workflow_editor_options(*, scope_type, scope_id, can_manage, max_tasks,
                                  agents, endpoints, default_model=None):
    if scope_type not in {"personal", "group"}:
        raise ValueError("Unsupported workflow editor scope.")
    agent_options = [
        {
            "id": str(agent.get("id") or ""),
            "name": str(agent.get("name") or ""),
            "display_name": str(agent.get("display_name") or agent.get("name") or ""),
            "is_global": bool(agent.get("is_global")),
            "is_group": bool(agent.get("is_group")),
            "group_id": str(agent.get("group_id") or ""),
        }
        for agent in agents
        if agent.get("is_enabled", True) and agent.get("name") and agent.get("id")
    ]
    models = []
    seen_endpoints = set()
    for endpoint in endpoints:
        endpoint_id = str(endpoint.get("id") or "")
        if endpoint_id in seen_endpoints:
            continue
        seen_endpoints.add(endpoint_id)
        if not endpoint_id or endpoint.get("enabled") is False:
            continue
        provider = endpoint.get("provider") or "aoai"
        for model in endpoint.get("models") or []:
            if not model.get("id") or not supports_model_capability(model, provider=provider):
                continue
            models.append({
                "endpoint_id": endpoint_id,
                "model_id": str(model["id"]),
                "label": f"{endpoint.get('name') or endpoint_id} / {model.get('displayName') or model.get('modelName') or model['id']}",
                "provider": provider,
            })
    default_model = default_model or {}
    return {
        "definition_version": WORKFLOW_DEFINITION_VERSION,
        "supported_definition_versions": [1, 2, 3],
        "supported_node_kinds": ["task", "if", "route"],
        "flow_limits": dict(FLOW_LIMITS),
        "scope": {"type": scope_type, "id": str(scope_id)},
        "can_manage": bool(can_manage),
        "max_tasks": max_tasks,
        "agents": agent_options,
        "models": models,
        "default_model": {
            "label": str(default_model.get("label") or "Default app model"),
            "valid": bool(default_model.get("valid")),
        },
    }


def get_workflow_editor_options(user_id, settings, *, group_id=""):
    # Existing stores own agent/model eligibility and initialize app services.
    # Import them only at this already-authorized request boundary.
    from functions_group import assert_group_role
    from functions_group_workflows import (
        GROUP_WORKFLOW_MEMBER_ROLES,
        _build_model_endpoint_candidates as group_endpoints,
        get_group_workflow_agent_options,
    )
    from functions_personal_workflows import (
        _build_default_model_summary,
        _build_model_endpoint_candidates as personal_endpoints,
        _build_selectable_agents,
        get_workflow_max_tasks,
    )
    from functions_settings import get_group_workflow_management_roles

    if group_id:
        role = assert_group_role(user_id, group_id, allowed_roles=GROUP_WORKFLOW_MEMBER_ROLES)
        agents = (
            get_group_workflow_agent_options(group_id, settings=settings)
            if settings.get("enable_semantic_kernel") and settings.get("allow_group_agents") else []
        )
        endpoints = group_endpoints(group_id, settings)
        can_manage = role in get_group_workflow_management_roles(settings)
    else:
        agents = (
            _build_selectable_agents(user_id, settings)
            if settings.get("enable_semantic_kernel") and settings.get("allow_user_agents") else []
        )
        endpoints = personal_endpoints(user_id, settings)
        can_manage = True
    return build_workflow_editor_options(
        scope_type="group" if group_id else "personal", scope_id=group_id or user_id,
        can_manage=can_manage, max_tasks=get_workflow_max_tasks(settings),
        agents=agents, endpoints=endpoints, default_model=_build_default_model_summary(settings),
    )
