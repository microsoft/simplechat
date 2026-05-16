# functions_document_comparison.py
"""Shared deterministic document comparison services."""

import logging

from functions_appinsights import log_event
from functions_debug import debug_print
from functions_document_actions import DOCUMENT_ACTION_TYPE_COMPARISON
from functions_document_analysis import (
    build_document_analysis_progress_snapshot,
    run_document_analysis,
)


def _normalize_progress_percent(value, default_value=0):
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return max(0, min(100, int(default_value or 0)))


def _scale_progress_percent(value, start_percent, end_percent):
    normalized_value = _normalize_progress_percent(value)
    normalized_start = _normalize_progress_percent(start_percent)
    normalized_end = _normalize_progress_percent(end_percent)

    if normalized_end <= normalized_start:
        return normalized_start

    return normalized_start + int(round((normalized_value / 100) * (normalized_end - normalized_start)))


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


def _calculate_document_state_percent(document_state):
    document_state = document_state if isinstance(document_state, dict) else {}
    completed_windows = document_state.get('processed_windows', 0) + document_state.get('failed_windows', 0)
    completed_chunks = document_state.get('processed_chunks', 0) + document_state.get('failed_chunks', 0)
    total_chunks = document_state.get('total_chunks', 0)
    total_windows = document_state.get('total_windows', 0)
    overall_total = total_chunks or total_windows
    overall_completed = completed_chunks if total_chunks else completed_windows

    return _calculate_progress_percent(
        overall_completed,
        overall_total,
        fallback_complete=str(document_state.get('status') or '').strip().lower() in {'completed', 'completed_with_failures'},
    )


def _set_comparison_progress_meta(
    coverage,
    *,
    phase,
    phase_label,
    phase_detail=None,
    status='running',
    percent_override=None,
    phase_step=None,
    phase_total_steps=None,
):
    if not isinstance(coverage, dict):
        return {}

    progress_meta = {
        'phase': str(phase or '').strip().lower() or 'running',
        'phase_label': str(phase_label or '').strip() or 'Running document comparison',
        'phase_detail': str(phase_detail or '').strip() or None,
        'status': str(status or '').strip().lower() or 'running',
        'percent_override': None if percent_override is None else _normalize_progress_percent(percent_override),
        'phase_step': None if phase_step is None else max(0, int(phase_step)),
        'phase_total_steps': None if phase_total_steps is None else max(0, int(phase_total_steps)),
    }
    coverage['progress_meta'] = progress_meta
    return progress_meta


def _create_document_state(document_id, role_label):
    return {
        'document_id': document_id,
        'document_name': document_id,
        'role_label': role_label,
        'scope': None,
        'scope_id': None,
        'total_windows': 0,
        'processed_windows': 0,
        'failed_windows': 0,
        'total_chunks': 0,
        'processed_chunks': 0,
        'failed_chunks': 0,
        'total_pages': 0,
        'status': 'pending',
        'status_text': 'Queued',
        'active_window_number': None,
        'active_attempt_number': None,
        'failed_ranges': [],
        'ranges': [],
        'retries': 0,
    }


def _refresh_comparison_coverage(coverage, document_order, document_states):
    ordered_documents = [document_states[document_id] for document_id in document_order if document_id in document_states]
    coverage['documents'] = ordered_documents
    coverage['document_count'] = len(ordered_documents)
    coverage['total_windows'] = sum(document.get('total_windows', 0) for document in ordered_documents)
    coverage['processed_windows'] = sum(document.get('processed_windows', 0) for document in ordered_documents)
    coverage['failed_windows'] = sum(document.get('failed_windows', 0) for document in ordered_documents)
    coverage['total_chunks'] = sum(document.get('total_chunks', 0) for document in ordered_documents)
    coverage['processed_chunks'] = sum(document.get('processed_chunks', 0) for document in ordered_documents)
    coverage['failed_chunks'] = sum(document.get('failed_chunks', 0) for document in ordered_documents)
    coverage['retries'] = sum(document.get('retries', 0) for document in ordered_documents)
    return coverage


