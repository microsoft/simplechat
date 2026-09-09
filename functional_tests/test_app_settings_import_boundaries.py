# test_app_settings_import_boundaries.py
"""
Regression coverage for CodeQL py/cyclic-import and py/side-effect-in-assert.
Version: 0.261.027
Implemented in: 0.261.027

Import real cache/logging modules in fresh interpreters with configuration imports
and network access blocked. Exercise initialization from supplied settings in both
normal and optimized Python; module stubs cannot mask the dependency boundary.
"""

import ast
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
FORBIDDEN_MODULES = {"config", "functions_settings", "functions_appinsights", "functions_redis_client"}
BOOTSTRAP_PROBE = r'''
import ast
import builtins
import copy
import importlib
import json
import logging
from pathlib import Path
import socket
import sys
import threading
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
forbidden = {
    "config", "single_app.config", "application.single_app.config",
    "functions_settings", "functions_redis_client",
}
real_import = builtins.__import__

def guarded_import(name, *args, **kwargs):
    if name in forbidden:
        raise AssertionError("Reverse bootstrap import: " + name)
    return real_import(name, *args, **kwargs)

def no_network(*args, **kwargs):
    raise AssertionError("Network access during import/bootstrap")

def check(condition, message):
    if not condition:
        raise AssertionError(message)

class Container:
    def __init__(self):
        self.reads = 0
        self.version = 0
        self.redis_enabled = False

    def read_item(self, item, partition_key, **kwargs):
        self.reads += 1
        if item == "app_settings":
            return {
                "id": item, "_etag": "test-etag", "from_cosmos": True,
                "enable_redis_cache": self.redis_enabled,
            }
        return {"id": item, "version": self.version}

    def upsert_item(self, body):
        self.version = body["version"]

class Redis:
    def get(self, key):
        return json.dumps({"state": "ready", "document": {
            "id": "app_settings", "_etag": "test-etag", "from_redis": True,
        }})

with patch.object(builtins, "__import__", guarded_import), patch.object(socket.socket, "connect", no_network):
    importlib.import_module(sys.argv[2])
    cache = importlib.import_module("app_settings_cache")
    insights = importlib.import_module("functions_appinsights")
    logger = logging.getLogger("import_boundary_probe")
    logger.handlers = [logging.NullHandler()]
    logger.propagate = False
    insights._appinsights_logger = logger
    settings_container, governance_container = Container(), Container()
    factory_calls = []
    factory_failure = [False]

    def factory(**kwargs):
        factory_calls.append(kwargs)
        if factory_failure[0]:
            raise ValueError("synthetic Redis construction failure")
        return Redis()

    dependencies = cache.AppCacheDependencies(
        settings_container=settings_container,
        governance_container=governance_container,
        create_redis_client=factory,
        log_event=insights.log_event,
    )
    try:
        cache.get_settings_store()
    except RuntimeError:
        pass
    else:
        raise AssertionError("Unconfigured accessor silently bootstrapped")

    from azure.cosmos.exceptions import CosmosResourceNotFoundError
    from app_settings_store import AppSettingsStore
    owner_source = (Path(sys.argv[1]) / "functions_settings.py").read_text(encoding="utf-8-sig")
    owner_tree = ast.parse(owner_source)
    owner_nodes = [
        node for node in owner_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {
            "_get_app_cache_dependencies", "_get_app_settings_store",
            "configure_application_cache",
        }
    ]
    owner = {
        "app_settings_cache": cache,
        "_settings_store_init_lock": threading.Lock(),
        "AppSettingsStore": AppSettingsStore,
        "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
        "cosmos_settings_container": settings_container,
        "cosmos_governance_policies_container": governance_container,
        "log_event": insights.log_event,
    }
    exec(compile(ast.Module(body=owner_nodes, type_ignores=[]), "settings_owner_bootstrap", "exec"), owner)

    for enabled in (False, True):
        cache.APP_SETTINGS_STORE = None
        cache.get_settings_cache = None
        settings_container.redis_enabled = enabled
        bootstrap = owner["_get_app_settings_store"]()
        check(bootstrap.redis_required == enabled, "Bootstrap ignored persisted Redis enablement")
        check(cache.APP_SETTINGS_STORE is None, "Temporary bootstrap reader was installed as a cache")
        if enabled:
            try:
                bootstrap.write(lambda document: document)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Bootstrap allowed Redis-required writes without a Redis client")
        settings = {"enable_redis_cache": enabled, "redis_url": "unused.invalid"}
        original = copy.deepcopy(settings)
        reads_before = settings_container.reads
        owner["configure_application_cache"](settings, redis_client_factory=factory)
        check(settings == original, "Configuration mutated the settings payload")
        check(settings_container.reads == reads_before, "Configuration reloaded settings")
        configured = owner["_get_app_settings_store"]()
        check(configured is cache.APP_SETTINGS_STORE, "Owner did not return the configured shared store")
        check(settings_container.reads == reads_before, "Initialized owner reloaded bootstrap settings")
        loaded = cache.get_settings_cache()
        check(loaded.get("from_redis" if enabled else "from_cosmos"), "Wrong settings backend")
        if enabled:
            check(factory_calls[-1]["settings"] is settings, "Factory ignored the supplied settings")
        else:
            version = cache.get_governance_cache_version()
            bumped = cache.bump_governance_cache_version()
            check(bumped == version + 1, "Injected governance container was not used")

    factory_failure[0] = True
    cache.configure_app_cache(
        {"enable_redis_cache": True, "redis_url": "unused.invalid"},
        dependencies=dependencies,
    )
    check(cache.get_settings_store().redis_required, "Redis write requirement was silently disabled")
    loaded = cache.get_settings_cache()
    check(loaded.get("from_cosmos"), "Failed Redis did not use the injected Cosmos reader")
    check(not any(name in sys.modules for name in forbidden), "Bootstrap loaded a forbidden module")
print("PASS: cold imports and settings-driven configuration; no reverse imports or network")
'''


