# test_content_screening_jobs.py
"""
Behavioral tests for durable content screening jobs and crash recovery.
Version: 0.261.106
Implemented in: 0.261.106

Uses fake Cosmos/Blob clients, real service/detector/CAS methods, a controlled
clock, and external processor doubles. No live Azure resources are read.
"""

import json
import sys
import threading
import types
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from flask import Flask, session


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from content_screening import access, checkpoints, engine, jobs, service
from content_screening.contracts import (
    ContentUnit,
    DocumentHeldError,
    ScreeningConflictError,
    Subject,
    content_fingerprint,
    document_is_available,
    hash_payload,
    metadata_fingerprint,
)
from content_screening.extraction import current_extraction, heartbeat_publication
from content_screening.permissions import assert_subject_access
from content_screening.policies import default_policy
from content_screening.repository import ScreeningRepository
from content_screening.storage import ScreeningStorage
import test_content_screening_model as model_test_support
from test_content_screening_persistence import FakeBlobService, FakeCosmos


@pytest.fixture
def runtime(monkeypatch):
    metadata = FakeCosmos()
    containers = {
        scope: FakeCosmos(partition_field="id") for scope in ("personal", "group", "public")
    }
    repository = ScreeningRepository(metadata, containers)
    clock = {"now": datetime(2026, 9, 8, 12, tzinfo=timezone.utc)}
    monkeypatch.setattr(jobs, "_now", lambda: clock["now"])
    monkeypatch.setattr(jobs, "_assert_migration_open", lambda: None)
    monkeypatch.setattr(jobs, "_screening_enabled", lambda: True)
    monkeypatch.setattr(jobs, "_configuration_snapshot", lambda *_args: {"baseline": None, "workspace": None})
    logs = []
    monkeypatch.setattr(jobs, "_log", lambda code, **metadata: logs.append({"code": code, **metadata}))
    return repository, clock, logs


def add_document(repository, document_id, scope="personal", scope_id="owner", revision=1, **extra):
    field = {"personal": "user_id", "group": "group_id", "public": "public_workspace_id"}[scope]
    return repository.document_container(scope).create_item({
        "id": document_id, field: scope_id, "version": revision, "file_name": "private-canary.txt", **extra,
    })


def create_job(repository, ids=None, **scope):
    selection = {"scope_type": "personal", "scope_id": "owner", **scope}
    if ids is not None:
        selection["document_ids"] = ids
    return jobs.create_scan_job("owner", selection, repository=repository)


def enroll_scan(repository, *, actor_id="owner", scope="personal", scope_id="owner", scan_id="upload-scan", file_name="original.txt", lease=None, source_ref=None):
    document = add_document(repository, "one", scope, scope_id, file_name=file_name)
    subject = Subject(scope, scope_id, "one", "1")
    policy = {"enabled": True}
    scan = repository.create({
        "id": scan_id, "partition_key": scan_id, "kind": "scan",
        "subject": subject.to_dict(), "actor_id": actor_id, "state": "pending_scan",
        "policy": policy, "policy_fingerprint": hash_payload(policy),
        "original_file_name": file_name, "source_ref": source_ref,
        "lease": lease, "finding_count": 0, "review_required": False,
    })
    repository.update_document(subject, {
        "content_screening": {
            "state": "pending_scan", "scan_id": scan_id, "source_revision": "1",
        },
    }, etag=document["_etag"])
    return subject, scan


def completing_processor(repository, calls, *, finding_ids=()):
    def processor(subject, actor_id, *, job_id):
        document = repository.read_document(subject)
        assert not document_is_available(document)
        calls.append((subject.key, actor_id))
        marker = document["content_screening"]
        findings = subject.document_id in finding_ids
        state = "pending_review" if findings else "cleared"
        repository.update_document(subject, {
            "content_screening": {
                **marker, "state": state, "content_fingerprint": hash_payload(subject.key),
                "finding_count": int(findings), "review_required": findings,
            },
        }, etag=document["_etag"])
        return {"state": state}
    return processor


def complete_external_processor_fixture(repository, subject):
    """Give isolated external-processor doubles the same terminal proof contract."""
    document = repository.read_document(subject)
    marker = document["content_screening"]
    scan = repository.get_scan(marker["scan_id"])
    reference = {"protected": "processor-test-units"}
    active_blob = {
        "container": "processor-test-projection", "path": scan["id"],
        "etag": "processor-test-etag", "content_hash": hash_payload(subject.key),
    }
    document = repository.update_document(subject, {
        "blob_container": active_blob["container"], "blob_path": active_blob["path"],
        "blob_etag": active_blob["etag"], "blob_content_hash": active_blob["content_hash"],
        "content_screening": {
            **marker, "canonical_ref": reference, "active_blob": active_blob,
            "policy_fingerprint": scan["policy_fingerprint"],
        },
    }, etag=document["_etag"])
    return repository.replace({
        **scan, "state": "cleared", "content_fingerprint": marker["content_fingerprint"],
        "coverage_complete": True, "result_status": "pass", "units_ref": reference,
        "publication": {
            "active_blob": active_blob, "content_fingerprint": marker["content_fingerprint"],
            "metadata_fingerprint": metadata_fingerprint(document),
        },
    }, scan["_etag"])


def drain(repository, job_id, processor, *, maximum=20):
    for _attempt in range(maximum):
        job = jobs.run_scan_job(job_id, processor=processor, repository=repository)
        if job["status"] in jobs.FINISHED_JOB_STATUSES:
            return job
    raise AssertionError("The durable job did not finish its bounded slices.")


def test_queue_does_not_hold_documents_and_claim_holds_before_processing(runtime):
    repository, _clock, _logs = runtime
    add_document(repository, "one")
    job = create_job(repository, ["one"])
    assert document_is_available(repository.document_container("personal").read_item("one", "one"))
    assert not repository.query("work_item")["items"]
    calls = []
    result = drain(repository, job["id"], completing_processor(repository, calls))
    assert result["status"] == "completed"
    assert result["counts"]["completed"] == result["counts"]["total"] == 1
    assert len(calls) == 1
    item = repository.query("work_item")["items"][0]
    assert item["checkpoint"]["stage"] == "completed"
    assert item["started"] and not item["lease"]


def test_all_workspace_scan_pages_every_scope_and_historical_revision(runtime, monkeypatch):
    repository, _clock, _logs = runtime
    monkeypatch.setattr(jobs, "ENUMERATION_PAGE_SIZE", 2)
    monkeypatch.setattr(jobs, "MAX_ITEMS_PER_RUN", 2)
    for scope in jobs.SCOPE_ORDER:
        for index in range(5):
            add_document(repository, f"{scope}-{index}", scope, f"scope-{scope}", index + 1, is_current_version=index == 4)
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        session["user"] = {"oid": "administrator", "roles": ["Admin"]}
        job = jobs.create_scan_job("administrator", {"all_workspaces": True}, is_admin=True, repository=repository)
    calls = []
    result = drain(repository, job["id"], completing_processor(repository, calls))
    assert result["status"] == "completed"
    assert result["counts"]["total"] == result["counts"]["completed"] == 15
    assert len({subject_key for subject_key, _actor in calls}) == 15
    assert result["enumeration"]["pages"] == 9
    assert "items" not in result
    assert result["enumeration"]["complete"]


def test_request_body_admin_flags_are_not_authority(runtime):
    repository, *_ = runtime
    with pytest.raises(PermissionError):
        jobs.create_scan_job("owner", {"all_workspaces": True}, is_admin=True, repository=repository)
    with pytest.raises(PermissionError):
        create_job(repository, scope_id="other-owner")
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        session["user"] = {"oid": "owner", "roles": ["User"]}
        with pytest.raises(PermissionError):
            jobs.create_scan_job("owner", {"all_workspaces": True}, is_admin=True, repository=repository)
        session["user"] = {"oid": "administrator", "roles": ["Admin"]}
        with pytest.raises(PermissionError):
            jobs.create_scan_job("spoofed-actor", {"all_workspaces": True}, is_admin=True, repository=repository)
    assert repository.count("job") == 0


def test_duplicate_workers_cannot_claim_the_same_item(runtime):
    repository, *_ = runtime
    add_document(repository, "one")
    job = create_job(repository, ["one"])
    entered, release = threading.Event(), threading.Event()
    calls = []
    complete = completing_processor(repository, calls)

    def processor(subject, actor_id, **kwargs):
        entered.set()
        assert release.wait(5)
        return complete(subject, actor_id, **kwargs)

    outputs = []
    worker = threading.Thread(target=lambda: outputs.append(jobs.run_scan_job(job["id"], processor=processor, repository=repository)))
    worker.start()
    try:
        assert entered.wait(5)
        duplicate = jobs.run_scan_job(job["id"], processor=processor, repository=repository)
        assert duplicate["status"] == "running"
        assert not calls
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert len(calls) == 1
    assert outputs[0]["counts"]["completed"] == 1


def test_crash_after_scan_commit_is_resumed_without_reprocessing(runtime):
    repository, clock, _logs = runtime
    add_document(repository, "one")
    job = create_job(repository, ["one"])
    calls = []
    complete = completing_processor(repository, calls)

    def crash(subject, actor_id, **kwargs):
        result = complete(subject, actor_id, **kwargs)
        document = repository.read_document(subject)
        scan_id = document["content_screening"]["scan_id"]
        policy, units_ref = {"enabled": True}, {"protected": "canonical-units"}
        active_blob = {"container": "approved", "path": "released", "etag": "released-etag", "content_hash": hash_payload("released")}
        document = repository.update_document(subject, {
            "blob_container": active_blob["container"], "blob_path": active_blob["path"],
            "blob_etag": active_blob["etag"], "blob_content_hash": active_blob["content_hash"],
            "content_screening": {
                **document["content_screening"], "canonical_ref": units_ref,
                "policy_fingerprint": hash_payload(policy), "active_blob": active_blob,
            },
        }, etag=document["_etag"])
        repository.create({
            "id": scan_id, "partition_key": scan_id, "kind": "scan",
            "subject": subject.to_dict(), "state": "cleared", "finding_count": 0,
            "coverage_complete": True, "result_status": "pass",
            "content_fingerprint": document["content_screening"]["content_fingerprint"],
            "policy": policy, "policy_fingerprint": hash_payload(policy), "units_ref": units_ref,
            "publication": {
                "active_blob": active_blob, "metadata_fingerprint": metadata_fingerprint(document),
                "content_fingerprint": document["content_screening"]["content_fingerprint"],
            },
        })
        raise SystemExit("simulated-worker-loss")

    with pytest.raises(SystemExit):
        jobs.run_scan_job(job["id"], processor=crash, repository=repository)
    saved = repository.get(job["id"], job["id"])
    assert saved["lease"] and saved["status"] == "running"
    clock["now"] += timedelta(seconds=jobs.LEASE_SECONDS + 1)
    restarted = ScreeningRepository(repository.container, repository._document_containers)
    result = drain(restarted, job["id"], complete)
    assert result["counts"]["completed"] == 1
    assert len(calls) == 1


def test_partial_enumeration_checkpoint_recovers_duplicate_items(runtime, monkeypatch):
    repository, clock, _logs = runtime
    for index in range(5):
        add_document(repository, f"doc-{index}")
    job = create_job(repository)
    original = jobs._create_item
    attempts = {"count": 0}

    def crash_after_item(*args, **kwargs):
        item = original(*args, **kwargs)
        attempts["count"] += 1
        if attempts["count"] == 2:
            raise SystemExit()
        return item

    monkeypatch.setattr(jobs, "_create_item", crash_after_item)
    with pytest.raises(SystemExit):
        jobs.run_scan_job(job["id"], repository=repository)
    assert repository.count("work_item") == 2
    assert all(document_is_available(item) for item in repository.document_container("personal").documents.values())
    clock["now"] += timedelta(seconds=jobs.LEASE_SECONDS + 1)
    monkeypatch.setattr(jobs, "_create_item", original)
    calls = []
    result = drain(repository, job["id"], completing_processor(repository, calls))
    assert result["counts"]["total"] == len(calls) == 5


