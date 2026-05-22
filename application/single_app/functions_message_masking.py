# functions_message_masking.py

"""Helpers for layered chat message masking."""

from copy import deepcopy
from datetime import datetime, timezone
import uuid


MASK_ACTION_MASK_ALL = 'mask_all'
MASK_ACTION_MASK_SELECTION = 'mask_selection'
MASK_ACTION_UNMASK_MESSAGE = 'unmask_message'
MASK_ACTION_CLEAR_ALL = 'clear_all_masks'
MASK_ACTION_LEGACY_UNMASK_ALL = 'unmask_all'

SUPPORTED_MESSAGE_MASK_ACTIONS = {
    MASK_ACTION_MASK_ALL,
    MASK_ACTION_MASK_SELECTION,
    MASK_ACTION_UNMASK_MESSAGE,
    MASK_ACTION_CLEAR_ALL,
    MASK_ACTION_LEGACY_UNMASK_ALL,
}

MASK_METADATA_FIELDS = (
    'masked',
    'masked_ranges',
    'masked_by_user_id',
    'masked_timestamp',
    'masked_by_display_name',
)


def utc_now_iso():
    """Return a timezone-aware UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def resolve_mask_display_name(current_user):
    """Resolve a stable display name from authenticated user information."""
    user = current_user or {}
    return (
        user.get('displayName')
        or user.get('display_name')
        or user.get('email')
        or user.get('userPrincipalName')
        or user.get('user_principal_name')
        or 'Unknown User'
    )


def _safe_int(value):
    if isinstance(value, bool):
        raise ValueError('Mask range values must be numeric')
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('Mask range values must be numeric') from exc


def _normalize_range(range_item, content=None):
    if not isinstance(range_item, dict):
        return None

    start = _safe_int(range_item.get('start'))
    end = _safe_int(range_item.get('end'))
    if content is not None:
        content_length = len(content)
        start = max(0, min(start, content_length))
        end = max(0, min(end, content_length))
    else:
        start = max(0, start)
        end = max(0, end)

    if start >= end:
        return None

    normalized = {
        'id': str(range_item.get('id') or uuid.uuid4()),
        'user_id': str(range_item.get('user_id') or ''),
        'display_name': str(range_item.get('display_name') or 'Unknown User'),
        'start': start,
        'end': end,
        'text': str(range_item.get('text') or ''),
        'timestamp': str(range_item.get('timestamp') or utc_now_iso()),
    }
    if content is not None:
        normalized['text'] = content[start:end]
    return normalized


def _copy_identity_if_earlier(target_range, candidate_range):
    if str(candidate_range.get('timestamp') or '') >= str(target_range.get('timestamp') or ''):
        return

    for key in ('id', 'user_id', 'display_name', 'timestamp'):
        target_range[key] = candidate_range.get(key)


def merge_masked_ranges(ranges, content=None):
    """Merge overlapping or adjacent masked ranges while preserving canonical offsets."""
    normalized_ranges = []
    canonical_content = content if isinstance(content, str) else None
    for range_item in ranges or []:
        normalized = _normalize_range(range_item, canonical_content)
        if normalized:
            normalized_ranges.append(normalized)

    if not normalized_ranges:
        return []

    sorted_ranges = sorted(normalized_ranges, key=lambda item: (item['start'], item['end']))
    merged = [deepcopy(sorted_ranges[0])]

    for current_range in sorted_ranges[1:]:
        last_range = merged[-1]
        if current_range['start'] <= last_range['end']:
            last_range['end'] = max(last_range['end'], current_range['end'])
            if canonical_content is not None:
                last_range['text'] = canonical_content[last_range['start']:last_range['end']]
            else:
                last_range['text'] = f"{last_range.get('text', '')}{current_range.get('text', '')}"
            _copy_identity_if_earlier(last_range, current_range)
            continue

        merged.append(deepcopy(current_range))

    return merged


def remove_masked_content(content, masked_ranges):
    """Remove masked portions from message content using canonical stored offsets."""
    if not masked_ranges or not content:
        return content

    result = str(content)
    sorted_ranges = sorted(masked_ranges, key=lambda item: int(item.get('start', 0) or 0), reverse=True)

    for range_item in sorted_ranges:
        try:
            start = _safe_int(range_item.get('start'))
            end = _safe_int(range_item.get('end'))
        except ValueError:
            continue

        start = max(0, min(start, len(result)))
        end = max(0, min(end, len(result)))
        if start < end:
            result = result[:start] + result[end:]

    return result


def _resolve_selection_offsets(content, selection):
    if not isinstance(selection, dict):
        raise ValueError('Selection details are required')

    start = _safe_int(selection.get('start'))
    end = _safe_int(selection.get('end'))
    selected_text = str(selection.get('text') or '')
    if start < 0 or end <= start:
        raise ValueError('Selection start and end are invalid')

    canonical_content = str(content or '')
    if end <= len(canonical_content):
        canonical_text = canonical_content[start:end]
        if not selected_text or canonical_text == selected_text:
            return start, end, canonical_text

    if selected_text:
        first_index = canonical_content.find(selected_text)
        if first_index >= 0 and canonical_content.find(selected_text, first_index + 1) == -1:
            return first_index, first_index + len(selected_text), selected_text

    raise ValueError('Selection no longer matches the stored message content')


def _build_mask_range(content, selection, user_id, display_name, timestamp):
    start, end, canonical_text = _resolve_selection_offsets(content, selection)
    return {
        'id': str(uuid.uuid4()),
        'user_id': user_id,
        'display_name': display_name,
        'start': start,
        'end': end,
        'text': canonical_text,
        'timestamp': timestamp,
    }


def clear_full_message_mask(metadata):
    """Remove only the full-message mask layer from a metadata object."""
    metadata['masked'] = False
    metadata['masked_by_user_id'] = None
    metadata['masked_timestamp'] = None
    metadata['masked_by_display_name'] = None


def clear_all_message_masks(metadata):
    """Remove both full-message and range mask layers from a metadata object."""
    clear_full_message_mask(metadata)
    metadata['masked_ranges'] = []


def apply_message_mask_action(message_doc, action, selection, user_id, display_name, timestamp=None):
    """Apply a layered mask action to a message document and return updated metadata."""
    normalized_action = str(action or '').strip()
    if normalized_action not in SUPPORTED_MESSAGE_MASK_ACTIONS:
        raise ValueError('Invalid mask action')

    metadata = message_doc.setdefault('metadata', {})
    if not isinstance(metadata, dict):
        metadata = {}
        message_doc['metadata'] = metadata

    effective_timestamp = timestamp or utc_now_iso()
    content = message_doc.get('content', '')

    if normalized_action == MASK_ACTION_MASK_ALL:
        metadata['masked'] = True
        metadata['masked_by_user_id'] = user_id
        metadata['masked_timestamp'] = effective_timestamp
        metadata['masked_by_display_name'] = display_name
    elif normalized_action == MASK_ACTION_UNMASK_MESSAGE:
        clear_full_message_mask(metadata)
    elif normalized_action in (MASK_ACTION_CLEAR_ALL, MASK_ACTION_LEGACY_UNMASK_ALL):
        clear_all_message_masks(metadata)
    elif normalized_action == MASK_ACTION_MASK_SELECTION:
        masked_ranges = list(metadata.get('masked_ranges', []) or [])
        masked_ranges.append(
            _build_mask_range(
                content,
                selection,
                user_id,
                display_name,
                effective_timestamp,
            )
        )
        metadata['masked_ranges'] = merge_masked_ranges(masked_ranges, str(content or ''))

    return metadata


def copy_message_mask_metadata(source_metadata, target_metadata):
    """Copy mask-related metadata fields from one metadata dictionary to another."""
    if not isinstance(source_metadata, dict) or not isinstance(target_metadata, dict):
        return target_metadata

    for field_name in MASK_METADATA_FIELDS:
        if field_name in source_metadata:
            target_metadata[field_name] = deepcopy(source_metadata.get(field_name))

    return target_metadata
