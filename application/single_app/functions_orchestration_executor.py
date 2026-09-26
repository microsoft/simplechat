# functions_orchestration_executor.py

"""
The deterministic step engine: it runs a validated plan, and it is the only thing that does.

The planner writes a plan and never touches it again; this module walks that plan's
Gather, Reason and Render steps in their compiled dependency order, calls one adapter per
step, and retains each step's typed results so later steps read them only through their
named inputs. Nothing here chooses *what* to do -- that was the planner's job and the
schema already validated the result -- so the executor's whole responsibility is to run the
plan faithfully and to fail safely when the world has changed underneath it.

Properties worth stating, because they are the reason this is an engine and not a loop:

**Required work fails closed.** A step whose required input did not complete is not run,
and a required step that fails fails the run. A producer that feeds only optional inputs
can fail without failing the plan; the consumer discloses what could not be gathered.

**Access is re-checked when work runs, not trusted from plan time.** Every step resolves
its authorized sources again and compares them with the snapshot captured when execution
began, so a document whose access was revoked, or which changed, stops the work that
depended on it instead of reaching an answer the user is no longer allowed to see.

**Progress is durable.** Each step boundary can be checkpointed, so a retried attempt
reuses committed results instead of repeating work, and read-only gathering retries once
after a transient provider failure.

Re-planning is *surfaced, not performed*. A step can hand back a ``replan_hint``; the executor
collects those and returns them, bounded by the replan budget, but it never calls the planner
itself.

A plan from the removed legacy contract is refused before anything runs.

Version: 0.261.139
"""

import logging
from contextlib import nullcontext
from agent_execution_context import DelegationBudget
import re
import time
from copy import copy, deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from werkzeug.utils import secure_filename

from content_screening.access import assert_current_request_sources_available
from content_screening.contracts import ScreeningError
from functions_appinsights import log_event
from functions_mixed_source_orchestration import (
    AUTHORIZATION_STATUS_AUTHORIZED,
    MixedSourceCancellationError,
)
from functions_orchestration_adapters import (
    get_adapter as _default_get_adapter,
    resolve_context_source_manifest,
)
from functions_orchestration_context import (
    ElicitationContextError,
    build_elicitation_user_request,
    resolve_elicitation_references,
)
from functions_orchestration_deliverables import explicit_image_shortfalls
from functions_orchestration_registry import (
    CAPABILITY_TABULAR_ANALYZE, DEPENDENCY_PLAN_CONTRACT_VERSION,
    admitted_export_pairs, get_capability,
    resolve_available_capability_ids,
)
from functions_orchestration_result_contracts import (
    InputBinding, ProducerIdentity, ResultContractError, ResultRef, TaskResult, digest,
)
from functions_orchestration_result_runtime import (
    decode_step_result, raise_source_service_failure, read_complete_input, read_result_document_citations,
    require_result_service, resolve_step_inputs,
    retain_gather_result, validate_task_diagnostics, validate_task_outputs,
)
from functions_orchestration_results import ResultUnavailableError
from functions_workflow_result_store import WorkflowResultIntegrityError, WorkflowResultStorageUnavailableError
from functions_orchestration_schema import (
    PLAN_STATUS_CANCELLED,
    PLAN_STATUS_COMPLETED,
    PLAN_STATUS_FAILED,
    PLAN_STATUS_RUNNING,
    PLAN_STATUS_WAITING,
    STEP_STATUS_CANCELLED,
    STEP_STATUS_COMPLETED,
    STEP_STATUS_FAILED,
    STEP_STATUS_PENDING,
    STEP_STATUS_RUNNING,
    STEP_STATUS_WAITING,
    STEP_STATUS_PARTIAL,
    STEP_STATUS_SKIPPED,
    build_step_result,
    build_failure,
    safe_failure,
    failure_from_exception,
    failure_explanation,
    failure_is_transient,
    optional_input_producers,
    plan_contract_version,
    validate_plan,
)
from functions_orchestration_checkpoints import (
    CheckpointError, restore_context, step_input_fingerprint,
)
from functions_orchestration_timing import (
    initial_execution_deadline, positive_setting_int as _setting_int,
)

_LOG_PREFIX = '[ORCHESTRATION_EXECUTOR]'

# One retry of a read-only step after a transient provider failure, after this pause. The
# pause is interruptible and never extends past the step or run deadline.
_TRANSIENT_RETRY_DELAY_SECONDS = 1.5
_TRANSIENT_RETRY_SUMMARY = 'Retrying after a temporary service error.'


def _should_retry_transient(step, result, step_cancel):
    """Whether a failed read-only step should get its single transient-failure retry."""
    capability = get_capability(step.get('capability_id'))
    if not capability or not capability.get('retry_on_transient'):
        return False
    if not isinstance(result, dict) or result.get('status') != STEP_STATUS_FAILED:
        return False
    if not failure_is_transient(result.get('failure')):
        return False
    return not step_cancel()


def _pause_before_retry(step_cancel, delay=None):
    """Wait for the retry delay, returning False when the step was stopped meanwhile."""
    delay = _TRANSIENT_RETRY_DELAY_SECONDS if delay is None else delay
    deadline = time.monotonic() + delay
    while time.monotonic() < deadline:
        if step_cancel():
            return False
        time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
    return not step_cancel()


def _log_transient_retry(context, step, result):
    log_event(
        f'{_LOG_PREFIX} Retrying a read-only step after a transient failure.',
        extra={
            'run_id': getattr(context, 'run_id', None), 'conversation_id': getattr(context, 'conversation_id', None),
            'step_id': step.get('step_id'), 'capability_id': step.get('capability_id'),
            'reason_code': ((result or {}).get('failure') or {}).get('code'),
            'provider_status': ((result or {}).get('failure') or {}).get('provider_status'),
        },
        level=logging.WARNING,
    )

# Budget fallbacks for when a setting is absent or unparseable. Chosen to match the shipped
# defaults in functions_settings so a missing settings dict behaves like the default config
# rather than like an unbounded run.
_DEFAULT_MAX_STEPS = 8
_DEFAULT_STEP_TIMEOUT_SECONDS = 120
_DEFAULT_MAX_REPLANS = 2


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _text(value, limit=None):
    if value is None:
        return ''
    text = str(value).strip()
    if limit is not None and len(text) > limit:
        text = text[:limit].rstrip()
    return text


def _string_list(value):
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    out = []
    seen = set()
    for item in value:
        text = _text(item)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _emit(emit, event):
    if not callable(emit):
        return
    try:
        emit(event)
    except Exception:
        # Progress is advisory; a failed emit must never break a run.
        pass


def _make_cancel_probe(cancel_requested):
    if not callable(cancel_requested):
        return lambda: False

    def _probe():
        try:
            return bool(cancel_requested())
        except Exception as exc:
            raise CheckpointError('ownership_lost') from exc

    return _probe


# --------------------------------------------------------------------------------------
# Run context
# --------------------------------------------------------------------------------------

