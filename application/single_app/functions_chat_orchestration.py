# functions_chat_orchestration.py
"""Deterministic Phase 1 planning helpers for coordinated chat turns."""

import re
import uuid
from collections.abc import Mapping


ORCHESTRATION_PLAN_VERSION = 1
ORCHESTRATION_GUIDANCE_MARKER = '[Turn Orchestration Guidance]'

IMAGE_CREATION_PATTERNS = (
    re.compile(
        r'\b(?:create|generate|make|design|draw|render|illustrate|produce|build)\b'
        r'[^.!?\n]{0,100}\b(?:image|picture|illustration|graphic|infographic|sketch|poster|visual|'
        r'logo|diagram|timeline|map|storyboard|concept\s+art)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:image|picture|illustration|graphic|infographic|sketch|poster|visual|logo|diagram|timeline|'
        r'map|storyboard|concept\s+art)\b'
        r'[^.!?\n]{0,100}\b(?:create|generate|make|design|draw|render|produce|build)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\bturn\b[^.!?\n]{0,80}\binto\b[^.!?\n]{0,40}'
        r'\b(?:an?\s+)?(?:image|picture|illustration|graphic|infographic|sketch|poster|visual)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:draw|sketch|illustrate)\s+(?:an?|the|this|that|my|our)\s+'
        r'(?!\b(?:chart|conclusion|attention|comparison|difference|distinction|graph|implications?|'
        r'inferences?|insights?|lessons?|plot|table)\b)',
        re.IGNORECASE,
    ),
    re.compile(r'\bvisuali[sz]e\b[^.!?\n]{0,100}\b(?:as|with|showing|depicting)\b', re.IGNORECASE),
)

GROUNDING_REQUEST_PATTERN = re.compile(
    r'\bground(?:ed|ing)?\s+(?:this|it|the\s+\w+)?\s*(?:in|on)\b',
    re.IGNORECASE,
)

EVIDENCE_SOURCE_PATTERNS = (
    (
        'enterprise_data',
        re.compile(
            r'\b(?:microsoft\s*365|m365|microsoft\s+graph|graph\s+profile|'
            r'(?:use|using|query|from)\s+(?:microsoft\s+)?graph|'
            r'(?:my|our)\s+(?:calendar|email|mail|profile|role|collaborators?|'
            r'work\s+life|work\s+history|values|priorities|responsibilities|organization))\b',
            re.IGNORECASE,
        ),
    ),
    (
        'structured_data',
        re.compile(
            r'\b(?:sql|database|data\s+warehouse|warehouse\s+data|lakehouse|'
            r'databricks|snowflake)\b',
            re.IGNORECASE,
        ),
    ),
    (
        'business_system',
        re.compile(r'\b(?:crm|salesforce|service\s*now|dynamics\s*365|workday)\b', re.IGNORECASE),
    ),
    (
        'public_web',
        re.compile(
            r'\b(?:linkedin|public\s+profile|public\s+web|web\s+search|search\s+the\s+web|'
            r'online\s+sources?|publicly\s+available)\b',
            re.IGNORECASE,
        ),
    ),
    (
        'workspace_search',
        re.compile(
            r'\b(?:(?:my|our|the)\s+workspace|workspace\s+(?:documents?|files?|knowledge)|'
            r'selected\s+(?:documents?|files?)|uploaded\s+(?:documents?|files?))\b',
            re.IGNORECASE,
        ),
    ),
    (
        'conversation_evidence',
        re.compile(
            r'\b(?:earlier\s+(?:messages?|sources?|citations?)|previous\s+(?:messages?|sources?|citations?)|'
            r'conversation\s+history|prior\s+(?:messages?|sources?|citations?)|cited\s+documents?)\b'
            r'|\b(?:information|context|messages?|sources?|citations?)\s+above\b',
            re.IGNORECASE,
        ),
    ),
    (
        'selected_images',
        re.compile(
            r'\b(?:(?:selected|attached|uploaded|reference)\s+(?:image|photo|picture|headshot)|'
            r'(?:this|the)\s+(?:image|photo|picture|headshot)\s+as\s+(?:an?\s+)?reference)\b',
            re.IGNORECASE,
        ),
    ),
)

