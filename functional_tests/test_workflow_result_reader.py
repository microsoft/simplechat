# test_workflow_result_reader.py
"""
Functional test for the workflow result reader behind chat Follow up.
Version: 0.261.231
Implemented in: 0.261.214
Results stopped re-checking their sources in: 0.261.231

This test ensures that the reader point-reads a personal workflow and run as the
requester, answers someone else's run exactly like a missing one, reads only
finished runs, verifies the whole run's lineage with the real run-history guard,
binds the result to a digest of its included outputs, and returns bounded
excerpts that never carry store references. The documents a run read are
provenance and are not re-checked. It uses fake containers and an in-memory
canonical result store; the result contract, the authorizer and the Analyze
reader are real.
"""

import json
import re
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

import functions_workflow_result_masking as masking  # noqa: E402
import functions_workflow_result_reader as reader  # noqa: E402
from functions_analysis_access import AnalysisResultUnavailable  # noqa: E402
from functions_saved_analysis import SavedAnalysisInput  # noqa: E402
from functions_workflow_result_store import WorkflowResultStorageUnavailableError  # noqa: E402
from functions_workflow_results import authorize_workflow_run_read  # noqa: E402
from functions_workflow_runtime_store import RESUMABLE_STATES, TERMINAL_STATES  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_result_chat import (  # noqa: E402
    COMPLETED_AT,
    EXPECTED_QUERY,
    OTHER_USER,
    RUN_ID,
    SECOND_SOURCE,
    USER,
    WORKFLOW_ID,
    RunFixture,
    accepted_partial,
    analysis_result,
    canonical,
    closed,
    projected_fields,
    two_text_tasks,
)


def test_version_is_at_least_the_workflow_results_release():
    assert_app_version_at_least("0.261.214")


def test_a_finished_run_reads_as_its_owner_with_a_public_descriptor():
    fixture = RunFixture()
    two_text_tasks(fixture)
    fixture.reset_counters()

    result = fixture.read()

    descriptor = result["descriptor"]
    assert set(descriptor) == {
        "version", "workflow_id", "run_id", "workflow_name", "status", "completed_at", "result_sha256", "available",
    }
    assert descriptor["version"] == "workflow-result-v1"
    assert descriptor["workflow_id"] == WORKFLOW_ID and descriptor["run_id"] == RUN_ID
    assert descriptor["workflow_name"] == "Weekly digest"
    assert descriptor["status"] == "completed"
    assert descriptor["completed_at"] == COMPLETED_AT
    assert re.fullmatch(r"[0-9a-f]{64}", descriptor["result_sha256"])
    assert descriptor["available"] is True
    assert result["excerpts"] == [] and result["saved_inputs"] == []
    assert result["output_count"] == 2 and result["partial"] is False
    stored_digests = {item["workflow_result"]["result_ref"]["sha256"] for item in fixture.items}
    assert set(fixture.store.loads) == stored_digests
    assert fixture.store.pages == []
    exposed = json.dumps(descriptor)
    assert "result_ref" not in exposed
    assert not any(digest in exposed for digest in stored_digests)
    assert fixture.containers["workflows"].reads == [(WORKFLOW_ID, USER)]
    assert fixture.containers["runs"].reads == [(RUN_ID, USER)]


def test_excerpts_put_the_final_output_first_and_carry_no_store_references():
    fixture = RunFixture()
    fixture.add_task("task-collect-71", {"reply": "Collected three headlines."}, order=1, label="Collect news")
    fixture.add_task("task-rank-73", {
        "reply": "Ranked.", "authoritative_result": {"kind": "records", "value": [{"rank": 1, "headline": "Rates"}]},
    }, order=2, label="Rank headlines")
    fixture.add_task("task-summary-72", {
        "reply": "Summary.", "authoritative_result": {"kind": "json", "value": {"top": "Rates", "count": 3}},
    }, order=3, label="Write the digest")

    result = fixture.read(include_excerpts=True)

    excerpts = result["excerpts"]
    assert [excerpt["label"] for excerpt in excerpts] == ["Write the digest", "Collect news", "Rank headlines"]
    assert [excerpt["final"] for excerpt in excerpts] == [True, False, False]
    assert [excerpt["kind"] for excerpt in excerpts] == ["json", "text", "records"]
    assert json.loads(excerpts[0]["text"]) == {"top": "Rates", "count": 3}
    assert excerpts[1]["text"] == "Collected three headlines."
    assert json.loads(excerpts[2]["text"]) == {"rank": 1, "headline": "Rates"}
    assert all(set(excerpt) == {"label", "kind", "final", "text", "truncated", "note"} for excerpt in excerpts)
    assert result["truncated"] is False and result["omitted_outputs"] == 0
    exposed = json.dumps(excerpts)
    for item in fixture.items:
        assert item["workflow_result"]["result_ref"]["sha256"] not in exposed
        assert item["task_id"] not in exposed
    assert WORKFLOW_ID not in exposed and RUN_ID not in exposed and "ITEM-PREVIEW-TEXT" not in exposed


