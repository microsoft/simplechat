# test_content_screening_pipeline.py
"""
Functional integration tests for workspace admission and reviewed publication.
Version: 0.261.113
Implemented in: 0.261.106

Runs the real durable job, scanner, repository, private storage, TXT extraction,
and publication services against fake Azure boundaries. No live data is used.
"""

import ast
import copy
import hashlib
import logging
import math
import os
import sys
import types
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

# Import the reusable modules, not config.py or the application bootstrap.
from content_screening import access, engine, jobs, publication, service
from content_screening.contracts import (
    SCREENING_FIELD,
    ContentUnit,
    DocumentHeldError,
    ScreeningConflictError,
    ScreeningError,
    Subject,
    document_is_available,
    hash_payload,
    metadata_fingerprint,
)
from content_screening.extraction import current_extraction
from content_screening.policies import default_policy
from content_screening.repository import ScreeningRepository
from content_screening.storage import ScreeningStorage
import functions_embedding_compatibility as embedding_compatibility
from functions_embeddings import EmbeddingVector
from test_content_screening_persistence import FakeBlob, FakeBlobContainer, FakeBlobService, FakeCosmos, FakeSdkError


class Properties(dict):
    def __getattr__(self, name):
        return self[name]


class AzureLikeBlob(FakeBlob):
    def _record(self):
        try:
            return super()._record()
        except FakeSdkError as error:
            raise ResourceNotFoundError("Missing test blob") from error

    def upload_blob(self, *args, **kwargs):
        try:
            return super().upload_blob(*args, **kwargs)
        except FakeSdkError as error:
            if error.status_code == 409:
                raise ResourceExistsError("Existing test blob") from error
            raise

    def get_blob_properties(self):
        return Properties(super().get_blob_properties())

    def download_blob(self, **kwargs):
        try:
            return super().download_blob(**kwargs)
        except FakeSdkError as error:
            if error.status_code == 412:
                raise ResourceModifiedError("Changed test blob") from error
            raise


class AzureLikeContainer(FakeBlobContainer):
    def get_blob_client(self, name):
        return AzureLikeBlob(self, name)


class AzureLikeStorage(FakeBlobService):
    def get_container_client(self, name):
        return self.containers.setdefault(name, AzureLikeContainer())


class SearchProjection:
    def __init__(self):
        self.documents = {}
        self.fail_next_upload = False
        self.writes = 0

    def search(self, **kwargs):
        document_id = kwargs["filter"].split("'")[1]
        return [copy.deepcopy(item) for item in self.documents.values() if item["document_id"] == document_id]

    def upload_documents(self, documents, **kwargs):
        self.writes += 1
        self.documents.update({item["id"]: copy.deepcopy(item) for item in documents})
        failed, self.fail_next_upload = self.fail_next_upload, False
        return [types.SimpleNamespace(succeeded=not failed) for _ in documents]


