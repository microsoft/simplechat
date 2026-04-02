# functions_message_artifacts.py
"""Helpers for storing large assistant-side payloads outside primary chat items."""

import json
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple


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


def make_json_serializable(value: Any) -> Any:
    """Convert nested values into JSON-serializable structures."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): make_json_serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [make_json_serializable(item) for item in value]
    return str(value)


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
                merged_citation = deepcopy(raw_citation)
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
    serialized_payload = json.dumps(payload, default=str)
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