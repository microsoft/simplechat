# functions_deliverable_planner.py
"""Deterministic deliverable planning contracts for chat orchestration."""

import re
from collections.abc import Mapping
from datetime import datetime, timezone


DELIVERABLE_PLAN_CONTRACT_VERSION = 1
DELIVERABLE_ADAPTER_REGISTRY_REVISION = 1
DEFAULT_DELIVERABLE_INTENT_REVISION = 1
DEFAULT_MATERIALIZED_DELIVERABLE_PLAN_REVISION = 1
DEFAULT_INLINE_RESPONSE_MAX_CHARS = 12000

DELIVERABLE_RESPONSE_MODES = frozenset({
    'inline_response_only',
    'full_inline_with_supporting_artifacts',
    'summary_with_primary_artifact',
    'summary_with_supporting_artifacts',
    'clarification_required',
})
DELIVERABLE_KINDS = frozenset({'inline_response', 'generated_file', 'workspace_artifact'})
DELIVERABLE_DIRECTIVE_EFFECTS = (
    'prefer',
    'avoid',
    'require',
    'explicit_only',
    'ask_first',
    'forbid',
    'automatic_when_useful',
)
GENERATED_FILE_FORMAT_ALIASES = {
    'csv': 'csv',
    'comma-separated values': 'csv',
    'md': 'md',
    'markdown': 'md',
    'json': 'json',
    'xml': 'xml',
    'pdf': 'pdf',
    'docx': 'docx',
    'word': 'docx',
    'powerpoint': 'pptx',
    'pptx': 'pptx',
}
FORMAT_TOKEN_PATTERN = re.compile(
    r'\b(csv|markdown|md|json|xml|pdf|docx|word|powerpoint|pptx)\b',
    re.IGNORECASE,
)


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value, *, max_chars=4000):
    normalized = re.sub(r'\s+', ' ', str(value or '').strip())
    return normalized[:max_chars].rstrip()


def _normalize_identifier(value, field_name, *, max_chars=160):
    normalized = _normalize_text(value, max_chars=max_chars).lower()
    normalized = re.sub(r'[^a-z0-9_.:-]+', '_', normalized).strip('_')
    if not normalized:
        raise ValueError(f'{field_name} is required')
    return normalized


def _normalize_ids(values):
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]

    normalized = []
    for value in values:
        identifier = str(value or '').strip()
        if identifier and identifier not in normalized:
            normalized.append(identifier)
    return normalized


def _normalize_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def _normalize_mapping(value, field_name):
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f'{field_name} must be a mapping')
    return dict(value)


def _normalize_format(value):
    normalized = _normalize_text(value, max_chars=80).lower()
    return GENERATED_FILE_FORMAT_ALIASES.get(normalized, normalized)


def _detect_format_from_text(value):
    match = FORMAT_TOKEN_PATTERN.search(str(value or ''))
    if not match:
        return ''
    return _normalize_format(match.group(1))


def _build_adapter(adapter_id, *, kind, output_format, role, approval_required=False):
    return {
        'id': adapter_id,
        'kind': kind,
        'format': output_format,
        'role': role,
        'schema_revision': 1,
        'registry_revision': DELIVERABLE_ADAPTER_REGISTRY_REVISION,
        'approval_required': bool(approval_required),
        'automatic_generation_supported': True,
    }


def get_available_deliverable_adapters(policy=None):
    """Return deterministic, server-owned deliverable adapter descriptors."""
    normalized_policy = _normalize_mapping(policy, 'policy')
    disabled_adapter_ids = set(_normalize_ids(normalized_policy.get('disabled_adapter_ids')))
    adapters = [
        _build_adapter(
            'inline_response',
            kind='inline_response',
            output_format='markdown',
            role='primary_inline_answer',
        ),
        _build_adapter(
            'markdown_analysis_artifact',
            kind='generated_file',
            output_format='md',
            role='supporting_audit_artifact',
        ),
        _build_adapter(
            'csv_structured_artifact',
            kind='generated_file',
            output_format='csv',
            role='structured_supporting_output',
        ),
    ]
    return [adapter for adapter in adapters if adapter['id'] not in disabled_adapter_ids]


def _adapter_by_format(adapters, requested_format):
    normalized_format = _normalize_format(requested_format)
    for adapter in adapters:
        if adapter.get('kind') == 'generated_file' and adapter.get('format') == normalized_format:
            return adapter
    return None