class RunContext:
    """The retained results and ambient state one run carries as its steps execute.

    Adapters read this by duck typing -- they never import this class -- so the attribute
    names here are the actual contract with the adapters, not the constructor signature.
    ``task_results`` holds each step's typed, retained results; the per-step accumulators
    (``evidence``, ``citations``, ``artifacts``, ``notes``) are scoped to one step and become
    that step's retained result rather than being shared between steps.

    It also carries the request-scoped identity and catalog an adapter needs but cannot look
    up itself: this object is built on the request thread and then read from the executor's
    worker thread, where Flask's ``g``, ``session`` and ``current_app`` do not exist. Anything
    an adapter would otherwise have fished out of ``g`` is captured here instead.
    """

    def __init__(
        self,
        *,
        run_id=None,
        plan_id=None,
        conversation_id=None,
        user_id=None,
        turn_index=0,
        attempt_index=1,
        invoke_prompt=None,
        planner_client=None,
        planner_deployment=None,
        user_message='',
        user_message_id=None,
        answered_questions=None,
        elicitation_references=None,
        selected_document_ids=None,
        original_seeds=None,
        resolved_message=None,
        conversation_context=None,
        context_message_ids=None,
        allowed_user_urls=None,
        revalidate_conversation_context=None,
        memory_context=None,
        reload_memory_context=None,
        chat_type='personal',
        selection_mode=None,
        doc_scope='all',
        tags=None,
        document_filter_mode=None,
        active_group_ids=None,
        active_group_id=None,
        active_public_workspace_id=None,
        active_public_workspace_ids=None,
        gpt_model=None,
        model_context=None,
        request_correlation_id=None,
        durable_execution_callback=None,
        resolve_source_manifest=None,
        user_roles=None,
        user_email=None,
        agent_catalog=None,
        action_catalog=None,
        user_enable_agents=True,
        agent_execution_identity=None,
        delegation_budget=None,
        saved_analyses=None,
        analysis_result_contexts=None,
        plan_contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION,
        result_service=None,
        task_results=None,
        result_aliases=None,
        result_guard_token_for_step=None,
        result_input_fingerprint_for_step=None,
        composition_profiles=None,
        composition_profile_validator=None,
        execution_deadline_at=None,
        native_bridge_for_step=None,
        external_source_admission=None,
        external_source_preflight=None,
        capture_external_source_configuration=None,
        rendering_service=None,
        export_catalog=None,
    ):
        self.run_id = run_id
        self.plan_id = plan_id
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.turn_index = turn_index
        self.attempt_index = attempt_index
        if type(plan_contract_version) is not int or plan_contract_version != DEPENDENCY_PLAN_CONTRACT_VERSION:
            raise ResultContractError('result_version_unsupported')
        self.plan_contract_version = plan_contract_version
        self.result_service = result_service
        self.task_results = dict(task_results or {})
        self.result_aliases = dict(result_aliases or {})
        if any(type(task) is not TaskResult or key != task.producer.step_id for key, task in self.task_results.items()):
            raise ResultContractError('result_producer_invalid')
        if any(type(reference) is not ResultRef for reference in self.result_aliases.values()):
            raise ResultContractError('result_reference_untrusted')
        if result_guard_token_for_step is not None and not callable(result_guard_token_for_step):
            raise ResultContractError('result_guard_required')
        self._result_guard_token_for_step = result_guard_token_for_step
        if result_input_fingerprint_for_step is not None and not callable(result_input_fingerprint_for_step):
            raise ResultContractError('result_input_fingerprint_required')
        self._result_input_fingerprint_for_step = result_input_fingerprint_for_step
        self.composition_profiles = dict(composition_profiles or {})
        self.composition_profile_validator = composition_profile_validator
        self.execution_deadline_at = execution_deadline_at
        self.pending_results = {}
        if native_bridge_for_step is not None and not callable(native_bridge_for_step):
            raise ResultContractError('result_adapter_unavailable')
        self.native_bridge_for_step = native_bridge_for_step
        for callback in (
            external_source_admission, external_source_preflight, capture_external_source_configuration,
        ):
            if callback is not None and not callable(callback):
                raise ResultContractError('result_external_reader_required')
        self.external_source_admission = external_source_admission
        self.external_source_preflight = external_source_preflight
        self.capture_external_source_configuration = capture_external_source_configuration
        self.rendering_service = rendering_service
        self.export_catalog = deepcopy(export_catalog)

        self.invoke_prompt = invoke_prompt
        self.planner_client = planner_client
        self.planner_deployment = planner_deployment
        self.user_message = user_message
        self.answered_questions = deepcopy(answered_questions or [])
        self.resolved_message = resolved_message if resolved_message is not None else user_message
        self.user_request = build_elicitation_user_request(self.resolved_message, self.answered_questions)
        self.elicitation_references = list(elicitation_references or [])
        self.selected_document_ids = list(selected_document_ids or [])
        self.original_seeds = dict(original_seeds or {})
        self.user_message_id = user_message_id
        self.conversation_context = deepcopy(conversation_context or {})
        self.context_message_ids = (
            list(context_message_ids) if context_message_ids is not None else None
        )
        self.allowed_user_urls = list(allowed_user_urls) if allowed_user_urls is not None else None
        self.revalidate_conversation_context = revalidate_conversation_context
        self.memory_context = deepcopy(memory_context or {})
        self.reload_memory_context = reload_memory_context
        self.chat_type = chat_type

        self.selection_mode = selection_mode
        self.doc_scope = doc_scope
        # The tags the user picked in the composer. Carried for the whole run rather than
        # per step: a tag is a standing narrowing of what this turn is about, so a step that
        # searched without it would look more widely than the user asked.
        self.tags = list(tags or [])
        self.document_filter_mode = document_filter_mode or 'intersection'
        self.active_group_ids = list(active_group_ids or [])
        self.active_group_id = active_group_id
        self.active_public_workspace_id = active_public_workspace_id
        self.active_public_workspace_ids = _string_list(active_public_workspace_ids or active_public_workspace_id)

        self.gpt_model = gpt_model
        self.model_context = model_context
        self.request_correlation_id = request_correlation_id
        self.durable_execution_callback = durable_execution_callback

        # A route can inject a pre-scoped resolver (document_ids -> manifest); when absent the
        # adapters fall back to the real resolver. Held here so re-authorization and the
        # tabular adapter use the same seam.
        self.resolve_source_manifest = resolve_source_manifest

        # Request-scoped identity and catalog, captured on the request thread before the run's
        # worker thread starts. execute_plan runs in a threading.Thread with no Flask request
        # context, so adapters cannot read g/session/current_app; they read these instead.
        #
        # user_roles gates two app-role checks -- UrlAccessUser for reading URLs and
        # DeepResearchUser for the deep research crawl. It fails CLOSED: an unknown value is
        # normalized to "no roles", never to "all roles", so a break in this plumbing withholds
        # a capability rather than granting it to everyone. An empty list is preserved (it means
        # "authenticated, no roles"), but any non-list is treated as unknown for the same reason.
        if isinstance(user_roles, (list, tuple, set)):
            self.user_roles = list(user_roles)
        else:
            self.user_roles = None
        self.user_email = user_email
        # The agents this user may invoke, as full config records (not the planner projection).
        # The agent adapter refuses any agent name absent from this list, so a plan can never
        # invoke an agent the catalog did not offer this user, even after a repair.
        self.agent_catalog = list(agent_catalog) if agent_catalog else None
        self.action_catalog = list(action_catalog or [])
        # Semantic Kernel can be enabled deployment-wide while a user has agents switched off in
        # their own settings; carried so the agent adapter re-checks it without touching user
        # state it cannot reach from the worker thread.
        self.user_enable_agents = bool(user_enable_agents)
        self.agent_execution_identity = agent_execution_identity
        self.delegation_budget = delegation_budget if delegation_budget is not None else DelegationBudget()

        # Accumulators.
        self.evidence = []
        self.citations = []
        self.artifacts = []
        self.notes = []
        self.saved_analyses = deepcopy(saved_analyses or [])
        self.analysis_result_contexts = deepcopy(self.conversation_context.get('analysis_result_contexts') or [])
        for reference in analysis_result_contexts or []:
            if reference not in self.analysis_result_contexts:
                self.analysis_result_contexts.append(deepcopy(reference))
        self.token_usage = {}
        self.failures = []
        self.step_token_usage = {}

        # Documents any step produced evidence for, in first-seen order.
        self.documents_touched = []
        # Which documents each step reached, keyed by step id. A later step can name an
        # earlier one instead of naming documents, which is how a plan expresses "search,
        # then analyse what you found" -- something it could not say while every step's
        # documents had to be known when the plan was written.
        self.step_documents = {}

        # The manifest captured when execution began, and the authorized manifest resolved
        # again before finalization; the second is what the handoff is built from.
        self.execution_manifest = []
        self.source_manifest = []

    def result_producer(self, step):
        capability = get_capability(step.get('capability_id'))
        if capability is None:
            raise ResultContractError('result_producer_invalid')
        result_contract_version = capability.get('result_contract_version')
        if type(result_contract_version) is not str:
            raise ResultContractError('result_producer_invalid')
        return ProducerIdentity(
            self.user_id, self.conversation_id, self.run_id, self.attempt_index,
            step['step_id'], capability['id'], result_contract_version,
        )

    def result_guard_token_for_step(self, step_id):
        if not callable(self._result_guard_token_for_step):
            raise ResultContractError('result_guard_required')
        token = self._result_guard_token_for_step(step_id)
        if type(token) is not str or not token.strip() or token != token.strip():
            raise ResultContractError('result_guard_required')
        return token

    def result_input_fingerprint_for_step(self, step_id):
        if not callable(self._result_input_fingerprint_for_step):
            raise ResultContractError('result_input_fingerprint_required')
        value = self._result_input_fingerprint_for_step(step_id)
        digest(value)
        return value