@pytest.mark.parametrize("scenario", [
    "missing_workflow", "missing_run", "another_users_run", "run_of_another_workflow",
    "group_workflow", "deleting_workflow", "group_run", "malformed_ids",
])
def test_someone_elses_or_a_missing_run_reads_exactly_like_not_found(scenario):
    fixture = RunFixture()
    two_text_tasks(fixture)
    fixture.reset_counters()
    user_id, workflow_id, run_id = USER, WORKFLOW_ID, RUN_ID
    if scenario == "missing_workflow":
        fixture.containers["workflows"].documents.clear()
    elif scenario == "missing_run":
        fixture.containers["runs"].documents.clear()
    elif scenario == "another_users_run":
        user_id = OTHER_USER
    elif scenario == "run_of_another_workflow":
        fixture.run["workflow_id"] = "wf-other-5"
    elif scenario == "group_workflow":
        fixture.workflow["group_id"] = "group-9"
    elif scenario == "deleting_workflow":
        fixture.workflow["deleting"] = True
    elif scenario == "group_run":
        fixture.run["group_id"] = "group-9"
    else:
        workflow_id = "../wf digest"

    error = closed(lambda: fixture.read(user_id=user_id, workflow_id=workflow_id, run_id=run_id))

    baseline = RunFixture()
    baseline.containers["runs"].documents.clear()
    missing = closed(baseline.read)
    assert error.code == "workflow_result_not_found" and error.status == 404
    assert reader.workflow_result_error_payload(error) == reader.workflow_result_error_payload(missing)
    assert WORKFLOW_ID not in error.message and RUN_ID not in error.message
    assert fixture.store.loads == []
    assert fixture.containers["run_items"].queries == []


def _partition_blind(container):
    """A read path that lost its partition scope: the id alone picks the document."""
    def read_item(item, partition_key):
        container.reads.append((item, partition_key))
        for document in container.documents:
            if document.get("id") == item:
                return {**deepcopy(document), "_etag": "etag-1", "_ts": 1}
        raise CosmosResourceNotFoundError(status_code=404, message="missing")

    container.read_item = read_item


@pytest.mark.parametrize("blind", ["workflows", "runs"])
def test_each_owner_comparison_holds_if_a_read_ever_loses_its_partition_scope(blind):
    """The point reads in the requester's partition are the owner check, and the
    stored user_id is compared again. If a later read path ignored the partition, a
    cross-partition lookup by id for example, neither someone else's workflow nor
    someone else's run may pair with the requester's own documents."""
    fixture = RunFixture()
    two_text_tasks(fixture)
    if blind == "workflows":
        # The requester's own run names the owner's workflow id.
        fixture.containers["runs"].documents.append({**fixture.run, "user_id": OTHER_USER})
    else:
        # The requester's own workflow shares the owner's workflow id.
        fixture.containers["workflows"].documents.append({**fixture.workflow, "user_id": OTHER_USER})
    _partition_blind(fixture.containers[blind])
    fixture.reset_counters()

    error = closed(lambda: fixture.read(user_id=OTHER_USER))

    assert error.code == "workflow_result_not_found" and error.status == 404
    assert fixture.store.loads == []
    assert fixture.containers["run_items"].queries == []


@pytest.mark.parametrize("status,code", [
    ("completed", None), ("completed_partial", None),
    ("failed", "workflow_result_not_finished"), ("invalid", "workflow_result_not_finished"),
    ("incomplete", "workflow_result_not_finished"), ("cancelled", "workflow_result_not_finished"),
    ("skipped", "workflow_result_not_finished"),
    ("queued", "workflow_result_in_progress"), ("running", "workflow_result_in_progress"),
    ("pending", "workflow_result_in_progress"), ("", "workflow_result_in_progress"),
    (None, "workflow_result_in_progress"),
])
def test_only_completed_runs_are_readable(status, code):
    fixture = RunFixture(status=status)
    two_text_tasks(fixture)
    fixture.reset_counters()
    if code is None:
        result = fixture.read()
        assert result["descriptor"]["status"] == status
        return
    error = closed(fixture.read)
    assert error.code == code and error.status == 409
    assert fixture.store.loads == []


def test_status_families_cover_every_terminal_run_state():
    assert reader.READABLE_RUN_STATUSES | reader.UNFINISHED_RUN_STATUSES == TERMINAL_STATES
    assert not reader.READABLE_RUN_STATUSES & reader.UNFINISHED_RUN_STATUSES
    # A readable run can't be resumed in place; the digest still guards any rewrite.
    assert RESUMABLE_STATES <= reader.UNFINISHED_RUN_STATUSES


@pytest.mark.parametrize("variant", [
    "workflow_definition_v3", "run_definition_v3", "runtime_schema_2", "workflow_outputs", "v2_task_result",
])
def test_structured_runs_are_closed_until_exact_node_selectors_are_supported(variant):
    fixture = RunFixture()
    two_text_tasks(fixture)
    fixture.reset_counters()
    if variant == "workflow_definition_v3":
        fixture.workflow["definition_version"] = 3
    elif variant == "run_definition_v3":
        fixture.run["definition_version"] = 3
    elif variant == "runtime_schema_2":
        fixture.run["runtime"] = {"schema_version": 2}
    elif variant == "workflow_outputs":
        fixture.run["workflow_outputs"] = {"digest": "value"}
    else:
        fixture.items[0]["workflow_result"]["contract_version"] = "workflow-result-v2"

    error = closed(fixture.read)

    assert error.code == "workflow_result_unsupported" and error.status == 409
    assert fixture.store.loads == []


