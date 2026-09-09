# test_app_settings_store_consistency.py
"""
Regression tests for shared settings and conditional writes.
Version: 0.261.025
Implemented in: 0.261.025

Independent store objects represent workers. Fake services exercise ETag conflicts,
interrupted publication and lease expiry without network access or wall-clock sleeps.
"""

import ast
import copy
import importlib.util
import json
import logging
from pathlib import Path
import socket
import secrets
import sys
from types import SimpleNamespace
import types

import pytest
from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from redis.exceptions import ConnectionError as RedisConnectionError


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
SPEC = importlib.util.spec_from_file_location("settings_store_under_test", APP / "app_settings_store.py")
store_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(store_module)
AppSettingsStore = store_module.AppSettingsStore
SettingsConflictError = store_module.SettingsConflictError
SettingsUnavailableError = store_module.SettingsUnavailableError


class FakeRedis:
    def __init__(self):
        self.raw = None
        self.failed = False
        self.fail_publication = False
        self.reads = 0

    def get(self, key):
        assert key == store_module.SETTINGS_STATE_KEY
        self.reads += 1
        if self.failed:
            raise RedisConnectionError("offline")
        return self.raw

    def eval(self, script, key_count, key, previous, replacement):
        assert script == store_module.COMPARE_AND_SET
        assert key_count == 1 and key == store_module.SETTINGS_STATE_KEY
        if self.failed or (self.fail_publication and json.loads(replacement)["state"] == "ready"):
            raise RedisConnectionError("offline")
        previous = previous.decode() if isinstance(previous, bytes) else previous
        if (self.raw.decode() if self.raw else "") != previous:
            return 0
        self.raw = replacement.encode()
        return 1


class FakeCosmos:
    def __init__(self):
        self.etag = 1
        self.document = {"id": "app_settings", "_etag": "1", "enabled": False}
        self.before_replace = None
        self.after_replace = None
        self.before_create = None
        self.failed = False
        self.writes = 0
        self.tokens = []

    def _response(self, response_hook=None):
        if response_hook:
            response_hook({"x-ms-session-token": f"token-{self.etag}"}, self.document)
        return copy.deepcopy(self.document)

    def read_item(self, item, partition_key, *, response_hook=None, session_token=None):
        assert item == partition_key == "app_settings"
        self.tokens.append(session_token)
        if self.failed:
            raise RuntimeError("Cosmos offline")
        if self.document is None:
            raise CosmosResourceNotFoundError(status_code=404, message="Missing")
        return self._response(response_hook)

    def replace_item(self, item, body, *, etag, match_condition, response_hook=None, session_token=None):
        assert match_condition == MatchConditions.IfNotModified
        callback, self.before_replace = self.before_replace, None
        if callback:
            callback()
        if self.document["_etag"] != etag:
            raise CosmosAccessConditionFailedError(status_code=412, message="Conflict")
        self.etag += 1
        self.writes += 1
        self.document = {**copy.deepcopy(body), "_etag": str(self.etag)}
        result = self._response(response_hook)
        callback, self.after_replace = self.after_replace, None
        if callback:
            callback()
        return result

    def create_item(self, body, *, response_hook=None):
        callback, self.before_create = self.before_create, None
        if callback:
            callback()
        if self.document is not None:
            raise CosmosResourceExistsError(status_code=409, message="Exists")
        self.document = {**copy.deepcopy(body), "_etag": str(self.etag)}
        self.writes += 1
        return self._response(response_hook)


@pytest.fixture
def world(monkeypatch):
    def deny_network(*_args, **_kwargs):
        raise AssertionError("Tests must not contact external services")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    now = [1000.0]
    monkeypatch.setattr(store_module.time, "time", lambda: now[0])
    cosmos, redis = FakeCosmos(), FakeRedis()
    fallback = []
    workers = [
        AppSettingsStore(cosmos, redis, redis_required=True, on_fallback=fallback.append)
        for _ in range(3)
    ]
    return SimpleNamespace(cosmos=cosmos, redis=redis, a=workers[0], b=workers[1],
                           c=workers[2], now=now, fallback=fallback)


def change(**updates):
    return lambda document: {**document, **updates}


