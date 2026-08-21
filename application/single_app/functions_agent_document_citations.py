# functions_agent_document_citations.py

"""Derive document citations from agent document-search plugin invocations.

Agents retrieve workspace documents through ``DocumentSearchPlugin``. Those calls are
recorded as agent tool citations, which describe the tool invocation rather than the
documents that were retrieved. This module converts the document payloads carried in
those invocations into the same document citation shape the route-level hybrid search
produces, so agent-discovered documents behave like any other retrieved source.

Derived citations are *sources*, not cited references. They are intentionally not
capped or pre-filtered; ``functions_citation_tracking`` narrows sources down to the
subset a response actually cited.
"""

import json
import logging
import os
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from functions_appinsights import log_event
from functions_citation_tracking import resolve_citation_location

try:
    # config.py builds live Azure clients on import, so it is unavailable to the
    # standalone functional tests that exercise this module. Fall back to the same
    # extension set config defines when it cannot be imported.
    from config import TABULAR_EXTENSIONS
except Exception:
    TABULAR_EXTENSIONS = frozenset({'csv', 'xlsx', 'xls', 'xlsm'})

AGENT_DOCUMENT_CITATION_SOURCE = 'agent_document_search'

DOCUMENT_SEARCH_PLUGIN_NAMES = frozenset({
    'documentsearchplugin',
    'document_search_plugin',
    'document_search',
})

DOCUMENT_SEARCH_RESULT_FUNCTIONS = frozenset({'search_documents'})
DOCUMENT_CHUNK_FUNCTIONS = frozenset({'retrieve_document_chunks'})
DOCUMENT_SUMMARY_FUNCTIONS = frozenset({'summarize_document'})

DOCUMENT_SEARCH_FUNCTIONS = (
    DOCUMENT_SEARCH_RESULT_FUNCTIONS
    | DOCUMENT_CHUNK_FUNCTIONS
    | DOCUMENT_SUMMARY_FUNCTIONS
)

DOCUMENT_SEARCH_CITATION_INSTRUCTIONS = (
    'When you use any excerpt below in your answer, cite it by copying that entry\'s '
    '"citation" value verbatim, including the bracketed reference id. Do not invent, '
    'reformat, or renumber citation values.'
)


def _normalize_name(value: Any) -> str:
    return str(value or '').strip().lower()


def is_document_search_plugin(plugin_name: Any) -> bool:
    """Return True when the plugin name identifies the document search plugin."""
    return _normalize_name(plugin_name) in DOCUMENT_SEARCH_PLUGIN_NAMES


def is_document_search_invocation(plugin_name: Any, function_name: Any) -> bool:
    """Return True when an invocation retrieved workspace documents."""
    return (
        is_document_search_plugin(plugin_name)
        and _normalize_name(function_name) in DOCUMENT_SEARCH_FUNCTIONS
    )


def _is_tabular_file_name(file_name: Any) -> bool:
    normalized_file_name = str(file_name or '').strip().lower()
    if not normalized_file_name:
        return False

    _, extension = os.path.splitext(normalized_file_name)
    return extension.lstrip('.') in TABULAR_EXTENSIONS


def coerce_result_payload(value: Any) -> Optional[Dict[str, Any]]:
    """Return a mapping payload from a plugin result, parsing JSON strings when needed."""
    if isinstance(value, Mapping):
        return dict(value)

    if isinstance(value, str):
        candidate = value.strip()
        if not candidate.startswith('{'):
            return None
        try:
            parsed_value = json.loads(candidate)
        except (TypeError, ValueError):
            return None
        return dict(parsed_value) if isinstance(parsed_value, Mapping) else None

    return None


def build_inline_citation_marker(
    file_name: Any,
    location_label: Any,
    location_value: Any,
    citation_id: Any,
) -> str:
    """Return the literal inline reference the citation tracker can match."""
    normalized_citation_id = str(citation_id or '').strip().lstrip('#').strip()
    if not normalized_citation_id:
        return ''

    normalized_file_name = str(file_name or 'Document').strip() or 'Document'
    normalized_label = str(location_label or 'Page').strip() or 'Page'
    normalized_value = str(location_value or '1').strip() or '1'

    return (
        f'(Source: {normalized_file_name}, {normalized_label}: {normalized_value}) '
        f'[#{normalized_citation_id}]'
    )


def _derive_document_id(result: Mapping[str, Any], citation_id: Any) -> str:
    document_id = str(result.get('document_id') or '').strip()
    if document_id:
        return document_id

    normalized_citation_id = str(citation_id or '').strip()
    if '_' in normalized_citation_id:
        return '_'.join(normalized_citation_id.split('_')[:-1])

    return normalized_citation_id


