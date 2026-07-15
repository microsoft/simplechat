# functions_chat_capability_choices.py
"""Durable capability proposal, decision, and resume contracts."""

import copy
import re
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

from functions_chat_capabilities import CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID


CAPABILITY_CHOICE_VERSION = 1
CAPABILITY_PROVENANCE_VERSION = 1
DEFAULT_CAPABILITY_CHOICE_TTL_SECONDS = 86400
MAX_CAPABILITY_CHOICE_TTL_SECONDS = 604800
CAPABILITY_RESUME_LEASE_SECONDS = 1800
CAPABILITY_PROPOSAL_STATUSES = {
    'pending',
    'approved',
    'declined',
    'expired',
    'invalidated',
}
CAPABILITY_RESUME_STATUSES = {
    'not_requested',
    'pending',
    'running',
    'completed',
    'failed',
}
STREET_ADDRESS_PATTERN = re.compile(
    r'\b\d{1,6}\s+(?:[A-Za-z0-9][A-Za-z0-9.\'-]*\s+){0,6}'
    r'(?:Street|St|Road|Rd|Avenue|Ave|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|'
    r'Place|Pl|Parkway|Pkwy)\b(?:\s*,\s*[A-Za-z .\'-]+)?(?:\s+[A-Z]{2})?(?:\s+\d{5}(?:-\d{4})?)?',
    re.IGNORECASE,
)
EMAIL_PATTERN = re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.IGNORECASE)
PHONE_PATTERN = re.compile(r'(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)')
ACCOUNT_IDENTIFIER_PATTERN = re.compile(
    r'\b(?:account|parcel|customer|member|case)\s*(?:id|number|no\.?|#)\s*[:#-]?\s*[A-Z0-9-]{4,}\b',
    re.IGNORECASE,
)
PARCEL_LOOKUP_PATTERN = re.compile(
    r'\b(?:parcel|property\s+(?:record|records|assessment|assessor)|tax\s+record|this\s+address|'
    r'at\s+the\s+(?:property|address))\b',
    re.IGNORECASE,
)


class CapabilityChoiceError(ValueError):
    """Raised when a capability proposal or decision is invalid."""

    def __init__(self, message, *, code='invalid_capability_choice'):
        super().__init__(message)
        self.code = code


def _utc_now():
    return datetime.now(timezone.utc)


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


def _normalize_identifier(value, field_name):
    normalized = str(value or '').strip()
    if not normalized or len(normalized) > 200:
        raise CapabilityChoiceError(f'{field_name} is required', code=f'invalid_{field_name}')
    return normalized


def _normalize_identifiers(values, *, max_items=16):
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    normalized = []
    for value in values:
        identifier = str(value or '').strip()
        if not identifier or len(identifier) > 200 or identifier in normalized:
            continue
        normalized.append(identifier)
        if len(normalized) >= max_items:
            break
    return normalized


