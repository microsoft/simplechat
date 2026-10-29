# functions_m365_history.py
"""Approval of a fixed private-history snapshot before conversation sharing."""

from dataclasses import dataclass
from typing import Callable

from functions_conversation_memory import PublicationGrant
from functions_m365_approvals import (
    M365ApprovalRequired, M365PolicyError, material_fingerprint, strictest_sharing_policy,
)
from functions_m365_execution import M365ExecutionContext
from functions_m365_operations import M365_LEGACY_OPERATION_SOURCES, M365_SOURCES


@dataclass(frozen=True)
class HistoryPublication:
    request_id: str
    messages: tuple
    approval_ids: tuple
    audience_version: str


def history_sources(messages):
    """Use persisted source provenance and legacy tool identifiers, not prose."""
    sources = {}
    for message in messages:
        metadata = message.get("metadata") or {}
        for source, ceiling in (metadata.get("m365_source_policies") or {}).items():
            if source in M365_SOURCES:
                sources[source] = strictest_sharing_policy(sources.get(source), ceiling)
        for citation in message.get("agent_citations") or []:
            function = citation.get("function_name") or ""
            result = citation.get("function_result") or {}
            source = result.get("source") if isinstance(result, dict) else None
            if source not in M365_SOURCES:
                source = M365_LEGACY_OPERATION_SOURCES.get(function)
            if source in M365_SOURCES:
                if source not in (metadata.get("m365_source_policies") or {}):
                    sources[source] = strictest_sharing_policy(sources.get(source), "request")
        purpose = metadata.get("memory_purpose") or ""
        for source in ("onedrive", "spo"):
            if purpose in {f"m365_file_{source}", f"m365_search_{source}", f"m365_discovery_{source}"}:
                if source not in (metadata.get("m365_source_policies") or {}):
                    sources[source] = strictest_sharing_policy(sources.get(source), "request")
    return sources


