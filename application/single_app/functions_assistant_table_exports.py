# functions_assistant_table_exports.py
"""Helpers for turning assistant-rendered tables into downloadable CSV exports."""

import csv
import io
import re
from datetime import datetime
from typing import Any, Dict, List, Optional


ASSISTANT_TABLE_EXPORT_PREVIEW_ROWS = 3

TABLE_EXPORT_REQUEST_MARKERS = (
    'turn that into a csv',
    'turn these into a csv',
    'turn this into a csv',
    'turn it into a csv',
    'turn that into csv',
    'turn these into csv',
    'turn this into csv',
    'turn it into csv',
    'convert that to a csv',
    'convert these to a csv',
    'convert this to a csv',
    'convert it to a csv',
    'convert that to csv',
    'convert these to csv',
    'convert this to csv',
    'convert it to csv',
    'format that as a csv',
    'format these as a csv',
    'format this as a csv',
    'format it as a csv',
    'format that as csv',
    'format these as csv',
    'format this as csv',
    'format it as csv',
    'put that into a csv',
    'put these into a csv',
    'put this into a csv',
    'put it into a csv',
    'put that in a csv',
    'put these in a csv',
    'put this in a csv',
    'put it in a csv',
    'export csv',
    'export as csv',
    'export to csv',
    'generate csv',
    'generate a csv',
    'build csv',
    'build a csv',
    'prepare csv',
    'prepare a csv',
    'turn that into a table',
    'turn these into a table',
    'turn this into a table',
    'turn it into a table',
    'convert that to a table',
    'convert these to a table',
    'convert this to a table',
    'convert it to a table',
    'format that as a table',
    'format these as a table',
    'format this as a table',
    'format it as a table',
    'put that into a table',
    'put these into a table',
    'put that in a table',
    'put these in a table',
    'put this into a table',
    'put it into a table',
    'put this in a table',
    'put it in a table',
    'make that a table',
    'make these a table',
    'make this a table',
    'make it a table',
    'make a table',
    'create a table',
    'create table',
    'build a table',
    'generate a table',
    'prepare a table',
    'table for me',
    'in table format',
    'download table',
    'table file',
    'spreadsheet',
    'csv file',
    'download csv',
    'save csv',
    'make a csv',
    'make csv',
    'create a csv',
    'create csv',
)


def assistant_table_export_requested(user_question: str) -> bool:
    """Return True when the user asked for table-shaped output or a CSV export."""
    normalized_question = re.sub(r'\s+', ' ', str(user_question or '').strip().casefold())
    if not normalized_question:
        return False

    return any(marker in normalized_question for marker in TABLE_EXPORT_REQUEST_MARKERS)


def build_assistant_table_csv_export(user_question: str, assistant_content: str) -> Optional[Dict[str, Any]]:
    """Build CSV export metadata from the largest table found in the assistant response."""
    if not assistant_table_export_requested(user_question):
        return None

    table_rows = extract_assistant_table_entries(assistant_content)
    if not table_rows:
        return None

    generated_file_name = _build_assistant_table_export_file_name()
    return {
        'file_name': generated_file_name,
        'file_content': build_assistant_table_csv(table_rows),
        'output_format': 'csv',
        'row_count': len(table_rows),
        'preview_rows': table_rows[:ASSISTANT_TABLE_EXPORT_PREVIEW_ROWS],
        'summary': (
            f"Prepared a CSV export with {len(table_rows)} row(s) from the table "
            'in the assistant response.'
        ),
    }


def extract_assistant_table_entries(assistant_content: str) -> List[Dict[str, str]]:
    """Extract table rows from Markdown pipe tables or tab-separated assistant output."""
    normalized_content = str(assistant_content or '').replace('\r\n', '\n').replace('\r', '\n')
    if not normalized_content.strip():
        return []

    candidates = [
        _extract_markdown_table_entries(normalized_content),
        _extract_tab_separated_table_entries(normalized_content),
    ]
    return max(candidates, key=len, default=[])


def build_assistant_table_csv(table_rows: List[Dict[str, Any]]) -> str:
    """Serialize extracted table rows to CSV while preserving column order."""
    ordered_columns = []
    seen_columns = set()
    for table_row in table_rows or []:
        if not isinstance(table_row, dict):
            continue
        for column_name in table_row.keys():
            normalized_column_name = str(column_name or '').strip()
            if not normalized_column_name or normalized_column_name in seen_columns:
                continue
            seen_columns.add(normalized_column_name)
            ordered_columns.append(normalized_column_name)

    if not ordered_columns:
        ordered_columns = ['value']

    output_buffer = io.StringIO()
    writer = csv.DictWriter(output_buffer, fieldnames=ordered_columns, extrasaction='ignore')
    writer.writeheader()
    for table_row in table_rows or []:
        serialized_row = {}
        if isinstance(table_row, dict):
            for column_name in ordered_columns:
                serialized_row[column_name] = _serialize_table_cell(table_row.get(column_name))
        writer.writerow(serialized_row)
    return output_buffer.getvalue()


def _extract_markdown_table_entries(content: str) -> List[Dict[str, str]]:
    lines = content.split('\n')
    best_entries = []
    index = 0

    while index < len(lines):
        if not _is_markdown_table_line(lines[index]):
            index += 1
            continue

        table_block = []
        while index < len(lines) and _is_markdown_table_line(lines[index]):
            table_block.append(lines[index])
            index += 1

        block_entries = _parse_markdown_table_block(table_block)
        if len(block_entries) > len(best_entries):
            best_entries = block_entries

    return best_entries


