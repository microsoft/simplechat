# test_orchestration_cosmos_response_contract.py
"""Real orchestration boundaries accept the pinned Cosmos SDK's mapping responses.

Version: 0.261.140
Implemented in: 0.261.140

Authenticated HTTP routes, claims, result/output stores, publication and scheduler
run unchanged, with only external I/O doubled. SDK-shaped point reads and writes
retain ETags. Query rows remain plain dictionaries, as in azure-cosmos 4.9.0.
Downloaded CSV bytes are checked against all 50 state/capital records.
"""

import csv
import importlib
import io
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from azure.core import MatchConditions
from azure.cosmos import exceptions
from azure.cosmos._cosmos_responses import CosmosDict

from test_orchestration_deliverables import _csv_plan, _normalize, _store
from test_orchestration_harness_routes import modules, real_http_harness  # noqa: F401
from test_orchestration_harness_scheduler import tick
from test_support.orchestration_harness_execution import input_binding


STATE_CAPITALS = (
    ("Alabama", "Montgomery"), ("Alaska", "Juneau"), ("Arizona", "Phoenix"),
    ("Arkansas", "Little Rock"), ("California", "Sacramento"), ("Colorado", "Denver"),
    ("Connecticut", "Hartford"), ("Delaware", "Dover"), ("Florida", "Tallahassee"),
    ("Georgia", "Atlanta"), ("Hawaii", "Honolulu"), ("Idaho", "Boise"),
    ("Illinois", "Springfield"), ("Indiana", "Indianapolis"), ("Iowa", "Des Moines"),
    ("Kansas", "Topeka"), ("Kentucky", "Frankfort"), ("Louisiana", "Baton Rouge"),
    ("Maine", "Augusta"), ("Maryland", "Annapolis"), ("Massachusetts", "Boston"),
    ("Michigan", "Lansing"), ("Minnesota", "Saint Paul"), ("Mississippi", "Jackson"),
    ("Missouri", "Jefferson City"), ("Montana", "Helena"), ("Nebraska", "Lincoln"),
    ("Nevada", "Carson City"), ("New Hampshire", "Concord"), ("New Jersey", "Trenton"),
    ("New Mexico", "Santa Fe"), ("New York", "Albany"), ("North Carolina", "Raleigh"),
    ("North Dakota", "Bismarck"), ("Ohio", "Columbus"), ("Oklahoma", "Oklahoma City"),
    ("Oregon", "Salem"), ("Pennsylvania", "Harrisburg"), ("Rhode Island", "Providence"),
    ("South Carolina", "Columbia"), ("South Dakota", "Pierre"), ("Tennessee", "Nashville"),
    ("Texas", "Austin"), ("Utah", "Salt Lake City"), ("Vermont", "Montpelier"),
    ("Virginia", "Richmond"), ("Washington", "Olympia"), ("West Virginia", "Charleston"),
    ("Wisconsin", "Madison"), ("Wyoming", "Cheyenne"),
)


@pytest.fixture(params=[False, True], ids=["plain-dict", "cosmos-dict"])
def storage_runtime(real_http_harness, request):
    harness = real_http_harness.harness
    for container in (
        harness.conversations, harness.messages, harness.runs,
        harness.steps, harness.results.container,
    ):
        container.sdk_responses = request.param
    real_http_harness.sdk_responses = request.param
    return real_http_harness


def _frames(response):
    return [
        json.loads(frame.partition("data:")[2].strip())
        for frame in response.get_data(as_text=True).split("\n\n")
        if frame.startswith("data:")
    ]


def _execute(runtime, run_id):
    return runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": run_id, "conversation_id": "conversation-1",
    }, buffered=True)


