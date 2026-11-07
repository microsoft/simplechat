# test_document_transform_sources.py
"""
Functional tests for native Office reference intake and current-authority consumption.
Version: 0.261.321
Implemented in: 0.261.321

Real guarded packages and screening byte access run against isolated in-memory storage.
The existing generated-artifact route boundary is executed with scoped storage and
publication callbacks. No filesystem source locator, SAS, Azure or model call is used.
"""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosResourceNotFoundError

APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

from content_screening.contracts import ContentUnit, DocumentHeldError, ScreeningConflictError
from content_screening.extraction import ExtractionCapture, publication_context
from content_screening import publication
from functions_chat_upload_extraction import build_workspace_upload_file_content
from functions_document_transform_sources import (
    DocumentTransformSources, OFFICE_REFERENCE_MIME_TYPES, TEMPLATE_EXTENSIONS, native_template_pages,
)
from functions_document_transform import DocumentTransformError
from test_content_screening_access import ScreeningAccessFixture, access
from test_document_transform_core import archive_bytes, fixture_files, source_bytes, WORD_NS, PPT_NS, OFFICE_REL_NS, REL_NS
from test_support.app_source import run_definitions
from test_content_screening_pipeline import pipeline, save_empty_baseline  # noqa: F401
from test_orchestration_services import services, runtime, checkpoint_factory
from test_support.orchestration_results import ResultFixture
from functions_orchestration_context import build_capability_request_context
from content_screening import service


def blank_template(extension):
    files = fixture_files(extension)
    if extension in {".docx", ".dotx"}:
        files["word/document.xml"] = (
            f'<w:document xmlns:w="{WORD_NS}"><w:body><w:p/></w:body></w:document>'
        ).encode()
    return archive_bytes(files)


@pytest.fixture
def document_source():
    fixture = ScreeningAccessFixture()
    fixture.setUp()
    fixture.content = source_bytes()
    fixture.document["file_name"] = "reference.docx"
    fixture.document["content_screening"]["active_blob"]["content_hash"] = hashlib.sha256(fixture.content).hexdigest()
    fixture.seed_release(fixture.document)

    def read_document(document_id):
        with access.strict_source_authority():
            return access.read_available_document_bytes(document_id, user_id="user-1", purpose="native")

    sources = DocumentTransformSources(
        user_id="user-1", conversation_id="conversation-1",
        read_conversation=lambda cid: fixture.conversations.read_item(cid, cid),
        read_document_metadata=lambda did: access.assert_document_available(did, user_id="user-1", strict_errors=True),
        read_document_bytes=read_document,
        authorize_artifact=lambda *args: pytest.fail("Document source entered artifact authorization."),
        open_artifact_stream=lambda *args, **kwargs: pytest.fail("Document source entered artifact transport."),
    )
    try:
        yield fixture, sources
    finally:
        fixture.doCleanups()


def test_document_reference_reads_only_screening_active_bytes_and_safe_metadata(document_source):
    fixture, sources = document_source
    handle = {"kind": "document", "document_id": "document-1"}
    reference = {"handle": handle, "extension": ".docx", "content_sha256": hashlib.sha256(fixture.content).hexdigest()}
    content = sources.read_reference(reference)
    metadata = sources.describe_reference(handle)
    resolved = sources.resolve_reference(handle)
    assert content == fixture.content
    assert fixture.blob_requests == [("user-documents", fixture.document["content_screening"]["active_blob"]["path"])]
    assert metadata["handle"] == handle and metadata["extension"] == ".docx"
    assert resolved["file_name"] == "reference.docx"
    assert resolved["source"] == {
        "document_id": "document-1", "scope": "personal", "scope_id": "user-1",
        "source_version": fixture.document.get("version"),
        "source_revision": fixture.document.get("_etag"),
        "authorization_status": "authorized",
    }
    assert metadata["source"] == resolved["source"]
    assert not any(field in metadata for field in ("blob_path", "blob_container", "sas_url", "connection"))


