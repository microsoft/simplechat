# test_orchestration_render_resume.py
"""
Observe checkpoint-pinned Render files without performing scheduler work.
Version: 0.261.127
Implemented in: 0.261.127

Real output persistence, source authorization, committed messages and StepResult
builders exercise exact resume bindings and current readiness. Retry claims,
rendering, model execution and stale completion fallbacks are forbidden.
"""

import importlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from functions_generated_export_contracts import GeneratedFileExportRequest
from functions_orchestration_output_store import OutputStorageError
from functions_orchestration_rendering import resume_render_file
from functions_orchestration_results import NamedOutput
from test_orchestration_output_lifecycle import lifecycle, production_modules  # noqa: F401
from test_support.orchestration_results import complete


@pytest.fixture
def resumption(lifecycle):
    world = lifecycle
    producer = world.add_render_step("json_file")
    step = {
        "step_id": "json_file", "capability_id": "render_file", "role": "render", "enabled": True,
        "arguments": {
            "file_name": "json_file.json", "output_format": "json", "profile": "exact_records_v1",
        },
    }
    run = world.runs.read_item("run-1", "conversation-1")
    run["plan"]["steps"] = [
        deepcopy(step) if entry["step_id"] == step["step_id"] else entry
        for entry in run["plan"]["steps"]
    ]
    world.runs.upsert_item(run)
    reader = world.service.results.open_result(world.saved.output("findings"))
    context = SimpleNamespace(
        plan_contract_version=2, execution_deadline_at=world.deadline.isoformat(),
        result_producer=lambda current: producer, allow_generated_files=False,
    )
    case = SimpleNamespace(
        world=world, producer=producer, step=step, context=context, user_id="owner",
        service_factory=Mock(return_value=world.service),
        resolve_inputs=Mock(return_value={"source": reader}), cancel_requested=None, forbidden=None,
        effect_snapshot=None,
    )
    yield case
    if case.forbidden is not None and case.forbidden.call_count:
        raise AssertionError("Observation attempted execution or retry admission.")
    if case.effect_snapshot is not None and case.effect_snapshot != persistence_snapshot(world):
        raise AssertionError("Render observation changed durable state or transport effects.")


def pending_result(case, output):
    pending = case.world.modules.schema.build_step_result(
        status="waiting", summary="The file is pending.",
        wait={"kind": "orchestration_output", "output_id": output["output_id"]},
    )
    pending["outputs"] = [{"state": "completed", "file_name": "PRIVATE stale file"}]
    pending["artifacts"] = [{"artifact_message_id": "PRIVATE stale artifact"}]
    return pending


def completed_result(case, output):
    saved = case.world.modules.schema.build_step_result(
        status="completed", summary="PRIVATE cached completion",
        artifacts=[{"artifact_message_id": "PRIVATE stale artifact"}],
    )
    saved["outputs"] = [{
        **deepcopy(output), "state": "completed", "file_name": "PRIVATE cached name",
        "artifact_message_id": "PRIVATE stale artifact", "row_count": 999999,
    }]
    return saved


def persistence_snapshot(world):
    return deepcopy({
        "runs": world.runs.items, "messages": world.messages.items, "conversations": world.conversations.items,
        "results": world.results.container.items, "artifacts": world.blobs.data,
        "result_blobs": world.results.blobs.records,
        "writes": (
            world.runs.sequence, world.messages.sequence, world.conversations.sequence,
            world.results.container.sequence, world.blobs.uploads, world.blobs.deletes,
            len(world.results.blobs.uploads), len(world.results.blobs.deletes), world.results.blobs.etag_counter,
        ),
        "renders": world.render_calls,
    })


def forbid_execution(case, monkeypatch):
    forbidden = Mock(side_effect=AssertionError("A Render resumer attempted execution or retry admission."))
    case.forbidden = forbidden
    for name in ("ensure_output", "render_attempt", "reconcile", "claim_due", "manual_retry", "renderer"):
        monkeypatch.setattr(case.world.service, name, forbidden)
    for name in ("ensure", "claim_due", "manual_retry", "prepare_intent", "fail", "cancel", "renew", "_batch"):
        monkeypatch.setattr(case.world.service.store, name, forbidden)
    for name in ("stage", "upload", "delete", "cleanup"):
        monkeypatch.setattr(case.world.service.transport, name, forbidden)
    monkeypatch.setattr(case.world.service.results, "persist_task_result", forbidden)
    for container in (
        case.world.runs, case.world.messages, case.world.conversations, case.world.results.container,
    ):
        for name in ("create_item", "upsert_item", "replace_item", "delete_item", "execute_item_batch"):
            monkeypatch.setattr(container, name, forbidden)
    case.context.invoke_prompt = forbidden
    case.effect_snapshot = persistence_snapshot(case.world)
    return forbidden


