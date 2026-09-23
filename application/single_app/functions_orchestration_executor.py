# functions_orchestration_executor.py

"""
The deterministic step engine: it runs a validated plan, and it is the only thing that does.

The planner writes a plan and never touches it again; this module walks that plan's steps in
dependency order, calls one adapter per step, threads each step's evidence into a shared
context, and hands the accumulated evidence to the terminal ``respond`` step. Nothing here
chooses *what* to do -- that was the planner's job and the schema already validated the
result -- so the executor's whole responsibility is to run the plan faithfully and to fail
safely when the world has changed underneath it.

Two properties are worth stating because they are the reason this is an engine and not a
loop:

**A plan always attempts an answer.** A gather step can fail, be skipped because its
dependency failed, or be cut off by a budget, and the run still reaches ``respond`` and
answers with whatever evidence survived. The terminal step is therefore exempt from every
skip rule except an explicit cancellation. A failed answer completion still fails the run.

**Access is re-checked at answer time, not trusted from plan time.** Between the planner
naming a document and the executor answering from it, the user's access to that document can
be revoked. So before ``respond`` runs, the authorized source manifest is re-resolved and
compared against the one captured when execution began; evidence for any document that is no
longer authorized is dropped and noted, rather than being synthesised into an answer the user
is no longer allowed to see. This mirrors the re-authorization the mixed-source workflow
runner already performs, because the failure it prevents is the same one.

Re-planning is *surfaced, not performed*. A step can hand back a ``replan_hint``; the executor
collects those and returns them, bounded by the replan budget, but it never calls the planner
itself. The route owns that loop, because only the route can decide to spend another planner
round trip.

Version: 0.261.130
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
from content_screening.contracts import DocumentHeldError, ScreeningError
from functions_appinsights import log_event
from functions_mixed_source_orchestration import (
    AUTHORIZATION_STATUS_AUTHORIZED,
    MixedSourceCancellationError,
    compare_reauthorized_source_manifests,
)
from functions_orchestration_adapters import (
    get_adapter as _default_get_adapter,
    resolve_context_source_manifest,
    synthesize_source_manifest_from_evidence,
)
from functions_orchestration_context import (
    ElicitationContextError,
    build_elicitation_user_request,
    resolve_elicitation_references,
)
from functions_orchestration_registry import (
    CAPABILITY_RESPOND, CAPABILITY_TABULAR_ANALYZE, DEPENDENCY_PLAN_CONTRACT_VERSION,
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
    plan_contract_version,
    validate_plan,
)
from functions_orchestration_checkpoints import (
    CheckpointError, restore_context, step_input_fingerprint,
)
from functions_orchestration_timing import (
    execution_timeout_seconds, initial_execution_deadline, positive_setting_int as _setting_int,
)

_LOG_PREFIX = '[ORCHESTRATION_EXECUTOR]'

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
    """The evidence and ambient state one run accumulates as its steps execute.

    Adapters read this by duck typing -- they never import this class -- so the attribute
    names here are the actual contract with the adapters, not the constructor signature. The
    accumulators (``evidence``, ``citations``, ``artifacts``, ``notes``, ``token_usage``) are
    what each step contributes to and what the terminal step answers from.

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
        plan_contract_version=1,
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
        if type(plan_contract_version) is not int or plan_contract_version not in (1, DEPENDENCY_PLAN_CONTRACT_VERSION):
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
        if self.plan_contract_version != DEPENDENCY_PLAN_CONTRACT_VERSION:
            raise ResultContractError('result_version_unsupported')
        capability = get_capability(step.get('capability_id'), contract_version=self.plan_contract_version)
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
        if (
            self.plan_contract_version != DEPENDENCY_PLAN_CONTRACT_VERSION
            or not callable(self._result_input_fingerprint_for_step)
        ):
            raise ResultContractError('result_input_fingerprint_required')
        value = self._result_input_fingerprint_for_step(step_id)
        digest(value)
        return value

    def merge_step_result(self, result, step_id=None):
        """Fold one step's accumulables into the run.

        Failed steps return empty lists, so merging them is harmless; that is deliberate, so
        the caller never has to branch on status before merging.

        ``step_id`` records which documents *this* step reached, which is what lets a later
        step act on what an earlier one found rather than on what the planner guessed at
        plan time.
        """
        if not isinstance(result, dict):
            return
        self.evidence.extend(result.get('evidence') or [])
        self.citations.extend(result.get('citations') or [])
        self.artifacts.extend(result.get('artifacts') or [])
        self.notes.extend(result.get('notes') or [])
        for descriptor in result.get('saved_analyses') or []:
            if descriptor not in self.saved_analyses:
                self.saved_analyses.append(deepcopy(descriptor))

        found_here = []
        for envelope in result.get('evidence') or []:
            document_id = _text((envelope or {}).get('document_id'))
            if document_id and document_id not in self.documents_touched:
                self.documents_touched.append(document_id)
            if document_id and document_id not in found_here:
                found_here.append(document_id)
        if step_id:
            self.step_documents[step_id] = found_here


