# test_m365_loader_preflight.py
"""
Runtime tests for authoritative Microsoft 365 loader preflight and propagation.
Version: 0.261.029
Implemented in: 0.261.029

Loads the complete real loader module and real M365 context/capability/policy
modules. Unrelated model, plugin, settings, and cloud adapters are scoped import
seams; these tests verify loader control flow, not full application cold startup.
"""

import ast
import builtins
import importlib.util
import logging
import socket
import sys
import types
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import Flask, g


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
REAL_MODULES = {
    "flask",
    "azure.core.exceptions",
    "azure.identity",
    "functions_m365_execution",
    "functions_m365_operations",
    "functions_m365_approvals",
    "functions_msgraph_operations",
}


@pytest.fixture
def loader_runtime(monkeypatch):
    monkeypatch.syspath_prepend(str(APP_ROOT))
    import functions_m365_approvals as approvals
    import functions_m365_execution as execution
    from test_support.m365 import Clock, CosmosContainer, Notifications

    def no_network(*args, **kwargs):
        raise AssertionError("Loader tests must not contact network services.")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(execution, "_execution_context", ContextVar("test_m365_loader_context", default=None))
    monkeypatch.setattr(execution, "_action_config_resolver", None)
    monkeypatch.setattr(execution, "_action_selection_resolver", None)
    monkeypatch.setattr(execution, "_workflow_validator", None)
    monkeypatch.setattr(execution, "_workflow_binding_resolver", None)
    tree = ast.parse((APP_ROOT / "semantic_kernel_loader.py").read_text(encoding="utf-8"))
    seams = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.lineno > 150 or node.module in REAL_MODULES:
            continue
        seam = seams.setdefault(node.module, types.ModuleType(node.module))
        for item in node.names:
            if item.name == "SecretReturnType":
                value = types.SimpleNamespace(NAME="name", VALUE="value")
            elif item.name.endswith("_PLUGIN_TYPE"):
                value = item.name.removesuffix("_PLUGIN_TYPE").lower()
            elif item.name.endswith("_SENSITIVE_ADDITIONAL_FIELDS") or item.name.endswith("_SENSITIVE_AUTH_FIELDS"):
                value = frozenset()
            else:
                value = Mock(name=f"{node.module}.{item.name}")
            setattr(seam, item.name, value)
    seams["app_settings_cache"] = types.ModuleType("app_settings_cache")
    for name, seam in seams.items():
        monkeypatch.setitem(sys.modules, name, seam)

    spec = importlib.util.spec_from_file_location("m365_test_full_loader", APP_ROOT / "semantic_kernel_loader.py")
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    loader.logging = logging
    loader.log_event = Mock()
    loader.debug_print = Mock()
    loader.hydrate_workspace_identity_in_plugin = lambda manifest: manifest
    loader.is_tabular_processing_enabled = lambda settings: False
    for name in (
        "load_time_plugin", "load_http_plugin", "load_wait_plugin", "load_math_plugin",
        "load_text_plugin", "load_fact_memory_plugin", "load_document_search_plugin",
        "load_chart_plugin", "load_embedding_model_plugin",
    ):
        setattr(loader, name, Mock(return_value=None))
    loader.get_current_user_id_or_none = lambda: "owner"
    log_loader = types.SimpleNamespace(load_multiple_plugins=Mock(return_value={"calendar": True}))
    loader.create_logged_plugin_loader = lambda kernel: log_loader
    context = execution.M365ExecutionContext(
        actor_user_id="owner",
        data_user_id="owner",
        tenant_id="tenant",
        conversation_id="conversation",
        request_id="logical-request",
        agent_id="agent",
        shared=True,
        audience_version="audience",
        action_configs={"calendar": {"type": "m365_calendar"}},
    )
    container = CosmosContainer()
    service = approvals.M365ApprovalService(
        container_factory=lambda: container,
        notification_sender=Notifications(),
        decision_validator=lambda approval: True,
        clock=Clock(),
    )
    with pytest.raises(approvals.M365ApprovalRequired) as captured:
        service.authorize_sources(context, {"calendar": "request"})
    return types.SimpleNamespace(
        loader=loader, execution=execution, approvals=approvals, context=context,
        pending=captured.value, log_loader=log_loader,
    )