@pytest.mark.parametrize("variant", ["no_rows", "no_result_refs", "only_failed_rows_have_refs"])
def test_runs_without_a_durable_result_are_preview_only(variant):
    fixture = RunFixture()
    two_text_tasks(fixture)
    if variant == "no_rows":
        fixture.items.clear()
    elif variant == "no_result_refs":
        for item in fixture.items:
            item["workflow_result"] = {}
    else:
        for item in fixture.items:
            item["status"] = "failed"
    fixture.reset_counters()

    error = closed(fixture.read)

    assert error.code == "workflow_result_preview_only" and error.status == 409
    assert fixture.store.loads == []


def test_too_many_or_duplicate_task_rows_are_invalid():
    fixture = RunFixture()
    two_text_tasks(fixture)
    fixture.items.append({**deepcopy(fixture.items[0]), "id": "duplicate"})
    duplicated = closed(fixture.read)
    assert duplicated.code == "workflow_result_invalid"

    crowded = RunFixture()
    two_text_tasks(crowded)
    crowded.items.extend(
        {**deepcopy(crowded.items[0]), "id": f"extra-{index}", "status": "skipped"}
        for index in range(reader.MAX_TASK_ROWS)
    )
    overflowed = closed(crowded.read)
    assert overflowed.code == "workflow_result_invalid"


@pytest.mark.parametrize("stage", [
    "workflow_read", "workflow_read_cosmos", "run_read", "items_query", "items_iteration",
    "result_load_unavailable", "result_load_azure", "page_read",
])
def test_storage_failures_are_transient_and_never_read_as_not_found(stage):
    fixture = RunFixture()
    two_text_tasks(fixture)
    if stage == "workflow_read":
        fixture.containers["workflows"].read_error = AzureError("SECRET-STORAGE-DETAIL")
    elif stage == "workflow_read_cosmos":
        fixture.containers["workflows"].read_error = CosmosHttpResponseError(status_code=503, message="down")
    elif stage == "run_read":
        fixture.containers["runs"].read_error = CosmosHttpResponseError(status_code=500, message="down")
    elif stage == "items_query":
        fixture.containers["run_items"].query_error = CosmosHttpResponseError(status_code=429, message="busy")
    elif stage == "items_iteration":
        fixture.containers["run_items"].iteration_error = CosmosHttpResponseError(status_code=503, message="down")
    elif stage == "result_load_unavailable":
        fixture.store.load_error = WorkflowResultStorageUnavailableError("SECRET-STORAGE-DETAIL")
    elif stage == "result_load_azure":
        fixture.store.load_error = AzureError("SECRET-STORAGE-DETAIL")
    else:
        fixture.add_task("task-summary-72", {"reply": "x" * (300 * 1024)}, order=2)

        def unavailable(*args, **kwargs):
            raise WorkflowResultStorageUnavailableError("SECRET-STORAGE-DETAIL")

        fixture.store.read_page = unavailable

    error = closed(lambda: fixture.read(include_excerpts=True))

    assert error.code == "workflow_result_storage_unavailable" and error.status == 503
    assert "SECRET-STORAGE-DETAIL" not in error.message


def test_a_removed_stored_result_reads_as_not_found():
    fixture = RunFixture()
    two_text_tasks(fixture)
    fixture.store.contents.clear()

    error = closed(fixture.read)

    assert error.code == "workflow_result_not_found" and error.status == 404


def test_the_items_query_is_the_exact_projection_and_the_real_authorizer_accepts_its_rows():
    fixture = RunFixture()
    _, analysis_ref = fixture.add_task("task-analyze-74", analysis_result(), order=1, label="Analyze reports")
    fixture.add_task("task-summary-72", {"reply": "The digest: one finding."}, order=2)
    fixture.reset_counters()

    result = fixture.read()

    assert reader._ITEMS_QUERY == EXPECTED_QUERY
    query = fixture.containers["run_items"].queries[-1]
    assert query["partition_key"] == RUN_ID
    assert query["parameters"] == [
        {"name": "@run_id", "value": RUN_ID}, {"name": "@workflow_id", "value": WORKFLOW_ID},
    ]
    assert projected_fields(query["query"]) == [
        "workflow_id", "run_id", "task_id", "task_order", "status", "item_type", "label", "workflow_result",
    ]
    assert result["descriptor"]["available"] is True
    # The real run guard verified lineage only; the Analyze sources are provenance and aren't re-resolved.
    assert fixture.sources.readers == []
    assert analysis_ref["sha256"] in fixture.store.loads


def test_dropping_workflow_id_from_the_projection_fails_closed(monkeypatch):
    fixture = RunFixture()
    fixture.add_task("task-analyze-74", analysis_result(), order=1)
    fixture.add_task("task-summary-72", {"reply": "The digest."}, order=2)
    mutated = EXPECTED_QUERY.replace("c.workflow_id, ", "", 1)
    assert mutated != EXPECTED_QUERY

    rows = list(fixture.containers["run_items"].query_items(
        mutated, [{"name": "@run_id", "value": RUN_ID}, {"name": "@workflow_id", "value": WORKFLOW_ID}],
        RUN_ID,
    ))
    assert rows and all("workflow_id" not in row for row in rows)
    with pytest.raises(AnalysisResultUnavailable) as caught:
        authorize_workflow_run_read(
            fixture.workflow, RUN_ID, reader_user_id=USER, result_items=rows,
            load_result=fixture.store.load, source_resolver=fixture.sources,
        )
    assert caught.value.code == "analysis_lineage_invalid"

    monkeypatch.setattr(reader, "_ITEMS_QUERY", mutated)
    error = closed(fixture.read)
    assert error.status in {403, 409}
    assert error.code in {"workflow_result_invalid", "workflow_result_access_denied"}


