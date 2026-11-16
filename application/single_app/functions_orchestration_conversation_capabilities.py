# functions_orchestration_conversation_capabilities.py
"""Private, typed conversation capabilities and exact approved send boundaries.

Version: 0.261.381
Runtime owners are imported at operation boundaries, after application bootstrap.
"""

from copy import deepcopy
import hashlib
import json

from functions_conversation_references import (
    ConversationReferenceError, normalize_conversation_references, reference_identifier,
)


CONVERSATION_REFERENCE_SCHEMA = {
    'type': 'array', 'maxItems': 5,
    'items': {
        'type': 'object', 'additionalProperties': False,
        'properties': {
            'kind': {'type': 'string', 'enum': ['conversation']},
            'id': {'type': 'string', 'minLength': 1, 'maxLength': 200},
            'message_ids': {'type': 'array', 'maxItems': 20, 'items': {'type': 'string'}},
        },
        'required': ['kind', 'id'],
    },
}
CONVERSATION_SEND_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {
        'destination_conversation_id': {'type': 'string', 'minLength': 1, 'maxLength': 200},
        'instruction': {'type': 'string', 'minLength': 1, 'maxLength': 8000},
        'conversation_references': CONVERSATION_REFERENCE_SCHEMA,
    },
    'required': ['destination_conversation_id', 'instruction'],
}


def normalize_conversation_send(value):
    if type(value) is not dict or value.keys() - set(CONVERSATION_SEND_SCHEMA['properties']):
        raise ConversationReferenceError(public_message='Invalid conversation send configuration.')
    destination = reference_identifier(value.get('destination_conversation_id'))
    instruction = value.get('instruction')
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 8000:
        raise ConversationReferenceError(public_message='A conversation send needs an instruction of at most 8000 characters.')
    return {
        'destination_conversation_id': destination,
        'instruction': instruction.strip(),
        'conversation_references': normalize_conversation_references(value.get('conversation_references')),
    }


def conversation_request_allowed(context):
    """Only the current user's request, never retrieved source prose, opts into lookup."""
    message = str((context or {}).get('user_message') or '').lower()
    return bool((context or {}).get('conversation_references')) or any(
        word in message for word in ('conversation', 'previous chat', 'earlier chat', 'other chat')
    )


def resolve_conversation_snapshot(user_id, references, *, query='', destination_id=None, snapshot=None, resolver=None):
    """Keep excerpts stable while rechecking current access, deletion and masking on reuse."""
    if resolver is None:
        from functions_conversation_reference_runtime import resolve_conversation_references

        resolver = resolve_conversation_references
    references = normalize_conversation_references(references)
    if snapshot is None:
        return resolver(user_id, references, query=query, destination_id=destination_id, max_tokens=4000)
    selected = {}
    for excerpt in snapshot.get('excerpts') or []:
        selected.setdefault(excerpt['conversation_id'], []).append(excerpt['message_id'])
    narrowed = [
        {**reference, **({'message_ids': selected[reference['id']]} if selected.get(reference['id']) else {})}
        for reference in references
    ]
    current = resolver(user_id, narrowed, query='', destination_id=destination_id, max_tokens=4000)
    current_by_id = {
        (item['conversation_id'], item['message_id']): item for item in current.get('excerpts') or []
    }
    for previous in snapshot.get('excerpts') or []:
        now = current_by_id.get((previous['conversation_id'], previous['message_id']))
        if now is None or any(now.get(key) != previous.get(key) for key in ('role', 'content', 'timestamp')):
            raise ConversationReferenceError(
                'conversation_reference_changed',
                'Conversation evidence changed or became unavailable. Start a new run to refresh it.', 409,
            )
    return deepcopy(snapshot)


def _send_matches(destination, instruction, references, configured):
    requested = normalize_conversation_send({
        'destination_conversation_id': destination, 'instruction': instruction,
        'conversation_references': references,
    })
    return requested == normalize_conversation_send(configured)


