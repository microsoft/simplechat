#!/usr/bin/env python3
# test_workflow_handoff_end_to_end.py
"""
Functional test for one-time workflow hand-off, end to end.
Version: 0.261.239
Implemented in: 0.261.239

This test ensures that an accepted hand-off over a workspace query of 3 and of 200 documents:

* creates one disabled one-time workflow and queues exactly one durable run;
* completes that run through the real durable runtime and workflow runner, where the For each
  analyzes every document once under its own analysis producer and the report reads every saved
  record, whole for 3 records and in pages of at most 100 records and 128 KiB for 200;
* records ``one_time_status``, leaves the workflow idle and disabled, and readies chat delivery;
* posts one summary back to the chat through 6b-1's delivery worker and the real result reader;
* keeps private values out of every response and log, and internal hand-off IDs out of every app
  log from accept through delivery, including the runner's, the runtime's and the worker's.

Only the edges are faked: Cosmos containers, the model, the per-document Analyze, document
enumeration and the lease heartbeat. Checks use explicit raises, so they hold under ``python -O``.
"""

import copy
import dataclasses
import importlib
import json
import sys
import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
for _path in (APP_ROOT, ROOT / "functional_tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402

from test_orchestration_harness_routes import modules  # noqa: E402,F401
from test_orchestration_workflow_handoff_planner import _require, _same  # noqa: E402
from test_orchestration_workflow_handoff_routes import (  # noqa: E402
    accept,
    expect,
    expected_run_id,
    hw,  # noqa: F401
    internal_ids,
    private_values,
    query_loop,
    require_no_leak,
    seed_handoff_run,
    status_rows,
    stored_runs,
    stored_workflow,
)
from test_orchestration_workflow_proposal_routes import CONVERSATION, OWNER, _log_recorder, login  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_chat_delivery_fakes import make_conversation, make_world  # noqa: E402
from test_workflow_for_each_execution import LoopJournalContainer  # noqa: E402


MINIMUM_VERSION = "0.261.239"
# The report contract's bounds, written out so the observed report is checked against the contract
# rather than against the production constants under test.
PAGE_RECORDS = 100
PAGE_BYTES = 128 * 1024
REDUCTION_CHILDREN = 32
HANDOFF_ITEM_LIMIT = 500
DRIVE_LIMIT = 50
MODEL_NAME = "handoff-fixture"
RESPONSE_TOKENS = 16384
# Sized so 100 saved records fit one report request and 200 don't.
CONTEXT_WINDOW = 272000
WORKFLOW_CONVERSATION = "workflow-conversation"
FINDING_SENTENCE = "The clause sets out routine indemnity terms for the supplier and the customer."
# Nine sentences keep a record near 1.2 KB of values, so the 100-record cap, not the 128 KiB byte
# cap, ends each report page.
FINDING = " ".join([FINDING_SENTENCE] * 9)
WHOLE_REPLY = "The saved findings describe routine indemnity terms across the reviewed documents."
PAGE_NOTE = "The saved record describes routine indemnity findings."
_MISSING = object()


def without_private(document):
    return {key: value for key, value in document.items() if not str(key).startswith("_")}


def _app_modules():
    root = str(APP_ROOT.resolve()).lower()
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if not path:
            continue
        try:
            resolved = str(Path(path).resolve()).lower()
        except (OSError, ValueError):
            continue
        if resolved.startswith(root):
            yield module


def _rebind(monkeypatch, name, original, replacement):
    """Point every loaded app module whose ``name`` still holds ``original`` at ``replacement``."""
    bound = 0
    for module in _app_modules():
        if module.__dict__.get(name, _MISSING) is original:
            monkeypatch.setattr(module, name, replacement)
            bound += 1
    return bound


def _completion(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=None)


def _json_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))


