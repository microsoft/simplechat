# functions_chat_capability_choices.py
"""Durable capability proposal, decision, and resume contracts."""

import copy
import hashlib
import hmac
import json
import re
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

from functions_chat_capabilities import (
    CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID,
    PLANNER_DOCUMENT_ACTION_CAPABILITY_IDS,
    PLANNER_IMAGE_CAPABILITY_ID,
    PLANNER_RETRIEVAL_CAPABILITY_IDS,
    expand_governed_capability_baseline_ids,
    get_capability_option_revalidation_error,
)


CAPABILITY_CHOICE_VERSION = 3
CAPABILITY_PROVENANCE_VERSION = 2
APPROVED_USER_TURN_GOAL_VERSION = 1
MAX_APPROVED_GOAL_SOURCE_TURNS = 3
MAX_APPROVED_GOAL_DISPLAY_CHARS = 240
MAX_CLIENT_CLARIFICATION_OPTIONS = 6
MAX_CLIENT_CLARIFICATION_OPTION_CHARS = 120
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

_CLIENT_PRIVATE_METADATA_KEYS = frozenset({
    'capability_resume_request',
})


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


def _normalize_labels(values, *, max_items=8):
    normalized = []
    for value in values or []:
        label = ' '.join(str(value or '').split())[:120]
        if label and label not in normalized:
            normalized.append(label)
        if len(normalized) >= max_items:
            break
    return normalized


def _goal_source_record(message, *, conversation_id):
    if not isinstance(message, Mapping):
        raise CapabilityChoiceError(
            'goal source message is invalid',
            code='goal_source_invalid',
        )
    message_id = _normalize_identifier(message.get('id'), 'source_user_message_id')
    if (
        message.get('conversation_id') != conversation_id
        or message.get('role') != 'user'
    ):
        raise CapabilityChoiceError(
            'goal source message is outside the authorized conversation',
            code='goal_source_invalid',
        )
    metadata = message.get('metadata') if isinstance(message.get('metadata'), Mapping) else {}
    thread_info = (
        metadata.get('thread_info')
        if isinstance(metadata.get('thread_info'), Mapping)
        else {}
    )
    if (
        metadata.get('is_deleted') is True
        or metadata.get('masked') is True
        or bool(metadata.get('masked_ranges') or [])
        or metadata.get('is_generated_chat_artifact') is True
        or thread_info.get('active_thread') is False
    ):
        raise CapabilityChoiceError(
            'goal source message is no longer active',
            code='goal_source_inactive',
        )
    thread_id = str(thread_info.get('thread_id') or '').strip()
    if not thread_id:
        raise CapabilityChoiceError(
            'goal source message has no active thread binding',
            code='goal_source_thread_invalid',
        )
    content = str(message.get('content') or '').strip()
    if not content:
        raise CapabilityChoiceError(
            'goal source message is empty',
            code='goal_source_invalid',
        )
    return {
        'message_id': message_id,
        'content_hash': hashlib.sha256(content.encode('utf-8')).hexdigest(),
        'thread_id': thread_id,
        'previous_thread_id': str(
            thread_info.get('previous_thread_id') or ''
        ).strip(),
        'thread_attempt': int(thread_info.get('thread_attempt') or 1),
    }, content


