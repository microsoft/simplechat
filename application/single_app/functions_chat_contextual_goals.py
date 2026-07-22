# functions_chat_contextual_goals.py
"""Bounded authorized user-turn context for chat capability planning."""

from collections.abc import Mapping

from functions_chat_capability_choices import CapabilityChoiceError


MAX_PRIOR_USER_TURNS = 2
MAX_CONTEXT_TURN_CHARS = 8000


def _active_user_turn(message, *, conversation_id):
    if not isinstance(message, Mapping):
        return False
    metadata = message.get('metadata') if isinstance(message.get('metadata'), Mapping) else {}
    thread_info = (
        metadata.get('thread_info')
        if isinstance(metadata.get('thread_info'), Mapping)
        else {}
    )
    return bool(
        message.get('conversation_id') == conversation_id
        and message.get('role') == 'user'
        and str(message.get('id') or '').strip()
        and str(message.get('content') or '').strip()
        and str(thread_info.get('thread_id') or '').strip()
        and metadata.get('is_deleted') is not True
        and metadata.get('masked') is not True
        and not (metadata.get('masked_ranges') or [])
        and metadata.get('is_generated_chat_artifact') is not True
        and thread_info.get('active_thread') is not False
    )


def _read_active_user_turn_for_thread(container, conversation_id, thread_id):
    rows = list(container.query_items(
        query=(
            'SELECT TOP 2 * FROM c '
            'WHERE c.conversation_id = @conversation_id '
            'AND c.role = "user" '
            'AND c.metadata.thread_info.thread_id = @thread_id '
            'AND (NOT IS_DEFINED(c.metadata.is_deleted) OR c.metadata.is_deleted != true) '
            'AND (NOT IS_DEFINED(c.metadata.masked) OR c.metadata.masked != true) '
            'AND (NOT IS_DEFINED(c.metadata.masked_ranges) '
            'OR ARRAY_LENGTH(c.metadata.masked_ranges) = 0) '
            'AND (NOT IS_DEFINED(c.metadata.is_generated_chat_artifact) '
            'OR c.metadata.is_generated_chat_artifact != true) '
            'AND (NOT IS_DEFINED(c.metadata.thread_info.active_thread) '
            'OR c.metadata.thread_info.active_thread != false)'
        ),
        parameters=[
            {'name': '@conversation_id', 'value': conversation_id},
            {'name': '@thread_id', 'value': thread_id},
        ],
        partition_key=conversation_id,
    ))
    active_rows = [
        row
        for row in rows
        if _active_user_turn(row, conversation_id=conversation_id)
    ]
    if len(active_rows) > 1:
        raise CapabilityChoiceError(
            'planning context thread has multiple active user attempts',
            code='goal_source_thread_ambiguous',
        )
    return active_rows[0] if active_rows else None


def load_bounded_prior_user_turns(container, *, conversation_id):
    """Load at most two preceding active user turns from one authorized partition."""
    conversation_id = str(conversation_id or '').strip()
    if not conversation_id:
        raise CapabilityChoiceError(
            'conversation_id is required for planning context',
            code='invalid_conversation_id',
        )
    latest_rows = list(container.query_items(
        query=(
            'SELECT TOP 2 * FROM c '
            'WHERE c.conversation_id = @conversation_id '
            'AND c.role = "user" '
            'AND (NOT IS_DEFINED(c.metadata.is_deleted) OR c.metadata.is_deleted != true) '
            'AND (NOT IS_DEFINED(c.metadata.masked) OR c.metadata.masked != true) '
            'AND (NOT IS_DEFINED(c.metadata.masked_ranges) '
            'OR ARRAY_LENGTH(c.metadata.masked_ranges) = 0) '
            'AND (NOT IS_DEFINED(c.metadata.is_generated_chat_artifact) '
            'OR c.metadata.is_generated_chat_artifact != true) '
            'AND (NOT IS_DEFINED(c.metadata.thread_info.active_thread) '
            'OR c.metadata.thread_info.active_thread != false) '
            'ORDER BY c.timestamp DESC'
        ),
        parameters=[{'name': '@conversation_id', 'value': conversation_id}],
        partition_key=conversation_id,
    ))
    latest_turn = next(
        (
            row
            for row in latest_rows
            if _active_user_turn(row, conversation_id=conversation_id)
        ),
        None,
    )
    latest_user_candidate_invalid = bool(
        latest_rows
        and (
            latest_turn is None
            or str(latest_rows[0].get('id') or '').strip()
            != str(latest_turn.get('id') or '').strip()
        )
    )
    if latest_turn is None:
        return {
            'prior_user_messages': [],
            'predecessor_thread_id': None,
            'latest_user_candidate_invalid': (
                latest_user_candidate_invalid
            ),
        }

    newest_first = [latest_turn]
    seen_thread_ids = {
        str(latest_turn['metadata']['thread_info']['thread_id'])
    }
    while len(newest_first) < MAX_PRIOR_USER_TURNS:
        previous_thread_id = str(
            newest_first[-1].get('metadata', {}).get('thread_info', {}).get(
                'previous_thread_id'
            ) or ''
        ).strip()
        if not previous_thread_id:
            break
        if previous_thread_id in seen_thread_ids:
            raise CapabilityChoiceError(
                'planning context thread lineage contains a cycle',
                code='goal_source_thread_invalid',
            )
        previous_turn = _read_active_user_turn_for_thread(
            container,
            conversation_id,
            previous_thread_id,
        )
        if previous_turn is None:
            break
        newest_first.append(previous_turn)
        seen_thread_ids.add(previous_thread_id)

    return {
        'prior_user_messages': list(reversed(newest_first)),
        'predecessor_thread_id': str(
            latest_turn.get('metadata', {}).get('thread_info', {}).get(
                'thread_id'
            ) or ''
        ).strip() or None,
        'latest_user_candidate_invalid': latest_user_candidate_invalid,
    }