def normalize_directive_snapshot(directive_snapshot=None):
    """Normalize a resolved directive snapshot without reading raw instruction text."""
    if directive_snapshot is None:
        return {
            'available': False,
            'revision': None,
            'effects': {effect: [] for effect in DELIVERABLE_DIRECTIVE_EFFECTS},
        }
    if not isinstance(directive_snapshot, Mapping):
        raise ValueError('directive_snapshot must be a mapping')

    raw_effects = directive_snapshot.get('effects')
    if not isinstance(raw_effects, Mapping):
        raw_effects = directive_snapshot

    effects = {}
    for effect in DELIVERABLE_DIRECTIVE_EFFECTS:
        entries = []
        for index, entry in enumerate(raw_effects.get(effect) or []):
            if not isinstance(entry, Mapping):
                continue
            directive_ref = _normalize_text(
                entry.get('directive_ref') or entry.get('ref') or f'{effect}_{index + 1}',
                max_chars=160,
            )
            target = _normalize_text(
                entry.get('target') or entry.get('deliverable_kind') or entry.get('format'),
                max_chars=160,
            )
            if directive_ref:
                entries.append({
                    'directive_ref': directive_ref,
                    'target': target or '*',
                    'reason_code': _normalize_text(
                        entry.get('reason_code') or effect,
                        max_chars=120,
                    ),
                })
        effects[effect] = entries

    return {
        'available': True,
        'revision': _normalize_text(
            directive_snapshot.get('revision') or directive_snapshot.get('snapshot_revision'),
            max_chars=120,
        ) or None,
        'effects': effects,
    }


def _normalize_requested_output(requested_output=None):
    normalized = _normalize_mapping(requested_output, 'requested_output')
    output_type = _normalize_text(normalized.get('type') or 'response', max_chars=120) or 'response'
    output_format = _normalize_format(normalized.get('format') or normalized.get('file_format'))
    if not output_format:
        output_format = _detect_format_from_text(output_type)
    if not output_format:
        output_format = _detect_format_from_text(normalized.get('instructions'))

    normalized_output = {
        'type': output_type,
    }
    if output_format:
        normalized_output['format'] = output_format
    if isinstance(normalized.get('schema'), Mapping):
        normalized_output['schema'] = dict(normalized['schema'])
    instructions = []
    for instruction in normalized.get('instructions') or []:
        normalized_instruction = _normalize_text(instruction, max_chars=1000)
        if normalized_instruction and normalized_instruction not in instructions:
            instructions.append(normalized_instruction)
    if instructions:
        normalized_output['instructions'] = instructions[:24]
    return normalized_output


def _build_provisional_deliverables(requested_output, adapters):
    requested_format = requested_output.get('format')
    requested_type = str(requested_output.get('type') or '').strip().lower()
    if not requested_format and requested_type in GENERATED_FILE_FORMAT_ALIASES:
        requested_format = _normalize_format(requested_type)
    if not requested_format and requested_type in {'generated_file', 'file', 'artifact'}:
        requested_format = 'md'

    if not requested_format:
        return []

    adapter = _adapter_by_format(adapters, requested_format)
    if not adapter:
        return [{
            'id': f'unsupported_{requested_format}_deliverable',
            'kind': 'generated_file',
            'format': requested_format,
            'role': 'requested_output',
            'required': True,
            'adapter_id': None,
            'status': 'unsupported',
            'reason_codes': ['requested_format_not_supported'],
        }]

    return [{
        'id': f'{adapter["format"]}_requested_deliverable',
        'kind': adapter['kind'],
        'format': adapter['format'],
        'role': 'primary_requested_artifact',
        'required': True,
        'adapter_id': adapter['id'],
        'status': 'provisional',
        'reason_codes': ['explicit_requested_output'],
    }]


def _select_response_mode(provisional_deliverables, requested_output):
    if not provisional_deliverables:
        return 'inline_response_only'
    if str(requested_output.get('type') or '').strip().lower() in {'summary_with_artifact', 'summary'}:
        return 'summary_with_supporting_artifacts'
    if any(deliverable.get('required') for deliverable in provisional_deliverables):
        return 'summary_with_primary_artifact'
    return 'summary_with_supporting_artifacts'


