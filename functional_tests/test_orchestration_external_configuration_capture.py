# test_orchestration_external_configuration_capture.py
"""
Functional tests for private, invocation-time Gather configuration capture.
Version: 0.261.134
Implemented in: 0.261.127
Acquisition-boundary coverage updated in: 0.261.129
Pre-acquisition provider failure classification updated in: 0.261.134

Real adapters, web search and source review run with provider/page I/O doubled.
No live provider, remote configuration or user artifact is accessed.
"""

import asyncio
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
import hashlib
import hmac
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from azure.ai.agents.models import Agent, AgentThread, RunStep, ThreadMessage, ThreadRun
import pytest
from semantic_kernel.agents import AzureAIAgent as SdkAzureAIAgent
from semantic_kernel.agents.azure_ai.azure_ai_agent import AgentThreadActions
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.contents import AuthorRole, ChatMessageContent, FunctionCallContent
from semantic_kernel.functions import kernel_function

from test_orchestration_external_sources import ExternalSourceWorld
from test_support.offline_bootstrap import offline_app_imports


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"


@pytest.fixture(scope="module")
def gather_modules():
    previous = set(sys.modules)
    try:
        with pytest.MonkeyPatch.context() as monkeypatch, offline_app_imports() as offline:
            monkeypatch.syspath_prepend(str(APP))
            # Reuse the loop created before Windows loopback sockets are blocked.
            monkeypatch.setattr(asyncio, "run", offline.loop.run_until_complete)
            modules = SimpleNamespace(
                adapters=importlib.import_module("functions_orchestration_adapters"),
                web=importlib.import_module("route_backend_chats"),
                review=importlib.import_module("functions_source_review"),
                foundry=importlib.import_module("foundry_agent_runtime"),
                configuration=importlib.import_module("functions_orchestration_external_configuration"),
                runtime=importlib.import_module("functions_orchestration_executor"),
            )
            for module in vars(modules).values():
                assert Path(module.__file__).resolve().parent == APP
            yield modules
    finally:
        for name in set(sys.modules) - previous:
            if str(APP) in (getattr(sys.modules[name], "__file__", "") or ""):
                sys.modules.pop(name, None)


