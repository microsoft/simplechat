# test_orchestration_output_resume_runtime.py
"""
Keep actual saved-Render dispatch read-only across output deadlines.
Version: 0.261.127
Implemented in: 0.261.127

The real compiler, executor, retained results and output services create two
independent files. Only saved-file observation is placed inside the zero-write
guard; ordinary execution setup remains outside that boundary.
"""

import importlib
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from functions_orchestration_output_store import OutputStorageError, OutputUnavailableError, parse_time
from test_orchestration_output_configuration import current_metadata_failure
from test_orchestration_output_lifecycle import lifecycle, production_modules  # noqa: F401
from test_orchestration_render_resume import forbid_execution, persistence_snapshot
from test_orchestration_render_waiting_runtime import render_runtime  # noqa: F401


@pytest.mark.parametrize("saved_status", ["waiting", "completed"])
def test_actual_saved_render_dispatch_calls_the_shared_resumer_exactly_once(
    render_runtime, monkeypatch, saved_status,
):
    case, world = render_runtime, render_runtime.lifecycle
    if saved_status == "waiting":
        world.failures["md"] = [TimeoutError("An admitted file is waiting for its scheduler retry.")]
    first = case.execute(case.initial)
    assert first["status"] == saved_status
    context = case.state["context"]
    context.allow_generated_files = False
    saved_result = deepcopy(first["steps"][1])
    original_saved = deepcopy(saved_result)
    observation = SimpleNamespace(world=world, context=context, forbidden=None, effect_snapshot=None)
    forbidden = forbid_execution(observation, monkeypatch)
    before = persistence_snapshot(world)
    rendering = importlib.import_module("functions_orchestration_rendering")
    executor = importlib.import_module("functions_orchestration_executor")
    shared = Mock(wraps=rendering.resume_render_file)
    monkeypatch.setattr(rendering, "resume_render_file", shared)
    try:
        result = executor._render_dependency_step(
            case.plan["steps"][1], context, settings=case.settings, user_id="owner",
            saved_result=saved_result,
        )
    finally:
        if forbidden.call_count or persistence_snapshot(world) != before:
            raise AssertionError("Saved-Render dispatch performed effects.")
    assert shared.call_count == 1
    assert shared.call_args.args == (case.plan["steps"][1], context, saved_result)
    assert shared.call_args.kwargs["service_factory"] is executor._context_rendering_service
    assert shared.call_args.kwargs["resolve_inputs"] is executor.resolve_step_inputs
    assert shared.call_args.kwargs["build_step_result"] is executor.build_step_result
    assert shared.call_args.kwargs["build_failure"] is executor.build_failure
    assert saved_result == original_saved and result["status"] == saved_status
    assert len(case.calls) == len(world.render_calls) == 1
    assert world.blobs.uploads == int(saved_status == "completed")


@pytest.mark.parametrize("saved_status", ["waiting", "completed"])
@pytest.mark.parametrize("boundary", ["record", "parent"])
@pytest.mark.parametrize("denied", [False, True])
def test_actual_saved_resumer_normalizes_only_metadata_permission_faults(
    render_runtime, monkeypatch, saved_status, boundary, denied,
):
    case, world = render_runtime, render_runtime.lifecycle
    if saved_status == "waiting":
        world.failures["md"] = [TimeoutError("An admitted file is waiting for its scheduler retry.")]
    first = case.execute(case.initial)
    assert first["status"] == saved_status
    context = case.state["context"]
    context.allow_generated_files = False
    saved_result = deepcopy(first["steps"][1])
    original_saved = deepcopy(saved_result)
    context_before = deepcopy((context.task_results, context.result_aliases, context.pending_results))
    error = (
        OutputUnavailableError("output_conversation_unavailable") if denied
        else PermissionError("PRIVATE output metadata credential failure")
    )
    metadata_read = Mock(side_effect=error)
    monkeypatch.setattr(world.service.store, "get" if boundary == "record" else "current_run", metadata_read)
    observation = SimpleNamespace(world=world, context=context, forbidden=None, effect_snapshot=None)
    forbidden = forbid_execution(observation, monkeypatch)
    before = persistence_snapshot(world)
    rendering = importlib.import_module("functions_orchestration_rendering")
    executor = importlib.import_module("functions_orchestration_executor")
    shared = Mock(wraps=rendering.resume_render_file)
    monkeypatch.setattr(rendering, "resume_render_file", shared)

    def dispatch():
        return executor._render_dependency_step(
            case.plan["steps"][1], context, settings=case.settings, user_id="owner", saved_result=saved_result,
        )

    try:
        if denied:
            result = dispatch()
            assert result["status"] == "failed" and result["artifacts"] == result["outputs"] == []
            assert result["output_error"] == {"code": error.code, "retryable": False}
        else:
            with pytest.raises(OutputStorageError) as caught:
                dispatch()
            assert caught.value.__cause__ is error and caught.value.retryable is True
    finally:
        if forbidden.call_count or persistence_snapshot(world) != before:
            raise AssertionError("Saved-Render metadata read performed effects.")
    assert shared.call_count == metadata_read.call_count == 1
    assert saved_result == original_saved
    assert context_before == (context.task_results, context.result_aliases, context.pending_results)
    assert len(case.calls) == len(world.render_calls) == 1
    assert world.blobs.uploads == int(saved_status == "completed")


