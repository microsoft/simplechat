# functions_orchestration_checkpoints.py
"""Private, immutable step-boundary checkpoints in the run-steps partition.

Version: 0.261.105
The lifecycle row fences every batch, including uncommitted chunks. It survives
cleanup, so an old worker cannot recreate payloads after conversation deletion.
"""

import base64
import hashlib
import json
import math
import uuid
from copy import deepcopy

from azure.core import MatchConditions
from azure.cosmos import exceptions

from functions_orchestration_schema import build_failure


CHECKPOINT_VERSION = 1
CHUNK_BYTES = 128 * 1024
MAX_DOCUMENT_BYTES = 256 * 1024
MAX_CHECKPOINT_BYTES = 8 * 1024 * 1024
MAX_CHUNKS = 64
LIFECYCLE_ID = 'checkpoint:lifecycle'
STATE_FIELDS = (
    'evidence', 'citations', 'artifacts', 'notes', 'documents_touched',
    'step_documents', 'execution_manifest', 'source_manifest',
)
INPUT_FIELDS = (
    'user_message', 'user_message_id', 'resolved_message', 'answered_questions',
    'elicitation_references', 'selected_document_ids', 'original_seeds',
    'conversation_context', 'context_message_ids', 'allowed_user_urls',
    'chat_type', 'selection_mode', 'doc_scope', 'tags', 'document_filter_mode',
    'active_group_ids', 'active_group_id', 'active_public_workspace_ids',
    'gpt_model',
)


class CheckpointError(RuntimeError):
    def __init__(self, code='checkpoint_unavailable'):
        self.failure = build_failure(code)
        self.code = self.failure['code']
        super().__init__(self.failure['message'])


def _check_json(value, depth=0):
    if depth > 64:
        raise CheckpointError('checkpoint_invalid')
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _check_json(item, depth + 1)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _check_json(item, depth + 1)
        return
    raise CheckpointError('checkpoint_invalid')


def json_bytes(value):
    _check_json(value)
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, UnicodeError, TypeError) as exc:
        raise CheckpointError('checkpoint_invalid') from exc


