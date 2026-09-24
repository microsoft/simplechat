# functions_orchestration_recovery.py
"""Execution leases and explicitly requested, checkpoint-only retry attempts.

Version: 0.261.134
Retry publication is one transactional parent CAS + child create. It never
replans, invokes an adapter, or changes plan-revision lineage.
Terminal publication preserves an administrator's reply retraction; its probe
never replaces the original publication failure with a missing-reply read.
A retry that runs a failed producer again also runs the steps that completed without it.
"""

import logging
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError, ServiceRequestError, ServiceResponseError
from azure.cosmos import exceptions

from content_screening.contracts import ScreeningError
import functions_orchestration_runs as run_store
from functions_appinsights import log_event
from functions_orchestration_checkpoints import (
    CHECKPOINT_VERSION, DEPENDENCY_STATE_FIELDS, LIFECYCLE_ID, OPTIONAL_STATE_FIELDS, STATE_FIELDS,
    CheckpointError, CheckpointStore, context_binding, context_state,
    effective_plan, fingerprint, restore_context, step_input_fingerprint,
)
from functions_orchestration_plan_revisions import PlanRevisionError, read_revision_run
from functions_orchestration_output_store import build_output_cleanup_intent
from functions_orchestration_registry import admitted_export_pairs, get_capability
from functions_orchestration_schema import (
    PlanValidationError, build_failure, build_step_result, plan_contract_version, safe_failure, step_input_specs,
    summarize_plan,
)
from functions_orchestration_result_contracts import ProducerIdentity, ResultContractError, ResultRef, TaskResult
from functions_orchestration_result_runtime import (
    encode_step_result, raise_source_service_failure, require_result_service, reuse_alias, validate_task_diagnostics,
)
from functions_orchestration_results import OrchestrationResults, ResultUnavailableError
from functions_workflow_result_store import (
    AnalysisWorkUnitConflictError, WorkflowResultIntegrityError, WorkflowResultStorageUnavailableError,
)


LEASE_SECONDS = 45
HEARTBEAT_SECONDS = 10
EFFECT_CAPABILITIES = {'agent_invoke', 'action_invoke'}
_TERMINAL = {'completed', 'failed', 'cancelled'}
_RETRY_FIELDS = {'conversation_id', 'submission_id', 'expected_version', 'confirm_external_effects'}
_CONTINUATION_FIELDS = {'conversation_id', 'submission_id', 'expected_version'}
_STORAGE_READ_ERRORS = (
    WorkflowResultStorageUnavailableError, HttpResponseError, exceptions.CosmosHttpResponseError,
    ServiceRequestError, ServiceResponseError, ConnectionError, TimeoutError,
)


def _retained_statuses(record):
    return {'completed', 'partial'} if plan_contract_version(record.get('plan')) == 2 else {'completed'}


def _retained_producer_steps(record):
    return [
        step for step in (record.get('plan') or {}).get('steps') or []
        if plan_contract_version(record.get('plan')) == 2
        or step.get('capability_id') in {'document_analyze', 'tabular_analyze'}
    ]


def _reuse_invalidated_by_rerun(record, retained):
    """Retained dependency steps that must run again because something they consumed does.

    A step can complete without an optional input whose producer failed. When a retry
    runs that producer again, the saved result was computed without an input the new
    attempt may now have, so the step and every step computed from it run again. Reusing
    it would otherwise fail the attempt with ``recovery_changed`` as soon as the producer
    succeeded, and the retry could never deliver what the first attempt missed.
    """
    if plan_contract_version(record.get('plan')) != 2:
        return set()
    steps = [step for step in record['plan'].get('steps') or [] if step.get('enabled', True)]
    rerun = {step['step_id'] for step in steps} - set(retained)
    consumed = {
        step['step_id']: {spec.binding.step_id for spec in step_input_specs(step) if spec.binding.step_id is not None}
        for step in steps if step['step_id'] in retained
    }
    invalidated = set()
    while True:
        added = {
            step_id for step_id, producers in consumed.items()
            if step_id not in invalidated and producers & (rerun | invalidated)
        }
        if not added:
            return invalidated
        invalidated |= added


class RecoveryError(RuntimeError):
    def __init__(self, message=None, *, code='recovery_unavailable', status_code=409, recovery=None, current_run_id=None):
        self.code = code
        self.status_code = status_code
        self.message = message or 'Saved progress is unavailable. Review the request and create a new plan.'
        self.recovery = recovery
        self.current_run_id = current_run_id
        super().__init__(self.message)


def _now():
    return datetime.now(timezone.utc)


def _valid_id(value):
    return isinstance(value, str) and 0 < len(value) <= 200 and value == value.strip() and not any(
        ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF or char in '/\\?#' for char in value
    )


def lease_fields():
    return {
        'token': uuid.uuid4().hex, 'expires_at': (_now() + timedelta(seconds=LEASE_SECONDS)).isoformat(),
        'heartbeat_at': _now().isoformat(),
    }


def _live(record):
    lease = record.get('execution_lease') or {}
    if not lease.get('token'):
        return False
    try:
        return datetime.fromisoformat(lease['expires_at']) > _now()
    except (KeyError, ValueError, TypeError):
        return True


def _owned(run_id, user_id, conversation_id, authorize):
    try:
        if not callable(authorize) or authorize() is False:
            raise RecoveryError(code='not_found', status_code=404)
        record = read_revision_run(run_id, user_id, conversation_id)
        if record.get('checkpoints_deleted'):
            raise RecoveryError(code='not_found', status_code=404)
        return record
    except PlanRevisionError as exc:
        raise RecoveryError('Run not found.', code='not_found', status_code=404) from exc


def _replace(record, updates):
    replacement = run_store._strip_cosmos_metadata(deepcopy(record))
    replacement.update(deepcopy(updates))
    replacement['updated_at'] = _now().isoformat()
    return run_store.cosmos_orchestration_runs_container.replace_item(
        item=record['id'], body=replacement, etag=record['_etag'],
        match_condition=MatchConditions.IfNotModified,
    )


def checkpoint_store(record, authorize, *, token=None, claim_id=None):
    return CheckpointStore(
        run_store.cosmos_orchestration_run_steps_container,
        run_id=record['id'], user_id=record['user_id'], conversation_id=record['conversation_id'],
        turn_id=record.get('turn_id') or record['plan'].get('turn_id'), authorize=authorize,
        token=token, claim_id=claim_id,
        plan_contract_version=plan_contract_version(record.get('plan')),
    )


def _publication_id(run_id):
    return f'orchestration_guard_{fingerprint(run_id)[:40]}'


def fence_publication(record, container):
    if container is None:
        return
    item_id = _publication_id(record['id'])
    for _ in range(8):
        try:
            existing = container.read_item(item=item_id, partition_key=record['conversation_id'])
        except exceptions.CosmosResourceNotFoundError:
            tombstone = {
                'id': item_id, 'conversation_id': record['conversation_id'], 'user_id': record['user_id'],
                'role': 'assistant_artifact', 'content': '', 'run_id': record['id'], 'token': None,
                'metadata': {'is_generated_chat_artifact': True, 'orchestration_publication_guard': True},
            }
            try:
                container.create_item(body=tombstone)
                return
            except exceptions.CosmosResourceExistsError:
                continue
        if existing.get('run_id') != record['id'] or existing.get('user_id') != record['user_id']:
            raise CheckpointError('ownership_lost')
        replacement = run_store._strip_cosmos_metadata(existing)
        replacement['token'] = None
        try:
            container.replace_item(
                item=item_id, body=replacement, etag=existing['_etag'],
                match_condition=MatchConditions.IfNotModified,
            )
            return
        except exceptions.CosmosAccessConditionFailedError:
            continue
    raise CheckpointError('ownership_lost')


def _execution_steps(record):
    """Inherited successes remain durable even before this attempt copies them."""
    references = record.get('inherited_checkpoints') or {}
    if not isinstance(references, dict):
        raise CheckpointError('checkpoint_invalid')
    expected = set(record.get('retry_reused_step_ids') or [])
    if expected != set(references):
        raise CheckpointError('checkpoint_invalid')
    planned = {step['step_id']: step for step in record.get('plan', {}).get('steps') or []}
    if set(references) - set(planned):
        raise CheckpointError('checkpoint_invalid')
    steps = {step['step_id']: deepcopy(step) for step in record.get('execution_steps') or []}
    for step_id, reference in references.items():
        if not isinstance(reference, dict) or not isinstance(reference.get('provenance'), dict):
            raise CheckpointError('checkpoint_invalid')
        if step_id in steps and steps[step_id].get('status') not in _retained_statuses(record):
            raise CheckpointError('checkpoint_invalid')
        steps.setdefault(step_id, {
            'step_id': step_id, 'step_index': list(planned).index(step_id),
            'capability_id': planned[step_id]['capability_id'], 'status': reference.get('status', 'completed'),
            'checkpoint_available': True, 'effects_uncertain': False, 'reused': True,
            'reused_from_run_id': reference['provenance'].get('run_id'),
            'summary': 'Reused saved result',
        })
    return [steps[step_id] for step_id in planned if step_id in steps]