# --------------------------------------------------------------------------------------
# Plan traversal
# --------------------------------------------------------------------------------------

def _collect_plan_document_ids(steps):
    ids = []
    for step in steps:
        arguments = step.get('arguments') if isinstance(step.get('arguments'), dict) else {}
        for key in ('document_ids', 'right_document_ids', 'target_document_ids'):
            for document_id in _string_list(arguments.get(key)):
                if document_id not in ids:
                    ids.append(document_id)
        for key in ('left_document_id', 'source_document_id'):
            document_id = _text(arguments.get(key))
            if document_id and document_id not in ids:
                ids.append(document_id)
    return ids


# --------------------------------------------------------------------------------------
# Step execution
# --------------------------------------------------------------------------------------

def _step_record(context, step, index, status, result, started_at, completed_at, duration_ms):
    result = result if isinstance(result, dict) else {}
    record = {
        'run_id': getattr(context, 'run_id', None),
        'step_id': step.get('step_id'),
        'step_index': index,
        'capability_id': step.get('capability_id'),
        'title': step.get('title') or step.get('capability_id'),
        'status': status,
        'started_at': started_at,
        'completed_at': completed_at,
        'summary': result.get('summary') or '',
        'error': result.get('error'),
        'arguments': step.get('arguments') if isinstance(step.get('arguments'), dict) else {},
        'duration_ms': duration_ms,
        'replan_hint': result.get('replan_hint'),
        'failure': result.get('failure'),
        'checkpoint_available': False,
        'reused': False,
        'reused_from_run_id': None,
        'effects_uncertain': status == STEP_STATUS_RUNNING and step.get('capability_id') in ('agent_invoke', 'action_invoke'),
    }
    if result.get('saved_analyses'):
        record['saved_analyses'] = deepcopy(result['saved_analyses'])
    if result.get('model_binding'):
        record['model_binding'] = deepcopy(result['model_binding'])
    record['role'] = step['role']
    task = result.get('task_result')
    if task is not None:
        record['task_result'] = task.to_dict()
    if result.get('wait') is not None:
        record['wait'] = deepcopy(result['wait'])
    if step['role'] == 'render':
        for field in ('outputs', 'output_error'):
            if field in result:
                record[field] = deepcopy(result[field])
    return record


