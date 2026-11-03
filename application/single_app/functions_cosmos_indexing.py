# functions_cosmos_indexing.py
"""Cosmos DB indexing policy comparison and maintenance helpers."""

import copy
import logging
from collections.abc import Mapping
from datetime import datetime, timezone

from azure.core import MatchConditions

import config as app_config
from config import (
    cosmos_activity_logs_container,
    cosmos_activity_logs_container_name,
    cosmos_collaboration_messages_container,
    cosmos_collaboration_messages_container_name,
    cosmos_conversations_container,
    cosmos_conversations_container_name,
    cosmos_data_management_jobs_container,
    cosmos_data_management_jobs_container_name,
    cosmos_database,
    cosmos_group_documents_container,
    cosmos_group_documents_container_name,
    cosmos_messages_container,
    cosmos_messages_container_name,
    cosmos_public_documents_container,
    cosmos_public_documents_container_name,
    cosmos_user_documents_container,
    cosmos_user_documents_container_name,
)
from functions_appinsights import log_event


COSMOS_INDEXING_POLICY_DEFINITION_VERSION = 3
COSMOS_INDEXING_POLICY_APPLY_SETTING = 'app_maintenance_apply_cosmos_indexing_policies'
COSMOS_INDEXING_POLICY_MAX_REPLACE_RETRIES = 3
COSMOS_INDEXING_FAILURE_MESSAGES = {
    'invalid_partition_key_definition': 'The existing partition-key definition could not be verified. No update was submitted.',
    'partition_key_change_rejected': 'Cosmos rejected a partition-key change. Upgrade to the patched application and retry applying indexes.',
    'indexing_access_denied': 'Cosmos denied access. Ask an administrator to verify the application identity has the required access.',
    'indexing_conflict': 'The container changed during the update. Refresh status and retry applying indexes.',
    'indexing_policy_failed': 'Unable to process the indexing policy. Check the server logs before retrying.',
}


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _composite_index(*paths):
    return [
        {
            'path': path,
            'order': order,
        }
        for path, order in paths
    ]


COSMOS_INDEXING_POLICY_DEFINITIONS = [
    {
        'container_name': cosmos_activity_logs_container_name,
        'container': cosmos_activity_logs_container,
        'partition_key_path': '/user_id',
        'description': 'Control Center activity feed keyset ordering with partition-aware ties.',
        'expected_policy': {
            'compositeIndexes': [
                _composite_index(
                    ('/timestamp', 'descending'), ('/id', 'descending'), ('/user_id', 'descending'),
                ),
            ],
        },
    },
    {
        'container_name': cosmos_conversations_container_name,
        'container': cosmos_conversations_container,
        'partition_key_path': '/id',
        'description': 'Personal conversation list, feed, and search ordering by user and last update.',
        'expected_policy': {
            'compositeIndexes': [
                _composite_index(('/user_id', 'ascending'), ('/last_updated', 'descending')),
                _composite_index(
                    ('/user_id', 'ascending'),
                    ('/is_hidden', 'ascending'),
                    ('/last_updated', 'descending'),
                ),
            ],
        },
    },
    {
        'container_name': cosmos_messages_container_name,
        'container': cosmos_messages_container,
        'partition_key_path': '/conversation_id',
        'description': 'Personal chat message ordering by timestamp and retry-thread attempt metadata.',
        'expected_policy': {
            'compositeIndexes': [
                _composite_index(('/conversation_id', 'ascending'), ('/timestamp', 'ascending')),
                _composite_index(('/conversation_id', 'ascending'), ('/timestamp', 'descending')),
                _composite_index(
                    ('/conversation_id', 'ascending'),
                    ('/metadata/thread_info/thread_id', 'ascending'),
                    ('/role', 'ascending'),
                    ('/metadata/thread_info/thread_attempt', 'ascending'),
                ),
            ],
        },
    },
    {
        'container_name': cosmos_data_management_jobs_container_name,
        'container': cosmos_data_management_jobs_container,
        'partition_key_path': '/id',
        'description': 'Deterministic Data Management job and backup history pagination.',
        'expected_policy': {
            'compositeIndexes': [
                _composite_index(('/created_at', 'descending'), ('/id', 'descending')),
            ],
        },
    },
    {
        'container_name': cosmos_collaboration_messages_container_name,
        'container': cosmos_collaboration_messages_container,
        'partition_key_path': '/conversation_id',
        'description': 'Collaboration chat message ordering by timestamp.',
        'expected_policy': {
            'compositeIndexes': [
                _composite_index(('/conversation_id', 'ascending'), ('/timestamp', 'ascending')),
                _composite_index(('/conversation_id', 'ascending'), ('/timestamp', 'descending')),
            ],
        },
    },
    {
        'container_name': cosmos_user_documents_container_name,
        'container': cosmos_user_documents_container,
        'partition_key_path': '/id',
        'description': 'Personal document version lookups before the document access index read model.',
        'expected_policy': {
            'compositeIndexes': [
                _composite_index(('/id', 'ascending'), ('/version', 'descending')),
                _composite_index(('/id', 'ascending'), ('/user_id', 'ascending'), ('/version', 'descending')),
            ],
        },
    },
    {
        'container_name': cosmos_group_documents_container_name,
        'container': cosmos_group_documents_container,
        'partition_key_path': '/id',
        'description': 'Group document version lookups before the document access index read model.',
        'expected_policy': {
            'compositeIndexes': [
                _composite_index(('/id', 'ascending'), ('/version', 'descending')),
                _composite_index(('/id', 'ascending'), ('/group_id', 'ascending'), ('/version', 'descending')),
            ],
        },
    },
    {
        'container_name': cosmos_public_documents_container_name,
        'container': cosmos_public_documents_container,
        'partition_key_path': '/id',
        'description': 'Public workspace document version lookups before the document access index read model.',
        'expected_policy': {
            'compositeIndexes': [
                _composite_index(('/id', 'ascending'), ('/version', 'descending')),
                _composite_index(
                    ('/id', 'ascending'),
                    ('/public_workspace_id', 'ascending'),
                    ('/version', 'descending'),
                ),
            ],
        },
    },
]

