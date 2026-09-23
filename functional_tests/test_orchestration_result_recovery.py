# test_orchestration_result_recovery.py
"""
Native resumed guards and exact committed-result recovery for orchestration.
Version: 0.261.125
Implemented in: 0.261.125

Exercise real checkpoint/transport/facade APIs with external I/O doubled.
The parent integration owns the next application version increment.
"""

from copy import deepcopy
from dataclasses import replace

import pytest
from azure.cosmos.exceptions import CosmosBatchOperationError

from content_screening.contracts import ScreeningError
from functions_document_analysis_checkpoints import analysis_checkpoints_for_orchestration
from functions_orchestration_result_contracts import (
    RESULT_MANIFEST_VERSION,
    RESULT_RECEIPT_VERSION,
    TASK_RESULT_VERSION,
    InputBinding,
    InputSpec,
    ResultContractError,
    canonical_bytes,
    canonical_digest,
)
from functions_orchestration_results import NamedOutput, ResultUnavailableError
from functions_workflow_result_store import (
    AnalysisWorkUnitConflictError,
    OrchestrationResultConflictError,
    WorkflowResultIntegrityError,
    WorkflowResultStorageUnavailableError,
)
from test_support.orchestration_results import COLUMNS, ROWS, ResultFixture, complete, source
from test_support.versioning import assert_app_version_at_least


def native_checkpoints(fixture, producer, *, previous=None):
    return analysis_checkpoints_for_orchestration(
        producer.user_id, producer.conversation_id, producer.run_id, producer.step_id,
        store=fixture.service.store, resume_run_id=previous,
        authorize=lambda: fixture.service.access.authorize_producer(producer, for_write=True),
        source_authorizer=lambda user_id, sources, require_snapshot: (
            fixture.service.access.authorize_sources(sources, require_snapshot=require_snapshot)
        ),
    )


INPUT_FINGERPRINT = "a" * 64


def test_recovery_foundation_version():
    assert_app_version_at_least("0.261.125")


def persist_native_output(fixture, producer, checkpoints, **changes):
    options = {
        "producer": producer, "role": "reason", "status": "complete",
        "outputs": [NamedOutput("findings", "records-v1", deepcopy(ROWS), complete(3), COLUMNS)],
        "sources": [source()], "origin": "grounded", "guard_token": checkpoints.token,
    }
    return fixture.service.persist_task_result(**{**options, **changes})


@pytest.mark.parametrize("blob", [False, True])
def test_resumed_native_work_and_generic_results_share_the_owning_guard(blob):
    fixture = ResultFixture(blob=blob)
    first = native_checkpoints(fixture, fixture.producer)
    request = {"operation": "analyze", "documents": ["document-1"]}
    unit = {"work_unit_id": "window-1", "source": source(), "status": "completed"}
    first.prepare()
    first.initialize(request, [source()])
    first.source_loaded(source())
    claim = first.claim_unit(unit)
    first.commit_unit(claim, unit, {"findings": ROWS}, "Retained native findings.")
    first.cancel(reason="failed")

    resumed_producer = replace(fixture.producer, run_id="run-2", attempt_index=2)
    fixture.add_producer(resumed_producer)
    resumed = native_checkpoints(fixture, resumed_producer, previous="run-1")
    resumed.prepare()
    resumed.initialize(request, [source()])
    restored_unit = resumed.load_unit(unit)
    assert restored_unit["candidate_result"]["findings"] == ROWS
    before = fixture.service.store._analysis_guard(resumed.binding, required=True)

    task = persist_native_output(fixture, resumed_producer, resumed)
    after = fixture.service.store._analysis_guard(resumed.binding, required=True)
    for key in ("resume_from", "token", "request_digest", "request_registered", "source_snapshot_digest"):
        assert after[key] == before[key]
    assert after["resume_from"] == first.binding
    rows = list(fixture.restart().open_result(task.output("findings")).iter_records())
    assert rows == ROWS
    with pytest.raises(AnalysisWorkUnitConflictError):
        persist_native_output(fixture, fixture.producer, first)

    competitor = native_checkpoints(fixture, resumed_producer, previous="run-1")
    with pytest.raises(AnalysisWorkUnitConflictError):
        persist_native_output(fixture, resumed_producer, competitor)
    resumed.cancel()
    with pytest.raises(AnalysisWorkUnitConflictError):
        persist_native_output(fixture, resumed_producer, resumed)
    retained = list(fixture.restart().open_result(task.output("findings")).iter_records())
    assert retained == ROWS
    fixture.service.store.delete_orchestration_results("owner", "conversation-1", "run-2")
    with pytest.raises(AnalysisWorkUnitConflictError):
        persist_native_output(fixture, resumed_producer, resumed)
    with pytest.raises(AnalysisWorkUnitConflictError):
        fixture.restart().open_result(task.output("findings"))


