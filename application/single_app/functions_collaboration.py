# functions_collaboration.py

"""Persistence, authorization, and serialization helpers for collaborative conversations."""

from config import *
from collaboration_models import (
    COLLABORATION_KIND,
    GROUP_MULTI_USER_CHAT_TYPE,
    MEMBERSHIP_ROLE_ADMIN,
    MEMBERSHIP_ROLE_MEMBER,
    MEMBERSHIP_ROLE_OWNER,
    MEMBERSHIP_STATUS_ACCEPTED,
    MEMBERSHIP_STATUS_DECLINED,
    MEMBERSHIP_STATUS_PENDING,
    MEMBERSHIP_STATUS_REMOVED,
    MESSAGE_KIND_HUMAN,
    PERSONAL_MULTI_USER_CHAT_TYPE,
    add_personal_pending_participants,
    apply_personal_invite_response,
    build_collaboration_message_doc,
    build_collaboration_message_doc_from_legacy,
    build_collaboration_user_state,
    build_group_collaboration_conversation,
    build_personal_collaboration_conversation,
    ensure_group_participant_record,
    get_collaboration_user_state_doc_id,
    refresh_personal_participant_indexes,
    remove_personal_participant,
    utc_now_iso,
)
from functions_appinsights import log_event
from functions_group import (
    assert_group_role,
    check_group_status_allows_operation,
    find_group_by_id,
    get_user_groups,
)
from functions_message_artifacts import filter_assistant_artifact_items
from functions_thoughts import delete_thoughts_for_conversation, get_thoughts_for_message


PERSONAL_COLLABORATION_MANAGER_ROLES = {
    MEMBERSHIP_ROLE_OWNER,
    MEMBERSHIP_ROLE_ADMIN,
}


def is_collaboration_conversation(conversation_doc):
    return bool((conversation_doc or {}).get('conversation_kind') == COLLABORATION_KIND)


def is_personal_collaboration_conversation(conversation_doc):
    return bool((conversation_doc or {}).get('chat_type') == PERSONAL_MULTI_USER_CHAT_TYPE)


def is_group_collaboration_conversation(conversation_doc):
    return bool((conversation_doc or {}).get('chat_type') == GROUP_MULTI_USER_CHAT_TYPE)


def get_collaboration_conversation(conversation_id):
    return cosmos_collaboration_conversations_container.read_item(
        item=conversation_id,
        partition_key=conversation_id,
    )


def get_collaboration_user_state(user_id, conversation_id):
    return cosmos_collaboration_user_state_container.read_item(
        item=get_collaboration_user_state_doc_id(user_id, conversation_id),
        partition_key=user_id,
    )


def get_collaboration_message(message_id):
    query = 'SELECT TOP 1 * FROM c WHERE c.id = @message_id'
    items = list(cosmos_collaboration_messages_container.query_items(
        query=query,
        parameters=[{'name': '@message_id', 'value': message_id}],
        enable_cross_partition_query=True,
    ))
    if not items:
        raise CosmosResourceNotFoundError(message='Collaborative message not found')
    return items[0]


def get_personal_collaboration_participant(conversation_doc, participant_user_id):
    normalized_user_id = str(participant_user_id or '').strip()
    for participant in list((conversation_doc or {}).get('participants', []) or []):
        if str(participant.get('user_id') or '').strip() == normalized_user_id:
            return participant
    return None


def get_personal_collaboration_role(conversation_doc, participant_user_id, user_state=None):
    if user_state and str(user_state.get('role') or '').strip():
        return str(user_state.get('role') or '').strip()

    participant = get_personal_collaboration_participant(conversation_doc, participant_user_id)
    if not participant:
        return ''
    return str(participant.get('role') or '').strip()


def serialize_collaboration_message(message_doc):
    metadata = message_doc.get('metadata', {}) if isinstance(message_doc, dict) else {}
    return {
        'id': message_doc.get('id'),
        'conversation_id': message_doc.get('conversation_id'),
        'role': message_doc.get('role'),
        'message_kind': message_doc.get('message_kind', MESSAGE_KIND_HUMAN),
        'content': message_doc.get('content', ''),
        'reply_to_message_id': message_doc.get('reply_to_message_id'),
        'timestamp': message_doc.get('timestamp'),
        'sender': metadata.get('sender', {}),
        'metadata': metadata,
        'explicit_ai_invocation': bool(metadata.get('explicit_ai_invocation', False)),
        'model_deployment_name': message_doc.get('model_deployment_name'),
        'augmented': bool(message_doc.get('augmented', False)),
        'hybrid_citations': list(message_doc.get('hybrid_citations', []) or []),
        'web_search_citations': list(message_doc.get('web_search_citations', []) or []),
        'agent_citations': list(message_doc.get('agent_citations', []) or []),
        'agent_display_name': message_doc.get('agent_display_name'),
        'agent_name': message_doc.get('agent_name'),
    }


