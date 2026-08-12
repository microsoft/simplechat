# functions_tabular_parity_contract.py
"""Observation-only tabular Search/Analyze parity contracts."""

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field


def log_event(*args, **kwargs):
    """Lazily resolve telemetry logging so contract tests do not require Azure packages."""
    try:
        from functions_appinsights import log_event as _log_event_impl
    except ImportError:
        return None
    return _log_event_impl(*args, **kwargs)


TABULAR_PARITY_PLANNER_CONTRACT_VERSION = 1

TABULAR_PARITY_CONTRACT_FOREGROUND_AGGREGATE = 'foreground_aggregate'
TABULAR_PARITY_CONTRACT_STRUCTURED_EXPORT = 'structured_export'
TABULAR_PARITY_CONTRACT_HIERARCHICAL_ANALYSIS = 'hierarchical_analysis'
TABULAR_PARITY_CONTRACT_COMBINED = 'combined'

TABULAR_PARITY_STATE_PLANNED = 'planned'
TABULAR_PARITY_STATE_FOREGROUND = 'foreground'
TABULAR_PARITY_STATE_QUEUED = 'queued'
TABULAR_PARITY_STATE_RUNNING = 'running'
TABULAR_PARITY_STATE_COMPLETED = 'completed'
TABULAR_PARITY_STATE_PARTIAL = 'partial'
TABULAR_PARITY_STATE_FAILED = 'failed'
TABULAR_PARITY_STATE_CANCELED = 'canceled'

TABULAR_PARITY_EVIDENCE_PENDING = 'pending'
TABULAR_PARITY_EVIDENCE_COMPLETE = 'complete'
TABULAR_PARITY_EVIDENCE_PARTIAL = 'partial'
TABULAR_PARITY_EVIDENCE_FAILED = 'failed'
TABULAR_PARITY_EVIDENCE_CANCELED = 'canceled'
TABULAR_PARITY_EVIDENCE_NONE = 'none'

TABULAR_PARITY_EVENT_CLASSIFICATION_STARTED = 'classification_started'
TABULAR_PARITY_EVENT_CLASSIFICATION_COMPLETED = 'classification_completed'
TABULAR_PARITY_EVENT_CLASSIFICATION_FAILED = 'classification_failed'
TABULAR_PARITY_EVENT_SOURCE_MANIFEST_RESOLVED = 'source_manifest_resolved'
TABULAR_PARITY_EVENT_DURABLE_PREFLIGHT_ATTEMPTED = 'durable_preflight_attempted'
TABULAR_PARITY_EVENT_DURABLE_PREFLIGHT_ACCEPTED = 'durable_preflight_accepted'
TABULAR_PARITY_EVENT_DURABLE_PREFLIGHT_DECLINED = 'durable_preflight_declined'
TABULAR_PARITY_EVENT_DURABLE_PREFLIGHT_FAILED = 'durable_preflight_failed'
TABULAR_PARITY_EVENT_FIRST_FOREGROUND_TABULAR_INVOCATION = 'first_foreground_tabular_invocation'
TABULAR_PARITY_EVENT_POST_TOOL_FALLBACK_ATTEMPTED = 'post_tool_generated_output_fallback_attempted'
TABULAR_PARITY_EVENT_POST_TOOL_FALLBACK_USED = 'post_tool_generated_output_fallback_used'
TABULAR_PARITY_EVENT_EXECUTED_CONTRACT_MISMATCH = 'planner_executed_contract_mismatch'
TABULAR_PARITY_EVENT_RESPONSE_METADATA_EMITTED = 'response_metadata_emitted'

TABULAR_PARITY_EVENT_NAMES = frozenset({
    TABULAR_PARITY_EVENT_CLASSIFICATION_STARTED,
    TABULAR_PARITY_EVENT_CLASSIFICATION_COMPLETED,
    TABULAR_PARITY_EVENT_CLASSIFICATION_FAILED,
    TABULAR_PARITY_EVENT_SOURCE_MANIFEST_RESOLVED,
    TABULAR_PARITY_EVENT_DURABLE_PREFLIGHT_ATTEMPTED,
    TABULAR_PARITY_EVENT_DURABLE_PREFLIGHT_ACCEPTED,
    TABULAR_PARITY_EVENT_DURABLE_PREFLIGHT_DECLINED,
    TABULAR_PARITY_EVENT_DURABLE_PREFLIGHT_FAILED,
    TABULAR_PARITY_EVENT_FIRST_FOREGROUND_TABULAR_INVOCATION,
    TABULAR_PARITY_EVENT_POST_TOOL_FALLBACK_ATTEMPTED,
    TABULAR_PARITY_EVENT_POST_TOOL_FALLBACK_USED,
    TABULAR_PARITY_EVENT_EXECUTED_CONTRACT_MISMATCH,
    TABULAR_PARITY_EVENT_RESPONSE_METADATA_EMITTED,
})

