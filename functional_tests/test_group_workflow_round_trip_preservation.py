# test_group_workflow_round_trip_preservation.py
#!/usr/bin/env python3
"""
Functional test for group workflow save round-trip preservation.
Version: 0.261.174
Implemented in: 0.261.141

This test ensures that existing group workflow definitions survive load, edit and save. A group
workflow carrying alert rules, URL access, a Monitor File Sync trigger and a document action is
saved through the real ``save_group_workflow``. The loaded record is then sent back unchanged,
as the V2 editor does. Every server-modelled field must survive, except ``modified_at``,
``updated_at`` and ``modified_by``.

The real ``functions_group_workflows`` and ``functions_personal_workflows`` modules are loaded
from their files. They run with the real alert, document action, definition, definition store
and Microsoft 365 binding modules. Only I/O is doubled: the Cosmos workflow container, the group
role check, the File Sync source store and application settings. Every other application
dependency refuses to be called, so an unmodelled path fails loudly instead of passing vacuously.
Unlike the older store integration suite, the File Sync, document action and alert normalizers
are not stubbed, and ``test_the_real_server_rules_run_in_this_harness`` proves it.
"""

import ast
import copy
import importlib.util
import itertools
import json
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest
from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"

GROUP_ID = "group-alpha"
OTHER_GROUP_ID = "group-beta"
OWNER_ID = "owner-1"
EDITOR_ID = "admin-2"
MEMBER_ID = "member-3"
SOURCE_ID = "finance-share"
TIMESTAMP_FIELDS = {"modified_at", "updated_at", "modified_by"}
SETTINGS = {
    "workflow_max_tasks": 50,
    "enable_semantic_kernel": False,
    "allow_group_agents": False,
    "allow_group_custom_endpoints": False,
    "model_endpoints": [],
    "azure_openai_gpt_deployment": "gpt-4o",
    "gpt_model": {"selected": [{"deploymentName": "gpt-4o", "modelName": "gpt-4o"}]},
}
_MISSING = object()


class WorkflowContainer:
    """A JSON-serializing Cosmos container double with etag preconditions."""

    def __init__(self, partition_field):
        self.partition_field = partition_field
        self.items = {}
        self.writes = []
        self._etags = itertools.count(1)

    def _stored(self, body):
        stored = json.loads(json.dumps(body))
        stored["_etag"] = f'"etag-{next(self._etags)}"'
        stored["_ts"] = 1790000000
        self.items[(stored[self.partition_field], stored["id"])] = stored
        return copy.deepcopy(stored)

    def create_item(self, body, **kwargs):
        if (body[self.partition_field], body["id"]) in self.items:
            raise CosmosResourceExistsError(status_code=409, message="Entity already exists")
        self.writes.append(("create_item", body["id"]))
        return self._stored(body)

    def read_item(self, item, partition_key, **kwargs):
        record = self.items.get((partition_key, item))
        if record is None:
            raise CosmosResourceNotFoundError(status_code=404, message="Entity does not exist")
        return copy.deepcopy(record)

    def replace_item(self, item, body, etag=None, match_condition=None, **kwargs):
        record = self.items.get((body[self.partition_field], item))
        if record is None:
            raise CosmosResourceNotFoundError(status_code=404, message="Entity does not exist")
        if match_condition == MatchConditions.IfNotModified and etag != record["_etag"]:
            raise CosmosAccessConditionFailedError(status_code=412, message="Precondition failed")
        self.writes.append(("replace_item", item))
        return self._stored(body)

    def query_items(self, query=None, parameters=None, partition_key=None, **kwargs):
        return iter([
            copy.deepcopy(record) for (partition, _), record in self.items.items()
            if partition_key is None or partition == partition_key
        ])


def _refusal(module_name, attribute):
    def refused(*args, **kwargs):
        raise AssertionError(f"The code under test called {module_name}.{attribute}, which this test does not model.")

    refused.__name__ = attribute
    return refused


def _module(name, **attributes):
    """A stand-in module whose unmodelled names import as functions that refuse to be called."""
    module = types.ModuleType(name)
    module.__dict__.update(attributes)

    def missing(attribute):
        if attribute.startswith("__"):
            raise AttributeError(attribute)
        return _refusal(name, attribute)

    module.__getattr__ = missing
    return module


