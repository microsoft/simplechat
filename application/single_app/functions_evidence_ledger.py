# functions_evidence_ledger.py
"""Output-neutral result and evidence ledger helpers for chat orchestration."""

import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit


EVIDENCE_LEDGER_VERSION = 1
EVIDENCE_LEDGER_GUIDANCE_MARKER = '[Turn Evidence Ledger]'

SOURCE_STATUSES = frozenset({
    'not_requested',
    'planned',
    'pending',
    'running',
    'succeeded',
    'partial',
    'not_found',
    'not_available',
    'failed',
    'unauthorized',
    'skipped',
    'cancelled',
})
AUTHORIZATION_STATUSES = frozenset({
    'pending',
    'authorized',
    'denied',
    'not_required',
})
REQUIREMENT_STATUSES = frozenset({
    'pending',
    'satisfied',
    'partial',
    'unsatisfied',
    'not_required',
})
FACT_CONFIDENCE_LEVELS = frozenset({
    'source_supported',
    'derived_from_sources',
    'user_provided',
    'placeholder',
    'unsupported',
})
RESULT_STATUSES = frozenset({'succeeded', 'partial', 'failed'})
CONFLICT_STATUSES = frozenset({'unresolved', 'resolved'})
LEDGER_STATUSES = frozenset({
    'collecting',
    'ready',
    'partial',
    'failed',
    'completed',
    'cancelled',
})

SENSITIVE_METADATA_KEY_PARTS = (
    'connection',
    'credential',
    'endpoint',
    'key',
    'password',
    'secret',
    'token',
)
REQUIREMENT_SOURCE_TYPES = {
    'public_web': (
        'public_web',
        'web_search',
        'url_access',
        'source_review',
        'deep_research',
    ),
    'workspace_search': (
        'workspace_search',
        'selected_documents',
        'user_workspace_context',
        'conversation_documents',
    ),
    'conversation_evidence': (
        'conversation_evidence',
        'conversation_history',
        'chat_upload',
        'prior_citations',
    ),
    'selected_images': ('selected_images', 'selected_image'),
    'unspecified_grounding': ('evidence_discovery',),
}
MODEL_LEDGER_SECTIONS = (
    'requirements',
    'sources',
    'missing_or_failed',
    'conflicts',
    'unsupported_facts',
    'facts',
    'results',
    'citations',
    'artifacts',
)
COMPACTION_INSERTION_ORDER = (
    'requirements',
    'sources',
    'citations',
    'artifacts',
    'facts',
    'unsupported_facts',
    'results',
    'conflicts',
    'missing_or_failed',
)


def _normalize_identifier(value, field_name):
    identifier = str(value or '').strip()
    if not identifier:
        raise ValueError(f'{field_name} is required')
    return identifier


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


def _normalize_text(value, field_name, *, required=False, max_chars=4000):
    normalized = str(value or '').strip()
    if required and not normalized:
        raise ValueError(f'{field_name} is required')
    if len(normalized) > max_chars:
        return f'{normalized[:max_chars - 3]}...'
    return normalized


def _validate_choice(value, allowed_values, field_name):
    normalized = _normalize_identifier(value, field_name).lower()
    if normalized not in allowed_values:
        expected = ', '.join(sorted(allowed_values))
        raise ValueError(f'{field_name} must be one of: {expected}')
    return normalized


def _sanitize_uri(value):
    normalized = _normalize_text(value, 'uri', max_chars=2000)
    if not normalized:
        return ''
    try:
        parsed = urlsplit(normalized)
    except ValueError:
        return ''
    if parsed.scheme.lower() not in {'http', 'https'}:
        if parsed.scheme:
            return ''
        return urlunsplit(('', parsed.netloc, parsed.path, '', ''))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))


def _sanitize_reference(value):
    normalized = _normalize_text(value, 'reference', max_chars=1000)
    if (
        normalized.startswith(('http://', 'https://', '/', '//'))
        or '?' in normalized
        or '#' in normalized
    ):
        return _sanitize_uri(normalized)
    return normalized


