# test_orchestration_directory_access.py
"""
Functional test for Chat Orchestration's Microsoft Entra ID directory access guidance.
Version: 0.261.204
Implemented in: 0.261.204

This test ensures that when Microsoft Graph refuses the application's own directory read
(the Directory.Read.All application permission is missing, or the client-credential
sign-in is refused), the refusal is kept distinct from decisions about the user: users
see which source could not be verified and that they should contact an administrator,
administrators get one notification and an Admin Settings warning, and the deployers
request and consent to the permission. Real readers, bootstrap wiring, notifications,
admin route, templates and JavaScript run with only the Graph wire, MSAL, Cosmos and
the browser DOM doubled. No tenant, network, or Azure CLI access occurs.
"""

import base64
from copy import deepcopy
from datetime import datetime
from html.parser import HTMLParser
import importlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from azure.core.exceptions import HttpResponseError
from azure.cosmos.exceptions import (
    CosmosHttpResponseError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from flask import Blueprint, Flask
import pytest
import requests
from werkzeug.test import Client
from werkzeug.wrappers import Response

# These real application modules are imported after adding the repository paths.
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(TESTS))

from functions_orchestration_directory_access import (
    DIRECTORY_ACCESS_FAILURE_CODE,
    DIRECTORY_ACCESS_REASONS,
    DIRECTORY_GATED_CAPABILITIES,
    DIRECTORY_PERMISSION_MISSING,
    DIRECTORY_SIGN_IN_FAILED,
    GRAPH_DIRECTORY_PERMISSION,
    GRAPH_DIRECTORY_PERMISSION_ID,
    GRAPH_RESOURCE_APP_ID,
    directory_access_reason,
)
from functions_orchestration_external_identity import ExternalIdentityServiceError
from functions_orchestration_invocation_capture import (
    OrchestrationInvocationCapture,
    OrchestrationInvocationDeniedError,
)
from functions_orchestration_results import ResultUnavailableError
from test_orchestration_external_bootstrap import external_root, reader_for  # noqa: F401
from test_orchestration_external_identity import (
    APP_ID,
    GraphWorld,
    SCOPE,
    TOKEN,
    USER_ID,
    read_identity,
)
from test_orchestration_harness_routes import login, modules  # noqa: F401
from test_support.versioning import assert_app_version_at_least


CHECK_URL = "/api/admin/settings/orchestration/directory-access-check"
NOTIFICATION_TYPE = "orchestration_directory_access_unavailable"
ACCESS_DENIED = "external_identity_access_denied"
PRIVATE_ERROR = "synthetic-private-error"
CLIENT_SECRET = "synthetic-client-secret"
PRIVATE_SETTING = "private-setting-must-not-be-returned"
WEB = {"enable_chat_orchestration": True, "enable_web_search": True}
ALL_SOURCES = {
    **WEB,
    "enable_url_access": True,
    "enable_source_review": True,
    "enable_semantic_kernel": True,
    "enable_chat_orchestration_actions": True,
}
EXPECTED_SOURCES = [
    {"id": "web_search", "label": "Search the web"},
    {"id": "url_fetch", "label": "Read linked pages"},
    {"id": "deep_research", "label": "Research in depth"},
    {"id": "agent_invoke", "label": "Ask an agent"},
    {"id": "action_invoke", "label": "Use an action"},
]
ACTIVITIES = {
    "web_search": "use web search",
    "url_fetch": "read linked web pages",
    "deep_research": "use deep research",
    "agent_invoke": "use agents",
    "action_invoke": "use actions",
}
REPORT_FIELDS = {
    "status", "required", "reason", "capabilities", "web_search_enabled",
    "application_client_id", "graph_permission", "graph_permission_id",
    "graph_resource_app_id", "checked_at",
}


class ReasonText(str):
    """A string subclass must never be trusted as an application reason code."""


def user_message(activity):
    return (
        f"Unable to verify your permission to {activity} because this application "
        "doesn't have access to Microsoft Entra ID. Please contact your administrator."
    )


def refuse(world, kind, status):
    world.overrides[kind, 0] = {"status": status, "raw": TOKEN.encode()}


# --------------------------------------------------------------------------------------
# Directory reader and invocation contracts
# --------------------------------------------------------------------------------------

def test_version_includes_directory_access_guidance():
    assert_app_version_at_least("0.261.204")


@pytest.mark.parametrize("kind", ["user", "principals", "assignments"])
@pytest.mark.parametrize("status, code", [
    (403, DIRECTORY_PERMISSION_MISSING),
    (401, DIRECTORY_SIGN_IN_FAILED),
    (404, ACCESS_DENIED),
    (410, ACCESS_DENIED),
])
def test_graph_refusals_of_the_application_are_not_user_decisions(kind, status, code):
    with GraphWorld() as world:
        refuse(world, kind, status)
        with pytest.raises(ResultUnavailableError) as caught:
            read_identity(world.reader())
    assert caught.value.code == code
    assert directory_access_reason(caught.value) == (code if code in DIRECTORY_ACCESS_REASONS else None)
    assert TOKEN not in repr(caught.value) and TOKEN not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("code, expected", [
    (DIRECTORY_PERMISSION_MISSING, DIRECTORY_PERMISSION_MISSING),
    (DIRECTORY_SIGN_IN_FAILED, DIRECTORY_SIGN_IN_FAILED),
    (ReasonText(DIRECTORY_PERMISSION_MISSING), ACCESS_DENIED),
    ("result_unavailable", ACCESS_DENIED),
    ("external_identity_role_required", ACCESS_DENIED),
    (None, ACCESS_DENIED),
])
def test_only_exact_directory_reasons_survive_the_token_source(code, expected):
    with GraphWorld() as world:
        world.token_provider.side_effect = ResultUnavailableError(code)
        with pytest.raises(ResultUnavailableError) as caught:
            read_identity(world.reader())
        assert world.adapter.requests == []
    assert type(caught.value.code) is str
    assert caught.value.code == expected
    assert caught.value.__context__ is None


@pytest.mark.parametrize("status", [401, 403])
def test_sdk_refusals_of_user_settings_stay_access_denials(status):
    with GraphWorld() as world:
        error = HttpResponseError(TOKEN)
        error.status_code = status
        world.settings_reader.side_effect = error
        with pytest.raises(ResultUnavailableError) as caught:
            read_identity(world.reader())
    assert caught.value.code == ACCESS_DENIED
    assert directory_access_reason(caught.value) is None
    assert TOKEN not in str(caught.value)


def test_directory_access_reason_accepts_only_exact_application_reasons():
    assert directory_access_reason(ResultUnavailableError(DIRECTORY_PERMISSION_MISSING)) == DIRECTORY_PERMISSION_MISSING
    assert directory_access_reason(ResultUnavailableError(DIRECTORY_SIGN_IN_FAILED)) == DIRECTORY_SIGN_IN_FAILED
    assert directory_access_reason(
        OrchestrationInvocationDeniedError(DIRECTORY_SIGN_IN_FAILED)
    ) == DIRECTORY_SIGN_IN_FAILED
    spoofed = PermissionError(PRIVATE_ERROR)
    spoofed.code = ReasonText(DIRECTORY_PERMISSION_MISSING)
    not_a_refusal = RuntimeError(PRIVATE_ERROR)
    not_a_refusal.code = DIRECTORY_PERMISSION_MISSING
    for error in (
        ResultUnavailableError(ACCESS_DENIED),
        ResultUnavailableError(),
        OrchestrationInvocationDeniedError(),
        OrchestrationInvocationDeniedError(ACCESS_DENIED),
        ExternalIdentityServiceError(),
        spoofed,
        not_a_refusal,
        RuntimeError(DIRECTORY_PERMISSION_MISSING),
        None,
    ):
        assert directory_access_reason(error) is None
    assert set(DIRECTORY_ACCESS_REASONS) == {DIRECTORY_PERMISSION_MISSING, DIRECTORY_SIGN_IN_FAILED}


@pytest.mark.parametrize("error, expected", [
    (ResultUnavailableError(DIRECTORY_PERMISSION_MISSING), DIRECTORY_PERMISSION_MISSING),
    (ResultUnavailableError(DIRECTORY_SIGN_IN_FAILED), DIRECTORY_SIGN_IN_FAILED),
    (ResultUnavailableError(ACCESS_DENIED), ACCESS_DENIED),
    (OrchestrationInvocationDeniedError(DIRECTORY_PERMISSION_MISSING), DIRECTORY_PERMISSION_MISSING),
    (OrchestrationInvocationDeniedError(), None),
    (PermissionError(PRIVATE_ERROR), None),
])
def test_invocation_denials_keep_only_a_stable_reason(error, expected):
    capture = OrchestrationInvocationCapture(Mock(return_value=None))
    with pytest.raises(OrchestrationInvocationDeniedError) as caught:
        capture.fail(error)
    assert caught.value is not error
    assert caught.value.authority_reason == expected
    assert caught.value.code == "result_unavailable"
    assert caught.value.retryable is False
    assert PRIVATE_ERROR not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("value", [
    "external-identity-denied", "External_identity", "a" * 81, "has space", "trailing\n",
    "_leading", "9starts_with_digit", "", ReasonText(DIRECTORY_PERMISSION_MISSING), 7, None,
])
def test_unsafe_authority_reasons_are_dropped(value):
    assert OrchestrationInvocationDeniedError(value).authority_reason is None
    error = PermissionError(PRIVATE_ERROR)
    error.code = value
    capture = OrchestrationInvocationCapture(Mock(return_value=None))
    with pytest.raises(OrchestrationInvocationDeniedError) as caught:
        capture.fail(error)
    assert caught.value.authority_reason is None
    assert OrchestrationInvocationDeniedError("a" * 80).authority_reason == "a" * 80


