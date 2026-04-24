# functions_document_actions.py
"""Shared helpers for backend document actions."""

from functions_exhaustive_document_review import normalize_exhaustive_review_targets
from functions_search import normalize_search_id_list


DOCUMENT_ACTION_TYPE_NONE = 'none'
DOCUMENT_ACTION_TYPE_EXHAUSTIVE_REVIEW = 'exhaustive_review'
DOCUMENT_ACTION_TYPE_COMPARISON = 'comparison'
VALID_DOCUMENT_ACTION_TYPES = {
    DOCUMENT_ACTION_TYPE_NONE,
    DOCUMENT_ACTION_TYPE_EXHAUSTIVE_REVIEW,
    DOCUMENT_ACTION_TYPE_COMPARISON,
}


def normalize_document_action_type(action_type):
    normalized_type = str(action_type or DOCUMENT_ACTION_TYPE_NONE).strip().lower()
    if normalized_type not in VALID_DOCUMENT_ACTION_TYPES:
        return DOCUMENT_ACTION_TYPE_NONE
    return normalized_type


def _build_legacy_exhaustive_action(legacy_exhaustive_review=None):
    legacy_exhaustive_review = legacy_exhaustive_review if isinstance(legacy_exhaustive_review, dict) else {}
    if not legacy_exhaustive_review.get('enabled'):
        return {}

    return {
        'type': DOCUMENT_ACTION_TYPE_EXHAUSTIVE_REVIEW,
        'doc_scope': legacy_exhaustive_review.get('doc_scope', 'all'),
        'active_group_ids': legacy_exhaustive_review.get('active_group_ids'),
        'active_public_workspace_id': legacy_exhaustive_review.get('active_public_workspace_id'),
        'window_unit': legacy_exhaustive_review.get('window_unit'),
        'window_size': legacy_exhaustive_review.get('window_size'),
        'window_percent': legacy_exhaustive_review.get('window_percent'),
        'max_retries_per_window': legacy_exhaustive_review.get('max_retries_per_window'),
        'document_ids': legacy_exhaustive_review.get('document_ids'),
    }


def normalize_document_action_config(
    action_payload=None,
    existing_action=None,
    legacy_exhaustive_review=None,
    max_documents=None,
):
    action_payload = action_payload if isinstance(action_payload, dict) else {}
    existing_action = existing_action if isinstance(existing_action, dict) else {}
    source_action = action_payload or existing_action or _build_legacy_exhaustive_action(legacy_exhaustive_review)
    action_type = normalize_document_action_type(source_action.get('type'))

    normalized_action = {
        'type': action_type,
        'doc_scope': 'all',
        'active_group_ids': [],
        'active_public_workspace_id': [],
        'window_unit': 'pages',
        'window_size': None,
        'window_percent': None,
        'max_retries_per_window': 1,
        'document_ids': [],
        'left_document_id': '',
        'right_document_ids': [],
    }
    if action_type == DOCUMENT_ACTION_TYPE_NONE:
        return normalized_action

    if action_type == DOCUMENT_ACTION_TYPE_EXHAUSTIVE_REVIEW:
        normalized_targets = normalize_exhaustive_review_targets(
            document_ids=source_action.get('document_ids'),
            doc_scope=source_action.get('doc_scope', 'all'),
            active_group_ids=source_action.get('active_group_ids'),
            active_public_workspace_id=source_action.get('active_public_workspace_id'),
            window_unit=source_action.get('window_unit'),
            window_size=source_action.get('window_size'),
            window_percent=source_action.get('window_percent'),
            max_retries_per_window=source_action.get('max_retries_per_window'),
            max_documents=max_documents,
        )
        normalized_action.update(normalized_targets)
        return normalized_action

    left_candidates = normalize_search_id_list([source_action.get('left_document_id')])
    if not left_candidates:
        raise ValueError('Select one left-side document for comparison.')

    left_document_id = left_candidates[0]
    right_document_ids = [
        document_id for document_id in normalize_search_id_list(source_action.get('right_document_ids'))
        if document_id != left_document_id
    ]
    if not right_document_ids:
        raise ValueError('Select one or more right-side documents for comparison.')

    normalized_targets = normalize_exhaustive_review_targets(
        document_ids=[left_document_id, *right_document_ids],
        doc_scope=source_action.get('doc_scope', 'all'),
        active_group_ids=source_action.get('active_group_ids'),
        active_public_workspace_id=source_action.get('active_public_workspace_id'),
        window_unit=source_action.get('window_unit'),
        window_size=source_action.get('window_size'),
        window_percent=source_action.get('window_percent'),
        max_retries_per_window=source_action.get('max_retries_per_window'),
        max_documents=max_documents,
    )

    normalized_action.update(normalized_targets)
    normalized_action['left_document_id'] = left_document_id
    normalized_action['right_document_ids'] = [
        document_id for document_id in normalized_action.get('document_ids', [])
        if document_id != left_document_id
    ]
    return normalized_action


def get_document_action_config(document_source, max_documents=None):
    document_source = document_source if isinstance(document_source, dict) else {}
    return normalize_document_action_config(
        action_payload=document_source.get('document_action'),
        existing_action=document_source.get('document_action'),
        legacy_exhaustive_review=document_source.get('exhaustive_review'),
        max_documents=max_documents,
    )


def build_legacy_exhaustive_review_config(action_config=None):
    action_config = action_config if isinstance(action_config, dict) else {}
    if action_config.get('type') != DOCUMENT_ACTION_TYPE_EXHAUSTIVE_REVIEW:
        return {
            'enabled': False,
            'document_ids': [],
            'doc_scope': 'all',
            'active_group_ids': [],
            'active_public_workspace_id': [],
            'window_unit': 'pages',
            'window_size': None,
            'window_percent': None,
            'max_retries_per_window': 1,
        }

    return {
        'enabled': True,
        'document_ids': list(action_config.get('document_ids', [])),
        'doc_scope': action_config.get('doc_scope', 'all'),
        'active_group_ids': list(action_config.get('active_group_ids', [])),
        'active_public_workspace_id': list(action_config.get('active_public_workspace_id', [])),
        'window_unit': action_config.get('window_unit', 'pages'),
        'window_size': action_config.get('window_size'),
        'window_percent': action_config.get('window_percent'),
        'max_retries_per_window': action_config.get('max_retries_per_window', 1),
    }