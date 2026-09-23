# test_orchestration_results.py
"""
M1 authorized retained-result persistence, complete readers, and lifecycle fences.
Version: 0.261.125
Implemented in: 0.261.125

Real contracts, facade, record trees, transport, source/screening checks and SDK-
formatted conditional batches run with external Cosmos/Blob/source I/O doubled.
"""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from content_screening.contracts import ScreeningError
from functions_generated_file_exports import GeneratedFileExportRequest, build_generated_file_export
from functions_orchestration_result_contracts import (
    InputBinding, InputSpec, RecordColumn, ResultContractError, ResultRef, TaskResult, canonical_bytes,
)
from functions_orchestration_results import NamedOutput, ResultUnavailableError, SavedAnalysisRecordSource
from functions_workflow_result_store import (
    ANALYSIS_CONTROL_RECORD_TYPE,
    ORCHESTRATION_RESULT_RECORD_TYPE,
    AnalysisWorkUnitConflictError,
    WorkflowResultIntegrityError,
    WorkflowResultStorageUnavailableError,
    _orchestration_identity,
)
from test_support.orchestration_results import COLUMNS, ROWS, ResultFixture, complete, native_analysis, source
from test_workflow_result_store import FakeBlob


def store_arguments(producer):
    return producer.user_id, producer.conversation_id, producer.run_id, producer.step_id


def commit_modified_manifest(fixture, reference, change):
    store = fixture.service.store
    args = store_arguments(reference.producer)
    manifest = store.load_committed_orchestration_result(*args, reference.manifest_sha256)
    change(manifest)
    stored = store.save_orchestration(
        *args, manifest, guard_token="server-attempt-token", require_analysis_guard=True,
    )
    store.commit_orchestration_result(*args, stored, guard_token="server-attempt-token")
    return replace(reference, manifest_sha256=stored["sha256"])


@pytest.mark.parametrize("blob", [False, True])
def test_full_restart_and_second_consumer_keep_original_records_and_schema(blob):
    fixture = ResultFixture(blob=blob)
    original = deepcopy(ROWS)
    task = fixture.save()
    descriptor = json.loads(json.dumps(task.to_dict()))
    restart = fixture.restart()
    first = restart.open_result(TaskResult.from_dict(descriptor).output("findings"))
    preview = first.preview(max_items=1)
    all_rows = list(first.iter_records())
    second = fixture.restart().open_result(ResultRef.from_dict(task.output("findings").to_dict()))
    second_rows = list(second.iter_records())
    assert first.kind == "records"
    assert first.record_count == 3
    assert first.columns == COLUMNS
    assert all_rows == second_rows == original
    assert all_rows[0]["id"] == "001" and all_rows[-1]["id"] == "last"
    assert list(all_rows[0]) == [column.name for column in COLUMNS]
    assert preview["preview"] is True and preview["integrity_verified"] is False
    assert preview["value"] == original[:1] and preview["truncated"] is True
    assert {row["type"] for row in fixture.container.items.values()} == {
        ANALYSIS_CONTROL_RECORD_TYPE, ORCHESTRATION_RESULT_RECORD_TYPE,
    }
    assert not any("role" in row or "is_generated_chat_artifact" in row for row in fixture.container.items.values())
    if blob:
        assert all(name.startswith("orchestration-analysis-results/") for _, name in fixture.blobs.records)


def test_30000_record_stream_exceeds_checkpoint_limit_without_losing_last_record():
    fixture = ResultFixture(blob=True)
    produced = []

    def rows():
        produced.append("called")
        for index in range(30000):
            yield {"id": f"{index:05}", "amount": index, "enabled": False, "detail": f"retained-{index} " + "x" * 320}

    task = fixture.save(grounded=False, outputs=[NamedOutput("rows", "records-v1", rows(), complete(30000), COLUMNS)])
    reference = task.output("rows")
    checkpoint = canonical_bytes(task.to_dict())
    reader = fixture.restart().open_result(TaskResult.from_dict(json.loads(checkpoint)).output("rows"))
    count, first, last = 0, None, None
    for record in reader.iter_records():
        if count == 0:
            first = record
        last = record
        count += 1
    second_reader = fixture.restart().open_result(reference)
    second_count = 0
    for record in second_reader.iter_records():
        second_count += 1
    assert produced == ["called"]
    assert count == second_count == 30000
    assert first["id"] == "00000" and last["id"] == "29999"
    assert last["detail"].startswith("retained-29999 ")
    assert reference.size_bytes > 8 * 1024 * 1024
    assert len(checkpoint) < 4096
    assert b"retained-29999" not in checkpoint
    assert max(len(row["data"]) for row in fixture.blobs.records.values()) <= 128 * 1024


