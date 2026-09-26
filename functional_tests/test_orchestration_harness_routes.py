# test_orchestration_harness_routes.py
"""
Real authenticated routes and bootstrap for orchestration file admission.
Version: 0.261.139
Implemented in: 0.261.127
Initial-claim timing coverage added in: 0.261.129
Auto-routing admission and content-review file visibility added in: 0.261.131
Single plan contract, no admission switch, legacy runs refused: 0.261.139

Only external settings/storage I/O is replaced. The production Flask routes,
Blueprint guards, result services and shared format registry run unchanged.
"""

import importlib
import json
import subprocess
import sys
import threading
import unicodedata
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import fitz
import pytest
from flask import Blueprint, Flask, session
from werkzeug.datastructures import MultiDict
from werkzeug.test import Client
from werkzeug.wrappers import Response

from content_screening.contracts import (
    DocumentHeldError, ScreeningConfigurationError,
    SourceAuthorityUnavailableError, SourceAuthorityUnverifiedError,
)
from test_support.offline_bootstrap import offline_app_imports
from test_support.orchestration_harness_execution import (
    HarnessEnvironment, compose_step, input_binding, render_step,
)
from test_support.orchestration_revisions import AtomicMemoryContainer


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
RETRY_ID = "e7d1160f-307e-4c9c-89de-a35c7bc5ae63"
OUTPUT_ID = "orender_" + "a" * 64
SOURCE_SERVICE_FAILURES = (
    "directory", "directory_invalid", "screening", "source_authority", "source_authority_invalid",
    "configuration", "configuration_invalid",
)


@pytest.fixture(scope="module")
def modules():
    before = set(sys.modules)
    with offline_app_imports() as environment:
        imported = SimpleNamespace(
            execution_loop=environment.loop,
            route=importlib.import_module("route_backend_orchestration"),
            bootstrap=importlib.import_module("functions_orchestration_bootstrap"),
            auth=importlib.import_module("functions_authentication"),
            config=importlib.import_module("config"),
            runs=importlib.import_module("functions_orchestration_runs"),
            artifacts=importlib.import_module("functions_orchestration_artifacts"),
        )
        previous_factory = imported.artifacts.configure_orchestration_artifact_service(None)
        try:
            yield imported
        finally:
            imported.artifacts.configure_orchestration_artifact_service(previous_factory)
        assert not environment.network_attempts
    for name in set(sys.modules) - before:
        path = getattr(sys.modules.get(name), "__file__", None)
        if path and Path(path).resolve().is_relative_to(APP):
            sys.modules.pop(name, None)


@pytest.fixture
def runtime(modules, monkeypatch):
    conversations = AtomicMemoryContainer("id")
    runs = AtomicMemoryContainer("conversation_id")
    results = AtomicMemoryContainer("run_id")
    messages = AtomicMemoryContainer("conversation_id")
    conversations.create_item({"id": "conversation", "user_id": "owner"})
    settings = {
        "enable_chat_orchestration": True,
        "max_generated_chat_artifact_size_mb": 1,
        "azure_openai_api_key": "private-setting-must-not-be-returned",
    }
    for module, name, value in (
        (modules.config, "cosmos_conversations_container", conversations),
        (modules.route, "cosmos_conversations_container", conversations),
        (modules.config, "cosmos_orchestration_runs_container", runs),
        (modules.runs, "cosmos_orchestration_runs_container", runs),
        (modules.config, "cosmos_personal_workflow_run_items_container", results),
        (modules.config, "cosmos_messages_container", messages),
    ):
        monkeypatch.setattr(module, name, value)
    monkeypatch.setattr(modules.route, "get_settings", lambda: dict(settings))
    monkeypatch.setattr(modules.bootstrap, "get_settings", lambda: dict(settings))
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="local-harness-test")
    blueprint = Blueprint("backend_orchestration", __name__)
    blueprint.before_request(modules.auth.user_required_blueprint())
    modules.route.register_route_backend_orchestration(blueprint)
    app.register_blueprint(blueprint)
    return SimpleNamespace(
        client=Client(app, Response), app=app, conversations=conversations,
        runs=runs, results=results, messages=messages, settings=settings, modules=modules,
    )


def login(runtime, *, user_id="owner", roles=("Admin",)):
    serializer = runtime.app.session_interface.get_signing_serializer(runtime.app)
    cookie = serializer.dumps({"user": {"oid": user_id, "roles": list(roles)}})
    runtime.client.set_cookie(runtime.app.config["SESSION_COOKIE_NAME"], cookie)


def catalog(runtime, **query):
    return runtime.client.get(
        "/api/v2/orchestration/export-catalog",
        query_string={"conversation_id": "conversation", **query},
    )


def test_catalog_requires_real_session_and_user_blueprint_role(runtime):
    anonymous = catalog(runtime)
    login(runtime, roles=())
    no_role = catalog(runtime)
    assert anonymous.status_code == 401
    assert no_role.status_code == 403
    assert not runtime.runs.items


def test_catalog_rechecks_conversation_owner_even_for_admin(runtime):
    login(runtime, user_id="someone-else")
    response = catalog(runtime)
    assert response.status_code == 404
    assert response.get_json() == {"error": "Conversation not found."}


def test_catalog_comes_from_shared_registry_without_settings(runtime):
    login(runtime)
    response = catalog(runtime)
    value = response.get_json()
    encoded = json.dumps(value)
    assert response.status_code == 200
    assert {entry["format_id"] for entry in value["formats"]} == {
        "csv", "xlsx", "docx", "pptx", "pdf", "json", "xml", "yaml", "md", "txt",
    }
    assert "private-setting-must-not-be-returned" not in encoded
    assert not runtime.results.items
    assert not runtime.messages.items


@pytest.mark.parametrize("saved_run", [False, True])
def test_catalog_does_not_advertise_formats_when_render_capability_is_disabled(runtime, saved_run):
    login(runtime)
    runtime.settings["chat_orchestration_enabled_capabilities"] = ["compose"]
    query = {}
    if saved_run:
        runtime.runs.create_item({
            "id": "saved-run", "run_id": "saved-run", "record_type": "orchestration_run",
            "conversation_id": "conversation", "user_id": "owner",
            "plan": {"planner_contract_version": 2, "steps": []},
        })
        query["run_id"] = "saved-run"
    response = catalog(runtime, **query)
    assert response.status_code == 403
    assert response.get_json() == {
        "error": "File rendering is not available for this conversation.",
        "code": "rendering_unavailable",
    }
    assert not runtime.results.items and not runtime.messages.items


@pytest.mark.parametrize("formats", [(), ("md",)])
def test_catalog_obeys_the_current_server_format_selection(runtime, monkeypatch, formats):
    login(runtime)
    services = runtime.modules.bootstrap.build_orchestration_services(
        "owner", "conversation", settings=runtime.settings,
    )
    admitted = [entry for entry in services.export_catalog() if entry["format_id"] in formats]
    monkeypatch.setattr(services, "export_catalog", lambda: deepcopy(admitted))
    monkeypatch.setattr(runtime.modules.route, "_orchestration_services", lambda *args, **kwargs: services)
    response = catalog(runtime)
    value = response.get_json()
    if formats:
        assert response.status_code == 200, value
        assert value["formats"] == admitted
    else:
        assert response.status_code == 403, value
        assert value["code"] == "rendering_unavailable"
    assert not runtime.runs.items and not runtime.results.items and not runtime.messages.items


def test_invalid_server_catalog_is_an_explicit_service_failure(runtime, monkeypatch):
    login(runtime)
    services = runtime.modules.bootstrap.build_orchestration_services(
        "owner", "conversation", settings=runtime.settings,
    )
    invalid = services.export_catalog()
    invalid[0]["media_type"] = "PRIVATE_INVALID_SERVER_METADATA"
    monkeypatch.setattr(services, "export_catalog", lambda: deepcopy(invalid))
    monkeypatch.setattr(runtime.modules.route, "_orchestration_services", lambda *args, **kwargs: services)
    response = catalog(runtime)
    value = response.get_json()
    assert response.status_code == 503, value
    assert value["code"] == "unavailable" and "formats" not in value
    assert "PRIVATE_INVALID_SERVER_METADATA" not in response.get_data(as_text=True)
    assert not runtime.runs.items and not runtime.results.items and not runtime.messages.items


def test_catalog_requires_actual_render_runtime(runtime, monkeypatch):
    login(runtime)
    rendering = importlib.import_module("functions_orchestration_rendering")
    monkeypatch.delattr(rendering, "resume_render_file", raising=False)
    response = catalog(runtime)
    assert response.status_code == 403
    assert response.get_json()["code"] == "rendering_unavailable"
    assert not runtime.runs.items and not runtime.results.items and not runtime.messages.items


