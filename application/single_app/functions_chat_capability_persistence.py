# functions_chat_capability_persistence.py
"""Conditional persistence helpers for durable chat capability choices."""

import copy
from collections.abc import Mapping
from datetime import datetime, timezone

from azure.core import MatchConditions

from functions_chat_capability_choices import (
    CapabilityChoiceError,
    apply_capability_choice_decision,
    build_decline_aware_execution_baseline,
    capability_choice_is_expired,
    claim_capability_choice_resume,
    complete_capability_choice_resume,
    fail_capability_choice_resume,
    revalidate_capability_choice,
    revalidate_capability_execution_baseline,
    revalidate_capability_execution_compatibility,
)


CAPABILITY_PROPOSAL_METADATA_KEY = 'capability_proposal'
CAPABILITY_PROVENANCE_METADATA_KEY = 'capability_provenance'
MAX_CONDITIONAL_WRITE_ATTEMPTS = 3


def _normalize_identifier(value, field_name):
    normalized = str(value or '').strip()
    if not normalized or len(normalized) > 200:
        raise CapabilityChoiceError(f'{field_name} is required', code=f'invalid_{field_name}')
    return normalized


def read_capability_proposal_message(container, *, conversation_id, proposal_id):
    """Read and validate an exact assistant proposal from its conversation partition."""
    conversation_id = _normalize_identifier(conversation_id, 'conversation_id')
    proposal_id = _normalize_identifier(proposal_id, 'proposal_id')
    message = container.read_item(item=proposal_id, partition_key=conversation_id)
    if message.get('conversation_id') != conversation_id:
        raise CapabilityChoiceError(
            'proposal does not belong to this conversation',
            code='proposal_conversation_mismatch',
        )
    if message.get('role') != 'assistant':
        raise CapabilityChoiceError(
            'capability proposal must be an assistant message',
            code='proposal_role_invalid',
        )
    metadata = message.get('metadata') if isinstance(message.get('metadata'), Mapping) else {}
    proposal = metadata.get(CAPABILITY_PROPOSAL_METADATA_KEY)
    if not isinstance(proposal, Mapping):
        raise CapabilityChoiceError(
            'capability proposal metadata is missing',
            code='proposal_metadata_missing',
        )
    if proposal.get('proposal_id') != proposal_id:
        raise CapabilityChoiceError(
            'proposal identifier does not match the stored message',
            code='proposal_id_mismatch',
        )
    if proposal.get('conversation_id') != conversation_id:
        raise CapabilityChoiceError(
            'stored proposal conversation does not match',
            code='proposal_conversation_mismatch',
        )
    return message, copy.deepcopy(dict(proposal))


def _replace_proposal_message(container, message, proposal):
    updated_message = copy.deepcopy(dict(message))
    updated_metadata = (
        copy.deepcopy(dict(updated_message.get('metadata')))
        if isinstance(updated_message.get('metadata'), Mapping)
        else {}
    )
    updated_metadata[CAPABILITY_PROPOSAL_METADATA_KEY] = copy.deepcopy(dict(proposal))
    provenance = updated_metadata.get(CAPABILITY_PROVENANCE_METADATA_KEY)
    if isinstance(provenance, Mapping):
        updated_provenance = copy.deepcopy(dict(provenance))
        if not isinstance(updated_provenance.get('proposed_capabilities'), Mapping):
            updated_provenance['proposed_capabilities'] = copy.deepcopy(dict(proposal))
        decision = proposal.get('decision')
        updated_provenance['capability_decisions'] = (
            [copy.deepcopy(dict(decision))]
            if isinstance(decision, Mapping)
            else []
        )
        updated_metadata[CAPABILITY_PROVENANCE_METADATA_KEY] = updated_provenance
    updated_message['metadata'] = updated_metadata
    return container.replace_item(
        item=updated_message['id'],
        body=updated_message,
        etag=message.get('_etag'),
        match_condition=MatchConditions.IfNotModified,
    )


def _is_conditional_conflict(exc):
    return getattr(exc, 'status_code', None) in {409, 412}


