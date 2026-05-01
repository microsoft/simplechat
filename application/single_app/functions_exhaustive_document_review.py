# functions_exhaustive_document_review.py
"""Shared exhaustive document review services."""

import logging
from typing import Any, Callable, Dict, List, Optional

from functions_appinsights import log_event
from functions_debug import debug_print
from functions_search import normalize_search_id_list, normalize_search_scope


DEFAULT_WINDOW_UNIT = 'pages'
DEFAULT_MAX_RETRIES_PER_WINDOW = 1
DEFAULT_REDUCTION_BATCH_SIZE = 5
DEFAULT_MAX_REDUCTION_ROUNDS = 4
CHAT_EXHAUSTIVE_REVIEW_MAX_DOCUMENTS = 3
WORKFLOW_EXHAUSTIVE_REVIEW_MAX_DOCUMENTS = 10


def _get_search_service_helpers():
    from functions_search_service import build_document_chunk_windows, get_document_chunks_payload

    return build_document_chunk_windows, get_document_chunks_payload


def _coerce_int(value, default_value, min_value=None, max_value=None):
    try:
        normalized_value = int(value)
    except (TypeError, ValueError):
        normalized_value = default_value

    if normalized_value is None:
        return None

    if min_value is not None and normalized_value < min_value:
        if default_value is None:
            normalized_value = min_value
        else:
            normalized_value = min_value if default_value < min_value else default_value
    if max_value is not None and normalized_value > max_value:
        normalized_value = max_value
    return normalized_value


def _count_chunk_pages(chunks):
    return len({chunk.get('page_number') for chunk in chunks if chunk.get('page_number') is not None})


def _calculate_progress_percent(completed_value, total_value, fallback_complete=False):
    try:
        resolved_total = int(total_value or 0)
        resolved_completed = int(completed_value or 0)
    except (TypeError, ValueError):
        resolved_total = 0
        resolved_completed = 0

    if resolved_total > 0:
        return max(0, min(100, int(round((resolved_completed / resolved_total) * 100))))
    return 100 if fallback_complete else 0


def _resolve_document_file_name(document_payload):
    if not isinstance(document_payload, dict):
        return ''
    return str(document_payload.get('file_name') or '').strip()


def _resolve_document_title(document_payload):
    if not isinstance(document_payload, dict):
        return ''
    return str(document_payload.get('title') or '').strip()


def _resolve_document_name(document_payload):
    if not isinstance(document_payload, dict):
        return 'Document'

    return (
        _resolve_document_file_name(document_payload)
        or _resolve_document_title(document_payload)
        or str(document_payload.get('id') or '').strip()
        or 'Document'
    )


