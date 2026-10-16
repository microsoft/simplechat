# functions_workflow_editor.py
"""Non-secret editor choices and trusted loop-runner eligibility."""

import re
import uuid

from flask import has_request_context, session
from requests.exceptions import RequestException

from functions_ai_connections import supports_model_capability
from functions_appinsights import log_event
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


def workflow_assist_available(settings, *, user_roles=None, group_id=""):
    """Combine the existing assistant flag with this editor's existing scope policy."""
    # Settings owns bootstrap and is loaded only when authorized editor options are requested.
    from functions_settings import is_group_workflows_enabled_for_group, is_workflow_assistant_enabled_for_user

    if group_id:
        return settings.get('enable_workflow_ai_assistant') is True and is_group_workflows_enabled_for_group(
            settings, group_id,
        )
    return is_workflow_assistant_enabled_for_user(settings, user_roles=user_roles)


def workflow_result_recipient_choices(user_id, *, group_id="", instruction=""):
    """Project the existing collaborator/member lookup to canonical identities, without inviting."""
    # These owners initialize config; load them only at the authorized editor request boundary.
    from collaboration_models import normalize_collaboration_user
    from functions_group import assert_group_role, find_group_by_id
    from functions_settings import get_group_workflow_management_roles, get_settings, get_user_settings
    from functions_simplechat_operations import _group_member_summaries, search_directory_users

    if group_id:
        assert_group_role(user_id, group_id, allowed_roles=get_group_workflow_management_roles(get_settings()))
        candidates = _group_member_summaries(find_group_by_id(group_id))
    else:
        document = get_user_settings(user_id) or {}
        candidates = list((document.get('settings') or {}).get('recentCollaborators') or [])
        audience = re.search(
            r'\b(?:share\b.{0,80}?\bwith|send\b.{0,80}?\bto|deliver\b.{0,80}?\bto|invite)\s+([^.!?\n]+)',
            instruction, re.IGNORECASE,
        )
        queries = re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', instruction) if audience else []
        if audience:
            queries.extend(re.split(r'\s+and\s+|[,;]', audience.group(1), flags=re.IGNORECASE))
        for query in list(dict.fromkeys(query.strip().strip('"\'') for query in queries if query.strip()))[:5]:
            # The existing collaboration directory search returns all matches, not a guessed person.
            try:
                candidates.extend(search_directory_users(query[:100], limit=20))
            except (PermissionError, RequestException) as exc:
                log_event('[WORKFLOW_ASSIST] Recipient choices unavailable',
                          extra={'error_type': type(exc).__name__}, debug_only=True)
    choices = {}
    for candidate in candidates:
        normalized = normalize_collaboration_user(candidate)
        if not normalized:
            continue
        try:
            identity = str(uuid.UUID(normalized['user_id']))
        except (ValueError, TypeError, AttributeError):
            continue
        if identity == user_id:
            continue
        name = normalized.get('display_name') or normalized.get('email') or 'Member'
        email = normalized.get('email')
        label = f'{name} ({email})' if email and email != name else name
        choices.setdefault(identity, {'id': identity, 'label': str(label)[:250]})
    return list(choices.values())[:100]


