# functions_workflow_runner.py
"""
Workflow execution helpers for personal workflows.
"""

import asyncio
import csv
import io
import json
import logging
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from azure.identity import (
    AzureAuthorityHosts,
    ClientSecretCredential,
    DefaultAzureCredential,
    get_bearer_token_provider,
)
from flask import Flask, g, has_request_context, session
from openai import AzureOpenAI
from semantic_kernel import Kernel
from semantic_kernel.contents.chat_message_content import ChatMessageContent

from collaboration_models import (
    COLLABORATION_KIND,
    GROUP_MULTI_USER_CHAT_TYPE,
    PERSONAL_MULTI_USER_CHAT_TYPE,
    normalize_collaboration_user,
)
from config import (
    SECRET_KEY,
    cognitive_services_scope,
    cosmos_conversations_container,
    cosmos_messages_container,
)
from functions_activity_logging import log_conversation_creation, log_token_usage, log_workflow_run
from functions_appinsights import log_event
from functions_chart_operations import append_proactive_chart_guidance
from functions_collaboration import (
    create_collaboration_message_notifications,
    get_collaboration_conversation,
    mirror_source_message_to_collaboration,
)
from functions_document_actions import (
    DOCUMENT_ACTION_CONTEXT_WORKFLOW,
    DOCUMENT_ACTION_TYPE_COMPARISON,
    DOCUMENT_ACTION_TYPE_ANALYZE,
    DOCUMENT_ACTION_TYPE_NONE,
    get_document_action_config,
    get_document_action_max_documents,
    get_document_action_max_documents_by_type,
    get_enabled_document_action_types,
)
from functions_document_comparison import run_document_comparison
from functions_debug import debug_print
from functions_document_analysis import run_document_analysis
from functions_keyvault import SecretReturnType, keyvault_model_endpoint_get_helper
from functions_message_artifacts import (
    build_agent_citation_tool_label,
    build_agent_citation_artifact_documents,
    make_json_serializable,
)
from functions_notifications import create_workflow_priority_notification
from functions_personal_workflows import save_personal_workflow_run
from functions_search_service import resolve_document_context
from functions_simplechat_operations import upload_generated_analysis_artifact_for_current_user
from functions_settings import get_settings, get_user_settings, is_tabular_processing_enabled, normalize_model_endpoints
from functions_source_review import (
    URL_ACCESS_CONTEXT_WORKFLOW,
    compact_source_review_result_for_metadata,
    perform_source_review,
    validate_url_access_request,
)
from functions_thoughts import ThoughtTracker
from semantic_kernel_loader import load_user_semantic_kernel
from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger
from semantic_kernel_plugins.plugin_invocation_thoughts import register_plugin_invocation_thought_callback


_workflow_runner_app = None
DOCUMENT_ANALYSIS_ARTIFACT_REPLY_CHAR_THRESHOLD = 12000
DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_ITEM_COUNT = 3
DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_ROW_COUNT = 5
DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_LINE_COUNT = 5
DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_LINE_LENGTH = 220
TABULAR_DOCUMENT_EXTENSIONS = {'.csv', '.xls', '.xlsx', '.xlsm'}


def _utc_now():
    return datetime.now(timezone.utc)


def _utc_now_iso():
    return _utc_now().isoformat()


def _strip_markdown_code_fence(text):
    normalized_text = str(text or '').strip()
    if not normalized_text.startswith('```'):
        return normalized_text

    code_fence_match = re.fullmatch(r'```(?:[a-zA-Z0-9_-]+)?\s*(.*?)\s*```', normalized_text, re.DOTALL)
    if not code_fence_match:
        return normalized_text

    return str(code_fence_match.group(1) or '').strip()


def _parse_json_artifact_payload(text):
    normalized_text = _strip_markdown_code_fence(text)
    if not normalized_text:
        return None

    try:
        return json.loads(normalized_text)
    except (TypeError, ValueError):
        return None


def _prompt_explicitly_requests_artifact(analysis_prompt):
    prompt_text = str(analysis_prompt or '').strip().lower()
    if not prompt_text:
        return False

    artifact_markers = (
        'download',
        'export',
        'artifact',
        'save as',
        'save it as',
        'save to file',
        'json file',
        'csv file',
        'markdown file',
    )
    return any(marker in prompt_text for marker in artifact_markers)


def _normalize_generated_artifact_file_stem(value, fallback_value='analysis-artifact'):
    normalized_value = re.sub(r'[^a-z0-9._-]+', '-', str(value or '').strip().lower()).strip('-._')
    return normalized_value or fallback_value


def _build_document_analysis_artifact_file_name(analysis_result, output_format):
    document_summaries = analysis_result.get('documents') if isinstance(analysis_result.get('documents'), list) else []
    primary_label = ''
    if document_summaries:
        first_document = document_summaries[0] if isinstance(document_summaries[0], dict) else {}
        primary_label = (
            first_document.get('title')
            or first_document.get('file_name')
            or first_document.get('document_name')
            or ''
        )

    primary_stem = os.path.splitext(str(primary_label or '').strip())[0]
    base_name = _normalize_generated_artifact_file_stem(primary_stem, fallback_value='analysis')
    if len(document_summaries) > 1:
        base_name = f'{base_name}-and-{len(document_summaries) - 1}-more'

    analysis_suffix = '' if base_name.endswith('-analysis') else '-analysis'
    return f'{base_name}{analysis_suffix}.{output_format}'


def _build_document_analysis_preview_lines(analysis_text):
    preview_lines = []
    for line in _strip_markdown_code_fence(analysis_text).splitlines():
        normalized_line = str(line or '').strip()
        if not normalized_line:
            continue

        if len(normalized_line) > DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_LINE_LENGTH:
            normalized_line = f'{normalized_line[:DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_LINE_LENGTH - 1]}…'
        preview_lines.append(normalized_line)
        if len(preview_lines) >= DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_LINE_COUNT:
            break

    return preview_lines


def _build_document_analysis_artifact_summary(document_count, output_format):
    normalized_document_count = max(0, int(document_count or 0))
    source_label = f'{normalized_document_count} source' if normalized_document_count == 1 else f'{normalized_document_count} sources'
    return (
        f'Saved the full analysis for {source_label} in this chat as a downloadable '
        f'{str(output_format or "json").upper()} artifact.'
    )


def _normalize_document_analysis_column_name(column_name):
    return re.sub(r'[^a-z0-9]+', ' ', str(column_name or '').strip().lower()).strip()


def _parse_document_analysis_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)

    normalized_value = str(value or '').strip().replace(',', '')
    if not re.fullmatch(r'[+-]?\d+', normalized_value):
        return None
    return int(normalized_value)


def _extract_document_analysis_answer_rows(analysis_text):
    parsed_output = _parse_json_artifact_payload(analysis_text)
    if isinstance(parsed_output, list) and all(isinstance(item, dict) for item in parsed_output):
        return list(parsed_output)
    if isinstance(parsed_output, dict):
        for row_key in ('rows', 'items', 'results', 'data'):
            row_values = parsed_output.get(row_key)
            if isinstance(row_values, list) and all(isinstance(item, dict) for item in row_values):
                return list(row_values)
        return [parsed_output]

    return _extract_markdown_table_rows(analysis_text)


def _choose_document_analysis_page_column(rows):
    candidate_scores = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for column_name, column_value in row.items():
            normalized_column = _normalize_document_analysis_column_name(column_name)
            if not normalized_column:
                continue
            if normalized_column in {'page', 'page number', 'page no', 'page num'}:
                score = 4
            elif normalized_column.endswith(' page') and normalized_column not in {'start page', 'end page'}:
                score = 2
            else:
                continue

            if str(column_value or '').strip():
                score += 1
            candidate_scores[column_name] = candidate_scores.get(column_name, 0) + score

    if not candidate_scores:
        return None
    return max(candidate_scores.items(), key=lambda item: item[1])[0]


def _choose_document_analysis_count_column(rows):
    candidate_scores = {}
    excluded_columns = {
        'window count',
        'chunk count',
        'source count',
        'document count',
        'row count',
        'total chunks',
        'processed chunks',
        'failed chunks',
        'total windows',
        'processed windows',
        'failed windows',
    }
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for column_name, column_value in row.items():
            normalized_column = _normalize_document_analysis_column_name(column_name)
            if 'count' not in normalized_column:
                continue
            if normalized_column in excluded_columns:
                continue

            parsed_count = _parse_document_analysis_int(column_value)
            if parsed_count is None:
                continue

            score = 3
            if parsed_count > 0:
                score += 2
            if 'exact phrase' in normalized_column or 'phrase' in normalized_column:
                score += 2
            candidate_scores[column_name] = candidate_scores.get(column_name, 0) + score

    if not candidate_scores:
        return None
    return max(candidate_scores.items(), key=lambda item: item[1])[0]


def _format_document_analysis_metric_label(column_name):
    metric_label = re.sub(r'\s+', ' ', str(column_name or 'Count').strip()) or 'Count'
    if len(metric_label) > 120:
        metric_label = f'{metric_label[:117]}...'
    return metric_label


def _build_document_analysis_page_count_summary(answer_rows):
    rows = [row for row in (answer_rows or []) if isinstance(row, dict)]
    if not rows:
        return ''

    page_column = _choose_document_analysis_page_column(rows)
    count_column = _choose_document_analysis_count_column(rows)
    if not page_column or not count_column:
        return ''

    page_counts = []
    for row in rows:
        page_value = str(row.get(page_column) or '').strip()
        count_value = _parse_document_analysis_int(row.get(count_column))
        if not page_value or count_value is None:
            continue
        page_counts.append((page_value, count_value))

    if not page_counts:
        return ''

    metric_label = _format_document_analysis_metric_label(count_column)
    total_count = sum(count_value for _, count_value in page_counts)
    page_row_count = len(page_counts)
    non_zero_page_counts = [
        (page_value, count_value)
        for page_value, count_value in page_counts
        if count_value > 0
    ]

    if not non_zero_page_counts:
        return (
            f'{metric_label}: 0 total across {page_row_count} page row(s). '
            'No matches were found in the page-level rows.'
        )

    displayed_page_counts = non_zero_page_counts[:20]
    page_summary = ', '.join(
        f'{page_value} ({count_value})'
        for page_value, count_value in displayed_page_counts
    )
    hidden_count = len(non_zero_page_counts) - len(displayed_page_counts)
    if hidden_count > 0:
        page_summary = f'{page_summary}, and {hidden_count} more'

    return (
        f'{metric_label}: {total_count} total across {page_row_count} page row(s). '
        f'Pages with matches: {page_summary}.'
    )


def _build_document_analysis_answer_excerpt(analysis_text):
    excerpt_lines = []
    for line in _strip_markdown_code_fence(analysis_text).splitlines():
        normalized_line = str(line or '').strip()
        if not normalized_line:
            continue
        if normalized_line.startswith('|'):
            continue
        if normalized_line.startswith('#'):
            continue

        if len(normalized_line) > 260:
            normalized_line = f'{normalized_line[:257]}...'
        excerpt_lines.append(normalized_line)
        if len(excerpt_lines) >= 2:
            break

    return ' '.join(excerpt_lines).strip()


def _build_document_analysis_answer_summary(analysis_reply, structured_rows=None):
    answer_rows = _extract_document_analysis_answer_rows(analysis_reply)
    page_count_summary = _build_document_analysis_page_count_summary(answer_rows)
    if page_count_summary:
        return page_count_summary

    if answer_rows:
        return f'The final structured answer contains {len(answer_rows)} row(s).'

    structured_row_count = len([row for row in (structured_rows or []) if isinstance(row, dict)])
    if structured_row_count:
        return f'The retained structured analysis contains {structured_row_count} row(s).'

    return _build_document_analysis_answer_excerpt(analysis_reply)


def _coerce_document_analysis_count(value, default=0):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _get_primary_tabular_generated_outputs(primary_generated_outputs):
    normalized_outputs = []
    for output in primary_generated_outputs or []:
        if not isinstance(output, dict):
            continue

        capability = str(output.get('capability') or '').strip().lower()
        has_tabular_identity = bool(
            capability == 'tabular'
            or output.get('background_export')
            or output.get('export_run_id')
            or output.get('run_id')
        )
        if not has_tabular_identity:
            continue

        output_format = str(output.get('output_format') or '').strip().lower()
        file_name = str(output.get('file_name') or '').strip().lower()
        if not output_format and file_name:
            output_format = os.path.splitext(file_name)[1].lstrip('.').lower()
        if not output_format:
            continue

        normalized_outputs.append(output)
    return normalized_outputs


def _prompt_explicitly_requests_markdown_artifact(analysis_prompt):
    prompt_text = str(analysis_prompt or '').strip().lower()
    if not prompt_text:
        return False

    markdown_markers = (
        'markdown',
        'md file',
        '.md',
    )
    return any(marker in prompt_text for marker in markdown_markers)


def _build_document_analysis_primary_output_reply(
    document_count,
    artifacts,
    row_count,
    raw_item_count,
    primary_generated_outputs,
):
    normalized_document_count = _coerce_document_analysis_count(document_count)
    document_label = f'{normalized_document_count} source document' if normalized_document_count == 1 else f'{normalized_document_count} source documents'
    primary_output = primary_generated_outputs[0] if primary_generated_outputs else {}
    output_format = str(primary_output.get('output_format') or 'json').strip().upper() or 'JSON'
    primary_row_count = _coerce_document_analysis_count(primary_output.get('row_count'))
    batch_count = _coerce_document_analysis_count(primary_output.get('batch_count'))
    file_name = str(primary_output.get('file_name') or '').strip()

    if primary_output.get('background_export'):
        if batch_count:
            primary_line = (
                f'I analyzed {document_label}. The full generated {output_format} export is queued in the background '
                f'for {primary_row_count} row(s) across {batch_count} batch(es). Progress is checkpointed, and the '
                'downloadable file will appear in this chat when the run completes.'
            )
        else:
            primary_line = (
                f'I analyzed {document_label}. The full generated {output_format} export is queued in the background '
                f'for {primary_row_count} row(s). Progress is checkpointed, and the downloadable file will appear in '
                'this chat when the run completes.'
            )
    elif file_name:
        primary_line = (
            f'I analyzed {document_label}. The full generated {output_format} export contains {primary_row_count} '
            f'row(s) and is attached as "{file_name}".'
        )
    else:
        primary_line = (
            f'I analyzed {document_label}. The full generated {output_format} export contains {primary_row_count} '
            'row(s) and is attached to this chat.'
        )

    lines = [primary_line]

    supporting_formats = []
    for artifact in artifacts or []:
        artifact_format = str(artifact.get('output_format') or '').strip().upper()
        if artifact_format and artifact_format not in supporting_formats:
            supporting_formats.append(artifact_format)

    if supporting_formats:
        supporting_label = ', '.join(supporting_formats)
        structured_row_count = _coerce_document_analysis_count(row_count)
        lines.append(
            f'I also attached a supporting {supporting_label} analysis preview with {structured_row_count} structured row(s) for quick review; '
            'the generated export is the exhaustive deliverable.'
        )
    elif raw_item_count:
        retained_note_count = _coerce_document_analysis_count(raw_item_count)
        lines.append(
            f'{retained_note_count} raw analysis note(s) were used during synthesis; the generated export is the primary deliverable.'
        )

    return '\n'.join(lines)


def _prompt_requests_exhaustive_analysis_output(analysis_prompt):
    prompt_text = str(analysis_prompt or '').strip().lower()
    if not prompt_text:
        return False

    exhaustive_markers = (
        'list all',
        'list out all',
        'find all',
        'identify all',
        'extract all',
        'include all',
        'every ',
        'each ',
        'full list',
        'complete list',
        'comprehensive list',
        'inventory',
        'catalog',
        'catalogue',
        'one row per',
        'one object per',
        'all vendors',
        'all entities',
    )
    return any(marker in prompt_text for marker in exhaustive_markers)


def _prompt_requests_table_analysis_output(analysis_prompt):
    prompt_text = str(analysis_prompt or '').strip().lower()
    if not prompt_text:
        return False

    table_markers = (
        'make a table',
        'create a table',
        'build a table',
        'put it into a table',
        'put this into a table',
        'put these into a table',
        'format as a table',
        'format this as a table',
        'format these as a table',
        'table format',
        'markdown table',
        'csv',
        'spreadsheet',
        'one row per',
        'each row',
        'columns',
    )
    if any(marker in prompt_text for marker in table_markers):
        return True

    return bool(re.search(r'\btable\b', prompt_text))


def _get_document_analysis_artifact_intent(analysis_result, analysis_prompt):
    analysis_result = analysis_result if isinstance(analysis_result, dict) else {}
    analysis_intent = analysis_result.get('analysis_intent') if isinstance(analysis_result.get('analysis_intent'), dict) else {}
    table_output_requested = bool(
        analysis_intent.get('table_output_requested')
        or _prompt_requests_table_analysis_output(analysis_prompt)
    )
    exhaustive_output_requested = bool(
        analysis_intent.get('exhaustive')
        or table_output_requested
        or _prompt_requests_exhaustive_analysis_output(analysis_prompt)
    )

    return {
        'exhaustive': exhaustive_output_requested,
        'table_output_requested': table_output_requested,
        'csv_artifact_recommended': bool(
            analysis_intent.get('csv_artifact_recommended')
            or table_output_requested
            or exhaustive_output_requested
        ),
        'markdown_analysis_artifact_recommended': bool(
            analysis_intent.get('markdown_analysis_artifact_recommended')
            or exhaustive_output_requested
        ),
    }


def _split_markdown_table_cells(line):
    stripped_line = str(line or '').strip()
    if '|' not in stripped_line:
        return []

    if stripped_line.startswith('|'):
        stripped_line = stripped_line[1:]
    if stripped_line.endswith('|'):
        stripped_line = stripped_line[:-1]

    return [cell.strip() for cell in stripped_line.split('|')]


def _is_markdown_table_separator(cells):
    if not cells:
        return False

    for cell in cells:
        normalized_cell = str(cell or '').replace(' ', '')
        if not re.fullmatch(r':?-{3,}:?', normalized_cell):
            return False
    return True


def _normalize_document_analysis_row_key(value, fallback_value):
    normalized_value = re.sub(r'\s+', ' ', str(value or '').strip())
    return normalized_value or fallback_value


def _dedupe_document_analysis_row_keys(headers):
    deduped_headers = []
    seen_headers = {}
    for index, header in enumerate(headers or [], start=1):
        normalized_header = _normalize_document_analysis_row_key(header, f'column_{index}')
        normalized_key = normalized_header.casefold()
        seen_count = seen_headers.get(normalized_key, 0) + 1
        seen_headers[normalized_key] = seen_count
        if seen_count > 1:
            normalized_header = f'{normalized_header}_{seen_count}'
        deduped_headers.append(normalized_header)
    return deduped_headers


def _extract_markdown_table_rows(analysis_text):
    rows = []
    lines = str(analysis_text or '').splitlines()
    line_index = 0

    while line_index + 1 < len(lines):
        header_cells = _split_markdown_table_cells(lines[line_index])
        separator_cells = _split_markdown_table_cells(lines[line_index + 1])
        if not header_cells or not _is_markdown_table_separator(separator_cells):
            line_index += 1
            continue

        headers = _dedupe_document_analysis_row_keys(header_cells)
        line_index += 2
        while line_index < len(lines):
            row_cells = _split_markdown_table_cells(lines[line_index])
            if not row_cells:
                break
            if _is_markdown_table_separator(row_cells):
                line_index += 1
                continue

            row = {}
            for column_index, header in enumerate(headers):
                row[header] = row_cells[column_index] if column_index < len(row_cells) else ''
            rows.append(row)
            line_index += 1

    return rows


