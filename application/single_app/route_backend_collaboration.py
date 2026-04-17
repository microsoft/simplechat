# route_backend_collaboration.py

import json
import threading
import time

import app_settings_cache
from flask import Response, current_app, jsonify, request, session, stream_with_context

from config import *
from collaboration_models import MEMBERSHIP_STATUS_PENDING, MESSAGE_KIND_AI_REQUEST, add_seconds_to_iso, normalize_collaboration_user, utc_now_iso
from functions_appinsights import log_event
from functions_authentication import *
from functions_collaboration import (
    assert_user_can_participate_in_collaboration_conversation,
    assert_user_can_view_collaboration_conversation,
    create_collaboration_message_notifications,
    create_group_collaboration_conversation_record,
    create_personal_collaboration_conversation_record,
    delete_collaboration_message,
    delete_personal_collaboration_conversation,
    ensure_collaboration_source_conversation,
    ensure_personal_collaboration_for_legacy_conversation,
    get_collaboration_conversation,
    get_collaboration_user_state,
    invite_personal_collaboration_participants,
    leave_personal_collaboration_conversation,
    list_collaboration_messages,
    list_group_collaboration_conversations_for_user,
    list_personal_collaboration_conversations_for_user,
    mirror_source_message_to_collaboration,
    persist_collaboration_message,
    record_personal_invite_response,
    remove_personal_collaboration_member,
    resolve_collaboration_mentions,
    serialize_collaboration_conversation,
    serialize_collaboration_message,
    sync_collaboration_conversation_metadata_from_source,
    toggle_personal_collaboration_hide,
    toggle_personal_collaboration_pin,
    update_personal_collaboration_member_role,
    update_personal_collaboration_title,
)
from functions_group import assert_group_role, check_group_status_allows_operation, find_group_by_id
from functions_notifications import mark_collaboration_message_notifications_read_for_conversation
from functions_settings import get_settings, get_user_settings
from swagger_wrapper import swagger_route, get_auth_security


COLLABORATION_EVENT_HEARTBEAT_SECONDS = 15
COLLABORATION_EVENT_TTL_SECONDS = 3600


class CollaborationEventSession:
    HEARTBEAT_EVENT = ': keep-alive\n\n'

    def __init__(self, conversation_id, heartbeat_interval_seconds=15, session_ttl_seconds=3600):
        self.conversation_id = conversation_id
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.session_ttl_seconds = session_ttl_seconds
        self.cache_key = f'collaboration:{conversation_id}'
        self._condition = threading.Condition()

    def _build_metadata(self):
        return {
            'conversation_id': self.conversation_id,
            'active': True,
            'heartbeat_interval_seconds': self.heartbeat_interval_seconds,
            'updated_at': utc_now_iso(),
        }

    def initialize(self):
        existing_metadata = app_settings_cache.get_stream_session_meta(self.cache_key)
        if existing_metadata:
            app_settings_cache.set_stream_session_meta(
                self.cache_key,
                self._build_metadata(),
                ttl_seconds=self.session_ttl_seconds,
            )
            return

        app_settings_cache.initialize_stream_session_cache(
            self.cache_key,
            self._build_metadata(),
            ttl_seconds=self.session_ttl_seconds,
        )

    def publish(self, event_payload):
        self.initialize()
        event_text = f'data: {json.dumps(event_payload)}\n\n'
        app_settings_cache.append_stream_session_event(
            self.cache_key,
            event_text,
            ttl_seconds=self.session_ttl_seconds,
        )
        app_settings_cache.set_stream_session_meta(
            self.cache_key,
            self._build_metadata(),
            ttl_seconds=self.session_ttl_seconds,
        )
        with self._condition:
            self._condition.notify_all()

    def iter_events(self, start_index=0):
        self.initialize()
        next_index = max(int(start_index or 0), 0)
        last_heartbeat_at = time.time()

        while True:
            pending_events = app_settings_cache.get_stream_session_events(
                self.cache_key,
                start_index=next_index,
            ) or []
            if pending_events:
                for event_to_yield in pending_events:
                    next_index += 1
                    last_heartbeat_at = time.time()
                    yield event_to_yield
                continue

            metadata = app_settings_cache.get_stream_session_meta(self.cache_key)
            if not metadata:
                self.initialize()
                metadata = app_settings_cache.get_stream_session_meta(self.cache_key)
            if not metadata:
                return

            heartbeat_interval_seconds = int(
                metadata.get('heartbeat_interval_seconds') or self.heartbeat_interval_seconds
            )
            remaining_heartbeat_seconds = max(
                heartbeat_interval_seconds - (time.time() - last_heartbeat_at),
                0.25,
            )
            with self._condition:
                self._condition.wait(timeout=min(1.0, remaining_heartbeat_seconds))

            if (time.time() - last_heartbeat_at) >= heartbeat_interval_seconds:
                last_heartbeat_at = time.time()
                yield self.HEARTBEAT_EVENT


