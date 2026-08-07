# functions_orchestration_interaction.py
"""Phase 12 orchestration interaction policy and per-turn snapshot helpers."""

import copy
import hashlib
import json
from collections.abc import Mapping


ORCHESTRATION_INTERACTION_VERSION = 2
DIRECTIVE_RESOLUTION_VERSION = 1

EXECUTION_MODE_MANUAL = 'manual'
EXECUTION_MODE_BALANCED = 'balanced'
EXECUTION_MODE_AUTO = 'auto'
EXECUTION_MODES = (
    EXECUTION_MODE_MANUAL,
    EXECUTION_MODE_BALANCED,
    EXECUTION_MODE_AUTO,
)

REVIEW_VISIBILITY_COLLAPSED = 'collapsed'
REVIEW_VISIBILITY_EXPANDED = 'expanded'
REVIEW_VISIBILITY_LEVELS = (
    REVIEW_VISIBILITY_COLLAPSED,
    REVIEW_VISIBILITY_EXPANDED,
)

ORCHESTRATION_CONTEXT_PERSONAL = 'personal'
ORCHESTRATION_CONTEXT_GROUP = 'group'
ORCHESTRATION_CONTEXT_PUBLIC = 'public'
ORCHESTRATION_CONTEXT_EXTERNAL = 'external'
ORCHESTRATION_CONTEXTS = (
    ORCHESTRATION_CONTEXT_PERSONAL,
    ORCHESTRATION_CONTEXT_GROUP,
    ORCHESTRATION_CONTEXT_PUBLIC,
    ORCHESTRATION_CONTEXT_EXTERNAL,
)

LEGACY_REVIEW_ONLY_MODE = 'review_only'
DEFAULT_HARD_APPROVAL_BOUNDARIES = (
    'external_data',
    'sensitive_data',
    'write_action',
    'consequential_action',
    'budget_overflow',
    'unsupported_output_adapter',
)

DEFAULT_ORCHESTRATION_INTERACTION_POLICY = {
    'enabled_execution_modes': list(EXECUTION_MODES),
    'default_execution_mode': EXECUTION_MODE_BALANCED,
    'enabled_review_visibility': list(REVIEW_VISIBILITY_LEVELS),
    'default_review_visibility': REVIEW_VISIBILITY_COLLAPSED,
    'allow_conversation_execution_mode': True,
    'allow_per_message_execution_mode': True,
    'allow_conversation_review_visibility': True,
    'allow_per_message_review_visibility': True,
    'require_expanded_review_visibility': False,
    'context_execution_modes': {
        ORCHESTRATION_CONTEXT_PERSONAL: list(EXECUTION_MODES),
        ORCHESTRATION_CONTEXT_GROUP: list(EXECUTION_MODES),
        ORCHESTRATION_CONTEXT_PUBLIC: list(EXECUTION_MODES),
        ORCHESTRATION_CONTEXT_EXTERNAL: list(EXECUTION_MODES),
    },
    'capability_automation': {
        'workspace_search': 'recommend',
        'analyze': 'recommend',
        'compare': 'recommend',
        'image': 'recommend',
        'web_search': 'recommend',
        'url_access': 'recommend',
        'deep_research': 'recommend',
    },
    'deliverable_automation': 'recommend',
    'budgets': {
        EXECUTION_MODE_MANUAL: {
            'max_latency_seconds': 60,
            'max_cost_usd': 1.0,
            'max_tokens': 32000,
            'max_sources': 20,
            'max_artifact_bytes': 5000000,
        },
        EXECUTION_MODE_BALANCED: {
            'max_latency_seconds': 120,
            'max_cost_usd': 3.0,
            'max_tokens': 64000,
            'max_sources': 40,
            'max_artifact_bytes': 15000000,
        },
        EXECUTION_MODE_AUTO: {
            'max_latency_seconds': 240,
            'max_cost_usd': 5.0,
            'max_tokens': 128000,
            'max_sources': 80,
            'max_artifact_bytes': 30000000,
        },
    },
    'plan_details_drawer_enabled': True,
    'advanced_plan_editing': 'view_only',
    'retention_days': 90,
    'audit_enabled': True,
    'hard_approval_boundaries': list(DEFAULT_HARD_APPROVAL_BOUNDARIES),
}


def _compact_string(value, *, max_length=128):
    return ' '.join(str(value or '').split())[:max_length]


