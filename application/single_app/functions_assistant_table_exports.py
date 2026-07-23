# functions_assistant_table_exports.py
"""Helpers for turning assistant-rendered tables into downloadable CSV exports."""

import csv
import io
import re
from datetime import datetime
from typing import Any, Dict, List, Optional


ASSISTANT_TABLE_EXPORT_PREVIEW_ROWS = 3
CSV_FENCE_LANGUAGES = {'', 'csv', 'md', 'markdown', 'plaintext', 'text', 'text/csv', 'txt'}
CSV_OUTPUT_REQUEST_PATTERNS = (
    re.compile(
        r'\b(?:build|create|download|export|generate|make|prepare|save)\b'
        r'.{0,120}\b(?:a\s+)?(?:(?:single|combined|one)\s+)?csv(?:\s+(?:file|format|output))?\b'
    ),
    re.compile(
        r'\b(?:respond|return|provide|output)\b'
        r'(?:(?!\bfrom\b).){0,80}\b(?:as|in|to\s+)?(?:a\s+)?(?:(?:single|combined|one)\s+)?csv\b'
    ),
    re.compile(
        r'\b(?:convert|format|put|turn)\b.{0,80}\b(?:as|in|into|to)\s+(?:a\s+)?(?:(?:single|combined|one)\s+)?csv\b'
    ),
    re.compile(r'\b(?:get|give)\s+(?:me\s+)?(?:a|the|one)\s+(?:(?:single|combined)\s+)?csv\b'),
    re.compile(
        r'\b(?:need|want)\s+(?:(?:a|the|one)\s+)?(?:direct\s+)?(?:(?:single|combined)\s+)?csv'
        r'(?:\s+(?:file|format|output))?\b'
    ),
    re.compile(
        r'\b(?:need|want)\b.{0,40}\b(?:results?|output|answer|response|fields?|rows?|data|this|that|it)\b'
        r'.{0,40}\b(?:as|in)\s+(?:(?:single|combined|one)\s+)?csv\b'
    ),
    re.compile(r'\b(?:single|combined|one)\s+csv(?:\s+(?:file|format|output))?\b'),
    re.compile(r'\bcsv\s+(?:output|version)\b'),
    re.compile(r'^\s*(?:a\s+)?csv\s+file\s*(?:,?\s*please)?[.!?]?\s*$'),
    re.compile(
        r'\b(?:build|create|download|export|generate|make|prepare|save|turn)\b'
        r'.{0,80}\bspreadsheet\b'
    ),
)
CSV_PROSE_PREFIXES = (
    'below ',
    'csv data',
    'for clarity',
    'for context',
    'here are ',
    'here is ',
    'i extracted ',
    'i found ',
    'in summary',
    'sure ',
    'the following ',
    'the requested ',
    'the export ',
    'this csv ',
    'this export ',
    'your csv ',
)
SIGNED_NUMBER_PATTERN = re.compile(
    r'[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?',
    flags=re.IGNORECASE,
)

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
    'download csv',
    'save csv',
    'make a csv',
    'make csv',
    'create a csv',
    'create csv',
    'csv version',
)


CSV_EXPLICIT_ROW_SCHEMA_PATTERNS = (
    re.compile(r'\b(?:one|a|each)\s+(?:row|record|line|entry|object)\s+(?:per|for|of)\b'),
    re.compile(r'\b(?:one|a|each)\s+(?:file|document|source|record|item)\s+per\s+row\b'),
    re.compile(r'\b(?:columns?|fields?)\s*(?::|=|are|should|must|include|with)\b'),
    re.compile(r'\b(?:include|with|using)\s+(?:the\s+)?(?:columns?|fields?)\b'),
)

