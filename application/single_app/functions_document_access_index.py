# functions_document_access_index.py
"""Document access index projection helpers for Cosmos-backed document reads."""

import copy
import hashlib
import logging
import re
from datetime import datetime, timezone

from config import (
    cosmos_document_access_index_container,
    cosmos_group_documents_container,
    cosmos_group_documents_container_name,
    cosmos_public_documents_container,
    cosmos_public_documents_container_name,
    cosmos_settings_container,
    cosmos_user_documents_container,
    cosmos_user_documents_container_name,
)
from functions_appinsights import log_event
from functions_settings import get_settings


DOCUMENT_ACCESS_INDEX_TYPE = 'document_access_index'
DOCUMENT_ACCESS_REPAIR_TYPE = 'document_access_index_repair'
DOCUMENT_ACCESS_BACKFILL_STATE_TYPE = 'document_access_index_backfill_state'
DOCUMENT_ACCESS_BACKFILL_STATE_DOC_ID = 'document_access_index_backfill_state'
DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION = 1

DOCUMENT_ACCESS_SCOPE_PERSONAL = 'personal'
DOCUMENT_ACCESS_SCOPE_GROUP = 'group'
DOCUMENT_ACCESS_SCOPE_PUBLIC = 'public'
DOCUMENT_ACCESS_PRINCIPAL_USER = 'user'

DOCUMENT_ACCESS_OPERATION_UPSERT = 'upsert'
DOCUMENT_ACCESS_OPERATION_DELETE = 'delete'

DOCUMENT_ACCESS_APPROVAL_APPROVED = 'approved'
DOCUMENT_ACCESS_APPROVAL_NOT_APPROVED = 'not_approved'

DOCUMENT_ACCESS_BACKFILL_ENABLED_SETTING = 'enable_startup_document_access_index_backfill'
DOCUMENT_ACCESS_BACKFILL_BATCH_SIZE_SETTING = 'document_access_index_backfill_batch_size'
DOCUMENT_ACCESS_REPAIR_BATCH_SIZE_SETTING = 'document_access_index_repair_batch_size'
DOCUMENT_ACCESS_DEFAULT_BACKFILL_BATCH_SIZE = 200
DOCUMENT_ACCESS_MAX_BACKFILL_BATCH_SIZE = 1000
DOCUMENT_ACCESS_DEFAULT_REPAIR_BATCH_SIZE = 100
DOCUMENT_ACCESS_MAX_REPAIR_BATCH_SIZE = 500

DOCUMENT_ACCESS_SOURCE_SCOPES = (
    DOCUMENT_ACCESS_SCOPE_PERSONAL,
    DOCUMENT_ACCESS_SCOPE_GROUP,
    DOCUMENT_ACCESS_SCOPE_PUBLIC,
)


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _normalize_positive_int(value, default_value, min_value=1, max_value=1000):
    try:
        normalized_value = int(value)
    except (TypeError, ValueError):
        normalized_value = default_value
    return min(max(normalized_value, min_value), max_value)


def get_document_access_index_settings(settings=None):
    """Normalize document access index feature flags."""
    if settings is None:
        settings = get_settings()
    return {
        'container_enabled': bool(settings.get('enable_document_access_index_container', True)),
        'write_through_enabled': bool(settings.get('enable_document_access_index_write_through', True)),
        'reads_enabled': bool(settings.get('enable_document_access_index_reads', False)),
        'shadow_validation_enabled': bool(settings.get('enable_document_access_index_shadow_validation', False)),
        'startup_backfill_enabled': bool(settings.get(DOCUMENT_ACCESS_BACKFILL_ENABLED_SETTING, False)),
        'backfill_batch_size': _normalize_positive_int(
            settings.get(DOCUMENT_ACCESS_BACKFILL_BATCH_SIZE_SETTING),
            DOCUMENT_ACCESS_DEFAULT_BACKFILL_BATCH_SIZE,
            max_value=DOCUMENT_ACCESS_MAX_BACKFILL_BATCH_SIZE,
        ),
        'repair_batch_size': _normalize_positive_int(
            settings.get(DOCUMENT_ACCESS_REPAIR_BATCH_SIZE_SETTING),
            DOCUMENT_ACCESS_DEFAULT_REPAIR_BATCH_SIZE,
            max_value=DOCUMENT_ACCESS_MAX_REPAIR_BATCH_SIZE,
        ),
    }


def _is_container_enabled(settings=None):
    normalized_settings = get_document_access_index_settings(settings)
    return normalized_settings.get('container_enabled')


