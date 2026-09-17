# functions_orchestration_recovery.py
"""Execution leases and explicitly requested, checkpoint-only retry attempts.

Version: 0.261.105
Retry publication is one transactional parent CAS + child create. It never
replans, invokes an adapter, or changes plan-revision lineage.
"""

import logging
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from azure.core import MatchConditions
from azure.cosmos import exceptions

import functions_orchestration_runs as run_store
from functions_appinsights import log_event
from functions_orchestration_checkpoints import (
    CHECKPOINT_VERSION, CheckpointError, CheckpointStore, context_binding,
    effective_plan, fingerprint, restore_context, step_input_fingerprint,
)
from functions_orchestration_plan_revisions import PlanRevisionError, read_revision_run
from functions_orchestration_schema import build_failure, safe_failure, summarize_plan


LEASE_SECONDS = 45
HEARTBEAT_SECONDS = 10
EFFECT_CAPABILITIES = {'agent_invoke', 'action_invoke'}
_TERMINAL = {'completed', 'failed', 'cancelled'}
_RETRY_FIELDS = {'conversation_id', 'submission_id', 'expected_version', 'confirm_external_effects'}


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


def checkpoint_store(record, authorize, *, token=None):
    return CheckpointStore(
        run_store.cosmos_orchestration_run_steps_container,
        run_id=record['id'], user_id=record['user_id'], conversation_id=record['conversation_id'],
        turn_id=record.get('turn_id') or record['plan'].get('turn_id'), authorize=authorize, token=token,
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
        if step_id in steps and steps[step_id].get('status') != 'completed':
            raise CheckpointError('checkpoint_invalid')
        steps.setdefault(step_id, {
            'step_id': step_id, 'step_index': list(planned).index(step_id),
            'capability_id': planned[step_id]['capability_id'], 'status': 'completed',
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


def _completed_checkpoint(record, step_id, authorize, visited=None):
    visited = set(visited or ())
    if record['id'] in visited or len(visited) >= 128:
        raise CheckpointError('checkpoint_invalid')
    visited.add(record['id'])
    steps = {step['step_id']: step for step in _execution_steps(record)}
    if steps.get(step_id, {}).get('status') != 'completed':
        raise CheckpointError('checkpoint_invalid')
    reference = (record.get('inherited_checkpoints') or {}).get(step_id)
    store = checkpoint_store(record, authorize)
    if store.has_manifest(step_id):
        payload = store.load(step_id)
    elif reference:
        if reference.get('source_run_id') != record.get('retry_of_run_id'):
            raise CheckpointError('checkpoint_invalid')
        try:
            parent = _owned(reference['source_run_id'], record['user_id'], record['conversation_id'], authorize)
        except RecoveryError as exc:
            raise CheckpointError('context_unavailable') from exc
        _validate_inherited_parent(record, parent)
        payload = _completed_checkpoint(parent, step_id, authorize, visited)
    else:
        raise CheckpointError('checkpoint_unavailable')
    if payload.get('binding') != record.get('execution_binding'):
        raise CheckpointError('recovery_changed')
    if not reference and payload.get('provenance') != {'run_id': record['id'], 'step_id': step_id}:
        raise CheckpointError('checkpoint_invalid')
    if reference and (
        reference.get('payload_digest') != fingerprint(payload)
        or reference.get('provenance') != payload.get('provenance')
    ):
        raise CheckpointError('checkpoint_invalid')
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
        if step.get('status') == 'completed' and step.get('capability_id') != 'respond'
    ]
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


def reconcile_checkpoints(record, authorize):
    """Read-only reconciliation of a crash after manifest commit but before progress.

    A committed successful result is never replayed just because a later run-row
    write was lost. Missing manifests on interrupted work remain uncertain.
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
    for step_id in record.get('inherited_checkpoints') or {}:
        _completed_checkpoint(record, step_id, authorize)
    store = checkpoint_store(record, authorize)
    for step in updated.get('execution_steps') or []:
        if step.get('status') not in ('running', 'failed') or step.get('capability_id') == 'respond':
            continue
        if store.has_manifest(step['step_id']):
            payload = store.load(step['step_id'])
            if payload.get('binding') != record.get('execution_binding'):
                raise CheckpointError('checkpoint_invalid')
            step.update({
                'status': 'completed', 'checkpoint_available': True, 'effects_uncertain': False,
                'failure': None, 'error': None, 'summary': payload['result'].get('summary') or 'Saved result',
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
    if record.get('outcome') in ('completed', 'partial', 'failed', 'cancelled'):
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
        self.stopped = threading.Event()
        self.failed = None
        self.thread = None
        self.lock = threading.RLock()
        self.message_container = message_container

    def publish_message(self, document):
        """Fence and message are in the same container/partition: no stale publish."""
        self.read()
        if self.message_container is None:
            raise CheckpointError('message_not_saved')
        if (
            document.get('id') != f'assistant_orchestration_{fingerprint(self.run_id)[:40]}'
            or document.get('conversation_id') != self.conversation_id or document.get('role') != 'assistant'
            or (document.get('metadata') or {}).get('orchestration', {}).get('run_id') != self.run_id
        ):
            raise CheckpointError('message_not_saved')
        item_id = _publication_id(self.run_id)
        guard = self.message_container.read_item(item=item_id, partition_key=self.conversation_id)
        if not self._owns_publication_guard(guard):
            raise CheckpointError('ownership_lost')
        replacement = run_store._strip_cosmos_metadata(guard)
        replacement['published_message_id'] = document['id']
        replacement['document_digest'] = fingerprint(run_store._strip_cosmos_metadata(document))
        try:
            self.message_container.execute_item_batch(
                batch_operations=[
                    ('replace', (item_id, replacement), {'if_match_etag': guard['_etag']}),
                    ('upsert', (document,)),
                ], partition_key=self.conversation_id,
            )
        except Exception:
            if not self._published_message_matches(document, replacement['document_digest']):
                raise
        self.read()

    def _owns_publication_guard(self, guard):
        return (
            guard.get('id') == _publication_id(self.run_id)
            and guard.get('conversation_id') == self.conversation_id
            and guard.get('run_id') == self.run_id and guard.get('user_id') == self.user_id
            and guard.get('token') == self.token and guard.get('role') == 'assistant_artifact'
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
            or not _live(record) or record.get('latest_attempt_run_id') not in (None, self.run_id)
        ):
            raise CheckpointError('ownership_lost')
        return record

    def update(self, updates):
        with self.lock:
            for _ in range(8):
                record = self.read()
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
                            ((saved.get('execution_lease') or {}).get('token') == self.token and _live(saved))
                            or (released and saved.get('execution_lease') is None)
                        )
                    )
                    if owned and all(saved.get(key) == value for key, value in updates.items()):
                        return saved
                    raise
            raise CheckpointError('ownership_lost')

    def renew(self):
        self.update({'execution_lease': {
            'token': self.token, 'heartbeat_at': _now().isoformat(),
            'expires_at': (_now() + timedelta(seconds=LEASE_SECONDS)).isoformat(),
        }})

    def cancel_requested(self):
        return bool(self.read().get('cancellation_requested_at'))

    def start(self):
        self.update({'finalization_status': 'pending'})
        if self.message_container is not None:
            guard = {
                'id': _publication_id(self.run_id), 'conversation_id': self.conversation_id,
                'user_id': self.user_id, 'run_id': self.run_id, 'token': self.token,
                'role': 'assistant_artifact', 'content': '',
                'metadata': {'is_generated_chat_artifact': True, 'orchestration_publication_guard': True},
            }
            self.message_container.create_item(body=guard)

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


def request_cancellation(run_id, user_id, conversation_id, authorize):
    for _ in range(8):
        record = _owned(run_id, user_id, conversation_id, authorize)
        if record.get('status') in _TERMINAL and not _live(record):
            return record
        try:
            return _replace(record, {
                'cancellation_requested_at': record.get('cancellation_requested_at') or _now().isoformat(),
                'cancellation_requested_by': user_id,
            })
        except exceptions.CosmosAccessConditionFailedError:
            continue
    raise RecoveryError('The cancellation could not be saved. Please retry.', status_code=503)


def _validate_payload_sources(payload, context, settings, user_id):
    # Lazy import avoids initializing adapter services in storage-only callers.
    from functions_orchestration_adapters import resolve_context_source_manifest

    state = payload.get('state') or {}
    saved = state.get('execution_manifest') or []
    document_ids = set(state.get('documents_touched') or [])
    document_ids.update(
        citation['document_id'] for citation in state.get('citations') or []
        if isinstance(citation, dict) and citation.get('document_id')
    )
    if document_ids:
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


def validate_resume(record, context, settings, authorize, *, source_run_id=None):
    """Reconstruct from persisted data without invoking any capability."""
    source_id = source_run_id or record.get('retry_of_run_id') or record['id']
    source = _owned(source_id, record['user_id'], record['conversation_id'], authorize)
    if (
        (source.get('turn_id') or source['plan'].get('turn_id')) != (record.get('turn_id') or record['plan'].get('turn_id'))
        or effective_plan(source['plan']) != effective_plan(record['plan'])
        or (source_id != record['id'] and source.get('latest_attempt_run_id') != record['id'])
    ):
        raise CheckpointError('recovery_changed')
    source = reconcile_checkpoints(source, authorize)
    binding = context_binding(context, record['plan'], settings)
    if source.get('execution_binding') != binding:
        raise CheckpointError('recovery_changed')
    source_steps = {step['step_id']: step for step in _execution_steps(source)}
    payloads = {}
    initial_state = {key: deepcopy(getattr(context, key, None)) for key in (
        'evidence', 'citations', 'artifacts', 'notes', 'documents_touched', 'step_documents',
        'execution_manifest', 'source_manifest',
    )}
    try:
        context.execution_manifest = deepcopy(source.get('execution_initial_manifest') or [])
        interrupted = False
        for step in record['plan'].get('steps') or []:
            if not step.get('enabled', True) or step.get('capability_id') == 'respond':
                continue
            saved = source_steps.get(step['step_id']) or {}
            if saved.get('status') != 'completed':
                interrupted = True
                continue
            # A later success consumed the old earlier_findings. Never repair that
            # invalid input by silently repeating a successful external operation.
            if interrupted:
                raise CheckpointError('recovery_changed')
            payload = _completed_checkpoint(source, step['step_id'], authorize)
            if (
                payload.get('binding') != binding
                or payload.get('input_fingerprint') != step_input_fingerprint(step, context, binding)
            ):
                raise CheckpointError('recovery_changed')
            _validate_payload_sources(payload, context, settings, record['user_id'])
            restore_context(context, payload)
            payloads[step['step_id']] = payload
    finally:
        for key, value in initial_state.items():
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
    record = reconcile_checkpoints(record, authorize)
    recovery = recovery_projection(record)
    if record.get('recovery_version') != data['expected_version'] or recovery.get('current_run_id'):
        raise RecoveryError(
            'The recovery state changed. Reload this run.', code='recovery_changed',
            recovery=recovery, current_run_id=recovery.get('current_run_id'),
        )
    if not recovery['eligible']:
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
        if not isinstance(payloads, dict) or set(payloads) != set(recovery['reused_step_ids']):
            raise CheckpointError('checkpoint_invalid')
    except CheckpointError as exc:
        blocked = {**recovery, 'eligible': False, 'reason_code': exc.code, 'message': exc.failure['message']}
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
        'inherited_checkpoints',
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
        self.binding = context_binding(context, record['plan'], settings)
        self.store = checkpoint_store(record, lease.read, token=lease.token)
        self.reused = validate_resume(record, context, settings, lease.authorize) if record.get('retry_of_run_id') else {}
        self.records = _execution_steps(record)

    def initialize(self):
        self.lease.update({
            'checkpoint_version': CHECKPOINT_VERSION, 'execution_binding': self.binding,
            'execution_steps': deepcopy(self.records), 'attempt_index': self.record.get('attempt_index') or 1,
            'execution_initial_manifest': deepcopy(self.context.execution_manifest),
        })
        self.store.initialize()

    def before_step(self, step):
        self.lease.read()
        revalidate = getattr(self.context, 'revalidate_conversation_context', None)
        if callable(revalidate):
            revalidate()
        value = self.reused.get(step['step_id'])
        if value:
            if value['input_fingerprint'] != step_input_fingerprint(step, self.context, self.binding):
                raise CheckpointError('recovery_changed')
            _validate_payload_sources(value, self.context, self.settings, self.record['user_id'])
        return value

    def save_step(self, record):
        self.store.save_step(record)
        self.records = [row for row in self.records if row['step_id'] != record['step_id']] + [deepcopy(record)]
        self.lease.update({'execution_steps': self.records})

    def commit(self, step, result, input_fingerprint, *, reused=None):
        self.lease.read()
        if not reused and self.context.documents_touched:
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
        if not reused and self.context.artifacts:
            resolve_versions = getattr(self.context, 'checkpoint_artifact_versions', None)
            if not callable(resolve_versions):
                raise CheckpointError('context_unavailable')
            versions = resolve_versions(self.context.artifacts)
        self.store.commit(
            step, result, self.context, input_fingerprint=input_fingerprint, binding=self.binding,
            provenance=(reused or {}).get('provenance'),
            artifact_versions=versions,
        )


def cleanup_conversation_checkpoints(conversation_id, user_id, authorize, *, message_container=None, conversation_container=None):
    """Explicit retention cleanup; no TTL or optional blob container is assumed."""
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
    for row in rows:
        if row['id'] in visited:
            continue
        visited.add(row['id'])
        if not run_store._is_run_record(row) or row.get('user_id') != user_id:
            continue
        for _ in range(8):
            current = read_revision_run(row['id'], user_id, conversation_id)
            try:
                _replace(current, {'checkpoints_deleted': True, 'execution_lease': None, 'recovery_blocked_code': 'context_unavailable'})
                break
            except exceptions.CosmosAccessConditionFailedError:
                continue
        else:
            raise CheckpointError()
        if current.get('latest_attempt_run_id') and current['latest_attempt_run_id'] not in visited:
            rows.append(read_revision_run(current['latest_attempt_run_id'], user_id, conversation_id))
        fence_publication(row, message_container)
        if current.get('checkpoint_version') == CHECKPOINT_VERSION:
            store = checkpoint_store(row, authorize)
            # initialize may have failed before creating the guard. A tombstone
            # still has to exist to prevent a delayed initializer from succeeding.
            try:
                store.container.create_item(body={
                    **store.identity, 'id': 'checkpoint:lifecycle',
                    'record_type': 'checkpoint_lifecycle', 'token': None, 'deleted': True,
                })
            except exceptions.CosmosResourceExistsError:
                pass
            store.delete_payloads()