def _build_document_analysis_source_context(item, default_level='analysis'):
    item = item if isinstance(item, dict) else {}
    window_range = item.get('window_range') if isinstance(item.get('window_range'), dict) else {}
    return {
        'source_level': item.get('level') or default_level,
        'source_document': item.get('file_name') or item.get('document_name') or item.get('label'),
        'source_title': item.get('title'),
        'source_label': item.get('label'),
        'source_document_id': item.get('document_id'),
        'source_scope': item.get('scope'),
        'source_scope_id': item.get('scope_id'),
        'window_number': window_range.get('window_number'),
        'start_page': window_range.get('start_page'),
        'end_page': window_range.get('end_page'),
        'start_chunk_sequence': window_range.get('start_chunk_sequence'),
        'end_chunk_sequence': window_range.get('end_chunk_sequence'),
    }


def _serialize_document_analysis_csv_value(value):
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if hasattr(value, 'isoformat') and not isinstance(value, str):
        try:
            return value.isoformat()
        except TypeError:
            pass
    return str(value)


def _add_document_analysis_source_context(row, source_context):
    normalized_row = dict(row or {})
    for context_key, context_value in (source_context or {}).items():
        if context_value in (None, ''):
            continue
        normalized_row.setdefault(context_key, context_value)
    return normalized_row


def _extract_document_analysis_rows_from_text(analysis_text, source_context, include_fallback_note=True):
    rows = []
    parsed_json = _parse_json_artifact_payload(analysis_text)
    if isinstance(parsed_json, dict):
        rows.append(parsed_json)
    elif isinstance(parsed_json, list) and all(isinstance(item, dict) for item in parsed_json):
        rows.extend(parsed_json)

    if not rows:
        rows.extend(_extract_markdown_table_rows(analysis_text))

    if not rows and include_fallback_note and str(analysis_text or '').strip():
        rows.append({'analysis_note': str(analysis_text or '').strip()})

    return [
        _add_document_analysis_source_context(row, source_context)
        for row in rows
        if isinstance(row, dict)
    ]


def _build_document_analysis_structured_rows(analysis_result):
    analysis_result = analysis_result if isinstance(analysis_result, dict) else {}
    rows = []
    raw_analysis_items = analysis_result.get('raw_analysis_items') if isinstance(analysis_result.get('raw_analysis_items'), list) else []
    document_analysis_items = analysis_result.get('document_analysis_items') if isinstance(analysis_result.get('document_analysis_items'), list) else []
    source_items = raw_analysis_items or document_analysis_items

    for item in source_items:
        if not isinstance(item, dict):
            continue
        source_context = _build_document_analysis_source_context(item)
        rows.extend(_extract_document_analysis_rows_from_text(item.get('text', ''), source_context))

    if not rows:
        final_context = {
            'source_level': 'final_analysis',
            'source_document': 'Final analysis',
            'source_label': 'Final analysis',
        }
        rows.extend(_extract_document_analysis_rows_from_text(
            analysis_result.get('analysis_reply') or analysis_result.get('reply') or '',
            final_context,
        ))

    return rows


