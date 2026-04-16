# collaboration_models.py

"""Pure collaboration data-model helpers for multi-user conversations."""

from datetime import datetime, timedelta
import uuid


COLLABORATION_KIND = 'collaborative'

PERSONAL_MULTI_USER_CHAT_TYPE = 'personal_multi_user'
GROUP_MULTI_USER_CHAT_TYPE = 'group_multi_user'

MEMBERSHIP_STATUS_ACCEPTED = 'accepted'
MEMBERSHIP_STATUS_PENDING = 'pending'
MEMBERSHIP_STATUS_DECLINED = 'declined'
MEMBERSHIP_STATUS_REMOVED = 'removed'

MEMBERSHIP_ROLE_OWNER = 'owner'
MEMBERSHIP_ROLE_ADMIN = 'admin'
MEMBERSHIP_ROLE_MEMBER = 'member'

MESSAGE_KIND_HUMAN = 'human_message'
MESSAGE_KIND_AI_REQUEST = 'ai_request'
MESSAGE_KIND_ASSISTANT = 'assistant_response'

DEFAULT_PERSONAL_COLLABORATION_TITLE = 'New Collaborative Conversation'
DEFAULT_GROUP_COLLABORATION_TITLE = 'New Group Collaborative Conversation'


def utc_now_iso():
    return datetime.utcnow().isoformat()


def add_seconds_to_iso(timestamp, seconds):
    base_timestamp = datetime.fromisoformat(str(timestamp or utc_now_iso()))
    return (base_timestamp + timedelta(seconds=int(seconds or 0))).isoformat()


def _clean_string(value):
    return str(value or '').strip()


def normalize_collaboration_user(raw_user, fallback_user_id=None):
    raw_user = raw_user or {}
    if not isinstance(raw_user, dict):
        raw_user = {}

    user_id = _clean_string(
        raw_user.get('user_id')
        or raw_user.get('userId')
        or raw_user.get('id')
        or fallback_user_id
    )
    if not user_id:
        return None

    display_name = _clean_string(
        raw_user.get('display_name')
        or raw_user.get('displayName')
        or raw_user.get('name')
        or raw_user.get('username')
    )
    email = _clean_string(
        raw_user.get('email')
        or raw_user.get('mail')
        or raw_user.get('userPrincipalName')
    )

    return {
        'user_id': user_id,
        'display_name': display_name or email or 'Unknown User',
        'email': email,
    }


def build_collaboration_context(scope_type, scope_id, scope_name):
    return [
        {
            'type': 'primary',
            'scope': _clean_string(scope_type),
            'id': _clean_string(scope_id),
            'name': _clean_string(scope_name),
        }
    ]


def build_default_collaboration_title(conversation_type, group_name=''):
    normalized_type = _clean_string(conversation_type).lower()
    normalized_group_name = _clean_string(group_name)
    if normalized_type == 'group':
        if normalized_group_name:
            return f'{normalized_group_name} collaborative conversation'
        return DEFAULT_GROUP_COLLABORATION_TITLE
    return DEFAULT_PERSONAL_COLLABORATION_TITLE


def refresh_personal_participant_indexes(conversation_doc):
    participants = conversation_doc.setdefault('participants', [])
    accepted_participant_ids = []
    pending_participant_ids = []
    owner_user_ids = []
    admin_user_ids = []

    for participant in participants:
        participant_user_id = _clean_string(participant.get('user_id'))
        participant_status = _clean_string(participant.get('status'))
        participant_role = _clean_string(participant.get('role'))

        if not participant_user_id:
            continue

        if participant_status == MEMBERSHIP_STATUS_ACCEPTED:
            if participant_user_id not in accepted_participant_ids:
                accepted_participant_ids.append(participant_user_id)
            if participant_role == MEMBERSHIP_ROLE_OWNER and participant_user_id not in owner_user_ids:
                owner_user_ids.append(participant_user_id)
            if participant_role == MEMBERSHIP_ROLE_ADMIN and participant_user_id not in admin_user_ids:
                admin_user_ids.append(participant_user_id)
        elif participant_status == MEMBERSHIP_STATUS_PENDING:
            if participant_user_id not in pending_participant_ids:
                pending_participant_ids.append(participant_user_id)

    conversation_doc['accepted_participant_ids'] = accepted_participant_ids
    conversation_doc['pending_participant_ids'] = pending_participant_ids
    conversation_doc['owner_user_ids'] = owner_user_ids
    conversation_doc['admin_user_ids'] = admin_user_ids
    conversation_doc['participant_count'] = len(accepted_participant_ids)
    conversation_doc['pending_invite_count'] = len(pending_participant_ids)
    return conversation_doc