def test_first_directory_reason_is_sticky_for_the_invocation():
    capture = OrchestrationInvocationCapture(Mock(return_value=None))
    with pytest.raises(OrchestrationInvocationDeniedError) as first:
        capture.fail(ResultUnavailableError(DIRECTORY_PERMISSION_MISSING))
    with pytest.raises(OrchestrationInvocationDeniedError) as again:
        capture.require_valid()
    with pytest.raises(OrchestrationInvocationDeniedError) as later:
        capture.fail(ResultUnavailableError(DIRECTORY_SIGN_IN_FAILED))
    assert first.value.authority_reason == DIRECTORY_PERMISSION_MISSING
    assert again.value.authority_reason == DIRECTORY_PERMISSION_MISSING
    assert later.value.authority_reason == DIRECTORY_PERMISSION_MISSING
    assert first.value is not again.value


def test_capture_callback_refusal_keeps_the_directory_reason():
    callback = Mock(side_effect=ResultUnavailableError(DIRECTORY_SIGN_IN_FAILED))
    capture = OrchestrationInvocationCapture(callback)
    with pytest.raises(OrchestrationInvocationDeniedError) as caught:
        capture("web", settings={})
    callback.assert_called_once()
    assert caught.value.authority_reason == DIRECTORY_SIGN_IN_FAILED
    assert caught.value.__context__ is None
    with pytest.raises(OrchestrationInvocationDeniedError) as retained:
        capture.require_valid()
    assert retained.value.authority_reason == DIRECTORY_SIGN_IN_FAILED


# --------------------------------------------------------------------------------------
# What users are told
# --------------------------------------------------------------------------------------

def test_users_are_told_which_source_could_not_be_verified(modules):
    # The schema imports application settings, so it is loaded inside the offline application.
    schema = importlib.import_module("functions_orchestration_schema")
    assert schema.DIRECTORY_ACCESS_ACTIVITIES == ACTIVITIES
    assert tuple(schema.DIRECTORY_ACCESS_ACTIVITIES) == DIRECTORY_GATED_CAPABILITIES
    assert schema.build_failure(DIRECTORY_ACCESS_FAILURE_CODE, capability_id="web_search") == {
        "code": DIRECTORY_ACCESS_FAILURE_CODE,
        "message": user_message("use web search"),
        "capability_id": "web_search",
    }
    for capability_id, activity in ACTIVITIES.items():
        failure = schema.build_failure(DIRECTORY_ACCESS_FAILURE_CODE, step_id="gather", capability_id=capability_id)
        assert failure["message"] == user_message(activity)
        assert schema.safe_failure({"code": DIRECTORY_ACCESS_FAILURE_CODE, "message": PRIVATE_ERROR}, capability_id=capability_id) == {
            "code": DIRECTORY_ACCESS_FAILURE_CODE, "message": user_message(activity), "capability_id": capability_id,
        }
    generic = user_message("use web search and other external sources")
    assert schema.FAILURE_MESSAGES[DIRECTORY_ACCESS_FAILURE_CODE] == generic
    assert schema.build_failure(DIRECTORY_ACCESS_FAILURE_CODE)["message"] == generic
    assert schema.build_failure(DIRECTORY_ACCESS_FAILURE_CODE, capability_id="compose")["message"] == generic
    unrelated = schema.build_failure("result_unavailable", capability_id="web_search")
    assert unrelated["message"] == schema.FAILURE_MESSAGES["result_unavailable"]


def test_executor_explains_only_application_directory_refusals(modules):
    # The executor imports application settings, so it is loaded inside the offline application.
    executor = importlib.import_module("functions_orchestration_executor")
    schema = importlib.import_module("functions_orchestration_schema")
    unavailable = schema.build_failure("result_unavailable")
    explained = schema.build_failure(DIRECTORY_ACCESS_FAILURE_CODE)
    denied = OrchestrationInvocationDeniedError(DIRECTORY_PERMISSION_MISSING)
    # Recording the step's failure names its source; the runtime tests cover that wording.
    assert executor._access_failure(denied) == explained
    assert executor._access_failure(ResultUnavailableError(DIRECTORY_SIGN_IN_FAILED)) == explained
    assert explained["message"] == schema.FAILURE_MESSAGES[DIRECTORY_ACCESS_FAILURE_CODE]
    for refusal in (
        ResultUnavailableError(ACCESS_DENIED),
        ResultUnavailableError("external_identity_role_required"),
        OrchestrationInvocationDeniedError(),
        OrchestrationInvocationDeniedError(ACCESS_DENIED),
    ):
        assert executor._access_failure(refusal) == unavailable
    assert executor._authority_reason(denied) == DIRECTORY_PERMISSION_MISSING
    assert executor._authority_reason(ResultUnavailableError(ACCESS_DENIED)) == ACCESS_DENIED
    assert executor._authority_reason(OrchestrationInvocationDeniedError()) is None
    assert executor._authority_reason(RuntimeError(PRIVATE_ERROR)) is None


# --------------------------------------------------------------------------------------
# Administrator notifications from live requests
# --------------------------------------------------------------------------------------

class NotificationStore:
    """Cosmos-like notifications container: unique ids, 409 on a duplicate, point reads."""

    def __init__(self):
        self.items = {}
        self.creates = []
        self.reads = []
        self.fail = None

    def create_item(self, body, **_options):
        self.creates.append(deepcopy(body))
        if self.fail is not None:
            raise self.fail
        if body["id"] in self.items:
            raise CosmosResourceExistsError(status_code=409, message="Conflict")
        self.items[body["id"]] = deepcopy(body)
        return deepcopy(body)

    def read_item(self, item, partition_key, **_options):
        self.reads.append((item, partition_key))
        stored = self.items.get(item)
        if stored is None or stored.get("user_id") != partition_key:
            raise CosmosResourceNotFoundError(status_code=404, message="Not found")
        return deepcopy(stored)


@pytest.fixture
def directory_state(external_root, monkeypatch):
    # Readiness and notifications load application clients, so they come from the offline application.
    readiness = importlib.import_module("functions_orchestration_directory_readiness")
    notifications = importlib.import_module("functions_notifications")
    store = NotificationStore()
    events = []

    def recorder(source):
        def record(message, extra=None, level=logging.INFO, **_options):
            events.append(SimpleNamespace(source=source, message=message, extra=deepcopy(extra), level=level))
        return record

    monkeypatch.setattr(notifications, "cosmos_notifications_container", store)
    monkeypatch.setattr(notifications, "log_event", recorder("notifications"))
    monkeypatch.setattr(readiness, "log_event", recorder("readiness"))
    readiness.reset_directory_access_state()
    yield SimpleNamespace(
        runtime=external_root, world=external_root.world, readiness=readiness,
        notifications=notifications, store=store, events=events,
    )
    readiness.reset_directory_access_state()


def events_from(state, source):
    return [(event.extra, event.level) for event in state.events if event.source == source]


def assert_private_values_absent(text):
    for private in (TOKEN, CLIENT_SECRET, PRIVATE_ERROR, PRIVATE_SETTING):
        assert private not in text


def test_live_refusal_notifies_administrators_once(directory_state):
    state = directory_state
    refuse(state.world, "user", 403)
    for _attempt in range(2):
        with pytest.raises(ResultUnavailableError) as caught:
            read_identity(reader_for(state.runtime))
        assert caught.value.code == DIRECTORY_PERMISSION_MISSING
        assert caught.value.__context__ is None
    assert len(state.store.creates) == 1
    [notification] = state.store.items.values()
    assert notification["notification_type"] == NOTIFICATION_TYPE
    assert notification["scope"] == "assignment"
    assert notification["assignment"] == {"roles": ["Admin"]}
    assert notification["user_id"] is None
    assert notification["link_url"] == "/admin/settings#chat-orchestration"
    assert notification["title"] == "Chat Orchestration can't verify access to web search"
    assert GRAPH_DIRECTORY_PERMISSION in notification["message"]
    assert notification["metadata"] == {
        "reason": DIRECTORY_PERMISSION_MISSING,
        "graph_permission": GRAPH_DIRECTORY_PERMISSION,
        "graph_permission_id": GRAPH_DIRECTORY_PERMISSION_ID,
        "graph_resource_app_id": GRAPH_RESOURCE_APP_ID,
    }
    serialized = json.dumps(notification)
    assert_private_values_absent(serialized)
    assert USER_ID not in serialized
    assert events_from(state, "readiness") == [({"authority_reason": DIRECTORY_PERMISSION_MISSING}, logging.WARNING)]


