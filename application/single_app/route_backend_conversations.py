# route_backend_conversations.py

from config import *
from functions_authentication import *
from functions_settings import *

def register_route_backend_conversations(app):

    @app.route('/api/get_messages', methods=['GET'])
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
            # Then query the messages in cosmos_messages_container
            message_query = f"SELECT * FROM c WHERE c.conversation_id = '{conversation_id}' ORDER BY c.timestamp ASC"
            messages = list(cosmos_messages_container.query_items(
                query=message_query,
                partition_key=conversation_id
            ))
            return jsonify({'messages': messages})
        except CosmosResourceNotFoundError:
            return jsonify({'messages': []})
        except Exception:
            return jsonify({'error': 'Conversation not found'}), 404
        
    @app.route('/api/get_conversations', methods=['GET'])
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
            'title': 'New Conversation'
        }
        cosmos_conversations_container.upsert_item(conversation_item)

        return jsonify({
            'conversation_id': conversation_id,
            'title': 'New Conversation'
        }), 200
    
    @app.route('/api/conversations/<conversation_id>', methods=['PUT'])
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