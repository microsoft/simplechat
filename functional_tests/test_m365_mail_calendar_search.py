# test_m365_mail_calendar_search.py
#!/usr/bin/env python3
"""
Functional tests for searching Microsoft 365 mail and calendar history.
Version: 0.261.129
Implemented in: 0.261.129

These tests run the real Graph plugin and transport with scripted Graph
responses. They check that Read my mail and Read my calendar events reach
older items through date ranges, keyword search, and exact continuation,
and that each result reports honestly whether its range was fully read.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The shared M365 provider fixtures live in the provider core suite.
from test_m365_provider_core import FakeResponse, execution, graph_plugins  # noqa: E402,F401
from functions_m365_transport import M365CloudConfig, M365Transport  # noqa: E402


GRAPH_CLOUD = M365CloudConfig("https://graph.microsoft.com/v1.0", "https://login.microsoftonline.com/tenant")
MESSAGES_PAGE_2 = "https://graph.microsoft.com/v1.0/me/messages?page=2"


def scripted_plugin(modules, source, pages):
    calls = []

    def request(method, url, **kwargs):
        calls.append({
            "url": url,
            "params": dict(kwargs.get("params") or {}),
            "headers": dict(kwargs.get("headers") or {}),
        })
        return FakeResponse(pages.pop(0))

    plugin = modules["msgraph_plugin"].MSGraphPlugin({"id": "legacy"})
    plugin._transports[source] = M365Transport(
        source, "legacy", cloud=GRAPH_CLOUD,
        request=Mock(side_effect=request),
        token_provider=Mock(return_value={"access_token": "unit-test-token"}),
    )
    return plugin, calls


def message(message_id, received, is_read=False):
    return {"id": message_id, "subject": f"Subject {message_id}", "receivedDateTime": received, "isRead": is_read}


def event(event_id, start, end, **fields):
    return {
        "id": event_id,
        "subject": fields.pop("subject", f"Event {event_id}"),
        "start": {"dateTime": f"{start}.0000000", "timeZone": "UTC"},
        "end": {"dateTime": f"{end}.0000000", "timeZone": "UTC"},
        **fields,
    }


def ids(result):
    return [item["id"] for item in result["value"]]


def test_mail_date_range_reaches_older_mail_and_continues_exactly(graph_plugins):
    modules, _ = graph_plugins
    plugin, calls = scripted_plugin(modules, "email", [
        {"value": [
            message("m1", "2025-01-20T10:00:00Z"),
            message("m2", "2025-01-15T09:00:00Z"),
            message("m3", "2025-01-10T08:00:00Z"),
        ]},
        {"value": [message("m3", "2025-01-10T08:00:00Z")]},
    ])

    first = plugin.get_my_messages(top=2, received_from="2025-01-01", received_to="2025-01-31")

    assert calls[0]["url"].endswith("/v1.0/me/mailFolders/inbox/messages")
    assert calls[0]["params"]["$filter"] == (
        "receivedDateTime ge 2025-01-01T00:00:00Z and receivedDateTime lt 2025-02-01T00:00:00Z"
    )
    assert calls[0]["params"]["$orderby"] == "receivedDateTime desc"
    assert calls[0]["params"]["$top"] == 3
    assert "$search" not in calls[0]["params"]
    assert ids(first) == ["m1", "m2"] and first["count"] == 2 and first["truncated"] is True
    coverage = first["coverage"]
    assert coverage["complete"] is False
    assert coverage["newest_received"] == "2025-01-20T10:00:00Z"
    assert coverage["oldest_received"] == "2025-01-15T09:00:00Z"
    assert coverage["continue_with"] == {
        "folder": "inbox", "top": 2,
        "received_from": "2025-01-01T00:00:00Z", "received_to": "2025-01-10T08:00:01Z",
    }
    assert "continue_with" in first["note"]

    second = plugin.get_my_messages(**coverage["continue_with"])

    assert calls[1]["params"]["$filter"] == (
        "receivedDateTime ge 2025-01-01T00:00:00Z and receivedDateTime lt 2025-01-10T08:00:01Z"
    )
    assert ids(second) == ["m3"]
    assert second["coverage"]["complete"] is True and second["truncated"] is False
    assert "continue_with" not in second["coverage"]


def test_mail_unread_filter_leads_with_the_received_date(graph_plugins):
    modules, _ = graph_plugins
    plugin, calls = scripted_plugin(modules, "email", [
        {"value": [message("u1", "2025-02-01T10:00:00Z")]},
        {"value": []},
    ])

    unread = plugin.get_my_messages(unread_only=True)
    plain = plugin.get_my_messages(unread_only="false")
    invalid = plugin.get_my_messages(unread_only="sometimes")

    assert calls[0]["params"]["$filter"] == "receivedDateTime ge 1900-01-01T00:00:00Z and isRead eq false"
    assert calls[0]["params"]["$orderby"] == "receivedDateTime desc"
    assert ids(unread) == ["u1"] and unread["coverage"]["complete"] is True
    assert "$filter" not in calls[1]["params"]
    assert plain["count"] == 0 and plain["note"] == "No messages match this request."
    assert invalid["error"] == "invalid_parameters" and len(calls) == 2


def test_mail_search_sends_only_literal_words_and_applies_exact_bounds(graph_plugins):
    modules, _ = graph_plugins
    plugin, calls = scripted_plugin(modules, "email", [{"value": [
        message("after-range", "2024-04-01T05:00:00Z"),
        message("inside", "2024-03-20T12:00:00Z"),
        message("first-instant", "2024-03-01T00:00:00Z"),
        message("before-range", "2024-02-29T23:00:00Z"),
    ]}])

    result = plugin.get_my_messages(
        search='from:alice subject:"Budget" OR review AND (2024)',
        received_from="2024-03-01", received_to="2024-03-31", folder="all",
    )

    params = calls[0]["params"]
    assert calls[0]["url"].endswith("/v1.0/me/messages")
    assert params["$search"] == (
        '"alice AND budget AND review AND 2024 AND received>=2024-02-29 AND received<=2024-04-02"'
    )
    assert "$filter" not in params and "$orderby" not in params
    assert params["$top"] == 100
    assert "bodyPreview" in params["$select"] and "receivedDateTime" in params["$select"]
    assert "ConsistencyLevel" not in calls[0]["headers"]
    assert ids(result) == ["inside", "first-instant"]
    assert result["coverage"]["search_terms"] == ["alice", "budget", "review", "2024"]
    assert result["coverage"]["folder"] == "all" and result["coverage"]["complete"] is True


def test_mail_search_budget_continues_from_the_last_examined_message(graph_plugins, monkeypatch):
    modules, _ = graph_plugins
    plugin, calls = scripted_plugin(modules, "email", [
        {"value": [
            message("above-range", "2024-04-01T03:00:00Z"),
            message("k1", "2024-03-25T10:00:00Z"),
        ], "@odata.nextLink": MESSAGES_PAGE_2},
        {"value": [message("k2", "2024-03-20T10:00:00Z")], "@odata.nextLink": MESSAGES_PAGE_2},
    ])
    monkeypatch.setattr(plugin, "MAIL_SEARCH_MAX_PAGES", 2)

    result = plugin.get_my_messages(
        top=2, search="budget", folder="all", received_from="2024-03-01", received_to="2024-03-31",
    )

    assert len(calls) == 2 and calls[1]["params"] == {}
    assert ids(result) == ["k1"]
    assert result["coverage"]["complete"] is False
    assert result["coverage"]["continue_with"] == {
        "folder": "all", "top": 2, "search": "budget",
        "received_from": "2024-03-01T00:00:00Z", "received_to": "2024-03-20T10:00:01Z",
    }


def test_mail_continuation_returns_boundary_ties_exactly_once(graph_plugins):
    modules, _ = graph_plugins
    plugin, calls = scripted_plugin(modules, "email", [
        {"value": [
            message("a", "2025-03-01T10:00:00Z"),
            message("b", "2025-03-01T09:00:00Z"),
            message("c", "2025-03-01T09:00:00Z"),
        ]},
        {"value": [message("b", "2025-03-01T09:00:00Z"), message("c", "2025-03-01T09:00:00Z")]},
        {"value": [message("x", "2025-03-02T08:00:00Z"), message("y", "2025-03-02T08:00:00Z")]},
    ])

    first = plugin.get_my_messages(top=2)
    second = plugin.get_my_messages(**first["coverage"]["continue_with"])
    whole_page_tie = plugin.get_my_messages(top=1)

    assert ids(first) == ["a"]
    assert first["coverage"]["continue_with"]["received_to"] == "2025-03-01T09:00:01Z"
    assert "may be missing" not in first["note"]
    assert calls[1]["params"]["$filter"] == "receivedDateTime lt 2025-03-01T09:00:01Z"
    assert ids(second) == ["b", "c"] and second["coverage"]["complete"] is True
    assert ids(whole_page_tie) == ["x"]
    assert whole_page_tie["coverage"]["continue_with"]["received_to"] == "2025-03-02T08:00:00Z"
    assert "Some messages received at 2025-03-02T08:00:00Z may be missing" in whole_page_tie["note"]
    assert "Raise top" in whole_page_tie["note"]


def test_mail_tie_at_received_from_is_not_reported_complete(graph_plugins, monkeypatch):
    modules, _ = graph_plugins
    plugin, _ = scripted_plugin(modules, "email", [{
        "value": [message("x", "2025-03-01T08:00:00Z"), message("y", "2025-03-01T08:00:00Z", is_read=True)],
        "@odata.nextLink": MESSAGES_PAGE_2,
    }])
    monkeypatch.setattr(plugin, "MAIL_SEARCH_MAX_PAGES", 1)

    result = plugin.get_my_messages(
        top=1, folder="all", search="budget", unread_only=True, received_from="2025-03-01T08:00:00Z",
    )

    # Unread mail from that same second may sit past the scan budget, so the range isn't complete.
    assert ids(result) == ["x"]
    assert result["coverage"]["complete"] is False
    assert "continue_with" not in result["coverage"]
    assert "Some messages received at 2025-03-01T08:00:00Z may be missing" in result["note"]
    assert "Narrow the request" not in result["note"]


def test_mail_rejects_unusable_search_and_dates_before_remote_access(graph_plugins):
    modules, _ = graph_plugins
    plugin, calls = scripted_plugin(modules, "email", [])
    eleven_words = " ".join(f"word{index}" for index in range(11))
    results = [
        plugin.get_my_messages(search="AND OR NOT"),
        plugin.get_my_messages(search=eleven_words),
        plugin.get_my_messages(search="budget\x00"),
        plugin.get_my_messages(search="x" * 501),
        plugin.get_my_messages(received_from="last spring"),
        plugin.get_my_messages(received_from="1850-01-01"),
        plugin.get_my_messages(received_from="2025-03-01", received_to="2025-02-01"),
    ]

    assert all(result["error"] == "invalid_parameters" for result in results)
    assert "at least one word" in results[0]["message"]
    assert "at most 10 words" in results[1]["message"]
    assert "earlier than received_to" in results[6]["message"]
    assert calls == []


def test_mail_provider_errors_pass_through_without_coverage(graph_plugins):
    modules, _ = graph_plugins
    plugin = modules["msgraph_plugin"].MSGraphPlugin({"id": "legacy"})
    plugin._transports["email"] = M365Transport(
        "email", "legacy", cloud=GRAPH_CLOUD,
        request=Mock(return_value=FakeResponse(
            {"error": {"code": "ErrorInvalidRestriction", "message": "Too complex."}}, status=400,
        )),
        token_provider=Mock(return_value={"access_token": "unit-test-token"}),
    )

    result = plugin.get_my_messages(received_from="2025-01-01")

    assert result.get("error") and "coverage" not in result and "note" not in result


def test_calendar_without_a_range_reads_the_next_30_days(graph_plugins, monkeypatch):
    modules, _ = graph_plugins
    module = modules["msgraph_plugin"]

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 5, 6, 12, 30, 15, 123456, tzinfo=timezone.utc)

    monkeypatch.setattr(module, "datetime", FixedDatetime)
    plugin, calls = scripted_plugin(modules, "calendar", [{"value": [
        event("soon", "2026-05-07T09:00:00", "2026-05-07T09:30:00"),
    ]}])

    result = plugin.get_my_events()

    params = calls[0]["params"]
    assert calls[0]["url"].endswith("/v1.0/me/calendarView")
    assert params["startDateTime"] == "2026-05-06T12:30:15Z"
    assert params["endDateTime"] == "2026-06-05T12:30:15Z"
    assert params["$orderby"] == "start/dateTime" and params["$top"] == 6
    assert ids(result) == ["soon"] and result["coverage"]["complete"] is True
    assert "No time range was given" in result["note"]


def test_calendar_query_matches_every_word_and_hides_scan_fields(graph_plugins):
    modules, _ = graph_plugins
    plugin, calls = scripted_plugin(modules, "calendar", [{"value": [
        event(
            "review", "2024-02-01T15:00:00", "2024-02-01T16:00:00", subject="Roadmap review",
            attendees=[{"emailAddress": {"name": "Pat", "address": "pat@contoso.com"}}],
            bodyPreview="", categories=[],
        ),
        event("lunch", "2024-03-01T12:00:00", "2024-03-01T13:00:00", subject="Lunch", attendees=[], bodyPreview=""),
        event(
            "planning", "2024-06-01T09:00:00", "2024-06-01T10:00:00", subject="Planning",
            attendees=[], bodyPreview="Contoso roadmap planning", categories=["Blue"],
        ),
    ]}])

    result = plugin.get_my_events(start_datetime="2024-01-01", end_datetime="2024-12-31", query="Contoso roadmap")

    params = calls[0]["params"]
    assert params["startDateTime"] == "2024-01-01T00:00:00Z"
    assert params["endDateTime"] == "2025-01-01T00:00:00Z"
    assert params["$top"] == 100
    for field in ("attendees", "bodyPreview", "categories"):
        assert field in params["$select"]
    assert ids(result) == ["review", "planning"]
    assert result["value"][0]["matched_on"] == ["attendees", "subject"]
    assert result["value"][1]["matched_on"] == ["description"]
    for item in result["value"]:
        assert not {"attendees", "bodyPreview", "categories"} & set(item)
        assert {"subject", "start", "end"} <= set(item)
    assert result["coverage"]["query_terms"] == ["contoso", "roadmap"]
    assert result["coverage"]["events_scanned"] == 3 and result["coverage"]["complete"] is True


def test_calendar_newest_first_continues_backward_without_repeats(graph_plugins):
    modules, _ = graph_plugins
    plugin, calls = scripted_plugin(modules, "calendar", [
        {"value": [
            event("e", "2024-01-20T09:00:00", "2024-01-20T10:00:00"),
            event("d", "2024-01-15T09:00:00", "2024-01-15T10:00:00"),
            event("c", "2024-01-10T09:00:00", "2024-01-10T10:00:00"),
        ]},
        {"value": [event("c", "2024-01-10T09:00:00", "2024-01-10T10:00:00")]},
    ])

    first = plugin.get_my_events(
        start_datetime="2024-01-01T00:00:00Z", end_datetime="2024-02-01T00:00:00Z", order="newest_first", top=2,
    )
    second = plugin.get_my_events(**first["coverage"]["continue_with"])

    assert calls[0]["params"]["$orderby"] == "start/dateTime desc" and calls[0]["params"]["$top"] == 3
    assert ids(first) == ["e", "d"]
    assert first["coverage"]["continue_with"] == {
        "top": 2, "order": "newest_first",
        "start_datetime": "2024-01-01T00:00:00Z", "end_datetime": "2024-01-10T09:00:01Z",
        "starts_in_range": False,
    }
    assert calls[1]["params"]["endDateTime"] == "2024-01-10T09:00:01Z"
    assert ids(second) == ["c"] and second["coverage"]["complete"] is True


def test_calendar_oldest_first_continuation_leaves_out_events_still_running(graph_plugins):
    modules, _ = graph_plugins
    conference = event("conference", "2024-02-28T00:00:00", "2024-03-03T00:00:00")
    standup = event("standup", "2024-03-01T09:00:00", "2024-03-01T11:00:00")
    plugin, calls = scripted_plugin(modules, "calendar", [
        {"value": [conference, standup, event("review", "2024-03-01T10:00:00", "2024-03-01T10:30:00")]},
        {"value": [
            conference, standup,
            event("review", "2024-03-01T10:00:00", "2024-03-01T10:30:00"),
            event("retro", "2024-03-01T15:00:00", "2024-03-01T16:00:00"),
        ]},
    ])

    first = plugin.get_my_events(start_datetime="2024-03-01", end_datetime="2024-03-01", top=2)
    continue_with = first["coverage"]["continue_with"]
    second = plugin.get_my_events(**continue_with)

    assert ids(first) == ["conference", "standup"]
    assert continue_with == {
        "top": 2, "order": "oldest_first",
        "start_datetime": "2024-03-01T10:00:00Z", "end_datetime": "2024-03-02T00:00:00Z",
        "starts_in_range": True,
    }
    assert calls[1]["params"]["$top"] == 100
    assert ids(second) == ["review", "retro"] and second["coverage"]["complete"] is True


def test_calendar_reports_in_progress_events_that_overflow_the_page(graph_plugins):
    modules, _ = graph_plugins
    plugin, _ = scripted_plugin(modules, "calendar", [{"value": [
        event("trip", "2024-02-27T00:00:00", "2024-03-05T00:00:00"),
        event("leave", "2024-02-28T00:00:00", "2024-03-04T00:00:00"),
    ]}])

    result = plugin.get_my_events(start_datetime="2024-03-01", end_datetime="2024-03-01", top=1)

    assert ids(result) == ["trip"] and result["coverage"]["complete"] is False
    assert result["coverage"]["continue_with"]["start_datetime"] == "2024-03-01T00:00:00Z"
    assert result["coverage"]["continue_with"]["starts_in_range"] is True
    assert "Raise top" in result["note"]


def test_calendar_ties_on_a_range_boundary_are_not_reported_complete(graph_plugins):
    modules, _ = graph_plugins
    plugin, calls = scripted_plugin(modules, "calendar", [
        {"value": [
            event("a", "2024-03-01T09:00:00", "2024-03-01T10:00:00"),
            event("b", "2024-03-01T09:00:00", "2024-03-01T09:30:00"),
        ]},
        {"value": [
            event("c", "2024-03-01T09:00:00", "2024-03-01T10:00:00"),
            event("d", "2024-03-01T09:00:00", "2024-03-01T09:30:00"),
            event("early", "2024-03-01T08:00:00", "2024-03-01T11:00:00"),
        ]},
        {"value": [
            event("e", "2024-03-01T09:00:00", "2024-03-01T10:00:00"),
            event("f", "2024-03-01T09:00:00", "2024-03-01T09:30:00"),
        ]},
    ])

    at_window_end = plugin.get_my_events(
        start_datetime="2024-03-01T00:00:00Z", end_datetime="2024-03-01T09:00:01Z", top=1,
    )
    at_window_start = plugin.get_my_events(
        start_datetime="2024-03-01T09:00:00Z", end_datetime="2024-03-02T00:00:00Z",
        order="newest_first", starts_in_range=True, top=1,
    )
    mid_window = plugin.get_my_events(start_datetime="2024-03-01", end_datetime="2024-03-01", top=1)

    for result in (at_window_end, at_window_start):
        assert result["coverage"]["complete"] is False
        assert "continue_with" not in result["coverage"]
        assert "Some events that start at 2024-03-01T09:00:00Z may be missing" in result["note"]
        assert "Narrow the time range" not in result["note"]
    assert ids(at_window_end) == ["a"] and ids(at_window_start) == ["c"]
    assert calls[1]["params"]["$top"] == 100
    # Mid-window, paging still moves past the shared start time and says what it may have skipped.
    assert ids(mid_window) == ["e"]
    assert mid_window["coverage"]["continue_with"]["start_datetime"] == "2024-03-01T09:00:01Z"
    assert "may be missing" in mid_window["note"]


def test_calendar_rejects_invalid_ranges_and_order_before_remote_access(graph_plugins):
    modules, _ = graph_plugins
    plugin, calls = scripted_plugin(modules, "calendar", [])
    results = [
        plugin.get_my_events(order="sideways"),
        plugin.get_my_events(start_datetime="2024-01-01"),
        plugin.get_my_events(start_datetime="2024-02-01", end_datetime="2024-01-01"),
        plugin.get_my_events(start_datetime="soon", end_datetime="later"),
        plugin.get_my_events(starts_in_range="perhaps"),
        plugin.get_my_events(query="NOT AND"),
    ]

    assert all(result["error"] == "invalid_parameters" for result in results)
    assert results[1]["message"].startswith("Both start_datetime and end_datetime are required")
    assert "earlier than end_datetime" in results[2]["message"]
    assert calls == []


def test_kernel_functions_describe_search_parameters_to_the_model(graph_plugins):
    from semantic_kernel.functions.kernel_plugin import KernelPlugin

    modules, _ = graph_plugins
    plugin = modules["msgraph_plugin"].MSGraphPlugin({"id": "legacy"})
    kernel_plugin = KernelPlugin.from_object(
        "msgraph", {"get_my_messages": plugin.get_my_messages, "get_my_events": plugin.get_my_events},
    )
    expected = {
        "get_my_messages": {"top", "folder", "unread_only", "select_fields", "search", "received_from", "received_to"},
        "get_my_events": {"top", "start_datetime", "end_datetime", "select_fields", "query", "order", "starts_in_range"},
    }

    for function_name, parameter_names in expected.items():
        function = kernel_plugin[function_name]
        described = {parameter.name: parameter.description for parameter in function.parameters}
        assert set(described) == parameter_names
        assert all(described[name] for name in parameter_names)
        assert all(not parameter.is_required for parameter in function.parameters)
        assert "coverage.continue_with" in function.description
        assert "recent" not in function.description.lower() and "upcoming" not in function.description.lower()


def test_parsed_graph_times_normalize_to_utc_seconds(graph_plugins):
    modules, _ = graph_plugins
    plugin = modules["msgraph_plugin"].MSGraphPlugin({"id": "legacy"})

    parsed = plugin._parse_graph_datetime({"dateTime": "2024-03-01T09:15:30.1234567", "timeZone": "UTC"})
    offset, _ = plugin._parse_time_bound("2024-03-01T09:15:30-05:00", "received_from", "get_my_messages")
    day_end, _ = plugin._parse_time_bound("2024-03-01", "received_to", "get_my_messages", end_of_day=True)

    assert parsed == datetime(2024, 3, 1, 9, 15, 30, 123456, tzinfo=timezone.utc)
    assert plugin._format_graph_datetime(offset) == "2024-03-01T14:15:30Z"
    assert day_end - timedelta(days=1) == datetime(2024, 3, 1, tzinfo=timezone.utc)
    assert plugin._parse_graph_datetime("not a date") is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
