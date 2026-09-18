# functions_m365_runtime.py
"""Web/workflow ownership layer for Microsoft 365 execution and disclosures."""

from contextlib import contextmanager, nullcontext
import hashlib
import json
import logging
from urllib.parse import urlencode
from uuid import uuid4

from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from azure.core import MatchConditions
from flask import g, has_request_context, request

from config import (
    TENANT_ID,
    cosmos_conversations_container,
    cosmos_m365_execution_runs_container,
)
from functions_appinsights import log_event
from functions_collaboration import (
    assert_user_can_participate_in_collaboration_conversation,
    build_conversation_participation_context,
    get_collaboration_conversation,
)
from functions_m365_approvals import (
    M365ApprovalRequired,
    M365PolicyError,
    get_m365_approval_service,
    material_fingerprint,
    strictest_sharing_policy,
)
from functions_m365_execution import (
    M365ExecutionContext,
    get_m365_execution_context,
    m365_execution_context,
    preflight_m365_manifests as execution_preflight_m365_manifests,
    prepare_m365_workflow_binding,
)
from functions_m365_operations import (
    M365_ACTION_DEFINITIONS,
    M365_LEGACY_OPERATION_SOURCES,
)
from functions_m365_connections import preflight_m365_chat_authentication
from functions_m365_workflow_binding import workflow_execution_fingerprint
from m365_interaction import M365_AUTH_INTERACTION_CODES


M365_RESUME_FIELDS = frozenset({
    "message", "content", "conversation_id", "hybrid_search", "web_search_enabled",
    "url_access_enabled", "source_review_enabled", "deep_research_enabled",
    "selected_document_id", "selected_document_ids", "doc_scope", "tags",
    "active_group_id", "active_group_ids", "active_public_workspace_id",
    "active_public_workspace_ids", "model_deployment", "model_id",
    "model_endpoint_id", "model_provider", "top_n", "classifications",
    "chat_type", "reasoning_effort", "reply_to_message_id", "mentioned_participants",
    "m365_collaboration_message_id",
    "selection_mode", "document_context_requested", "prompt_info",
    "conversation_task_document_ids", "image_generation",
})


def m365_resume_payload(payload):
    safe = {key: value for key, value in payload.items() if key in M365_RESUME_FIELDS}
    agent = payload.get("agent_info")
    if isinstance(agent, dict):
        safe["agent_info"] = {
            key: value for key, value in agent.items()
            if key in {"id", "name", "is_global", "is_group", "group_id"}
        }
    elif isinstance(agent, str):
        safe["agent_info"] = agent
    return safe


def install_m365_context(context):
    """Keep request context cleanup separate from the user's authentication state."""
    if has_request_context():
        g.m365_execution_context = context
    else:
        raise M365PolicyError(
            "m365_context_required",
            "The execution owner must enter a scoped Microsoft 365 context.",
        )
    return context


def _conversation_access(user_id, conversation_id):
    try:
        conversation = cosmos_conversations_container.read_item(
            item=conversation_id, partition_key=conversation_id,
        )
    except CosmosResourceNotFoundError:
        return None, None, None
    access = build_conversation_participation_context(user_id, conversation)
    shared_id = access.get("collaboration_conversation_id")
    shared = None
    if shared_id:
        shared = get_collaboration_conversation(shared_id)
        assert_user_can_participate_in_collaboration_conversation(user_id, shared)
    return conversation, access, shared


def _audience_version(conversation, shared):
    if shared:
        return material_fingerprint({
            "id": shared["id"],
            "scope": shared.get("scope"),
            "participants": shared.get("participants"),
            "status": shared.get("status"),
        })
    return material_fingerprint({
        "id": conversation.get("id"),
        "owner": conversation.get("user_id"),
    })


def workflow_destination_access(actor, workflow, conversation_id):
    """A workflow's output audience can be shared even when its backing chat is hidden."""
    from functions_group import assert_group_role, find_group_by_id
    group_id = workflow.get("group_id")
    if group_id:
        assert_group_role(actor, group_id, ("Owner", "Admin", "DocumentManager", "User"))
        run_as = workflow.get("m365_run_as_user_id")
        if run_as:
            assert_group_role(run_as, group_id, ("Owner", "Admin", "DocumentManager", "User"))
    elif actor != workflow["user_id"]:
        raise PermissionError("This personal workflow is not available to this user.")
    elif workflow.get("m365_run_as_user_id") not in (None, "", workflow["user_id"]):
        raise PermissionError("A personal workflow must use its owner's connected account.")
    if workflow.get("conversation_id") != conversation_id:
        raise PermissionError("This conversation is not the workflow's approved destination.")
    conversation, access, shared = _conversation_access(workflow["user_id"], conversation_id)
    if conversation is None:
        raise LookupError("The workflow conversation was not found.")
    if shared is None and group_id:
        group = find_group_by_id(group_id)
        if not group:
            raise LookupError("The workflow group was not found.")
        shared = {
            "id": f"workflow-{workflow['id']}",
            "scope": {"type": "group", "group_id": group_id},
            "participants": {
                key: group.get(key) for key in ("owner", "admins", "documentManagers", "users")
            },
            "status": group.get("status", "active"),
        }
    elif shared is None and workflow.get("m365_run_as_user_id") != workflow["user_id"]:
        shared = {
            "id": f"workflow-{workflow['id']}",
            "scope": {"type": "personal", "owner_id": workflow["user_id"]},
            "participants": [workflow["user_id"]],
            "status": "active",
        }
    return conversation, access, shared


