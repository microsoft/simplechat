# functions_collaboration.py

"""Persistence, authorization, and serialization helpers for collaborative conversations."""

from copy import deepcopy
import uuid

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
    MESSAGE_KIND_AI_REQUEST,
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
    normalize_collaboration_user,
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
from functions_notifications import create_collaboration_message_notification
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


def get_collaboration_visibility_mode(conversation_doc):
    scope = (conversation_doc or {}).get('scope', {}) if isinstance((conversation_doc or {}).get('scope'), dict) else {}
    visibility_mode = str(scope.get('visibility_mode') or '').strip().lower()
    if visibility_mode:
        return visibility_mode
    if is_group_collaboration_conversation(conversation_doc):
        return 'group_membership'
    return 'invited_members'


def is_invited_group_collaboration_conversation(conversation_doc):
    return bool(
        is_group_collaboration_conversation(conversation_doc)
        and get_collaboration_visibility_mode(conversation_doc) == 'invited_members'
    )


def is_explicit_membership_collaboration(conversation_doc):
    return bool(
        is_personal_collaboration_conversation(conversation_doc)
        or is_invited_group_collaboration_conversation(conversation_doc)
    )


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


def get_collaboration_user_state_or_none(user_id, conversation_id):
    try:
        return get_collaboration_user_state(user_id, conversation_id)
    except CosmosResourceNotFoundError:
        return None


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


def get_collaboration_message_by_source_message(conversation_id, source_message_id):
    normalized_conversation_id = str(conversation_id or '').strip()
    normalized_source_message_id = str(source_message_id or '').strip()
    if not normalized_conversation_id or not normalized_source_message_id:
        return None

    query = (
        'SELECT TOP 1 * FROM c WHERE c.conversation_id = @conversation_id '
        'AND c.metadata.source_message_id = @source_message_id'
    )
    items = list(cosmos_collaboration_messages_container.query_items(
        query=query,
        parameters=[
            {'name': '@conversation_id', 'value': normalized_conversation_id},
            {'name': '@source_message_id', 'value': normalized_source_message_id},
        ],
        partition_key=normalized_conversation_id,
    ))
    return items[0] if items else None


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


def _build_group_member_lookup(group_doc):
    member_lookup = {}
    if not isinstance(group_doc, dict):
        return member_lookup

    owner = group_doc.get('owner', {}) if isinstance(group_doc.get('owner'), dict) else {}
    owner_summary = normalize_collaboration_user({
        'userId': owner.get('id'),
        'displayName': owner.get('displayName'),
        'email': owner.get('email'),
    })
    if owner_summary:
        member_lookup[owner_summary['user_id']] = owner_summary

    for raw_member in list(group_doc.get('users', []) or []):
        member_summary = normalize_collaboration_user(raw_member)
        if not member_summary:
            continue
        member_lookup[member_summary['user_id']] = member_summary

    return member_lookup


def _resolve_group_member_summary(group_doc, user_id):
    normalized_user_id = str(user_id or '').strip()
    if not normalized_user_id:
        return None
    return _build_group_member_lookup(group_doc).get(normalized_user_id)


def _normalize_group_conversation_participants(group_doc, participants_to_add):
    member_lookup = _build_group_member_lookup(group_doc)
    normalized_participants = []
    missing_participant_labels = []

    for raw_participant in participants_to_add or []:
        participant_summary = normalize_collaboration_user(raw_participant)
        if not participant_summary:
            continue

        group_member_summary = member_lookup.get(participant_summary['user_id'])
        if not group_member_summary:
            missing_participant_labels.append(
                participant_summary.get('display_name')
                or participant_summary.get('email')
                or participant_summary['user_id']
            )
            continue

        normalized_participants.append(group_member_summary)

    if missing_participant_labels:
        missing_labels = ', '.join(sorted(set(missing_participant_labels)))
        raise ValueError(
            f'Only current group members can be added to this shared conversation: {missing_labels}'
        )

    return normalized_participants


def ensure_collaboration_user_state_for_participant(
    conversation_doc,
    participant_summary,
    role,
    membership_status,
    invited_by_user_id=None,
    created_at=None,
):
    normalized_participant = normalize_collaboration_user(participant_summary)
    if not normalized_participant:
        raise ValueError('participant_summary is required')

    normalized_conversation_id = str((conversation_doc or {}).get('id') or '').strip()
    if not normalized_conversation_id:
        raise ValueError('conversation_id is required')

    timestamp = str(created_at or '').strip() or utc_now_iso()
    state_doc = get_collaboration_user_state_or_none(
        normalized_participant['user_id'],
        normalized_conversation_id,
    )
    if state_doc is None:
        state_doc = build_collaboration_user_state(
            conversation_doc=conversation_doc,
            user_summary=normalized_participant,
            role=role,
            membership_status=membership_status,
            invited_by_user_id=invited_by_user_id,
            created_at=timestamp,
        )
    else:
        state_doc['user_display_name'] = normalized_participant['display_name']
        state_doc['user_email'] = normalized_participant['email']
        state_doc['title_snapshot'] = conversation_doc.get('title')
        state_doc['role'] = str(role or state_doc.get('role') or MEMBERSHIP_ROLE_MEMBER).strip() or MEMBERSHIP_ROLE_MEMBER
        state_doc['membership_status'] = str(
            membership_status or state_doc.get('membership_status') or MEMBERSHIP_STATUS_PENDING
        ).strip() or MEMBERSHIP_STATUS_PENDING
        state_doc['updated_at'] = timestamp
        state_doc['scope_type'] = ((conversation_doc or {}).get('scope') or {}).get('type')
        state_doc['group_id'] = ((conversation_doc or {}).get('scope') or {}).get('group_id')
        state_doc['group_name'] = ((conversation_doc or {}).get('scope') or {}).get('group_name')
        state_doc['chat_type'] = conversation_doc.get('chat_type')
        if invited_by_user_id is not None:
            state_doc['invited_by_user_id'] = str(invited_by_user_id or '').strip()

    if state_doc.get('membership_status') == MEMBERSHIP_STATUS_ACCEPTED and not state_doc.get('joined_at'):
        state_doc['joined_at'] = timestamp

    cosmos_collaboration_user_state_container.upsert_item(state_doc)
    return state_doc


def _bootstrap_collaboration_user_state_from_participant(conversation_doc, participant_record, invited_by_user_id=None):
    if not isinstance(participant_record, dict):
        return None

    membership_status = str(participant_record.get('status') or '').strip() or MEMBERSHIP_STATUS_PENDING
    if membership_status not in (MEMBERSHIP_STATUS_ACCEPTED, MEMBERSHIP_STATUS_PENDING):
        return None

    created_at = (
        participant_record.get('joined_at')
        or participant_record.get('invited_at')
        or (conversation_doc or {}).get('created_at')
        or utc_now_iso()
    )
    state_doc = ensure_collaboration_user_state_for_participant(
        conversation_doc,
        participant_record,
        role=participant_record.get('role') or MEMBERSHIP_ROLE_MEMBER,
        membership_status=membership_status,
        invited_by_user_id=invited_by_user_id,
        created_at=created_at,
    )

    if participant_record.get('responded_at'):
        state_doc['responded_at'] = participant_record.get('responded_at')
    if participant_record.get('removed_at'):
        state_doc['removed_at'] = participant_record.get('removed_at')
    cosmos_collaboration_user_state_container.upsert_item(state_doc)
    return state_doc


