# route_backend_chats.py
from semantic_kernel import Kernel
from semantic_kernel.agents.runtime import InProcessRuntime
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.connectors.ai.prompt_execution_settings import PromptExecutionSettings
from semantic_kernel.connectors.ai.chat_completion_client_base import ChatCompletionClientBase
from semantic_kernel_fact_memory_store import FactMemoryStore
from semantic_kernel_loader import initialize_semantic_kernel
from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger
import builtins
import asyncio, types
import json
from config import *
from flask import g
from functions_authentication import *
from functions_search import *
from functions_settings import *
from functions_agents import get_agent_id_by_name
from functions_group import find_group_by_id
from functions_chat import *
from functions_conversation_metadata import collect_conversation_metadata, update_conversation_with_metadata
from functions_debug import debug_print
from flask import current_app


def get_kernel():
    return getattr(g, 'kernel', None) or getattr(builtins, 'kernel', None)

def get_kernel_agents():
    g_agents = getattr(g, 'kernel_agents', None)
    builtins_agents = getattr(builtins, 'kernel_agents', None)
    log_event(f"[SKChat] get_kernel_agents - g.kernel_agents: {type(g_agents)} ({len(g_agents) if g_agents else 0} agents), builtins.kernel_agents: {type(builtins_agents)} ({len(builtins_agents) if builtins_agents else 0} agents)", level=logging.INFO)
    return g_agents or builtins_agents

