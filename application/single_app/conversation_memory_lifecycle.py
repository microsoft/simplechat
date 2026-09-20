# conversation_memory_lifecycle.py
"""Dependency-injected cleanup of stored conversation memory references."""

from functions_conversation_memory import (
    ConversationMemoryStore,
    EvidenceChunk,
    EvidenceLocation,
    EvidenceSource,
    MemoryAuthorizationError,
    MemoryContext,
    MemoryNotFoundError,
)


def clone_owned_memory(store, source_context, target_context, run_id):
    """A private fork by the same owner copies evidence without granting new readers."""
    if (
        source_context.tenant_id != target_context.tenant_id
        or source_context.principal_id != target_context.principal_id
        or source_context.storage_owner != source_context.principal_id
        or target_context.storage_owner != target_context.principal_id
        or source_context.conversation_id == target_context.conversation_id
    ):
        raise MemoryAuthorizationError("Private evidence can only be forked by its owner.")
    manifest = store.read_manifest(source_context, run_id)
    if manifest["status"] != "completed":
        raise MemoryAuthorizationError("Finish evidence capture before forking the conversation.")
    target = store.create_run(target_context, purpose=manifest["purpose"])
    target_id = target["run_id"]
    reference_map = {run_id: target_id}
    offset = 0
    while offset is not None:
        page = store.list_sources(source_context, run_id, start=offset)
        for source in page["sources"]:
            def chunks():
                start = 0
                while start is not None:
                    evidence = store.read_evidence_range(
                        source_context, run_id, source["evidence_id"], start=start,
                    )
                    for chunk in evidence["chunks"]:
                        location = dict(chunk["locator"])
                        location["pages"] = tuple(location.get("pages") or ())
                        location["slides"] = tuple(location.get("slides") or ())
                        yield EvidenceChunk(chunk["text"], EvidenceLocation(**location))
                    start = evidence["next_start"]
            copied = store.add_evidence(
                target_context, target_id, source=EvidenceSource(**source["source"]), chunks=chunks(),
            )
            reference_map[f"{run_id}:{source['evidence_id']}"] = f"{target_id}:{copied['evidence_id']}"
        offset = page["next_start"]
    copied_checkpoints = 0
    for index in range(manifest["committed_checkpoint_slots"]):
        try:
            checkpoint = store.read_checkpoint(source_context, run_id, index=index)
        except MemoryNotFoundError:
            continue
        checkpoint = remap_memory_references(checkpoint, reference_map)
        store.append_checkpoint(
            target_context, target_id, checkpoint=checkpoint["checkpoint"],
            output=checkpoint["output"], note=checkpoint["note"],
            completed_units=checkpoint["completed_units"], total_units=checkpoint["total_units"],
        )
        copied_checkpoints += 1
    if copied_checkpoints != manifest["checkpoint_count"]:
        raise MemoryNotFoundError("A committed source checkpoint is unavailable for copying.")
    return {**store.complete_run(target_context, target_id), "reference_map": reference_map}


def remap_memory_references(value, run_map):
    if isinstance(value, dict):
        return {key: remap_memory_references(item, run_map) for key, item in value.items()}
    if isinstance(value, list):
        return [remap_memory_references(item, run_map) for item in value]
    if isinstance(value, str):
        if value in run_map:
            return run_map[value]
        run_id, separator, suffix = value.partition(":")
        if run_id in run_map:
            return run_map[run_id] + (separator + suffix if separator else "")
    return value


def delete_referenced_conversation_memory(
    messages, blob_client, *, tenant_id, read_conversation, log_event, conversation_context=None,
):
    contexts = {}
    if conversation_context is not None:
        conversation = read_conversation(conversation_context.conversation_id)
        if (
            conversation_context.tenant_id != tenant_id
            or conversation_context.storage_owner != conversation.get("user_id")
            or conversation_context.container != "personal-chat"
        ):
            raise MemoryAuthorizationError("The conversation memory inventory has an invalid storage binding.")
        contexts[(
            conversation_context.container,
            conversation_context.storage_owner,
            conversation_context.conversation_id,
        )] = conversation_context
    for message in messages:
        if message.get("artifact_kind") != "conversation_memory":
            continue
        raw = (message.get("metadata") or {}).get("memory_context")
        if not isinstance(raw, dict) or raw.get("tenant_id") != tenant_id:
            raise MemoryAuthorizationError("Conversation memory cleanup metadata is invalid.")
        context = MemoryContext(**raw)
        if context.conversation_id != message.get("conversation_id"):
            raise MemoryAuthorizationError("Conversation memory belongs to another conversation.")
        conversation = read_conversation(context.conversation_id)
        if context.storage_owner != conversation.get("user_id") or context.container != "personal-chat":
            raise MemoryAuthorizationError("Conversation memory has an invalid storage binding.")
        contexts[(context.container, context.storage_owner, context.conversation_id)] = context
    for context in contexts.values():
        store = ConversationMemoryStore(
            blob_client,
            authorize_access=lambda candidate, operation, expected=context: (
                candidate == expected and operation == "delete"
            ),
            log_event=log_event,
        )
        try:
            store.delete_conversation_memory(context)
        except MemoryNotFoundError:
            continue
    return len(contexts)