def _normalize_options(options):
    normalized_options = []
    seen_option_ids = set()
    for raw_option in options or []:
        if not isinstance(raw_option, Mapping):
            continue
        option_id = _normalize_identifier(raw_option.get('id'), 'option_id')
        if option_id in seen_option_ids:
            raise CapabilityChoiceError('proposal option IDs must be unique', code='duplicate_option_id')
        seen_option_ids.add(option_id)
        option_kind = str(raw_option.get('kind') or 'capability').strip().lower()
        if option_id == CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID:
            option_kind = 'continue'
        if option_kind not in {'capability', 'agent', 'continue'}:
            raise CapabilityChoiceError('proposal option kind is invalid', code='invalid_option_kind')
        capability_ids = _normalize_identifiers(raw_option.get('capability_ids'), max_items=8)
        effective_ids = _normalize_identifiers(
            raw_option.get('effective_capability_ids') or capability_ids,
            max_items=8,
        )
        agent_ref = str(raw_option.get('agent_ref') or '').strip()
        if option_kind == 'continue':
            capability_ids = []
            effective_ids = []
            agent_ref = ''
        elif option_kind == 'agent':
            if capability_ids or effective_ids:
                raise CapabilityChoiceError(
                    'agent options cannot name built-in capabilities',
                    code='invalid_agent_option_capability',
                )
            if agent_ref != option_id or not re.fullmatch(
                r'agent:(?:personal|global|group):[a-f0-9]{32}',
                agent_ref,
            ):
                raise CapabilityChoiceError(
                    'agent option reference is invalid',
                    code='invalid_agent_option_reference',
                )
        elif not capability_ids:
            raise CapabilityChoiceError(
                'capability options must name at least one capability',
                code='missing_option_capability',
            )
        normalized_option = {
            'id': option_id,
            'kind': option_kind,
            'capability_ids': capability_ids,
            'effective_capability_ids': effective_ids,
            'label': ' '.join(str(raw_option.get('label') or option_id).split())[:120],
            'latency_class': str(raw_option.get('latency_class') or 'unknown').strip()[:40],
            'cost_class': str(raw_option.get('cost_class') or 'unknown').strip()[:40],
            'external_data': bool(raw_option.get('external_data')),
            'requires_user_choice': True,
            'external_query_mode': str(
                raw_option.get('external_query_mode') or 'minimized'
            ).strip().lower()[:40],
            'sensitive_input_types': _normalize_identifiers(
                raw_option.get('sensitive_input_types'),
                max_items=8,
            ),
        }
        if option_kind == 'agent':
            normalized_option.update({
                'agent_ref': agent_ref,
                'category': str(raw_option.get('category') or 'specialized_agent').strip()[:40],
                'scope_class': str(raw_option.get('scope_class') or '').strip().lower()[:20],
                'read_only': raw_option.get('read_only') is True,
                'risk_class': str(raw_option.get('risk_class') or '').strip().lower()[:40],
                'data_sensitivity': str(
                    raw_option.get('data_sensitivity') or ''
                ).strip().lower()[:40],
                'capability_tags': _normalize_identifiers(
                    raw_option.get('capability_tags'),
                    max_items=16,
                ),
                'evidence_types': _normalize_identifiers(
                    raw_option.get('evidence_types'),
                    max_items=16,
                ),
            })
            if (
                normalized_option['scope_class'] not in {'personal', 'global', 'group'}
                or normalized_option['read_only'] is not True
                or not normalized_option['capability_tags']
                or not normalized_option['evidence_types']
            ):
                raise CapabilityChoiceError(
                    'agent option descriptor is incomplete',
                    code='invalid_agent_option_descriptor',
                )
        normalized_options.append(normalized_option)
    if not normalized_options:
        raise CapabilityChoiceError('proposal options are required', code='missing_options')
    return normalized_options


def build_minimized_external_query(user_message, *, include_sensitive_inputs=False):
    """Build a current-message-only query while omitting unnecessary personal data."""
    query = ' '.join(str(user_message or '').split())
    omitted_types = []
    replacements = (
        (STREET_ADDRESS_PATTERN, 'street_address'),
        (EMAIL_PATTERN, 'email_address'),
        (PHONE_PATTERN, 'phone_number'),
        (ACCOUNT_IDENTIFIER_PATTERN, 'account_identifier'),
    )
    if not include_sensitive_inputs:
        for pattern, sensitive_type in replacements:
            if pattern.search(query):
                query = pattern.sub(' ', query)
                omitted_types.append(sensitive_type)
    query = re.sub(r'\s+([,.;:!?])', r'\1', query)
    query = re.sub(r'\s{2,}', ' ', query).strip(' ,;:-')
    return {
        'query': query[:1000],
        'source': 'current_message_only',
        'omitted_sensitive_input_types': omitted_types,
        'parcel_specific': bool(PARCEL_LOOKUP_PATTERN.search(str(user_message or ''))),
        'conversation_history_included': False,
        'workspace_content_included': False,
    }


def add_sensitive_external_query_options(recommendation, user_message):
    """Add explicit address-bearing alternatives only for parcel-specific requests."""
    if not isinstance(recommendation, Mapping):
        return recommendation
    minimized_query = build_minimized_external_query(user_message)
    if (
        not minimized_query['parcel_specific']
        or 'street_address' not in minimized_query['omitted_sensitive_input_types']
    ):
        return copy.deepcopy(dict(recommendation))

    updated = copy.deepcopy(dict(recommendation))
    updated_options = []
    sensitive_recommended_option_id = None
    for option in updated.get('options') or []:
        if not isinstance(option, Mapping):
            continue
        normalized_option = dict(option)
        if normalized_option.get('external_data') and normalized_option.get('capability_ids'):
            normalized_option['external_query_mode'] = 'minimized'
            updated_options.append(normalized_option)
            sensitive_option = dict(normalized_option)
            sensitive_option['id'] = f"{normalized_option['id']}_with_sensitive_inputs"
            sensitive_option['label'] = f"{normalized_option.get('label') or 'Search'} with supplied address"
            sensitive_option['external_query_mode'] = 'include_approved_sensitive_inputs'
            sensitive_option['sensitive_input_types'] = ['street_address']
            updated_options.append(sensitive_option)
            if normalized_option.get('id') == updated.get('recommended_option_id'):
                sensitive_recommended_option_id = sensitive_option['id']
        else:
            updated_options.append(normalized_option)
    updated['options'] = updated_options
    if sensitive_recommended_option_id:
        updated['recommended_option_id'] = sensitive_recommended_option_id
    updated['sensitive_data_notice_required'] = True
    return updated