def _build_progress_snapshot(coverage):
    coverage = coverage if isinstance(coverage, dict) else {}
    document_summaries = coverage.get('documents', []) if isinstance(coverage.get('documents'), list) else []
    completed_documents = 0
    running_documents = 0
    pending_documents = 0
    documents = []

    for document_summary in document_summaries:
        status = str(document_summary.get('status') or 'pending').strip().lower() or 'pending'
        if status in {'completed', 'completed_with_failures'}:
            completed_documents += 1
        elif status == 'running':
            running_documents += 1
        else:
            pending_documents += 1

        completed_windows = document_summary.get('processed_windows', 0) + document_summary.get('failed_windows', 0)
        completed_chunks = document_summary.get('processed_chunks', 0) + document_summary.get('failed_chunks', 0)
        total_chunks = document_summary.get('total_chunks', 0)
        total_windows = document_summary.get('total_windows', 0)
        progress_total = total_chunks or total_windows
        progress_completed = completed_chunks if total_chunks else completed_windows

        documents.append({
            'document_id': document_summary.get('document_id'),
            'document_name': document_summary.get('document_name'),
            'file_name': document_summary.get('file_name'),
            'title': document_summary.get('title'),
            'scope': document_summary.get('scope'),
            'scope_id': document_summary.get('scope_id'),
            'status': status,
            'status_text': document_summary.get('status_text'),
            'total_windows': total_windows,
            'processed_windows': document_summary.get('processed_windows', 0),
            'failed_windows': document_summary.get('failed_windows', 0),
            'completed_windows': completed_windows,
            'total_chunks': total_chunks,
            'processed_chunks': document_summary.get('processed_chunks', 0),
            'failed_chunks': document_summary.get('failed_chunks', 0),
            'completed_chunks': completed_chunks,
            'total_pages': document_summary.get('total_pages', 0),
            'active_window_number': document_summary.get('active_window_number'),
            'active_attempt_number': document_summary.get('active_attempt_number'),
            'percent': _calculate_progress_percent(
                progress_completed,
                progress_total,
                fallback_complete=status in {'completed', 'completed_with_failures'},
            ),
        })

    completed_windows = coverage.get('processed_windows', 0) + coverage.get('failed_windows', 0)
    completed_chunks = coverage.get('processed_chunks', 0) + coverage.get('failed_chunks', 0)
    overall_total = coverage.get('total_chunks', 0) or coverage.get('total_windows', 0)
    overall_completed = completed_chunks if coverage.get('total_chunks', 0) else completed_windows

    return {
        'overall': {
            'document_count': coverage.get('document_count', 0),
            'completed_documents': completed_documents,
            'running_documents': running_documents,
            'pending_documents': pending_documents,
            'total_windows': coverage.get('total_windows', 0),
            'processed_windows': coverage.get('processed_windows', 0),
            'failed_windows': coverage.get('failed_windows', 0),
            'completed_windows': completed_windows,
            'total_chunks': coverage.get('total_chunks', 0),
            'processed_chunks': coverage.get('processed_chunks', 0),
            'failed_chunks': coverage.get('failed_chunks', 0),
            'completed_chunks': completed_chunks,
            'retries': coverage.get('retries', 0),
            'window_unit': coverage.get('window_unit'),
            'percent': _calculate_progress_percent(
                overall_completed,
                overall_total,
                fallback_complete=bool(coverage.get('document_count')) and completed_documents >= coverage.get('document_count', 0),
            ),
        },
        'documents': documents,
    }


def build_document_review_progress_snapshot(coverage):
    return _build_progress_snapshot(coverage)


def normalize_exhaustive_review_targets(
    document_ids,
    doc_scope='all',
    active_group_ids=None,
    active_public_workspace_id=None,
    window_unit=DEFAULT_WINDOW_UNIT,
    window_size=None,
    window_percent=None,
    max_retries_per_window=DEFAULT_MAX_RETRIES_PER_WINDOW,
    max_documents=None,
):
    normalized_document_ids = normalize_search_id_list(document_ids)
    if not normalized_document_ids:
        raise ValueError('At least one document id is required for exhaustive review.')
    if max_documents is not None and len(normalized_document_ids) > max_documents:
        raise ValueError(
            f'Exhaustive review supports up to {max_documents} '
            f"document{'s' if max_documents != 1 else ''} at a time."
        )

    normalized_scope = normalize_search_scope(doc_scope)
    normalized_window_unit = str(window_unit or DEFAULT_WINDOW_UNIT).strip().lower()
    if normalized_window_unit not in ('pages', 'chunks'):
        normalized_window_unit = DEFAULT_WINDOW_UNIT

    normalized_window_size = None
    if window_size not in (None, ''):
        normalized_window_size = _coerce_int(window_size, None, min_value=1, max_value=100)

    normalized_window_percent = None
    if window_percent not in (None, ''):
        normalized_window_percent = _coerce_int(window_percent, None, min_value=1, max_value=100)

    normalized_max_retries = _coerce_int(
        max_retries_per_window,
        DEFAULT_MAX_RETRIES_PER_WINDOW,
        min_value=0,
        max_value=5,
    )

    return {
        'document_ids': normalized_document_ids,
        'doc_scope': normalized_scope,
        'active_group_ids': normalize_search_id_list(active_group_ids),
        'active_public_workspace_id': normalize_search_id_list(active_public_workspace_id),
        'window_unit': normalized_window_unit,
        'window_size': normalized_window_size,
        'window_percent': normalized_window_percent,
        'max_retries_per_window': normalized_max_retries,
    }


def _render_window_source_text(window_payload):
    source_parts = []
    for chunk in window_payload.get('chunks', []):
        chunk_text = str(chunk.get('chunk_text') or '').strip()
        if not chunk_text:
            continue

        chunk_labels = []
        if chunk.get('page_number') is not None:
            chunk_labels.append(f"Page {chunk.get('page_number')}")
        if chunk.get('chunk_sequence') is not None:
            chunk_labels.append(f"Chunk {chunk.get('chunk_sequence')}")
        prefix = f"[{', '.join(chunk_labels)}] " if chunk_labels else ''
        source_parts.append(f"{prefix}{chunk_text}")

    return '\n\n'.join(source_parts)


