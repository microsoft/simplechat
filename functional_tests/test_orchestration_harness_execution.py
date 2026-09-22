# test_orchestration_harness_execution.py
"""Real-boundary headless V2 preparation, execution and publication regressions.

Version: 0.261.127
Implemented in: 0.261.127

Production context, models, runtime, services, result store, checkpoint/lease and
artifact adapters execute with external Azure/model I/O doubled. Cold imports run
in fresh normal and optimized interpreters with network access prohibited.
Caught source-authority failures fence actual answer/research calls within a V2
operation, without leaking the fence into another operation or worker.
Named-data availability stays internal; published outputs are renderer file DTOs.
Current external-configuration failures are exercised through the real metadata
reader and SDK metadata GET, never through an acquisition or capability override.
"""

import builtins
import importlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from copy import copy, deepcopy
from datetime import datetime, timedelta, timezone
from inspect import signature
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

import pytest

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import Agent
from azure.core.exceptions import ServiceRequestError
from agent_execution_context import ExecutionIdentity
from content_screening import access as screening_access
from content_screening.contracts import (
    DocumentHeldError, ScreeningConfigurationError, ScreeningError,
    SourceAuthorityUnavailableError, SourceAuthorityUnverifiedError,
)
from functions_orchestration_checkpoints import CheckpointError
from functions_orchestration_execution import (
    HarnessExecutionError, _delivery_summary, build_harness_invoke_prompt, finalize_harness_failure,
    prepare_harness_execution, refresh_harness_delivery,
)
from functions_orchestration_external_identity import ExternalIdentityServiceError
from functions_orchestration_models import (
    OrchestrationModel, OrchestrationModelError, get_planner_acquisition_configuration,
    planner_client_construction_source,
)
from functions_orchestration_result_contracts import ProducerIdentity, ResultContractError
from functions_orchestration_results import ResultUnavailableError
from functions_orchestration_schema import PlanValidationError
from test_support import offline_bootstrap
from test_support.orchestration_harness_execution import (
    HarnessEnvironment, compose_step, decoded_frames, input_binding, native_step,
    project_session_cache, render_step,
)
from test_support.orchestration_revisions import AtomicMemoryContainer


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"


@pytest.fixture(scope="module")
def initialized_application():
    before = set(sys.modules)
    with patch.object(
        offline_bootstrap, "TemporaryDirectory", project_session_cache,
    ), offline_bootstrap.offline_app_imports() as environment:
        bootstrap = importlib.import_module("functions_orchestration_bootstrap")
        if Path(bootstrap.__file__).resolve().parent != APP:
            raise AssertionError("The real application bootstrap must be imported.")
        yield
        if environment.network_attempts:
            raise AssertionError("The harness swallowed a blocked network request.")
    for name in set(sys.modules) - before:
        module_path = getattr(sys.modules[name], "__file__", "") or ""
        if str(APP) in module_path:
            sys.modules.pop(name, None)


@pytest.fixture
def harness(initialized_application, monkeypatch):
    return HarnessEnvironment(monkeypatch)


@pytest.fixture
def current_metadata(harness, monkeypatch):
    # SDK transport fixtures load only after the real offline application owners.
    io = importlib.import_module("test_orchestration_external_metadata")
    metadata = importlib.import_module("functions_orchestration_external_metadata")
    configuration = importlib.import_module("functions_orchestration_external_configuration")
    definition = Agent({
        "id": "metadata-agent", "model": "gpt-4o", "instructions": "Use the configured sources.",
        "tools": [{"type": "bing_grounding", "bing_grounding": {
            "search_configurations": [{"connection_id": "metadata-search"}],
        }}],
        "tool_resources": None, "response_format": "auto", "temperature": 0.2, "top_p": 1,
    })
    state = SimpleNamespace(
        configuration=configuration, definition=definition, requests=[], tokens=[],
        credentials=[], clients=[], transports=[], failure=None, status=200,
        revoke_after_get=False, cancel_after_get=False, observed=[],
    )
    settings = {
        "web_search_agent": {"other_settings": {"azure_ai_foundry": {
            "agent_id": "metadata-agent",
            "endpoint": "https://metadata.services.ai.azure.com/api/projects/headless",
            "api_version": "2025-05-01", "authentication_type": "managed_identity",
            "managed_identity_type": "system_assigned",
        }}},
    }
    read_conversation = harness.bootstrap.read_owned_conversation
    reader = metadata.build_external_metadata_reader(
        "owner", "conversation-1",
        read_conversation=lambda conversation_id: read_conversation("owner", conversation_id),
        execution_check=lambda: not (state.cancel_after_get and state.requests),
    )
    producer = ProducerIdentity(
        "owner", "conversation-1", "run-1", 1, "metadata-source", "web_search", "test-v2",
    )

    def credential(**kwargs):
        value = io.MetadataCredential(state, kwargs)
        state.credentials.append(value)
        return value

    def client(**kwargs):
        transport = io.MetadataTransport(state)
        value = AgentsClient(**kwargs, transport=transport)
        state.clients.append(value)
        state.transports.append(transport)
        return value

    def arm(fault):
        if fault in {"service", "throttled", "denied"}:
            state.status = {"service": 503, "throttled": 429, "denied": 403}[fault]
        elif fault == "timeout":
            state.failure = TimeoutError("PRIVATE_METADATA_TRANSPORT")
        elif fault == "invalid":
            state.definition = Agent({**definition.as_dict(), "model": ""})
        elif fault == "limit":
            state.definition = Agent({
                **definition.as_dict(),
                "instructions": "PRIVATE_METADATA " + "x" * configuration.MAX_CONFIGURATION_BYTES,
            })
        elif fault == "cancelled":
            state.cancel_after_get = True
        else:
            raise AssertionError("Unknown metadata fault.")

    def read_current():
        try:
            return reader("web", producer=producer, settings=settings, source=None, selector=None)
        except (
            configuration.ExternalConfigurationServiceError,
            configuration.ExternalConfigurationCancelledError, ResultUnavailableError,
        ) as error:
            state.observed.append(error)
            raise
        finally:
            state.status, state.failure, state.cancel_after_get = 200, None, False
            state.definition = definition

    monkeypatch.setattr("azure.identity.DefaultAzureCredential", credential)
    monkeypatch.setattr("azure.ai.agents.AgentsClient", client)
    state.read, state.arm = read_current, arm
    yield state
    assert all(value.closed for value in (*state.credentials, *state.transports))
    assert all(
        method == "GET" and urlsplit(url).path.rsplit("/", 1)[-1] == "metadata-agent"
        for method, url, _kwargs in state.requests
    )


@pytest.fixture
def external_callback_execution(harness, monkeypatch):
    """Observe callback effects without replacing leases, context binding or claims."""
    state = SimpleNamespace(calls=[], on_call=None, error=None, value=object(), replacements=[])

    def effect(name, arguments):
        state.calls.append((name, arguments))
        if state.on_call is not None:
            state.on_call()
        if state.error is not None:
            raise state.error
        return state.value

    def capture(source_type, *, producer, settings, source=None, selector=None):
        return effect("capture_external_source_configuration", {
            "source_type": source_type, "producer": producer, "settings": settings,
            "source": source, "selector": selector,
        })

    def admit(*, producer, prepared):
        return effect("external_source_admission", {"producer": producer, "prepared": prepared})

    def preflight(*, producer, selector=None):
        effect("external_source_preflight", {"producer": producer, "selector": selector})

    state.callbacks = {
        "capture_external_source_configuration": capture, "external_source_admission": admit,
        "external_source_preflight": preflight,
    }
    build_services = harness.bootstrap.build_orchestration_services

    def services_with_callbacks(*args, **kwargs):
        services = build_services(*args, **kwargs)
        services.capture_external_source_configuration = capture
        services.external_source_admission = admit
        services.external_source_preflight = preflight
        return services

    monkeypatch.setattr(harness.bootstrap, "build_orchestration_services", services_with_callbacks)
    harness.create(replies=["Retained before the real owner takeover."])
    state.execution = harness.prepare()
    state.lease = state.execution.lease
    producer = state.execution.context.result_producer(state.execution.record["plan"]["steps"][0])
    state.arguments = {
        "capture_external_source_configuration": {
            "source_type": "web", "producer": producer, "settings": state.execution.settings,
            "source": {"private": "configuration"}, "selector": None,
        },
        "external_source_admission": {"producer": producer, "prepared": {"private": "prepared"}},
        "external_source_preflight": {"producer": producer, "selector": None},
    }

    def invoke(name):
        return getattr(state.execution.context, name)(**state.arguments[name])

    def take_over():
        continuation = importlib.import_module("functions_orchestration_continuation")
        record, replacement = _claim_external_callback_replacement(harness, state.lease)
        state.replacements.append(replacement)
        replacement.start()
        services = harness.services()
        services.results.store = continuation.bind_orchestration_result_store(
            record, store=services.results.store, lease=replacement,
        )
        state.execution.lease = replacement
        return record, replacement, services

    state.invoke, state.take_over = invoke, take_over
    try:
        yield state
    finally:
        state.execution.lease = state.lease
        state.execution.close()
        for replacement in state.replacements:
            replacement.close(release=True)