def manifests():
    return [
        {
            "id": "calendar", "name": "calendar", "type": "m365_calendar",
            "additionalFields": {"m365_capabilities": {"get_my_events": False, "get_my_timezone": True}},
        },
        {"id": "unrelated", "name": "unrelated", "type": "custom"},
    ]


def install_preflight(monkeypatch, runtime, callback):
    # The execution owner supplies this public hook; the loader never fabricates consent.
    monkeypatch.setattr(runtime.execution, "preflight_m365_manifests", callback)


def _block_runtime_import(monkeypatch):
    original_import = builtins.__import__

    def no_runtime_import(name, *args, **kwargs):
        if name == "functions_m365_runtime":
            raise AssertionError("The loader must use execution preflight without importing runtime owners.")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_runtime_import)


def test_bootstrap_without_authoritative_context_does_not_preflight(loader_runtime, monkeypatch):
    runtime = loader_runtime
    _block_runtime_import(monkeypatch)
    preflight = Mock(side_effect=AssertionError("Startup has no conversation authorization."))
    install_preflight(monkeypatch, runtime, preflight)
    result = runtime.loader._apply_agent_plugin_runtime_overlays(manifests())
    assert result[0]["enabled_functions"] == ["get_my_timezone"]
    assert preflight.call_count == 0
    app = Flask(__name__)
    with app.test_request_context():
        g.m365_execution_context = {"shared": False, "caller_supplied": True}
        result = runtime.loader._apply_agent_plugin_runtime_overlays(manifests())
    assert result[0]["enabled_functions"] == ["get_my_timezone"]
    assert preflight.call_count == 0


def test_authoritative_context_uses_execution_preflight_without_runtime_import(loader_runtime, monkeypatch):
    runtime = loader_runtime
    _block_runtime_import(monkeypatch)
    preflight = Mock(side_effect=lambda effective: effective)
    install_preflight(monkeypatch, runtime, preflight)
    with runtime.execution.m365_execution_context(runtime.context):
        result = runtime.loader._apply_agent_plugin_runtime_overlays(manifests())
    assert preflight.call_count == 1
    assert result[0]["enabled_functions"] == ["get_my_timezone"]


def test_preflight_receives_effective_caps_and_preserves_declined_pruning(loader_runtime, monkeypatch):
    runtime = loader_runtime
    seen = []

    def prune(effective):
        seen.append(effective)
        return [item for item in effective if item["type"] == "custom"]

    install_preflight(monkeypatch, runtime, prune)
    app = Flask(__name__)
    with app.test_request_context():
        g.m365_execution_context = runtime.context
        result = runtime.loader._apply_agent_plugin_runtime_overlays(
            manifests(),
            {"action_capabilities": {"calendar": {"get_my_events": True, "get_my_timezone": False, "send_mail": True}}},
        )
    assert seen[0][0]["enabled_functions"] == []
    assert result == [manifests()[1]]
    assert seen[0][0]["additionalFields"]["m365_capabilities"]["get_my_events"] is False


def test_explicit_context_scope_supports_non_flask_jobs_without_leaking(loader_runtime, monkeypatch):
    runtime = loader_runtime
    seen = []

    def record(effective):
        seen.append(runtime.execution.get_m365_execution_context())
        return effective

    install_preflight(monkeypatch, runtime, record)
    explicit = runtime.execution.M365ExecutionContext(
        actor_user_id="trigger-user", data_user_id="run-as-user", tenant_id="tenant",
        workflow_id="workflow", run_id="run", request_id="request",
        workflow_fingerprint="approved-revision", connection_id="connection",
        action_configs={"calendar": {"type": "m365_calendar"}},
    )
    with runtime.execution.m365_execution_context(explicit):
        runtime.loader._apply_agent_plugin_runtime_overlays(manifests())
    restored = runtime.execution.get_m365_execution_context()
    assert seen == [explicit]
    assert restored is None


