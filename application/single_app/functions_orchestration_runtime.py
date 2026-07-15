# functions_orchestration_runtime.py
"""Request-scoped execution graph runtime for chat orchestration plans."""

import copy
import json
from collections.abc import Callable, Mapping, MutableMapping
from concurrent.futures import CancelledError, FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone

from functions_appinsights import log_event
from functions_evidence_collectors import apply_evidence_collector_result
from functions_evidence_ledger import (
    add_evidence_source,
    add_execution_failure,
    set_evidence_ledger_status,
)


ORCHESTRATION_RUNTIME_VERSION = 1
ORCHESTRATION_NODE_STATUSES = frozenset({
    'pending',
    'running',
    'succeeded',
    'partial',
    'failed',
    'skipped',
    'blocked',
    'cancelled',
})
ORCHESTRATION_TERMINAL_NODE_STATUSES = frozenset({
    'succeeded',
    'partial',
    'failed',
    'skipped',
    'blocked',
    'cancelled',
})
ORCHESTRATION_RUN_STATUSES = frozenset({
    'pending',
    'running',
    'succeeded',
    'partial',
    'failed',
    'cancelled',
})
ORCHESTRATION_FAILURE_NODE_STATUSES = frozenset({
    'failed',
    'skipped',
    'blocked',
    'cancelled',
})
ORCHESTRATION_PARALLEL_NODE_TYPES = frozenset({'collect', 'plan'})
ORCHESTRATION_REPLAN_NODE_TYPES = frozenset({'collect', 'plan'})
DEFAULT_MAX_PARALLEL_NODES = 1
DEFAULT_MAX_REPLANS = 1
DEFAULT_MAX_RUNTIME_NODES = 32
MAX_NODE_ATTEMPTS = 3
MAX_RUNTIME_TEXT_CHARS = 1000

COLLECTOR_TO_NODE_STATUS = {
    'not_requested': 'skipped',
    'skipped': 'skipped',
    'succeeded': 'succeeded',
    'partial': 'partial',
    'not_found': 'failed',
    'not_available': 'failed',
    'failed': 'failed',
    'unauthorized': 'failed',
}
NODE_TO_SOURCE_STATUS = {
    'succeeded': 'succeeded',
    'partial': 'partial',
    'failed': 'failed',
    'skipped': 'skipped',
    'blocked': 'failed',
    'cancelled': 'cancelled',
}
SOURCE_TO_NODE_STATUS = {
    'succeeded': 'succeeded',
    'partial': 'partial',
    'not_found': 'failed',
    'not_available': 'failed',
    'failed': 'failed',
    'unauthorized': 'failed',
    'skipped': 'skipped',
    'cancelled': 'cancelled',
}
PROVENANCE_LEDGER_SECTIONS = (
    'facts',
    'unsupported_facts',
    'results',
    'citations',
    'artifacts',
    'missing_or_failed',
)
PROGRESS_MESSAGES = {
    'conversation_evidence': 'Reviewing conversation evidence',
    'selected_documents': 'Reviewing selected documents',
    'selected_images': 'Reviewing selected image',
    'workspace_search': 'Searching workspace documents',
    'web_search': 'Searching public web',
    'source_review': 'Reviewing source pages',
    'deep_research': 'Reviewing source pages',
    'selected_agent': 'Calling selected agent',
    'selected_action': 'Calling selected action',
    'evidence_discovery': 'Planning evidence workflow',
    'image_proposal': 'Building image proposal',
    'response': 'Building response',
}


class OrchestrationRuntimeError(ValueError):
    """Raised when an orchestration run or execution graph is invalid."""


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value, *, max_chars=MAX_RUNTIME_TEXT_CHARS):
    normalized = ' '.join(str(value or '').split())
    return normalized[:max_chars].rstrip()


def _normalize_identifier(value, field_name):
    identifier = str(value or '').strip()
    if not identifier:
        raise OrchestrationRuntimeError(f'{field_name} is required')
    return identifier


def _normalize_identifiers(values):
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    normalized = []
    for value in values:
        identifier = str(value or '').strip()
        if identifier and identifier not in normalized:
            normalized.append(identifier)
    return normalized


def _safe_error_type(value):
    normalized = _normalize_text(value, max_chars=120).lower().replace(' ', '_')
    return normalized or 'execution_failed'


@dataclass
class OrchestrationNode:
    """One request-scoped plan step and its runtime lifecycle."""

    id: str
    type: str
    capability: str
    origin: str
    required: bool
    depends_on: list[str] = field(default_factory=list)
    status: str = 'pending'
    attempt_count: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    error_type: str | None = None
    user_message: str | None = None
    debug_message: str | None = None

    @classmethod
    def from_plan_step(cls, step):
        if not isinstance(step, Mapping):
            raise OrchestrationRuntimeError('orchestration steps must be mappings')
        normalized_status = str(step.get('status') or 'pending').strip().lower()
        if normalized_status != 'pending':
            raise OrchestrationRuntimeError('request-scoped runtime steps must start pending')
        return cls(
            id=_normalize_identifier(step.get('id'), 'step id'),
            type=_normalize_identifier(step.get('type'), 'step type'),
            capability=_normalize_identifier(step.get('capability'), 'step capability'),
            origin=_normalize_text(step.get('origin'), max_chars=120) or 'orchestrator',
            required=bool(step.get('required', True)),
            depends_on=_normalize_identifiers(step.get('depends_on')),
        )

    def to_metadata(self):
        metadata = {
            'id': self.id,
            'type': self.type,
            'capability': self.capability,
            'origin': self.origin,
            'required': self.required,
            'status': self.status,
            'depends_on': list(self.depends_on),
            'attempt_count': self.attempt_count,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
        }
        if self.error_type:
            metadata['error'] = {
                'type': self.error_type,
                'user_message': self.user_message,
            }
        return metadata