@pytest.mark.parametrize("kind", ["text-v1", "markdown-v1", "structured-v1"])
def test_large_values_use_streamed_sections_and_bounded_previews(kind):
    fixture = ResultFixture(blob=True)
    text = "complete\u4e2d\u6587\n" * 600000
    value = text if kind != "structured-v1" else {"text": text, "last": "final-value"}
    task = fixture.save(grounded=False, outputs=[NamedOutput("prepared", kind, value, complete(1))])
    reader = fixture.restart().open_result(task.output("prepared"))
    preview = reader.preview(max_bytes=257)
    assert preview["truncated"] is True and preview["preview"] is True
    assert len(preview["value"].encode("utf-8")) <= 257
    read = reader.read_value if kind == "structured-v1" else reader.read_text
    if reader.reference.size_bytes > 8 * 1024 * 1024:
        with pytest.raises(ResultContractError, match="invalid"):
            read()
    if kind == "structured-v1":
        rebuilt = json.loads(b"".join(reader.iter_value_bytes()))
    else:
        rebuilt = "".join(reader.iter_text())
    assert rebuilt == value
    if kind != "structured-v1":
        assert reader.character_count == len(text)
    assert max(len(row["data"]) for row in fixture.blobs.records.values()) <= 128 * 1024


@pytest.mark.parametrize("kind,value", [
    ("records-v1", []), ("text-v1", ""), ("markdown-v1", ""), ("structured-v1", None),
])
def test_proven_empty_outputs_are_not_unavailable_or_default_success(kind, value):
    fixture = ResultFixture()
    count = 0 if kind == "records-v1" else 1
    task = fixture.save(grounded=False, outputs=[
        NamedOutput("empty", kind, value, complete(count), COLUMNS if kind == "records-v1" else ()),
    ])
    reader = fixture.restart().open_result(task.output("empty"))
    actual = list(reader.iter_records()) if kind == "records-v1" else (
        reader.read_text() if kind in {"text-v1", "markdown-v1"} else reader.read_value()
    )
    assert actual == value


@pytest.mark.parametrize("field,value", [
    ("user_id", "foreign"), ("conversation_id", "foreign-conversation"), ("run_id", "foreign-run"),
    ("step_id", "missing"), ("capability_id", "different"), ("attempt_index", 2),
])
def test_result_producer_owner_scope_and_attempt_mismatch_fail(field, value):
    fixture = ResultFixture()
    reference = fixture.save().output("findings")
    forged = replace(reference, producer=replace(reference.producer, **{field: value}))
    with pytest.raises((ResultUnavailableError, ResultContractError)):
        fixture.service.open_result(forged)


@pytest.mark.parametrize("change", ["deleted", "revoked", "scope", "revision", "version", "screening"])
def test_current_source_access_is_checked_on_consumption_not_only_save(change):
    fixture = ResultFixture()
    reference = fixture.save().output("findings")
    reader = fixture.service.open_result(reference)
    if change == "deleted":
        fixture.sources.clear()
    elif change == "revoked":
        fixture.denied.add("document-1")
    elif change == "scope":
        fixture.sources["document-1"].update(scope="group", scope_id="foreign-group")
    elif change == "revision":
        fixture.sources["document-1"]["source_revision"] = "revision-2"
    elif change == "version":
        fixture.sources["document-1"]["source_version"] = 2
    else:
        fixture.held.add("document-1")
    with pytest.raises((PermissionError, ScreeningError)):
        list(reader.iter_records())
    with pytest.raises((PermissionError, ScreeningError)):
        fixture.restart().open_result(reference)