@pytest.mark.parametrize("entry", ["agent", "global", "agent_fallback", "global_fallback"])
def test_pending_approval_escapes_every_loader_before_registration(loader_runtime, monkeypatch, entry):
    runtime = loader_runtime
    preflight = Mock(side_effect=runtime.pending)
    install_preflight(monkeypatch, runtime, preflight)
    runtime.loader._get_governed_global_plugin_manifests = lambda *args, **kwargs: manifests()
    kernel = types.SimpleNamespace(add_plugin=Mock())
    with runtime.execution.m365_execution_context(runtime.context):
        with pytest.raises(runtime.approvals.M365ApprovalRequired) as captured:
            if entry == "agent":
                runtime.loader.load_agent_specific_plugins(kernel, ["calendar", "unrelated"], {})
            elif entry == "global":
                runtime.loader.load_plugins_for_kernel(kernel, manifests(), {})
            elif entry == "agent_fallback":
                runtime.loader._load_agent_plugins_original_method(kernel, manifests())
            else:
                runtime.loader._load_plugins_original_method(kernel, manifests(), {})
    assert captured.value is runtime.pending
    assert preflight.call_count == 1
    assert runtime.log_loader.load_multiple_plugins.call_count == 0
    assert kernel.add_plugin.call_count == 0


@pytest.mark.parametrize("entry", ["agent", "global"])
def test_logged_loader_policy_failure_never_invokes_recovery(loader_runtime, monkeypatch, entry):
    runtime = loader_runtime
    install_preflight(monkeypatch, runtime, lambda effective: effective)
    runtime.loader._get_governed_global_plugin_manifests = lambda *args, **kwargs: manifests()
    runtime.log_loader.load_multiple_plugins.side_effect = runtime.pending
    fallback = Mock()
    monkeypatch.setattr(runtime.loader, "_load_agent_plugins_original_method", fallback)
    monkeypatch.setattr(runtime.loader, "_load_plugins_original_method", fallback)
    with runtime.execution.m365_execution_context(runtime.context):
        with pytest.raises(runtime.approvals.M365ApprovalRequired) as captured:
            if entry == "agent":
                runtime.loader.load_agent_specific_plugins(Mock(), ["calendar", "unrelated"], {})
            else:
                runtime.loader.load_plugins_for_kernel(Mock(), manifests(), {})
    assert captured.value is runtime.pending
    assert fallback.call_count == 0


@pytest.mark.parametrize("failure", ["missing", "invalid_result", "dependency_error", "permission_error"])
def test_preflight_dependency_failure_is_explicit_and_never_recovers_unrestricted(loader_runtime, monkeypatch, failure):
    runtime = loader_runtime
    if failure == "missing":
        monkeypatch.delattr(runtime.execution, "preflight_m365_manifests")
    elif failure == "invalid_result":
        install_preflight(monkeypatch, runtime, lambda effective: None)
    elif failure == "permission_error":
        install_preflight(monkeypatch, runtime, Mock(side_effect=PermissionError("Scope denied")))
    else:
        install_preflight(monkeypatch, runtime, Mock(side_effect=RuntimeError("Storage unavailable")))
    runtime.loader._get_governed_global_plugin_manifests = lambda *args, **kwargs: manifests()
    fallback = Mock()
    monkeypatch.setattr(runtime.loader, "_load_agent_plugins_original_method", fallback)
    with runtime.execution.m365_execution_context(runtime.context):
        with pytest.raises(runtime.approvals.M365PolicyError) as captured:
            runtime.loader.load_agent_specific_plugins(Mock(), ["calendar", "unrelated"], {})
    assert captured.value.code == "m365_preflight_unavailable"
    assert fallback.call_count == 0
    assert runtime.log_loader.load_multiple_plugins.call_count == 0