@dataclass(frozen=True)
class OrchestrationNodeResult:
    """Normalized output returned by a runtime node adapter."""

    status: str = 'succeeded'
    summary: str = ''
    collector_result: Mapping | None = None
    additional_nodes: tuple[Mapping, ...] = ()
    error_type: str | None = None
    user_message: str | None = None
    debug_message: str | None = None
    retryable: bool = False
    attempt_count: int = 1


@dataclass(frozen=True)
class OrchestrationNodeContext:
    """Isolated context supplied to one adapter; evidence_ledger is a read-only snapshot."""

    run_id: str
    task_type: str
    task_profile: str | None
    original_request: str
    node: OrchestrationNode
    evidence_ledger: dict
    is_cancel_requested: Callable[[], bool]


@dataclass(frozen=True)
class OrchestrationNodeAdapter:
    """Trusted adapter; parallel_safe adapters must not depend on Flask request context."""

    execute: Callable[[OrchestrationNodeContext], object]
    parallel_safe: bool = False
    read_only: bool = True
    cancel: Callable[[OrchestrationNodeContext], None] | None = None
    max_attempts: int = 1
    retry_on_exception: bool = False


@dataclass
class OrchestrationRun:
    """In-process execution graph linked to one immutable turn plan and ledger."""

    run_id: str
    task_type: str
    task_profile: str | None
    mode: str
    plan_snapshot: dict
    evidence_ledger: MutableMapping
    nodes: list[OrchestrationNode]
    policy: dict
    max_replans: int = DEFAULT_MAX_REPLANS
    max_nodes: int = DEFAULT_MAX_RUNTIME_NODES
    status: str = 'pending'
    replan_count: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    cancel_requested: bool = False
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_plan(
        cls,
        plan,
        evidence_ledger,
        *,
        max_replans=DEFAULT_MAX_REPLANS,
        max_nodes=DEFAULT_MAX_RUNTIME_NODES,
    ):
        if not isinstance(plan, Mapping):
            raise OrchestrationRuntimeError('plan must be a mapping')
        if not isinstance(evidence_ledger, MutableMapping):
            raise OrchestrationRuntimeError('evidence_ledger must be a mutable mapping')
        run_id = _normalize_identifier(plan.get('run_id'), 'run id')
        if run_id != str(evidence_ledger.get('run_id') or '').strip():
            raise OrchestrationRuntimeError('plan and evidence ledger run ids must match')
        mode = str(plan.get('mode') or '').strip().lower()
        if mode not in {'direct', 'coordinated'}:
            raise OrchestrationRuntimeError('plan mode must be direct or coordinated')
        if mode != str(evidence_ledger.get('orchestration_mode') or '').strip().lower():
            raise OrchestrationRuntimeError('plan and evidence ledger modes must match')

        normalized_max_replans = int(max_replans)
        normalized_max_nodes = int(max_nodes)
        if normalized_max_replans < 0:
            raise OrchestrationRuntimeError('max_replans must be nonnegative')
        if normalized_max_nodes < 1:
            raise OrchestrationRuntimeError('max_nodes must be positive')

        nodes = [OrchestrationNode.from_plan_step(step) for step in plan.get('steps') or []]
        if not nodes:
            raise OrchestrationRuntimeError('plan must contain at least one step')
        if len(nodes) > normalized_max_nodes:
            raise OrchestrationRuntimeError('plan exceeds the runtime node budget')
        _validate_execution_graph(nodes)
        finalizer_nodes = [node for node in nodes if node.type == 'finalize']
        if len(finalizer_nodes) != 1:
            raise OrchestrationRuntimeError('plan must contain exactly one finalizer step')

        policy = plan.get('policy') if isinstance(plan.get('policy'), Mapping) else {}
        return cls(
            run_id=run_id,
            task_type=_normalize_identifier(plan.get('task_type'), 'task type'),
            task_profile=_normalize_text(plan.get('task_profile'), max_chars=120) or None,
            mode=mode,
            plan_snapshot=copy.deepcopy(dict(plan)),
            evidence_ledger=evidence_ledger,
            nodes=nodes,
            policy=copy.deepcopy(dict(policy)),
            max_replans=normalized_max_replans,
            max_nodes=normalized_max_nodes,
        )

    def to_metadata(self):
        node_counts = {
            status: sum(node.status == status for node in self.nodes)
            for status in sorted(ORCHESTRATION_NODE_STATUSES)
            if any(node.status == status for node in self.nodes)
        }
        return {
            'version': ORCHESTRATION_RUNTIME_VERSION,
            'run_id': self.run_id,
            'task_type': self.task_type,
            'task_profile': self.task_profile,
            'mode': self.mode,
            'status': self.status,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'replan_count': self.replan_count,
            'max_replans': self.max_replans,
            'node_counts': node_counts,
            'nodes': [node.to_metadata() for node in self.nodes],
            'warnings': list(self.warnings),
            'evidence_ledger_size_bytes': _ledger_size_bytes(self.evidence_ledger),
        }


def _validate_execution_graph(nodes):
    node_ids = [node.id for node in nodes]
    if len(node_ids) != len(set(node_ids)):
        raise OrchestrationRuntimeError('orchestration node ids must be unique')
    known_ids = set(node_ids)
    for node in nodes:
        unknown_dependencies = [
            dependency_id
            for dependency_id in node.depends_on
            if dependency_id not in known_ids
        ]
        if unknown_dependencies:
            raise OrchestrationRuntimeError(
                f'node {node.id} has unknown dependencies: {", ".join(unknown_dependencies)}'
            )
        if node.id in node.depends_on:
            raise OrchestrationRuntimeError(f'node {node.id} cannot depend on itself')

    remaining = {node.id: set(node.depends_on) for node in nodes}
    while remaining:
        ready_ids = {node_id for node_id, dependencies in remaining.items() if not dependencies}
        if not ready_ids:
            raise OrchestrationRuntimeError('orchestration execution graph contains a cycle')
        remaining = {
            node_id: dependencies - ready_ids
            for node_id, dependencies in remaining.items()
            if node_id not in ready_ids
        }


