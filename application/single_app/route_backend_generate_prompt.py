# route_backend_generate_prompt.py

import json
from config import *
from functions_authentication import *
from functions_settings import *
from functions_debug import debug_print
from functions_appinsights import log_event
from swagger_wrapper import swagger_route, get_auth_security
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

# Cognitive services scope for managed identity
cognitive_services_scope = "https://cognitiveservices.azure.com/.default"

# Maximum number of messages to include in prompt generation analysis
MAX_MESSAGES_FOR_ANALYSIS = 50

# Meta-prompt used to instruct the AI to generate a reusable prompt
GENERATE_PROMPT_META_PROMPT = """You are an expert prompt engineer. Analyze the following conversation between a user and an AI assistant.

Your task is to extract the core intent, communication patterns, and techniques used in the conversation, then generate a clear, reusable prompt that could guide an AI assistant to reproduce similar high-quality interactions.

The generated prompt should:
1. Capture the user's primary goals and desired output style
2. Include any specific formatting, tone, or structural requirements evident in the conversation
3. Be general enough to be reusable across similar tasks, not tied to specific data from this conversation
4. Be written as instructions to an AI assistant (second person)

Return your response as valid JSON with exactly two fields:
- "name": A short, descriptive title for the prompt (max 100 characters)
- "content": The full reusable prompt text in markdown format

Example response format:
{"name": "Technical Code Review Assistant", "content": "You are a code review assistant. When reviewing code, please..."}

IMPORTANT: Return ONLY the JSON object, no additional text or markdown formatting around it.

Here is the conversation to analyze:
"""


def _initialize_gpt_client(settings):
    """Initialize the Azure OpenAI GPT client using current settings.
    
    Returns:
        tuple: (gpt_client, gpt_model) or raises ValueError on failure
    """
    gpt_model = ""
    gpt_client = None
    enable_gpt_apim = settings.get('enable_gpt_apim', False)

    if enable_gpt_apim:
        raw = settings.get('azure_apim_gpt_deployment', '')
        if not raw:
            raise ValueError("APIM GPT deployment name not configured.")

        apim_models = [m.strip() for m in raw.split(',') if m.strip()]
        if not apim_models:
            raise ValueError("No valid APIM GPT deployment names found.")

        # Use the first available model for prompt generation
        gpt_model = apim_models[0]

        gpt_client = AzureOpenAI(
            api_version=settings.get('azure_apim_gpt_api_version'),
            azure_endpoint=settings.get('azure_apim_gpt_endpoint'),
            api_key=settings.get('azure_apim_gpt_subscription_key')
        )
    else:
        auth_type = settings.get('azure_openai_gpt_authentication_type')
        endpoint = settings.get('azure_openai_gpt_endpoint')
        api_version = settings.get('azure_openai_gpt_api_version')
        gpt_model_obj = settings.get('gpt_model', {})

        if gpt_model_obj and gpt_model_obj.get('selected'):
            selected_gpt_model = gpt_model_obj['selected'][0]
            gpt_model = selected_gpt_model['deploymentName']
        else:
            raise ValueError("No GPT model selected or configured.")

        if auth_type == 'managed_identity':
            token_provider = get_bearer_token_provider(DefaultAzureCredential(), cognitive_services_scope)
            gpt_client = AzureOpenAI(
                api_version=api_version,
                azure_endpoint=endpoint,
                azure_ad_token_provider=token_provider
            )
        else:
            api_key = settings.get('azure_openai_gpt_key')
            if not api_key:
                raise ValueError("Azure OpenAI API Key not configured.")
            gpt_client = AzureOpenAI(
                api_version=api_version,
                azure_endpoint=endpoint,
                api_key=api_key
            )

    if not gpt_client or not gpt_model:
        raise ValueError("GPT Client or Model could not be initialized.")

    return gpt_client, gpt_model