def resume(case, pending):
    return resume_render_file(
        case.step, case.context, pending,
        service_factory=case.service_factory, resolve_inputs=case.resolve_inputs,
        build_step_result=case.world.modules.schema.build_step_result,
        build_failure=case.world.modules.schema.build_failure, settings={}, user_id=case.user_id,
        cancel_requested=case.cancel_requested,
    )


@pytest.mark.parametrize("replacement", ["absent", None, False, True, "ready", {}])
def test_render_discovery_requires_a_real_callable_resumer(resumption, monkeypatch, replacement):
    case, world = resumption, resumption.world
    rendering = importlib.import_module("functions_orchestration_rendering")
    registry = importlib.import_module("functions_orchestration_registry")
    if replacement == "absent":
        monkeypatch.delattr(rendering, "resume_render_file")
    else:
        monkeypatch.setattr(rendering, "resume_render_file", replacement)
    forbid_execution(case, monkeypatch)
    descriptor = registry.get_capability("render_file", contract_version=2)
    unavailable = {}
    available = registry.resolve_available_capabilities(
        {}, contract_version=2, candidate_ids={"render_file"},
        request_context={"rendering_service": world.service}, unavailable=unavailable,
    )
    assert descriptor["runtime_unavailable_reason"] == "rendering_service_unavailable"
    assert available == [] and unavailable == {"render_file": "rendering_service_unavailable"}


def test_render_discovery_admits_the_existing_resumer_without_executing_it(resumption, monkeypatch):
    case, world = resumption, resumption.world
    registry = importlib.import_module("functions_orchestration_registry")
    forbid_execution(case, monkeypatch)
    descriptor = registry.get_capability("render_file", contract_version=2)
    unavailable = {}
    available = registry.resolve_available_capabilities(
        {}, contract_version=2, candidate_ids={"render_file"},
        request_context={"rendering_service": world.service}, unavailable=unavailable,
    )
    assert not descriptor.get("runtime_unavailable_reason")
    assert [capability["id"] for capability in available] == ["render_file"] and unavailable == {}


@pytest.mark.parametrize("state", ["waiting", "rendering", "completed", "expired"])
def test_real_context_service_adapter_performs_no_effects(resumption, monkeypatch, state):
    case, world = resumption, resumption.world
    executor = importlib.import_module("functions_orchestration_executor")
    policy = importlib.import_module("functions_orchestration_execution_policy")
    world.change_run(execution_lease={
        "token": "current-parent-lease", "expires_at": (world.now + timedelta(minutes=10)).isoformat(),
        "heartbeat_at": world.now.isoformat(),
    })
    case.context = executor.RunContext(
        run_id="run-1", plan_id="plan-1", conversation_id="conversation-1", user_id="owner",
        plan_contract_version=2, result_service=world.service.results, rendering_service=world.service,
        execution_deadline_at=world.deadline.isoformat(),
    )
    case.context.allow_generated_files = False
    case.service_factory = executor._context_rendering_service
    output = world.service.ensure_output(
        producer=case.context.result_producer(case.step), source_ref=world.saved.output("findings"),
        export_request=GeneratedFileExportRequest("json", "exact_records_v1"), file_name="json_file.json",
        approved_work_id="run-1", deadline_at=world.deadline.isoformat(),
    )
    if state == "completed":
        output = world.run(output)
    elif state == "rendering":
        world.service.claim_due(output["output_id"])
    elif state == "expired":
        world.now = world.deadline + timedelta(seconds=1)
    pending = completed_result(case, output) if state == "completed" else world.modules.schema.build_step_result(
        status="waiting", summary="The requested file is pending.",
        wait={"kind": "orchestration_output", **output},
    )
    context_before = deepcopy((
        case.context.task_results, case.context.result_aliases, case.context.pending_results,
        case.context.artifacts, case.context.evidence,
    ))
    forbid_execution(case, monkeypatch)
    with policy.orchestration_file_policy(allow_generated_files=False):
        result = resume(case, pending)
    expected_status = "failed" if state == "expired" else "completed" if state == "completed" else "waiting"
    assert result["status"] == expected_status, result.get("output_error")
    assert context_before == (
        case.context.task_results, case.context.result_aliases, case.context.pending_results,
        case.context.artifacts, case.context.evidence,
    )
    assert "task_result" not in result
    if state == "completed":
        assert result["artifacts"][0]["artifact_message_id"] == output["artifact_message_id"]
    else:
        assert result["artifacts"] == []
    if state == "expired":
        assert result["output_error"] == {"code": "output_deadline_exceeded", "retryable": False}