def serialize_collaboration_conversation(conversation_doc, current_user_id, user_state=None):
    conversation_doc = conversation_doc or {}
    participants = list(conversation_doc.get('participants', []) or [])
    membership_status = None
    if user_state:
        membership_status = user_state.get('membership_status')
    elif current_user_id in set(conversation_doc.get('accepted_participant_ids', []) or []):
        membership_status = MEMBERSHIP_STATUS_ACCEPTED
    elif is_group_collaboration_conversation(conversation_doc):
        membership_status = 'group_member'

    owner_user_ids = list(conversation_doc.get('owner_user_ids', []) or [])
    admin_user_ids = list(conversation_doc.get('admin_user_ids', []) or [])
    scope = conversation_doc.get('scope', {}) if isinstance(conversation_doc.get('scope'), dict) else {}
    current_user_role = get_personal_collaboration_role(
        conversation_doc,
        current_user_id,
        user_state=user_state,
    )
    can_manage_members = bool(
        is_personal_collaboration_conversation(conversation_doc)
        and membership_status == MEMBERSHIP_STATUS_ACCEPTED
        and current_user_role in PERSONAL_COLLABORATION_MANAGER_ROLES
    )
    can_manage_roles = bool(
        is_personal_collaboration_conversation(conversation_doc)
        and membership_status == MEMBERSHIP_STATUS_ACCEPTED
        and current_user_role == MEMBERSHIP_ROLE_OWNER
    )
    can_accept_invite = membership_status == MEMBERSHIP_STATUS_PENDING
    can_post_messages = bool(
        is_group_collaboration_conversation(conversation_doc)
        or membership_status == MEMBERSHIP_STATUS_ACCEPTED
    )
    can_delete_conversation = bool(
        is_personal_collaboration_conversation(conversation_doc)
        and membership_status == MEMBERSHIP_STATUS_ACCEPTED
        and current_user_role == MEMBERSHIP_ROLE_OWNER
    )
    can_leave_conversation = bool(
        is_personal_collaboration_conversation(conversation_doc)
        and membership_status == MEMBERSHIP_STATUS_ACCEPTED
    )

    return {
        'id': conversation_doc.get('id'),
        'title': conversation_doc.get('title', ''),
        'conversation_kind': conversation_doc.get('conversation_kind'),
        'chat_type': conversation_doc.get('chat_type'),
        'status': conversation_doc.get('status', 'active'),
        'created_at': conversation_doc.get('created_at'),
        'updated_at': conversation_doc.get('updated_at'),
        'last_message_at': conversation_doc.get('last_message_at'),
        'last_message_preview': conversation_doc.get('last_message_preview', ''),
        'message_count': conversation_doc.get('message_count', 0),
        'participant_count': conversation_doc.get('participant_count', 0),
        'pending_invite_count': conversation_doc.get('pending_invite_count', 0),
        'participants': participants,
        'accepted_participant_ids': list(conversation_doc.get('accepted_participant_ids', []) or []),
        'pending_participant_ids': list(conversation_doc.get('pending_participant_ids', []) or []),
        'owner_user_ids': owner_user_ids,
        'admin_user_ids': admin_user_ids,
        'current_user_role': current_user_role,
        'membership_status': membership_status,
        'can_manage_members': can_manage_members,
        'can_manage_roles': can_manage_roles,
        'can_accept_invite': can_accept_invite,
        'can_post_messages': can_post_messages,
        'can_delete_conversation': can_delete_conversation,
        'can_leave_conversation': can_leave_conversation,
        'scope': scope,
        'context': list(conversation_doc.get('context', []) or []),
        'scope_locked': conversation_doc.get('scope_locked', True),
        'locked_contexts': list(conversation_doc.get('locked_contexts', []) or []),
        'conversation_settings': dict(conversation_doc.get('conversation_settings', {}) or {}),
        'group_id': scope.get('group_id'),
        'group_name': scope.get('group_name'),
        'last_updated': conversation_doc.get('updated_at'),
        'is_pinned': bool((user_state or {}).get('is_pinned', False)),
        'is_hidden': bool((user_state or {}).get('is_hidden', False)),
        'classification': list(conversation_doc.get('classification', []) or []),
        'tags': list(conversation_doc.get('tags', []) or []),
        'strict': bool(conversation_doc.get('strict', False)),
        'summary': conversation_doc.get('summary'),
        'has_unread_assistant_response': False,
        'last_unread_assistant_message_id': None,
        'last_unread_assistant_at': None,
        'user_id': conversation_doc.get('created_by_user_id'),
        'source_conversation_id': conversation_doc.get('source_conversation_id'),
    }


def get_personal_collaboration_conversation_by_source_conversation(source_conversation_id):
    query = (
        'SELECT TOP 1 * FROM c WHERE c.conversation_kind = @conversation_kind '
        'AND c.chat_type = @chat_type AND c.source_conversation_id = @source_conversation_id'
    )
    items = list(cosmos_collaboration_conversations_container.query_items(
        query=query,
        parameters=[
            {'name': '@conversation_kind', 'value': COLLABORATION_KIND},
            {'name': '@chat_type', 'value': PERSONAL_MULTI_USER_CHAT_TYPE},
            {'name': '@source_conversation_id', 'value': source_conversation_id},
        ],
        enable_cross_partition_query=True,
    ))
    return items[0] if items else None