def test_explicit_historical_snapshot_never_refreshes_or_hides_changes():
    fixture = ResultFixture()
    reference = fixture.save(source_policy="snapshot").output("findings")
    fixture.sources["document-1"]["source_revision"] = "changed-revision"
    reader = fixture.restart().open_result(reference)
    metadata = reader.metadata()
    rows = list(reader.iter_records())
    assert metadata["source_snapshot_changed"] is True
    assert metadata["source_policy"] == "snapshot" and rows == ROWS
    with pytest.raises(PermissionError):
        fixture.service.open_result(reference, require_current_sources=True)
    fixture.held.add("document-1")
    with pytest.raises((PermissionError, ScreeningError)):
        reader.recheck()


def test_current_source_content_digest_is_not_ignored():
    fixture = ResultFixture()
    snapshot = {**source(), "content_sha256": "a" * 64}
    fixture.sources["document-1"] = deepcopy(snapshot)
    task = fixture.service.persist_task_result(
        producer=fixture.producer, role="reason", status="complete",
        outputs=[NamedOutput("result", "records-v1", ROWS, complete(3), COLUMNS)],
        sources=[snapshot], origin="grounded", guard_token="server-attempt-token",
    )
    fixture.sources["document-1"]["content_sha256"] = "b" * 64
    with pytest.raises(PermissionError):
        fixture.service.open_result(task.output("result"))


@pytest.mark.parametrize("kind", ["source-set-v1", "evidence-set-v1"])
@pytest.mark.parametrize("field,value", [
    ("source_version", 2), ("source_revision", "unretained-revision"), ("content_sha256", "a" * 64),
])
def test_embedded_sources_must_match_the_exact_authorized_lineage_snapshot(kind, field, value):
    fixture = ResultFixture()
    forged = {**source(), field: value}
    item = forged if kind == "source-set-v1" else {
        "evidence_id": "evidence-1", "source": forged, "text": "A quote cannot change its source snapshot.",
    }
    with pytest.raises(ResultContractError) as error:
        fixture.save(outputs=[NamedOutput("sources", kind, [item], complete(1))])
    assert error.value.code == "result_source_not_in_lineage"
    assert not any(row.get("record_kind") == "final" for row in fixture.container.items.values())


@pytest.mark.parametrize("change", ["conversation_deleted", "owner_changed", "run_deleted", "disabled", "missing", "capability", "attempt"])
def test_current_producer_is_rechecked_after_open(change):
    fixture = ResultFixture()
    reader = fixture.service.open_result(fixture.save().output("findings"))
    run = fixture.runs["run-1"]
    if change == "conversation_deleted":
        fixture.conversation["orchestration_deleted"] = True
    elif change == "owner_changed":
        fixture.conversation["user_id"] = "foreign"
    elif change == "run_deleted":
        run["checkpoints_deleted"] = True
    elif change == "disabled":
        run["plan"]["steps"][0]["enabled"] = False
    elif change == "missing":
        run["plan"]["steps"] = []
    elif change == "capability":
        run["plan"]["steps"][0]["capability_id"] = "different"
    else:
        run["attempt_index"] = 2
    with pytest.raises(PermissionError):
        reader.preview()


@pytest.mark.parametrize("status", ["pending", "invalid", "failed", "cancelled", "unavailable"])
def test_unfinished_retained_data_is_not_a_success_shaped_input(status):
    fixture = ResultFixture()
    task = fixture.save(status=status, outputs=[
        NamedOutput("findings", "records-v1", [], complete(0, status=status, expected=3), COLUMNS),
    ])
    assert task.status == status
    with pytest.raises(ResultContractError):
        fixture.service.open_result(task.output("findings"), allow_partial=True)


def test_partial_requires_explicit_consumption_and_cannot_be_promoted_by_a_child():
    fixture = ResultFixture()
    task = fixture.save(status="partial", outputs=[
        NamedOutput("findings", "records-v1", ROWS[:2], complete(2, status="partial", expected=3), COLUMNS),
    ])
    reference = task.output("findings")
    with pytest.raises(ResultContractError):
        fixture.service.open_result(reference)
    reader = fixture.service.open_result(reference, allow_partial=True)
    actual = list(reader.iter_records())
    assert actual == ROWS[:2] and reader.completeness.status == "partial"
    consumer = fixture.consumer()
    with pytest.raises(ResultContractError):
        fixture.save(
            grounded=False, producer=consumer, upstream=(reference,), allow_partial_inputs=True,
            outputs=[NamedOutput("summary", "text-v1", "Only two of three rows.", complete(1))],
        )