def _build_document_analysis_rows_csv(rows):
    rows = [row for row in (rows or []) if isinstance(row, dict)]
    if not rows:
        return ''

    preferred_columns = [
        'source_level',
        'source_document',
        'source_title',
        'source_label',
        'source_document_id',
        'source_scope',
        'source_scope_id',
        'window_number',
        'start_page',
        'end_page',
        'start_chunk_sequence',
        'end_chunk_sequence',
    ]
    ordered_columns = []
    seen_columns = set()

    def add_column(column_name):
        normalized_column = str(column_name or '').strip()
        if not normalized_column or normalized_column in seen_columns:
            return
        seen_columns.add(normalized_column)
        ordered_columns.append(normalized_column)

    for column_name in preferred_columns:
        if any(column_name in row for row in rows):
            add_column(column_name)

    for row in rows:
        for column_name in row.keys():
            add_column(column_name)

    output_buffer = io.StringIO()
    writer = csv.DictWriter(output_buffer, fieldnames=ordered_columns, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({
            column_name: _serialize_document_analysis_csv_value(row.get(column_name))
            for column_name in ordered_columns
        })
    return output_buffer.getvalue()


def _build_document_analysis_coverage_markdown(analysis_result):
    coverage = analysis_result.get('coverage') if isinstance(analysis_result.get('coverage'), dict) else {}
    if not coverage:
        return ''

    coverage_lines = [
        '## Coverage',
        f"- Documents analyzed: {coverage.get('document_count', 0)}",
        f"- Total windows: {coverage.get('total_windows', 0)}",
        f"- Processed windows: {coverage.get('processed_windows', 0)}",
        f"- Failed windows: {coverage.get('failed_windows', 0)}",
        f"- Total chunks: {coverage.get('total_chunks', 0)}",
        f"- Processed chunks: {coverage.get('processed_chunks', 0)}",
        f"- Failed chunks: {coverage.get('failed_chunks', 0)}",
        f"- Retries used: {coverage.get('retries', 0)}",
    ]
    return '\n'.join(coverage_lines)


def _build_document_analysis_markdown_artifact(analysis_result):
    analysis_result = analysis_result if isinstance(analysis_result, dict) else {}
    analysis_reply = str(analysis_result.get('analysis_reply') or analysis_result.get('reply') or '').strip()
    raw_analysis_items = analysis_result.get('raw_analysis_items') if isinstance(analysis_result.get('raw_analysis_items'), list) else []
    document_analysis_items = analysis_result.get('document_analysis_items') if isinstance(analysis_result.get('document_analysis_items'), list) else []

    lines = ['# Document Analysis', '']
    if analysis_reply:
        lines.extend(['## Final Analysis', '', analysis_reply, ''])

    coverage_markdown = _build_document_analysis_coverage_markdown(analysis_result)
    if coverage_markdown:
        lines.extend([coverage_markdown, ''])

    retained_items = raw_analysis_items or document_analysis_items
    if retained_items:
        section_title = 'Raw Window-Level Analysis Notes' if raw_analysis_items else 'Document-Level Analysis Notes'
        lines.extend([f'## {section_title}', ''])
        for index, item in enumerate(retained_items, start=1):
            if not isinstance(item, dict):
                continue
            source_context = _build_document_analysis_source_context(item)
            label = str(item.get('label') or source_context.get('source_document') or f'Analysis item {index}').strip()
            lines.extend([f'### {index}. {label}', ''])

            metadata_lines = []
            for metadata_key in (
                'source_document',
                'source_title',
                'source_document_id',
                'source_level',
                'window_number',
                'start_page',
                'end_page',
                'start_chunk_sequence',
                'end_chunk_sequence',
            ):
                metadata_value = source_context.get(metadata_key)
                if metadata_value in (None, ''):
                    continue
                metadata_lines.append(f'- {metadata_key}: {metadata_value}')
            if metadata_lines:
                lines.extend(metadata_lines)
                lines.append('')

            item_text = str(item.get('text') or '').strip()
            if item_text:
                lines.extend([item_text, ''])

    return '\n'.join(lines).strip()


def _upload_document_analysis_generated_artifact(
    normalized_conversation_id,
    file_name,
    file_content,
    output_format,
    summary,
    preview_rows=None,
    preview_items=None,
    preview_lines=None,
):
    try:
        upload_result = upload_generated_analysis_artifact_for_current_user(
            conversation_id=normalized_conversation_id,
            file_name=file_name,
            file_content=file_content,
            capability='analyze',
            output_format=output_format,
            summary=summary,
        )
    except Exception as exc:
        debug_print(
            '[WorkflowDocumentAnalysis] Generated artifact upload skipped | '
            f'conversation_id={normalized_conversation_id} | file={file_name} | error={exc}'
        )
        return None

    artifact_payload = {
        'capability': 'analyze',
        'artifact_message_id': upload_result.get('message', {}).get('id'),
        'conversation_id': normalized_conversation_id,
        'storage_scope': 'chat',
        'file_name': upload_result.get('message', {}).get('file_name') or file_name,
        'output_format': output_format,
        'summary': summary,
    }
    if preview_rows:
        artifact_payload['preview_rows'] = preview_rows
    if preview_items:
        artifact_payload['preview_items'] = preview_items
    if preview_lines:
        artifact_payload['preview_lines'] = preview_lines
    return artifact_payload


def _build_document_analysis_multi_artifact_reply(
    document_count,
    artifacts,
    row_count,
    raw_item_count,
    analysis_reply,
    structured_rows=None,
):
    normalized_document_count = max(0, int(document_count or 0))
    document_label = f'{normalized_document_count} source document' if normalized_document_count == 1 else f'{normalized_document_count} source documents'
    artifact_formats = []
    for artifact in artifacts or []:
        output_format = str(artifact.get('output_format') or '').strip().upper()
        if output_format and output_format not in artifact_formats:
            artifact_formats.append(output_format)
    artifact_label = ', '.join(artifact_formats) if artifact_formats else 'downloadable'
    artifact_word = 'artifact' if len(artifact_formats) == 1 else 'artifacts'

    lines = [f'I analyzed {document_label}.']
    answer_summary = _build_document_analysis_answer_summary(analysis_reply, structured_rows)
    if answer_summary:
        lines.append(f'Answer summary: {answer_summary}')

    lines.append(
        f'Full outputs: {artifact_label} {artifact_word} are attached to this chat for download and review.'
    )
    lines.append(
        f'The structured output has {max(0, int(row_count or 0))} row(s), and '
        f'{max(0, int(raw_item_count or 0))} raw analysis note(s) were retained for auditability.'
    )

    return '\n'.join(lines)


def _build_document_analysis_artifact_reply(document_count, output_format, analysis_reply=''):
    normalized_document_count = max(0, int(document_count or 0))
    document_label = f'{normalized_document_count} source document' if normalized_document_count == 1 else f'{normalized_document_count} source documents'
    lines = [f'I analyzed {document_label}.']
    answer_summary = _build_document_analysis_answer_summary(analysis_reply)
    if answer_summary:
        lines.append(f'Answer summary: {answer_summary}')
    lines.append(
        'Full results are saved as a downloadable '
        f'{str(output_format or "json").upper()} artifact attached to this chat.'
    )
    return '\n'.join(lines)


def _maybe_create_document_analysis_generated_artifacts(
    analysis_result,
    analysis_prompt,
    conversation_id='',
    primary_generated_outputs=None,
):
    normalized_conversation_id = str(conversation_id or '').strip()
    if not normalized_conversation_id or not has_request_context():
        return {'artifacts': [], 'assistant_reply': None}

    analysis_result = analysis_result if isinstance(analysis_result, dict) else {}
    analysis_reply = str(analysis_result.get('analysis_reply') or '').strip()
    if not analysis_reply:
        return {'artifacts': [], 'assistant_reply': None}

    document_summaries = analysis_result.get('documents') if isinstance(analysis_result.get('documents'), list) else []
    document_count = len(document_summaries)
    artifact_intent = _get_document_analysis_artifact_intent(analysis_result, analysis_prompt)
    primary_tabular_outputs = _get_primary_tabular_generated_outputs(primary_generated_outputs)
    raw_analysis_items = analysis_result.get('raw_analysis_items') if isinstance(analysis_result.get('raw_analysis_items'), list) else []
    create_lossless_artifacts = bool(
        artifact_intent.get('exhaustive')
        or artifact_intent.get('table_output_requested')
        or primary_tabular_outputs
    )

    if create_lossless_artifacts:
        artifacts = []
        structured_rows = _build_document_analysis_structured_rows(analysis_result)

        if artifact_intent.get('csv_artifact_recommended') and structured_rows:
            csv_output = _build_document_analysis_rows_csv(structured_rows)
            csv_file_name = _build_document_analysis_artifact_file_name(analysis_result, 'csv')
            csv_summary = (
                f'Saved {len(structured_rows)} extracted analysis row(s) for {document_count} '
                'source document(s) as a downloadable CSV artifact.'
            )
            csv_artifact = _upload_document_analysis_generated_artifact(
                normalized_conversation_id,
                csv_file_name,
                csv_output,
                'csv',
                csv_summary,
                preview_rows=structured_rows[:DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_ROW_COUNT],
            )
            if csv_artifact:
                artifacts.append(csv_artifact)

        markdown_output = _build_document_analysis_markdown_artifact(analysis_result)
        should_create_markdown_artifact = bool(
            artifact_intent.get('markdown_analysis_artifact_recommended')
            and markdown_output
            and (
                not primary_tabular_outputs
                or _prompt_explicitly_requests_markdown_artifact(analysis_prompt)
            )
        )
        if should_create_markdown_artifact:
            markdown_file_name = _build_document_analysis_artifact_file_name(analysis_result, 'md')
            markdown_summary = (
                f'Saved the final analysis plus retained raw analysis notes for {document_count} '
                'source document(s) as a downloadable Markdown artifact.'
            )
            markdown_artifact = _upload_document_analysis_generated_artifact(
                normalized_conversation_id,
                markdown_file_name,
                markdown_output,
                'md',
                markdown_summary,
                preview_lines=_build_document_analysis_preview_lines(analysis_reply),
            )
            if markdown_artifact:
                artifacts.append(markdown_artifact)

        json_payload = _parse_json_artifact_payload(analysis_reply)
        if json_payload is not None and not primary_tabular_outputs:
            json_file_name = _build_document_analysis_artifact_file_name(analysis_result, 'json')
            json_summary = _build_document_analysis_artifact_summary(document_count, 'json')
            json_preview_items = []
            if isinstance(json_payload, list):
                json_preview_items = json_payload[:DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_ITEM_COUNT]
            elif isinstance(json_payload, dict):
                json_preview_items = [json_payload]
            json_artifact = _upload_document_analysis_generated_artifact(
                normalized_conversation_id,
                json_file_name,
                json.dumps(json_payload, indent=2, ensure_ascii=False),
                'json',
                json_summary,
                preview_items=json_preview_items,
            )
            if json_artifact:
                artifacts.append(json_artifact)

        if artifacts or primary_tabular_outputs:
            assistant_reply = _build_document_analysis_multi_artifact_reply(
                document_count,
                artifacts,
                len(structured_rows),
                len(raw_analysis_items),
                analysis_reply,
                structured_rows=structured_rows,
            )
            if primary_tabular_outputs:
                assistant_reply = _build_document_analysis_primary_output_reply(
                    document_count,
                    artifacts,
                    len(structured_rows),
                    len(raw_analysis_items),
                    primary_tabular_outputs,
                )
            return {
                'artifacts': artifacts,
                'assistant_reply': assistant_reply,
            }

    if primary_tabular_outputs:
        return {
            'artifacts': [],
            'assistant_reply': _build_document_analysis_primary_output_reply(
                document_count,
                [],
                0,
                len(raw_analysis_items),
                primary_tabular_outputs,
            ),
        }

    json_payload = _parse_json_artifact_payload(analysis_reply)
    explicit_artifact_request = _prompt_explicitly_requests_artifact(analysis_prompt)
    should_generate_artifact = (
        explicit_artifact_request
        or json_payload is not None
        or len(analysis_reply) >= DOCUMENT_ANALYSIS_ARTIFACT_REPLY_CHAR_THRESHOLD
    )
    if not should_generate_artifact:
        return {'artifacts': [], 'assistant_reply': None}

    output_format = 'json' if json_payload is not None else 'md'
    preview_items = []
    preview_lines = []

    if output_format == 'json':
        serialized_output = json.dumps(json_payload, indent=2, ensure_ascii=False)
        if isinstance(json_payload, list):
            preview_items = json_payload[:DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_ITEM_COUNT]
        elif isinstance(json_payload, dict):
            preview_items = [json_payload]
    else:
        serialized_output = analysis_reply
        preview_lines = _build_document_analysis_preview_lines(analysis_reply)

    file_name = _build_document_analysis_artifact_file_name(analysis_result, output_format)
    summary = _build_document_analysis_artifact_summary(document_count, output_format)

    artifact_payload = _upload_document_analysis_generated_artifact(
        normalized_conversation_id,
        file_name,
        serialized_output,
        output_format,
        summary,
        preview_items=preview_items,
        preview_lines=preview_lines,
    )
    if not artifact_payload:
        return {'artifacts': [], 'assistant_reply': None}

    return {
        'artifacts': [artifact_payload],
        'assistant_reply': _build_document_analysis_artifact_reply(document_count, output_format, analysis_reply),
    }


def _build_comparison_artifact_file_name(comparison_result, output_format):
    left_document = comparison_result.get('left_document') if isinstance(comparison_result.get('left_document'), dict) else {}
    left_document_name = (
        left_document.get('document_name')
        or left_document.get('file_name')
        or left_document.get('title')
        or 'comparison'
    )
    right_documents = comparison_result.get('right_documents') if isinstance(comparison_result.get('right_documents'), list) else []
    base_name = _normalize_generated_artifact_file_stem(left_document_name, fallback_value='comparison')
    if right_documents:
        base_name = f'{base_name}-vs-{len(right_documents)}-targets'
    return f'{base_name}-comparison.{output_format}'


def _build_comparison_artifact_summary(left_document_name, right_count, output_format):
    target_label = '1 target' if int(right_count or 0) == 1 else f'{int(right_count or 0)} targets'
    return (
        f'Saved the full comparison for {left_document_name or "the selected source"} against {target_label} '
        f'in this chat as a downloadable {str(output_format or "json").upper()} artifact.'
    )


def _build_comparison_artifact_reply(left_document_name, right_count, output_format):
    target_label = '1 target' if int(right_count or 0) == 1 else f'{int(right_count or 0)} targets'
    return (
        f'I compared {left_document_name or "the selected source"} against {target_label} and saved the full '
        f'results as a downloadable {str(output_format or "json").upper()} artifact attached to this chat. '
        'The card below includes a short preview.'
    )


def _maybe_create_comparison_generated_artifacts(comparison_result, comparison_prompt, conversation_id=''):
    normalized_conversation_id = str(conversation_id or '').strip()
    if not normalized_conversation_id or not has_request_context():
        return {'artifacts': [], 'assistant_reply': None}

    comparison_result = comparison_result if isinstance(comparison_result, dict) else {}
    analysis_reply = str(comparison_result.get('analysis_reply') or '').strip()
    if not analysis_reply:
        return {'artifacts': [], 'assistant_reply': None}

    json_payload = _parse_json_artifact_payload(analysis_reply)
    explicit_artifact_request = _prompt_explicitly_requests_artifact(comparison_prompt)
    should_generate_artifact = (
        explicit_artifact_request
        or json_payload is not None
        or len(analysis_reply) >= DOCUMENT_ANALYSIS_ARTIFACT_REPLY_CHAR_THRESHOLD
    )
    if not should_generate_artifact:
        return {'artifacts': [], 'assistant_reply': None}

    left_document = comparison_result.get('left_document') if isinstance(comparison_result.get('left_document'), dict) else {}
    left_document_name = str(left_document.get('document_name') or 'the selected source').strip() or 'the selected source'
    right_documents = comparison_result.get('right_documents') if isinstance(comparison_result.get('right_documents'), list) else []
    output_format = 'json' if json_payload is not None else 'md'
    preview_items = []
    preview_lines = []

    if output_format == 'json':
        serialized_output = json.dumps(json_payload, indent=2, ensure_ascii=False)
        if isinstance(json_payload, list):
            preview_items = json_payload[:DOCUMENT_ANALYSIS_ARTIFACT_PREVIEW_ITEM_COUNT]
        elif isinstance(json_payload, dict):
            preview_items = [json_payload]
    else:
        serialized_output = analysis_reply
        preview_lines = _build_document_analysis_preview_lines(analysis_reply)

    file_name = _build_comparison_artifact_file_name(comparison_result, output_format)
    summary = _build_comparison_artifact_summary(left_document_name, len(right_documents), output_format)

    try:
        upload_result = upload_generated_analysis_artifact_for_current_user(
            conversation_id=normalized_conversation_id,
            file_name=file_name,
            file_content=serialized_output,
            capability='comparison',
            output_format=output_format,
            summary=summary,
        )
    except Exception as exc:
        debug_print(
            '[WorkflowDocumentComparison] Generated artifact upload skipped | '
            f'conversation_id={normalized_conversation_id} | error={exc}'
        )
        return {'artifacts': [], 'assistant_reply': None}

    artifact_payload = {
        'capability': 'comparison',
        'artifact_message_id': upload_result.get('message', {}).get('id'),
        'conversation_id': normalized_conversation_id,
        'storage_scope': 'chat',
        'file_name': upload_result.get('message', {}).get('file_name') or file_name,
        'output_format': output_format,
        'summary': summary,
    }
    if preview_items:
        artifact_payload['preview_items'] = preview_items
    if preview_lines:
        artifact_payload['preview_lines'] = preview_lines

    return {
        'artifacts': [artifact_payload],
        'assistant_reply': _build_comparison_artifact_reply(left_document_name, len(right_documents), output_format),
    }


def _coerce_token_count(value):
    try:
        if value in (None, ''):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_token_usage(payload):
    candidate = payload
    if isinstance(payload, dict) and payload.get('usage') is not None:
        candidate = payload.get('usage')
    elif getattr(payload, 'usage', None) is not None:
        candidate = getattr(payload, 'usage')

    if isinstance(candidate, dict):
        prompt_tokens = _coerce_token_count(candidate.get('prompt_tokens'))
        completion_tokens = _coerce_token_count(candidate.get('completion_tokens'))
        total_tokens = _coerce_token_count(candidate.get('total_tokens'))
    else:
        prompt_tokens = _coerce_token_count(getattr(candidate, 'prompt_tokens', None))
        completion_tokens = _coerce_token_count(getattr(candidate, 'completion_tokens', None))
        total_tokens = _coerce_token_count(getattr(candidate, 'total_tokens', None))

    if total_tokens is None and (prompt_tokens is not None or completion_tokens is not None):
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

    if prompt_tokens is None and completion_tokens is None and total_tokens is None:
        return None

    return {
        'prompt_tokens': prompt_tokens or 0,
        'completion_tokens': completion_tokens or 0,
        'total_tokens': total_tokens or 0,
    }


def _create_token_usage_aggregate():
    return {
        'prompt_tokens': 0,
        'completion_tokens': 0,
        'total_tokens': 0,
        'request_count': 0,
    }


def _accumulate_token_usage(aggregate, payload):
    usage = _extract_token_usage(payload)
    if not usage:
        return None

    aggregate['prompt_tokens'] += usage.get('prompt_tokens', 0)
    aggregate['completion_tokens'] += usage.get('completion_tokens', 0)
    aggregate['total_tokens'] += usage.get('total_tokens', 0)
    aggregate['request_count'] += 1
    return usage


def _finalize_token_usage(aggregate):
    if not isinstance(aggregate, dict):
        return None

    if not any(aggregate.get(key) for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')):
        return None

    token_usage = {
        'prompt_tokens': int(aggregate.get('prompt_tokens', 0) or 0),
        'completion_tokens': int(aggregate.get('completion_tokens', 0) or 0),
        'total_tokens': int(aggregate.get('total_tokens', 0) or 0),
    }
    request_count = _coerce_token_count(aggregate.get('request_count'))
    if request_count:
        token_usage['request_count'] = request_count
    return token_usage


def _strip_agent_citation_artifact_refs(agent_citations):
    compact_citations = []
    for citation in agent_citations or []:
        if not isinstance(citation, dict):
            compact_citations.append(citation)
            continue

        compact_citation = dict(citation)
        compact_citation.pop('artifact_id', None)
        compact_citation.pop('raw_payload_externalized', None)
        compact_citations.append(compact_citation)

    return compact_citations


def _persist_agent_citation_artifacts(
    conversation_id,
    assistant_message_id,
    agent_citations,
    created_timestamp,
    user_info=None,
):
    if not agent_citations:
        return []

    compact_citations, artifact_docs = build_agent_citation_artifact_documents(
        conversation_id=conversation_id,
        assistant_message_id=assistant_message_id,
        agent_citations=agent_citations,
        created_timestamp=created_timestamp,
        user_info=user_info,
    )

    try:
        for artifact_doc in artifact_docs:
            cosmos_messages_container.upsert_item(artifact_doc)
        return compact_citations
    except Exception as exc:
        log_event(
            f'[WorkflowRunner] Failed to persist workflow assistant artifacts: {exc}',
            extra={
                'conversation_id': conversation_id,
                'assistant_message_id': assistant_message_id,
                'artifact_count': len(artifact_docs),
                'citation_count': len(agent_citations),
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return _strip_agent_citation_artifact_refs(compact_citations)


def _normalize_invocation_timestamp(raw_timestamp):
    if not raw_timestamp:
        return None
    if hasattr(raw_timestamp, 'isoformat'):
        return raw_timestamp.isoformat()
    return str(raw_timestamp)


def _build_agent_citations_from_plugin_invocations(plugin_invocations):
    detailed_citations = []

    for invocation in plugin_invocations or []:
        tool_name = build_agent_citation_tool_label(
            invocation.plugin_name,
            invocation.function_name,
            invocation.parameters,
            invocation.result,
        )
        detailed_citations.append({
            'tool_name': tool_name,
            'function_name': invocation.function_name,
            'plugin_name': invocation.plugin_name,
            'function_arguments': make_json_serializable(invocation.parameters),
            'function_result': make_json_serializable(invocation.result),
            'duration_ms': invocation.duration_ms,
            'timestamp': _normalize_invocation_timestamp(invocation.timestamp),
            'success': invocation.success,
            'error_message': make_json_serializable(invocation.error_message),
            'user_id': invocation.user_id,
        })

    return detailed_citations


def _build_agent_citations_from_invocations(user_id, conversation_id):
    if not user_id or not conversation_id:
        return []

    plugin_logger = get_plugin_logger()
    plugin_invocations = plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000)
    return _build_agent_citations_from_plugin_invocations(plugin_invocations)


def _is_tabular_document_file(file_name):
    normalized_file_name = str(file_name or '').strip()
    if not normalized_file_name:
        return False

    return os.path.splitext(normalized_file_name)[1].lower() in TABULAR_DOCUMENT_EXTENSIONS


def _normalize_tabular_source_hint(scope):
    normalized_scope = str(scope or '').strip().lower()
    if normalized_scope == 'personal':
        return 'workspace'
    if normalized_scope in {'workspace', 'group', 'public', 'chat'}:
        return normalized_scope
    return 'workspace'


def _resolve_tabular_document_action_documents(action_config, user_id, conversation_id=''):
    action_config = action_config if isinstance(action_config, dict) else {}
    action_type = str(action_config.get('type') or '').strip().lower()

    document_ids = []
    role_by_document_id = {}
    if action_type == DOCUMENT_ACTION_TYPE_ANALYZE:
        document_ids = [
            str(document_id).strip()
            for document_id in list(action_config.get('document_ids') or [])
            if str(document_id).strip()
        ]
    elif action_type == DOCUMENT_ACTION_TYPE_COMPARISON:
        left_document_id = str(action_config.get('left_document_id') or '').strip()
        right_document_ids = [
            str(document_id).strip()
            for document_id in list(action_config.get('right_document_ids') or [])
            if str(document_id).strip()
        ]
        if left_document_id:
            document_ids.append(left_document_id)
            role_by_document_id[left_document_id] = 'left'
        for document_id in right_document_ids:
            document_ids.append(document_id)
            role_by_document_id[document_id] = 'right'

    if not document_ids:
        return []

    resolved_documents = []
    for document_id in document_ids:
        document_context = resolve_document_context(
            document_id=document_id,
            user_id=user_id,
            doc_scope=action_config.get('doc_scope'),
            active_group_ids=action_config.get('active_group_ids'),
            active_public_workspace_id=action_config.get('active_public_workspace_id'),
            conversation_id=conversation_id,
        )
        if not isinstance(document_context, dict):
            return []

        document_item = document_context.get('document') if isinstance(document_context.get('document'), dict) else {}
        file_name = str(document_item.get('file_name') or document_item.get('title') or '').strip()
        if not _is_tabular_document_file(file_name):
            return []

        document_name = str(document_item.get('title') or file_name or document_id).strip() or document_id
        resolved_documents.append({
            'document_id': document_id,
            'document_name': document_name,
            'file_name': file_name,
            'scope': str(document_context.get('scope') or '').strip().lower() or 'personal',
            'source_hint': _normalize_tabular_source_hint(document_context.get('scope')),
            'group_id': str(document_context.get('group_id') or '').strip() or None,
            'public_workspace_id': str(document_context.get('public_workspace_id') or '').strip() or None,
            'role_label': role_by_document_id.get(document_id),
        })

    return resolved_documents


def _resolve_tabular_document_action_model_name(workflow, settings):
    candidate_model_name = str(workflow.get('legacy_model_deployment') or '').strip()
    if candidate_model_name:
        return candidate_model_name

    for candidate in (
        settings.get('azure_apim_gpt_deployment'),
        settings.get('azure_openai_gpt_deployment'),
    ):
        normalized_candidate = str(candidate or '').strip()
        if normalized_candidate:
            return normalized_candidate.split(',')[0].strip()

    selected_models = settings.get('gpt_model', {}).get('selected') if isinstance(settings.get('gpt_model'), dict) else []
    if isinstance(selected_models, list) and selected_models:
        selected_model = selected_models[0] if isinstance(selected_models[0], dict) else {}
        for key in ('deploymentName', 'deployment', 'displayName'):
            normalized_candidate = str(selected_model.get(key) or '').strip()
            if normalized_candidate:
                return normalized_candidate

    return ''


def _truncate_tabular_document_action_analysis(tabular_analysis, max_chars=8000):
    rendered_analysis = str(tabular_analysis or '').strip()
    if len(rendered_analysis) <= max_chars:
        return rendered_analysis

    return f"{rendered_analysis[:max_chars]}\n[Computed tabular results truncated for prompt budget.]"


def _build_tabular_document_action_coverage(tabular_documents, phase_label):
    document_summaries = []
    for tabular_document in tabular_documents or []:
        document_summaries.append({
            'document_id': tabular_document.get('document_id'),
            'document_name': tabular_document.get('document_name'),
            'file_name': tabular_document.get('file_name'),
            'title': tabular_document.get('document_name'),
            'scope': tabular_document.get('scope'),
            'scope_id': (
                tabular_document.get('public_workspace_id')
                or tabular_document.get('group_id')
                or None
            ),
            'role_label': tabular_document.get('role_label'),
            'total_windows': 1,
            'processed_windows': 1,
            'failed_windows': 0,
            'total_chunks': 1,
            'processed_chunks': 1,
            'failed_chunks': 0,
            'total_pages': 0,
            'status': 'completed',
            'status_text': 'Completed tabular analysis',
            'active_window_number': None,
            'active_attempt_number': None,
            'failed_ranges': [],
            'ranges': [],
        })

    completed_document_count = len(document_summaries)
    return {
        'document_count': completed_document_count,
        'total_windows': completed_document_count,
        'processed_windows': completed_document_count,
        'failed_windows': 0,
        'total_chunks': completed_document_count,
        'processed_chunks': completed_document_count,
        'failed_chunks': 0,
        'retries': 0,
        'window_unit': 'tabular',
        'documents': document_summaries,
        'progress_meta': {
            'phase': 'completed',
            'phase_label': phase_label,
            'phase_detail': 'Prepared from tabular tool-backed results',
            'status': 'completed',
            'percent_override': 100,
            'phase_step': 1,
            'phase_total_steps': 1,
        },
    }


def _build_tabular_analysis_action_prompt(analysis_prompt, tabular_documents):
    # Import lazily to avoid a circular dependency during workflow startup.
    from functions_tabular_analysis import build_tabular_computed_results_system_message

    prompt_sections = [
        'You are completing deterministic document analysis using tool-backed tabular analysis.',
        'Use the computed tabular results below as the primary evidence. Do not say the analysis still needs to be run.',
        'If the computed results are insufficient for a conclusion, say so explicitly.',
        f'Analysis request:\n{str(analysis_prompt or "").strip()}',
    ]

    for tabular_document in tabular_documents or []:
        prompt_sections.append(
            build_tabular_computed_results_system_message(
                tabular_document.get('document_name') or tabular_document.get('file_name') or 'the selected tabular document',
                _truncate_tabular_document_action_analysis(tabular_document.get('analysis')),
                related_document_evidence_summary=tabular_document.get('related_document_evidence_summary') or '',
            )
        )

    prompt_sections.append(
        'Write one cohesive analysis that highlights concrete facts, counts, trends, anomalies, risks, open questions, and recommended follow-up based on the computed results.'
    )
    return append_proactive_chart_guidance(
        '\n\n'.join(section for section in prompt_sections if section),
        force=True,
    )


def _build_tabular_comparison_action_prompt(comparison_prompt, left_document, right_documents):
    # Import lazily to avoid a circular dependency during workflow startup.
    from functions_tabular_analysis import build_tabular_computed_results_system_message

    prompt_sections = [
        'You are completing a deterministic document comparison using tool-backed tabular analysis.',
        'Treat the source document as the primary baseline and compare each target document against it.',
        'Use the computed tabular results below as authoritative evidence for row-level facts, calculations, and numeric conclusions.',
        f'Comparison request:\n{str(comparison_prompt or "").strip()}',
    ]

    prompt_sections.append(
        build_tabular_computed_results_system_message(
            f"source document {left_document.get('document_name') or left_document.get('file_name') or 'Source'}",
            _truncate_tabular_document_action_analysis(left_document.get('analysis')),
            related_document_evidence_summary=left_document.get('related_document_evidence_summary') or '',
        )
    )

    for right_document in right_documents or []:
        prompt_sections.append(
            build_tabular_computed_results_system_message(
                f"target document {right_document.get('document_name') or right_document.get('file_name') or 'Target'}",
                _truncate_tabular_document_action_analysis(right_document.get('analysis')),
                related_document_evidence_summary=right_document.get('related_document_evidence_summary') or '',
            )
        )

    prompt_sections.append(
        'Explain what matches, what differs, what changed, what is missing, and which discrepancies or risks matter most for the user request. Organize the answer clearly by target document when there is more than one.'
    )
    return append_proactive_chart_guidance(
        '\n\n'.join(section for section in prompt_sections if section),
        force=True,
    )


def _build_workflow_generation_prompt(task_prompt):
    return append_proactive_chart_guidance(task_prompt)


def _workflow_url_access_enabled(workflow):
    value = (workflow or {}).get('url_access_enabled', False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def _get_workflow_url_access_system_content(url_access_context=None):
    url_access_context = url_access_context if isinstance(url_access_context, dict) else {}
    system_message = url_access_context.get('system_message')
    if not system_message:
        source_review_result = url_access_context.get('source_review_result')
        source_review_result = source_review_result if isinstance(source_review_result, dict) else {}
        system_message = source_review_result.get('system_message')
    if isinstance(system_message, dict):
        return str(system_message.get('content') or '').strip()
    return str(system_message or '').strip()


def _build_workflow_chat_messages(prompt_text, url_access_context=None, apply_generation_guidance=False):
    user_content = _build_workflow_generation_prompt(prompt_text) if apply_generation_guidance else str(prompt_text or '').strip()
    messages = []
    source_review_content = _get_workflow_url_access_system_content(url_access_context)
    if source_review_content:
        messages.append({'role': 'system', 'content': source_review_content})
    messages.append({'role': 'user', 'content': user_content})
    return messages


def _build_workflow_agent_messages(prompt_text, url_access_context=None, apply_generation_guidance=False):
    user_content = _build_workflow_generation_prompt(prompt_text) if apply_generation_guidance else str(prompt_text or '').strip()
    source_review_content = _get_workflow_url_access_system_content(url_access_context)
    if source_review_content:
        user_content = f'{source_review_content}\n\n[Workflow Task]\n{user_content}'
    return [ChatMessageContent(role='user', content=user_content)]


def _format_workflow_url_access_error(validation_result):
    validation_result = validation_result if isinstance(validation_result, dict) else {}
    reason = str(validation_result.get('reason') or '').strip()
    if reason == 'url_access_disabled':
        return 'URL Access is disabled by an administrator for workflow runs.'
    if reason == 'url_access_role_required':
        return 'Workflow URL Access requires the UrlAccessUser app role.'
    if reason == 'url_count_exceeded':
        return (
            f"Workflow URL Access supports up to {int(validation_result.get('limit') or 0)} direct URLs per run; "
            f"found {int(validation_result.get('url_count') or 0)}."
        )
    return 'Workflow URL Access request was not allowed.'


def _prepare_workflow_url_access_context(workflow, settings, conversation_id, run_id, thought_tracker=None, user_roles=None):
    workflow = workflow if isinstance(workflow, dict) else {}
    task_prompt = str(workflow.get('task_prompt') or '')
    requested = _workflow_url_access_enabled(workflow)
    url_access_context = {
        'requested': requested,
        'enabled': False,
        'authorization_prechecked': bool(workflow.get('url_access_authorized')),
        'validation': {},
        'source_review_result': {},
        'system_message': None,
    }
    if not requested:
        return url_access_context

    validation_result = validate_url_access_request(
        task_prompt,
        settings,
        execution_context=URL_ACCESS_CONTEXT_WORKFLOW,
        user_roles=user_roles,
        authorization_prechecked=bool(workflow.get('url_access_authorized')),
    )
    url_access_context['validation'] = validation_result
    url_access_context['enabled'] = bool(validation_result.get('enabled'))
    if not validation_result.get('allowed'):
        _add_workflow_activity_thought(
            thought_tracker,
            workflow,
            run_id,
            step_type='url_access',
            content='Workflow URL Access request was blocked',
            detail=_format_workflow_url_access_error(validation_result),
            activity_key=f'url-access:{run_id}',
            kind='url_access',
            title='URL Access',
            status='failed',
        )
        raise ValueError(_format_workflow_url_access_error(validation_result))

    urls = validation_result.get('urls') if isinstance(validation_result.get('urls'), list) else []
    if not urls:
        return url_access_context

    _add_workflow_activity_thought(
        thought_tracker,
        workflow,
        run_id,
        step_type='url_access',
        content='Reviewing workflow URLs',
        detail=f"urls={len(urls)} | limit={validation_result.get('limit')}",
        activity_key=f'url-access:{run_id}',
        kind='url_access',
        title='URL Access',
        status='running',
    )
    source_review_result = perform_source_review(
        settings=settings,
        user_id=str(workflow.get('user_id') or '').strip(),
        user_email=None,
        user_roles=[],
        user_message=task_prompt,
        web_search_citations=[],
        conversation_id=conversation_id,
        url_access_only=True,
        url_access_context=URL_ACCESS_CONTEXT_WORKFLOW,
        include_direct_user_urls=True,
        url_access_authorization_prechecked=bool(workflow.get('url_access_authorized')),
    )
    url_access_context['source_review_result'] = source_review_result if isinstance(source_review_result, dict) else {}
    url_access_context['system_message'] = url_access_context['source_review_result'].get('system_message')
    coverage = url_access_context['source_review_result'].get('coverage')
    coverage = coverage if isinstance(coverage, dict) else {}
    pages_reviewed = int(coverage.get('pages_reviewed') or 0)
    pages_skipped = int(coverage.get('pages_skipped') or 0)
    thought_content = (
        f'Reviewed {pages_reviewed} workflow URL source page(s)'
        if pages_reviewed
        else 'URL Access did not add workflow page evidence'
    )
    thought_detail = f"skipped={pages_skipped} | reason={url_access_context['source_review_result'].get('skipped_reason') or 'none'}"
    _add_workflow_activity_thought(
        thought_tracker,
        workflow,
        run_id,
        step_type='url_access',
        content=thought_content,
        detail=thought_detail,
        activity_key=f'url-access:{run_id}',
        kind='url_access',
        title='URL Access',
        status='completed',
    )
    return url_access_context


def _attach_workflow_url_access_result(execution_result, url_access_context=None):
    execution_result = execution_result if isinstance(execution_result, dict) else {}
    url_access_context = url_access_context if isinstance(url_access_context, dict) else {}
    if not url_access_context.get('requested'):
        return execution_result

    source_review_result = url_access_context.get('source_review_result')
    source_review_result = source_review_result if isinstance(source_review_result, dict) else {}
    coverage = source_review_result.get('coverage') if isinstance(source_review_result.get('coverage'), dict) else {}
    execution_result['url_access'] = {
        'requested': True,
        'enabled': bool(url_access_context.get('enabled')),
        'validation': url_access_context.get('validation') or {},
        'authorization_prechecked': bool(url_access_context.get('authorization_prechecked')),
        'pages_reviewed': int(coverage.get('pages_reviewed') or 0),
        'pages_skipped': int(coverage.get('pages_skipped') or 0),
        'skipped_reason': source_review_result.get('skipped_reason'),
    }
    if source_review_result:
        execution_result['source_review'] = compact_source_review_result_for_metadata(source_review_result)
        execution_result['web_search_citations'] = list(source_review_result.get('citations') or [])
    return execution_result


def _build_tabular_analysis_request_prompt(action_type, task_prompt, tabular_document):
    if action_type == DOCUMENT_ACTION_TYPE_COMPARISON:
        role_label = tabular_document.get('role_label') or 'document'
        document_name = tabular_document.get('document_name') or tabular_document.get('file_name') or 'the selected document'
        return (
            f'Summarize the tabular facts in the {role_label} workbook {document_name} that matter for the comparison request below. '
            'Focus on counts, totals, identifiers, dates, statuses, trends, anomalies, and any row-level evidence that would matter in a comparison.\n\n'
            f'Comparison request:\n{str(task_prompt or "").strip()}'
        )

    return str(task_prompt or '').strip()


def _build_tabular_document_action_thought_callback(thought_tracker=None, live_thought_callback=None):
    if thought_tracker is None and not callable(live_thought_callback):
        return None

    def callback(thought_payload):
        payload = thought_payload if isinstance(thought_payload, dict) else {}
        live_payload = dict(payload)

        if thought_tracker is not None:
            thought_tracker.add_thought(
                str(payload.get('step_type') or 'tabular_analysis').strip() or 'tabular_analysis',
                str(payload.get('content') or '').strip(),
                detail=payload.get('detail'),
                activity=payload.get('activity'),
            )
            live_payload['message_id'] = getattr(thought_tracker, 'message_id', None)
            live_payload['step_index'] = thought_tracker.current_index - 1

        if callable(live_thought_callback):
            live_thought_callback(live_payload)

    return callback


def _maybe_execute_tabular_document_action(
    action_type,
    workflow,
    action_config,
    settings,
    conversation_id='',
    invoke_prompt=None,
    thought_tracker=None,
    live_thought_callback=None,
):
    if action_type not in {DOCUMENT_ACTION_TYPE_ANALYZE, DOCUMENT_ACTION_TYPE_COMPARISON}:
        return None
    if not callable(invoke_prompt) or not is_tabular_processing_enabled(settings):
        return None

    user_id = str(workflow.get('user_id') or '').strip()
    if not user_id:
        return None

    tabular_documents = _resolve_tabular_document_action_documents(
        action_config,
        user_id,
        conversation_id=conversation_id,
    )
    if not tabular_documents:
        return None

    gpt_model = _resolve_tabular_document_action_model_name(workflow, settings)
    if not gpt_model:
        return None

    # Import lazily to avoid a circular dependency during workflow startup.
    from functions_tabular_analysis import (
        augment_tabular_invocations_with_related_document_evidence,
        build_tabular_related_document_evidence_summary,
        get_new_plugin_invocations,
        maybe_create_tabular_generated_output,
        run_tabular_analysis_with_thought_tracking,
    )

    plugin_logger = get_plugin_logger()
    baseline_invocation_count = 0
    if conversation_id:
        baseline_invocation_count = len(
            plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000)
        )
    generated_tabular_outputs = []
    task_prompt = str(workflow.get('task_prompt', '') or '').strip()
    tabular_post_processing_thought_callback = _build_tabular_document_action_thought_callback(
        thought_tracker=thought_tracker,
        live_thought_callback=live_thought_callback,
    )

    try:
        for tabular_document in tabular_documents:
            document_baseline_invocation_count = 0
            if conversation_id:
                document_baseline_invocation_count = len(
                    plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000)
                )

            tabular_analysis, _ = asyncio.run(
                run_tabular_analysis_with_thought_tracking(
                    user_question=_build_tabular_analysis_request_prompt(
                        action_type,
                        task_prompt,
                        tabular_document,
                    ),
                    tabular_filenames={tabular_document.get('file_name')},
                    user_id=user_id,
                    conversation_id=conversation_id,
                    gpt_model=gpt_model,
                    settings=settings,
                    source_hint=tabular_document.get('source_hint', 'workspace'),
                    group_id=tabular_document.get('group_id'),
                    public_workspace_id=tabular_document.get('public_workspace_id'),
                    execution_mode='analysis',
                    tabular_file_contexts=[{
                        'file_name': tabular_document.get('file_name'),
                        'source_hint': tabular_document.get('source_hint', 'workspace'),
                        'group_id': tabular_document.get('group_id'),
                        'public_workspace_id': tabular_document.get('public_workspace_id'),
                    }],
                    thought_tracker=thought_tracker,
                    live_thought_callback=live_thought_callback,
                )
            )
            if not str(tabular_analysis or '').strip():
                raise ValueError(
                    f"Tabular analysis returned no computed results for {tabular_document.get('document_name') or tabular_document.get('file_name') or tabular_document.get('document_id')}."
                )
            tabular_document['analysis'] = str(tabular_analysis).strip()

            if conversation_id:
                invocations_after_document = plugin_logger.get_invocations_for_conversation(
                    user_id,
                    conversation_id,
                    limit=1000,
                )
                document_tabular_invocations = get_new_plugin_invocations(
                    invocations_after_document,
                    document_baseline_invocation_count,
                )

                related_document_stats = augment_tabular_invocations_with_related_document_evidence(
                    document_tabular_invocations,
                    task_prompt,
                    user_id,
                    conversation_id=conversation_id,
                )
                if related_document_stats.get('augmented_row_count'):
                    tabular_document['related_document_evidence_summary'] = build_tabular_related_document_evidence_summary(
                        document_tabular_invocations,
                    )

                generated_tabular_output = asyncio.run(
                    maybe_create_tabular_generated_output(
                        user_question=task_prompt,
                        invocations=document_tabular_invocations,
                        gpt_model=gpt_model,
                        settings=settings,
                        conversation_id=conversation_id,
                        thought_callback=tabular_post_processing_thought_callback,
                        user_id=user_id,
                    )
                )
                if generated_tabular_output:
                    generated_tabular_outputs.append(generated_tabular_output)
    except Exception as exc:
        log_event(
            f'[WorkflowDocumentAction] Tabular document-action helper skipped: {exc}',
            extra={
                'conversation_id': conversation_id,
                'workflow_id': str(workflow.get('id') or '').strip(),
                'action_type': action_type,
                'document_count': len(tabular_documents),
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        if conversation_id:
            plugin_logger.clear_invocations_for_conversation(user_id, conversation_id)
        return None

    tabular_invocations = []
    if conversation_id:
        invocations_after = plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000)
        tabular_invocations = get_new_plugin_invocations(invocations_after, baseline_invocation_count)
    tabular_agent_citations = _build_agent_citations_from_plugin_invocations(tabular_invocations)

    if action_type == DOCUMENT_ACTION_TYPE_ANALYZE:
        analysis_result = {
            'reply': '',
            'analysis_reply': str(invoke_prompt(
                _build_tabular_analysis_action_prompt(workflow.get('task_prompt', ''), tabular_documents),
                stage='tabular_analysis',
                metadata={
                    'action_type': action_type,
                    'document_ids': [tabular_document.get('document_id') for tabular_document in tabular_documents],
                },
            ) or '').strip(),
            'coverage': _build_tabular_document_action_coverage(tabular_documents, 'Analysis complete'),
            'documents': [],
            'document_ids': [tabular_document.get('document_id') for tabular_document in tabular_documents],
            'doc_scope': action_config.get('doc_scope'),
            'window_unit': 'tabular',
            'window_size': None,
            'window_percent': None,
        }
        if not analysis_result['analysis_reply']:
            raise RuntimeError('Tabular analysis synthesis returned an empty response.')
        analysis_result['reply'] = analysis_result['analysis_reply']
        analysis_result['documents'] = analysis_result['coverage'].get('documents', [])
        return {
            'result': analysis_result,
            'agent_citations': tabular_agent_citations,
            'generated_tabular_outputs': generated_tabular_outputs,
        }

    left_document = tabular_documents[0] if tabular_documents else {}
    right_documents = tabular_documents[1:]
    comparison_result = {
        'reply': '',
        'analysis_reply': str(invoke_prompt(
            _build_tabular_comparison_action_prompt(
                workflow.get('task_prompt', ''),
                left_document,
                right_documents,
            ),
            stage='tabular_comparison',
            metadata={
                'action_type': action_type,
                'left_document_id': left_document.get('document_id'),
                'right_document_ids': [tabular_document.get('document_id') for tabular_document in right_documents],
            },
        ) or '').strip(),
        'coverage': _build_tabular_document_action_coverage(tabular_documents, 'Comparison complete'),
        'documents': [],
        'left_document': {
            'document_id': left_document.get('document_id'),
            'document_name': left_document.get('document_name'),
        },
        'right_documents': [
            {
                'document_id': tabular_document.get('document_id'),
                'document_name': tabular_document.get('document_name'),
            }
            for tabular_document in right_documents
        ],
        'comparison_items': [],
    }
    if not comparison_result['analysis_reply']:
        raise RuntimeError('Tabular comparison synthesis returned an empty response.')
    comparison_result['reply'] = comparison_result['analysis_reply']
    comparison_result['documents'] = comparison_result['coverage'].get('documents', [])
    return {
        'result': comparison_result,
        'agent_citations': tabular_agent_citations,
        'generated_tabular_outputs': generated_tabular_outputs,
    }


def _build_response_preview(text, max_length=220):
    normalized = str(text or '').strip()
    if len(normalized) <= max_length:
        return normalized
    return f'{normalized[:max_length].rstrip()}...'


def _normalize_workflow_alert_text(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def _summarize_workflow_alert_text(text, max_length=140):
    normalized = _normalize_workflow_alert_text(text)
    if not normalized:
        return ''

    sentence_match = re.search(r'(.+?[.!?])(?:\s|$)', normalized)
    if sentence_match:
        sentence = sentence_match.group(1).strip()
        if 24 <= len(sentence) <= max_length:
            return sentence

    numbered_split = re.split(r'\s+\d+\.\s+', normalized, maxsplit=1)[0].strip()
    if 24 <= len(numbered_split) <= max_length:
        return numbered_split

    dash_split = re.split(r'\s+-\s+', normalized, maxsplit=1)[0].strip()
    if 24 <= len(dash_split) <= max_length:
        return dash_split

    if len(normalized) <= max_length:
        return normalized

    return f'{normalized[:max_length - 3].rstrip()}...'


def _extract_message_text(message_content):
    if isinstance(message_content, str):
        return message_content
    if isinstance(message_content, list):
        parts = []
        for item in message_content:
            if isinstance(item, dict):
                text_value = item.get('text') or item.get('content') or ''
                if text_value:
                    parts.append(str(text_value))
            elif item:
                parts.append(str(item))
        return ''.join(parts)
    return str(message_content or '')


def _extract_created_conversation_docs_from_citations(agent_citations):
    created_function_names = {
        'create_group_conversation',
        'create_personal_collaboration_conversation',
        'create_personal_conversation',
    }
    created_conversations = []
    seen_conversation_ids = set()

    for citation in agent_citations or []:
        if not isinstance(citation, dict):
            continue
        if citation.get('plugin_name') != 'SimpleChatPlugin':
            continue
        if citation.get('function_name') not in created_function_names:
            continue

        invocation_result = citation.get('function_result') if isinstance(citation.get('function_result'), dict) else {}
        conversation_doc = invocation_result.get('conversation') if isinstance(invocation_result.get('conversation'), dict) else {}
        conversation_id = str(conversation_doc.get('id') or '').strip()
        if not conversation_id or conversation_id in seen_conversation_ids:
            continue

        seen_conversation_ids.add(conversation_id)
        created_conversations.append(dict(conversation_doc))

    return created_conversations


def _is_visualization_citation(citation):
    if not isinstance(citation, dict):
        return False

    function_result = citation.get('function_result') if isinstance(citation.get('function_result'), dict) else {}
    if function_result.get('success') is False:
        return False

    return bool(
        function_result.get('render_type')
        or function_result.get('chart_markdown')
        or function_result.get('chart_payload')
        or _contains_inline_image_gallery_result(function_result)
        or _contains_inline_video_result(function_result)
    )


def _contains_inline_image_gallery_result(function_result):
    if not isinstance(function_result, dict):
        return False

    image_gallery = function_result.get('image_gallery')
    if isinstance(image_gallery, dict) and list(image_gallery.get('items') or []):
        return True

    for field_name in ('items', 'images', 'image_urls'):
        field_value = function_result.get(field_name)
        if isinstance(field_value, list) and field_value:
            return True

    image_url = function_result.get('image_url')
    if isinstance(image_url, str) and image_url.strip():
        return True
    if isinstance(image_url, dict) and str(image_url.get('url') or '').strip():
        return True

    mime_type = str(function_result.get('mime') or '').strip().lower()
    if mime_type.startswith('image/'):
        return True

    result_type = str(function_result.get('type') or '').strip().lower()
    return result_type == 'image_url'


def _contains_inline_video_result(function_result):
    if not isinstance(function_result, dict):
        return False

    video_gallery = function_result.get('video_gallery')
    if isinstance(video_gallery, dict) and list(video_gallery.get('items') or []):
        return True

    for field_name in ('items', 'videos', 'video_urls'):
        field_value = function_result.get(field_name)
        if isinstance(field_value, list) and field_value:
            return True

    video_url = function_result.get('video_url')
    if isinstance(video_url, str) and video_url.strip():
        return True
    if isinstance(video_url, dict) and str(video_url.get('url') or '').strip():
        return True

    mime_type = str(function_result.get('mime') or '').strip().lower()
    if mime_type.startswith('video/'):
        return True

    result_type = str(function_result.get('type') or '').strip().lower()
    return result_type == 'video_url'


def _filter_visualization_agent_citations(agent_citations):
    return [citation for citation in agent_citations or [] if _is_visualization_citation(citation)]


def _is_collaboration_target_conversation(conversation_doc):
    chat_type = str((conversation_doc or {}).get('chat_type') or '').strip()
    conversation_kind = str((conversation_doc or {}).get('conversation_kind') or '').strip()
    return conversation_kind == COLLABORATION_KIND or chat_type in {
        GROUP_MULTI_USER_CHAT_TYPE,
        PERSONAL_MULTI_USER_CHAT_TYPE,
    }


def _build_workflow_mirror_metadata(workflow, source_assistant_doc, previous_thread_id):
    source_metadata = source_assistant_doc.get('metadata') if isinstance(source_assistant_doc.get('metadata'), dict) else {}
    workflow_metadata = source_metadata.get('workflow') if isinstance(source_metadata.get('workflow'), dict) else {}
    return {
        'source': 'workflow_mirror',
        'workflow': {
            'workflow_id': workflow.get('id'),
            'workflow_name': workflow.get('name'),
            'runner_type': workflow.get('runner_type'),
            'trigger_source': workflow_metadata.get('trigger_source'),
            'run_id': workflow_metadata.get('run_id'),
        },
        'mirrored_from': {
            'conversation_id': source_assistant_doc.get('conversation_id'),
            'message_id': source_assistant_doc.get('id'),
        },
        'thread_info': {
            'thread_id': str(uuid.uuid4()),
            'previous_thread_id': previous_thread_id,
            'active_thread': True,
            'thread_attempt': 1,
        },
    }


def _mirror_assistant_message_to_personal_conversation(
    workflow,
    source_assistant_doc,
    target_conversation_doc,
    mirrored_agent_citations,
):
    conversation_id = str((target_conversation_doc or {}).get('id') or '').strip()
    if not conversation_id:
        return None

    try:
        conversation_doc = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
    except Exception:
        conversation_doc = dict(target_conversation_doc or {})

    mirrored_message_id = str(uuid.uuid4())
    timestamp = _utc_now_iso()
    previous_thread_id = _get_latest_thread_id(conversation_id)
    prepared_agent_citations = _persist_agent_citation_artifacts(
        conversation_id=conversation_id,
        assistant_message_id=mirrored_message_id,
        agent_citations=mirrored_agent_citations,
        created_timestamp=timestamp,
        user_info={
            'user_id': str(workflow.get('user_id') or '').strip(),
        },
    )

    mirrored_assistant_doc = {
        'id': mirrored_message_id,
        'conversation_id': conversation_id,
        'role': 'assistant',
        'content': source_assistant_doc.get('content', ''),
        'timestamp': timestamp,
        'model_deployment_name': source_assistant_doc.get('model_deployment_name'),
        'augmented': bool(source_assistant_doc.get('augmented', False)),
        'hybrid_citations': list(source_assistant_doc.get('hybrid_citations') or []),
        'web_search_citations': list(source_assistant_doc.get('web_search_citations') or []),
        'agent_citations': prepared_agent_citations,
        'agent_display_name': source_assistant_doc.get('agent_display_name'),
        'agent_name': source_assistant_doc.get('agent_name'),
        'metadata': _build_workflow_mirror_metadata(
            workflow,
            source_assistant_doc,
            previous_thread_id,
        ),
    }
    cosmos_messages_container.upsert_item(mirrored_assistant_doc)

    conversation_doc['last_updated'] = timestamp
    conversation_doc['has_unread_assistant_response'] = True
    conversation_doc['last_unread_assistant_message_id'] = mirrored_message_id
    conversation_doc['last_unread_assistant_at'] = timestamp
    cosmos_conversations_container.upsert_item(conversation_doc)

    return mirrored_assistant_doc


def _mirror_workflow_visualizations_to_created_conversations(workflow, source_assistant_doc, execution_result):
    source_assistant_doc = source_assistant_doc if isinstance(source_assistant_doc, dict) else {}
    execution_result = execution_result if isinstance(execution_result, dict) else {}
    raw_agent_citations = list(execution_result.get('agent_citations') or [])
    mirrored_agent_citations = raw_agent_citations or list(source_assistant_doc.get('agent_citations') or [])
    hybrid_citations = list(source_assistant_doc.get('hybrid_citations') or [])
    web_search_citations = list(source_assistant_doc.get('web_search_citations') or [])
    if not source_assistant_doc or not (mirrored_agent_citations or hybrid_citations or web_search_citations):
        return []

    created_conversations = _extract_created_conversation_docs_from_citations(raw_agent_citations)
    if not created_conversations:
        return []

    source_conversation_id = str(source_assistant_doc.get('conversation_id') or '').strip()
    default_sender_user = normalize_collaboration_user({
        'user_id': str(workflow.get('user_id') or '').strip(),
        'display_name': str(workflow.get('user_id') or '').strip(),
    }) or {
        'user_id': str(workflow.get('user_id') or '').strip(),
        'display_name': str(workflow.get('user_id') or '').strip() or 'Workflow user',
        'email': '',
    }
    collaboration_source_doc = {
        **source_assistant_doc,
        'agent_citations': mirrored_agent_citations,
        'hybrid_citations': hybrid_citations,
        'web_search_citations': web_search_citations,
    }
    mirrored_message_ids = []

    for created_conversation in created_conversations:
        conversation_id = str(created_conversation.get('id') or '').strip()
        if not conversation_id or conversation_id == source_conversation_id:
            continue

        try:
            if _is_collaboration_target_conversation(created_conversation):
                collaboration_conversation = get_collaboration_conversation(conversation_id)
                mirrored_message_doc, updated_conversation, created = mirror_source_message_to_collaboration(
                    collaboration_conversation,
                    collaboration_source_doc,
                    default_sender_user,
                    extra_metadata={
                        'source_conversation_id': source_conversation_id,
                        'source_thought_user_id': str(workflow.get('user_id') or '').strip(),
                        'workflow_mirror': True,
                    },
                )
                if created and mirrored_message_doc:
                    create_collaboration_message_notifications(updated_conversation, mirrored_message_doc)
                    mirrored_message_ids.append(mirrored_message_doc.get('id'))
            else:
                mirrored_message_doc = _mirror_assistant_message_to_personal_conversation(
                    workflow,
                    source_assistant_doc,
                    created_conversation,
                    mirrored_agent_citations,
                )
                if mirrored_message_doc:
                    mirrored_message_ids.append(mirrored_message_doc.get('id'))
        except Exception as exc:
            log_event(
                f'[WorkflowRunner] Failed to mirror workflow visualizations into conversation {conversation_id}: {exc}',
                extra={
                    'workflow_id': str(workflow.get('id') or '').strip(),
                    'source_message_id': str(source_assistant_doc.get('id') or '').strip(),
                    'target_conversation_id': conversation_id,
                },
                level=logging.WARNING,
                exceptionTraceback=True,
            )

    return mirrored_message_ids


WORKFLOW_ALERT_PRIORITIES = {'low', 'medium', 'high'}


def _normalize_workflow_alert_priority(priority):
    normalized = str(priority or '').strip().lower()
    if normalized not in WORKFLOW_ALERT_PRIORITIES:
        return 'none'
    return normalized


def _dedupe_workflow_alert_targets(targets):
    deduped_targets = []
    seen_keys = set()

    for target in targets or []:
        if not isinstance(target, dict):
            continue

        link_context = target.get('link_context') if isinstance(target.get('link_context'), dict) else {}
        conversation_id = str(target.get('conversation_id') or link_context.get('conversation_id') or '').strip()
        link_url = str(target.get('link_url') or '').strip()
        dedupe_key = conversation_id or link_url
        if not dedupe_key or dedupe_key in seen_keys:
            continue

        seen_keys.add(dedupe_key)
        deduped_targets.append(target)

    return deduped_targets


def _normalize_workflow_alert_target_label(label):
    normalized_label = str(label or '').strip()
    lowered_label = normalized_label.lower()
    if lowered_label.startswith('open workflow'):
        return 'Open workflow'
    if lowered_label.startswith('open created'):
        return 'Open created conversation'
    if lowered_label.startswith('open updated'):
        return 'Open conversation'
    return normalized_label or 'Open conversation'


def _is_workflow_alert_workflow_target(target):
    return str((target or {}).get('label') or '').strip().lower() == 'open workflow'


def _get_workflow_alert_target_priority(target):
    target = target if isinstance(target, dict) else {}
    label = str(target.get('label') or '').strip().lower()
    link_context = target.get('link_context') if isinstance(target.get('link_context'), dict) else {}
    workspace_type = str(link_context.get('workspace_type') or '').strip().lower()
    chat_type = str(link_context.get('chat_type') or '').strip().lower()
    conversation_kind = str(link_context.get('conversation_kind') or '').strip().lower()

    priority = 0
    if label.startswith('open created'):
        priority += 100
    elif label.startswith('open conversation'):
        priority += 60
    else:
        priority += 20

    if workspace_type == 'group' or chat_type.startswith('group'):
        priority += 40
    elif workspace_type == 'personal' and (chat_type == 'personal_multi_user' or conversation_kind == 'collaboration'):
        priority += 20
    elif workspace_type == 'personal':
        priority += 10

    return priority


def _select_preferred_workflow_alert_targets(targets):
    normalized_targets = []
    for raw_target in _dedupe_workflow_alert_targets(targets):
        normalized_target = dict(raw_target)
        normalized_target['label'] = _normalize_workflow_alert_target_label(normalized_target.get('label'))
        normalized_targets.append(normalized_target)

    workflow_target = next(
        (target for target in normalized_targets if _is_workflow_alert_workflow_target(target)),
        None,
    )
    non_workflow_targets = [
        target for target in normalized_targets
        if not _is_workflow_alert_workflow_target(target)
    ]

    selected_targets = []
    if non_workflow_targets:
        selected_targets.append(max(non_workflow_targets, key=_get_workflow_alert_target_priority))

    if workflow_target:
        if not selected_targets or selected_targets[0].get('conversation_id') != workflow_target.get('conversation_id'):
            selected_targets.append(workflow_target)

    if not selected_targets and normalized_targets:
        selected_targets.append(normalized_targets[0])

    return selected_targets


def _strip_workflow_alert_markdown(text):
    normalized_text = str(text or '').strip()
    if not normalized_text:
        return ''

    normalized_text = re.sub(r'\[([^\]]+)\]\([^\)]*\)', r'\1', normalized_text)
    normalized_text = re.sub(r'[*_`#>~]+', '', normalized_text)
    normalized_text = re.sub(r'\s+', ' ', normalized_text)
    return normalized_text.strip(' \t-:;,')


def _normalize_workflow_alert_title_text(text, max_length=110):
    normalized_text = _strip_workflow_alert_markdown(text)
    if not normalized_text:
        return ''

    normalized_text = re.sub(
        r'^\s*eguardian\s*alert\s*[:,-]?\s*',
        'eGuardian Alert, ',
        normalized_text,
        flags=re.IGNORECASE,
    )
    normalized_text = re.sub(
        r'^\s*eguardian\s*[:,-]\s*',
        'eGuardian Alert, ',
        normalized_text,
        flags=re.IGNORECASE,
    )
    normalized_text = re.sub(r'\s+', ' ', normalized_text).strip(' ,;:-')
    if len(normalized_text) > max_length:
        normalized_text = f"{normalized_text[:max_length - 3].rstrip(' ,;:-')}..."
    return normalized_text


def _extract_workflow_alert_event_title(text, max_length=90):
    normalized_text = _strip_workflow_alert_markdown(text)
    if not normalized_text:
        return ''

    numbered_match = re.search(r'(?:^|\s)\d+\.\s*([^\-:.]{3,90}?)(?=\s+-|\.|:|$)', normalized_text)
    if numbered_match:
        return _normalize_workflow_alert_title_text(numbered_match.group(1), max_length=max_length)

    heading_match = re.search(r"^([A-Z][A-Za-z0-9/&()'\s]{5,90}?)(?=\s+-|:|\.)", normalized_text)
    if heading_match:
        return _normalize_workflow_alert_title_text(heading_match.group(1), max_length=max_length)

    return ''


def _build_workflow_alert_citation_label(citation):
    if not isinstance(citation, dict):
        return ''

    explicit_label = str(citation.get('tool_name') or '').strip()
    if explicit_label:
        return explicit_label

    return build_agent_citation_tool_label(
        citation.get('plugin_name'),
        citation.get('function_name'),
        citation.get('function_arguments'),
        citation.get('function_result'),
    )


def _get_workflow_alert_enrichment_priority(citation):
    function_name = str((citation or {}).get('function_name') or '').strip()
    priority_map = {
        'create_group_conversation': 100,
        'create_personal_collaboration_conversation': 100,
        'create_personal_conversation': 100,
        'create_calendar_invite': 95,
        'create_map_visualization': 90,
        'upload_markdown_document': 85,
        'create_group': 80,
        'invite_group_conversation_members': 75,
        'mark_message_as_read': 70,
        'get_my_messages': 40,
        'search_users': 30,
        'get_user_by_email': 30,
    }
    return priority_map.get(function_name, 10)


def _build_workflow_alert_enrichment_labels(agent_citations):
    ranked_labels = []
    seen_labels = set()

    for index, citation in enumerate(agent_citations or []):
        if not isinstance(citation, dict):
            continue
        if citation.get('success') is False:
            continue

        function_name = str(citation.get('function_name') or '').strip()
        if function_name == 'add_conversation_message':
            continue

        label = _normalize_workflow_alert_text(_build_workflow_alert_citation_label(citation))
        if not label:
            continue

        dedupe_key = label.lower()
        if dedupe_key in seen_labels:
            continue

        seen_labels.add(dedupe_key)
        ranked_labels.append((
            _get_workflow_alert_enrichment_priority(citation),
            index,
            label,
        ))

    ranked_labels.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked_labels]


def _extract_workflow_alert_subject(alert_title):
    normalized_title = _normalize_workflow_alert_title_text(alert_title)
    if not normalized_title:
        return ''

    normalized_title = re.sub(
        r'^\s*eguardian\s*alert,\s*',
        '',
        normalized_title,
        flags=re.IGNORECASE,
    )
    return normalized_title.strip(' ,;:-')


def _build_workflow_alert_action_plan(agent_citations):
    action_plan = {
        'summary_labels': [],
        'ready_lines': [],
        'support_lines': [],
    }
    seen_values = {
        'summary_labels': set(),
        'ready_lines': set(),
        'support_lines': set(),
    }

    for citation in agent_citations or []:
        if not isinstance(citation, dict) or citation.get('success') is False:
            continue

        function_name = str(citation.get('function_name') or '').strip()
        function_result = citation.get('function_result') if isinstance(citation.get('function_result'), dict) else {}
        citation_label = _normalize_workflow_alert_text(_build_workflow_alert_citation_label(citation))
        summary_label = ''
        ready_line = ''
        support_line = ''

        if function_name in {
            'create_group_conversation',
            'create_personal_collaboration_conversation',
            'create_personal_conversation',
        }:
            summary_label = 'coordination conversation'
            ready_line = 'Coordination conversation created'
        elif function_name == 'create_calendar_invite':
            is_teams_briefing = (
                str(function_result.get('meeting_type') or '').strip().lower() == 'teams'
                or 'teams' in citation_label.lower()
            )
            summary_label = 'Teams briefing' if is_teams_briefing else 'briefing invite'
            ready_line = 'Teams briefing prepared' if is_teams_briefing else 'Briefing invite prepared'
        elif function_name == 'create_map_visualization':
            summary_label = 'travel map'
            ready_line = 'Travel map generated'
        elif function_name == 'upload_markdown_document':
            support_line = 'Briefing document saved'
        elif function_name == 'invite_group_conversation_members':
            support_line = 'Participants invited'
        else:
            continue

        if summary_label:
            summary_key = summary_label.lower()
            if summary_key not in seen_values['summary_labels']:
                seen_values['summary_labels'].add(summary_key)
                action_plan['summary_labels'].append(summary_label)
        if ready_line:
            ready_key = ready_line.lower()
            if ready_key not in seen_values['ready_lines']:
                seen_values['ready_lines'].add(ready_key)
                action_plan['ready_lines'].append(ready_line)
        if support_line:
            support_key = support_line.lower()
            if support_key not in seen_values['support_lines']:
                seen_values['support_lines'].add(support_key)
                action_plan['support_lines'].append(support_line)

    return action_plan


def _join_workflow_alert_labels(labels):
    normalized_labels = [str(label or '').strip() for label in labels or [] if str(label or '').strip()]
    if not normalized_labels:
        return ''
    if len(normalized_labels) == 1:
        return normalized_labels[0]
    if len(normalized_labels) == 2:
        return f'{normalized_labels[0]} and {normalized_labels[1]}'
    return f"{', '.join(normalized_labels[:-1])}, and {normalized_labels[-1]}"


def _looks_like_workflow_alert_failure_text(text):
    normalized_text = _normalize_workflow_alert_text(text).lower()
    if not normalized_text:
        return False

    failure_markers = [
        "i can't",
        'i cannot',
        "couldn't",
        'could not',
        'failed to',
        'unable to',
        'not able to',
        'do not have access',
        'permission',
        'not supported',
        'not reliably',
    ]
    return any(marker in normalized_text for marker in failure_markers)


def _extract_workflow_alert_title_from_citations(agent_citations):
    for conversation_doc in _extract_created_conversation_docs_from_citations(agent_citations):
        conversation_title = str(conversation_doc.get('title') or '').strip()
        if conversation_title:
            return _normalize_workflow_alert_title_text(conversation_title)

    for enrichment_label in _build_workflow_alert_enrichment_labels(agent_citations):
        if ': ' not in enrichment_label:
            continue
        label_detail = enrichment_label.split(': ', 1)[1].strip()
        if label_detail:
            return _normalize_workflow_alert_title_text(label_detail)

    return ''


def _build_workflow_alert_action_summary(summary_labels):
    normalized_labels = [str(label or '').strip() for label in summary_labels or [] if str(label or '').strip()]
    if not normalized_labels:
        return ''

    summary_subset = normalized_labels[:3]
    joined_labels = _join_workflow_alert_labels(summary_subset)
    verb = 'is' if len(summary_subset) == 1 else 'are'
    return f'{joined_labels[:1].upper()}{joined_labels[1:]} {verb} ready.'


def _trim_workflow_alert_summary_text(text, max_length=180):
    normalized_text = _normalize_workflow_alert_text(text)
    if not normalized_text:
        return ''
    if len(normalized_text) <= max_length:
        return normalized_text
    return f'{normalized_text[:max_length - 3].rstrip()}...'


def _build_workflow_alert_success_summary(alert_title, action_plan, response_preview, workflow_name, trigger_source):
    alert_subject = _extract_workflow_alert_subject(alert_title)
    action_summary = _build_workflow_alert_action_summary(action_plan.get('summary_labels') or [])

    if alert_subject and action_summary:
        return _trim_workflow_alert_summary_text(f'{alert_subject}. {action_summary}', max_length=180)
    if alert_subject:
        return _trim_workflow_alert_summary_text(alert_subject, max_length=180)
    if action_summary:
        return _trim_workflow_alert_summary_text(action_summary, max_length=180)

    normalized_preview = _strip_workflow_alert_markdown(response_preview)
    if normalized_preview and not _looks_like_workflow_alert_failure_text(normalized_preview):
        return _summarize_workflow_alert_text(normalized_preview)

    return _summarize_workflow_alert_text(
        f'{workflow_name} completed from the {trigger_source} trigger.'
    )


def _build_workflow_alert_success_detail(alert_title, action_plan, response_preview, workflow_name, trigger_source):
    alert_subject = _extract_workflow_alert_subject(alert_title)
    ready_lines = list(action_plan.get('ready_lines') or [])
    support_lines = list(action_plan.get('support_lines') or [])
    detail_sections = []

    if alert_subject:
        detail_sections.append(f'Focus\n{alert_subject}')

    if ready_lines:
        ready_text = '\n- '.join(ready_lines[:4])
        detail_sections.append(f'Ready now\n- {ready_text}')

    if support_lines:
        support_text = '\n- '.join(support_lines[:2])
        detail_sections.append(f'Supporting items\n- {support_text}')

    if detail_sections:
        return '\n\n'.join(detail_sections)

    normalized_preview = _strip_workflow_alert_markdown(response_preview)
    if normalized_preview and not _looks_like_workflow_alert_failure_text(normalized_preview):
        return normalized_preview

    return _normalize_workflow_alert_text(
        f'{workflow_name} completed from the {trigger_source} trigger.'
    )


def _build_workflow_alert_content(workflow, run_record, execution_result, priority):
    execution_result = execution_result if isinstance(execution_result, dict) else {}
    workflow_name = _normalize_workflow_alert_title_text(workflow.get('name') or 'Workflow') or 'Workflow'
    trigger_source = str(run_record.get('trigger_source') or 'manual').strip() or 'manual'
    success = bool(run_record.get('success'))
    response_preview = _strip_workflow_alert_markdown(run_record.get('response_preview') or '')
    reply_text = _strip_workflow_alert_markdown(execution_result.get('reply') or '')
    error_text = _strip_workflow_alert_markdown(run_record.get('error') or '')
    agent_citations = list(execution_result.get('agent_citations') or [])
    enrichment_labels = _build_workflow_alert_enrichment_labels(agent_citations)
    action_plan = _build_workflow_alert_action_plan(agent_citations)

    alert_title = _extract_workflow_alert_title_from_citations(agent_citations)
    if not alert_title:
        alert_title = _extract_workflow_alert_event_title(reply_text or response_preview)
    if not alert_title:
        alert_title = workflow_name

    if success:
        alert_summary = _build_workflow_alert_success_summary(
            alert_title,
            action_plan,
            response_preview or reply_text,
            workflow_name,
            trigger_source,
        )
        alert_detail = _build_workflow_alert_success_detail(
            alert_title,
            action_plan,
            response_preview or reply_text,
            workflow_name,
            trigger_source,
        )
        notification_title = f'{priority.capitalize()} priority workflow alert: {alert_title}'
    else:
        failure_text = error_text or response_preview or reply_text or (
            f'{workflow_name} failed from the {trigger_source} trigger.'
        )
        alert_summary = _summarize_workflow_alert_text(failure_text)
        alert_detail = _normalize_workflow_alert_text(failure_text)
        notification_title = f'{priority.capitalize()} priority workflow alert: {workflow_name} failed'

    return {
        'notification_title': notification_title,
        'notification_message': alert_summary,
        'alert_title': alert_title,
        'alert_summary': alert_summary,
        'alert_detail': alert_detail,
        'event_title': alert_title,
        'enrichment_labels': enrichment_labels,
    }


def _build_workflow_alert_target_from_conversation(conversation_doc, default_label='Open conversation'):
    conversation_doc = conversation_doc if isinstance(conversation_doc, dict) else {}
    conversation_id = str(conversation_doc.get('id') or '').strip()
    if not conversation_id:
        return None

    chat_type = str(conversation_doc.get('chat_type') or '').strip().lower()
    conversation_kind = str(conversation_doc.get('conversation_kind') or '').strip()
    scope = conversation_doc.get('scope') if isinstance(conversation_doc.get('scope'), dict) else {}
    group_id = str(scope.get('group_id') or conversation_doc.get('group_id') or '').strip()
    workspace_type = 'group' if chat_type.startswith('group') or group_id else 'personal'
    label = str(default_label or conversation_doc.get('title') or 'Open conversation').strip() or 'Open conversation'

    link_context = {
        'workspace_type': workspace_type,
        'conversation_id': conversation_id,
        'chat_type': chat_type,
    }
    if group_id:
        link_context['group_id'] = group_id
    if conversation_kind:
        link_context['conversation_kind'] = conversation_kind

    return {
        'label': label,
        'link_url': f'/chats?conversationId={conversation_id}',
        'link_context': link_context,
        'conversation_id': conversation_id,
    }


def _get_simplechat_alert_target_label(function_name):
    target_labels = {
        'create_group_conversation': 'Open created conversation',
        'create_personal_collaboration_conversation': 'Open created conversation',
        'create_personal_conversation': 'Open created conversation',
        'add_conversation_message': 'Open conversation',
    }
    return target_labels.get(str(function_name or '').strip(), 'Open related conversation')


def _collect_agent_alert_targets(user_id, conversation_id):
    if not user_id or not conversation_id:
        return []

    plugin_logger = get_plugin_logger()
    invocations = plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=100)
    alert_targets = []

    for invocation in invocations:
        if invocation.plugin_name != 'SimpleChatPlugin' or not invocation.success:
            continue

        invocation_result = invocation.result
        if not isinstance(invocation_result, dict):
            continue

        conversation_doc = invocation_result.get('conversation') if isinstance(invocation_result.get('conversation'), dict) else {}
        alert_target = _build_workflow_alert_target_from_conversation(
            conversation_doc,
            default_label=_get_simplechat_alert_target_label(invocation.function_name),
        )
        if alert_target:
            alert_targets.append(alert_target)

    return _select_preferred_workflow_alert_targets(alert_targets)


def _create_workflow_priority_alert(workflow, run_record, conversation, execution_result=None):
    execution_result = execution_result if isinstance(execution_result, dict) else {}
    priority = _normalize_workflow_alert_priority(workflow.get('alert_priority'))
    if priority == 'none':
        return None

    try:
        user_id = str(workflow.get('user_id') or '').strip()
        workflow_id = str(workflow.get('id') or '').strip()
        workflow_name = _normalize_workflow_alert_title_text(workflow.get('name') or 'Workflow') or 'Workflow'
        trigger_source = str(run_record.get('trigger_source') or 'manual').strip() or 'manual'
        workflow_targets = list(execution_result.get('alert_targets') or [])
        workflow_conversation_target = _build_workflow_alert_target_from_conversation(
            conversation,
            default_label='Open workflow',
        )
        if workflow_conversation_target:
            workflow_targets.append(workflow_conversation_target)

        workflow_targets = _select_preferred_workflow_alert_targets(workflow_targets)
        primary_target = workflow_targets[0] if workflow_targets else None
        response_preview = str(run_record.get('response_preview') or '').strip()
        error_text = str(run_record.get('error') or '').strip()
        alert_content = _build_workflow_alert_content(
            workflow,
            run_record,
            execution_result,
            priority,
        )

        metadata = {
            'workflow_id': workflow_id,
            'workflow_name': workflow_name,
            'priority': priority,
            'trigger_source': trigger_source,
            'run_id': str(run_record.get('id') or '').strip(),
            'runner_type': str(workflow.get('runner_type') or '').strip(),
            'status': str(run_record.get('status') or '').strip(),
            'conversation_id': str((conversation or {}).get('id') or run_record.get('conversation_id') or '').strip(),
            'assistant_message_id': str(run_record.get('assistant_message_id') or '').strip(),
            'response_preview': response_preview,
            'error': error_text,
            'event_title': alert_content.get('event_title'),
            'alert_title': alert_content.get('alert_title'),
            'alert_summary': alert_content.get('alert_summary'),
            'alert_detail': alert_content.get('alert_detail'),
            'alert_enrichments': alert_content.get('enrichment_labels') or [],
            'link_targets': workflow_targets,
        }
        if execution_result.get('agent_name'):
            metadata['agent_name'] = execution_result.get('agent_name')
        if execution_result.get('agent_display_name'):
            metadata['agent_display_name'] = execution_result.get('agent_display_name')

        return create_workflow_priority_notification(
            user_id=user_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            priority=priority,
            title=alert_content.get('notification_title') or f'{priority.capitalize()} priority workflow alert: {workflow_name}',
            message=alert_content.get('notification_message') or _summarize_workflow_alert_text(response_preview or error_text),
            link_url=primary_target.get('link_url') if primary_target else '',
            link_context=primary_target.get('link_context') if primary_target else {},
            metadata=metadata,
        )
    except Exception as exc:
        log_event(
            f'[WorkflowRunner] Failed to create workflow alert: {exc}',
            extra={
                'workflow_id': str(workflow.get('id') or '').strip(),
                'user_id': str(workflow.get('user_id') or '').strip(),
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None


def _resolve_authority(auth_settings):
    management_cloud = (auth_settings.get('management_cloud') or 'public').lower()
    if management_cloud in ('government', 'usgovernment', 'usgov'):
        return AzureAuthorityHosts.AZURE_GOVERNMENT
    custom_authority = auth_settings.get('custom_authority') or ''
    if custom_authority:
        return custom_authority
    return AzureAuthorityHosts.AZURE_PUBLIC_CLOUD


def _resolve_foundry_scope(auth_settings, endpoint=None):
    custom_scope = (auth_settings.get('foundry_scope') or '').strip()
    if custom_scope:
        return custom_scope

    management_cloud = (auth_settings.get('management_cloud') or 'public').lower()
    if management_cloud in ('government', 'usgovernment', 'usgov'):
        return 'https://ai.azure.us/.default'
    if management_cloud == 'china':
        return 'https://ai.azure.cn/.default'
    if management_cloud == 'germany':
        return 'https://ai.azure.de/.default'

    endpoint_value = (endpoint or '').lower()
    if 'azure.us' in endpoint_value:
        return 'https://ai.azure.us/.default'
    if 'azure.cn' in endpoint_value:
        return 'https://ai.azure.cn/.default'
    if 'azure.de' in endpoint_value:
        return 'https://ai.azure.de/.default'
    return 'https://ai.azure.com/.default'


def _build_token_provider(auth_settings, provider='aoai', endpoint=None):
    auth_type = (auth_settings.get('type') or 'managed_identity').lower()
    authority = _resolve_authority(auth_settings)

    if auth_type == 'service_principal':
        credential = ClientSecretCredential(
            tenant_id=auth_settings.get('tenant_id'),
            client_id=auth_settings.get('client_id'),
            client_secret=auth_settings.get('client_secret'),
            authority=authority,
        )
    else:
        credential = DefaultAzureCredential(
            managed_identity_client_id=auth_settings.get('managed_identity_client_id') or None,
            authority=authority,
        )

    scope = cognitive_services_scope
    if provider in ('aifoundry', 'new_foundry'):
        scope = _resolve_foundry_scope(auth_settings, endpoint=endpoint)

    return get_bearer_token_provider(credential, scope)


def _get_workflow_runner_app():
    global _workflow_runner_app
    if _workflow_runner_app is None:
        workflow_app = Flask('simplechat_workflow_runner')
        workflow_app.secret_key = SECRET_KEY
        _workflow_runner_app = workflow_app
    return _workflow_runner_app


@contextmanager
def _ensure_execution_context(user_id):
    created_context = None
    reuse_existing = False

    if has_request_context():
        session_user = session.get('user') if isinstance(session.get('user'), dict) else {}
        session_user_id = str(session_user.get('oid') or '').strip()
        reuse_existing = session_user_id == str(user_id or '').strip()

    if not reuse_existing:
        created_context = _get_workflow_runner_app().test_request_context('/api/internal/workflows/run')
        created_context.push()
        session['user'] = {
            'oid': user_id,
            'roles': ['User'],
            'preferred_username': '',
            'name': user_id,
        }

    try:
        yield
    finally:
        if created_context is not None:
            created_context.pop()


def _ensure_workflow_conversation(workflow):
    conversation_id = str(workflow.get('conversation_id') or '').strip()
    user_id = str(workflow.get('user_id') or '').strip()
    title = f"Workflow: {workflow.get('name') or 'Untitled Workflow'}"

    if conversation_id:
        try:
            conversation = cosmos_conversations_container.read_item(item=conversation_id, partition_key=conversation_id)
            cleaned = {key: value for key, value in conversation.items() if not str(key).startswith('_')}
            if cleaned.get('title') != title:
                cleaned['title'] = title
                cleaned['last_updated'] = _utc_now_iso()
                cosmos_conversations_container.upsert_item(cleaned)
            return cleaned
        except Exception:
            pass

    conversation_id = str(uuid.uuid4())
    conversation = {
        'id': conversation_id,
        'user_id': user_id,
        'last_updated': _utc_now_iso(),
        'title': title,
        'context': [],
        'tags': ['workflow'],
        'strict': False,
        'is_pinned': False,
        'is_hidden': False,
        'chat_type': 'workflow',
        'workflow_id': workflow.get('id'),
        'has_unread_assistant_response': False,
        'last_unread_assistant_message_id': None,
        'last_unread_assistant_at': None,
    }
    cosmos_conversations_container.upsert_item(conversation)
    log_conversation_creation(
        user_id=user_id,
        conversation_id=conversation_id,
        title=title,
        workspace_type='personal',
    )
    conversation['added_to_activity_log'] = True
    cosmos_conversations_container.upsert_item(conversation)
    return conversation


def _get_latest_thread_id(conversation_id):
    try:
        rows = list(cosmos_messages_container.query_items(
            query=(
                'SELECT TOP 1 c.metadata.thread_info.thread_id as thread_id '
                'FROM c WHERE c.conversation_id = @conversation_id '
                'ORDER BY c.timestamp DESC'
            ),
            parameters=[{'name': '@conversation_id', 'value': conversation_id}],
            partition_key=conversation_id,
        ))
        return rows[0].get('thread_id') if rows else None
    except Exception:
        return None


def _create_user_message(conversation_id, workflow, trigger_source, run_id):
    previous_thread_id = _get_latest_thread_id(conversation_id)
    current_thread_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    document_action = _get_document_action_config(workflow)
    metadata = {
        'source': 'workflow',
        'workflow': {
            'workflow_id': workflow.get('id'),
            'workflow_name': workflow.get('name'),
            'runner_type': workflow.get('runner_type'),
            'trigger_source': trigger_source,
            'run_id': run_id,
            'url_access_enabled': _workflow_url_access_enabled(workflow),
            'url_access_authorized': bool(workflow.get('url_access_authorized')),
            'document_action': document_action,
            'analyze': workflow.get('analyze') or {},
        },
        'thread_info': {
            'thread_id': current_thread_id,
            'previous_thread_id': previous_thread_id,
            'active_thread': True,
            'thread_attempt': 1,
        },
    }
    message_doc = {
        'id': message_id,
        'conversation_id': conversation_id,
        'role': 'user',
        'content': workflow.get('task_prompt', ''),
        'timestamp': _utc_now_iso(),
        'model_deployment_name': None,
        'metadata': metadata,
    }
    cosmos_messages_container.upsert_item(message_doc)
    return message_doc


def _initialize_workflow_assistant_tracking(conversation_id, user_id, user_message_doc):
    assistant_message_id = str(uuid.uuid4())
    user_thread_info = (user_message_doc.get('metadata') or {}).get('thread_info') or {}
    thought_tracker = ThoughtTracker(
        conversation_id=conversation_id,
        message_id=assistant_message_id,
        thread_id=user_thread_info.get('thread_id'),
        user_id=user_id,
        force_enabled=True,
    )
    return assistant_message_id, thought_tracker


def _build_workflow_activity_payload(workflow, run_id, activity_key, kind, title, status, lane_key='main', lane_label='Main'):
    return {
        'activity_key': activity_key,
        'workflow_id': workflow.get('id'),
        'run_id': run_id,
        'kind': kind,
        'title': title,
        'status': status,
        'state': status,
        'lane_key': lane_key,
        'lane_label': lane_label,
    }


def _add_workflow_activity_thought(
    thought_tracker,
    workflow,
    run_id,
    *,
    step_type,
    content,
    detail=None,
    activity_key,
    kind,
    title,
    status,
    lane_key='main',
    lane_label='Main',
):
    if not thought_tracker:
        return None

    return thought_tracker.add_thought(
        step_type,
        content,
        detail=detail,
        activity=_build_workflow_activity_payload(
            workflow,
            run_id,
            activity_key,
            kind,
            title,
            status,
            lane_key=lane_key,
            lane_label=lane_label,
        ),
    )


def _create_assistant_message(conversation, workflow, result, trigger_source, run_id, user_message_doc, assistant_message_id=None):
    assistant_message_id = assistant_message_id or str(uuid.uuid4())
    timestamp = _utc_now_iso()
    user_thread_info = (user_message_doc.get('metadata') or {}).get('thread_info') or {}
    document_action = _get_document_action_config(workflow)
    raw_agent_citations = list(result.get('agent_citations') or [])
    web_search_citations = list(result.get('web_search_citations') or [])
    source_review_metadata = result.get('source_review') if isinstance(result.get('source_review'), dict) else {}
    url_access_metadata = result.get('url_access') if isinstance(result.get('url_access'), dict) else {}
    prepared_agent_citations = _persist_agent_citation_artifacts(
        conversation_id=conversation.get('id'),
        assistant_message_id=assistant_message_id,
        agent_citations=raw_agent_citations,
        created_timestamp=timestamp,
        user_info={
            'user_id': str(workflow.get('user_id') or '').strip(),
        },
    )
    assistant_doc = {
        'id': assistant_message_id,
        'conversation_id': conversation.get('id'),
        'role': 'assistant',
        'content': result.get('reply', ''),
        'timestamp': timestamp,
        'model_deployment_name': result.get('model_deployment_name'),
        'agent_citations': prepared_agent_citations,
        'web_search_citations': web_search_citations,
        'agent_display_name': result.get('agent_display_name'),
        'agent_name': result.get('agent_name'),
        'metadata': {
            'source': 'workflow',
            'token_usage': result.get('token_usage'),
            'source_review': source_review_metadata,
            'workflow': {
                'workflow_id': workflow.get('id'),
                'workflow_name': workflow.get('name'),
                'runner_type': workflow.get('runner_type'),
                'trigger_source': trigger_source,
                'run_id': run_id,
                'url_access': url_access_metadata,
                'selected_agent': workflow.get('selected_agent') or {},
                'model_binding_summary': workflow.get('model_binding_summary') or {},
                'document_action': document_action,
                'analyze': workflow.get('analyze') or {},
                'analysis_coverage': result.get('analysis_coverage') or {},
            },
            'thread_info': {
                'thread_id': str(uuid.uuid4()),
                'previous_thread_id': user_thread_info.get('thread_id'),
                'active_thread': True,
                'thread_attempt': 1,
            },
        },
    }
    cosmos_messages_container.upsert_item(assistant_doc)

    token_usage = result.get('token_usage') if isinstance(result.get('token_usage'), dict) else None
    if token_usage and token_usage.get('total_tokens'):
        try:
            log_token_usage(
                user_id=str(workflow.get('user_id') or '').strip(),
                token_type='chat',
                total_tokens=token_usage.get('total_tokens'),
                model=result.get('model_deployment_name'),
                workspace_type='personal',
                prompt_tokens=token_usage.get('prompt_tokens'),
                completion_tokens=token_usage.get('completion_tokens'),
                conversation_id=conversation.get('id'),
                message_id=assistant_message_id,
                additional_context={
                    'workflow_id': workflow.get('id'),
                    'run_id': run_id,
                    'document_action_type': document_action.get('type'),
                    'request_count': token_usage.get('request_count'),
                },
            )
        except Exception as exc:
            debug_print(f'[WorkflowRunner] Failed to log workflow token usage: {exc}')

    conversation['last_updated'] = timestamp
    conversation['workflow_id'] = workflow.get('id')
    conversation['chat_type'] = 'workflow'
    conversation['has_unread_assistant_response'] = True
    conversation['last_unread_assistant_message_id'] = assistant_message_id
    conversation['last_unread_assistant_at'] = timestamp
    cosmos_conversations_container.upsert_item(conversation)

    return assistant_doc


def _build_multi_endpoint_client(user_id, endpoint_id, model_id, settings):
    candidates = []
    user_settings = get_user_settings(user_id)
    if settings.get('allow_user_custom_endpoints', False):
        personal_endpoints, _ = normalize_model_endpoints(
            user_settings.get('settings', {}).get('personal_model_endpoints', []) or []
        )
        for endpoint in personal_endpoints:
            item = dict(endpoint)
            item['scope'] = 'user'
            candidates.append(item)

    global_endpoints, _ = normalize_model_endpoints(settings.get('model_endpoints', []) or [])
    for endpoint in global_endpoints:
        item = dict(endpoint)
        item['scope'] = 'global'
        candidates.append(item)

    endpoint_cfg = next((candidate for candidate in candidates if candidate.get('id') == endpoint_id), None)
    if not endpoint_cfg:
        raise ValueError('Selected model endpoint was not found.')

    model_cfg = next((model for model in endpoint_cfg.get('models', []) if model.get('id') == model_id), None)
    if not model_cfg:
        raise ValueError('Selected model was not found on the endpoint.')

    scope = endpoint_cfg.get('scope', 'global')
    resolved_endpoint = keyvault_model_endpoint_get_helper(
        endpoint_cfg,
        endpoint_cfg.get('id'),
        scope=scope,
        return_type=SecretReturnType.VALUE,
    )
    connection = resolved_endpoint.get('connection', {}) if isinstance(resolved_endpoint, dict) else {}
    auth = resolved_endpoint.get('auth', {}) if isinstance(resolved_endpoint, dict) else {}
    provider = str(resolved_endpoint.get('provider') or endpoint_cfg.get('provider') or 'aoai').strip().lower()
    deployment_name = (
        model_cfg.get('deploymentName')
        or model_cfg.get('deployment')
        or model_cfg.get('displayName')
        or model_id
    )
    api_version = connection.get('api_version') or connection.get('openai_api_version') or settings.get('azure_openai_gpt_api_version')
    endpoint = connection.get('endpoint')
    auth_type = str(auth.get('type') or 'api_key').strip().lower()

    if auth_type in ('key', 'api_key'):
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=auth.get('api_key'),
            api_version=api_version,
        )
    else:
        auth_settings = {
            'type': auth_type,
            'tenant_id': auth.get('tenant_id'),
            'client_id': auth.get('client_id'),
            'client_secret': auth.get('client_secret'),
            'managed_identity_client_id': auth.get('managed_identity_client_id'),
            'management_cloud': auth.get('management_cloud') or settings.get('management_cloud') or 'public',
            'custom_authority': auth.get('custom_authority') or settings.get('custom_authority') or '',
            'foundry_scope': auth.get('foundry_scope') or '',
        }
        token_provider = _build_token_provider(auth_settings, provider=provider, endpoint=endpoint)
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
            api_version=api_version,
        )

    return client, deployment_name, provider


def _build_legacy_default_client(settings):
    if settings.get('enable_gpt_apim', False):
        endpoint = settings.get('azure_apim_gpt_endpoint')
        deployment_name = settings.get('azure_apim_gpt_deployment')
        api_key = settings.get('azure_apim_gpt_subscription_key')
        api_version = settings.get('azure_apim_gpt_api_version') or settings.get('azure_openai_gpt_api_version')
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        return client, deployment_name, 'aoai'

    endpoint = settings.get('azure_openai_gpt_endpoint')
    deployment_name = settings.get('azure_openai_gpt_deployment')
    api_version = settings.get('azure_openai_gpt_api_version')
    api_key = settings.get('azure_openai_gpt_key')
    auth_type = str(settings.get('azure_openai_gpt_authentication_type') or 'key').strip().lower()
    if isinstance(deployment_name, str) and ',' in deployment_name:
        deployment_name = deployment_name.split(',')[0].strip()

    if auth_type in ('key', 'api_key') or api_key:
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        return client, deployment_name, 'aoai'

    auth_settings = {
        'type': auth_type,
        'tenant_id': settings.get('azure_openai_gpt_tenant_id') or settings.get('azure_openai_tenant_id'),
        'client_id': settings.get('azure_openai_gpt_client_id') or settings.get('azure_openai_client_id'),
        'client_secret': settings.get('azure_openai_gpt_client_secret') or settings.get('azure_openai_client_secret'),
        'managed_identity_client_id': settings.get('azure_openai_gpt_managed_identity_client_id') or settings.get('azure_openai_managed_identity_client_id'),
        'management_cloud': settings.get('management_cloud') or settings.get('azure_management_cloud') or 'public',
        'custom_authority': settings.get('custom_authority') or settings.get('azure_custom_authority') or '',
    }
    token_provider = _build_token_provider(auth_settings, provider='aoai', endpoint=endpoint)
    client = AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version=api_version,
    )
    return client, deployment_name, 'aoai'


def _resolve_model_workflow_client(workflow, settings):
    user_id = str(workflow.get('user_id') or '').strip()
    binding_summary = workflow.get('model_binding_summary') if isinstance(workflow.get('model_binding_summary'), dict) else {}
    endpoint_id = str(workflow.get('model_endpoint_id') or binding_summary.get('endpoint_id') or '').strip()
    model_id = str(workflow.get('model_id') or binding_summary.get('model_id') or '').strip()
    legacy_model_deployment = str(workflow.get('legacy_model_deployment') or '').strip()

    if endpoint_id and model_id:
        return _build_multi_endpoint_client(user_id, endpoint_id, model_id, settings)

    if legacy_model_deployment:
        client, _, provider = _build_legacy_default_client(settings)
        return client, legacy_model_deployment, provider

    default_selection = settings.get('default_model_selection', {}) if isinstance(settings, dict) else {}
    default_endpoint_id = str(default_selection.get('endpoint_id') or '').strip()
    default_model_id = str(default_selection.get('model_id') or '').strip()
    if default_endpoint_id and default_model_id:
        return _build_multi_endpoint_client(user_id, default_endpoint_id, default_model_id, settings)

    return _build_legacy_default_client(settings)


def _chain_activity_callbacks(*callbacks):
    active_callbacks = [callback for callback in callbacks if callable(callback)]
    if not active_callbacks:
        return None

    def callback(event):
        for activity_callback in active_callbacks:
            try:
                activity_callback(event)
            except Exception as exc:
                log_event(
                    f'[WorkflowRunner] Document analysis activity callback failed: {exc}',
                    level=logging.WARNING,
                    exceptionTraceback=True,
                )

    return callback


def _get_document_action_config(workflow):
    settings = get_settings()
    return get_document_action_config(
        workflow,
        max_documents_by_type=get_document_action_max_documents_by_type(
            DOCUMENT_ACTION_CONTEXT_WORKFLOW,
            settings=settings,
        ),
        allowed_action_types=get_enabled_document_action_types(settings=settings),
    )


def _build_document_action_activity_callback(workflow, run_id, thought_tracker=None):
    if not thought_tracker or not run_id:
        return None

    def callback(event):
        event_type = str((event or {}).get('type') or '').strip().lower()
        document_id = str((event or {}).get('document_id') or '').strip()
        document_name = str((event or {}).get('document_name') or 'Document').strip() or 'Document'
        window_range = (event or {}).get('window_range') if isinstance((event or {}).get('window_range'), dict) else {}
        window_number = window_range.get('window_number')

        if event_type == 'document_started':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Started analysis for {document_name}',
                detail=f"windows={event.get('window_count', 0)}",
                activity_key=f'analysis:{run_id}:{document_id}',
                kind='document_analysis',
                title='Document analysis',
                status='running',
            )
        elif event_type == 'window_started':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Analyzing window {window_number} for {document_name}',
                detail=f"attempt={event.get('attempt_number', 1)}",
                activity_key=f'analysis:{run_id}:{document_id}:window:{window_number}',
                kind='document_analysis',
                title='Document analysis',
                status='running',
            )
        elif event_type == 'window_retry':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Retrying window {window_number} for {document_name}',
                detail=f"attempt={event.get('attempt_number', 1)}",
                activity_key=f'analysis:{run_id}:{document_id}:window:{window_number}',
                kind='document_analysis',
                title='Document analysis',
                status='running',
            )
        elif event_type == 'window_completed':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Completed window {window_number} for {document_name}',
                detail=(
                    f"processed={event.get('processed_windows', 0)} | "
                    f"failed={event.get('failed_windows', 0)}"
                ),
                activity_key=f'analysis:{run_id}:{document_id}:window:{window_number}',
                kind='document_analysis',
                title='Document analysis',
                status='completed',
            )
        elif event_type == 'document_completed':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Completed analysis for {document_name}',
                detail=(
                    f"processed={event.get('processed_windows', 0)} | "
                    f"failed={event.get('failed_windows', 0)}"
                ),
                activity_key=f'analysis:{run_id}:{document_id}',
                kind='document_analysis',
                title='Document analysis',
                status='completed',
            )
        elif event_type == 'window_failed':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Failed analysis window {window_number} for {document_name}',
                detail=str(event.get('error') or 'Unknown analysis failure'),
                activity_key=f'analysis:{run_id}:{document_id}:window:{window_number}:failed',
                kind='document_analysis',
                title='Document analysis',
                status='failed',
            )
        elif event_type == 'reduction_started':
            reduction_step_index = event.get('reduction_step_index')
            reduction_step_total = event.get('reduction_step_total')
            reduction_detail = None
            if reduction_step_index is not None and reduction_step_total:
                reduction_detail = f'batch={reduction_step_index}/{reduction_step_total}'

            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content='Combining analysis findings into the final response',
                detail=reduction_detail,
                activity_key=f'analysis:{run_id}:reduction',
                kind='document_analysis',
                title='Document analysis',
                status='running',
            )
        elif event_type == 'reduction_completed':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content='Finished combining analysis findings into the final response',
                detail=f"documents={event.get('document_count', 0)}",
                activity_key=f'analysis:{run_id}:reduction',
                kind='document_analysis',
                title='Document analysis',
                status='completed',
            )
        elif event_type == 'comparison_started':
            right_document_name = str((event or {}).get('right_document_name') or 'Document').strip() or 'Document'
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Comparing {document_name} to {right_document_name}',
                detail=(
                    f"pair={event.get('comparison_index', 0)}/{event.get('comparison_count', 0)}"
                ),
                activity_key=f"compare:{run_id}:{document_id}:{event.get('right_document_id')}",
                kind='document_analysis',
                title='Document comparison',
                status='running',
            )
        elif event_type == 'comparison_completed':
            right_document_name = str((event or {}).get('right_document_name') or 'Document').strip() or 'Document'
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Completed comparison of {document_name} to {right_document_name}',
                detail=(
                    f"pair={event.get('comparison_index', 0)}/{event.get('comparison_count', 0)}"
                ),
                activity_key=f"compare:{run_id}:{document_id}:{event.get('right_document_id')}",
                kind='document_analysis',
                title='Document comparison',
                status='completed',
            )
        elif event_type == 'comparison_reduction_started':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content='Combining comparison findings across the selected documents',
                detail=f"pairs={event.get('comparison_count', 0)}",
                activity_key=f'compare:{run_id}:reduction',
                kind='document_analysis',
                title='Document comparison',
                status='running',
            )
        elif event_type == 'comparison_reduction_completed':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content='Finished combining comparison findings across the selected documents',
                detail=f"pairs={event.get('comparison_count', 0)}",
                activity_key=f'compare:{run_id}:reduction',
                kind='document_analysis',
                title='Document comparison',
                status='completed',
            )

    return callback


