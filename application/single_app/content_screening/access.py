# access.py
"""Authoritative ordinary-content access, independent of the screening toggle.

``assert_document_available(document_or_id, user_id=None, group_id=None,
public_workspace_id=None, *, purpose="read", metadata_reader=None,
strict_errors=False)`` returns a
fresh authorized document, never the supplied record. An injected reader must
implement the same object authorization as the default reader and accept
``document_id, user_id, group_id, public_workspace_id`` keyword arguments.

``filter_available_results(results, user_id=None, *, cached=False,
metadata_reader=None, units_reader=None)`` reads each distinct source once per call. Returned
results carry revision/generation provenance; a subsequent call is a new read.
An injected ``units_reader(reference, subject)`` supplies canonical units.

``assert_evidence_available(evidence, user_id=None, *, metadata_reader=None,
cached=False, strict_errors=False)`` checks known provenance on every reuse. Set ``cached=True`` for
historical results: an old unversioned context cannot borrow a new clearance.

Server-owned retained-result operations opt into typed authority failures with
``strict_errors=True`` or ``strict_source_authority()``. A headless owner that
catches errors keeps the latter scope around the entire source/model decision.

``public_document_payload(document)`` serializes already-authorized, current
metadata. Held documents retain only identification and safe status fields.
Neither a search projection nor a serialized payload is an authorization token.
"""

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
import hashlib
from importlib import import_module
import json
import logging
import math
import mimetypes
from urllib.parse import unquote

from azure.core.exceptions import HttpResponseError, ResourceNotFoundError, ServiceRequestError, ServiceResponseError
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout as RequestsTimeout

from content_screening.contracts import (
    SCREENING_FIELD,
    DocumentHeldError,
    ScreeningConflictError,
    ScreeningError,
    ScreeningValidationError,
    SourceAuthorityUnavailableError,
    SourceAuthorityUnverifiedError,
    AVAILABLE_STATES,
    HELD_STATES,
    content_fingerprint,
    hash_payload,
    metadata_fingerprint,
    normalize_units,
    public_screening_summary,
    require_document_available,
    subject_from_document,
)


PROVENANCE_FIELD = "screening_provenance"
PRIVATE_CONTAINER = "content-screening"
READ_GROUP_ROLES = ("Owner", "Admin", "DocumentManager", "User")
HELD_PUBLIC_FIELDS = frozenset({
    "id", "document_id", "file_name", "filename", "file_type", "file_size",
    "version", "revision_family_id", "is_current_version", "scope", "scope_id",
    "user_id", "group_id", "public_workspace_id", "conversation_id",
    "upload_date", "created_at", "updated_at", "last_updated",
    "percentage_complete", "number_of_pages", "num_chunks", "num_file_chunks",
    "current_file_chunk", "is_shared", "shared", "can_delete", "can_manage",
    "owner_id", "shared_approval_status", "user_role", "userRole",
})
PRIVATE_DOCUMENT_FIELDS = frozenset({
    "blob_container", "blob_path", "archived_blob_path", "blob_etag",
    "blob_content_hash", "blob_url", "download_url", "sas_url", "source_ref",
    "canonical_ref", "units_ref", "result_ref", "original_blob_path",
    "original_blob_container", "active_manifest_id", "active_content_manifest",
    PROVENANCE_FIELD,
    "generated_artifact_publication_binding", "generated_artifact_publication_processing",
})
_SOURCE_AUTHORITY_SCOPE = ContextVar("content_screening_source_authority_scope", default=None)


@contextmanager
def strict_source_authority():
    """Opt this server-owned operation into typed failures, with an isolated model fence."""
    current = _SOURCE_AUTHORITY_SCOPE.get()
    token = _SOURCE_AUTHORITY_SCOPE.set(current if current is not None else {"failure": None})
    try:
        yield
    except (ScreeningError, LookupError, PermissionError) as error:
        _remember_screening_failure(error)
        raise
    finally:
        _SOURCE_AUTHORITY_SCOPE.reset(token)


def strict_source_authority_enabled():
    return _SOURCE_AUTHORITY_SCOPE.get() is not None


def source_authority_not_found(error):
    """Recognize real provider missing records, never exception causes or message text."""
    return isinstance(error, (ResourceNotFoundError, CosmosResourceNotFoundError)) or (
        isinstance(error, HttpResponseError) and error.status_code == 404
    )


def raise_source_authority_error(error):
    """Preserve known access outcomes and sanitize non-authoritative I/O failures."""
    if isinstance(error, (ScreeningError, PermissionError)) or type(error) in (LookupError, FileNotFoundError):
        failure = error
    elif source_authority_not_found(error):
        failure = LookupError("Source not found or access denied.")
    elif isinstance(error, (
        TimeoutError, ConnectionError, ServiceRequestError, ServiceResponseError,
        RequestsConnectionError, RequestsTimeout,
    )) or (
        isinstance(error, HttpResponseError)
        and isinstance(error.status_code, int)
        and (error.status_code in (408, 429) or 500 <= error.status_code <= 599)
    ):
        failure = SourceAuthorityUnavailableError()
    else:
        failure = SourceAuthorityUnverifiedError()
    _remember_screening_failure(failure)
    # Import-only screening consumers must stay below telemetry/bootstrap owners.
    # Resolve logging only for an actual authority failure, after setting its fence.
    from functions_appinsights import log_event

    log_event(
        "[CONTENT_SCREENING] Current source authority could not be verified.",
        extra={"error_type": type(error).__name__, "code": getattr(failure, "code", "source_unavailable")},
        level=logging.WARNING,
    )
    if failure is error:
        raise error
    raise failure from error


def _malformed_source_authority():
    if strict_source_authority_enabled():
        raise_source_authority_error(SourceAuthorityUnverifiedError())
    raise DocumentHeldError()