def build_workflow_configuration_options(settings, *, user_id="", group_id="", user_roles=(),
                                         agents=(), recipient_choices=()):
    """Whitelist display-only registry metadata; never return a descriptor or raw settings."""
    # Registry/source owners can initialize cloud services, so resolve at the editor boundary.
    from functions_orchestration_registry import VISUAL_KINDS, get_capability, resolve_available_capabilities
    from functions_source_review import is_source_review_enabled_for_user, is_url_access_enabled_for_user
    from functions_workflow_configuration import WORKFLOW_CAPABILITY_IDS, new_workflow_configuration

    unavailable = {}
    descriptors = [get_capability(identity) for identity in WORKFLOW_CAPABILITY_IDS]
    available = {
        capability['id'] for capability in resolve_available_capabilities(
            settings, candidate_ids=[item['id'] for item in descriptors],
            unavailable=unavailable, include_runtime_bindings=False,
        )
    }
    if not is_url_access_enabled_for_user(settings, user_roles=user_roles):
        available.discard('url_fetch')
        unavailable['url_fetch'] = 'caller_access_required'
    if not is_source_review_enabled_for_user(settings, user_id, user_roles=user_roles):
        available.discard('deep_research')
        unavailable['deep_research'] = 'caller_access_required'
    if not agents:
        available.discard('agent_invoke')
        unavailable['agent_invoke'] = 'no_accessible_agents'
    enabled = settings.get('enable_chat_orchestration') is True
    sharing = settings.get('enable_collaborative_conversations') is True
    if not enabled:
        available.clear()
    defaults = new_workflow_configuration(
        settings=settings, workflow_scope='group' if group_id else 'personal',
    )
    def choice(identity, label, permitted, reason='feature_disabled'):
        return {'id': identity, 'label': label, 'available': permitted,
                **({'reason': reason} if not permitted else {})}

    visual_labels = {'chart': 'Chart', 'diagram': 'Diagram', 'image_proposal': 'Image proposal'}
    compose_available = 'compose' in available
    return {
        'chat_execution': {
            'modes': [
                choice('orchestration', 'Orchestration (automatic)', enabled),
                choice('selected', 'Selected capabilities', enabled),
                choice('off', 'Off', True),
            ],
            'capabilities': [
                choice(item['id'], item.get('label') or item['id'], item['id'] in available,
                       unavailable.get(item['id'], 'feature_disabled'))
                for item in descriptors
            ],
            'visual_requirements': [
                choice(identity, visual_labels[identity], compose_available) for identity in VISUAL_KINDS
            ],
            'default': defaults.get('chat_execution'),
        },
        'results_delivery': {
            'modes': [
                {'id': 'history', 'label': 'Run history only'},
                {'id': 'conversation', 'label': 'Create a results conversation'},
                {'id': 'task', 'label': 'Delivered by a task/agent'},
            ],
            'conversation_types': [
                item for item in (
                [{'id': 'group', 'label': 'Private group-scoped'}, {'id': 'group_shared', 'label': 'Shared group'}]
                if group_id else
                [{'id': 'personal', 'label': 'Personal'}, {'id': 'shared', 'label': 'Shared personal'}]
                ) if sharing or item['id'] not in ('shared', 'group_shared')
            ],
            'recipient_choices': list(recipient_choices) if sharing else [],
            'allow_all_group_members': bool(group_id and sharing),
            'default': defaults['results_delivery'],
        },
    }


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
    from functions_group import assert_group_role, get_user_groups
    from functions_public_workspaces import get_user_visible_public_workspace_docs
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
    options = build_workflow_editor_options(
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
    workspaces = [{'scope_type': 'personal', 'name': 'My workspace'}]
    if group_id:
        workspaces = [{'scope_type': 'group', 'scope_id': group_id, 'name': 'This group'}]
    else:
        if settings.get('enable_group_workspaces'):
            workspaces.extend({
                'scope_type': 'group', 'scope_id': str(group['id']), 'name': str(group.get('name') or 'Group'),
            } for group in get_user_groups(user_id))
        if settings.get('enable_public_workspaces'):
            workspaces.extend({
                'scope_type': 'public', 'scope_id': str(workspace['id']), 'name': str(workspace.get('name') or 'Public workspace'),
            } for workspace in get_user_visible_public_workspace_docs(user_id))
    options['document_workspaces'] = workspaces
    user_roles = (session.get('user') or {}).get('roles', []) if has_request_context() else []
    options.update(build_workflow_configuration_options(
        settings, user_id=user_id, group_id=group_id, user_roles=user_roles, agents=agents,
        recipient_choices=(
            workflow_result_recipient_choices(user_id, group_id=group_id)
            if can_manage and settings.get('enable_collaborative_conversations') is True else []
        ),
    ))
    options['workflow_assist_available'] = can_manage and workflow_assist_available(
        settings, user_roles=user_roles, group_id=group_id,
    )
    return options