@pytest.mark.parametrize("mismatch", ["instance", "facade", "actor", "conversation"])
def test_real_context_factory_rejects_a_transplanted_service(resumption, monkeypatch, mismatch):
    case, world = resumption, resumption.world
    output = world.prepare()
    executor = importlib.import_module("functions_orchestration_executor")
    case.context.result_service = world.service.results
    case.context.rendering_service = world.service
    case.context.user_id = "owner"
    case.context.conversation_id = "conversation-1"
    if mismatch == "instance":
        case.context.rendering_service = object()
    elif mismatch == "facade":
        case.context.result_service = world.results.restart()
    elif mismatch == "actor":
        case.context.user_id = "someone-else"
    else:
        case.context.conversation_id = "another-conversation"
    case.service_factory = executor._context_rendering_service
    forbid_execution(case, monkeypatch)
    result = resume(case, pending_result(case, output))
    assert result["status"] == "failed" and result["outputs"] == result["artifacts"] == []
    assert case.resolve_inputs.call_count == 0


@pytest.mark.parametrize("state", [
    "waiting", "retry_before_due", "retry_due", "rendering_live", "rendering_expired",
])
def test_resumption_only_observes_pending_scheduler_work(resumption, monkeypatch, state):
    case, world = resumption, resumption.world
    output = world.prepare()
    if state.startswith("retry"):
        world.failures["json"] = [TimeoutError("The first render was interrupted.")]
        output = world.run(output)
        if state == "retry_due":
            world.advance_due(output)
    elif state.startswith("rendering"):
        world.service.claim_due(output["output_id"])
        if state == "rendering_expired":
            world.now += timedelta(seconds=11)
    before = world.raw(output)
    calls = len(world.render_calls)
    stored = deepcopy((world.runs.items, world.messages.items, world.blobs.data))
    forbid_execution(case, monkeypatch)
    get_output = Mock(wraps=world.service.store.get)
    monkeypatch.setattr(world.service.store, "get", get_output)
    result = resume(case, pending_result(case, output))
    after = world.runs.read_item(output["output_id"], "conversation-1")
    assert result["status"] == "waiting" and result["artifacts"] == []
    assert result["wait"]["kind"] == "orchestration_output"
    assert result["outputs"][0]["output_id"] == output["output_id"]
    assert result["outputs"][0]["state"] == before["state"]
    assert "task_result" not in result and "PRIVATE" not in json.dumps(result)
    assert stored == (world.runs.items, world.messages.items, world.blobs.data)
    assert before == after and len(world.render_calls) == calls
    assert get_output.call_count == 1 and case.resolve_inputs.call_count == 1


@pytest.mark.parametrize("manual_queued", [False, True])
def test_resumption_preserves_exhausted_automatic_and_separate_manual_journals(
    resumption, monkeypatch, manual_queued,
):
    case, world = resumption, resumption.world
    output = world.prepare()
    world.failures["json"] = [TimeoutError("A bounded render failure.") for _ in range(3)]
    for attempt in range(3):
        output = world.run(output)
        if attempt < 2:
            world.advance_due(output)
    if manual_queued:
        world.service.manual_retry(output["output_id"], "explicit-manual-request")
    before = world.raw(output)
    forbid_execution(case, monkeypatch)
    result = resume(case, pending_result(case, output))
    after = world.raw(output)
    assert result["status"] == ("waiting" if manual_queued else "failed")
    assert result["outputs"][0]["automatic_attempts"] == 3
    assert result["outputs"][0]["attempt_count"] == (4 if manual_queued else 3)
    assert before == after and len(world.render_calls) == 3 and world.blobs.uploads == 0


@pytest.mark.parametrize("smaller_current_limit", [False, True])
@pytest.mark.parametrize("saved_kind", ["waiting", "completed"])
def test_resumption_returns_only_current_committed_artifact_facts(
    resumption, monkeypatch, smaller_current_limit, saved_kind,
):
    case, world = resumption, resumption.world
    completed = world.run(world.prepare())
    before = world.raw(completed)
    if smaller_current_limit:
        world.service.max_output_bytes = 1
    forbid_execution(case, monkeypatch)
    saved = pending_result(case, completed) if saved_kind == "waiting" else completed_result(case, completed)
    result = resume(case, saved)
    after = world.raw(completed)
    assert result["status"] == "completed" and result["failure"] is None
    assert result["outputs"] == [completed]
    assert len(result["artifacts"]) == 1
    card = result["artifacts"][0]
    assert card["output_id"] == completed["output_id"]
    assert card["artifact_message_id"] == completed["artifact_message_id"]
    assert card["source_kind"] == "orchestration_retained_output"
    assert card["storage_scope"] == "chat" and card["conversation_id"] == "conversation-1"
    assert "task_result" not in result and "PRIVATE" not in json.dumps(result)
    assert before == after and len(world.render_calls) == world.blobs.uploads == 1


