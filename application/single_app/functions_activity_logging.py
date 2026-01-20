"""
Activity logging functions for tracking chat and user interactions.
This module provides functions to log various types of user activity
for analytics and monitoring purposes.
"""

import logging
import uuid
from datetime import datetime
from typing import Optional
from functions_appinsights import log_event
from functions_debug import debug_print
from config import cosmos_activity_logs_container

def log_chat_activity(
    user_id: str,
    conversation_id: str,
    message_type: str,
    message_length: int = 0,
    has_document_search: bool = False,
    has_image_generation: bool = False,
    document_scope: Optional[str] = None,
    chat_context: Optional[str] = None
) -> None:
    """
    Log chat activity for monitoring. 
    Chat data is already stored in conversations/messages containers.
    
    Args:
        user_id (str): The ID of the user performing the action
        conversation_id (str): The ID of the conversation
        message_type (str): Type of message (e.g., 'user_message', 'assistant_message')
        message_length (int, optional): Length of the message content
        has_document_search (bool, optional): Whether document search was used
        has_image_generation (bool, optional): Whether image generation was used
        document_scope (str, optional): Scope of document search if used
        chat_context (str, optional): Context or type of chat session
    """
    
    try:        
        # Log to Application Insights for monitoring
        log_event(
            message=f"Chat activity: {message_type} for user {user_id}",
            extra={
                'user_id': user_id,
                'conversation_id': conversation_id,
                'message_type': message_type,
                'message_length': message_length,
                'has_document_search': has_document_search,
                'has_image_generation': has_image_generation,
                'document_scope': document_scope,
                'chat_context': chat_context,
                'activity_type': 'chat_activity'
            },
            level=logging.INFO
        )
        debug_print(f"Logged chat activity: {message_type} for user {user_id}")
        
    except Exception as e:
        # Log error but don't break the chat flow
        log_event(
            message=f"Error logging chat activity: {str(e)}",
            extra={
                'user_id': user_id,
                'conversation_id': conversation_id,
                'error': str(e)
            },
            level=logging.ERROR
        )
        debug_print(f"Error logging chat activity for user {user_id}: {str(e)}")


