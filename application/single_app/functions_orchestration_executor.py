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

**A plan always produces an answer.** A gather step can fail, be skipped because its
dependency failed, or be cut off by a budget, and the run still reaches ``respond`` and
answers with whatever evidence survived. The terminal step is therefore exempt from every
skip rule; the only thing that stops it is an explicit cancellation.

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

Version: 0.261.059
"""

import logging
import time
from datetime import datetime, timezone

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
from functions_orchestration_registry import CAPABILITY_RESPOND
from functions_orchestration_schema import (
    PLAN_STATUS_CANCELLED,
    PLAN_STATUS_COMPLETED,
    PLAN_STATUS_FAILED,
    PLAN_STATUS_RUNNING,
    STEP_STATUS_CANCELLED,
    STEP_STATUS_COMPLETED,
    STEP_STATUS_FAILED,
    STEP_STATUS_RUNNING,
    STEP_STATUS_SKIPPED,
    build_step_result,
)

_LOG_PREFIX = '[ORCHESTRATION_EXECUTOR]'

# Budget fallbacks for when a setting is absent or unparseable. Chosen to match the shipped
# defaults in functions_settings so a missing settings dict behaves like the default config
# rather than like an unbounded run.
_DEFAULT_MAX_STEPS = 8
_DEFAULT_STEP_TIMEOUT_SECONDS = 120
_DEFAULT_TOTAL_TIMEOUT_SECONDS = 600
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


def _setting_int(settings, key, default):
    try:
        value = int((settings or {}).get(key))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


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
        except Exception:
            return False

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
    """

    def __init__(
        self,
        *,
        run_id=None,
        plan_id=None,
        conversation_id=None,
        user_id=None,
        turn_index=0,
        invoke_prompt=None,
        user_message='',
        user_message_id=None,
        chat_type='personal',
        selection_mode=None,
        doc_scope='all',
        active_group_ids=None,
        active_group_id=None,
        active_public_workspace_id=None,
        gpt_model=None,
        model_context=None,
        request_correlation_id=None,
        durable_execution_callback=None,
        resolve_source_manifest=None,
    ):
        self.run_id = run_id
        self.plan_id = plan_id
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.turn_index = turn_index

        self.invoke_prompt = invoke_prompt
        self.user_message = user_message
        self.user_message_id = user_message_id
        self.chat_type = chat_type

        self.selection_mode = selection_mode
        self.doc_scope = doc_scope
        self.active_group_ids = list(active_group_ids or [])
        self.active_group_id = active_group_id
        self.active_public_workspace_id = active_public_workspace_id

        self.gpt_model = gpt_model
        self.model_context = model_context
        self.request_correlation_id = request_correlation_id
        self.durable_execution_callback = durable_execution_callback

        # A route can inject a pre-scoped resolver (document_ids -> manifest); when absent the
        # adapters fall back to the real resolver. Held here so re-authorization and the
        # tabular adapter use the same seam.
        self.resolve_source_manifest = resolve_source_manifest

        # Accumulators.
        self.evidence = []
        self.citations = []
        self.artifacts = []
        self.notes = []
        self.token_usage = {}

        # Documents any step produced evidence for, in first-seen order.
        self.documents_touched = []

        # The manifest captured when execution began, and the authorized manifest resolved
        # again before finalization; the second is what the handoff is built from.
        self.execution_manifest = []
        self.source_manifest = []

    def merge_step_result(self, result):
        """Fold one step's accumulables into the run.

        Failed steps return empty lists, so merging them is harmless; that is deliberate, so
        the caller never has to branch on status before merging.
        """
        if not isinstance(result, dict):
            return
        self.evidence.extend(result.get('evidence') or [])
        self.citations.extend(result.get('citations') or [])
        self.artifacts.extend(result.get('artifacts') or [])
        self.notes.extend(result.get('notes') or [])
        for envelope in result.get('evidence') or []:
            document_id = _text((envelope or {}).get('document_id'))
            if document_id and document_id not in self.documents_touched:
                self.documents_touched.append(document_id)


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
        result = adapter(
            step,
            context,
            settings=settings,
            user_id=user_id,
            emit=emit,
            cancel_requested=step_cancel,
        )
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
            error=str(exc),
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
    return {
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
    }