def _looks_sensitive_string(value):
    normalized = value.strip().lower()
    return (
        normalized.startswith('bearer ')
        or 'accountkey=' in normalized
        or 'sharedaccesssignature=' in normalized
        or 'sig=' in normalized and ('https://' in normalized or 'http://' in normalized)
    )


def _sanitize_metadata_value(value, *, depth=0):
    """Return bounded metadata, omitting binary values and nesting beyond five levels."""
    if depth > 5 or isinstance(value, (bytes, bytearray, memoryview)):
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if _looks_sensitive_string(value):
            return None
        normalized = _normalize_text(value, 'metadata value', max_chars=1000)
        if normalized.startswith(('http://', 'https://')):
            return _sanitize_uri(normalized)
        return normalized
    if isinstance(value, Mapping):
        sanitized = {}
        for key, nested_value in value.items():
            normalized_key = str(key or '').strip()
            compact_key = ''.join(character for character in normalized_key.lower() if character.isalnum())
            if not normalized_key or any(part in compact_key for part in SENSITIVE_METADATA_KEY_PARTS):
                continue
            safe_value = _sanitize_metadata_value(nested_value, depth=depth + 1)
            if safe_value is not None:
                sanitized[normalized_key] = safe_value
        return sanitized
    if isinstance(value, (list, tuple, set)):
        sanitized = []
        for item in list(value)[:50]:
            safe_value = _sanitize_metadata_value(item, depth=depth + 1)
            if safe_value is not None:
                sanitized.append(safe_value)
        return sanitized
    return None


def _sanitize_metadata(metadata):
    if metadata is None:
        return {}
    if not isinstance(metadata, Mapping):
        raise ValueError('metadata must be a mapping')
    return _sanitize_metadata_value(metadata) or {}


def _require_ledger(ledger):
    if not isinstance(ledger, dict) or ledger.get('version') != EVIDENCE_LEDGER_VERSION:
        raise ValueError('ledger must be a supported evidence ledger')
    for section in MODEL_LEDGER_SECTIONS:
        if not isinstance(ledger.get(section), list):
            raise ValueError(f'ledger section {section} must be a list')


def _find_entry(ledger, section, entry_id):
    return next(
        (entry for entry in ledger.get(section, []) if entry.get('id') == entry_id),
        None,
    )


def _next_identifier(ledger, section, prefix, requested_id=None):
    if requested_id is not None:
        identifier = _normalize_identifier(requested_id, f'{prefix}_id')
        if _find_entry(ledger, section, identifier):
            raise ValueError(f'{prefix}_id already exists: {identifier}')
        return identifier

    existing_ids = {entry.get('id') for entry in ledger.get(section, [])}
    index = len(existing_ids) + 1
    identifier = f'{prefix}_{index}'
    while identifier in existing_ids:
        index += 1
        identifier = f'{prefix}_{index}'
    return identifier


def _require_known_ids(ledger, section, identifiers, field_name):
    normalized = _normalize_ids(identifiers)
    known_ids = {entry.get('id') for entry in ledger.get(section, [])}
    unknown_ids = [identifier for identifier in normalized if identifier not in known_ids]
    if unknown_ids:
        raise ValueError(f'{field_name} contains unknown ids: {", ".join(unknown_ids)}')
    return normalized


def _requirement_source_types(requirement_id):
    return list(REQUIREMENT_SOURCE_TYPES.get(requirement_id, (requirement_id,)))


def _humanize_identifier(identifier):
    return identifier.replace('_', ' ').strip().capitalize()


