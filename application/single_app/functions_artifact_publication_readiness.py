# functions_artifact_publication_readiness.py
"""Receipt-bound observations of the existing document ingestion lifecycle."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError

from content_screening.access import assert_document_available
from content_screening.contracts import AVAILABLE_STATES, HELD_STATES, SCREENING_FIELD, DocumentHeldError


PUBLICATION_BINDING = "generated_artifact_publication_binding"
PUBLICATION_PROCESSING = "generated_artifact_publication_processing"
PUBLICATION_STATUS_FIELDS = (
    "version", "id", "document_id", "document_version", "destination", "completion_policy",
    "policy_satisfied", "state", "submission", "approval", "processing", "screening", "index",
    "reason_code", "retryable", "unresolved_stages",
)


def public_publication_status(value):
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("The publication completion status is unavailable.")
    projected = {key: deepcopy(value[key]) for key in PUBLICATION_STATUS_FIELDS if key in value}
    destination = value.get("destination")
    if not isinstance(destination, dict) or destination.get("workspace_scope") not in {"personal", "group", "public"}:
        raise ValueError("The publication destination is unavailable.")
    projected["destination"] = {key: destination[key] for key in (
        "workspace_scope", "group_id", "public_workspace_id",
    ) if key in destination}
    return projected


def _container(document):
    # Ingestion imports this module; resolve app clients only at the operation boundary.
    import config

    return (
        config.cosmos_public_documents_container if document.get("public_workspace_id") else
        config.cosmos_group_documents_container if document.get("group_id") else
        config.cosmos_user_documents_container
    )


def _same_document(current, document):
    return all(current.get(key) == document.get(key) for key in (
        "id", "user_id", "group_id", "public_workspace_id", "version", PUBLICATION_BINDING,
    ))


def _current_revision(document):
    return document.get("is_current_version") is not False and document.get("search_visibility_state") != "archived"


def _processing_change(document, change):
    container = _container(document)
    for _ in range(8):
        current = container.read_item(item=document["id"], partition_key=document["id"])
        if not _same_document(current, document) or not current.get("_etag"):
            raise ValueError("The publication destination revision changed.")
        replacement = change(deepcopy(current))
        if replacement is None:
            return False
        try:
            container.replace_item(
                item=current["id"], body=replacement, etag=current["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
            return True
        except CosmosHttpResponseError as exc:
            if exc.status_code != 412:
                raise
    raise RuntimeError("The publication processing checkpoint is busy.")


def begin_publication_processing(document, source_path):
    """A duplicate native dispatch cannot start another ingestion of this receipt."""
    binding = (document or {}).get(PUBLICATION_BINDING)
    if not binding:
        return True
    digest = hashlib.sha256()
    with Path(source_path).open("rb") as source:
        for block in iter(lambda: source.read(64 * 1024), b""):
            digest.update(block)
    if binding.get("version") != 1 or binding.get("document_version") != document.get("version"):
        raise ValueError("The publication destination revision changed.")
    if binding.get("content_sha256") != digest.hexdigest():
        def changed_input(current):
            if current.get(PUBLICATION_PROCESSING):
                return None
            current[PUBLICATION_PROCESSING] = {
                "binding": deepcopy(binding), "state": "failed", "reason_code": "publication_content_changed",
            }
            return current

        _processing_change(document, changed_input)
        raise ValueError("The publication input no longer matches the original artifact.")

    def claim(current):
        previous = current.get(PUBLICATION_PROCESSING)
        if previous:
            if previous.get("binding") != binding:
                raise ValueError("The publication processing identity changed.")
            if previous.get("state") == "complete":
                return None
            raise RuntimeError("This publication already has a native processing attempt. Reconcile it before retrying.")
        current[PUBLICATION_PROCESSING] = {
            "binding": deepcopy(binding), "state": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        return current

    return _processing_change(document, claim)


def finish_publication_processing(document, *, indexed_chunks=None, failed=False):
    """Native ingestion owns this evidence, not the workflow polling its result."""
    binding = (document or {}).get(PUBLICATION_BINDING)
    if not binding:
        return
    if not failed and (type(indexed_chunks) is not int or indexed_chunks < 0):
        raise ValueError("The native publication chunk count is invalid.")

    def finish(current):
        previous = current.get(PUBLICATION_PROCESSING) or {}
        if previous.get("binding") != binding or previous.get("state") not in {"running", "complete", "failed"}:
            raise ValueError("The publication has no matching native processing checkpoint.")
        state = "failed" if failed else "complete"
        if previous.get("state") in {"complete", "failed"}:
            if previous["state"] != state or not failed and previous.get("indexed_chunks") != indexed_chunks:
                raise ValueError("The native publication outcome already committed.")
            return None
        current[PUBLICATION_PROCESSING] = {
            **previous, "state": state, "indexed_chunks": indexed_chunks,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        return current

    _processing_change(document, finish)


def publication_binding_matches(receipt, document):
    binding = (document or {}).get(PUBLICATION_BINDING) or {}
    return bool(
        document and binding.get("version") == 1
        and binding.get("receipt_id") == receipt["id"]
        and binding.get("content_sha256") == receipt["content_sha256"]
        and type(binding.get("document_version")) is int
        and binding["document_version"] == document.get("version") == receipt.get("document_version")
        and document.get("generated_artifact_publication_receipt_id") == receipt["id"]
        and binding.get("conversation_id") == receipt["artifact_reference"]["conversation_id"]
        and binding.get("artifact_message_id") == receipt["artifact_reference"]["artifact_message_id"]
    )


def publication_processing_observation(receipt, document):
    if not publication_binding_matches(receipt, document):
        return "unavailable"
    evidence = document.get(PUBLICATION_PROCESSING) or {}
    if evidence.get("binding") != document[PUBLICATION_BINDING]:
        return "not_started"
    return evidence.get("state") if evidence.get("state") in {"running", "complete", "failed"} else "unavailable"


def publication_handoff_observed(receipt, document):
    if publication_processing_observation(receipt, document) in {"running", "complete", "failed"}:
        return True
    if (document or {}).get(SCREENING_FIELD):
        observed = inspect_publication_readiness(receipt, document, check_index=False)
        return (
            observed["processing"] == "complete" and observed["screening"] == "available"
            and not observed.get("reason_code")
        )
    return False


def _index_count(receipt, document):
    # Reuse the native scoped Search client. No ranked search or filename matching.
    from functions_documents import _get_search_client

    destination = receipt["destination"]
    scope = destination["workspace_scope"]
    field = {"personal": "user_id", "group": "group_id", "public": "public_workspace_id"}[scope]
    target = receipt["actor_user_id"] if scope == "personal" else destination[field]
    escaped_id = document["id"].replace("'", "''")
    escaped_target = target.replace("'", "''")
    client = _get_search_client(**{
        key: destination[key] for key in ("group_id", "public_workspace_id") if key in destination
    })
    results = client.search(
        search_text="*", filter=f"document_id eq '{escaped_id}' and version eq {document['version']} and {field} eq '{escaped_target}'",
        select=["id"], top=0, include_total_count=True,
        connection_timeout=30, read_timeout=30, retry_total=0,
    )
    count = results.get_count()
    if type(count) is not int or count < 0:
        raise ValueError("The exact indexed publication count is unavailable.")
    return count


def inspect_publication_readiness(receipt, document, *, available_reader=None, index_count=None, check_index=True):
    """Read native proof; never queue, approve, resume, index, or mutate a document."""
    processing = publication_processing_observation(receipt, document)
    observation = {"processing": processing, "screening": "not_required", "index": "pending"}
    if not publication_binding_matches(receipt, document):
        return {**observation, "reason_code": "publication_revision_changed"}
    if not _current_revision(document):
        return {**observation, "reason_code": "publication_revision_changed"}
    if (document.get(PUBLICATION_PROCESSING) or {}).get("reason_code") == "publication_content_changed":
        return {**observation, "reason_code": "publication_content_changed"}
    marker = document.get(SCREENING_FIELD)
    expected_count = (document.get(PUBLICATION_PROCESSING) or {}).get("indexed_chunks")
    if marker is not None:
        if not isinstance(marker, dict):
            return {**observation, "screening": "unavailable", "reason_code": "publication_screening_unavailable"}
        state = marker.get("state")
        if not isinstance(state, str) or state not in AVAILABLE_STATES | HELD_STATES:
            return {**observation, "screening": "unavailable", "reason_code": "publication_screening_unavailable"}
        if marker.get("sanitized") is True:
            return {**observation, "screening": "changed", "reason_code": "publication_content_changed"}
        if state in {"rejected", "deleting", "deleted"}:
            return {**observation, "screening": "rejected", "reason_code": "publication_screening_rejected"}
        if state not in AVAILABLE_STATES:
            if state in {"scan_error", "incomplete"}:
                return {**observation, "screening": "held", "reason_code": "publication_screening_unavailable"}
            return {**observation, "screening": "held" if state in {
                "pending_review", "remediating",
            } else "pending"}
        # The native release proof binds the scan, revision, canonical content and active blob.
        if (
            marker.get("source_revision") != str(receipt["document_version"])
            or (marker.get("active_blob") or {}).get("content_hash") != receipt["content_sha256"]
        ):
            return {**observation, "screening": "changed", "reason_code": "publication_content_changed"}
        expected_count = document.get("num_chunks")
        observation.update(processing="complete", screening="available")
    if observation["processing"] == "failed":
        return {**observation, "reason_code": "publication_processing_failed"}
    if observation["processing"] != "complete":
        return observation
    if type(expected_count) is not int or expected_count <= 0:
        return {**observation, "index": "unavailable", "reason_code": "publication_no_indexed_content"}
    destination = receipt["destination"]
    scope_args = {key: destination[key] for key in ("group_id", "public_workspace_id") if key in destination}
    try:
        current = (available_reader or assert_document_available)(
            document["id"], user_id=receipt["actor_user_id"], **scope_args,
        )
    except DocumentHeldError:
        return {**observation, "screening": "unavailable", "reason_code": "publication_screening_unavailable"}
    if not _same_document(current, document) or not _current_revision(current) or current.get(SCREENING_FIELD) != marker:
        return {**observation, "reason_code": "publication_revision_changed"}
    if not check_index:
        return observation
    if (index_count or _index_count)(receipt, current) != expected_count:
        return observation
    refreshed = (available_reader or assert_document_available)(
        document["id"], user_id=receipt["actor_user_id"], **scope_args,
    )
    if (
        not _same_document(refreshed, current) or not _current_revision(refreshed) or refreshed.get(SCREENING_FIELD) != marker
        or refreshed.get(PUBLICATION_PROCESSING) != current.get(PUBLICATION_PROCESSING)
        or refreshed.get("num_chunks") != current.get("num_chunks")
    ):
        return {**observation, "reason_code": "publication_revision_changed"}
    return {**observation, "index": "ready"}
