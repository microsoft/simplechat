# functions_conversation_metadata.py

from datetime import datetime
from config import *
from functions_settings import get_settings
from functions_authentication import get_current_user_info
from functions_group import find_group_by_id
from functions_public_workspaces import find_public_workspace_by_id
from functions_documents import get_document_metadata
from functions_debug import debug_print

def get_user_info_by_id(user_id):
    """
    Get user information by user ID from user settings or other sources.
    
    Args:
        user_id: The user ID to look up
        
    Returns:
        dict: User information with userId, name, email or None if not found
    """
    try:
        # Try to get from user_settings container first
        user_doc = cosmos_user_settings_container.read_item(
            item=user_id,
            partition_key=user_id
        )
        
        return {
            "userId": user_id,
            "name": user_doc.get("display_name", "Unknown User"),
            "email": user_doc.get("email", "")
        }
        
    except Exception:
        # If not found in user settings, return basic info
        return {
            "userId": user_id,
            "name": "Unknown User", 
            "email": ""
        }


def collect_conversation_metadata(user_message, conversation_id, user_id, active_group_id=None, 
                                document_scope=None, selected_document_id=None, model_deployment=None,
                                hybrid_search_enabled=False, 
                                image_gen_enabled=False, selected_documents=None, 
                                selected_agent=None, selected_agent_details=None, search_results=None, web_search_results=None,
                                conversation_item=None, additional_participants=None):
    """
    Collect comprehensive metadata for a conversation based on the user's interaction.
    
    Args:
        user_message: The user's message
        conversation_id: The conversation ID
        user_id: The user ID
        active_group_id: The active group ID if any
        document_scope: The document scope (personal, group, public, all)
        selected_document_id: Specific document ID if selected
        model_deployment: The AI model deployment name used
        hybrid_search_enabled: Whether hybrid search was used
        image_gen_enabled: Whether image generation was used
        selected_documents: List of documents actually used in the response
        selected_agent: Agent used if any
        search_results: Results from hybrid search
        conversation_item: Existing conversation item to update
        additional_participants: List of additional user IDs to include as participants
        selected_agent_details: Detailed agent metadata (is_group, group_id, group_name)
        
    Returns:
        dict: Updated conversation metadata
    """
    
    # Initialize metadata structure if not exists
    if not conversation_item:
        conversation_item = {}
    
    # Initialize context if not exists
    if 'context' not in conversation_item:
        conversation_item['context'] = []
    
    # Initialize tags if not exists
    if 'tags' not in conversation_item:
        conversation_item['tags'] = []
    
    # Initialize strict mode (default to false for now)
    if 'strict' not in conversation_item:
        conversation_item['strict'] = False
    
    # Prepare agent-derived group context (used when agent is a group and no documents were used)
    agent_primary_context = None
    agent_primary_context_active = False
    if selected_agent_details and selected_agent_details.get('is_group'):
        group_id = selected_agent_details.get('group_id')
        group_name = selected_agent_details.get('group_name')

        if group_id:
            if not group_name:
                group_info = find_group_by_id(group_id)
                if group_info:
                    group_name = group_info.get('name')
            agent_primary_context = {
                "type": "primary",
                "scope": "group",
                "id": group_id,
                "name": group_name or "Unknown Group"
            }

    # Process documents from search results first to determine primary context
    document_map = {}  # Map of document_id -> {scope, chunks, classification}
    workspace_used = None  # Track the first workspace used (becomes primary context)
    
    if search_results:
        for doc in search_results:
            chunk_id = doc.get('id')
            doc_scope_result = _determine_document_scope(doc, user_id, active_group_id)
            classification = doc.get('document_classification', 'None')
            
            if chunk_id:
                # Extract document ID from chunk ID (assumes format: doc_id_chunkNumber)
                if '_' in chunk_id:
                    document_id = '_'.join(chunk_id.split('_')[:-1])  # Remove last part (chunk number)
                else:
                    document_id = chunk_id  # Use full ID if no underscore
                
                # Initialize document entry if not exists
                if document_id not in document_map:
                    document_map[document_id] = {
                        'scope': doc_scope_result,
                        'chunk_ids': [],
                        'classification': classification
                    }
                
                # Add chunk ID to this document
                if chunk_id not in document_map[document_id]['chunk_ids']:
                    document_map[document_id]['chunk_ids'].append(chunk_id)
                
                # Set workspace_used to the first workspace encountered (for primary context)
                if workspace_used is None:
                    workspace_used = doc_scope_result
    
    # Set primary context based on document usage
    primary_context = None
    if workspace_used:
        # Documents were used - the first workspace becomes primary context
        scope_type = workspace_used['scope']
        scope_id = workspace_used['id']
        
        # Get appropriate name based on scope
        context_name = "Unknown"
        if scope_type == "group":
            group_info = find_group_by_id(scope_id)
            context_name = group_info.get('name', 'Unknown Group') if group_info else 'Unknown Group'
        elif scope_type == "public":
            workspace_info = find_public_workspace_by_id(scope_id)
            context_name = workspace_info.get('name', 'Unknown Workspace') if workspace_info else 'Unknown Workspace'
        elif scope_type == "personal":
            user_info = get_user_info_by_id(scope_id)
            context_name = user_info.get('name', 'Personal') if user_info else 'Personal'
        
        primary_context = {
            "type": "primary",
            "scope": scope_type,
            "id": scope_id,
            "name": context_name
        }
    # If no documents were used, fall back to agent-based primary context
    if not primary_context and agent_primary_context:
        primary_context = agent_primary_context
        agent_primary_context_active = True
    
    # Update or add primary context only if we don't already have one
    existing_primary = next((ctx for ctx in conversation_item['context'] if ctx.get('type') == 'primary'), None)
    if primary_context:
        if existing_primary:
            # Primary context already exists - determine how to handle the new context
            if (existing_primary.get('scope') == primary_context.get('scope') and 
                existing_primary.get('id') == primary_context.get('id')):
                # Same workspace - update existing primary context (e.g., refresh name)
                existing_primary.update(primary_context)
                debug_print(f"Updated existing primary context: {existing_primary}")
            elif agent_primary_context_active:
                # Promote the group agent context to become the new primary context
                existing_primary.update({
                    "scope": primary_context.get('scope'),
                    "id": primary_context.get('id'),
                    "name": primary_context.get('name')
                })
                debug_print(f"Replaced existing primary context with agent group context: {existing_primary}")
                primary_context = None
            else:
                # Different workspace - this should become a secondary context
                debug_print(f"Primary context already exists ({existing_primary.get('scope')}:{existing_primary.get('id')}), "f"treating new workspace ({primary_context.get('scope')}:{primary_context.get('id')}) as secondary")
                # We'll handle this in the secondary context logic below
                primary_context = None  # Don't set as primary, will be added as secondary
        else:
            # No existing primary context - set this as primary
            conversation_item['context'].append(primary_context)
            debug_print(f"Set new primary context: {primary_context}")
    elif not existing_primary:
        # No documents used and no existing primary context - this is a model-only conversation
        # We'll add Model context as secondary later
        pass
    
    # Collect secondary contexts based on other workspaces used
    secondary_contexts = []
    document_secondary_contexts = set()  # Track unique secondary contexts from documents
    
    # Get the current primary context for comparison
    current_primary = next((ctx for ctx in conversation_item['context'] if ctx.get('type') == 'primary'), None)
    
    # Process documents for secondary contexts (including the workspace_used if it wasn't set as primary)
    if document_map:
        for document_id, doc_info in document_map.items():
            scope_info = doc_info['scope']
            
            # Check if this workspace is different from the current primary context
            is_different_from_primary = True
            if current_primary:
                if (scope_info['scope'] == current_primary.get('scope') and 
                    scope_info['id'] == current_primary.get('id')):
                    is_different_from_primary = False
            
            # Add to secondary contexts if different from primary
            if is_different_from_primary:
                context_key = (scope_info['scope'], scope_info['id'])
                document_secondary_contexts.add(context_key)
                debug_print(f"Adding workspace to secondary contexts: {scope_info['scope']}:{scope_info['id']}")
    
    # Add secondary contexts from other workspaces with names
    existing_secondary_ids = {ctx.get('id') for ctx in conversation_item['context'] if ctx.get('type') == 'secondary'}
    for scope, ctx_id in document_secondary_contexts:
        if ctx_id not in existing_secondary_ids:
            # Get appropriate name based on scope
            context_name = "Unknown"
            if scope == "group":
                group_info = find_group_by_id(ctx_id)
                context_name = group_info.get('name', 'Unknown Group') if group_info else 'Unknown Group'
            elif scope == "public":
                workspace_info = find_public_workspace_by_id(ctx_id)
                context_name = workspace_info.get('name', 'Unknown Workspace') if workspace_info else 'Unknown Workspace'
            elif scope == "personal":
                user_info = get_user_info_by_id(ctx_id)
                context_name = user_info.get('name', 'Unknown User') if user_info else 'Unknown User'
            
            secondary_contexts.append({
                "type": "secondary",
                "scope": scope,
                "id": ctx_id,
                "name": context_name
            })
    
    # Add Model knowledge context for conversations without documents or as secondary for document conversations
    existing_model_context = next((ctx for ctx in conversation_item['context'] 
                                 if ctx.get('type') == 'secondary' and ctx.get('scope') == 'Model'), None)
    
    if not existing_model_context:
        # Always add Model context as secondary (to track that model knowledge was used)
        secondary_contexts.append({
            "type": "secondary",
            "scope": "Model",
            "id": "N/A", 
            "name": "Model's knowledge"
        })
    
    # Add new secondary contexts
    for ctx in secondary_contexts:
        conversation_item['context'].append(ctx)
    
    # Set chat_type based on primary context
    existing_primary = next((ctx for ctx in conversation_item['context'] if ctx.get('type') == 'primary'), None)
    if existing_primary:
        # Documents were used - set chat_type based on primary context scope
        if existing_primary.get('scope') == 'group':
            conversation_item['chat_type'] = 'group-single-user'  # Default to single-user for now
        elif existing_primary.get('scope') == 'public':
            conversation_item['chat_type'] = 'public'
        elif existing_primary.get('scope') == 'personal':
            conversation_item['chat_type'] = 'personal'
    else:
        # No documents used - model-only conversation, don't set chat_type
        # This will result in no badges being shown
        pass
    
    # Collect and update tags with proper deduplication
    current_tags = {}
    
    # Build existing tags dictionary with proper keys for deduplication
    for tag in conversation_item['tags']:
        if tag.get('category') == 'participant':
            # Use user_id as key for participants
            key = ('participant', tag.get('user_id'))
        elif tag.get('category') == 'document':
            # Use document_id as key for documents
            key = ('document', tag.get('document_id'))
        else:
            # Use value as key for other categories (agent, model, semantic, web)
            key = (tag.get('category'), tag.get('value'))
        current_tags[key] = tag
    
    # Add agent tag (avoid duplicates)
    if selected_agent:
        agent_key = ('agent', selected_agent)
        if agent_key not in current_tags:
            agent_tag = {
                "category": "agent",
                "value": selected_agent
            }
            current_tags[agent_key] = agent_tag
    
    # Add model tag (avoid duplicates)
    if model_deployment:
        model_key = ('model', model_deployment)
        if model_key not in current_tags:
            model_tag = {
                "category": "model", 
                "value": model_deployment
            }
            current_tags[model_key] = model_tag
    
    # Add participant tag for current user with full information (avoid duplicates)
    participant_key = ('participant', user_id)
    if participant_key not in current_tags:
        current_user_info = get_current_user_info()
        if current_user_info:
            participant_tag = {
                "category": "participant",
                "user_id": current_user_info.get("userId", user_id),
                "name": current_user_info.get("displayName", "Unknown User"),
                "email": current_user_info.get("email", "")
            }
        else:
            # Fallback if user info not available
            participant_tag = {
                "category": "participant",
                "user_id": user_id,
                "name": "Unknown User",
                "email": ""
            }
        current_tags[participant_key] = participant_tag
    
    # Add additional participants if provided (avoid duplicates)
    if additional_participants:
        for participant_id in additional_participants:
            participant_key = ('participant', participant_id)
            if participant_key not in current_tags:  # Don't duplicate existing participants
                participant_info = get_user_info_by_id(participant_id)
                if participant_info:
                    additional_participant_tag = {
                        "category": "participant",
                        "user_id": participant_info.get("userId", participant_id),
                        "name": participant_info.get("name", "Unknown User"),
                        "email": participant_info.get("email", "")
                    }
                    current_tags[('participant', participant_id)] = additional_participant_tag
    
    # Create consolidated document tags (handle existing documents properly)
    for document_id, doc_info in document_map.items():
        doc_key = ('document', document_id)
        
        # Check if this document already exists in current_tags
        if doc_key in current_tags:
            # Merge chunk IDs with existing document
            existing_doc = current_tags[doc_key]
            existing_chunks = existing_doc.get('chunk_ids', [])
            new_chunks = doc_info['chunk_ids']
            
            # Add only new chunk IDs that don't already exist
            for chunk_id in new_chunks:
                if chunk_id not in existing_chunks:
                    existing_chunks.append(chunk_id)
            
            # Update the existing document entry with chunk IDs
            existing_doc['chunk_ids'] = existing_chunks
            
            # Ensure existing document has title and scope name if missing
            if 'title' not in existing_doc or not existing_doc.get('title'):
                doc_scope = doc_info['scope']
                scope_type = doc_scope['scope']
                scope_id = doc_scope['id']
                
                # Get document title
                if scope_type == "group":
                    doc_metadata = get_document_metadata(document_id, user_id, group_id=scope_id)
                elif scope_type == "public":
                    doc_metadata = get_document_metadata(document_id, user_id, public_workspace_id=scope_id)
                else:  # personal
                    doc_metadata = get_document_metadata(document_id, user_id)
                
                if doc_metadata:
                    existing_doc['title'] = doc_metadata.get('title') or doc_metadata.get('file_name', 'Unknown Document')
            
            # Ensure scope has name if missing
            if isinstance(existing_doc.get('scope'), dict) and 'name' not in existing_doc['scope']:
                scope_info = existing_doc['scope']
                scope_type = scope_info['type']
                scope_id = scope_info['id']
                
                scope_name = "Unknown"
                if scope_type == "group":
                    group_info = find_group_by_id(scope_id)
                    scope_name = group_info.get('name', 'Unknown Group') if group_info else 'Unknown Group'
                elif scope_type == "public":
                    workspace_info = find_public_workspace_by_id(scope_id)
                    scope_name = workspace_info.get('name', 'Unknown Workspace') if workspace_info else 'Unknown Workspace'
                elif scope_type == "personal":
                    user_info = get_user_info_by_id(scope_id)
                    scope_name = user_info.get('name', 'Personal') if user_info else 'Personal'
                
                existing_doc['scope']['name'] = scope_name
        else:
            # Create new document entry with title and scope name
            # Get document metadata to retrieve title
            doc_scope = doc_info['scope']
            scope_type = doc_scope['scope']
            scope_id = doc_scope['id']
            
            # Get document title
            if scope_type == "group":
                doc_metadata = get_document_metadata(document_id, user_id, group_id=scope_id)
            elif scope_type == "public":
                doc_metadata = get_document_metadata(document_id, user_id, public_workspace_id=scope_id)
            else:  # personal
                doc_metadata = get_document_metadata(document_id, user_id)
            
            doc_title = "Unknown Document"
            if doc_metadata:
                doc_title = doc_metadata.get('title') or doc_metadata.get('file_name', 'Unknown Document')
            
            # Get scope name
            scope_name = "Unknown"
            if scope_type == "group":
                group_info = find_group_by_id(scope_id)
                scope_name = group_info.get('name', 'Unknown Group') if group_info else 'Unknown Group'
            elif scope_type == "public":
                workspace_info = find_public_workspace_by_id(scope_id)
                scope_name = workspace_info.get('name', 'Unknown Workspace') if workspace_info else 'Unknown Workspace'
            elif scope_type == "personal":
                user_info = get_user_info_by_id(scope_id)
                scope_name = user_info.get('name', 'Personal') if user_info else 'Personal'
            
            doc_tag = {
                "category": "document",
                "document_id": document_id,
                "title": doc_title,
                "scope": {
                    "type": scope_type,
                    "id": scope_id,
                    "name": scope_name
                },
                "chunk_ids": doc_info['chunk_ids'],
                "classification": doc_info['classification']
            }
            current_tags[doc_key] = doc_tag

    # Add semantic tags based on user message content (avoid duplicates)
    semantic_keywords = _extract_semantic_keywords(user_message)
    for keyword in semantic_keywords:
        semantic_key = ('semantic', keyword)
        if semantic_key not in current_tags:
            semantic_tag = {
                "category": "semantic",
                "value": keyword
            }
            current_tags[semantic_key] = semantic_tag    # Update the tags array
    conversation_item['tags'] = list(current_tags.values())
    
    return conversation_item