# --------------------------------------------------------------------------------------
# Plan traversal
# --------------------------------------------------------------------------------------

def _plan_steps(plan):
    steps = (plan or {}).get('steps')
    return [step for step in (steps or []) if isinstance(step, dict) and step.get('step_id')]


def _topological_order(steps, terminal_step_id=None):
    """Order steps so every step follows its dependencies.

    The validator already emits a topologically ordered, acyclic plan, so this is a safety
    net rather than the primary guarantee -- but it also lets the executor keep working if a
    persisted plan from another build is shaped slightly differently. A depth-first post-order
    yields dependencies first; the terminal step is then forced to the very end, because the
    single invariant the rest of the engine leans on is that ``respond`` runs last.
    """
    by_id = {step.get('step_id'): step for step in steps}
    ordered = []
    state = {}  # step_id -> 0 visiting, 1 done

    def visit(step_id):
        if state.get(step_id) == 1 or state.get(step_id) == 0:
            # Done, or a back-edge into a step still on the stack: ignore rather than recurse,
            # which both dedups and breaks any residual cycle.
            return
        state[step_id] = 0
        step = by_id.get(step_id)
        if step is not None:
            for dependency in step.get('depends_on') or []:
                if dependency in by_id and dependency != step_id:
                    visit(dependency)
        state[step_id] = 1
        if step is not None:
            ordered.append(step)

    for step in steps:
        visit(step.get('step_id'))

    if terminal_step_id:
        ordered = [step for step in ordered if step.get('step_id') != terminal_step_id]
        terminal = by_id.get(terminal_step_id)
        if terminal is not None:
            ordered.append(terminal)
    return ordered


def _find_terminal_step_id(steps):
    for step in steps:
        if step.get('capability_id') == CAPABILITY_RESPOND:
            return step.get('step_id')
    # No declared terminal (a malformed plan): treat the last step as terminal so the run
    # still finishes deterministically instead of never producing an answer.
    return steps[-1].get('step_id') if steps else None


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