def create_evidence_ledger(
    task_type,
    conversation_id,
    user_message_id,
    requested_output,
    *,
    task_profile=None,
    run_id=None,
    created_at=None,
    orchestration_mode='coordinated',
    plan_version=None,
):
    """Create an empty JSON-serializable result and evidence ledger."""
    if not isinstance(requested_output, Mapping):
        raise ValueError('requested_output must be a mapping')

    normalized_mode = _validate_choice(
        orchestration_mode,
        frozenset({'direct', 'coordinated'}),
        'orchestration_mode',
    )
    ledger_status = 'collecting' if normalized_mode == 'coordinated' else 'ready'
    return {
        'version': EVIDENCE_LEDGER_VERSION,
        'run_id': str(run_id or uuid.uuid4()),
        'task_type': _normalize_identifier(task_type, 'task_type'),
        'task_profile': _normalize_text(task_profile, 'task_profile') or None,
        'orchestration_mode': normalized_mode,
        'plan_version': plan_version,
        'conversation_id': _normalize_text(conversation_id, 'conversation_id') or None,
        'user_message_id': _normalize_text(user_message_id, 'user_message_id') or None,
        'created_at': _normalize_text(created_at, 'created_at')
        or datetime.now(timezone.utc).isoformat(),
        'requested_output': _sanitize_metadata(requested_output),
        'status': ledger_status,
        'requirements': [],
        'sources': [],
        'facts': [],
        'unsupported_facts': [],
        'results': [],
        'citations': [],
        'artifacts': [],
        'conflicts': [],
        'missing_or_failed': [],
    }


def create_evidence_ledger_from_plan(
    plan,
    *,
    user_message_id,
    conversation_id=None,
    requested_output=None,
    created_at=None,
):
    """Initialize a ledger from an immutable orchestration plan."""
    if not isinstance(plan, Mapping):
        raise ValueError('plan must be a mapping')

    selection_snapshot = plan.get('selection_snapshot')
    if not isinstance(selection_snapshot, Mapping):
        selection_snapshot = {}
    effective_conversation_id = conversation_id or selection_snapshot.get('conversation_id')
    effective_requested_output = requested_output or {
        'type': plan.get('finalizer') or 'response',
        'task_type': plan.get('task_type') or 'answer',
    }
    ledger = create_evidence_ledger(
        plan.get('task_type') or 'answer',
        effective_conversation_id,
        user_message_id,
        effective_requested_output,
        task_profile=plan.get('task_profile'),
        run_id=plan.get('run_id'),
        created_at=created_at,
        orchestration_mode=plan.get('mode') or 'direct',
        plan_version=plan.get('version'),
    )

    for requirement_id in _normalize_ids(plan.get('evidence_requirements')):
        add_evidence_requirement(
            ledger,
            _humanize_identifier(requirement_id),
            _requirement_source_types(requirement_id),
            requirement_id=requirement_id,
        )

    for source in plan.get('sources') or []:
        if not isinstance(source, Mapping):
            continue
        source_id = _normalize_identifier(source.get('id'), 'source id')
        source_type = str(source.get('type') or source_id).strip()
        requirement_ids = [
            requirement['id']
            for requirement in ledger['requirements']
            if source_type in requirement.get('source_types', [])
        ]
        add_evidence_source(
            ledger,
            source_type,
            source.get('status') or 'planned',
            source_id=source_id,
            origin=source.get('origin'),
            required=source.get('required', True),
            requirement_ids=requirement_ids,
            metadata=source.get('metadata'),
            authorization_status='pending',
        )

    return ledger


def add_evidence_requirement(
    ledger,
    description,
    source_types,
    *,
    required=True,
    requirement_id=None,
    status='pending',
):
    """Add an evidence requirement and return its normalized entry."""
    _require_ledger(ledger)
    normalized_status = _validate_choice(status, REQUIREMENT_STATUSES, 'requirement status')
    identifier = _next_identifier(
        ledger,
        'requirements',
        'requirement',
        requested_id=requirement_id,
    )
    entry = {
        'id': identifier,
        'description': _normalize_text(description, 'description', required=True),
        'source_types': _normalize_ids(source_types),
        'required': bool(required),
        'status': normalized_status,
    }
    if not entry['source_types']:
        raise ValueError('source_types must contain at least one source type')
    ledger['requirements'].append(entry)
    return entry


