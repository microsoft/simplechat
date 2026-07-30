# route_frontend_conversations.py

import logging
import re

import requests
from flask import Response, jsonify, redirect, render_template, request

from config import *
from functions_appinsights import log_event
from functions_azure_maps import (
    AZURE_MAPS_DEFAULT_ENDPOINT,
    AZURE_MAPS_DEFAULT_LANGUAGE,
    AZURE_MAPS_DEFAULT_TILESET_ID,
    AZURE_MAPS_DEFAULT_VIEW,
    AZURE_MAPS_TILE_API_VERSION,
    decode_tile_proxy_token,
    refresh_azure_maps_citation_payload,
    refresh_azure_maps_citation_payloads,
    refresh_azure_maps_message_content,
)
from functions_authentication import *
from functions_debug import debug_print
from functions_chat import sort_messages_by_thread
from functions_collaboration import (
    assert_user_can_view_collaboration_conversation,
    build_collaboration_message_metadata_payload,
    get_collaboration_conversation,
    get_collaboration_message,
    list_collaboration_messages,
)
from functions_image_messages import hydrate_image_messages
from functions_message_artifacts import (
    build_message_artifact_payload_map,
    filter_assistant_artifact_items,
    hydrate_agent_citations_from_artifacts,
)
from swagger_wrapper import swagger_route, get_auth_security


def _authorize_frontend_personal_conversation_access(user_id, conversation_id):
    """Load a personal conversation and ensure the caller owns it."""
    try:
        conversation_item = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
    except CosmosResourceNotFoundError as exc:
        raise LookupError(f"Conversation {conversation_id} not found") from exc

    if conversation_item.get('user_id') != user_id:
        raise PermissionError('Forbidden')

    return conversation_item