def _apply_summary_progress_event(document_state, event):
    event = event if isinstance(event, dict) else {}
    progress = event.get('progress') if isinstance(event.get('progress'), dict) else {}
    progress_documents = progress.get('documents') if isinstance(progress.get('documents'), list) else []
    progress_document = progress_documents[0] if progress_documents else {}
    progress_overall = progress.get('overall') if isinstance(progress.get('overall'), dict) else {}

    document_state['document_name'] = str(event.get('document_name') or document_state.get('document_name') or document_state.get('document_id')).strip() or document_state.get('document_id')
    document_state['scope'] = progress_document.get('scope', document_state.get('scope'))
    document_state['scope_id'] = progress_document.get('scope_id', document_state.get('scope_id'))
    document_state['total_windows'] = progress_document.get('total_windows', document_state.get('total_windows', 0))
    document_state['processed_windows'] = progress_document.get('processed_windows', document_state.get('processed_windows', 0))
    document_state['failed_windows'] = progress_document.get('failed_windows', document_state.get('failed_windows', 0))
    document_state['total_chunks'] = progress_document.get('total_chunks', document_state.get('total_chunks', 0))
    document_state['processed_chunks'] = progress_document.get('processed_chunks', document_state.get('processed_chunks', 0))
    document_state['failed_chunks'] = progress_document.get('failed_chunks', document_state.get('failed_chunks', 0))
    document_state['total_pages'] = progress_document.get('total_pages', document_state.get('total_pages', 0))
    document_state['active_window_number'] = progress_document.get('active_window_number', document_state.get('active_window_number'))
    document_state['active_attempt_number'] = progress_document.get('active_attempt_number', document_state.get('active_attempt_number'))
    document_state['status'] = progress_document.get('status', document_state.get('status', 'pending'))
    document_state['status_text'] = progress_document.get('status_text', document_state.get('status_text', 'Queued'))
    document_state['retries'] = progress_overall.get('retries', document_state.get('retries', 0))

    if event.get('type') == 'document_completed':
        document_state['active_window_number'] = None
        document_state['active_attempt_number'] = None


def _build_document_summary_prompt(comparison_prompt, role_label, document_name):
    return (
        'You are preparing a deterministic document summary that will be used for a later comparison. '
        'Focus on facts, obligations, definitions, decisions, changes, dates, and caveats that matter to the '
        'comparison request below. Preserve uncertainty instead of guessing.\n\n'
        f'Comparison request:\n{comparison_prompt}\n\n'
        f'Document role: {role_label}\n'
        f'Document name: {document_name}\n\n'
        'Write a comparison-ready summary of this document. Include the points that would matter when this '
        'document is compared against one or more other documents for differences, impact, alignment, conflicts, '
        'or version changes.'
    )


def _build_pairwise_comparison_prompt(comparison_prompt, left_name, right_name, left_summary, right_summary):
    return (
        'You are comparing two documents that were summarized from analysis. '
        'Treat the left document as the primary baseline and compare the right document against it.\n\n'
        f'Comparison request:\n{comparison_prompt}\n\n'
        f'Left document: {left_name}\n'
        f'Right document: {right_name}\n\n'
        'Explain what matches, what differs, what the right document changes or impacts relative to the left, '
        'and any conflicts, missing items, risks, or open questions that matter to the user request.\n\n'
        f'<LeftDocumentSummary>\n{left_summary}\n</LeftDocumentSummary>\n\n'
        f'<RightDocumentSummary>\n{right_summary}\n</RightDocumentSummary>'
    )


def _build_comparison_reduction_prompt(comparison_prompt, left_name, comparison_items):
    combined_sections = []
    for comparison_item in comparison_items:
        combined_sections.append(
            f"[{comparison_item.get('right_document_name')}]\n{comparison_item.get('text', '')}"
        )

    return (
        'You are consolidating pairwise document comparisons into one final answer. '
        'Keep the left document as the anchor and organize the response clearly by right-side document.\n\n'
        f'Comparison request:\n{comparison_prompt}\n\n'
        f'Left document: {left_name}\n\n'
        'Preserve material differences, impact analysis, conflicts, and unresolved questions.\n\n'
        f"<PairwiseComparisons>\n{'\n\n'.join(combined_sections)}\n</PairwiseComparisons>"
    )


def _format_comparison_coverage_summary(coverage, left_document_name, right_document_names):
    lines = [
        '## Comparison Coverage',
        f'- Left document: {left_document_name}',
        f"- Right documents compared: {len(right_document_names)}",
        f"- Total windows: {coverage.get('total_windows', 0)}",
        f"- Processed windows: {coverage.get('processed_windows', 0)}",
        f"- Failed windows: {coverage.get('failed_windows', 0)}",
        f"- Total chunks: {coverage.get('total_chunks', 0)}",
        f"- Processed chunks: {coverage.get('processed_chunks', 0)}",
        f"- Failed chunks: {coverage.get('failed_chunks', 0)}",
        f"- Retries used: {coverage.get('retries', 0)}",
        '',
        '### Documents Summarized',
    ]

    for document in coverage.get('documents', []):
        lines.append(
            '- '
            f"{document.get('document_name')}: "
            f"{document.get('processed_windows', 0)}/{document.get('total_windows', 0)} windows processed, "
            f"{document.get('processed_chunks', 0)}/{document.get('total_chunks', 0)} chunks completed"
        )

    return '\n'.join(lines)