def _is_eligible_legacy_personal_conversation(source_conversation_doc):
    chat_type = str(source_conversation_doc.get('chat_type') or '').strip().lower()
    if chat_type.startswith('group') or chat_type.startswith('public'):
        return False

    primary_context = next(
        (
            context_item
            for context_item in list(source_conversation_doc.get('context', []) or [])
            if context_item.get('type') == 'primary'
        ),
        None,
    )
    if primary_context and str(primary_context.get('scope') or '').strip().lower() in ('group', 'public'):
        return False

    return True


def _copy_legacy_personal_messages_to_collaboration(source_conversation_id, collaboration_conversation_id, owner_user):
    query = 'SELECT * FROM c WHERE c.conversation_id = @conversation_id ORDER BY c.timestamp ASC'
    raw_messages = list(cosmos_messages_container.query_items(
        query=query,
        parameters=[{'name': '@conversation_id', 'value': source_conversation_id}],
        partition_key=source_conversation_id,
    ))
    raw_messages = filter_assistant_artifact_items(raw_messages)

    copied_messages = []
    for raw_message in raw_messages:
        collaboration_message = build_collaboration_message_doc_from_legacy(
            collaboration_conversation_id,
            raw_message,
            owner_user,
        )
        if not collaboration_message:
            continue

        metadata = collaboration_message.setdefault('metadata', {})
        metadata.setdefault('source_message_id', raw_message.get('id'))
        metadata.setdefault('source_conversation_id', source_conversation_id)
        metadata.setdefault('source_thought_user_id', str((owner_user or {}).get('user_id') or '').strip())

        cosmos_collaboration_messages_container.upsert_item(collaboration_message)
        copied_messages.append(collaboration_message)

    return copied_messages


def ensure_personal_collaboration_for_legacy_conversation(source_conversation_id, owner_user, invited_participants=None):
    source_conversation_doc = cosmos_conversations_container.read_item(
        item=source_conversation_id,
        partition_key=source_conversation_id,
    )
    owner_summary = owner_user or {}
    owner_user_id = str(owner_summary.get('user_id') or '').strip()
    if not owner_user_id:
        raise PermissionError('User not authenticated')

    if str(source_conversation_doc.get('user_id') or '').strip() != owner_user_id:
        raise PermissionError('Only the conversation owner can convert this conversation')

    if not _is_eligible_legacy_personal_conversation(source_conversation_doc):
        raise PermissionError('Only personal single-user conversations can be converted into personal collaborative conversations')

    collaboration_conversation_doc = None
    linked_collaboration_id = str(source_conversation_doc.get('collaboration_conversation_id') or '').strip()
    if linked_collaboration_id:
        try:
            collaboration_conversation_doc = get_collaboration_conversation(linked_collaboration_id)
        except CosmosResourceNotFoundError:
            collaboration_conversation_doc = None

    if collaboration_conversation_doc is None:
        collaboration_conversation_doc = get_personal_collaboration_conversation_by_source_conversation(
            source_conversation_id,
        )

    if collaboration_conversation_doc is not None:
        invited_state_docs = []
        if invited_participants:
            collaboration_conversation_doc, invited_state_docs = invite_personal_collaboration_participants(
                collaboration_conversation_doc.get('id'),
                owner_user_id,
                invited_participants,
            )
        return collaboration_conversation_doc, invited_state_docs, False, source_conversation_doc

    collaboration_conversation_doc, user_state_docs = create_personal_collaboration_conversation_record(
        title=source_conversation_doc.get('title') or '',
        creator_user=owner_summary,
        invited_participants=invited_participants,
    )
    invited_state_docs = [
        state_doc
        for state_doc in user_state_docs
        if state_doc.get('user_id') != owner_user_id
    ]

    collaboration_conversation_doc['source_conversation_id'] = source_conversation_id
    collaboration_conversation_doc['classification'] = list(source_conversation_doc.get('classification', []) or [])
    collaboration_conversation_doc['tags'] = list(source_conversation_doc.get('tags', []) or [])
    collaboration_conversation_doc['strict'] = bool(source_conversation_doc.get('strict', False))
    collaboration_conversation_doc['summary'] = source_conversation_doc.get('summary')

    source_context = list(source_conversation_doc.get('context', []) or [])
    if source_context:
        collaboration_conversation_doc['context'] = source_context
    source_scope_locked = source_conversation_doc.get('scope_locked')
    if source_scope_locked is not None:
        collaboration_conversation_doc['scope_locked'] = bool(source_scope_locked)
    source_locked_contexts = list(source_conversation_doc.get('locked_contexts', []) or [])
    if source_locked_contexts:
        collaboration_conversation_doc['locked_contexts'] = source_locked_contexts

    copied_messages = _copy_legacy_personal_messages_to_collaboration(
        source_conversation_id,
        collaboration_conversation_doc.get('id'),
        owner_summary,
    )
    if copied_messages:
        last_copied_message = copied_messages[-1]
        collaboration_conversation_doc['last_message_at'] = last_copied_message.get('timestamp')
        collaboration_conversation_doc['last_message_preview'] = (
            (last_copied_message.get('metadata') or {}).get('last_message_preview') or ''
        )
        collaboration_conversation_doc['updated_at'] = last_copied_message.get('timestamp')
        collaboration_conversation_doc['message_count'] = len(copied_messages)

    cosmos_collaboration_conversations_container.upsert_item(collaboration_conversation_doc)

    conversion_timestamp = utc_now_iso()
    source_conversation_doc['collaboration_conversation_id'] = collaboration_conversation_doc.get('id')
    source_conversation_doc['converted_to_collaboration_at'] = conversion_timestamp
    source_conversation_doc['is_hidden'] = True
    source_conversation_doc['last_updated'] = conversion_timestamp
    cosmos_conversations_container.upsert_item(source_conversation_doc)

    log_event(
        '[Collaboration] Converted personal conversation into collaborative conversation',
        extra={
            'source_conversation_id': source_conversation_id,
            'conversation_id': collaboration_conversation_doc.get('id'),
            'created_by_user_id': owner_user_id,
            'copied_message_count': len(copied_messages),
        },
        level=logging.INFO,
    )
    return collaboration_conversation_doc, invited_state_docs, True, source_conversation_doc


