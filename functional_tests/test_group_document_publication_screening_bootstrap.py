# test_group_document_publication_screening_bootstrap.py
"""
Functional tests for receipt-bound screening reservation consumption.
Version: 0.261.131
Implemented in: 0.261.131

Real scoped Flask decisions, canonical publication, document creation, screening
admission, conditional repositories and durable scan queues use isolated stores.
The shared publication fixture blocks network access. No models or Azure services
are called; fake storage is not evidence of live Cosmos consistency.
"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

from test_content_screening_persistence import FakeBlobService, FakeCosmos
from test_group_document_management import StoreFailure, management  # noqa: F401
from test_group_document_publication import (
    BINDING, OPERATION, RECEIPTS, REQUESTER, ROOT, after_stage_claim, assert_receipt,
    change_receipt, decide, publication, publication_modules, receipt, set_actor, sharing, submit,
)
from test_group_document_read_apis import environment  # noqa: F401
from test_support.agent_delegation import APP_ROOT

from content_screening import repository as screening_repository
from content_screening.contracts import ContentUnit, DocumentHeldError, subject_from_document
from content_screening.policies import default_policy
from content_screening.repository import ScreeningRepository
from content_screening.storage import ScreeningStorage
from functions_artifact_publication_readiness import (
    PUBLICATION_SCREENING_CONSUMPTION as CONSUMPTION,
    PUBLICATION_SCREENING_RESERVATION as RESERVATION,
    publication_screening_reservation,
)


class InjectedCrash(BaseException):
    """Model process exit without letting request-level exception handlers run."""


@pytest.fixture
def screened_publication(publication, tmp_path):
    env = publication
    patch = env.scoped_monkeypatch
    env.settings["enable_content_screening"] = True
    metadata = FakeCosmos()
    repository = ScreeningRepository(metadata, {"group": env.source})
    patch.setattr(env.config, "cosmos_content_screening_container", metadata)
    patch.setattr(screening_repository, "get_repository", lambda: repository)
    policy = default_policy()
    policy.update(enabled=True, rules=[{
        "id": "restricted", "name": "Restricted", "type": "literal", "enabled": True,
        "severity": "high", "category": "sensitive", "values": ["PRIVATE_CANARY"],
    }])
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
    patch.setitem(
        env.document_helpers, "prepare_document_deletion",
        lambda item, actor: screening.prepare_document_deletion(item, actor, repository=repository, storage=storage),
    )
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

    def prepare():
        return screening.prepare_document_upload(
            env.target, REQUESTER, str(source_path), env.source.records[env.target]["file_name"],
            group_id="group-a",
        )

    env.publication_state["queue_hook"] = prepare
    env.screening = screening
    env.screening_repository = repository
    env.screening_metadata = metadata
    env.screening_storage = storage
    env.prepare_screened_upload = prepare
    return env


def current_document(env):
    return env.source.read_item(env.target, env.target)


def scan_records(env, kind="scan"):
    page = env.screening_repository.query(
        kind, "group:group-a", filters={"document_id": env.target}, page_size=100,
    )
    return page["items"]


def crash_before_queue(env):
    original = env.canonical._stage

    def stage(artifact, saved, name, *, complete=False):
        if name == "approval_queue" and not complete:
            raise InjectedCrash()
        return original(artifact, saved, name, complete=complete)

    with env.scoped_monkeypatch.context() as patch:
        patch.setattr(env.canonical, "_stage", stage)
        with pytest.raises(InjectedCrash):
            decide(env, "approve")


def assert_bootstrap_denied(env):
    view = sharing(env)
    response = decide(env, "approve")
    saved = receipt(env)
    assert response.status_code == 409, response.get_json()
    assert "Cancel" in response.get_json()["message"]
    assert "again" in response.get_json()["message"]
    assert "approve_artifact" not in view.get_json()["actions"]
    assert "approve_artifact" not in view.get_json()["publication"]["actions"]
    assert not env.publication_calls["queue_attempts"]
    assert "decision" not in saved
    return response


def test_reserved_scan_uuid_bootstraps_once_without_granting_content_or_sharing(screened_publication):
    env = screened_publication
    initial = submit(env)
    initial_receipt = receipt(env)
    original_proof = initial_receipt[RESERVATION]
    stored_proof = publication_screening_reservation(initial)
    assert initial["content_screening"]["scan_id"]
    assert original_proof == stored_proof
    assert CONSUMPTION not in initial_receipt
    pending = sharing(env)
    assert "approve_artifact" in pending.get_json()["actions"]
    response = decide(env, "approve")
    assert_receipt(response, env, "approve", "queued", "approved", 202)
    current = current_document(env)
    saved = receipt(env)
    scans = scan_records(env)
    jobs = list(env.screening_metadata.query_items(
        "SELECT * FROM c WHERE c.kind = @kind", parameters=[{"name": "@kind", "value": "job"}],
    ))
    assert len(env.publication_calls["queue_attempts"]) == len(scans) == len(jobs) == 1
    assert saved[RESERVATION] == original_proof
    assert saved[CONSUMPTION] == {
        "operation_id": current[OPERATION]["id"], "fingerprint": original_proof["fingerprint"],
        "scan_id": initial["content_screening"]["scan_id"],
    }
    assert current["content_screening"]["state"] == "pending_scan"
    assert current["content_screening"]["generation"] == 2
    assert current["content_screening"]["scan_id"] == initial["content_screening"]["scan_id"]
    with pytest.raises(DocumentHeldError):
        env.access.assert_document_available(env.target, user_id="manager", group_id="group-a")
    with pytest.raises(DocumentHeldError):
        env.access.read_available_document_bytes(env.target, user_id="manager", group_id="group-a")
    download = env.client.get(f"{ROOT}/{env.target}/download")
    share = env.client.post(
        f"{ROOT}/{env.target}/share",
        json={"expected_etag": current["_etag"], "target_group_id": "group-b"},
    )
    detail = env.client.get(f"/api/group_documents/{env.target}?group_id=group-a")
    repeated = decide(env, "approve")
    assert download.status_code == share.status_code == repeated.status_code == 409
    assert detail.status_code == 200
    assert detail.get_json()["content_screening"]["available"] is False
    assert detail.get_json()["document_actions"] == []
    assert "share" not in detail.get_json()["document_collaboration_actions"]
    serialized = str(detail.get_json())
    for private in (RESERVATION, CONSUMPTION, BINDING, original_proof["fingerprint"], current[OPERATION]["id"]):
        assert private not in serialized
    assert len(env.publication_calls["queue_attempts"]) == 1
    assert not env.blobs.downloads


def test_enrollment_fingerprints_the_stored_destination_not_the_creation_return_value(screened_publication):
    env = screened_publication
    original = env.canonical.create_document
    returned = {}

    def create(**values):
        original(**values)
        stored = env.source.read_item(values["document_id"], values["document_id"])
        returned.update(stored)
        returned["content_screening"] = env.screening.initial_document_marker(stored)
        return returned

    env.scoped_monkeypatch.setattr(env.canonical, "create_document", create)
    initial = submit(env)
    saved = receipt(env)
    stored_proof = publication_screening_reservation(initial)
    in_memory_proof = publication_screening_reservation(returned)
    assert saved[RESERVATION] == stored_proof
    assert saved[RESERVATION] != in_memory_proof
    response = decide(env, "approve")
    assert_receipt(response, env, "approve", "queued", "approved", 202)


def test_replaying_legacy_preparation_cannot_mint_missing_reservation_proof(screened_publication):
    env = screened_publication
    submit(env, legacy=True)
    message = env.messages.read_item(env.artifact_id, "private-conversation")
    metadata = deepcopy(message["metadata"])
    legacy = metadata[RECEIPTS][env.receipt_id]
    legacy.pop(RESERVATION)
    legacy["stages"].pop("prepare")
    env.messages.change(env.artifact_id, metadata=metadata)
    env.source.records[env.target].pop("generated_artifact_publication_receipt_id")
    submit(env, legacy=True)
    saved = receipt(env)
    assert RESERVATION not in saved
    assert_bootstrap_denied(env)


def test_scan_racing_preparation_cannot_be_hidden_before_proof_enrollment(screened_publication):
    env = screened_publication
    original = env.canonical.update_document

    def update(**values):
        original(**values)
        if "generated_artifact_publication_receipt_id" not in values:
            return
        env.target = values["document_id"]
        env.receipt_id = values["generated_artifact_publication_receipt_id"]
        current = current_document(env)
        scan = env.screening.begin_scan(
            subject_from_document(current), REQUESTER, repository=env.screening_repository,
            scan_id=current["content_screening"]["scan_id"],
        )
        env.source.change(env.target, content_screening=current["content_screening"])
        env.screening_metadata.documents.pop((scan["id"], scan["id"]))

    env.scoped_monkeypatch.setattr(env.canonical, "update_document", update)
    with pytest.raises(ValueError, match="Cancel"):
        submit(env)
    saved = receipt(env)
    assert RESERVATION not in saved
    assert saved[CONSUMPTION]["scan_id"]
    assert_bootstrap_denied(env)


@pytest.mark.parametrize("state", ["pending_scan", "pending_review", "scanning", "scan_error", "incomplete", "publishing"])
def test_actual_scan_attempt_is_never_bootstrap_admission(screened_publication, state):
    env = screened_publication
    initial = submit(env)
    scan = env.screening.begin_scan(
        subject_from_document(initial), REQUESTER, repository=env.screening_repository,
        scan_id=initial["content_screening"]["scan_id"],
    )
    env.screening._save_scan(env.screening_repository, scan, state=state)
    env.screening._set_document_state(env.screening_repository, scan, state)
    held = deepcopy(current_document(env)["content_screening"])
    assert_bootstrap_denied(env)
    current = current_document(env)
    assert current["content_screening"] == held


@pytest.mark.parametrize("remove_row", [False, True])
def test_failed_scan_marker_reset_and_removed_scan_cannot_unconsume_receipt(screened_publication, remove_row):
    env = screened_publication
    initial = submit(env)
    scan = env.screening.begin_scan(
        subject_from_document(initial), REQUESTER, repository=env.screening_repository,
        scan_id=initial["content_screening"]["scan_id"],
    )
    env.screening._record_failure(env.screening_repository, scan["id"], "fixture_failure")
    interrupted_receipt = receipt(env)
    consumed = interrupted_receipt[CONSUMPTION]
    env.source.change(env.target, content_screening=initial["content_screening"], status=initial["status"])
    if remove_row:
        env.screening_metadata.documents.pop((scan["id"], scan["id"]))
    assert_bootstrap_denied(env)
    saved = receipt(env)
    assert saved[CONSUMPTION] == consumed


@pytest.mark.parametrize("failure", ["before_scan_create", "after_scan_create"])
def test_scan_consumption_is_written_before_scan_creation_or_marker_replacement(screened_publication, failure):
    env = screened_publication
    initial = submit(env)
    original_create = env.screening_repository.create

    def create(record):
        saved = receipt(env)
        assert saved[CONSUMPTION]["scan_id"] == record["id"]
        if failure == "after_scan_create":
            original_create(record)
        raise StoreFailure()

    with env.scoped_monkeypatch.context() as patch:
        patch.setattr(env.screening_repository, "create", create)
        with pytest.raises(StoreFailure):
            env.screening.begin_scan(
                subject_from_document(initial), REQUESTER, repository=env.screening_repository,
                scan_id=initial["content_screening"]["scan_id"],
            )
    current = current_document(env)
    assert current["content_screening"] == initial["content_screening"]
    env.screening_metadata.documents.pop(
        (initial["content_screening"]["scan_id"], initial["content_screening"]["scan_id"]), None,
    )
    assert_bootstrap_denied(env)


@pytest.mark.parametrize("enrolled", [False, True])
def test_absent_marker_uses_current_destination_policy_and_never_bootstraps(screened_publication, enrolled):
    env = screened_publication
    if not enrolled:
        env.settings["enable_content_screening"] = False
    submit(env)
    env.settings["enable_content_screening"] = True
    env.source.records[env.target].pop("content_screening", None)
    assert_bootstrap_denied(env)


def test_disabling_screening_does_not_turn_a_persisted_reservation_into_available_content(screened_publication):
    env = screened_publication
    submit(env)
    env.settings["enable_content_screening"] = False
    assert_bootstrap_denied(env)


def test_enabled_empty_policy_preserves_ordinary_unscreened_approval(screened_publication):
    env = screened_publication
    baseline = env.screening_repository.get_policy("global", "global")
    env.screening_repository.save_policy(
        "global", "global", {**default_policy(), "enabled": True}, "administrator", etag=baseline["_etag"],
    )
    initial = submit(env)
    response = decide(env, "approve")
    saved = receipt(env)
    assert "content_screening" not in initial
    assert RESERVATION not in saved and CONSUMPTION not in saved
    assert_receipt(response, env, "approve", "queued", "approved", 202)
    assert len(env.publication_calls["queue_attempts"]) == 1


@pytest.mark.parametrize("failure", ["process_exit", "consumption_acknowledgement"])
def test_same_operation_prequeue_crash_recovers_exactly_once(screened_publication, failure):
    env = screened_publication
    initial = submit(env)
    if failure == "process_exit":
        crash_before_queue(env)
    else:
        original = env.messages.replace_item
        failed = False

        def replace(item, body, **kwargs):
            nonlocal failed
            result = original(item, body, **kwargs)
            candidate = body.get("metadata", {}).get(RECEIPTS, {}).get(env.receipt_id, {})
            if CONSUMPTION in candidate and not failed:
                failed = True
                raise TimeoutError("Private acknowledgement canary")
            return result

        with env.scoped_monkeypatch.context() as patch:
            patch.setattr(env.messages, "replace_item", replace)
            failed_response = decide(env, "approve")
        assert_receipt(failed_response, env, "approve", "partial", "approval_failed", 207)
    interrupted = current_document(env)
    interrupted_receipt = receipt(env)
    consumed = interrupted_receipt[CONSUMPTION]
    assert "scan_id" not in consumed
    assert consumed["operation_id"] == interrupted[OPERATION]["id"]
    assert interrupted["content_screening"] == initial["content_screening"]
    assert "approval_queue" not in interrupted_receipt["stages"]
    assert not env.publication_calls["queue_attempts"]
    view = sharing(env)
    assert "approve_artifact" in view.get_json()["actions"]
    response = decide(env, "approve", etag=view.get_json()["etag"])
    current = current_document(env)
    scans = scan_records(env)
    assert_receipt(response, env, "approve", "unchanged", "approved", 200)
    assert current[OPERATION]["id"] == interrupted[OPERATION]["id"]
    assert current[OPERATION]["execution_token"] != interrupted[OPERATION]["execution_token"]
    assert len(scans) == len(env.publication_calls["queue_attempts"]) == 1
    assert current["content_screening"]["state"] == "pending_scan"
    repeated = decide(env, "approve")
    assert repeated.status_code == 409
    assert len(env.publication_calls["queue_attempts"]) == 1


@pytest.mark.parametrize("change", ["operation_id", "actor", "missing_token"])
def test_a_different_operation_or_actor_cannot_borrow_consumed_prequeue_retry(screened_publication, change):
    env = screened_publication
    submit(env)
    crash_before_queue(env)
    interrupted = current_document(env)
    consumed = receipt(env)[CONSUMPTION]
    if change == "operation_id":
        env.source.change(env.target, **{OPERATION: {**interrupted[OPERATION], "id": "another-operation"}})
    elif change == "actor":
        set_actor(env, "admin")
    else:
        env.source.change(env.target, **{OPERATION: {**interrupted[OPERATION], "execution_token": None}})
    view = sharing(env)
    response = decide(env, "approve")
    saved = receipt(env)
    assert response.status_code == 409
    assert "Cancel" in response.get_json()["message"]
    assert "approve_artifact" not in view.get_json()["actions"]
    assert not env.publication_calls["queue_attempts"]
    assert saved[CONSUMPTION] == consumed
    with pytest.raises(ValueError, match="Cancel"):
        env.canonical.decide_artifact_publication(
            "manager", current_document(env), "approved", operation_id="another-operation",
        )
    assert not env.publication_calls["queue_attempts"]


@pytest.mark.parametrize("recreation", ["new_reservation", "copied_marker_new_resource"])
def test_recreated_destination_cannot_reuse_old_receipt_fingerprint(screened_publication, recreation):
    env = screened_publication
    initial = submit(env)
    original_proof = receipt(env)[RESERVATION]
    env.source.delete_item(env.target, env.target)
    replacement = deepcopy(initial)
    if recreation == "new_reservation":
        replacement["content_screening"] = env.screening.initial_document_marker(replacement)
    else:
        replacement["_rid"] = "another-physical-cosmos-document"
    env.source.create_item(replacement)
    assert_bootstrap_denied(env)
    saved = receipt(env)
    assert saved[RESERVATION] == original_proof


def test_unproven_legacy_reservation_can_cancel_and_request_a_new_admissible_receipt(screened_publication):
    env = screened_publication
    initial = submit(env, legacy=True)
    message = env.messages.read_item(env.artifact_id, "private-conversation")
    metadata = deepcopy(message["metadata"])
    metadata[RECEIPTS][env.receipt_id].pop(RESERVATION)
    env.messages.change(env.artifact_id, metadata=metadata)
    assert_bootstrap_denied(env)
    old_id, old_receipt = env.target, env.receipt_id
    set_actor(env, REQUESTER)
    cancelled = decide(env, "cancel")
    assert_receipt(cancelled, env, "cancel", "applied", "cancelled", 200)
    assert old_id not in env.source.records
    fresh = submit(env, request_id="new-screening-publication-request")
    assert fresh["id"] != old_id
    assert fresh["content_screening"]["scan_id"] != initial["content_screening"]["scan_id"]
    assert env.receipt_id != old_receipt
    set_actor(env, "manager")
    approved = decide(env, "approve")
    assert_receipt(approved, env, "approve", "queued", "approved", 202)
    receipts = env.messages.read_item(env.artifact_id, "private-conversation")["metadata"][RECEIPTS]
    assert receipts[old_receipt]["decision"]["choice"] == "cancelled"
    assert RESERVATION not in receipts[old_receipt]
    assert len(receipts) == len(env.publication_calls["create"]) == 2
    assert len(env.publication_calls["queue_attempts"]) == 1


@pytest.mark.parametrize("action", ["cancel", "reject"])
def test_negative_cleanup_preserves_existing_consumption_forever(screened_publication, action):
    env = screened_publication
    initial = submit(env)
    env.screening.begin_scan(
        subject_from_document(initial), REQUESTER, repository=env.screening_repository,
        scan_id=initial["content_screening"]["scan_id"],
    )
    consumed = receipt(env)[CONSUMPTION]
    if action == "cancel":
        set_actor(env, REQUESTER)
    response = decide(env, action)
    saved = receipt(env)
    assert_receipt(response, env, action, "applied", "cancelled" if action == "cancel" else "rejected", 200)
    assert env.target not in env.source.records
    assert saved[CONSUMPTION] == consumed
    assert not env.publication_calls["queue_attempts"]


@pytest.mark.parametrize("when", ["before", "after_bytes", "queue_claim"])
def test_screening_bootstrap_never_bypasses_original_source_authority(screened_publication, when):
    env = screened_publication
    submit(env)

    def revoke():
        env.publication_state["source_allowed"] = False

    if when == "before":
        revoke()
    elif when == "after_bytes":
        env.publication_state["download_hook"] = revoke
    else:
        after_stage_claim(env, "approval_queue", revoke)
    response = decide(env, "approve")
    saved = receipt(env)
    assert response.status_code == (207 if when == "queue_claim" else 409)
    assert not env.publication_calls["queue_attempts"]
    if when == "queue_claim":
        current = current_document(env)
        assert saved[CONSUMPTION]["operation_id"] == current[OPERATION]["id"]
        assert saved["stages"]["approval_queue"] == "started"
    else:
        assert CONSUMPTION not in saved and "decision" not in saved


def test_bootstrap_still_requires_the_exact_original_artifact_bytes(screened_publication):
    env = screened_publication
    submit(env)
    env.content = b"Different generated artifact bytes"
    response = decide(env, "approve")
    saved = receipt(env)
    assert response.status_code == 409
    assert CONSUMPTION not in saved and "decision" not in saved
    assert not env.publication_calls["queue_attempts"]


@pytest.mark.parametrize("when", ["before", "after"])
def test_scan_cannot_start_without_acknowledged_write_ahead_consumption(screened_publication, when):
    env = screened_publication
    initial = submit(env)
    original = env.messages.replace_item

    def replace(item, body, **kwargs):
        candidate = body.get("metadata", {}).get(RECEIPTS, {}).get(env.receipt_id, {})
        if CONSUMPTION not in candidate:
            return original(item, body, **kwargs)
        if when == "after":
            original(item, body, **kwargs)
        raise TimeoutError("Private receipt acknowledgement canary")

    with env.scoped_monkeypatch.context() as patch:
        patch.setattr(env.messages, "replace_item", replace)
        with pytest.raises(TimeoutError):
            env.screening.begin_scan(
                subject_from_document(initial), REQUESTER, repository=env.screening_repository,
                scan_id=initial["content_screening"]["scan_id"],
            )
    current = current_document(env)
    scans = scan_records(env)
    saved = receipt(env)
    assert not scans
    assert current["content_screening"] == initial["content_screening"]
    if when == "after":
        assert saved[CONSUMPTION]["scan_id"] == initial["content_screening"]["scan_id"]
        assert_bootstrap_denied(env)
    else:
        assert CONSUMPTION not in saved
        response = decide(env, "approve")
        assert_receipt(response, env, "approve", "queued", "approved", 202)


def test_concurrent_scan_consumption_wins_receipt_cas_before_approval(screened_publication):
    env = screened_publication
    initial = submit(env)

    def before_write(operation, item, body):
        candidate = body.get("metadata", {}).get(RECEIPTS, {}).get(env.receipt_id, {})
        if operation == "replace" and candidate.get("decision", {}).get("choice") == "approved":
            env.messages.before_write = None
            env.screening.begin_scan(
                subject_from_document(initial), REQUESTER, repository=env.screening_repository,
                scan_id=initial["content_screening"]["scan_id"],
            )

    env.messages.before_write = before_write
    response = decide(env, "approve")
    saved = receipt(env)
    scans = scan_records(env)
    assert response.status_code == 409
    assert "decision" not in saved
    assert saved[CONSUMPTION]["operation_id"] == f"scan:{initial['content_screening']['scan_id']}"
    assert len(scans) == 1
    assert not env.publication_calls["queue_attempts"]


@pytest.mark.parametrize("change", ["marker", "receipt", "scan"])
def test_queue_admission_rereads_reservation_and_consumption_after_stage_claim(screened_publication, change):
    env = screened_publication
    initial = submit(env)

    def invalidate():
        if change == "marker":
            env.source.change(env.target, content_screening=env.screening.initial_document_marker(initial))
        elif change == "receipt":
            saved = receipt(env)
            change_receipt(env, **{CONSUMPTION: {**saved[CONSUMPTION], "operation_id": "different-operation"}})
        else:
            env.screening.begin_scan(
                subject_from_document(initial), REQUESTER, repository=env.screening_repository,
                scan_id=initial["content_screening"]["scan_id"],
            )

    after_stage_claim(env, "approval_queue", invalidate)
    response = decide(env, "approve")
    saved = receipt(env)
    assert_receipt(response, env, "approve", "partial", "approval_failed", 207)
    assert saved["stages"]["approval_queue"] == "started"
    assert not env.publication_calls["queue_attempts"]
    repeated = decide(env, "approve")
    assert repeated.status_code == 409
    assert not env.publication_calls["queue_attempts"]


def test_unknown_queue_acknowledgement_never_allows_bootstrap_replay_even_after_reset(screened_publication):
    env = screened_publication
    initial = submit(env)
    env.publication_state["queue_failure"] = True
    response = decide(env, "approve")
    saved = receipt(env)
    assert_receipt(response, env, "approve", "partial", "approval_failed", 207)
    assert saved["stages"]["approval_queue"] == "started"
    assert saved[CONSUMPTION]["scan_id"] == initial["content_screening"]["scan_id"]
    env.source.change(env.target, content_screening=initial["content_screening"])
    env.screening_metadata.documents.pop(
        (initial["content_screening"]["scan_id"], initial["content_screening"]["scan_id"]),
    )
    repeated = decide(env, "approve")
    after = receipt(env)
    assert repeated.status_code == 409
    assert after[CONSUMPTION] == saved[CONSUMPTION]
    assert len(env.publication_calls["queue_attempts"]) == 1


@pytest.mark.parametrize("change", [
    {"blob_path": "group-a/unreviewed.md"},
    {"archived_blob_path": "group-a/older.md"},
    {"num_chunks": 1},
    {"number_of_pages": 1},
    {"content": "prior content"},
    {"version": 2},
    {"revision_family_id": "older-revision"},
    {"generated_artifact_publication_processing": {"state": "running"}},
    {"generated_artifact_publication_processing": {}},
    {"screening_provenance": {}},
])
def test_prior_content_or_native_processing_precludes_bootstrap(screened_publication, change):
    env = screened_publication
    submit(env)
    if "version" in change:
        current = current_document(env)
        change = {**change, BINDING: {**current[BINDING], "document_version": 2}}
        change_receipt(env, document_version=2)
    env.source.change(env.target, **change)
    assert_bootstrap_denied(env)


@pytest.mark.parametrize("change", [
    {"generation": 2}, {"generation": True}, {"review_required": True}, {"finding_count": 1},
    {"result_ref": {"private": "result"}}, {"review_decision": {"action": "reject"}},
    {"history": []}, {"previous_marker": {}}, {"content_fingerprint": "prior-content"},
])
def test_scan_results_reviews_or_history_are_not_initial_reservations(screened_publication, change):
    env = screened_publication
    initial = submit(env)
    env.source.change(env.target, content_screening={**initial["content_screening"], **change})
    assert_bootstrap_denied(env)


@pytest.mark.parametrize("kind", ["scan", "review", "finding", "model_window", "event", "audit", "checkpoint", "work_item"])
def test_private_scan_or_review_history_denies_even_with_an_initial_looking_marker(screened_publication, kind):
    env = screened_publication
    initial = submit(env)
    env.screening_repository.create({
        "id": "older-evidence", "partition_key": "older-evidence", "kind": kind,
        "subject": subject_from_document(initial).to_dict(), "state": "pending_scan",
    })
    assert_bootstrap_denied(env)


def test_inspection_of_an_existing_scan_consumes_before_engine_execution(screened_publication):
    env = screened_publication
    initial = submit(env)
    scan_id = initial["content_screening"]["scan_id"]
    policy = env.screening.get_effective_policy(subject_from_document(initial), repository=env.screening_repository)
    env.screening_repository.create({
        "id": scan_id, "partition_key": scan_id, "kind": "scan",
        "subject": subject_from_document(initial).to_dict(), "state": "pending_scan",
        "actor_id": REQUESTER, "policy": policy, "policy_fingerprint": env.screening.hash_payload(policy),
    })

    def engine(*args, **kwargs):
        saved = receipt(env)
        assert saved[CONSUMPTION]["scan_id"] == scan_id
        raise InjectedCrash()

    with pytest.raises(InjectedCrash):
        env.screening.inspect_scan(
            scan_id, [ContentUnit("unit", "Ordinary content")], REQUESTER,
            repository=env.screening_repository, storage=env.screening_storage, engine=engine,
        )
    consumed = receipt(env)[CONSUMPTION]
    env.source.change(env.target, content_screening=initial["content_screening"])
    env.screening_metadata.documents.pop((scan_id, scan_id))
    assert_bootstrap_denied(env)
    saved = receipt(env)
    assert saved[CONSUMPTION] == consumed


@pytest.mark.parametrize("first", ["content_screening.service", "functions_artifact_publication_readiness"])
def test_latch_modules_keep_real_cold_imports_below_azure_bootstrap(first):
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