def assistant_table_export_requested(user_question: str) -> bool:
    """Return True when the user asked for table-shaped output or a CSV export."""
    normalized_question = re.sub(r'\s+', ' ', str(user_question or '').strip().casefold())
    if not normalized_question:
        return False

    csv_markers = tuple(marker for marker in TABLE_EXPORT_REQUEST_MARKERS if 'csv' in marker)
    table_markers = tuple(marker for marker in TABLE_EXPORT_REQUEST_MARKERS if 'csv' not in marker)
    question_clauses = [
        clause.strip()
        for clause in re.split(r'[;.!?]+', normalized_question)
        if clause.strip()
    ]

    for question_clause in question_clauses:
        if 'csv' not in question_clause:
            continue
        csv_request_negated = bool(re.search(
            r"\b(?:do\s+not|don't|dont|never)\b.{0,80}\bcsv\b"
            r'|\b(?:not|no|without)\s+(?:a\s+)?csv\b',
            question_clause,
        ))
        if csv_request_negated:
            continue
        if any(marker in question_clause for marker in csv_markers):
            return True
        if any(pattern.search(question_clause) for pattern in CSV_OUTPUT_REQUEST_PATTERNS):
            return True

    return (
        any(marker in normalized_question for marker in table_markers)
        or any(
            pattern.search(normalized_question)
            for pattern in CSV_OUTPUT_REQUEST_PATTERNS
            if 'spreadsheet' in pattern.pattern
        )
    )


def build_csv_output_clarification_guidance(user_question: str) -> str:
    """Return model guidance for a CSV request that may need one schema clarification."""
    if not assistant_table_export_requested(user_question):
        return ''

    normalized_question = re.sub(r'\s+', ' ', str(user_question or '').strip().casefold())
    if any(pattern.search(normalized_question) for pattern in CSV_EXPLICIT_ROW_SCHEMA_PATTERNS):
        return (
            'The user explicitly specified CSV row or column structure. Preserve that structure, '
            'produce valid structured rows, and do not ask a clarification unless the requested '
            'evidence itself is contradictory.'
        )

    return (
        'The user requested a CSV artifact. If the authorized evidence and request do not establish '
        'one stable row unit and column schema, ask exactly one concise clarification before generating '
        'a file: whether each row should represent files, documents, or extracted records, and which '
        'columns to include. Do not create an empty or guessed CSV. If the schema is clear from the '
        'request or evidence, generate valid structured rows directly. If this conversation already '
        'contains that clarification, use the user\'s latest answer instead of asking again.'
    )


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


def has_generated_tabular_csv_output(generated_outputs: List[Dict[str, Any]]) -> bool:
    """Return whether a tabular CSV result already suppresses a duplicate table export."""
    for generated_output in generated_outputs or []:
        if not isinstance(generated_output, dict):
            continue

        capability = str(generated_output.get('capability') or '').strip().lower()
        if generated_output.get('suppress_assistant_table_export') and (
            not capability or capability == 'tabular'
        ):
            return True
        output_format = str(generated_output.get('output_format') or '').strip().lower()
        file_name = str(generated_output.get('file_name') or '').strip().lower()
        if (output_format == 'csv' or file_name.endswith('.csv')) and (
            not capability or capability == 'tabular'
        ):
            return True

    return False


