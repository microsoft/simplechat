# test_workflow_background_identity.py
"""
Functional test for scheduled workflow runs acting with their owner's identity.
Version: 0.261.218
Implemented in: 0.261.218

A scheduled workflow run has no signed-in session, so the runner gave it one that held
only the owner's object ID. Groups and messages the run created showed that ID instead
of a name, and the ID was written over the owner's stored display name. The SimpleChat
action also could not add group members or invite them to a group conversation: both
looked people up in Microsoft Graph with a signed-in token that the run does not have.

- The run's session carries the owner's stored display name and email, read without
  writing the owner's settings.
- A user_id given with an email or display name resolves without a directory lookup, as
  the REST members route already relies on. add_user_to_group now accepts one.
- A group conversation invite matches the group's current members by ID, email or
  display name before it falls back to the directory.

Each check runs the application's own definitions from source. Only storage, Microsoft
Graph and the collaboration store are modelled.
"""

import copy
import logging
import re
import sys
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional
from unittest.mock import patch

import pytest
from azure.core.exceptions import AzureError
from azure.cosmos import exceptions as cosmos_exceptions
from flask import Flask, g, has_request_context, session

from test_support.app_source import refusing_module_stub, run_definitions


OWNER_ID = "owner-1"
OWNER_EMAIL = "fiona.owner@example.test"
OWNER_PROFILE = {"id": OWNER_ID, "display_name": "Fiona Owner", "email": OWNER_EMAIL, "settings": {}}
OWNER_SESSION = {"oid": OWNER_ID, "roles": ["User"], "preferred_username": OWNER_EMAIL, "name": "Fiona Owner"}
BARE_SESSION = {"oid": OWNER_ID, "roles": ["User"], "preferred_username": "", "name": OWNER_ID}

GROUP = {
    "id": "group-1",
    "name": "Regional Response Team",
    "owner": {"id": OWNER_ID, "email": OWNER_EMAIL, "displayName": "Fiona Owner"},
    "users": [
        {"userId": OWNER_ID, "email": OWNER_EMAIL, "displayName": "Fiona Owner"},
        {"userId": "member-1", "email": "ada.admin@example.test", "displayName": "Ada Admin"},
        {"userId": "member-2", "email": "sam.lead@example.test", "displayName": "Sam Lead"},
        {"userId": "member-3", "email": "jo.editor@example.test", "displayName": "Jo Editor"},
        {"userId": "twin-1", "email": "alex.one@example.test", "displayName": "Alex Analyst"},
        {"userId": "twin-2", "email": "alex.two@example.test", "displayName": "Alex Analyst"},
    ],
}
CONVERSATION = {
    "id": "conversation-1",
    "chat_type": "group_multi_user",
    "title": "Incident 1 Coordination",
    "scope": {"group_id": "group-1", "group_name": "Regional Response Team"},
}


class UserSettingsContainer:
    """Stored user settings, which a background run may read but never write."""

    def __init__(self, docs):
        self.docs = docs
        self.error = None
        self.reads = []

    def read_item(self, item, partition_key):
        self.reads.append(item)
        if self.error is not None:
            raise self.error
        if item not in self.docs:
            raise cosmos_exceptions.CosmosResourceNotFoundError(status_code=404, message="Not found")
        return copy.deepcopy(self.docs[item])

    def upsert_item(self, *args, **kwargs):
        raise AssertionError("A background run wrote the owner's settings")


def refuse_directory(*args, **kwargs):
    # A scheduled run has no signed-in token, so every Graph directory call fails like this.
    raise PermissionError("Could not acquire access token")


@pytest.fixture
def runner():
    logs = []
    container = UserSettingsContainer({OWNER_ID: copy.deepcopy(OWNER_PROFILE)})

    def log_event(*args, **kwargs):
        logs.append((args, kwargs))

    settings = run_definitions("functions_settings.py", {
        "USER_SETTINGS_REQUEST_CACHE_ATTR", "read_user_settings_snapshot", "_authorize_user_settings_access",
        "_get_user_settings_request_cache", "_get_request_cached_user_settings", "_clone_user_settings_doc",
    }, {
        "copy": copy, "logging": logging, "g": g, "has_request_context": has_request_context,
        "exceptions": cosmos_exceptions, "cosmos_user_settings_container": container, "log_event": log_event,
    })
    namespace = run_definitions("functions_workflow_runner.py", {
        "_workflow_runner_app", "_get_workflow_runner_app", "_workflow_owner_identity", "_ensure_execution_context",
    }, {
        "Flask": Flask, "SECRET_KEY": "test-secret", "session": session, "has_request_context": has_request_context,
        "contextmanager": contextmanager, "AzureError": AzureError, "logging": logging, "log_event": log_event,
        "read_user_settings_snapshot": settings["read_user_settings_snapshot"],
    })
    # A cross-user settings read inside another member's request would consult the signed-in user.
    authentication = refusing_module_stub(
        "functions_authentication.py", "functions_authentication",
        get_current_user_id=lambda: (session.get("user") or {}).get("oid"),
    )
    with patch.dict(sys.modules, {"functions_authentication": authentication}):
        yield SimpleNamespace(context=namespace["_ensure_execution_context"], container=container, logs=logs)


def session_user_inside(runner, user_id):
    with runner.context(user_id):
        return dict(session["user"])


def signed_in_request(user):
    app = Flask("signed_in_request")
    app.secret_key = "test-secret"
    context = app.test_request_context("/api/user/workflows/workflow-1/run")
    context.push()
    session["user"] = dict(user)
    return context