if getattr(app_config, "cosmos_content_screening_container", None) is not None:
    COSMOS_INDEXING_POLICY_DEFINITIONS.append({
        'container_name': app_config.cosmos_content_screening_container_name,
        'container': app_config.cosmos_content_screening_container,
        'partition_key_path': '/partition_key',
        'description': 'Paged screening review queues and durable scan-job work items.',
        'expected_policy': {
            'compositeIndexes': [
                _composite_index(('/kind', 'ascending'), ('/scope_key', 'ascending'), ('/sort_key', 'ascending')),
                _composite_index(('/kind', 'ascending'), ('/actor_id', 'ascending'), ('/sort_key', 'ascending')),
                _composite_index(('/kind', 'ascending'), ('/status', 'ascending'), ('/sort_key', 'ascending')),
                _composite_index(
                    ('/kind', 'ascending'), ('/job_id', 'ascending'),
                    ('/status', 'ascending'), ('/sort_key', 'ascending'),
                ),
            ],
        },
    })


def _normalize_composite_path(path_definition):
    path = str((path_definition or {}).get('path') or '').strip()
    if path and not path.startswith('/'):
        path = f'/{path}'
    order = str((path_definition or {}).get('order') or 'ascending').strip().lower()
    if order not in ('ascending', 'descending'):
        order = 'ascending'
    return {
        'path': path,
        'order': order,
    }


def _canonical_composite_index(composite_index):
    return tuple(
        (
            normalized_path['path'],
            normalized_path['order'],
        )
        for normalized_path in [_normalize_composite_path(path) for path in list(composite_index or [])]
        if normalized_path['path']
    )


def _normalize_composite_index(composite_index):
    return [
        {
            'path': path,
            'order': order,
        }
        for path, order in _canonical_composite_index(composite_index)
    ]


def _get_current_indexing_policy(container_properties):
    current_policy = copy.deepcopy((container_properties or {}).get('indexingPolicy') or {})
    current_policy.setdefault('indexingMode', 'consistent')
    current_policy.setdefault('automatic', True)
    current_policy.setdefault('includedPaths', [{'path': '/*'}])
    current_policy.setdefault('excludedPaths', [{'path': '/"_etag"/?'}])
    current_policy['compositeIndexes'] = list(current_policy.get('compositeIndexes') or [])
    return current_policy


