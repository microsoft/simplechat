# functions_document_actions.py
"""Shared helpers for backend document actions."""

import copy

from functions_document_analysis import (
    CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS,
    WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS,
    normalize_document_analysis_targets,
)
from functions_search import normalize_search_id_list


DOCUMENT_ACTION_TYPE_NONE = 'none'
DOCUMENT_ACTION_TYPE_ANALYZE = 'analyze'
DOCUMENT_ACTION_TYPE_COMPARISON = 'comparison'
DOCUMENT_ACTION_CONTEXT_CHAT = 'chat'
DOCUMENT_ACTION_CONTEXT_WORKFLOW = 'workflow'
VALID_DOCUMENT_ACTION_TYPES = {
    DOCUMENT_ACTION_TYPE_NONE,
    DOCUMENT_ACTION_TYPE_ANALYZE,
    DOCUMENT_ACTION_TYPE_COMPARISON,
}
DOCUMENT_ACTION_LIMIT_BOUNDS = {
    DOCUMENT_ACTION_CONTEXT_CHAT: {
        'min': 2,
        'max': 300,
    },
    DOCUMENT_ACTION_CONTEXT_WORKFLOW: {
        'min': 2,
        'max': 1000,
    },
}
DEFAULT_DOCUMENT_ACTION_CAPABILITIES = {
    DOCUMENT_ACTION_TYPE_ANALYZE: {
        'enabled': True,
        'chat_max_documents': CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS,
        'workflow_max_documents': WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS,
    },
    DOCUMENT_ACTION_TYPE_COMPARISON: {
        'enabled': True,
        'chat_max_documents': CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS,
        'workflow_max_documents': WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS,
    },
}


def normalize_document_action_type(action_type):
    normalized_type = str(action_type or DOCUMENT_ACTION_TYPE_NONE).strip().lower()
    if normalized_type not in VALID_DOCUMENT_ACTION_TYPES:
        return DOCUMENT_ACTION_TYPE_NONE
    return normalized_type


def _coerce_document_action_limit(value, default_value, execution_context):
    bounds = DOCUMENT_ACTION_LIMIT_BOUNDS.get(execution_context, DOCUMENT_ACTION_LIMIT_BOUNDS[DOCUMENT_ACTION_CONTEXT_CHAT])
    try:
        normalized_value = int(value)
    except (TypeError, ValueError):
        normalized_value = int(default_value)

    return max(bounds['min'], min(bounds['max'], normalized_value))


def get_default_document_action_capabilities():
    return copy.deepcopy(DEFAULT_DOCUMENT_ACTION_CAPABILITIES)


def normalize_document_action_capabilities(settings_or_capabilities=None):
    raw_capabilities = settings_or_capabilities
    if isinstance(settings_or_capabilities, dict) and 'document_action_capabilities' in settings_or_capabilities:
        raw_capabilities = settings_or_capabilities.get('document_action_capabilities')

    raw_capabilities = raw_capabilities if isinstance(raw_capabilities, dict) else {}
    normalized_capabilities = get_default_document_action_capabilities()

    for action_type, default_capability in normalized_capabilities.items():
        raw_capability = raw_capabilities.get(action_type)
        if not isinstance(raw_capability, dict):
            continue

        normalized_capabilities[action_type] = {
            'enabled': bool(raw_capability.get('enabled', default_capability.get('enabled', True))),
            'chat_max_documents': _coerce_document_action_limit(
                raw_capability.get('chat_max_documents'),
                default_capability.get('chat_max_documents', CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS),
                DOCUMENT_ACTION_CONTEXT_CHAT,
            ),
            'workflow_max_documents': _coerce_document_action_limit(
                raw_capability.get('workflow_max_documents'),
                default_capability.get('workflow_max_documents', WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS),
                DOCUMENT_ACTION_CONTEXT_WORKFLOW,
            ),
        }

    return normalized_capabilities


def get_document_action_capability(action_type, settings=None):
    normalized_action_type = normalize_document_action_type(action_type)
    capabilities = normalize_document_action_capabilities(settings)
    default_capabilities = get_default_document_action_capabilities()
    return capabilities.get(normalized_action_type, default_capabilities.get(normalized_action_type, {}))


def is_document_action_enabled(action_type, settings=None):
    normalized_action_type = normalize_document_action_type(action_type)
    if normalized_action_type == DOCUMENT_ACTION_TYPE_NONE:
        return True

    capability = get_document_action_capability(normalized_action_type, settings=settings)
    return bool(capability.get('enabled', False))


def get_enabled_document_action_types(settings=None):
    enabled_action_types = {DOCUMENT_ACTION_TYPE_NONE}
    for action_type in (DOCUMENT_ACTION_TYPE_ANALYZE, DOCUMENT_ACTION_TYPE_COMPARISON):
        if is_document_action_enabled(action_type, settings=settings):
            enabled_action_types.add(action_type)
    return enabled_action_types


def get_document_action_max_documents(action_type, execution_context, settings=None):
    normalized_action_type = normalize_document_action_type(action_type)
    capability = get_document_action_capability(normalized_action_type, settings=settings)
    field_name = 'workflow_max_documents' if execution_context == DOCUMENT_ACTION_CONTEXT_WORKFLOW else 'chat_max_documents'
    default_capability = get_default_document_action_capabilities().get(normalized_action_type, {})
    default_value = default_capability.get(field_name, CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS)
    return _coerce_document_action_limit(capability.get(field_name, default_value), default_value, execution_context)