def run_document_comparison(
    user_id,
    comparison_prompt,
    action_config,
    invoke_prompt,
    activity_callback=None,
    conversation_id=None,
):
    normalized_prompt = str(comparison_prompt or '').strip()
    if not normalized_prompt:
        raise ValueError('A comparison prompt is required for document comparison.')
    if not callable(invoke_prompt):
        raise ValueError('A callable invoke_prompt handler is required for document comparison.')
    action_config = action_config if isinstance(action_config, dict) else {}
    if action_config.get('type') != DOCUMENT_ACTION_TYPE_COMPARISON:
        raise ValueError('Document comparison requires a comparison action configuration.')

    left_document_id = str(action_config.get('left_document_id') or '').strip()
    right_document_ids = list(action_config.get('right_document_ids') or [])
    if not left_document_id or not right_document_ids:
        raise ValueError('Document comparison requires one Source document and at least one Target document.')

    debug_print(
        '[DocumentComparison] Starting comparison | '
        f'user_id={user_id} | '
        f'left_document_id={left_document_id} | '
        f'right_count={len(right_document_ids)} | '
        f"doc_scope={action_config.get('doc_scope')} | "
        f"window_unit={action_config.get('window_unit')} | "
        f"window_size={action_config.get('window_size')} | "
        f"window_percent={action_config.get('window_percent')} | "
        f'prompt_chars={len(normalized_prompt)}'
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
        'window_unit': action_config.get('window_unit', 'pages'),
        'documents': [],
    }
    _set_comparison_progress_meta(
        coverage,
        phase='queued',
        phase_label='Queued for comparison',
        phase_detail='Preparing selected documents',
        status='running',
        percent_override=1,
    )
    document_order = [left_document_id, *right_document_ids]
    document_states = {
        left_document_id: _create_document_state(left_document_id, 'left'),
    }
    for document_id in right_document_ids:
        document_states[document_id] = _create_document_state(document_id, 'right')
    _refresh_comparison_coverage(coverage, document_order, document_states)

    document_summaries = {}
    for document_index, document_id in enumerate(document_order, start=1):
        document_state = document_states[document_id]
        role_label = document_state.get('role_label', 'right')
        debug_print(
            '[DocumentComparison] Starting summary pass | '
            f'document_index={document_index} | '
            f'document_id={document_id} | '
            f'role={role_label}'
        )
        document_state['status'] = 'running'
        document_state['status_text'] = f"Preparing {role_label}-side document {document_index} of {len(document_order)}"
        _refresh_comparison_coverage(coverage, document_order, document_states)

        def summary_activity_callback(event, current_document_id=document_id, current_document_index=document_index):
            current_document_state = document_states[current_document_id]
            _apply_summary_progress_event(current_document_state, event)
            _refresh_comparison_coverage(coverage, document_order, document_states)
            current_document_percent = _calculate_document_state_percent(current_document_state)
            summary_progress_percent = 0
            if document_order:
                summary_progress_percent = ((current_document_index - 1) + (current_document_percent / 100)) / len(document_order) * 100
            _set_comparison_progress_meta(
                coverage,
                phase='summarizing',
                phase_label='Summarizing documents for comparison',
                phase_detail=(
                    f'Document {current_document_index} of {len(document_order)}: '
                    f'{current_document_state.get("document_name") or current_document_id}'
                ),
                status='running',
                percent_override=max(1, _scale_progress_percent(summary_progress_percent, 5, 70)),
                phase_step=current_document_index,
                phase_total_steps=len(document_order),
            )
            if callable(activity_callback):
                forwarded_event = dict(event or {})
                forwarded_event['comparison_role'] = current_document_state.get('role_label')
                forwarded_event['progress'] = build_document_analysis_progress_snapshot(coverage)
                activity_callback(forwarded_event)

        summary_result = run_document_analysis(
            user_id=user_id,
            analysis_prompt=_build_document_summary_prompt(
                normalized_prompt,
                role_label,
                document_state.get('document_name'),
            ),
            document_ids=[document_id],
            invoke_prompt=invoke_prompt,
            doc_scope=action_config.get('doc_scope'),
            active_group_ids=action_config.get('active_group_ids'),
            active_public_workspace_id=action_config.get('active_public_workspace_id'),
            conversation_id=conversation_id,
            window_unit=action_config.get('window_unit'),
            window_size=action_config.get('window_size'),
            window_percent=action_config.get('window_percent'),
            max_retries_per_window=action_config.get('max_retries_per_window'),
            activity_callback=summary_activity_callback,
            max_documents=1,
            include_coverage_summary=False,
        )
        document_summaries[document_id] = summary_result
        document_state['document_name'] = (
            (summary_result.get('documents') or [{}])[0].get('document_name')
            or document_state.get('document_name')
        )
        document_state['status'] = 'completed_with_failures' if document_state.get('failed_windows', 0) else 'completed'
        document_state['status_text'] = 'Summary ready'
        document_state['active_window_number'] = None
        document_state['active_attempt_number'] = None
        _refresh_comparison_coverage(coverage, document_order, document_states)
        debug_print(
            '[DocumentComparison] Completed summary pass | '
            f'document_index={document_index} | '
            f'document_id={document_id} | '
            f"document_name={document_state.get('document_name')} | "
            f"processed_windows={document_state.get('processed_windows', 0)} | "
            f"failed_windows={document_state.get('failed_windows', 0)}"
        )

    left_document_name = document_states[left_document_id].get('document_name') or left_document_id
    comparison_items = []
    for comparison_index, right_document_id in enumerate(right_document_ids, start=1):
        right_document_name = document_states[right_document_id].get('document_name') or right_document_id
        comparison_progress_percent = ((comparison_index - 1) / len(right_document_ids)) * 100 if right_document_ids else 0
        _set_comparison_progress_meta(
            coverage,
            phase='comparing',
            phase_label='Comparing summarized documents',
            phase_detail=f'Comparison {comparison_index} of {len(right_document_ids)}: {left_document_name} vs {right_document_name}',
            status='running',
            percent_override=_scale_progress_percent(comparison_progress_percent, 70, 95),
            phase_step=comparison_index,
            phase_total_steps=len(right_document_ids),
        )
        debug_print(
            '[DocumentComparison] Starting pairwise comparison | '
            f'comparison_index={comparison_index}/{len(right_document_ids)} | '
            f'left_document_id={left_document_id} | '
            f'right_document_id={right_document_id} | '
            f'right_document_name={right_document_name}'
        )
        if callable(activity_callback):
            activity_callback({
                'type': 'comparison_started',
                'left_document_id': left_document_id,
                'left_document_name': left_document_name,
                'right_document_id': right_document_id,
                'right_document_name': right_document_name,
                'comparison_index': comparison_index,
                'comparison_count': len(right_document_ids),
                'progress': build_document_analysis_progress_snapshot(coverage),
            })

        pairwise_text = str(invoke_prompt(
            _build_pairwise_comparison_prompt(
                normalized_prompt,
                left_document_name,
                right_document_name,
                document_summaries[left_document_id].get('analysis_reply', ''),
                document_summaries[right_document_id].get('analysis_reply', ''),
            ),
            stage='comparison',
            metadata={
                'comparison_index': comparison_index,
                'comparison_count': len(right_document_ids),
                'left_document_id': left_document_id,
                'right_document_id': right_document_id,
            },
        ) or '').strip()
        if not pairwise_text:
            debug_print(
                '[DocumentComparison] Pairwise comparison failed | '
                f'comparison_index={comparison_index}/{len(right_document_ids)} | '
                f'left_document_id={left_document_id} | '
                f'right_document_id={right_document_id} | '
                'error=empty comparison response'
            )
            raise RuntimeError(
                f'Document comparison returned an empty response for {left_document_name} and {right_document_name}.'
            )

        comparison_items.append({
            'right_document_id': right_document_id,
            'right_document_name': right_document_name,
            'text': pairwise_text,
        })
        comparison_progress_percent = (comparison_index / len(right_document_ids)) * 100 if right_document_ids else 100
        _set_comparison_progress_meta(
            coverage,
            phase='comparing',
            phase_label='Comparing summarized documents',
            phase_detail=f'Completed comparison {comparison_index} of {len(right_document_ids)}: {left_document_name} vs {right_document_name}',
            status='running',
            percent_override=_scale_progress_percent(comparison_progress_percent, 70, 95),
            phase_step=comparison_index,
            phase_total_steps=len(right_document_ids),
        )
        debug_print(
            '[DocumentComparison] Completed pairwise comparison | '
            f'comparison_index={comparison_index}/{len(right_document_ids)} | '
            f'left_document_id={left_document_id} | '
            f'right_document_id={right_document_id}'
        )
        if callable(activity_callback):
            activity_callback({
                'type': 'comparison_completed',
                'left_document_id': left_document_id,
                'left_document_name': left_document_name,
                'right_document_id': right_document_id,
                'right_document_name': right_document_name,
                'comparison_index': comparison_index,
                'comparison_count': len(right_document_ids),
                'progress': build_document_analysis_progress_snapshot(coverage),
            })

    if len(comparison_items) == 1:
        final_reply = comparison_items[0].get('text', '').strip()
    else:
        _set_comparison_progress_meta(
            coverage,
            phase='reducing',
            phase_label='Combining comparison findings',
            phase_detail=f'Preparing final comparison from {len(comparison_items)} pairwise analyses',
            status='running',
            percent_override=96,
            phase_step=1,
            phase_total_steps=1,
        )
        debug_print(
            '[DocumentComparison] Starting comparison reduction | '
            f'left_document_id={left_document_id} | '
            f'comparison_count={len(comparison_items)}'
        )
        if callable(activity_callback):
            activity_callback({
                'type': 'comparison_reduction_started',
                'left_document_id': left_document_id,
                'left_document_name': left_document_name,
                'comparison_count': len(comparison_items),
                'progress': build_document_analysis_progress_snapshot(coverage),
            })
        final_reply = str(invoke_prompt(
            _build_comparison_reduction_prompt(
                normalized_prompt,
                left_document_name,
                comparison_items,
            ),
            stage='comparison_reduction',
            metadata={
                'comparison_count': len(comparison_items),
                'left_document_id': left_document_id,
            },
        ) or '').strip()
        if not final_reply:
            debug_print(
                '[DocumentComparison] Comparison reduction failed | '
                f'left_document_id={left_document_id} | error=empty reduction response'
            )
            raise RuntimeError('Document comparison reduction returned an empty response.')
        debug_print(
            '[DocumentComparison] Completed comparison reduction | '
            f'left_document_id={left_document_id} | '
            f'comparison_count={len(comparison_items)}'
        )

    _set_comparison_progress_meta(
        coverage,
        phase='completed',
        phase_label='Comparison complete',
        phase_detail='Preparing final response',
        status='completed',
        percent_override=100,
    )

    analysis_reply = final_reply.strip()
    coverage_summary = _format_comparison_coverage_summary(
        coverage,
        left_document_name,
        [document_states[document_id].get('document_name') or document_id for document_id in right_document_ids],
    )
    if coverage_summary:
        final_reply = f"{final_reply}\n\n{coverage_summary}".strip()

    if callable(activity_callback):
        activity_callback({
            'type': 'comparison_reduction_completed',
            'left_document_id': left_document_id,
            'left_document_name': left_document_name,
            'comparison_count': len(comparison_items),
            'progress': build_document_analysis_progress_snapshot(coverage),
        })

    log_event(
        '[DocumentComparison] Completed deterministic document comparison',
        extra={
            'user_id': user_id,
            'left_document_id': left_document_id,
            'right_document_count': len(right_document_ids),
            'document_count': coverage.get('document_count', 0),
            'total_windows': coverage.get('total_windows', 0),
            'processed_windows': coverage.get('processed_windows', 0),
            'failed_windows': coverage.get('failed_windows', 0),
            'retries': coverage.get('retries', 0),
        },
        level=logging.INFO,
    )
    debug_print(
        '[DocumentComparison] Completed comparison | '
        f'left={left_document_id} | '
        f'right_count={len(right_document_ids)} | '
        f"documents={coverage.get('document_count', 0)} | "
        f"windows={coverage.get('total_windows', 0)} | "
        f"processed={coverage.get('processed_windows', 0)} | "
        f"failed={coverage.get('failed_windows', 0)}"
    )

    return {
        'reply': final_reply,
        'analysis_reply': analysis_reply,
        'coverage': coverage,
        'documents': coverage.get('documents', []),
        'left_document': {
            'document_id': left_document_id,
            'document_name': left_document_name,
        },
        'right_documents': [
            {
                'document_id': document_id,
                'document_name': document_states[document_id].get('document_name') or document_id,
            }
            for document_id in right_document_ids
        ],
        'comparison_items': comparison_items,
    }