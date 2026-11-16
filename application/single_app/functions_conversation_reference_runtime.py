# functions_conversation_reference_runtime.py
"""Operation-bound wiring for private conversation references; no startup client creation."""

from functions_conversation_references import ConversationReferenceService


def get_conversation_reference_service():
    # Config owns these clients; resolve them only after web/scheduler bootstrap completes.
    from config import cosmos_conversations_container, cosmos_messages_container
    from functions_chat_content_review import checked_history_messages

    return ConversationReferenceService(
        cosmos_conversations_container,
        cosmos_messages_container,
        project_messages=lambda messages: checked_history_messages(messages, for_model=True),
    )


def authorize_private_conversation(user_id, conversation_id):
    return get_conversation_reference_service().authorize(user_id, conversation_id)


def search_conversation_references(user_id, query="", offset=0, limit=10, search_content=False, exclude_conversation_id=None):
    return get_conversation_reference_service().search(
        user_id, query, offset=offset, limit=limit, search_content=search_content,
        exclude_conversation_id=exclude_conversation_id,
    )


def resolve_conversation_references(user_id, references, query="", destination_id=None, max_tokens=4000):
    return get_conversation_reference_service().resolve(
        user_id, references, query, destination_id=destination_id, max_tokens=max_tokens,
    )