def _claim_external_callback_replacement(harness, lease):
    continuation = importlib.import_module("functions_orchestration_continuation")
    with lease.lock:
        current = lease.read()
        lease.update({"execution_lease": {
            **current["execution_lease"],
            "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        }})
        claimed = continuation.claim_run_continuation(
            "run-1", "owner", "conversation-1",
            authorize=lambda: harness.bootstrap.read_owned_conversation("owner", "conversation-1"),
            message_container=harness.messages, mode="outputs",
        )
        if claimed is None:
            raise AssertionError("The real expired parent claim was not acquired.")
    return claimed


def _catch_source_failures(*failures):
    caught = []
    for failure in failures:
        def read_metadata(**kwargs):
            raise failure

        try:
            screening_access.assert_document_available(
                "document-1", "owner", metadata_reader=read_metadata, strict_errors=True,
            )
        except (ScreeningError, LookupError, PermissionError) as error:
            caught.append(error)
        else:
            raise AssertionError("The real authority boundary accepted an unavailable source.")
    return caught


@pytest.mark.parametrize("native", [False, True])
def test_harness_preserves_the_real_strict_source_callbacks(harness, native):
    sources = importlib.import_module("functions_orchestration_source_access")
    with harness.native_io() if native else nullcontext():
        services = harness.services()
        assert services.results.access.source_resolver is sources.resolve_orchestration_source_manifest
        assert services.results.access.source_metadata_reader is sources.read_orchestration_source_metadata
        assert harness.bootstrap.resolve_orchestration_source_manifest is sources.resolve_orchestration_source_manifest
        assert harness.bootstrap.read_orchestration_source_metadata is sources.read_orchestration_source_metadata
    assert harness.model_calls == [] and harness.clients == []


def test_harness_strict_metadata_rechecks_the_actual_document_owner(harness, monkeypatch):
    documents = AtomicMemoryContainer("id")
    document = {"id": "document-1", "user_id": "owner", "filename": "source.txt"}
    documents.create_item(document)
    monkeypatch.setattr(harness.config, "cosmos_user_documents_container", documents)
    reader = harness.services().results.access.source_metadata_reader
    current = reader("document-1", "owner")
    document["user_id"] = "another-owner"
    documents.upsert_item(document)
    with pytest.raises(PermissionError):
        reader("document-1", "owner")
    enabled = screening_access.strict_source_authority_enabled()
    assert current["user_id"] == "owner" and enabled is False
    assert harness.model_calls == [] and harness.clients == []


@pytest.mark.parametrize("boundary", ["resolver", "metadata"])
@pytest.mark.parametrize("source_error,expected,retryable", [
    (TimeoutError, SourceAuthorityUnavailableError, True),
    (ValueError, SourceAuthorityUnverifiedError, False),
])
def test_harness_strict_source_io_failures_remain_fenced_at_the_real_model_boundary(
    harness, monkeypatch, boundary, source_error, expected, retryable,
):
    harness.create(replies=["MUST_NOT_BE_GENERATED"], final_response=input_binding("prepare"))
    execution = harness.prepare()
    calls, caught = [], []
    original_settings = harness.bootstrap.get_settings

    def unavailable_io(*args, **kwargs):
        calls.append(True)
        raise source_error("PRIVATE_SOURCE_IO_DIAGNOSTIC")

    if boundary == "resolver":
        mixed = importlib.import_module("functions_mixed_source_orchestration")
        monkeypatch.setattr(mixed, "_default_document_context_batch_resolver", unavailable_io)

        def read_source():
            return execution.services.results.access.source_resolver(
                ["document-1"], user_id="owner", conversation_id="conversation-1",
            )
    else:
        monkeypatch.setattr(harness.config.cosmos_user_documents_container, "read_item", unavailable_io)

        def read_source():
            return execution.services.results.access.source_metadata_reader("document-1", "owner")

    def settings_after_caught_failure():
        if not caught:
            try:
                read_source()
            except expected as error:
                caught.append(error)
        return original_settings()

    monkeypatch.setattr(harness.bootstrap, "get_settings", settings_after_caught_failure)
    try:
        with pytest.raises(HarnessExecutionError) as failure:
            execution.execute()
    finally:
        execution.close()
    saved = harness.read()
    messages = harness.assistant_messages()
    enabled = screening_access.strict_source_authority_enabled()
    screening_access.assert_current_request_sources_available("owner")
    assert calls == [True] and len(caught) == 1 and caught[0].retryable is retryable
    assert failure.value.retryable is retryable and failure.value.durable_status is None
    assert failure.value.final_frames == [] and "PRIVATE_" not in failure.value.message
    assert saved["status"] == "running" and not saved.get("failure") and not saved.get("completed_at")
    assert saved["execution_lease"] is None and messages == [] and harness.model_calls == []
    assert all(client.closed for client in harness.clients) and execution.lease.stopped.is_set()
    assert enabled is False


@pytest.mark.parametrize("phase", ["prepare", "execute"])
@pytest.mark.parametrize("source_error,retryable", [(TimeoutError, True), (ValueError, False)])
def test_strict_source_scope_preserves_caught_authority_failures_and_isolates_runs(
    harness, monkeypatch, phase, source_error, retryable,
):
    harness.create(replies=["MUST_NOT_BE_GENERATED"], final_response=input_binding("prepare"))
    execution = None
    if phase == "prepare":
        record, lease = harness.claim()
    else:
        execution = harness.prepare()
        record, lease = execution.record, execution.lease
    original_settings = harness.bootstrap.get_settings
    caught = []

    def settings_after_caught_source_failures():
        if not caught:
            caught.extend(_catch_source_failures(
                source_error("PRIVATE_AUTHORITY_DIAGNOSTIC"), PermissionError("PRIVATE_LATER_DENIAL"),
            ))
        return original_settings()

    monkeypatch.setattr(harness.bootstrap, "get_settings", settings_after_caught_source_failures)
    try:
        with pytest.raises(HarnessExecutionError) as failure:
            if phase == "prepare":
                execution = prepare_harness_execution(record, settings=harness.settings, lease=lease)
            else:
                execution.execute()
    finally:
        if execution is not None:
            execution.close()
        lease.close()
    saved = harness.read()
    messages = harness.assistant_messages()
    enabled = screening_access.strict_source_authority_enabled()
    screening_access.assert_current_request_sources_available("owner")
    assert failure.value.retryable is retryable and failure.value.durable_status is None
    assert failure.value.final_frames == [] and "PRIVATE_" not in failure.value.message
    assert len(caught) == 2 and caught[0].retryable is retryable
    assert saved["status"] == record["status"] == "running" and not saved.get("completed_at")
    assert not saved.get("failure") and saved["execution_lease"] is None
    assert harness.model_calls == [] and messages == [] and harness.blobs.file_uploads == 0
    assert all(client.closed for client in harness.clients) and lease.stopped.is_set()
    assert enabled is False

    with monkeypatch.context() as isolated:
        healthy = HarnessEnvironment(isolated)
        healthy.create(replies=["Independent authorized answer."], final_response=input_binding("prepare"))
        next_execution = healthy.prepare()
        frames = next_execution.execute()
        done = decoded_frames(frames)[-1]
        assert done["status"] == "completed" and done["message_saved"] is True
        assert done["full_content"] == "Independent authorized answer." and len(healthy.model_calls) == 1
        assert next_execution.lease.stopped.is_set() and all(client.closed for client in healthy.clients)


@pytest.mark.parametrize("boundary", ["before_call", "after_call"])
@pytest.mark.parametrize("source_error,expected", [
    (TimeoutError, SourceAuthorityUnavailableError), (ValueError, SourceAuthorityUnverifiedError),
    (DocumentHeldError, DocumentHeldError), (PermissionError, PermissionError),
])
def test_strict_source_scope_guards_the_actual_answer_model_boundary(
    harness, boundary, source_error, expected,
):
    harness.create(replies=["PRIVATE_UNVERIFIED_ANSWER"])
    execution = harness.prepare()
    checks, caught, usage = [], [], {}

    def revalidate():
        execution._revalidate_context()
        checks.append(True)
        if len(checks) == (1 if boundary == "before_call" else 2):
            caught.extend(_catch_source_failures(
                source_error("PRIVATE_AUTHORITY_DIAGNOSTIC"), PermissionError("PRIVATE_LATER_DENIAL"),
            ))

    invoke = build_harness_invoke_prompt(execution.answer_model, token_usage=usage, revalidate=revalidate)
    try:
        with pytest.raises(expected) as failure:
            invoke("Do not use content after its source decision failed.")
    finally:
        execution.close()
    enabled = screening_access.strict_source_authority_enabled()
    screening_access.assert_current_request_sources_available("owner")
    messages = harness.assistant_messages()
    assert failure.value is caught[0]
    assert len(harness.model_calls) == (0 if boundary == "before_call" else 1)
    assert usage.get("total_tokens", 0) == (0 if boundary == "before_call" else 10)
    assert messages == [] and all(client.closed for client in harness.clients)
    assert execution.lease.stopped.is_set() and enabled is False


@pytest.mark.parametrize("boundary", ["before_call", "after_call"])
@pytest.mark.parametrize("source_error,expected", [
    (TimeoutError, SourceAuthorityUnavailableError), (ValueError, SourceAuthorityUnverifiedError),
])
def test_strict_source_scope_guards_the_attested_research_client(
    harness, boundary, source_error, expected,
):
    harness.settings["chat_orchestration_planner_deployment"] = "gpt-4o-mini"
    harness.settings["gpt_model"]["selected"].append({
        "deploymentName": "gpt-4o-mini", "modelName": "gpt-4o-mini", "responseLength": 512,
    })
    caught = []

    def reply_after_caught_failure():
        caught.extend(_catch_source_failures(source_error("PRIVATE_AUTHORITY_DIAGNOSTIC")))
        return "PRIVATE_UNVERIFIED_RESEARCH"

    harness.create(replies=[reply_after_caught_failure])
    execution = harness.prepare()
    context = execution.context
    before = planner_client_construction_source(context.planner_client, context.planner_deployment)
    descriptor_before = get_planner_acquisition_configuration(context.planner_client)
    try:
        if boundary == "before_call":
            with screening_access.strict_source_authority():
                caught.extend(_catch_source_failures(source_error("PRIVATE_AUTHORITY_DIAGNOSTIC")))
                with pytest.raises(expected) as failure:
                    context.planner_client.chat.completions.create(
                        model=context.planner_deployment, messages=[{"role": "user", "content": "Research."}],
                    )
        else:
            with pytest.raises(expected) as failure:
                context.planner_client.chat.completions.create(
                    model=context.planner_deployment, messages=[{"role": "user", "content": "Research."}],
                )
        after = planner_client_construction_source(context.planner_client, context.planner_deployment)
        descriptor_after = get_planner_acquisition_configuration(context.planner_client)
    finally:
        execution.close()
    enabled = screening_access.strict_source_authority_enabled()
    screening_access.assert_current_request_sources_available("owner")
    assert failure.value is caught[0] and before == after
    assert descriptor_before == descriptor_after == before["model"]
    assert before["model"]["deployment"] == "gpt-4o-mini"
    assert len(harness.model_calls) == (0 if boundary == "before_call" else 1)
    assert all(client.closed for client in harness.clients) and execution.lease.stopped.is_set()
    assert enabled is False


@pytest.mark.parametrize("source_error,retryable", [(TimeoutError, True), (ValueError, False)])
def test_strict_source_scope_prevents_uncertain_model_results_becoming_durable_failures(
    harness, source_error, retryable,
):
    caught = []

    def reply_after_caught_failure():
        caught.extend(_catch_source_failures(source_error("PRIVATE_AUTHORITY_DIAGNOSTIC")))
        return "PRIVATE_UNVERIFIED_ANSWER"

    harness.create(replies=[reply_after_caught_failure], final_response=input_binding("prepare"))
    execution = harness.prepare()
    progress = []
    with pytest.raises(HarnessExecutionError) as failure:
        execution.execute(emit=progress.append)
    saved = harness.read()
    messages = harness.assistant_messages()
    enabled = screening_access.strict_source_authority_enabled()
    screening_access.assert_current_request_sources_available("owner")
    assert len(caught) == 1 and failure.value.retryable is retryable
    assert failure.value.final_frames == [] and failure.value.durable_status is None
    assert saved["status"] == "running" and not saved.get("completed_at") and not saved.get("failure")
    assert not saved.get("task_results") and saved["execution_lease"] is None
    assert len(harness.model_calls) == 1 and messages == [] and harness.blobs.file_uploads == 0
    assert all(frame.get("type") != "done" for frame in decoded_frames(progress))
    assert "PRIVATE_" not in json.dumps(progress) and enabled is False
    assert all(client.closed for client in harness.clients) and execution.lease.stopped.is_set()


def test_strict_source_scope_is_owned_by_the_actual_execution_worker(harness):
    failed, release = Event(), Event()
    observed = []

    def reply_after_caught_failure():
        observed.append(screening_access.strict_source_authority_enabled())
        _catch_source_failures(TimeoutError("PRIVATE_WORKER_AUTHORITY"))
        failed.set()
        if not release.wait(timeout=10):
            raise AssertionError("The independent caller did not release the worker.")
        return "PRIVATE_UNVERIFIED_ANSWER"

    harness.create(replies=[reply_after_caught_failure], final_response=input_binding("prepare"))
    execution = harness.prepare()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execution.execute)
            try:
                if not failed.wait(timeout=10):
                    raise AssertionError("The real execution worker did not reach its model boundary.")
                enabled = screening_access.strict_source_authority_enabled()
                screening_access.assert_current_request_sources_available("owner")
            finally:
                release.set()
            with pytest.raises(HarnessExecutionError) as failure:
                future.result(timeout=10)
    finally:
        execution.close()
    saved = harness.read()
    messages = harness.assistant_messages()
    assert observed == [True] and enabled is False
    assert failure.value.retryable is True and failure.value.final_frames == []
    assert saved["status"] == "running" and saved["execution_lease"] is None and messages == []
    assert len(harness.model_calls) == 1 and execution.lease.stopped.is_set()
    assert all(client.closed for client in harness.clients)


def test_source_free_composition_is_one_call_without_uploads(harness):
    harness.create(replies=["Exact prepared answer."], final_response=input_binding("prepare"))
    execution = harness.prepare()
    progress = []
    frames = execution.execute(emit=progress.append)
    done = decoded_frames(frames)[-1]
    record = harness.read()
    messages = harness.assistant_messages()
    recovered = harness.services()
    task = execution.context.task_results["prepare"]
    producer = execution.context.result_producer(record["plan"]["steps"][0])
    reference = task.output("answer")
    text = recovered.results.open_result(reference).read_text()
    repeated_progress = []
    repeated_frames = execution.execute(emit=repeated_progress.append)
    assert done["status"] == record["status"] == "completed"
    assert task.producer == reference.producer == producer
    assert producer.contract_version == "compose-v1" and execution.context.plan_contract_version == 2
    assert done["full_content"] == text == messages[0]["content"] == "Exact prepared answer."
    assert len(harness.model_calls) == 1
    assert harness.blobs.file_uploads == 0
    assert done["outputs"] == record["outputs"] == []
    assert record["result_outputs"] == [{
        "step_id": "prepare", "name": "answer",
        "kind": record["plan"]["steps"][0]["outputs"][0]["kind"],
        "status": "complete", "reference": reference.to_dict(),
    }]
    assert done["generated_artifacts"] == []
    assert done["message_saved"] is True and record["message_saved"] is True
    assert record["completed_at"] and record["execution_lease"] is None
    assert len(messages) == 1 and messages[0]["id"] == done["message_id"]
    assert execution.lease.stopped.is_set() and not execution.lease.thread.is_alive()
    assert all(client.closed for client in harness.clients)
    assert execution.context.invoke_prompt.output_tokens == 1024
    assert execution.context.invoke_prompt.provider == "aoai"
    assert progress and "orchestration_step" in progress[0]
    assert all(type(frame) is str and frame.startswith("data: ") and frame.endswith("\n\n") for frame in progress)
    assert len(frames) == 2 and set(progress).isdisjoint(frames)
    assert repeated_frames == frames and repeated_progress == []
    assert "azure_openai_gpt_key" not in json.dumps(done)
    assert "offline-fixture-not-a-credential" not in json.dumps(messages)
    published = json.dumps([*decoded_frames(progress), *decoded_frames(frames), *messages])
    assert '"result_outputs":' not in published


def test_delivery_summary_requires_a_current_committed_card():
    outputs = [
        {
            "output_id": "ready", "file_name": "ready.csv", "state": "completed",
            "available": True, "row_count": 2,
        },
        {
            "output_id": "denied", "file_name": "denied.csv", "state": "completed",
            "available": False, "row_count": None,
        },
        {
            "output_id": "revoked-between-reads", "file_name": "revoked.csv", "state": "completed",
            "available": True, "row_count": 999,
        },
    ]
    cards = [{"output_id": "ready", "artifact_message_id": "committed-ready-file"}]
    summary = _delivery_summary(outputs, cards)
    lines = summary.splitlines()
    assert "ready (2 rows)" in lines[1]
    assert "unavailable" in lines[2] and "unavailable" in lines[3]
    assert "999" not in summary


def test_prepared_checkpoint_uses_the_actual_owning_result_guard(harness, monkeypatch):
    harness.create()
    execution = harness.prepare()
    try:
        checkpoint = execution.context.analysis_checkpoint_factory("prepare")
        checkpoint.prepare()
        token = execution.context.result_guard_token_for_step("prepare")
        repeated = execution.context.analysis_checkpoint_factory("prepare")
        rendering = execution.services.rendering_for_context(
            execution.context, settings=harness.settings, user_id="owner",
        )
        before = harness.results.container.sequence
        with monkeypatch.context() as changed:
            changed.setattr(checkpoint, "token", "not-the-owning-lease-token")
            with pytest.raises(ResultContractError):
                execution.context.result_guard_token_for_step("prepare")
        after = harness.results.container.sequence
    finally:
        execution.close()
    assert checkpoint is repeated
    assert checkpoint.store is execution.services.results.store
    assert rendering is execution.context.rendering_service is execution.services.rendering
    assert execution._capability_context["rendering_service"] is rendering
    assert checkpoint.token == token == execution.lease.token
    assert before == after and harness.model_calls == [] and harness.blobs.file_uploads == 0
    assert execution.lease.stopped.is_set() and all(client.closed for client in harness.clients)


def test_preparation_binds_result_claim_before_capability_discovery(harness, monkeypatch):
    harness.create([compose_step(), compose_step("later")])
    service_type = harness.service_bindings.OrchestrationServices
    build_bindings = service_type.capability_request_bindings
    continuation = importlib.import_module("functions_orchestration_continuation")
    bind_store = Mock(wraps=continuation.bind_orchestration_result_store)
    observed = []

    def observe_bindings(services):
        bind_store.assert_called_once()
        scoped = services.results.store
        binding = scoped._orchestration_execution
        assert binding is not None
        current = binding.read()
        rows = deepcopy(list(harness.results.container.items.values()))
        observed.append((services, scoped, binding, current))
        assert len(rows) == 2 and all(row["record_kind"] == "lifecycle" for row in rows)
        assert harness.clients == [] and harness.model_calls == [] and harness.blobs.file_uploads == 0
        return build_bindings(services)

    monkeypatch.setattr(continuation, "bind_orchestration_result_store", bind_store)
    monkeypatch.setattr(service_type, "capability_request_bindings", observe_bindings)
    execution = harness.prepare()
    try:
        assert len(observed) == 1
        services, scoped, binding, current = observed[0]
        unbound = harness.services().results.store
        store_module = importlib.import_module("functions_workflow_result_store")
        before = deepcopy(harness.results.container.items)
        for step in execution.record["plan"]["steps"]:
            identity = store_module._orchestration_identity(
                "owner", "conversation-1", "run-1", step["step_id"],
            )
            guard = scoped._analysis_guard(identity)
            assert guard["token"] == execution.lease.token and guard["execution_claim_id"] is None
            with pytest.raises(store_module.AnalysisWorkUnitConflictError):
                unbound.save_orchestration(
                    "owner", "conversation-1", "run-1", step["step_id"], {"stale": True},
                    guard_token=execution.lease.token, require_analysis_guard=True,
                )
        assert services is execution.services
        assert scoped is execution.context.result_service.store
        assert bind_store.call_args.args == (execution.record,)
        assert bind_store.call_args.kwargs["lease"] is execution.lease
        original_store = bind_store.call_args.kwargs["store"]
        assert original_store is not scoped and original_store._orchestration_execution is None
        assert binding.read == execution.lease.read
        assert binding.token == execution.lease.token and binding.claim_id is None
        assert current["attempt_index"] == binding.attempt_index == 1
        assert unbound._orchestration_execution is None and unbound is not scoped
        assert harness.results.container.items == before
        assert not harness.model_calls and harness.blobs.file_uploads == 0
    finally:
        execution.close()
    assert execution.lease.stopped.is_set() and all(client.closed for client in harness.clients)


@pytest.mark.parametrize("outage", [ServiceRequestError, ConnectionError, TimeoutError])
def test_initial_result_binding_outage_does_not_publish_a_terminal_outcome(harness, monkeypatch, outage):
    harness.create()
    record, lease = harness.claim()
    calls = []

    def unavailable_guard(*args, **kwargs):
        calls.append((args, kwargs))
        raise outage("PRIVATE_RESULT_GUARD_DIAGNOSTIC")

    monkeypatch.setattr(harness.results.container, "read_item", unavailable_guard)
    with pytest.raises(HarnessExecutionError) as failure:
        prepare_harness_execution(record, settings=harness.settings, lease=lease)
    saved = harness.read()
    messages = harness.assistant_messages()
    assert calls
    assert failure.value.code == "message_not_saved" and failure.value.retryable is True
    assert failure.value.final_frames == [] and failure.value.durable_status is None
    assert "PRIVATE_" not in failure.value.message
    assert saved["status"] == "running" and not saved.get("failure") and not saved.get("completed_at")
    assert saved["attempt_index"] == 1 and saved["execution_lease"] is None
    assert messages == [] and harness.results.container.items == {}
    assert harness.clients == [] and harness.model_calls == [] and harness.blobs.file_uploads == 0
    assert lease.stopped.is_set() and not lease.thread.is_alive()


@pytest.mark.parametrize("binding", ["legacy", "apim", "planner_override", "endpoint_override"])
def test_planner_construction_proof_uses_the_actual_private_client_inputs(harness, monkeypatch, binding):
    construction_calls = []

    def construct_client(**kwargs):
        construction_calls.append(deepcopy(kwargs))
        return harness.client(**kwargs)

    monkeypatch.setattr(harness.planner, "AzureOpenAI", construct_client)
    endpoint_runtime = importlib.import_module("functions_model_endpoint_runtime")
    monkeypatch.setattr(endpoint_runtime, "AzureOpenAI", construct_client)
    expected_deployment = "gpt-4o"
    expected_endpoint = harness.settings["azure_openai_gpt_endpoint"]
    expected_version = harness.settings["azure_openai_gpt_api_version"]
    expected_length = 1024
    if binding == "apim":
        expected_deployment = "apim-research"
        expected_endpoint, expected_version = "https://private-apim.invalid", "2025-04-01-preview"
        expected_length = None
        harness.settings.update({
            "enable_gpt_apim": True, "azure_apim_gpt_endpoint": expected_endpoint,
            "azure_apim_gpt_api_version": expected_version,
            "azure_apim_gpt_deployment": "apim-answer,apim-research",
            "azure_apim_gpt_subscription_key": "PRIVATE_APIM_KEY",
            "chat_orchestration_planner_deployment": expected_deployment,
        })
    elif binding == "planner_override":
        expected_deployment, expected_length = "gpt-4o-mini", 512
        harness.settings["chat_orchestration_planner_deployment"] = expected_deployment
        harness.settings["gpt_model"]["selected"].append({
            "deploymentName": expected_deployment, "modelName": expected_deployment,
            "responseLength": expected_length,
        })
    elif binding == "endpoint_override":
        expected_deployment, expected_length = "private-research-model", 3072
        expected_endpoint, expected_version = "https://private-model.invalid", "2025-04-01-preview"
        harness.settings.update({
            "enable_multi_model_endpoints": True,
            "chat_orchestration_planner_model_endpoint_id": "research-endpoint",
            "chat_orchestration_planner_model_id": "research-model",
            "chat_orchestration_planner_model_provider": "aoai",
            "model_endpoints": [{
                "id": "research-endpoint", "provider": "aoai", "enabled": True,
                "connection": {"endpoint": expected_endpoint, "openai_api_version": expected_version},
                "auth": {"type": "api_key", "api_key": "PRIVATE_ENDPOINT_KEY"},
                "models": [{
                    "id": "research-model", "deploymentName": expected_deployment,
                    "modelName": "gpt-4o-mini", "responseLength": expected_length, "enabled": True,
                }],
            }],
        })
        settings_cache = importlib.import_module("app_settings_cache")
        monkeypatch.setattr(settings_cache, "get_settings_cache", lambda: deepcopy(harness.settings))
    harness.create(seeds={"reasoning_effort": "high"} if binding == "legacy" else {})
    execution = harness.prepare()
    try:
        context = execution.context
        descriptor = get_planner_acquisition_configuration(context.planner_client)
        source = planner_client_construction_source(context.planner_client, context.planner_deployment)
        assert descriptor == source["model"]
        assert set(descriptor) == {
            "provider", "protocol", "endpoint", "api_version", "deployment",
            "endpoint_id", "model_id", "parameters",
        }
        model = source["model"]
        public_metadata = execution.research_model.metadata()
        serialized_model = repr(execution.research_model)
        execution.settings["azure_openai_gpt_endpoint"] = "https://later-settings.invalid"
        execution.settings["azure_apim_gpt_endpoint"] = "https://later-apim.invalid"
        execution.settings["model_endpoints"] = []
        source["model"]["endpoint"] = "https://changed-return-value.invalid"
        source["model"]["parameters"]["response_length"] = 1
        descriptor["endpoint"] = "https://changed-descriptor.invalid"
        descriptor["parameters"]["response_length"] = 2

        def forbidden_read(*args, **kwargs):
            raise AssertionError("Construction proof must not rediscover settings, clients or identity.")

        with monkeypatch.context() as pinned:
            pinned.setattr(harness.bootstrap, "get_settings", forbidden_read)
            pinned.setattr(harness.bootstrap, "current_execution_identity", forbidden_read)
            pinned.setattr(harness.planner, "resolve_planner_client", forbidden_read)
            pinned.setattr(endpoint_runtime, "resolve_model_endpoint_from_context", forbidden_read)
            pinned.setattr(OrchestrationModel, "create_completion", forbidden_read)
            reopened = planner_client_construction_source(context.planner_client, context.planner_deployment)
            reopened_descriptor = get_planner_acquisition_configuration(context.planner_client)
    finally:
        execution.close()
    actual = reopened["model"]
    assert reopened_descriptor == actual and reopened_descriptor is not actual
    assert reopened_descriptor["parameters"] is not actual["parameters"]
    assert reopened["version"] == "orchestration-external-acquisition-v1"
    assert reopened["kind"] == "planner" and reopened["phase"] == "resolved"
    assert actual["deployment"] == expected_deployment
    assert actual["endpoint"] == construction_calls[-1]["azure_endpoint"] == expected_endpoint
    assert actual["api_version"] == construction_calls[-1]["api_version"] == expected_version
    assert actual["provider"] == "aoai" and actual["protocol"] == "azure_openai"
    assert actual["parameters"].get("response_length") == expected_length
    expected_parameters = {"response_length": expected_length} if expected_length is not None else {}
    if binding == "legacy":
        expected_parameters["reasoning_effort"] = "high"
    assert actual["parameters"] == expected_parameters
    if binding == "endpoint_override":
        assert actual["endpoint_id"] == "research-endpoint" and actual["model_id"] == "research-model"
    if binding != "legacy":
        assert execution.answer_model is not execution.research_model
        assert context.model_context["model_deployment"] != actual["deployment"]
    assert model is not actual and "PRIVATE_" not in json.dumps(reopened)
    assert expected_endpoint not in json.dumps(public_metadata) and expected_endpoint not in serialized_model
    saved = harness.read()
    assert "construction" not in json.dumps(saved)
    assert "acquisition_configuration" not in json.dumps(saved) and harness.model_calls == []
    assert all(client.closed for client in harness.clients)


@pytest.mark.parametrize("change", [
    "foreign_client", "foreign_chat", "foreign_completions", "deployment", "provider",
    "endpoint_id", "model_id", "behavior_name", "response_length", "reasoning_effort",
    "raw_client", "construction", "model", "copied_model", "closed",
])
def test_planner_construction_proof_rejects_changed_bindings(harness, change):
    harness.create()
    execution = harness.prepare()
    client, model = execution.context.planner_client, execution.research_model
    original_client = model.client
    try:
        if change == "foreign_client":
            candidate = SimpleNamespace(chat=client.chat)
        else:
            candidate = client
        if change == "foreign_chat":
            client.chat = SimpleNamespace(completions=client.chat.completions)
        elif change == "foreign_completions":
            client.chat.completions = SimpleNamespace(model=model)
        elif change == "closed":
            model.close()
        elif change == "raw_client":
            model.client = harness.client()
        elif change == "construction":
            model._construction = None
        elif change == "model":
            client.chat.completions.model = OrchestrationModel(model.client, model.deployment)
        elif change == "copied_model":
            client.chat.completions.model = copy(model)
        elif change in {"deployment", "provider", "endpoint_id", "model_id", "behavior_name", "reasoning_effort"}:
            setattr(model, change, "changed-binding")
        elif change == "response_length":
            model.response_length = 100
        with pytest.raises(OrchestrationModelError):
            get_planner_acquisition_configuration(candidate)
        with pytest.raises(OrchestrationModelError):
            planner_client_construction_source(candidate, execution.context.planner_deployment)
    finally:
        execution.close()
        if change == "raw_client":
            original_client.close()
    assert harness.model_calls == [] and all(value.closed for value in harness.clients)


@pytest.mark.parametrize("candidate_kind", ["raw", "wrapped", "none", "object"])
def test_unattested_planner_client_never_borrows_settings_for_proof(candidate_kind):
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: None)))
    model = OrchestrationModel(client, "gpt-4o", provider="aoai")
    wrapped = model.as_planner_client()
    candidate = {"raw": client, "wrapped": wrapped, "none": None, "object": object()}[candidate_kind]
    with pytest.raises(OrchestrationModelError):
        get_planner_acquisition_configuration(candidate)
    with pytest.raises(OrchestrationModelError):
        planner_client_construction_source(candidate, "gpt-4o")