def _resolve_document_action_reply(result):
    result = result if isinstance(result, dict) else {}
    analysis_reply = str(result.get('analysis_reply') or '').strip()
    if analysis_reply:
        return analysis_reply
    return str(result.get('reply') or '').strip()


def _execute_model_workflow(workflow, settings, run_id=None, thought_tracker=None, url_access_context=None):
    if thought_tracker and run_id:
        _add_workflow_activity_thought(
            thought_tracker,
            workflow,
            run_id,
            step_type='generation',
            content='Starting direct model execution',
            detail=None,
            activity_key=f'generation:{run_id}',
            kind='model_execution',
            title='Model execution',
            status='running',
        )

    client, deployment_name, provider = _resolve_model_workflow_client(workflow, settings)

    completion = client.chat.completions.create(
        model=deployment_name,
        messages=_build_workflow_chat_messages(
            workflow.get('task_prompt', ''),
            url_access_context=url_access_context,
            apply_generation_guidance=True,
        ),
    )
    reply = ''
    if getattr(completion, 'choices', None):
        reply = _extract_message_text(completion.choices[0].message.content)

    if thought_tracker and run_id:
        _add_workflow_activity_thought(
            thought_tracker,
            workflow,
            run_id,
            step_type='generation',
            content=f'Direct model execution completed with {deployment_name}',
            detail=f'provider={provider}',
            activity_key=f'generation:{run_id}',
            kind='model_execution',
            title='Model execution',
            status='completed',
        )

    return {
        'reply': reply,
        'model_deployment_name': deployment_name,
        'provider': provider,
    }