def build_personal_collaboration_conversation(
    title,
    creator_user,
    invited_participants=None,
    conversation_id=None,
    created_at=None,
):
    created_at = _clean_string(created_at) or utc_now_iso()
    conversation_id = _clean_string(conversation_id) or str(uuid.uuid4())
    creator_summary = normalize_collaboration_user(creator_user)
    if not creator_summary:
        raise ValueError('creator_user is required')

    conversation_title = _clean_string(title) or build_default_collaboration_title('personal')

    participants = [
        {
            'user_id': creator_summary['user_id'],
            'display_name': creator_summary['display_name'],
            'email': creator_summary['email'],
            'role': MEMBERSHIP_ROLE_OWNER,
            'status': MEMBERSHIP_STATUS_ACCEPTED,
            'invited_at': created_at,
            'joined_at': created_at,
        }
    ]
    existing_user_ids = {creator_summary['user_id']}

    for raw_participant in invited_participants or []:
        participant_summary = normalize_collaboration_user(raw_participant)
        if not participant_summary:
            continue
        if participant_summary['user_id'] in existing_user_ids:
            continue

        existing_user_ids.add(participant_summary['user_id'])
        participants.append({
            'user_id': participant_summary['user_id'],
            'display_name': participant_summary['display_name'],
            'email': participant_summary['email'],
            'role': MEMBERSHIP_ROLE_MEMBER,
            'status': MEMBERSHIP_STATUS_PENDING,
            'invited_at': created_at,
        })

    conversation_doc = {
        'id': conversation_id,
        'conversation_kind': COLLABORATION_KIND,
        'chat_type': PERSONAL_MULTI_USER_CHAT_TYPE,
        'title': conversation_title,
        'created_at': created_at,
        'updated_at': created_at,
        'last_message_at': None,
        'last_message_preview': '',
        'status': 'active',
        'created_by_user_id': creator_summary['user_id'],
        'created_by_display_name': creator_summary['display_name'],
        'scope': {
            'type': 'personal',
            'group_id': None,
            'group_name': None,
            'visibility_mode': 'invited_members',
            'allowed_scope_types': ['personal', 'public'],
        },
        'context': build_collaboration_context(
            'personal',
            creator_summary['user_id'],
            creator_summary['display_name'],
        ),
        'scope_locked': True,
        'locked_contexts': [{'scope': 'personal', 'id': creator_summary['user_id']}],
        'participants': participants,
        'conversation_settings': {
            'ai_invocation_mode': 'explicit_only',
            'reply_mode_enabled': True,
        },
        'message_count': 0,
        'tags': [],
    }
    return refresh_personal_participant_indexes(conversation_doc)


def build_group_collaboration_conversation(
    title,
    creator_user,
    group_id,
    group_name,
    conversation_id=None,
    created_at=None,
):
    created_at = _clean_string(created_at) or utc_now_iso()
    conversation_id = _clean_string(conversation_id) or str(uuid.uuid4())
    creator_summary = normalize_collaboration_user(creator_user)
    if not creator_summary:
        raise ValueError('creator_user is required')

    normalized_group_id = _clean_string(group_id)
    if not normalized_group_id:
        raise ValueError('group_id is required')

    normalized_group_name = _clean_string(group_name) or 'Group Workspace'
    conversation_title = _clean_string(title) or build_default_collaboration_title(
        'group',
        normalized_group_name,
    )

    return {
        'id': conversation_id,
        'conversation_kind': COLLABORATION_KIND,
        'chat_type': GROUP_MULTI_USER_CHAT_TYPE,
        'title': conversation_title,
        'created_at': created_at,
        'updated_at': created_at,
        'last_message_at': None,
        'last_message_preview': '',
        'status': 'active',
        'created_by_user_id': creator_summary['user_id'],
        'created_by_display_name': creator_summary['display_name'],
        'owner_user_ids': [creator_summary['user_id']],
        'accepted_participant_ids': [creator_summary['user_id']],
        'pending_participant_ids': [],
        'participant_count': 1,
        'pending_invite_count': 0,
        'scope': {
            'type': 'group',
            'group_id': normalized_group_id,
            'group_name': normalized_group_name,
            'visibility_mode': 'group_membership',
            'allowed_scope_types': ['group', 'public'],
        },
        'context': build_collaboration_context('group', normalized_group_id, normalized_group_name),
        'scope_locked': True,
        'locked_contexts': [{'scope': 'group', 'id': normalized_group_id}],
        'participants': [
            {
                'user_id': creator_summary['user_id'],
                'display_name': creator_summary['display_name'],
                'email': creator_summary['email'],
                'role': MEMBERSHIP_ROLE_OWNER,
                'status': MEMBERSHIP_STATUS_ACCEPTED,
                'invited_at': created_at,
                'joined_at': created_at,
            }
        ],
        'conversation_settings': {
            'ai_invocation_mode': 'explicit_only',
            'reply_mode_enabled': True,
        },
        'message_count': 0,
        'tags': [],
    }