TABULAR_PARITY_DURABLE_CONTRACTS = frozenset({
    TABULAR_PARITY_CONTRACT_STRUCTURED_EXPORT,
    TABULAR_PARITY_CONTRACT_HIERARCHICAL_ANALYSIS,
    TABULAR_PARITY_CONTRACT_COMBINED,
})
TABULAR_PARITY_DURABLE_PENDING_STATES = frozenset({
    TABULAR_PARITY_STATE_PLANNED,
    TABULAR_PARITY_STATE_QUEUED,
    TABULAR_PARITY_STATE_RUNNING,
})
TABULAR_PARITY_SOURCE_KINDS = frozenset({'tabular', 'narrative', 'unsupported', 'unresolved'})
TABULAR_PARITY_MODES = frozenset({'search', 'analyze', 'compare', 'chat', 'workflow', 'unknown'})
TABULAR_PARITY_CONTRACT_MODES = frozenset({'off', 'observe', 'shadow'})
TABULAR_PARITY_CONTRACT_OBSERVATION_MODES = frozenset({'observe', 'shadow'})


@dataclass(frozen=True)
class TabularParityPlannerResult:
    """Serializable normalized parity result for observation and tests."""

    planner_contract_version: int = TABULAR_PARITY_PLANNER_CONTRACT_VERSION
    execution_contract: str = TABULAR_PARITY_CONTRACT_FOREGROUND_AGGREGATE
    execution_state: str = TABULAR_PARITY_STATE_PLANNED
    requires_full_source: bool = False
    requires_structured_artifact: bool = False
    requested_output_format: str = ''
    decision_reason_code: str = 'ambiguous_foreground_default'
    source_manifest_fingerprint: str = ''
    source_coverage: dict = field(default_factory=dict)
    generated_tabular_outputs: list = field(default_factory=list)
    evidence_state: str = TABULAR_PARITY_EVIDENCE_NONE
    deferred_composition_required: bool = False
    token_usage: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def _normalize_lower_text(value):
    return re.sub(r'\s+', ' ', str(value or '').strip().lower())


def _safe_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_parity_mode(mode):
    normalized_mode = str(mode or '').strip().lower()
    if normalized_mode in TABULAR_PARITY_MODES:
        return normalized_mode
    return 'unknown'


def _normalize_reason_code(reason_code):
    normalized_reason = re.sub(r'[^a-z0-9_]+', '_', str(reason_code or '').strip().lower())
    normalized_reason = re.sub(r'_+', '_', normalized_reason).strip('_')
    return normalized_reason[:80] or 'unknown'


def _normalize_dimension_value(value):
    dimension_text = str(value or '').strip()
    if re.fullmatch(r'[A-Za-z0-9_-]{1,80}', dimension_text):
        return _normalize_reason_code(dimension_text)
    first_token = re.split(r'[:/\\\s]+', dimension_text, maxsplit=1)[0]
    return _normalize_reason_code(first_token)


def _normalize_output_format(user_question):
    normalized_question = _normalize_lower_text(user_question)
    format_patterns = (
        ('xlsx', r'\bxlsx\b'),
        ('xlsm', r'\bxlsm\b'),
        ('xls', r'\bxls\b'),
        ('csv', r'\bcsv\b'),
        ('json', r'\bjson\b'),
        ('xml', r'\bxml\b'),
    )
    for output_format, pattern in format_patterns:
        if re.search(pattern, normalized_question):
            return output_format
    workbook_artifact_markers = (
        'download',
        'export',
        'save',
        'generate',
        'create',
        'produce',
        'build',
        'write',
        'artifact',
        'output',
    )
    if (
        re.search(r'\b(?:excel workbook|workbook|spreadsheet)\b', normalized_question)
        and _question_has_any_marker(normalized_question, workbook_artifact_markers)
    ):
        return 'xlsx'
    return ''


def _question_has_any_marker(normalized_question, markers):
    return any(marker in normalized_question for marker in markers)