@pytest.mark.parametrize("pointer", ["wait", "both"])
def test_completed_checkpoints_may_retain_the_exact_wait_identity(resumption, monkeypatch, pointer):
    case, world = resumption, resumption.world
    completed = world.run(world.prepare())
    saved = completed_result(case, completed)
    saved["wait"] = {"kind": "orchestration_output", "output_id": completed["output_id"]}
    if pointer == "wait":
        saved.pop("outputs")
    before = world.raw(completed)
    forbid_execution(case, monkeypatch)
    result = resume(case, saved)
    after = world.raw(completed)
    assert result["status"] == "completed" and result["outputs"] == [completed]
    assert result["artifacts"][0]["artifact_message_id"] == completed["artifact_message_id"]
    assert before == after and len(world.render_calls) == 1
    assert case.context.allow_generated_files is False and "PRIVATE" not in json.dumps(result)


def test_completed_checkpoint_status_cannot_make_an_unfinished_file_ready(resumption, monkeypatch):
    case, world = resumption, resumption.world
    waiting = world.prepare()
    saved = completed_result(case, waiting)
    before = world.raw(waiting)
    forbid_execution(case, monkeypatch)
    result = resume(case, saved)
    after = world.raw(waiting)
    assert result["status"] == "waiting" and result["artifacts"] == []
    assert result["outputs"][0]["state"] == "waiting"
    assert before == after and not world.render_calls


@pytest.mark.parametrize("defect", [
    "missing", "collection", "multiple", "missing_id", "invalid_id", "conflict", "wrong_kind", "artifact_only",
])
def test_completed_checkpoint_requires_one_unambiguous_output_identity(resumption, monkeypatch, defect):
    case, world = resumption, resumption.world
    completed = world.run(world.prepare())
    saved = completed_result(case, completed)
    if defect == "missing":
        saved.pop("outputs")
    elif defect == "collection":
        saved["outputs"] = completed
    elif defect == "multiple":
        saved["outputs"] *= 2
    elif defect == "missing_id":
        saved["outputs"][0].pop("output_id")
    elif defect == "invalid_id":
        saved["outputs"][0]["output_id"] = "foreign/path"
    elif defect == "artifact_only":
        saved["outputs"] = []
        saved["artifacts"] = [{"output_id": completed["output_id"]}]
    else:
        saved["wait"] = {
            "kind": "native_analysis" if defect == "wrong_kind" else "orchestration_output",
            "output_id": completed["output_id"] if defect == "wrong_kind" else f"orender_{'f' * 64}",
        }
    before = world.raw(completed)
    forbid_execution(case, monkeypatch)
    result = resume(case, saved)
    after = world.raw(completed)
    assert result["status"] == "failed" and result["outputs"] == result["artifacts"] == []
    assert result["output_error"] == {"code": "output_binding_invalid", "retryable": False}
    assert case.service_factory.call_count == case.resolve_inputs.call_count == 0
    assert before == after and len(world.render_calls) == 1


@pytest.mark.parametrize("output_format", ["txt", "text", "md", "markdown"])
def test_resumption_preserves_empty_source_free_files_and_catalog_aliases(resumption, monkeypatch, output_format):
    case, world = resumption, resumption.world
    prepared = replace(world.results.producer, step_id="prepared")
    world.results.add_producer(prepared)
    source_kind = "text-v1" if output_format in {"txt", "text"} else "markdown-v1"
    saved = world.results.save(
        grounded=False, producer=prepared,
        outputs=[NamedOutput("empty", source_kind, "", complete(1))],
    )
    case.step["arguments"] = {
        "file_name": f"empty.{output_format.upper()}",
        "output_format": output_format, "profile": "prepared_text_v1",
    }
    run = world.runs.read_item("run-1", "conversation-1")
    run["plan"]["steps"] = [
        deepcopy(case.step) if step["step_id"] == case.step["step_id"] else step
        for step in run["plan"]["steps"]
    ]
    run["plan"]["steps"].append({
        "step_id": "prepared", "enabled": True, "capability_id": prepared.capability_id,
    })
    world.runs.upsert_item(run)
    reader = world.service.results.open_result(saved.output("empty"))
    case.resolve_inputs = Mock(return_value={"source": reader})
    output = world.prepare(
        output_format, step_id="json_file", reference=saved.output("empty"),
        file_name=case.step["arguments"]["file_name"],
    )
    completed = world.run(output)
    forbid_execution(case, monkeypatch)
    result = resume(case, pending_result(case, completed))
    assert result["status"] == "completed" and len(result["artifacts"]) == 1
    assert result["outputs"][0]["file_name"] == case.step["arguments"]["file_name"]
    assert result["outputs"][0]["size_bytes"] == result["artifacts"][0]["character_count"] == 0
    assert len(world.render_calls) == world.blobs.uploads == 1