@pytest.fixture
def capture_runtime(gather_modules, monkeypatch):
    modules = gather_modules
    authorization_world = ExternalSourceWorld()
    state = SimpleNamespace(
        calls=[], captured=[], sources=[], private={}, web=[], pages=[], fail_capture=False,
        credentials=[], clients=[], invocations=[], selected_settings=None,
        run_mutation=None, skip_run=False, poll_run=False, fail_phase=None,
    )
    settings = {
        "enable_web_search": True, "enable_url_access": True, "enable_source_review": True,
        "enable_semantic_kernel": True, "enable_deep_source_review": False,
        "deep_research_max_search_queries_per_turn": 1, "deep_research_enable_query_planning": False,
        "source_review_enable_llm_planning": False, "source_review_allow_js_rendering": False,
        "source_review_max_pages_per_turn": 2,
        "web_search_agent": {
            "other_settings": {"azure_ai_foundry": {
                "agent_id": "original-agent", "endpoint": "https://private-provider.invalid",
                "api_version": "2025-05-01",
                "api_key": "PRIVATE_CONFIGURATION_KEY",
            }},
        },
    }
    context = modules.runtime.RunContext(
        user_id="owner", conversation_id="conversation-1",
        run_id=authorization_world.fixture.producer.run_id, attempt_index=1,
        plan_contract_version=2, user_message="Review https://example.com/source",
        user_roles=["User"], allowed_user_urls=["https://example.com/source"],
        planner_client=object(), planner_deployment="original-planner",
    )
    construction_client = context.planner_client
    construction_model = context.planner_deployment
    authorization_producer = authorization_world.fixture.producer
    authorization_provider = authorization_world.provider()

    def preflight(*, producer, selector=None):
        with authorization_world:
            return authorization_provider.preflight_gather_invocation(producer=producer, selector=selector)

    def prepare_authorization(step):
        """Seed current server records before invocation, never from callback arguments."""
        capability = modules.adapters.get_capability(step["capability_id"], contract_version=2)
        authorization_world.fixture.producer = replace(
            authorization_producer, step_id=step["step_id"], capability_id=step["capability_id"],
            contract_version=capability["result_contract_version"],
        )
        authorization_world.settings.update(deepcopy(settings))
        authorization_world.run["plan"]["steps"] = [deepcopy(step)]
        authorization_world.run["user_message"] = context.user_message
        authorization_world.run["memory_audience"] = {
            "kind": "personal", "owner_id": "owner", "collaboration_id": "",
        }
        for kind, catalog in (("agents", context.agent_catalog), ("actions", context.action_catalog)):
            for entry in catalog or ():
                authorization_world.services.add(
                    kind, entry["scope_type"], entry["scope_id"], dict(entry),
                )

    def capture(source_type, *, producer, settings, source=None, selector=None):
        state.calls.append("capture")
        if state.fail_capture:
            raise RuntimeError("PRIVATE_CAPTURE_FAILURE")
        if source is not None and source.get("phase") == state.fail_phase:
            return False
        if source_type == "deep_research" and (
            context.planner_client is not construction_client or context.planner_deployment != construction_model
        ):
            raise PermissionError("Planner construction attestation is unavailable.")
        state.captured.append(deepcopy(settings))
        assert selector is None
        if source_type == "web" and source is not None:
            assert source["kind"] == "foundry"
            assert source["version"] == "orchestration-external-acquisition-v1"
            assert source["binding"] == "observed-run-v1"
            assert source["definition"]["id"] == "original-agent"
        else:
            assert source is None
        state.sources.append(deepcopy(source))
        if source_type != "web" or source is not None and source.get("phase") == "run":
            revision = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
            state.private[producer] = {"identity": hashlib.sha256(source_type.encode()).hexdigest(), "revision": revision}

    state.definition = Agent({
        "id": "original-agent", "name": "Original", "model": "provider-model",
        "instructions": "Use retrieved sources to answer the question.",
        "tools": [], "tool_resources": None, "temperature": 0.2, "top_p": 1, "response_format": "auto",
    })

    class Credential:
        closed = False

        async def close(self):
            self.closed = True

    def credential(foundry_settings, global_settings):
        state.selected_settings = deepcopy(global_settings)
        assert foundry_settings == global_settings["web_search_agent"]["other_settings"]["azure_ai_foundry"]
        value = Credential()
        state.credentials.append(value)
        return value

    class Runs:
        async def create(self, *, thread_id, agent_id, **kwargs):
            state.calls.append("web")
            state.web.append(deepcopy(state.selected_settings))
            value = {
                "id": "actual-run", "thread_id": thread_id, "assistant_id": agent_id,
                "tool_resources": state.definition.as_dict().get("tool_resources"),
                **deepcopy(kwargs),
            }
            if state.run_mutation is not None:
                state.run_mutation(value)
            self.run = ThreadRun(value)
            return self.run

        async def get(self, *, thread_id, run_id):
            state.calls.append("poll")
            return self.run

    class Client:
        def __init__(self):
            self.agents = self
            self.closed = False
            self.original_runs = self.runs = Runs()

        async def get_agent(self, agent_id):
            state.calls.append("definition")
            assert agent_id == "original-agent"
            return state.definition

        async def close(self):
            self.closed = True

    class AzureAIAgent:
        def __init__(self, *, client, definition):
            self.client = client
            self.definition = definition

        @staticmethod
        def create_client(**kwargs):
            client = Client()
            state.clients.append(client)
            return client

        async def invoke(self, **kwargs):
            state.invocations.append({**kwargs, "definition": self.definition.as_dict()})
            if not state.skip_run:
                controls = {
                    key: value for key, value in self.definition.as_dict().items()
                    if key in ("model", "instructions", "tools", "temperature", "top_p", "response_format")
                }
                controls.update({
                    key: value for key, value in kwargs.items()
                    if key not in ("messages", "metadata", "thread")
                })
                await self.client.agents.runs.create(
                    thread_id="actual-thread", agent_id=self.definition.id, **controls,
                )
                if state.poll_run:
                    await self.client.agents.runs.get(thread_id="actual-thread", run_id="actual-run")
            yield SimpleNamespace(
                message=modules.foundry.ChatMessageContent(
                    role="assistant", content="Retained provider content. [Source](https://example.com/source)",
                    metadata={"configuration_revision": "MODEL_MUST_NOT_ATTEST_CONFIGURATION"},
                ),
                thread=None,
            )

    async def page_io(**kwargs):
        state.calls.append("page")
        state.pages.append(deepcopy(kwargs["source_settings"]))
        return {
            "status": "reviewed", "url": kwargs["url"], "title": "Source",
            "content_type": "text/html", "depth": 0, "text_char_count": 31,
            "excerpts": ["Full retained page evidence."], "links": [], "truncated": False,
        }

    context.external_source_preflight = preflight
    context.capture_external_source_configuration = capture
    for module in (modules.adapters, modules.web, modules.review):
        monkeypatch.setattr(module, "log_event", Mock())
    monkeypatch.setattr(modules.web, "debug_print", Mock())
    monkeypatch.setattr(modules.foundry, "AzureAIAgent", AzureAIAgent)
    monkeypatch.setattr(modules.foundry, "_build_async_credential", credential)
    monkeypatch.setattr(modules.review, "_fetch_source_page", page_io)
    return SimpleNamespace(
        modules=modules, context=context, settings=settings, state=state, capture=capture,
        authorization_context=context, authorization_world=authorization_world,
        prepare_authorization=prepare_authorization,
    )


def run_gather(runtime, capability="web_search", *, cancel_requested=None, arguments=None):
    defaults = {
        "web_search": {"query": "Current source facts"},
        "url_fetch": {"urls": ["https://example.com/source"]},
        "deep_research": {"query": "Current source facts"},
        "agent_invoke": {"agent_name": "original-agent", "task": "Gather facts"},
        "action_invoke": {"action_ref": "original-action", "task": "Gather facts"},
    }
    step = {"step_id": "gather", "capability_id": capability, "arguments": arguments or defaults[capability]}
    if runtime.context is runtime.authorization_context and runtime.context.plan_contract_version == 2:
        runtime.prepare_authorization(step)
    result = getattr(runtime.modules.adapters, f"run_{capability}")(
        step, runtime.context, settings=runtime.settings, user_id="owner",
        emit=None, cancel_requested=cancel_requested,
    )
    return step, result


@pytest.mark.parametrize("error,code", [
    (ConnectionResetError("PRIVATE_PROVIDER_TEXT"), "connection_failed"),
    (TimeoutError("PRIVATE_PROVIDER_TEXT"), "provider_timeout"),
    (RuntimeError("PRIVATE_PROVIDER_TEXT"), "provider_failed"),
])
def test_provider_failure_before_acquisition_is_classified_not_reported_as_attestation(
    capture_runtime, monkeypatch, error, code,
):
    """Version 0.261.134: a failure before any capture is still a provider failure, and transient."""
    runtime = capture_runtime
    create_client = runtime.modules.foundry.AzureAIAgent.create_client

    def failing_client(**kwargs):
        client = create_client(**kwargs)

        async def get_agent(agent_id):
            runtime.state.calls.append("definition")
            raise error

        client.get_agent = get_agent
        return client

    monkeypatch.setattr(runtime.modules.foundry.AzureAIAgent, "create_client", staticmethod(failing_client))
    schema = importlib.import_module("functions_orchestration_schema")
    _, result = run_gather(runtime, "web_search")

    assert result["status"] == "failed"
    assert result["failure"]["code"] == code
    assert "attested" not in result["summary"]
    assert schema.failure_is_transient(result["failure"]) is True
    assert "PRIVATE_PROVIDER_TEXT" not in json.dumps(result)
    assert "web" not in runtime.state.calls