def _fetch_conversation_messages(conversation_id, user_id):
    """Fetch active thread messages for a conversation owned by the user.
    
    Returns:
        list: Filtered list of message dicts with role and content
    """
    # Verify the conversation belongs to this user
    try:
        conversation = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id
        )
    except Exception:
        return None

    if conversation.get('user_id') != user_id:
        return None

    # Query messages ordered by timestamp
    message_query = f"""
        SELECT * FROM c 
        WHERE c.conversation_id = '{conversation_id}' 
        ORDER BY c.timestamp ASC
    """

    all_items = list(cosmos_messages_container.query_items(
        query=message_query,
        partition_key=conversation_id
    ))

    # Filter for active thread messages only (same pattern as route_backend_conversations.py)
    filtered = []
    for item in all_items:
        role = item.get('role', '')
        # Skip non-text message types
        if role in ('image', 'image_chunk', 'file', 'safety', 'system'):
            continue

        thread_info = item.get('metadata', {}).get('thread_info', {})
        active = thread_info.get('active_thread')

        # Include if active_thread is True, None, or not defined
        if active is True or active is None or 'active_thread' not in thread_info:
            filtered.append({
                'role': role,
                'content': item.get('content', '')
            })

    return filtered


def register_route_backend_generate_prompt(app):

    @app.route('/api/conversations/<conversation_id>/generate-prompt', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def generate_prompt_from_conversation(conversation_id):
        """Analyze a conversation and generate a reusable prompt using AI."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        if not conversation_id:
            return jsonify({'error': 'No conversation_id provided'}), 400

        try:
            # Fetch conversation messages
            messages = _fetch_conversation_messages(conversation_id, user_id)
            if messages is None:
                return jsonify({'error': 'Conversation not found or access denied'}), 404

            if not messages:
                return jsonify({'error': 'Conversation has no messages to analyze'}), 400

            # Truncate to the last N messages to stay within token limits
            if len(messages) > MAX_MESSAGES_FOR_ANALYSIS:
                messages = messages[-MAX_MESSAGES_FOR_ANALYSIS:]

            # Build the conversation text for analysis
            conversation_text = "\n".join(
                f"{msg['role'].upper()}: {msg['content']}" for msg in messages
            )

            # Initialize GPT client
            settings = get_settings()
            gpt_client, gpt_model = _initialize_gpt_client(settings)

            # Build the full meta-prompt
            full_prompt = GENERATE_PROMPT_META_PROMPT + conversation_text

            # Call Azure OpenAI (non-streaming)
            log_event("Generate prompt from conversation started", level=logging.INFO)

            # Build API parameters - o-series and gpt-5 models require max_completion_tokens instead of max_tokens
            gpt_model_lower = gpt_model.lower()
            uses_completion_tokens = ('o1' in gpt_model_lower or 'o3' in gpt_model_lower or 'gpt-5' in gpt_model_lower)

            api_params = {
                "model": gpt_model,
                "messages": [{"role": "system", "content": full_prompt}],
                "temperature": 0.7,
            }

            if uses_completion_tokens:
                api_params["max_completion_tokens"] = 1500
            else:
                api_params["max_tokens"] = 1500

            debug_print(f"[GeneratePrompt] Using model: {gpt_model}, parameter: {'max_completion_tokens' if uses_completion_tokens else 'max_tokens'}")

            response = gpt_client.chat.completions.create(**api_params)

            ai_response = response.choices[0].message.content.strip()
            debug_print(f"[GeneratePrompt] Raw AI response: {ai_response[:200]}...")

            # Parse JSON response from AI
            try:
                # Handle possible markdown code block wrapping
                clean_response = ai_response
                if clean_response.startswith("```"):
                    # Remove markdown code fences
                    lines = clean_response.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    clean_response = "\n".join(lines)

                result = json.loads(clean_response)
                name = result.get('name', 'Generated Prompt').strip()[:100]
                content = result.get('content', '').strip()

                if not content:
                    raise ValueError("AI returned empty content")

            except (json.JSONDecodeError, ValueError) as parse_err:
                debug_print(f"[GeneratePrompt] JSON parse failed: {parse_err}, using raw response")
                # Fallback: use raw AI response as content with a default name
                name = "Generated Prompt"
                content = ai_response

            log_event("Generate prompt from conversation completed", level=logging.INFO)

            return jsonify({
                'success': True,
                'name': name,
                'content': content
            }), 200

        except ValueError as ve:
            log_event(f"Generate prompt configuration error: {ve}", level=logging.ERROR)
            return jsonify({'error': f'Configuration error: {str(ve)}'}), 500
        except Exception as e:
            log_event(f"Error generating prompt from conversation: {e}", level=logging.ERROR)
            debug_print(f"[GeneratePrompt] Error: {e}")
            return jsonify({'error': 'An unexpected error occurred while generating the prompt'}), 500