def _merge_expected_indexing_policy(current_policy, expected_policy):
    desired_policy = copy.deepcopy(current_policy or {})
    current_composite_indexes = list(desired_policy.get('compositeIndexes') or [])
    current_canonical_indexes = {
        _canonical_composite_index(index)
        for index in current_composite_indexes
        if _canonical_composite_index(index)
    }

    missing_indexes = []
    for expected_index in list((expected_policy or {}).get('compositeIndexes') or []):
        normalized_expected_index = _normalize_composite_index(expected_index)
        canonical_expected_index = _canonical_composite_index(normalized_expected_index)
        if not canonical_expected_index:
            continue
        if canonical_expected_index in current_canonical_indexes:
            continue
        missing_indexes.append(normalized_expected_index)
        current_composite_indexes.append(normalized_expected_index)
        current_canonical_indexes.add(canonical_expected_index)

    desired_policy['compositeIndexes'] = current_composite_indexes
    return desired_policy, missing_indexes


def _is_precondition_failed_error(exc):
    return getattr(exc, 'status_code', None) == 412


def _replace_container_indexing_policy(definition, container_properties, desired_policy):
    partition_key = (container_properties or {}).get('partitionKey')
    if (
        not isinstance(partition_key, Mapping)
        or partition_key.get('kind') not in ('Hash', 'MultiHash')
        or not isinstance(partition_key.get('paths'), list)
        or not partition_key['paths']
        or any(not isinstance(path, str) or not path.startswith('/') or len(path) < 2 for path in partition_key['paths'])
        or (partition_key['kind'] == 'Hash' and len(partition_key['paths']) != 1)
        or ('version' in partition_key and (
            type(partition_key['version']) is not int or partition_key['version'] not in (1, 2)
        ))
    ):
        raise ValueError('Container partition-key metadata is missing or invalid.')

    replace_kwargs = {}
    etag = (container_properties or {}).get('_etag')
    if etag:
        replace_kwargs['etag'] = etag
        replace_kwargs['match_condition'] = MatchConditions.IfNotModified

    if 'defaultTtl' in (container_properties or {}):
        replace_kwargs['default_ttl'] = container_properties.get('defaultTtl')
    if 'analyticalStorageTtl' in (container_properties or {}):
        replace_kwargs['analytical_storage_ttl'] = container_properties.get('analyticalStorageTtl')
    if 'conflictResolutionPolicy' in (container_properties or {}):
        replace_kwargs['conflict_resolution_policy'] = container_properties.get('conflictResolutionPolicy')
    if 'fullTextPolicy' in (container_properties or {}):
        replace_kwargs['full_text_policy'] = container_properties.get('fullTextPolicy')

    cosmos_database.replace_container(
        container=definition['container_name'],
        # PartitionKey(path=...) defaults to version 2, changing legacy immutable keys.
        partition_key=copy.deepcopy(dict(partition_key)),
        indexing_policy=desired_policy,
        **replace_kwargs,
    )


def _indexing_failure_details(exc):
    if isinstance(exc, ValueError):
        code = 'invalid_partition_key_definition'
    elif getattr(exc, 'status_code', None) == 400 and 'partition key cannot be changed' in str(exc).lower():
        code = 'partition_key_change_rejected'
    elif getattr(exc, 'status_code', None) in (401, 403):
        code = 'indexing_access_denied'
    elif _is_precondition_failed_error(exc):
        code = 'indexing_conflict'
    else:
        code = 'indexing_policy_failed'
    return code, COSMOS_INDEXING_FAILURE_MESSAGES[code]


def sanitize_cosmos_indexing_result(result):
    """Keep historical indexing errors safe when older maintenance state is returned."""
    sanitized = copy.deepcopy(result)
    if not isinstance(sanitized, dict):
        return None
    for container in sanitized.get('containers') or []:
        if isinstance(container, dict) and container.get('status') == 'failed':
            code = container.get('error_code')
            if code not in COSMOS_INDEXING_FAILURE_MESSAGES:
                code = (
                    'partition_key_change_rejected'
                    if 'partition key cannot be changed' in str(container.get('error', '')).lower()
                    else 'indexing_policy_failed'
                )
            container['error_code'] = code
            container['error'] = COSMOS_INDEXING_FAILURE_MESSAGES[code]
    return sanitized