EVIDENCE_SOURCE_SATISFIERS = {
    'public_web': {
        'web_search',
        'url_access',
        'source_review',
        'deep_research',
    },
    'workspace_search': {
        'selected_documents',
        'workspace_search',
        'user_workspace_context',
        'conversation_documents',
    },
}


def _coerce_bool(value):
    if isinstance(value, str):
        return value.strip().lower() == 'true'
    return bool(value)


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


def _nonnegative_int(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _selected_agent_identifier(selected_agent):
    if isinstance(selected_agent, Mapping):
        return str(
            selected_agent.get('id')
            or selected_agent.get('agent_id')
            or selected_agent.get('name')
            or ''
        ).strip()
    return str(selected_agent or '').strip()


def _selected_action_type(selected_action):
    if isinstance(selected_action, Mapping):
        return str(selected_action.get('type') or selected_action.get('action_type') or '').strip().lower()
    return str(selected_action or '').strip().lower()


def _selected_prompt_identifier(prompt_info):
    if not isinstance(prompt_info, Mapping):
        return ''
    return str(
        prompt_info.get('id')
        or prompt_info.get('prompt_id')
        or prompt_info.get('name')
        or prompt_info.get('title')
        or ''
    ).strip()


def user_requested_image_generation(user_message):
    """Return whether the message asks to create an image-like output."""
    normalized_message = str(user_message or '').strip()
    if not normalized_message:
        return False
    return any(pattern.search(normalized_message) for pattern in IMAGE_CREATION_PATTERNS)


def detect_requested_evidence_sources(user_message):
    """Return source-neutral evidence hints explicitly present in the message."""
    normalized_message = str(user_message or '').strip()
    requested_sources = []
    for source_type, pattern in EVIDENCE_SOURCE_PATTERNS:
        if pattern.search(normalized_message):
            requested_sources.append(source_type)
    return requested_sources


def _build_source(source_type, origin, metadata=None):
    return {
        'id': source_type,
        'origin': origin,
        'required': True,
        'status': 'planned',
        'metadata': dict(metadata or {}),
    }


def _build_collection_step(source):
    if source['id'] == 'selected_action':
        step_type = 'execute'
    elif source['id'] == 'evidence_discovery':
        step_type = 'plan'
    else:
        step_type = 'collect'
    return {
        'id': f"{step_type}_{source['id']}",
        'type': step_type,
        'capability': source['id'],
        'origin': source['origin'],
        'required': source['required'],
        'status': 'pending',
        'depends_on': [],
    }


def _source_requirement_is_already_covered(source_type, source_types):
    if source_type in source_types:
        return True
    return bool(EVIDENCE_SOURCE_SATISFIERS.get(source_type, set()).intersection(source_types))


def build_turn_orchestration_plan(
    user_message,
    *,
    run_id=None,
    conversation_id=None,
    selected_agent=None,
    selected_action=None,
    selected_document_ids=None,
    conversation_document_ids=None,
    assigned_knowledge_enabled=False,
    document_scope=None,
    active_group_ids=None,
    active_public_workspace_ids=None,
    tags=None,
    hybrid_search_enabled=False,
    web_search_enabled=False,
    url_access_enabled=False,
    source_review_enabled=False,
    deep_research_enabled=False,
    user_workspace_context_enabled=False,
    selected_image_reference_count=0,
    prior_citation_count=0,
    image_generation_available=False,
    model_deployment=None,
    model_id=None,
    model_endpoint_id=None,
    model_provider=None,
    reasoning_effort=None,
    prompt_info=None,
):
    """Build a JSON-serializable, immutable-by-convention plan snapshot for one turn."""
    selected_document_ids = _normalize_ids(selected_document_ids)
    conversation_document_ids = _normalize_ids(conversation_document_ids)
    active_group_ids = _normalize_ids(active_group_ids)
    active_public_workspace_ids = _normalize_ids(active_public_workspace_ids)
    selected_tags = _normalize_ids(tags)
    selected_agent_id = _selected_agent_identifier(selected_agent)
    selected_action_type = _selected_action_type(selected_action)
    selected_prompt_id = _selected_prompt_identifier(prompt_info)
    selected_image_reference_count = _nonnegative_int(selected_image_reference_count)
    selected_sources = []

    if selected_agent_id:
        selected_sources.append(_build_source('selected_agent', 'selection', {'agent_id': selected_agent_id}))
    if selected_action_type and selected_action_type != 'none':
        selected_sources.append(
            _build_source('selected_action', 'selection', {'action_type': selected_action_type})
        )
    if selected_document_ids:
        selected_sources.append(
            _build_source('selected_documents', 'selection', {'count': len(selected_document_ids)})
        )
    if _coerce_bool(hybrid_search_enabled):
        selected_sources.append(_build_source('workspace_search', 'selection'))
    if _coerce_bool(web_search_enabled):
        selected_sources.append(_build_source('web_search', 'selection'))
    if _coerce_bool(url_access_enabled):
        selected_sources.append(_build_source('url_access', 'selection'))
    if _coerce_bool(source_review_enabled) and not _coerce_bool(deep_research_enabled):
        selected_sources.append(_build_source('source_review', 'selection'))
    if _coerce_bool(deep_research_enabled):
        selected_sources.append(_build_source('deep_research', 'selection'))
    if _coerce_bool(user_workspace_context_enabled):
        selected_sources.append(_build_source('user_workspace_context', 'selection'))
    if selected_image_reference_count:
        selected_sources.append(
            _build_source(
                'selected_images',
                'selection',
                {'count': selected_image_reference_count},
            )
        )

    requested_source_types = detect_requested_evidence_sources(user_message)
    grounding_language_detected = bool(GROUNDING_REQUEST_PATTERN.search(str(user_message or '')))
    selected_source_types = [source['id'] for source in selected_sources]
    requested_sources = list(selected_sources)
    if conversation_document_ids:
        requested_sources.append(
            _build_source(
                'conversation_documents',
                'conversation',
                {'count': len(conversation_document_ids)},
            )
        )
    if _coerce_bool(assigned_knowledge_enabled):
        requested_sources.append(_build_source('assigned_knowledge', 'agent_configuration'))

    existing_source_types = [source['id'] for source in requested_sources]
    if grounding_language_detected and not requested_source_types and not requested_sources:
        requested_source_types.append('unspecified_grounding')
        requested_sources.append(
            _build_source(
                'evidence_discovery',
                'request',
                {'requirement': 'unspecified_grounding'},
            )
        )
        existing_source_types.append('evidence_discovery')
    for source_type in requested_source_types:
        if source_type == 'unspecified_grounding':
            continue
        if not _source_requirement_is_already_covered(source_type, existing_source_types):
            metadata = {}
            if source_type == 'conversation_evidence':
                metadata['available_citation_count'] = _nonnegative_int(prior_citation_count)
            requested_sources.append(_build_source(source_type, 'request', metadata))
            existing_source_types.append(source_type)

    image_generation_requested = user_requested_image_generation(user_message)
    requires_evidence_before_finalization = bool(requested_sources)
    grounded_image_generation_requested = bool(
        image_generation_requested
        and (requires_evidence_before_finalization or grounding_language_detected)
    )

    reason_codes = []
    if selected_sources:
        reason_codes.append('selected_capability')
    if requested_source_types or grounding_language_detected:
        reason_codes.append('evidence_requested')
    if grounded_image_generation_requested:
        reason_codes.append('grounded_image_generation')

    collection_steps = [_build_collection_step(source) for source in requested_sources]
    collection_step_ids = {step['capability']: step['id'] for step in collection_steps}
    selected_action_step = next(
        (step for step in collection_steps if step['capability'] == 'selected_action'),
        None,
    )
    if selected_action_step:
        selected_action_step['depends_on'] = [
            collection_step_ids[source_type]
            for source_type in (
                'selected_agent',
                'selected_documents',
                'conversation_documents',
                'assigned_knowledge',
            )
            if source_type in collection_step_ids
        ]
    finalizer_capability = (
        'image_proposal'
        if image_generation_requested and _coerce_bool(image_generation_available)
        else 'response'
    )
    finalizer_step = {
        'id': f'finalize_{finalizer_capability}',
        'type': 'finalize',
        'capability': finalizer_capability,
        'origin': 'orchestrator',
        'required': True,
        'status': 'pending',
        'depends_on': [step['id'] for step in collection_steps],
    }

    warnings = []
    if image_generation_requested and not _coerce_bool(image_generation_available):
        warnings.append('image_generation_unavailable')

    selection_snapshot = {
        'conversation_id': str(conversation_id or '').strip() or None,
        'agent_id': selected_agent_id or None,
        'action_type': selected_action_type if selected_action_type and selected_action_type != 'none' else None,
        'selected_document_ids': selected_document_ids,
        'document_scope': str(document_scope or '').strip() or None,
        'active_group_ids': active_group_ids,
        'active_public_workspace_ids': active_public_workspace_ids,
        'tags': selected_tags,
        'conversation_document_ids': conversation_document_ids,
        'toggles': {
            'workspace_search': _coerce_bool(hybrid_search_enabled),
            'web_search': _coerce_bool(web_search_enabled),
            'url_access': _coerce_bool(url_access_enabled),
            'source_review': _coerce_bool(source_review_enabled),
            'deep_research': _coerce_bool(deep_research_enabled),
            'user_workspace_context': _coerce_bool(user_workspace_context_enabled),
        },
        'selected_image_reference_count': selected_image_reference_count,
        'model': {
            'deployment': str(model_deployment or '').strip() or None,
            'model_id': str(model_id or '').strip() or None,
            'endpoint_id': str(model_endpoint_id or '').strip() or None,
            'provider': str(model_provider or '').strip() or None,
            'reasoning_effort': str(reasoning_effort or '').strip() or None,
        },
        'prompt_id': selected_prompt_id or None,
    }

    return {
        'version': ORCHESTRATION_PLAN_VERSION,
        'run_id': str(run_id or uuid.uuid4()),
        'selection_snapshot': selection_snapshot,
        'mode': 'coordinated' if collection_steps else 'direct',
        'task_type': 'image_generation' if image_generation_requested else 'answer',
        'task_profile': (
            'grounded_image_generation'
            if grounded_image_generation_requested
            else 'image_generation'
            if image_generation_requested
            else 'grounded_answer'
            if collection_steps
            else 'direct_answer'
        ),
        'image_generation_requested': image_generation_requested,
        'grounded_image_generation_requested': grounded_image_generation_requested,
        'requires_evidence_before_finalization': requires_evidence_before_finalization,
        'reason_codes': reason_codes,
        'selected_capabilities': selected_source_types,
        'evidence_requirements': requested_source_types,
        'requested_evidence_sources': [source['id'] for source in requested_sources],
        'sources': requested_sources,
        'steps': [*collection_steps, finalizer_step],
        'finalizer': finalizer_capability,
        'policy': {
            'selected_capabilities_are_required': True,
            'allow_governed_read_only_discovery': True,
            'allow_bounded_replanning': True,
            'central_finalizer_required': True,
            'approval_required_for': [
                'side_effect',
                'sensitive_access',
                'budget_overflow',
            ],
        },
        'warnings': warnings,
    }


def build_turn_orchestration_guidance_message(plan):
    """Build finalizer guidance for a coordinated plan."""
    if not isinstance(plan, Mapping) or plan.get('mode') != 'coordinated':
        return ''

    source_labels = ', '.join(str(source) for source in plan.get('requested_evidence_sources') or [])
    requirement_labels = ', '.join(str(requirement) for requirement in plan.get('evidence_requirements') or [])
    guidance = [
        ORCHESTRATION_GUIDANCE_MARKER,
        f'Required source attempts for this turn: {source_labels or "none"}.',
        f'Evidence requirements inferred from the request: {requirement_labels or "none beyond selected sources"}.',
        'Use the results from every attempted source when producing the final response.',
        'Do not add a source-status note or list sources merely to report successful attempts.',
        'Only mention source execution status when a required source was skipped, unavailable, unauthorized, failed, returned no evidence, or produced partial results.',
        'Use only supported facts, preserve material source conflicts, and identify partial results instead of filling evidence gaps with assumptions.',
    ]

    if plan.get('grounded_image_generation_requested'):
        guidance.extend([
            'This is a grounded image-generation task.',
            'Do not emit a simpleimage proposal until the required evidence sources have been attempted.',
            'Do not claim that requested evidence is unavailable until the relevant selected or available source has been attempted.',
        ])

    return '\n'.join(guidance)