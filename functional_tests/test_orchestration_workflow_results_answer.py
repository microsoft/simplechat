# test_orchestration_workflow_results_answer.py
"""
Functional test for the workflow_results orchestration capability (answer lineage, finalize failure path, leak surfaces).
Version: 0.261.217
Implemented in: 0.261.217
This test ensures workflow_results answer lineage is retained for read-time masking while excerpt text and sidecars stay off public orchestration surfaces.
"""

import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(ROOT / "functional_tests"))

from functions_saved_analysis import sanitize_saved_analysis_messages  # noqa: E402
from test_orchestration_harness_routes import modules  # noqa: E402,F401
from test_support.orchestration_harness_execution import (  # noqa: E402
    HarnessEnvironment,
    compose_step,
    decoded_frames,
    input_binding,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402


USER_ID = "owner"
CONVERSATION_ID = "conversation-1"
WORKFLOW_ID = "wf-answer-lineage-7c4f"
RUN_ID = "run-answer-lineage-3b9d"
HANDLE = "workflow_results_answer_handle_2a71"
WORKFLOW_NAME = "Answer Lineage Digest"
EXCERPT_MARKER = "WORKFLOW_RESULT_EXCERPT_MARKER_8f1c2a"
COMPOSED_MARKER = "COMPOSED_FROM_WORKFLOW_RESULT_0a61"
RESULT_SHA = "c" * 64
NONCE = "0123456789abcdef"
LOCAL_ZONE = "America/New_York"
COMPLETED_AT = "2026-09-29T14:05:00+00:00"
RUN_TIME_FRAGMENT = "Sep"
RESULTS_SETTINGS = {
    "enable_chat_orchestration": True,
    "enable_chat_workflow_results": True,
    "allow_user_workflows": True,
    "require_member_of_workflow_user": False,
    "chat_orchestration_enabled_capabilities": [],
}


class FakeWorkflowResultUnavailable(Exception):
    """Reader refusal test double with the public ``code`` shape used by production."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def test_version_is_at_least_workflow_results_answer_release():
    assert_app_version_at_least("0.261.217")


@pytest.fixture
def results_module(modules):
    import importlib

    return importlib.import_module("functions_orchestration_workflow_results")


@pytest.fixture
def executor_module(modules):
    import importlib

    return importlib.import_module("functions_orchestration_executor")


@pytest.fixture
def recovery_module(modules):
    import importlib

    return importlib.import_module("functions_orchestration_recovery")


@pytest.fixture
def route_module(modules):
    import importlib

    return importlib.import_module("route_backend_orchestration")


def _planning():
    return {
        "conversation_private": True,
        "workflow_results": {"ready": True},
        "catalog": {"workflows": [{"handle": HANDLE, "name": WORKFLOW_NAME}]},
        "handles": {"workflows": {HANDLE: {"id": WORKFLOW_ID}}},
        "time_zone": LOCAL_ZONE,
        "request_local_time": "Tuesday, September 29, 2026, 10:30 AM EDT",
    }


def _workflow_results_step(step_id="read_digest"):
    return {
        "step_id": step_id,
        "capability_id": "workflow_results",
        "arguments": {"workflow": HANDLE, "selector": "latest"},
        "inputs": {},
        "outputs": [{"name": "result", "kind": "structured-v1"}],
    }


def _answer_step():
    return compose_step(
        "answer",
        inputs={"workflow_notes": {"binding": input_binding("read_digest", "result"), "allow_partial": False}},
    )


def _completed_run():
    return {
        "id": RUN_ID,
        "workflow_id": WORKFLOW_ID,
        "status": "completed",
        "started_at": "2026-09-29T14:00:00+00:00",
        "completed_at": COMPLETED_AT,
    }


def _result_payload(marker=EXCERPT_MARKER):
    return {
        "descriptor": {
            "version": "workflow-result-v1",
            "workflow_id": WORKFLOW_ID,
            "run_id": RUN_ID,
            "workflow_name": WORKFLOW_NAME,
            "status": "completed",
            "completed_at": COMPLETED_AT,
            "result_sha256": RESULT_SHA,
            "available": True,
        },
        "excerpts": [{
            "label": "Summary",
            "kind": "text",
            "final": True,
            "text": marker,
            "truncated": False,
            "note": "",
        }],
        "saved_inputs": [],
        "partial": False,
        "truncated": False,
        "analysis_only": False,
        "omitted_outputs": 0,
    }


def _retained_value(outcome="read"):
    return {
        "version": 1,
        "outcome": outcome,
        "reason": None if outcome == "read" else "workflow_result_unavailable",
        "workflow_name": WORKFLOW_NAME,
        "status": "completed",
        "completed_at": COMPLETED_AT,
        "partial": False,
        "truncated": False,
        "newer_in_progress": False,
        "context": (
            {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "result_sha256": RESULT_SHA}
            if outcome == "read" else None
        ),
    }


def _install_workflow_result_runtime(results_module, monkeypatch, *, authorize=None):
    calls = {"queries": [], "reads": [], "reader": [], "authorize": []}
    planning = _planning()

    def query_runs(user_id, query, parameters):
        calls["queries"].append((user_id, query, deepcopy(parameters)))
        if query == results_module._LATEST_QUERY:
            return [_completed_run()]
        if query == results_module._IN_PROGRESS_QUERY:
            return []
        if query == results_module._COMPLETED_ON_QUERY:
            return [_completed_run()]
        raise AssertionError(f"unexpected query: {query}")

    def read_result(user_id, workflow_id, run_id, **options):
        calls["reader"].append((user_id, workflow_id, run_id, deepcopy(options)))
        return _result_payload()

    def authorize_context(user_id, context, **options):
        calls["authorize"].append((user_id, deepcopy(context), deepcopy(options)))
        if authorize is not None:
            authorize(user_id, context, **options)
        return None

    monkeypatch.setattr(results_module, "workflow_results_settings_gate", lambda settings: None)
    monkeypatch.setattr(results_module, "workflow_results_gate", lambda settings, roles: None)
    monkeypatch.setattr(results_module, "refresh_workflow_planning_privacy", lambda current, conversation, user_id: planning)
    monkeypatch.setattr(results_module, "_read_conversation", lambda conversation_id: {
        "id": CONVERSATION_ID,
        "user_id": USER_ID,
    })
    monkeypatch.setattr(results_module, "_read_workflow", lambda user_id, workflow_id: {
        "id": WORKFLOW_ID,
        "user_id": USER_ID,
        "name": WORKFLOW_NAME,
    })
    monkeypatch.setattr(results_module, "_query_runs", query_runs)
    monkeypatch.setattr(results_module, "_read_result", read_result)
    monkeypatch.setattr(results_module, "_authorize_result_context", authorize_context)
    monkeypatch.setattr(results_module, "_reader_unavailable_type", lambda: FakeWorkflowResultUnavailable)
    monkeypatch.setattr(results_module, "_new_nonce", lambda: NONCE)
    return calls


def _results_harness(monkeypatch, results_module, *, replies=None, authorize=None):
    env = HarnessEnvironment(monkeypatch)
    env.settings.update(RESULTS_SETTINGS)
    real_normalize = env.schema.normalize_plan

    def normalize(raw, *args, **kwargs):
        capability_ids = kwargs.get("available_capability_ids")
        if capability_ids is not None and "workflow_results" not in capability_ids:
            kwargs["available_capability_ids"] = [*capability_ids, "workflow_results"]
        kwargs.setdefault("workflow_planning", _planning())
        return real_normalize(raw, *args, **kwargs)

    monkeypatch.setattr(env.schema, "normalize_plan", normalize)
    calls = _install_workflow_result_runtime(results_module, monkeypatch, authorize=authorize)
    env.create(
        [_answer_step(), _workflow_results_step()],
        replies=list(replies or [f"{COMPOSED_MARKER}: {EXCERPT_MARKER}"]),
        final_response=input_binding("answer", "answer"),
        workflow_planning=_planning(),
        time_zone=LOCAL_ZONE,
    )
    return env, calls


def _run_harness(env):
    emitted = []
    execution = env.prepare()
    try:
        frames = decoded_frames(execution.execute(emit=emitted.append))
    finally:
        execution.close()
    messages = env.assistant_messages()
    saved = env.read()
    return SimpleNamespace(emitted=emitted, frames=frames, messages=messages, saved=saved)


def _json(value):
    return json.dumps(value, sort_keys=True, default=str)


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _require_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def _assert_absent(value, *needles):
    text = _json(value)
    for needle in needles:
        if needle in text:
            raise AssertionError(f"{needle!r} unexpectedly appeared in {text}")


def test_successful_answer_uses_plural_lineage_metadata_and_safe_disclosure(monkeypatch, results_module):
    env, calls = _results_harness(monkeypatch, results_module)
    outcome = _run_harness(env)
    message = outcome.messages[0]
    metadata = message["metadata"]
    content = message["content"]
    fixed_note = content.replace(f"{COMPOSED_MARKER}: {EXCERPT_MARKER}", "")

    _require_equal(outcome.saved["status"], "completed", "run should complete")
    _require_equal(metadata.get("workflow_result_contexts"), [{
        "workflow_id": WORKFLOW_ID,
        "run_id": RUN_ID,
        "result_sha256": RESULT_SHA,
    }], "plural lineage contexts should be saved")
    _require("workflow_result" not in metadata, "singular workflow_result metadata key must not be used")
    _require(WORKFLOW_NAME in content, "read disclosure should name the workflow")
    _require("workflow was not re-run" in content, "read disclosure should say the workflow was not re-run")
    _require_equal(calls["authorize"], [
        (USER_ID, {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "result_sha256": RESULT_SHA}, {}),
        (USER_ID, {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "result_sha256": RESULT_SHA}, {}),
    ], "lineage should be authorized before save and before publish")
    _assert_absent(content, WORKFLOW_ID, RUN_ID, HANDLE)
    _assert_absent(fixed_note, EXCERPT_MARKER)
    _require_equal(content.count(EXCERPT_MARKER), 1, "excerpt marker should appear only in composed content")


def test_pre_publish_reauthorization_failure_publishes_fixed_failure_and_overwrites_at_rest(monkeypatch, results_module):
    def fail_second_authorization(user_id, context, **options):
        if len(authorizations) >= 2:
            raise FakeWorkflowResultUnavailable("workflow_result_changed")

    authorizations = []

    def authorize(user_id, context, **options):
        authorizations.append((user_id, deepcopy(context)))
        fail_second_authorization(user_id, context, **options)

    env, _calls = _results_harness(monkeypatch, results_module, authorize=authorize)
    outcome = _run_harness(env)
    message = outcome.messages[0]
    content = message["content"]
    saved = env.read()

    _require_equal(saved["status"], "failed", "changed result should fail the run")
    _require_equal(saved["failure"]["code"], "workflow_result_changed", "failure code should be workflow_result_changed")
    _require(
        "A workflow result this answer used changed or is no longer available" in content,
        "fixed workflow-result-changed failure should be published",
    )
    _assert_absent(content, WORKFLOW_NAME, RUN_TIME_FRAGMENT, EXCERPT_MARKER, COMPOSED_MARKER)
    _require("the workflow was not re-run" not in content, "failure path must not keep the read disclosure")
    _require("workflow_result_contexts" not in message["metadata"], "failed answer should carry no lineage metadata")
    _assert_absent(saved["message"], EXCERPT_MARKER, COMPOSED_MARKER)
    _require_equal(len(authorizations), 2, "pre-publish reauthorization should run after first lineage check")


def test_run_summary_and_detail_rows_are_allowlisted_against_message_summary_and_sidecar(route_module, monkeypatch):
    monkeypatch.setattr(route_module, "_run_response_removed", lambda record: False)
    record = {
        "id": "run-route-allowlist",
        "run_id": "run-route-allowlist",
        "conversation_id": CONVERSATION_ID,
        "user_id": USER_ID,
        "status": "completed",
        "outcome": "completed",
        "message": f"message {EXCERPT_MARKER}",
        "summary": f"summary {EXCERPT_MARKER}",
        "workflow_results": {"context": {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID}, "nonce": EXCERPT_MARKER},
        "task_results": {"read_digest": {"secret": EXCERPT_MARKER}},
        "plan_summary": {"title": "Safe title"},
        "capabilities_used": ["workflow_results", "compose"],
        "artifacts": [],
        "outputs": [],
        "failure": None,
    }

    summary = route_module._run_summary_row(deepcopy(record))
    detail = route_module._run_detail_row(deepcopy(record))

    for projected in (summary, detail):
        _require("message" not in projected, "route projection must not include run message")
        _require("summary" not in projected, "route projection must not include run summary")
        _require("workflow_results" not in projected, "route projection must not include workflow_results sidecar")
        _require("task_results" not in projected, "route projection must not include task_results")
        _assert_absent(projected, EXCERPT_MARKER, WORKFLOW_ID, RUN_ID)


def test_sidecar_stays_server_only_and_restore_reauthorizes_or_fails_closed(
    monkeypatch,
    results_module,
    executor_module,
    recovery_module,
):
    _install_workflow_result_runtime(results_module, monkeypatch)
    monkeypatch.setattr(results_module, "require_result_service", lambda context: context.result_service)
    from functions_orchestration_result_contracts import ProducerIdentity, TaskResult

    producer = ProducerIdentity(
        USER_ID,
        CONVERSATION_ID,
        "run-1",
        1,
        "read_digest",
        "workflow_results",
        "task-result-v1",
    )

    output = results_module.run_workflow_results(
        _workflow_results_step(),
        SimpleNamespace(
            result_service=_MemoryResultService(_retained_value()),
            plan_contract_version=2,
            run_id="run-1",
            attempt_root_run_id="run-1",
            conversation_id=CONVERSATION_ID,
            workflow_planning=_planning(),
            user_roles=["User"],
            settings=deepcopy(RESULTS_SETTINGS),
            time_zone=LOCAL_ZONE,
            result_producer=lambda current_step: producer,
            result_guard_token_for_step=lambda step_id: "guard-token",
            result_input_fingerprint_for_step=lambda step_id: "input-fingerprint",
        ),
        settings=deepcopy(RESULTS_SETTINGS),
        user_id=USER_ID,
    )
    step = {**_workflow_results_step(), "role": "gather"}
    record = executor_module._step_record(
        SimpleNamespace(run_id="run-1"),
        step,
        0,
        "completed",
        output,
        "2026-09-29T14:00:00+00:00",
        "2026-09-29T14:05:00+00:00",
        7,
    )
    task_result = output["task_result"].to_dict()
    public = recovery_module.public_execution_fields({
        "attempt_index": 1,
        "status": "completed",
        "outcome": "completed",
        "failure": None,
        "failures": [],
        "task_results": {"read_digest": task_result},
        "workflow_results": output["workflow_results"],
    })
    restore_context = SimpleNamespace(
        result_service=_MemoryResultService(_retained_value()),
        workflow_planning=_planning(),
        user_roles=["User"],
        settings=deepcopy(RESULTS_SETTINGS),
        conversation_id=CONVERSATION_ID,
    )
    restored = executor_module._restore_workflow_results(
        step,
        restore_context,
        "completed",
        {"status": "completed", "task_result": output["task_result"]},
        user_id=USER_ID,
    )

    def reject_authorization(user_id, context, **options):
        raise FakeWorkflowResultUnavailable("workflow_result_changed")

    _install_workflow_result_runtime(results_module, monkeypatch, authorize=reject_authorization)
    failed_restore_context = SimpleNamespace(
        result_service=_MemoryResultService(_retained_value()),
        workflow_planning=_planning(),
        user_roles=["User"],
        settings=deepcopy(RESULTS_SETTINGS),
        conversation_id=CONVERSATION_ID,
    )
    failed_restore = executor_module._restore_workflow_results(
        step,
        failed_restore_context,
        "completed",
        {"status": "completed", "task_result": output["task_result"]},
        user_id=USER_ID,
    )

    _require_equal(record["workflow_results"]["context"]["run_id"], RUN_ID, "server step record should keep sidecar")
    _assert_absent(task_result, EXCERPT_MARKER, RUN_ID, WORKFLOW_ID, NONCE)
    _assert_absent(public, EXCERPT_MARKER, RUN_ID, WORKFLOW_ID, NONCE)
    _require_equal(restored["workflow_results"]["context"]["run_id"], RUN_ID, "restore should rebuild sidecar")
    _require("workflow_results" not in failed_restore, "failed restore should leave sidecar missing")
    _require(isinstance(TaskResult.from_dict(task_result), TaskResult), "persisted task result should remain valid")


def test_results_run_events_and_thought_shaped_payloads_do_not_contain_excerpt_marker(monkeypatch, results_module):
    import importlib

    thoughts_module = importlib.import_module("functions_thoughts")
    stored_thoughts = _RecordingThoughtsContainer()
    tracked_thoughts = []
    real_add_thought = thoughts_module.ThoughtTracker.add_thought

    def record_add_thought(self, step_type, content, detail=None, activity=None):
        tracked_thoughts.append({"content": content, "detail": detail, "activity": deepcopy(activity)})
        return real_add_thought(self, step_type, content, detail, activity)

    # Stored thoughts are served by route_backend_thoughts without lineage masking, so a
    # results run must never persist excerpt or composed text there.
    monkeypatch.setattr(thoughts_module, "cosmos_thoughts_container", stored_thoughts)
    monkeypatch.setattr(thoughts_module.ThoughtTracker, "add_thought", record_add_thought)
    env, _calls = _results_harness(monkeypatch, results_module, replies=[f"{COMPOSED_MARKER}: clean answer"])
    outcome = _run_harness(env)
    event_payloads = [*_decode_maybe_sse(outcome.emitted), *outcome.frames]
    thought_shaped = [
        event for event in event_payloads
        if isinstance(event, dict) and ("content" in event or "detail" in event or event.get("type") == "thought")
    ]

    _require_equal(outcome.saved["status"], "completed", "results run should complete")
    _assert_absent(event_payloads, EXCERPT_MARKER)
    for thought in thought_shaped:
        _assert_absent({key: thought.get(key) for key in ("content", "detail")}, EXCERPT_MARKER)
    _assert_absent(stored_thoughts.items, EXCERPT_MARKER, COMPOSED_MARKER)
    _assert_absent(tracked_thoughts, EXCERPT_MARKER, COMPOSED_MARKER)


class _RecordingThoughtsContainer:
    def __init__(self):
        self.items = []

    def upsert_item(self, body, *args, **kwargs):
        self.items.append(deepcopy(body))
        return body

    def create_item(self, body, *args, **kwargs):
        self.items.append(deepcopy(body))
        return body

    def patch_item(self, item, partition_key, patch_operations, *args, **kwargs):
        self.items.append({"id": item, "patch": deepcopy(patch_operations)})
        return {}


def test_stored_answer_with_workflow_result_contexts_is_masked_when_source_changes_or_is_deleted():
    message = {
        "id": "assistant-workflow-result-answer",
        "conversation_id": CONVERSATION_ID,
        "role": "assistant",
        "content": f"stored answer {EXCERPT_MARKER}",
        "timestamp": "2026-09-29T14:06:00+00:00",
        "metadata": {
            "workflow_result_contexts": [{
                "workflow_id": WORKFLOW_ID,
                "run_id": RUN_ID,
                "result_sha256": RESULT_SHA,
            }],
        },
        "hybrid_citations": [{"secret": EXCERPT_MARKER}],
        "web_search_citations": [],
        "agent_citations": [],
        "thoughts": [{"content": EXCERPT_MARKER}],
    }

    # This calls the same masking entry point used by chat and orchestration read routes; the
    # Flask route adds authentication/storage plumbing that is unrelated to the lineage decision.
    readable = sanitize_saved_analysis_messages(
        [deepcopy(message)],
        USER_ID,
        workflow_result_reader=lambda user_id, context: None,
        conversation_reader=lambda conversation_id: {"id": conversation_id, "user_id": USER_ID},
    )[0]
    masked_deleted = sanitize_saved_analysis_messages(
        [deepcopy(message)],
        USER_ID,
        workflow_result_reader=lambda user_id, context: (_ for _ in ()).throw(LookupError("deleted")),
        conversation_reader=lambda conversation_id: {"id": conversation_id, "user_id": USER_ID},
    )[0]
    masked_changed = sanitize_saved_analysis_messages(
        [deepcopy(message)],
        USER_ID,
        workflow_result_reader=lambda user_id, context: (_ for _ in ()).throw(ValueError("changed")),
        conversation_reader=lambda conversation_id: {"id": conversation_id, "user_id": USER_ID},
    )[0]

    _require_equal(readable["content"], f"stored answer {EXCERPT_MARKER}", "readable source should keep content")
    for masked in (masked_deleted, masked_changed):
        _require_equal(
            masked["content"],
            "This answer is unavailable because access to the workflow result it used could not be confirmed.",
            "deleted or changed source should mask content",
        )
        _require_equal(
            masked["metadata"]["workflow_result"],
            {"version": "workflow-result-v1", "available": False},
            "masked message should carry unavailable descriptor",
        )
        _assert_absent(masked, EXCERPT_MARKER, WORKFLOW_ID, RUN_ID)


class _MemoryResultService:
    def __init__(self, value):
        self.value = deepcopy(value)
        self.persisted = []
        self.opened = []
        self.access = SimpleNamespace(authorize_producer=lambda producer, for_write=False: None)

    def persist_task_result(
        self, *, producer, role, status, outputs, sources, origin, guard_token, upstream, input_fingerprint,
    ):
        from functions_orchestration_result_contracts import ResultRef, TaskResult, canonical_bytes

        self.persisted.append({
            "producer": producer,
            "role": role,
            "status": status,
            "outputs": [(output.name, output.kind, deepcopy(output.value)) for output in outputs],
            "sources": list(sources),
            "origin": origin,
            "guard_token": guard_token,
            "upstream": tuple(upstream),
            "input_fingerprint": input_fingerprint,
        })
        references = tuple(
            ResultRef(
                producer=producer,
                output_name=output.name,
                kind=output.kind,
                manifest_sha256="d" * 64,
                content_sha256="e" * 64,
                size_bytes=max(1, len(canonical_bytes(output.value))),
                item_count=output.completeness.actual_count,
                completeness=output.completeness,
                columns=(),
                character_count=None,
            )
            for output in outputs
        )
        return TaskResult(producer=producer, role=role, status=status, outputs=references)

    def open_result(self, reference, allow_partial=True):
        self.opened.append((reference, allow_partial))
        value = deepcopy(self.value)

        class Opened:
            def read_value(self):
                return deepcopy(value)

        return Opened()


def _decode_maybe_sse(values):
    decoded = []
    for value in values:
        if isinstance(value, str) and value.startswith("data:"):
            decoded.extend(decoded_frames([value]))
        else:
            decoded.append(value)
    return decoded


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