def _extract_tab_separated_table_entries(content: str) -> List[Dict[str, str]]:
    lines = content.split('\n')
    best_entries = []
    index = 0

    while index < len(lines):
        if not _is_tab_separated_table_line(lines[index]):
            index += 1
            continue

        table_block = []
        while index < len(lines) and _is_tab_separated_table_line(lines[index]):
            table_block.append(lines[index])
            index += 1

        block_entries = _parse_delimited_table_block(table_block, '\t')
        if len(block_entries) > len(best_entries):
            best_entries = block_entries

    return best_entries


def _parse_markdown_table_block(table_block: List[str]) -> List[Dict[str, str]]:
    split_rows = [
        _split_markdown_table_line(line)
        for line in table_block
        if _is_markdown_table_line(line)
    ]
    split_rows = [row for row in split_rows if len(row) >= 2]
    if len(split_rows) < 2:
        return []

    separator_index = next(
        (index for index, row in enumerate(split_rows[1:], start=1) if _is_markdown_separator_row(row)),
        None,
    )
    if separator_index is not None:
        header_cells = split_rows[separator_index - 1]
        data_rows = [row for row in split_rows[separator_index + 1:] if not _is_markdown_separator_row(row)]
    else:
        header_cells = split_rows[0]
        data_rows = split_rows[1:]

    return _build_table_entries(header_cells, data_rows)


def _parse_delimited_table_block(table_block: List[str], delimiter: str) -> List[Dict[str, str]]:
    split_rows = [
        [_clean_table_cell(cell) for cell in line.strip().split(delimiter)]
        for line in table_block
        if delimiter in line
    ]
    split_rows = [row for row in split_rows if len(row) >= 2]
    if len(split_rows) < 2:
        return []

    return _build_table_entries(split_rows[0], split_rows[1:])


def _build_table_entries(header_cells: List[str], data_rows: List[List[str]]) -> List[Dict[str, str]]:
    headers = _build_unique_headers(header_cells)
    if len(headers) < 2:
        return []

    entries = []
    for data_row in data_rows or []:
        normalized_row = _coerce_row_length(data_row, len(headers))
        if not any(str(cell or '').strip() for cell in normalized_row):
            continue
        entries.append({
            header: _clean_table_cell(normalized_row[index])
            for index, header in enumerate(headers)
        })

    return entries


def _is_markdown_table_line(line: str) -> bool:
    stripped_line = str(line or '').strip()
    if not stripped_line or stripped_line.startswith('```') or '|' not in stripped_line:
        return False

    return len(_split_markdown_table_line(stripped_line)) >= 2


def _is_tab_separated_table_line(line: str) -> bool:
    stripped_line = str(line or '').strip()
    if not stripped_line or '\t' not in stripped_line:
        return False

    return len([cell for cell in stripped_line.split('\t') if cell.strip()]) >= 2


def _split_markdown_table_line(line: str) -> List[str]:
    stripped_line = str(line or '').strip()
    if stripped_line.startswith('|'):
        stripped_line = stripped_line[1:]
    if stripped_line.endswith('|') and not stripped_line.endswith('\\|'):
        stripped_line = stripped_line[:-1]

    cells = []
    current_cell = []
    index = 0
    while index < len(stripped_line):
        character = stripped_line[index]
        if character == '\\' and index + 1 < len(stripped_line) and stripped_line[index + 1] == '|':
            current_cell.append('|')
            index += 2
            continue
        if character == '|':
            cells.append(_clean_table_cell(''.join(current_cell)))
            current_cell = []
        else:
            current_cell.append(character)
        index += 1

    cells.append(_clean_table_cell(''.join(current_cell)))
    return cells


def _is_markdown_separator_row(row: List[str]) -> bool:
    if not row:
        return False

    return all(re.fullmatch(r':?-{3,}:?', str(cell or '').replace(' ', '')) for cell in row)


def _build_unique_headers(header_cells: List[str]) -> List[str]:
    headers = []
    seen_headers = {}
    for index, header_cell in enumerate(header_cells or []):
        header = _clean_table_cell(header_cell) or f'Column {index + 1}'
        normalized_header = header.casefold()
        occurrence_count = seen_headers.get(normalized_header, 0)
        seen_headers[normalized_header] = occurrence_count + 1
        if occurrence_count:
            header = f'{header} {occurrence_count + 1}'
        headers.append(header)
    return headers


def _coerce_row_length(row: List[str], target_length: int) -> List[str]:
    normalized_row = list(row or [])
    if len(normalized_row) > target_length and target_length > 0:
        normalized_row = normalized_row[:target_length - 1] + [' | '.join(normalized_row[target_length - 1:])]
    if len(normalized_row) < target_length:
        normalized_row.extend([''] * (target_length - len(normalized_row)))
    return normalized_row


def _clean_table_cell(value: Any) -> str:
    cleaned = str(value or '').strip()
    cleaned = re.sub(r'<br\s*/?>', ' ', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    for marker in ('**', '__', '`'):
        if cleaned.startswith(marker) and cleaned.endswith(marker) and len(cleaned) >= len(marker) * 2:
            cleaned = cleaned[len(marker):-len(marker)].strip()
    return cleaned


def _serialize_table_cell(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        return str(value)
    return str(value)


def _build_assistant_table_export_file_name() -> str:
    timestamp_suffix = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    base_name = 'assistant_table'
    return f'{base_name}_generated_{timestamp_suffix}.csv'