def test_editor_catalog_hides_disabled_rendering_without_removing_saved_file_intent(runtime):
    runtime.settings["chat_orchestration_enabled_capabilities"] = ["compose"]
    plan = {
        "planner_contract_version": 2, "plan_id": "plan-1", "run_id": "saved-run",
        "conversation_id": "conversation", "turn_id": "turn-1", "revision": 0,
        "status": "awaiting_approval", "steps": [
            {
                "step_id": "draft", "capability_id": "compose", "role": "reason", "enabled": True,
                "depends_on": [], "inputs": {}, "outputs": [{"name": "report", "kind": "markdown-v1"}],
                "arguments": {"instruction": "Prepare a report."},
            },
            {
                "step_id": "file", "capability_id": "render_file", "role": "render", "enabled": True,
                "depends_on": ["draft"], "inputs": {
                    "source": {"binding": input_binding("draft", "report"), "allow_partial": False},
                },
                "outputs": [], "arguments": {
                    "file_name": "report.md", "output_format": "md", "profile": "prepared_text_v1",
                },
            },
        ],
    }
    record = runtime.runs.create_item({
        "id": "saved-run", "run_id": "saved-run", "record_type": "orchestration_run",
        "conversation_id": "conversation", "user_id": "owner", "turn_id": "turn-1",
        "revision": 0, "status": "awaiting_approval", "plan": plan,
    })
    before = deepcopy(runtime.runs.items)
    frame = runtime.modules.route._plan_editor_event(record, "owner")
    event = json.loads(frame.removeprefix("data:").strip())
    options = runtime.modules.route._plan_result_options(record, "owner", runtime.settings)
    after = deepcopy(runtime.runs.items)
    assert event["export_catalog"] == []
    assert event["plan"]["steps"][1]["arguments"] == plan["steps"][1]["arguments"]
    assert event["plan"]["steps"][1]["inputs"] == plan["steps"][1]["inputs"]
    assert len(options["export_catalog"]) == 10
    assert before == after and not runtime.results.items and not runtime.messages.items


def test_bootstrap_binds_the_real_native_request_builder_without_submitting_work(runtime):
    native = importlib.import_module("functions_orchestration_native_results")
    service = runtime.modules.bootstrap.build_orchestration_services(
        "owner", "conversation", settings=runtime.settings,
    )
    bridge = service.native_bridge_for_step({
        "capability_id": "tabular_analyze",
        "arguments": {
            "question": "Summarize the complete selected table.",
            "document_ids": ["selected-document"],
            "native_operation": "analysis",
        },
    }, None)
    assert service.native_bridge_for_step is runtime.modules.bootstrap.native_bridge_for_step
    assert bridge.request_builder is native.build_native_orchestration_request
    assert bridge.native_operation == "analysis"
    assert bridge.task_type == "hierarchical_analysis"
    assert bridge.source_policy == "current"
    assert bridge.input_fingerprint_for_step is None
    assert bridge.model_resolver is None
    assert [(output.name, output.kind) for output in bridge.output_specs] == [
        ("analysis", "structured-v1"), ("coverage", "structured-v1"),
    ]
    assert not runtime.runs.items
    assert not runtime.results.items
    assert not runtime.messages.items


def test_bootstrap_binds_strict_source_callbacks_without_source_io(runtime):
    strict = importlib.import_module("functions_orchestration_source_access")
    service = runtime.modules.bootstrap.build_orchestration_services(
        "owner", "conversation", settings=runtime.settings,
    )
    assert service.results.access.source_resolver is strict.resolve_orchestration_source_manifest
    assert service.results.access.source_metadata_reader is strict.read_orchestration_source_metadata
    assert not runtime.runs.items and not runtime.results.items and not runtime.messages.items


@pytest.mark.parametrize("failure,expected_type", [
    (TimeoutError("PRIVATE source backend timeout"), SourceAuthorityUnavailableError),
    (ValueError("PRIVATE malformed authority"), SourceAuthorityUnverifiedError),
    (ScreeningConfigurationError("PRIVATE screening configuration"), ScreeningConfigurationError),
    (PermissionError("PRIVATE source denial"), PermissionError),
])
def test_bootstrap_source_resolver_keeps_operational_failure_distinct_from_denial(runtime, failure, expected_type):
    service = runtime.modules.bootstrap.build_orchestration_services(
        "owner", "conversation", settings=runtime.settings,
    )
    resolver = Mock(side_effect=failure)
    with pytest.raises(expected_type):
        service.results.access.source_resolver(
            ["document"], user_id="owner", conversation_id="conversation", context_resolver=resolver,
        )
    assert resolver.call_count == 1
    assert not runtime.runs.items and not runtime.results.items and not runtime.messages.items


def test_bootstrap_metadata_reader_rechecks_real_owner_and_preserves_storage_failure(runtime, monkeypatch):
    documents = AtomicMemoryContainer("id")
    document = {"id": "document", "user_id": "owner", "filename": "document.txt"}
    documents.create_item(document)
    monkeypatch.setattr(runtime.modules.config, "cosmos_user_documents_container", documents)
    service = runtime.modules.bootstrap.build_orchestration_services(
        "owner", "conversation", settings=runtime.settings,
    )
    reader = service.results.access.source_metadata_reader
    current = reader("document", "owner")
    document["user_id"] = "another-owner"
    documents.upsert_item(document)
    with pytest.raises(PermissionError):
        reader("document", "owner")
    monkeypatch.setattr(documents, "read_item", Mock(side_effect=TimeoutError("PRIVATE current metadata outage")))
    with pytest.raises(SourceAuthorityUnavailableError):
        reader("document", "owner")
    assert current["id"] == "document" and current["user_id"] == "owner"


def test_native_discovery_uses_the_injected_factory_without_invoking_it(runtime):
    factory = Mock(side_effect=AssertionError("Discovery must not build or execute native work."))
    route = runtime.modules.route
    legacy = route._capability_request_context("owner", {}, "Compute selected rows.", [])
    bound = route._capability_request_context(
        "owner", {}, "Compute selected rows.", [], native_bridge_for_step=factory,
    )
    settings = {**runtime.settings, "enable_user_workspace": True}
    unavailable = route.resolve_available_capability_ids(
        settings, candidate_ids={"tabular_analyze"}, request_context=legacy, contract_version=2,
    )
    available = route.resolve_available_capability_ids(
        settings, candidate_ids={"tabular_analyze"}, request_context=bound, contract_version=2,
    )
    assert "native_bridge_for_step" not in legacy
    assert bound["native_bridge_for_step"] is factory
    assert "tabular_analyze" not in unavailable
    assert available == ["tabular_analyze"]
    factory.assert_not_called()


def test_external_discovery_requires_all_actual_server_callbacks_without_invoking_them(runtime):
    route = runtime.modules.route
    callbacks = {
        name: Mock(side_effect=AssertionError("Discovery must not acquire or authorize a source."))
        for name in (
            "external_source_preflight",
            "external_source_admission", "external_source_authorizer",
            "capture_external_source_configuration",
        )
    }
    legacy = route._capability_request_context("owner", {}, "Read the source.", [])
    context = route._capability_request_context("owner", {}, "Read the source.", [], **callbacks)
    for name, callback in callbacks.items():
        assert name not in legacy and context[name] is callback
        callback.assert_not_called()


@pytest.mark.parametrize("missing", [
    "external_source_preflight", "external_source_admission",
    "external_source_authorizer", "capture_external_source_configuration",
])
@pytest.mark.parametrize("value", [None, True, False, "configured", {}])
def test_external_discovery_rejects_partial_or_untrusted_bindings(runtime, missing, value):
    callbacks = {
        name: Mock(side_effect=AssertionError("Invalid discovery must not call a source service."))
        for name in (
            "external_source_preflight",
            "external_source_admission", "external_source_authorizer",
            "capture_external_source_configuration",
        )
    }
    callbacks[missing] = value
    with pytest.raises(ValueError, match="Complete server external-source"):
        runtime.modules.route._capability_request_context(
            "owner", {}, "Read the source.", [], **callbacks,
        )


def test_render_discovery_uses_only_the_actual_actor_bound_service(runtime):
    route = runtime.modules.route
    services = runtime.modules.bootstrap.build_orchestration_services(
        "owner", "conversation", settings=runtime.settings,
    )
    legacy = route._capability_request_context("owner", {}, "Create a file.", [])
    bound = route._capability_request_context(
        "owner", {}, "Create a file.", [], rendering_service=services.rendering,
    )
    with pytest.raises(ValueError, match="actor-bound"):
        route._capability_request_context(
            "another-owner", {}, "Create a file.", [], rendering_service=services.rendering,
        )
    assert "rendering_service" not in legacy
    assert bound["rendering_service"] is services.rendering
    assert not runtime.runs.items and not runtime.results.items and not runtime.messages.items