def _is_write_through_enabled(settings=None, force=False):
    normalized_settings = get_document_access_index_settings(settings)
    if force:
        return normalized_settings.get('container_enabled')
    return normalized_settings.get('container_enabled') and normalized_settings.get('write_through_enabled')


def _is_not_found_error(exc):
    return getattr(exc, 'status_code', None) == 404


def _safe_id_part(value):
    normalized = str(value or '').strip()
    normalized = re.sub(r'[^A-Za-z0-9_.:-]+', '_', normalized)
    return normalized or 'none'


def build_document_access_scope_key(scope_type, scope_id):
    """Build the access-index partition key for a user, group, or public workspace scope."""
    normalized_scope_type = str(scope_type or '').strip().lower()
    normalized_scope_id = str(scope_id or '').strip()
    if not normalized_scope_type or not normalized_scope_id:
        return None
    return f'{normalized_scope_type}:{normalized_scope_id}'


def build_document_access_index_row_id(scope_key, source_scope, document_id, version):
    """Build a deterministic Cosmos id for one scope/document/version projection row."""
    raw_id = ':'.join([
        'dai',
        _safe_id_part(scope_key),
        _safe_id_part(source_scope),
        _safe_id_part(document_id),
        _safe_id_part(version),
    ])
    if len(raw_id) <= 900:
        return raw_id
    return f'dai:{hashlib.sha256(raw_id.encode("utf-8")).hexdigest()}'


def _normalize_string_list(value):
    if not isinstance(value, list):
        return []
    return [
        str(item).strip()
        for item in value
        if str(item or '').strip()
    ]


def _normalize_share_entry(entry):
    normalized_entry = str(entry or '').strip()
    if not normalized_entry:
        return None
    if ',' in normalized_entry:
        scope_id, approval_status = normalized_entry.split(',', 1)
        approval_status = str(approval_status or '').strip().lower() or 'unknown'
    else:
        scope_id = normalized_entry
        approval_status = DOCUMENT_ACCESS_APPROVAL_NOT_APPROVED

    scope_id = str(scope_id or '').strip()
    if not scope_id:
        return None
    return {
        'scope_id': scope_id,
        'approval_status': approval_status,
        'raw_entry': normalized_entry,
    }


def _resolve_source_scope(document_item):
    if document_item.get('public_workspace_id'):
        return DOCUMENT_ACCESS_SCOPE_PUBLIC
    if document_item.get('group_id'):
        return DOCUMENT_ACCESS_SCOPE_GROUP
    return DOCUMENT_ACCESS_SCOPE_PERSONAL


def _source_scope_container_name(source_scope):
    if source_scope == DOCUMENT_ACCESS_SCOPE_PUBLIC:
        return 'public_documents'
    if source_scope == DOCUMENT_ACCESS_SCOPE_GROUP:
        return 'group_documents'
    return 'documents'


def _get_document_version(document_item):
    try:
        return int(document_item.get('version') or 0)
    except (TypeError, ValueError):
        return 0


def _build_base_row(document_item, source_scope, scope_type, scope_id, access_role, approval_status, projected_at):
    document_id = str(document_item.get('id') or document_item.get('document_id') or '').strip()
    version = _get_document_version(document_item)
    scope_key = build_document_access_scope_key(scope_type, scope_id)
    if not document_id or not scope_key:
        return None

    approval_status = str(approval_status or '').strip().lower() or 'unknown'
    access_granted = approval_status == DOCUMENT_ACCESS_APPROVAL_APPROVED
    source_updated_at = document_item.get('last_updated') or document_item.get('upload_date')

    return {
        'id': build_document_access_index_row_id(scope_key, source_scope, document_id, version),
        'type': DOCUMENT_ACCESS_INDEX_TYPE,
        'schema_version': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
        'projection_status': 'ready',
        'projection_version': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
        'repair_required': False,
        'projected_at': projected_at,
        'scope_key': scope_key,
        'scope_type': scope_type,
        'scope_id': str(scope_id or '').strip(),
        'source_scope': source_scope,
        'source_container': _source_scope_container_name(source_scope),
        'source_document_id': document_id,
        'source_partition_key': document_id,
        'document_id': document_id,
        'revision_family_id': document_item.get('revision_family_id') or document_id,
        'version': version,
        'is_current_version': bool(document_item.get('is_current_version', True)),
        'search_visibility_state': str(document_item.get('search_visibility_state') or 'active').strip().lower(),
        'access_role': access_role,
        'approval_status': approval_status,
        'access_granted': access_granted,
        'file_name': document_item.get('file_name'),
        'title': document_item.get('title'),
        'document_classification': document_item.get('document_classification', 'None'),
        'tags': _normalize_string_list(document_item.get('tags')),
        'status': document_item.get('status'),
        'percentage_complete': document_item.get('percentage_complete'),
        'upload_date': document_item.get('upload_date'),
        'last_updated': document_item.get('last_updated'),
        'source_updated_at': source_updated_at,
        'owner_user_id': document_item.get('user_id'),
        'owner_group_id': document_item.get('group_id'),
        'owner_public_workspace_id': document_item.get('public_workspace_id'),
    }