def register_route_frontend_conversations(bp):
    def _disable_response_caching(response):
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    def _refresh_azure_maps_message_payloads(messages):
        refreshed_messages = []
        for message in messages or []:
            if not isinstance(message, dict):
                refreshed_messages.append(message)
                continue

            refreshed_message = dict(message)
            refreshed_message['agent_citations'] = refresh_azure_maps_citation_payloads(
                refreshed_message.get('agent_citations')
            )
            if refreshed_message.get('role') == 'assistant':
                refreshed_message['content'] = refresh_azure_maps_message_content(
                    refreshed_message.get('content')
                )
            refreshed_messages.append(refreshed_message)

        return refreshed_messages

    @bp.route('/conversations')
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def conversations():
        user_id = get_current_user_id()
        if not user_id:
            return redirect(url_for('frontend_authentication.login'))
        
        query = f"""
            SELECT *
            FROM c
            WHERE c.user_id = '{user_id}'
            ORDER BY c.last_updated DESC
        """
        items = list(cosmos_conversations_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        return render_template('conversations.html', conversations=items)

    @bp.route('/conversation/<conversation_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def view_conversation(conversation_id):
        user_id = get_current_user_id()
        if not user_id:
            return redirect(url_for('frontend_authentication.login'))
        try:
            _authorize_frontend_personal_conversation_access(user_id, conversation_id)
        except LookupError:
            return "Conversation not found", 404
        except PermissionError:
            return "Forbidden", 403

        message_query = f"""
            SELECT * FROM c
            WHERE c.conversation_id = '{conversation_id}'
            ORDER BY c.timestamp ASC
        """
        messages = list(cosmos_messages_container.query_items(
            query=message_query,
            partition_key=conversation_id
        ))
        artifact_payload_map = build_message_artifact_payload_map(messages)
        messages = filter_assistant_artifact_items(messages)
        messages = hydrate_agent_citations_from_artifacts(messages, artifact_payload_map)
        messages = _refresh_azure_maps_message_payloads(messages)
        return render_template('chat.html', conversation_id=conversation_id, messages=messages)
    
    @bp.route('/conversation/<conversation_id>/messages', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_conversation_messages(conversation_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            _authorize_frontend_personal_conversation_access(user_id, conversation_id)
        except LookupError:
            return jsonify({'error': 'Conversation not found'}), 404
        except PermissionError:
            return jsonify({'error': 'Forbidden'}), 403
        
        msg_query = f"""
            SELECT * FROM c
            WHERE c.conversation_id = '{conversation_id}'
            ORDER BY c.timestamp ASC
        """
        all_items = list(cosmos_messages_container.query_items(
            query=msg_query,
            partition_key=conversation_id
        ))
        artifact_payload_map = build_message_artifact_payload_map(all_items)
        all_items = filter_assistant_artifact_items(all_items)
        all_items = hydrate_agent_citations_from_artifacts(all_items, artifact_payload_map)
        all_items = _refresh_azure_maps_message_payloads(all_items)

        debug_print(f"Frontend endpoint - Query returned {len(all_items)} total items (before filtering)")
        
        # Filter for active_thread = True OR active_thread is not defined (backwards compatibility)
        filtered_items = []
        for item in all_items:
            thread_info = item.get('metadata', {}).get('thread_info', {})
            active = thread_info.get('active_thread')
            
            # Include if: active_thread is True, OR active_thread is not defined, OR active_thread is None
            if active is True or active is None or 'active_thread' not in thread_info:
                filtered_items.append(item)
                debug_print(f"Frontend endpoint - ✅ Including: id={item.get('id')}, role={item.get('role')}, active={active}, attempt={thread_info.get('thread_attempt', 'N/A')}")
            else:
                debug_print(f"Frontend endpoint - ❌ Excluding: id={item.get('id')}, role={item.get('role')}, active={active}, attempt={thread_info.get('thread_attempt', 'N/A')}")
        
        all_items = filtered_items
        debug_print(f"Frontend endpoint - After filtering: {len(all_items)} items remaining")

        # Log thread info BEFORE sorting
        debug_print(f"Frontend endpoint - BEFORE SORT:")
        for item in all_items:
            thread_info = item.get('metadata', {}).get('thread_info', {})
            thread_id = thread_info.get('thread_id', 'NO_THREAD_ID')
            prev_thread_id = thread_info.get('previous_thread_id', 'NO_PREV')
            timestamp = item.get('timestamp', 'NO_TIMESTAMP')
            attempt = thread_info.get('thread_attempt', 'N/A')
            debug_print(f"  {item.get('id')}: thread_id={thread_id}, prev={prev_thread_id}, attempt={attempt}, timestamp={timestamp}")

        # Sort messages using threading logic
        all_items = sort_messages_by_thread(all_items)
        
        # Log thread info AFTER sorting
        debug_print(f"Frontend endpoint - AFTER SORT:")
        for i, item in enumerate(all_items):
            thread_info = item.get('metadata', {}).get('thread_info', {})
            thread_id = thread_info.get('thread_id', 'NO_THREAD_ID')
            prev_thread_id = thread_info.get('previous_thread_id', 'NO_PREV')
            timestamp = item.get('timestamp', 'NO_TIMESTAMP')
            attempt = thread_info.get('thread_attempt', 'N/A')
            debug_print(f"  {i+1}. {item.get('id')}: thread_id={thread_id}, prev={prev_thread_id}, attempt={attempt}, timestamp={timestamp}")

        messages = hydrate_image_messages(
            all_items,
            image_url_builder=lambda image_id: f"/api/image/{image_id}",
        )

        # Remove file content for security
        for m in messages:
            if m.get('role') == 'file' and 'file_content' in m:
                del m['file_content']

        response = jsonify({'messages': messages})
        return _disable_response_caching(response)

    @bp.route('/api/conversation/<conversation_id>/agent-citation/<artifact_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_agent_citation_artifact(conversation_id, artifact_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        artifact_lookup_conversation_id = conversation_id

        try:
            conversation = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id,
            )
        except CosmosResourceNotFoundError:
            try:
                conversation = get_collaboration_conversation(conversation_id)
            except CosmosResourceNotFoundError:
                return jsonify({'error': 'Conversation not found'}), 404

            try:
                assert_user_can_view_collaboration_conversation(user_id, conversation)
            except PermissionError:
                return jsonify({'error': 'Unauthorized access to conversation'}), 403

            artifact_lookup_conversation_id = str(conversation.get('source_conversation_id') or '').strip()
            if artifact_lookup_conversation_id:
                conversation_messages = list(cosmos_messages_container.query_items(
                    query="SELECT * FROM c WHERE c.conversation_id = @conversation_id",
                    parameters=[{'name': '@conversation_id', 'value': artifact_lookup_conversation_id}],
                    partition_key=artifact_lookup_conversation_id,
                ))
            else:
                conversation_messages = list_collaboration_messages(conversation_id)
        else:
            if conversation.get('user_id') != user_id:
                return jsonify({'error': 'Unauthorized access to conversation'}), 403

            conversation_messages = list(cosmos_messages_container.query_items(
                query="SELECT * FROM c WHERE c.conversation_id = @conversation_id",
                parameters=[{'name': '@conversation_id', 'value': conversation_id}],
                partition_key=conversation_id,
            ))

        artifact_payload_map = build_message_artifact_payload_map(conversation_messages)
        artifact_payload = artifact_payload_map.get(str(artifact_id or ''))
        if artifact_payload is None and artifact_lookup_conversation_id != conversation_id:
            collaboration_messages = list_collaboration_messages(conversation_id)
            artifact_payload_map = build_message_artifact_payload_map(collaboration_messages)
            artifact_payload = artifact_payload_map.get(str(artifact_id or ''))
        if not isinstance(artifact_payload, dict):
            return jsonify({'error': 'Agent citation artifact not found'}), 404

        citation = artifact_payload.get('citation')
        if citation is None:
            return jsonify({'error': 'Agent citation payload not found'}), 404

        response = jsonify({'citation': refresh_azure_maps_citation_payload(citation)})
        return _disable_response_caching(response)

    @bp.route('/api/azure-maps/tile', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_azure_maps_tile():
        tile_proxy_token = str(request.args.get('token') or '').strip()
        token_payload = decode_tile_proxy_token(tile_proxy_token)
        if not token_payload:
            return jsonify({'error': 'Invalid or expired Azure Maps tile token.'}), 400

        subscription_key = str(token_payload.get('subscription_key') or '').strip()
        if not subscription_key:
            return jsonify({'error': 'Azure Maps tile token is missing a subscription key.'}), 400

        try:
            zoom = int(str(request.args.get('zoom') or '').strip())
            tile_x = int(str(request.args.get('x') or '').strip())
            tile_y = int(str(request.args.get('y') or '').strip())
        except ValueError:
            return jsonify({'error': 'Tile requests must include numeric zoom, x, and y values.'}), 400

        raw_tileset_id = str(request.args.get('tilesetId') or AZURE_MAPS_DEFAULT_TILESET_ID).strip()
        raw_language = str(request.args.get('language') or AZURE_MAPS_DEFAULT_LANGUAGE).strip()
        raw_view = str(request.args.get('view') or AZURE_MAPS_DEFAULT_VIEW).strip()
        raw_tile_size = str(request.args.get('tileSize') or '256').strip()

        if not re.fullmatch(r'[A-Za-z0-9._-]+', raw_tileset_id):
            return jsonify({'error': 'tilesetId contains unsupported characters.'}), 400
        if raw_language and not re.fullmatch(r'[A-Za-z0-9-]{2,16}', raw_language):
            return jsonify({'error': 'language contains unsupported characters.'}), 400
        if raw_view and not re.fullmatch(r'[A-Za-z]+', raw_view):
            return jsonify({'error': 'view contains unsupported characters.'}), 400
        if raw_tile_size not in {'256', '512'}:
            return jsonify({'error': 'tileSize must be 256 or 512.'}), 400

        upstream_params = {
            'api-version': AZURE_MAPS_TILE_API_VERSION,
            'tilesetId': raw_tileset_id,
            'zoom': zoom,
            'x': tile_x,
            'y': tile_y,
            'tileSize': raw_tile_size,
            'language': raw_language or AZURE_MAPS_DEFAULT_LANGUAGE,
            'view': raw_view or AZURE_MAPS_DEFAULT_VIEW,
            'subscription-key': subscription_key,
        }

        try:
            upstream_response = requests.get(
                f'{AZURE_MAPS_DEFAULT_ENDPOINT}/map/tile',
                params=upstream_params,
                timeout=20,
            )
        except requests.RequestException as exc:
            log_event(
                f"[AzureMaps] Tile proxy request failed: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Azure Maps tile request failed.'}), 502

        proxy_response = Response(
            upstream_response.content,
            status=upstream_response.status_code,
            content_type=upstream_response.headers.get('Content-Type', 'image/png'),
        )

        cache_control = upstream_response.headers.get('Cache-Control')
        if cache_control:
            proxy_response.headers['Cache-Control'] = cache_control
        proxy_response.headers['X-Content-Type-Options'] = 'nosniff'
        return proxy_response

    @bp.route('/api/message/<message_id>/metadata', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_message_metadata(message_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            # Query for the message by ID and user
            msg_query = f"""
                SELECT * FROM c
                WHERE c.id = '{message_id}'
            """
            messages = list(cosmos_messages_container.query_items(
                query=msg_query,
                enable_cross_partition_query=True
            ))
            
            if not messages:
                message = get_collaboration_message(message_id)
                conversation = get_collaboration_conversation(message.get('conversation_id'))
                assert_user_can_view_collaboration_conversation(
                    user_id,
                    conversation,
                    allow_pending=True,
                )
                return jsonify(build_collaboration_message_metadata_payload(message, conversation))
                
            message = messages[0]
            
            # Verify the message belongs to a conversation owned by the current user
            conversation_id = message.get('conversation_id')
            if conversation_id:
                try:
                    conversation = cosmos_conversations_container.read_item(
                        item=conversation_id,
                        partition_key=conversation_id
                    )
                    if conversation.get('user_id') != user_id:
                        return jsonify({'error': 'Unauthorized access to message'}), 403
                except CosmosResourceNotFoundError:
                    return jsonify({'error': 'Conversation not found'}), 404
            
            # Return appropriate data based on message role
            # User messages: return metadata object only (has user_info, button_states, etc.)
            # Other messages: return full document (has id, role, augmented, etc. at top level)
            message_role = message.get('role', '')
            
            if message_role == 'user':
                # User messages - return nested metadata object
                metadata = message.get('metadata', {})
                return jsonify(metadata)
            else:
                # Assistant, image, file messages - return full document
                return jsonify(message)

        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Message not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
            
        except Exception as e:
            log_event(f"get_message_metadata failed: {e}", level="WARNING")
            return jsonify({'error': 'Failed to fetch message metadata'}), 500