def _ledger_size_bytes(ledger):
    try:
        return len(json.dumps(ledger, ensure_ascii=True, separators=(',', ':')).encode('utf-8'))
    except (TypeError, ValueError):
        return 0


def _normalize_adapters(adapters):
    if not isinstance(adapters, Mapping):
        raise OrchestrationRuntimeError('adapters must be a mapping')
    normalized = {}
    for key, adapter in adapters.items():
        normalized_key = str(key or '').strip()
        if not normalized_key:
            raise OrchestrationRuntimeError('adapter keys must be nonempty')
        if isinstance(adapter, OrchestrationNodeAdapter):
            max_attempts = int(adapter.max_attempts)
            if max_attempts < 1 or max_attempts > MAX_NODE_ATTEMPTS:
                raise OrchestrationRuntimeError(
                    f'adapter max_attempts must be between 1 and {MAX_NODE_ATTEMPTS}'
                )
            normalized[normalized_key] = OrchestrationNodeAdapter(
                execute=adapter.execute,
                parallel_safe=adapter.parallel_safe,
                read_only=adapter.read_only,
                cancel=adapter.cancel,
                max_attempts=max_attempts if adapter.read_only else 1,
                retry_on_exception=(
                    bool(adapter.retry_on_exception) if adapter.read_only else False
                ),
            )
        elif callable(adapter):
            normalized[normalized_key] = OrchestrationNodeAdapter(execute=adapter)
        else:
            raise OrchestrationRuntimeError('adapter values must be callable runtime adapters')
    return normalized


def _resolve_adapter(node, adapters):
    for key in (
        node.id,
        f'{node.type}.{node.capability}',
        node.capability,
        node.type,
    ):
        if key in adapters:
            return adapters[key]
    return None


def _normalize_node_result(raw_result, node):
    if raw_result is None:
        result = OrchestrationNodeResult()
    elif isinstance(raw_result, OrchestrationNodeResult):
        result = raw_result
    elif isinstance(raw_result, Mapping):
        collector_result = raw_result.get('collector_result')
        if collector_result is None and raw_result.get('source_type'):
            collector_result = raw_result
        raw_status = raw_result.get('node_status') or raw_result.get('status') or 'succeeded'
        normalized_raw_status = str(raw_status).strip().lower()
        normalized_status = COLLECTOR_TO_NODE_STATUS.get(
            normalized_raw_status,
            normalized_raw_status,
        )
        additional_nodes = raw_result.get('additional_nodes') or ()
        if isinstance(additional_nodes, Mapping):
            additional_nodes = (additional_nodes,)
        result = OrchestrationNodeResult(
            status=normalized_status,
            summary=_normalize_text(raw_result.get('summary')),
            collector_result=(
                copy.deepcopy(dict(collector_result))
                if isinstance(collector_result, Mapping)
                else None
            ),
            additional_nodes=tuple(additional_nodes),
            error_type=raw_result.get('error_type'),
            user_message=raw_result.get('user_message'),
            debug_message=raw_result.get('debug_message'),
            retryable=bool(raw_result.get('retryable', False)),
        )
    else:
        raise OrchestrationRuntimeError(
            f'adapter for {node.id} returned an unsupported result type'
        )

    normalized_status = str(result.status or '').strip().lower()
    if normalized_status not in ORCHESTRATION_TERMINAL_NODE_STATUSES:
        raise OrchestrationRuntimeError(
            f'adapter for {node.id} returned unsupported status {normalized_status or "empty"}'
        )
    return OrchestrationNodeResult(
        status=normalized_status,
        summary=_normalize_text(result.summary),
        collector_result=(
            copy.deepcopy(dict(result.collector_result))
            if isinstance(result.collector_result, Mapping)
            else None
        ),
        additional_nodes=tuple(result.additional_nodes or ()),
        error_type=_safe_error_type(result.error_type) if result.error_type else None,
        user_message=_normalize_text(result.user_message),
        debug_message=_normalize_text(result.debug_message),
        retryable=bool(result.retryable),
        attempt_count=max(1, min(int(result.attempt_count), MAX_NODE_ATTEMPTS)),
    )


def _adapter_failure_result(node, ex, *, retryable=False):
    return OrchestrationNodeResult(
        status='failed',
        error_type=type(ex).__name__,
        user_message=f'The {node.capability.replace("_", " ")} step could not be completed.',
        debug_message=str(ex),
        retryable=retryable,
    )


def _adapter_unavailable_result(node):
    return OrchestrationNodeResult(
        status='failed',
        error_type='adapter_unavailable',
        user_message=f'The {node.capability.replace("_", " ")} capability is unavailable.',
    )


def _cancelled_result(node):
    return OrchestrationNodeResult(
        status='cancelled',
        error_type='cancelled',
        user_message=f'The {node.capability.replace("_", " ")} step was cancelled.',
    )


def _is_cancel_requested(callback):
    if callback is None:
        return False
    try:
        return bool(callback())
    except Exception as ex:
        log_event(
            '[OrchestrationRuntime] Cancellation check failed',
            {'error_type': type(ex).__name__},
            debug_only=True,
        )
        return False


def _build_node_context(run, node, original_request, cancel_requested):
    return OrchestrationNodeContext(
        run_id=run.run_id,
        task_type=run.task_type,
        task_profile=run.task_profile,
        original_request=_normalize_text(original_request, max_chars=8000),
        node=copy.deepcopy(node),
        evidence_ledger=copy.deepcopy(dict(run.evidence_ledger)),
        is_cancel_requested=lambda: _is_cancel_requested(cancel_requested),
    )