def _build_citation_record(
    *,
    file_name: Any,
    document_id: Any,
    citation_id: Any,
    page_number: Any,
    sheet_name: Any = None,
    chunk_text: Any = None,
    chunk_id: Any = None,
    chunk_sequence: Any = None,
    score: Any = None,
    group_id: Any = None,
    public_workspace_id: Any = None,
    version: Any = None,
    classification: Any = None,
    plugin_name: Any = None,
    function_name: Any = None,
) -> Dict[str, Any]:
    resolved_file_name = str(file_name or 'Unknown').strip() or 'Unknown'
    location_label, location_value = resolve_citation_location(
        page_number=page_number,
        chunk_text=chunk_text,
        sheet_name=sheet_name,
        is_tabular=_is_tabular_file_name(resolved_file_name),
    )

    return {
        'file_name': resolved_file_name,
        'document_id': str(document_id or '').strip(),
        'citation_id': str(citation_id or '').strip(),
        'page_number': page_number,
        'sheet_name': sheet_name,
        'location_label': location_label,
        'location_value': location_value,
        'chunk_id': chunk_id,
        'chunk_sequence': chunk_sequence,
        'score': score,
        'group_id': group_id,
        'public_workspace_id': public_workspace_id,
        'version': version,
        'classification': classification,
        'source': AGENT_DOCUMENT_CITATION_SOURCE,
        'agent_document_search': True,
        'plugin_name': plugin_name,
        'function_name': function_name,
    }


def _resolve_location_number(*candidate_values):
    """Return the first non-null candidate so a valid sequence of 0 is preserved."""
    for candidate_value in candidate_values:
        if candidate_value is not None and candidate_value != '':
            return candidate_value
    return None


def _build_citation_from_search_result(
    result: Mapping[str, Any],
    plugin_name: Any,
    function_name: Any,
) -> Optional[Dict[str, Any]]:
    citation_id = str(result.get('id') or result.get('citation_id') or '').strip()
    document_id = _derive_document_id(result, citation_id)
    if not citation_id and not document_id:
        return None

    chunk_sequence = result.get('chunk_sequence')
    return _build_citation_record(
        file_name=result.get('file_name') or result.get('title'),
        document_id=document_id,
        citation_id=citation_id or document_id,
        page_number=_resolve_location_number(result.get('page_number'), chunk_sequence),
        sheet_name=result.get('sheet_name'),
        chunk_text=result.get('chunk_text'),
        chunk_id=result.get('chunk_id'),
        chunk_sequence=chunk_sequence,
        score=result.get('score'),
        group_id=result.get('group_id'),
        public_workspace_id=result.get('public_workspace_id'),
        version=result.get('version'),
        classification=result.get('document_classification') or result.get('classification'),
        plugin_name=plugin_name,
        function_name=function_name,
    )


def _build_citations_from_chunk_payload(
    payload: Mapping[str, Any],
    plugin_name: Any,
    function_name: Any,
) -> List[Dict[str, Any]]:
    document_item = payload.get('document') if isinstance(payload.get('document'), Mapping) else {}
    document_id = str(document_item.get('id') or '').strip()
    citations: List[Dict[str, Any]] = []

    for chunk in payload.get('chunks') or []:
        if not isinstance(chunk, Mapping):
            continue

        citation_id = str(chunk.get('id') or '').strip()
        chunk_document_id = str(chunk.get('document_id') or '').strip() or document_id
        if not citation_id and not chunk_document_id:
            continue

        chunk_sequence = chunk.get('chunk_sequence')
        citations.append(_build_citation_record(
            file_name=chunk.get('file_name') or document_item.get('file_name') or document_item.get('title'),
            document_id=chunk_document_id,
            citation_id=citation_id or chunk_document_id,
            page_number=_resolve_location_number(chunk.get('page_number'), chunk_sequence),
            sheet_name=chunk.get('sheet_name'),
            chunk_text=chunk.get('chunk_text'),
            chunk_id=chunk.get('chunk_id'),
            chunk_sequence=chunk_sequence,
            score=chunk.get('score'),
            group_id=chunk.get('group_id') or document_item.get('group_id'),
            public_workspace_id=(
                chunk.get('public_workspace_id')
                or document_item.get('public_workspace_id')
            ),
            version=chunk.get('version') or document_item.get('version'),
            classification=(
                chunk.get('document_classification')
                or document_item.get('document_classification')
            ),
            plugin_name=plugin_name,
            function_name=function_name,
        ))

    return citations