def _load(name, source_file):
    spec = importlib.util.spec_from_file_location(name, source_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _compiled(source_file, names, namespace):
    """Compile named top-level definitions and literal constants from a heavy module's source."""
    tree = ast.parse(Path(source_file).read_text(encoding="utf-8"), filename=str(source_file))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in names for target in node.targets
        ):
            nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source_file), "exec"), namespace)
    missing = set(names) - set(namespace)
    assert not missing, f"Missing definitions in {Path(source_file).name}: {sorted(missing)}"
    return namespace


@contextmanager
def _installed(names):
    """Restore every module name this harness touches once loading is complete."""
    originals = {name: sys.modules.get(name, _MISSING) for name in names}
    try:
        yield
    finally:
        for name, original in originals.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def _document_analysis_seams():
    """The real document target and id normalizers, compiled away from their Azure-bound modules."""
    search = _compiled(
        APP_ROOT / "functions_search.py",
        ("VALID_SEARCH_SCOPES", "normalize_search_scope", "normalize_search_id_list"),
        {},
    )
    analysis = _compiled(
        APP_ROOT / "functions_document_analysis.py",
        (
            "DEFAULT_WINDOW_UNIT", "DEFAULT_MAX_RETRIES_PER_WINDOW", "CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS",
            "WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS", "_coerce_int", "normalize_document_analysis_targets",
        ),
        {
            "normalize_search_scope": search["normalize_search_scope"],
            "normalize_search_id_list": search["normalize_search_id_list"],
        },
    )
    return {
        "functions_search": _module(
            "functions_search", normalize_search_id_list=search["normalize_search_id_list"],
        ),
        "functions_document_analysis": _module(
            "functions_document_analysis",
            CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS=analysis["CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS"],
            WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS=analysis["WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS"],
            normalize_document_analysis_targets=analysis["normalize_document_analysis_targets"],
        ),
        "functions_document_analysis_results": _module("functions_document_analysis_results"),
    }


