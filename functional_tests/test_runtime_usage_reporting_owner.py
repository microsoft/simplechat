# test_runtime_usage_reporting_owner.py
"""
Real-module offline Control Center usage owner coverage.
Version: 0.261.447
Implemented in: 0.261.447
"""

import importlib
from pathlib import Path

from azure.cosmos._cosmos_responses import CosmosDict
from flask import Blueprint, Flask

from test_control_center_usage import UsageQueryStore, event
from test_orchestration_harness_execution import initialized_application


class UserPointStore:
    """Installed-SDK point response, distinct from plain query rows."""

    def __init__(self):
        self.response = CosmosDict({
            "id": "viewer", "_etag": '"usage-owner-etag"',
            "email": "viewer@example.test", "display_name": "Usage viewer",
        }, response_headers={})
        self.reads = []

    def read_item(self, item, partition_key):
        self.reads.append((item, partition_key))
        return self.response


def test_real_control_center_usage_owners(initialized_application, monkeypatch):
    """Import the actual owner and exercise its registered handlers, not extracted AST."""
    route = importlib.import_module("route_backend_control_center")
    authentication = importlib.import_module("functions_authentication")
    root = Path(__file__).resolve().parents[1] / "application" / "single_app"
    assert Path(route.__file__).resolve().parent == root
    settings = {"require_member_of_control_center_admin": True}
    monkeypatch.setattr(authentication, "get_settings", lambda: settings)
    store = UsageQueryStore([event(1), event(2, outcome="failed")])
    monkeypatch.setattr(route, "cosmos_activity_logs_container", store)
    app = Flask(__name__)
    app.secret_key = "offline-usage-owner"
    app.testing = True
    bp = Blueprint("usage_owner_contract", __name__)
    route.register_route_backend_control_center(bp)
    app.register_blueprint(bp)
    client = app.test_client()
    path = "/api/v2/control-center/activity-logs/usage?refresh=true"
    denied = client.get(path)
    assert denied.status_code in (302, 401)
    assert not store.queries
    with client.session_transaction() as state:
        state["user"] = {"oid": "viewer", "roles": ["ControlCenterAdmin"]}
    response = client.get(path)
    assert response.status_code == 200
    assert response.get_json()["totals"]["action"]["invocations"] == 2
    csv_response = client.get("/api/admin/control-center/activity-logs/usage?format=csv")
    assert csv_response.status_code == 200
    assert "raw_json" not in csv_response.get_data(as_text=True)
    where, params = route.build_activity_logs_query_context(usage_args={
        "usage_view": "true", "usage_kind": "action", "usage_auth": "managed_identity",
    })
    assert "c.runtime_usage.auth_type" in where
    assert {"name": "@usage_auth", "value": "managed_identity"} in params


def test_real_activity_query_and_user_point_consumers(initialized_application, monkeypatch):
    """Exercise representative real-owner mapping consumers with SDK-default points."""
    route = importlib.import_module("route_backend_control_center")
    activity = importlib.import_module("functions_control_center_activity")
    users = UserPointStore()
    monkeypatch.setattr(route, "cosmos_user_settings_container", users)
    cache = {}
    details = route.get_activity_log_user_details("viewer", cache)
    assert details == {"email": "viewer@example.test", "display_name": "Usage viewer"}
    assert users.reads == [("viewer", "viewer")]
    assert users.response["_etag"] == '"usage-owner-etag"'
    cached = route.get_activity_log_user_details("viewer", cache)
    assert cached == details
    assert len(users.reads) == 1
    store = UsageQueryStore([event(1)])
    filters = activity.parse_activity_filters({"usage_kind": "action"})
    rows, snapshot = activity.query_activity_rows(store, filters, 20)
    assert rows[0]["activity_type"] == "action_run"
    assert snapshot
    assert {"name": "@usage_kind", "value": "action"} in store.queries[0]["parameters"]