def _require_available_metadata(document):
    if not isinstance(document, Mapping):
        _malformed_source_authority()
    invalid_available_marker = False
    if SCREENING_FIELD in document:
        marker = document.get(SCREENING_FIELD)
        if not isinstance(marker, dict) or not isinstance(marker.get("state"), str):
            _malformed_source_authority()
        if strict_source_authority_enabled() and marker["state"] not in AVAILABLE_STATES | HELD_STATES:
            _malformed_source_authority()
        invalid_available_marker = (
            not isinstance(marker.get("scan_id"), str) or not marker["scan_id"].strip()
            or not isinstance(marker.get("content_fingerprint"), str) or not marker["content_fingerprint"].strip()
            or isinstance(marker.get("source_revision"), bool)
        )
        if strict_source_authority_enabled() and marker["state"] in AVAILABLE_STATES:
            revision = marker.get("source_revision")
            if (
                invalid_available_marker or not isinstance(revision, (str, int, float))
                or (isinstance(revision, str) and not revision.strip())
                or (isinstance(revision, float) and not math.isfinite(revision))
            ):
                _malformed_source_authority()
    require_document_available(document)
    if SCREENING_FIELD in document:
        marker = document[SCREENING_FIELD]
        if invalid_available_marker:
            _malformed_source_authority()
        if marker.get("review_required") is True:
            raise DocumentHeldError()


def _current_user_id(user_id=None):
    if user_id:
        return str(user_id)
    # Avoid authentication/configuration initialization in standalone tests.
    execution = import_module("agent_execution_context")
    actor_id = execution.execution_user_id()
    if actor_id:
        return actor_id
    return import_module("functions_authentication").get_current_user_id()


def _approved_share(entries, scope_id):
    return any(str(entry) in {str(scope_id), f"{scope_id},approved"} for entry in entries or [])


def _authorize_document(document, user_id, group_id=None, public_workspace_id=None, *, metadata_only=False):
    if not user_id:
        raise PermissionError("Document not found or access denied.")
    if strict_source_authority_enabled():
        scope_id = document.get("public_workspace_id") or document.get("group_id") or document.get("user_id")
        if (
            not isinstance(scope_id, str) or not scope_id.strip()
            or (document.get("public_workspace_id") and document.get("group_id"))
        ):
            _malformed_source_authority()
    if document.get("public_workspace_id"):
        workspace_id = document["public_workspace_id"]
        if public_workspace_id and str(workspace_id) != str(public_workspace_id):
            raise PermissionError("Document not found or access denied.")
        # Public content does not require a management role. Directory visibility
        # is a preference, not an authorization grant for assigned knowledge.
        workspaces = import_module("functions_public_workspaces")
        workspace = workspaces.find_public_workspace_by_id(workspace_id)
        if strict_source_authority_enabled() and workspace is not None and (
            not isinstance(workspace, Mapping) or workspace.get("id") != workspace_id
        ):
            _malformed_source_authority()
        if not workspace:
            raise PermissionError("Document not found or access denied.")
        return
    if document.get("group_id"):
        groups = import_module("functions_group")
        candidates = [group_id] if group_id else [document["group_id"]]
        if not group_id or group_id == document["group_id"]:
            candidates.extend(
                str(entry).rsplit(",", 1)[0]
                for entry in document.get("shared_group_ids", []) or []
                if metadata_only or "," not in str(entry) or str(entry).endswith(",approved")
            )
        for candidate in dict.fromkeys(candidates):
            shared = _approved_share(document.get("shared_group_ids"), candidate)
            if metadata_only:
                shared = any(str(entry).split(",", 1)[0] == str(candidate) for entry in document.get("shared_group_ids", []) or [])
            if candidate != document["group_id"] and not shared:
                continue
            try:
                groups.assert_group_role(user_id, candidate, allowed_roles=READ_GROUP_ROLES)
                return
            except (LookupError, PermissionError, ValueError) as error:
                if strict_source_authority_enabled() and not (
                    isinstance(error, PermissionError) or type(error) is LookupError
                ):
                    raise_source_authority_error(error)
                continue
        raise PermissionError("Document not found or access denied.")
    shared = _approved_share(document.get("shared_user_ids"), user_id)
    if metadata_only:
        shared = any(str(entry).split(",", 1)[0] == str(user_id) for entry in document.get("shared_user_ids", []) or [])
    if document.get("user_id") != user_id and not shared:
        raise PermissionError("Document not found or access denied.")


def _read_authorized_document(
    document_id, user_id, group_id=None, public_workspace_id=None, *, metadata_only=False, scope_type=None,
):
    # Deliberately bypass the document-access index and all positive caches.
    config = import_module("config")
    names = (
        ["cosmos_public_documents_container"] if public_workspace_id else
        ["cosmos_group_documents_container"] if group_id else
        ["cosmos_user_documents_container"] if scope_type == "personal" else
        ["cosmos_user_documents_container", "cosmos_group_documents_container",
         "cosmos_public_documents_container"]
    )
    for name in names:
        container = getattr(config, name)
        try:
            document = container.read_item(item=document_id, partition_key=document_id)
        except Exception as error:
            if strict_source_authority_enabled():
                if source_authority_not_found(error):
                    continue
                raise_source_authority_error(error)
            if getattr(error, "status_code", None) == 404 or type(error).__name__ == "CosmosResourceNotFoundError":
                continue
            raise DocumentHeldError() from error
        if not isinstance(document, Mapping) or str(document.get("id")) != str(document_id):
            _malformed_source_authority()
        _authorize_document(document, user_id, group_id, public_workspace_id, metadata_only=metadata_only)
        if not metadata_only and SCREENING_FIELD in document:
            _require_release_proof(document, config.cosmos_content_screening_container)
        return dict(document)
    raise LookupError("Document not found or access denied.")


def _require_release_proof(document, container):
    """A restored marker or stale metadata write cannot create a clearance."""
    _require_available_metadata(document)
    marker = document[SCREENING_FIELD]
    try:
        scan = container.read_item(item=marker["scan_id"], partition_key=marker["scan_id"])
    except Exception as error:
        if strict_source_authority_enabled() and not source_authority_not_found(error):
            raise_source_authority_error(error)
        raise DocumentHeldError() from error
    if not isinstance(scan, Mapping):
        _malformed_source_authority()
    publication = scan.get("publication")
    if (
        scan.get("kind") != "scan"
        or scan.get("subject") != subject_from_document(document).to_dict()
        or scan.get("state") != marker.get("state")
        or scan.get("coverage_complete") is not True
        or scan.get("result_status") not in {"pass", "findings"}
        or scan.get("content_fingerprint") != marker.get("content_fingerprint")
        or scan.get("policy_fingerprint") != marker.get("policy_fingerprint")
        or hash_payload(scan.get("policy")) != scan.get("policy_fingerprint")
        or scan.get("units_ref") != marker.get("canonical_ref")
        or not isinstance(publication, Mapping)
        or publication.get("active_blob") != marker.get("active_blob")
        or publication.get("content_fingerprint") != marker.get("content_fingerprint")
        or publication.get("metadata_fingerprint") != metadata_fingerprint(document)
    ):
        raise DocumentHeldError()