@pytest.mark.parametrize("first_module", ["app_settings_cache", "functions_appinsights"])
@pytest.mark.parametrize("optimized", [False, True])
def test_real_imports_and_bootstrap_do_not_reenter_config(first_module, optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    result = subprocess.run(
        command + ["-c", BOOTSTRAP_PROBE, str(APP), first_module],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: cold imports" in result.stdout


def test_cache_dependency_graph_has_no_reverse_imports():
    """Inspect function-local imports too: deferring an edge does not remove it."""
    pending = ["app_settings_cache"]
    inspected = set()
    while pending:
        name = pending.pop()
        if name in inspected:
            continue
        inspected.add(name)
        tree = ast.parse((APP / f"{name}.py").read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            imports = []
            if isinstance(node, ast.ImportFrom):
                imports = [node.module or ""]
            elif isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            for imported in imports:
                normalized = imported.removeprefix("application.").removeprefix("single_app.").split(".")[0]
                assert normalized not in FORBIDDEN_MODULES, f"{name}:{node.lineno} imports {imported}"
                if (APP / f"{normalized}.py").is_file():
                    pending.append(normalized)
    assert "app_settings_store" in inspected


def test_consistency_assertions_only_inspect_results():
    """No settings operations, getter bootstrap, or database writes inside asserts."""
    tree = ast.parse((ROOT / "functional_tests" / "test_app_settings_store_consistency.py").read_text(encoding="utf-8"))
    pure_calls = {"len", "hasattr", "isinstance", "json.loads"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            for descendant in ast.walk(node.test):
                if isinstance(descendant, ast.Call):
                    function = ast.unparse(descendant.func)
                    assert function in pure_calls, f"Line {node.lineno}: execute {function} before asserting its result"


def test_web_and_scheduler_pass_the_real_factory_through_the_settings_owner():
    for filename in ("app.py", "simplechat_scheduler.py"):
        tree = ast.parse((APP / filename).read_text(encoding="utf-8-sig"))
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "configure_application_cache"
        ]
        assert len(calls) == 1
        call = calls[0]
        assert isinstance(call.args[0], ast.Name) and call.args[0].id == "settings"
        keywords = {kw.arg: ast.unparse(kw.value) for kw in call.keywords}
        assert keywords["redis_client_factory"] == "functions_redis_client.create_redis_client"
