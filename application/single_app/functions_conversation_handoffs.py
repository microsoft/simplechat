# functions_conversation_handoffs.py
"""Durable private-conversation FIFO and shared execution admission (issue #1835).

This module is bootstrap-free. The runtime supplies initialized storage and policy
callbacks. A destination control document and each enqueue are updated atomically.
Expired executing leases are uncertain, never permission to repeat a model call.
"""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import threading
import time
import uuid

from azure.core import MatchConditions
from azure.cosmos import exceptions

from cosmos_document_utils import normalize_cosmos_document


CONTROL_ID = 'destination-admission'
LEASE_SECONDS = 180
MAX_QUEUE = 32
MAX_INSTRUCTION_CHARS = 12000
TERMINAL = frozenset({'completed', 'failed', 'cancelled'})


class ConversationHandoffError(ValueError):
    def __init__(self, code, public_message, status_code=409):
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
        self.status_code = status_code


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(c in value for c in '/\\?#'):
        raise ConversationHandoffError('invalid_request', 'A valid conversation or request identifier is required.', 400)
    return value.strip()


@dataclass
class DestinationLease:
    store: object
    conversation_id: str
    user_id: str
    owner_id: str
    token: str
    stop: object = field(default_factory=threading.Event)
    lost: object = field(default_factory=threading.Event)
    thread: object = None

    def start(self):
        def renew():
            while not self.stop.wait(LEASE_SECONDS / 3):
                try:
                    self.store.heartbeat(self)
                except Exception:
                    self.lost.set()
                    return
        self.thread = threading.Thread(target=renew, daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)
        if not self.lost.is_set():
            self.store.release(self)

    def assert_owned(self):
        if self.lost.is_set():
            raise ConversationHandoffError('lease_lost', 'Execution ownership changed. Do not repeat this request.')
        self.store.assert_lease(self)