def _build_citation_from_document_payload(
    payload: Mapping[str, Any],
    plugin_name: Any,
    function_name: Any,
) -> Optional[Dict[str, Any]]:
    document_item = payload.get('document') if isinstance(payload.get('document'), Mapping) else {}
    document_id = str(document_item.get('id') or '').strip()
    citation_chunk = payload.get('citation_chunk') if isinstance(payload.get('citation_chunk'), Mapping) else {}
    if not document_id:
        document_id = str(citation_chunk.get('document_id') or '').strip()
    if not document_id:
        return None

    # Prefer a real indexed chunk so the citation resolves. Chunk ids are not always
    # "<document_id>_1" - video chunks are keyed by second and can start at zero - so a
    # synthesized locator is never used when the summary reports its source chunk.
    citation_id = str(citation_chunk.get('id') or '').strip() or document_id
    chunk_sequence = citation_chunk.get('chunk_sequence')

    return _build_citation_record(
        file_name=(
            citation_chunk.get('file_name')
            or document_item.get('file_name')
            or document_item.get('title')
        ),
        document_id=document_id,
        citation_id=citation_id,
        page_number=_resolve_location_number(citation_chunk.get('page_number'), chunk_sequence),
        chunk_id=citation_chunk.get('chunk_id'),
        chunk_sequence=chunk_sequence,
        group_id=document_item.get('group_id'),
        public_workspace_id=document_item.get('public_workspace_id'),
        version=citation_chunk.get('version') or document_item.get('version'),
        classification=(
            citation_chunk.get('document_classification')
            or document_item.get('document_classification')
        ),
        plugin_name=plugin_name,
        function_name=function_name,
    )


def build_document_citations_from_result_payload(
    payload: Any,
    plugin_name: Any = None,
    function_name: Any = None,
) -> List[Dict[str, Any]]:
    """Return document citations derived from one document-search result payload."""
    result_payload = coerce_result_payload(payload)
    if not result_payload or result_payload.get('error'):
        return []

    normalized_function_name = _normalize_name(function_name)

    if normalized_function_name in DOCUMENT_SEARCH_RESULT_FUNCTIONS:
        citations = []
        for result in result_payload.get('results') or []:
            if not isinstance(result, Mapping):
                continue
            citation = _build_citation_from_search_result(result, plugin_name, function_name)
            if citation:
                citations.append(citation)
        return citations

    if normalized_function_name in DOCUMENT_CHUNK_FUNCTIONS:
        return _build_citations_from_chunk_payload(result_payload, plugin_name, function_name)

    if normalized_function_name in DOCUMENT_SUMMARY_FUNCTIONS:
        citation = _build_citation_from_document_payload(result_payload, plugin_name, function_name)
        return [citation] if citation else []

    return []


def _iter_document_search_entries(
    entries: Optional[Iterable[Any]],
    plugin_name_getter,
    function_name_getter,
    result_getter,
    success_getter,
):
    for entry in entries or []:
        if entry is None:
            continue

        plugin_name = plugin_name_getter(entry)
        function_name = function_name_getter(entry)
        if not is_document_search_invocation(plugin_name, function_name):
            continue

        success_value = success_getter(entry)
        if success_value is False:
            continue

        yield plugin_name, function_name, result_getter(entry)


def build_document_citations_from_agent_citations(
    agent_citations: Optional[Iterable[Any]],
) -> List[Dict[str, Any]]:
    """Return document citations derived from agent tool citation records."""
    citations: List[Dict[str, Any]] = []
    entries = _iter_document_search_entries(
        agent_citations,
        lambda entry: entry.get('plugin_name') if isinstance(entry, Mapping) else None,
        lambda entry: entry.get('function_name') if isinstance(entry, Mapping) else None,
        lambda entry: entry.get('function_result') if isinstance(entry, Mapping) else None,
        lambda entry: entry.get('success') if isinstance(entry, Mapping) else None,
    )

    for plugin_name, function_name, result_payload in entries:
        citations.extend(build_document_citations_from_result_payload(
            result_payload,
            plugin_name=plugin_name,
            function_name=function_name,
        ))

    return citations


def build_document_citations_from_invocations(
    invocations: Optional[Iterable[Any]],
) -> List[Dict[str, Any]]:
    """Return document citations derived from raw plugin invocation records."""
    citations: List[Dict[str, Any]] = []
    entries = _iter_document_search_entries(
        invocations,
        lambda entry: getattr(entry, 'plugin_name', None),
        lambda entry: getattr(entry, 'function_name', None),
        lambda entry: getattr(entry, 'result', None),
        lambda entry: getattr(entry, 'success', None),
    )

    for plugin_name, function_name, result_payload in entries:
        citations.extend(build_document_citations_from_result_payload(
            result_payload,
            plugin_name=plugin_name,
            function_name=function_name,
        ))

    return citations


def _build_citation_identity(citation: Mapping[str, Any]) -> Tuple[str, str, str, str]:
    citation_id = str(citation.get('citation_id') or '').strip()
    if citation_id:
        return ('citation_id', citation_id, '', '')

    return (
        'locator',
        str(citation.get('document_id') or '').strip(),
        str(citation.get('chunk_id') or '').strip(),
        str(citation.get('page_number') or '').strip(),
    )