def create_personal_collaboration_conversation_record(title, creator_user, invited_participants=None):
    conversation_doc = build_personal_collaboration_conversation(
        title=title,
        creator_user=creator_user,
        invited_participants=invited_participants,
    )
    cosmos_collaboration_conversations_container.upsert_item(conversation_doc)

    user_states = []
    for participant in conversation_doc.get('participants', []):
        membership_status = participant.get('status')
        role = participant.get('role')
        invited_by_user_id = ''
        if participant.get('user_id') != conversation_doc.get('created_by_user_id'):
            invited_by_user_id = conversation_doc.get('created_by_user_id')
        state_doc = build_collaboration_user_state(
            conversation_doc=conversation_doc,
            user_summary=participant,
            role=role,
            membership_status=membership_status,
            invited_by_user_id=invited_by_user_id,
            created_at=participant.get('invited_at') or conversation_doc.get('created_at'),
        )
        cosmos_collaboration_user_state_container.upsert_item(state_doc)
        user_states.append(state_doc)

    log_event(
        '[Collaboration] Created personal collaborative conversation',
        extra={
            'conversation_id': conversation_doc.get('id'),
            'created_by_user_id': conversation_doc.get('created_by_user_id'),
            'participant_count': conversation_doc.get('participant_count', 0),
            'pending_invite_count': conversation_doc.get('pending_invite_count', 0),
        },
        level=logging.INFO,
    )
    return conversation_doc, user_states


def create_group_collaboration_conversation_record(title, creator_user, group_doc):
    conversation_doc = build_group_collaboration_conversation(
        title=title,
        creator_user=creator_user,
        group_id=group_doc.get('id'),
        group_name=group_doc.get('name', 'Group Workspace'),
    )
    cosmos_collaboration_conversations_container.upsert_item(conversation_doc)
    log_event(
        '[Collaboration] Created group collaborative conversation',
        extra={
            'conversation_id': conversation_doc.get('id'),
            'group_id': group_doc.get('id'),
            'created_by_user_id': conversation_doc.get('created_by_user_id'),
        },
        level=logging.INFO,
    )
    return conversation_doc


def list_personal_collaboration_conversations_for_user(user_id):
    query = (
        'SELECT * FROM c WHERE c.user_id = @user_id '
        'AND c.conversation_kind = @conversation_kind'
    )
    states = list(cosmos_collaboration_user_state_container.query_items(
        query=query,
        parameters=[
            {'name': '@user_id', 'value': user_id},
            {'name': '@conversation_kind', 'value': COLLABORATION_KIND},
        ],
        partition_key=user_id,
    ))

    conversations = []
    for state_doc in states:
        membership_status = state_doc.get('membership_status')
        if membership_status not in (MEMBERSHIP_STATUS_ACCEPTED, MEMBERSHIP_STATUS_PENDING):
            continue

        if state_doc.get('chat_type') != PERSONAL_MULTI_USER_CHAT_TYPE:
            continue

        conversation_id = state_doc.get('conversation_id')
        if not conversation_id:
            continue

        try:
            conversation_doc = get_collaboration_conversation(conversation_id)
        except CosmosResourceNotFoundError:
            continue

        conversations.append((conversation_doc, state_doc))

    conversations.sort(
        key=lambda item: item[0].get('updated_at') or item[0].get('created_at') or '',
        reverse=True,
    )
    return conversations