def test_the_digest_is_deterministic_and_independent_of_the_excerpt_budget():
    fixture = RunFixture()
    two_text_tasks(fixture)
    fixture.add_task("task-long-75", {"reply": "long " * 4000}, order=3)

    first = fixture.read()["descriptor"]["result_sha256"]
    second = fixture.read()["descriptor"]["result_sha256"]
    small = fixture.read(include_excerpts=True, excerpt_budget_bytes=1024)
    large = fixture.read(include_excerpts=True, excerpt_budget_bytes=reader.MAX_EXCERPT_BUDGET_BYTES)

    assert first == second == small["descriptor"]["result_sha256"] == large["descriptor"]["result_sha256"]
    assert small["truncated"] is True and large["truncated"] is False
    expected = reader.workflow_result_digest(WORKFLOW_ID, RUN_ID, "completed", sorted(
        fixture.items, key=lambda item: item["task_order"],
    ))
    assert first == expected


def test_a_resume_that_rewrites_an_included_result_changes_the_digest_and_nothing_is_read():
    fixture = RunFixture()
    two_text_tasks(fixture)
    before = fixture.read()["descriptor"]["result_sha256"]

    fixture.add_task("task-summary-72", {"reply": "The digest after a resumed attempt."}, order=2)
    fixture.reset_counters()
    error = closed(lambda: fixture.read(expected_sha256=before, include_excerpts=True))

    assert error.code == "workflow_result_changed" and error.status == 409
    assert fixture.store.loads == [] and fixture.store.pages == []
    after = fixture.read(include_excerpts=True)
    assert after["descriptor"]["result_sha256"] != before
    assert after["excerpts"][0]["text"] == "The digest after a resumed attempt."


def test_newly_succeeded_tasks_and_a_status_change_also_change_the_digest():
    fixture = RunFixture(status="completed_partial")
    fixture.add_task("task-collect-71", {"reply": "Collected."}, order=1)
    fixture.add_task("task-summary-72", {"reply": "Not yet."}, order=2, status="failed")
    partial = fixture.read()["descriptor"]["result_sha256"]

    fixture.items[1]["status"] = "succeeded"
    with_new_task = fixture.read()["descriptor"]["result_sha256"]
    fixture.run["status"] = "completed"
    completed = fixture.read()["descriptor"]["result_sha256"]

    assert len({partial, with_new_task, completed}) == 3


@pytest.mark.parametrize("value", ["ABC", "a" * 63, "g" * 64, 12, ""])
def test_a_malformed_expected_digest_is_an_invalid_context(value):
    fixture = RunFixture()
    two_text_tasks(fixture)
    error = closed(lambda: fixture.read(expected_sha256=value))
    assert error.code == "workflow_result_invalid_context" and error.status == 400


@pytest.mark.parametrize("budget", [1023, reader.MAX_EXCERPT_BUDGET_BYTES + 1, True, 2048.0, None])
def test_the_excerpt_budget_is_bounded(budget):
    fixture = RunFixture()
    two_text_tasks(fixture)
    with pytest.raises(ValueError):
        fixture.read(excerpt_budget_bytes=budget)


@pytest.mark.parametrize("where", ["included_output", "failed_task_outside_the_result"])
def test_lost_source_access_anywhere_in_the_run_keeps_the_result_readable(where):
    fixture = RunFixture()
    status = "succeeded" if where == "included_output" else "failed"
    fixture.add_task("task-analyze-74", analysis_result(), order=1, status=status)
    fixture.add_task("task-summary-72", {"reply": "The digest."}, order=2)
    readable = fixture.read()
    assert readable["descriptor"]["available"] is True

    fixture.sources.allowed = False
    after = fixture.read(include_excerpts=True)

    # The result takes its access from its workflow and run, not from the documents it read.
    assert after["descriptor"]["available"] is True
    assert after["descriptor"]["result_sha256"] == readable["descriptor"]["result_sha256"]
    assert fixture.sources.readers == []


def test_a_row_that_points_at_another_tasks_result_is_refused():
    fixture = RunFixture()
    two_text_tasks(fixture)
    fixture.items[1]["workflow_result"]["result_ref"] = deepcopy(fixture.items[0]["workflow_result"]["result_ref"])
    pointed = closed(fixture.read)
    # A lineage failure is an invalid result, not an access denial.
    assert pointed.code == "workflow_result_invalid" and pointed.status == 409

    other = RunFixture()
    two_text_tasks(other)
    other.items[1]["workflow_result"]["authoritative_output"] = "records"
    relabeled = closed(other.read)
    assert relabeled.code == "workflow_result_invalid"


def test_the_reader_rechecks_that_each_manifest_names_its_own_task(monkeypatch):
    # Run authorization already refuses this row (above). The reader's own identity check
    # must still hold if authorization ever stops comparing task ids, so it's replaced here.
    fixture = RunFixture()
    two_text_tasks(fixture)
    fixture.items[1]["workflow_result"]["result_ref"] = deepcopy(fixture.items[0]["workflow_result"]["result_ref"])
    authorized = []
    monkeypatch.setattr(reader, "authorize_workflow_run_read", lambda *args, **kwargs: authorized.append(args))

    error = closed(fixture.read)

    assert len(authorized) == 1
    assert error.code == "workflow_result_invalid" and error.status == 409


