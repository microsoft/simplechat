#!/usr/bin/env python3
# test_notifications_status_and_search_filters.py
"""
Functional test for the notification list's server-side read filter and search.
Version: 0.261.448
Implemented in: 0.261.448

The V2 Notifications page filters by All, Unread and Read and searches the list. Classic does
both on the page it has fetched, so its totals and its paging describe the unfiltered list.
GET /api/notifications now takes `status` and `q` and applies them before it pages, so `total`
and `has_more` describe the filtered list.

The real get_user_notifications runs over an in-memory notifications container, and the real
route body runs on a closed Flask app, so no live application, credentials or services are
used. The checks cover: each filter and the search on their own and together; totals and
`has_more` page by page; dismissed notifications staying out; the search reading the title and
the message the reader is shown, including a reason added to the message, and never what a
team alert hides from a group member; blank and over-long search text; a bad `status` being
refused before anything is read; and the classic request, which sends neither parameter,
being answered as it always was.
"""

import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import Mock, patch

import pytest
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


ROUTES = APP / "route_backend_notifications.py"
ROUTE_PATH = "/api/notifications"
READER = "reader-1"
OWNER = "owner-9"
GROUP_ID = "group-7"
BASE_TIME = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
MEMBERSHIPS = {READER: [GROUP_ID], OWNER: [GROUP_ID]}


def stamp(minutes):
    """A created_at that sorts after every smaller number of minutes."""
    return (BASE_TIME + timedelta(minutes=minutes)).isoformat()


def notice(notice_id, title, message="", *, minutes, read=False, dismissed=False, user_id=READER, **extra):
    """A personal notification document as create_notification stores it."""
    record = {
        "id": notice_id,
        "user_id": user_id,
        "group_id": None,
        "public_workspace_id": None,
        "scope": "personal",
        "notification_type": "system_announcement",
        "title": title,
        "message": message,
        "created_at": stamp(minutes),
        "read_by": [user_id] if read else [],
        "dismissed_by": [user_id] if dismissed else [],
        "link_url": "",
        "link_context": {},
        "metadata": {},
        "assignment": None,
    }
    record.update(extra)
    return record


def team_alert():
    """A team workflow alert whose owner is OWNER: members of the group read a reduced copy."""
    return notice(
        "team-alert", "Customer list exported to SECRET-PARTNER",
        "The run read the private HR folder and found 4 records", minutes=70,
        user_id=None, group_id=GROUP_ID, scope="group", notification_type="workflow_priority_alert",
        metadata={
            "priority": "high", "category": "failure", "delivery": "popup", "audience": "group",
            "owner_user_id": OWNER, "workflow_id": "wf-2", "workflow_name": "Nightly scan",
            "workflow_scope": "group", "workflow_group_id": GROUP_ID, "run_id": "run-9", "status": "failed",
            "matched_rules": [
                {"rule_id": "r1", "rule_name": "Run failed", "severity": "high",
                 "condition_type": "run_status", "reason": "Workflow run failed"},
                {"rule_id": "r2", "rule_name": "Leak found", "severity": "medium",
                 "condition_type": "model_evaluation", "reason": "The output names SECRET-PARTNER"},
            ],
            "response_preview": "SECRET-PARTNER received 4 HR records",
            "alert_summary": "4 HR records went to SECRET-PARTNER",
            "link_targets": [],
        },
    )


def paging_documents():
    """25 notifications, Item 00 oldest. Every fifth, Items 00, 05, 10, 15 and 20, is read."""
    return [
        notice(f"item-{number:02d}", f"Item {number:02d}", f"Batch {number // 10}", minutes=number,
               read=number % 5 == 0)
        for number in range(25)
    ]


def mixed_documents():
    """A small inbox where the filters and the search each have something to tell apart."""
    return [
        notice("quarterly", "Quarterly LEDGER review is ready", "Finance shared the numbers.",
               minutes=60),
        notice("workbook", "Budget workbook processed", "Your ledger export finished with 12 chunks.",
               minutes=59, read=True),
        notice("strasse", "Straße closure notice", "Maintenance on Saturday.", minutes=58),
        notice("contract", "Reminder", "Contract signed.", minutes=57, read=True),
        notice("dismissed", "Dismissed ledger notice", "Nobody wants to see this.", minutes=56,
               dismissed=True),
        notice("denied", "Request Denied", "Your request was denied.", minutes=55,
               notification_type="approval_request_denied",
               metadata={"comment": "Missing purchase order"}),
        notice("group-note", "Design folder updated", "A teammate added a ledger template.", minutes=54,
               user_id=None, group_id=GROUP_ID, scope="group"),
        notice("someone-elses", "Ledger for someone else", "Private to another user.", minutes=53,
               user_id="someone-else"),
    ]


