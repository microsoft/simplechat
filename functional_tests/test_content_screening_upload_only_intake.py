# test_content_screening_upload_only_intake.py
"""
Functional tests for upload-only content screening intake.
Version: 0.261.230
Implemented in: 0.261.230

This test ensures that, with content screening on and an active policy, documents
SimpleChat generates or publishes into a workspace never receive a screening marker,
while user uploads, chat uploads and File Sync still do. It also ensures that clients
cannot set the server-managed exemption, that editing metadata keeps a cleared document
available, that model-generated metadata applies without a new hold, and that the
publication screening reservation is gone. Refs #1621.

Runs the real create_document, update_document, metadata extraction, upload dispatch,
generated-upload, scan-job, publication and document-guard code against in-memory
stores. No Azure resources, models or application startup are used.
"""

import ast
from copy import deepcopy
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, Dict
import uuid

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from content_screening import access, contracts, jobs, service  # noqa: E402
from content_screening.contracts import (  # noqa: E402
    SCREENING_FIELD,
    DocumentHeldError,
    ScreeningConflictError,
    ScreeningValidationError,
    Subject,
    content_fingerprint,
    document_is_available,
    hash_payload,
    subject_from_document,
)
from content_screening.policies import default_policy  # noqa: E402
from content_screening.repository import ScreeningRepository  # noqa: E402
import functions_artifact_publication_readiness as readiness  # noqa: E402
import functions_document_provenance as provenance  # noqa: E402
from test_content_screening_jobs import add_document, create_job, runtime, service_runtime  # noqa: E402,F401
from test_content_screening_persistence import FakeCosmos  # noqa: E402
from test_document_provenance_versions_and_guards import (  # noqa: E402,F401
    MUTATING_ROUTES,
    load_functions,
    mutation_client,
)
from test_group_document_management import management  # noqa: E402,F401
from test_group_document_publication import (  # noqa: E402,F401
    REQUESTER,
    assert_receipt,
    decide,
    publication,
    publication_modules,
    receipt,
    sharing,
    submit,
)
from test_group_document_read_apis import environment  # noqa: E402,F401
from test_support.agent_delegation import execute_functions  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


GENERATED = {"reason": "generated", "version": 1}
SCOPES = {
    "personal": {},
    "group": {"group_id": "group-1"},
    "public": {"public_workspace_id": "public-1"},
}
ACTIVE_POLICY_RULE = {
    "id": "restricted", "name": "Restricted", "type": "literal", "enabled": True,
    "severity": "high", "category": "sensitive", "values": ["PRIVATE_CANARY"],
}


def generated_exemption():
    # Resolved at call time so the suite reports per-test failures without the feature.
    return contracts.generated_screening_exemption()


def test_version_supports_upload_only_intake():
    assert_app_version_at_least("0.261.230")


# --- Exemption contract -----------------------------------------------------------------


def test_the_exemption_is_an_exact_server_marker():
    first = generated_exemption()
    first["version"] = 2
    assert generated_exemption() == GENERATED
    assert contracts.SCREENING_EXEMPTION_FIELD == "screening_exemption"
    assert contracts.is_generated_screening_exempt({"screening_exemption": GENERATED})
    for near_match in (
        {"reason": "generated", "version": True}, {"reason": "generated", "version": "1"},
        {"reason": "Generated", "version": 1}, {"reason": "generated"},
        {"reason": "generated", "version": 1, "scope": "all"}, ["generated", 1], None,
    ):
        assert not contracts.is_generated_screening_exempt({"screening_exemption": near_match}), near_match
    assert not contracts.is_generated_screening_exempt(None)


@pytest.mark.parametrize("payload", [
    {"screening_exemption": GENERATED},
    {"screeningExemption": GENERATED},
    {"Screening-Exemption": "generated"},
    {"metadata": {"screening_exemption": GENERATED}},
    {"documents": [{"id": "doc-1", "SCREENING_EXEMPTION": GENERATED}]},
])
def test_clients_cannot_send_the_exemption_in_any_document_payload(payload):
    with pytest.raises(ScreeningValidationError):
        access.reject_screening_fields(payload)