def test_one_long_text_output_uses_the_whole_budget_and_says_it_was_cut():
    fixture = RunFixture()
    fixture.add_task("task-summary-72", {"reply": "é" * 5000}, order=1)

    result = fixture.read(include_excerpts=True, excerpt_budget_bytes=4096)

    excerpt = result["excerpts"][0]
    assert len(excerpt["text"].encode("utf-8")) == 4096
    assert "\ufffd" not in excerpt["text"] and ("é" * 5000).startswith(excerpt["text"])
    assert excerpt["truncated"] is True and result["truncated"] is True
    assert excerpt["note"] == "[Excerpt truncated: the first 4 KB of 10 KB.]"


def test_the_final_output_gets_half_the_budget_and_the_rest_share_what_is_left():
    fixture = RunFixture()
    fixture.add_task("task-a-81", {"reply": "a" * 4000}, order=1)
    fixture.add_task("task-b-82", {"reply": "b" * 100}, order=2)
    fixture.add_task("task-c-83", {"reply": "c" * 4000}, order=3)

    result = fixture.read(include_excerpts=True, excerpt_budget_bytes=4096)

    sizes = [len(excerpt["text"]) for excerpt in result["excerpts"]]
    assert [excerpt["text"][0] for excerpt in result["excerpts"]] == ["c", "a", "b"]
    assert sizes[0] == 2048
    assert sizes[1] == 1024 and sizes[2] == 100
    assert sum(sizes) <= 4096


def test_outputs_past_the_count_or_budget_are_omitted_and_flagged():
    fixture = RunFixture()
    for index in range(reader.MAX_EXCERPT_OUTPUTS + 1):
        fixture.add_task(f"task-{index:02d}", {"reply": f"Output {index}."}, order=index + 1)
    result = fixture.read(include_excerpts=True)
    assert len(result["excerpts"]) == reader.MAX_EXCERPT_OUTPUTS
    assert result["omitted_outputs"] == 1 and result["truncated"] is True

    tight = RunFixture()
    for index in range(3):
        tight.add_task(f"task-{index:02d}", {"reply": "z" * 2048}, order=index + 1)
    squeezed = tight.read(include_excerpts=True, excerpt_budget_bytes=1024)
    assert [len(excerpt["text"]) for excerpt in squeezed["excerpts"]] == [512, 512]
    assert squeezed["omitted_outputs"] == 1 and squeezed["truncated"] is True


def test_record_pages_are_read_a_page_at_a_time_within_the_limit():
    fixture = RunFixture()
    records = [{"row": index, "value": f"item {index}"} for index in range(250)]
    manifest, _ = fixture.add_task("task-analyze-74", analysis_result(records), order=1)
    assert manifest["outputs"]["records"]["storage_kind"] == "record_pages"

    text, cut, note = reader._output_excerpt(
        fixture.workflow, RUN_ID, "task-analyze-74", manifest, fixture.store.load, fixture.store.read_page, 2048,
    )
    lines = text.split("\n")
    assert cut is True and len(text.encode("utf-8")) <= 2048
    assert json.loads(lines[0]) == records[0]
    assert note == f"[Excerpt truncated: the first {len(lines)} of 250 records.]"

    everything, cut, note = reader._output_excerpt(
        fixture.workflow, RUN_ID, "task-analyze-74", manifest, fixture.store.load, fixture.store.read_page,
        reader.MAX_EXCERPT_BUDGET_BYTES,
    )
    assert cut is False and note is None
    assert [json.loads(line) for line in everything.split("\n")] == records


def test_a_large_text_output_is_read_by_page_prefix_and_never_whole():
    fixture = RunFixture()
    original = "abc😀é" * 15000
    manifest, _ = fixture.add_task("task-summary-72", {"reply": original}, order=1)
    section_digest = manifest["outputs"]["text"]["result_ref"]["sha256"]
    assert manifest["outputs"]["text"]["result_ref"]["size_bytes"] > reader.FULL_SECTION_READ_BYTES
    fixture.reset_counters()

    result = fixture.read(include_excerpts=True, excerpt_budget_bytes=4096)

    excerpt = result["excerpts"][0]
    assert section_digest not in fixture.store.loads
    assert fixture.store.pages == [(section_digest, 0, 4096 * 3 + 4096)]
    assert 4000 <= len(excerpt["text"].encode("utf-8")) <= 4096
    assert original.startswith(excerpt["text"]) and "\ufffd" not in excerpt["text"]
    assert excerpt["truncated"] is True and excerpt["note"].startswith("[Excerpt truncated: the first 4 KB of ")


def test_a_large_json_output_is_read_by_page_prefix():
    fixture = RunFixture()
    value = {"items": [{"n": index, "text": "x" * 50} for index in range(6000)]}
    manifest, _ = fixture.add_task("task-summary-72", {
        "reply": "Summary.", "authoritative_result": {"kind": "json", "value": value},
    }, order=1)
    assert manifest["outputs"]["json"]["result_ref"]["size_bytes"] > reader.FULL_SECTION_READ_BYTES

    result = fixture.read(include_excerpts=True, excerpt_budget_bytes=2048)

    excerpt = result["excerpts"][0]
    assert len(excerpt["text"]) == 2048 and canonical(value).startswith(excerpt["text"])
    assert excerpt["truncated"] is True and excerpt["kind"] == "json"