def _validate_inherited_parent(record, parent):
    if (
        record.get('retry_of_run_id') != parent['id']
        or parent.get('latest_attempt_run_id') != record['id']
        or record.get('turn_id') != parent.get('turn_id')
        or effective_plan(record['plan']) != effective_plan(parent['plan'])
        or record.get('execution_binding') != parent.get('execution_binding')
        or record.get('attempt_root_run_id') != (parent.get('attempt_root_run_id') or parent['id'])
        or record.get('attempt_index') != (parent.get('attempt_index') or 1) + 1
        or any(record.get(key) != parent.get(key) for key in (
            'user_message_id', 'user_message', 'resolved_message', 'request_resolution',
        ))
    ):
        raise CheckpointError('recovery_changed')


def _receipt_checkpoint(record, step_id, authorize, result_service):
    """Reconstruct only from a guarded input checkpoint and an authenticated commit."""
    if not isinstance(result_service, OrchestrationResults):
        raise CheckpointError('result_unavailable')
    store = checkpoint_store(record, authorize)
    original = store.load(step_id, input_only=True)
    if original.get('binding') != record.get('execution_binding'):
        raise CheckpointError('recovery_changed')
    try:
        producer = ProducerIdentity.from_dict(original['result_producer'])
        planned = next(step for step in record['plan']['steps'] if step['step_id'] == step_id)
        if (
            producer.attempt_index != record.get('attempt_index', 1)
            or producer.capability_id != planned['capability_id']
            or planned.get('enabled') is not True
        ):
            raise CheckpointError('recovery_changed')
        task = result_service.recover_task_result(
            producer=producer, input_fingerprint=original['input_fingerprint'],
        )
        if task is None:
            return None
        if task.role != planned['role']:
            raise CheckpointError('checkpoint_invalid')
    except (exceptions.CosmosResourceNotFoundError, ResourceNotFoundError) as exc:
        raise CheckpointError('result_unavailable') from exc
    except _STORAGE_READ_ERRORS as exc:
        raise CheckpointError('checkpoint_storage_unavailable') from exc
    except (
        ResultContractError, ResultUnavailableError, PermissionError, ScreeningError,
        AnalysisWorkUnitConflictError, WorkflowResultIntegrityError,
    ) as exc:
        raise_source_service_failure(exc)
        raise CheckpointError('result_unavailable') from exc
    state = deepcopy(original['state'])
    if type(state.get('task_results')) is not dict or type(state.get('pending_results')) is not dict:
        raise CheckpointError('checkpoint_invalid')
    if step_id in state['task_results']:
        raise CheckpointError('checkpoint_invalid')
    state['task_results'][step_id] = task.to_dict()
    state['pending_results'].pop(step_id, None)
    result = build_step_result(
        status='partial' if task.status == 'partial' else 'completed', task_result=task,
        summary='Recovered the committed result without repeating the producer.',
    )
    return {
        'schema_version': CHECKPOINT_VERSION, 'binding': original['binding'],
        'input_fingerprint': original['input_fingerprint'], 'step_id': step_id,
        'result': encode_step_result(result, retained_only=True), 'state': state, 'usage': {},
        'provenance': deepcopy(original['provenance']), 'artifact_versions': {},
    }


def _completed_checkpoint(record, step_id, authorize, visited=None, *, result_service=None):
    visited = set(visited or ())
    if record['id'] in visited or len(visited) >= 128:
        raise CheckpointError('checkpoint_invalid')
    visited.add(record['id'])
    steps = {step['step_id']: step for step in _execution_steps(record)}
    if steps.get(step_id, {}).get('status') not in _retained_statuses(record):
        raise CheckpointError('checkpoint_invalid')
    reference = (record.get('inherited_checkpoints') or {}).get(step_id)
    store = checkpoint_store(record, authorize)
    local = store.has_manifest(step_id)
    dependency_contract = plan_contract_version(record['plan']) == 2
    inherited = None
    if reference and (not local or dependency_contract):
        if reference.get('source_run_id') != record.get('retry_of_run_id'):
            raise CheckpointError('checkpoint_invalid')
        try:
            parent = _owned(reference['source_run_id'], record['user_id'], record['conversation_id'], authorize)
        except RecoveryError as exc:
            if dependency_contract and (exc.status_code >= 500 or exc.status_code == 429):
                raise CheckpointError('checkpoint_storage_unavailable') from exc
            raise CheckpointError('context_unavailable') from exc
        except (exceptions.CosmosResourceNotFoundError, ResourceNotFoundError) as exc:
            if not dependency_contract:
                raise
            raise CheckpointError('context_unavailable') from exc
        except _STORAGE_READ_ERRORS as exc:
            if not dependency_contract:
                raise
            raise CheckpointError('checkpoint_storage_unavailable') from exc
        _validate_inherited_parent(record, parent)
        inherited = _completed_checkpoint(parent, step_id, authorize, visited, result_service=result_service)
    if local:
        payload = store.load(step_id)
    elif inherited is not None:
        payload = inherited
    elif dependency_contract and result_service is not None and store.has_manifest(step_id, input_only=True):
        payload = _receipt_checkpoint(record, step_id, authorize, result_service)
        if payload is None:
            raise CheckpointError('checkpoint_unavailable')
    else:
        raise CheckpointError('checkpoint_unavailable')
    if payload.get('binding') != record.get('execution_binding'):
        raise CheckpointError('recovery_changed')
    if not reference and payload.get('provenance') != {'run_id': record['id'], 'step_id': step_id}:
        raise CheckpointError('checkpoint_invalid')
    if reference and (
        reference.get('payload_digest') != fingerprint(inherited if inherited is not None else payload)
        or reference.get('provenance') != payload.get('provenance')
    ):
        raise CheckpointError('checkpoint_invalid')
    if dependency_contract and local and inherited is not None and any(
        payload.get(key) != inherited.get(key)
        for key in ('schema_version', 'binding', 'input_fingerprint', 'step_id', 'result', 'provenance', 'artifact_versions')
    ):
        raise CheckpointError('recovery_changed')
    return payload


def recovery_projection(record):
    """Pure, read-only hints; POST revalidates every fact before publication."""
    run_id = record.get('run_id') or record.get('id')
    invalid = False
    try:
        steps = _execution_steps(record)
    except CheckpointError:
        steps = record.get('execution_steps') or []
        invalid = True
    reused = [
        step['step_id'] for step in steps
        if step.get('status') in _retained_statuses(record) and step.get('capability_id') != 'respond'
    ]
    try:
        stale = _reuse_invalidated_by_rerun(record, reused)
    except PlanValidationError:
        stale, invalid = set(), True
    reused = [step_id for step_id in reused if step_id not in stale]
    retry = [
        step['step_id'] for step in record.get('plan', {}).get('steps') or []
        if step.get('enabled', True) and (step['step_id'] not in reused or step.get('capability_id') == 'respond')
    ]
    uncertain = any(
        step.get('capability_id') in EFFECT_CAPABILITIES and step.get('effects_uncertain')
        for step in steps
    )
    reason, message = None, None
    current = record.get('latest_attempt_run_id')
    if current and current != run_id:
        reason, message = 'recovery_changed', 'A newer execution attempt already exists.'
    elif record.get('checkpoints_deleted'):
        reason, message = 'context_unavailable', 'Executable recovery data was removed.'
    elif record.get('checkpoint_version') != CHECKPOINT_VERSION or not record.get('execution_binding'):
        reason, message = 'legacy_no_checkpoints', 'This run has no durable checkpoints and cannot resume. Create a new plan.'
    elif _live(record):
        reason, message = 'execution_live', 'This attempt is still running. Wait for it to finish or stop it.'
    elif plan_contract_version(record.get('plan')) == 2 and any(step.get('status') == 'waiting' for step in steps):
        reason, message = 'result_not_ready', build_failure('result_not_ready')['message']
    elif plan_contract_version(record.get('plan')) == 2 and any(step.get('status') == 'running' for step in steps):
        reason, message = 'result_commit_unconfirmed', build_failure('result_commit_unconfirmed')['message']
    elif invalid:
        reason, message = 'checkpoint_invalid', build_failure('checkpoint_invalid')['message']
    elif record.get('status') == 'completed' and record.get('outcome', 'completed') == 'completed':
        reason, message = 'already_completed', 'This request is already complete.'
    elif not record.get('started_at'):
        reason, message = 'not_started', 'This attempt has not started.'
    elif record.get('recovery_blocked_code'):
        reason = record['recovery_blocked_code']
        message = build_failure(reason)['message']
    elif (record.get('failure') or {}).get('code') == 'context_unavailable':
        reason, message = 'context_unavailable', build_failure('context_unavailable')['message']
    elif any(not step.get('checkpoint_available') for step in steps if step.get('step_id') in reused):
        reason, message = 'checkpoint_unavailable', build_failure('checkpoint_unavailable')['message']
    return {
        'eligible': reason is None, 'reason_code': reason, 'message': message,
        'expected_version': record.get('recovery_version'),
        'source_run_id': run_id, 'retry_step_ids': retry, 'reused_step_ids': reused,
        'requires_confirmation': uncertain,
        **({'current_run_id': current} if current and current != run_id else {}),
    }