def _prefer_projection_row(existing_row, candidate_row):
    if not existing_row:
        return candidate_row
    if existing_row.get('access_role') == 'owner':
        return existing_row
    if candidate_row.get('access_role') == 'owner':
        return candidate_row
    if existing_row.get('access_granted') and not candidate_row.get('access_granted'):
        return candidate_row
    return existing_row


def build_document_access_index_rows(document_item):
    """Build deterministic per-scope projection rows for one source document."""
    if not isinstance(document_item, dict):
        return []

    source_scope = _resolve_source_scope(document_item)
    projected_at = _utc_now_iso()
    rows_by_key = {}

    def add_row(scope_type, scope_id, access_role, approval_status):
        row = _build_base_row(
            document_item,
            source_scope,
            scope_type,
            scope_id,
            access_role,
            approval_status,
            projected_at,
        )
        if not row:
            return
        row_key = (row['scope_key'], row['id'])
        rows_by_key[row_key] = _prefer_projection_row(rows_by_key.get(row_key), row)

    if source_scope == DOCUMENT_ACCESS_SCOPE_PUBLIC:
        add_row(
            DOCUMENT_ACCESS_SCOPE_PUBLIC,
            document_item.get('public_workspace_id'),
            'public_workspace',
            DOCUMENT_ACCESS_APPROVAL_APPROVED,
        )
    elif source_scope == DOCUMENT_ACCESS_SCOPE_GROUP:
        add_row(
            DOCUMENT_ACCESS_SCOPE_GROUP,
            document_item.get('group_id'),
            'owner',
            DOCUMENT_ACCESS_APPROVAL_APPROVED,
        )
        for share_entry in _normalize_string_list(document_item.get('shared_group_ids')):
            normalized_share = _normalize_share_entry(share_entry)
            if normalized_share:
                add_row(
                    DOCUMENT_ACCESS_SCOPE_GROUP,
                    normalized_share['scope_id'],
                    'shared_group',
                    normalized_share['approval_status'],
                )
    else:
        add_row(
            DOCUMENT_ACCESS_PRINCIPAL_USER,
            document_item.get('user_id'),
            'owner',
            DOCUMENT_ACCESS_APPROVAL_APPROVED,
        )
        for share_entry in _normalize_string_list(document_item.get('shared_user_ids')):
            normalized_share = _normalize_share_entry(share_entry)
            if normalized_share:
                add_row(
                    DOCUMENT_ACCESS_PRINCIPAL_USER,
                    normalized_share['scope_id'],
                    'shared_user',
                    normalized_share['approval_status'],
                )

    return sorted(rows_by_key.values(), key=lambda row: (row['scope_key'], row['id']))


def _query_existing_projection_rows(source_scope, document_id):
    query = (
        'SELECT c.id, c.scope_key FROM c '
        'WHERE c.type = @type AND c.source_scope = @source_scope AND c.source_document_id = @document_id'
    )
    return list(cosmos_document_access_index_container.query_items(
        query=query,
        parameters=[
            {'name': '@type', 'value': DOCUMENT_ACCESS_INDEX_TYPE},
            {'name': '@source_scope', 'value': source_scope},
            {'name': '@document_id', 'value': document_id},
        ],
        enable_cross_partition_query=True,
    ))


def _repair_document_id(source_scope, document_id):
    raw_id = f'document_access_projection_repair:{source_scope}:{document_id}'
    if len(raw_id) <= 900:
        return raw_id
    return f'document_access_projection_repair:{hashlib.sha256(raw_id.encode("utf-8")).hexdigest()}'


def _record_projection_repair_required(document_item, operation, error):
    document_item = document_item if isinstance(document_item, dict) else {}
    document_id = str(document_item.get('id') or document_item.get('document_id') or '').strip()
    if not document_id:
        return None
    source_scope = _resolve_source_scope(document_item)
    repair_doc_id = _repair_document_id(source_scope, document_id)
    repair_doc = {
        'id': repair_doc_id,
        'type': DOCUMENT_ACCESS_REPAIR_TYPE,
        'status': 'repair_required',
        'operation': operation,
        'source_scope': source_scope,
        'source_document_id': document_id,
        'source_updated_at': document_item.get('last_updated') or document_item.get('upload_date'),
        'error': str(error),
        'updated_at': _utc_now_iso(),
        'schema_version': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
    }
    cosmos_settings_container.upsert_item(repair_doc)
    return repair_doc


