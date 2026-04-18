# test_msgraph_plugin_operations.py
#!/usr/bin/env python3
"""
Functional test for Microsoft Graph plugin operations.
Version: 0.241.037
Implemented in: 0.241.037

This test ensures the Microsoft Graph plugin exposes high-value read
operations plus focused mail state updates and calendar invite creation,
routes requests through the shared Graph helper, and handles pagination and
token consent failures safely.
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


from semantic_kernel_plugins.msgraph_plugin import MSGraphPlugin  # noqa: E402
import semantic_kernel_plugins.msgraph_plugin as msgraph_module  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, payload, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


def test_msgraph_plugin_exposes_expected_operations() -> bool:
    """Verify the plugin metadata and registration expose the new operations."""
    print("Testing Microsoft Graph plugin metadata and function registration...")

    plugin = MSGraphPlugin({"name": "msgraph_plugin"})
    expected_functions = {
        "get_my_profile",
        "get_my_timezone",
        "get_my_events",
        "create_calendar_invite",
        "get_my_messages",
        "mark_message_as_read",
        "search_users",
        "get_user_by_email",
        "list_drive_items",
        "get_my_security_alerts",
    }

    registered_functions = set(plugin.get_functions())
    if expected_functions != registered_functions:
        print(f"Unexpected function registration. Got: {sorted(registered_functions)}")
        return False

    method_names = {method["name"] for method in plugin.metadata.get("methods", [])}
    missing_methods = expected_functions - method_names
    if missing_methods:
        print(f"Metadata missing methods: {sorted(missing_methods)}")
        return False

    print("Microsoft Graph plugin metadata includes the expected operations")
    return True


def test_msgraph_plugin_paginates_and_truncates_list_results() -> bool:
    """Verify the shared Graph helper paginates list results up to the requested max."""
    print("Testing Microsoft Graph helper pagination behavior...")

    plugin = MSGraphPlugin({"name": "msgraph_plugin"})
    original_token_helper = msgraph_module.get_valid_access_token_for_plugins
    original_request = msgraph_module.requests.request

    responses = [
        FakeResponse(200, {"value": [{"id": "1"}, {"id": "2"}], "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?page=2"}),
        FakeResponse(200, {"value": [{"id": "3"}, {"id": "4"}]})
    ]
    request_log = []

    def fake_token_helper(scopes=None):
        return {"access_token": "fake-token", "scopes": scopes}

    def fake_request(method, url, headers=None, params=None, json=None, timeout=None):
        request_log.append({
            "method": method,
            "url": url,
            "headers": headers,
            "params": params,
            "timeout": timeout,
        })
        return responses.pop(0)

    try:
        msgraph_module.get_valid_access_token_for_plugins = fake_token_helper
        msgraph_module.requests.request = fake_request

        result = plugin.get_my_messages(top=3)

        if result.get("count") != 3:
            print(f"Expected 3 messages after pagination, got: {result}")
            return False
        if len(result.get("value", [])) != 3:
            print(f"Expected truncated message list of length 3, got: {result.get('value', [])}")
            return False
        if not result.get("truncated"):
            print(f"Expected truncated=True when additional page data remains, got: {result}")
            return False
        if len(request_log) != 2:
            print(f"Expected 2 Graph requests, got {len(request_log)}")
            return False

        print("Microsoft Graph helper paginates and truncates list results safely")
        return True
    finally:
        msgraph_module.get_valid_access_token_for_plugins = original_token_helper
        msgraph_module.requests.request = original_request


def test_msgraph_plugin_marks_messages_as_read() -> bool:
    """Verify the plugin issues a PATCH request with Mail.ReadWrite and isRead."""
    print("Testing Microsoft Graph message read-state updates...")

    plugin = MSGraphPlugin({"name": "msgraph_plugin"})
    original_token_helper = msgraph_module.get_valid_access_token_for_plugins
    original_request = msgraph_module.requests.request

    request_log = []

    def fake_token_helper(scopes=None):
        request_log.append({"scopes": scopes})
        return {"access_token": "fake-token", "scopes": scopes}

    def fake_request(method, url, headers=None, params=None, json=None, timeout=None):
        request_log.append({
            "method": method,
            "url": url,
            "headers": headers,
            "params": params,
            "json": json,
            "timeout": timeout,
        })
        return FakeResponse(200, {"id": "message-123", "isRead": True})

    try:
        msgraph_module.get_valid_access_token_for_plugins = fake_token_helper
        msgraph_module.requests.request = fake_request

        result = plugin.mark_message_as_read("message-123")

        if result.get("id") != "message-123" or result.get("isRead") is not True:
            print(f"Expected updated message payload, got: {result}")
            return False
        if request_log[0].get("scopes") != ["Mail.ReadWrite"]:
            print(f"Expected Mail.ReadWrite scope, got: {request_log[0]}")
            return False
        if request_log[1].get("method") != "PATCH":
            print(f"Expected PATCH request, got: {request_log[1]}")
            return False
        if not str(request_log[1].get("url", "")).endswith("/v1.0/me/messages/message-123"):
            print(f"Expected message update URL, got: {request_log[1]}")
            return False
        if request_log[1].get("json") != {"isRead": True}:
            print(f"Expected isRead payload, got: {request_log[1]}")
            return False

        invalid_result = plugin.mark_message_as_read("", is_read=True)
        if invalid_result.get("error") != "invalid_parameters":
            print(f"Expected invalid_parameters for empty message id, got: {invalid_result}")
            return False

        print("Microsoft Graph plugin issues the expected message read-state PATCH request")
        return True
    finally:
        msgraph_module.get_valid_access_token_for_plugins = original_token_helper
        msgraph_module.requests.request = original_request


def test_msgraph_plugin_reads_mailbox_timezone() -> bool:
    """Verify the plugin can read mailbox timezone settings for the signed-in user."""
    print("Testing Microsoft Graph mailbox timezone lookup...")

    plugin = MSGraphPlugin({"name": "msgraph_plugin"})
    original_token_helper = msgraph_module.get_valid_access_token_for_plugins
    original_request = msgraph_module.requests.request

    request_log = []

    def fake_token_helper(scopes=None):
        request_log.append({"scopes": scopes})
        return {"access_token": "fake-token", "scopes": scopes}

    def fake_request(method, url, headers=None, params=None, json=None, timeout=None):
        request_log.append({
            "method": method,
            "url": url,
            "headers": headers,
            "params": params,
            "timeout": timeout,
        })
        return FakeResponse(
            200,
            {
                "timeZone": "Pacific Standard Time",
                "dateFormat": "M/d/yyyy",
                "timeFormat": "h:mm tt",
                "language": {"locale": "en-US", "displayName": "English (United States)"},
                "workingHours": {"timeZone": {"name": "Pacific Standard Time"}},
            },
        )

    try:
        msgraph_module.get_valid_access_token_for_plugins = fake_token_helper
        msgraph_module.requests.request = fake_request

        result = plugin.get_my_timezone()
        if result.get("time_zone") != "Pacific Standard Time":
            print(f"Expected Pacific Standard Time, got: {result}")
            return False
        if result.get("time_format") != "h:mm tt":
            print(f"Expected mailbox time format in result, got: {result}")
            return False
        if request_log[0].get("scopes") != ["MailboxSettings.Read"]:
            print(f"Expected MailboxSettings.Read scope, got: {request_log[0]}")
            return False
        if not str(request_log[1].get("url", "")).endswith("/v1.0/me/mailboxSettings"):
            print(f"Expected mailboxSettings request URL, got: {request_log[1]}")
            return False

        print("Microsoft Graph plugin reads mailbox timezone settings safely")
        return True
    finally:
        msgraph_module.get_valid_access_token_for_plugins = original_token_helper
        msgraph_module.requests.request = original_request


def test_msgraph_plugin_creates_teams_calendar_invites_with_group_attendees() -> bool:
    """Verify calendar invites can include group members and become Teams meetings."""
    print("Testing Microsoft Graph Teams invite creation with group attendees...")

    plugin = MSGraphPlugin({"name": "msgraph_plugin"})
    original_token_helper = msgraph_module.get_valid_access_token_for_plugins
    original_request = msgraph_module.requests.request
    original_current_user_info = msgraph_module.get_current_user_info
    original_assert_group_role = msgraph_module.assert_group_role
    original_find_group_by_id = msgraph_module.find_group_by_id

    request_log = []

    def fake_token_helper(scopes=None):
        request_log.append({"scopes": scopes})
        return {"access_token": "fake-token", "scopes": scopes}

    def fake_request(method, url, headers=None, params=None, json=None, timeout=None):
        request_log.append({
            "method": method,
            "url": url,
            "headers": headers,
            "params": params,
            "json": json,
            "timeout": timeout,
        })
        return FakeResponse(
            201,
            {
                "id": "event-123",
                "subject": json.get("subject"),
                "isOnlineMeeting": json.get("isOnlineMeeting", False),
                "onlineMeeting": {"joinUrl": "https://teams.example.test/join"},
                "attendees": json.get("attendees", []),
            },
        )

    try:
        msgraph_module.get_valid_access_token_for_plugins = fake_token_helper
        msgraph_module.requests.request = fake_request
        msgraph_module.get_current_user_info = lambda: {
            "userId": "user-1",
            "email": "owner@example.com",
            "displayName": "Owner User",
        }
        msgraph_module.assert_group_role = lambda *args, **kwargs: "Owner"
        msgraph_module.find_group_by_id = lambda group_id: {
            "id": group_id,
            "owner": {
                "id": "user-1",
                "email": "owner@example.com",
                "displayName": "Owner User",
            },
            "users": [
                {"userId": "user-1", "email": "owner@example.com", "displayName": "Owner User"},
                {"userId": "user-2", "email": "project@example.com", "displayName": "Project Member"},
                {"userId": "user-3", "email": "shared@example.com", "displayName": "Shared Person"},
            ],
        }

        result = plugin.create_calendar_invite(
            subject="Team Sync",
            start_datetime="2025-05-01T09:00:00",
            end_datetime="2025-05-01T09:30:00",
            attendee_emails="guest@example.com; shared@example.com",
            include_group_members=True,
            group_id="group-123",
            make_teams_meeting=True,
            timezone="Pacific Standard Time",
        )

        if result.get("id") != "event-123":
            print(f"Expected created event id, got: {result}")
            return False
        if result.get("join_url") != "https://teams.example.test/join":
            print(f"Expected Teams join URL, got: {result}")
            return False
        if result.get("group_id") != "group-123":
            print(f"Expected resolved group id, got: {result}")
            return False
        if result.get("requested_attendee_count") != 3:
            print(f"Expected 3 total attendees after dedupe, got: {result}")
            return False
        if result.get("included_group_member_count") != 1:
            print(f"Expected exactly 1 new attendee from the group, got: {result}")
            return False
        if request_log[0].get("scopes") != ["Calendars.ReadWrite"]:
            print(f"Expected Calendars.ReadWrite scope, got: {request_log[0]}")
            return False
        if request_log[1].get("method") != "POST":
            print(f"Expected POST request, got: {request_log[1]}")
            return False
        if not str(request_log[1].get("url", "")).endswith("/v1.0/me/events"):
            print(f"Expected event creation URL, got: {request_log[1]}")
            return False

        payload = request_log[1].get("json") or {}
        attendee_addresses = sorted(
            attendee.get("emailAddress", {}).get("address")
            for attendee in payload.get("attendees", [])
        )
        if attendee_addresses != ["guest@example.com", "project@example.com", "shared@example.com"]:
            print(f"Unexpected attendee payload: {payload}")
            return False
        if payload.get("isOnlineMeeting") is not True or payload.get("onlineMeetingProvider") != "teamsForBusiness":
            print(f"Expected Teams meeting payload, got: {payload}")
            return False

        print("Microsoft Graph plugin creates Teams invites with deduped group attendees")
        return True
    finally:
        msgraph_module.get_valid_access_token_for_plugins = original_token_helper
        msgraph_module.requests.request = original_request
        msgraph_module.get_current_user_info = original_current_user_info
        msgraph_module.assert_group_role = original_assert_group_role
        msgraph_module.find_group_by_id = original_find_group_by_id


def test_msgraph_plugin_surfaces_token_consent_errors() -> bool:
    """Verify token acquisition failures are returned as structured plugin errors."""
    print("Testing Microsoft Graph token consent error handling...")

    plugin = MSGraphPlugin({"name": "msgraph_plugin"})
    original_token_helper = msgraph_module.get_valid_access_token_for_plugins
    original_request = msgraph_module.requests.request

    def fake_token_helper(scopes=None):
        return {
            "error": "consent_required",
            "message": "Consent is required.",
            "consent_url": "https://example.test/consent",
            "scopes": scopes,
        }

    def fail_if_called(*args, **kwargs):
        raise AssertionError("requests.request should not be called when token acquisition fails")

    try:
        msgraph_module.get_valid_access_token_for_plugins = fake_token_helper
        msgraph_module.requests.request = fail_if_called

        result = plugin.search_users("Ada")
        if result.get("error") != "consent_required":
            print(f"Expected consent_required result, got: {result}")
            return False
        if result.get("operation") != "search_users":
            print(f"Expected operation name in token error result, got: {result}")
            return False

        print("Microsoft Graph plugin surfaces consent requirements safely")
        return True
    finally:
        msgraph_module.get_valid_access_token_for_plugins = original_token_helper
        msgraph_module.requests.request = original_request


if __name__ == "__main__":
    tests = [
        test_msgraph_plugin_exposes_expected_operations,
        test_msgraph_plugin_paginates_and_truncates_list_results,
        test_msgraph_plugin_marks_messages_as_read,
        test_msgraph_plugin_reads_mailbox_timezone,
        test_msgraph_plugin_creates_teams_calendar_invites_with_group_attendees,
        test_msgraph_plugin_surfaces_token_consent_errors,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(tests)} tests passed")
    sys.exit(0 if success else 1)