@pytest.mark.parametrize("failure", ["held", "revoked", "deleted", "cross_user", "digest", "extension", "sanitized"])
def test_document_reference_rechecks_current_access_and_revision(document_source, failure):
    fixture, sources = document_source
    reference = {
        "handle": {"kind": "document", "document_id": "document-1"},
        "extension": ".docx", "content_sha256": hashlib.sha256(fixture.content).hexdigest(),
    }
    if failure == "held":
        fixture.hold()
    elif failure == "revoked":
        fixture.document.update(user_id="owner-2", shared_user_ids=[])
        fixture.seed_release(fixture.document)
    elif failure == "deleted":
        fixture.documents.clear()
        for container in (fixture.personal, fixture.groups, fixture.public):
            container.failure = CosmosResourceNotFoundError()
    elif failure == "cross_user":
        fixture.conversations.documents["conversation-1"]["user_id"] = "other-user"
    elif failure == "digest":
        reference["content_sha256"] = "0" * 64
    elif failure == "extension":
        reference["extension"] = ".dotx"
    elif failure == "sanitized":
        fixture.document["file_name"] = "reference.txt"
    with pytest.raises((PermissionError, LookupError, DocumentHeldError, DocumentTransformError)):
        sources.read_reference(reference)
    if failure not in {"digest", "extension", "sanitized"}:
        assert fixture.blob_requests == []


def test_document_hold_during_byte_read_is_not_downgraded_to_draft(document_source):
    fixture, sources = document_source
    fixture.after_blob_read = fixture.hold
    with pytest.raises((DocumentHeldError, ScreeningConflictError)):
        sources.read_reference({"kind": "document", "document_id": "document-1"})


def test_reference_resolver_uses_only_current_authorized_provenance_and_valid_revision(document_source):
    fixture, sources = document_source
    handle = {"kind": "document", "document_id": "document-1"}
    fixture.hold()
    with pytest.raises(DocumentHeldError):
        sources.resolve_reference(handle)
    sources.read_document_metadata = lambda did: {
        "id": did, "file_name": "reference.docx", "user_id": "user-1", "version": {"unexpected": "value"},
    }
    with pytest.raises(DocumentTransformError):
        sources.resolve_reference(handle)


@pytest.mark.parametrize("scope", ["group", "public"])
def test_native_document_reader_preserves_current_group_and_public_access(document_source, scope):
    fixture, sources = document_source
    fixture.personal.documents.clear()
    fixture.personal.failure = CosmosResourceNotFoundError()
    container = fixture.groups if scope == "group" else fixture.public
    if scope == "public":
        fixture.groups.failure = CosmosResourceNotFoundError()
    scope_id = "group-1" if scope == "group" else "workspace-1"
    scope_field = "group_id" if scope == "group" else "public_workspace_id"
    fixture.document[scope_field] = scope_id
    fixture.document["content_screening"]["active_blob"].update(
        container=f"{scope}-documents", path=f"{scope_id}/approved/reference.docx",
    )
    container.documents["document-1"] = fixture.document
    fixture.seed_release(fixture.document)
    handle = {"kind": "document", "document_id": "document-1"}
    content = sources.read_reference(handle)
    metadata = sources.describe_reference(handle)
    assert content == fixture.content and metadata["scope"] == scope and metadata["scope_id"] == scope_id
    fixture.blob_requests.clear()
    if scope == "group":
        fixture.memberships.clear()
    else:
        fixture.workspace_ids.clear()
    with pytest.raises((PermissionError, LookupError, DocumentHeldError)):
        sources.read_reference(handle)
    assert not fixture.blob_requests


@pytest.mark.parametrize("reference", [
    {"kind": "document", "document_id": "document-1", "blob_path": "foreign/path"},
    {"kind": "blob", "sas_url": "https://example.invalid/private"},
    {"kind": "artifact", "conversation_id": "conversation-1", "message_id": "../message"},
    {"handle": {"kind": "document", "document_id": "document-1"}, "extension": ".docx", "content_sha256": "x"},
    {"handle": {"kind": "document", "document_id": "document-1"}, "extension": [".docx"], "content_sha256": "0" * 64},
])
def test_locators_and_malformed_handles_are_never_consumed(document_source, reference):
    fixture, sources = document_source
    with pytest.raises(DocumentTransformError):
        sources.read_reference(reference)
    assert fixture.blob_requests == []