def reconcile_checkpoints(record, authorize, *, result_service=None, _defer_inherited_validation=False):
    """Read-only reconciliation of a crash after manifest commit but before progress.

    An injected initialized result service additionally reconciles the producer
    commit-before-checkpoint window. Missing receipts on interrupted work remain
    uncertain; neither previews nor a replacement producer prove completion.
    """
    updated = deepcopy(record)
    current = record
    visited = {record['id']}
    while current.get('latest_attempt_run_id'):
        target = current['latest_attempt_run_id']
        if target in visited or len(visited) >= 128:
            raise CheckpointError('checkpoint_invalid')
        visited.add(target)
        child = _owned(target, record['user_id'], record['conversation_id'], authorize)
        if child.get('retry_of_run_id') != current['id'] or child.get('turn_id') != record.get('turn_id'):
            raise CheckpointError('checkpoint_invalid')
        updated['latest_attempt_run_id'] = target
        current = child
    if record.get('checkpoint_version') != CHECKPOINT_VERSION or record.get('checkpoints_deleted'):
        return updated
    updated['execution_steps'] = _execution_steps(record)
    if not _defer_inherited_validation:
        for step_id in record.get('inherited_checkpoints') or {}:
            _completed_checkpoint(record, step_id, authorize, result_service=result_service)
    store = checkpoint_store(record, authorize)
    reconcilable = {'running', 'failed', 'waiting'}
    if plan_contract_version(record.get('plan')) == 2:
        reconcilable.add('cancelled')
    for step in updated.get('execution_steps') or []:
        if step.get('status') not in reconcilable or step.get('capability_id') == 'respond':
            continue
        if store.has_manifest(step['step_id']):
            payload = store.load(step['step_id'])
            if payload.get('binding') != record.get('execution_binding'):
                raise CheckpointError('checkpoint_invalid')
            step.update({
                'status': payload['result']['status'], 'checkpoint_available': True, 'effects_uncertain': False,
                'failure': None, 'error': None, 'summary': payload['result'].get('summary') or 'Saved result',
            })
        elif plan_contract_version(record.get('plan')) == 2 and store.has_manifest(step['step_id'], waiting=True):
            payload = store.load(step['step_id'], waiting=True)
            if payload.get('binding') != record.get('execution_binding'):
                raise CheckpointError('checkpoint_invalid')
            step.update({
                'status': 'waiting', 'checkpoint_available': True, 'effects_uncertain': False,
                'failure': None, 'error': None, 'wait': deepcopy(payload['result'].get('wait')),
                'summary': 'Waiting for retained computation.',
            })
        elif (
            plan_contract_version(record.get('plan')) == 2 and result_service is not None
            and store.has_manifest(step['step_id'], input_only=True)
        ):
            payload = _receipt_checkpoint(record, step['step_id'], authorize, result_service)
            if payload is not None:
                step.update({
                    'status': payload['result']['status'], 'checkpoint_available': True, 'effects_uncertain': False,
                    'failure': None, 'error': None, 'summary': payload['result']['summary'],
                    'task_result': deepcopy(payload['result']['task_result']),
                })
    return updated


def public_execution_fields(record):
    fields = {
        'attempt_index': record.get('attempt_index') or 1,
        'retry_of_run_id': record.get('retry_of_run_id'),
        'failure': safe_failure(record['failure']) if record.get('failure') else None,
        'failures': [safe_failure(value) for value in record.get('failures') or []],
        'recovery': recovery_projection(record),
    }
    if record.get('outcome') in ('completed', 'partial', 'failed', 'cancelled', 'waiting'):
        fields['outcome'] = record['outcome']
    if record.get('latest_attempt_run_id'):
        fields['latest_attempt_run_id'] = record['latest_attempt_run_id']
    if record.get('finalization_status') in ('pending', 'saved', 'failed', 'interrupted'):
        if _live(record):
            fields['finalization_status'] = 'pending'
        elif record.get('message_saved') is True and record.get('assistant_message_id'):
            fields.update({'finalization_status': 'saved', 'message_saved': True})
        elif record.get('message_saved') is False and record.get('finalization_status') == 'failed':
            fields.update({'finalization_status': 'failed', 'message_saved': False})
        else:
            fields['finalization_status'] = 'interrupted'
    if record.get('status') == 'running' and record.get('execution_lease') and not _live(record):
        failure = build_failure('execution_expired')
        fields.update({
            'status': 'failed',
            'outcome': 'partial' if fields['recovery']['reused_step_ids'] else 'failed',
            'failure': fields['failure'] or failure, 'failures': fields['failures'] + [failure],
        })
    return fields