def _source_arguments(source, user_id, group_id=None, public_workspace_id=None):
    if isinstance(source, Mapping):
        provenance = source.get(PROVENANCE_FIELD)
        if isinstance(provenance, Mapping):
            source_id = (
                source.get("workspace_document_id") or source.get("document_id")
                or source.get("source_document_id") or source.get("doc_id")
            )
            if source_id is not None and str(source_id) != str(provenance.get("document_id")):
                _malformed_source_authority()
        reference = provenance if isinstance(provenance, Mapping) else source
        document_id = (
            reference.get("workspace_document_id") or reference.get("document_id")
            or reference.get("source_document_id") or reference.get("doc_id") or reference.get("id")
        )
        scope = reference.get("scope_type") or reference.get("scope")
        scope_id = reference.get("scope_id")
        group_id = group_id or reference.get("group_id") or (scope_id if scope == "group" else None)
        public_workspace_id = public_workspace_id or reference.get("public_workspace_id") or (
            scope_id if scope == "public" else None
        )
    else:
        document_id = source
    if not isinstance(document_id, (str, int)) or not str(document_id).strip():
        _malformed_source_authority()
    return {
        "document_id": str(document_id),
        "user_id": user_id,
        "group_id": group_id,
        "public_workspace_id": public_workspace_id,
    }


def document_provenance(document):
    """Return non-content revision identity suitable for persisted evidence."""
    scope = "public" if document.get("public_workspace_id") else "group" if document.get("group_id") else "personal"
    marker = document.get(SCREENING_FIELD)
    return {
        "document_id": document.get("id") or document.get("document_id"),
        "scope_type": scope,
        "scope_id": document.get("public_workspace_id") or document.get("group_id") or document.get("user_id"),
        "source_revision": str(document.get("version") or 1),
        "generation": hash_payload(marker) if SCREENING_FIELD in document else None,
    }


def _check_source_revision(source, document, *, cached=False):
    if not isinstance(source, Mapping):
        return
    provenance = source.get(PROVENANCE_FIELD)
    if isinstance(provenance, Mapping):
        if dict(provenance) != document_provenance(document):
            raise ScreeningConflictError()
    elif SCREENING_FIELD in source:
        if document_provenance(source) != document_provenance(document):
            raise ScreeningConflictError()
    elif cached and SCREENING_FIELD in document:
        # Pre-enrollment caches have no generation and cannot prove that their
        # snippets survived a remediation performed without a version bump.
        raise ScreeningConflictError()
    version = source.get("version")
    if version is not None and str(version) != str(document.get("version") or 1):
        raise ScreeningConflictError()


def _remember_document_use(document, user_id):
    # Flask request-local provenance is evidence, not an availability cache.
    flask = import_module("flask")
    if not flask.has_request_context():
        return
    sources = getattr(flask.g, "content_screening_sources", None)
    if sources is None:
        sources = {}
        flask.g.content_screening_sources = sources
    reference = document_provenance(document)
    key = (user_id, reference["scope_type"], reference["scope_id"], reference["document_id"])
    sources.setdefault(key, {PROVENANCE_FIELD: reference})


def _remember_screening_failure(error):
    current = _SOURCE_AUTHORITY_SCOPE.get()
    if current is not None:
        if current["failure"] is None:
            current["failure"] = error
        error = current["failure"]
    flask = import_module("flask")
    if flask.has_request_context():
        flask.g.content_screening_error = error


def assert_document_available(
    document_or_id, user_id=None, group_id=None, public_workspace_id=None, *,
    purpose="read", metadata_reader=None, strict_errors=False,
):
    if type(strict_errors) is not bool:
        raise TypeError("The source authority error policy must be server-owned.")
    if strict_errors:
        with strict_source_authority():
            return assert_document_available(
                document_or_id, user_id, group_id, public_workspace_id,
                purpose=purpose, metadata_reader=metadata_reader,
            )
    try:
        user_id = _current_user_id(user_id)
        arguments = _source_arguments(document_or_id, user_id, group_id, public_workspace_id)
    except Exception as error:
        if strict_source_authority_enabled():
            raise_source_authority_error(error)
        raise
    reader = metadata_reader or _read_authorized_document
    try:
        document = reader(**arguments)
        if not isinstance(document, Mapping) or str(document.get("id")) != arguments["document_id"]:
            _malformed_source_authority()
        _require_available_metadata(document)
        _check_source_revision(document_or_id, document)
    except (DocumentHeldError, ScreeningConflictError, LookupError, PermissionError) as error:
        if strict_source_authority_enabled():
            raise_source_authority_error(error)
        _remember_screening_failure(error)
        raise
    except Exception as error:
        if strict_source_authority_enabled():
            raise_source_authority_error(error)
        failure = DocumentHeldError()
        _remember_screening_failure(failure)
        raise failure from error
    _remember_document_use(document, user_id)
    return dict(document)


def _load_active_units(document, units_reader=None):
    marker = document.get(SCREENING_FIELD) or {}
    reference = marker.get("canonical_ref")
    if not reference:
        raise DocumentHeldError()
    try:
        if units_reader is None:
            # Only an authoritative release marker can select this private artifact.
            storage = import_module("content_screening.storage").ScreeningStorage()
            units_reader = storage.read_json
        units = normalize_units(units_reader(reference, subject_from_document(document)))
    except ScreeningError:
        raise
    except Exception as error:
        raise DocumentHeldError() from error
    if content_fingerprint(units) != marker.get("content_fingerprint"):
        raise ScreeningConflictError()
    return units