@pytest.fixture
def artifact_source():
    content = source_bytes()
    conversation = {"id": "conversation-1", "user_id": "user-1"}
    artifact = {
        "id": "message-1", "conversation_id": "conversation-1", "role": "file",
        "filename": "result.docx", "file_content_source": "blob", "_etag": "m1",
        "blob_container": "personal-chat", "blob_path": "owner/conversation-1/generated/result.docx",
        "metadata": {
            "is_generated_chat_artifact": True,
            "generated_artifact_content_sha256": hashlib.sha256(content).hexdigest(),
            "generated_artifact_size_bytes": len(content),
        },
    }
    state = {"published": True, "approved": True, "content": content, "after_read": None}
    reads = []

    class NotFound(Exception):
        pass

    def participate(user_id, document):
        if document["user_id"] != user_id or document.get("deleted"):
            raise PermissionError("Conversation access denied.")

    def publication_check(user_id, document):
        if not state["published"]:
            raise PermissionError("Artifact is not published.")

    def approval_check(user_id, document):
        if not state["approved"]:
            raise PermissionError("Artifact is awaiting approval.")

    namespace = {
        "CosmosResourceNotFoundError": NotFound,
        "cosmos_conversations_container": SimpleNamespace(read_item=lambda **kwargs: deepcopy(conversation)),
        "cosmos_messages_container": SimpleNamespace(read_item=lambda **kwargs: deepcopy(artifact)),
        "build_conversation_participation_context": participate,
        "assert_generated_chat_artifact_is_published_for_user": publication_check,
        "assert_generated_file_approval_allows_download": approval_check,
        "assert_document_available": lambda *args, **kwargs: pytest.fail("Artifact reauthorized original documents."),
    }
    run_definitions("route_enhanced_citations.py", {"_get_authorized_chat_artifact_message"}, namespace)

    @contextmanager
    def open_stream(record, *, check):
        check()
        reads.append((record["blob_container"], record["blob_path"]))
        yield io.BytesIO(state["content"])
        if state["after_read"]:
            state["after_read"]()
        check()

    sources = DocumentTransformSources(
        user_id="user-1", conversation_id="conversation-1",
        read_conversation=lambda cid: deepcopy(conversation),
        read_document_metadata=lambda did: pytest.fail("Artifact entered document metadata."),
        read_document_bytes=lambda did: pytest.fail("Artifact entered document bytes."),
        authorize_artifact=namespace["_get_authorized_chat_artifact_message"],
        open_artifact_stream=open_stream, list_artifacts=lambda cid: [artifact],
    )
    return SimpleNamespace(
        sources=sources, artifact=artifact, conversation=conversation, state=state, reads=reads,
        handle={"kind": "artifact", "conversation_id": "conversation-1", "message_id": "message-1"},
    )


def test_same_conversation_generated_file_is_a_native_reference_without_promotion(artifact_source):
    fixture = artifact_source
    candidates = fixture.sources.planning_candidates()
    content = fixture.sources.read_reference(fixture.handle)
    assert candidates[0]["handle"] == fixture.handle
    assert candidates[0]["content_sha256"] == hashlib.sha256(content).hexdigest()
    assert content == fixture.state["content"]
    assert len(fixture.reads) == 1
    resolved = fixture.sources.resolve_reference(fixture.handle)
    assert resolved == {"file_name": "result.docx", "source": None}
    metadata = fixture.sources.describe_reference(fixture.handle)
    assert metadata["source"] is None


def test_reference_candidates_are_bounded_and_skip_invalid_optional_artifacts(document_source, artifact_source):
    _fixture, sources = document_source
    sources.read_document_metadata = lambda did: {"id": did, "file_name": "reference.docx", "user_id": "user-1"}
    candidates = sources.planning_candidates([f"document-{number}" for number in range(30)])
    assert len(candidates) == 15
    artifact_source.sources.list_artifacts = lambda cid: [
        {"id": "../invalid", "file_name": "invalid.docx"}, artifact_source.artifact,
    ]
    candidates = artifact_source.sources.planning_candidates()
    assert len(candidates) == 1 and candidates[0]["handle"] == artifact_source.handle