def test_every_worker_reads_shared_state_after_completed_save(world):
    assert not world.a.read()["enabled"]
    assert not world.b.read()["enabled"]
    stored = world.a.write(change(enabled=True))
    for worker in (world.b, world.a, world.c, world.b):
        assert worker.read()["enabled"]
        assert worker.read()["_etag"] == stored["_etag"]


def test_no_redis_mode_has_no_worker_snapshot(world):
    a, b = AppSettingsStore(world.cosmos), AppSettingsStore(world.cosmos)
    assert not b.read()["enabled"]
    a.write(change(enabled=True))
    assert b.read()["enabled"]


def test_returned_settings_do_not_mutate_shared_document(world):
    settings = world.a.read()
    settings["enabled"] = "unsaved"
    assert world.b.read()["enabled"] is False


def test_partial_writes_merge_authoritative_document_on_conflict(world):
    store = AppSettingsStore(world.cosmos)
    world.cosmos.before_replace = lambda: store.write(change(enabled=True))
    stored = store.write(change(last_update_check_time="new"))
    assert stored["enabled"]
    assert stored["last_update_check_time"] == "new"
    assert world.cosmos.writes == 2


def test_stale_form_is_rejected_without_poisoning_cache(world):
    stale = world.a.read()
    world.b.write(change(enabled=True))
    before = world.redis.raw
    with pytest.raises(SettingsConflictError):
        world.a.write(change(enabled=False), expected_etag=stale["_etag"])
    assert world.redis.raw == before
    assert world.b.read()["enabled"]


def test_unavailable_redis_rejects_save_before_cosmos_write(world):
    world.a.read()
    before = copy.deepcopy(world.cosmos.document)
    world.redis.failed = True
    with pytest.raises(SettingsUnavailableError):
        world.a.write(change(enabled=True))
    assert world.cosmos.document == before
    assert world.b.read() == before
    assert world.fallback


def test_client_construction_failure_does_not_enable_cosmos_only_writes(world):
    store = AppSettingsStore(world.cosmos, redis_required=True)
    with pytest.raises(SettingsUnavailableError):
        store.write(change(enabled=True))
    assert store.read()["enabled"] is False
    assert world.cosmos.writes == 0


def test_interrupted_publication_never_restores_previous_payload(world):
    world.a.read()
    world.redis.fail_publication = True
    with pytest.raises(SettingsUnavailableError):
        world.a.write(change(enabled=True))
    assert json.loads(world.redis.raw)["state"] == "pending"
    assert world.b.read()["enabled"]
    world.redis.fail_publication = False
    world.now[0] += store_module.WRITE_LEASE_SECONDS + 1
    assert world.c.read()["enabled"]
    assert json.loads(world.redis.raw)["state"] == "ready"


def test_expired_writer_cannot_commit_over_recovery_and_new_save(world):
    world.a.read()

    def take_over():
        world.now[0] += store_module.WRITE_LEASE_SECONDS + 1
        world.b.read()
        world.b.write(change(enabled=True))

    world.cosmos.before_replace = take_over
    with pytest.raises(SettingsConflictError):
        world.a.write(change(enabled=False))
    assert world.c.read()["enabled"]


def test_delayed_publication_cannot_replace_newer_ready_state(world):
    world.a.read()

    def newer_save():
        world.now[0] += store_module.WRITE_LEASE_SECONDS + 1
        world.b.read()
        world.b.write(change(enabled=True))

    world.cosmos.after_replace = newer_save
    with pytest.raises(SettingsUnavailableError):
        world.a.write(change(enabled=False))
    assert world.c.read()["enabled"]


def test_migration_retries_against_newer_document(world):
    store = AppSettingsStore(world.cosmos)
    world.cosmos.before_replace = lambda: store.write(change(enabled=True))

    def migrate(current):
        current.setdefault("new_default", "default")
        return current

    assert store.write(migrate)["enabled"]
    assert world.cosmos.document["new_default"] == "default"


def test_session_token_travels_with_shared_payload(world):
    world.a.read()
    state = json.loads(world.redis.raw)
    world.b.read(use_cosmos=True)
    assert world.cosmos.tokens[-1] == state["session_token"]
    world.b.write(change(enabled=True))
    assert state["session_token"] in world.cosmos.tokens


def test_cosmos_failure_cannot_return_old_worker_data(world):
    world.a.read()
    world.redis.failed = True
    world.cosmos.failed = True
    with pytest.raises(RuntimeError, match="Cosmos offline"):
        world.b.read()