def test_upstream_lineage_and_explicit_aliases_reauthorize_without_cross_attempt_rebinding():
    fixture = ResultFixture()
    task = fixture.save()
    consumer = fixture.consumer()
    spec = InputSpec("data", InputBinding("analyze", "findings"), ("records-v1",))
    reader = fixture.service.resolve_input(spec, consumer=consumer, task_results={"analyze": task})
    actual = list(reader.iter_records())
    assert actual == ROWS
    next_consumer = fixture.consumer(run_id="run-2", attempt_index=2)
    with pytest.raises(ResultContractError):
        fixture.service.resolve_input(spec, consumer=next_consumer, task_results={"analyze": task})
    alias = InputSpec("data", InputBinding(existing_result="saved_findings"), ("records-v1",))
    with pytest.raises(ResultContractError):
        fixture.service.resolve_input(alias, consumer=next_consumer, task_results={})
    with pytest.raises(ResultContractError) as error:
        fixture.service.resolve_input(
            alias, consumer=task.producer, task_results={},
            existing_results={"saved_findings": task.output("findings")},
        )
    assert error.value.code == "result_binding_cycle"
    reader = fixture.service.resolve_input(
        alias, consumer=next_consumer, task_results={}, existing_results={"saved_findings": task.output("findings")},
    )
    actual = list(reader.iter_records())
    assert actual == ROWS
    child = fixture.save(
        grounded=False, producer=consumer, upstream=(task.output("findings"),),
        outputs=[NamedOutput("draft", "text-v1", "Prepared from all original findings.", complete(1))],
    )
    fixture.denied.add("document-1")
    with pytest.raises(PermissionError):
        fixture.restart().open_result(child.output("draft"))


def test_result_references_never_select_caller_supplied_storage():
    fixture = ResultFixture()
    reference = fixture.save().output("findings")
    with pytest.raises(ResultContractError):
        ResultRef.from_dict({**reference.to_dict(), "storage": "blob", "blob_path": "foreign"})
    with pytest.raises(ResultContractError):
        fixture.service.open_result(reference.to_dict())
    uncommitted = fixture.service.store.save_orchestration(
        *store_arguments(reference.producer), {"private": "uncommitted"},
        guard_token="server-attempt-token", require_analysis_guard=True,
    )
    with pytest.raises(WorkflowResultIntegrityError):
        fixture.service.open_result(replace(reference, manifest_sha256=uncommitted["sha256"]))


def test_existing_exact_records_json_export_accepts_full_reader_without_a_new_profile():
    fixture = ResultFixture()
    reference = fixture.save().output("findings")
    reader = fixture.restart().open_result(reference)
    with build_generated_file_export(
        source=reader, export_request=GeneratedFileExportRequest("json"),
        max_output_bytes=1024 * 1024,
    ) as rendered:
        data = rendered.file_content.read()
        values = json.loads(data)
        count = rendered.record_count
        profile = rendered.profile
    assert values == ROWS and count == 3 and profile == "exact_records_v1"
    with pytest.raises(ValueError):
        build_generated_file_export(
            source=reader, export_request=GeneratedFileExportRequest("csv"),
            max_output_bytes=1024 * 1024,
        )


def test_declared_content_digest_and_record_count_are_verified_not_only_transport():
    fixture = ResultFixture()
    reference = fixture.save().output("findings")
    corrupt = commit_modified_manifest(
        fixture, reference, lambda manifest: manifest["outputs"]["findings"].update(content_sha256="0" * 64),
    )
    corrupt = replace(corrupt, content_sha256="0" * 64)
    reader = fixture.service.open_result(corrupt)
    with pytest.raises(ResultContractError) as failure:
        list(reader.iter_records())
    assert failure.value.code == "result_content_integrity"
    corrupt_count = commit_modified_manifest(
        fixture, reference, lambda manifest: manifest["outputs"]["findings"]["storage"].update(record_count=4),
    )
    with pytest.raises(ResultContractError) as failure:
        fixture.service.open_result(corrupt_count)
    assert failure.value.code == "result_count_invalid"