def _reconcile_requirement_statuses(ledger):
    terminal_unsatisfied_statuses = {
        'not_found',
        'not_available',
        'failed',
        'unauthorized',
        'skipped',
        'cancelled',
        'not_requested',
    }
    for requirement in ledger['requirements']:
        if requirement['status'] == 'not_required':
            continue
        requirement_id = requirement['id']
        matching_sources = [
            source
            for source in ledger['sources']
            if requirement_id in source.get('requirement_ids', [])
        ]
        matching_gaps = [
            gap
            for gap in ledger['missing_or_failed']
            if requirement_id in gap.get('requirement_ids', [])
        ]
        source_statuses = {source.get('status') for source in matching_sources}
        if 'succeeded' in source_statuses and not matching_gaps:
            requirement['status'] = 'satisfied'
        elif 'succeeded' in source_statuses or 'partial' in source_statuses:
            requirement['status'] = 'partial'
        elif matching_gaps and not source_statuses.intersection({'planned', 'pending', 'running'}):
            requirement['status'] = 'unsatisfied'
        elif source_statuses and source_statuses.issubset(terminal_unsatisfied_statuses):
            requirement['status'] = 'unsatisfied'
        else:
            requirement['status'] = 'pending'


def add_evidence_source(
    ledger,
    source_type,
    status='planned',
    *,
    source_id=None,
    origin=None,
    required=None,
    summary='',
    requirement_ids=None,
    citations=None,
    artifacts=None,
    metadata=None,
    raw_metadata=None,
    authorization_status=None,
):
    """Add or update a normalized evidence source without retaining raw payloads."""
    _require_ledger(ledger)
    del raw_metadata
    normalized_type = _normalize_identifier(source_type, 'source_type')
    normalized_status = _validate_choice(status, SOURCE_STATUSES, 'source status')
    normalized_authorization = None
    if authorization_status is not None:
        normalized_authorization = _validate_choice(
            authorization_status,
            AUTHORIZATION_STATUSES,
            'authorization_status',
        )
    normalized_requirement_ids = None
    if requirement_ids is not None:
        normalized_requirement_ids = _require_known_ids(
            ledger,
            'requirements',
            requirement_ids,
            'requirement_ids',
        )
    identifier = str(source_id or '').strip()
    existing = _find_entry(ledger, 'sources', identifier) if identifier else None
    if existing:
        existing.update({
            'type': normalized_type,
            'origin': _normalize_text(origin, 'origin') or existing.get('origin'),
            'required': existing.get('required', True) if required is None else bool(required),
            'status': normalized_status,
            'authorization_status': normalized_authorization or existing.get('authorization_status', 'pending'),
            'summary': _normalize_text(summary, 'summary') or existing.get('summary', ''),
            'requirement_ids': (
                existing.get('requirement_ids', [])
                if normalized_requirement_ids is None
                else normalized_requirement_ids
            ),
            'metadata': {
                **existing.get('metadata', {}),
                **_sanitize_metadata(metadata),
            },
        })
        entry = existing
    else:
        identifier = _next_identifier(
            ledger,
            'sources',
            'source',
            requested_id=source_id,
        )
        entry = {
            'id': identifier,
            'type': normalized_type,
            'origin': _normalize_text(origin, 'origin') or None,
            'required': True if required is None else bool(required),
            'status': normalized_status,
            'authorization_status': normalized_authorization or 'pending',
            'summary': _normalize_text(summary, 'summary'),
            'requirement_ids': normalized_requirement_ids or [],
            'citation_ids': [],
            'artifact_ids': [],
            'metadata': _sanitize_metadata(metadata),
        }
        ledger['sources'].append(entry)

    if normalized_status == 'unauthorized':
        entry['authorization_status'] = 'denied'
    elif normalized_status in {'succeeded', 'partial'} and entry['authorization_status'] == 'pending':
        entry['authorization_status'] = 'authorized'

    for citation in citations or []:
        if not isinstance(citation, Mapping):
            raise ValueError('citations must contain mappings')
        citation_values = dict(citation)
        citation_values.pop('source_id', None)
        if 'citation_id' not in citation_values and 'id' in citation_values:
            citation_values['citation_id'] = citation_values.pop('id')
        add_citation(ledger, entry['id'], **citation_values)
    for artifact in artifacts or []:
        if not isinstance(artifact, Mapping):
            raise ValueError('artifacts must contain mappings')
        artifact_values = dict(artifact)
        artifact_type = artifact_values.pop('artifact_type', None) or artifact_values.pop('type', None)
        if 'artifact_id' not in artifact_values and 'id' in artifact_values:
            artifact_values['artifact_id'] = artifact_values.pop('id')
        artifact_values.setdefault('source_ids', [entry['id']])
        add_artifact(ledger, artifact_type, **artifact_values)

    _reconcile_requirement_statuses(ledger)
    return entry