def test_creation_and_creation_race_preserve_winner(world):
    world.cosmos.document = None
    store = AppSettingsStore(world.cosmos)
    world.cosmos.before_create = lambda: AppSettingsStore(world.cosmos).write(
        lambda current: current,
        defaults={"id": "app_settings", "enabled": True},
    )
    result = store.write(lambda current: current, defaults={"id": "app_settings", "enabled": False})
    assert result["enabled"]


def load_update_settings(store):
    tree = ast.parse((APP / "functions_settings.py").read_text(encoding="utf-8-sig"))
    names = {"update_settings", "coerce_multi_model_endpoint_enablement"}
    namespace = {
        "copy": copy, "logging": logging,
        "COSMOS_METADATA_FIELDS": store_module.COSMOS_METADATA_FIELDS,
        "SETTINGS_REVISION_FIELD": store_module.SETTINGS_REVISION_FIELD,
        "app_settings_cache": SimpleNamespace(get_settings_store=lambda: store),
        "log_event": lambda *_args, **_kwargs: None,
        "is_tabular_processing_enabled": lambda _settings: False,
    }
    for name in (
        "normalize_group_workflow_assignment_settings", "normalize_agents_page_promoted_popular_settings",
        "normalize_document_access_index_required_settings", "normalize_inbound_mcp_settings",
        "normalize_public_workspace_display_settings", "normalize_key_vault_reminder_settings",
        "normalize_model_endpoint_identity_header_settings",
    ):
        namespace[name] = lambda settings: None
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "functions_settings.py", "exec"), namespace)
    return namespace["update_settings"]


def test_real_update_settings_rejects_old_full_snapshot_and_merges_deltas(world):
    old = world.a.read()
    update_a, update_b = load_update_settings(world.a), load_update_settings(world.b)
    assert update_a({"enabled": True})
    assert update_b({"last_update_check_time": "new"})
    assert world.c.read()["enabled"]
    old["last_update_check_time"] = "stale"
    assert update_b(old) is False
    assert world.c.read()["enabled"]


def test_startup_does_not_publish_bootstrap_snapshot():
    for filename in ("app.py", "simplechat_scheduler.py"):
        source = (APP / filename).read_text(encoding="utf-8-sig")
        assert "app_settings_cache.update_settings_cache(settings)" not in source


def load_get_settings(store):
    """Use the real getter/default-merge flow, isolating unrelated feature normalizers."""
    tree = ast.parse((APP / "functions_settings.py").read_text(encoding="utf-8-sig"))
    definitions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    getter = definitions["get_settings"]
    namespace = {
        "copy": copy, "logging": logging, "secrets": secrets,
        "app_settings_cache": SimpleNamespace(get_settings_store=lambda: store),
        "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
        "SettingsConflictError": SettingsConflictError,
        "SettingsUnavailableError": SettingsUnavailableError,
        "log_event": lambda *_args, **_kwargs: None,
        "_apply_tabular_parity_env_kill_switch": lambda settings: settings,
        "attach_public_workspace_label_context": lambda settings: settings,
        "normalize_document_intelligence_pdf_image_extraction_mode": lambda mode: mode,
        "is_tabular_processing_enabled": lambda settings: False,
    }
    for node in ast.walk(getter.body[0]):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in namespace:
            if node.id.startswith("get_default_"):
                namespace[node.id] = lambda: {}
            elif node.id == "INBOUND_MCP_SETTINGS_DEFAULTS":
                namespace[node.id] = {}
            else:
                namespace[node.id] = 1 if "MAX" in node.id or "MIN" in node.id or "SIZE" in node.id or "PAGES" in node.id else ""
    normalizer = next(node for node in getter.body if isinstance(node, ast.FunctionDef) and node.name == "normalize_loaded_settings")
    for node in ast.walk(normalizer):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name.startswith(("normalize_", "apply_custom_")) and name not in namespace:
                namespace[name] = lambda settings: False
    nodes = [getter, definitions["deep_merge_dicts"]]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "functions_settings.py", "exec"), namespace)
    return namespace["get_settings"]


def test_real_get_settings_migrations_are_stable_after_publication(world):
    getter = load_get_settings(world.a)
    first = getter()
    assert first is not None
    writes = world.cosmos.writes
    second = getter()
    assert second == first
    assert world.cosmos.writes == writes


