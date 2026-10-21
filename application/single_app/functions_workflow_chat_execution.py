# functions_workflow_chat_execution.py
"""Workflow-owned planning and execution through the existing chat runtime.

Version: 0.261.343
The application factories are deliberately deferred until task dispatch. Importing
workflow definitions or the scheduler must not initialize provider clients.
"""

import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Callable

from agent_execution_context import capture_execution_identity, workflow_identity_scope
from public_source_policy import current_public_source_policy


class WorkflowChatExecutionError(ValueError):
    """A safe workflow failure; never replace required tools with a plain answer."""


def child_execution_id(workflow_run_id, task_id):
    return f"run_{uuid.uuid5(uuid.NAMESPACE_URL, f'workflow-chat:{workflow_run_id}:{task_id}').hex}"


def workflow_capability_roles(workflow):
    """Restore only the existing server-authored, owner-bound capability grants."""
    user_id = workflow.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise PermissionError("The workflow execution identity is unavailable.")
    roles = ["User"]
    for prefix, role in (("url_access", "UrlAccessUser"), ("deep_research", "DeepResearchUser")):
        if (
            workflow.get(f"{prefix}_authorized") is True
            and workflow.get(f"{prefix}_authorized_by") == user_id
            and isinstance(workflow.get(f"{prefix}_authorized_at"), str)
            and workflow[f"{prefix}_authorized_at"]
        ):
            roles.append(role)
    return tuple(roles)


@contextmanager
def workflow_chat_identity(workflow, conversation_id):
    principal = capture_execution_identity(workflow["user_id"], conversation_id)
    principal = replace(principal, roles=workflow_capability_roles(workflow))
    with workflow_identity_scope(principal):
        yield principal


def build_workflow_chat_seeds(workflow, configuration):
    """Use composer identifiers and positive requirements, not a parallel tool set."""
    action = workflow.get("document_action") or {}
    selected = workflow.get("selected_agent") if workflow.get("runner_type") == "agent" else None
    group_id = workflow.get("group_id")
    scope = action.get("doc_scope") or ("group" if group_id else "personal")
    required = list(configuration.get("required_capabilities") or [])
    if action.get("type") == "search" and "document_search" not in required:
        required.append("document_search")
    model = {
        target: workflow[source] for source, target in (
            ("model_endpoint_id", "model_endpoint_id"), ("model_id", "model_id"),
            ("model_provider", "model_provider"),
        ) if workflow.get(source)
    }
    return {
        "document_ids": list(action.get("document_ids") or []),
        "document_labels": {},
        "doc_scope": scope,
        "active_group_ids": list(action.get("active_group_ids") or ([group_id] if group_id and scope in {"all", "group"} else [])),
        "active_public_workspace_ids": list(action.get("active_public_workspace_id") or []),
        "public_workspace_selection": None,
        "public_source_policy": workflow.get(
            "public_source_policy", current_public_source_policy(workflow.get("user_id")),
        ),
        "agent": deepcopy(selected),
        "model": model or None,
        "prompt": None,
        "tags": list(action.get("tags") or []),
        "document_filter_mode": action.get("document_filter_mode") or "intersection",
        "required_capabilities": required,
        "image_generation": "generate_image" in required,
        "image_references": [],
        "image_reference_documents": [],
        "image_reference_messages": [],
    }


def validate_required_outputs(plan, configuration):
    enabled = [step for step in plan.get("steps") or [] if step.get("enabled", True)]
    used = {step.get("capability_id") for step in enabled}
    if set(configuration.get("required_capabilities") or []) - used:
        raise WorkflowChatExecutionError("The task plan omitted a required capability.")
    deliverables = plan.get("deliverables") or []
    for kind in configuration.get("visual_requirements") or []:
        if kind == "image_proposal":
            if not any(
                step.get("capability_id") == "compose"
                and "image_proposal" in (step.get("arguments") or {}).get("visuals", [])
                for step in enabled
            ):
                raise WorkflowChatExecutionError("The task plan omitted a required image proposal.")
            continue
        if not any(
            item.get("kind") == kind and item.get("status") == "planned"
            and item.get("requested") == "explicit"
            for item in deliverables
        ):
            raise WorkflowChatExecutionError("The task plan omitted a required visual output.")


@dataclass(frozen=True)
class WorkflowChatRuntime:
    authorize: Callable[[], object]
    plan: Callable[[str, dict], tuple[dict, dict]]
    read: Callable[[str], dict | None]
    create: Callable[[dict, dict, dict], dict]
    start: Callable[[dict], dict]
    advance: Callable[[dict], dict]
    read_message: Callable[[str | None], dict | None]