def _file_sync_constant(name):
    tree = ast.parse((APP_ROOT / "functions_file_sync.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not a literal constant in functions_file_sync.py")


class GroupWorkflowStore:
    """The real group workflow store over doubled I/O."""

    def __init__(self):
        self.settings = copy.deepcopy(SETTINGS)
        self.container = WorkflowContainer("group_id")
        self.roles = {
            (GROUP_ID, OWNER_ID): "Owner",
            (GROUP_ID, EDITOR_ID): "Admin",
            (GROUP_ID, MEMBER_ID): "User",
            (OTHER_GROUP_ID, OWNER_ID): "Owner",
        }
        self.file_sync_groups = {GROUP_ID, OTHER_GROUP_ID}
        self.sources = {
            (GROUP_ID, SOURCE_ID): {
                "id": SOURCE_ID, "scope_type": "group", "group_id": GROUP_ID,
                "name": "Finance share", "source_type": "smb", "auth": {"password": "never-store"},
            },
            (OTHER_GROUP_ID, "other-share"): {
                "id": "other-share", "scope_type": "group", "group_id": OTHER_GROUP_ID,
                "name": "Other share", "source_type": "smb",
            },
        }
        self.source_reads = []
        self.clock = (f"2026-09-2{day}T12:00:00+00:00" for day in range(1, 10))

        def assert_group_role(user_id, group_id, allowed_roles=("Owner", "Admin")):
            role = self.roles.get((group_id, user_id))
            if not role:
                raise PermissionError("User is not a member of this group")
            if role.lower() not in {allowed.lower() for allowed in allowed_roles}:
                raise PermissionError("Insufficient permissions for this group")
            return role

        manager_roles = _file_sync_constant("FILE_SYNC_MANAGER_ROLES")

        def get_authorized_sync_source(scope_type, source_id, user_id, scope_id=None, allowed_roles=manager_roles):
            self.source_reads.append((scope_type, scope_id, source_id, user_id))
            assert_group_role(user_id, scope_id, allowed_roles=allowed_roles)
            source = self.sources.get((scope_id, source_id))
            if source is None:
                raise LookupError("File sync source not found")
            return copy.deepcopy(source)

        def sanitize_file_sync_source(source):
            sanitized = dict(source or {})
            sanitized.pop("auth", None)
            return sanitized

        settings_module = _module(
            "functions_settings",
            get_settings=lambda: copy.deepcopy(self.settings),
            normalize_model_endpoints=lambda endpoints: (copy.deepcopy(list(endpoints or [])), False),
        )
        file_sync_module = _module(
            "functions_file_sync",
            FILE_SYNC_SCOPE_GROUP=_file_sync_constant("FILE_SYNC_SCOPE_GROUP"),
            FILE_SYNC_SCOPE_PERSONAL=_file_sync_constant("FILE_SYNC_SCOPE_PERSONAL"),
            FILE_SYNC_SCOPE_PUBLIC=_file_sync_constant("FILE_SYNC_SCOPE_PUBLIC"),
            get_authorized_sync_source=get_authorized_sync_source,
            sanitize_file_sync_source=sanitize_file_sync_source,
            is_file_sync_enabled_for_group=lambda settings, group_id, user_info=None: group_id in self.file_sync_groups,
        )
        config_module = _module(
            "config",
            cosmos_group_workflows_container=self.container,
            cosmos_group_workflow_runs_container=WorkflowContainer("group_id"),
            cosmos_group_workflow_run_items_container=WorkflowContainer("run_id"),
            cosmos_personal_workflows_container=WorkflowContainer("user_id"),
            cosmos_personal_workflow_runs_container=WorkflowContainer("user_id"),
            cosmos_personal_workflow_run_items_container=WorkflowContainer("run_id"),
            cosmos_conversations_container=WorkflowContainer("id"),
        )
        stubs = {
            "config": config_module,
            "functions_appinsights": _module(
                "functions_appinsights", log_event=lambda *args, **kwargs: None,
                debug_print=lambda *args, **kwargs: None, is_debug_enabled=lambda *args, **kwargs: False,
            ),
            "functions_debug": _module("functions_debug", debug_print=lambda *args, **kwargs: None),
            "functions_settings": settings_module,
            "functions_file_sync": file_sync_module,
            "functions_group": _module("functions_group", assert_group_role=assert_group_role),
            "functions_ai_connections": _module("functions_ai_connections"),
            "functions_global_agents": _module("functions_global_agents"),
            "functions_personal_agents": _module("functions_personal_agents"),
            "functions_group_agents": _module("functions_group_agents"),
            "functions_workflow_result_store": _module("functions_workflow_result_store"),
            "functions_workflow_bindings": _module("functions_workflow_bindings"),
            "functions_workflow_runtime_store": _module("functions_workflow_runtime_store"),
            **_document_analysis_seams(),
        }
        # Load order follows the import graph: the alert normalizer imports the definitions module, and
        # the group store takes its member roles from the pure workflow policy module.
        real = (
            "functions_workflow_alert_safety", "functions_workflow_definitions", "functions_workflow_alerts",
            "functions_m365_workflow_binding", "functions_workflow_definition_store", "functions_document_actions",
            "functions_personal_workflows", "functions_group_workflow_policy", "functions_group_workflows",
        )
        with _installed((*stubs, *real)):
            sys.modules.update(stubs)
            loaded = {name: _load(name, APP_ROOT / f"{name}.py") for name in real}
        self.modules = loaded
        self.module = loaded["functions_group_workflows"]
        self.module._utc_now_iso = lambda: next(self.clock)

    def save(self, payload, actor=OWNER_ID):
        return self.module.save_group_workflow(
            GROUP_ID, copy.deepcopy(payload), actor_user_id=actor, user_info={"roles": ["User"]},
        )

    def load(self, workflow_id):
        return self.module.get_group_workflow(GROUP_ID, workflow_id)


def monitored_workflow(**overrides):
    """A V2-shaped group definition that uses every family the round trip must keep."""
    record = {
        "name": "Monitor finance drops",
        "description": "Summarize every changed finance file.",
        "definition_version": 2,
        "durable_execution": True,
        "runner_type": "model",
        "model_endpoint_id": "",
        "model_id": "",
        "m365_run_as_user_id": EDITOR_ID,
        "chat_capabilities_enabled": False,
        "trigger_type": "file_sync",
        "schedule": {"unit": "minutes", "value": 30},
        "is_enabled": True,
        "error_handling": {"strategy": "continue", "retry_count": 2},
        "url_access_enabled": True,
        "url_access_authorized": True,
        "url_access_authorized_by": OWNER_ID,
        "url_access_authorized_at": "2026-09-20T09:00:00+00:00",
        "alert_mode": "rules",
        "alert_priority": "high",
        "alert_evaluation": {"on_error": "alert"},
        "alert_rules": [
            {
                "id": "rule-changes", "name": "Files changed", "enabled": True, "severity": "high",
                "delivery": "popup", "scope": {"type": "final"},
                "condition": {"type": "file_sync", "outcome": "changes_found"},
            },
            {
                "id": "rule-risk", "name": "Risk mentioned", "enabled": False, "severity": "critical",
                "delivery": "notify_only", "scope": {"type": "task", "task_id": "summarize"},
                "condition": {"type": "text_match", "mode": "contains_any", "values": ["penalty", "breach"]},
            },
            {
                "id": "rule-failed", "name": "Run failed", "severity": "medium",
                "condition": {"type": "run_status", "statuses": ["failed", "completed_with_task_errors"]},
            },
        ],
        "file_sync": {
            "enabled": True,
            "wait_mode": "complete",
            "continue_mode": "changed",
            "use_changed_documents": True,
            "sources": [{"scope_type": "group", "scope_id": GROUP_ID, "source_id": SOURCE_ID}],
        },
        "tasks": [
            {
                "id": "summarize", "type": "instructions", "name": "Summarize changes",
                "instructions": "Summarize each changed finance file.", "order": 1,
                "runner": {"type": "inherit"},
                "document_action": {"type": "analyze", "document_ids": [], "analysis_mode": "per_document"},
            },
            {
                "id": "update", "type": "instructions", "name": "Draft the update",
                "instructions": "Draft the team update from the summaries.", "order": 2,
                "runner": {"type": "inherit"},
                "document_action": {"type": "none"},
                "inputs": [{"name": "summaries", "task_id": "summarize", "output": "text"}],
            },
        ],
        "reference_inputs": [],
        "group_id": GROUP_ID,
    }
    record.update(copy.deepcopy(overrides))
    return record


@pytest.fixture
def store():
    return GroupWorkflowStore()


def _changed_fields(before, after, ignored=TIMESTAMP_FIELDS):
    keys = (set(before) | set(after)) - set(ignored)
    return sorted(key for key in keys if before.get(key, _MISSING) != after.get(key, _MISSING))


def test_first_save_keeps_every_modelled_family(store):
    """The first save stores the File Sync trigger, alerts, URL access and document action as sent."""
    saved = store.save(monitored_workflow())
    stored = store.load(saved["id"])

    assert stored["trigger_type"] == "file_sync"
    assert stored["file_sync"] == {
        "enabled": True, "wait_mode": "complete", "continue_mode": "changed", "use_changed_documents": True,
        "sources": [{
            "scope_type": "group", "scope_id": GROUP_ID, "source_id": SOURCE_ID,
            "name": "Finance share", "source_type": "smb",
        }],
    }
    assert stored["schedule"] == {"unit": "minutes", "value": 30}
    assert stored["next_run_at"]
    assert stored["alert_mode"] == "rules"
    assert stored["alert_priority"] == "high"
    assert stored["alert_evaluation"] == {"on_error": "alert"}
    assert [rule["id"] for rule in stored["alert_rules"]] == ["rule-changes", "rule-risk", "rule-failed"]
    assert stored["alert_rules"][1]["scope"] == {"type": "task", "task_id": "summarize"}
    assert stored["alert_rules"][1]["enabled"] is False
    assert (stored["url_access_enabled"], stored["url_access_authorized"]) == (True, True)
    assert stored["url_access_authorized_by"] == OWNER_ID
    assert stored["url_access_authorized_at"] == "2026-09-20T09:00:00+00:00"
    summarize_action = stored["tasks"][0]["document_action"]
    assert summarize_action["type"] == "analyze"
    assert summarize_action["document_ids"] == []
    assert summarize_action["analysis_mode"] == "per_document"
    assert (summarize_action["doc_scope"], summarize_action["active_group_ids"]) == ("group", [GROUP_ID])
    assert stored["tasks"][1]["inputs"][0]["task_id"] == "summarize"
    assert stored["m365_run_as_user_id"] == EDITOR_ID
    assert "never-store" not in json.dumps(stored)
    assert len(stored["definition_revision"]) == 64


def test_sending_the_loaded_record_back_unchanged_keeps_every_server_field(store):
    """The V2 editor resends the whole loaded record; only the edit timestamps and editor may change."""
    first = store.save(monitored_workflow())
    loaded = store.load(first["id"])

    resaved = store.save(loaded, actor=EDITOR_ID)
    reloaded = store.load(first["id"])

    assert _changed_fields(loaded, resaved) == []
    assert _changed_fields(loaded, reloaded) == []
    assert reloaded["modified_by"] == EDITOR_ID
    assert reloaded["modified_at"] != loaded["modified_at"]
    assert reloaded["updated_at"] != loaded["updated_at"]
    assert reloaded["created_by"] == OWNER_ID
    assert reloaded["user_id"] == OWNER_ID
    assert reloaded["definition_revision"] == loaded["definition_revision"]
    assert [write[0] for write in store.container.writes] == ["create_item", "replace_item"]
    # The saved sources were re-authorized for the resaving editor, not trusted from the payload.
    assert store.source_reads[-1] == ("group", GROUP_ID, SOURCE_ID, EDITOR_ID)


def test_a_metadata_edit_changes_only_that_field(store):
    """An edit of one authored field leaves alerts, URL access, File Sync and document actions untouched."""
    first = store.save(monitored_workflow())
    loaded = store.load(first["id"])

    edited = store.save({**loaded, "description": "Summarize and flag risky changes."}, actor=EDITOR_ID)
    reloaded = store.load(first["id"])

    assert edited["description"] == "Summarize and flag risky changes."
    assert _changed_fields(loaded, reloaded) == ["definition_revision", "description"]
    for field in (
        "alert_mode", "alert_priority", "alert_rules", "alert_evaluation", "url_access_enabled",
        "url_access_authorized", "url_access_authorized_by", "url_access_authorized_at", "file_sync",
        "trigger_type", "schedule", "next_run_at", "document_action", "analyze", "tasks",
    ):
        assert reloaded[field] == loaded[field], field


def test_a_second_round_trip_is_stable(store):
    """Normalization is idempotent: resending a resent record still changes nothing."""
    first = store.save(monitored_workflow())
    loaded = store.load(first["id"])
    store.save(loaded, actor=EDITOR_ID)
    once = store.load(first["id"])
    store.save(once, actor=OWNER_ID)
    twice = store.load(first["id"])

    assert _changed_fields(once, twice) == []
    assert _changed_fields(loaded, twice) == []


def test_the_real_server_rules_run_in_this_harness(store):
    """Anti-vacuity: the File Sync and alert normalizers here are the real ones, so they refuse bad input."""
    base = monitored_workflow()
    with pytest.raises(ValueError, match="continue only when changes are found"):
        store.save({**base, "file_sync": {**base["file_sync"], "continue_mode": "always"}})
    with pytest.raises(ValueError, match="must wait for the sync to complete"):
        store.save({**base, "file_sync": {**base["file_sync"], "wait_mode": "queued"}})
    with pytest.raises(ValueError, match="only use File Sync sources from this group"):
        store.save({**base, "file_sync": {**base["file_sync"], "sources": [
            {"scope_type": "group", "scope_id": OTHER_GROUP_ID, "source_id": "other-share"},
        ]}})
    with pytest.raises(ValueError, match="at least one group File Sync source"):
        store.save({**base, "file_sync": {**base["file_sync"], "sources": []}})
    # A deleted source is a reviewed 400 since 0.261.149, not the LookupError the route mapped to 404.
    with pytest.raises(store.modules["functions_workflow_definitions"].WorkflowSourceUnavailableError):
        store.save({**base, "file_sync": {**base["file_sync"], "sources": [
            {"scope_type": "group", "scope_id": GROUP_ID, "source_id": "deleted-share"},
        ]}})
    with pytest.raises(PermissionError):
        store.save(base, actor=MEMBER_ID)
    with pytest.raises(ValueError, match="between 1 and 59"):
        store.save({**base, "schedule": {"unit": "minutes", "value": 90}})
    orphaned_rule = {**base["alert_rules"][1], "scope": {"type": "task", "task_id": "removed-task"}}
    with pytest.raises(ValueError, match="watches a task that is no longer in this workflow"):
        store.save({**base, "alert_rules": [base["alert_rules"][0], orphaned_rule]})
    store.file_sync_groups.discard(GROUP_ID)
    with pytest.raises(ValueError, match="Group File Sync must be enabled"):
        store.save(base)
    assert store.container.writes == []
