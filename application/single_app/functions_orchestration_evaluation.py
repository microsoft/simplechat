# functions_orchestration_evaluation.py
"""Build bounded, privacy-safe evaluation events for chat orchestration."""

import hashlib
from collections.abc import Mapping
from datetime import datetime, timezone


ORCHESTRATION_EVALUATION_VERSION = 1
MAX_EVALUATION_COUNT = 10000
MAX_EVALUATION_LATENCY_MS = 604800000
MAX_EVALUATION_REASON_CODES = 12
SAFE_CAPABILITY_IDS = frozenset({
    'analyze',
    'compare',
    'deep_research',
    'image',
    'url_access',
    'web_search',
    'workspace_search',
})
SAFE_REASON_CODES = frozenset({
    'business_system_evidence',
    'comparison_targets_required',
    'current_authoritative_sources',
    'current_public_information',
    'document_analysis_requested',
    'multi_document_comparison',
    'multi_source_public_research',
    'specialized_organizational_knowledge',
    'user_supplied_url_requires_review',
    'visual_output_materially_helpful',
    'workspace_evidence_requested',
})
SAFE_NODE_STATUSES = frozenset({
    'blocked',
    'cancelled',
    'failed',
    'partial',
    'pending',
    'running',
    'skipped',
    'succeeded',
})
SAFE_RUN_STATUSES = frozenset({
    'awaiting_user_choice',
    'cancelled',
    'failed',
    'partial',
    'pending',
    'running',
    'succeeded',
})
SAFE_TASK_PROFILES = frozenset({
    'direct_answer',
    'grounded_answer',
    'grounded_image_generation',
    'image_generation',
})


def _field(value, name, default=None):
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _bounded_count(value):
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(normalized, MAX_EVALUATION_COUNT))


def _safe_enum(value, allowed_values, fallback='other'):
    normalized = str(value or '').strip().lower()
    return normalized if normalized in allowed_values else fallback


def _parse_timestamp(value):
    normalized = str(value or '').strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latency_ms(started_at, completed_at):
    started = _parse_timestamp(started_at)
    completed = _parse_timestamp(completed_at)
    if not started or not completed or completed < started:
        return 0
    elapsed_ms = round((completed - started).total_seconds() * 1000)
    return min(elapsed_ms, MAX_EVALUATION_LATENCY_MS)


def _correlation_id(value):
    normalized = str(value or '').strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]


def _safe_reason_codes(values):
    normalized = []
    for value in values or []:
        reason_code = _safe_enum(value, SAFE_REASON_CODES, fallback='')
        if reason_code and reason_code not in normalized:
            normalized.append(reason_code)
        if len(normalized) >= MAX_EVALUATION_REASON_CODES:
            break
    return normalized


def _proposal_option(proposal, option_id):
    return next(
        (
            option
            for option in (_field(proposal, 'options', []) or [])
            if isinstance(option, Mapping)
            and str(option.get('id') or '').strip() == str(option_id or '').strip()
        ),
        {},
    )


def _capability_class(option):
    if not isinstance(option, Mapping):
        return 'unknown'
    if option.get('kind') == 'agent' or option.get('agent_ref'):
        return 'governed_agent'
    capability_ids = [
        str(capability_id or '').strip()
        for capability_id in (option.get('capability_ids') or [])
        if str(capability_id or '').strip() in SAFE_CAPABILITY_IDS
    ]
    if capability_ids:
        return capability_ids[0]
    if not option.get('capability_ids') and not option.get('agent_ref'):
        return 'continue_without_capabilities'
    return 'unknown'


def _base_event(event_type):
    return {
        'evaluation_version': ORCHESTRATION_EVALUATION_VERSION,
        'event_type': event_type,
    }