def test_a_page_that_does_not_match_its_manifest_is_invalid():
    fixture = RunFixture()
    fixture.add_task("task-summary-72", {"reply": "y" * (300 * 1024)}, order=1)
    real_read_page = fixture.store.read_page

    def mismatched(*args, **kwargs):
        page = real_read_page(*args, **kwargs)
        return {**page, "content": page["content"].replace('"output_name":"text"', '"output_name":"diagnostics"', 1)}

    fixture.store.read_page = mismatched
    error = closed(lambda: fixture.read(include_excerpts=True))
    assert error.code == "workflow_result_invalid" and error.status == 409


@pytest.mark.parametrize("text,expected", [
    ("plain", "plain"),
    ("caf\\u00e9 and more", "café and more"),
    ("cut escape \\u00", "cut escape "),
    ("cut backslash \\", "cut backslash "),
    ("\\ud83d\\ude00 smile", "😀 smile"),
    ("cut pair \\ud83d\\ude0", "cut pair "),
    ("cut high \\ud83d", "cut high "),
    ("lone high \\ud83dxxxxxx tail", "lone high \ufffdxxxxxx tail"),
    ("lone low \\ude00 tail", "lone low \ufffd tail"),
    ("line\\nbreak \\\"quoted\\\" \\/", "line\nbreak \"quoted\" /"),
    ('stops at the "closing quote', "stops at the "),
])
def test_json_string_prefixes_decode_leniently_at_the_cut(text, expected):
    assert reader.decode_json_string_prefix(text) == expected


@pytest.mark.parametrize("text", ["bad \\q escape", "bad \\u12zz hex"])
def test_json_string_prefixes_reject_invalid_escapes(text):
    with pytest.raises(ValueError):
        reader.decode_json_string_prefix(text)


def test_one_memoized_loader_serves_authorization_the_completion_rule_and_excerpts():
    fixture = RunFixture()
    two_text_tasks(fixture)
    fixture.reset_counters()

    fixture.read(include_excerpts=True)

    manifests = [item["workflow_result"]["result_ref"]["sha256"] for item in fixture.items]
    assert all(fixture.store.loads.count(digest) == 1 for digest in manifests)
    assert len(fixture.store.loads) == 4

    analysis = RunFixture()
    analysis.add_task("task-analyze-74", analysis_result(), order=1)
    analysis.reset_counters()
    loaded = analysis.read(include_excerpts=True)
    assert len(loaded["saved_inputs"]) == 1
    assert analysis.store.loads == [analysis.items[0]["workflow_result"]["result_ref"]["sha256"]]


def test_the_manifest_memo_keeps_only_a_bounded_number_of_manifests():
    calls = []

    def load(workflow, run_id, task_id, reference, **selectors):
        calls.append(reference["sha256"])
        if reference["sha256"].startswith("manifest"):
            return {"identity": {"task_id": task_id}, "outputs": {}}
        return {"value": "section"}

    memo = reader._ManifestMemo(load, limit=2)
    for _ in range(2):
        memo({}, RUN_ID, "a", {"sha256": "manifest-a"})
        memo({}, RUN_ID, "a", {"sha256": "section-a"})
    assert calls == ["manifest-a", "section-a", "section-a"]
    memo({}, RUN_ID, "b", {"sha256": "manifest-b"})
    memo({}, RUN_ID, "c", {"sha256": "manifest-c"})
    memo({}, RUN_ID, "a", {"sha256": "manifest-a"})
    assert calls[-1] == "manifest-a" and memo.load_count == 6


def test_a_completed_run_refuses_an_accepted_partial_analysis_instead_of_skipping_it():
    fixture = RunFixture()
    fixture.add_task("task-analyze-74", analysis_result(), order=1, edit=accepted_partial)
    fixture.add_task("task-summary-72", {"reply": "The digest."}, order=2)
    for include_excerpts in (False, True):
        error = closed(lambda: fixture.read(include_excerpts=include_excerpts))
        assert error.code == "workflow_result_invalid" and error.status == 409

    report = RunFixture()
    _, first = report.add_task("task-analyze-a", analysis_result(), order=1, edit=accepted_partial)
    _, second = report.add_task("task-analyze-b", analysis_result(sources=(SECOND_SOURCE,)), order=2)
    receipts = [
        report.receipt("task-analyze-a", first, allow_partial=True), report.receipt("task-analyze-b", second),
    ]
    report.add_task("task-report-c", {"reply": "Combined report."}, order=3, consumed=receipts)
    error = closed(lambda: report.read(include_excerpts=True))
    assert error.code == "workflow_result_invalid"


def test_a_report_with_several_analysis_parents_is_skipped_and_flagged():
    fixture = RunFixture()
    _, first = fixture.add_task("task-analyze-a", analysis_result(), order=1)
    _, second = fixture.add_task("task-analyze-b", analysis_result(sources=(SECOND_SOURCE,)), order=2)
    receipts = [fixture.receipt("task-analyze-a", first), fixture.receipt("task-analyze-b", second)]
    fixture.add_task("task-report-c", {"reply": "Combined report."}, order=3, consumed=receipts)
    assert fixture.items[-1]["workflow_result"]["analysis_result"] is True

    result = fixture.read(include_excerpts=True)

    assert result["skipped_reports"] == 1 and result["omitted_outputs"] == 1
    assert {saved.context["result_sha256"] for saved in result["saved_inputs"]} == {
        first["sha256"], second["sha256"],
    }
    assert result["excerpts"] == [] and result["analysis_only"] is False