class CollaborationEventRegistry:
    def __init__(self, heartbeat_interval_seconds=15, session_ttl_seconds=3600):
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.session_ttl_seconds = session_ttl_seconds
        self._sessions = {}
        self._lock = threading.Lock()

    def get_session(self, conversation_id):
        with self._lock:
            session = self._sessions.get(conversation_id)
            if session is None:
                session = CollaborationEventSession(
                    conversation_id=conversation_id,
                    heartbeat_interval_seconds=self.heartbeat_interval_seconds,
                    session_ttl_seconds=self.session_ttl_seconds,
                )
                self._sessions[conversation_id] = session
            session.initialize()
            return session

    def publish(self, conversation_id, event_payload):
        self.get_session(conversation_id).publish(event_payload)


COLLABORATION_EVENT_REGISTRY = CollaborationEventRegistry(
    heartbeat_interval_seconds=COLLABORATION_EVENT_HEARTBEAT_SECONDS,
    session_ttl_seconds=COLLABORATION_EVENT_TTL_SECONDS,
)


def get_user_state_or_none(user_id, conversation_id):
    try:
        return get_collaboration_user_state(user_id, conversation_id)
    except CosmosResourceNotFoundError:
        return None


def _build_collaboration_event(conversation_id, event_type, payload):
    return {
        'conversation_id': conversation_id,
        'event_type': event_type,
        'occurred_at': utc_now_iso(),
        'payload': payload,
    }


def _require_collaboration_feature_enabled():
    settings = get_settings()
    if not settings.get('enable_collaborative_conversations', False):
        raise PermissionError('Collaborative conversations are disabled by configuration')
    return settings


def _get_current_collaboration_user():
    current_user = get_current_user_info()
    return normalize_collaboration_user(current_user)


def _normalize_participant_payload(raw_payload):
    if raw_payload is None:
        return []
    if isinstance(raw_payload, dict):
        raw_payload = [raw_payload]

    normalized_participants = []
    for raw_participant in raw_payload:
        participant_summary = normalize_collaboration_user(raw_participant)
        if participant_summary:
            normalized_participants.append(participant_summary)
    return normalized_participants


def _read_source_message_doc(source_conversation_id, source_message_id):
    normalized_conversation_id = str(source_conversation_id or '').strip()
    normalized_message_id = str(source_message_id or '').strip()
    if not normalized_conversation_id or not normalized_message_id:
        raise CosmosResourceNotFoundError(message='Source message not found')

    try:
        return cosmos_messages_container.read_item(
            item=normalized_message_id,
            partition_key=normalized_conversation_id,
        )
    except CosmosResourceNotFoundError:
        query = 'SELECT TOP 1 * FROM c WHERE c.id = @message_id'
        items = list(cosmos_messages_container.query_items(
            query=query,
            parameters=[{'name': '@message_id', 'value': normalized_message_id}],
            enable_cross_partition_query=True,
        ))
        if not items:
            raise
        return items[0]


def _serialize_stream_error(error_message, **extra_fields):
    payload = {'error': str(error_message or 'Streaming request failed')}
    payload.update({key: value for key, value in extra_fields.items() if value is not None})
    return f'data: {json.dumps(payload)}\n\n'


def _build_collaboration_stream_request_payload(data, source_conversation_id, message_content):
    return {
        'message': message_content,
        'conversation_id': source_conversation_id,
        'hybrid_search': bool(data.get('hybrid_search')),
        'web_search_enabled': bool(data.get('web_search_enabled')),
        'selected_document_id': data.get('selected_document_id'),
        'selected_document_ids': data.get('selected_document_ids') or [],
        'classifications': data.get('classifications'),
        'tags': data.get('tags') or [],
        'image_generation': bool(data.get('image_generation')),
        'doc_scope': data.get('doc_scope'),
        'chat_type': data.get('chat_type', 'user'),
        'active_group_ids': data.get('active_group_ids') or [],
        'active_group_id': data.get('active_group_id'),
        'active_public_workspace_ids': data.get('active_public_workspace_ids') or [],
        'active_public_workspace_id': data.get('active_public_workspace_id'),
        'model_deployment': data.get('model_deployment'),
        'model_id': data.get('model_id'),
        'model_endpoint_id': data.get('model_endpoint_id'),
        'model_provider': data.get('model_provider'),
        'prompt_info': data.get('prompt_info'),
        'agent_info': data.get('agent_info'),
        'reasoning_effort': data.get('reasoning_effort'),
    }