def get_collaboration_user_state_doc_id(user_id, conversation_id):
    return f'{_clean_string(user_id)}:{_clean_string(conversation_id)}'


def build_collaboration_user_state(
    conversation_doc,
    user_summary,
    role,
    membership_status,
    invited_by_user_id=None,
    created_at=None,
):
    normalized_user = normalize_collaboration_user(user_summary)
    if not normalized_user:
        raise ValueError('user_summary is required')

    created_at = _clean_string(created_at) or utc_now_iso()
    conversation_id = _clean_string(conversation_doc.get('id'))
    scope = conversation_doc.get('scope', {}) if isinstance(conversation_doc, dict) else {}

    state_doc = {
        'id': get_collaboration_user_state_doc_id(normalized_user['user_id'], conversation_id),
        'conversation_kind': COLLABORATION_KIND,
        'conversation_id': conversation_id,
        'user_id': normalized_user['user_id'],
        'user_display_name': normalized_user['display_name'],
        'user_email': normalized_user['email'],
        'chat_type': conversation_doc.get('chat_type'),
        'scope_type': scope.get('type'),
        'group_id': scope.get('group_id'),
        'group_name': scope.get('group_name'),
        'title_snapshot': conversation_doc.get('title'),
        'role': _clean_string(role) or MEMBERSHIP_ROLE_MEMBER,
        'membership_status': _clean_string(membership_status) or MEMBERSHIP_STATUS_PENDING,
        'invited_by_user_id': _clean_string(invited_by_user_id),
        'created_at': created_at,
        'updated_at': created_at,
        'last_read_message_id': None,
        'last_read_at': None,
        'last_seen_at': None,
        'is_hidden': False,
        'is_pinned': False,
    }

    if state_doc['membership_status'] == MEMBERSHIP_STATUS_ACCEPTED:
        state_doc['joined_at'] = created_at

    return state_doc


def apply_personal_invite_response(conversation_doc, invited_user_id, action, responded_at=None):
    normalized_user_id = _clean_string(invited_user_id)
    normalized_action = _clean_string(action).lower()
    if normalized_action not in ('accept', 'decline'):
        raise ValueError('action must be accept or decline')

    responded_at = _clean_string(responded_at) or utc_now_iso()

    participant_record = None
    for participant in conversation_doc.get('participants', []):
        if _clean_string(participant.get('user_id')) != normalized_user_id:
            continue

        if _clean_string(participant.get('status')) != MEMBERSHIP_STATUS_PENDING:
            raise ValueError('participant invite is not pending')

        participant_record = participant
        if normalized_action == 'accept':
            participant['status'] = MEMBERSHIP_STATUS_ACCEPTED
            participant['joined_at'] = responded_at
        else:
            participant['status'] = MEMBERSHIP_STATUS_DECLINED
        participant['responded_at'] = responded_at
        break

    if participant_record is None:
        raise LookupError('pending participant not found')

    conversation_doc['updated_at'] = responded_at
    refresh_personal_participant_indexes(conversation_doc)
    return participant_record


def add_personal_pending_participants(conversation_doc, new_participants, invited_at=None):
    invited_at = _clean_string(invited_at) or utc_now_iso()
    existing_by_user_id = {
        _clean_string(participant.get('user_id')): participant
        for participant in conversation_doc.get('participants', [])
        if _clean_string(participant.get('user_id'))
    }

    added_participants = []
    for raw_participant in new_participants or []:
        participant_summary = normalize_collaboration_user(raw_participant)
        if not participant_summary:
            continue

        participant_user_id = participant_summary['user_id']
        existing_participant = existing_by_user_id.get(participant_user_id)
        if existing_participant:
            existing_status = _clean_string(existing_participant.get('status'))
            if existing_status in (MEMBERSHIP_STATUS_ACCEPTED, MEMBERSHIP_STATUS_PENDING):
                continue

            existing_participant['display_name'] = participant_summary['display_name']
            existing_participant['email'] = participant_summary['email']
            existing_participant['status'] = MEMBERSHIP_STATUS_PENDING
            existing_participant['role'] = MEMBERSHIP_ROLE_MEMBER
            existing_participant['invited_at'] = invited_at
            existing_participant.pop('joined_at', None)
            existing_participant.pop('removed_at', None)
            existing_participant.pop('responded_at', None)
            added_participants.append(existing_participant)
            continue

        participant_record = {
            'user_id': participant_user_id,
            'display_name': participant_summary['display_name'],
            'email': participant_summary['email'],
            'role': MEMBERSHIP_ROLE_MEMBER,
            'status': MEMBERSHIP_STATUS_PENDING,
            'invited_at': invited_at,
        }
        conversation_doc.setdefault('participants', []).append(participant_record)
        existing_by_user_id[participant_user_id] = participant_record
        added_participants.append(participant_record)

    if added_participants:
        conversation_doc['updated_at'] = invited_at
        refresh_personal_participant_indexes(conversation_doc)

    return added_participants


