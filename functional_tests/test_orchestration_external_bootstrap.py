# test_orchestration_external_bootstrap.py
"""
Application-owned current identity and acquisition wiring for retained results.
Version: 0.261.140
Implemented in: 0.261.127
Single orchestration contract updated in: 0.261.139

Runs the real bootstrap, authentication factory and directory reader with only
the MSAL client, Cosmos storage and HTTP wire doubled. No tenant calls, consent
changes, settings repairs, cached role fallback or interactive scope changes.
"""

import hashlib
import hmac
import importlib
import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from requests.exceptions import Timeout

from functions_orchestration_external_identity import ExternalIdentityServiceError
from functions_orchestration_invocation_capture import OrchestrationInvocationServiceError
from functions_orchestration_result_contracts import canonical_digest
from functions_orchestration_results import ResultUnavailableError
from test_orchestration_external_identity import (
    APP_ID,
    CONVERSATION_ID,
    GraphWorld,
    TOKEN,
    URL_ROLE,
    USER_ID,
    assignment,
)
from test_orchestration_harness_routes import modules
from test_support.orchestration_results import ResultContainer
from test_support.orchestration_revisions import AtomicMemoryContainer


class BoundedMemoryContainer(AtomicMemoryContainer):
    def read_item(self, item, partition_key, **options):
        if options and options != {
            "connection_timeout": 10.0, "read_timeout": 10.0, "retry_total": 0,
        }:
            raise AssertionError("Unexpected point-read options.")
        return super().read_item(item, partition_key)


@pytest.fixture
def external_root(modules, monkeypatch):
    with GraphWorld() as world:
        conversations = BoundedMemoryContainer("id")
        settings = BoundedMemoryContainer("id")
        runs = AtomicMemoryContainer("conversation_id")
        conversations.create_item(deepcopy(world.conversation))
        settings.create_item(deepcopy(world.settings))
        settings_read = Mock(wraps=settings.read_item)
        monkeypatch.setattr(settings, "read_item", settings_read)
        token = Mock(return_value={"access_token": TOKEN})
        client = SimpleNamespace(acquire_token_for_client=token)
        client_factory = Mock(return_value=client)
        root = modules.bootstrap
        monkeypatch.setattr(modules.config, "cosmos_conversations_container", conversations)
        monkeypatch.setattr(modules.config, "cosmos_user_settings_container", settings)
        monkeypatch.setattr(modules.config, "cosmos_orchestration_runs_container", runs)
        monkeypatch.setattr(modules.runs, "cosmos_orchestration_runs_container", runs)
        result_items = ResultContainer()
        monkeypatch.setattr(modules.config, "cosmos_personal_workflow_run_items_container", result_items)
        monkeypatch.setattr(modules.auth, "CLIENT_ID", APP_ID)
        monkeypatch.setattr(modules.auth, "CLIENT_SECRET", "synthetic-client-secret")
        monkeypatch.setattr(modules.auth, "ConfidentialClientApplication", client_factory)
        monkeypatch.setattr(modules.auth, "get_graph_base_url", lambda: world.base_url)
        monkeypatch.setattr(modules.auth, "get_graph_authority", lambda: "https://login.example.test/tenant")
        monkeypatch.setattr(root.requests, "get", world.session.get)
        yield SimpleNamespace(
            root=root, auth=modules.auth, world=world, settings=settings,
            settings_read=settings_read, conversations=conversations,
            token=token, client_factory=client_factory, runs=runs, result_items=result_items,
        )


def reader_for(runtime):
    return runtime.root.build_external_identity_reader(USER_ID, CONVERSATION_ID)


def read_identity(reader):
    return reader(user_id=USER_ID, conversation_id=CONVERSATION_ID)


def test_source_free_service_construction_never_acquires_directory_authority(external_root):
    runtime = external_root
    unused_reader = reader_for(runtime)
    services = runtime.root.build_orchestration_services(
        USER_ID, CONVERSATION_ID, settings={"max_generated_chat_artifact_size_mb": 1},
    )
    catalog = services.export_catalog()
    bindings = services.capability_request_bindings()
    assert callable(unused_reader)
    assert catalog
    assert all(callable(bindings[name]) for name in (
        "external_source_preflight",
        "external_source_admission", "external_source_authorizer",
        "capture_external_source_configuration",
    ))
    assert runtime.world.adapter.requests == []
    runtime.client_factory.assert_not_called()
    runtime.settings_read.assert_not_called()


