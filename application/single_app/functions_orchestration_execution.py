# functions_orchestration_execution.py
"""Headless preparation and guarded publication for saved orchestration attempts.

Version: 0.261.141
Implemented in: 0.261.127

Every saved attempt uses the Gather / Reason / Render contract; a run from the removed
legacy contract is refused before any preparation. The ``Harness*`` names below are the
historical names of this runtime and are kept for compatibility with its callers.

Web and scheduler callers claim the attempt first and pass its real ExecutionLease
to ``prepare_harness_execution``. Preparation starts an unstarted lease; ``execute``
owns resource cleanup and publishes the durable message independently of a browser.
Its optional callback receives only progress SSE strings; returned final SSE strings
are never sent to that callback. Call ``close`` if prepared execution is not started.
An accepted lease's definitive preparation failure is finalized before raising
``HarnessExecutionError``. Its ``final_frames`` contain the final SSE strings and
``durable_status`` is the confirmed terminal status, or None if ownership/storage
prevented confirmation. Rejected or foreign leases are never finalized.
After a renderer-only tick and guarded runtime reconciliation, use
``refresh_harness_delivery`` to publish the saved outcome without preparing models,
recalling memory, polling native computation, or executing any producer.
Delivery reconstructs document citations from the selected final result's exact
authorized lineage, never from ambient tasks or a stale saved citation list.
``finalize_harness_failure`` records a verified deadline, cancellation or access
failure without execution. Delivery infrastructure failures raise a safe exception
with ``retryable`` set when appropriate; they never masquerade as source denial.
Directory, external-configuration and screening service failures propagate with
that classification from preparation and normal finalization too, without
publishing uncertain content or replacing validated service retryability.
Typed checkpoint-read and output-storage outages remain retryable through
known application wrappers; missing or invalid proof is not reclassified.
An optional server ``checkpoint_factory(record, context, settings, lease)`` binds
an explicit continuation owner at execution time. It is never persisted; omitting
it keeps the existing ExecutionCheckpoints owner. An invalid or failed supplied
factory never falls back to another owner.
With a same-attempt or injected continuation owner, uncertain checkpoint/storage
I/O propagates without terminalizing retained work, including lease-start failures.
Initial and resumed execution bind the shared result store to the actual owning
lease through ``WorkflowResultStore.bind_orchestration_execution`` before capability or
retained-result access. Its canonical binding keeps native producer tokens
unchanged while fencing generic result access with the current parent claim;
older store views are never rebound. Model-free delivery does not claim results.
Preparation and execution each own a strict source-authority scope on the
calling worker. Nested source failures remain fenced even when caught; answer
and research calls check that fence before and after provider invocation. The
scope is released with the operation, never retained on a lease or shared between
independent runs. Uncertain authority cannot publish a terminal aggregate outcome.
Recognized output-read configuration failures preserve retained work during both
initial finalization and model-free refresh, including nonretryable wrapped errors.
An opaque permission fault escaping current-file observation also blocks publication;
the output facade still owns verified source-denial and hold projections.
Capability discovery uses the initialized services' shared request bindings;
``external_source_preflight``, ``external_source_admission``,
``external_source_authorizer`` and ``capture_external_source_configuration`` stay
runtime-only and must all be present before their saved capabilities can be
prepared. Preflight is the real synchronous invocation guard; configuration capture
separately validates current/actual acquisition support. The authorizer comes from
``services.results.access``. Discovery neither invokes these callbacks nor applies
a new-plan readiness check to saved work.
Runtime preflight/capture/admission callbacks check their original claim before
and after each invocation, including failure. The captured actor/run/token/claim
identity cannot be replaced by retagging the lease. Their closures reject a stopped
worker; shared service callbacks and model-free history readers remain unmodified.
Active discovery and revalidation use the services' current admitted export
catalog through the shared canonical resolver. Empty selections stay empty;
format/profile narrowing lives only on the runtime context, not saved permission
snapshots. Model-free delivery does not require admission for new Render work.
Typed invocation cancellation remains cancellation, including through known
application wrappers; ordinary owner interruptions are not inferred to be stops.
Headless lifecycle failures opt in to typed invocation control. Capture may
reconstruct their safe code, but never their diagnostics or publication state.
Every published reply, including model-free delivery, passes chat's configured
output checkpoint first. A removed reply publishes only the safe notice, without
citations or file cards; an administrator's later retraction is never overwritten.
Check-before-display runs keep files private until that checked reply is saved.
Saved history rejects content-check removals through the shared normalizer. An Auto plan's
per-step model bindings are reauthorized before model setup; a missing or stale binding fails
closed.

Application-owner imports are deliberately deferred until preparation. Importing
this module neither imports a route nor discovers configuration or Azure clients.
"""

import json
import logging
import re
import threading
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps

from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosAccessConditionFailedError, CosmosResourceNotFoundError
from openai import OpenAIError

from agent_execution_context import ExecutionIdentity, capture_execution_identity
from content_screening.access import (
    assert_current_request_sources_available, guard_model_callable, strict_source_authority,
)
from content_screening.contracts import DocumentHeldError, ScreeningError
from functions_appinsights import log_event, workflow_log_context
from functions_orchestration_adapters import resolve_context_source_manifest
from functions_orchestration_checkpoints import CheckpointError, fingerprint, orchestration_answer_message_id
from functions_orchestration_context import (
    HISTORY_MAX_MESSAGES,
    CatalogResolutionError,
    ConversationContextError,
    ElicitationContextError,
    build_capability_request_context,
    build_elicitation_user_request,
    conversation_user_urls,
    normalize_history_message,
    resolve_action_catalog,
    resolve_agent_catalog,
    resolve_elicitation_references,
    validate_clarification_answers,
    validate_conversation_snapshot,
)
from functions_orchestration_deliverables import (
    delivery_notes, generated_image_assets, project_generated_images,
)
from functions_orchestration_events import (
    build_content_event,
    build_error_event,
    build_model_reasoning_metadata,
    build_planning_thought,
    build_reasoning_adjustment_event,
    build_run_done_event,
    build_step_event,
    merge_reasoning_adjustments,
    serialize_sse,
)
from functions_orchestration_executor import RunContext, execute_plan
from functions_orchestration_invocation_capture import (
    OrchestrationInvocationCancelledError, OrchestrationInvocationControlError,
)
from functions_orchestration_memory import (
    OrchestrationMemoryError,
    load_orchestration_memory,
    validate_memory_audience,
    validate_memory_context,
)
from functions_model_catalog import ModelCatalogError
from functions_orchestration_model_routing import (
    STEP_TASKS, answer_selection, step_model_context, validate_auto_bindings,
)
from functions_orchestration_models import (
    REASONING_COMPLETION_BUDGET,
    OrchestrationModelError,
    has_planner_model_override,
    resolve_orchestration_model,
)
from functions_orchestration_registry import (
    CapabilityResolutionError, resolve_admitted_export_catalog, resolve_available_capability_ids,
)
from functions_orchestration_result_contracts import InputBinding, ResultContractError, ResultRef, TaskResult
from functions_orchestration_result_runtime import read_complete_input, read_result_document_citations
from functions_orchestration_results import ResultUnavailableError
from functions_orchestration_schema import (
    LEGACY_PLAN_CODE,
    build_failure,
    failure_explanation,
    is_legacy_plan,
    plan_contract_version,
    PlanValidationError,
    safe_failure,
    summarize_plan,
)
from functions_workflow_context import (
    WorkflowContextBudgetError,
    calculate_workflow_context_budget,
)
from model_endpoint_clients import (
    ModelEndpointBehavior, extract_chat_completion_response_text, is_response_format_rejection,
)


ANSWER_MAX_TOKENS = 4000
ANSWER_TEMPERATURE = 0.3
_USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")
_WAITING_OUTPUT_STATES = frozenset({"waiting", "rendering", "retry_scheduled"})
_MODEL_METADATA_FIELDS = ("model_deployment_name", "model_provider", "model_endpoint_id", "model_id")
_REASONING_METADATA_FIELDS = ("reasoning_effort", "requested_reasoning_effort", "reasoning_mode")
_DELIVERY_FAILURE_CODES = frozenset({"run_timeout", "user_cancelled", "context_unavailable"})


class HarnessExecutionError(OrchestrationInvocationControlError):
    """Application-owned failure text, never a provider diagnostic."""

    def __init__(
        self, code="execution_interrupted", *, final_frames=(), durable_status=None, retryable=False,
    ):
        self.failure = build_failure(code)
        self.code = self.failure["code"]
        self.message = self.failure["message"]
        self.final_frames = list(final_frames)
        self.durable_status = durable_status
        self.retryable = retryable
        super().__init__(self.message)


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _usage(*values):
    return {
        field: sum(
            value.get(field, 0) for value in values
            if isinstance(value, dict) and type(value.get(field, 0)) is int
            and value.get(field, 0) >= 0
        )
        for field in _USAGE_FIELDS
    }


