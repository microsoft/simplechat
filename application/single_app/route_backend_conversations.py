# route_backend_conversations.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_conversation_metadata import get_conversation_metadata
from flask import Response, request
from functions_debug import debug_print
from swagger_wrapper import swagger_route, get_auth_security
from functions_activity_logging import log_conversation_creation, log_conversation_deletion, log_conversation_archival

def register_route_backend_conversations(app):

    @app.route('/api/get_messages', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_get_messages():
        conversation_id = request.args.get('conversation_id')
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        if not conversation_id:
            return jsonify({'error': 'No conversation_id provided'}), 400
        try:
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            # Query all messages in cosmos_messages_container
            # We'll filter for active_thread in Python since Cosmos DB boolean queries can be tricky
            message_query = f"""
                SELECT * FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                ORDER BY c.timestamp ASC
            """
            
            debug_print(f"Executing query: {message_query}")
            
            all_items = list(cosmos_messages_container.query_items(
                query=message_query,
                partition_key=conversation_id
            ))
            
            debug_print(f"Query returned {len(all_items)} total items (before filtering)")
            
            # Filter for active_thread = True OR active_thread is not defined (backwards compatibility)
            filtered_items = []
            for item in all_items:
                thread_info = item.get('metadata', {}).get('thread_info', {})
                active = thread_info.get('active_thread')
                debug_print(f"Evaluating item id={item.get('id')}, role={item.get('role')}, active_thread={active}, attempt={thread_info.get('thread_attempt', 'N/A')}")
                
                # Include if: active_thread is True, OR active_thread is not defined, OR active_thread is None
                if active is True or active is None or 'active_thread' not in thread_info:
                    filtered_items.append(item)
                    debug_print(f"  ✅ Including: id={item.get('id')}, role={item.get('role')}, active={active}, attempt={thread_info.get('thread_attempt', 'N/A')}")
                else:
                    debug_print(f"  ❌ Excluding: id={item.get('id')}, role={item.get('role')}, active={active}, attempt={thread_info.get('thread_attempt', 'N/A')}")
            
            all_items = filtered_items
            debug_print(f"After filtering: {len(all_items)} items remaining")
            
            
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
                else:
                    # Regular message or main image document
                    if item.get('role') == 'image' and item.get('metadata', {}).get('is_chunked'):
                        # This is a chunked image main document
                        image_id = item.get('id')
                        total_chunks = item.get('metadata', {}).get('total_chunks', 1)
                        
                        # We'll reassemble after collecting all chunks
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
                    
                    debug_print(f"Reassembling chunked image {image_id} with {total_chunks} chunks")
                    debug_print(f"Available chunks in chunked_images: {list(chunked_images.get(image_id, {}).keys())}")
                    
                    # Preserve extracted_text and vision_analysis from main message
                    extracted_text = message.get('extracted_text')
                    vision_analysis = message.get('vision_analysis')
                    
                    debug_print(f"Image has extracted_text: {bool(extracted_text)}, vision_analysis: {bool(vision_analysis)}")
                    
                    # Start with the content from the main message (chunk 0)
                    complete_content = message.get('content', '')
                    debug_print(f"Main message content length: {len(complete_content)} bytes")
                    
                    # Add remaining chunks in order (chunks 1, 2, 3, etc.)
                    if image_id in chunked_images:
                        chunks = chunked_images[image_id]
                        for chunk_index in range(1, total_chunks):
                            if chunk_index in chunks:
                                chunk_content = chunks[chunk_index]
                                complete_content += chunk_content
                                debug_print(f"Added chunk {chunk_index}, length: {len(chunk_content)} bytes")
                            else:
                                print(f"WARNING: Missing chunk {chunk_index} for image {image_id}")
                    else:
                        print(f"WARNING: No chunks found for image {image_id} in chunked_images")
                    
                    debug_print(f"Final reassembled image total size: {len(complete_content)} bytes")
                    
                    # For large images (>1MB), use a URL reference instead of embedding in JSON
                    if len(complete_content) > 1024 * 1024:  # 1MB threshold
                        debug_print(f"Large image detected ({len(complete_content)} bytes), using URL reference")
                        # Store the complete content temporarily and provide a URL reference
                        message['content'] = f"/api/image/{image_id}"
                        message['metadata']['is_large_image'] = True
                        message['metadata']['image_size'] = len(complete_content)
                        # Store the complete content in a way that can be retrieved by the image endpoint
                        # For now, we'll modify the message in place but this could be optimized
                        message['_complete_image_data'] = complete_content
                    else:
                        # Small enough to embed directly
                        message['content'] = complete_content
                    
                    # IMPORTANT: Preserve extracted_text and vision_analysis in the final message
                    # These fields are needed by the frontend to display the info drawer
                    if extracted_text:
                        message['extracted_text'] = extracted_text
                    if vision_analysis:
                        message['vision_analysis'] = vision_analysis
            
            return jsonify({'messages': messages})
        except CosmosResourceNotFoundError:
            return jsonify({'messages': []})
        except Exception as e:
            print(f"ERROR: Failed to get messages: {str(e)}")
            return jsonify({'error': 'Conversation not found'}), 404

    @app.route('/api/image/<image_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_get_image(image_id):
        """Serve large images that were stored in chunks"""
        print(f"🔥 IMAGE ENDPOINT CALLED: {image_id}")
        print(f"🔥 Request URL: {request.url}")
        print(f"🔥 Request headers: {dict(request.headers)}")
        
        user_id = get_current_user_id()
        if not user_id:
            print(f"🔥 Authentication failed for image request")
            return jsonify({'error': 'User not authenticated'}), 401
            
        try:
            # Extract conversation_id from image_id (format: conversation_id_image_timestamp_random)
            parts = image_id.split('_')
            if len(parts) < 4:
                return jsonify({'error': 'Invalid image ID format'}), 400
            
            # Reconstruct conversation_id (everything except the last 3 parts)
            conversation_id = '_'.join(parts[:-3])
            
            debug_print(f"Serving image {image_id} from conversation {conversation_id}")
            
            # Query for the main image document and chunks
            message_query = f"SELECT * FROM c WHERE c.conversation_id = '{conversation_id}'"
            all_items = list(cosmos_messages_container.query_items(
                query=message_query,
                partition_key=conversation_id
            ))
            
            # Find the specific image and its chunks
            main_image = None
            chunks = {}
            
            debug_print(f"Searching through {len(all_items)} items for image {image_id}")
            
            for item in all_items:
                item_id = item.get('id')
                item_role = item.get('role')
                debug_print(f"Checking item {item_id}, role: {item_role}")
                
                if item_id == image_id and item_role == 'image':
                    main_image = item
                    debug_print(f"✅ Found main image document: {item_id}")
                    debug_print(f"Main image content length: {len(item.get('content', ''))} bytes")
                    debug_print(f"Main image metadata: {item.get('metadata', {})}")
                elif (item_role == 'image_chunk' and 
                      item.get('parent_message_id') == image_id):
                    chunk_index = item.get('metadata', {}).get('chunk_index', 0)
                    chunk_content = item.get('content', '')
                    chunks[chunk_index] = chunk_content
                    debug_print(f"✅ Found chunk {chunk_index}: {len(chunk_content)} bytes")
                    debug_print(f"Chunk {chunk_index} starts with: {chunk_content[:50]}...")
                    debug_print(f"Chunk {chunk_index} ends with: ...{chunk_content[-20:]}")
            
            debug_print(f"Found main_image: {main_image is not None}")
            debug_print(f"Found chunks: {list(chunks.keys())}")
            
            if not main_image:
                print(f"ERROR: Main image not found for {image_id}")
                return jsonify({'error': 'Image not found'}), 404
            
            # Reassemble the image
            complete_content = main_image.get('content', '')
            total_chunks = main_image.get('metadata', {}).get('total_chunks', 1)
            
            debug_print(f"Starting reassembly...")
            debug_print(f"Main content length: {len(complete_content)} bytes")
            debug_print(f"Expected total chunks: {total_chunks}")
            debug_print(f"Available chunk indices: {list(chunks.keys())}")
            debug_print(f"Main content starts with: {complete_content[:50]}...")
            debug_print(f"Main content ends with: ...{complete_content[-20:]}")
            
            reassembly_log = []
            original_length = len(complete_content)
            
            for chunk_index in range(1, total_chunks):
                if chunk_index in chunks:
                    chunk_content = chunks[chunk_index]
                    complete_content += chunk_content
                    reassembly_log.append(f"Added chunk {chunk_index}: {len(chunk_content)} bytes")
                    debug_print(f"Added chunk {chunk_index}: {len(chunk_content)} bytes")
                    debug_print(f"Total length now: {len(complete_content)} bytes")
                else:
                    error_msg = f"Missing chunk {chunk_index}"
                    reassembly_log.append(f"❌ {error_msg}")
                    print(f"WARNING: {error_msg}")
            
            final_length = len(complete_content)
            debug_print(f"Reassembly complete!")
            debug_print(f"Original length: {original_length} bytes")
            debug_print(f"Final length: {final_length} bytes")
            debug_print(f"Added: {final_length - original_length} bytes")
            debug_print(f"Reassembly log: {reassembly_log}")
            debug_print(f"Final content starts with: {complete_content[:50]}...")
            debug_print(f"Final content ends with: ...{complete_content[-20:]}")
            
            # Return the image data with appropriate headers
            if complete_content.startswith('data:image/'):
                # Extract mime type and base64 data
                header, base64_data = complete_content.split(',', 1)
                mime_type = header.split(':')[1].split(';')[0]
                
                import base64
                image_data = base64.b64decode(base64_data)
                
                return Response(
                    image_data,
                    mimetype=mime_type,
                    headers={
                        'Content-Length': len(image_data),
                        'Cache-Control': 'public, max-age=3600'  # Cache for 1 hour
                    }
                )
            else:
                return jsonify({'error': 'Invalid image format'}), 400
                
        except Exception as e:
            print(f"ERROR: Failed to serve image {image_id}: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to retrieve image'}), 500
        
    @app.route('/api/get_conversations', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_conversations():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        query = f"SELECT * FROM c WHERE c.user_id = '{user_id}' ORDER BY c.last_updated DESC"
        items = list(cosmos_conversations_container.query_items(query=query, enable_cross_partition_query=True))
        return jsonify({
            'conversations': items
        }), 200


    @app.route('/api/create_conversation', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def create_conversation():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        conversation_id = str(uuid.uuid4())
        conversation_item = {
            'id': conversation_id,
            'user_id': user_id,
            'last_updated': datetime.utcnow().isoformat(),
            'title': 'New Conversation',
            'context': [],
            'tags': [],
            'strict': False,
            'is_pinned': False,
            'is_hidden': False
        }
        cosmos_conversations_container.upsert_item(conversation_item)
        
        # Log conversation creation
        log_conversation_creation(
            user_id=user_id,
            conversation_id=conversation_id,
            title='New Conversation',
            workspace_type='personal'
        )
        
        # Mark as logged to activity logs to prevent duplicate migration
        conversation_item['added_to_activity_log'] = True
        cosmos_conversations_container.upsert_item(conversation_item)

        return jsonify({
            'conversation_id': conversation_id,
            'title': 'New Conversation'
        }), 200
    
    @app.route('/api/conversations/<conversation_id>', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def update_conversation_title(conversation_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        # Parse the new title from the request body
        data = request.get_json()
        new_title = data.get('title', '').strip()
        if not new_title:
            return jsonify({'error': 'Title is required'}), 400

        try:
            # Retrieve the conversation
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )

            # Ensure that the conversation belongs to the current user
            if conversation_item.get('user_id') != user_id:
                return jsonify({'error': 'Forbidden'}), 403

            # Update the title
            conversation_item['title'] = new_title

            # Optionally update the last_updated time
            from datetime import datetime
            conversation_item['last_updated'] = datetime.utcnow().isoformat()

            # Write back to Cosmos DB
            cosmos_conversations_container.upsert_item(conversation_item)

            return jsonify({
                'message': 'Conversation updated', 
                'title': new_title,
                'classification': conversation_item.get('classification', []) # Send classifications if any
            }), 200
        except Exception as e:
            print(e)
            return jsonify({'error': 'Failed to update conversation'}), 500
        
    @app.route('/api/conversations/<conversation_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def delete_conversation(conversation_id):
        """
        Delete a conversation. If archiving is enabled, copy it to archived_conversations first.
        """
        settings = get_settings()
        archiving_enabled = settings.get('enable_conversation_archiving', False)

        try:
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
        except CosmosResourceNotFoundError:
            return jsonify({
                "error": f"Conversation {conversation_id} not found."
            }), 404
        except Exception as e:
            return jsonify({
                "error": str(e)
            }), 500

        if archiving_enabled:
            archived_item = dict(conversation_item)
            archived_item["archived_at"] = datetime.utcnow().isoformat()
            cosmos_archived_conversations_container.upsert_item(archived_item)
            
            # Log conversation archival
            log_conversation_archival(
                user_id=conversation_item.get('user_id'),
                conversation_id=conversation_id,
                title=conversation_item.get('title', 'Untitled'),
                workspace_type='personal',
                context=conversation_item.get('context', []),
                tags=conversation_item.get('tags', [])
            )

        message_query = f"SELECT * FROM c WHERE c.conversation_id = '{conversation_id}'"
        results = list(cosmos_messages_container.query_items(
            query=message_query,
            partition_key=conversation_id
        ))

        for doc in results:
            if archiving_enabled:
                archived_doc = dict(doc)
                archived_doc["archived_at"] = datetime.utcnow().isoformat()
                cosmos_archived_messages_container.upsert_item(archived_doc)

            cosmos_messages_container.delete_item(doc['id'], partition_key=conversation_id)
        
        # Log conversation deletion before actual deletion
        log_conversation_deletion(
            user_id=conversation_item.get('user_id'),
            conversation_id=conversation_id,
            title=conversation_item.get('title', 'Untitled'),
            workspace_type='personal',
            context=conversation_item.get('context', []),
            tags=conversation_item.get('tags', []),
            is_archived=archiving_enabled,
            is_bulk_operation=False
        )
        
        try:
            cosmos_conversations_container.delete_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            # TODO: Delete any facts that were stored with this conversation.
        except Exception as e:
            return jsonify({
                "error": str(e)
            }), 500

        return jsonify({
            "success": True
        }), 200
        
    @app.route('/api/delete_multiple_conversations', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def delete_multiple_conversations():
        """
        Delete multiple conversations at once. If archiving is enabled, copy them to archived_conversations first.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
            
        data = request.get_json()
        conversation_ids = data.get('conversation_ids', [])
        
        if not conversation_ids:
            return jsonify({'error': 'No conversation IDs provided'}), 400
            
        settings = get_settings()
        archiving_enabled = settings.get('enable_conversation_archiving', False)
        
        success_count = 0
        failed_ids = []
        
        for conversation_id in conversation_ids:
            try:
                # Verify the conversation exists and belongs to the user
                try:
                    conversation_item = cosmos_conversations_container.read_item(
                        item=conversation_id,
                        partition_key=conversation_id
                    )
                    
                    # Check if the conversation belongs to the current user
                    if conversation_item.get('user_id') != user_id:
                        failed_ids.append(conversation_id)
                        continue
                        
                except CosmosResourceNotFoundError:
                    failed_ids.append(conversation_id)
                    continue
                
                # Archive if enabled
                if archiving_enabled:
                    archived_item = dict(conversation_item)
                    archived_item["archived_at"] = datetime.utcnow().isoformat()
                    cosmos_archived_conversations_container.upsert_item(archived_item)
                    
                    # Log conversation archival
                    log_conversation_archival(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        title=conversation_item.get('title', 'Untitled'),
                        workspace_type='personal',
                        context=conversation_item.get('context', []),
                        tags=conversation_item.get('tags', [])
                    )
                
                # Get and archive messages if enabled
                message_query = f"SELECT * FROM c WHERE c.conversation_id = '{conversation_id}'"
                messages = list(cosmos_messages_container.query_items(
                    query=message_query,
                    partition_key=conversation_id
                ))
                
                for message in messages:
                    if archiving_enabled:
                        archived_message = dict(message)
                        archived_message["archived_at"] = datetime.utcnow().isoformat()
                        cosmos_archived_messages_container.upsert_item(archived_message)
                    
                    cosmos_messages_container.delete_item(message['id'], partition_key=conversation_id)
                
                # Log conversation deletion before actual deletion
                log_conversation_deletion(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    title=conversation_item.get('title', 'Untitled'),
                    workspace_type='personal',
                    context=conversation_item.get('context', []),
                    tags=conversation_item.get('tags', []),
                    is_archived=archiving_enabled,
                    is_bulk_operation=True
                )
                
                # Delete the conversation
                cosmos_conversations_container.delete_item(
                    item=conversation_id,
                    partition_key=conversation_id
                )
                
                success_count += 1
                
            except Exception as e:
                print(f"Error deleting conversation {conversation_id}: {str(e)}")
                failed_ids.append(conversation_id)
        
        return jsonify({
            "success": True,
            "deleted_count": success_count,
            "failed_ids": failed_ids
        }), 200

    @app.route('/api/conversations/<conversation_id>/pin', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def toggle_conversation_pin(conversation_id):
        """
        Toggle the pinned status of a conversation.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            # Retrieve the conversation
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            
            # Ensure that the conversation belongs to the current user
            if conversation_item.get('user_id') != user_id:
                return jsonify({'error': 'Forbidden'}), 403
            
            # Toggle the pinned status
            current_pinned = conversation_item.get('is_pinned', False)
            conversation_item['is_pinned'] = not current_pinned
            conversation_item['last_updated'] = datetime.utcnow().isoformat()
            
            # Update in Cosmos DB
            cosmos_conversations_container.upsert_item(conversation_item)
            
            return jsonify({
                'success': True,
                'is_pinned': conversation_item['is_pinned']
            }), 200
            
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404
        except Exception as e:
            print(f"Error toggling conversation pin: {e}")
            return jsonify({'error': 'Failed to toggle pin status'}), 500
    
    @app.route('/api/conversations/<conversation_id>/hide', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def toggle_conversation_hide(conversation_id):
        """
        Toggle the hidden status of a conversation.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            # Retrieve the conversation
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            
            # Ensure that the conversation belongs to the current user
            if conversation_item.get('user_id') != user_id:
                return jsonify({'error': 'Forbidden'}), 403
            
            # Toggle the hidden status
            current_hidden = conversation_item.get('is_hidden', False)
            conversation_item['is_hidden'] = not current_hidden
            conversation_item['last_updated'] = datetime.utcnow().isoformat()
            
            # Update in Cosmos DB
            cosmos_conversations_container.upsert_item(conversation_item)
            
            return jsonify({
                'success': True,
                'is_hidden': conversation_item['is_hidden']
            }), 200
            
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404
        except Exception as e:
            print(f"Error toggling conversation hide: {e}")
            return jsonify({'error': 'Failed to toggle hide status'}), 500

    @app.route('/api/conversations/bulk-pin', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def bulk_pin_conversations():
        """
        Pin or unpin multiple conversations at once.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        data = request.get_json()
        conversation_ids = data.get('conversation_ids', [])
        pin_action = data.get('action', 'pin')  # 'pin' or 'unpin'
        
        if not conversation_ids:
            return jsonify({'error': 'No conversation IDs provided'}), 400
        
        if pin_action not in ['pin', 'unpin']:
            return jsonify({'error': 'Invalid action. Must be "pin" or "unpin"'}), 400
        
        success_count = 0
        failed_ids = []
        
        for conversation_id in conversation_ids:
            try:
                conversation_item = cosmos_conversations_container.read_item(
                    item=conversation_id,
                    partition_key=conversation_id
                )
                
                # Check if the conversation belongs to the current user
                if conversation_item.get('user_id') != user_id:
                    failed_ids.append(conversation_id)
                    continue
                
                # Set pin status
                conversation_item['is_pinned'] = (pin_action == 'pin')
                conversation_item['last_updated'] = datetime.utcnow().isoformat()
                
                # Update in Cosmos DB
                cosmos_conversations_container.upsert_item(conversation_item)
                success_count += 1
                
            except CosmosResourceNotFoundError:
                failed_ids.append(conversation_id)
            except Exception as e:
                print(f"Error updating conversation {conversation_id}: {str(e)}")
                failed_ids.append(conversation_id)
        
        return jsonify({
            "success": True,
            "updated_count": success_count,
            "failed_ids": failed_ids,
            "action": pin_action
        }), 200

    @app.route('/api/conversations/bulk-hide', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def bulk_hide_conversations():
        """
        Hide or unhide multiple conversations at once.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        data = request.get_json()
        conversation_ids = data.get('conversation_ids', [])
        hide_action = data.get('action', 'hide')  # 'hide' or 'unhide'
        
        if not conversation_ids:
            return jsonify({'error': 'No conversation IDs provided'}), 400
        
        if hide_action not in ['hide', 'unhide']:
            return jsonify({'error': 'Invalid action. Must be "hide" or "unhide"'}), 400
        
        success_count = 0
        failed_ids = []
        
        for conversation_id in conversation_ids:
            try:
                conversation_item = cosmos_conversations_container.read_item(
                    item=conversation_id,
                    partition_key=conversation_id
                )
                
                # Check if the conversation belongs to the current user
                if conversation_item.get('user_id') != user_id:
                    failed_ids.append(conversation_id)
                    continue
                
                # Set hide status
                conversation_item['is_hidden'] = (hide_action == 'hide')
                conversation_item['last_updated'] = datetime.utcnow().isoformat()
                
                # Update in Cosmos DB
                cosmos_conversations_container.upsert_item(conversation_item)
                success_count += 1
                
            except CosmosResourceNotFoundError:
                failed_ids.append(conversation_id)
            except Exception as e:
                print(f"Error updating conversation {conversation_id}: {str(e)}")
                failed_ids.append(conversation_id)
        
        return jsonify({
            "success": True,
            "updated_count": success_count,
            "failed_ids": failed_ids,
            "action": hide_action
        }), 200

    @app.route('/api/conversations/<conversation_id>/metadata', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_conversation_metadata_api(conversation_id):
        """
        Get detailed metadata for a conversation including context, tags, and other information.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            # Retrieve the conversation
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            
            # Ensure that the conversation belongs to the current user
            if conversation_item.get('user_id') != user_id:
                return jsonify({'error': 'Forbidden'}), 403
            
            # Return the full conversation metadata
            return jsonify({
                "conversation_id": conversation_id,
                "title": conversation_item.get('title', ''),
                "user_id": conversation_item.get('user_id', ''),
                "last_updated": conversation_item.get('last_updated', ''),
                "classification": conversation_item.get('classification', []),
                "context": conversation_item.get('context', []),
                "tags": conversation_item.get('tags', []),
                "strict": conversation_item.get('strict', False),
                "is_pinned": conversation_item.get('is_pinned', False),
                "is_hidden": conversation_item.get('is_hidden', False)
            }), 200
            
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404
        except Exception as e:
            print(f"Error retrieving conversation metadata: {e}")
            return jsonify({'error': 'Failed to retrieve conversation metadata'}), 500
    
    @app.route('/api/conversations/classifications', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_user_classifications():
        """
        Get all unique classifications from user's conversations
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            # Query all conversations for this user
            query = f"SELECT c.classification FROM c WHERE c.user_id = '{user_id}'"
            items = list(cosmos_conversations_container.query_items(
                query=query,
                enable_cross_partition_query=True
            ))
            
            # Extract and flatten all classifications
            classifications_set = set()
            for item in items:
                classifications = item.get('classification', [])
                if isinstance(classifications, list):
                    for classification in classifications:
                        if classification and isinstance(classification, str):
                            classifications_set.add(classification.strip())
            
            # Sort alphabetically
            classifications_list = sorted(list(classifications_set))
            
            return jsonify({
                'success': True,
                'classifications': classifications_list
            }), 200
            
        except Exception as e:
            print(f"Error fetching classifications: {e}")
            return jsonify({'error': 'Failed to fetch classifications'}), 500
    
    @app.route('/api/search_conversations', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def search_conversations():
        """
        Search conversations and messages with filters and pagination
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json()
            search_term = data.get('search_term', '').strip()
            date_from = data.get('date_from', '')
            date_to = data.get('date_to', '')
            chat_types = data.get('chat_types', [])
            classifications = data.get('classifications', [])
            has_files = data.get('has_files', False)
            has_images = data.get('has_images', False)
            page = int(data.get('page', 1))
            per_page = int(data.get('per_page', 20))
            
            # Validate search term
            if not search_term or len(search_term) < 3:
                return jsonify({
                    'success': False,
                    'error': 'Search term must be at least 3 characters'
                }), 400
            
            # Build conversation query with filters
            # Find conversations where user is a participant (supports multi-user conversations)
            # Check both old schema (user_id at root) and new schema (participant tag)
            query_parts = [
                f"(c.user_id = '{user_id}' OR EXISTS(SELECT VALUE t FROM t IN c.tags WHERE t.category = 'participant' AND t.user_id = '{user_id}'))"
            ]
            
            debug_print(f"🔍 Search parameters:")
            debug_print(f"  user_id: {user_id}")
            debug_print(f"  search_term: {search_term}")
            debug_print(f"  date_from: {date_from}")
            debug_print(f"  date_to: {date_to}")
            debug_print(f"  chat_types: {chat_types}")
            debug_print(f"  classifications: {classifications}")
            
            if date_from:
                query_parts.append(f"c.last_updated >= '{date_from}'")
            if date_to:
                query_parts.append(f"c.last_updated <= '{date_to}T23:59:59'")
            
            conversation_query = f"SELECT * FROM c WHERE {' AND '.join(query_parts)}"
            debug_print(f"\n📋 Conversation query: {conversation_query}")
            
            conversations = list(cosmos_conversations_container.query_items(
                query=conversation_query,
                enable_cross_partition_query=True,
                max_item_count=-1  # Get all items, no pagination limit
            ))
            
            debug_print(f"Found {len(conversations)} conversations from query")
            
            # Check if target conversation is in the results
            target_conv_id = "2712dbad-560d-4d2e-a354-b8f67fcf9429"
            target_conv = next((c for c in conversations if c['id'] == target_conv_id), None)
            if target_conv:
                debug_print(f"\n🎯 Found target conversation {target_conv_id}")
                debug_print(f"   chat_type: {target_conv.get('chat_type')}")
                debug_print(f"   title: {target_conv.get('title', 'N/A')}")
            else:
                debug_print(f"\n❌ Target conversation {target_conv_id} NOT in query results")
            
            # Filter by chat types if specified
            if chat_types:
                before_count = len(conversations)
                filtered_out = []
                filtered_in = []
                
                for c in conversations:
                    # Default to 'personal' if chat_type is not defined (legacy conversations)
                    chat_type = c.get('chat_type', 'personal')
                    if chat_type in chat_types:
                        filtered_in.append(c)
                    else:
                        filtered_out.append(c)
                
                conversations = filtered_in
                debug_print(f"After chat_type filter: {len(conversations)} (removed {before_count - len(conversations)})")
                
                # Show some examples of filtered out chat types
                if filtered_out:
                    unique_types = set(c.get('chat_type', 'None/personal') for c in filtered_out[:10])
                    debug_print(f"   Filtered out chat_types (sample): {unique_types}")
            
            # Filter by classifications if specified
            if classifications:
                before_count = len(conversations)
                conversations = [c for c in conversations if any(
                    cls in (c.get('classification', []) or []) for cls in classifications
                )]
                debug_print(f"After classification filter: {len(conversations)} (removed {before_count - len(conversations)})")
            
            # Search messages in each conversation
            results = []
            search_lower = search_term.lower()
            
            debug_print(f"🔍 Starting search for term: '{search_term}'")
            debug_print(f"Found {len(conversations)} conversations to search")
            
            # Create a set of conversation IDs for fast lookup
            conversation_ids = set(c['id'] for c in conversations)
            conversation_map = {c['id']: c for c in conversations}
            
            # Do a single cross-partition query for all matching messages
            # This is much faster than querying each conversation individually
            message_query = f"SELECT * FROM m WHERE CONTAINS(m.content, '{search_term}', true) AND (m.role = 'user' OR m.role = 'assistant')"
            debug_print(f"\n📋 Cross-partition message query: {message_query}")
            
            all_matching_messages = list(cosmos_messages_container.query_items(
                query=message_query,
                enable_cross_partition_query=True,
                max_item_count=-1
            ))
            
            debug_print(f"Found {len(all_matching_messages)} total messages across all conversations")
            
            # Group messages by conversation and filter
            messages_by_conversation = {}
            for msg in all_matching_messages:
                conv_id = msg.get('conversation_id')
                
                # Only include messages from conversations we have access to
                if conv_id not in conversation_ids:
                    continue
                
                # Filter out inactive threads
                thread_info = msg.get('metadata', {}).get('thread_info', {})
                active = thread_info.get('active_thread')
                
                # Include all messages where active_thread is not explicitly False
                if active is not False:
                    if conv_id not in messages_by_conversation:
                        messages_by_conversation[conv_id] = []
                    messages_by_conversation[conv_id].append(msg)
            
            debug_print(f"After filtering: {len(messages_by_conversation)} conversations have matching messages")
            
            # Build results for each conversation with matches
            for conv_id, matching_messages in messages_by_conversation.items():
                
                # Apply file/image filters if specified
                if has_files or has_images:
                    filtered_messages = []
                    for msg in matching_messages:
                        metadata = msg.get('metadata', {})
                        if has_files and metadata.get('uploaded_files'):
                            filtered_messages.append(msg)
                        elif has_images and metadata.get('generated_images'):
                            filtered_messages.append(msg)
                        elif not has_files and not has_images:
                            filtered_messages.append(msg)
                    matching_messages = filtered_messages
                
                if matching_messages:
                    # Get conversation details
                    conversation = conversation_map.get(conv_id)
                    if not conversation:
                        continue
                    
                    # Build message snippets
                    message_snippets = []
                    for msg in matching_messages[:5]:  # Limit to 5 messages per conversation
                        content = msg.get('content', '')
                        content_lower = content.lower()
                        
                        # Find match position
                        match_pos = content_lower.find(search_lower)
                        if match_pos != -1:
                            # Extract 50 chars before and after
                            start = max(0, match_pos - 50)
                            end = min(len(content), match_pos + len(search_term) + 50)
                            snippet = content[start:end]
                            
                            # Add ellipsis if truncated
                            if start > 0:
                                snippet = '...' + snippet
                            if end < len(content):
                                snippet = snippet + '...'
                            
                            message_snippets.append({
                                'message_id': msg.get('id'),
                                'content_snippet': snippet,
                                'timestamp': msg.get('timestamp', ''),
                                'role': msg.get('role', 'unknown')
                            })
                    
                    results.append({
                        'conversation': {
                            'id': conversation['id'],
                            'title': conversation.get('title', 'Untitled'),
                            'last_updated': conversation.get('last_updated', ''),
                            'classification': conversation.get('classification', []),
                            'chat_type': conversation.get('chat_type', 'personal'),
                            'is_pinned': conversation.get('is_pinned', False),
                            'is_hidden': conversation.get('is_hidden', False)
                        },
                        'messages': message_snippets,
                        'match_count': len(matching_messages)
                    })
            
            # Sort by last_updated (most recent first)
            results.sort(key=lambda x: x['conversation']['last_updated'], reverse=True)
            
            # Pagination
            total_results = len(results)
            total_pages = math.ceil(total_results / per_page) if total_results > 0 else 1
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            paginated_results = results[start_idx:end_idx]
            
            return jsonify({
                'success': True,
                'total_results': total_results,
                'page': page,
                'total_pages': total_pages,
                'per_page': per_page,
                'results': paginated_results
            }), 200
            
        except Exception as e:
            print(f"Error searching conversations: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to search conversations'}), 500
    
    @app.route('/api/user-settings/search-history', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_search_history():
        """Get user's search history"""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            history = get_user_search_history(user_id)
            return jsonify({
                'success': True,
                'history': history
            }), 200
        except Exception as e:
            print(f"Error retrieving search history: {e}")
            return jsonify({'error': 'Failed to retrieve search history'}), 500
    
    @app.route('/api/user-settings/search-history', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def save_search_to_history():
        """Save a search term to user's history"""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json()
            search_term = data.get('search_term', '').strip()
            
            if not search_term:
                return jsonify({'error': 'Search term is required'}), 400
            
            history = add_search_to_history(user_id, search_term)
            return jsonify({
                'success': True,
                'history': history
            }), 200
        except Exception as e:
            print(f"Error saving search to history: {e}")
            return jsonify({'error': 'Failed to save search to history'}), 500
    
    @app.route('/api/user-settings/search-history', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def clear_search_history():
        """Clear user's search history"""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            success = clear_user_search_history(user_id)
            if success:
                return jsonify({
                    'success': True,
                    'message': 'Search history cleared'
                }), 200
            else:
                return jsonify({'error': 'Failed to clear search history'}), 500
        except Exception as e:
            print(f"Error clearing search history: {e}")
            return jsonify({'error': 'Failed to clear search history'}), 500
    
    @app.route('/api/message/<message_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def delete_message(message_id):
        """
        Delete a message or entire thread. Only the message author can delete their messages.
        If archiving is enabled, messages are marked with is_deleted=true and masked.
        If archiving is disabled, messages are permanently deleted.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json() or {}
            delete_thread = data.get('delete_thread', False)
            
            settings = get_settings()
            archiving_enabled = settings.get('enable_conversation_archiving', False)
            
            # Find the message using cross-partition query
            query = "SELECT * FROM c WHERE c.id = @message_id"
            params = [{"name": "@message_id", "value": message_id}]
            message_results = list(cosmos_messages_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            
            if not message_results:
                return jsonify({'error': 'Message not found'}), 404
            
            message_doc = message_results[0]
            conversation_id = message_doc.get('conversation_id')
            
            # Verify ownership - only the message author can delete their message
            message_user_id = message_doc.get('metadata', {}).get('user_info', {}).get('user_id')
            if not message_user_id:
                # Fallback: check conversation ownership for backwards compatibility
                # All messages in a conversation (user, assistant, system) belong to the conversation owner
                try:
                    conversation = cosmos_conversations_container.read_item(
                        item=conversation_id,
                        partition_key=conversation_id
                    )
                    if conversation.get('user_id') != user_id:
                        return jsonify({'error': 'You can only delete messages from your own conversations'}), 403
                except:
                    return jsonify({'error': 'Conversation not found'}), 404
            elif message_user_id != user_id:
                return jsonify({'error': 'You can only delete your own messages'}), 403
            
            # Collect messages to delete
            messages_to_delete = []
            
            if delete_thread and message_doc.get('role') == 'user':
                # Delete entire thread: user message + system message + assistant/image messages
                thread_id = message_doc.get('metadata', {}).get('thread_info', {}).get('thread_id')
                thread_previous_id = message_doc.get('metadata', {}).get('thread_info', {}).get('previous_thread_id')
                
                if thread_id:
                    # Query all messages in this thread exchange (user, system, assistant messages with same thread_id)
                    # Do NOT include subsequent threads that reference this thread_id as previous_thread_id
                    thread_query = f"""
                        SELECT * FROM c 
                        WHERE c.conversation_id = '{conversation_id}' 
                        AND c.metadata.thread_info.thread_id = '{thread_id}'
                    """
                    thread_messages = list(cosmos_messages_container.query_items(
                        query=thread_query,
                        partition_key=conversation_id
                    ))
                    messages_to_delete = thread_messages
                    
                    # THREAD CHAIN REPAIR: Update subsequent threads to maintain chain integrity
                    # Find messages where previous_thread_id points to the thread we're deleting
                    subsequent_query = f"""
                        SELECT * FROM c 
                        WHERE c.conversation_id = '{conversation_id}' 
                        AND c.metadata.thread_info.previous_thread_id = '{thread_id}'
                    """
                    subsequent_messages = list(cosmos_messages_container.query_items(
                        query=subsequent_query,
                        partition_key=conversation_id
                    ))
                    
                    # Update each subsequent message to skip over the deleted thread
                    # Point their previous_thread_id to the deleted thread's previous_thread_id
                    for subsequent_msg in subsequent_messages:
                        # Skip messages that are being deleted (they're in the same thread)
                        if subsequent_msg['id'] in [m['id'] for m in messages_to_delete]:
                            continue
                        
                        # Update previous_thread_id to maintain chain
                        if 'metadata' not in subsequent_msg:
                            subsequent_msg['metadata'] = {}
                        if 'thread_info' not in subsequent_msg['metadata']:
                            subsequent_msg['metadata']['thread_info'] = {}
                        
                        subsequent_msg['metadata']['thread_info']['previous_thread_id'] = thread_previous_id
                        
                        # Upsert the updated message
                        cosmos_messages_container.upsert_item(subsequent_msg)
                        print(f"Repaired thread chain: Message {subsequent_msg['id']} now points to thread {thread_previous_id}")
                else:
                    messages_to_delete = [message_doc]
            else:
                # Delete only the specified message
                messages_to_delete = [message_doc]
            
            # THREAD ATTEMPT PROMOTION: If deleting an active thread attempt, promote next attempt
            if messages_to_delete:
                first_msg = messages_to_delete[0]
                thread_id = first_msg.get('metadata', {}).get('thread_info', {}).get('thread_id')
                is_active = first_msg.get('metadata', {}).get('thread_info', {}).get('active_thread', True)
                
                if thread_id and is_active:
                    # Find all other attempts for this thread_id
                    other_attempts_query = f"""
                        SELECT * FROM c 
                        WHERE c.conversation_id = '{conversation_id}' 
                        AND c.metadata.thread_info.thread_id = '{thread_id}'
                        AND c.id NOT IN ({','.join([f"'{m['id']}'" for m in messages_to_delete])})
                        AND c.role = 'user'
                    """
                    other_attempts = list(cosmos_messages_container.query_items(
                        query=other_attempts_query,
                        partition_key=conversation_id
                    ))
                    
                    # If there are other attempts, promote the next one (lowest thread_attempt)
                    if other_attempts:
                        # Sort by thread_attempt to find the next one
                        other_attempts.sort(key=lambda m: m.get('metadata', {}).get('thread_info', {}).get('thread_attempt', 0))
                        next_attempt_number = other_attempts[0].get('metadata', {}).get('thread_info', {}).get('thread_attempt', 0)
                        
                        # Activate all messages with this thread_attempt
                        activate_query = f"""
                            SELECT * FROM c 
                            WHERE c.conversation_id = '{conversation_id}' 
                            AND c.metadata.thread_info.thread_id = '{thread_id}'
                            AND c.metadata.thread_info.thread_attempt = {next_attempt_number}
                        """
                        messages_to_activate = list(cosmos_messages_container.query_items(
                            query=activate_query,
                            partition_key=conversation_id
                        ))
                        
                        for msg_to_activate in messages_to_activate:
                            if 'metadata' not in msg_to_activate:
                                msg_to_activate['metadata'] = {}
                            if 'thread_info' not in msg_to_activate['metadata']:
                                msg_to_activate['metadata']['thread_info'] = {}
                            msg_to_activate['metadata']['thread_info']['active_thread'] = True
                            cosmos_messages_container.upsert_item(msg_to_activate)
                        
                        print(f"Promoted thread_attempt {next_attempt_number} to active after deleting active thread {thread_id}")
            
            deleted_message_ids = []
            
            for msg in messages_to_delete:
                msg_id = msg['id']
                
                if archiving_enabled:
                    # Mark as deleted and mask the message
                    if 'metadata' not in msg:
                        msg['metadata'] = {}
                    
                    msg['metadata']['is_deleted'] = True
                    msg['metadata']['deleted_by_user_id'] = user_id
                    msg['metadata']['deleted_timestamp'] = datetime.utcnow().isoformat()
                    msg['metadata']['masked'] = True
                    msg['metadata']['masked_by_user_id'] = user_id
                    msg['metadata']['masked_timestamp'] = datetime.utcnow().isoformat()
                    
                    # Archive the message
                    archived_msg = dict(msg)
                    archived_msg['archived_at'] = datetime.utcnow().isoformat()
                    cosmos_archived_messages_container.upsert_item(archived_msg)
                    
                    # Update the message in the main container (for conversation history exclusion)
                    cosmos_messages_container.upsert_item(msg)
                else:
                    # Permanently delete the message
                    cosmos_messages_container.delete_item(msg_id, partition_key=conversation_id)
                
                deleted_message_ids.append(msg_id)
            
            return jsonify({
                'success': True,
                'deleted_message_ids': deleted_message_ids,
                'archived': archiving_enabled
            }), 200
            
        except Exception as e:
            print(f"Error deleting message: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to delete message'}), 500
    @app.route('/api/message/<message_id>/retry', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def retry_message(message_id):
        """
        Retry/regenerate a message by creating new user+system+assistant messages 
        with incremented thread_attempt and same thread_id.
        Only the message author can retry their messages.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json() or {}
            selected_model = data.get('model')
            reasoning_effort = data.get('reasoning_effort')
            agent_info = data.get('agent_info')  # Get agent info if provided
            
            # Find the original message
            query = "SELECT * FROM c WHERE c.id = @message_id"
            params = [{"name": "@message_id", "value": message_id}]
            message_results = list(cosmos_messages_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            
            if not message_results:
                return jsonify({'error': 'Message not found'}), 404
            
            original_msg = message_results[0]
            conversation_id = original_msg.get('conversation_id')
            original_role = original_msg.get('role')
            
            # Verify ownership
            message_user_id = original_msg.get('metadata', {}).get('user_info', {}).get('user_id')
            if not message_user_id:
                # Fallback to conversation ownership
                try:
                    conversation = cosmos_conversations_container.read_item(
                        item=conversation_id,
                        partition_key=conversation_id
                    )
                    if conversation.get('user_id') != user_id:
                        return jsonify({'error': 'You can only retry messages from your own conversations'}), 403
                except:
                    return jsonify({'error': 'Conversation not found'}), 404
            elif message_user_id != user_id:
                return jsonify({'error': 'You can only retry your own messages'}), 403
            
            # Get thread info from original message
            thread_id = original_msg.get('metadata', {}).get('thread_info', {}).get('thread_id')
            previous_thread_id = original_msg.get('metadata', {}).get('thread_info', {}).get('previous_thread_id')
            
            if not thread_id:
                return jsonify({'error': 'Message has no thread_id'}), 400
            
            # Find current max thread_attempt for this thread_id
            attempt_query = f"""
                SELECT VALUE MAX(c.metadata.thread_info.thread_attempt) 
                FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
            """
            attempt_results = list(cosmos_messages_container.query_items(
                query=attempt_query,
                partition_key=conversation_id
            ))
            
            current_max_attempt = attempt_results[0] if attempt_results and attempt_results[0] is not None else 0
            new_attempt = current_max_attempt + 1
            
            # Set all existing attempts for this thread to active_thread=false
            deactivate_query = f"""
                SELECT * FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
            """
            existing_messages = list(cosmos_messages_container.query_items(
                query=deactivate_query,
                partition_key=conversation_id
            ))
            
            print(f"🔍 Retry - Found {len(existing_messages)} existing messages to deactivate")
            
            for msg in existing_messages:
                msg_id = msg.get('id', 'unknown')
                msg_role = msg.get('role', 'unknown')
                old_active = msg.get('metadata', {}).get('thread_info', {}).get('active_thread', None)
                
                if 'metadata' not in msg:
                    msg['metadata'] = {}
                if 'thread_info' not in msg['metadata']:
                    msg['metadata']['thread_info'] = {}
                msg['metadata']['thread_info']['active_thread'] = False
                cosmos_messages_container.upsert_item(msg)
                
                print(f"  ✏️ Deactivated: {msg_id} (role={msg_role}, was_active={old_active}, now_active=False)")
            
            # Find the original user message in this thread to get the content
            # Get the FIRST user message in this thread (attempt=1) to ensure we get the original content
            user_msg_query = f"""
                SELECT * FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
                AND c.role = 'user'
                ORDER BY c.metadata.thread_info.thread_attempt ASC
            """
            user_msg_results = list(cosmos_messages_container.query_items(
                query=user_msg_query,
                partition_key=conversation_id
            ))
            
            if not user_msg_results:
                return jsonify({'error': 'User message not found in thread'}), 404
            
            # Get the first user message (attempt 1) to get original content and metadata
            original_user_msg = user_msg_results[0]
            user_content = original_user_msg.get('content', '')
            original_metadata = original_user_msg.get('metadata', {})
            original_thread_info = original_metadata.get('thread_info', {})
            
            print(f"🔍 Retry - Original user message: {original_user_msg.get('id')}")
            print(f"🔍 Retry - Original thread_id: {original_thread_info.get('thread_id')}")
            print(f"🔍 Retry - Original previous_thread_id: {original_thread_info.get('previous_thread_id')}")
            print(f"🔍 Retry - Original attempt: {original_thread_info.get('thread_attempt')}")
            print(f"🔍 Retry - New attempt will be: {new_attempt}")
            
            # Create new user message with same content but new attempt number
            import uuid
            import time
            import random
            
            new_user_message_id = f"{conversation_id}_user_{int(time.time())}_{random.randint(1000,9999)}"
            
            # Copy metadata but update thread_attempt and keep same thread_id and previous_thread_id from original
            new_metadata = dict(original_metadata)
            new_metadata['retried'] = True  # Mark as retried
            new_metadata['thread_info'] = {
                'thread_id': thread_id,  # Keep same thread_id
                'previous_thread_id': original_thread_info.get('previous_thread_id'),  # Preserve original previous_thread_id
                'active_thread': True,
                'thread_attempt': new_attempt
            }
            
            print(f"🔍 Retry - New user message ID: {new_user_message_id}")
            print(f"🔍 Retry - New thread_info: {new_metadata['thread_info']}")
            
            # Create new user message
            new_user_message = {
                'id': new_user_message_id,
                'conversation_id': conversation_id,
                'role': 'user',
                'content': user_content,
                'timestamp': datetime.utcnow().isoformat(),
                'model_deployment_name': None,
                'metadata': new_metadata
            }
            cosmos_messages_container.upsert_item(new_user_message)
            
            # Build chat request parameters from original message metadata
            chat_request = {
                'message': user_content,
                'conversation_id': conversation_id,
                'model_deployment': selected_model or original_metadata.get('model_selection', {}).get('selected_model'),
                'reasoning_effort': reasoning_effort or original_metadata.get('reasoning_effort'),
                'hybrid_search': original_metadata.get('document_search', {}).get('enabled', False),
                'selected_document_id': original_metadata.get('document_search', {}).get('document_id'),
                'doc_scope': original_metadata.get('document_search', {}).get('scope'),
                'top_n': original_metadata.get('document_search', {}).get('top_n'),
                'classifications': original_metadata.get('document_search', {}).get('classifications'),
                'image_generation': original_metadata.get('image_generation', {}).get('enabled', False),
                'active_group_id': original_metadata.get('chat_context', {}).get('group_id'),
                'active_public_workspace_id': original_metadata.get('chat_context', {}).get('public_workspace_id'),
                'chat_type': original_metadata.get('chat_context', {}).get('type', 'user'),
                'retry_user_message_id': new_user_message_id,  # Pass this to skip user message creation
                'retry_thread_id': thread_id,  # Pass thread_id to maintain same thread
                'retry_thread_attempt': new_attempt  # Pass attempt number
            }
            
            # Add agent_info to chat request if provided (for agent-based retry)
            if agent_info:
                chat_request['agent_info'] = agent_info
                print(f"🤖 Retry - Using agent: {agent_info.get('display_name')} ({agent_info.get('name')})")
            elif original_metadata.get('agent_selection'):
                # Use original agent selection if no new agent specified
                chat_request['agent_info'] = original_metadata.get('agent_selection')
                print(f"🤖 Retry - Using original agent from metadata")
            
            print(f"🔍 Retry - Chat request params: retry_user_message_id={new_user_message_id}, retry_thread_id={thread_id}, retry_thread_attempt={new_attempt}")
            
            # Make internal request to chat API
            from flask import g
            g.conversation_id = conversation_id
            
            # Import and call chat function directly
            # We'll need to modify the chat_api to handle retry requests
            return jsonify({
                'success': True,
                'message': 'Retry initiated',
                'thread_id': thread_id,
                'new_attempt': new_attempt,
                'user_message_id': new_user_message_id,
                'chat_request': chat_request
            }), 200
            
        except Exception as e:
            print(f"Error retrying message: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to retry message'}), 500

    @app.route('/api/message/<message_id>/edit', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def edit_message(message_id):
        """
        Edit a user message and regenerate the response with the edited content.
        Creates a new attempt with edited content while preserving original model/settings.
        Only the message author can edit their messages.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json() or {}
            edited_content = data.get('content', '').strip()
            
            if not edited_content:
                return jsonify({'error': 'Message content cannot be empty'}), 400
            
            # Find the original message
            query = "SELECT * FROM c WHERE c.id = @message_id"
            params = [{"name": "@message_id", "value": message_id}]
            message_results = list(cosmos_messages_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            
            if not message_results:
                return jsonify({'error': 'Message not found'}), 404
            
            original_msg = message_results[0]
            conversation_id = original_msg.get('conversation_id')
            original_role = original_msg.get('role')
            
            # Only allow editing user messages
            if original_role != 'user':
                return jsonify({'error': 'Only user messages can be edited'}), 400
            
            # Verify ownership
            message_user_id = original_msg.get('metadata', {}).get('user_info', {}).get('user_id')
            if not message_user_id:
                # Fallback to conversation ownership
                try:
                    conversation = cosmos_conversations_container.read_item(
                        item=conversation_id,
                        partition_key=conversation_id
                    )
                    if conversation.get('user_id') != user_id:
                        return jsonify({'error': 'You can only edit messages from your own conversations'}), 403
                except:
                    return jsonify({'error': 'Conversation not found'}), 404
            elif message_user_id != user_id:
                return jsonify({'error': 'You can only edit your own messages'}), 403
            
            # Get thread info from original message
            thread_id = original_msg.get('metadata', {}).get('thread_info', {}).get('thread_id')
            previous_thread_id = original_msg.get('metadata', {}).get('thread_info', {}).get('previous_thread_id')
            
            if not thread_id:
                return jsonify({'error': 'Message has no thread_id'}), 400
            
            # Find current max thread_attempt for this thread_id
            attempt_query = f"""
                SELECT VALUE MAX(c.metadata.thread_info.thread_attempt) 
                FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
            """
            attempt_results = list(cosmos_messages_container.query_items(
                query=attempt_query,
                partition_key=conversation_id
            ))
            
            current_max_attempt = attempt_results[0] if attempt_results and attempt_results[0] is not None else 0
            new_attempt = current_max_attempt + 1
            
            # Set all existing attempts for this thread to active_thread=false
            deactivate_query = f"""
                SELECT * FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
            """
            existing_messages = list(cosmos_messages_container.query_items(
                query=deactivate_query,
                partition_key=conversation_id
            ))
            
            print(f"🔍 Edit - Found {len(existing_messages)} existing messages to deactivate")
            
            for msg in existing_messages:
                msg_id = msg.get('id', 'unknown')
                msg_role = msg.get('role', 'unknown')
                old_active = msg.get('metadata', {}).get('thread_info', {}).get('active_thread', None)
                
                if 'metadata' not in msg:
                    msg['metadata'] = {}
                if 'thread_info' not in msg['metadata']:
                    msg['metadata']['thread_info'] = {}
                msg['metadata']['thread_info']['active_thread'] = False
                cosmos_messages_container.upsert_item(msg)
                
                print(f"  ✏️ Deactivated: {msg_id} (role={msg_role}, was_active={old_active}, now_active=False)")
            
            # Get the FIRST user message in this thread (attempt=1) to get original metadata
            user_msg_query = f"""
                SELECT * FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
                AND c.role = 'user'
                ORDER BY c.metadata.thread_info.thread_attempt ASC
            """
            user_msg_results = list(cosmos_messages_container.query_items(
                query=user_msg_query,
                partition_key=conversation_id
            ))
            
            if not user_msg_results:
                return jsonify({'error': 'User message not found in thread'}), 404
            
            # Get the first user message (attempt 1) to get original metadata
            original_user_msg = user_msg_results[0]
            original_metadata = original_user_msg.get('metadata', {})
            original_thread_info = original_metadata.get('thread_info', {})
            
            print(f"🔍 Edit - Original user message: {original_user_msg.get('id')}")
            print(f"🔍 Edit - Original thread_id: {original_thread_info.get('thread_id')}")
            print(f"🔍 Edit - Original previous_thread_id: {original_thread_info.get('previous_thread_id')}")
            print(f"🔍 Edit - Original attempt: {original_thread_info.get('thread_attempt')}")
            print(f"🔍 Edit - New attempt will be: {new_attempt}")
            
            # Create new user message with edited content
            import time
            import random
            
            new_user_message_id = f"{conversation_id}_user_{int(time.time())}_{random.randint(1000,9999)}"
            
            # Copy metadata but update thread_attempt, add edited flag, and keep same thread_id
            new_metadata = dict(original_metadata)
            new_metadata['edited'] = True  # Mark as edited
            new_metadata['thread_info'] = {
                'thread_id': thread_id,  # Keep same thread_id
                'previous_thread_id': original_thread_info.get('previous_thread_id'),  # Preserve original
                'active_thread': True,
                'thread_attempt': new_attempt
            }
            
            print(f"🔍 Edit - New user message ID: {new_user_message_id}")
            print(f"🔍 Edit - New thread_info: {new_metadata['thread_info']}")
            print(f"🔍 Edit - Edited flag set: {new_metadata.get('edited')}")
            
            # Create new user message with edited content
            new_user_message = {
                'id': new_user_message_id,
                'conversation_id': conversation_id,
                'role': 'user',
                'content': edited_content,  # Use edited content
                'timestamp': datetime.utcnow().isoformat(),
                'model_deployment_name': None,
                'metadata': new_metadata
            }
            cosmos_messages_container.upsert_item(new_user_message)
            
            # Build chat request parameters from original message metadata
            # Keep all original settings (model, reasoning, doc search, etc.)
            chat_request = {
                'message': edited_content,  # Use edited content
                'conversation_id': conversation_id,
                'model_deployment': original_metadata.get('model_selection', {}).get('selected_model'),
                'reasoning_effort': original_metadata.get('reasoning_effort'),
                'hybrid_search': original_metadata.get('document_search', {}).get('enabled', False),
                'selected_document_id': original_metadata.get('document_search', {}).get('document_id'),
                'doc_scope': original_metadata.get('document_search', {}).get('scope'),
                'top_n': original_metadata.get('document_search', {}).get('top_n'),
                'classifications': original_metadata.get('document_search', {}).get('classifications'),
                'image_generation': original_metadata.get('image_generation', {}).get('enabled', False),
                'active_group_id': original_metadata.get('chat_context', {}).get('group_id'),
                'active_public_workspace_id': original_metadata.get('chat_context', {}).get('public_workspace_id'),
                'chat_type': original_metadata.get('chat_context', {}).get('type', 'user'),
                'edited_user_message_id': new_user_message_id,  # Pass this to skip user message creation
                'retry_thread_id': thread_id,  # Pass thread_id to maintain same thread
                'retry_thread_attempt': new_attempt  # Pass attempt number
            }
            
            # Include agent_info from original metadata if present (for agent-based edits)
            if original_metadata.get('agent_selection'):
                agent_selection = original_metadata.get('agent_selection')
                chat_request['agent_info'] = {
                    'name': agent_selection.get('selected_agent'),
                    'display_name': agent_selection.get('agent_display_name'),
                    'id': agent_selection.get('agent_id'),
                    'is_global': agent_selection.get('is_global', False),
                    'is_group': agent_selection.get('is_group', False),
                    'group_id': agent_selection.get('group_id'),
                    'group_name': agent_selection.get('group_name')
                }
                print(f"🤖 Edit - Using agent: {chat_request['agent_info'].get('display_name')} ({chat_request['agent_info'].get('name')})")
            
            print(f"🔍 Edit - Chat request params: edited_user_message_id={new_user_message_id}, retry_thread_id={thread_id}, retry_thread_attempt={new_attempt}")
            
            # Return success with chat_request for frontend to call chat API
            return jsonify({
                'success': True,
                'message': 'Edit initiated',
                'thread_id': thread_id,
                'new_attempt': new_attempt,
                'user_message_id': new_user_message_id,
                'edited': True,
                'chat_request': chat_request
            }), 200
            
        except Exception as e:
            print(f"Error editing message: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to edit message'}), 500

    @app.route('/api/message/<message_id>/switch-attempt', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def switch_attempt(message_id):
        """
        Switch between thread attempts by setting active_thread flags.
        Cycles through attempts based on direction (prev/next).
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json() or {}
            direction = data.get('direction', 'next')  # 'prev' or 'next'
            
            # Find the current message
            query = "SELECT * FROM c WHERE c.id = @message_id"
            params = [{"name": "@message_id", "value": message_id}]
            message_results = list(cosmos_messages_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            
            if not message_results:
                return jsonify({'error': 'Message not found'}), 404
            
            current_msg = message_results[0]
            conversation_id = current_msg.get('conversation_id')
            
            # Verify ownership
            message_user_id = current_msg.get('metadata', {}).get('user_info', {}).get('user_id')
            if not message_user_id:
                try:
                    conversation = cosmos_conversations_container.read_item(
                        item=conversation_id,
                        partition_key=conversation_id
                    )
                    if conversation.get('user_id') != user_id:
                        return jsonify({'error': 'You can only switch attempts in your own conversations'}), 403
                except:
                    return jsonify({'error': 'Conversation not found'}), 404
            elif message_user_id != user_id:
                return jsonify({'error': 'You can only switch attempts in your own conversations'}), 403
            
            # Get thread info
            thread_id = current_msg.get('metadata', {}).get('thread_info', {}).get('thread_id')
            current_attempt = current_msg.get('metadata', {}).get('thread_info', {}).get('thread_attempt', 0)
            
            if not thread_id:
                return jsonify({'error': 'Message has no thread_id'}), 400
            
            # Get all attempts for this thread_id, ordered by thread_attempt
            attempts_query = f"""
                SELECT DISTINCT c.metadata.thread_info.thread_attempt 
                FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
                AND c.role = 'user'
                ORDER BY c.metadata.thread_info.thread_attempt ASC
            """
            attempts_results = list(cosmos_messages_container.query_items(
                query=attempts_query,
                partition_key=conversation_id
            ))
            
            available_attempts = sorted([r.get('thread_attempt', 0) for r in attempts_results])
            
            if not available_attempts:
                return jsonify({'error': 'No attempts found'}), 404
            
            # Find current index and determine target attempt
            try:
                current_index = available_attempts.index(current_attempt)
            except ValueError:
                current_index = 0
            
            if direction == 'prev':
                target_index = (current_index - 1) % len(available_attempts)
            else:  # 'next'
                target_index = (current_index + 1) % len(available_attempts)
            
            target_attempt = available_attempts[target_index]
            
            # Deactivate all attempts for this thread
            deactivate_query = f"""
                SELECT * FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
            """
            all_thread_messages = list(cosmos_messages_container.query_items(
                query=deactivate_query,
                partition_key=conversation_id
            ))
            
            # Update active_thread flags
            for msg in all_thread_messages:
                if 'metadata' not in msg:
                    msg['metadata'] = {}
                if 'thread_info' not in msg['metadata']:
                    msg['metadata']['thread_info'] = {}
                
                msg_attempt = msg['metadata']['thread_info'].get('thread_attempt', 0)
                msg['metadata']['thread_info']['active_thread'] = (msg_attempt == target_attempt)
                cosmos_messages_container.upsert_item(msg)
            
            return jsonify({
                'success': True,
                'target_attempt': target_attempt,
                'available_attempts': available_attempts
            }), 200
            
        except Exception as e:
            print(f"Error switching attempt: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to switch attempt'}), 500