@pytest.fixture
def pipeline(monkeypatch):
    metadata = FakeCosmos()
    containers = {scope: FakeCosmos(partition_field="id") for scope in ("personal", "group", "public")}
    repository = ScreeningRepository(metadata, containers)
    blob_service = AzureLikeStorage()
    storage = ScreeningStorage(blob_service)
    search = SearchProjection()
    settings = {
        "enable_content_screening": True, "enable_enhanced_citations": True,
        "enable_extract_meta_data": False, "enable_notifications": False,
        "max_file_size_mb": 16,
    }
    embedding_profile = types.SimpleNamespace(profile_id="fixture-embedding-profile", dimensions=2, legacy=False)
    write_profiles = []
    monkeypatch.setattr(embedding_compatibility, "read_embedding_settings", lambda: settings)
    monkeypatch.setattr(embedding_compatibility, "active_embedding_profile", lambda value=None: embedding_profile)
    monkeypatch.setattr(embedding_compatibility, "_runtime_index_metadata", lambda *args: {"provenance": True})
    policy = default_policy()
    policy.update({"enabled": True, "rules": [{
        "id": "restricted", "name": "Restricted", "type": "literal",
        "enabled": True, "severity": "high", "category": "sensitive",
        "values": ["PRIVATE_CANARY"],
    }]})
    repository.save_policy("global", "global", policy, "administrator")
    monkeypatch.setattr(service, "_repository", lambda value=None: value if value is not None else repository)
    monkeypatch.setattr(service, "_storage", lambda value=None: value if value is not None else storage)
    monkeypatch.setattr(service, "_settings", lambda value=None: value if value is not None else settings)
    monkeypatch.setattr(service, "_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(jobs, "_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(jobs, "_assert_migration_open", lambda: None)
    review_requests = []
    reviews = types.ModuleType("content_screening.reviews")
    reviews.ensure_review = lambda scan, actor_id, **kwargs: review_requests.append(scan["id"])
    monkeypatch.setitem(sys.modules, "content_screening.reviews", reviews)
    monkeypatch.setitem(sys.modules, "functions_activity_logging", types.SimpleNamespace(
        log_document_creation_transaction=lambda **kwargs: {"id": kwargs["idempotency_key"]},
        log_token_usage=lambda **kwargs: {"id": kwargs["idempotency_key"]},
    ))

    def get_metadata(document_id, user_id, group_id=None, public_workspace_id=None):
        scope = "public" if public_workspace_id else "group" if group_id else "personal"
        document = containers[scope].read_item(document_id, document_id)
        if scope == "personal":
            assert user_id == document["user_id"], "Private extraction must use the document's owner scope."
        return document

    def update_document(**updates):
        document_id = updates.pop("document_id")
        user_id = updates.pop("user_id")
        group_id = updates.pop("group_id", None)
        public_workspace_id = updates.pop("public_workspace_id", None)
        document = get_metadata(document_id, user_id, group_id, public_workspace_id)
        subject = service.subject_from_document(document)
        repository.update_document(subject, updates, etag=document["_etag"])
        capture = current_extraction(document_id)
        if capture is not None:
            capture.heartbeat()

    def generate_embedding(text):
        for item in containers["personal"].documents.values():
            marker = item.get(SCREENING_FIELD) or {}
            if marker.get("state") == "publishing":
                scan = repository.get_scan(marker["scan_id"])
                assert scan["coverage_complete"] is True
                break
        else:
            raise AssertionError("Embedding ran before complete screening and publication.")
        return EmbeddingVector([0.25, 0.75], embedding_profile), {
            "total_tokens": len(text), "model_deployment_name": "test-embedding",
        }

    def search_write_slot(container, *, embedding_profile_id):
        write_profiles.append(embedding_profile_id)
        return nullcontext()

    def delete_chunks(document_id, **kwargs):
        search.documents = {key: value for key, value in search.documents.items() if value["document_id"] != document_id}

    helpers = types.ModuleType("functions_documents")
    helpers.get_document_metadata = get_metadata
    helpers._get_search_client = lambda **kwargs: search
    helpers._get_blob_service_client = lambda: blob_service
    helpers._get_blob_container_name = lambda **kwargs: "approved-documents"
    helpers._ensure_blob_container_ready = lambda client, name: client.get_container_client(name)
    helpers._build_archived_scope_value = lambda value: f"archived:{value}"
    helpers.get_settings = lambda: settings
    helpers.get_embedding_safe_chunk_characters = lambda value=None: 100
    helpers.get_embedding_usable_tokens = lambda value=None: 128
    helpers.generate_embedding = generate_embedding
    helpers.delete_document_chunks = delete_chunks
    helpers.set_document_chunk_visibility = lambda *args, **kwargs: None
    helpers.get_document_blob_storage_info = lambda document, **kwargs: (
        document.get("blob_container"), document.get("blob_path"),
    )
    helpers._get_screening_source_bytes = publication.source_bytes
    helpers._get_screening_existing_chunks = publication.existing_chunks
    helpers._publish_screened_document = publication.publish_document

    namespace = {
        "os": os, "math": math, "logging": logging,
        "datetime": datetime, "timezone": timezone, "current_extraction": current_extraction,
        "ScreeningError": ScreeningError, "get_settings": lambda: settings,
        "get_chunk_size_config": lambda value=None: {"txt": {"value": 3}},
        "get_document_metadata": get_metadata, "update_document": update_document,
        "allowed_file": lambda *args: True,
        "log_event": lambda *args, **kwargs: None,
        "TABULAR_EXTENSIONS": {"csv"}, "IMAGE_EXTENSIONS": {"png"},
        "DOCUMENT_EXTENSIONS": {"pdf", "docx"}, "VIDEO_EXTENSIONS": {"mp4"},
        "AUDIO_EXTENSIONS": {"mp3"}, "VISIO_EXTENSIONS": {"vsdx"},
        "EMAIL_EXTENSIONS": {"msg"},
        "hold_data_management_search_write_slot": search_write_slot,
        "prepare_embedding_search_documents": embedding_compatibility.prepare_embedding_search_documents,
        "cosmos_data_management_jobs_container": None,
    }
    functions = {
        "save_chunks", "upload_to_blob", "process_txt", "_process_document_upload_background_impl",
        "_search_indexing_results_succeeded", "_execute_document_search_write",
    }
    tree = ast.parse((APP_ROOT / "functions_documents.py").read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in functions]
    assert len(nodes) == len(functions)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP_ROOT / "functions_documents.py"), "exec"), namespace)
    helpers._process_document_upload_background_impl = namespace["_process_document_upload_background_impl"]
    helpers._execute_document_search_write = namespace["_execute_document_search_write"]
    monkeypatch.setitem(sys.modules, "functions_documents", helpers)
    config = types.ModuleType("config")
    config.cosmos_content_screening_container = metadata
    config.cosmos_user_documents_container = containers["personal"]
    config.cosmos_group_documents_container = containers["group"]
    config.cosmos_public_documents_container = containers["public"]
    config.CLIENTS = {"storage_account_office_docs_client": blob_service}
    config.build_enhanced_citations_blob_service_client = lambda values: blob_service
    monkeypatch.setitem(sys.modules, "config", config)
    return types.SimpleNamespace(
        repository=repository, storage=storage, blobs=blob_service, search=search,
        settings=settings, helpers=helpers, reviews=review_requests,
        embedding_profile=embedding_profile, write_profiles=write_profiles,
    )