def register_route_backend_chats(app):
    @app.route('/api/chat', methods=['POST'])
    @login_required
    @user_required
    def chat_api():
        try:
            settings = get_settings()
            data = request.get_json()
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({
                    'error': 'User not authenticated'
                }), 401

            # Extract from request
            user_message = data.get('message', '')
            conversation_id = data.get('conversation_id')
            hybrid_search_enabled = data.get('hybrid_search')
            selected_document_id = data.get('selected_document_id')
            image_gen_enabled = data.get('image_generation')
            document_scope = data.get('doc_scope')
            active_group_id = data.get('active_group_id')
            frontend_gpt_model = data.get('model_deployment')
            top_n_results = data.get('top_n')  # Extract top_n parameter from request
            classifications_to_send = data.get('classifications')  # Extract classifications parameter from request
            chat_type = data.get('chat_type', 'user')  # 'user' or 'group', default to 'user'
            
            # Store conversation_id in Flask context for plugin logger access
            g.conversation_id = conversation_id
            
            # Clear plugin invocations at start of message processing to ensure
            # each message only shows citations for tools executed during that specific interaction
            from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger
            plugin_logger = get_plugin_logger()
            plugin_logger.clear_invocations_for_conversation(user_id, conversation_id)
            
            # Validate chat_type
            if chat_type not in ('user', 'group'):
                chat_type = 'user'
                
            search_query = user_message # <--- ADD THIS LINE (Initialize search_query)
            hybrid_citations_list = [] # <--- ADD THIS LINE (Initialize hybrid list)
            agent_citations_list = [] # <--- ADD THIS LINE (Initialize agent citations list)
            system_messages_for_augmentation = [] # Collect system messages from search
            search_results = []
            selected_agent = None  # Initialize selected_agent early to prevent NameError
            # --- Configuration ---
            # History / Summarization Settings
            raw_conversation_history_limit = settings.get('conversation_history_limit', 6)
            # Round up to nearest even number
            conversation_history_limit = math.ceil(raw_conversation_history_limit)
            if conversation_history_limit % 2 != 0:
                conversation_history_limit += 1
            enable_summarize_content_history_beyond_conversation_history_limit = settings.get('enable_summarize_content_history_beyond_conversation_history_limit', True) # Use a dedicated setting if possible
            enable_summarize_content_history_for_search = settings.get('enable_summarize_content_history_for_search', False) # Use a dedicated setting if possible
            number_of_historical_messages_to_summarize = settings.get('number_of_historical_messages_to_summarize', 10) # Number of messages to summarize for search context

            max_file_content_length = 50000 # 50KB

            # Convert toggles from string -> bool if needed
            if isinstance(hybrid_search_enabled, str):
                hybrid_search_enabled = hybrid_search_enabled.lower() == 'true'
            if isinstance(image_gen_enabled, str):
                image_gen_enabled = image_gen_enabled.lower() == 'true'

            # GPT & Image generation APIM or direct
            gpt_model = ""
            gpt_client = None
            enable_gpt_apim = settings.get('enable_gpt_apim', False)
            enable_image_gen_apim = settings.get('enable_image_gen_apim', False)

            try:
                if enable_gpt_apim:
                    # read raw comma-delimited deployments
                    raw = settings.get('azure_apim_gpt_deployment', '')
                    if not raw:
                        raise ValueError("APIM GPT deployment name not configured.")

                    # split, strip, and filter out empty entries
                    apim_models = [m.strip() for m in raw.split(',') if m.strip()]
                    if not apim_models:
                        raise ValueError("No valid APIM GPT deployment names found.")

                    # if frontend specified one, use it (must be in the configured list)
                    if frontend_gpt_model:
                        if frontend_gpt_model not in apim_models:
                            raise ValueError(
                                f"Requested model '{frontend_gpt_model}' is not configured for APIM."
                            )
                        gpt_model = frontend_gpt_model

                    # otherwise if there's exactly one deployment, default to it
                    elif len(apim_models) == 1:
                        gpt_model = apim_models[0]

                    # otherwise you must pass model_deployment in the request
                    else:
                        raise ValueError(
                            "Multiple APIM GPT deployments configured; please include "
                            "'model_deployment' in your request."
                        )

                    # initialize the APIM client
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
                        # Fallback or raise error if no model selected/configured
                        raise ValueError("No GPT model selected or configured.")

                    if frontend_gpt_model:
                        gpt_model = frontend_gpt_model
                    elif gpt_model_obj and gpt_model_obj.get('selected'):
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
                    else: # Default to API Key
                        api_key = settings.get('azure_openai_gpt_key')
                        if not api_key: raise ValueError("Azure OpenAI API Key not configured.")
                        gpt_client = AzureOpenAI(
                            api_version=api_version,
                            azure_endpoint=endpoint,
                            api_key=api_key
                        )

                if not gpt_client or not gpt_model:
                    raise ValueError("GPT Client or Model could not be initialized.")

            except Exception as e:
                print(f"Error initializing GPT client/model: {e}")
                # Handle error appropriately - maybe return 500 or default behavior
                return jsonify({'error': f'Failed to initialize AI model: {str(e)}'}), 500

            # ---------------------------------------------------------------------
            # 1) Load or create conversation
            # ---------------------------------------------------------------------
            if not conversation_id:
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
            else:
                try:
                    conversation_item = cosmos_conversations_container.read_item(item=conversation_id, partition_key=conversation_id)
                except CosmosResourceNotFoundError:
                    # If conversation ID is provided but not found, create a new one with that ID
                    # Or decide if you want to return an error instead
                    conversation_item = {
                        'id': conversation_id, # Keep the provided ID if needed for linking
                        'user_id': user_id,
                        'last_updated': datetime.utcnow().isoformat(),
                        'title': 'New Conversation', # Or maybe fetch title differently?
                        'context': [],
                        'tags': [],
                        'strict': False
                    }
                    # Optionally log that a conversation was expected but not found
                    print(f"Warning: Conversation ID {conversation_id} not found, creating new.")
                    cosmos_conversations_container.upsert_item(conversation_item)
                except Exception as e:
                    print(f"Error reading conversation {conversation_id}: {e}")
                    return jsonify({'error': f'Error reading conversation: {str(e)}'}), 500

            # Determine the actual chat context based on existing conversation or document usage
            # For existing conversations, use the chat_type from conversation metadata
            # For new conversations, it will be determined during metadata collection
            actual_chat_type = 'personal'  # Default
            
            if conversation_item.get('chat_type'):
                # Use existing chat_type from conversation metadata
                actual_chat_type = conversation_item['chat_type']
                print(f"Using existing chat_type from conversation: {actual_chat_type}")
            elif conversation_item.get('context'):
                # Fallback: determine from existing context
                primary_context = next((ctx for ctx in conversation_item['context'] if ctx.get('type') == 'primary'), None)
                if primary_context:
                    if primary_context.get('scope') == 'group':
                        actual_chat_type = 'group-single-user'  # Default to single-user for groups
                    elif primary_context.get('scope') == 'public':
                        actual_chat_type = 'public'
                    elif primary_context.get('scope') == 'personal':
                        actual_chat_type = 'personal'
                    print(f"Determined chat_type from existing primary context: {actual_chat_type}")
                else:
                    # No primary context exists - model-only conversation
                    actual_chat_type = None  # This will result in no badges
                    print(f"No primary context found - model-only conversation")
            else:
                # New conversation - will be determined by document usage during metadata collection
                # For now, use the legacy logic as fallback
                if document_scope == 'group' or (active_group_id and chat_type == 'group'):
                    actual_chat_type = 'group'
                elif document_scope == 'public':
                    actual_chat_type = 'public'
                print(f"New conversation - using legacy logic: {actual_chat_type}")

            # ---------------------------------------------------------------------
            # 2) Append the user message to conversation immediately
            # ---------------------------------------------------------------------
            user_message_id = f"{conversation_id}_user_{int(time.time())}_{random.randint(1000,9999)}"
            
            # Collect comprehensive metadata for user message
            user_metadata = {}
            
            # Get current user information
            current_user = get_current_user_info()
            if current_user:
                user_metadata['user_info'] = {
                    'user_id': current_user.get('userId'),
                    'username': current_user.get('userPrincipalName'),
                    'display_name': current_user.get('displayName'),
                    'email': current_user.get('email'),
                    'timestamp': datetime.utcnow().isoformat()
                }
            
            # Button states and selections
            user_metadata['button_states'] = {
                'image_generation': image_gen_enabled,
                'document_search': hybrid_search_enabled
            }
            
            # Document search scope and selections
            if hybrid_search_enabled:
                user_metadata['workspace_search'] = {
                    'search_enabled': True,
                    'document_scope': document_scope,
                    'selected_document_id': selected_document_id,
                    'classification': classifications_to_send
                }
                
                # Get document details if specific document selected
                if selected_document_id and selected_document_id != "all":
                    try:
                        # Use the appropriate documents container based on scope
                        if document_scope == 'group':
                            cosmos_container = cosmos_group_documents_container
                        elif document_scope == 'public':
                            cosmos_container = cosmos_public_documents_container
                        else:
                            cosmos_container = cosmos_user_documents_container
                        
                        doc_query = "SELECT c.file_name, c.title, c.document_id, c.group_id FROM c WHERE c.id = @doc_id"
                        doc_params = [{"name": "@doc_id", "value": selected_document_id}]
                        doc_results = list(cosmos_container.query_items(
                            query=doc_query, parameters=doc_params, enable_cross_partition_query=True
                        ))
                        if doc_results:
                            doc_info = doc_results[0]
                            user_metadata['workspace_search']['document_name'] = doc_info.get('title') or doc_info.get('file_name')
                            user_metadata['workspace_search']['document_filename'] = doc_info.get('file_name')
                    except Exception as e:
                        print(f"Error retrieving document details: {e}")
                
                # Add scope-specific details
                if document_scope == 'group' and active_group_id:
                    try:
                        debug_print(f"Workspace search - looking up group for id: {active_group_id}")
                        group_doc = find_group_by_id(active_group_id)
                        debug_print(f"Workspace search group lookup result: {group_doc}")
                        
                        if group_doc and group_doc.get('name'):
                            group_name = group_doc.get('name')
                            user_metadata['workspace_search']['group_name'] = group_name
                            debug_print(f"Workspace search - set group_name to: {group_name}")
                        else:
                            debug_print(f"Workspace search - no group found or no name for id: {active_group_id}")
                            user_metadata['workspace_search']['group_name'] = None
                            
                    except Exception as e:
                        print(f"Error retrieving group details: {e}")
                        user_metadata['workspace_search']['group_name'] = None
                        import traceback
                        traceback.print_exc()
            else:
                user_metadata['workspace_search'] = {
                    'search_enabled': False
                }
            
            # Agent selection (if available)
            if hasattr(g, 'kernel_agents') and g.kernel_agents:
                try:
                    # Try to get selected agent info from user settings or global settings
                    selected_agent_info = None
                    if user_id:
                        try:
                            user_settings_doc = cosmos_user_settings_container.read_item(
                                item=user_id, partition_key=user_id
                            )
                            selected_agent_info = user_settings_doc.get('settings', {}).get('selected_agent')
                        except:
                            pass
                    
                    if not selected_agent_info:
                        # Fallback to global selected agent
                        selected_agent_info = settings.get('global_selected_agent')
                    
                    if selected_agent_info:
                        user_metadata['agent_selection'] = {
                            'selected_agent': selected_agent_info.get('name'),
                            'agent_display_name': selected_agent_info.get('display_name'),
                            'is_global': selected_agent_info.get('is_global', False)
                        }
                except Exception as e:
                    print(f"Error retrieving agent details: {e}")
            
            # Prompt selection (extract from message if available)
            prompt_info = data.get('prompt_info')
            if prompt_info:
                user_metadata['prompt_selection'] = {
                    'selected_prompt_index': prompt_info.get('index'),
                    'selected_prompt_text': prompt_info.get('content'),
                    'prompt_name': prompt_info.get('name'),
                    'prompt_id': prompt_info.get('id')
                }
            
            # Agent selection (from frontend if available, override settings-based selection)
            agent_info = data.get('agent_info')
            if agent_info:
                user_metadata['agent_selection'] = {
                    'selected_agent': agent_info.get('name'),
                    'agent_display_name': agent_info.get('display_name'),
                    'is_global': agent_info.get('is_global', False)
                }
            
            # Model selection information
            user_metadata['model_selection'] = {
                'selected_model': gpt_model,
                'frontend_requested_model': frontend_gpt_model
            }
            
            # Chat type and group context for this specific message
            user_metadata['chat_context'] = {
                'conversation_id': conversation_id
            }
            
            # Note: Message-level chat_type will be determined after document search is completed
            
            user_message_doc = {
                'id': user_message_id,
                'conversation_id': conversation_id,
                'role': 'user',
                'content': user_message,
                'timestamp': datetime.utcnow().isoformat(),
                'model_deployment_name': None,  # Model not used for user message
                'metadata': user_metadata, 
            }
            
            # Debug: Print the complete metadata being saved
            debug_print(f"Complete user_metadata being saved: {json.dumps(user_metadata, indent=2, default=str)}")
            debug_print(f"Final chat_context for message: {user_metadata['chat_context']}")
            debug_print(f"document_search: {hybrid_search_enabled}, has_search_results: {bool(search_results)}")
            
            # Note: Message-level chat_type will be updated after document search
            
            cosmos_messages_container.upsert_item(user_message_doc)

            # Set conversation title if it's still the default
            if conversation_item.get('title', 'New Conversation') == 'New Conversation' and user_message:
                new_title = (user_message[:30] + '...') if len(user_message) > 30 else user_message
                conversation_item['title'] = new_title

            conversation_item['last_updated'] = datetime.utcnow().isoformat()
            cosmos_conversations_container.upsert_item(conversation_item) # Update timestamp and potentially title

            # ---------------------------------------------------------------------
            # 3) Check Content Safety (but DO NOT return 403).
            #    If blocked, add a "safety" role message & skip GPT.
            # ---------------------------------------------------------------------
            blocked = False
            block_reasons = []
            triggered_categories = []
            blocklist_matches = []

            if settings.get('enable_content_safety') and "content_safety_client" in CLIENTS:
                try:
                    content_safety_client = CLIENTS["content_safety_client"]
                    request_obj = AnalyzeTextOptions(text=user_message)
                    cs_response = content_safety_client.analyze_text(request_obj)

                    max_severity = 0
                    for cat_result in cs_response.categories_analysis:
                        triggered_categories.append({
                            "category": cat_result.category,
                            "severity": cat_result.severity
                        })
                        if cat_result.severity > max_severity:
                            max_severity = cat_result.severity

                    if cs_response.blocklists_match:
                        for match in cs_response.blocklists_match:
                            blocklist_matches.append({
                                "blocklistName": match.blocklist_name,
                                "blocklistItemId": match.blocklist_item_id,
                                "blocklistItemText": match.blocklist_item_text
                            })

                    # Example: If severity >=4 or blocklist, we call it "blocked"
                    if max_severity >= 4:
                        blocked = True
                        block_reasons.append("Max severity >= 4")
                    if len(blocklist_matches) > 0:
                        blocked = True
                        block_reasons.append("Blocklist match")
                    
                    if blocked:
                        # Upsert to safety container
                        safety_item = {
                            'id': str(uuid.uuid4()),
                            'user_id': user_id,
                            'conversation_id': conversation_id,
                            'message': user_message,
                            'triggered_categories': triggered_categories,
                            'blocklist_matches': blocklist_matches,
                            'timestamp': datetime.utcnow().isoformat(),
                            'reason': "; ".join(block_reasons),
                            'metadata': {}
                        }
                        cosmos_safety_container.upsert_item(safety_item)

                        # Instead of 403, we'll add a "safety" message
                        blocked_msg_content = (
                            "Your message was blocked by Content Safety.\n\n"
                            f"**Reason**: {', '.join(block_reasons)}\n"
                            "Triggered categories:\n"
                        )
                        for cat in triggered_categories:
                            blocked_msg_content += (
                                f" - {cat['category']} (severity={cat['severity']})\n"
                            )
                        if blocklist_matches:
                            blocked_msg_content += (
                                "\nBlocklist Matches:\n" +
                                "\n".join([f" - {m['blocklistItemText']} (in {m['blocklistName']})"
                                        for m in blocklist_matches])
                            )

                        # Insert a special "role": "safety" or "blocked"
                        safety_message_id = f"{conversation_id}_safety_{int(time.time())}_{random.randint(1000,9999)}"

                        safety_doc = {
                            'id': safety_message_id,
                            'conversation_id': conversation_id,
                            'role': 'safety',
                            'content': blocked_msg_content.strip(),
                            'timestamp': datetime.utcnow().isoformat(),
                            'model_deployment_name': None,
                            'metadata': {},  # No metadata needed for safety messages
                        }
                        cosmos_messages_container.upsert_item(safety_doc)

                        # Update conversation's last_updated
                        conversation_item['last_updated'] = datetime.utcnow().isoformat()
                        cosmos_conversations_container.upsert_item(conversation_item)

                        # Return a normal 200 with a special field: blocked=True
                        return jsonify({
                            'reply': blocked_msg_content.strip(),
                            'blocked': True,
                            'triggered_categories': triggered_categories,
                            'blocklist_matches': blocklist_matches,
                            'conversation_id': conversation_id,
                            'conversation_title': conversation_item['title'],
                            'message_id': safety_message_id
                        }), 200

                except HttpResponseError as e:
                    print(f"[Content Safety Error] {e}")
                except Exception as ex:
                    print(f"[Content Safety] Unexpected error: {ex}")

            # ---------------------------------------------------------------------
            # 4) Augmentation (Search, etc.) - Run *before* final history prep
            # ---------------------------------------------------------------------
            
            # Hybrid Search
            if hybrid_search_enabled:
                
                # Optional: Summarize recent history *for search* (uses its own limit)
                if enable_summarize_content_history_for_search:
                    # Fetch last N messages for search context
                    limit_n_search = number_of_historical_messages_to_summarize * 2
                    query_search = f"SELECT TOP {limit_n_search} * FROM c WHERE c.conversation_id = @conv_id ORDER BY c.timestamp DESC"
                    params_search = [{"name": "@conv_id", "value": conversation_id}]
                    
                    
                    try:
                        last_messages_desc = list(cosmos_messages_container.query_items(
                            query=query_search, parameters=params_search, partition_key=conversation_id, enable_cross_partition_query=True
                        ))
                        last_messages_asc = list(reversed(last_messages_desc))

                        if last_messages_asc and len(last_messages_asc) >= conversation_history_limit:
                            summary_prompt_search = "Please summarize the key topics or questions from this recent conversation history in 50 words or less:\n\n"
                            message_texts_search = [f"{msg.get('role', 'user').upper()}: {msg.get('content', '')}" for msg in last_messages_asc]
                            summary_prompt_search += "\n".join(message_texts_search)

                            try:
                                # Use the already initialized gpt_client and gpt_model
                                summary_response_search = gpt_client.chat.completions.create(
                                    model=gpt_model,
                                    messages=[{"role": "system", "content": summary_prompt_search}],
                                    max_tokens=100 # Keep summary short
                                )
                                summary_for_search = summary_response_search.choices[0].message.content.strip()
                                if summary_for_search:
                                    search_query = f"Based on the recent conversation about: '{summary_for_search}', the user is now asking: {user_message}"
                            except Exception as e:
                                print(f"Error summarizing conversation for search: {e}")
                                # Proceed with original user_message as search_query
                    except Exception as e:
                        print(f"Error fetching messages for search summarization: {e}")


                # Perform the search
                try:
                    # Prepare search arguments
                    # Set default and maximum values for top_n
                    default_top_n = 12
                    max_top_n = 500  # Reasonable cap to prevent excessive resource usage
                    
                    # Process top_n_results if provided
                    if top_n_results is not None:
                        try:
                            top_n = int(top_n_results)
                            # Ensure top_n is within reasonable bounds
                            if top_n < 1:
                                top_n = default_top_n
                            elif top_n > max_top_n:
                                top_n = max_top_n
                        except (ValueError, TypeError):
                            # If conversion fails, use default
                            top_n = default_top_n
                    else:
                        top_n = default_top_n
                    
                    search_args = {
                        "query": search_query,
                        "user_id": user_id,
                        "top_n": top_n,
                        "doc_scope": document_scope,
                    }
                    
                    # Add active_group_id when document scope is 'group' or chat_type is 'group'
                    if (document_scope == 'group' or chat_type == 'group') and active_group_id:
                        search_args["active_group_id"] = active_group_id
    
                        
                    if selected_document_id:
                        search_args["document_id"] = selected_document_id
                    
                    # Log if a non-default top_n value is being used
                    if top_n != default_top_n:
                        print(f"Using custom top_n value: {top_n} (requested: {top_n_results})")
                    
                    # Public scope now automatically searches all visible public workspaces
                    search_results = hybrid_search(**search_args) # Assuming hybrid_search handles None document_id
                except Exception as e:
                    print(f"Error during hybrid search: {e}")
                    # Only treat as error if the exception is from embedding failure
                    return jsonify({
                        'error': 'There was an issue with the embedding process. Please check with an admin on embedding configuration.'
                    }), 500

                if search_results:
                    retrieved_texts = []
                    combined_documents = []
                    classifications_found = set(conversation_item.get('classification', [])) # Load existing

                    for doc in search_results:
                        # ... (your existing doc processing logic) ...
                        chunk_text = doc.get('chunk_text', '')
                        file_name = doc.get('file_name', 'Unknown')
                        version = doc.get('version', 'N/A') # Add default
                        chunk_sequence = doc.get('chunk_sequence', 0) # Add default
                        page_number = doc.get('page_number') or chunk_sequence or 1 # Ensure a fallback page
                        citation_id = doc.get('id', str(uuid.uuid4())) # Ensure ID exists
                        classification = doc.get('document_classification')
                        chunk_id = doc.get('chunk_id', str(uuid.uuid4())) # Ensure ID exists
                        score = doc.get('score', 0.0) # Add default score
                        group_id = doc.get('group_id', None) # Add default group ID

                        citation = f"(Source: {file_name}, Page: {page_number}) [#{citation_id}]"
                        retrieved_texts.append(f"{chunk_text}\n{citation}")
                        combined_documents.append({
                            "file_name": file_name, 
                            "citation_id": citation_id, 
                            "page_number": page_number,
                            "version": version, 
                            "classification": classification, 
                            "chunk_text": chunk_text,
                            "chunk_sequence": chunk_sequence,
                            "chunk_id": chunk_id,
                            "score": score,
                            "group_id": group_id,
                        })
                        if classification:
                            classifications_found.add(classification)

                    retrieved_content = "\n\n".join(retrieved_texts)
                    # Construct system prompt for search results
                    system_prompt_search = f"""You are an AI assistant. Use the following retrieved document excerpts to answer the user's question. Cite sources using the format (Source: filename, Page: page number).

                        Retrieved Excerpts:
                        {retrieved_content}

                        Based *only* on the information provided above, answer the user's query. If the answer isn't in the excerpts, say so.

                        Example
                        User: What is the policy on double dipping?
                        Assistant: The policy prohibits entities from using federal funds received through one program to apply for additional funds through another program, commonly known as 'double dipping' (Source: PolicyDocument.pdf, Page: 12)
                        """
                    # Add this to a temporary list, don't save to DB yet
                    system_messages_for_augmentation.append({
                        'role': 'system',
                        'content': system_prompt_search,
                        'documents': combined_documents # Keep track of docs used
                    })

                    # Loop through each source document/chunk used for this message
                    for source_doc in combined_documents:
                        # 4. Create a citation dictionary, selecting the desired fields
                        #    It's generally best practice *not* to include the full chunk_text
                        #    in the citation itself, as it can be large. The citation points *to* the chunk.
                        citation_data = {
                            "file_name": source_doc.get("file_name"),
                            "citation_id": source_doc.get("citation_id"), # Seems like a useful identifier
                            "page_number": source_doc.get("page_number"),
                            "chunk_id": source_doc.get("chunk_id"), # Specific chunk identifier
                            "chunk_sequence": source_doc.get("chunk_sequence"), # Order within document/group
                            "score": source_doc.get("score"), # Relevance score from search
                            "group_id": source_doc.get("group_id"), # Grouping info if used
                            "version": source_doc.get("version"), # Document version
                            "classification": source_doc.get("classification") # Document classification
                            # Add any other relevant metadata fields from source_doc here
                        }
                        # Using .get() provides None if a key is missing, preventing KeyErrors
                        hybrid_citations_list.append(citation_data)

                    # Reorder hybrid citations list in descending order based on page_number
                    hybrid_citations_list.sort(key=lambda x: x.get('page_number', 0), reverse=True)

                    # Update conversation classifications if new ones were found
                    if list(classifications_found) != conversation_item.get('classification', []):
                        conversation_item['classification'] = list(classifications_found)
                        # No need to upsert item here, will be updated later

            # Update message-level chat_type based on actual document usage for this message
            # This must happen after document search is completed so search_results is populated
            message_chat_type = None
            if hybrid_search_enabled and search_results and len(search_results) > 0:
                # Documents were actually used for this message
                if document_scope == 'group':
                    message_chat_type = 'group'
                elif document_scope == 'public':
                    message_chat_type = 'public'  
                else:
                    message_chat_type = 'personal'
            else:
                # No documents used for this message - only model knowledge
                message_chat_type = 'Model'
            
            # Update the message-level chat_type in user_metadata
            user_metadata['chat_context']['chat_type'] = message_chat_type
            debug_print(f"Set message-level chat_type to: {message_chat_type}")
            debug_print(f"hybrid_search_enabled: {hybrid_search_enabled}, search_results count: {len(search_results) if search_results else 0}")
            
            # Add context-specific information based on message chat type
            if message_chat_type == 'group' and active_group_id:
                user_metadata['chat_context']['group_id'] = active_group_id
                # We may have already fetched this in workspace_search section
                if 'workspace_search' in user_metadata and user_metadata['workspace_search'].get('group_name'):
                    user_metadata['chat_context']['group_name'] = user_metadata['workspace_search']['group_name']
                    debug_print(f"Chat context - using group_name from workspace_search: {user_metadata['workspace_search']['group_name']}")
                else:
                    try:
                        debug_print(f"Chat context - looking up group for id: {active_group_id}")
                        group_doc = find_group_by_id(active_group_id)
                        debug_print(f"Chat context group lookup result: {group_doc}")
                        
                        if group_doc and group_doc.get('name'):
                            group_title = group_doc.get('name')
                            user_metadata['chat_context']['group_name'] = group_title
                            debug_print(f"Chat context - set group_name to: {group_title}")
                        else:
                            debug_print(f"Chat context - no group found or no name for id: {active_group_id}")
                            user_metadata['chat_context']['group_name'] = None
                            
                    except Exception as e:
                        print(f"Error retrieving group name for chat context: {e}")
                        user_metadata['chat_context']['group_name'] = None
                        import traceback
                        traceback.print_exc()
            elif message_chat_type == 'public':
                # For public chat, add workspace information if available from document selection
                if 'workspace_search' in user_metadata and user_metadata['workspace_search'].get('document_name'):
                    # Use the document name as workspace context for public documents
                    user_metadata['chat_context']['workspace_context'] = f"Public Document: {user_metadata['workspace_search']['document_name']}"
                else:
                    user_metadata['chat_context']['workspace_context'] = "Public Workspace"
                debug_print(f"Set public workspace_context: {user_metadata['chat_context'].get('workspace_context')}")
            # For personal chat type or Model, no additional context needed beyond conversation_id
            
            # Update the user message document with the final metadata
            user_message_doc['metadata'] = user_metadata
            debug_print(f"Updated message metadata with chat_type: {message_chat_type}")
            
            # Update the user message in Cosmos DB with the final chat_type information
            cosmos_messages_container.upsert_item(user_message_doc)
            debug_print(f"User message re-saved to Cosmos DB with updated chat_context")

            # Image Generation
            if image_gen_enabled:
                if enable_image_gen_apim:
                    image_gen_model = settings.get('azure_apim_image_gen_deployment')
                    image_gen_client = AzureOpenAI(
                        api_version=settings.get('azure_apim_image_gen_api_version'),
                        azure_endpoint=settings.get('azure_apim_image_gen_endpoint'),
                        api_key=settings.get('azure_apim_image_gen_subscription_key')
                    )
                else:
                    if (settings.get('azure_openai_image_gen_authentication_type') == 'managed_identity'):
                        token_provider = get_bearer_token_provider(DefaultAzureCredential(), cognitive_services_scope)
                        image_gen_client = AzureOpenAI(
                            api_version=settings.get('azure_openai_image_gen_api_version'),
                            azure_endpoint=settings.get('azure_openai_image_gen_endpoint'),
                            azure_ad_token_provider=token_provider
                        )
                        image_gen_model_obj = settings.get('image_gen_model', {})

                        if image_gen_model_obj and image_gen_model_obj.get('selected'):
                            selected_image_gen_model = image_gen_model_obj['selected'][0]
                            image_gen_model = selected_image_gen_model['deploymentName']
                    else:
                        image_gen_client = AzureOpenAI(
                            api_version=settings.get('azure_openai_image_gen_api_version'),
                            azure_endpoint=settings.get('azure_openai_image_gen_endpoint'),
                            api_key=settings.get('azure_openai_image_gen_key')
                        )
                        image_gen_obj = settings.get('image_gen_model', {})
                        if image_gen_obj and image_gen_obj.get('selected'):
                            selected_image_gen_model = image_gen_obj['selected'][0]
                            image_gen_model = selected_image_gen_model['deploymentName']

                try:
                    debug_print(f"Generating image with model: {image_gen_model}")
                    debug_print(f"Using prompt: {user_message}")
                    
                    # Azure OpenAI doesn't support response_format parameter
                    # Different models return different formats automatically
                    image_response = image_gen_client.images.generate(
                        prompt=user_message,
                        n=1,
                        model=image_gen_model
                    )
                    
                    debug_print(f"Image response received: {type(image_response)}")
                    response_dict = json.loads(image_response.model_dump_json())
                    debug_print(f"Response dict: {response_dict}")
                    
                    # Extract image URL or base64 data with validation
                    if 'data' not in response_dict or not response_dict['data']:
                        raise ValueError("No image data in response")
                    
                    image_data = response_dict['data'][0]
                    debug_print(f"Image data keys: {list(image_data.keys())}")
                    
                    generated_image_url = None
                    
                    # Handle different response formats
                    if 'url' in image_data and image_data['url']:
                        # dall-e-3 format: returns URL
                        generated_image_url = image_data['url']
                        debug_print(f"Using URL format: {generated_image_url}")
                    elif 'b64_json' in image_data and image_data['b64_json']:
                        # gpt-image-1 format: returns base64 data
                        b64_data = image_data['b64_json']
                        # Create data URL for frontend
                        generated_image_url = f"data:image/png;base64,{b64_data}"
                        
                        # Redacted logging for large base64 content
                        if len(b64_data) > 100:
                            redacted_content = f"{b64_data[:50]}...{b64_data[-50:]}"
                            debug_print(f"Using base64 format, length: {len(b64_data)}")
                            debug_print(f"Base64 content (redacted): {redacted_content}")
                        else:
                            debug_print(f"Using base64 format, full content: {b64_data}")
                    else:
                        available_keys = list(image_data.keys())
                        raise ValueError(f"No URL or base64 data in image data. Available keys: {available_keys}")
                    
                    # Validate we have a valid image source
                    if not generated_image_url or generated_image_url == 'null':
                        raise ValueError("Generated image URL is null or empty")

                    image_message_id = f"{conversation_id}_image_{int(time.time())}_{random.randint(1000,9999)}"
                    
                    # Check if image data is too large for a single Cosmos document (2MB limit)
                    # Account for JSON overhead by using 1.5MB as the safe limit for base64 content
                    max_content_size = 1500000  # 1.5MB in bytes
                    
                    if len(generated_image_url) > max_content_size:
                        debug_print(f"Large image detected ({len(generated_image_url)} bytes), splitting across multiple documents")
                        
                        # Split the data URL into manageable chunks
                        if generated_image_url.startswith('data:image/png;base64,'):
                            # Extract just the base64 part for splitting
                            data_url_prefix = 'data:image/png;base64,'
                            base64_content = generated_image_url[len(data_url_prefix):]
                            debug_print(f"Extracted base64 content length: {len(base64_content)} bytes")
                        else:
                            # For regular URLs, store as-is (shouldn't happen with large content)
                            data_url_prefix = ''
                            base64_content = generated_image_url
                        
                        # Calculate chunk size and number of chunks
                        chunk_size = max_content_size - len(data_url_prefix) - 200  # More room for JSON overhead
                        chunks = [base64_content[i:i+chunk_size] for i in range(0, len(base64_content), chunk_size)]
                        total_chunks = len(chunks)
                        
                        debug_print(f"Splitting into {total_chunks} chunks of max {chunk_size} bytes each")
                        for i, chunk in enumerate(chunks):
                            debug_print(f"Chunk {i} length: {len(chunk)} bytes")
                        
                        # Verify we can reassemble before storing
                        reassembled_test = data_url_prefix + ''.join(chunks)
                        if len(reassembled_test) == len(generated_image_url):
                            debug_print(f"✅ Chunking verification passed - can reassemble to original size")
                        else:
                            debug_print(f"❌ Chunking verification failed - {len(reassembled_test)} vs {len(generated_image_url)}")
                        
                        
                        # Create main image document with metadata
                        main_image_doc = {
                            'id': image_message_id,
                            'conversation_id': conversation_id,
                            'role': 'image',
                            'content': f"{data_url_prefix}{chunks[0]}",  # First chunk with data URL prefix
                            'prompt': user_message,
                            'created_at': datetime.utcnow().isoformat(),
                            'timestamp': datetime.utcnow().isoformat(),
                            'model_deployment_name': image_gen_model,
                            'metadata': {
                                'is_chunked': True,
                                'total_chunks': total_chunks,
                                'chunk_index': 0,
                                'original_size': len(generated_image_url)
                            }
                        }
                        
                        # Create additional chunk documents
                        chunk_docs = []
                        for i in range(1, total_chunks):
                            chunk_doc = {
                                'id': f"{image_message_id}_chunk_{i}",
                                'conversation_id': conversation_id,
                                'role': 'image_chunk',
                                'content': chunks[i],
                                'parent_message_id': image_message_id,
                                'created_at': datetime.utcnow().isoformat(),
                                'timestamp': datetime.utcnow().isoformat(),
                                'metadata': {
                                    'is_chunk': True,
                                    'chunk_index': i,
                                    'total_chunks': total_chunks,
                                    'parent_message_id': image_message_id
                                }
                            }
                            chunk_docs.append(chunk_doc)
                        
                        # Store all documents
                        debug_print(f"Storing main document with content length: {len(main_image_doc['content'])} bytes")
                        cosmos_messages_container.upsert_item(main_image_doc)
                        
                        for i, chunk_doc in enumerate(chunk_docs):
                            debug_print(f"Storing chunk {i+1} with content length: {len(chunk_doc['content'])} bytes")
                            cosmos_messages_container.upsert_item(chunk_doc)
                            
                        debug_print(f"Successfully stored image in {total_chunks} documents")
                        debug_print(f"Main doc content starts with: {main_image_doc['content'][:50]}...")
                        debug_print(f"Main doc content ends with: ...{main_image_doc['content'][-50:]}")
                        
                        # Return the full image URL for immediate display
                        response_image_url = generated_image_url
                        
                    else:
                        # Small image - store normally in single document
                        debug_print(f"Small image ({len(generated_image_url)} bytes), storing in single document")
                        
                        image_doc = {
                            'id': image_message_id,
                            'conversation_id': conversation_id,
                            'role': 'image',
                            'content': generated_image_url,
                            'prompt': user_message,
                            'created_at': datetime.utcnow().isoformat(),
                            'timestamp': datetime.utcnow().isoformat(),
                            'model_deployment_name': image_gen_model,
                            'metadata': {
                                'is_chunked': False,
                                'original_size': len(generated_image_url)
                            }
                        }
                        cosmos_messages_container.upsert_item(image_doc)
                        response_image_url = generated_image_url

                    conversation_item['last_updated'] = datetime.utcnow().isoformat()
                    cosmos_conversations_container.upsert_item(conversation_item)

                    return jsonify({
                        'reply': "Image loading...",
                        'image_url': response_image_url,
                        'conversation_id': conversation_id,
                        'conversation_title': conversation_item['title'],
                        'model_deployment_name': image_gen_model,
                        'message_id': image_message_id
                    }), 200
                except Exception as e:
                    debug_print(f"Image generation error: {str(e)}")
                    debug_print(f"Error type: {type(e)}")
                    import traceback
                    debug_print(f"Traceback: {traceback.format_exc()}")
                    
                    # Handle different types of errors appropriately
                    error_message = str(e)
                    status_code = 500
                    
                    # Check if this is a content moderation error
                    if "safety system" in error_message.lower() or "moderation_blocked" in error_message:
                        user_friendly_message = "Image generation was blocked by content safety policies. Please try a different prompt that doesn't involve potentially harmful content."
                        status_code = 400  # Bad request rather than server error
                    elif "400" in error_message and "BadRequestError" in str(type(e)):
                        user_friendly_message = f"Image generation request was invalid: {error_message}"
                        status_code = 400
                    else:
                        user_friendly_message = f"Image generation failed due to a technical error: {error_message}"
                    
                    return jsonify({
                        'error': user_friendly_message
                    }), status_code

            # ---------------------------------------------------------------------
            # 5) Prepare FINAL conversation history for GPT (including summarization)
            # ---------------------------------------------------------------------
            conversation_history_for_api = []
            summary_of_older = ""


            try:
                # Fetch ALL messages for potential summarization, sorted OLD->NEW
                all_messages_query = "SELECT * FROM c WHERE c.conversation_id = @conv_id ORDER BY c.timestamp ASC"
                params_all = [{"name": "@conv_id", "value": conversation_id}]
                all_messages = list(cosmos_messages_container.query_items(
                    query=all_messages_query, parameters=params_all, partition_key=conversation_id, enable_cross_partition_query=True
                ))

                total_messages = len(all_messages)

                # Determine which messages are "recent" and which are "older"
                # `conversation_history_limit` includes the *current* user message
                num_recent_messages = min(total_messages, conversation_history_limit)
                num_older_messages = total_messages - num_recent_messages

                recent_messages = all_messages[-num_recent_messages:] # Last N messages
                older_messages_to_summarize = all_messages[:num_older_messages] # Messages before the recent ones

                # Summarize older messages if needed and present
                if enable_summarize_content_history_beyond_conversation_history_limit and older_messages_to_summarize:
                    print(f"Summarizing {len(older_messages_to_summarize)} older messages for conversation {conversation_id}")
                    summary_prompt_older = (
                        "Summarize the following conversation history concisely (around 50-100 words), "
                        "focusing on key facts, decisions, or context that might be relevant for future turns. "
                        "Do not add any introductory phrases like 'Here is a summary'.\n\n"
                        "Conversation History:\n"
                    )
                    message_texts_older = []
                    for msg in older_messages_to_summarize:
                        role = msg.get('role', 'user')
                        # Skip roles that shouldn't be in summary (adjust as needed)
                        if role in ['system', 'safety', 'blocked', 'image', 'file']: continue
                        content = msg.get('content', '')
                        message_texts_older.append(f"{role.upper()}: {content}")

                    if message_texts_older: # Only summarize if there's content to summarize
                        summary_prompt_older += "\n".join(message_texts_older)
                        try:
                            # Use the already initialized client and model
                            summary_response_older = gpt_client.chat.completions.create(
                                model=gpt_model,
                                messages=[{"role": "system", "content": summary_prompt_older}],
                                max_tokens=150, # Adjust token limit for summary
                                temperature=0.3 # Lower temp for factual summary
                            )
                            summary_of_older = summary_response_older.choices[0].message.content.strip()
                            print(f"Generated summary: {summary_of_older}")
                        except Exception as e:
                            print(f"Error summarizing older conversation history: {e}")
                            summary_of_older = "" # Failed, proceed without summary
                    else:
                        print("No summarizable content found in older messages.")


                # Construct the final history for the API call
                # Start with the summary if available
                if summary_of_older:
                    conversation_history_for_api.append({
                        "role": "system",
                        "content": f"<Summary of previous conversation context>\n{summary_of_older}\n</Summary of previous conversation context>"
                    })

                # Add augmentation system messages (search, agents) next
                # **Important**: Decide if you want these saved. If so, you need to upsert them now.
                # For simplicity here, we're just adding them to the API call context.
                for aug_msg in system_messages_for_augmentation:
                    # 1. Extract the source documents list for this specific system message
                    # Use .get with a default empty list [] for safety in case 'documents' is missing

                    # 5. Create the final system_doc dictionary for Cosmos DB upsert
                    system_message_id = f"{conversation_id}_system_aug_{int(time.time())}_{random.randint(1000,9999)}"
                    system_doc = {
                        'id': system_message_id,
                        'conversation_id': conversation_id,
                        'role': aug_msg.get('role'),
                        'content': aug_msg.get('content'),
                        'search_query': search_query, # Include the search query used for this augmentation
                        'user_message': user_message, # Include the original user message for context
                        'model_deployment_name': None, # As per your original structure
                        'timestamp': datetime.utcnow().isoformat(),
                        'metadata': {}
                    }
                    cosmos_messages_container.upsert_item(system_doc)
                    conversation_history_for_api.append(aug_msg) # Add to API context

                    # --- NEW: Save plugin output as agent citation ---
                    agent_citations_list.append({
                        "tool_name": str(selected_agent.name) if selected_agent else "All Citations",
                        "function_arguments": json.dumps(aug_msg, default=str),
                        "function_result": aug_msg.get('content', ''),
                        "timestamp": datetime.utcnow().isoformat()
                    })


                # Add the recent messages (user, assistant, relevant system/file messages)
                allowed_roles_in_history = ['user', 'assistant'] # Add 'system' if you PERSIST general system messages not related to augmentation
                max_file_content_length_in_history = 50000 # Increased limit for all file content in history
                max_tabular_content_length_in_history = 50000 # Same limit for tabular data consistency

                for message in recent_messages:
                    role = message.get('role')
                    content = message.get('content')

                    if role in allowed_roles_in_history:
                        conversation_history_for_api.append({"role": role, "content": content})
                    elif role == 'file': # Handle file content inclusion (simplified)
                        filename = message.get('filename', 'uploaded_file')
                        file_content = message.get('file_content', '') # Assuming file content is stored
                        is_table = message.get('is_table', False)
                        
                        # Use higher limit for tabular data that needs complete analysis
                        content_limit = max_tabular_content_length_in_history if is_table else max_file_content_length_in_history
                        
                        display_content = file_content[:content_limit]
                        if len(file_content) > content_limit:
                            display_content += "..."
                        
                        # Enhanced message for tabular data
                        if is_table:
                            conversation_history_for_api.append({
                                'role': 'system', # Represent file as system info
                                'content': f"[User uploaded a tabular data file named '{filename}'. This is CSV format data for analysis:\n{display_content}]\nThis is complete tabular data in CSV format. You can perform calculations, analysis, and data operations on this dataset."
                            })
                        else:
                            conversation_history_for_api.append({
                                'role': 'system', # Represent file as system info
                                'content': f"[User uploaded a file named '{filename}'. Content preview:\n{display_content}]\nUse this file context if relevant."
                            })
                    # elif role == 'image': # If you want to represent image generation prompts/results
                    #     prompt = message.get('prompt', 'User generated an image.')
                    #     img_url = message.get('content', '') # URL is in content
                    #     conversation_history_for_api.append({
                    #         'role': 'system',
                    #         'content': f"[Assistant generated an image based on the prompt: '{prompt}'. Image URL: {img_url}]"
                    #     })

                    # Ignored roles: 'safety', 'blocked', 'system' (if they are only for augmentation/summary)

                # Ensure the very last message is the current user's message (it should be if fetched correctly)
                if not conversation_history_for_api or conversation_history_for_api[-1]['role'] != 'user':
                    print("Warning: Last message in history is not the user's current message. Appending.")
                    # This might happen if 'recent_messages' somehow didn't include the latest user message saved in step 2
                    # Or if the last message had an ignored role. Find the actual user message:
                    user_msg_found = False
                    for msg in reversed(recent_messages):
                        if msg['role'] == 'user' and msg['id'] == user_message_id:
                            conversation_history_for_api.append({"role": "user", "content": msg['content']})
                            user_msg_found = True
                            break
                    if not user_msg_found: # Still not found? Append the original input as fallback
                        conversation_history_for_api.append({"role": "user", "content": user_message})

            except Exception as e:
                print(f"Error preparing conversation history: {e}")
                return jsonify({'error': f'Error preparing conversation history: {str(e)}'}), 500

            # ---------------------------------------------------------------------
            # 6) Final GPT Call
            # ---------------------------------------------------------------------
            default_system_prompt = settings.get('default_system_prompt', '').strip()
            # Only add if non-empty and not already present (excluding summary/augmentation system messages)
            if default_system_prompt:
                # Find if any system message (not summary or augmentation) is present
                has_general_system_prompt = any(
                    msg.get('role') == 'system' and not (
                        msg.get('content', '').startswith('<Summary of previous conversation context>') or
                        "retrieved document excerpts" in msg.get('content', '')
                    )
                    for msg in conversation_history_for_api
                )
                if not has_general_system_prompt:
                    # Insert at the start, after any summary if present
                    insert_idx = 0
                    if conversation_history_for_api and conversation_history_for_api[0].get('role') == 'system' and conversation_history_for_api[0].get('content', '').startswith('<Summary of previous conversation context>'):
                        insert_idx = 1
                    conversation_history_for_api.insert(insert_idx, {
                        "role": "system",
                        "content": default_system_prompt
                    })

            # --- DRY Fallback Chain Helper ---
            def try_fallback_chain(steps):
                """
                steps: list of dicts with keys:
                    'name': str, 'func': callable, 'on_success': callable, 'on_error': callable
                Returns: (ai_message, final_model_used, chat_mode, kernel_fallback_notice)
                """
                for step in steps:
                    try:
                        result = step['func']()
                        return step['on_success'](result)
                    except Exception as e:
                        log_event(
                            f"[Fallback Failure] Fallback step {step['name']} failed: {e}",
                            extra={
                                "step_name": step['name'],
                                "error": str(e)
                            }
                        )
                        if 'on_error' in step and step['on_error']:
                            step['on_error'](e)
                        continue
                # If all fail, return default error
                return ("Sorry, I encountered an error.", gpt_model, None, None)

            # --- Inject facts as a system message at the top of conversation_history_for_api ---
            def get_facts_for_context(scope_id, scope_type, conversation_id: str = None, agent_id: str = None):
                settings = get_settings()
                agents = settings.get('semantic_kernel_agents', [])
                default_agent = next((a for a in agents if a.get('default_agent')), None)
                agent_dict = default_agent or (agents[0] if agents else None)
                agent_id = agent_dict.get('id') if agent_dict else None
                if not scope_id or not scope_type:
                    return ""
                fact_store = FactMemoryStore()
                kwargs = dict(
                    scope_type=scope_type,
                    scope_id=scope_id,
                )
                if agent_id:
                    kwargs['agent_id'] = agent_id
                if conversation_id:
                    kwargs['conversation_id'] = conversation_id
                facts = fact_store.get_facts(**kwargs)
                if not facts:
                    return ""
                fact_lines = []
                for fact in facts:
                    value = fact.get('value', '')
                    if value:
                        fact_lines.append(f"- {value}")
                fact_lines.append(f"- agent_id: {agent_id}")
                fact_lines.append(f"- scope_type: {scope_type}")
                fact_lines.append(f"- scope_id: {scope_id}")
                fact_lines.append(f"- conversation_id: {conversation_id}")
                return "\n".join(fact_lines)

            async def run_sk_call(callable_obj, *args, **kwargs):
                log_event(
                    f"Running Semantic Kernel callable: {callable_obj.__name__}",
                    extra={
                        "callable_name": callable_obj.__name__,
                        "call_args": args,
                        "call_kwargs": kwargs
                    }
                )
                runtime = kwargs.get("runtime", None)
                started_runtime = False
                try:
                    if runtime is not None and getattr(runtime, "_run_context", None) is None:
                        runtime.start()
                        started_runtime = True
                        log_event(
                            f"Started runtime for callable: {callable_obj.__name__}",
                            extra={"runtime": runtime}
                        )
                    result = callable_obj(*args, **kwargs)
                    if asyncio.iscoroutine(result):
                        log_event(
                            f"Callable {callable_obj.__name__} returned a coroutine, awaiting.",
                            extra={"callable_name": callable_obj.__name__}
                        )
                        result = await result
                    if hasattr(result, "get") and asyncio.iscoroutinefunction(result.get):
                        try:
                            log_event(
                                f"Callable {callable_obj.__name__} returned an orchestration result, awaiting result.get().",
                                extra={"callable_name": callable_obj.__name__}
                            )
                            return await result.get()
                        except Exception as e:
                            log_event(
                                f"Error awaiting orchestration result.get()", 
                                extra={"error": str(e)},
                                level=logging.ERROR,
                                exceptionTraceback=True
                            )
                            return "Sorry, the orchestration failed."
                    elif isinstance(result, types.AsyncGeneratorType):
                        log_event(
                            f"Callable {callable_obj.__name__} returned an async generator, iterating.",
                            extra={"callable_name": callable_obj.__name__}
                        )
                        async for r in result:
                            return r
                    else:
                        return result
                except asyncio.CancelledError:
                    log_event(
                        f"Callable {callable_obj.__name__} was cancelled.",
                        extra={"callable_name": callable_obj.__name__},
                        level=logging.WARNING,
                        exceptionTraceback=True
                    )
                    raise
                finally:
                    if runtime is not None and started_runtime:
                        log_event(
                            f"Stopping runtime for callable: {callable_obj.__name__}",
                            extra={"runtime": runtime}
                        )
                        await runtime.stop_when_idle()

            ai_message = "Sorry, I encountered an error." # Default error message
            final_model_used = gpt_model # Track model used for the response
            kernel_fallback_notice = None
            chat_mode = None
            scope_id=active_group_id if chat_type == 'group' else user_id
            scope_type='group' if chat_type == 'group' else 'user'
            conversation_id=conversation_id
            enable_multi_agent_orchestration = False
            fallback_steps = []
            selected_agent = None
            user_settings = get_user_settings(user_id).get('settings', {})
            per_user_semantic_kernel = settings.get('per_user_semantic_kernel', False)
            enable_semantic_kernel = settings.get('enable_semantic_kernel', False)
            user_enable_agents = user_settings.get('enable_agents', True)  # Default to True for backward compatibility
            redis_client = None
            # --- Semantic Kernel state management (per-user mode) ---
            if enable_semantic_kernel and per_user_semantic_kernel:
                redis_client = current_app.config.get('SESSION_REDIS') if 'current_app' in globals() else None
                initialize_semantic_kernel(user_id=user_id, redis_client=redis_client)
            elif enable_semantic_kernel:
                # Global mode: set g.kernel/g.kernel_agents from builtins
                g.kernel = getattr(builtins, 'kernel', None)
                g.kernel_agents = getattr(builtins, 'kernel_agents', None)
            if per_user_semantic_kernel:
                settings_agents = user_settings.get('agents', [])
                logging.debug(f"[SKChat] Per-user Semantic Kernel enabled. Using user-specific settings.")
            else: 
                enable_multi_agent_orchestration = settings.get('enable_multi_agent_orchestration', False)
                settings_agents = settings.get('semantic_kernel_agents', [])
            kernel = get_kernel()
            all_agents = get_kernel_agents()
            
            log_event(f"[SKChat] Retrieved kernel: {type(kernel)}, all_agents: {type(all_agents)} with {len(all_agents) if all_agents else 0} agents", level=logging.INFO)
            if all_agents:
                if isinstance(all_agents, dict):
                    agent_names = list(all_agents.keys())
                else:
                    agent_names = [getattr(agent, 'name', 'unnamed') for agent in all_agents]
                log_event(f"[SKChat] Agent names available: {agent_names}", level=logging.INFO)
            else:
                log_event(f"[SKChat] No agents loaded - proceeding in model-only mode", level=logging.INFO)
            
            log_event(f"[SKChat] Semantic Kernel enabled. Per-user mode: {per_user_semantic_kernel}, Multi-agent orchestration: {enable_multi_agent_orchestration}, agents enabled: {user_enable_agents}")
            if enable_semantic_kernel and user_enable_agents:
            # PATCH: Use new agent selection logic
                agent_name_to_select = None
                if per_user_semantic_kernel:
                    agent_name_to_select = user_settings.get('selected_agent')
                    log_event(f"[SKChat] Per-user mode: selected_agent from user_settings: {agent_name_to_select}")
                else:
                    global_selected_agent_info = settings.get('global_selected_agent')
                    if global_selected_agent_info:
                        agent_name_to_select = global_selected_agent_info.get('name')
                        log_event(f"[SKChat] Global mode: selected_agent from global_selected_agent: {agent_name_to_select}")
                if all_agents:
                    agent_iter = all_agents.values() if isinstance(all_agents, dict) else all_agents
                    agent_debug_info = []
                    for agent in agent_iter:
                        agent_debug_info.append({
                            "name": getattr(agent, 'name', None),
                            "default_agent": getattr(agent, 'default_agent', None),
                            "is_global": getattr(agent, 'is_global', None),
                            "repr": repr(agent)
                        })
                        # Prefer explicit selection, fallback to default_agent
                        if agent_name_to_select and getattr(agent, 'name', None) == agent_name_to_select:
                            selected_agent = agent
                            log_event(f"[SKChat] selected_agent found by explicit selection: {agent_name_to_select}")
                            break
                    if not selected_agent:
                        # Fallback to default_agent
                        for agent in agent_iter:
                            if getattr(agent, 'default_agent', False):
                                selected_agent = agent
                                log_event(f"[SKChat] selected_agent found by default_agent=True")
                                break
                    if not selected_agent and agent_iter:
                        selected_agent = next(iter(agent_iter), None)
                        log_event(f"[SKChat] selected_agent fallback to first agent: {getattr(selected_agent, 'name', None)}")
                    log_event(f"[SKChat] Agent selection debug info: {agent_debug_info}")
                else:
                    log_event(f"[SKChat] all_agents is empty or None!", level=logging.WARNING)
                if selected_agent is None:
                    log_event(f"[SKChat][ERROR] No selected_agent found! all_agents: {all_agents}", level=logging.ERROR)
                log_event(f"[SKChat] selected_agent: {str(getattr(selected_agent, 'name', None))}")
                agent_id = getattr(selected_agent, 'id', None)
                extra={
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "scope_type": scope_type,
                    "message_count": len(conversation_history_for_api),
                    "agent": bool(selected_agent is not None),
                    "selected_agent_id": agent_id or None,
                    "kernel": bool(kernel is not None),
                }

                # Use the orchestrator agent as the default agent
                

                # Add additional metadata here to scope the facts to be returned
                # Allows for additional per agent and per conversation scoping.
                facts = get_facts_for_context(
                    scope_id=scope_id,
                    scope_type=scope_type
                )
                if facts:
                    conversation_history_for_api.insert(0, {
                        "role": "system",
                        "content": f"<Fact Memory>\n{facts}\n</Fact Memory>"
                    })
                conversation_history_for_api.insert(0, {
                    "role": "system",
                    "content": f"""<Conversation Metadata>\n<Scope ID: {scope_id}>\n<Scope Type: {scope_type}>\n<Conversation ID: {conversation_id}>\n<Agent ID: {agent_id}>\n</Conversation Metadata>"""
                })

                agent_message_history = [
                    ChatMessageContent(
                        role=msg["role"],
                        content=msg["content"],
                        metadata=msg.get("metadata", {})
                    )
                    for msg in conversation_history_for_api
                ]

                # --- Fallback Chain Steps ---
                if enable_multi_agent_orchestration and all_agents and "orchestrator" in all_agents and not per_user_semantic_kernel:
                    def invoke_orchestrator():
                        orchestrator = all_agents["orchestrator"]
                        runtime = InProcessRuntime()
                        return asyncio.run(run_sk_call(
                            orchestrator.invoke,
                            task=agent_message_history,
                            runtime=runtime,
                        ))
                    def orchestrator_success(result):
                        msg = str(result)
                        notice = None
                        return (msg, "multi-agent-chat", "multi-agent-chat", notice)
                    def orchestrator_error(e):
                        print(f"Error during Semantic Kernel Agent invocation: {str(e)}")
                        log_event(
                            f"Error during Semantic Kernel Agent invocation: {str(e)}",
                            extra=extra,
                            level=logging.ERROR,
                            exceptionTraceback=True
                        )
                    fallback_steps.append({
                        'name': 'orchestrator',
                        'func': invoke_orchestrator,
                        'on_success': orchestrator_success,
                        'on_error': orchestrator_error
                    })

                if selected_agent:
                    def invoke_selected_agent():
                        return asyncio.run(run_sk_call(
                            selected_agent.invoke,
                            agent_message_history,
                        ))
                    def agent_success(result):
                        msg = str(result)
                        notice = None
                        agent_used = getattr(selected_agent, 'name', 'All Plugins')
                        
                        # Get the actual model deployment used by the agent
                        actual_model_deployment = getattr(selected_agent, 'deployment_name', None) or agent_used
                        debug_print(f"Agent '{agent_used}' using deployment: {actual_model_deployment}")
                        
                        # Extract detailed plugin invocations for enhanced agent citations
                        plugin_logger = get_plugin_logger()
                        # CRITICAL FIX: Filter by user_id and conversation_id to prevent cross-conversation contamination
                        plugin_invocations = plugin_logger.get_invocations_for_conversation(user_id, conversation_id)
                        
                        # Convert plugin invocations to citation format with detailed information
                        detailed_citations = []
                        for inv in plugin_invocations:
                            # Handle timestamp formatting safely
                            timestamp_str = None
                            if inv.timestamp:
                                if hasattr(inv.timestamp, 'isoformat'):
                                    timestamp_str = inv.timestamp.isoformat()
                                else:
                                    timestamp_str = str(inv.timestamp)
                            
                            # Ensure all values are JSON serializable
                            def make_json_serializable(obj):
                                if obj is None:
                                    return None
                                elif isinstance(obj, (str, int, float, bool)):
                                    return obj
                                elif isinstance(obj, dict):
                                    return {str(k): make_json_serializable(v) for k, v in obj.items()}
                                elif isinstance(obj, (list, tuple)):
                                    return [make_json_serializable(item) for item in obj]
                                else:
                                    return str(obj)
                            
                            citation = {
                                'tool_name': f"{inv.plugin_name}.{inv.function_name}",
                                'function_name': inv.function_name,
                                'plugin_name': inv.plugin_name,
                                'function_arguments': make_json_serializable(inv.parameters),
                                'function_result': make_json_serializable(inv.result),
                                'duration_ms': inv.duration_ms,
                                'timestamp': timestamp_str,
                                'success': inv.success,
                                'error_message': make_json_serializable(inv.error_message),
                                'user_id': inv.user_id
                            }
                            detailed_citations.append(citation)
                        
                        log_event(
                            f"[Enhanced Agent Citations] Extracted {len(detailed_citations)} detailed plugin invocations",
                            extra={
                                "agent": agent_used,
                                "plugin_count": len(detailed_citations),
                                "plugins": [f"{inv.plugin_name}.{inv.function_name}" for inv in plugin_invocations],
                                "total_duration_ms": sum(inv.duration_ms for inv in plugin_invocations if inv.duration_ms)
                            }
                        )

                        # print(f"[Enhanced Agent Citations] Agent used: {agent_used}")
                        # print(f"[Enhanced Agent Citations] Extracted {len(detailed_citations)} detailed plugin invocations")
                        # for citation in detailed_citations:
                        #     print(f"[Enhanced Agent Citations] - Plugin: {citation['plugin_name']}, Function: {citation['function_name']}")
                        #     print(f"  Parameters: {citation['function_arguments']}")
                        #     print(f"  Result: {citation['function_result']}")
                        #     print(f"  Duration: {citation['duration_ms']}ms, Success: {citation['success']}")

                        # Store detailed citations globally to be accessed by the calling function
                        agent_citations_list.extend(detailed_citations)
                        
                        if enable_multi_agent_orchestration and not per_user_semantic_kernel:
                            # If the agent response indicates fallback mode
                            notice = (
                                "[SK Fallback]: The AI assistant is running in single agent fallback mode. "
                                "Some advanced features may not be available. "
                                "Please contact your administrator to configure Semantic Kernel for richer responses."
                            )
                        return (msg, actual_model_deployment, "agent", notice)
                    def agent_error(e):
                        print(f"Error during Semantic Kernel Agent invocation: {str(e)}")
                        log_event(
                            f"Error during Semantic Kernel Agent invocation: {str(e)}",
                            extra=extra,
                            level=logging.ERROR,
                            exceptionTraceback=True
                        )
                    fallback_steps.append({
                        'name': 'agent',
                        'func': invoke_selected_agent,
                        'on_success': agent_success,
                        'on_error': agent_error
                    })

                if kernel:
                    def invoke_kernel():
                        chat_history = "\n".join([
                            f"{msg['role']}: {msg['content']}" for msg in conversation_history_for_api
                        ])
                        chat_func = None
                        if hasattr(kernel, 'plugins'):
                            for plugin in kernel.plugins.values():
                                if hasattr(plugin, 'functions') and 'chat' in plugin.functions:
                                    chat_func = plugin.functions['chat']
                                    break
                        if chat_func:
                            return asyncio.run(run_sk_call(kernel.invoke, chat_func, input=chat_history))
                        else:
                            log_event(
                                "No dedicated chat action/plugin found. Trying kernel-native chatcompletion via service lookup.",
                                extra=extra, 
                                level=logging.WARNING
                            )
                            chat_service = kernel.get_service(type=ChatCompletionClientBase)
                            if chat_service is not None:
                                chat_hist = ChatHistory()
                                for msg in conversation_history_for_api:
                                    chat_hist.add_message({"role": msg["role"], "content": msg["content"]})
                                settings_obj = PromptExecutionSettings()
                                async def run_chatcompletion():
                                    return await chat_service.get_chat_message_contents(chat_hist, settings_obj)
                                chat_result = asyncio.run(run_chatcompletion())
                                if chat_result and hasattr(chat_result[0], 'content'):
                                    return chat_result[0].content
                                else:
                                    return str(chat_result)
                            else:
                                log_event("No chat completion service found in kernel. Falling back to GPT.", extra=extra, level=logging.WARNING)
                                raise Exception("No chat completion service found in kernel.")
                    def kernel_success(result):
                        msg = '[SK fallback] Running in kernel only mode. Ask your administrator to configure Semantic Kernel for richer responses.'
                        return (str(result), "kernel", "kernel", msg)
                    def kernel_error(e):
                        print(f"Error during kernel invocation: {str(e)}")
                        log_event(
                            f"Error during kernel invocation: {str(e)}",
                            extra=extra,
                            level=logging.ERROR,
                            exceptionTraceback=True
                        )
                    fallback_steps.append({
                        'name': 'kernel',
                        'func': invoke_kernel,
                        'on_success': kernel_success,
                        'on_error': kernel_error
                    })

            def invoke_gpt_fallback():
                if not conversation_history_for_api:
                    raise Exception('Cannot generate response: No conversation history available.')
                if conversation_history_for_api[-1].get('role') != 'user':
                    raise Exception('Internal error: Conversation history improperly formed.')
                print(f"--- Sending to GPT ({gpt_model}) ---")
                print(f"Total messages in API call: {len(conversation_history_for_api)}")
                response = gpt_client.chat.completions.create(
                    model=gpt_model,
                    messages=conversation_history_for_api,
                )
                msg = response.choices[0].message.content
                notice = None
                if enable_semantic_kernel and user_enable_agents:
                    msg = f"[GPT Fallback. Advanced features not available.] {msg}"
                    notice = (
                        "[SK Fallback]: The AI assistant is running in GPT only mode. "
                        "No advanced features are available. "
                        "Please contact your administrator to resolve Semantic Kernel integration."
                    )
                log_event(
                    f"[Tokens] GPT completion response received - prompt_tokens: {response.usage.prompt_tokens}, completion_tokens: {response.usage.completion_tokens}, total_tokens: {response.usage.total_tokens}",
                    extra={
                        "model": gpt_model,
                        "completion_tokens": response.usage.completion_tokens,
                        "prompt_tokens": response.usage.prompt_tokens,
                        "total_tokens": response.usage.total_tokens,
                        "user_id": get_current_user_id(),
                        "active_group_id": active_group_id,
                        "doc_scope": document_scope
                    },
                    level=logging.INFO
                )
                return (msg, gpt_model, None, notice)
            def gpt_success(result):
                return result
            def gpt_error(e):
                print(f"Error during final GPT completion: {str(e)}")
                if "context length" in str(e).lower():
                    return ("Sorry, the conversation history is too long even after summarization. Please start a new conversation or try a shorter message.", gpt_model, None, None)
                else:
                    return (f"Sorry, I encountered an error generating the response. Details: {str(e)}", gpt_model, None, None)
            fallback_steps.append({
                'name': 'gpt',
                'func': invoke_gpt_fallback,
                'on_success': gpt_success,
                'on_error': gpt_error
            })

            ai_message, final_model_used, chat_mode, kernel_fallback_notice = try_fallback_chain(fallback_steps)
            if kernel:
                try:
                    for service in getattr(kernel, "services", {}).values():
                        # Each service is likely an AzureChatCompletion or similar
                        prompt_tokens = getattr(service, "prompt_tokens", None)
                        completion_tokens = getattr(service, "completion_tokens", None)
                        total_tokens = getattr(service, "total_tokens", None)
                        debug_print(f"Service {getattr(service, 'service_id', None)} prompt_tokens: {prompt_tokens}, completion_tokens: {completion_tokens}, total_tokens: {total_tokens}")
                        log_event(
                            f"[Tokens] Service token usage: prompt_tokens: {prompt_tokens}, completion_tokens: {completion_tokens}, total_tokens: {total_tokens}",
                            extra={
                                "service_id": getattr(service, "service_id", None),
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens,
                                "total_tokens": total_tokens,
                                "user_id": get_current_user_id(),
                                "active_group_id": active_group_id,
                                "doc_scope": document_scope
                            },
                            level=logging.INFO
                        )
                except Exception as e:
                    log_event(
                        f"[Tokens] Error logging service token usage for user '{get_current_user_id()}': {e}",
                        level=logging.ERROR,
                        exceptionTraceback=True
                    )


            # ---------------------------------------------------------------------
            # 7) Save GPT response (or error message)
            # ---------------------------------------------------------------------
            
            # Determine the actual model used and agent information
            actual_model_used = final_model_used
            agent_display_name = None
            agent_name = None
            
            if selected_agent:
                # When using an agent, use the agent's actual model deployment
                if hasattr(selected_agent, 'deployment_name') and selected_agent.deployment_name:
                    actual_model_used = selected_agent.deployment_name
                
                # Get agent display information
                if hasattr(selected_agent, 'display_name'):
                    agent_display_name = selected_agent.display_name
                if hasattr(selected_agent, 'name'):
                    agent_name = selected_agent.name
            
            assistant_message_id = f"{conversation_id}_assistant_{int(time.time())}_{random.randint(1000,9999)}"
            assistant_doc = {
                'id': assistant_message_id,
                'conversation_id': conversation_id,
                'role': 'assistant',
                'content': ai_message,
                'timestamp': datetime.utcnow().isoformat(),
                'augmented': bool(system_messages_for_augmentation),
                'hybrid_citations': hybrid_citations_list, # <--- SIMPLIFIED: Directly use the list
                'hybridsearch_query': search_query if hybrid_search_enabled and search_results else None, # Log query only if hybrid search ran and found results
                'agent_citations': agent_citations_list, # <--- NEW: Store agent tool invocation results
                'user_message': user_message,
                'model_deployment_name': actual_model_used,
                'agent_display_name': agent_display_name,
                'agent_name': agent_name,
                'metadata': {} # Used by SK
            }
            cosmos_messages_container.upsert_item(assistant_doc)

            # Update the user message metadata with the actual model used
            # This ensures the UI shows the correct model in the metadata panel
            try:
                user_message_doc = cosmos_messages_container.read_item(
                    item=user_message_id, 
                    partition_key=conversation_id
                )
                
                # Update the model selection in metadata to show actual model used
                if 'metadata' in user_message_doc and 'model_selection' in user_message_doc['metadata']:
                    user_message_doc['metadata']['model_selection']['selected_model'] = actual_model_used
                    cosmos_messages_container.upsert_item(user_message_doc)
                    
            except Exception as e:
                print(f"Warning: Could not update user message metadata: {e}")

            # Update conversation's last_updated timestamp one last time
            conversation_item['last_updated'] = datetime.utcnow().isoformat()
            
            # Collect comprehensive conversation metadata
            try:
                # Determine selected agent name if one was used
                selected_agent_name = None
                if selected_agent:
                    selected_agent_name = getattr(selected_agent, 'name', None)
                
                # Collect metadata for this conversation interaction
                conversation_item = collect_conversation_metadata(
                    user_message=user_message,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    active_group_id=active_group_id,
                    document_scope=document_scope,
                    selected_document_id=selected_document_id,
                    model_deployment=actual_model_used,
                    hybrid_search_enabled=hybrid_search_enabled,
                    image_gen_enabled=image_gen_enabled,
                    selected_documents=combined_documents if 'combined_documents' in locals() else None,
                    selected_agent=selected_agent_name,
                    search_results=search_results if 'search_results' in locals() else None,
                    conversation_item=conversation_item
                )
            except Exception as e:
                print(f"Error collecting conversation metadata: {e}")
                # Continue even if metadata collection fails
            
            # Add any other final updates to conversation_item if needed (like classifications if not done earlier)
            cosmos_conversations_container.upsert_item(conversation_item)

            # ---------------------------------------------------------------------
            # 8) Return final success (even if AI generated an error message)
            # ---------------------------------------------------------------------
            # Persist per-user kernel state if needed
            enable_redis_for_kernel = False
            if enable_semantic_kernel and per_user_semantic_kernel and redis_client and enable_redis_for_kernel:
                save_user_kernel(user_id, g.kernel, g.kernel_agents, redis_client)
            return jsonify({
                'reply': ai_message, # Send the AI's response (or the error message) back
                'conversation_id': conversation_id,
                'conversation_title': conversation_item['title'], # Send updated title
                'classification': conversation_item.get('classification', []), # Send classifications if any
                'model_deployment_name': actual_model_used,
                'agent_display_name': agent_display_name,
                'agent_name': agent_name,
                'message_id': assistant_message_id,
                'user_message_id': user_message_id,  # Include the user message ID
                'blocked': False, # Explicitly false if we got this far
                'augmented': bool(system_messages_for_augmentation),
                'hybrid_citations': hybrid_citations_list,
                'agent_citations': agent_citations_list,
                'kernel_fallback_notice': kernel_fallback_notice
            }), 200
        
        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            print(f"[CHAT API ERROR] Unhandled exception in chat_api: {str(e)}")
            print(f"[CHAT API ERROR] Full traceback:\n{error_traceback}")
            log_event(
                f"[CHAT API ERROR] Unhandled exception in chat_api: {str(e)}",
                extra={
                    "error_message": str(e),
                    "traceback": error_traceback,
                    "user_id": user_id if 'user_id' in locals() else None,
                    "conversation_id": conversation_id if 'conversation_id' in locals() else None
                },
                level=logging.ERROR
            )
            return jsonify({
                'error': f'Internal server error: {str(e)}',
                'details': error_traceback if app.debug else None
            }), 500