def test_claim_and_lease_keep_plain_records_and_conditional_etags(storage_runtime):
    harness = storage_runtime.harness
    harness.create()
    raw = harness.read()
    assert isinstance(raw, CosmosDict) is storage_runtime.sdk_responses
    claimed, lease = harness.claim()
    try:
        current = lease.read()
        updated = lease.update({"recovery_probe": True})
        assert type(claimed) is type(current) is type(updated) is dict
        assert claimed["_etag"] == current["_etag"]
        assert updated["_etag"] != current["_etag"]
        assert updated["execution_lease"]["token"] == lease.token
        with pytest.raises(exceptions.CosmosAccessConditionFailedError):
            harness.runs.replace_item(
                "run-1", body=current, etag=current["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
    finally:
        if not lease.stopped.is_set():
            lease.close(release=True)
    saved = harness.read()
    assert saved["recovery_probe"] is True
    assert saved["execution_lease"] is None
    assert harness.model_calls == []


def test_status_reads_accept_sdk_responses_before_execution(storage_runtime):
    harness = storage_runtime.harness
    harness.create()
    before = deepcopy(harness.runs.items)
    responses = [
        storage_runtime.client.get(path, query_string={"conversation_id": "conversation-1"})
        for path in (
            "/api/v2/orchestration/runs",
            "/api/v2/orchestration/runs/run-1",
            "/api/v2/orchestration/runs/run-1/steps",
        )
    ]
    values = [response.get_json() for response in responses]
    assert [response.status_code for response in responses] == [200, 200, 200], values
    assert len(values[0]["runs"]) == 1
    assert values[1]["run"]["outputs"] == []
    assert values[1]["run"]["generated_artifacts"] == []
    assert values[2]["steps"] == []
    assert harness.runs.items == before
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0


def test_source_free_answer_executes_and_recovers_through_http(storage_runtime):
    harness = storage_runtime.harness
    record = harness.create(
        replies=["A complete rewritten answer."], final_response=input_binding("prepare"),
    )
    executed = _execute(storage_runtime, record["id"])
    events = _frames(executed)
    detail = storage_runtime.client.get(
        "/api/v2/orchestration/runs/run-1", query_string={"conversation_id": "conversation-1"},
    )
    saved = harness.read()
    messages = harness.assistant_messages()
    assert executed.status_code == detail.status_code == 200, events
    assert events[-1]["status"] == saved["status"] == detail.get_json()["run"]["status"] == "completed"
    assert messages[0]["content"] == "A complete rewritten answer."
    assert len(messages) == len(harness.model_calls) == 1
    assert saved["message_saved"] is True and saved["execution_lease"] is None
    assert harness.blobs.file_uploads == 0


def test_complete_csv_download_and_history_use_sdk_responses(storage_runtime):
    harness = storage_runtime.harness
    rows = [{"State": state, "Capital": capital} for state, capital in STATE_CAPITALS]
    plan = _normalize(harness, {**_csv_plan(), "final_response": None})
    assert "final_response" not in plan
    record = _store(harness, plan, replies=[json.dumps({"rows": rows})])
    response = _execute(storage_runtime, record["id"])
    events = _frames(response)
    saved = harness.read()
    assert response.status_code == 200 and saved["status"] == "completed", events
    services = harness.services()
    screening = importlib.import_module("content_screening.access")
    messages = harness.assistant_messages()
    with harness.publication_only(services):
        detail = storage_runtime.client.get(
            "/api/v2/orchestration/runs/run-1", query_string={"conversation_id": "conversation-1"},
        )
        projected = detail.get_json()
        assert detail.status_code == 200, projected
        outputs = projected["run"]["outputs"]
        assert len(outputs) == 1 and outputs[0]["state"] == "completed"
        with services.rendering.open_download(outputs[0]["output_id"]) as stream:
            downloaded = stream.read()
        reader = csv.DictReader(io.StringIO(downloaded.decode("utf-8")))
        actual = list(reader)
        with storage_runtime.app.test_request_context():
            history = screening.public_history_messages(messages, "owner")
    assert reader.fieldnames == ["State", "Capital"]
    assert len(actual) == len({row["State"] for row in actual}) == 50
    assert actual == rows
    assert actual[-1] == {"State": "Wyoming", "Capital": "Cheyenne"}
    assert history[0]["metadata"]["orchestration"]["outputs"] == outputs
    assert len(history[0]["generated_artifacts"]) == len(messages) == 1
    assert len(harness.model_calls) == harness.blobs.file_uploads == 1
    assert saved["execution_lease"] is None


def test_expired_initial_claim_reaches_terminal_state_without_generation(
    storage_runtime, monkeypatch,
):
    harness = storage_runtime.harness
    continuation = importlib.import_module("functions_orchestration_continuation")
    now = [datetime.now(timezone.utc)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now[0].astimezone(tz) if tz is not None else now[0].replace(tzinfo=None)

    for module in (harness.revisions, harness.recovery, continuation):
        monkeypatch.setattr(module, "_now", lambda: now[0])
    monkeypatch.setattr(harness.execution, "datetime", Clock)
    harness.settings["chat_orchestration_total_timeout_seconds"] = 173
    harness.create(final_response=input_binding("prepare"))
    claimed, lease = harness.claim()
    lease.close(release=True)
    now[0] += timedelta(seconds=200)
    result, _queries, logs = tick(harness, clock=lambda: now[0])
    saved = harness.read()
    assert result["ok"] is True, (result, logs)
    assert saved["status"] == "failed" and saved["failure"]["code"] == "run_timeout"
    assert saved["message_saved"] is True and saved["execution_lease"] is None
    assert saved["started_at"] == claimed["started_at"]
    assert saved["execution_deadline_at"] == claimed["execution_deadline_at"]
    assert len(harness.assistant_messages()) == 1
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0


def test_post_claim_preparation_failure_is_durable_with_sdk_responses(storage_runtime):
    harness = storage_runtime.harness
    harness.create()
    claimed, lease = harness.claim()
    harness.settings["enable_chat_orchestration"] = False
    try:
        with pytest.raises(harness.execution.HarnessExecutionError) as failure:
            harness.execution.prepare_harness_execution(
                claimed, settings=harness.settings, lease=lease,
            )
    finally:
        if not lease.stopped.is_set():
            lease.close(release=True)
    saved = harness.read()
    assert failure.value.durable_status == saved["status"] == "failed"
    assert saved["message_saved"] is True and saved["execution_lease"] is None
    assert len(harness.assistant_messages()) == 1
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0


def test_sdk_normalization_cannot_borrow_a_successor_lease(storage_runtime):
    harness = storage_runtime.harness
    harness.create()
    _claimed, lease = harness.claim()
    successor = harness.read()
    successor["execution_lease"]["token"] = "successor-owned-token"
    harness.runs.upsert_item(successor)
    before = deepcopy(harness.runs.items)
    try:
        with pytest.raises(harness.recovery.CheckpointError) as failure:
            lease.update({"status": "completed"})
    finally:
        lease.close()
    assert failure.value.code == "ownership_lost"
    assert harness.runs.items == before
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("boundary", ["conversation", "run"])
def test_foreign_owner_remains_inaccessible(storage_runtime, boundary):
    harness = storage_runtime.harness
    harness.create()
    if boundary == "conversation":
        changed = harness.conversations.read_item("conversation-1", "conversation-1")
        changed["user_id"] = "someone-else"
        harness.conversations.upsert_item(changed)
    else:
        changed = harness.read()
        changed["user_id"] = "someone-else"
        harness.runs.upsert_item(changed)
    response = storage_runtime.client.get(
        "/api/v2/orchestration/runs/run-1", query_string={"conversation_id": "conversation-1"},
    )
    assert response.status_code == 404
    assert "someone-else" not in response.get_data(as_text=True)
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0


def test_real_read_outage_is_not_a_missing_run(storage_runtime):
    harness = storage_runtime.harness
    harness.create()
    harness.runs.fail_reads = True
    response = _execute(storage_runtime, "run-1")
    assert response.status_code == 503
    assert "Private test" not in response.get_data(as_text=True)
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("malformed", [None, [], [["id", "run-1"]], "run-1"])
def test_output_read_does_not_coerce_non_mapping_documents(storage_runtime, monkeypatch, malformed):
    harness = storage_runtime.harness
    harness.create()
    store = harness.services().outputs
    output_errors = importlib.import_module("functions_orchestration_output_store")
    monkeypatch.setattr(harness.runs, "read_item", lambda **kwargs: malformed)
    with pytest.raises(output_errors.OutputError) as failure:
        store._point("run-1")
    assert failure.value.code == "output_record_invalid"
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0
