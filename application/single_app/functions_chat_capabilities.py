# functions_chat_capabilities.py
"""Governed built-in and agent capability discovery for chat orchestration."""

import copy
import hashlib
import hmac
import json
import re
from collections.abc import Mapping

from functions_chat_orchestration import user_requested_image_generation


CAPABILITY_INVENTORY_VERSION = 1
CAPABILITY_RECOMMENDATION_VERSION = 1
AGENT_CAPABILITY_INVENTORY_VERSION = 1
CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID = 'continue_without_capabilities'
PLANNER_PLAN_MAX_BUNDLE_DEPTH = 4
PLANNER_PLAN_MAX_EFFECTIVE_CAPABILITIES = 8
PLANNER_PLAN_MAX_ACTIONABLE_OPTIONS = 3
PLANNER_DOCUMENT_ACTION_CAPABILITY_IDS = frozenset({'analyze', 'compare'})
PLANNER_IMAGE_CAPABILITY_ID = 'image'
PLANNER_RETRIEVAL_CAPABILITY_IDS = frozenset({
    'workspace_search',
    'web_search',
    'url_access',
    'deep_research',
})

AGENT_DISCOVERY_RISK_CLASSES = {'internal_read', 'external_read'}
AGENT_DISCOVERY_DATA_SENSITIVITY_CLASSES = {'public', 'internal'}
AGENT_DISCOVERY_COST_CLASSES = {'low', 'standard'}
AGENT_DISCOVERY_LATENCY_CLASSES = {'seconds', 'minutes'}
AGENT_DISCOVERY_SCOPE_CLASSES = {'personal', 'global', 'group'}

CAPABILITY_STATES = {
    'selected',
    'unselected',
    'unavailable',
    'unauthorized',
    'policy_blocked',
}
GOVERNANCE_MODES = {'manual_only', 'recommend', 'auto_read_only', 'blocked'}
DEFAULT_CAPABILITY_GOVERNANCE_MODES = {
    'workspace_search': 'recommend',
    'analyze': 'recommend',
    'compare': 'recommend',
    'image': 'recommend',
    'web_search': 'recommend',
    'url_access': 'recommend',
    'deep_research': 'recommend',
}

CAPABILITY_DEFINITIONS = {
    'workspace_search': {
        'label': 'Workspace Search',
        'category': 'retrieval',
        'risk_class': 'internal_read',
        'cost_class': 'low',
        'latency_class': 'seconds',
        'evidence_types': ['workspace_documents', 'authorized_knowledge'],
        'input_requirements': ['authorized_workspace_scope'],
        'external_data': False,
        'read_only': True,
        'default_requires_user_choice': True,
    },
    'analyze': {
        'label': 'Analyze',
        'category': 'analysis',
        'risk_class': 'internal_read',
        'cost_class': 'standard',
        'latency_class': 'seconds',
        'evidence_types': ['document_findings', 'calculated_results'],
        'input_requirements': ['authorized_document_target'],
        'external_data': False,
        'read_only': True,
        'default_requires_user_choice': True,
    },
    'compare': {
        'label': 'Compare',
        'category': 'analysis',
        'risk_class': 'internal_read',
        'cost_class': 'standard',
        'latency_class': 'seconds',
        'evidence_types': ['document_differences', 'document_consistency'],
        'input_requirements': ['two_authorized_document_targets'],
        'external_data': False,
        'read_only': True,
        'default_requires_user_choice': True,
    },
    'image': {
        'label': 'Image',
        'category': 'generation',
        'risk_class': 'generated_content',
        'cost_class': 'standard',
        'latency_class': 'seconds',
        'evidence_types': ['visual_output'],
        'input_requirements': [],
        'external_data': False,
        'read_only': False,
        'default_requires_user_choice': True,
    },
    'web_search': {
        'label': 'Web Search',
        'category': 'retrieval',
        'risk_class': 'external_read',
        'cost_class': 'standard',
        'latency_class': 'seconds',
        'evidence_types': ['public_web', 'current_information'],
        'input_requirements': [],
        'external_data': True,
        'read_only': True,
        'default_requires_user_choice': True,
    },
    'url_access': {
        'label': 'URL Access',
        'category': 'retrieval',
        'risk_class': 'external_read',
        'cost_class': 'standard',
        'latency_class': 'seconds',
        'evidence_types': ['supplied_url_content'],
        'input_requirements': ['user_supplied_url'],
        'external_data': True,
        'read_only': True,
        'default_requires_user_choice': True,
    },
    'deep_research': {
        'label': 'Deep Research',
        'category': 'retrieval',
        'risk_class': 'external_read',
        'cost_class': 'extended',
        'latency_class': 'minutes',
        'evidence_types': ['public_web', 'current_information', 'authoritative_sources'],
        'input_requirements': [],
        'external_data': True,
        'read_only': True,
        'default_requires_user_choice': True,
        'bundle': ['deep_research', 'web_search'],
    },
}

URL_PATTERN = re.compile(r'https?://[^\s<>\"]+', re.IGNORECASE)
CURRENT_INFORMATION_PATTERN = re.compile(
    r'\b(?:current|currently|latest|recent|recently|today|tonight|tomorrow|this\s+(?:week|month|year)|'
    r'up[- ]to[- ]date|as\s+of\s+20\d{2}|20(?:2[6-9]|[3-9]\d))\b',
    re.IGNORECASE,
)
LOCAL_AUTHORITATIVE_PATTERN = re.compile(
    r'\b(?:law|laws|legal|regulation|regulations|regulatory|ordinance|ordinances|zoning|permit|permits|'
    r'policy|policies|schedule|schedules|official\s+records?|county|municipal|property|parcel|'
    r'city\s+rules?|state\s+rules?)\b',
    re.IGNORECASE,
)
INHERENTLY_CURRENT_AUTHORITY_PATTERN = re.compile(
    r'\b(?:regulation|regulations|regulatory|ordinance|ordinances|zoning|permit|permits|'
    r'official\s+records?|county|municipal|city\s+rules?|state\s+rules?|property\s+rules?|parcel)\b',
    re.IGNORECASE,
)
WORKSPACE_EVIDENCE_PATTERN = re.compile(
    r'\b(?:(?:my|our)\s+(?:workspace|documents?|files?|uploads?)|workspace\s+(?:documents?|files?|knowledge)|'
    r'selected\s+(?:documents?|files?)|uploaded\s+(?:documents?|files?))\b',
    re.IGNORECASE,
)
DOCUMENT_ANALYSIS_PATTERN = re.compile(
    r'\b(?:analy[sz]e|extract|calculate|compute|summari[sz]e|findings?|themes?|trends?|structured\s+findings?)\b',
    re.IGNORECASE,
)
DOCUMENT_COMPARISON_PATTERN = re.compile(
    r'\b(?:compare|comparison|differences?|tradeoffs?|trade-offs?|consisten(?:cy|t)|changes?\s+between|'
    r'versus|vs\.?|across\s+(?:the\s+)?documents?)\b',
    re.IGNORECASE,
)
MULTI_SOURCE_RESEARCH_PATTERN = re.compile(
    r'\b(?:deep\s+research|comprehensive\s+research|investigate|multiple\s+sources?|multi-source|'
    r'authoritative\s+sources?|source-intensive|due\s+diligence)\b',
    re.IGNORECASE,
)
ORGANIZATIONAL_KNOWLEDGE_PATTERN = re.compile(
    r'\b(?:our|my|company|corporate|organization|organizational|internal|employee|employees|'
    r'workplace|benefits?|human\s+resources|hr\b|handbook|intranet)\b',
    re.IGNORECASE,
)
BUSINESS_SYSTEM_EVIDENCE_PATTERN = re.compile(
    r'\b(?:business\s+system|crm|erp|hris|service\s*tickets?|incidents?|customer\s+records?|'
    r'account\s+records?|inventory\s+system|case\s+records?|system\s+records?)\b',
    re.IGNORECASE,
)