def seed(pipeline, *, source_name="document.txt"):
    document = {
        "id": "document", "user_id": "owner", "version": 1, "file_name": source_name,
        "is_current_version": True, "upload_date": "2026-09-16T00:00:00Z",
        "num_chunks": 0, "number_of_pages": 0,
    }
    document[SCREENING_FIELD] = service.initial_document_marker(document)
    return pipeline.repository.document_container("personal").create_item(document)


def upload(pipeline, tmp_path, text):
    source = tmp_path / "document.txt"
    source.write_bytes(text.encode("utf-8"))
    return service.process_screened_upload(
        "document", "owner", str(source), "document.txt",
        pipeline.helpers._process_document_upload_background_impl,
    )


def approve(pipeline, scan_id, *, flagged=False):
    scan = pipeline.repository.get_scan(scan_id)
    scan["review_decision"] = {
        "action": "approve_with_flags" if flagged else "approve_clean",
        "actor_id": "owner", "reason": "Reviewed the exact candidate",
        "scan_id": scan_id, "source_revision": "1",
        "content_fingerprint": scan["content_fingerprint"],
        "policy_fingerprint": scan["policy_fingerprint"],
        "policy_snapshot_hash": hash_payload(scan["policy"]),
        "decided_at": datetime.now(timezone.utc).isoformat(), "acknowledged_flags": flagged,
    }
    pipeline.repository.replace(scan, scan["_etag"])
    return service.publish_scan(scan_id, "owner", repository=pipeline.repository, storage=pipeline.storage)


def drain_candidate(pipeline, candidate):
    work = pipeline.repository.query("work_item", filters={"scan_id": candidate["id"]})["items"]
    assert len(work) == 1
    jobs.run_scan_job(work[0]["job_id"], repository=pipeline.repository)
    return pipeline.repository.get_scan(candidate["id"])


def test_real_txt_intake_scans_before_embedding_and_releases_exact_source(pipeline, tmp_path):
    seed(pipeline)
    text = "First line of evidence\nSecond line with a complete tail"
    result = upload(pipeline, tmp_path, text)
    assert result["state"] == "cleared"
    document = pipeline.repository.read_document(Subject("personal", "owner", "document", "1"))
    assert document_is_available(document)
    assert "".join(item["chunk_text"] for item in pipeline.search.documents.values()) == text
    assert pipeline.write_profiles
    assert set(pipeline.write_profiles) == {pipeline.embedding_profile.profile_id}
    assert all(
        item["embedding_profile_id"] == pipeline.embedding_profile.profile_id
        for item in pipeline.search.documents.values()
    )
    assert result["publication"]["metadata_fingerprint"] == metadata_fingerprint(document)
    read, content = access.read_available_document_bytes("document", "owner")
    assert read["content_screening"]["scan_id"] == result["id"]
    assert content.decode("utf-8") == text