class ExecutionLease:
    """A worker-independent heartbeat, with fail-closed reads and conditional writes."""

    def __init__(self, record, authorize, *, message_container=None):
        self.run_id = record['id']
        self.user_id = record['user_id']
        self.conversation_id = record['conversation_id']
        self.authorize = authorize
        self.token = (record.get('execution_lease') or {}).get('token')
        self.claim_id = (record.get('execution_lease') or {}).get('claim_id')
        self.stopped = threading.Event()
        self.failed = None
        self.thread = None
        self.lock = threading.RLock()
        self.message_container = message_container

    def publish_message(self, document):
        """Fence and message are in the same container/partition: no stale publish."""
        # Recovery can initialize before chat routes; resolve the projection
        # adapter only at the publication boundary, never during bootstrap.
        from functions_chat_content_review import reply_is_retracted

        self.read()
        if self.message_container is None:
            raise CheckpointError('message_not_saved')
        if (
            document.get('id') != f'assistant_orchestration_{fingerprint(self.run_id)[:40]}'
            or document.get('conversation_id') != self.conversation_id
            or not (document.get('role') == 'assistant' or document.get('role') == 'safety' and reply_is_retracted(document))
            or (document.get('metadata') or {}).get('orchestration', {}).get('run_id') != self.run_id
        ):
            raise CheckpointError('message_not_saved')
        item_id = _publication_id(self.run_id)
        for attempt in range(2):
            guard = self.message_container.read_item(item=item_id, partition_key=self.conversation_id)
            if not self._owns_publication_guard(guard):
                raise CheckpointError('ownership_lost')
            try:
                previous = self.message_container.read_item(item=document["id"], partition_key=self.conversation_id)
            except exceptions.CosmosResourceNotFoundError:
                previous = None
            if previous is not None and reply_is_retracted(previous):
                document.clear()
                document.update(run_store._strip_cosmos_metadata(previous))
            replacement = run_store._strip_cosmos_metadata(guard)
            replacement['published_message_id'] = document['id']
            replacement['document_digest'] = fingerprint(run_store._strip_cosmos_metadata(document))
            message_operation = (
                ("replace", (document["id"], document), {"if_match_etag": previous["_etag"]})
                if previous is not None else ("create", (document,))
            )
            try:
                self.message_container.execute_item_batch(
                    batch_operations=[
                        ('replace', (item_id, replacement), {'if_match_etag': guard['_etag']}),
                        message_operation,
                    ], partition_key=self.conversation_id,
                )
                break
            except Exception:
                if self._published_message_matches(document, replacement['document_digest']):
                    break
                if attempt == 0:
                    # Probe only for a concurrent retraction; never replace the original failure.
                    try:
                        current = self.message_container.read_item(
                            item=document["id"], partition_key=self.conversation_id,
                        )
                    except Exception:
                        current = None
                    if current is not None and reply_is_retracted(current):
                        continue
                raise
        self.read()

    def _owns_publication_guard(self, guard):
        return (
            guard.get('id') == _publication_id(self.run_id)
            and guard.get('conversation_id') == self.conversation_id
            and guard.get('run_id') == self.run_id and guard.get('user_id') == self.user_id
            and guard.get('token') == self.token and guard.get('role') == 'assistant_artifact'
            and guard.get('claim_id') == self.claim_id
            and (guard.get('metadata') or {}).get('orchestration_publication_guard') is True
        )

    def _published_message_matches(self, document, digest):
        """A lost batch acknowledgement is success only for this exact publication."""
        self.read()
        try:
            guard = self.message_container.read_item(
                item=_publication_id(self.run_id), partition_key=self.conversation_id,
            )
            saved = self.message_container.read_item(item=document['id'], partition_key=self.conversation_id)
        except exceptions.CosmosResourceNotFoundError:
            return False
        matches = (
            self._owns_publication_guard(guard)
            and guard.get('published_message_id') == document['id']
            and guard.get('document_digest') == digest
            and fingerprint(run_store._strip_cosmos_metadata(saved)) == digest
        )
        self.read()
        return matches

    def read(self):
        if self.failed:
            raise self.failed
        record = _owned(self.run_id, self.user_id, self.conversation_id, self.authorize)
        if (
            not self.token or (record.get('execution_lease') or {}).get('token') != self.token
            or (record.get('execution_lease') or {}).get('claim_id') != self.claim_id
            or not _live(record) or record.get('latest_attempt_run_id') not in (None, self.run_id)
        ):
            raise CheckpointError('ownership_lost')
        return record

    def update(self, updates, *, precondition=None):
        with self.lock:
            for _ in range(8):
                record = self.read()
                if precondition is not None:
                    precondition(record)
                try:
                    return _replace(record, updates)
                except exceptions.CosmosAccessConditionFailedError:
                    continue
                except Exception:
                    saved = _owned(self.run_id, self.user_id, self.conversation_id, self.authorize)
                    released = 'execution_lease' in updates and updates['execution_lease'] is None
                    owned = (
                        saved.get('latest_attempt_run_id') in (None, self.run_id)
                        and (
                            (
                                (saved.get('execution_lease') or {}).get('token') == self.token
                                and (saved.get('execution_lease') or {}).get('claim_id') == self.claim_id
                                and _live(saved)
                            )
                            or (
                                released and saved.get('execution_lease') is None
                                and (saved.get('continuation_submission') or {}).get('claim_id') == self.claim_id
                            )
                        )
                    )
                    if owned and all(saved.get(key) == value for key, value in updates.items()):
                        return saved
                    raise
            raise CheckpointError('ownership_lost')

    def initialize_checkpoint_state(self, updates, *, precondition=None):
        """Own the initial checkpoint CAS; continuation also freezes its first binding."""
        return self.update(updates, precondition=precondition)

    def renew(self):
        self.update({'execution_lease': {
            'token': self.token, 'heartbeat_at': _now().isoformat(),
            'expires_at': (_now() + timedelta(seconds=LEASE_SECONDS)).isoformat(),
            **({'claim_id': self.claim_id} if self.claim_id is not None else {}),
        }})

    def cancel_requested(self):
        return bool(self.read().get('cancellation_requested_at'))

    def ensure_publication_guard(self):
        record = self.read()
        if self.message_container is None:
            return
        guard = {
            'id': _publication_id(self.run_id), 'conversation_id': self.conversation_id,
            'user_id': self.user_id, 'run_id': self.run_id, 'token': self.token,
            'role': 'assistant_artifact', 'content': '',
            'metadata': {'is_generated_chat_artifact': True, 'orchestration_publication_guard': True},
            **({'claim_id': self.claim_id} if self.claim_id is not None else {}),
        }
        try:
            self.message_container.create_item(body=guard)
            return
        except exceptions.CosmosResourceExistsError:
            if self.claim_id is None:
                raise
        submission = record.get('continuation_submission') or {}
        previous = submission.get('publication_guard')
        if submission.get('claim_id') != self.claim_id or type(previous) is not dict:
            raise CheckpointError('ownership_lost')
        for _ in range(8):
            self.read()
            current = self.message_container.read_item(
                item=guard['id'], partition_key=self.conversation_id,
            )
            if self._owns_publication_guard(current):
                return
            if (
                any(current.get(key) != guard[key] for key in (
                    'id', 'conversation_id', 'user_id', 'run_id', 'role',
                ))
                or (current.get('metadata') or {}).get('orchestration_publication_guard') is not True
                or current.get('token') != self.token
                or current.get('claim_id') != previous.get('claim_id')
                or previous.get('present') is not True
            ):
                raise CheckpointError('ownership_lost')
            replacement = run_store._strip_cosmos_metadata(deepcopy(current))
            replacement.update({'token': self.token, 'claim_id': self.claim_id})
            try:
                self.message_container.replace_item(
                    item=guard['id'], body=replacement, etag=current['_etag'],
                    match_condition=MatchConditions.IfNotModified,
                )
                self.read()
                return
            except exceptions.CosmosAccessConditionFailedError:
                continue
        raise CheckpointError('ownership_lost')

    def start(self):
        self.update({'finalization_status': 'pending'})
        self.ensure_publication_guard()

        def heartbeat():
            while not self.stopped.wait(HEARTBEAT_SECONDS):
                try:
                    self.renew()
                except Exception as exc:
                    self.failed = CheckpointError('ownership_lost')
                    log_event(
                        '[ORCHESTRATION_RUNS] Execution heartbeat failed closed.',
                        extra={'run_id': self.run_id, 'error_type': type(exc).__name__}, level=logging.ERROR,
                    )
                    return

        self.thread = threading.Thread(target=heartbeat, name=f'orchestration-lease-{self.run_id}', daemon=True)
        self.thread.start()
        return self

    def close(self, *, release=False):
        self.stopped.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=HEARTBEAT_SECONDS + 1)
        if release:
            return self.update({'execution_lease': None})


