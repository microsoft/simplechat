# route_frontend_conversations.py

from config import *
from functions_authentication import *
from functions_debug import debug_print

def register_route_frontend_conversations(app):
    @app.route('/conversations')
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
        return render_template('chat.html', conversation_id=conversation_id, messages=messages)
    
    @app.route('/conversation/<conversation_id>/messages', methods=['GET'])
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

        debug_print(f"Frontend endpoint - Query returned {len(all_items)} total items")
        for i, item in enumerate(all_items):
            debug_print(f"Frontend endpoint - Item {i}: id={item.get('id')}, role={item.get('role')}")

        # Process messages and reassemble chunked images
        messages = []
        chunked_images = {}  # Store image chunks by parent_message_id
        
        for item in all_items:
            if item.get('role') == 'image_chunk':
                # This is a chunk, store it for reassembly
                parent_id = item.get('parent_message_id')
                if parent_id not in chunked_images:
                    chunked_images[parent_id] = {}
                chunk_index = item.get('metadata', {}).get('chunk_index', 0)
                chunked_images[parent_id][chunk_index] = item.get('content', '')
                debug_print(f"Frontend endpoint - Stored chunk {chunk_index} for parent {parent_id}")
            else:
                # Regular message or main image document
                if item.get('role') == 'image' and item.get('metadata', {}).get('is_chunked'):
                    # This is a chunked image main document
                    messages.append(item)
                else:
                    # Regular message
                    messages.append(item)

        # Reassemble chunked images
        for message in messages:
            if (message.get('role') == 'image' and 
                message.get('metadata', {}).get('is_chunked')):
                
                image_id = message.get('id')
                total_chunks = message.get('metadata', {}).get('total_chunks', 1)
                
                debug_print(f"Frontend endpoint - Reassembling chunked image {image_id} with {total_chunks} chunks")
                debug_print(f"Frontend endpoint - Available chunks: {list(chunked_images.get(image_id, {}).keys())}")
                
                # Start with the content from the main message (chunk 0)
                complete_content = message.get('content', '')
                debug_print(f"Frontend endpoint - Main message content length: {len(complete_content)} bytes")
                
                # Add remaining chunks in order (chunks 1, 2, 3, etc.)
                if image_id in chunked_images:
                    chunks = chunked_images[image_id]
                    for chunk_index in range(1, total_chunks):
                        if chunk_index in chunks:
                            chunk_content = chunks[chunk_index]
                            complete_content += chunk_content
                            debug_print(f"Frontend endpoint - Added chunk {chunk_index}, length: {len(chunk_content)} bytes")
                        else:
                            print(f"WARNING: Frontend endpoint - Missing chunk {chunk_index} for image {image_id}")
                else:
                    print(f"WARNING: Frontend endpoint - No chunks found for image {image_id}")
                
                debug_print(f"Frontend endpoint - Final reassembled image total size: {len(complete_content)} bytes")
                
                # For large images (>1MB), use a URL reference instead of embedding in JSON
                if len(complete_content) > 1024 * 1024:  # 1MB threshold
                    debug_print(f"Frontend endpoint - Large image detected ({len(complete_content)} bytes), using URL reference")
                    # Store the complete content temporarily and provide a URL reference
                    message['content'] = f"/api/image/{image_id}"
                    message['metadata']['is_large_image'] = True
                    message['metadata']['image_size'] = len(complete_content)
                else:
                    # Small enough to embed directly
                    message['content'] = complete_content

        # Remove file content for security
        for m in messages:
            if m.get('role') == 'file' and 'file_content' in m:
                del m['file_content']

        return jsonify({'messages': messages})

    @app.route('/api/message/<message_id>/metadata', methods=['GET'])
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
                return jsonify({'error': 'Message not found'}), 404
                
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
            
            # Return the metadata from the message
            metadata = message.get('metadata', {})
            return jsonify(metadata)
            
        except Exception as e:
            print(f"Error fetching message metadata: {str(e)}")
            return jsonify({'error': 'Failed to fetch message metadata'}), 500