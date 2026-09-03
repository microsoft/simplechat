# test_app_settings_auxiliary_writers.py
"""
Functional tests for auxiliary app-settings writers.
Version: 0.261.025
Implemented in: 0.261.025

Execute isolated production functions through AST extraction, without importing
application configuration or contacting Redis, Cosmos DB, or other cloud services.
Verify field-only updates, optimistic concurrency, and rejected-write responses.
"""

import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

import pytest


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
WRITER_FILES = (
    "background_tasks.py",
    "functions_control_center.py",
    "functions_retention_policy.py",
    "functions_service_health.py",
    "plugin_validation_endpoint.py",
    "route_backend_agents.py",
    "route_backend_control_center.py",
    "route_backend_retention_policy.py",
    "route_backend_settings.py",
    "route_custom_pages.py",
)


class SettingsStore:
    """Keep a stale reader snapshot separate from the latest persisted document."""

    def __init__(self, settings=None, *, available=True, conflict=False):
        self.snapshot = {
            "_etag": '"original"',
            "app_title": "stale title",
            "unrelated_secret": "must not be written",
            **(settings or {}),
        }
        self.live = deepcopy(self.snapshot)
        self.live["app_title"] = "latest title"
        if conflict:
            self.live["_etag"] = '"concurrent-write"'
        self.available = available
        self.calls = []

    def read(self):
        return self.snapshot

    def update(self, updates, *, expected_etag=None):
        self.calls.append((deepcopy(updates), expected_etag))
        if not self.available:
            return False
        if expected_etag is not None and expected_etag != self.live["_etag"]:
            return False
        self.live.update(deepcopy(updates))
        return True


class IsolateFunction(ast.NodeTransformer):
    """Remove route decorators and replace inline imports with injected doubles."""

    def visit_FunctionDef(self, node):
        node.decorator_list = []
        return self.generic_visit(node)

    def visit_Import(self, node):
        return None

    def visit_ImportFrom(self, node):
        return None


def load_function(filename, function_name, store, **overrides):
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
    functions = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    assert len(functions) == 1, function_name
    function = IsolateFunction().visit(functions[0])
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    empty_container = SimpleNamespace(query_items=lambda **kwargs: [])
    namespace = {
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
        "logging": logging,
        "uuid": uuid,
        "deepcopy": deepcopy,
        "get_settings": store.read,
        "update_settings": store.update,
        "jsonify": lambda payload: payload,
        "debug_print": lambda *args, **kwargs: None,
        "log_event": lambda *args, **kwargs: None,
        "get_current_user_id": lambda: "admin",
        "builtins": SimpleNamespace(kernel_reload_needed=False),
        "request": SimpleNamespace(
            json={}, method="POST", get_json=lambda **kwargs: {},
        ),
        "cosmos_user_settings_container": empty_container,
        "cosmos_groups_container": empty_container,
        **overrides,
    }
    exec(compile(module, str(APP_DIR / filename), "exec"), namespace)
    return namespace[function_name]


def response_parts(response):
    return response if isinstance(response, tuple) else (response, 200)


def assert_delta(store, expected_keys, *, etag=None):
    assert len(store.calls) == 1
    updates, expected_etag = store.calls[0]
    assert set(updates) == set(expected_keys)
    assert expected_etag == etag
    assert store.live["app_title"] == "latest title"
    assert "unrelated_secret" not in updates


@pytest.mark.parametrize("filename", WRITER_FILES)
def test_no_full_settings_snapshot_is_written(filename):
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "update_settings"
    ]
    assert calls
    for call in calls:
        assert not (isinstance(call.args[0], ast.Name) and call.args[0].id == "settings")


