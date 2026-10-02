#!/usr/bin/env python3
# test_workflow_chat_delivery_notice_and_unread.py
"""
Functional test for workflow chat delivery notices and unread marks.
Version: 0.261.218
Implemented in: 0.261.218

This test ensures chat-started workflow delivery notifications stay idempotent and guarded unread marks preserve owner-scoped conversation state.
"""

import copy
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "application" / "single_app", ROOT / "functional_tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402

from functions_conversation_unread import (  # noqa: E402
    UNREAD_ALREADY_MARKED,
    UNREAD_CONFLICT,
    UNREAD_MARKED,
    UNREAD_NOT_FOUND,
    UNREAD_READ_SINCE,
    UNREAD_UNAVAILABLE,
    mark_conversation_unread_guarded,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_chat_delivery_fakes import (  # noqa: E402
    CONVERSATION_ID,
    OTHER_USER,
    REQUESTED_AT,
    USER,
    FakeContainer,
    cosmos_error,
    make_conversation,
    require,
    shift,
)


MESSAGE_ID = "assistant-workflow-result-1"
PLANNED_AT = shift(REQUESTED_AT, minutes=10)


class FakeConfigCosmosDatabase:
    """Minimal database stand-in for config.py import-time container setup."""

    def __init__(self):
        self.containers = {}

    def create_container_if_not_exists(self, id, **kwargs):
        if id not in self.containers:
            self.containers[id] = FakeContainer(id)
        return self.containers[id]


class FakeConfigCosmosClient:
    """Minimal Cosmos client stand-in that never opens a network connection."""

    def __init__(self, *args, **kwargs):
        self.database = FakeConfigCosmosDatabase()

    def create_database_if_not_exists(self, *args, **kwargs):
        return self.database


APP_DIR = (ROOT / "application" / "single_app").resolve()


def is_app_module(module):
    location = getattr(module, "__file__", None)
    if not location:
        return False
    try:
        return Path(location).resolve().is_relative_to(APP_DIR)
    except (OSError, ValueError):
        return False


@pytest.fixture(scope="module", autouse=True)
def forget_app_modules_imported_here():
    # config.py binds its containers on first import, so a later file must not inherit these fake ones.
    before = set(sys.modules)
    yield
    added = [name for name, module in list(sys.modules.items()) if name not in before and is_app_module(module)]
    for name in added:
        sys.modules.pop(name, None)


def import_app_module_without_live_cosmos(module_name):
    """Import an app module while config.py sees only fake Cosmos clients."""
    if module_name in sys.modules:
        return sys.modules[module_name]

    import azure.cosmos as azure_cosmos

    original_cosmos_client = azure_cosmos.CosmosClient
    azure_cosmos.CosmosClient = FakeConfigCosmosClient
    try:
        return importlib.import_module(module_name)
    finally:
        azure_cosmos.CosmosClient = original_cosmos_client


@pytest.fixture(name="notifications")
def notifications_fixture():
    return import_app_module_without_live_cosmos("functions_notifications")


def test_version_is_at_least_the_chat_delivery_release():
    checked = assert_app_version_at_least("0.261.218")
    require(isinstance(checked, str), f"version helper should return the current version, got {checked!r}")


def test_notification_type_matches_contract_and_registry(notifications):
    delivery = importlib.import_module("functions_workflow_chat_delivery")
    notice_type = notifications.WORKFLOW_CHAT_DELIVERY_NOTIFICATION_TYPE
    contract_type = delivery.NOTIFICATION_TYPE
    require(notice_type == "workflow_chat_delivery", f"notification constant changed: {notice_type}")
    require(contract_type == notice_type, f"delivery contract type drifted: {contract_type}")

    entry = notifications.NOTIFICATION_TYPES.get(notice_type)
    require(isinstance(entry, dict), "workflow chat delivery notification type must be registered")
    icon = entry.get("icon")
    color = entry.get("color")
    require(icon == "bi-activity", f"workflow chat delivery icon changed: {entry}")
    require(color == "info", f"workflow chat delivery color changed: {entry}")


def test_chat_response_notification_passes_retry_options_to_create_notification(notifications, monkeypatch):
    captured = []

    def fake_create_notification(**kwargs):
        captured.append(copy.deepcopy(kwargs))
        return {"id": f"notice-{len(captured)}", **kwargs}

    monkeypatch.setattr(notifications, "create_notification", fake_create_notification)
    first = notifications.create_chat_response_notification(
        USER,
        CONVERSATION_ID,
        MESSAGE_ID,
        conversation_title="Digest",
        response_preview="Done",
        idempotency_key="k-1",
        strict=True,
    )
    first_call = captured[-1]
    require(first["id"] == "notice-1", f"patched notification helper returned unexpected doc: {first}")
    require(first_call.get("idempotency_key") == "k-1", f"idempotency key was not passed through: {first_call}")
    require(first_call.get("strict") is True, f"strict=True was not passed through: {first_call}")

    notifications.create_chat_response_notification(USER, CONVERSATION_ID, MESSAGE_ID)
    default_call = captured[-1]
    require(default_call.get("idempotency_key") is None, f"default idempotency key changed: {default_call}")
    require(default_call.get("strict") is False, f"default strict flag changed: {default_call}")


def test_chat_response_notification_idempotency_returns_existing_notice(notifications, monkeypatch):
    container = FakeContainer("notifications")
    monkeypatch.setattr(notifications, "cosmos_notifications_container", container)

    first = notifications.create_chat_response_notification(
        USER, CONVERSATION_ID, MESSAGE_ID, idempotency_key="same-key", strict=True,
    )
    second = notifications.create_chat_response_notification(
        USER, CONVERSATION_ID, MESSAGE_ID, idempotency_key="same-key", strict=True,
    )
    stored_count = len(container.items)
    require(stored_count == 1, f"same retry key should store exactly one notice, got {stored_count}")
    require(second.get("id") == first.get("id"), f"repeat retry should return the existing notice: {first} {second}")

    third = notifications.create_chat_response_notification(
        USER, CONVERSATION_ID, MESSAGE_ID, idempotency_key="different-key", strict=True,
    )
    stored_count = len(container.items)
    require(stored_count == 2, f"different retry key should create a second notice, got {stored_count}")
    require(third.get("id") != first.get("id"), "different retry keys must not collide")


def test_chat_response_notification_strict_create_failure_contract(notifications, monkeypatch):
    soft_container = FakeContainer("notifications-soft")
    soft_container.fail("create_item", cosmos_error(500, "create failed"))
    monkeypatch.setattr(notifications, "cosmos_notifications_container", soft_container)
    soft_result = notifications.create_chat_response_notification(
        USER, CONVERSATION_ID, MESSAGE_ID, idempotency_key="soft-failure", strict=False,
    )
    require(soft_result is None, f"strict=False should swallow create failures and return None: {soft_result}")

    hard_container = FakeContainer("notifications-hard")
    hard_container.fail("create_item", cosmos_error(500, "create failed"))
    monkeypatch.setattr(notifications, "cosmos_notifications_container", hard_container)
    with pytest.raises(Exception) as raised:
        notifications.create_chat_response_notification(
            USER, CONVERSATION_ID, MESSAGE_ID, idempotency_key="hard-failure", strict=True,
        )
    status_code = getattr(raised.value, "status_code", None)
    require(status_code == 500, f"strict=True should propagate the storage error, got {raised.value!r}")


def replace_count(container):
    writes = container.writes("replace_item")
    return len(writes)


def test_guarded_unread_marked_sets_fields_and_raises_last_updated():
    conversation = make_conversation(last_updated=shift(PLANNED_AT, minutes=-5))
    container = FakeContainer("conversations", [conversation])
    outcome, returned = mark_conversation_unread_guarded(container, CONVERSATION_ID, USER, MESSAGE_ID, PLANNED_AT)
    stored = container.get(CONVERSATION_ID)

    require(outcome == UNREAD_MARKED, f"expected marked outcome, got {outcome}")
    require(returned.get("id") == CONVERSATION_ID, f"returned conversation mismatch: {returned}")
    require(stored.get("has_unread_assistant_response") is True, f"unread flag not set: {stored}")
    require(stored.get("last_unread_assistant_message_id") == MESSAGE_ID, f"unread message mismatch: {stored}")
    require(stored.get("last_unread_assistant_at") == PLANNED_AT, f"unread timestamp mismatch: {stored}")
    require(stored.get("last_updated") == PLANNED_AT, f"last_updated should be raised to planned_at: {stored}")

    newer_last_updated = shift(PLANNED_AT, minutes=5)
    newer_container = FakeContainer("conversations-newer", [make_conversation(last_updated=newer_last_updated)])
    newer_outcome, _newer_returned = mark_conversation_unread_guarded(
        newer_container, CONVERSATION_ID, USER, "assistant-workflow-result-2", PLANNED_AT,
    )
    newer_stored = newer_container.get(CONVERSATION_ID)
    require(newer_outcome == UNREAD_MARKED, f"expected newer conversation to be marked: {newer_outcome}")
    require(newer_stored.get("last_updated") == newer_last_updated, f"last_updated must not be lowered: {newer_stored}")


def test_guarded_unread_already_marked_does_not_write_again():
    container = FakeContainer("conversations", [make_conversation()])
    first_outcome, _first = mark_conversation_unread_guarded(container, CONVERSATION_ID, USER, MESSAGE_ID, PLANNED_AT)
    writes_after_first = replace_count(container)
    second_outcome, _second = mark_conversation_unread_guarded(container, CONVERSATION_ID, USER, MESSAGE_ID, PLANNED_AT)
    writes_after_second = replace_count(container)

    require(first_outcome == UNREAD_MARKED, f"setup mark failed: {first_outcome}")
    require(second_outcome == UNREAD_ALREADY_MARKED, f"expected already_marked, got {second_outcome}")
    require(writes_after_second == writes_after_first, "already_marked should not issue another replace")


def test_guarded_unread_read_since_skips_without_writing():
    read_at = shift(PLANNED_AT, minutes=1)
    container = FakeContainer("conversations", [make_conversation(last_updated=read_at)])
    outcome, conversation = mark_conversation_unread_guarded(
        container,
        CONVERSATION_ID,
        USER,
        MESSAGE_ID,
        PLANNED_AT,
        skip_if_read_since=PLANNED_AT,
    )
    writes = replace_count(container)
    require(outcome == UNREAD_READ_SINCE, f"expected read_since when last_updated reached skip time: {outcome}")
    require(conversation.get("last_updated") == read_at, f"read_since should return the stored conversation: {conversation}")
    require(writes == 0, f"read_since should not write, got {writes} replaces")


def test_guarded_unread_missing_conversation_returns_not_found():
    container = FakeContainer("conversations")
    outcome, conversation = mark_conversation_unread_guarded(container, CONVERSATION_ID, USER, MESSAGE_ID, PLANNED_AT)
    require(outcome == UNREAD_NOT_FOUND, f"missing conversation should return not_found, got {outcome}")
    require(conversation is None, f"missing conversation should not return a document: {conversation}")


@pytest.mark.parametrize("case_id,overrides", [
    ("non_private", {"chat_type": "personal_multi_user"}),
    ("soft_deleted", {"deleted": True}),
    ("orchestration_deleted", {"orchestration_deleted": True}),
    ("wrong_owner", {"user_id": OTHER_USER}),
])
def test_guarded_unread_unavailable_cases_do_not_write(case_id, overrides):
    container = FakeContainer("conversations", [make_conversation(**overrides)])
    outcome, conversation = mark_conversation_unread_guarded(container, CONVERSATION_ID, USER, MESSAGE_ID, PLANNED_AT)
    writes = replace_count(container)
    require(outcome == UNREAD_UNAVAILABLE, f"{case_id} should be unavailable, got {outcome}")
    require(isinstance(conversation, dict), f"{case_id} should return the read conversation")
    require(writes == 0, f"{case_id} should not write, got {writes} replaces")


def test_guarded_unread_require_private_false_allows_non_private_conversation():
    container = FakeContainer("conversations", [make_conversation(chat_type="personal_multi_user")])
    outcome, _conversation = mark_conversation_unread_guarded(
        container,
        CONVERSATION_ID,
        USER,
        MESSAGE_ID,
        PLANNED_AT,
        require_private=False,
    )
    stored = container.get(CONVERSATION_ID)
    require(outcome == UNREAD_MARKED, f"require_private=False should allow non-private conversations: {outcome}")
    require(stored.get("last_unread_assistant_message_id") == MESSAGE_ID, f"non-private mark missing: {stored}")


def test_guarded_unread_conflict_after_retry_budget_counts_attempts():
    max_retries = 2
    expected_attempts = max_retries + 1
    container = FakeContainer("conversations", [make_conversation()])
    container.fail("replace_item", *[cosmos_error(412, "etag conflict") for _index in range(expected_attempts)])
    outcome, conversation = mark_conversation_unread_guarded(
        container, CONVERSATION_ID, USER, MESSAGE_ID, PLANNED_AT, max_retries=max_retries,
    )
    attempts = replace_count(container)
    require(outcome == UNREAD_CONFLICT, f"exhausted 412 retries should return conflict, got {outcome}")
    require(conversation.get("id") == CONVERSATION_ID, f"conflict should return the last read conversation: {conversation}")
    require(attempts == expected_attempts, f"max_retries={max_retries} should make {expected_attempts} attempts, got {attempts}")


def test_guarded_unread_retry_preserves_concurrent_edit():
    container = FakeContainer("conversations", [make_conversation(title="Original title")])

    def concurrent_title_update():
        current = container.get(CONVERSATION_ID)
        current["title"] = "Concurrent title"
        container.put(current)
        return cosmos_error(412, "etag conflict")

    container.fail("replace_item", concurrent_title_update)
    outcome, _conversation = mark_conversation_unread_guarded(container, CONVERSATION_ID, USER, MESSAGE_ID, PLANNED_AT)
    stored = container.get(CONVERSATION_ID)
    attempts = replace_count(container)

    require(outcome == UNREAD_MARKED, f"retry after one 412 should mark, got {outcome}")
    require(attempts == 2, f"one conflict should produce exactly two replace attempts, got {attempts}")
    require(stored.get("title") == "Concurrent title", f"retry should preserve concurrent title: {stored}")
    require(stored.get("last_unread_assistant_message_id") == MESSAGE_ID, f"retry should still set unread mark: {stored}")


@pytest.mark.parametrize("field_name,conversation_id,user_id,message_id", [
    ("conversation_id_none", None, USER, MESSAGE_ID),
    ("conversation_id_empty", "", USER, MESSAGE_ID),
    ("user_id_none", CONVERSATION_ID, None, MESSAGE_ID),
    ("user_id_empty", CONVERSATION_ID, "", MESSAGE_ID),
    ("message_id_none", CONVERSATION_ID, USER, None),
    ("message_id_empty", CONVERSATION_ID, USER, ""),
])
def test_guarded_unread_rejects_missing_required_ids(field_name, conversation_id, user_id, message_id):
    container = FakeContainer("conversations", [make_conversation()])
    with pytest.raises(ValueError, match="unread mark"):
        mark_conversation_unread_guarded(container, conversation_id, user_id, message_id, PLANNED_AT)
    writes = replace_count(container)
    require(writes == 0, f"{field_name} should be rejected before writing, got {writes} replaces")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