def get_document_action_max_documents_by_type(execution_context, settings=None):
    return {
        DOCUMENT_ACTION_TYPE_ANALYZE: get_document_action_max_documents(
            DOCUMENT_ACTION_TYPE_ANALYZE,
            execution_context,
            settings=settings,
        ),
        DOCUMENT_ACTION_TYPE_COMPARISON: get_document_action_max_documents(
            DOCUMENT_ACTION_TYPE_COMPARISON,
            execution_context,
            settings=settings,
        ),
    }


def _resolve_max_documents(action_type, max_documents=None, max_documents_by_type=None):
    if isinstance(max_documents_by_type, dict):
        resolved_value = max_documents_by_type.get(action_type)
        if resolved_value is not None:
            return resolved_value
    return max_documents


def _build_document_action_disabled_message(action_type):
    if action_type == DOCUMENT_ACTION_TYPE_ANALYZE:
        return 'Document analysis is currently disabled in admin settings.'
    if action_type == DOCUMENT_ACTION_TYPE_COMPARISON:
        return 'Document comparison is currently disabled in admin settings.'
    return 'The selected document action is currently disabled in admin settings.'


def _build_analyze_action(legacy_analyze=None):
    legacy_analyze = legacy_analyze if isinstance(legacy_analyze, dict) else {}
    if not legacy_analyze.get('enabled'):
        return {}

    return {
        'type': DOCUMENT_ACTION_TYPE_ANALYZE,
        'doc_scope': legacy_analyze.get('doc_scope', 'all'),
        'active_group_ids': legacy_analyze.get('active_group_ids'),
        'active_public_workspace_id': legacy_analyze.get('active_public_workspace_id'),
        'window_unit': legacy_analyze.get('window_unit'),
        'window_size': legacy_analyze.get('window_size'),
        'window_percent': legacy_analyze.get('window_percent'),
        'max_retries_per_window': legacy_analyze.get('max_retries_per_window'),
        'document_ids': legacy_analyze.get('document_ids'),
    }


def normalize_document_action_config(
    action_payload=None,
    existing_action=None,
    legacy_analyze=None,
    max_documents=None,
    max_documents_by_type=None,
    allowed_action_types=None,
):
    action_payload = action_payload if isinstance(action_payload, dict) else {}
    existing_action = existing_action if isinstance(existing_action, dict) else {}
    source_action = action_payload or existing_action or _build_analyze_action(legacy_analyze)
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

    if allowed_action_types is not None:
        normalized_allowed_action_types = {
            normalize_document_action_type(allowed_action_type)
            for allowed_action_type in allowed_action_types
        }
        normalized_allowed_action_types.add(DOCUMENT_ACTION_TYPE_NONE)
        if action_type not in normalized_allowed_action_types:
            raise ValueError(_build_document_action_disabled_message(action_type))

    resolved_max_documents = _resolve_max_documents(
        action_type,
        max_documents=max_documents,
        max_documents_by_type=max_documents_by_type,
    )

    if action_type == DOCUMENT_ACTION_TYPE_ANALYZE:
        normalized_targets = normalize_document_analysis_targets(
            document_ids=source_action.get('document_ids'),
            doc_scope=source_action.get('doc_scope', 'all'),
            active_group_ids=source_action.get('active_group_ids'),
            active_public_workspace_id=source_action.get('active_public_workspace_id'),
            window_unit=source_action.get('window_unit'),
            window_size=source_action.get('window_size'),
            window_percent=source_action.get('window_percent'),
            max_retries_per_window=source_action.get('max_retries_per_window'),
            max_documents=resolved_max_documents,
        )
        normalized_action.update(normalized_targets)
        return normalized_action

    left_candidates = normalize_search_id_list([source_action.get('left_document_id')])
    if not left_candidates:
        raise ValueError('Select one Source document for comparison.')

    left_document_id = left_candidates[0]
    right_document_ids = [
        document_id for document_id in normalize_search_id_list(source_action.get('right_document_ids'))
        if document_id != left_document_id
    ]
    if not right_document_ids:
        raise ValueError('Select one or more Target documents for comparison.')

    normalized_targets = normalize_document_analysis_targets(
        document_ids=[left_document_id, *right_document_ids],
        doc_scope=source_action.get('doc_scope', 'all'),
        active_group_ids=source_action.get('active_group_ids'),
        active_public_workspace_id=source_action.get('active_public_workspace_id'),
        window_unit=source_action.get('window_unit'),
        window_size=source_action.get('window_size'),
        window_percent=source_action.get('window_percent'),
        max_retries_per_window=source_action.get('max_retries_per_window'),
        max_documents=resolved_max_documents,
    )

    normalized_action.update(normalized_targets)
    normalized_action['left_document_id'] = left_document_id
    normalized_action['right_document_ids'] = [
        document_id for document_id in normalized_action.get('document_ids', [])
        if document_id != left_document_id
    ]
    return normalized_action


def get_document_action_config(document_source, max_documents=None, max_documents_by_type=None, allowed_action_types=None):
    document_source = document_source if isinstance(document_source, dict) else {}
    return normalize_document_action_config(
        action_payload=document_source.get('document_action'),
        existing_action=document_source.get('document_action'),
        legacy_analyze=document_source.get('analyze'),
        max_documents=max_documents,
        max_documents_by_type=max_documents_by_type,
        allowed_action_types=allowed_action_types,
    )


def build_analyze_config(action_config=None):
    action_config = action_config if isinstance(action_config, dict) else {}
    if action_config.get('type') != DOCUMENT_ACTION_TYPE_ANALYZE:
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