def _question_requests_structured_artifact(normalized_question, output_format):
    if not output_format:
        return False
    artifact_markers = (
        'download',
        'export',
        'save',
        'generate',
        'create',
        'produce',
        'build',
        'write',
        'file',
        'artifact',
        'output',
    )
    structured_markers = (
        'one row per',
        'one object per',
        'each row',
        'every row',
        'for each row',
        'for every row',
        'all rows',
        'all records',
        'full dataset',
        'entire dataset',
        'no omissions',
    )
    format_phrase_patterns = (
        rf'\bas\s+(?:a\s+)?{re.escape(output_format)}\b',
        rf'\bin\s+(?:a\s+)?{re.escape(output_format)}\b',
        rf'\bto\s+(?:a\s+)?{re.escape(output_format)}\b',
    )
    return (
        _question_has_any_marker(normalized_question, artifact_markers)
        or _question_has_any_marker(normalized_question, structured_markers)
        or any(re.search(pattern, normalized_question) for pattern in format_phrase_patterns)
    )


def _question_requests_full_source(normalized_question):
    exhaustive_markers = (
        'all rows',
        'every row',
        'each row',
        'for each row',
        'for every row',
        'all records',
        'every record',
        'each record',
        'full dataset',
        'entire dataset',
        'whole dataset',
        'complete dataset',
        'full table',
        'entire table',
        'whole table',
        'full file',
        'entire file',
        'whole file',
        'each transaction',
        'every transaction',
        'no omissions',
        'do not omit',
        'without omitting',
        'summarize the entire table',
        'summarise the entire table',
        'summarize the whole table',
        'summarise the whole table',
    )
    return _question_has_any_marker(normalized_question, exhaustive_markers)


def _question_requests_analysis(normalized_question):
    analysis_markers = (
        'analyze',
        'analyse',
        'analysis',
        'summarize',
        'summarise',
        'summary',
        'synthesize',
        'synthesise',
        'evaluate',
        'assess',
        'classify',
        'review',
        'find patterns',
        'patterns',
        'themes',
        'risks',
        'insights',
        'explain',
    )
    return _question_has_any_marker(normalized_question, analysis_markers)


def _question_requests_bounded_foreground(normalized_question):
    bounded_markers = (
        'count',
        'average',
        'mean',
        'sum',
        'total',
        'minimum',
        'maximum',
        'group by',
        'filter',
        'lookup',
        'find rows where',
        'show a sample',
        'sample rows',
        'first 5',
        'first five',
        'first 10',
        'first ten',
        'top 5',
        'top five',
        'top 10',
        'top ten',
        'inspect columns',
        'list columns',
        'column names',
        'schema',
    )
    return _question_has_any_marker(normalized_question, bounded_markers)


def build_tabular_parity_source_coverage(source_manifest=None):
    coverage = {
        'requested_source_count': 0,
        'authorized_source_count': 0,
        'tabular_source_count': 0,
        'narrative_source_count': 0,
        'unsupported_source_count': 0,
        'unresolved_source_count': 0,
    }
    for source in list(source_manifest or []):
        if not isinstance(source, dict):
            continue
        coverage['requested_source_count'] += 1
        if str(source.get('authorization_status') or '').strip().lower() == 'authorized':
            coverage['authorized_source_count'] += 1
        source_kind = str(source.get('source_kind') or '').strip().lower()
        if source_kind not in TABULAR_PARITY_SOURCE_KINDS:
            source_kind = 'unsupported'
        coverage[f'{source_kind}_source_count'] += 1
    return coverage


def build_tabular_parity_source_manifest_fingerprint(source_manifest=None):
    canonical_sources = []
    for source in list(source_manifest or []):
        if not isinstance(source, dict):
            continue
        canonical_sources.append({
            'authorization_status': str(source.get('authorization_status') or '').strip().lower(),
            'document_id': str(source.get('document_id') or '').strip(),
            'scope': str(source.get('scope') or '').strip().lower(),
            'scope_id': str(source.get('scope_id') or '').strip(),
            'source_kind': str(source.get('source_kind') or '').strip().lower(),
            'source_version': str(source.get('source_version') or '').strip(),
        })
    if not canonical_sources:
        return ''
    canonical_sources.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(',', ':')))
    canonical_payload = json.dumps(canonical_sources, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical_payload.encode('utf-8')).hexdigest()[:24]


