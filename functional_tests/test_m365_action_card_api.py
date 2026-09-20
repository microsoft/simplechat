# test_m365_action_card_api.py
"""
Behavioral tests for authoritative M365 action cards and confirmation APIs.
Version: 0.261.038
Implemented in: 0.261.038

Real records, projections, route bodies, tenant/CSRF checks and delivery claims
run with scoped external storage/Graph seams. No live messages are sent.
"""

from contextlib import contextmanager
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Blueprint, Flask, session
import pytest


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Standalone tests establish the repository source path before real module imports.
import functions_m365_connections as connections
import functions_m365_pending_delivery as delivery
from functions_m365_context import M365ExecutionContext, m365_execution_context
from test_m365_routes import blueprint_guard, login_guard, module_stub, user_guard
from test_support.m365 import CosmosContainer, Query


class CardContainer(CosmosContainer):
    def __init__(self):
        super().__init__("user_id")
        self.queries = []
        self.query_error = None

    def query_items(self, query, parameters=None, partition_key=None, max_item_count=50, **kwargs):
        self.queries.append(query)
        if self.query_error:
            raise self.query_error
        values = {item["name"]: item["value"] for item in parameters or []}
        rows = deepcopy(list(self.items.values()))
        if partition_key is not None:
            rows = [row for row in rows if row["user_id"] == partition_key]
        for field in ("user_id", "type", "conversation_id", "workflow_id", "run_id", "request_id"):
            if f"@{field}" in values:
                rows = [row for row in rows if row.get(field) == values[f"@{field}"]]
        if "@action_ids" in values:
            rows = [row for row in rows if row["id"] in values["@action_ids"]]
        if "c.status IN" in query:
            rows = [row for row in rows if row["status"] in {"pending", "scheduled", "sending", "review_required", "recovery_required"}]
        rows.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
        if "TOP @limit" in query:
            rows = rows[:values["@limit"]]
        elif "TOP 100" in query:
            rows = rows[:100]
        return Query(rows, max_item_count)