@pytest.mark.parametrize("route", MUTATING_ROUTES, ids=lambda route: f"{route[2]} {route[1]}")
def test_every_guarded_document_mutation_route_rejects_a_client_exemption(mutation_client, route):
    path, method = mutation_client.paths[route], route[2]
    mutation_client.reached.clear()
    for body in ({"title": "Report", "screening_exemption": GENERATED}, {"meta": {"screeningExemption": GENERATED}}):
        response = mutation_client.client.open(path, method=method, json=body)
        assert response.status_code == 400, (route, body)
        assert response.get_json()["error_code"] == ScreeningValidationError.code
    response = mutation_client.client.open(path, method=method, data={"screening_exemption": "generated"})
    assert response.status_code == 400, route
    assert mutation_client.reached == []


def test_the_exemption_is_never_echoed_to_clients():
    stored = {"id": "doc-1", "file_name": "report.md", "user_id": "user-1", "screening_exemption": GENERATED}
    assert not access.is_public_document_field("screening_exemption")
    assert "screening_exemption" not in access.public_document_payload(stored)


class ReachedStorage(Exception):
    """Raised by the operation guard to prove a call got past the field guards."""


def test_no_update_path_can_set_or_change_the_exemption():
    namespace = load_functions("functions_documents.py", {"update_document"}, {
        "SCREENING_FIELD": SCREENING_FIELD, "ScreeningValidationError": ScreeningValidationError,
        "ORIGIN_FIELD_NAMES": provenance.ORIGIN_FIELD_NAMES, "DocumentOriginError": provenance.DocumentOriginError,
    })
    reached = []

    def guard():
        reached.append(True)
        raise ReachedStorage()

    for field in ("screening_exemption", "screening_state"):
        with pytest.raises(ScreeningValidationError):
            namespace["update_document"](document_id="doc-1", user_id="user-1", operation_guard=guard, **{field: GENERATED})
    assert reached == []
    with pytest.raises(ReachedStorage):
        namespace["update_document"](document_id="doc-1", user_id="user-1", operation_guard=guard, title="Report")


# --- Intake: the real create_document ---------------------------------------------------


class DocumentStore:
    """A scope-filtered stand-in for one Cosmos documents container."""

    def __init__(self):
        self.records = {}

    def query_items(self, query, parameters, enable_cross_partition_query=True):
        values = {item["name"]: item["value"] for item in parameters}
        fields = {
            "@file_name": "file_name", "@user_id": "user_id", "@group_id": "group_id",
            "@public_workspace_id": "public_workspace_id",
        }
        return [
            deepcopy(record) for record in self.records.values()
            if all(record.get(field) == values[name] for name, field in fields.items() if name in values)
        ]

    def upsert(self, document):
        self.records[document["id"]] = deepcopy(document)


@pytest.fixture
def screening_on(monkeypatch):
    repository = ScreeningRepository(FakeCosmos(), {scope: FakeCosmos(partition_field="id") for scope in SCOPES})
    policy = default_policy()
    policy.update(enabled=True, rules=[dict(ACTIVE_POLICY_RULE)])
    repository.save_policy("global", "global", policy, "administrator")
    settings = {
        "enable_content_screening": True, "enable_enhanced_citations": True,
        "enable_content_screening_workspace_uploads": True,
    }
    monkeypatch.setattr(service, "_repository", lambda value=None: value if value is not None else repository)
    monkeypatch.setattr(service, "_settings", lambda value=None: value if value is not None else settings)
    monkeypatch.setattr(service, "_log", lambda *args, **kwargs: None)
    return SimpleNamespace(repository=repository, settings=settings)


@pytest.fixture
def intake(screening_on):
    stores = {scope: DocumentStore() for scope in SCOPES}
    namespace = {
        "datetime": datetime, "timezone": timezone, "logging": logging, "re": re,
        "SCREENING_FIELD": SCREENING_FIELD,
        "SCREENING_EXEMPTION_FIELD": getattr(contracts, "SCREENING_EXEMPTION_FIELD", "screening_exemption"),
        "is_generated_screening_exempt": getattr(contracts, "is_generated_screening_exempt", lambda document: False),
        "ScreeningValidationError": ScreeningValidationError,
        "cosmos_user_documents_container": stores["personal"],
        "cosmos_group_documents_container": stores["group"],
        "cosmos_public_documents_container": stores["public"],
        "require_xsd_ingestion_capability": lambda *args, **kwargs: None,
        "set_document_chunk_visibility": lambda document, active: None,
        "_upsert_document_and_sync_access_index": lambda container, document, operation: container.upsert(document),
        "_get_blob_container_name": lambda **kwargs: "documents",
        "apply_document_provenance": provenance.apply_document_provenance,
        "validate_origin": provenance.validate_origin,
        "initial_document_marker": service.initial_document_marker,
        "add_file_task_to_file_processing_log": lambda *args, **kwargs: None,
        "log_event": lambda *args, **kwargs: None,
    }
    load_functions("functions_documents.py", {
        "create_document", "_build_carried_forward_metadata", "_document_revision_sort_key", "_safe_int",
        "ensure_list",
    }, namespace)

    def create(scope, document_id, *, file_name="report.md", **values):
        namespace["create_document"](
            file_name=file_name, user_id="user-1", document_id=document_id, num_file_chunks=0,
            status="Queued for processing", **SCOPES[scope], **values,
        )
        return deepcopy(stores[scope].records[document_id])

    return SimpleNamespace(
        create=create, stores=stores, create_document=namespace["create_document"], screening=screening_on,
    )