def _execute_document_analysis_workflow(
    workflow,
    settings,
    conversation_id='',
    run_id=None,
    thought_tracker=None,
    external_activity_callback=None,
    action_config=None,
    url_access_context=None,
):
    analysis_config = action_config if isinstance(action_config, dict) else _get_document_action_config(workflow)
    if analysis_config.get('type') != DOCUMENT_ACTION_TYPE_ANALYZE:
        raise ValueError('Document analysis is not enabled for this workflow.')
    workflow_analysis_max_documents = get_document_action_max_documents(
        DOCUMENT_ACTION_TYPE_ANALYZE,
        DOCUMENT_ACTION_CONTEXT_WORKFLOW,
        settings=settings,
    )

    activity_callback = _chain_activity_callbacks(
        _build_document_action_activity_callback(workflow, run_id, thought_tracker=thought_tracker),
        external_activity_callback,
    )
    user_id = str(workflow.get('user_id') or '').strip()
    selected_agent = workflow.get('selected_agent') if isinstance(workflow.get('selected_agent'), dict) else {}
    debug_print(
        '[WorkflowDocumentAnalysis] Starting workflow action | '
        f"workflow_id={workflow.get('id')} | "
        f'run_id={run_id} | '
        f"runner_type={workflow.get('runner_type')} | "
        f'conversation_id={conversation_id} | '
        f"documents={len(analysis_config.get('document_ids') or [])} | "
        f'max_documents={workflow_analysis_max_documents}'
    )
    token_usage_aggregate = _create_token_usage_aggregate()

    if workflow.get('runner_type') == 'agent':
        with _ensure_execution_context(user_id):
            plugin_logger = get_plugin_logger()
            previous_force_enable_agents = getattr(g, 'force_enable_agents', None) if hasattr(g, 'force_enable_agents') else None
            previous_request_agent_info = getattr(g, 'request_agent_info', None) if hasattr(g, 'request_agent_info') else None
            previous_request_agent_name = getattr(g, 'request_agent_name', None) if hasattr(g, 'request_agent_name') else None
            previous_conversation_id = getattr(g, 'conversation_id', None) if hasattr(g, 'conversation_id') else None

            g.force_enable_agents = True
            g.request_agent_info = dict(selected_agent)
            g.request_agent_name = selected_agent.get('name')
            callback_key = None
            if conversation_id:
                plugin_logger.clear_invocations_for_conversation(user_id, conversation_id)
                g.conversation_id = conversation_id

            try:
                kernel = Kernel()
                kernel, agent_objs = load_user_semantic_kernel(kernel, settings, user_id, None)
                if not agent_objs:
                    raise ValueError('The selected agent could not be loaded for analysis.')

                loaded_agent = None
                requested_name = str(selected_agent.get('name') or '').strip()
                if requested_name:
                    loaded_agent = agent_objs.get(requested_name)
                if loaded_agent is None:
                    loaded_agent = next(iter(agent_objs.values()))

                if thought_tracker and run_id and conversation_id:
                    callback_key = register_plugin_invocation_thought_callback(
                        plugin_logger,
                        thought_tracker,
                        user_id,
                        conversation_id,
                        actor_label='Workflow agent',
                    )

                def invoke_prompt(prompt_text, stage='window_analysis', metadata=None):
                    result = asyncio.run(loaded_agent.invoke(_build_workflow_agent_messages(
                        prompt_text,
                        url_access_context=url_access_context,
                    )))
                    _accumulate_token_usage(token_usage_aggregate, result)
                    return str(result)

                tabular_action_payload = _maybe_execute_tabular_document_action(
                    DOCUMENT_ACTION_TYPE_ANALYZE,
                    workflow,
                    analysis_config,
                    settings,
                    conversation_id=conversation_id,
                    invoke_prompt=invoke_prompt,
                    thought_tracker=thought_tracker,
                    live_thought_callback=external_activity_callback,
                )
                if tabular_action_payload:
                    analysis_result = tabular_action_payload.get('result') or {}
                else:
                    analysis_result = run_document_analysis(
                        user_id=user_id,
                        analysis_prompt=workflow.get('task_prompt', ''),
                        document_ids=analysis_config.get('document_ids'),
                        invoke_prompt=invoke_prompt,
                        doc_scope=analysis_config.get('doc_scope'),
                        active_group_ids=analysis_config.get('active_group_ids'),
                        active_public_workspace_id=analysis_config.get('active_public_workspace_id'),
                        window_unit=analysis_config.get('window_unit'),
                        window_size=analysis_config.get('window_size'),
                        window_percent=analysis_config.get('window_percent'),
                        max_retries_per_window=analysis_config.get('max_retries_per_window'),
                        activity_callback=activity_callback,
                        max_documents=workflow_analysis_max_documents,
                    )
                document_analysis_artifact_payload = _maybe_create_document_analysis_generated_artifacts(
                    analysis_result,
                    workflow.get('task_prompt', ''),
                    conversation_id=conversation_id,
                    primary_generated_outputs=list((tabular_action_payload or {}).get('generated_tabular_outputs') or []),
                )
                agent_citations = _build_agent_citations_from_invocations(user_id, conversation_id)
                if not agent_citations:
                    agent_citations = list((tabular_action_payload or {}).get('agent_citations') or [])
                alert_targets = _collect_agent_alert_targets(user_id, conversation_id)
                token_usage = _finalize_token_usage(token_usage_aggregate)

                return {
                    'reply': (
                        document_analysis_artifact_payload.get('assistant_reply')
                        or _resolve_document_action_reply(analysis_result)
                    ),
                    'analysis_result': analysis_result,
                    'analysis_coverage': analysis_result.get('coverage') or {},
                    'generated_analysis_artifacts': document_analysis_artifact_payload.get('artifacts', []),
                    'model_deployment_name': getattr(loaded_agent, 'deployment_name', None) or requested_name,
                    'token_usage': token_usage,
                    'provider': 'agent',
                    'agent_name': getattr(loaded_agent, 'name', None) or requested_name,
                    'agent_display_name': getattr(loaded_agent, 'display_name', None) or selected_agent.get('display_name') or requested_name,
                    'agent_citations': agent_citations,
                    'generated_tabular_outputs': list((tabular_action_payload or {}).get('generated_tabular_outputs') or []),
                    'alert_targets': alert_targets,
                }
            finally:
                if callback_key:
                    plugin_logger.deregister_callbacks(callback_key)
                if previous_force_enable_agents is None and hasattr(g, 'force_enable_agents'):
                    delattr(g, 'force_enable_agents')
                else:
                    g.force_enable_agents = previous_force_enable_agents

                if previous_request_agent_info is None and hasattr(g, 'request_agent_info'):
                    delattr(g, 'request_agent_info')
                else:
                    g.request_agent_info = previous_request_agent_info

                if previous_request_agent_name is None and hasattr(g, 'request_agent_name'):
                    delattr(g, 'request_agent_name')
                else:
                    g.request_agent_name = previous_request_agent_name

                if previous_conversation_id is None and hasattr(g, 'conversation_id'):
                    delattr(g, 'conversation_id')
                else:
                    g.conversation_id = previous_conversation_id

    client, deployment_name, provider = _resolve_model_workflow_client(workflow, settings)

    def invoke_model_prompt(prompt_text, stage='window_analysis', metadata=None):
        completion = client.chat.completions.create(
            model=deployment_name,
            messages=_build_workflow_chat_messages(
                prompt_text,
                url_access_context=url_access_context,
            ),
        )
        _accumulate_token_usage(token_usage_aggregate, completion)
        if not getattr(completion, 'choices', None):
            return ''
        return _extract_message_text(completion.choices[0].message.content)

    tabular_action_payload = _maybe_execute_tabular_document_action(
        DOCUMENT_ACTION_TYPE_ANALYZE,
        workflow,
        analysis_config,
        settings,
        conversation_id=conversation_id,
        invoke_prompt=invoke_model_prompt,
        thought_tracker=thought_tracker,
        live_thought_callback=external_activity_callback,
    )
    if tabular_action_payload:
        analysis_result = tabular_action_payload.get('result') or {}
    else:
        analysis_result = run_document_analysis(
            user_id=user_id,
            analysis_prompt=workflow.get('task_prompt', ''),
            document_ids=analysis_config.get('document_ids'),
            invoke_prompt=invoke_model_prompt,
            doc_scope=analysis_config.get('doc_scope'),
            active_group_ids=analysis_config.get('active_group_ids'),
            active_public_workspace_id=analysis_config.get('active_public_workspace_id'),
            window_unit=analysis_config.get('window_unit'),
            window_size=analysis_config.get('window_size'),
            window_percent=analysis_config.get('window_percent'),
            max_retries_per_window=analysis_config.get('max_retries_per_window'),
            activity_callback=activity_callback,
            max_documents=workflow_analysis_max_documents,
        )
    document_analysis_artifact_payload = _maybe_create_document_analysis_generated_artifacts(
        analysis_result,
        workflow.get('task_prompt', ''),
        conversation_id=conversation_id,
        primary_generated_outputs=list((tabular_action_payload or {}).get('generated_tabular_outputs') or []),
    )
    token_usage = _finalize_token_usage(token_usage_aggregate)
    debug_print(
        '[WorkflowDocumentAnalysis] Completed workflow action | '
        f"workflow_id={workflow.get('id')} | "
        f'run_id={run_id} | '
        f'provider={provider} | '
        f'model={deployment_name} | '
        f"total_tokens={(token_usage or {}).get('total_tokens', 0)} | "
        f"processed_windows={(analysis_result.get('coverage') or {}).get('processed_windows', 0)} | "
        f"failed_windows={(analysis_result.get('coverage') or {}).get('failed_windows', 0)}"
    )
    return {
        'reply': (
            document_analysis_artifact_payload.get('assistant_reply')
            or _resolve_document_action_reply(analysis_result)
        ),
        'analysis_result': analysis_result,
        'analysis_coverage': analysis_result.get('coverage') or {},
        'generated_analysis_artifacts': document_analysis_artifact_payload.get('artifacts', []),
        'model_deployment_name': deployment_name,
        'token_usage': token_usage,
        'provider': provider,
        'agent_citations': list((tabular_action_payload or {}).get('agent_citations') or []),
        'generated_tabular_outputs': list((tabular_action_payload or {}).get('generated_tabular_outputs') or []),
    }