@pytest.mark.parametrize("blob", [False, True])
def test_crash_after_commit_recovers_exact_original_before_any_checkpoint(blob, monkeypatch):
    fixture = ResultFixture(blob=blob)
    producer = fixture.producer
    missing = fixture.service.recover_task_result(producer=producer, input_fingerprint=INPUT_FINGERPRINT)
    assert missing is None
    checkpoints = native_checkpoints(fixture, producer)
    checkpoints.prepare()
    original_commit = fixture.service.store.commit_orchestration_result

    def commit_then_crash(*args, **kwargs):
        original_commit(*args, **kwargs)
        raise RuntimeError("Injected crash before the runtime captures the result descriptor.")

    with monkeypatch.context() as scoped:
        scoped.setattr(fixture.service.store, "commit_orchestration_result", commit_then_crash)
        with pytest.raises(RuntimeError, match="Injected crash"):
            persist_native_output(fixture, producer, checkpoints, input_fingerprint=INPUT_FINGERPRINT)
    fixture.runs["run-1"]["status"] = "failed"
    fixture.runs["run-1"]["latest_attempt_run_id"] = "retry-after-sibling-failure"
    checkpoints.cancel(reason="failed")
    restart = fixture.restart()
    recovered = restart.recover_task_result(producer=producer, input_fingerprint=INPUT_FINGERPRINT)
    recovered_again = fixture.restart().recover_task_result(producer=producer, input_fingerprint=INPUT_FINGERPRINT)
    rows = list(restart.open_result(recovered.output("findings")).iter_records())
    assert recovered == recovered_again
    assert rows == ROWS and rows[0]["id"] == "001" and rows[-1]["id"] == "last"
    assert recovered.producer == producer
    assert fixture.container.queries == []
    next_producer = fixture.consumer(run_id="run-2", attempt_index=2)
    direct = InputSpec("data", InputBinding("analyze", "findings"), ("records-v1",))
    with pytest.raises(ResultContractError):
        restart.resolve_input(direct, consumer=next_producer, task_results={"analyze": recovered})
    alias = InputSpec("data", InputBinding(existing_result="prior_result"), ("records-v1",))
    reader = restart.resolve_input(
        alias, consumer=next_producer, task_results={},
        existing_results={"prior_result": recovered.output("findings")},
    )
    retained = list(reader.iter_records())
    assert retained == ROWS


def test_receipt_and_digest_commit_are_atomic_and_retry_does_not_pick_a_partial_commit(monkeypatch):
    fixture = ResultFixture()
    checkpoints = native_checkpoints(fixture, fixture.producer)
    checkpoints.prepare()
    store = fixture.service.store
    original_write = store._write_analysis_record

    def fail_companion(identity, record, **kwargs):
        if record.get("key", "").startswith(RESULT_RECEIPT_VERSION):
            fixture.container.fail_batch_at = 2
        try:
            return original_write(identity, record, **kwargs)
        finally:
            fixture.container.fail_batch_at = None

    with monkeypatch.context() as scoped:
        scoped.setattr(store, "_write_analysis_record", fail_companion)
        with pytest.raises(CosmosBatchOperationError):
            persist_native_output(fixture, fixture.producer, checkpoints, input_fingerprint=INPUT_FINGERPRINT)
    final_rows = [row for row in fixture.container.items.values() if row.get("record_kind") == "final"]
    missing = fixture.restart().recover_task_result(producer=fixture.producer, input_fingerprint=INPUT_FINGERPRINT)
    assert final_rows == [] and missing is None
    saved = persist_native_output(fixture, fixture.producer, checkpoints, input_fingerprint=INPUT_FINGERPRINT)
    recovered = fixture.restart().recover_task_result(producer=fixture.producer, input_fingerprint=INPUT_FINGERPRINT)
    assert recovered == saved