def claim_waiting_continuation(run_id, user_id, data, *, authorize, message_container=None):
    """Claim one explicit v2 refresh without changing producer attempt or guard token.

    Returns ``{"acquired": bool, "record": private_run_record}``. A repeated
    submission returns acquired=False and MUST NOT dispatch another worker.
    """
    if (
        type(data) is not dict or set(data) != _CONTINUATION_FIELDS
        or not all(_valid_id(data.get(key)) for key in _CONTINUATION_FIELDS)
    ):
        raise RecoveryError('Invalid continuation request.', code='invalid_request', status_code=400)
    conversation_id = data['conversation_id']
    record = _owned(run_id, user_id, conversation_id, authorize)
    request_digest = fingerprint(data)
    previous = record.get('continuation_submission') or {}
    if previous.get('submission_id') == data['submission_id']:
        if previous.get('fingerprint') != request_digest:
            raise RecoveryError(code='recovery_changed')
        return {'acquired': False, 'record': record}
    if (
        plan_contract_version(record.get('plan')) != 2
        or record.get('checkpoint_version') != CHECKPOINT_VERSION
        or not record.get('execution_binding')
    ):
        raise RecoveryError(code='legacy_no_checkpoints')
    approval = record.get('approval') or (record.get('plan') or {}).get('approval') or {}
    if (
        record.get('recovery_version') != data['expected_version']
        or record.get('latest_attempt_run_id') not in (None, record['id'])
        or approval.get('state') != 'approved'
        or record.get('cancellation_requested_at')
        or record.get('status') not in {'waiting', 'running'}
    ):
        raise RecoveryError(code='recovery_changed')
    try:
        deadline = datetime.fromisoformat(record['execution_deadline_at'])
        if deadline.tzinfo is None:
            raise ValueError('A persisted timezone is required.')
    except (KeyError, TypeError, ValueError) as exc:
        raise RecoveryError(code='recovery_changed') from exc
    if deadline <= _now():
        failure = build_failure('run_timeout')
        try:
            stopped = _replace(record, {
                'status': 'failed', 'outcome': 'failed', 'failure': failure,
                'error': failure['message'], 'execution_lease': None, 'completed_at': _now().isoformat(),
                'recovery_version': uuid.uuid4().hex,
            })
        except exceptions.CosmosAccessConditionFailedError as exc:
            raise RecoveryError(code='recovery_changed') from exc
        fence_publication(stopped, message_container)
        raise RecoveryError(failure['message'], code='run_timeout')
    if _live(record):
        raise RecoveryError('Another worker owns this continuation.', code='execution_live')
    store = checkpoint_store(record, authorize)
    lifecycle = store._read(LIFECYCLE_ID)
    token = lifecycle.get('token')
    if (
        lifecycle.get('deleted') or not _valid_id(token)
        or ((record.get('execution_lease') or {}).get('token') not in (None, token))
    ):
        raise RecoveryError(code='ownership_lost')
    waiting = []
    planned = {step['step_id']: step for step in record['plan']['steps']}
    for step in _execution_steps(record):
        if step.get('status') == 'running':
            raise RecoveryError(code='result_commit_unconfirmed')
        if step.get('status') != 'waiting' or not store.has_manifest(step['step_id'], waiting=True):
            continue
        payload = store.load(step['step_id'], waiting=True)
        if (
            payload.get('binding') != record['execution_binding']
            or type(payload.get('result', {}).get('wait')) is not dict
            or not payload['result']['wait']
        ):
            raise RecoveryError(code='checkpoint_invalid')
        declared = planned.get(step['step_id'])
        if declared is None or declared.get('enabled') is not True:
            raise RecoveryError(code='checkpoint_invalid')
        capability = get_capability(declared['capability_id'], contract_version=2)
        if payload['result'].get('task_result') is not None:
            pending = TaskResult.from_dict(payload['result']['task_result'])
            if pending.status != 'pending' or pending.outputs:
                raise RecoveryError(code='checkpoint_invalid')
            producer = pending.producer
        else:
            original = store.load(step['step_id'], input_only=True)
            producer = ProducerIdentity.from_dict(original['result_producer'])
            if declared.get('role') != 'render':
                raise RecoveryError(code='checkpoint_invalid')
        if (
            capability is None
            or producer != ProducerIdentity(
                user_id, conversation_id, run_id, record.get('attempt_index', 1),
                step['step_id'], declared['capability_id'], capability['result_contract_version'],
            )
        ):
            raise RecoveryError(code='recovery_changed')
        waiting.append(step['step_id'])
    if not waiting:
        raise RecoveryError(code='result_not_ready')
    publication_guard = None
    if message_container is not None:
        try:
            guard = message_container.read_item(
                item=_publication_id(run_id), partition_key=conversation_id,
            )
        except exceptions.CosmosResourceNotFoundError:
            publication_guard = {'present': False, 'claim_id': None}
        else:
            if (
                guard.get('user_id') != user_id or guard.get('conversation_id') != conversation_id
                or guard.get('run_id') != run_id or guard.get('role') != 'assistant_artifact'
                or (guard.get('metadata') or {}).get('orchestration_publication_guard') is not True
                or guard.get('token') != token
            ):
                raise RecoveryError(code='ownership_lost')
            publication_guard = {'present': True, 'claim_id': guard.get('claim_id')}
    claim_id = uuid.uuid4().hex
    updates = {
        'status': 'running', 'execution_lease': {**lease_fields(), 'token': token, 'claim_id': claim_id},
        'recovery_version': uuid.uuid4().hex,
        'continuation_submission': {
            'submission_id': data['submission_id'], 'fingerprint': request_digest,
            'claim_id': claim_id, 'waiting_step_ids': waiting,
            'checkpoint_claim_id': lifecycle.get('claim_id'), 'publication_guard': publication_guard,
        },
    }
    try:
        claimed = _replace(record, updates)
    except exceptions.CosmosAccessConditionFailedError as exc:
        raise RecoveryError(code='recovery_changed') from exc
    except Exception:
        claimed = _owned(run_id, user_id, conversation_id, authorize)
        if any(claimed.get(key) != value for key, value in updates.items()):
            raise
    lease = ExecutionLease(claimed, authorize, message_container=message_container)
    checkpoint_store(
        claimed, lease.read, token=token, claim_id=claim_id,
    ).adopt_claim(lifecycle.get('claim_id'))
    lease.ensure_publication_guard()
    if lease.cancel_requested():
        failure = build_failure('user_cancelled')
        cancelled = lease.update({
            'status': 'cancelled', 'outcome': 'cancelled', 'failure': failure,
            'completed_at': _now().isoformat(), 'execution_lease': None,
        })
        fence_publication(cancelled, message_container)
        raise RecoveryError(failure['message'], code='user_cancelled')
    return {'acquired': True, 'record': lease.read()}


def request_cancellation(run_id, user_id, conversation_id, authorize, *, analysis_cancel=None):
    for _ in range(8):
        record = _owned(run_id, user_id, conversation_id, authorize)
        try:
            if record.get('status') not in _TERMINAL or _live(record):
                record = _replace(record, {
                    'cancellation_requested_at': record.get('cancellation_requested_at') or _now().isoformat(),
                    'cancellation_requested_by': user_id,
                })
        except exceptions.CosmosAccessConditionFailedError:
            continue
        analyze_steps = _retained_producer_steps(record)
        if analyze_steps:
            # Keep this optional I/O dependency out of unrelated run recovery.
            if analysis_cancel is None:
                from functions_workflow_result_store import cancel_orchestration_analysis_result
                analysis_cancel = cancel_orchestration_analysis_result
            try:
                for step in analyze_steps:
                    analysis_cancel(user_id, conversation_id, run_id, step['step_id'])
            except Exception as exc:
                log_event(
                    '[ORCHESTRATION_RUNS] Analysis cancellation fence could not be confirmed.',
                    extra={'run_id': run_id, 'error_type': type(exc).__name__}, level=logging.ERROR,
                )
                raise RecoveryError('The cancellation could not be confirmed. Please retry.', status_code=503) from exc
        return record
    raise RecoveryError('The cancellation could not be saved. Please retry.', status_code=503)


def _validate_payload_sources(payload, context, settings, user_id):
    state = payload.get('state') or {}
    if getattr(context, 'plan_contract_version', 1) == 2:
        if state.get('plan_contract_version') != 2:
            raise CheckpointError('checkpoint_invalid')
        try:
            service = require_result_service(context)
            tasks = state.get('task_results')
            aliases = state.get('result_aliases')
            if type(tasks) is not dict or type(aliases) is not dict:
                raise CheckpointError('checkpoint_invalid')
            references = []
            for step_id, value in tasks.items():
                task = TaskResult.from_dict(value)
                if step_id != task.producer.step_id:
                    raise CheckpointError('checkpoint_invalid')
                service.access.authorize_producer(task.producer)
                references.extend(task.outputs)
            for alias, value in aliases.items():
                reference = ResultRef.from_dict(value)
                if alias != reuse_alias(reference) and context.result_aliases.get(alias) != reference:
                    raise CheckpointError('recovery_changed')
                references.append(reference)
            for reference in references:
                service.open_result(reference, allow_partial=True, require_current_sources=True).recheck()
                if (
                    reference.producer.run_id != context.run_id
                    or reference.producer.attempt_index != context.attempt_index
                ):
                    context.result_aliases[reuse_alias(reference)] = reference
        except (exceptions.CosmosResourceNotFoundError, ResourceNotFoundError) as exc:
            raise CheckpointError('result_unavailable') from exc
        except _STORAGE_READ_ERRORS as exc:
            raise CheckpointError('checkpoint_storage_unavailable') from exc
        except (ResultContractError, ResultUnavailableError, PermissionError, ScreeningError) as exc:
            raise_source_service_failure(exc)
            raise CheckpointError('result_unavailable') from exc
        return
    saved_analyses = state.get('saved_analyses', [])
    if not isinstance(saved_analyses, list):
        raise CheckpointError('checkpoint_invalid')
    if saved_analyses:
        # Recovery needs access checks, not legacy full-data/model materialization.
        from functions_saved_analysis import (
            load_orchestration_analysis_input,
            load_saved_analysis,
            saved_analysis_context,
        )

        for descriptor in saved_analyses:
            if not isinstance(descriptor, dict) or not isinstance(descriptor.get('binding'), dict):
                raise CheckpointError('checkpoint_invalid')
            try:
                if descriptor['binding'].get('kind') == 'orchestration':
                    load_orchestration_analysis_input(user_id, descriptor, authorize_only=True)
                elif descriptor['binding'].get('kind') in {'chat', 'workflow'}:
                    load_saved_analysis(user_id, saved_analysis_context(descriptor))
                else:
                    raise CheckpointError('checkpoint_invalid')
            except CheckpointError:
                raise
            except Exception as exc:
                raise CheckpointError('context_unavailable') from exc
    saved = state.get('execution_manifest') or []
    document_ids = set(state.get('documents_touched') or [])
    document_ids.update(
        citation['document_id'] for citation in state.get('citations') or []
        if isinstance(citation, dict) and citation.get('document_id')
    )
    if document_ids:
        # Only direct document checks need the adapter's source resolver.
        from functions_orchestration_adapters import resolve_context_source_manifest

        fresh = resolve_context_source_manifest(context, sorted(document_ids), settings=settings, user_id=user_id)
        by_id = {item.get('document_id'): item for item in fresh}
        original = {item.get('document_id'): item for item in saved}
        for document_id in document_ids:
            current = by_id.get(document_id) or {}
            prior = original.get(document_id) or {}
            if (
                current.get('authorization_status') != 'authorized'
                or not prior or prior.get('source_version') != current.get('source_version')
                or prior.get('source_revision') != current.get('source_revision')
                or (prior.get('source_version') is None and not prior.get('source_revision'))
                or prior.get('scope') != current.get('scope')
                or prior.get('scope_id') != current.get('scope_id')
            ):
                raise CheckpointError('context_unavailable')
    artifacts = state.get('artifacts') or []
    if artifacts:
        validate_artifacts = getattr(context, 'validate_checkpoint_artifacts', None)
        if not callable(validate_artifacts) or validate_artifacts(artifacts) is not True:
            raise CheckpointError('context_unavailable')
        versions = getattr(context, 'checkpoint_artifact_versions', None)
        if not callable(versions) or versions(artifacts) != payload.get('artifact_versions'):
            raise CheckpointError('context_unavailable')