def test_screened_publication_rejects_an_embedding_profile_change(pipeline, tmp_path, monkeypatch):
    seed(pipeline)
    generate = pipeline.helpers.generate_embedding

    def changed_profile(text):
        result = generate(text)
        pipeline.embedding_profile.profile_id = "replacement-embedding-profile"
        return result

    monkeypatch.setattr(pipeline.helpers, "generate_embedding", changed_profile)
    result = upload(pipeline, tmp_path, "Reviewed source content")
    assert result["state"] == "publishing"
    assert pipeline.search.documents == {}
    document = pipeline.repository.read_document(Subject("personal", "owner", "document", "1"))
    assert not document_is_available(document)


def test_last_line_finding_prevents_all_search_and_original_access(pipeline, tmp_path):
    seed(pipeline)
    result = upload(pipeline, tmp_path, "Ordinary opening pages\nPRIVATE_CANARY")
    assert result["state"] == "pending_review"
    assert not pipeline.search.documents
    assert result["id"] in pipeline.reviews
    with pytest.raises(DocumentHeldError):
        access.read_available_document_bytes("document", "owner")
    assert b"PRIVATE_CANARY" in pipeline.storage.read_bytes(result["source_ref"], Subject.from_dict(result["subject"]))
    accepted = approve(pipeline, result["id"], flagged=True)
    assert accepted["state"] == "approved_with_flags"
    assert access.read_available_document_bytes("document", "owner")[1].endswith(b"PRIVATE_CANARY")


def test_clean_candidate_is_queued_rescanned_and_never_uses_original_bytes(pipeline, tmp_path):
    seed(pipeline)
    result = upload(pipeline, tmp_path, "Retained text\nPRIVATE_CANARY")
    subject = Subject.from_dict(result["subject"])
    units = [
        ContentUnit.from_dict(unit) for unit in pipeline.storage.read_json(result["units_ref"], subject)
    ]
    cleaned = [
        ContentUnit(unit.unit_id, unit.text.replace("PRIVATE_CANARY", ""), unit.locator)
        for unit in units
    ]
    candidate = service.create_candidate_scan(
        result["id"], cleaned, "owner", repository=pipeline.repository, storage=pipeline.storage,
    )
    assert candidate["state"] == "pending_scan"
    assert not pipeline.search.documents
    candidate = drain_candidate(pipeline, candidate)
    assert candidate["state"] == "pending_review"
    assert candidate["finding_count"] == 0
    approve(pipeline, candidate["id"])
    document, content = access.read_available_document_bytes("document", "owner")
    assert document["file_name"].endswith(".txt")
    assert b"PRIVATE_CANARY" not in content
    assert b"PRIVATE_CANARY" in pipeline.storage.read_bytes(candidate["source_ref"], subject)
    assert all("PRIVATE_CANARY" not in item["chunk_text"] for item in pipeline.search.documents.values())


def test_restored_clear_marker_without_release_proof_is_not_available(pipeline, tmp_path):
    seed(pipeline)
    result = upload(pipeline, tmp_path, "Ordinary evidence")
    pipeline.repository.container.documents.pop((result["id"], result["id"]))
    with pytest.raises(DocumentHeldError):
        access.assert_document_available("document", "owner")


def test_unscreened_metadata_cannot_borrow_previous_clearance(pipeline, tmp_path):
    seed(pipeline)
    upload(pipeline, tmp_path, "Ordinary evidence")
    document = pipeline.repository.document_container("personal").read_item("document", "document")
    document["abstract"] = "PRIVATE_CANARY"
    pipeline.repository.document_container("personal").replace_item(
        item="document", body=document, etag=document["_etag"],
        match_condition=MatchConditions.IfNotModified,
    )
    with pytest.raises(DocumentHeldError):
        access.assert_document_available("document", "owner")


def test_initial_metadata_changes_do_not_enqueue_a_sourceless_rescan(pipeline):
    document = seed(pipeline)
    assert service.queue_metadata_rescan(document, {"tags": ["intake"]}, "owner", repository=pipeline.repository) is None
    assert not pipeline.repository.query("job")["items"]
    current = pipeline.repository.read_document(Subject("personal", "owner", "document", "1"))
    assert current["tags"] == ["intake"]
    assert current[SCREENING_FIELD]["scan_id"] == document[SCREENING_FIELD]["scan_id"]