def _execute_document_comparison_workflow(
    workflow,
    settings,
    conversation_id='',
    run_id=None,
    thought_tracker=None,
    external_activity_callback=None,
    action_config=None,
    url_access_context=None,
):
    comparison_config = action_config if isinstance(action_config, dict) else _get_document_action_config(workflow)
    if comparison_config.get('type') != DOCUMENT_ACTION_TYPE_COMPARISON:
        raise ValueError('Document comparison is not enabled for this workflow.')

    activity_callback = _chain_activity_callbacks(
        _build_document_action_activity_callback(workflow, run_id, thought_tracker=thought_tracker),
        external_activity_callback,
    )
    user_id = str(workflow.get('user_id') or '').strip()
    selected_agent = workflow.get('selected_agent') if isinstance(workflow.get('selected_agent'), dict) else {}
    debug_print(
        '[WorkflowDocumentComparison] Starting workflow action | '
        f"workflow_id={workflow.get('id')} | "
        f'run_id={run_id} | '
        f"runner_type={workflow.get('runner_type')} | "
        f'conversation_id={conversation_id} | '
        f"left_document_id={comparison_config.get('left_document_id')} | "
        f"right_count={len(comparison_config.get('right_document_ids') or [])}"
    )
    token_usage_aggregate = _create_token_usage_aggregate()

    if workflow.get('runner_type') == 'agent':
        with _ensure_execution_context(user_id):
            plugin_logger = get_plugin_logger()
            previous_force_enable_agents = getattr(g, 'force_enable_agents', None) if hasattr(g, 'force_enable_agents') else None
            previous_request_agent_info = getattr(g, 'request_agent_info', None) if hasattr(g, 'request_agent_info') else None
            previous_request_agent_name = getattr(g, 'request_agent_name', None) if hasattr(g, 'request_agent_name') else None
            previous_conversation_id = getattr(g, 'conversation_id', None) if hasattr(g, 'conversation_id') else None

            g.force_enable_agents = True
            g.request_agent_info = dict(selected_agent)
            g.request_agent_name = selected_agent.get('name')
            callback_key = None
            if conversation_id:
                plugin_logger.clear_invocations_for_conversation(user_id, conversation_id)
                g.conversation_id = conversation_id

            try:
                kernel = Kernel()
                kernel, agent_objs = load_user_semantic_kernel(kernel, settings, user_id, None)
                if not agent_objs:
                    raise ValueError('The selected agent could not be loaded for document comparison.')

                loaded_agent = None
                requested_name = str(selected_agent.get('name') or '').strip()
                if requested_name:
                    loaded_agent = agent_objs.get(requested_name)
                if loaded_agent is None:
                    loaded_agent = next(iter(agent_objs.values()))

                if thought_tracker and run_id and conversation_id:
                    callback_key = register_plugin_invocation_thought_callback(
                        plugin_logger,
                        thought_tracker,
                        user_id,
                        conversation_id,
                        actor_label='Workflow agent',
                    )

                def invoke_prompt(prompt_text, stage='window_analysis', metadata=None):
                    result = asyncio.run(loaded_agent.invoke(_build_workflow_agent_messages(
                        prompt_text,
                        url_access_context=url_access_context,
                    )))
                    _accumulate_token_usage(token_usage_aggregate, result)
                    return str(result)

                tabular_action_payload = _maybe_execute_tabular_document_action(
                    DOCUMENT_ACTION_TYPE_COMPARISON,
                    workflow,
                    comparison_config,
                    settings,
                    conversation_id=conversation_id,
                    invoke_prompt=invoke_prompt,
                    thought_tracker=thought_tracker,
                    live_thought_callback=external_activity_callback,
                )
                if tabular_action_payload:
                    comparison_result = tabular_action_payload.get('result') or {}
                else:
                    comparison_result = run_document_comparison(
                        user_id=user_id,
                        comparison_prompt=workflow.get('task_prompt', ''),
                        action_config=comparison_config,
                        invoke_prompt=invoke_prompt,
                        activity_callback=activity_callback,
                        conversation_id=conversation_id,
                    )
                comparison_artifact_payload = _maybe_create_comparison_generated_artifacts(
                    comparison_result,
                    workflow.get('task_prompt', ''),
                    conversation_id=conversation_id,
                )
                agent_citations = _build_agent_citations_from_invocations(user_id, conversation_id)
                if not agent_citations:
                    agent_citations = list((tabular_action_payload or {}).get('agent_citations') or [])
                alert_targets = _collect_agent_alert_targets(user_id, conversation_id)
                token_usage = _finalize_token_usage(token_usage_aggregate)

                return {
                    'reply': (
                        comparison_artifact_payload.get('assistant_reply')
                        or _resolve_document_action_reply(comparison_result)
                    ),
                    'analysis_result': comparison_result,
                    'analysis_coverage': comparison_result.get('coverage') or {},
                    'generated_analysis_artifacts': comparison_artifact_payload.get('artifacts', []),
                    'model_deployment_name': getattr(loaded_agent, 'deployment_name', None) or requested_name,
                    'token_usage': token_usage,
                    'provider': 'agent',
                    'agent_name': getattr(loaded_agent, 'name', None) or requested_name,
                    'agent_display_name': getattr(loaded_agent, 'display_name', None) or selected_agent.get('display_name') or requested_name,
                    'agent_citations': agent_citations,
                    'generated_tabular_outputs': list((tabular_action_payload or {}).get('generated_tabular_outputs') or []),
                    'alert_targets': alert_targets,
                }
            finally:
                if callback_key:
                    plugin_logger.deregister_callbacks(callback_key)
                if previous_force_enable_agents is None and hasattr(g, 'force_enable_agents'):
                    delattr(g, 'force_enable_agents')
                else:
                    g.force_enable_agents = previous_force_enable_agents

                if previous_request_agent_info is None and hasattr(g, 'request_agent_info'):
                    delattr(g, 'request_agent_info')
                else:
                    g.request_agent_info = previous_request_agent_info

                if previous_request_agent_name is None and hasattr(g, 'request_agent_name'):
                    delattr(g, 'request_agent_name')
                else:
                    g.request_agent_name = previous_request_agent_name

                if previous_conversation_id is None and hasattr(g, 'conversation_id'):
                    delattr(g, 'conversation_id')
                else:
                    g.conversation_id = previous_conversation_id

    client, deployment_name, provider = _resolve_model_workflow_client(workflow, settings)

    def invoke_model_prompt(prompt_text, stage='window_analysis', metadata=None):
        completion = client.chat.completions.create(
            model=deployment_name,
            messages=_build_workflow_chat_messages(
                prompt_text,
                url_access_context=url_access_context,
            ),
        )
        _accumulate_token_usage(token_usage_aggregate, completion)
        if not getattr(completion, 'choices', None):
            return ''
        return _extract_message_text(completion.choices[0].message.content)

    tabular_action_payload = _maybe_execute_tabular_document_action(
        DOCUMENT_ACTION_TYPE_COMPARISON,
        workflow,
        comparison_config,
        settings,
        conversation_id=conversation_id,
        invoke_prompt=invoke_model_prompt,
        thought_tracker=thought_tracker,
        live_thought_callback=external_activity_callback,
    )
    if tabular_action_payload:
        comparison_result = tabular_action_payload.get('result') or {}
    else:
        comparison_result = run_document_comparison(
            user_id=user_id,
            comparison_prompt=workflow.get('task_prompt', ''),
            action_config=comparison_config,
            invoke_prompt=invoke_model_prompt,
            activity_callback=activity_callback,
            conversation_id=conversation_id,
        )
    comparison_artifact_payload = _maybe_create_comparison_generated_artifacts(
        comparison_result,
        workflow.get('task_prompt', ''),
        conversation_id=conversation_id,
    )
    token_usage = _finalize_token_usage(token_usage_aggregate)
    debug_print(
        '[WorkflowDocumentComparison] Completed workflow action | '
        f"workflow_id={workflow.get('id')} | "
        f'run_id={run_id} | '
        f'provider={provider} | '
        f'model={deployment_name} | '
        f"total_tokens={(token_usage or {}).get('total_tokens', 0)} | "
        f"processed_windows={(comparison_result.get('coverage') or {}).get('processed_windows', 0)} | "
        f"failed_windows={(comparison_result.get('coverage') or {}).get('failed_windows', 0)}"
    )
    return {
        'reply': (
            comparison_artifact_payload.get('assistant_reply')
            or _resolve_document_action_reply(comparison_result)
        ),
        'analysis_result': comparison_result,
        'analysis_coverage': comparison_result.get('coverage') or {},
        'generated_analysis_artifacts': comparison_artifact_payload.get('artifacts', []),
        'model_deployment_name': deployment_name,
        'token_usage': token_usage,
        'provider': provider,
        'agent_citations': list((tabular_action_payload or {}).get('agent_citations') or []),
        'generated_tabular_outputs': list((tabular_action_payload or {}).get('generated_tabular_outputs') or []),
    }


