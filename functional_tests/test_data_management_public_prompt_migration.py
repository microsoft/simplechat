# test_data_management_public_prompt_migration.py
"""
Functional test for selected public workspace prompt migration.
Version: 0.250.072
Implemented in: 0.250.072

This test ensures selected public workspace migrations copy current public_id
prompts, preserve legacy ownership compatibility, exclude unselected prompts,
and retain all-workspaces migration behavior.
"""

import copy
import importlib.util
from pathlib import Path
import sys
import types

from azure.core.exceptions import ResourceNotFoundError

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
sys.path.insert(0, str(APP_ROOT))

# Local application modules require the app source path during standalone test runs.
from functions_data_management_migration_state import initialize_migration_state
from functions_migration_provenance import create_migration_provenance_context


class FakeJobContainer:
    """Provide job and manifest persistence required by the migration helpers."""

    def __init__(self):
        self.manifest_batches = []

    def upsert_item(self, body):
        return copy.deepcopy(body)

    def create_item(self, body):
        self.manifest_batches.append(copy.deepcopy(body))
        return copy.deepcopy(body)


class FakePromptContainer:
    """Emulate selected public-prompt Cosmos queries and target writes."""

    def __init__(self, documents):
        self.documents = {
            document["id"]: copy.deepcopy(document)
            for document in documents
        }
        self.created = []
        self.queries = []

    def query_items(self, **kwargs):
        self.queries.append(copy.deepcopy(kwargs))
        selected_id = next(
            (
                parameter["value"]
                for parameter in kwargs.get("parameters") or []
                if parameter["name"] == "@selected_id"
            ),
            None,
        )
        query = kwargs.get("query") or ""
        filter_fields = [
            field_name
            for field_name in ("public_id", "public_workspace_id")
            if f"c.{field_name} = @selected_id" in query
        ]
        documents = list(self.documents.values())
        if selected_id is not None and filter_fields:
            documents = [
                document
                for document in documents
                if any(document.get(field_name) == selected_id for field_name in filter_fields)
            ]
        parameters = {
            parameter["name"]: parameter["value"]
            for parameter in kwargs.get("parameters") or []
        }
        if "@source_start_epoch" in parameters:
            documents = [
                document for document in documents
                if document.get("_ts", 0) >= parameters["@source_start_epoch"]
            ]
        if "@source_cutoff_epoch" in parameters:
            documents = [
                document for document in documents
                if document.get("_ts", 0) <= parameters["@source_cutoff_epoch"]
            ]
        return iter(copy.deepcopy(documents))

    def read_item(self, item, partition_key, **_kwargs):
        if item != partition_key or item not in self.documents:
            raise ResourceNotFoundError("not found")
        return copy.deepcopy(self.documents[item])

    def create_item(self, document, response_hook=None, **_kwargs):
        if document["id"] in self.documents:
            conflict = RuntimeError("conflict")
            conflict.status_code = 409
            raise conflict
        if response_hook:
            response_hook({"x-ms-request-charge": "1.0"}, document)
        stored_document = copy.deepcopy(document)
        self.documents[stored_document["id"]] = stored_document
        self.created.append(stored_document)
        return copy.deepcopy(stored_document)


class FakeTargetDatabase:
    """Return the isolated prompt target for the migration resource."""

    def __init__(self, target_container):
        self.target_container = target_container

    def create_container_if_not_exists(self, **_kwargs):
        return self.target_container


