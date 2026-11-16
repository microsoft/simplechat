# test_orchestration_external_metadata.py
"""
Functional tests for independent current external-source metadata reconstruction.
Version: 0.261.134
Implemented in: 0.261.127
Per-step Auto bindings rebuilt from the producing step's binding since: 0.261.134

Real application resolvers, manifest preparation, SDK metadata deserialization
and configuration projections run with storage/HTTP I/O doubled. No source
content, model, tool, Graph request or live credential is accessed. Refs #1509.
"""

import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import hmac
import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from azure.ai.agents import AgentsClient
from azure.ai.agents.models import Agent, ThreadRun
from azure.core.credentials import AccessToken
from azure.core.exceptions import ClientAuthenticationError, DecodeError, ServiceRequestError
from azure.core.pipeline.transport import HttpResponse, HttpTransport
import pytest

from test_orchestration_external_configuration_capture import gather_modules
from test_orchestration_result_imports import APP_PROBE, EARLY_PROBE, run_probe
from test_support.offline_bootstrap import OfflineContainer


def private_digest(value):
    return hmac.new(b"synthetic-metadata-reader-test-key", value, hashlib.sha256).hexdigest()


class MetadataResponse(HttpResponse):
    def __init__(self, request, payload, status=200):
        super().__init__(request, None)
        self.status_code = status
        self.headers = {"content-type": "application/json"}
        self.reason = "OK" if status == 200 else "Metadata error"
        self.content_type = "application/json"
        self._body = json.dumps(payload).encode("utf-8")

    def body(self):
        return self._body

    def json(self):
        return json.loads(self._body)

    def stream_download(self, pipeline, **kwargs):
        yield self._body


class MetadataTransport(HttpTransport):
    def __init__(self, state):
        self.state = state
        self.closed = False

    def open(self):
        return None

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def send(self, request, **kwargs):
        self.state.requests.append((request.method, request.url, deepcopy(kwargs)))
        if self.state.failure is not None:
            raise self.state.failure
        if self.state.revoke_after_get:
            self.state.conversation["user_id"] = "another-owner"
        payload = self.state.definition.as_dict()
        if self.state.status != 200:
            payload = {"error": {"code": "synthetic", "message": "PRIVATE_PROVIDER_ERROR"}}
        return MetadataResponse(request, payload, self.state.status)


class MetadataCredential:
    def __init__(self, state, options):
        self.state = state
        self.options = options
        self.closed = False

    def get_token(self, *scopes, **_kwargs):
        self.state.tokens.append(scopes)
        return AccessToken("synthetic-test-access-token", 4102444800)

    def close(self):
        self.closed = True


class RecordedContainer(OfflineContainer):
    def __init__(self, items):
        super().__init__()
        self.items = deepcopy(items)
        self.reads = []
        self.failure = None

    def read_item(self, item, partition_key, **kwargs):
        self.reads.append((item, partition_key))
        if self.failure is not None:
            raise self.failure
        return super().read_item(item, partition_key, **kwargs)


@pytest.fixture
def metadata_world(gather_modules, monkeypatch):
    modules = SimpleNamespace(
        metadata=importlib.import_module("functions_orchestration_external_metadata"),
        configuration=gather_modules.configuration,
        contracts=importlib.import_module("functions_orchestration_result_contracts"),
        runs=importlib.import_module("functions_orchestration_runs"),
        settings=importlib.import_module("functions_settings"),
        actions=importlib.import_module("functions_orchestration_actions"),
        catalog=importlib.import_module("functions_action_catalog"),
        agents=importlib.import_module("functions_agent_delegation"),
        loader=importlib.import_module("semantic_kernel_loader"),
        models=importlib.import_module("functions_orchestration_models"),
        config=importlib.import_module("config"),
        foundry=gather_modules.foundry,
    )
    settings = {
        "enable_semantic_kernel": True, "allow_user_plugins": True, "allow_user_agents": True,
        "enable_user_workspace": True, "enable_chat_orchestration": True,
        "enable_chat_orchestration_actions": True, "enable_web_search": True,
        "enable_gpt_apim": False, "enable_multi_model_endpoints": False,
        "azure_openai_gpt_endpoint": "https://metadata-model.openai.azure.com",
        "azure_openai_gpt_api_version": "2024-12-01-preview",
        "azure_openai_gpt_authentication_type": "key",
        "azure_openai_gpt_key": "synthetic-model-key",
        "gpt_model": {"selected": [{
            "deploymentName": "gpt-4o", "modelName": "gpt-4o", "responseLength": 2048,
        }]},
        "web_search_agent": {"other_settings": {"azure_ai_foundry": {
            "agent_id": "remote-agent", "endpoint": "https://metadata.services.ai.azure.com/api/projects/project",
            "api_version": "2025-05-01", "authentication_type": "managed_identity",
            "managed_identity_type": "system_assigned",
        }}},
    }
    definition = Agent({
        "id": "remote-agent", "model": "gpt-4o", "instructions": "Use the configured sources.",
        "tools": [{"type": "bing_grounding", "bing_grounding": {
            "search_configurations": [{"connection_id": "bing-connection"}],
        }}],
        "tool_resources": None, "response_format": "auto", "temperature": 0.2, "top_p": 1,
    })
    state = SimpleNamespace(
        modules=modules, settings=settings, definition=definition, requests=[], tokens=[],
        credentials=[], clients=[], transports=[], status=200, failure=None, revoke_after_get=False,
        conversation={"id": "conversation", "user_id": "owner"}, ownership_reads=[],
    )
    run = {
        "id": "run", "user_id": "owner", "conversation_id": "conversation", "attempt_index": 1,
        "plan": {"planner_contract_version": 2},
        "seeds": {"model": {"model_deployment": "gpt-4o", "model_provider": "aoai"}},
    }
    state.run_store = RecordedContainer({"run": run})
    monkeypatch.setattr(modules.runs, "cosmos_orchestration_runs_container", state.run_store)
    action = {
        "id": "action-one", "user_id": "owner", "name": "Lookup", "type": "openapi", "is_enabled": True,
        "endpoint": "https://action.invalid", "auth": {"type": "none"},
        "additionalFields": {"openapi_spec_content": json.dumps({
            "openapi": "3.0.0", "info": {"title": "Lookup", "version": "1"},
            "paths": {"/lookup": {"get": {"operationId": "lookup", "responses": {"200": {"description": "OK"}}}}},
        })},
    }
    state.action_store = RecordedContainer({"action-one": action})
    monkeypatch.setattr(modules.config, "cosmos_personal_actions_container", state.action_store)
    agent = {
        "id": "agent-one", "user_id": "owner", "name": "Research", "agent_type": "aifoundry",
        "other_settings": deepcopy(settings["web_search_agent"]["other_settings"]),
        "max_completion_tokens": 3072,
    }
    state.agent_store = RecordedContainer({"agent-one": agent})
    monkeypatch.setattr(modules.config, "cosmos_personal_agents_container", state.agent_store)
    monkeypatch.setattr(modules.settings, "get_settings", lambda *args, **kwargs: deepcopy(settings))
    cache = importlib.import_module("app_settings_cache")
    monkeypatch.setattr(cache, "get_settings_cache", lambda: deepcopy(settings))

    def credential(**kwargs):
        value = MetadataCredential(state, kwargs)
        state.credentials.append(value)
        return value

    def client(**kwargs):
        transport = MetadataTransport(state)
        value = AgentsClient(**kwargs, transport=transport)
        state.clients.append((value, dict(kwargs)))
        state.transports.append(transport)
        return value

    monkeypatch.setattr("azure.identity.DefaultAzureCredential", credential)
    monkeypatch.setattr("azure.identity.ClientSecretCredential", credential)
    monkeypatch.setattr("azure.ai.agents.AgentsClient", client)

    def read_conversation(conversation_id):
        state.ownership_reads.append(conversation_id)
        return deepcopy(state.conversation)

    state.read_conversation = read_conversation
    state.reader = modules.metadata.build_external_metadata_reader(
        "owner", "conversation", read_conversation=read_conversation,
    )
    return state