def _request_digest(workflow, configuration):
    value = {
        "prompt": workflow.get("task_prompt"), "configuration": configuration,
        "seeds": build_workflow_chat_seeds(workflow, configuration),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _binding(workflow, run_id, task_id, digest, execution_id):
    return {
        "workflow_id": workflow["id"], "workflow_run_id": run_id, "task_id": task_id,
        "group_id": workflow.get("group_id") or "", "request_digest": digest, "execution_id": execution_id,
    }


def workflow_chat_result(record, answer):
    if record.get("status") != "completed" or record.get("outcome") != "completed":
        raise WorkflowChatExecutionError("The required chat capability execution did not complete.")
    if record.get("message_saved") is not True or record.get("finalization_status") != "saved":
        raise WorkflowChatExecutionError("The task outcome has not been saved.")
    if (
        not isinstance(answer, dict) or answer.get("conversation_id") != record["conversation_id"]
        or answer.get("id") != record.get("assistant_message_id")
        or answer.get("role") != "assistant"
    ):
        raise WorkflowChatExecutionError("The saved task outcome is unavailable.")
    return {
        "reply": answer.get("content") or "",
        "model_deployment_name": answer.get("model_deployment_name") or "",
        "provider": answer.get("model_provider") or "",
        "hybrid_citations": deepcopy(answer.get("hybrid_citations") or []),
        "web_search_citations": deepcopy(answer.get("web_search_citations") or []),
        "agent_citations": deepcopy(answer.get("agent_citations") or []),
        "generated_artifacts": deepcopy(answer.get("generated_artifacts") or []),
        "orchestration": deepcopy((answer.get("metadata") or {}).get("orchestration") or {}),
        "orchestration_run_id": record["id"],
        "orchestration_message_id": answer["id"],
        "token_usage": deepcopy(record.get("token_usage") or {}),
        "execution_status": "succeeded",
        "chat_execution_enabled": True,
    }


def cancel_workflow_chat_executions(workflow, run_id, conversation_id):
    """Fence only this workflow run's children through the existing cancellation owner."""
    import config
    from functions_orchestration_bootstrap import read_owned_conversation
    from functions_orchestration_recovery import fence_publication, request_cancellation
    from functions_orchestration_runs import get_orchestration_run

    user_id = workflow["user_id"]

    def authorize():
        conversation = read_owned_conversation(user_id, conversation_id)
        if conversation.get("workflow_id") != workflow["id"]:
            raise PermissionError("The workflow conversation is unavailable.")
        return conversation

    authorize()
    selectors = config.cosmos_orchestration_runs_container.query_items(
        query=(
            "SELECT c.id FROM c WHERE c.user_id = @user_id "
            "AND c.workflow_execution.workflow_id = @workflow_id "
            "AND c.workflow_execution.workflow_run_id = @workflow_run_id"
        ),
        parameters=[
            {"name": "@user_id", "value": user_id},
            {"name": "@workflow_id", "value": workflow["id"]},
            {"name": "@workflow_run_id", "value": run_id},
        ],
        partition_key=conversation_id,
    )
    for selector in selectors:
        record = get_orchestration_run(selector["id"], user_id, conversation_id, strict=True)
        binding = (record or {}).get("workflow_execution") or {}
        if binding.get("workflow_id") != workflow["id"] or binding.get("workflow_run_id") != run_id:
            raise WorkflowChatExecutionError("The saved chat execution does not match this task.")
        record = request_cancellation(record["id"], user_id, conversation_id, authorize)
        fence_publication(record, config.cosmos_messages_container)


def execute_workflow_chat_task(
    workflow, settings, *, conversation_id, run_id, configuration, check_cancelled,
    runtime=None, execution=None, clock=time.monotonic, sleep=time.sleep,
):
    """Resume the same admitted child; only a genuinely new run plans again."""
    if not settings.get("enable_chat_orchestration"):
        raise WorkflowChatExecutionError("Chat orchestration is not available for this task.")
    producer = workflow.get("_analysis_producer") or {}
    task_id = str((workflow.get("active_task") or {}).get("id") or "legacy-task")
    execution_id = str(producer.get("execution_id") or task_id)
    child_id = child_execution_id(run_id, execution_id)
    digest = _request_digest(workflow, configuration)
    binding = _binding(workflow, run_id, task_id, digest, execution_id)
    runtime = runtime or _application_runtime(workflow, settings, conversation_id, run_id, check_cancelled)
    runtime.authorize()
    with workflow_chat_identity(workflow, conversation_id):
        record = runtime.read(child_id)
        if record is None:
            check_cancelled()
            plan, turn = runtime.plan(child_id, configuration)
            validate_required_outputs(plan, configuration)
            check_cancelled()
            record = runtime.create(plan, turn, binding)
        if (
            record.get("id") != child_id or record.get("user_id") != workflow["user_id"]
            or record.get("conversation_id") != conversation_id or record.get("workflow_execution") != binding
        ):
            raise WorkflowChatExecutionError("The saved chat execution does not match this task.")
        deadline = clock() + 600
        while True:
            runtime.authorize()
            check_cancelled()
            if record.get("status") in {"completed", "failed", "cancelled"}:
                return workflow_chat_result(record, runtime.read_message(record.get("assistant_message_id")))
            record = runtime.start(record) if not record.get("started_at") else runtime.advance(record)
            if record.get("status") in {"completed", "failed", "cancelled"}:
                continue
            if execution is not None:
                execution.wait_for_output(f"task:{task_id}", [{
                    "kind": "workflow_orchestration", "run_id": child_id,
                    "workflow_run_id": run_id, "task_id": task_id,
                }])
            if clock() >= deadline:
                raise WorkflowChatExecutionError("The task is still waiting for its required chat output.")
            sleep(0.5)


def _application_runtime(workflow, settings, conversation_id, run_id, check_cancelled):
    # This composition root is entered only after the workflow owner initialized config.
    import config
    from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError
    from cosmos_document_utils import normalize_cosmos_document
    from functions_orchestration_bootstrap import (
        build_orchestration_cleanup_service, build_orchestration_services, current_execution_identity,
        read_owned_conversation,
    )
    from functions_orchestration_context import (
        build_capability_request_context, build_conversation_signals, build_conversation_snapshot,
        build_planner_context, enrich_planner_candidates, normalize_history_message,
        resolve_action_catalog, resolve_agent_catalog, resolve_candidate_documents,
        resolve_image_reference_candidates,
    )
    from functions_orchestration_execution import prepare_harness_execution
    from functions_orchestration_memory import load_orchestration_memory
    from functions_orchestration_models import resolve_orchestration_model
    from functions_orchestration_plan_revisions import claim_plan_run, read_revision_run
    from functions_orchestration_planner import plan_request
    from functions_orchestration_recovery import ExecutionLease
    from functions_orchestration_registry import resolve_admitted_export_catalog
    from functions_orchestration_runs import create_orchestration_run, get_orchestration_run
    from functions_orchestration_scheduler import (
        OrchestrationSchedulerResources, continue_workflow_orchestration_once,
    )
    from functions_orchestration_services import composition_profiles
    from functions_appinsights import log_event
    from functions_workflow_runtime import _authorize_execution
    from functions_workflow_configuration import WORKFLOW_CAPABILITY_IDS

    user_id = workflow["user_id"]
    actor_id = workflow.get("_workflow_actor_user_id") or user_id
    allowed = settings.get("chat_orchestration_enabled_capabilities")
    completed_capability = workflow.get("_workflow_completed_document_capability")
    settings = {
        **settings,
        "chat_orchestration_enabled_capabilities": [
            capability for capability in WORKFLOW_CAPABILITY_IDS
            if (allowed is None or capability in allowed) and capability != completed_capability
        ],
    }

    def authorize():
        check_cancelled()
        _authorize_execution(workflow, actor_id, settings)
        conversation = read_owned_conversation(user_id, conversation_id)
        if conversation.get("workflow_id") != workflow["id"]:
            raise PermissionError("The workflow conversation is unavailable.")
        return conversation

    def read(child_id):
        authorize()
        return get_orchestration_run(child_id, user_id, conversation_id, strict=True)

    def plan(child_id, configuration):
        conversation = authorize()
        seeds = build_workflow_chat_seeds(workflow, configuration)
        request = workflow.get("task_prompt") or ""
        visuals = configuration.get("visual_requirements") or []
        if visuals:
            request += "\n\n[Required outputs]\nInclude " + ", ".join(visuals) + " in the final answer."
        turn_id = f"turn_{uuid.uuid5(uuid.NAMESPACE_URL, child_id).hex}"
        message_id = f"{conversation_id}_workflow_task_{child_id}"
        message = {
            "id": message_id, "conversation_id": conversation_id, "role": "user", "content": request,
            "metadata": {"workflow_id": workflow["id"], "workflow_run_id": run_id},
        }
        try:
            config.cosmos_messages_container.create_item(body=message)
        except CosmosResourceExistsError:
            previous = config.cosmos_messages_container.read_item(item=message_id, partition_key=conversation_id)
            if any(previous.get(key) != message.get(key) for key in ("conversation_id", "role", "content", "metadata")):
                raise WorkflowChatExecutionError("The saved task request changed.") from None
        normalized = normalize_history_message(message)
        identity = current_execution_identity(user_id, conversation_id, seeded_agent=seeds.get("agent"))
        services = build_orchestration_services(user_id, conversation_id, settings=settings)
        agents = resolve_agent_catalog(user_id, seeds=seeds, settings=settings, user_groups=seeds["active_group_ids"])
        actions = resolve_action_catalog(
            user_id, seeds=seeds, settings=settings, user_groups=seeds["active_group_ids"],
            user_roles=identity["user_roles"],
        )
        candidates, _ = resolve_candidate_documents(request, user_id, seeds, conversation_id, settings)
        candidates = enrich_planner_candidates(candidates, user_id, conversation_id=conversation_id, seeds=seeds)
        seeds = resolve_image_reference_candidates(
            seeds, user_id, conversation_id, candidates=candidates, settings=settings,
        )
        memory = load_orchestration_memory(user_id, conversation, request, settings=settings, seeds=seeds)
        context = build_planner_context(
            request, candidates=candidates, seeds=seeds, agents=agents, actions=actions,
            signals=build_conversation_signals([], request), memory_context=memory,
        )
        if services.document_transform_candidate_reader is not None:
            references = services.document_transform_candidate_reader([item["document_id"] for item in candidates])
            context["document_transform_references"] = seeds["document_transform_references"] = references
        catalog = resolve_admitted_export_catalog(services.export_catalog())
        request_context = build_capability_request_context(
            user_id, identity, request, agents, actions, **services.capability_request_bindings(),
        )
        model = resolve_orchestration_model(settings, user_id=user_id, seeds=seeds, identity_context=identity, planner=True)
        try:
            kind, planned = plan_request(
                request, context, conversation_id, user_id, settings=settings,
                approval_mode="auto", authorized_document_ids={item["document_id"] for item in candidates},
                allow_elicitation=False, turn_id=turn_id, seeds=seeds,
                document_labels={item["document_id"]: item.get("file_name") or "" for item in candidates},
                request_context=request_context, planner_model=model, contract_version=2,
                export_catalog=catalog, composition_profiles=composition_profiles(),
            )
        finally:
            model.close()
        if kind != "plan":
            raise WorkflowChatExecutionError("The task needs more information before it can execute.")
        planned.update(run_id=child_id, plan_id=f"plan_{uuid.uuid5(uuid.NAMESPACE_URL, child_id).hex}", turn_id=turn_id)
        return planned, {
            "user_message": request, "resolved_message": request, "user_message_id": message_id,
            "user_message_fingerprint": normalized["fingerprint"], "turn_id": turn_id, "seeds": seeds,
            "conversation_context": build_conversation_snapshot([], None, turn_id=turn_id),
            "memory_audience": memory["audience"], "memory_scope": memory["scope"],
            "planning_token_usage": planned.get("token_usage") or {},
            "time_zone": (workflow.get("schedule") or {}).get("timezone") or "UTC",
        }

    def create(planned, turn, binding):
        return create_orchestration_run(
            planned, user_id, conversation_id, idempotent=True, turn_context=turn,
            initial_updates={"workflow_execution": binding},
        )

    def start(record):
        authorize()
        services = build_orchestration_services(user_id, conversation_id, settings=settings)
        claimed = claim_plan_run(
            record["id"], user_id, conversation_id, plan_id=record["plan"]["plan_id"],
            conversation_context=record["conversation_context"], settings=settings,
            export_catalog=resolve_admitted_export_catalog(services.export_catalog()),
            composition_profiles=composition_profiles(),
        )
        lease = ExecutionLease(claimed, authorize, message_container=config.cosmos_messages_container)
        execution = prepare_harness_execution(claimed, settings=settings, lease=lease)
        execution.execute()
        return read(record["id"])

    resources = OrchestrationSchedulerResources(
        runs_container=config.cosmos_orchestration_runs_container,
        messages_container=config.cosmos_messages_container, settings=settings,
        read_conversation=lambda uid, cid: authorize() if (uid, cid) == (user_id, conversation_id) else None,
        read_run=read_revision_run, build_services=build_orchestration_services,
        build_cleanup_service=build_orchestration_cleanup_service, log=log_event,
    )

    def read_message(message_id):
        if not message_id:
            return None
        authorize()
        try:
            return normalize_cosmos_document(config.cosmos_messages_container.read_item(
                item=message_id, partition_key=conversation_id,
            ))
        except CosmosResourceNotFoundError:
            raise WorkflowChatExecutionError("The saved task outcome is unavailable.") from None

    return WorkflowChatRuntime(
        authorize, plan, read, create, start,
        lambda record: continue_workflow_orchestration_once(record, resources=resources, authorize=authorize),
        read_message,
    )
