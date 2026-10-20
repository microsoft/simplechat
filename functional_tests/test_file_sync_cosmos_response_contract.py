# test_file_sync_cosmos_response_contract.py
"""
Runtime evidence for the shared File Sync owners' Cosmos response contracts.
Version: 0.261.359
Implemented in: 0.261.359

Execute production storage owners with real SDK CosmosDict point responses and
plain query rows across every workspace scope. Reuse conditional-write and fault
injection seams; block network access and isolate configuration and cloud I/O.
"""

import ast
from copy import deepcopy
import hashlib
import json
import logging
import re
import socket
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional
from unittest.mock import Mock
import uuid

from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos import exceptions
from azure.cosmos._cosmos_responses import CosmosDict
import pytest

from test_support.agent_delegation import APP_ROOT
from test_support.orchestration_revisions import AtomicMemoryContainer


class FileSyncContainer(AtomicMemoryContainer):
    """SDK-shaped conditional storage with the File Sync query subset."""

    before_delete = None

    def delete_item(self, item, partition_key, **kwargs):
        self._hook("before_delete")
        return super().delete_item(item, partition_key, **kwargs)

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        top = re.search(r"SELECT TOP (\d+)", query)
        rows = super().query_items(
            re.sub(r"SELECT TOP \d+", "SELECT", query),
            parameters=parameters, partition_key=partition_key, **kwargs,
        )
        if "c.status IN ('queued', 'running')" in query:
            return [sum(row.get("status") in {"queued", "running"} for row in rows)]
        if "c.schedule.enabled = true" in query:
            now = next(item["value"] for item in parameters if item["name"] == "@now")
            rows = [
                row for row in rows
                if row.get("enabled") is True
                and (row.get("schedule") or {}).get("enabled") is True
                and (row.get("schedule") or {}).get("next_run_at") is not None
                and row["schedule"]["next_run_at"] <= now
            ]
        if "ORDER BY c.started_at DESC" in query:
            rows.sort(key=lambda row: row["started_at"], reverse=True)
        return rows[:int(top.group(1))] if top else rows


@pytest.fixture(params=["personal", "group", "public"])
def storage(request, monkeypatch):
    network = Mock(side_effect=AssertionError("File Sync contracts cannot access the network."))
    monkeypatch.setattr(socket.socket, "connect", network)
    monkeypatch.setattr(socket, "getaddrinfo", network)
    fields = {"personal": "user_id", "group": "group_id", "public": "public_workspace_id"}
    containers = {
        scope: {
            "sources": FileSyncContainer(field),
            "items": FileSyncContainer("source_id"),
            "runs": FileSyncContainer("source_id"),
        }
        for scope, field in fields.items()
    }
    names = {
        "FILE_SYNC_SCOPE_PERSONAL", "FILE_SYNC_SCOPE_GROUP", "FILE_SYNC_SCOPE_PUBLIC",
        "FILE_SYNC_SCOPES", "FILE_SYNC_MANAGER_ROLES", "FILE_SYNC_WRITE_ATTEMPTS",
        "_FILE_SYNC_EDITABLE_AUTH_FIELDS", "FileSyncWriteConflict",
        "FileSyncConfigConflict", "FileSyncSourceBusy",
        "_validate_scope", "_scope_field", "_source_scope_id", "_keyvault_scope",
        "_get_sources_container", "_get_items_container", "_get_runs_container",
        "_safe_int", "_write_with_etag_guard", "get_authorized_sync_source",
        "list_file_sync_sources", "create_file_sync_source", "delete_file_sync_source",
        "_file_sync_editable_projection", "compute_file_sync_config_revision",
        "list_file_sync_runs", "_create_run", "_update_run", "process_file_sync_run_by_id",
        "_load_existing_items", "_count_active_runs", "_source_has_active_run",
        "_get_due_sources_for_scope", "_read_file_sync_source_for_document_action",
    }
    tree = ast.parse((APP_ROOT / "functions_file_sync.py").read_text(encoding="utf-8"))
    definitions = [
        node for node in tree.body
        if (
            isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names
        ) or (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in names for target in node.targets)
        )
    ]
    namespace = {
        "Any": Any, "Callable": Callable, "Dict": Dict, "Iterable": Iterable,
        "List": List, "Optional": Optional, "hashlib": hashlib, "json": json,
        "logging": logging, "uuid": uuid, "MatchConditions": MatchConditions,
        "CosmosResourceNotFoundError": exceptions.CosmosResourceNotFoundError,
        "CosmosResourceExistsError": exceptions.CosmosResourceExistsError,
        "CosmosAccessConditionFailedError": exceptions.CosmosAccessConditionFailedError,
        "_now_iso": lambda: "2026-10-20T12:00:00+00:00",
        "get_file_sync_config": lambda: {"file_sync_max_sources_per_scope": 10},
        "_normalize_source_payload": lambda scope, scope_id, payload, *args, **kwargs: deepcopy(payload),
        "_log_file_sync_activity": Mock(), "log_event": Mock(),
        "assert_group_role": Mock(), "assert_public_workspace_role": Mock(),
        "keyvault_file_sync_delete_helper": Mock(),
        "keyvault_file_sync_discard_staged_helper": Mock(),
    }
    for scope, by_kind in containers.items():
        for kind, container in by_kind.items():
            namespace[f"cosmos_{scope}_file_sync_{kind}_container"] = container
    exec(compile(ast.Module(body=definitions, type_ignores=[]), "functions_file_sync.py", "exec"), namespace)
    source = namespace["create_file_sync_source"](request.param, "workspace-a", {
        "name": "Contracts", "source_type": "azure_files", "enabled": True,
        "connection": {"share_name": "documents"}, "auth": {"auth_type": "managed_identity"},
        "schedule": {"enabled": True, "next_run_at": "2026-10-20T11:00:00+00:00"},
    }, "workspace-a")
    yield SimpleNamespace(
        functions=namespace, scope=request.param, scope_id="workspace-a", source=source,
        **containers[request.param],
    )
    network.assert_not_called()