def producer(world, capability="web_search"):
    return world.modules.contracts.ProducerIdentity(
        "owner", "conversation", "run", 1, "gather", capability, "test-v2",
    )


def read_current(world, source_type="web", *, source=None, selector=None, identity=None, reader=None):
    capabilities = {
        "web": "web_search", "url": "url_fetch", "agent": "agent_invoke",
        "action": "action_invoke", "deep_research": "deep_research",
    }
    return (reader or world.reader)(
        source_type, producer=identity or producer(world, capabilities[source_type]),
        settings=world.settings, source=source, selector=selector,
    )


def action_source(world):
    selector = world.modules.catalog._action_ref("personal", "owner", "action-one")
    source = world.modules.catalog.resolve_action_manifest("owner", selector, settings=world.settings)
    return source, selector


def agent_source(world):
    reference = {"id": "agent-one", "scope_type": "personal", "scope_id": "owner"}
    source = world.modules.agents.resolve_delegation_agent(reference, user_id="owner", settings=world.settings)
    return source, "personal:owner:agent-one"


def new_attestor(world):
    reader = world.modules.metadata.build_external_metadata_reader(
        "owner", "conversation", read_conversation=world.read_conversation,
    )
    return world.modules.configuration.OrchestrationExternalConfigurationAttestor(
        user_id="owner", conversation_id="conversation", read_current_source=reader,
        private_digest=private_digest,
    )


def foundry_capture(world, *, max_completion_tokens=None):
    class Refusal:
        def refuse(self):
            raise AssertionError("The actual engine rejected the fixture definition")

    local = world.settings["web_search_agent"]["other_settings"]["azure_ai_foundry"]
    evidence = world.modules.foundry._captured_foundry_definition(
        world.definition, local["agent_id"], local["endpoint"], local["api_version"], Refusal(),
    )
    evidence["foundry_settings"] = deepcopy(local)
    evidence["overrides"] = {
        key: deepcopy(evidence["definition"][key])
        for key in ("model", "instructions", "temperature", "top_p", "response_format")
    }
    if max_completion_tokens is not None:
        evidence["overrides"]["max_completion_tokens"] = max_completion_tokens
    run = ThreadRun({
        "id": "actual-sdk-run", "thread_id": "actual-sdk-thread", "assistant_id": local["agent_id"],
        **{key: value for key, value in world.definition.as_dict().items() if key != "id"},
        **evidence["overrides"],
    })
    return {
        **evidence, "phase": "run",
        "run": world.modules.configuration.foundry_run_snapshot(run),
    }


def test_construction_and_url_policy_read_do_not_open_sdk_or_store_resources(metadata_world):
    world = metadata_world
    assert world.ownership_reads == world.requests == world.credentials == world.run_store.reads == []
    result = read_current(world, "url")
    assert result is None
    assert world.ownership_reads == ["conversation", "conversation"]
    assert world.requests == world.credentials == world.run_store.reads == []


@pytest.mark.parametrize("field,value", [
    ("user_id", "other"), ("conversation_id", "other"), ("capability_id", "agent_invoke"),
])
def test_producer_mismatch_fails_before_any_metadata_read(metadata_world, field, value):
    world = metadata_world
    identity = replace(producer(world), **{field: value})
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        read_current(world, identity=identity)
    assert world.ownership_reads == world.requests == world.credentials == []


@pytest.mark.parametrize("changes", [
    {"id": "another-conversation"}, {"user_id": "other"}, {"orchestration_deleted": True},
])
def test_live_ownership_is_required_before_sdk_or_configuration_resolution(metadata_world, changes):
    world = metadata_world
    world.conversation.update(changes)
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        read_current(world)
    assert world.requests == world.credentials == world.run_store.reads == []


def test_real_sdk_get_agent_is_bounded_private_current_metadata(metadata_world):
    world = metadata_world
    before = deepcopy(world.settings)
    current = read_current(world)
    expected_definition = world.modules.configuration.foundry_definition_snapshot(world.definition)
    assert current["phase"] == "current"
    assert current["kind"] == "foundry"
    assert current["definition"] == expected_definition
    assert "run" not in current and "request" not in current
    assert world.settings == before
    assert len(world.requests) == 1
    method, url, options = world.requests[0]
    assert method == "GET"
    assert "remote-agent" in urlsplit(url).path
    assert parse_qs(urlsplit(url).query)["api-version"] == ["2025-05-01"]
    assert options["connection_timeout"] == 5 and options["read_timeout"] == 10
    assert world.clients[0][1]["retry_total"] == 0
    assert all(credential.closed for credential in world.credentials)
    assert all(transport.closed for transport in world.transports)
    assert world.run_store.reads == []


