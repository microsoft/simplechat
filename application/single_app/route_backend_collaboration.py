# route_backend_collaboration.py

import json
import threading
import time

import app_settings_cache
from flask import Response, jsonify, request, stream_with_context

from config import *
from collaboration_models import MEMBERSHIP_STATUS_PENDING, add_seconds_to_iso, normalize_collaboration_user, utc_now_iso
from functions_appinsights import log_event
from functions_authentication import *
from functions_collaboration import (
    assert_user_can_participate_in_collaboration_conversation,
    assert_user_can_view_collaboration_conversation,
    build_collaboration_message_metadata_payload,
    create_group_collaboration_conversation_record,
    create_personal_collaboration_conversation_record,
    delete_personal_collaboration_conversation,
    ensure_personal_collaboration_for_legacy_conversation,
    get_collaboration_conversation,
    get_collaboration_user_state,
    invite_personal_collaboration_participants,
    leave_personal_collaboration_conversation,
    list_collaboration_messages,
    list_group_collaboration_conversations_for_user,
    list_personal_collaboration_conversations_for_user,
    persist_collaboration_message,
    record_personal_invite_response,
    remove_personal_collaboration_member,
    resolve_collaboration_mentions,
    serialize_collaboration_conversation,
    serialize_collaboration_message,
    toggle_personal_collaboration_hide,
    toggle_personal_collaboration_pin,
    update_personal_collaboration_member_role,
    update_personal_collaboration_title,
)
from functions_group import assert_group_role, check_group_status_allows_operation, find_group_by_id
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