def _known_failure_chain(error):
    """Follow causes only through known application-owned wrappers."""
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        if not isinstance(current, (CheckpointError, HarnessExecutionError, PermissionError)):
            return
        current = current.__cause__


def _is_invocation_cancellation(error):
    """Recognize a server cancellation, not arbitrary owner errors or code text."""
    return any(
        isinstance(failure, OrchestrationInvocationCancelledError)
        for failure in _known_failure_chain(error)
    )


def _failure(error):
    if _is_invocation_cancellation(error):
        return build_failure("user_cancelled")
    if isinstance(error, (CheckpointError, HarnessExecutionError)):
        return safe_failure(error.failure)
    if isinstance(error, (
        ConversationContextError, OrchestrationMemoryError, PermissionError,
        DocumentHeldError, ResultUnavailableError, CatalogResolutionError,
        CapabilityResolutionError, ElicitationContextError, OrchestrationModelError,
        PlanValidationError,
    )):
        return build_failure("context_unavailable")
    if isinstance(error, ResultContractError):
        return build_failure("result_invalid")
    return build_failure("execution_interrupted")


def _log_failure(message, record, error, *, stage="execution"):
    response_type = type(record).__name__
    record = record if isinstance(record, dict) else {}
    log_event(
        f"[ORCHESTRATION_RUNS] {message}",
        level=logging.WARNING,
        extra={
            **workflow_log_context(
                run_id=record.get("id"), conversation_id=record.get("conversation_id"),
                turn_id=record.get("turn_id"),
            ),
            "stage": stage, "response_type": response_type,
            "error_type": type(error).__name__, "execution_code": _failure(error)["code"],
        },
    )


def _execution_bound_external_callback(callback, lease):
    """Fence runtime effects without rebinding shared services to a mutable owner."""
    if callback is None:
        return None
    if not callable(callback):
        raise ResultContractError("result_external_reader_required")
    read_execution, is_stopped = lease.read, lease.stopped.is_set
    original_owner = (
        lease.run_id, lease.user_id, lease.conversation_id, lease.token, lease.claim_id,
    )

    def check_execution():
        if is_stopped():
            raise CheckpointError("ownership_lost")
        record = read_execution()
        claim = record.get("execution_lease") or {}
        current_owner = (
            record.get("id"), record.get("user_id"), record.get("conversation_id"),
            claim.get("token"), claim.get("claim_id"),
        )
        if is_stopped() or current_owner != original_owner:
            raise CheckpointError("ownership_lost")

    @wraps(callback)
    def guarded(*args, **kwargs):
        check_execution()
        try:
            return callback(*args, **kwargs)
        finally:
            check_execution()

    return guarded


def _create_answer_completion(model, messages, *, json_output, stage):
    """Request JSON mode when asked, resending without it if the endpoint refuses the option."""
    options = {
        "messages": messages, "temperature": ANSWER_TEMPERATURE,
        "max_tokens": ANSWER_MAX_TOKENS, "use_model_response_length": True,
    }
    if not json_output:
        return model.create_completion(**options)
    try:
        return model.create_completion(**options, response_format={"type": "json_object"})
    except Exception as exc:
        if not is_response_format_rejection(exc):
            raise
        # JSON-mode support differs by endpoint and API version; the prompt already asks
        # for one JSON object, and the caller validates the reply either way.
        log_event(
            "[ORCHESTRATION] Retrying the answer model without a JSON response format.",
            level=logging.INFO,
            extra={"stage": stage, "reason": "json_format_retry", "error_type": type(exc).__name__},
        )
        return model.create_completion(**options)


def build_harness_invoke_prompt(model, *, token_usage, revalidate):
    """Bind the authorized model once, preserving exact composition budget metadata.

    ``metadata={"json_output": True}`` asks the endpoint for a JSON object; an endpoint that
    refuses the option is asked again without it.
    """
    behavior_name = model.behavior_name or model.deployment
    output_tokens = model.response_length
    if output_tokens is None:
        output_tokens = (
            max(ANSWER_MAX_TOKENS, REASONING_COMPLETION_BUDGET)
            if ModelEndpointBehavior(model.provider, behavior_name).is_openai_reasoning_model
            else ANSWER_MAX_TOKENS
        )

    @strict_source_authority()
    def invoke_prompt(prompt_text, stage="window_analysis", metadata=None):
        messages = (
            prompt_text if isinstance(prompt_text, list)
            else [{"role": "user", "content": str(prompt_text or "")}]
        )
        revalidate()
        assert_current_request_sources_available()
        if (metadata or {}).get("complete_saved_analysis_input"):
            audit = calculate_workflow_context_budget(
                messages, invoke_prompt.model_metadata,
                provider=invoke_prompt.provider, output_tokens=invoke_prompt.output_tokens,
            )
            invoke_prompt.context_budget = audit
            if audit["decision"] != "full_input":
                raise WorkflowContextBudgetError(audit)
        try:
            response = _create_answer_completion(
                model, messages, json_output=(metadata or {}).get("json_output") is True, stage=stage,
            )
        except (OpenAIError, AzureError) as exc:
            log_event(
                "[ORCHESTRATION] The answer model request failed.",
                level=logging.WARNING,
                extra={"stage": stage, "error_type": type(exc).__name__},
            )
            raise HarnessExecutionError("model_failed") from exc
        usage = getattr(response, "usage", None)
        for field in _USAGE_FIELDS:
            value = getattr(usage, field, None)
            if type(value) is int and value >= 0:
                token_usage[field] = token_usage.get(field, 0) + value
        revalidate()
        assert_current_request_sources_available()
        if not response or not response.choices:
            raise HarnessExecutionError("model_failed")
        choice = response.choices[0]
        if choice.finish_reason == "content_filter" or getattr(choice.message, "refusal", None):
            raise HarnessExecutionError("model_failed")
        text = extract_chat_completion_response_text(response)
        if not text.strip():
            raise HarnessExecutionError("model_failed")
        return text

    invoke_prompt.model_metadata = model.model_metadata or behavior_name
    invoke_prompt.provider = model.provider
    invoke_prompt.output_tokens = output_tokens
    return invoke_prompt


def _conversation_context(record, message_container, read_conversation):
    """Rebuild the exact saved snapshot and turn, never the latest browser history."""
    read_conversation()
    user_id, conversation_id = record["user_id"], record["conversation_id"]
    snapshot = record.get("conversation_context")
    entries = snapshot.get("messages") if type(snapshot) is dict else None
    if (
        type(entries) is not list or len(entries) > HISTORY_MAX_MESSAGES
        or not record.get("user_message_id") or not record.get("user_message_fingerprint")
    ):
        raise ConversationContextError("This request needs a new plan.")
    ids = [entry.get("id") for entry in entries if type(entry) is dict]
    if (
        len(ids) != len(entries) or any(type(value) is not str or not value for value in ids)
        or len(set(ids)) != len(ids)
    ):
        raise ConversationContextError("This request needs a new plan.")
    try:
        turn = message_container.read_item(
            item=record["user_message_id"], partition_key=conversation_id,
        )
        messages = [
            message_container.read_item(item=message_id, partition_key=conversation_id)
            for message_id in ids
        ]
    except CosmosResourceNotFoundError as exc:
        raise ConversationContextError("This request needs a new plan.") from exc
    normalized = normalize_history_message(turn)
    if (
        not normalized or normalized["role"] != "user"
        or turn.get("conversation_id") != conversation_id
        or normalized["fingerprint"] != record["user_message_fingerprint"]
        or any(message.get("conversation_id") != conversation_id for message in messages)
    ):
        raise ConversationContextError("This request needs a new plan.")
    contexts = deepcopy(snapshot.get("analysis_result_contexts") or [])
    for context in record.get("analysis_result_contexts") or []:
        if context not in contexts:
            contexts.append(deepcopy(context))
    if messages or contexts:
        # Saved-analysis readers need initialized storage; early imports must not
        # pull their artifact/provider dependency chain into the runtime.
        from functions_saved_analysis import (
            analysis_result_contexts, load_saved_analysis, sanitize_saved_analysis_messages,
        )

        messages = sanitize_saved_analysis_messages(messages, user_id)
        for message in messages:
            for context in analysis_result_contexts(message):
                if context not in contexts:
                    contexts.append(context)
        for context in contexts:
            load_saved_analysis(user_id, context)
    validated = validate_conversation_snapshot(
        {key: value for key, value in snapshot.items() if key != "analysis_result_contexts"},
        messages,
    )
    if contexts:
        validated["analysis_result_contexts"] = contexts
    return validated