def build_deliverable_intent(
    original_request,
    plan,
    *,
    requested_output=None,
    output_profile=None,
    directive_snapshot=None,
    adapters=None,
    policy=None,
    capability_plan_revision=None,
    intent_revision=DEFAULT_DELIVERABLE_INTENT_REVISION,
    created_at=None,
):
    """Build the pre-execution, server-authoritative deliverable intent."""
    if not isinstance(plan, Mapping):
        raise ValueError('plan must be a mapping')
    normalized_requested_output = _normalize_requested_output(requested_output)
    normalized_output_profile = _normalize_mapping(output_profile, 'output_profile')
    normalized_policy = _normalize_mapping(policy, 'policy')
    available_adapters = list(adapters or get_available_deliverable_adapters(normalized_policy))
    provisional_deliverables = _build_provisional_deliverables(
        normalized_requested_output,
        available_adapters,
    )
    directive_constraints = normalize_directive_snapshot(directive_snapshot)
    response_mode = _select_response_mode(provisional_deliverables, normalized_requested_output)

    return {
        'version': DELIVERABLE_PLAN_CONTRACT_VERSION,
        'deliverable_intent_revision': int(intent_revision),
        'run_id': _normalize_text(plan.get('run_id'), max_chars=160) or None,
        'source_plan_id': _normalize_text(plan.get('run_id'), max_chars=160) or None,
        'capability_plan_revision': capability_plan_revision or plan.get('version'),
        'requested_outcome': _normalize_text(original_request, max_chars=8000),
        'requested_output': normalized_requested_output,
        'output_profile': normalized_output_profile,
        'response_mode': response_mode,
        'primary_response': {
            'type': 'inline_summary' if provisional_deliverables else 'inline_answer',
            'target_length': 'concise' if provisional_deliverables else 'complete',
            'must_include': ['what_was_done', 'key_findings', 'next_actions']
            if provisional_deliverables
            else [],
        },
        'provisional_deliverables': provisional_deliverables,
        'available_adapters': available_adapters,
        'directive_constraints': directive_constraints,
        'constraints': {
            'supported_evidence_only': True,
            'do_not_claim_unpublished_artifacts': True,
            'preserve_missing_and_partial_coverage': True,
            'max_inline_chars': int(
                normalized_policy.get('max_inline_chars') or DEFAULT_INLINE_RESPONSE_MAX_CHARS
            ),
            'automatic_optional_artifacts_allowed': _normalize_bool(
                normalized_policy.get('automatic_optional_artifacts_allowed'),
                default=True,
            ),
        },
        'policy': {
            'publication_target': _normalize_text(
                normalized_policy.get('publication_target') or 'chat_message',
                max_chars=120,
            ),
            'audience_scope': _normalize_text(
                normalized_policy.get('audience_scope') or 'conversation',
                max_chars=120,
            ),
            'approval_required_for_storage': _normalize_bool(
                normalized_policy.get('approval_required_for_storage'),
                default=False,
            ),
        },
        'created_at': _normalize_text(created_at, max_chars=120) or _utc_now(),
    }


def _ledger_ids(ledger, section):
    if not isinstance(ledger, Mapping):
        return []
    values = ledger.get(section) or []
    return [entry.get('id') for entry in values if isinstance(entry, Mapping) and entry.get('id')]


def _build_evidence_snapshot(ledger):
    return {
        'ledger_status': _normalize_text((ledger or {}).get('status'), max_chars=80),
        'requirement_ids': _ledger_ids(ledger, 'requirements'),
        'source_ids': _ledger_ids(ledger, 'sources'),
        'fact_ids': _ledger_ids(ledger, 'facts'),
        'result_ids': _ledger_ids(ledger, 'results'),
        'artifact_ids': _ledger_ids(ledger, 'artifacts'),
        'conflict_ids': _ledger_ids(ledger, 'conflicts'),
        'missing_or_failed_ids': _ledger_ids(ledger, 'missing_or_failed'),
    }