def test_recovery_rechecks_preflight_and_propagates_new_pending_state(loader_runtime, monkeypatch):
    runtime = loader_runtime
    preflight = Mock(side_effect=[manifests(), runtime.pending])
    install_preflight(monkeypatch, runtime, preflight)
    runtime.loader._get_governed_global_plugin_manifests = lambda *args, **kwargs: manifests()
    runtime.log_loader.load_multiple_plugins.side_effect = RuntimeError("Adapter load failed")
    fallback = Mock()
    monkeypatch.setattr(runtime.loader, "_load_agent_plugins_original_method", fallback)
    with runtime.execution.m365_execution_context(runtime.context):
        with pytest.raises(runtime.approvals.M365ApprovalRequired) as captured:
            runtime.loader.load_agent_specific_plugins(Mock(), ["calendar", "unrelated"], {})
    assert captured.value is runtime.pending
    assert preflight.call_count == 2
    assert fallback.call_count == 0


@pytest.mark.parametrize("entry", ["agent_fallback", "global_fallback"])
def test_original_registration_policy_failure_is_not_logged_away(loader_runtime, monkeypatch, entry):
    runtime = loader_runtime
    install_preflight(monkeypatch, runtime, lambda effective: effective)
    plugin = types.SimpleNamespace(get_kernel_plugin=Mock(side_effect=runtime.pending))
    runtime.loader.discover_plugins = lambda: {"M365CalendarPlugin": type("M365CalendarPlugin", (), {})}
    runtime.loader.PluginHealthChecker.create_plugin_safely.return_value = (plugin, [])
    kernel = types.SimpleNamespace(add_plugin=Mock())
    with runtime.execution.m365_execution_context(runtime.context):
        with pytest.raises(runtime.approvals.M365ApprovalRequired) as captured:
            if entry == "agent_fallback":
                runtime.loader._load_agent_plugins_original_method(kernel, manifests()[:1])
            else:
                runtime.loader._load_plugins_original_method(kernel, manifests()[:1], {})
    assert captured.value is runtime.pending
    assert kernel.add_plugin.call_count == 0


@pytest.fixture
def actual_policy_runtime(loader_runtime, monkeypatch):
    from test_support.m365 import Clock, CosmosContainer, Notifications

    runtime = loader_runtime
    container = CosmosContainer()
    service = runtime.approvals.M365ApprovalService(
        container_factory=lambda: container,
        notification_sender=Notifications(),
        decision_validator=lambda approval: True,
        clock=Clock(),
    )
    monkeypatch.setattr(runtime.approvals, "_service", service)
    runtime.service = service
    runtime.container = container
    runtime.loader._get_governed_global_plugin_manifests = lambda *args, **kwargs: manifests()
    saved_actions = {
        "calendar": manifests()[0],
        "legacy": {
            "id": "legacy", "type": "msgraph",
            "enabled_functions": ["get_my_events", "get_my_messages", "get_my_profile"],
            "additionalFields": {"maximum_sharing_acknowledgement": "request"},
        },
    }
    runtime.saved_actions = saved_actions

    def resolve_saved_action(context, action_id, source):
        saved = saved_actions.get(action_id)
        if (
            context.actor_user_id != "owner"
            or context.tenant_id != "tenant"
            or saved is None
            or source not in runtime.execution._action_sources(saved)
        ):
            raise runtime.approvals.M365PolicyError(
                "m365_action_not_authorized", "The saved fixture action is not authorized.",
            )
        return deepcopy(saved)

    monkeypatch.setattr(runtime.execution, "_action_config_resolver", resolve_saved_action)
    return runtime


def test_canonical_preflight_pauses_then_prunes_only_declined_source(actual_policy_runtime):
    runtime = actual_policy_runtime
    app = Flask(__name__)
    with app.test_request_context():
        g.m365_execution_context = runtime.context
        with pytest.raises(runtime.approvals.M365ApprovalRequired) as captured:
            runtime.loader.load_agent_specific_plugins(Mock(), ["calendar", "unrelated"], {})
        pending = captured.value
        assert runtime.log_loader.load_multiple_plugins.call_count == 0
        with pytest.raises(runtime.approvals.M365ApprovalRequired) as repeated:
            runtime.loader.load_agent_specific_plugins(Mock(), ["calendar", "unrelated"], {})
        assert repeated.value.approval_id == pending.approval_id
        saved = runtime.service.decide(pending.approval_id, "owner", {
            "decisions": {"calendar": {"duration": "no"}},
        })
        runtime.loader.load_agent_specific_plugins(Mock(), ["calendar", "unrelated"], {})
        loaded = runtime.log_loader.load_multiple_plugins.call_args.args[0]
        denied = g.m365_declined_sources
    assert saved["status"] == "denied"
    assert loaded == [manifests()[1]]
    assert denied == ["calendar"]