def _partition_citations(citations):
    documents, web, tools = [], [], []
    for citation in citations or []:
        if not isinstance(citation, dict):
            continue
        if citation.get("document_id"):
            documents.append(deepcopy(citation))
        elif citation.get("tool_name") or citation.get("function_name"):
            tools.append(deepcopy(citation))
        else:
            web.append(deepcopy(citation))
    return documents, web, tools


def _delivery_summary(outputs, artifacts):
    """Describe only durable, public file facts; artifact cards provide the links."""
    delivered = {artifact["output_id"] for artifact in artifacts}
    lines = []
    for output in outputs:
        name = re.sub(r"([\\`*{}\[\]()#+.!_<>|~-])", r"\\\1", output["file_name"])
        state = output["state"]
        if output.get("available") is False or (
            state == "completed" and output["output_id"] not in delivered
        ):
            detail = "unavailable; current access could not be verified"
        elif state == "completed":
            facts = []
            for key, unit in (("row_count", "rows"), ("character_count", "characters"), ("size_bytes", "bytes")):
                if type(output.get(key)) is int and output[key] >= 0:
                    facts.append(f"{output[key]:,} {unit}")
            detail = "ready" + (f" ({', '.join(facts)})" if facts else "")
        elif state == "retry_scheduled":
            detail = "waiting for an automatic file retry"
        elif state in _WAITING_OUTPUT_STATES:
            detail = "waiting for file preparation"
        elif state == "cancelled":
            detail = "cancelled"
        else:
            detail = "could not be created"
            if output.get("can_retry"):
                detail += "; a file-only retry is available"
        lines.append(f"- {name}: {detail}.")
    return "Files:\n" + "\n".join(lines) if lines else ""


