# test_publication_native_processing.py
"""
Native document processing evidence for workflow publication completion.
Version: 0.261.118
Implemented in: 0.261.118

The real upload dispatcher, chunk writes and screening release run against the
shared closed pipeline fixture. Readiness never invokes a second native job.
"""

import hashlib

import pytest

from test_content_screening_pipeline import pipeline, save_empty_baseline  # noqa: F401
from content_screening import access, service
from content_screening.contracts import SCREENING_FIELD, Subject
from functions_artifact_publication_readiness import (
    PUBLICATION_BINDING, PUBLICATION_PROCESSING, inspect_publication_readiness, publication_handoff_observed,
)


@pytest.mark.parametrize("screened,bypass_wrapper", [(False, False), (True, False), (True, True)])
def test_real_native_completion_proves_the_exact_receipt_projection(pipeline, tmp_path, screened, bypass_wrapper):
    if not screened:
        save_empty_baseline(pipeline)
    content = b"Ordinary original artifact content. All of these words must reach the native index."
    receipt = {
        "id": "a" * 64, "document_id": "publication-document", "document_version": 1,
        "actor_user_id": "owner", "destination": {"workspace_scope": "personal"},
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "artifact_reference": {"conversation_id": "conversation", "artifact_message_id": "artifact"},
    }
    document = {
        "id": receipt["document_id"], "user_id": "owner", "version": 1, "file_name": "artifact.txt",
        "is_current_version": True, "upload_date": "2026-09-18T17:00:00Z",
        "num_chunks": 0, "number_of_pages": 0,
        "generated_artifact_publication_receipt_id": receipt["id"],
        PUBLICATION_BINDING: {
            "version": 1, "receipt_id": receipt["id"], "document_version": 1,
            "content_sha256": receipt["content_sha256"], **receipt["artifact_reference"],
        },
    }
    marker = service.initial_document_marker(document)
    if marker is not None:
        document[SCREENING_FIELD] = marker
    pipeline.repository.document_container("personal").create_item(document)
    source = tmp_path / "artifact.txt"
    source.write_bytes(content)
    arguments = {"document_id": document["id"], "user_id": "owner", "temp_file_path": str(source), "original_filename": source.name}
    if bypass_wrapper:
        service.prepare_document_upload(**arguments)
        service.process_screened_upload(**arguments, processor=pipeline.helpers._process_document_upload_background_impl)
    else:
        pipeline.helpers.process_document_upload_background(**arguments)
    current = pipeline.repository.read_document(Subject("personal", "owner", document["id"], "1"))
    indexed = [
        chunk for chunk in pipeline.search.documents.values()
        if chunk.get("document_id") == document["id"] and chunk.get("version") == 1 and chunk.get("user_id") == "owner"
    ]
    assert indexed
    observed = inspect_publication_readiness(receipt, current, index_count=lambda *args: len(indexed))
    assert observed["processing"] == "complete" and observed["index"] == "ready"
    assert observed["screening"] == ("available" if screened else "not_required")
    if bypass_wrapper:
        assert PUBLICATION_PROCESSING not in current
    assert publication_handoff_observed(receipt, current)
    public = access.public_document_payload(current)
    assert PUBLICATION_BINDING not in public and "generated_artifact_publication_processing" not in public
