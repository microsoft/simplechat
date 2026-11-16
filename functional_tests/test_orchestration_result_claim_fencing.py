# test_orchestration_result_claim_fencing.py
"""Cached producer tokens cannot bypass the current parent result-write epoch.

Version: 0.261.129
Implemented in: 0.261.129

Real leases, continuation claims, result-store views and conditional batches
run over the existing storage doubles. The lifecycle claim changes without
retagging retained producer identities, receipts or native child work.
"""

import importlib
from copy import deepcopy

import pytest

from test_orchestration_continuation import (
    claim, harness, initialized_continuation, result_epoch,  # noqa: F401
)


def unbound_store(harness, backend):
    module = importlib.import_module("functions_workflow_result_store")
    return module.WorkflowResultStore(
        harness.results.container, harness.blobs if backend == "blob" else None,
        "harness-chat" if backend == "blob" else None,
    )


def claim_result_view(harness, store):
    record, lease = claim(harness, mode="outputs")
    lease.start()
    scoped = harness.continuation.bind_orchestration_result_store(
        record, store=store, lease=lease,
    )
    return lease, scoped


@pytest.mark.parametrize("backend", ["cosmos", "blob"])
@pytest.mark.parametrize("require_guard", [False, True])
def test_cached_token_cannot_write_through_a_fresh_unbound_store(
    harness, result_epoch, backend, require_guard,
):
    data = result_epoch
    token = data.execution.lease.token
    data.execution.close()
    lease, current = claim_result_view(harness, data.base)
    raw = unbound_store(harness, backend)
    module = importlib.import_module("functions_workflow_result_store")
    rows = deepcopy(harness.results.container.items)
    blobs = deepcopy(harness.blobs.records)
    with pytest.raises(module.AnalysisWorkUnitConflictError):
        raw.save_orchestration(
            "owner", "conversation-1", "run-1", "prepare", {"stale": True},
            guard_token=token, require_analysis_guard=require_guard,
        )
    receipt = current.load_orchestration_result_receipt(data.producer, data.fingerprint)
    guard = current._analysis_guard(data.identity)
    assert lease.token == token and guard["token"] == token
    assert guard["execution_claim_id"] == lease.claim_id
    assert lease.claim_id != data.execution.lease.claim_id
    assert harness.results.container.items == rows and harness.blobs.records == blobs
    assert receipt is not None and len(harness.model_calls) == 1
    lease.close(release=True)


@pytest.mark.parametrize("backend", ["cosmos", "blob"])
@pytest.mark.parametrize("operation", ["payload", "checkpoint"])
def test_cached_lifecycle_batch_cannot_commit_after_same_token_epoch_adoption(
    harness, result_epoch, backend, operation,
):
    data = result_epoch
    data.execution.close()
    raw = unbound_store(harness, backend)
    old_lease, old_store = claim_result_view(harness, raw)
    old_guard = old_store._analysis_guard(data.identity)
    before = deepcopy(harness.results.container.items)
    batch_count = len(harness.results.container.batch_calls)
    takeover = {}

    def adopt_new_epoch():
        old_lease.close(release=True)
        lease, current = claim_result_view(harness, data.base)
        takeover.update(
            lease=lease, store=current, guard=current._analysis_guard(data.identity),
        )

    harness.results.container.before_batch = adopt_new_epoch
    try:
        with pytest.raises(harness.continuation.CheckpointError) as raised:
            if operation == "payload":
                old_store.save_orchestration(
                    "owner", "conversation-1", "run-1", "prepare", {"stale": True},
                    guard_token=old_lease.token,
                )
            else:
                old_store.write_analysis_checkpoint(
                    data.identity, "final", "stale-worker-result", {"status": "completed"},
                    token=old_lease.token,
                )
    finally:
        harness.results.container.before_batch = None

    batches = harness.results.container.batch_calls[batch_count:]
    current = takeover["store"]
    new_guard = takeover["guard"]
    receipt = current.load_orchestration_result_receipt(data.producer, data.fingerprint)
    pending = current.read_analysis_checkpoint(data.identity, "unit", "pending-unit")
    historical = data.base.load_orchestration_result_receipt(data.producer, data.fingerprint)
    assert raised.value.code == "ownership_lost"
    assert len(batches) == 1
    assert batches[0][0]["ifMatch"] == old_guard["_etag"]
    assert batches[0][0]["resourceBody"]["execution_claim_id"] == old_lease.claim_id
    assert new_guard["_etag"] != old_guard["_etag"]
    assert new_guard["token"] == old_guard["token"] == old_lease.token == takeover["lease"].token
    assert new_guard["execution_claim_id"] == takeover["lease"].claim_id != old_lease.claim_id
    assert set(harness.results.container.items) == set(before)
    for key, row in before.items():
        if row.get("record_kind") != "lifecycle":
            assert harness.results.container.items[key] == row
    assert receipt == historical and receipt is not None and pending == data.pending
    assert len(harness.model_calls) == 1 and harness.blobs.file_uploads == 0
    takeover["lease"].close(release=True)