def build_capability_choice_proposal(
    recommendation,
    *,
    run_id,
    conversation_id,
    user_message_id,
    assistant_message_id=None,
    now=None,
    ttl_seconds=DEFAULT_CAPABILITY_CHOICE_TTL_SECONDS,
):
    """Create one bounded, durable proposal linked to an exact user turn."""
    if not isinstance(recommendation, Mapping):
        raise CapabilityChoiceError('recommendation is required', code='missing_recommendation')
    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    try:
        normalized_ttl = int(ttl_seconds)
    except (TypeError, ValueError):
        normalized_ttl = DEFAULT_CAPABILITY_CHOICE_TTL_SECONDS
    normalized_ttl = max(60, min(normalized_ttl, MAX_CAPABILITY_CHOICE_TTL_SECONDS))
    proposal_id = str(assistant_message_id or uuid.uuid4())
    options = _normalize_options(recommendation.get('options'))
    option_ids = {option['id'] for option in options}
    recommended_option_id = _normalize_identifier(
        recommendation.get('recommended_option_id'),
        'recommended_option_id',
    )
    if recommended_option_id not in option_ids:
        raise CapabilityChoiceError(
            'recommended option must be allowlisted',
            code='invalid_recommended_option',
        )
    return {
        'version': CAPABILITY_CHOICE_VERSION,
        'proposal_id': proposal_id,
        'run_id': _normalize_identifier(run_id, 'run_id'),
        'conversation_id': _normalize_identifier(conversation_id, 'conversation_id'),
        'user_message_id': _normalize_identifier(user_message_id, 'user_message_id'),
        'assistant_message_id': proposal_id,
        'status': 'pending',
        'requirement_ids': _normalize_identifiers(recommendation.get('requirement_ids')),
        'reason_codes': _normalize_identifiers(recommendation.get('reason_codes')),
        'recommended_option_id': recommended_option_id,
        'options': options,
        'created_at': current_time.isoformat(),
        'expires_at': (current_time + timedelta(seconds=normalized_ttl)).isoformat(),
        'decision': None,
        'resume': {
            'status': 'not_requested',
            'execution_id': None,
            'child_run_id': None,
            'assistant_message_id': None,
            'claimed_at': None,
            'lease_expires_at': None,
            'completed_at': None,
            'error_type': None,
        },
    }


def get_capability_choice_option(proposal, option_id):
    normalized_option_id = str(option_id or '').strip()
    return next(
        (
            dict(option)
            for option in (proposal.get('options') or [])
            if isinstance(option, Mapping) and option.get('id') == normalized_option_id
        ),
        None,
    )


def capability_choice_is_expired(proposal, *, now=None):
    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    expires_at = _parse_timestamp(proposal.get('expires_at'))
    return expires_at is None or current_time >= expires_at


def apply_capability_choice_decision(proposal, option_id, *, actor_user_id, now=None):
    """Apply an allowlisted decision once and return an idempotent replay thereafter."""
    if not isinstance(proposal, Mapping):
        raise CapabilityChoiceError('proposal is required', code='invalid_proposal')
    updated = copy.deepcopy(dict(proposal))
    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    normalized_option_id = _normalize_identifier(option_id, 'option_id')
    actor_user_id = _normalize_identifier(actor_user_id, 'actor_user_id')
    existing_decision = updated.get('decision') if isinstance(updated.get('decision'), Mapping) else None
    if existing_decision:
        if existing_decision.get('option_id') != normalized_option_id:
            raise CapabilityChoiceError(
                'this proposal already has a different decision',
                code='decision_conflict',
            )
        return updated, True

    status = str(updated.get('status') or '').strip().lower()
    if status != 'pending':
        raise CapabilityChoiceError(
            'this capability proposal is no longer pending',
            code=f'proposal_{status or "invalid"}',
        )
    if capability_choice_is_expired(updated, now=current_time):
        updated['status'] = 'expired'
        raise CapabilityChoiceError('this capability proposal has expired', code='proposal_expired')

    option = get_capability_choice_option(updated, normalized_option_id)
    if option is None:
        raise CapabilityChoiceError(
            'option_id is not valid for this proposal',
            code='option_not_allowlisted',
        )
    capability_ids = list(option.get('capability_ids') or [])
    agent_ref = str(option.get('agent_ref') or '').strip() or None
    decision_status = 'declined' if not capability_ids and not agent_ref else 'approved'
    updated['status'] = decision_status
    updated['decision'] = {
        'option_id': normalized_option_id,
        'status': decision_status,
        'capability_ids': capability_ids,
        'effective_capability_ids': list(option.get('effective_capability_ids') or capability_ids),
        'agent_ref': agent_ref,
        'external_query_mode': option.get('external_query_mode') or 'minimized',
        'sensitive_input_types': list(option.get('sensitive_input_types') or []),
        'actor_user_id': actor_user_id,
        'decided_at': current_time.isoformat(),
    }
    updated['resume'] = {
        'status': 'pending',
        'execution_id': None,
        'child_run_id': None,
        'assistant_message_id': None,
        'claimed_at': None,
        'lease_expires_at': None,
        'completed_at': None,
        'error_type': None,
    }
    return updated, False