@pytest.mark.parametrize("failure", [
    "other_conversation", "cross_user", "conversation_deleted", "message_deleted", "masked",
    "approval_revoked", "unpublished", "unbound", "digest", "message_changed",
])
def test_artifact_reference_preserves_live_container_and_publication_access(artifact_source, failure):
    fixture = artifact_source
    if failure == "other_conversation":
        fixture.handle["conversation_id"] = "other-conversation"
    elif failure == "cross_user":
        fixture.conversation["user_id"] = "other-user"
    elif failure == "conversation_deleted":
        fixture.conversation["deleted"] = True
    elif failure == "message_deleted":
        fixture.artifact["metadata"]["is_deleted"] = True
    elif failure == "masked":
        fixture.artifact["metadata"]["masked"] = True
    elif failure == "approval_revoked":
        fixture.state["approved"] = False
    elif failure == "unpublished":
        fixture.state["published"] = False
    elif failure == "unbound":
        fixture.artifact["metadata"].pop("generated_artifact_content_sha256")
    elif failure == "digest":
        fixture.state["content"] = source_bytes(".dotx")
    elif failure == "message_changed":
        fixture.state["after_read"] = lambda: fixture.artifact.update(_etag="m2")
    with pytest.raises((PermissionError, LookupError, DocumentTransformError)):
        fixture.sources.read_reference(fixture.handle)
    if failure not in {"digest", "message_changed"}:
        assert fixture.reads == []


@pytest.mark.parametrize("extension", [".dotx", ".potx"])
@pytest.mark.parametrize("screened", [False, True])
def test_blank_template_ingestion_retains_exact_source_without_di_or_indexing(extension, screened):
    content = blank_template(extension)
    capture = ExtractionCapture(
        subject=publication.subject_from_document({"id": "document-1", "user_id": "user-1", "version": 1}),
        scan_id="scan-1", file_name=f"blank{extension}",
    )
    retained = []
    updates = []
    namespace = {
        "open": lambda *args, **kwargs: io.BytesIO(content),
        "native_template_pages": native_template_pages, "current_extraction": lambda did: capture if screened else None,
        "json": json, "ContentUnit": ContentUnit, "get_settings": lambda: {},
        "get_chunk_size_config": lambda settings: {}, "WORD_CHUNK_SIZE": 1000,
        "chunk_word_file_into_pages": lambda **kwargs: kwargs["di_pages"],
        "_build_office_embedded_image_chunks": lambda *args: ([], 0, "native", 0),
        "upload_to_blob": lambda *args, **kwargs: retained.append(content),
        "save_chunks": lambda **kwargs: pytest.fail("Blank template cannot create an index chunk."),
    }
    run_definitions("functions_documents.py", {"process_office_template"}, namespace)
    result = namespace["process_office_template"](
        "document-1", "user-1", "in-memory", f"blank{extension}", extension, False,
        lambda **kwargs: updates.append(kwargs),
    )
    assert retained == [content] and result == (0, 0, None)
    assert updates[-1]["office_template_structure"]["extension"] == extension
    if screened:
        capture.completed = True
        units = capture.finish({})
        assert units[0].locator == {"kind": "metadata", "field": "office_template_structure"}
        assert any(
            unit.locator.get("field") == "office_template_package_text" and "original" in unit.text
            for unit in units
        )
        assert publication.publication_chunks(units, 1000) == []


@pytest.mark.parametrize("extension", [".dotx", ".potx"])
@pytest.mark.parametrize("failure", [None, "not_template", "sanitized", "unbound"])
def test_blank_screened_template_can_release_native_bytes_with_zero_search_chunks(monkeypatch, extension, failure):
    content = blank_template(extension)
    document = {
        "id": "document-1", "user_id": "user-1", "version": 1, "file_name": f"blank{extension}",
        "content_screening": {"state": "publishing", "scan_id": "scan-1"},
    }
    units = [ContentUnit("structure", "native template structure", {"kind": "metadata", "field": "office_template_structure"})]
    scan = {"id": "scan-1", "original_file_name": document["file_name"], "source_ref": {"bound": True}}
    if failure == "not_template":
        native_extension = ".docx" if extension == ".dotx" else ".pptx"
        document["file_name"] = f"blank{native_extension}"
        content = blank_template(native_extension)
    elif failure == "sanitized":
        scan["sanitized"] = True
    elif failure == "unbound":
        scan.pop("source_ref")
    calls = []
    helpers = SimpleNamespace(
        get_settings=lambda: {}, get_embedding_safe_chunk_characters=lambda settings: 1000,
        get_embedding_usable_tokens=lambda settings: 4000,
        _get_search_client=lambda **kwargs: object(),
        delete_document_chunks=lambda *args, **kwargs: calls.append("clear"),
        generate_embedding=lambda *args: pytest.fail("Empty template cannot be indexed."),
        _build_archived_scope_value=lambda scope: scope,
    )
    monkeypatch.setattr(publication, "_document_helpers", lambda: helpers)
    monkeypatch.setattr(publication, "_project_blob", lambda *args: {"file_name": document["file_name"]})
    monkeypatch.setattr(publication, "_remove_previous_raw_projection", lambda *args: calls.append("release"))
    storage = SimpleNamespace(read_bytes=lambda *args: content)
    with publication_context(publication.subject_from_document(document), "scan-1"):
        if failure:
            with pytest.raises(publication.ScreeningValidationError):
                publication.publish_document(document, units, scan, "user-1", storage=storage)
            assert not calls
            return
        result = publication.publish_document(document, units, scan, "user-1", storage=storage)
    assert result["num_chunks"] == 0 and calls == ["clear", "release"]