@pytest.mark.parametrize("capability,source_type", [
    ("web_search", "web"), ("url_fetch", "url"),
])
def test_real_gather_captures_actual_settings_before_provider_work(capture_runtime, capability, source_type):
    runtime = capture_runtime
    step, result = run_gather(runtime, capability)
    producer = runtime.context.result_producer(step)
    assert result["status"] == "completed", result
    assert runtime.state.calls[0] == "capture"
    assert runtime.state.calls.index("capture") < runtime.state.calls.index("web" if runtime.state.web else "page")
    capture_count = 3 if capability == "web_search" else 1
    assert runtime.state.calls.count("capture") == capture_count
    assert runtime.state.captured == [runtime.settings] * capture_count
    assert runtime.state.private[producer]["identity"] == hashlib.sha256(source_type.encode()).hexdigest()
    assert len(runtime.state.private[producer]["revision"]) == 64
    assert runtime.authorization_world.identity_reads == 1
    assert runtime.authorization_world.configuration_reads == []
    assert runtime.state.web or runtime.state.pages
    assert all(client.closed for client in runtime.state.clients)
    assert all(credential.closed for credential in runtime.state.credentials)
    public = json.dumps(result)
    assert "PRIVATE_CONFIGURATION_KEY" not in public
    assert "private-provider.invalid" not in public
    assert "MODEL_MUST_NOT_ATTEST_CONFIGURATION" not in public
    assert not result["artifacts"]


@pytest.mark.parametrize("capability", ["web_search", "url_fetch"])
def test_capture_and_owner_mutation_cannot_change_pinned_execution_settings(capture_runtime, capability):
    runtime = capture_runtime
    expected = deepcopy(runtime.settings)

    def mutate_after_capture(source_type, **kwargs):
        runtime.capture(source_type, **kwargs)
        kwargs["settings"]["web_search_agent"]["other_settings"]["azure_ai_foundry"]["agent_id"] = "callback-mutation"
        kwargs["settings"]["source_review_max_pages_per_turn"] = 99
        runtime.settings["web_search_agent"]["other_settings"]["azure_ai_foundry"]["agent_id"] = "owner-mutation"
        runtime.settings["source_review_max_pages_per_turn"] = 99

    runtime.context.capture_external_source_configuration = mutate_after_capture
    _, result = run_gather(runtime, capability)
    assert result["status"] == "completed", result
    assert runtime.state.captured == [expected] * (3 if capability == "web_search" else 1)
    assert all(settings == expected for settings in runtime.state.web)
    assert all(settings["source_review_max_pages_per_turn"] == 2 for settings in runtime.state.pages)


@pytest.mark.parametrize("capability", ["web_search", "url_fetch", "deep_research"])
@pytest.mark.parametrize("failure", ["missing", "refused", "exception"])
def test_capture_failure_prevents_all_provider_work(capture_runtime, capability, failure):
    runtime = capture_runtime
    if failure == "missing":
        del runtime.context.capture_external_source_configuration
    elif failure == "refused":
        runtime.context.capture_external_source_configuration = lambda *args, **kwargs: False
    else:
        runtime.state.fail_capture = True
    _, result = run_gather(runtime, capability)
    assert result["status"] == "failed"
    assert not runtime.state.web and not runtime.state.pages and not runtime.state.private
    assert "PRIVATE_CAPTURE_FAILURE" not in json.dumps(result)
    assert "PRIVATE_CAPTURE_FAILURE" not in repr(runtime.modules.adapters.log_event.call_args_list)
    assert all(
        not call.kwargs.get("exceptionTraceback")
        for call in runtime.modules.adapters.log_event.call_args_list
    )


@pytest.mark.parametrize("capability,phase", [
    ("web_search", None), ("url_fetch", None), ("deep_research", None),
    ("web_search", "definition"), ("web_search", "run"),
])
@pytest.mark.parametrize("owner,cancelled", [
    ("identity", False), ("identity", True), ("configuration", False), ("configuration", True),
])
def test_authority_failures_keep_operational_and_cancellation_meaning(capture_runtime, capability, phase, owner, cancelled):
    runtime = capture_runtime
    errors = importlib.import_module(f"functions_orchestration_external_{owner}")
    prefix = "ExternalIdentity" if owner == "identity" else "ExternalConfiguration"
    error_type = getattr(errors, prefix + ("CancelledError" if cancelled else "ServiceError"))
    code = f"external_{owner}_timeout"
    failure = error_type() if cancelled else error_type(code)
    failure.private_detail = "PRIVATE_AUTHORITY_FAILURE"

    def capture(source_type, **kwargs):
        if (kwargs["source"] or {}).get("phase") == phase:
            raise failure
        return runtime.capture(source_type, **kwargs)

    runtime.context.capture_external_source_configuration = capture
    if cancelled:
        _, result = run_gather(runtime, capability)
        assert result["status"] == "cancelled"
        assert not result["artifacts"]
        assert "PRIVATE_" not in json.dumps(result)
    else:
        with pytest.raises(error_type) as caught:
            run_gather(runtime, capability)
        assert caught.value.code == code and caught.value.retryable
        assert caught.value is not failure
        assert not hasattr(caught.value, "private_detail")
    if phase is None:
        assert runtime.state.web == runtime.state.pages == runtime.state.invocations == []
    assert runtime.state.private == {}
    assert all(client.closed for client in runtime.state.clients)
    assert all(credential.closed for credential in runtime.state.credentials)