@pytest.mark.parametrize("deployment", [None, False, "", "different-deployment"])
def test_planner_construction_envelope_keeps_exact_deployment_validation(harness, deployment):
    harness.create()
    execution = harness.prepare()
    try:
        descriptor = get_planner_acquisition_configuration(execution.context.planner_client)
        with pytest.raises(OrchestrationModelError):
            planner_client_construction_source(execution.context.planner_client, deployment)
        assert descriptor["deployment"] == execution.context.planner_deployment
        assert harness.model_calls == [] and harness.blobs.file_uploads == 0
    finally:
        execution.close()


@pytest.mark.parametrize("truthy_factory", [True, False])
def test_injected_checkpoint_factory_receives_the_real_owned_runtime(harness, truthy_factory):
    harness.create(replies=["Prepared under the injected owner."], final_response=input_binding("prepare"))
    record, original_lease = harness.claim()
    calls = []

    class ContinuationLease(harness.recovery.ExecutionLease):
        pass

    class ContinuationCheckpoints(harness.recovery.ExecutionCheckpoints):
        pass

    class CheckpointFactory:
        def __bool__(self):
            return truthy_factory

        def __call__(self, owned_record, context, settings, lease):
            checkpoints = ContinuationCheckpoints(owned_record, context, settings, lease)
            calls.append((owned_record, context, settings, lease, checkpoints))
            return checkpoints

    lease = ContinuationLease(
        record, original_lease.authorize, message_container=harness.messages,
    )
    factory = CheckpointFactory()
    execution = prepare_harness_execution(
        record, settings=harness.settings, lease=lease, checkpoint_factory=factory,
    )
    assert calls == [] and execution.checkpoint_factory is factory
    frames = execution.execute()
    repeated = execution.execute()
    done = decoded_frames(frames)[-1]
    saved = harness.read()
    assert len(calls) == 1
    assert calls[0][0] is execution.record and calls[0][1] is execution.context
    assert calls[0][2] is execution.settings and calls[0][3] is execution.lease is lease
    assert isinstance(calls[0][4], ContinuationCheckpoints)
    assert done["status"] == saved["status"] == "completed"
    assert saved["checkpoint_version"] and saved["execution_binding"] and saved["task_results"]
    assert done["full_content"] == "Prepared under the injected owner." and done["message_saved"] is True
    assert repeated == frames and len(harness.model_calls) == 1
    assert "checkpoint_factory" not in json.dumps(saved)
    assert lease.stopped.is_set() and saved["execution_lease"] is None
    assert all(client.closed for client in harness.clients)


@pytest.mark.parametrize("invalid_factory", [False, "PRIVATE_INVALID_FACTORY"])
def test_invalid_checkpoint_factory_fails_before_model_setup(harness, invalid_factory):
    harness.create()
    record, lease = harness.claim()
    with pytest.raises(HarnessExecutionError) as failure:
        prepare_harness_execution(
            record, settings=harness.settings, lease=lease, checkpoint_factory=invalid_factory,
        )
    saved = harness.read()
    assert failure.value.code == "checkpoint_unavailable" and failure.value.durable_status == "failed"
    assert saved["status"] == "failed" and saved["execution_lease"] is None
    assert harness.clients == [] and harness.model_calls == [] and lease.stopped.is_set()
    assert "PRIVATE_INVALID_FACTORY" not in json.dumps(failure.value.final_frames)


@pytest.mark.parametrize("behavior", ["raise", "none"])
def test_failed_checkpoint_factory_never_falls_back_to_default_execution(harness, behavior):
    harness.create(replies=["Must not be generated."], final_response=input_binding("prepare"))
    calls = []

    def unavailable_checkpoints(record, context, settings, lease):
        calls.append((record, context, settings, lease))
        if behavior == "raise":
            raise RuntimeError("PRIVATE_FACTORY_DIAGNOSTIC")
        return None

    execution = harness.prepare(checkpoint_factory=unavailable_checkpoints)
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    saved = harness.read()
    assert len(calls) == 1 and calls[0][3] is execution.lease
    assert done["status"] == saved["status"] == "failed" and done["message_saved"] is True
    assert not saved.get("task_results") and harness.model_calls == []
    assert "PRIVATE_FACTORY_DIAGNOSTIC" not in json.dumps(frames)
    assert saved["execution_lease"] is None and execution.lease.stopped.is_set()
    assert all(client.closed for client in harness.clients)


@pytest.mark.parametrize("checkpoint_owner", ["default", "injected"])
@pytest.mark.parametrize("boundary", ["lease_read", "lease_start", "result_binding", "checkpoint_restore"])
@pytest.mark.parametrize("wrapper", ["checkpoint", "permission"])
@pytest.mark.parametrize("outage", [ServiceRequestError, ConnectionError, TimeoutError])
def test_continuation_io_preserves_saved_work_for_retry(
    harness, monkeypatch, boundary, wrapper, outage, checkpoint_owner,
):
    harness.settings["tabular_generated_output_inline_max_rows"] = 1
    with harness.native_io(row_count=3) as native:
        harness.create(
            [native_step()], seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
            original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        )
        first = harness.prepare()
        first_frames = first.execute()
        first_done = decoded_frames(first_frames)[-1]
        original = harness.read()
        messages = harness.assistant_messages()
        assert first_done["status"] == original["status"] == "waiting"
        claimed = harness.recovery.claim_waiting_continuation(
            "run-1", "owner", {
                "conversation_id": "conversation-1", "submission_id": "checkpoint-io-retry",
                "expected_version": original["recovery_version"],
            },
            authorize=lambda: harness.bootstrap.read_owned_conversation("owner", "conversation-1"),
            message_container=harness.messages,
        )
        record = claimed["record"]
        factory_calls = []

        def fail_storage_read():
            failure = outage("PRIVATE_STORAGE_DIAGNOSTIC")
            if wrapper == "checkpoint":
                raise CheckpointError("checkpoint_unavailable") from failure
            raise PermissionError("PRIVATE_AUTHORIZATION_WRAPPER") from failure

        class ContinuationLease(harness.recovery.ExecutionLease):
            failed_read = False

            def read(self):
                if boundary == "lease_read" and not self.failed_read:
                    self.failed_read = True
                    fail_storage_read()
                return super().read()

            def start(self):
                if boundary == "lease_start":
                    fail_storage_read()
                return super().start()

        def restore_checkpoints(record, context, settings, lease):
            factory_calls.append((record, context, settings, lease))
            fail_storage_read()

        def unavailable_checkpoint_store(*args, **kwargs):
            factory_calls.append((args, kwargs))
            fail_storage_read()

        def unavailable_result_guard(*args, **kwargs):
            fail_storage_read()

        if boundary == "result_binding":
            monkeypatch.setattr(harness.results.container, "read_item", unavailable_result_guard)
        lease = ContinuationLease(
            record, lambda: harness.bootstrap.read_owned_conversation("owner", "conversation-1"),
            message_container=harness.messages,
        )
        with pytest.raises(HarnessExecutionError) as failure:
            execution = prepare_harness_execution(
                record, settings=harness.settings, lease=lease,
                checkpoint_factory=restore_checkpoints if checkpoint_owner == "injected" else None,
            )
            if boundary == "checkpoint_restore" and checkpoint_owner == "default":
                monkeypatch.setattr(harness.recovery, "checkpoint_store", unavailable_checkpoint_store)
            execution.execute()
        saved = harness.read()
        assert failure.value.code == "message_not_saved" and failure.value.retryable is True
        assert failure.value.durable_status is None and failure.value.final_frames == []
        assert "PRIVATE_" not in failure.value.message
        assert saved["status"] == record["status"] == "running" and not saved.get("failure")
        assert saved["task_results"] == original["task_results"]
        assert saved["pending_results"] == original["pending_results"]
        assert saved["execution_binding"] == original["execution_binding"]
        assert saved["execution_deadline_at"] == original["execution_deadline_at"]
        assert saved["continuation_submission"] == record["continuation_submission"]
        assert saved["attempt_index"] == 1 and saved["execution_lease"] is None
        assert harness.assistant_messages() == messages and native.jobs.created == 1
        assert harness.model_calls == [] and harness.blobs.file_uploads == 0
        assert len(factory_calls) == (1 if boundary == "checkpoint_restore" else 0)
        assert lease.stopped.is_set() and all(client.closed for client in harness.clients)


@pytest.mark.parametrize("binding_available", [True, False])
def test_native_preparation_uses_the_actual_service_binding_before_model_setup(harness, monkeypatch, binding_available):
    harness.create([{
        "step_id": "native", "capability_id": "tabular_analyze",
        "arguments": {
            "question": "Return the selected identifiers.", "document_ids": ["doc-1"],
            "native_operation": "query", "query_expression": "index == index", "columns": ["id"],
        },
    }])
    record, lease = harness.claim()
    if not binding_available:
        monkeypatch.setattr(harness.bootstrap, "native_bridge_for_step", None)
        with pytest.raises(HarnessExecutionError) as failure:
            prepare_harness_execution(record, settings=harness.settings, lease=lease)
        assert failure.value.code == "context_unavailable"
        assert harness.clients == [] and harness.model_calls == []
        assert lease.stopped.is_set()
        return
    execution = prepare_harness_execution(record, settings=harness.settings, lease=lease)
    try:
        factory = execution.context.native_bridge_for_step
        bridge = factory(execution.record["plan"]["steps"][0], execution.context)
        execution._revalidate_context()
        producer = execution.context.result_producer(execution.record["plan"]["steps"][0])
    finally:
        execution.close()
    assert factory is execution.services.native_bridge_for_step is harness.bootstrap.native_bridge_for_step
    assert execution._capability_context["native_bridge_for_step"] is factory
    assert bridge.native_operation == "query" and bridge.task_type == "structured_export"
    assert producer.contract_version == "native-tabular-result-v1"
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0
    assert lease.stopped.is_set() and all(client.closed for client in harness.clients)


@pytest.mark.parametrize("has_preflight", [True, False], ids=["preflight", "no_preflight"])
@pytest.mark.parametrize(
    ("has_admission", "has_authorizer", "has_capture"),
    [
        (True, True, True), (False, True, False), (True, True, False), (False, True, True),
        (True, False, True), (True, False, False), (False, False, True), (False, False, False),
    ],
    ids=[
        "complete", "read_only", "uncaptured", "unadmitted",
        "unauthorized", "admission_only", "capture_only", "missing",
    ],
)
def test_external_preparation_uses_complete_initialized_service_bindings(
    harness, monkeypatch, has_admission, has_authorizer, has_capture, has_preflight,
):
    harness.settings.update({"enable_web_search": True, "enable_chat_orchestration_harness": False})
    callbacks = {
        name: Mock(side_effect=AssertionError("Discovery must not acquire or authorize an external source."))
        for name in (
            "external_source_preflight",
            "external_source_admission", "external_source_authorizer",
            "capture_external_source_configuration",
        )
    }
    build_services = harness.bootstrap.build_orchestration_services
    build_context = harness.execution.build_capability_request_context
    discovery_calls = []
    complete = has_preflight and has_admission and has_authorizer and has_capture

    def observe_discovery(*args, **kwargs):
        discovery_calls.append(kwargs)
        return build_context(*args, **kwargs)

    def initialized_services(*args, **kwargs):
        services = build_services(*args, **kwargs)
        services.external_source_preflight = (
            callbacks["external_source_preflight"] if has_preflight else None
        )
        services.external_source_admission = (
            callbacks["external_source_admission"] if has_admission else None
        )
        services.results.access.external_source_authorizer = (
            callbacks["external_source_authorizer"] if has_authorizer else None
        )
        services.capture_external_source_configuration = (
            callbacks["capture_external_source_configuration"] if has_capture else None
        )
        return services

    monkeypatch.setattr(harness.execution, "build_capability_request_context", observe_discovery)
    monkeypatch.setattr(harness.bootstrap, "build_orchestration_services", initialized_services)
    harness.create([{
        "step_id": "gather", "capability_id": "web_search",
        "arguments": {"query": "The approved external question."},
    }])
    record, lease = harness.claim()
    if not complete:
        with pytest.raises(HarnessExecutionError) as failure:
            prepare_harness_execution(record, settings=harness.settings, lease=lease)
        assert failure.value.code == "context_unavailable"
        assert harness.clients == [] and lease.stopped.is_set()
    else:
        execution = prepare_harness_execution(record, settings=harness.settings, lease=lease)
        try:
            execution._revalidate_context()
            bindings = execution.services.capability_request_bindings()
            context = execution.context
            for name, callback in callbacks.items():
                assert execution._capability_context[name] is bindings[name] is callback
            assert context.external_source_admission.__wrapped__ is callbacks["external_source_admission"]
            assert context.external_source_preflight.__wrapped__ is callbacks["external_source_preflight"]
            assert (
                context.capture_external_source_configuration.__wrapped__
                is callbacks["capture_external_source_configuration"]
            )
            assert context.result_service.access.external_source_authorizer is callbacks["external_source_authorizer"]
            assert execution._capability_context["native_bridge_for_step"] is execution.services.native_bridge_for_step
            assert execution._capability_context["rendering_service"] is execution.services.rendering
        finally:
            execution.close()
        assert len(harness.clients) == 1 and all(client.closed for client in harness.clients)
        assert lease.stopped.is_set()
    saved = harness.read()
    expected_keywords = {"allowed_user_urls", "native_bridge_for_step", "rendering_service"}
    if complete:
        expected_keywords.update(callbacks)
    assert len(discovery_calls) == 1 and set(discovery_calls[0]) == expected_keywords
    if complete:
        for name, callback in callbacks.items():
            assert discovery_calls[0][name] is callback
    assert saved["execution_lease"] is None and harness.model_calls == []
    assert all(name not in json.dumps(saved) for name in callbacks)
    for callback in callbacks.values():
        callback.assert_not_called()