def _invoke_adapter(adapter, context):
    if adapter is None:
        return _normalize_node_result(
            _adapter_unavailable_result(context.node),
            context.node,
        )
    for attempt_number in range(1, adapter.max_attempts + 1):
        if context.is_cancel_requested():
            result = _normalize_node_result(_cancelled_result(context.node), context.node)
        else:
            try:
                result = _normalize_node_result(adapter.execute(context), context.node)
            except Exception as ex:
                result = _normalize_node_result(
                    _adapter_failure_result(
                        context.node,
                        ex,
                        retryable=adapter.retry_on_exception,
                    ),
                    context.node,
                )
        result = OrchestrationNodeResult(
            status=result.status,
            summary=result.summary,
            collector_result=result.collector_result,
            additional_nodes=result.additional_nodes,
            error_type=result.error_type,
            user_message=result.user_message,
            debug_message=result.debug_message,
            retryable=result.retryable,
            attempt_count=attempt_number,
        )
        if (
            result.status != 'failed'
            or not result.retryable
            or attempt_number >= adapter.max_attempts
        ):
            return result
        log_event(
            '[OrchestrationRuntime] Retrying read-only node',
            {
                'run_id': context.run_id,
                'node_id': context.node.id,
                'capability': context.node.capability,
                'attempt_count': attempt_number,
                'max_attempts': adapter.max_attempts,
                'error_type': result.error_type,
            },
        )
    return result


def _progress_message(node, status):
    base_message = PROGRESS_MESSAGES.get(
        node.capability,
        node.capability.replace('_', ' ').capitalize(),
    )
    if status == 'running':
        return base_message
    suffix = {
        'succeeded': 'completed',
        'partial': 'completed with partial results',
        'failed': 'failed',
        'skipped': 'was skipped',
        'blocked': 'was blocked',
        'cancelled': 'was cancelled',
    }.get(status, status)
    return f'{base_message} {suffix}'


def _emit_progress(run, node, progress_callback):
    if progress_callback is None:
        return
    node_index = next(
        index
        for index, runtime_node in enumerate(run.nodes)
        if runtime_node.id == node.id
    )
    event = {
        'version': ORCHESTRATION_RUNTIME_VERSION,
        'run_id': run.run_id,
        'node_id': node.id,
        'node_index': node_index,
        'node_count': len(run.nodes),
        'node_type': node.type,
        'capability': node.capability,
        'required': node.required,
        'status': node.status,
        'message': _progress_message(node, node.status),
    }
    try:
        progress_callback(event)
    except Exception as ex:
        log_event(
            '[OrchestrationRuntime] Progress callback failed',
            {
                'run_id': run.run_id,
                'node_id': node.id,
                'error_type': type(ex).__name__,
            },
            debug_only=True,
        )


def _log_node_lifecycle(run, node):
    log_event(
        f'[OrchestrationRuntime] Node {node.status}',
        {
            'run_id': run.run_id,
            'node_id': node.id,
            'node_type': node.type,
            'capability': node.capability,
            'required': node.required,
            'status': node.status,
            'attempt_count': node.attempt_count,
            'error_type': node.error_type,
        },
    )


def _start_node(run, node, progress_callback):
    node.status = 'running'
    node.attempt_count += 1
    node.started_at = _utc_now()
    _emit_progress(run, node, progress_callback)
    _log_node_lifecycle(run, node)


def _complete_node(run, node, result, progress_callback):
    node.status = result.status
    node.attempt_count = max(node.attempt_count, result.attempt_count)
    node.completed_at = _utc_now()
    node.error_type = result.error_type
    node.user_message = result.user_message or None
    node.debug_message = result.debug_message or None
    _apply_node_result_to_ledger(run, node, result)
    _attach_existing_source_provenance(run.evidence_ledger, node)
    _emit_progress(run, node, progress_callback)
    _log_node_lifecycle(run, node)


def _existing_ledger_ids(ledger):
    return {
        section: {
            str(entry.get('id'))
            for entry in ledger.get(section, [])
            if isinstance(entry, Mapping) and entry.get('id')
        }
        for section in PROVENANCE_LEDGER_SECTIONS
    }


def _attach_node_provenance(ledger, node_id, previous_ids):
    for section in PROVENANCE_LEDGER_SECTIONS:
        known_ids = previous_ids.get(section, set())
        for entry in ledger.get(section, []):
            if not isinstance(entry, MutableMapping):
                continue
            if str(entry.get('id') or '') not in known_ids:
                entry['step_id'] = node_id


def _attach_existing_source_provenance(ledger, node):
    source = _ledger_source(ledger, node.capability)
    if isinstance(source, MutableMapping):
        metadata = source.get('metadata')
        if not isinstance(metadata, Mapping):
            metadata = {}
        source['metadata'] = {
            **dict(metadata),
            'runtime_node_id': node.id,
        }

    for section in ('facts', 'unsupported_facts', 'results', 'artifacts'):
        for entry in ledger.get(section, []):
            if not isinstance(entry, MutableMapping) or entry.get('step_id'):
                continue
            if node.capability in (entry.get('source_ids') or []):
                entry['step_id'] = node.id
    for entry in ledger.get('citations', []):
        if (
            isinstance(entry, MutableMapping)
            and not entry.get('step_id')
            and entry.get('source_id') == node.capability
        ):
            entry['step_id'] = node.id
    for entry in ledger.get('missing_or_failed', []):
        if (
            isinstance(entry, MutableMapping)
            and not entry.get('step_id')
            and entry.get('source_id') == node.capability
        ):
            entry['step_id'] = node.id


def _ledger_source(ledger, source_id):
    return next(
        (
            source
            for source in ledger.get('sources', [])
            if isinstance(source, Mapping) and source.get('id') == source_id
        ),
        None,
    )