def build_approved_user_turn_goal(
    source_user_messages,
    *,
    conversation_id,
    current_user_message_id,
    display_summary=None,
    approved_by_option_id=None,
    approved_sensitive_input_types=None,
):
    """Build a bounded server-owned goal from exact active user documents."""
    conversation_id = _normalize_identifier(conversation_id, 'conversation_id')
    current_user_message_id = _normalize_identifier(
        current_user_message_id,
        'current_user_message_id',
    )
    raw_messages = (
        source_user_messages
        if isinstance(source_user_messages, list)
        else []
    )
    if not 1 <= len(raw_messages) <= MAX_APPROVED_GOAL_SOURCE_TURNS:
        raise CapabilityChoiceError(
            'approved goal must contain one to three user turns',
            code='goal_source_count_invalid',
        )
    source_records = []
    source_contents = []
    for message in raw_messages:
        source_record, content = _goal_source_record(
            message,
            conversation_id=conversation_id,
        )
        if source_record['message_id'] in {
            item['message_id']
            for item in source_records
        }:
            raise CapabilityChoiceError(
                'approved goal source turns must be unique',
                code='goal_source_duplicate',
            )
        source_records.append(source_record)
        source_contents.append(content)
    source_ids = [record['message_id'] for record in source_records]
    if current_user_message_id not in source_ids:
        raise CapabilityChoiceError(
            'approved goal must include the current user turn',
            code='goal_current_turn_missing',
        )
    combined_user_text = '\n'.join(source_contents)
    contextual_query = ' '.join(combined_user_text.split())[:1000]
    minimized = build_minimized_external_query(
        combined_user_text,
        approved_sensitive_input_types=approved_sensitive_input_types,
    )
    prior_user_turn_included = any(
        message_id != current_user_message_id
        for message_id in source_ids
    )
    if display_summary is None:
        summary_source = next(
            (
                content
                for message_id, content in zip(source_ids, source_contents)
                if message_id != current_user_message_id
            ),
            source_contents[-1],
        )
        display_summary = ' '.join(summary_source.split())
    normalized_summary = ' '.join(str(display_summary or '').split())[
        :MAX_APPROVED_GOAL_DISPLAY_CHARS
    ]
    return {
        'version': APPROVED_USER_TURN_GOAL_VERSION,
        'source': 'approved_user_turn_goal',
        'conversation_id': conversation_id,
        'current_user_message_id': current_user_message_id,
        'source_user_message_ids': source_ids,
        'source_turn_lineage': source_records,
        'display_summary': normalized_summary,
        'contextual_query': contextual_query,
        'external_query': minimized['query'],
        'omitted_sensitive_input_types': list(
            minimized['omitted_sensitive_input_types']
        ),
        'prior_user_turn_included': prior_user_turn_included,
        'assistant_text_included': False,
        'workspace_content_included': False,
        'approved_by_option_id': (
            _normalize_identifier(approved_by_option_id, 'approved_by_option_id')
            if approved_by_option_id
            else None
        ),
    }


def rebuild_approved_user_turn_goal(
    stored_goal,
    source_user_messages,
    *,
    approved_sensitive_input_types=None,
):
    """Rebuild a stored goal from exact documents and reject changed lineage."""
    if not isinstance(stored_goal, Mapping) or (
        stored_goal.get('version') != APPROVED_USER_TURN_GOAL_VERSION
        or stored_goal.get('source') != 'approved_user_turn_goal'
    ):
        raise CapabilityChoiceError(
            'approved goal metadata is invalid',
            code='goal_metadata_invalid',
        )
    rebuilt = build_approved_user_turn_goal(
        source_user_messages,
        conversation_id=stored_goal.get('conversation_id'),
        current_user_message_id=stored_goal.get('current_user_message_id'),
        display_summary=stored_goal.get('display_summary'),
        approved_by_option_id=stored_goal.get('approved_by_option_id'),
        approved_sensitive_input_types=approved_sensitive_input_types,
    )
    expected_ids = list(stored_goal.get('source_user_message_ids') or [])
    if rebuilt['source_user_message_ids'] != expected_ids:
        raise CapabilityChoiceError(
            'approved goal source turns changed',
            code='goal_source_changed',
        )
    expected_lineage = stored_goal.get('source_turn_lineage') or []
    if len(expected_lineage) != len(rebuilt['source_turn_lineage']):
        raise CapabilityChoiceError(
            'approved goal lineage changed',
            code='goal_source_changed',
        )
    for expected, actual in zip(expected_lineage, rebuilt['source_turn_lineage']):
        expected_hash = str(expected.get('content_hash') or '') if isinstance(expected, Mapping) else ''
        actual_hash = str(actual.get('content_hash') or '')
        expected_binding = {
            key: expected.get(key)
            for key in (
                'message_id',
                'thread_id',
                'previous_thread_id',
                'thread_attempt',
            )
        } if isinstance(expected, Mapping) else {}
        actual_binding = {
            key: actual.get(key)
            for key in expected_binding
        }
        if (
            not expected_hash
            or not hmac.compare_digest(expected_hash, actual_hash)
            or expected_binding != actual_binding
        ):
            raise CapabilityChoiceError(
                'approved goal source content or lineage changed',
                code='goal_source_changed',
            )
    return rebuilt