def test_a_scheduled_run_acts_with_the_owners_stored_name_and_email(runner):
    assert not has_request_context()
    assert session_user_inside(runner, OWNER_ID) == OWNER_SESSION
    assert runner.container.reads == [OWNER_ID]
    assert not has_request_context()


def test_an_owner_without_a_stored_profile_keeps_the_bare_identity(runner):
    runner.container.docs.clear()
    assert session_user_inside(runner, OWNER_ID) == BARE_SESSION


def test_an_unavailable_settings_store_falls_back_to_the_bare_identity(runner):
    runner.container.error = cosmos_exceptions.CosmosHttpResponseError(status_code=503, message="Unavailable")
    assert session_user_inside(runner, OWNER_ID) == BARE_SESSION
    assert [(args[0], kwargs.get("extra"), kwargs.get("level")) for args, kwargs in runner.logs] == [(
        "[WorkflowRunner] Owner profile unavailable for a background run",
        {"user_id": OWNER_ID, "error_type": "CosmosHttpResponseError"},
        logging.WARNING,
    )]


def test_a_run_inside_the_owners_signed_in_request_keeps_that_session(runner):
    signed_in = {"oid": OWNER_ID, "roles": ["User", "WorkflowUser"], "preferred_username": OWNER_EMAIL, "name": "Fiona"}
    context = signed_in_request(signed_in)
    try:
        assert session_user_inside(runner, OWNER_ID) == signed_in
        assert session["user"] == signed_in
    finally:
        context.pop()
    assert runner.container.reads == []


def test_a_run_inside_another_members_request_acts_as_the_owner(runner):
    member = {"oid": "member-2", "roles": ["User"], "preferred_username": "max@example.test", "name": "Max Member"}
    context = signed_in_request(member)
    try:
        assert session_user_inside(runner, OWNER_ID) == OWNER_SESSION
        assert session["user"] == member
    finally:
        context.pop()


@pytest.fixture
def operations():
    invited = []
    models = run_definitions("collaboration_models.py", {"_clean_string", "normalize_collaboration_user"}, {})

    def invite(conversation_id, owner_user_id, participants_to_add):
        invited.append((conversation_id, owner_user_id, copy.deepcopy(participants_to_add)))
        return copy.deepcopy(CONVERSATION), [
            {
                "user_id": participant["user_id"], "user_display_name": participant["display_name"],
                "user_email": participant["email"], "membership_status": "pending",
            }
            for participant in participants_to_add
        ]

    namespace = run_definitions("functions_simplechat_operations.py", {
        "CONVERSATION_ACCESS_ERROR", "invite_group_conversation_members_for_current_user",
        "_build_invited_participants", "_group_member_summaries", "_match_group_member",
        "_split_participant_identifiers", "resolve_directory_user",
    }, {
        "Any": Any, "Dict": Dict, "Iterable": Iterable, "List": List, "Optional": Optional, "re": re,
        "normalize_collaboration_user": models["normalize_collaboration_user"],
        "_require_collaboration_feature_enabled": lambda: {},
        "_require_current_user_info": lambda: {"userId": OWNER_ID, "email": OWNER_EMAIL, "displayName": "Fiona Owner"},
        "get_collaboration_conversation": lambda conversation_id: copy.deepcopy(CONVERSATION),
        "CosmosResourceNotFoundError": cosmos_exceptions.CosmosResourceNotFoundError,
        "is_group_collaboration_conversation": lambda doc: (doc or {}).get("chat_type") == "group_multi_user",
        "find_group_by_id": lambda group_id: copy.deepcopy(GROUP) if group_id == "group-1" else None,
        "invite_personal_collaboration_participants": invite,
        "_get_directory_user_by_id": refuse_directory,
        "_find_directory_users_by_email": refuse_directory,
        "search_directory_users": refuse_directory,
    })
    return SimpleNamespace(namespace=namespace, invited=invited)


def test_a_known_object_id_with_an_email_needs_no_directory_lookup(operations):
    resolved = operations.namespace["resolve_directory_user"](
        user_id="member-1", email="ada.admin@example.test", display_name="Ada Admin",
    )
    assert resolved == {"id": "member-1", "displayName": "Ada Admin", "email": "ada.admin@example.test"}


def test_invites_match_current_group_members_without_a_directory_lookup(operations):
    result = operations.namespace["invite_group_conversation_members_for_current_user"](
        conversation_id="conversation-1",
        participant_identifiers=f" ADA.ADMIN@example.test , member-2\nJo Editor; {OWNER_EMAIL}",
    )
    assert operations.invited == [("conversation-1", OWNER_ID, [
        {"user_id": "member-1", "display_name": "Ada Admin", "email": "ada.admin@example.test"},
        {"user_id": "member-2", "display_name": "Sam Lead", "email": "sam.lead@example.test"},
        {"user_id": "member-3", "display_name": "Jo Editor", "email": "jo.editor@example.test"},
    ])]
    assert [participant["user_id"] for participant in result["invited_participants"]] == ["member-1", "member-2", "member-3"]


@pytest.mark.parametrize("identifier", ["Alex Analyst", "outsider@example.test"])
def test_an_identifier_naming_several_members_or_none_is_left_to_the_directory(operations, identifier):
    with pytest.raises(PermissionError, match="Could not acquire access token"):
        operations.namespace["invite_group_conversation_members_for_current_user"](
            conversation_id="conversation-1", participant_identifiers=identifier,
        )
    assert operations.invited == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