def test_missing_final_record_fails_even_with_valid_transport_digests():
    fixture = ResultFixture()
    reference = fixture.save().output("findings")
    store = fixture.service.store
    args = store_arguments(reference.producer)

    def drop_last(manifest):
        output = manifest["outputs"]["findings"]["storage"]
        index = store.load_orchestration(*args, output["result_ref"])
        leaf = index["value"]["children"][-1]
        page = store.load_orchestration(*args, leaf["result_ref"])
        page["value"].pop()
        leaf["result_ref"] = store.save_orchestration(
            *args, page, guard_token="server-attempt-token", require_analysis_guard=True,
        )
        output["result_ref"] = store.save_orchestration(
            *args, index, guard_token="server-attempt-token", require_analysis_guard=True,
        )

    corrupt = commit_modified_manifest(fixture, reference, drop_last)
    reader = fixture.service.open_result(corrupt)
    with pytest.raises(ValueError, match="count"):
        list(reader.iter_records())


def test_unavailable_blob_backend_is_not_an_empty_or_preview_fallback():
    fixture = ResultFixture(blob=True)
    reference = fixture.save().output("findings")
    unavailable = fixture.restart(blobs=False)
    with pytest.raises(WorkflowResultStorageUnavailableError):
        unavailable.open_result(reference)


@pytest.mark.parametrize("blob", [False, True])
def test_cleanup_keeps_tombstone_and_late_workers_cannot_recreate_results(blob):
    fixture = ResultFixture(blob=blob)
    reference = fixture.save().output("findings")
    fixture.service.store.delete_orchestration_results("owner", "conversation-1", "run-1")
    remaining = deepcopy(fixture.container.items)
    with pytest.raises(AnalysisWorkUnitConflictError):
        fixture.save()
    with pytest.raises(AnalysisWorkUnitConflictError):
        fixture.restart().open_result(reference)
    assert fixture.container.items == remaining
    assert len(remaining) == 1 and next(iter(remaining.values()))["deleted"] is True
    if blob:
        assert fixture.blobs.records == {}


def test_cancelled_fence_stops_writes_but_does_not_delete_completed_inputs():
    fixture = ResultFixture()
    reference = fixture.save().output("findings")
    identity = _orchestration_identity(*store_arguments(fixture.producer))
    fixture.service.store.cancel_analysis_attempt(identity, token="server-attempt-token")
    with pytest.raises(AnalysisWorkUnitConflictError):
        fixture.save()
    reader = fixture.restart().open_result(reference)
    records = list(reader.iter_records())
    assert records == ROWS


def test_deletion_during_blob_upload_cannot_commit_or_recreate_payload(monkeypatch):
    fixture = ResultFixture(blob=True)
    identity = _orchestration_identity(*store_arguments(fixture.producer))
    original = FakeBlob.upload_blob
    deleted = []

    def upload(blob, **kwargs):
        original(blob, **kwargs)
        if not deleted:
            fixture.service.store.fence_analysis_attempt(identity)
            deleted.append(True)

    monkeypatch.setattr(FakeBlob, "upload_blob", upload)
    with pytest.raises(AnalysisWorkUnitConflictError):
        fixture.save()
    assert deleted == [True]
    assert fixture.blobs.records == {}
    assert all(row["record_kind"] == "lifecycle" for row in fixture.container.items.values())


def test_cross_token_worker_cannot_write_after_owner_has_prepared():
    fixture = ResultFixture()
    fixture.service.store.prepare_orchestration_result(*store_arguments(fixture.producer), guard_token="new-owner-token")
    before = deepcopy(fixture.container.items)
    with pytest.raises(AnalysisWorkUnitConflictError):
        fixture.save()
    assert fixture.container.items == before