def _serialize_window_range(window_payload):
    return {
        'window_number': window_payload.get('window_number'),
        'window_unit': window_payload.get('window_unit'),
        'start_page': window_payload.get('start_page'),
        'end_page': window_payload.get('end_page'),
        'start_chunk_sequence': window_payload.get('start_chunk_sequence'),
        'end_chunk_sequence': window_payload.get('end_chunk_sequence'),
        'page_count': window_payload.get('page_count', 0),
        'chunk_count': window_payload.get('chunk_count', 0),
    }


def _build_window_label(document_name, window_range):
    if window_range.get('start_page') is not None and window_range.get('end_page') is not None:
        range_label = f"pages {window_range.get('start_page')} to {window_range.get('end_page')}"
    else:
        range_label = (
            f"chunks {window_range.get('start_chunk_sequence')} to {window_range.get('end_chunk_sequence')}"
        )
    return f"{document_name} - window {window_range.get('window_number')} ({range_label})"


def _build_window_review_prompt(review_prompt, document_payload, window_payload, window_range):
    document_file_name = _resolve_document_file_name(document_payload)
    document_title = _resolve_document_title(document_payload)
    document_name = _resolve_document_name(document_payload)
    range_label = _build_window_label(document_name, window_range)
    display_title_line = ''
    if document_title and document_title != document_name:
        display_title_line = f'Display title: {document_title}\n'

    return (
        'You are completing a deterministic document review. Review only the supplied document excerpt. '
        'Do not assume that missing details appear elsewhere in the document. If the excerpt is insufficient '
        'for a conclusion, say so explicitly. When you need to name the source document in a table, '
        'summary, or citation, use the preferred source name below and do not substitute an internal GUID '\
        'or document identifier.\n\n'
        f'Preferred source name: {document_name}\n'
        f'Source filename: {document_file_name or document_name}\n'
        f'{display_title_line}'
        f'Scope: {document_payload.get("scope")}\n'
        f'Coverage slice: {range_label}\n'
        f'Chunk count in slice: {window_range.get("chunk_count", 0)}\n'
        f'Page count in slice: {window_range.get("page_count", 0)}\n\n'
        'Task instructions:\n'
        f'{review_prompt}\n\n'
        'Write a focused review of this slice. Preserve concrete facts, decisions, comments, action items, '
        'and open questions. Call out anything that still needs follow-up.\n\n'
        f'<DocumentSlice>\n{_render_window_source_text(window_payload)}\n</DocumentSlice>'
    )


def _build_reduction_prompt(review_prompt, items, stage_label, failed_range_labels):
    combined_sections = []
    for item in items:
        combined_sections.append(
            f"[{item.get('label')}]\n{item.get('text', '')}"
        )
    combined_text = '\n\n'.join(combined_sections)

    failed_note = ''
    if failed_range_labels:
        failed_note = (
            'Some windows failed during earlier processing. Treat those slices as uncovered gaps and mention '
            'them explicitly in the final answer if they matter. Failed slices: '
            f"{'; '.join(failed_range_labels)}\n\n"
        )

    return (
        'You are consolidating exhaustive document review outputs. Preserve material findings, unresolved '
        'questions, and any coverage caveats. Do not drop important issues just to make the answer shorter.\n\n'
        f'Stage: {stage_label}\n'
        f'Task instructions:\n{review_prompt}\n\n'
        f'{failed_note}'
        'Combine the review notes below into one coherent answer.\n\n'
        f'<WindowReviews>\n{combined_text}\n</WindowReviews>'
    )


def _build_reduction_batches(items, batch_size):
    reduction_batches = []
    for start_index in range(0, len(items), batch_size):
        reduction_batches.append(items[start_index:start_index + batch_size])
    return reduction_batches