@pytest.mark.parametrize("field,value", [
    ("user_id", "another-user"), ("conversation_id", "another-conversation"), ("run_id", "another-run"),
    ("attempt_index", 2), ("step_id", "another-step"), ("capability_id", "url_fetch"),
    ("contract_version", "untrusted-contract"),
])
def test_every_producer_identity_field_is_checked_before_capture(capture_runtime, field, value):
    runtime = capture_runtime
    original = runtime.context.result_producer
    runtime.context.result_producer = lambda step: replace(original(step), **{field: value})
    _, result = run_gather(runtime)
    assert result["status"] == "failed"
    assert runtime.state.calls == []


@pytest.mark.parametrize("fault", [
    "noncallable_capture", "no_producer_factory", "untyped_producer",
    "nonmapping_settings", "boolean_attempt", "float_attempt",
])
def test_invalid_server_capture_bindings_fail_closed(capture_runtime, fault):
    runtime = capture_runtime
    original = runtime.context.result_producer
    if fault == "noncallable_capture":
        runtime.context.capture_external_source_configuration = True
    elif fault == "no_producer_factory":
        runtime.context.result_producer = None
    elif fault == "untyped_producer":
        runtime.context.result_producer = lambda step: original(step).to_dict()
    elif fault == "nonmapping_settings":
        runtime.settings = None
    else:
        runtime.context.attempt_index = True if fault == "boolean_attempt" else 1.0
    _, result = run_gather(runtime)
    assert result["status"] == "failed"
    assert runtime.state.calls == []


def test_callback_result_is_private_and_not_part_of_the_step_result(capture_runtime):
    runtime = capture_runtime

    def capture_with_private_result(source_type, **kwargs):
        runtime.capture(source_type, **kwargs)
        return {"identity": "PRIVATE_CAPTURE_IDENTITY", "revision": "PRIVATE_CAPTURE_REVISION"}

    runtime.context.capture_external_source_configuration = capture_with_private_result
    _, result = run_gather(runtime)
    assert result["status"] == "completed", result
    assert "PRIVATE_CAPTURE_" not in json.dumps(result)


def test_foundry_capture_pins_actual_definition_and_ignores_later_mutation(capture_runtime):
    runtime = capture_runtime
    original = runtime.state.definition.as_dict()

    def mutate_source(source_type, **kwargs):
        runtime.capture(source_type, **kwargs)
        if kwargs["source"] is not None:
            kwargs["source"]["definition"]["model"] = "callback-replacement"
            runtime.state.definition["model"] = "remote-replacement"
            runtime.state.definition["instructions"] = "Changed remote instructions."

    runtime.context.capture_external_source_configuration = mutate_source
    _, result = run_gather(runtime)
    assert result["status"] == "completed", result
    invocation = runtime.state.invocations[0]
    assert invocation["definition"]["model"] == original["model"]
    assert invocation["definition"]["instructions"] == original["instructions"]
    for key in ("model", "instructions", "temperature", "top_p", "response_format"):
        assert invocation[key] == original[key]
    assert runtime.state.sources[1]["definition"]["model"] == original["model"]
    assert runtime.state.calls == ["capture", "definition", "capture", "web", "capture"]
    assert runtime.state.sources[-1]["run"]["agent_id"] == "original-agent"
    assert "assistant_id" not in runtime.state.sources[-1]["run"]


def test_actual_sdk_builds_run_options_from_captured_definition(capture_runtime):
    runtime = capture_runtime
    _, result = run_gather(runtime)
    assert result["status"] == "completed", result
    invocation = runtime.state.invocations[0]
    captured = runtime.state.sources[1]["definition"]
    credential = runtime.state.credentials[0]
    client = SdkAzureAIAgent.create_client(
        credential=credential, endpoint="https://private-provider.invalid", api_version="2025-05-01",
    )
    try:
        agent = SdkAzureAIAgent(client=client, definition=Agent(invocation["definition"]))
        options = AgentThreadActions._generate_options(
            agent=agent,
            **{key: invocation[key] for key in ("model", "temperature", "top_p", "response_format")},
        )
        tools = AgentThreadActions._get_tools(agent=agent, kernel=agent.kernel)
        assert agent.instructions == captured["instructions"]
        assert tools == captured["tools"]
        for key in ("model", "temperature", "top_p", "response_format"):
            assert options[key] == captured[key]
    finally:
        asyncio.run(client.close())


@pytest.mark.parametrize("field", [
    "model", "instructions", "tools", "tool_resources", "temperature", "top_p",
    "response_format", "id", "thread_id", "assistant_id",
])
def test_incomplete_actual_run_cannot_complete_capture(capture_runtime, field):
    runtime = capture_runtime
    runtime.state.run_mutation = lambda value: value.pop(field, None)
    with pytest.raises(PermissionError) as denied:
        run_gather(runtime)
    assert denied.value.code == "result_unavailable" and denied.value.retryable is False
    assert runtime.state.private == {}
    assert len(runtime.state.web) == 1
    assert all(client.runs is client.original_runs and client.closed for client in runtime.state.clients)
    assert all(credential.closed for credential in runtime.state.credentials)


@pytest.mark.parametrize("field,value", [
    ("model", "replaced-model"), ("instructions", "Replaced instructions."),
    ("tools", [{"type": "file_search"}]), ("tool_resources", {"file_search": {}}),
    ("temperature", 0.8), ("top_p", 0.5), ("response_format", "json_object"),
    ("assistant_id", "another-agent"), ("thread_id", "another-thread"),
])
def test_changed_actual_run_never_becomes_execution_proof(capture_runtime, field, value):
    runtime = capture_runtime
    runtime.state.run_mutation = lambda observed: observed.update({field: value})
    _, result = run_gather(runtime)
    assert result["status"] == "failed"
    assert runtime.state.private == {}
    assert not result["artifacts"]
    assert all(client.runs is client.original_runs and client.closed for client in runtime.state.clients)


