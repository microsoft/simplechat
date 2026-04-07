"""Shared support menu configuration for user-facing latest features."""

from copy import deepcopy


_SUPPORT_LATEST_FEATURE_CATALOG = [
    {
        'id': 'guided_tutorials',
        'title': 'Guided Tutorials',
        'icon': 'bi-signpost-split',
        'summary': 'Step-by-step walkthroughs help users discover core chat, workspace, and onboarding flows faster.',
        'details': 'Guided Tutorials add clearer in-product guidance so new and returning users can find important workflows without relying on separate documentation.',
        'image': 'images/features/guided_tutorials_chat.png',
        'image_alt': 'Guided tutorials feature screenshot',
    },
    {
        'id': 'background_chat',
        'title': 'Background Chat',
        'icon': 'bi-bell',
        'summary': 'Long-running chat requests can finish in the background while users continue working elsewhere in the app.',
        'details': 'Background Chat improves resilience for longer generations by notifying users when work completes instead of forcing them to stay on one screen.',
        'image': 'images/features/background_completion_notifications-01.png',
        'image_alt': 'Background chat notification screenshot',
    },
    {
        'id': 'gpt_selection',
        'title': 'GPT Selection',
        'icon': 'bi-cpu',
        'summary': 'Teams can expose better model-selection options so users can choose the best experience for a task.',
        'details': 'Recent model-selection improvements make endpoint and model choices easier to understand when multiple AI options are available.',
        'image': 'images/features/model_selection_multi_endpoint_admin_placeholder.svg',
        'image_alt': 'GPT selection placeholder screenshot',
    },
    {
        'id': 'tabular_analysis',
        'title': 'Tabular Analysis',
        'icon': 'bi-table',
        'summary': 'Spreadsheet and table workflows continue to improve for exploration, filtering, and grounded follow-up questions.',
        'details': 'Tabular Analysis keeps expanding the app\'s ability to reason over rows, columns, and multi-file datasets with clearer grounded answers.',
        'image': None,
        'image_alt': '',
    },
    {
        'id': 'citation_improvements',
        'title': 'Citation Improvements',
        'icon': 'bi-journal-text',
        'summary': 'Enhanced citations give users better source traceability, document previews, and history-aware grounding.',
        'details': 'Citation Improvements help users inspect where answers came from and navigate supporting material with less friction.',
        'image': 'images/features/citation_improvements_history_replay_placeholder.svg',
        'image_alt': 'Citation improvements placeholder screenshot',
    },
    {
        'id': 'document_versioning',
        'title': 'Document Versioning',
        'icon': 'bi-files',
        'summary': 'Document revision visibility has improved so users can work with the right version of shared content.',
        'details': 'Document Versioning reduces confusion by making it easier to understand current versus historical document revisions.',
        'image': 'images/features/document_revision_workspace_placeholder.svg',
        'image_alt': 'Document versioning placeholder screenshot',
    },
    {
        'id': 'summaries_export',
        'title': 'Summaries and Export',
        'icon': 'bi-file-earmark-arrow-down',
        'summary': 'Conversation summaries and export workflows continue to expand for reporting and follow-up sharing.',
        'details': 'Summaries and Export features make it easier to capture, reuse, and share the important parts of a chat session.',
        'image': None,
        'image_alt': '',
    },
    {
        'id': 'agent_operations',
        'title': 'Agent Operations',
        'icon': 'bi-grid',
        'summary': 'Agent creation, organization, and operational controls keep getting smoother for advanced scenarios.',
        'details': 'Agent Operations updates improve how teams browse, manage, and reason about reusable AI assistants.',
        'image': None,
        'image_alt': '',
    },
    {
        'id': 'ai_transparency',
        'title': 'AI Transparency',
        'icon': 'bi-stars',
        'summary': 'Thought and reasoning transparency options help users better understand what the assistant is doing.',
        'details': 'AI Transparency work adds safer, clearer visibility into intermediate reasoning and background work where teams choose to expose it.',
        'image': None,
        'image_alt': '',
    },
    {
        'id': 'deployment',
        'title': 'Deployment',
        'icon': 'bi-hdd-rack',
        'summary': 'Deployment guidance and diagnostics keep improving so admins can roll out changes with less guesswork.',
        'details': 'Deployment updates focus on making configuration, startup validation, and operational guidance easier to follow.',
        'image': 'images/features/gunicorn_startup_guidance.png',
        'image_alt': 'Deployment guidance screenshot',
    },
    {
        'id': 'redis_key_vault',
        'title': 'Redis and Key Vault',
        'icon': 'bi-key',
        'summary': 'Caching and secret-management setup guidance has expanded for more secure and predictable operations.',
        'details': 'Redis and Key Vault improvements make it easier for teams to configure caching and secret storage patterns correctly.',
        'image': 'images/features/redis_key_vault.png',
        'image_alt': 'Redis and Key Vault screenshot',
    },
]


def get_support_latest_feature_catalog():
    """Return a copy of the support latest-features catalog."""
    return deepcopy(_SUPPORT_LATEST_FEATURE_CATALOG)


def get_default_support_latest_features_visibility():
    """Return default visibility for each user-facing latest feature."""
    return {item['id']: True for item in _SUPPORT_LATEST_FEATURE_CATALOG}


def normalize_support_latest_features_visibility(raw_visibility):
    """Normalize persisted latest-feature visibility to the current catalog."""
    defaults = get_default_support_latest_features_visibility()
    if not isinstance(raw_visibility, dict):
        return defaults

    normalized = defaults.copy()
    for feature_id in defaults:
        if feature_id in raw_visibility:
            normalized[feature_id] = bool(raw_visibility.get(feature_id))

    return normalized


def get_visible_support_latest_features(settings):
    """Return the subset of latest-feature entries enabled for end users."""
    normalized_visibility = normalize_support_latest_features_visibility(
        (settings or {}).get('support_latest_features_visibility', {})
    )
    visible_items = []

    for item in _SUPPORT_LATEST_FEATURE_CATALOG:
        if normalized_visibility.get(item['id'], True):
            visible_items.append(deepcopy(item))

    return visible_items


def has_visible_support_latest_features(settings):
    """Return True when at least one latest-feature entry is enabled for users."""
    normalized_visibility = normalize_support_latest_features_visibility(
        (settings or {}).get('support_latest_features_visibility', {})
    )
    return any(normalized_visibility.values())