def add_fact(
    ledger,
    text,
    source_ids,
    *,
    requirement_ids=None,
    confidence='source_supported',
    fact_id=None,
):
    """Add a fact, keeping unsupported statements outside the supported fact list."""
    _require_ledger(ledger)
    normalized_confidence = _validate_choice(
        confidence,
        FACT_CONFIDENCE_LEVELS,
        'confidence',
    )
    normalized_source_ids = _require_known_ids(
        ledger,
        'sources',
        source_ids,
        'source_ids',
    )
    normalized_requirement_ids = _require_known_ids(
        ledger,
        'requirements',
        requirement_ids,
        'requirement_ids',
    )
    if normalized_confidence in {'source_supported', 'derived_from_sources'} and not normalized_source_ids:
        raise ValueError(f'{normalized_confidence} facts require at least one source_id')
    denied_source_ids = [
        source_id
        for source_id in normalized_source_ids
        if (
            (_find_entry(ledger, 'sources', source_id) or {}).get('authorization_status') == 'denied'
            or (_find_entry(ledger, 'sources', source_id) or {}).get('status') == 'unauthorized'
        )
    ]
    if denied_source_ids and normalized_confidence != 'unsupported':
        raise ValueError(
            f'supported facts cannot use denied sources: {", ".join(denied_source_ids)}'
        )

    target_section = 'unsupported_facts' if normalized_confidence == 'unsupported' else 'facts'
    identifier = _next_identifier(
        ledger,
        target_section,
        'fact',
        requested_id=fact_id,
    )
    entry = {
        'id': identifier,
        'text': _normalize_text(text, 'text', required=True),
        'confidence': normalized_confidence,
        'source_ids': normalized_source_ids,
        'requirement_ids': normalized_requirement_ids,
    }
    ledger[target_section].append(entry)
    return entry


def add_citation(
    ledger,
    source_id,
    *,
    citation_id=None,
    title='',
    uri='',
    locator='',
    excerpt='',
    metadata=None,
):
    """Add a citation linked to one authorized evidence source."""
    _require_ledger(ledger)
    normalized_source_id = _require_known_ids(
        ledger,
        'sources',
        [source_id],
        'source_id',
    )[0]
    identifier = _next_identifier(
        ledger,
        'citations',
        'citation',
        requested_id=citation_id,
    )
    entry = {
        'id': identifier,
        'source_id': normalized_source_id,
        'title': _normalize_text(title, 'title', max_chars=1000),
        'uri': _sanitize_uri(uri),
        'locator': _normalize_text(locator, 'locator', max_chars=500),
        'excerpt': _normalize_text(excerpt, 'excerpt', max_chars=2000),
        'metadata': _sanitize_metadata(metadata),
    }
    ledger['citations'].append(entry)
    source = _find_entry(ledger, 'sources', normalized_source_id)
    source['citation_ids'].append(identifier)
    return entry