def merge_agent_document_citations(
    target_citations: Optional[List[Dict[str, Any]]],
    derived_citations: Optional[Iterable[Mapping[str, Any]]],
) -> int:
    """Append deduplicated derived citations into ``target_citations`` in place.

    Existing entries always win, so route-level citations keep their original metadata
    when the same chunk was also retrieved by an agent. Returns the number appended.
    """
    if target_citations is None:
        return 0

    seen_identities = {
        _build_citation_identity(citation)
        for citation in target_citations
        if isinstance(citation, Mapping)
    }

    appended_count = 0
    for citation in derived_citations or []:
        if not isinstance(citation, Mapping):
            continue

        identity = _build_citation_identity(citation)
        if identity in seen_identities:
            continue

        seen_identities.add(identity)
        target_citations.append(dict(citation))
        appended_count += 1

    return appended_count


def apply_agent_document_citations(
    hybrid_citations: Optional[List[Dict[str, Any]]],
    agent_citations: Optional[Iterable[Any]] = None,
    sort_key=None,
    conversation_id: Any = None,
    plugin_invocations: Optional[Iterable[Any]] = None,
) -> int:
    """Merge agent document-search results into hybrid citations in place.

    ``plugin_invocations`` lets callers supply raw invocation records in addition to
    agent citation records. Streaming cancellation and error paths need this because
    invocations are only folded into the agent citation list once a stream completes.
    Merging is deduplicated, so passing both sources never double-counts a chunk.

    Returns the number of document citations added, which callers use for capability
    usage metadata and telemetry.
    """
    if hybrid_citations is None:
        return 0

    derived_citations = build_document_citations_from_agent_citations(agent_citations)
    derived_citations.extend(build_document_citations_from_invocations(plugin_invocations))
    if not derived_citations:
        return 0

    appended_count = merge_agent_document_citations(hybrid_citations, derived_citations)
    if appended_count and sort_key:
        hybrid_citations.sort(key=sort_key, reverse=True)

    if appended_count:
        log_event(
            '[AGENT_DOCUMENT_CITATIONS] Added document sources from agent document search',
            extra={
                'conversation_id': conversation_id,
                'derived_citation_count': len(derived_citations),
                'added_citation_count': appended_count,
                'total_document_citation_count': len(hybrid_citations),
            },
            level=logging.INFO,
        )

    return appended_count


def annotate_document_search_payload(
    payload: Any,
    function_name: Any,
) -> Any:
    """Attach ready-to-copy inline citation markers to a document-search payload.

    The markers use the exact format the citation tracker matches, so a model that
    copies them promotes the retrieved document into the cited references for the
    response and into the conversation's used documents.
    """
    if not isinstance(payload, dict) or payload.get('error'):
        return payload

    normalized_function_name = _normalize_name(function_name)
    annotated_count = 0

    if normalized_function_name in DOCUMENT_SEARCH_RESULT_FUNCTIONS:
        for result in payload.get('results') or []:
            if not isinstance(result, dict):
                continue
            citation = _build_citation_from_search_result(result, None, function_name)
            if not citation:
                continue
            marker = build_inline_citation_marker(
                citation.get('file_name'),
                citation.get('location_label'),
                citation.get('location_value'),
                citation.get('citation_id'),
            )
            if marker:
                result['citation'] = marker
                annotated_count += 1

    elif normalized_function_name in DOCUMENT_CHUNK_FUNCTIONS:
        chunk_citations = _build_citations_from_chunk_payload(payload, None, function_name)
        citations_by_id = {
            str(citation.get('citation_id') or ''): citation
            for citation in chunk_citations
        }
        for chunk in payload.get('chunks') or []:
            if not isinstance(chunk, dict):
                continue
            citation = citations_by_id.get(str(chunk.get('id') or ''))
            if not citation:
                continue
            marker = build_inline_citation_marker(
                citation.get('file_name'),
                citation.get('location_label'),
                citation.get('location_value'),
                citation.get('citation_id'),
            )
            if marker:
                chunk['citation'] = marker
                annotated_count += 1

    elif normalized_function_name in DOCUMENT_SUMMARY_FUNCTIONS:
        citation = _build_citation_from_document_payload(payload, None, function_name)
        if citation:
            marker = build_inline_citation_marker(
                citation.get('file_name'),
                citation.get('location_label'),
                citation.get('location_value'),
                citation.get('citation_id'),
            )
            if marker:
                payload['citation'] = marker
                annotated_count += 1

    if annotated_count:
        payload['citation_instructions'] = DOCUMENT_SEARCH_CITATION_INSTRUCTIONS

    return payload
