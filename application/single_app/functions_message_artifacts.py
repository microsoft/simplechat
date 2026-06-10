# functions_message_artifacts.py
"""Helpers for storing large assistant-side payloads outside primary chat items."""

import json
import math
import numbers
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from functions_azure_maps import refresh_azure_maps_citation_payload


ASSISTANT_ARTIFACT_ROLE = 'assistant_artifact'
ASSISTANT_ARTIFACT_CHUNK_ROLE = 'assistant_artifact_chunk'
ASSISTANT_ARTIFACT_KIND_AGENT_CITATION = 'agent_citation'
ASSISTANT_ARTIFACT_CHUNK_SIZE = 180000
COMPACT_VALUE_MAX_STRING = 400
COMPACT_VALUE_MAX_LIST_ITEMS = 5
COMPACT_VALUE_MAX_DICT_KEYS = 12
COMPACT_VALUE_MAX_DEPTH = 3
TABULAR_ARGUMENT_EXCLUDE_KEYS = {
    'conversation_id',
    'group_id',
    'public_workspace_id',
    'source',
    'user_id',
}


def is_assistant_artifact_role(role: Optional[str]) -> bool:
    """Return True for auxiliary assistant artifact records stored in messages."""
    return role in {ASSISTANT_ARTIFACT_ROLE, ASSISTANT_ARTIFACT_CHUNK_ROLE}