@pytest.mark.parametrize("logging_type", ["debug", "file_processing", "both"])
@pytest.mark.parametrize("available,conflict", [(True, False), (False, False), (True, True)])
def test_logging_expiration_uses_guarded_deltas(logging_type, available, conflict):
    expiry = (datetime.now() - timedelta(days=1)).isoformat()
    fields = {
        "debug": ("enable_debug_logging", "debug_logging_timer_enabled", "debug_logging_turnoff_time"),
        "file_processing": (
            "enable_file_processing_logs", "file_processing_logs_timer_enabled",
            "file_processing_logs_turnoff_time",
        ),
    }
    selected = fields.values() if logging_type == "both" else [fields[logging_type]]
    settings = {}
    expected_keys = []
    for enabled_key, timer_key, expiry_key in selected:
        settings.update({enabled_key: True, timer_key: True, expiry_key: expiry})
        expected_keys.extend([enabled_key, timer_key, expiry_key])
    store = SettingsStore(settings, available=available, conflict=conflict)
    original = deepcopy(store.snapshot)
    check = load_function("background_tasks.py", "check_logging_timers_once", store)

    assert check() is (available and not conflict)
    assert_delta(store, expected_keys, etag='"original"')
    assert store.snapshot == original
    if not available or conflict:
        assert all(store.live[key] == value for key, value in settings.items())


def test_logging_expiration_does_not_write_before_expiry():
    store = SettingsStore({
        "enable_debug_logging": True,
        "debug_logging_timer_enabled": True,
        "debug_logging_turnoff_time": (datetime.now() + timedelta(days=1)).isoformat(),
    })
    check = load_function("background_tasks.py", "check_logging_timers_once", store)
    check()
    assert store.calls == []


@pytest.mark.parametrize("available,conflict", [(True, False), (False, False), (True, True)])
def test_refresh_schedule_seed_rejects_failed_or_stale_writes(available, conflict):
    store = SettingsStore(available=available, conflict=conflict)
    next_run = datetime(2026, 9, 10, 6, tzinfo=timezone.utc)
    seed = load_function(
        "background_tasks.py", "_seed_control_center_auto_refresh_next_run", store,
        get_control_center_auto_refresh_schedule=lambda settings: {
            "time": "02:00", "hour": 2, "minute": 0, "timezone": "America/New_York",
        },
        calculate_next_control_center_auto_refresh_run=lambda *args, **kwargs: next_run,
    )
    if available and not conflict:
        assert seed(store.snapshot, next_run) == next_run
    else:
        with pytest.raises(RuntimeError, match="Unable to save"):
            seed(store.snapshot, next_run)
    assert_delta(store, {
        "control_center_auto_refresh_enabled", "control_center_auto_refresh_time",
        "control_center_auto_refresh_hour", "control_center_auto_refresh_minute",
        "control_center_auto_refresh_timezone", "control_center_auto_refresh_next_run",
    }, etag='"original"')


@pytest.mark.parametrize("available", [True, False])
@pytest.mark.parametrize("nested", [True, False])
def test_autoscale_runtime_writes_report_failure_and_guard_policies(available, nested):
    store = SettingsStore({"cosmos_throughput_autoscale_enabled": True}, available=available)
    delta = {"cosmos_throughput_last_checked_at": "now"}
    if nested:
        delta["cosmos_throughput_container_policies"] = {"messages": {"last_scale_up_at": "now"}}
    released = []
    lock = object()
    check = load_function(
        "background_tasks.py", "check_cosmos_throughput_autoscale_once", store,
        acquire_distributed_task_lock=lambda *args, **kwargs: lock,
        release_distributed_task_lock=released.append,
        evaluate_and_apply_cosmos_throughput_scaling=lambda *args, **kwargs: {
            "settings_update": delta,
        },
    )
    result = check()
    assert_delta(store, delta, etag='"original"' if nested else None)
    assert released == [lock]
    if not available:
        assert result["success"] is False
        assert "Unable to save" in result["error"]