@pytest.mark.parametrize("fault", ["definition_only", "refused_definition", "refused_run"])
def test_foundry_requires_successful_actual_run_capture(capture_runtime, fault):
    runtime = capture_runtime
    if fault == "definition_only":
        runtime.state.skip_run = True
    else:
        runtime.state.fail_phase = "definition" if fault == "refused_definition" else "run"
    _, result = run_gather(runtime)
    assert result["status"] == "failed"
    assert runtime.state.private == {}
    assert len(runtime.state.web) == (1 if fault == "refused_run" else 0)
    assert all(client.runs is client.original_runs and client.closed for client in runtime.state.clients)


def test_existing_poll_observes_same_run_without_extra_provider_work(capture_runtime):
    runtime = capture_runtime
    runtime.state.poll_run = True
    _, result = run_gather(runtime)
    assert result["status"] == "completed", result
    assert runtime.state.calls == ["capture", "definition", "capture", "web", "capture", "poll", "capture"]
    assert runtime.state.sources[-1] == runtime.state.sources[-2]
    assert all(client.runs is client.original_runs for client in runtime.state.clients)


def _private_digest(value):
    return hmac.new(b"synthetic-owned-invocation-test-key", value, hashlib.sha256).hexdigest()


def _current_web_configuration(runtime):
    configuration = runtime.modules.configuration
    settings = deepcopy(runtime.settings["web_search_agent"]["other_settings"]["azure_ai_foundry"])
    definition = configuration.foundry_definition_snapshot(runtime.state.definition)
    return {
        "version": configuration.EXTERNAL_ACQUISITION_VERSION,
        "kind": "foundry", "phase": "current", "binding": configuration.FOUNDRY_OBSERVED_RUN,
        "endpoint": settings["endpoint"], "api_version": settings["api_version"],
        "foundry_settings": settings, "definition": definition,
        "overrides": {
            key: definition[key]
            for key in ("model", "instructions", "temperature", "top_p", "response_format")
        },
    }


def _web_attestor(runtime):
    return runtime.modules.configuration.OrchestrationExternalConfigurationAttestor(
        user_id="owner", conversation_id="conversation-1", private_digest=_private_digest,
        read_current_source=lambda *_args, **_kwargs: _current_web_configuration(runtime),
    )


def test_real_capture_admission_retention_and_restart_do_not_depend_on_capture_map(capture_runtime):
    runtime = capture_runtime
    # These are the shared storage/authority I/O doubles; all facades and readers are real.
    world_type = importlib.import_module("test_orchestration_external_sources").ExternalSourceWorld
    unavailable = runtime.modules.configuration.ResultUnavailableError
    with world_type() as world:
        runtime.context.run_id = world.fixture.producer.run_id
        attestor = _web_attestor(runtime)
        phases = []

        def capture(source_type, **kwargs):
            attestor.capture(source_type, **kwargs)
            source = kwargs.get("source")
            phases.append(source.get("phase") if source is not None else None)
            if source is None or source["phase"] == "definition":
                with pytest.raises(unavailable) as denied:
                    attestor.for_admission(
                        source_type, producer=kwargs["producer"], settings=kwargs["settings"],
                        source=None, selector=None,
                    )
                assert denied.value.code == "external_configuration_capture_required"

        runtime.context.capture_external_source_configuration = capture
        step, result = run_gather(runtime)
        assert result["status"] == "completed", result
        assert phases == [None, "definition", "run"]
        world.fixture.producer = runtime.context.result_producer(step)
        world.run = world.fixture.runs[world.fixture.producer.run_id]
        world.run["plan"]["planner_contract_version"] = 2
        world.settings.update(deepcopy(runtime.settings))
        world.prepared["notes"] = result["notes"]
        world.prepared["citations"] = result["citations"]
        provider = world.provider(
            read_configuration=attestor.current, configuration_admitter=attestor.for_admission,
        )
        catalog = world.admit(provider)
        service = world.service(provider, catalog)
        task = world.persist(service, catalog)
        reference = task.output("prepared")
        before = service.open_result(reference).read_value()

        restarted = _web_attestor(runtime)
        reader = world.provider(read_configuration=restarted.current, configuration_admitter=None)
        restored = world.service(reader).open_result(reference).read_value()
        assert before == restored
        assert "Retained provider content." in "\n".join(restored["notes"])
        assert len(runtime.state.web) == 1
        assert not result["artifacts"]
        public = json.dumps(reference.to_dict())
        assert "PRIVATE_CONFIGURATION_KEY" not in public
        assert "private-provider.invalid" not in public
        assert "original-agent" not in public
        runtime.state.definition["instructions"] = "Changed current remote definition."
        with pytest.raises(unavailable):
            world.service(reader).open_result(reference)
        assert len(runtime.state.web) == 1