def test_same_input_receipt_is_immutable_not_latest_result_wins():
    fixture = ResultFixture()
    checkpoints = native_checkpoints(fixture, fixture.producer)
    saved = persist_native_output(fixture, fixture.producer, checkpoints, input_fingerprint=INPUT_FINGERPRINT)
    repeated = persist_native_output(fixture, fixture.producer, checkpoints, input_fingerprint=INPUT_FINGERPRINT)
    assert repeated == saved
    changed = [NamedOutput("findings", "records-v1", ROWS[:1], complete(1), COLUMNS)]
    with pytest.raises(OrchestrationResultConflictError):
        persist_native_output(
            fixture, fixture.producer, checkpoints, input_fingerprint=INPUT_FINGERPRINT, outputs=changed,
        )
    original = fixture.restart().recover_task_result(producer=fixture.producer, input_fingerprint=INPUT_FINGERPRINT)
    other = persist_native_output(
        fixture, fixture.producer, checkpoints, input_fingerprint="b" * 64, outputs=changed,
    )
    exact_other = fixture.restart().recover_task_result(producer=fixture.producer, input_fingerprint="b" * 64)
    assert original == saved and exact_other == other and other != saved


def test_racing_receipt_writers_return_one_winner_not_an_ambiguous_catalog(monkeypatch):
    fixture = ResultFixture()
    checkpoints = native_checkpoints(fixture, fixture.producer)
    original_write = fixture.service.store._write_analysis_record
    raced = []
    winner = []

    def commit_competitor():
        winner.append(persist_native_output(
            fixture, fixture.producer, checkpoints, input_fingerprint=INPUT_FINGERPRINT,
        ))

    def race(identity, record, **kwargs):
        if record.get("key", "").startswith(RESULT_RECEIPT_VERSION) and not raced:
            raced.append(True)
            fixture.container.before_batch = commit_competitor
        return original_write(identity, record, **kwargs)

    monkeypatch.setattr(fixture.service.store, "_write_analysis_record", race)
    with pytest.raises(OrchestrationResultConflictError):
        persist_native_output(
            fixture, fixture.producer, checkpoints, input_fingerprint=INPUT_FINGERPRINT,
            outputs=[NamedOutput("findings", "records-v1", ROWS[:1], complete(1), COLUMNS)],
        )
    recovered = fixture.restart().recover_task_result(producer=fixture.producer, input_fingerprint=INPUT_FINGERPRINT)
    assert recovered == winner[0]
    receipts = [
        row for row in fixture.container.items.values()
        if row.get("key", "").startswith(RESULT_RECEIPT_VERSION)
    ]
    assert len(receipts) == 1


def test_unused_extensions_preserve_published_v1_bytes_and_optional_fingerprints():
    default_fixture = ResultFixture()
    default = default_fixture.save()
    explicit = ResultFixture().save(input_fingerprint=None, external_sources=())
    reference = default.output("findings")
    manifest = default_fixture.service.store.load_committed_orchestration_result(
        "owner", "conversation-1", "run-1", "analyze", reference.manifest_sha256,
    )
    # Captured from the complete published facade in commit 18fc08ac, not a
    # reimplementation of its serializer or a value tied to the app version.
    assert reference.manifest_sha256 == "a1a6021aa32908a7c4657ebeb8c4a005a379cddbc809dd990710f110c8948fd6"
    assert canonical_digest(default.to_dict()) == "42bbe2b028fa4f3298f980b18398532fb3b535551ae60ce23821a8118221d9ce"
    assert len(canonical_bytes(default.to_dict())) == 1281
    assert explicit == default and manifest["version"] == TASK_RESULT_VERSION
    assert "input_fingerprint" not in manifest and "version" not in manifest["lineage"]
    missing = default_fixture.service.recover_task_result(
        producer=default_fixture.producer, input_fingerprint=INPUT_FINGERPRINT,
    )
    assert missing is None