def test_another_instance_reuses_the_same_notification(directory_state):
    state = directory_state
    refuse(state.world, "assignments", 403)
    with pytest.raises(ResultUnavailableError):
        read_identity(reader_for(state.runtime))
    # A second process has no memory of the first report; the retry key prevents a duplicate.
    state.readiness.reset_directory_access_state()
    with pytest.raises(ResultUnavailableError):
        read_identity(reader_for(state.runtime))
    assert len(state.store.creates) == 2
    assert len(state.store.items) == 1
    [notification_id] = state.store.items
    assert state.store.reads == [(notification_id, None)]


@pytest.mark.parametrize("error", ["invalid_client", "unauthorized_client", "consent_required"])
def test_refused_application_sign_in_is_reported_without_directory_reads(directory_state, error):
    state = directory_state
    state.runtime.token.return_value = {"error": error, "error_description": PRIVATE_ERROR}
    with pytest.raises(ResultUnavailableError) as caught:
        read_identity(reader_for(state.runtime))
    assert caught.value.code == DIRECTORY_SIGN_IN_FAILED
    assert state.world.adapter.requests == []
    [notification] = state.store.items.values()
    assert notification["title"] == "Chat Orchestration can't sign in to Microsoft Entra ID"
    assert notification["metadata"]["reason"] == DIRECTORY_SIGN_IN_FAILED
    assert_private_values_absent(json.dumps(notification))


@pytest.mark.parametrize("case", ["role_required", "account_disabled", "not_found", "outage", "timeout"])
def test_user_decisions_and_outages_do_not_notify(directory_state, case):
    state = directory_state
    expected = ResultUnavailableError
    if case == "role_required":
        state.world.assignments.clear()
    elif case == "account_disabled":
        state.world.user["accountEnabled"] = False
    elif case == "not_found":
        refuse(state.world, "user", 404)
    elif case == "outage":
        refuse(state.world, "principals", 503)
        expected = ExternalIdentityServiceError
    else:
        state.world.adapter.error = requests.Timeout(TOKEN)
        expected = ExternalIdentityServiceError
    with pytest.raises(expected) as caught:
        read_identity(reader_for(state.runtime))
    assert directory_access_reason(caught.value) is None
    assert state.store.creates == []
    assert state.events == []


def test_unsaved_notification_is_retried_by_the_next_failure(directory_state):
    state = directory_state
    refuse(state.world, "user", 403)
    state.store.fail = CosmosHttpResponseError(status_code=503, message=PRIVATE_ERROR)
    with pytest.raises(ResultUnavailableError) as caught:
        read_identity(reader_for(state.runtime))
    assert caught.value.code == DIRECTORY_PERMISSION_MISSING
    assert len(state.store.creates) == 1 and state.store.items == {}
    assert events_from(state, "notifications") == [({"error_type": "CosmosHttpResponseError"}, logging.WARNING)]
    state.store.fail = None
    for _attempt in range(2):
        with pytest.raises(ResultUnavailableError):
            read_identity(reader_for(state.runtime))
    assert len(state.store.creates) == 2
    assert len(state.store.items) == 1
    assert_private_values_absent(json.dumps([event.__dict__ for event in state.events], default=str))


def test_notifier_failure_never_replaces_the_users_refusal(directory_state, monkeypatch):
    state = directory_state
    refuse(state.world, "user", 403)
    original = state.notifications.create_notification
    monkeypatch.setattr(state.notifications, "create_notification", Mock(side_effect=RuntimeError(PRIVATE_ERROR)))
    with pytest.raises(ResultUnavailableError) as caught:
        read_identity(reader_for(state.runtime))
    assert caught.value.code == DIRECTORY_PERMISSION_MISSING
    assert caught.value.__context__ is None
    assert events_from(state, "readiness") == [
        ({"authority_reason": DIRECTORY_PERMISSION_MISSING}, logging.WARNING),
        ({"error_type": "RuntimeError"}, logging.WARNING),
    ]
    assert_private_values_absent(json.dumps([event.__dict__ for event in state.events], default=str))
    monkeypatch.setattr(state.notifications, "create_notification", original)
    with pytest.raises(ResultUnavailableError):
        read_identity(reader_for(state.runtime))
    assert len(state.store.items) == 1


def test_only_directory_reasons_are_reported(directory_state):
    state = directory_state
    reasons = (ACCESS_DENIED, "result_unavailable", ReasonText(DIRECTORY_PERMISSION_MISSING), None, 7, [])
    results = [state.readiness.report_directory_access_failure(reason) for reason in reasons]
    assert results == [None] * len(reasons)
    assert state.store.creates == []
    assert state.events == []


# --------------------------------------------------------------------------------------
# The Admin Settings check
# --------------------------------------------------------------------------------------

def check(state, settings=WEB, **options):
    return state.readiness.check_orchestration_directory_access(USER_ID, deepcopy(settings), **options)


@pytest.mark.parametrize("settings", [
    None,
    [],
    {},
    {"enable_web_search": True},
    {**ALL_SOURCES, "enable_chat_orchestration": False},
    {"enable_chat_orchestration": True},
    {**ALL_SOURCES, "chat_orchestration_enabled_capabilities": ["compose"]},
    {**ALL_SOURCES, "chat_orchestration_enabled_capabilities": "not-a-list"},
])
def test_check_reads_nothing_when_no_external_source_is_enabled(directory_state, settings):
    state = directory_state
    report = check(state, settings)
    assert report == {
        "status": "not_required", "required": False, "reason": None, "capabilities": [],
        "web_search_enabled": False, "application_client_id": APP_ID,
        "graph_permission": GRAPH_DIRECTORY_PERMISSION,
        "graph_permission_id": GRAPH_DIRECTORY_PERMISSION_ID,
        "graph_resource_app_id": GRAPH_RESOURCE_APP_ID, "checked_at": None,
    }
    assert state.runtime.client_factory.call_count == 0
    assert state.world.adapter.requests == []
    assert state.store.creates == []


def test_check_lists_every_source_that_needs_directory_access(directory_state):
    state = directory_state
    everything = check(state, ALL_SOURCES)
    linked_pages_only = check(state, {**ALL_SOURCES, "chat_orchestration_enabled_capabilities": ["url_fetch"]})
    assert everything["capabilities"] == EXPECTED_SOURCES
    assert everything["web_search_enabled"] is True
    assert linked_pages_only["capabilities"] == [EXPECTED_SOURCES[1]]
    assert linked_pages_only["web_search_enabled"] is False
    assert linked_pages_only["required"] is True


def test_ready_check_signs_in_as_the_application_and_is_briefly_reused(directory_state):
    state = directory_state
    first = check(state)
    assert set(first) == REPORT_FIELDS
    assert first["status"] == "ready" and first["reason"] is None and first["required"] is True
    assert first["capabilities"] == [EXPECTED_SOURCES[0]]
    assert first["web_search_enabled"] is True
    assert first["application_client_id"] == APP_ID
    assert datetime.fromisoformat(first["checked_at"]).utcoffset() is not None
    assert len(state.world.adapter.requests) == 3
    assert state.runtime.client_factory.call_count == 1
    assert state.runtime.client_factory.call_args.kwargs == {
        "authority": "https://login.example.test/tenant", "client_credential": CLIENT_SECRET,
        "token_cache": None, "timeout": 10.0,
    }
    assert state.runtime.token.call_args.kwargs == {"scopes": [SCOPE]}
    # Reopening Admin Settings reuses a recent success without signing in or rereading Graph.
    refuse(state.world, "user", 403)
    cached = check(state)
    assert cached == first
    assert len(state.world.adapter.requests) == 3
    assert state.runtime.client_factory.call_count == 1
    assert state.store.creates == []
    # Re-checking reads again, finds the refusal, and reports it.
    rechecked = check(state, refresh=True)
    assert rechecked["status"] == "permission_missing"
    assert rechecked["reason"] == DIRECTORY_PERMISSION_MISSING
    assert len(state.world.adapter.requests) == 4
    assert len(state.store.items) == 1
    # A failure is never reused, so a fixed permission shows up on the next page load.
    state.world.overrides.clear()
    fixed = check(state)
    assert fixed["status"] == "ready"
    assert len(state.world.adapter.requests) == 7