class M365HistoryService:
    def __init__(
        self, *, tenant_id, jobs, approvals, read_conversation: Callable,
        read_messages: Callable, memory_resolver: Callable, audience_resolver: Callable,
        has_active_request: Callable,
    ):
        self.tenant_id = tenant_id
        self.jobs = jobs
        self.approvals = approvals
        self.read_conversation = read_conversation
        self.read_messages = read_messages
        self.memory_resolver = memory_resolver
        self.audience_resolver = audience_resolver
        self.has_active_request = has_active_request

    def _snapshot(self, user_id, conversation_id, scope, participants):
        conversation = self.read_conversation(scope, conversation_id)
        if conversation.get("user_id") != user_id:
            raise PermissionError("Only the owner may publish this private history.")
        if self.has_active_request(conversation_id):
            raise M365PolicyError(
                "m365_history_busy",
                "Wait for the current Microsoft 365 request to finish before sharing its conversation.",
            )
        messages = list(self.read_messages(scope, conversation_id))
        sources = history_sources(messages)
        memories = []
        resolver = None
        for message in messages:
            if message.get("artifact_kind") != "conversation_memory":
                continue
            if resolver is None:
                resolver = self.memory_resolver(user_id, conversation, scope)
            store, context = resolver
            run_id = (message.get("metadata") or {}).get("memory_run_id")
            manifest = store.read_manifest(context, run_id)
            purpose = manifest["purpose"]
            source = next((
                candidate for candidate in ("onedrive", "spo")
                if purpose in {
                    f"m365_file_{candidate}", f"m365_search_{candidate}",
                    f"m365_discovery_{candidate}",
                }
            ), None)
            if source is None:
                continue
            sources.setdefault(source, "request")
            if not manifest.get("publication") and manifest["status"] != "completed":
                raise M365PolicyError("m365_history_busy", "Finish or cancel unfinished evidence capture before sharing.")
            memories.append({
                "run_id": run_id, "source": source,
                "content_revision": manifest["content_revision"],
                "content_sha256": manifest["content_sha256"],
            })
        audience = self.audience_resolver(user_id, conversation, scope, participants)
        fingerprint = material_fingerprint({
            "conversation": {
                key: conversation.get(key)
                for key in ("summary", "context", "scope_locked", "locked_contexts")
            },
            "messages": [
                {"id": item["id"], "etag": item.get("_etag")}
                for item in messages if item.get("artifact_kind") != "conversation_memory"
            ],
            "memories": memories,
        })
        return conversation, messages, sources, memories, audience, fingerprint

    def prepare(self, user_id, conversation_id, scope, participants):
        snapshot = self._snapshot(user_id, conversation_id, scope, participants)
        conversation, messages, sources, memories, audience, fingerprint = snapshot
        if not sources:
            return HistoryPublication("", tuple(messages), (), audience)
        request_id = "m365-share-" + material_fingerprint([
            user_id, conversation_id, scope, audience, fingerprint,
        ])
        context = M365ExecutionContext(
            actor_user_id=user_id, data_user_id=user_id, tenant_id=self.tenant_id,
            conversation_id=conversation_id, request_id=request_id,
            shared=True, audience_version=audience,
            action_configs={
                f"history-{source}": {
                    "source": source, "maximum_sharing_acknowledgement": ceiling,
                } for source, ceiling in sources.items()
            },
        )
        record = {
            "id": request_id, "type": "m365_history_publication", "user_id": user_id,
            "conversation_id": conversation_id, "scope": scope,
            "participants": participants, "audience_version": audience,
            "snapshot_fingerprint": fingerprint, "sources": sources,
            "status": "awaiting_approval",
        }
        self.jobs.upsert_item(body=record)
        try:
            grants = self.approvals.authorize_sources(context, sources)
        except M365ApprovalRequired as error:
            record["approval_id"] = error.approval_id
            self.jobs.upsert_item(body=record)
            raise
        approval_ids = tuple(dict.fromkeys(grant["approval_id"] for grant in grants.values()))
        if memories:
            store, memory_context = self.memory_resolver(user_id, conversation, scope)
            previous_authorizer = store.authorize_publish

            def authorize_publish(ctx, manifest, supplied):
                if supplied is not context:
                    raise PermissionError("The evidence publication context is invalid.")
                evidence = next((item for item in memories if item["run_id"] == manifest["run_id"]), None)
                if (
                    evidence is None or manifest["content_revision"] != evidence["content_revision"]
                    or manifest["content_sha256"] != evidence["content_sha256"]
                ):
                    raise PermissionError("The retained evidence changed before publication.")
                grant = self.approvals.authorize_sources(context, sources)[evidence["source"]]
                return PublicationGrant(
                    tenant_id=ctx.tenant_id, principal_id=ctx.principal_id,
                    conversation_id=ctx.conversation_id, run_id=manifest["run_id"],
                    request_id=manifest["request_id"], content_revision=manifest["content_revision"],
                    approval_ids=(grant["approval_id"],), authorization_id=request_id,
                    audience_fingerprint=audience, approved_at=grant["acknowledged_at"],
                    expires_at=grant.get("expires_at"),
                )

            store.authorize_publish = authorize_publish
            try:
                for memory in memories:
                    manifest = store.read_manifest(memory_context, memory["run_id"])
                    if manifest.get("publication") is None:
                        store.publish(memory_context, memory["run_id"], grant_context=context)
            finally:
                store.authorize_publish = previous_authorizer
        record.update(status="approved", approval_ids=list(approval_ids))
        self.jobs.upsert_item(body=record)
        return HistoryPublication(request_id, tuple(messages), approval_ids, audience)

    def validate_decision(self, approval):
        context = approval.get("context") or {}
        record = self.jobs.read_item(context["request_id"], partition_key=approval["subject_user_id"])
        if record.get("type") != "m365_history_publication":
            return False
        snapshot = self._snapshot(
            approval["subject_user_id"], record["conversation_id"],
            record["scope"], record["participants"],
        )
        return (
            snapshot[4] == record["audience_version"] == context["audience_version"]
            and snapshot[5] == record["snapshot_fingerprint"]
        )


_service = None


def configure_m365_history(service):
    global _service
    _service = service


def prepare_m365_history_publication(user_id, conversation_id, scope, participants):
    if _service is None:
        raise M365PolicyError("m365_history_unavailable", "History sharing authorization is not configured.")
    return _service.prepare(user_id, conversation_id, scope, participants)


def validate_m365_history_decision(approval):
    return _service is not None and _service.validate_decision(approval)