class HarnessExecution:
    """One already-claimed attempt, safe to execute without Flask request state."""

    def __init__(self, record, lease):
        self.record = deepcopy(record)
        self.lease = lease
        self.checkpoint_factory = None
        self.context = None
        self.services = None
        self.answer_model = None
        self.research_model = None
        self.settings = None
        self.prompt_token_usage = _usage(
            record.get("harness_prompt_token_usage", record.get("planning_token_usage")),
        )
        self._emit = None
        self._frames = None
        self._final_record = None
        self._bootstrap = None
        self._closed = False
        self._released = False
        self._required_capabilities = None
        self._capability_context = None
        self._delivery_only = False
        self._delivery_context_denied = False
        self._saved_model_metadata = {}
        self._saved_reasoning = {}
        self._execution_lock = threading.Lock()
        self._preparation_stage = "claim_validation"

    @property
    def service(self):
        return self.services

    def _read_conversation(self):
        self.lease.read()
        return self._bootstrap.read_owned_conversation(
            self.record["user_id"], self.record["conversation_id"],
        )

    def _validate_memory(self):
        conversation = self._read_conversation()
        validate_memory_context(
            conversation, self.record["user_id"],
            self.record.get("memory_audience"), self.record.get("memory_scope"),
        )
        if self.context is not None:
            memory = self.context.memory_context
            validate_memory_context(
                conversation, self.record["user_id"], memory["audience"], memory["scope"],
            )
        return conversation

    def _revalidate_context(self):
        if not self._delivery_only:
            assert_current_request_sources_available(self.record["user_id"])
        snapshot = _conversation_context(
            self.record, self.lease.message_container, self._read_conversation,
        )
        resolve_elicitation_references(
            self.record.get("seeds", {}).get("elicitation_references") or [],
            self.record["user_id"], self.record["conversation_id"],
            settings=self._bootstrap.get_settings(),
        )
        self._validate_memory()
        self._validate_capabilities()
        if not self._delivery_only:
            assert_current_request_sources_available(self.record["user_id"])
        return snapshot

    def _validate_capabilities(self):
        if self._required_capabilities is None:
            return
        current = self._bootstrap.get_settings()
        export_catalog = None
        if not self._delivery_only:
            export_catalog = resolve_admitted_export_catalog(self.services.export_catalog())
            if self.context is not None:
                self.context.export_catalog = export_catalog
        available = resolve_available_capability_ids(
            current, allowed_ids=current.get("chat_orchestration_enabled_capabilities"),
            candidate_ids=self._required_capabilities,
            request_context=self._capability_context, contract_version=2, export_catalog=export_catalog,
        )
        if not current.get("enable_chat_orchestration") or self._required_capabilities - set(available):
            raise HarnessExecutionError("context_unavailable")

    def _reload_memory(self):
        memory = load_orchestration_memory(
            self.record["user_id"], self._validate_memory(),
            self.context.user_request, settings=self._bootstrap.get_settings(),
            seeds=self.record.get("seeds") or {},
            expected_audience=self.context.memory_context["audience"],
        )
        self.context.memory_context = memory
        for notice in memory["notices"]:
            self._send(build_planning_thought(notice))
        return memory

    def _initialize(self, settings, identity_context, execution_identity):
        # Bootstrap and recovery import config as the initialized application owner.
        # They must never run merely because a scheduler imports this module.
        self._preparation_stage = "bootstrap"
        import functions_orchestration_bootstrap as bootstrap
        from functions_document_analysis_checkpoints import analysis_checkpoints_for_orchestration

        self._bootstrap = bootstrap
        self._preparation_stage = "settings"
        self.settings = deepcopy(bootstrap.get_settings() if settings is None else settings)
        if type(self.settings) is not dict or not self.settings.get("enable_chat_orchestration"):
            raise HarnessExecutionError("context_unavailable")
        plan = self.record["plan"]
        auto_routing = plan.get("model_routing") == "auto"
        if auto_routing and any(
            step.get("enabled", True) and step.get("capability_id") in STEP_TASKS and not step.get("model_binding")
            for step in plan.get("steps") or []
        ):
            # An Auto plan without its approved bindings is never run on a substituted model.
            raise HarnessExecutionError("model_routing_changed")
        user_id, conversation_id = self.record["user_id"], self.record["conversation_id"]
        seeds = self.record.get("seeds") or {}
        self._preparation_stage = "context"
        snapshot = self._revalidate_context()
        answers = self.record.get("answered_questions") or []
        validate_clarification_answers(answers)
        self._preparation_stage = "identity"
        current_identity = capture_execution_identity(user_id, conversation_id)
        principal = execution_identity or current_identity
        if (
            type(principal) is not ExecutionIdentity
            or principal.user_id != user_id or principal.conversation_id != conversation_id
            or principal.roles != current_identity.roles or principal.email != current_identity.email
        ):
            raise HarnessExecutionError("context_unavailable")
        identity = bootstrap.current_execution_identity(
            user_id, conversation_id, seeded_agent=seeds.get("agent"),
        )
        if identity_context is not None:
            if (
                type(identity_context) is not dict
                or not isinstance(identity_context.get("user_roles", []), (list, tuple))
                or set(identity_context.get("user_roles") or []) - set(identity.get("user_roles") or [])
            ):
                raise HarnessExecutionError("context_unavailable")
            identity["user_roles"] = list(identity_context.get("user_roles") or [])
            identity["user_enable_agents"] = (
                identity.get("user_enable_agents", True)
                and identity_context.get("user_enable_agents", True) is True
            )
        if (
            type(identity) is not dict
            or not isinstance(identity.get("user_roles", []), (list, tuple))
            or set(identity.get("user_roles") or []) - set(principal.roles)
        ):
            raise HarnessExecutionError("context_unavailable")
        identity["user_roles"] = list(identity.get("user_roles") or [])
        identity["user_email"] = current_identity.email
        self._preparation_stage = "catalogs"
        agents = resolve_agent_catalog(
            user_id, seeds=seeds, settings=self.settings,
            user_groups=seeds.get("active_group_ids") or None,
        ) if identity.get("user_enable_agents", True) else []
        actions = resolve_action_catalog(
            user_id, seeds=seeds, settings=self.settings,
            user_groups=seeds.get("active_group_ids") or None,
        )
        user_message = self.record.get("user_message") or ""
        allowed_urls = list(dict.fromkeys([
            *(self.record.get("edit_user_urls") or []),
            *conversation_user_urls(
                user_message, snapshot, (self.record.get("request_resolution") or {}).get("message_ids"),
                answers,
            ),
        ]))[:8]
        self._preparation_stage = "services"
        self.services = bootstrap.build_orchestration_services(
            user_id, conversation_id, settings=self.settings,
        )
        self._preparation_stage = "result_binding"
        try:
            current = self.lease.read()
            if any(
                current.get(key) != self.record.get(key)
                for key in ("id", "user_id", "conversation_id", "attempt_index")
            ):
                raise CheckpointError("ownership_lost")
            self.services.results.store = self.services.results.store.bind_orchestration_execution(
                user_id, conversation_id, self.record["id"],
                guard_token=self.lease.token, check_execution=self.lease.read,
            )
        except Exception as exc:
            self._raise_delivery_infrastructure_failure(exc, storage_required=True)
            raise
        self._preparation_stage = "capabilities"
        request_context = build_capability_request_context(
            user_id, identity, user_message, agents, actions, allowed_user_urls=allowed_urls,
            **self.services.capability_request_bindings(),
        )
        export_catalog = resolve_admitted_export_catalog(self.services.export_catalog())
        required = {
            step["capability_id"] for step in self.record["plan"]["steps"] if step.get("enabled", True)
        }
        available = resolve_available_capability_ids(
            self.settings, allowed_ids=self.settings.get("chat_orchestration_enabled_capabilities"),
            candidate_ids=required, request_context=request_context, contract_version=2,
            export_catalog=export_catalog,
        )
        if required - set(available):
            raise HarnessExecutionError("context_unavailable")
        self._required_capabilities = required
        self._capability_context = request_context
        self._preparation_stage = "memory"
        memory = load_orchestration_memory(
            user_id, self._validate_memory(),
            build_elicitation_user_request(self.record.get("resolved_message") or user_message, answers),
            settings=self.settings, seeds=seeds, expected_audience=self.record.get("memory_audience"),
        )
        assert_current_request_sources_available(user_id)

        def resolve_step_model(step_seeds, current_settings):
            return resolve_orchestration_model(
                current_settings, user_id=user_id, seeds=step_seeds, identity_context=identity,
            )

        self._preparation_stage = "model_binding"
        try:
            if auto_routing:
                # Reauthorize every approved binding before any step, never rerouting one.
                validate_auto_bindings(plan, seeds, self.settings, resolve_step_model)
            answer_seeds = answer_selection(plan, seeds)
        except ModelCatalogError as exc:
            raise HarnessExecutionError("model_routing_changed") from exc
        self.answer_model = resolve_orchestration_model(
            self.settings, user_id=user_id, seeds=answer_seeds, identity_context=identity,
        )
        self.research_model = (
            resolve_orchestration_model(
                self.settings, user_id=user_id, seeds=seeds, planner=True, identity_context=identity,
            ) if has_planner_model_override(self.settings) else self.answer_model
        )
        invoke_prompt = build_harness_invoke_prompt(
            self.answer_model, token_usage=self.prompt_token_usage, revalidate=self._revalidate_context,
        )
        planner_client = self.research_model.as_planner_client()
        # Guard this run's private interface without replacing its attested client.
        planner_client.chat.completions.create = strict_source_authority()(
            guard_model_callable(planner_client.chat.completions.create, (), user_id),
        )
        self._preparation_stage = "context_binding"
        self.context = RunContext(
            run_id=self.record["id"], plan_id=self.record["plan"].get("plan_id"),
            conversation_id=conversation_id, user_id=user_id,
            turn_index=self.record.get("turn_index") or 0, attempt_index=self.record.get("attempt_index") or 1,
            invoke_prompt=invoke_prompt, planner_client=planner_client,
            planner_deployment=self.research_model.deployment, user_message=user_message,
            user_message_id=self.record["user_message_id"], answered_questions=answers,
            elicitation_references=seeds.get("elicitation_references") or [],
            selected_document_ids=seeds.get("document_ids") or [],
            original_seeds=self.record.get("original_seeds") or {},
            resolved_message=self.record.get("resolved_message") or user_message,
            conversation_context=snapshot, analysis_result_contexts=self.record.get("analysis_result_contexts"),
            context_message_ids=(self.record.get("request_resolution") or {}).get("message_ids"),
            allowed_user_urls=allowed_urls, revalidate_conversation_context=self._revalidate_context,
            memory_context=memory, reload_memory_context=self._reload_memory,
            doc_scope=seeds.get("doc_scope") or "all", tags=seeds.get("tags") or None,
            document_filter_mode=seeds.get("document_filter_mode") or None,
            active_group_ids=seeds.get("active_group_ids") or None,
            active_group_id=(seeds.get("active_group_ids") or [None])[0],
            active_public_workspace_id=(seeds.get("active_public_workspace_ids") or [None])[0],
            active_public_workspace_ids=seeds.get("active_public_workspace_ids") or None,
            agent_catalog=agents, action_catalog=actions,
            user_roles=identity["user_roles"], user_email=identity["user_email"],
            user_enable_agents=identity.get("user_enable_agents", True),
            gpt_model=self.answer_model.deployment,
            model_context={
                "model_id": self.answer_model.model_id, "endpoint_id": self.answer_model.endpoint_id,
                "provider": self.answer_model.provider, "model_deployment": self.answer_model.deployment,
                "user_id": user_id, "active_group_ids": seeds.get("active_group_ids") or [],
            },
            agent_execution_identity=principal, plan_contract_version=2,
        )
        self.context.prompt_token_usage = self.prompt_token_usage
        if auto_routing:
            def guarded_planner_client(model):
                client = model.as_planner_client()
                client.chat.completions.create = strict_source_authority()(
                    guard_model_callable(client.chat.completions.create, (), user_id),
                )
                return client

            def step_scope(step, target=None):
                return step_model_context(
                    step, target if target is not None else self.context,
                    settings=self._bootstrap.get_settings(), seeds=seeds,
                    resolve_model=resolve_step_model,
                    invoke_factory=lambda model: build_harness_invoke_prompt(
                        model, token_usage=self.prompt_token_usage, revalidate=self._revalidate_context,
                    ),
                    planner_client_factory=guarded_planner_client,
                )

            self.context.step_model_scope = step_scope

        def checkpoint_factory(step_id):
            return analysis_checkpoints_for_orchestration(
                user_id, conversation_id, self.record["id"], step_id,
                authorize=lambda: not self.lease.cancel_requested(),
                attempt_token=self.lease.token, store=self.services.results.store,
                resume_run_id=self.record.get("retry_of_run_id"), settings=self.settings,
            )

        self.services.bind_context(
            self.context, self.record, checkpoint_factory=checkpoint_factory,
            guard_token=self.lease.token, execution_check=self.lease.read,
        )
        self.context.export_catalog = resolve_admitted_export_catalog(self.context.export_catalog)
        self.context.external_source_preflight = _execution_bound_external_callback(
            self.context.external_source_preflight, self.lease,
        )
        self.context.external_source_admission = _execution_bound_external_callback(
            self.context.external_source_admission, self.lease,
        )
        self.context.capture_external_source_configuration = _execution_bound_external_callback(
            self.context.capture_external_source_configuration, self.lease,
        )
        assert_current_request_sources_available(user_id)
        self._preparation_stage = "prepared"

    def _initialize_delivery_resources(self, settings, services):
        # Publication uses initialized owners without model or checkpoint setup.
        import functions_orchestration_bootstrap as bootstrap
        from functions_orchestration_services import OrchestrationServices

        self._bootstrap = bootstrap
        self._delivery_only = True
        self.settings = deepcopy(bootstrap.get_settings() if settings is None else settings)
        if type(self.settings) is not dict:
            raise HarnessExecutionError("context_unavailable")
        user_id, conversation_id = self.record["user_id"], self.record["conversation_id"]
        self.services = services if services is not None else bootstrap.build_orchestration_services(
            user_id, conversation_id, settings=self.settings,
        )
        if (
            not isinstance(self.services, OrchestrationServices)
            or self.services.user_id != user_id or self.services.conversation_id != conversation_id
        ):
            raise HarnessExecutionError("context_unavailable")
        principal = capture_execution_identity(user_id, conversation_id)
        identity = bootstrap.current_execution_identity(user_id, conversation_id)
        if set(identity.get("user_roles") or []) - set(principal.roles):
            raise HarnessExecutionError("context_unavailable")
        self._required_capabilities = set()
        self._capability_context = build_capability_request_context(
            user_id, identity, self.record.get("user_message") or "", [], [],
            rendering_service=self.services.rendering,
        )
        return principal, identity

    def _read_delivery_metadata(self):
        self.lease.read()
        conversation_id = self.record["conversation_id"]
        message_id = orchestration_answer_message_id(self.record["id"])
        try:
            previous = self.lease.message_container.read_item(
                item=message_id, partition_key=conversation_id,
            )
        except CosmosResourceNotFoundError:
            previous = None
        if previous is not None:
            if (
                previous.get("role") != "assistant" or previous.get("conversation_id") != conversation_id
                or ((previous.get("metadata") or {}).get("orchestration") or {}).get("run_id") != self.record["id"]
            ):
                raise HarnessExecutionError("message_not_saved")
            self._saved_model_metadata = {
                key: previous[key] for key in _MODEL_METADATA_FIELDS
                if type(previous.get(key)) is str
            }
            self._saved_reasoning = {
                key: previous[key] for key in _REASONING_METADATA_FIELDS
                if key in previous and (previous[key] is None or type(previous[key]) is str)
            }
            self._saved_reasoning["reasoning_adjustments"] = merge_reasoning_adjustments(
                previous.get("reasoning_adjustments"), self.record.get("reasoning_adjustments"),
            )

    def _raise_delivery_infrastructure_failure(self, error, *, storage_required=False):
        if isinstance(error, HarnessExecutionError) and error.retryable:
            raise error
        if _is_invocation_cancellation(error):
            return
        # Rendering owns the shared cause-chain distinction between a missing or
        # denied source and unavailable storage, screening, or configuration.
        from functions_orchestration_external_configuration import ExternalConfigurationServiceError
        from functions_orchestration_external_identity import ExternalIdentityServiceError
        from functions_orchestration_output_store import OutputError, OutputStorageError
        from functions_orchestration_rendering import (
            output_failure, raise_output_read_infrastructure_failure,
        )

        for failure in _known_failure_chain(error):
            if isinstance(failure, OutputStorageError) or (
                isinstance(failure, CheckpointError) and failure.code == "checkpoint_storage_unavailable"
            ):
                raise HarnessExecutionError("message_not_saved", retryable=True) from failure
        external_service_errors = (ExternalIdentityServiceError, ExternalConfigurationServiceError)
        if isinstance(error, external_service_errors):
            raise HarnessExecutionError("message_not_saved", retryable=error.retryable) from error
        try:
            raise_output_read_infrastructure_failure(error)
        except Exception as infrastructure_error:
            continuing = bool(
                self.lease.claim_id
                and (self.record.get("continuation_submission") or {}).get("claim_id") == self.lease.claim_id
            )
            # Preserve normal model/step failure handling, but never label
            # uncertain authority (including wrapped source reads) as denial.
            if (
                not self._delivery_only
                and self.checkpoint_factory is None
                and not continuing and not storage_required
                and not isinstance(infrastructure_error, (
                    *external_service_errors, ScreeningError, ResultUnavailableError, OutputError,
                ))
                and not isinstance(error, PermissionError)
            ):
                return
            if isinstance(infrastructure_error, external_service_errors):
                retryable = infrastructure_error.retryable
            else:
                _, retryable = output_failure(infrastructure_error)
            raise HarnessExecutionError("message_not_saved", retryable=retryable) from infrastructure_error

    def _initialize_delivery(self, settings, services):
        if self.record.get("status") not in {"waiting", "completed", "failed", "cancelled"}:
            raise HarnessExecutionError("result_not_ready")
        if (
            not self.record.get("started_at") or not self.record.get("execution_deadline_at")
            or not self.record.get("execution_binding")
        ):
            raise HarnessExecutionError("checkpoint_unavailable")
        deadline = datetime.fromisoformat(self.record["execution_deadline_at"])
        if deadline.tzinfo is None:
            raise HarnessExecutionError("checkpoint_invalid")
        if self.record["status"] == "completed":
            states = {
                step["step_id"]: step["status"] for step in self.record.get("execution_steps") or []
            }
            required = [
                step for step in self.record["plan"]["steps"]
                if step.get("enabled", True) and not step.get("optional", False)
            ] or [step for step in self.record["plan"]["steps"] if step.get("enabled", True)]
            if self.record.get("pending_results") or any(
                states.get(step["step_id"]) != "completed" for step in required
            ):
                raise HarnessExecutionError("result_not_ready")
        principal, identity = self._initialize_delivery_resources(settings, services)
        self._read_delivery_metadata()
        try:
            snapshot = self._revalidate_context()
        except Exception as exc:
            self._raise_delivery_infrastructure_failure(exc)
            self._delivery_context_denied = _failure(exc)["code"] == "context_unavailable"
            raise
        conversation = self._read_conversation()
        user_id, conversation_id = self.record["user_id"], self.record["conversation_id"]
        seeds = self.record.get("seeds") or {}
        tasks = self.record.get("task_results") or {}
        pending = self.record.get("pending_results") or {}
        if type(tasks) is not dict or type(pending) is not dict:
            raise HarnessExecutionError("checkpoint_invalid")
        self.context = RunContext(
            run_id=self.record["id"], plan_id=self.record["plan"].get("plan_id"),
            conversation_id=conversation_id, user_id=user_id,
            attempt_index=self.record.get("attempt_index") or 1,
            turn_index=self.record.get("turn_index") or 0,
            user_message=self.record.get("user_message") or "",
            user_message_id=self.record.get("user_message_id"),
            resolved_message=self.record.get("resolved_message") or self.record.get("user_message"),
            answered_questions=self.record.get("answered_questions") or [],
            conversation_context=snapshot, original_seeds=self.record.get("original_seeds") or {},
            elicitation_references=seeds.get("elicitation_references") or [],
            selected_document_ids=seeds.get("document_ids") or [],
            doc_scope=seeds.get("doc_scope") or "all", tags=seeds.get("tags") or None,
            document_filter_mode=seeds.get("document_filter_mode") or None,
            active_group_ids=seeds.get("active_group_ids") or None,
            active_group_id=(seeds.get("active_group_ids") or [None])[0],
            active_public_workspace_ids=seeds.get("active_public_workspace_ids") or None,
            active_public_workspace_id=(seeds.get("active_public_workspace_ids") or [None])[0],
            memory_context={
                "audience": validate_memory_audience(
                    conversation, user_id, self.record.get("memory_audience"),
                ),
                "scope": deepcopy(self.record.get("memory_scope")),
            },
            user_roles=identity.get("user_roles") or [], user_email=principal.email,
            user_enable_agents=False, agent_execution_identity=principal,
            plan_contract_version=2, result_service=self.services.results,
            task_results={name: TaskResult.from_dict(value) for name, value in tasks.items()},
            execution_deadline_at=self.record["execution_deadline_at"],
        )
        self.context.pending_results = deepcopy(pending)
        response = None
        if self.record["plan"].get("final_response"):
            binding = InputBinding.from_dict(self.record["plan"]["final_response"])
            if binding.existing_result is not None:
                response = ResultRef.from_dict(
                    (self.record.get("result_aliases") or {})[binding.existing_result],
                )
            else:
                task = self.context.task_results.get(binding.step_id)
                if task is not None and task.status in {"complete", "partial"}:
                    response = task.output(binding.output_name)
        if self.record.get("final_response") and (
            response is None or response.to_dict() != self.record["final_response"]
        ):
            raise HarnessExecutionError("recovery_changed")
        return {
            **deepcopy(self.record),
            "final_response": response.to_dict() if response is not None else None,
        }

    def _finalize_delivery_failure(self, failure_code):
        current = self.lease.read()
        if failure_code not in _DELIVERY_FAILURE_CODES:
            raise HarnessExecutionError("result_invalid")
        if failure_code == "user_cancelled" and not (
            current.get("cancellation_requested_at") or current.get("status") == "cancelled"
        ):
            raise HarnessExecutionError("result_not_ready")
        if failure_code == "run_timeout":
            if not current.get("started_at") or not current.get("execution_deadline_at"):
                raise HarnessExecutionError("checkpoint_unavailable")
            try:
                deadline = datetime.fromisoformat(current["execution_deadline_at"])
            except (ValueError, TypeError) as exc:
                raise HarnessExecutionError("checkpoint_invalid") from exc
            if deadline.tzinfo is None:
                raise HarnessExecutionError("checkpoint_invalid")
            states = {
                step["step_id"]: step["status"] for step in current.get("execution_steps") or []
            }
            enabled = [step for step in current["plan"]["steps"] if step.get("enabled", True)]
            required = [step for step in enabled if not step.get("optional", False)] or enabled
            if deadline > datetime.now(timezone.utc) or all(
                states.get(step["step_id"]) == "completed" for step in required
            ):
                raise HarnessExecutionError("result_not_ready")
        self.context = None
        return self._finish(
            {"capabilities_used": current.get("capabilities_used") or []},
            HarnessExecutionError(failure_code),
        )

    def _send(self, frame):
        if callable(self._emit):
            try:
                self._emit(frame)
            except (Exception, GeneratorExit) as exc:
                # A transport loss cannot cancel publication by the owning worker.
                self._emit = None
                _log_failure("Execution progress delivery stopped.", self.record, exc)

    def _progress(self, event):
        if type(event) is not dict or event.get("type") != "step":
            return
        extra = {
            key: event[key] for key in (
                "failure", "reused", "reused_from_run_id", "checkpoint_available", "role", "model_binding",
            ) if key in event
        }
        if event.get("role") == "render":
            extra["outputs"] = [
                output for output in self.services.rendering.list_public_outputs(self.record["id"])
                if output["step_id"] == event.get("step_id")
            ]
        self._send(build_step_event(
            event.get("step_id"), event.get("phase"), event.get("summary") or "",
            event.get("step_index"), event.get("capability_id"), **extra,
        ))

    def _persist(self, record_type, payload):
        if record_type == "run":
            try:
                assert_current_request_sources_available(self.record["user_id"])
            except (ScreeningError, LookupError, PermissionError) as error:
                # A caught service outage is not a durable failed/empty-source run.
                # Classify through the initialized renderer without hiding the
                # original cause behind another wrapper at the checkpoint boundary.
                from functions_orchestration_rendering import raise_output_read_infrastructure_failure

                raise_output_read_infrastructure_failure(error)
            updates = {
                **{key: value for key, value in payload.items() if key != "run_id"},
                "harness_prompt_token_usage": _usage(self.prompt_token_usage),
            }
            if "started_at" in updates and self.record.get("started_at"):
                updates["started_at"] = self.record["started_at"]
            if "token_usage" in payload:
                updates["harness_step_token_usage"] = _usage(payload["token_usage"])
            self.lease.update(updates)

    def _reasoning(self):
        if self._delivery_only:
            return {
                **deepcopy(self._saved_reasoning),
                "reasoning_adjustments": merge_reasoning_adjustments(
                    self._saved_reasoning.get("reasoning_adjustments"),
                    self.record.get("reasoning_adjustments"),
                ),
            }
        reasoning = build_model_reasoning_metadata(self.answer_model)
        reasoning["reasoning_adjustments"] = merge_reasoning_adjustments(
            self.record["plan"].get("reasoning_adjustments"), reasoning.get("reasoning_adjustments"),
            build_model_reasoning_metadata(self.research_model, "planner").get("reasoning_adjustments")
            if self.research_model is not self.answer_model else [],
        )
        return reasoning

    def _file_state(self):
        if self.services is None or not any(
            step.get("enabled", True) and step["capability_id"] == "render_file"
            for step in self.record["plan"]["steps"]
        ):
            return [], []
        try:
            return (
                self.services.rendering.list_public_outputs(self.record["id"]),
                self.services.rendering.committed_artifacts(self.record["id"]),
            )
        except PermissionError as exc:
            if type(exc) is not PermissionError or exc.__cause__ is not None:
                raise
            # A failed observation is not the facade's verified unavailable-file projection.
            raise HarnessExecutionError("message_not_saved", retryable=True) from exc

    def _read_image_asset(self, reference):
        """A generated image's retained descriptor, reauthorized for the current owner."""
        reader = self.services.results.open_result(reference, require_current_sources=True)
        value = read_complete_input(reader)
        reader.recheck()
        return value

    def _validate_citations(self, citations):
        document_ids = sorted({
            citation["document_id"] for citation in citations
            if isinstance(citation, dict) and citation.get("document_id")
        })
        if not document_ids:
            return
        manifest = resolve_context_source_manifest(
            self.context, document_ids, settings=self._bootstrap.get_settings(),
            user_id=self.record["user_id"],
        )
        if set(document_ids) - {
            source.get("document_id") for source in manifest
            if source.get("authorization_status") == "authorized"
        }:
            raise HarnessExecutionError("context_unavailable")

    def _touch_conversation(self, documents):
        # Cache/citation integrations belong after application initialization and
        # never determine whether the authoritative assistant message committed.
        from functions_citation_tracking import merge_cited_documents_into_conversation
        from functions_conversation_cache import invalidate_conversation_cache_for_item

        try:
            for _ in range(3):
                conversation = self._read_conversation()
                if documents:
                    merge_cited_documents_into_conversation(conversation, documents)
                conversation["last_updated"] = _now_iso()
                try:
                    saved = self._bootstrap.config.cosmos_conversations_container.replace_item(
                        item=conversation["id"], body=conversation, etag=conversation["_etag"],
                        match_condition=MatchConditions.IfNotModified,
                    )
                except CosmosAccessConditionFailedError:
                    continue
                invalidate_conversation_cache_for_item(saved, reason="orchestration_completed")
                break
        except Exception as exc:
            _log_failure("The saved conversation index could not be refreshed.", self.record, exc)

    def _finalize(self, result, error, *, refreshes=0):
        # Recovery is an application-owned store dependency, not an import-time dependency.
        from functions_orchestration_recovery import public_execution_fields

        if refreshes > 2:
            raise HarnessExecutionError("message_not_saved")
        current = self.lease.read()
        if error is not None:
            self._raise_delivery_infrastructure_failure(error)
        result = result if type(result) is dict else {}
        failures = [safe_failure(value) for value in result.get("failures") or []]
        status = result.get("status", "failed")
        if status not in {"completed", "waiting", "failed", "cancelled"}:
            error = error or HarnessExecutionError("result_invalid")
        prepared, citations, reader = "", [], None
        assets = {}
        if error is None:
            try:
                self._revalidate_context()
                if result.get("final_response") and not current.get("cancellation_requested_at"):
                    reference = ResultRef.from_dict(result["final_response"])
                    reader = self.services.results.open_result(
                        reference, allow_partial=True, require_current_sources=True,
                    )
                    prepared = read_complete_input(reader)
                    if type(prepared) is not str:
                        raise HarnessExecutionError("result_invalid")
                    reader.recheck()
                    if self._delivery_only:
                        citations = read_result_document_citations(self.context, reference)
                if not self._delivery_only:
                    citations = result.get("citations") or []
                self._validate_citations(citations)
                if self.context is not None and not current.get("cancellation_requested_at"):
                    assets = generated_image_assets(self.context.task_results, self._read_image_asset)
            except Exception as exc:
                self._raise_delivery_infrastructure_failure(exc)
                _log_failure("Execution context could not be reauthorized.", self.record, exc)
                error, prepared, citations, assets = exc, "", [], {}
        if error is not None:
            failure = _failure(error)
            status = "cancelled" if failure["code"] == "user_cancelled" else "failed"
            failures.append(failure)
        if status == "cancelled" or current.get("cancellation_requested_at") or current.get("status") == "cancelled":
            status, prepared, citations, assets = "cancelled", "", [], {}
            if not any(value["code"] == "user_cancelled" for value in failures):
                failures.append(build_failure("user_cancelled"))
        # Generated images appear in the answer where its content placed them.
        prepared = project_generated_images(prepared, assets)

        outputs, artifacts = self._file_state()
        delivered = {artifact["output_id"] for artifact in artifacts}
        ready = bool(delivered)
        required_steps = {
            step["step_id"] for step in self.record["plan"]["steps"]
            if step.get("enabled", True) and not step.get("optional", False)
        }
        if not required_steps:
            required_steps = {
                step["step_id"] for step in self.record["plan"]["steps"] if step.get("enabled", True)
            }
        if status == "completed" and any(
            output["step_id"] in required_steps
            and (
                output["state"] != "completed" or output.get("available") is False
                or output["output_id"] not in delivered
            )
            for output in outputs
        ):
            status = "failed"
            failures.append(build_failure("result_unavailable"))
        outcome = status if status in {"waiting", "cancelled", "completed"} else (
            "partial" if ready or prepared or result.get("outcome") == "partial" else "failed"
        )
        if status == "failed" and not failures:
            failures.append(build_failure("execution_interrupted"))
        content = [prepared] if prepared else []
        files = _delivery_summary(outputs, artifacts)
        if files:
            content.append(files)
        if status not in {"waiting", "cancelled"}:
            # Deterministic, model-free: what the user asked for and did not receive.
            notes = delivery_notes(
                self.record["plan"],
                {step.get("step_id"): step.get("status") for step in current.get("execution_steps") or []},
                file_steps_with_outputs={output["step_id"] for output in outputs},
            )
            if notes:
                content.append(notes)
        if status == "waiting":
            content.append(build_failure("result_not_ready")["message"])
        elif status in {"failed", "cancelled"}:
            content.append(failure_explanation(failures, partial=outcome == "partial", cancelled=status == "cancelled"))
        elif not content:
            content.append("The requested content is prepared. No downloadable files were created.")
        answer = "\n\n".join(content)
        # Durable orchestration replies use chat's output checkpoint before persistence.
        from functions_chat_content_checks import (
            CHECK_METADATA, attach_chat_check, check_chat_content, retract_message_content,
            strip_private_chat_checks,
        )

        output_check = check_chat_content(
            answer, "chat_output", user_id=self.record["user_id"], settings=self.settings,
        )
        if output_check.blocked:
            answer, citations = output_check.notice, []
        if self._delivery_only:
            if "harness_step_token_usage" in self.record:
                combined_usage = _usage(self.prompt_token_usage, self.record["harness_step_token_usage"])
            elif not self.record.get("execution_binding"):
                combined_usage = _usage(self.prompt_token_usage)
            else:
                combined_usage = _usage(self.record.get("token_usage"))
        else:
            combined_usage = _usage(
                self.prompt_token_usage,
                result.get("token_usage", self.context.token_usage if self.context is not None else {}),
            )
        reasoning = self._reasoning()
        model_metadata = (
            self.answer_model.metadata() if self.answer_model is not None
            else deepcopy(self._saved_model_metadata)
        )
        message_id = orchestration_answer_message_id(self.record["id"])
        timestamp = current.get("assistant_message_created_at") or _now_iso()
        # Validation may fail before checkpoint restoration populates this context.
        has_execution_state = self.context is not None and "task_results" in result
        updates = {
            "status": status, "outcome": outcome, "message": answer,
            "failure": failures[0] if failures else None, "failures": failures,
            "error": failures[0]["message"] if failures else None,
            "completed_at": None if status == "waiting" else _now_iso(),
            "execution_deadline_at": current.get("execution_deadline_at"),
            "pending_results": deepcopy(
                self.context.pending_results if has_execution_state else current.get("pending_results") or {},
            ),
            "task_results": (
                {name: task.to_dict() for name, task in self.context.task_results.items()}
                if has_execution_state else deepcopy(current.get("task_results") or {})
            ),
            "outputs": outputs, "artifacts": artifacts, "citations": deepcopy(citations),
            "token_usage": combined_usage,
            "harness_prompt_token_usage": _usage(self.prompt_token_usage),
            "reasoning_adjustments": reasoning["reasoning_adjustments"],
            "assistant_message_created_at": timestamp,
            "message_saved": False, "finalization_status": "pending",
        }
        if not self._delivery_only:
            updates["harness_step_token_usage"] = _usage(
                result.get("token_usage", self.context.token_usage if self.context is not None else {}),
            )
        if output_check.blocked:
            # The executor's provisional summary cannot retain text the checkpoint removed.
            updates["summary"] = answer
        current = self.lease.update(updates)
        public = public_execution_fields({
            **current, "execution_lease": None, "finalization_status": "saved",
            "assistant_message_id": message_id, "message_saved": True,
        })
        summary = summarize_plan(self.record["plan"])
        summary.update(status=status, capabilities_used=list(result.get("capabilities_used") or []))
        # The answer owns the list of image messages it shows. Images are never re-linked:
        # a retry lists the images it reused from an earlier attempt, and that attempt's
        # answer keeps showing them too.
        generated_images = [
            {"visual_id": asset_id, "message_id": asset["message_id"]}
            for asset_id, asset in assets.items()
        ]
        metadata = {
            "orchestration": {
                "run_id": self.record["id"], "turn_id": self.record.get("turn_id"),
                "plan_summary": summary, **public, "status": status, "outputs": outputs,
                **({"generated_images": generated_images} if generated_images else {}),
            },
            "token_usage": combined_usage, **reasoning,
        }
        documents, web, tools = _partition_citations(citations)
        document = {
            "id": message_id, "conversation_id": self.record["conversation_id"],
            "role": "assistant", "content": answer, "timestamp": timestamp,
            "metadata": metadata, **model_metadata, **reasoning,
            "hybrid_citations": documents, "web_search_citations": web, "agent_citations": tools,
            "generated_artifacts": artifacts, "augmented": bool(documents or web or tools),
        }
        if output_check.status != "not_required":
            document = (
                retract_message_content(document, output_check) if output_check.blocked
                else attach_chat_check(document, output_check)
            )
        latest = self.lease.read()
        if latest.get("cancellation_requested_at") and status != "cancelled":
            return self._finalize(result, error, refreshes=refreshes + 1)
        try:
            # The lease reauthorizes ownership even when bootstrap failed before
            # initialization. Such failures publish no prepared content or sources.
            if self._bootstrap is not None:
                self._read_conversation()
            if error is None:
                self._revalidate_context()
                if reader is not None:
                    reader.recheck()
                self._validate_citations(citations)
            latest_outputs, latest_artifacts = self._file_state()
        except Exception as exc:
            self._raise_delivery_infrastructure_failure(exc)
            if error is not None:
                raise
            return self._finalize(result, exc, refreshes=refreshes + 1)
        if latest_outputs != outputs or latest_artifacts != artifacts:
            return self._finalize(result, error, refreshes=refreshes + 1)
        self.lease.publish_message(document)
        saved = self.lease.message_container.read_item(
            item=message_id, partition_key=self.record["conversation_id"],
        )
        if fingerprint({key: value for key, value in saved.items() if not key.startswith("_")}) != fingerprint(document):
            raise HarnessExecutionError("message_not_saved")
        # Publication preserves an administrator's earlier retraction of this reply.
        blocked = document.get("role") == "safety"
        if blocked:
            answer, documents, web, tools = document["content"], [], [], []
        checked = CHECK_METADATA in (document.get("metadata") or {})
        self.lease.update({
            "assistant_message_id": message_id, "message_saved": True, "finalization_status": "saved",
            "chat_content_checked_output": checked, "chat_content_output_pending": False,
        })
        if checked:
            try:
                from functions_chat_content_review import record_chat_content_incident

                record_chat_content_incident(document, self.record["user_id"])
            except Exception as exc:
                _log_failure("A chat content incident could not be recorded.", self.record, exc)
        if self._bootstrap is not None:
            self._touch_conversation(documents)
        finalized = self.lease.close(release=True)
        self._released = True
        self._final_record = finalized
        public = public_execution_fields(finalized)
        frame = build_run_done_event(
            self.record["conversation_id"], message_id=message_id, run_id=self.record["id"],
            turn_id=self.record.get("turn_id"), full_content=answer, citations=documents,
            web_citations=web, agent_citations=tools, artifacts=[] if blocked else artifacts,
            outputs=[] if blocked else outputs,
            plan_summary=summary, status=status, outcome=outcome,
            attempt_index=public["attempt_index"], retry_of_run_id=public["retry_of_run_id"],
            failure=updates["failure"], failures=failures, recovery=public["recovery"],
            message_saved=True, finalization_status=public.get("finalization_status"),
            generated_images=[] if blocked else generated_images,
            **model_metadata, **reasoning,
        )
        payload = json.loads(frame.partition("data:")[2].strip())
        payload.update({
            "metadata": document.get("metadata") or {}, "role": document["role"],
            "replace_content": True, "blocked": blocked,
        })
        return [build_content_event(answer), serialize_sse(strip_private_chat_checks(payload))]

    def _finish(self, result, error):
        try:
            self._frames = self._finalize(result, error)
        except Exception as exc:
            self._raise_delivery_infrastructure_failure(exc)
            _log_failure("Headless message publication was not confirmed.", self.record, exc)
            failure = build_failure("message_not_saved")
            self._final_record = None
            try:
                self._final_record = self.lease.update({
                    "status": "failed", "outcome": "failed", "failure": failure,
                    "failures": [failure], "error": failure["message"],
                    "completed_at": _now_iso(), "message_saved": False,
                    "finalization_status": "failed", "recovery_blocked_code": "message_not_saved",
                })
            except Exception as persistence_error:
                _log_failure("Publication failure could not be recorded.", self.record, persistence_error)
            self._frames = [
                build_error_event(failure["message"], self.record["conversation_id"]),
                build_run_done_event(
                    self.record["conversation_id"], run_id=self.record["id"],
                    turn_id=self.record.get("turn_id"), status="failed", outcome="failed",
                    attempt_index=self.record.get("attempt_index") or 1,
                    retry_of_run_id=self.record.get("retry_of_run_id"),
                    failure=failure, failures=[failure], message_saved=False,
                    finalization_status="failed", outputs=[],
                ),
            ]
        return list(self._frames)

    def _preparation_error(self, error):
        _log_failure(
            "Headless execution preparation failed.", self.record, error,
            stage=self._preparation_stage,
        )
        try:
            # A partially bound context has not restored durable producer state.
            self.context = None
            frames = self._finish(
                {"token_usage": self.record.get("harness_step_token_usage") or {}}, error,
            )
            return HarnessExecutionError(
                _failure(error)["code"], final_frames=frames,
                durable_status=(self._final_record or {}).get("status"),
            )
        finally:
            self.close()

    @strict_source_authority()
    def execute(self, emit=None):
        """Emit progress only, returning final frames once publication is resolved."""
        if not self._execution_lock.acquire(blocking=False):
            raise HarnessExecutionError("ownership_lost")
        try:
            if self._frames is not None:
                return list(self._frames)
            if self._closed or self.context is None:
                raise HarnessExecutionError("ownership_lost")
            self._emit = emit
            checkpoint_factory = self.checkpoint_factory
            if checkpoint_factory is None:
                # Recovery requires the initialized application containers.
                from functions_orchestration_recovery import ExecutionCheckpoints

                checkpoint_factory = ExecutionCheckpoints

            def create_checkpoints(context):
                checkpoints = checkpoint_factory(self.record, context, self.settings, self.lease)
                if checkpoints is None:
                    raise HarnessExecutionError("checkpoint_unavailable")
                return checkpoints

            result, error = None, None
            try:
                self._validate_capabilities()
                self._mark_output_check_pending()
                adjustments = self._reasoning()["reasoning_adjustments"]
                if adjustments:
                    self._send(build_reasoning_adjustment_event(adjustments))
                result = execute_plan(
                    self.record["plan"], self.context, settings=self.settings,
                    user_id=self.record["user_id"], emit=self._progress,
                    cancel_requested=self.lease.cancel_requested, persist=self._persist,
                    checkpoints=create_checkpoints,
                )
                assert_current_request_sources_available(self.record["user_id"])
            except Exception as exc:
                error = exc
                _log_failure("Headless execution did not complete.", self.record, exc)
            return self._finish(result, error)
        finally:
            self.close()
            self._execution_lock.release()

    def _mark_output_check_pending(self):
        """Keep run files private until a check-before-display reply is published."""
        from functions_chat_content_checks import enabled_chat_scanners

        if (
            self.settings.get("chat_content_output_mode") == "check_before_display"
            and enabled_chat_scanners(self.settings, "chat_output")
        ):
            self.lease.update({"chat_content_output_pending": True})

    def close(self):
        """Idempotently close model clients and stop/release only our own heartbeat."""
        if self._closed:
            return
        self._closed = True
        seen = set()
        for model in (self.research_model, self.answer_model):
            if model is not None and id(model) not in seen:
                seen.add(id(model))
                try:
                    model.close()
                except Exception as exc:
                    _log_failure("An execution model could not be closed.", self.record, exc)
        try:
            self.lease.close(release=not self._released)
            self._released = True
        except Exception as exc:
            _log_failure("An execution lease could not be released.", self.record, exc)