def add_artifact(
    ledger,
    artifact_type,
    *,
    artifact_id=None,
    name='',
    source_ids=None,
    reference='',
    metadata=None,
):
    """Add compact artifact lineage; direct generated artifacts may omit source_ids."""
    _require_ledger(ledger)
    normalized_source_ids = _require_known_ids(
        ledger,
        'sources',
        source_ids,
        'source_ids',
    )
    identifier = _next_identifier(
        ledger,
        'artifacts',
        'artifact',
        requested_id=artifact_id,
    )
    entry = {
        'id': identifier,
        'type': _normalize_identifier(artifact_type, 'artifact_type'),
        'name': _normalize_text(name, 'name', max_chars=1000),
        'source_ids': normalized_source_ids,
        'reference': _sanitize_reference(reference),
        'metadata': _sanitize_metadata(metadata),
    }
    ledger['artifacts'].append(entry)
    for normalized_source_id in normalized_source_ids:
        source = _find_entry(ledger, 'sources', normalized_source_id)
        source['artifact_ids'].append(identifier)
    return entry


def add_result(
    ledger,
    result_type,
    summary,
    *,
    result_id=None,
    status='succeeded',
    source_ids=None,
    requirement_ids=None,
    citation_ids=None,
    artifact_ids=None,
):
    """Add a computed or executor output with normalized provenance."""
    _require_ledger(ledger)
    entry = {
        'id': _next_identifier(
            ledger,
            'results',
            'result',
            requested_id=result_id,
        ),
        'type': _normalize_identifier(result_type, 'result_type'),
        'status': _validate_choice(status, RESULT_STATUSES, 'result status'),
        'summary': _normalize_text(summary, 'summary', required=True),
        'source_ids': _require_known_ids(ledger, 'sources', source_ids, 'source_ids'),
        'requirement_ids': _require_known_ids(
            ledger,
            'requirements',
            requirement_ids,
            'requirement_ids',
        ),
        'citation_ids': _require_known_ids(
            ledger,
            'citations',
            citation_ids,
            'citation_ids',
        ),
        'artifact_ids': _require_known_ids(
            ledger,
            'artifacts',
            artifact_ids,
            'artifact_ids',
        ),
    }
    ledger['results'].append(entry)
    return entry


def add_conflict(
    ledger,
    description,
    source_ids,
    *,
    conflict_id=None,
    fact_ids=None,
    requirement_ids=None,
    status='unresolved',
):
    """Record a material evidence conflict without silently resolving it."""
    _require_ledger(ledger)
    entry = {
        'id': _next_identifier(
            ledger,
            'conflicts',
            'conflict',
            requested_id=conflict_id,
        ),
        'description': _normalize_text(description, 'description', required=True),
        'status': _validate_choice(status, CONFLICT_STATUSES, 'conflict status'),
        'source_ids': _require_known_ids(ledger, 'sources', source_ids, 'source_ids'),
        'fact_ids': _require_known_ids(ledger, 'facts', fact_ids, 'fact_ids'),
        'requirement_ids': _require_known_ids(
            ledger,
            'requirements',
            requirement_ids,
            'requirement_ids',
        ),
    }
    if len(entry['source_ids']) < 2 and len(entry['fact_ids']) < 2:
        raise ValueError('conflicts require at least two source_ids or two fact_ids')
    ledger['conflicts'].append(entry)
    return entry