def build_collaboration_image_url(conversation_id, message_id):
    normalized_conversation_id = str(conversation_id or '').strip()
    normalized_message_id = str(message_id or '').strip()
    if not normalized_conversation_id or not normalized_message_id:
        return ''

    return f'/api/collaboration/conversations/{normalized_conversation_id}/images/{normalized_message_id}'


def serialize_collaboration_message(message_doc):
    metadata = message_doc.get('metadata', {}) if isinstance(message_doc, dict) else {}
    display_role = _get_collaboration_display_role(message_doc)
    serialized_role = 'image' if display_role == 'image' else message_doc.get('role')
    serialized_content = message_doc.get('content', '')
    if display_role == 'image':
        serialized_content = build_collaboration_image_url(
            message_doc.get('conversation_id'),
            message_doc.get('id'),
        ) or serialized_content

    return {
        'id': message_doc.get('id'),
        'conversation_id': message_doc.get('conversation_id'),
        'role': serialized_role,
        'message_kind': message_doc.get('message_kind', MESSAGE_KIND_HUMAN),
        'content': serialized_content,
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
        'filename': message_doc.get('filename'),
        'prompt': message_doc.get('prompt'),
        'extracted_text': message_doc.get('extracted_text'),
        'vision_analysis': message_doc.get('vision_analysis'),
    }


def _get_collaboration_source_message(message_doc):
    metadata = message_doc.get('metadata', {}) if isinstance(message_doc, dict) else {}
    source_message_id = str(metadata.get('source_message_id') or '').strip()
    if not source_message_id:
        return None

    query = 'SELECT TOP 1 * FROM c WHERE c.id = @message_id'
    items = list(cosmos_messages_container.query_items(
        query=query,
        parameters=[{'name': '@message_id', 'value': source_message_id}],
        enable_cross_partition_query=True,
    ))
    return items[0] if items else None


def _get_collaboration_display_role(message_doc):
    metadata = message_doc.get('metadata', {}) if isinstance(message_doc, dict) else {}
    source_role = str(metadata.get('source_role') or '').strip().lower()
    if source_role == 'safety':
        return 'assistant'
    if source_role in ('assistant', 'image', 'file'):
        return source_role

    role = str(message_doc.get('role') or '').strip().lower()
    return role or 'user'


def _build_collaboration_chat_context(conversation_doc, message_doc):
    scope = conversation_doc.get('scope', {}) if isinstance(conversation_doc, dict) else {}
    chat_type = str(conversation_doc.get('chat_type') or '').strip().lower()
    chat_scope = 'group' if chat_type == GROUP_MULTI_USER_CHAT_TYPE else 'personal'
    return {
        'conversation_id': message_doc.get('conversation_id') or conversation_doc.get('id'),
        'chat_type': chat_scope,
        'workspace_context': chat_scope,
        'group_id': scope.get('group_id'),
        'group_name': scope.get('group_name'),
        'conversation_title': conversation_doc.get('title'),
    }


def _build_collaboration_mentions(message_doc):
    metadata = message_doc.get('metadata', {}) if isinstance(message_doc, dict) else {}
    mentions = []
    seen_user_ids = set()
    for raw_participant in list(metadata.get('mentioned_participants', []) or []):
        participant = normalize_collaboration_user(raw_participant)
        if not participant:
            continue

        participant_user_id = participant['user_id']
        if participant_user_id in seen_user_ids:
            continue

        seen_user_ids.add(participant_user_id)
        mentions.append(participant)
    return mentions


def _build_collaboration_reply_context(message_doc):
    reply_to_message_id = str(message_doc.get('reply_to_message_id') or '').strip()
    if not reply_to_message_id:
        return None

    try:
        reply_message_doc = get_collaboration_message(reply_to_message_id)
    except CosmosResourceNotFoundError:
        return {
            'message_id': reply_to_message_id,
        }

    reply_metadata = reply_message_doc.get('metadata', {}) if isinstance(reply_message_doc, dict) else {}
    reply_sender = normalize_collaboration_user(reply_metadata.get('sender') or {}) or {
        'user_id': '',
        'display_name': 'Participant',
        'email': '',
    }
    reply_preview = str(reply_message_doc.get('content') or '').strip()
    if len(reply_preview) > 160:
        reply_preview = f'{reply_preview[:157]}...'

    return {
        'message_id': reply_message_doc.get('id') or reply_to_message_id,
        'sender_display_name': reply_sender.get('display_name') or 'Participant',
        'content_preview': reply_preview or 'No message content',
    }


def _build_collaboration_generation_details(message_doc, source_message_doc=None):
    generation_details = {}
    for field_name, value in {
        'selected_model': message_doc.get('model_deployment_name') or (source_message_doc or {}).get('model_deployment_name'),
        'agent_name': message_doc.get('agent_name') or (source_message_doc or {}).get('agent_name'),
        'agent_display_name': message_doc.get('agent_display_name') or (source_message_doc or {}).get('agent_display_name'),
        'augmented': message_doc.get('augmented') if 'augmented' in message_doc else (source_message_doc or {}).get('augmented'),
    }.items():
        if value not in (None, '', []):
            generation_details[field_name] = value

    hybrid_citations = list(message_doc.get('hybrid_citations', []) or (source_message_doc or {}).get('hybrid_citations', []) or [])
    web_search_citations = list(message_doc.get('web_search_citations', []) or (source_message_doc or {}).get('web_search_citations', []) or [])
    agent_citations = list(message_doc.get('agent_citations', []) or (source_message_doc or {}).get('agent_citations', []) or [])

    if hybrid_citations:
        generation_details['document_citation_count'] = len(hybrid_citations)
    if web_search_citations:
        generation_details['web_citation_count'] = len(web_search_citations)
    if agent_citations:
        generation_details['agent_citation_count'] = len(agent_citations)

    return generation_details


