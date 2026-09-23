# functions_generated_artifact_sources.py
"""Shared source dispatch for generated files, independent of their renderer."""

from contextlib import contextmanager
from copy import deepcopy
import uuid

from azure.core.exceptions import AzureError
from flask import g, has_request_context

from content_screening.contracts import ScreeningError
from functions_analysis_access import AnalysisResultUnavailable
from functions_appinsights import log_event
from functions_orchestration_artifacts import (
    ORCHESTRATION_ARTIFACT_KEY_PREFIX,
    ORCHESTRATION_ARTIFACT_KIND,
    authorize_orchestration_output_artifact,
    is_orchestration_artifact_source,
    load_orchestration_artifact_binding,
    load_orchestration_output_history,
    validate_orchestration_artifact_binding,
)
from functions_orchestration_output_store import OutputConflictError, OutputStorageError, OutputUnavailableError
from functions_workflow_result_store import WorkflowResultStorageUnavailableError
from functions_workflow_runtime_store import RuntimeUnavailable


_HISTORY_SOURCE_ERRORS = (PermissionError, LookupError, ValueError, AzureError,
                          WorkflowResultStorageUnavailableError, RuntimeUnavailable, ScreeningError,
                          OutputConflictError, OutputStorageError)
_UNAVAILABLE_HISTORY = "Saved workflow output is unavailable because current access could not be confirmed."
_ORCHESTRATION_UNAVAILABLE_HISTORY = "Generated file is unavailable because current access or publication could not be confirmed."
_RETAINED_SOURCE_KINDS = frozenset({"workflow_saved_output", ORCHESTRATION_ARTIFACT_KIND})
_ORCHESTRATION_HISTORY_DENIAL_CODES = frozenset({
    "output_access_denied", "output_conversation_unavailable", "output_run_unavailable",
})


@contextmanager
def _history_screening_context():
    request_context = has_request_context()
    previous_error = getattr(g, "content_screening_error", None) if request_context else None
    previous_sources = dict(getattr(g, "content_screening_sources", {}) or {}) if request_context else {}
    try:
        yield
    finally:
        if request_context:
            g.content_screening_error = previous_error
            g.content_screening_sources = previous_sources