@pytest.mark.parametrize("group_id", [None, "single-user-group"])
def test_canonical_preflight_does_not_prompt_for_private_audience(actual_policy_runtime, group_id):
    runtime = actual_policy_runtime
    app = Flask(__name__)
    context = runtime.execution.M365ExecutionContext(
        actor_user_id="owner", data_user_id="owner", tenant_id="tenant",
        conversation_id="private", request_id="private-request", shared=False,
        group_id=group_id,
    )
    with app.test_request_context():
        g.m365_execution_context = context
        result = runtime.loader._apply_agent_plugin_runtime_overlays(manifests())
    assert result[0]["enabled_functions"] == ["get_my_timezone"]
    assert runtime.container.items == {}


def test_canonical_preflight_preserves_other_legacy_functions_after_denial(actual_policy_runtime):
    runtime = actual_policy_runtime
    app = Flask(__name__)
    legacy = {
        "id": "legacy", "name": "legacy", "type": "msgraph",
        "enabled_functions": ["get_my_events", "get_my_messages", "get_my_profile"],
        "additionalFields": {"maximum_sharing_acknowledgement": "request"},
    }
    with app.test_request_context():
        g.m365_execution_context = runtime.context
        with pytest.raises(runtime.approvals.M365ApprovalRequired) as captured:
            runtime.loader._apply_agent_plugin_runtime_overlays([legacy])
        decision = runtime.service.decide(captured.value.approval_id, "owner", {
            "decisions": {
                "calendar": {"duration": "request", "timezone": "America/New_York"},
                "email": {"duration": "no"},
            },
        })
        result = runtime.loader._apply_agent_plugin_runtime_overlays([legacy])
    assert decision["status"] == "approved"
    assert set(result[0]["enabled_functions"]) == {"get_my_events", "get_my_profile"}


def test_canonical_preflight_ignores_actions_without_enabled_functions(actual_policy_runtime):
    runtime = actual_policy_runtime
    disabled = {**manifests()[0], "enabled_functions": []}
    app = Flask(__name__)
    with app.test_request_context():
        g.m365_execution_context = runtime.context
        result = runtime.loader._apply_agent_plugin_runtime_overlays([disabled, manifests()[1]])
    assert result == [manifests()[1]]
    assert runtime.container.items == {}


def test_source_denial_keeps_published_snapshot_tools(actual_policy_runtime):
    runtime = actual_policy_runtime
    file_action = {
        "id": "files", "name": "files", "type": "m365_onedrive",
        "enabled_functions": ["search_files", "read_file_chunk"],
        "additionalFields": {"maximum_sharing_acknowledgement": "request"},
    }
    runtime.saved_actions["files"] = file_action
    app = Flask(__name__)
    with app.test_request_context():
        g.m365_execution_context = runtime.context
        with pytest.raises(runtime.approvals.M365ApprovalRequired) as captured:
            runtime.loader._apply_agent_plugin_runtime_overlays([file_action, manifests()[1]])
        decision = runtime.service.decide(captured.value.approval_id, "owner", {
            "decisions": {"onedrive": {"duration": "no"}},
        })
        result = runtime.loader._apply_agent_plugin_runtime_overlays([file_action, manifests()[1]])
        repeated = runtime.loader._apply_agent_plugin_runtime_overlays(result)
    assert decision["status"] == "denied"
    assert result[0]["enabled_functions"] == ["read_file_chunk"]
    assert result[1] == manifests()[1]
    assert repeated[0]["enabled_functions"] == ["read_file_chunk"]
