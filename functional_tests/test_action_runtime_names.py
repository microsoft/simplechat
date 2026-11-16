# test_action_runtime_names.py
"""
Regression tests for saved action names and runtime-only kernel bindings.
Version: 0.261.347
Implemented in: 0.261.347

No external service or action operation is called by these registration tests.
"""

from copy import deepcopy
import ast
import importlib.util
from pathlib import Path
import subprocess
import sys
import types
from unittest.mock import Mock

import pytest
from semantic_kernel import Kernel
from semantic_kernel.functions import kernel_function

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Application path setup precedes bootstrap-free contract imports.
from action_runtime_contracts import register_action_plugin, runtime_plugin_names
from functions_action_manifest import bind_action_origin


class OfflineAction:
    @kernel_function
    def create_calendar_invite(self, subject: str) -> str:
        raise AssertionError("Registration must never invoke an action.")


def manifest(name, action_id="calendar", scope="personal", scope_id="owner"):
    return bind_action_origin(
        {"id": action_id, "name": name, "type": "m365_calendar"}, scope, scope_id,
    )


def test_reported_fed_action_registers_without_changing_saved_identity():
    action = manifest("FED-unblock-seven-20261019-a-FED-29-send-m365_calendar")
    before = deepcopy(action)
    kernel = Kernel()
    name = register_action_plugin(kernel, OfflineAction(), action)
    functions = kernel.get_full_list_of_function_metadata()
    assert action == before
    assert functions[0].plugin_name == name
    assert functions[0].name == "create_calendar_invite"
    assert name.replace("_", "").isalnum()
    assert len(functions[0].fully_qualified_name) <= 64


def test_valid_names_remain_compatible_and_aliases_do_not_collide():
    actions = [
        manifest("calendar-demo", "dash"),
        manifest("calendar_demo", "underscore"),
        manifest("calendar_demo", "group-action", "group", "team"),
        manifest("x" * 100, "long"),
    ]
    for ordered in (actions, list(reversed(actions))):
        kernel = Kernel()
        names = runtime_plugin_names(kernel, ordered)
        assert len(set(names.values())) == len(actions)
        for action in ordered:
            registered = register_action_plugin(kernel, OfflineAction(), action)
            assert registered == names[id(action)]
        assert len(kernel.plugins) == len(actions)
    simple = manifest("m365_calendar")
    assert register_action_plugin(Kernel(), OfflineAction(), simple) == "m365_calendar"


def test_core_plugin_collision_does_not_overwrite_core_or_rebind_an_action():
    kernel = Kernel()
    kernel.add_plugin(OfflineAction(), plugin_name="time")
    action = manifest("time")
    alias = register_action_plugin(kernel, OfflineAction(), action)
    assert alias != "time"
    assert set(kernel.plugins) == {"time", alias}
    assert register_action_plugin(kernel, OfflineAction(), action) == alias


def test_custom_kernel_facade_receives_only_the_runtime_name():
    from semantic_kernel.functions import KernelPlugin

    class Facade(OfflineAction):
        def get_kernel_plugin(self, plugin_name):
            return KernelPlugin.from_object(plugin_name, self)

    action = manifest("a-calendar")
    kernel = Kernel()
    name = register_action_plugin(kernel, Facade(), action)
    assert kernel.plugins[name].name == name
    assert action["name"] == "a-calendar"


def test_impossible_qualified_name_is_rejected_before_registration():
    class TooLong:
        @kernel_function(name="f" * 64)
        def execute(self):
            raise AssertionError("Must not invoke.")

    with pytest.raises(ValueError, match="tool name"):
        register_action_plugin(Kernel(), TooLong(), manifest("a"))


def test_companion_binding_preserves_scope_without_overwriting_its_query():
    from functions_action_manifest import copy_action_manifest, get_action_origin

    kernel = Kernel()
    query = manifest("FED-query")
    query_name = register_action_plugin(kernel, OfflineAction(), query)
    schema = copy_action_manifest(query)
    schema["name"] += "_schema"
    schema["type"] = "sql_schema"
    schema_name = register_action_plugin(kernel, OfflineAction(), schema, runtime_role="sql_schema")
    assert query_name != schema_name
    assert get_action_origin(schema) == get_action_origin(query)
    assert set(kernel.plugins) == {query_name, schema_name}


def test_short_valid_names_can_use_the_entire_qualified_name_budget():
    class LongOperation:
        @kernel_function(name="f" * 60)
        def execute(self):
            raise AssertionError("Must not invoke.")

    kernel = Kernel()
    name = register_action_plugin(kernel, LongOperation(), manifest("a"))
    assert name == "a"
    assert len(next(iter(kernel.plugins[name].functions.values())).metadata.fully_qualified_name) == 62


def test_real_logged_loader_returns_unique_runtime_outcomes(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "application" / "single_app" / "semantic_kernel_plugins" / "logged_plugin_loader.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    real = {
        "semantic_kernel", "semantic_kernel.functions", "action_runtime_contracts",
        "functions_action_manifest", "action_credential_contracts", "functions_m365_approvals",
        "functions_yamcs_operations",
    }
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.module in real:
            continue
        if node.module.split(".", 1)[0] in sys.stdlib_module_names:
            continue
        module = types.ModuleType(node.module)
        for item in node.names:
            value = (item.name.removesuffix("_PLUGIN_TYPE").lower()
                     if item.name.endswith("_PLUGIN_TYPE") else Mock())
            setattr(module, item.name, value)
        monkeypatch.setitem(sys.modules, node.module, module)
    spec = importlib.util.spec_from_file_location("offline_logged_action_loader", path)
    loader_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader_module)
    kernel = Kernel()
    loader = loader_module.LoggedPluginLoader(kernel)
    monkeypatch.setattr(loader, "_create_plugin_instance", lambda manifest: OfflineAction())
    monkeypatch.setattr(loader, "_wrap_plugin_functions", lambda *args: None)
    actions = [manifest("FED-action", "first"), manifest("FED-action", "second", "group", "team")]
    original = deepcopy(actions)
    results = loader.load_multiple_plugins(actions, "owner")
    assert len(results) == 2 and all(results.values())
    assert set(results) == set(kernel.plugins)
    assert actions == original


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_contract_and_recovery_cold_imports_are_bootstrap_free(optimized, reverse):
    root = Path(__file__).resolve().parents[1] / "application" / "single_app"
    modules = ["action_runtime_contracts", "functions_action_recovery"]
    if reverse:
        modules.reverse()
    probe = f"""
import importlib, socket, sys
sys.path.insert(0, {str(root)!r})
def refuse(*args, **kwargs):
    raise RuntimeError('Cold import attempted network access.')
socket.create_connection = refuse
socket.socket.connect = refuse
for name in {modules!r}:
    importlib.import_module(name)
if 'config' in sys.modules:
    raise RuntimeError('Cold import reached application bootstrap.')
"""
    result = subprocess.run(
        [sys.executable, *(["-O"] if optimized else []), "-B", "-c", probe],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
