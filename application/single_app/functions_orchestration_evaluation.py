# functions_orchestration_evaluation.py
"""Build bounded, privacy-safe evaluation events for chat orchestration."""

import hashlib
from collections.abc import Mapping
from datetime import datetime, timezone

from functions_chat_capability_planner import (
    CAPABILITY_PLANNER_DECISIONS,
    CAPABILITY_PLANNER_FAILURE_CODES,
    CAPABILITY_PLANNER_REASON_CODES,
)


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
SAFE_PLANNER_CAPABILITY_CLASSES = SAFE_CAPABILITY_IDS | {'governed_agent'}
SAFE_PLANNER_PROVIDER_CLASSES = frozenset({
    'anthropic',
    'azure_openai',
    'openai_style',
})
SAFE_PLANNER_MODEL_CLASSES = frozenset({
    'claude',
    'gpt',
    'openai_reasoning',
})
SAFE_PLANNER_STATUSES = frozenset({
    'discarded',
    'rejected',
    'timed_out',
    'valid',
})
SAFE_PLANNER_AGREEMENT_CATEGORIES = frozenset({
    'decision_agreement_capability_difference',
    'decision_agreement_direct',
    'decision_and_capability_agreement',
    'decision_disagreement',
    'not_compared',
})
SAFE_CAPABILITY_COMBINATIONS = frozenset({
    'analyze',
    'compare',
    'deep_research+web_search',
    'governed_agent',
    'image',
    'url_access',
    'web_search',
    'web_search+workspace_search',
    'workspace_search',
})
SAFE_PLANNER_ACTIVATION_STATUSES = frozenset({'materialized', 'suppressed'})
SAFE_RECOMMENDATION_SOURCES = frozenset({'deterministic', 'direct', 'planner'})
SAFE_PLANNER_SUPPRESSION_REASONS = frozenset({
    'deterministic_conflict',
    'planner_not_materialized',
})
SAFE_REVALIDATION_PHASES = frozenset({'decision', 'execution', 'resume'})
SAFE_REVALIDATION_STATUSES = frozenset({
    'expired',
    'invalidated',
    'rejected',
    'succeeded',
})
SAFE_REVALIDATION_REASON_CLASSES = frozenset({
    'agent',
    'authorization',
    'availability',
    'bundle',
    'conflict',
    'expired',
    'input',
    'lease',
    'policy',
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
        reason_code = _safe_enum(
            value,
            SAFE_REASON_CODES | CAPABILITY_PLANNER_REASON_CODES,
            fallback='',
        )
        if reason_code and reason_code not in normalized:
            normalized.append(reason_code)
        if len(normalized) >= MAX_EVALUATION_REASON_CODES:
            break
    return normalized


def _safe_planner_reason_codes(values):
    normalized = []
    for value in values or []:
        reason_code = _safe_enum(
            value,
            CAPABILITY_PLANNER_REASON_CODES,
            fallback='',
        )
        if reason_code and reason_code not in normalized:
            normalized.append(reason_code)
        if len(normalized) >= MAX_EVALUATION_REASON_CODES:
            break
    return normalized


def _safe_planner_capability_classes(values):
    normalized = []
    for value in values or []:
        capability_class = _safe_enum(
            value,
            SAFE_PLANNER_CAPABILITY_CLASSES,
            fallback='',
        )
        if capability_class and capability_class not in normalized:
            normalized.append(capability_class)
        if len(normalized) >= MAX_EVALUATION_REASON_CODES:
            break
    return normalized


def _planner_model_class(model_name):
    normalized = str(model_name or '').strip().lower()
    if 'claude' in normalized:
        return 'claude'
    if normalized.startswith(('o1', 'o3', 'o4')):
        return 'openai_reasoning'
    if normalized.startswith('gpt'):
        return 'gpt'
    return 'other'


def _planner_event_fields(run_id, metadata, *, provider_class, model_name):
    summary = metadata if isinstance(metadata, Mapping) else {}
    return {
        'run_correlation_id': _correlation_id(run_id),
        'planner_mode': _safe_enum(summary.get('mode'), {'shadow', 'assist'}),
        'provider_class': _safe_enum(
            provider_class,
            SAFE_PLANNER_PROVIDER_CLASSES,
        ),
        'model_class': _safe_enum(
            _planner_model_class(model_name),
            SAFE_PLANNER_MODEL_CLASSES,
        ),
        'status': _safe_enum(summary.get('status'), SAFE_PLANNER_STATUSES),
        'decision': _safe_enum(
            summary.get('decision'),
            CAPABILITY_PLANNER_DECISIONS,
        ),
        'candidate_count': _bounded_count(summary.get('candidate_count')),
        'capability_count': _bounded_count(
            len(summary.get('recommended_capability_classes') or [])
        ),
        'capability_classes': _safe_planner_capability_classes(
            summary.get('recommended_capability_classes')
        ),
        'reason_codes': _safe_planner_reason_codes(summary.get('reason_codes')),
        'latency_ms': _bounded_count(summary.get('latency_ms')),
        'fallback_used': bool(summary.get('fallback_used')),
    }


def _safe_capability_combination(capability_classes):
    safe_classes = sorted(set(_safe_planner_capability_classes(capability_classes)))
    combination = '+'.join(safe_classes)
    if combination in SAFE_CAPABILITY_COMBINATIONS:
        return combination
    if len(safe_classes) > 1:
        return 'multiple_safe_capabilities'
    return safe_classes[0] if safe_classes else 'unknown'


def _revalidation_reason_class(error_code):
    normalized = str(error_code or '').strip().lower()
    if normalized == 'proposal_expired':
        return 'expired'
    if normalized.startswith('agent_'):
        return 'agent'
    if 'unauthorized' in normalized or 'forbidden' in normalized:
        return 'authorization'
    if any(value in normalized for value in ('missing', 'unavailable')):
        return 'availability'
    if any(value in normalized for value in ('bundle', 'plan_', 'decision_mismatch')):
        return 'bundle'
    if 'input' in normalized:
        return 'input'
    if any(value in normalized for value in ('policy', 'blocked', 'discoverable', 'read_only')):
        return 'policy'
    if any(value in normalized for value in ('resume_', 'lease')):
        return 'lease'
    if any(value in normalized for value in ('conflict', 'write_conflict')):
        return 'conflict'
    return 'other'


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


def _capability_classes(option):
    if not isinstance(option, Mapping):
        return []
    if option.get('kind') == 'agent' or option.get('agent_ref'):
        return ['governed_agent']
    return _safe_planner_capability_classes(
        option.get('effective_capability_ids')
        or option.get('capability_ids')
        or []
    )


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
        'capability_count': _bounded_count(len(_capability_classes(recommended_option))),
        'capability_combination': _safe_capability_combination(
            _capability_classes(recommended_option)
        ),
        'recommendation_source': _safe_enum(
            _field(proposal, 'recommendation_source'),
            {'deterministic', 'planner'},
            fallback='deterministic',
        ),
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
        'capability_count': _bounded_count(len(_capability_classes(selected_option))),
        'capability_combination': _safe_capability_combination(
            _capability_classes(selected_option)
        ),
        'recommendation_source': _safe_enum(
            _field(proposal, 'recommendation_source'),
            {'deterministic', 'planner'},
            fallback='deterministic',
        ),
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
        'capability_count': _bounded_count(len(_capability_classes(selected_option))),
        'capability_combination': _safe_capability_combination(
            _capability_classes(selected_option)
        ),
        'recommendation_source': _safe_enum(
            proposal.get('recommendation_source'),
            {'deterministic', 'planner'},
            fallback='deterministic',
        ),
        'reason_codes': _safe_reason_codes(proposal.get('reason_codes') or []),
        'incremental_latency_ms': _latency_ms(
            decision.get('decided_at'),
            _field(run, 'completed_at'),
        ),
    }


def build_planner_completed_evaluation_event(
    run_id,
    metadata,
    *,
    provider_class,
    model_name,
):
    """Summarize one valid planner result without planner payload content."""
    return {
        **_base_event('orchestration_planner_completed'),
        **_planner_event_fields(
            run_id,
            metadata,
            provider_class=provider_class,
            model_name=model_name,
        ),
    }


def build_planner_rejected_evaluation_event(
    run_id,
    metadata,
    *,
    provider_class,
    model_name,
):
    """Summarize one rejected or cancelled planner result."""
    summary = metadata if isinstance(metadata, Mapping) else {}
    return {
        **_base_event('orchestration_planner_rejected'),
        **_planner_event_fields(
            run_id,
            summary,
            provider_class=provider_class,
            model_name=model_name,
        ),
        'failure_code': _safe_enum(
            summary.get('failure_code'),
            CAPABILITY_PLANNER_FAILURE_CODES,
        ),
    }


def build_planner_timed_out_evaluation_event(
    run_id,
    metadata,
    *,
    provider_class,
    model_name,
):
    """Summarize one transport-bounded planner timeout."""
    summary = metadata if isinstance(metadata, Mapping) else {}
    return {
        **_base_event('orchestration_planner_timed_out'),
        **_planner_event_fields(
            run_id,
            summary,
            provider_class=provider_class,
            model_name=model_name,
        ),
        'failure_code': _safe_enum(
            summary.get('failure_code'),
            {'transport_timeout'},
        ),
    }


def build_planner_shadow_compared_evaluation_event(
    run_id,
    metadata,
    comparison,
    *,
    provider_class,
    model_name,
):
    """Compare planner and deterministic decisions using fixed safe classes."""
    compared = comparison if isinstance(comparison, Mapping) else {}
    return {
        **_base_event('orchestration_planner_shadow_compared'),
        **_planner_event_fields(
            run_id,
            metadata,
            provider_class=provider_class,
            model_name=model_name,
        ),
        'planner_decision': _safe_enum(
            compared.get('planner_decision'),
            CAPABILITY_PLANNER_DECISIONS | {'unavailable'},
        ),
        'deterministic_decision': _safe_enum(
            compared.get('deterministic_decision'),
            {'direct', 'propose'},
        ),
        'agreement_category': _safe_enum(
            compared.get('agreement_category'),
            SAFE_PLANNER_AGREEMENT_CATEGORIES,
        ),
    }


def build_planner_activation_evaluation_event(
    run_id,
    metadata,
    *,
    provider_class,
    model_name,
):
    """Summarize governed assist activation without planner or option payloads."""
    summary = metadata if isinstance(metadata, Mapping) else {}
    capability_classes = _safe_planner_capability_classes(
        summary.get('recommended_capability_classes')
    )
    return {
        **_base_event('orchestration_planner_activation'),
        **_planner_event_fields(
            run_id,
            summary,
            provider_class=provider_class,
            model_name=model_name,
        ),
        'activation_status': _safe_enum(
            summary.get('activation_status'),
            SAFE_PLANNER_ACTIVATION_STATUSES,
        ),
        'recommendation_source': _safe_enum(
            summary.get('recommendation_source'),
            SAFE_RECOMMENDATION_SOURCES,
        ),
        'suppression_reason': _safe_enum(
            summary.get('suppression_reason'),
            SAFE_PLANNER_SUPPRESSION_REASONS,
            fallback='none',
        ),
        'capability_combination': _safe_capability_combination(capability_classes),
    }


def build_recommendation_revalidation_evaluation_event(
    correlation_value,
    *,
    phase,
    proposal=None,
    error_code=None,
):
    """Record bounded additive-member revalidation without object identifiers."""
    proposal_value = proposal if isinstance(proposal, Mapping) else {}
    decision = proposal_value.get('decision')
    decision = decision if isinstance(decision, Mapping) else {}
    selected_option = _proposal_option(
        proposal_value,
        decision.get('option_id') or proposal_value.get('recommended_option_id'),
    )
    reason_class = _revalidation_reason_class(error_code)
    if not error_code:
        status = 'succeeded'
    elif reason_class == 'expired':
        status = 'expired'
    elif reason_class in {
        'agent',
        'authorization',
        'availability',
        'bundle',
        'input',
        'policy',
    }:
        status = 'invalidated'
    else:
        status = 'rejected'
    capability_classes = _capability_classes(selected_option)
    return {
        **_base_event('orchestration_recommendation_revalidated'),
        'run_correlation_id': _correlation_id(
            proposal_value.get('run_id') or correlation_value
        ),
        'phase': _safe_enum(phase, SAFE_REVALIDATION_PHASES),
        'status': _safe_enum(status, SAFE_REVALIDATION_STATUSES),
        'reason_class': _safe_enum(
            reason_class,
            SAFE_REVALIDATION_REASON_CLASSES,
            fallback='other',
        ),
        'capability_count': _bounded_count(len(capability_classes)),
        'capability_combination': _safe_capability_combination(capability_classes),
        'recommendation_source': _safe_enum(
            proposal_value.get('recommendation_source'),
            {'deterministic', 'planner'},
            fallback='deterministic',
        ),
    }