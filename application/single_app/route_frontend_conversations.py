# route_frontend_conversations.py

from config import *
from functions_authentication import *

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
        messages = list(cosmos_messages_container.query_items(
            query=msg_query,
            partition_key=conversation_id
        ))

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