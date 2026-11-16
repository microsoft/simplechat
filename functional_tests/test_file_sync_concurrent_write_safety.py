#!/usr/bin/env python3
# test_file_sync_concurrent_write_safety.py
"""
Functional test for File Sync concurrent write safety.
Version: 0.261.138
Implemented in: 0.261.138

This test ensures a File Sync run never overwrites a manager's change made while
the run was going (an edit, a disable, a delete, or an ignored path), and that a
manager's save never undoes a result the run recorded.

It loads the real functions_file_sync module against in-memory Cosmos containers
that enforce etag preconditions the way the service does, and interleaves the
writers deterministically. Remote file I/O, document ingestion and the other
application modules are stubbed; every write path under test is production code.
"""

import ast
import copy
import importlib.util
import os
import socket
import sys
import types
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from flask import Blueprint, Flask

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
FILE_SYNC_PATH = APP_ROOT / "functions_file_sync.py"
FILE_SYNC_ROUTES_PATH = APP_ROOT / "route_backend_file_sync.py"

GROUP_ID = "group-a"
SOURCE_ID = "source-1"
MANAGER_ID = "manager-1"
SHARE_ROOT = "\\\\files\\contracts"
PAST_NEXT_RUN = "2026-01-01T00:00:00+00:00"
SETTINGS = {
    "enable_file_sync": True,
    "enable_redis_cache": True,
    "redis_url": "redis.invalid",
    "redis_auth_type": "managed_identity",
    "file_sync_debug_logging": False,
}
CONSTANTS = {
    "CLIENT_ID": "test-client-id",
    "CLIENT_SECRET": "test-client-secret",
    "TENANT_ID": "test-tenant-id",
    "AZURE_STORAGE_ENDPOINT_SUFFIXES": ("core.windows.net",),
    "WORKSPACE_IDENTITY_SCOPE_GLOBAL": "global",
    "ui_trigger_word": "Stored_In_KeyVault",
}
_MISSING = object()


class FakeContainer:
    """An in-memory Cosmos container that enforces etag preconditions.

    ``replace_item`` refuses a stale etag with 412 and a missing record with 404;
    it never creates. ``before_replace`` holds callables that run, one per replace
    call, before the precondition is checked, to land a concurrent write exactly
    between a writer's read and its write.
    """

    def __init__(self, name, partition_field):
        self.name = name
        self.partition_field = partition_field
        self.records = {}
        self.calls = []
        self.before_replace = []
        self._etag_sequence = 0

    def _store(self, body):
        self._etag_sequence += 1
        stored = copy.deepcopy(dict(body))
        stored["_etag"] = f'"etag-{self._etag_sequence}"'
        self.records[(stored[self.partition_field], stored["id"])] = stored
        return copy.deepcopy(stored)

    def seed(self, body):
        return self._store(body)

    def get(self, item_id, partition_key):
        record = self.records.get((partition_key, item_id))
        return copy.deepcopy(record) if record is not None else None

    def writes(self, method):
        return [call for call in self.calls if call[0] == method]

    def read_item(self, item, partition_key, **kwargs):
        self.calls.append(("read_item", item))
        record = self.records.get((partition_key, item))
        if record is None:
            raise CosmosResourceNotFoundError(status_code=404, message="Entity does not exist")
        return copy.deepcopy(record)

    def replace_item(self, item, body, etag=None, match_condition=None, **kwargs):
        item_id = item if isinstance(item, str) else item["id"]
        self.calls.append(("replace_item", item_id))
        if self.before_replace:
            self.before_replace.pop(0)()
        record = self.records.get((body[self.partition_field], item_id))
        if record is None:
            raise CosmosResourceNotFoundError(status_code=404, message="Entity does not exist")
        if match_condition == MatchConditions.IfNotModified and etag != record["_etag"]:
            raise CosmosAccessConditionFailedError(status_code=412, message="Precondition failed")
        return self._store(body)

    def create_item(self, body, **kwargs):
        self.calls.append(("create_item", body["id"]))
        if (body[self.partition_field], body["id"]) in self.records:
            raise CosmosResourceExistsError(status_code=409, message="Entity already exists")
        return self._store(body)

    def upsert_item(self, body, **kwargs):
        self.calls.append(("upsert_item", body["id"]))
        return self._store(body)

    def delete_item(self, item, partition_key, **kwargs):
        self.calls.append(("delete_item", item))
        if self.records.pop((partition_key, item), None) is None:
            raise CosmosResourceNotFoundError(status_code=404, message="Entity does not exist")

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        # The code under test only lists every record in one source's partition.
        self.calls.append(("query_items", partition_key))
        return [
            copy.deepcopy(record)
            for (record_partition, _), record in self.records.items()
            if partition_key is None or record_partition == partition_key
        ]