def test_real_sk_observes_sdk_runs_and_cleans_owned_thread(capture_runtime, monkeypatch):
    runtime = capture_runtime
    attestor = _web_attestor(runtime)
    runtime.context.capture_external_source_configuration = attestor.capture
    calls = []
    clients = []
    create_client = SdkAzureAIAgent.create_client

    def client_factory(**kwargs):
        client = create_client(**kwargs)
        operations = client.agents
        original_runs = operations.runs
        clients.append((client, operations, original_runs))

        async def get_agent(agent_id):
            calls.append("definition")
            return runtime.state.definition

        async def create_thread(**_kwargs):
            calls.append("thread")
            return AgentThread({"id": "actual-thread"})

        async def create_message(**_kwargs):
            calls.append("message")
            return ThreadMessage({"id": "input-message", "thread_id": "actual-thread", "role": "user", "content": []})

        async def create_run(**kwargs):
            calls.append("create-run")
            return ThreadRun({
                "id": "actual-run", "thread_id": kwargs["thread_id"], "assistant_id": kwargs["agent_id"],
                "status": "queued", "tool_resources": None,
                **{key: value for key, value in kwargs.items() if key not in ("thread_id", "agent_id", "metadata")},
            })

        async def get_run(*_args, **_kwargs):
            calls.append("get-run")
            return ThreadRun({
                **{key: value for key, value in runtime.state.definition.as_dict().items() if key not in ("id", "name")},
                "id": "actual-run", "thread_id": "actual-thread", "assistant_id": "original-agent",
                "status": "completed",
            })

        async def list_steps(**_kwargs):
            calls.append("steps")
            yield RunStep({
                "id": "message-step", "type": "message_creation", "completed_at": 1700000000,
                "step_details": {"type": "message_creation", "message_creation": {"message_id": "output-message"}},
            })

        async def get_message(**_kwargs):
            calls.append("get-message")
            return ThreadMessage({
                "id": "output-message", "thread_id": "actual-thread", "run_id": "actual-run", "role": "assistant",
                "content": [{"type": "text", "text": {"value": "Actual SDK retained final line.", "annotations": []}}],
            })

        async def delete_thread(*_args, **_kwargs):
            calls.append("delete-thread")

        monkeypatch.setattr(operations, "get_agent", get_agent)
        monkeypatch.setattr(operations.threads, "create", create_thread)
        monkeypatch.setattr(operations.threads, "delete", delete_thread)
        monkeypatch.setattr(operations.messages, "create", create_message)
        monkeypatch.setattr(operations.messages, "get", get_message)
        monkeypatch.setattr(original_runs, "create", create_run)
        monkeypatch.setattr(original_runs, "get", get_run)
        monkeypatch.setattr(operations.run_steps, "list", list_steps)
        return client

    monkeypatch.setattr(runtime.modules.foundry, "AzureAIAgent", SdkAzureAIAgent)
    monkeypatch.setattr(SdkAzureAIAgent, "create_client", client_factory)
    step, result = run_gather(runtime)
    assert result["status"] == "completed", result
    assert calls == [
        "definition", "thread", "message", "create-run", "get-run", "steps", "get-message", "delete-thread",
    ]
    assert all(client.agents is operations and operations.runs is original for client, operations, original in clients)
    proof = attestor.for_admission(
        "web", producer=runtime.context.result_producer(step), settings=runtime.settings, source=None, selector=None,
    )
    current = attestor.current(
        "web", producer=runtime.context.result_producer(step), settings=runtime.settings, source=None,
    )
    assert proof == current
    assert "Actual SDK retained final line." in "\n".join(result["notes"])


def test_real_action_configuration_captures_prepared_origin_and_constructed_model(capture_runtime, monkeypatch):
    runtime = capture_runtime
    actions = importlib.import_module("functions_orchestration_actions")
    manifests = importlib.import_module("functions_action_manifest")
    catalog = importlib.import_module("functions_action_catalog")
    contexts = importlib.import_module("agent_execution_context")
    loader_module = importlib.import_module("semantic_kernel_plugins.logged_plugin_loader")
    settings_module = importlib.import_module("functions_settings")
    kernel_loader = importlib.import_module("semantic_kernel_loader")
    policy = importlib.import_module("functions_orchestration_execution_policy")
    configuration = runtime.modules.configuration
    runtime.settings.update({
        "enable_chat_orchestration": True, "enable_chat_orchestration_actions": True,
        "azure_openai_gpt_endpoint": "https://model.invalid", "azure_openai_gpt_api_version": "2024-10-21",
        "azure_openai_gpt_authentication_type": "key", "azure_openai_gpt_key": "SYNTHETIC_PRIVATE_MODEL_KEY",
        "gpt_model": {"selected": [{"deploymentName": "gpt-4o"}]},
    })
    selector = catalog._action_ref("personal", "owner", "lookup")
    manifest = manifests.ScopedActionManifest({
        "id": "lookup", "name": "lookup", "type": "openapi", "action_ref": selector,
        "scope_type": "personal", "scope_id": "owner", "enabled_functions": ["lookup"],
        "auth": {"type": "api_key", "api_key": "SYNTHETIC_PRIVATE_ACTION_KEY"},
    }, manifests.McpActionOrigin("personal", "owner", "lookup"))
    runtime.context.action_catalog = [deepcopy(manifest)]
    runtime.context.agent_execution_identity = contexts.ExecutionIdentity(
        "owner", "conversation-1", bridge=lambda _reference: nullcontext(),
    )
    runtime.context.delegation_budget = contexts.DelegationBudget()
    calls = []
    models = []
    captures = []
    loaded = []

    class Lookup:
        @kernel_function(description="Read retained test rows.")
        def lookup(self) -> str:
            calls.append("tool")
            return "First retained row\nFinal retained row 1000"

    class Loader:
        def __init__(self, kernel):
            self.kernel = kernel
            self.plugin_instances = []

        def load_plugin_from_manifest(self, prepared, user_id):
            calls.append("load")
            loaded.append(prepared)
            self.kernel.add_plugin(Lookup(), plugin_name="lookup")
            return True

    async def reply(service, history, execution):
        calls.append("model")
        models.append(service)
        if len(models) == 1:
            return [ChatMessageContent(role=AuthorRole.ASSISTANT, items=[
                FunctionCallContent(id="lookup-call", name="lookup-lookup", arguments="{}"),
            ])]
        return [ChatMessageContent(role=AuthorRole.ASSISTANT, content="First retained row\nFinal retained row 1000")]

    def metadata(_source_type, *, producer, settings, source, selector):
        return {
            "version": configuration.EXTERNAL_ACQUISITION_VERSION, "kind": "action", "phase": "current",
            "reference": {"id": "lookup", "scope_type": "personal", "scope_id": "owner"},
            "manifest": deepcopy(manifest),
            "prepared_manifest": kernel_loader.prepare_action_plugin_manifest(manifest, settings),
            "model": {
                "provider": "aoai", "protocol": "azure_openai",
                "endpoint": settings["azure_openai_gpt_endpoint"], "api_version": settings["azure_openai_gpt_api_version"],
                "deployment": "gpt-4o", "endpoint_id": None, "model_id": None,
                "parameters": {"parallel_tool_calls": False, "tool_choice": "auto"},
            },
        }

    attestor = configuration.OrchestrationExternalConfigurationAttestor(
        user_id="owner", conversation_id="conversation-1", read_current_source=metadata, private_digest=_private_digest,
    )

    def capture(source_type, **kwargs):
        if kwargs["source"] is None:
            calls.append("preflight")
            return
        calls.append("capture")
        captures.append(deepcopy(kwargs))
        attestor.capture(source_type, **kwargs)

    runtime.context.capture_external_source_configuration = capture
    monkeypatch.setattr(actions, "resolve_action_manifest", lambda *_args, **_kwargs: deepcopy(manifest))
    monkeypatch.setattr(settings_module, "get_settings", lambda: deepcopy(runtime.settings))
    monkeypatch.setattr(loader_module, "create_logged_plugin_loader", Loader)
    monkeypatch.setattr(AzureChatCompletion, "_inner_get_chat_message_contents", reply)
    with policy.orchestration_file_policy(allow_generated_files=False):
        step, result = run_gather(runtime, "action_invoke", arguments={"action_ref": selector, "task": "Read all rows."})
    assert result["status"] == "completed", result
    assert calls == ["preflight", "preflight", "capture", "load", "model", "capture", "tool", "model"]
    assert len(captures) == 2
    assert captures[0]["source"] == captures[1]["source"]
    assert captures[0]["source"]["prepared_manifest"] == loaded[0]
    origin = manifests.get_action_origin(captures[0]["source"]["manifest"])
    assert origin == manifests.McpActionOrigin("personal", "owner", "lookup")
    assert captures[0]["source"]["model"]["deployment"] == models[0].ai_model_id
    assert models[0].client.is_closed()
    assert "Final retained row 1000" in "\n".join(result["notes"])
    assert not result["artifacts"]
    assert "SYNTHETIC_PRIVATE" not in json.dumps(result)
    producer = runtime.context.result_producer(step)
    proof = attestor.for_admission(
        "action", producer=producer, settings=runtime.settings, source=manifest, selector=selector,
    )
    restarted = configuration.OrchestrationExternalConfigurationAttestor(
        user_id="owner", conversation_id="conversation-1", read_current_source=metadata, private_digest=_private_digest,
    )
    current = restarted.current("action", producer=producer, settings=runtime.settings, source=manifest)
    assert proof == current