def retained_url_runtime(runtime, monkeypatch):
    """Use the real root, Graph wire, current policy, retention and result store."""
    # Runtime imports must follow the initialized application fixture.
    executor = importlib.import_module("functions_orchestration_executor")
    url = "https://example.com/source"
    settings = {
        "enable_chat_orchestration": True,
        "enable_url_access": True, "require_member_of_url_access_user": True,
        "chat_orchestration_enabled_capabilities": [], "max_generated_chat_artifact_size_mb": 1,
    }
    monkeypatch.setattr(runtime.root, "get_settings", lambda: deepcopy(settings))
    monkeypatch.setitem(runtime.root.config.CLIENTS, "storage_account_office_docs_client", None)
    runtime.world.assignments.append(assignment("url-assignment", role_id=URL_ROLE))
    step = {
        "step_id": "gather", "capability_id": "url_fetch",
        "arguments": {"urls": [url]}, "enabled": True,
    }
    fingerprint = canonical_digest({"step": step, "inputs": []})
    context = executor.RunContext(
        user_id=USER_ID, conversation_id=CONVERSATION_ID, run_id="external-root-run",
        attempt_index=1, plan_contract_version=2, user_message=f"Review {url}",
        user_roles=["User", "UrlAccessUser"], allowed_user_urls=[url],
        result_guard_token_for_step=lambda _step_id: "server-attempt-token",
        result_input_fingerprint_for_step=lambda _step_id: fingerprint,
    )
    record = {
        "id": context.run_id, "user_id": USER_ID, "conversation_id": CONVERSATION_ID,
        "attempt_index": 1, "status": "running", "user_message": context.user_message,
        "memory_audience": {"kind": "personal", "owner_id": USER_ID, "collaboration_id": ""},
        "plan": {"planner_contract_version": 2, "steps": [deepcopy(step)]},
    }
    runtime.runs.create_item(record)
    services = runtime.root.build_orchestration_services(USER_ID, CONVERSATION_ID, settings=settings)
    context.result_service = services.results
    context.external_source_admission = services.external_source_admission
    context.external_source_preflight = services.external_source_preflight
    context.capture_external_source_configuration = services.capture_external_source_configuration
    return SimpleNamespace(
        context=context, producer=context.result_producer(step), step=step, settings=settings,
        services=services, fingerprint=fingerprint,
        result={
            "status": "completed", "evidence": [],
            "notes": ["Retained source line.\n" * 600 + "The final line: caf\u00e9."],
            "citations": [{"url": url, "title": "Original source"}],
        },
    )


def retain_root_url(bound):
    # The real root is initialized before this runtime boundary is imported.
    retention = importlib.import_module("functions_orchestration_result_runtime")
    bound.services.capture_external_source_configuration(
        "url", producer=bound.producer, settings=deepcopy(bound.settings),
    )
    return retention.retain_gather_result(bound.step, bound.context, bound.result, source_manifest=[])


def test_default_root_entry_authorization_does_not_create_acquisition_proof(external_root, monkeypatch):
    runtime = external_root
    bound = retained_url_runtime(runtime, monkeypatch)
    authorized = bound.services.external_source_preflight(producer=bound.producer, selector=None)
    assert authorized is None
    assert runtime.world.adapter.requests
    with pytest.raises(ResultUnavailableError):
        bound.services.external_source_admission(producer=bound.producer, prepared=bound.result)
    assert bound.services.results.access.external_source_catalog == {}
    assert runtime.result_items.items == {}
    runtime.world.assignments = []
    with pytest.raises(ResultUnavailableError):
        bound.services.external_source_preflight(producer=bound.producer, selector=None)