class FakeNotificationsContainer:
    """An in-memory notifications container that answers the four reads the list makes."""

    def __init__(self, documents):
        self.documents = [deepcopy(document) for document in documents]
        self.queries = []

    def query_items(self, query, parameters=None, partition_key=None, enable_cross_partition_query=False,
                    **kwargs):
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        self.queries.append({"query": query, "parameters": values})
        if "c.scope = 'assignment'" in query:
            matches = [document for document in self.documents if document.get("scope") == "assignment"]
        elif "@user_id" in values:
            matches = [document for document in self.documents if document.get("user_id") == values["@user_id"]]
        elif "@group_id" in values:
            matches = [document for document in self.documents if document.get("group_id") == values["@group_id"]]
        elif "@workspace_id" in values:
            matches = [
                document for document in self.documents
                if document.get("public_workspace_id") == values["@workspace_id"]
            ]
        else:
            raise AssertionError(f"Unexpected notifications read: {query}")
        return deepcopy(matches)


def stub_modules(container):
    replacements = {}
    for name, values in {
        "config": {"cosmos_notifications_container": container},
        "functions_appinsights": {"log_event": Mock()},
        "functions_debug": {"debug_print": Mock()},
        "functions_group": {
            "assert_group_role": Mock(),
            "find_group_by_id": Mock(),
            "get_user_groups": lambda user: [{"id": group_id} for group_id in MEMBERSHIPS.get(user, [])],
        },
        "functions_public_workspaces": {
            "find_public_workspace_by_id": Mock(),
            "get_user_public_workspaces": lambda user: [],
        },
    }.items():
        module = types.ModuleType(name)
        module.__dict__.update(values)
        replacements[name] = module
    return replacements


def load_notifications():
    spec = importlib.util.spec_from_file_location("test_status_search_notifications", APP / "functions_notifications.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Inbox:
    """The real list function over a fake container, asked the way the route asks it."""

    def __init__(self, module, container):
        self.module = module
        self.container = container

    def list(self, user_id=READER, **kwargs):
        kwargs.setdefault("per_page", 20)
        return self.module.get_user_notifications(user_id, **kwargs)

    def ids(self, user_id=READER, **kwargs):
        return [item["id"] for item in self.list(user_id, **kwargs)["notifications"]]


@pytest.fixture
def make_inbox():
    """Build an Inbox over some documents. The list imports its group and workspace lookups when
    it runs, so the stubbed modules stay in place until the test ends."""
    with patch.dict(sys.modules, {}):
        def build(documents):
            container = FakeNotificationsContainer(documents)
            sys.modules.update(stub_modules(container))
            return Inbox(load_notifications(), container)

        yield build


@pytest.fixture
def mixed(make_inbox):
    return make_inbox(mixed_documents() + [team_alert()])


def route_function():
    tree = ast.parse(ROUTES.read_text(encoding="utf-8"))
    registrar = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_notifications"
    )
    return next(
        node for node in registrar.body
        if isinstance(node, ast.FunctionDef)
        and node.decorator_list
        and isinstance(node.decorator_list[0], ast.Call)
        and node.decorator_list[0].args
        and getattr(node.decorator_list[0].args[0], "value", None) == ROUTE_PATH
    )


def route_client(inbox, user_id=READER):
    """The real route body, without its decorators, on a closed Flask app."""
    calls = []

    def recording_list(**kwargs):
        calls.append(kwargs)
        return inbox.module.get_user_notifications(**kwargs)

    namespace = {
        "request": request,
        "jsonify": jsonify,
        "session": {"user": {"roles": []}},
        "get_current_user_id": lambda: user_id,
        "get_user_notifications": recording_list,
        "parse_notification_read_status": inbox.module.parse_notification_read_status,
        "debug_print": Mock(),
    }
    function = route_function()
    function.decorator_list = []
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROUTES), "exec"), namespace)  # noqa: S102
    app = Flask("notification-filters")
    app.add_url_rule(ROUTE_PATH, endpoint="notifications", view_func=namespace[function.name])
    return app.test_client(), calls