def _claimed_harness_execution(record, lease, *, delivery_only=False, checkpoint_factory=None):
    if type(record) is not dict or is_legacy_plan(record.get("plan")):
        # A plan from the removed legacy contract is never executed or published.
        error = HarnessExecutionError(LEGACY_PLAN_CODE if type(record) is dict else "context_unavailable")
        _log_failure("Execution claim could not be admitted.", record, error, stage="claim_validation")
        raise error
    try:
        plan_contract_version(record["plan"])
    except PlanValidationError as exc:
        raise HarnessExecutionError("context_unavailable") from exc
    if lease is None:
        raise HarnessExecutionError("ownership_lost")
    # The concrete lease imports the application-owned run store. It is not a
    # duck-typed token source, and no replacement guard may be minted here.
    from functions_orchestration_recovery import ExecutionLease

    if (
        not isinstance(lease, ExecutionLease)
        or any(
            getattr(lease, lease_key) != record.get(record_key)
            for lease_key, record_key in (
                ("run_id", "id"), ("user_id", "user_id"), ("conversation_id", "conversation_id"),
            )
        )
    ):
        raise HarnessExecutionError("ownership_lost")
    execution = HarnessExecution(record, lease)
    execution._delivery_only = delivery_only
    execution.checkpoint_factory = checkpoint_factory
    accepted = False
    try:
        current = lease.read()
        if (
            any(current.get(key) != record.get(key) for key in ("id", "user_id", "conversation_id", "plan"))
            or current.get("attempt_index", 1) != record.get("attempt_index", 1)
            or lease.stopped.is_set() or lease.message_container is None
            or current.get("status") in {"deleted", "superseded"}
            or current.get("superseded_by_run_id") or current.get("outputs_deleted")
        ):
            raise HarnessExecutionError("ownership_lost")
        execution.record = deepcopy(current)
        execution.prompt_token_usage = _usage(
            current.get("harness_prompt_token_usage", current.get("planning_token_usage")),
        )
        accepted = True
        if lease.thread is None:
            execution._preparation_stage = "lease_start"
            lease.start()
        return execution
    except Exception as exc:
        if accepted and not delivery_only:
            raise execution._preparation_error(exc) from exc
        _log_failure("Execution claim could not be read.", record, exc, stage="claim_read")
        execution.close()
        execution._raise_delivery_infrastructure_failure(exc)
        raise HarnessExecutionError(_failure(exc)["code"]) from exc
    except BaseException:
        execution.close()
        raise