def test_default_root_admits_url_and_reopens_full_result_after_restart(external_root, monkeypatch):
    runtime = external_root
    bound = retained_url_runtime(runtime, monkeypatch)
    assert runtime.world.adapter.requests == []
    task = retain_root_url(bound)
    assert len(bound.services.results.access.external_source_catalog) == 1
    assert len(task.outputs) == 1 and task.output("prepared").kind == "structured-v1"
    original_reader = bound.services.results.open_result(task.output("prepared"))
    original = original_reader.read_value()
    assert original["notes"] == bound.result["notes"]
    assert original["citations"] == bound.result["citations"]
    assert original["content_scope"] == "reported_external_content"
    assert len(original["notes"][0]) > 4096

    restarted = runtime.root.build_orchestration_services(
        USER_ID, CONVERSATION_ID, settings=bound.settings,
    )
    monkeypatch.setattr(restarted, "external_source_admission", Mock(side_effect=AssertionError("No reacquisition")))
    monkeypatch.setattr(
        restarted, "capture_external_source_configuration", Mock(side_effect=AssertionError("No recapture")),
    )
    recovered = restarted.results.recover_task_result(
        producer=bound.producer, input_fingerprint=bound.fingerprint,
    )
    assert recovered == task
    reader = restarted.results.open_result(recovered.output("prepared"), require_current_sources=True)
    restored = reader.read_value()
    metadata = reader.metadata()
    assert restored == original
    assert metadata["origin"] == "grounded" and metadata["external_source_count"] == 1
    assert restarted.results.access.external_source_catalog == {}
    assert runtime.world.adapter.requests
    wire = json.dumps(task.to_dict())
    assert TOKEN not in wire and "synthetic-client-secret" not in wire
    restarted.external_source_admission.assert_not_called()
    restarted.capture_external_source_configuration.assert_not_called()


@pytest.mark.parametrize("change", ["roles", "account", "settings", "user_url", "owner", "deleted", "missing"])
def test_default_root_preflight_uses_current_authority_before_acquisition(external_root, monkeypatch, change):
    runtime = external_root
    bound = retained_url_runtime(runtime, monkeypatch)
    supplied_settings = deepcopy(bound.settings)
    if change == "roles":
        runtime.world.assignments = []
    elif change == "account":
        runtime.world.user["accountEnabled"] = False
    elif change == "settings":
        bound.settings["enable_url_access"] = False
    elif change == "user_url":
        record = runtime.runs.read_item(bound.context.run_id, CONVERSATION_ID)
        record["user_message"] = "Review an unspecified source."
        runtime.runs.replace_item(
            record["id"], record, etag=record["_etag"], match_condition=MatchConditions.IfNotModified,
        )
    else:
        conversation = runtime.conversations.read_item(CONVERSATION_ID, CONVERSATION_ID)
        if change == "missing":
            runtime.conversations.delete_item(
                CONVERSATION_ID, CONVERSATION_ID, etag=conversation["_etag"],
            )
        else:
            conversation.update(
                {"user_id": "another-owner"} if change == "owner" else {"orchestration_deleted": True},
            )
            runtime.conversations.replace_item(
                CONVERSATION_ID, conversation,
                etag=conversation["_etag"], match_condition=MatchConditions.IfNotModified,
            )
    with pytest.raises(ResultUnavailableError):
        bound.services.capture_external_source_configuration(
            "url", producer=bound.producer, settings=supplied_settings,
        )
    assert bound.services.results.access.external_source_catalog == {}
    assert runtime.result_items.items == {}


@pytest.mark.parametrize("field", ["user_id", "conversation_id"])
def test_default_root_capture_refuses_a_foreign_producer_before_directory_io(external_root, monkeypatch, field):
    runtime = external_root
    bound = retained_url_runtime(runtime, monkeypatch)
    foreign = replace(bound.producer, **{field: "foreign"})
    with pytest.raises(ResultUnavailableError):
        bound.services.capture_external_source_configuration(
            "url", producer=foreign, settings=bound.settings,
        )
    assert runtime.world.adapter.requests == []
    assert runtime.result_items.items == {}
    runtime.client_factory.assert_not_called()