def list_group_collaboration_conversations_for_user(user_id):
    user_groups = get_user_groups(user_id)
    group_map = {
        str(group_doc.get('id')): group_doc
        for group_doc in user_groups
        if group_doc.get('id')
    }
    if not group_map:
        return []

    query = (
        'SELECT * FROM c WHERE c.conversation_kind = @conversation_kind '
        'AND c.chat_type = @chat_type AND c.status = @status'
    )
    items = list(cosmos_collaboration_conversations_container.query_items(
        query=query,
        parameters=[
            {'name': '@conversation_kind', 'value': COLLABORATION_KIND},
            {'name': '@chat_type', 'value': GROUP_MULTI_USER_CHAT_TYPE},
            {'name': '@status', 'value': 'active'},
        ],
        enable_cross_partition_query=True,
    ))

    filtered_items = []
    for conversation_doc in items:
        group_id = str((conversation_doc.get('scope') or {}).get('group_id') or '')
        if group_id not in group_map:
            continue

        allowed, _ = check_group_status_allows_operation(group_map[group_id], 'view')
        if allowed:
            filtered_items.append(conversation_doc)

    filtered_items.sort(
        key=lambda item: item.get('updated_at') or item.get('created_at') or '',
        reverse=True,
    )
    return filtered_items


def assert_user_can_view_collaboration_conversation(user_id, conversation_doc, allow_pending=False):
    if not is_collaboration_conversation(conversation_doc):
        raise LookupError('Collaboration conversation not found')

    if is_personal_collaboration_conversation(conversation_doc):
        try:
            user_state = get_collaboration_user_state(user_id, conversation_doc.get('id'))
        except CosmosResourceNotFoundError as exc:
            raise PermissionError('You are not a participant in this collaborative conversation') from exc

        membership_status = user_state.get('membership_status')
        if membership_status == MEMBERSHIP_STATUS_ACCEPTED:
            return {
                'user_state': user_state,
                'membership_status': membership_status,
            }
        if allow_pending and membership_status == MEMBERSHIP_STATUS_PENDING:
            return {
                'user_state': user_state,
                'membership_status': membership_status,
            }
        raise PermissionError('You do not have access to this collaborative conversation')

    if is_group_collaboration_conversation(conversation_doc):
        group_id = str((conversation_doc.get('scope') or {}).get('group_id') or '').strip()
        if not group_id:
            raise LookupError('Group collaborative conversation is missing group context')

        group_doc = find_group_by_id(group_id)
        if not group_doc:
            raise LookupError('Group not found')

        group_role = assert_group_role(
            user_id,
            group_id,
            allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
        )
        allowed, reason = check_group_status_allows_operation(group_doc, 'view')
        if not allowed:
            raise PermissionError(reason)
        return {
            'group_doc': group_doc,
            'group_role': group_role,
            'membership_status': 'group_member',
        }

    raise PermissionError('Unsupported collaboration conversation type')


def assert_user_can_participate_in_collaboration_conversation(user_id, conversation_doc):
    access_context = assert_user_can_view_collaboration_conversation(
        user_id,
        conversation_doc,
        allow_pending=False,
    )

    if is_group_collaboration_conversation(conversation_doc):
        group_doc = access_context.get('group_doc')
        allowed, reason = check_group_status_allows_operation(group_doc, 'chat')
        if not allowed:
            raise PermissionError(reason)

    return access_context


def record_personal_invite_response(conversation_id, user_id, action):
    conversation_doc = get_collaboration_conversation(conversation_id)
    if not is_personal_collaboration_conversation(conversation_doc):
        raise PermissionError('Invite responses are only supported for personal collaborative conversations')

    user_state = get_collaboration_user_state(user_id, conversation_id)
    participant_record = apply_personal_invite_response(
        conversation_doc,
        invited_user_id=user_id,
        action=action,
        responded_at=utc_now_iso(),
    )

    membership_status = MEMBERSHIP_STATUS_ACCEPTED if str(action).lower() == 'accept' else MEMBERSHIP_STATUS_DECLINED
    user_state['membership_status'] = membership_status
    user_state['updated_at'] = participant_record.get('responded_at')
    user_state['responded_at'] = participant_record.get('responded_at')
    if membership_status == MEMBERSHIP_STATUS_ACCEPTED:
        user_state['joined_at'] = participant_record.get('joined_at')

    cosmos_collaboration_conversations_container.upsert_item(conversation_doc)
    cosmos_collaboration_user_state_container.upsert_item(user_state)
    return conversation_doc, user_state, participant_record


def invite_personal_collaboration_participants(conversation_id, owner_user_id, participants_to_add):
    conversation_doc = get_collaboration_conversation(conversation_id)
    if not is_personal_collaboration_conversation(conversation_doc):
        raise PermissionError('Member invites are only supported for personal collaborative conversations')

    actor_user_state = None
    try:
        actor_user_state = get_collaboration_user_state(owner_user_id, conversation_id)
    except CosmosResourceNotFoundError:
        actor_user_state = None

    actor_role = get_personal_collaboration_role(
        conversation_doc,
        owner_user_id,
        user_state=actor_user_state,
    )
    if actor_role not in PERSONAL_COLLABORATION_MANAGER_ROLES:
        raise PermissionError('Only conversation owners or admins can invite members')

    invite_timestamp = utc_now_iso()
    added_participants = add_personal_pending_participants(
        conversation_doc,
        participants_to_add,
        invited_at=invite_timestamp,
    )
    if not added_participants:
        return conversation_doc, []

    cosmos_collaboration_conversations_container.upsert_item(conversation_doc)

    created_state_docs = []
    for participant in added_participants:
        state_doc = build_collaboration_user_state(
            conversation_doc=conversation_doc,
            user_summary=participant,
            role=participant.get('role', MEMBERSHIP_ROLE_MEMBER),
            membership_status=participant.get('status', MEMBERSHIP_STATUS_PENDING),
            invited_by_user_id=owner_user_id,
            created_at=invite_timestamp,
        )
        cosmos_collaboration_user_state_container.upsert_item(state_doc)
        created_state_docs.append(state_doc)

    return conversation_doc, created_state_docs