@pytest.mark.parametrize("change", ["deadline_elapsed", "run_cancelled"])
def test_completed_siblings_remain_observable_without_restarting_work(resumption, monkeypatch, change):
    case, world = resumption, resumption.world
    completed = world.run(world.prepare())
    if change == "deadline_elapsed":
        world.now = world.deadline + timedelta(seconds=1)
    else:
        world.change_run(status="cancelled", cancellation_requested_at=world.now.isoformat())
    before = world.raw(completed)
    forbid_execution(case, monkeypatch)
    result = resume(case, pending_result(case, completed))
    after = world.raw(completed)
    assert result["status"] == "completed" and result["artifacts"][0]["output_id"] == completed["output_id"]
    assert before == after and len(world.render_calls) == world.blobs.uploads == 1


@pytest.mark.parametrize("change", [
    "actor", "attempt", "producer_run", "work", "step_arguments", "deadline",
    "source", "reader", "input_name", "other_output",
])
@pytest.mark.parametrize("saved_kind", ["waiting", "completed"])
def test_resumption_rejects_changed_bindings_without_admission(resumption, monkeypatch, change, saved_kind):
    case, world = resumption, resumption.world
    output = world.prepare()
    pending = pending_result(case, output) if saved_kind == "waiting" else completed_result(case, output)
    if change == "actor":
        case.user_id = "someone-else"
    elif change in {"attempt", "producer_run"}:
        producer = replace(
            case.producer, **({"attempt_index": 2} if change == "attempt" else {"run_id": "another-run"}),
        )
        case.context.result_producer = lambda step: producer
    elif change == "work":
        case.context.approved_work_id = "different-approved-work"
    elif change == "step_arguments":
        case.step["arguments"]["file_name"] = "changed.json"
    elif change == "deadline":
        case.context.execution_deadline_at = (world.deadline + timedelta(seconds=1)).isoformat()
    elif change == "source":
        other = world.retain_source("document-2")
        reader = world.service.results.open_result(other)
        case.resolve_inputs = Mock(return_value={"source": reader})
    elif change == "reader":
        case.resolve_inputs = Mock(return_value={"source": {"value": "not a retained reader"}})
    elif change == "input_name":
        case.resolve_inputs = Mock(return_value={"undeclared_source": case.resolve_inputs.return_value["source"]})
    else:
        other = world.prepare("csv")
        if saved_kind == "waiting":
            pending["wait"]["output_id"] = other["output_id"]
        else:
            pending["outputs"][0]["output_id"] = other["output_id"]
    before = deepcopy((world.runs.items, world.messages.items, world.blobs.data))
    forbid_execution(case, monkeypatch)
    result = resume(case, pending)
    assert result["status"] == "failed" and result["output_error"]["retryable"] is False
    assert result["outputs"] == result["artifacts"] == []
    assert "PRIVATE" not in json.dumps(result) and "task_result" not in result
    assert before == (world.runs.items, world.messages.items, world.blobs.data)
    assert not world.render_calls and world.blobs.uploads == 0


@pytest.mark.parametrize("change", [
    "status", "kind", "missing_id", "invalid_id", "contract", "contract_bool", "contract_float",
])
def test_resumption_requires_a_real_saved_file_result(resumption, monkeypatch, change):
    case, world = resumption, resumption.world
    output = world.prepare()
    pending = pending_result(case, output)
    if change == "status":
        pending["status"] = "failed"
    elif change == "kind":
        pending["wait"]["kind"] = "native_analysis"
    elif change == "missing_id":
        pending["wait"].pop("output_id")
    elif change == "invalid_id":
        pending["wait"]["output_id"] = "foreign/file/path"
    else:
        case.context.plan_contract_version = {"contract": 1, "contract_bool": True, "contract_float": 2.0}[change]
    before = world.raw(output)
    forbid_execution(case, monkeypatch)
    result = resume(case, pending)
    after = world.raw(output)
    assert result["status"] == "failed" and result["outputs"] == result["artifacts"] == []
    assert before == after and case.service_factory.call_count == case.resolve_inputs.call_count == 0