def _format_coverage_summary(coverage):
    lines = [
        '## Coverage',
        f"- Documents reviewed: {coverage.get('document_count', 0)}",
        f"- Total windows: {coverage.get('total_windows', 0)}",
        f"- Processed windows: {coverage.get('processed_windows', 0)}",
        f"- Failed windows: {coverage.get('failed_windows', 0)}",
        f"- Total chunks: {coverage.get('total_chunks', 0)}",
        f"- Processed chunks: {coverage.get('processed_chunks', 0)}",
        f"- Failed chunks: {coverage.get('failed_chunks', 0)}",
        f"- Retries used: {coverage.get('retries', 0)}",
        f"- Window unit: {coverage.get('window_unit')}",
    ]

    document_summaries = coverage.get('documents', [])
    if document_summaries:
        lines.append('')
        lines.append('### Document Coverage')
        for document_summary in document_summaries:
            coverage_document_name = (
                document_summary.get('file_name')
                or document_summary.get('document_name')
                or document_summary.get('document_id')
                or 'Document'
            )
            lines.append(
                '- '
                f"{coverage_document_name}: "
                f"{document_summary.get('processed_windows', 0)}/{document_summary.get('total_windows', 0)} windows processed, "
                f"{document_summary.get('processed_chunks', 0)}/{document_summary.get('total_chunks', 0)} chunks completed"
            )
            failed_ranges = document_summary.get('failed_ranges', [])
            if failed_ranges:
                lines.append(f"  Failed ranges: {', '.join(failed_ranges)}")

    return '\n'.join(lines)