def _request_fingerprint(payload, conversation_id):
    ignored = {
        "m365_request_id", "retry_user_message_id", "edited_user_message_id",
        "retry_thread_id", "retry_thread_attempt",
    }
    canonical = m365_resume_payload({
        key: value for key, value in payload.items() if key not in ignored
    })
    canonical["conversation_id"] = conversation_id
    return hashlib.sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


def read_pending_m365_chat_request(user_id, request_id, conversation_id):
    try:
        record = cosmos_m365_execution_runs_container.read_item(
            item=request_id, partition_key=user_id,
        )
    except CosmosResourceNotFoundError as error:
        raise LookupError("Pending Microsoft 365 request not found.") from error
    if (
        record.get("user_id") != user_id
        or record.get("actor_user_id") != user_id
        or record.get("conversation_id") != conversation_id
        or record.get("workflow_id")
        or record.get("status") not in {"awaiting_approval", "ready_to_resume"}
    ):
        raise PermissionError("The Microsoft 365 continuation is not available to this user.")
    return record


def initialize_m365_chat_context(user_id, conversation_id, *, allow_new=False):
    """Resolve shared audience from storage, never from request chat-type flags."""
    payload = request.get_json(silent=True) or {}
    conversation, _access, shared = _conversation_access(user_id, conversation_id)
    if conversation is None:
        if not allow_new:
            raise M365PolicyError("conversation_not_found", "Conversation not found.")
        conversation = {"id": conversation_id, "user_id": user_id}
    request_id = str(payload.get("m365_request_id") or "").strip()
    fingerprint = _request_fingerprint(payload, conversation_id)
    if request_id:
        job = read_pending_m365_chat_request(user_id, request_id, conversation_id)
        if (
            job.get("request_fingerprint") != fingerprint
            or job.get("conversation_id") != conversation_id
            or job.get("user_id") != user_id
            or job.get("status") not in {"awaiting_approval", "ready_to_resume"}
        ):
            raise M365PolicyError("m365_request_changed", "The pending request changed or has already completed.")
        claimed = {**job, "status": "running"}
        cosmos_m365_execution_runs_container.replace_item(
            job["id"], body=claimed,
            etag=job["_etag"], match_condition=MatchConditions.IfNotModified,
        )
        g.m365_has_pending_record = True
    else:
        request_id = uuid4().hex
    context = M365ExecutionContext(
        actor_user_id=user_id, data_user_id=user_id, tenant_id=TENANT_ID,
        conversation_id=conversation_id, shared=shared is not None,
        request_id=request_id, audience_version=_audience_version(conversation, shared),
    )
    g.m365_request_fingerprint = fingerprint
    return install_m365_context(context)


def _manifest_sources(manifest):
    definition = M365_ACTION_DEFINITIONS.get(manifest.get("type"))
    if definition:
        return {definition["source"]}
    if manifest.get("type") != "msgraph":
        return set()
    enabled = manifest.get("enabled_functions")
    if enabled is None:
        enabled = M365_LEGACY_OPERATION_SOURCES
    return {
        M365_LEGACY_OPERATION_SOURCES[name]
        for name in enabled if name in M365_LEGACY_OPERATION_SOURCES
    }


def preflight_m365_manifests(manifests):
    """Use the shared preflight for chat, loader, and workflow execution."""
    permitted = execution_preflight_m365_manifests(manifests)
    context = get_m365_execution_context()
    if context is not None and context.action_configs:
        ensure_m365_execution_record(context)
        preflight_m365_chat_authentication(permitted, context)
    return permitted


def ensure_m365_execution_record(context):
    from azure.cosmos.exceptions import CosmosResourceExistsError
    try:
        record = cosmos_m365_execution_runs_container.read_item(context.request_id, partition_key=context.data_user_id)
    except CosmosResourceNotFoundError:
        record = {
            "id": context.request_id, "user_id": context.data_user_id,
            "actor_user_id": context.actor_user_id, "type": "m365_execution_request",
            "status": "running", "conversation_id": context.conversation_id,
            "workflow_id": context.workflow_id, "run_id": context.run_id,
        }
        try:
            record = cosmos_m365_execution_runs_container.create_item(body=record)
        except CosmosResourceExistsError:
            record = cosmos_m365_execution_runs_container.read_item(context.request_id, partition_key=context.data_user_id)
    if record.get("conversation_id") != context.conversation_id or record.get("actor_user_id") != context.actor_user_id:
        raise PermissionError("Microsoft 365 request identity does not match its stored execution.")
    g.m365_has_pending_record = True
    return record