def remove_personal_collaboration_member(conversation_id, owner_user_id, member_user_id):
    conversation_doc = get_collaboration_conversation(conversation_id)
    if not is_personal_collaboration_conversation(conversation_doc):
        raise PermissionError('Member removal is only supported for personal collaborative conversations')

    actor_user_state = None
    try:
        actor_user_state = get_collaboration_user_state(owner_user_id, conversation_id)
    except CosmosResourceNotFoundError:
        actor_user_state = None

    actor_role = get_personal_collaboration_role(
        conversation_doc,
        owner_user_id,
        user_state=actor_user_state,
    )
    if actor_role not in PERSONAL_COLLABORATION_MANAGER_ROLES:
        raise PermissionError('Only conversation owners or admins can remove members')

    member_participant = get_personal_collaboration_participant(conversation_doc, member_user_id)
    if member_participant is None:
        raise LookupError('participant not found')
    member_role = str(member_participant.get('role') or '').strip()
    if actor_role != MEMBERSHIP_ROLE_OWNER and member_role != MEMBERSHIP_ROLE_MEMBER:
        raise PermissionError('Only conversation owners can remove admins')

    removed_participant = remove_personal_participant(
        conversation_doc,
        participant_user_id=member_user_id,
        removed_at=utc_now_iso(),
    )
    cosmos_collaboration_conversations_container.upsert_item(conversation_doc)

    try:
        user_state = get_collaboration_user_state(member_user_id, conversation_id)
    except CosmosResourceNotFoundError:
        user_state = None

    if user_state:
        user_state['membership_status'] = MEMBERSHIP_STATUS_REMOVED
        user_state['updated_at'] = removed_participant.get('removed_at')
        user_state['removed_at'] = removed_participant.get('removed_at')
        cosmos_collaboration_user_state_container.upsert_item(user_state)

    return conversation_doc, removed_participant


def list_collaboration_messages(conversation_id):
    query = 'SELECT * FROM c WHERE c.conversation_id = @conversation_id ORDER BY c.timestamp ASC'
    return list(cosmos_collaboration_messages_container.query_items(
        query=query,
        parameters=[{'name': '@conversation_id', 'value': conversation_id}],
        partition_key=conversation_id,
    ))


def persist_collaboration_message(conversation_doc, sender_user, content, reply_to_message_id=None):
    conversation_id = conversation_doc.get('id')
    message_doc = build_collaboration_message_doc(
        conversation_id=conversation_id,
        sender_user=sender_user,
        content=content,
        reply_to_message_id=reply_to_message_id,
        message_kind=MESSAGE_KIND_HUMAN,
        timestamp=utc_now_iso(),
    )

    if is_group_collaboration_conversation(conversation_doc):
        ensure_group_participant_record(conversation_doc, sender_user, joined_at=message_doc.get('timestamp'))

    cosmos_collaboration_messages_container.upsert_item(message_doc)

    conversation_doc['last_message_at'] = message_doc.get('timestamp')
    conversation_doc['last_message_preview'] = (
        message_doc.get('metadata', {}).get('last_message_preview', '')
    )
    conversation_doc['updated_at'] = message_doc.get('timestamp')
    conversation_doc['message_count'] = int(conversation_doc.get('message_count', 0) or 0) + 1

    if is_personal_collaboration_conversation(conversation_doc):
        refresh_personal_participant_indexes(conversation_doc)

    cosmos_collaboration_conversations_container.upsert_item(conversation_doc)
    return message_doc, conversation_doc


def update_personal_collaboration_title(conversation_id, current_user_id, new_title):
    conversation_doc = get_collaboration_conversation(conversation_id)
    if not is_personal_collaboration_conversation(conversation_doc):
        raise PermissionError('Title updates are only supported for personal collaborative conversations')
    if current_user_id not in set(conversation_doc.get('owner_user_ids', []) or []):
        raise PermissionError('Only conversation owners can rename collaborative conversations')

    normalized_title = str(new_title or '').strip()
    if not normalized_title:
        raise ValueError('Title is required')

    conversation_doc['title'] = normalized_title
    conversation_doc['updated_at'] = utc_now_iso()
    cosmos_collaboration_conversations_container.upsert_item(conversation_doc)
    return conversation_doc


def toggle_personal_collaboration_pin(conversation_id, current_user_id):
    conversation_doc = get_collaboration_conversation(conversation_id)
    if not is_personal_collaboration_conversation(conversation_doc):
        raise PermissionError('Pin is only supported for personal collaborative conversations')

    user_state = get_collaboration_user_state(current_user_id, conversation_id)
    user_state['is_pinned'] = not bool(user_state.get('is_pinned', False))
    user_state['updated_at'] = utc_now_iso()
    cosmos_collaboration_user_state_container.upsert_item(user_state)
    return conversation_doc, user_state


