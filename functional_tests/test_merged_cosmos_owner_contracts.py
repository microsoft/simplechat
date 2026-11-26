# test_merged_cosmos_owner_contracts.py
"""
Functional tests for merged Cosmos owner response contracts.
Version: 0.261.483
Implemented in: 0.261.483

The tests execute the real owner functions with installed-SDK point responses
and plain query rows while keeping application bootstrap and Azure I/O offline.
"""

import ast
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from azure.core import MatchConditions
from azure.cosmos._cosmos_responses import CosmosDict
from azure.cosmos import exceptions


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"


def load_functions(path, names, namespace):
    """Execute selected real function definitions with supplied owner dependencies."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in selected} == names
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)


def test_update_user_settings_accepts_sdk_point_and_preserves_etag_write():
    document = {
        "id": "owner",
        "_etag": "etag-1",
        "settings": {
            "agents": [{"id": "agent", "name": "Agent"}],
            "plugins": [],
            "selected_agent": {"id": "agent"},
            "enable_agents": True,
        },
    }

    class Container:
        def __init__(self):
            self.replaced = None

        def read_item(self, item, partition_key):
            assert item == partition_key == "owner"
            return CosmosDict(deepcopy(document), response_headers={})

        def replace_item(self, item, *, body, etag, match_condition):
            assert item == "owner"
            assert etag == "etag-1"
            assert match_condition == MatchConditions.IfNotModified
            self.replaced = deepcopy(dict(body))
            return CosmosDict({**dict(body), "_etag": "etag-2"}, response_headers={})

    container = Container()
    namespace = {
        "MatchConditions": MatchConditions,
        "SettingsConflictError": RuntimeError,
        "_authorize_user_settings_access": lambda user_id, _operation, **_kwargs: user_id,
        "_delete_user_ui_settings_cache": lambda _user_id: None,
        "_set_request_cached_user_settings": lambda _user_id, _document: None,
        "copy": SimpleNamespace(deepcopy=deepcopy),
        "cosmos_user_settings_container": container,
        "datetime": SimpleNamespace(now=lambda _timezone: datetime(2026, 11, 25, tzinfo=timezone.utc)),
        "exceptions": exceptions,
        "log_event": lambda *_args, **_kwargs: None,
        "reserve_model_endpoint_ca_references": lambda *_args, **_kwargs: nullcontext(False),
        "sanitize_settings_for_logging": lambda value: value,
        "timezone": timezone,
        "validate_legacy_plugin_settings_update": lambda *_args, **_kwargs: None,
    }
    load_functions(APP / "functions_settings.py", {"update_user_settings"}, namespace)

    assert namespace["update_user_settings"](
        "owner",
        {"fontSizePreference": "large"},
        expected_etag="etag-1",
    )
    assert container.replaced["settings"]["fontSizePreference"] == "large"
    assert container.replaced["_etag"] == "etag-1"


def test_group_endpoint_references_accept_plain_query_rows():
    class QueryContainer:
        def __init__(self, rows):
            self.rows = rows

        def query_items(self, **kwargs):
            assert kwargs["partition_key"] == "group-a"
            return list(deepcopy(self.rows))

    agents = QueryContainer([{
        "id": "agent-a",
        "name": "Agent",
        "agent_type": "local",
        "model_endpoint_id": "endpoint-a",
        "other_settings": {},
    }])
    workflows = QueryContainer([{
        "id": "workflow-a",
        "name": "Workflow",
        "tasks": [{
            "runner": {
                "model_endpoint_id": "endpoint-a",
            },
        }],
    }])
    namespace = {
        "GROUP_ENDPOINT_FOUNDRY_AGENT_SETTINGS": {
            "aifoundry": "azure_ai_foundry",
        },
        "GroupEndpointError": RuntimeError,
        "cosmos_group_agents_container": agents,
        "cosmos_group_workflows_container": workflows,
        "log_event": lambda *_args, **_kwargs: None,
    }
    load_functions(
        APP / "functions_group_endpoint_access.py",
        {
            "_same_endpoint",
            "_agent_uses_endpoint",
            "_workflow_uses_endpoint",
            "find_group_endpoint_references",
        },
        namespace,
    )

    references = namespace["find_group_endpoint_references"]("group-a", "endpoint-a")
    assert references == [
        {"kind": "agent", "id": "agent-a", "name": "Agent"},
        {"kind": "workflow", "id": "workflow-a", "name": "Workflow"},
    ]