@pytest.mark.parametrize("service", [True, False, "render", {}, lambda: None])
def test_render_discovery_rejects_flags_descriptors_and_unverified_factories(runtime, service):
    with pytest.raises(ValueError, match="server rendering service"):
        runtime.modules.route._capability_request_context(
            "owner", {}, "Create a file.", [], rendering_service=service,
        )


def test_root_output_authorization_receives_the_same_initialized_service(runtime, monkeypatch):
    authorize = Mock(return_value=True)
    monkeypatch.setattr(runtime.modules.bootstrap, "_authorize_render_output", authorize)
    services = runtime.modules.bootstrap.build_orchestration_services(
        "owner", "conversation", settings=runtime.settings,
    )
    authorize.assert_not_called()
    record = {"user_id": "owner", "conversation_id": "conversation"}
    authorized = services.rendering.authorize_execution(record, operation="download")
    assert authorized is True
    authorize.assert_called_once_with(
        record, operation="download", rendering_service=services.rendering,
    )
    assert not runtime.runs.items and not runtime.results.items and not runtime.messages.items


@pytest.mark.parametrize("field,value", [
    ("user_id", "another-owner"), ("conversation_id", "another-conversation"),
])
def test_root_output_authorization_cannot_escape_its_bound_actor_or_conversation(runtime, monkeypatch, field, value):
    root = runtime.modules.bootstrap
    services = root.build_orchestration_services("owner", "conversation", settings=runtime.settings)
    read_conversation = Mock(side_effect=AssertionError("A foreign scope must fail before storage access."))
    monkeypatch.setattr(root, "read_owned_conversation", read_conversation)
    record = {"user_id": "owner", "conversation_id": "conversation", field: value}
    with pytest.raises(root.OutputUnavailableError):
        services.rendering.authorize_execution(record, operation="download")
    read_conversation.assert_not_called()


@pytest.mark.parametrize("external_mode", ["none", "read_only", "complete"])
def test_plan_edit_options_inject_the_actual_native_factory(runtime, monkeypatch, external_mode):
    record = {"conversation_id": "conversation", "plan": {"planner_contract_version": 2}}
    original = json.dumps(record, sort_keys=True)
    services = runtime.modules.bootstrap.build_orchestration_services(
        "owner", "conversation", settings=runtime.settings,
    )
    callbacks = {
        name: Mock(side_effect=AssertionError("Editing must not invoke external acquisition."))
        for name in (
            "external_source_preflight",
            "external_source_admission", "external_source_authorizer",
            "capture_external_source_configuration",
        )
    }
    for name, callback in callbacks.items():
        owner = services.results.access if name == "external_source_authorizer" else services
        active = external_mode == "complete" or (
            external_mode == "read_only" and name == "external_source_authorizer"
        )
        monkeypatch.setattr(owner, name, callback if active else None)
    factory = Mock(return_value=services)
    monkeypatch.setattr(runtime.modules.route, "_orchestration_services", factory)
    options = runtime.modules.route._plan_result_options(record, "owner", runtime.settings)
    current = json.dumps(record, sort_keys=True)
    assert options["native_bridge_for_step"] is runtime.modules.bootstrap.native_bridge_for_step
    assert options["rendering_service"] is services.rendering
    assert callable(options["result_alias_resolver"])
    assert options["export_catalog"]
    assert options["composition_profiles"]
    for name, callback in callbacks.items():
        if external_mode == "complete":
            assert options[name] is callback
        else:
            assert name not in options
        callback.assert_not_called()
    assert current == original
    assert not runtime.runs.items
    assert not runtime.results.items
    factory.assert_called_once_with("owner", "conversation", settings=runtime.settings)


@pytest.mark.parametrize("factory", [True, False, "native", {}])
def test_native_discovery_rejects_noncallable_readiness(runtime, factory):
    with pytest.raises(ValueError, match="server native bridge"):
        runtime.modules.route._capability_request_context(
            "owner", {}, "Compute selected rows.", [], native_bridge_for_step=factory,
        )


def test_new_catalog_requires_chat_orchestration(runtime):
    login(runtime)
    runtime.settings["enable_chat_orchestration"] = False
    response = catalog(runtime)
    assert response.status_code == 403
    assert response.get_json()["code"] == "disabled"
    assert runtime.runs.items == {} and runtime.messages.items == {}


def test_new_catalog_needs_no_other_switch(runtime):
    login(runtime)
    runtime.settings.pop("enable_chat_orchestration_harness", None)
    response = catalog(runtime)
    assert response.status_code == 200
    assert response.get_json()["formats"]


def test_saved_run_catalog_remains_readable(runtime):
    login(runtime)
    record = {
        "id": "saved-run", "run_id": "saved-run", "record_type": "orchestration_run",
        "conversation_id": "conversation", "user_id": "owner",
        "plan": {"planner_contract_version": 2, "steps": []},
    }
    runtime.runs.create_item(record)
    response = catalog(runtime, run_id="saved-run")
    stored = runtime.runs.read_item("saved-run", "conversation")
    assert response.status_code == 200
    assert stored["plan"] == record["plan"]


def test_legacy_or_foreign_run_cannot_admit_a_file_catalog(runtime):
    login(runtime)
    runtime.runs.create_item({
        "id": "old-run", "run_id": "old-run", "record_type": "orchestration_run",
        "conversation_id": "conversation", "user_id": "owner",
        "plan": {"planner_contract_version": 1, "steps": []},
    })
    runtime.runs.create_item({
        "id": "foreign-run", "run_id": "foreign-run", "record_type": "orchestration_run",
        "conversation_id": "conversation", "user_id": "other",
        "plan": {"planner_contract_version": 2, "steps": []},
    })
    legacy = catalog(runtime, run_id="old-run")
    foreign = catalog(runtime, run_id="foreign-run")
    assert legacy.status_code == 409
    assert legacy.get_json() == {
        "error": runtime.modules.route.LEGACY_PLAN_MESSAGE, "code": "legacy_plan",
    }
    assert foreign.status_code == 404


def test_saved_run_execution_uses_the_headless_path(runtime, monkeypatch):
    login(runtime)
    plan = {
        "planner_contract_version": 2,
        "steps": [{"step_id": "answer", "capability_id": "compose", "enabled": True}],
    }
    runtime.runs.create_item({
        "id": "saved-run", "run_id": "saved-run", "record_type": "orchestration_run",
        "conversation_id": "conversation", "user_id": "owner", "status": "awaiting_approval",
        "plan": plan, "user_message": "Prepare an answer", "seeds": {},
    })
    route = runtime.modules.route
    native_factory = Mock(side_effect=AssertionError("HTTP admission must not submit native work."))
    services = runtime.modules.bootstrap.build_orchestration_services(
        "owner", "conversation", settings=runtime.settings,
    )
    monkeypatch.setattr(services, "native_bridge_for_step", native_factory)
    prepared = Mock(return_value=Response('{"harness":true}', status=202, mimetype="application/json"))
    available = Mock(return_value=["compose"])
    route_models = Mock(side_effect=AssertionError("The run route must not set up models itself."))
    monkeypatch.setattr(route, "_conversation_context_for_run", lambda *args: {"messages": []})
    monkeypatch.setattr(route, "_orchestration_services", lambda *args, **kwargs: services)
    monkeypatch.setattr(route, "_request_identity", lambda *args, **kwargs: {"user_enable_agents": False})
    monkeypatch.setattr(route, "capture_execution_identity", lambda *args: None)
    monkeypatch.setattr(route, "resolve_action_catalog", lambda *args, **kwargs: [])
    monkeypatch.setattr(route, "apply_plan_edits", lambda *args, **kwargs: plan)
    monkeypatch.setattr(route, "resolve_available_capability_ids", available)
    monkeypatch.setattr(route, "resolve_orchestration_model", route_models)
    monkeypatch.setattr(route, "_prepare_execution_stream", prepared)
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": "saved-run", "conversation_id": "conversation", "user_id": "forged",
    })
    assert response.status_code == 202
    assert response.get_json() == {"harness": True}
    assert prepared.call_args.args[0]["plan"]["planner_contract_version"] == 2
    assert prepared.call_args.args[2] == "owner"
    assert prepared.call_args.args[-1] is services
    assert available.call_args.kwargs["contract_version"] == 2
    assert available.call_args.kwargs["request_context"]["native_bridge_for_step"] is native_factory
    assert available.call_args.kwargs["request_context"]["rendering_service"] is services.rendering
    native_factory.assert_not_called()
    route_models.assert_not_called()