def attach_m365_message_provenance(message):
    context = get_m365_execution_context()
    if context is None or not context.action_configs:
        return message
    policies = {}
    for action in context.action_configs.values():
        sources = _manifest_sources(action) if action.get("type") else {action.get("source")}
        for source in sources:
            if source in {"calendar", "email", "onedrive", "spo"}:
                policies[source] = strictest_sharing_policy(
                    policies.get(source), action.get("maximum_sharing_acknowledgement"),
                )
    metadata = message.setdefault("metadata", {})
    metadata["m365_source_policies"] = policies
    metadata["m365_data_user_id"] = context.data_user_id
    metadata["m365_request_id"] = context.request_id
    metadata["m365_approval_ids"] = list(dict.fromkeys(
        grant["approval_id"] for grant in getattr(g, "m365_source_grants", {}).values()
        if grant.get("approval_id")
    ))
    return message


def resolve_m365_workflow_binding(context, manifests, policies):
    workflow = getattr(g, "m365_workflow", None) if has_request_context() else None
    if not workflow:
        raise M365PolicyError("m365_workflow_required", "The workflow execution context is unavailable.")
    all_manifests = getattr(g, "m365_workflow_manifests", manifests)
    instructions = "\n\n".join(
        str(task.get("instructions") or "") for task in workflow.get("tasks") or []
    ) or str(workflow.get("task_prompt") or "")
    agents = workflow.get("selected_agent") or []
    if isinstance(agents, list):
        instructions += "\n\n" + "\n\n".join(
            f"Agent {agent.get('name') or agent.get('id')}:\n{agent.get('instructions') or ''}"
            for agent in agents
        )
    review = {
        "instructions": instructions or "No instructions configured.",
        "capabilities": "\n".join(
            f"{item.get('displayName') or item.get('name')}: "
            + ", ".join(item.get("enabled_functions") or [])
            for item in all_manifests
        ),
        "runtime_inputs": json.dumps({
            key: workflow[key] for key in ("document_action", "file_sync", "context")
            if key in workflow
        }, ensure_ascii=False, sort_keys=True),
        "triggers": f"Manual runs and {workflow.get('trigger_type', 'manual')} triggers. "
        f"Schedule: {json.dumps(workflow.get('schedule') or {}, sort_keys=True)}",
        "destinations": f"Conversation {context.conversation_id}; "
        f"group {workflow.get('group_id') or 'none'}; owner {workflow['user_id']}. "
        "Published answers and retained evidence are available to the approved conversation audience.",
    }
    return prepare_m365_workflow_binding(
        context, workflow, all_manifests, review=review,
    )


def load_current_workflow(workflow):
    # Workflow stores depend on action modules, so resolve after runtime bootstrap.
    from functions_group_workflows import get_group_workflow
    from functions_personal_workflows import get_personal_workflow
    if workflow.get("group_id"):
        current = get_group_workflow(workflow["group_id"], workflow["id"])
    else:
        current = get_personal_workflow(workflow["user_id"], workflow["id"])
    if not current:
        raise M365PolicyError("m365_workflow_missing", "The workflow no longer exists.")
    return current