def build_orchestration_run_evaluation_event(run):
    """Summarize one terminal run without copying node IDs or evidence content."""
    nodes = list(_field(run, 'nodes', []) or [])
    source_nodes = [node for node in nodes if _field(node, 'type') != 'finalize']
    finalizer = next(
        (node for node in nodes if _field(node, 'type') == 'finalize'),
        None,
    )
    ledger = _field(run, 'evidence_ledger', {})
    ledger = ledger if isinstance(ledger, Mapping) else {}
    source_status_counts = {
        status: _bounded_count(sum(
            _safe_enum(_field(node, 'status'), SAFE_NODE_STATUSES) == status
            for node in source_nodes
        ))
        for status in ('succeeded', 'partial', 'failed', 'skipped', 'blocked', 'cancelled')
    }
    successful_source_count = (
        source_status_counts['succeeded'] + source_status_counts['partial']
    )
    citation_count = _bounded_count(len(ledger.get('citations') or []))
    citation_yield = round(citation_count / successful_source_count, 3) if successful_source_count else 0.0
    return {
        **_base_event('orchestration_run_completed'),
        'run_correlation_id': _correlation_id(_field(run, 'run_id')),
        'run_status': _safe_enum(_field(run, 'status'), SAFE_RUN_STATUSES),
        'orchestration_mode': _safe_enum(_field(run, 'mode'), {'direct', 'coordinated'}),
        'task_profile': _safe_enum(_field(run, 'task_profile'), SAFE_TASK_PROFILES),
        'source_count': _bounded_count(len(source_nodes)),
        'required_source_count': _bounded_count(sum(
            bool(_field(node, 'required')) for node in source_nodes
        )),
        'source_succeeded_count': source_status_counts['succeeded'],
        'source_partial_count': source_status_counts['partial'],
        'source_failed_count': source_status_counts['failed'],
        'source_skipped_count': source_status_counts['skipped'],
        'source_blocked_count': source_status_counts['blocked'],
        'source_cancelled_count': source_status_counts['cancelled'],
        'finalizer_status': _safe_enum(
            _field(finalizer, 'status'),
            SAFE_NODE_STATUSES,
            fallback='missing',
        ),
        'citation_count': citation_count,
        'citation_yield': citation_yield,
        'unsupported_fact_count': _bounded_count(len(ledger.get('unsupported_facts') or [])),
        'missing_evidence_count': _bounded_count(len(ledger.get('missing_or_failed') or [])),
        'replan_count': _bounded_count(_field(run, 'replan_count', 0)),
        'run_latency_ms': _latency_ms(
            _field(run, 'started_at'),
            _field(run, 'completed_at'),
        ),
    }


def build_recommendation_created_evaluation_event(proposal):
    """Summarize a server-authored recommendation without option identifiers."""
    recommended_option = _proposal_option(
        proposal,
        _field(proposal, 'recommended_option_id'),
    )
    return {
        **_base_event('orchestration_recommendation_created'),
        'run_correlation_id': _correlation_id(_field(proposal, 'run_id')),
        'recommended_capability': _capability_class(recommended_option),
        'reason_codes': _safe_reason_codes(_field(proposal, 'reason_codes', [])),
        'option_count': _bounded_count(len(_field(proposal, 'options', []) or [])),
        'requirement_count': _bounded_count(len(_field(proposal, 'requirement_ids', []) or [])),
        'external_data': bool(recommended_option.get('external_data')),
        'sensitive_data_notice_required': bool(
            _field(proposal, 'sensitive_data_notice_required', False)
        ),
    }


def build_recommendation_decision_evaluation_event(proposal, *, idempotent=False):
    """Summarize an approved or declined recommendation decision."""
    decision = _field(proposal, 'decision', {})
    decision = decision if isinstance(decision, Mapping) else {}
    selected_option = _proposal_option(proposal, decision.get('option_id'))
    return {
        **_base_event('orchestration_recommendation_decided'),
        'run_correlation_id': _correlation_id(_field(proposal, 'run_id')),
        'decision_status': _safe_enum(
            decision.get('status'),
            {'approved', 'declined'},
        ),
        'selected_capability': _capability_class(selected_option),
        'reason_codes': _safe_reason_codes(_field(proposal, 'reason_codes', [])),
        'decision_latency_ms': _latency_ms(
            _field(proposal, 'created_at'),
            decision.get('decided_at'),
        ),
        'idempotent': bool(idempotent),
    }


def build_recommendation_outcome_evaluation_event(run, resume_context):
    """Join a resumed recommendation to aggregate terminal run outcomes."""
    context = resume_context if isinstance(resume_context, Mapping) else {}
    proposal = context.get('original_proposal')
    proposal = proposal if isinstance(proposal, Mapping) else {}
    decision = context.get('decision')
    decision = decision if isinstance(decision, Mapping) else {}
    selected_option = _proposal_option(proposal, decision.get('option_id'))
    run_event = build_orchestration_run_evaluation_event(run)
    return {
        **run_event,
        'event_type': 'orchestration_recommendation_outcome',
        'parent_run_correlation_id': _correlation_id(proposal.get('run_id')),
        'decision_status': _safe_enum(
            decision.get('status'),
            {'approved', 'declined'},
        ),
        'selected_capability': _capability_class(selected_option),
        'reason_codes': _safe_reason_codes(proposal.get('reason_codes') or []),
        'incremental_latency_ms': _latency_ms(
            decision.get('decided_at'),
            _field(run, 'completed_at'),
        ),
    }