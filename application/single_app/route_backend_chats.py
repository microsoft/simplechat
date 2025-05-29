# route_backend_chats.py

from config import *
from functions_authentication import *
from functions_search import *
from functions_bing_search import *
from functions_settings import *

def register_route_backend_chats(app):
    @app.route('/api/chat', methods=['POST'])
    @login_required
    @user_required
    def chat_api():
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
        bing_search_enabled = data.get('bing_search')
        image_gen_enabled = data.get('image_generation')
        document_scope = data.get('doc_scope')
        active_group_id = data.get('active_group_id')
        frontend_gpt_model = data.get('model_deployment')
        
        search_query = user_message # <--- ADD THIS LINE (Initialize search_query)
        hybrid_citations_list = [] # <--- ADD THIS LINE (Initialize hybrid list)
        system_messages_for_augmentation = [] # Collect system messages from search/bing
        search_results = []
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
        if isinstance(bing_search_enabled, str):
            bing_search_enabled = bing_search_enabled.lower() == 'true'
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
                'title': 'New Conversation'
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
                    'title': 'New Conversation' # Or maybe fetch title differently?
                }
                # Optionally log that a conversation was expected but not found
                print(f"Warning: Conversation ID {conversation_id} not found, creating new.")
                cosmos_conversations_container.upsert_item(conversation_item)
            except Exception as e:
                print(f"Error reading conversation {conversation_id}: {e}")
                return jsonify({'error': f'Error reading conversation: {str(e)}'}), 500

        # ---------------------------------------------------------------------
        # 2) Append the user message to conversation immediately
        # ---------------------------------------------------------------------
        user_message_id = f"{conversation_id}_user_{int(time.time())}_{random.randint(1000,9999)}"
        user_message_doc = {
            'id': user_message_id,
            'conversation_id': conversation_id,
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.utcnow().isoformat(),
            'model_deployment_name': None # Model not used for user message
        }
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
                        'reason': "; ".join(block_reasons)
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
                        'model_deployment_name': None
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
        # 4) Augmentation (Search, Bing, etc.) - Run *before* final history prep
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
                search_args = {
                    "query": search_query,
                    "user_id": user_id,
                    "top_n": 12,
                    "doc_scope": document_scope,
                    "active_group_id": active_group_id
                }
                if selected_document_id:
                    search_args["document_id"] = selected_document_id

                search_results = hybrid_search(**search_args) # Assuming hybrid_search handles None document_id
            except Exception as e:
                 print(f"Error during hybrid search: {e}")
                 # Optionally inform the user or just proceed without search results

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

        # Bing Search
        bing_results = []
        bing_citations_list = []
        
        if bing_search_enabled:
             # Collect citations for Bing results
            try:
                bing_results = process_query_with_bing_and_llm(user_message) # Assuming this function exists and works
            except Exception as e:
                 print(f"Error during Bing search: {e}")
                 # Optionally inform user or proceed

            if bing_results:
                retrieved_texts_bing = []
                for r in bing_results:
                    title = r.get("name", "Untitled")
                    snippet = r.get("snippet", "No snippet available.")
                    url = r.get("url", "#")
                    citation = f"(Source: {title}) [{url}]"
                    retrieved_texts_bing.append(f"{snippet}\n{citation}")
                    
                    # <<< Collect Bing citation data >>>
                    bing_citation_data = {
                        "title": title,
                        "url": url,
                        "snippet": snippet # Store the snippet used in the prompt
                    }
                    bing_citations_list.append(bing_citation_data)

                retrieved_content_bing = "\n\n".join(retrieved_texts_bing)
                system_prompt_bing = f"""You are an AI assistant. Use the following web search results to answer the user's question. Cite sources using the format (Source: page_title).

                    Web Search Results:
                    {retrieved_content_bing}

                    Based *only* on the information provided above, answer the user's query. If the answer isn't in the results, say so.

                    Example:
                    User: What is the capital of France?
                    Assistant: The capital of France is Paris (Source: OfficialFrancePage)
                    """
                # Add to the temporary list
                system_messages_for_augmentation.append({
                    'role': 'system',
                    'content': system_prompt_bing
                })

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
                image_response = image_gen_client.images.generate(
                    prompt=user_message,
                    n=1,
                    model=image_gen_model
                )
                generated_image_url = json.loads(image_response.model_dump_json())['data'][0]['url']

                image_message_id = f"{conversation_id}_image_{int(time.time())}_{random.randint(1000,9999)}"
                image_doc = {
                    'id': image_message_id,
                    'conversation_id': conversation_id,
                    'role': 'image',
                    'content': generated_image_url,
                    'prompt': user_message,
                    'created_at': datetime.utcnow().isoformat(),
                    'timestamp': datetime.utcnow().isoformat(),
                    'model_deployment_name': image_gen_model
                }
                cosmos_messages_container.upsert_item(image_doc)

                conversation_item['last_updated'] = datetime.utcnow().isoformat()
                cosmos_conversations_container.upsert_item(conversation_item)

                return jsonify({
                    'reply': "Image loading...",
                    'image_url': generated_image_url,
                    'conversation_id': conversation_id,
                    'conversation_title': conversation_item['title'],
                    'model_deployment_name': image_gen_model,
                    'message_id': image_message_id
                }), 200
            except Exception as e:
                return jsonify({
                    'error': f'Image generation failed: {str(e)}'
                }), 500

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

            # Add augmentation system messages (search, bing) next
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
                    'timestamp': datetime.utcnow().isoformat()
                }
                cosmos_messages_container.upsert_item(system_doc)
                conversation_history_for_api.append(aug_msg) # Add to API context


            # Add the recent messages (user, assistant, relevant system/file messages)
            allowed_roles_in_history = ['user', 'assistant'] # Add 'system' if you PERSIST general system messages not related to augmentation
            max_file_content_length_in_history = 1000 # Limit file content directly in history

            for message in recent_messages:
                role = message.get('role')
                content = message.get('content')

                if role in allowed_roles_in_history:
                    conversation_history_for_api.append({"role": role, "content": content})
                elif role == 'file': # Handle file content inclusion (simplified)
                     filename = message.get('filename', 'uploaded_file')
                     file_content = message.get('file_content', '') # Assuming file content is stored
                     display_content = file_content[:max_file_content_length_in_history]
                     if len(file_content) > max_file_content_length_in_history:
                         display_content += "..."
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
        ai_message = "Sorry, I encountered an error." # Default error message
        final_model_used = gpt_model # Track model used for the response

        if not conversation_history_for_api:
             return jsonify({'error': 'Cannot generate response: No conversation history available.'}), 500
        if conversation_history_for_api[-1].get('role') != 'user':
             print(f"Error: Last message role is not user: {conversation_history_for_api[-1].get('role')}")
             return jsonify({'error': 'Internal error: Conversation history improperly formed.'}), 500

        try:
            print(f"--- Sending to GPT ({final_model_used}) ---")
            # print(json.dumps(conversation_history_for_api, indent=2)) # DEBUG: Log the exact history sent
            print(f"Total messages in API call: {len(conversation_history_for_api)}")
            # Calculate rough token estimate if needed for debugging

            response = gpt_client.chat.completions.create(
                model=final_model_used,
                messages=conversation_history_for_api,
                # Add other parameters like temperature, max_tokens if needed
            )
            ai_message = response.choices[0].message.content

            # Optional: Log token usage
            # print(f"Completion Tokens: {response.usage.completion_tokens}")
            # print(f"Prompt Tokens: {response.usage.prompt_tokens}")
            # print(f"Total Tokens: {response.usage.total_tokens}")

        except Exception as e:
            print(f"Error during final GPT completion: {str(e)}")
            # Keep the default error message 'ai_message'
            # Optionally, set a more specific error message based on exception type
            if "context length" in str(e).lower():
                 ai_message = "Sorry, the conversation history is too long even after summarization. Please start a new conversation or try a shorter message."
            else:
                 ai_message = f"Sorry, I encountered an error generating the response. Details: {str(e)}"
            # Return 500 but include the error message for the user
            # Save the error message as the assistant response? Or just return error?
            # Let's save the error as the response for now.
            pass # Fallthrough to save the error message


        # ---------------------------------------------------------------------
        # 7) Save GPT response (or error message)
        # ---------------------------------------------------------------------
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
            'web_search_citations': bing_citations_list, # <--- SIMPLIFIED: Directly use the list
            'user_message': user_message,
            'model_deployment_name': final_model_used
        }
        cosmos_messages_container.upsert_item(assistant_doc)

        # Update conversation's last_updated timestamp one last time
        conversation_item['last_updated'] = datetime.utcnow().isoformat()
        # Add any other final updates to conversation_item if needed (like classifications if not done earlier)
        cosmos_conversations_container.upsert_item(conversation_item)

        # ---------------------------------------------------------------------
        # 8) Return final success (even if AI generated an error message)
        # ---------------------------------------------------------------------
        return jsonify({
            'reply': ai_message, # Send the AI's response (or the error message) back
            'conversation_id': conversation_id,
            'conversation_title': conversation_item['title'], # Send updated title
            'classification': conversation_item.get('classification', []), # Send classifications if any
            'model_deployment_name': final_model_used,
            'message_id': assistant_message_id,
            'blocked': False, # Explicitly false if we got this far
            'augmented': bool(system_messages_for_augmentation),
            'hybrid_citations': hybrid_citations_list,
            'web_search_citations': bing_citations_list
        }), 200