def workflow_m365_manifests(workflow):
    """Resolve all statically selected agent actions before a workflow can run."""
    from functions_global_actions import get_global_actions
    from functions_global_agents import get_global_agents
    from functions_group import assert_group_role
    from functions_group_actions import get_group_actions
    from functions_group_agents import get_group_agents
    from functions_keyvault import SecretReturnType
    from functions_personal_actions import get_personal_actions
    from functions_personal_agents import get_personal_agents
    from functions_msgraph_operations import get_msgraph_enabled_function_names, resolve_msgraph_action_capabilities
    from functions_m365_operations import get_m365_enabled_function_names
    from functions_settings import get_settings

    tasks = workflow.get("tasks") or []
    selections = []
    if not tasks:
        selections.append(workflow.get("selected_agent") or {})
    for task in tasks:
        runner = task.get("runner") or {}
        mode = runner.get("type") or "inherit"
        if mode == "inherit":
            selections.append(workflow.get("selected_agent") or {})
        elif mode == "agent":
            selections.append(runner.get("selected_agent") or {})
    if not any(isinstance(item, dict) and (item.get("id") or item.get("name")) for item in selections):
        return [], dict(workflow)
    owner_id = workflow["user_id"]
    group_id = workflow.get("group_id")
    settings = get_settings()
    agents = [{**agent, "_m365_scope": "global"} for agent in get_global_agents()]
    global_actions = get_global_actions(return_type=SecretReturnType.NAME)
    if group_id:
        assert_group_role(owner_id, group_id, ("Owner", "Admin", "DocumentManager", "User"))
        agents += [{**agent, "_m365_scope": "group"} for agent in get_group_agents(group_id)]
        local_actions = get_group_actions(group_id, return_type=SecretReturnType.NAME)
    else:
        agents += [{**agent, "_m365_scope": "personal"} for agent in get_personal_agents(owner_id)]
        local_actions = get_personal_actions(owner_id, return_type=SecretReturnType.NAME)
    selected_agents = []
    for selection in selections:
        if not isinstance(selection, dict) or not (selection.get("id") or selection.get("name")):
            continue
        scope = "global" if selection.get("is_global") else "group" if group_id else "personal"
        matches = [
            agent for agent in agents
            if agent["_m365_scope"] == scope and (
                str(agent.get("id") or "") == str(selection["id"])
                if selection.get("id") else agent.get("name") == selection.get("name")
            )
        ]
        if len(matches) != 1:
            raise M365PolicyError("m365_agent_unavailable", "The workflow agent is unavailable or ambiguous.")
        if matches[0] not in selected_agents:
            selected_agents.append(matches[0])
    selected_actions_by_id = {}
    for agent in selected_agents:
        requested = set()
        for reference in agent.get("actions_to_load") or []:
            if isinstance(reference, str):
                requested.add(reference)
            elif isinstance(reference, dict):
                requested.update(filter(None, (reference.get("id"), reference.get("name"))))
        actions = global_actions if agent["_m365_scope"] == "global" else [
            *local_actions,
            *(global_actions if settings.get("merge_global_semantic_kernel_with_workspace") else []),
        ]
        overrides = (agent.get("other_settings") or {}).get("action_capabilities") or {}
        for action in actions:
            if action.get("id") not in requested and action.get("name") not in requested:
                continue
            action_type = action.get("type")
            if action_type != "msgraph" and action_type not in M365_ACTION_DEFINITIONS:
                continue
            normalized = dict(action)
            fields = action.get("additionalFields") or {}
            override = overrides.get(action.get("id"), overrides.get(action.get("name")))
            if action_type == "msgraph":
                defaults = fields.get("msgraph_capabilities", action.get("msgraph_capabilities"))
                saved_functions = set(get_msgraph_enabled_function_names(defaults))
                if action.get("msgraph_capabilities") is not None:
                    saved_functions.intersection_update(get_msgraph_enabled_function_names(action["msgraph_capabilities"]))
                if action.get("enabled_functions") is not None:
                    saved_functions.intersection_update(action["enabled_functions"])
                capabilities = resolve_msgraph_action_capabilities(
                    overrides, action_defaults=defaults,
                    action_id=action.get("id"), action_name=action.get("name"),
                )
                enabled = sorted(saved_functions.intersection(get_msgraph_enabled_function_names(capabilities)))
            else:
                enabled = get_m365_enabled_function_names(action_type, action, agent_capabilities=override)
            action_id = str(action.get("id") or action.get("name"))
            previous = selected_actions_by_id.get(action_id)
            normalized["enabled_functions"] = sorted(set(enabled) | set((previous or {}).get("enabled_functions") or []))
            if normalized["enabled_functions"]:
                selected_actions_by_id[action_id] = normalized
    selected_actions = list(selected_actions_by_id.values())
    fingerprint_workflow = dict(workflow)
    fingerprint_workflow["selected_agent"] = [
        {
            "id": agent.get("id"), "name": agent.get("name"),
            "scope": agent["_m365_scope"],
            "instructions": agent.get("instructions"),
            "other_settings": agent.get("other_settings"),
            "actions_to_load": agent.get("actions_to_load"),
        } for agent in selected_agents
    ]
    return selected_actions, fingerprint_workflow