def test_missing_permission_found_by_the_check_notifies_once(directory_state):
    state = directory_state
    refuse(state.world, "principals", 403)
    report = check(state, ALL_SOURCES)
    again = check(state, ALL_SOURCES)
    assert report["status"] == again["status"] == "permission_missing"
    assert report["reason"] == DIRECTORY_PERMISSION_MISSING
    assert report["capabilities"] == EXPECTED_SOURCES
    assert len(state.store.creates) == 1
    [notification] = state.store.items.values()
    assert notification["metadata"]["reason"] == DIRECTORY_PERMISSION_MISSING
    assert_private_values_absent(json.dumps([report, notification]))


@pytest.mark.parametrize("error", [
    "invalid_client", "invalid_grant", "unauthorized_client", "invalid_scope",
    "access_denied", "consent_required", "interaction_required",
])
def test_refused_application_sign_in_is_a_credential_problem(directory_state, error):
    state = directory_state
    state.runtime.token.return_value = {"error": error, "error_description": PRIVATE_ERROR}
    report = check(state)
    assert report["status"] == "sign_in_failed"
    assert report["reason"] == DIRECTORY_SIGN_IN_FAILED
    assert state.world.adapter.requests == []
    [notification] = state.store.items.values()
    assert notification["metadata"]["reason"] == DIRECTORY_SIGN_IN_FAILED
    assert_private_values_absent(json.dumps([report, notification]))


@pytest.mark.parametrize("case, reason", [
    ("graph_outage", "external_identity_service_unavailable"),
    ("token_outage", "external_identity_service_unavailable"),
    ("token_throttled", "external_identity_throttled"),
    ("token_unrecognized", "external_identity_response_invalid"),
    ("timeout", "external_identity_timeout"),
])
def test_outages_are_unverified_and_never_reused(directory_state, case, reason):
    state = directory_state
    if case == "graph_outage":
        refuse(state.world, "user", 503)
    elif case == "token_outage":
        state.runtime.token.return_value = {"error": "temporarily_unavailable", "error_description": PRIVATE_ERROR}
    elif case == "token_throttled":
        state.runtime.token.return_value = {"error": "too_many_requests", "error_description": PRIVATE_ERROR}
    elif case == "token_unrecognized":
        state.runtime.token.return_value = {"error": PRIVATE_ERROR}
    else:
        state.world.adapter.error = requests.Timeout(TOKEN)
    report = check(state)
    assert report["status"] == "unverified"
    assert report["reason"] == reason
    assert state.store.creates == []
    assert state.events == []
    assert_private_values_absent(json.dumps(report))
    state.world.overrides.clear()
    state.world.adapter.error = None
    state.runtime.token.return_value = {"access_token": TOKEN}
    recovered = check(state)
    assert recovered["status"] == "ready"


def test_unusable_application_id_is_unverified_without_signing_in(directory_state, monkeypatch):
    state = directory_state
    monkeypatch.setattr(state.runtime.auth, "CLIENT_ID", "not-a-guid")
    report = check(state)
    assert report["status"] == "unverified"
    assert report["reason"] == "external_identity_configuration_invalid"
    assert report["application_client_id"] is None
    assert state.runtime.client_factory.call_count == 0
    assert state.world.adapter.requests == []
    assert state.store.creates == []


def test_token_source_mints_only_its_own_graph_token(directory_state, monkeypatch):
    state = directory_state
    _graph_base, graph_scope, app_client_id, get_access_token = (
        state.readiness.graph_directory_token_provider(timeout=4.0)
    )
    assert graph_scope == SCOPE and app_client_id == APP_ID
    # A token for any other resource is refused before the application signs in.
    for scope in ("https://management.azure.com/.default", SCOPE.upper(), f"{SCOPE} offline_access", None):
        with pytest.raises(ResultUnavailableError) as refused:
            get_access_token(scope)
        assert refused.value.code == ACCESS_DENIED
    assert state.runtime.client_factory.call_count == 0
    token = get_access_token(SCOPE)
    assert token == TOKEN
    assert state.runtime.client_factory.call_count == 1
    assert state.runtime.client_factory.call_args.kwargs["timeout"] == 4.0
    assert state.runtime.token.call_args.kwargs == {"scopes": [SCOPE]}
    # A token source built for one application never signs in as another.
    monkeypatch.setattr(state.runtime.auth, "CLIENT_ID", "11111111-1111-4111-8111-111111111111")
    with pytest.raises(ResultUnavailableError) as changed:
        get_access_token(SCOPE)
    assert changed.value.code == ACCESS_DENIED
    assert state.runtime.token.call_count == 1


class UnexpectedProbeFailure(Exception):
    """A failure no directory reader contract anticipates."""


@pytest.mark.parametrize("case, error_type", [
    ("prepare", "RuntimeError"),
    ("read", "UnexpectedProbeFailure"),
])
def test_unexpected_check_failures_are_unverified_and_logged_by_type(directory_state, monkeypatch, case, error_type):
    state = directory_state
    if case == "prepare":
        def unavailable():
            raise RuntimeError(PRIVATE_ERROR)

        monkeypatch.setattr(state.runtime.auth, "get_graph_base_url", unavailable)
    else:
        state.world.adapter.error = UnexpectedProbeFailure(PRIVATE_ERROR)
    report = check(state)
    assert report["status"] == "unverified"
    assert report["reason"] == "directory_check_failed"
    assert events_from(state, "readiness") == [({"error_type": error_type}, logging.WARNING)]
    assert state.store.creates == []
    assert_private_values_absent(json.dumps([report, [event.__dict__ for event in state.events]], default=str))


@pytest.fixture
def admin_route(directory_state, monkeypatch):
    state = directory_state
    # Admin settings routes import the full settings stack, so they load inside the offline application.
    admin = importlib.import_module("route_frontend_admin_settings")
    settings = {**WEB, "azure_openai_api_key": PRIVATE_SETTING}
    route_events = []

    def record(message, extra=None, level=logging.INFO, **_options):
        route_events.append((deepcopy(extra), level))

    monkeypatch.setattr(admin, "get_settings", lambda: deepcopy(settings))
    monkeypatch.setattr(admin, "log_event", record)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="local-directory-access-test")
    blueprint = Blueprint("frontend_admin_settings", __name__)
    blueprint.before_request(state.runtime.auth.admin_required_blueprint())
    admin.register_route_frontend_admin_settings(blueprint)
    app.register_blueprint(blueprint)
    return SimpleNamespace(
        state=state, admin=admin, app=app, client=Client(app, Response), events=route_events,
    )


def response_json(response):
    return json.loads(response.get_data(as_text=True))


def test_directory_access_check_is_admin_only(admin_route):
    route = admin_route
    anonymous = route.client.post(CHECK_URL, json={"refresh": True})
    login(route, user_id=USER_ID, roles=("User",))
    signed_in_user = route.client.post(CHECK_URL, json={"refresh": True})
    assert anonymous.status_code == 401
    assert signed_in_user.status_code == 403
    assert route.state.runtime.client_factory.call_count == 0
    assert route.state.world.adapter.requests == []
    assert route.state.store.creates == []


def test_administrator_sees_the_missing_permission_without_private_values(admin_route):
    route = admin_route
    refuse(route.state.world, "user", 403)
    login(route, user_id=USER_ID, roles=("Admin",))
    response = route.client.post(CHECK_URL, json={"refresh": False})
    body = response_json(response)
    assert response.status_code == 200
    assert set(body) == REPORT_FIELDS | {"success"}
    assert body["success"] is True
    assert body["status"] == "permission_missing"
    assert body["reason"] == DIRECTORY_PERMISSION_MISSING
    assert body["capabilities"] == [EXPECTED_SOURCES[0]]
    assert body["web_search_enabled"] is True
    assert body["application_client_id"] == APP_ID
    assert body["graph_permission"] == GRAPH_DIRECTORY_PERMISSION
    assert body["graph_permission_id"] == GRAPH_DIRECTORY_PERMISSION_ID
    assert body["graph_resource_app_id"] == GRAPH_RESOURCE_APP_ID
    assert_private_values_absent(response.get_data(as_text=True))
    assert len(route.state.store.items) == 1


@pytest.mark.parametrize("request_options, rechecked", [
    ({"json": {"refresh": True}}, True),
    ({"json": {"refresh": "true"}}, False),
    ({"json": {"refresh": 1}}, False),
    ({"json": {}}, False),
    ({"json": [True]}, False),
    ({"data": "refresh=true", "content_type": "text/plain"}, False),
])
def test_only_an_explicit_recheck_bypasses_a_recent_success(admin_route, request_options, rechecked):
    route = admin_route
    login(route, user_id=USER_ID, roles=("Admin",))
    first = route.client.post(CHECK_URL, json={})
    refuse(route.state.world, "user", 403)
    second = route.client.post(CHECK_URL, **request_options)
    assert first.status_code == second.status_code == 200
    assert response_json(first)["status"] == "ready"
    assert response_json(second)["status"] == ("permission_missing" if rechecked else "ready")