@pytest.mark.parametrize("change", ["roles", "account", "settings"])
def test_default_root_retained_reads_recheck_current_authority(external_root, monkeypatch, change):
    runtime = external_root
    bound = retained_url_runtime(runtime, monkeypatch)
    task = retain_root_url(bound)
    before = deepcopy(runtime.result_items.items)
    if change == "roles":
        runtime.world.assignments = []
    elif change == "account":
        runtime.world.user["accountEnabled"] = False
    else:
        bound.settings["enable_url_access"] = False
    restarted = runtime.root.build_orchestration_services(USER_ID, CONVERSATION_ID, settings=bound.settings)
    with pytest.raises(ResultUnavailableError):
        restarted.results.open_result(task.output("prepared"), require_current_sources=True)
    assert runtime.result_items.items == before


def test_default_root_preserves_directory_timeout_instead_of_denial(external_root, monkeypatch):
    runtime = external_root
    bound = retained_url_runtime(runtime, monkeypatch)
    runtime.world.adapter.error = Timeout("Private directory transport details.")
    with pytest.raises(ExternalIdentityServiceError) as raised:
        bound.services.capture_external_source_configuration(
            "url", producer=bound.producer, settings=bound.settings,
        )
    assert raised.value.code == "external_identity_timeout"
    assert raised.value.retryable is True
    assert "Private" not in str(raised.value)
    assert bound.services.results.access.external_source_catalog == {}
    assert runtime.result_items.items == {}


@pytest.mark.parametrize("store", ["conversations", "runs", "app_settings"])
@pytest.mark.parametrize("error_type, code, retryable", [
    (AzureError, "external_configuration_service_unavailable", True),
    (Timeout, "external_configuration_timeout", True),
    (ValueError, "external_configuration_metadata_invalid", False),
])
def test_default_root_current_authority_storage_failures_are_operational(
    external_root, monkeypatch, store, error_type, code, retryable,
):
    runtime = external_root
    bound = retained_url_runtime(runtime, monkeypatch)
    failure = Mock(side_effect=error_type("Private current-authority storage details."))
    if store == "app_settings":
        monkeypatch.setattr(runtime.root, "get_settings", failure)
    else:
        monkeypatch.setattr(getattr(runtime, store), "read_item", failure)
    with pytest.raises(OrchestrationInvocationServiceError) as raised:
        bound.services.capture_external_source_configuration(
            "url", producer=bound.producer, settings=bound.settings,
        )
    assert raised.value.code == code
    assert raised.value.retryable is retryable
    assert "Private" not in str(raised.value)
    assert runtime.result_items.items == {}


def test_private_configuration_digest_is_stable_keyed_and_purpose_scoped(external_root, monkeypatch):
    root = external_root.root
    key = b"test-backend-secret-" + b"a" * 32
    value = b'{"source":"action","private_configuration":"fixture"}'
    monkeypatch.setattr(root.config, "SECRET_KEY", key)
    first = root.private_external_configuration_digest(value)
    repeated = root.private_external_configuration_digest(value)
    changed = root.private_external_configuration_digest(value + b" ")
    expected = hmac.new(
        key, b"SimpleChat:orchestration-external-configuration:v1\x00" + value, hashlib.sha256,
    ).hexdigest()
    unkeyed = hashlib.sha256(value).hexdigest()
    monkeypatch.setattr(root.config, "SECRET_KEY", key.decode("utf-8"))
    text_key = root.private_external_configuration_digest(value)
    monkeypatch.setattr(root.config, "SECRET_KEY", b"test-backend-secret-" + b"b" * 32)
    rotated = root.private_external_configuration_digest(value)
    assert first == repeated == text_key == expected
    assert first != changed and first != rotated and first != unkeyed
    assert len(first) == 64 and all(character in "0123456789abcdef" for character in first)
    assert external_root.world.adapter.requests == []
    external_root.client_factory.assert_not_called()


@pytest.mark.parametrize("key", [
    None, "", "short", "dev-secret-key-change-in-production", True, {},
    b"short", " " * 32, "\ud800" * 32,
])
def test_private_configuration_digest_refuses_missing_weak_or_public_default_keys(external_root, monkeypatch, key):
    root = external_root.root
    monkeypatch.setattr(root.config, "SECRET_KEY", key)
    with pytest.raises(ResultUnavailableError) as raised:
        root.private_external_configuration_digest(b'{"source":"action"}')
    assert raised.value.code == "external_configuration_private_digest_required"
    assert external_root.world.adapter.requests == []
    external_root.client_factory.assert_not_called()