def _run_single_step(step, context, settings, user_id, emit, step_cancel, get_adapter):
    capability_id = step.get('capability_id')
    adapter = get_adapter(capability_id)
    if adapter is None:
        return build_step_result(
            status=STEP_STATUS_FAILED,
            summary=f'No adapter is registered for capability {capability_id}.',
            error=f'Unknown capability: {capability_id}',
        )
    try:
        binding_scope = getattr(context, 'step_model_scope', None)
        with binding_scope(step) if binding_scope else nullcontext():
            result = adapter(
                step,
                context,
                settings=settings,
                user_id=user_id,
                emit=emit,
                cancel_requested=step_cancel,
            )
            if isinstance(result, dict) and step.get('model_binding'):
                result['model_binding'] = deepcopy(step['model_binding'])
                model = getattr(context, 'step_model', None)
                if model is not None:
                    result['model_binding']['selection'] = model.answer_model_selection()
                    result['model_binding']['reasoning'] = deepcopy(model.reasoning_resolution)
    except MixedSourceCancellationError:
        return build_step_result(status=STEP_STATUS_CANCELLED, summary='Step was cancelled.')
    except Exception as exc:
        # Adapters promise not to raise; the executor still cannot trust that promise, because
        # one adapter throwing must not abandon a plan the rest could still answer.
        log_event(
            f'{_LOG_PREFIX} Adapter for {capability_id} raised: {exc}',
            extra={'run_id': getattr(context, 'run_id', None), 'step_id': step.get('step_id')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return build_step_result(
            status=STEP_STATUS_FAILED,
            summary='The step raised an unexpected error.',
            failure=failure_from_exception(exc, answering=capability_id == CAPABILITY_RESPOND),
        )

    if not isinstance(result, dict) or 'status' not in result:
        return build_step_result(
            status=STEP_STATUS_FAILED,
            summary='The step returned an invalid result.',
            error='Adapter did not return a StepResult.',
        )
    return result


def _dependency_blocked(step, statuses):
    """Whether a step should be skipped because a dependency did not complete.

    Only a dependency that ran and did not complete blocks; a dependency that is merely not
    yet recorded does not, since topological order guarantees dependencies are resolved
    first. Optional steps are never blocked -- the planner marked them able to proceed on
    partial inputs -- and the caller exempts the terminal step entirely.
    """
    for dependency in step.get('depends_on') or []:
        status = statuses.get(dependency)
        if status in (STEP_STATUS_FAILED, STEP_STATUS_SKIPPED, STEP_STATUS_CANCELLED):
            return True
    return False


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
    if getattr(context, 'plan_contract_version', 1) == DEPENDENCY_PLAN_CONTRACT_VERSION:
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
# Re-authorization before finalization
# --------------------------------------------------------------------------------------

def _reauthorize_before_finalization(context, settings, user_id, cancel_requested):
    """Re-resolve access and drop evidence for anything no longer authorized.

    Returns a small report for the run result. The manifest it leaves on the context is what
    the terminal step builds its handoff from, so this both enforces access and supplies the
    coverage manifest in one pass.
    """
    revalidate_context = getattr(context, 'revalidate_conversation_context', None)
    if callable(revalidate_context):
        revalidate_context()
    evidence = [envelope for envelope in (context.evidence or []) if isinstance(envelope, dict)]
    if not evidence:
        context.source_manifest = []
        return {'checked': False, 'reason': 'no_evidence', 'dropped_document_ids': []}

    touched = []
    for envelope in evidence:
        document_id = _text(envelope.get('document_id'))
        if document_id and document_id not in touched:
            touched.append(document_id)

    try:
        fresh_manifest = resolve_context_source_manifest(
            context,
            touched,
            settings=settings,
            user_id=user_id,
            cancel_requested=cancel_requested,
        )
    except MixedSourceCancellationError:
        raise
    except Exception as exc:
        if getattr(context, 'durable_checkpoints', False) or context.saved_analyses:
            raise ElicitationContextError('Sources could not be reauthorized.') from exc
        if context.elicitation_references:
            log_event(
                f'{_LOG_PREFIX} Accepted source re-authorization failed.',
                extra={'exception_type': type(exc).__name__}, level=logging.WARNING,
            )
            raise ElicitationContextError('Accepted answer sources could not be rechecked. Please retry the run.') from exc
        log_event(
            f'{_LOG_PREFIX} Re-authorization resolve failed; answering on gather-time authorization: {exc}',
            extra={'run_id': getattr(context, 'run_id', None)},
            level=logging.WARNING,
        )
        fresh_manifest = None

    if not fresh_manifest:
        if getattr(context, 'durable_checkpoints', False) or context.saved_analyses:
            raise ElicitationContextError('Sources could not be reauthorized.')
        if context.elicitation_references:
            raise ElicitationContextError('Accepted answer sources could not be rechecked. Please retry the run.')
        # The resolver could not run (no resolver wired, or it errored). The evidence was
        # authorized when it was gathered, so answering from it is the same guarantee the
        # non-orchestrated chat path already gives; the fallback manifest just lets the
        # handoff carry it. The note keeps this honest to the user.
        context.source_manifest = synthesize_source_manifest_from_evidence(evidence)
        context.notes.append('Re-authorization was unavailable; answered using gather-time authorization.')
        return {'checked': False, 'reason': 'resolver_unavailable', 'dropped_document_ids': []}

    execution_manifest = context.execution_manifest or synthesize_source_manifest_from_evidence(evidence)
    comparison = compare_reauthorized_source_manifests(execution_manifest, fresh_manifest)

    authorized_ids = {
        _text(entry.get('document_id'))
        for entry in fresh_manifest
        if isinstance(entry, dict)
        and entry.get('authorization_status') == AUTHORIZATION_STATUS_AUTHORIZED
    }
    dropped = [document_id for document_id in touched if document_id not in authorized_ids]
    accepted_ids = {
        reference['id'] for reference in context.elicitation_references
        if reference.get('kind') in ('document', 'chat_attachment')
    }
    if accepted_ids.intersection(dropped):
        raise ElicitationContextError('An accepted answer source is no longer available. Please update the answer.')

    if dropped:
        if getattr(context, 'durable_checkpoints', False) or context.saved_analyses:
            raise ElicitationContextError('A saved source is no longer available.')
        context.evidence = [
            envelope for envelope in evidence
            if _text(envelope.get('document_id')) not in dropped
        ]
        context.citations = [
            citation for citation in context.citations or []
            if not isinstance(citation, dict) or _text(citation.get('document_id')) not in dropped
        ]
        # Rebuild documents_touched to match the surviving evidence, so the run record does
        # not claim to have used a document whose evidence was just dropped.
        context.documents_touched = [
            document_id for document_id in context.documents_touched if document_id not in dropped
        ]
        context.notes.append(
            f'Dropped evidence for {len(dropped)} source(s) that were no longer authorized at answer time.'
        )
        log_event(
            f'{_LOG_PREFIX} Dropped {len(dropped)} de-authorized source(s) before finalization.',
            extra={'run_id': getattr(context, 'run_id', None), 'dropped_count': len(dropped)},
            level=logging.WARNING,
        )

    context.source_manifest = [
        entry for entry in fresh_manifest
        if isinstance(entry, dict)
        and entry.get('authorization_status') == AUTHORIZATION_STATUS_AUTHORIZED
    ]
    return {
        'checked': True,
        'dropped_document_ids': dropped,
        'authorization_failure_count': comparison.get('authorization_failure_count', 0),
        'source_version_changed_count': comparison.get('source_version_changed_count', 0),
    }


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
    """Run a validated plan to an answer and return the run result.

    ``persist`` is an optional callable ``persist(record_type, record)`` where ``record_type``
    is ``'run'`` or ``'step'``; it is how the route writes progress to Cosmos without this
    module importing the persistence layer (which imports config). ``get_adapter`` is
    injectable for the same reason the persistence is: it lets a test drive the engine with
    fake adapters without importing the real ones.
    """
    version = plan_contract_version(plan)
    if version != getattr(context, 'plan_contract_version', 1):
        raise ResultContractError('result_version_unsupported')
    if version == DEPENDENCY_PLAN_CONTRACT_VERSION:
        return _execute_dependency_plan(
            plan, context, settings=settings, user_id=user_id, emit=emit,
            cancel_requested=cancel_requested, persist=persist, get_adapter=get_adapter,
            checkpoints=checkpoints,
        )
    settings = settings if isinstance(settings, dict) else {}
    get_adapter = get_adapter or _default_get_adapter
    cancel_probe = _make_cancel_probe(cancel_requested)

    steps = _plan_steps(plan)
    terminal_step_id = _find_terminal_step_id(steps)
    ordered_steps = _topological_order(steps, terminal_step_id=terminal_step_id)

    max_steps = _setting_int(settings, 'chat_orchestration_max_steps', _DEFAULT_MAX_STEPS)
    step_timeout = _setting_int(settings, 'chat_orchestration_step_timeout_seconds', _DEFAULT_STEP_TIMEOUT_SECONDS)
    total_timeout = execution_timeout_seconds(settings)
    max_replans = _setting_int(settings, 'chat_orchestration_max_replans', _DEFAULT_MAX_REPLANS)

    run_started_monotonic = time.monotonic()
    total_deadline = run_started_monotonic + total_timeout if total_timeout else None

    _persist(persist, 'run', {
        'run_id': getattr(context, 'run_id', None),
        'status': PLAN_STATUS_RUNNING,
        'started_at': _now_iso(),
    })

    def check_accepted_context():
        resolve_elicitation_references(
            context.elicitation_references, user_id, context.conversation_id, settings=settings,
        )

    def unavailable_context_result():
        failure = build_failure('context_unavailable')
        result = {
            'run_id': context.run_id,
            'status': PLAN_STATUS_FAILED,
            'completed_at': _now_iso(),
            'message': failure_explanation([failure]),
            'error': failure['message'], 'failure': failure, 'failures': [failure], 'outcome': 'failed',
            'evidence': [], 'citations': [], 'artifacts': [],
            'reauthorization': {'checked': True, 'reason': 'elicitation_context_unavailable'},
        }
        _persist(persist, 'run', result)
        return result

    try:
        check_accepted_context()
    except ElicitationContextError:
        return unavailable_context_result()

    # Capture the plan-time authorized manifest so the finalization re-check has something to
    # compare against. Only worth resolving when the plan actually names documents.
    plan_document_ids = _string_list(
        _collect_plan_document_ids(steps)
        + [item['id'] for item in context.elicitation_references if item.get('kind') in ('document', 'chat_attachment')]
    )
    if plan_document_ids:
        try:
            context.execution_manifest = resolve_context_source_manifest(
                context,
                plan_document_ids,
                settings=settings,
                user_id=user_id,
                cancel_requested=cancel_probe,
            )
        except MixedSourceCancellationError:
            context.execution_manifest = []
        except Exception as exc:
            log_event(
                f'{_LOG_PREFIX} Could not capture execution manifest; re-auth will compare against evidence: {exc}',
                extra={'run_id': getattr(context, 'run_id', None)},
                level=logging.WARNING,
            )
            context.execution_manifest = []

    statuses = {}
    step_records = []
    replan_hints = []
    total_units = len(ordered_steps)
    cancelled = False
    budget_note_emitted = False
    executed_non_terminal = 0
    terminal_result = None
    reauthorization = {'checked': False, 'reason': 'not_reached', 'dropped_document_ids': []}
    first_error = None
    if checkpoints is not None:
        context.durable_checkpoints = True
        checkpoints = checkpoints(context) if callable(checkpoints) else checkpoints
        checkpoints.initialize()

    def persist_step(record):
        if checkpoints is not None:
            checkpoints.save_step(record)
        else:
            _persist(persist, 'step', record)

    for index, step in enumerate(ordered_steps):
        step_id = step.get('step_id')
        is_terminal = step_id == terminal_step_id

        # Cancellation aborts everything, terminal included: a user who cancels does not want
        # the answer written from half a plan.
        if cancelled or cancel_probe():
            cancelled = True
            statuses[step_id] = STEP_STATUS_CANCELLED
            record = _step_record(context, step, index, STEP_STATUS_CANCELLED, None, None, None, 0)
            step_records.append(record)
            record['failure'] = build_failure('user_cancelled', step_id=step_id, capability_id=step.get('capability_id'))
            if not context.failures:
                context.failures.append(record['failure'])
            persist_step(record)
            _emit(emit, {'type': 'step', 'phase': STEP_STATUS_CANCELLED, 'step_id': step_id,
                         'capability_id': step.get('capability_id'), 'step_index': index,
                         'completed': index + 1, 'total': total_units})
            continue

        try:
            check_accepted_context()
        except ElicitationContextError:
            return unavailable_context_result()

        # Re-authorize immediately before the terminal step, so the answer is written from
        # evidence that is still authorized rather than evidence that merely was.
        if is_terminal:
            try:
                reauthorization = _reauthorize_before_finalization(context, settings, user_id, cancel_probe)
            except MixedSourceCancellationError:
                cancelled = True
                statuses[step_id] = STEP_STATUS_CANCELLED
                record = _step_record(context, step, index, STEP_STATUS_CANCELLED, None, None, None, 0)
                step_records.append(record)
                persist_step(record)
                continue
            except ElicitationContextError:
                return unavailable_context_result()

        # Disabled steps never run; a dependent non-optional step will then skip in turn.
        if not is_terminal and step.get('enabled', True) is False:
            statuses[step_id] = STEP_STATUS_SKIPPED
            result = build_step_result(status=STEP_STATUS_SKIPPED, summary='Step is disabled.')
            record = _step_record(context, step, index, STEP_STATUS_SKIPPED, result, None, None, 0)
            step_records.append(record)
            persist_step(record)
            _emit(emit, {'type': 'step', 'phase': STEP_STATUS_SKIPPED, 'step_id': step_id,
                         'capability_id': step.get('capability_id'), 'step_index': index,
                         'completed': index + 1, 'total': total_units})
            continue

        # A budget cut -- step count or wall-clock -- stops further gathering but still lets
        # the run answer with what it has, so a slow plan degrades to a partial answer rather
        # than to nothing.
        over_total_time = bool(total_deadline and time.monotonic() > total_deadline)
        over_step_budget = (not is_terminal) and executed_non_terminal >= max_steps
        if over_total_time or over_step_budget:
            statuses[step_id] = STEP_STATUS_SKIPPED
            reason = 'the time budget was exhausted' if over_total_time else 'the step budget was reached'
            result = build_step_result(status=STEP_STATUS_SKIPPED, summary=f'Skipped because {reason}.')
            result['failure'] = build_failure('run_timeout' if over_total_time else 'step_budget', step_id=step_id, capability_id=step.get('capability_id'))
            context.failures.append(result['failure'])
            record = _step_record(context, step, index, STEP_STATUS_SKIPPED, result, None, None, 0)
            step_records.append(record)
            persist_step(record)
            if not budget_note_emitted:
                context.notes.append(f'Some steps were skipped because {reason}.')
                budget_note_emitted = True
            _emit(emit, {'type': 'step', 'phase': STEP_STATUS_SKIPPED, 'step_id': step_id,
                         'capability_id': step.get('capability_id'), 'step_index': index,
                         'completed': index + 1, 'total': total_units})
            continue

        # A dependency that did not complete blocks a required step; optional and terminal
        # steps are exempt.
        if not is_terminal and not step.get('optional', False) and _dependency_blocked(step, statuses):
            statuses[step_id] = STEP_STATUS_SKIPPED
            result = build_step_result(
                status=STEP_STATUS_SKIPPED,
                summary='Skipped because a required earlier step did not complete.',
            )
            record = _step_record(context, step, index, STEP_STATUS_SKIPPED, result, None, None, 0)
            step_records.append(record)
            persist_step(record)
            _emit(emit, {'type': 'step', 'phase': STEP_STATUS_SKIPPED, 'step_id': step_id,
                         'capability_id': step.get('capability_id'), 'step_index': index,
                         'completed': index + 1, 'total': total_units})
            continue

        reused = checkpoints.before_step(step) if checkpoints is not None else None
        input_fingerprint = (
            step_input_fingerprint(step, context, checkpoints.binding) if checkpoints is not None else None
        )
        if reused:
            restore_context(context, reused)
            result = deepcopy(reused['result'])
            context.step_token_usage = deepcopy(reused.get('usage') or {})
            checkpoints.commit(step, result, input_fingerprint, reused=reused)
            record = _step_record(context, step, index, STEP_STATUS_COMPLETED, result, None, _now_iso(), 0)
            record.update({
                'checkpoint_available': True, 'reused': True,
                'reused_from_run_id': (reused.get('provenance') or {}).get('run_id'),
                'summary': 'Reused saved result',
                'token_usage': {}, 'reused_token_usage': deepcopy(reused.get('usage') or {}),
            })
            step_records.append(record)
            statuses[step_id] = STEP_STATUS_COMPLETED
            persist_step(record)
            _emit(emit, {
                'type': 'step', 'phase': STEP_STATUS_COMPLETED, **record,
                'completed': index + 1, 'total': total_units,
            })
            continue

        # Cooperative interruption retains its measured cause. A callback may stop
        # blocked providers, but a deadline is never evidence of the user pressing Stop.
        step_deadline = time.monotonic() + step_timeout if step_timeout else None
        control = {'reason': None}

        def _step_cancel(_step_deadline=step_deadline):
            if control['reason']:
                return True
            if cancel_probe():
                control['reason'] = 'user_cancelled'
                return True
            now = time.monotonic()
            if total_deadline and now >= total_deadline:
                control['reason'] = 'run_timeout'
                return True
            if _step_deadline and now >= _step_deadline:
                control['reason'] = 'step_timeout'
                return True
            return False

        started_at = _now_iso()
        running_record = _step_record(context, step, index, STEP_STATUS_RUNNING, None, started_at, None, 0)
        persist_step(running_record)
        _emit(emit, {'type': 'step', 'phase': STEP_STATUS_RUNNING, 'step_id': step_id,
                     'capability_id': step.get('capability_id'), 'step_index': index,
                     'title': step.get('title'), 'completed': index, 'total': total_units})

        started_monotonic = time.monotonic()
        usage_before = deepcopy(context.token_usage)
        prompt_usage_before = deepcopy(getattr(context, 'prompt_token_usage', {}) or {})
        result = _run_single_step(step, context, settings, user_id, emit, _step_cancel, get_adapter)
        _step_cancel()
        reason = control['reason']
        if reason or result.get('status') in (STEP_STATUS_FAILED, STEP_STATUS_CANCELLED):
            failure = build_failure(
                reason or ('execution_interrupted' if result.get('status') == STEP_STATUS_CANCELLED else 'step_failed'),
                step_id=step_id, capability_id=step.get('capability_id'),
            ) if reason or not result.get('failure') else safe_failure(
                result['failure'], step_id=step_id, capability_id=step.get('capability_id'),
            )
            # Failure details are not trusted data. No provider body, adapter error
            # prose, partial diagnostic citations or stack trace reaches the answer.
            result = build_step_result(
                status=STEP_STATUS_CANCELLED if reason == 'user_cancelled' else STEP_STATUS_FAILED,
                summary=failure['message'], error=failure['message'], failure=failure,
            )
            context.failures.append(failure)
            log_event(
                f'{_LOG_PREFIX} Step did not complete.',
                extra={
                    'run_id': context.run_id, 'step_id': step_id,
                    'attempt_index': context.attempt_index, 'reason_code': failure['code'],
                }, level=logging.WARNING,
            )
        context.step_token_usage = {
            key: value - usage_before.get(key, 0)
            for key, value in context.token_usage.items()
            if type(value) is int and type(usage_before.get(key, 0)) is int
        }
        for key, value in (getattr(context, 'prompt_token_usage', {}) or {}).items():
            if type(value) is int and type(prompt_usage_before.get(key, 0)) is int:
                context.step_token_usage[key] = context.step_token_usage.get(key, 0) + value - prompt_usage_before.get(key, 0)
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        completed_at = _now_iso()

        status = result.get('status') or STEP_STATUS_COMPLETED
        statuses[step_id] = status

        if is_terminal:
            terminal_result = result
        else:
            # Terminal citations include accumulated evidence plus freshly recalled memory.
            # Return that final set below instead of merging and duplicating its sources.
            context.merge_step_result(result, step_id=step_id)
            executed_non_terminal += 1

        replan_hint = _text(result.get('replan_hint'))
        if replan_hint and len(replan_hints) < max_replans:
            replan_hints.append({'step_id': step_id, 'capability_id': step.get('capability_id'), 'hint': replan_hint})

        if status == STEP_STATUS_FAILED and not first_error:
            first_error = result.get('error') or result.get('summary')

        if status == STEP_STATUS_CANCELLED:
            cancelled = True

        record = _step_record(context, step, index, status, result, started_at, completed_at, duration_ms)
        record['effects_uncertain'] = (
            step.get('capability_id') in ('agent_invoke', 'action_invoke') and status != STEP_STATUS_COMPLETED
        )
        record['token_usage'] = deepcopy(context.step_token_usage)
        if checkpoints is not None and status == STEP_STATUS_COMPLETED:
            checkpoints.commit(step, result, input_fingerprint)
            record['checkpoint_available'] = True
        step_records.append(record)
        persist_step(record)
        _emit(emit, {'type': 'step', 'phase': status, 'step_id': step_id,
                     'capability_id': step.get('capability_id'), 'step_index': index,
                     'summary': record['summary'], 'failure': record['failure'],
                     **({'model_binding': record['model_binding']} if record.get('model_binding') else {}),
                     'checkpoint_available': record['checkpoint_available'],
                     'completed': index + 1, 'total': total_units})

    # Resolve overall status. Cancellation wins; otherwise the run is complete when the
    # terminal step produced an answer, and failed when it did not.
    terminal_completed = bool(
        terminal_result and terminal_result.get('status') == STEP_STATUS_COMPLETED
    )
    if cancelled:
        run_status = PLAN_STATUS_CANCELLED
    elif terminal_completed and not context.failures and not any(
        row['status'] == STEP_STATUS_PENDING for row in step_records
    ):
        run_status = PLAN_STATUS_COMPLETED
    else:
        run_status = PLAN_STATUS_FAILED

    message = _text((terminal_result or {}).get('message')) if terminal_result else ''
    partial = bool(context.evidence or context.notes or any(
        row['status'] == STEP_STATUS_COMPLETED and row['capability_id'] != CAPABILITY_RESPOND
        for row in step_records
    ))
    outcome = 'cancelled' if cancelled else (
        'completed' if run_status == PLAN_STATUS_COMPLETED else 'partial' if partial else 'failed'
    )
    if context.failures or not message:
        explanation = failure_explanation(context.failures, partial=partial, cancelled=cancelled)
        message = f'{message}\n\n{explanation}' if message else explanation

    capabilities_used = []
    for record in step_records:
        if record['status'] == STEP_STATUS_COMPLETED and record['capability_id']:
            if record['capability_id'] not in capabilities_used:
                capabilities_used.append(record['capability_id'])

    documents_touched = _documents_touched_records(context)

    run_result = {
        'run_id': getattr(context, 'run_id', None),
        'plan_id': getattr(context, 'plan_id', None) or (plan or {}).get('plan_id'),
        'conversation_id': getattr(context, 'conversation_id', None),
        'status': run_status,
        'outcome': outcome,
        'failure': context.failures[0] if context.failures else None,
        'failures': list(context.failures),
        'message': message,
        'summary': _text((terminal_result or {}).get('summary')),
        'evidence': list(context.evidence or []),
        'citations': list((terminal_result or {}).get('citations') or context.citations or []),
        'artifacts': list(context.artifacts or []),
        'notes': list(context.notes or []),
        'documents_touched': documents_touched,
        'capabilities_used': capabilities_used,
        'token_usage': dict(context.token_usage or {}),
        'steps': step_records,
        'replan_hints': replan_hints,
        'reauthorization': reauthorization,
        'completed_at': _now_iso(),
        'error': first_error if run_status == PLAN_STATUS_FAILED else None,
    }
    if context.saved_analyses:
        run_result['saved_analyses'] = deepcopy(context.saved_analyses)
    if context.analysis_result_contexts:
        run_result['analysis_result_contexts'] = deepcopy(context.analysis_result_contexts)
    if (terminal_result or {}).get('analysis_consumption'):
        run_result['analysis_consumption'] = deepcopy(terminal_result['analysis_consumption'])

    _persist(persist, 'run', {
        'run_id': getattr(context, 'run_id', None),
        'status': run_status,
        'outcome': outcome,
        'failure': run_result['failure'],
        'failures': run_result['failures'],
        'completed_at': run_result['completed_at'],
        'error': run_result['error'],
        'documents_touched': documents_touched,
        'artifacts': run_result['artifacts'],
        'capabilities_used': capabilities_used,
        'token_usage': run_result['token_usage'],
        **({'saved_analyses': run_result['saved_analyses']} if context.saved_analyses else {}),
        **({'analysis_result_contexts': context.analysis_result_contexts} if context.analysis_result_contexts else {}),
        **({'analysis_consumption': run_result['analysis_consumption']} if run_result.get('analysis_consumption') else {}),
    })

    _emit(emit, {'type': 'run', 'phase': run_status, 'run_id': getattr(context, 'run_id', None)})

    return run_result


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
    # Bridge construction is an execution dependency, never a legacy dispatch dependency.
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
        # Native failure contracts are execution-only, not legacy startup dependencies.
        from functions_orchestration_native_results import raise_native_orchestration_infrastructure_failure

        raise_native_orchestration_infrastructure_failure(error)


def _run_dependency_step(
    step, context, settings, user_id, emit, cancel_probe, resolver, *,
    input_fingerprint, native_pending=None,
):
    # Dispatch the additive policy only for the new contract; legacy execution is unchanged.
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
        with orchestration_file_policy(allow_generated_files=step['role'] == 'render'):
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
        # only the admitted identity; load the output contract outside legacy startup.
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
    # Keep concrete output-service dependencies out of legacy runtime bootstrap.
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


def _documents_touched_records(context):
    """The touched documents as ledger-shaped records, named from the manifest when possible."""
    display_by_id = {}
    for entry in (getattr(context, 'source_manifest', None) or []):
        if isinstance(entry, dict):
            document_id = _text(entry.get('document_id'))
            if document_id:
                display_by_id[document_id] = _text(entry.get('display_name')) or None

    records = []
    for document_id in getattr(context, 'documents_touched', None) or []:
        records.append({
            'document_id': document_id,
            'display_name': display_by_id.get(document_id),
        })
    return records