def project_chat_metadata_for_client(metadata):
    """Remove server-only execution and contextual lineage from client metadata."""
    def project(value, key_name=None):
        if key_name == 'chat_clarification' and isinstance(value, Mapping):
            return {
                'version': value.get('version'),
                'code': str(value.get('code') or '')[:64],
                'question': str(value.get('question') or '')[:240],
                'status': str(value.get('status') or '')[:32],
                'options': [
                    str(option or '')[:MAX_CLIENT_CLARIFICATION_OPTION_CHARS]
                    for option in value.get('options') or []
                    if str(option or '').strip()
                ][:MAX_CLIENT_CLARIFICATION_OPTIONS],
                'created_at': value.get('created_at'),
                'expires_at': value.get('expires_at'),
                'resolved_at': value.get('resolved_at'),
                'response_mode': value.get('response_mode'),
            }
        if key_name == 'clarification_response' and isinstance(value, Mapping):
            return {
                'version': value.get('version'),
                'code': str(value.get('code') or '')[:64],
                'status': str(value.get('status') or '')[:32],
                'response_mode': str(value.get('response_mode') or '')[:32],
                'idempotent': value.get('idempotent') is True,
            }
        if isinstance(value, Mapping):
            return {
                str(key): project(item, str(key))
                for key, item in value.items()
                if (
                    not str(key).startswith('_')
                    and str(key) not in _CLIENT_PRIVATE_METADATA_KEYS
                )
            }
        if isinstance(value, list):
            return [project(item) for item in value]
        return copy.deepcopy(value)

    return project(metadata if isinstance(metadata, Mapping) else {})


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
        if option_kind not in {'capability', 'agent', 'context', 'continue'}:
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
        elif option_kind == 'context':
            if (
                capability_ids
                or not effective_ids
                or agent_ref
                or raw_option.get('external_data') is not True
                or raw_option.get('read_only') is not True
            ):
                raise CapabilityChoiceError(
                    'context options must bind read-only external capabilities',
                    code='invalid_context_option',
                )
        elif not capability_ids:
            raise CapabilityChoiceError(
                'capability options must name at least one capability',
                code='missing_option_capability',
            )
        elif not set(capability_ids).issubset(effective_ids):
            raise CapabilityChoiceError(
                'effective capabilities must include every approved capability',
                code='invalid_option_effective_capabilities',
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
            'read_only': raw_option.get('read_only') is True,
            'risk_class': str(raw_option.get('risk_class') or '').strip().lower()[:40],
            'data_sensitivity': str(
                raw_option.get('data_sensitivity') or ''
            ).strip().lower()[:40],
            'external_query_mode': str(
                raw_option.get('external_query_mode') or 'minimized'
            ).strip().lower()[:40],
            'sensitive_input_types': _normalize_identifiers(
                raw_option.get('sensitive_input_types'),
                max_items=8,
            ),
        }
        if option_kind == 'context':
            normalized_option['approval_scope'] = 'prior_user_goal_egress'
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


def build_minimized_external_query(
    user_message,
    *,
    include_sensitive_inputs=False,
    approved_sensitive_input_types=None,
):
    """Build a current-message-only query while omitting unnecessary personal data."""
    query = ' '.join(str(user_message or '').split())
    omitted_types = []
    approved_types = {
        str(value or '').strip().lower()
        for value in (approved_sensitive_input_types or [])
        if str(value or '').strip().lower() == 'street_address'
    }
    if include_sensitive_inputs:
        approved_types.add('street_address')
    replacements = (
        (STREET_ADDRESS_PATTERN, 'street_address'),
        (EMAIL_PATTERN, 'email_address'),
        (PHONE_PATTERN, 'phone_number'),
        (ACCOUNT_IDENTIFIER_PATTERN, 'account_identifier'),
    )
    for pattern, sensitive_type in replacements:
        if sensitive_type in approved_types:
            continue
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


def resolve_external_retrieval_message(request_data, user_message):
    """Preserve an explicitly empty server-minimized query without raw fallback."""
    source = request_data if isinstance(request_data, Mapping) else {}
    if '_server_external_query' in source:
        return str(source.get('_server_external_query') or '').strip()
    return str(user_message or '').strip()