def test_cancel_holds_started_work_and_leaves_queued_documents_untouched(runtime):
    repository, *_ = runtime
    for document_id in ("one", "two", "three"):
        add_document(repository, document_id)
    job = create_job(repository)
    started = []

    def cancel(subject, actor_id, **kwargs):
        started.append(subject)
        jobs.request_scan_job_action(job["id"], actor_id, "cancel", repository=repository)
        return {"state": "incomplete"}

    result = drain(repository, job["id"], cancel)
    assert result["status"] == "cancelled"
    assert len(started) == 1
    assert repository.read_document(started[0])["content_screening"]["state"] == "incomplete"
    unstarted = [
        document for document in repository.document_container("personal").documents.values()
        if document["id"] != started[0].document_id
    ]
    assert all("content_screening" not in document and document_is_available(document) for document in unstarted)
    resumed = jobs.request_scan_job_action(job["id"], "owner", "resume", repository=repository)
    assert resumed["status"] == "queued"
    calls = []
    finished = drain(repository, job["id"], completing_processor(repository, calls))
    assert finished["counts"]["completed"] == 3


def test_partial_failures_retry_boundedly_and_are_not_reported_as_clean(runtime):
    repository, clock, logs = runtime
    for document_id in ("clean", "flagged", "broken"):
        add_document(repository, document_id)
    job = create_job(repository)
    calls = []
    complete = completing_processor(repository, calls, finding_ids={"flagged"})

    def process(subject, actor_id, **kwargs):
        if subject.document_id == "broken":
            raise RuntimeError("private-document-secret-canary")
        return complete(subject, actor_id, **kwargs)

    for _attempt in range(8):
        result = jobs.run_scan_job(job["id"], processor=process, repository=repository)
        if result["status"] in jobs.FINISHED_JOB_STATUSES:
            break
        clock["now"] += timedelta(minutes=5)
    assert result["status"] == "incomplete"
    assert result["counts"]["failed"] == result["counts"]["completed"] == result["counts"]["findings"] == 1
    failed = repository.query("work_item", filters={"status": "failed"})["items"][0]
    assert failed["attempts"] == jobs.MAX_ATTEMPTS
    assert not document_is_available(repository.read_document(Subject.from_dict(failed["subject"])))
    assert "private-document-secret-canary" not in repr(result) + repr(failed) + repr(logs)


def test_source_replacement_cannot_be_cleared_by_stale_work(runtime, monkeypatch):
    repository, *_ = runtime
    add_document(repository, "one")
    job = create_job(repository, ["one"])
    original = jobs._hold_document

    def replace_source(repo, current_job, item, owner, **kwargs):
        stored = repo.document_container("personal").documents[("one", "one")]
        stored["version"] = 2
        return original(repo, current_job, item, owner, **kwargs)

    monkeypatch.setattr(jobs, "_hold_document", replace_source)
    calls = []
    result = drain(repository, job["id"], completing_processor(repository, calls))
    assert result["status"] == "incomplete"
    assert result["counts"]["skipped"] == 1
    assert not calls
    assert "content_screening" not in repository.document_container("personal").documents[("one", "one")]


def test_missing_selected_documents_are_explicitly_skipped(runtime):
    repository, *_ = runtime
    job = create_job(repository, ["deleted"])
    result = drain(repository, job["id"], completing_processor(repository, []))
    assert result["status"] == "incomplete"
    assert result["counts"]["skipped"] == result["counts"]["total"] == 1


def test_revoked_scope_management_blocks_get_resume_and_worker_boundaries(runtime, monkeypatch):
    repository, *_ = runtime
    permitted = {"value": True}

    def authorize(actor_id, group_id, *, allowed_roles):
        assert actor_id == "owner" and group_id == "group"
        assert set(allowed_roles) == {"Owner", "Admin", "DocumentManager"}
        if not permitted["value"]:
            raise PermissionError()
        return "DocumentManager"

    monkeypatch.setitem(sys.modules, "functions_group", types.SimpleNamespace(assert_group_role=authorize))
    add_document(repository, "one", "group", "group")
    job = create_job(repository, scope_type="group", scope_id="group")
    permitted["value"] = False
    with pytest.raises(PermissionError):
        jobs.get_scan_job(job["id"], "owner", repository=repository)
    result = jobs.run_scan_job(job["id"], processor=completing_processor(repository, []), repository=repository)
    assert result["status"] == "incomplete"
    assert "content_screening" not in repository.document_container("group").documents[("one", "one")]
    with pytest.raises(PermissionError):
        jobs.request_scan_job_action(job["id"], "owner", "resume", repository=repository)


def test_migration_freeze_does_not_start_or_release_documents(runtime, monkeypatch):
    repository, *_ = runtime
    add_document(repository, "one")
    job = create_job(repository)

    def frozen():
        raise jobs.ScreeningJobStopped(code="screening_migration_frozen")

    monkeypatch.setattr(jobs, "_assert_migration_open", frozen)
    result = jobs.run_scan_job(job["id"], processor=completing_processor(repository, []), repository=repository)
    assert result["status"] == "queued"
    assert not repository.query("work_item")["items"]
    assert "content_screening" not in repository.document_container("personal").documents[("one", "one")]


def test_disabled_feature_does_not_drain_queued_jobs(runtime, monkeypatch):
    repository, *_ = runtime
    add_document(repository, "one")
    job = create_job(repository)
    monkeypatch.setattr(jobs, "_screening_enabled", lambda: False)
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "queued" and result["lease"] is None
    assert repository.count("work_item") == 0


def test_heartbeat_extends_job_and_item_leases(runtime):
    repository, clock, _logs = runtime
    add_document(repository, "one")
    job = create_job(repository)
    claimed, owner = jobs._claim_job(repository, job)
    claimed = jobs._enumerate(repository, claimed, owner)
    candidate = repository.query("work_item")["items"][0]
    item = jobs._claim_item(repository, claimed, candidate, owner)
    clock["now"] += timedelta(seconds=200)
    jobs._heartbeat(repository, job["id"], owner, item["id"])
    clock["now"] += timedelta(seconds=101)
    current = repository.get(job["id"], job["id"])
    assert jobs._claim_job(repository, current) is None
    renewed = repository.get(item["id"], job["id"])
    assert renewed["heartbeat_at"] and not jobs._expired(renewed["lease"]["expires_at"])


def test_scheduler_discovers_jobs_after_pages_of_active_workers(runtime, monkeypatch):
    repository, *_ = runtime
    monkeypatch.setattr(jobs, "ENUMERATION_PAGE_SIZE", 2)
    for index in range(6):
        job = jobs._new_job(
            "owner", {"scope_type": "personal", "scope_id": "owner"}, False,
            {"baseline": None, "workspace": None}, job_id=f"job-{index}",
        )
        job["partition_key"] = job["id"]
        repository.create(job)
    ordered = sorted(
        [record for record in repository.container.documents.values() if record["kind"] == "job"],
        key=lambda record: record["sort_key"],
    )
    for job in ordered[:-1]:
        repository.replace({
            **job, "status": "running",
            "lease": {"owner": "other-worker", "expires_at": (jobs._now() + timedelta(hours=1)).isoformat()},
        }, job["_etag"])
    queued_id = ordered[-1]["id"]
    called = []
    monkeypatch.setattr(jobs, "run_scan_job", lambda job_id, **kwargs: called.append(job_id))
    assert jobs.check_due_scan_jobs_once(repository=repository, max_jobs=1) == [queued_id]
    assert called == [queued_id]
    assert len([
        query for query in repository.container.queries
        if {"name": "@kind", "value": "job"} in query["parameters"]
    ]) == 3


def test_ingestion_enqueue_is_idempotent_and_recovers_a_missing_item(runtime):
    repository, *_ = runtime
    document = add_document(repository, "one")
    subject = Subject("personal", "owner", "one", "1")
    repository.create({
        "id": "upload-scan", "partition_key": "upload-scan", "kind": "scan",
        "subject": subject.to_dict(), "actor_id": "owner", "state": "pending_scan",
    })
    repository.update_document(subject, {
        "content_screening": {"state": "pending_scan", "scan_id": "upload-scan", "source_revision": "1"},
    }, etag=document["_etag"])
    job = jobs.enqueue_document_scan(subject, "owner", scan_id="upload-scan", repository=repository)
    repeated = jobs.enqueue_document_scan(subject, "owner", scan_id="upload-scan", repository=repository)
    assert repeated["id"] == job["id"]
    item = repository.query("work_item")["items"][0]
    del repository.container.documents[(item["id"], item["partition_key"])]
    calls = []
    result = drain(repository, job["id"], completing_processor(repository, calls))
    assert result["status"] == "completed"
    recovered = repository.query("work_item")["items"][0]
    assert recovered["scan_id"] == "upload-scan"
    assert len(calls) == 1


def test_lost_worker_cannot_commit_after_a_new_lease(runtime):
    repository, *_ = runtime
    add_document(repository, "one")
    job = create_job(repository)

    def lose_lease(subject, actor_id, *, job_id):
        current = repository.get(job_id, job_id)
        repository.replace({
            **current, "lease": {"owner": "new-worker", "expires_at": (jobs._now() + timedelta(hours=1)).isoformat()},
        }, current["_etag"])
        jobs.assert_scan_job_active(job_id, subject, repository=repository)
        raise AssertionError("A stale worker was permitted to publish.")

    result = jobs.run_scan_job(job["id"], processor=lose_lease, repository=repository)
    assert result["lease"]["owner"] == "new-worker"
    assert not document_is_available(repository.read_document(Subject("personal", "owner", "one", "1")))
    assert repository.query("work_item")["items"][0]["status"] == "running"


def test_global_admission_bounds_parallel_jobs_and_recovers_expired_slots(runtime):
    repository, clock, _logs = runtime
    first, second, third = [create_job(repository) for _index in range(3)]
    assert jobs._claim_job(repository, first) is not None
    assert jobs._claim_job(repository, second) is not None
    assert jobs._claim_job(repository, third) is None
    assert repository.count("work_item") == 0
    slots = repository.get(jobs.RUNNER_ADMISSION_ID, jobs.RUNNER_ADMISSION_ID)["slots"]
    assert len(slots) == jobs.MAX_CONCURRENT_JOBS
    clock["now"] += timedelta(seconds=jobs.LEASE_SECONDS + 1)
    assert jobs._claim_job(repository, repository.get(third["id"], third["id"])) is not None


def test_default_processor_keeps_the_pre_hold_scan_lineage(runtime, monkeypatch):
    repository, *_ = runtime
    document = add_document(repository, "one")
    subject = Subject("personal", "owner", "one", "1")
    repository.update_document(subject, {"content_screening": {
        "state": "cleared", "source_revision": "1", "scan_id": "previous-scan",
        "content_fingerprint": "old-fingerprint", "canonical_ref": {"protected": "previous"},
    }}, etag=document["_etag"])
    job = create_job(repository, ["one"])
    monkeypatch.setattr(service, "_settings", lambda: {"enable_content_screening": True})
    monkeypatch.setattr(service, "validate_screening_configuration", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "get_effective_policy", lambda *_args, **_kwargs: {"enabled": True})
    monkeypatch.setattr(service, "_log", lambda *_args, **_kwargs: None)
    complete = completing_processor(repository, [])

    def scan_existing(subject, actor_id, **kwargs):
        complete(subject, actor_id, job_id=kwargs["job_id"])
        return complete_external_processor_fixture(repository, subject)

    monkeypatch.setattr(service, "scan_existing_document", scan_existing)
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "completed"
    item = repository.query("work_item")["items"][0]
    scan = repository.get_scan(item["scan_id"])
    assert scan["previous_marker"]["scan_id"] == "previous-scan"
    assert scan["previous_marker"]["canonical_ref"] == {"protected": "previous"}