def extract_assistant_table_entries(assistant_content: str) -> List[Dict[str, str]]:
    """Extract table rows from Markdown, tab-separated, or CSV assistant output."""
    normalized_content = str(assistant_content or '').replace('\r\n', '\n').replace('\r', '\n')
    if not normalized_content.strip():
        return []

    fenced_csv_rows = _extract_fenced_comma_separated_table_entries(normalized_content)
    if fenced_csv_rows:
        return fenced_csv_rows

    candidates = [
        _extract_markdown_table_entries(normalized_content),
        _extract_tab_separated_table_entries(normalized_content),
        _extract_comma_separated_table_entries(normalized_content),
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

    safe_columns = build_safe_csv_headers(ordered_columns)

    output_buffer = io.StringIO()
    writer = csv.DictWriter(output_buffer, fieldnames=safe_columns, extrasaction='ignore')
    writer.writeheader()
    for table_row in table_rows or []:
        serialized_row = {}
        if isinstance(table_row, dict):
            for source_column, safe_column in zip(ordered_columns, safe_columns):
                serialized_row[safe_column] = _serialize_table_cell(table_row.get(source_column))
        writer.writerow(serialized_row)
    return output_buffer.getvalue()


def build_safe_csv_headers(header_cells: List[Any]) -> List[str]:
    """Return non-empty, formula-safe, unique CSV headers in source order."""
    headers = []
    seen_headers = set()
    for index, header_cell in enumerate(header_cells or []):
        base_header = neutralize_csv_spreadsheet_formula(_clean_table_cell(header_cell)) or f'Column {index + 1}'
        header = base_header
        occurrence_count = 2
        while header.casefold() in seen_headers:
            header = f'{base_header} {occurrence_count}'
            occurrence_count += 1
        seen_headers.add(header.casefold())
        headers.append(header)
    return headers


def neutralize_csv_spreadsheet_formula(value: Any) -> str:
    """Prefix spreadsheet formula-like text while preserving signed numbers."""
    serialized_value = '' if value is None else str(value)
    if _spreadsheet_formula_candidate(serialized_value):
        return f"'{serialized_value}"
    return serialized_value


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


def _extract_comma_separated_table_entries(content: str) -> List[Dict[str, str]]:
    fenced_candidates = []
    unfenced_sections = []
    previous_end = 0
    fence_pattern = re.compile(
        r'```[ \t]*(?P<language>[^\n`]*)\n(?P<body>.*?)```',
        flags=re.IGNORECASE | re.DOTALL,
    )

    for fence_match in fence_pattern.finditer(content):
        unfenced_sections.append(content[previous_end:fence_match.start()])
        language = str(fence_match.group('language') or '').strip().casefold()
        if language in CSV_FENCE_LANGUAGES:
            fenced_candidates.extend(_parse_csv_table_candidates(fence_match.group('body'), trusted=True))
        previous_end = fence_match.end()
    unfenced_sections.append(content[previous_end:])

    if fenced_candidates:
        return max(fenced_candidates, key=len, default=[])

    candidates = []
    for section in unfenced_sections:
        candidates.extend(_parse_csv_table_candidates(section, trusted=False))

    return max(candidates, key=len, default=[])


def _extract_fenced_comma_separated_table_entries(content: str) -> List[Dict[str, str]]:
    explicit_csv_candidates = []
    generic_fenced_candidates = []
    fence_pattern = re.compile(
        r'```[ \t]*(?P<language>[^\n`]*)\n(?P<body>.*?)```',
        flags=re.IGNORECASE | re.DOTALL,
    )
    for fence_match in fence_pattern.finditer(content):
        language = str(fence_match.group('language') or '').strip().casefold()
        if language in CSV_FENCE_LANGUAGES:
            parsed_candidates = _parse_csv_table_candidates(fence_match.group('body'), trusted=True)
            if language in {'csv', 'text/csv'}:
                explicit_csv_candidates.extend(parsed_candidates)
            else:
                generic_fenced_candidates.extend(parsed_candidates)
    if explicit_csv_candidates:
        return max(explicit_csv_candidates, key=len, default=[])
    return max(generic_fenced_candidates, key=len, default=[])


def _parse_csv_table_candidates(content: str, trusted: bool = False) -> List[List[Dict[str, str]]]:
    if ',' not in str(content or ''):
        return []

    try:
        parsed_rows = list(csv.reader(io.StringIO(content), strict=True))
    except csv.Error:
        return []

    candidates = []
    current_rows = []
    current_width = None
    for parsed_row in parsed_rows:
        if not trusted and _is_csv_source_citation_row(parsed_row):
            candidate_rows = _trim_trailing_csv_narration_rows(current_rows)
            if len(candidate_rows) >= 2:
                candidates.append(_build_csv_table_entries(candidate_rows, trusted=trusted))
            current_rows = []
            current_width = None
            continue

        row_width = len(parsed_row)
        if row_width < 2:
            if len(current_rows) >= 2:
                candidates.append(_build_csv_table_entries(current_rows, trusted=trusted))
            current_rows = []
            current_width = None
            continue

        if current_width is not None and row_width != current_width:
            if len(current_rows) >= 2:
                candidates.append(_build_csv_table_entries(current_rows, trusted=trusted))
            current_rows = []

        current_rows.append(parsed_row)
        current_width = row_width

    if len(current_rows) >= 2:
        candidates.append(_build_csv_table_entries(current_rows, trusted=trusted))

    return [candidate for candidate in candidates if candidate]


def _build_csv_table_entries(parsed_rows: List[List[str]], trusted: bool = False) -> List[Dict[str, str]]:
    if len(parsed_rows) < 2:
        return []

    if trusted:
        header_index = 0
    else:
        header_index = next(
            (
                row_index
                for row_index, parsed_row in enumerate(parsed_rows[:-1])
                if _is_likely_csv_header_row(parsed_row)
            ),
            None,
        )
    if header_index is None:
        return []

    table_rows = parsed_rows[header_index:]
    headers = _build_unique_headers(table_rows[0])
    if len(headers) < 2:
        return []

    entries = []
    for parsed_row in table_rows[1:]:
        if not trusted and _is_csv_source_citation_row(parsed_row):
            break
        normalized_row = _coerce_row_length(parsed_row, len(headers))
        if not any(str(cell or '').strip() for cell in normalized_row):
            continue
        entries.append({
            header: _clean_csv_cell(normalized_row[index])
            for index, header in enumerate(headers)
        })
    return entries


def _is_likely_csv_header_row(parsed_row: List[str]) -> bool:
    cleaned_cells = [_clean_csv_cell(cell) for cell in parsed_row]
    if len(cleaned_cells) < 2 or any(not cell for cell in cleaned_cells):
        return False

    if _is_likely_csv_preamble_row(parsed_row) or _is_csv_source_citation_row(parsed_row):
        return False

    return all('\n' not in cell for cell in cleaned_cells)


def _is_likely_csv_discourse_row(parsed_row: List[str]) -> bool:
    if not parsed_row:
        return False

    first_cell = _clean_csv_cell(parsed_row[0]).casefold()
    return first_cell.startswith(CSV_PROSE_PREFIXES)


def _is_likely_csv_preamble_row(parsed_row: List[str]) -> bool:
    if _is_likely_csv_discourse_row(parsed_row):
        return True

    cleaned_cells = [_clean_csv_cell(cell) for cell in parsed_row]
    combined_text = ', '.join(cell for cell in cleaned_cells if cell)
    word_count = len(re.findall(r"\b[\w'-]+\b", combined_text))
    return (
        len(cleaned_cells) == 2
        and word_count >= 5
        and cleaned_cells[-1].rstrip().endswith(('.', '!'))
        and not any(re.search(r'\d', cell) for cell in cleaned_cells)
    )


def _trim_trailing_csv_narration_rows(parsed_rows: List[List[str]]) -> List[List[str]]:
    trimmed_rows = list(parsed_rows or [])
    while len(trimmed_rows) > 1 and _is_likely_csv_trailing_narration_row(trimmed_rows[-1]):
        trimmed_rows.pop()
    return trimmed_rows


def _is_likely_csv_trailing_narration_row(parsed_row: List[str]) -> bool:
    cleaned_cells = [_clean_csv_cell(cell) for cell in parsed_row]
    if len(cleaned_cells) != 2 or not _is_likely_csv_discourse_row(parsed_row):
        return False

    combined_text = ', '.join(cell for cell in cleaned_cells if cell)
    word_count = len(re.findall(r"\b[\w'-]+\b", combined_text))
    return word_count >= 5 and cleaned_cells[-1].rstrip().endswith(('.', '!'))


def _is_csv_source_citation_row(parsed_row: List[str]) -> bool:
    if not parsed_row:
        return False

    first_cell = _clean_csv_cell(parsed_row[0])
    return bool(re.match(
        r'^\s*(?:[-*+>\u2022\u25e6\u25aa\u2023]\s*)?'
        r'(?:(?:\[\s*\d+\s*\]|\(\s*\d+\s*\)|\d+[.)])\s*)?'
        r'[\[(]?\s*(?:sources?|citations?)\s*[\])]?\s*:',
        first_cell,
        flags=re.IGNORECASE,
    ))


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
    return build_safe_csv_headers(header_cells)


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


def _clean_csv_cell(value: Any) -> str:
    return str(value or '').replace('\r\n', '\n').replace('\r', '\n').strip()


def _serialize_table_cell(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        return neutralize_csv_spreadsheet_formula(str(value))
    return neutralize_csv_spreadsheet_formula(str(value))


def _spreadsheet_formula_candidate(value: Any) -> bool:
    normalized_value = str(value or '').lstrip()
    if not normalized_value or normalized_value[0] not in ('=', '+', '-', '@'):
        return False
    if normalized_value[0] in ('+', '-') and SIGNED_NUMBER_PATTERN.fullmatch(normalized_value):
        return False
    return True


def _build_assistant_table_export_file_name() -> str:
    timestamp_suffix = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    base_name = 'assistant_table'
    return f'{base_name}_generated_{timestamp_suffix}.csv'