@pytest.mark.parametrize("scope", SCOPES)
def test_generated_documents_get_no_marker_while_uploads_and_file_sync_still_do(intake, scope):
    uploaded = intake.create(scope, "uploaded", file_name="upload.md")
    chat = intake.create(scope, "chat", file_name="chat.md", origin=provenance.chat_upload_origin(
        conversation_id="conversation-1", message_id="conversation-1_file_1",
    ))
    synced = intake.create(
        scope, "synced", file_name="synced.md",
        xsd_logical_path="folder/synced.md", xsd_family_namespace="file-sync:source-1",
    )
    for screened in (uploaded, chat, synced):
        assert screened[SCREENING_FIELD]["state"] == "pending_scan"
        assert screened["status"] == "Content screening pending"
        assert "screening_exemption" not in screened
        assert not document_is_available(screened)
    generated = intake.create(scope, "generated", file_name="generated.md", screening_exemption=generated_exemption())
    assert SCREENING_FIELD not in generated
    assert generated["screening_exemption"] == GENERATED
    assert generated["status"] == "Queued for processing"
    assert document_is_available(generated)


def test_the_exemption_belongs_to_one_version_and_is_never_carried_forward(intake):
    generated = intake.create("personal", "doc-1", screening_exemption=generated_exemption())
    uploaded = intake.create("personal", "doc-2")
    regenerated = intake.create("personal", "doc-3", screening_exemption=generated_exemption())
    assert generated["version"] == 1 and SCREENING_FIELD not in generated
    assert uploaded["version"] == 2 and SCREENING_FIELD in uploaded and "screening_exemption" not in uploaded
    assert regenerated["version"] == 3 and SCREENING_FIELD not in regenerated
    assert regenerated["screening_exemption"] == GENERATED


@pytest.mark.parametrize("exemption", [
    {"reason": "generated", "version": 2}, {"reason": "upload", "version": 1}, {"reason": "generated"}, "generated",
])
def test_a_malformed_exemption_is_refused_before_anything_is_written(intake, exemption):
    with pytest.raises(ScreeningValidationError):
        intake.create("personal", "doc-1", screening_exemption=exemption)
    assert intake.stores["personal"].records == {}


def test_an_existing_marker_still_wins_over_the_exemption(screening_on):
    marked = {
        "id": "doc-1", "user_id": "user-1", "version": 1, "screening_exemption": GENERATED,
        SCREENING_FIELD: {"state": "pending_review", "scan_id": "scan-1"},
    }
    assert service.document_requires_screening(marked, screening_on.settings) is True
    unmarked = {key: value for key, value in marked.items() if key != SCREENING_FIELD}
    assert service.document_requires_screening(unmarked, screening_on.settings) is False
    assert service.initial_document_marker(unmarked) is None