def test_capture_and_fresh_current_reader_project_identically_without_a_capture_map(metadata_world):
    world = metadata_world
    attestor = new_attestor(world)
    identity = producer(world)
    evidence = foundry_capture(world)
    attestor.capture("web", producer=identity, settings=world.settings)
    attestor.capture("web", producer=identity, settings=world.settings, source=evidence)
    admitted = attestor.for_admission("web", producer=identity, settings=world.settings)
    fresh = new_attestor(world)
    current = fresh.current("web", producer=identity, settings=world.settings)
    assert admitted == current
    assert fresh._captures == {}
    wire = json.dumps({"identity": current.identity, "revision": current.revision})
    assert "https:" not in wire and "remote-agent" not in wire and "synthetic" not in wire
    world.definition = Agent({**world.definition.as_dict(), "instructions": "Changed current instructions."})
    changed = fresh.current("web", producer=identity, settings=world.settings)
    assert changed != admitted
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        attestor.for_admission("web", producer=identity, settings=world.settings)


@pytest.mark.parametrize("status,retryable", [(401, None), (403, None), (404, None), (410, None), (429, True), (503, True), (400, False)])
def test_metadata_http_errors_remain_denial_or_typed_service_failure(metadata_world, status, retryable):
    world = metadata_world
    world.status = status
    expected = (
        world.modules.configuration.ResultUnavailableError if retryable is None
        else world.modules.configuration.ExternalConfigurationServiceError
    )
    with pytest.raises(expected) as raised:
        read_current(world)
    if retryable is not None:
        assert raised.value.retryable is retryable
    assert "PRIVATE_PROVIDER_ERROR" not in str(raised.value)
    assert len(world.requests) == 1
    assert all(credential.closed for credential in world.credentials)
    assert all(transport.closed for transport in world.transports)


@pytest.mark.parametrize("failure", [TimeoutError("PRIVATE_TIMEOUT"), ServiceRequestError("PRIVATE_OUTAGE")])
def test_transport_outages_do_not_become_missing_configuration(metadata_world, failure):
    world = metadata_world
    world.failure = failure
    with pytest.raises(world.modules.configuration.ExternalConfigurationServiceError) as raised:
        read_current(world)
    assert raised.value.retryable is True
    assert "PRIVATE" not in str(raised.value)
    assert len(world.requests) == 1