def filter_assistant_artifact_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return only primary conversation items, excluding assistant artifacts and chunks."""
    return [item for item in items or [] if not is_assistant_artifact_role(item.get('role'))]


def _normalize_json_scalar(value: Any) -> Any:
    """Normalize scalar values into JSON-safe primitives."""
    if hasattr(value, 'item') and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass

    if value is None:
        return None

    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')

    if isinstance(value, bool):
        return value

    if isinstance(value, numbers.Integral):
        return int(value)

    if isinstance(value, numbers.Real):
        numeric_value = float(value)
        if not math.isfinite(numeric_value):
            return None
        return numeric_value

    if hasattr(value, 'isoformat') and not isinstance(value, str):
        try:
            return value.isoformat()
        except TypeError:
            pass

    return value


def make_json_serializable(value: Any) -> Any:
    """Convert nested values into JSON-serializable structures."""
    value = _normalize_json_scalar(value)

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): make_json_serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [make_json_serializable(item) for item in value]
    return str(value)


def build_agent_citation_tool_label(
    plugin_name: str,
    function_name: str,
    function_arguments: Any = None,
    function_result: Any = None,
) -> str:
    """Return a user-facing label for agent tool citations."""
    normalized_plugin_name = str(plugin_name or '').strip()
    normalized_function_name = str(function_name or '').strip()
    fallback_label = '.'.join(part for part in [normalized_plugin_name, normalized_function_name] if part)
    if not fallback_label:
        return 'Tool invocation'

    parsed_arguments = _parse_json_if_possible(function_arguments)
    parsed_result = _parse_json_if_possible(function_result)

    if normalized_plugin_name == 'AzureMapsOpenLayersPlugin' and normalized_function_name == 'create_map_visualization':
        title = _first_non_empty(
            _get_mapping_value(parsed_arguments, 'title'),
            _get_mapping_value(_get_mapping_value(parsed_result, 'map_payload'), 'title'),
        )
        return _format_tool_label('Map', title, fallback_label=fallback_label)

    image_gallery_payload = _get_image_gallery_payload(parsed_result)
    if image_gallery_payload:
        title = _first_non_empty(
            _get_mapping_value(image_gallery_payload, 'title'),
            _get_mapping_value(parsed_arguments, 'title'),
            _get_mapping_value(parsed_result, 'title'),
        )
        return _format_tool_label('Image gallery', title, fallback_label=fallback_label)

    video_gallery_payload = _get_video_gallery_payload(parsed_result)
    if video_gallery_payload:
        title = _first_non_empty(
            _get_mapping_value(video_gallery_payload, 'title'),
            _get_mapping_value(parsed_arguments, 'title'),
            _get_mapping_value(parsed_result, 'title'),
        )
        return _format_tool_label('Video gallery', title, fallback_label=fallback_label)

    if _has_image_result(parsed_result):
        title = _first_non_empty(
            _get_mapping_value(parsed_result, 'title'),
            _get_mapping_value(parsed_arguments, 'title'),
            _get_mapping_value(parsed_result, 'summary'),
        )
        return _format_tool_label('Image', title, fallback_label=fallback_label)

    if _has_video_result(parsed_result):
        title = _first_non_empty(
            _get_mapping_value(parsed_result, 'title'),
            _get_mapping_value(parsed_arguments, 'title'),
            _get_mapping_value(parsed_result, 'summary'),
        )
        return _format_tool_label('Video', title, fallback_label=fallback_label)

    if normalized_plugin_name == 'SimpleChatPlugin':
        simplechat_label = _build_simplechat_tool_label(
            normalized_function_name,
            parsed_arguments,
            parsed_result,
        )
        if simplechat_label:
            return simplechat_label

    if normalized_plugin_name == 'MSGraphPlugin':
        msgraph_label = _build_msgraph_tool_label(
            normalized_function_name,
            parsed_arguments,
            parsed_result,
        )
        if msgraph_label:
            return msgraph_label

    return fallback_label


def _build_simplechat_tool_label(function_name: str, arguments: Any, result: Any) -> str:
    conversation_payload = _get_mapping_value(result, 'conversation')
    group_payload = _get_mapping_value(result, 'group')
    detail = ''

    if function_name == 'create_group':
        detail = _first_non_empty(
            _get_mapping_value(arguments, 'name'),
            _get_mapping_value(group_payload, 'name'),
        )
        return _format_tool_label('Group workspace', detail, fallback_label='SimpleChatPlugin.create_group')

    if function_name == 'add_user_to_group':
        detail = _first_non_empty(
            _get_mapping_value(arguments, 'display_name'),
            _get_mapping_value(arguments, 'email'),
            _get_mapping_value(arguments, 'user_identifier'),
        )
        return _format_tool_label('Group member', detail, fallback_label='SimpleChatPlugin.add_user_to_group')

    if function_name == 'create_group_conversation':
        detail = _first_non_empty(
            _get_mapping_value(arguments, 'title'),
            _get_mapping_value(conversation_payload, 'title'),
        )
        return _format_tool_label('Group conversation', detail, fallback_label='SimpleChatPlugin.create_group_conversation')

    if function_name == 'create_personal_conversation':
        detail = _first_non_empty(
            _get_mapping_value(arguments, 'title'),
            _get_mapping_value(conversation_payload, 'title'),
        )
        return _format_tool_label('Personal conversation', detail, fallback_label='SimpleChatPlugin.create_personal_conversation')

    if function_name == 'create_personal_collaboration_conversation':
        detail = _first_non_empty(
            _get_mapping_value(arguments, 'title'),
            _get_mapping_value(conversation_payload, 'title'),
        )
        return _format_tool_label('Personal collaboration', detail, fallback_label='SimpleChatPlugin.create_personal_collaboration_conversation')

    if function_name == 'invite_group_conversation_members':
        detail = _first_non_empty(_get_mapping_value(conversation_payload, 'title'))
        return _format_tool_label('Conversation participants', detail, fallback_label='SimpleChatPlugin.invite_group_conversation_members')

    if function_name == 'upload_markdown_document':
        detail = _first_non_empty(
            _get_mapping_value(arguments, 'file_name'),
            _get_mapping_value(result, 'file_name'),
            _get_mapping_value(_get_mapping_value(result, 'document'), 'file_name'),
        )
        return _format_tool_label('Markdown file', detail, fallback_label='SimpleChatPlugin.upload_markdown_document')

    if function_name == 'upload_word_document':
        detail = _first_non_empty(
            _get_mapping_value(arguments, 'file_name'),
            _get_mapping_value(result, 'file_name'),
            _get_mapping_value(_get_mapping_value(result, 'document'), 'file_name'),
        )
        return _format_tool_label('Word file', detail, fallback_label='SimpleChatPlugin.upload_word_document')

    if function_name == 'upload_powerpoint_document':
        detail = _first_non_empty(
            _get_mapping_value(arguments, 'file_name'),
            _get_mapping_value(result, 'file_name'),
            _get_mapping_value(_get_mapping_value(result, 'document'), 'file_name'),
        )
        return _format_tool_label('PowerPoint file', detail, fallback_label='SimpleChatPlugin.upload_powerpoint_document')

    if function_name == 'create_personal_workflow':
        detail = _first_non_empty(
            _get_mapping_value(arguments, 'name'),
            _get_mapping_value(_get_mapping_value(result, 'workflow'), 'name'),
        )
        return _format_tool_label('Workflow', detail, fallback_label='SimpleChatPlugin.create_personal_workflow')

    if function_name == 'add_conversation_message':
        detail = _first_non_empty(_get_mapping_value(conversation_payload, 'title'))
        return _format_tool_label('Conversation message', detail, fallback_label='SimpleChatPlugin.add_conversation_message')

    if function_name == 'make_group_inactive':
        detail = _first_non_empty(_get_mapping_value(group_payload, 'name'))
        return _format_tool_label('Group status update', detail, fallback_label='SimpleChatPlugin.make_group_inactive')

    return ''


def _build_msgraph_tool_label(function_name: str, arguments: Any, result: Any) -> str:
    if function_name == 'create_calendar_invite':
        teams_meeting_requested = bool(
            _get_mapping_value(arguments, 'make_teams_meeting')
            or _get_mapping_value(result, 'teams_meeting_requested')
            or _get_mapping_value(result, 'join_url')
            or _get_mapping_value(_get_mapping_value(result, 'onlineMeeting'), 'joinUrl')
        )
        detail = _first_non_empty(
            _get_mapping_value(arguments, 'subject'),
            _get_mapping_value(result, 'subject'),
        )
        base_label = 'Teams meeting' if teams_meeting_requested else 'Calendar invite'
        return _format_tool_label(base_label, detail, fallback_label='MSGraphPlugin.create_calendar_invite')

    if function_name == 'get_my_messages':
        return 'Mail messages'

    if function_name == 'mark_message_as_read':
        return 'Mail status update'

    if function_name == 'send_mail':
        detail = _first_non_empty(
            _get_mapping_value(arguments, 'subject'),
            _get_mapping_value(result, 'subject'),
            _get_mapping_value(result, 'mail_send_status'),
        )
        return _format_tool_label('Mail message', detail, fallback_label='MSGraphPlugin.send_mail')

    if function_name in {'search_users', 'get_user_by_email'}:
        detail = _first_non_empty(
            _get_mapping_value(arguments, 'query'),
            _get_mapping_value(arguments, 'email'),
        )
        return _format_tool_label('User lookup', detail, fallback_label=f'MSGraphPlugin.{function_name}')

    return ''


def _format_tool_label(base_label: str, detail: str = '', fallback_label: str = '') -> str:
    normalized_base = str(base_label or '').strip()
    normalized_detail = str(detail or '').strip()
    if normalized_base and normalized_detail:
        return f'{normalized_base}: {normalized_detail}'
    if normalized_base:
        return normalized_base
    return str(fallback_label or 'Tool invocation').strip() or 'Tool invocation'


def _first_non_empty(*values: Any) -> str:
    for value in values:
        normalized = str(value or '').strip()
        if normalized:
            return normalized
    return ''


def _get_mapping_value(candidate: Any, key: str) -> Any:
    if isinstance(candidate, dict):
        return candidate.get(key)
    return None


def _get_image_gallery_payload(candidate: Any) -> Any:
    if not isinstance(candidate, dict):
        return None

    image_gallery_payload = _get_mapping_value(candidate, 'image_gallery')
    if isinstance(image_gallery_payload, dict):
        items = _get_mapping_value(image_gallery_payload, 'items')
        if isinstance(items, list) and items:
            return image_gallery_payload

    candidate_items = _get_mapping_value(candidate, 'items')
    if isinstance(candidate_items, list) and candidate_items:
        return candidate

    candidate_images = _get_mapping_value(candidate, 'images')
    if isinstance(candidate_images, list) and candidate_images:
        return candidate

    candidate_image_urls = _get_mapping_value(candidate, 'image_urls')
    if isinstance(candidate_image_urls, list) and candidate_image_urls:
        return candidate

    return None


def _get_video_gallery_payload(candidate: Any) -> Any:
    if not isinstance(candidate, dict):
        return None

    video_gallery_payload = _get_mapping_value(candidate, 'video_gallery')
    if isinstance(video_gallery_payload, dict):
        items = _get_mapping_value(video_gallery_payload, 'items')
        if isinstance(items, list) and items:
            return video_gallery_payload

    candidate_items = _get_mapping_value(candidate, 'items')
    if isinstance(candidate_items, list) and candidate_items:
        return candidate

    candidate_videos = _get_mapping_value(candidate, 'videos')
    if isinstance(candidate_videos, list) and candidate_videos:
        return candidate

    candidate_video_urls = _get_mapping_value(candidate, 'video_urls')
    if isinstance(candidate_video_urls, list) and candidate_video_urls:
        return candidate

    return None


def _has_image_result(candidate: Any) -> bool:
    if not isinstance(candidate, dict):
        return False

    image_url = _get_mapping_value(candidate, 'image_url')
    if isinstance(image_url, str) and image_url.strip():
        return True

    if isinstance(image_url, dict) and str(image_url.get('url') or '').strip():
        return True

    mime_type = str(_get_mapping_value(candidate, 'mime') or '').strip().lower()
    if mime_type.startswith('image/'):
        return True

    result_type = str(_get_mapping_value(candidate, 'type') or '').strip().lower()
    return result_type == 'image_url'


def _has_video_result(candidate: Any) -> bool:
    if not isinstance(candidate, dict):
        return False

    video_url = _get_mapping_value(candidate, 'video_url')
    if isinstance(video_url, str) and video_url.strip():
        return True

    if isinstance(video_url, dict) and str(video_url.get('url') or '').strip():
        return True

    mime_type = str(_get_mapping_value(candidate, 'mime') or '').strip().lower()
    if mime_type.startswith('video/'):
        return True

    result_type = str(_get_mapping_value(candidate, 'type') or '').strip().lower()
    return result_type == 'video_url'


def build_agent_citation_artifact_documents(
    conversation_id: str,
    assistant_message_id: str,
    agent_citations: List[Dict[str, Any]],
    created_timestamp: str,
    user_info: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return compact citations plus auxiliary message records for full raw payloads."""
    compact_citations: List[Dict[str, Any]] = []
    artifact_docs: List[Dict[str, Any]] = []

    for index, citation in enumerate(agent_citations or [], start=1):
        serializable_citation = make_json_serializable(citation)
        artifact_id = f"{assistant_message_id}_artifact_{index}"

        compact_citations.append(
            build_compact_agent_citation(serializable_citation, artifact_id=artifact_id)
        )
        artifact_docs.extend(
            _build_artifact_documents(
                conversation_id=conversation_id,
                assistant_message_id=assistant_message_id,
                artifact_id=artifact_id,
                artifact_kind=ASSISTANT_ARTIFACT_KIND_AGENT_CITATION,
                payload={
                    'schema_version': 1,
                    'artifact_kind': ASSISTANT_ARTIFACT_KIND_AGENT_CITATION,
                    'citation': serializable_citation,
                },
                created_timestamp=created_timestamp,
                artifact_index=index,
                user_info=user_info,
                citation=serializable_citation if isinstance(serializable_citation, dict) else None,
            )
        )

    return compact_citations, artifact_docs