class ConversationHandoffStore:
    def __init__(self, container, *, clock=time.time):
        self.container = container
        self.clock = clock

    def read(self, destination_id, item_id):
        try:
            return normalize_cosmos_document(self.container.read_item(item=item_id, partition_key=destination_id))
        except exceptions.CosmosResourceNotFoundError:
            return None

    def control(self, destination_id):
        current = self.read(destination_id, CONTROL_ID)
        if current is not None:
            return current
        body = {'id': CONTROL_ID, 'destination_conversation_id': destination_id,
                'kind': 'admission', 'queue': [], 'sequence': 0, 'active': None}
        try:
            return normalize_cosmos_document(self.container.create_item(body=body))
        except exceptions.CosmosResourceExistsError:
            return self.read(destination_id, CONTROL_ID)

    def replace(self, document):
        if not document.get('_etag'):
            raise ConversationHandoffError('storage_unavailable', 'Execution state could not be safely updated.', 503)
        return normalize_cosmos_document(self.container.replace_item(
            item=document['id'], body=document, etag=document['_etag'],
            match_condition=MatchConditions.IfNotModified,
        ))

    def enqueue(self, document):
        destination = document['destination_conversation_id']
        for _ in range(12):
            existing = self.read(destination, document['id'])
            if existing is not None:
                if existing.get('fingerprint') != document['fingerprint'] or existing.get('user_id') != document['user_id']:
                    raise ConversationHandoffError('request_conflict', 'This request identifier was already used for a different send.')
                return existing
            control = self.control(destination)
            if len(control['queue']) >= MAX_QUEUE:
                raise ConversationHandoffError('queue_full', 'This conversation has too many queued tasks. Wait or cancel a queued task.', 429)
            control['sequence'] += 1
            control['queue'].append(document['id'])
            candidate = {**document, 'sequence': control['sequence']}
            try:
                self.container.execute_item_batch(batch_operations=[
                    ('replace', (CONTROL_ID, control), {'if_match_etag': control['_etag']}),
                    ('create', (candidate,)),
                ], partition_key=destination)
                return self.read(destination, document['id'])
            except exceptions.CosmosHttpResponseError as error:
                status = getattr(error, 'status_code', None)
                operations = getattr(error, 'operation_responses', []) or []
                if status not in (409, 412, 424) and not any(r.get('statusCode') in (409, 412) for r in operations):
                    raise
        raise ConversationHandoffError('destination_busy', 'The conversation queue changed. Please retry.')

    def acquire(self, user_id, destination_id, owner_id, *, kind='chat'):
        for _ in range(12):
            control = self.control(destination_id)
            active = control.get('active')
            if active:
                code = 'destination_needs_attention' if active['expires_at'] <= self.clock() else 'destination_busy'
                raise ConversationHandoffError(code, 'This conversation already has active work. Wait for it to finish; interrupted work must be reviewed first.')
            if control['queue'] and (kind != 'handoff' or control['queue'][0] != owner_id):
                raise ConversationHandoffError('destination_busy', 'Queued tasks will run first. Wait for this conversation to become available.')
            token = uuid.uuid4().hex
            control['active'] = {'owner_id': owner_id, 'user_id': user_id, 'kind': kind,
                                 'token': token, 'expires_at': self.clock() + LEASE_SECONDS}
            try:
                self.replace(control)
                return DestinationLease(self, destination_id, user_id, owner_id, token)
            except exceptions.CosmosHttpResponseError as error:
                if error.status_code != 412:
                    raise
        raise ConversationHandoffError('destination_busy', 'This conversation is busy. Please wait.')

    def assert_lease(self, lease):
        control = self.control(lease.conversation_id)
        active = control.get('active') or {}
        if active.get('token') != lease.token or active.get('expires_at', 0) <= self.clock():
            raise ConversationHandoffError('lease_lost', 'Execution ownership expired. Review the task before continuing.')
        return control

    def heartbeat(self, lease):
        for _ in range(12):
            control = self.assert_lease(lease)
            control['active']['expires_at'] = self.clock() + LEASE_SECONDS
            try:
                self.replace(control)
                return
            except exceptions.CosmosHttpResponseError as error:
                if error.status_code != 412:
                    raise
        raise ConversationHandoffError('lease_lost', 'Could not renew execution ownership.')

    def release(self, lease):
        for _ in range(12):
            control = self.control(lease.conversation_id)
            if (control.get('active') or {}).get('token') != lease.token:
                return
            control['active'] = None
            if control['queue'] and control['queue'][0] == lease.owner_id:
                job = self.read(lease.conversation_id, lease.owner_id)
                if job and job['status'] in TERMINAL:
                    control['queue'].pop(0)
                elif job and job['status'] == 'needs_attention':
                    # An uncertain external effect must block subsequent destination work.
                    return
            try:
                self.replace(control)
                return
            except exceptions.CosmosHttpResponseError as error:
                if error.status_code != 412:
                    raise

    def update_job(self, destination_id, job_id, mutate, *, lease=None):
        for _ in range(12):
            if lease:
                lease.assert_owned()
            job = self.read(destination_id, job_id)
            if job is None:
                raise ConversationHandoffError('handoff_unavailable', 'This task is unavailable.', 404)
            mutate(job)
            job['updated_at'] = self.clock()
            try:
                return self.replace(job)
            except exceptions.CosmosHttpResponseError as error:
                if error.status_code != 412:
                    raise
        raise ConversationHandoffError('state_conflict', 'Task state changed. Reload before continuing.')

    def prune_terminal_head(self, destination_id):
        for _ in range(12):
            control = self.control(destination_id)
            if control.get('active') or not control['queue']:
                return
            job = self.read(destination_id, control['queue'][0])
            if job is None or job['status'] not in TERMINAL:
                return
            control['queue'].pop(0)
            try:
                self.replace(control)
            except exceptions.CosmosHttpResponseError as error:
                if error.status_code != 412:
                    raise