def build_resumed_external_query(
    user_message,
    execution_capability_ids,
    *,
    external_query_mode='minimized',
    approved_sensitive_input_types=None,
):
    """Build a marker value when resumed Web Search or Deep Research will execute."""
    execution_ids = {
        str(capability_id or '').strip().lower()
        for capability_id in execution_capability_ids or []
        if str(capability_id or '').strip()
    }
    if not execution_ids.intersection({'web_search', 'deep_research'}):
        return None
    external_query = build_minimized_external_query(
        user_message,
        approved_sensitive_input_types=(
            approved_sensitive_input_types
            if str(external_query_mode or '').strip().lower()
            == 'include_approved_sensitive_inputs'
            else []
        ),
    )
    return external_query['query']


def add_sensitive_external_query_options(
    recommendation,
    user_message,
    *,
    max_actionable_options=None,
):
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
        if (
            normalized_option.get('external_data')
            and (
                normalized_option.get('capability_ids')
                or normalized_option.get('kind') == 'context'
            )
        ):
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
    if max_actionable_options is not None:
        try:
            option_limit = max(1, min(int(max_actionable_options), 11))
        except (TypeError, ValueError):
            option_limit = 1
        continue_options = [
            option
            for option in updated_options
            if option.get('id') == CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID
        ]
        actionable_options = [
            option
            for option in updated_options
            if option.get('id') != CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID
        ]
        recommended_option_id = updated.get('recommended_option_id')
        actionable_options.sort(
            key=lambda option: option.get('id') != recommended_option_id
        )
        updated['options'] = (
            actionable_options[:option_limit]
            + continue_options[:1]
        )
    updated['sensitive_data_notice_required'] = True
    return updated