def has_generated_artifact_source(metadata):
    return (
        "generated_artifact_source" in metadata
        or "generated_artifact_origin" in metadata
        or bool(metadata.get("generated_artifact_source_required"))
        or str(metadata.get("generated_artifact_idempotency_key") or "").startswith((
            "generated-export:v1:", ORCHESTRATION_ARTIFACT_KEY_PREFIX,
        ))
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
    if is_orchestration_artifact_source(source):
        binding = validate_orchestration_artifact_binding(source)
        return {
            "generated_artifact_source_required": True, "generated_artifact_source": binding,
            "generated_artifact_origin": ORCHESTRATION_ARTIFACT_KIND,
        }
    # Workflow stores are loaded only for an explicit workflow-source adapter.
    from functions_workflow_artifacts import validate_workflow_artifact_binding

    binding = validate_workflow_artifact_binding(source)
    return {"generated_artifact_source_required": True, "generated_artifact_source": deepcopy(binding)}


def authorize_generated_artifact_preparation(user_id, metadata):
    if metadata.get("analysis_result_required") or metadata.get("analysis_producer"):
        raise AnalysisResultUnavailable("generated_artifact_source_conflict")
    if is_orchestration_artifact_source(metadata.get("generated_artifact_source")):
        if metadata.get("generated_artifact_source_required") is not True:
            raise AnalysisResultUnavailable("generated_artifact_source_unbound")
        return load_orchestration_artifact_binding(
            user_id, metadata["generated_artifact_source"], require_ready=False, for_publication=True,
        )
    # The legacy workflow owner remains deferred until its source kind is selected.
    from functions_workflow_artifacts import load_workflow_artifact_binding

    return load_workflow_artifact_binding(
        user_id, metadata.get("generated_artifact_source"), require_ready=False, for_publication=True,
    )


def authorize_generated_artifact_source(user_id, artifact, *, for_publication=False, native_authorizer=None):
    metadata = artifact.get("metadata") or {}
    if has_generated_artifact_source(metadata):
        if metadata.get("analysis_result_required") or metadata.get("analysis_producer"):
            raise AnalysisResultUnavailable("generated_artifact_source_conflict")
        if metadata.get("generated_artifact_source_required") is not True:
            raise AnalysisResultUnavailable("generated_artifact_source_unbound")
        origin = metadata.get("generated_artifact_origin")
        binding = metadata.get("generated_artifact_source")
        if origin is not None and (
            not isinstance(binding, dict) or origin != binding.get("kind")
        ):
            raise AnalysisResultUnavailable("generated_artifact_source_conflict")
        if is_orchestration_artifact_source(metadata.get("generated_artifact_source")):
            return authorize_orchestration_output_artifact(user_id, artifact, for_publication=for_publication)
        # Workflow authorization is unchanged and rejects unknown source kinds.
        from functions_workflow_artifacts import authorize_workflow_saved_output_artifact

        return authorize_workflow_saved_output_artifact(user_id, artifact, for_publication=for_publication)
    if native_authorizer is None:
        # Native sources retain their existing authorization and eligibility contract.
        from functions_saved_analysis import authorize_analysis_artifact

        native_authorizer = authorize_analysis_artifact
    return native_authorizer(user_id, artifact, **({"for_publication": True} if for_publication else {}))


def sanitize_generated_artifact_history(message, user_id):
    """Reauthorize saved-output cards and strip private bindings from history."""
    metadata = message.get("metadata") or {}
    orchestration_history = (
        is_orchestration_artifact_source(metadata.get("generated_artifact_source"))
        or metadata.get("generated_artifact_origin") == ORCHESTRATION_ARTIFACT_KIND
    )
    is_file = message.get("role") == "file" and has_generated_artifact_source(metadata)
    orchestration = metadata.get("orchestration")
    has_output_history = isinstance(orchestration, dict) and "outputs" in orchestration
    top_level_cards = message.get("generated_artifacts") or []
    has_orchestration_cards = any(
        isinstance(card, dict) and card.get("source_kind") == ORCHESTRATION_ARTIFACT_KIND
        for card in top_level_cards
    )
    fields = ("generated_analysis_artifacts", "generated_tabular_outputs", "generated_orchestration_outputs")
    cards = [
        item for field in fields for item in metadata.get(field) or []
        if isinstance(item, dict) and item.get("source_kind") in _RETAINED_SOURCE_KINDS
    ]
    if not is_file and not cards and not has_output_history and not has_orchestration_cards:
        return message

    def authorize(conversation_id, message_id):
        # Reuse the complete conversation/approval/source/screening boundary for saved cards.
        from route_enhanced_citations import _get_authorized_chat_artifact_message

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

    def log_unavailable(exc, *, orchestration=False):
        if orchestration:
            # Keep the legacy workflow import path independent of rendering.
            from functions_orchestration_rendering import raise_output_read_infrastructure_failure

            raise_output_read_infrastructure_failure(exc)
        log_event(
            "[SIMPLE_CHAT] Saved-output artifact withheld on history read",
            {"message_id": message.get("id"), "exception_type": type(exc).__name__},
        )

    safe = deepcopy(message)
    if has_output_history:
        try:
            with _history_screening_context():
                current = load_orchestration_output_history(
                    user_id, message.get("conversation_id"), orchestration.get("run_id"),
                )
        except OutputUnavailableError as exc:
            if exc.code not in _ORCHESTRATION_HISTORY_DENIAL_CODES:
                raise
            log_unavailable(exc, orchestration=True)
            current = {"outputs": [], "artifacts": []}
        safe["metadata"]["orchestration"]["outputs"] = current["outputs"]
        if "generated_artifacts" in message:
            safe["generated_artifacts"] = [
                deepcopy(card) for card in top_level_cards
                if not isinstance(card, dict) or card.get("source_kind") != ORCHESTRATION_ARTIFACT_KIND
            ] + current["artifacts"]
    if is_file:
        try:
            authorized_message = authorize(message.get("conversation_id"), message.get("id"))
            if orchestration_history:
                current_metadata = authorized_message.get("metadata") or {}
                if not is_orchestration_artifact_source(current_metadata.get("generated_artifact_source")):
                    raise AnalysisResultUnavailable("generated_artifact_source_unbound")
                message = authorized_message
                metadata = current_metadata
                safe = deepcopy(authorized_message)
        except _HISTORY_SOURCE_ERRORS as exc:
            log_unavailable(exc, orchestration=orchestration_history)
            return {
                **{key: deepcopy(message[key]) for key in (
                    "id", "conversation_id", "timestamp", "created_at", "updated_at", "thread_id", "active_thread",
                ) if key in message},
                "role": "file", "content": (
                    _ORCHESTRATION_UNAVAILABLE_HISTORY
                    if orchestration_history
                    else _UNAVAILABLE_HISTORY
                ), "content_unavailable": True,
                "file_content": "", "extracted_text": "",
                **({"metadata": {"generated_artifact_origin": ORCHESTRATION_ARTIFACT_KIND}}
                   if orchestration_history else {}),
            }
        safe = {key: value for key, value in safe.items() if key in {
            "id", "conversation_id", "role", "filename", "file_name", "content",
            "timestamp", "created_at", "updated_at", "thread_id", "active_thread",
        }}
        safe["metadata"] = {
            key: value for key, value in metadata.items() if key in {
                "is_generated_chat_artifact", "generated_artifact_capability", "generated_artifact_output_format",
                "generated_artifact_summary", "generated_artifact_origin", "thread_info",
            }
        }
        if orchestration_history:
            safe["metadata"]["generated_artifact_origin"] = ORCHESTRATION_ARTIFACT_KIND
        return safe

    def project_cards(values, source_kinds):
        projected = []
        for card in values:
            if not isinstance(card, dict) or card.get("source_kind") not in source_kinds:
                projected.append(deepcopy(card))
                continue
            try:
                if card.get("conversation_id") != message.get("conversation_id"):
                    raise AnalysisResultUnavailable("generated_artifact_source_unbound")
                authorize(card["conversation_id"], card.get("artifact_message_id"))
            except _HISTORY_SOURCE_ERRORS as exc:
                log_unavailable(exc, orchestration=card["source_kind"] == ORCHESTRATION_ARTIFACT_KIND)
                projected.append({
                    "capability": "file_export", "source_kind": card["source_kind"],
                    "status": "unavailable",
                    **({"output_format": "json"} if card["source_kind"] == "workflow_saved_output" else {}),
                    "summary": (
                        _ORCHESTRATION_UNAVAILABLE_HISTORY
                        if card["source_kind"] == ORCHESTRATION_ARTIFACT_KIND else _UNAVAILABLE_HISTORY
                    ),
                })
            else:
                projected.append({key: deepcopy(value) for key, value in card.items() if key in {
                    "capability", "source_kind", "artifact_message_id", "conversation_id", "storage_scope",
                    "file_name", "output_format", "summary", "suppress_assistant_text", "row_count", "row_source",
                    "output_id", "profile", "character_count",
                }})
        return projected

    for field in fields:
        if field in metadata:
            safe["metadata"][field] = project_cards(metadata[field], _RETAINED_SOURCE_KINDS)
    if has_orchestration_cards and not has_output_history:
        safe["generated_artifacts"] = project_cards(top_level_cards, {ORCHESTRATION_ARTIFACT_KIND})
    return safe