def _materialize_deliverable(deliverable, evidence_snapshot, intent):
    required = _normalize_bool(deliverable.get('required'), default=False)
    ledger_status = evidence_snapshot.get('ledger_status')
    missing_count = len(evidence_snapshot.get('missing_or_failed_ids') or [])
    status = 'planned'
    if deliverable.get('status') == 'unsupported':
        status = 'failed'
    elif ledger_status == 'failed' and required:
        status = 'failed'
    elif missing_count:
        status = 'partial'

    approval_required = bool(
        deliverable.get('approval_required')
        or intent.get('policy', {}).get('approval_required_for_storage')
        or intent.get('directive_constraints', {}).get('effects', {}).get('ask_first')
    )
    return {
        'id': _normalize_identifier(deliverable.get('id'), 'deliverable id'),
        'kind': _normalize_identifier(deliverable.get('kind'), 'deliverable kind'),
        'format': _normalize_text(deliverable.get('format'), max_chars=80) or None,
        'role': _normalize_text(deliverable.get('role'), max_chars=160) or 'supporting_output',
        'required': required,
        'status': status,
        'adapter_id': _normalize_text(deliverable.get('adapter_id'), max_chars=160) or None,
        'adapter_schema_revision': 1,
        'source_evidence': (
            ['ledger_supported_facts']
            if evidence_snapshot.get('fact_ids')
            else ['ledger_results']
            if evidence_snapshot.get('result_ids')
            else []
        ),
        'approval_required': approval_required,
        'approval': {
            'state': 'required' if approval_required else 'not_required',
            'bound_to_materialized_plan_revision': None,
        },
        'publication': {
            'target': intent.get('policy', {}).get('publication_target') or 'chat_message',
            'audience_scope': intent.get('policy', {}).get('audience_scope') or 'conversation',
            'state': 'not_published',
        },
        'failure_behavior': 'disclose_failure_and_continue',
        'reason_codes': list(deliverable.get('reason_codes') or []),
    }


def materialize_deliverable_plan(
    deliverable_intent,
    ledger,
    *,
    materialized_plan_revision=DEFAULT_MATERIALIZED_DELIVERABLE_PLAN_REVISION,
    partial_evidence_override=None,
    approval_decision=None,
    created_at=None,
):
    """Bind deliverable intent to a terminal evidence snapshot."""
    intent = _normalize_mapping(deliverable_intent, 'deliverable_intent')
    if intent.get('version') != DELIVERABLE_PLAN_CONTRACT_VERSION:
        raise ValueError('deliverable_intent must use a supported version')
    if not isinstance(ledger, Mapping):
        raise ValueError('ledger must be a mapping')

    evidence_snapshot = _build_evidence_snapshot(ledger)
    deliverables = [
        _materialize_deliverable(deliverable, evidence_snapshot, intent)
        for deliverable in intent.get('provisional_deliverables') or []
        if isinstance(deliverable, Mapping)
    ]
    approval = _normalize_mapping(approval_decision, 'approval_decision')
    normalized_revision = int(materialized_plan_revision)
    for deliverable in deliverables:
        deliverable['approval']['bound_to_materialized_plan_revision'] = normalized_revision
        if approval.get('state'):
            deliverable['approval']['state'] = _normalize_text(approval.get('state'), max_chars=80)

    materialized = {
        'version': DELIVERABLE_PLAN_CONTRACT_VERSION,
        'deliverable_intent_revision': intent.get('deliverable_intent_revision'),
        'materialized_plan_revision': normalized_revision,
        'run_id': intent.get('run_id') or ledger.get('run_id'),
        'source_plan_id': intent.get('source_plan_id'),
        'requested_outcome': intent.get('requested_outcome') or '',
        'response_mode': intent.get('response_mode') or 'inline_response_only',
        'primary_response': dict(intent.get('primary_response') or {}),
        'deliverables': deliverables,
        'evidence_snapshot': evidence_snapshot,
        'constraints': dict(intent.get('constraints') or {}),
        'directive_outcomes': {
            'applied': [],
            'overridden': [],
            'conflicting': [],
            'ignored': [],
            'source_revision': (
                intent.get('directive_constraints') or {}
            ).get('revision'),
        },
        'approval_decision': approval or {'state': 'not_required'},
        'publication_lineage': [],
        'created_at': _normalize_text(created_at, max_chars=120) or _utc_now(),
    }
    if partial_evidence_override:
        if not isinstance(partial_evidence_override, Mapping):
            raise ValueError('partial_evidence_override must be a mapping')
        materialized['partial_evidence_override'] = {
            'state': 'accepted',
            'missing_or_failed_ids': evidence_snapshot['missing_or_failed_ids'],
            'decision_ref': _normalize_text(
                partial_evidence_override.get('decision_ref'),
                max_chars=160,
            ) or None,
            'approved_at': _normalize_text(
                partial_evidence_override.get('approved_at'),
                max_chars=120,
            ) or _utc_now(),
            'disclosure_required': True,
        }
    return materialized