@pytest.mark.parametrize("extension", [".dotx", ".potx"])
def test_template_package_type_is_validated_not_just_suffix(extension):
    with pytest.raises(DocumentTransformError):
        native_template_pages(source_bytes(".docx"), extension)
    files = fixture_files(extension)
    files["custom/vbaProject.bin"] = b"unsafe"
    with pytest.raises(DocumentTransformError):
        native_template_pages(archive_bytes(files), extension)


def test_template_screening_includes_custom_xml_but_does_not_invent_visible_narrative():
    content = blank_template(".dotx")
    pages, supplemental, structure = native_template_pages(content, ".dotx")
    assert not any(page["content"] for page in pages)
    assert any("original" in text for text in supplemental)
    assert structure["narrative_indexed"] is False


def test_potx_visible_text_follows_declared_slide_order_not_sorted_part_names():
    files = fixture_files(".potx")
    files["ppt/presentation.xml"] = (
        f'<p:presentation xmlns:p="{PPT_NS}" xmlns:r="{OFFICE_REL_NS}"><p:sldIdLst>'
        '<p:sldId id="256" r:id="rSecond"/><p:sldId id="257" r:id="rTenth"/>'
        '</p:sldIdLst></p:presentation>'
    ).encode()
    files["ppt/_rels/presentation.xml.rels"] = (
        f'<Relationships xmlns="{REL_NS}"><Relationship Id="rSecond" Type="{OFFICE_REL_NS}/slide" Target="slides/slide2.xml"/>'
        f'<Relationship Id="rTenth" Type="{OFFICE_REL_NS}/slide" Target="slides/slide10.xml"/></Relationships>'
    ).encode()
    for name, text in (("slide2.xml", "second"), ("slide10.xml", "tenth")):
        files[f"ppt/slides/{name}"] = (
            f'<p:sld xmlns:p="{PPT_NS}" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            f'<p:cSld><a:t>{text}</a:t></p:cSld></p:sld>'
        ).encode()
    pages, _supplemental, structure = native_template_pages(archive_bytes(files), ".potx")
    assert [page["content"] for page in pages] == ["second", "tenth"]
    assert structure["narrative_indexed"] is True


def test_template_allowance_is_shared_and_blank_upload_remains_selectable():
    namespace = run_definitions("config.py", {"DOCUMENT_EXTENSIONS"}, {})
    assert {"dotx", "potx"}.issubset(namespace["DOCUMENT_EXTENSIONS"])
    namespace = run_definitions("functions_mixed_source_orchestration.py", {"NARRATIVE_SOURCE_EXTENSIONS"}, {})
    assert TEMPLATE_EXTENSIONS <= namespace["NARRATIVE_SOURCE_EXTENSIONS"]
    document = {
        "id": "document-1", "file_name": "blank.dotx", "office_template_structure": {"extension": ".dotx"},
        "percentage_complete": 100, "number_of_pages": 0, "status": "Processing complete",
    }
    response, status = build_workspace_upload_file_content("blank.dotx", document, [])
    assert status == 200 and response["indexed_text_available"] is False
    assert "structural inspection" in response["file_content"]