def test_changed_blob_without_revision_bump_is_not_scanned_as_the_snapshot(runtime, monkeypatch):
    repository, *_ = runtime
    add_document(repository, "one", blob_path="original", blob_etag="original-version")
    job = create_job(repository)
    original = jobs._hold_document

    def change_blob(repo, current_job, item, owner, **kwargs):
        repo.document_container("personal").documents[("one", "one")]["blob_etag"] = "different-source"
        return original(repo, current_job, item, owner, **kwargs)

    monkeypatch.setattr(jobs, "_hold_document", change_blob)
    result = jobs.run_scan_job(job["id"], processor=completing_processor(repository, []), repository=repository)
    item = repository.query("work_item")["items"][0]
    assert result["status"] == "incomplete"
    assert item["status"] == "skipped" and item["error_code"] == "screening_source_changed"
    assert "content_screening" not in repository.document_container("personal").documents[("one", "one")]


def test_unit_checkpoints_are_durable_bounded_and_lease_guarded(runtime):
    repository, *_ = runtime
    add_document(repository, "one")
    job = create_job(repository)
    complete = completing_processor(repository, [])
    saved = []

    def process(subject, actor_id, *, job_id):
        saved.append(jobs.checkpoint_scan_job_item(job_id, subject, {
            "stage": "scanning", "units_total": 10, "units_completed": 4,
            "last_unit_hash": hash_payload("unit-four"),
        }, repository=repository))
        return complete(subject, actor_id, job_id=job_id)

    result = drain(repository, job["id"], process)
    assert result["status"] == "completed"
    item = repository.query("work_item")["items"][0]
    assert saved[0]["checkpoint"]["units_completed"] == item["checkpoint"]["units_completed"] == 4
    with pytest.raises(jobs.ScreeningJobStopped):
        jobs.checkpoint_scan_job_item(job["id"], Subject("personal", "owner", "one", "1"), {"stage": "scanning"}, repository=repository)


def test_cancelled_processor_cannot_release_through_the_repository(runtime):
    repository, *_ = runtime
    add_document(repository, "one")
    job = create_job(repository)
    complete = completing_processor(repository, [])

    def ignore_cancel(subject, actor_id, *, job_id):
        jobs.request_scan_job_action(job_id, actor_id, "cancel", repository=repository)
        return complete(subject, actor_id, job_id=job_id)

    result = drain(repository, job["id"], ignore_cancel)
    assert result["status"] == "cancelled"
    assert repository.read_document(Subject("personal", "owner", "one", "1"))["content_screening"]["state"] == "incomplete"


def test_internal_enqueue_validates_enrollment_and_scan_id_idempotency(runtime):
    repository, *_ = runtime
    subject, scan = enroll_scan(repository)
    job = jobs.enqueue_document_scan(subject, "owner", repository=repository)
    assert job["counts"]["total"] == job["counts"]["queued"] == 1
    assert jobs.enqueue_document_scan(subject, "owner", scan_id=scan["id"], repository=repository)["id"] == job["id"]
    with pytest.raises(ScreeningConflictError):
        jobs.enqueue_document_scan(subject, "different-actor", repository=repository)
    with pytest.raises(ScreeningConflictError):
        jobs.enqueue_document_scan(Subject("personal", "other", "one", "1"), "owner", repository=repository)
    replacement = repository.create({**scan, "id": "next-scan", "partition_key": "next-scan"})
    document = repository.read_document(subject)
    repository.update_document(subject, {
        "content_screening": {**document["content_screening"], "scan_id": replacement["id"]},
    }, etag=document["_etag"])
    next_job = jobs.enqueue_document_scan(subject, "owner", scan_id=replacement["id"], repository=repository)
    assert next_job["id"] != job["id"]
    assert repository.count("work_item") == 2
    with pytest.raises(ScreeningConflictError):
        jobs.enqueue_document_scan(subject, "owner", scan_id=scan["id"], repository=repository)


def test_internal_upload_enqueue_does_not_grant_public_management_rights(runtime, monkeypatch):
    repository, *_ = runtime
    principal = "authorized-upload-application"
    subject, scan = enroll_scan(repository, actor_id=principal, scope="public", scope_id="workspace")
    monkeypatch.setitem(sys.modules, "functions_public_workspaces", types.SimpleNamespace(
        find_public_workspace_by_id=lambda _scope: {"owner": {"userId": "workspace-owner"}},
        get_user_role_in_public_workspace=lambda *_args: "User",
    ))
    with pytest.raises(PermissionError):
        jobs.create_scan_job(
            principal, {"scope_type": "public", "scope_id": "workspace", "document_ids": ["one"]},
            repository=repository,
        )
    job = jobs.enqueue_document_scan(subject, principal, scan_id=scan["id"], repository=repository)
    with pytest.raises(PermissionError):
        jobs.get_scan_job(job["id"], principal, repository=repository)
    calls = []
    result = drain(repository, job["id"], completing_processor(repository, calls))
    assert result["status"] == "completed"
    assert calls == [(subject.key, principal)]


@pytest.mark.parametrize("release_early", [False, True])
def test_active_per_scan_lease_defers_without_document_writes_or_attempts(runtime, release_early):
    repository, clock, _logs = runtime
    expires_at = (clock["now"] + timedelta(hours=1)).isoformat()
    subject, scan = enroll_scan(repository, lease={"owner": "active-extractor", "expires_at": expires_at})
    job = jobs.enqueue_document_scan(subject, "owner", repository=repository)
    original_document = repository.read_document(subject)
    original_scan = repository.get_scan(scan["id"])
    calls = []
    result = jobs.run_scan_job(job["id"], processor=completing_processor(repository, calls), repository=repository)
    assert result["status"] == "queued" and result["counts"]["queued"] == 1
    item = repository.query("work_item")["items"][0]
    assert item["attempts"] == 0 and item["started"] is False
    assert item["checkpoint"]["stage"] == "waiting_for_scan_lease"
    assert item["next_attempt_at"] == expires_at
    assert repository.read_document(subject) == original_document
    assert repository.get_scan(scan["id"]) == original_scan
    assert not calls
    if release_early:
        repository.replace({**original_scan, "lease": None}, original_scan["_etag"])
    else:
        clock["now"] += timedelta(hours=1, seconds=1)
    result = drain(repository, job["id"], completing_processor(repository, calls))
    assert result["status"] == "completed"
    assert len(calls) == 1
    assert repository.query("work_item")["items"][0]["attempts"] == 1


def test_scan_lease_race_after_item_claim_is_deferred_without_error_hold(runtime, monkeypatch):
    repository, clock, _logs = runtime
    subject, scan = enroll_scan(repository)
    job = jobs.enqueue_document_scan(subject, "owner", repository=repository)
    original_document = repository.read_document(subject)
    original_hold = jobs._hold_document

    def acquire_scan_lease(repo, current_job, item, owner, **kwargs):
        current = repo.get_scan(scan["id"])
        repo.replace({
            **current, "state": "extracting",
            "lease": {"owner": "competing-extractor", "expires_at": (clock["now"] + timedelta(hours=1)).isoformat()},
        }, current["_etag"])
        return original_hold(repo, current_job, item, owner, **kwargs)

    monkeypatch.setattr(jobs, "_hold_document", acquire_scan_lease)
    calls = []
    result = jobs.run_scan_job(job["id"], processor=completing_processor(repository, calls), repository=repository)
    item = repository.query("work_item")["items"][0]
    assert result["status"] == "queued"
    assert item["attempts"] == 0 and item["error_code"] is None
    assert item["checkpoint"]["stage"] == "waiting_for_scan_lease"
    assert repository.read_document(subject) == original_document
    assert repository.get_scan(scan["id"])["lease"]["owner"] == "competing-extractor"
    assert not calls


def test_parent_scanner_busy_result_does_not_overwrite_its_active_marker(runtime):
    repository, clock, _logs = runtime
    subject, scan = enroll_scan(repository)
    job = jobs.enqueue_document_scan(subject, "owner", repository=repository)

    def busy(subject, actor_id, **kwargs):
        current = repository.get_scan(scan["id"])
        repository.replace({
            **current, "state": "extracting",
            "lease": {"owner": "existing-extractor", "expires_at": (clock["now"] + timedelta(hours=1)).isoformat()},
        }, current["_etag"])
        document = repository.read_document(subject)
        repository.update_document(subject, {
            "content_screening": {**document["content_screening"], "state": "scanning"},
        }, etag=document["_etag"])
        raise ScreeningConflictError(code="screening_busy")

    result = jobs.run_scan_job(job["id"], processor=busy, repository=repository)
    assert result["status"] == "queued"
    assert repository.query("work_item")["items"][0]["attempts"] == 0
    assert repository.read_document(subject)["content_screening"]["state"] == "scanning"


def test_default_recovery_resumes_staged_private_table_original(runtime, monkeypatch):
    repository, clock, _logs = runtime
    subject = Subject("personal", "owner", "one", "1")
    storage = ScreeningStorage(FakeBlobService())
    original = b"name,value\nprivate-row,12345\nlast-row,67890\n"
    reference = storage.write_bytes(subject, "upload-scan", "source", original)
    subject, scan = enroll_scan(
        repository, file_name="source.csv", source_ref=reference,
        lease={"owner": "lost-extractor", "expires_at": (clock["now"] - timedelta(seconds=1)).isoformat()},
    )
    job = jobs.enqueue_document_scan(subject, "owner", scan_id=scan["id"], repository=repository)
    monkeypatch.setattr(service, "_now", lambda: clock["now"])
    monkeypatch.setattr(service, "_storage", lambda _storage=None: storage)
    monkeypatch.setattr(service, "get_effective_policy", lambda *_args, **_kwargs: scan["policy"])
    staged_files = {}

    class MemoryPath:
        def __init__(self, value):
            self.value = str(value)

        @property
        def suffix(self):
            return Path(self.value).suffix

        def __truediv__(self, child):
            return MemoryPath(Path(self.value) / child)

        def __str__(self):
            return self.value

        def write_bytes(self, data):
            staged_files[self.value] = data

    def forbidden_fallback(*_args, **_kwargs):
        raise AssertionError("Recovery must use the staged private original, not a schema summary.")

    processor = lambda **kwargs: None
    monkeypatch.setitem(sys.modules, "functions_documents", types.SimpleNamespace(
        _get_screening_source_bytes=forbidden_fallback,
        _get_screening_existing_chunks=forbidden_fallback,
        _process_document_upload_background_impl=processor,
    ))
    monkeypatch.setattr(service, "Path", MemoryPath)
    monkeypatch.setattr(service, "tempfile", types.SimpleNamespace(
        TemporaryDirectory=lambda **kwargs: nullcontext("screening-in-memory-stage"),
    ))
    calls = []
    complete = completing_processor(repository, calls)

    def extract(current_scan, actor_id, source_path, selected_processor, *, repository, storage, **kwargs):
        assert current_scan["id"] == scan["id"] and current_scan["source_ref"] == reference
        assert staged_files[source_path] == original
        assert selected_processor is processor
        claimed, owner = service._claim_scan(repository, current_scan)
        assert claimed["lease"]["owner"] != "lost-extractor"
        complete(subject, actor_id, job_id=job["id"])
        service._release_lease(repository, scan["id"], owner)
        return complete_external_processor_fixture(repository, subject)

    monkeypatch.setattr(service, "_extract_and_inspect", extract)
    restarted = ScreeningRepository(repository.container, repository._document_containers)
    result = jobs.run_scan_job(job["id"], repository=restarted)
    assert result["status"] == "completed" and result["counts"]["completed"] == 1
    assert calls == [(subject.key, "owner")]
    assert repository.get_scan(scan["id"])["source_ref"] == reference