def _execute_document_action_workflow(
    workflow,
    settings,
    conversation_id='',
    run_id=None,
    thought_tracker=None,
    external_activity_callback=None,
    url_access_context=None,
):
    action_config = _get_document_action_config(workflow)
    action_type = action_config.get('type')
    debug_print(
        '[WorkflowDocumentAction] Dispatching action | '
        f"workflow_id={workflow.get('id')} | "
        f'run_id={run_id} | '
        f'action_type={action_type} | '
        f"runner_type={workflow.get('runner_type')} | "
        f'conversation_id={conversation_id}'
    )

    try:
        if action_type == DOCUMENT_ACTION_TYPE_ANALYZE:
            result = _execute_document_analysis_workflow(
                workflow,
                settings,
                conversation_id=conversation_id,
                run_id=run_id,
                thought_tracker=thought_tracker,
                external_activity_callback=external_activity_callback,
                action_config=action_config,
                url_access_context=url_access_context,
            )
        elif action_type == DOCUMENT_ACTION_TYPE_COMPARISON:
            result = _execute_document_comparison_workflow(
                workflow,
                settings,
                conversation_id=conversation_id,
                run_id=run_id,
                thought_tracker=thought_tracker,
                external_activity_callback=external_activity_callback,
                action_config=action_config,
                url_access_context=url_access_context,
            )
        else:
            raise ValueError('No document action is enabled for this workflow.')
    except Exception as exc:
        debug_print(
            '[WorkflowDocumentAction] Action failed | '
            f"workflow_id={workflow.get('id')} | "
            f'run_id={run_id} | '
            f'action_type={action_type} | '
            f"runner_type={workflow.get('runner_type')} | "
            f'error={exc}'
        )
        raise

    debug_print(
        '[WorkflowDocumentAction] Action completed | '
        f"workflow_id={workflow.get('id')} | "
        f'run_id={run_id} | '
        f'action_type={action_type} | '
        f"provider={result.get('provider')} | "
        f"model={result.get('model_deployment_name')} | "
        f"processed_windows={(result.get('analysis_coverage') or {}).get('processed_windows', 0)} | "
        f"failed_windows={(result.get('analysis_coverage') or {}).get('failed_windows', 0)}"
    )
    return result


