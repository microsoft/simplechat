# functions_document_citations.py
"""Shared, bootstrap-free document citation formatting and source projection."""

import re
from typing import Any


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


def resolve_citation_location(
    page_number: Any = None,
    chunk_text: Any = None,
    sheet_name: Any = None,
    is_tabular: bool = False,
) -> tuple[str, str]:
    """Return a schema-, sheet-, or page-aware citation location."""
    if sheet_name not in (None, ''):
        return 'Sheet', str(sheet_name)
    normalized_chunk_text = str(chunk_text or '').strip()
    if is_tabular and (
        normalized_chunk_text.startswith('Tabular workbook:')
        or normalized_chunk_text.startswith('Tabular data file:')
    ):
        return 'Location', 'Workbook Schema'
    if page_number is None or page_number == '':
        return 'Page', '1'
    return 'Page', str(page_number)


def build_document_citation(source, location):
    """Project a real source locator; missing locations never become invented page 1."""
    if not isinstance(source, dict) or not isinstance(location, dict):
        return None
    document_id = source.get('document_id')
    citation_id = location.get('chunk_id')
    if not isinstance(document_id, str) or not document_id.strip():
        return None
    if not isinstance(citation_id, str) or not re.fullmatch(r'[A-Za-z0-9_=\-]+', citation_id):
        return None
    page = location.get('page_number')
    if page is None or page == '':
        page = location.get('chunk_sequence')
    sheet = location.get('sheet_name')
    if page in (None, '') and sheet in (None, ''):
        return None
    label, value = resolve_citation_location(page_number=page, sheet_name=sheet)
    file_name = source.get('file_name') or source.get('document_name') or document_id
    # Keep labels within one marker even when a filename resembles citation syntax.
    file_name = re.sub(r'\s+', ' ', str(file_name)).strip()
    file_name = re.sub(r'\(Source:', 'Source:', file_name, flags=re.IGNORECASE)
    file_name = file_name.replace('[#', '[')
    value = re.sub(r'\s+', ' ', value).replace('[#', '[')
    scope = source.get('scope')
    scope_id = source.get('scope_id')
    if isinstance(scope, dict):
        scope, scope_id = scope.get('type'), scope.get('id')
    citation = {
        'source_type': 'document', 'document_id': document_id, 'file_name': file_name,
        'citation_id': citation_id, 'chunk_id': citation_id,
        'page_number': page, 'chunk_sequence': location.get('chunk_sequence'),
        'location_label': label, 'location_value': value,
        'group_id': scope_id if scope == 'group' else None,
        'public_workspace_id': scope_id if scope == 'public' else None,
    }
    if sheet not in (None, ''):
        citation['sheet_name'] = sheet
    citation['citation'] = build_inline_citation_marker(file_name, label, value, citation_id)
    return citation