def load_module(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture
def cards(monkeypatch):
    container = CardContainer()
    log = Mock()
    connection_service = connections.M365ConnectionService(
        container_factory=lambda: CosmosContainer("user_id"),
        config_provider=lambda: connections.M365IdentityConfig(
            "client", "tenant", "https://login.microsoftonline.com/tenant",
            "https://graph.microsoft.com", "azurecloud",
        ),
    )
    monkeypatch.setattr(connections, "_service", connection_service)
    seams = {
        "config": module_stub("config", cosmos_msgraph_pending_actions_container=container),
        "functions_appinsights": module_stub("functions_appinsights", log_event=log),
        "functions_debug": module_stub("functions_debug", debug_print=lambda *args: None),
        "functions_authentication": module_stub(
            "functions_authentication", login_required=login_guard, user_required=user_guard,
            user_required_blueprint=blueprint_guard, get_valid_access_token_for_plugins=Mock(),
        ),
        "swagger_wrapper": module_stub(
            "swagger_wrapper", swagger_route=lambda **kwargs: lambda function: function, get_auth_security=lambda: [],
        ),
    }
    with patch.dict(sys.modules, seams):
        security = load_module("card_test_security", APP / "route_backend_m365.py")
        service = load_module("card_test_service", APP / "functions_msgraph_pending_actions.py")
        with patch.dict(sys.modules, {
            "route_backend_m365": security, "functions_msgraph_pending_actions": service,
        }):
            routes = load_module("card_test_routes", APP / "route_backend_msgraph_pending_actions.py")
    writes = []

    @contextmanager
    def context_scope(action, **kwargs):
        with m365_execution_context(M365ExecutionContext(**action["m365_execution"]["context"])):
            yield

    class Transport:
        def __init__(self, source, action_id, **kwargs):
            self.before_request = None

        @contextmanager
        def operation_context(self, operation):
            yield

        @contextmanager
        def callback_context(self, before_request, on_progress):
            self.before_request = before_request
            yield
            self.before_request = None

        def get_token(self, scopes):
            return "offline", scopes

        def request_json(self, method, path, scopes, **kwargs):
            if method == "GET":
                return {"isDraft": True, "changeKey": "draft-version"}
            if self.before_request:
                self.before_request()
            writes.append((method, path, deepcopy(kwargs.get("json_body"))))
            return {"id": "event-created", "webLink": "https://outlook.example.test/event"}

    def authorize_conversation(user_id, conversation_id):
        if user_id not in {"owner", "viewer"} or conversation_id != "conversation":
            raise PermissionError("Denied")
        return conversation_id

    monkeypatch.setattr(delivery, "_dependencies", {})
    delivery.configure_m365_pending_delivery(
        container=container, context_scope=context_scope, log_event=log, transport_factory=Transport,
        notification_sender=lambda action: {"id": "notice"},
        capture_agent_reference=lambda context, action_id: {"id": "agent", "name": "agent"},
        conversation_authorizer=authorize_conversation,
        view_authorizer=lambda action, viewer: viewer == action["user_id"] or (
            viewer == "viewer" and action.get("m365_execution", {}).get("context", {}).get("shared")
        ),
    )
    app = Flask(__name__)
    app.secret_key = "offline-only"
    app.config["TESTING"] = True
    blueprint = Blueprint("card_test", __name__)
    blueprint.before_request(blueprint_guard())
    routes.register_route_backend_msgraph_pending_actions(blueprint)
    app.register_blueprint(blueprint)
    client = app.test_client()
    csrf = "c" * 40

    def sign_in(owner="owner", tenant="tenant"):
        with client.session_transaction() as saved_session:
            saved_session.update(user={"oid": owner, "tid": tenant, "roles": ["User"]}, m365_csrf_token=csrf)

    sign_in()

    def create(operation="create_calendar_invite", *, shared=False, body="Exact reviewed content"):
        source_type = "m365_calendar" if operation == "create_calendar_invite" else "m365_email"
        context = M365ExecutionContext(
            "owner", "owner", "tenant", conversation_id="conversation", request_id="request",
            shared=shared, audience_version="audience", action_configs={"source-action": {"type": source_type}},
        )
        payload = {
            "subject": "Review me", "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": "reviewed@example.test"}}],
            "bccRecipients": [{"emailAddress": {"address": "private@example.test"}}],
        }
        graph_payload = payload if operation == "create_calendar_invite" else {"message": payload, "saveToSentItems": True}
        with app.test_request_context(), m365_execution_context(context):
            return service.create_msgraph_pending_action(
                "owner", operation=operation, graph_resource_type="calendar" if source_type == "m365_calendar" else "mail",
                action_mode="manual", conversation_id="conversation", graph_payload=graph_payload,
                graph_message_id="draft" if source_type == "m365_email" else "",
                graph_draft_version="draft-version" if source_type == "m365_email" else "",
                summary={
                    "subject": "Review me", "body_preview": body,
                    "bcc_recipients": ["private@example.test"], "to_recipients": ["reviewed@example.test"],
                }, m365_action_id="source-action",
            )

    return SimpleNamespace(
        container=container, service=service, routes=routes, client=client, create=create,
        writes=writes, sign_in=sign_in, headers={"X-M365-CSRF-Token": csrf}, log=log, app=app,
    )


@pytest.mark.parametrize("operation", ["create_calendar_invite", "send_mail"])
def test_card_creation_and_read_never_send_and_confirmation_sends_once(cards, operation):
    created = cards.create(operation)
    response = cards.client.get(f"/api/msgraph/pending-actions/{created['id']}")
    card = response.get_json()["pending_action"]
    assert response.status_code == 200
    assert card["can_send_now"] and card["can_cancel"] and card["version"]
    assert "graph_payload" not in card and "graph_endpoint" not in card and "m365_execution" not in card
    assert cards.writes == []
    sent = cards.client.post(
        f"/api/msgraph/pending-actions/{created['id']}/send-now",
        json={"expected_version": card["version"]}, headers=cards.headers,
    )
    repeated = cards.client.post(
        f"/api/msgraph/pending-actions/{created['id']}/send-now",
        json={"expected_version": card["version"]}, headers=cards.headers,
    )
    assert sent.status_code == repeated.status_code == 200
    assert sent.get_json()["pending_action"]["status"] == "sent"
    assert len(cards.writes) == 1