def register_route_backend_collaboration(app):
    @app.route('/api/collaboration/conversations', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def list_collaboration_conversations_api():
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            scope_filter = str(request.args.get('scope') or 'all').strip().lower()
            include_pending = str(request.args.get('include_pending', 'true')).strip().lower() != 'false'
            conversations = []

            if scope_filter in ('all', 'personal'):
                for conversation_doc, user_state in list_personal_collaboration_conversations_for_user(current_user['user_id']):
                    serialized = serialize_collaboration_conversation(
                        conversation_doc,
                        current_user_id=current_user['user_id'],
                        user_state=user_state,
                    )
                    if include_pending or serialized.get('membership_status') != MEMBERSHIP_STATUS_PENDING:
                        conversations.append(serialized)

            if scope_filter in ('all', 'group'):
                for conversation_doc in list_group_collaboration_conversations_for_user(current_user['user_id']):
                    conversations.append(serialize_collaboration_conversation(
                        conversation_doc,
                        current_user_id=current_user['user_id'],
                    ))

            conversations.sort(
                key=lambda item: item.get('updated_at') or item.get('created_at') or '',
                reverse=True,
            )
            return jsonify({'conversations': conversations}), 200
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to list conversations: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to load collaborative conversations'}), 500

    @app.route('/api/collaboration/conversations', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def create_collaboration_conversation_api():
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            data = request.get_json(silent=True) or {}
            conversation_type = str(data.get('conversation_type') or '').strip().lower()
            title = str(data.get('title') or '').strip()

            if conversation_type == 'personal':
                participants_to_invite = _normalize_participant_payload(data.get('participants', []))
                conversation_doc, user_states = create_personal_collaboration_conversation_record(
                    title=title,
                    creator_user=current_user,
                    invited_participants=participants_to_invite,
                )
                creator_state = next(
                    (state for state in user_states if state.get('user_id') == current_user['user_id']),
                    None,
                )
                serialized = serialize_collaboration_conversation(
                    conversation_doc,
                    current_user_id=current_user['user_id'],
                    user_state=creator_state,
                )
                COLLABORATION_EVENT_REGISTRY.publish(
                    conversation_doc.get('id'),
                    _build_collaboration_event(
                        conversation_doc.get('id'),
                        'collaboration.created',
                        {'conversation': serialized},
                    ),
                )
                return jsonify({'conversation': serialized}), 201

            if conversation_type == 'group':
                group_id = str(data.get('group_id') or '').strip()
                if not group_id:
                    user_settings = get_user_settings(current_user['user_id'])
                    group_id = str(
                        ((user_settings or {}).get('settings') or {}).get('activeGroupOid') or ''
                    ).strip()
                if not group_id:
                    return jsonify({'error': 'group_id is required for group collaborative conversations'}), 400

                group_doc = find_group_by_id(group_id)
                if not group_doc:
                    return jsonify({'error': 'Group not found'}), 404

                assert_group_role(
                    current_user['user_id'],
                    group_id,
                    allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
                )
                allowed, reason = check_group_status_allows_operation(group_doc, 'chat')
                if not allowed:
                    return jsonify({'error': reason}), 403

                conversation_doc = create_group_collaboration_conversation_record(
                    title=title,
                    creator_user=current_user,
                    group_doc=group_doc,
                )
                serialized = serialize_collaboration_conversation(
                    conversation_doc,
                    current_user_id=current_user['user_id'],
                )
                COLLABORATION_EVENT_REGISTRY.publish(
                    conversation_doc.get('id'),
                    _build_collaboration_event(
                        conversation_doc.get('id'),
                        'collaboration.created',
                        {'conversation': serialized},
                    ),
                )
                return jsonify({'conversation': serialized}), 201

            return jsonify({'error': 'conversation_type must be personal or group'}), 400
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to create conversation: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to create collaborative conversation'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_collaboration_conversation_api(conversation_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            conversation_doc = get_collaboration_conversation(conversation_id)
            access_context = assert_user_can_view_collaboration_conversation(
                current_user['user_id'],
                conversation_doc,
                allow_pending=True,
            )
            serialized = serialize_collaboration_conversation(
                conversation_doc,
                current_user_id=current_user['user_id'],
                user_state=access_context.get('user_state'),
            )
            return jsonify({'conversation': serialized}), 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative conversation not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to load conversation {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to load collaborative conversation'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>/invite-response', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def respond_to_collaboration_invite_api(conversation_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            data = request.get_json(silent=True) or {}
            action = str(data.get('action') or '').strip().lower()
            if action not in ('accept', 'decline'):
                return jsonify({'error': 'action must be accept or decline'}), 400

            conversation_doc, user_state, participant_record = record_personal_invite_response(
                conversation_id,
                current_user['user_id'],
                action,
            )
            serialized = serialize_collaboration_conversation(
                conversation_doc,
                current_user_id=current_user['user_id'],
                user_state=user_state,
            )
            event_type = 'collaboration.invite.accepted' if action == 'accept' else 'collaboration.invite.declined'
            COLLABORATION_EVENT_REGISTRY.publish(
                conversation_id,
                _build_collaboration_event(
                    conversation_id,
                    event_type,
                    {
                        'conversation': serialized,
                        'participant': participant_record,
                    },
                ),
            )
            return jsonify({'conversation': serialized}), 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative conversation not found'}), 404
        except (LookupError, PermissionError, ValueError) as exc:
            return jsonify({'error': str(exc)}), 403 if isinstance(exc, PermissionError) else 400
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to respond to invite for {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to update invite response'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>/members', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def invite_collaboration_members_api(conversation_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            data = request.get_json(silent=True) or {}
            participants_to_add = _normalize_participant_payload(
                data.get('participants', data.get('participant'))
            )
            if not participants_to_add:
                return jsonify({'error': 'participants are required'}), 400

            conversation_doc, state_docs = invite_personal_collaboration_participants(
                conversation_id,
                current_user['user_id'],
                participants_to_add,
            )
            serialized = serialize_collaboration_conversation(
                conversation_doc,
                current_user_id=current_user['user_id'],
            )
            invited_participants = []
            for state_doc in state_docs:
                invited_participants.append({
                    'user_id': state_doc.get('user_id'),
                    'display_name': state_doc.get('user_display_name'),
                    'email': state_doc.get('user_email'),
                    'membership_status': state_doc.get('membership_status'),
                })
            if invited_participants:
                COLLABORATION_EVENT_REGISTRY.publish(
                    conversation_id,
                    _build_collaboration_event(
                        conversation_id,
                        'collaboration.member.invited',
                        {
                            'conversation': serialized,
                            'participants': invited_participants,
                        },
                    ),
                )
            return jsonify({'conversation': serialized, 'invited_participants': invited_participants}), 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative conversation not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to invite members for {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to invite collaborative conversation members'}), 500

    @app.route('/api/collaboration/conversations/from-personal/<conversation_id>/members', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def convert_personal_conversation_to_collaboration_api(conversation_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            data = request.get_json(silent=True) or {}
            participants_to_add = _normalize_participant_payload(
                data.get('participants', data.get('participant'))
            )
            if not participants_to_add:
                return jsonify({'error': 'participants are required'}), 400

            conversation_doc, invited_state_docs, created_new, _ = ensure_personal_collaboration_for_legacy_conversation(
                conversation_id,
                current_user,
                invited_participants=participants_to_add,
            )
            serialized = serialize_collaboration_conversation(
                conversation_doc,
                current_user_id=current_user['user_id'],
            )
            invited_participants = [
                {
                    'user_id': state_doc.get('user_id'),
                    'display_name': state_doc.get('user_display_name'),
                    'email': state_doc.get('user_email'),
                    'membership_status': state_doc.get('membership_status'),
                }
                for state_doc in invited_state_docs
            ]

            if created_new:
                COLLABORATION_EVENT_REGISTRY.publish(
                    conversation_doc.get('id'),
                    _build_collaboration_event(
                        conversation_doc.get('id'),
                        'collaboration.created',
                        {'conversation': serialized, 'source_conversation_id': conversation_id},
                    ),
                )

            if invited_participants:
                COLLABORATION_EVENT_REGISTRY.publish(
                    conversation_doc.get('id'),
                    _build_collaboration_event(
                        conversation_doc.get('id'),
                        'collaboration.member.invited',
                        {
                            'conversation': serialized,
                            'participants': invited_participants,
                            'source_conversation_id': conversation_id,
                        },
                    ),
                )

            return jsonify({
                'conversation': serialized,
                'invited_participants': invited_participants,
                'created': created_new,
                'source_conversation_id': conversation_id,
            }), 201 if created_new else 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to convert personal conversation {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to convert conversation to collaborative conversation'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>/members/<member_user_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def remove_collaboration_member_api(conversation_id, member_user_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            conversation_doc, removed_participant = remove_personal_collaboration_member(
                conversation_id,
                current_user['user_id'],
                member_user_id,
            )
            serialized = serialize_collaboration_conversation(
                conversation_doc,
                current_user_id=current_user['user_id'],
            )
            COLLABORATION_EVENT_REGISTRY.publish(
                conversation_id,
                _build_collaboration_event(
                    conversation_id,
                    'collaboration.member.removed',
                    {
                        'conversation': serialized,
                        'participant': removed_participant,
                    },
                ),
            )
            return jsonify({'conversation': serialized, 'removed_participant': removed_participant}), 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative conversation not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except (LookupError, ValueError) as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to remove member for {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to remove collaborative conversation member'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>/members/<member_user_id>/role', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def update_collaboration_member_role_api(conversation_id, member_user_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            data = request.get_json(silent=True) or {}
            new_role = str(data.get('role') or '').strip().lower()
            if not new_role:
                return jsonify({'error': 'role is required'}), 400

            conversation_doc, updated_participant = update_personal_collaboration_member_role(
                conversation_id,
                current_user['user_id'],
                member_user_id,
                new_role,
            )
            serialized = serialize_collaboration_conversation(
                conversation_doc,
                current_user_id=current_user['user_id'],
                user_state=get_user_state_or_none(current_user['user_id'], conversation_id),
            )
            COLLABORATION_EVENT_REGISTRY.publish(
                conversation_id,
                _build_collaboration_event(
                    conversation_id,
                    'collaboration.member.role_updated',
                    {
                        'conversation': serialized,
                        'participant': updated_participant,
                    },
                ),
            )
            return jsonify({'conversation': serialized, 'participant': updated_participant}), 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative conversation not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except (LookupError, ValueError) as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to update member role for {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to update collaborative conversation role'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def update_collaboration_conversation_title_api(conversation_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            data = request.get_json(silent=True) or {}
            new_title = str(data.get('title') or '').strip()
            if not new_title:
                return jsonify({'error': 'Title is required'}), 400

            conversation_doc = update_personal_collaboration_title(
                conversation_id,
                current_user['user_id'],
                new_title,
            )
            serialized = serialize_collaboration_conversation(
                conversation_doc,
                current_user_id=current_user['user_id'],
                user_state=get_user_state_or_none(current_user['user_id'], conversation_id),
            )
            COLLABORATION_EVENT_REGISTRY.publish(
                conversation_id,
                _build_collaboration_event(
                    conversation_id,
                    'collaboration.updated',
                    {'conversation': serialized},
                ),
            )
            return jsonify(serialized), 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative conversation not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to update title for {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to update collaborative conversation'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>/pin', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def toggle_collaboration_conversation_pin_api(conversation_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            _, user_state = toggle_personal_collaboration_pin(conversation_id, current_user['user_id'])
            return jsonify({'success': True, 'is_pinned': bool(user_state.get('is_pinned', False))}), 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative conversation not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to toggle pin for {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to toggle collaborative pin status'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>/hide', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def toggle_collaboration_conversation_hide_api(conversation_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            _, user_state = toggle_personal_collaboration_hide(conversation_id, current_user['user_id'])
            return jsonify({'success': True, 'is_hidden': bool(user_state.get('is_hidden', False))}), 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative conversation not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to toggle hide for {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to toggle collaborative hide status'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>/delete-action', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def collaboration_delete_action_api(conversation_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            data = request.get_json(silent=True) or {}
            action = str(data.get('action') or '').strip().lower()
            new_owner_user_id = str(data.get('new_owner_user_id') or '').strip() or None

            if action == 'delete':
                conversation_doc = get_collaboration_conversation(conversation_id)
                serialized = serialize_collaboration_conversation(
                    conversation_doc,
                    current_user_id=current_user['user_id'],
                    user_state=get_user_state_or_none(current_user['user_id'], conversation_id),
                )
                COLLABORATION_EVENT_REGISTRY.publish(
                    conversation_id,
                    _build_collaboration_event(
                        conversation_id,
                        'collaboration.deleted',
                        {
                            'conversation': serialized,
                            'deleted_by_user_id': current_user['user_id'],
                        },
                    ),
                )
                delete_personal_collaboration_conversation(conversation_id, current_user['user_id'])
                return jsonify({'success': True, 'action': 'delete', 'conversation_id': conversation_id}), 200

            if action == 'leave':
                conversation_doc, removed_participant, promoted_participant = leave_personal_collaboration_conversation(
                    conversation_id,
                    current_user['user_id'],
                    new_owner_user_id=new_owner_user_id,
                )
                serialized = serialize_collaboration_conversation(
                    conversation_doc,
                    current_user_id=current_user['user_id'],
                    user_state=get_user_state_or_none(current_user['user_id'], conversation_id),
                )
                COLLABORATION_EVENT_REGISTRY.publish(
                    conversation_id,
                    _build_collaboration_event(
                        conversation_id,
                        'collaboration.member.removed',
                        {
                            'conversation': serialized,
                            'participant': removed_participant,
                            'promoted_participant': promoted_participant,
                        },
                    ),
                )
                return jsonify({
                    'success': True,
                    'action': 'leave',
                    'conversation': serialized,
                    'removed_participant': removed_participant,
                    'promoted_participant': promoted_participant,
                }), 200

            return jsonify({'error': 'action must be delete or leave'}), 400
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative conversation not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except (LookupError, ValueError) as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to complete delete action for {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to update collaborative conversation membership'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>/messages', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_collaboration_messages_api(conversation_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            conversation_doc = get_collaboration_conversation(conversation_id)
            assert_user_can_view_collaboration_conversation(
                current_user['user_id'],
                conversation_doc,
                allow_pending=True,
            )
            messages = [serialize_collaboration_message(doc) for doc in list_collaboration_messages(conversation_id)]
            return jsonify({'messages': messages}), 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative conversation not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to load messages for {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to load collaborative conversation messages'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>/messages', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def post_collaboration_message_api(conversation_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            data = request.get_json(silent=True) or {}
            message_content = str(data.get('content') or '').strip()
            reply_to_message_id = str(data.get('reply_to_message_id') or '').strip() or None
            if not message_content:
                return jsonify({'error': 'content is required'}), 400

            conversation_doc = get_collaboration_conversation(conversation_id)
            assert_user_can_participate_in_collaboration_conversation(current_user['user_id'], conversation_doc)
            mentioned_participants = resolve_collaboration_mentions(
                conversation_doc,
                data.get('mentioned_participants'),
            )
            message_doc, updated_conversation_doc = persist_collaboration_message(
                conversation_doc,
                current_user,
                message_content,
                reply_to_message_id=reply_to_message_id,
                mentioned_participants=mentioned_participants,
            )
            create_collaboration_message_notifications(updated_conversation_doc, message_doc)
            serialized_message = serialize_collaboration_message(message_doc)
            serialized_conversation = serialize_collaboration_conversation(
                updated_conversation_doc,
                current_user_id=current_user['user_id'],
            )
            COLLABORATION_EVENT_REGISTRY.publish(
                conversation_id,
                _build_collaboration_event(
                    conversation_id,
                    'collaboration.message.created',
                    {
                        'conversation': serialized_conversation,
                        'message': serialized_message,
                    },
                ),
            )
            return jsonify({'conversation': serialized_conversation, 'message': serialized_message}), 201
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative conversation not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to post message for {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to post collaborative conversation message'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>/stream', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def stream_collaboration_message_api(conversation_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            data = request.get_json(silent=True) or {}
            message_content = str(data.get('content') or data.get('message') or '').strip()
            reply_to_message_id = str(data.get('reply_to_message_id') or '').strip() or None
            if not message_content:
                return jsonify({'error': 'content is required'}), 400

            conversation_doc = get_collaboration_conversation(conversation_id)
            assert_user_can_participate_in_collaboration_conversation(current_user['user_id'], conversation_doc)
            source_conversation_doc, conversation_doc = ensure_collaboration_source_conversation(
                conversation_doc,
                current_user,
            )
            source_conversation_id = str((source_conversation_doc or {}).get('id') or '').strip()
            if not source_conversation_id:
                return jsonify({'error': 'Failed to initialize collaboration AI context'}), 500

            mentioned_participants = resolve_collaboration_mentions(
                conversation_doc,
                data.get('mentioned_participants'),
            )
            invocation_target = data.get('invocation_target') if isinstance(data.get('invocation_target'), dict) else None
            extra_metadata = {}
            if invocation_target:
                extra_metadata['ai_invocation_target'] = invocation_target

            user_message_doc, updated_conversation_doc = persist_collaboration_message(
                conversation_doc,
                current_user,
                message_content,
                reply_to_message_id=reply_to_message_id,
                mentioned_participants=mentioned_participants,
                message_kind=MESSAGE_KIND_AI_REQUEST,
                extra_metadata=extra_metadata,
            )
            user_message_doc.setdefault('metadata', {})['source_conversation_id'] = source_conversation_id
            cosmos_collaboration_messages_container.upsert_item(user_message_doc)

            create_collaboration_message_notifications(updated_conversation_doc, user_message_doc)
            serialized_user_message = serialize_collaboration_message(user_message_doc)
            serialized_user_conversation = serialize_collaboration_conversation(
                updated_conversation_doc,
                current_user_id=current_user['user_id'],
                user_state=get_user_state_or_none(current_user['user_id'], conversation_id),
            )
            COLLABORATION_EVENT_REGISTRY.publish(
                conversation_id,
                _build_collaboration_event(
                    conversation_id,
                    'collaboration.message.created',
                    {
                        'conversation': serialized_user_conversation,
                        'message': serialized_user_message,
                    },
                ),
            )

            session_snapshot = dict(session)
            source_owner_user = normalize_collaboration_user({
                'user_id': updated_conversation_doc.get('created_by_user_id'),
                'display_name': updated_conversation_doc.get('created_by_display_name'),
            }) or current_user
            stream_request_payload = _build_collaboration_stream_request_payload(
                data,
                source_conversation_id,
                message_content,
            )

            def generate_stream():
                try:
                    internal_stream_view = current_app.view_functions.get('chat_stream_api')
                    if not callable(internal_stream_view):
                        yield _serialize_stream_error(
                            'Chat streaming endpoint is unavailable',
                            user_message_id=serialized_user_message.get('id'),
                            message_persisted=True,
                            conversation_id=conversation_id,
                        )
                        return

                    buffer = ''
                    with current_app.test_request_context('/api/chat/stream', method='POST', json=stream_request_payload):
                        session.clear()
                        session.update(session_snapshot)
                        internal_response = current_app.make_response(internal_stream_view())

                        if int(internal_response.status_code or 500) >= 400:
                            try:
                                error_payload = internal_response.get_json(silent=True) or {}
                            except Exception:
                                error_payload = {}
                            yield _serialize_stream_error(
                                error_payload.get('error') or error_payload.get('message') or 'Failed to start collaboration AI workflow',
                                user_message_id=serialized_user_message.get('id'),
                                message_persisted=True,
                                conversation_id=conversation_id,
                            )
                            return

                        def transform_event_block(event_block):
                            normalized_event_block = str(event_block or '')
                            if not normalized_event_block.strip():
                                return None

                            if normalized_event_block.lstrip().startswith(':'):
                                return normalized_event_block + '\n\n'

                            data_lines = [
                                line for line in normalized_event_block.split('\n')
                                if line.startswith('data:')
                            ]
                            if not data_lines:
                                return normalized_event_block + '\n\n'

                            json_text = '\n'.join(line[5:].lstrip() for line in data_lines)
                            try:
                                stream_payload = json.loads(json_text)
                            except json.JSONDecodeError:
                                return normalized_event_block + '\n\n'

                            if stream_payload.get('error'):
                                return _serialize_stream_error(
                                    stream_payload.get('error'),
                                    partial_content=stream_payload.get('partial_content'),
                                    user_message_id=serialized_user_message.get('id'),
                                    message_persisted=True,
                                    conversation_id=conversation_id,
                                )

                            if not stream_payload.get('done'):
                                return normalized_event_block + '\n\n'

                            source_message_id = str(stream_payload.get('message_id') or '').strip()
                            if not source_message_id:
                                return _serialize_stream_error(
                                    'AI workflow completed without a source assistant message',
                                    user_message_id=serialized_user_message.get('id'),
                                    message_persisted=True,
                                    conversation_id=conversation_id,
                                )

                            source_user_message_id = str(stream_payload.get('user_message_id') or '').strip()
                            if source_user_message_id:
                                try:
                                    saved_user_message_doc = cosmos_collaboration_messages_container.read_item(
                                        item=serialized_user_message.get('id'),
                                        partition_key=conversation_id,
                                    )
                                    saved_user_message_doc['metadata'] = {
                                        **dict(saved_user_message_doc.get('metadata', {}) or {}),
                                        'source_message_id': source_user_message_id,
                                        'source_conversation_id': source_conversation_id,
                                        'source_thought_user_id': current_user['user_id'],
                                    }
                                    cosmos_collaboration_messages_container.upsert_item(saved_user_message_doc)
                                except Exception:
                                    pass

                            try:
                                source_message_doc = _read_source_message_doc(source_conversation_id, source_message_id)
                            except CosmosResourceNotFoundError:
                                return _serialize_stream_error(
                                    'Failed to load the generated assistant response',
                                    user_message_id=serialized_user_message.get('id'),
                                    message_persisted=True,
                                    conversation_id=conversation_id,
                                )

                            try:
                                source_conversation_doc = cosmos_conversations_container.read_item(
                                    item=source_conversation_id,
                                    partition_key=source_conversation_id,
                                )
                                updated_conversation_doc, _ = sync_collaboration_conversation_metadata_from_source(
                                    updated_conversation_doc,
                                    source_conversation_doc,
                                )
                            except CosmosResourceNotFoundError:
                                source_conversation_doc = None
                            except Exception:
                                source_conversation_doc = None

                            mirrored_message_doc, final_conversation_doc, _ = mirror_source_message_to_collaboration(
                                updated_conversation_doc,
                                source_message_doc,
                                source_owner_user,
                                reply_to_message_id=serialized_user_message.get('id'),
                                extra_metadata={
                                    'source_conversation_id': source_conversation_id,
                                    'source_thought_user_id': current_user['user_id'],
                                },
                            )
                            if not mirrored_message_doc:
                                return _serialize_stream_error(
                                    'Failed to mirror the assistant response into the collaboration conversation',
                                    user_message_id=serialized_user_message.get('id'),
                                    message_persisted=True,
                                    conversation_id=conversation_id,
                                )

                            create_collaboration_message_notifications(final_conversation_doc, mirrored_message_doc)
                            serialized_assistant_message = serialize_collaboration_message(mirrored_message_doc)
                            serialized_final_conversation = serialize_collaboration_conversation(
                                final_conversation_doc,
                                current_user_id=current_user['user_id'],
                                user_state=get_user_state_or_none(current_user['user_id'], conversation_id),
                            )
                            COLLABORATION_EVENT_REGISTRY.publish(
                                conversation_id,
                                _build_collaboration_event(
                                    conversation_id,
                                    'collaboration.message.created',
                                    {
                                        'conversation': serialized_final_conversation,
                                        'message': serialized_assistant_message,
                                    },
                                ),
                            )

                            transformed_payload = {
                                **stream_payload,
                                'conversation_id': conversation_id,
                                'conversation_title': serialized_final_conversation.get('title'),
                                'chat_type': serialized_final_conversation.get('chat_type'),
                                'classification': serialized_final_conversation.get('classification', []),
                                'context': serialized_final_conversation.get('context', []),
                                'scope_locked': serialized_final_conversation.get('scope_locked'),
                                'locked_contexts': serialized_final_conversation.get('locked_contexts', []),
                                'message_id': serialized_assistant_message.get('id'),
                                'user_message_id': serialized_user_message.get('id'),
                                'model_deployment_name': serialized_assistant_message.get('model_deployment_name') or stream_payload.get('model_deployment_name'),
                                'augmented': serialized_assistant_message.get('augmented', False),
                                'hybrid_citations': serialized_assistant_message.get('hybrid_citations', []),
                                'web_search_citations': serialized_assistant_message.get('web_search_citations', []),
                                'agent_citations': serialized_assistant_message.get('agent_citations', []),
                                'agent_display_name': serialized_assistant_message.get('agent_display_name'),
                                'agent_name': serialized_assistant_message.get('agent_name'),
                                'full_content': mirrored_message_doc.get('content') if serialized_assistant_message.get('role') != 'image' else stream_payload.get('full_content', ''),
                                'image_url': mirrored_message_doc.get('content') if serialized_assistant_message.get('role') == 'image' else stream_payload.get('image_url'),
                                'reload_messages': False,
                            }
                            return f'data: {json.dumps(transformed_payload)}\n\n'

                        for chunk in internal_response.response:
                            if chunk is None:
                                continue

                            chunk_text = chunk.decode('utf-8') if isinstance(chunk, (bytes, bytearray)) else str(chunk)
                            buffer += chunk_text.replace('\r', '')

                            while '\n\n' in buffer:
                                event_block, buffer = buffer.split('\n\n', 1)
                                transformed_block = transform_event_block(event_block)
                                if transformed_block:
                                    yield transformed_block

                        if buffer.strip():
                            transformed_block = transform_event_block(buffer.strip())
                            if transformed_block:
                                yield transformed_block
                except Exception as exc:
                    log_event(
                        f'[Collaboration] Failed to stream AI message for {conversation_id}: {exc}',
                        level=logging.ERROR,
                        exceptionTraceback=True,
                    )
                    yield _serialize_stream_error(
                        'Failed to stream collaborative AI response',
                        user_message_id=serialized_user_message.get('id'),
                        message_persisted=True,
                        conversation_id=conversation_id,
                    )

            return Response(stream_with_context(generate_stream()), mimetype='text/event-stream')
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative conversation not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to start AI stream for {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to start collaborative AI workflow'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>/messages/<message_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def delete_collaboration_message_api(conversation_id, message_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            deleted_message_doc, updated_conversation_doc = delete_collaboration_message(
                conversation_id,
                message_id,
                current_user['user_id'],
            )
            serialized_conversation = serialize_collaboration_conversation(
                updated_conversation_doc,
                current_user_id=current_user['user_id'],
                user_state=get_user_state_or_none(current_user['user_id'], conversation_id),
            )
            COLLABORATION_EVENT_REGISTRY.publish(
                conversation_id,
                _build_collaboration_event(
                    conversation_id,
                    'collaboration.message.deleted',
                    {
                        'conversation': serialized_conversation,
                        'message_id': message_id,
                        'deleted_by_user_id': current_user['user_id'],
                        'deleted_message': {
                            'id': deleted_message_doc.get('id'),
                            'sender_user_id': (
                                ((deleted_message_doc.get('metadata') or {}).get('sender') or {}).get('user_id')
                            ),
                        },
                    },
                ),
            )
            return jsonify({
                'success': True,
                'deleted_message_ids': [message_id],
                'archived': False,
                'conversation': serialized_conversation,
            }), 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative message not found'}), 404
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to delete message {message_id} for {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to delete collaborative conversation message'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>/mark-read', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def mark_collaboration_conversation_read_api(conversation_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            conversation_doc = get_collaboration_conversation(conversation_id)
            assert_user_can_view_collaboration_conversation(
                current_user['user_id'],
                conversation_doc,
                allow_pending=True,
            )
            notifications_marked_read = mark_collaboration_message_notifications_read_for_conversation(
                current_user['user_id'],
                conversation_id,
            )

            return jsonify({
                'success': True,
                'conversation_id': conversation_id,
                'notifications_marked_read': notifications_marked_read,
            }), 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative conversation not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to mark conversation {conversation_id} read: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to mark collaborative conversation read'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>/typing', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def collaboration_typing_api(conversation_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            data = request.get_json(silent=True) or {}
            is_typing = bool(data.get('is_typing', True))
            conversation_doc = get_collaboration_conversation(conversation_id)
            assert_user_can_participate_in_collaboration_conversation(current_user['user_id'], conversation_doc)

            typing_payload = {
                'user': current_user,
                'is_typing': is_typing,
                'expires_at': add_seconds_to_iso(utc_now_iso(), 8),
            }
            COLLABORATION_EVENT_REGISTRY.publish(
                conversation_id,
                _build_collaboration_event(
                    conversation_id,
                    'collaboration.typing.updated',
                    typing_payload,
                ),
            )
            return jsonify({'success': True}), 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative conversation not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to publish typing event for {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to publish typing event'}), 500

    @app.route('/api/collaboration/conversations/<conversation_id>/events', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def collaboration_events_api(conversation_id):
        try:
            _require_collaboration_feature_enabled()
            current_user = _get_current_collaboration_user()
            if not current_user:
                return jsonify({'error': 'User not authenticated'}), 401

            conversation_doc = get_collaboration_conversation(conversation_id)
            assert_user_can_view_collaboration_conversation(
                current_user['user_id'],
                conversation_doc,
                allow_pending=True,
            )

            start_index = request.args.get('start_index', 0)
            session = COLLABORATION_EVENT_REGISTRY.get_session(conversation_id)
            return Response(
                stream_with_context(session.iter_events(start_index=start_index)),
                mimetype='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no',
                    'Connection': 'keep-alive',
                },
            )
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Collaborative conversation not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except Exception as exc:
            log_event(
                f'[Collaboration] Failed to attach event stream for {conversation_id}: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to attach collaborative event stream'}), 500