def resolve_collaboration_mentions(conversation_doc, raw_mentions):
    normalized_mentions = []
    if not isinstance(raw_mentions, list):
        return normalized_mentions

    accepted_participants = {}
    for participant in list((conversation_doc or {}).get('participants', []) or []):
        participant_user_id = str(participant.get('user_id') or '').strip()
        participant_status = str(participant.get('status') or '').strip().lower()
        if not participant_user_id or participant_status != MEMBERSHIP_STATUS_ACCEPTED:
            continue
        accepted_participants[participant_user_id] = participant

    seen_user_ids = set()
    for raw_participant in raw_mentions:
        candidate = normalize_collaboration_user(raw_participant)
        if not candidate:
            continue

        candidate_user_id = candidate['user_id']
        if candidate_user_id in seen_user_ids:
            continue

        participant = accepted_participants.get(candidate_user_id)
        if not participant:
            continue

        seen_user_ids.add(candidate_user_id)
        normalized_mentions.append({
            'user_id': candidate_user_id,
            'display_name': str(participant.get('display_name') or candidate.get('display_name') or '').strip() or 'Unknown User',
            'email': str(participant.get('email') or candidate.get('email') or '').strip(),
        })

    return normalized_mentions


def _get_group_collaboration_notification_recipient_ids(conversation_doc, sender_user_id):
    scope = conversation_doc.get('scope', {}) if isinstance(conversation_doc, dict) else {}
    group_id = str(scope.get('group_id') or '').strip()
    if not group_id:
        return []

    group_doc = find_group_by_id(group_id)
    if not group_doc:
        return []

    recipient_ids = set()
    owner_user_id = str((group_doc.get('owner') or {}).get('id') or '').strip()
    if owner_user_id:
        recipient_ids.add(owner_user_id)

    for member in list(group_doc.get('users', []) or []):
        member_user_id = str(member.get('userId') or '').strip()
        if member_user_id:
            recipient_ids.add(member_user_id)

    normalized_sender_user_id = str(sender_user_id or '').strip()
    if normalized_sender_user_id:
        recipient_ids.discard(normalized_sender_user_id)

    return sorted(recipient_ids)


def list_collaboration_notification_recipient_ids(conversation_doc, sender_user_id):
    if (
        is_group_collaboration_conversation(conversation_doc)
        and get_collaboration_visibility_mode(conversation_doc) == 'group_membership'
    ):
        return _get_group_collaboration_notification_recipient_ids(conversation_doc, sender_user_id)

    accepted_participant_ids = set(conversation_doc.get('accepted_participant_ids', []) or [])
    normalized_sender_user_id = str(sender_user_id or '').strip()
    if normalized_sender_user_id:
        accepted_participant_ids.discard(normalized_sender_user_id)

    return sorted(user_id for user_id in accepted_participant_ids if str(user_id or '').strip())


def create_collaboration_message_notifications(conversation_doc, message_doc):
    """Fan out personal inbox notifications for recipients of a shared message."""
    if not conversation_doc or not message_doc:
        return []

    metadata = message_doc.get('metadata', {}) if isinstance(message_doc, dict) else {}
    sender = normalize_collaboration_user(metadata.get('sender') or {}) or {}
    sender_user_id = str(sender.get('user_id') or '').strip()
    recipient_ids = list_collaboration_notification_recipient_ids(conversation_doc, sender_user_id)
    if not recipient_ids:
        return []

    mentioned_user_ids = {
        str(participant.get('user_id') or '').strip()
        for participant in list(metadata.get('mentioned_participants', []) or [])
        if str(participant.get('user_id') or '').strip()
    }
    scope = conversation_doc.get('scope', {}) if isinstance(conversation_doc, dict) else {}
    created_notifications = []

    for recipient_user_id in recipient_ids:
        try:
            notification_doc = create_collaboration_message_notification(
                user_id=recipient_user_id,
                conversation_id=message_doc.get('conversation_id'),
                message_id=message_doc.get('id'),
                conversation_title=conversation_doc.get('title'),
                sender_display_name=sender.get('display_name'),
                message_preview=message_doc.get('content'),
                chat_type=conversation_doc.get('chat_type'),
                group_id=scope.get('group_id'),
                mentioned_user=recipient_user_id in mentioned_user_ids,
            )
            if notification_doc:
                created_notifications.append(notification_doc)
        except Exception as exc:
            log_event(
                f'[Collaboration Notifications] Failed to create notification for conversation {message_doc.get("conversation_id")}: {exc}',
                level=logging.WARNING,
                exceptionTraceback=True,
                debug_only=True,
            )

    return created_notifications


def build_collaboration_message_metadata_payload(message_doc, conversation_doc):
    source_message_doc = _get_collaboration_source_message(message_doc)
    message_metadata = deepcopy(message_doc.get('metadata', {}) if isinstance(message_doc.get('metadata'), dict) else {})
    source_metadata = deepcopy(source_message_doc.get('metadata', {}) if isinstance((source_message_doc or {}).get('metadata'), dict) else {})
    merged_metadata = {
        **source_metadata,
        **message_metadata,
    }

    chat_context = _build_collaboration_chat_context(conversation_doc, message_doc)
    mentions = _build_collaboration_mentions(message_doc)
    reply_context = _build_collaboration_reply_context(message_doc)
    display_role = _get_collaboration_display_role(message_doc)
    sender_summary = normalize_collaboration_user(merged_metadata.get('sender') or {}) or {
        'user_id': '',
        'display_name': 'Unknown User',
        'email': '',
    }
    generation_details = _build_collaboration_generation_details(message_doc, source_message_doc=source_message_doc)
    collaboration_section = {
        'conversation_kind': conversation_doc.get('conversation_kind'),
        'conversation_title': conversation_doc.get('title'),
        'chat_type': conversation_doc.get('chat_type'),
        'participant_count': int(conversation_doc.get('participant_count', 0) or 0),
        'message_kind': message_doc.get('message_kind'),
        'display_role': display_role,
    }

    merged_metadata['chat_context'] = {
        **chat_context,
        **dict(merged_metadata.get('chat_context', {}) or {}),
    }
    merged_metadata['collaboration'] = {
        **dict(merged_metadata.get('collaboration', {}) or {}),
        **collaboration_section,
    }
    merged_metadata['user_info'] = {
        **dict(merged_metadata.get('user_info', {}) or {}),
        'user_id': sender_summary.get('user_id'),
        'display_name': sender_summary.get('display_name'),
        'email': sender_summary.get('email'),
        'username': sender_summary.get('user_id'),
        'timestamp': message_doc.get('timestamp'),
    }
    merged_metadata['message_details'] = {
        'message_id': message_doc.get('id'),
        'conversation_id': message_doc.get('conversation_id'),
        'role': message_doc.get('role'),
        'display_role': display_role,
        'message_kind': message_doc.get('message_kind'),
        'timestamp': message_doc.get('timestamp'),
        'source_role': merged_metadata.get('source_role'),
        'explicit_ai_invocation': bool(merged_metadata.get('explicit_ai_invocation', False)),
    }

    if mentions:
        merged_metadata['mentions'] = mentions
    if reply_context:
        merged_metadata['reply_context'] = reply_context
    if generation_details:
        merged_metadata['generation_details'] = generation_details

    if display_role == 'file':
        merged_metadata['file_details'] = {
            'filename': message_doc.get('filename') or (source_message_doc or {}).get('filename') or merged_metadata.get('legacy_filename'),
            'source_message_id': merged_metadata.get('source_message_id'),
            'is_table': (source_message_doc or {}).get('is_table'),
        }
    if display_role == 'image':
        collaboration_image_url = build_collaboration_image_url(
            message_doc.get('conversation_id'),
            message_doc.get('id'),
        )
        merged_metadata['image_details'] = {
            'filename': message_doc.get('filename') or (source_message_doc or {}).get('filename') or merged_metadata.get('legacy_filename'),
            'image_url': collaboration_image_url or merged_metadata.get('legacy_image_url') or (source_message_doc or {}).get('content'),
            'is_user_upload': bool(merged_metadata.get('is_user_upload', False)),
            'extracted_text': message_doc.get('extracted_text') or (source_message_doc or {}).get('extracted_text'),
            'vision_analysis': message_doc.get('vision_analysis') or (source_message_doc or {}).get('vision_analysis'),
        }

    if str(message_doc.get('role') or '').strip().lower() != 'assistant':
        return merged_metadata

    payload = deepcopy(source_message_doc or {})
    payload.update({
        'id': message_doc.get('id'),
        'conversation_id': message_doc.get('conversation_id'),
        'role': display_role,
        'message_kind': message_doc.get('message_kind'),
        'content': build_collaboration_image_url(message_doc.get('conversation_id'), message_doc.get('id')) if display_role == 'image' else message_doc.get('content'),
        'timestamp': message_doc.get('timestamp'),
        'model_deployment_name': message_doc.get('model_deployment_name') or payload.get('model_deployment_name'),
        'augmented': message_doc.get('augmented') if 'augmented' in message_doc else payload.get('augmented'),
        'hybrid_citations': deepcopy(message_doc.get('hybrid_citations', []) or payload.get('hybrid_citations', []) or []),
        'web_search_citations': deepcopy(message_doc.get('web_search_citations', []) or payload.get('web_search_citations', []) or []),
        'agent_citations': deepcopy(message_doc.get('agent_citations', []) or payload.get('agent_citations', []) or []),
        'agent_display_name': message_doc.get('agent_display_name') or payload.get('agent_display_name'),
        'agent_name': message_doc.get('agent_name') or payload.get('agent_name'),
        'filename': message_doc.get('filename') or payload.get('filename') or merged_metadata.get('legacy_filename'),
        'prompt': message_doc.get('prompt') or payload.get('prompt'),
        'is_table': message_doc.get('is_table') if 'is_table' in message_doc else payload.get('is_table'),
        'extracted_text': message_doc.get('extracted_text') or payload.get('extracted_text'),
        'vision_analysis': message_doc.get('vision_analysis') or payload.get('vision_analysis'),
    })
    payload['metadata'] = merged_metadata
    return payload