def test_prepare_document_upload_skips_a_generated_document(intake, monkeypatch, tmp_path):
    generated = intake.create("personal", "generated", screening_exemption=generated_exemption())
    monkeypatch.setattr(service, "_document_for_upload", lambda *args, **kwargs: deepcopy(generated))
    monkeypatch.setattr(service, "begin_scan", lambda *args, **kwargs: pytest.fail("Generated content is never scanned."))
    source = tmp_path / "report.md"
    source.write_text("Generated report with PRIVATE_CANARY", encoding="utf-8")
    assert service.prepare_document_upload("generated", "user-1", str(source), "report.md") is None
    assert intake.screening.repository.query("scan")["items"] == []


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_agent_generated_uploads_create_unscreened_documents(intake, tmp_path, scope):
    queued, processed = [], []

    def write_temp(content, suffix):
        path = tmp_path / f"{uuid.uuid4().hex}{suffix}"
        path.write_bytes(content)
        return str(path)

    namespace = {
        "Any": Any, "Dict": Dict, "os": os, "uuid": uuid,
        "require_generated_file_publication_allowed": lambda: None,
        "_write_temp_generated_file": write_temp,
        "_resolve_group_upload_target_for_current_user": lambda user_id, group_id="", default_group_id="": "group-1",
        "create_document": intake.create_document,
        "update_document": lambda **kwargs: None,
        "process_document_upload_background": lambda **kwargs: processed.append(kwargs),
        "_queue_document_upload_background_task": lambda **kwargs: queued.append(kwargs),
        "invalidate_group_search_cache": lambda *args, **kwargs: None,
        "invalidate_personal_search_cache": lambda *args, **kwargs: None,
        "log_document_upload": lambda **kwargs: None,
        "generated_screening_exemption": getattr(contracts, "generated_screening_exemption", lambda: None),
    }
    execute_functions("functions_simplechat_operations.py", {"_upload_generated_document_for_current_user"}, namespace)
    result = namespace["_upload_generated_document_for_current_user"](
        "user-1", "summary.md", b"# Generated summary", scope, group_id="group-1" if scope == "group" else "",
    )
    stored = intake.stores[scope].records[result["document"]["id"]]
    assert SCREENING_FIELD not in stored
    assert stored["screening_exemption"] == GENERATED
    assert len(queued) == 1 and processed == []


def test_upload_dispatch_processes_a_generated_document_without_screening(intake, monkeypatch):
    generated = intake.create("group", "generated", screening_exemption=generated_exemption())
    calls = []
    namespace = {
        "partial": __import__("functools").partial,
        "get_document_metadata": lambda *args, **kwargs: deepcopy(generated),
        "get_settings": lambda: intake.screening.settings,
        "document_requires_screening": service.document_requires_screening,
        "process_screened_upload": lambda *args, **kwargs: pytest.fail("Generated content is never screened."),
        "_process_document_upload_background_impl": lambda *args, **kwargs: calls.append((args, kwargs)),
        "PUBLICATION_BINDING": readiness.PUBLICATION_BINDING,
        "begin_publication_processing": lambda *args, **kwargs: pytest.fail("No publication binding."),
        "log_event": lambda *args, **kwargs: None,
    }
    execute_functions("functions_documents.py", {"process_document_upload_background"}, namespace)
    namespace["process_document_upload_background"](
        "generated", "user-1", "unused-temp-path", "report.md", group_id="group-1",
    )
    assert len(calls) == 1 and calls[0][1]["group_id"] == "group-1"