def revalidate_capability_choice(proposal, inventory):
    """Reject approved capabilities that are no longer offerable at resume time."""
    decision = proposal.get('decision') if isinstance(proposal, Mapping) else None
    if not isinstance(decision, Mapping):
        raise CapabilityChoiceError('proposal has no decision', code='decision_missing')
    if decision.get('status') == 'declined':
        return True
    inventory_entries = (
        inventory.get('capabilities')
        if isinstance(inventory, Mapping)
        else None
    )
    entries_by_id = {
        entry.get('id'): entry
        for entry in (inventory_entries or [])
        if isinstance(entry, Mapping) and entry.get('id')
    }
    approved_capability_ids = set(decision.get('capability_ids') or [])
    effective_capability_ids = set(
        decision.get('effective_capability_ids') or approved_capability_ids
    )
    for capability_id in effective_capability_ids:
        entry = entries_by_id.get(capability_id)
        if not entry:
            raise CapabilityChoiceError(
                'an approved capability is no longer in the governed inventory',
                code='capability_missing',
            )
        if entry.get('state') not in {'selected', 'unselected'}:
            raise CapabilityChoiceError(
                'an approved capability is no longer available or authorized',
                code=f"capability_{entry.get('state') or 'invalid'}",
            )
        if (
            capability_id in approved_capability_ids
            and entry.get('state') == 'unselected'
            and entry.get('discoverable') is not True
        ):
            raise CapabilityChoiceError(
                'an approved capability is no longer discoverable',
                code='capability_policy_blocked',
            )
    agent_ref = str(decision.get('agent_ref') or '').strip()
    if agent_ref:
        agent_entries = (
            inventory.get('agents')
            if isinstance(inventory, Mapping)
            else None
        )
        agent_entry = next(
            (
                entry
                for entry in (agent_entries or [])
                if isinstance(entry, Mapping) and entry.get('id') == agent_ref
            ),
            None,
        )
        if not agent_entry:
            raise CapabilityChoiceError(
                'the approved agent is no longer in the governed catalog',
                code='agent_missing',
            )
        if not (
            agent_entry.get('state') == 'unselected'
            and agent_entry.get('discoverable') is True
            and agent_entry.get('requires_user_choice') is True
            and agent_entry.get('read_only') is True
        ):
            raise CapabilityChoiceError(
                'the approved agent is no longer governed for discovery',
                code='agent_policy_blocked',
            )
        approved_option = get_capability_choice_option(
            proposal,
            decision.get('option_id'),
        )
        if not approved_option or approved_option.get('agent_ref') != agent_ref:
            raise CapabilityChoiceError(
                'the approved agent option is no longer valid',
                code='agent_option_invalid',
            )
        scalar_descriptor_fields = (
            'scope_class',
            'read_only',
            'external_data',
            'risk_class',
            'data_sensitivity',
            'cost_class',
            'latency_class',
        )
        list_descriptor_fields = ('capability_tags', 'evidence_types')
        descriptor_changed = any(
            approved_option.get(field_name) != agent_entry.get(field_name)
            for field_name in scalar_descriptor_fields
        ) or any(
            list(approved_option.get(field_name) or [])
            != list(agent_entry.get(field_name) or [])
            for field_name in list_descriptor_fields
        )
        if descriptor_changed:
            raise CapabilityChoiceError(
                'the approved agent discovery policy has changed',
                code='agent_policy_changed',
            )
    return True