def _add_missing_or_failed(
    ledger,
    *,
    kind,
    source_type,
    status,
    message,
    requirement_ids=None,
    source_id=None,
    step_id=None,
    entry_id=None,
):
    _require_ledger(ledger)
    normalized_requirement_ids = _require_known_ids(
        ledger,
        'requirements',
        requirement_ids,
        'requirement_ids',
    )
    normalized_source_ids = _require_known_ids(
        ledger,
        'sources',
        [source_id] if source_id else [],
        'source_id',
    )
    normalized_status = _validate_choice(status, SOURCE_STATUSES, 'status')
    entry = {
        'id': _next_identifier(
            ledger,
            'missing_or_failed',
            'gap',
            requested_id=entry_id,
        ),
        'kind': kind,
        'requirement_ids': normalized_requirement_ids,
        'source_id': normalized_source_ids[0] if normalized_source_ids else None,
        'source_type': _normalize_identifier(source_type, 'source_type'),
        'status': normalized_status,
        'message': _normalize_text(message, 'message', required=True),
        'step_id': _normalize_text(step_id, 'step_id') or None,
    }
    ledger['missing_or_failed'].append(entry)
    if normalized_source_ids:
        source = _find_entry(ledger, 'sources', normalized_source_ids[0])
        if source:
            source['status'] = normalized_status
            if normalized_status == 'unauthorized':
                source['authorization_status'] = 'denied'
            elif (
                normalized_status in {'succeeded', 'partial', 'not_found', 'failed'}
                and source.get('authorization_status') == 'pending'
            ):
                source['authorization_status'] = 'authorized'
    _reconcile_requirement_statuses(ledger)
    return entry


def add_missing_evidence(
    ledger,
    requirement_id,
    source_type,
    status,
    message,
    *,
    source_id=None,
    missing_id=None,
):
    """Record evidence that was requested but unavailable or not found."""
    return _add_missing_or_failed(
        ledger,
        kind='missing_evidence',
        requirement_ids=[requirement_id] if requirement_id else [],
        source_type=source_type,
        source_id=source_id,
        status=status,
        message=message,
        entry_id=missing_id,
    )


def add_execution_failure(
    ledger,
    source_type,
    status,
    message,
    *,
    source_id=None,
    step_id=None,
    requirement_ids=None,
    failure_id=None,
):
    """Record an explicit executor failure, skip, denial, or cancellation."""
    return _add_missing_or_failed(
        ledger,
        kind='execution_failure',
        requirement_ids=requirement_ids,
        source_type=source_type,
        source_id=source_id,
        status=status,
        message=message,
        step_id=step_id,
        entry_id=failure_id,
    )


def set_evidence_ledger_status(ledger, status):
    """Set the turn-level ledger status."""
    _require_ledger(ledger)
    ledger['status'] = _validate_choice(status, LEDGER_STATUSES, 'ledger status')
    return ledger['status']


def _model_safe_ledger(ledger):
    _require_ledger(ledger)
    model_sections = {
        section: [_sanitize_metadata(entry) for entry in ledger.get(section, [])]
        for section in MODEL_LEDGER_SECTIONS
    }
    for source in model_sections['sources']:
        source.pop('citation_ids', None)
        source.pop('artifact_ids', None)
    return {
        'version': ledger['version'],
        'run_id': ledger.get('run_id'),
        'task_type': ledger.get('task_type'),
        'task_profile': ledger.get('task_profile'),
        'orchestration_mode': ledger.get('orchestration_mode'),
        'requested_output': _sanitize_metadata(ledger.get('requested_output')),
        'status': ledger.get('status'),
        **model_sections,
    }


def _truncate_model_strings(value, max_chars):
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value
        return f'{value[:max_chars - 3]}...'
    if isinstance(value, list):
        return [_truncate_model_strings(item, max_chars) for item in value]
    if isinstance(value, Mapping):
        return {
            key: _truncate_model_strings(nested_value, max_chars)
            for key, nested_value in value.items()
        }
    return value


def _serialize_compact_ledger(ledger):
    return json.dumps(
        ledger,
        ensure_ascii=True,
        separators=(',', ':'),
        sort_keys=True,
    )