@pytest.mark.parametrize("field,value", [
    ("id", "another-agent"), ("model", None), ("instructions", None),
    ("instructions", "Unbound {{variable}}"), ("tools", None),
    ("tools", [{"type": "file_search"}]), ("tools", [{"type": "function"}]),
    ("tool_resources", {"file_search": {"vector_store_ids": ["mutable-store"]}}),
    ("temperature", None), ("temperature", True), ("top_p", None),
    ("response_format", None),
])
def test_foundry_unpinned_definitions_never_start_a_run(capture_runtime, field, value):
    runtime = capture_runtime
    definition = runtime.state.definition.as_dict()
    definition[field] = value
    runtime.state.definition = Agent(definition)
    if (field, value) in (("model", None), ("tools", None), ("temperature", True)):
        with pytest.raises(runtime.modules.configuration.ExternalConfigurationServiceError) as invalid:
            run_gather(runtime)
        assert invalid.value.code == "external_configuration_metadata_invalid"
        assert invalid.value.retryable is False
    elif field in ("tools", "tool_resources"):
        with pytest.raises(PermissionError) as refused:
            run_gather(runtime)
        assert refused.value.code == "result_unavailable"
        assert refused.value.retryable is False
    else:
        _, result = run_gather(runtime)
        assert result["status"] == "failed"
    assert runtime.state.calls == ["capture", "definition"]
    assert runtime.state.invocations == []
    assert runtime.state.private == {}
    assert all(client.closed for client in runtime.state.clients)
    assert all(credential.closed for credential in runtime.state.credentials)


@pytest.mark.parametrize("entrypoint,streaming", [
    ("execute_new_foundry_agent", False), ("execute_new_foundry_agent_stream", True),
    ("execute_foundry_workflow_agent", False), ("execute_foundry_workflow_agent_stream", True),
])
def test_remote_protocol_without_definition_proof_refuses_before_io(capture_runtime, entrypoint, streaming):
    runtime = capture_runtime
    captures = importlib.import_module("functions_orchestration_invocation_capture")
    callback = Mock()
    state = captures.OrchestrationInvocationCapture(callback)
    kwargs = {
        "global_settings": runtime.settings, "message_history": [], "metadata": {},
        "invocation_capture": state,
        "workflow_settings" if "workflow" in entrypoint else "foundry_settings": {},
    }

    async def invoke():
        result = getattr(runtime.modules.foundry, entrypoint)(**kwargs)
        if streaming:
            async for _ in result:
                pytest.fail("An unverified remote stream must not produce content.")
        else:
            await result

    with pytest.raises(captures.OrchestrationInvocationCaptureError):
        asyncio.run(invoke())
    assert runtime.state.clients == []
    assert runtime.state.credentials == []
    callback.assert_not_called()