def _clear_projection_repair_required(source_scope, document_id):
    repair_doc_id = _repair_document_id(source_scope, document_id)
    try:
        cosmos_settings_container.delete_item(item=repair_doc_id, partition_key=repair_doc_id)
    except Exception as exc:
        if not _is_not_found_error(exc):
            log_event(
                '[DocumentAccessIndex] Failed to clear projection repair state.',
                extra={
                    'source_scope': source_scope,
                    'document_id': document_id,
                    'error': str(exc),
                },
                level=logging.WARNING,
                exceptionTraceback=True,
            )


def sync_document_access_index_for_document(
    document_item,
    operation=DOCUMENT_ACCESS_OPERATION_UPSERT,
    settings=None,
    force=False,
):
    """Synchronize access-index rows for one source document."""
    if not _is_write_through_enabled(settings, force=force):
        return {
            'success': True,
            'status': 'skipped_disabled',
            'operation': operation,
            'upserted_count': 0,
            'deleted_count': 0,
        }

    rows = build_document_access_index_rows(document_item)
    document_id = str((document_item or {}).get('id') or (document_item or {}).get('document_id') or '').strip()
    if not document_id:
        raise ValueError('document_item must include id or document_id')

    source_scope = _resolve_source_scope(document_item)
    expected_keys = {(row['scope_key'], row['id']) for row in rows}
    existing_rows = _query_existing_projection_rows(source_scope, document_id)
    deleted_count = 0

    for existing_row in existing_rows:
        existing_key = (existing_row.get('scope_key'), existing_row.get('id'))
        if existing_key in expected_keys:
            continue
        cosmos_document_access_index_container.delete_item(
            item=existing_row.get('id'),
            partition_key=existing_row.get('scope_key'),
        )
        deleted_count += 1

    for row in rows:
        cosmos_document_access_index_container.upsert_item(copy.deepcopy(row))

    _clear_projection_repair_required(source_scope, document_id)
    return {
        'success': True,
        'status': 'synchronized',
        'operation': operation,
        'source_scope': source_scope,
        'document_id': document_id,
        'upserted_count': len(rows),
        'deleted_count': deleted_count,
    }


def delete_document_access_index_for_document(
    document_item,
    operation=DOCUMENT_ACCESS_OPERATION_DELETE,
    settings=None,
    force=False,
):
    """Delete all access-index rows for one source document."""
    if not _is_write_through_enabled(settings, force=force):
        return {
            'success': True,
            'status': 'skipped_disabled',
            'operation': operation,
            'deleted_count': 0,
        }

    document_id = str((document_item or {}).get('id') or (document_item or {}).get('document_id') or '').strip()
    if not document_id:
        raise ValueError('document_item must include id or document_id')

    source_scope = _resolve_source_scope(document_item)
    existing_rows = _query_existing_projection_rows(source_scope, document_id)
    deleted_count = 0
    for existing_row in existing_rows:
        cosmos_document_access_index_container.delete_item(
            item=existing_row.get('id'),
            partition_key=existing_row.get('scope_key'),
        )
        deleted_count += 1

    _clear_projection_repair_required(source_scope, document_id)
    return {
        'success': True,
        'status': 'deleted',
        'operation': operation,
        'source_scope': source_scope,
        'document_id': document_id,
        'deleted_count': deleted_count,
    }