@contextmanager
def workflow_m365_context(workflow, run_id, conversation_id, *, actor_user_id=None):
    current = load_current_workflow(workflow)
    manifests, fingerprint_workflow = workflow_m365_manifests(current)
    if not manifests:
        yield None
        return
    run_as = str(current.get("m365_run_as_user_id") or "").strip()
    if not run_as:
        raise M365PolicyError(
            "m365_run_as_required",
            "Select a Microsoft 365 Run as account on this workflow.",
        )
    actor = str(actor_user_id or current["user_id"])
    conversation, _access, shared = workflow_destination_access(actor, current, conversation_id)
    if conversation is None:
        raise M365PolicyError("conversation_not_found", "The workflow conversation was not found.")
    previous_state = {
        name: value for name, value in vars(g).items() if name.startswith("m365_")
    }
    for name in list(previous_state):
        delattr(g, name)
    g.m365_workflow = fingerprint_workflow
    g.m365_workflow_manifests = manifests
    try:
        context = M365ExecutionContext(
            actor_user_id=actor, data_user_id=run_as, tenant_id=TENANT_ID,
            conversation_id=conversation_id, shared=shared is not None,
            request_id=run_id, workflow_id=current["id"], run_id=run_id,
            audience_version=_audience_version(conversation, shared),
            group_id=current.get("group_id"),
        )
        install_m365_context(context)
        preflight_m365_manifests(manifests)
        from functions_m365_file_runtime import resolve_m365_budget_run
        resolve_m365_budget_run(get_m365_execution_context())
        yield get_m365_execution_context()
    except M365ApprovalRequired as error:
        record_m365_pending(error)
        raise
    except M365PolicyError as error:
        if error.code in M365_AUTH_INTERACTION_CODES:
            record_m365_auth_wait(error)
        raise
    finally:
        for name in list(vars(g)):
            if name.startswith("m365_"):
                delattr(g, name)
        for name, value in previous_state.items():
            setattr(g, name, value)


def validate_m365_workflow_execution(context):
    from functions_settings import get_settings, is_group_workflows_enabled_for_group

    workflow = getattr(g, "m365_workflow", None)
    if not workflow or workflow.get("id") != context.workflow_id:
        return False
    current = load_current_workflow(workflow)
    settings = get_settings()
    if current.get("group_id"):
        if not is_group_workflows_enabled_for_group(settings, current["group_id"]):
            return False
    elif not settings.get("allow_user_workflows", False):
        return False
    conversation, _access, shared = workflow_destination_access(context.actor_user_id, current, context.conversation_id)
    manifests, fingerprint_workflow = workflow_m365_manifests(current)
    return (
        current.get("m365_run_as_user_id") == context.data_user_id
        and _audience_version(conversation, shared) == context.audience_version
        and workflow_execution_fingerprint(fingerprint_workflow, manifests)
        == context.workflow_fingerprint
    )


def configure_m365_pending_delivery_runtime(request_context_factory):
    """Bootstrap supplies a request-context factory, never another user's session."""
    from config import cosmos_msgraph_pending_actions_container
    from functions_m365_pending_delivery import configure_m365_pending_delivery
    from functions_notifications import create_notification

    def notify_delivery(action):
        context = action["m365_execution"]["context"]
        query = {
            "workflowId": action["workflow_id"], "runId": action["run_id"],
            "scope": "group" if context.get("group_id") else "personal",
        }
        if context.get("group_id"):
            query["groupId"] = context["group_id"]
        pending = action.get("status") == "pending"
        return create_notification(
            user_id=action["user_id"], notification_type="system_announcement",
            title="Microsoft 365 action awaiting review" if pending else "Microsoft 365 delivery needs attention",
            message=(
                "Review the outgoing mail or calendar action in workflow activity. Only the Run as user can send or cancel it."
                if pending else "Delivery did not complete. Review its status before starting a new action."
            ),
            link_url=f"/workflow-activity?{urlencode(query)}",
            metadata={"m365_pending_action_id": action["id"], "workflow_id": action["workflow_id"]},
        )

    @contextmanager
    def delivery_context(action):
        delivery = action["m365_execution"]
        context = M365ExecutionContext(**delivery["context"])
        with nullcontext() if has_request_context() else request_context_factory("/api/internal/m365-delivery"):
            previous = getattr(g, "m365_workflow", None)
            g.m365_workflow = load_current_workflow(delivery["workflow_ref"])
            try:
                with m365_execution_context(context):
                    if not validate_m365_workflow_execution(context):
                        raise M365PolicyError("m365_workflow_changed", "The workflow or destination changed after this delivery was prepared.")
                    request_record = cosmos_m365_execution_runs_container.read_item(
                        context.request_id, partition_key=context.data_user_id,
                    )
                    if request_record.get("status") in {"cancelled", "recovery_required", "failed"}:
                        raise M365PolicyError("m365_execution_stopped", "This workflow execution no longer permits delivery.")
                    yield context
            finally:
                if previous is None:
                    delattr(g, "m365_workflow")
                else:
                    g.m365_workflow = previous

    configure_m365_pending_delivery(
        container=cosmos_msgraph_pending_actions_container,
        context_scope=delivery_context, log_event=log_event, notification_sender=notify_delivery,
    )


def authorize_m365_conversation_audit(user_id, conversation_id):
    conversation, _access, _shared = _conversation_access(user_id, conversation_id)
    if conversation is not None:
        return True
    shared = get_collaboration_conversation(conversation_id)
    assert_user_can_participate_in_collaboration_conversation(user_id, shared)
    return True


def resolve_m365_audit_conversation_id(user_id, conversation_id):
    conversation, _access, _shared = _conversation_access(user_id, conversation_id)
    if conversation is not None:
        return conversation_id
    shared = get_collaboration_conversation(conversation_id)
    assert_user_can_participate_in_collaboration_conversation(user_id, shared)
    return shared.get("source_conversation_id") or shared.get("legacy_source_conversation_id") or conversation_id