@pytest.mark.parametrize("status", ["pending", "invalid", "failed", "cancelled", "unavailable"])
def test_pending_jobs_and_unusable_results_never_create_terminal_receipts(status):
    fixture = ResultFixture()
    checkpoints = native_checkpoints(fixture, fixture.producer)
    with pytest.raises(ResultContractError):
        persist_native_output(
            fixture, fixture.producer, checkpoints, status=status, input_fingerprint=INPUT_FINGERPRINT,
            outputs=[NamedOutput("findings", "records-v1", [], complete(0, status=status, expected=3), COLUMNS)],
        )
    assert fixture.container.items == {}


def test_recovery_retains_partial_state_and_requires_explicit_partial_read():
    fixture = ResultFixture()
    checkpoints = native_checkpoints(fixture, fixture.producer)
    saved = persist_native_output(
        fixture, fixture.producer, checkpoints, status="partial", input_fingerprint=INPUT_FINGERPRINT,
        outputs=[NamedOutput("findings", "records-v1", ROWS[:1], complete(1, status="partial", expected=3), COLUMNS)],
    )
    recovered = fixture.restart().recover_task_result(producer=fixture.producer, input_fingerprint=INPUT_FINGERPRINT)
    assert recovered == saved and recovered.status == "partial"
    with pytest.raises(ResultContractError):
        fixture.service.open_result(recovered.output("findings"))
    reader = fixture.service.open_result(recovered.output("findings"), allow_partial=True)
    rows = list(reader.iter_records())
    assert rows == ROWS[:1] and reader.completeness.limitations


def test_partial_task_receipt_preserves_unreadable_failure_output_without_promoting_it():
    fixture = ResultFixture()
    checkpoints = native_checkpoints(fixture, fixture.producer)
    saved = persist_native_output(
        fixture, fixture.producer, checkpoints, status="partial", input_fingerprint=INPUT_FINGERPRINT,
        outputs=[
            NamedOutput("retained", "records-v1", ROWS, complete(3), COLUMNS),
            NamedOutput("failed", "records-v1", [], complete(0, status="failed", expected=1), COLUMNS),
        ],
    )
    recovered = fixture.restart().recover_task_result(producer=fixture.producer, input_fingerprint=INPUT_FINGERPRINT)
    assert recovered == saved and recovered.status == "partial"
    with pytest.raises(ResultContractError):
        fixture.service.open_result(recovered.output("failed"), allow_partial=True)


@pytest.mark.parametrize("change", ["source_deleted", "screening", "revision", "owner", "scope", "attempt", "cleanup"])
def test_receipt_recovery_reauthorizes_current_source_and_producer_state(change):
    fixture = ResultFixture()
    checkpoints = native_checkpoints(fixture, fixture.producer)
    persist_native_output(fixture, fixture.producer, checkpoints, input_fingerprint=INPUT_FINGERPRINT)
    if change == "source_deleted":
        fixture.sources.clear()
    elif change == "screening":
        fixture.held.add("document-1")
    elif change == "revision":
        fixture.sources["document-1"]["source_revision"] = "new-revision"
    elif change == "owner":
        fixture.conversation["user_id"] = "foreign"
    elif change == "scope":
        fixture.sources["document-1"].update(scope="group", scope_id="foreign-group")
    elif change == "attempt":
        fixture.runs["run-1"]["attempt_index"] = 2
    else:
        fixture.service.store.delete_orchestration_results("owner", "conversation-1", "run-1")
    with pytest.raises((PermissionError, ScreeningError, AnalysisWorkUnitConflictError)):
        fixture.restart().recover_task_result(producer=fixture.producer, input_fingerprint=INPUT_FINGERPRINT)


@pytest.mark.parametrize("change", [
    "fingerprint", "producer", "coerced_attempt", "reference", "missing_guard", "missing_commit",
])
def test_corrupt_or_incomplete_receipt_is_not_reported_as_missing(change):
    fixture = ResultFixture()
    checkpoints = native_checkpoints(fixture, fixture.producer)
    persist_native_output(fixture, fixture.producer, checkpoints, input_fingerprint=INPUT_FINGERPRINT)
    rows = fixture.container.items
    receipt = next(row for row in rows.values() if row.get("key", "").startswith(RESULT_RECEIPT_VERSION))
    if change == "fingerprint":
        receipt["binding"]["input_fingerprint"] = "b" * 64
    elif change == "producer":
        receipt["binding"]["producer"]["user_id"] = "foreign"
    elif change == "coerced_attempt":
        receipt["binding"]["producer"]["attempt_index"] = True
    elif change == "reference":
        receipt["reference"]["size_bytes"] += 1
    else:
        kind = "lifecycle" if change == "missing_guard" else "final"
        key = next(
            key for key, row in rows.items()
            if row.get("record_kind") == kind and not row.get("key", "").startswith(RESULT_RECEIPT_VERSION)
        )
        del rows[key]
    with pytest.raises((WorkflowResultIntegrityError, AnalysisWorkUnitConflictError)):
        fixture.restart().recover_task_result(producer=fixture.producer, input_fingerprint=INPUT_FINGERPRINT)


