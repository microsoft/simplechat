# functions_orchestration_checkpoints.py
"""Private, immutable step-boundary checkpoints in the run-steps partition.

Version: 0.261.127
The lifecycle row fences every batch, including uncommitted chunks. It survives
cleanup, so an old worker cannot recreate payloads after conversation deletion.
"""

import base64
import hashlib
import json
import math
import uuid
from copy import deepcopy
from datetime import datetime

from azure.core import MatchConditions
from azure.cosmos import exceptions

from functions_orchestration_invocation_capture import OrchestrationInvocationControlError
from functions_orchestration_schema import build_failure, plan_contract_version, step_input_specs
from functions_orchestration_registry import build_planner_capability_projection, get_capability
from functions_orchestration_result_contracts import (
    ProducerIdentity, ResultContractError, ResultRef, TaskResult, digest as validate_result_digest,
)
from functions_orchestration_result_runtime import encode_step_result


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
# Absent/empty Analyze references must retain pre-Analyze checkpoint fingerprints.
OPTIONAL_STATE_FIELDS = ('saved_analyses',)
DEPENDENCY_STATE_FIELDS = (
    'plan_contract_version', 'task_results', 'result_aliases', 'pending_results', 'execution_deadline_at',
)
INPUT_FIELDS = (
    'user_message', 'user_message_id', 'resolved_message', 'answered_questions',
    'elicitation_references', 'selected_document_ids', 'original_seeds',
    'conversation_context', 'context_message_ids', 'allowed_user_urls',
    'chat_type', 'selection_mode', 'doc_scope', 'tags', 'document_filter_mode',
    'active_group_ids', 'active_group_id', 'active_public_workspace_ids',
    'gpt_model',
)


class CheckpointError(OrchestrationInvocationControlError):
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


def _execution_settings_fingerprint(settings):
    """The new-plan admission switch is not an input to already approved v2 work."""
    if isinstance(settings, dict):
        settings = {key: value for key, value in settings.items() if key != 'enable_chat_orchestration_harness'}
    return fingerprint(settings)


def _manifest_address(step_id, *, waiting=False, input_only=False):
    if waiting and input_only:
        raise CheckpointError('checkpoint_invalid')
    if input_only:
        prefix, kind = 'checkpoint-input', 'checkpoint_input_manifest'
    elif waiting:
        prefix, kind = 'checkpoint-wait', 'checkpoint_wait_manifest'
    else:
        prefix, kind = 'checkpoint', 'checkpoint_manifest'
    return f'{prefix}:{fingerprint(step_id)}', kind


def effective_plan(plan):
    values = [
        {key: deepcopy(step.get(key)) for key in (
            'step_id', 'capability_id', 'arguments', 'depends_on', 'enabled', 'optional',
        )}
        for step in plan.get('steps') or []
    ]
    if plan_contract_version(plan) == 2:
        for value, step in zip(values, plan.get('steps') or []):
            value.update({
                'plan_contract_version': 2,
                **{key: deepcopy(step.get(key)) for key in ('role', 'inputs', 'outputs')},
            })
    return values


def context_state(context):
    state = {key: deepcopy(getattr(context, key, None)) for key in STATE_FIELDS}
    for key in OPTIONAL_STATE_FIELDS:
        value = getattr(context, key, None)
        if value:
            state[key] = deepcopy(value)
    if getattr(context, 'plan_contract_version', 1) == 2:
        for key in ('evidence', 'citations', 'artifacts', 'notes', 'documents_touched', 'saved_analyses'):
            if key in state:
                state[key] = []
        state['step_documents'] = {}
        for key in ('execution_manifest', 'source_manifest'):
            state[key] = [
                {field: source[field] for field in (
                    'document_id', 'scope', 'scope_id', 'source_version', 'source_revision',
                    'content_sha256', 'authorization_status',
                ) if field in source}
                for source in state[key] or []
            ]
        state.update({
            'plan_contract_version': 2,
            'task_results': {name: task.to_dict() for name, task in context.task_results.items()},
            'result_aliases': {name: reference.to_dict() for name, reference in context.result_aliases.items()},
            'pending_results': deepcopy(context.pending_results),
            'execution_deadline_at': context.execution_deadline_at,
        })
    json_bytes(state)
    return state