def validate_resume(record, context, settings, authorize, *, source_run_id=None, allow_waiting=False):
    """Reconstruct from persisted data without invoking any capability."""
    source_id = record['id'] if allow_waiting else (
        source_run_id or record.get('retry_of_run_id') or record['id']
    )
    source = _owned(source_id, record['user_id'], record['conversation_id'], authorize)
    if (
        (source.get('turn_id') or source['plan'].get('turn_id')) != (record.get('turn_id') or record['plan'].get('turn_id'))
        or effective_plan(source['plan']) != effective_plan(record['plan'])
        or (source_id != record['id'] and source.get('latest_attempt_run_id') != record['id'])
    ):
        raise CheckpointError('recovery_changed')
    dependency_contract = plan_contract_version(record['plan']) == 2
    if dependency_contract and getattr(context, 'export_catalog', None) is not None:
        admitted_pairs = admitted_export_pairs(context.export_catalog)
        for step in record['plan'].get('steps') or []:
            if step['capability_id'] == 'render_file' and (
                step['arguments']['output_format'], step['arguments']['profile']
            ) not in admitted_pairs:
                raise CheckpointError('context_unavailable')
    if allow_waiting and (
        not dependency_contract or source_id != record['id'] or context.run_id != source_id
        or context.attempt_index != source.get('attempt_index', 1)
    ):
        raise CheckpointError('ownership_lost')
    result_service = require_result_service(context) if dependency_contract else None
    source = reconcile_checkpoints(source, authorize, result_service=result_service)
    binding = context_binding(context, record['plan'], settings)
    if source.get('execution_binding') != binding:
        raise CheckpointError('recovery_changed')
    source_steps = {step['step_id']: step for step in _execution_steps(source)}
    # A continuation keeps failed steps terminal; any other resume runs them again, so a
    # step that completed without one of their outputs cannot be reused.
    stale = set() if allow_waiting else _reuse_invalidated_by_rerun(record, {
        step_id for step_id, saved in source_steps.items() if saved.get('status') in _retained_statuses(source)
    })
    payloads = {}
    state_fields = STATE_FIELDS + OPTIONAL_STATE_FIELDS + (DEPENDENCY_STATE_FIELDS if dependency_contract else ())
    initial_state = {key: deepcopy(getattr(context, key, None)) for key in state_fields}
    absent_optional_fields = {key for key in state_fields if not hasattr(context, key)}
    completed_before = set(getattr(context, '_completed_result_step_ids', ()))
    context._completed_result_step_ids = set(completed_before)
    try:
        context.execution_manifest = deepcopy(source.get('execution_initial_manifest') or [])
        interrupted = False
        for step in record['plan'].get('steps') or []:
            if not step.get('enabled', True) or step.get('capability_id') == 'respond':
                continue
            saved = source_steps.get(step['step_id']) or {}
            if dependency_contract and saved.get('status') == 'waiting':
                if not allow_waiting:
                    raise CheckpointError('result_not_ready')
                source_store = checkpoint_store(source, authorize)
                if not source_store.has_manifest(step['step_id'], waiting=True):
                    continue
                payload = source_store.load(step['step_id'], waiting=True)
                if (
                    payload.get('binding') != binding
                    or payload.get('input_fingerprint') != step_input_fingerprint(
                        step, context, binding, settings=settings,
                    )
                ):
                    raise CheckpointError('recovery_changed')
                _validate_payload_sources(payload, context, settings, record['user_id'])
                restore_context(context, payload)
                payloads[step['step_id']] = payload
                continue
            if dependency_contract and saved.get('status') == 'running':
                raise CheckpointError('result_commit_unconfirmed')
            if saved.get('status') not in _retained_statuses(source) or step['step_id'] in stale:
                interrupted = True
                continue
            # A later success consumed the old earlier_findings. Never repair that
            # invalid input by silently repeating a successful external operation.
            if interrupted and not dependency_contract:
                raise CheckpointError('recovery_changed')
            payload = _completed_checkpoint(source, step['step_id'], authorize, result_service=result_service)
            if (
                payload.get('binding') != binding
                or payload.get('input_fingerprint') != step_input_fingerprint(step, context, binding, settings=settings)
            ):
                raise CheckpointError('recovery_changed')
            _validate_payload_sources(payload, context, settings, record['user_id'])
            restore_context(context, payload)
            context._completed_result_step_ids.add(step['step_id'])
            payloads[step['step_id']] = payload
    finally:
        context._completed_result_step_ids = completed_before
        for key, value in initial_state.items():
            if key in absent_optional_fields:
                if hasattr(context, key):
                    delattr(context, key)
            else:
                setattr(context, key, value)
    return payloads