def test_source_writes_and_authorized_reads_use_sdk_documents(storage):
    env, functions = storage, storage.functions
    saved = env.sources.read_item(env.source["id"], env.scope_id)
    assert isinstance(saved, CosmosDict)
    assert type(env.source) is dict
    assert type(saved["connection"]) is dict
    authorized = functions["get_authorized_sync_source"](
        env.scope, saved["id"], env.scope_id, scope_id=env.scope_id,
    )
    assert isinstance(authorized, CosmosDict)
    assert authorized["_etag"] == saved["_etag"]
    if env.scope != "personal":
        functions[f"assert_{'public_workspace' if env.scope == 'public' else 'group'}_role"].assert_called_once_with(
            env.scope_id, env.scope_id, allowed_roles=functions["FILE_SYNC_MANAGER_ROLES"],
        )
    with pytest.raises(LookupError):
        functions["get_authorized_sync_source"](
            env.scope, saved["id"], "different-workspace", scope_id="different-workspace",
        )
    malformed = {**saved, "scope_type": "invalid"}
    env.sources.upsert_item(malformed)
    with pytest.raises(PermissionError, match="does not belong"):
        functions["get_authorized_sync_source"](
            env.scope, saved["id"], env.scope_id, scope_id=env.scope_id,
        )


def test_guarded_writes_preserve_sdk_fields_and_retry_current_etags(storage):
    env, functions = storage, storage.functions
    original = env.sources.read_item(env.source["id"], env.scope_id)
    seen = []

    def edit(current):
        seen.append(current)
        return {**current, "name": "Edited"}

    env.sources.before_replace = lambda: env.sources.upsert_item({
        **original, "last_run_status": "completed",
    })
    saved = functions["_write_with_etag_guard"](
        env.sources, original["id"], env.scope_id, edit,
    )
    assert isinstance(saved, CosmosDict)
    assert saved["name"] == "Edited"
    assert saved["last_run_status"] == "completed"
    assert saved["_etag"] != original["_etag"]
    assert len(seen) == 2
    assert all(isinstance(current, CosmosDict) for current in seen)
    missing = functions["_write_with_etag_guard"](env.sources, "missing", env.scope_id, edit)
    assert missing is None
    created = functions["_write_with_etag_guard"](
        env.sources, "new", env.scope_id, edit,
        new_document=lambda: {**env.source, "id": "new"},
    )
    assert isinstance(created, CosmosDict)
    assert created["id"] == "new"