def _determine_document_scope(doc, user_id, active_group_id):
    """
    Determine the scope and ID for a document based on its properties.
    
    Args:
        doc: Document from search results
        user_id: Current user ID
        active_group_id: Active group ID if any
        
    Returns:
        dict: Scope information with 'scope' and 'id' keys
    """
    # Check if it's a public document
    if doc.get('public_workspace_id'):
        return {
            "scope": "public",
            "id": doc.get('public_workspace_id')
        }
    
    # Check if it's a group document
    if doc.get('group_id'):
        return {
            "scope": "group", 
            "id": doc.get('group_id')
        }
    
    # Default to personal
    return {
        "scope": "personal",
        "id": doc.get('user_id', user_id)
    }


def _extract_semantic_keywords(message, max_keywords=5):
    """
    Extract semantic keywords from a user message.
    This is a basic implementation - could be enhanced with NLP libraries.
    
    Args:
        message: User message text
        max_keywords: Maximum number of keywords to extract
        
    Returns:
        list: List of semantic keywords
    """
    # Basic keyword extraction - remove common words and short words
    common_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by',
        'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him',
        'her', 'us', 'them', 'my', 'your', 'his', 'hers', 'its', 'our', 'their', 'am', 'is', 'are',
        'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
        'would', 'could', 'should', 'may', 'might', 'can', 'what', 'where', 'when', 'why', 'how',
        'who', 'which', 'there', 'here', 'then', 'now', 'if', 'so', 'than', 'very', 'just', 'only',
        'also', 'even', 'still', 'much', 'many', 'some', 'any', 'all', 'each', 'every', 'no', 'not'
    }
    
    # Clean and tokenize the message
    import re
    words = re.findall(r'\b[a-zA-Z]+\b', message.lower())
    
    # Filter out common words and short words
    keywords = [word for word in words if len(word) > 3 and word not in common_words]
    
    # Get word frequency
    word_freq = {}
    for word in keywords:
        word_freq[word] = word_freq.get(word, 0) + 1
    
    # Sort by frequency and return top keywords
    sorted_keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
    return [word for word, freq in sorted_keywords[:max_keywords]]


def update_conversation_with_metadata(conversation_id, metadata_updates):
    """
    Update a conversation document with new metadata.
    
    Args:
        conversation_id: The conversation ID to update
        metadata_updates: Dictionary containing the metadata to update
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Read the existing conversation
        conversation_item = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id
        )
        
        # Update with new metadata
        conversation_item.update(metadata_updates)
        conversation_item['last_updated'] = datetime.utcnow().isoformat()
        
        # Upsert back to Cosmos
        cosmos_conversations_container.upsert_item(conversation_item)
        
        return True
        
    except Exception as e:
        print(f"Error updating conversation metadata for {conversation_id}: {e}")
        return False


def get_conversation_metadata(conversation_id):
    """
    Retrieve conversation metadata.
    
    Args:
        conversation_id: The conversation ID
        
    Returns:
        dict: Conversation metadata or None if not found
    """
    try:
        conversation_item = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id
        )
        return conversation_item
        
    except Exception as e:
        print(f"Error retrieving conversation metadata for {conversation_id}: {e}")
        return None