class FixtureModel:
    """Answers each saved-record report stage the way the reporting contract expects."""

    def __init__(self, marker):
        self.marker = marker
        self.model_metadata = {
            "id": MODEL_NAME,
            "modelName": MODEL_NAME,
            "contextWindow": CONTEXT_WINDOW,
            "inputTokenLimit": CONTEXT_WINDOW,
            "outputTokenLimit": RESPONSE_TOKENS,
            "outputTokenAccounting": "total_generation",
            "responseLength": RESPONSE_TOKENS,
        }
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.wholes = []
        self.pages = []
        self.reductions = []
        self.supports = 0
        self.others = []

    def create(self, model=None, messages=None, **kwargs):
        content = str(((messages or [{}])[-1] or {}).get("content") or "")
        if self.marker not in content:
            self.others.append(len(content.encode("utf-8")))
            return _completion(WHOLE_REPLY)
        payload = json.loads(content.split(self.marker, 1)[1])
        if "inputs" in payload:
            self.wholes.append(sum(len(item.get("records") or []) for item in payload["inputs"]))
            return _completion(WHOLE_REPLY)
        if "chunks" in payload:
            chunks = payload["chunks"]
            self.reductions.append(len(chunks))
            notes = [note for chunk in chunks for note in chunk.get("notes") or []]
            conclusions = [
                {"text": notes[0]["text"], "supporting_records": notes[0]["supporting_records"]},
            ] if notes else []
            return _completion(json.dumps({
                "covered_chunks": [chunk["chunk_id"] for chunk in chunks], "conclusions": conclusions,
            }))
        if "supporting_records" in payload:
            self.supports += 1
            return _completion(json.dumps({"supported": True}))
        records = payload["records"]
        self.pages.append({
            "records": len(records),
            "value_bytes": sum(_json_bytes(record["values"]) for record in records),
            "request_bytes": len(content.encode("utf-8")),
        })
        return _completion(json.dumps({
            "record_explanations": [{"record_ref": record["record_ref"], "text": PAGE_NOTE} for record in records],
        }))