def _persist(persist, record_type, record):
    if not callable(persist):
        return
    try:
        persist(record_type, record)
    except Exception as exc:
        # Persistence is a side effect of running the plan, not a condition for it; a failed
        # write is logged and the run continues rather than losing the answer.
        log_event(
            f'{_LOG_PREFIX} Failed to persist {record_type} record: {exc}',
            level=logging.ERROR,
            exceptionTraceback=True,
        )


# --------------------------------------------------------------------------------------
# Re-authorization before finalization
# --------------------------------------------------------------------------------------

def _reauthorize_before_finalization(context, settings, user_id, cancel_requested):
    """Re-resolve access and drop evidence for anything no longer authorized.

    Returns a small report for the run result. The manifest it leaves on the context is what
    the terminal step builds its handoff from, so this both enforces access and supplies the
    coverage manifest in one pass.
    """
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
        log_event(
            f'{_LOG_PREFIX} Re-authorization resolve failed; answering on gather-time authorization: {exc}',
            extra={'run_id': getattr(context, 'run_id', None)},
            level=logging.WARNING,
        )
        fresh_manifest = None

    if not fresh_manifest:
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

    if dropped:
        context.evidence = [
            envelope for envelope in evidence
            if _text(envelope.get('document_id')) not in dropped
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
):
    """Run a validated plan to an answer and return the run result.

    ``persist`` is an optional callable ``persist(record_type, record)`` where ``record_type``
    is ``'run'`` or ``'step'``; it is how the route writes progress to Cosmos without this
    module importing the persistence layer (which imports config). ``get_adapter`` is
    injectable for the same reason the persistence is: it lets a test drive the engine with
    fake adapters without importing the real ones.
    """
    settings = settings if isinstance(settings, dict) else {}
    get_adapter = get_adapter or _default_get_adapter
    cancel_probe = _make_cancel_probe(cancel_requested)

    steps = _plan_steps(plan)
    terminal_step_id = _find_terminal_step_id(steps)
    ordered_steps = _topological_order(steps, terminal_step_id=terminal_step_id)

    max_steps = _setting_int(settings, 'chat_orchestration_max_steps', _DEFAULT_MAX_STEPS)
    step_timeout = _setting_int(settings, 'chat_orchestration_step_timeout_seconds', _DEFAULT_STEP_TIMEOUT_SECONDS)
    total_timeout = _setting_int(settings, 'chat_orchestration_total_timeout_seconds', _DEFAULT_TOTAL_TIMEOUT_SECONDS)
    max_replans = _setting_int(settings, 'chat_orchestration_max_replans', _DEFAULT_MAX_REPLANS)

    run_started_monotonic = time.monotonic()
    total_deadline = run_started_monotonic + total_timeout if total_timeout else None

    _persist(persist, 'run', {
        'run_id': getattr(context, 'run_id', None),
        'status': PLAN_STATUS_RUNNING,
        'started_at': _now_iso(),
    })

    # Capture the plan-time authorized manifest so the finalization re-check has something to
    # compare against. Only worth resolving when the plan actually names documents.
    plan_document_ids = _collect_plan_document_ids(steps)
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
            _persist(persist, 'step', record)
            _emit(emit, {'type': 'step', 'phase': STEP_STATUS_CANCELLED, 'step_id': step_id,
                         'capability_id': step.get('capability_id'), 'step_index': index,
                         'completed': index + 1, 'total': total_units})
            continue

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
                _persist(persist, 'step', record)
                continue

        # Disabled steps never run; a dependent non-optional step will then skip in turn.
        if not is_terminal and step.get('enabled', True) is False:
            statuses[step_id] = STEP_STATUS_SKIPPED
            result = build_step_result(status=STEP_STATUS_SKIPPED, summary='Step is disabled.')
            record = _step_record(context, step, index, STEP_STATUS_SKIPPED, result, None, None, 0)
            step_records.append(record)
            _persist(persist, 'step', record)
            _emit(emit, {'type': 'step', 'phase': STEP_STATUS_SKIPPED, 'step_id': step_id,
                         'capability_id': step.get('capability_id'), 'step_index': index,
                         'completed': index + 1, 'total': total_units})
            continue

        # A budget cut -- step count or wall-clock -- stops further gathering but still lets
        # the run answer with what it has, so a slow plan degrades to a partial answer rather
        # than to nothing.
        over_total_time = bool(total_deadline and time.monotonic() > total_deadline)
        over_step_budget = (not is_terminal) and executed_non_terminal >= max_steps
        if not is_terminal and (over_total_time or over_step_budget):
            statuses[step_id] = STEP_STATUS_SKIPPED
            reason = 'the time budget was exhausted' if over_total_time else 'the step budget was reached'
            result = build_step_result(status=STEP_STATUS_SKIPPED, summary=f'Skipped because {reason}.')
            record = _step_record(context, step, index, STEP_STATUS_SKIPPED, result, None, None, 0)
            step_records.append(record)
            _persist(persist, 'step', record)
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
            _persist(persist, 'step', record)
            _emit(emit, {'type': 'step', 'phase': STEP_STATUS_SKIPPED, 'step_id': step_id,
                         'capability_id': step.get('capability_id'), 'step_index': index,
                         'completed': index + 1, 'total': total_units})
            continue

        # Run it. The per-step deadline is folded into the cancel probe rather than enforced
        # by killing a thread: adapters check cancellation at their own safe points, which is
        # the only portable way to time-bound work that may hold external resources.
        step_deadline = time.monotonic() + step_timeout if step_timeout else None

        def _step_cancel(_step_deadline=step_deadline):
            if cancel_probe():
                return True
            now = time.monotonic()
            if _step_deadline and now > _step_deadline:
                return True
            if total_deadline and now > total_deadline:
                return True
            return False

        _emit(emit, {'type': 'step', 'phase': STEP_STATUS_RUNNING, 'step_id': step_id,
                     'capability_id': step.get('capability_id'), 'step_index': index,
                     'title': step.get('title'), 'completed': index, 'total': total_units})

        started_at = _now_iso()
        started_monotonic = time.monotonic()
        result = _run_single_step(step, context, settings, user_id, emit, _step_cancel, get_adapter)
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        completed_at = _now_iso()

        status = result.get('status') or STEP_STATUS_COMPLETED
        statuses[step_id] = status

        if is_terminal:
            terminal_result = result
        else:
            # The terminal step's citations echo what the run already accumulated; merging
            # them would double every citation, so only non-terminal results are merged.
            context.merge_step_result(result)
            executed_non_terminal += 1

        replan_hint = _text(result.get('replan_hint'))
        if replan_hint and len(replan_hints) < max_replans:
            replan_hints.append({'step_id': step_id, 'capability_id': step.get('capability_id'), 'hint': replan_hint})

        if status == STEP_STATUS_FAILED and not first_error:
            first_error = result.get('error') or result.get('summary')

        if status == STEP_STATUS_CANCELLED:
            # An adapter reporting cancellation (rather than the probe firing between steps)
            # still cancels the run.
            cancelled = True

        record = _step_record(context, step, index, status, result, started_at, completed_at, duration_ms)
        step_records.append(record)
        _persist(persist, 'step', record)
        _emit(emit, {'type': 'step', 'phase': status, 'step_id': step_id,
                     'capability_id': step.get('capability_id'), 'step_index': index,
                     'summary': record['summary'], 'completed': index + 1, 'total': total_units})

    # Resolve overall status. Cancellation wins; otherwise the run is complete when the
    # terminal step produced an answer, and failed when it did not.
    terminal_completed = bool(
        terminal_result and terminal_result.get('status') == STEP_STATUS_COMPLETED
    )
    if cancelled:
        run_status = PLAN_STATUS_CANCELLED
    elif terminal_completed:
        run_status = PLAN_STATUS_COMPLETED
    else:
        run_status = PLAN_STATUS_FAILED

    message = _text((terminal_result or {}).get('message')) if terminal_result else ''

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
        'message': message,
        'summary': _text((terminal_result or {}).get('summary')),
        'evidence': list(context.evidence or []),
        'citations': list(context.citations or []),
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

    _persist(persist, 'run', {
        'run_id': getattr(context, 'run_id', None),
        'status': run_status,
        'completed_at': run_result['completed_at'],
        'error': run_result['error'],
        'documents_touched': documents_touched,
        'artifacts': run_result['artifacts'],
        'capabilities_used': capabilities_used,
        'token_usage': run_result['token_usage'],
    })

    _emit(emit, {'type': 'run', 'phase': run_status, 'run_id': getattr(context, 'run_id', None)})

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
