# test_mcp_drift_cosmos_contract.py
"""Real-owner MCP drift persistence and notification retry contracts.

Version: 0.261.459
Implemented in: 0.261.459

Uses the shared SDK-default container and the installed CosmosDict without Azure
bootstrap or network access. Runtime config imports supply only storage handles.
"""

from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import patch

import pytest
from azure.cosmos._cosmos_responses import CosmosDict


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_action_manifest import bind_action_origin
import functions_mcp_tool_pinning as pinning
from test_support.workflow_chat_delivery_fakes import FakeContainer


@pytest.mark.parametrize("scope,container_name,partition_field", [
    ("personal", "cosmos_personal_actions_container", "user_id"),
    ("group", "cosmos_group_actions_container", "group_id"),
    ("global", "cosmos_global_actions_container", "id"),
])
def test_drift_owner_persists_sdk_documents_and_retries_notification(scope, container_name, partition_field):
    scope_id = "global" if scope == "global" else "owner-1"
    partition_key = "action-1" if scope == "global" else scope_id
    actions = FakeContainer("mcp-actions")
    notifications = FakeContainer("mcp-notifications")
    seeded = actions.create_item({
        "id": "action-1", "type": "mcp", partition_field: partition_key,
        "additionalFields": {"retained": {"value": "unchanged"}},
    })
    action = bind_action_origin(seeded, scope, scope_id)
    config = ModuleType("config")
    setattr(config, container_name, actions)
    config.cosmos_notifications_container = notifications
    drift = {
        "has_drift": True, "manifest_hash": "changed-manifest",
        "new": ["wait"], "changed": ["search"], "removed": [],
    }

    with patch.dict(sys.modules, {"config": config}), patch.object(pinning, "log_event") as logged:
        pinning.persist_mcp_tool_drift(action, drift)
        first = actions.read_item(item="action-1", partition_key=partition_key)
        pinning.persist_mcp_tool_drift(action, drift)

    stored = actions.read_item(item="action-1", partition_key=partition_key)
    notification_id = next(iter(notifications.items))
    notification = notifications.read_item(
        item=notification_id, partition_key=scope_id if scope == "personal" else None,
    )

    assert type(seeded) is CosmosDict
    assert type(first) is CosmosDict
    assert type(stored) is CosmosDict
    assert type(notification) is CosmosDict
    assert stored["_etag"] != first["_etag"] != seeded["_etag"]
    assert stored[partition_field] == partition_key
    assert stored["additionalFields"]["retained"] == {"value": "unchanged"}
    assert stored["additionalFields"]["mcp_tool_drift"]["manifest_hash"] == "changed-manifest"
    assert stored["additionalFields"]["mcp_tool_drift"]["changed"] == ["search"]
    assert action["additionalFields"]["mcp_tool_drift"]["new"] == ["wait"]
    assert ("read_item", "action-1", partition_key) in actions.calls
    assert len(notifications.items) == 1
    assert notification["scope"] == ("assignment" if scope == "global" else scope)
    assert notification["user_id"] == (scope_id if scope == "personal" else None)
    assert notification["group_id"] == (scope_id if scope == "group" else None)
    assert notification["metadata"]["scope_id"] == scope_id
    assert notification["metadata"]["action_id"] == "action-1"
    assert notifications.calls.count(("create_item", notification_id)) == 2
    assert notifications.calls.count((
        "read_item", notification_id, scope_id if scope == "personal" else None,
    )) == 2
    assert logged.call_count == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