def validate_conversation_send_approval(user_id, source_conversation_id, destination_conversation_id,
                                        instruction, references, approval):
    """The queue revalidates the saved approval at admission and again at dispatch."""
    if type(approval) is not dict:
        return False
    if approval.get('kind') == 'workflow':
        from functions_workflow_conversation_references import validate_workflow_conversation_send_approval

        return validate_workflow_conversation_send_approval(
            user_id, source_conversation_id, destination_conversation_id, instruction, references, approval,
        )
    if approval.get('kind') != 'orchestration':
        return False
    from functions_orchestration_runs import get_orchestration_run

    record = get_orchestration_run(approval.get('run_id'), user_id, source_conversation_id, strict=True)
    if not record or record.get('status') in ('cancelled', 'failed', 'superseded'):
        return False
    plan = record.get('plan') or {}
    grant = plan.get('approval') or {}
    if (
        plan.get('revision') != approval.get('revision') or grant.get('state') != 'approved'
        or grant.get('mode') != 'manual' or grant.get('approved_by') != user_id
    ):
        return False
    step = next((item for item in plan.get('steps') or [] if item.get('step_id') == approval.get('step_id')), None)
    return bool(
        step and step.get('enabled', True) and step.get('capability_id') == 'conversation_send'
        and _send_matches(destination_conversation_id, instruction, references, step.get('arguments'))
    )


def _retain_result(step, context, value, summary):
    # Result services depend on initialized authority owners; contract parsing above does not.
    from functions_orchestration_result_contracts import Completeness, Coverage
    from functions_orchestration_result_runtime import require_result_service
    from functions_orchestration_results import NamedOutput
    from functions_orchestration_schema import build_step_result

    service = require_result_service(context)
    task = service.persist_task_result(
        producer=context.result_producer(step), role=step['role'], status='complete',
        outputs=[NamedOutput('result', 'structured-v1', value,
                             Completeness('complete', 1, 1, Coverage(1, 1, 'items'), 'valid', ('conversation_reference',), ()))],
        sources=[], origin='generated', upstream=(),
        guard_token=context.result_guard_token_for_step(step['step_id']),
        input_fingerprint=context.result_input_fingerprint_for_step(step['step_id']),
    )
    return build_step_result(status='completed', summary=summary, task_result=task)


def run_conversation_capability(step, context, *, settings, user_id, emit=None, cancel_requested=None):
    from functions_conversation_reference_runtime import authorize_private_conversation, search_conversation_references

    authorize_private_conversation(user_id, context.conversation_id)
    if user_id != context.user_id:
        raise ConversationReferenceError('conversation_reference_unavailable', 'Conversation source unavailable.', 404)
    if callable(cancel_requested) and cancel_requested():
        from functions_orchestration_schema import build_step_result

        return build_step_result(status='cancelled')
    arguments = step.get('arguments') or {}
    capability = step['capability_id']
    if capability == 'conversation_search':
        if not conversation_request_allowed({'user_message': context.user_message, **(context.seeds or {})}):
            raise ConversationReferenceError(public_message='Ask to search conversations before using this capability.')
        value = search_conversation_references(
            user_id, arguments.get('query', ''), offset=arguments.get('offset', 0), limit=arguments.get('limit', 10),
            search_content=arguments.get('search_content', False), exclude_conversation_id=context.conversation_id,
        )
        return _retain_result(step, context, value, 'Searched eligible private conversations; coverage may be partial.')
    if capability == 'conversation_read':
        references = normalize_conversation_references(arguments.get('conversation_references'))
        cache = getattr(context, 'conversation_reference_snapshots', None)
        if cache is None:
            cache = context.conversation_reference_snapshots = {}
        key = json.dumps(references, sort_keys=True)
        value = resolve_conversation_snapshot(
            user_id, references, query=arguments.get('query', ''), destination_id=context.conversation_id,
            snapshot=cache.get(key),
        )
        cache[key] = value
        return _retain_result(step, context, value, 'Read bounded private conversation evidence.')
    if capability != 'conversation_send':
        raise ConversationReferenceError(public_message='Unsupported conversation capability.')
    from functions_conversation_handoff_runtime import enqueue_conversation_handoff

    configured = normalize_conversation_send(arguments)
    approval = {
        'kind': 'orchestration', 'run_id': context.run_id,
        'revision': context.conversation_send_plan_revision, 'step_id': step['step_id'],
    }
    request_id = hashlib.sha256(f'{context.attempt_root_run_id}:{step["step_id"]}'.encode()).hexdigest()
    handoff = enqueue_conversation_handoff(
        user_id, context.conversation_id, configured['destination_conversation_id'], configured['instruction'],
        references=configured['conversation_references'], request_id=request_id, approval=approval,
        origin={'kind': 'orchestration', 'run_id': context.run_id,
                'visited_conversation_ids': [context.conversation_id], 'hop_count': 0},
    )
    return _retain_result(step, context, {'kind': 'conversation_handoff', **handoff}, 'Destination AI work was queued.')