def test_cancel_stops_without_remote_calls_and_is_not_a_recall(cards):
    created = cards.create()
    cancelled = cards.client.post(
        f"/api/msgraph/pending-actions/{created['id']}/cancel",
        json={"expected_version": created["version"]}, headers=cards.headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.get_json()["pending_action"]["status"] == "cancelled"
    assert cards.writes == []


def test_csrf_revision_and_owner_checks_precede_delivery(cards):
    created = cards.create()
    path = f"/api/msgraph/pending-actions/{created['id']}/send-now"
    no_csrf = cards.client.post(path, json={"expected_version": created["version"]})
    stale = cards.client.post(path, json={"expected_version": "stale"}, headers=cards.headers)
    cards.sign_in("viewer")
    other_owner = cards.client.post(path, json={"expected_version": created["version"]}, headers=cards.headers)
    assert no_csrf.status_code == 403
    assert stale.status_code == 409
    assert other_owner.status_code == 404
    assert cards.writes == []


def test_shared_viewers_receive_read_only_cards_without_private_preview(cards):
    created = cards.create(shared=True)
    cards.sign_in("viewer")
    response = cards.client.get("/api/msgraph/pending-actions?conversation_id=conversation")
    card = response.get_json()["pending_actions"][0]
    assert card["id"] == created["id"]
    assert card["can_send_now"] is False and card["can_cancel"] is False
    assert card["viewer_is_owner"] is False
    assert "bcc_recipients" not in card["summary"]
    assert "body_preview" not in card["summary"]
    assert cards.writes == []


def test_shared_refresh_requires_conversation_access_and_never_enables_owner_controls(cards):
    created = cards.create("send_mail", shared=True)
    cards.sign_in("viewer")
    owner_partition = cards.client.get(f"/api/msgraph/pending-actions/{created['id']}")
    shared = cards.client.get(
        f"/api/msgraph/pending-actions/{created['id']}?conversation_id=conversation",
    )
    unrelated = cards.client.get(
        f"/api/msgraph/pending-actions/{created['id']}?conversation_id=unrelated",
    )
    assert owner_partition.status_code == 404
    assert unrelated.status_code == 403
    assert shared.status_code == 200
    card = shared.get_json()["pending_action"]
    assert not card["viewer_is_owner"] and not card["can_send_now"] and not card["can_cancel"]
    assert "bcc_recipients" not in card["summary"] and "body_preview" not in card["summary"]
    assert cards.writes == []


def test_history_hydration_discards_saved_permissions_and_inaccessible_references(cards):
    created = cards.create("send_mail", shared=True)
    message = {
        "id": "message", "conversation_id": "conversation",
        "m365_pending_actions": [{"id": created["id"], "can_send_now": True, "summary": {"body_preview": "stale"}}],
        "metadata": {"m365_pending_action_ids": [created["id"], "unrelated"]},
    }
    hydrated = cards.service.hydrate_m365_pending_action_cards([message], "viewer", "conversation")
    assert hydrated[0]["metadata"]["m365_pending_action_ids"] == [created["id"]]
    card = hydrated[0]["m365_pending_actions"][0]
    assert not card["can_send_now"] and "body_preview" not in card["summary"]
    assert message["m365_pending_actions"][0]["can_send_now"] is True
    assert message["metadata"]["m365_pending_action_ids"] == [created["id"], "unrelated"]


def test_inaccessible_conversation_is_rejected_before_query(cards):
    response = cards.client.get("/api/msgraph/pending-actions?conversation_id=unrelated")
    assert response.status_code == 403
    assert cards.container.queries == []


def test_list_failure_is_an_error_not_an_empty_success(cards):
    from azure.cosmos.exceptions import CosmosHttpResponseError

    cards.container.query_error = CosmosHttpResponseError(status_code=503)
    response = cards.client.get("/api/msgraph/pending-actions")
    payload = response.get_json()
    assert response.status_code == 503
    assert payload["success"] is False
    assert "pending_actions" not in payload


def test_large_body_requires_complete_owner_review_before_showing_send(cards):
    body = "The complete review content. " * 400
    created = cards.create("send_mail", body=body)
    listed = cards.client.get("/api/msgraph/pending-actions")
    preview = listed.get_json()["pending_actions"][0]
    assert len(preview["summary"]["body_preview"]) == cards.service.MSGRAPH_PENDING_PREVIEW_CHARACTERS
    assert preview["review_details_required"] and preview["summary"]["body_preview_truncated"]
    assert not preview["can_send_now"]
    full = cards.client.get(f"/api/msgraph/pending-actions/{created['id']}")
    reviewed = full.get_json()["pending_action"]
    assert reviewed["summary"]["body_preview"] == body
    assert reviewed["summary"]["bcc_recipients"] == ["private@example.test"]
    assert reviewed["can_send_now"] and not reviewed["review_details_required"]
    assert cards.writes == []


def test_projection_disables_changed_material_and_new_unbound_writes_fail(cards):
    created = cards.create()
    action = cards.container.read_item(created["id"], "owner")
    action["graph_payload"]["subject"] = "Not the reviewed subject"
    cards.container.upsert_item(body=action)
    response = cards.client.get(f"/api/msgraph/pending-actions/{created['id']}")
    invalid = response.get_json()["pending_action"]
    assert invalid["requires_recreation"] and not invalid["can_send_now"] and invalid["can_cancel"]
    with pytest.raises(delivery.M365PolicyError):
        cards.service.create_msgraph_pending_action(
            "owner", operation="create_calendar_invite", graph_resource_type="calendar",
            action_mode="manual", graph_payload={"subject": "Unbound"},
        )
    assert len(cards.container.items) == 1


@pytest.mark.parametrize("binding", [None, "legacy", [], {"context": "invalid"}])
def test_malformed_legacy_bindings_remain_cancellable_not_executable(cards, binding):
    created = cards.create()
    action = cards.container.read_item(created["id"], "owner")
    action.update(m365_execution=binding, summary=["invalid legacy summary"])
    cards.container.upsert_item(body=action)
    response = cards.client.get(f"/api/msgraph/pending-actions/{created['id']}")
    card = response.get_json()["pending_action"]
    assert response.status_code == 200
    assert card["requires_recreation"] and not card["can_send_now"] and card["can_cancel"]
    assert card["summary"] == {} and cards.writes == []


def test_owner_pagination_is_bounded_and_cursors_cannot_change_scope(cards):
    for _ in range(3):
        cards.create(shared=True)
    first = cards.client.get("/api/msgraph/pending-actions?limit=2")
    payload = first.get_json()
    assert len(payload["pending_actions"]) == 2 and payload["continuation_token"]
    second = cards.client.get("/api/msgraph/pending-actions", query_string={
        "limit": 2, "continuation_token": payload["continuation_token"],
    })
    changed_scope = cards.client.get("/api/msgraph/pending-actions", query_string={
        "conversation_id": "conversation", "continuation_token": payload["continuation_token"],
    })
    invalid = cards.client.get("/api/msgraph/pending-actions?continuation_token=invalid")
    assert len(second.get_json()["pending_actions"]) == 1
    assert second.get_json()["continuation_token"] is None
    assert changed_scope.status_code == invalid.status_code == 400
    assert cards.writes == []


def test_historical_provider_errors_are_not_returned_as_raw_diagnostics(cards):
    created = cards.create()
    action = cards.container.read_item(created["id"], "owner")
    action.update(status="failed", error="A provider credential must not be displayed")
    saved = cards.container.upsert_item(body=action)
    response = cards.client.post(
        f"/api/msgraph/pending-actions/{created['id']}/send-now",
        json={"expected_version": saved["_etag"]}, headers=cards.headers,
    )
    assert response.status_code == 409
    assert "provider credential" not in response.get_data(as_text=True)
    assert cards.writes == []


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