@pytest.mark.parametrize("name", [
    "external_source_preflight", "external_source_admission", "capture_external_source_configuration",
])
def test_external_runtime_callbacks_keep_signature_return_and_shared_service_identity(
    harness, monkeypatch, external_callback_execution, name,
):
    state = external_callback_execution
    context_callback = getattr(state.execution.context, name)
    raw_callback = state.callbacks[name]
    fresh_services = harness.services()
    order = []
    read_run = harness.runs.read_item

    def observed_read(*args, **kwargs):
        result = read_run(*args, **kwargs)
        order.append("lease_read")
        return result

    state.on_call = lambda: order.append("effect")
    monkeypatch.setattr(harness.runs, "read_item", observed_read)
    with state.lease.lock:
        result = state.invoke(name)
    expected = None if name == "external_source_preflight" else state.value
    assert result is expected
    assert order == ["lease_read", "effect", "lease_read"]
    assert state.calls == [(name, state.arguments[name])]
    assert signature(context_callback) == signature(raw_callback)
    assert context_callback is not raw_callback and context_callback.__wrapped__ is raw_callback
    assert getattr(state.execution.services, name) is getattr(fresh_services, name) is raw_callback
    assert state.execution._capability_context[name] is raw_callback
    assert fresh_services.results.store._orchestration_execution is None
    saved = harness.read()
    assert all(callback_name not in json.dumps(saved) for callback_name in state.callbacks)
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("source_type", ["agent", "action", "web", "deep_research", "url"])
def test_external_fence_forwards_none_source_without_promoting_preparation_to_proof(
    harness, external_callback_execution, source_type,
):
    state = external_callback_execution
    state.value = None
    arguments = state.arguments["capture_external_source_configuration"]
    selector = f"personal:owner:{source_type}-one" if source_type in {"agent", "action"} else None
    arguments.update(source_type=source_type, source=None, selector=selector)
    result = state.invoke("capture_external_source_configuration")
    assert result is None and state.calls == [("capture_external_source_configuration", arguments)]
    if source_type in {"agent", "action"}:
        module = importlib.import_module("functions_orchestration_invocation_capture")
        callback = state.execution.context.capture_external_source_configuration
        producer = arguments["producer"]
        capture = module.OrchestrationInvocationCapture(
            lambda source_type, **kwargs: callback(source_type, producer=producer, **kwargs),
        )
        capture(source_type, settings=state.execution.settings, selector=selector)
        with pytest.raises(module.OrchestrationInvocationCaptureError):
            capture.require_valid(captured=True)
        assert state.calls[-1][1]["source"] is None and state.calls[-1][1]["selector"] == selector
    saved = harness.read()
    assert not saved.get("result_aliases") and not saved.get("task_results")
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("loss", ["stopped", "stolen"])
@pytest.mark.parametrize("sticky", [False, True])
def test_real_capture_preserves_the_headless_lease_fence_initial_and_sticky_failure(
    harness, external_callback_execution, loss, sticky,
):
    state = external_callback_execution
    if loss == "stolen":
        harness.run_engine(state.execution)
        state.take_over()
    else:
        state.lease.close()
    module = importlib.import_module("functions_orchestration_invocation_capture")
    callback = state.execution.context.capture_external_source_configuration
    producer = state.arguments["capture_external_source_configuration"]["producer"]
    capture = module.OrchestrationInvocationCapture(
        lambda source_type, **kwargs: callback(source_type, producer=producer, **kwargs),
    )
    observed = []

    def invoke():
        try:
            capture("web", settings=state.execution.settings)
        except Exception as error:
            observed.append(error)
            if not sticky:
                raise
        capture.require_valid(captured=True)

    with pytest.raises(CheckpointError) as failure:
        invoke()
    assert failure.value.code == "ownership_lost"
    assert len(observed) == 1 and isinstance(observed[0], CheckpointError)
    assert observed[0].code == "ownership_lost" and state.calls == []
    assert len(harness.model_calls) == (1 if loss == "stolen" else 0) and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("name", [
    "external_source_preflight", "external_source_admission", "capture_external_source_configuration",
])
@pytest.mark.parametrize("loss", ["stopped", "stolen"])
def test_external_runtime_callbacks_reject_the_original_stopped_or_stolen_lease(
    harness, external_callback_execution, name, loss,
):
    state = external_callback_execution
    if loss == "stolen":
        harness.run_engine(state.execution)
        record, replacement, services = state.take_over()
        current = replacement.read()
        assert current["id"] == record["id"] == "run-1" and current["attempt_index"] == 1
        assert replacement.token == state.lease.token and replacement.claim_id != state.lease.claim_id
        assert state.execution.lease is replacement and services is not state.execution.services
    else:
        state.lease.close()
        current = state.lease.read()
        assert state.lease.stopped.is_set() and current["execution_lease"]["token"] == state.lease.token
    before = deepcopy(harness.results.container.items)
    with pytest.raises(CheckpointError) as failure:
        state.invoke(name)
    assert failure.value.code == "ownership_lost" and state.calls == []
    assert harness.results.container.items == before
    assert getattr(state.execution.services, name) is state.callbacks[name]
    assert len(harness.model_calls) == (1 if loss == "stolen" else 0)
    assert harness.blobs.file_uploads == 0


@pytest.mark.parametrize("name", [
    "external_source_preflight", "external_source_admission", "capture_external_source_configuration",
])
@pytest.mark.parametrize("loss", ["stopped", "stolen"])
@pytest.mark.parametrize("callback_failed", [False, True])
def test_external_runtime_callbacks_recheck_the_original_lease_after_effects(
    harness, external_callback_execution, name, loss, callback_failed,
):
    state = external_callback_execution
    if loss == "stolen":
        harness.run_engine(state.execution)
        state.on_call = state.take_over
    else:
        state.on_call = state.lease.close
    if callback_failed:
        configuration = importlib.import_module("functions_orchestration_external_configuration")
        state.error = configuration.ExternalConfigurationServiceError("external_configuration_throttled")
    with pytest.raises(CheckpointError) as failure:
        state.invoke(name)
    assert failure.value.code == "ownership_lost"
    assert state.calls == [(name, state.arguments[name])]
    if loss == "stolen":
        replacement = state.replacements[0]
        current = replacement.read()
        assert replacement.token == state.lease.token and replacement.claim_id != state.lease.claim_id
        assert state.execution.lease is replacement and current["status"] == "running"
    else:
        assert state.lease.stopped.is_set()
    assert getattr(state.execution.services, name) is state.callbacks[name]
    assert len(harness.model_calls) == (1 if loss == "stolen" else 0)
    assert harness.blobs.file_uploads == 0


@pytest.mark.parametrize("name", [
    "external_source_preflight", "external_source_admission", "capture_external_source_configuration",
])
@pytest.mark.parametrize("error_kind", [
    "external_configuration_service_unavailable", "external_configuration_timeout",
    "external_configuration_throttled", "external_configuration_metadata_invalid",
    "external_configuration_limit_exceeded", "cancelled", "denied", "held",
])
def test_external_runtime_callbacks_preserve_typed_failures_and_recheck_the_live_lease(
    harness, monkeypatch, external_callback_execution, name, error_kind,
):
    state = external_callback_execution
    configuration = importlib.import_module("functions_orchestration_external_configuration")
    if error_kind == "cancelled":
        error = configuration.ExternalConfigurationCancelledError()
    elif error_kind == "denied":
        error = ResultUnavailableError("result_source_unavailable")
    elif error_kind == "held":
        error = DocumentHeldError()
    else:
        error = configuration.ExternalConfigurationServiceError(error_kind)
    state.error = error
    order = []
    read_run = harness.runs.read_item

    def observed_read(*args, **kwargs):
        result = read_run(*args, **kwargs)
        order.append("lease_read")
        return result

    state.on_call = lambda: order.append("effect")
    monkeypatch.setattr(harness.runs, "read_item", observed_read)
    with state.lease.lock, pytest.raises(type(error)) as failure:
        state.invoke(name)
    assert failure.value is error and order == ["lease_read", "effect", "lease_read"]
    assert state.calls == [(name, state.arguments[name])]
    current = state.lease.read()
    assert current["status"] == "running" and not current.get("failure")
    assert not state.lease.stopped.is_set() and harness.model_calls == [] and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("name", [
    "external_source_preflight", "external_source_admission", "capture_external_source_configuration",
])
@pytest.mark.parametrize("loss", ["stopped", "stolen"])
def test_actual_root_external_callbacks_cannot_borrow_a_replacement_owner(harness, monkeypatch, name, loss):
    harness.create(replies=["Retained before the real root callback race."])
    execution = harness.prepare()
    original_lease, replacement = execution.lease, None
    raw_callback = getattr(execution.services, name)
    callback = getattr(execution.context, name)
    producer = execution.context.result_producer(execution.record["plan"]["steps"][0])
    sources = importlib.import_module("functions_orchestration_external_sources")
    configuration = importlib.import_module("functions_orchestration_external_configuration")
    effect = Mock(side_effect=AssertionError("A stale worker reached actual root preflight or admission."))
    try:
        if name == "external_source_preflight":
            assert type(raw_callback.__self__) is sources.OrchestrationExternalSourceProvider
            assert raw_callback.__func__ is sources.OrchestrationExternalSourceProvider.preflight_gather_invocation
        else:
            assert raw_callback.__module__ == harness.bootstrap.__name__
        assert callback.__wrapped__ is raw_callback
        assert signature(callback) == signature(raw_callback)
        if loss == "stolen":
            harness.run_engine(execution)
            record, replacement = _claim_external_callback_replacement(harness, original_lease)
            replacement.start()
            execution.lease = replacement
            current = replacement.read()
            assert current["attempt_index"] == record["attempt_index"] == 1
            assert replacement.token == original_lease.token and replacement.claim_id != original_lease.claim_id
        else:
            original_lease.close()
            current = original_lease.read()
            assert current["execution_lease"]["token"] == original_lease.token
        monkeypatch.setattr(sources.OrchestrationExternalSourceProvider, "preflight_gather_acquisition", effect)
        monkeypatch.setattr(sources.OrchestrationExternalSourceProvider, "_gather_invocation_state", effect)
        monkeypatch.setattr(configuration.OrchestrationExternalConfigurationAttestor, "selector_for", effect)
        with pytest.raises(CheckpointError) as failure:
            if name == "capture_external_source_configuration":
                callback("web", producer=producer, settings=harness.settings)
            elif name == "external_source_preflight":
                callback(producer=producer, selector=None)
            else:
                callback(producer=producer, prepared={"private": "unadmitted"})
        assert failure.value.code == "ownership_lost"
        effect.assert_not_called()
        assert getattr(execution.services, name) is raw_callback
        assert len(harness.model_calls) == (1 if loss == "stolen" else 0) and harness.blobs.file_uploads == 0
    finally:
        execution.lease = original_lease
        execution.close()
        if replacement is not None:
            replacement.close(release=True)


@pytest.mark.parametrize("columns", [None, [], ["id"]])
def test_csv_render_requires_an_explicit_projection_from_the_shared_catalog(harness, columns):
    table = render_step("table", "csv", output="rows")
    if columns is not None:
        table["arguments"]["options"] = {"columns": columns}
    steps = [
        compose_step(outputs=[{
            "name": "rows", "kind": "records-v1",
            "columns": [{"name": "id", "value_type": "string", "nullable": False}],
        }]),
        table,
    ]
    if not columns:
        with pytest.raises(PlanValidationError):
            harness.create(steps)
        assert harness.runs.items == {}
    else:
        record = harness.create(steps)
        assert record["plan"]["steps"][1]["arguments"]["options"]["columns"] == ["id"]
    assert harness.clients == [] and harness.model_calls == [] and harness.blobs.file_uploads == 0


def test_explicit_multiple_renders_share_complete_prepared_content(harness):
    columns = [{"name": "id", "value_type": "string", "nullable": False}]
    rows = [{"id": "001"}, {"id": "final-row"}]
    table = render_step("table", "csv", output="rows")
    table["arguments"]["options"] = {"columns": ["id"]}
    harness.create(
        [
            compose_step(outputs=[{"name": "rows", "kind": "records-v1", "columns": columns}]),
            table,
            render_step("data", "json", output="rows"),
        ],
        replies=[json.dumps({"rows": rows})],
    )
    execution = harness.prepare()
    progress = []
    frames = execution.execute(emit=progress.append)
    done = decoded_frames(frames)[-1]
    record = harness.read()
    restart = harness.services()
    outputs = restart.rendering.list_public_outputs("run-1")
    artifacts = restart.rendering.committed_artifacts("run-1")
    messages = harness.assistant_messages()
    assert done["status"] == "completed"
    assert len(harness.model_calls) == 1 and harness.blobs.file_uploads == 2
    assert len(outputs) == len(artifacts) == 2
    assert all(output["state"] == "completed" and output["row_count"] == 2 for output in outputs)
    assert done["outputs"] == record["outputs"] == messages[0]["metadata"]["orchestration"]["outputs"] == outputs
    assert any(
        output["step_id"] == "prepare" and output["name"] == "rows" and output["status"] == "complete"
        for output in record["result_outputs"]
    )
    assert done["generated_artifacts"] == artifacts
    assert "No downloadable files were created" not in done["full_content"]
    assert "2 rows" in done["full_content"] and "ready" in done["full_content"]
    assert "storage_locator" not in json.dumps(done)
    assert "source_ref" not in json.dumps(done)
    assert "content_sha256" not in json.dumps(done["outputs"])
    assert len(messages) == 1
    published = json.dumps([*decoded_frames(progress), *decoded_frames(frames), *messages])
    assert '"result_outputs":' not in published


def test_native_waiting_resumes_the_same_headless_attempt_without_resubmission(harness, monkeypatch):
    store_module = importlib.import_module("functions_workflow_result_store")
    harness.settings.update({
        "enable_tabular_generation_plan": False,
        "enable_tabular_completion_driven_checkpointing": False,
        "tabular_generated_output_inline_max_rows": 1,
    })
    with harness.native_io() as native:
        harness.create(
            [
                native_step(),
                compose_step(inputs={"rows": {
                    "binding": input_binding("compute", "records"), "allow_partial": False,
                }}),
            ],
            replies=["All 37 rows were prepared."], final_response=input_binding("prepare"),
            seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
            original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        )
        first = harness.prepare()
        first_store = first.services.results.store
        first_binding = first_store._orchestration_execution
        assert first_binding is not None and first_binding.claim_id is None
        first_frames = first.execute()
        first_done = decoded_frames(first_frames)[-1]
        first_record = harness.read()
        first_message = harness.assistant_messages()[0]
        assert first_done["status"] == "waiting", first_done
        original_task = deepcopy(first_record["task_results"]["compute"])
        original_wait = deepcopy(first_record["pending_results"]["compute"])
        original_deadline = first_record["execution_deadline_at"]
        original_binding = deepcopy(first_record["execution_binding"])
        assert first_record["completed_at"] is None and first_record["execution_lease"] is None
        assert native.jobs.created == 1 and harness.model_calls == []
        assert first.lease.stopped.is_set() and all(client.closed for client in harness.clients)

        def forbidden(*args, **kwargs):
            raise AssertionError("A native refresh rebuilt or resubmitted its computation.")

        bridge_module = importlib.import_module("functions_orchestration_native_results")
        opens = []
        open_result = native.results.open_native_tabular_result

        def read_once(**kwargs):
            opens.append(deepcopy(kwargs))
            return open_result(**kwargs)

        monkeypatch.setattr(bridge_module, "build_native_orchestration_request", forbidden)
        monkeypatch.setattr(native.native, "build_native_tabular_compute_callback", forbidden)
        monkeypatch.setattr(native.results, "open_native_tabular_result", read_once)
        pending = harness.continue_waiting("pending-native-event")
        pending_store = pending.services.results.store
        pending_binding = pending_store._orchestration_execution
        unbound = harness.services().results.store
        before = deepcopy(harness.results.container.items)
        with pytest.raises(CheckpointError):
            first_store.save_orchestration(
                "owner", "conversation-1", "run-1", "compute", {"stale": True},
                guard_token=first.lease.token, require_analysis_guard=True,
            )
        with pytest.raises(store_module.AnalysisWorkUnitConflictError):
            unbound.save_orchestration(
                "owner", "conversation-1", "run-1", "compute", {"token_only": True},
                guard_token=first.lease.token, require_analysis_guard=True,
            )
        assert pending_binding is not None and pending_binding.claim_id == pending.lease.claim_id
        assert pending_binding.claim_id != first_binding.claim_id
        assert pending_binding.token == first_binding.token == first.lease.token
        assert first_store._orchestration_execution is first_binding
        assert harness.results.container.items == before and not opens
        pending_frames = pending.execute()
        pending_done = decoded_frames(pending_frames)[-1]
        pending_record = harness.read()
        pending_message = harness.assistant_messages()[0]
        assert pending_done["status"] == "waiting", pending_done
        assert pending.lease.token == first.lease.token
        assert pending_record["attempt_index"] == first_record["attempt_index"] == 1
        assert pending_record["task_results"]["compute"] == original_task
        assert pending_record["pending_results"]["compute"] == original_wait
        assert pending_record["execution_binding"] == original_binding
        assert pending_record["execution_deadline_at"] == original_deadline
        assert pending_record["completed_at"] is None and len(opens) == 1
        assert pending_message["id"] == first_message["id"]
        assert pending_message["timestamp"] == first_message["timestamp"]
        assert native.jobs.created == 1 and harness.model_calls == []

        native.engine.process_tabular_generated_output_run(original_wait["handle"]["job_id"], "owner")
        resumed = harness.continue_waiting("ready-native-event")
        resumed_binding = resumed.services.results.store._orchestration_execution
        assert resumed_binding is not None and resumed_binding.claim_id == resumed.lease.claim_id
        assert resumed_binding.claim_id != pending_binding.claim_id
        assert resumed_binding.token == pending_binding.token == first_binding.token
        assert pending_store._orchestration_execution is pending_binding
        with pytest.raises(CheckpointError):
            pending_store.save_orchestration(
                "owner", "conversation-1", "run-1", "compute", {"stale": True},
                guard_token=pending.lease.token, require_analysis_guard=True,
            )
        complete_frames = resumed.execute()
        done = decoded_frames(complete_frames)[-1]
        record = harness.read()
        messages = harness.assistant_messages()
        restart = harness.services()
        task = resumed.context.task_results["compute"]
        rows = list(restart.results.open_result(task.output("records")).iter_records())
        coverage = restart.results.open_result(task.output("coverage")).read_value()
        assert done["status"] == record["status"] == "completed", done
        assert record["pending_results"] == {} and record["completed_at"]
        assert record["task_results"]["compute"]["producer"] == original_task["producer"]
        assert record["execution_binding"] == original_binding
        assert record["execution_deadline_at"] == original_deadline
        assert resumed.lease.token == first.lease.token and record["attempt_index"] == 1
        assert len(opens) == 2 and all(read["handle"] == original_wait["handle"] for read in opens)
        assert native.jobs.created == 1 and len(harness.model_calls) == 1
        assert len(rows) == 37 and rows[-1] == {"Item_ID": "item-000037", "doubled": 74}
        assert coverage["outputs"]["records"]["actual_count"] == 37
        assert len(messages) == 1 and messages[0]["id"] == first_message["id"] == done["message_id"]
        assert done["full_content"] == messages[0]["content"] == "All 37 rows were prepared."
        assert harness.blobs.file_uploads == 0 and done["generated_artifacts"] == []
        assert resumed.lease.stopped.is_set() and all(client.closed for client in harness.clients)