def remove_personal_participant(conversation_doc, participant_user_id, removed_at=None):
    normalized_user_id = _clean_string(participant_user_id)
    removed_at = _clean_string(removed_at) or utc_now_iso()
    owner_ids = set(conversation_doc.get('owner_user_ids', []) or [])
    if normalized_user_id in owner_ids:
        raise ValueError('owners cannot be removed from personal collaborative conversations')

    removed_participant = None
    for participant in conversation_doc.get('participants', []):
        if _clean_string(participant.get('user_id')) != normalized_user_id:
            continue

        participant['status'] = MEMBERSHIP_STATUS_REMOVED
        participant['removed_at'] = removed_at
        removed_participant = participant
        break

    if removed_participant is None:
        raise LookupError('participant not found')

    conversation_doc['updated_at'] = removed_at
    refresh_personal_participant_indexes(conversation_doc)
    return removed_participant


def ensure_group_participant_record(conversation_doc, user_summary, joined_at=None):
    joined_at = _clean_string(joined_at) or utc_now_iso()
    normalized_user = normalize_collaboration_user(user_summary)
    if not normalized_user:
        raise ValueError('user_summary is required')

    participant_record = None
    for participant in conversation_doc.get('participants', []):
        if _clean_string(participant.get('user_id')) != normalized_user['user_id']:
            continue

        participant['display_name'] = normalized_user['display_name']
        participant['email'] = normalized_user['email']
        participant['status'] = MEMBERSHIP_STATUS_ACCEPTED
        participant.setdefault('joined_at', joined_at)
        participant_record = participant
        break

    if participant_record is None:
        participant_record = {
            'user_id': normalized_user['user_id'],
            'display_name': normalized_user['display_name'],
            'email': normalized_user['email'],
            'role': MEMBERSHIP_ROLE_MEMBER,
            'status': MEMBERSHIP_STATUS_ACCEPTED,
            'invited_at': joined_at,
            'joined_at': joined_at,
        }
        conversation_doc.setdefault('participants', []).append(participant_record)

    accepted_participant_ids = list(conversation_doc.get('accepted_participant_ids', []) or [])
    if normalized_user['user_id'] not in accepted_participant_ids:
        accepted_participant_ids.append(normalized_user['user_id'])
    conversation_doc['accepted_participant_ids'] = accepted_participant_ids
    conversation_doc['participant_count'] = len(accepted_participant_ids)
    conversation_doc['updated_at'] = joined_at
    return participant_record


def _truncate_preview(content, max_length=160):
    content = _clean_string(content)
    if len(content) <= int(max_length):
        return content
    return f"{content[: int(max_length) - 3]}..."


