# functions_group_assignment_ids.py
"""Normalization for administrator-managed group assignment lists.

Several admin capabilities are scoped by a list of SimpleChat group ids: group
workflows, File Sync and file downloads all store one. The stored value has to
tolerate more shapes than it produces, because the server-rendered admin form
round-trips the list through a hidden textarea and older saves left behind
comma-separated text, JSON strings, and JSON strings nested inside JSON strings.

These functions live here rather than in ``functions_settings`` because
``admin_settings_fields`` needs them and cannot import that module: it builds a
Cosmos client at import time through ``config``. ``functions_settings``
re-exports everything below, so existing callers are unaffected.
"""

import json
import uuid

GROUP_WORKFLOW_ALLOWED_GROUP_ID_PARSE_DEPTH_LIMIT = 5


def _iter_group_workflow_allowed_group_id_candidates(value, depth=0):
    """Yield raw assignment candidates from legacy text, JSON, and nested JSON strings."""
    if value is None or depth > GROUP_WORKFLOW_ALLOWED_GROUP_ID_PARSE_DEPTH_LIMIT:
        return

    if isinstance(value, str):
        stripped_value = value.strip()
        if not stripped_value:
            return

        if stripped_value.startswith('[') or stripped_value.startswith('"'):
            try:
                parsed_value = json.loads(stripped_value)
            except (TypeError, ValueError):
                parsed_value = None

            if isinstance(parsed_value, list):
                for candidate in parsed_value:
                    yield from _iter_group_workflow_allowed_group_id_candidates(candidate, depth + 1)
                return

            if isinstance(parsed_value, str) and parsed_value != stripped_value:
                yield from _iter_group_workflow_allowed_group_id_candidates(parsed_value, depth + 1)
                return

        for candidate in stripped_value.replace('\r', '\n').replace(',', '\n').replace(';', '\n').split('\n'):
            yield candidate
        return

    if isinstance(value, (list, tuple, set)):
        for candidate in value:
            yield from _iter_group_workflow_allowed_group_id_candidates(candidate, depth + 1)
        return

    yield value


def normalize_group_workflow_allowed_group_id(value):
    """Return a canonical SimpleChat group id or an empty string for invalid values."""
    group_id = str(value or '').strip()
    if not group_id:
        return ''

    try:
        return str(uuid.UUID(group_id))
    except (AttributeError, TypeError, ValueError):
        return ''


def normalize_group_workflow_allowed_group_ids(value):
    """Normalize group workflow assignment settings into unique group ids."""
    normalized_ids = []
    seen_ids = set()
    for candidate in _iter_group_workflow_allowed_group_id_candidates(value):
        group_id = normalize_group_workflow_allowed_group_id(candidate)
        if not group_id or group_id in seen_ids:
            continue
        normalized_ids.append(group_id)
        seen_ids.add(group_id)
    return normalized_ids