def test_receipt_preserves_named_output_order_and_rejects_foreign_lookup_before_storage():
    fixture = ResultFixture()
    checkpoints = native_checkpoints(fixture, fixture.producer)
    saved = persist_native_output(
        fixture, fixture.producer, checkpoints, input_fingerprint=INPUT_FINGERPRINT,
        outputs=[
            NamedOutput("z_text", "text-v1", "First named output.", complete(1)),
            NamedOutput("a_data", "structured-v1", {"last": True}, complete(1)),
        ],
    )
    recovered = fixture.restart().recover_task_result(producer=fixture.producer, input_fingerprint=INPUT_FINGERPRINT)
    assert recovered == saved
    assert tuple(reference.output_name for reference in recovered.outputs) == ("z_text", "a_data")
    fixture.container.fail_reads = True
    with pytest.raises(ResultUnavailableError):
        fixture.service.recover_task_result(
            producer=replace(fixture.producer, user_id="foreign"), input_fingerprint=INPUT_FINGERPRINT,
        )


def test_receipt_recovery_exhausts_data_integrity_checks_and_never_falls_back():
    fixture = ResultFixture(blob=True)
    checkpoints = native_checkpoints(fixture, fixture.producer)
    task = persist_native_output(fixture, fixture.producer, checkpoints)
    store = fixture.service.store
    args = ("owner", "conversation-1", "run-1", "analyze")
    manifest = store.load_committed_orchestration_result(*args, task.output("findings").manifest_sha256)
    manifest.update(
        version=RESULT_MANIFEST_VERSION, input_fingerprint=INPUT_FINGERPRINT, output_order=list(manifest["outputs"]),
    )
    manifest["outputs"]["findings"]["content_sha256"] = "0" * 64
    stored = store.save_orchestration(*args, manifest, guard_token=checkpoints.token, require_analysis_guard=True)
    store.commit_orchestration_result(
        *args, stored, guard_token=checkpoints.token, producer=fixture.producer, input_fingerprint=INPUT_FINGERPRINT,
    )
    with pytest.raises(ResultContractError) as error:
        fixture.restart().recover_task_result(producer=fixture.producer, input_fingerprint=INPUT_FINGERPRINT)
    assert error.value.code == "result_content_integrity"
    with pytest.raises(WorkflowResultStorageUnavailableError):
        fixture.restart(blobs=False).recover_task_result(producer=fixture.producer, input_fingerprint=INPUT_FINGERPRINT)


@pytest.mark.parametrize("stop", ["cancel", "delete"])
def test_receipt_commit_loses_native_cas_when_cancellation_or_deletion_wins(stop, monkeypatch):
    fixture = ResultFixture()
    checkpoints = native_checkpoints(fixture, fixture.producer)
    original_write = fixture.service.store._write_analysis_record

    def race_stop(identity, record, **kwargs):
        if record.get("key", "").startswith(RESULT_RECEIPT_VERSION):
            fixture.container.before_batch = (
                checkpoints.cancel if stop == "cancel"
                else lambda: fixture.service.store.fence_analysis_attempt(identity)
            )
        return original_write(identity, record, **kwargs)

    monkeypatch.setattr(fixture.service.store, "_write_analysis_record", race_stop)
    with pytest.raises(AnalysisWorkUnitConflictError):
        persist_native_output(fixture, fixture.producer, checkpoints, input_fingerprint=INPUT_FINGERPRINT)
    assert not any(row.get("record_kind") == "final" for row in fixture.container.items.values())
    with pytest.raises(AnalysisWorkUnitConflictError):
        persist_native_output(fixture, fixture.producer, checkpoints, input_fingerprint=INPUT_FINGERPRINT)