@pytest.fixture
def e2e(modules, monkeypatch, request):
    """``hw``'s accept route, wired to the real runtime, runner, result store and reader."""
    runner = importlib.import_module("functions_workflow_runner")
    runtime = importlib.import_module("functions_workflow_runtime")
    personal = importlib.import_module("functions_personal_workflows")
    result_store = importlib.import_module("functions_workflow_result_store")
    runtime_store = importlib.import_module("functions_workflow_runtime_store")
    execution = importlib.import_module("functions_workflow_execution")
    checkpoints = importlib.import_module("functions_document_analysis_checkpoints")
    access = importlib.import_module("functions_analysis_access")
    native = importlib.import_module("functions_native_analysis_results")
    reporting = importlib.import_module("functions_workflow_reporting")
    loop_inputs = importlib.import_module("functions_workflow_loop_inputs")
    worker = importlib.import_module("functions_workflow_chat_delivery_worker")
    reader = importlib.import_module("functions_workflow_result_reader")
    config = importlib.import_module("config")

    # hw fakes the result transport and the runtime journal for its route tests. Keep the real ones,
    # bound below to one in-memory journal, so the runner, runtime and reader share what they save.
    transport = {
        runtime: (
            "save_workflow_task_result", "load_workflow_task_result", "save_workflow_runtime_result",
            "load_workflow_runtime_result", "workflow_runtime_store", "WorkflowRuntimeLease",
            "signal_workflow_chat_delivery",
        ),
        result_store: (
            "save_workflow_task_result", "load_workflow_task_result", "save_workflow_runtime_result",
            "load_workflow_runtime_result",
        ),
    }
    reals = {
        (module, name): module.__dict__.get(name, _MISSING)
        for module, names in transport.items() for name in names
    }
    container_names = (
        "cosmos_personal_workflows_container",
        "cosmos_personal_workflow_runs_container",
        "cosmos_personal_workflow_run_items_container",
    )
    original_containers = {name: getattr(config, name, _MISSING) for name in container_names}

    hw = request.getfixturevalue("hw")
    for (module, name), value in reals.items():
        if value is not _MISSING:
            monkeypatch.setattr(module, name, value)

    journal = LoopJournalContainer()

    def make_store(workflow, run_id):
        return runtime_store.WorkflowRuntimeStore(journal, workflow, run_id, clock=lambda: hw.clock.now)

    def store_for(workflow, run_id, *args, **kwargs):
        return make_store(workflow, run_id)

    def results(*args, **kwargs):
        return result_store.WorkflowResultStore(journal)

    _rebind(monkeypatch, "workflow_runtime_store", runtime_store.workflow_runtime_store, store_for)
    for name in ("_configured_store", "_configured_result_store"):
        _rebind(monkeypatch, name, getattr(result_store, name), results)
    replacements = {
        "cosmos_personal_workflows_container": hw.workflows,
        "cosmos_personal_workflow_runs_container": hw.wf_runs,
        "cosmos_personal_workflow_run_items_container": journal,
    }
    for name, replacement in replacements.items():
        original = original_containers[name]
        if original is not _MISSING:
            _rebind(monkeypatch, name, original, replacement)
        monkeypatch.setattr(config, name, replacement, raising=False)
        monkeypatch.setattr(personal, name, replacement, raising=False)

    class SynchronousLease:
        """Drive the real journal synchronously; the renewable heartbeat has its own tests."""

        def __init__(self, store, owner_id=None, **kwargs):
            self.store = store
            self.owner_id = owner_id
            self.token = None

        def __enter__(self):
            self.token = self.store.claim(owner_id=self.owner_id)
            return self

        def check(self):
            return self.store.assert_owned(self.token)

        def __exit__(self, *args):
            if self.token:
                try:
                    self.store.release(self.token)
                except runtime_store.WorkflowRuntimeConflict:
                    # A wait or terminal transition already released the claim.
                    return False
            return False

    _rebind(monkeypatch, "WorkflowRuntimeLease", runtime_store.WorkflowRuntimeLease, SynchronousLease)

    signals = []

    def signal(user_id, run_id, *args, **kwargs):
        signals.append((user_id, run_id))

    _rebind(monkeypatch, "signal_workflow_chat_delivery", runtime.signal_workflow_chat_delivery, signal)

    # hw records the logs of the modules its route tests exercise; record every other app module too,
    # under any name it imported log_event as. functions_appinsights is swept as well, so a module
    # that imports log_event later, or inside a function, records too.
    logs = []
    real_log_event = importlib.import_module("functions_appinsights").log_event
    for module in list(_app_modules()):
        names = [name for name, value in list(module.__dict__.items()) if value is real_log_event]
        for name in names:
            monkeypatch.setattr(module, name, _log_recorder(logs, module.__name__))

    messages_container = SimpleNamespace(
        read_item=lambda item=None, partition_key=None, **kwargs: {"id": item or "user-message"},
        upsert_item=lambda body=None, **kwargs: body,
    )
    stubs = {
        "_ensure_execution_context": lambda *args, **kwargs: nullcontext(),
        "workflow_m365_manifests": lambda workflow, *args, **kwargs: ([], workflow),
        "_execute_workflow_file_sync": lambda *args, **kwargs: None,
        "_ensure_workflow_conversation": lambda *args, **kwargs: {"id": WORKFLOW_CONVERSATION, "user_id": OWNER},
        "_create_user_message": lambda conversation_id, *args, **kwargs: {
            "id": "user-message", "conversation_id": conversation_id,
        },
        "cosmos_messages_container": messages_container,
        "_initialize_workflow_assistant_tracking": lambda *args, **kwargs: ("assistant-message", None),
        "_prepare_workflow_url_access_context": lambda *args, **kwargs: {},
        "_attach_workflow_url_access_result": lambda result, *args, **kwargs: result,
        "_create_assistant_message": lambda *args, **kwargs: {"id": "assistant-message"},
        "_mirror_workflow_visualizations_to_created_conversations": lambda *args, **kwargs: None,
        "_add_workflow_activity_thought": lambda *args, **kwargs: None,
        "_create_workflow_priority_alert": lambda *args, **kwargs: None,
        "log_workflow_run": lambda *args, **kwargs: None,
        "get_settings": lambda *args, **kwargs: copy.deepcopy(hw.settings),
        "get_workflow_alert_signals": lambda *args, **kwargs: [],
        "capture_execution_identity": lambda *args, **kwargs: None,
        "workflow_alert_signal_scope": lambda *args, **kwargs: nullcontext(),
        "_workflow_delegation_scope": lambda *args, **kwargs: nullcontext(),
        "_apply_workflow_run_time_context": lambda workflow, *args, **kwargs: workflow,
    }
    for name, value in stubs.items():
        monkeypatch.setattr(runner, name, value, raising=False)

    world = SimpleNamespace(
        hw=hw, runner=runner, runtime=runtime, runtime_store=runtime_store, worker=worker, reader=reader,
        journal=journal, make_store=make_store, signals=signals, logs=logs,
        keys=[], sources={}, dispatches=[], max_items=[], consumptions=[],
        model=FixtureModel(reporting.REPORT_DATA_MARKER),
    )

    def use_documents(count):
        world.keys[:] = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"handoff-e2e-document-{index}")) for index in range(count)]
        world.sources.clear()
        for key in world.keys:
            world.sources[key] = {
                "document_id": key, "scope": "personal", "scope_id": OWNER, "source_kind": "tabular",
                "file_name": f"{key}.csv", "source_version": 1, "source_revision": "rev-1",
            }

    world.use_documents = use_documents

    def resolver(values, **kwargs):
        resolved = []
        for value in values:
            key = value if isinstance(value, str) else (value or {}).get("document_id")
            resolved.append({**world.sources[key], "authorization_status": "authorized"})
        return resolved

    def source_authorizer(user_id, values, **kwargs):
        return access.authorize_analysis_sources(user_id, values, **{**kwargs, "resolver": resolver})

    def documents(*args, **kwargs):
        world.max_items.append(kwargs.get("max_items"))
        for key in list(world.keys):
            yield {
                "document": {
                    "document_id": key, "file_name": world.sources[key]["file_name"],
                    "scope_type": "personal", "scope_id": OWNER,
                },
                "source": {
                    "document_id": key, "scope": "personal", "scope_id": OWNER,
                    "source_version": 1, "source_revision": "rev-1",
                },
                "availability": {"document_id": key, "scope_type": "personal", "scope_id": OWNER},
            }
        metadata = kwargs.get("capture_metadata")
        if isinstance(metadata, dict):
            metadata.update(complete=True, count=len(world.keys), count_exact=True)

    def reauthorize(bound_workflow, item, *args, **kwargs):
        return item

    _rebind(monkeypatch, "iter_workflow_loop_documents", loop_inputs.iter_workflow_loop_documents, documents)
    _rebind(
        monkeypatch, "reauthorize_workflow_loop_document", loop_inputs.reauthorize_workflow_loop_document, reauthorize,
    )

    def prepare(bound_workflow, run_id, task_id, actor_user_id, settings, *args, **kwargs):
        current = execution.current_workflow_execution()
        prepared = checkpoints.analysis_checkpoints_for_workflow(
            bound_workflow, run_id, task_id, user_id=actor_user_id, authorize=current.check, settings=settings,
            source_authorizer=source_authorizer, store=result_store.WorkflowResultStore(journal),
            **current.selectors(),
        )
        prepared.prepare()
        return prepared

    monkeypatch.setattr(runner, "_prepare_workflow_analysis_checkpoints", prepare)

    real_dispatch = runner._execute_workflow_dispatch

    def dispatch(execution_workflow, *args, **kwargs):
        action = execution_workflow.get("document_action") or {}
        if action.get("type") != "analyze":
            return real_dispatch(execution_workflow, *args, **kwargs)
        targets = list(action.get("document_ids") or [])
        _same(len(targets), 1, "the documents one item's Analyze targets")
        key = targets[0]
        producer = copy.deepcopy(execution_workflow.get("_analysis_producer"))
        world.dispatches.append((key, producer))
        source = world.sources[key]
        result = native.adapt_native_analysis_result(
            user_id=OWNER, conversation_id=WORKFLOW_CONVERSATION, source=source,
            complete_output={
                "status": "completed", "source_file_name": source["file_name"],
                "source_authorization": {"source": "workspace"}, "kind": "records",
                "value": [{"finding": FINDING}],
            },
            source_resolver=resolver, analysis_producer=producer,
        )
        return {"reply": result["reply"], "analysis_result": result}

    monkeypatch.setattr(runner, "_execute_workflow_dispatch", dispatch)
    monkeypatch.setattr(
        runner, "_resolve_model_workflow_client",
        lambda *args, **kwargs: (world.model, MODEL_NAME, "aoai"),
    )

    real_explain = runner.explain_saved_analysis

    def explain(*args, **kwargs):
        result = real_explain(*args, **kwargs)
        world.consumptions.append(copy.deepcopy((result or {}).get("analysis_consumption")))
        return result

    monkeypatch.setattr(runner, "explain_saved_analysis", explain)
    return world