def test_unknown_saved_contract_is_neither_run_nor_called_legacy(runtime):
    login(runtime)
    runtime.runs.create_item({
        "id": "unknown-run", "run_id": "unknown-run", "record_type": "orchestration_run",
        "conversation_id": "conversation", "user_id": "owner", "status": "awaiting_approval",
        "plan": {"planner_contract_version": 3, "steps": []},
    })
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": "unknown-run", "conversation_id": "conversation",
    })
    assert response.status_code == 409
    assert response.get_json()["code"] == "plan_changed"


@pytest.mark.parametrize("selection", [
    ["compose"], ["render_file"], ["compose", "render_file"],
    ["document_analyze", "render_file"], [],
])
def test_both_admin_normalizers_store_exactly_the_selected_capabilities(modules, selection):
    admin = importlib.import_module("route_frontend_admin_settings")
    fields = importlib.import_module("admin_settings_fields")
    key = "chat_orchestration_enabled_capabilities"
    form = MultiDict((key, value) for value in selection)
    classic = admin.normalize_chat_orchestration_settings(form)
    typed, errors, _warnings = fields.normalize_admin_settings_updates({key: selection}, {})
    assert errors == {}
    assert typed[key] == selection
    assert set(classic[key]) == set(selection)
    assert "enable_chat_orchestration_harness" not in classic
    assert "enable_chat_orchestration_harness" not in typed


def test_admin_projection_lists_every_registered_capability(modules):
    admin = importlib.import_module("route_frontend_admin_settings")
    registry = importlib.import_module("functions_orchestration_registry")
    projection = admin.orchestration_admin_capabilities()
    identifiers = [capability["id"] for capability in projection]
    compose = next(capability for capability in projection if capability["id"] == "compose")
    assert identifiers == registry.all_capability_ids()
    assert "respond" not in identifiers and len(identifiers) == len(set(identifiers))
    assert compose["role"] == "reason"
    assert all(set(capability) == {"id", "label", "role", "summary", "cost"} for capability in projection)
    assert "native_bridge_for_step" not in json.dumps(projection)


def test_execution_storage_outage_is_not_reported_as_a_missing_run(runtime):
    login(runtime)
    runtime.runs.fail_reads = True
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": "saved-run", "conversation_id": "conversation",
    })
    assert response.status_code == 503
    assert "Private test" not in response.get_data(as_text=True)


@pytest.fixture
def real_http_harness(modules, monkeypatch):
    harness = HarnessEnvironment(monkeypatch)
    for name, value in (
        ("cosmos_conversations_container", harness.conversations),
        ("cosmos_messages_container", harness.messages),
        ("get_settings", lambda: dict(harness.settings)),
        ("get_user_settings", lambda user_id: {"settings": {}}),
    ):
        monkeypatch.setattr(modules.route, name, value)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="real-http-harness-test")
    blueprint = Blueprint("backend_orchestration", __name__)
    blueprint.before_request(modules.auth.user_required_blueprint())
    modules.route.register_route_backend_orchestration(blueprint)
    app.register_blueprint(blueprint)
    runtime = SimpleNamespace(app=app, client=Client(app, Response), harness=harness)
    login(runtime)
    return runtime


def test_real_http_plans_then_executes_without_any_admission_switch(real_http_harness, monkeypatch):
    runtime = real_http_harness
    harness = runtime.harness
    harness.settings.pop("enable_chat_orchestration_harness", None)
    harness.settings.update(enable_user_workspace=False, chat_orchestration_total_timeout_seconds=173)
    initial_claims = []
    prepare_execution = harness.execution.prepare_harness_execution

    def observe_claim(record, **kwargs):
        saved = harness.runs.read_item(record["id"], record["conversation_id"])
        initial_claims.append(deepcopy(saved))
        return prepare_execution(record, **kwargs)

    monkeypatch.setattr(harness.execution, "prepare_harness_execution", observe_claim)
    request = "Write an original short note and save the same note as Markdown and PDF."
    content = "One complete draft for the two approved files."
    harness.replies = [
        json.dumps({
            "relationship": "new_topic", "resolved_message": request,
            "message_ids": [], "requires_retrieval": False, "clarification": "",
        }),
        json.dumps({
            "kind": "plan",
            "steps": [
                compose_step(),
                render_step("markdown_file", "md"),
                render_step("pdf_file", "pdf", profile="prepared_report_v1"),
            ],
            "final_response": input_binding("prepare"),
        }),
        content,
    ]
    planned = runtime.client.post("/api/v2/orchestration/plan", json={
        "conversation_id": "conversation-1", "turn_id": "new-preview-turn",
        "message": request,
        "approval_mode": "manual", "planner_contract_version": 1,
    }, buffered=True)
    planning_frames = [
        json.loads(frame.partition("data:")[2].strip())
        for frame in planned.get_data(as_text=True).split("\n\n") if frame.startswith("data:")
    ]
    assert planned.status_code == 200 and "plan" in planning_frames[-1], planning_frames
    plan = planning_frames[-1]["plan"]
    record = harness.runs.read_item(plan["run_id"], "conversation-1")
    assert plan["planner_contract_version"] == 2 and record["plan"] == plan
    assert [step["capability_id"] for step in plan["steps"]] == ["compose", "render_file", "render_file"]
    assert len(planning_frames[-1]["export_catalog"]) == 10
    assert len(harness.model_calls) == 2 and harness.blobs.file_uploads == 0
    assert harness.assistant_messages() == []

    executed = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": "conversation-1", "run_id": plan["run_id"],
    }, buffered=True)
    frames = [
        json.loads(frame.partition("data:")[2].strip())
        for frame in executed.get_data(as_text=True).split("\n\n") if frame.startswith("data:")
    ]
    saved = harness.runs.read_item(plan["run_id"], "conversation-1")
    assert executed.status_code == 200 and frames[-1]["status"] == saved["status"] == "completed", frames
    assert len(initial_claims) == 1
    claimed = initial_claims[0]
    started = datetime.fromisoformat(claimed["started_at"])
    deadline = datetime.fromisoformat(claimed["execution_deadline_at"])
    assert (deadline - started).total_seconds() == 173
    assert saved["started_at"] == claimed["started_at"]
    assert saved["execution_deadline_at"] == claimed["execution_deadline_at"]
    assert len(harness.model_calls) == 3 and harness.blobs.file_uploads == 2
    assert frames[-1]["full_content"].startswith(content) and len(harness.assistant_messages()) == 1
    services = harness.services()
    with harness.publication_only(services):
        detail = runtime.client.get(
            f"/api/v2/orchestration/runs/{plan['run_id']}",
            query_string={"conversation_id": "conversation-1"},
        )
        current = detail.get_json()
        assert detail.status_code == 200 and len(current["run"]["generated_artifacts"]) == 2
        for output in current["run"]["outputs"]:
            with services.rendering.open_download(output["output_id"]) as stream:
                payload = stream.read()
            assert output["state"] == "completed" and len(payload) == output["size_bytes"]
    assert len(harness.model_calls) == 3 and harness.blobs.file_uploads == 2
    assert all(client.closed for client in harness.clients)


def test_real_http_execution_persists_one_source_free_answer_without_files(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    record = harness.create(
        replies=["The complete retained answer."],
        final_response=input_binding("prepare"),
    )
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": record["id"], "conversation_id": "conversation-1",
    }, buffered=True)
    frames = [
        json.loads(frame.partition("data:")[2].strip())
        for frame in response.get_data(as_text=True).split("\n\n")
        if frame.startswith("data:")
    ]
    saved = harness.read()
    messages = harness.assistant_messages()
    assert response.status_code == 200
    assert frames[-1]["status"] == saved["status"] == "completed", frames
    assert frames[-1]["full_content"] == messages[0]["content"] == "The complete retained answer."
    assert frames[-1]["message_id"] == messages[0]["id"]
    assert frames[-1]["outputs"] == [] and frames[-1]["generated_artifacts"] == []
    assert len(messages) == len(harness.model_calls) == 1
    assert harness.blobs.file_uploads == 0
    assert saved["execution_lease"] is None
    assert all(client.closed for client in harness.clients)