class CreationCalls(ast.NodeVisitor):
    """Collect create_document calls with their innermost enclosing function."""

    def __init__(self, module):
        self.module, self.stack, self.calls = module, [], []

    def visit_FunctionDef(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == "create_document":
            exempt = any(keyword.arg == "screening_exemption" for keyword in node.keywords)
            self.calls.append((self.module, self.stack[-1] if self.stack else "<module>", exempt))
        self.generic_visit(node)


def creation_calls():
    found = []
    for path in sorted(APP_ROOT.glob("*.py")):
        visitor = CreationCalls(path.name)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8-sig"), filename=path.name))
        found.extend(visitor.calls)
    return found


def test_only_generated_creation_sites_mark_their_documents():
    calls = creation_calls()
    exempt = {(module, function) for module, function, marked in calls if marked}
    screened = {(module, function) for module, function, marked in calls if not marked}
    assert exempt == {
        ("functions_simplechat_operations.py", "_upload_generated_document_for_current_user"),
        ("functions_artifact_publication.py", "_publish_generated_chat_artifact_for_user"),
    }
    assert screened >= {
        ("route_backend_documents.py", "api_user_upload_document"),
        ("route_backend_group_documents.py", "api_upload_group_document"),
        ("route_backend_public_documents.py", "api_upload_public_document"),
        ("route_external_public_documents.py", "external_upload_public_document"),
        ("functions_group_document_management.py", "upload_group_documents"),
        ("functions_public_document_management.py", "upload_public_documents"),
        ("functions_documents.py", "queue_personal_workspace_upload_from_temp_file"),
        ("functions_documents.py", "queue_group_workspace_upload_from_temp_file"),
        ("functions_file_sync.py", "_create_document_from_remote_file"),
    }
    assert not exempt & screened


# --- Bulk scans never enroll generated documents ---------------------------------------


def test_scan_jobs_skip_generated_documents_and_still_scan_uploads(service_runtime):
    repository = service_runtime.repository
    add_document(repository, "generated", file_name="generated.md", screening_exemption=generated_exemption())
    add_document(repository, "uploaded", file_name="uploaded.txt")
    job = create_job(repository)
    for _attempt in range(10):
        job = jobs.run_scan_job(job["id"], repository=repository)
        if job["status"] in jobs.FINISHED_JOB_STATUSES:
            break
    items = {
        item["subject"]["document_id"]: item
        for item in repository.query("work_item", filters={"job_id": job["id"]})["items"]
    }
    assert items["generated"]["status"] == "skipped"
    assert items["generated"]["error_code"] == "screening_not_required"
    generated = repository.read_document(Subject("personal", "owner", "generated", "1"))
    assert SCREENING_FIELD not in generated and document_is_available(generated)
    assert items["uploaded"]["status"] == "completed"
    uploaded = repository.read_document(Subject("personal", "owner", "uploaded", "1"))
    assert uploaded[SCREENING_FIELD]["state"] == "cleared"


def test_a_generated_document_cannot_begin_a_scan(service_runtime):
    repository = service_runtime.repository
    add_document(repository, "generated", file_name="generated.md", screening_exemption=generated_exemption())
    with pytest.raises(ScreeningConflictError) as raised:
        service.begin_scan(Subject("personal", "owner", "generated", "1"), "owner", repository=repository)
    assert raised.value.code == "screening_not_required"
    assert SCREENING_FIELD not in repository.read_document(Subject("personal", "owner", "generated", "1"))
    assert repository.query("scan")["items"] == []


# --- Metadata: edits and generated metadata keep a release --------------------------------


class ScanStore:
    def __init__(self, scan):
        self.scan = scan

    def read_item(self, item, partition_key):
        if item != self.scan["id"] or partition_key != self.scan["id"]:
            raise LookupError("The scan record was not found.")
        return deepcopy(self.scan)


def released_document():
    policy = {"enabled": True, "rules": [dict(ACTIVE_POLICY_RULE)]}
    fingerprint = content_fingerprint([contracts.ContentUnit("unit-1", "Released text", {})])
    active_blob = {"container": "documents", "path": "doc-1/released.txt", "etag": "etag-1", "content_hash": "hash-1"}
    document = {
        "id": "doc-1", "user_id": "user-1", "version": 1, "file_name": "released.txt", "title": "Original",
        SCREENING_FIELD: {
            "state": "cleared", "scan_id": "scan-1", "source_revision": "1", "review_required": False,
            "content_fingerprint": fingerprint, "policy_fingerprint": hash_payload(policy),
            "canonical_ref": {"name": "units"}, "active_blob": active_blob,
        },
    }
    scan = {
        "id": "scan-1", "kind": "scan", "subject": subject_from_document(document).to_dict(), "state": "cleared",
        "coverage_complete": True, "result_status": "pass", "content_fingerprint": fingerprint,
        "policy": policy, "policy_fingerprint": hash_payload(policy), "units_ref": {"name": "units"},
        "publication": {
            "active_blob": active_blob, "content_fingerprint": fingerprint,
            "metadata_fingerprint": contracts.metadata_fingerprint(document),
        },
    }
    return document, ScanStore(scan)


def test_editing_metadata_after_release_keeps_the_release_proof():
    document, scans = released_document()
    access._require_release_proof(document, scans)
    edited = {**document, "title": "Edited", "abstract": "Edited abstract", "tags": ["edited"]}
    access._require_release_proof(edited, scans)
    restored = {**edited, SCREENING_FIELD: {**edited[SCREENING_FIELD], "scan_id": "scan-2"}}
    with pytest.raises(DocumentHeldError):
        access._require_release_proof(restored, scans)


def test_a_rename_may_not_change_the_inspected_source_format():
    document, _scans = released_document()
    assert service.validate_screened_metadata_update(document, {"file_name": "renamed.TXT", "title": "New"}) is None
    with pytest.raises(ScreeningValidationError):
        service.validate_screened_metadata_update(document, {"file_name": "renamed.pdf"})
    assert service.validate_screened_metadata_update(
        {key: value for key, value in document.items() if key != SCREENING_FIELD}, {"file_name": "renamed.pdf"},
    ) is None


def test_model_generated_metadata_applies_without_a_hold(management):
    env = management
    env.settings["enable_content_screening"] = True
    source = env.source.records["document-a"]
    env.seed_release(source)
    marker = deepcopy(source[SCREENING_FIELD])
    namespace = env.document_helpers
    namespace["extract_document_metadata"] = lambda **kwargs: {
        "title": "Generated title", "authors": ["Model author"], "abstract": "Generated abstract",
        "keywords": ["generated"], "publication_date": "2026", "organization": "Contoso",
    }
    execute_functions("functions_documents.py", {"process_metadata_extraction_background"}, namespace)
    namespace["process_metadata_extraction_background"]("document-a", "owner", group_id="group-a")
    current = env.source.records["document-a"]
    assert current["title"] == "Generated title" and current["abstract"] == "Generated abstract"
    assert current[SCREENING_FIELD] == marker
    assert current["status"] == "Metadata extraction complete"
    assert document_is_available(current)
    available = env.access.assert_document_available("document-a", user_id="owner", group_id="group-a")
    assert available["title"] == "Generated title"
    assert {write.get("title") for write in env.chunk_writes} == {"Generated title"}
    assert env.blobs.metadata_writes == []
    assert env.queue.jobs == []


def test_a_rename_through_update_document_keeps_the_screened_source_format(management):
    env = management
    env.seed_release(env.source.records["document-a"])
    original = env.source.records["document-a"]["file_name"]
    suffix = Path(original).suffix
    with pytest.raises(ScreeningValidationError):
        env.document_helpers["update_document"](
            document_id="document-a", user_id="owner", group_id="group-a", file_name="renamed.unsupported",
        )
    assert env.source.records["document-a"]["file_name"] == original
    env.document_helpers["update_document"](
        document_id="document-a", user_id="owner", group_id="group-a", file_name=f"renamed{suffix}",
    )
    assert env.source.records["document-a"]["file_name"] == f"renamed{suffix}"
    assert document_is_available(env.source.records["document-a"])


# --- Publication: no screening reservation -----------------------------------------------


@pytest.fixture
def screened_group_publication(publication, tmp_path):
    """The real publication engine and create_document with screening on and an active policy."""
    import importlib.util

    from content_screening import repository as screening_repository
    from content_screening.storage import ScreeningStorage
    from test_content_screening_persistence import FakeBlobService

    env = publication
    patch = env.scoped_monkeypatch
    env.settings["enable_content_screening"] = True
    metadata = FakeCosmos()
    repository = ScreeningRepository(metadata, {"group": env.source})
    patch.setattr(env.config, "cosmos_content_screening_container", metadata)
    patch.setattr(screening_repository, "get_repository", lambda: repository)
    policy = default_policy()
    policy.update(enabled=True, rules=[dict(ACTIVE_POLICY_RULE)])
    repository.save_policy("global", "global", policy, "administrator")
    spec = importlib.util.spec_from_file_location(
        "content_screening.service", APP_ROOT / "content_screening" / "service.py",
    )
    screening = importlib.util.module_from_spec(spec)
    patch.setitem(sys.modules, "content_screening.service", screening)
    spec.loader.exec_module(screening)
    storage = ScreeningStorage(FakeBlobService())
    patch.setattr(screening, "_storage", lambda value=None: value if value is not None else storage)
    patch.setitem(env.document_helpers, "initial_document_marker", screening.initial_document_marker)
    patch.setattr(
        sys.modules["functions_documents"], "get_document_metadata",
        env.document_helpers["get_document_metadata"], raising=False,
    )

    def create_destination(**values):
        env.publication_calls["create"].append(deepcopy(values))
        return env.document_helpers["create_document"](**values)

    patch.setattr(env.canonical, "create_document", create_destination)
    source_path = tmp_path / "accepted.md"
    source_path.write_bytes(env.content)
    prepared = []

    def prepare():
        prepared.append(screening.prepare_document_upload(
            env.target, REQUESTER, str(source_path), env.source.records[env.target]["file_name"],
            group_id="group-a",
        ))

    env.publication_state["queue_hook"] = prepare
    env.screening_repository = repository
    env.prepared = prepared
    return env


def test_published_destination_is_unscreened_and_approval_needs_no_reservation(screened_group_publication):
    env = screened_group_publication
    created = submit(env)
    assert SCREENING_FIELD not in created
    assert created["screening_exemption"] == GENERATED
    assert env.publication_calls["create"][0]["screening_exemption"] == GENERATED
    assert not any(str(key).startswith("screening_") for key in receipt(env))
    view = sharing(env)
    assert "approve_artifact" in view.get_json()["actions"]
    assert "screening_exemption" not in str(view.get_json())
    response = decide(env, "approve")
    assert_receipt(response, env, "approve", "queued", "approved", 202)
    current = env.source.read_item(env.target, env.target)
    saved = receipt(env)
    assert SCREENING_FIELD not in current
    assert saved["decision"]["choice"] == "approved" and "operation_id" not in saved["decision"]
    assert not any(str(key).startswith("screening_") for key in saved)
    assert len(env.publication_calls["queue_attempts"]) == 1
    assert env.prepared == [None]
    assert env.screening_repository.query("scan")["items"] == []
    detail = env.client.get(f"/api/group_documents/{env.target}?group_id=group-a")
    assert "screening_exemption" not in str(detail.get_json())


def test_publication_readiness_counts_a_marker_free_destination_as_screened():
    binding = {
        "version": 1, "receipt_id": "receipt-1", "document_version": 1, "content_sha256": "sha-1",
        "conversation_id": "conversation-1", "artifact_message_id": "artifact-1",
    }
    saved = {
        "id": "receipt-1", "content_sha256": "sha-1", "document_version": 1, "actor_user_id": "user-1",
        "destination": {"workspace_scope": "group", "group_id": "group-1"},
        "artifact_reference": {"conversation_id": "conversation-1", "artifact_message_id": "artifact-1"},
    }
    destination = {
        "id": "doc-1", "group_id": "group-1", "version": 1, "user_id": "user-1",
        "generated_artifact_publication_receipt_id": "receipt-1", "screening_exemption": GENERATED,
        readiness.PUBLICATION_BINDING: binding,
        readiness.PUBLICATION_PROCESSING: {"binding": binding, "state": "complete", "indexed_chunks": 2},
    }
    ready = readiness.inspect_publication_readiness(
        saved, destination, available_reader=lambda *args, **kwargs: deepcopy(destination),
        index_count=lambda *args: 2,
    )
    assert ready == {"processing": "complete", "screening": "not_required", "index": "ready"}

    def held(*args, **kwargs):
        raise DocumentHeldError()

    denied = readiness.inspect_publication_readiness(saved, destination, available_reader=held, index_count=lambda *args: 2)
    assert denied["reason_code"] == "publication_screening_unavailable"


def test_the_publication_reservation_and_metadata_rescan_are_gone():
    removed = {
        "consume_artifact_publication_screening_scan", "_consume_publication_reservation",
        "publication_screening_reservation", "_enroll_screening_reservation",
        "_reservation_has_screening_history", "_bootstrap_retry_operation_id", "queue_metadata_rescan",
    }
    defined = set()
    for path in [*APP_ROOT.glob("*.py"), *(APP_ROOT / "content_screening").glob("*.py")]:
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=path.name)
        defined |= {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in removed
        }
        assert "screening_reservation" not in source, path.name
    assert defined == set()


@pytest.mark.parametrize("first", ["content_screening.service", "functions_artifact_publication_readiness"])
def test_screening_and_readiness_modules_keep_real_cold_imports_below_azure_bootstrap(first):
    second = (
        "functions_artifact_publication_readiness"
        if first == "content_screening.service" else "content_screening.service"
    )
    code = (
        "import importlib, socket, sys\n"
        "def blocked(*args, **kwargs):\n"
        "    raise RuntimeError('Network forbidden during cold import')\n"
        "socket.create_connection = blocked\n"
        "socket.socket.connect = blocked\n"
        f"importlib.import_module({first!r})\n"
        f"importlib.import_module({second!r})\n"
        "if any(name in sys.modules for name in ('config', 'functions_settings', 'functions_artifact_publication')):\n"
        "    raise RuntimeError('Readiness or screening initialized application owners')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=APP_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), *sys.argv[1:]]))