def prepare_retry(run_id, user_id, data, *, authorize, validate, message_container=None):
    if (
        not isinstance(data, dict) or set(data) - _RETRY_FIELDS
        or not all(_valid_id(data.get(key)) for key in ('conversation_id', 'submission_id', 'expected_version'))
        or type(data.get('confirm_external_effects', False)) is not bool
    ):
        raise RecoveryError('Invalid retry request.', code='invalid_request', status_code=400)
    conversation_id = data['conversation_id']
    record = _owned(run_id, user_id, conversation_id, authorize)
    request_digest = fingerprint(data)
    submission = record.get('retry_submission') or {}
    if submission.get('submission_id') == data['submission_id']:
        if submission.get('fingerprint') != request_digest:
            raise RecoveryError('This retry submission changed.', code='recovery_changed')
        return _owned(submission['run_id'], user_id, conversation_id, authorize)
    # The validate callback below rechecks v2 receipt chains with its initialized
    # service. Structural admission alone cannot reopen a receipt-backed ancestor.
    record = reconcile_checkpoints(
        record, authorize, _defer_inherited_validation=plan_contract_version(record['plan']) == 2,
    )
    recovery = recovery_projection(record)
    if record.get('recovery_version') != data['expected_version'] or recovery.get('current_run_id'):
        raise RecoveryError(
            'The recovery state changed. Reload this run.', code='recovery_changed',
            recovery=recovery, current_run_id=recovery.get('current_run_id'),
        )
    receipt_candidate = (
        plan_contract_version(record['plan']) == 2 and recovery['reason_code'] == 'result_commit_unconfirmed'
    )
    if not recovery['eligible'] and not receipt_candidate:
        raise RecoveryError(recovery['message'], recovery=recovery)
    if recovery['requires_confirmation'] and not data.get('confirm_external_effects'):
        raise RecoveryError(
            'This step may already have performed external actions. Confirm before retrying.',
            code='confirmation_required', recovery=recovery,
        )
    if not callable(validate):
        raise RecoveryError()
    try:
        payloads = validate(record)
        if not isinstance(payloads, dict):
            raise CheckpointError('checkpoint_invalid')
        if plan_contract_version(record['plan']) == 2:
            planned = {step['step_id']: step for step in record['plan']['steps'] if step.get('enabled')}
            if set(payloads) - set(planned) or set(recovery['reused_step_ids']) - set(payloads):
                raise CheckpointError('checkpoint_invalid')
            records = {step['step_id']: step for step in _execution_steps(record)}
            for step_id, payload in payloads.items():
                if (
                    payload.get('step_id') != step_id or payload.get('binding') != record.get('execution_binding')
                    or (payload.get('result') or {}).get('status') not in _retained_statuses(record)
                ):
                    raise CheckpointError('checkpoint_invalid')
                saved = records.setdefault(step_id, {
                    'step_id': step_id, 'capability_id': planned[step_id]['capability_id'],
                })
                saved.update({
                    'status': payload['result']['status'], 'checkpoint_available': True,
                    'effects_uncertain': False, 'failure': None, 'error': None,
                })
            record['execution_steps'] = list(records.values())
            recovery = recovery_projection(record)
            if not recovery['eligible'] or set(payloads) != set(recovery['reused_step_ids']):
                raise CheckpointError(recovery['reason_code'] or 'checkpoint_invalid')
        elif set(payloads) != set(recovery['reused_step_ids']):
            raise CheckpointError('checkpoint_invalid')
    except CheckpointError as exc:
        blocked = {**recovery, 'eligible': False, 'reason_code': exc.code, 'message': exc.failure['message']}
        if exc.code == 'checkpoint_storage_unavailable':
            raise RecoveryError(
                exc.failure['message'], code=exc.code, status_code=503, recovery=blocked,
            ) from exc
        raise RecoveryError(exc.failure['message'], recovery=blocked) from exc
    except (ValueError, PermissionError) as exc:
        raise RecoveryError(build_failure('context_unavailable')['message']) from exc

    # Fence the steps partition first. If the later parent CAS loses, the old
    # attempt remains safely fenced and the winning successor is authoritative.
    checkpoint_store(record, authorize).fence(allow_missing=bool(record.get('inherited_checkpoints')))
    fence_publication(record, message_container)
    current = _owned(run_id, user_id, conversation_id, authorize)
    if current.get('_etag') != record.get('_etag'):
        raise RecoveryError('The recovery state changed. Reload this run.', code='recovery_changed')
    child_id = f'run_{uuid.uuid4().hex}'
    child = run_store._strip_cosmos_metadata(deepcopy(record))
    for key in (
        'execution_steps', 'execution_lease', 'failure', 'failures', 'outcome',
        'assistant_message_id', 'cancellation_requested_at', 'cancellation_requested_by',
        'retry_submission', 'latest_attempt_run_id', 'recovery_blocked_code', 'message_saved',
        'edit_claim', 'edit_pending', 'edit_narrowing', 'terminal_publication', 'finalization_status',
        'inherited_checkpoints', 'chat_content_checked_output', 'chat_content_output_pending',
    ):
        child.pop(key, None)
    if plan_contract_version(record['plan']) == 2:
        for key in (
            'execution_deadline_at', 'pending_results', 'task_results', 'outputs', 'result_outputs',
            'message', 'summary', 'final_response', 'delivery_facts',
        ):
            child.pop(key, None)
    child.update({
        'id': child_id, 'run_id': child_id, 'status': 'awaiting_approval',
        'created_at': _now().isoformat(), 'started_at': None, 'completed_at': None,
        'error': None, 'token_usage': {}, 'planning_token_usage': {},
        'artifacts': [], 'documents_touched': [], 'execution_steps': [],
        'retry_of_run_id': run_id, 'attempt_index': (record.get('attempt_index') or 1) + 1,
        'attempt_root_run_id': record.get('attempt_root_run_id') or run_id,
        'recovery_version': uuid.uuid4().hex, 'edit_version': uuid.uuid4().hex,
        'retry_reused_step_ids': recovery['reused_step_ids'],
        'retry_confirmed_external_effects': bool(data.get('confirm_external_effects')),
        'inherited_checkpoints': {
            step_id: {
                'source_run_id': run_id, 'payload_digest': fingerprint(payload),
                'provenance': deepcopy(payload['provenance']),
                **({'status': payload['result']['status']} if plan_contract_version(record['plan']) == 2 else {}),
            } for step_id, payload in payloads.items()
        },
    })
    child['plan'] = deepcopy(record['plan'])
    child['plan'].update({'run_id': child_id, 'status': 'awaiting_approval', 'edit_version': child['edit_version']})
    for step in child['plan'].get('steps') or []:
        step['status'] = 'pending'
    child['approval'] = {
        **(child['plan'].get('approval') or {}), 'mode': 'manual', 'state': 'pending',
        'approved_at': None, 'approved_by': None,
    }
    child['plan']['approval'] = deepcopy(child['approval'])
    child['plan_summary'] = summarize_plan(child['plan'])
    child['execution_steps'] = _execution_steps(child)
    parent = run_store._strip_cosmos_metadata(deepcopy(record))
    parent.update({
        'latest_attempt_run_id': child_id, 'execution_lease': None,
        'retry_submission': {'submission_id': data['submission_id'], 'fingerprint': request_digest, 'run_id': child_id},
    })
    if parent.get('status') not in _TERMINAL:
        failure = build_failure('execution_expired')
        parent.update({
            'status': 'failed', 'outcome': 'failed', 'failure': failure,
            'failures': [failure], 'error': failure['message'], 'completed_at': _now().isoformat(),
        })
    try:
        run_store.cosmos_orchestration_runs_container.execute_item_batch(
            batch_operations=[
                ('replace', (run_id, parent), {'if_match_etag': record['_etag']}),
                ('create', (child,)),
            ], partition_key=conversation_id,
        )
    except Exception as exc:
        # An ambiguous response can be a committed batch. A repeated stable request
        # returns that same child, including after a process restart.
        latest = _owned(run_id, user_id, conversation_id, authorize)
        saved = latest.get('retry_submission') or {}
        if saved.get('submission_id') == data['submission_id'] and saved.get('fingerprint') == request_digest:
            return _owned(saved['run_id'], user_id, conversation_id, authorize)
        if latest.get('latest_attempt_run_id'):
            raise RecoveryError(
                'A newer attempt already exists.', code='recovery_changed',
                current_run_id=latest['latest_attempt_run_id'],
            ) from exc
        raise RecoveryError('Retry preparation could not be saved. Retry the same request.', status_code=503) from exc
    return _owned(child_id, user_id, conversation_id, authorize)