def drive(e2e, run_id):
    """Continue the durable run the way the worker does, until it reaches a terminal state."""
    terminal = e2e.runtime.RUNTIME_TERMINAL_STATES
    state = None
    for attempt in range(1, DRIVE_LIMIT + 1):
        e2e.runtime.continue_durable_workflow_run(stored_workflow(e2e.hw), run_id)
        state = e2e.make_store(stored_workflow(e2e.hw), run_id).read()["state"]
        if state in terminal:
            return attempt, state
    raise AssertionError(f"The hand-off run did not finish in {DRIVE_LIMIT} continuations; it is {state!r}.")


def deliver(e2e, run):
    """Deliver the finished run through 6b-1's worker, reading its result with the real reader."""
    world = make_world(run=without_private(run))
    world.workflows.put(stored_workflow(e2e.hw))
    world.conversations.put(make_conversation(id=CONVERSATION, user_id=OWNER))
    reads = []

    def read_result(user_id, workflow_id, run_id, **kwargs):
        result = e2e.reader.read_workflow_result(
            user_id, workflow_id, run_id, **kwargs,
            containers={"workflows": world.workflows, "runs": world.runs, "run_items": e2e.journal},
        )
        reads.append(copy.deepcopy(result))
        return result

    services = dataclasses.replace(
        world.services,
        runtime_store_factory=lambda user_id, workflow_id, run_id: e2e.make_store(
            {"id": workflow_id, "user_id": user_id}, run_id,
        ),
        runtime_conflict_error=e2e.runtime_store.WorkflowRuntimeConflict,
        runtime_unavailable_error=e2e.runtime_store.RuntimeUnavailable,
        read_workflow_result=read_result,
        result_unavailable_error=e2e.reader.WorkflowResultUnavailable,
    )
    outcome = e2e.worker.process_workflow_chat_delivery(OWNER, run["id"], services=services)
    return outcome, world, reads