@pytest.mark.parametrize("saved_status", ["waiting", "completed"])
@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("code", [
    "external_configuration_metadata_invalid", "external_configuration_limit_exceeded",
])
@pytest.mark.parametrize("entrypoint", ["public_helper", "actual_dispatch"])
def test_saved_render_preserves_nonretryable_operational_metadata_failures(
    render_runtime, monkeypatch, saved_status, wrapped, code, entrypoint,
):
    case, world = render_runtime, render_runtime.lifecycle
    if saved_status == "waiting":
        world.failures["md"] = [TimeoutError("An admitted file is waiting for its scheduler retry.")]
    first = case.execute(case.initial)
    assert first["status"] == saved_status
    context = case.state["context"]
    context.allow_generated_files = False
    saved_result = deepcopy(first["steps"][1])
    original_saved = deepcopy(saved_result)
    context_before = deepcopy((context.task_results, context.result_aliases, context.pending_results))
    configuration = importlib.import_module("functions_orchestration_external_configuration")
    results = importlib.import_module("functions_orchestration_results")
    failure = current_metadata_failure(world, configuration, code)

    def authorize(*args, **kwargs):
        try:
            return failure.call()
        except configuration.ExternalConfigurationServiceError as error:
            if not wrapped:
                raise
            raise results.ResultUnavailableError() from error

    world.service.authorize_execution = authorize
    observation = SimpleNamespace(world=world, context=context, forbidden=None, effect_snapshot=None)
    forbidden = forbid_execution(observation, monkeypatch)
    before = persistence_snapshot(world)
    rendering = importlib.import_module("functions_orchestration_rendering")
    executor = importlib.import_module("functions_orchestration_executor")
    shared = Mock(wraps=rendering.resume_render_file)
    monkeypatch.setattr(rendering, "resume_render_file", shared)
    try:
        with pytest.raises(configuration.ExternalConfigurationServiceError) as caught:
            if entrypoint == "public_helper":
                rendering.resume_render_file(
                    case.plan["steps"][1], context, saved_result,
                    service_factory=executor._context_rendering_service,
                    resolve_inputs=executor.resolve_step_inputs,
                    build_step_result=executor.build_step_result, build_failure=executor.build_failure,
                    settings=case.settings, user_id="owner",
                )
            else:
                executor._render_dependency_step(
                    case.plan["steps"][1], context, settings=case.settings, user_id="owner",
                    saved_result=saved_result,
                )
    finally:
        if forbidden.call_count or persistence_snapshot(world) != before:
            raise AssertionError("Failed saved-Render observation performed effects.")
    assert shared.call_count == 1
    assert caught.value is failure.raised[-1] and caught.value.code == code
    assert caught.value.retryable is False and failure.digest.call_count == 0
    assert saved_result == original_saved
    assert context_before == (context.task_results, context.result_aliases, context.pending_results)
    assert len(case.calls) == len(world.render_calls) == 1
    assert world.blobs.uploads == int(saved_status == "completed")


@pytest.mark.parametrize("render_runtime", [2], indirect=True)
@pytest.mark.parametrize("expired", ["target", "sibling"])
@pytest.mark.parametrize("entrypoint", ["public_helper", "actual_dispatch"])
def test_saved_render_observation_never_expires_target_or_sibling_durably(
    render_runtime, monkeypatch, expired, entrypoint,
):
    case, world = render_runtime, render_runtime.lifecycle
    failures = [TimeoutError("The selected file is waiting for its scheduler retry.")]
    if expired == "sibling":
        failures.insert(0, lambda: None)
    world.failures["md"] = failures
    first = case.execute(case.initial)
    assert first["status"] == "waiting" and len(first["outputs"]) == 2
    assert len(case.calls) == 1 and len(world.render_calls) == 2 and world.blobs.uploads == 1
    context = case.state["context"]
    context.allow_generated_files = False
    world.now = parse_time(context.execution_deadline_at)
    observation = SimpleNamespace(world=world, context=context, forbidden=None, effect_snapshot=None)
    forbidden = forbid_execution(observation, monkeypatch)
    before = persistence_snapshot(world)
    saved_result = deepcopy(first["steps"][1])
    context_before = deepcopy((context.task_results, context.result_aliases, context.pending_results))
    executor = importlib.import_module("functions_orchestration_executor")
    try:
        if entrypoint == "public_helper":
            rendering = importlib.import_module("functions_orchestration_rendering")
            result = rendering.resume_render_file(
                case.plan["steps"][1], context, saved_result,
                service_factory=executor._context_rendering_service,
                resolve_inputs=executor.resolve_step_inputs,
                build_step_result=executor.build_step_result, build_failure=executor.build_failure,
                settings=case.settings, user_id="owner",
            )
        else:
            result = executor._render_dependency_step(
                case.plan["steps"][1], context, settings=case.settings, user_id="owner",
                saved_result=saved_result,
            )
    finally:
        if forbidden.call_count:
            raise AssertionError("Actual saved-Render dispatch attempted a durable write or execution.")
        if persistence_snapshot(world) != before:
            raise AssertionError("Actual saved-Render dispatch changed output/result/storage state.")
    assert context_before == (context.task_results, context.result_aliases, context.pending_results)
    assert result["status"] == ("failed" if expired == "target" else "completed")
    if expired == "target":
        assert result["output_error"] == {"code": "output_deadline_exceeded", "retryable": False}
        assert result["artifacts"] == []
    else:
        assert len(result["artifacts"]) == 1
        assert result["artifacts"][0]["output_id"] == first["steps"][1]["outputs"][0]["output_id"]
    assert len(case.calls) == 1 and len(world.render_calls) == 2 and world.blobs.uploads == 1