def test_read_only_retry_context_keeps_initialized_external_bindings_without_effects(
    real_http_harness, modules, monkeypatch,
):
    runtime = real_http_harness
    harness = runtime.harness
    record = harness.create(final_response=input_binding("prepare"))
    original = deepcopy(record)
    services = harness.services()
    callbacks = {
        name: Mock(side_effect=AssertionError("Read-only retry validation must not acquire sources."))
        for name in (
            "external_source_preflight",
            "external_source_admission", "external_source_authorizer",
            "capture_external_source_configuration",
        )
    }
    for name, callback in callbacks.items():
        owner = services.results.access if name == "external_source_authorizer" else services
        monkeypatch.setattr(owner, name, callback)
    monkeypatch.setattr(services, "export_catalog", lambda: [])
    monkeypatch.setattr(modules.route, "_orchestration_services", lambda *args, **kwargs: services)
    validator = Mock(return_value={"verified": True})
    monkeypatch.setattr(modules.route, "validate_resume", validator)
    with runtime.app.test_request_context():
        session["user"] = {"oid": "owner", "roles": ["Admin"]}
        result = modules.route._validate_retry_context(record, "owner", harness.settings)
    context = validator.call_args.args[1]
    assert result == {"verified": True}
    assert context.result_service is services.results
    assert context.export_catalog == []
    assert context.external_source_admission is callbacks["external_source_admission"]
    assert context.external_source_preflight is callbacks["external_source_preflight"]
    assert context.capture_external_source_configuration is callbacks["capture_external_source_configuration"]
    for callback in callbacks.values():
        callback.assert_not_called()
    assert record == original
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0
    assert all(client.closed for client in harness.clients)


def test_real_http_execution_renders_two_files_from_one_retained_result(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    content = "Complete caf\u00e9 findings.\nThe original last line."
    record = harness.create(
        steps=[
            compose_step(),
            render_step("markdown_file", "md"),
            render_step("pdf_file", "pdf", profile="prepared_report_v1"),
        ],
        replies=[content], final_response=input_binding("prepare"),
    )
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": record["id"], "conversation_id": "conversation-1",
    }, buffered=True)
    frames = [
        json.loads(frame.partition("data:")[2].strip())
        for frame in response.get_data(as_text=True).split("\n\n") if frame.startswith("data:")
    ]
    saved = harness.read()
    assert response.status_code == 200
    assert frames[-1]["status"] == saved["status"] == "completed", frames
    message = harness.messages.read_item(frames[-1]["message_id"], "conversation-1")
    assert content in message["content"]
    assert len(frames[-1]["outputs"]) == len(message["generated_artifacts"]) == 2
    assert len(harness.model_calls) == 1 and harness.blobs.file_uploads == 2

    services = harness.services()
    screening = importlib.import_module("content_screening.access")
    with harness.publication_only(services):
        detail = runtime.client.get(
            f"/api/v2/orchestration/runs/{record['id']}",
            query_string={"conversation_id": "conversation-1"},
        )
        current = detail.get_json()
        assert detail.status_code == 200, current
        outputs = current["run"]["outputs"]
        assert len(outputs) == current["run"]["artifact_count"] == 2
        assert len(current["run"]["generated_artifacts"]) == 2
        with runtime.app.test_request_context():
            history = screening.public_history_messages([message], "owner")
        stored_message = harness.messages.read_item(message["id"], "conversation-1")
        assert history[0]["metadata"]["orchestration"]["outputs"] == outputs
        assert history[0]["generated_artifacts"] == current["run"]["generated_artifacts"]
        assert stored_message == message
        for output in outputs:
            with services.rendering.open_download(output["output_id"]) as stream:
                downloaded = stream.read()
            assert output["state"] == "completed" and output["available"] is True
            assert output["character_count"] == len(content)
            assert output["size_bytes"] == len(downloaded)
            if output["output_format"] == "md":
                assert downloaded == content.encode("utf-8")
            else:
                with fitz.open(stream=downloaded, filetype="pdf") as document:
                    text = unicodedata.normalize("NFKC", "".join(page.get_text() for page in document))
                assert "Complete caf\u00e9 findings." in text
                assert "The original last line." in text
    assert len(harness.model_calls) == 1 and harness.blobs.file_uploads == 2
    assert saved["execution_lease"] is None
    assert all(client.closed for client in harness.clients)


@pytest.mark.parametrize("boundary", ["validation", "claim"])
@pytest.mark.parametrize("catalog_mode", ["empty", "different", "invalid"])
def test_real_http_rejects_removed_render_pairs_before_claiming_or_generating(
    real_http_harness, modules, monkeypatch, boundary, catalog_mode,
):
    runtime = real_http_harness
    harness = runtime.harness
    record = harness.create(
        steps=[compose_step(), render_step("markdown_file", "md")],
        replies=["This draft must not be generated."], final_response=input_binding("prepare"),
    )
    original = deepcopy(harness.read())
    services = harness.services()
    canonical = services.export_catalog()
    if catalog_mode == "invalid":
        admitted = deepcopy(canonical)
        admitted[0]["media_type"] = "PRIVATE_INVALID_SERVER_METADATA"
    else:
        admitted = [
            entry for entry in canonical
            if catalog_mode == "different" and entry["format_id"] == "pdf"
        ]
    monkeypatch.setattr(modules.route, "_orchestration_services", lambda *args, **kwargs: services)
    if boundary == "validation":
        monkeypatch.setattr(services, "export_catalog", lambda: deepcopy(admitted))
    else:
        prepare = modules.route._prepare_execution_stream

        def narrowed_before_claim(*args, **kwargs):
            monkeypatch.setattr(services, "export_catalog", lambda: deepcopy(admitted))
            return prepare(*args, **kwargs)

        monkeypatch.setattr(modules.route, "_prepare_execution_stream", narrowed_before_claim)
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": record["id"], "conversation_id": "conversation-1",
    }, buffered=True)
    saved = harness.read()
    expected_status = 503 if catalog_mode == "invalid" else 409
    assert response.status_code == expected_status, response.get_json(silent=True) or saved["status"]
    assert "PRIVATE_INVALID_SERVER_METADATA" not in response.get_data(as_text=True)
    assert saved == original
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0


@pytest.mark.parametrize("stop_requested", [False, True])
def test_real_http_pending_file_preserves_its_committed_sibling(real_http_harness, stop_requested):
    runtime = real_http_harness
    harness = runtime.harness
    uploads = 0

    def fail_second_upload():
        nonlocal uploads
        uploads += 1
        if uploads == 1:
            harness.blobs.before_file_upload = fail_second_upload
            return
        raise ConnectionError("PRIVATE_SECOND_FILE_UPLOAD_OUTAGE")

    harness.blobs.before_file_upload = fail_second_upload
    record = harness.create(
        steps=[
            compose_step(), render_step("markdown_file", "md"),
            render_step("pdf_file", "pdf", profile="prepared_report_v1"),
        ],
        replies=["One complete retained draft."], final_response=input_binding("prepare"),
    )
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": record["id"], "conversation_id": "conversation-1",
    }, buffered=True)
    body = response.get_data(as_text=True)
    frames = [
        json.loads(frame.partition("data:")[2].strip())
        for frame in body.split("\n\n") if frame.startswith("data:")
    ]
    saved = harness.read()
    assert response.status_code == 200
    assert frames[-1]["status"] == saved["status"] == "waiting", frames
    assert "PRIVATE_SECOND_FILE_UPLOAD_OUTAGE" not in body
    assert len(harness.model_calls) == 1 and uploads == 2 and harness.blobs.file_uploads == 1

    services = harness.services()
    with harness.publication_only(services):
        detail = runtime.client.get(
            f"/api/v2/orchestration/runs/{record['id']}",
            query_string={"conversation_id": "conversation-1"},
        )
        current = detail.get_json()
        assert detail.status_code == 200, current
        outputs = {output["output_format"]: output for output in current["run"]["outputs"]}
        assert outputs["md"]["state"] == "completed" and outputs["md"]["available"] is True
        assert outputs["pdf"]["state"] == "retry_scheduled" and outputs["pdf"]["available"] is True
        assert outputs["pdf"]["artifact_message_id"] is None
        assert outputs["pdf"]["automatic_attempts"] == outputs["pdf"]["attempt_count"] == 2
        assert outputs["pdf"]["next_retry_at"] and outputs["pdf"]["can_retry"] is False
        assert current["run"]["artifact_count"] == len(current["run"]["generated_artifacts"]) == 1
        pending = services.outputs.get(outputs["pdf"]["output_id"])
        assert [attempt["state"] for attempt in pending["attempts"]] == ["failed", "admitted"]
        assert pending["attempts"][-1]["started_at"] is None
        with services.rendering.open_download(outputs["md"]["output_id"]) as stream:
            downloaded = stream.read()
    assert downloaded == b"One complete retained draft."
    assert len(harness.model_calls) == 1 and harness.blobs.file_uploads == 1
    assert saved["execution_lease"] is None
    if stop_requested:
        stopped = runtime.client.post(
            f"/api/v2/orchestration/cancel/{record['id']}",
            json={"conversation_id": "conversation-1"},
        )
        stopped_body = stopped.get_json()
        assert stopped.status_code == 200, stopped_body
        fresh = harness.services()
        with harness.publication_only(fresh):
            preserved = fresh.rendering.read(outputs["md"]["output_id"])
            with fresh.rendering.open_download(outputs["md"]["output_id"]) as stream:
                retained = stream.read()
        assert preserved["state"] == "completed" and preserved["available"] is True
        assert retained == downloaded
        assert len(harness.model_calls) == 1 and harness.blobs.file_uploads == 1


