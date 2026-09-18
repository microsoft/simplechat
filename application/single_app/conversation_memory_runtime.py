# conversation_memory_runtime.py
"""Application-owned authorization and storage factories for conversation memory."""

from datetime import datetime, timezone
from dataclasses import replace

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError

from config import (
    CLIENTS,
    TENANT_ID,
    build_enhanced_citations_blob_service_client,
    cosmos_conversations_container,
    cosmos_messages_container,
)
from functions_appinsights import log_event
from functions_collaboration import build_conversation_participation_context
from functions_conversation_memory import (
    ConversationMemoryStore,
    MemoryAuthorizationError,
    MemoryContext,
    PublicationGrant,
)
from functions_m365_approvals import get_m365_approval_service
from functions_m365_execution import (
    M365ExecutionContext,
    authorize_m365_publication,
    get_m365_execution_context,
)
from functions_settings import get_settings


MEMORY_ARTIFACT_KIND = "conversation_memory"


def get_chat_memory_blob_client():
    """Use configured chat storage independently from citation display settings."""
    client = CLIENTS.get("storage_account_office_docs_client")
    if client is not None:
        return client
    return build_enhanced_citations_blob_service_client(get_settings())


def resolve_memory_context(execution=None):
    execution = execution or get_m365_execution_context()
    if not isinstance(execution, M365ExecutionContext) or not execution.conversation_id:
        raise MemoryAuthorizationError("An authorized conversation is required for retained evidence.")
    conversation = cosmos_conversations_container.read_item(
        item=execution.conversation_id, partition_key=execution.conversation_id,
    )
    if execution.workflow_id:
        # The workflow owner supplies a validated destination; this does not switch user identity.
        from functions_m365_runtime import load_current_workflow, workflow_destination_access
        from flask import g
        workflow = load_current_workflow(g.m365_workflow)
        workflow_destination_access(execution.actor_user_id, workflow, execution.conversation_id)
    else:
        build_conversation_participation_context(execution.actor_user_id, conversation)
    owner = str(conversation.get("user_id") or "").strip()
    if not owner:
        raise MemoryAuthorizationError("The backing conversation has no storage owner.")
    return MemoryContext(
        tenant_id=execution.tenant_id,
        principal_id=execution.data_user_id,
        conversation_id=execution.conversation_id,
        storage_owner=owner,
        container="personal-chat",
        request_id=execution.request_id,
    )


def _authorize_memory_access(context, operation):
    execution = get_m365_execution_context()
    if not isinstance(execution, M365ExecutionContext):
        return False
    if (
        context.tenant_id != execution.tenant_id
        or context.principal_id != execution.data_user_id
        or context.conversation_id != execution.conversation_id
    ):
        return False
    current = resolve_memory_context(execution)
    return replace(current, request_id=context.request_id) == context


def _authorize_memory_publication(context, run, grant_context):
    execution = get_m365_execution_context()
    authorized_execution = grant_context.get("execution_context") if isinstance(grant_context, dict) else None
    if (
        not isinstance(grant_context, dict)
        or not isinstance(execution, M365ExecutionContext)
        or not isinstance(authorized_execution, M365ExecutionContext)
        or replace(authorized_execution, action_configs=execution.action_configs) != execution
        or not execution.shared
        or execution.tenant_id != context.tenant_id
        or execution.data_user_id != run.get("principal_id")
        or execution.conversation_id != context.conversation_id
        or execution.data_user_id != context.principal_id
    ):
        raise MemoryAuthorizationError("This snapshot has not been approved for this conversation.")
    source = grant_context.get("source")
    action_id = grant_context.get("action_id")
    if source not in {"onedrive", "spo"} or not action_id:
        raise MemoryAuthorizationError("The retained evidence has no authorized file source.")
    if run.get("purpose") not in {f"m365_file_{source}", f"m365_search_{source}"}:
        raise MemoryAuthorizationError("Only captured source evidence can be published through this action.")
    execution, decision = authorize_m365_publication(
        source, action_id, operation_name=grant_context.get("operation_name"), context=execution,
    )
    references = (decision["approval_id"],)
    return PublicationGrant(
        tenant_id=context.tenant_id, principal_id=context.principal_id,
        conversation_id=context.conversation_id, run_id=run["run_id"],
        request_id=run["request_id"], content_revision=run["content_revision"],
        approval_ids=references, authorization_id=decision["audit_id"],
        audience_fingerprint=execution.audience_version,
        approved_at=decision["acknowledged_at"],
        expires_at=decision.get("expires_at"),
        publication_request_id=execution.request_id,
    )


class RetainedConversationMemoryStore(ConversationMemoryStore):
    def create_run(self, context, **kwargs):
        run = super().create_run(context, **kwargs)
        register_memory_artifact(context, run)
        return run

    def get_or_create_manifest(self, context, **kwargs):
        run = super().get_or_create_manifest(context, **kwargs)
        register_memory_artifact(context, run)
        return run

    def publish(self, context, run_id, **kwargs):
        run = super().publish(context, run_id, **kwargs)
        register_memory_artifact(context, run)
        return run


def get_conversation_memory_store():
    return RetainedConversationMemoryStore(
        get_chat_memory_blob_client(),
        authorize_access=_authorize_memory_access,
        authorize_publish=_authorize_memory_publication,
        log_event=log_event,
    )


def resolve_m365_memory(execution):
    store = get_conversation_memory_store()
    context = resolve_memory_context(execution)
    if not _authorize_memory_access(context, "register"):
        raise MemoryAuthorizationError("The conversation memory inventory is not authorized.")
    for attempt in range(4):
        conversation = cosmos_conversations_container.read_item(
            item=context.conversation_id, partition_key=context.conversation_id,
        )
        if conversation.get("m365_working_memory"):
            break
        try:
            cosmos_conversations_container.replace_item(
                conversation["id"], body={**conversation, "m365_working_memory": True},
                partition_key=context.conversation_id,
                etag=conversation["_etag"], match_condition=MatchConditions.IfNotModified,
            )
            break
        except CosmosHttpResponseError as error:
            if error.status_code != 412 or attempt == 3:
                raise
    return store, context


def register_memory_artifact(context, run):
    """Attach cleanup/audit references, not the evidence body, to chat retention."""
    execution = get_m365_execution_context()
    if not _authorize_memory_access(context, "register") or execution is None:
        raise MemoryAuthorizationError("The conversation evidence reference is not authorized.")
    artifact = {
        "id": f"memory-{run['run_id']}",
        "conversation_id": context.conversation_id,
        "user_id": execution.actor_user_id,
        "role": "assistant_artifact",
        "artifact_kind": MEMORY_ARTIFACT_KIND,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "memory_run_id": run["run_id"],
            "memory_purpose": run["purpose"],
            "m365_source_policies": {
                item["source"]: item.get("maximum_sharing_acknowledgement", "always")
                for item in execution.action_configs.values()
                if item.get("source") in {"email", "calendar", "onedrive", "spo"}
            },
            "memory_context": {
                "tenant_id": context.tenant_id,
                "principal_id": context.principal_id,
                "conversation_id": context.conversation_id,
                "storage_owner": context.storage_owner,
                "container": context.container,
            },
            "publication": run.get("publication"),
        },
    }
    cosmos_messages_container.upsert_item(body=artifact)
    return artifact["id"]