@pytest.mark.parametrize("change", ["format", "filename"])
def test_resumption_cannot_substitute_another_request_from_the_same_producer(resumption, monkeypatch, change):
    case, world = resumption, resumption.world
    original = world.prepare()
    other = world.prepare(
        "csv" if change == "format" else "json", step_id="json_file",
        file_name="other.csv" if change == "format" else "other.json",
    )
    before = deepcopy(world.runs.items)
    pending = pending_result(case, original)
    pending["wait"]["output_id"] = other["output_id"]
    forbid_execution(case, monkeypatch)
    result = resume(case, pending)
    assert result["status"] == "failed"
    assert result["output_error"] == {"code": "output_binding_invalid", "retryable": False}
    assert result["outputs"] == result["artifacts"] == []
    assert world.runs.items == before and not world.render_calls


@pytest.mark.parametrize("boundary", ["factory", "inputs", "authority"])
@pytest.mark.parametrize("code,retryable", [
    ("external_identity_timeout", True), ("external_identity_response_invalid", False),
])
@pytest.mark.parametrize("saved_kind", ["waiting", "completed"])
def test_resumption_withholds_cached_success_on_current_authority_failure(
    resumption, monkeypatch, boundary, code, retryable, saved_kind,
):
    case, world = resumption, resumption.world
    completed = world.run(world.prepare())
    before = world.raw(completed)
    identity = importlib.import_module("functions_orchestration_external_identity")
    unavailable = Mock(side_effect=identity.ExternalIdentityServiceError(code))
    if boundary == "factory":
        case.service_factory = unavailable
    elif boundary == "inputs":
        case.resolve_inputs = unavailable
    else:
        world.service.authorize_execution = unavailable
    forbid_execution(case, monkeypatch)
    saved = pending_result(case, completed) if saved_kind == "waiting" else completed_result(case, completed)
    original_saved = deepcopy(saved)
    with pytest.raises(identity.ExternalIdentityServiceError) as caught:
        resume(case, saved)
    after = world.runs.read_item(completed["output_id"], "conversation-1")
    assert caught.value.code == code and caught.value.retryable is retryable
    assert caught.value is unavailable.side_effect
    assert saved == original_saved and before == after


@pytest.mark.parametrize("kind,wrapped", [
    *[
        (kind, wrapped)
        for kind in (
            "storage", "timeout", "reader_configuration", "external_reader_configuration",
            "source_configuration", "screening_service", "screening_configuration",
        )
        for wrapped in (False, True)
    ],
    ("storage_permission", False),
])
def test_resumption_propagates_operational_read_failures_without_a_replacement_result(
    resumption, monkeypatch, kind, wrapped,
):
    case, world = resumption, resumption.world
    completed = world.run(world.prepare())
    results = importlib.import_module("functions_orchestration_results")
    output_store = importlib.import_module("functions_orchestration_output_store")
    screening = importlib.import_module("content_screening.contracts")
    errors = {
        "storage": OutputStorageError(),
        "timeout": TimeoutError("PRIVATE backing-store timeout"),
        "reader_configuration": results.ResultUnavailableError("result_source_reader_required"),
        "external_reader_configuration": results.ResultUnavailableError("result_external_authorizer_required"),
        "source_configuration": output_store.OutputError("output_source_configuration_invalid"),
        "screening_service": screening.ScreeningError(),
        "screening_configuration": screening.SourceAuthorityUnverifiedError(),
        "storage_permission": PermissionError("PRIVATE backing-store permission"),
    }
    error = errors[kind]
    raised_error = error
    if wrapped:
        raised_error = results.ResultUnavailableError()
        raised_error.__cause__ = error
    if kind == "storage_permission":
        monkeypatch.setattr(world.service.store, "get", Mock(side_effect=raised_error))
    else:
        monkeypatch.setattr(world.service, "_authorize_read_record", Mock(side_effect=raised_error))
    saved = completed_result(case, completed)
    original_saved = deepcopy(saved)
    forbid_execution(case, monkeypatch)
    normalized = kind == "storage_permission" or (wrapped and kind == "timeout")
    expected = OutputStorageError if normalized else type(error)
    with pytest.raises(expected) as caught:
        resume(case, saved)
    if kind == "storage_permission":
        assert caught.value.__cause__ is error
    elif not wrapped or kind not in {"storage", "timeout"}:
        assert caught.value is error
    assert saved == original_saved