def context_binding(context, plan, settings):
    """Hash runtime bindings; never persist identity, credentials or memory prompts."""
    dependency_contract = plan_contract_version(plan) == 2
    model = getattr(context, 'model_context', None) or {}
    inputs = {key: getattr(context, key, None) for key in INPUT_FIELDS}
    if getattr(context, 'analysis_result_contexts', None):
        inputs['analysis_result_contexts'] = context.analysis_result_contexts
    payload = {
        'plan': effective_plan(plan),
        'inputs': inputs,
        'model': {key: model.get(key) for key in ('model_id', 'endpoint_id', 'provider', 'model_deployment')},
        'memory_digest': fingerprint(getattr(context, 'memory_context', {}) or {}),
        'agent_catalog_digest': fingerprint(getattr(context, 'agent_catalog', []) or []),
        'action_catalog_digest': fingerprint(getattr(context, 'action_catalog', []) or []),
        'settings_digest': (
            _execution_settings_fingerprint(settings) if dependency_contract else fingerprint(settings)
        ),
    }
    if dependency_contract:
        payload.update({'plan_contract_version': 2, 'final_response': plan.get('final_response')})
    return fingerprint(payload)


def step_input_fingerprint(step, context, binding, *, settings=None):
    if getattr(context, 'plan_contract_version', 1) == 2:
        references = {}
        try:
            for spec in step_input_specs(step):
                if spec.binding.existing_result is not None:
                    reference = context.result_aliases[spec.binding.existing_result]
                else:
                    reference = context.task_results[spec.binding.step_id].output(spec.binding.output_name)
                references[spec.name] = reference.to_dict()
        except (KeyError, ResultContractError) as exc:
            raise CheckpointError('result_unavailable') from exc
        arguments = step.get('arguments') or {}
        document_ids = set(arguments.get('document_ids') or []) | set(arguments.get('right_document_ids') or [])
        if arguments.get('left_document_id'):
            document_ids.add(arguments['left_document_id'])
        if step['capability_id'] == 'document_search' and not document_ids:
            document_ids.update(context.selected_document_ids)
        model = getattr(context, 'model_context', None) or {}
        capability = get_capability(step['capability_id'], contract_version=2)
        capability_binding = {
            **build_planner_capability_projection([capability])[0], 'adapter': capability['adapter'],
        }
        return fingerprint({
            'plan_contract_version': 2,
            'step': effective_plan({'planner_contract_version': 2, 'steps': [step]})[0],
            'inputs': references,
            'request': {key: getattr(context, key, None) for key in INPUT_FIELDS},
            'model': {key: model.get(key) for key in ('model_id', 'endpoint_id', 'provider', 'model_deployment')},
            'memory_digest': fingerprint(getattr(context, 'memory_context', {}) or {}),
            'settings_digest': _execution_settings_fingerprint(settings or {}),
            'capability': {key: capability_binding.get(key) for key in (
                'id', 'plan_contract_version', 'result_contract_version', 'role', 'adapter', 'inputs',
                'result_input_kinds', 'result_outputs', 'optional_result_outputs',
                'result_output_kinds', 'partial_inputs_supported', 'max_per_plan',
            )},
            **({'native_output_variants': capability_binding['result_output_variants']}
               if 'result_output_variants' in capability_binding else {}),
            'output_profiles': {
                output['profile']: context.composition_profiles.get(output['profile'])
                for output in step['outputs'] if 'profile' in output
            },
            'capability_catalog': [
                entry for entry in (getattr(context, 'agent_catalog', None) or [])
                if step['capability_id'] == 'agent_invoke' and entry.get('name') == arguments.get('agent_name')
            ] + [
                entry for entry in (getattr(context, 'action_catalog', None) or [])
                if step['capability_id'] == 'action_invoke' and entry.get('action_ref') == arguments.get('action_ref')
            ],
            'sources': sorted(
                [
                    {key: source.get(key) for key in (
                        'document_id', 'scope', 'scope_id', 'source_version', 'source_revision', 'content_sha256',
                    )}
                    for source in getattr(context, 'execution_manifest', []) if source.get('document_id') in document_ids
                ],
                key=lambda source: source['document_id'],
            ),
        })
    # All accumulated context matters: action_invoke consumes earlier_findings even
    # without a declared dependency. Usage is attribution, not an adapter input.
    return fingerprint({'binding': binding, 'step': effective_plan({'steps': [step]})[0], 'context': context_state(context)})