@pytest.mark.parametrize("status", [429, 503])
def test_authentication_service_throttling_and_outage_are_retryable(metadata_world, monkeypatch, status):
    world = metadata_world
    failure = ClientAuthenticationError("PRIVATE_AUTH_SERVICE_ERROR")
    failure.status_code = status

    def get_token(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(MetadataCredential, "get_token", get_token)
    with pytest.raises(world.modules.configuration.ExternalConfigurationServiceError) as raised:
        read_current(world)
    assert raised.value.retryable is True
    assert "PRIVATE" not in str(raised.value)
    assert world.requests == []
    assert all(credential.closed for credential in world.credentials)
    assert all(transport.closed for transport in world.transports)


@pytest.mark.parametrize("status,retryable", [(200, False), (429, True), (503, True)])
def test_sdk_decode_error_keeps_http_outage_distinct_from_malformed_success(metadata_world, status, retryable):
    world = metadata_world
    failure = DecodeError("PRIVATE_RESPONSE")
    failure.status_code = status
    world.failure = failure
    with pytest.raises(world.modules.configuration.ExternalConfigurationServiceError) as raised:
        read_current(world)
    assert raised.value.retryable is retryable
    assert "PRIVATE" not in str(raised.value)
    assert all(credential.closed for credential in world.credentials)
    assert all(transport.closed for transport in world.transports)


@pytest.mark.parametrize("status", [401, 403, 404, 410])
def test_malformed_denial_response_is_not_an_operational_outage(metadata_world, status):
    world = metadata_world
    failure = DecodeError("PRIVATE_DENIAL_RESPONSE")
    failure.status_code = status
    world.failure = failure
    with pytest.raises(world.modules.configuration.ResultUnavailableError) as raised:
        read_current(world)
    assert "PRIVATE" not in str(raised.value)
    assert all(credential.closed for credential in world.credentials)
    assert all(transport.closed for transport in world.transports)


def test_cancellation_and_owner_control_errors_are_not_reclassified(metadata_world):
    world = metadata_world

    class LeaseLost(RuntimeError):
        pass

    for failure in (InterruptedError("stopped"), LeaseLost("lost")):
        def check():
            raise failure

        reader = world.modules.metadata.build_external_metadata_reader(
            "owner", "conversation", read_conversation=world.read_conversation, execution_check=check,
        )
        with pytest.raises(type(failure)) as raised:
            read_current(world, reader=reader)
        assert raised.value is failure
    assert world.requests == world.credentials == world.ownership_reads == []


@pytest.mark.parametrize("stage", ["credentials", "clients", "requests"])
@pytest.mark.parametrize("failure_kind", ["cancel", "budget", "false"])
def test_control_checks_during_metadata_io_preserve_failure_and_close_owned_resources(metadata_world, stage, failure_kind):
    world = metadata_world
    failure = InterruptedError("cancelled") if failure_kind == "cancel" else ValueError("owner-budget")

    def check():
        if getattr(world, stage):
            if failure_kind == "false":
                return False
            raise failure

    reader = world.modules.metadata.build_external_metadata_reader(
        "owner", "conversation", read_conversation=world.read_conversation, execution_check=check,
    )
    expected = world.modules.configuration.ExternalConfigurationCancelledError if failure_kind == "false" else type(failure)
    with pytest.raises(expected) as raised:
        read_current(world, reader=reader)
    if failure_kind != "false":
        assert raised.value is failure
    assert all(credential.closed for credential in world.credentials)
    assert all(transport.closed for transport in world.transports)
    assert len(world.requests) == (1 if stage == "requests" else 0)


def test_elapsed_metadata_deadline_refuses_output_and_closes_resources(metadata_world, monkeypatch):
    world = metadata_world
    monkeypatch.setattr(world.modules.metadata, "monotonic", lambda: 31 if world.requests else 0)
    with pytest.raises(world.modules.configuration.ExternalConfigurationServiceError) as raised:
        read_current(world)
    assert raised.value.code == "external_configuration_timeout"
    assert raised.value.retryable is True
    assert len(world.requests) == 1
    assert all(credential.closed for credential in world.credentials)
    assert all(transport.closed for transport in world.transports)


def test_ownership_revocation_during_get_prevents_return_and_closes_resources(metadata_world):
    world = metadata_world
    world.revoke_after_get = True
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        read_current(world)
    assert len(world.requests) == 1
    assert all(credential.closed for credential in world.credentials)
    assert all(transport.closed for transport in world.transports)


@pytest.mark.parametrize("changes", [
    {"endpoint": ""}, {"api_version": ""}, {"agent_id": ""},
    {"authentication_type": "delegated_user"}, {"authentication_type": "api_key"},
    {"authentication_type": ""}, {"endpoint": "http://metadata.invalid"},
])
def test_missing_implicit_or_unsupported_foundry_configuration_never_opens_client(metadata_world, changes):
    world = metadata_world
    world.settings["web_search_agent"]["other_settings"]["azure_ai_foundry"].update(changes)
    with pytest.raises((world.modules.configuration.ResultUnavailableError,
                        world.modules.configuration.ExternalConfigurationServiceError)):
        read_current(world)
    assert world.requests == world.credentials == []


@pytest.mark.parametrize("changes", [
    {"tool_resources": {"file_search": {"vector_store_ids": ["resource"]}}},
    {"tools": [{"type": "azure_ai_search", "azure_ai_search": {"indexes": []}}]},
    {"tools": [{"type": "function", "function": {"name": "hidden_child"}}]},
    {"instructions": "Template {{variable}}"}, {"temperature": None},
])
def test_unreconstructible_definition_never_creates_current_authority(metadata_world, changes):
    world = metadata_world
    world.definition = Agent({**world.definition.as_dict(), **changes})
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        read_current(world)
    assert len(world.requests) == 1


def test_missing_sdk_fields_are_not_invented(metadata_world):
    world = metadata_world
    definition = world.definition.as_dict()
    definition.pop("top_p")
    world.definition = Agent(definition)
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        read_current(world)


def test_malformed_sdk_model_is_a_nonretryable_verification_failure(metadata_world):
    world = metadata_world
    world.definition = Agent({**world.definition.as_dict(), "model": ""})
    with pytest.raises(world.modules.configuration.ExternalConfigurationServiceError) as raised:
        read_current(world)
    assert raised.value.code == "external_configuration_metadata_invalid"
    assert raised.value.retryable is False


@pytest.mark.parametrize("selection", ["legacy", "endpoint-model", "endpoint-deployment"])
def test_action_uses_real_scoped_origin_preparation_and_actual_constructed_model(metadata_world, selection):
    world = metadata_world
    if selection != "legacy":
        configure_model_endpoint(world)
    if selection == "endpoint-deployment":
        world.run_store.items["run"]["seeds"]["model"].pop("model_id")
    source, selector = action_source(world)
    before = deepcopy(source)
    current = read_current(world, "action", source=source, selector=selector)
    origin = importlib.import_module("functions_action_manifest").get_action_origin
    assert origin(current["manifest"]) == origin(source)
    assert origin(current["prepared_manifest"]) == origin(source)
    assert source == before
    answer_binding = world.modules.models.resolve_orchestration_model(
        world.settings, user_id="owner", seeds=deepcopy(world.run_store.items["run"]["seeds"]),
    )
    try:
        context = SimpleNamespace(
            model_context={
                "provider": answer_binding.provider, "model_deployment": answer_binding.deployment,
                "endpoint_id": answer_binding.endpoint_id, "model_id": answer_binding.model_id,
            },
            gpt_model=answer_binding.deployment, active_group_ids=[],
        )
    finally:
        answer_binding.close()
    service, model = world.modules.actions._build_action_model(
        world.settings, context, "owner", capture_configuration=True,
    )
    try:
        assert model["model_id"] == (None if selection == "legacy" else "model-one")
        execution = service.get_prompt_execution_settings_class()(
            service_id="orchestration-action", parallel_tool_calls=False, tool_choice="auto",
        )
        model["parameters"] = {
            "parallel_tool_calls": execution.parallel_tool_calls, "tool_choice": execution.tool_choice,
        }
        captured = {
            "version": world.modules.configuration.EXTERNAL_ACQUISITION_VERSION,
            "kind": "action", "phase": "resolved",
            "reference": {"id": "action-one", "scope_type": "personal", "scope_id": "owner"},
            "manifest": source,
            "prepared_manifest": world.modules.loader.prepare_action_plugin_manifest(source, world.settings),
            "model": model,
        }
        expected = world.modules.configuration.project_external_configuration(
            "action", settings=world.settings, source=captured, selector=selector, private_digest=private_digest,
        )
        observed = world.modules.configuration.project_external_configuration(
            "action", settings=world.settings, source=current, selector=selector, private_digest=private_digest,
        )
        assert observed == expected
        attestor = new_attestor(world)
        identity = producer(world, "action_invoke")
        attestor.capture("action", producer=identity, settings=world.settings, source=captured, selector=selector)
        admitted = attestor.for_admission(
            "action", producer=identity, settings=world.settings, source=source, selector=selector,
        )
        fresh = new_attestor(world)
        restored = fresh.current("action", producer=identity, settings=world.settings, source=source)
        assert restored == admitted == expected
        assert fresh._captures == {}
    finally:
        asyncio.run(service.client.close())
    assert world.requests == world.credentials == []
    assert world.run_store.reads == [("run", "conversation")] * 3


def test_plain_action_dictionary_is_not_authorized_metadata(metadata_world):
    world = metadata_world
    source, selector = action_source(world)
    world.action_store.reads.clear()
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        read_current(world, "action", source=dict(source), selector=selector)
    assert world.action_store.reads == world.run_store.reads == []


@pytest.mark.parametrize("changed", [{"is_enabled": False}, {"endpoint": "https://changed.invalid"}])
def test_current_exact_action_revocation_or_change_is_not_accepted_from_old_payload(metadata_world, changed):
    world = metadata_world
    source, selector = action_source(world)
    world.action_store.items["action-one"].update(changed)
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        read_current(world, "action", source=source, selector=selector)
    assert world.run_store.reads == world.requests == []


@pytest.mark.parametrize("kind", ["workspace-identity", "secret-reference", "mcp-alias"])
def test_indirect_action_dependencies_are_refused_before_legacy_hydration(metadata_world, monkeypatch, kind):
    world = metadata_world
    action = world.action_store.items["action-one"]
    if kind == "workspace-identity":
        action["identity_id"] = "workspace-identity"
    elif kind == "secret-reference":
        action["auth"] = {"type": "key", "key": "owner--action--user--action-secret"}
    else:
        action["type"] = "mcpplugin"
    source, selector = action_source(world)
    prepare = Mock(side_effect=AssertionError("Unsupported metadata must not enter legacy hydration"))
    monkeypatch.setattr(world.modules.loader, "prepare_action_plugin_manifest", prepare)
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        read_current(world, "action", source=source, selector=selector)
    assert prepare.call_count == 0
    assert world.requests == world.credentials == []


def test_indirect_foundry_secret_is_not_passed_to_a_defaulting_secret_helper(metadata_world, monkeypatch):
    world = metadata_world
    local = world.settings["web_search_agent"]["other_settings"]["azure_ai_foundry"]
    local.update(
        authentication_type="service_principal", tenant_id="tenant", client_id="client",
        client_secret="owner--agent--user--foundry-secret",
    )
    resolve = Mock(side_effect=AssertionError("Indirect secrets are not a supported metadata mode"))
    monkeypatch.setattr(world.modules.foundry, "_resolve_secret_value", resolve)
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        read_current(world)
    assert resolve.call_count == 0
    assert world.requests == world.credentials == []


def test_remote_agent_uses_full_actual_current_resolver_config_and_live_definition(metadata_world):
    world = metadata_world
    source, selector = agent_source(world)
    current = read_current(world, "agent", source=source, selector=selector)
    resolved = world.modules.loader.resolve_agent_config(
        deepcopy(source), deepcopy(world.settings), execution_user_id="owner", group_scope_id=None,
    )
    assert current["resolved_config"] == resolved
    assert current["foundry"]["phase"] == "current"
    assert current["foundry"]["overrides"]["max_completion_tokens"] == 3072
    attestor = new_attestor(world)
    identity = producer(world, "agent_invoke")
    attestor.capture(
        "agent", producer=identity, settings=world.settings, selector=selector,
        source={
            "version": world.modules.configuration.EXTERNAL_ACQUISITION_VERSION,
            "kind": "agent", "phase": "resolved", "reference": current["reference"],
            "resolved_config": resolved,
        },
    )
    attestor.capture(
        "agent", producer=identity, settings=world.settings, selector=selector,
        source=foundry_capture(world, max_completion_tokens=3072),
    )
    admitted = attestor.for_admission(
        "agent", producer=identity, settings=world.settings, selector=selector, source=source,
    )
    fresh = new_attestor(world)
    restored = fresh.current("agent", producer=identity, settings=world.settings, source=source)
    assert restored == admitted
    assert fresh._captures == {}


def test_research_current_uses_exact_saved_selection_not_captured_answer_metadata(metadata_world, monkeypatch):
    world = metadata_world
    world.settings["enable_web_search"] = False
    world.run_store.items["run"]["seeds"]["reasoning_effort"] = "medium"
    runtime = importlib.import_module("functions_model_endpoint_runtime")
    forbidden = Mock(side_effect=AssertionError("Current reads must not construct a model"))
    for name in ("build_model_endpoint_sync_chat_client", "build_semantic_kernel_chat_service_for_model"):
        monkeypatch.setattr(runtime, name, forbidden)
    monkeypatch.setattr("openai.AzureOpenAI", forbidden)
    monkeypatch.setattr("openai.AsyncAzureOpenAI", forbidden)
    current = read_current(world, "deep_research")
    assert current["phase"] == "current" and current["web"] is None
    assert current["model"] == {
        "provider": "aoai", "protocol": "azure_openai",
        "endpoint": world.settings["azure_openai_gpt_endpoint"],
        "api_version": world.settings["azure_openai_gpt_api_version"], "deployment": "gpt-4o",
        "endpoint_id": "", "model_id": "",
        "parameters": {"response_length": 2048, "reasoning_effort": "medium"},
    }
    assert forbidden.call_count == 0
    assert world.requests == world.credentials == []


def test_explicit_research_override_is_independent_of_answer_selection(metadata_world):
    world = metadata_world
    world.settings.update(
        enable_web_search=False, chat_orchestration_planner_deployment="gpt-4o-mini",
        chat_orchestration_planner_model_provider="aoai",
    )
    current = read_current(world, "deep_research")
    assert current["model"]["deployment"] == "gpt-4o-mini"
    assert current["model"]["parameters"] == {}
    assert world.run_store.items["run"]["seeds"]["model"]["model_deployment"] == "gpt-4o"


@pytest.mark.parametrize("modern", [False, True])
@pytest.mark.parametrize("web_enabled", [False, True])
def test_actual_research_constructor_capture_equals_fresh_current_projection(metadata_world, modern, web_enabled):
    world = metadata_world
    if modern:
        configure_model_endpoint(world)
    world.settings["enable_web_search"] = web_enabled
    seeds = deepcopy(world.run_store.items["run"]["seeds"])
    binding = world.modules.models.resolve_orchestration_model(
        world.settings, user_id="owner", seeds=seeds, planner=True,
    )
    try:
        planner_client = binding.as_planner_client()
        evidence = world.modules.models.planner_client_construction_source(planner_client, binding.deployment)
        attestor = new_attestor(world)
        identity = producer(world, "deep_research")
        attestor.capture("deep_research", producer=identity, settings=world.settings)
        attestor.capture("deep_research", producer=identity, settings=world.settings, source=evidence)
        if web_enabled:
            attestor.capture(
                "deep_research", producer=identity, settings=world.settings, source=foundry_capture(world),
            )
        admitted = attestor.for_admission("deep_research", producer=identity, settings=world.settings)
        fresh = new_attestor(world)
        current = fresh.current("deep_research", producer=identity, settings=world.settings)
        assert current == admitted
        assert fresh._captures == {}
    finally:
        binding.close()


def configure_model_endpoint(world):
    endpoint = {
        "id": "endpoint-one", "provider": "aoai", "enabled": True, "name": "Explicit Azure",
        "connection": {
            "endpoint": "https://endpoint-model.openai.azure.com",
            "api_version": "2024-12-01-preview",
        },
        "auth": {"type": "api_key", "api_key": "synthetic-endpoint-key"},
        "models": [{
            "id": "model-one", "deploymentName": "gpt-4o-mini", "modelName": "gpt-4o-mini",
            "enabled": True, "responseLength": 1024,
        }],
    }
    world.settings.update(enable_multi_model_endpoints=True, model_endpoints=[endpoint])
    world.run_store.items["run"]["seeds"]["model"] = {
        "model_endpoint_id": "endpoint-one", "model_id": "model-one",
        "model_deployment": "gpt-4o-mini", "model_provider": "aoai",
    }
    return endpoint


@pytest.mark.parametrize("source_type", ["action", "deep_research"])
def test_modern_model_metadata_reuses_real_authorized_endpoint_resolution(metadata_world, source_type):
    world = metadata_world
    endpoint = configure_model_endpoint(world)
    world.settings["enable_web_search"] = False
    source, selector = action_source(world) if source_type == "action" else (None, None)
    current = read_current(world, source_type, source=source, selector=selector)
    assert current["model"]["endpoint"] == endpoint["connection"]["endpoint"]
    assert current["model"]["endpoint_id"] == "endpoint-one"
    assert current["model"]["model_id"] == "model-one"
    assert current["model"]["deployment"] == "gpt-4o-mini"
    assert current["model"]["parameters"] == (
        {"parallel_tool_calls": False, "tool_choice": "auto"}
        if source_type == "action" else {"response_length": 1024}
    )
    assert world.requests == world.credentials == []
    world.settings["enable_gpt_apim"] = True
    unchanged = read_current(world, source_type, source=source, selector=selector)
    assert unchanged == current


@pytest.mark.parametrize("kind", ["endpoint-disabled", "model-disabled", "wrong-model", "wrong-provider"])
def test_disabled_or_retargeted_model_never_falls_back(metadata_world, kind):
    world = metadata_world
    endpoint = configure_model_endpoint(world)
    world.settings["enable_web_search"] = False
    if kind == "endpoint-disabled":
        endpoint["enabled"] = False
    elif kind == "model-disabled":
        endpoint["models"][0]["enabled"] = False
    elif kind == "wrong-model":
        endpoint["models"][0]["id"] = "different-model"
    else:
        endpoint["provider"] = "custom"
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        read_current(world, "deep_research")
    assert world.requests == world.credentials == []


@pytest.mark.parametrize("mutation", ["wrong-owner", "wrong-conversation", "deleted", "wrong-attempt", "v1", "missing"])
def test_saved_selection_read_requires_the_same_current_owned_v2_producer(metadata_world, mutation):
    world = metadata_world
    run = world.run_store.items["run"]
    if mutation == "wrong-owner":
        run["user_id"] = "other"
    elif mutation == "wrong-conversation":
        run["conversation_id"] = "other"
    elif mutation == "deleted":
        run["checkpoints_deleted"] = True
    elif mutation == "wrong-attempt":
        run["attempt_index"] = 2
    elif mutation == "v1":
        run["plan"]["planner_contract_version"] = 1
    else:
        world.run_store.items.clear()
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        read_current(world, "deep_research")
    assert world.requests == world.credentials == []
    assert world.run_store.reads == [("run", "conversation")]


def test_strict_run_read_preserves_outage_instead_of_falling_back_to_settings(metadata_world):
    world = metadata_world
    world.run_store.failure = ServiceRequestError("PRIVATE_STORAGE_OUTAGE")
    with pytest.raises(world.modules.configuration.ExternalConfigurationServiceError) as raised:
        read_current(world, "deep_research")
    assert raised.value.retryable is True
    assert world.requests == world.credentials == []


def test_action_and_research_construction_never_uses_a_current_reader_capture_map(metadata_world):
    world = metadata_world
    world.settings["enable_web_search"] = False
    first = read_current(world, "deep_research")
    world.settings["azure_openai_gpt_endpoint"] = "https://changed-model.openai.azure.com"
    fresh = world.modules.metadata.build_external_metadata_reader(
        "owner", "conversation", read_conversation=world.read_conversation,
    )
    changed = read_current(world, "deep_research", reader=fresh)
    assert changed["model"]["endpoint"] != first["model"]["endpoint"]
    assert changed["model"]["deployment"] == first["model"]["deployment"]
    assert world.requests == world.credentials == []


@pytest.mark.parametrize("mutation", ["apim", "implicit-model", "implicit-endpoint", "implicit-version"])
def test_implicit_and_apim_model_bindings_are_explicitly_unavailable(metadata_world, mutation):
    world = metadata_world
    if mutation == "apim":
        world.settings["enable_gpt_apim"] = True
    elif mutation == "implicit-model":
        world.run_store.items["run"]["seeds"]["model"] = {}
    elif mutation == "implicit-endpoint":
        world.settings.pop("azure_openai_gpt_endpoint")
    else:
        world.settings.pop("azure_openai_gpt_api_version")
    with pytest.raises((world.modules.configuration.ResultUnavailableError,
                        world.modules.configuration.ExternalConfigurationServiceError)):
        read_current(world, "deep_research")
    assert world.requests == world.credentials == []


def test_current_run_roles_never_grant_endpoint_access(metadata_world, monkeypatch):
    world = metadata_world
    configure_model_endpoint(world)
    world.run_store.items["run"]["user_roles"] = ["Admin"]
    governance = importlib.import_module("functions_governance")
    checks = []

    def deny(user_id, endpoints, feature):
        checks.append((user_id, feature))
        raise PermissionError("Current model access was revoked")

    monkeypatch.setattr(governance, "filter_governed_model_endpoints", deny)
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        read_current(world, "deep_research")
    assert checks == [("owner", "governance_global_endpoints")]
    assert world.requests == world.credentials == []


def test_unnamed_action_model_cannot_be_retargeted_by_later_multi_endpoint_settings(metadata_world):
    world = metadata_world
    source, selector = action_source(world)
    original = read_current(world, "action", source=source, selector=selector)
    world.settings.update(
        enable_multi_model_endpoints=True,
        model_endpoints=[{
            "id": "new-endpoint", "name": "Different transport", "provider": "aoai", "enabled": True,
            "connection": {"endpoint": "https://another.openai.azure.com", "api_version": "2024-12-01-preview"},
            "auth": {"type": "api_key", "api_key": "synthetic"},
            "models": [{"id": "new-model", "deploymentName": "gpt-4o", "enabled": True}],
        }],
    )
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        read_current(world, "action", source=source, selector=selector)
    assert original["model"]["endpoint"] == world.settings["azure_openai_gpt_endpoint"]
    assert world.requests == world.credentials == []


def bind_producing_step(world, capability, selection, *, group_id=None):
    """Make the saved run a per-step Auto plan whose producing step has its own model.

    Auto requests carry no model of their own, so the run's seeds hold none.
    """
    run = world.run_store.items["run"]
    run["seeds"]["model"] = None
    run["plan"].update(model_routing="auto", steps=[{
        "step_id": "gather", "capability_id": capability,
        "model_binding": {
            "selection": deepcopy(selection), "label": selection["model_deployment"],
            "profile_id": "profile", "profile_revision": "one", "task": "general",
            "required_capabilities": ["generatesText", "processesText"], "group_id": group_id,
        },
    }])
    return deepcopy(run["plan"]["steps"][0]["model_binding"])


def bound_step_model(world, binding):
    """Resolve the model exactly as a per-step Auto scope does for this binding."""
    routing = importlib.import_module("functions_orchestration_model_routing")
    seeds = deepcopy(world.run_store.items["run"]["seeds"])
    return world.modules.models.resolve_orchestration_model(
        world.settings, user_id="owner", seeds=routing.binding_seeds(seeds, binding),
    )


def add_classic_model(world, deployment="gpt-4o-mini", response_length=1024):
    world.settings["gpt_model"]["selected"].append({
        "deploymentName": deployment, "modelName": deployment, "responseLength": response_length,
    })


def test_bound_auto_research_is_rebuilt_from_its_binding_not_the_run_or_planner_override(metadata_world):
    world = metadata_world
    world.settings.update(
        enable_web_search=False, enable_deep_source_review=False,
        chat_orchestration_planner_deployment="gpt-4o", chat_orchestration_planner_model_provider="aoai",
    )
    add_classic_model(world)
    world.run_store.items["run"]["seeds"]["reasoning_effort"] = "medium"
    binding = bind_producing_step(world, "deep_research", {
        "model_deployment": "gpt-4o-mini", "model_provider": "aoai",
    })
    current = read_current(world, "deep_research")
    assert current["model"]["deployment"] == "gpt-4o-mini"
    assert current["model"]["parameters"] == {"response_length": 1024}
    model = bound_step_model(world, binding)
    try:
        evidence = world.modules.models.planner_client_construction_source(
            model.as_planner_client(), model.deployment,
        )
        attestor = new_attestor(world)
        identity = producer(world, "deep_research")
        attestor.capture("deep_research", producer=identity, settings=world.settings)
        attestor.capture("deep_research", producer=identity, settings=world.settings, source=evidence)
        attestor.validate_acquisition(
            "deep_research", producer=identity, settings=world.settings,
            current_settings=world.settings, source=evidence,
        )
        admitted = attestor.for_admission("deep_research", producer=identity, settings=world.settings)
        fresh = new_attestor(world).current("deep_research", producer=identity, settings=world.settings)
        assert fresh == admitted
    finally:
        model.close()
    assert world.requests == world.credentials == []


@pytest.mark.parametrize("selection", ["legacy", "endpoint"])
def test_bound_auto_action_is_rebuilt_from_its_binding_and_admits_its_actual_model(metadata_world, selection):
    world = metadata_world
    if selection == "legacy":
        add_classic_model(world)
        chosen = {"model_deployment": "gpt-4o-mini", "model_provider": "aoai"}
    else:
        endpoint = configure_model_endpoint(world)
        endpoint["models"].append({
            "id": "model-two", "deploymentName": "gpt-4.1", "modelName": "gpt-4.1", "enabled": True,
        })
        chosen = {
            "model_endpoint_id": "endpoint-one", "model_id": "model-two",
            "model_deployment": "gpt-4.1", "model_provider": "aoai",
        }
    binding = bind_producing_step(world, "action_invoke", chosen)
    source, selector = action_source(world)
    current = read_current(world, "action", source=source, selector=selector)
    assert current["model"]["deployment"] == chosen["model_deployment"]
    assert current["model"]["model_id"] == chosen.get("model_id")
    model = bound_step_model(world, binding)
    try:
        context = SimpleNamespace(
            model_context={
                "provider": model.provider, "model_deployment": model.deployment,
                "endpoint_id": model.endpoint_id, "model_id": model.model_id,
                "user_id": "owner", "active_group_ids": [],
            },
            gpt_model=model.deployment, active_group_ids=[],
        )
    finally:
        model.close()
    service, built = world.modules.actions._build_action_model(
        world.settings, context, "owner", capture_configuration=True,
    )
    try:
        execution = service.get_prompt_execution_settings_class()(
            service_id="orchestration-action", parallel_tool_calls=False, tool_choice="auto",
        )
        built["parameters"] = {
            "parallel_tool_calls": execution.parallel_tool_calls, "tool_choice": execution.tool_choice,
        }
        captured = {
            "version": world.modules.configuration.EXTERNAL_ACQUISITION_VERSION,
            "kind": "action", "phase": "resolved",
            "reference": {"id": "action-one", "scope_type": "personal", "scope_id": "owner"},
            "manifest": source,
            "prepared_manifest": world.modules.loader.prepare_action_plugin_manifest(source, world.settings),
            "model": built,
        }
        attestor = new_attestor(world)
        identity = producer(world, "action_invoke")
        attestor.capture("action", producer=identity, settings=world.settings, source=captured, selector=selector)
        admitted = attestor.for_admission(
            "action", producer=identity, settings=world.settings, source=source, selector=selector,
        )
        fresh = new_attestor(world).current("action", producer=identity, settings=world.settings, source=source)
        assert fresh == admitted
    finally:
        asyncio.run(service.client.close())
    assert world.requests == world.credentials == []


@pytest.mark.parametrize("mutation", ["unbound", "malformed", "other-step", "other-capability"])
def test_auto_step_without_its_own_binding_is_refused(metadata_world, mutation):
    world = metadata_world
    world.settings["enable_web_search"] = False
    bind_producing_step(world, "deep_research", {"model_deployment": "gpt-4o", "model_provider": "aoai"})
    # A usable run selection must not stand in for the step's missing binding.
    world.run_store.items["run"]["seeds"]["model"] = {"model_deployment": "gpt-4o", "model_provider": "aoai"}
    step = world.run_store.items["run"]["plan"]["steps"][0]
    if mutation == "unbound":
        step.pop("model_binding")
    elif mutation == "malformed":
        step["model_binding"]["selection"] = "gpt-4o"
    elif mutation == "other-step":
        step["step_id"] = "another"
    else:
        step["capability_id"] = "action_invoke"
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        read_current(world, "deep_research")
    assert world.requests == world.credentials == []


def test_pinned_runs_keep_their_own_selection_and_planner_override(metadata_world):
    world = metadata_world
    world.settings.update(enable_web_search=False, chat_orchestration_planner_deployment="gpt-4o-mini")
    add_classic_model(world)
    run = world.run_store.items["run"]
    run["plan"]["steps"] = [{
        "step_id": "gather", "capability_id": "deep_research",
        "model_binding": {"selection": {"model_deployment": "gpt-4o"}},
    }]
    current = read_current(world, "deep_research")
    assert current["model"]["deployment"] == "gpt-4o-mini", "a pinned run still honors the planner override"


@pytest.mark.parametrize("planner,expected", [
    (True, ["document-group", "model-group"]),
    (False, ["document-group"]),
])
def test_bound_step_groups_match_how_each_client_authorizes_its_model(metadata_world, planner, expected):
    """Research resolves its model with the binding's model group, as the step scope does.

    The action builder authorizes with the run's own groups only, never groups carried in
    model context, so a rebuilt action configuration cannot use the binding's group either.
    """
    world = metadata_world
    world.run_store.items["run"]["seeds"]["active_group_ids"] = ["document-group"]
    capability = "deep_research" if planner else "action_invoke"
    bind_producing_step(
        world, capability, {"model_deployment": "gpt-4o", "model_provider": "aoai"},
        group_id="model-group",
    )
    read = world.modules.metadata._MetadataRead("owner", "conversation", world.read_conversation, None)
    seeds = world.modules.metadata._run_seeds(read, producer(world, capability), planner=planner)
    assert seeds == {
        "model": {"model_deployment": "gpt-4o", "model_provider": "aoai"},
        "reasoning_effort": "", "active_group_ids": expected, "bound": True,
    }
    assert world.run_store.items["run"]["seeds"]["active_group_ids"] == ["document-group"]


def test_bound_action_model_is_still_authorized_only_with_the_run_groups(metadata_world, monkeypatch):
    """A step scope's model context never widens the groups an action model is checked against."""
    world = metadata_world
    runtime = importlib.import_module("functions_model_endpoint_runtime")
    routing = importlib.import_module("functions_orchestration_model_routing")
    seen = []

    def resolve(settings, model_context, authorize=False):
        seen.append((deepcopy(model_context["active_group_ids"]), authorize))
        return None

    monkeypatch.setattr(runtime, "resolve_model_endpoint_from_context", resolve)
    binding = {"selection": {"model_endpoint_id": "group-endpoint", "model_id": "group-model"}, "group_id": "model-group"}
    scoped = routing.binding_seeds({"active_group_ids": ["document-group"]}, binding)
    context = SimpleNamespace(
        model_context={
            "endpoint_id": "group-endpoint", "model_id": "group-model", "provider": "aoai",
            "active_group_ids": scoped["active_group_ids"],
        },
        gpt_model="group-model", active_group_ids=["document-group"],
    )
    assert scoped["active_group_ids"] == ["document-group", "model-group"]
    with pytest.raises(PermissionError):
        world.modules.actions._build_action_model(world.settings, context, "owner")
    assert seen == [(["document-group"], True)]


@pytest.mark.parametrize("auth", ["managed_identity", "service_principal"])
def test_foundry_credential_configuration_and_cleanup_match_explicit_auth(metadata_world, auth):
    world = metadata_world
    local = world.settings["web_search_agent"]["other_settings"]["azure_ai_foundry"]
    local["authentication_type"] = auth
    if auth == "managed_identity":
        local.update(managed_identity_type="user_assigned", managed_identity_client_id="identity-one")
    else:
        local.update(tenant_id="tenant-one", client_id="client-one", client_secret="synthetic-client-secret")
    read_current(world)
    options = world.credentials[0].options
    assert options["connection_timeout"] == 5 and options["read_timeout"] == 10
    assert options["retry_total"] == 0
    if auth == "managed_identity":
        assert options["managed_identity_client_id"] == "identity-one"
    else:
        assert options["tenant_id"] == "tenant-one"
        assert options["client_id"] == "client-one"
        assert options["client_secret"] == "synthetic-client-secret"
    assert world.credentials[0].closed


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("functions_orchestration_external_metadata", "functions_orchestration_external_configuration"),
    ("functions_orchestration_external_configuration", "functions_orchestration_external_metadata"),
])
def test_metadata_composition_imports_without_initializing_application_owners(order, optimized):
    run_probe(EARLY_PROBE, order, optimized)


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("functions_orchestration_external_metadata", "app", "background_tasks"),
    ("app", "functions_orchestration_external_metadata", "background_tasks"),
    ("background_tasks", "functions_orchestration_external_metadata"),
])
def test_metadata_composition_preserves_real_web_and_scheduler_imports(order, optimized):
    run_probe(APP_PROBE, order, optimized)