def _record_node_failure(run, node, result):
    if any(
        gap.get('step_id') == node.id
        for gap in run.evidence_ledger.get('missing_or_failed', [])
        if isinstance(gap, Mapping)
    ):
        return
    source = _ledger_source(run.evidence_ledger, node.capability)
    source_status = NODE_TO_SOURCE_STATUS.get(node.status, 'failed')
    failure = add_execution_failure(
        run.evidence_ledger,
        node.capability,
        source_status,
        result.user_message
        or f'The {node.capability.replace("_", " ")} step did not complete.',
        source_id=node.capability if source else None,
        step_id=node.id,
        failure_id=f'failure_{node.id}',
    )
    failure['error_type'] = result.error_type or 'execution_failed'


def _apply_node_result_to_ledger(run, node, result):
    previous_ids = _existing_ledger_ids(run.evidence_ledger)
    if result.collector_result is not None:
        collector_result = copy.deepcopy(dict(result.collector_result))
        metadata = collector_result.get('metadata')
        if not isinstance(metadata, Mapping):
            metadata = {}
        collector_result['metadata'] = {
            **dict(metadata),
            'runtime_node_id': node.id,
        }
        gaps = []
        for gap in collector_result.get('missing_or_failed') or []:
            if isinstance(gap, Mapping):
                normalized_gap = dict(gap)
                normalized_gap.setdefault('step_id', node.id)
                gaps.append(normalized_gap)
        collector_result['missing_or_failed'] = gaps
        apply_evidence_collector_result(
            run.evidence_ledger,
            collector_result,
            source_id=node.capability,
            origin=node.origin,
            required=node.required,
        )
    elif node.type != 'finalize':
        source = _ledger_source(run.evidence_ledger, node.capability)
        add_evidence_source(
            run.evidence_ledger,
            node.capability,
            NODE_TO_SOURCE_STATUS.get(node.status, 'failed'),
            source_id=node.capability,
            origin=node.origin,
            required=node.required,
            requirement_ids=(source or {}).get('requirement_ids'),
            metadata={'runtime_node_id': node.id},
        )

    _attach_node_provenance(run.evidence_ledger, node.id, previous_ids)
    if node.status in ORCHESTRATION_FAILURE_NODE_STATUSES:
        _record_node_failure(run, node, result)


def _dependency_blocks(node, node_by_id):
    return any(
        node_by_id[dependency_id].required
        and node_by_id[dependency_id].status in ORCHESTRATION_FAILURE_NODE_STATUSES
        for dependency_id in node.depends_on
    )


def _block_failed_dependents(run, progress_callback):
    changed = True
    while changed:
        changed = False
        node_by_id = {node.id: node for node in run.nodes}
        for node in run.nodes:
            if node.status != 'pending' or not _dependency_blocks(node, node_by_id):
                continue
            result = OrchestrationNodeResult(
                status='blocked',
                error_type='required_dependency_failed',
                user_message=(
                    f'The {node.capability.replace("_", " ")} step was blocked because '
                    'a required dependency did not complete.'
                ),
            )
            node.completed_at = _utc_now()
            node.status = result.status
            node.error_type = result.error_type
            node.user_message = result.user_message
            _apply_node_result_to_ledger(run, node, result)
            _emit_progress(run, node, progress_callback)
            _log_node_lifecycle(run, node)
            changed = True


def _ready_nodes(run):
    node_by_id = {node.id: node for node in run.nodes}
    return [
        node
        for node in run.nodes
        if node.status == 'pending'
        and all(
            node_by_id[dependency_id].status in ORCHESTRATION_TERMINAL_NODE_STATUSES
            for dependency_id in node.depends_on
        )
        and not _dependency_blocks(node, node_by_id)
    ]


def _parallel_eligible(node, adapter):
    return bool(
        adapter
        and adapter.parallel_safe
        and adapter.read_only
        and node.type in ORCHESTRATION_PARALLEL_NODE_TYPES
    )


def _select_execution_batch(ready_nodes, adapters, max_parallel_nodes):
    if max_parallel_nodes <= 1:
        return ready_nodes[:1]
    parallel_nodes = [
        node
        for node in ready_nodes
        if _parallel_eligible(node, _resolve_adapter(node, adapters))
    ]
    if len(parallel_nodes) >= 2:
        return parallel_nodes[:max_parallel_nodes]
    return ready_nodes[:1]


def _cancel_adapter(adapter, context):
    if adapter is None or adapter.cancel is None:
        return
    try:
        adapter.cancel(context)
    except Exception as ex:
        log_event(
            '[OrchestrationRuntime] Adapter cancellation failed',
            {
                'node_id': context.node.id,
                'error_type': type(ex).__name__,
            },
            debug_only=True,
        )


def _execute_batch(
    run,
    batch,
    adapters,
    original_request,
    cancel_requested,
    progress_callback,
):
    invocations = []
    for node in batch:
        if node.type == 'finalize':
            _prepare_ledger_for_finalizer(run)
        _start_node(run, node, progress_callback)
        adapter = _resolve_adapter(node, adapters)
        context = _build_node_context(run, node, original_request, cancel_requested)
        invocations.append((node, adapter, context))

    if len(invocations) == 1:
        node, adapter, context = invocations[0]
        result = _invoke_adapter(adapter, context)
        if _is_cancel_requested(cancel_requested):
            _cancel_adapter(adapter, context)
            result = _cancelled_result(node)
        return [(node, result)]

    results = {}
    cancellation_signalled = set()
    with ThreadPoolExecutor(max_workers=len(invocations)) as executor:
        future_to_invocation = {
            executor.submit(_invoke_adapter, adapter, context): (node, adapter, context)
            for node, adapter, context in invocations
        }
        pending_futures = set(future_to_invocation)
        while pending_futures:
            completed_futures, pending_futures = wait(
                pending_futures,
                timeout=0.05,
                return_when=FIRST_COMPLETED,
            )
            if _is_cancel_requested(cancel_requested):
                for future in pending_futures:
                    node, adapter, context = future_to_invocation[future]
                    if node.id not in cancellation_signalled:
                        cancellation_signalled.add(node.id)
                        future.cancel()
                        _cancel_adapter(adapter, context)
            for future in completed_futures:
                node, _adapter, _context = future_to_invocation[future]
                try:
                    result = future.result()
                except CancelledError:
                    result = _cancelled_result(node)
                results[node.id] = result

    cancellation_requested = _is_cancel_requested(cancel_requested)
    return [
        (
            node,
            _cancelled_result(node) if cancellation_requested else results[node.id],
        )
        for node, _adapter, _context in invocations
    ]