class ExecutionCheckpoints:
    def __init__(self, record, context, settings, lease):
        self.record = record
        self.context = context
        self.settings = settings
        self.lease = lease
        dependency_contract = plan_contract_version(record['plan']) == 2
        claim_id = getattr(lease, 'claim_id', None)
        self.continuing = bool(
            dependency_contract and claim_id
            and (record.get('continuation_submission') or {}).get('claim_id') == claim_id
        )
        if dependency_contract and record.get('execution_deadline_at'):
            context.execution_deadline_at = record['execution_deadline_at']
        self.binding = context_binding(context, record['plan'], settings)
        self.store = checkpoint_store(record, lease.read, token=lease.token, claim_id=claim_id)
        self.reused = validate_resume(
            record, context, settings, lease.authorize, allow_waiting=self.continuing,
        ) if (
            record.get('retry_of_run_id') or (dependency_contract and record.get('execution_binding'))
        ) else {}
        self.records = _execution_steps(record)
        self.terminal_results = {
            row['step_id']: build_step_result(
                status=row['status'], failure=safe_failure(row.get('failure') or build_failure('step_failed')),
                **({'task_result': TaskResult.from_dict(row['task_result'])}
                   if row.get('task_result') is not None and row['status'] == 'failed' else {}),
            )
            for row in self.records
            if self.continuing and row['step_id'] not in self.reused and row.get('status') in ('failed', 'cancelled')
        }

    def initialize(self):
        self.lease.initialize_checkpoint_state({
            'checkpoint_version': CHECKPOINT_VERSION, 'execution_binding': self.binding,
            'execution_steps': deepcopy(self.records), 'attempt_index': self.record.get('attempt_index') or 1,
            'execution_initial_manifest': (
                context_state(self.context)['execution_manifest']
                if self.context.plan_contract_version == 2 else deepcopy(self.context.execution_manifest)
            ),
            **({'execution_deadline_at': self.context.execution_deadline_at}
               if self.context.plan_contract_version == 2 else {}),
        })
        self.store.initialize()

    def before_step(self, step):
        self.lease.read()
        revalidate = getattr(self.context, 'revalidate_conversation_context', None)
        if callable(revalidate):
            revalidate()
        value = self.reused.get(step['step_id'])
        if value:
            if value['input_fingerprint'] != step_input_fingerprint(
                step, self.context, self.binding, settings=self.settings,
            ):
                raise CheckpointError('recovery_changed')
            _validate_payload_sources(value, self.context, self.settings, self.record['user_id'])
        return value

    def previous_terminal_result(self, step):
        self.lease.read()
        result = deepcopy(self.terminal_results.get(step['step_id']))
        if result and result.get('task_result') is not None:
            validate_task_diagnostics(step, self.context, result['task_result'])
        return result

    def begin_step(self, step, input_fingerprint):
        self.lease.read()
        self.store.commit_input(
            step, self.context, input_fingerprint=input_fingerprint, binding=self.binding,
        )

    def save_step(self, record):
        self.store.save_step(record)
        self.records = [row for row in self.records if row['step_id'] != record['step_id']] + [deepcopy(record)]
        updates = {'execution_steps': self.records}
        if self.context.plan_contract_version == 2:
            current = self.lease.read()
            task_results = deepcopy(current.get('task_results', {}))
            pending_results = deepcopy(current.get('pending_results', {}))
            if type(task_results) is not dict or type(pending_results) is not dict:
                raise CheckpointError('checkpoint_invalid')
            step_id = record['step_id']
            task = record.get('task_result') if record['status'] in ('completed', 'partial', 'waiting') else None
            if task is not None:
                parsed = TaskResult.from_dict(task)
                if parsed.producer.step_id != step_id:
                    raise CheckpointError('checkpoint_invalid')
                task_results[step_id] = parsed.to_dict()
            else:
                task_results.pop(step_id, None)
            if record['status'] == 'waiting' and record.get('wait'):
                pending_results[step_id] = deepcopy(record['wait'])
            else:
                pending_results.pop(step_id, None)
            updates.update(
                task_results=task_results, pending_results=pending_results,
                execution_deadline_at=self.context.execution_deadline_at,
            )
        self.lease.update(updates)

    def commit(self, step, result, input_fingerprint, *, reused=None):
        self.lease.read()
        if reused and self.context.plan_contract_version == 2 and self.store.has_manifest(step['step_id']):
            existing = self.store.load(step['step_id'])
            if fingerprint(existing) != fingerprint(reused):
                raise CheckpointError('recovery_changed')
            return
        if not reused and self.context.documents_touched and self.context.plan_contract_version == 1:
            # Capture versions for search-discovered sources as well as named ones.
            from functions_orchestration_adapters import resolve_context_source_manifest

            manifest = resolve_context_source_manifest(
                self.context, self.context.documents_touched, settings=self.settings, user_id=self.record['user_id'],
            )
            if any(
                not any(item.get('document_id') == document_id and item.get('authorization_status') == 'authorized' for item in manifest)
                for document_id in self.context.documents_touched
            ):
                raise CheckpointError('context_unavailable')
            self.context.execution_manifest = manifest
        versions = (reused or {}).get('artifact_versions') or {}
        if not reused and self.context.artifacts and self.context.plan_contract_version == 1:
            resolve_versions = getattr(self.context, 'checkpoint_artifact_versions', None)
            if not callable(resolve_versions):
                raise CheckpointError('context_unavailable')
            versions = resolve_versions(self.context.artifacts)
        self.store.commit(
            step, result, self.context, input_fingerprint=input_fingerprint, binding=self.binding,
            provenance=(reused or {}).get('provenance'),
            artifact_versions=versions,
        )


def cleanup_conversation_checkpoints(
    conversation_id, user_id, authorize, *, message_container=None, conversation_container=None,
    analysis_cleanup=None, analysis_fence=None, output_cleanup=None, retain_committed=False,
):
    """Fence and enroll owned output cleanup before removing retained payloads."""
    if not callable(authorize) or authorize() is False:
        raise RecoveryError(code='not_found', status_code=404)
    if conversation_container is not None:
        for _ in range(8):
            conversation = conversation_container.read_item(item=conversation_id, partition_key=conversation_id)
            if conversation.get('user_id') != user_id:
                raise RecoveryError(code='not_found', status_code=404)
            replacement = run_store._strip_cosmos_metadata(conversation)
            replacement['orchestration_deleted'] = True
            try:
                conversation_container.replace_item(
                    item=conversation_id, body=replacement, etag=conversation['_etag'],
                    match_condition=MatchConditions.IfNotModified,
                )
                break
            except exceptions.CosmosAccessConditionFailedError:
                continue
        else:
            raise CheckpointError()
    rows = list(run_store.cosmos_orchestration_runs_container.query_items(
        query='SELECT * FROM c WHERE c.conversation_id = @conversation_id AND c.user_id = @user_id',
        parameters=[{'name': '@conversation_id', 'value': conversation_id}, {'name': '@user_id', 'value': user_id}],
        partition_key=conversation_id,
    ))
    visited = set()
    cleanup_runs = []
    for row in rows:
        if row['id'] in visited:
            continue
        visited.add(row['id'])
        if not run_store._is_run_record(row) or row.get('user_id') != user_id:
            continue
        for _ in range(8):
            if authorize() is False:
                raise RecoveryError(code='not_found', status_code=404)
            current = read_revision_run(row['id'], user_id, conversation_id)
            updates = {
                'checkpoints_deleted': True, 'execution_lease': None,
                'recovery_blocked_code': 'context_unavailable',
            }
            intent = None
            if plan_contract_version(current.get('plan')) == 2:
                intent = build_output_cleanup_intent(current, retain_committed=retain_committed)
                if intent['output_ids'] and output_cleanup is not None and not callable(output_cleanup):
                    raise RecoveryError(
                        'Generated-file cleanup is unavailable. The conversation was not deleted.',
                        code='output_cleanup_required', status_code=503,
                    )
                updates['output_cleanup'] = intent
            elif current.get('render_output_ids') or 'output_cleanup' in current:
                raise CheckpointError('checkpoint_invalid')
            store = None
            if type(current.get('checkpoint_version')) is int and current['checkpoint_version'] == CHECKPOINT_VERSION:
                store = checkpoint_store(current, authorize)
                # A lost parent acknowledgment must already have genuine deletion proof.
                store.fence(deleted=True, allow_missing=True)
            elif intent is not None and intent['output_ids']:
                raise CheckpointError('checkpoint_invalid')
            fence_publication(current, message_container)
            try:
                current = _replace(current, updates)
                break
            except exceptions.CosmosAccessConditionFailedError:
                continue
        else:
            raise CheckpointError()
        if current.get('latest_attempt_run_id') and current['latest_attempt_run_id'] not in visited:
            rows.append(read_revision_run(current['latest_attempt_run_id'], user_id, conversation_id))
        cleanup_runs.append((current, store))

    for index, (current, store) in enumerate(cleanup_runs):
        intent = current.get('output_cleanup') if plan_contract_version(current.get('plan')) == 2 else None
        if intent is None or not intent['output_ids']:
            continue
        if output_cleanup is None:
            # Initialize output services only after every deletion fence and intent is durable.
            from functions_orchestration_bootstrap import build_orchestration_cleanup_service

            output_cleanup = build_orchestration_cleanup_service(user_id, conversation_id).enroll_run_cleanup
        enrolled = output_cleanup(current['id'])
        expected = {
            'run_id': current['id'], 'enrollment_status': 'completed',
            'output_count': len(intent['output_ids']), 'retain_committed': intent['retain_committed'],
        }
        if (
            type(enrolled) is not dict or enrolled != expected
            or type(enrolled.get('output_count')) is not int
            or type(enrolled.get('retain_committed')) is not bool
        ):
            raise RecoveryError(
                'Generated-file cleanup could not be confirmed.',
                code='output_cleanup_unconfirmed', status_code=503,
            )
        confirmed = read_revision_run(current['id'], user_id, conversation_id)
        if (
            confirmed.get('checkpoints_deleted') is not True
            or build_output_cleanup_intent(
                confirmed, retain_committed=intent['retain_committed'],
            ) != {**intent, 'state': 'completed'}
        ):
            raise RecoveryError(
                'Generated-file cleanup could not be confirmed.',
                code='output_cleanup_unconfirmed', status_code=503,
            )
        cleanup_runs[index] = (confirmed, store)

    # Enroll every owned run before any source-cleanup failure can stop this sweep.
    for current, store in cleanup_runs:
        if authorize() is False:
            raise RecoveryError(code='not_found', status_code=404)
        if _retained_producer_steps(current):
            if analysis_cleanup is None:
                # Resolve private result I/O only for runs that actually planned Analyze.
                from functions_workflow_result_store import (
                    delete_orchestration_analysis_results,
                    fence_orchestration_analysis_result,
                )
                analysis_cleanup = delete_orchestration_analysis_results
                analysis_fence = analysis_fence or fence_orchestration_analysis_result
            if analysis_fence is not None:
                for step in _retained_producer_steps(current):
                    analysis_fence(user_id, conversation_id, current['id'], step['step_id'])
            if authorize() is False:
                raise RecoveryError(code='not_found', status_code=404)
            analysis_cleanup(user_id, conversation_id, current['id'])
        if store is not None:
            store.delete_payloads()