def build_message_artifact_payload_map(raw_messages: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Reassemble assistant artifact records into a payload map keyed by artifact id."""
    artifact_messages: Dict[str, Dict[str, Any]] = {}
    artifact_chunks: Dict[str, Dict[int, str]] = {}

    for message in raw_messages or []:
        role = message.get('role')
        if role == ASSISTANT_ARTIFACT_ROLE:
            artifact_messages[message.get('id')] = message
        elif role == ASSISTANT_ARTIFACT_CHUNK_ROLE:
            parent_id = message.get('parent_message_id')
            if not parent_id:
                continue
            artifact_chunks.setdefault(parent_id, {})[
                int((message.get('metadata') or {}).get('chunk_index', 0))
            ] = str(message.get('content', ''))

    artifact_payloads: Dict[str, Dict[str, Any]] = {}
    for artifact_id, artifact_message in artifact_messages.items():
        content = str(artifact_message.get('content', ''))
        metadata = artifact_message.get('metadata', {}) or {}

        if metadata.get('is_chunked'):
            total_chunks = int(metadata.get('total_chunks', 1) or 1)
            chunk_map = artifact_chunks.get(artifact_id, {})
            rebuilt_chunks = [content]
            for chunk_index in range(1, total_chunks):
                rebuilt_chunks.append(chunk_map.get(chunk_index, ''))
            content = ''.join(rebuilt_chunks)

        try:
            parsed = json.loads(content)
        except Exception:
            continue

        if isinstance(parsed, dict):
            artifact_payloads[artifact_id] = parsed

    return artifact_payloads


def hydrate_agent_citations_from_artifacts(
    messages: List[Dict[str, Any]],
    artifact_payload_map: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return messages with agent citations inflated from assistant artifact records."""
    hydrated_messages: List[Dict[str, Any]] = []

    for message in messages or []:
        hydrated_message = deepcopy(message)
        agent_citations = hydrated_message.get('agent_citations')
        if not isinstance(agent_citations, list) or not agent_citations:
            hydrated_messages.append(hydrated_message)
            continue

        hydrated_citations = []
        for citation in agent_citations:
            if not isinstance(citation, dict):
                hydrated_citations.append(citation)
                continue

            artifact_id = citation.get('artifact_id')
            artifact_payload = artifact_payload_map.get(str(artifact_id or ''))
            raw_citation = artifact_payload.get('citation') if isinstance(artifact_payload, dict) else None
            if isinstance(raw_citation, dict):
                merged_citation = refresh_azure_maps_citation_payload(deepcopy(raw_citation))
                merged_citation.setdefault('artifact_id', artifact_id)
                merged_citation.setdefault('raw_payload_externalized', True)
                hydrated_citations.append(merged_citation)
            else:
                hydrated_citations.append(citation)

        hydrated_message['agent_citations'] = hydrated_citations
        hydrated_messages.append(hydrated_message)

    return hydrated_messages


def build_compact_agent_citation(citation: Any, artifact_id: Optional[str] = None) -> Dict[str, Any]:
    """Build a compact citation record suitable for storing on the assistant message."""
    if not isinstance(citation, dict):
        compact_value = _compact_value(citation)
        compact_citation = {
            'tool_name': 'Tool invocation',
            'function_result': compact_value,
        }
        if artifact_id:
            compact_citation['artifact_id'] = artifact_id
            compact_citation['raw_payload_externalized'] = True
        return compact_citation

    function_name = str(citation.get('function_name') or '').strip()
    plugin_name = str(citation.get('plugin_name') or '').strip()
    compact_citation = {
        'tool_name': citation.get('tool_name') or function_name or 'Tool invocation',
        'function_name': citation.get('function_name'),
        'plugin_name': citation.get('plugin_name'),
        'duration_ms': citation.get('duration_ms'),
        'timestamp': citation.get('timestamp'),
        'success': citation.get('success'),
        'error_message': _compact_value(citation.get('error_message')),
        'function_arguments': _compact_function_arguments(
            citation.get('function_arguments'),
            function_name=function_name,
            plugin_name=plugin_name,
        ),
        'function_result': _compact_function_result(
            citation.get('function_result'),
            function_name=function_name,
            plugin_name=plugin_name,
        ),
    }
    if artifact_id:
        compact_citation['artifact_id'] = artifact_id
        compact_citation['raw_payload_externalized'] = True
    return _remove_empty_values(compact_citation)


def _build_artifact_documents(
    conversation_id: str,
    assistant_message_id: str,
    artifact_id: str,
    artifact_kind: str,
    payload: Dict[str, Any],
    created_timestamp: str,
    artifact_index: int,
    user_info: Optional[Dict[str, Any]] = None,
    citation: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    serialized_payload = json.dumps(make_json_serializable(payload), default=str, allow_nan=False)
    chunks = [
        serialized_payload[index:index + ASSISTANT_ARTIFACT_CHUNK_SIZE]
        for index in range(0, len(serialized_payload), ASSISTANT_ARTIFACT_CHUNK_SIZE)
    ] or ['']

    base_metadata = {
        'artifact_type': artifact_kind,
        'artifact_index': artifact_index,
        'is_chunked': len(chunks) > 1,
        'total_chunks': len(chunks),
        'chunk_index': 0,
        'root_message_id': assistant_message_id,
        'user_info': user_info,
    }
    if citation:
        base_metadata.update({
            'tool_name': citation.get('tool_name'),
            'function_name': citation.get('function_name'),
            'plugin_name': citation.get('plugin_name'),
        })

    main_doc = {
        'id': artifact_id,
        'conversation_id': conversation_id,
        'role': ASSISTANT_ARTIFACT_ROLE,
        'content': chunks[0],
        'parent_message_id': assistant_message_id,
        'artifact_kind': artifact_kind,
        'timestamp': created_timestamp,
        'metadata': base_metadata,
    }

    docs = [main_doc]
    for chunk_index in range(1, len(chunks)):
        docs.append({
            'id': f"{artifact_id}_chunk_{chunk_index}",
            'conversation_id': conversation_id,
            'role': ASSISTANT_ARTIFACT_CHUNK_ROLE,
            'content': chunks[chunk_index],
            'parent_message_id': artifact_id,
            'artifact_kind': artifact_kind,
            'timestamp': created_timestamp,
            'metadata': {
                'artifact_type': artifact_kind,
                'artifact_index': artifact_index,
                'is_chunk': True,
                'chunk_index': chunk_index,
                'total_chunks': len(chunks),
                'parent_message_id': artifact_id,
                'root_message_id': assistant_message_id,
                'user_info': user_info,
            },
        })

    return docs


def _compact_function_arguments(arguments: Any, function_name: str, plugin_name: str) -> Any:
    parsed_arguments = _parse_json_if_possible(arguments)
    if not isinstance(parsed_arguments, dict):
        return _compact_value(parsed_arguments)

    if _is_tabular_citation(function_name, plugin_name):
        filtered_arguments = {
            key: value
            for key, value in parsed_arguments.items()
            if key not in TABULAR_ARGUMENT_EXCLUDE_KEYS
        }
        return _compact_value(filtered_arguments)

    return _compact_value(parsed_arguments)


def _compact_function_result(result: Any, function_name: str, plugin_name: str) -> Any:
    parsed_result = _parse_json_if_possible(result)
    if _is_tabular_citation(function_name, plugin_name):
        return _compact_tabular_result_payload(function_name, parsed_result)
    return _compact_value(parsed_result)


def _compact_tabular_result_payload(function_name: str, payload: Any) -> Any:
    if not isinstance(payload, dict):
        return _compact_value(payload)

    summary: Dict[str, Any] = {}
    preferred_keys = [
        'filename',
        'selected_sheet',
        'source_sheet',
        'source_value_column',
        'target_sheet',
        'target_match_column',
        'lookup_column',
        'lookup_value',
        'target_column',
        'match_operator',
        'column',
        'operation',
        'group_by',
        'aggregate_column',
        'date_component',
        'query_expression',
        'filter_applied',
        'source_filter_applied',
        'target_filter_applied',
        'normalize_match',
        'row_count',
        'rows_scanned',
        'distinct_count',
        'returned_values',
        'values',
        'source_cohort_size',
        'matched_source_value_count',
        'unmatched_source_value_count',
        'source_value_match_counts_returned',
        'source_value_match_counts_limited',
        'matched_target_row_count',
        'total_matches',
        'returned_rows',
        'groups',
        'value',
        'result',
        'highest_group',
        'highest_value',
        'lowest_group',
        'lowest_value',
        'error',
        'candidate_sheets',
        'sheet_count',
    ]

    for key in preferred_keys:
        if key in payload:
            summary[key] = _compact_value(payload.get(key), depth=1)

    if isinstance(payload.get('top_results'), dict):
        summary['top_results'] = _compact_value(payload.get('top_results'), depth=1)

    if isinstance(payload.get('details'), list):
        summary['details'] = _compact_value(payload.get('details'), depth=1)

    source_value_match_counts = payload.get('source_value_match_counts')
    if isinstance(source_value_match_counts, list) and source_value_match_counts:
        summary['source_value_match_counts'] = [
            _compact_value(item, depth=1)
            for item in source_value_match_counts[:10]
        ]
        summary['source_value_match_counts_sample_limited'] = len(source_value_match_counts) > 10

    data_rows = payload.get('data')
    if isinstance(data_rows, list) and data_rows:
        summary['sample_rows'] = [_compact_value(row, depth=1) for row in data_rows[:3]]
        summary['sample_rows_limited'] = len(data_rows) > 3 or int(payload.get('returned_rows') or 0) > 3

    if function_name == 'lookup_value' and 'value' not in summary and isinstance(data_rows, list) and len(data_rows) == 1:
        summary['sample_rows'] = [_compact_value(data_rows[0], depth=1)]

    return _remove_empty_values(summary)


def _compact_value(value: Any, depth: int = 0) -> Any:
    value = _normalize_json_scalar(value)

    if value is None or isinstance(value, (int, float, bool)):
        return value

    if isinstance(value, str):
        if len(value) <= COMPACT_VALUE_MAX_STRING:
            return value
        return f"{value[:COMPACT_VALUE_MAX_STRING]}... [truncated {len(value) - COMPACT_VALUE_MAX_STRING} chars]"

    if depth >= COMPACT_VALUE_MAX_DEPTH:
        if isinstance(value, dict):
            return f"<dict with {len(value)} keys>"
        if isinstance(value, list):
            return f"<list with {len(value)} items>"
        return str(value)

    if isinstance(value, list):
        compact_items = [_compact_value(item, depth=depth + 1) for item in value[:COMPACT_VALUE_MAX_LIST_ITEMS]]
        if len(value) > COMPACT_VALUE_MAX_LIST_ITEMS:
            compact_items.append({'remaining_items': len(value) - COMPACT_VALUE_MAX_LIST_ITEMS})
        return compact_items

    if isinstance(value, dict):
        compact_mapping: Dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= COMPACT_VALUE_MAX_DICT_KEYS:
                compact_mapping['remaining_keys'] = len(value) - COMPACT_VALUE_MAX_DICT_KEYS
                break
            compact_mapping[str(key)] = _compact_value(item, depth=depth + 1)
        return compact_mapping

    return str(value)


def _parse_json_if_possible(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    trimmed = value.strip()
    if not trimmed or trimmed[0] not in '{[':
        return value

    try:
        return json.loads(trimmed)
    except Exception:
        return value


def _is_tabular_citation(function_name: str, plugin_name: str) -> bool:
    return plugin_name == 'TabularProcessingPlugin' or function_name in {
        'aggregate_column',
        'count_rows',
        'count_rows_by_related_values',
        'describe_tabular_file',
        'filter_rows',
        'filter_rows_by_related_values',
        'get_distinct_values',
        'group_by_aggregate',
        'group_by_datetime_component',
        'lookup_value',
        'query_tabular_data',
    }


def _remove_empty_values(mapping: Dict[str, Any]) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {}
    for key, value in mapping.items():
        if value in (None, '', [], {}):
            continue
        cleaned[key] = value
    return cleaned