# The list ------------------------------------------------------------------------------------


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.448")


def test_the_read_filter_splits_the_list_without_changing_its_order(mixed):
    everything = ["team-alert", "quarterly", "workbook", "strasse", "contract", "denied", "group-note"]

    assert mixed.ids() == everything
    assert mixed.ids(read_status="all") == everything
    assert mixed.ids(read_status="unread") == ["team-alert", "quarterly", "strasse", "denied", "group-note"]
    assert mixed.ids(read_status="read") == ["workbook", "contract"]
    # The filter is blank-tolerant and case-tolerant, as the route's own parser is.
    assert mixed.ids(read_status="  UnRead ") == mixed.ids(read_status="unread")
    assert mixed.ids(read_status="") == everything

    read_item = mixed.list(read_status="read")["notifications"][0]
    assert read_item["is_read"] is True
    assert all(item["is_read"] is False for item in mixed.list(read_status="unread")["notifications"])


def test_the_filter_and_the_old_include_read_flag_agree_and_both_still_work(mixed):
    assert mixed.ids(include_read=False) == mixed.ids(read_status="unread")
    # Asking for read notifications while excluding them is simply empty, never an error.
    assert mixed.ids(include_read=False, read_status="read") == []
    # Dismissed notifications stay out of every view, and come back only when asked for.
    for status in ("all", "unread", "read"):
        assert "dismissed" not in mixed.ids(read_status=status)
    assert "dismissed" in mixed.ids(include_dismissed=True)
    assert mixed.ids(include_dismissed=True, read_status="unread").count("dismissed") == 1


def test_a_filter_pages_by_what_is_left_after_filtering(make_inbox):
    inbox = make_inbox(paging_documents())

    unread_pages = [inbox.list(page=number, per_page=10, read_status="unread") for number in (1, 2, 3)]
    assert [page["total"] for page in unread_pages] == [20, 20, 20]
    assert [len(page["notifications"]) for page in unread_pages] == [10, 10, 0]
    assert [page["has_more"] for page in unread_pages] == [True, False, False]
    assert all(item["is_read"] is False for page in unread_pages for item in page["notifications"])
    first_ids = [item["id"] for item in unread_pages[0]["notifications"]]
    assert first_ids == [f"item-{number:02d}" for number in (24, 23, 22, 21, 19, 18, 17, 16, 14, 13)]

    read = inbox.list(per_page=10, read_status="read")
    assert (read["total"], len(read["notifications"]), read["has_more"]) == (5, 5, False)

    everything = [inbox.list(page=number, per_page=10) for number in (1, 2, 3)]
    assert [page["total"] for page in everything] == [25, 25, 25]
    assert [len(page["notifications"]) for page in everything] == [10, 10, 5]
    assert [page["has_more"] for page in everything] == [True, True, False]
    assert everything[0]["page"] == 1 and everything[0]["per_page"] == 10


def test_the_search_reads_the_title_and_the_message_ignoring_case(mixed):
    # The word is in the title of one notice, the message of two, and ignored case in both.
    assert mixed.ids(search="ledger") == ["quarterly", "workbook", "group-note"]
    assert mixed.ids(search="LEDGER") == mixed.ids(search="ledger")
    assert mixed.ids(search="  ledger  ") == mixed.ids(search="ledger")
    # Case is folded the way the language does it, not only for ASCII.
    assert mixed.ids(search="STRASSE") == ["strasse"]
    assert mixed.ids(search="straße") == ["strasse"]
    # Somewhere in the text is enough; the title and the message are searched apart.
    assert mixed.ids(search="review is ready") == ["quarterly"]
    assert mixed.ids(search="numbers.") == ["quarterly"]
    assert mixed.ids(search="no such words anywhere") == []


def test_the_search_finds_the_reason_the_reader_is_shown_in_the_message(mixed):
    # The reason lives in the notification's metadata; the message the reader sees appends it.
    shown = mixed.list(search="purchase order")["notifications"]
    assert [item["id"] for item in shown] == ["denied"]
    assert shown[0]["message"] == "Your request was denied. Reason provided: Missing purchase order"