def toggle_personal_collaboration_hide(conversation_id, current_user_id):
    conversation_doc = get_collaboration_conversation(conversation_id)
    if not is_personal_collaboration_conversation(conversation_doc):
        raise PermissionError('Hide is only supported for personal collaborative conversations')

    user_state = get_collaboration_user_state(current_user_id, conversation_id)
    user_state['is_hidden'] = not bool(user_state.get('is_hidden', False))
    user_state['updated_at'] = utc_now_iso()
    cosmos_collaboration_user_state_container.upsert_item(user_state)
    return conversation_doc, user_state


def update_personal_collaboration_member_role(conversation_id, current_user_id, member_user_id, new_role):
    conversation_doc = get_collaboration_conversation(conversation_id)
    if not is_personal_collaboration_conversation(conversation_doc):
        raise PermissionError('Role updates are only supported for personal collaborative conversations')
    if current_user_id not in set(conversation_doc.get('owner_user_ids', []) or []):
        raise PermissionError('Only conversation owners can change participant roles')

    normalized_role = str(new_role or '').strip().lower()
    if normalized_role not in (MEMBERSHIP_ROLE_ADMIN, MEMBERSHIP_ROLE_MEMBER):
        raise ValueError('role must be admin or member')

    participant = get_personal_collaboration_participant(conversation_doc, member_user_id)
    if participant is None:
        raise LookupError('participant not found')
    if str(participant.get('status') or '').strip() != MEMBERSHIP_STATUS_ACCEPTED:
        raise ValueError('Only active participants can have admin access')
    if str(participant.get('role') or '').strip() == MEMBERSHIP_ROLE_OWNER:
        raise ValueError('Use owner transfer to change owner access')

    if str(participant.get('role') or '').strip() == normalized_role:
        return conversation_doc, participant

    timestamp = utc_now_iso()
    participant['role'] = normalized_role
    conversation_doc['updated_at'] = timestamp
    refresh_personal_participant_indexes(conversation_doc)
    cosmos_collaboration_conversations_container.upsert_item(conversation_doc)

    try:
        user_state = get_collaboration_user_state(member_user_id, conversation_id)
    except CosmosResourceNotFoundError:
        user_state = None

    if user_state:
        user_state['role'] = normalized_role
        user_state['updated_at'] = timestamp
        cosmos_collaboration_user_state_container.upsert_item(user_state)

    return conversation_doc, participant


def leave_personal_collaboration_conversation(conversation_id, current_user_id, new_owner_user_id=None):
    conversation_doc = get_collaboration_conversation(conversation_id)
    if not is_personal_collaboration_conversation(conversation_doc):
        raise PermissionError('Leave is only supported for personal collaborative conversations')

    participant = get_personal_collaboration_participant(conversation_doc, current_user_id)
    if participant is None:
        raise PermissionError('You are not a participant in this collaborative conversation')
    if str(participant.get('status') or '').strip() != MEMBERSHIP_STATUS_ACCEPTED:
        raise PermissionError('Only active participants can leave this collaborative conversation')

    normalized_new_owner_user_id = str(new_owner_user_id or '').strip()
    current_role = str(participant.get('role') or '').strip()
    promoted_participant = None
    timestamp = utc_now_iso()

    if current_role == MEMBERSHIP_ROLE_OWNER:
        owner_user_ids = list(conversation_doc.get('owner_user_ids', []) or [])
        other_owner_ids = [owner_user_id for owner_user_id in owner_user_ids if owner_user_id != current_user_id]
        if not other_owner_ids and not normalized_new_owner_user_id:
            raise ValueError('Assign a new owner before leaving this shared conversation')

        if normalized_new_owner_user_id:
            if normalized_new_owner_user_id == current_user_id:
                raise ValueError('Choose another participant as the new owner')

            promoted_participant = get_personal_collaboration_participant(
                conversation_doc,
                normalized_new_owner_user_id,
            )
            if promoted_participant is None:
                raise LookupError('The selected new owner is not a participant in this conversation')
            if str(promoted_participant.get('status') or '').strip() != MEMBERSHIP_STATUS_ACCEPTED:
                raise ValueError('The selected new owner must already be an active participant')
            promoted_participant['role'] = MEMBERSHIP_ROLE_OWNER

            try:
                new_owner_state = get_collaboration_user_state(normalized_new_owner_user_id, conversation_id)
            except CosmosResourceNotFoundError:
                new_owner_state = None

            if new_owner_state:
                new_owner_state['role'] = MEMBERSHIP_ROLE_OWNER
                new_owner_state['updated_at'] = timestamp
                cosmos_collaboration_user_state_container.upsert_item(new_owner_state)

    participant['status'] = MEMBERSHIP_STATUS_REMOVED
    participant['removed_at'] = timestamp
    conversation_doc['updated_at'] = timestamp
    refresh_personal_participant_indexes(conversation_doc)
    cosmos_collaboration_conversations_container.upsert_item(conversation_doc)

    try:
        user_state = get_collaboration_user_state(current_user_id, conversation_id)
    except CosmosResourceNotFoundError:
        user_state = None

    if user_state:
        user_state['membership_status'] = MEMBERSHIP_STATUS_REMOVED
        user_state['role'] = MEMBERSHIP_ROLE_MEMBER
        user_state['removed_at'] = timestamp
        user_state['updated_at'] = timestamp
        cosmos_collaboration_user_state_container.upsert_item(user_state)

    return conversation_doc, participant, promoted_participant


