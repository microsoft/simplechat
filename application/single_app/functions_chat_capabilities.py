# functions_chat_capabilities.py
"""Governed built-in capability discovery for chat orchestration."""

import re
from collections.abc import Mapping

from functions_chat_orchestration import user_requested_image_generation


CAPABILITY_INVENTORY_VERSION = 1
CAPABILITY_RECOMMENDATION_VERSION = 1
CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID = 'continue_without_capabilities'

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


def _coerce_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() == 'true'
    return bool(value)


def _bounded_reason(value):
    normalized = re.sub(r'[^a-z0-9_]+', '_', str(value or '').strip().lower()).strip('_')
    return normalized[:80] or None


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
        ):
            return False
        for effective_capability_id in entry.get('bundle') or []:
            effective_entry = entries_by_id.get(effective_capability_id)
            if not effective_entry or effective_entry.get('state') not in {'selected', 'unselected'}:
                return False
        return True

    for requirement in requirements or []:
        if not isinstance(requirement, Mapping):
            continue
        requirement_id = str(requirement.get('id') or '').strip()
        preferences = REQUIREMENT_CAPABILITY_PREFERENCES.get(requirement_id, [])
        if not preferences or selected_ids.intersection(preferences):
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
        if entry.get('bundle'):
            option['effective_capability_ids'] = list(entry['bundle'])
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
            if entry and entry.get('auto_use_allowed') is True:
                if capability_id not in automatic_ids:
                    automatic_ids.append(capability_id)
                break

    recommendation_inventory = {
        'version': inventory.get('version'),
        'capabilities': [
            dict(entry)
            for entry in inventory_entries
            if not isinstance(entry, Mapping)
            or entry.get('id') not in automatic_ids
        ],
    }
    return {
        'auto_capability_ids': automatic_ids,
        'recommendation': build_capability_recommendation(
            recommendation_inventory,
            requirements,
        ),
    }