def sync_document_access_index_for_document_fail_open(document_item, operation=DOCUMENT_ACCESS_OPERATION_UPSERT, settings=None):
    """Synchronize projection rows without failing the source document mutation."""
    try:
        return sync_document_access_index_for_document(document_item, operation=operation, settings=settings)
    except Exception as exc:
        log_event(
            '[DocumentAccessIndex] Document access index synchronization failed; source document remains authoritative.',
            extra={
                'document_id': (document_item or {}).get('id'),
                'operation': operation,
                'error': str(exc),
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        try:
            _record_projection_repair_required(document_item, operation, exc)
        except Exception as repair_exc:
            log_event(
                '[DocumentAccessIndex] Failed to record projection repair state.',
                extra={
                    'document_id': (document_item or {}).get('id'),
                    'operation': operation,
                    'error': str(repair_exc),
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
        return {
            'success': False,
            'status': 'repair_required',
            'operation': operation,
            'error': str(exc),
        }


def delete_document_access_index_for_document_fail_open(document_item, operation=DOCUMENT_ACCESS_OPERATION_DELETE, settings=None):
    """Delete projection rows without failing the source document mutation."""
    try:
        return delete_document_access_index_for_document(document_item, operation=operation, settings=settings)
    except Exception as exc:
        log_event(
            '[DocumentAccessIndex] Document access index delete failed; source document remains authoritative.',
            extra={
                'document_id': (document_item or {}).get('id'),
                'operation': operation,
                'error': str(exc),
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        try:
            _record_projection_repair_required(document_item, operation, exc)
        except Exception as repair_exc:
            log_event(
                '[DocumentAccessIndex] Failed to record projection delete repair state.',
                extra={
                    'document_id': (document_item or {}).get('id'),
                    'operation': operation,
                    'error': str(repair_exc),
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
        return {
            'success': False,
            'status': 'repair_required',
            'operation': operation,
            'error': str(exc),
        }


def _get_source_scope_container(source_scope):
    if source_scope == DOCUMENT_ACCESS_SCOPE_GROUP:
        return cosmos_group_documents_container, cosmos_group_documents_container_name
    if source_scope == DOCUMENT_ACCESS_SCOPE_PUBLIC:
        return cosmos_public_documents_container, cosmos_public_documents_container_name
    return cosmos_user_documents_container, cosmos_user_documents_container_name


def _normalize_source_scopes(source_scopes=None):
    if not source_scopes:
        return list(DOCUMENT_ACCESS_SOURCE_SCOPES)
    if isinstance(source_scopes, str):
        source_scopes = [source_scopes]
    normalized_scopes = []
    for source_scope in list(source_scopes or []):
        normalized_scope = str(source_scope or '').strip().lower()
        if normalized_scope in DOCUMENT_ACCESS_SOURCE_SCOPES and normalized_scope not in normalized_scopes:
            normalized_scopes.append(normalized_scope)
    return normalized_scopes or list(DOCUMENT_ACCESS_SOURCE_SCOPES)


def _query_first_page(container, query, parameters=None, continuation_token=None, max_item_count=100):
    query_iterable = container.query_items(
        query=query,
        parameters=list(parameters or []),
        enable_cross_partition_query=True,
        max_item_count=max_item_count,
    )
    if not hasattr(query_iterable, 'by_page'):
        return list(query_iterable), None

    try:
        page_iterator = query_iterable.by_page(continuation_token=continuation_token)
    except TypeError:
        page_iterator = query_iterable.by_page(continuation_token)
    try:
        page = next(page_iterator)
    except StopIteration:
        return [], None

    return list(page), getattr(page_iterator, 'continuation_token', None)


def _query_source_document_page(source_scope, continuation_token=None, max_item_count=100):
    source_container, source_container_name = _get_source_scope_container(source_scope)
    query = (
        'SELECT * FROM c '
        'WHERE (NOT IS_DEFINED(c.type) OR c.type = @document_metadata_type)'
    )
    documents, next_token = _query_first_page(
        source_container,
        query=query,
        parameters=[{'name': '@document_metadata_type', 'value': 'document_metadata'}],
        continuation_token=continuation_token,
        max_item_count=max_item_count,
    )
    return {
        'source_scope': source_scope,
        'source_container': source_container_name,
        'documents': documents,
        'continuation_token': next_token,
    }


def _query_repair_documents(max_item_count=DOCUMENT_ACCESS_DEFAULT_REPAIR_BATCH_SIZE):
    query = (
        'SELECT * FROM c '
        'WHERE c.type = @type AND c.status = @status'
    )
    repair_docs, _next_token = _query_first_page(
        cosmos_settings_container,
        query=query,
        parameters=[
            {'name': '@type', 'value': DOCUMENT_ACCESS_REPAIR_TYPE},
            {'name': '@status', 'value': 'repair_required'},
        ],
        max_item_count=max_item_count,
    )
    return repair_docs


def _read_backfill_state():
    try:
        return cosmos_settings_container.read_item(
            item=DOCUMENT_ACCESS_BACKFILL_STATE_DOC_ID,
            partition_key=DOCUMENT_ACCESS_BACKFILL_STATE_DOC_ID,
        )
    except Exception as exc:
        if _is_not_found_error(exc):
            return None
        log_event(
            '[DocumentAccessIndex] Failed to read document access index backfill state.',
            extra={'error': str(exc)},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        raise


def _write_backfill_state(state):
    state_body = copy.deepcopy(state or {})
    state_body.update({
        'id': DOCUMENT_ACCESS_BACKFILL_STATE_DOC_ID,
        'type': DOCUMENT_ACCESS_BACKFILL_STATE_TYPE,
        'updated_at': _utc_now_iso(),
        'schema_version': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
    })
    cosmos_settings_container.upsert_item(state_body)
    return state_body


def _build_initial_backfill_state(source_scopes):
    return {
        'id': DOCUMENT_ACCESS_BACKFILL_STATE_DOC_ID,
        'type': DOCUMENT_ACCESS_BACKFILL_STATE_TYPE,
        'status': 'not_started',
        'source_scopes': list(source_scopes),
        'completed_source_scopes': [],
        'continuation_tokens': {},
        'current_source_scope': None,
        'total_documents_processed': 0,
        'total_documents_failed': 0,
        'total_rows_upserted': 0,
        'total_rows_deleted': 0,
        'last_error': None,
        'schema_version': DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
    }


def _get_next_backfill_scope(source_scopes, completed_source_scopes):
    completed = set(completed_source_scopes or [])
    for source_scope in source_scopes:
        if source_scope not in completed:
            return source_scope
    return None


def _repair_document_stub(source_scope, document_id):
    document_stub = {'id': document_id}
    if source_scope == DOCUMENT_ACCESS_SCOPE_GROUP:
        document_stub['group_id'] = 'repair'
    elif source_scope == DOCUMENT_ACCESS_SCOPE_PUBLIC:
        document_stub['public_workspace_id'] = 'repair'
    return document_stub


def _read_source_document_for_repair(source_scope, document_id):
    source_container, _source_container_name = _get_source_scope_container(source_scope)
    return source_container.read_item(item=document_id, partition_key=document_id)


def _repair_operation_represents_delete(operation):
    normalized_operation = str(operation or '').strip().lower()
    return 'delete' in normalized_operation or 'cleanup' in normalized_operation


def _mark_repair_document_failed(repair_doc, error):
    updated_repair_doc = copy.deepcopy(repair_doc or {})
    updated_repair_doc.update({
        'status': 'repair_required',
        'last_repair_error': str(error),
        'last_repair_attempted_at': _utc_now_iso(),
        'repair_attempt_count': int(updated_repair_doc.get('repair_attempt_count') or 0) + 1,
    })
    cosmos_settings_container.upsert_item(updated_repair_doc)
    return updated_repair_doc


def count_document_access_index_repair_documents():
    """Return the current number of projection repair documents."""
    try:
        return len(_query_repair_documents(max_item_count=DOCUMENT_ACCESS_MAX_REPAIR_BATCH_SIZE))
    except Exception as exc:
        log_event(
            '[DocumentAccessIndex] Failed to count projection repair documents.',
            extra={'error': str(exc)},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None


def get_document_access_index_backfill_status(settings=None):
    """Return persisted backfill state and repair backlog diagnostics."""
    normalized_settings = get_document_access_index_settings(settings)
    state = _read_backfill_state() or _build_initial_backfill_state(DOCUMENT_ACCESS_SOURCE_SCOPES)
    return {
        'success': True,
        'state': state,
        'repair_required_count': count_document_access_index_repair_documents(),
        'settings': {
            'startup_backfill_enabled': normalized_settings.get('startup_backfill_enabled'),
            'backfill_batch_size': normalized_settings.get('backfill_batch_size'),
            'repair_batch_size': normalized_settings.get('repair_batch_size'),
        },
    }


def reconcile_document_access_index_repair_documents(settings=None, max_repairs=None, force=False):
    """Repair projection rows recorded by fail-open write-through operations."""
    if not _is_container_enabled(settings) and not force:
        return {
            'success': True,
            'status': 'skipped_disabled',
            'repairs_processed': 0,
            'repairs_succeeded': 0,
            'repairs_failed': 0,
        }

    normalized_settings = get_document_access_index_settings(settings)
    max_repairs = _normalize_positive_int(
        max_repairs,
        normalized_settings.get('repair_batch_size'),
        max_value=DOCUMENT_ACCESS_MAX_REPAIR_BATCH_SIZE,
    )
    repair_docs = _query_repair_documents(max_item_count=max_repairs)
    repairs_succeeded = 0
    repairs_failed = 0

    for repair_doc in repair_docs:
        document_id = str(repair_doc.get('source_document_id') or '').strip()
        source_scope = str(repair_doc.get('source_scope') or '').strip().lower()
        operation = repair_doc.get('operation')
        if not document_id or source_scope not in DOCUMENT_ACCESS_SOURCE_SCOPES:
            repairs_failed += 1
            _mark_repair_document_failed(repair_doc, 'Repair document is missing source scope or document id.')
            continue

        try:
            if _repair_operation_represents_delete(operation):
                delete_document_access_index_for_document(
                    _repair_document_stub(source_scope, document_id),
                    operation='document_access_repair_delete',
                    settings=settings,
                    force=True,
                )
            else:
                try:
                    source_document = _read_source_document_for_repair(source_scope, document_id)
                except Exception as source_error:
                    if not _is_not_found_error(source_error):
                        raise
                    delete_document_access_index_for_document(
                        _repair_document_stub(source_scope, document_id),
                        operation='document_access_repair_source_missing',
                        settings=settings,
                        force=True,
                    )
                else:
                    sync_document_access_index_for_document(
                        source_document,
                        operation='document_access_repair_sync',
                        settings=settings,
                        force=True,
                    )
            repairs_succeeded += 1
        except Exception as exc:
            repairs_failed += 1
            _mark_repair_document_failed(repair_doc, exc)
            log_event(
                '[DocumentAccessIndex] Projection repair reconciliation failed.',
                extra={
                    'document_id': document_id,
                    'source_scope': source_scope,
                    'operation': operation,
                    'error': str(exc),
                },
                level=logging.WARNING,
                exceptionTraceback=True,
            )

    return {
        'success': repairs_failed == 0,
        'status': 'reconciled' if repairs_failed == 0 else 'reconciled_with_errors',
        'repairs_processed': len(repair_docs),
        'repairs_succeeded': repairs_succeeded,
        'repairs_failed': repairs_failed,
    }


def run_document_access_index_backfill_once(
    settings=None,
    batch_size=None,
    source_scopes=None,
    reset=False,
    force=False,
):
    """Run one resumable batch of document access index backfill work."""
    normalized_settings = get_document_access_index_settings(settings)
    if not normalized_settings.get('container_enabled'):
        return {
            'success': True,
            'status': 'skipped_disabled',
            'processed_count': 0,
            'failed_count': 0,
        }
    if not force and not normalized_settings.get('startup_backfill_enabled'):
        return {
            'success': True,
            'status': 'skipped_disabled',
            'processed_count': 0,
            'failed_count': 0,
        }

    source_scopes = _normalize_source_scopes(source_scopes)
    batch_size = _normalize_positive_int(
        batch_size,
        normalized_settings.get('backfill_batch_size'),
        max_value=DOCUMENT_ACCESS_MAX_BACKFILL_BATCH_SIZE,
    )
    state = None if reset else _read_backfill_state()
    if not state or state.get('type') != DOCUMENT_ACCESS_BACKFILL_STATE_TYPE:
        state = _build_initial_backfill_state(source_scopes)
    else:
        state = copy.deepcopy(state)
        state['source_scopes'] = source_scopes
        state.setdefault('completed_source_scopes', [])
        state.setdefault('continuation_tokens', {})
        state.setdefault('total_documents_processed', 0)
        state.setdefault('total_documents_failed', 0)
        state.setdefault('total_rows_upserted', 0)
        state.setdefault('total_rows_deleted', 0)

    if state.get('status') == 'succeeded' and not reset:
        return {
            'success': True,
            'status': 'skipped_completed',
            'processed_count': 0,
            'failed_count': 0,
            'state': state,
        }

    run_processed = 0
    run_failed = 0
    run_rows_upserted = 0
    run_rows_deleted = 0
    state['status'] = 'running'
    state['last_started_at'] = _utc_now_iso()
    state['last_error'] = None

    try:
        while run_processed < batch_size:
            source_scope = _get_next_backfill_scope(
                source_scopes,
                state.get('completed_source_scopes', []),
            )
            if not source_scope:
                break

            continuation_token = state.get('continuation_tokens', {}).get(source_scope)
            remaining_count = batch_size - run_processed
            page_result = _query_source_document_page(
                source_scope,
                continuation_token=continuation_token,
                max_item_count=remaining_count,
            )
            documents = page_result.get('documents', [])
            next_token = page_result.get('continuation_token')

            if not documents:
                completed_scopes = state.setdefault('completed_source_scopes', [])
                if source_scope not in completed_scopes:
                    completed_scopes.append(source_scope)
                state.setdefault('continuation_tokens', {}).pop(source_scope, None)
                state['current_source_scope'] = None
                continue

            state['current_source_scope'] = source_scope
            for document_item in documents:
                run_processed += 1
                state['total_documents_processed'] = int(state.get('total_documents_processed') or 0) + 1
                try:
                    result = sync_document_access_index_for_document(
                        document_item,
                        operation='document_access_backfill',
                        settings=settings,
                        force=True,
                    )
                except Exception as exc:
                    run_failed += 1
                    state['total_documents_failed'] = int(state.get('total_documents_failed') or 0) + 1
                    try:
                        _record_projection_repair_required(document_item, 'document_access_backfill', exc)
                    except Exception as repair_error:
                        log_event(
                            '[DocumentAccessIndex] Failed to record backfill repair state.',
                            extra={
                                'document_id': (document_item or {}).get('id'),
                                'source_scope': source_scope,
                                'error': str(repair_error),
                            },
                            level=logging.ERROR,
                            exceptionTraceback=True,
                        )
                    log_event(
                        '[DocumentAccessIndex] Backfill projection failed for one source document.',
                        extra={
                            'document_id': (document_item or {}).get('id'),
                            'source_scope': source_scope,
                            'error': str(exc),
                        },
                        level=logging.WARNING,
                        exceptionTraceback=True,
                    )
                    continue
                if result.get('success') is False:
                    run_failed += 1
                    state['total_documents_failed'] = int(state.get('total_documents_failed') or 0) + 1
                    continue
                run_rows_upserted += int(result.get('upserted_count') or 0)
                run_rows_deleted += int(result.get('deleted_count') or 0)
                state['total_rows_upserted'] = (
                    int(state.get('total_rows_upserted') or 0)
                    + int(result.get('upserted_count') or 0)
                )
                state['total_rows_deleted'] = (
                    int(state.get('total_rows_deleted') or 0)
                    + int(result.get('deleted_count') or 0)
                )

            if next_token:
                state.setdefault('continuation_tokens', {})[source_scope] = next_token
                break

            state.setdefault('continuation_tokens', {}).pop(source_scope, None)
            completed_scopes = state.setdefault('completed_source_scopes', [])
            if source_scope not in completed_scopes:
                completed_scopes.append(source_scope)
            state['current_source_scope'] = None

        if _get_next_backfill_scope(source_scopes, state.get('completed_source_scopes', [])):
            state['status'] = 'in_progress'
        elif int(state.get('total_documents_failed') or 0) > 0:
            state['status'] = 'succeeded_with_errors'
        else:
            state['status'] = 'succeeded'

        state.update({
            'last_completed_at': _utc_now_iso(),
            'last_processed_count': run_processed,
            'last_failed_count': run_failed,
            'last_rows_upserted': run_rows_upserted,
            'last_rows_deleted': run_rows_deleted,
        })
        state = _write_backfill_state(state)
        return {
            'success': run_failed == 0,
            'status': state.get('status'),
            'processed_count': run_processed,
            'failed_count': run_failed,
            'rows_upserted': run_rows_upserted,
            'rows_deleted': run_rows_deleted,
            'state': state,
        }
    except Exception as exc:
        state['status'] = 'failed'
        state['last_error'] = str(exc)
        state['last_completed_at'] = _utc_now_iso()
        state = _write_backfill_state(state)
        log_event(
            '[DocumentAccessIndex] Document access index backfill batch failed.',
            extra={'error': str(exc), 'current_source_scope': state.get('current_source_scope')},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return {
            'success': False,
            'status': 'failed',
            'processed_count': run_processed,
            'failed_count': run_failed,
            'error': str(exc),
            'state': state,
        }


def run_document_access_index_backfill_maintenance(
    settings=None,
    run_backfill=None,
    reset=False,
    batch_size=None,
    repair_batch_size=None,
):
    """Run repair reconciliation and one optional backfill batch for app maintenance."""
    normalized_settings = get_document_access_index_settings(settings)
    if run_backfill is None:
        run_backfill = normalized_settings.get('startup_backfill_enabled', False)
    if not run_backfill:
        return {
            'success': True,
            'status': 'skipped_disabled',
            'repair_reconciliation': {
                'success': True,
                'status': 'skipped_disabled',
            },
            'backfill': {
                'success': True,
                'status': 'skipped_disabled',
            },
            'current_status': get_document_access_index_backfill_status(settings=settings),
        }

    repair_result = reconcile_document_access_index_repair_documents(
        settings=settings,
        max_repairs=repair_batch_size,
        force=True,
    )
    backfill_result = run_document_access_index_backfill_once(
        settings=settings,
        batch_size=batch_size,
        reset=reset,
        force=True,
    )
    success = repair_result.get('success') and backfill_result.get('success')
    status = 'completed' if success else 'completed_with_errors'
    return {
        'success': bool(success),
        'status': status,
        'repair_reconciliation': repair_result,
        'backfill': backfill_result,
        'current_status': get_document_access_index_backfill_status(settings=settings),
    }