def test_evidence_sources_and_comparison_keep_distinct_full_kinds():
    fixture = ResultFixture()
    fixture.sources["document-2"] = source("document-2")
    sources = [source(), source("document-2")]
    value = {
        "left_document_id": "document-1", "right_document_ids": ["document-2"],
        "items": [{"right_document_id": "document-2", "right_document_name": "Second source", "text": "Prepared differences."}],
        "failed_document_ids": [],
    }
    task = fixture.service.persist_task_result(
        producer=fixture.producer, role="reason", status="complete", sources=sources,
        origin="grounded", guard_token="server-attempt-token",
        outputs=[
            NamedOutput("sources", "source-set-v1", sources, complete(2)),
            NamedOutput("evidence", "evidence-set-v1", [{"evidence_id": "e1", "source": source(), "text": "A source excerpt."}], complete(1)),
            NamedOutput("comparison", "comparison-v1", value, complete(1)),
        ],
    )
    restarted = fixture.restart()
    evidence = list(restarted.open_result(task.output("evidence")).iter_items())
    compared = restarted.open_result(task.output("comparison")).read_value()
    saved_sources = list(restarted.open_result(task.output("sources")).iter_items())
    assert evidence[0]["text"] == "A source excerpt."
    assert compared == value and saved_sources == sources
    with pytest.raises(ResultContractError):
        list(restarted.open_result(task.output("evidence")).iter_records())


def test_nonempty_comparison_error_prose_cannot_claim_a_complete_comparison():
    fixture = ResultFixture()
    fixture.sources["document-2"] = source("document-2")
    comparison = {
        "left_document_id": "document-1", "right_document_ids": ["document-2"],
        "items": [], "failed_document_ids": ["document-2"],
    }
    with pytest.raises(ResultContractError):
        fixture.service.persist_task_result(
            producer=fixture.producer, role="reason", status="complete", sources=list(fixture.sources.values()),
            origin="grounded", guard_token="server-attempt-token",
            outputs=[NamedOutput("comparison", "comparison-v1", comparison, complete(1))],
        )


def test_saved_analyze_adapter_uses_actual_saved_reader_preserving_evidence_and_sources():
    # The owning service is deliberately imported at this integration boundary,
    # never by the lower-level orchestration result modules.
    from functions_saved_analysis import load_orchestration_analysis_input, save_orchestration_analysis

    fixture = ResultFixture()
    native = native_analysis(150)
    store = fixture.service.store

    def authorize(user_id, binding):
        fixture.service.access.authorize_producer(fixture.producer)
        if user_id != fixture.producer.user_id or binding != {
            "kind": "orchestration", "user_id": "owner", "conversation_id": "conversation-1",
            "run_id": "run-1", "step_id": "analyze",
        }:
            raise PermissionError("Unexpected saved Analyze producer.")

    def save_result(user_id, conversation_id, run_id, step_id, value, *, settings):
        return store.save_orchestration(user_id, conversation_id, run_id, step_id, value)

    descriptor = save_orchestration_analysis(
        {"analysis_result": native}, **dict(zip(("user_id", "conversation_id", "run_id", "step_id"), store_arguments(fixture.producer))),
        settings={}, authorize_run=authorize, source_resolver=fixture.resolve, save_result=save_result,
    )
    restarted = fixture.restart()
    reader, _ = load_orchestration_analysis_input(
        "owner", descriptor, authorize_run=authorize, load_result=restarted.store.load_orchestration,
        source_resolver=fixture.resolve, bounded=True,
    )
    adapter = SavedAnalysisRecordSource(reader, columns=(RecordColumn("finding", "string"), RecordColumn("detail", "string")))
    values = list(adapter.iter_records())
    units = list(adapter.iter_units())
    metadata = adapter.metadata()
    assert len(values) == 150 and values[-1]["finding"] == "Complete finding 149"
    assert units[-1]["record"]["record_id"] == "record-149"
    assert units[-1]["evidence"][0]["quote"] == "Source quote 149"
    assert metadata["sources"] == [source()] and metadata["coverage"] == native["coverage"]
    assert "original_sources_reanalyzed" in metadata and metadata["original_sources_reanalyzed"] is False
    fixture.denied.add("document-1")
    with pytest.raises(PermissionError):
        list(adapter.iter_records())