@pytest.mark.parametrize("available", [True, False])
@pytest.mark.parametrize("enabled", [True, False])
def test_scheduled_control_center_refresh_writes_only_runtime_fields(available, enabled):
    store = SettingsStore({
        "control_center_auto_refresh_enabled": enabled,
        "control_center_auto_refresh_timezone": "UTC",
    }, available=available)
    run = load_function(
        "functions_control_center.py", "execute_control_center_refresh", store,
        calculate_next_control_center_auto_refresh_run=lambda *args, **kwargs: datetime.now(timezone.utc),
    )
    result = run()
    assert result["success"] is available
    assert_delta(store, {"control_center_last_refresh", "control_center_auto_refresh_next_run"})
    assert (store.calls[0][0]["control_center_auto_refresh_next_run"] is not None) is enabled
    if not available:
        assert result["error"] == "Unable to save Control Center refresh settings."


@pytest.mark.parametrize("available", [True, False])
def test_retention_execution_writes_only_runtime_fields(available):
    store = SettingsStore({"enable_retention_policy_personal": True}, available=available)
    run = load_function(
        "functions_retention_policy.py", "execute_retention_policy", store,
        process_personal_retention=lambda: {"conversations": 0, "documents": 0, "users_affected": 0},
    )
    result = run()
    assert result["success"] is available
    assert_delta(store, {"retention_policy_last_run", "retention_policy_next_run"})
    if not available:
        assert result["errors"] == ["Unable to save retention policy execution settings."]


@pytest.mark.parametrize("available", [True, False])
@pytest.mark.parametrize("payload", [
    {"enable_retention_policy_personal": True},
    {"enable_retention_policy_group": False, "enable_retention_policy_public": True},
    {"retention_policy_execution_hour": 8},
])
def test_retention_admin_updates_only_submitted_fields(available, payload):
    store = SettingsStore(available=available)
    route = load_function(
        "route_backend_retention_policy.py", "update_retention_policy_settings", store,
        request=SimpleNamespace(get_json=lambda: payload),
    )
    result, status = response_parts(route())
    expected = set(payload)
    if "retention_policy_execution_hour" in payload:
        expected.add("retention_policy_next_run")
    assert_delta(store, expected)
    assert result["success"] is available
    assert status == (200 if available else 500)


def test_invalid_retention_hour_does_not_write_settings():
    store = SettingsStore()
    route = load_function(
        "route_backend_retention_policy.py", "update_retention_policy_settings", store,
        request=SimpleNamespace(get_json=lambda: {"retention_policy_execution_hour": 24}),
    )
    assert response_parts(route())[1] == 400
    assert store.calls == []


@pytest.mark.parametrize("available", [True, False])
def test_manual_control_center_refresh_reports_timestamp_save_failure(available):
    store = SettingsStore(available=available)
    route = load_function("route_backend_control_center.py", "api_refresh_control_center_data", store)
    result, status = response_parts(route())
    assert_delta(store, {"control_center_last_refresh"})
    assert result["success"] is available
    assert status == (200 if available else 500)


@pytest.mark.parametrize("available,conflict", [(True, False), (False, False), (True, True)])
def test_migration_notice_uses_original_etag_and_reports_write_result(available, conflict):
    notice = {"enabled": True, "other_field": "preserve"}
    store = SettingsStore({"multi_endpoint_migration_notice": notice}, available=available, conflict=conflict)
    disable = load_function("route_backend_agents.py", "_maybe_disable_multi_endpoint_migration_notice", store)
    preview = {"summary": {"ready_to_migrate": 0, "needs_default_model": 0}}

    assert disable(store.snapshot, preview) is (available and not conflict)
    assert_delta(store, {"multi_endpoint_migration_notice"}, etag='"original"')
    assert store.calls[0][0]["multi_endpoint_migration_notice"] == {
        "enabled": False, "other_field": "preserve",
    }
    assert store.snapshot["multi_endpoint_migration_notice"]["enabled"] is True
    if not available or conflict:
        assert store.live["multi_endpoint_migration_notice"]["enabled"] is True


@pytest.mark.parametrize("available", [True, False])
def test_global_agent_selection_is_an_explicit_field_update(available):
    store = SettingsStore(available=available)
    route = load_function(
        "route_backend_agents.py", "set_selected_agent", store,
        request=SimpleNamespace(json={"name": "chosen"}),
        get_global_agents=lambda: [{"name": "chosen"}],
    )
    result, status = response_parts(route())
    assert_delta(store, {"global_selected_agent"})
    assert status == (200 if available else 500)
    assert result.get("success", False) is available
    assert route.__globals__["builtins"].kernel_reload_needed is available