def fingerprint(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def effective_plan(plan):
    return [
        {key: deepcopy(step.get(key)) for key in (
            'step_id', 'capability_id', 'arguments', 'depends_on', 'enabled', 'optional',
        )}
        for step in plan.get('steps') or []
    ]


def context_state(context):
    state = {key: deepcopy(getattr(context, key, None)) for key in STATE_FIELDS}
    json_bytes(state)
    return state


def context_binding(context, plan, settings):
    """Hash runtime bindings; never persist identity, credentials or memory prompts."""
    model = getattr(context, 'model_context', None) or {}
    return fingerprint({
        'plan': effective_plan(plan),
        'inputs': {key: getattr(context, key, None) for key in INPUT_FIELDS},
        'model': {key: model.get(key) for key in ('model_id', 'endpoint_id', 'provider', 'model_deployment')},
        'memory_digest': fingerprint(getattr(context, 'memory_context', {}) or {}),
        'agent_catalog_digest': fingerprint(getattr(context, 'agent_catalog', []) or []),
        'action_catalog_digest': fingerprint(getattr(context, 'action_catalog', []) or []),
        'settings_digest': fingerprint(settings),
    })


def step_input_fingerprint(step, context, binding):
    # All accumulated context matters: action_invoke consumes earlier_findings even
    # without a declared dependency. Usage is attribution, not an adapter input.
    return fingerprint({'binding': binding, 'step': effective_plan({'steps': [step]})[0], 'context': context_state(context)})


def restore_context(context, payload):
    state = payload.get('state')
    if not isinstance(state, dict) or set(state) != set(STATE_FIELDS):
        raise CheckpointError('checkpoint_invalid')
    json_bytes(state)
    for key in STATE_FIELDS:
        setattr(context, key, deepcopy(state[key]))


class CheckpointStore:
    def __init__(self, container, *, run_id, user_id, conversation_id, turn_id, authorize, token=None):
        self.container = container
        self.identity = {
            'run_id': run_id, 'user_id': user_id, 'conversation_id': conversation_id,
            'turn_id': turn_id, 'schema_version': CHECKPOINT_VERSION,
        }
        self.authorize = authorize
        self.token = token

    def _authorized(self):
        if not callable(self.authorize) or self.authorize() is False:
            raise CheckpointError('context_unavailable')

    def _verify(self, document):
        if not isinstance(document, dict) or any(document.get(key) != value for key, value in self.identity.items()):
            raise CheckpointError('checkpoint_invalid')
        return document

    def _read(self, item_id):
        self._authorized()
        try:
            return self._verify(self.container.read_item(item=item_id, partition_key=self.identity['run_id']))
        except CheckpointError:
            raise
        except Exception as exc:
            raise CheckpointError() from exc

    def initialize(self):
        self._authorized()
        if not self.token:
            raise CheckpointError('ownership_lost')
        document = {**self.identity, 'id': LIFECYCLE_ID, 'record_type': 'checkpoint_lifecycle', 'token': self.token, 'deleted': False}
        try:
            self.container.create_item(body=document)
        except exceptions.CosmosResourceExistsError:
            existing = self._read(LIFECYCLE_ID)
            if existing.get('deleted') or existing.get('token') != self.token:
                raise CheckpointError('ownership_lost') from None
        except Exception as exc:
            raise CheckpointError() from exc

    def _write(self, document, *, immutable=True):
        self._authorized()
        document = {**document, **self.identity}
        if len(json_bytes(document)) > MAX_DOCUMENT_BYTES:
            raise CheckpointError('checkpoint_invalid')
        for _ in range(8):
            guard = self._read(LIFECYCLE_ID)
            if guard.get('deleted') or guard.get('token') != self.token or not self.token:
                raise CheckpointError('ownership_lost')
            replacement = {key: value for key, value in guard.items() if not key.startswith('_')}
            replacement['write_id'] = uuid.uuid4().hex
            operations = [
                ('replace', (LIFECYCLE_ID, replacement), {'if_match_etag': guard['_etag']}),
                ('create' if immutable else 'upsert', (document,)),
            ]
            try:
                self.container.execute_item_batch(batch_operations=operations, partition_key=self.identity['run_id'])
                return
            except (exceptions.CosmosBatchOperationError, exceptions.CosmosHttpResponseError) as exc:
                if exc.status_code == 412:
                    continue
                if immutable and exc.status_code == 409:
                    saved = self._read(document['id'])
                    if all(saved.get(key) == value for key, value in document.items()):
                        return
                raise CheckpointError() from exc
            except Exception as exc:
                raise CheckpointError() from exc
        raise CheckpointError()

    def save_step(self, record):
        self._write({
            **deepcopy(record), 'id': f"{self.identity['run_id']}:{record['step_id']}",
            'record_type': 'step',
        }, immutable=False)

    def commit(self, step, result, context, *, input_fingerprint, binding, provenance=None, artifact_versions=None):
        if result.get('status') != 'completed':
            raise CheckpointError('checkpoint_invalid')
        payload = {
            'schema_version': CHECKPOINT_VERSION, 'binding': binding,
            'input_fingerprint': input_fingerprint, 'step_id': step['step_id'],
            'result': deepcopy(result), 'state': context_state(context),
            'usage': deepcopy(getattr(context, 'step_token_usage', {}) or {}),
            'provenance': provenance or {'run_id': self.identity['run_id'], 'step_id': step['step_id']},
            'artifact_versions': artifact_versions or {},
        }
        raw = json_bytes(payload)
        if not raw or len(raw) > MAX_CHECKPOINT_BYTES:
            raise CheckpointError('checkpoint_invalid')
        digest = hashlib.sha256(raw).hexdigest()
        prefix = f"checkpoint:{fingerprint(step['step_id'])}"
        chunks = [raw[offset:offset + CHUNK_BYTES] for offset in range(0, len(raw), CHUNK_BYTES)]
        if len(chunks) > MAX_CHUNKS:
            raise CheckpointError('checkpoint_invalid')
        for index, data in enumerate(chunks):
            self._write({
                'id': f'{prefix}:{digest}:{index}', 'record_type': 'checkpoint_chunk',
                'step_id': step['step_id'], 'index': index, 'digest': digest,
                'data': base64.b64encode(data).decode('ascii'),
            })
        manifest = {
            'id': prefix, 'record_type': 'checkpoint_manifest', 'step_id': step['step_id'],
            'digest': digest, 'bytes': len(raw), 'chunks': len(chunks),
            'binding': binding, 'input_fingerprint': input_fingerprint,
        }
        self._write(manifest)
        return payload

    def load(self, step_id):
        guard = self._read(LIFECYCLE_ID)
        if guard.get('deleted'):
            raise CheckpointError('context_unavailable')
        prefix = f'checkpoint:{fingerprint(step_id)}'
        manifest = self._read(prefix)
        count, size, digest = manifest.get('chunks'), manifest.get('bytes'), manifest.get('digest')
        if (
            manifest.get('record_type') != 'checkpoint_manifest' or manifest.get('step_id') != step_id
            or type(count) is not int or not 1 <= count <= MAX_CHUNKS
            or type(size) is not int or not 1 <= size <= MAX_CHECKPOINT_BYTES
            or not isinstance(digest, str) or len(digest) != 64
        ):
            raise CheckpointError('checkpoint_invalid')
        parts = []
        for index in range(count):
            chunk = self._read(f'{prefix}:{digest}:{index}')
            if (
                chunk.get('record_type') != 'checkpoint_chunk' or chunk.get('index') != index
                or chunk.get('step_id') != step_id or chunk.get('digest') != digest
                or len(json_bytes(chunk)) > MAX_DOCUMENT_BYTES
            ):
                raise CheckpointError('checkpoint_invalid')
            try:
                part = base64.b64decode(chunk['data'], validate=True)
            except (KeyError, ValueError, TypeError) as exc:
                raise CheckpointError('checkpoint_invalid') from exc
            if not part or len(part) > CHUNK_BYTES:
                raise CheckpointError('checkpoint_invalid')
            parts.append(part)
        raw = b''.join(parts)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise CheckpointError('checkpoint_invalid')
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise CheckpointError('checkpoint_invalid') from exc
        if (
            payload.get('schema_version') != CHECKPOINT_VERSION or payload.get('step_id') != step_id
            or payload.get('binding') != manifest.get('binding')
            or payload.get('input_fingerprint') != manifest.get('input_fingerprint')
            or (payload.get('result') or {}).get('status') != 'completed'
        ):
            raise CheckpointError('checkpoint_invalid')
        self._authorized()
        return payload

    def has_manifest(self, step_id):
        self._authorized()
        try:
            self.container.read_item(
                item=f'checkpoint:{fingerprint(step_id)}', partition_key=self.identity['run_id'],
            )
            return True
        except exceptions.CosmosResourceNotFoundError:
            return False
        except Exception as exc:
            raise CheckpointError('checkpoint_unavailable') from exc

    def fence(self, *, deleted=False, allow_missing=False):
        """Revoke the partition writer before recovery publication or cleanup."""
        for _ in range(8):
            self._authorized()
            try:
                guard = self._verify(self.container.read_item(
                    item=LIFECYCLE_ID, partition_key=self.identity['run_id'],
                ))
            except exceptions.CosmosResourceNotFoundError:
                if not allow_missing:
                    raise CheckpointError('checkpoint_unavailable') from None
                try:
                    self.container.create_item(body={
                        **self.identity, 'id': LIFECYCLE_ID, 'record_type': 'checkpoint_lifecycle',
                        'token': None, 'deleted': deleted,
                    })
                    return
                except exceptions.CosmosResourceExistsError:
                    continue
                except Exception as exc:
                    raise CheckpointError('checkpoint_unavailable') from exc
            except CheckpointError:
                raise
            except Exception as exc:
                raise CheckpointError('checkpoint_unavailable') from exc
            replacement = {key: value for key, value in guard.items() if not key.startswith('_')}
            replacement.update({'token': None, 'deleted': deleted or guard.get('deleted', False)})
            try:
                self.container.replace_item(
                    item=LIFECYCLE_ID, body=replacement, etag=guard['_etag'],
                    match_condition=MatchConditions.IfNotModified,
                )
                return
            except exceptions.CosmosAccessConditionFailedError:
                continue
        raise CheckpointError()

    def delete_payloads(self):
        self.fence(deleted=True)
        rows = list(self.container.query_items(
            query='SELECT * FROM c WHERE c.run_id = @partition_run',
            parameters=[{'name': '@partition_run', 'value': self.identity['run_id']}],
            partition_key=self.identity['run_id'],
        ))
        for row in rows:
            if row.get('id') == LIFECYCLE_ID:
                continue
            self._verify(row)
            self.container.delete_item(
                item=row['id'], partition_key=self.identity['run_id'],
                etag=row['_etag'], match_condition=MatchConditions.IfNotModified,
            )