def resolve_m365_selected_manifests(context):
    """Reload the request's canonical agent selection, including current overlays."""
    if context.workflow_id:
        workflow = getattr(g, "m365_workflow", None) if has_request_context() else None
        if not workflow or workflow.get("id") != context.workflow_id:
            raise M365PolicyError("m365_workflow_required", "The current workflow selection is unavailable.")
        current = load_current_workflow(workflow)
        manifests, _ = workflow_m365_manifests(current)
        return manifests
    selection = getattr(g, "m365_selected_agent_ref", None) if has_request_context() else None
    if not selection:
        return []
    manifests, _ = workflow_m365_manifests({
        "user_id": context.actor_user_id,
        "group_id": selection.get("group_id") if selection.get("is_group") else None,
        "selected_agent": selection,
        "tasks": [],
    })
    return manifests


def resolve_m365_action_selection(context):
    return [str(item.get("id") or item.get("name")) for item in resolve_m365_selected_manifests(context)]


def resolve_m365_action_config(context, action_id, source):
    """Resolve current saved policy for a request using a preloaded global kernel."""
    from functions_global_actions import get_global_actions
    from functions_governance import (
        filter_actions_by_action_type_access,
        filter_governed_global_actions_for_user,
    )
    from functions_group import get_user_groups
    from functions_group_actions import get_governed_group_actions
    from functions_personal_actions import get_personal_actions
    from functions_keyvault import SecretReturnType

    user_id = context.actor_user_id
    actions = filter_actions_by_action_type_access(
        user_id, get_personal_actions(user_id, return_type=SecretReturnType.NAME),
        "governance_user_actions", "personal",
    )
    actions += filter_governed_global_actions_for_user(
        user_id, get_global_actions(return_type=SecretReturnType.NAME),
    )
    for group in get_user_groups(user_id):
        actions += get_governed_group_actions(
            group["id"], user_id, return_type=SecretReturnType.NAME,
        )
    candidates = [
        action for action in actions
        if str(action.get("id") or action.get("name")) == action_id
        and (source in _manifest_sources(action) or (source is None and action.get("type") == "msgraph"))
    ]
    if len(candidates) != 1:
        raise M365PolicyError(
            "m365_action_not_authorized",
            "The Microsoft 365 action is unavailable in the current user context.",
        )
    action = candidates[0]
    selected = [
        item for item in resolve_m365_selected_manifests(context)
        if str(item.get("id") or item.get("name")) == action_id and item.get("type") == action.get("type")
    ]
    if len(selected) != 1:
        raise M365PolicyError("m365_action_not_selected", "This action is no longer selected by the current agent.")
    ensure_m365_execution_record(context)
    return {
        **action,
        "enabled_functions": selected[0]["enabled_functions"],
        "source": source,
        "maximum_sharing_acknowledgement": (
            action.get("additionalFields") or {}
        ).get("maximum_sharing_acknowledgement", "always"),
    }


def validate_m365_approval_decision(approval):
    """Revalidate stored publication/run-as targets before a user's decision."""
    snapshot = approval.get("context") or {}
    actor = snapshot.get("actor_user_id")
    conversation_id = snapshot.get("conversation_id")
    if str(snapshot.get("request_id") or "").startswith("m365-share-"):
        from functions_m365_history import validate_m365_history_decision
        return validate_m365_history_decision(approval)
    if conversation_id and not snapshot.get("workflow_id"):
        conversation, _access, shared = _conversation_access(actor, conversation_id)
        if conversation is None or _audience_version(conversation, shared) != snapshot.get("audience_version"):
            return False
    if snapshot.get("workflow_id"):
        try:
            pending = cosmos_m365_execution_runs_container.read_item(
                item=snapshot["request_id"], partition_key=approval["subject_user_id"],
            )
        except CosmosResourceNotFoundError:
            return False
        reference = pending.get("workflow_ref") or {}
        if reference.get("id") != snapshot["workflow_id"]:
            return False
        current = load_current_workflow(reference)
        if current.get("active_run_id") != snapshot.get("run_id") or current.get("status") in {"idle", "cancelling", "cancelled"}:
            return False
        conversation, _access, shared = workflow_destination_access(
            actor, current, conversation_id,
        )
        if _audience_version(conversation, shared) != snapshot.get("audience_version"):
            return False
        manifests, fingerprint_workflow = workflow_m365_manifests(current)
        if (
            current.get("m365_run_as_user_id") != approval["subject_user_id"]
            or workflow_execution_fingerprint(fingerprint_workflow, manifests)
            != snapshot.get("workflow_fingerprint")
        ):
            return False
    return True