def build_capability_choice_proposal(
    recommendation,
    *,
    run_id,
    conversation_id,
    user_message_id,
    assistant_message_id=None,
    approved_user_turn_goal=None,
    capability_inventory=None,
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
    private_goal = (
        copy.deepcopy(dict(approved_user_turn_goal))
        if isinstance(approved_user_turn_goal, Mapping)
        else None
    )
    raw_options = copy.deepcopy(list(recommendation.get('options') or []))
    if private_goal:
        if (
            private_goal.get('version') != APPROVED_USER_TURN_GOAL_VERSION
            or private_goal.get('source') != 'approved_user_turn_goal'
            or private_goal.get('conversation_id') != conversation_id
            or private_goal.get('current_user_message_id') != user_message_id
            or private_goal.get('prior_user_turn_included') is not True
        ):
            raise CapabilityChoiceError(
                'approved prior-user goal is invalid for this proposal',
                code='goal_metadata_invalid',
            )
        for raw_option in raw_options:
            if (
                isinstance(raw_option, Mapping)
                and raw_option.get('external_data') is True
                and raw_option.get('id') != CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID
            ):
                raw_option['prior_goal_included'] = True
                raw_option['goal_source_count'] = len(
                    private_goal.get('source_user_message_ids') or []
                )
                raw_option['goal_display_summary'] = private_goal.get(
                    'display_summary'
                )
    options = _normalize_options(raw_options)
    if private_goal and not any(
        option.get('kind') != 'continue'
        for option in options
    ):
        raise CapabilityChoiceError(
            'contextual user goal requires an actionable option',
            code='goal_action_option_missing',
        )
    option_ids = {option['id'] for option in options}
    external_capability_ids = sorted({
        str(entry.get('id') or '').strip()
        for entry in (
            capability_inventory.get('capabilities')
            if isinstance(capability_inventory, Mapping)
            else []
        ) or []
        if isinstance(entry, Mapping)
        and entry.get('external_data') is True
        and str(entry.get('id') or '').strip()
    })[:8]
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
        'recommendation_source': (
            'planner'
            if recommendation.get('source') == 'planner'
            else 'deterministic'
        ),
        'requirement_ids': _normalize_identifiers(recommendation.get('requirement_ids')),
        'reason_codes': _normalize_identifiers(recommendation.get('reason_codes')),
        'selected_context_labels': _normalize_labels(
            recommendation.get('selected_context_labels')
        ),
        'sensitive_data_notice_required': bool(
            recommendation.get('sensitive_data_notice_required')
        ),
        'prior_goal_included': bool(private_goal),
        'goal_source_count': min(
            len(private_goal.get('source_user_message_ids') or [])
            if private_goal
            else 0,
            MAX_APPROVED_GOAL_SOURCE_TURNS,
        ),
        'goal_display_summary': (
            str(private_goal.get('display_summary') or '')[
                :MAX_APPROVED_GOAL_DISPLAY_CHARS
            ]
            if private_goal
            else ''
        ),
        '_external_capability_ids': external_capability_ids,
        '_approved_user_turn_goal': private_goal,
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
    decision_status = (
        'declined'
        if option.get('kind') == 'continue'
        else 'approved'
    )
    updated['status'] = decision_status
    decision = {
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
    if updated.get('prior_goal_included') is True:
        decision.update({
            'approval_scope': (
                'prior_user_goal_egress_declined'
                if decision_status == 'declined'
                else option.get('approval_scope') or 'contextual_capability'
            ),
            'contextual_goal_included': decision_status == 'approved',
            'prior_goal_included': bool(
                decision_status == 'approved'
                and option.get('external_data') is True
            ),
            'goal_source_count': (
                updated.get('goal_source_count', 0)
                if decision_status == 'approved'
                else 0
            ),
        })
    updated['decision'] = decision
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
    private_goal = updated.get('_approved_user_turn_goal')
    if isinstance(private_goal, Mapping):
        private_goal = copy.deepcopy(dict(private_goal))
        private_goal['approved_by_option_id'] = (
            normalized_option_id
            if decision_status == 'approved'
            else None
        )
        updated['_approved_user_turn_goal'] = private_goal
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
    approved_option = get_capability_choice_option(
        proposal,
        decision.get('option_id'),
    )
    if not approved_option:
        raise CapabilityChoiceError(
            'the approved option is no longer present in the proposal',
            code='capability_option_invalid',
        )
    if (
        set(approved_option.get('capability_ids') or []) != approved_capability_ids
        or set(approved_option.get('effective_capability_ids') or [])
        != effective_capability_ids
        or str(approved_option.get('agent_ref') or '').strip()
        != str(decision.get('agent_ref') or '').strip()
    ):
        raise CapabilityChoiceError(
            'the approved decision no longer matches its server-authored option',
            code='capability_decision_mismatch',
        )
    private_goal = proposal.get('_approved_user_turn_goal')
    if decision.get('contextual_goal_included') is True:
        if not (
            isinstance(private_goal, Mapping)
            and private_goal.get('approved_by_option_id')
            == decision.get('option_id')
        ):
            raise CapabilityChoiceError(
                'approved prior-user goal no longer matches the option decision',
                code='goal_approval_mismatch',
            )
    if (
        decision.get('prior_goal_included') is True
        and approved_option.get('external_data') is not True
    ):
        raise CapabilityChoiceError(
            'approved external goal no longer matches an external option',
            code='goal_approval_mismatch',
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
            entry.get('state') == 'unselected'
            and entry.get('discoverable') is not True
        ):
            raise CapabilityChoiceError(
                'an approved capability is no longer discoverable',
                code='capability_policy_blocked',
            )
        if entry.get('input_ready') is not True:
            raise CapabilityChoiceError(
                'an approved capability no longer has its required input',
                code='capability_input_unavailable',
            )
        if (
            str(approved_option.get('id') or '').startswith('plan:')
            and entry.get('read_only') is not True
        ):
            raise CapabilityChoiceError(
                'an approved capability is no longer read only',
                code='capability_policy_blocked',
            )
    bundle_error = get_capability_option_revalidation_error(
        approved_option,
        inventory,
    )
    if bundle_error:
        raise CapabilityChoiceError(
            'the approved capability plan no longer matches current policy',
            code=bundle_error,
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


def revalidate_capability_execution_baseline(
    inventory,
    *,
    selected_capability_ids=None,
    prior_effective_capabilities=None,
    automatic_capability_root_ids=None,
    automatic_capability_effective_ids=None,
    baseline_error_code=None,
):
    """Revalidate selected mandates and prior automatic discovery as server state."""
    if str(baseline_error_code or '').strip():
        raise CapabilityChoiceError(
            'the submitted capability baseline is no longer authorized',
            code=str(baseline_error_code).strip()[:120],
        )
    inventory_entries = (
        inventory.get('capabilities')
        if isinstance(inventory, Mapping)
        else None
    )
    entries_by_id = {
        str(entry.get('id') or '').strip(): entry
        for entry in (inventory_entries or [])
        if isinstance(entry, Mapping) and str(entry.get('id') or '').strip()
    }

    def require_entry(capability_id):
        entry = entries_by_id.get(capability_id)
        if not entry:
            raise CapabilityChoiceError(
                'a baseline capability is no longer in the governed inventory',
                code='capability_missing',
            )
        return entry

    selected_root_ids = []
    for raw_capability_id in selected_capability_ids or []:
        capability_id = str(raw_capability_id or '').strip()
        if not capability_id:
            continue
        selected_root_ids.append(capability_id)
        entry = require_entry(capability_id)
        state = str(entry.get('state') or '').strip().lower()
        if state != 'selected':
            code = (
                f'capability_{state}'
                if state in {'unavailable', 'unauthorized', 'policy_blocked'}
                else 'capability_selection_changed'
            )
            raise CapabilityChoiceError(
                'a selected capability is no longer available or authorized',
                code=code,
            )
        if entry.get('input_ready') is not True:
            raise CapabilityChoiceError(
                'a selected capability no longer has its required input',
                code='capability_input_unavailable',
            )

    try:
        expanded_selected_ids = expand_governed_capability_baseline_ids(
            inventory,
            selected_root_ids,
        )
    except ValueError as bundle_error:
        raise CapabilityChoiceError(
            'a selected capability bundle is no longer valid',
            code='capability_bundle_changed',
        ) from bundle_error
    for capability_id in expanded_selected_ids:
        if capability_id in selected_root_ids:
            continue
        entry = require_entry(capability_id)
        state = str(entry.get('state') or '').strip().lower()
        if state not in {'selected', 'unselected'}:
            code = (
                f'capability_{state}'
                if state in {'unavailable', 'unauthorized', 'policy_blocked'}
                else 'capability_bundle_changed'
            )
            raise CapabilityChoiceError(
                'a selected capability dependency is no longer authorized',
                code=code,
            )
        if entry.get('input_ready') is not True:
            raise CapabilityChoiceError(
                'a selected capability dependency no longer has its required input',
                code='capability_input_unavailable',
            )
        if entry.get('read_only') is not True:
            raise CapabilityChoiceError(
                'a selected capability dependency is no longer read-only',
                code='capability_policy_blocked',
            )

    prior_selection_ids = {
        str(item.get('id') or '').strip()
        for item in prior_effective_capabilities or []
        if isinstance(item, Mapping)
        and str(item.get('origin') or '').strip() == 'selection'
        and str(item.get('id') or '').strip()
    }
    if prior_selection_ids and prior_selection_ids != set(expanded_selected_ids):
        raise CapabilityChoiceError(
            'the selected capability bundle has changed',
            code='capability_bundle_changed',
        )

    prior_automatic_ids = {
        str(item.get('id') or '').strip()
        for item in prior_effective_capabilities or []
        if isinstance(item, Mapping)
        and str(item.get('id') or '').strip()
        and str(item.get('origin') or '').strip() == 'discovery_auto'
    }
    has_bound_automatic_roots = automatic_capability_root_ids is not None
    if not has_bound_automatic_roots and len(prior_automatic_ids) > 1:
        raise CapabilityChoiceError(
            'the legacy automatic capability bundle cannot be reconstructed safely',
            code='capability_bundle_changed',
        )
    automatic_root_ids = {
        str(capability_id or '').strip()
        for capability_id in (
            automatic_capability_root_ids
            if has_bound_automatic_roots
            else prior_automatic_ids
        ) or []
        if str(capability_id or '').strip()
    }
    expected_automatic_ids = {
        str(capability_id or '').strip()
        for capability_id in (
            automatic_capability_effective_ids
            if automatic_capability_effective_ids is not None
            else prior_automatic_ids
        ) or []
        if str(capability_id or '').strip()
    }
    try:
        expanded_automatic_ids = expand_governed_capability_baseline_ids(
            inventory,
            automatic_root_ids,
        )
    except ValueError as bundle_error:
        raise CapabilityChoiceError(
            'an automatically discovered capability bundle is no longer valid',
            code='capability_bundle_changed',
        ) from bundle_error
    if set(expanded_automatic_ids) != expected_automatic_ids:
        raise CapabilityChoiceError(
            'the automatically discovered capability bundle has changed',
            code='capability_bundle_changed',
        )
    for capability_id in expanded_automatic_ids:
        entry = require_entry(capability_id)
        state = str(entry.get('state') or '').strip().lower()
        if state == 'selected':
            if entry.get('input_ready') is not True:
                raise CapabilityChoiceError(
                    'an automatic bundle dependency no longer has its required input',
                    code='capability_input_unavailable',
                )
            if entry.get('read_only') is not True:
                raise CapabilityChoiceError(
                    'an automatic bundle dependency is no longer read-only',
                    code='capability_policy_blocked',
                )
            continue
        if state != 'unselected':
            code = (
                f'capability_{state}'
                if state in {'unavailable', 'unauthorized', 'policy_blocked'}
                else 'capability_policy_blocked'
            )
            raise CapabilityChoiceError(
                'an automatically discovered capability is no longer eligible',
                code=code,
            )
        if entry.get('input_ready') is not True:
            raise CapabilityChoiceError(
                'an automatically discovered capability no longer has its required input',
                code='capability_input_unavailable',
            )
        if not (
            entry.get('discoverable') is True
            and entry.get('auto_use_allowed') is True
            and entry.get('read_only') is True
        ):
            raise CapabilityChoiceError(
                'an automatically discovered capability is no longer policy approved',
                code='capability_policy_blocked',
            )
    return True


def build_decline_aware_execution_baseline(
    proposal,
    refreshed_inventory,
    *,
    selected_capability_ids=None,
    prior_effective_capabilities=None,
    automatic_capability_root_ids=None,
    automatic_capability_effective_ids=None,
):
    """Exclude only proposal-bound external capabilities after explicit decline."""
    decision = (
        proposal.get('decision')
        if isinstance(proposal, Mapping)
        and isinstance(proposal.get('decision'), Mapping)
        else {}
    )
    if decision.get('approval_scope') != 'prior_user_goal_egress_declined':
        return {
            'selected_capability_ids': selected_capability_ids,
            'prior_effective_capabilities': prior_effective_capabilities,
            'automatic_capability_root_ids': automatic_capability_root_ids,
            'automatic_capability_effective_ids': (
                automatic_capability_effective_ids
            ),
        }
    external_capability_ids = {
        str(capability_id or '').strip()
        for capability_id in proposal.get('_external_capability_ids') or []
        if str(capability_id or '').strip()
    }
    if not external_capability_ids:
        external_capability_ids = {
            str(entry.get('id') or '').strip()
            for entry in (
                refreshed_inventory.get('capabilities')
                if isinstance(refreshed_inventory, Mapping)
                else []
            ) or []
            if isinstance(entry, Mapping)
            and entry.get('external_data') is True
            and str(entry.get('id') or '').strip()
        }

    def filtered_ids(values):
        if values is None:
            return None
        return [
            capability_id
            for capability_id in values
            if str(capability_id or '').strip() not in external_capability_ids
        ]

    return {
        'selected_capability_ids': filtered_ids(selected_capability_ids),
        'prior_effective_capabilities': [
            item
            for item in prior_effective_capabilities or []
            if not (
                isinstance(item, Mapping)
                and str(item.get('id') or '').strip()
                in external_capability_ids
            )
        ],
        'automatic_capability_root_ids': filtered_ids(
            automatic_capability_root_ids
        ),
        'automatic_capability_effective_ids': filtered_ids(
            automatic_capability_effective_ids
        ),
    }


def revalidate_capability_execution_compatibility(
    proposal,
    *,
    selected_capability_ids=None,
    prior_effective_capabilities=None,
    selected_agent_present=False,
):
    """Reject persisted combinations unsupported by compatibility executors."""
    decision = proposal.get('decision') if isinstance(proposal, Mapping) else None
    if not isinstance(decision, Mapping) or decision.get('status') == 'declined':
        return True
    execution_ids = {
        str(capability_id or '').strip().lower()
        for capability_id in selected_capability_ids or []
        if str(capability_id or '').strip()
    }
    execution_ids.update(
        str(item.get('id') or '').strip().lower()
        for item in prior_effective_capabilities or []
        if isinstance(item, Mapping)
        and str(item.get('origin') or '').strip() == 'discovery_auto'
        and str(item.get('id') or '').strip()
    )
    execution_ids.update(
        str(capability_id or '').strip().lower()
        for capability_id in decision.get('effective_capability_ids') or []
        if str(capability_id or '').strip()
    )
    if selected_agent_present or str(decision.get('agent_ref') or '').strip():
        execution_ids.add('selected_agent')
    if (
        execution_ids.intersection(PLANNER_DOCUMENT_ACTION_CAPABILITY_IDS)
        and execution_ids.intersection(PLANNER_RETRIEVAL_CAPABILITY_IDS)
    ) or (
        PLANNER_IMAGE_CAPABILITY_ID in execution_ids
        and len(execution_ids) > 1
    ):
        raise CapabilityChoiceError(
            'this capability combination is not supported by the current executor',
            code='capability_combination_unsupported',
        )
    return True


def build_capability_resume_origins(
    capability_inventory,
    effective_capability_ids,
    *,
    prior_effective_capabilities=None,
    automatic_capability_root_ids=None,
    approved_agent_ref=None,
):
    """Rebuild execution origins without rewriting selected mandates as approvals."""
    selected_root_ids = {
        str(entry.get('id') or '').strip()
        for entry in (
            capability_inventory.get('capabilities')
            if isinstance(capability_inventory, Mapping)
            else []
        ) or []
        if isinstance(entry, Mapping)
        and entry.get('state') == 'selected'
        and str(entry.get('id') or '').strip()
    }
    entries_by_id = {
        str(entry.get('id') or '').strip(): entry
        for entry in (
            capability_inventory.get('capabilities')
            if isinstance(capability_inventory, Mapping)
            else []
        ) or []
        if isinstance(entry, Mapping) and str(entry.get('id') or '').strip()
    }
    try:
        selected_ids = set(
            expand_governed_capability_baseline_ids(
                capability_inventory,
                selected_root_ids,
            )
        )
    except ValueError:
        selected_ids = selected_root_ids
    origins = {
        capability_id: 'selection'
        for capability_id in selected_ids
    }
    prior_automatic_ids = {
        str(item.get('id') or '').strip()
        for item in prior_effective_capabilities or []
        if isinstance(item, Mapping)
        and str(item.get('origin') or '').strip() == 'discovery_auto'
        and str(item.get('id') or '').strip()
    }
    automatic_root_ids = {
        str(capability_id or '').strip()
        for capability_id in (
            automatic_capability_root_ids
            if automatic_capability_root_ids is not None
            else prior_automatic_ids
        ) or []
        if str(capability_id or '').strip()
    }
    try:
        automatic_ids = expand_governed_capability_baseline_ids(
            capability_inventory,
            automatic_root_ids,
        )
    except ValueError:
        automatic_ids = list(automatic_root_ids)
    for capability_id in automatic_ids:
        entry = entries_by_id.get(capability_id)
        if (
            entry
            and entry.get('state') == 'unselected'
            and entry.get('discoverable') is True
            and entry.get('auto_use_allowed') is True
            and entry.get('input_ready') is True
            and entry.get('read_only') is True
            and capability_id not in origins
        ):
            origins[capability_id] = 'discovery_auto'
    for raw_capability_id in effective_capability_ids or []:
        capability_id = str(raw_capability_id or '').strip()
        if not capability_id:
            continue
        if capability_id not in origins:
            origins[capability_id] = 'discovery_approved'
    if str(approved_agent_ref or '').strip():
        origins['selected_agent'] = 'discovery_approved'
    return origins


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
    if (
        resume.get('status') not in {'running', 'failed'}
        or resume.get('execution_id') != execution_id
    ):
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
    automatic_capability_root_ids=None,
    automatic_capability_effective_ids=None,
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
        'automatic_capability_root_ids': list(dict.fromkeys(
            str(capability_id or '').strip()
            for capability_id in (automatic_capability_root_ids or [])
            if str(capability_id or '').strip()
        ))[:8],
        'automatic_capability_effective_ids': list(dict.fromkeys(
            str(capability_id or '').strip()
            for capability_id in (automatic_capability_effective_ids or [])
            if str(capability_id or '').strip()
        ))[:8],
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