def _evaluate_single_indexing_policy(definition, apply_changes=False):
    for attempt in range(COSMOS_INDEXING_POLICY_MAX_REPLACE_RETRIES):
        container_properties = definition['container'].read()
        current_policy = _get_current_indexing_policy(container_properties)
        desired_policy, missing_indexes = _merge_expected_indexing_policy(
            current_policy,
            definition.get('expected_policy', {}),
        )

        result = {
            'container_name': definition['container_name'],
            'partition_key_path': definition['partition_key_path'],
            'description': definition.get('description', ''),
            'status': 'aligned' if not missing_indexes else 'missing_expected_indexes',
            'apply_requested': bool(apply_changes),
            'applied': False,
            'definition_version': COSMOS_INDEXING_POLICY_DEFINITION_VERSION,
            'current_composite_index_count': len(current_policy.get('compositeIndexes') or []),
            'expected_composite_index_count': len(
                list((definition.get('expected_policy') or {}).get('compositeIndexes') or [])
            ),
            'missing_composite_index_count': len(missing_indexes),
            'missing_composite_indexes': missing_indexes,
            'index_transformation_progress': container_properties.get('indexTransformationProgress'),
        }

        if not missing_indexes or not apply_changes:
            return result

        try:
            _replace_container_indexing_policy(definition, container_properties, desired_policy)
            result.update({
                'status': 'updated',
                'applied': True,
                'submitted_at': _utc_now_iso(),
                'desired_composite_index_count': len(desired_policy.get('compositeIndexes') or []),
            })
            return result
        except Exception as exc:
            if _is_precondition_failed_error(exc) and attempt < COSMOS_INDEXING_POLICY_MAX_REPLACE_RETRIES - 1:
                log_event(
                    '[COSMOS_INDEXING] Retrying indexing policy update after ETag conflict.',
                    extra={
                        'container_name': definition['container_name'],
                        'attempt': attempt + 1,
                    },
                    level=logging.WARNING,
                    debug_only=True,
                )
                continue
            raise

    raise RuntimeError(f"Failed to update indexing policy for {definition['container_name']} after retries.")


def list_expected_cosmos_indexing_policies():
    """Return JSON-safe expected Cosmos indexing policy definitions."""
    return [
        {
            'container_name': definition['container_name'],
            'partition_key_path': definition['partition_key_path'],
            'description': definition.get('description', ''),
            'definition_version': COSMOS_INDEXING_POLICY_DEFINITION_VERSION,
            'expected_composite_indexes': [
                _normalize_composite_index(index)
                for index in list((definition.get('expected_policy') or {}).get('compositeIndexes') or [])
            ],
        }
        for definition in COSMOS_INDEXING_POLICY_DEFINITIONS
    ]


def run_cosmos_indexing_policy_maintenance(apply_changes=False):
    """Compare or apply expected Cosmos indexing policies for configured hot containers."""
    results = []
    for definition in COSMOS_INDEXING_POLICY_DEFINITIONS:
        try:
            results.append(_evaluate_single_indexing_policy(definition, apply_changes=apply_changes))
        except Exception as exc:
            log_event(
                '[COSMOS_INDEXING] Failed to evaluate Cosmos indexing policy.',
                extra={
                    'container_name': definition.get('container_name'),
                    'apply_changes': bool(apply_changes),
                    'error': str(exc),
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            error_code, error_message = _indexing_failure_details(exc)
            results.append({
                'container_name': definition.get('container_name'),
                'partition_key_path': definition.get('partition_key_path'),
                'description': definition.get('description', ''),
                'status': 'failed',
                'apply_requested': bool(apply_changes),
                'applied': False,
                'definition_version': COSMOS_INDEXING_POLICY_DEFINITION_VERSION,
                'error_code': error_code,
                'error': error_message,
            })

    failed_count = sum(1 for result in results if result.get('status') == 'failed')
    missing_count = sum(1 for result in results if result.get('missing_composite_index_count', 0))
    updated_count = sum(1 for result in results if result.get('applied'))

    return {
        'success': failed_count == 0,
        'mode': 'apply' if apply_changes else 'report_only',
        'apply_setting': COSMOS_INDEXING_POLICY_APPLY_SETTING,
        'definition_version': COSMOS_INDEXING_POLICY_DEFINITION_VERSION,
        'container_count': len(results),
        'failed_container_count': failed_count,
        'containers_missing_expected_indexes': missing_count,
        'updated_container_count': updated_count,
        'evaluated_at': _utc_now_iso(),
        'containers': results,
    }


def get_cosmos_indexing_policy_status():
    """Return report-only Cosmos indexing policy status for admin diagnostics."""
    return run_cosmos_indexing_policy_maintenance(apply_changes=False)
