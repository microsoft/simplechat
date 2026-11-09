# test_plugin_discovery_identity.py
"""
Functional tests for canonical plugin discovery and instance isolation.
Version: 0.261.423
Implemented in: 0.261.421

Production discovery, logged registration, classic loading, and real bootstrap
imports run with external I/O isolated. Fresh normal and optimized processes
check import order without substituting config or plugin modules.
"""

import importlib
import json
import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from importlib.metadata import version
from pathlib import Path

import pytest
from flask import Flask, session
from semantic_kernel import Kernel

from test_orchestration_harness_routes import modules


__all__ = ["modules"]
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
IMPORT_ORDERS = (
    ("document_search_plugin", "plugin_loader", "logged_plugin_loader", "classic"),
    ("plugin_loader", "logged_plugin_loader", "classic", "document_search_plugin"),
    ("logged_plugin_loader", "classic", "plugin_loader", "document_search_plugin"),
    ("classic", "plugin_loader", "logged_plugin_loader", "document_search_plugin"),
)
COLD_IMPORT_PROBE = """
import importlib
import json
import socket
import sys
from pathlib import Path
from unittest.mock import patch
from test_support.offline_bootstrap import offline_app_imports

dns_attempts = []
def no_dns(*args, **kwargs):
    dns_attempts.append(True)
    raise AssertionError("Cold plugin import attempted DNS access.")

with offline_app_imports() as environment, patch.object(socket, "getaddrinfo", no_dns):
    for name in json.loads(sys.argv[1]):
        module_name = "semantic_kernel_loader" if name == "classic" else "semantic_kernel_plugins." + name
        importlib.import_module(module_name)
        if name == "plugin_loader":
            discovered_early = importlib.import_module(module_name).discover_plugins()
            reader_early = importlib.import_module("semantic_kernel_plugins.document_search_plugin")
            if discovered_early.get("DocumentSearchPlugin") is not reader_early.DocumentSearchPlugin:
                raise AssertionError("Discovery-first loading created a different reader class.")
    discovery = importlib.import_module("semantic_kernel_plugins.plugin_loader")
    first = discovery.discover_plugins()
    second = discovery.discover_plugins()
    if "DocumentSearchPlugin" not in first or first.keys() != second.keys():
        raise AssertionError("Installed plugin discovery changed between calls.")
    for name, plugin_class in first.items():
        owner = importlib.import_module(plugin_class.__module__)
        canonical = vars(owner).get(plugin_class.__name__)
        if canonical is not plugin_class or second[name] is not plugin_class:
            raise AssertionError("Installed plugin class identity was not preserved.")
    importlib.import_module("functions_orchestration_bootstrap")
    importlib.import_module("app")
    importlib.import_module("functions_orchestration_execution")
    config = importlib.import_module("config")
    if Path(config.__file__).resolve() != Path(sys.argv[2]).resolve():
        raise AssertionError("The real config module was not imported.")
    if environment.network_attempts or dns_attempts:
        raise AssertionError("A blocked network attempt was swallowed during startup.")
    print("PLUGIN_IDENTITY_RESULT:" + json.dumps({"plugins": len(first), "network_attempts": 0}))
"""


@pytest.fixture
def discovery(modules):
    return importlib.import_module("semantic_kernel_plugins.plugin_loader")


@pytest.fixture
def request_app():
    app = Flask(__name__)
    app.secret_key = "plugin-identity-test"
    return app


def test_repeated_discovery_reuses_every_canonical_plugin_class(discovery):
    first = discovery.discover_plugins()
    second = discovery.discover_plugins()
    assert "DocumentSearchPlugin" in first
    assert first.keys() == second.keys()
    for name, plugin_class in first.items():
        owner = importlib.import_module(plugin_class.__module__)
        canonical = vars(owner).get(plugin_class.__name__)
        assert canonical is plugin_class, name
        assert second[name] is plugin_class, name


def test_required_template_parser_is_explicitly_pinned_and_importable(modules):
    requirements = (APP / "requirements.txt").read_text(encoding="utf-8").splitlines()
    pins = [line.partition("==")[2] for line in requirements if line.lower().startswith("pymeta3==")]
    parser = importlib.import_module("pymeta.grammar")
    installed = version("PyMeta3")
    assert len(pins) == 1 and installed == pins[0]
    assert callable(parser.OMeta)