@pytest.mark.parametrize("value", [None, {}, "configuration", bytearray(b"configuration")])
def test_private_configuration_digest_requires_canonical_bytes(external_root, value):
    root = external_root.root
    with pytest.raises(root.ResultContractError) as raised:
        root.private_external_configuration_digest(value)
    assert raised.value.code == "external_configuration_payload_invalid"


@pytest.mark.parametrize("graph_base, expected_scope", [
    ("https://graph.microsoft.com/v1.0", "https://graph.microsoft.com/.default"),
    ("https://graph.microsoft.us/v1.0", "https://graph.microsoft.us/.default"),
    ("https://graph.example.test/gateway/v1.0", "https://graph.example.test/.default"),
])
def test_real_root_uses_current_application_authority_and_trusted_cloud_origin(
    external_root, graph_base, expected_scope,
):
    runtime = external_root
    runtime.world.base_url = graph_base
    runtime.world.prefix = urlsplit(graph_base).path.rstrip("/")
    interactive_scopes = deepcopy(runtime.auth.SCOPE)
    identity = read_identity(reader_for(runtime))
    assert identity.user_id == USER_ID
    assert identity.roles == ("User",)
    runtime.client_factory.assert_called_once_with(
        APP_ID, authority="https://login.example.test/tenant",
        client_credential="synthetic-client-secret", token_cache=None, timeout=10.0,
    )
    assert all(call.kwargs == {"scopes": [expected_scope]} for call in runtime.token.call_args_list)
    assert runtime.auth.SCOPE == interactive_scopes
    assert len(runtime.world.adapter.requests) == 3
    assert runtime.settings_read.call_count >= 2
    assert all(call.kwargs == {
        "item": USER_ID, "partition_key": USER_ID,
        "connection_timeout": 10.0, "read_timeout": 10.0, "retry_total": 0,
    } for call in runtime.settings_read.call_args_list)
    runtime.world.settings_reader.assert_not_called()


def test_current_settings_are_point_read_without_repairs_or_request_cache(external_root):
    runtime = external_root
    reader = reader_for(runtime)
    initial = read_identity(reader)
    settings = runtime.settings.read_item(USER_ID, USER_ID)
    settings["settings"]["enable_agents"] = False
    runtime.settings.upsert_item(settings)
    changed = read_identity(reader)
    assert initial.user_enable_agents is True
    assert changed.user_enable_agents is False
    runtime.client_factory.assert_called_once()
    runtime.world.assignments = []
    with pytest.raises(ResultUnavailableError):
        read_identity(reader)


def test_current_identity_accepts_sdk_conversation_and_settings_responses(external_root):
    runtime = external_root
    runtime.conversations.sdk_responses = True
    runtime.settings.sdk_responses = True
    reader = reader_for(runtime)
    initial = read_identity(reader)
    settings = runtime.settings.read_item(USER_ID, USER_ID)
    settings["settings"]["enable_agents"] = False
    runtime.settings.upsert_item(settings)
    changed = read_identity(reader)
    assert initial.user_id == changed.user_id == USER_ID
    assert initial.roles == changed.roles == ("User",)
    assert initial.user_enable_agents is True and changed.user_enable_agents is False
    runtime.world.assignments = []
    with pytest.raises(ResultUnavailableError):
        read_identity(reader)


def test_identity_does_not_coerce_non_mapping_settings_into_authority(external_root, monkeypatch):
    runtime = external_root
    read_settings = runtime.settings.read_item
    monkeypatch.setattr(
        runtime.settings, "read_item",
        lambda *args, **kwargs: list(read_settings(*args, **kwargs).items()),
    )
    with pytest.raises(ResultUnavailableError):
        read_identity(reader_for(runtime))