def _prepare_ledger_for_finalizer(run):
    source_nodes = [node for node in run.nodes if node.type != 'finalize']
    if not source_nodes:
        set_evidence_ledger_status(run.evidence_ledger, 'ready')
        return
    if any(
        node.required and node.status in ORCHESTRATION_FAILURE_NODE_STATUSES
        for node in source_nodes
    ):
        set_evidence_ledger_status(run.evidence_ledger, 'failed')
    elif any(
        node.status == 'partial'
        or (not node.required and node.status in ORCHESTRATION_FAILURE_NODE_STATUSES)
        for node in source_nodes
    ):
        set_evidence_ledger_status(run.evidence_ledger, 'partial')
    else:
        set_evidence_ledger_status(run.evidence_ledger, 'ready')


def _replan_is_allowed(run):
    return bool(run.policy.get('allow_bounded_replanning', False))


def _downgrade_replan_node(run, node, warning):
    if warning not in run.warnings:
        run.warnings.append(warning)
    if node.status == 'succeeded':
        node.status = 'partial'
        source = _ledger_source(run.evidence_ledger, node.capability)
        if source:
            source['status'] = 'partial'


def _apply_replanned_nodes(run, node, additional_nodes):
    if not additional_nodes:
        return
    if not _replan_is_allowed(run):
        _downgrade_replan_node(run, node, 'replanning_not_allowed')
        return
    if run.replan_count >= run.max_replans:
        _downgrade_replan_node(run, node, 'replan_budget_exhausted')
        return
    if not all(isinstance(step, Mapping) for step in additional_nodes):
        _downgrade_replan_node(run, node, 'invalid_replan_nodes')
        return

    normalized_nodes = [OrchestrationNode.from_plan_step(step) for step in additional_nodes]
    if any(replanned.type not in ORCHESTRATION_REPLAN_NODE_TYPES for replanned in normalized_nodes):
        _downgrade_replan_node(run, node, 'replan_requires_read_only_nodes')
        return
    if len(run.nodes) + len(normalized_nodes) > run.max_nodes:
        _downgrade_replan_node(run, node, 'runtime_node_budget_exhausted')
        return

    finalizer = next(existing for existing in run.nodes if existing.type == 'finalize')
    insertion_index = run.nodes.index(finalizer)
    candidate_nodes = copy.deepcopy([
        *run.nodes[:insertion_index],
        *normalized_nodes,
        *run.nodes[insertion_index:],
    ])
    candidate_finalizer = next(
        candidate for candidate in candidate_nodes if candidate.type == 'finalize'
    )
    for replanned in normalized_nodes:
        if replanned.id not in candidate_finalizer.depends_on:
            candidate_finalizer.depends_on.append(replanned.id)
    try:
        _validate_execution_graph(candidate_nodes)
    except OrchestrationRuntimeError:
        _downgrade_replan_node(run, node, 'invalid_replan_graph')
        return
    for replanned in normalized_nodes:
        if replanned.id not in finalizer.depends_on:
            finalizer.depends_on.append(replanned.id)
    run.nodes[insertion_index:insertion_index] = normalized_nodes
    run.replan_count += 1


def _cancel_pending_nodes(run, progress_callback):
    run.cancel_requested = True
    for node in run.nodes:
        if node.status != 'pending':
            continue
        result = _cancelled_result(node)
        node.status = result.status
        node.completed_at = _utc_now()
        node.error_type = result.error_type
        node.user_message = result.user_message
        _apply_node_result_to_ledger(run, node, result)
        _emit_progress(run, node, progress_callback)
        _log_node_lifecycle(run, node)


def _finalize_run(run):
    if run.completed_at:
        return
    finalizer = next(node for node in run.nodes if node.type == 'finalize')
    if run.cancel_requested or finalizer.status == 'cancelled':
        run.status = 'cancelled'
        set_evidence_ledger_status(run.evidence_ledger, 'cancelled')
    elif finalizer.status in {'succeeded', 'partial'}:
        degraded = finalizer.status == 'partial' or any(
            node.status == 'partial'
            or (not node.required and node.status in ORCHESTRATION_FAILURE_NODE_STATUSES)
            for node in run.nodes
            if node.type != 'finalize'
        )
        run.status = 'partial' if degraded else 'succeeded'
        set_evidence_ledger_status(run.evidence_ledger, 'completed')
    else:
        run.status = 'failed'
        set_evidence_ledger_status(run.evidence_ledger, 'failed')
    run.completed_at = _utc_now()
    log_event(
        f'[OrchestrationRuntime] Run {run.status}',
        {
            'run_id': run.run_id,
            'task_type': run.task_type,
            'task_profile': run.task_profile,
            'mode': run.mode,
            'status': run.status,
            'node_count': len(run.nodes),
            'replan_count': run.replan_count,
            'evidence_ledger_size_bytes': _ledger_size_bytes(run.evidence_ledger),
        },
    )


def _start_run(run, *, max_parallel_nodes=DEFAULT_MAX_PARALLEL_NODES):
    if run.status == 'running':
        return
    if run.status != 'pending':
        raise OrchestrationRuntimeError('a completed orchestration run cannot restart')
    run.status = 'running'
    run.started_at = _utc_now()
    log_event(
        '[OrchestrationRuntime] Run started',
        {
            'run_id': run.run_id,
            'task_type': run.task_type,
            'task_profile': run.task_profile,
            'mode': run.mode,
            'node_count': len(run.nodes),
            'max_parallel_nodes': max_parallel_nodes,
            'max_replans': run.max_replans,
        },
    )