def test_logged_reader_instances_keep_separate_configuration(discovery, request_app):
    loader_module = importlib.import_module("semantic_kernel_plugins.logged_plugin_loader")
    reader_module = importlib.import_module("semantic_kernel_plugins.document_search_plugin")
    manifests = [
        {
            "name": name, "type": "document_search",
            "additionalFields": {"allowed_scopes": [scope]},
        }
        for name, scope in (("personal_reader", "personal"), ("public_reader", "public"))
    ]
    originals = deepcopy(manifests)
    loaders = [loader_module.LoggedPluginLoader(Kernel()) for _ in manifests]
    loaded = [
        loader.load_plugin_from_manifest(manifest, user_id="owner")
        for loader, manifest in zip(loaders, manifests)
    ]
    assert loaded == [True, True]
    readers = [loader.plugin_instances[0] for loader in loaders]
    assert all(type(reader) is reader_module.DocumentSearchPlugin for reader in readers)
    assert readers[0] is not readers[1]
    with request_app.test_request_context():
        session["user"] = {"oid": "owner"}
        initial_scopes = [reader._resolve_doc_scope_requests("all") for reader in readers]
        readers[0].manifest["additionalFields"]["allowed_scopes"].append("group")
        changed_scopes = [reader._resolve_doc_scope_requests("all") for reader in readers]
    assert initial_scopes == [["personal"], ["public"]]
    assert changed_scopes == [["personal", "group"], ["public"]]
    assert manifests == originals
    functions = [loader.kernel.get_list_of_function_metadata({}) for loader in loaders]
    assert all(len(items) == 4 for items in functions)


def test_concurrent_discovery_and_loading_keep_reader_identity_and_scope(discovery, request_app):
    loader_module = importlib.import_module("semantic_kernel_plugins.logged_plugin_loader")
    reader_module = importlib.import_module("semantic_kernel_plugins.document_search_plugin")

    def load_reader(index):
        scope = ("personal", "group", "public")[index % 3]
        user_id = f"owner-{index}"
        with request_app.test_request_context():
            session["user"] = {"oid": user_id}
            classes = discovery.discover_plugins()
            loader = loader_module.LoggedPluginLoader(Kernel())
            loaded = loader.load_plugin_from_manifest({
                "name": f"reader_{index}", "type": "document_search",
                "additionalFields": {"allowed_scopes": [scope]},
            }, user_id=user_id)
            reader = loader.plugin_instances[0] if loaded else None
            scopes = reader._resolve_doc_scope_requests("all") if reader is not None else None
            observed_user = reader._get_user_id() if reader is not None else None
        return loaded, classes.get("DocumentSearchPlugin"), reader, scopes, scope, observed_user, user_id

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(load_reader, range(12)))
    readers = []
    for loaded, plugin_class, reader, scopes, expected_scope, observed_user, expected_user in results:
        assert loaded
        assert plugin_class is reader_module.DocumentSearchPlugin
        assert type(reader) is reader_module.DocumentSearchPlugin
        assert scopes == [expected_scope]
        assert observed_user == expected_user
        readers.append(reader)
    assert len({id(reader) for reader in readers}) == len(readers)


def test_module_import_failure_is_logged_without_private_exception_text(
    discovery, monkeypatch, caplog,
):
    telemetry = importlib.import_module("functions_appinsights")
    logger = logging.getLogger("test.plugin.discovery")
    monkeypatch.setattr(telemetry, "get_appinsights_logger", lambda: logger)
    monkeypatch.setattr(telemetry, "_load_logging_settings", lambda: {})
    original_import = importlib.import_module

    def fail_optional_module(name, package=None):
        if name == "semantic_kernel_plugins.unavailable_plugin":
            raise ImportError("PRIVATE_PLUGIN_IMPORT_SENTINEL")
        return original_import(name, package)

    monkeypatch.setattr(discovery.os, "listdir", lambda path: [
        "document_search_plugin.py", "unavailable_plugin.py", "base_plugin.py", "__init__.py",
    ])
    monkeypatch.setattr(discovery.importlib, "import_module", fail_optional_module)
    with caplog.at_level(logging.WARNING, logger=logger.name):
        found = discovery.discover_plugins()
    assert "DocumentSearchPlugin" in found
    records = [
        record for record in caplog.records
        if getattr(record, "sc_message", None) == "[PLUGIN_LOADER] Plugin module could not be loaded."
    ]
    assert len(records) == 1
    assert records[0].sc_error_type == "ImportError"
    properties = [
        {key: value for key, value in record.__dict__.items() if key.startswith("sc_")}
        for record in records
    ]
    assert "PRIVATE_PLUGIN_IMPORT_SENTINEL" not in json.dumps(properties)


@pytest.mark.parametrize("order", IMPORT_ORDERS, ids=("reader-first", "discovery-first", "logged-first", "classic-first"))
@pytest.mark.parametrize("optimized", [False, True], ids=("normal", "optimized"))
def test_real_cold_import_orders_preserve_identity_and_network_free_startup(order, optimized):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(APP), str(TESTS)))
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [
        sys.executable, *(["-O"] if optimized else []), "-c", COLD_IMPORT_PROBE,
        json.dumps(order), str(APP / "config.py"),
    ]
    result = subprocess.run(
        command, cwd=ROOT, env=environment, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    records = [
        line.removeprefix("PLUGIN_IDENTITY_RESULT:")
        for line in result.stdout.splitlines() if line.startswith("PLUGIN_IDENTITY_RESULT:")
    ]
    assert len(records) == 1
    report = json.loads(records[0])
    assert report["plugins"] > 1
    assert report["network_attempts"] == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