def test_the_search_and_the_read_filter_narrow_each_other(mixed):
    assert mixed.ids(search="ledger", read_status="unread") == ["quarterly", "group-note"]
    assert mixed.ids(search="ledger", read_status="read") == ["workbook"]
    assert mixed.ids(search="ledger", read_status="read", include_read=False) == []
    assert mixed.ids(search="ledger", include_dismissed=True) == [
        "quarterly", "workbook", "dismissed", "group-note",
    ]


def test_a_search_pages_and_counts_only_what_matched(make_inbox):
    inbox = make_inbox(paging_documents())

    # "item 1" is Item 10 to Item 19, of which Items 10 and 15 are read.
    pages = [inbox.list(page=number, per_page=4, search="item 1") for number in (1, 2, 3)]
    assert [page["total"] for page in pages] == [10, 10, 10]
    assert [len(page["notifications"]) for page in pages] == [4, 4, 2]
    assert [page["has_more"] for page in pages] == [True, True, False]
    assert [item["id"] for page in pages for item in page["notifications"]] == [
        f"item-{number}" for number in range(19, 9, -1)
    ]

    unread = inbox.list(per_page=10, search="item 1", read_status="unread")
    assert (unread["total"], len(unread["notifications"]), unread["has_more"]) == (8, 8, False)
    read = inbox.list(per_page=10, search="item 1", read_status="read")
    assert [item["id"] for item in read["notifications"]] == ["item-15", "item-10"]

    none = inbox.list(per_page=10, search="batch 9")
    assert (none["notifications"], none["total"], none["has_more"]) == ([], 0, False)


def test_a_blank_search_changes_nothing(mixed):
    everything = mixed.ids()
    for blank in ("", "   ", None):
        assert mixed.ids(search=blank) == everything


def test_search_text_is_capped_and_never_part_of_a_query(make_inbox):
    long_title = "x" * 150
    inbox = make_inbox([notice("long", long_title, minutes=1), notice("other", "Something else", minutes=2)])

    # Only the first 100 characters are used, so more text after them cannot make a miss.
    assert inbox.ids(search="x" * 100 + "zzz") == ["long"]
    assert inbox.ids(search="x" * 5000) == ["long"]
    # Up to the cap, every character counts.
    assert inbox.ids(search="x" * 99 + "z") == []

    hostile = "'; DROP CONTAINER notifications; --"
    assert inbox.ids(search=hostile) == []
    sent = repr(inbox.container.queries)
    assert "DROP" not in sent and "xxxx" not in sent


def test_a_bad_read_filter_is_refused_before_anything_is_read(mixed):
    reads_before = len(mixed.container.queries)

    for bad in ("archived", "unread,read", "1", "all; read", "<script>"):
        with pytest.raises(ValueError):
            mixed.list(read_status=bad)
    assert len(mixed.container.queries) == reads_before


def test_the_search_cannot_find_what_a_team_alert_hides_from_a_group_member(mixed):
    # A member reads a reduced alert: only the facts, never the run's output.
    assert mixed.ids(search="secret-partner") == []
    assert mixed.ids(search="private hr folder") == []
    member_view = mixed.list(search="nightly scan")["notifications"]
    assert [item["id"] for item in member_view] == ["team-alert"]
    assert member_view[0]["title"] == "High priority workflow alert: Nightly scan"
    assert mixed.ids(search="leak found") == ["team-alert"]
    assert mixed.ids(search="open it for details") == ["team-alert"]

    # The workflow's owner reads the alert in full, so the same words find it for them.
    assert mixed.ids(OWNER, search="secret-partner") == ["team-alert"]
    assert mixed.ids(OWNER, search="private hr folder") == ["team-alert"]
    assert mixed.ids(OWNER, search="open it for details") == []


def test_a_team_alerts_read_state_is_the_readers_own_in_every_view(make_inbox):
    alert = team_alert()
    alert["read_by"] = [OWNER]
    inbox = make_inbox([alert])

    assert inbox.ids(READER, read_status="unread") == ["team-alert"]
    assert inbox.ids(READER, read_status="read") == []
    assert inbox.ids(OWNER, read_status="read") == ["team-alert"]
    assert inbox.ids(OWNER, read_status="unread") == []