def _stable_digest(value):
    serialized = json.dumps(value, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()[:24]


def _as_dict(value):
    return value if isinstance(value, Mapping) else {}


def _normalize_identifier_list(values, allowed_values, *, fallback_values):
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        values = list(fallback_values)

    allowed = set(allowed_values)
    normalized = []
    for value in values:
        item = str(value or '').strip().lower()
        if item in allowed and item not in normalized:
            normalized.append(item)
    if not normalized:
        normalized = list(fallback_values)
    return normalized


def _normalize_execution_mode(value, fallback=EXECUTION_MODE_BALANCED):
    mode = str(value or '').strip().lower()
    if mode == LEGACY_REVIEW_ONLY_MODE:
        return LEGACY_REVIEW_ONLY_MODE
    return mode if mode in EXECUTION_MODES else fallback


def _normalize_review_visibility(value, fallback=REVIEW_VISIBILITY_COLLAPSED):
    visibility = str(value or '').strip().lower()
    return visibility if visibility in REVIEW_VISIBILITY_LEVELS else fallback


def _normalize_bool(value, fallback=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'true', '1', 'yes', 'on'}:
            return True
        if normalized in {'false', '0', 'no', 'off'}:
            return False
    return fallback


def _normalize_automation_value(value, fallback='recommend'):
    normalized = str(value or '').strip().lower()
    if normalized in {'manual_only', 'recommend', 'auto_read_only', 'blocked'}:
        return normalized
    if normalized in {'automatic', 'auto'}:
        return 'auto_read_only'
    return fallback


def _normalize_deliverable_automation(value):
    normalized = str(value or '').strip().lower()
    if normalized in {'automatic', 'recommend', 'manual_only'}:
        return normalized
    if normalized == 'auto':
        return 'automatic'
    return 'recommend'


def _bounded_int(value, fallback, *, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return min(maximum, max(minimum, parsed))


def _bounded_float(value, fallback, *, minimum, maximum):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return min(maximum, max(minimum, parsed))


def _normalize_mode_budget(raw_budget, fallback_budget):
    raw_budget = _as_dict(raw_budget)
    return {
        'max_latency_seconds': _bounded_int(
            raw_budget.get('max_latency_seconds'),
            fallback_budget['max_latency_seconds'],
            minimum=1,
            maximum=3600,
        ),
        'max_cost_usd': _bounded_float(
            raw_budget.get('max_cost_usd'),
            fallback_budget['max_cost_usd'],
            minimum=0,
            maximum=1000,
        ),
        'max_tokens': _bounded_int(
            raw_budget.get('max_tokens'),
            fallback_budget['max_tokens'],
            minimum=1000,
            maximum=2000000,
        ),
        'max_sources': _bounded_int(
            raw_budget.get('max_sources'),
            fallback_budget['max_sources'],
            minimum=0,
            maximum=1000,
        ),
        'max_artifact_bytes': _bounded_int(
            raw_budget.get('max_artifact_bytes'),
            fallback_budget['max_artifact_bytes'],
            minimum=0,
            maximum=500000000,
        ),
    }


def _select_allowed_value(
    candidates,
    allowed_values,
    default_value,
    default_source,
    *,
    fallback_source='admin_policy_fallback',
):
    allowed = list(allowed_values or [])
    normalized_default = str(default_value or '').strip().lower()
    if normalized_default not in allowed:
        normalized_default = allowed[0]

    for candidate in candidates:
        value = str(candidate.get('value') or '').strip().lower()
        if not value:
            continue
        if value in allowed:
            return value, candidate.get('source') or default_source, None
        return normalized_default, fallback_source, {
            'requested': value,
            'source': candidate.get('source') or 'unknown',
            'reason': 'not_allowed_by_admin_policy',
            'fallback': normalized_default,
        }
    return normalized_default, default_source, None


def normalize_orchestration_interaction_policy(settings=None):
    """Return a bounded admin policy for Phase 12 interaction controls."""
    source_settings = _as_dict(settings)
    source_policy = _as_dict(source_settings.get('orchestration_interaction_policy'))
    defaults = DEFAULT_ORCHESTRATION_INTERACTION_POLICY

    enabled_execution_modes = _normalize_identifier_list(
        source_policy.get(
            'enabled_execution_modes',
            source_settings.get('orchestration_execution_modes_enabled'),
        ),
        EXECUTION_MODES,
        fallback_values=defaults['enabled_execution_modes'],
    )
    default_execution_mode = _normalize_execution_mode(
        source_policy.get(
            'default_execution_mode',
            source_settings.get('orchestration_default_execution_mode'),
        ),
        defaults['default_execution_mode'],
    )
    if default_execution_mode == LEGACY_REVIEW_ONLY_MODE:
        default_execution_mode = EXECUTION_MODE_BALANCED
    if default_execution_mode not in enabled_execution_modes:
        default_execution_mode = enabled_execution_modes[0]

    enabled_review_visibility = _normalize_identifier_list(
        source_policy.get(
            'enabled_review_visibility',
            source_settings.get('orchestration_review_visibility_levels_enabled'),
        ),
        REVIEW_VISIBILITY_LEVELS,
        fallback_values=defaults['enabled_review_visibility'],
    )
    default_review_visibility = _normalize_review_visibility(
        source_policy.get(
            'default_review_visibility',
            source_settings.get('orchestration_default_review_visibility'),
        ),
        defaults['default_review_visibility'],
    )
    require_expanded = _normalize_bool(
        source_policy.get(
            'require_expanded_review_visibility',
            source_settings.get('orchestration_require_expanded_review_visibility'),
        ),
        defaults['require_expanded_review_visibility'],
    )
    if require_expanded and REVIEW_VISIBILITY_EXPANDED not in enabled_review_visibility:
        enabled_review_visibility.append(REVIEW_VISIBILITY_EXPANDED)
    if default_review_visibility not in enabled_review_visibility:
        default_review_visibility = enabled_review_visibility[0]
    if require_expanded:
        default_review_visibility = REVIEW_VISIBILITY_EXPANDED

    raw_context_modes = _as_dict(
        source_policy.get(
            'context_execution_modes',
            source_settings.get('orchestration_context_execution_modes'),
        )
    )
    context_execution_modes = {}
    for context_name in ORCHESTRATION_CONTEXTS:
        context_execution_modes[context_name] = [
            mode
            for mode in _normalize_identifier_list(
                raw_context_modes.get(context_name),
                EXECUTION_MODES,
                fallback_values=enabled_execution_modes,
            )
            if mode in enabled_execution_modes
        ]
        if not context_execution_modes[context_name]:
            context_execution_modes[context_name] = [default_execution_mode]

    raw_capability_automation = _as_dict(
        source_policy.get(
            'capability_automation',
            source_settings.get('orchestration_capability_automation'),
        )
    )
    capability_automation = {}
    for capability_id, fallback_mode in defaults['capability_automation'].items():
        capability_automation[capability_id] = _normalize_automation_value(
            raw_capability_automation.get(capability_id),
            fallback_mode,
        )

    raw_budgets = _as_dict(source_policy.get('budgets', source_settings.get('orchestration_mode_budgets')))
    budgets = {
        mode: _normalize_mode_budget(raw_budgets.get(mode), defaults['budgets'][mode])
        for mode in EXECUTION_MODES
    }

    hard_approval_boundaries = _normalize_identifier_list(
        source_policy.get(
            'hard_approval_boundaries',
            source_settings.get('orchestration_hard_approval_boundaries'),
        ),
        DEFAULT_HARD_APPROVAL_BOUNDARIES,
        fallback_values=DEFAULT_HARD_APPROVAL_BOUNDARIES,
    )

    policy = {
        'version': ORCHESTRATION_INTERACTION_VERSION,
        'enabled_execution_modes': enabled_execution_modes,
        'default_execution_mode': default_execution_mode,
        'enabled_review_visibility': enabled_review_visibility,
        'default_review_visibility': default_review_visibility,
        'allow_conversation_execution_mode': _normalize_bool(
            source_policy.get(
                'allow_conversation_execution_mode',
                source_settings.get('orchestration_allow_conversation_execution_mode'),
            ),
            defaults['allow_conversation_execution_mode'],
        ),
        'allow_per_message_execution_mode': _normalize_bool(
            source_policy.get(
                'allow_per_message_execution_mode',
                source_settings.get('orchestration_allow_per_message_execution_mode'),
            ),
            defaults['allow_per_message_execution_mode'],
        ),
        'allow_conversation_review_visibility': _normalize_bool(
            source_policy.get(
                'allow_conversation_review_visibility',
                source_settings.get('orchestration_allow_conversation_review_visibility'),
            ),
            defaults['allow_conversation_review_visibility'],
        ),
        'allow_per_message_review_visibility': _normalize_bool(
            source_policy.get(
                'allow_per_message_review_visibility',
                source_settings.get('orchestration_allow_per_message_review_visibility'),
            ),
            defaults['allow_per_message_review_visibility'],
        ),
        'require_expanded_review_visibility': require_expanded,
        'context_execution_modes': context_execution_modes,
        'capability_automation': capability_automation,
        'deliverable_automation': _normalize_deliverable_automation(
            source_policy.get(
                'deliverable_automation',
                source_settings.get('orchestration_deliverable_automation'),
            )
        ),
        'budgets': budgets,
        'plan_details_drawer_enabled': _normalize_bool(
            source_policy.get(
                'plan_details_drawer_enabled',
                source_settings.get('orchestration_plan_details_drawer_enabled'),
            ),
            defaults['plan_details_drawer_enabled'],
        ),
        'advanced_plan_editing': (
            _compact_string(
                source_policy.get(
                    'advanced_plan_editing',
                    source_settings.get('orchestration_advanced_plan_editing'),
                ),
                max_length=32,
            )
            or defaults['advanced_plan_editing']
        ),
        'retention_days': _bounded_int(
            source_policy.get(
                'retention_days',
                source_settings.get('orchestration_interaction_retention_days'),
            ),
            defaults['retention_days'],
            minimum=1,
            maximum=3650,
        ),
        'audit_enabled': _normalize_bool(
            source_policy.get(
                'audit_enabled',
                source_settings.get('orchestration_interaction_audit_enabled'),
            ),
            defaults['audit_enabled'],
        ),
        'hard_approval_boundaries': hard_approval_boundaries,
    }
    policy['policy_version'] = _stable_digest(policy)
    return policy


def _extract_preference_container(value):
    if not isinstance(value, Mapping):
        return {}
    settings = value.get('settings') if isinstance(value.get('settings'), Mapping) else value
    preference = settings.get('orchestration_interaction')
    if isinstance(preference, Mapping):
        return preference
    camel_preference = settings.get('orchestrationInteraction')
    return camel_preference if isinstance(camel_preference, Mapping) else {}


def _extract_request_interaction(request_payload):
    payload = _as_dict(request_payload)
    interaction = payload.get('orchestration_interaction')
    if isinstance(interaction, Mapping):
        return interaction

    legacy_mode = payload.get('mode')
    return {
        'execution_mode': payload.get('execution_mode') or legacy_mode,
        'review_visibility': payload.get('review_visibility'),
    }


def _normalize_context_type(value):
    normalized = str(value or '').strip().lower()
    return normalized if normalized in ORCHESTRATION_CONTEXTS else ORCHESTRATION_CONTEXT_PERSONAL


def resolve_orchestration_interaction(
    *,
    settings=None,
    user_settings=None,
    conversation=None,
    request_payload=None,
    context_type=ORCHESTRATION_CONTEXT_PERSONAL,
):
    """Resolve one submitted turn's execution mode and review visibility snapshot."""
    policy = normalize_orchestration_interaction_policy(settings)
    context_name = _normalize_context_type(context_type)
    context_allowed_modes = list(
        policy['context_execution_modes'].get(context_name)
        or policy['enabled_execution_modes']
    )
    if policy['default_execution_mode'] not in context_allowed_modes:
        context_default_mode = context_allowed_modes[0]
    else:
        context_default_mode = policy['default_execution_mode']

    user_preference = _extract_preference_container(user_settings)
    conversation_preference = _extract_preference_container(conversation)
    request_interaction = _extract_request_interaction(request_payload)

    requested_mode = _normalize_execution_mode(
        request_interaction.get('execution_mode'),
        fallback='',
    )
    requested_visibility = _normalize_review_visibility(
        request_interaction.get('review_visibility'),
        fallback='',
    )
    legacy_review_only = requested_mode == LEGACY_REVIEW_ONLY_MODE
    if legacy_review_only:
        requested_mode = EXECUTION_MODE_BALANCED
        requested_visibility = REVIEW_VISIBILITY_EXPANDED

    execution_candidates = []
    if requested_mode and policy['allow_per_message_execution_mode']:
        execution_candidates.append({
            'value': requested_mode,
            'source': 'per_message_override',
        })
    if policy['allow_conversation_execution_mode']:
        execution_candidates.append({
            'value': conversation_preference.get('execution_mode'),
            'source': 'conversation_preference',
        })
    execution_candidates.append({
        'value': user_preference.get('default_execution_mode'),
        'source': 'user_preference',
    })
    execution_mode, execution_source, execution_fallback = _select_allowed_value(
        execution_candidates,
        context_allowed_modes,
        context_default_mode,
        'admin_default',
    )

    visibility_candidates = []
    if requested_visibility and policy['allow_per_message_review_visibility']:
        visibility_candidates.append({
            'value': requested_visibility,
            'source': 'per_message_override',
        })
    if policy['allow_conversation_review_visibility']:
        visibility_candidates.append({
            'value': conversation_preference.get('review_visibility'),
            'source': 'conversation_preference',
        })
    visibility_candidates.append({
        'value': user_preference.get('default_review_visibility'),
        'source': 'user_preference',
    })
    review_visibility, review_source, review_fallback = _select_allowed_value(
        visibility_candidates,
        policy['enabled_review_visibility'],
        policy['default_review_visibility'],
        'admin_default',
    )
    if policy['require_expanded_review_visibility']:
        review_visibility = REVIEW_VISIBILITY_EXPANDED
        review_source = 'admin_policy_required'
        review_fallback = None

    user_preference_version = _stable_digest(user_preference)
    snapshot = {
        'version': ORCHESTRATION_INTERACTION_VERSION,
        'execution_mode': execution_mode,
        'execution_mode_source': execution_source,
        'review_visibility': review_visibility,
        'review_visibility_source': review_source,
        'admin_policy_version': policy['policy_version'],
        'user_preference_version': user_preference_version,
        'directive_resolution_version': DIRECTIVE_RESOLUTION_VERSION,
        'memory_revision_digest': '',
        'applied_directive_refs': [],
        'overridden_directive_refs': [],
        'conflicting_directive_refs': [],
        'hard_approval_boundaries': list(policy['hard_approval_boundaries']),
        'context_type': context_name,
        'policy_summary': {
            'enabled_execution_modes': list(context_allowed_modes),
            'enabled_review_visibility': list(policy['enabled_review_visibility']),
            'allow_per_message_execution_mode': policy['allow_per_message_execution_mode'],
            'allow_conversation_execution_mode': policy['allow_conversation_execution_mode'],
            'allow_per_message_review_visibility': policy['allow_per_message_review_visibility'],
            'allow_conversation_review_visibility': policy['allow_conversation_review_visibility'],
            'plan_details_drawer_enabled': policy['plan_details_drawer_enabled'],
            'advanced_plan_editing': policy['advanced_plan_editing'],
        },
        'mode_budget': copy.deepcopy(policy['budgets'][execution_mode]),
    }
    fallbacks = [fallback for fallback in (execution_fallback, review_fallback) if fallback]
    if legacy_review_only:
        snapshot.setdefault('legacy_migration', {})['mode'] = LEGACY_REVIEW_ONLY_MODE
    if fallbacks:
        snapshot['fallbacks'] = fallbacks
    return snapshot


def execution_mode_allows_automatic_read(interaction_snapshot, capability_entry):
    """Return whether the selected mode permits silent low-risk read-only work."""
    snapshot = _as_dict(interaction_snapshot)
    capability = _as_dict(capability_entry)
    mode = _normalize_execution_mode(snapshot.get('execution_mode'))
    if mode == EXECUTION_MODE_MANUAL:
        return False
    if capability.get('read_only') is not True:
        return False
    if capability.get('external_data') is True:
        return False
    if capability.get('auto_use_allowed') is not True:
        return False
    return mode in {EXECUTION_MODE_BALANCED, EXECUTION_MODE_AUTO}


def execution_mode_allows_recommendation(interaction_snapshot, capability_entry):
    """Return whether unselected optional capability recommendations may pause the turn."""
    snapshot = _as_dict(interaction_snapshot)
    capability = _as_dict(capability_entry)
    mode = _normalize_execution_mode(snapshot.get('execution_mode'))
    if capability.get('requires_user_choice') is not True:
        return False
    if mode == EXECUTION_MODE_AUTO and capability.get('external_data') is not True:
        return False
    return True


def apply_execution_mode_to_capability_inventory(inventory, interaction_snapshot):
    """Return an inventory with mode-specific automation/recommendation flags applied."""
    if not isinstance(inventory, Mapping):
        return inventory
    updated = copy.deepcopy(dict(inventory))
    capabilities = []
    for entry in updated.get('capabilities') or []:
        if not isinstance(entry, Mapping):
            continue
        capability = dict(entry)
        if not execution_mode_allows_automatic_read(interaction_snapshot, capability):
            capability['auto_use_allowed'] = False
        if not execution_mode_allows_recommendation(interaction_snapshot, capability):
            capability['requires_user_choice'] = False
        capabilities.append(capability)
    updated['capabilities'] = capabilities
    return updated