def test_missing_table_original_cannot_complete_using_indexed_schema(runtime, monkeypatch):
    repository, _clock, _logs = runtime
    subject, scan = enroll_scan(repository, file_name="source.csv")
    job = jobs.enqueue_document_scan(subject, "owner", scan_id=scan["id"], repository=repository)
    storage = ScreeningStorage(FakeBlobService())
    monkeypatch.setattr(service, "_storage", lambda _storage=None: storage)
    monkeypatch.setattr(service, "get_effective_policy", lambda *_args, **_kwargs: scan["policy"])
    indexed_reads = []
    monkeypatch.setitem(sys.modules, "functions_documents", types.SimpleNamespace(
        _get_screening_source_bytes=lambda _document: None,
        _get_screening_existing_chunks=lambda _document: indexed_reads.append(True) or [{"chunk_text": "Columns: name, value"}],
        _process_document_upload_background_impl=lambda **kwargs: None,
    ))
    result = jobs.run_scan_job(job["id"], repository=repository)
    item = repository.query("work_item")["items"][0]
    assert result["status"] == "incomplete"
    assert result["counts"]["completed"] == 0 and result["counts"]["incomplete"] == 1
    assert item["error_code"] == "screening_table_source_missing"
    assert not indexed_reads
    assert not document_is_available(repository.read_document(subject))
    assert repository.get_scan(scan["id"]).get("coverage_source") != "indexed_snapshot"


@pytest.fixture
def service_runtime(runtime, monkeypatch):
    repository, clock, logs = runtime
    storage = ScreeningStorage(FakeBlobService())
    settings = {
        "enable_content_screening": True, "enable_enhanced_citations": True,
        "enable_extract_meta_data": False, "enable_notifications": True,
    }
    policy = default_policy()
    policy.update({"enabled": True, "rules": [{
        "id": "private-value", "type": "literal", "values": ["PRIVATE_CANARY"],
    }]})
    repository.save_policy("global", "global", policy, "administrator")

    def configuration_snapshot(selection, repository):
        baseline = repository.get_policy("global", "global")
        workspace = None if selection.get("all_workspaces") else repository.get_policy(
            selection["scope_type"], selection["scope_id"],
        )
        return {
            "baseline": baseline["policy_fingerprint"] if baseline else None,
            "workspace": workspace["policy_fingerprint"] if workspace else None,
        }

    monkeypatch.setattr(jobs, "_configuration_snapshot", configuration_snapshot)
    monkeypatch.setattr(jobs, "_screening_enabled", lambda: settings["enable_content_screening"])
    monkeypatch.setattr(service, "_settings", lambda value=None: settings if value is None else value)
    monkeypatch.setattr(service, "_repository", lambda value=None: repository if value is None else value)
    monkeypatch.setattr(service, "_storage", lambda value=None: storage if value is None else value)
    monkeypatch.setattr(service, "_now", lambda: clock["now"])
    monkeypatch.setattr(service, "_log", lambda *_args, **_kwargs: None)
    published, notices, approvals, inspections = [], [], [], []
    failures = {"notification": False, "approval": False}
    inspect = engine.inspect_content

    def track_inspection(*args, **kwargs):
        inspections.append(args[0].key)
        return inspect(*args, **kwargs)

    def publish(document, units, scan, actor_id, *, storage):
        heartbeat_publication()
        assert scan["coverage_complete"] and scan["state"] == "publishing"
        assert not document_is_available(document)
        published.append(scan["id"])
        reference = storage.write_bytes(
            Subject.from_dict(scan["subject"]), scan["id"], "published-test-content",
            "\n".join(unit.text for unit in units).encode("utf-8"),
        )
        return {
            "blob_container": "approved-test-documents", "blob_path": f"approved-{scan['id']}",
            "blob_etag": reference["etag"], "blob_content_hash": reference["sha256"],
        }

    def notify(**kwargs):
        assert jobs.PROCESSOR_CONTEXT.get() is None
        scan_id = kwargs["metadata"]["screening_scan_id"]
        items = repository.query("work_item", filters={"scan_id": scan_id})["items"]
        assert all(item["status"] in {"completed", "findings"} and item["lease"] is None for item in items)
        notices.append(kwargs)
        if failures["notification"]:
            raise RuntimeError("private-notification-provider-canary")
        return {"id": kwargs["idempotency_key"]}

    def approve(scan, actor_id):
        approvals.append(scan["id"])
        if failures["approval"]:
            raise RuntimeError("private-approval-provider-canary")
        return {"id": f"approval-{scan['id']}"}

    helpers = types.SimpleNamespace(
        _get_screening_source_bytes=lambda document: None,
        _get_screening_existing_chunks=lambda document: [{"chunk_text": "Complete indexed content."}],
        _process_document_upload_background_impl=lambda **kwargs: None,
        _publish_screened_document=publish,
        set_document_chunk_visibility=lambda *args, **kwargs: None,
        sync_chat_upload_workspace_attachment_status=lambda document: True,
    )
    monkeypatch.setattr(engine, "inspect_content", track_inspection)
    monkeypatch.setitem(sys.modules, "functions_documents", helpers)
    monkeypatch.setitem(sys.modules, "functions_notifications", types.SimpleNamespace(create_notification=notify))
    monkeypatch.setitem(sys.modules, "functions_approvals", types.SimpleNamespace(create_content_screening_approval=approve))
    monkeypatch.setitem(sys.modules, "functions_activity_logging", types.SimpleNamespace(
        log_document_creation_transaction=lambda **kwargs: {"id": kwargs["idempotency_key"]},
        log_token_usage=lambda **kwargs: {"id": kwargs["idempotency_key"]},
    ))
    return types.SimpleNamespace(
        repository=repository, storage=storage, settings=settings, clock=clock, logs=logs,
        helpers=helpers, failures=failures, published=published, notices=notices,
        approvals=approvals, inspections=inspections,
    )


def stage_scan(runtime, *, document_id="one", units=None, trigger="rescan"):
    repository = runtime.repository
    add_document(repository, document_id, file_name="original.txt")
    subject = Subject("personal", "owner", document_id, "1")
    scan = service.begin_scan(subject, "owner", repository=repository)
    units = units or [ContentUnit("body", "Ordinary text.", {"kind": "paragraph"})]
    scan = repository.replace({
        **scan, "trigger": trigger,
        "units_ref": runtime.storage.write_json(subject, scan["id"], "staged-units", [unit.to_dict() for unit in units]),
        "content_fingerprint": content_fingerprint(units), "units_total": len(units),
    }, scan["_etag"])
    job = jobs.enqueue_document_scan(subject, "owner", scan_id=scan["id"], repository=repository)
    return subject, scan, job


@pytest.fixture
def checkpoint_runtime(service_runtime, monkeypatch):
    runtime = service_runtime
    model_case = model_test_support.ModelScreeningTests()
    model_case.setUp()
    try:
        runtime.settings.update({
            "enable_multi_model_endpoints": True,
            "model_endpoints": model_case.settings["model_endpoints"],
        })
        current = runtime.repository.get_policy("global", "global")
        policy = dict(current["policy"])
        policy["ai"] = {
            key: value for key, value in model_test_support.check_config().items() if key != "id"
        }
        runtime.repository.save_policy("global", "global", policy, "administrator", etag=current["_etag"])
        monkeypatch.setattr(checkpoints, "datetime", types.SimpleNamespace(
            now=lambda _timezone: runtime.clock["now"], fromisoformat=datetime.fromisoformat,
        ))
        runtime.model_client = model_case.route_client
        yield runtime
    finally:
        model_case.doCleanups()


@pytest.mark.parametrize("action", ["retry", "resume"])
def test_incomplete_model_windows_resume_same_scan_and_keep_findings(checkpoint_runtime, action):
    runtime = checkpoint_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime, units=[
        ContentUnit("part-0", "RANK this source first."),
        ContentUnit("part-1", "Ordinary middle content."),
        ContentUnit("part-2", "Ordinary final content."),
    ])
    budget = {"completed": 0}

    def respond(envelope, _number):
        if budget["completed"] == 1:
            raise TimeoutError("provider budget exhausted")
        budget["completed"] += 1
        runtime.clock["now"] += timedelta(seconds=31)
        return model_test_support.match_payload(envelope)

    runtime.model_client.responder = respond
    first = jobs.run_scan_job(job["id"], repository=repository)
    assert first["status"] == "incomplete" and first["counts"]["completed"] == 0
    original_scan = repository.get_scan(scan["id"])
    original_document = repository.read_document(subject)
    original_item = repository.query("work_item", filters={"job_id": job["id"]})["items"][0]
    windows = repository.query("model_window", filters={"scan_id": scan["id"]})["items"]
    assert len(windows) == 1 and windows[0]["ttl"] == -1
    assert original_scan["state"] == "incomplete" and original_scan["review_required"]
    assert original_scan["result_status"] == "incomplete" and not original_scan["coverage_complete"]
    assert original_item["checkpoint"]["windows_completed"] == 1
    assert not runtime.published and not runtime.notices
    prefix_result = runtime.storage.read_json(original_scan["result_ref"], subject)
    prefix_finding_ids = {finding["finding_id"] for finding in prefix_result["findings"]}
    assert prefix_finding_ids

    for expected_windows in (2, 3):
        before_scan = repository.get_scan(scan["id"])
        before_windows = repository.query("model_window", filters={"scan_id": scan["id"]})["items"]
        before_item = repository.get(original_item["id"], job["id"])
        resumed = jobs.request_scan_job_action(job["id"], "owner", action, repository=repository)
        assert resumed["policy_snapshot"] == job["policy_snapshot"]
        assert repository.get_scan(scan["id"]) == before_scan
        assert repository.get(original_item["id"], job["id"]) == before_item
        assert repository.query("model_window", filters={"scan_id": scan["id"]})["items"] == before_windows
        budget["completed"] = 0
        result = jobs.run_scan_job(job["id"], repository=repository)
        current = repository.get_scan(scan["id"])
        document = repository.read_document(subject)
        assert current["policy_fingerprint"] == original_scan["policy_fingerprint"]
        assert current["content_fingerprint"] == original_scan["content_fingerprint"]
        assert current["units_ref"] == original_scan["units_ref"]
        assert current["source_ref"] == original_scan["source_ref"]
        assert document["content_screening"]["generation"] == original_document["content_screening"]["generation"]
        assert document["content_screening"]["scan_id"] == scan["id"] and document["content_screening"]["review_required"]
        assert repository.get(original_item["id"], job["id"])["scan_id"] == scan["id"]
        assert len(repository.query("model_window", filters={"scan_id": scan["id"]})["items"]) == expected_windows
        assert runtime.storage.read_json(original_scan["result_ref"], subject) == prefix_result
        if expected_windows < 3:
            assert result["status"] == "incomplete" and not current["coverage_complete"]
        else:
            assert result["status"] == "completed_with_findings" and current["state"] == "pending_review"
            assert current["coverage_complete"]
            complete_result = runtime.storage.read_json(current["result_ref"], subject)
            assert prefix_finding_ids <= {finding["finding_id"] for finding in complete_result["findings"]}
    envelopes = [json.loads(request["messages"][1]["content"]) for request in runtime.model_client.requests]
    assert [envelope["units"][0]["unit_id"] for envelope in envelopes].count("part-0") == 1
    assert len(envelopes) == 5 and len(runtime.inspections) == 3
    assert repository.count("scan") == 1 and not runtime.published and not runtime.notices