@pytest.mark.parametrize("extension", [".dotx", ".potx"])
@pytest.mark.parametrize("screened", [False, True])
def test_blank_template_full_lifecycle_retains_native_bytes_and_correct_mime(pipeline, tmp_path, monkeypatch, extension, screened):
    if not screened:
        save_empty_baseline(pipeline)
    content = blank_template(extension)
    document = {
        "id": "document-1", "user_id": "owner", "version": 1, "file_name": f"blank{extension}",
        "is_current_version": True, "upload_date": "2026-10-10T00:00:00Z", "num_chunks": 0, "number_of_pages": 0,
    }
    marker = service.initial_document_marker(document)
    if marker is not None:
        document["content_screening"] = marker
    pipeline.repository.document_container("personal").create_item(document)
    source = tmp_path / document["file_name"]
    source.write_bytes(content)
    content_types = []
    blob_type = type(pipeline.blobs.get_blob_client(container="approved-documents", blob="probe"))
    upload_blob = blob_type.upload_blob

    def capture_upload(blob, payload, **options):
        if options.get("content_settings"):
            content_types.append(options["content_settings"].content_type)
        return upload_blob(blob, payload, **options)

    def read_unscreened_blob(container, path, record):
        blob = pipeline.blobs.get_blob_client(container=container, blob=path)
        properties = blob.get_blob_properties()
        return blob.download_blob(etag=properties.etag, match_condition=MatchConditions.IfNotModified).readall()

    monkeypatch.setattr(blob_type, "upload_blob", capture_upload)
    pipeline.helpers.process_document_upload_background(
        document_id=document["id"], user_id="owner", temp_file_path=str(source), original_filename=document["file_name"],
    )
    assert not pipeline.search.documents
    with access.strict_source_authority():
        current, actual = access.read_available_document_bytes(
            document["id"], user_id="owner", purpose="native",
            blob_reader=None if screened else read_unscreened_blob,
        )
    assert actual == content
    if screened:
        assert current["content_screening"]["state"] == "cleared"
    else:
        assert "content_screening" not in current
    assert current["num_chunks"] == 0 and current["percentage_complete"] == 100
    assert OFFICE_REFERENCE_MIME_TYPES[extension] in content_types


def test_populated_template_ingestion_indexes_visible_text_and_reports_usage():
    content = source_bytes(".dotx")
    saved_chunks = []
    updates = []

    def save_chunk(**kwargs):
        saved_chunks.append(kwargs)
        return {"total_tokens": 17, "model_deployment_name": "fixture-embedding"}

    namespace = {
        "open": lambda *args, **kwargs: io.BytesIO(content),
        "native_template_pages": native_template_pages, "current_extraction": lambda did: None,
        "get_settings": lambda: {}, "get_chunk_size_config": lambda settings: {}, "WORD_CHUNK_SIZE": 1000,
        "chunk_word_file_into_pages": lambda **kwargs: kwargs["di_pages"],
        "_build_office_embedded_image_chunks": lambda *args: ([], 0, "native", 0),
        "upload_to_blob": lambda *args, **kwargs: None, "save_chunks": save_chunk,
    }
    run_definitions("functions_documents.py", {"process_office_template"}, namespace)
    result = namespace["process_office_template"](
        "document-1", "user-1", "in-memory", "reference.dotx", ".dotx", False,
        lambda **kwargs: updates.append(kwargs),
    )
    assert len(saved_chunks) == 1 and saved_chunks[0]["page_text_content"]
    assert result == (1, 17, "fixture-embedding")
    assert updates[-1]["office_template_structure"]["narrative_indexed"] is True


def test_native_source_callbacks_bind_explicitly_without_reading_inputs():
    def unavailable(*args, **kwargs):
        raise AssertionError("Binding must not read reference sources.")

    fixture = ResultFixture()
    bound = services(
        fixture, document_transform_source_reader=unavailable,
        document_transform_source_resolver=unavailable, document_transform_candidate_reader=unavailable,
    )
    request = build_capability_request_context(
        "owner", {}, "Inspect the reference", {}, **bound.capability_request_bindings(),
    )
    record, context = runtime(fixture)
    configured = bound.bind_context(
        context, record, checkpoint_factory=checkpoint_factory(fixture),
        guard_token="owning-lease-token", execution_check=lambda: True,
    )
    assert configured is context
    assert request["document_transform_source_reader"] is unavailable
    assert request["document_transform_source_resolver"] is unavailable
    assert context.document_transform_source_reader is unavailable
    assert context.document_transform_source_resolver is unavailable
    assert bound.rendering.document_transform_source_reader is unavailable


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