def require_no_drive_leak(e2e):
    """No app log, from accept through delivery, carries a private value or an internal hand-off ID."""
    hw = e2e.hw
    private = private_values(hw)
    internal = internal_ids(hw)
    leaks = set()
    entries = [*hw.record.logs, *e2e.logs]
    for entry in entries:
        text = entry["message"] + entry["extra"]
        leaks.update((entry["source"], "private", value[:12]) for value in private if value in text)
        leaks.update((entry["source"], "internal", value[:12]) for value in internal if value in text)
    _require(not leaks, f"Logs carry values they must not: {sorted(leaks)!r}")
    delivery_source = e2e.worker.delivery_log.__module__
    _require(
        any(entry["source"] == delivery_source and "Delivery closed." in entry["message"] for entry in entries),
        "The delivery worker's logs were not recorded, so the leak check would miss them.",
    )
    return entries


def require_consumption(e2e, count):
    _same(len(e2e.consumptions), 1, "saved-record reports")
    consumption = e2e.consumptions[0]
    _require(isinstance(consumption, dict), f"The report recorded no consumption: {consumption!r}")
    _same(
        (consumption.get("input_kind"), consumption.get("record_count")), ("workflow_records", count),
        "what the report consumed",
    )
    _same(
        consumption.get("deterministic_values"), {"accepted_record_count": count, "accepted_subset_only": False},
        "the report's computed values",
    )
    _same(len(consumption.get("context_budgets") or []), 1, "the report's recorded budgets")
    model = e2e.model
    _same(model.others, [], "model calls outside the saved-record report")
    if count <= PAGE_RECORDS:
        _same((consumption.get("mode"), consumption.get("page_count")), ("complete_input", 0), "a small report's mode")
        _same(model.wholes, [count], "whole-input report calls")
        _same((model.pages, model.reductions, model.supports), ([], [], 0), "paged report calls for a small report")
        return consumption
    pages = -(-count // PAGE_RECORDS)
    _same(
        (consumption.get("mode"), consumption.get("page_count")), ("record_pages", pages),
        f"a large report's mode (pages {model.pages!r}, budgets {consumption.get('context_budgets')!r})",
    )
    _same((consumption.get("checkpoints") or {}).get("page_count"), pages, "the checkpointed page count")
    _same(model.wholes, [], "whole-input report calls for a large report")
    _same(
        [page["records"] for page in model.pages],
        [min(PAGE_RECORDS, count - index * PAGE_RECORDS) for index in range(pages)],
        f"records per report page (request bytes {[page['request_bytes'] for page in model.pages]})",
    )
    for page in model.pages:
        _require(page["value_bytes"] <= PAGE_BYTES, f"A report page carried {page['value_bytes']} bytes of records.")
    _require(
        model.reductions and all(0 < chunks <= REDUCTION_CHILDREN for chunks in model.reductions),
        f"Every reduction stays within {REDUCTION_CHILDREN} chunks: {model.reductions!r}",
    )
    _require(model.supports >= 1, "The report checked its conclusion against the original records.")
    return consumption


@pytest.mark.parametrize("count", [3, 200], ids=["three-documents", "two-hundred-documents"])
def test_an_accepted_handoff_runs_once_and_posts_its_summary_to_chat(e2e, count):
    hw = e2e.hw
    e2e.use_documents(count)
    seed_handoff_run(hw, loop=query_loop(hw))
    login(hw)

    response = accept(hw)
    payload = expect(response, 201)
    require_no_leak(hw, response)

    _same((payload["state"], payload["created"]), ("queued", True), "the accept response")
    workflow = stored_workflow(hw)
    _require(workflow is not None, "The accept created no workflow.")
    _same(workflow["is_enabled"], False, "a hand-off workflow is created disabled")
    _same((workflow.get("origin") or {}).get("one_time"), True, "a hand-off workflow is one-time")
    _same(len(hw.record.queued), 1, "queue calls")
    runs = stored_runs(hw)
    _same(len(runs), 1, "durable runs")
    run_id = runs[0]["id"]
    _same(run_id, expected_run_id(hw.workflow_id, hw.handoff_id), "the deterministic run id")
    _same(payload["run"]["id"], run_id, "the accepted run")
    _same((runs[0].get("chat_invocation") or {}).get("handoff_id"), hw.handoff_id, "the run's hand-off")

    continuations, state = drive(e2e, run_id)

    _same(state, "completed", f"the runtime state after {continuations} continuation(s)")
    runs = stored_runs(hw)
    _same(len(runs), 1, "durable runs after the drive")
    run = runs[0]
    _same(run["status"], "completed", "the run's status")
    _same(len(hw.record.queued), 1, "queue calls after the drive")
    workflow = stored_workflow(hw)
    one_time = workflow.get("one_time_status") or {}
    _same(set(one_time), {"state", "run_id", "completed_at"}, "the one-time status fields")
    _same((one_time["state"], one_time["run_id"]), ("completed", run_id), "the one-time status")
    _require(isinstance(one_time["completed_at"], str) and one_time["completed_at"], "The one-time status has no time.")
    _same((workflow.get("active_run_id"), workflow["is_enabled"]), ("", False), "the finished hand-off workflow")

    analyzed = [key for key, _producer in e2e.dispatches]
    _same(len(analyzed), count, "Analyze dispatches")
    _same(set(analyzed), set(e2e.keys), "the analyzed documents")
    executions = {(producer or {}).get("execution_id") for _key, producer in e2e.dispatches}
    _require(
        None not in executions and len(executions) == count,
        f"Each document is analyzed under its own producer: {len(executions)} for {count}.",
    )
    _require(e2e.max_items, "The For each never enumerated its documents.")
    _same(set(e2e.max_items), {HANDOFF_ITEM_LIMIT}, "the For each's item limit")

    require_consumption(e2e, count)

    _require((OWNER, run_id) in e2e.signals, f"The finished run never readied chat delivery: {e2e.signals!r}")
    outcome, world, reads = deliver(e2e, run)
    _same(outcome, e2e.worker.OUTCOME_DELIVERED, "the delivery outcome")
    _same(len(world.delivery_messages()), 1, "summaries posted to chat")
    _same(len(reads), 1, "result reads")
    expected = [WHOLE_REPLY] if count <= PAGE_RECORDS else [
        f"Read all {count} accepted saved records in {-(-count // PAGE_RECORDS)} model-sized pages.",
        f"- {PAGE_NOTE} (Supporting saved records: ",
    ]
    delivered = json.dumps(reads[0], default=str)
    for text in expected:
        _require(text in delivered, f"The delivered result is not the run's report; it lacks {text!r}: {reads[0]!r}")

    rows = status_rows(hw)
    _same(len(rows), 1, "the conversation's chat-started runs")
    require_no_drive_leak(e2e)


def test_version_is_at_least_the_handoff_release():
    assert_app_version_at_least(MINIMUM_VERSION)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
