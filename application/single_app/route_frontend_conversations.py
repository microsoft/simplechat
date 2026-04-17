# route_frontend_conversations.py

from config import *
from functions_appinsights import log_event
from functions_authentication import *
from functions_debug import debug_print
from functions_chat import sort_messages_by_thread
from functions_collaboration import (
    assert_user_can_view_collaboration_conversation,
    build_collaboration_message_metadata_payload,
    get_collaboration_conversation,
    get_collaboration_message,
)
from functions_image_messages import hydrate_image_messages
from functions_message_artifacts import (
    build_message_artifact_payload_map,
    filter_assistant_artifact_items,
)
from swagger_wrapper import swagger_route, get_auth_security

def register_route_frontend_conversations(app):
    @app.route('/conversations')
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def conversations():
        user_id = get_current_user_id()
        if not user_id:
            return redirect(url_for('login'))
        
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

    @app.route('/conversation/<conversation_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def view_conversation(conversation_id):
        user_id = get_current_user_id()
        if not user_id:
            return redirect(url_for('login'))
        try:
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
        except Exception:
            return "Conversation not found", 404

        message_query = f"""
            SELECT * FROM c
            WHERE c.conversation_id = '{conversation_id}'
            ORDER BY c.timestamp ASC
        """
        messages = list(cosmos_messages_container.query_items(
            query=message_query,
            partition_key=conversation_id
        ))
        messages = filter_assistant_artifact_items(messages)
        return render_template('chat.html', conversation_id=conversation_id, messages=messages)
    
    @app.route('/conversation/<conversation_id>/messages', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_conversation_messages(conversation_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            _ = cosmos_conversations_container.read_item(conversation_id, conversation_id)
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404
        
        msg_query = f"""
            SELECT * FROM c
            WHERE c.conversation_id = '{conversation_id}'
            ORDER BY c.timestamp ASC
        """
        all_items = list(cosmos_messages_container.query_items(
            query=msg_query,
            partition_key=conversation_id
        ))
        all_items = filter_assistant_artifact_items(all_items)

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

        return jsonify({'messages': messages})

    @app.route('/api/conversation/<conversation_id>/agent-citation/<artifact_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_agent_citation_artifact(conversation_id, artifact_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            conversation = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id,
            )
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404

        if conversation.get('user_id') != user_id:
            return jsonify({'error': 'Unauthorized access to conversation'}), 403

        conversation_messages = list(cosmos_messages_container.query_items(
            query="SELECT * FROM c WHERE c.conversation_id = @conversation_id",
            parameters=[{'name': '@conversation_id', 'value': conversation_id}],
            partition_key=conversation_id,
        ))
        artifact_payload_map = build_message_artifact_payload_map(conversation_messages)
        artifact_payload = artifact_payload_map.get(str(artifact_id or ''))
        if not isinstance(artifact_payload, dict):
            return jsonify({'error': 'Agent citation artifact not found'}), 404

        citation = artifact_payload.get('citation')
        if citation is None:
            return jsonify({'error': 'Agent citation payload not found'}), 404

        return jsonify({'citation': citation})

    @app.route('/api/message/<message_id>/metadata', methods=['GET'])
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