def test_real_http_file_reads_recheck_the_current_approved_filename(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    record = harness.create(
        steps=[
            compose_step(), render_step("markdown_file", "md"),
            render_step("pdf_file", "pdf", profile="prepared_report_v1"),
        ],
        replies=["Retained file-name binding."], final_response=input_binding("prepare"),
    )
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": record["id"], "conversation_id": "conversation-1",
    }, buffered=True)
    saved = harness.read()
    assert response.status_code == 200 and saved["status"] == "completed"
    markdown_step = next(step for step in saved["plan"]["steps"] if step["step_id"] == "markdown_file")
    markdown_step["arguments"]["file_name"] = "a-different-approved-file.md"
    harness.runs.upsert_item(saved)

    services = harness.services()
    with harness.publication_only(services):
        current = services.rendering.list_public_outputs(record["id"])
        cards = services.rendering.committed_artifacts(record["id"])
        outputs = {output["output_format"]: output for output in current}
        assert outputs["md"]["state"] == "completed" and outputs["md"]["available"] is False
        assert outputs["md"]["error_code"] == "output_plan_changed"
        assert outputs["md"]["artifact_message_id"] is None
        assert outputs["pdf"]["state"] == "completed" and outputs["pdf"]["available"] is True
        assert [card["output_format"] for card in cards] == ["pdf"]
        with pytest.raises(harness.bootstrap.OutputUnavailableError):
            with services.rendering.open_download(outputs["md"]["output_id"]):
                raise AssertionError("A file no longer matching the approved request was readable.")
    assert len(harness.model_calls) == 1 and harness.blobs.file_uploads == 2


@pytest.mark.parametrize("persist_failure", [False, True])
def test_real_http_preparation_failure_only_streams_confirmed_outcomes(
    real_http_harness, monkeypatch, persist_failure,
):
    runtime = real_http_harness
    harness = runtime.harness
    record = harness.create(final_response=input_binding("prepare"))

    def failed_model_allocation(**kwargs):
        if persist_failure:
            harness.runs.fail_writes = True
        raise ConnectionError("PRIVATE_MODEL_ALLOCATION_DETAILS")

    monkeypatch.setattr(harness.planner, "AzureOpenAI", failed_model_allocation)
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": record["id"], "conversation_id": "conversation-1",
    }, buffered=True)
    saved = harness.read()
    messages = harness.assistant_messages()
    body = response.get_data(as_text=True)
    assert "PRIVATE_MODEL_ALLOCATION_DETAILS" not in body
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0
    if persist_failure:
        assert response.status_code == 503
        assert saved["status"] == "running" and messages == []
        assert response.get_json()["code"]
    else:
        frames = [
            json.loads(frame.partition("data:")[2].strip())
            for frame in body.split("\n\n") if frame.startswith("data:")
        ]
        assert response.status_code == 200
        assert frames[-1]["status"] == saved["status"] == "failed"
        assert frames[-1]["message_saved"] is True and len(messages) == 1
        assert frames[-1]["message_id"] == messages[0]["id"]
        assert saved["execution_lease"] is None


@pytest.fixture
def retry_runtime(runtime, monkeypatch):
    runtime.runs.create_item({
        "id": "saved-run", "run_id": "saved-run", "record_type": "orchestration_run",
        "conversation_id": "conversation", "user_id": "owner", "status": "partial",
        "plan": {"planner_contract_version": 2, "steps": []},
    })
    runtime.public_output = {
        "output_id": OUTPUT_ID, "state": "waiting", "attempt_count": 4,
        "automatic_attempts": 3, "can_retry": False, "artifact_message_id": None,
    }
    runtime.service = SimpleNamespace(
        outputs=SimpleNamespace(get=Mock(return_value={"run_id": "saved-run"})),
        rendering=SimpleNamespace(
            manual_retry=Mock(return_value=runtime.public_output),
            list_public_outputs=Mock(return_value=[runtime.public_output]),
            committed_artifacts=Mock(return_value=[]),
        ),
    )
    runtime.factory = Mock(return_value=runtime.service)
    monkeypatch.setattr(runtime.modules.route, "_orchestration_services", runtime.factory)
    return runtime


def retry_file(runtime, **body):
    return runtime.client.post(
        f"/api/v2/orchestration/runs/saved-run/outputs/{OUTPUT_ID}/retry",
        json={"conversation_id": "conversation", "submission_id": RETRY_ID, **body},
    )


def test_retry_authentication_and_ownership_precede_output_lookup(retry_runtime):
    anonymous = retry_file(retry_runtime)
    login(retry_runtime, user_id="foreign")
    foreign = retry_file(retry_runtime)
    assert anonymous.status_code == 401
    assert foreign.status_code == 404
    retry_runtime.factory.assert_not_called()


def test_file_retry_preserves_submission_and_never_retries_the_whole_run(retry_runtime, monkeypatch):
    login(retry_runtime)
    whole_run_retry = Mock(side_effect=AssertionError("File retry must not replay the plan."))
    monkeypatch.setattr(retry_runtime.modules.route, "prepare_retry", whole_run_retry)
    response = retry_file(retry_runtime)
    repeated = retry_file(retry_runtime)
    assert response.status_code == repeated.status_code == 202
    assert response.get_json()["output"] == retry_runtime.public_output
    assert response.get_json()["run"]["run_id"] == "saved-run"
    assert response.get_json()["run"]["status"] == "partial"
    assert retry_runtime.service.rendering.manual_retry.call_count == 2
    retry_runtime.service.rendering.manual_retry.assert_called_with(OUTPUT_ID, RETRY_ID)
    whole_run_retry.assert_not_called()


def test_file_retry_cannot_select_a_sibling_run_output(retry_runtime):
    login(retry_runtime)
    retry_runtime.service.outputs.get.return_value = {"run_id": "a-different-run"}
    response = retry_file(retry_runtime)
    assert response.status_code == 404
    retry_runtime.service.rendering.manual_retry.assert_not_called()


@pytest.mark.parametrize("submission", [None, False, "", "retry", "A" * 256])
def test_file_retry_rejects_invalid_submission_before_admission(retry_runtime, submission):
    login(retry_runtime)
    response = retry_file(retry_runtime, submission_id=submission)
    assert response.status_code == 400
    retry_runtime.factory.assert_not_called()


def test_file_retry_reports_uncertain_storage_without_provider_text(retry_runtime):
    login(retry_runtime)
    retry_runtime.service.rendering.manual_retry.side_effect = retry_runtime.modules.route.OutputStorageError()
    response = retry_file(retry_runtime)
    assert response.status_code == 503
    assert response.get_json()["code"] == "output_storage_unavailable"
    assert "Retry the same action" in response.get_json()["error"]


def source_service_error(runtime, failure):
    if failure == "screening":
        return ScreeningConfigurationError("Private screening backend details.")
    if failure == "source_authority":
        return SourceAuthorityUnavailableError()
    if failure == "source_authority_invalid":
        return SourceAuthorityUnverifiedError()
    if failure in ("configuration", "configuration_invalid"):
        code = (
            "external_configuration_metadata_invalid" if failure == "configuration_invalid"
            else "external_configuration_timeout"
        )
        return runtime.modules.route.ExternalConfigurationServiceError(code)
    code = (
        "external_identity_response_invalid" if failure == "directory_invalid"
        else "external_identity_timeout"
    )
    return runtime.modules.route.ExternalIdentityServiceError(code)


