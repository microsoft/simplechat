# publication.py
"""Application-side projection of inspected canonical content."""

import hashlib
import json
import mimetypes
from urllib.parse import quote

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import ContentSettings
from werkzeug.utils import secure_filename

from content_screening.contracts import (
    SCREENING_FIELD,
    ContentUnit,
    ScreeningConflictError,
    ScreeningError,
    ScreeningValidationError,
    subject_from_document,
)
from content_screening.exports import build_clean_artifact, structured_sheets, table_schema_text
from content_screening.extraction import heartbeat_publication, is_publication, publication_chunks


def _document_helpers():
    # The document module imports the reusable contracts; defer this reverse edge.
    import functions_documents

    return functions_documents


def existing_chunks(document):
    helpers = _document_helpers()
    subject = subject_from_document(document)
    client = helpers._get_search_client(
        group_id=subject.scope_id if subject.scope_type == "group" else None,
        public_workspace_id=subject.scope_id if subject.scope_type == "public" else None,
    )
    document_id = subject.document_id.replace("'", "''")
    chunks = list(client.search(
        search_text="*", filter=f"document_id eq '{document_id}'",
        select="id,document_id,chunk_text,page_number,chunk_sequence,file_name",
    ))
    return sorted(chunks, key=lambda item: (item.get("chunk_sequence") or 0, item.get("id") or ""))


def source_bytes(document):
    helpers = _document_helpers()
    container, path = helpers.get_document_blob_storage_info(
        document, prefer_archived=document.get("is_current_version") is False,
    )
    if not container or not path:
        return None
    client = helpers._get_blob_service_client().get_blob_client(container=container, blob=path)
    try:
        properties = client.get_blob_properties()
    except ResourceNotFoundError:
        return None
    owner = (properties.metadata or {}).get("document_id")
    if owner and owner != document["id"]:
        raise ScreeningConflictError("The stored source no longer belongs to this document.")
    return client.download_blob(
        etag=properties.etag, match_condition=MatchConditions.IfNotModified,
    ).readall()


def _metadata_from_units(units, file_name):
    metadata = {
        "title": file_name, "authors": [], "abstract": "", "keywords": [],
        "organization": "", "publication_date": "", "vision_analysis": None,
        "vision_description": "", "vision_objects": [], "vision_extracted_text": "",
        "tags": [], "document_classification": "None",
    }
    for unit in units:
        if unit.locator.get("kind") != "metadata":
            continue
        name = unit.locator.get("field")
        if name in {"authors", "keywords", "tags"}:
            try:
                value = json.loads(unit.text)
            except (ValueError, TypeError) as error:
                raise ScreeningValidationError("Reviewed metadata contains an invalid list.") from error
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ScreeningValidationError("Reviewed metadata contains an invalid list.")
            metadata[name] = value
        elif name in {"title", "abstract", "organization", "publication_date", "document_classification"}:
            metadata[name] = unit.text
    return metadata


def _project_blob(document, scan, file_name, content, content_type):
    helpers = _document_helpers()
    subject = subject_from_document(document)
    container = helpers._get_blob_container_name(
        group_id=subject.scope_id if subject.scope_type == "group" else None,
        public_workspace_id=subject.scope_id if subject.scope_type == "public" else None,
    )
    name = secure_filename(file_name) or "reviewed-document.txt"
    path = "/".join((
        quote(subject.scope_id, safe=""), quote(subject.document_id, safe=""),
        "screened", quote(scan["id"], safe=""), name,
    ))
    client = helpers._get_blob_service_client()
    container_client = helpers._ensure_blob_container_ready(client, container)
    blob = container_client.get_blob_client(path)
    fingerprint = hashlib.sha256(content).hexdigest()
    metadata = {
        "document_id": subject.document_id,
        "screening_scan_id": scan["id"],
        "screening_content_hash": fingerprint,
    }
    try:
        blob.upload_blob(
            content, overwrite=False, metadata=metadata,
            content_settings=ContentSettings(content_type=content_type),
        )
    except ResourceExistsError:
        existing = blob.get_blob_properties()
        if (existing.metadata or {}) != metadata:
            raise ScreeningConflictError("A different source projection already exists.")
    properties = blob.get_blob_properties()
    return {
        "file_name": file_name, "blob_container": container, "blob_path": path,
        "blob_path_mode": "screened_revision", "archived_blob_path": None,
        "blob_etag": properties.etag, "blob_content_hash": fingerprint,
        "source_file_available": True, "enhanced_citations": True,
        "file_size": len(content),
    }