def test_a_run_of_only_multi_parent_reports_is_unsupported():
    fixture = RunFixture()
    _, first = fixture.add_task("task-analyze-a", analysis_result(), order=1)
    _, second = fixture.add_task("task-analyze-b", analysis_result(sources=(SECOND_SOURCE,)), order=2)
    receipts = [fixture.receipt("task-analyze-a", first), fixture.receipt("task-analyze-b", second)]
    fixture.add_task("task-report-c", {"reply": "Combined report."}, order=3, consumed=receipts)
    for item in fixture.items[:2]:
        item["status"] = "failed"

    error = closed(fixture.read)

    assert error.code == "workflow_result_unsupported" and error.status == 409


def test_a_report_with_one_analysis_parent_stands_in_for_it_once():
    fixture = RunFixture()
    _, parent = fixture.add_task("task-analyze-a", analysis_result(), order=1)
    fixture.add_task("task-report-c", {"reply": "Report."}, order=2, consumed=[
        fixture.receipt("task-analyze-a", parent),
    ])

    result = fixture.read(include_excerpts=True)

    assert len(result["saved_inputs"]) == 1
    assert isinstance(result["saved_inputs"][0], SavedAnalysisInput)
    assert result["saved_inputs"][0].context["result_sha256"] == parent["sha256"]
    assert result["skipped_reports"] == 0 and result["omitted_outputs"] == 0


def test_a_completed_partial_run_reads_its_accepted_partial_analysis_and_discloses_it():
    fixture = RunFixture(status="completed_partial")
    fixture.add_task("task-analyze-74", analysis_result(), order=1, edit=accepted_partial)
    fixture.add_task("task-summary-72", {"reply": "Unfinished."}, order=2, status="failed")

    result = fixture.read(include_excerpts=True)

    assert result["partial"] is True and len(result["saved_inputs"]) == 1
    disclosure = reader.format_workflow_result_disclosure(result["descriptor"], partial=result["partial"])
    assert "The run completed partially, so its result may be incomplete." in disclosure


@pytest.mark.parametrize("include_excerpts", [False, True])
def test_partial_plain_outputs_follow_the_run_status(include_excerpts):
    def partial_validation(envelope):
        envelope["validation"] = {"status": "partial"}

    completed = RunFixture()
    completed.add_task("task-summary-72", {"reply": "Some of it."}, order=1, edit=partial_validation)
    error = closed(lambda: completed.read(include_excerpts=include_excerpts))
    assert error.code == "workflow_result_invalid" and error.status == 409

    partial = RunFixture(status="completed_partial")
    partial.add_task("task-summary-72", {"reply": "Some of it."}, order=1, edit=partial_validation)
    result = partial.read(include_excerpts=include_excerpts)
    assert result["partial"] is True


def test_a_mixed_run_answers_from_its_saved_analysis_only():
    fixture = RunFixture()
    fixture.add_task("task-analyze-74", analysis_result(), order=1)
    fixture.add_task("task-summary-72", {"reply": "Unverifiable prose."}, order=2)

    result = fixture.read(include_excerpts=True)

    assert len(result["saved_inputs"]) == 1 and result["excerpts"] == []
    assert result["analysis_only"] is True and result["omitted_outputs"] == 1
    disclosure = reader.format_workflow_result_disclosure(
        result["descriptor"], analysis_only=result["analysis_only"],
    )
    assert "Only the saved analysis in this run's result was used." in disclosure


def test_the_disclosure_names_the_run_in_the_users_time_zone():
    descriptor = {"workflow_name": "Weekly digest", "completed_at": COMPLETED_AT}
    assert reader.format_workflow_result_disclosure(descriptor, "America/New_York") == (
        "_This answer uses the stored result of the Weekly digest run of Mon Jan 5, 2026, 9:02 AM EST. "
        "The workflow was not re-run._"
    )
    assert reader.format_workflow_run_time("2026-07-06T13:02:00Z", "America/New_York") == "Mon Jul 6, 2026, 9:02 AM EDT"
    assert reader.format_workflow_run_time(COMPLETED_AT, None) == "Mon Jan 5, 2026, 2:02 PM UTC"
    assert reader.format_workflow_run_time(COMPLETED_AT, "Not/AZone") == "Mon Jan 5, 2026, 2:02 PM UTC"
    assert reader.format_workflow_run_time("2026-01-05T14:02:00", "UTC") == "Mon Jan 5, 2026, 2:02 PM UTC"
    assert reader.format_workflow_run_time("not a time", "UTC") == ""
    everything = reader.format_workflow_result_disclosure(
        descriptor, "UTC", truncated=True, partial=True, analysis_only=True, skipped_reports=True,
    )
    assert everything.startswith("_This answer uses the stored result of the Weekly digest run of ")
    assert everything.endswith(
        "The workflow was not re-run. The run completed partially, so its result may be incomplete. "
        "Only the saved analysis in this run's result was used. "
        "A report that combined several saved analyses couldn't be used. "
        "Only part of the result fit in this answer._"
    )
    undated = reader.format_workflow_result_disclosure({"workflow_name": "Weekly digest"})
    assert undated.startswith("_This answer uses the stored result of a stored Weekly digest run.")