@pytest.mark.parametrize("failure", ["source", "screening", "message", "capability", "output_storage"])
@pytest.mark.parametrize("saved_kind", ["waiting", "completed"])
def test_resumption_rechecks_current_readiness_not_cached_completion(resumption, monkeypatch, failure, saved_kind):
    case, world = resumption, resumption.world
    completed = world.run(world.prepare())
    before = world.raw(completed)
    if failure == "source":
        world.results.denied.add("document-1")
    elif failure == "screening":
        world.results.held.add("document-1")
    elif failure == "message":
        world.messages.delete_item(completed["artifact_message_id"], "conversation-1")
    elif failure == "capability":
        world.capabilities = False
    else:
        world.runs.fail_reads = True
    forbid_execution(case, monkeypatch)
    saved = pending_result(case, completed) if saved_kind == "waiting" else completed_result(case, completed)
    if failure == "output_storage":
        try:
            with pytest.raises(OutputStorageError):
                resume(case, saved)
        finally:
            world.runs.fail_reads = False
    else:
        result = resume(case, saved)
        assert result["status"] == "failed" and result["artifacts"] == [] and result["output_error"]
        assert completed["artifact_message_id"] not in json.dumps(result)
        assert "PRIVATE" not in json.dumps(result)
        if failure in {"source", "screening", "capability"}:
            assert result["outputs"][0]["available"] is False
            assert result["outputs"][0]["artifact_message_id"] is None
            assert result["failure"]["code"] == "result_unavailable"
    after = world.runs.read_item(completed["output_id"], "conversation-1")
    assert before == after and len(world.render_calls) == world.blobs.uploads == 1


@pytest.mark.parametrize("boundary", ["factory", "inputs", "authority", "output_storage"])
@pytest.mark.parametrize("completed", [False, True])
def test_resumption_preserves_the_saved_checkpoint_during_uncertainty(
    resumption, monkeypatch, boundary, completed,
):
    case, world = resumption, resumption.world
    output = world.prepare()
    if completed:
        output = world.run(output)
    saved = world.modules.schema.build_step_result(
        status="completed" if completed else "waiting", summary="PRIVATE cached status",
        wait=None if completed else {"kind": "orchestration_output", "output_id": output["output_id"]},
        artifacts=[{"artifact_message_id": "PRIVATE cached artifact"}],
    )
    saved["outputs"] = [{
        **deepcopy(output), "state": "completed", "available": True, "can_retry": True,
        "row_count": 999999, "character_count": 999999, "size_bytes": 999999,
        "attempt_count": 999999, "automatic_attempts": 999999, "max_automatic_attempts": 999999,
        "message": "PRIVATE cached success", "next_retry_at": "PRIVATE cached retry",
        "download_url": "https://example.invalid/PRIVATE", "source_ref": {"id": "PRIVATE source"},
        "internal": {"secret": "PRIVATE metadata"},
    }]
    saved_before = deepcopy(saved)
    identity = importlib.import_module("functions_orchestration_external_identity")
    failure = Mock(side_effect=identity.ExternalIdentityServiceError("external_identity_timeout"))
    original_factory, original_inputs = case.service_factory, case.resolve_inputs
    original_authority = world.service.authorize_execution
    if boundary == "factory":
        case.service_factory = failure
    elif boundary == "inputs":
        case.resolve_inputs = failure
    elif boundary == "authority":
        world.service.authorize_execution = failure
    else:
        world.runs.fail_reads = True
    forbid_execution(case, monkeypatch)
    expected_type = OutputStorageError if boundary == "output_storage" else identity.ExternalIdentityServiceError
    with pytest.raises(expected_type) as caught:
        resume(case, saved)
    code = "output_storage_unavailable" if boundary == "output_storage" else "external_identity_timeout"
    assert caught.value.code == code and saved == saved_before

    case.service_factory, case.resolve_inputs = original_factory, original_inputs
    world.service.authorize_execution = original_authority
    world.runs.fail_reads = False
    restored = resume(case, saved)
    assert restored["status"] == ("completed" if completed else "waiting")
    assert restored["outputs"] == [output] and len(restored["artifacts"]) == int(completed)
    assert "status_uncertain" not in restored["outputs"][0]


@pytest.mark.parametrize("field", ["step_id", "file_name", "output_format", "profile"])
def test_resumption_does_not_replace_a_failed_read_with_mismatched_cached_metadata(
    resumption, monkeypatch, field,
):
    case, world = resumption, resumption.world
    output = world.prepare()
    saved = pending_result(case, output)
    saved["outputs"] = [{**deepcopy(output), field: "PRIVATE mismatched metadata"}]
    case.service_factory = Mock(side_effect=TimeoutError("PRIVATE backing service failure"))
    forbid_execution(case, monkeypatch)
    original_saved = deepcopy(saved)
    with pytest.raises(TimeoutError) as caught:
        resume(case, saved)
    assert caught.value is case.service_factory.side_effect and saved == original_saved


