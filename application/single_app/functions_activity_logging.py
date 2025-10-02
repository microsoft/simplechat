"""
Activity logging functions for tracking chat and user interactions.
This module provides functions to log various types of user activity
for analytics and monitoring purposes.
"""

import logging
from datetime import datetime
from typing import Optional
from functions_appinsights import log_event
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
