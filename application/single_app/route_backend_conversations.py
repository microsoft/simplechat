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
            'strict': False
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
                "strict": conversation_item.get('strict', False)
            }), 200
            
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404
        except Exception as e:
            print(f"Error retrieving conversation metadata: {e}")
            return jsonify({'error': 'Failed to retrieve conversation metadata'}), 500