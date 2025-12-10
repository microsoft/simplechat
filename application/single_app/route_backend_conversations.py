# route_backend_conversations.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_conversation_metadata import get_conversation_metadata
from flask import Response, request
from functions_debug import debug_print
from swagger_wrapper import swagger_route, get_auth_security

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
            # Query all messages and chunks in cosmos_messages_container
            message_query = f"SELECT * FROM c WHERE c.conversation_id = '{conversation_id}' ORDER BY c.timestamp ASC"
            all_items = list(cosmos_messages_container.query_items(
                query=message_query,
                partition_key=conversation_id
            ))
            
            debug_print(f"Query returned {len(all_items)} total items")
            for i, item in enumerate(all_items):
                debug_print(f"Item {i}: id={item.get('id')}, role={item.get('role')}")
            
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
            query_parts = [f"c.user_id = '{user_id}'"]
            
            if date_from:
                query_parts.append(f"c.last_updated >= '{date_from}'")
            if date_to:
                query_parts.append(f"c.last_updated <= '{date_to}T23:59:59'")
            
            conversation_query = f"SELECT * FROM c WHERE {' AND '.join(query_parts)}"
            conversations = list(cosmos_conversations_container.query_items(
                query=conversation_query,
                enable_cross_partition_query=True
            ))
            
            # Filter by chat types if specified
            if chat_types:
                conversations = [c for c in conversations if c.get('chat_type') in chat_types]
            
            # Filter by classifications if specified
            if classifications:
                conversations = [c for c in conversations if any(
                    cls in (c.get('classification', []) or []) for cls in classifications
                )]
            
            # Search messages in each conversation
            results = []
            search_lower = search_term.lower()
            
            for conversation in conversations:
                conv_id = conversation['id']
                
                # Query messages for this conversation
                message_query = f"SELECT * FROM m WHERE m.conversation_id = '{conv_id}' AND CONTAINS(LOWER(m.content), '{search_lower}')"
                matching_messages = list(cosmos_messages_container.query_items(
                    query=message_query,
                    partition_key=conv_id
                ))
                
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