def _execute_agent_workflow(workflow, settings, conversation_id='', run_id=None, thought_tracker=None, url_access_context=None):
    user_id = str(workflow.get('user_id') or '').strip()
    selected_agent = workflow.get('selected_agent') if isinstance(workflow.get('selected_agent'), dict) else {}
    if not selected_agent:
        raise ValueError('No selected agent is configured for this workflow.')

    with _ensure_execution_context(user_id):
        plugin_logger = get_plugin_logger()
        previous_force_enable_agents = getattr(g, 'force_enable_agents', None) if hasattr(g, 'force_enable_agents') else None
        previous_request_agent_info = getattr(g, 'request_agent_info', None) if hasattr(g, 'request_agent_info') else None
        previous_request_agent_name = getattr(g, 'request_agent_name', None) if hasattr(g, 'request_agent_name') else None
        previous_conversation_id = getattr(g, 'conversation_id', None) if hasattr(g, 'conversation_id') else None

        g.force_enable_agents = True
        g.request_agent_info = dict(selected_agent)
        g.request_agent_name = selected_agent.get('name')
        callback_key = None
        if conversation_id:
            plugin_logger.clear_invocations_for_conversation(user_id, conversation_id)
            g.conversation_id = conversation_id

        if thought_tracker and run_id:
            agent_label = selected_agent.get('display_name') or selected_agent.get('name') or 'Agent'
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='generation',
                content=f'Starting agent workflow with {agent_label}',
                detail=f'agent={agent_label}',
                activity_key=f'agent:{run_id}',
                kind='agent_execution',
                title='Agent execution',
                status='running',
            )

        if thought_tracker and run_id and conversation_id:
            callback_key = register_plugin_invocation_thought_callback(
                plugin_logger,
                thought_tracker,
                user_id,
                conversation_id,
                actor_label='Workflow agent',
            )

        try:
            kernel = Kernel()
            kernel, agent_objs = load_user_semantic_kernel(kernel, settings, user_id, None)
            if not agent_objs:
                raise ValueError('The selected agent could not be loaded for workflow execution.')

            loaded_agent = None
            requested_name = str(selected_agent.get('name') or '').strip()
            if requested_name:
                loaded_agent = agent_objs.get(requested_name)
            if loaded_agent is None:
                loaded_agent = next(iter(agent_objs.values()))

            result = asyncio.run(loaded_agent.invoke(_build_workflow_agent_messages(
                workflow.get('task_prompt', ''),
                url_access_context=url_access_context,
                apply_generation_guidance=True,
            )))
            reply = str(result)
            agent_citations = _build_agent_citations_from_invocations(user_id, conversation_id)
            alert_targets = _collect_agent_alert_targets(user_id, conversation_id)

            if thought_tracker and run_id:
                _add_workflow_activity_thought(
                    thought_tracker,
                    workflow,
                    run_id,
                    step_type='generation',
                    content='Agent workflow completed',
                    detail=f"agent={getattr(loaded_agent, 'display_name', None) or getattr(loaded_agent, 'name', None) or requested_name}",
                    activity_key=f'agent:{run_id}',
                    kind='agent_execution',
                    title='Agent execution',
                    status='completed',
                )

            return {
                'reply': reply,
                'model_deployment_name': getattr(loaded_agent, 'deployment_name', None) or requested_name,
                'provider': 'agent',
                'agent_name': getattr(loaded_agent, 'name', None) or requested_name,
                'agent_display_name': getattr(loaded_agent, 'display_name', None) or selected_agent.get('display_name') or requested_name,
                'agent_citations': agent_citations,
                'alert_targets': alert_targets,
            }
        finally:
            if callback_key:
                plugin_logger.deregister_callbacks(callback_key)
            if previous_force_enable_agents is None and hasattr(g, 'force_enable_agents'):
                delattr(g, 'force_enable_agents')
            else:
                g.force_enable_agents = previous_force_enable_agents

            if previous_request_agent_info is None and hasattr(g, 'request_agent_info'):
                delattr(g, 'request_agent_info')
            else:
                g.request_agent_info = previous_request_agent_info

            if previous_request_agent_name is None and hasattr(g, 'request_agent_name'):
                delattr(g, 'request_agent_name')
            else:
                g.request_agent_name = previous_request_agent_name

            if previous_conversation_id is None and hasattr(g, 'conversation_id'):
                delattr(g, 'conversation_id')
            else:
                g.conversation_id = previous_conversation_id


def run_personal_workflow(workflow, trigger_source='manual', user_roles=None):
    """Execute a personal workflow and persist a run record."""
    workflow = workflow if isinstance(workflow, dict) else {}
    user_id = str(workflow.get('user_id') or '').strip()
    workflow_id = str(workflow.get('id') or '').strip()
    run_id = str(uuid.uuid4())
    started_at = _utc_now_iso()
    settings = get_settings()

    run_record = {
        'id': run_id,
        'workflow_id': workflow_id,
        'workflow_name': workflow.get('name'),
        'runner_type': workflow.get('runner_type'),
        'trigger_type': workflow.get('trigger_type'),
        'trigger_source': trigger_source,
        'status': 'running',
        'success': False,
        'started_at': started_at,
        'completed_at': None,
        'conversation_id': workflow.get('conversation_id'),
        'response_preview': '',
        'error': '',
    }
    save_personal_workflow_run(user_id, run_record)

    conversation = None
    thought_tracker = None
    try:
        conversation = _ensure_workflow_conversation(workflow)
        run_record['conversation_id'] = conversation.get('id')
        user_message_doc = _create_user_message(conversation.get('id'), workflow, trigger_source, run_id)
        assistant_message_id, thought_tracker = _initialize_workflow_assistant_tracking(
            conversation.get('id'),
            user_id,
            user_message_doc,
        )
        run_record['user_message_id'] = user_message_doc.get('id')
        run_record['assistant_message_id'] = assistant_message_id
        save_personal_workflow_run(user_id, run_record)

        _add_workflow_activity_thought(
            thought_tracker,
            workflow,
            run_id,
            step_type='workflow',
            content='Workflow run started',
            detail=f'trigger_source={trigger_source}',
            activity_key=f'run:{run_id}',
            kind='workflow_run',
            title='Workflow run',
            status='running',
        )

        url_access_context = _prepare_workflow_url_access_context(
            workflow,
            settings,
            conversation.get('id'),
            run_id,
            thought_tracker=thought_tracker,
            user_roles=user_roles,
        )
        document_action = _get_document_action_config(workflow)
        if document_action.get('type') != DOCUMENT_ACTION_TYPE_NONE:
            execution_result = _execute_document_action_workflow(
                workflow,
                settings,
                conversation_id=conversation.get('id'),
                run_id=run_id,
                thought_tracker=thought_tracker,
                url_access_context=url_access_context,
            )
        elif workflow.get('runner_type') == 'agent':
            execution_result = _execute_agent_workflow(
                workflow,
                settings,
                conversation_id=conversation.get('id'),
                run_id=run_id,
                thought_tracker=thought_tracker,
                url_access_context=url_access_context,
            )
        else:
            execution_result = _execute_model_workflow(
                workflow,
                settings,
                run_id=run_id,
                thought_tracker=thought_tracker,
                url_access_context=url_access_context,
            )
        execution_result = _attach_workflow_url_access_result(execution_result, url_access_context)

        assistant_doc = _create_assistant_message(
            conversation,
            workflow,
            execution_result,
            trigger_source,
            run_id,
            user_message_doc,
            assistant_message_id=assistant_message_id,
        )
        _mirror_workflow_visualizations_to_created_conversations(
            workflow,
            assistant_doc,
            execution_result,
        )

        _add_workflow_activity_thought(
            thought_tracker,
            workflow,
            run_id,
            step_type='workflow',
            content='Workflow run completed',
            detail=f"message_id={assistant_doc.get('id')}",
            activity_key=f'run:{run_id}',
            kind='workflow_run',
            title='Workflow run',
            status='completed',
        )

        completed_at = _utc_now_iso()
        run_record.update({
            'status': 'completed',
            'success': True,
            'completed_at': completed_at,
            'conversation_id': conversation.get('id'),
            'user_message_id': user_message_doc.get('id'),
            'assistant_message_id': assistant_doc.get('id'),
            'model_deployment_name': execution_result.get('model_deployment_name'),
            'agent_name': execution_result.get('agent_name'),
            'agent_display_name': execution_result.get('agent_display_name'),
            'analysis_coverage': execution_result.get('analysis_coverage') or {},
            'url_access': execution_result.get('url_access') or {},
            'source_review': execution_result.get('source_review') or {},
            'response_preview': _build_response_preview(execution_result.get('reply')),
            'error': '',
        })
        save_personal_workflow_run(user_id, run_record)
        log_workflow_run(
            user_id=user_id,
            workflow_id=workflow_id,
            workflow_name=workflow.get('name', ''),
            status='completed',
            trigger_source=trigger_source,
            run_id=run_id,
            conversation_id=conversation.get('id'),
            runner_type=workflow.get('runner_type'),
        )
        alert_notification = _create_workflow_priority_alert(
            workflow,
            run_record,
            conversation,
            execution_result=execution_result,
        )

        return {
            'success': True,
            'run': run_record,
            'notification': alert_notification,
            'workflow_updates': {
                'conversation_id': conversation.get('id'),
                'last_run_started_at': started_at,
                'last_run_at': completed_at,
                'last_run_status': 'completed',
                'last_run_error': '',
                'last_run_response_preview': run_record.get('response_preview', ''),
                'last_run_trigger_source': trigger_source,
                'run_count': int(workflow.get('run_count') or 0) + 1,
            },
        }
    except Exception as exc:
        if thought_tracker:
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='workflow',
                content='Workflow run failed',
                detail=str(exc),
                activity_key=f'run:{run_id}',
                kind='workflow_run',
                title='Workflow run',
                status='failed',
            )
        completed_at = _utc_now_iso()
        run_record.update({
            'status': 'failed',
            'success': False,
            'completed_at': completed_at,
            'error': str(exc),
            'response_preview': '',
        })
        save_personal_workflow_run(user_id, run_record)
        log_workflow_run(
            user_id=user_id,
            workflow_id=workflow_id,
            workflow_name=workflow.get('name', ''),
            status='failed',
            trigger_source=trigger_source,
            run_id=run_id,
            conversation_id=run_record.get('conversation_id'),
            runner_type=workflow.get('runner_type'),
            error=str(exc),
        )
        log_event(
            f'[WorkflowRunner] Workflow execution failed: {exc}',
            extra={
                'workflow_id': workflow_id,
                'workflow_name': workflow.get('name'),
                'user_id': user_id,
                'trigger_source': trigger_source,
            },
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        alert_notification = _create_workflow_priority_alert(
            workflow,
            run_record,
            conversation,
        )
        return {
            'success': False,
            'run': run_record,
            'notification': alert_notification,
            'workflow_updates': {
                'last_run_started_at': started_at,
                'last_run_at': completed_at,
                'last_run_status': 'failed',
                'last_run_error': str(exc),
                'last_run_response_preview': '',
                'last_run_trigger_source': trigger_source,
                'run_count': int(workflow.get('run_count') or 0) + 1,
                'conversation_id': run_record.get('conversation_id'),
            },
        }