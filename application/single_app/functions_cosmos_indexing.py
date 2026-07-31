# functions_cosmos_indexing.py
"""Cosmos DB indexing policy comparison and maintenance helpers."""

import copy
import logging
from datetime import datetime, timezone

from azure.core import MatchConditions
from azure.cosmos import PartitionKey

from config import (
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


COSMOS_INDEXING_POLICY_DEFINITION_VERSION = 2
COSMOS_INDEXING_POLICY_APPLY_SETTING = 'app_maintenance_apply_cosmos_indexing_policies'
COSMOS_INDEXING_POLICY_MAX_REPLACE_RETRIES = 3


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
        partition_key=PartitionKey(path=definition['partition_key_path']),
        indexing_policy=desired_policy,
        **replace_kwargs,
    )


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
                    '[CosmosIndexing] Retrying indexing policy update after ETag conflict.',
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
                '[CosmosIndexing] Failed to evaluate Cosmos indexing policy.',
                extra={
                    'container_name': definition.get('container_name'),
                    'apply_changes': bool(apply_changes),
                    'error': str(exc),
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            results.append({
                'container_name': definition.get('container_name'),
                'partition_key_path': definition.get('partition_key_path'),
                'description': definition.get('description', ''),
                'status': 'failed',
                'apply_requested': bool(apply_changes),
                'applied': False,
                'definition_version': COSMOS_INDEXING_POLICY_DEFINITION_VERSION,
                'error': str(exc),
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