@strict_source_authority()
def prepare_harness_execution(
    record, *, settings=None, identity_context=None, execution_identity=None, lease=None,
    checkpoint_factory=None,
):
    """Prepare a saved attempt, finalizing definite failures but propagating uncertain authority."""
    execution = _claimed_harness_execution(record, lease, checkpoint_factory=checkpoint_factory)
    try:
        if checkpoint_factory is not None and not callable(checkpoint_factory):
            raise HarnessExecutionError("checkpoint_unavailable")
        execution._initialize(settings, identity_context, execution_identity)
        return execution
    except Exception as exc:
        raise execution._preparation_error(exc) from exc
    except BaseException:
        execution.close()
        raise


def refresh_harness_delivery(record, *, services=None, settings=None, lease=None):
    """Publish a renderer-only tick after guarded runtime reconciliation.

    The caller renders due outputs and reconciles execution/checkpoint state first.
    The authoritative leased run must already have status waiting, completed,
    failed or cancelled, with its original deadline, task_results, pending_results
    and execution_steps. A merely running claim is not a reconciled outcome.

    No model is resolved or called, no memory is recalled, and no producer, native
    poll, renderer or execute_plan is invoked. This updates only delivery facts and
    the stable assistant message, then closes/releases the supplied owning lease.
    Definite context denial produces a safe failed message without prepared text.
    Infrastructure failures raise a safe error (retryable for transient faults)
    and do not turn the authoritative outcome into a source-denial failure.
    """
    execution = _claimed_harness_execution(record, lease, delivery_only=True)
    try:
        result = execution._initialize_delivery(settings, services)
        return execution._finish(result, None)
    except Exception as exc:
        _log_failure("Delivery refresh could not be prepared.", execution.record, exc)
        execution._raise_delivery_infrastructure_failure(exc)
        if execution._delivery_context_denied:
            try:
                return execution._finalize_delivery_failure("context_unavailable")
            except Exception as publication_error:
                execution._raise_delivery_infrastructure_failure(publication_error)
                raise HarnessExecutionError(_failure(publication_error)["code"]) from publication_error
        raise HarnessExecutionError(_failure(exc)["code"]) from exc
    finally:
        execution.close()