class Recorder:
    def __init__(self):
        self.events = []
        self.activity = []

    def log_event(self, message, *args, **kwargs):
        self.events.append((message, kwargs.get("level"), kwargs.get("extra") or {}))

    def messages(self):
        return [message for message, _, _ in self.events]


def _partition_field(container_name):
    if "_sources_" not in container_name:
        return "source_id"
    if "_group_" in container_name:
        return "group_id"
    if "_public_" in container_name:
        return "public_workspace_id"
    return "user_id"


def _refuse(module_name, attribute):
    def refused(*args, **kwargs):
        raise AssertionError(f"The code under test called {module_name}.{attribute}, which this test does not model")

    refused.__name__ = attribute
    return refused


def _passthrough_decorator(function):
    return function


def _app_imports(module_path):
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            top_level = node.module.split(".")[0]
            if (APP_ROOT / f"{top_level}.py").exists() or (APP_ROOT / top_level).is_dir():
                yield node.module, [alias.name for alias in node.names]


def _stub_modules(module_path, behaviour, containers):
    """Stub every application module ``module_path`` imports.

    Names in ``behaviour`` get that behaviour; containers become fakes; anything
    else refuses to be called, so an unmodelled dependency fails loudly instead
    of returning a value of the wrong type.
    """
    modules = {}
    for module_name, names in _app_imports(module_path):
        if module_name in behaviour and isinstance(behaviour[module_name], types.ModuleType):
            modules[module_name] = behaviour[module_name]
            continue
        module = modules.setdefault(module_name, types.ModuleType(module_name))
        for name in names:
            if name.endswith("_container"):
                value = containers.setdefault(name, FakeContainer(name, _partition_field(name)))
            elif name in CONSTANTS:
                value = CONSTANTS[name]
            else:
                value = behaviour.get(module_name, {}).get(name) or _refuse(module_name, name)
            setattr(module, name, value)
    for module_name in list(modules):
        parts = module_name.split(".")
        for depth in range(1, len(parts)):
            package_name = ".".join(parts[:depth])
            package = modules.setdefault(package_name, types.ModuleType(package_name))
            package.__path__ = []
            setattr(package, parts[depth], modules[".".join(parts[:depth + 1])])
    return modules


@contextmanager
def _installed_modules(modules):
    originals = {name: sys.modules.get(name, _MISSING) for name in modules}
    sys.modules.update(modules)
    try:
        yield
    finally:
        for name, original in originals.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


@contextmanager
def _network_blocked():
    def refuse_connection(*args, **kwargs):
        raise AssertionError("The test attempted a network connection")

    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection
    socket.socket.connect = refuse_connection
    socket.create_connection = refuse_connection
    try:
        yield
    finally:
        socket.socket.connect = original_connect
        socket.create_connection = original_create_connection