def _remove_previous_raw_projection(document, scan, projection, storage):
    previous = scan.get("previous_blob") or {}
    if (
        not scan.get("sanitized") or not previous.get("container") or not previous.get("path")
        or (previous["container"], previous["path"]) == (projection["blob_container"], projection["blob_path"])
    ):
        return
    helpers = _document_helpers()
    blob = helpers._get_blob_service_client().get_blob_client(
        container=previous["container"], blob=previous["path"],
    )
    try:
        properties = blob.get_blob_properties()
    except ResourceNotFoundError:
        return
    current = blob.download_blob(
        etag=properties.etag, match_condition=MatchConditions.IfNotModified,
    ).readall()
    previous_marker = scan.get("previous_marker") or {}
    active_blob = previous_marker.get("active_blob") or {}
    if previous_marker.get("sanitized"):
        if (
            active_blob.get("container") != previous["container"]
            or active_blob.get("path") != previous["path"]
            or active_blob.get("etag") != properties.etag
            or active_blob.get("content_hash") != hashlib.sha256(current).hexdigest()
        ):
            raise ScreeningConflictError("The previous clean source changed after inspection.")
    else:
        if not scan.get("source_ref"):
            raise ScreeningConflictError("An original source appeared after this scan. Inspect it before release.")
        if hashlib.sha256(current).digest() != hashlib.sha256(
            storage.read_bytes(scan["source_ref"], subject_from_document(document))
        ).digest():
            raise ScreeningConflictError("The original source changed after it was inspected.")
    blob.delete_blob(
        etag=properties.etag, match_condition=MatchConditions.IfNotModified,
        delete_snapshots="include",
    )


def publish_document(document, units, scan, actor_id, *, storage):
    helpers = _document_helpers()
    subject = subject_from_document(document)
    marker = document.get(SCREENING_FIELD) or {}
    if (
        marker.get("state") != "publishing" or marker.get("scan_id") != scan["id"]
        or not is_publication(subject, scan["id"])
    ):
        raise ScreeningConflictError()
    if scan.get("sanitized") or not scan.get("source_ref"):
        artifact = build_clean_artifact(units, subject.document_id, scan["original_file_name"])
        file_name, content, content_type = artifact.file_name, artifact.content, artifact.content_type
    else:
        file_name = document.get("file_name") or scan["original_file_name"]
        content = storage.read_bytes(scan["source_ref"], subject)
        content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    metadata = _metadata_from_units(units, file_name)
    settings = helpers.get_settings()
    max_characters = min(
        helpers.get_embedding_safe_chunk_characters(settings),
        max(1, helpers.get_embedding_usable_tokens(settings) // 4),
    )
    if structured_sheets(units):
        chunks = publication_chunks([
            ContentUnit("table-schema", table_schema_text(units), {"kind": "schema"}),
        ], max_characters)
    else:
        chunks = publication_chunks(units, max_characters)
    if not chunks:
        raise ScreeningValidationError("No reviewed content is available to publish.")
    scope_args = {
        "group_id": subject.scope_id if subject.scope_type == "group" else None,
        "public_workspace_id": subject.scope_id if subject.scope_type == "public" else None,
    }
    client = helpers._get_search_client(**scope_args)
    projection = _project_blob(document, scan, file_name, content, content_type)
    helpers.delete_document_chunks(subject.document_id, **scope_args)
    total_tokens, model_name = 0, None
    batch = []
    is_archived = document.get("is_current_version") is False or document.get("search_visibility_state") == "archived"
    scope_value = helpers._build_archived_scope_value(subject.scope_id) if is_archived else subject.scope_id
    scope_field = {"personal": "user_id", "group": "group_id", "public": "public_workspace_id"}[subject.scope_type]
    for chunk in chunks:
        heartbeat_publication()
        embedded = helpers.generate_embedding(chunk["chunk_text"])
        if embedded is None:
            raise ScreeningError(code="screening_embedding_failed")
        embedding, usage = embedded if isinstance(embedded, tuple) else (embedded, {})
        if not embedding:
            raise ScreeningError(code="screening_embedding_failed")
        total_tokens += int((usage or {}).get("total_tokens") or 0)
        model_name = model_name or (usage or {}).get("model_deployment_name")
        sequence = chunk["chunk_sequence"]
        item = {
            "id": f"{subject.document_id}_{sequence}",
            "document_id": subject.document_id, "chunk_id": str(sequence),
            "chunk_sequence": sequence, "page_number": chunk.get("page_number"),
            "chunk_text": chunk["chunk_text"], "embedding": embedding,
            "file_name": projection["file_name"], "version": int(document.get("version") or 1),
            "title": metadata["title"], "author": metadata["authors"],
            "chunk_keywords": metadata["keywords"], "chunk_summary": "",
            "document_classification": metadata["document_classification"],
            "document_tags": metadata["tags"],
            "upload_date": document.get("upload_date"),
            scope_field: scope_value,
        }
        if subject.scope_type == "personal":
            item["shared_user_ids"] = [] if is_archived else document.get("shared_user_ids", [])
        elif subject.scope_type == "group":
            item["shared_group_ids"] = [] if is_archived else document.get("shared_group_ids", [])
        batch.append(item)
        if len(batch) == 32:
            helpers._execute_document_search_write(client, "upload_documents", documents=batch)
            batch = []
    if batch:
        helpers._execute_document_search_write(client, "upload_documents", documents=batch)
    _remove_previous_raw_projection(document, scan, projection, storage)
    return {
        **metadata, **projection, "num_chunks": len(chunks), "number_of_pages": len(chunks),
        "embedding_tokens": total_tokens, "embedding_model_deployment_name": model_name,
        "current_file_chunk": None,
    }