@pytest.mark.parametrize("failure", SOURCE_SERVICE_FAILURES)
@pytest.mark.parametrize("boundary", ["admission", "refresh"])
def test_file_retry_source_service_failure_is_not_missing_or_revoked(retry_runtime, failure, boundary):
    login(retry_runtime)
    rendering = retry_runtime.service.rendering
    callback = rendering.manual_retry if boundary == "admission" else rendering.list_public_outputs
    callback.side_effect = source_service_error(retry_runtime, failure)
    response = retry_file(retry_runtime)
    body = response.get_json()
    saved = retry_runtime.runs.read_item("saved-run", "conversation")
    assert response.status_code == 503
    assert body["code"] == "output_storage_unavailable"
    assert "Retry the same action" in body["error"]
    assert "output" not in body
    assert "Private screening backend details" not in response.get_data(as_text=True)
    assert saved["status"] == "partial"


@pytest.mark.parametrize("failure", SOURCE_SERVICE_FAILURES)
@pytest.mark.parametrize("endpoint,query", [
    ("/api/v2/orchestration/runs/saved-run", {"conversation_id": "conversation"}),
    ("/api/v2/orchestration/runs", {"conversation_id": "conversation", "include_plan": "true"}),
    ("/api/v2/orchestration/runs", {"conversation_id": "conversation"}),
])
def test_run_reads_source_service_failure_never_returns_saved_output_links(retry_runtime, failure, endpoint, query):
    login(retry_runtime)
    retry_runtime.service.rendering.list_public_outputs.side_effect = source_service_error(retry_runtime, failure)
    response = retry_runtime.client.get(
        endpoint, query_string=query,
    )
    body = response.get_json()
    assert response.status_code == 503
    assert body["code"] == "output_status_unavailable"
    assert "run" not in body and "runs" not in body
    assert "Private screening backend details" not in response.get_data(as_text=True)


@pytest.mark.parametrize("failure", SOURCE_SERVICE_FAILURES)
def test_plan_editor_source_service_failure_is_not_a_changed_plan(retry_runtime, failure):
    payload, status = retry_runtime.modules.route._plan_edit_error(source_service_error(retry_runtime, failure))
    assert status == 503
    assert payload["code"] == "source_access_unavailable"
    assert "previous plan is unchanged" in payload["error"]
    assert "Private screening backend details" not in json.dumps(payload)


def test_file_retry_hides_screening_details(retry_runtime):
    login(retry_runtime)
    retry_runtime.service.rendering.manual_retry.side_effect = DocumentHeldError("private hold details")
    response = retry_file(retry_runtime)
    assert response.status_code == 404
    assert response.get_json()["code"] == "output_unavailable"
    assert "private hold details" not in response.get_data(as_text=True)


def test_file_retry_rechecks_conversation_after_durable_admission(retry_runtime):
    login(retry_runtime)

    def deleted_during_admission(*_args):
        conversation = retry_runtime.conversations.read_item("conversation", "conversation")
        retry_runtime.conversations.delete_item("conversation", "conversation", etag=conversation["_etag"])
        return retry_runtime.public_output

    retry_runtime.service.rendering.manual_retry.side_effect = deleted_during_admission
    response = retry_file(retry_runtime)
    assert response.status_code == 404
    assert "output" not in response.get_json()


def test_file_retry_rejects_browser_transport_or_actor_arguments(retry_runtime):
    login(retry_runtime)
    response = retry_file(retry_runtime, user_id="owner", destination="a-browser-chosen-path")
    assert response.status_code == 400
    retry_runtime.factory.assert_not_called()


def test_v2_run_projection_uses_current_outputs_not_saved_browser_snapshots(retry_runtime):
    record = retry_runtime.runs.read_item("saved-run", "conversation")
    record["outputs"] = [{"artifact_message_id": "stale-link", "source_ref": "private-binding"}]
    current = [
        {"output_id": "ready", "state": "completed", "available": True, "artifact_message_id": "verified"},
        {"output_id": "held", "state": "completed", "available": False, "artifact_message_id": None},
    ]
    committed = committed_artifact(output_id="ready", artifact_message_id="verified")
    retry_runtime.service.rendering.list_public_outputs.return_value = current
    retry_runtime.service.rendering.committed_artifacts.return_value = [committed]
    projected = retry_runtime.modules.route._run_detail_row(record)
    assert projected["outputs"] == current
    assert projected["generated_artifacts"] == [committed]
    assert projected["artifact_count"] == 1
    assert "stale-link" not in json.dumps(projected)
    assert "private-binding" not in json.dumps(projected)
    retry_runtime.service.rendering.list_public_outputs.assert_called_once_with("saved-run")
    retry_runtime.service.rendering.committed_artifacts.assert_called_once_with("saved-run")


def test_lean_v2_run_list_exposes_current_file_recovery_without_loading_plans_or_cards(retry_runtime):
    login(retry_runtime)
    record = retry_runtime.runs.read_item("saved-run", "conversation")
    record.update(
        status="completed",
        outputs=[{"artifact_message_id": "stale-link", "source_ref": "private-binding"}],
        artifacts=[{"artifact_message_id": "stale-link"}] * 3,
        result_aliases={"private-alias": "private-result-reference"},
    )
    retry_runtime.runs.upsert_item(record)
    current = [
        {**retry_runtime.public_output, "state": "retry_scheduled", "available": True},
        {"output_id": "ready", "state": "completed", "available": True, "artifact_message_id": "verified"},
        {"output_id": "held", "state": "completed", "available": False, "artifact_message_id": None},
    ]
    retry_runtime.service.rendering.list_public_outputs.return_value = current
    response = retry_runtime.client.get(
        "/api/v2/orchestration/runs", query_string={"conversation_id": "conversation"},
    )
    body = response.get_json()
    assert response.status_code == 200
    assert len(body["runs"]) == 1
    row = body["runs"][0]
    assert row["status"] == "completed" and row["outputs"] == current
    assert row["artifact_count"] == 1
    assert not {"plan", "generated_artifacts", "result_aliases", "task_results", "seeds"}.intersection(row)
    assert "stale-link" not in json.dumps(body) and "private-binding" not in json.dumps(body)
    retry_runtime.service.rendering.list_public_outputs.assert_called_once_with("saved-run")
    retry_runtime.service.rendering.committed_artifacts.assert_not_called()