def test_failed_check_returns_only_a_generic_error(admin_route, monkeypatch):
    route = admin_route
    monkeypatch.setattr(
        route.admin, "check_orchestration_directory_access", Mock(side_effect=RuntimeError(PRIVATE_ERROR)),
    )
    login(route, user_id=USER_ID, roles=("Admin",))
    response = route.client.post(CHECK_URL, json={"refresh": True})
    assert response.status_code == 500
    assert response_json(response) == {
        "success": False, "error": "The directory access check could not be completed.",
    }
    assert route.events == [({"error_type": "RuntimeError"}, logging.WARNING)]
    assert_private_values_absent(response.get_data(as_text=True))


# --------------------------------------------------------------------------------------
# Deployers request and consent to the permission
# --------------------------------------------------------------------------------------

APP_PRINCIPAL = "12121212-1212-4121-8121-121212121212"
GRAPH_PRINCIPAL = "13131313-1313-4131-8131-131313131313"
OTHER_PRINCIPAL = "14141414-1414-4141-8141-141414141414"
OTHER_ROLE = "15151515-1515-4151-8151-151515151515"
POWERSHELL_SHELLS = list(dict.fromkeys(
    shell for shell in (shutil.which("pwsh"), shutil.which("powershell")) if shell
))


def deployer(*parts):
    return ROOT.joinpath("deployers", *parts).read_text(encoding="utf-8")


