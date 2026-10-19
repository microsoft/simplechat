# functions_action_credential_runtime.py
"""Web/scheduler composition of credential services after runtime initialization."""

from action_credential_contracts import ActionCredentialError
from functions_action_credential_conversations import CredentialConversations
import functions_action_credentials as credentials
import functions_action_credential_continuation as continuation


def configure_action_credential_runtime():
    # Owners are imported only by initialized web/scheduler composition. Lower
    # credential modules never import these owners, even through deferred imports.
    import functions_action_catalog
    import functions_agent_delegation
    import functions_authentication
    import functions_settings
    import functions_workspace_identities as identities
    import route_backend_chats
    from content_screening import access
    from flask import has_request_context, request

    def authorize_shared(user_id, shared):
        # Collaboration initializes storage; only initialized runtime callbacks load it.
        from functions_collaboration import assert_user_can_participate_in_collaboration_conversation

        return assert_user_can_participate_in_collaboration_conversation(user_id, shared, read_only=True)

    def authorize_orchestration(shared, user_id):
        from functions_orchestration_collaboration import authorize_shared_orchestration

        return authorize_shared_orchestration(shared, user_id, read_only=True)

    from config import cosmos_collaboration_conversations_container, cosmos_collaboration_messages_container

    conversations = CredentialConversations(
        personal_container=route_backend_chats.cosmos_conversations_container,
        shared_container=cosmos_collaboration_conversations_container,
        message_container=cosmos_collaboration_messages_container,
        authorize_personal=route_backend_chats._authorize_personal_conversation_access,
        authorize_shared=authorize_shared, authorize_orchestration=authorize_orchestration,
    )

    def capture_chat_origin(user_id, conversation_id):
        data = request.get_json(silent=True) if has_request_context() else None
        message_id = data.get("m365_collaboration_message_id") if isinstance(data, dict) else None
        return conversations.chat_origin(user_id, conversation_id, message_id) if message_id else {}

    def publish_chat_result(user_id, item, saved):
        context = conversations.authorize_request(user_id, item)
        if context.get("credential_conversation_kind") != "collaborative":
            return saved
        from functions_collaboration import (
            create_collaboration_message_notifications, get_collaboration_conversation,
            mirror_source_message_to_collaboration, publish_collaboration_event,
            serialize_collaboration_conversation, serialize_collaboration_message,
        )

        visible_id = context["credential_visible_conversation_id"]
        shared = get_collaboration_conversation(visible_id)
        authorize_shared(user_id, shared)
        question = conversations._read(
            conversations.messages, item["continuation"]["collaboration_message_id"], visible_id,
        )
        sender = (question["metadata"] or {})["sender"]
        message, shared, _created = mirror_source_message_to_collaboration(
            shared, saved, sender, reply_to_message_id=question["id"],
            extra_metadata={"source_thought_user_id": user_id},
            message_id="shared_" + saved["id"],
        )
        if not message:
            raise ActionCredentialError("credential_publication_unavailable", 503)
        authorize_shared(user_id, shared)
        create_collaboration_message_notifications(shared, message)
        serialized = serialize_collaboration_message(message)
        publish_collaboration_event(visible_id, {
            "conversation_id": visible_id, "event_type": "collaboration.message.created",
            "payload": {
                "conversation": serialize_collaboration_conversation(shared, current_user_id=user_id),
                "message": serialized,
            },
        })
        return serialized

    def resolve_manifest(user_id, action_ref):
        scope_type, scope_id, action_id = action_ref.split(":", 2)
        catalog_ref = functions_action_catalog._action_ref(scope_type, scope_id, action_id)
        user = functions_authentication.get_current_user_info() or {}
        return functions_action_catalog.resolve_action_manifest(
            user_id, catalog_ref, settings=functions_settings.get_settings(), user_roles=user.get("roles") or [],
        )

    def resolve_agent(reference, *, user_id):
        return functions_agent_delegation.resolve_delegation_agent(
            reference, user_id=user_id, settings=functions_settings.get_settings(),
        )

    def update_identity(*args, **kwargs):
        try:
            return identities.update_workspace_identity_conditional(*args, **kwargs)
        except identities.WorkspaceIdentityConflict:
            raise ActionCredentialError("identity_changed") from None

    credentials.configure_action_credential_services(credentials.CredentialServices(
        current_user_id=functions_authentication.get_current_user_id_or_none,
        authorize_conversation=conversations.resolve,
        resolve_manifest=resolve_manifest,
        read_identity=identities.get_workspace_identity,
        list_identities=identities.list_workspace_identities,
        identity_supports_usage=identities.identity_supports_usage,
        read_identity_auth=identities.get_workspace_identity_auth,
        create_identity=identities.create_workspace_identity,
        update_identity=update_identity,
        authorize_request_context=conversations.authorize_request,
        capture_chat_origin=capture_chat_origin,
        publish_chat_result=publish_chat_result,
    ))
    continuation.configure_action_credential_continuation_services(continuation.CredentialContinuationServices(
        collect_sources=access.current_request_source_provenance,
        authorize_source=access.assert_document_available,
        resolve_agent=resolve_agent,
    ))