REQUIREMENT_CAPABILITY_PREFERENCES = {
    'current_public_information': ['web_search', 'deep_research'],
    'current_authoritative_sources': ['deep_research', 'web_search'],
    'supplied_url_review': ['url_access'],
    'workspace_evidence': ['workspace_search'],
    'document_analysis': ['analyze'],
    'multi_document_comparison': ['compare'],
    'visual_output': ['image'],
    'multi_source_public_research': ['deep_research', 'web_search'],
}

_PLANNER_PLAN_LATENCY_ORDER = {
    'immediate': 0,
    'seconds': 1,
    'minutes': 2,
}
_PLANNER_PLAN_COST_ORDER = {
    'none': 0,
    'low': 1,
    'standard': 2,
    'extended': 3,
}


def _coerce_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() == 'true'
    return bool(value)


def _bounded_reason(value):
    normalized = re.sub(r'[^a-z0-9_]+', '_', str(value or '').strip().lower()).strip('_')
    return normalized[:80] or None


def _normalize_agent_descriptor_identifiers(values, *, max_items=16):
    if not isinstance(values, list):
        return []
    normalized = []
    for value in values:
        identifier = re.sub(
            r'[^a-z0-9_:-]+',
            '_',
            str(value or '').strip().lower(),
        ).strip('_')[:64]
        if identifier and identifier not in normalized:
            normalized.append(identifier)
        if len(normalized) >= max_items:
            break
    return normalized


def _resolve_agent_scope_class(agent, catalog_key):
    scope_class = str(agent.get('scope_type') or '').strip().lower()
    if scope_class == 'enterprise':
        scope_class = 'global'
    if scope_class not in AGENT_DISCOVERY_SCOPE_CLASSES:
        scope_class = str(catalog_key or '').partition(':')[0].strip().lower()
    return scope_class if scope_class in AGENT_DISCOVERY_SCOPE_CLASSES else None