def record_m365_auth_wait(error, *, user_message_id=None):
    from functions_notifications import create_notification
    context = get_m365_execution_context()
    if context is None:
        raise error
    try:
        prior = cosmos_m365_execution_runs_container.read_item(context.request_id, partition_key=context.data_user_id)
    except CosmosResourceNotFoundError:
        prior = {}
    workflow = getattr(g, "m365_workflow", None) or {}
    record = {
        **prior, "id": context.request_id, "user_id": context.data_user_id,
        "actor_user_id": context.actor_user_id, "type": "m365_execution_request",
        "status": "awaiting_sign_in", "conversation_id": context.conversation_id,
        "workflow_id": context.workflow_id, "run_id": context.run_id,
        "workflow_ref": {key: workflow[key] for key in ("id", "user_id", "group_id") if key in workflow},
        "authentication_error": error.code,
        "required_scopes": error.payload.get("scopes") or [],
        "user_message_id": user_message_id or prior.get("user_message_id"),
        "request_fingerprint": getattr(g, "m365_request_fingerprint", prior.get("request_fingerprint")),
        "payload": prior.get("payload") or m365_resume_payload(request.get_json(silent=True) or {}),
        "audience_version": context.audience_version,
    }
    _save_m365_wait_record(record, prior, context)
    if prior.get("status") != "awaiting_sign_in":
        create_notification(
            user_id=context.data_user_id, notification_type="system_announcement",
            title="Microsoft 365 sign-in required",
            message=(
                "Your Microsoft 365 workflow is paused. Review it in Approvals or reconnect its account in Profile."
                if context.workflow_id else
                "Your Microsoft 365 chat request is paused. Connect in the conversation or Approvals, then resume it."
            ),
            link_url="/approvals",
            metadata={"m365_request_id": context.request_id, "workflow_id": context.workflow_id},
        )
    g.m365_approval_pending = True
    return {
        **error.payload, "type": "m365_sign_in_required",
        "error": error.payload["message"], "m365_request_id": context.request_id,
        "conversation_id": context.conversation_id, "user_message_id": user_message_id,
        "message_persisted": bool(user_message_id), "done": True,
    }


def configure_m365_history_runtime():
    """Supply live ownership/storage callbacks without a collaboration import cycle."""
    from config import cosmos_group_conversations_container, cosmos_group_messages_container, cosmos_messages_container
    from conversation_memory_runtime import get_chat_memory_blob_client
    from functions_conversation_memory import ConversationMemoryStore, MemoryContext
    from functions_group import assert_group_role, find_group_by_id
    from functions_m365_history import M365HistoryService, configure_m365_history

    def read_conversation(scope, conversation_id):
        container = cosmos_group_conversations_container if scope == "group" else cosmos_conversations_container
        return container.read_item(item=conversation_id, partition_key=conversation_id)

    def read_messages(scope, conversation_id):
        container = cosmos_group_messages_container if scope == "group" else cosmos_messages_container
        return container.query_items(
            query="SELECT * FROM c WHERE c.conversation_id = @id ORDER BY c.timestamp ASC",
            parameters=[{"name": "@id", "value": conversation_id}],
            partition_key=conversation_id,
        )

    def memory_resolver(user_id, conversation, scope):
        context = MemoryContext(
            tenant_id=TENANT_ID, principal_id=user_id,
            conversation_id=conversation["id"], storage_owner=conversation["user_id"],
            container="group-chat" if scope == "group" else "personal-chat",
        )

        def authorize(candidate, operation):
            latest = read_conversation(scope, conversation["id"])
            return candidate == context and latest.get("user_id") == user_id

        return ConversationMemoryStore(
            get_chat_memory_blob_client(), authorize_access=authorize, log_event=log_event,
        ), context

    def audience(user_id, conversation, scope, participants):
        group_id = conversation.get("group_id") or next((
            item.get("id") for item in conversation.get("context") or []
            if item.get("type") == "primary" and item.get("scope") == "group"
        ), None)
        group = None
        if group_id:
            assert_group_role(user_id, group_id, ("Owner", "Admin", "DocumentManager", "User"))
            group = find_group_by_id(group_id)
        participant_ids = sorted({
            str(item.get("user_id") or item.get("userId") or item.get("id") or "")
            for item in participants or []
        })
        return material_fingerprint({
            "owner": user_id, "participants": participant_ids, "group_id": group_id,
            "group_members": {
                key: group.get(key) for key in ("owner", "admins", "documentManagers", "users")
            } if group else None,
        })

    def has_active_request(conversation_id):
        return next(iter(cosmos_m365_execution_runs_container.query_items(
            query=(
                "SELECT TOP 1 c.id FROM c WHERE c.conversation_id = @id "
                "AND c.type = 'm365_execution_request' "
                "AND c.status IN ('running', 'resuming')"
            ),
            parameters=[{"name": "@id", "value": conversation_id}],
            enable_cross_partition_query=True,
        )), None) is not None

    configure_m365_history(M365HistoryService(
        tenant_id=TENANT_ID, jobs=cosmos_m365_execution_runs_container,
        approvals=get_m365_approval_service(), read_conversation=read_conversation,
        read_messages=read_messages, memory_resolver=memory_resolver,
        audience_resolver=audience, has_active_request=has_active_request,
    ))