def load_data_management_module(monkeypatch, source_container, job_container):
    """Load the production migration module with focused Cosmos dependencies."""
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.072"
    config_module.cosmos_data_management_jobs_container = job_container
    config_module.cosmos_data_management_job_items_container = job_container
    config_module.cosmos_settings_container = job_container
    config_module.cosmos_public_prompts_container = source_container
    config_module.cosmos_public_prompts_container_name = "public-prompts"
    monkeypatch.setitem(sys.modules, "config", config_module)

    appinsights_module = types.ModuleType("functions_appinsights")
    appinsights_module.log_event = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "functions_appinsights", appinsights_module)

    throughput_module = types.ModuleType("functions_cosmos_throughput")
    throughput_module.CosmosThroughputError = RuntimeError
    throughput_module.get_container_throughput = lambda *_args, **_kwargs: {}
    throughput_module.get_database_throughput = lambda *_args, **_kwargs: {}
    throughput_module.set_database_throughput = lambda *_args, **_kwargs: {}
    monkeypatch.setitem(sys.modules, "functions_cosmos_throughput", throughput_module)

    module_name = "data_management_public_prompt_migration_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def copy_public_prompts(module, source_container, selection):
    """Run the production Cosmos copy path for only the public prompt resource."""
    prompt_definition = next(
        definition
        for definition in module.DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS["public_workspaces"]
        if definition["name"] == "public_prompts"
    )
    module.DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS = {
        "users": [],
        "groups": [],
        "public_workspaces": [prompt_definition],
    }
    target_container = FakePromptContainer([])
    migration_id = "11111111-1111-1111-1111-111111111111"
    migration_state = initialize_migration_state(
        None,
        migration_id,
        {"test": "public-prompt-migration"},
    )
    job = {"id": migration_id, "migration_state": migration_state}
    artifacts = module._copy_cosmos_records_to_target(
        FakeTargetDatabase(target_container),
        "public_workspaces",
        selection,
        job,
        migration_state,
        create_migration_provenance_context(migration_id=migration_id),
        {
            "migration_max_parallel_operations": 1,
            "migration_retry_count": 1,
            "data_management_job_lease_seconds": 900,
        },
    )
    return prompt_definition, target_container, artifacts


def test_selected_public_prompt_migration_supports_current_and_legacy_ownership(monkeypatch):
    """Copy selected current and legacy prompts exactly once while excluding others."""
    source_documents = [
        {"id": "current-selected", "public_id": "public-a", "_ts": 1},
        {"id": "legacy-selected", "public_workspace_id": "public-a", "_ts": 1},
        {
            "id": "transitional-selected",
            "public_id": "public-a",
            "public_workspace_id": "public-a",
            "_ts": 1,
        },
        {"id": "current-unselected", "public_id": "public-b", "_ts": 1},
        {"id": "legacy-unselected", "public_workspace_id": "public-b", "_ts": 1},
    ]
    source_container = FakePromptContainer(source_documents)
    module = load_data_management_module(monkeypatch, source_container, FakeJobContainer())
    selected_scope = {
        "mode": "selected",
        "ids": ["public-a"],
        "include_documents": False,
    }

    prompt_definition, target_container, artifacts = copy_public_prompts(
        module,
        source_container,
        selected_scope,
    )

    assert prompt_definition["filter_fields"] == ["public_id", "public_workspace_id"]
    assert {document["id"] for document in target_container.created} == {
        "current-selected",
        "legacy-selected",
        "transitional-selected",
    }
    assert len(target_container.created) == 3
    assert artifacts[0]["source_read_count"] == 3
    assert artifacts[0]["copied_count"] == 3
    assert artifacts[0]["created_count"] == 3
    assert artifacts[0]["failed_count"] == 0
    assert "c.public_id = @selected_id" in source_container.queries[0]["query"]
    assert "c.public_workspace_id = @selected_id" in source_container.queries[0]["query"]


def test_all_public_prompt_migration_remains_unfiltered(monkeypatch):
    """Copy every prompt for all-workspaces migration without selected-scope filtering."""
    source_documents = [
        {"id": "current-selected", "public_id": "public-a", "_ts": 1},
        {"id": "legacy-selected", "public_workspace_id": "public-a", "_ts": 1},
        {
            "id": "transitional-selected",
            "public_id": "public-a",
            "public_workspace_id": "public-a",
            "_ts": 1,
        },
        {"id": "current-unselected", "public_id": "public-b", "_ts": 1},
        {"id": "legacy-unselected", "public_workspace_id": "public-b", "_ts": 1},
    ]
    source_container = FakePromptContainer(source_documents)
    module = load_data_management_module(monkeypatch, source_container, FakeJobContainer())
    all_scope = {
        "mode": "all",
        "ids": [],
        "include_documents": False,
    }

    _prompt_definition, target_container, artifacts = copy_public_prompts(
        module,
        source_container,
        all_scope,
    )

    assert {document["id"] for document in target_container.created} == {
        document["id"] for document in source_documents
    }
    assert artifacts[0]["source_read_count"] == len(source_documents)
    assert artifacts[0]["copied_count"] == len(source_documents)
    assert "c.public_id = @selected_id" not in source_container.queries[0]["query"]
    assert "c.public_workspace_id = @selected_id" not in source_container.queries[0]["query"]