def persist_capability_decision(
    container,
    *,
    conversation_id,
    proposal_id,
    option_id,
    actor_user_id,
    refreshed_inventory,
    selected_capability_ids=None,
    prior_effective_capabilities=None,
    automatic_capability_root_ids=None,
    automatic_capability_effective_ids=None,
    selected_agent_present=False,
    baseline_error_code=None,
    source_lineage_validator=None,
    now=None,
):
    """Persist one allowlisted decision using optimistic concurrency."""
    last_conflict = None
    for _ in range(MAX_CONDITIONAL_WRITE_ATTEMPTS):
        message, proposal = read_capability_proposal_message(
            container,
            conversation_id=conversation_id,
            proposal_id=proposal_id,
        )
        if proposal.get('status') == 'pending' and capability_choice_is_expired(proposal, now=now):
            expired_proposal = copy.deepcopy(proposal)
            expired_proposal['status'] = 'expired'
            expired_proposal['invalidated_at'] = _transition_timestamp(now)
            expired_proposal['invalidation_reason'] = 'proposal_expired'
            try:
                _replace_proposal_message(container, message, expired_proposal)
            except Exception as exc:
                if _is_conditional_conflict(exc):
                    last_conflict = exc
                    continue
                raise
            raise CapabilityChoiceError(
                'this capability proposal has expired',
                code='proposal_expired',
            )
        updated, idempotent = apply_capability_choice_decision(
            proposal,
            option_id,
            actor_user_id=actor_user_id,
            now=now,
        )
        try:
            if callable(source_lineage_validator):
                source_lineage_validator(updated)
            validation_baseline = build_decline_aware_execution_baseline(
                updated,
                refreshed_inventory,
                selected_capability_ids=selected_capability_ids,
                prior_effective_capabilities=prior_effective_capabilities,
                automatic_capability_root_ids=automatic_capability_root_ids,
                automatic_capability_effective_ids=(
                    automatic_capability_effective_ids
                ),
            )
            revalidate_capability_execution_baseline(
                refreshed_inventory,
                **validation_baseline,
                baseline_error_code=baseline_error_code,
            )
            revalidate_capability_execution_compatibility(
                updated,
                selected_capability_ids=validation_baseline[
                    'selected_capability_ids'
                ],
                prior_effective_capabilities=validation_baseline[
                    'prior_effective_capabilities'
                ],
                selected_agent_present=selected_agent_present,
            )
            revalidate_capability_choice(updated, refreshed_inventory)
        except CapabilityChoiceError as validation_error:
            invalidated = _build_invalidated_proposal(updated, validation_error.code, now=now)
            try:
                _replace_proposal_message(container, message, invalidated)
            except Exception as exc:
                if _is_conditional_conflict(exc):
                    last_conflict = exc
                    continue
                raise
            raise
        if idempotent:
            return message, updated, True
        try:
            saved_message = _replace_proposal_message(container, message, updated)
            return saved_message, updated, False
        except Exception as exc:
            if not _is_conditional_conflict(exc):
                raise
            last_conflict = exc
    raise CapabilityChoiceError(
        'the capability proposal changed while the decision was being saved',
        code='decision_write_conflict',
    ) from last_conflict


def persist_capability_resume_claim(
    container,
    *,
    conversation_id,
    proposal_id,
    refreshed_inventory,
    selected_capability_ids=None,
    prior_effective_capabilities=None,
    automatic_capability_root_ids=None,
    automatic_capability_effective_ids=None,
    selected_agent_present=False,
    baseline_error_code=None,
    source_lineage_validator=None,
    now=None,
    execution_id=None,
    child_run_id=None,
):
    """Revalidate and conditionally claim one resume execution."""
    last_conflict = None
    for _ in range(MAX_CONDITIONAL_WRITE_ATTEMPTS):
        message, proposal = read_capability_proposal_message(
            container,
            conversation_id=conversation_id,
            proposal_id=proposal_id,
        )
        resume_state = proposal.get('resume') if isinstance(proposal.get('resume'), Mapping) else {}
        if (
            resume_state.get('status') != 'completed'
            and capability_choice_is_expired(proposal, now=now)
        ):
            invalidated = _build_invalidated_proposal(proposal, 'proposal_expired', now=now)
            try:
                _replace_proposal_message(container, message, invalidated)
            except Exception as exc:
                if _is_conditional_conflict(exc):
                    last_conflict = exc
                    continue
                raise
            raise CapabilityChoiceError(
                'this capability proposal has expired',
                code='proposal_expired',
            )
        try:
            if callable(source_lineage_validator):
                source_lineage_validator(proposal)
            validation_baseline = build_decline_aware_execution_baseline(
                proposal,
                refreshed_inventory,
                selected_capability_ids=selected_capability_ids,
                prior_effective_capabilities=prior_effective_capabilities,
                automatic_capability_root_ids=automatic_capability_root_ids,
                automatic_capability_effective_ids=(
                    automatic_capability_effective_ids
                ),
            )
            revalidate_capability_execution_baseline(
                refreshed_inventory,
                **validation_baseline,
                baseline_error_code=baseline_error_code,
            )
            revalidate_capability_execution_compatibility(
                proposal,
                selected_capability_ids=validation_baseline[
                    'selected_capability_ids'
                ],
                prior_effective_capabilities=validation_baseline[
                    'prior_effective_capabilities'
                ],
                selected_agent_present=selected_agent_present,
            )
            revalidate_capability_choice(proposal, refreshed_inventory)
        except CapabilityChoiceError as validation_error:
            invalidated = _build_invalidated_proposal(proposal, validation_error.code, now=now)
            try:
                _replace_proposal_message(container, message, invalidated)
            except Exception as exc:
                if _is_conditional_conflict(exc):
                    last_conflict = exc
                    continue
                raise
            raise
        updated, idempotent = claim_capability_choice_resume(
            proposal,
            now=now,
            execution_id=execution_id,
            child_run_id=child_run_id,
        )
        if idempotent:
            return message, updated, True
        try:
            saved_message = _replace_proposal_message(container, message, updated)
            return saved_message, updated, False
        except Exception as exc:
            if not _is_conditional_conflict(exc):
                raise
            last_conflict = exc
    raise CapabilityChoiceError(
        'the capability proposal changed while resume was being claimed',
        code='resume_write_conflict',
    ) from last_conflict