def test_the_workflow_name_is_treated_as_user_authored_display_text():
    fixture = RunFixture(name="  Digest\u0000 *bold* [link](x)\n_under_ " + "n" * 200)
    two_text_tasks(fixture)

    descriptor = fixture.read()["descriptor"]

    name = descriptor["workflow_name"]
    assert "\u0000" not in name and "\n" not in name and len(name) <= reader.WORKFLOW_NAME_MAX_CHARS
    assert name.startswith("Digest *bold* [link](x) _under_")
    disclosure = reader.format_workflow_result_disclosure(descriptor, "UTC")
    assert "\\*bold\\*" in disclosure and "\\[link\\]\\(x\\)" in disclosure and "\\_under\\_" in disclosure

    fixture.workflow["name"] = ""
    renamed = fixture.read()
    assert renamed["descriptor"]["workflow_name"].startswith("Digest")
    fixture.run["workflow_name"] = None
    unnamed = fixture.read()
    assert unnamed["descriptor"]["workflow_name"] == "Workflow"


def test_the_browser_selector_and_message_contexts_are_validated():
    context = {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "result_sha256": "b" * 64}
    assert reader.workflow_result_context({**context, "extra": "dropped"}) == context
    for bad in (None, [], {**context, "result_sha256": "B" * 64}, {**context, "run_id": "../x"},
                {**context, "workflow_id": 7}, {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID}):
        error = closed(lambda: reader.workflow_result_context(bad))
        assert error.code == "workflow_result_invalid_context" and error.status == 400

    descriptor = {**context, "version": "workflow-result-v1", "workflow_name": "Weekly digest", "available": True}
    second = {**context, "run_id": "run-other-8"}
    message = {"metadata": {
        "workflow_result": descriptor, "workflow_result_contexts": [context, second, context],
    }}
    contexts, malformed = reader.workflow_result_message_contexts(message)
    assert contexts == [context, second] and malformed is False
    assert masking.message_uses_workflow_result(message) is True

    question = {"metadata": {"workflow_result_context": context}}
    assert reader.workflow_result_message_contexts(question) == ([context], False)
    for metadata in ({"workflow_result_contexts": "not-a-list"}, {"workflow_result": {"run_id": RUN_ID}}):
        found, malformed = reader.workflow_result_message_contexts({"metadata": metadata})
        assert found == [] and malformed is True
        assert masking.message_uses_workflow_result({"metadata": metadata}) is True
    assert reader.workflow_result_message_contexts({"metadata": {"other": 1}}) == ([], False)
    assert masking.message_uses_workflow_result({"content": "plain"}) is False


def test_closed_reasons_have_fixed_payloads_and_logs_never_carry_exception_text(monkeypatch):
    assert reader.workflow_result_error_payload(reader.WorkflowResultUnavailable("workflow_result_changed")) == (
        {"error": reader._REASONS["workflow_result_changed"][1], "code": "workflow_result_changed"}, 409,
    )
    assert reader.WorkflowResultUnavailable("no_such_code").code == "workflow_result_invalid"
    assert reader.workflow_result_error_payload(RuntimeError("SECRET"))[0]["code"] == "workflow_result_invalid"
    assert {status for status, _ in reader._REASONS.values()} == {400, 403, 404, 409, 503}

    events = []
    monkeypatch.setattr(reader, "log_event", lambda message, **kwargs: events.append((message, kwargs)))
    fixture = RunFixture()
    two_text_tasks(fixture)
    fixture.store.load_error = PermissionError(f"SECRET-PATH {WORKFLOW_ID}")

    error = closed(fixture.read)

    assert error.code == "workflow_result_access_denied" and "SECRET" not in error.message
    assert events and all(message == "[WorkflowResults] Workflow result unavailable" for message, _ in events)
    for _, kwargs in events:
        assert set(kwargs["extra"]) <= {"code", "stage", "error_type"}
        assert "SECRET" not in json.dumps(kwargs["extra"]) and WORKFLOW_ID not in json.dumps(kwargs["extra"])


def test_unexpected_programming_errors_are_not_disguised_as_closed_reasons():
    fixture = RunFixture()
    two_text_tasks(fixture)
    fixture.store.load_error = TypeError("unexpected")
    with pytest.raises(TypeError):
        fixture.read()


def test_authorizing_a_stored_context_reads_no_excerpts():
    fixture = RunFixture()
    fixture.add_task("task-summary-72", {"reply": "z" * (300 * 1024)}, order=1)
    digest = fixture.read()["descriptor"]["result_sha256"]
    fixture.reset_counters()
    context = {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "result_sha256": digest}

    descriptor = reader.authorize_workflow_result_context(
        USER, context, containers=fixture.containers, load_result=fixture.store.load,
        read_page=fixture.store.read_page, source_resolver=fixture.sources,
    )

    assert descriptor["result_sha256"] == digest
    assert fixture.store.pages == [] and fixture.store.loads == [fixture.items[0]["workflow_result"]["result_ref"]["sha256"]]
    with pytest.raises(reader.WorkflowResultUnavailable) as caught:
        reader.authorize_workflow_result_context(
            OTHER_USER, context, containers=fixture.containers, load_result=fixture.store.load,
            source_resolver=fixture.sources,
        )
    assert caught.value.code == "workflow_result_not_found"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