def infer_tabular_parity_evidence_state(execution_contract, execution_state):
    normalized_contract = str(execution_contract or '').strip().lower()
    normalized_state = str(execution_state or TABULAR_PARITY_STATE_PLANNED).strip().lower()
    if normalized_state in {TABULAR_PARITY_STATE_FAILED}:
        return TABULAR_PARITY_EVIDENCE_FAILED
    if normalized_state in {TABULAR_PARITY_STATE_CANCELED}:
        return TABULAR_PARITY_EVIDENCE_CANCELED
    if normalized_contract in TABULAR_PARITY_DURABLE_CONTRACTS:
        if normalized_state in TABULAR_PARITY_DURABLE_PENDING_STATES:
            return TABULAR_PARITY_EVIDENCE_PENDING
        if normalized_state == TABULAR_PARITY_STATE_COMPLETED:
            return TABULAR_PARITY_EVIDENCE_COMPLETE
        if normalized_state == TABULAR_PARITY_STATE_PARTIAL:
            return TABULAR_PARITY_EVIDENCE_PARTIAL
        return TABULAR_PARITY_EVIDENCE_PENDING
    if normalized_contract == TABULAR_PARITY_CONTRACT_FOREGROUND_AGGREGATE:
        if normalized_state in {TABULAR_PARITY_STATE_FOREGROUND, TABULAR_PARITY_STATE_COMPLETED}:
            return TABULAR_PARITY_EVIDENCE_COMPLETE
        if normalized_state == TABULAR_PARITY_STATE_PARTIAL:
            return TABULAR_PARITY_EVIDENCE_PARTIAL
    return TABULAR_PARITY_EVIDENCE_NONE


def build_tabular_parity_planner_result(
    execution_contract,
    execution_state=TABULAR_PARITY_STATE_PLANNED,
    requires_full_source=False,
    requires_structured_artifact=False,
    requested_output_format='',
    decision_reason_code='ambiguous_foreground_default',
    source_manifest=None,
    source_coverage=None,
    generated_tabular_outputs=None,
    evidence_state=None,
    deferred_composition_required=False,
    token_usage=None,
):
    normalized_contract = str(execution_contract or TABULAR_PARITY_CONTRACT_FOREGROUND_AGGREGATE).strip().lower()
    normalized_state = str(execution_state or TABULAR_PARITY_STATE_PLANNED).strip().lower()
    coverage = dict(source_coverage or build_tabular_parity_source_coverage(source_manifest))
    return TabularParityPlannerResult(
        execution_contract=normalized_contract,
        execution_state=normalized_state,
        requires_full_source=bool(requires_full_source),
        requires_structured_artifact=bool(requires_structured_artifact),
        requested_output_format=str(requested_output_format or '').strip().lower(),
        decision_reason_code=_normalize_reason_code(decision_reason_code),
        source_manifest_fingerprint=build_tabular_parity_source_manifest_fingerprint(source_manifest),
        source_coverage=coverage,
        generated_tabular_outputs=list(generated_tabular_outputs or []),
        evidence_state=evidence_state or infer_tabular_parity_evidence_state(normalized_contract, normalized_state),
        deferred_composition_required=bool(deferred_composition_required),
        token_usage=dict(token_usage or {}),
    )


def classify_tabular_parity_request(user_question, source_manifest=None):
    normalized_question = _normalize_lower_text(user_question)
    output_format = _normalize_output_format(normalized_question)
    requires_artifact = _question_requests_structured_artifact(normalized_question, output_format)
    requires_full_source = _question_requests_full_source(normalized_question)
    requests_analysis = _question_requests_analysis(normalized_question)
    requests_bounded_foreground = _question_requests_bounded_foreground(normalized_question)

    if requires_artifact and requires_full_source and requests_analysis:
        return build_tabular_parity_planner_result(
            TABULAR_PARITY_CONTRACT_COMBINED,
            requires_full_source=True,
            requires_structured_artifact=True,
            requested_output_format=output_format,
            decision_reason_code='explicit_full_source_analysis_and_artifact',
            source_manifest=source_manifest,
            deferred_composition_required=True,
        )
    if requires_artifact:
        return build_tabular_parity_planner_result(
            TABULAR_PARITY_CONTRACT_STRUCTURED_EXPORT,
            requires_full_source=True,
            requires_structured_artifact=True,
            requested_output_format=output_format,
            decision_reason_code='explicit_structured_artifact',
            source_manifest=source_manifest,
        )
    if requires_full_source and requests_analysis:
        return build_tabular_parity_planner_result(
            TABULAR_PARITY_CONTRACT_HIERARCHICAL_ANALYSIS,
            requires_full_source=True,
            requires_structured_artifact=False,
            requested_output_format='',
            decision_reason_code='explicit_full_source_analysis',
            source_manifest=source_manifest,
            deferred_composition_required=True,
        )
    if requests_bounded_foreground:
        return build_tabular_parity_planner_result(
            TABULAR_PARITY_CONTRACT_FOREGROUND_AGGREGATE,
            execution_state=TABULAR_PARITY_STATE_FOREGROUND,
            requires_full_source=False,
            requires_structured_artifact=False,
            requested_output_format='',
            decision_reason_code='bounded_aggregate_or_inspection',
            source_manifest=source_manifest,
        )
    return build_tabular_parity_planner_result(
        TABULAR_PARITY_CONTRACT_FOREGROUND_AGGREGATE,
        execution_state=TABULAR_PARITY_STATE_FOREGROUND,
        requires_full_source=False,
        requires_structured_artifact=False,
        requested_output_format=output_format,
        decision_reason_code='ambiguous_foreground_default',
        source_manifest=source_manifest,
    )


