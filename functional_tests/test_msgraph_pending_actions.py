# test_msgraph_pending_actions.py
#!/usr/bin/env python3
"""
Functional test for Microsoft Graph pending actions.
Version: 0.241.179
Implemented in: 0.241.179

This test ensures user-owned pending Microsoft Graph mail and calendar actions
can be sanitized for the browser, approved, sent, and cancelled without exposing
stored Graph request payloads to the frontend.
"""

from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

if "olefile" not in sys.modules:
    sys.modules["olefile"] = types.ModuleType("olefile")


import functions_msgraph_pending_actions as pending_module  # noqa: E402


class FakePendingActionContainer:
    def __init__(self):
        self.items = {}

    def upsert_item(self, body):
        item = dict(body)
        self.items[(item["user_id"], item["id"])] = item
        return dict(item)

    def read_item(self, item, partition_key):
        return dict(self.items[(partition_key, item)])

    def query_items(self, query, parameters=None, partition_key=None):
        del query
        filters = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        results = []
        for (user_id, _), item in self.items.items():
            if partition_key and user_id != partition_key:
                continue
            if filters.get("@user_id") and item.get("user_id") != filters.get("@user_id"):
                continue
            if filters.get("@type") and item.get("type") != filters.get("@type"):
                continue
            if filters.get("@conversation_id") and item.get("conversation_id") != filters.get("@conversation_id"):
                continue
            if filters.get("@workflow_id") and item.get("workflow_id") != filters.get("@workflow_id"):
                continue
            if filters.get("@run_id") and item.get("run_id") != filters.get("@run_id"):
                continue
            results.append(dict(item))
        return sorted(results, key=lambda action: action.get("created_at") or "")


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("No JSON payload")
        return self._payload


def test_msgraph_pending_action_send_and_cancel():
    """Verify send-now and cancel paths update user-owned pending actions."""
    print("Testing Microsoft Graph pending action send/cancel behavior...")

    fake_container = FakePendingActionContainer()
    original_container = pending_module.cosmos_msgraph_pending_actions_container
    original_request = pending_module.requests.request
    original_token_helper = pending_module.get_valid_access_token_for_plugins

    request_log = []

    def fake_token_helper(scopes=None):
        request_log.append({"scopes": scopes})
        return {"access_token": "fake-token"}

    def fake_request(method, url, headers=None, json=None, timeout=None):
        request_log.append({
            "method": method,
            "url": url,
            "headers": headers,
            "json": json,
            "timeout": timeout,
        })
        if method == "POST" and url.endswith("/v1.0/me/messages/draft-123/send"):
            return FakeResponse(202)
        if method == "DELETE" and url.endswith("/v1.0/me/messages/draft-cancel"):
            return FakeResponse(204)
        if method == "POST" and url.endswith("/v1.0/me/events"):
            return FakeResponse(201, {"id": "event-123", "webLink": "https://calendar.example.test/event"})
        return FakeResponse(500, text="Unexpected request")

    try:
        pending_module.cosmos_msgraph_pending_actions_container = fake_container
        pending_module.requests.request = fake_request
        pending_module.get_valid_access_token_for_plugins = fake_token_helper

        mail_action = pending_module.create_msgraph_pending_action(
            "user-1",
            operation=pending_module.MSGRAPH_PENDING_OPERATION_SEND_MAIL,
            graph_resource_type=pending_module.MSGRAPH_PENDING_RESOURCE_MAIL,
            action_mode=pending_module.MSGRAPH_PENDING_ACTION_MANUAL,
            graph_message_id="draft-123",
            graph_payload={"subject": "Hidden draft payload"},
            summary={"subject": "Visible subject", "to_recipients": ["ada@example.com"]},
            conversation_id="conversation-1",
        )
        sanitized = pending_module.sanitize_msgraph_pending_action_for_client(mail_action)
        if "graph_payload" in sanitized or sanitized.get("subject") != "Visible subject":
            print(f"Expected browser-safe pending action summary, got: {sanitized}")
            return False

        sent_action, send_error = pending_module.approve_msgraph_pending_action("user-1", mail_action["id"])
        if send_error or sent_action.get("status") != pending_module.MSGRAPH_PENDING_STATUS_SENT:
            print(f"Expected sent pending mail action, got action={sent_action}, error={send_error}")
            return False
        if request_log[0].get("scopes") != ["Mail.Send"] or request_log[1].get("method") != "POST":
            print(f"Expected Mail.Send POST for pending mail action, got: {request_log[:2]}")
            return False

        cancel_action = pending_module.create_msgraph_pending_action(
            "user-1",
            operation=pending_module.MSGRAPH_PENDING_OPERATION_SEND_MAIL,
            graph_resource_type=pending_module.MSGRAPH_PENDING_RESOURCE_MAIL,
            action_mode=pending_module.MSGRAPH_PENDING_ACTION_DELAYED,
            graph_message_id="draft-cancel",
            summary={"subject": "Cancel me"},
        )
        cancelled_action, cancel_error = pending_module.cancel_msgraph_pending_action("user-1", cancel_action["id"])
        if cancel_error or cancelled_action.get("status") != pending_module.MSGRAPH_PENDING_STATUS_CANCELLED:
            print(f"Expected cancelled pending mail action, got action={cancelled_action}, error={cancel_error}")
            return False
        if request_log[2].get("scopes") != ["Mail.ReadWrite"] or request_log[3].get("method") != "DELETE":
            print(f"Expected Mail.ReadWrite DELETE for pending mail cancellation, got: {request_log[2:4]}")
            return False

        calendar_action = pending_module.create_msgraph_pending_action(
            "user-1",
            operation=pending_module.MSGRAPH_PENDING_OPERATION_CREATE_CALENDAR_INVITE,
            graph_resource_type=pending_module.MSGRAPH_PENDING_RESOURCE_CALENDAR,
            action_mode=pending_module.MSGRAPH_PENDING_ACTION_MANUAL,
            graph_payload={"subject": "Planning", "start": {"dateTime": "2025-05-01T09:00:00"}},
            summary={"subject": "Planning"},
            workflow_id="workflow-1",
            run_id="run-1",
        )
        committed_calendar, calendar_error = pending_module.approve_msgraph_pending_action("user-1", calendar_action["id"])
        if calendar_error or committed_calendar.get("graph_event_id") != "event-123":
            print(f"Expected created pending calendar event, got action={committed_calendar}, error={calendar_error}")
            return False
        if request_log[4].get("scopes") != ["Calendars.ReadWrite"] or request_log[5].get("json", {}).get("subject") != "Planning":
            print(f"Expected Calendars.ReadWrite POST for pending calendar action, got: {request_log[4:6]}")
            return False

        listed = pending_module.list_msgraph_pending_actions("user-1", workflow_id="workflow-1", run_id="run-1")
        if len(listed) != 1 or listed[0].get("id") != calendar_action["id"]:
            print(f"Expected filtered pending calendar action list, got: {listed}")
            return False

        print("Microsoft Graph pending actions send, cancel, sanitize, and filter correctly")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        pending_module.cosmos_msgraph_pending_actions_container = original_container
        pending_module.requests.request = original_request
        pending_module.get_valid_access_token_for_plugins = original_token_helper


if __name__ == "__main__":
    success = test_msgraph_pending_action_send_and_cancel()
    sys.exit(0 if success else 1)