def run_exhaustive_document_review(
    user_id,
    review_prompt,
    document_ids,
    invoke_prompt,
    doc_scope='all',
    active_group_ids=None,
    active_public_workspace_id=None,
    window_unit=DEFAULT_WINDOW_UNIT,
    window_size=None,
    window_percent=None,
    max_retries_per_window=DEFAULT_MAX_RETRIES_PER_WINDOW,
    reduction_batch_size=DEFAULT_REDUCTION_BATCH_SIZE,
    max_reduction_rounds=DEFAULT_MAX_REDUCTION_ROUNDS,
    activity_callback=None,
    max_documents=None,
    include_coverage_summary=True,
):
    normalized_review_prompt = str(review_prompt or '').strip()
    if not normalized_review_prompt:
        raise ValueError('A review prompt is required for exhaustive document review.')
    if not callable(invoke_prompt):
        raise ValueError('A callable invoke_prompt handler is required for exhaustive document review.')

    build_document_chunk_windows, get_document_chunks_payload = _get_search_service_helpers()

    targets = normalize_exhaustive_review_targets(
        document_ids=document_ids,
        doc_scope=doc_scope,
        active_group_ids=active_group_ids,
        active_public_workspace_id=active_public_workspace_id,
        window_unit=window_unit,
        window_size=window_size,
        window_percent=window_percent,
        max_retries_per_window=max_retries_per_window,
        max_documents=max_documents,
    )

    reduction_batch_size = _coerce_int(
        reduction_batch_size,
        DEFAULT_REDUCTION_BATCH_SIZE,
        min_value=2,
        max_value=8,
    )
    max_reduction_rounds = _coerce_int(
        max_reduction_rounds,
        DEFAULT_MAX_REDUCTION_ROUNDS,
        min_value=1,
        max_value=8,
    )

    debug_print(
        '[ExhaustiveReview] Starting review | '
        f'user_id={user_id} | '
        f"documents={len(targets.get('document_ids', []))} | "
        f"doc_scope={targets.get('doc_scope')} | "
        f"window_unit={targets.get('window_unit')} | "
        f"window_size={targets.get('window_size')} | "
        f"window_percent={targets.get('window_percent')} | "
        f"max_retries={targets.get('max_retries_per_window')} | "
        f'prompt_chars={len(normalized_review_prompt)}'
    )

    coverage = {
        'document_count': 0,
        'total_windows': 0,
        'processed_windows': 0,
        'failed_windows': 0,
        'total_chunks': 0,
        'processed_chunks': 0,
        'failed_chunks': 0,
        'retries': 0,
        'window_unit': targets.get('window_unit'),
        'documents': [],
    }
    document_runs = []
    reduction_items = []
    failed_range_labels = []

    for document_index, document_id in enumerate(targets.get('document_ids', []), start=1):
        document_payload = get_document_chunks_payload(
            document_id=document_id,
            user_id=user_id,
            doc_scope=targets.get('doc_scope'),
            active_group_ids=targets.get('active_group_ids'),
            active_public_workspace_id=targets.get('active_public_workspace_id'),
            window_unit=targets.get('window_unit'),
            window_size=targets.get('window_size'),
            window_percent=targets.get('window_percent'),
        )
        windows = build_document_chunk_windows(
            document_payload.get('chunks', []),
            window_unit=targets.get('window_unit'),
            window_size=targets.get('window_size'),
            window_percent=targets.get('window_percent'),
        )

        document_metadata = document_payload.get('document') if isinstance(document_payload.get('document'), dict) else {}
        document_file_name = _resolve_document_file_name(document_metadata)
        document_title = _resolve_document_title(document_metadata)
        document_name = _resolve_document_name(document_metadata)

        document_summary = {
            'document_id': document_id,
            'document_name': document_name,
            'file_name': document_file_name,
            'title': document_title,
            'scope': document_payload.get('scope'),
            'scope_id': document_payload.get('scope_id'),
            'total_windows': len(windows),
            'processed_windows': 0,
            'failed_windows': 0,
            'total_chunks': int(document_payload.get('chunk_count') or len(document_payload.get('chunks', [])) or 0),
            'processed_chunks': 0,
            'failed_chunks': 0,
            'total_pages': _count_chunk_pages(document_payload.get('chunks', [])),
            'status': 'pending',
            'status_text': 'Queued',
            'active_window_number': None,
            'active_attempt_number': None,
            'failed_ranges': [],
            'ranges': [],
        }
        coverage['documents'].append(document_summary)
        coverage['document_count'] += 1
        coverage['total_windows'] += len(windows)
        coverage['total_chunks'] += document_summary.get('total_chunks', 0)
        document_runs.append({
            'document_id': document_id,
            'document_index': document_index,
            'document_payload': document_payload,
            'document_name': document_name,
            'document_summary': document_summary,
            'windows': windows,
        })

    for document_run in document_runs:
        document_id = document_run.get('document_id')
        document_payload = document_run.get('document_payload') or {}
        document_name = document_run.get('document_name')
        document_summary = document_run.get('document_summary') or {}
        windows = document_run.get('windows') or []
        document_index = document_run.get('document_index') or 1
        debug_print(
            '[ExhaustiveReview] Starting document | '
            f'document_index={document_index} | '
            f"document_count={coverage.get('document_count', 0)} | "
            f'document_id={document_id} | '
            f'document_name={document_name} | '
            f"windows={len(windows)} | "
            f"chunks={document_summary.get('total_chunks', 0)} | "
            f"pages={document_summary.get('total_pages', 0)}"
        )
        document_summary['status'] = 'running'
        document_summary['status_text'] = f"Starting document {document_index} of {coverage.get('document_count', 0)}"
        if callable(activity_callback):
            activity_callback({
                'type': 'document_started',
                'document_id': document_id,
                'document_index': document_index,
                'document_count': coverage.get('document_count', 0),
                'document_name': document_name,
                'window_count': len(windows),
                'chunk_count': document_summary.get('total_chunks', 0),
                'page_count': document_summary.get('total_pages', 0),
                'progress': _build_progress_snapshot(coverage),
            })

        for window_payload in windows:
            window_range = _serialize_window_range(window_payload)
            document_summary['ranges'].append(window_range)
            window_label = _build_window_label(document_name, window_range)
            debug_print(
                '[ExhaustiveReview] Starting window | '
                f'document_id={document_id} | '
                f'document_name={document_name} | '
                f"window={window_range.get('window_number')} | "
                f"chunk_count={window_range.get('chunk_count', 0)} | "
                f"page_range={window_range.get('page_start')}:{window_range.get('page_end')}"
            )
            document_summary['active_window_number'] = window_range.get('window_number')
            document_summary['active_attempt_number'] = 1
            document_summary['status_text'] = (
                f"Reviewing window {window_range.get('window_number')} of {document_summary.get('total_windows', 0)}"
            )

            if callable(activity_callback):
                activity_callback({
                    'type': 'window_started',
                    'document_id': document_id,
                    'document_name': document_name,
                    'window_range': window_range,
                    'progress': _build_progress_snapshot(coverage),
                })

            review_text = ''
            last_error = ''
            max_attempts = targets.get('max_retries_per_window', DEFAULT_MAX_RETRIES_PER_WINDOW) + 1
            for attempt_number in range(1, max_attempts + 1):
                if attempt_number > 1:
                    coverage['retries'] += 1

                try:
                    prompt_text = _build_window_review_prompt(
                        normalized_review_prompt,
                        document_payload.get('document', {}),
                        window_payload,
                        window_range,
                    )
                    review_text = str(invoke_prompt(
                        prompt_text,
                        stage='window_review',
                        metadata={
                            'document_id': document_id,
                            'document_name': document_name,
                            'window_range': window_range,
                            'attempt_number': attempt_number,
                        },
                    ) or '').strip()
                    if not review_text:
                        raise ValueError('The review runner returned an empty response.')
                    break
                except Exception as exc:
                    last_error = str(exc)
                    debug_print(
                        '[ExhaustiveReview] Window attempt failed | '
                        f'document_id={document_id} | '
                        f'document_name={document_name} | '
                        f"window={window_range.get('window_number')} | "
                        f'attempt={attempt_number}/{max_attempts} | '
                        f'will_retry={attempt_number < max_attempts} | '
                        f'error={last_error}'
                    )
                    document_summary['active_window_number'] = window_range.get('window_number')
                    document_summary['active_attempt_number'] = attempt_number
                    document_summary['status_text'] = (
                        f"Retrying window {window_range.get('window_number')} after attempt {attempt_number}"
                        if attempt_number < max_attempts
                        else f"Window {window_range.get('window_number')} failed"
                    )
                    if callable(activity_callback):
                        activity_callback({
                            'type': 'window_retry' if attempt_number < max_attempts else 'window_failed',
                            'document_id': document_id,
                            'document_name': document_name,
                            'window_range': window_range,
                            'attempt_number': attempt_number,
                            'error': last_error,
                            'progress': _build_progress_snapshot(coverage),
                        })
                    if attempt_number >= max_attempts:
                        break

            if review_text:
                debug_print(
                    '[ExhaustiveReview] Completed window | '
                    f'document_id={document_id} | '
                    f'document_name={document_name} | '
                    f"window={window_range.get('window_number')} | "
                    f"chunk_count={window_range.get('chunk_count', 0)}"
                )
                coverage['processed_windows'] += 1
                coverage['processed_chunks'] += window_range.get('chunk_count', 0) or 0
                document_summary['processed_windows'] += 1
                document_summary['processed_chunks'] += window_range.get('chunk_count', 0) or 0
                document_summary['status_text'] = (
                    f"Completed window {window_range.get('window_number')} of {document_summary.get('total_windows', 0)}"
                )
                document_summary['active_attempt_number'] = None
                reduction_items.append({
                    'label': window_label,
                    'text': review_text,
                    'document_id': document_id,
                    'document_name': document_name,
                    'window_range': window_range,
                })
                if callable(activity_callback):
                    activity_callback({
                        'type': 'window_completed',
                        'document_id': document_id,
                        'document_name': document_name,
                        'window_range': window_range,
                        'progress': _build_progress_snapshot(coverage),
                    })
            else:
                debug_print(
                    '[ExhaustiveReview] Window failed | '
                    f'document_id={document_id} | '
                    f'document_name={document_name} | '
                    f"window={window_range.get('window_number')} | "
                    f'error={last_error or "unknown"}'
                )
                coverage['failed_windows'] += 1
                coverage['failed_chunks'] += window_range.get('chunk_count', 0) or 0
                document_summary['failed_windows'] += 1
                document_summary['failed_chunks'] += window_range.get('chunk_count', 0) or 0
                document_summary['failed_ranges'].append(window_label)
                document_summary['status_text'] = (
                    f"Failed window {window_range.get('window_number')} of {document_summary.get('total_windows', 0)}"
                )
                document_summary['active_attempt_number'] = None
                failed_range_labels.append(window_label)

        document_summary['active_window_number'] = None
        document_summary['active_attempt_number'] = None
        document_summary['status'] = 'completed_with_failures' if document_summary.get('failed_windows', 0) else 'completed'
        document_summary['status_text'] = (
            'Completed with some failed windows'
            if document_summary.get('failed_windows', 0)
            else 'Completed'
        )
        if callable(activity_callback):
            activity_callback({
                'type': 'document_completed',
                'document_id': document_id,
                'document_name': document_name,
                'processed_windows': document_summary.get('processed_windows', 0),
                'failed_windows': document_summary.get('failed_windows', 0),
                'processed_chunks': document_summary.get('processed_chunks', 0),
                'failed_chunks': document_summary.get('failed_chunks', 0),
                'progress': _build_progress_snapshot(coverage),
            })
        debug_print(
            '[ExhaustiveReview] Completed document | '
            f'document_index={document_index} | '
            f'document_id={document_id} | '
            f'document_name={document_name} | '
            f"processed_windows={document_summary.get('processed_windows', 0)} | "
            f"failed_windows={document_summary.get('failed_windows', 0)} | "
            f"processed_chunks={document_summary.get('processed_chunks', 0)} | "
            f"failed_chunks={document_summary.get('failed_chunks', 0)}"
        )

    if not reduction_items:
        debug_print(
            '[ExhaustiveReview] Review failed | '
            f'user_id={user_id} | error=No document windows were reviewed successfully'
        )
        raise RuntimeError('No document windows were reviewed successfully.')

    current_items = reduction_items
    reduction_round = 1
    while len(current_items) > 1 and reduction_round <= max_reduction_rounds:
        next_items = []
        batches = _build_reduction_batches(current_items, reduction_batch_size)
        for batch_index, batch_items in enumerate(batches, start=1):
            debug_print(
                '[ExhaustiveReview] Starting reduction batch | '
                f'round={reduction_round} | '
                f'batch={batch_index}/{len(batches)} | '
                f'items={len(batch_items)}'
            )
            reduction_prompt = _build_reduction_prompt(
                normalized_review_prompt,
                batch_items,
                stage_label=f'reduction-{reduction_round}.{batch_index}',
                failed_range_labels=failed_range_labels,
            )
            reduced_text = str(invoke_prompt(
                reduction_prompt,
                stage='reduction',
                metadata={
                    'reduction_round': reduction_round,
                    'batch_index': batch_index,
                    'item_count': len(batch_items),
                },
            ) or '').strip()
            if not reduced_text:
                debug_print(
                    '[ExhaustiveReview] Reduction failed | '
                    f'round={reduction_round} | '
                    f'batch={batch_index} | error=empty reduction response'
                )
                raise RuntimeError(
                    f'Exhaustive review reduction returned an empty response at round {reduction_round}, batch {batch_index}.'
                )

            source_labels = [item.get('label') for item in batch_items]
            debug_print(
                '[ExhaustiveReview] Completed reduction batch | '
                f'round={reduction_round} | '
                f'batch={batch_index}/{len(batches)} | '
                f'sources={len(source_labels)}'
            )
            next_items.append({
                'label': f'Reduction {reduction_round}.{batch_index}',
                'text': reduced_text,
                'source_labels': source_labels,
            })
        current_items = next_items
        reduction_round += 1

    final_reply = current_items[0].get('text', '').strip()
    coverage_summary = _format_coverage_summary(coverage)
    if include_coverage_summary and coverage_summary:
        final_reply = f"{final_reply}\n\n{coverage_summary}".strip()

    log_event(
        '[ExhaustiveReview] Completed exhaustive document review',
        extra={
            'user_id': user_id,
            'document_count': coverage.get('document_count', 0),
            'total_windows': coverage.get('total_windows', 0),
            'processed_windows': coverage.get('processed_windows', 0),
            'failed_windows': coverage.get('failed_windows', 0),
            'retries': coverage.get('retries', 0),
        },
        level=logging.INFO,
    )
    debug_print(
        '[ExhaustiveReview] Completed review | '
        f"documents={coverage.get('document_count', 0)} | "
        f"windows={coverage.get('total_windows', 0)} | "
        f"processed={coverage.get('processed_windows', 0)} | "
        f"failed={coverage.get('failed_windows', 0)} | "
        f"retries={coverage.get('retries', 0)}"
    )

    return {
        'reply': final_reply,
        'analysis_reply': current_items[0].get('text', '').strip(),
        'coverage': coverage,
        'documents': coverage.get('documents', []),
        'document_ids': targets.get('document_ids', []),
        'doc_scope': targets.get('doc_scope'),
        'window_unit': targets.get('window_unit'),
        'window_size': targets.get('window_size'),
        'window_percent': targets.get('window_percent'),
        'max_retries_per_window': targets.get('max_retries_per_window'),
    }