def test_the_default_list_is_what_it_was_before_the_filters(mixed):
    page = mixed.list(page=1, per_page=20, include_read=True, include_dismissed=False, user_roles=[])

    assert set(page) == {"notifications", "total", "page", "per_page", "has_more"}
    assert [item["id"] for item in page["notifications"]] == [
        "team-alert", "quarterly", "workbook", "strasse", "contract", "denied", "group-note",
    ]
    assert page["total"] == 7 and page["has_more"] is False
    # The count behind the bell reads the list without ever naming the new parameters.
    assert mixed.module.get_unread_notification_count(READER) == 5


# The route ------------------------------------------------------------------------------------


def test_the_route_keeps_its_blueprint_swagger_and_auth_policy():
    decorators = [ast.unparse(value) for value in route_function().decorator_list]

    assert decorators == [
        "bp.route('/api/notifications', methods=['GET'])",
        "swagger_route(security=get_auth_security())",
        "login_required",
        "user_required",
    ]


def test_the_classic_request_is_answered_as_before(mixed):
    client, calls = route_client(mixed)

    response = client.get(ROUTE_PATH, query_string={
        "page": 1, "per_page": 20, "include_read": "true", "include_dismissed": "false",
    })

    assert response.status_code == 200
    assert set(response.json) == {"success", "notifications", "total", "page", "per_page", "has_more"}
    assert response.json["success"] is True
    assert response.json["total"] == 7
    assert [item["id"] for item in response.json["notifications"]][:2] == ["team-alert", "quarterly"]
    assert calls == [{
        "user_id": READER, "page": 1, "per_page": 20, "include_read": True, "include_dismissed": False,
        "user_roles": [], "read_status": "all", "search": "",
    }]


def test_the_route_applies_status_and_q_before_paging(make_inbox):
    inbox = make_inbox(paging_documents())
    client, calls = route_client(inbox)

    first = client.get(ROUTE_PATH, query_string={"status": "unread", "q": "ITEM 1", "per_page": 10, "page": 1})
    second = client.get(ROUTE_PATH, query_string={"status": "unread", "q": "ITEM 1", "per_page": 10, "page": 2})

    assert first.status_code == 200 and second.status_code == 200
    assert (first.json["total"], first.json["has_more"], len(first.json["notifications"])) == (8, False, 8)
    assert second.json["notifications"] == [] and second.json["total"] == 8
    assert calls[0]["read_status"] == "unread" and calls[0]["search"] == "ITEM 1"
    assert all(item["is_read"] is False for item in first.json["notifications"])


def test_the_route_still_replaces_a_page_size_it_does_not_offer(make_inbox):
    client, calls = route_client(make_inbox(paging_documents()))

    response = client.get(ROUTE_PATH, query_string={"per_page": 15, "status": "read"})

    assert response.status_code == 200
    assert response.json["per_page"] == 20
    assert calls[0]["per_page"] == 20


@pytest.mark.parametrize("status", ["archived", "unread,read", "0", "all;read", "<script>"])
def test_the_route_refuses_an_unknown_status_instead_of_showing_everything(mixed, status):
    client, calls = route_client(mixed)
    reads_before = len(mixed.container.queries)

    response = client.get(ROUTE_PATH, query_string={"status": status, "q": "ledger"})

    assert response.status_code == 400
    assert response.json == {"success": False, "error": "Invalid status. Use all, unread or read."}
    # The refusal is a fixed sentence: the rejected value is never echoed back.
    assert status not in response.get_data(as_text=True)
    assert calls == []
    assert len(mixed.container.queries) == reads_before


@pytest.mark.parametrize(("status", "expected"), [
    ("", "all"), ("all", "all"), ("ALL", "all"), (" unread ", "unread"), ("Read", "read"),
])
def test_the_route_accepts_every_spelling_of_a_real_status(mixed, status, expected):
    client, calls = route_client(mixed)

    response = client.get(ROUTE_PATH, query_string={"status": status})

    assert response.status_code == 200
    assert calls[0]["read_status"] == expected


def test_the_route_answers_an_over_long_search_by_using_only_its_first_part(make_inbox):
    inbox = make_inbox([notice("long", "x" * 150, minutes=1)])
    client, _ = route_client(inbox)

    response = client.get(ROUTE_PATH, query_string={"q": "x" * 100 + "y" * 400})

    assert response.status_code == 200
    assert [item["id"] for item in response.json["notifications"]] == ["long"]


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-q"]))