def _load(module_path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def remote_path_for(relative_path):
    return f"{SHARE_ROOT}\\{relative_path}"


def remote_file(relative_path, modified_at, size):
    return {
        "remote_path": remote_path_for(relative_path),
        "relative_path": relative_path,
        "file_name": relative_path,
        "modified_at": modified_at,
        "size": size,
        "remote_change_token": None,
        "web_url": None,
    }


def finished_run(run_id, counts=None):
    return {
        "id": run_id,
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts or {},
    }


class Harness:
    def __init__(self, module, containers, recorder):
        self.module = module
        self.recorder = recorder
        self.sources = containers["cosmos_group_file_sync_sources_container"]
        self.items = containers["cosmos_group_file_sync_items_container"]
        self.runs = containers["cosmos_group_file_sync_runs_container"]

    def seed_source(self, **overrides):
        source = {
            "id": SOURCE_ID,
            "source_id": SOURCE_ID,
            "type": "file_sync_source",
            "scope_type": "group",
            "group_id": GROUP_ID,
            "name": "Contracts share",
            "source_type": "smb",
            "enabled": True,
            "recursive": True,
            "connection": {"unc_path": SHARE_ROOT, "selected_paths": []},
            "filters": {
                "include_patterns": [],
                "exclude_patterns": [],
                "allowed_extensions": [],
                "fixed_tags": [],
                "folder_tag_mode": "parent",
            },
            "schedule": {"enabled": True, "interval_minutes": 60, "next_run_at": PAST_NEXT_RUN},
            "remote_delete_policy": "ignore",
            "identity_id": "",
            "auth": {
                "auth_type": "username_password",
                "username": "svc-sync",
                "domain": "",
                "password_secret_name": "kv-file-sync-password",
            },
            "created_by": MANAGER_ID,
            "created_at": "2026-09-01T00:00:00+00:00",
            "updated_at": "2026-09-01T00:00:00+00:00",
            "last_run_status": None,
            "last_run_at": None,
        }
        source.update(overrides)
        return self.sources.seed(source)

    def stored_source(self):
        return self.sources.get(SOURCE_ID, GROUP_ID)

    def item_id(self, relative_path):
        return self.module._item_id_for_path(SOURCE_ID, remote_path_for(relative_path))

    def seed_item(self, relative_path, **fields):
        item = {
            "id": self.item_id(relative_path),
            "type": "file_sync_item",
            "source_id": SOURCE_ID,
            "scope_type": "group",
            "group_id": GROUP_ID,
            "remote_path": remote_path_for(relative_path),
            "relative_path": relative_path,
            "file_name": relative_path,
            "ignored": False,
        }
        item.update(fields)
        return self.items.seed(item)

    def stored_item(self, relative_path):
        return self.items.get(self.item_id(relative_path), SOURCE_ID)

    def edit(self, payload):
        return self.module.update_file_sync_source("group", GROUP_ID, SOURCE_ID, payload, MANAGER_ID)

    def ignore(self, relative_path):
        return self.module.set_file_sync_path_ignored(self.stored_source(), remote_path_for(relative_path), True, MANAGER_ID)

    def delete_source(self):
        return self.module.delete_file_sync_source("group", GROUP_ID, SOURCE_ID, MANAGER_ID)

    def keep_conflicting(self, container, times):
        """Make the next ``times`` writes to ``container`` lose to another writer."""

        def concurrent_write():
            record = container.records[next(iter(container.records))]
            container.seed(record)

        container.before_replace.extend([concurrent_write] * times)

    def run_sync(self, remote_files=(), staged_hashes=None, during_run=None):
        """Run a sync through the production entry point.

        ``during_run`` acts as the manager after the run has loaded the source and
        its items and before it writes anything, which is when a real run spends
        its time listing and ingesting remote files.
        """
        module = self.module
        staged_hashes = staged_hashes or {}

        def list_remote_files(source, config):
            if during_run:
                during_run()
            return [copy.deepcopy(entry) for entry in remote_files]

        module._list_remote_files = list_remote_files
        module._stage_remote_file = lambda source, entry: ("not-a-real-temp-file", staged_hashes[entry["file_name"]])
        module._create_document_from_remote_file = lambda source, entry, temp_file_path: f"doc-{entry['file_name']}"
        module._apply_sync_tags_to_existing_document = lambda source, existing_item, entry: None
        run = module._create_run(self.stored_source(), MANAGER_ID, "manual")
        return module.process_file_sync_run_by_id("group", GROUP_ID, SOURCE_ID, run["id"], MANAGER_ID, "manual")


@contextmanager
def file_sync_harness():
    recorder = Recorder()
    containers = {}
    behaviour = {
        "functions_appinsights": {"log_event": recorder.log_event},
        "functions_debug": {"debug_print": lambda *args, **kwargs: None},
        "functions_settings": {
            "get_settings": lambda: dict(SETTINGS),
            "normalize_file_sync_allowed_group_ids": lambda value: [str(entry) for entry in (value or [])],
            "normalize_file_sync_allowed_public_workspace_ids": lambda value: [str(entry) for entry in (value or [])],
        },
        "functions_group": {"assert_group_role": lambda user_id, group_id, allowed_roles=None: "Owner"},
        "functions_documents": {
            "allowed_file": lambda file_name: True,
            # Same (is_valid, error_message, normalized_tags) shape as the real validator;
            # these sources carry no fixed tags, so nothing needs normalizing.
            "validate_tags": lambda tags: (True, None, list(tags)),
        },
        "utils_cache": {
            "invalidate_group_search_cache": lambda *args, **kwargs: None,
            "invalidate_personal_search_cache": lambda *args, **kwargs: None,
            "invalidate_public_workspace_search_cache": lambda *args, **kwargs: None,
        },
    }
    modules = _stub_modules(FILE_SYNC_PATH, behaviour, containers)
    activity_logging = types.ModuleType("functions_activity_logging")
    activity_logging.log_file_sync_activity = lambda **payload: recorder.activity.append(payload)
    modules["functions_activity_logging"] = activity_logging

    module_name = "functions_file_sync_under_test"
    with _installed_modules({**modules, module_name: None}), _network_blocked():
        module = _load(FILE_SYNC_PATH, module_name)
        yield Harness(module, containers, recorder)


@contextmanager
def file_sync_client(harness):
    """A Flask client for the real File Sync routes, backed by the harness module."""
    behaviour = {
        "functions_file_sync": harness.module,
        "functions_appinsights": {"log_event": harness.recorder.log_event},
        "functions_authentication": {
            "admin_required": _passthrough_decorator,
            "login_required": _passthrough_decorator,
            "user_required": _passthrough_decorator,
            "enabled_required": lambda setting_name: _passthrough_decorator,
            "get_current_user_id": lambda: MANAGER_ID,
            "get_current_user_info": lambda: {"userId": MANAGER_ID},
        },
        "functions_group": {"require_active_group": lambda user_id, allowed_roles=None: GROUP_ID},
        "functions_settings": {"get_settings": lambda: dict(SETTINGS)},
        "swagger_wrapper": {
            "get_auth_security": lambda: [],
            "swagger_route": lambda **kwargs: _passthrough_decorator,
        },
    }
    modules = _stub_modules(FILE_SYNC_ROUTES_PATH, behaviour, {})
    module_name = "route_backend_file_sync_under_test"
    with _installed_modules({**modules, module_name: None}):
        routes = _load(FILE_SYNC_ROUTES_PATH, module_name)
    app = Flask(__name__)
    blueprint = Blueprint("file_sync_under_test", __name__)
    routes.register_route_backend_file_sync(blueprint)
    app.register_blueprint(blueprint)
    yield app.test_client()


def _parse_time(value):
    return datetime.fromisoformat(value)


def test_version_includes_the_fix():
    """The fix ships in 0.261.138."""
    assert_app_version_at_least("0.261.138")


def test_run_records_its_status_without_rewriting_the_source():
    """A run writes its own fields onto the stored source and schedules the next run."""
    with file_sync_harness() as harness:
        harness.seed_source()
        started = datetime.now(timezone.utc)
        run = harness.run_sync()
        stored = harness.stored_source()

        assert run["status"] == "completed"
        assert stored["last_run_id"] == run["id"]
        assert stored["last_run_status"] == "completed"
        next_run = _parse_time(stored["schedule"]["next_run_at"])
        assert started + timedelta(minutes=59) <= next_run <= datetime.now(timezone.utc) + timedelta(minutes=61)
        assert stored["name"] == "Contracts share"
        assert stored["auth"]["password_secret_name"] == "kv-file-sync-password"
        assert not harness.sources.writes("upsert_item")
        assert not harness.sources.writes("create_item")


def test_run_keeps_an_edit_made_while_it_was_running():
    """A rename, new path and new interval saved mid-run survive the run finishing."""
    with file_sync_harness() as harness:
        harness.seed_source()
        started = datetime.now(timezone.utc)

        def manager_edits():
            harness.edit({
                "name": "Contracts (2026)",
                "connection": {"unc_path": "\\\\files\\contracts-2026"},
                "schedule": {"enabled": True, "interval_minutes": 120},
            })

        run = harness.run_sync(
            remote_files=[remote_file("new.txt", "2026-09-20T00:00:00+00:00", 5)],
            staged_hashes={"new.txt": "hash-new"},
            during_run=manager_edits,
        )
        stored = harness.stored_source()

        assert run["status"] == "completed"
        assert stored["name"] == "Contracts (2026)"
        assert stored["connection"]["unc_path"] == "\\\\files\\contracts-2026"
        assert stored["schedule"]["interval_minutes"] == 120
        assert stored["auth"]["password_secret_name"] == "kv-file-sync-password"
        assert stored["last_run_id"] == run["id"]
        assert stored["last_run_status"] == "completed"
        # The next run is scheduled from the interval the manager just saved.
        next_run = _parse_time(stored["schedule"]["next_run_at"])
        assert started + timedelta(minutes=119) <= next_run <= datetime.now(timezone.utc) + timedelta(minutes=121)

        created_item = harness.stored_item("new.txt")
        assert created_item["document_id"] == "doc-new.txt"
        assert created_item["status"] == "synced"
        assert created_item["ignored"] is False


def test_run_does_not_re_enable_a_source_disabled_while_it_was_running():
    """Turning a source and its schedule off mid-run stays off."""
    with file_sync_harness() as harness:
        harness.seed_source()

        run = harness.run_sync(during_run=lambda: harness.edit({"enabled": False, "schedule": {"enabled": False}}))
        stored = harness.stored_source()

        assert run["status"] == "completed"
        assert stored["enabled"] is False
        assert stored["schedule"]["enabled"] is False
        assert stored["schedule"]["next_run_at"] is None
        assert stored["last_run_status"] == "completed"


def test_run_does_not_recreate_a_source_deleted_while_it_was_running():
    """A source deleted mid-run stays deleted, and the run is not reported as failed."""
    with file_sync_harness() as harness:
        harness.seed_source()

        run = harness.run_sync(during_run=harness.delete_source)

        assert run["status"] == "completed"
        assert harness.stored_source() is None
        assert not harness.sources.writes("upsert_item")
        assert not harness.sources.writes("create_item")
        assert any("the source was not recreated" in message for message in harness.recorder.messages())


def test_run_keeps_paths_ignored_while_it_was_running():
    """Changed, unchanged and missing files all keep an ignore saved mid-run."""
    with file_sync_harness() as harness:
        harness.seed_source()
        harness.seed_item(
            "changed.txt",
            status="synced",
            document_id="doc-changed-v1",
            content_hash="hash-v1",
            remote_modified_at="2026-09-01T00:00:00+00:00",
            remote_size=10,
        )
        harness.seed_item(
            "unchanged.txt",
            status="synced",
            document_id="doc-unchanged",
            remote_modified_at="2026-09-01T00:00:00+00:00",
            remote_size=20,
        )
        harness.seed_item("missing.txt", status="synced", document_id="doc-missing")

        def manager_ignores():
            for relative_path in ("changed.txt", "unchanged.txt", "missing.txt"):
                harness.ignore(relative_path)

        run = harness.run_sync(
            remote_files=[
                remote_file("changed.txt", "2026-09-20T00:00:00+00:00", 12),
                remote_file("unchanged.txt", "2026-09-01T00:00:00+00:00", 20),
            ],
            staged_hashes={"changed.txt": "hash-v2"},
            during_run=manager_ignores,
        )

        assert run["status"] == "completed"
        changed = harness.stored_item("changed.txt")
        unchanged = harness.stored_item("unchanged.txt")
        missing = harness.stored_item("missing.txt")
        for item in (changed, unchanged, missing):
            assert item["ignored"] is True, item
            assert item["status"] == "ignored", item
        # The run's own results are still recorded on the ignored items.
        assert changed["document_id"] == "doc-changed.txt"
        assert changed["content_hash"] == "hash-v2"
        assert changed["last_sync_run_id"] == run["id"]
        assert unchanged["last_seen_at"]
        assert missing["last_missing_at"]
        assert not harness.items.writes("upsert_item")


def test_ignoring_a_path_keeps_a_result_the_run_recorded_meanwhile():
    """An ignore saved while a run records a new version keeps that version's document."""
    with file_sync_harness() as harness:
        harness.seed_source()
        harness.seed_item("a.txt", status="synced", document_id="doc-a-v1", content_hash="hash-v1")
        source = harness.stored_source()
        updated_file = remote_file("a.txt", "2026-09-20T00:00:00+00:00", 12)
        updated_file["content_hash"] = "hash-v2"

        def run_records_a_new_version():
            harness.module._upsert_synced_item(
                source,
                harness.stored_item("a.txt"),
                updated_file,
                "doc-a-v2",
                status="synced",
                run_id="run-9",
                sync_action="updated",
            )

        harness.items.before_replace.append(run_records_a_new_version)
        returned = harness.ignore("a.txt")
        stored = harness.stored_item("a.txt")

        assert stored["ignored"] is True
        assert stored["status"] == "ignored"
        assert stored["document_id"] == "doc-a-v2"
        assert stored["last_sync_run_id"] == "run-9"
        assert returned["document_id"] == "doc-a-v2"


def test_saving_a_source_keeps_a_run_result_recorded_while_the_save_was_prepared():
    """A run finishing between the editor's read and its write keeps its status and next run."""
    with file_sync_harness() as harness:
        harness.seed_source()
        run_start_copy = harness.stored_source()
        real_normalize = harness.module._normalize_source_payload
        recorded = {}

        def normalize_while_a_run_finishes(*args, **kwargs):
            normalized = real_normalize(*args, **kwargs)
            harness.module._update_source_after_run(run_start_copy, finished_run("run-7", {"scanned": 3}))
            recorded["next_run_at"] = harness.stored_source()["schedule"]["next_run_at"]
            return normalized

        harness.module._normalize_source_payload = normalize_while_a_run_finishes
        saved = harness.edit({"name": "Contracts (renamed)", "schedule": {"enabled": True, "interval_minutes": 90}})
        stored = harness.stored_source()

        assert stored["name"] == "Contracts (renamed)"
        assert stored["schedule"]["interval_minutes"] == 90
        assert stored["last_run_id"] == "run-7"
        assert stored["last_run_status"] == "completed"
        assert stored["last_run_counts"] == {"scanned": 3}
        assert recorded["next_run_at"] != PAST_NEXT_RUN
        assert stored["schedule"]["next_run_at"] == recorded["next_run_at"]
        assert saved["name"] == "Contracts (renamed)"
        assert not harness.sources.writes("upsert_item")


def test_run_status_write_retries_when_an_edit_lands_between_its_read_and_write():
    """The engine's refused write is re-applied to the edited copy, not dropped."""
    with file_sync_harness() as harness:
        harness.seed_source()
        run_start_copy = harness.stored_source()
        harness.sources.before_replace.append(lambda: harness.edit({"name": "Renamed mid-write"}))

        harness.module._update_source_after_run(run_start_copy, finished_run("run-8"))
        stored = harness.stored_source()

        assert stored["name"] == "Renamed mid-write"
        assert stored["last_run_id"] == "run-8"
        # The engine's first write was refused, the edit landed, then the engine retried.
        assert len(harness.sources.writes("replace_item")) == 3


def test_run_is_not_marked_failed_when_its_status_cannot_be_recorded():
    """Losing every write attempt logs a warning and leaves the run completed."""
    with file_sync_harness() as harness:
        harness.seed_source()
        harness.keep_conflicting(harness.sources, harness.module.FILE_SYNC_WRITE_ATTEMPTS)

        run = harness.run_sync()

        assert run["status"] == "completed"
        assert harness.stored_source()["last_run_status"] is None
        assert any("Run status was not recorded" in message for message in harness.recorder.messages())


def test_saving_a_source_deleted_while_the_save_was_prepared_is_refused():
    """An edit racing a delete is refused with LookupError and never recreates the source."""
    with file_sync_harness() as harness:
        harness.seed_source()
        real_normalize = harness.module._normalize_source_payload

        def normalize_while_deleted(*args, **kwargs):
            normalized = real_normalize(*args, **kwargs)
            harness.delete_source()
            return normalized

        harness.module._normalize_source_payload = normalize_while_deleted
        try:
            harness.edit({"name": "Too late"})
            refused = False
        except LookupError:
            refused = True

        assert refused
        assert harness.stored_source() is None
        assert not harness.sources.writes("upsert_item")
        assert not harness.sources.writes("create_item")


def test_group_source_route_reports_save_outcomes():
    """The group PATCH route returns 200, 409 on a lasting conflict, and 404 on a raced delete."""
    with file_sync_harness() as harness:
        harness.seed_source()
        with file_sync_client(harness) as client:
            saved = client.patch(f"/api/file-sync/group/sources/{SOURCE_ID}", json={"name": "Saved"})
            saved_body = saved.get_json()

            harness.keep_conflicting(harness.sources, harness.module.FILE_SYNC_WRITE_ATTEMPTS)
            conflicted = client.patch(f"/api/file-sync/group/sources/{SOURCE_ID}", json={"name": "Conflicted"})
            conflicted_body = conflicted.get_json()

            real_normalize = harness.module._normalize_source_payload

            def normalize_while_deleted(*args, **kwargs):
                normalized = real_normalize(*args, **kwargs)
                harness.delete_source()
                return normalized

            harness.module._normalize_source_payload = normalize_while_deleted
            raced = client.patch(f"/api/file-sync/group/sources/{SOURCE_ID}", json={"name": "Raced"})

        assert saved.status_code == 200, saved_body
        assert saved_body["source"]["name"] == "Saved"
        assert "auth" not in saved_body["source"]
        assert conflicted.status_code == 409, conflicted_body
        assert "changed while it was being saved" in conflicted_body["error"]
        assert raced.status_code == 404
        assert harness.stored_source() is None


if __name__ == "__main__":
    tests = [
        test_version_includes_the_fix,
        test_run_records_its_status_without_rewriting_the_source,
        test_run_keeps_an_edit_made_while_it_was_running,
        test_run_does_not_re_enable_a_source_disabled_while_it_was_running,
        test_run_does_not_recreate_a_source_deleted_while_it_was_running,
        test_run_keeps_paths_ignored_while_it_was_running,
        test_ignoring_a_path_keeps_a_result_the_run_recorded_meanwhile,
        test_saving_a_source_keeps_a_run_result_recorded_while_the_save_was_prepared,
        test_run_status_write_retries_when_an_edit_lands_between_its_read_and_write,
        test_run_is_not_marked_failed_when_its_status_cannot_be_recorded,
        test_saving_a_source_deleted_while_the_save_was_prepared_is_refused,
        test_group_source_route_reports_save_outcomes,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print(f"Passed {test.__name__}")
            results.append(True)
        except Exception as error:
            import traceback

            print(f"Failed {test.__name__}: {error}")
            traceback.print_exc()
            results.append(False)
    print(f"Results: {sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