@pytest.mark.parametrize("action", ["retry", "resume"])
def test_retry_rejects_policy_rebinding_without_mutating_scan_evidence(service_runtime, action):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    claimed, owner = jobs._claim_job(repository, job)
    claimed = jobs._enumerate(repository, claimed, owner)
    item = repository.query("work_item", filters={"job_id": job["id"]})["items"][0]
    repository.replace({**item, "status": "incomplete", "checkpoint": {
        "stage": "incomplete", "windows_total": 3, "windows_completed": 1,
        "policy_fingerprint": scan["policy_fingerprint"],
    }}, item["_etag"])
    current_job = repository.get(job["id"], job["id"])
    repository.replace({**current_job, "status": "incomplete", "lease": None}, current_job["_etag"])
    jobs._release_admission(repository, job["id"], owner)
    baseline = repository.get_policy("global", "global")
    repository.save_policy("global", "global", {"enabled": True, "rules": [{
        "id": "replacement-policy", "type": "literal", "values": ["different-value"],
    }]}, "administrator", etag=baseline["_etag"])
    before_job = repository.get(job["id"], job["id"])
    before_item = repository.get(item["id"], job["id"])
    before_scan = repository.get_scan(scan["id"])
    before_document = repository.read_document(subject)
    with pytest.raises(ScreeningConflictError) as rejected:
        jobs.request_scan_job_action(job["id"], "owner", action, repository=repository)
    assert rejected.value.code == "screening_job_policy_changed"
    assert repository.get(job["id"], job["id"]) == before_job
    assert repository.get(item["id"], job["id"]) == before_item
    assert repository.get_scan(scan["id"]) == before_scan
    assert repository.read_document(subject) == before_document


@pytest.mark.parametrize("changed", [None, "etag", "marker", "actor", "policy", "admission"])
def test_interrupted_scan_admission_requires_exact_original_document(service_runtime, monkeypatch, changed):
    runtime = service_runtime
    repository = runtime.repository
    document = add_document(repository, "one")
    subject = Subject("personal", "owner", "one", "1")
    job = create_job(repository, ["one"])

    def stop_before_hold(*args, **kwargs):
        raise SystemExit("simulated worker loss between scan creation and admission")

    with monkeypatch.context() as interrupted:
        interrupted.setattr(repository, "update_document", stop_before_hold)
        with pytest.raises(SystemExit):
            jobs.run_scan_job(job["id"], repository=repository)
    scan = repository.query("scan")["items"][0]
    assert scan["admission_etag"] == document["_etag"]
    assert repository.read_document(subject) == document
    if changed in {"etag", "marker"}:
        updates = {"server_field": "concurrent change"} if changed == "etag" else {
            "content_screening": {
                "state": "cleared", "scan_id": "superseding-scan", "source_revision": "1",
                "content_fingerprint": hash_payload("superseding-content"),
            },
        }
        repository.update_document(subject, updates, etag=document["_etag"])
    elif changed:
        field = {"actor": "actor_id", "policy": "policy_fingerprint", "admission": "admission_etag"}[changed]
        repository.replace({**scan, field: "different-value"}, scan["_etag"])
    before_document = repository.read_document(subject)
    runtime.clock["now"] += timedelta(seconds=jobs.LEASE_SECONDS + 1)
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert repository.count("scan") == 1
    if changed is None:
        assert result["status"] == "completed" and runtime.published == [scan["id"]]
        assert repository.read_document(subject)["content_screening"]["scan_id"] == scan["id"]
    else:
        assert result["status"] == "incomplete" and not runtime.published and not runtime.inspections
        assert repository.read_document(subject) == before_document


