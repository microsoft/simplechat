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

MARKDOWN_FORMATTING_CHARS = {'*', '_', '`'}


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

    try:
        display_start = _safe_int(range_item.get('display_start'))
        display_end = _safe_int(range_item.get('display_end'))
    except ValueError:
        display_start = None
        display_end = None

    if display_start is not None and display_end is not None and display_start >= 0 and display_end > display_start:
        normalized['display_start'] = display_start
        normalized['display_end'] = display_end
        normalized['display_text'] = str(range_item.get('display_text') or range_item.get('text') or '')
    return normalized


def _clear_display_offsets(range_item):
    for field_name in ('display_start', 'display_end', 'display_text'):
        range_item.pop(field_name, None)


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
            _clear_display_offsets(last_range)
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

        projected_offsets = _resolve_selection_offsets_from_projected_markdown(canonical_content, selected_text)
        if projected_offsets:
            return projected_offsets

    raise ValueError('Selection no longer matches the stored message content')


def _is_markdown_table_separator_line(line):
    stripped_line = line.strip()
    return bool(stripped_line and '-' in stripped_line and all(char in '|:- ' for char in stripped_line))


def _project_markdown_to_visible_text(content):
    projected_chars = []
    projected_to_canonical = []
    canonical_offset = 0

    for line in str(content or '').splitlines(keepends=True):
        line_without_newline = line.rstrip('\r\n')
        if _is_markdown_table_separator_line(line_without_newline):
            canonical_offset += len(line)
            continue

        for index, char in enumerate(line):
            original_index = canonical_offset + index
            if char in MARKDOWN_FORMATTING_CHARS:
                continue
            if char == '|':
                projected_chars.append(' ')
                projected_to_canonical.append(original_index)
                continue
            projected_chars.append(char)
            projected_to_canonical.append(original_index)
        canonical_offset += len(line)

    return ''.join(projected_chars), projected_to_canonical


def _normalize_match_text(value):
    normalized_chars = []
    normalized_to_original = []
    last_was_space = True

    for index, char in enumerate(str(value or '')):
        if char.isspace():
            if not last_was_space and normalized_chars:
                normalized_chars.append(' ')
                normalized_to_original.append(index)
            last_was_space = True
            continue

        normalized_chars.append(char)
        normalized_to_original.append(index)
        last_was_space = False

    if normalized_chars and normalized_chars[-1] == ' ':
        normalized_chars.pop()
        normalized_to_original.pop()

    return ''.join(normalized_chars), normalized_to_original


def _expand_markdown_formatting_boundaries(content, start, end):
    canonical_content = str(content or '')
    expanded_start = start
    expanded_end = end

    for marker in ('**', '__'):
        marker_length = len(marker)
        if (
            expanded_start >= marker_length
            and expanded_end + marker_length <= len(canonical_content)
            and canonical_content[expanded_start - marker_length:expanded_start] == marker
            and canonical_content[expanded_end:expanded_end + marker_length] == marker
        ):
            expanded_start -= marker_length
            expanded_end += marker_length
            return expanded_start, expanded_end

    if (
        expanded_start >= 1
        and expanded_end + 1 <= len(canonical_content)
        and canonical_content[expanded_start - 1] == '`'
        and canonical_content[expanded_end:expanded_end + 1] == '`'
    ):
        expanded_start -= 1
        expanded_end += 1

    return expanded_start, expanded_end


def _resolve_selection_offsets_from_projected_markdown(content, selected_text):
    projected_content, projected_to_canonical = _project_markdown_to_visible_text(content)
    normalized_content, normalized_to_projected = _normalize_match_text(projected_content)
    normalized_selection, _ = _normalize_match_text(selected_text)

    if not normalized_content or not normalized_selection:
        return None

    first_index = normalized_content.find(normalized_selection)
    if first_index < 0 or normalized_content.find(normalized_selection, first_index + 1) != -1:
        return None

    projected_start = normalized_to_projected[first_index]
    projected_end = normalized_to_projected[first_index + len(normalized_selection) - 1]
    canonical_start = projected_to_canonical[projected_start]
    canonical_end = projected_to_canonical[projected_end] + 1
    canonical_start, canonical_end = _expand_markdown_formatting_boundaries(
        content,
        canonical_start,
        canonical_end,
    )

    return canonical_start, canonical_end, str(content or '')[canonical_start:canonical_end]


def _get_selection_display_offsets(selection):
    display_start_value = selection.get('display_start', selection.get('start'))
    display_end_value = selection.get('display_end', selection.get('end'))
    display_start = _safe_int(display_start_value)
    display_end = _safe_int(display_end_value)
    if display_start < 0 or display_end <= display_start:
        return None

    return {
        'display_start': display_start,
        'display_end': display_end,
        'display_text': str(selection.get('display_text') or selection.get('text') or ''),
    }


def _build_mask_range(content, selection, user_id, display_name, timestamp):
    start, end, canonical_text = _resolve_selection_offsets(content, selection)
    mask_range = {
        'id': str(uuid.uuid4()),
        'user_id': user_id,
        'display_name': display_name,
        'start': start,
        'end': end,
        'text': canonical_text,
        'timestamp': timestamp,
    }
    display_offsets = _get_selection_display_offsets(selection)
    if display_offsets:
        mask_range.update(display_offsets)
    return mask_range


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