@pytest.mark.parametrize("available,conflict", [(True, False), (False, False), (True, True)])
@pytest.mark.parametrize("has_fallback", [True, False])
def test_disabling_selected_agent_checks_etag_before_replacing_selection(available, conflict, has_fallback):
    store = SettingsStore({
        "global_selected_agent": {"name": "disabled"},
    }, available=available, conflict=conflict)
    route = load_function(
        "route_backend_agents.py", "set_agent_enabled", store,
        request=SimpleNamespace(get_json=lambda **kwargs: {"is_enabled": False}),
        get_global_agents=lambda **kwargs: (
            [{"name": "disabled", "id": "agent-id"}] if kwargs.get("include_disabled")
            else ([{"name": "fallback"}] if has_fallback else [])
        ),
        update_global_agent_enabled=lambda *args, **kwargs: True,
        log_agent_update=lambda **kwargs: None,
    )
    result, status = response_parts(route("disabled"))
    assert_delta(store, {"global_selected_agent"}, etag='"original"')
    assert status == (200 if available and not conflict else 500)
    assert result.get("success", False) is (available and not conflict)
    assert route.__globals__["builtins"].kernel_reload_needed is True
    if not available or conflict:
        assert store.live["global_selected_agent"] == {"name": "disabled"}


@pytest.mark.parametrize("setting_name", ["simple_value", "nested.branch.value"])
@pytest.mark.parametrize("available,conflict", [(True, False), (False, False), (True, True)])
def test_agent_setting_updates_keep_unrelated_fields_and_guard_nested_edits(setting_name, available, conflict):
    store = SettingsStore({
        "nested": {"branch": {"value": "old", "sibling": "keep"}, "other": "keep"},
    }, available=available, conflict=conflict)
    original = deepcopy(store.snapshot)
    route = load_function(
        "route_backend_agents.py", "update_agent_setting", store,
        request=SimpleNamespace(json={"value": "new"}),
    )
    result, status = response_parts(route(setting_name))
    nested = "." in setting_name
    expected_success = available and not (conflict and nested)
    assert_delta(store, {setting_name.split(".")[0]}, etag='"original"' if nested else None)
    assert status == (200 if expected_success else 500)
    assert result.get("success", False) is expected_success
    assert store.snapshot == original
    if nested:
        assert store.calls[0][0]["nested"] == {
            "branch": {"value": "new", "sibling": "keep"}, "other": "keep",
        }


@pytest.mark.parametrize("available", [True, False])
@pytest.mark.parametrize("orchestration_type", ["group_chat", "single"])
def test_orchestration_writes_only_owned_fields(available, orchestration_type):
    store = SettingsStore(available=available)
    route = load_function(
        "route_backend_agents.py", "orchestration_settings", store,
        request=SimpleNamespace(method="POST", json={
            "orchestration_type": orchestration_type, "max_rounds_per_agent": 3,
        }),
        get_agent_orchestration_types=lambda: [
            {"value": "group_chat", "agent_mode": "multi"},
            {"value": "single", "agent_mode": "single"},
        ],
    )
    result, status = response_parts(route())
    assert_delta(store, {"orchestration_type", "enable_multi_agent_orchestration", "max_rounds_per_agent"})
    assert status == (200 if available else 500)
    assert result.get("success", False) is available


