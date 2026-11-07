# functions_action_credential_conversations.py
"""Credential-specific conversation routing; storage and policies come from bootstrap."""

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from action_credential_contracts import ActionCredentialError
from cosmos_document_utils import normalize_cosmos_document


class CredentialConversations:
    def __init__(self, *, personal_container, shared_container, message_container,
                 authorize_personal, authorize_shared, authorize_orchestration):
        self.personal = personal_container
        self.shared = shared_container
        self.messages = message_container
        self.authorize_personal = authorize_personal
        self.authorize_shared = authorize_shared
        self.authorize_orchestration = authorize_orchestration

    @staticmethod
    def _read(container, item_id, partition):
        try:
            return normalize_cosmos_document(container.read_item(item=item_id, partition_key=partition))
        except CosmosResourceNotFoundError:
            return None

    @staticmethod
    def _linked(source, shared):
        return bool(
            source
            and source.get("conversation_kind") == "collaboration_source"
            and source.get("collaboration_conversation_id") == shared["id"]
            and source.get("user_id") == shared.get("created_by_user_id")
            and source.get("id") in {shared["id"], shared.get("source_conversation_id")}
        )

    def resolve(self, user_id, conversation_id):
        if not isinstance(conversation_id, str) or not conversation_id.strip() or not user_id:
            raise LookupError("Conversation not found.")
        source = self._read(self.personal, conversation_id, conversation_id)
        shared_id = (source or {}).get("collaboration_conversation_id")
        if source is not None and not shared_id:
            self.authorize_personal(user_id, conversation_id)
            return source
        shared_id = shared_id or conversation_id
        shared = self._read(self.shared, shared_id, shared_id)
        if shared is None or shared.get("status") != "active":
            raise LookupError("Conversation not found.")
        self.authorize_shared(user_id, shared)
        if source is not None and not self._linked(source, shared):
            raise LookupError("Conversation not found.")
        execution_ids = []
        source_id = shared.get("source_conversation_id")
        if source_id:
            backing = source if source and source["id"] == source_id else self._read(self.personal, source_id, source_id)
            if not self._linked(backing, shared):
                raise LookupError("Conversation not found.")
            execution_ids.append(source_id)
        if shared.get("created_by_user_id") == user_id:
            backing = source if source and source["id"] == shared_id else self._read(self.personal, shared_id, shared_id)
            if backing is not None:
                if not self._linked(backing, shared):
                    raise LookupError("Conversation not found.")
                self.authorize_orchestration(shared, user_id)
                execution_ids.append(shared_id)
        return {
            "id": conversation_id,
            "credential_visible_conversation_id": shared_id,
            "credential_conversation_kind": "collaborative",
            "credential_execution_ids": tuple(dict.fromkeys(execution_ids)),
        }

    def chat_origin(self, user_id, conversation_id, message_id):
        context = self.resolve(user_id, conversation_id)
        visible_id = context.get("credential_visible_conversation_id")
        if not visible_id or not message_id or conversation_id == visible_id:
            raise ActionCredentialError("credential_continuation_unavailable")
        message = self._read(self.messages, message_id, visible_id)
        metadata = (message or {}).get("metadata") or {}
        if (
            not message or message.get("conversation_id") != visible_id
            or (metadata.get("sender") or {}).get("user_id") != user_id
            or metadata.get("source_conversation_id") != conversation_id
            or message.get("message_kind") != "ai_request"
            or message.get("is_deleted") or metadata.get("is_deleted")
        ):
            raise ActionCredentialError("credential_continuation_unavailable")
        return {"visible_conversation_id": visible_id, "collaboration_message_id": message_id}

    def authorize_request(self, user_id, item):
        context = self.resolve(user_id, item["conversation_id"])
        if context.get("credential_conversation_kind") != "collaborative":
            return context
        if item["conversation_id"] not in context["credential_execution_ids"]:
            raise LookupError("Conversation not found.")
        descriptor = item.get("continuation") or {}
        if descriptor.get("mode") == "chat":
            origin = self.chat_origin(user_id, item["conversation_id"], descriptor.get("collaboration_message_id"))
            if origin["visible_conversation_id"] != descriptor.get("visible_conversation_id"):
                raise ActionCredentialError("credential_continuation_unavailable")
        else:
            if descriptor.get("mode") != "orchestration" or item["conversation_id"] != context["credential_visible_conversation_id"]:
                raise ActionCredentialError("credential_continuation_unavailable")
            shared = self._read(self.shared, context["credential_visible_conversation_id"], context["credential_visible_conversation_id"])
            if shared is None:
                raise LookupError("Conversation not found.")
            self.authorize_orchestration(shared, user_id)
        return context