def _delete_source_personal_conversation(conversation_doc, current_user_id):
    source_conversation_id = str((conversation_doc or {}).get('source_conversation_id') or '').strip()
    if not source_conversation_id:
        return

    try:
        source_conversation = cosmos_conversations_container.read_item(
            item=source_conversation_id,
            partition_key=source_conversation_id,
        )
    except CosmosResourceNotFoundError:
        return

    if str(source_conversation.get('user_id') or '').strip() != str(current_user_id or '').strip():
        return
    if str(source_conversation.get('collaboration_conversation_id') or '').strip() != str(conversation_doc.get('id') or '').strip():
        return

    message_query = 'SELECT * FROM c WHERE c.conversation_id = @conversation_id'
    source_messages = list(cosmos_messages_container.query_items(
        query=message_query,
        parameters=[{'name': '@conversation_id', 'value': source_conversation_id}],
        partition_key=source_conversation_id,
    ))

    for message_doc in source_messages:
        cosmos_messages_container.delete_item(
            item=message_doc.get('id'),
            partition_key=source_conversation_id,
        )

    delete_thoughts_for_conversation(source_conversation_id, current_user_id)
    cosmos_conversations_container.delete_item(
        item=source_conversation_id,
        partition_key=source_conversation_id,
    )


def delete_personal_collaboration_conversation(conversation_id, current_user_id):
    conversation_doc = get_collaboration_conversation(conversation_id)
    if not is_personal_collaboration_conversation(conversation_doc):
        raise PermissionError('Delete is only supported for personal collaborative conversations')
    if current_user_id not in set(conversation_doc.get('owner_user_ids', []) or []):
        raise PermissionError('Only conversation owners can delete this shared conversation')

    message_query = 'SELECT * FROM c WHERE c.conversation_id = @conversation_id'
    messages = list(cosmos_collaboration_messages_container.query_items(
        query=message_query,
        parameters=[{'name': '@conversation_id', 'value': conversation_id}],
        partition_key=conversation_id,
    ))
    for message_doc in messages:
        cosmos_collaboration_messages_container.delete_item(
            item=message_doc.get('id'),
            partition_key=conversation_id,
        )

    state_query = 'SELECT * FROM c WHERE c.conversation_id = @conversation_id'
    state_docs = list(cosmos_collaboration_user_state_container.query_items(
        query=state_query,
        parameters=[{'name': '@conversation_id', 'value': conversation_id}],
        enable_cross_partition_query=True,
    ))
    for state_doc in state_docs:
        cosmos_collaboration_user_state_container.delete_item(
            item=state_doc.get('id'),
            partition_key=state_doc.get('user_id'),
        )

    _delete_source_personal_conversation(conversation_doc, current_user_id)
    cosmos_collaboration_conversations_container.delete_item(
        item=conversation_id,
        partition_key=conversation_id,
    )
    return conversation_doc


def get_accessible_collaboration_message_thoughts(conversation_doc, message_doc, viewer_user_id):
    conversation_id = str((conversation_doc or {}).get('id') or '').strip()
    message_id = str((message_doc or {}).get('id') or '').strip()
    metadata = (message_doc or {}).get('metadata', {}) if isinstance(message_doc, dict) else {}

    if not conversation_id or not message_id:
        return []

    direct_thoughts = get_thoughts_for_message(conversation_id, message_id, viewer_user_id)
    if direct_thoughts:
        return direct_thoughts

    fallback_user_ids = []
    for candidate_user_id in (
        metadata.get('source_thought_user_id'),
        (conversation_doc or {}).get('created_by_user_id'),
    ):
        normalized_candidate = str(candidate_user_id or '').strip()
        if not normalized_candidate or normalized_candidate in fallback_user_ids:
            continue
        fallback_user_ids.append(normalized_candidate)

    fallback_conversation_id = str(
        metadata.get('source_conversation_id')
        or (conversation_doc or {}).get('source_conversation_id')
        or ''
    ).strip()
    fallback_message_id = str(metadata.get('source_message_id') or '').strip()

    for candidate_user_id in fallback_user_ids:
        candidate_thoughts = get_thoughts_for_message(conversation_id, message_id, candidate_user_id)
        if candidate_thoughts:
            return candidate_thoughts

        if fallback_conversation_id and fallback_message_id:
            candidate_thoughts = get_thoughts_for_message(
                fallback_conversation_id,
                fallback_message_id,
                candidate_user_id,
            )
            if candidate_thoughts:
                return candidate_thoughts

    return []