def is_tabular_parity_telemetry_enabled(settings):
    normalized_settings = settings if isinstance(settings, dict) else {}
    contract_mode = str(normalized_settings.get('tabular_parity_contract_mode') or 'off').strip().lower()
    if contract_mode not in TABULAR_PARITY_CONTRACT_MODES:
        contract_mode = 'off'
    return (
        _safe_bool(normalized_settings.get('enable_tabular_parity_contract_telemetry', False))
        and contract_mode in TABULAR_PARITY_CONTRACT_OBSERVATION_MODES
    )


def build_safe_tabular_parity_event_properties(
    event_name,
    mode,
    planner_result=None,
    metrics=None,
    dimensions=None,
):
    result = planner_result.to_dict() if isinstance(planner_result, TabularParityPlannerResult) else dict(planner_result or {})
    coverage = result.get('source_coverage') if isinstance(result.get('source_coverage'), dict) else {}
    properties = {
        'event_name': event_name if event_name in TABULAR_PARITY_EVENT_NAMES else 'unknown',
        'mode': _normalize_parity_mode(mode),
        'planner_contract_version': _safe_int(
            result.get('planner_contract_version'),
            TABULAR_PARITY_PLANNER_CONTRACT_VERSION,
        ),
        'execution_contract': str(result.get('execution_contract') or '').strip().lower()[:64],
        'execution_state': str(result.get('execution_state') or '').strip().lower()[:64],
        'evidence_state': str(result.get('evidence_state') or '').strip().lower()[:64],
        'decision_reason_code': _normalize_reason_code(result.get('decision_reason_code')),
        'requires_full_source': bool(result.get('requires_full_source')),
        'requires_structured_artifact': bool(result.get('requires_structured_artifact')),
        'requested_output_format': str(result.get('requested_output_format') or '').strip().lower()[:16],
        'source_manifest_fingerprint': str(result.get('source_manifest_fingerprint') or '').strip()[:24],
        'requested_source_count': _safe_int(coverage.get('requested_source_count')),
        'authorized_source_count': _safe_int(coverage.get('authorized_source_count')),
        'tabular_source_count': _safe_int(coverage.get('tabular_source_count')),
        'narrative_source_count': _safe_int(coverage.get('narrative_source_count')),
        'unsupported_source_count': _safe_int(coverage.get('unsupported_source_count')),
        'unresolved_source_count': _safe_int(coverage.get('unresolved_source_count')),
    }
    for key, value in dict(metrics or {}).items():
        safe_key = _normalize_reason_code(key)
        properties[f'metric_{safe_key}'] = _safe_int(value)
    for key, value in dict(dimensions or {}).items():
        safe_key = _normalize_reason_code(key)
        if isinstance(value, bool):
            properties[f'dimension_{safe_key}'] = value
        elif isinstance(value, (int, float)):
            properties[f'dimension_{safe_key}'] = value
        else:
            properties[f'dimension_{safe_key}'] = _normalize_dimension_value(value)
    return properties


def emit_tabular_parity_event(
    settings,
    event_name,
    mode,
    planner_result=None,
    metrics=None,
    dimensions=None,
    level=logging.INFO,
):
    if not is_tabular_parity_telemetry_enabled(settings):
        return None
    properties = build_safe_tabular_parity_event_properties(
        event_name,
        mode,
        planner_result=planner_result,
        metrics=metrics,
        dimensions=dimensions,
    )
    log_event(
        '[TABULAR_PARITY_CONTRACT] Tabular parity observation event.',
        properties,
        level=level,
        debug_only=True,
    )
    return properties
