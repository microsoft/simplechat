# test_workflow_runtime_store.py
"""
Functional tests for the durable workflow runtime-control journal.
Version: 0.261.111
Implemented in: 0.261.111

These tests validate milestone 3 runtime-control durability: scoped control-row
initialization, fenced claims, CAS-protected state updates, safe gate decisions,
cancellation/tombstone behavior, projection redaction, and retry/resume
semantics without importing deployed app configuration.
"""

import importlib.util
import json
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)


STORE_PATH = Path(__file__).resolve().parents[1].joinpath(
    "application", "single_app", "functions_workflow_runtime_store.py",
)
SPEC = importlib.util.spec_from_file_location("isolated_workflow_runtime_store", STORE_PATH)
runtime_store = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_store)


def json_copy(value):
    return json.loads(json.dumps(value, ensure_ascii=True, allow_nan=False))


class FakeClock:
    def __init__(self):
        self.current = datetime(2026, 9, 16, 20, 18, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.current

    def advance(self, seconds):
        self.current += timedelta(seconds=seconds)


class FakeCosmosContainer:
    def __init__(self):
        self.records = {}
        self.etag_counter = 0
        self.before_replace = None
        self.before_batch = None
        self.replaces = []
        self.batches = []

    def _key(self, partition_key, item):
        return (partition_key, item)

    def _with_etag(self, record):
        self.etag_counter += 1
        copied = json_copy(record)
        copied["_etag"] = f"etag-{self.etag_counter}"
        return copied

    def create_item(self, *, body):
        key = self._key(body["run_id"], body["id"])
        if key in self.records:
            raise CosmosResourceExistsError(status_code=409, message="Fake duplicate")
        self.records[key] = self._with_etag(body)
        return json_copy(self.records[key])

    def read_item(self, *, item, partition_key):
        key = self._key(partition_key, item)
        if key not in self.records:
            raise CosmosResourceNotFoundError(status_code=404, message="Fake missing")
        return json_copy(self.records[key])

    def replace_item(self, *, item, body, etag, match_condition):
        key = self._key(body["run_id"], item)
        if key not in self.records:
            raise CosmosResourceNotFoundError(status_code=404, message="Fake missing")
        if self.before_replace is not None:
            callback = self.before_replace
            self.before_replace = None
            callback(self)
        if match_condition is not MatchConditions.IfNotModified or self.records[key]["_etag"] != etag:
            raise CosmosHttpResponseError(status_code=412, message="Fake stale etag")
        self.records[key] = self._with_etag(body)
        self.replaces.append(json_copy(self.records[key]))
        return json_copy(self.records[key])

    def force_replace(self, body):
        key = self._key(body["run_id"], body["id"])
        self.records[key] = self._with_etag(body)

    def execute_item_batch(self, *, batch_operations, partition_key):
        if self.before_batch is not None:
            callback = self.before_batch
            self.before_batch = None
            callback(self)
        staged = deepcopy(self.records)
        for operation in batch_operations:
            name, args = operation[0], operation[1]
            options = operation[2] if len(operation) > 2 else {}
            if name == "replace":
                item, body = args
                key = self._key(partition_key, item)
                if key not in staged:
                    raise CosmosHttpResponseError(status_code=404, message="Fake missing")
                if staged[key]["_etag"] != options.get("if_match_etag"):
                    raise CosmosHttpResponseError(status_code=412, message="Fake stale etag")
                staged[key] = self._with_etag(body)
            elif name == "create":
                (body,) = args
                key = self._key(partition_key, body["id"])
                if key in staged:
                    raise CosmosHttpResponseError(status_code=409, message="Fake duplicate")
                staged[key] = self._with_etag(body)
            elif name == "upsert":
                (body,) = args
                key = self._key(partition_key, body["id"])
                staged[key] = self._with_etag(body)
            else:
                raise AssertionError(f"Unsupported batch operation {name}")
        self.records = staged
        self.batches.append(json_copy(batch_operations))
        return []


def make_store(workflow=None, run_id="run-1", container=None, clock=None):
    workflow = workflow or {"id": "workflow-1", "user_id": "user-1"}
    clock = clock or FakeClock()
    container = container or FakeCosmosContainer()
    store = runtime_store.WorkflowRuntimeStore(container, workflow, run_id, clock=clock)
    return store, container, clock


def initialized_store(workflow=None):
    store, container, clock = make_store(workflow=workflow)
    control = store.initialize(
        snapshot_ref={"storage": "cosmos", "sha256": "snapshot"},
        definition_revision=3,
        actor_user_id="user-1",
        request_id="init-1",
    )
    return store, container, clock, control


def assert_conflict(code, callback):
    try:
        callback()
    except runtime_store.RuntimeConflict as exc:
        assert exc.code == code, f"expected {code}, got {exc.code}"
        return exc
    raise AssertionError(f"expected RuntimeConflict({code})")


def test_initialize_idempotency_and_tombstone_prevents_resurrection():
    store, _container, _clock = make_store()
    first = store.initialize(
        snapshot_ref={"sha256": "same"},
        definition_revision=7,
        actor_user_id="user-1",
        request_id="init-request",
    )
    second = store.initialize(
        snapshot_ref={"sha256": "same"},
        definition_revision=7,
        actor_user_id="user-1",
        request_id="init-request",
    )
    assert second["version"] == first["version"]
    assert_conflict(
        "initialize_conflict",
        lambda: store.initialize(
            snapshot_ref={"sha256": "different"},
            definition_revision=7,
            actor_user_id="user-1",
            request_id="init-request",
        ),
    )
    tombstone = store.tombstone()
    assert tombstone["deleted"] is True
    assert tombstone["state"] == "cancelled"
    assert_conflict(
        "tombstoned",
        lambda: store.initialize(
            snapshot_ref={"sha256": "same"},
            definition_revision=7,
            actor_user_id="user-1",
            request_id="init-request",
        ),
    )
    assert_conflict("not_found", store.read)


def test_claim_race_two_owners_and_same_owner_replay():
    store, _container, _clock, _control = initialized_store()
    owner_one = store.claim(owner_id="worker-1")
    assert owner_one is not None
    assert owner_one["owner_id"] == "worker-1"
    assert store.claim(owner_id="worker-2") is None
    replayed = store.claim(owner_id="worker-1")
    assert replayed == owner_one


def test_expired_claim_fences_old_owner_and_increments_epoch():
    store, _container, clock, _control = initialized_store()
    old_token = store.claim(owner_id="worker-1", ttl_seconds=5)
    clock.advance(6)
    new_token = store.claim(owner_id="worker-2", ttl_seconds=45)
    assert new_token is not None
    assert new_token["epoch"] == old_token["epoch"] + 1
    assert_conflict(
        "ownership_lost",
        lambda: store.update(old_token, {"phase": "old-owner-write"}),
    )
    updated = store.update(new_token, {"phase": "new-owner-write"})
    assert updated["phase"] == "new-owner-write"


def test_invalid_timestamp_fails_closed_for_claim_and_assert():
    store, container, _clock, _control = initialized_store()
    token = store.claim(owner_id="worker-1")
    current = store.read()
    current["lease"]["expires_at"] = "not-a-date"
    container.force_replace(current)
    assert store.claim(owner_id="worker-2") is None
    assert_conflict("ownership_lost", lambda: store.assert_owned(token))


def test_heartbeat_preserves_state_and_public_version_after_cas_retry():
    store, container, _clock, control = initialized_store()
    token = store.claim(owner_id="worker-1")
    version_after_claim = store.read()["version"]

    def concurrent_update(fake_container):
        current = fake_container.read_item(item=runtime_store.CONTROL_ID, partition_key="run-1")
        body = {key: deepcopy(value) for key, value in current.items() if not key.startswith("_")}
        body["phase"] = "concurrent-phase"
        body["version"] += 1
        fake_container.force_replace(body)

    container.before_replace = concurrent_update
    heartbeat = store.heartbeat(token, ttl_seconds=45)
    assert heartbeat["phase"] == "concurrent-phase"
    assert heartbeat["version"] == control["version"] + 1
    assert runtime_store.public_projection(heartbeat)["version"] == version_after_claim + 1


def test_stale_version_updates_are_rejected_and_units_require_guard():
    store, _container, _clock, control = initialized_store()
    token = store.claim(owner_id="worker-1")
    assert_conflict("expected_version_required", lambda: store.update(token, {"units": {}}))
    first = store.update(token, {"phase": "phase-1"}, expected_version=control["version"])
    assert first["version"] == control["version"] + 1
    assert_conflict(
        "stale_version",
        lambda: store.update(token, {"phase": "phase-2"}, expected_version=control["version"]),
    )


def test_concurrent_decisions_stale_approval_and_identical_replay():
    store, _container, _clock, control = initialized_store()
    token = store.claim(owner_id="worker-1")
    waiting = store.wait(
        token,
        state="waiting_approval",
        gate={
            "id": "gate-1",
            "kind": "approval",
            "unit_id": "unit-1",
            "input_digest": "digest-1",
            "attempt": 2,
            "reason": "needs review",
            "choices": ["approve", "reject"],
        },
    )
    decided = store.decide(
        expected_version=waiting["version"],
        gate_id="gate-1",
        choice="approve",
        actor_user_id="user-1",
        request_id="decision-1",
    )
    replayed = store.decide(
        expected_version=waiting["version"],
        gate_id="gate-1",
        choice="approve",
        actor_user_id="user-1",
        request_id="decision-1",
    )
    assert replayed["version"] == decided["version"]
    assert replayed["state"] == "queued"
    assert replayed["memory"]["decisions"][0]["input_digest"] == "digest-1"
    assert replayed["memory"]["decisions"][0]["attempt"] == 2
    assert_conflict(
        "stale_version",
        lambda: store.decide(
            expected_version=waiting["version"],
            gate_id="gate-1",
            choice="reject",
            actor_user_id="user-2",
            request_id="decision-2",
        ),
    )
    assert control["version"] == 1


def test_invalid_choices_and_output_gate_cannot_be_approved():
    store, _container, _clock, _control = initialized_store()
    token = store.claim(owner_id="worker-1")
    assert_conflict(
        "invalid_gate",
        lambda: store.wait(
            token,
            state="waiting_approval",
            gate={"id": "bad-gate", "kind": "approval", "choices": ["approve", "ship-it"]},
        ),
    )
    output_gate = store.wait(
        token,
        state="waiting_output",
        gate={
            "id": "output-gate",
            "kind": "output",
            "unit_id": "unit-2",
            "reason": "waiting",
            "references": [{"child_run_id": "child-1", "result_ref": {"sha256": "safe-ref"}}],
        },
    )
    projection = runtime_store.public_projection(output_gate)
    assert projection["gate"]["references"] == {"count": 1}
    assert "child-1" not in json.dumps(projection["gate"], sort_keys=True)
    assert_conflict(
        "unsupported_gate",
        lambda: store.decide(
            expected_version=output_gate["version"],
            gate_id="output-gate",
            choice="approve",
            actor_user_id="user-1",
            request_id="bad-output-approval",
        ),
    )
    requeued = store.requeue_output(expected_version=output_gate["version"], gate_id="output-gate")
    assert requeued["state"] == "queued"


def test_cancel_while_worker_active_fences_commit_and_prevents_zombie_requeue():
    store, _container, _clock, _control = initialized_store()
    token = store.claim(owner_id="worker-1")
    cancelled = store.request_cancel(actor_user_id="user-1", request_id="cancel-1")
    assert cancelled["state"] == "cancelled"
    assert cancelled["lease"] is None
    assert store.claim(owner_id="worker-2") is None
    assert_conflict(
        "ownership_lost",
        lambda: store.transition(token, state="completed", completion_ref={"sha256": "done"}),
    )
    replayed = store.request_cancel(actor_user_id="user-1", request_id="cancel-1")
    assert replayed["state"] == "cancelled"


def test_identity_mismatch_is_rejected():
    store, container, _clock, _control = initialized_store()
    mismatched = runtime_store.WorkflowRuntimeStore(
        container,
        {"id": "workflow-1", "user_id": "user-1", "group_id": "group-1"},
        "run-1",
        clock=FakeClock(),
    )
    assert_conflict("identity_mismatch", mismatched.read)
    assert store.read()["scope_type"] == "personal"


def test_finite_json_and_size_bounds():
    store, _container, _clock, _control = initialized_store()
    token = store.claim(owner_id="worker-1")
    assert_conflict("invalid_payload", lambda: store.update(token, {"phase": float("nan")}))
    assert_conflict(
        "payload_too_large",
        lambda: store.update(token, {"metadata": {"note": "x" * (runtime_store.MAX_CONTROL_BYTES + 1)}}),
    )
    assert_conflict(
        "invalid_gate",
        lambda: store.wait(
            token,
            state="waiting_approval",
            gate={"id": "gate-raw", "kind": "approval", "raw_prompt": "secret", "choices": ["approve"]},
        ),
    )


def test_projection_excludes_tokens_raw_payloads_and_private_refs():
    store, _container, _clock, control = initialized_store()
    token = store.claim(owner_id="worker-1")
    updated = store.update(
        token,
        {
            "phase": "running",
            "progress": {"percent": 50},
            "run_record": {"private_payload": "hidden"},
            "context_ref": {"storage": "blob", "token": "hidden"},
            "units": {
                "unit-1": {
                    "state": "completed",
                    "attempt": 1,
                    "input_digest": "digest-1",
                    "replay_safe": True,
                    "result_ref": {
                        "storage": "cosmos",
                        "sha256": "safe",
                        "payload": "hidden",
                        "token": "hidden",
                    },
                }
            },
        },
        expected_version=control["version"],
    )
    projection = runtime_store.workflow_runtime_projection(updated)
    projection_text = json.dumps(projection, sort_keys=True)
    assert "lease" not in projection
    assert "token" not in projection_text
    assert "hidden" not in projection_text
    assert "run_record" not in projection_text
    assert "context_ref" not in projection_text
    assert projection["control_state"] == "running"
    assert projection["created_at"] == control["created_at"]
    assert projection["actor_user_id"] == "user-1"
    assert projection["snapshot_ref"]["sha256"] == "snapshot"
    assert projection["memory"]["unit_count"] == 1
    assert projection["memory"]["completed_unit_count"] == 1
    assert projection["memory"]["units"] == [{
        "key": "unit-1",
        "state": "completed",
        "attempt": 1,
        "input_digest": "digest-1",
        "replay_safe": True,
        "result_ref": {"storage": "cosmos", "sha256": "safe"},
    }]


def test_retry_resume_preserves_completed_units():
    store, _container, _clock, control = initialized_store()
    token = store.claim(owner_id="worker-1")
    with_units = store.update(
        token,
        {
            "units": {
                "complete": {"state": "completed", "attempt": 1, "replay_safe": True, "result_ref": {"sha256": "ok"}},
                "failed": {"state": "failed", "attempt": 1, "replay_safe": False, "error_ref": {"sha256": "bad"}},
            }
        },
        expected_version=control["version"],
    )
    failed = store.transition(token, state="failed", completion_ref={"sha256": "run-failed"})
    resumed = store.resume(
        expected_version=failed["version"],
        actor_user_id="user-1",
        request_id="resume-1",
    )
    assert resumed["state"] == "queued"
    assert resumed["units"] == with_units["units"]
    assert resumed["units"]["complete"]["state"] == "completed"


def test_runtime_lease_context_releases_without_auto_queueing():
    store, _container, clock, _control = initialized_store()
    with runtime_store.WorkflowRuntimeLease(
        store, owner_id="worker-1", ttl_seconds=30, heartbeat_seconds=0,
    ) as lease:
        assert lease.token is not None
        assert lease.check()["state"] == "running"
    released = store.read()
    assert released["state"] == "running"
    assert released["lease"] is not None
    assert runtime_store._parse_timestamp(released["lease"]["expires_at"]) <= clock()
    new_token = store.claim(owner_id="worker-2")
    assert new_token is not None


def test_runtime_lease_exit_allows_confirmed_tombstone_cleanup_only():
    store, _container, _clock, _control = initialized_store()
    lease = runtime_store.WorkflowRuntimeLease(
        store, owner_id="worker-1", ttl_seconds=30, heartbeat_seconds=0,
    )
    lease.__enter__()
    store.tombstone()
    assert lease.__exit__(None, None, None) is False

    missing_store, missing_container, _missing_clock, _missing_control = initialized_store()
    missing_lease = runtime_store.WorkflowRuntimeLease(
        missing_store, owner_id="worker-1", ttl_seconds=30, heartbeat_seconds=0,
    )
    missing_lease.__enter__()
    del missing_container.records[("run-1", runtime_store.CONTROL_ID)]
    assert_conflict("not_found", lambda: missing_lease.__exit__(None, None, None))


def test_write_record_fenced_batch_does_not_increment_public_version():
    store, container, _clock, control = initialized_store()
    token = store.claim(owner_id="worker-1")
    claimed = store.read()
    record = {
        "id": "task-item-1",
        "run_id": "run-1",
        "type": "workflow_task",
        "item_type": "workflow_task",
        "payload": {"value": 1},
    }
    written = store.write_record(token, record)
    saved = container.read_item(item="task-item-1", partition_key="run-1")
    after = store.read()
    assert written["workflow_id"] == "workflow-1"
    assert saved["scope_type"] == "personal"
    assert after["version"] == claimed["version"] == control["version"]
    assert after["write_nonce"]
    assert container.batches[-1][0][0] == "replace"
    assert container.batches[-1][1][0] == "upsert"


def test_write_record_retries_stale_control_etag_with_fresh_owned_check():
    store, container, _clock, _control = initialized_store()
    token = store.claim(owner_id="worker-1")

    def concurrent_guard_update(fake_container):
        current = fake_container.read_item(item=runtime_store.CONTROL_ID, partition_key="run-1")
        body = {key: deepcopy(value) for key, value in current.items() if not key.startswith("_")}
        body["phase"] = "concurrent-before-batch"
        fake_container.force_replace(body)

    container.before_batch = concurrent_guard_update
    written = store.write_record(token, {"id": "retry-item", "run_id": "run-1", "payload": "ok"})
    current = store.read()
    assert written["id"] == "retry-item"
    assert current["phase"] == "concurrent-before-batch"
    assert current["version"] == 1


def test_write_record_immutable_conflict_verifies_exact_existing_payload():
    store, _container, _clock, _control = initialized_store()
    token = store.claim(owner_id="worker-1")
    record = {"id": "immutable-item", "run_id": "run-1", "payload": {"value": "first"}}
    first = store.write_record(token, record, immutable=True)
    identical = store.write_record(token, record, immutable=True)
    assert identical == first
    assert_conflict(
        "immutable_conflict",
        lambda: store.write_record(
            token,
            {"id": "immutable-item", "run_id": "run-1", "payload": {"value": "second"}},
            immutable=True,
        ),
    )


def test_write_record_rejects_run_mismatch_stale_lease_and_tombstone():
    store, container, clock, _control = initialized_store()
    token = store.claim(owner_id="worker-1", ttl_seconds=5)
    assert_conflict(
        "identity_mismatch",
        lambda: store.write_record(token, {"id": "wrong-run", "run_id": "other-run"}),
    )
    clock.advance(6)
    assert_conflict(
        "ownership_lost",
        lambda: store.write_record(token, {"id": "expired-item", "run_id": "run-1"}),
    )
    assert ("run-1", "expired-item") not in container.records
    takeover = store.claim(owner_id="worker-2")
    store.tombstone()
    assert_conflict(
        "not_found",
        lambda: store.write_record(takeover, {"id": "tombstone-item", "run_id": "run-1"}),
    )
    assert ("run-1", "tombstone-item") not in container.records


def run_all_tests():
    tests = [
        test_runtime_conflict_class_export,
        test_initialize_idempotency_and_tombstone_prevents_resurrection,
        test_claim_race_two_owners_and_same_owner_replay,
        test_expired_claim_fences_old_owner_and_increments_epoch,
        test_invalid_timestamp_fails_closed_for_claim_and_assert,
        test_heartbeat_preserves_state_and_public_version_after_cas_retry,
        test_stale_version_updates_are_rejected_and_units_require_guard,
        test_concurrent_decisions_stale_approval_and_identical_replay,
        test_invalid_choices_and_output_gate_cannot_be_approved,
        test_cancel_while_worker_active_fences_commit_and_prevents_zombie_requeue,
        test_identity_mismatch_is_rejected,
        test_finite_json_and_size_bounds,
        test_projection_excludes_tokens_raw_payloads_and_private_refs,
        test_retry_resume_preserves_completed_units,
        test_runtime_lease_context_releases_without_auto_queueing,
        test_runtime_lease_exit_allows_confirmed_tombstone_cleanup_only,
        test_write_record_fenced_batch_does_not_increment_public_version,
        test_write_record_retries_stale_control_etag_with_fresh_owned_check,
        test_write_record_immutable_conflict_verifies_exact_existing_payload,
        test_write_record_rejects_run_mismatch_stale_lease_and_tombstone,
    ]
    for test in tests:
        print(f"Running {test.__name__}...")
        test()
    print(f"Passed {len(tests)} workflow runtime journal tests.")


def test_runtime_conflict_class_export():
    assert runtime_store.WorkflowRuntimeConflict is runtime_store.RuntimeConflict
    conflict = runtime_store.WorkflowRuntimeConflict("test_conflict")
    assert conflict.code == "test_conflict"


if __name__ == "__main__":
    try:
        run_all_tests()
    except AssertionError as exc:
        print(f"Test failed: {exc}")
        sys.exit(1)
    except runtime_store.RuntimeConflict as exc:
        print(f"Unexpected RuntimeConflict: {exc.code}")
        sys.exit(1)
    sys.exit(0)
