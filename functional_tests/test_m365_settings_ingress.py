# test_m365_settings_ingress.py
"""
Regression tests for retired Graph actions at the generic settings boundary.
Version: 0.261.031
Implemented in: 0.261.029

Executes the production writer with isolated storage/cache I/O and the real
legacy validator. Cold-import coverage separately exercises the owning module.
"""

import ast
from datetime import datetime, timezone
import logging
from pathlib import Path
import sys

from azure.core import MatchConditions
from azure.cosmos import exceptions
import pytest


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# The standalone source path must be initialized before repository imports.
from json_schema_validation import validate_legacy_plugin_settings_update
from test_support.m365 import CosmosContainer


def writer(container):
    tree = ast.parse((APP / "functions_settings.py").read_text(encoding="utf-8-sig"))
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "update_user_settings")
    events = []
    namespace = {
        "_authorize_user_settings_access": lambda user_id, *args, **kwargs: user_id,
        "sanitize_settings_for_logging": lambda changes: {"fields": list(changes)},
        "log_event": lambda message, *args, **kwargs: events.append(message),
        "cosmos_user_settings_container": container,
        "validate_legacy_plugin_settings_update": validate_legacy_plugin_settings_update,
        "MatchConditions": MatchConditions,
        "exceptions": exceptions, "datetime": datetime, "timezone": timezone, "logging": logging,
        "get_settings": lambda: {},
        "_set_request_cached_user_settings": lambda *args: None,
        "_delete_user_ui_settings_cache": lambda *args: None,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(APP / "functions_settings.py"), "exec"), namespace)
    return namespace["update_user_settings"], events


@pytest.mark.parametrize("field", ["plugins", "semantic_kernel_plugins"])
@pytest.mark.parametrize("alias", ["msgraph", "Microsoft Graph Plugin"])
def test_generic_settings_cannot_introduce_a_retired_action(field, alias):
    container = CosmosContainer("id")
    update, events = writer(container)
    saved = update("owner", {field: [{"id": "new-action", "type": alias}]})
    assert saved is False
    assert container.items == {}
    assert any("Rejected invalid or retired" in event for event in events)


def test_existing_exact_legacy_entry_remains_editable():
    container = CosmosContainer("id")
    container.create_item(body={
        "id": "owner", "settings": {
            "plugins": [{"id": "old", "type": "msgraph"}],
            "agents": [{"id": "agent", "name": "Agent"}], "selected_agent": {"id": "agent"},
        },
    })
    update, events = writer(container)
    saved = update("owner", {"plugins": [{"id": "old", "type": "msgraph", "description": "Updated"}]})
    record = container.read_item("owner", "owner")
    assert saved is True
    assert record["settings"]["plugins"][0]["description"] == "Updated"


@pytest.mark.parametrize("changes", [
    {"plugins": [{"id": "old", "type": "msgraph", "description": "Stale edit"}]},
    {"theme": "dark"},
])
def test_concurrent_removal_cannot_be_undone_by_a_stale_settings_write(changes):
    class Container(CosmosContainer):
        def replace_item(self, item, body, **kwargs):
            latest = self.read_item(item, body[self.partition_field])
            latest["settings"]["plugins"] = []
            self.upsert_item(body=latest)
            return super().replace_item(item, body, **kwargs)

    container = Container("id")
    container.create_item(body={
        "id": "owner", "settings": {
            "plugins": [{"id": "old", "type": "msgraph"}],
            "agents": [{"id": "agent", "name": "Agent"}], "selected_agent": {"id": "agent"},
        },
    })
    update, events = writer(container)
    saved = update("owner", changes)
    record = container.read_item("owner", "owner")
    assert saved is False
    assert record["settings"]["plugins"] == []
    assert any("Cosmos DB HTTP error" in event for event in events)


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