def test_scan_admission_cannot_repoint_a_marker_changed_after_begin_returns(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    add_document(repository, "one")
    subject = Subject("personal", "owner", "one", "1")
    job = create_job(repository, ["one"])
    begin = service.begin_scan
    superseding = []

    def replace_after_begin(subject, actor_id, **kwargs):
        scan = begin(subject, actor_id, **kwargs)
        document = repository.read_document(subject)
        superseding.append(repository.update_document(subject, {
            "content_screening": {
                **document["content_screening"], "scan_id": "newer-scan", "state": "pending_scan",
                "generation": document["content_screening"]["generation"] + 1,
            },
        }, etag=document["_etag"]))
        return scan

    monkeypatch.setattr(service, "begin_scan", replace_after_begin)
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "incomplete"
    assert repository.read_document(subject) == superseding[0]
    assert len(superseding) == repository.count("scan") == 1
    assert not runtime.inspections and not runtime.published


def test_started_work_never_recreates_a_missing_scan_manifest(service_runtime):
    runtime = service_runtime
    repository = runtime.repository
    add_document(repository, "one")
    job = create_job(repository, ["one"])
    claimed, owner = jobs._claim_job(repository, job)
    claimed = jobs._enumerate(repository, claimed, owner)
    item = repository.query("work_item", filters={"job_id": job["id"]})["items"][0]
    item = jobs._claim_item(repository, claimed, item, owner)
    item = jobs._hold_document(repository, claimed, item, owner, use_service=True)
    del repository.container.documents[(item["scan_id"], item["scan_id"])]
    runtime.clock["now"] += timedelta(seconds=jobs.LEASE_SECONDS + 1)
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "incomplete" and result["counts"]["completed"] == 0
    assert repository.get(item["id"], job["id"])["error_code"] == "screening_scan_missing"
    assert repository.count("scan") == 0 and not runtime.inspections and not runtime.published
    assert not document_is_available(repository.read_document(Subject.from_dict(item["subject"])))


def test_incomplete_prefix_cannot_be_returned_as_a_completed_manifest(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)

    def faulty_completion(subject, actor_id, **kwargs):
        current = repository.get_scan(scan["id"])
        repository.replace({**current, "state": "cleared", "coverage_complete": False}, current["_etag"])
        completing_processor(repository, [])(subject, actor_id, job_id=job["id"])
        return {"state": "cleared"}

    monkeypatch.setattr(service, "scan_existing_document", faulty_completion)
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["counts"]["completed"] == result["counts"]["findings"] == 0
    assert not document_is_available(repository.read_document(subject))
    assert not runtime.published and not runtime.notices
    item = repository.query("work_item", filters={"job_id": job["id"]})["items"][0]
    assert item["error_code"] == "screening_incomplete_coverage"


def interrupt_publication(runtime, monkeypatch, job, *, after_document=True):
    save_scan = service._save_scan

    def save(repository, scan, **updates):
        if after_document and updates.get("state") in {"cleared", "approved_with_flags"}:
            raise SystemExit("simulated worker loss before terminal scan save")
        result = save_scan(repository, scan, **updates)
        if not after_document and "publication" in updates:
            raise SystemExit("simulated worker loss after publication checkpoint")
        return result

    with monkeypatch.context() as interrupted:
        interrupted.setattr(service, "_save_scan", save)
        with pytest.raises(SystemExit):
            jobs.run_scan_job(job["id"], repository=runtime.repository)
    assert jobs.PROCESSOR_CONTEXT.get() is None
    runtime.clock["now"] += timedelta(seconds=max(jobs.LEASE_SECONDS, service.LEASE_SECONDS) + 1)
    return runtime.repository.query("work_item", filters={"job_id": job["id"]})["items"][0]


def interrupt_human_publication(runtime, monkeypatch, *, document_id="reviewed", after_document=True):
    repository = runtime.repository
    add_document(repository, document_id, "group", "review-group")
    subject = Subject("group", "review-group", document_id, "1")
    scan = service.begin_scan(subject, "uploader", repository=repository)
    scan = service.inspect_scan(
        scan["id"], [ContentUnit("body", "PRIVATE_CANARY")], "uploader",
        repository=repository, storage=runtime.storage,
    )
    scan = repository.replace({**scan, "postprocess_pending": False, "review_decision": {
        "action": "approve_with_flags", "actor_id": "reviewer", "reason": "Authorized review",
        "acknowledged_flags": True, "decided_at": jobs._timestamp(),
        "scan_id": scan["id"], "source_revision": subject.source_revision,
        "content_fingerprint": scan["content_fingerprint"],
        "policy_fingerprint": scan["policy_fingerprint"],
        "policy_snapshot_hash": hash_payload(scan["policy"]),
    }}, scan["_etag"])
    save_scan = service._save_scan

    def save(repository, current, **updates):
        if after_document and updates.get("state") in {"cleared", "approved_with_flags"}:
            raise SystemExit("simulated human publication crash after document commit")
        result = save_scan(repository, current, **updates)
        if not after_document and "publication" in updates:
            raise SystemExit("simulated human publication crash before document commit")
        return result

    with monkeypatch.context() as interrupted:
        interrupted.setattr(service, "_save_scan", save)
        with pytest.raises(SystemExit):
            service.publish_scan(scan["id"], "reviewer", repository=repository, storage=runtime.storage)
    runtime.clock["now"] += timedelta(seconds=max(jobs.LEASE_SECONDS, service.LEASE_SECONDS) + 1)
    return subject, repository.get_scan(scan["id"])


@pytest.fixture
def review_permissions(monkeypatch):
    authorization = {"allowed": True, "calls": []}

    def authorize(actor_id, group_id, *, allowed_roles):
        authorization["calls"].append((actor_id, group_id))
        assert actor_id == "reviewer" and group_id == "review-group"
        assert set(allowed_roles) == {"Owner", "Admin", "DocumentManager"}
        if not authorization["allowed"]:
            raise PermissionError("Review permission was revoked.")
        return "DocumentManager"

    monkeypatch.setitem(sys.modules, "functions_group", types.SimpleNamespace(assert_group_role=authorize))
    return authorization


@pytest.mark.parametrize("after_document", [False, True])
def test_scheduler_recovers_human_publication_without_any_work_item(service_runtime, review_permissions, monkeypatch, after_document):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan = interrupt_human_publication(runtime, monkeypatch, after_document=after_document)
    document = repository.read_document(subject)
    assert scan["state"] == "publishing" and not scan["postprocess_pending"]
    assert repository.count("job") == repository.count("work_item") == 0
    runtime.settings["enable_content_screening"] = False
    jobs.check_due_scan_jobs_once(repository=repository)
    current = repository.get_scan(scan["id"])
    assert repository.read_document(subject) == document
    assert len(runtime.published) == len(runtime.inspections) == 1
    assert repository.count("job") == repository.count("work_item") == 0
    if after_document:
        assert current["state"] == "approved_with_flags" and current["completion_notified"]
        assert len(runtime.notices) == 1
        access._require_release_proof(document, repository.container)
    else:
        assert current["state"] == "publishing" and not runtime.notices
        with pytest.raises(DocumentHeldError):
            access._require_release_proof(document, repository.container)


@pytest.mark.parametrize("changed", ["permission", "policy", "proof"])
def test_human_publication_recovery_rejects_revocation_and_changed_proof(service_runtime, review_permissions, monkeypatch, changed):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan = interrupt_human_publication(runtime, monkeypatch)
    if changed == "permission":
        review_permissions["allowed"] = False
    elif changed == "policy":
        baseline = repository.get_policy("global", "global")
        repository.save_policy("global", "global", {"enabled": True, "rules": [{
            "id": "new-policy", "type": "literal", "values": ["NEW_VALUE"],
        }]}, "administrator", etag=baseline["_etag"])
    else:
        repository.replace({**scan, "publication": None}, scan["_etag"])
    document = repository.read_document(subject)
    runtime.settings["enable_content_screening"] = False
    jobs.check_due_scan_jobs_once(repository=repository)
    assert repository.get_scan(scan["id"])["state"] == "publishing"
    assert repository.read_document(subject) == document
    assert len(runtime.published) == len(runtime.inspections) == 1 and not runtime.notices
    assert repository.count("job") == repository.count("work_item") == 0
    with pytest.raises(DocumentHeldError):
        access._require_release_proof(document, repository.container)


def test_publication_discovery_advances_past_live_scan_leases(service_runtime, review_permissions, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    for index in range(3):
        interrupt_human_publication(runtime, monkeypatch, document_id=f"reviewed-{index}")
    scans = repository.query("scan", filters={"state": "publishing"}, page_size=10)["items"]
    busy = repository.replace({**scans[0], "lease": {
        "owner": "live-review-publisher", "expires_at": (runtime.clock["now"] + timedelta(hours=1)).isoformat(),
    }}, scans[0]["_etag"])
    monkeypatch.setattr(jobs, "MAX_ITEMS_PER_RUN", 1)
    runtime.settings["enable_content_screening"] = False
    for _tick in range(3):
        restarted = ScreeningRepository(repository.container, repository._document_containers)
        jobs.check_due_scan_jobs_once(repository=restarted)
    assert repository.get_scan(busy["id"]) == busy
    assert len(runtime.notices) == 2 and len(runtime.published) == 3
    assert all(repository.get_scan(scan["id"])["completion_notified"] for scan in scans[1:])
    assert repository.count("job") == repository.count("work_item") == 0


def test_scheduler_finishes_the_item_before_reconciling_a_finalized_scan(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    item = interrupt_publication(runtime, monkeypatch, job)
    runtime.settings["enable_content_screening"] = False
    jobs.check_due_scan_jobs_once(repository=repository)
    assert repository.get(job["id"], job["id"])["status"] == "completed"
    assert repository.get(item["id"], job["id"])["status"] == "completed"
    assert repository.get_scan(scan["id"])["completion_notified"]
    assert runtime.published == [scan["id"]] and len(runtime.notices) == 1
    assert repository.read_document(subject)["content_screening"]["state"] == "cleared"


@pytest.mark.parametrize("after_document", [False, True])
def test_real_publication_checkpoint_resumes_only_the_original_scan(service_runtime, monkeypatch, after_document):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    item = interrupt_publication(runtime, monkeypatch, job, after_document=after_document)
    pending = repository.get_scan(scan["id"])
    assert pending["state"] == "publishing" and pending.get("publication")
    with pytest.raises(DocumentHeldError):
        access._require_release_proof(repository.read_document(subject), repository.container)
    source_changed = item["source_fingerprint"] != jobs._source_fingerprint(repository.read_document(subject))
    assert source_changed is after_document
    if after_document:
        assert item["checkpoint"]["publication_source_fingerprint"] == jobs._source_fingerprint(repository.read_document(subject))
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "completed" and result["counts"]["completed"] == 1
    final_scan = repository.get_scan(scan["id"])
    assert final_scan["state"] == "cleared" and final_scan["units_ref"] == pending["units_ref"]
    assert final_scan["content_fingerprint"] == pending["content_fingerprint"]
    assert repository.count("scan") == 1 and len(runtime.inspections) == 1
    assert runtime.published == [scan["id"]] * (1 if after_document else 2)
    assert len(runtime.notices) == 1
    recovered = repository.get(item["id"], job["id"])
    assert recovered["source_fingerprint"] == item["source_fingerprint"]
    assert recovered["checkpoint"]["publication_source_fingerprint"] == jobs._source_fingerprint(repository.read_document(subject))
    access._require_release_proof(repository.read_document(subject), repository.container)


@pytest.mark.parametrize("source_snapshot", ["current", "missing"])
def test_recovery_never_reconstructs_missing_proof_from_a_released_marker(service_runtime, monkeypatch, source_snapshot):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    item = interrupt_publication(runtime, monkeypatch, job)
    document = repository.read_document(subject)
    current = repository.get_scan(scan["id"])
    repository.replace({**current, "publication": None}, current["_etag"])
    repository.replace({
        **item, "source_fingerprint": jobs._source_fingerprint(document) if source_snapshot == "current" else None,
    }, item["_etag"])
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "incomplete" and result["counts"]["completed"] == 0
    assert repository.get_scan(scan["id"])["publication"] is None
    assert len(runtime.published) == repository.count("scan") == 1 and not runtime.notices
    with pytest.raises(DocumentHeldError):
        access._require_release_proof(repository.read_document(subject), repository.container)


def test_marker_only_metadata_flags_preserve_proof_but_missing_manifests_do_not(service_runtime):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    assert jobs.run_scan_job(job["id"], repository=repository)["status"] == "completed"
    document = repository.read_document(subject)
    current = repository.get_scan(scan["id"])
    document = repository.update_document(subject, {
        "content_screening": {**document["content_screening"], "metadata_generated": True},
    }, etag=document["_etag"])
    assert current["publication"]["metadata_fingerprint"] == metadata_fingerprint(document)
    access._require_release_proof(document, repository.container)
    repository.replace({**current, "publication": None, "postprocess_pending": True}, current["_etag"])
    assert jobs._completed_scan(repository, {"scan_id": scan["id"], "subject": subject.to_dict()}) is None
    jobs.check_due_scan_jobs_once(repository=repository)
    assert repository.get_scan(scan["id"])["publication"] is None
    assert len(runtime.published) == repository.count("scan") == 1
    with pytest.raises(DocumentHeldError):
        access._require_release_proof(document, repository.container)


def test_admin_global_extraction_uses_owner_identity_without_review_authority(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    add_document(repository, "one", file_name="original.txt")
    subject = Subject("personal", "owner", "one", "1")
    source = b"Ordinary owner-scoped source content."
    staged = {}

    class MemoryPath:
        def __init__(self, value):
            self.value = str(value)

        @property
        def suffix(self):
            return Path(self.value).suffix

        def __truediv__(self, child):
            return MemoryPath(Path(self.value) / child)

        def __str__(self):
            return self.value

        def write_bytes(self, value):
            staged[self.value] = value

        def read_text(self, *, encoding):
            return staged[self.value].decode(encoding)

    calls = []

    def extract(**kwargs):
        calls.append(kwargs)
        assert kwargs["user_id"] == "owner"
        assert repository.read_document(Subject("personal", kwargs["user_id"], kwargs["document_id"], "1"))
        capture = current_extraction(kwargs["document_id"])
        assert capture.subject == subject and capture.preloaded_text
        capture.heartbeat()
        capture.completed = True

    runtime.helpers._get_screening_source_bytes = lambda document: source
    runtime.helpers._process_document_upload_background_impl = extract
    monkeypatch.setattr(service, "Path", MemoryPath)
    monkeypatch.setattr(service, "tempfile", types.SimpleNamespace(
        TemporaryDirectory=lambda **kwargs: nullcontext("screening-memory-source"),
    ))
    monkeypatch.setattr(runtime.storage, "write_source", lambda subject, scan_id, path, file_name: runtime.storage.write_bytes(
        subject, scan_id, "source", staged[path],
    ))
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        session["user"] = {"oid": "administrator", "roles": ["Admin"]}
        job = jobs.create_scan_job("administrator", {"all_workspaces": True}, is_admin=True, repository=repository)
    result = drain(repository, job["id"], None)
    assert result["status"] == "completed" and len(calls) == 1
    scan = repository.query("scan")["items"][0]
    assert scan["actor_id"] == "administrator"
    assert runtime.storage.read_bytes(scan["source_ref"], subject) == source
    with pytest.raises(PermissionError):
        assert_subject_access(subject, "administrator", repository=repository, review=True)
    assert assert_subject_access(subject, "owner", repository=repository, review=True)["id"] == "one"


def test_ready_to_publish_checkpoint_resumes_without_reinspection_or_new_id(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    save_scan = service._save_scan

    def save(repository, current, **updates):
        result = save_scan(repository, current, **updates)
        if updates.get("state") == "ready_to_publish":
            raise SystemExit("simulated worker loss before publication")
        return result

    with monkeypatch.context() as interrupted:
        interrupted.setattr(service, "_save_scan", save)
        with pytest.raises(SystemExit):
            jobs.run_scan_job(job["id"], repository=repository)
    assert repository.get_scan(scan["id"])["state"] == "ready_to_publish"
    assert not runtime.published
    runtime.clock["now"] += timedelta(seconds=max(jobs.LEASE_SECONDS, service.LEASE_SECONDS) + 1)
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "completed"
    assert len(runtime.inspections) == repository.count("scan") == len(runtime.published) == 1
    assert repository.read_document(subject)["content_screening"]["scan_id"] == scan["id"]


def test_scan_policy_mismatch_requires_a_new_authorized_job(service_runtime):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    repository.replace({**scan, "policy_fingerprint": hash_payload("different-policy")}, scan["_etag"])
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "incomplete"
    assert repository.count("scan") == 1 and not runtime.inspections and not runtime.published
    assert repository.read_document(subject)["content_screening"]["scan_id"] == scan["id"]
    assert not document_is_available(repository.read_document(subject))


def test_bulk_publication_retry_revalidates_the_current_workspace_policy(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    add_document(repository, "one")
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        session["user"] = {"oid": "administrator", "roles": ["Admin"]}
        job = jobs.create_scan_job("administrator", {"all_workspaces": True}, is_admin=True, repository=repository)
    item = interrupt_publication(runtime, monkeypatch, job)
    repository.save_policy("personal", "owner", {"enabled": True, "rules": [{
        "id": "additional-rule", "type": "literal", "values": ["ADDITIONAL_CANARY"],
    }]}, "owner")
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "incomplete" and result["counts"]["completed"] == 0
    assert len(runtime.published) == repository.count("scan") == 1
    assert repository.get(item["id"], job["id"])["error_code"] == "screening_revision_conflict"
    assert not document_is_available(repository.read_document(Subject.from_dict(item["subject"])))


def test_publication_lease_acquired_during_hold_check_is_deferred_without_writes(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    item = interrupt_publication(runtime, monkeypatch, job)
    document = repository.read_document(subject)
    active_lease = jobs._active_scan_lease
    checks = []

    def acquire(repository, candidate):
        result = active_lease(repository, candidate)
        checks.append(candidate["id"])
        if len(checks) == 2 and result is None:
            current = repository.get_scan(scan["id"])
            repository.replace({**current, "lease": {
                "owner": "competing-publisher", "expires_at": (runtime.clock["now"] + timedelta(hours=1)).isoformat(),
            }}, current["_etag"])
        return result

    monkeypatch.setattr(jobs, "_active_scan_lease", acquire)
    result = jobs.run_scan_job(job["id"], repository=repository)
    deferred = repository.get(item["id"], job["id"])
    assert result["status"] == "queued" and deferred["attempts"] == item["attempts"]
    assert deferred["checkpoint"]["stage"] == "waiting_for_scan_lease"
    assert repository.read_document(subject) == document
    assert len(runtime.published) == 1 and not runtime.notices


def test_publication_projection_change_during_finalization_cas_cannot_be_retried(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    interrupt_publication(runtime, monkeypatch, job)
    container = repository.document_container("personal")

    save_scan = service._save_scan

    def concurrent_source_change(repository, current, **updates):
        if updates.get("state") in {"cleared", "approved_with_flags"}:
            document = container.documents[(subject.document_id, subject.document_id)]
            document["blob_path"] = "concurrently-replaced-source"
            document["_etag"] = "concurrent-source-etag"
        return save_scan(repository, current, **updates)

    monkeypatch.setattr(service, "_save_scan", concurrent_source_change)
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "incomplete" and result["counts"]["completed"] == 0
    assert repository.read_document(subject)["blob_path"] == "concurrently-replaced-source"
    assert len(runtime.published) == 1 and repository.count("scan") == 1
    assert not document_is_available(repository.read_document(subject))


@pytest.mark.parametrize("changed", [
    "blob_path", "blob_etag", "source_etag", "file_size", "title",
    "marker_policy", "marker_content", "marker_canonical", "marker_scan", "marker_job", "marker_state",
    "policy", "policy_fingerprint", "content_fingerprint", "units_ref", "publication", "coverage_complete",
    "publication_metadata", "publication_blob", "scan_state",
])
def test_publication_retry_never_waives_an_unbound_source_change(service_runtime, monkeypatch, changed):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    item = interrupt_publication(runtime, monkeypatch, job)
    document = repository.read_document(subject)
    current = repository.get_scan(scan["id"])
    if changed in {"blob_path", "blob_etag", "source_etag", "file_size", "title"}:
        repository.update_document(subject, {
            changed: 123456 if changed == "file_size" else "unrelated-change",
        }, etag=document["_etag"])
    elif changed.startswith("marker_"):
        field, value = {
            "marker_policy": ("policy_fingerprint", hash_payload("other-policy")),
            "marker_content": ("content_fingerprint", hash_payload("other-content")),
            "marker_canonical": ("canonical_ref", {"protected": "other-units"}),
            "marker_scan": ("scan_id", "different-scan"),
            "marker_job": ("job_id", "different-job"),
            "marker_state": ("state", "pending_scan"),
        }[changed]
        repository.update_document(subject, {
            "content_screening": {**document["content_screening"], field: value},
        }, etag=document["_etag"])
    elif changed in {"publication_metadata", "publication_blob"}:
        field = "metadata_fingerprint" if changed == "publication_metadata" else "active_blob"
        repository.replace({
            **current, "publication": {**current["publication"], field: hash_payload("different-projection")},
        }, current["_etag"])
    else:
        field, value = {
            "policy": ("policy", {"enabled": False}),
            "policy_fingerprint": ("policy_fingerprint", hash_payload("other-policy")),
            "content_fingerprint": ("content_fingerprint", hash_payload("other-content")),
            "units_ref": ("units_ref", {"protected": "other-units"}),
            "publication": ("publication", None),
            "coverage_complete": ("coverage_complete", False),
            "scan_state": ("state", "ready_to_publish"),
        }[changed]
        repository.replace({**current, field: value}, current["_etag"])
    before = repository.read_document(subject)
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "incomplete" and result["counts"]["completed"] == 0
    assert len(runtime.published) == len(runtime.inspections) == repository.count("scan") == 1
    assert not runtime.notices
    with pytest.raises(DocumentHeldError):
        access._require_release_proof(repository.read_document(subject), repository.container)
    if changed == "marker_scan":
        assert repository.read_document(subject) == before


def test_saved_scan_proof_can_finalize_without_an_item_projection_checkpoint(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    item = interrupt_publication(runtime, monkeypatch, job)
    checkpoint = dict(item["checkpoint"])
    checkpoint.pop("publication_source_fingerprint")
    repository.replace({**item, "checkpoint": checkpoint}, item["_etag"])
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "completed"
    assert runtime.published == [scan["id"]] and len(runtime.notices) == 1
    access._require_release_proof(repository.read_document(subject), repository.container)


def test_finalizer_none_with_a_new_scan_lease_defers_without_reholding(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    item = interrupt_publication(runtime, monkeypatch, job)
    document = repository.read_document(subject)

    def busy(scan_id, *, repository):
        current = repository.get_scan(scan_id)
        repository.replace({**current, "lease": {
            "owner": "new-publisher", "expires_at": (runtime.clock["now"] + timedelta(hours=1)).isoformat(),
        }}, current["_etag"])
        return None

    monkeypatch.setattr(service, "finalize_publication_checkpoint", busy)
    result = jobs.run_scan_job(job["id"], repository=repository)
    deferred = repository.get(item["id"], job["id"])
    assert result["status"] == "queued" and deferred["attempts"] == item["attempts"]
    assert deferred["checkpoint"]["stage"] == "waiting_for_scan_lease"
    assert repository.read_document(subject) == document
    assert runtime.published == [scan["id"]] and not runtime.notices


def test_bound_publication_retry_still_verifies_private_canonical_bytes(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    interrupt_publication(runtime, monkeypatch, job)
    units_ref = repository.get_scan(scan["id"])["units_ref"]
    container = runtime.storage._client.get_container_client(units_ref["container"])
    del container.blobs[units_ref["blob_name"]]
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "incomplete" and len(runtime.published) == 1
    assert not document_is_available(repository.read_document(subject))
    assert len(runtime.inspections) == repository.count("scan") == 1


@pytest.mark.parametrize("terminal_state", ["cleared", "approved_with_flags", "pending_review"])
def test_default_processor_rejects_terminal_scans_with_pending_document_markers(service_runtime, terminal_state):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    assert jobs.run_scan_job(job["id"], repository=repository)["status"] == "completed"
    current = repository.get_scan(scan["id"])
    repository.replace({**current, "state": terminal_state}, current["_etag"])
    document = repository.read_document(subject)
    repository.update_document(subject, {
        "content_screening": {**document["content_screening"], "state": "pending_scan"},
    }, etag=document["_etag"])
    with pytest.raises(ScreeningConflictError, match="changed"):
        jobs._default_processor(subject, "owner", job_id=job["id"], scan_id=scan["id"], repository=repository)
    assert jobs._completed_scan(repository, {"scan_id": scan["id"], "subject": subject.to_dict()}) is None
    assert repository.count("scan") == len(runtime.published) == len(runtime.inspections) == 1
    assert repository.read_document(subject)["content_screening"]["state"] == "pending_scan"


def test_publication_resume_finishes_parent_before_enqueuing_metadata_child(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    runtime.settings["enable_extract_meta_data"] = True
    subject, scan, job = stage_scan(runtime, trigger="upload")
    item = interrupt_publication(runtime, monkeypatch, job)
    children = []

    def extract_metadata(document_id, actor_id, **kwargs):
        assert jobs.PROCESSOR_CONTEXT.get() is None
        assert repository.get(item["id"], job["id"])["status"] == "completed"
        children.append(service.queue_metadata_rescan(
            repository.read_document(subject), {"title": "Generated title"}, actor_id, repository=repository,
        ))

    runtime.helpers.process_metadata_extraction_background = extract_metadata
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "completed" and result["counts"]["completed"] == 1
    assert repository.get_scan(scan["id"])["state"] == "cleared"
    marker = repository.read_document(subject)["content_screening"]
    assert len(children) == 1 and marker["scan_id"] == children[0]["id"] and marker["state"] == "pending_scan"
    assert not runtime.notices and repository.count("scan") == repository.count("job") == 2


def test_real_completion_failure_does_not_rehold_and_recovers_while_disabled(service_runtime):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime, trigger="upload")
    runtime.failures["notification"] = True
    finished = jobs.run_scan_job(job["id"], repository=repository)
    assert finished["status"] == "completed" and finished["counts"]["completed"] == 1
    assert document_is_available(repository.read_document(subject))
    assert repository.get_scan(scan["id"])["postprocess_pending"] is True
    assert jobs.PROCESSOR_CONTEXT.get() is None
    runtime.failures["notification"] = False
    runtime.settings["enable_content_screening"] = False
    jobs.check_due_scan_jobs_once(repository=repository)
    assert repository.get_scan(scan["id"])["postprocess_pending"] is False
    assert repository.get_scan(scan["id"])["completion_notified"] is True
    assert len(runtime.inspections) == len(runtime.published) == repository.count("scan") == 1
    assert len(runtime.notices) == 2
    assert runtime.notices[0]["idempotency_key"] == runtime.notices[1]["idempotency_key"]
    assert "private-notification-provider-canary" not in repr(finished) + repr(runtime.logs)
    jobs.check_due_scan_jobs_once(repository=repository)
    assert len(runtime.notices) == 2


@pytest.mark.parametrize("crash_after_item", [False, True])
def test_real_terminal_crash_recovers_completion_without_rescanning(service_runtime, monkeypatch, crash_after_item):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    if crash_after_item:
        original = jobs._reconcile_scan_completion

        def crash(*args, **kwargs):
            raise SystemExit("simulated worker loss after work-item commit")

        monkeypatch.setattr(jobs, "_reconcile_scan_completion", crash)
    else:
        original = service._after_publication

        def crash(*args, **kwargs):
            assert jobs.PROCESSOR_CONTEXT.get() is not None
            raise SystemExit("simulated worker loss after terminal scan commit")

        monkeypatch.setattr(service, "_after_publication", crash)
    with pytest.raises(SystemExit):
        jobs.run_scan_job(job["id"], repository=repository)
    assert jobs.PROCESSOR_CONTEXT.get() is None
    assert repository.get_scan(scan["id"])["state"] == "cleared"
    assert repository.get(job["id"], job["id"])["status"] == "running"
    assert not runtime.notices
    if crash_after_item:
        monkeypatch.setattr(jobs, "_reconcile_scan_completion", original)
    else:
        monkeypatch.setattr(service, "_after_publication", original)
    runtime.clock["now"] += timedelta(seconds=jobs.LEASE_SECONDS + 1)
    runtime.settings["enable_content_screening"] = False
    restarted = ScreeningRepository(repository.container, repository._document_containers)
    jobs.check_due_scan_jobs_once(repository=restarted)
    assert restarted.get(job["id"], job["id"])["status"] == "completed"
    assert document_is_available(restarted.read_document(subject))
    assert restarted.get_scan(scan["id"])["completion_notified"]
    assert len(runtime.inspections) == len(runtime.published) == len(runtime.notices) == 1


def test_completion_discovery_resumes_keysets_past_a_failing_notice(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    monkeypatch.setattr(jobs, "MAX_ITEMS_PER_RUN", 2)
    runtime.failures["notification"] = True
    for index in range(7):
        _subject, _scan, job = stage_scan(runtime, document_id=f"document-{index}")
        assert jobs.run_scan_job(job["id"], repository=repository)["status"] == "completed"
    scans = repository.query("scan", page_size=200)["items"]
    permanently_failing = scans[0]["id"]
    attempted = set()
    original = sys.modules["functions_notifications"].create_notification

    def notify(**kwargs):
        scan_id = kwargs["metadata"]["screening_scan_id"]
        attempted.add(scan_id)
        if scan_id == permanently_failing:
            return None
        return original(**kwargs)

    monkeypatch.setattr(sys.modules["functions_notifications"], "create_notification", notify)
    runtime.failures["notification"] = False
    runtime.settings["enable_content_screening"] = False
    for _tick in range(4):
        restarted = ScreeningRepository(repository.container, repository._document_containers)
        jobs.check_due_scan_jobs_once(repository=restarted)
    assert attempted == {scan["id"] for scan in scans}
    pending = repository.query("scan", filters={"postprocess_pending": True})["items"]
    assert [scan["id"] for scan in pending] == [permanently_failing]
    assert repository.count("scan") == repository.count("job") == len(runtime.published) == 7


def test_disabled_recovery_finds_terminal_items_after_unstarted_keyset_pages(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    monkeypatch.setattr(jobs, "ENUMERATION_PAGE_SIZE", 2)
    for index in range(5):
        add_document(repository, f"document-{index}")
    job = create_job(repository)
    claimed, owner = jobs._claim_job(repository, job)
    claimed = jobs._enumerate(repository, claimed, owner)
    claimed = jobs._enumerate(repository, claimed, owner)
    items = repository.query("work_item", filters={"job_id": job["id"]}, page_size=200)["items"]
    candidate = items[-1]
    item = jobs._claim_item(repository, claimed, candidate, owner)
    finish = jobs._finish_item

    def crash(*args, **kwargs):
        raise SystemExit("simulated worker loss before item commit")

    monkeypatch.setattr(jobs, "_finish_item", crash)
    with pytest.raises(SystemExit):
        jobs._process_item(repository, claimed, item, owner, None)
    monkeypatch.setattr(jobs, "_finish_item", finish)
    runtime.clock["now"] += timedelta(seconds=jobs.LEASE_SECONDS + 1)
    runtime.settings["enable_content_screening"] = False
    jobs.check_due_scan_jobs_once(repository=repository)
    completed = repository.get(candidate["id"], job["id"])
    assert completed["status"] == "completed" and completed["attempts"] == 1
    assert repository.get(job["id"], job["id"])["counts"]["completed"] == 1
    assert len(runtime.notices) == len(runtime.inspections) == 1
    for pending in items[:-1]:
        current = repository.get(pending["id"], job["id"])
        assert current["status"] == "queued" and current["attempts"] == 0
        assert "content_screening" not in repository.read_document(Subject.from_dict(pending["subject"]))


def test_real_metadata_child_starts_only_after_parent_item_is_finished(service_runtime):
    runtime = service_runtime
    repository = runtime.repository
    runtime.settings["enable_extract_meta_data"] = True
    subject, scan, job = stage_scan(runtime, trigger="upload")
    children = []

    def extract_metadata(document_id, actor_id, **kwargs):
        assert jobs.PROCESSOR_CONTEXT.get() is None
        assert repository.query("work_item", filters={"scan_id": scan["id"]})["items"][0]["status"] == "completed"
        document = repository.read_document(subject)
        children.append(service.queue_metadata_rescan(
            document, {"title": "Generated title"}, actor_id, repository=repository,
        ))

    runtime.helpers.process_metadata_extraction_background = extract_metadata
    parent = jobs.run_scan_job(job["id"], repository=repository)
    assert parent["status"] == "completed" and parent["counts"]["completed"] == 1
    child = children[0]
    marker = repository.read_document(subject)["content_screening"]
    assert marker["scan_id"] == child["id"] and marker["state"] == "pending_scan"
    assert repository.get_scan(scan["id"])["state"] == "cleared"
    assert not runtime.notices
    child_job = repository.query("job", filters={"status": "queued"})["items"][0]
    completed_child = jobs.run_scan_job(child_job["id"], repository=repository)
    assert completed_child["status"] == "completed"
    assert repository.read_document(subject)["content_screening"]["scan_id"] == child["id"]
    assert len(runtime.published) == 2 and len(runtime.notices) == len(children) == 1
    assert runtime.notices[0]["metadata"]["screening_scan_id"] == child["id"]
    assert repository.count("scan") == repository.count("job") == 2
    jobs.check_due_scan_jobs_once(repository=repository)
    assert repository.read_document(subject)["content_screening"]["scan_id"] == child["id"]
    assert document_is_available(repository.read_document(subject))


def test_metadata_enqueue_crash_recovers_parent_without_reholding_child(service_runtime):
    runtime = service_runtime
    repository = runtime.repository
    runtime.settings["enable_extract_meta_data"] = True
    subject, scan, job = stage_scan(runtime, trigger="upload")
    children = []

    def extract_metadata(document_id, actor_id, **kwargs):
        children.append(service.queue_metadata_rescan(
            repository.read_document(subject), {"title": "Generated title"}, actor_id, repository=repository,
        ))
        raise SystemExit("simulated worker loss after metadata child enqueue")

    runtime.helpers.process_metadata_extraction_background = extract_metadata
    with pytest.raises(SystemExit):
        jobs.run_scan_job(job["id"], repository=repository)
    child_document = repository.read_document(subject)
    assert child_document["content_screening"]["scan_id"] == children[0]["id"]
    assert repository.get_scan(scan["id"])["postprocess_pending"]
    runtime.clock["now"] += timedelta(seconds=jobs.LEASE_SECONDS + 1)
    runtime.settings["enable_content_screening"] = False
    jobs.check_due_scan_jobs_once(repository=repository)
    assert repository.get(job["id"], job["id"])["status"] == "completed"
    assert repository.read_document(subject) == child_document
    assert repository.get_scan(scan["id"])["postprocess_pending"] is False
    assert len(runtime.published) == 1 and not runtime.notices
    assert repository.count("scan") == repository.count("job") == 2


def test_approved_with_flags_completion_retries_without_reopening_review(service_runtime):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime, units=[ContentUnit("body", "PRIVATE_CANARY")])
    assert jobs.run_scan_job(job["id"], repository=repository)["status"] == "completed_with_findings"
    current = repository.get_scan(scan["id"])
    repository.replace({**current, "review_decision": {
        "action": "approve_with_flags", "actor_id": "owner", "reason": "Authorized test approval",
        "acknowledged_flags": True, "decided_at": jobs._timestamp(),
        "scan_id": scan["id"], "source_revision": subject.source_revision,
        "content_fingerprint": current["content_fingerprint"],
        "policy_fingerprint": current["policy_fingerprint"],
        "policy_snapshot_hash": hash_payload(current["policy"]),
    }}, current["_etag"])
    runtime.failures["notification"] = True
    with pytest.raises(RuntimeError):
        service.publish_scan(scan["id"], "owner", repository=repository)
    assert repository.get_scan(scan["id"])["state"] == "approved_with_flags"
    approvals = len(runtime.approvals)
    runtime.failures["notification"] = False
    runtime.settings["enable_content_screening"] = False
    jobs.check_due_scan_jobs_once(repository=repository)
    assert repository.get_scan(scan["id"])["completion_notified"]
    assert repository.read_document(subject)["content_screening"]["state"] == "approved_with_flags"
    assert len(runtime.published) == 1 and len(runtime.approvals) == approvals
    assert repository.count("scan") == 1


def test_disabled_completion_never_runs_an_unscreened_metadata_followup(service_runtime):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime, trigger="upload")
    runtime.failures["notification"] = True
    jobs.run_scan_job(job["id"], repository=repository)
    runtime.failures["notification"] = False
    runtime.settings.update(enable_content_screening=False, enable_extract_meta_data=True)
    runtime.helpers.process_metadata_extraction_background = lambda *args, **kwargs: pytest.fail("Disabled screening must not generate unchecked metadata.")
    jobs.check_due_scan_jobs_once(repository=repository)
    assert document_is_available(repository.read_document(subject))
    assert repository.get_scan(scan["id"])["completion_notified"]
    assert repository.count("scan") == repository.count("job") == 1


@pytest.mark.parametrize("during_publication", [False, True])
def test_real_service_cancellation_never_releases_content(service_runtime, monkeypatch, during_publication):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime, units=[
        ContentUnit(f"part-{index}", f"Ordinary paragraph {index}.") for index in range(4)
    ])
    if during_publication:
        publish = runtime.helpers._publish_screened_document

        def cancel(document, units, current_scan, actor_id, **kwargs):
            jobs.request_scan_job_action(job["id"], actor_id, "cancel", repository=repository)
            return publish(document, units, current_scan, actor_id, **kwargs)

        runtime.helpers._publish_screened_document = cancel
    else:
        inspect = engine.inspect_content

        def cancel(*args, on_progress, **kwargs):
            def progress(event):
                if event.get("completed_windows") == 1:
                    jobs.request_scan_job_action(job["id"], "owner", "cancel", repository=repository)
                return on_progress(event)
            return inspect(*args, on_progress=progress, **kwargs)

        monkeypatch.setattr(engine, "inspect_content", cancel)
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "cancelled"
    assert not document_is_available(repository.read_document(subject))
    assert not runtime.published and not runtime.notices
    assert repository.get_scan(scan["id"])["state"] not in {"cleared", "approved_with_flags"}
    if not during_publication:
        inspection = runtime.storage.read_json(repository.get_scan(scan["id"])["result_ref"], subject)
        assert inspection["detectors"][0]["completed_windows"] < inspection["detectors"][0]["required_windows"]


def test_real_pending_review_creation_is_retried_after_worker_failure_and_disable(service_runtime):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime, units=[ContentUnit("body", "PRIVATE_CANARY")])
    runtime.failures["approval"] = True
    first = jobs.run_scan_job(job["id"], repository=repository)
    assert first["status"] == "queued" and first["counts"]["retry"] == 1
    assert repository.get_scan(scan["id"])["state"] == "pending_review"
    assert not runtime.published
    runtime.failures["approval"] = False
    runtime.settings["enable_content_screening"] = False
    jobs.check_due_scan_jobs_once(repository=repository)
    finished = repository.get(job["id"], job["id"])
    assert finished["status"] == "completed_with_findings" and finished["counts"]["findings"] == 1
    assert repository.get_scan(scan["id"])["approval_id"] == f"approval-{scan['id']}"
    assert repository.read_document(subject)["content_screening"]["state"] == "pending_review"
    assert len(runtime.inspections) == 1 and len(set(runtime.approvals)) == 1
    assert "private-approval-provider-canary" not in repr(finished) + repr(runtime.logs)


def test_background_review_receipts_retry_until_acknowledged_without_releasing(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime, units=[ContentUnit("body", "PRIVATE_CANARY")])
    assert jobs.run_scan_job(job["id"], repository=repository)["status"] == "completed_with_findings"
    current = repository.get_scan(scan["id"])
    document = repository.read_document(subject)
    acknowledged = {"value": False}
    monkeypatch.setattr(
        sys.modules["functions_approvals"], "create_content_screening_approval",
        lambda scan, actor_id: {"id": current["approval_id"], "notifications_complete": acknowledged["value"]},
    )
    runtime.settings["enable_content_screening"] = False
    jobs.check_due_scan_jobs_once(repository=repository)
    assert repository.get_scan(scan["id"])["postprocess_pending"] is True
    assert repository.read_document(subject) == document
    acknowledged["value"] = True
    jobs.check_due_scan_jobs_once(repository=repository)
    assert repository.get_scan(scan["id"])["postprocess_pending"] is False
    assert repository.get_scan(scan["id"])["review_notifications_complete"] is True
    assert repository.read_document(subject) == document
    assert not runtime.published and not runtime.notices


def test_background_recovery_clears_superseded_review_without_notifying(service_runtime):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime, units=[ContentUnit("body", "PRIVATE_CANARY")])
    assert jobs.run_scan_job(job["id"], repository=repository)["status"] == "completed_with_findings"
    document = repository.read_document(subject)
    successor = service.begin_scan(
        subject, "owner", repository=repository,
        expected_document_etag=document["_etag"], parent_scan_id=scan["id"],
    )
    document = repository.read_document(subject)
    review_calls = len(runtime.approvals)
    runtime.settings["enable_content_screening"] = False
    jobs.check_due_scan_jobs_once(repository=repository)
    assert repository.get_scan(scan["id"])["postprocess_pending"] is False
    assert repository.read_document(subject) == document
    assert document["content_screening"]["scan_id"] == successor["id"]
    assert len(runtime.approvals) == review_calls
    assert not runtime.published and not runtime.notices


def test_real_all_workspace_scan_covers_every_scope_and_revision_keyset(service_runtime, monkeypatch):
    runtime = service_runtime
    repository = runtime.repository
    monkeypatch.setattr(jobs, "ENUMERATION_PAGE_SIZE", 2)
    monkeypatch.setattr(jobs, "MAX_ITEMS_PER_RUN", 2)
    for scope in jobs.SCOPE_ORDER:
        for index in range(5):
            add_document(
                repository, f"{scope}-{index}", scope, f"{scope}-owner", index + 1,
                is_current_version=index == 4,
            )
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context():
        session["user"] = {"oid": "administrator", "roles": ["Admin"]}
        job = jobs.create_scan_job("administrator", {"all_workspaces": True}, is_admin=True, repository=repository)
    completed = drain(repository, job["id"], None)
    assert completed["status"] == "completed"
    assert completed["counts"]["completed"] == completed["counts"]["total"] == 15
    assert len(set(runtime.inspections)) == len(runtime.published) == len(runtime.notices) == 15
    assert completed["enumeration"]["complete"] and completed["enumeration"]["pages"] == 9


@pytest.mark.parametrize("marker", [None, [], {}, {"state": "unknown"}, {"state": "rejected"}, {"state": "deleting"}, {"state": "deleted"}])
def test_invalid_or_terminal_markers_are_not_replaced_by_a_new_scan(runtime, marker):
    repository, *_ = runtime
    document = add_document(repository, "one", content_screening=marker)
    job = create_job(repository, ["one"])
    calls = []
    result = jobs.run_scan_job(job["id"], processor=completing_processor(repository, calls), repository=repository)
    assert result["status"] == "incomplete" and result["counts"]["completed"] == 0
    assert repository.document_container("personal").read_item("one", "one") == document
    assert not calls and repository.count("scan") == 0


@pytest.mark.parametrize("missing_document", [False, True])
def test_deleted_ingestion_sources_are_never_recreated(service_runtime, missing_document):
    runtime = service_runtime
    repository = runtime.repository
    subject, scan, job = stage_scan(runtime)
    current = repository.get_scan(scan["id"])
    repository.replace({**current, "state": "deleted", "source_ref": None, "units_ref": None}, current["_etag"])
    runtime.storage.delete_revision(subject)
    if missing_document:
        del repository.document_container("personal").documents[("one", "one")]
    result = jobs.run_scan_job(job["id"], repository=repository)
    assert result["status"] == "incomplete" and result["counts"]["completed"] == 0
    assert not runtime.inspections and not runtime.published and not runtime.notices
    assert repository.get_scan(scan["id"])["state"] == "deleted"
    assert repository.count("scan") == 1
    if missing_document:
        assert repository.document_container("personal").documents == {}