class ConversationHandoffService:
    def __init__(self, store, *, authorize, normalize_references, resolve_references,
                 resolve_destination, generate, validate_approval, mark_unread):
        self.store = store
        self.authorize = authorize
        self.normalize_references = normalize_references
        self.resolve_references = resolve_references
        self.resolve_destination = resolve_destination
        self.generate = generate
        self.validate_approval = validate_approval
        self.mark_unread = mark_unread

    def validate(self, job):
        user_id = job['user_id']
        self.authorize(user_id, job['source_conversation_id'])
        self.authorize(user_id, job['destination_conversation_id'])
        for ref in job['conversation_references']:
            self.authorize(user_id, ref['id'])
        if job.get('approval') is not None and not self.validate_approval(job):
            raise ConversationHandoffError('approval_required', 'The approved send scope changed. Review and approve the destination and task again.')

    def enqueue(self, user_id, source_id, destination_id, instruction, *, references=None,
                request_id=None, approval=None, origin=None, destination_config_revision=None):
        user_id, source_id, destination_id = map(identifier, (user_id, source_id, destination_id))
        if source_id == destination_id:
            raise ConversationHandoffError('handoff_cycle', 'Choose a different destination conversation.', 400)
        if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > MAX_INSTRUCTION_CHARS:
            raise ConversationHandoffError('invalid_instruction', 'Provide a task instruction of at most 12,000 characters.', 400)
        origin = deepcopy(origin) if origin is not None else None
        if origin is not None:
            if not isinstance(origin, dict) or approval is None:
                raise ConversationHandoffError('approval_required', 'Automated sends need an approved execution scope.')
            visited = origin.get('visited_conversation_ids', [source_id])
            if not isinstance(visited, list) or destination_id in visited or origin.get('hop_count', 0) != 0:
                raise ConversationHandoffError('handoff_cycle', 'This send would exceed the approved one-hop boundary.', 400)
        normalized = self.normalize_references(references if references is not None else [{'kind': 'conversation', 'id': source_id}])
        if any(ref['id'] == destination_id for ref in normalized):
            raise ConversationHandoffError('handoff_cycle', 'A destination cannot reference itself as an external source.', 400)
        key = identifier(request_id) if request_id is not None else uuid.uuid4().hex
        request = {'user_id': user_id, 'source_conversation_id': source_id,
                   'destination_conversation_id': destination_id, 'instruction': instruction.strip(),
                   'conversation_references': normalized, 'approval': deepcopy(approval), 'origin': origin}
        self.validate(request)
        existing_id = 'handoff-' + digest([user_id, destination_id, key])
        fingerprint = digest(request)
        existing = self.store.read(destination_id, existing_id)
        if existing is not None:
            if existing.get('fingerprint') != fingerprint:
                raise ConversationHandoffError('request_conflict', 'This request identifier was already used for a different send.')
            return existing
        config = self.resolve_destination(user_id, destination_id)
        if destination_config_revision is not None and destination_config_revision != config['revision']:
            raise ConversationHandoffError('destination_configuration_changed', 'The destination model changed. Review the destination again.')
        self.resolve_references(user_id, normalized, query=instruction, destination_id=destination_id)
        now = self.store.clock()
        return self.store.enqueue({**request, 'id': existing_id, 'kind': 'handoff', 'request_id': key,
                                   'fingerprint': fingerprint, 'status': 'queued', 'created_at': now,
                                   'updated_at': now, 'destination_config': config, 'attempt': 0,
                                   'destination_user_message_id': existing_id + '-user',
                                   'destination_message_id': existing_id + '-assistant'})

    def get(self, user_id, destination_id, job_id):
        self.authorize(user_id, identifier(destination_id))
        job = self.store.read(destination_id, identifier(job_id))
        if job is None or job.get('kind') != 'handoff' or job.get('user_id') != user_id:
            raise ConversationHandoffError('handoff_unavailable', 'This task is unavailable.', 404)
        self.validate(job)
        return job

    def list(self, user_id, conversation_id):
        self.authorize(user_id, identifier(conversation_id))
        rows = self.store.container.query_items(
            query='SELECT TOP 100 * FROM c WHERE c.kind = @kind AND c.user_id = @user AND (c.source_conversation_id = @conversation OR c.destination_conversation_id = @conversation) ORDER BY c.created_at DESC',
            parameters=[{'name': '@kind', 'value': 'handoff'}, {'name': '@user', 'value': user_id},
                        {'name': '@conversation', 'value': conversation_id}], enable_cross_partition_query=True,
        )
        results = []
        for row in rows:
            try:
                self.authorize(user_id, row['source_conversation_id'])
                self.authorize(user_id, row['destination_conversation_id'])
            except (ValueError, PermissionError, LookupError):
                continue
            results.append(row)
        return results

    def cancel(self, user_id, destination_id, job_id):
        self.get(user_id, destination_id, job_id)
        def mutate(job):
            if job['status'] in TERMINAL:
                return
            if job['status'] == 'needs_attention':
                raise ConversationHandoffError('uncertain_execution', 'Execution may have had effects. Review the destination before resolving this task.')
            job['cancel_requested'] = True
            if job['status'] == 'queued':
                job['status'] = 'cancelled'
        job = self.store.update_job(destination_id, job_id, mutate)
        self.store.prune_terminal_head(destination_id)
        return job

    def dispatch(self, destination_id):
        self.store.prune_terminal_head(destination_id)
        control = self.store.control(destination_id)
        active = control.get('active')
        if active:
            if active['expires_at'] <= self.store.clock() and active['kind'] == 'handoff':
                def uncertain(job):
                    if job['status'] not in TERMINAL:
                        job.update(status='needs_attention', error='Execution was interrupted. Its effects are uncertain; it was not repeated.')
                self.store.update_job(destination_id, active['owner_id'], uncertain)
            return None
        if not control['queue']:
            return None
        job = self.store.read(destination_id, control['queue'][0])
        try:
            lease = self.store.acquire(job['user_id'], destination_id, job['id'], kind='handoff').start()
        except ConversationHandoffError as error:
            if error.code == 'destination_busy':
                return None
            raise
        invoked = False
        try:
            def start(current):
                if current['status'] != 'queued' or current.get('cancel_requested'):
                    raise ConversationHandoffError('cancelled', 'This task was cancelled.')
                current.update(status='starting', attempt=current['attempt'] + 1)
            job = self.store.update_job(destination_id, job['id'], start, lease=lease)
            self.validate(job)
            config = self.resolve_destination(job['user_id'], destination_id)
            if config['revision'] != job['destination_config']['revision']:
                raise ConversationHandoffError('destination_configuration_changed', 'The destination model changed. Review and send a new task.')
            evidence = self.resolve_references(job['user_id'], job['conversation_references'], query=job['instruction'], destination_id=destination_id)
            def running(current):
                if current.get('cancel_requested'):
                    raise ConversationHandoffError('cancelled', 'This task was cancelled.')
                current.update(status='running', reference_revision=evidence.get('revision'))
            job = self.store.update_job(destination_id, job['id'], running, lease=lease)
            def before_effect():
                lease.assert_owned()
                self.validate(job)
                current = self.store.read(destination_id, job['id'])
                if current.get('cancel_requested'):
                    raise ConversationHandoffError('cancelled', 'This task was cancelled.')
                fresh = self.resolve_references(job['user_id'], job['conversation_references'], query=job['instruction'], destination_id=destination_id)
                if fresh.get('revision') != evidence.get('revision'):
                    raise ConversationHandoffError('source_changed', 'Source context changed. Review and send a new task.')
            before_effect()
            invoked = True
            self.generate(job, evidence, before_effect)
            lease.assert_owned()
            self.mark_unread(job)
            job = self.store.update_job(destination_id, job['id'], lambda current: current.update(status='completed'), lease=lease)
            return job
        except Exception as error:
            code = getattr(error, 'code', None)
            safe = getattr(error, 'public_message', 'Task execution failed. Review the destination before sending again.')
            def fail(current):
                if current['status'] in TERMINAL:
                    return
                status = 'cancelled' if code == 'cancelled' else ('needs_attention' if invoked else 'failed')
                current.update(status=status, error=safe, error_code=code or 'execution_failed')
            if not lease.lost.is_set():
                try:
                    active_token = (self.store.control(destination_id).get('active') or {}).get('token')
                    check_lease = None if (code == 'lease_lost' and active_token == lease.token) else lease
                    job = self.store.update_job(destination_id, job['id'], fail, lease=check_lease)
                except ConversationHandoffError:
                    lease.lost.set()
            return job
        finally:
            lease.close()


@contextmanager
def held_destination(store, user_id, conversation_id, owner_id, *, kind='chat'):
    lease = store.acquire(user_id, conversation_id, owner_id, kind=kind).start()
    try:
        yield lease
    finally:
        lease.close()


def public_handoff(job):
    fields = ('id', 'source_conversation_id', 'destination_conversation_id', 'instruction',
              'status', 'error', 'error_code', 'created_at', 'updated_at', 'sequence',
              'destination_user_message_id', 'destination_message_id', 'conversation_references',
              'cancel_requested', 'destination_config')
    return {key: deepcopy(job[key]) for key in fields if key in job}