@pytest.mark.parametrize("fault", ["no_client", "no_model", "replaced_client", "replaced_model"])
def test_research_requires_actual_bound_planner_configuration(capture_runtime, fault):
    runtime = capture_runtime
    if fault == "no_client":
        runtime.context.planner_client = None
    elif fault == "no_model":
        runtime.context.planner_deployment = ""
    elif fault == "replaced_client":
        runtime.context.planner_client = object()
    else:
        runtime.context.planner_deployment = "different-planner"
    if fault in ("replaced_client", "replaced_model"):
        with pytest.raises(PermissionError) as denied:
            run_gather(runtime, "deep_research")
        assert denied.value.code == "result_unavailable" and denied.value.retryable is False
    else:
        _, result = run_gather(runtime, "deep_research")
        assert result["status"] == "failed"
    assert not runtime.state.web and not runtime.state.pages and not runtime.state.private


def test_research_preparation_cannot_replace_missing_planner_construction_proof(capture_runtime):
    runtime = capture_runtime
    runtime.context.capture_external_source_configuration = _web_attestor(runtime).capture
    _, result = run_gather(runtime, "deep_research")
    assert result["status"] == "failed"
    assert runtime.state.web == [] and runtime.state.pages == []
    assert runtime.state.clients == [] and runtime.state.credentials == []


@pytest.mark.parametrize("field,value", [("planner_client", None), ("planner_deployment", "replacement-model")])
def test_research_refuses_binding_replacement_during_capture(capture_runtime, field, value):
    runtime = capture_runtime

    def replace_after_capture(source_type, **kwargs):
        runtime.capture(source_type, **kwargs)
        setattr(runtime.context, field, value)

    runtime.context.capture_external_source_configuration = replace_after_capture
    _, result = run_gather(runtime, "deep_research")
    assert result["status"] == "failed"
    assert runtime.state.calls == ["capture"]
    assert not runtime.state.web and not runtime.state.pages


def test_research_does_not_rediscover_planner_after_capture(capture_runtime, monkeypatch):
    runtime = capture_runtime
    resolve = Mock(side_effect=AssertionError("A captured planner must not be resolved again."))
    monkeypatch.setattr(runtime.modules.adapters, "_resolve_source_review_planner", resolve)
    _, result = run_gather(runtime, "deep_research")
    assert result["status"] == "failed"
    resolve.assert_not_called()
    assert runtime.state.web == [] and runtime.state.pages == []


@pytest.mark.parametrize("capability", ["agent_invoke", "action_invoke"])
def test_freshly_resolved_engines_are_not_attested_from_catalog_candidates(capture_runtime, monkeypatch, capability):
    runtime = capture_runtime
    runtime.settings["allow_user_agents"] = True
    contexts = importlib.import_module("agent_execution_context")
    catalog = importlib.import_module("functions_action_catalog")
    selector = catalog._action_ref("personal", "owner", "original-action-id")
    engine_name = "agent_delegation_runtime" if capability == "agent_invoke" else "functions_orchestration_actions"
    engine = importlib.import_module(engine_name)

    async def unobserved_engine(*args, **kwargs):
        return {"findings": "Unattested output", "calls": 1, "root_id": "root", "invocations": [], "artifacts": []}

    preparations = []

    def prepare(source_type, *, producer, settings, source=None, selector=None):
        assert source is None
        preparations.append((source_type, selector))

    invocation = Mock(side_effect=unobserved_engine)
    monkeypatch.setattr(engine, "invoke_scoped_agent" if capability == "agent_invoke" else "invoke_action", invocation)
    runtime.context.agent_catalog = [{
        "id": "original-agent-id", "name": "original-agent",
        "scope_type": "personal", "scope_id": "owner", "catalog_key": "personal:owner:original-agent-id",
    }]
    runtime.context.action_catalog = [{
        "action_ref": selector, "id": "original-action-id", "name": "original-action",
        "type": "openapi", "scope_type": "personal", "scope_id": "owner", "is_enabled": True,
    }]
    runtime.context.agent_execution_identity = contexts.ExecutionIdentity(
        "owner", "conversation-1", bridge=lambda _reference: nullcontext(),
    )
    runtime.context.capture_external_source_configuration = prepare
    arguments = {"action_ref": selector, "task": "Gather facts"} if capability == "action_invoke" else None
    _, result = run_gather(runtime, capability, arguments=arguments)
    assert result["status"] == "failed"
    assert result["notes"] == result["artifacts"] == []
    assert runtime.state.calls == []
    expected = (
        ("agent", "personal:owner:original-agent-id") if capability == "agent_invoke"
        else ("action", selector)
    )
    assert preparations == [expected]
    invocation.assert_called_once()


@pytest.mark.parametrize("capability", ["web_search", "url_fetch", "deep_research"])
def test_v1_gather_does_not_require_or_call_capture(capture_runtime, capability):
    runtime = capture_runtime
    runtime.context.plan_contract_version = 1
    callback = Mock(side_effect=AssertionError("Legacy execution must not capture v2 configuration."))
    runtime.context.capture_external_source_configuration = callback
    runtime.context.external_source_preflight = callback
    _, result = run_gather(runtime, capability)
    assert result["status"] == "completed", result
    callback.assert_not_called()
    assert runtime.state.web or runtime.state.pages


@pytest.mark.parametrize("capability", ["web_search", "url_fetch", "deep_research", "agent_invoke", "action_invoke"])
def test_cancellation_never_captures_or_invokes(capture_runtime, capability):
    _, result = run_gather(capture_runtime, capability, cancel_requested=lambda: True)
    assert result["status"] == "cancelled"
    assert capture_runtime.state.calls == []


def test_unapproved_url_does_not_create_an_acquisition_binding(capture_runtime):
    _, result = run_gather(
        capture_runtime, "url_fetch", arguments={"urls": ["https://unapproved.invalid/source"]},
    )
    assert result["status"] == "completed", result
    assert not result["notes"] and not result["citations"]
    assert capture_runtime.state.calls == []
    assert capture_runtime.state.private == {}