def serialize_collaboration_conversation(conversation_doc, current_user_id, user_state=None):
    conversation_doc = conversation_doc or {}
    participants = list(conversation_doc.get('participants', []) or [])
    visibility_mode = get_collaboration_visibility_mode(conversation_doc)
    membership_status = None
    if user_state:
        membership_status = user_state.get('membership_status')
    elif current_user_id in set(conversation_doc.get('accepted_participant_ids', []) or []):
        membership_status = MEMBERSHIP_STATUS_ACCEPTED
    elif is_group_collaboration_conversation(conversation_doc) and visibility_mode == 'group_membership':
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
        is_explicit_membership_collaboration(conversation_doc)
        and membership_status == MEMBERSHIP_STATUS_ACCEPTED
        and current_user_role in PERSONAL_COLLABORATION_MANAGER_ROLES
    )
    can_manage_roles = bool(
        is_explicit_membership_collaboration(conversation_doc)
        and membership_status == MEMBERSHIP_STATUS_ACCEPTED
        and current_user_role == MEMBERSHIP_ROLE_OWNER
    )
    can_accept_invite = membership_status == MEMBERSHIP_STATUS_PENDING
    can_post_messages = bool(
        (
            is_group_collaboration_conversation(conversation_doc)
            and visibility_mode == 'group_membership'
        )
        or membership_status == MEMBERSHIP_STATUS_ACCEPTED
    )
    can_delete_conversation = bool(
        is_explicit_membership_collaboration(conversation_doc)
        and membership_status == MEMBERSHIP_STATUS_ACCEPTED
        and current_user_role == MEMBERSHIP_ROLE_OWNER
    )
    can_leave_conversation = bool(
        is_explicit_membership_collaboration(conversation_doc)
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
        'visibility_mode': visibility_mode,
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


def _is_eligible_legacy_group_conversation(source_conversation_doc):
    if str((source_conversation_doc or {}).get('conversation_kind') or '').strip().lower() == COLLABORATION_KIND:
        return False

    chat_type = str((source_conversation_doc or {}).get('chat_type') or '').strip().lower()
    if chat_type in ('group-single-user', 'group_single_user', 'group'):
        return True

    primary_context = next(
        (
            context_item
            for context_item in list((source_conversation_doc or {}).get('context', []) or [])
            if context_item.get('type') == 'primary'
        ),
        None,
    )
    return bool(primary_context and str(primary_context.get('scope') or '').strip().lower() == 'group')


def _copy_legacy_group_messages_to_collaboration(source_conversation_id, collaboration_conversation_id, owner_user):
    query = 'SELECT * FROM c WHERE c.conversation_id = @conversation_id ORDER BY c.timestamp ASC'
    raw_messages = list(cosmos_group_messages_container.query_items(
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
        metadata.setdefault('source_conversation_scope', 'group')
        metadata.setdefault('source_thought_user_id', str((owner_user or {}).get('user_id') or '').strip())

        cosmos_collaboration_messages_container.upsert_item(collaboration_message)
        copied_messages.append(collaboration_message)

    return copied_messages


def ensure_group_collaboration_for_legacy_conversation(source_conversation_id, owner_user, invited_participants=None):
    source_conversation_doc = cosmos_group_conversations_container.read_item(
        item=source_conversation_id,
        partition_key=source_conversation_id,
    )
    owner_summary = owner_user or {}
    owner_user_id = str(owner_summary.get('user_id') or '').strip()
    if not owner_user_id:
        raise PermissionError('User not authenticated')

    if str(source_conversation_doc.get('user_id') or '').strip() != owner_user_id:
        raise PermissionError('Only the conversation owner can convert this group conversation')

    if not _is_eligible_legacy_group_conversation(source_conversation_doc):
        raise PermissionError('Only group single-user conversations can be converted into group multi-user conversations')

    primary_group_context = next(
        (
            context_item
            for context_item in list(source_conversation_doc.get('context', []) or [])
            if context_item.get('type') == 'primary' and str(context_item.get('scope') or '').strip().lower() == 'group'
        ),
        None,
    )
    group_id = str(
        source_conversation_doc.get('group_id')
        or (primary_group_context or {}).get('id')
        or ''
    ).strip()
    if not group_id:
        raise LookupError('Group conversation is missing group context')

    group_doc = find_group_by_id(group_id)
    if not group_doc:
        raise LookupError('Group not found')

    assert_group_role(
        owner_user_id,
        group_id,
        allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
    )
    allowed, reason = check_group_status_allows_operation(group_doc, 'chat')
    if not allowed:
        raise PermissionError(reason)

    collaboration_conversation_doc = None
    linked_collaboration_id = str(source_conversation_doc.get('collaboration_conversation_id') or '').strip()
    if linked_collaboration_id:
        try:
            collaboration_conversation_doc = get_collaboration_conversation(linked_collaboration_id)
        except CosmosResourceNotFoundError:
            collaboration_conversation_doc = None

    if collaboration_conversation_doc is not None:
        invited_state_docs = []
        if invited_participants:
            collaboration_conversation_doc, invited_state_docs = invite_personal_collaboration_participants(
                collaboration_conversation_doc.get('id'),
                owner_user_id,
                invited_participants,
            )
        return collaboration_conversation_doc, invited_state_docs, False, source_conversation_doc

    collaboration_conversation_doc, user_states = create_group_collaboration_conversation_record(
        title=source_conversation_doc.get('title') or '',
        creator_user=owner_summary,
        group_doc=group_doc,
        invited_participants=invited_participants,
    )
    invited_state_docs = [
        state_doc
        for state_doc in user_states
        if state_doc.get('user_id') != owner_user_id
    ]

    collaboration_conversation_doc['classification'] = list(source_conversation_doc.get('classification', []) or [])
    collaboration_conversation_doc['tags'] = list(source_conversation_doc.get('tags', []) or [])
    collaboration_conversation_doc['strict'] = bool(source_conversation_doc.get('strict', False))
    collaboration_conversation_doc['summary'] = source_conversation_doc.get('summary')
    collaboration_conversation_doc['legacy_source_conversation_id'] = source_conversation_id
    collaboration_conversation_doc['legacy_source_scope'] = 'group'

    source_context = list(source_conversation_doc.get('context', []) or [])
    if source_context:
        collaboration_conversation_doc['context'] = source_context
    source_scope_locked = source_conversation_doc.get('scope_locked')
    if source_scope_locked is not None:
        collaboration_conversation_doc['scope_locked'] = bool(source_scope_locked)
    source_locked_contexts = list(source_conversation_doc.get('locked_contexts', []) or [])
    if source_locked_contexts:
        collaboration_conversation_doc['locked_contexts'] = source_locked_contexts

    copied_messages = _copy_legacy_group_messages_to_collaboration(
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
    cosmos_group_conversations_container.upsert_item(source_conversation_doc)

    log_event(
        '[Collaboration] Converted group conversation into collaborative conversation',
        extra={
            'source_conversation_id': source_conversation_id,
            'conversation_id': collaboration_conversation_doc.get('id'),
            'group_id': group_id,
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


def create_group_collaboration_conversation_record(title, creator_user, group_doc, invited_participants=None):
    conversation_doc = build_group_collaboration_conversation(
        title=title,
        creator_user=creator_user,
        group_id=group_doc.get('id'),
        group_name=group_doc.get('name', 'Group Workspace'),
        invited_participants=_normalize_group_conversation_participants(
            group_doc,
            invited_participants,
        ) if invited_participants else None,
    )
    cosmos_collaboration_conversations_container.upsert_item(conversation_doc)

    user_states = []
    for participant in conversation_doc.get('participants', []):
        invited_by_user_id = ''
        if participant.get('user_id') != conversation_doc.get('created_by_user_id'):
            invited_by_user_id = conversation_doc.get('created_by_user_id')
        state_doc = ensure_collaboration_user_state_for_participant(
            conversation_doc,
            participant,
            role=participant.get('role') or MEMBERSHIP_ROLE_MEMBER,
            membership_status=participant.get('status') or MEMBERSHIP_STATUS_PENDING,
            invited_by_user_id=invited_by_user_id,
            created_at=participant.get('joined_at') or participant.get('invited_at') or conversation_doc.get('created_at'),
        )
        user_states.append(state_doc)

    log_event(
        '[Collaboration] Created group collaborative conversation',
        extra={
            'conversation_id': conversation_doc.get('id'),
            'group_id': group_doc.get('id'),
            'created_by_user_id': conversation_doc.get('created_by_user_id'),
            'participant_count': conversation_doc.get('participant_count', 0),
            'pending_invite_count': conversation_doc.get('pending_invite_count', 0),
        },
        level=logging.INFO,
    )
    return conversation_doc, user_states


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

    state_query = (
        'SELECT * FROM c WHERE c.user_id = @user_id '
        'AND c.conversation_kind = @conversation_kind'
    )
    state_docs = list(cosmos_collaboration_user_state_container.query_items(
        query=state_query,
        parameters=[
            {'name': '@user_id', 'value': user_id},
            {'name': '@conversation_kind', 'value': COLLABORATION_KIND},
        ],
        partition_key=user_id,
    ))

    conversations = []
    seen_conversation_ids = set()
    for state_doc in state_docs:
        membership_status = state_doc.get('membership_status')
        if membership_status not in (MEMBERSHIP_STATUS_ACCEPTED, MEMBERSHIP_STATUS_PENDING):
            continue
        if state_doc.get('chat_type') != GROUP_MULTI_USER_CHAT_TYPE:
            continue

        conversation_id = str(state_doc.get('conversation_id') or '').strip()
        if not conversation_id or conversation_id in seen_conversation_ids:
            continue

        try:
            conversation_doc = get_collaboration_conversation(conversation_id)
        except CosmosResourceNotFoundError:
            continue

        if not is_group_collaboration_conversation(conversation_doc):
            continue

        group_id = str((conversation_doc.get('scope') or {}).get('group_id') or '')
        group_doc = group_map.get(group_id)
        if not group_doc:
            continue

        allowed, _ = check_group_status_allows_operation(group_doc, 'view')
        if not allowed:
            continue

        seen_conversation_ids.add(conversation_id)
        conversations.append((conversation_doc, state_doc))

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

    for conversation_doc in items:
        if get_collaboration_visibility_mode(conversation_doc) != 'group_membership':
            continue

        conversation_id = str(conversation_doc.get('id') or '').strip()
        if not conversation_id or conversation_id in seen_conversation_ids:
            continue

        group_id = str((conversation_doc.get('scope') or {}).get('group_id') or '')
        group_doc = group_map.get(group_id)
        if not group_doc:
            continue

        allowed, _ = check_group_status_allows_operation(group_doc, 'view')
        if allowed:
            user_state = get_collaboration_user_state_or_none(user_id, conversation_id)
            conversations.append((conversation_doc, user_state))
            seen_conversation_ids.add(conversation_id)

    conversations.sort(
        key=lambda item: item[0].get('updated_at') or item[0].get('created_at') or '',
        reverse=True,
    )
    return conversations


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

        if get_collaboration_visibility_mode(conversation_doc) == 'group_membership':
            return {
                'group_doc': group_doc,
                'group_role': group_role,
                'membership_status': 'group_member',
                'user_state': get_collaboration_user_state_or_none(user_id, conversation_doc.get('id')),
            }

        user_state = get_collaboration_user_state_or_none(user_id, conversation_doc.get('id'))
        if user_state is None:
            participant = get_personal_collaboration_participant(conversation_doc, user_id)
            user_state = _bootstrap_collaboration_user_state_from_participant(
                conversation_doc,
                participant,
                invited_by_user_id=conversation_doc.get('created_by_user_id'),
            )

        if user_state is None:
            raise PermissionError('You are not a participant in this shared group conversation')

        membership_status = user_state.get('membership_status')
        if membership_status == MEMBERSHIP_STATUS_ACCEPTED:
            return {
                'group_doc': group_doc,
                'group_role': group_role,
                'user_state': user_state,
                'membership_status': membership_status,
            }
        if allow_pending and membership_status == MEMBERSHIP_STATUS_PENDING:
            return {
                'group_doc': group_doc,
                'group_role': group_role,
                'user_state': user_state,
                'membership_status': membership_status,
            }
        raise PermissionError('You do not have access to this shared group conversation')

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
    if not is_explicit_membership_collaboration(conversation_doc):
        raise PermissionError('Invite responses are only supported for invite-managed collaborative conversations')

    if is_group_collaboration_conversation(conversation_doc):
        group_id = str(((conversation_doc.get('scope') or {}).get('group_id')) or '').strip()
        assert_group_role(
            user_id,
            group_id,
            allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
        )

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
    if not is_explicit_membership_collaboration(conversation_doc):
        raise PermissionError('Member invites are only supported for invite-managed collaborative conversations')

    actor_user_state = get_collaboration_user_state_or_none(owner_user_id, conversation_id)

    if is_group_collaboration_conversation(conversation_doc):
        group_id = str(((conversation_doc.get('scope') or {}).get('group_id')) or '').strip()
        group_role = assert_group_role(
            owner_user_id,
            group_id,
            allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
        )
        group_doc = find_group_by_id(group_id)
        if not group_doc:
            raise LookupError('Group not found')
        allowed, reason = check_group_status_allows_operation(group_doc, 'chat')
        if not allowed:
            raise PermissionError(reason)
        participants_to_add = _normalize_group_conversation_participants(group_doc, participants_to_add)

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
    if not is_explicit_membership_collaboration(conversation_doc):
        raise PermissionError('Member removal is only supported for invite-managed collaborative conversations')

    actor_user_state = get_collaboration_user_state_or_none(owner_user_id, conversation_id)

    if is_group_collaboration_conversation(conversation_doc):
        group_id = str(((conversation_doc.get('scope') or {}).get('group_id')) or '').strip()
        group_role = assert_group_role(
            owner_user_id,
            group_id,
            allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
        )
        group_doc = find_group_by_id(group_id)
        if not group_doc:
            raise LookupError('Group not found')
        allowed, reason = check_group_status_allows_operation(group_doc, 'chat')
        if not allowed:
            raise PermissionError(reason)

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


def persist_collaboration_message(
    conversation_doc,
    sender_user,
    content,
    reply_to_message_id=None,
    mentioned_participants=None,
    message_kind=MESSAGE_KIND_HUMAN,
    extra_metadata=None,
):
    conversation_id = conversation_doc.get('id')
    message_doc = build_collaboration_message_doc(
        conversation_id=conversation_id,
        sender_user=sender_user,
        content=content,
        reply_to_message_id=reply_to_message_id,
        mentioned_participants=mentioned_participants,
        message_kind=message_kind,
        timestamp=utc_now_iso(),
    )

    if isinstance(extra_metadata, dict) and extra_metadata:
        message_doc['metadata'] = {
            **dict(message_doc.get('metadata', {}) or {}),
            **extra_metadata,
        }

    return _save_collaboration_message_doc(conversation_doc, message_doc)


def _save_collaboration_message_doc(conversation_doc, message_doc):
    sender_summary = normalize_collaboration_user(
        ((message_doc or {}).get('metadata', {}) or {}).get('sender') or {},
    )

    if is_group_collaboration_conversation(conversation_doc):
        sender_user_id = str((sender_summary or {}).get('user_id') or '').strip()
        if sender_user_id and sender_user_id != 'assistant' and str(message_doc.get('role') or '').strip().lower() == 'user':
            if get_collaboration_visibility_mode(conversation_doc) == 'group_membership':
                ensure_group_participant_record(
                    conversation_doc,
                    sender_summary,
                    joined_at=message_doc.get('timestamp'),
                )
            else:
                participant_record = get_personal_collaboration_participant(
                    conversation_doc,
                    sender_user_id,
                )
                if participant_record is not None:
                    participant_record['display_name'] = sender_summary.get('display_name') or participant_record.get('display_name')
                    participant_record['email'] = sender_summary.get('email') or participant_record.get('email')

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


def sync_collaboration_conversation_metadata_from_source(conversation_doc, source_conversation_doc):
    if not isinstance(conversation_doc, dict) or not isinstance(source_conversation_doc, dict):
        return conversation_doc, False

    metadata_fields = {
        'context': deepcopy(list(source_conversation_doc.get('context', []) or [])),
        'tags': deepcopy(list(source_conversation_doc.get('tags', []) or [])),
        'strict': bool(source_conversation_doc.get('strict', False)),
        'scope_locked': bool(source_conversation_doc.get('scope_locked', conversation_doc.get('scope_locked', False))),
        'locked_contexts': deepcopy(list(source_conversation_doc.get('locked_contexts', []) or [])),
        'classification': deepcopy(list(source_conversation_doc.get('classification', []) or [])),
        'summary': deepcopy(source_conversation_doc.get('summary')),
    }

    updated = False
    for field_name, field_value in metadata_fields.items():
        if conversation_doc.get(field_name) != field_value:
            conversation_doc[field_name] = field_value
            updated = True

    if updated:
        cosmos_collaboration_conversations_container.upsert_item(conversation_doc)

    return conversation_doc, updated


def ensure_collaboration_source_conversation(conversation_doc, current_user):
    normalized_current_user = normalize_collaboration_user(current_user)
    if not normalized_current_user:
        raise PermissionError('User not authenticated')

    source_conversation_id = str((conversation_doc or {}).get('source_conversation_id') or '').strip()
    source_conversation_doc = None
    source_updated = False

    if source_conversation_id:
        try:
            source_conversation_doc = cosmos_conversations_container.read_item(
                item=source_conversation_id,
                partition_key=source_conversation_id,
            )
        except CosmosResourceNotFoundError:
            source_conversation_doc = None
            source_conversation_id = ''

    timestamp = utc_now_iso()
    if source_conversation_doc is None:
        source_conversation_id = str(uuid.uuid4())
        source_conversation_doc = {
            'id': source_conversation_id,
            'user_id': str((conversation_doc or {}).get('created_by_user_id') or normalized_current_user.get('user_id') or '').strip(),
            'last_updated': timestamp,
            'title': str((conversation_doc or {}).get('title') or 'Collaborative Conversation').strip() or 'Collaborative Conversation',
            'context': list((conversation_doc or {}).get('context', []) or []),
            'tags': list((conversation_doc or {}).get('tags', []) or []),
            'strict': bool((conversation_doc or {}).get('strict', False)),
            'chat_type': 'group' if is_group_collaboration_conversation(conversation_doc) else 'personal_single_user',
            'scope_locked': bool((conversation_doc or {}).get('scope_locked', False)),
            'locked_contexts': list((conversation_doc or {}).get('locked_contexts', []) or []),
            'classification': list((conversation_doc or {}).get('classification', []) or []),
            'summary': (conversation_doc or {}).get('summary'),
            'conversation_kind': 'collaboration_source',
            'collaboration_conversation_id': (conversation_doc or {}).get('id'),
            'is_hidden': True,
        }
        source_updated = True
    else:
        synchronized_values = {
            'title': str((conversation_doc or {}).get('title') or source_conversation_doc.get('title') or 'Collaborative Conversation').strip() or 'Collaborative Conversation',
            'context': list((conversation_doc or {}).get('context', []) or source_conversation_doc.get('context', []) or []),
            'tags': list((conversation_doc or {}).get('tags', []) or source_conversation_doc.get('tags', []) or []),
            'strict': bool((conversation_doc or {}).get('strict', source_conversation_doc.get('strict', False))),
            'scope_locked': bool((conversation_doc or {}).get('scope_locked', source_conversation_doc.get('scope_locked', False))),
            'locked_contexts': list((conversation_doc or {}).get('locked_contexts', []) or source_conversation_doc.get('locked_contexts', []) or []),
            'classification': list((conversation_doc or {}).get('classification', []) or source_conversation_doc.get('classification', []) or []),
            'summary': (conversation_doc or {}).get('summary', source_conversation_doc.get('summary')),
            'conversation_kind': 'collaboration_source',
            'collaboration_conversation_id': (conversation_doc or {}).get('id'),
            'is_hidden': True,
        }
        for field_name, field_value in synchronized_values.items():
            if source_conversation_doc.get(field_name) != field_value:
                source_conversation_doc[field_name] = field_value
                source_updated = True

    if source_updated:
        source_conversation_doc['last_updated'] = timestamp
        cosmos_conversations_container.upsert_item(source_conversation_doc)

    if str((conversation_doc or {}).get('source_conversation_id') or '').strip() != source_conversation_id:
        conversation_doc['source_conversation_id'] = source_conversation_id
        cosmos_collaboration_conversations_container.upsert_item(conversation_doc)

    return source_conversation_doc, conversation_doc


def mirror_source_message_to_collaboration(
    conversation_doc,
    source_message_doc,
    default_sender_user,
    reply_to_message_id=None,
    extra_metadata=None,
):
    source_message_id = str((source_message_doc or {}).get('id') or '').strip()
    if not source_message_id:
        raise ValueError('source_message_doc.id is required')

    existing_message = get_collaboration_message_by_source_message(
        (conversation_doc or {}).get('id'),
        source_message_id,
    )
    if existing_message:
        return existing_message, conversation_doc, False

    collaboration_message = build_collaboration_message_doc_from_legacy(
        (conversation_doc or {}).get('id'),
        source_message_doc,
        default_sender_user,
    )
    if not collaboration_message:
        return None, conversation_doc, False

    source_role = str((source_message_doc or {}).get('role') or '').strip().lower()
    source_metadata = (source_message_doc or {}).get('metadata', {}) if isinstance((source_message_doc or {}).get('metadata'), dict) else {}
    message_metadata = collaboration_message.setdefault('metadata', {})
    message_metadata.setdefault('source_message_id', source_message_id)
    message_metadata.setdefault('source_conversation_id', str((conversation_doc or {}).get('source_conversation_id') or '').strip() or None)
    message_metadata.setdefault('source_thought_user_id', str((default_sender_user or {}).get('user_id') or (conversation_doc or {}).get('created_by_user_id') or '').strip())

    if isinstance(extra_metadata, dict) and extra_metadata:
        message_metadata.update(extra_metadata)

    if reply_to_message_id:
        collaboration_message['reply_to_message_id'] = str(reply_to_message_id or '').strip() or None

    if source_role == 'image':
        message_metadata['last_message_preview'] = '[Uploaded image]' if bool(source_metadata.get('is_user_upload')) else '[Generated image]'

    return (*_save_collaboration_message_doc(conversation_doc, collaboration_message), True)


def _refresh_collaboration_conversation_message_summary(conversation_doc):
    conversation_id = str((conversation_doc or {}).get('id') or '').strip()
    if not conversation_id:
        raise ValueError('conversation_id is required')

    remaining_messages = list_collaboration_messages(conversation_id)
    conversation_doc['message_count'] = len(remaining_messages)

    if remaining_messages:
        last_message_doc = remaining_messages[-1]
        last_message_timestamp = last_message_doc.get('timestamp') or utc_now_iso()
        conversation_doc['last_message_at'] = last_message_timestamp
        conversation_doc['last_message_preview'] = (
            (last_message_doc.get('metadata') or {}).get('last_message_preview') or ''
        )
        conversation_doc['updated_at'] = last_message_timestamp
    else:
        conversation_doc['last_message_at'] = None
        conversation_doc['last_message_preview'] = ''
        conversation_doc['updated_at'] = utc_now_iso()

    cosmos_collaboration_conversations_container.upsert_item(conversation_doc)
    return conversation_doc


def delete_collaboration_message(conversation_id, message_id, current_user_id):
    conversation_doc = get_collaboration_conversation(conversation_id)
    access_context = assert_user_can_participate_in_collaboration_conversation(
        current_user_id,
        conversation_doc,
    )
    message_doc = get_collaboration_message(message_id)

    if str(message_doc.get('conversation_id') or '').strip() != str(conversation_id or '').strip():
        raise LookupError('Collaborative message not found in this conversation')

    metadata = message_doc.get('metadata', {}) if isinstance(message_doc, dict) else {}
    sender_user_id = str(
        ((metadata.get('sender') or {}).get('user_id'))
        or ((metadata.get('user_info') or {}).get('user_id'))
        or ''
    ).strip()
    normalized_current_user_id = str(current_user_id or '').strip()

    can_delete_message = sender_user_id == normalized_current_user_id
    if not can_delete_message and is_personal_collaboration_conversation(conversation_doc):
        actor_role = get_personal_collaboration_role(
            conversation_doc,
            normalized_current_user_id,
            user_state=access_context.get('user_state'),
        )
        can_delete_message = actor_role in PERSONAL_COLLABORATION_MANAGER_ROLES
    elif not can_delete_message and is_group_collaboration_conversation(conversation_doc):
        can_delete_message = access_context.get('group_role') in ('Owner', 'Admin', 'DocumentManager')

    if not can_delete_message:
        raise PermissionError('You can only delete your own shared messages')

    cosmos_collaboration_messages_container.delete_item(
        item=message_id,
        partition_key=conversation_id,
    )
    updated_conversation_doc = _refresh_collaboration_conversation_message_summary(conversation_doc)
    return message_doc, updated_conversation_doc


def update_personal_collaboration_title(conversation_id, current_user_id, new_title):
    conversation_doc = get_collaboration_conversation(conversation_id)
    if not is_collaboration_conversation(conversation_doc):
        raise PermissionError('Title updates are only supported for collaborative conversations')
    if is_group_collaboration_conversation(conversation_doc):
        group_id = str(((conversation_doc.get('scope') or {}).get('group_id')) or '').strip()
        assert_group_role(
            current_user_id,
            group_id,
            allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
        )
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
    if not is_collaboration_conversation(conversation_doc):
        raise PermissionError('Pin is only supported for collaborative conversations')

    access_context = assert_user_can_view_collaboration_conversation(
        current_user_id,
        conversation_doc,
        allow_pending=True,
    )
    user_state = access_context.get('user_state')
    if user_state is None:
        if is_group_collaboration_conversation(conversation_doc):
            participant_summary = _resolve_group_member_summary(access_context.get('group_doc'), current_user_id) or {
                'user_id': current_user_id,
                'display_name': 'Group Member',
                'email': '',
            }
            user_state = ensure_collaboration_user_state_for_participant(
                conversation_doc,
                participant_summary,
                role=get_personal_collaboration_role(conversation_doc, current_user_id) or MEMBERSHIP_ROLE_MEMBER,
                membership_status=MEMBERSHIP_STATUS_ACCEPTED,
                invited_by_user_id='',
                created_at=conversation_doc.get('created_at'),
            )
        else:
            user_state = get_collaboration_user_state(current_user_id, conversation_id)

    user_state['is_pinned'] = not bool(user_state.get('is_pinned', False))
    user_state['updated_at'] = utc_now_iso()
    cosmos_collaboration_user_state_container.upsert_item(user_state)
    return conversation_doc, user_state


def toggle_personal_collaboration_hide(conversation_id, current_user_id):
    conversation_doc = get_collaboration_conversation(conversation_id)
    if not is_collaboration_conversation(conversation_doc):
        raise PermissionError('Hide is only supported for collaborative conversations')

    access_context = assert_user_can_view_collaboration_conversation(
        current_user_id,
        conversation_doc,
        allow_pending=True,
    )
    user_state = access_context.get('user_state')
    if user_state is None:
        if is_group_collaboration_conversation(conversation_doc):
            participant_summary = _resolve_group_member_summary(access_context.get('group_doc'), current_user_id) or {
                'user_id': current_user_id,
                'display_name': 'Group Member',
                'email': '',
            }
            user_state = ensure_collaboration_user_state_for_participant(
                conversation_doc,
                participant_summary,
                role=get_personal_collaboration_role(conversation_doc, current_user_id) or MEMBERSHIP_ROLE_MEMBER,
                membership_status=MEMBERSHIP_STATUS_ACCEPTED,
                invited_by_user_id='',
                created_at=conversation_doc.get('created_at'),
            )
        else:
            user_state = get_collaboration_user_state(current_user_id, conversation_id)

    user_state['is_hidden'] = not bool(user_state.get('is_hidden', False))
    user_state['updated_at'] = utc_now_iso()
    cosmos_collaboration_user_state_container.upsert_item(user_state)
    return conversation_doc, user_state


def update_personal_collaboration_member_role(conversation_id, current_user_id, member_user_id, new_role):
    conversation_doc = get_collaboration_conversation(conversation_id)
    if not is_explicit_membership_collaboration(conversation_doc):
        raise PermissionError('Role updates are only supported for invite-managed collaborative conversations')
    if is_group_collaboration_conversation(conversation_doc):
        group_id = str(((conversation_doc.get('scope') or {}).get('group_id')) or '').strip()
        group_doc = find_group_by_id(group_id)
        if not group_doc:
            raise LookupError('Group not found')
        assert_group_role(
            current_user_id,
            group_id,
            allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
        )
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

    user_state = get_collaboration_user_state_or_none(member_user_id, conversation_id)

    if user_state:
        user_state['role'] = normalized_role
        user_state['updated_at'] = timestamp
        cosmos_collaboration_user_state_container.upsert_item(user_state)

    return conversation_doc, participant


def leave_personal_collaboration_conversation(conversation_id, current_user_id, new_owner_user_id=None):
    conversation_doc = get_collaboration_conversation(conversation_id)
    if not is_explicit_membership_collaboration(conversation_doc):
        raise PermissionError('Leave is only supported for invite-managed collaborative conversations')
    if is_group_collaboration_conversation(conversation_doc):
        group_id = str(((conversation_doc.get('scope') or {}).get('group_id')) or '').strip()
        group_doc = find_group_by_id(group_id)
        if not group_doc:
            raise LookupError('Group not found')
        assert_group_role(
            current_user_id,
            group_id,
            allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
        )
        allowed, reason = check_group_status_allows_operation(group_doc, 'chat')
        if not allowed:
            raise PermissionError(reason)

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


def _delete_source_group_conversation(conversation_doc, current_user_id):
    source_conversation_id = str((conversation_doc or {}).get('legacy_source_conversation_id') or '').strip()
    if not source_conversation_id:
        return

    try:
        source_conversation = cosmos_group_conversations_container.read_item(
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
    source_messages = list(cosmos_group_messages_container.query_items(
        query=message_query,
        parameters=[{'name': '@conversation_id', 'value': source_conversation_id}],
        partition_key=source_conversation_id,
    ))

    for message_doc in source_messages:
        cosmos_group_messages_container.delete_item(
            item=message_doc.get('id'),
            partition_key=source_conversation_id,
        )

    delete_thoughts_for_conversation(source_conversation_id, current_user_id)
    cosmos_group_conversations_container.delete_item(
        item=source_conversation_id,
        partition_key=source_conversation_id,
    )


def delete_personal_collaboration_conversation(conversation_id, current_user_id):
    conversation_doc = get_collaboration_conversation(conversation_id)
    if not is_explicit_membership_collaboration(conversation_doc):
        raise PermissionError('Delete is only supported for invite-managed collaborative conversations')
    if is_group_collaboration_conversation(conversation_doc):
        group_id = str(((conversation_doc.get('scope') or {}).get('group_id')) or '').strip()
        group_doc = find_group_by_id(group_id)
        if not group_doc:
            raise LookupError('Group not found')
        assert_group_role(
            current_user_id,
            group_id,
            allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
        )
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
    if is_group_collaboration_conversation(conversation_doc):
        _delete_source_group_conversation(conversation_doc, current_user_id)
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