def test_native_continuation_rechecks_current_source_before_polling(harness, monkeypatch):
    harness.settings["tabular_generated_output_inline_max_rows"] = 1
    with harness.native_io() as native:
        harness.create(
            [native_step()], seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
            original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        )
        first = harness.prepare()
        first_frames = first.execute()
        first_done = decoded_frames(first_frames)[-1]
        assert first_done["status"] == "waiting", first_done
        first_record = harness.read()
        native.state["allowed"] = False
        polls = []

        def forbidden_poll(**kwargs):
            polls.append(kwargs)
            raise AssertionError("A revoked source must be denied before native polling.")

        monkeypatch.setattr(native.results, "open_native_tabular_result", forbidden_poll)
        execution = harness.continue_waiting("revoked-native-event")
        frames = execution.execute()
        done = decoded_frames(frames)[-1]
        record = harness.read()
        messages = harness.assistant_messages()
        assert done["status"] == record["status"] == "failed", done
        assert polls == [] and native.jobs.created == 1 and harness.model_calls == []
        assert record["attempt_index"] == first_record["attempt_index"] == 1
        assert record["execution_deadline_at"] == first_record["execution_deadline_at"]
        assert execution.lease.token == first.lease.token
        assert len(messages) == 1 and messages[0]["id"] == first_done["message_id"] == done["message_id"]
        assert done["generated_artifacts"] == [] and harness.blobs.file_uploads == 0
        assert "Fixture document access revoked" not in json.dumps(done)
        assert execution.lease.stopped.is_set() and all(client.closed for client in harness.clients)


@pytest.mark.parametrize("disconnect", [ConnectionError, GeneratorExit])
def test_transport_disconnect_does_not_own_finalization(harness, disconnect):
    harness.create(replies=["The worker saved this answer."], final_response=input_binding("prepare"))
    execution = harness.prepare()

    def disconnected(frame):
        raise disconnect("Private browser transport details.")

    frames = execution.execute(emit=disconnected)
    again = execution.execute()
    done = decoded_frames(frames)[-1]
    record = harness.read()
    messages = harness.assistant_messages()
    assert done["message_saved"] is True and record["finalization_status"] == "saved"
    assert len(messages) == 1 and len(harness.model_calls) == 1
    assert again == frames
    assert execution.lease.stopped.is_set()
    assert all(client.closed for client in harness.clients)


@pytest.mark.parametrize("change", ["turn", "history", "owner", "memory_audience"])
def test_changed_saved_context_fails_before_model_or_upload(harness, change):
    history = [{
        "id": "old-message", "conversation_id": "conversation-1",
        "role": "user", "content": "Original constraint.", "timestamp": "2026-09-20T18:00:00+00:00",
    }]
    harness.create(replies=["Must not be generated."], history=history)
    record, lease = harness.claim()
    if change in {"turn", "history"}:
        item_id = harness.turn["id"] if change == "turn" else "old-message"
        changed = harness.messages.read_item(item_id, "conversation-1")
        changed["content"] = "Changed after approval."
        harness.messages.upsert_item(changed)
    else:
        changed = harness.conversations.read_item("conversation-1", "conversation-1")
        if change == "owner":
            changed["user_id"] = "another-user"
        else:
            changed["collaboration_conversation_id"] = "now-shared"
        harness.conversations.upsert_item(changed)
    with pytest.raises(HarnessExecutionError):
        prepare_harness_execution(record, settings=harness.settings, lease=lease)
    messages = harness.assistant_messages()
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0
    if change == "owner":
        assert messages == []
    else:
        assert len(messages) == 1 and messages[0]["metadata"]["orchestration"]["status"] == "failed"
    assert lease.stopped.is_set()


def test_saved_background_claims_cannot_elevate_current_identity(harness):
    harness.create(replies=["Must not be generated."])
    record = harness.read()
    record["identity_context"] = {"user_roles": ["UrlAccessUser"]}
    record["user_roles"] = ["UrlAccessUser"]
    harness.runs.upsert_item(record)
    execution = harness.prepare()
    assert execution.context.user_roles == []
    assert execution.context.agent_execution_identity.roles == ()
    execution.close()


def test_injected_claims_require_the_bound_execution_identity(harness):
    harness.create(replies=["Must not be generated."])
    record, lease = harness.claim()
    with pytest.raises(HarnessExecutionError):
        prepare_harness_execution(
            record, settings=harness.settings, lease=lease,
            identity_context={"user_roles": ["UrlAccessUser"]},
            execution_identity=ExecutionIdentity("owner", "conversation-1"),
        )
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0
    assert lease.stopped.is_set()


def test_foreign_execution_identity_is_not_accepted(harness):
    harness.create()
    record, lease = harness.claim()
    with pytest.raises(HarnessExecutionError):
        prepare_harness_execution(
            record, settings=harness.settings, lease=lease,
            execution_identity=ExecutionIdentity("someone-else", "conversation-1"),
        )
    assert harness.model_calls == []
    assert lease.stopped.is_set()


def test_cached_execution_identity_cannot_restore_background_roles(harness):
    harness.create()
    record, lease = harness.claim()
    with pytest.raises(HarnessExecutionError):
        prepare_harness_execution(
            record, settings=harness.settings, lease=lease,
            identity_context={"user_roles": ["UrlAccessUser"]},
            execution_identity=ExecutionIdentity(
                "owner", "conversation-1", roles=("UrlAccessUser",), email="stale@example.invalid",
            ),
        )
    assert harness.model_calls == []
    assert lease.stopped.is_set()


def test_no_implicit_claim_or_foreign_lease_cleanup(harness):
    saved = harness.create()
    with pytest.raises(HarnessExecutionError):
        prepare_harness_execution(saved, settings=harness.settings)
    record, lease = harness.claim()
    lease.start()
    foreign = {**record, "id": "someone-elses-run"}
    with pytest.raises(HarnessExecutionError):
        prepare_harness_execution(foreign, settings=harness.settings, lease=lease)
    current = harness.read()
    stopped = lease.stopped.is_set()
    lease.close(release=True)
    assert stopped is False
    assert current["execution_lease"]["token"] == lease.token
    assert harness.model_calls == []


def test_saved_legacy_plan_is_not_changed_or_executed(harness, monkeypatch):
    saved = harness.create()
    discovery = Mock(side_effect=AssertionError("Legacy preparation must not use private V2 discovery."))
    monkeypatch.setattr(harness.execution, "build_capability_request_context", discovery)
    monkeypatch.setattr(harness.bootstrap, "build_orchestration_services", discovery)
    legacy = {**deepcopy(saved), "plan": {**saved["plan"], "planner_contract_version": 1}}
    with pytest.raises(HarnessExecutionError):
        prepare_harness_execution(legacy, settings=harness.settings)
    unchanged = harness.read()
    assert unchanged["status"] == saved["status"]
    assert unchanged["started_at"] is None
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0
    discovery.assert_not_called()


def test_current_capability_revocation_prevents_a_model_call(harness):
    harness.create(replies=["Must not be generated."], final_response=input_binding("prepare"))
    execution = harness.prepare()
    harness.settings["chat_orchestration_enabled_capabilities"] = ["document_search"]
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    assert done["status"] == "failed" and done["message_saved"] is True
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0
    assert all(client.closed for client in harness.clients)


def test_context_edit_after_composition_does_not_publish_stale_content(harness):
    harness.create(replies=["Do not disclose this now-stale content."], final_response=input_binding("prepare"))
    execution = harness.prepare()

    def change_after_step(frame):
        event = decoded_frames([frame])[0]
        if event.get("step_id") == "prepare" and event.get("status") == "completed":
            changed = harness.messages.read_item(harness.turn["id"], "conversation-1")
            changed["content"] = "The user revised the approved request."
            harness.messages.upsert_item(changed)

    frames = execution.execute(emit=change_after_step)
    done = decoded_frames(frames)[-1]
    messages = harness.assistant_messages()
    assert len(harness.model_calls) == 1 and len(messages) == 1
    assert done["status"] == "failed" and done["message_saved"] is True
    assert "now-stale content" not in messages[0]["content"]
    assert "now-stale content" not in json.dumps(done)


def test_model_allocation_failure_closes_the_first_client_and_heartbeat(harness, monkeypatch):
    harness.settings["chat_orchestration_planner_deployment"] = "gpt-4o"
    harness.create()
    record, lease = harness.claim()
    allocate = harness.client

    def second_client_fails(**kwargs):
        if harness.clients:
            raise PermissionError("SECRET_SECOND_MODEL_DETAILS")
        return allocate(**kwargs)

    monkeypatch.setattr(harness.planner, "AzureOpenAI", second_client_fails)
    with pytest.raises(HarnessExecutionError) as failure:
        prepare_harness_execution(record, settings=harness.settings, lease=lease)
    saved = harness.read()
    messages = harness.assistant_messages()
    done = decoded_frames(failure.value.final_frames)[-1]
    assert len(harness.clients) == 1 and harness.clients[0].closed is True
    assert lease.stopped.is_set() and not lease.thread.is_alive()
    assert saved["status"] == "failed" and saved["message_saved"] is True
    assert failure.value.durable_status == saved["status"] == done["status"]
    assert done["message_saved"] is True and done["message_id"] == messages[0]["id"]
    assert len(messages) == 1
    assert "SECRET_SECOND_MODEL_DETAILS" not in json.dumps(messages)


@pytest.mark.parametrize("failure_point", ["settings", "bootstrap", "publication", "guard"])
def test_claimed_preparation_failure_has_an_explicit_durable_outcome(harness, monkeypatch, failure_point):
    harness.create()
    record, lease = harness.claim()
    if failure_point == "guard":
        harness.messages.fail_writes = True
    else:
        lease.start()
    if failure_point in {"settings", "publication"}:
        harness.settings["enable_chat_orchestration"] = False
    if failure_point == "publication":
        harness.messages.fail_batch_at = 1
    if failure_point == "bootstrap":
        original_import = builtins.__import__

        def failing_bootstrap_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 0 and name == "functions_orchestration_bootstrap":
                raise ImportError("PRIVATE_BOOTSTRAP_DIAGNOSTIC")
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", failing_bootstrap_import)
    before_results = harness.results.container.sequence
    with pytest.raises(HarnessExecutionError) as failure:
        prepare_harness_execution(record, settings=harness.settings, lease=lease)
    saved = harness.read()
    messages = harness.assistant_messages()
    assert saved["status"] == "failed"
    done = decoded_frames(failure.value.final_frames)[-1]
    published = failure_point in {"settings", "bootstrap"}
    assert failure.value.durable_status == done["status"] == "failed"
    assert saved["completed_at"] and saved["execution_lease"] is None
    assert done["message_saved"] is published and saved["message_saved"] is published
    assert saved["finalization_status"] == ("saved" if published else "failed")
    assert len(messages) == int(published)
    assert harness.model_calls == [] and harness.clients == [] and harness.blobs.file_uploads == 0
    assert harness.results.container.sequence == before_results
    assert not saved.get("task_results") and not saved.get("execution_steps")
    assert lease.stopped.is_set() and (lease.thread is None or not lease.thread.is_alive())
    assert "PRIVATE_BOOTSTRAP_DIAGNOSTIC" not in json.dumps(failure.value.final_frames)
    assert "Private test" not in json.dumps(failure.value.final_frames)


def test_preparation_failure_preserves_a_current_cancellation(harness):
    harness.create()
    record, lease = harness.claim()
    lease.start()
    lease.update({"cancellation_requested_at": "2026-09-21T19:00:00+00:00"})
    harness.settings["enable_chat_orchestration"] = False
    with pytest.raises(HarnessExecutionError) as failure:
        prepare_harness_execution(record, settings=harness.settings, lease=lease)
    saved = harness.read()
    done = decoded_frames(failure.value.final_frames)[-1]
    assert failure.value.durable_status == done["status"] == saved["status"] == "cancelled"
    assert saved["message_saved"] is True and saved["completed_at"]
    assert saved["execution_lease"] is None and lease.stopped.is_set()
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0


def test_preparation_failure_never_claims_a_status_it_could_not_persist(harness):
    harness.create()
    record, lease = harness.claim()
    lease.start()
    harness.runs.fail_writes = True
    harness.settings["enable_chat_orchestration"] = False
    with pytest.raises(HarnessExecutionError) as failure:
        prepare_harness_execution(record, settings=harness.settings, lease=lease)
    saved = harness.read()
    done = decoded_frames(failure.value.final_frames)[-1]
    assert failure.value.durable_status is None
    assert done["message_saved"] is False and done["finalization_status"] == "failed"
    assert saved["status"] == "running" and saved["execution_lease"]["token"] == lease.token
    assert harness.model_calls == [] and harness.assistant_messages() == []
    assert lease.stopped.is_set() and not lease.thread.is_alive()


def test_preparation_failure_cannot_finalize_a_replacement_owner(harness, monkeypatch):
    harness.create()
    record, lease = harness.claim()
    lease.start()

    def lost_owner_during_model_allocation(**kwargs):
        replacement = harness.read()
        replacement["execution_lease"]["token"] = "replacement-server-owner"
        harness.runs.upsert_item(replacement)
        raise PermissionError("PRIVATE_ALLOCATION_DIAGNOSTIC")

    monkeypatch.setattr(harness.planner, "AzureOpenAI", lost_owner_during_model_allocation)
    with pytest.raises(HarnessExecutionError) as failure:
        prepare_harness_execution(record, settings=harness.settings, lease=lease)
    saved = harness.read()
    done = decoded_frames(failure.value.final_frames)[-1]
    assert failure.value.durable_status is None and done["message_saved"] is False
    assert saved["status"] == "running" and saved["execution_lease"]["token"] == "replacement-server-owner"
    assert harness.model_calls == [] and harness.assistant_messages() == []
    assert lease.stopped.is_set() and not lease.thread.is_alive()
    assert "PRIVATE_ALLOCATION_DIAGNOSTIC" not in json.dumps(failure.value.final_frames)


def test_stale_lease_cannot_publish_or_release_the_new_owner(harness):
    harness.create(replies=["Private prepared answer."], final_response=input_binding("prepare"))
    execution = harness.prepare()
    replacement = harness.read()
    replacement["execution_lease"]["token"] = "different-server-owner"
    harness.runs.upsert_item(replacement)
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    current = harness.read()
    messages = harness.assistant_messages()
    assert done["status"] == "failed" and done["message_saved"] is False
    assert messages == [] and harness.model_calls == [] and harness.blobs.file_uploads == 0
    assert current["execution_lease"]["token"] == "different-server-owner"
    assert execution.lease.stopped.is_set()


def test_cancellation_publishes_honest_terminal_state_without_model(harness):
    harness.create(replies=["Must not be generated."], final_response=input_binding("prepare"))
    execution = harness.prepare()
    record = harness.read()
    record["cancellation_requested_at"] = "2026-09-21T19:00:00+00:00"
    harness.runs.upsert_item(record)
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    record = harness.read()
    assert done["status"] == record["status"] == "cancelled"
    assert done["message_saved"] is True and record["completed_at"]
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0
    assert len(harness.assistant_messages()) == 1


