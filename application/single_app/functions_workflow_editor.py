# functions_workflow_editor.py
"""Non-secret editor choices and trusted loop-runner eligibility."""

from functions_ai_connections import supports_model_capability
from functions_generated_file_exports import GENERATED_RECORD_EXPORT_FORMATS
from functions_workflow_definitions import (
    WORKFLOW_DEFINITION_VERSION, WORKFLOW_INPUT_PROCESSING_MODES, WORKFLOW_PUBLICATION_COMPLETION_POLICIES,
)
from functions_workflow_flow import FLOW_LIMITS
from functions_workflow_limits import (
    WORKFLOW_LOOP_ITEMS_DEFAULT,
    WORKFLOW_MIN_SCHEDULE_INTERVAL_DEFAULT,
    WORKFLOW_REPEAT_ITERATIONS_DEFAULT,
    WORKFLOW_REPEAT_ITERATIONS_MAX,
    get_workflow_max_loop_items,
    get_workflow_max_repeat_iterations,
    get_workflow_min_schedule_interval_seconds,
    validate_workflow_max_loop_items,
    validate_workflow_max_repeat_iterations,
    validate_workflow_min_schedule_interval_seconds,
)
from functions_workflow_schedules import build_workflow_schedule_editor_options


def build_workflow_editor_options(*, scope_type, scope_id, can_manage, max_tasks,
                                  agents, endpoints, default_model=None,
                                  max_loop_items=WORKFLOW_LOOP_ITEMS_DEFAULT,
                                  max_repeat_iterations=WORKFLOW_REPEAT_ITERATIONS_DEFAULT,
                                  min_schedule_interval_seconds=WORKFLOW_MIN_SCHEDULE_INTERVAL_DEFAULT,
                                  merge=None):
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
            "loop_eligible": agent.get("agent_type") == "local",
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
                # Catalog models use the locally metered model path, not hosted-agent execution.
                "loop_eligible": True,
            })
    default_model = default_model or {}
    default_model_valid = bool(default_model.get("valid"))
    options = {
        "definition_version": WORKFLOW_DEFINITION_VERSION,
        "supported_definition_versions": [1, 2, 3],
        "supported_node_kinds": ["task", "if", "route", "for_each", "collect", "repeat_until"],
        "supported_iterable_kinds": ["input", "documents", "workspace_query"],
        "supported_query_modes": ["all_matches", "best_n"],
        "supported_binding_sources": ["node_output", "loop_item", "repeat_state"],
        "supported_input_processing_modes": sorted(WORKFLOW_INPUT_PROCESSING_MODES),
        "supported_publication_completion_policies": list(WORKFLOW_PUBLICATION_COMPLETION_POLICIES),
        "publication_source_capabilities": [
            {"source_kind": "native_analysis", "output_kinds": ["records", "json", "text", "document_results"],
             "artifact_formats": ["md", "csv", "json"]},
            {"source_kind": "saved_output", "output_kinds": ["records"],
             "artifact_formats": list(GENERATED_RECORD_EXPORT_FORMATS["exact_records_v1"])},
        ],
        "flow_limits": {
            **FLOW_LIMITS,
            "max_loop_items": validate_workflow_max_loop_items(max_loop_items),
            "max_repeat_iterations": validate_workflow_max_repeat_iterations(max_repeat_iterations),
            "hard_repeat_iterations": WORKFLOW_REPEAT_ITERATIONS_MAX,
        },
        "schedule": build_workflow_schedule_editor_options(
            min_interval_seconds=validate_workflow_min_schedule_interval_seconds(min_schedule_interval_seconds),
        ),
        "scope": {"type": scope_type, "id": str(scope_id)},
        "can_manage": bool(can_manage),
        "max_tasks": max_tasks,
        "agents": agent_options,
        "models": models,
        "default_model": {
            "label": str(default_model.get("label") or "Default app model"),
            "valid": default_model_valid,
            "loop_eligible": default_model_valid,
        },
    }
    if merge is not None:
        # Whether a task may merge files, and how many one run may merge, as the save will check.
        options["document_actions"] = {"merge": {
            "enabled": bool(merge.get("enabled")),
            "workflow_max_documents": int(merge["workflow_max_documents"]),
        }}
    return options


def get_workflow_editor_options(user_id, settings, *, group_id=""):
    # Existing stores own agent/model eligibility and initialize app services.
    # Import them only at this already-authorized request boundary.
    from functions_document_actions import (
        DOCUMENT_ACTION_CONTEXT_WORKFLOW,
        DOCUMENT_ACTION_TYPE_MERGE,
        get_document_action_max_documents,
        is_document_action_enabled,
    )
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
        max_loop_items=get_workflow_max_loop_items(settings),
        max_repeat_iterations=get_workflow_max_repeat_iterations(settings),
        min_schedule_interval_seconds=get_workflow_min_schedule_interval_seconds(settings),
        merge={
            "enabled": is_document_action_enabled(DOCUMENT_ACTION_TYPE_MERGE, settings=settings),
            "workflow_max_documents": get_document_action_max_documents(
                DOCUMENT_ACTION_TYPE_MERGE, DOCUMENT_ACTION_CONTEXT_WORKFLOW, settings=settings,
            ),
        },
    )