def build_collaboration_message_doc(
    conversation_id,
    sender_user,
    content,
    reply_to_message_id=None,
    mentioned_participants=None,
    message_kind=MESSAGE_KIND_HUMAN,
    message_id=None,
    timestamp=None,
):
    normalized_sender = normalize_collaboration_user(sender_user)
    if not normalized_sender:
        raise ValueError('sender_user is required')

    normalized_conversation_id = _clean_string(conversation_id)
    if not normalized_conversation_id:
        raise ValueError('conversation_id is required')

    normalized_content = str(content or '')
    normalized_timestamp = _clean_string(timestamp) or utc_now_iso()
    normalized_message_kind = _clean_string(message_kind) or MESSAGE_KIND_HUMAN

    if normalized_message_kind == MESSAGE_KIND_ASSISTANT:
        role = 'assistant'
    else:
        role = 'user'

    normalized_mentions = []
    seen_mentioned_user_ids = set()
    for raw_participant in mentioned_participants or []:
        mentioned_user = normalize_collaboration_user(raw_participant)
        if not mentioned_user:
            continue

        mentioned_user_id = mentioned_user['user_id']
        if mentioned_user_id in seen_mentioned_user_ids:
            continue

        seen_mentioned_user_ids.add(mentioned_user_id)
        normalized_mentions.append(mentioned_user)

    metadata = {
        'sender': normalized_sender,
        'user_info': {
            'user_id': normalized_sender['user_id'],
            'display_name': normalized_sender['display_name'],
            'email': normalized_sender['email'],
            'username': normalized_sender['user_id'],
            'timestamp': normalized_timestamp,
        },
        'explicit_ai_invocation': normalized_message_kind == MESSAGE_KIND_AI_REQUEST,
        'last_message_preview': _truncate_preview(normalized_content),
    }
    if normalized_mentions:
        metadata['mentioned_participants'] = normalized_mentions
        metadata['mentioned_user_ids'] = [participant['user_id'] for participant in normalized_mentions]

    return {
        'id': _clean_string(message_id) or f'{normalized_conversation_id}_{uuid.uuid4().hex}',
        'conversation_id': normalized_conversation_id,
        'role': role,
        'message_kind': normalized_message_kind,
        'content': normalized_content,
        'reply_to_message_id': _clean_string(reply_to_message_id) or None,
        'timestamp': normalized_timestamp,
        'metadata': metadata,
    }


def build_collaboration_message_doc_from_legacy(
    conversation_id,
    legacy_message,
    default_sender_user,
):
    legacy_message = legacy_message or {}
    legacy_role = _clean_string(legacy_message.get('role')).lower()
    legacy_metadata = legacy_message.get('metadata', {}) if isinstance(legacy_message.get('metadata'), dict) else {}

    if legacy_role in ('assistant_artifact', 'assistant_artifact_chunk'):
        return None

    content = str(legacy_message.get('content') or '')
    message_kind = MESSAGE_KIND_HUMAN
    sender_user = normalize_collaboration_user(
        legacy_metadata.get('user_info') or default_sender_user,
    )

    if legacy_role == 'assistant':
        message_kind = MESSAGE_KIND_ASSISTANT
        sender_user = {
            'user_id': 'assistant',
            'display_name': _clean_string(legacy_message.get('agent_display_name')) or 'AI',
            'email': '',
        }
    elif legacy_role == 'safety':
        message_kind = MESSAGE_KIND_ASSISTANT
        sender_user = {
            'user_id': 'assistant',
            'display_name': 'Content Safety',
            'email': '',
        }
    elif legacy_role == 'file':
        filename = _clean_string(legacy_message.get('filename')) or 'file'
        content = f'[File shared] {filename}'
    elif legacy_role == 'image':
        is_user_upload = bool(legacy_metadata.get('is_user_upload'))
        if is_user_upload:
            filename = _clean_string(legacy_message.get('filename')) or 'image'
            content = f'[Uploaded image] {filename}'
        else:
            message_kind = MESSAGE_KIND_ASSISTANT
            sender_user = {
                'user_id': 'assistant',
                'display_name': _clean_string(legacy_message.get('agent_display_name')) or 'AI',
                'email': '',
            }
            image_url = _clean_string(legacy_message.get('content'))
            content = f'[Generated image] {image_url}' if image_url else '[Generated image]'
    elif legacy_role not in ('user', '') and not content.strip():
        return None

    if not sender_user:
        return None

    collaboration_message = build_collaboration_message_doc(
        conversation_id=conversation_id,
        sender_user=sender_user,
        content=content,
        reply_to_message_id=legacy_message.get('reply_to_message_id'),
        message_kind=message_kind,
        timestamp=legacy_message.get('timestamp'),
    )

    collaboration_metadata = collaboration_message.get('metadata', {})
    collaboration_message['metadata'] = {
        **dict(legacy_metadata),
        **collaboration_metadata,
        'source_message_id': _clean_string(legacy_message.get('id')) or None,
        'source_role': legacy_role or None,
    }
    if legacy_role == 'image':
        collaboration_message['metadata']['legacy_image_url'] = _clean_string(legacy_message.get('content')) or None
    if legacy_role == 'file':
        collaboration_message['metadata']['legacy_filename'] = _clean_string(legacy_message.get('filename')) or None

    for optional_key in (
        'model_deployment_name',
        'augmented',
        'hybrid_citations',
        'web_search_citations',
        'agent_citations',
        'agent_display_name',
        'agent_name',
        'extracted_text',
        'vision_analysis',
        'filename',
        'prompt',
        'is_table',
    ):
        if optional_key in legacy_message:
            collaboration_message[optional_key] = legacy_message.get(optional_key)

    return collaboration_message