@pytest.mark.parametrize("change", ["deleted", "foreign", "missing_settings", "denied"])
def test_current_conversation_or_user_restriction_never_uses_saved_roles(external_root, change):
    runtime = external_root
    reader = reader_for(runtime)
    initial = read_identity(reader)
    assert initial.roles == ("User",)
    if change in ("deleted", "foreign"):
        conversation = runtime.conversations.read_item(CONVERSATION_ID, CONVERSATION_ID)
        if change == "deleted":
            conversation["orchestration_deleted"] = True
        else:
            conversation["user_id"] = "other-owner"
        runtime.conversations.upsert_item(conversation)
    elif change == "missing_settings":
        settings = runtime.settings.read_item(USER_ID, USER_ID)
        runtime.settings.delete_item(USER_ID, USER_ID, etag=settings["_etag"])
    else:
        settings = runtime.settings.read_item(USER_ID, USER_ID)
        settings["settings"]["access"] = {"status": "deny"}
        runtime.settings.upsert_item(settings)
    with pytest.raises(ResultUnavailableError):
        read_identity(reader)


@pytest.mark.parametrize("field", ["user_id", "conversation_id"])
def test_reader_rejects_another_actor_or_conversation_before_io(external_root, field):
    runtime = external_root
    reader = reader_for(runtime)
    arguments = {"user_id": USER_ID, "conversation_id": CONVERSATION_ID, field: "other"}
    with pytest.raises(ResultUnavailableError):
        reader(**arguments)
    runtime.client_factory.assert_not_called()
    runtime.settings_read.assert_not_called()
    assert runtime.world.adapter.requests == []


@pytest.mark.parametrize("error, code, retryable", [
    ("server_error", "external_identity_service_unavailable", True),
    ("temporarily_unavailable", "external_identity_service_unavailable", True),
    ("too_many_requests", "external_identity_throttled", True),
    ("unknown_error", "external_identity_response_invalid", False),
])
def test_token_service_failure_is_not_reported_as_role_revocation(external_root, error, code, retryable):
    runtime = external_root
    runtime.token.return_value = {"error": error, "error_description": "synthetic-private-error"}
    with pytest.raises(ExternalIdentityServiceError) as caught:
        read_identity(reader_for(runtime))
    runtime.token.assert_called_once_with(scopes=[runtime.world.scope])
    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert "synthetic-private-error" not in str(caught.value)
    assert runtime.world.adapter.requests == []


@pytest.mark.parametrize("error", ["invalid_client", "invalid_scope", "access_denied", "consent_required"])
def test_missing_application_permission_fails_without_interactive_fallback(external_root, error):
    runtime = external_root
    runtime.token.return_value = {"error": error, "error_description": "synthetic-private-error"}
    with pytest.raises(ResultUnavailableError) as caught:
        read_identity(reader_for(runtime))
    assert "synthetic-private-error" not in str(caught.value)
    assert runtime.world.adapter.requests == []


def test_token_network_timeout_is_a_safe_retryable_service_failure(external_root):
    runtime = external_root
    runtime.token.side_effect = Timeout("synthetic-private-error")
    with pytest.raises(ExternalIdentityServiceError) as caught:
        read_identity(reader_for(runtime))
    assert caught.value.code == "external_identity_timeout"
    assert caught.value.retryable is True
    assert "synthetic-private-error" not in str(caught.value)
    assert caught.value.__context__ is None


@pytest.mark.parametrize("store", ["conversations", "settings"])
def test_current_authorization_storage_outage_is_not_an_access_denial(external_root, store):
    runtime = external_root
    getattr(runtime, store).fail_reads = True
    with pytest.raises(ExternalIdentityServiceError) as caught:
        read_identity(reader_for(runtime))
    assert caught.value.code == "external_identity_service_unavailable"
    assert caught.value.retryable is True


def test_existing_auth_factory_keeps_its_default_arguments(external_root):
    runtime = external_root
    cache = object()
    application = runtime.auth._build_msal_app(cache=cache)
    assert application.acquire_token_for_client is runtime.token
    runtime.client_factory.assert_called_once_with(
        APP_ID, authority=runtime.auth.AUTHORITY,
        client_credential="synthetic-client-secret", token_cache=cache,
    )