def finalize_harness_failure(record, *, failure_code, services=None, settings=None, lease=None):
    """Finalize a known terminal condition without restoring or executing the DAG.

    The caller supplies a real CAS-claimed same-attempt lease and one of
    run_timeout, user_cancelled, or context_unavailable. Timeout and cancellation
    are verified against current durable state; timeout requires unfinished required
    work. context_unavailable is only for a positively established authorization or
    context denial, never a backend outage.
    Deleted/superseded/unowned runs cannot publish. Transient infrastructure errors
    raise HarnessExecutionError(retryable=True) rather than inventing an outcome.

    Existing task/pending refs, producer identities, deadline and usage survive.
    The returned final SSE frames describe the same stable assistant message.
    Models, memory recall, producers, native polling and rendering are not invoked.
    """
    if type(failure_code) is not str or failure_code not in _DELIVERY_FAILURE_CODES:
        raise HarnessExecutionError("result_invalid")
    execution = _claimed_harness_execution(record, lease, delivery_only=True)
    try:
        execution._initialize_delivery_resources(settings, services)
        execution._read_delivery_metadata()
        return execution._finalize_delivery_failure(failure_code)
    except Exception as exc:
        _log_failure("Known delivery failure could not be finalized.", execution.record, exc)
        execution._raise_delivery_infrastructure_failure(exc)
        raise HarnessExecutionError(_failure(exc)["code"]) from exc
    finally:
        execution.close()