def _find_runtime_node(run, node_id):
    normalized_node_id = str(node_id or '').strip()
    node = next((candidate for candidate in run.nodes if candidate.id == normalized_node_id), None)
    if node is None:
        raise OrchestrationRuntimeError(f'unknown orchestration node: {normalized_node_id}')
    return node


def reconcile_orchestration_run_from_ledger(run, *, progress_callback=None):
    """Reconcile authorized collector outputs already applied by an existing request path."""
    if not isinstance(run, OrchestrationRun):
        raise OrchestrationRuntimeError('run must be an OrchestrationRun')
    _start_run(run)

    reconciled = True
    while reconciled:
        reconciled = False
        _block_failed_dependents(run, progress_callback)
        ready_ids = {node.id for node in _ready_nodes(run)}
        for node in run.nodes:
            if node.type == 'finalize' or node.status != 'pending' or node.id not in ready_ids:
                continue
            source = _ledger_source(run.evidence_ledger, node.capability)
            source_status = str((source or {}).get('status') or '').strip().lower()
            node_status = SOURCE_TO_NODE_STATUS.get(source_status)
            if node_status is None:
                continue
            _attach_existing_source_provenance(run.evidence_ledger, node)
            _start_node(run, node, progress_callback)
            result = OrchestrationNodeResult(
                status=node_status,
                summary=_normalize_text((source or {}).get('summary')),
                error_type=(
                    source_status
                    if node_status in ORCHESTRATION_FAILURE_NODE_STATUSES
                    else None
                ),
                user_message=(
                    f'The {node.capability.replace("_", " ")} source ended with '
                    f'{source_status.replace("_", " ")} status.'
                    if node_status in ORCHESTRATION_FAILURE_NODE_STATUSES
                    else None
                ),
            )
            _complete_node(run, node, result, progress_callback)
            _attach_existing_source_provenance(run.evidence_ledger, node)
            reconciled = True
    return run


def start_orchestration_node(run, node_id, *, progress_callback=None):
    """Start one externally executed node after enforcing graph dependencies."""
    if not isinstance(run, OrchestrationRun):
        raise OrchestrationRuntimeError('run must be an OrchestrationRun')
    reconcile_orchestration_run_from_ledger(run, progress_callback=progress_callback)
    _block_failed_dependents(run, progress_callback)
    node = _find_runtime_node(run, node_id)
    if node.status != 'pending':
        raise OrchestrationRuntimeError(
            f'orchestration node {node.id} cannot start from {node.status}'
        )
    if node.id not in {ready.id for ready in _ready_nodes(run)}:
        raise OrchestrationRuntimeError(
            f'orchestration node {node.id} has nonterminal dependencies'
        )
    if node.type == 'finalize':
        _prepare_ledger_for_finalizer(run)
    _start_node(run, node, progress_callback)
    return node


def complete_orchestration_node(run, node_id, result=None, *, progress_callback=None):
    """Complete one externally executed node and normalize its ledger lifecycle."""
    if not isinstance(run, OrchestrationRun):
        raise OrchestrationRuntimeError('run must be an OrchestrationRun')
    node = _find_runtime_node(run, node_id)
    if node.status != 'running':
        raise OrchestrationRuntimeError(
            f'orchestration node {node.id} cannot complete from {node.status}'
        )
    normalized_result = _normalize_node_result(result, node)
    _complete_node(run, node, normalized_result, progress_callback)
    _apply_replanned_nodes(run, node, normalized_result.additional_nodes)
    _block_failed_dependents(run, progress_callback)
    return node


def cancel_orchestration_run(run, *, progress_callback=None):
    """Mark pending and externally running nodes cancelled, then close the request run."""
    if not isinstance(run, OrchestrationRun):
        raise OrchestrationRuntimeError('run must be an OrchestrationRun')
    if run.completed_at:
        return run
    _start_run(run)
    run.cancel_requested = True
    for node in run.nodes:
        if node.status not in {'pending', 'running'}:
            continue
        result = _cancelled_result(node)
        if node.status == 'running':
            _complete_node(run, node, result, progress_callback)
        else:
            node.status = result.status
            node.completed_at = _utc_now()
            node.error_type = result.error_type
            node.user_message = result.user_message
            _apply_node_result_to_ledger(run, node, result)
            _emit_progress(run, node, progress_callback)
            _log_node_lifecycle(run, node)
    _finalize_run(run)
    return run


def fail_orchestration_run(
    run,
    *,
    error_type='request_failed',
    user_message='The orchestration request could not be completed.',
    progress_callback=None,
):
    """Fail active work, block pending work, and close one request-scoped run."""
    if not isinstance(run, OrchestrationRun):
        raise OrchestrationRuntimeError('run must be an OrchestrationRun')
    if run.completed_at:
        return run
    _start_run(run)
    normalized_error_type = _safe_error_type(error_type)
    normalized_user_message = _normalize_text(user_message)
    for node in run.nodes:
        if node.status == 'running':
            _complete_node(
                run,
                node,
                OrchestrationNodeResult(
                    status='failed',
                    error_type=normalized_error_type,
                    user_message=normalized_user_message,
                ),
                progress_callback,
            )
        elif node.status == 'pending':
            node.status = 'blocked'
            node.completed_at = _utc_now()
            node.error_type = normalized_error_type
            node.user_message = normalized_user_message
            _apply_node_result_to_ledger(
                run,
                node,
                OrchestrationNodeResult(
                    status='blocked',
                    error_type=normalized_error_type,
                    user_message=normalized_user_message,
                ),
            )
            _emit_progress(run, node, progress_callback)
            _log_node_lifecycle(run, node)
    _finalize_run(run)
    return run