@pytest.mark.parametrize("saved_outputs", [False, True])
def test_resumption_does_not_overwrite_a_full_saved_wait_after_a_failed_read(
    resumption, monkeypatch, saved_outputs,
):
    case, world = resumption, resumption.world
    output = world.prepare()
    saved = world.modules.schema.build_step_result(
        status="waiting", summary="The file is pending.", wait={"kind": "orchestration_output", **output},
    )
    if saved_outputs:
        saved["outputs"] = [deepcopy(output)]
    case.service_factory = Mock(side_effect=TimeoutError("PRIVATE backing service failure"))
    forbid_execution(case, monkeypatch)
    original_saved = deepcopy(saved)
    with pytest.raises(TimeoutError):
        resume(case, saved)
    assert saved == original_saved


@pytest.mark.parametrize("failure", ["source", "screening", "capability", "cancelled", "identity", "configuration"])
def test_resumption_distinguishes_denial_cancellation_and_nonretryable_uncertainty(resumption, monkeypatch, failure):
    case, world = resumption, resumption.world
    output = world.run(world.prepare())
    saved = world.modules.schema.build_step_result(status="completed", summary="The file was ready.")
    saved["outputs"] = [deepcopy(output)]
    if failure == "source":
        world.results.denied.add("document-1")
    elif failure == "screening":
        world.results.held.add("document-1")
    elif failure == "capability":
        world.capabilities = False
    elif failure == "cancelled":
        case.cancel_requested = lambda: True
    else:
        if failure == "identity":
            module = importlib.import_module("functions_orchestration_external_identity")
            error = module.ExternalIdentityServiceError("external_identity_response_invalid")
        else:
            module = importlib.import_module("functions_orchestration_external_configuration")
            error = module.ExternalConfigurationServiceError("external_configuration_metadata_invalid")
        world.service.authorize_execution = Mock(side_effect=error)
    forbid_execution(case, monkeypatch)
    if failure in {"identity", "configuration"}:
        with pytest.raises(type(error)) as caught:
            resume(case, saved)
        assert caught.value is error and caught.value.retryable is False
    else:
        result = resume(case, saved)
        assert result["status"] == ("cancelled" if failure == "cancelled" else "failed")
        assert result["artifacts"] == [] and result["output_error"]["retryable"] is False
        if failure == "cancelled":
            assert result["outputs"] == []
        else:
            assert result["outputs"][0]["available"] is False
            assert result["outputs"][0]["artifact_message_id"] is None
            assert result["outputs"][0]["can_retry"] is False
            assert all(result["outputs"][0][key] is None for key in (
                "row_count", "character_count", "size_bytes", "next_retry_at",
            ))


@pytest.mark.parametrize("kind", ["callback", "run", "output"])
def test_resumption_observes_cancellation_without_work(resumption, monkeypatch, kind):
    case, world = resumption, resumption.world
    output = world.prepare()
    if kind == "callback":
        case.cancel_requested = lambda: True
    elif kind == "run":
        world.change_run(status="cancelled", cancellation_requested_at=world.now.isoformat())
    else:
        world.service.store.cancel(output["output_id"])
    before = world.raw(output)
    forbid_execution(case, monkeypatch)
    result = resume(case, pending_result(case, output))
    after = world.raw(output)
    assert result["status"] == "cancelled" and result["outputs"] == result["artifacts"] == []
    assert result["output_error"]["code"] == "output_cancelled"
    assert before == after and not world.render_calls and world.blobs.uploads == 0


@pytest.mark.parametrize("elapsed_seconds", [0, 1])
@pytest.mark.parametrize("state", ["waiting", "rendering", "retry_scheduled", "failed", "manual_queued"])
def test_resumption_reports_saved_deadline_without_changing_status_or_lease(
    resumption, monkeypatch, state, elapsed_seconds,
):
    case, world = resumption, resumption.world
    output = world.prepare()
    if state == "rendering":
        world.service.claim_due(output["output_id"])
    elif state in {"retry_scheduled", "failed", "manual_queued"}:
        world.failures["json"] = [TimeoutError("A bounded render failure.") for _ in range(3)]
        for attempt in range(1 if state == "retry_scheduled" else 3):
            output = world.run(output)
            if state != "retry_scheduled" and attempt < 2:
                world.advance_due(output)
        if state == "manual_queued":
            world.service.manual_retry(output["output_id"], "explicit-manual-request")
    world.now = world.deadline + timedelta(seconds=elapsed_seconds)
    before = world.raw(output)
    forbid_execution(case, monkeypatch)
    result = resume(case, pending_result(case, output))
    saved = world.raw(output)
    assert result["status"] == "failed"
    assert result["output_error"] == {"code": "output_deadline_exceeded", "retryable": False}
    assert result["outputs"] == result["artifacts"] == []
    assert saved == before and saved["state"] == ("waiting" if state == "manual_queued" else state)
    assert world.blobs.uploads == 0
