# orchestration_revisions.py
"""
In-memory Cosmos boundary for conditional orchestration revision tests.

Version: 0.261.102
Implemented in: 0.261.102

Batch operations are formatted by the installed SDK and applied to a copy. A failed
operation never makes preceding operations visible. Hooks permit deterministic races.
"""

import re
from copy import deepcopy
from threading import RLock

from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos import _base, exceptions


class AtomicMemoryContainer:
    def __init__(self, partition_field):
        self.partition_field = partition_field
        self.items = {}
        self.queries = []
        self.sequence = 0
        self.fail_reads = False
        self.fail_queries = False
        self.fail_writes = False
        self.fail_batch_at = None
        self.before_replace = None
        self.before_batch = None
        self.after_batch = None
        self.batch_calls = []
        self._lock = RLock()

    def _hook(self, name):
        callback = getattr(self, name)
        if callback:
            setattr(self, name, None)
            callback()

    def _save(self, body):
        if self.fail_writes:
            raise AzureError('Private test storage failure')
        self.sequence += 1
        saved = {**deepcopy(body), '_etag': str(self.sequence)}
        self.items[(body[self.partition_field], body['id'])] = saved
        return deepcopy(saved)

    def upsert_item(self, body):
        with self._lock:
            return self._save(body)

    def create_item(self, body):
        with self._lock:
            if (body[self.partition_field], body['id']) in self.items:
                raise exceptions.CosmosResourceExistsError(status_code=409, message='Test record exists')
            return self._save(body)

    def read_item(self, item, partition_key):
        with self._lock:
            if self.fail_reads:
                raise AzureError('Private test read failure')
            record = self.items.get((partition_key, item))
            if record is None:
                raise exceptions.CosmosResourceNotFoundError(status_code=404, message='Test record not found')
            return deepcopy(record)

    def replace_item(self, item, body, **kwargs):
        self._hook('before_replace')
        with self._lock:
            existing = self.read_item(item, body[self.partition_field])
            if (
                kwargs.get('match_condition') != MatchConditions.IfNotModified
                or kwargs.get('etag') != existing['_etag']
            ):
                raise exceptions.CosmosAccessConditionFailedError(status_code=412, message='Test version changed')
            if item != body['id']:
                raise ValueError('Replacement changed identity')
            return self._save(body)

    def delete_item(self, item, partition_key, **kwargs):
        with self._lock:
            existing = self.read_item(item, partition_key)
            if kwargs.get('etag') != existing['_etag']:
                raise exceptions.CosmosAccessConditionFailedError(status_code=412, message='Test version changed')
            del self.items[(partition_key, item)]

    def execute_item_batch(self, batch_operations, partition_key, **kwargs):
        self._hook('before_batch')
        operations = _base._format_batch_operations(deepcopy(batch_operations))
        self.batch_calls.append(deepcopy(operations))
        with self._lock:
            if self.fail_writes:
                raise AzureError('Private test batch failure')
            working = deepcopy(self.items)
            sequence = self.sequence
            responses = []
            for index, operation in enumerate(operations):
                if index == self.fail_batch_at:
                    raise exceptions.CosmosBatchOperationError(
                        error_index=index, headers={}, status_code=503,
                        message='Private injected batch failure', operation_responses=[],
                    )
                body = operation.get('resourceBody')
                item_id = operation.get('id') or (body or {}).get('id')
                key = (partition_key, item_id)
                existing = working.get(key)
                kind = operation['operationType']
                status = 200
                if kind == 'Create' and existing is not None:
                    status = 409
                elif kind in ('Replace', 'Read', 'Delete') and existing is None:
                    status = 404
                elif operation.get('ifMatch') is not None and (
                    existing is None or existing['_etag'] != operation['ifMatch']
                ):
                    status = 412
                elif body is not None and (
                    body.get(self.partition_field) != partition_key or body.get('id') != item_id
                ):
                    status = 400
                if status >= 400:
                    raise exceptions.CosmosBatchOperationError(
                        error_index=index, headers={}, status_code=status,
                        message='Private conditional batch failure',
                        operation_responses=[
                            {'statusCode': status if position == index else 424}
                            for position in range(len(operations))
                        ],
                    )
                if kind in ('Create', 'Replace', 'Upsert'):
                    sequence += 1
                    working[key] = {**deepcopy(body), '_etag': str(sequence)}
                    responses.append({
                        'statusCode': 201 if kind == 'Create' else 200,
                        'resourceBody': deepcopy(working[key]),
                        'eTag': str(sequence),
                    })
                elif kind == 'Read':
                    responses.append({'statusCode': 200, 'resourceBody': deepcopy(existing)})
                elif kind == 'Delete':
                    del working[key]
                    responses.append({'statusCode': 204})
                else:
                    raise AssertionError(f'Unsupported test batch operation: {kind}')
            self.items = working
            self.sequence = sequence
        self._hook('after_batch')
        return responses

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        with self._lock:
            self.queries.append((query, deepcopy(parameters), partition_key))
            if self.fail_queries:
                raise AzureError('Private test query failure')
            params = {entry['name']: entry['value'] for entry in parameters or []}
            rows = [
                deepcopy(item) for (partition, _), item in self.items.items()
                if partition_key is None or partition == partition_key
            ]
        for parameter, field in (
            ('@conversation_id', 'conversation_id'), ('@user_id', 'user_id'), ('@run_id', 'id'),
        ):
            if parameter in params:
                rows = [row for row in rows if row.get(field) == params[parameter]]
        if '@turn_id' in params:
            rows = [
                row for row in rows
                if (row.get('turn_id') or (row.get('plan') or {}).get('turn_id')) == params['@turn_id']
            ]
        if '@revision_root_run_id' in params:
            rows = [
                row for row in rows
                if (row.get('revision_root_run_id') or row['id']) == params['@revision_root_run_id']
            ]
        if '@before_revision' in params:
            rows = [row for row in rows if row.get('revision', 0) < params['@before_revision']]
        if '@message_ids' in params:
            rows = [row for row in rows if row['id'] in params['@message_ids']]
        if '@before_timestamp' in params:
            rows = [row for row in rows if row.get('timestamp', '') < params['@before_timestamp']]
        if 'c.record_type' in query:
            rows = [row for row in rows if row.get('record_type') in (None, 'run', 'orchestration_run')]
        if 'NOT IS_DEFINED(c.superseded_by_run_id)' in query:
            rows = [row for row in rows if 'superseded_by_run_id' not in row]
        if 'c.status != "superseded"' in query:
            rows = [row for row in rows if row.get('status') != 'superseded']
        if 'c.role IN' in query:
            rows = [
                row for row in rows
                if row.get('role') in ('user', 'assistant')
                and not (row.get('metadata') or {}).get('masked')
                and not (row.get('metadata') or {}).get('is_generated_chat_artifact')
                and (row.get('metadata') or {}).get('thread_info', {}).get('active_thread') is not False
            ]
        if 'SELECT VALUE MAX' in query:
            return [max((row.get('turn_index', 0) for row in rows), default=None)]
        for field in ('timestamp', 'created_at', 'turn_index', 'revision'):
            if f'ORDER BY c.{field} DESC' in query:
                rows.sort(key=lambda row: row.get(field, 0 if field in ('revision', 'turn_index') else ''), reverse=True)
        top = re.search(r'SELECT TOP (\d+)', query)
        return rows[:int(top.group(1))] if top else rows