def persist_capability_resume_completion(
    container,
    *,
    conversation_id,
    proposal_id,
    execution_id,
    assistant_message_id,
    now=None,
):
    """Conditionally mark the exact claimed resume execution complete."""
    return _persist_resume_transition(
        container,
        conversation_id=conversation_id,
        proposal_id=proposal_id,
        transition=lambda proposal: complete_capability_choice_resume(
            proposal,
            execution_id=execution_id,
            assistant_message_id=assistant_message_id,
            now=now,
        ),
        conflict_code='resume_completion_write_conflict',
    )


def persist_capability_resume_failure(
    container,
    *,
    conversation_id,
    proposal_id,
    execution_id,
    error_type,
    now=None,
):
    """Conditionally release the exact failed resume execution for retry."""
    return _persist_resume_transition(
        container,
        conversation_id=conversation_id,
        proposal_id=proposal_id,
        transition=lambda proposal: fail_capability_choice_resume(
            proposal,
            execution_id=execution_id,
            error_type=error_type,
            now=now,
        ),
        conflict_code='resume_failure_write_conflict',
    )


def persist_capability_invalidation(
    container,
    *,
    conversation_id,
    proposal_id,
    reason,
    expected_execution_id=None,
    now=None,
):
    """Conditionally invalidate a proposal after fresh execution reauthorization."""
    last_conflict = None
    for _ in range(MAX_CONDITIONAL_WRITE_ATTEMPTS):
        message, proposal = read_capability_proposal_message(
            container,
            conversation_id=conversation_id,
            proposal_id=proposal_id,
        )
        resume = proposal.get('resume') if isinstance(proposal.get('resume'), Mapping) else {}
        if (
            expected_execution_id
            and str(resume.get('execution_id') or '').strip()
            != str(expected_execution_id).strip()
        ):
            raise CapabilityChoiceError(
                'resume claim does not match invalidation request',
                code='resume_claim_mismatch',
            )
        invalidated = _build_invalidated_proposal(proposal, reason, now=now)
        try:
            saved_message = _replace_proposal_message(
                container,
                message,
                invalidated,
            )
            return saved_message, invalidated, False
        except Exception as exc:
            if not _is_conditional_conflict(exc):
                raise
            last_conflict = exc
    raise CapabilityChoiceError(
        'the capability proposal changed while it was being invalidated',
        code='invalidation_write_conflict',
    ) from last_conflict


def _persist_resume_transition(
    container,
    *,
    conversation_id,
    proposal_id,
    transition,
    conflict_code,
):
    last_conflict = None
    for _ in range(MAX_CONDITIONAL_WRITE_ATTEMPTS):
        message, proposal = read_capability_proposal_message(
            container,
            conversation_id=conversation_id,
            proposal_id=proposal_id,
        )
        updated, idempotent = transition(proposal)
        if idempotent:
            return message, updated, True
        try:
            saved_message = _replace_proposal_message(container, message, updated)
            return saved_message, updated, False
        except Exception as exc:
            if not _is_conditional_conflict(exc):
                raise
            last_conflict = exc
    raise CapabilityChoiceError(
        'the capability proposal changed while resume state was being saved',
        code=conflict_code,
    ) from last_conflict


def _transition_timestamp(now=None):
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    return current_time.astimezone(timezone.utc).isoformat()


def _build_invalidated_proposal(proposal, reason, *, now=None):
    invalidated = copy.deepcopy(dict(proposal))
    invalidated['status'] = 'invalidated'
    invalidated['invalidated_at'] = _transition_timestamp(now)
    invalidated['invalidation_reason'] = str(reason or 'capability_invalidated').strip()[:120]
    decision = invalidated.get('decision')
    if isinstance(decision, Mapping):
        invalidated_decision = copy.deepcopy(dict(decision))
        invalidated_decision['status'] = 'invalidated'
        invalidated['decision'] = invalidated_decision
    resume = invalidated.get('resume')
    if isinstance(resume, Mapping):
        invalidated_resume = copy.deepcopy(dict(resume))
        invalidated_resume['status'] = 'failed'
        invalidated_resume['lease_expires_at'] = None
        invalidated_resume['error_type'] = invalidated['invalidation_reason']
        invalidated['resume'] = invalidated_resume
    return invalidated