@pytest.mark.parametrize("include_plan", ["false", "true"])
@pytest.mark.parametrize("legacy_plan", [{"steps": []}, {"planner_contract_version": 1, "steps": []}])
def test_legacy_runs_are_omitted_from_the_run_list(retry_runtime, include_plan, legacy_plan):
    login(retry_runtime)
    record = retry_runtime.runs.read_item("saved-run", "conversation")
    record["plan"] = legacy_plan
    record["artifacts"] = [{"artifact_message_id": "legacy-file"}]
    retry_runtime.runs.upsert_item(record)
    response = retry_runtime.client.get(
        "/api/v2/orchestration/runs",
        query_string={"conversation_id": "conversation", "include_plan": include_plan},
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["runs"] == []
    assert "legacy-file" not in json.dumps(body)
    retry_runtime.factory.assert_not_called()


def committed_artifact(*, output_id=OUTPUT_ID, artifact_message_id="verified-file"):
    return {
        "capability": "render_file", "source_kind": "orchestration_retained_output",
        "output_id": output_id, "artifact_message_id": artifact_message_id,
        "conversation_id": "conversation", "storage_scope": "chat",
        "file_name": "report.txt", "output_format": "txt", "profile": "prepared_text_v1",
        "summary": "The requested file is ready.", "row_count": 0, "character_count": 5,
    }


def test_run_detail_poll_acquires_late_committed_cards_and_removes_revoked_cards(retry_runtime):
    login(retry_runtime)
    client = retry_runtime.client
    rendering = retry_runtime.service.rendering
    endpoint = "/api/v2/orchestration/runs/saved-run"
    query = {"conversation_id": "conversation"}
    pending = client.get(endpoint, query_string=query)
    artifact = committed_artifact()
    rendering.list_public_outputs.return_value = [{
        **retry_runtime.public_output, "state": "completed", "available": True,
        "artifact_message_id": artifact["artifact_message_id"],
    }]
    rendering.committed_artifacts.return_value = [artifact]
    completed = client.get(endpoint, query_string=query)
    rendering.list_public_outputs.return_value = [{
        **retry_runtime.public_output, "state": "completed", "available": False,
        "artifact_message_id": None,
    }]
    rendering.committed_artifacts.return_value = []
    revoked = client.get(endpoint, query_string=query)
    assert pending.status_code == completed.status_code == revoked.status_code == 200
    assert pending.get_json()["run"]["generated_artifacts"] == []
    assert completed.get_json()["run"]["generated_artifacts"] == [artifact]
    assert completed.get_json()["run"]["artifact_count"] == 1
    assert revoked.get_json()["run"]["generated_artifacts"] == []
    assert revoked.get_json()["run"]["artifact_count"] == 0
    assert revoked.get_json()["run"]["outputs"][0]["state"] == "completed"


@pytest.mark.parametrize("endpoint,query", [
    ("/api/v2/orchestration/runs/saved-run", {"conversation_id": "conversation"}),
    ("/api/v2/orchestration/runs", {"conversation_id": "conversation", "include_plan": "true"}),
])
def test_run_reads_never_substitute_saved_cards_after_current_commit_read_fails(retry_runtime, endpoint, query):
    login(retry_runtime)
    retry_runtime.service.rendering.committed_artifacts.side_effect = retry_runtime.modules.route.OutputStorageError()
    response = retry_runtime.client.get(
        endpoint, query_string=query,
    )
    assert response.status_code == 503
    assert response.get_json()["code"] == "output_status_unavailable"
    assert "run" not in response.get_json()


def test_v2_run_projection_does_not_hide_backend_outage_as_empty_outputs(retry_runtime):
    record = retry_runtime.runs.read_item("saved-run", "conversation")
    retry_runtime.service.rendering.list_public_outputs.side_effect = retry_runtime.modules.route.OutputStorageError()
    with pytest.raises(retry_runtime.modules.route.OutputStorageError):
        retry_runtime.modules.route._run_detail_row(record)


def test_headless_stream_emits_progress_then_one_terminal_frame(modules):
    execution = Mock()
    progress = modules.route.serialize_sse({"type": "thought", "content": "progress"})
    complete = modules.route.serialize_sse({"done": True, "status": "completed"})

    def execute(emit):
        emit(progress)
        return [complete]

    execution.execute.side_effect = execute
    response = modules.route._stream_execution(
        execution, run_id="run", conversation_id="conversation",
    )
    frames = list(response.response)
    response.close()
    assert frames == [progress, complete]
    assert execution.execute.call_count == 1
    execution.close.assert_called_once()


def test_headless_stream_withholds_progress_until_the_checked_reply(modules):
    execution = Mock()
    progress = modules.route.serialize_sse({"type": "thought", "content": "unchecked progress"})
    complete = modules.route.serialize_sse({
        "done": True, "status": "completed", "metadata": {"chat_content_checks": {"status": "passed"}},
    })

    def execute(emit):
        emit(progress)
        return [complete]

    execution.execute.side_effect = execute
    response = modules.route._stream_execution(
        execution, run_id="run", conversation_id="conversation", settings={
            "enable_content_screening": True, "enable_content_screening_chat_output": True,
            "chat_content_output_mode": "check_before_display",
        },
    )
    frames = list(response.response)
    response.close()
    assert frames == [modules.route.serialize_sse({"done": True, "status": "completed", "metadata": {}})]
    execution.close.assert_called_once()


def test_headless_stream_close_before_start_releases_resources(modules):
    execution = Mock()
    response = modules.route._stream_execution(
        execution, run_id="run", conversation_id="conversation",
    )
    response.close()
    execution.execute.assert_not_called()
    execution.close.assert_called_once()


def test_headless_stream_reports_unconfirmed_work_without_private_exception_text(modules):
    execution = Mock()
    execution.execute.side_effect = RuntimeError("private provider diagnostic")
    response = modules.route._stream_execution(
        execution, run_id="run", conversation_id="conversation",
    )
    frames = list(response.response)
    response.close()
    content = "".join(frames)
    assert "Reload the run" in content
    assert "private provider diagnostic" not in content
    assert '"done": true' not in content
    execution.close.assert_called_once()


def test_headless_worker_keeps_running_after_browser_disconnect(modules):
    execution = Mock()
    continue_work = threading.Event()
    closed = threading.Event()
    finished_work = []
    progress = modules.route.serialize_sse({"type": "thought", "content": "progress"})

    def execute(emit):
        emit(progress)
        if not continue_work.wait(timeout=5):
            raise RuntimeError("The test did not release its worker.")
        finished_work.append("committed")
        emit(modules.route.serialize_sse({"type": "thought", "content": "later progress"}))
        return [modules.route.serialize_sse({"done": True, "status": "completed"})]

    execution.execute.side_effect = execute
    execution.close.side_effect = closed.set
    response = modules.route._stream_execution(
        execution, run_id="run", conversation_id="conversation",
    )
    iterator = iter(response.response)
    try:
        first = next(iterator)
        iterator.close()
        response.close()
        closed_on_disconnect = closed.is_set()
    finally:
        continue_work.set()
        worker_closed = closed.wait(timeout=5)
    assert first == progress
    assert not closed_on_disconnect
    assert worker_closed
    assert finished_work == ["committed"]
    execution.close.assert_called_once()


@pytest.mark.parametrize("optimized", [False, True])
def test_real_bootstrap_route_import_and_registration_are_network_free(optimized):
    script = f"""
import sys
sys.path[:0] = [{str(APP)!r}, {str(TESTS)!r}]
from flask import Blueprint, Flask
from werkzeug.test import Client
from werkzeug.wrappers import Response
from test_support.offline_bootstrap import offline_app_imports
with offline_app_imports() as environment:
    import functions_orchestration_services
    import functions_orchestration_bootstrap as bootstrap
    import route_backend_orchestration as routes
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'cold-harness-test'
    blueprint = Blueprint('backend_orchestration', __name__)
    routes.register_route_backend_orchestration(blueprint)
    app.register_blueprint(blueprint)
    response = Client(app, Response).get('/api/v2/orchestration/export-catalog')
    if response.status_code != 401:
        raise RuntimeError('The catalog bypassed authentication.')
    bootstrap.initialize_orchestration_artifact_access()
    if environment.network_attempts:
        raise RuntimeError('Bootstrap attempted network I/O.')
"""
    command = [sys.executable, *(["-O"] if optimized else []), "-c", script]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_removed_harness_reply_hides_run_files_from_history(real_http_harness, monkeypatch):
    runtime = real_http_harness
    harness = runtime.harness
    checks = importlib.import_module("functions_chat_content_checks")
    policies = importlib.import_module("content_screening.policies")
    policy = policies.default_policy()
    policy["enabled"] = True
    policy["rules"] = [deepcopy(policies.STARTER_RULE_TEMPLATES["email"])]
    harness.settings.update({
        "enable_content_screening": True, "enable_content_screening_chat_output": True,
    })

    def evaluate(text, checkpoint, *, user_id, settings=None, required_scanners=None):
        return checks.evaluate_chat_content(
            text, checkpoint, settings if settings is not None else harness.settings,
            baseline_loader=lambda: policy, required_scanners=required_scanners,
        )

    monkeypatch.setattr(checks, "check_chat_content", evaluate)
    record = harness.create(
        [compose_step(), render_step("report", "md")],
        replies=["The complete retained report."], final_response=input_binding("prepare"),
    )
    executed = runtime.client.post("/api/v2/orchestration/run", json={
        "run_id": record["id"], "conversation_id": "conversation-1",
    }, buffered=True)
    saved = harness.read()
    before = runtime.client.get(
        f"/api/v2/orchestration/runs/{record['id']}", query_string={"conversation_id": "conversation-1"},
    ).get_json()["run"]
    message = harness.messages.read_item(saved["assistant_message_id"], "conversation-1")
    decision = checks.ChatContentDecision("chat_output", "findings", "block", {
        "schema_version": 1, "checkpoint": "chat_output", "origin": "assistant", "status": "findings",
        "complete": True, "decision": "block", "attempted_at": "2026-09-23T12:00:00+00:00", "scanners": [],
    }, checks.REMOVED_REPLY_MESSAGE)
    harness.messages.upsert_item(checks.retract_message_content(message, decision))
    after = runtime.client.get(
        f"/api/v2/orchestration/runs/{record['id']}", query_string={"conversation_id": "conversation-1"},
    ).get_json()["run"]
    listed = runtime.client.get(
        "/api/v2/orchestration/runs", query_string={"conversation_id": "conversation-1"},
    ).get_json()

    assert executed.status_code == 200 and saved["chat_content_checked_output"] is True
    assert len(before["outputs"]) == len(before["generated_artifacts"]) == before["artifact_count"] == 1
    assert after["outputs"] == [] and after["generated_artifacts"] == [] and after["artifact_count"] == 0
    rows = [row for row in listed["runs"] if row["run_id"] == record["id"]]
    assert rows and rows[0]["outputs"] == [] and rows[0]["artifact_count"] == 0
    assert checks.CHECK_METADATA not in json.dumps([before, after, listed])
    assert harness.blobs.file_uploads == 1 and len(harness.model_calls) == 1