def _build_agent_discovery_reference(
    catalog_key,
    scope_class,
    reference_secret,
    identity_epoch=None,
):
    secret = str(reference_secret or '').encode('utf-8')
    if not secret:
        return None
    digest = hmac.new(
        secret,
        f"{catalog_key or ''}\n{identity_epoch or ''}".encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()[:32]
    return f'agent:{scope_class}:{digest}'


def build_governed_agent_capability_inventory(agents, *, reference_secret):
    """Build safe descriptors from an already authorized canonical agent catalog."""
    entries = []
    seen_references = set()
    for agent in agents or []:
        if not isinstance(agent, Mapping):
            continue
        if not _coerce_bool(agent.get('discoverable_by_orchestrator'), default=False):
            continue
        descriptor = agent.get('orchestrator_descriptor')
        if not isinstance(descriptor, Mapping):
            continue
        if not _coerce_bool(descriptor.get('read_only'), default=False):
            continue

        risk_class = str(descriptor.get('risk_class') or '').strip().lower()
        data_sensitivity = str(descriptor.get('data_sensitivity') or '').strip().lower()
        cost_class = str(descriptor.get('cost_class') or '').strip().lower()
        latency_class = str(descriptor.get('latency_class') or '').strip().lower()
        if (
            risk_class not in AGENT_DISCOVERY_RISK_CLASSES
            or data_sensitivity not in AGENT_DISCOVERY_DATA_SENSITIVITY_CLASSES
            or cost_class not in AGENT_DISCOVERY_COST_CLASSES
            or latency_class not in AGENT_DISCOVERY_LATENCY_CLASSES
        ):
            continue

        capability_tags = _normalize_agent_descriptor_identifiers(
            descriptor.get('capability_tags')
        )
        evidence_types = _normalize_agent_descriptor_identifiers(
            descriptor.get('evidence_types')
        )
        if not capability_tags or not evidence_types:
            continue

        catalog_key = str(agent.get('catalog_key') or '').strip()
        identity_epoch = str(agent.get('created_at') or '').strip()
        scope_class = _resolve_agent_scope_class(agent, catalog_key)
        option_reference = _build_agent_discovery_reference(
            catalog_key,
            scope_class,
            reference_secret,
            identity_epoch=identity_epoch,
        )
        if not catalog_key or not identity_epoch or not scope_class or not option_reference:
            continue
        if option_reference in seen_references:
            continue
        seen_references.add(option_reference)

        label = ' '.join(
            str(
                agent.get('display_name')
                or agent.get('displayName')
                or agent.get('name')
                or 'Specialized agent'
            ).split()
        )[:120]
        entries.append({
            'id': option_reference,
            'kind': 'agent',
            'label': label,
            'category': 'specialized_agent',
            'state': 'unselected',
            'scope': 'current_user',
            'scope_class': scope_class,
            'discoverable': True,
            'auto_use_allowed': False,
            'requires_user_choice': True,
            'read_only': True,
            'external_data': _coerce_bool(descriptor.get('external_data'), default=False),
            'risk_class': risk_class,
            'data_sensitivity': data_sensitivity,
            'cost_class': cost_class,
            'latency_class': latency_class,
            'capability_tags': capability_tags,
            'evidence_types': evidence_types,
        })

    return {
        'version': AGENT_CAPABILITY_INVENTORY_VERSION,
        'agents': entries,
    }


def resolve_governed_agent_capability_reference(agents, option_id, *, reference_secret):
    """Resolve one opaque option through the current governed canonical catalog."""
    normalized_option_id = str(option_id or '').strip()
    if not normalized_option_id.startswith('agent:'):
        return None
    for agent in agents or []:
        if not isinstance(agent, Mapping):
            continue
        inventory = build_governed_agent_capability_inventory(
            [agent],
            reference_secret=reference_secret,
        )
        descriptor = next(iter(inventory.get('agents') or []), None)
        if descriptor and descriptor.get('id') == normalized_option_id:
            return dict(agent)
    return None


def classify_agent_capability_requirements(user_message):
    """Classify only explicit organizational or business-system evidence needs."""
    message = str(user_message or '').strip()
    requirements = []
    if ORGANIZATIONAL_KNOWLEDGE_PATTERN.search(message):
        requirements.append({
            'id': 'specialized_organizational_knowledge',
            'reason_code': 'specialized_organizational_knowledge',
        })
    if BUSINESS_SYSTEM_EVIDENCE_PATTERN.search(message):
        requirements.append({
            'id': 'business_system_evidence',
            'reason_code': 'business_system_evidence',
        })
    return requirements


def _agent_descriptor_match_score(agent, user_message):
    normalized_message = re.sub(
        r'[^a-z0-9]+',
        ' ',
        str(user_message or '').strip().lower(),
    ).strip()
    message_terms = set(normalized_message.split())
    score = 0
    for identifier in (
        list(agent.get('capability_tags') or [])
        + list(agent.get('evidence_types') or [])
    ):
        normalized_identifier = re.sub(
            r'[^a-z0-9]+',
            ' ',
            str(identifier or '').strip().lower(),
        ).strip()
        if not normalized_identifier:
            continue
        if re.search(rf'\b{re.escape(normalized_identifier)}\b', normalized_message):
            score += 4
            continue
        score += sum(
            1
            for term in normalized_identifier.split()
            if len(term) >= 4 and term in message_terms
        )
    return score


def build_agent_capability_recommendation(
    inventory,
    user_message,
    *,
    selected_agent_present=False,
    selected_capability_ids=None,
):
    """Build at most one explicit-choice agent option from safe descriptors."""
    if selected_agent_present or not isinstance(inventory, Mapping):
        return None
    requirements = classify_agent_capability_requirements(user_message)
    if not requirements:
        return None
    selected_capability_ids = {
        str(capability_id or '').strip().lower()
        for capability_id in (selected_capability_ids or [])
        if str(capability_id or '').strip()
    }
    requirement_ids = {requirement['id'] for requirement in requirements}
    if (
        'specialized_organizational_knowledge' in requirement_ids
        and selected_capability_ids.intersection({'workspace_search', 'analyze', 'compare'})
    ):
        requirements = [
            requirement
            for requirement in requirements
            if requirement['id'] != 'specialized_organizational_knowledge'
        ]
    if not requirements:
        return None

    ranked_candidates = []
    for agent in inventory.get('agents') or []:
        if not isinstance(agent, Mapping):
            continue
        if not (
            agent.get('kind') == 'agent'
            and agent.get('state') == 'unselected'
            and agent.get('discoverable') is True
            and agent.get('requires_user_choice') is True
            and agent.get('read_only') is True
        ):
            continue
        score = _agent_descriptor_match_score(agent, user_message)
        if score > 0:
            ranked_candidates.append((score, str(agent.get('id') or ''), agent))
    if not ranked_candidates:
        return None

    _, _, agent = sorted(
        ranked_candidates,
        key=lambda item: (-item[0], item[1]),
    )[0]
    option = {
        'id': agent['id'],
        'kind': 'agent',
        'agent_ref': agent['id'],
        'capability_ids': [],
        'effective_capability_ids': [],
        'label': agent['label'],
        'category': agent['category'],
        'scope_class': agent['scope_class'],
        'latency_class': agent['latency_class'],
        'cost_class': agent['cost_class'],
        'external_data': agent['external_data'],
        'requires_user_choice': True,
        'read_only': True,
        'risk_class': agent['risk_class'],
        'data_sensitivity': agent['data_sensitivity'],
        'capability_tags': list(agent['capability_tags']),
        'evidence_types': list(agent['evidence_types']),
    }
    return {
        'version': CAPABILITY_RECOMMENDATION_VERSION,
        'status': 'pending',
        'requirement_ids': [requirement['id'] for requirement in requirements],
        'reason_codes': [requirement['reason_code'] for requirement in requirements],
        'recommended_option_id': agent['id'],
        'options': [
            option,
            {
                'id': CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID,
                'kind': 'continue',
                'capability_ids': [],
                'effective_capability_ids': [],
                'label': 'Continue without additional capabilities',
                'latency_class': 'immediate',
                'cost_class': 'none',
                'external_data': False,
                'requires_user_choice': True,
            },
        ],
        'required_inputs': [],
    }


def merge_capability_recommendations(primary, secondary):
    """Merge built-in and agent options into one bounded Phase 8A proposal."""
    recommendations = [
        recommendation
        for recommendation in (primary, secondary)
        if isinstance(recommendation, Mapping)
    ]
    if not recommendations:
        return None
    if len(recommendations) == 1:
        return copy.deepcopy(dict(recommendations[0]))

    options = []
    continue_option = None
    seen_option_ids = set()
    for recommendation in recommendations:
        for option in recommendation.get('options') or []:
            if not isinstance(option, Mapping):
                continue
            option_id = str(option.get('id') or '').strip()
            if not option_id:
                continue
            if option_id == CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID:
                continue_option = continue_option or copy.deepcopy(dict(option))
                continue
            if option_id in seen_option_ids or len(options) >= 11:
                continue
            seen_option_ids.add(option_id)
            options.append(copy.deepcopy(dict(option)))
    if continue_option:
        options.append(continue_option)

    def merge_identifiers(field_name, max_items=16):
        merged = []
        for recommendation in recommendations:
            for value in recommendation.get(field_name) or []:
                normalized = str(value or '').strip()
                if normalized and normalized not in merged:
                    merged.append(normalized)
                if len(merged) >= max_items:
                    return merged
        return merged

    secondary_recommended_id = str(
        recommendations[-1].get('recommended_option_id') or ''
    ).strip()
    recommended_option_id = (
        secondary_recommended_id
        if secondary_recommended_id in seen_option_ids
        else str(recommendations[0].get('recommended_option_id') or '').strip()
    )
    return {
        'version': CAPABILITY_RECOMMENDATION_VERSION,
        'status': 'pending',
        'requirement_ids': merge_identifiers('requirement_ids'),
        'reason_codes': merge_identifiers('reason_codes'),
        'recommended_option_id': recommended_option_id,
        'options': options,
        'required_inputs': merge_identifiers('required_inputs'),
    }


def filter_unsupported_document_action_recommendation(
    recommendation,
    baseline_capability_ids,
    *,
    selected_agent_present=False,
):
    """Remove choices that the document-action compatibility executor cannot fulfill."""
    if not isinstance(recommendation, Mapping):
        return recommendation
    baseline_ids = {
        str(capability_id or '').strip().lower()
        for capability_id in baseline_capability_ids or []
        if str(capability_id or '').strip()
    }
    if selected_agent_present:
        baseline_ids.add('selected_agent')
    filtered = copy.deepcopy(dict(recommendation))
    filtered_options = []
    for option in filtered.get('options') or []:
        if not isinstance(option, Mapping):
            continue
        option_id = str(option.get('id') or '').strip()
        if option_id == CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID:
            filtered_options.append(copy.deepcopy(dict(option)))
            continue
        execution_ids = baseline_ids | {
            str(capability_id or '').strip().lower()
            for capability_id in (
                option.get('effective_capability_ids')
                or option.get('capability_ids')
                or []
            )
            if str(capability_id or '').strip()
        }
        if str(option.get('agent_ref') or '').strip():
            execution_ids.add('selected_agent')
        if (
            execution_ids.intersection(PLANNER_DOCUMENT_ACTION_CAPABILITY_IDS)
            and execution_ids.intersection(PLANNER_RETRIEVAL_CAPABILITY_IDS)
        ) or (
            PLANNER_IMAGE_CAPABILITY_ID in execution_ids
            and len(execution_ids) > 1
        ):
            continue
        filtered_options.append(copy.deepcopy(dict(option)))
    recommended_option_id = str(filtered.get('recommended_option_id') or '').strip()
    if not any(
        str(option.get('id') or '').strip() == recommended_option_id
        for option in filtered_options
    ):
        return None
    filtered['options'] = filtered_options
    return filtered


def _normalize_governance_mode(value):
    normalized = str(value or 'recommend').strip().lower()
    return normalized if normalized in GOVERNANCE_MODES else 'blocked'


def normalize_capability_governance_modes(settings_or_modes=None):
    """Normalize per-capability policy while failing closed on invalid values."""
    raw_modes = settings_or_modes
    if isinstance(settings_or_modes, Mapping) and 'chat_capability_governance' in settings_or_modes:
        raw_modes = settings_or_modes.get('chat_capability_governance')
    raw_modes = raw_modes if isinstance(raw_modes, Mapping) else {}
    normalized = {}
    for capability_id, default_mode in DEFAULT_CAPABILITY_GOVERNANCE_MODES.items():
        raw_value = raw_modes.get(capability_id, default_mode)
        if isinstance(raw_value, Mapping):
            raw_value = raw_value.get('mode')
        normalized[capability_id] = _normalize_governance_mode(raw_value)
    return normalized


def build_governed_capability_inventory(*, selected_capability_ids=None, resolved_capabilities=None):
    """Build a fail-closed inventory from server-resolved capability decisions."""
    selected_ids = {
        str(capability_id or '').strip().lower()
        for capability_id in (selected_capability_ids or [])
        if str(capability_id or '').strip().lower() in CAPABILITY_DEFINITIONS
    }
    resolved_capabilities = resolved_capabilities if isinstance(resolved_capabilities, Mapping) else {}
    entries = []

    for capability_id, definition in CAPABILITY_DEFINITIONS.items():
        resolved = resolved_capabilities.get(capability_id)
        resolved = resolved if isinstance(resolved, Mapping) else {}
        enabled = _coerce_bool(resolved.get('enabled'), default=False)
        available = enabled and _coerce_bool(resolved.get('available'), default=False)
        authorized = _coerce_bool(resolved.get('authorized'), default=False)
        governance_mode = _normalize_governance_mode(resolved.get('governance_mode'))
        policy_allowed = governance_mode != 'blocked' and _coerce_bool(
            resolved.get('policy_allowed'),
            default=True,
        )
        input_ready = _coerce_bool(resolved.get('input_ready'), default=True)
        selected = capability_id in selected_ids

        if not available:
            state = 'unavailable'
        elif not authorized:
            state = 'unauthorized'
        elif not policy_allowed:
            state = 'policy_blocked'
        elif selected:
            state = 'selected'
        else:
            state = 'unselected'

        discoverable = bool(
            state == 'unselected'
            and input_ready
            and governance_mode in {'recommend', 'auto_read_only'}
            and _coerce_bool(resolved.get('discoverable'), default=True)
        )
        auto_use_allowed = bool(
            discoverable
            and governance_mode == 'auto_read_only'
            and capability_id == 'workspace_search'
            and definition['read_only']
            and not definition['external_data']
        )
        requires_user_choice = bool(
            discoverable
            and not auto_use_allowed
            and definition['default_requires_user_choice']
        )

        entry = {
            'id': capability_id,
            'label': definition['label'],
            'category': definition['category'],
            'state': state,
            'selected': selected,
            'available': available,
            'authorized': authorized,
            'discoverable': discoverable,
            'auto_use_allowed': auto_use_allowed,
            'requires_user_choice': requires_user_choice,
            'read_only': definition['read_only'],
            'external_data': definition['external_data'],
            'risk_class': definition['risk_class'],
            'cost_class': definition['cost_class'],
            'latency_class': definition['latency_class'],
            'evidence_types': list(definition['evidence_types']),
            'input_requirements': list(definition['input_requirements']),
            'input_ready': input_ready,
            'scope': 'current_user',
            'governance_mode': governance_mode,
        }
        if definition.get('bundle'):
            entry['bundle'] = list(definition['bundle'])
        if state in {'unavailable', 'unauthorized', 'policy_blocked'}:
            reason = _bounded_reason(resolved.get('reason')) or state
            entry['diagnostic_reason'] = reason
        entries.append(entry)

    return {
        'version': CAPABILITY_INVENTORY_VERSION,
        'capabilities': entries,
    }


def classify_capability_requirements(user_message, *, authorized_document_count=0):
    """Classify common capability requirements without a planning-model call."""
    message = str(user_message or '').strip()
    if not message:
        return []

    try:
        document_count = max(0, int(authorized_document_count or 0))
    except (TypeError, ValueError):
        document_count = 0

    requirements = []

    def add_requirement(requirement_id, reason_code, *, required_inputs=None):
        if any(item['id'] == requirement_id for item in requirements):
            return
        requirements.append({
            'id': requirement_id,
            'reason_code': reason_code,
            'required_inputs': list(required_inputs or []),
        })

    has_current_signal = bool(CURRENT_INFORMATION_PATTERN.search(message))
    has_authoritative_signal = bool(LOCAL_AUTHORITATIVE_PATTERN.search(message))
    if has_authoritative_signal and (
        has_current_signal or INHERENTLY_CURRENT_AUTHORITY_PATTERN.search(message)
    ):
        add_requirement('current_authoritative_sources', 'current_authoritative_sources')
    elif has_current_signal:
        add_requirement('current_public_information', 'current_public_information')

    if URL_PATTERN.search(message):
        add_requirement('supplied_url_review', 'user_supplied_url_requires_review')
    if WORKSPACE_EVIDENCE_PATTERN.search(message):
        add_requirement('workspace_evidence', 'workspace_evidence_requested')
    if DOCUMENT_ANALYSIS_PATTERN.search(message) and document_count >= 1:
        add_requirement('document_analysis', 'document_analysis_requested')
    if DOCUMENT_COMPARISON_PATTERN.search(message):
        if document_count >= 2:
            add_requirement('multi_document_comparison', 'multi_document_comparison')
        else:
            add_requirement(
                'multi_document_comparison',
                'comparison_targets_required',
                required_inputs=['two_authorized_document_targets'],
            )
    if user_requested_image_generation(message):
        add_requirement('visual_output', 'visual_output_materially_helpful')
    if MULTI_SOURCE_RESEARCH_PATTERN.search(message):
        add_requirement('multi_source_public_research', 'multi_source_public_research')

    return requirements


def build_capability_recommendation(inventory, requirements):
    """Build one bounded proposal for unresolved deterministic requirements."""
    if not isinstance(inventory, Mapping):
        return None
    inventory_entries = inventory.get('capabilities')
    if not isinstance(inventory_entries, list):
        return None

    entries_by_id = {
        entry.get('id'): entry
        for entry in inventory_entries
        if isinstance(entry, Mapping) and entry.get('id') in CAPABILITY_DEFINITIONS
    }
    selected_ids = {
        capability_id
        for capability_id, entry in entries_by_id.items()
        if entry.get('state') == 'selected'
    }
    try:
        selected_effective_ids = set(
            expand_governed_capability_baseline_ids(
                inventory,
                selected_ids,
            )
        )
    except ValueError:
        return None
    option_ids = []
    requirement_ids = []
    reason_codes = []
    required_inputs = []

    def candidate_is_eligible(capability_id):
        entry = entries_by_id.get(capability_id)
        if not (
            entry
            and entry.get('state') == 'unselected'
            and entry.get('discoverable') is True
            and capability_id not in selected_effective_ids
        ):
            return False
        try:
            effective_capability_ids = expand_governed_capability_baseline_ids(
                inventory,
                [capability_id],
            )
        except ValueError:
            return False
        for effective_capability_id in effective_capability_ids:
            effective_entry = entries_by_id.get(effective_capability_id)
            if not (
                effective_entry
                and effective_entry.get('state') in {'selected', 'unselected'}
                and effective_entry.get('input_ready') is True
            ):
                return False
        return True

    for requirement in requirements or []:
        if not isinstance(requirement, Mapping):
            continue
        requirement_id = str(requirement.get('id') or '').strip()
        preferences = REQUIREMENT_CAPABILITY_PREFERENCES.get(requirement_id, [])
        if not preferences or selected_effective_ids.intersection(preferences):
            continue

        eligible_ids = [
            capability_id
            for capability_id in preferences
            if candidate_is_eligible(capability_id)
        ]
        if not eligible_ids:
            continue

        requirement_inputs = [
            str(value or '').strip()
            for value in (requirement.get('required_inputs') or [])
            if str(value or '').strip()
        ]
        if requirement_inputs and requirement_id == 'multi_document_comparison':
            continue

        requirement_ids.append(requirement_id)
        reason_code = _bounded_reason(requirement.get('reason_code'))
        if reason_code and reason_code not in reason_codes:
            reason_codes.append(reason_code)
        for input_requirement in requirement_inputs:
            if input_requirement not in required_inputs:
                required_inputs.append(input_requirement)
        for capability_id in eligible_ids:
            if capability_id not in option_ids:
                option_ids.append(capability_id)

    if not option_ids:
        return None

    options = []
    for capability_id in option_ids:
        entry = entries_by_id[capability_id]
        option = {
            'id': capability_id,
            'capability_ids': [capability_id],
            'label': entry['label'],
            'latency_class': entry['latency_class'],
            'cost_class': entry['cost_class'],
            'external_data': entry['external_data'],
            'requires_user_choice': entry['requires_user_choice'],
        }
        effective_capability_ids = expand_governed_capability_baseline_ids(
            inventory,
            [capability_id],
        )
        if effective_capability_ids != [capability_id]:
            option['effective_capability_ids'] = effective_capability_ids
        options.append(option)

    options.append({
        'id': CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID,
        'capability_ids': [],
        'label': 'Continue without additional capabilities',
        'latency_class': 'immediate',
        'cost_class': 'none',
        'external_data': False,
        'requires_user_choice': True,
    })

    return {
        'version': CAPABILITY_RECOMMENDATION_VERSION,
        'status': 'pending',
        'requirement_ids': requirement_ids,
        'reason_codes': reason_codes,
        'recommended_option_id': option_ids[0],
        'options': options,
        'required_inputs': required_inputs,
    }


def _selected_planner_capability_ids(inventory, selection_snapshot):
    selected_ids = {
        str(entry.get('id') or '').strip().lower()
        for entry in (inventory.get('capabilities') or [])
        if isinstance(entry, Mapping) and entry.get('state') == 'selected'
    }
    snapshot_values = selection_snapshot
    if isinstance(selection_snapshot, Mapping):
        snapshot_values = (
            selection_snapshot.get('selected_capability_ids')
            or selection_snapshot.get('capability_ids')
            or []
        )
    if not isinstance(snapshot_values, (list, tuple, set, frozenset)):
        snapshot_values = []
    for raw_capability_id in snapshot_values:
        capability_id = str(raw_capability_id or '').strip().lower()
        if capability_id in CAPABILITY_DEFINITIONS or capability_id == 'selected_agent':
            selected_ids.add(capability_id)
    entries_by_id = {
        str(entry.get('id') or '').strip().lower(): entry
        for entry in (inventory.get('capabilities') or [])
        if isinstance(entry, Mapping) and str(entry.get('id') or '').strip()
    }
    for capability_id in list(selected_ids):
        entry = entries_by_id.get(capability_id)
        if capability_id not in CAPABILITY_DEFINITIONS or not (entry or {}).get('bundle'):
            continue
        selected_ids.update(
            _expand_planner_capability_bundle(capability_id, entries_by_id)
        )
    return selected_ids


def _expand_planner_capability_bundle(
    capability_id,
    entries_by_id,
    *,
    path=(),
    depth=0,
):
    if depth > PLANNER_PLAN_MAX_BUNDLE_DEPTH or capability_id in path:
        raise ValueError('planner capability bundle is cyclic or too deep')
    entry = entries_by_id.get(capability_id)
    if not entry or capability_id not in CAPABILITY_DEFINITIONS:
        raise ValueError('planner capability bundle member is missing')
    if not (
        entry.get('state') in {'selected', 'unselected'}
        and entry.get('input_ready') is True
        and entry.get('read_only') is True
    ):
        raise ValueError('planner capability bundle member is ineligible')
    if entry.get('state') == 'unselected' and entry.get('discoverable') is not True:
        raise ValueError('planner capability bundle member is not discoverable')

    expanded_ids = [capability_id]
    raw_bundle = entry.get('bundle') or []
    if not isinstance(raw_bundle, list):
        raise ValueError('planner capability bundle is invalid')
    for raw_member_id in raw_bundle:
        member_id = str(raw_member_id or '').strip().lower()
        if member_id == capability_id:
            continue
        for expanded_id in _expand_planner_capability_bundle(
            member_id,
            entries_by_id,
            path=path + (capability_id,),
            depth=depth + 1,
        ):
            if expanded_id not in expanded_ids:
                expanded_ids.append(expanded_id)
        if len(expanded_ids) > PLANNER_PLAN_MAX_EFFECTIVE_CAPABILITIES:
            raise ValueError('planner capability bundle is too large')
    return expanded_ids


def expand_governed_capability_baseline_ids(inventory, capability_ids):
    """Expand server-defined built-in bundle dependencies without changing origin."""
    entries_by_id = {
        str(entry.get('id') or '').strip().lower(): entry
        for entry in (
            inventory.get('capabilities')
            if isinstance(inventory, Mapping)
            else []
        ) or []
        if isinstance(entry, Mapping) and str(entry.get('id') or '').strip()
    }

    def expand(capability_id, *, path=(), depth=0):
        if depth > PLANNER_PLAN_MAX_BUNDLE_DEPTH or capability_id in path:
            raise ValueError('capability baseline bundle is cyclic or too deep')
        entry = entries_by_id.get(capability_id)
        if not entry or capability_id not in CAPABILITY_DEFINITIONS:
            raise ValueError('capability baseline bundle member is missing')
        expanded_ids = [capability_id]
        raw_bundle = entry.get('bundle') or []
        if not isinstance(raw_bundle, list):
            raise ValueError('capability baseline bundle is invalid')
        for raw_member_id in raw_bundle:
            member_id = str(raw_member_id or '').strip().lower()
            if member_id == capability_id:
                continue
            for expanded_id in expand(
                member_id,
                path=path + (capability_id,),
                depth=depth + 1,
            ):
                if expanded_id not in expanded_ids:
                    expanded_ids.append(expanded_id)
            if len(expanded_ids) > PLANNER_PLAN_MAX_EFFECTIVE_CAPABILITIES:
                raise ValueError('capability baseline bundle is too large')
        return expanded_ids

    expanded_baseline_ids = []
    for raw_capability_id in capability_ids or []:
        capability_id = str(raw_capability_id or '').strip().lower()
        if not capability_id or capability_id == 'selected_agent':
            continue
        for expanded_id in expand(capability_id):
            if expanded_id not in expanded_baseline_ids:
                expanded_baseline_ids.append(expanded_id)
    return expanded_baseline_ids


def _planner_plan_label(approved_ids, entries_by_id):
    approved_set = set(approved_ids)
    if approved_set == {'workspace_search', 'web_search'}:
        return 'Search workspace and web'
    if approved_ids == ['deep_research']:
        return 'Run Deep Research'
    labels = [entries_by_id[capability_id]['label'] for capability_id in approved_ids]
    if len(labels) == 1:
        return f'Add {labels[0]}'
    return f"Add {', '.join(labels[:-1])} and {labels[-1]}"


def _planner_plan_aggregate_class(entries, field_name, order, default):
    return max(
        (str(entry.get(field_name) or default).strip().lower() for entry in entries),
        key=lambda value: order.get(value, len(order)),
        default=default,
    )


def _build_planner_builtin_option(candidate, entries_by_id, selected_ids, inventory_version):
    candidate_ids = []
    for raw_capability_id in candidate.get('capability_ids') or []:
        capability_id = str(raw_capability_id or '').strip().lower()
        if capability_id in selected_ids:
            continue
        if capability_id not in candidate_ids:
            candidate_ids.append(capability_id)
    if not candidate_ids:
        return None

    expanded_by_root = {}
    try:
        for capability_id in candidate_ids:
            entry = entries_by_id.get(capability_id)
            if not (
                entry
                and entry.get('state') == 'unselected'
                and entry.get('discoverable') is True
                and entry.get('input_ready') is True
                and entry.get('read_only') is True
                and entry.get('requires_user_choice') is True
            ):
                return None
            expanded_by_root[capability_id] = _expand_planner_capability_bundle(
                capability_id,
                entries_by_id,
            )
    except ValueError:
        return None

    approved_ids = sorted(
        capability_id
        for capability_id in candidate_ids
        if not any(
            capability_id in expanded_ids
            for other_id, expanded_ids in expanded_by_root.items()
            if other_id != capability_id
        )
    )
    effective_ids = sorted({
        effective_id
        for capability_id in approved_ids
        for effective_id in expanded_by_root[capability_id]
    })
    if not approved_ids or len(effective_ids) > PLANNER_PLAN_MAX_EFFECTIVE_CAPABILITIES:
        return None

    effective_entries = [entries_by_id[capability_id] for capability_id in effective_ids]
    policy_binding = [
        {
            'id': entry['id'],
            'state': entry.get('state'),
            'discoverable': entry.get('discoverable') is True,
            'input_ready': entry.get('input_ready') is True,
            'read_only': entry.get('read_only') is True,
            'requires_user_choice': entry.get('requires_user_choice') is True,
            'risk_class': entry.get('risk_class'),
            'latency_class': entry.get('latency_class'),
            'cost_class': entry.get('cost_class'),
            'external_data': entry.get('external_data') is True,
        }
        for entry in effective_entries
    ]
    option_digest = hashlib.sha256(
        json.dumps(
            {
                'inventory_version': inventory_version,
                'approved_ids': approved_ids,
                'effective_ids': effective_ids,
                'policy': policy_binding,
            },
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')
    ).hexdigest()[:32]
    risk_order = {
        'internal_read': 0,
        'external_read': 1,
    }
    risk_class = _planner_plan_aggregate_class(
        effective_entries,
        'risk_class',
        risk_order,
        'internal_read',
    )
    data_sensitivity = (
        'internal'
        if any(
            str(entry.get('risk_class') or '').strip().lower() == 'internal_read'
            for entry in effective_entries
        )
        else 'public'
    )
    return {
        'id': f'plan:{option_digest}',
        'kind': 'capability',
        'capability_ids': approved_ids,
        'effective_capability_ids': effective_ids,
        'label': _planner_plan_label(approved_ids, entries_by_id),
        'latency_class': _planner_plan_aggregate_class(
            effective_entries,
            'latency_class',
            _PLANNER_PLAN_LATENCY_ORDER,
            'seconds',
        ),
        'cost_class': _planner_plan_aggregate_class(
            effective_entries,
            'cost_class',
            _PLANNER_PLAN_COST_ORDER,
            'standard',
        ),
        'external_data': any(entry.get('external_data') is True for entry in effective_entries),
        'requires_user_choice': True,
        'read_only': True,
        'risk_class': risk_class,
        'data_sensitivity': data_sensitivity,
    }


def get_capability_option_revalidation_error(option, inventory):
    """Return a bounded error when a built-in option no longer matches server policy."""
    if not isinstance(option, Mapping) or not isinstance(inventory, Mapping):
        return 'capability_plan_invalid'
    option_kind = str(option.get('kind') or 'capability').strip().lower()
    if option_kind == 'context':
        entries_by_id = {
            str(entry.get('id') or '').strip().lower(): entry
            for entry in (inventory.get('capabilities') or [])
            if isinstance(entry, Mapping) and str(entry.get('id') or '').strip()
        }
        rebuilt_option = _build_contextual_egress_option(
            option.get('effective_capability_ids') or [],
            entries_by_id,
            inventory.get('version'),
        )
        if not rebuilt_option:
            return 'capability_plan_invalid'
        expected_option_id = rebuilt_option['id']
        if str(option.get('id') or '').endswith('_with_sensitive_inputs'):
            expected_option_id = f'{expected_option_id}_with_sensitive_inputs'
            if not (
                option.get('external_query_mode')
                == 'include_approved_sensitive_inputs'
                and 'street_address' in (option.get('sensitive_input_types') or [])
            ):
                return 'capability_plan_policy_changed'
        for field_name in (
            'kind',
            'effective_capability_ids',
            'latency_class',
            'cost_class',
            'external_data',
            'read_only',
            'risk_class',
            'data_sensitivity',
        ):
            if option.get(field_name) != rebuilt_option.get(field_name):
                return 'capability_plan_policy_changed'
        if option.get('id') != expected_option_id:
            return 'capability_plan_policy_changed'
        return None
    if option_kind != 'capability':
        return None
    option_id = str(option.get('id') or '').strip()
    approved_ids = [
        str(capability_id or '').strip().lower()
        for capability_id in (option.get('capability_ids') or [])
        if str(capability_id or '').strip()
    ]
    if not approved_ids:
        return 'capability_plan_invalid'
    entries_by_id = {
        str(entry.get('id') or '').strip().lower(): entry
        for entry in (inventory.get('capabilities') or [])
        if isinstance(entry, Mapping) and str(entry.get('id') or '').strip()
    }
    try:
        rebuilt_effective_ids = set(
            expand_governed_capability_baseline_ids(
                inventory,
                approved_ids,
            )
        )
    except ValueError:
        return 'capability_plan_invalid'
    if rebuilt_effective_ids != set(
        option.get('effective_capability_ids') or approved_ids
    ):
        return 'capability_bundle_changed'
    if not option_id.startswith('plan:'):
        if len(approved_ids) != 1:
            return 'capability_plan_invalid'
        root_entry = entries_by_id.get(approved_ids[0])
        if not root_entry:
            return 'capability_plan_invalid'
        for field_name in ('latency_class', 'cost_class', 'external_data'):
            if option.get(field_name) != root_entry.get(field_name):
                return 'capability_plan_policy_changed'
        if root_entry.get('requires_user_choice') is not True:
            return 'capability_plan_policy_changed'
        return None
    selected_ids = _selected_planner_capability_ids(inventory, None)
    rebuilt_option = _build_planner_builtin_option(
        {'capability_ids': approved_ids},
        entries_by_id,
        selected_ids,
        inventory.get('version'),
    )
    if not rebuilt_option:
        return 'capability_plan_invalid'
    if (
        set(rebuilt_option.get('capability_ids') or []) != set(approved_ids)
        or set(rebuilt_option.get('effective_capability_ids') or [])
        != set(option.get('effective_capability_ids') or approved_ids)
    ):
        return 'capability_bundle_changed'

    expected_option_id = rebuilt_option['id']
    if option_id.endswith('_with_sensitive_inputs'):
        expected_option_id = f'{expected_option_id}_with_sensitive_inputs'
        if not (
            option.get('external_query_mode') == 'include_approved_sensitive_inputs'
            and 'street_address' in (option.get('sensitive_input_types') or [])
        ):
            return 'capability_plan_policy_changed'
    if option_id != expected_option_id:
        return 'capability_plan_policy_changed'
    for field_name in (
        'latency_class',
        'cost_class',
        'external_data',
        'read_only',
        'risk_class',
        'data_sensitivity',
    ):
        if option.get(field_name) != rebuilt_option.get(field_name):
            return 'capability_plan_policy_changed'
    return None


def _build_planner_agent_option(candidate, agents_by_id, selected_ids):
    candidate_ids = [
        str(capability_id or '').strip()
        for capability_id in (candidate.get('capability_ids') or [])
        if str(capability_id or '').strip() not in selected_ids
    ]
    if len(candidate_ids) != 1:
        return None
    agent = agents_by_id.get(candidate_ids[0])
    if not (
        agent
        and agent.get('kind') == 'agent'
        and agent.get('state') == 'unselected'
        and agent.get('discoverable') is True
        and agent.get('requires_user_choice') is True
        and agent.get('read_only') is True
        and agent.get('scope_class') in AGENT_DISCOVERY_SCOPE_CLASSES
        and agent.get('risk_class') in AGENT_DISCOVERY_RISK_CLASSES
        and agent.get('data_sensitivity') in AGENT_DISCOVERY_DATA_SENSITIVITY_CLASSES
    ):
        return None
    return {
        'id': agent['id'],
        'kind': 'agent',
        'agent_ref': agent['id'],
        'capability_ids': [],
        'effective_capability_ids': [],
        'label': agent['label'],
        'category': agent['category'],
        'scope_class': agent['scope_class'],
        'latency_class': agent['latency_class'],
        'cost_class': agent['cost_class'],
        'external_data': agent['external_data'],
        'requires_user_choice': True,
        'read_only': True,
        'risk_class': agent['risk_class'],
        'data_sensitivity': agent['data_sensitivity'],
        'capability_tags': list(agent['capability_tags']),
        'evidence_types': list(agent['evidence_types']),
    }


def _planner_option_signature(option):
    if not isinstance(option, Mapping):
        return frozenset()
    agent_ref = str(option.get('agent_ref') or '').strip()
    if agent_ref:
        return frozenset({agent_ref})
    return frozenset(
        str(capability_id or '').strip().lower()
        for capability_id in (
            option.get('effective_capability_ids')
            or option.get('capability_ids')
            or []
        )
        if str(capability_id or '').strip()
    )


def _recommended_capability_option(recommendation):
    if not isinstance(recommendation, Mapping):
        return None
    recommended_option_id = str(
        recommendation.get('recommended_option_id') or ''
    ).strip()
    return next(
        (
            option
            for option in recommendation.get('options') or []
            if isinstance(option, Mapping)
            and str(option.get('id') or '').strip() == recommended_option_id
        ),
        None,
    )


def _build_contextual_egress_option(effective_ids, entries_by_id, inventory_version):
    normalized_ids = sorted({
        str(capability_id or '').strip().lower()
        for capability_id in effective_ids or []
        if str(capability_id or '').strip().lower() in entries_by_id
    })
    effective_entries = [entries_by_id[capability_id] for capability_id in normalized_ids]
    if not effective_entries or not all(
        entry.get('external_data') is True
        and entry.get('read_only') is True
        and entry.get('input_ready') is True
        and entry.get('state') in {'selected', 'unselected'}
        for entry in effective_entries
    ):
        return None
    binding = {
        'kind': 'prior_user_goal_egress',
        'inventory_version': inventory_version,
        'capabilities': [
            {
                'id': entry.get('id'),
                'state': entry.get('state'),
                'risk_class': entry.get('risk_class'),
                'latency_class': entry.get('latency_class'),
                'cost_class': entry.get('cost_class'),
                'data_sensitivity': entry.get('data_sensitivity'),
            }
            for entry in effective_entries
        ],
    }
    option_digest = hashlib.sha256(
        json.dumps(binding, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()[:32]
    effective_id_set = set(normalized_ids)
    if 'deep_research' in effective_id_set:
        label = 'Research using the earlier request'
    elif 'web_search' in effective_id_set:
        label = 'Search the web using the earlier request'
    else:
        label = 'Use external sources from the earlier request'
    risk_order = {
        'internal_read': 0,
        'external_read': 1,
    }
    return {
        'id': f'context:{option_digest}',
        'kind': 'context',
        'capability_ids': [],
        'effective_capability_ids': normalized_ids,
        'label': label,
        'latency_class': _planner_plan_aggregate_class(
            effective_entries,
            'latency_class',
            _PLANNER_PLAN_LATENCY_ORDER,
            'seconds',
        ),
        'cost_class': _planner_plan_aggregate_class(
            effective_entries,
            'cost_class',
            _PLANNER_PLAN_COST_ORDER,
            'standard',
        ),
        'external_data': True,
        'requires_user_choice': True,
        'read_only': True,
        'risk_class': _planner_plan_aggregate_class(
            effective_entries,
            'risk_class',
            risk_order,
            'external_read',
        ),
        'data_sensitivity': (
            'internal'
            if any(
                str(entry.get('risk_class') or '').strip().lower()
                == 'internal_read'
                for entry in effective_entries
            )
            else 'public'
        ),
    }


def build_contextual_egress_recommendation(
    validated_result,
    inventory,
    selection_snapshot=None,
):
    """Require one choice when a prior goal would use baseline external retrieval."""
    if not (
        isinstance(validated_result, Mapping)
        and validated_result.get('status') == 'valid'
        and validated_result.get('decision') == 'direct'
        and validated_result.get('prior_goal_included') is True
        and isinstance(inventory, Mapping)
    ):
        return None
    entries_by_id = {
        str(entry.get('id') or '').strip().lower(): entry
        for entry in inventory.get('capabilities') or []
        if isinstance(entry, Mapping) and str(entry.get('id') or '').strip()
    }
    try:
        selected_ids = _selected_planner_capability_ids(
            inventory,
            selection_snapshot,
        )
        automatic_root_ids = {
            str(capability_id or '').strip().lower()
            for capability_id in (
                selection_snapshot.get('auto_capability_ids')
                if isinstance(selection_snapshot, Mapping)
                else []
            ) or []
            if str(capability_id or '').strip()
        }
        automatic_ids = set(expand_governed_capability_baseline_ids(
            inventory,
            automatic_root_ids,
        ))
    except ValueError:
        return None
    external_effective_ids = {
        capability_id
        for capability_id in selected_ids | automatic_ids
        if capability_id in entries_by_id
        and entries_by_id[capability_id].get('external_data') is True
    }
    option = _build_contextual_egress_option(
        external_effective_ids,
        entries_by_id,
        inventory.get('version'),
    )
    if not option:
        return None
    reason_codes = [
        str(item.get('reason_code') or '').strip().lower()
        for item in validated_result.get('requirements') or []
        if isinstance(item, Mapping)
        and _bounded_reason(item.get('reason_code'))
    ]
    if not reason_codes:
        reason_codes = ['public_source_retrieval']
    return {
        'version': CAPABILITY_RECOMMENDATION_VERSION,
        'status': 'pending',
        'source': 'planner',
        'requirement_ids': [
            str(item.get('id') or '').strip().lower()
            for item in validated_result.get('requirements') or []
            if isinstance(item, Mapping) and str(item.get('id') or '').strip()
        ],
        'reason_codes': list(dict.fromkeys(reason_codes)),
        'recommended_option_id': option['id'],
        'options': [
            option,
            {
                'id': CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID,
                'kind': 'continue',
                'capability_ids': [],
                'effective_capability_ids': [],
                'label': 'Continue without external retrieval',
                'latency_class': 'immediate',
                'cost_class': 'none',
                'external_data': False,
                'requires_user_choice': True,
            },
        ],
        'required_inputs': [],
        'selected_capability_ids': sorted(selected_ids),
        'selected_context_labels': [
            entry['label']
            for entry in inventory.get('capabilities') or []
            if isinstance(entry, Mapping)
            and entry.get('state') == 'selected'
            and str(entry.get('label') or '').strip()
        ],
    }


def arbitrate_planner_capability_recommendation(
    planner_recommendation,
    deterministic_recommendation,
):
    """Activate only a validated planner recommendation in Assist mode."""
    del deterministic_recommendation
    planner = (
        copy.deepcopy(dict(planner_recommendation))
        if isinstance(planner_recommendation, Mapping)
        else None
    )
    if not planner:
        return None, {
            'activation_status': 'suppressed',
            'recommendation_source': 'direct',
            'suppression_reason': 'planner_not_materialized',
        }

    planner_signature = _planner_option_signature(
        _recommended_capability_option(planner)
    )
    if not planner_signature:
        return None, {
            'activation_status': 'suppressed',
            'recommendation_source': 'direct',
            'suppression_reason': 'planner_not_materialized',
        }
    return planner, {
        'activation_status': 'materialized',
        'recommendation_source': 'planner',
        'suppression_reason': None,
    }


def build_planner_capability_recommendation(
    validated_result,
    inventory,
    selection_snapshot=None,
):
    """Materialize validated high-confidence planner candidates as server-owned options."""
    if not (
        isinstance(validated_result, Mapping)
        and validated_result.get('status') == 'valid'
        and validated_result.get('decision') == 'propose'
        and isinstance(inventory, Mapping)
    ):
        return None
    candidates = validated_result.get('candidate_plans')
    candidates = candidates if isinstance(candidates, list) else []
    recommended_candidate_id = str(
        validated_result.get('recommended_plan_id') or ''
    ).strip().lower()
    recommended_candidate = next(
        (
            candidate
            for candidate in candidates
            if isinstance(candidate, Mapping)
            and str(candidate.get('id') or '').strip().lower() == recommended_candidate_id
        ),
        None,
    )
    if not recommended_candidate or recommended_candidate.get('confidence') != 'high':
        return None

    entries_by_id = {
        str(entry.get('id') or '').strip().lower(): entry
        for entry in (inventory.get('capabilities') or [])
        if isinstance(entry, Mapping) and str(entry.get('id') or '').strip()
    }
    agents_by_id = {
        str(entry.get('id') or '').strip(): entry
        for entry in (inventory.get('agents') or [])
        if isinstance(entry, Mapping) and str(entry.get('id') or '').strip()
    }
    try:
        selected_ids = _selected_planner_capability_ids(
            inventory,
            selection_snapshot,
        )
    except ValueError:
        return None
    auto_capability_ids = {
        str(capability_id or '').strip().lower()
        for capability_id in (
            selection_snapshot.get('auto_capability_ids')
            if isinstance(selection_snapshot, Mapping)
            else []
        ) or []
        if str(capability_id or '').strip().lower() in entries_by_id
    }
    try:
        expanded_auto_capability_ids = set(
            expand_governed_capability_baseline_ids(
                inventory,
                auto_capability_ids,
            )
        )
    except ValueError:
        return None
    already_effective_ids = selected_ids | expanded_auto_capability_ids
    ordered_candidates = [recommended_candidate] + [
        candidate
        for candidate in candidates
        if candidate is not recommended_candidate
    ]
    options = []
    option_ids_by_effective_plan = {}
    recommended_option_id = None
    reason_codes = []
    for candidate in ordered_candidates:
        if not isinstance(candidate, Mapping) or candidate.get('confidence') != 'high':
            continue
        candidate_additions = {
            str(capability_id or '').strip()
            for capability_id in (candidate.get('capability_ids') or [])
            if str(capability_id or '').strip() not in already_effective_ids
        }
        execution_union = candidate_additions | already_effective_ids
        if (
            execution_union.intersection(PLANNER_DOCUMENT_ACTION_CAPABILITY_IDS)
            and execution_union.intersection(PLANNER_RETRIEVAL_CAPABILITY_IDS)
        ) or (
            PLANNER_IMAGE_CAPABILITY_ID in execution_union
            and len(execution_union) > 1
        ):
            continue
        if candidate_additions and candidate_additions.issubset(agents_by_id):
            option = _build_planner_agent_option(
                candidate,
                agents_by_id,
                already_effective_ids,
            )
        elif candidate_additions and candidate_additions.issubset(entries_by_id):
            option = _build_planner_builtin_option(
                candidate,
                entries_by_id,
                already_effective_ids,
                inventory.get('version'),
            )
        else:
            option = None
        if not option:
            continue
        plan_key = tuple(sorted(_planner_option_signature(option)))
        option_id = option_ids_by_effective_plan.get(plan_key)
        if not option_id:
            if len(options) >= PLANNER_PLAN_MAX_ACTIONABLE_OPTIONS:
                continue
            option_id = option['id']
            option_ids_by_effective_plan[plan_key] = option_id
            options.append(option)
        candidate_id = str(candidate.get('id') or '').strip().lower()
        if candidate_id == recommended_candidate_id:
            recommended_option_id = option_id
        reason_code = _bounded_reason(candidate.get('reason_code'))
        if reason_code and reason_code not in reason_codes:
            reason_codes.append(reason_code)

    if not recommended_option_id:
        return None
    options.append({
        'id': CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID,
        'kind': 'continue',
        'capability_ids': [],
        'effective_capability_ids': [],
        'label': 'Continue without additional capabilities',
        'latency_class': 'immediate',
        'cost_class': 'none',
        'external_data': False,
        'requires_user_choice': True,
    })
    requirement_ids = [
        str(requirement.get('id') or '').strip().lower()
        for requirement in (validated_result.get('requirements') or [])
        if isinstance(requirement, Mapping) and str(requirement.get('id') or '').strip()
    ]
    return {
        'version': CAPABILITY_RECOMMENDATION_VERSION,
        'status': 'pending',
        'source': 'planner',
        'requirement_ids': requirement_ids,
        'reason_codes': reason_codes,
        'recommended_option_id': recommended_option_id,
        'options': options,
        'required_inputs': [],
        'selected_capability_ids': sorted(selected_ids),
        'selected_context_labels': [
            entry['label']
            for entry in (inventory.get('capabilities') or [])
            if isinstance(entry, Mapping)
            and entry.get('state') == 'selected'
            and str(entry.get('label') or '').strip()
        ] + (
            ['Selected agent']
            if 'selected_agent' in selected_ids
            else []
        ),
    }


def match_governed_capabilities(inventory, requirements):
    """Separate policy-approved automatic discovery from user-choice recommendations."""
    inventory_entries = (
        inventory.get('capabilities')
        if isinstance(inventory, Mapping)
        else None
    )
    if not isinstance(inventory_entries, list):
        return {
            'auto_capability_ids': [],
            'recommendation': None,
        }

    automatic_ids = []
    for requirement in requirements or []:
        if not isinstance(requirement, Mapping):
            continue
        requirement_id = str(requirement.get('id') or '').strip()
        for capability_id in REQUIREMENT_CAPABILITY_PREFERENCES.get(requirement_id, []):
            entry = next(
                (
                    capability
                    for capability in inventory_entries
                    if isinstance(capability, Mapping)
                    and capability.get('id') == capability_id
                ),
                None,
            )
            auto_bundle_allowed = False
            if entry and entry.get('auto_use_allowed') is True:
                try:
                    expanded_ids = expand_governed_capability_baseline_ids(
                        inventory,
                        [capability_id],
                    )
                except ValueError:
                    expanded_ids = []
                expanded_entries = [
                    next(
                        (
                            capability
                            for capability in inventory_entries
                            if isinstance(capability, Mapping)
                            and capability.get('id') == expanded_id
                        ),
                        None,
                    )
                    for expanded_id in expanded_ids
                ]
                auto_bundle_allowed = bool(expanded_entries) and all(
                    member
                    and member.get('input_ready') is True
                    and member.get('read_only') is True
                    and (
                        member.get('state') == 'selected'
                        or member.get('auto_use_allowed') is True
                    )
                    for member in expanded_entries
                )
            if auto_bundle_allowed:
                if capability_id not in automatic_ids:
                    automatic_ids.append(capability_id)
                break

    try:
        automatic_effective_ids = set(
            expand_governed_capability_baseline_ids(
                inventory,
                automatic_ids,
            )
        )
    except ValueError:
        automatic_ids = []
        automatic_effective_ids = set()
    recommendation_inventory = {
        'version': inventory.get('version'),
        'capabilities': [
            {
                **dict(entry),
                **(
                    {
                        'state': 'selected',
                        'selected': True,
                        'discoverable': False,
                        'auto_use_allowed': False,
                        'requires_user_choice': False,
                    }
                    if isinstance(entry, Mapping)
                    and entry.get('id') in automatic_effective_ids
                    and entry.get('state') != 'selected'
                    else {}
                ),
            }
            for entry in inventory_entries
        ],
    }
    return {
        'auto_capability_ids': automatic_ids,
        'recommendation': build_capability_recommendation(
            recommendation_inventory,
            requirements,
        ),
    }