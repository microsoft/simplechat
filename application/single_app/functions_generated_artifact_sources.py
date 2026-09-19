# functions_generated_artifact_sources.py
"""Shared source dispatch for generated files, independent of their renderer."""

from copy import deepcopy
import uuid

from azure.core.exceptions import AzureError
from flask import g, has_request_context

from content_screening.contracts import ScreeningError
from functions_analysis_access import AnalysisResultUnavailable
from functions_appinsights import log_event
from functions_workflow_result_store import WorkflowResultStorageUnavailableError
from functions_workflow_runtime_store import RuntimeUnavailable


_HISTORY_SOURCE_ERRORS = (PermissionError, LookupError, ValueError, AzureError,
                          WorkflowResultStorageUnavailableError, RuntimeUnavailable, ScreeningError)
_UNAVAILABLE_HISTORY = "Saved workflow output is unavailable because current access could not be confirmed."


def has_generated_artifact_source(metadata):
    return (
        "generated_artifact_source" in metadata
        or bool(metadata.get("generated_artifact_source_required"))
        or str(metadata.get("generated_artifact_idempotency_key") or "").startswith("generated-export:v1:")
    )


def generated_chat_artifact_address(owner_id, conversation_id, file_name, idempotency_key, blob_container):
    suffix = uuid.uuid5(
        uuid.NAMESPACE_URL, f"simplechat-generated-artifact:{conversation_id}:{idempotency_key}",
    ).hex if idempotency_key else uuid.uuid4().hex
    message_id = f"{conversation_id}_generated_file_{suffix}"
    return {
        "conversation_id": conversation_id, "artifact_message_id": message_id,
        "file_name": file_name, "blob_container": blob_container,
        "blob_path": f"{owner_id}/{conversation_id}/generated/{message_id}/{file_name}",
    }


def generated_artifact_source_metadata(source):
    # Workflow stores are loaded only for an explicit workflow-source adapter.
    from functions_workflow_artifacts import validate_workflow_artifact_binding

    binding = validate_workflow_artifact_binding(source)
    return {"generated_artifact_source_required": True, "generated_artifact_source": deepcopy(binding)}


def authorize_generated_artifact_preparation(user_id, metadata):
    from functions_workflow_artifacts import load_workflow_artifact_binding

    if metadata.get("analysis_result_required") or metadata.get("analysis_producer"):
        raise AnalysisResultUnavailable("generated_artifact_source_conflict")
    return load_workflow_artifact_binding(
        user_id, metadata.get("generated_artifact_source"), require_ready=False, for_publication=True,
    )


def authorize_generated_artifact_source(user_id, artifact, *, for_publication=False, native_authorizer=None):
    metadata = artifact.get("metadata") or {}
    if has_generated_artifact_source(metadata):
        from functions_workflow_artifacts import authorize_workflow_saved_output_artifact

        if metadata.get("analysis_result_required") or metadata.get("analysis_producer"):
            raise AnalysisResultUnavailable("generated_artifact_source_conflict")
        if metadata.get("generated_artifact_source_required") is not True:
            raise AnalysisResultUnavailable("generated_artifact_source_unbound")
        return authorize_workflow_saved_output_artifact(user_id, artifact, for_publication=for_publication)
    if native_authorizer is None:
        # Native sources retain their existing authorization and eligibility contract.
        from functions_saved_analysis import authorize_analysis_artifact

        native_authorizer = authorize_analysis_artifact
    return native_authorizer(user_id, artifact, **({"for_publication": True} if for_publication else {}))


def sanitize_generated_artifact_history(message, user_id):
    """Reauthorize saved-output cards and strip private bindings from history."""
    metadata = message.get("metadata") or {}
    is_file = message.get("role") == "file" and has_generated_artifact_source(metadata)
    fields = ("generated_analysis_artifacts", "generated_tabular_outputs")
    cards = [
        item for field in fields for item in metadata.get(field) or []
        if isinstance(item, dict) and item.get("source_kind") == "workflow_saved_output"
    ]
    if not is_file and not cards:
        return message
    # Reuse the complete conversation/approval/source/screening boundary, not just an opaque id.
    from route_enhanced_citations import _get_authorized_chat_artifact_message

    def authorize(conversation_id, message_id):
        request_context = has_request_context()
        previous_error = getattr(g, "content_screening_error", None) if request_context else None
        previous_sources = dict(getattr(g, "content_screening_sources", {}) or {}) if request_context else {}
        try:
            return _get_authorized_chat_artifact_message(user_id, conversation_id, message_id)
        except _HISTORY_SOURCE_ERRORS:
            if request_context:
                g.content_screening_error = previous_error
                g.content_screening_sources = previous_sources
            raise

    def log_unavailable(exc):
        log_event(
            "[SIMPLE_CHAT] Saved-output artifact withheld on history read",
            {"message_id": message.get("id"), "exception_type": type(exc).__name__},
        )

    safe = deepcopy(message)
    if is_file:
        try:
            authorize(message.get("conversation_id"), message.get("id"))
        except _HISTORY_SOURCE_ERRORS as exc:
            log_unavailable(exc)
            return {
                **{key: deepcopy(message[key]) for key in (
                    "id", "conversation_id", "timestamp", "created_at", "updated_at", "thread_id", "active_thread",
                ) if key in message},
                "role": "file", "content": _UNAVAILABLE_HISTORY, "content_unavailable": True,
                "file_content": "", "extracted_text": "",
            }
        safe = {key: value for key, value in safe.items() if key in {
            "id", "conversation_id", "role", "filename", "file_name", "content",
            "timestamp", "created_at", "updated_at", "thread_id", "active_thread",
        }}
        safe["metadata"] = {
            key: value for key, value in metadata.items() if key in {
                "is_generated_chat_artifact", "generated_artifact_capability", "generated_artifact_output_format",
                "generated_artifact_summary", "thread_info",
            }
        }
        return safe
    for field in fields:
        if field not in metadata:
            continue
        projected = []
        for card in metadata[field]:
            if not isinstance(card, dict) or card.get("source_kind") != "workflow_saved_output":
                projected.append(deepcopy(card))
                continue
            try:
                if card.get("conversation_id") != message.get("conversation_id"):
                    raise AnalysisResultUnavailable("generated_artifact_source_unbound")
                authorize(card["conversation_id"], card.get("artifact_message_id"))
            except _HISTORY_SOURCE_ERRORS as exc:
                log_unavailable(exc)
                projected.append({
                    "capability": "file_export", "source_kind": "workflow_saved_output",
                    "output_format": "json", "status": "unavailable",
                    "summary": _UNAVAILABLE_HISTORY,
                })
            else:
                projected.append({key: deepcopy(value) for key, value in card.items() if key in {
                    "capability", "source_kind", "artifact_message_id", "conversation_id", "storage_scope",
                    "file_name", "output_format", "summary", "suppress_assistant_text", "row_count", "row_source",
                }})
        safe["metadata"][field] = projected
    return safe