@pytest.mark.parametrize("authority", ["identity", "configuration"])
@pytest.mark.parametrize("entrypoint", ["prepare", "execute", "finalize"])
@pytest.mark.parametrize("wrapper", ["direct", "result", "checkpoint"])
def test_typed_invocation_cancellation_remains_cancellation(
    harness, monkeypatch, authority, entrypoint, wrapper,
):
    module = importlib.import_module(f"functions_orchestration_external_{authority}")
    cancellation_type = (
        module.ExternalIdentityCancelledError if authority == "identity"
        else module.ExternalConfigurationCancelledError
    )
    harness.create(replies=["PRIVATE_PREPARED_CONTENT"], final_response=input_binding("prepare"))
    execution, result = None, None
    if entrypoint == "prepare":
        record, lease = harness.claim()
    else:
        execution = harness.prepare()
        lease = execution.lease
        if entrypoint == "finalize":
            result = harness.run_engine(execution)
        record = lease.read()

    def cancelled_check():
        error = cancellation_type()
        if wrapper == "result":
            raise ResultUnavailableError("result_source_unavailable") from error
        if wrapper == "checkpoint":
            raise CheckpointError("checkpoint_unavailable") from error
        raise error

    monkeypatch.setattr(harness.bootstrap, "get_settings", cancelled_check)
    try:
        if entrypoint == "prepare":
            with pytest.raises(HarnessExecutionError) as failure:
                execution = prepare_harness_execution(record, settings=harness.settings, lease=lease)
            frames = failure.value.final_frames
            assert failure.value.code == "user_cancelled" and failure.value.durable_status == "cancelled"
        elif entrypoint == "execute":
            frames = execution.execute()
        else:
            frames = execution._finish(result, None)
    finally:
        if execution is not None:
            execution.close()
        lease.close()
    done = decoded_frames(frames)[-1]
    saved = harness.read()
    messages = harness.assistant_messages()
    assert done["status"] == done["outcome"] == saved["status"] == "cancelled"
    assert done["failure"]["code"] == "user_cancelled" and done["message_saved"] is True
    assert not saved.get("cancellation_requested_at") and saved["completed_at"]
    assert saved["task_results"] == (record.get("task_results") or {})
    assert saved["execution_lease"] is None and lease.stopped.is_set()
    assert len(harness.model_calls) == (1 if entrypoint == "finalize" else 0)
    assert len(messages) == 1 and "PRIVATE_" not in json.dumps(frames + messages)
    assert all(client.closed for client in harness.clients) and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("authority", ["identity", "configuration"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_delivery_preparation_cancellation_is_not_persisted_as_source_denial(
    harness, monkeypatch, authority, wrapped,
):
    harness.create(replies=["PRIVATE_PREPARED_CONTENT"], final_response=input_binding("prepare"))
    execution = harness.prepare()
    harness.run_engine(execution)
    record = execution.lease.read()
    module = importlib.import_module(f"functions_orchestration_external_{authority}")
    cancellation_type = (
        module.ExternalIdentityCancelledError if authority == "identity"
        else module.ExternalConfigurationCancelledError
    )

    def cancelled_check():
        error = cancellation_type()
        if wrapped:
            raise ResultUnavailableError("result_source_unavailable") from error
        raise error

    monkeypatch.setattr(harness.bootstrap, "get_settings", cancelled_check)
    try:
        with harness.publication_only(execution.services), pytest.raises(HarnessExecutionError) as failure:
            refresh_harness_delivery(
                record, services=execution.services, settings=harness.settings, lease=execution.lease,
            )
    finally:
        execution.close()
    saved = harness.read()
    messages = harness.assistant_messages()
    assert failure.value.code == "user_cancelled" and failure.value.retryable is False
    assert failure.value.final_frames == [] and failure.value.durable_status is None
    assert saved["status"] == record["status"] and saved["task_results"] == record["task_results"]
    assert not saved.get("failure") and saved["execution_lease"] is None and messages == []
    assert len(harness.model_calls) == 1 and execution.lease.stopped.is_set()
    assert all(client.closed for client in harness.clients) and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("error_type,nested_cancel", [
    (InterruptedError, False), (RuntimeError, False), (RuntimeError, True),
])
def test_untyped_owner_errors_are_not_inferred_to_be_invocation_cancellation(
    harness, monkeypatch, error_type, nested_cancel,
):
    harness.create()
    execution = harness.prepare()

    def interrupted_owner():
        error = error_type("PRIVATE_OWNER_DIAGNOSTIC")
        error.code = "external_configuration_cancelled"
        if nested_cancel:
            module = importlib.import_module("functions_orchestration_external_configuration")
            raise error from module.ExternalConfigurationCancelledError()
        raise error

    monkeypatch.setattr(harness.bootstrap, "get_settings", interrupted_owner)
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    saved = harness.read()
    assert done["status"] == saved["status"] == "failed"
    assert all(failure["code"] != "user_cancelled" for failure in done["failures"])
    assert "PRIVATE_" not in json.dumps(frames) and harness.model_calls == []
    assert execution.lease.stopped.is_set() and all(client.closed for client in harness.clients)


def test_failed_publication_never_reports_success_or_provider_text(harness):
    harness.create(replies=["Prepared but not published."], final_response=input_binding("prepare"))
    execution = harness.prepare()
    harness.messages.fail_batch_at = 1
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    record = harness.read()
    assert done["status"] == record["status"] == "failed"
    assert done["message_saved"] is False and record["message_saved"] is False
    assert record["finalization_status"] == "failed"
    assert harness.assistant_messages() == []
    assert "Private" not in json.dumps(decoded_frames(frames))
    assert "SECRET" not in json.dumps(decoded_frames(frames))
    assert all(client.closed for client in harness.clients)
    assert execution.lease.stopped.is_set()


def test_lost_publication_acknowledgement_requires_exact_guard_commit(harness):
    harness.create(replies=["Durable answer."], final_response=input_binding("prepare"))
    execution = harness.prepare()

    def lost_ack():
        raise ConnectionError("SECRET_PROVIDER_ACK")

    harness.messages.after_batch = lost_ack
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    messages = harness.assistant_messages()
    record = harness.read()
    assert done["message_saved"] is True and record["message_saved"] is True
    assert len(messages) == 1 and messages[0]["content"] == "Durable answer."
    assert "SECRET_PROVIDER_ACK" not in json.dumps(done)


def test_delivery_refresh_reuses_real_saved_results_without_any_execution(harness):
    harness.create(replies=["Previously prepared content."], final_response=input_binding("prepare"))
    execution = harness.prepare()
    result = harness.run_engine(execution)
    message_id = f"assistant_orchestration_{harness.execution.fingerprint('run-1')[:40]}"
    original_timestamp = "2026-09-21T20:00:00+00:00"
    previous = {
        "id": message_id, "conversation_id": "conversation-1", "role": "assistant",
        "content": "Checking saved delivery.", "timestamp": original_timestamp,
        "metadata": {"orchestration": {"run_id": "run-1", "status": "waiting"}},
        **execution.answer_model.metadata(), **execution._reasoning(),
    }
    execution.lease.publish_message(previous)
    execution.lease.update({
        "assistant_message_id": message_id, "assistant_message_created_at": original_timestamp,
        "message_saved": True, "finalization_status": "saved",
    })
    record = execution.lease.read()
    restarted_services = harness.services()
    before_usage = harness.execution._usage(
        record["harness_prompt_token_usage"], record["harness_step_token_usage"],
    )
    before_task_results = deepcopy(record["task_results"])
    before_producer_writes = harness.results.container.sequence

    try:
        with harness.publication_only(restarted_services):
            frames = refresh_harness_delivery(
                record, services=restarted_services, settings=harness.settings, lease=execution.lease,
            )
    finally:
        execution.close()
    done = decoded_frames(frames)[-1]
    saved = harness.read()
    messages = harness.assistant_messages()
    assert result["status"] == done["status"] == saved["status"] == "completed"
    assert done["message_id"] == message_id
    assert len(messages) == 1 and messages[0]["timestamp"] == original_timestamp
    assert done["full_content"] == messages[0]["content"] == "Previously prepared content."
    assert done["model_deployment_name"] == previous["model_deployment_name"]
    assert done["model_provider"] == previous["model_provider"]
    assert saved["token_usage"] == before_usage and before_usage["total_tokens"] == 10
    assert saved["task_results"] == before_task_results
    assert saved["attempt_index"] == 1 and saved["id"] == "run-1"
    assert saved["execution_deadline_at"] == record["execution_deadline_at"]
    assert harness.results.container.sequence == before_producer_writes
    assert len(harness.model_calls) == 1 and harness.blobs.file_uploads == 0
    assert saved["message_saved"] is True and saved["execution_lease"] is None
    assert all(client.closed for client in harness.clients)


def test_delivery_refresh_uses_real_committed_files_without_execution(harness):
    rows = [{"id": "001"}, {"id": "final-row"}]
    table = render_step("table", "csv", output="rows")
    table["arguments"]["options"] = {"columns": ["id"]}
    harness.create(
        [
            compose_step(outputs=[{
                "name": "rows", "kind": "records-v1",
                "columns": [{"name": "id", "value_type": "string", "nullable": False}],
            }]),
            table,
            render_step("data", "json", output="rows"),
        ],
        replies=[json.dumps({"rows": rows})],
    )
    execution = harness.prepare()
    try:
        result = harness.run_engine(execution)
        assert result["status"] == "completed", result
        record = execution.lease.update({
            "artifacts": [{
                "artifact_message_id": "stale-cached-file", "file_name": "uncommitted.csv",
                "output_id": "not-a-committed-output",
            }],
        })
        services = harness.services()
        producer_writes = harness.results.container.sequence
        before_tasks = deepcopy(record["task_results"])
        uploads = harness.blobs.file_uploads
        with harness.publication_only(services):
            expected_outputs = services.rendering.list_public_outputs("run-1")
            expected_artifacts = services.rendering.committed_artifacts("run-1")
            frames = refresh_harness_delivery(
                record, services=services, settings=harness.settings, lease=execution.lease,
            )
    finally:
        execution.close()
    done = decoded_frames(frames)[-1]
    saved = harness.read()
    messages = harness.assistant_messages()
    assert done["status"] == saved["status"] == "completed"
    assert done["outputs"] == expected_outputs == saved["outputs"]
    assert done["generated_artifacts"] == expected_artifacts == saved["artifacts"]
    assert len(expected_outputs) == len(expected_artifacts) == 2
    assert all(output["available"] and output["row_count"] == 2 for output in expected_outputs)
    assert len(messages) == 1 and messages[0]["generated_artifacts"] == expected_artifacts
    assert "stale-cached-file" not in json.dumps(done) and "uncommitted.csv" not in done["full_content"]
    assert "2 rows" in done["full_content"] and "ready" in done["full_content"]
    assert saved["task_results"] == before_tasks
    assert saved["execution_deadline_at"] == record["execution_deadline_at"]
    assert saved["attempt_index"] == 1 and saved["token_usage"]["total_tokens"] == 10
    assert harness.results.container.sequence == producer_writes
    assert harness.blobs.file_uploads == uploads == 2 and len(harness.model_calls) == 1
    assert done["message_saved"] is True and saved["finalization_status"] == "saved"
    assert saved["execution_lease"] is None and execution.lease.stopped.is_set()
    assert all(client.closed for client in harness.clients)


def test_delivery_refresh_rejects_an_unreconciled_running_claim(harness):
    harness.create(replies=["Must not be generated."])
    execution = harness.prepare()
    current = execution.lease.read()
    try:
        with harness.publication_only(execution.services), pytest.raises(HarnessExecutionError) as failure:
            refresh_harness_delivery(
                current, services=execution.services, settings=harness.settings, lease=execution.lease,
            )
    finally:
        execution.close()
    messages = harness.assistant_messages()
    assert failure.value.code == "result_not_ready"
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0
    assert messages == []
    assert execution.lease.stopped.is_set()


def test_delivery_refresh_does_not_call_a_model_to_explain_failure(harness):
    harness.create(replies=[RuntimeError("PRIVATE_PROVIDER_DETAILS")], final_response=input_binding("prepare"))
    execution = harness.prepare()
    result = harness.run_engine(execution)
    current = execution.lease.read()
    services = harness.services()
    try:
        with harness.publication_only(services):
            frames = refresh_harness_delivery(
                current, services=services, settings=harness.settings, lease=execution.lease,
            )
    finally:
        execution.close()
    done = decoded_frames(frames)[-1]
    messages = harness.assistant_messages()
    assert result["status"] == done["status"] == "failed"
    assert done["message_saved"] is True and len(messages) == 1
    assert len(harness.model_calls) == 1 and harness.blobs.file_uploads == 0
    assert "PRIVATE_PROVIDER_DETAILS" not in json.dumps(done)


@pytest.mark.parametrize("deadline_offset", [-1, 0, 1])
def test_deadline_failure_uses_the_exact_approved_boundary_without_execution(harness, monkeypatch, deadline_offset):
    harness.create()
    record, lease = harness.claim()
    lease.start()
    now = datetime.now(timezone.utc)

    class PublicationClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr(harness.execution, "datetime", PublicationClock)
    deadline = (now + timedelta(seconds=deadline_offset)).isoformat()
    record = lease.update({
        "started_at": (now - timedelta(minutes=10)).isoformat(),
        "execution_deadline_at": deadline,
    })
    services = harness.services()
    before_results = harness.results.container.sequence
    with harness.publication_only(services):
        if deadline_offset > 0:
            with pytest.raises(HarnessExecutionError) as failure:
                finalize_harness_failure(
                    record, failure_code="run_timeout", services=services,
                    settings=harness.settings, lease=lease,
                )
            frames = []
        else:
            frames = finalize_harness_failure(
                record, failure_code="run_timeout", services=services,
                settings=harness.settings, lease=lease,
            )
    saved = harness.read()
    messages = harness.assistant_messages()
    assert harness.model_calls == [] and harness.clients == [] and harness.blobs.file_uploads == 0
    assert harness.results.container.sequence == before_results
    assert saved["execution_deadline_at"] == deadline
    assert saved["id"] == record["id"] and saved["attempt_index"] == record["attempt_index"]
    assert saved["execution_lease"] is None and lease.stopped.is_set()
    if deadline_offset > 0:
        assert failure.value.code == "result_not_ready" and saved["status"] == "running"
        assert messages == []
    else:
        done = decoded_frames(frames)[-1]
        assert done["status"] == saved["status"] == "failed" and saved["completed_at"]
        assert done["failure"]["code"] == "run_timeout" and done["message_saved"] is True
        assert len(messages) == 1 and messages[0]["id"] == done["message_id"]


@pytest.mark.parametrize("failure_code", ["context_unavailable", "user_cancelled"])
def test_known_delivery_failure_never_prepares_models_or_replays_work(harness, failure_code):
    planning_usage = {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
    harness.create(planning_token_usage=planning_usage)
    record, lease = harness.claim()
    lease.start()
    if failure_code == "user_cancelled":
        record = lease.update({"cancellation_requested_at": datetime.now(timezone.utc).isoformat()})
    else:
        harness.settings["enable_chat_orchestration"] = False
    services = harness.services()
    with harness.publication_only(services):
        frames = finalize_harness_failure(
            record, failure_code=failure_code, services=services, settings=harness.settings, lease=lease,
        )
    done = decoded_frames(frames)[-1]
    saved = harness.read()
    messages = harness.assistant_messages()
    assert saved["status"] == done["status"] == ("cancelled" if failure_code == "user_cancelled" else "failed")
    assert done["failure"]["code"] == failure_code and done["message_saved"] is True
    assert saved["token_usage"] == done["metadata"]["token_usage"] == planning_usage
    assert saved["completed_at"] and saved["execution_lease"] is None
    assert len(messages) == 1 and harness.clients == [] and harness.model_calls == []
    assert harness.blobs.file_uploads == 0 and lease.stopped.is_set()


@pytest.mark.parametrize("failure_code", ["run_timeout", "user_cancelled"])
def test_delivery_failure_cannot_override_completed_work_without_a_real_terminal_condition(harness, monkeypatch, failure_code):
    harness.create(replies=["Already prepared."], final_response=input_binding("prepare"))
    execution = harness.prepare()
    harness.run_engine(execution)
    record = execution.lease.read()
    late = datetime.fromisoformat(record["execution_deadline_at"]) + timedelta(seconds=1)

    class PublicationClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return late.astimezone(tz) if tz is not None else late.replace(tzinfo=None)

    monkeypatch.setattr(harness.execution, "datetime", PublicationClock)
    services = harness.services()
    try:
        with harness.publication_only(services), pytest.raises(HarnessExecutionError) as failure:
            finalize_harness_failure(
                record, failure_code=failure_code, services=services,
                settings=harness.settings, lease=execution.lease,
            )
    finally:
        execution.close()
    saved = harness.read()
    messages = harness.assistant_messages()
    assert failure.value.code == "result_not_ready"
    assert saved["status"] == "completed" and saved["task_results"] == record["task_results"]
    assert messages == [] and len(harness.model_calls) == 1 and harness.blobs.file_uploads == 0


def test_delivery_context_denial_preserves_results_but_never_republishes_their_content(harness):
    harness.create(replies=["PRIVATE_PREPARED_CONTENT"], final_response=input_binding("prepare"))
    execution = harness.prepare()
    harness.run_engine(execution)
    record = execution.lease.read()
    changed = harness.messages.read_item(harness.turn["id"], "conversation-1")
    changed["content"] = "The approved context changed."
    harness.messages.upsert_item(changed)
    services = harness.services()
    try:
        with harness.publication_only(services):
            frames = refresh_harness_delivery(
                record, services=services, settings=harness.settings, lease=execution.lease,
            )
    finally:
        execution.close()
    done = decoded_frames(frames)[-1]
    saved = harness.read()
    messages = harness.assistant_messages()
    assert done["status"] == saved["status"] == "failed"
    assert done["failure"]["code"] == "context_unavailable" and done["message_saved"] is True
    assert saved["task_results"] == record["task_results"] and saved["token_usage"]["total_tokens"] == 10
    assert len(messages) == 1 and len(harness.model_calls) == 1
    assert "PRIVATE_PREPARED_CONTENT" not in json.dumps(frames + messages)
    assert execution.lease.stopped.is_set() and all(client.closed for client in harness.clients)


@pytest.mark.parametrize("outage", ["results", "messages", "publication", "settings", "run"])
def test_delivery_outage_is_not_persisted_as_source_denial(harness, monkeypatch, outage):
    harness.create(replies=["Saved content."], final_response=input_binding("prepare"))
    execution = harness.prepare()
    harness.run_engine(execution)
    record = execution.lease.read()
    services = harness.services()
    before_results = deepcopy(record["task_results"])
    try:
        if outage == "results":
            harness.results.container.fail_reads = True
        elif outage == "messages":
            harness.messages.fail_reads = True
        elif outage == "publication":
            harness.messages.fail_batch_at = 1
        elif outage == "run":
            harness.runs.fail_reads = True
        else:
            def unavailable_settings():
                raise ConnectionError("PRIVATE_BACKEND_DIAGNOSTIC")

            monkeypatch.setattr(harness.bootstrap, "get_settings", unavailable_settings)
        with harness.publication_only(services), pytest.raises(HarnessExecutionError) as failure:
            refresh_harness_delivery(
                record, services=services, settings=harness.settings, lease=execution.lease,
            )
    finally:
        harness.results.container.fail_reads = False
        harness.messages.fail_reads = False
        harness.runs.fail_reads = False
        execution.close()
    saved = harness.read()
    messages = harness.assistant_messages()
    assert failure.value.retryable is True and failure.value.code == "message_not_saved"
    assert failure.value.final_frames == [] and failure.value.durable_status is None
    assert saved["status"] == record["status"] == "completed" and not saved.get("failure")
    assert saved["task_results"] == before_results
    assert messages == [] and len(harness.model_calls) == 1 and harness.blobs.file_uploads == 0
    assert "PRIVATE_BACKEND_DIAGNOSTIC" not in failure.value.message
    assert execution.lease.stopped.is_set() and all(client.closed for client in harness.clients)


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("code,retryable", [
    ("external_identity_service_unavailable", True),
    ("external_identity_response_invalid", False),
])
def test_delivery_keeps_current_directory_failures_distinct_from_denial(harness, monkeypatch, wrapped, code, retryable):
    harness.create()
    record, lease = harness.claim()
    lease.start()
    services = harness.services()

    def unavailable_identity(*args, **kwargs):
        if wrapped:
            try:
                raise ExternalIdentityServiceError(code)
            except ExternalIdentityServiceError as exc:
                raise ResultUnavailableError("result_external_identity_unavailable") from exc
        raise ExternalIdentityServiceError(code)

    monkeypatch.setattr(harness.bootstrap, "current_execution_identity", unavailable_identity)
    with harness.publication_only(services), pytest.raises(HarnessExecutionError) as failure:
        finalize_harness_failure(
            record, failure_code="context_unavailable", services=services,
            settings=harness.settings, lease=lease,
        )
    saved = harness.read()
    messages = harness.assistant_messages()
    assert failure.value.code == "message_not_saved" and failure.value.retryable is retryable
    assert failure.value.final_frames == [] and failure.value.durable_status is None
    assert saved["status"] == record["status"] == "running"
    assert saved.get("task_results") == record.get("task_results")
    assert not saved.get("failure") and messages == []
    assert harness.model_calls == [] and harness.clients == [] and lease.stopped.is_set()


@pytest.mark.parametrize("sticky", [False, True])
@pytest.mark.parametrize("family,type_name,code,retryable", [
    ("identity", "ExternalIdentityServiceError", "external_identity_service_unavailable", True),
    ("identity", "ExternalIdentityServiceError", "external_identity_response_invalid", False),
    ("configuration", "ExternalConfigurationServiceError", "external_configuration_service_unavailable", True),
    ("configuration", "ExternalConfigurationServiceError", "external_configuration_metadata_invalid", False),
    ("identity", "ExternalIdentityCancelledError", None, False),
    ("configuration", "ExternalConfigurationCancelledError", None, False),
])
def test_real_capture_preserves_headless_authority_classification(
    harness, monkeypatch, sticky, family, type_name, code, retryable,
):
    capture_module = importlib.import_module("functions_orchestration_invocation_capture")
    authority_module = importlib.import_module(f"functions_orchestration_external_{family}")
    error_type = getattr(authority_module, type_name)
    original = error_type() if code is None else error_type(code)
    calls, observed = [], []

    def check_current_authority(source_type, **kwargs):
        calls.append(source_type)
        raise original from RuntimeError("PRIVATE_CAPTURE_PROVIDER_DIAGNOSTIC")

    capture = capture_module.OrchestrationInvocationCapture(check_current_authority)

    def unavailable_authority():
        try:
            capture("deep_research", settings={})
        except Exception as error:
            observed.append(error)
            if not sticky:
                raise
        capture.require_valid(captured=True)

    harness.create(replies=["MUST_NOT_BE_GENERATED"])
    record, lease = harness.claim()
    monkeypatch.setattr(harness.bootstrap, "get_settings", unavailable_authority)
    with pytest.raises(HarnessExecutionError) as failure:
        prepare_harness_execution(record, settings=harness.settings, lease=lease)
    saved = harness.read()
    messages = harness.assistant_messages()
    assert calls == ["deep_research"] and observed
    assert all(type(error) is error_type and error.__cause__ is None for error in observed)
    assert failure.value.retryable is retryable
    if code is None:
        assert failure.value.code == "user_cancelled" and failure.value.durable_status == "cancelled"
        assert saved["status"] == saved["outcome"] == "cancelled"
        assert not saved.get("cancellation_requested_at")
        frames = decoded_frames(failure.value.final_frames)
        assert frames[-1]["status"] == "cancelled" and frames[-1]["message_saved"] is True
    else:
        assert all(error.code == code and error.retryable is retryable for error in observed)
        assert failure.value.code == "message_not_saved"
        assert failure.value.final_frames == [] and failure.value.durable_status is None
        assert saved["status"] == record["status"] == "running"
        assert not saved.get("failure") and not saved.get("completed_at")
        assert messages == []
    assert saved["execution_lease"] is None and lease.stopped.is_set() and not lease.thread.is_alive()
    assert harness.clients == [] and harness.model_calls == [] and harness.blobs.file_uploads == 0
    assert "PRIVATE_" not in failure.value.message
    assert "PRIVATE_" not in json.dumps([saved, messages, failure.value.final_frames])


@pytest.mark.parametrize("boundary", ["prepare", "source", "model", "finalize", "refresh"])
@pytest.mark.parametrize("fault,code,retryable", [
    ("service", "external_configuration_service_unavailable", True),
    ("timeout", "external_configuration_timeout", True),
    ("throttled", "external_configuration_throttled", True),
    ("invalid", "external_configuration_metadata_invalid", False),
    ("limit", "external_configuration_limit_exceeded", False),
    ("cancelled", "external_configuration_cancelled", False),
    ("denied", None, False),
])
def test_actual_current_metadata_errors_survive_headless_boundaries(
    harness, monkeypatch, current_metadata, boundary, fault, code, retryable,
):
    source = current_metadata
    configuration = source.configuration
    harness.settings["enable_chat_orchestration_harness"] = False
    fault_entry_tasks = []

    def read_current_metadata():
        fault_entry_tasks.append(deepcopy(harness.read().get("task_results")))
        source.read()

    def answer_after_current_metadata():
        read_current_metadata()
        return "PRIVATE_UNVERIFIED_ANSWER"

    harness.create(
        replies=[answer_after_current_metadata if boundary == "model" else "PRIVATE_PREPARED_ANSWER"],
        final_response=input_binding("prepare"),
    )
    execution = None
    services = None
    if boundary == "prepare":
        record, lease = harness.claim()
        result = None
    else:
        execution = harness.prepare()
        result = harness.run_engine(execution) if boundary in {"finalize", "refresh"} else None
        lease = execution.lease
        record = lease.read()
        if boundary == "refresh":
            services = harness.services()
    source.arm(fault)

    if boundary != "model":
        read_settings = harness.bootstrap.get_settings

        def settings_after_current_metadata():
            read_current_metadata()
            return read_settings()

        monkeypatch.setattr(harness.bootstrap, "get_settings", settings_after_current_metadata)

    def run_boundary():
        if boundary == "prepare":
            return prepare_harness_execution(record, settings=harness.settings, lease=lease)
        if boundary in {"source", "model"}:
            return execution.execute()
        if boundary == "finalize":
            return execution._finish(result, None)
        with harness.publication_only(services):
            return refresh_harness_delivery(
                record, services=services, settings=harness.settings, lease=lease,
            )

    try:
        if fault not in {"cancelled", "denied"}:
            with pytest.raises(HarnessExecutionError) as failure:
                run_boundary()
            assert failure.value.code == "message_not_saved" and failure.value.retryable is retryable
            assert failure.value.final_frames == [] and failure.value.durable_status is None
            assert "PRIVATE_" not in failure.value.message
        elif boundary == "prepare" or boundary == "refresh" and fault == "cancelled":
            with pytest.raises(HarnessExecutionError) as failure:
                run_boundary()
            expected = "user_cancelled" if fault == "cancelled" else "context_unavailable"
            assert failure.value.code == expected and failure.value.retryable is False
        else:
            frames = run_boundary()
            done = decoded_frames(frames)[-1]
            expected = "cancelled" if fault == "cancelled" else "failed"
            assert done["status"] == expected and done["message_saved"] is True
    finally:
        if execution is not None:
            execution.close()

    saved = harness.read()
    messages = harness.assistant_messages()
    assert len(source.observed) == len(fault_entry_tasks) == 1
    observed = source.observed[0]
    if fault not in {"cancelled", "denied"}:
        assert type(observed) is configuration.ExternalConfigurationServiceError
        assert observed.code == code and observed.retryable is retryable
        assert saved["status"] == record["status"] and saved.get("task_results") == fault_entry_tasks[0]
        assert not saved.get("failure") and messages == []
    elif fault == "cancelled":
        assert type(observed) is configuration.ExternalConfigurationCancelledError
        assert observed.code == code
        if boundary != "refresh":
            assert saved["status"] == saved["outcome"] == "cancelled"
    else:
        assert type(observed) is ResultUnavailableError and saved["status"] == "failed"
    assert saved["execution_lease"] is None and lease.stopped.is_set()
    assert not lease.thread.is_alive() and all(client.closed for client in harness.clients)
    assert len(harness.model_calls) == (0 if boundary in {"prepare", "source"} else 1)
    assert harness.blobs.file_uploads == 0 and harness.settings["enable_chat_orchestration_harness"] is False
    assert "PRIVATE_" not in json.dumps([messages, saved.get("failure")])


@pytest.mark.parametrize("sticky", [False, True])
@pytest.mark.parametrize("fault,code,retryable", [
    ("service", "external_configuration_service_unavailable", True),
    ("timeout", "external_configuration_timeout", True),
    ("throttled", "external_configuration_throttled", True),
    ("invalid", "external_configuration_metadata_invalid", False),
    ("limit", "external_configuration_limit_exceeded", False),
    ("cancelled", "external_configuration_cancelled", False),
])
def test_actual_current_metadata_capture_preserves_initial_and_sticky_failure(
    harness, monkeypatch, current_metadata, sticky, fault, code, retryable,
):
    source = current_metadata
    capture_module = importlib.import_module("functions_orchestration_invocation_capture")
    capture = capture_module.OrchestrationInvocationCapture(lambda _source_type, **_kwargs: source.read())
    observed = []
    harness.create(replies=["MUST_NOT_BE_GENERATED"])
    record, lease = harness.claim()
    source.arm(fault)

    def current_configuration():
        try:
            capture("web", settings={})
        except (
            source.configuration.ExternalConfigurationServiceError,
            source.configuration.ExternalConfigurationCancelledError,
        ) as error:
            observed.append((error, error.__cause__, error.__context__))
            if not sticky:
                raise
        capture.require_valid(captured=True)

    monkeypatch.setattr(harness.bootstrap, "get_settings", current_configuration)
    with pytest.raises(HarnessExecutionError) as failure:
        prepare_harness_execution(record, settings=harness.settings, lease=lease)
    saved = harness.read()
    messages = harness.assistant_messages()
    assert len(source.requests) == len(source.observed) == len(observed) == 1
    original = source.observed[0]
    preserved, cause, context = observed[0]
    assert type(preserved) is type(original) and preserved.code == original.code == code
    assert cause is None and context is None
    assert failure.value.retryable is retryable
    if fault == "cancelled":
        assert failure.value.code == "user_cancelled" and failure.value.durable_status == "cancelled"
        assert saved["status"] == saved["outcome"] == "cancelled"
    else:
        assert preserved.retryable is retryable
        assert failure.value.code == "message_not_saved" and failure.value.durable_status is None
        assert failure.value.final_frames == [] and saved["status"] == record["status"] == "running"
        assert not saved.get("failure") and not saved.get("completed_at") and messages == []
    assert saved["execution_lease"] is None and lease.stopped.is_set() and not lease.thread.is_alive()
    assert harness.clients == [] and harness.model_calls == [] and harness.blobs.file_uploads == 0
    assert "PRIVATE_" not in json.dumps([saved, messages, failure.value.final_frames])


@pytest.mark.parametrize("entrypoint", ["prepare", "finalize", "refresh"])
@pytest.mark.parametrize("wrapper", ["direct", "result", "checkpoint", "nested"])
@pytest.mark.parametrize("authority,retryable", [
    ("directory_service", True), ("directory_response", False),
    ("screening_service", True), ("screening_configuration", False),
    ("checkpoint_storage_read", True), ("checkpoint_storage_code", True),
    ("output_storage", True),
    ("external_configuration_service_unavailable", True),
    ("external_configuration_timeout", True),
    ("external_configuration_throttled", True),
    ("external_configuration_metadata_invalid", False),
    ("external_configuration_limit_exceeded", False),
])
def test_authority_infrastructure_never_becomes_a_headless_denial(
    harness, monkeypatch, entrypoint, wrapper, authority, retryable,
):
    harness.create(replies=["PRIVATE_PREPARED_CONTENT"], final_response=input_binding("prepare"))
    execution = None
    if entrypoint == "prepare":
        record, lease = harness.claim()
        result = None
    else:
        execution = harness.prepare()
        result = harness.run_engine(execution)
        lease = execution.lease
        record = lease.read()
    services = harness.services()
    before_tasks = deepcopy(record.get("task_results"))

    def unavailable_checkpoint_read(*args, **kwargs):
        raise ServiceRequestError("PRIVATE_CHECKPOINT_STORAGE_DIAGNOSTIC")

    if authority == "checkpoint_storage_read":
        monkeypatch.setattr(harness.steps, "read_item", unavailable_checkpoint_read)

    def unavailable_authority():
        if authority == "directory_service":
            error = ExternalIdentityServiceError()
        elif authority == "directory_response":
            error = ExternalIdentityServiceError("external_identity_response_invalid")
        elif authority == "screening_service":
            error = ScreeningError("PRIVATE_AUTHORITY_DIAGNOSTIC")
        elif authority == "screening_configuration":
            error = ScreeningConfigurationError("PRIVATE_AUTHORITY_DIAGNOSTIC")
        elif authority == "checkpoint_storage_read":
            store = harness.recovery.checkpoint_store(record, lease.read)
            try:
                store.has_manifest("prepare")
            except CheckpointError as storage_error:
                error = storage_error
            else:
                raise AssertionError("The real checkpoint presence read must fail.")
            assert error.code == "checkpoint_storage_unavailable"
        elif authority == "checkpoint_storage_code":
            error = CheckpointError("checkpoint_storage_unavailable")
        elif authority == "output_storage":
            output_store = importlib.import_module("functions_orchestration_output_store")
            error = output_store.OutputStorageError()
        else:
            configuration = importlib.import_module("functions_orchestration_external_configuration")
            error = configuration.ExternalConfigurationServiceError(authority)
        if wrapper == "nested":
            try:
                raise ResultUnavailableError("result_source_unavailable") from error
            except ResultUnavailableError as wrapped:
                raise CheckpointError("checkpoint_unavailable") from wrapped
        if wrapper == "checkpoint":
            raise CheckpointError("checkpoint_unavailable") from error
        if wrapper == "result":
            raise ResultUnavailableError("result_source_unavailable") from error
        raise error

    monkeypatch.setattr(harness.bootstrap, "get_settings", unavailable_authority)
    try:
        with pytest.raises(HarnessExecutionError) as failure:
            if entrypoint == "prepare":
                prepare_harness_execution(record, settings=harness.settings, lease=lease)
            elif entrypoint == "finalize":
                execution._finish(result, None)
            else:
                with harness.publication_only(services):
                    refresh_harness_delivery(
                        record, services=services, settings=harness.settings, lease=lease,
                    )
    finally:
        if execution is not None:
            execution.close()
    saved = harness.read()
    messages = harness.assistant_messages()
    assert failure.value.code == "message_not_saved"
    assert failure.value.retryable is retryable and failure.value.final_frames == []
    assert failure.value.durable_status is None and not saved.get("failure")
    assert saved["status"] == record["status"] and saved.get("task_results") == before_tasks
    assert saved["execution_lease"] is None and lease.stopped.is_set()
    assert messages == [] and harness.blobs.file_uploads == 0
    assert len(harness.model_calls) == (0 if entrypoint == "prepare" else 1)
    assert all(client.closed for client in harness.clients)
    assert "PRIVATE_" not in failure.value.message


def test_checkpoint_read_outage_preserves_the_committed_file_before_publication(harness, monkeypatch):
    harness.create(
        [compose_step(), render_step("report", "md")],
        replies=["The complete retained report."],
    )
    execution = harness.prepare()
    result = harness.run_engine(execution)
    original = execution.lease.read()
    services = harness.services()
    outputs = services.rendering.list_public_outputs("run-1")
    artifacts = services.rendering.committed_artifacts("run-1")
    messages = harness.assistant_messages()
    read_item = harness.steps.read_item
    failed_reads = []

    def unavailable_checkpoint_body(item, partition_key, **kwargs):
        if item != "checkpoint:lifecycle":
            failed_reads.append(item)
            raise ServiceRequestError("PRIVATE_CHECKPOINT_READ_DIAGNOSTIC")
        return read_item(item=item, partition_key=partition_key, **kwargs)

    try:
        with monkeypatch.context() as unavailable:
            unavailable.setattr(harness.steps, "read_item", unavailable_checkpoint_body)
            with pytest.raises(HarnessExecutionError) as failure:
                execution._finish(result, None)
    finally:
        execution.close()
    saved = harness.read()
    current_outputs = services.rendering.list_public_outputs("run-1")
    current_artifacts = services.rendering.committed_artifacts("run-1")
    current_messages = harness.assistant_messages()
    assert failed_reads and failure.value.code == "message_not_saved"
    assert failure.value.retryable is True and failure.value.final_frames == []
    assert failure.value.durable_status is None
    assert saved["status"] == original["status"] == "completed" and not saved.get("failure")
    assert saved["task_results"] == original["task_results"]
    assert saved["execution_deadline_at"] == original["execution_deadline_at"]
    assert saved["execution_lease"] is None and saved.get("message_saved") is not True
    assert current_outputs == outputs and current_artifacts == artifacts
    assert len(artifacts) == 1 and outputs[0]["state"] == "completed"
    assert current_messages == messages == []
    assert len(harness.model_calls) == 1 and harness.blobs.file_uploads == 1
    assert all(client.closed for client in harness.clients) and execution.lease.stopped.is_set()
    assert "PRIVATE_" not in failure.value.message


def test_real_native_checkpoint_read_outage_does_not_poll_or_finalize(harness, monkeypatch):
    harness.settings["tabular_generated_output_inline_max_rows"] = 1
    with harness.native_io(row_count=3) as native:
        harness.create(
            [native_step()], seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
            original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        )
        first = harness.prepare()
        first_frames = first.execute()
        original = harness.read()
        messages = harness.assistant_messages()
        assert decoded_frames(first_frames)[-1]["status"] == original["status"] == "waiting"
        continued = harness.continue_waiting("checkpoint-read-outage")
        claimed = continued.lease.read()
        read_item = harness.steps.read_item
        failed_reads = []

        def unavailable_checkpoint_body(item, partition_key, **kwargs):
            if item != "checkpoint:lifecycle":
                failed_reads.append(item)
                raise ServiceRequestError("PRIVATE_NATIVE_CHECKPOINT_DIAGNOSTIC")
            return read_item(item=item, partition_key=partition_key, **kwargs)

        poll = Mock(side_effect=AssertionError("Unverified native checkpoints must not be polled."))
        monkeypatch.setattr(native.results, "open_native_tabular_result", poll)
        monkeypatch.setattr(harness.steps, "read_item", unavailable_checkpoint_body)
        with pytest.raises(HarnessExecutionError) as failure:
            continued.execute()
        saved = harness.read()
        current_messages = harness.assistant_messages()
        assert failed_reads and failure.value.code == "message_not_saved"
        assert failure.value.retryable is True and failure.value.final_frames == []
        assert failure.value.durable_status is None
        assert saved["status"] == claimed["status"] == "running" and not saved.get("failure")
        assert saved["task_results"] == original["task_results"]
        assert saved["pending_results"] == original["pending_results"]
        assert saved["execution_binding"] == original["execution_binding"]
        assert saved["execution_deadline_at"] == original["execution_deadline_at"]
        assert saved["attempt_index"] == 1 and saved["execution_lease"] is None
        assert current_messages == messages and native.jobs.created == 1
        assert harness.model_calls == [] and harness.blobs.file_uploads == 0
        poll.assert_not_called()
        assert continued.lease.stopped.is_set() and all(client.closed for client in harness.clients)
        assert "PRIVATE_" not in failure.value.message


@pytest.mark.parametrize("code", [
    "checkpoint_unavailable", "checkpoint_invalid", "context_unavailable",
    "recovery_changed", "ownership_lost", "result_unavailable", "provider_code_lookalike",
])
def test_checkpoint_storage_classification_does_not_relabel_definitive_failures(harness, monkeypatch, code):
    harness.create()
    record, lease = harness.claim()
    if code == "provider_code_lookalike":
        error = RuntimeError("PRIVATE_PROVIDER_DIAGNOSTIC")
        error.code = "checkpoint_storage_unavailable"
        error.retryable = True
        expected = "execution_interrupted"
    else:
        error = CheckpointError(code)
        expected = code

    def unavailable_authority():
        raise error

    monkeypatch.setattr(harness.bootstrap, "get_settings", unavailable_authority)
    with pytest.raises(HarnessExecutionError) as failure:
        prepare_harness_execution(record, settings=harness.settings, lease=lease)
    saved = harness.read()
    assert failure.value.code == expected and failure.value.retryable is False
    assert failure.value.durable_status == saved["status"] == "failed"
    assert saved["failure"]["code"] == expected
    assert saved["execution_lease"] is None and lease.stopped.is_set()
    assert harness.clients == [] and harness.model_calls == [] and harness.blobs.file_uploads == 0
    assert "PRIVATE_" not in json.dumps([saved, failure.value.final_frames])


@pytest.mark.parametrize("denial", [DocumentHeldError, ResultUnavailableError])
def test_genuine_hold_or_denial_still_finalizes_without_prepared_content(harness, monkeypatch, denial):
    harness.create(replies=["PRIVATE_PREPARED_CONTENT"], final_response=input_binding("prepare"))
    execution = harness.prepare()
    result = harness.run_engine(execution)
    record = execution.lease.read()

    def denied_authority():
        raise denial("PRIVATE_AUTHORITY_DIAGNOSTIC")

    monkeypatch.setattr(harness.bootstrap, "get_settings", denied_authority)
    try:
        frames = execution._finish(result, None)
    finally:
        execution.close()
    done = decoded_frames(frames)[-1]
    saved = harness.read()
    messages = harness.assistant_messages()
    assert done["status"] == saved["status"] == "failed"
    assert done["failure"]["code"] == "context_unavailable" and done["message_saved"] is True
    assert saved["task_results"] == record["task_results"]
    assert len(messages) == 1 and "PRIVATE_" not in json.dumps(frames + messages)
    assert saved["execution_lease"] is None and execution.lease.stopped.is_set()
    assert all(client.closed for client in harness.clients)


@pytest.mark.parametrize("code,retryable", [
    ("external_identity_service_unavailable", True),
    ("external_identity_response_invalid", False),
])
def test_execution_publication_authority_failure_closes_without_a_success_frame(
    harness, monkeypatch, code, retryable,
):
    harness.create(replies=["PRIVATE_PREPARED_CONTENT"], final_response=input_binding("prepare"))
    execution = harness.prepare()

    def uncertain_publication(*args, **kwargs):
        raise ExternalIdentityServiceError(code)

    monkeypatch.setattr(harness.messages, "execute_item_batch", uncertain_publication)
    progress = []
    with pytest.raises(HarnessExecutionError) as failure:
        execution.execute(emit=progress.append)
    saved = harness.read()
    messages = harness.assistant_messages()
    assert failure.value.code == "message_not_saved" and failure.value.retryable is retryable
    assert failure.value.final_frames == [] and failure.value.durable_status is None
    assert saved["status"] == "completed" and saved.get("failure") is None
    assert saved["message_saved"] is False and saved["finalization_status"] == "pending"
    assert all(event.get("type") != "done" for event in decoded_frames(progress))
    assert messages == [] and len(harness.model_calls) == 1
    assert execution.lease.stopped.is_set() and not execution.lease.thread.is_alive()
    assert saved["execution_lease"] is None and all(client.closed for client in harness.clients)


@pytest.mark.parametrize("change", ["deleted_conversation", "owner", "superseded", "outputs_deleted", "checkpoints_deleted"])
def test_delivery_failure_does_not_publish_into_a_gone_or_superseded_context(harness, change):
    harness.create()
    record, lease = harness.claim()
    lease.start()
    services = harness.services()
    if change in {"deleted_conversation", "owner"}:
        conversation = harness.conversations.read_item("conversation-1", "conversation-1")
        if change == "deleted_conversation":
            harness.conversations.delete_item("conversation-1", "conversation-1", etag=conversation["_etag"])
        else:
            conversation["user_id"] = "someone-else"
            harness.conversations.upsert_item(conversation)
    else:
        changes = (
            {"status": "superseded", "superseded_by_run_id": "next-run"}
            if change == "superseded" else {change: True}
        )
        lease.update(changes)
    with harness.publication_only(services), pytest.raises(HarnessExecutionError) as failure:
        finalize_harness_failure(
            record, failure_code="context_unavailable", services=services, settings=harness.settings, lease=lease,
        )
    saved = harness.read()
    messages = harness.assistant_messages()
    assert failure.value.durable_status is None and failure.value.retryable is False
    assert saved["status"] != "failed" and messages == []
    assert harness.model_calls == [] and harness.clients == [] and harness.blobs.file_uploads == 0
    assert lease.stopped.is_set()


def test_saved_v2_is_not_reinterpreted_by_a_rollout_setting(harness, monkeypatch):
    admission = importlib.import_module("functions_orchestration_admission")

    def forbidden_new_admission(*args, **kwargs):
        raise AssertionError("A saved V2 attempt must not run through new-plan admission.")

    monkeypatch.setattr(admission, "HARNESS_ADMISSION_READY", False)
    monkeypatch.setattr(admission, "get_new_plan_contract_version", forbidden_new_admission)
    harness.create(replies=["Still V2."], final_response=input_binding("prepare"))
    harness.settings["enable_chat_orchestration_harness"] = False
    execution = harness.prepare()
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    assert execution.context.plan_contract_version == 2
    assert done["status"] == "completed" and done["full_content"] == "Still V2."


EARLY_PROBE = r'''
import builtins
import importlib
import socket
import sys
from unittest.mock import patch

sys.path[:0] = sys.argv[1:3]
original = builtins.__import__
network_attempts = []
forbidden = {"config", "functions_settings", "route_backend_orchestration", "app", "background_tasks"}
def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and name in forbidden:
        raise AssertionError("Headless import initialized an owner: " + name)
    return original(name, globals, locals, fromlist, level)
def no_network(*args, **kwargs):
    network_attempts.append(True)
    raise AssertionError("Cold import attempted network access")
with patch.object(builtins, "__import__", guarded_import), patch.object(socket.socket, "connect", no_network):
    for name in sys.argv[3:]:
        importlib.import_module(name)
    module = importlib.import_module("functions_orchestration_execution")
    if not all(callable(function) for function in (
        module.prepare_harness_execution, module.HarnessExecution.execute,
        module.refresh_harness_delivery, module.finalize_harness_failure,
    )):
        raise AssertionError("Missing real headless boundary")
    for function, keywords in (
        (module.prepare_harness_execution, {}),
        (module.refresh_harness_delivery, {}),
        (module.finalize_harness_failure, {"failure_code": "context_unavailable"}),
    ):
        try:
            function({"plan": {"planner_contract_version": 2}}, **keywords)
        except module.HarnessExecutionError as error:
            if error.code != "ownership_lost":
                raise
        else:
            raise AssertionError("An unclaimed attempt was accepted")
    if forbidden.intersection(sys.modules) or network_attempts:
        raise AssertionError("An early owner or network side effect was hidden")
print("PASS: cold headless execution imports")
'''


BOOTSTRAP_PROBE = r'''
import importlib
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = sys.argv[1:3]
from test_support import offline_bootstrap
from test_support.orchestration_harness_execution import project_session_cache
with patch.object(offline_bootstrap, "TemporaryDirectory", project_session_cache):
    with offline_bootstrap.offline_app_imports() as environment:
        for name in sys.argv[3:]:
            try:
                importlib.import_module(name)
            except NameError as error:
                frames = traceback.extract_tb(error.__traceback__)
                if (
                    sys.argv[3] == "background_tasks" and error.name == "enabled_required"
                    and any(Path(frame.filename).name == "route_backend_agents.py" for frame in frames)
                    and not environment.network_attempts
                ):
                    print("BASELINE: background_tasks -> app -> route_backend_agents enabled_required NameError")
                    sys.exit(31)
                raise
        web = importlib.import_module("app")
        scheduler = importlib.import_module("background_tasks")
        headless = importlib.import_module("functions_orchestration_execution")
        if not hasattr(web, "app") or not callable(scheduler.check_m365_workflow_continuations_once):
            raise AssertionError("The real owner bootstrap did not finish")
        if not callable(headless.prepare_harness_execution) or environment.network_attempts:
            raise AssertionError("The headless boundary failed in an owner bootstrap")
print("PASS: real web/scheduler headless boundary")
'''

EXECUTION_PROBE = r'''
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

sys.path[:0] = sys.argv[1:3]
from test_support import offline_bootstrap
from test_support.orchestration_harness_execution import (
    HarnessEnvironment, decoded_frames, input_binding, project_session_cache,
)
from content_screening import access as screening_access
from content_screening.contracts import SourceAuthorityUnavailableError
with patch.object(offline_bootstrap, "TemporaryDirectory", project_session_cache):
    with offline_bootstrap.offline_app_imports() as environment, pytest.MonkeyPatch.context() as monkeypatch:
        for reply, status in (("Exact cold-process content.", "completed"), (RuntimeError("PRIVATE_MODEL_FAILURE"), "failed")):
            harness = HarnessEnvironment(monkeypatch)
            harness.create(replies=[reply], final_response=input_binding("prepare"))
            execution = harness.prepare()
            source_access = sys.modules["functions_orchestration_source_access"]
            if (
                execution.services.results.access.source_resolver is not source_access.resolve_orchestration_source_manifest
                or execution.services.results.access.source_metadata_reader is not source_access.read_orchestration_source_metadata
            ):
                execution.close()
                raise AssertionError("The fixture replaced a real strict source-authority callback")
            frames = execution.execute()
            done = decoded_frames(frames)[-1]
            saved = harness.read()
            messages = harness.assistant_messages()
            if done["status"] != status or saved["status"] != status or done["message_saved"] is not True:
                raise AssertionError("The real headless outcome was not saved")
            if len(messages) != 1 or len(harness.model_calls) != 1 or harness.blobs.file_uploads:
                raise AssertionError("A required operation disappeared or publication was duplicated")
            if saved["execution_lease"] is not None or not execution.lease.stopped.is_set():
                raise AssertionError("The owning worker did not release its heartbeat")
            if not all(client.closed for client in harness.clients):
                raise AssertionError("A model client leaked")
            if "PRIVATE_MODEL_FAILURE" in messages[0]["content"]:
                raise AssertionError("A provider diagnostic escaped")
        caught = []

        def unavailable_source(**kwargs):
            raise TimeoutError("PRIVATE_AUTHORITY_DIAGNOSTIC")

        def reply_after_caught_failure():
            try:
                screening_access.assert_document_available(
                    "document-1", "owner", metadata_reader=unavailable_source, strict_errors=True,
                )
            except SourceAuthorityUnavailableError:
                caught.append(True)
            return "PRIVATE_UNVERIFIED_ANSWER"

        harness = HarnessEnvironment(monkeypatch)
        harness.create(replies=[reply_after_caught_failure], final_response=input_binding("prepare"))
        execution = harness.prepare()
        try:
            execution.execute()
        except harness.execution.HarnessExecutionError as error:
            if not error.retryable or error.final_frames or error.durable_status is not None:
                raise AssertionError("An uncertain authority outcome was misclassified")
        else:
            raise AssertionError("A caught source failure escaped the real model fence")
        finally:
            execution.close()
        saved = harness.read()
        messages = harness.assistant_messages()
        screening_access.assert_current_request_sources_available("owner")
        if screening_access.strict_source_authority_enabled() or caught != [True]:
            raise AssertionError("The source decision disappeared or leaked beyond its operation")
        if saved["status"] != "running" or saved.get("failure") or saved.get("task_results") or messages:
            raise AssertionError("Unverified model content acquired a durable terminal outcome")
        if len(harness.model_calls) != 1 or not all(client.closed for client in harness.clients):
            raise AssertionError("The actual model call or its cleanup disappeared")
        if saved["execution_lease"] is not None or not execution.lease.stopped.is_set():
            raise AssertionError("Uncertain source authority leaked its owning lease")
        harness = HarnessEnvironment(monkeypatch)
        harness.create()
        record, lease = harness.claim()
        lease.start()
        record = lease.update({"cancellation_requested_at": "2026-09-21T19:00:00+00:00"})
        services = harness.services()
        with harness.publication_only(services):
            frames = harness.execution.finalize_harness_failure(
                record, failure_code="user_cancelled", services=services,
                settings=harness.settings, lease=lease,
            )
        done = decoded_frames(frames)[-1]
        saved = harness.read()
        messages = harness.assistant_messages()
        if done["status"] != "cancelled" or saved["status"] != "cancelled" or len(messages) != 1:
            raise AssertionError("Required model-free finalization disappeared")
        if harness.clients or harness.model_calls or harness.blobs.file_uploads:
            raise AssertionError("Failure finalization executed work")
        if saved["execution_lease"] is not None or not lease.stopped.is_set():
            raise AssertionError("Failure finalization leaked its owning lease")
        if environment.network_attempts:
            raise AssertionError("Execution swallowed a blocked external request")
print("PASS: real cold-process execution success and failure")
'''


def run_probe(probe, modules, optimized):
    command = [sys.executable, "-B"] + (["-O"] if optimized else [])
    process = subprocess.run(
        command + ["-c", probe, str(APP), str(TESTS), *modules],
        cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
    )
    return process


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("functions_orchestration_execution", "functions_orchestration_executor"),
    ("functions_orchestration_executor", "functions_orchestration_execution"),
])
def test_cold_headless_imports_do_not_discover_application_owners(order, optimized):
    process = run_probe(EARLY_PROBE, order, optimized)
    assert process.returncode == 0, process.stdout[-6000:] + process.stderr[-6000:]
    assert "PASS:" in process.stdout


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("functions_orchestration_execution", "app", "background_tasks"),
    ("background_tasks", "functions_orchestration_execution", "app"),
])
def test_real_web_scheduler_bootstrap_import_boundaries(order, optimized):
    process = run_probe(BOOTSTRAP_PROBE, order, optimized)
    if process.returncode == 31 and "BASELINE:" in process.stdout:
        pytest.xfail("Pre-existing scheduler-first background_tasks -> app NameError.")
    assert process.returncode == 0, process.stdout[-6000:] + process.stderr[-6000:]
    assert "PASS:" in process.stdout


@pytest.mark.parametrize("optimized", [False, True])
def test_real_headless_execution_keeps_required_operations_under_optimization(optimized):
    process = run_probe(EXECUTION_PROBE, (), optimized)
    assert process.returncode == 0, process.stdout[-6000:] + process.stderr[-6000:]
    assert "PASS:" in process.stdout