def restore_context(context, payload):
    state = payload.get('state')
    dependency_contract = getattr(context, 'plan_contract_version', 1) == 2
    allowed = set(STATE_FIELDS) | set(OPTIONAL_STATE_FIELDS)
    if dependency_contract:
        allowed.update(DEPENDENCY_STATE_FIELDS)
    if (
        not isinstance(state, dict) or not set(STATE_FIELDS).issubset(state)
        or set(state) - allowed
        or (dependency_contract and state.get('plan_contract_version') != 2)
    ):
        raise CheckpointError('checkpoint_invalid')
    json_bytes(state)
    for key in STATE_FIELDS:
        if dependency_contract and key == 'artifacts':
            continue
        setattr(context, key, deepcopy(state[key]))
    for key in OPTIONAL_STATE_FIELDS:
        value = state.get(key, [])
        if not isinstance(value, list):
            raise CheckpointError('checkpoint_invalid')
        setattr(context, key, deepcopy(value))
    if dependency_contract:
        try:
            for field, descriptor_type in (('task_results', TaskResult), ('result_aliases', ResultRef)):
                values = state.get(field)
                if type(values) is not dict:
                    raise CheckpointError('checkpoint_invalid')
                restored = {name: descriptor_type.from_dict(value) for name, value in values.items()}
                current = getattr(context, field)
                if field == 'task_results' and any(name != value.producer.step_id for name, value in restored.items()):
                    raise CheckpointError('checkpoint_invalid')
                for name, value in restored.items():
                    if field == 'task_results' and name in getattr(context, '_failed_result_step_ids', ()):
                        continue
                    previous = current.get(name)
                    if previous is not None and previous != value:
                        if (
                            field != 'task_results' or previous.producer != value.producer
                            or previous.role != value.role
                        ):
                            raise CheckpointError('recovery_changed')
                        if value.status == 'pending' and not value.outputs and previous.status in ('complete', 'partial'):
                            continue
                        if not (
                            previous.status == 'pending' and not previous.outputs
                            and value.status in ('complete', 'partial')
                        ):
                            raise CheckpointError('recovery_changed')
                    current[name] = value
            if type(state.get('pending_results')) is not dict:
                raise CheckpointError('checkpoint_invalid')
            for step_id, wait in state['pending_results'].items():
                task = context.task_results.get(step_id)
                if (
                    (task is not None and task.status in ('complete', 'partial'))
                    or step_id in getattr(context, '_completed_result_step_ids', ())
                    or step_id in getattr(context, '_failed_result_step_ids', ())
                ):
                    continue
                if step_id in context.pending_results and context.pending_results[step_id] != wait:
                    current = context.pending_results[step_id]
                    if (
                        type(current) is dict and type(wait) is dict
                        and current.get('kind') == wait.get('kind') == 'orchestration_output'
                        and current.get('output_id') and current.get('output_id') == wait.get('output_id')
                        and all(
                            current[key] == wait[key]
                            for key in ('step_id', 'file_name', 'output_format', 'profile')
                            if key in current and key in wait
                        )
                    ):
                        continue
                    raise CheckpointError('recovery_changed')
                context.pending_results[step_id] = deepcopy(wait)
            for step_id, task in context.task_results.items():
                if task.status in ('complete', 'partial'):
                    context.pending_results.pop(step_id, None)
            saved_deadline = state.get('execution_deadline_at')
            if type(saved_deadline) is not str or datetime.fromisoformat(saved_deadline).tzinfo is None:
                raise CheckpointError('checkpoint_invalid')
            if context.execution_deadline_at is None:
                context.execution_deadline_at = saved_deadline
        except ResultContractError as exc:
            raise CheckpointError('checkpoint_invalid') from exc
        except ValueError as exc:
            raise CheckpointError('checkpoint_invalid') from exc