def test_real_get_settings_migration_does_not_revert_an_admin_write(world):
    world.a.read()
    getter = load_get_settings(world.a)

    def concurrent_writer():
        AppSettingsStore(world.cosmos).write(change(enabled=True))

    world.cosmos.before_replace = concurrent_writer
    result = getter()
    assert result is not None and result["enabled"]
    assert world.cosmos.document["enabled"]


def test_real_get_settings_defers_migration_during_redis_outage(world):
    world.redis.failed = True
    before = copy.deepcopy(world.cosmos.document)
    result = load_get_settings(world.a)()
    assert result is not None
    assert world.cosmos.document == before


def test_real_get_settings_creates_defaults_without_overwriting_winner(world):
    world.cosmos.document = None
    getter = load_get_settings(AppSettingsStore(world.cosmos))
    assert getter() is not None
    assert world.cosmos.document["id"] == "app_settings"


def test_missing_shared_document_can_be_initialized_without_an_abandoned_marker(world):
    world.cosmos.document = None
    assert load_get_settings(world.a)() is not None
    assert json.loads(world.redis.raw)["state"] == "ready"


def test_logging_guard_handles_recursive_cache_failure():
    tree = ast.parse((APP / "functions_appinsights.py").read_text(encoding="utf-8-sig"))
    definition = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_load_logging_settings")
    namespace = {
        "_logging_settings_load_state": SimpleNamespace(),
        "Dict": dict,
        "Any": object,
    }
    calls = []

    def recursive_cache_read():
        calls.append(1)
        assert namespace["_load_logging_settings"]() == {}
        raise RedisConnectionError("offline")

    namespace["app_settings_cache"] = SimpleNamespace(get_settings_cache=recursive_cache_read)
    exec(compile(ast.Module(body=[definition], type_ignores=[]), "functions_appinsights.py", "exec"), namespace)
    assert namespace["_load_logging_settings"]() == {}
    assert calls == [1]
    assert namespace["_logging_settings_load_state"].active is False


def load_cache_module(world, monkeypatch):
    monkeypatch.syspath_prepend(str(APP))
    config = types.ModuleType("config")
    config.cosmos_settings_container = world.cosmos
    insights = types.ModuleType("functions_appinsights")
    insights.log_event = lambda *_args, **_kwargs: None
    client_module = types.ModuleType("functions_redis_client")
    client_module.AUTH_TYPE_MANAGED_IDENTITY = "managed_identity"
    client_module.CREDENTIAL_PURPOSE_APP_CACHE = "app_cache"
    client_module.create_redis_client = lambda **_kwargs: world.redis
    monkeypatch.setitem(sys.modules, "config", config)
    monkeypatch.setitem(sys.modules, "functions_appinsights", insights)
    monkeypatch.setitem(sys.modules, "functions_redis_client", client_module)
    spec = importlib.util.spec_from_file_location("cache_wiring_under_test", APP / "app_settings_cache.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_worker_configuration_does_not_publish_startup_snapshot(world, monkeypatch):
    world.cosmos.document.update(enable_redis_cache=True, redis_url="unused.invalid")
    cache = load_cache_module(world, monkeypatch)
    snapshot = cache.get_settings_store().read()
    world.b.write(change(enabled=True))
    cache.configure_app_cache(snapshot)
    assert cache.get_settings_cache()["enabled"]
    cache.update_settings_cache(snapshot)
    assert world.c.read()["enabled"]
    assert not hasattr(cache, "APP_SETTINGS_CACHE")


def test_actual_cache_initialization_failure_keeps_write_requirement(world, monkeypatch):
    world.cosmos.document.update(enable_redis_cache=True, redis_url="unused.invalid")
    cache = load_cache_module(world, monkeypatch)

    def unavailable_client(**_kwargs):
        raise ValueError("Client cannot be created")

    cache.create_redis_client = unavailable_client
    cache.configure_app_cache(world.cosmos.document)
    assert cache.APP_SETTINGS_STORE.redis_required is True
    assert cache.get_settings_cache()["enabled"] is False
    with pytest.raises(RuntimeError, match="Configured Redis is unavailable"):
        cache.APP_SETTINGS_STORE.write(change(enabled=True))
    assert world.cosmos.writes == 0