def test_source_item_and_run_queries_keep_plain_rows(storage):
    env, functions = storage, storage.functions
    future = {
        **env.source, "id": "future",
        "schedule": {"enabled": True, "next_run_at": "2099-01-01T00:00:00+00:00"},
    }
    env.sources.create_item(future)
    env.sources.create_item({
        **env.source, "id": "disabled", "enabled": False,
        functions["_scope_field"](env.scope): "other-workspace",
    })
    sources = functions["list_file_sync_sources"](env.scope, env.scope_id)
    due = functions["_get_due_sources_for_scope"](env.scope)
    assert {row["id"] for row in sources} == {env.source["id"], "future"}
    assert all(type(row) is dict for row in sources)
    assert [row["id"] for row in due] == [env.source["id"]]
    assert type(due[0]) is dict
    env.items.create_item({"id": "item", "source_id": env.source["id"], "document_id": "document"})
    env.items.create_item({"id": "other-item", "source_id": "other-source"})
    items = functions["_load_existing_items"](env.source)
    assert list(items) == ["item"]
    assert type(items["item"]) is dict
    run = functions["_create_run"](env.source, env.scope_id, "manual")
    sdk_run = env.runs.read_item(run["id"], env.source["id"])
    assert isinstance(sdk_run, CosmosDict)
    assert type(run) is dict
    assert type(sdk_run["counts"]) is dict
    active = functions["_count_active_runs"]()
    has_active = functions["_source_has_active_run"](env.source)
    assert active == 1
    assert has_active is True
    updated = functions["_update_run"](sdk_run, {"status": "completed"})
    stored = env.runs.read_item(run["id"], env.source["id"])
    assert updated is sdk_run
    assert isinstance(stored, CosmosDict)
    assert stored["status"] == "completed"
    assert stored["_etag"] != sdk_run["_etag"]
    active = functions["_count_active_runs"]()
    has_active = functions["_source_has_active_run"](env.source)
    newer = functions["_create_run"](env.source, env.scope_id, "manual")
    functions["_update_run"](newer, {
        "status": "completed", "started_at": "2026-10-20T13:00:00+00:00",
    })
    runs = functions["list_file_sync_runs"](env.scope, env.source["id"], limit=1)
    assert active == 0
    assert has_active is False
    assert len(runs) == 1
    assert type(runs[0]) is dict
    assert runs[0]["id"] == newer["id"]
    assert env.runs.queries[-1][2] == env.source["id"]


def test_process_by_id_preserves_sdk_documents_at_engine_boundary(storage):
    env, functions = storage, storage.functions
    run = functions["_create_run"](env.source, env.scope_id, "manual")
    processor = Mock(return_value={"status": "completed"})
    functions["_process_file_sync_source"] = processor
    result = functions["process_file_sync_run_by_id"](
        env.scope, env.scope_id, env.source["id"], run["id"], env.scope_id, "scheduled",
    )
    assert result == {"status": "completed"}
    saved_source, saved_run = processor.call_args.args
    assert isinstance(saved_source, CosmosDict)
    assert isinstance(saved_run, CosmosDict)
    assert saved_source["_etag"]
    assert saved_run["_etag"]
    assert type(saved_run["counts"]) is dict
    assert processor.call_args.kwargs == {"triggered_by": env.scope_id, "trigger": "scheduled"}
    processor.reset_mock()
    with pytest.raises(exceptions.CosmosResourceNotFoundError):
        functions["process_file_sync_run_by_id"](
            env.scope, "different-workspace", env.source["id"], run["id"],
        )
    processor.assert_not_called()


def test_conditional_delete_retries_sdk_point_read_after_etag_change(storage):
    env, functions = storage, storage.functions
    saved = env.sources.read_item(env.source["id"], env.scope_id)
    revision = functions["compute_file_sync_config_revision"](saved)
    env.sources.before_delete = lambda: env.sources.upsert_item({
        **saved, "last_run_status": "completed",
    })
    result = functions["delete_file_sync_source"](
        env.scope, env.scope_id, saved["id"], env.scope_id,
        expected_config_revision=revision, refuse_active_run=True,
    )
    assert result["documents_deleted"] == 0
    with pytest.raises(exceptions.CosmosResourceNotFoundError):
        env.sources.read_item(saved["id"], env.scope_id)
    functions["keyvault_file_sync_delete_helper"].assert_called_once()


def test_document_action_reads_keep_sdk_shape_and_missing_semantics(storage):
    env, functions = storage, storage.functions
    source = functions["_read_file_sync_source_for_document_action"](
        env.scope, env.source["id"], env.scope_id,
    )
    assert isinstance(source, CosmosDict)
    assert source["id"] == env.source["id"]
    assert source["_etag"]
    for source_id, partition in [("missing", env.scope_id), (env.source["id"], "other"), (None, env.scope_id)]:
        missing = functions["_read_file_sync_source_for_document_action"](env.scope, source_id, partition)
        assert missing is None
    env.sources.fail_reads = True
    with pytest.raises(AzureError):
        functions["_read_file_sync_source_for_document_action"](env.scope, env.source["id"], env.scope_id)


def test_storage_write_failures_are_not_successful_results(storage):
    env, functions = storage, storage.functions
    env.sources.fail_writes = True
    with pytest.raises(AzureError):
        functions["create_file_sync_source"](env.scope, env.scope_id, {"name": "Another"}, env.scope_id)
    with pytest.raises(AzureError):
        functions["_write_with_etag_guard"](
            env.sources, env.source["id"], env.scope_id, lambda current: current,
        )
    env.runs.fail_writes = True
    with pytest.raises(AzureError):
        functions["_create_run"](env.source, env.scope_id, "manual")
    with pytest.raises(AzureError):
        functions["_update_run"]({"id": "run", "scope_type": env.scope, "source_id": env.source["id"]}, {})