def _checked_chunk_result(result, document, units):
    text = result.get("chunk_text")
    if not isinstance(text, str) or not text:
        raise DocumentHeldError()
    source_texts = [
        unit.text for unit in units
        if unit.locator.get("kind") not in {"metadata", "table_cell", "table_formula", "table_sheet"}
    ]
    if any(unit.locator.get("kind") == "table_sheet" for unit in units):
        exports = import_module("content_screening.exports")
        source_texts.append(exports.table_schema_text(units))
    if not any(text in source_text for source_text in source_texts):
        raise ScreeningConflictError()
    checked = dict(result)
    for field in ("file_name", "title", "abstract", "keywords", "tags"):
        if field in checked:
            checked[field] = deepcopy(document.get(field))
    if "author" in checked:
        checked["author"] = deepcopy(document.get("authors", []))
    if "chunk_keywords" in checked:
        checked["chunk_keywords"] = deepcopy(document.get("keywords", []))
    if "chunk_summary" in checked:
        checked["chunk_summary"] = ""
    if "document_tags" in checked:
        checked["document_tags"] = deepcopy(document.get("tags", []))
    if "document_classification" in checked:
        checked["document_classification"] = document.get("document_classification", "None")
    return checked


def filter_available_results(results, user_id=None, *, cached=False, metadata_reader=None, units_reader=None):
    """Exclude inaccessible, held, missing, and stale sources from broad search."""
    user_id = _current_user_id(user_id)
    reader = metadata_reader or _read_authorized_document
    decisions = {}
    active_units = {}
    allowed = []
    for result in results or []:
        if not isinstance(result, Mapping):
            continue
        try:
            arguments = _source_arguments(result, user_id)
            key = (arguments["document_id"], arguments["group_id"], arguments["public_workspace_id"])
            if key not in decisions:
                try:
                    document = reader(**arguments)
                    if not isinstance(document, Mapping) or str(document.get("id")) != arguments["document_id"]:
                        raise DocumentHeldError()
                    _require_available_metadata(document)
                    decisions[key] = document
                except Exception:
                    decisions[key] = None
            document = decisions[key]
            if not document:
                continue
            _check_source_revision(result, document, cached=cached)
            checked = dict(result)
            if SCREENING_FIELD in document:
                if "chunk_text" in result:
                    if key not in active_units:
                        try:
                            active_units[key] = _load_active_units(document, units_reader)
                        except Exception:
                            active_units[key] = None
                    if active_units[key] is None:
                        continue
                    checked = _checked_chunk_result(checked, document, active_units[key])
                for field in ("file_name", "title", "abstract", "keywords", "tags"):
                    if field in checked:
                        checked[field] = deepcopy(document.get(field))
                if "document_tags" in checked:
                    checked["document_tags"] = deepcopy(document.get("tags", []))
                if "document_classification" in checked:
                    checked["document_classification"] = document.get("document_classification", "None")
            checked[PROVENANCE_FIELD] = document_provenance(document)
            allowed.append(checked)
            _remember_document_use(document, user_id)
        except (DocumentHeldError, ScreeningConflictError, PermissionError, LookupError):
            continue
    return allowed


def assert_document_chunks_available(
    chunks, document_or_id, user_id=None, group_id=None, public_workspace_id=None, *,
    expected_chunk_count=None, metadata_reader=None, units_reader=None,
):
    """Validate an explicit ordered read against current canonical content.

    Returns sanitized chunks with provenance. Unlike broad search this raises
    for any stale/held/missing chunk rather than quietly yielding partial input.
    Scanner snapshots must use their separate internal read, not this helper.
    """
    document = assert_document_available(
        document_or_id, user_id, group_id, public_workspace_id,
        purpose="chunks", metadata_reader=metadata_reader,
    )
    chunks = list(chunks or [])
    units = _load_active_units(document, units_reader) if SCREENING_FIELD in document else None
    checked = []
    for chunk in chunks:
        _check_source_revision(chunk, document)
        if units is not None:
            chunk = _checked_chunk_result(chunk, document, units)
        checked.append({**chunk, PROVENANCE_FIELD: document_provenance(document)})
    if (
        SCREENING_FIELD in document and expected_chunk_count is not None
        and len(checked) != int(expected_chunk_count)
    ):
        raise DocumentHeldError()
    assert_document_available(
        {PROVENANCE_FIELD: document_provenance(document)}, user_id,
        purpose="chunks", metadata_reader=metadata_reader,
    )
    return checked