@pytest.mark.parametrize("fallback", [True, False])
@pytest.mark.parametrize("container_result", ["saved", "failed", "exception"])
@pytest.mark.parametrize("available,conflict", [(True, False), (False, False), (True, True)])
def test_plugin_repairs_preserve_other_plugins_and_reject_failed_writes(
    fallback, container_result, available, conflict,
):
    store = SettingsStore({
        "semantic_kernel_plugins": [
            {"name": "repair-me", "type": "Example"},
            {"name": "keep-me", "type": "Other"},
        ],
    }, available=available, conflict=conflict)
    original = deepcopy(store.snapshot)
    plugin = object()
    health_checker = SimpleNamespace(
        create_plugin_safely=lambda *args: (None, ["error"]) if fallback else (plugin, []),
        check_plugin_health=lambda *args: {"is_healthy": False, "errors": ["error"], "timestamp": "now"},
    )
    recovery = SimpleNamespace(
        create_fallback_plugin=lambda *args: plugin,
        attempt_plugin_repair=lambda *args: (plugin, True),
    )

    def save_global_action(manifest):
        if container_result == "exception":
            raise RuntimeError("container unavailable")
        return manifest if container_result == "saved" else None

    route = load_function(
        "plugin_validation_endpoint.py", "repair_plugin", store,
        discover_plugins=lambda: {"Example": object},
        PluginHealthChecker=health_checker,
        PluginErrorRecovery=recovery,
        save_global_action=save_global_action,
    )
    result, status = response_parts(route("repair-me"))
    assert_delta(store, {"semantic_kernel_plugins"}, etag='"original"')
    assert status == (200 if available and not conflict else 500)
    assert result["success"] is (available and not conflict)
    assert store.snapshot == original
    written_plugins = store.calls[0][0]["semantic_kernel_plugins"]
    assert written_plugins[-1] == original["semantic_kernel_plugins"][-1]
    if container_result == "saved":
        assert len(written_plugins) == 1
    else:
        assert len(written_plugins) == 2
        assert written_plugins[0]["metadata"]["status"] == ("fallback" if fallback else "repaired")
    if not available or conflict:
        assert store.live["semantic_kernel_plugins"] == original["semantic_kernel_plugins"]


def load_service_health_function(function_name, store):
    filename = "functions_service_health.py"
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
    namespace = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.startswith("SEMANTIC_SEARCH_")
    }
    for helper_name in ("get_default_service_health", "_utc_now_iso", "_sanitize_error_summary"):
        namespace[helper_name] = load_function(filename, helper_name, store, **namespace)
    return load_function(filename, function_name, store, **namespace)


@pytest.mark.parametrize("function_name", [
    "record_semantic_search_quota_exceeded",
    "clear_semantic_search_quota_warning",
])
@pytest.mark.parametrize("available,conflict", [(True, False), (False, False), (True, True)])
def test_service_health_updates_guard_nested_state(function_name, available, conflict):
    store = SettingsStore({
        "service_health": {
            "semantic_search": {
                "status": "quota_exceeded", "occurrence_count": 5,
                "first_seen_at": "first occurrence",
            },
            "other_service": {"status": "keep"},
        },
    }, available=available, conflict=conflict)
    if conflict:
        store.live["service_health"]["other_service"]["status"] = "newer status"
    original = deepcopy(store.snapshot)
    before_write = deepcopy(store.live)
    update = load_service_health_function(function_name, store)
    result = update(source="test")

    assert_delta(store, {"service_health"}, etag='"original"')
    assert store.snapshot == original
    written_health = store.calls[0][0]["service_health"]
    assert written_health["other_service"] == {"status": "keep"}
    recording = function_name == "record_semantic_search_quota_exceeded"
    if recording:
        assert written_health["semantic_search"]["occurrence_count"] == 6
        assert written_health["semantic_search"]["first_seen_at"] == "first occurrence"
    else:
        assert written_health["semantic_search"]["status"] == "ok"
    if available and not conflict:
        assert result == (written_health["semantic_search"] if recording else True)
    else:
        assert result is (None if recording else False)
        assert store.live == before_write


def test_service_health_clear_without_warning_does_not_write():
    store = SettingsStore({
        "service_health": {"semantic_search": {"status": "ok"}},
    }, available=False)
    clear = load_service_health_function("clear_semantic_search_quota_warning", store)
    assert clear() is False
    assert store.calls == []