class CheckpointStore:
    def __init__(
        self, container, *, run_id, user_id, conversation_id, turn_id, authorize,
        token=None, claim_id=None, plan_contract_version=1,
    ):
        if type(plan_contract_version) is not int or plan_contract_version not in (1, 2):
            raise CheckpointError('checkpoint_invalid')
        self.container = container
        self.identity = {
            'run_id': run_id, 'user_id': user_id, 'conversation_id': conversation_id,
            'turn_id': turn_id, 'schema_version': CHECKPOINT_VERSION,
        }
        self.authorize = authorize
        self.token = token
        self.claim_id = claim_id
        self._storage_error_code = (
            'checkpoint_storage_unavailable' if plan_contract_version == 2 else 'checkpoint_unavailable'
        )

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
        except exceptions.CosmosResourceNotFoundError as exc:
            raise CheckpointError() from exc
        except Exception as exc:
            raise CheckpointError(self._storage_error_code) from exc

    def initialize(self):
        self._authorized()
        if not self.token:
            raise CheckpointError('ownership_lost')
        document = {
            **self.identity, 'id': LIFECYCLE_ID, 'record_type': 'checkpoint_lifecycle',
            'token': self.token, 'deleted': False,
            **({'claim_id': self.claim_id} if self.claim_id is not None else {}),
        }
        try:
            self.container.create_item(body=document)
        except exceptions.CosmosResourceExistsError:
            existing = self._read(LIFECYCLE_ID)
            if (
                existing.get('deleted') or existing.get('token') != self.token
                or existing.get('claim_id') != self.claim_id
            ):
                raise CheckpointError('ownership_lost') from None
        except Exception as exc:
            raise CheckpointError() from exc

    def adopt_claim(self, previous_claim_id):
        """Fence prior execution writers without changing the producer's lifecycle token."""
        if not self.token or not self.claim_id:
            raise CheckpointError('ownership_lost')
        for _ in range(8):
            self._authorized()
            guard = self._read(LIFECYCLE_ID)
            if guard.get('deleted') or guard.get('token') != self.token:
                raise CheckpointError('ownership_lost')
            if guard.get('claim_id') == self.claim_id:
                return
            if guard.get('claim_id') != previous_claim_id:
                raise CheckpointError('ownership_lost')
            replacement = {key: value for key, value in guard.items() if not key.startswith('_')}
            replacement['claim_id'] = self.claim_id
            try:
                self.container.replace_item(
                    item=LIFECYCLE_ID, body=replacement, etag=guard['_etag'],
                    match_condition=MatchConditions.IfNotModified,
                )
                self._authorized()
                return
            except exceptions.CosmosAccessConditionFailedError:
                continue
        raise CheckpointError('ownership_lost')

    def _write(self, document, *, immutable=True):
        self._authorized()
        document = {**document, **self.identity}
        if len(json_bytes(document)) > MAX_DOCUMENT_BYTES:
            raise CheckpointError('checkpoint_invalid')
        for _ in range(8):
            guard = self._read(LIFECYCLE_ID)
            if (
                guard.get('deleted') or guard.get('token') != self.token or not self.token
                or guard.get('claim_id') != self.claim_id
            ):
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
        dependency_contract = getattr(context, 'plan_contract_version', 1) == 2
        accepted = ('completed', 'partial', 'waiting') if dependency_contract else ('completed',)
        if result.get('status') not in accepted:
            raise CheckpointError('checkpoint_invalid')
        waiting = dependency_contract and result.get('status') == 'waiting'
        payload = {
            'schema_version': CHECKPOINT_VERSION, 'binding': binding,
            'input_fingerprint': input_fingerprint, 'step_id': step['step_id'],
            'result': encode_step_result(result, retained_only=True) if dependency_contract else deepcopy(result),
            'state': context_state(context),
            'usage': deepcopy(getattr(context, 'step_token_usage', {}) or {}),
            'provenance': provenance or {'run_id': self.identity['run_id'], 'step_id': step['step_id']},
            'artifact_versions': artifact_versions or {},
        }
        return self._commit_payload(step['step_id'], payload, waiting=waiting)

    def commit_input(self, step, context, *, input_fingerprint, binding):
        """Fence the exact producer/input state before starting v2 producer work."""
        if getattr(context, 'plan_contract_version', 1) != 2:
            raise CheckpointError('checkpoint_invalid')
        validate_result_digest(input_fingerprint)
        payload = {
            'schema_version': CHECKPOINT_VERSION, 'binding': binding,
            'input_fingerprint': input_fingerprint, 'step_id': step['step_id'],
            'result_producer': context.result_producer(step).to_dict(),
            'state': context_state(context),
            'provenance': {'run_id': self.identity['run_id'], 'step_id': step['step_id']},
        }
        return self._commit_payload(step['step_id'], payload, input_only=True)

    def _commit_payload(self, step_id, payload, *, waiting=False, input_only=False):
        raw = json_bytes(payload)
        if not raw or len(raw) > MAX_CHECKPOINT_BYTES:
            raise CheckpointError('checkpoint_invalid')
        digest = hashlib.sha256(raw).hexdigest()
        prefix, record_type = _manifest_address(step_id, waiting=waiting, input_only=input_only)
        chunks = [raw[offset:offset + CHUNK_BYTES] for offset in range(0, len(raw), CHUNK_BYTES)]
        if len(chunks) > MAX_CHUNKS:
            raise CheckpointError('checkpoint_invalid')
        for index, data in enumerate(chunks):
            self._write({
                'id': f'{prefix}:{digest}:{index}', 'record_type': 'checkpoint_chunk',
                'step_id': step_id, 'index': index, 'digest': digest,
                'data': base64.b64encode(data).decode('ascii'),
            })
        manifest = {
            'id': prefix, 'record_type': record_type, 'step_id': step_id,
            'digest': digest, 'bytes': len(raw), 'chunks': len(chunks),
            'binding': payload['binding'], 'input_fingerprint': payload['input_fingerprint'],
        }
        self._write(manifest, immutable=not waiting)
        return payload

    def load(self, step_id, *, waiting=False, input_only=False):
        guard = self._read(LIFECYCLE_ID)
        if guard.get('deleted'):
            raise CheckpointError('context_unavailable')
        prefix, record_type = _manifest_address(step_id, waiting=waiting, input_only=input_only)
        manifest = self._read(prefix)
        count, size, digest = manifest.get('chunks'), manifest.get('bytes'), manifest.get('digest')
        if (
            manifest.get('record_type') != record_type
            or manifest.get('step_id') != step_id
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
        dependency_contract = (payload.get('state') or {}).get('plan_contract_version') == 2
        accepted = ('waiting',) if waiting and dependency_contract else (
            ('completed', 'partial') if dependency_contract else ('completed',)
        )
        if (
            payload.get('schema_version') != CHECKPOINT_VERSION or payload.get('step_id') != step_id
            or payload.get('binding') != manifest.get('binding')
            or payload.get('input_fingerprint') != manifest.get('input_fingerprint')
            or (not input_only and (payload.get('result') or {}).get('status') not in accepted)
            or (waiting and not dependency_contract)
            or (input_only and not dependency_contract)
        ):
            raise CheckpointError('checkpoint_invalid')
        if input_only:
            try:
                producer = ProducerIdentity.from_dict(payload.get('result_producer'))
                validate_result_digest(payload['input_fingerprint'])
                if (
                    any(getattr(producer, key) != self.identity[key] for key in (
                        'user_id', 'conversation_id', 'run_id',
                    ))
                    or producer.step_id != step_id
                    or payload.get('provenance') != {'run_id': producer.run_id, 'step_id': step_id}
                ):
                    raise CheckpointError('checkpoint_invalid')
            except ResultContractError as exc:
                raise CheckpointError('checkpoint_invalid') from exc
        self._authorized()
        return payload

    def has_manifest(self, step_id, *, waiting=False, input_only=False):
        self._authorized()
        prefix, _ = _manifest_address(step_id, waiting=waiting, input_only=input_only)
        try:
            self.container.read_item(
                item=prefix,
                partition_key=self.identity['run_id'],
            )
            return True
        except exceptions.CosmosResourceNotFoundError:
            return False
        except Exception as exc:
            raise CheckpointError(self._storage_error_code) from exc

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
            query=(
                'SELECT * FROM c WHERE c.run_id = @partition_run AND c.turn_id = @turn_id'
            ),
            parameters=[
                {'name': '@partition_run', 'value': self.identity['run_id']},
                {'name': '@turn_id', 'value': self.identity['turn_id']},
            ],
            partition_key=self.identity['run_id'],
        ))
        for row in rows:
            # Native/result lifecycle fences share this partition but have their
            # own cleanup owner and must survive a checkpoint payload sweep.
            if row.get('id') == LIFECYCLE_ID or row.get('record_type') not in {
                'step', 'checkpoint_chunk', 'checkpoint_manifest',
                'checkpoint_wait_manifest', 'checkpoint_input_manifest',
            }:
                continue
            self._verify(row)
            self.container.delete_item(
                item=row['id'], partition_key=self.identity['run_id'],
                etag=row['_etag'], match_condition=MatchConditions.IfNotModified,
            )