def record_m365_pending(error, *, user_message_id=None):
    context = get_m365_execution_context()
    if context is None:
        raise error
    payload = dict(error.payload)
    payload.update({
        "type": "m365_approval_required",
        "m365_request_id": context.request_id,
        "conversation_id": context.conversation_id,
        "user_message_id": user_message_id,
        "message_persisted": bool(user_message_id),
        "done": True,
    })
    try:
        prior = cosmos_m365_execution_runs_container.read_item(
            context.request_id, partition_key=context.data_user_id,
        )
    except CosmosResourceNotFoundError:
        prior = {}
    record = {
        **prior,
        "id": context.request_id, "user_id": context.data_user_id,
        "type": "m365_execution_request", "status": "awaiting_approval",
        "actor_user_id": context.actor_user_id,
        "conversation_id": context.conversation_id,
        "workflow_id": context.workflow_id, "run_id": context.run_id,
        "request_fingerprint": getattr(g, "m365_request_fingerprint", None),
        "approval_id": error.approval_id,
        "user_message_id": user_message_id,
        "payload": m365_resume_payload(request.get_json(silent=True) or {}),
        "audience_version": context.audience_version,
        "workflow_ref": {
            key: value for key, value in (getattr(g, "m365_workflow", None) or {}).items()
            if key in {"id", "user_id", "group_id"}
        },
    }
    _save_m365_wait_record(record, prior, context)
    g.m365_approval_pending = True
    log_event(
        "[MS_GRAPH_PLUGIN] Microsoft 365 execution is waiting for approval.",
        level=logging.INFO,
        extra={"request_id": context.request_id, "approval_id": error.approval_id},
    )
    return payload


def _save_m365_wait_record(record, prior, context):
    if prior.get("status") in {"cancelled", "completed", "failed"}:
        raise M365PolicyError("m365_request_stopped", "This Microsoft 365 request has already stopped.")
    try:
        if prior:
            cosmos_m365_execution_runs_container.replace_item(
                record["id"], body=record,
                etag=prior["_etag"], match_condition=MatchConditions.IfNotModified,
            )
        else:
            cosmos_m365_execution_runs_container.create_item(body=record)
    except CosmosHttpResponseError as error:
        if error.status_code not in {409, 412}:
            raise
        raise M365PolicyError(
            "m365_request_changed", "The request changed while it was pausing. Review its current status before resuming.",
        ) from error


def complete_m365_request(*, success=True):
    context = get_m365_execution_context()
    if context is None or not getattr(g, "m365_has_pending_record", False) or getattr(g, "m365_approval_pending", False):
        return
    try:
        record = cosmos_m365_execution_runs_container.read_item(
            item=context.request_id, partition_key=context.data_user_id,
        )
    except CosmosResourceNotFoundError:
        return
    if record.get("status") in {"cancelled", "recovery_required"}:
        return
    record["status"] = "completed" if success else "failed"
    record.pop("payload", None)
    record.pop("request_fingerprint", None)
    cosmos_m365_execution_runs_container.replace_item(
        record["id"], body=record,
        etag=record["_etag"], match_condition=MatchConditions.IfNotModified,
    )
    if record.get("approval_id"):
        get_m365_approval_service().record_execution_status(
            record["approval_id"], context.data_user_id, context.request_id, record["status"],
        )


def cancel_m365_workflow_requests(workflow_id, run_id):
    """The caller has already authorized cancellation of this exact workflow run."""
    from functions_m365_pending_delivery import cancel_m365_run_deliveries
    jobs = cosmos_m365_execution_runs_container
    records = jobs.query_items(
        query=(
            "SELECT * FROM c WHERE c.type = 'm365_execution_request' "
            "AND c.workflow_id = @workflow_id AND c.run_id = @run_id "
            "AND c.status NOT IN ('completed', 'failed')"
        ),
        parameters=[
            {"name": "@workflow_id", "value": workflow_id},
            {"name": "@run_id", "value": run_id},
        ],
        enable_cross_partition_query=True,
    )
    for record in records:
        record["status"] = "cancelled"
        record.pop("payload", None)
        record.pop("request_fingerprint", None)
        jobs.replace_item(
            record["id"], body=record,
            etag=record["_etag"], match_condition=MatchConditions.IfNotModified,
        )
        if record.get("approval_id"):
            get_m365_approval_service().record_execution_status(
                record["approval_id"], record["user_id"], record["id"], "cancelled",
            )
    cancel_m365_run_deliveries(workflow_id, run_id)