@pytest.mark.parametrize("function_name", [
    "scale_cosmos_throughput_admin",
    "convert_cosmos_throughput_to_autoscale_admin",
])
@pytest.mark.parametrize("nested", [True, False])
@pytest.mark.parametrize("available,conflict", [(True, False), (False, False), (True, True)])
def test_throughput_routes_guard_policies_and_report_failed_runtime_saves(
    function_name, nested, available, conflict,
):
    policies = {"messages": {"last_scale_up_at": "before", "enabled": True}}
    store = SettingsStore({
        "cosmos_throughput_container_policies": policies,
    }, available=available, conflict=conflict)
    delta = {"cosmos_throughput_last_checked_at": "now"}
    if nested:
        delta["cosmos_throughput_container_policies"] = {
            "messages": {"last_scale_up_at": "now", "enabled": True},
        }
    scaling_calls = []
    audit_calls = []
    scope = "container" if nested else "database"
    container_name = "messages" if nested else ""
    scale_result = {
        "scope": scope, "container_name": container_name,
        "from_ru": 400, "to_ru": 800, "mode": "manual",
        "from_mode": "manual", "to_mode": "autoscale",
    }

    def set_database_throughput(settings, target_ru, **kwargs):
        scaling_calls.append((target_ru, kwargs))
        return dict(scale_result)

    def build_runtime_update(**kwargs):
        assert kwargs["settings"] is store.snapshot
        return deepcopy(delta)

    route = load_function(
        "route_backend_settings.py", function_name, store,
        session={"user": {"email": "admin@example.test"}},
        request=SimpleNamespace(get_json=lambda **kwargs: {
            "direction": "up", "container_name": container_name,
        }),
        get_cosmos_throughput_status=lambda *args, **kwargs: {"throughput": {"current_ru": 400}},
        calculate_manual_scale_target=lambda *args, **kwargs: 800,
        calculate_manual_to_autoscale_target=lambda *args, **kwargs: 800,
        set_database_throughput=set_database_throughput,
        build_runtime_update=build_runtime_update,
        log_general_admin_action=lambda **kwargs: audit_calls.append(kwargs),
        CosmosThroughputError=ValueError,
    )
    result, status = response_parts(route())
    expected_success = available and not (conflict and nested)
    assert_delta(store, delta, etag='"original"' if nested else None)
    assert len(scaling_calls) == 1
    assert bool(audit_calls) is expected_success
    assert status == (200 if expected_success else 500)
    assert result.get("success", False) is expected_success
    if expected_success:
        expected = {
            "success": True, "scope": scope, "container_name": container_name,
            "from_ru": 400, "to_ru": 800,
        }
        if function_name == "scale_cosmos_throughput_admin":
            expected.update({"direction": "up", "mode": "manual"})
        else:
            expected.update({
                "from_mode": "manual", "to_mode": "autoscale",
                "reason": "manual_to_autoscale_conversion",
            })
        assert result == expected
    else:
        assert "runtime settings could not be saved" in result["error"]
        assert store.live["cosmos_throughput_container_policies"] == policies


@pytest.mark.parametrize("available,conflict", [(True, False), (False, False), (True, True)])
def test_custom_request_access_page_reports_failed_setting_save(available, conflict):
    store = SettingsStore(available=available, conflict=conflict)
    saved_pages = []

    def save_custom_page(payload, **kwargs):
        saved_pages.append(deepcopy(payload))
        return payload

    route = load_function(
        "route_custom_pages.py", "admin_create_request_access_custom_page", store,
        validate_custom_page_metadata=lambda *args, **kwargs: [],
        save_custom_page=save_custom_page,
        _current_admin_user_id=lambda: "admin",
    )
    result, status = response_parts(route())
    assert_delta(store, {
        "access_request_button_enabled", "access_request_button_text", "access_request_page_url",
    })
    assert len(saved_pages) == 1
    assert status == (201 if available else 500)
    if available:
        assert result == {"page": saved_pages[0], "access_request_button_enabled": True}
    else:
        assert "access_request_button_enabled" not in result
        assert "Page saved" in result["error"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
