# route_external_chat.py

from config import *
from functions_authentication import *
from functions_chat import *
from functions_settings import *
from functions_appinsights import log_event

def register_route_external_chat(app):
    @app.route('/external/chat', methods=['POST'])
    @login_required
    #@accesstoken_required_greg
    #@enabled_required("enable_chat")
    def external_send_message():
        """
        POST /external/chat
        Expects JSON: { 
            "message": "string",
            "conversation_id": "string",
            "user_id": "string" 
        }
        Sends a chat message to SimpleChat and returns the response.
        """
        try:
            data = request.get_json()
            if not data:
                return jsonify({"error": "Request must be JSON"}), 400
            
            user_message = data.get('message', '')
            conversation_id = data.get('conversation_id')
            user_id = data.get('user_id')
            
            if not user_message:
                return jsonify({"error": "Missing 'message' field"}), 400
            
            if not user_id:
                return jsonify({"error": "Missing 'user_id' field"}), 400
            
            # Optional parameters with defaults
            chat_type = data.get('chat_type', 'user')
            hybrid_search_enabled = data.get('hybrid_search', False)
            bing_search_enabled = data.get('bing_search', False)
            image_gen_enabled = data.get('image_generation', False)
            selected_document_id = data.get('selected_document_id')
            document_scope = data.get('doc_scope', 'user')
            active_group_id = data.get('active_group_id')
            frontend_gpt_model = data.get('model_deployment')
            
            # Validate chat_type
            if chat_type not in ('user', 'group'):
                chat_type = 'user'
                
            # Convert string booleans if needed
            if isinstance(hybrid_search_enabled, str):
                hybrid_search_enabled = hybrid_search_enabled.lower() == 'true'
            if isinstance(bing_search_enabled, str):
                bing_search_enabled = bing_search_enabled.lower() == 'true'
            if isinstance(image_gen_enabled, str):
                image_gen_enabled = image_gen_enabled.lower() == 'true'
            
            # Log the external chat request
            log_event("External chat message received", extra={
                "user_id": user_id,
                "conversation_id": conversation_id,
                "chat_type": chat_type,
                "message_length": len(user_message)
            })
            
            # For simplicity, create a basic chat response
            # In a real implementation, this would integrate with the full chat pipeline
            settings = get_settings()
            
            # Create or get conversation
            if not conversation_id:
                # Generate new conversation ID
                import uuid
                conversation_id = str(uuid.uuid4())
                
                # Create conversation document
                from datetime import datetime
                conversation_doc = {
                    'id': conversation_id,
                    'user_id': user_id,
                    'type': 'conversation',
                    'title': user_message[:50] + '...' if len(user_message) > 50 else user_message,
                    'created_date': datetime.utcnow().isoformat(),
                    'modified_date': datetime.utcnow().isoformat(),
                    'messages': []
                }
                
                try:
                    cosmos_conversations_container.create_item(conversation_doc)
                except Exception as e:
                    print(f"Error creating conversation: {e}")
                    # Continue anyway, the conversation might already exist
            
            # For now, return a simple response
            # In a full implementation, this would call the complete chat pipeline
            assistant_response = f"I received your message: '{user_message}'. This is a simplified external API response."
            
            # Store the message and response
            try:
                from datetime import datetime
                import uuid
                
                # Store user message
                user_msg_doc = {
                    'id': str(uuid.uuid4()),
                    'conversation_id': conversation_id,
                    'user_id': user_id,
                    'type': 'user',
                    'content': user_message,
                    'timestamp': datetime.utcnow().isoformat(),
                    'metadata': {
                        'chat_type': chat_type,
                        'hybrid_search': hybrid_search_enabled,
                        'bing_search': bing_search_enabled,
                        'image_generation': image_gen_enabled,
                        'document_scope': document_scope
                    }
                }
                
                # Store assistant response
                assistant_msg_doc = {
                    'id': str(uuid.uuid4()),
                    'conversation_id': conversation_id,
                    'user_id': user_id,
                    'type': 'assistant',
                    'content': assistant_response,
                    'timestamp': datetime.utcnow().isoformat(),
                    'metadata': {}
                }
                
                cosmos_messages_container.create_item(user_msg_doc)
                cosmos_messages_container.create_item(assistant_msg_doc)
                
            except Exception as e:
                print(f"Error storing messages: {e}")
                # Continue to return response even if storage fails
            
            return jsonify({
                "conversation_id": conversation_id,
                "response": assistant_response,
                "user_message": user_message,
                "timestamp": datetime.utcnow().isoformat(),
                "status": "success"
            }), 200
            
        except Exception as e:
            print(f"Error in external_send_message: {e}")
            return jsonify({
                "error": f"An error occurred while processing your message: {str(e)}"
            }), 500