def resource_block(source, declaration):
    """Extract one Terraform resource without depending on an HCL parser."""
    start = source.index(declaration)
    depth = 0
    for index in range(source.index("{", start), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError(f"Unclosed resource: {declaration}")


def test_entra_initializer_requests_and_consents_to_the_application_permission():
    source = deployer("Initialize-EntraApplication.ps1")
    assert (
        '$directoryReadPermission = @{ Name = "Directory.Read.All"; '
        f'Id = "{GRAPH_DIRECTORY_PERMISSION_ID}"; Type = "Role" }}'
    ) in source
    permissions = source[source.index("$permissions = @("):]
    permissions = permissions[:permissions.index("\n    )")]
    assert permissions.rstrip().endswith("$directoryReadPermission")
    assert '--api-permissions "$($permission.Id)=$($permission.Type)"' in source
    assert f'$microsoftGraphId = "{GRAPH_RESOURCE_APP_ID}"' in source
    region = "#region Grant Directory.Read.All Administrator Consent"
    consent = source[source.index(region):]
    consent = consent[:consent.index("#endregion")]
    for fragment in (
        "Grant-GraphApplicationPermission `", "-GraphUrl $graphUrl `",
        "-ServicePrincipalId $servicePrincipal.id `", "-ResourceAppId $microsoftGraphId `",
        "-AppRoleId $directoryReadPermission.Id",
    ):
        assert fragment in consent
    # Consent needs the service principal, and a refusal only warns so setup can finish.
    assert source.index("$servicePrincipal = ") < source.index("#region Add API Permissions") < source.index(region)
    assert "catch {" in consent and "Write-WarningMessage" in consent


def test_azure_cli_deployer_requests_and_consents_to_the_application_permission():
    source = deployer("azurecli", "deploy-simplechat.ps1")
    request = (
        f"az ad app permission add --id $($appRegistration.id) --api {GRAPH_RESOURCE_APP_ID} "
        f"--api-permissions {GRAPH_DIRECTORY_PERMISSION_ID}=Role"
    )
    grant = '"$paramGraphUrl/v1.0/servicePrincipals/$appServicePrincipalId/appRoleAssignments"'
    assert request in source
    assert f"$graphServicePrincipalId = az ad sp show --id {GRAPH_RESOURCE_APP_ID} --query id -o tsv" in source
    assert "$appServicePrincipalId = az ad sp show --id $($appRegistration.appId) --query id -o tsv" in source
    assert (
        "@{ principalId = $appServicePrincipalId; resourceId = $graphServicePrincipalId; "
        f'appRoleId = "{GRAPH_DIRECTORY_PERMISSION_ID}" }}'
    ) in source
    assert f"az rest --method POST --uri {grant}" in source
    assert "Remove-Item -Path $directoryConsentBodyPath -Force" in source
    assert source.index(request) < source.index(grant)


def test_terraform_requests_and_consents_to_the_application_permission():
    source = deployer("terraform", "main.tf")
    access = resource_block(source, 'resource "azuread_application_api_access" "api_permissions"')
    consent = resource_block(source, 'resource "azuread_app_role_assignment" "msgraph_directory_read_all"')
    role = re.escape('data.azuread_service_principal.msgraph.app_role_ids["Directory.Read.All"]')
    assert re.search(r"role_ids\s*=\s*\[\s*" + role + r"\s*\]", access)
    assert re.search(r"app_role_id\s*=\s*" + role + r"\s*\n", consent)
    assert re.search(
        r"principal_object_id\s*=\s*azuread_service_principal\.app_registration_sp\.object_id\s*\n", consent,
    )
    assert re.search(r"resource_object_id\s*=\s*data\.azuread_service_principal\.msgraph\.object_id\s*\n", consent)


GRANT_HARNESS = r"""
$ErrorActionPreference = 'Stop'
$source = Get-Content -LiteralPath $env:SIMPLECHAT_TEST_DEPLOYER -Raw
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$functions = @($ast.FindAll({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $true))
foreach ($helperName in @('Get-CommandOutputText', 'Invoke-AzureCliJson', 'Grant-GraphApplicationPermission')) {
    $found = @($functions | Where-Object { $_.Name -eq $helperName })
    if ($found.Count -ne 1) { throw "Expected one $helperName helper." }
    . ([scriptblock]::Create($found[0].Extent.Text))
}
$data = $env:SIMPLECHAT_TEST_CASES | ConvertFrom-Json

function Get-ArgumentValue($arguments, $name) {
    $index = [array]::IndexOf($arguments, $name)
    if ($index -lt 0) { throw "Missing argument $name" }
    return $arguments[$index + 1]
}

function az {
    $arguments = [string[]]@($args | ForEach-Object { "$_" })
    $script:calls.Add(($arguments -join ' '))
    $global:LASTEXITCODE = 0
    if (($arguments[0..2] -join ' ') -eq 'ad sp list') {
        if ($script:case.failure -eq 'lookup') {
            $global:LASTEXITCODE = 1
            return 'ERROR: synthetic lookup failure'
        }
        return (ConvertTo-Json -InputObject @($script:case.graphPrincipals) -Depth 8 -Compress)
    }
    if ($arguments[0] -eq 'rest' -and (Get-ArgumentValue $arguments '--method') -eq 'GET') {
        return (ConvertTo-Json -InputObject ([pscustomobject]@{ value = @($script:case.assignments) }) -Depth 8 -Compress)
    }
    if ($arguments[0] -eq 'rest' -and (Get-ArgumentValue $arguments '--method') -eq 'POST') {
        $bodyPath = (Get-ArgumentValue $arguments '--body').Substring(1)
        $script:posts.Add([pscustomobject]@{
            uri = (Get-ArgumentValue $arguments '--uri')
            headers = (Get-ArgumentValue $arguments '--headers')
            output = (Get-ArgumentValue $arguments '--output')
            bodyPath = $bodyPath
            body = [System.IO.File]::ReadAllText($bodyPath)
        })
        if ($script:case.failure -eq 'grant') {
            $global:LASTEXITCODE = 1
            return 'Forbidden: synthetic grant refusal'
        }
        return
    }
    throw "Unexpected Azure CLI call: $($arguments -join ' ')"
}

$results = [System.Collections.Generic.List[object]]::new()
foreach ($case in $data.cases) {
    $script:case = $case
    $script:calls = [System.Collections.Generic.List[string]]::new()
    $script:posts = [System.Collections.Generic.List[object]]::new()
    $outcome = $null
    $failure = $null
    try {
        $outcome = Grant-GraphApplicationPermission -GraphUrl $case.graphUrl `
            -ServicePrincipalId $data.appPrincipalId -ResourceAppId $data.resourceAppId -AppRoleId $data.appRoleId
    }
    catch {
        $failure = $_.Exception.Message
    }
    $results.Add([pscustomobject]@{
        name = $case.name
        outcome = $outcome
        failure = $failure
        calls = [string[]]$script:calls.ToArray()
        posts = [object[]]$script:posts.ToArray()
        bodyFilesRemaining = @($script:posts | Where-Object { Test-Path -LiteralPath $_.bodyPath }).Count
    })
}
ConvertTo-Json -InputObject ([object[]]$results.ToArray()) -Depth 8 -Compress
"""


def grant_case(name, **changes):
    case = {
        "name": name,
        "graphUrl": "https://graph.microsoft.com",
        "graphPrincipals": [{"id": GRAPH_PRINCIPAL, "appId": GRAPH_RESOURCE_APP_ID}],
        "assignments": [
            {"resourceId": GRAPH_PRINCIPAL, "appRoleId": OTHER_ROLE},
            {"resourceId": OTHER_PRINCIPAL, "appRoleId": GRAPH_DIRECTORY_PERMISSION_ID},
        ],
        "failure": "",
    }
    case.update(changes)
    return case


def unwrap_powershell_json(value):
    """Windows PowerShell 5.1 can serialize a wrapped array as {"value": [...], "Count": n}."""
    if isinstance(value, dict):
        if set(value) == {"value", "Count"} and isinstance(value["value"], list):
            return [unwrap_powershell_json(item) for item in value["value"]]
        return {key: unwrap_powershell_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [unwrap_powershell_json(item) for item in value]
    return value


@pytest.mark.skipif(not POWERSHELL_SHELLS, reason="PowerShell is not installed")
@pytest.mark.parametrize("shell", POWERSHELL_SHELLS)
def test_entra_initializer_grants_administrator_consent_once(shell):
    cases = [
        grant_case("granted", graphUrl="https://graph.microsoft.com/"),
        grant_case("granted-sovereign", graphUrl="https://graph.microsoft.us"),
        grant_case("already-granted", assignments=[
            {"resourceId": GRAPH_PRINCIPAL, "appRoleId": OTHER_ROLE},
            {"resourceId": GRAPH_PRINCIPAL, "appRoleId": GRAPH_DIRECTORY_PERMISSION_ID},
        ]),
        grant_case("no-assignments", assignments=[]),
        grant_case("grant-refused", failure="grant"),
        grant_case("lookup-failed", failure="lookup"),
        grant_case("no-graph-principal", graphPrincipals=[]),
    ]
    environment = os.environ.copy()
    environment["SIMPLECHAT_TEST_DEPLOYER"] = str(ROOT / "deployers" / "Initialize-EntraApplication.ps1")
    environment["SIMPLECHAT_TEST_CASES"] = json.dumps({
        "appPrincipalId": APP_PRINCIPAL,
        "resourceAppId": GRAPH_RESOURCE_APP_ID,
        "appRoleId": GRAPH_DIRECTORY_PERMISSION_ID,
        "cases": cases,
    })
    result = subprocess.run(
        [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
         "& ([scriptblock]::Create([Console]::In.ReadToEnd()))"],
        input=GRANT_HARNESS, capture_output=True, text=True, env=environment, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    outcomes = {item["name"]: item for item in unwrap_powershell_json(json.loads(result.stdout))}
    assert set(outcomes) == {case["name"] for case in cases}
    lookup = f"ad sp list --filter appId eq '{GRAPH_RESOURCE_APP_ID}' --output json --only-show-errors"

    def assignments_uri(base):
        return f"{base}/v1.0/servicePrincipals/{APP_PRINCIPAL}/appRoleAssignments"

    expected_body = {"principalId": APP_PRINCIPAL, "resourceId": GRAPH_PRINCIPAL, "appRoleId": GRAPH_DIRECTORY_PERMISSION_ID}
    for name, base in (
        ("granted", "https://graph.microsoft.com"),
        ("granted-sovereign", "https://graph.microsoft.us"),
        ("no-assignments", "https://graph.microsoft.com"),
    ):
        outcome = outcomes[name]
        assert outcome["failure"] is None, name
        assert outcome["outcome"] == "Granted", name
        assert outcome["calls"][0] == lookup
        assert outcome["calls"][1] == (
            f"rest --method GET --uri {assignments_uri(base)} --output json --only-show-errors"
        )
        [post] = outcome["posts"]
        assert post["uri"] == assignments_uri(base)
        assert post["headers"] == "Content-Type=application/json"
        assert post["output"] == "none"
        assert json.loads(post["body"]) == expected_body
        assert outcome["bodyFilesRemaining"] == 0
    already = outcomes["already-granted"]
    assert already["outcome"] == "AlreadyGranted" and already["failure"] is None
    assert already["posts"] == [] and len(already["calls"]) == 2
    refused = outcomes["grant-refused"]
    assert refused["outcome"] is None
    assert refused["failure"] == "Azure CLI returned: Forbidden: synthetic grant refusal"
    assert len(refused["posts"]) == 1 and refused["bodyFilesRemaining"] == 0
    lookup_failed = outcomes["lookup-failed"]
    assert lookup_failed["failure"] == (
        f"Find the service principal for API '{GRAPH_RESOURCE_APP_ID}' failed. "
        "Azure CLI returned: ERROR: synthetic lookup failure"
    )
    assert lookup_failed["calls"] == [lookup] and lookup_failed["posts"] == []
    missing = outcomes["no-graph-principal"]
    assert missing["failure"] == f"No service principal for API '{GRAPH_RESOURCE_APP_ID}' exists in this tenant."
    assert missing["calls"] == [lookup] and missing["posts"] == []


# --------------------------------------------------------------------------------------
# Admin Settings markup and browser module
# --------------------------------------------------------------------------------------

JS_MODULE = APP / "static" / "js" / "admin" / "admin_orchestration_directory_access.js"
NODE = shutil.which("node")
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
STATE_ORDER = ["permission_missing", "sign_in_failed", "unverified"]
PERMISSION_SUMMARY = (
    "Chat Orchestration can't verify that users may use web search, because this app registration "
    "doesn't have the Microsoft Graph Directory.Read.All permission."
)
SIGN_IN_SUMMARY = (
    "Chat Orchestration can't verify that users may use web search, because Microsoft Entra ID "
    "refused SimpleChat's application sign-in."
)
FIX_COMMANDS = (
    f"az ad app permission add --id {APP_ID} --api {GRAPH_RESOURCE_APP_ID} "
    f"--api-permissions {GRAPH_DIRECTORY_PERMISSION_ID}=Role\n"
    f"az ad app permission admin-consent --id {APP_ID}"
)


class Element:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children = []
        self.text = []

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def select(self, predicate):
        return [element for element in self.walk() if predicate(element)]

    def with_attribute(self, name):
        return self.select(lambda element: name in element.attrs)

    def classes(self):
        return set(self.attrs.get("class", "").split())

    def ancestors(self):
        parent = self.parent
        while parent is not None:
            yield parent
            parent = parent.parent

    def to_json(self):
        return {
            "tag": self.tag, "attrs": dict(self.attrs), "text": "".join(self.text).strip(),
            "children": [child.to_json() for child in self.children],
        }


class TemplateTree(HTMLParser):
    """A tolerant element tree for Jinja templates: stray end tags are ignored."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Element("#document", {}, None)
        self.stack = [self.root]
        self.feed(text)
        self.close()

    def _element(self, tag, attrs):
        element = Element(tag, {name: "" if value is None else value for name, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(element)
        return element

    def handle_starttag(self, tag, attrs):
        element = self._element(tag, attrs)
        if tag not in VOID_TAGS:
            self.stack.append(element)

    def handle_startendtag(self, tag, attrs):
        self._element(tag, attrs)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        self.stack[-1].text.append(data)


def template(*parts):
    return TemplateTree(APP.joinpath("templates", *parts).read_text(encoding="utf-8")).root


def by_id(root, element_id):
    [element] = root.select(lambda element: element.attrs.get("id") == element_id)
    return element


def js_source():
    return JS_MODULE.read_text(encoding="utf-8")


def js_problem_states():
    match = re.search(r"export const PROBLEM_STATES = Object\.freeze\(\[([^\]]*)\]\);", js_source())
    assert match
    return re.findall(r'"([a-z_]+)"', match.group(1))


def test_orchestration_pane_explains_each_directory_problem():
    alert = by_id(template("admin", "_panes", "chat-orchestration.html"), "chat-orchestration-directory-access-alert")
    assert alert.tag == "div"
    assert {"alert", "alert-warning", "d-none"} <= alert.classes()
    assert alert.attrs.get("role") == "status" and alert.attrs.get("aria-live") == "polite"
    # The notification links to /admin/settings#chat-orchestration, the pane that holds this guidance.
    pane = next(element for element in alert.ancestors() if "tab-pane" in element.classes())
    assert pane.attrs["id"] == "chat-orchestration"
    states = alert.with_attribute("data-directory-access-state")
    assert [state.attrs["data-directory-access-state"] for state in states] == STATE_ORDER == js_problem_states()
    assert all("d-none" in state.classes() for state in states)
    for state in states:
        [capabilities] = state.with_attribute("data-directory-access-capabilities")
        assert capabilities.tag == "span"
    permission, sign_in, _unverified = states
    [commands] = alert.with_attribute("data-directory-access-commands")
    assert commands.tag == "code" and commands.parent.tag == "pre" and commands in list(permission.walk())
    permission_text = " ".join(" ".join(element.text) for element in permission.walk())
    assert "Directory.Read.All" in permission_text and "Grant admin consent" in permission_text
    assert "MICROSOFT_PROVIDER_AUTHENTICATION_SECRET" in " ".join(" ".join(element.text) for element in sign_in.walk())
    [button] = alert.with_attribute("data-directory-access-recheck")
    assert button.tag == "button" and button.attrs.get("type") == "button"
    [detail] = alert.with_attribute("data-directory-access-detail")
    assert detail.tag == "span"
    assert not any(
        name == "style" or name.startswith("on") for element in alert.walk() for name in element.attrs
    )


def test_web_search_pane_points_to_the_fix():
    alert = by_id(template("admin", "_panes", "web-research.html"), "web-search-directory-access-alert")
    assert {"alert", "alert-warning", "d-none"} <= alert.classes()
    assert alert.attrs.get("role") == "status" and alert.attrs.get("aria-live") == "polite"
    [summary] = alert.with_attribute("data-directory-access-summary")
    assert summary.tag == "span"
    [link] = alert.select(lambda element: element.tag == "a")
    assert link.attrs == {
        "href": "#chat-orchestration-directory-access-alert",
        "data-admin-link": "chat-orchestration-directory-access-alert",
    }
    assert not any(
        name == "style" or name.startswith("on") for element in alert.walk() for name in element.attrs
    )


def test_admin_settings_loads_the_local_module():
    page = APP.joinpath("templates", "admin_settings.html").read_text(encoding="utf-8")
    tag = (
        '<script type="module" src="{{ url_for(\'static\', '
        "filename='js/admin/admin_orchestration_directory_access.js') }}?v={{ config['VERSION'] }}\"></script>"
    )
    assert page.count(tag) == 1
    assert "js/admin/admin_card_links.js" in page
    assert JS_MODULE.is_file()


def test_browser_module_writes_text_only_and_calls_the_admin_route():
    source = js_source()
    routes = APP.joinpath("route_frontend_admin_settings.py").read_text(encoding="utf-8")
    assert source.startswith("// admin_orchestration_directory_access.js\n")
    assert "\t" not in source
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
                      "import(", "http://", "https://", "style.display"):
        assert forbidden not in source, forbidden
    assert re.search(r"\balert\s*\(", source) is None
    assert re.search(r'const CHECK_URL = "([^"]+)";', source).group(1) == CHECK_URL
    assert f"@bp.route('{CHECK_URL}', methods=['POST'])" in routes
    assert f'const GRAPH_RESOURCE_APP_ID = "{GRAPH_RESOURCE_APP_ID}";' in source
    assert f'const GRAPH_DIRECTORY_PERMISSION_ID = "{GRAPH_DIRECTORY_PERMISSION_ID}";' in source


NODE_HARNESS = r"""
import { readFileSync } from "node:fs";

const input = JSON.parse(readFileSync(0, "utf8"));
const source = readFileSync(input.modulePath, "utf8");
const warnings = [];
console.warn = (...args) => {
    warnings.push(args.map((arg) => (arg instanceof Error ? arg.message : String(arg))).join(" | "));
};

class FakeClassList {
    constructor(names) { this.names = new Set(names); }
    toggle(name, force) {
        const present = force === undefined ? !this.names.has(name) : Boolean(force);
        if (present) { this.names.add(name); } else { this.names.delete(name); }
        return present;
    }
    contains(name) { return this.names.has(name); }
}

class FakeElement {
    constructor(spec) {
        this.tag = spec.tag;
        this.attributes = { ...spec.attrs };
        this.children = spec.children.map((child) => new FakeElement(child));
        this.classList = new FakeClassList((spec.attrs.class || "").split(/\s+/).filter(Boolean));
        this.listeners = {};
        this.disabled = false;
        this.text = spec.text;
    }
    get textContent() { return this.text; }
    set textContent(value) { this.text = String(value); }
    get innerHTML() { throw new Error("innerHTML is not allowed"); }
    set innerHTML(_value) { throw new Error("innerHTML is not allowed"); }
    getAttribute(name) { return Object.hasOwn(this.attributes, name) ? this.attributes[name] : null; }
    *descendants() { for (const child of this.children) { yield child; yield* child.descendants(); } }
    querySelectorAll(selector) {
        const match = /^\[([a-z-]+)\]$/.exec(selector);
        if (!match) { throw new Error(`Unsupported selector ${selector}`); }
        return [...this.descendants()].filter((element) => Object.hasOwn(element.attributes, match[1]));
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
    click() { for (const listener of this.listeners.click || []) { listener({ type: "click" }); } }
}

function makePage({ alert = true, webSearch = true } = {}) {
    const page = {
        alert: alert ? new FakeElement(input.alert) : null,
        webSearch: webSearch ? new FakeElement(input.webSearchAlert) : null,
        byId: new Map(),
    };
    for (const root of [page.alert, page.webSearch]) {
        if (!root) { continue; }
        for (const element of [root, ...root.descendants()]) {
            if (element.attributes.id) { page.byId.set(element.attributes.id, element); }
        }
    }
    return page;
}

function makeDocument(page, readyState = "complete") {
    const listeners = {};
    return {
        readyState,
        listeners,
        getElementById: (id) => page.byId.get(id) || null,
        addEventListener(type, listener) { (listeners[type] ||= []).push(listener); },
    };
}

function texts(root, attribute) {
    return root ? root.querySelectorAll(`[${attribute}]`).map((element) => element.textContent) : [];
}

function snapshot(page) {
    const alert = page.alert;
    return {
        alertHidden: alert ? alert.classList.contains("d-none") : null,
        visibleStates: alert ? alert.querySelectorAll("[data-directory-access-state]")
            .filter((block) => !block.classList.contains("d-none"))
            .map((block) => block.getAttribute("data-directory-access-state")) : [],
        capabilities: texts(alert, "data-directory-access-capabilities"),
        commands: texts(alert, "data-directory-access-commands"),
        detail: texts(alert, "data-directory-access-detail"),
        buttonDisabled: alert ? alert.querySelectorAll("[data-directory-access-recheck]").map((b) => b.disabled) : [],
        webSearchHidden: page.webSearch ? page.webSearch.classList.contains("d-none") : null,
        summary: texts(page.webSearch, "data-directory-access-summary"),
    };
}

let instance = 0;
function loadModule() {
    instance += 1;
    const encoded = Buffer.from(`${source}\n// test instance ${instance}\n`).toString("base64");
    return import(`data:text/javascript;base64,${encoded}`);
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const requests = [];
let reply = null;
let activePage = null;
globalThis.fetch = async (url, options) => {
    const alert = activePage?.alert;
    requests.push({
        url,
        method: options.method,
        headers: options.headers,
        credentials: options.credentials,
        body: options.body,
        buttonDisabled: alert ? alert.querySelector("[data-directory-access-recheck]").disabled : null,
        detail: alert ? alert.querySelector("[data-directory-access-detail]").textContent : null,
    });
    if (reply.networkError) { throw new Error(reply.networkError); }
    const current = reply;
    return { ok: current.ok, status: current.status, json: async () => current.body };
};

const results = { renders: {}, checks: {}, init: {} };

activePage = makePage({ alert: false, webSearch: false });
globalThis.document = makeDocument(activePage);
const module = await loadModule();
await settle();
results.problemStates = [...module.PROBLEM_STATES];
results.requestsWithoutAlert = requests.length;

for (const [name, reports] of Object.entries(input.renders)) {
    const page = makePage();
    for (const report of reports) {
        module.renderDirectoryAccess(report, makeDocument(page));
    }
    results.renders[name] = snapshot(page);
}
results.sources = input.sources.map((capabilities) => module.directoryAccessSources(capabilities));
results.commands = input.commandReports.map((report) => module.directoryAccessCommands(report));

for (const [name, scenario] of Object.entries(input.checks)) {
    const page = makePage();
    activePage = page;
    globalThis.document = makeDocument(page);
    if (scenario.initial) { module.renderDirectoryAccess(scenario.initial); }
    const before = snapshot(page);
    reply = scenario.reply;
    const start = requests.length;
    const warningStart = warnings.length;
    const returned = await (scenario.options
        ? module.checkDirectoryAccess(scenario.options)
        : module.checkDirectoryAccess());
    results.checks[name] = {
        returned, before, page: snapshot(page),
        requests: requests.slice(start), warnings: warnings.slice(warningStart),
    };
}

{
    const page = makePage();
    activePage = page;
    const loading = makeDocument(page, "loading");
    globalThis.document = loading;
    reply = { ok: true, status: 200, body: input.readyReport };
    const start = requests.length;
    await loadModule();
    await settle();
    const beforeLoaded = requests.length - start;
    const listeners = loading.listeners.DOMContentLoaded || [];
    listeners.forEach((listener) => listener());
    await settle();
    page.alert.querySelector("[data-directory-access-recheck]").click();
    await settle();
    results.init.loading = {
        beforeLoaded, listeners: listeners.length,
        bodies: requests.slice(start).map((request) => request.body),
    };
}
{
    const page = makePage();
    activePage = page;
    globalThis.document = makeDocument(page, "complete");
    reply = { ok: true, status: 200, body: input.problemReport };
    const start = requests.length;
    await loadModule();
    await settle();
    results.init.complete = { bodies: requests.slice(start).map((request) => request.body), page: snapshot(page) };
}
{
    const page = makePage({ alert: false });
    activePage = page;
    globalThis.document = makeDocument(page, "complete");
    const start = requests.length;
    await loadModule();
    await settle();
    results.init.withoutAlert = requests.length - start;
}

process.stdout.write(JSON.stringify({ results, warnings }));
"""


def js_report(**changes):
    report = {
        "success": True, "status": "permission_missing", "required": True,
        "reason": DIRECTORY_PERMISSION_MISSING, "capabilities": EXPECTED_SOURCES[:3],
        "web_search_enabled": True, "application_client_id": APP_ID,
        "graph_permission": GRAPH_DIRECTORY_PERMISSION, "graph_permission_id": GRAPH_DIRECTORY_PERMISSION_ID,
        "graph_resource_app_id": GRAPH_RESOURCE_APP_ID, "checked_at": "2026-05-06T12:00:00+00:00",
    }
    report.update(changes)
    return report


@pytest.fixture(scope="module")
def browser_run():
    if NODE is None:
        pytest.skip("Node.js is not installed")
    orchestration = template("admin", "_panes", "chat-orchestration.html")
    web_research = template("admin", "_panes", "web-research.html")
    failure = {"ok": False, "status": 500, "body": {
        "success": False, "error": "The directory access check could not be completed.",
    }}
    hostile = "<img src=x onerror=alert(1)>"
    payload = {
        "modulePath": str(JS_MODULE),
        "alert": by_id(orchestration, "chat-orchestration-directory-access-alert").to_json(),
        "webSearchAlert": by_id(web_research, "web-search-directory-access-alert").to_json(),
        "readyReport": js_report(status="ready", reason=None),
        "problemReport": js_report(),
        "renders": {
            "permission": [js_report()],
            "sign_in": [js_report(status="sign_in_failed", reason=DIRECTORY_SIGN_IN_FAILED)],
            "unverified": [js_report(status="unverified", reason="external_identity_timeout")],
            "unverified_undated": [js_report(status="unverified", reason="external_identity_timeout", checked_at="soon")],
            "without_web_search": [js_report(web_search_enabled=False, capabilities=[EXPECTED_SOURCES[1]])],
            "fixed": [js_report(), js_report(status="ready", reason=None)],
            "not_required": [js_report(status="not_required", reason=None, checked_at=None)],
            "unknown_status": [js_report(status=hostile)],
            "inherited_status": [js_report(status="constructor")],
            "empty": [None],
            "hostile_values": [js_report(
                application_client_id=hostile, graph_resource_app_id=hostile, graph_permission_id=hostile,
                capabilities=[{"id": hostile, "label": hostile}], checked_at=hostile,
            )],
        },
        "sources": [
            None, [], [EXPECTED_SOURCES[0]], EXPECTED_SOURCES[:2], EXPECTED_SOURCES,
            [{"id": "compose"}, EXPECTED_SOURCES[3], None],
            [{"id": "constructor"}, {"id": "__proto__"}, {"id": "toString"}],
        ],
        "commandReports": [js_report(), js_report(application_client_id=APP_ID.upper()), {}, None],
        "checks": {
            "refresh_found_problem": {"options": {"refresh": True}, "reply": {"ok": True, "status": 200, "body": js_report()}},
            "page_load": {"options": None, "reply": {"ok": True, "status": 200, "body": js_report(status="ready", reason=None)}},
            "refresh_failed": {"options": {"refresh": True}, "initial": js_report(), "reply": failure},
            "page_load_failed": {"options": None, "initial": js_report(), "reply": failure},
            "unsuccessful_payload": {"options": {"refresh": True}, "reply": {
                "ok": True, "status": 200, "body": {"success": False, "error": "synthetic"},
            }},
            "network_error": {"options": {"refresh": True}, "reply": {"networkError": "synthetic network failure"}},
        },
    }
    result = subprocess.run(
        [NODE, "--input-type=module", "--eval", NODE_HARNESS],
        input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
        timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


def test_browser_module_shows_the_matching_guidance(browser_run):
    renders = browser_run["results"]["renders"]
    hidden = {
        "alertHidden": True, "visibleStates": [], "detail": [""], "buttonDisabled": [False], "webSearchHidden": True,
    }
    permission = renders["permission"]
    assert permission["alertHidden"] is False
    assert permission["visibleStates"] == ["permission_missing"]
    assert permission["capabilities"] == ["web search, linked pages or deep research"] * 3
    assert permission["commands"] == [FIX_COMMANDS]
    [detail] = permission["detail"]
    assert detail.startswith("Checked ") and detail.endswith(".") and "Reason" not in detail
    assert permission["webSearchHidden"] is False and permission["summary"] == [PERMISSION_SUMMARY]
    sign_in = renders["sign_in"]
    assert sign_in["visibleStates"] == ["sign_in_failed"] and sign_in["summary"] == [SIGN_IN_SUMMARY]
    assert sign_in["webSearchHidden"] is False
    unverified = renders["unverified"]
    assert unverified["visibleStates"] == ["unverified"] and unverified["webSearchHidden"] is True
    assert unverified["detail"][0].startswith("Reason: external_identity_timeout. Checked ")
    assert renders["unverified_undated"]["detail"] == ["Reason: external_identity_timeout."]
    without_web_search = renders["without_web_search"]
    assert without_web_search["alertHidden"] is False and without_web_search["webSearchHidden"] is True
    assert without_web_search["capabilities"] == ["linked pages"] * 3
    for name in ("fixed", "not_required", "unknown_status", "inherited_status", "empty"):
        assert {key: renders[name][key] for key in hidden} == hidden, name
    hostile = renders["hostile_values"]
    assert hostile["capabilities"] == ["web search or another external source"] * 3
    assert hostile["commands"] == [
        f"az ad app permission add --id <application-client-id> --api {GRAPH_RESOURCE_APP_ID} "
        f"--api-permissions {GRAPH_DIRECTORY_PERMISSION_ID}=Role\n"
        "az ad app permission admin-consent --id <application-client-id>"
    ]
    assert hostile["detail"] == [""]
    assert "onerror" not in json.dumps(renders)


def test_browser_module_names_sources_and_fix_commands(browser_run):
    results = browser_run["results"]
    assert results["problemStates"] == STATE_ORDER
    assert results["sources"] == [
        "web search or another external source",
        "web search or another external source",
        "web search",
        "web search or linked pages",
        "web search, linked pages, deep research, agents or actions",
        "agents",
        "web search or another external source",
    ]
    placeholder = FIX_COMMANDS.replace(APP_ID, "<application-client-id>")
    assert results["commands"] == [
        FIX_COMMANDS, FIX_COMMANDS.replace(APP_ID, APP_ID.upper()), placeholder, placeholder,
    ]


def test_browser_module_checks_on_load_and_rechecks_on_request(browser_run):
    results = browser_run["results"]
    checks = results["checks"]
    found = checks["refresh_found_problem"]
    [request] = found["requests"]
    assert request == {
        "url": CHECK_URL, "method": "POST",
        "headers": {"Accept": "application/json", "Content-Type": "application/json"},
        "credentials": "same-origin", "body": json.dumps({"refresh": True}, separators=(",", ":")),
        "buttonDisabled": True, "detail": "Checking...",
    }
    assert found["returned"]["status"] == "permission_missing"
    assert found["page"]["visibleStates"] == ["permission_missing"] and found["page"]["buttonDisabled"] == [False]
    assert found["warnings"] == []
    page_load = checks["page_load"]
    assert [item["body"] for item in page_load["requests"]] == ['{"refresh":false}']
    assert page_load["requests"][0]["detail"] == ""
    assert page_load["page"]["alertHidden"] is True
    refresh_failed = checks["refresh_failed"]
    assert refresh_failed["returned"] is None
    assert refresh_failed["page"]["visibleStates"] == ["permission_missing"]
    assert refresh_failed["page"]["detail"] == ["The check could not be completed. Try again."]
    assert refresh_failed["page"]["buttonDisabled"] == [False]
    assert refresh_failed["warnings"] == [
        "Chat Orchestration directory access check failed. | The directory access check could not be completed."
    ]
    page_load_failed = checks["page_load_failed"]
    assert page_load_failed["returned"] is None
    assert page_load_failed["page"] == page_load_failed["before"]
    assert len(page_load_failed["warnings"]) == 1
    for name in ("unsuccessful_payload", "network_error"):
        assert checks[name]["returned"] is None, name
        assert checks[name]["page"]["detail"] == ["The check could not be completed. Try again."], name
        assert len(checks[name]["warnings"]) == 1, name
    assert results["requestsWithoutAlert"] == 0
    loading = results["init"]["loading"]
    assert loading["beforeLoaded"] == 0 and loading["listeners"] == 1
    assert loading["bodies"] == ['{"refresh":false}', '{"refresh":true}']
    complete = results["init"]["complete"]
    assert complete["bodies"] == ['{"refresh":false}']
    assert complete["page"]["visibleStates"] == ["permission_missing"]
    assert results["init"]["withoutAlert"] == 0