def _persist(persist, record_type, record):
    if not callable(persist):
        return
    try:
        persist(record_type, record)
    except Exception as exc:
        log_event(
            f'{_LOG_PREFIX} Failed to persist {record_type} record: {exc}',
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        raise CheckpointError() from exc


# --------------------------------------------------------------------------------------
# execute_plan
# --------------------------------------------------------------------------------------

def execute_plan(
    plan,
    context,
    *,
    settings,
    user_id,
    emit=None,
    cancel_requested=None,
    persist=None,
    get_adapter=None,
    checkpoints=None,
):
    """Run a validated plan and return the run result.

    ``persist`` is an optional callable ``persist(record_type, record)`` where ``record_type``
    is ``'run'`` or ``'step'``; it is how the route writes progress to Cosmos without this
    module importing the persistence layer (which imports config). ``get_adapter`` is
    injectable for the same reason the persistence is: it lets a test drive the engine with
    fake adapters without importing the real ones.

    A plan from the removed legacy contract raises ``LegacyPlanError`` before any step runs.
    """
    version = plan_contract_version(plan)
    if version != getattr(context, 'plan_contract_version', None):
        raise ResultContractError('result_version_unsupported')
    return _execute_dependency_plan(
        plan, context, settings=settings, user_id=user_id, emit=emit,
        cancel_requested=cancel_requested, persist=persist, get_adapter=get_adapter,
        checkpoints=checkpoints,
    )


def _dependency_request_context(context):
    return {
        'user_id': context.user_id, 'user_email': context.user_email, 'user_roles': context.user_roles,
        'agent_catalog': context.agent_catalog, 'action_catalog': context.action_catalog,
        'user_enable_agents': context.user_enable_agents,
        'native_bridge_for_step': context.native_bridge_for_step,
        'external_source_admission': context.external_source_admission,
        'external_source_preflight': context.external_source_preflight,
        'capture_external_source_configuration': context.capture_external_source_configuration,
        'external_source_authorizer': getattr(
            getattr(context.result_service, 'access', None), 'external_source_authorizer', None,
        ),
        'rendering_service': context.rendering_service,
        'message_urls': context.allowed_user_urls if context.allowed_user_urls is not None else re.findall(
            r'https?://[^\s<>"]+', context.user_message,
        ),
    }


def _dependency_source_manifest(context, document_ids, settings, cancel_probe):
    if not document_ids:
        return []
    manifest = resolve_context_source_manifest(
        context, document_ids, settings=settings, user_id=context.user_id, cancel_requested=cancel_probe,
    )
    by_id = {item.get('document_id'): item for item in manifest}
    original = {item.get('document_id'): item for item in context.execution_manifest}
    for document_id in document_ids:
        source = by_id.get(document_id)
        if not source or source.get('authorization_status') != AUTHORIZATION_STATUS_AUTHORIZED:
            raise ResultUnavailableError('result_source_unavailable')
        prior = original.get(document_id)
        if prior and any(
            prior.get(key) != source.get(key)
            for key in ('scope', 'scope_id', 'source_version', 'source_revision', 'content_sha256')
        ):
            raise ResultUnavailableError('result_source_snapshot_changed')
    return manifest


def _dependency_adapter_context(context, manifest, step, input_fingerprint):
    scoped = copy(context)
    for name in ('evidence', 'citations', 'artifacts', 'notes', 'saved_analyses', 'documents_touched'):
        setattr(scoped, name, [])
    scoped.step_documents = {}
    scoped.execution_manifest = deepcopy(manifest)
    scoped.source_manifest = deepcopy(manifest)
    scoped._result_input_fingerprint_for_step = (
        lambda step_id: input_fingerprint if step_id == step['step_id'] else None
    )
    return scoped


def _native_step_bridge(step, context, settings):
    # Bridge construction is an execution dependency, never an import-time dependency.
    from functions_orchestration_native_results import NativeOrchestrationBridge

    factory = context.native_bridge_for_step
    if not callable(factory):
        raise ResultContractError('result_adapter_unavailable')
    bridge = factory(step, context)
    arguments = step['arguments']
    if (
        type(bridge) is not NativeOrchestrationBridge or bridge.source_policy != 'current'
        or bridge.native_operation != arguments['native_operation']
        or bridge.task_type != arguments['task_type']
    ):
        raise ResultContractError('result_contract_invalid')
    fingerprint = context.result_input_fingerprint_for_step(step['step_id'])
    if (
        bridge.input_fingerprint_for_step is not None
        and bridge.input_fingerprint_for_step(step, context) != fingerprint
    ):
        raise ResultContractError('result_input_changed')
    return replace(bridge, input_fingerprint_for_step=lambda native_step, native_context: fingerprint)


def _raise_dependency_service_failure(step, error):
    raise_source_service_failure(error)
    if step['capability_id'] == CAPABILITY_TABULAR_ANALYZE:
        # Native failure contracts are execution-only, not startup dependencies.
        from functions_orchestration_native_results import raise_native_orchestration_infrastructure_failure

        raise_native_orchestration_infrastructure_failure(error)


def _run_dependency_step(
    step, context, settings, user_id, emit, cancel_probe, resolver, *,
    input_fingerprint, native_pending=None,
):
    # The file policy is loaded where steps run, not when the executor is imported.
    from functions_orchestration_execution_policy import orchestration_file_policy, OrchestrationFilePolicyError

    try:
        if step['role'] != 'render':
            assert_current_request_sources_available(user_id)
        service = require_result_service(context)
        producer = context.result_producer(step)
        service.access.authorize_producer(producer, for_write=True)
        if native_pending is None and step['role'] != 'render':
            recovered = service.recover_task_result(producer=producer, input_fingerprint=input_fingerprint)
            if recovered is not None:
                validate_task_outputs(step, context, recovered)
            assert_current_request_sources_available(user_id)
            if recovered is not None:
                return build_step_result(
                    status=STEP_STATUS_PARTIAL if recovered.status == 'partial' else STEP_STATUS_COMPLETED,
                    task_result=recovered, summary='Recovered the committed result without repeating the producer.',
                )
        readers = resolve_step_inputs(step, context)
        runtime_step = deepcopy(step)
        named_sources = []
        if 'sources' in readers and step['capability_id'] == 'document_analyze':
            named_sources = read_complete_input(readers['sources'])
            runtime_step['arguments']['document_ids'] = [
                source['document_id'] for source in named_sources
            ]
            if len(set(runtime_step['arguments']['document_ids'])) != len(named_sources):
                raise ResultContractError('result_source_identity_ambiguous')
        document_ids = _collect_plan_document_ids([runtime_step])
        if step['capability_id'] == 'document_search' and not document_ids:
            document_ids = list(context.selected_document_ids)
        manifest = _dependency_source_manifest(context, document_ids, settings, cancel_probe)
        if named_sources:
            by_id = {source['document_id']: source for source in manifest}
            for source in named_sources:
                current = by_id.get(source['document_id'], {})
                if any(
                    current.get(field) != source.get(field)
                    for field in ('scope', 'scope_id', 'source_version', 'source_revision')
                ) or (source.get('content_sha256') is not None and current.get('content_sha256') != source['content_sha256']):
                    raise ResultUnavailableError('result_source_snapshot_changed')
        scoped = _dependency_adapter_context(context, manifest, step, input_fingerprint)
        binding_scope = getattr(context, 'step_model_scope', None)
        model_scope = (
            binding_scope(step, scoped)
            if callable(binding_scope) and step['role'] != 'render' else nullcontext()
        )
        # Render publishes files; generate_image publishes the one chat image it was approved
        # to create. Every other Gather or Reason step stays unable to publish anything.
        capability = get_capability(step['capability_id'], contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION)
        publishes = step['role'] == 'render' or (capability or {}).get('publishes_generated_images') is True
        with orchestration_file_policy(allow_generated_files=publishes), model_scope:
            if step['capability_id'] == 'render_file':
                result = _render_dependency_step(
                    runtime_step, scoped, settings=settings, user_id=user_id, cancel_requested=cancel_probe,
                )
            elif step['capability_id'] == CAPABILITY_TABULAR_ANALYZE:
                bridge = _native_step_bridge(runtime_step, scoped, settings)
                if native_pending is None:
                    result = bridge.execute(
                        runtime_step, scoped, settings=settings, user_id=user_id,
                        emit=emit, cancel_requested=cancel_probe,
                    )
                else:
                    result = bridge.resume(
                        runtime_step, scoped, native_pending, settings=settings, user_id=user_id,
                        emit=emit, cancel_requested=cancel_probe,
                    )
            else:
                adapter = resolver(step['capability_id'])
                if not callable(adapter):
                    raise ResultContractError('result_adapter_unavailable')
                result = adapter(
                    runtime_step, scoped, settings=settings, user_id=user_id,
                    emit=emit, cancel_requested=cancel_probe,
                )
            if isinstance(result, dict) and step.get('model_binding') and step['role'] != 'render':
                # The executed binding, including the reasoning the provider actually accepted.
                result['model_binding'] = deepcopy(step['model_binding'])
                model = getattr(scoped, 'step_model', None)
                if model is not None:
                    result['model_binding']['selection'] = model.answer_model_selection()
                    result['model_binding']['reasoning'] = deepcopy(model.reasoning_resolution)
        context.token_usage = scoped.token_usage
        if hasattr(scoped, 'prompt_token_usage'):
            context.prompt_token_usage = scoped.prompt_token_usage
        if step['role'] != 'render':
            assert_current_request_sources_available(user_id)
        if cancel_probe():
            raise MixedSourceCancellationError('orchestration_step')
        if type(result) is not dict or result.get('status') not in (
            STEP_STATUS_COMPLETED, STEP_STATUS_PARTIAL, STEP_STATUS_PENDING, STEP_STATUS_WAITING,
            STEP_STATUS_FAILED, STEP_STATUS_CANCELLED,
        ):
            raise ResultContractError('result_contract_invalid')
        if step['role'] != 'render' and (
            result.get('artifacts') or any(entry.get('generated_artifacts') for entry in result.get('evidence') or [])
        ):
            raise OrchestrationFilePolicyError()
        if step['role'] == 'render':
            return _validate_render_step_result(step, result)
        task = result.get('task_result')
        if result['status'] in (STEP_STATUS_FAILED, STEP_STATUS_CANCELLED):
            if result['status'] == STEP_STATUS_FAILED and task is not None:
                validate_task_diagnostics(step, context, task)
            return result
        if task is None and step['role'] == 'gather':
            gathered_ids = list(dict.fromkeys(
                entry['document_id'] for entry in [*(result.get('evidence') or []), *(result.get('citations') or [])]
                if isinstance(entry, dict) and entry.get('document_id')
            )) if step['capability_id'] == 'document_search' else []
            manifest = _dependency_source_manifest(context, gathered_ids, settings, cancel_probe)
            task = retain_gather_result(step, scoped, result, source_manifest=manifest)
        validate_task_outputs(step, context, task)
        if task.status == 'pending':
            if type(result.get('wait')) is not dict or not result['wait']:
                raise ResultContractError('result_wait_required')
            result['status'] = STEP_STATUS_WAITING
        elif task.status in ('complete', 'partial'):
            result['status'] = STEP_STATUS_COMPLETED if task.status == 'complete' else STEP_STATUS_PARTIAL
        else:
            raise ResultContractError('result_not_ready')
        result['task_result'] = task
        return result
    except MixedSourceCancellationError:
        raise
    except Exception as exc:
        _raise_dependency_service_failure(step, exc)
        log_event(
            f'{_LOG_PREFIX} A dependency-bound step could not complete.',
            level=logging.WARNING,
            extra={'run_id': context.run_id, 'step_id': step['step_id'], 'error_type': type(exc).__name__},
        )
        if isinstance(exc, OrchestrationFilePolicyError):
            failure = build_failure('file_publication_not_allowed')
        elif isinstance(exc, (ResultUnavailableError, ElicitationContextError, PermissionError, ScreeningError)):
            failure = build_failure('result_unavailable')
        elif isinstance(exc, ResultContractError):
            failure = build_failure('result_invalid')
        else:
            failure = failure_from_exception(exc)
        return build_step_result(
            status=STEP_STATUS_FAILED, failure=failure, summary=failure['message'], error=failure['message'],
        )


def _dependency_adapter(capability_id):
    if capability_id == 'render_file':
        return _render_dependency_step
    return _default_get_adapter(capability_id, contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION)


def _validate_render_step_result(step, result):
    """Files are service-verified deliveries, never fabricated typed data outputs."""
    if (
        type(result) is not dict or result.get('task_result') is not None
        or result.get('evidence') or result.get('notes') or result.get('citations')
    ):
        raise ResultContractError('result_contract_invalid')
    status = result.get('status')
    if status not in (STEP_STATUS_COMPLETED, STEP_STATUS_WAITING, STEP_STATUS_FAILED, STEP_STATUS_CANCELLED):
        raise ResultContractError('result_contract_invalid')
    if status in (STEP_STATUS_FAILED, STEP_STATUS_CANCELLED):
        if result.get('artifacts'):
            raise ResultContractError('result_contract_invalid')
        return result
    outputs = result.get('outputs')
    if status == STEP_STATUS_WAITING and type(outputs) is list and not outputs:
        # A committed file's DTO can be withheld after an uncertain read. Keep
        # only the admitted identity; load the output contract only when rendering runs.
        from functions_orchestration_output_store import _OUTPUT_ID

        wait = result.get('wait')
        error = result.get('output_error')
        if (
            result.get('artifacts') or result.get('failure') is not None
            or type(wait) is not dict or wait.get('kind') != 'orchestration_output'
            or type(wait.get('output_id')) is not str or _OUTPUT_ID.fullmatch(wait['output_id']) is None
            or type(error) is not dict or error.get('retryable') is not True
            or type(error.get('code')) is not str or not error['code']
            or ('error_code' in wait and wait['error_code'] != error['code'])
        ):
            raise ResultContractError('result_wait_required')
        return result
    if (
        type(outputs) is not list or len(outputs) != 1 or type(outputs[0]) is not dict
        or outputs[0].get('step_id') != step['step_id']
        or not isinstance(outputs[0].get('output_id'), str)
        or outputs[0].get('file_name') != secure_filename(step['arguments']['file_name'])
        or any(outputs[0].get(key) != step['arguments'][key] for key in ('output_format', 'profile'))
    ):
        raise ResultContractError('result_contract_invalid')
    if status == STEP_STATUS_COMPLETED:
        if (
            outputs[0].get('state') != 'completed' or outputs[0].get('available') is not True
            or type(result.get('artifacts')) is not list or len(result['artifacts']) != 1
        ):
            raise ResultContractError('result_contract_invalid')
    else:
        wait = result.get('wait')
        if (
            result.get('artifacts') or type(wait) is not dict
            or wait.get('kind') != 'orchestration_output'
            or wait.get('output_id') != outputs[0]['output_id']
        ):
            raise ResultContractError('result_wait_required')
    return result


def _context_rendering_service(context, *, settings, user_id):
    """Use only the initialized actor-bound service installed by the parent factory."""
    # Keep concrete output-service dependencies out of module import.
    from functions_orchestration_rendering import OrchestrationRenderingService

    service = context.rendering_service
    if not isinstance(service, OrchestrationRenderingService):
        raise ResultContractError('result_adapter_unavailable')
    if (
        service.results is not context.result_service
        or user_id != context.user_id or user_id != service.results.access.user_id
        or context.conversation_id != service.results.access.conversation_id
    ):
        raise ResultContractError('result_producer_mismatch')
    return service


def _dependency_file_outcomes(context, *, settings, user_id):
    """Project only current file outcomes and verified commits from the owning service."""
    if context.rendering_service is None:
        return [], []
    service = _context_rendering_service(context, settings=settings, user_id=user_id)
    return service.list_public_outputs(context.run_id), service.committed_artifacts(context.run_id)


def _render_dependency_step(
    step, context, *, settings, user_id, emit=None, cancel_requested=None, saved_result=None,
):
    # Rendering and its read-only resumer share the actual output service, not adapter tables.
    import functions_orchestration_rendering as rendering
    from functions_orchestration_execution_policy import orchestration_file_policy

    catalog = getattr(context, 'export_catalog', None)
    if catalog is not None and (
        step['arguments']['output_format'], step['arguments']['profile']
    ) not in admitted_export_pairs(catalog):
        raise ResultContractError('result_adapter_unavailable')
    arguments = {
        'service_factory': _context_rendering_service, 'resolve_inputs': resolve_step_inputs,
        'build_step_result': build_step_result, 'build_failure': build_failure,
        'settings': settings, 'user_id': user_id, 'cancel_requested': cancel_requested,
    }
    with orchestration_file_policy(allow_generated_files=saved_result is None):
        if saved_result is None:
            result = rendering.execute_render_file(step, context, **arguments)
        else:
            result = rendering.resume_render_file(step, context, saved_result, **arguments)
    result = _validate_render_step_result(step, result)
    if result['status'] == STEP_STATUS_WAITING:
        wait = result['wait']
        result['wait'] = {'kind': 'orchestration_output', 'output_id': wait['output_id']}
        if wait.get('error_code') is not None:
            result['wait']['error_code'] = wait['error_code']
    return result


def resume_native_dependency_step(
    step, context, *, settings, user_id, input_fingerprint, emit=None, cancel_requested=None,
):
    """Reopen one saved native wait once; the owning continuation commits the returned result."""
    if (
        context.plan_contract_version != DEPENDENCY_PLAN_CONTRACT_VERSION
        or user_id != context.user_id or step.get('capability_id') != CAPABILITY_TABULAR_ANALYZE
        or step.get('role') != 'reason' or step.get('enabled') is not True
    ):
        raise ResultContractError('result_producer_invalid')
    available = resolve_available_capability_ids(
        settings, allowed_ids=settings.get('chat_orchestration_enabled_capabilities'),
        request_context=_dependency_request_context(context),
        candidate_ids={CAPABILITY_TABULAR_ANALYZE}, contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION,
        export_catalog=context.export_catalog,
    )
    if CAPABILITY_TABULAR_ANALYZE not in available:
        raise ResultContractError('result_adapter_unavailable')
    current_fingerprint = step_input_fingerprint(step, context, None, settings=settings)
    if type(input_fingerprint) is not str or input_fingerprint != current_fingerprint:
        raise ResultContractError('result_input_changed')
    task = context.task_results.get(step['step_id'])
    wait = context.pending_results.get(step['step_id'])
    validate_task_outputs(step, context, task)
    if task.status != 'pending' or type(wait) is not dict or not wait:
        raise ResultContractError('result_wait_required')
    if context.execution_deadline_at is not None:
        deadline = datetime.fromisoformat(context.execution_deadline_at)
        if deadline.tzinfo is None:
            raise ResultContractError('result_deadline_invalid')
        if datetime.now(timezone.utc) >= deadline:
            return build_step_result(status=STEP_STATUS_FAILED, failure=build_failure('run_timeout'))
    pending = build_step_result(status=STEP_STATUS_WAITING, task_result=task, wait=wait)
    try:
        return _run_dependency_step(
            step, context, settings, user_id, emit, cancel_requested or (lambda: False),
            _dependency_adapter, input_fingerprint=input_fingerprint, native_pending=pending,
        )
    except MixedSourceCancellationError:
        return build_step_result(status=STEP_STATUS_CANCELLED, failure=build_failure('user_cancelled'))


def resume_waiting_dependency_step(
    step, context, *, settings, user_id, input_fingerprint, emit=None, cancel_requested=None,
    saved_result=None,
):
    """Refresh one authorized saved wait; never enter the ordinary producer resolver."""
    wait = context.pending_results.get(step['step_id'])
    if type(wait) is not dict:
        raise ResultContractError('result_wait_required')
    if wait.get('kind') == 'native_tabular_compute':
        return resume_native_dependency_step(
            step, context, settings=settings, user_id=user_id, input_fingerprint=input_fingerprint,
            emit=emit, cancel_requested=cancel_requested,
        )
    if wait.get('kind') == 'orchestration_output':
        if (
            context.plan_contract_version != 2 or user_id != context.user_id
            or step.get('capability_id') != 'render_file' or step.get('role') != 'render'
            or step.get('enabled') is not True
            or input_fingerprint != step_input_fingerprint(step, context, None, settings=settings)
        ):
            raise ResultContractError('result_input_changed')
        if (
            type(saved_result) is not dict or saved_result.get('status') != STEP_STATUS_WAITING
            or type(saved_result.get('wait')) is not dict
            or saved_result['wait'].get('kind') != 'orchestration_output'
            or saved_result['wait'].get('output_id') != wait.get('output_id')
        ):
            raise ResultContractError('result_wait_invalid')
        return _render_dependency_step(
            step, context, settings=settings, user_id=user_id, cancel_requested=cancel_requested,
            saved_result=saved_result,
        )
    if (
        context.plan_contract_version != 2 or user_id != context.user_id
        or step.get('role') not in ('gather', 'reason') or step.get('enabled') is not True
        or set(wait) != {'kind', 'input_fingerprint'} or wait['kind'] != 'orchestration_result'
        or wait['input_fingerprint'] != input_fingerprint
        or step_input_fingerprint(step, context, None, settings=settings) != input_fingerprint
    ):
        raise ResultContractError('result_wait_invalid')
    task = context.task_results.get(step['step_id'])
    validate_task_outputs(step, context, task)
    if task.status != 'pending' or task.outputs:
        raise ResultContractError('result_wait_invalid')
    if callable(cancel_requested) and cancel_requested():
        return build_step_result(status=STEP_STATUS_CANCELLED, failure=build_failure('user_cancelled'))
    if type(context.execution_deadline_at) is not str:
        raise ResultContractError('result_deadline_invalid')
    deadline = datetime.fromisoformat(context.execution_deadline_at)
    if deadline.tzinfo is None:
        raise ResultContractError('result_deadline_invalid')
    if datetime.now(timezone.utc) >= deadline:
        return build_step_result(status=STEP_STATUS_FAILED, failure=build_failure('run_timeout'))
    service = require_result_service(context)
    resolve_step_inputs(step, context)
    _dependency_source_manifest(context, _collect_plan_document_ids([step]), settings, cancel_requested)
    completed = service.recover_task_result(producer=task.producer, input_fingerprint=input_fingerprint)
    if completed is None:
        return build_step_result(
            status=STEP_STATUS_WAITING, task_result=task, wait=wait,
            summary='Waiting for the retained producer result.',
        )
    validate_task_outputs(step, context, completed)
    return build_step_result(
        status=STEP_STATUS_PARTIAL if completed.status == 'partial' else STEP_STATUS_COMPLETED,
        task_result=completed, summary='Recovered the retained producer result.',
    )


def _execute_dependency_plan(
    plan, context, *, settings, user_id, emit, cancel_requested, persist, get_adapter, checkpoints,
):
    settings = settings or {}
    if user_id != context.user_id or any(
        plan.get(name, getattr(context, name)) != getattr(context, name)
        for name in ('run_id', 'conversation_id', 'user_id')
    ):
        raise ResultUnavailableError('result_owner_mismatch')
    service = require_result_service(context)
    available = resolve_available_capability_ids(
        settings, allowed_ids=settings.get('chat_orchestration_enabled_capabilities'),
        request_context=_dependency_request_context(context),
        candidate_ids={step.get('capability_id') for step in plan.get('steps') or []},
        contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION,
        export_catalog=context.export_catalog,
    )
    plan = validate_plan(
        plan, settings=settings, available_capability_ids=available,
        agent_names=[agent.get('name') for agent in context.agent_catalog or []],
        action_refs=[action.get('action_ref') for action in context.action_catalog],
        existing_results=context.result_aliases, composition_profiles=context.composition_profiles,
        export_catalog=context.export_catalog, contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION,
    )
    steps = plan['steps']
    resolver = get_adapter or _dependency_adapter
    cancel_probe = _make_cancel_probe(cancel_requested)
    planned_ids = _collect_plan_document_ids([step for step in steps if step['enabled']])
    if any(
        step['enabled'] and step['capability_id'] == 'document_search' and not step['arguments'].get('document_ids')
        for step in steps
    ):
        planned_ids = list(dict.fromkeys([*planned_ids, *context.selected_document_ids]))
    step_timeout = _setting_int(settings, 'chat_orchestration_step_timeout_seconds', _DEFAULT_STEP_TIMEOUT_SECONDS)
    if context.execution_deadline_at is None:
        context.execution_deadline_at = initial_execution_deadline(datetime.now(timezone.utc), settings)
    context.execution_manifest = _dependency_source_manifest(context, planned_ids, settings, cancel_probe)
    if checkpoints is not None:
        context.durable_checkpoints = True
        checkpoints = checkpoints(context) if callable(checkpoints) else checkpoints
        checkpoints.initialize()
    deadline = datetime.fromisoformat(context.execution_deadline_at)
    if deadline.tzinfo is None:
        raise ResultContractError('result_deadline_invalid')
    _persist(persist, 'run', {
        'run_id': context.run_id, 'status': PLAN_STATUS_RUNNING,
        'started_at': (
            checkpoints.record.get('started_at') if getattr(checkpoints, 'continuing', False) else None
        ) or _now_iso(),
        'planner_contract_version': DEPENDENCY_PLAN_CONTRACT_VERSION,
        'execution_deadline_at': context.execution_deadline_at,
    })
    records, statuses, hints = [], {}, []
    context._completed_result_step_ids = set()
    context._failed_result_step_ids = set()
    context.artifacts = []
    cancelled = False

    def save(record):
        if checkpoints is not None:
            checkpoints.save_step(record)
        else:
            _persist(persist, 'step', record)

    for index, step in enumerate(steps):
        step_id = step['step_id']
        context.step_token_usage = {}
        started_at, completed_at, elapsed = None, None, 0
        reused = None
        result = None
        if cancelled or cancel_probe():
            cancelled = True
            result = build_step_result(status=STEP_STATUS_CANCELLED, failure=build_failure('user_cancelled'))
        elif not step['enabled']:
            result = build_step_result(status=STEP_STATUS_SKIPPED, summary='Step is disabled.')
        elif any(statuses.get(dependency) == STEP_STATUS_WAITING for dependency in step['depends_on']):
            result = build_step_result(status=STEP_STATUS_WAITING, summary='Waiting for required results.')
        elif any(
            statuses.get(dependency) not in (STEP_STATUS_COMPLETED, STEP_STATUS_PARTIAL)
            # A producer bound only through optional inputs may fail; the consumer discloses it.
            and dependency not in optional_input_producers(step)
            for dependency in step['depends_on']
        ):
            result = build_step_result(
                status=STEP_STATUS_SKIPPED, failure=build_failure('dependency_unavailable'),
                summary=build_failure('dependency_unavailable')['message'],
            )
        else:
            resolve_elicitation_references(
                context.elicitation_references, user_id, context.conversation_id, settings=settings,
            )
            revalidate = context.revalidate_conversation_context
            if callable(revalidate):
                revalidate()
            previous = checkpoints.previous_terminal_result(step) if checkpoints is not None else None
            reused = checkpoints.before_step(step) if checkpoints is not None and previous is None else None
            input_fingerprint = step_input_fingerprint(
                step, context, checkpoints.binding if checkpoints is not None else None, settings=settings,
            )
            if previous is not None:
                result = previous
            elif reused and reused['result']['status'] == STEP_STATUS_WAITING:
                if not checkpoints.continuing:
                    raise CheckpointError('result_not_ready')
                restore_context(context, reused)
                try:
                    result = resume_waiting_dependency_step(
                        step, context, settings=settings, user_id=user_id,
                        input_fingerprint=reused['input_fingerprint'], emit=emit, cancel_requested=cancel_probe,
                        saved_result=reused['result'],
                    )
                except (
                    ResultContractError, ResultUnavailableError, PermissionError, ScreeningError,
                    WorkflowResultIntegrityError, WorkflowResultStorageUnavailableError,
                ) as exc:
                    _raise_dependency_service_failure(step, exc)
                    if step['role'] == 'render':
                        raise
                    log_event(
                        f'{_LOG_PREFIX} A saved wait could not be resumed.',
                        level=logging.WARNING,
                        extra={'run_id': context.run_id, 'step_id': step_id, 'error_type': type(exc).__name__},
                    )
                    result = build_step_result(status=STEP_STATUS_FAILED, failure=build_failure('result_unavailable'))
                task = result.get('task_result')
                if result['status'] in (STEP_STATUS_COMPLETED, STEP_STATUS_PARTIAL, STEP_STATUS_WAITING):
                    if step['role'] == 'render':
                        _validate_render_step_result(step, result)
                    else:
                        validate_task_outputs(step, context, task)
                        context.task_results[step_id] = task
                    if result['status'] == STEP_STATUS_WAITING:
                        context.pending_results[step_id] = deepcopy(result['wait'])
                    else:
                        context.pending_results.pop(step_id, None)
                    checkpoints.commit(step, result, input_fingerprint)
                else:
                    context.task_results.pop(step_id, None)
                    context.pending_results.pop(step_id, None)
                reused = None
            elif reused:
                restore_context(context, reused)
                if step['role'] == 'render':
                    result = _render_dependency_step(
                        step, context, settings=settings, user_id=user_id,
                        cancel_requested=cancel_probe, saved_result=reused['result'],
                    )
                    if result['status'] == STEP_STATUS_COMPLETED:
                        context.pending_results.pop(step_id, None)
                        checkpoints.commit(step, result, input_fingerprint, reused=reused)
                else:
                    result = decode_step_result(reused['result'])
                    validate_task_outputs(step, context, result['task_result'], reused=True)
                    context.pending_results.pop(step_id, None)
                    checkpoints.commit(step, result, input_fingerprint, reused=reused)
            elif step_id in context.task_results:
                task = context.task_results[step_id]
                validate_task_outputs(step, context, task)
                if task.status == 'pending' and not context.pending_results.get(step_id):
                    raise ResultContractError('result_wait_required')
                result = build_step_result(
                    status=STEP_STATUS_WAITING if task.status == 'pending' else (
                        STEP_STATUS_PARTIAL if task.status == 'partial' else STEP_STATUS_COMPLETED
                    ), task_result=task, wait=context.pending_results.get(step_id),
                    summary='Retained task result; producer was not repeated.',
                )
                if task.status != 'pending':
                    context.pending_results.pop(step_id, None)
                if checkpoints is not None:
                    checkpoints.commit(step, result, input_fingerprint)
            elif datetime.now(timezone.utc) >= deadline:
                result = build_step_result(status=STEP_STATUS_FAILED, failure=build_failure('run_timeout'))
            else:
                started_at = _now_iso()
                started = time.monotonic()
                reason = None
                usage_before = deepcopy(context.token_usage)
                prompt_usage_before = deepcopy(getattr(context, 'prompt_token_usage', {}) or {})

                def step_cancel():
                    nonlocal reason
                    if reason:
                        return True
                    if cancel_probe():
                        reason = 'user_cancelled'
                    elif datetime.now(timezone.utc) >= deadline:
                        reason = 'run_timeout'
                    elif time.monotonic() - started >= step_timeout:
                        reason = 'step_timeout'
                    return reason is not None

                running = _step_record(context, step, index, STEP_STATUS_RUNNING, None, started_at, None, 0)
                running.update({
                    'result_producer': context.result_producer(step).to_dict(),
                    'input_fingerprint': input_fingerprint,
                })
                if checkpoints is not None:
                    checkpoints.begin_step(step, input_fingerprint)
                save(running)
                _emit(emit, {'type': 'step', 'phase': STEP_STATUS_RUNNING, **running, 'completed': index, 'total': len(steps)})
                try:
                    result = _run_dependency_step(
                        step, context, settings, user_id, emit, step_cancel, resolver,
                        input_fingerprint=input_fingerprint,
                    )
                    if _should_retry_transient(step, result, step_cancel):
                        _log_transient_retry(context, step, result)
                        _emit(emit, {
                            'type': 'step', 'phase': STEP_STATUS_RUNNING, **running,
                            'summary': _TRANSIENT_RETRY_SUMMARY, 'completed': index, 'total': len(steps),
                        })
                        if _pause_before_retry(step_cancel):
                            result = _run_dependency_step(
                                step, context, settings, user_id, emit, step_cancel, resolver,
                                input_fingerprint=input_fingerprint,
                            )
                except MixedSourceCancellationError:
                    result = build_step_result(
                        status=STEP_STATUS_CANCELLED if reason == 'user_cancelled' else STEP_STATUS_FAILED,
                        failure=build_failure(reason or 'execution_interrupted'),
                    )
                step_cancel()
                if reason:
                    result = build_step_result(
                        status=STEP_STATUS_CANCELLED if reason == 'user_cancelled' else STEP_STATUS_FAILED,
                        failure=build_failure(reason),
                    )
                context.step_token_usage = {
                    key: value - usage_before.get(key, 0)
                    for key, value in context.token_usage.items()
                    if type(value) is int and type(usage_before.get(key, 0)) is int
                }
                for key, value in (getattr(context, 'prompt_token_usage', {}) or {}).items():
                    if type(value) is int and type(prompt_usage_before.get(key, 0)) is int:
                        context.step_token_usage[key] = (
                            context.step_token_usage.get(key, 0) + value - prompt_usage_before.get(key, 0)
                        )
                elapsed = int((time.monotonic() - started) * 1000)
                completed_at = None if result['status'] == STEP_STATUS_WAITING else _now_iso()
                task = result.get('task_result')
                if (task is not None or step['role'] == 'render') and result['status'] in (
                    STEP_STATUS_COMPLETED, STEP_STATUS_PARTIAL, STEP_STATUS_WAITING,
                ):
                    if task is not None:
                        context.task_results[step_id] = task
                    if result['status'] == STEP_STATUS_WAITING:
                        context.pending_results[step_id] = deepcopy(result['wait'])
                    else:
                        context.pending_results.pop(step_id, None)
                    if checkpoints is not None:
                        checkpoints.commit(step, result, input_fingerprint)
        status = result['status']
        if status == STEP_STATUS_CANCELLED:
            cancelled = True
        if status in (STEP_STATUS_FAILED, STEP_STATUS_CANCELLED):
            context._failed_result_step_ids.add(step_id)
            context.task_results.pop(step_id, None)
            context.pending_results.pop(step_id, None)
        if status in (STEP_STATUS_FAILED, STEP_STATUS_CANCELLED) or result.get('failure'):
            delivery = {
                field: deepcopy(result[field]) for field in ('outputs', 'output_error')
                if step['role'] == 'render' and field in result
            }
            failure = safe_failure(
                result.get('failure') or build_failure('step_failed'), step_id=step_id,
                capability_id=step['capability_id'],
            )
            result = build_step_result(
                status=status, summary=failure['message'], failure=failure, error=failure['message'],
                task_result=result.get('task_result') if status == STEP_STATUS_FAILED else None,
            )
            result.update(delivery)
            context.failures.append(failure)
        if result.get('replan_hint') and len(hints) < _setting_int(
            settings, 'chat_orchestration_max_replans', _DEFAULT_MAX_REPLANS,
        ):
            hints.append({'step_id': step_id, 'capability_id': step['capability_id'], 'hint': result['replan_hint']})
        statuses[step_id] = status
        if status in (STEP_STATUS_COMPLETED, STEP_STATUS_PARTIAL):
            context._completed_result_step_ids.add(step_id)
        if step['role'] == 'render' and status == STEP_STATUS_COMPLETED:
            context.artifacts.extend(deepcopy(result['artifacts']))
        record = _step_record(context, step, index, status, result, started_at, completed_at, elapsed)
        record.update({
            'checkpoint_available': checkpoints is not None
            and (result.get('task_result') is not None or bool(result.get('outputs')))
            and status in (STEP_STATUS_COMPLETED, STEP_STATUS_PARTIAL, STEP_STATUS_WAITING),
            'token_usage': {} if reused else deepcopy(context.step_token_usage),
            'reused': bool(reused),
            'reused_from_run_id': (reused.get('provenance') or {}).get('run_id') if reused else None,
            'effects_uncertain': step['capability_id'] in ('agent_invoke', 'action_invoke')
            and status in (STEP_STATUS_FAILED, STEP_STATUS_CANCELLED),
        })
        save(record)
        records.append(record)
        _emit(emit, {'type': 'step', 'phase': status, **record, 'completed': index + 1, 'total': len(steps)})

    enabled = [step for step in steps if step['enabled']]
    required = [step for step in enabled if not step['optional']] or enabled
    waiting = any(statuses[step['step_id']] == STEP_STATUS_WAITING for step in required)
    complete = bool(required) and all(statuses[step['step_id']] == STEP_STATUS_COMPLETED for step in required)
    message, response_reference, citations = '', None, []
    authorized_references = set()
    if not cancelled:
        try:
            for task in context.task_results.values():
                if task.status in ('complete', 'partial'):
                    for reference in task.outputs:
                        service.open_result(reference, allow_partial=True, require_current_sources=True).recheck()
                        authorized_references.add(reference)
            if plan.get('final_response'):
                binding = InputBinding.from_dict(plan['final_response'])
                task = context.task_results.get(binding.step_id) if binding.step_id else None
                if binding.existing_result:
                    response_reference = context.result_aliases[binding.existing_result]
                elif task and task.status in ('complete', 'partial'):
                    response_reference = task.output(binding.output_name)
                else:
                    complete = False
                    waiting = waiting or bool(task and task.status == 'pending')
                if response_reference is not None:
                    reader = service.open_result(response_reference, allow_partial=True, require_current_sources=True)
                    message = read_complete_input(reader)
                    citations = read_result_document_citations(context, response_reference)
                    authorized_references.add(response_reference)
                    if response_reference.completeness.status != 'complete':
                        complete = False
        except (
            ResultContractError, ResultUnavailableError, PermissionError, ScreeningError,
            WorkflowResultIntegrityError, WorkflowResultStorageUnavailableError,
        ) as exc:
            raise_source_service_failure(exc)
            log_event(
                f'{_LOG_PREFIX} Retained content could not be reauthorized for finalization.',
                level=logging.WARNING, extra={'run_id': context.run_id, 'error_type': type(exc).__name__},
            )
            context.failures.append(build_failure('result_unavailable'))
            message, complete, response_reference, citations = '', False, None, []
            context.artifacts = []
    file_outputs, committed_artifacts = _dependency_file_outcomes(
        context, settings=settings, user_id=user_id,
    )
    for step in required:
        if step['role'] == 'render' and sum(
            output.get('step_id') == step['step_id']
            and output.get('state') == 'completed' and output.get('available') is True
            for output in file_outputs
        ) != 1:
            complete = False
    # An image the user explicitly asked for is required even though its step is optional
    # work for the answer: a missing image must not be reported as a delivered request.
    if explicit_image_shortfalls(plan, statuses):
        complete = False
    partial = any(status in (STEP_STATUS_COMPLETED, STEP_STATUS_PARTIAL) for status in statuses.values())
    status = PLAN_STATUS_CANCELLED if cancelled else (
        PLAN_STATUS_WAITING if waiting else PLAN_STATUS_COMPLETED if complete else PLAN_STATUS_FAILED
    )
    outcome = 'cancelled' if cancelled else 'waiting' if waiting else (
        'completed' if complete else 'partial' if partial else 'failed'
    )
    if waiting:
        facts = build_failure('result_not_ready')['message']
    elif cancelled or not complete:
        if not context.failures:
            context.failures.append(build_failure('result_partial' if partial else 'result_invalid'))
        facts = failure_explanation(context.failures, partial=partial, cancelled=cancelled)
    else:
        facts = '' if message else (
            'The requested files are ready.' if committed_artifacts
            else 'The requested content is prepared. No downloadable files were created.'
        )
    if facts:
        message = f'{message}\n\n{facts}' if message else facts
    result_outputs = []
    for step in steps:
        task = context.task_results.get(step['step_id'])
        references = {reference.output_name: reference for reference in task.outputs} if task else {}
        for specification in step['outputs']:
            reference = references.get(specification['name'])
            authorized = reference is not None and reference in authorized_references
            result_outputs.append({
                'step_id': step['step_id'], 'name': specification['name'], 'kind': specification['kind'],
                'status': reference.completeness.status if authorized else (
                    'pending' if statuses[step['step_id']] == STEP_STATUS_WAITING else 'unavailable'
                ),
                **({'reference': reference.to_dict()} if authorized else {}),
            })
    run_result = {
        'run_id': context.run_id, 'plan_id': context.plan_id or plan.get('plan_id'),
        'conversation_id': context.conversation_id, 'planner_contract_version': DEPENDENCY_PLAN_CONTRACT_VERSION,
        'status': status, 'outcome': outcome, 'message': message, 'summary': message.split('\n', 1)[0][:600],
        'failure': context.failures[0] if context.failures else None, 'failures': list(context.failures),
        'evidence': [], 'citations': citations, 'artifacts': committed_artifacts,
        'notes': [], 'documents_touched': [],
        'capabilities_used': list(dict.fromkeys(
            step['capability_id'] for step in records if step['status'] in (STEP_STATUS_COMPLETED, STEP_STATUS_PARTIAL)
        )),
        'token_usage': dict(context.token_usage), 'steps': records, 'replan_hints': hints,
        'reauthorization': {'checked': not cancelled, 'reason': 'named_retained_results'},
        'completed_at': None if waiting else _now_iso(), 'error': None,
        'task_results': {step_id: task.to_dict() for step_id, task in context.task_results.items()},
        'outputs': file_outputs, 'result_outputs': result_outputs,
        'pending_results': deepcopy(context.pending_results),
        'execution_deadline_at': context.execution_deadline_at,
        'final_response': response_reference.to_dict() if response_reference else None,
        'delivery_facts': {'files': file_outputs},
    }
    _persist(persist, 'run', run_result)
    _emit(emit, {
        'type': 'run', 'phase': status, 'run_id': context.run_id, 'outcome': outcome, 'outputs': file_outputs,
    })
    return run_result