def _compacted_entry_references_are_retained(section, entry, retained_ids):
    reference_fields = {
        'sources': (('requirement_ids', 'requirements'),),
        'citations': (('source_id', 'sources'),),
        'artifacts': (('source_ids', 'sources'),),
        'facts': (
            ('source_ids', 'sources'),
            ('requirement_ids', 'requirements'),
        ),
        'unsupported_facts': (
            ('source_ids', 'sources'),
            ('requirement_ids', 'requirements'),
        ),
        'results': (
            ('source_ids', 'sources'),
            ('requirement_ids', 'requirements'),
            ('citation_ids', 'citations'),
            ('artifact_ids', 'artifacts'),
        ),
        'conflicts': (
            ('source_ids', 'sources'),
            ('fact_ids', 'facts'),
            ('requirement_ids', 'requirements'),
        ),
        'missing_or_failed': (
            ('source_id', 'sources'),
            ('requirement_ids', 'requirements'),
        ),
    }
    for field_name, target_section in reference_fields.get(section, ()):
        field_value = entry.get(field_name)
        referenced_ids = _normalize_ids(field_value)
        if not set(referenced_ids).issubset(retained_ids[target_section]):
            return False
    return True


def compact_evidence_ledger_for_model(ledger, max_chars=12000):
    """Return bounded valid JSON with raw and sensitive payload fields omitted."""
    try:
        normalized_max_chars = int(max_chars)
    except (TypeError, ValueError) as exc:
        raise ValueError('max_chars must be an integer') from exc
    if normalized_max_chars < 512:
        raise ValueError('max_chars must be at least 512')

    model_ledger = _model_safe_ledger(ledger)
    serialized = _serialize_compact_ledger(model_ledger)
    if len(serialized) <= normalized_max_chars:
        return serialized

    trimmed_ledger = _truncate_model_strings(model_ledger, 320)
    serialized = _serialize_compact_ledger(trimmed_ledger)
    if len(serialized) <= normalized_max_chars:
        return serialized

    bounded_ledger = {
        key: value
        for key, value in trimmed_ledger.items()
        if key not in MODEL_LEDGER_SECTIONS
    }
    bounded_ledger['compaction'] = {
        'truncated': True,
        'omitted': {
            section: len(trimmed_ledger.get(section, []))
            for section in MODEL_LEDGER_SECTIONS
        },
    }
    for section in MODEL_LEDGER_SECTIONS:
        bounded_ledger[section] = []

    if len(_serialize_compact_ledger(bounded_ledger)) > normalized_max_chars:
        bounded_ledger['requested_output'] = {
            'type': str((bounded_ledger.get('requested_output') or {}).get('type') or 'response')[:80]
        }

    retained_ids = {section: set() for section in MODEL_LEDGER_SECTIONS}
    for section in COMPACTION_INSERTION_ORDER:
        for entry in trimmed_ledger.get(section, []):
            if not _compacted_entry_references_are_retained(section, entry, retained_ids):
                continue
            bounded_ledger[section].append(entry)
            bounded_ledger['compaction']['omitted'][section] -= 1
            if len(_serialize_compact_ledger(bounded_ledger)) > normalized_max_chars:
                bounded_ledger[section].pop()
                bounded_ledger['compaction']['omitted'][section] += 1
                break
            retained_ids[section].add(entry.get('id'))

    bounded_ledger['compaction']['omitted'] = {
        section: count
        for section, count in bounded_ledger['compaction']['omitted'].items()
        if count
    }
    serialized = _serialize_compact_ledger(bounded_ledger)
    if len(serialized) > normalized_max_chars:
        return _serialize_compact_ledger({
            'version': EVIDENCE_LEDGER_VERSION,
            'status': ledger.get('status'),
            'compaction': {'truncated': True},
        })
    return serialized


def build_evidence_ledger_guidance_message(ledger, max_chars=12000):
    """Build source-of-truth guidance for any answer or artifact finalizer."""
    compact_ledger = compact_evidence_ledger_for_model(ledger, max_chars=max_chars)
    return '\n'.join([
        EVIDENCE_LEDGER_GUIDANCE_MARKER,
        'Treat this ledger as the authority for grounded facts and normalized outputs.',
        'Use supported facts and results with their source lineage.',
        'Do not present unsupported_facts as factual content or fill missing evidence with assumptions.',
        'Preserve unresolved conflicts and disclose required sources that failed, were denied, or returned no evidence.',
        compact_ledger,
    ])