def claim_capability_choice_resume(proposal, *, now=None, execution_id=None, child_run_id=None):
    """Claim one resume execution while allowing idempotent completed replays."""
    updated = copy.deepcopy(dict(proposal))
    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    proposal_status = str(updated.get('status') or '').strip().lower()
    if proposal_status not in {'approved', 'declined'}:
        raise CapabilityChoiceError(
            'this capability proposal cannot be resumed',
            code=f'proposal_{proposal_status or "invalid"}',
        )
    resume = updated.get('resume') if isinstance(updated.get('resume'), Mapping) else {}
    resume_status = str(resume.get('status') or 'not_requested').strip().lower()
    if resume_status == 'completed':
        return updated, True
    if resume_status == 'running':
        lease_expires_at = _parse_timestamp(resume.get('lease_expires_at'))
        if lease_expires_at and current_time < lease_expires_at:
            raise CapabilityChoiceError(
                'this capability decision is already being resumed',
                code='resume_in_progress',
            )
    if resume_status not in {'pending', 'failed', 'running'}:
        raise CapabilityChoiceError(
            'this capability decision is not ready to resume',
            code='resume_not_ready',
        )
    execution_id = str(execution_id or uuid.uuid4())
    child_run_id = str(child_run_id or uuid.uuid4())
    updated['resume'] = {
        'status': 'running',
        'execution_id': execution_id,
        'child_run_id': child_run_id,
        'assistant_message_id': None,
        'claimed_at': current_time.isoformat(),
        'lease_expires_at': (
            current_time + timedelta(seconds=CAPABILITY_RESUME_LEASE_SECONDS)
        ).isoformat(),
        'completed_at': None,
        'error_type': None,
    }
    return updated, False


def complete_capability_choice_resume(
    proposal,
    *,
    execution_id,
    assistant_message_id,
    now=None,
):
    """Mark the exact claimed resume execution complete."""
    updated = copy.deepcopy(dict(proposal))
    resume = updated.get('resume') if isinstance(updated.get('resume'), Mapping) else {}
    if resume.get('status') == 'completed':
        if resume.get('assistant_message_id') == assistant_message_id:
            return updated, True
        raise CapabilityChoiceError('resume already completed', code='resume_completed')
    if resume.get('status') != 'running' or resume.get('execution_id') != execution_id:
        raise CapabilityChoiceError('resume claim does not match', code='resume_claim_mismatch')
    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    updated['resume'] = {
        **dict(resume),
        'status': 'completed',
        'assistant_message_id': _normalize_identifier(
            assistant_message_id,
            'assistant_message_id',
        ),
        'completed_at': current_time.isoformat(),
        'lease_expires_at': None,
        'error_type': None,
    }
    return updated, False


def fail_capability_choice_resume(proposal, *, execution_id, error_type, now=None):
    """Release the exact resume claim for an authorized retry after failure."""
    updated = copy.deepcopy(dict(proposal))
    resume = updated.get('resume') if isinstance(updated.get('resume'), Mapping) else {}
    if resume.get('status') != 'running' or resume.get('execution_id') != execution_id:
        return updated, True
    current_time = now or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    updated['resume'] = {
        **dict(resume),
        'status': 'failed',
        'lease_expires_at': None,
        'completed_at': current_time.isoformat(),
        'error_type': re.sub(
            r'[^a-z0-9_]+',
            '_',
            str(error_type or 'resume_failed').strip().lower(),
        )[:120],
    }
    return updated, False


def build_capability_provenance(
    *,
    selection_snapshot,
    capability_inventory,
    proposal=None,
    decisions=None,
    effective_capabilities=None,
):
    """Keep submitted, proposed, decided, and effective capability facts separate."""
    return {
        'version': CAPABILITY_PROVENANCE_VERSION,
        'selection_snapshot': copy.deepcopy(dict(selection_snapshot or {})),
        'capability_inventory': copy.deepcopy(dict(capability_inventory or {})),
        'proposed_capabilities': (
            copy.deepcopy(dict(proposal)) if isinstance(proposal, Mapping) else None
        ),
        'capability_decisions': [
            copy.deepcopy(dict(decision))
            for decision in (decisions or [])
            if isinstance(decision, Mapping)
        ],
        'effective_capabilities': [
            {
                'id': str(item.get('id') or '').strip(),
                'origin': str(item.get('origin') or '').strip(),
                'required': bool(item.get('required', True)),
            }
            for item in (effective_capabilities or [])
            if isinstance(item, Mapping) and str(item.get('id') or '').strip()
        ],
    }