def assert_evidence_available(evidence, user_id=None, *, metadata_reader=None, cached=False, strict_errors=False):
    """Revalidate known workspace provenance before using saved/model evidence."""
    if type(strict_errors) is not bool:
        raise TypeError("The source authority error policy must be server-owned.")
    if strict_errors:
        with strict_source_authority():
            return assert_evidence_available(evidence, user_id, metadata_reader=metadata_reader, cached=cached)
    sources = []
    visited = set()

    def collect(value, native_context=None, native_tool=False):
        if not isinstance(value, (Mapping, list, tuple)) or id(value) in visited:
            return
        visited.add(id(value))
        if isinstance(value, (list, tuple)):
            for item in value:
                collect(item, native_context, native_tool)
            return
        context = dict(native_context or {})
        tool_identity = " ".join(str(value.get(key) or "").lower() for key in ("function_name", "tool_name", "plugin_name"))
        native_tool = native_tool or any(kind in tool_identity for kind in ("tabular", "blobstorage", "blob_storage"))
        arguments = value.get("function_arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (ValueError, TypeError, RecursionError):
                if native_tool:
                    raise DocumentHeldError()
        if isinstance(arguments, Mapping):
            context.update({
                key: arguments[key] for key in (
                    "source", "filename", "group_id", "public_workspace_id",
                    "container_name", "blob_name", "container", "blob_path",
                ) if key in arguments
            })
        chat_only = not value.get("workspace_document_id") and not value.get(PROVENANCE_FIELD) and (
            value.get("scope") == "chat" or value.get("source_type") == "chat_upload" or value.get("source") == "chat"
        )
        if isinstance(value.get(PROVENANCE_FIELD), Mapping):
            sources.append(value)
        elif not chat_only and any(value.get(key) for key in ("document_id", "doc_id", "workspace_document_id", "source_document_id")):
            sources.append(value)
        standalone_chat_file = (
            value.get("role") in {"file", "image"} and not value.get("workspace_document_id")
            and value.get("blob_container") == "personal-chat"
            and not isinstance(value.get(PROVENANCE_FIELD), Mapping)
        )
        native = None if standalone_chat_file else _resolve_native_evidence(
            {**context, **value}, _current_user_id(user_id), resolve_filename=native_tool,
        )
        if native is not None:
            sources.append({
                "document_id": native["id"],
                "group_id": native.get("group_id"),
                "public_workspace_id": native.get("public_workspace_id"),
            })
        for key, item in value.items():
            if key in {"function_result", "function_arguments"} and isinstance(item, str):
                try:
                    item = json.loads(item)
                except (ValueError, TypeError, RecursionError):
                    continue
            if not chat_only and key in {"document_ids", "selected_document_ids"} and isinstance(item, (list, tuple)):
                sources.extend({"document_id": document_id} for document_id in item if isinstance(document_id, str))
            if key != PROVENANCE_FIELD:
                collect(item, context, native_tool or key in {"source_authorization", "source_descriptor"})

    try:
        collect(evidence)
    except (ScreeningError, LookupError, PermissionError) as error:
        _remember_screening_failure(error)
        raise
    proven_sources = {}
    for source in sources:
        provenance = source.get(PROVENANCE_FIELD)
        if isinstance(provenance, Mapping):
            proven_sources.setdefault(str(provenance.get("document_id")), []).append(provenance)
    seen = set()
    for source in sources:
        arguments = _source_arguments(source, user_id)
        key = (
            arguments["document_id"], arguments["group_id"], arguments["public_workspace_id"],
            hash_payload(source.get(PROVENANCE_FIELD)) if PROVENANCE_FIELD in source else source.get("version"),
        )
        if key in seen:
            continue
        seen.add(key)
        document = assert_document_available(source, user_id=user_id, purpose="evidence", metadata_reader=metadata_reader)
        if cached and SCREENING_FIELD in document and not isinstance(source.get(PROVENANCE_FIELD), Mapping):
            proofs = proven_sources.get(str(document.get("id")), [])
            if not proofs or any(dict(proof) != document_provenance(document) for proof in proofs):
                error = ScreeningConflictError()
                _remember_screening_failure(error)
                raise error


def _resolve_native_evidence(value, user_id, *, resolve_filename=False):
    container = value.get("container_name") or value.get("blob_container") or value.get("container")
    path = value.get("blob_name") or value.get("blob_path")
    if isinstance(container, str) and container and isinstance(path, str) and path:
        return assert_blob_available(container, path, user_id, purpose="evidence")
    source = value.get("source")
    filename = value.get("filename")
    if not resolve_filename or source not in {"workspace", "personal", "group", "public"} or not isinstance(filename, str) or not filename:
        return None
    config = import_module("config")
    definitions = {
        "workspace": ("cosmos_user_documents_container", "user_id"),
        "personal": ("cosmos_user_documents_container", "user_id"),
        "group": ("cosmos_group_documents_container", "group_id"),
        "public": ("cosmos_public_documents_container", "public_workspace_id"),
    }
    container_name, scope_field = definitions[source]
    clauses = ["c.file_name = @native_filename"]
    parameters = [{"name": "@native_filename", "value": filename}]
    requested_scope = None
    if scope_field == "user_id":
        clauses.append(
            "(c.user_id = @actor OR ARRAY_CONTAINS(c.shared_user_ids, @actor) "
            "OR ARRAY_CONTAINS(c.shared_user_ids, @approved_actor))"
        )
        parameters.extend([
            {"name": "@actor", "value": user_id},
            {"name": "@approved_actor", "value": f"{user_id},approved"},
        ])
    elif value.get(scope_field):
        requested_scope = value[scope_field]
        clauses.append(f"c.{scope_field} = @native_scope")
        parameters.append({"name": "@native_scope", "value": requested_scope})
    rows = list(getattr(config, container_name).query_items(
        query=f"SELECT TOP 51 * FROM c WHERE {' AND '.join(clauses)}",
        parameters=parameters, enable_cross_partition_query=True,
    ))
    if len(rows) > 50:
        raise DocumentHeldError()
    matches = []
    for row in rows:
        if row.get("file_name") != filename or requested_scope and row.get(scope_field) != requested_scope:
            continue
        try:
            document = _read_authorized_document(
                row["id"], user_id,
                group_id=row.get("group_id"), public_workspace_id=row.get("public_workspace_id"),
            )
        except PermissionError:
            continue
        matches.append(document)
    if len(matches) != 1:
        raise DocumentHeldError()
    _remember_document_use(matches[0], user_id)
    return matches[0]


def refresh_workspace_attachment(message, user_id=None):
    """Replace workspace-backed history with only the currently admitted text."""
    metadata = message.get("metadata") if isinstance(message.get("metadata"), Mapping) else {}
    attachment = metadata.get("workspace_attachment") or {}
    document_id = message.get("workspace_document_id") or (
        attachment.get("document_id") if isinstance(attachment, Mapping) else None
    )
    if not document_id or message.get("role") not in {"file", "image"}:
        return message
    user_id = _current_user_id(user_id)
    document = assert_document_available(document_id, user_id, purpose="history")
    if SCREENING_FIELD not in document:
        return message
    helpers = import_module("functions_documents")
    chunks = helpers.get_ordered_document_chunks(
        document["id"], user_id=user_id, group_id=document.get("group_id"),
        public_workspace_id=document.get("public_workspace_id"),
    )
    chunks = assert_document_chunks_available(chunks, document, user_id)
    text = "\n\n".join(chunk.get("chunk_text", "") for chunk in chunks)
    safe = {
        key: deepcopy(message[key]) for key in (
            "id", "conversation_id", "timestamp", "created_at", "updated_at",
            "is_table", "active_thread", "thread_id",
        ) if key in message
    }
    safe.update({
        "role": "file", "content": "", "file_content": text, "extracted_text": text,
        "filename": document.get("file_name"), "file_name": document.get("file_name"),
        "workspace_document_id": document["id"], "file_content_source": "workspace",
        "vision_analysis": {}, PROVENANCE_FIELD: document_provenance(document),
        "metadata": {
            **({"thread_info": deepcopy(metadata["thread_info"])} if "thread_info" in metadata else {}),
            "workspace_attachment": {
                "document_id": document["id"], "file_name": document.get("file_name"),
                "scope": document_provenance(document)["scope_type"],
                "group_id": document.get("group_id"),
                "public_workspace_id": document.get("public_workspace_id"),
                "status": document.get("status"), SCREENING_FIELD: public_screening_summary(document),
                PROVENANCE_FIELD: document_provenance(document),
            },
        },
    })
    return safe


def public_history_messages(messages, user_id=None):
    """Withhold unavailable source material without deleting ordinary chat text."""
    user_id = _current_user_id(user_id)
    safe_messages = []
    flask = import_module("flask")
    for message in messages or []:
        if not isinstance(message, Mapping):
            continue
        request_context = flask.has_request_context()
        previous_error = getattr(flask.g, "content_screening_error", None) if request_context else None
        previous_sources = dict(getattr(flask.g, "content_screening_sources", {}) or {}) if request_context else {}
        try:
            refreshed = refresh_workspace_attachment(message, user_id)
            assert_evidence_available(refreshed, user_id, cached=True)
        except (ScreeningError, LookupError, PermissionError):
            if request_context:
                flask.g.content_screening_error = previous_error
                flask.g.content_screening_sources = previous_sources
            safe = {
                key: deepcopy(message[key]) for key in (
                    "id", "conversation_id", "role", "timestamp", "created_at", "updated_at",
                    "workspace_document_id", "thread_id", "active_thread",
                ) if key in message
            }
            safe.update({
                "role": "file" if message.get("role") == "image" else message.get("role"),
                "content": "Source content is unavailable pending document screening and review.",
                "file_content": "", "extracted_text": "",
                "agent_citations": [], "hybrid_citations": [], "web_search_citations": [],
                "content_unavailable": True, "content_screening_error": "document_under_review",
            })
            safe_messages.append(safe)
        else:
            # This dispatcher handles per-file denials itself. Operational failures
            # must escape rather than become an unrelated document-screening hold.
            from functions_generated_artifact_sources import sanitize_generated_artifact_history

            safe_messages.append(deepcopy(sanitize_generated_artifact_history(refreshed, user_id)))
    assert_current_request_sources_available(user_id)
    return safe_messages


def assert_current_request_sources_available(user_id=None):
    """Check every source already consumed in this request before a model step."""
    current = _SOURCE_AUTHORITY_SCOPE.get()
    if current is not None and current["failure"] is not None:
        raise current["failure"]
    flask = import_module("flask")
    if flask.has_request_context():
        failure = getattr(flask.g, "content_screening_error", None)
        if failure:
            raise failure
        sources = getattr(flask.g, "content_screening_sources", {}) or {}
        for (actor_id, _scope, _scope_id, _document_id), source in list(sources.items()):
            assert_document_available(source, user_id=user_id or actor_id, purpose="model")


def current_request_source_provenance():
    """Return source identities to persist with an assistant/tool result."""
    flask = import_module("flask")
    if not flask.has_request_context():
        return []
    sources = getattr(flask.g, "content_screening_sources", {}) or {}
    return deepcopy(list(sources.values()))


def guard_chat_service(service, *, source_validator=None):
    """Guard each SK provider call, including automatic tool-call continuations.

    The SDK's public method contains the automatic invocation loop. Guard its
    inner provider methods instead so every loop iteration rechecks provenance.
    Reusable request services retain no identity. A background worker can supply
    a source validator bound to its server-owned run for each provider request.
    """
    if source_validator is not None:
        setattr(service, "_content_screening_source_validator", source_validator)
    if getattr(service, "_content_screening_guarded", False):
        return service

    def validate():
        validator = getattr(service, "_content_screening_source_validator", None)
        if callable(validator):
            validator()
        assert_current_request_sources_available()

    def guard_completion(invoke):
        @wraps(invoke)
        async def guarded(*args, **kwargs):
            validate()
            result = await invoke(*args, **kwargs)
            validate()
            return result
        return guarded

    def guard_stream(invoke):
        @wraps(invoke)
        async def guarded(*args, **kwargs):
            validate()
            stream = invoke(*args, **kwargs)
            try:
                async for result in stream:
                    validate()
                    yield result
            finally:
                if hasattr(stream, "aclose"):
                    await stream.aclose()
            validate()
        return guarded

    for name, wrapper in (
        ("_inner_get_chat_message_contents", guard_completion),
        ("_inner_get_streaming_chat_message_contents", guard_stream),
    ):
        if not callable(getattr(service, name, None)):
            name = name.replace("_inner_", "")
        invoke = getattr(service, name, None)
        if callable(invoke):
            setattr(service, name, wrapper(invoke))
    setattr(service, "_content_screening_guarded", True)
    return service


def guard_model_callable(invoke, evidence, user_id=None):
    """Wrap synchronous model steps, including reductions/retries and results."""
    @wraps(invoke)
    def guarded(*args, **kwargs):
        current_evidence = evidence() if callable(evidence) else evidence
        assert_evidence_available(current_evidence, user_id)
        assert_current_request_sources_available(user_id)
        result = invoke(*args, **kwargs)
        assert_evidence_available(current_evidence, user_id)
        assert_current_request_sources_available(user_id)
        return result
    return guarded


def public_document_payload(document):
    if not isinstance(document, Mapping):
        return {}
    if SCREENING_FIELD not in document:
        return {key: deepcopy(value) for key, value in document.items() if key not in {
            "generated_artifact_publication_binding", "generated_artifact_publication_processing",
        }}
    try:
        _require_available_metadata(document)
        config = import_module("config")
        _require_release_proof(document, config.cosmos_content_screening_container)
        available = True
    except (ScreeningError, AttributeError):
        available = False
    public_fields = HELD_PUBLIC_FIELDS
    if document.get("generated_artifact_publication_binding"):
        public_fields = public_fields | {
            "generated_artifact_promotion_status", "generated_artifact_requested_by_user_id",
            "generated_artifact_requested_by_display_name", "generated_artifact_requested_at",
        }
    payload = {
        key: deepcopy(value) for key, value in document.items()
        if (available or key in public_fields)
        and key not in PRIVATE_DOCUMENT_FIELDS and key != SCREENING_FIELD
        and not key.startswith("_") and not key.startswith("screening_")
    }
    marker = document.get(SCREENING_FIELD)
    summary_source = document
    if not isinstance(marker, dict) or not isinstance(marker.get("state"), str):
        summary_source = {SCREENING_FIELD: None}
    payload[SCREENING_FIELD] = public_screening_summary(summary_source)
    payload[SCREENING_FIELD]["available"] = available
    if not available and payload[SCREENING_FIELD]["state"] in {"cleared", "approved_with_flags"}:
        payload[SCREENING_FIELD]["state"] = "scan_error"
    for field in ("scan_id", "review_id", "updated_at"):
        value = payload[SCREENING_FIELD].get(field)
        if value is not None and not isinstance(value, str):
            payload[SCREENING_FIELD][field] = None
    if not available:
        payload["status"] = "Content screening: document unavailable"
        payload["enhanced_citations"] = False
    return payload


def public_documents_payload(documents, user_id=None, *, metadata_reader=None):
    """Refresh list projections before serializing; never authorize with DAI."""
    actor_id = _current_user_id(user_id)
    payloads = []
    seen = {}
    for document in documents or []:
        if not isinstance(document, Mapping):
            continue
        arguments = _source_arguments(document, actor_id)
        identity = (arguments["document_id"], arguments["group_id"], arguments["public_workspace_id"])
        try:
            if identity not in seen:
                if metadata_reader is None:
                    seen[identity] = _read_authorized_document(**arguments, metadata_only=True)
                else:
                    seen[identity] = metadata_reader(**arguments)
            fresh = seen[identity]
            if not isinstance(fresh, Mapping):
                raise DocumentHeldError()
            safe_extras = {
                key: value for key, value in document.items()
                if key in {"owner_id", "shared_approval_status", "user_role", "userRole", "can_manage", "can_delete"}
            }
            payloads.append(public_document_payload({**safe_extras, **fresh}))
        except (LookupError, PermissionError):
            continue
    return payloads


def register_document_api_guards(blueprint, *, user_resolver=None):
    """Protect ordinary classic/V2 document responses and mutation requests."""
    flask = import_module("flask")

    @blueprint.before_request
    def reject_client_screening_state():
        if flask.request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            try:
                reject_screening_fields(flask.request.get_json(silent=True))
                reject_screening_fields(flask.request.form.to_dict())
            except ScreeningValidationError as error:
                return flask.jsonify({"error": error.public_message, "error_code": error.code}), error.status_code
        return None

    @blueprint.after_request
    def enforce_document_response(response):
        try:
            assert_current_request_sources_available()
            if response.is_json and response.status_code < 300:
                payload = response.get_json()
                if isinstance(payload, dict):
                    actor_id = user_resolver() if user_resolver else _current_user_id()
                    if "id" in payload and ("file_name" in payload or "filename" in payload):
                        refreshed = public_documents_payload([payload], actor_id)
                        payload = refreshed[0] if refreshed else {"error": "Document not found or access denied."}
                        if not refreshed:
                            response.status_code = 404
                    for key in ("documents", "versions"):
                        if isinstance(payload.get(key), list):
                            payload[key] = public_documents_payload(payload[key], actor_id)
                    response.set_data(flask.json.dumps(payload))
        except (DocumentHeldError, ScreeningConflictError) as error:
            response = flask.jsonify({"error": error.public_message, "error_code": error.code})
            response.status_code = error.status_code
        except (LookupError, PermissionError):
            response = flask.jsonify({"error": "Document not found or access denied."})
            response.status_code = 404
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        response.headers.pop("ETag", None)
        return response


def reject_screening_fields(payload):
    """Reject server-managed state in any ordinary document mutation payload."""
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            normalized = str(key).replace("_", "").replace("-", "").lower()
            if normalized.startswith(("contentscreening", "screening")) or normalized in {
                "generatedartifactpublicationbinding", "generatedartifactpublicationprocessing",
                "availabilitygeneration", "activecontentmanifest", "activemanifestid",
                "canonicalref", "unitsref", "resultref", "sourceref",
                "scanid", "reviewid", "contentfingerprint", "sourcerevision",
                "reviewrequired", "sanitized", "activeblob",
            }:
                raise ScreeningValidationError("Content screening fields are server-managed.")
            reject_screening_fields(value)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            reject_screening_fields(value)


def _active_blob_reference(document):
    if SCREENING_FIELD in document:
        marker = document.get(SCREENING_FIELD) or {}
        active_blob = marker.get("active_blob")
        if not isinstance(active_blob, Mapping):
            raise DocumentHeldError()
        container, path = active_blob.get("container"), active_blob.get("path")
        if (
            not container or not path or container == PRIVATE_CONTAINER
            or not active_blob.get("etag") or not active_blob.get("content_hash")
        ):
            raise DocumentHeldError()
        return str(container), str(path)
    # This raw location helper is also used by the scanner; only ordinary
    # callers come through this availability boundary.
    helpers = import_module("functions_documents")
    container, path = helpers.get_document_blob_storage_info(
        document, prefer_archived=document.get("is_current_version") is False,
    )
    if not container or not path or container == PRIVATE_CONTAINER:
        raise DocumentHeldError()
    return str(container), str(path)


def get_available_blob_reference(
    document_or_id, user_id=None, group_id=None, public_workspace_id=None, *,
    purpose="download", metadata_reader=None,
):
    """Return ``(fresh_document, container, path)`` for the active representation.

    Enrolled sources require the release marker's immutable ``active_blob``
    manifest (container, path, etag, content_hash). There is no original fallback.
    """
    document = assert_document_available(
        document_or_id, user_id, group_id, public_workspace_id,
        purpose=purpose, metadata_reader=metadata_reader,
    )
    try:
        container, path = _active_blob_reference(document)
    except (DocumentHeldError, ScreeningConflictError) as error:
        _remember_screening_failure(error)
        raise
    return document, container, path


def _download_available_blob(container, path, document):
    config = import_module("config")
    client = config.CLIENTS["storage_account_office_docs_client"].get_blob_client(
        container=container, blob=path,
    )
    marker = document.get(SCREENING_FIELD) or {}
    active_blob = marker.get("active_blob") or {}
    if SCREENING_FIELD in document:
        match_conditions = import_module("azure.core").MatchConditions
        return client.download_blob(
            etag=active_blob["etag"], match_condition=match_conditions.IfNotModified,
        ).readall()
    return client.download_blob().readall()


def read_available_document_bytes(
    document_or_id, user_id=None, group_id=None, public_workspace_id=None, *,
    purpose="download", metadata_reader=None, blob_reader=None,
):
    """Return ``(fresh_document, bytes)`` after manifest and post-read checks.

    A test-only/in-process ``blob_reader(container, path, document)`` can replace
    Azure I/O. This helper never generates a SAS or reads reviewer-only storage.
    """
    document, container, path = get_available_blob_reference(
        document_or_id, user_id, group_id, public_workspace_id,
        purpose=purpose, metadata_reader=metadata_reader,
    )
    try:
        content = (blob_reader or _download_available_blob)(container, path, document)
    except ScreeningError:
        raise
    except Exception as error:
        failure = DocumentHeldError()
        _remember_screening_failure(failure)
        raise failure from error
    if SCREENING_FIELD in document:
        expected_hash = document[SCREENING_FIELD]["active_blob"]["content_hash"]
        if not isinstance(content, bytes) or hashlib.sha256(content).hexdigest() != expected_hash:
            error = ScreeningConflictError()
            _remember_screening_failure(error)
            raise error
    assert_document_available(
        {PROVENANCE_FIELD: document_provenance(document)}, user_id,
        purpose=purpose, metadata_reader=metadata_reader,
    )
    return document, content


def build_available_document_response(document_or_id, user_id=None, *, purpose="preview"):
    """Serve an active representation without a raw SAS or executable HTML."""
    document, content = read_available_document_bytes(document_or_id, user_id=user_id, purpose=purpose)
    file_name = import_module("werkzeug.utils").secure_filename(document.get("file_name") or "document")
    content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    inline_types = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"}
    disposition = "inline" if content_type in inline_types else "attachment"
    response = import_module("flask").Response(content, content_type=content_type)
    response.headers["Content-Disposition"] = f'{disposition}; filename="{file_name}"'
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _resolve_blob_document(container_name, blob_name, user_id):
    config = import_module("config")
    if container_name == config.storage_account_personal_chat_container_name:
        parts = str(blob_name).split("/")
        if len(parts) < 3:
            raise PermissionError("Chat file is not authorized.")
        conversation_id = parts[1]
        conversation = config.cosmos_conversations_container.read_item(
            item=conversation_id, partition_key=conversation_id,
        )
        import_module("functions_collaboration").build_conversation_participation_context(user_id, conversation)
        if "/generated/tabular_runs/" in str(blob_name):
            raise DocumentHeldError()
        messages = list(config.cosmos_messages_container.query_items(
            query=(
                "SELECT c.workspace_document_id FROM c "
                "WHERE c.blob_container = @container AND c.blob_path = @path"
            ),
            parameters=[
                {"name": "@container", "value": container_name},
                {"name": "@path", "value": blob_name},
            ],
            partition_key=conversation_id,
        ))
        linked_ids = {
            message["workspace_document_id"] for message in messages
            if message.get("workspace_document_id")
        }
        if len(linked_ids) > 1:
            raise DocumentHeldError()
        if linked_ids:
            return _read_authorized_document(str(next(iter(linked_ids))), user_id)
        return None
    containers = {
        config.storage_account_user_documents_container_name: ("cosmos_user_documents_container", "user_id"),
        config.storage_account_group_documents_container_name: ("cosmos_group_documents_container", "group_id"),
        config.storage_account_public_documents_container_name: ("cosmos_public_documents_container", "public_workspace_id"),
    }
    target = containers.get(container_name)
    if not target:
        return None
    parts = str(blob_name).split("/")
    if len(parts) < 2 or not parts[0]:
        raise DocumentHeldError()
    container = getattr(config, target[0])
    rows = container.query_items(
        query=(
            f"SELECT * FROM c WHERE c.{target[1]} = @scope_id AND "
            "(c.blob_path = @path OR c.archived_blob_path = @path OR c.file_name = @file_name)"
        ),
        parameters=[
            {"name": "@scope_id", "value": unquote(parts[0])},
            {"name": "@path", "value": blob_name},
            {"name": "@file_name", "value": unquote(parts[-1])},
        ],
        enable_cross_partition_query=True,
    )
    for row in rows:
        scope_id = row.get(target[1])
        legacy_path = f"{scope_id}/{row.get('file_name', '')}"
        marker = row.get(SCREENING_FIELD)
        active_blob = marker.get("active_blob", {}) if isinstance(marker, Mapping) else {}
        paths = {row.get("blob_path"), row.get("archived_blob_path"), legacy_path, active_blob.get("path")}
        if blob_name not in paths:
            continue
        # The query only locates the document. The point read is the decision.
        return _read_authorized_document(
            str(row["id"]), user_id,
            group_id=scope_id if target[1] == "group_id" else None,
            public_workspace_id=scope_id if target[1] == "public_workspace_id" else None,
        )
    raise DocumentHeldError()


def assert_blob_available(
    container_name, blob_name, user_id=None, *, purpose="native", document_resolver=None,
):
    """Gate fresh/cached native bytes; return their current document or ``None``.

    ``None`` means a non-workspace container (for example a chat-only upload);
    its existing authorization still applies. The reserved private container is
    always denied, even if it appears in a remembered authorized-location list.
    ``document_resolver(container_name, blob_name, user_id)`` must return freshly
    authorized metadata, never a cached positive decision.
    """
    if str(container_name).lower() == PRIVATE_CONTAINER:
        raise DocumentHeldError()
    user_id = _current_user_id(user_id)
    document = _read_blob_document_safely(container_name, blob_name, user_id, document_resolver)
    if document is None:
        return None
    try:
        _require_available_metadata(document)
        if SCREENING_FIELD in document:
            if _active_blob_reference(document) != (container_name, blob_name):
                raise DocumentHeldError()
    except (DocumentHeldError, ScreeningConflictError) as error:
        if purpose != "enumeration":
            _remember_screening_failure(error)
        raise
    _remember_document_use(document, user_id)
    return dict(document)


def _read_blob_document_safely(container_name, blob_name, user_id, document_resolver=None):
    try:
        return (document_resolver or _resolve_blob_document)(container_name, blob_name, user_id)
    except (ScreeningError, LookupError, PermissionError):
        raise
    except Exception as error:
        raise DocumentHeldError() from error


def resolve_available_blob_location(container_name, blob_name, user_id=None):
    """Map an authorized workspace-linked chat file to its active clean source."""
    if str(container_name).lower() == PRIVATE_CONTAINER:
        raise DocumentHeldError()
    user_id = _current_user_id(user_id)
    document = _read_blob_document_safely(container_name, blob_name, user_id)
    if document is None:
        return container_name, blob_name
    document = assert_document_available(document, user_id=user_id, purpose="native")
    if SCREENING_FIELD in document:
        return _active_blob_reference(document)
    return container_name, blob_name