def test_stale_worker_failure_does_not_clear_another_workers_lease(pipeline):
    seed(pipeline)
    subject = Subject("personal", "owner", "document", "1")
    scan = service.begin_scan(subject, "owner", repository=pipeline.repository)
    scan, owner = service._claim_scan(pipeline.repository, scan)
    replacement = pipeline.repository.replace({
        **scan, "lease": {"owner": "new-worker", "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()},
    }, scan["_etag"])
    service._record_failure(pipeline.repository, scan["id"], "old_failure", owner=owner)
    assert pipeline.repository.get_scan(scan["id"]) == replacement


def test_old_failure_does_not_reopen_a_deleted_subject(pipeline):
    seed(pipeline)
    scan = service.begin_scan(Subject("personal", "owner", "document", "1"), "owner", repository=pipeline.repository)
    deleting = pipeline.repository.replace({**scan, "state": "deleting", "lease": None}, scan["_etag"])
    service._record_failure(pipeline.repository, scan["id"], "old_failure")
    assert pipeline.repository.get_scan(scan["id"]) == deleting


def test_partial_search_publication_is_held_and_retries_the_same_blob(pipeline, tmp_path):
    seed(pipeline)
    pipeline.search.fail_next_upload = True
    failed = upload(pipeline, tmp_path, "Ordinary text that spans more than one bounded publication chunk")
    assert failed["state"] == "publishing"
    with pytest.raises(DocumentHeldError):
        access.assert_document_available("document", "owner")
    published = service.publish_scan(
        failed["id"], "owner", repository=pipeline.repository, storage=pipeline.storage,
    )
    assert published["state"] == "cleared"
    assert access.read_available_document_bytes("document", "owner")[1].startswith(b"Ordinary text")


def test_admin_inspection_uses_personal_owner_storage_without_granting_review(pipeline, tmp_path):
    seed(pipeline)
    subject = Subject("personal", "owner", "document", "1")
    scan = service.begin_scan(subject, "administrator", repository=pipeline.repository)
    path = tmp_path / "document.txt"
    path.write_bytes(b"Private workspace ordinary document")
    source_ref = pipeline.storage.write_source(subject, scan["id"], str(path), "document.txt")
    scan = pipeline.repository.replace({**scan, "source_ref": source_ref}, scan["_etag"])
    result = service._extract_and_inspect(
        scan, "administrator", str(path), pipeline.helpers._process_document_upload_background_impl,
        repository=pipeline.repository, storage=pipeline.storage,
    )
    assert result["state"] == "cleared"
    from content_screening.permissions import ScreeningPermissionError, assert_subject_access

    with pytest.raises(ScreeningPermissionError):
        assert_subject_access(subject, "administrator", repository=pipeline.repository, review=True)


def test_second_remediation_does_not_compare_clean_derivative_to_raw_original(pipeline, tmp_path):
    seed(pipeline)
    initial = upload(pipeline, tmp_path, "First PRIVATE_CANARY\nSecond PRIVATE_CANARY\nRetain this")
    subject = Subject.from_dict(initial["subject"])
    units = [ContentUnit.from_dict(value) for value in pipeline.storage.read_json(initial["units_ref"], subject)]
    first_units = [
        ContentUnit(unit.unit_id, unit.text.replace("PRIVATE_CANARY", "", 1), unit.locator)
        for unit in units
    ]
    first = drain_candidate(pipeline, service.create_candidate_scan(
        initial["id"], first_units, "owner", repository=pipeline.repository, storage=pipeline.storage,
    ))
    approve(pipeline, first["id"], flagged=True)
    old_document = pipeline.repository.read_document(subject)
    old_blob = old_document["blob_path"]
    rescan = service.begin_scan(subject, "owner", repository=pipeline.repository)
    rescan = service.scan_existing_document(subject, "owner", repository=pipeline.repository, storage=pipeline.storage)
    assert rescan["state"] == "pending_review"
    units = [ContentUnit.from_dict(value) for value in pipeline.storage.read_json(rescan["units_ref"], subject)]
    second_units = [
        ContentUnit(unit.unit_id, unit.text.replace("PRIVATE_CANARY", ""), unit.locator)
        for unit in units
    ]
    second = drain_candidate(pipeline, service.create_candidate_scan(
        rescan["id"], second_units, "owner", repository=pipeline.repository, storage=pipeline.storage,
    ))
    approve(pipeline, second["id"])
    assert b"PRIVATE_CANARY" not in access.read_available_document_bytes("document", "owner")[1]
    assert old_blob not in pipeline.blobs.get_container_client("approved-documents").blobs


def test_scanning_error_retains_known_evidence_for_a_clean_looking_retry(pipeline, tmp_path, monkeypatch):
    seed(pipeline)
    found = upload(pipeline, tmp_path, "Retain PRIVATE_CANARY")
    subject = Subject.from_dict(found["subject"])
    units = [ContentUnit.from_dict(value) for value in pipeline.storage.read_json(found["units_ref"], subject)]

    def stopped_engine(*args, **kwargs):
        raise ScreeningError(code="screening_storage_failed")

    with pytest.raises(ScreeningError):
        service.inspect_scan(
            found["id"], units, "owner", repository=pipeline.repository, storage=pipeline.storage,
            engine=stopped_engine,
        )
    failed = pipeline.repository.get_scan(found["id"])
    assert failed["result_ref"] == found["result_ref"]
    assert failed["review_required"] is True
    assert not document_is_available(pipeline.repository.read_document(subject))


def test_deleted_document_recovery_requires_a_real_started_deletion(pipeline, monkeypatch):
    document = seed(pipeline)
    subject = Subject("personal", "owner", "document", "1")
    scan = service.begin_scan(subject, "owner", repository=pipeline.repository)
    pipeline.repository.document_container("personal").documents.pop(("document", "document"))
    with pytest.raises(ScreeningConflictError):
        service.delete_screened_document(scan["id"], "owner", repository=pipeline.repository, storage=pipeline.storage)
    scan = pipeline.repository.replace({
        **scan, "state": "deleting", "deleted_by": "owner",
        "deletion_started_at": datetime.now(timezone.utc).isoformat(),
    }, scan["_etag"])
    result = service.delete_screened_document(scan["id"], "owner", repository=pipeline.repository, storage=pipeline.storage)
    assert result["state"] == "deleted"


def interrupt_after_document_release(pipeline, tmp_path, monkeypatch):
    seed(pipeline)
    save = service._save_scan

    def crash(repository, scan, **updates):
        if updates.get("state") == "cleared" and updates.get("published_at"):
            raise SystemExit("Simulated worker shutdown after document commit")
        return save(repository, scan, **updates)

    with monkeypatch.context() as context:
        context.setattr(service, "_save_scan", crash)
        with pytest.raises(SystemExit):
            upload(pipeline, tmp_path, "Complete inspected text")
    document = pipeline.repository.read_document(Subject("personal", "owner", "document", "1"))
    scan = pipeline.repository.get_scan(document[SCREENING_FIELD]["scan_id"])
    assert document[SCREENING_FIELD]["state"] == "cleared"
    assert scan["state"] == "publishing"
    expired = {**scan, "lease": {
        **scan["lease"], "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }}
    return pipeline.repository.replace(expired, scan["_etag"])


def test_recovery_finalizes_only_the_already_committed_publication(pipeline, tmp_path, monkeypatch):
    scan = interrupt_after_document_release(pipeline, tmp_path, monkeypatch)
    with pytest.raises(DocumentHeldError):
        access.assert_document_available("document", "owner")
    writes = pipeline.search.writes
    finished = service.finalize_publication_checkpoint(scan["id"], repository=pipeline.repository)
    assert finished["state"] == "cleared"
    assert finished["postprocess_pending"] is True
    assert pipeline.search.writes == writes
    assert access.read_available_document_bytes("document", "owner")[1] == b"Complete inspected text"


def test_recovery_does_not_invent_proof_for_changed_metadata(pipeline, tmp_path, monkeypatch):
    scan = interrupt_after_document_release(pipeline, tmp_path, monkeypatch)
    subject = Subject("personal", "owner", "document", "1")
    document = pipeline.repository.read_document(subject)
    pipeline.repository.update_document(subject, {"abstract": "UNAPPROVED"}, etag=document["_etag"])
    with pytest.raises(ScreeningConflictError):
        service.finalize_publication_checkpoint(scan["id"], repository=pipeline.repository)
    with pytest.raises(DocumentHeldError):
        access.assert_document_available("document", "owner")


def test_service_model_resume_reuses_durable_validated_windows(pipeline, tmp_path):
    from test_content_screening_model import ModelScreeningTests, clean_payload

    model_case = ModelScreeningTests()
    model_case.setUp()
    try:
        pipeline.settings.update(model_case.settings)
        policy_record = pipeline.repository.get_policy("global", "global")
        policy = copy.deepcopy(policy_record["policy"])
        policy["ai"].update({
            "enabled": True,
            "model_selection": {"endpoint_id": "scanner-endpoint", "model_id": "scanner-model"},
            "window_unit": "chunks", "window_size": 1, "max_characters": 256, "overlap_characters": 0,
        })
        pipeline.repository.save_policy(
            "global", "global", policy, "administrator", etag=policy_record["_etag"],
        )
        seed(pipeline)

        def fail_second_window(envelope, request_number):
            return TimeoutError("Synthetic timeout") if request_number == 2 else clean_payload(envelope)

        model_case.route_client.responder = fail_second_window
        first = upload(pipeline, tmp_path, "Complete source text " * 40)
        assert first["state"] in {"incomplete", "scan_error"}
        windows = pipeline.repository.query("model_window", filters={"scan_id": first["id"]})["items"]
        assert len(windows) == 1
        first_window = model_case.route_client.envelopes[0]["window_id"]
        work = pipeline.repository.query("work_item", filters={"scan_id": first["id"]})["items"]
        assert len(work) == 1
        jobs.request_scan_job_action(work[0]["job_id"], "owner", "retry", repository=pipeline.repository)
        model_case.route_client.responder = lambda envelope, _number: clean_payload(envelope)
        jobs.run_scan_job(work[0]["job_id"], repository=pipeline.repository)
        finished = pipeline.repository.get_scan(first["id"])
        assert finished["state"] == "cleared"
        assert sum(item["window_id"] == first_window for item in model_case.route_client.envelopes) == 1
        assert finished["usage"]["checkpoint_windows"] == 1
        assert document_is_available(access.assert_document_available("document", "owner"))
    finally:
        model_case.doCleanups()


def test_activation_validates_model_binding_without_inference_or_secret_hydration(pipeline):
    from test_content_screening_model import ModelScreeningTests
    from content_screening.model import validate_scanner_model_configuration
    from content_screening.contracts import ScreeningConfigurationError

    model_case = ModelScreeningTests()
    model_case.setUp()
    try:
        selection = {"endpoint_id": "scanner-endpoint", "model_id": "scanner-model"}
        validate_scanner_model_configuration(model_case.settings, selection)
        assert not model_case.azure_factory.called
        assert not model_case.hydrate.called
        with pytest.raises(ScreeningConfigurationError):
            validate_scanner_model_configuration(model_case.settings, {**selection, "model_id": "missing"})
        with pytest.raises(ScreeningConfigurationError):
            validate_scanner_model_configuration({**model_case.settings, "enable_multi_model_endpoints": False}, selection)
    finally:
        model_case.doCleanups()


def test_internal_configuration_validation_does_not_trust_a_cached_model_registry(pipeline):
    from test_content_screening_model import ModelScreeningTests
    from content_screening.contracts import ScreeningConfigurationError

    model_case = ModelScreeningTests()
    model_case.setUp()
    try:
        pipeline.settings.update(copy.deepcopy(model_case.settings))
        stored = pipeline.repository.get_policy("global", "global")
        policy = copy.deepcopy(stored["policy"])
        policy["ai"].update({
            "enabled": True,
            "model_selection": {"endpoint_id": "scanner-endpoint", "model_id": "scanner-model"},
        })
        pipeline.repository.save_policy("global", "global", policy, "administrator", etag=stored["_etag"])
        model_case.settings["model_endpoints"][0]["models"][0]["enabled"] = False
        with pytest.raises(ScreeningConfigurationError):
            service.validate_screening_configuration(pipeline.settings, repository=pipeline.repository)
        service.validate_screening_configuration(
            pipeline.settings, repository=pipeline.repository, proposed_settings=True,
        )
        assert not model_case.azure_factory.called
        assert not model_case.hydrate.called
    finally:
        model_case.doCleanups()