def planner_prior_user_turns(context_state):
    """Project only bounded user text into the planner request builder."""
    state = context_state if isinstance(context_state, Mapping) else {}
    return [
        {
            'role': 'user',
            'text': str(message.get('content') or '').strip()[
                :MAX_CONTEXT_TURN_CHARS
            ],
        }
        for message in state.get('prior_user_messages') or []
        if isinstance(message, Mapping)
        and str(message.get('content') or '').strip()
    ][-MAX_PRIOR_USER_TURNS:]


def resolve_planner_goal_source_messages(
    planner_request,
    planner_result,
    context_state,
    current_user_message,
):
    """Resolve validated opaque refs to exact request-local user documents."""
    request = planner_request if isinstance(planner_request, Mapping) else {}
    result = planner_result if isinstance(planner_result, Mapping) else {}
    state = context_state if isinstance(context_state, Mapping) else {}
    dialogue_context = [
        turn
        for turn in request.get('dialogue_context') or []
        if isinstance(turn, Mapping) and turn.get('role') == 'user'
    ]
    prior_message_count = max(0, len(dialogue_context) - 1)
    available_prior_messages = [
        message
        for message in state.get('prior_user_messages') or []
        if isinstance(message, Mapping)
    ]
    source_messages = (
        available_prior_messages[-prior_message_count:]
        if prior_message_count
        else []
    )
    source_messages.append(current_user_message)
    if len(source_messages) != len(dialogue_context):
        raise CapabilityChoiceError(
            'planner goal refs cannot be bound to exact user turns',
            code='goal_source_binding_invalid',
        )
    messages_by_ref = {}
    for turn, message in zip(dialogue_context, source_messages):
        turn_ref = str(turn.get('ref') or '').strip()
        projected_text = str(turn.get('text') or '').strip()
        exact_text = str(message.get('content') or '').strip()[
            :MAX_CONTEXT_TURN_CHARS
        ]
        if not turn_ref or projected_text != exact_text:
            raise CapabilityChoiceError(
                'planner goal context changed before source binding',
                code='goal_source_changed',
            )
        messages_by_ref[turn_ref] = message
    selected_messages = []
    for turn_ref in result.get('goal_turn_refs') or []:
        source_message = messages_by_ref.get(str(turn_ref or '').strip())
        if source_message is None:
            raise CapabilityChoiceError(
                'planner selected an unavailable goal ref',
                code='unknown_goal_turn_ref',
            )
        selected_messages.append(source_message)
    structured_state = (
        request.get('structured_state')
        if isinstance(request.get('structured_state'), Mapping)
        else {}
    )
    if (
        structured_state.get('type') == 'clarification'
        and current_user_message not in selected_messages
    ):
        selected_messages.append(current_user_message)
    if not selected_messages:
        raise CapabilityChoiceError(
            'planner selected no goal source turns',
            code='invalid_goal_turn_refs',
        )
    return selected_messages


def read_exact_goal_source_messages(container, *, conversation_id, stored_goal):
    """Read exact persisted source IDs from an already authorized conversation."""
    if not isinstance(stored_goal, Mapping):
        raise CapabilityChoiceError(
            'approved goal metadata is missing',
            code='goal_metadata_invalid',
        )
    source_ids = list(stored_goal.get('source_user_message_ids') or [])
    if not 1 <= len(source_ids) <= 3:
        raise CapabilityChoiceError(
            'approved goal source count is invalid',
            code='goal_source_count_invalid',
        )
    messages = []
    for source_id in source_ids:
        source_id = str(source_id or '').strip()
        if not source_id:
            raise CapabilityChoiceError(
                'approved goal source ID is invalid',
                code='goal_source_invalid',
            )
        message = container.read_item(
            item=source_id,
            partition_key=conversation_id,
        )
        messages.append(message)
    return messages