def log_user_activity(
    user_id: str,
    activity_type: str,
    activity_details: Optional[dict] = None
) -> None:
    """
    Log general user activity for analytics and monitoring.
    
    Args:
        user_id (str): The ID of the user performing the action
        activity_type (str): Type of activity (e.g., 'login', 'logout', 'file_upload')
        activity_details (dict, optional): Additional details about the activity
    """
    
    try:
        # Create activity data
        activity_data = {
            'user_id': user_id,
            'activity_type': activity_type,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Add additional details if provided
        if activity_details:
            activity_data.update(activity_details)
        
        # Log to Application Insights
        log_event(
            message=f"User activity logged: {activity_type} for user {user_id}",
            extra=activity_data,
            level=logging.INFO
        )
        debug_print(f"Logged user activity: {activity_type} for user {user_id}")
        
    except Exception as e:
        # Log error but don't break the user flow
        log_event(
            message=f"Error logging user activity: {str(e)}",
            extra={
                'user_id': user_id,
                'activity_type': activity_type,
                'error': str(e)
            },
            level=logging.ERROR
        )
        debug_print(f"Error logging user activity for user {user_id}: {str(e)}")


def log_document_upload(
    user_id: str,
    container_type: str,
    document_id: str,
    file_size: int = 0,
    file_type: Optional[str] = None
) -> None:
    """
    Log document upload activity for monitoring.
    Document data is already stored in documents containers.
    
    Args:
        user_id (str): The ID of the user uploading the document
        container_type (str): Type of container ('personal', 'group', 'public')
        document_id (str): The ID of the uploaded document
        file_size (int, optional): Size of the uploaded file in bytes
        file_type (str, optional): Type/extension of the uploaded file
    """
    
    try:
        # Log to Application Insights for monitoring
        log_event(
            message=f"Document upload: {file_type} ({file_size} bytes) for user {user_id}",
            extra={
                'user_id': user_id,
                'container_type': container_type,
                'document_id': document_id,
                'file_size': file_size,
                'file_type': file_type,
                'activity_type': 'document_upload'
            },
            level=logging.INFO
        )
        debug_print(f"Logged document upload for user {user_id}")
        
    except Exception as e:
        # Log error but don't break the upload flow
        log_event(
            message=f"Error logging document upload activity: {str(e)}",
            extra={
                'user_id': user_id,
                'document_id': document_id,
                'error': str(e)
            },
            level=logging.ERROR
        )
        debug_print(f"Error logging document upload for user {user_id}: {str(e)}")


def log_document_creation_transaction(
    user_id: str,
    document_id: str,
    workspace_type: str,
    file_name: str,
    file_type: Optional[str] = None,
    file_size: Optional[int] = None,
    page_count: Optional[int] = None,
    embedding_tokens: Optional[int] = None,
    embedding_model: Optional[str] = None,
    version: Optional[int] = None,
    author: Optional[str] = None,
    title: Optional[str] = None,
    subject: Optional[str] = None,
    publication_date: Optional[str] = None,
    keywords: Optional[list] = None,
    abstract: Optional[str] = None,
    group_id: Optional[str] = None,
    public_workspace_id: Optional[str] = None,
    additional_metadata: Optional[dict] = None
) -> None:
    """
    Log comprehensive document creation transaction to activity_logs container.
    This creates a permanent record of the document creation that persists even if the document is deleted.
    
    Args:
        user_id (str): The ID of the user who created the document
        document_id (str): The ID of the created document
        workspace_type (str): Type of workspace ('personal', 'group', 'public')
        file_name (str): Name of the uploaded file
        file_type (str, optional): File extension/type (.pdf, .docx, etc.)
        file_size (int, optional): Size of the file in bytes
        page_count (int, optional): Number of pages/chunks processed
        embedding_tokens (int, optional): Total embedding tokens used
        embedding_model (str, optional): Embedding model deployment name
        version (int, optional): Document version
        author (str, optional): Document author (from metadata)
        title (str, optional): Document title (from metadata)
        subject (str, optional): Document subject (from metadata)
        publication_date (str, optional): Document publication date (from metadata)
        keywords (list, optional): Document keywords (from metadata)
        abstract (str, optional): Document abstract (from metadata)
        group_id (str, optional): Group ID if group workspace
        public_workspace_id (str, optional): Public workspace ID if public workspace
        additional_metadata (dict, optional): Any additional metadata to store
    """
    
    try:
        import uuid
        
        # Create comprehensive activity log record
        activity_record = {
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'activity_type': 'document_creation',
            'workspace_type': workspace_type,
            'timestamp': datetime.utcnow().isoformat(),
            'created_at': datetime.utcnow().isoformat(),
            'document': {
                'document_id': document_id,
                'file_name': file_name,
                'file_type': file_type,
                'file_size_bytes': file_size,
                'page_count': page_count,
                'version': version
            },
            'embedding_usage': {
                'total_tokens': embedding_tokens,
                'model_deployment_name': embedding_model
            },
            'document_metadata': {
                'author': author,
                'title': title,
                'subject': subject,
                'publication_date': publication_date,
                'keywords': keywords or [],
                'abstract': abstract
            },
            'workspace_context': {}
        }
        
        # Add workspace-specific context
        if workspace_type == 'group' and group_id:
            activity_record['workspace_context']['group_id'] = group_id
        elif workspace_type == 'public' and public_workspace_id:
            activity_record['workspace_context']['public_workspace_id'] = public_workspace_id
            
        # Add any additional metadata
        if additional_metadata:
            activity_record['additional_metadata'] = additional_metadata
            
        # Save to activity_logs container for permanent record
        cosmos_activity_logs_container.create_item(body=activity_record)
        
        # Also log to Application Insights for monitoring
        log_event(
            message=f"Document creation transaction logged: {file_name} ({file_type}) for user {user_id}",
            extra=activity_record,
            level=logging.INFO
        )
        debug_print(f"Logged document creation transaction: {document_id} for user {user_id}")

        
    except Exception as e:
        # Log error but don't break the document creation flow
        log_event(
            message=f"Error logging document creation transaction: {str(e)}",
            extra={
                'user_id': user_id,
                'document_id': document_id,
                'workspace_type': workspace_type,
                'error': str(e)
            },
            level=logging.ERROR
        )
        debug_print(f"Error logging document creation transaction for user {user_id}: {str(e)}")


def log_document_deletion_transaction(
    user_id: str,
    document_id: str,
    workspace_type: str,
    file_name: str,
    file_type: Optional[str] = None,
    page_count: Optional[int] = None,
    version: Optional[int] = None,
    group_id: Optional[str] = None,
    public_workspace_id: Optional[str] = None,
    document_metadata: Optional[dict] = None
) -> None:
    """
    Log document deletion transaction to activity_logs container.
    This creates a permanent record of the document deletion.
    
    Args:
        user_id (str): The ID of the user who deleted the document
        document_id (str): The ID of the deleted document
        workspace_type (str): Type of workspace ('personal', 'group', 'public')
        file_name (str): Name of the deleted file
        file_type (str, optional): File extension/type (.pdf, .docx, etc.)
        page_count (int, optional): Number of pages/chunks that were stored
        version (int, optional): Document version
        group_id (str, optional): Group ID if group workspace
        public_workspace_id (str, optional): Public workspace ID if public workspace
        document_metadata (dict, optional): Full document metadata for reference
    """
    
    try:
        import uuid
        
        # Create deletion activity log record
        activity_record = {
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'activity_type': 'document_deletion',
            'workspace_type': workspace_type,
            'timestamp': datetime.utcnow().isoformat(),
            'created_at': datetime.utcnow().isoformat(),
            'document': {
                'document_id': document_id,
                'file_name': file_name,
                'file_type': file_type,
                'page_count': page_count,
                'version': version
            },
            'workspace_context': {}
        }
        
        # Add workspace-specific context
        if workspace_type == 'group' and group_id:
            activity_record['workspace_context']['group_id'] = group_id
        elif workspace_type == 'public' and public_workspace_id:
            activity_record['workspace_context']['public_workspace_id'] = public_workspace_id
            
        # Add full document metadata if provided
        if document_metadata:
            activity_record['deleted_document_metadata'] = document_metadata
            
        # Save to activity_logs container for permanent record
        cosmos_activity_logs_container.create_item(body=activity_record)
        
        # Also log to Application Insights for monitoring
        log_event(
            message=f"Document deletion transaction logged: {file_name} ({file_type}) for user {user_id}",
            extra=activity_record,
            level=logging.INFO
        )
        
        debug_print(f"Logged document deletion transaction: {document_id} for user {user_id}")
        
    except Exception as e:
        # Log error but don't break the document deletion flow
        log_event(
            message=f"Error logging document deletion transaction: {str(e)}",
            extra={
                'user_id': user_id,
                'document_id': document_id,
                'workspace_type': workspace_type,
                'error': str(e)
            },
            level=logging.ERROR
        )
        debug_print(f"Error logging document deletion transaction for user {user_id}: {str(e)}")


def log_document_metadata_update_transaction(
    user_id: str,
    document_id: str,
    workspace_type: str,
    file_name: str,
    updated_fields: dict,
    file_type: Optional[str] = None,
    group_id: Optional[str] = None,
    public_workspace_id: Optional[str] = None,
    additional_metadata: Optional[dict] = None
) -> None:
    """
    Log document metadata update transaction to activity_logs container.
    This creates a permanent record of metadata modifications.
    
    Args:
        user_id (str): The ID of the user who updated the metadata
        document_id (str): The ID of the updated document
        workspace_type (str): Type of workspace ('personal', 'group', 'public')
        file_name (str): Name of the document file
        updated_fields (dict): Dictionary of fields that were updated with their new values
        file_type (str, optional): File extension/type (.pdf, .docx, etc.)
        group_id (str, optional): Group ID if group workspace
        public_workspace_id (str, optional): Public workspace ID if public workspace
        additional_metadata (dict, optional): Any additional metadata to store
    """
    
    try:
        import uuid
        
        # Create metadata update activity log record
        activity_record = {
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'activity_type': 'document_metadata_update',
            'workspace_type': workspace_type,
            'timestamp': datetime.utcnow().isoformat(),
            'created_at': datetime.utcnow().isoformat(),
            'document': {
                'document_id': document_id,
                'file_name': file_name,
                'file_type': file_type
            },
            'updated_fields': updated_fields,
            'workspace_context': {}
        }
        
        # Add workspace-specific context
        if workspace_type == 'group' and group_id:
            activity_record['workspace_context']['group_id'] = group_id
        elif workspace_type == 'public' and public_workspace_id:
            activity_record['workspace_context']['public_workspace_id'] = public_workspace_id
            
        # Add any additional metadata
        if additional_metadata:
            activity_record['additional_metadata'] = additional_metadata
            
        # Save to activity_logs container for permanent record
        cosmos_activity_logs_container.create_item(body=activity_record)
        
        # Also log to Application Insights for monitoring
        log_event(
            message=f"Document metadata update transaction logged: {file_name} for user {user_id}",
            extra=activity_record,
            level=logging.INFO
        )
        
        debug_print(f"Logged document metadata update transaction: {document_id} for user {user_id}")
        
    except Exception as e:
        # Log error but don't break the document update flow
        log_event(
            message=f"Error logging document metadata update transaction: {str(e)}",
            extra={
                'user_id': user_id,
                'document_id': document_id,
                'workspace_type': workspace_type,
                'error': str(e)
            },
            level=logging.ERROR
        )
        debug_print(f"Error logging document metadata update transaction for user {user_id}: {str(e)}")


def log_token_usage(
    user_id: str,
    token_type: str,
    total_tokens: int,
    model: str,
    workspace_type: Optional[str] = None,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    document_id: Optional[str] = None,
    file_name: Optional[str] = None,
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    group_id: Optional[str] = None,
    public_workspace_id: Optional[str] = None,
    additional_context: Optional[dict] = None
) -> None:
    """
    Log token usage to activity_logs container for easy reporting and analytics.
    Supports both embedding tokens (document processing) and chat tokens (conversations).
    
    Args:
        user_id (str): The ID of the user whose action consumed tokens
        token_type (str): Type of token usage ('embedding' or 'chat')
        total_tokens (int): Total tokens consumed
        model (str): Model deployment name used
        workspace_type (str, optional): Type of workspace ('personal', 'group', 'public')
        prompt_tokens (int, optional): Prompt tokens (for chat)
        completion_tokens (int, optional): Completion tokens (for chat)
        document_id (str, optional): Document ID (for embedding)
        file_name (str, optional): File name (for embedding)
        conversation_id (str, optional): Conversation ID (for chat)
        message_id (str, optional): Message ID (for chat)
        group_id (str, optional): Group ID if group workspace
        public_workspace_id (str, optional): Public workspace ID if public workspace
        additional_context (dict, optional): Any additional context to store
    """
    
    try:
        import uuid
        
        # Create token usage activity log record
        activity_record = {
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'activity_type': 'token_usage',
            'token_type': token_type,
            'timestamp': datetime.utcnow().isoformat(),
            'created_at': datetime.utcnow().isoformat(),
            'usage': {
                'total_tokens': total_tokens,
                'model': model
            },
            'workspace_type': workspace_type,
            'workspace_context': {}
        }
        
        # Add token type specific details
        if token_type == 'embedding':
            activity_record['embedding_details'] = {
                'document_id': document_id,
                'file_name': file_name
            }
        elif token_type == 'chat':
            activity_record['usage']['prompt_tokens'] = prompt_tokens
            activity_record['usage']['completion_tokens'] = completion_tokens
            activity_record['chat_details'] = {
                'conversation_id': conversation_id,
                'message_id': message_id
            }
        
        # Add workspace-specific context
        if group_id:
            activity_record['workspace_context']['group_id'] = group_id
        if public_workspace_id:
            activity_record['workspace_context']['public_workspace_id'] = public_workspace_id
            
        # Add any additional context
        if additional_context:
            activity_record['additional_context'] = additional_context
            
        # Save to activity_logs container
        cosmos_activity_logs_container.create_item(body=activity_record)
        
        # Also log to Application Insights for monitoring
        log_event(
            message=f"Token usage logged: {token_type} - {total_tokens} tokens ({model})",
            extra=activity_record,
            level=logging.INFO
        )
        debug_print(f"Logged token usage: {token_type} - {total_tokens} tokens for user {user_id}")
        
    except Exception as e:
        # Log error but don't break the flow
        log_event(
            message=f"Error logging token usage: {str(e)}",
            extra={
                'user_id': user_id,
                'token_type': token_type,
                'total_tokens': total_tokens,
                'error': str(e)
            },
            level=logging.ERROR
        )
        debug_print(f"Error logging token usage for user {user_id}: {str(e)}")


def log_conversation_creation(
    user_id: str,
    conversation_id: str,
    title: str,
    workspace_type: str = 'personal',
    context: list = None,
    tags: list = None,
    group_id: str = None,
    public_workspace_id: str = None,
    additional_context: dict = None
) -> None:
    """
    Log conversation creation to the activity_logs container.
    
    Args:
        user_id (str): The ID of the user creating the conversation
        conversation_id (str): The unique ID of the conversation
        title (str): The conversation title
        workspace_type (str, optional): Type of workspace ('personal', 'group', 'public')
        context (list, optional): Conversation context array
        tags (list, optional): Conversation tags array
        group_id (str, optional): Group ID if in group workspace
        public_workspace_id (str, optional): Public workspace ID if applicable
        additional_context (dict, optional): Any additional context information
    """
    try:
        # Build activity log
        activity_log = {
            'id': str(uuid.uuid4()),
            'activity_type': 'conversation_creation',
            'user_id': user_id,
            'timestamp': datetime.utcnow().isoformat(),
            'conversation': {
                'conversation_id': conversation_id,
                'title': title,
                'context': context or [],
                'tags': tags or []
            },
            'workspace_type': workspace_type,
            'workspace_context': {}
        }
        
        # Add workspace-specific context
        if workspace_type == 'group' and group_id:
            activity_log['workspace_context']['group_id'] = group_id
        elif workspace_type == 'public' and public_workspace_id:
            activity_log['workspace_context']['public_workspace_id'] = public_workspace_id
        
        # Add additional context if provided
        if additional_context:
            activity_log['additional_context'] = additional_context
        
        # Save to activity logs container
        cosmos_activity_logs_container.upsert_item(activity_log)
        
        debug_print(f"✅ Logged conversation creation: {conversation_id}")
        
    except Exception as e:
        # Non-blocking error handling
        debug_print(f"⚠️ Error logging conversation creation: {str(e)}")
        log_event(
            message=f"Error logging conversation creation: {str(e)}",
            extra={
                'user_id': user_id,
                'conversation_id': conversation_id,
                'error': str(e)
            },
            level=logging.ERROR
        )


def log_conversation_deletion(
    user_id: str,
    conversation_id: str,
    title: str,
    workspace_type: str = 'personal',
    context: list = None,
    tags: list = None,
    is_archived: bool = False,
    is_bulk_operation: bool = False,
    group_id: str = None,
    public_workspace_id: str = None,
    additional_context: dict = None
) -> None:
    """
    Log conversation deletion to the activity_logs container.
    
    Args:
        user_id (str): The ID of the user deleting the conversation
        conversation_id (str): The unique ID of the conversation
        title (str): The conversation title
        workspace_type (str, optional): Type of workspace ('personal', 'group', 'public')
        context (list, optional): Conversation context array
        tags (list, optional): Conversation tags array
        is_archived (bool, optional): Whether the conversation was archived before deletion
        is_bulk_operation (bool, optional): Whether this is part of a bulk deletion
        group_id (str, optional): Group ID if in group workspace
        public_workspace_id (str, optional): Public workspace ID if applicable
        additional_context (dict, optional): Any additional context information
    """
    try:
        # Build activity log
        activity_log = {
            'id': str(uuid.uuid4()),
            'activity_type': 'conversation_deletion',
            'user_id': user_id,
            'timestamp': datetime.utcnow().isoformat(),
            'conversation': {
                'conversation_id': conversation_id,
                'title': title,
                'context': context or [],
                'tags': tags or []
            },
            'deletion_details': {
                'is_archived': is_archived,
                'is_bulk_operation': is_bulk_operation
            },
            'workspace_type': workspace_type,
            'workspace_context': {}
        }
        
        # Add workspace-specific context
        if workspace_type == 'group' and group_id:
            activity_log['workspace_context']['group_id'] = group_id
        elif workspace_type == 'public' and public_workspace_id:
            activity_log['workspace_context']['public_workspace_id'] = public_workspace_id
        
        # Add additional context if provided
        if additional_context:
            activity_log['additional_context'] = additional_context
        
        # Save to activity logs container
        cosmos_activity_logs_container.upsert_item(activity_log)
        
        debug_print(f"✅ Logged conversation deletion: {conversation_id} (archived: {is_archived}, bulk: {is_bulk_operation})")
        
    except Exception as e:
        # Non-blocking error handling
        debug_print(f"⚠️ Error logging conversation deletion: {str(e)}")
        log_event(
            message=f"Error logging conversation deletion: {str(e)}",
            extra={
                'user_id': user_id,
                'conversation_id': conversation_id,
                'error': str(e)
            },
            level=logging.ERROR
        )


def log_conversation_archival(
    user_id: str,
    conversation_id: str,
    title: str,
    workspace_type: str = 'personal',
    context: list = None,
    tags: list = None,
    group_id: str = None,
    public_workspace_id: str = None,
    additional_context: dict = None
) -> None:
    """
    Log conversation archival to the activity_logs container.
    
    Args:
        user_id (str): The ID of the user archiving the conversation
        conversation_id (str): The unique ID of the conversation
        title (str): The conversation title
        workspace_type (str, optional): Type of workspace ('personal', 'group', 'public')
        context (list, optional): Conversation context array
        tags (list, optional): Conversation tags array
        group_id (str, optional): Group ID if in group workspace
        public_workspace_id (str, optional): Public workspace ID if applicable
        additional_context (dict, optional): Any additional context information
    """
    try:
        # Build activity log
        activity_log = {
            'id': str(uuid.uuid4()),
            'activity_type': 'conversation_archival',
            'user_id': user_id,
            'timestamp': datetime.utcnow().isoformat(),
            'conversation': {
                'conversation_id': conversation_id,
                'title': title,
                'context': context or [],
                'tags': tags or []
            },
            'workspace_type': workspace_type,
            'workspace_context': {}
        }
        
        # Add workspace-specific context
        if workspace_type == 'group' and group_id:
            activity_log['workspace_context']['group_id'] = group_id
        elif workspace_type == 'public' and public_workspace_id:
            activity_log['workspace_context']['public_workspace_id'] = public_workspace_id
        
        # Add additional context if provided
        if additional_context:
            activity_log['additional_context'] = additional_context
        
        # Save to activity logs container
        cosmos_activity_logs_container.upsert_item(activity_log)
        
        debug_print(f"✅ Logged conversation archival: {conversation_id}")
        
    except Exception as e:
        # Non-blocking error handling
        debug_print(f"⚠️ Error logging conversation archival: {str(e)}")
        log_event(
            message=f"Error logging conversation archival: {str(e)}",
            extra={
                'user_id': user_id,
                'conversation_id': conversation_id,
                'error': str(e)
            },
            level=logging.ERROR
        )


def log_user_login(
    user_id: str,
    login_method: str = 'azure_ad'
) -> None:
    """
    Log user login activity to the activity_logs container.
    
    Args:
        user_id (str): The ID of the user logging in
        login_method (str, optional): Method used for login (e.g., 'azure_ad', 'local')
    """
    
    try:
        # Create login activity record
        import uuid
        login_activity = {
            'id': str(uuid.uuid4()),
            'user_id': user_id,
            'activity_type': 'user_login',
            'login_method': login_method,
            'timestamp': datetime.utcnow().isoformat(),
            'created_at': datetime.utcnow().isoformat(),
            'details': {
                'login_method': login_method,
                'success': True
            }
        }
        
        # Save to activity_logs container
        cosmos_activity_logs_container.create_item(body=login_activity)
        
        # Also log to Application Insights for monitoring
        log_event(
            message=f"User login logged for user {user_id}",
            extra=login_activity,
            level=logging.INFO
        )
        debug_print(f"✅ User login activity logged for user {user_id}")
        
    except Exception as e:
        # Log error but don't break the login flow
        log_event(
            message=f"Error logging user login activity: {str(e)}",
            extra={
                'user_id': user_id,
                'login_method': login_method,
                'error': str(e)
            },
            level=logging.ERROR
        )
        debug_print(f"⚠️  Warning: Failed to log user login activity for user {user_id}: {str(e)}")


def log_group_status_change(
    group_id: str,
    group_name: str,
    old_status: str,
    new_status: str,
    changed_by_user_id: str,
    changed_by_email: str,
    reason: Optional[str] = None
) -> None:
    """
    Log group status change to activity_logs container for audit trail.
    
    Args:
        group_id (str): The ID of the group whose status is changing
        group_name (str): The name of the group
        old_status (str): Previous status value
        new_status (str): New status value
        changed_by_user_id (str): User ID of admin who made the change
        changed_by_email (str): Email of admin who made the change
        reason (str, optional): Optional reason for the status change
    """
    
    try:
        import uuid
        
        # Create status change activity record
        status_change_activity = {
            'id': str(uuid.uuid4()),
            'activity_type': 'group_status_change',
            'timestamp': datetime.utcnow().isoformat(),
            'created_at': datetime.utcnow().isoformat(),
            'group': {
                'group_id': group_id,
                'group_name': group_name
            },
            'status_change': {
                'old_status': old_status,
                'new_status': new_status,
                'changed_at': datetime.utcnow().isoformat()
            },
            'changed_by': {
                'user_id': changed_by_user_id,
                'email': changed_by_email
            },
            'workspace_type': 'group',
            'workspace_context': {
                'group_id': group_id
            }
        }
        
        # Add reason if provided
        if reason:
            status_change_activity['status_change']['reason'] = reason
        
        # Save to activity_logs container for permanent audit trail
        cosmos_activity_logs_container.create_item(body=status_change_activity)
        
        # Also log to Application Insights for monitoring
        log_event(
            message=f"Group status changed: {group_name} ({group_id}) from '{old_status}' to '{new_status}' by {changed_by_email}",
            extra=status_change_activity,
            level=logging.INFO
        )
        
        debug_print(f"✅ Group status change logged: {group_id} -> {new_status}")
        
    except Exception as e:
        # Log error but don't break the status update flow
        log_event(
            message=f"Error logging group status change: {str(e)}",
            extra={
                'group_id': group_id,
                'new_status': new_status,
                'changed_by_user_id': changed_by_user_id,
                'error': str(e)
            },
            level=logging.ERROR
        )
        debug_print(f"⚠️  Warning: Failed to log group status change: {str(e)}")


def log_group_member_deleted(
    removed_by_user_id: str,
    removed_by_email: str,
    removed_by_role: str,
    member_user_id: str,
    member_email: str,
    member_name: str,
    group_id: str,
    group_name: str,
    action: str,
    description: Optional[str] = None
) -> None:
    """
    Log group member deletion/removal transaction to activity_logs container.
    This creates a permanent record when users are removed from groups.
    
    Args:
        removed_by_user_id (str): ID of user performing the removal
        removed_by_email (str): Email of user performing the removal
        removed_by_role (str): Role of user performing the removal (Owner, Admin, Member)
        member_user_id (str): ID of the member being removed
        member_email (str): Email of the member being removed
        member_name (str): Display name of the member being removed
        group_id (str): ID of the group
        group_name (str): Name of the group
        action (str): Specific action ('member_left_group' or 'admin_removed_member')
        description (str, optional): Human-readable description of the action
    """
    
    try:
        import uuid
        
        # Create group member deletion activity log record
        activity_record = {
            'id': str(uuid.uuid4()),
            'user_id': removed_by_user_id,  # Person who performed the action (for partitioning)
            'activity_type': 'group_member_deleted',
            'timestamp': datetime.utcnow().isoformat(),
            'created_at': datetime.utcnow().isoformat(),
            'removed_by': {
                'user_id': removed_by_user_id,
                'email': removed_by_email,
                'role': removed_by_role
            },
            'removed_member': {
                'user_id': member_user_id,
                'email': member_email,
                'name': member_name
            },
            'group': {
                'group_id': group_id,
                'group_name': group_name
            },
            'description': description or f"{removed_by_role} removed member from group"
        }
        
        # Save to activity_logs container for permanent record
        cosmos_activity_logs_container.create_item(body=activity_record)
        
        # Also log to Application Insights for monitoring
        log_event(
            message=f"Group member deleted: {member_name} ({member_email}) removed from {group_name}",
            extra=activity_record,
            level=logging.INFO
        )
        
        debug_print(f"✅ Group member deletion logged to activity_logs: {member_user_id} from group {group_id}")
        
    except Exception as e:
        # Log error but don't break the member removal flow
        log_event(
            message=f"Error logging group member deletion: {str(e)}",
            extra={
                'removed_by_user_id': removed_by_user_id,
                'member_user_id': member_user_id,
                'group_id': group_id,
                'error': str(e)
            },
            level=logging.ERROR
        )
        debug_print(f"⚠️  Warning: Failed to log group member deletion: {str(e)}")


def log_public_workspace_status_change(
    workspace_id: str,
    workspace_name: str,
    old_status: str,
    new_status: str,
    changed_by_user_id: str,
    changed_by_email: str,
    reason: Optional[str] = None
) -> None:
    """
    Log public workspace status change to activity_logs container for audit trail.
    
    Args:
        workspace_id (str): The ID of the public workspace whose status is changing
        workspace_name (str): The name of the public workspace
        old_status (str): Previous status value
        new_status (str): New status value
        changed_by_user_id (str): User ID of admin who made the change
        changed_by_email (str): Email of admin who made the change
        reason (str, optional): Optional reason for the status change
    """
    
    try:
        import uuid
        
        # Create status change activity record
        status_change_activity = {
            'id': str(uuid.uuid4()),
            'activity_type': 'public_workspace_status_change',
            'timestamp': datetime.utcnow().isoformat(),
            'created_at': datetime.utcnow().isoformat(),
            'public_workspace': {
                'workspace_id': workspace_id,
                'workspace_name': workspace_name
            },
            'status_change': {
                'old_status': old_status,
                'new_status': new_status,
                'changed_at': datetime.utcnow().isoformat()
            },
            'changed_by': {
                'user_id': changed_by_user_id,
                'email': changed_by_email
            },
            'workspace_type': 'public_workspace',
            'workspace_context': {
                'public_workspace_id': workspace_id
            }
        }
        
        # Add reason if provided
        if reason:
            status_change_activity['status_change']['reason'] = reason
        
        # Save to activity_logs container for permanent audit trail
        cosmos_activity_logs_container.create_item(body=status_change_activity)
        
        # Also log to Application Insights for monitoring
        log_event(
            message=f"Public workspace status changed: {workspace_name} ({workspace_id}) from '{old_status}' to '{new_status}' by {changed_by_email}",
            extra=status_change_activity,
            level=logging.INFO
        )
        
        debug_print(f"✅ Logged public workspace status change: {workspace_name} ({workspace_id}) {old_status} -> {new_status}")
        
    except Exception as e:
        # Log error but don't fail the operation
        log_event(
            message=f"Error logging public workspace status change: {str(e)}",
            extra={
                'workspace_id': workspace_id,
                'old_status': old_status,
                'new_status': new_status,
                'changed_by_user_id': changed_by_user_id,
                'error': str(e)
            },
            level=logging.ERROR
        )
        debug_print(f"⚠️  Warning: Failed to log public workspace status change: {str(e)}")