def finish_orchestration_run(run):
    """Close a fully terminal externally executed run and derive its aggregate status."""
    if not isinstance(run, OrchestrationRun):
        raise OrchestrationRuntimeError('run must be an OrchestrationRun')
    if any(node.status not in ORCHESTRATION_TERMINAL_NODE_STATUSES for node in run.nodes):
        raise OrchestrationRuntimeError('orchestration run still has nonterminal nodes')
    _finalize_run(run)
    return run


def execute_orchestration_run(
    run,
    adapters,
    *,
    original_request='',
    cancel_requested=None,
    progress_callback=None,
    max_parallel_nodes=DEFAULT_MAX_PARALLEL_NODES,
):
    """Execute one request-scoped run through injected, authorization-preserving adapters."""
    if not isinstance(run, OrchestrationRun):
        raise OrchestrationRuntimeError('run must be an OrchestrationRun')
    if run.status != 'pending':
        raise OrchestrationRuntimeError('an orchestration run can execute only once')
    normalized_max_parallel_nodes = int(max_parallel_nodes)
    if normalized_max_parallel_nodes < 1:
        raise OrchestrationRuntimeError('max_parallel_nodes must be positive')
    normalized_adapters = _normalize_adapters(adapters)
    _start_run(run, max_parallel_nodes=normalized_max_parallel_nodes)

    while any(node.status == 'pending' for node in run.nodes):
        if _is_cancel_requested(cancel_requested):
            _cancel_pending_nodes(run, progress_callback)
            break
        _block_failed_dependents(run, progress_callback)
        ready_nodes = _ready_nodes(run)
        if not ready_nodes:
            if any(node.status == 'pending' for node in run.nodes):
                raise OrchestrationRuntimeError('orchestration graph cannot make progress')
            break
        batch = _select_execution_batch(
            ready_nodes,
            normalized_adapters,
            normalized_max_parallel_nodes,
        )
        completed = _execute_batch(
            run,
            batch,
            normalized_adapters,
            original_request,
            cancel_requested,
            progress_callback,
        )
        for node, result in completed:
            _complete_node(run, node, result, progress_callback)
            _apply_replanned_nodes(run, node, result.additional_nodes)
        if _is_cancel_requested(cancel_requested):
            _cancel_pending_nodes(run, progress_callback)
            break

    _block_failed_dependents(run, progress_callback)
    if _is_cancel_requested(cancel_requested):
        _cancel_pending_nodes(run, progress_callback)
    _finalize_run(run)
    return run


def resolve_orchestration_evidence_discovery(run, *, progress_callback=None):
    """Resolve the generic discovery node from usable authorized evidence already collected."""
    if not isinstance(run, OrchestrationRun):
        raise OrchestrationRuntimeError('run must be an OrchestrationRun')
    discovery_node = next(
        (node for node in run.nodes if node.capability == 'evidence_discovery'),
        None,
    )
    if discovery_node is None or discovery_node.status != 'pending':
        return discovery_node

    evidence_source_ids = []
    for section in ('facts', 'results', 'artifacts'):
        for entry in run.evidence_ledger.get(section, []):
            if not isinstance(entry, Mapping):
                continue
            for source_id in entry.get('source_ids') or []:
                normalized_source_id = str(source_id or '').strip()
                if (
                    normalized_source_id
                    and normalized_source_id != 'evidence_discovery'
                    and normalized_source_id not in evidence_source_ids
                ):
                    evidence_source_ids.append(normalized_source_id)
    for citation in run.evidence_ledger.get('citations', []):
        if not isinstance(citation, Mapping):
            continue
        source_id = str(citation.get('source_id') or '').strip()
        if source_id and source_id != 'evidence_discovery' and source_id not in evidence_source_ids:
            evidence_source_ids.append(source_id)

    authorized_source_ids = {
        str(source.get('id') or '').strip()
        for source in run.evidence_ledger.get('sources', [])
        if isinstance(source, Mapping)
        and source.get('authorization_status') != 'denied'
        and str(source.get('status') or '').strip().lower() in {'succeeded', 'partial'}
    }
    usable_source_ids = [
        source_id for source_id in evidence_source_ids if source_id in authorized_source_ids
    ]

    start_orchestration_node(
        run,
        discovery_node.id,
        progress_callback=progress_callback,
    )
    if usable_source_ids:
        collector_result = {
            'source_type': 'evidence_discovery',
            'status': 'succeeded',
            'summary': (
                f'Discovered usable authorized evidence from {len(usable_source_ids)} source(s).'
            ),
            'facts': [],
            'citations': [],
            'artifacts': [],
            'missing_or_failed': [],
            'metadata': {
                'authorization_status': 'authorized',
                'discovered_source_ids': usable_source_ids,
            },
        }
        result = OrchestrationNodeResult(
            status='succeeded',
            summary=collector_result['summary'],
            collector_result=collector_result,
        )
    else:
        collector_result = {
            'source_type': 'evidence_discovery',
            'status': 'not_found',
            'summary': 'No usable authorized evidence was discovered for the requested grounding.',
            'facts': [],
            'citations': [],
            'artifacts': [],
            'missing_or_failed': [{
                'kind': 'missing_evidence',
                'status': 'not_found',
                'message': 'No usable authorized evidence was found for the requested grounding.',
                'step_id': discovery_node.id,
            }],
            'metadata': {'authorization_status': 'authorized'},
        }
        result = OrchestrationNodeResult(
            status='failed',
            summary=collector_result['summary'],
            collector_result=collector_result,
            error_type='evidence_not_found',
            user_message='No usable authorized evidence was found for the requested grounding.',
        )
    complete_orchestration_node(
        run,
        discovery_node.id,
        result,
        progress_callback=progress_callback,
    )
    return discovery_node