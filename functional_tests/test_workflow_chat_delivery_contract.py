#!/usr/bin/env python3
# test_workflow_chat_delivery_contract.py
"""
Functional test for the workflow chat delivery contract module.
Version: 0.261.218
Implemented in: 0.261.218

This test ensures the pure delivery helpers preserve idempotent chat-result message contracts.
"""

import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "application" / "single_app", ROOT / "functional_tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402

import functions_workflow_chat_delivery as delivery  # noqa: E402
from functions_workflow_result_reader import format_workflow_run_time  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_chat_delivery_fakes import (  # noqa: E402
    CONVERSATION_ID,
    RUN_ID,
    STEP_ID,
    USER,
    WORKFLOW_ID,
    require,
)

NOW = datetime(2026, 5, 4, 15, 0, 0, tzinfo=timezone.utc)
NOW_TEXT = "2026-05-04T15:00:00.000000Z"
REQUESTED_AT = "2026-05-04T14:05:00.000000Z"


def _summary(state="completed", version=5, **overrides):
    summary = {
        "exists": True,
        "deleted": False,
        "version": version,
        "state": state,
        "phase": None,
        "gate_reason_code": None,
        "deadline_at": None,
        "deadline_seconds": None,
        "schema_version": 2,
    }
    summary.update(overrides)
    return summary


def _record(status=delivery.STATUS_PENDING, generation=None, **overrides):
    record = delivery.build_chat_delivery_seed(
        time_zone="America/New_York",
        model_selection={"model": {"model_deployment": "gpt-4o"}, "reasoning_effort": "medium"},
        requester_roles=["User"],
        now=NOW,
    )
    record = delivery.finalize_chat_delivery_seed(record, None)
    record.update({"status": status, "generation": generation, "updated_at": NOW_TEXT})
    record.update(overrides)
    return record


def _reconcile(record, summary, now=NOW):
    return delivery.reconcile_chat_delivery(record, summary, now=now)


@pytest.fixture(autouse=True)
def clear_delivery_hints():
    delivery.clear_workflow_chat_delivery_hints()
    yield
    delivery.clear_workflow_chat_delivery_hints()


def test_version_is_at_least_the_chat_delivery_release():
    assert_app_version_at_least("0.261.218")


def test_workflow_delivery_message_id_is_deterministic_and_prefixed():
    first = delivery.workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, 5)
    second = delivery.workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, 5)
    require(first == second, "message id should be deterministic for the same run, chat, and generation")
    require(first.startswith(delivery.DELIVERY_MESSAGE_ID_PREFIX), "message id should carry the delivery prefix")
    require(len(first) == len(delivery.DELIVERY_MESSAGE_ID_PREFIX) + 40, "message id should use a 40-char fingerprint")


def test_workflow_delivery_message_id_changes_when_generation_changes():
    old_id = delivery.workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, 5)
    new_id = delivery.workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, 6)
    require(old_id != new_id, "message id must include generation in its fingerprint")


def test_workflow_delivery_message_id_changes_when_run_or_conversation_changes():
    first = delivery.workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, 5)
    other_run = delivery.workflow_delivery_message_id(f"{RUN_ID}-other", CONVERSATION_ID, 5)
    other_conversation = delivery.workflow_delivery_message_id(RUN_ID, f"{CONVERSATION_ID}-other", 5)
    require(first != other_run, "message id should change when only the run id changes")
    require(first != other_conversation, "message id should change when only the conversation id changes")


def test_workflow_delivery_message_id_rejects_missing_inputs():
    with pytest.raises(ValueError, match="run_id is required"):
        delivery.workflow_delivery_message_id("", CONVERSATION_ID, 5)
    with pytest.raises(ValueError, match="conversation_id is required"):
        delivery.workflow_delivery_message_id(RUN_ID, "", 5)
    with pytest.raises(ValueError, match="generation must be a non-negative integer"):
        delivery.workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, -1)
    with pytest.raises(ValueError, match="generation must be a non-negative integer"):
        delivery.workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, True)


def test_delivery_thread_id_is_deterministic_and_distinct_per_message():
    first_message = delivery.workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, 5)
    second_message = delivery.workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, 6)
    first_thread = delivery.delivery_thread_id(first_message)
    repeat_thread = delivery.delivery_thread_id(first_message)
    second_thread = delivery.delivery_thread_id(second_message)
    require(first_thread == repeat_thread, "thread id should be deterministic for one message id")
    require(first_thread != second_thread, "different message ids should get different thread ids")
    with pytest.raises(ValueError, match="message_id is required"):
        delivery.delivery_thread_id(" ")


def test_is_workflow_delivery_message_accepts_metadata_and_delivery_id():
    metadata_message = {"metadata": {delivery.DELIVERY_METADATA_KEY: {"run_id": RUN_ID}}}
    id_message = {"id": delivery.workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, 5), "metadata": {}}
    require(delivery.is_workflow_delivery_message(metadata_message), "metadata key should identify a workflow delivery message")
    require(delivery.is_workflow_delivery_message(id_message), "delivery id prefix should identify a workflow delivery message")


def test_is_workflow_delivery_message_rejects_ordinary_and_malformed_messages():
    samples = [
        None,
        [],
        {},
        {"id": "assistant_regular_1", "metadata": {}},
        {"metadata": None},
        {"metadata": "not-a-dict"},
        {"metadata": {delivery.DELIVERY_METADATA_KEY: "not-a-dict"}},
    ]
    for sample in samples:
        result = delivery.is_workflow_delivery_message(sample)
        require(result is False, f"malformed message should not be recognized: {sample!r}")


def test_delivery_notification_key_formats_are_pinned_literals():
    key = delivery.delivery_notification_key(RUN_ID, 5)
    notice_key = delivery.undeliverable_notification_key(RUN_ID, 5)
    expired_key = delivery.expired_notification_key(RUN_ID)
    require(key == "workflow-chat-delivery:run-delivery-1:5", "delivery notification key format changed")
    require(notice_key == "workflow-chat-delivery-notice:run-delivery-1:5", "undeliverable notification key format changed")
    require(expired_key == "workflow-chat-delivery-notice:run-delivery-1:expired", "expired notification key format changed")


def test_token_usage_idempotency_key_format_is_pinned_literal():
    message_id = delivery.workflow_delivery_message_id(RUN_ID, CONVERSATION_ID, 5)
    key = delivery.token_usage_idempotency_key(message_id, 3)
    require(key == f"workflow_result_delivery:{message_id}:3", "token usage idempotency key format changed")


def test_idempotency_keys_differ_by_generation_and_attempt():
    gen_five = delivery.delivery_notification_key(RUN_ID, 5)
    gen_six = delivery.delivery_notification_key(RUN_ID, 6)
    attempt_one = delivery.token_usage_idempotency_key("message-1", 1)
    attempt_two = delivery.token_usage_idempotency_key("message-1", 2)
    require(gen_five != gen_six, "notification keys must vary by generation")
    require(attempt_one != attempt_two, "token usage keys must vary by attempt")


def test_format_delivery_timestamp_normalizes_naive_and_aware_datetimes():
    naive = datetime(2026, 5, 4, 15, 0, 1, 123456)
    aware = datetime(2026, 5, 4, 11, 0, 1, 123456, tzinfo=timezone(timedelta(hours=-4)))
    require(delivery.format_delivery_timestamp(naive) == "2026-05-04T15:00:01.123456Z", "naive timestamps should be treated as UTC")
    require(delivery.format_delivery_timestamp(aware) == "2026-05-04T15:00:01.123456Z", "aware timestamps should normalize to UTC")
    require(delivery.format_delivery_timestamp("not-datetime") is None, "non-datetime values should not format")


def test_parse_delivery_timestamp_round_trips_and_normalizes():
    original = datetime(2026, 5, 4, 11, 0, 1, tzinfo=timezone(timedelta(hours=-4)))
    formatted = delivery.format_delivery_timestamp(original)
    parsed = delivery.parse_delivery_timestamp(formatted)
    require(parsed == datetime(2026, 5, 4, 15, 0, 1, tzinfo=timezone.utc), "format/parse should round trip through UTC")
    naive = delivery.parse_delivery_timestamp("2026-05-04T15:00:01")
    require(naive == datetime(2026, 5, 4, 15, 0, 1, tzinfo=timezone.utc), "naive parsed timestamps should become UTC")


def test_parse_delivery_timestamp_returns_none_for_junk_inputs():
    for value in ("", "not-a-date", "1" * 65, object(), None):
        parsed = delivery.parse_delivery_timestamp(value)
        require(parsed is None, f"junk timestamp should parse as None: {value!r}")


def test_delivery_label_includes_quoted_name_and_asked_when():
    label = delivery.delivery_label("Daily digest", "Sun Jan 4, 2026, 9:30 PM EST")
    without_time = delivery.delivery_label("Daily digest", "")
    require(label == "Results from `Daily digest` · you asked on Sun Jan 4, 2026, 9:30 PM EST", "delivery label format changed")
    require(without_time == "Results from `Daily digest`", "empty asked time should be omitted from delivery label")


def test_format_workflow_run_time_pins_asked_time_in_new_york():
    rendered = format_workflow_run_time("2026-01-05T02:30:00Z", "America/New_York")
    require(rendered == "Sun Jan 4, 2026, 9:30 PM EST", "asked time format for America/New_York changed")


def test_format_workflow_run_time_falls_back_to_utc_for_bad_or_missing_zone():
    bad_zone = format_workflow_run_time("2026-01-05T02:30:00Z", "Not/A_Real_Zone")
    missing_zone = format_workflow_run_time("2026-01-05T02:30:00Z", None)
    expected = "Mon Jan 5, 2026, 2:30 AM UTC"
    require(bad_zone == expected, "invalid time zone should fall back to UTC")
    require(missing_zone == expected, "missing time zone should fall back to UTC")


def test_clean_catalog_text_drops_noise_collapses_space_and_caps_length():
    cleaned = delivery.clean_catalog_text("  Alpha\u200b\n\tBeta  ", 80)
    capped = delivery.clean_catalog_text("abcdefghij", 6)
    require(cleaned == "Alpha Beta", "catalog text should remove controls and collapse whitespace")
    require(capped == "abcde…", "catalog text should cap with an ellipsis")
    require(delivery.clean_catalog_text(42, 80) == "", "non-string catalog text should become empty")


def test_quoted_workflow_name_neutralizes_backticks_noise_and_empty_names():
    quoted = delivery.quoted_workflow_name("Bad`Name\u200b\nNext")
    empty = delivery.quoted_workflow_name("```\u200b")
    require(quoted == "`Bad'Name Next`", "quoted workflow name should neutralize markdown/control characters")
    require(empty is None, "names with nothing but backticks and noise should be omitted")


def test_quoted_workflow_name_caps_to_name_max_length():
    quoted = delivery.quoted_workflow_name("A" * 90)
    inner = quoted.strip("`")
    require(len(inner) == delivery.NAME_MAX_LENGTH, "quoted workflow name should cap inner text at NAME_MAX_LENGTH")
    require(inner.endswith("…"), "capped workflow names should end with an ellipsis")


def test_display_workflow_name_falls_back_to_default_workflow():
    require(delivery.display_workflow_name("Daily digest") == "`Daily digest`", "display name should quote real names")
    require(delivery.display_workflow_name("```") == "`Workflow`", "display name should fall back for empty sanitized names")


def test_notice_workflow_name_uses_quotes_and_default_text():
    named = delivery.notice_workflow_name('Daily "digest"')
    fallback = delivery.notice_workflow_name("\u200b")
    require(named == '"Daily \'digest\'"', "notice workflow name should quote and neutralize double quotes")
    require(fallback == "your workflow", "notice workflow name should fall back to your workflow")


def test_notice_title_pins_every_supported_kind():
    expected = {
        delivery.KIND_RESULT: 'Results from "Daily digest" are ready',
        delivery.KIND_ANALYSIS: 'Results from "Daily digest" are ready',
        delivery.KIND_STATUS: 'Results from "Daily digest" are ready',
        delivery.KIND_CONTENT_BLOCKED: 'Results from "Daily digest" are ready',
        delivery.KIND_FAILED: '"Daily digest" didn\'t finish',
        delivery.KIND_CANCELLED: '"Daily digest" was cancelled',
        delivery.KIND_SKIPPED: '"Daily digest" didn\'t run',
        delivery.KIND_EXPIRED: '"Daily digest" didn\'t finish in time to post to chat',
    }
    for kind, title in expected.items():
        actual = delivery.notice_title(kind, "Daily digest")
        require(actual == title, f"notice title changed for {kind}")
    fallback = delivery.notice_title(delivery.KIND_RESULT, "\u200b")
    require(fallback == "Results from your workflow are ready", "default notice title sentence casing changed")


def test_delivered_notice_preview_is_pinned():
    preview = delivery.delivered_notice_preview("Daily digest")
    fallback = delivery.delivered_notice_preview("\u200b")
    require(preview == 'Results from "Daily digest" are in your chat', "delivered preview changed")
    require(fallback == "Results from your workflow are in your chat", "default delivered preview changed")


def test_assemble_delivery_content_joins_non_empty_parts_with_blank_lines():
    content = delivery.assemble_delivery_content("Label", "  Body\n", "Disclosure")
    body_only = delivery.assemble_delivery_content("", "  Body  ", "")
    require(content == "Label\n\nBody\n\nDisclosure", "delivery content layout changed")
    require(body_only == "Body", "empty label/disclosure should be omitted")


def test_failure_reason_text_pins_all_known_codes_and_unknown_default():
    expected = {
        "failed": "the run stopped before it finished",
        "invalid": "the workflow couldn't run as defined",
        "incomplete": "some of its steps didn't finish",
        "skipped": "no new or changed files were detected",
        delivery.REASON_DEADLINE_EXCEEDED: "it reached its time limit",
        "execution_budget_exceeded": "it reached its execution limit",
        "repeat_iteration_limit": "it reached its repeat limit",
        "m365_authorization": "Microsoft 365 access needs to be reconnected",
        "authorization": "your workflow access must be restored",
    }
    require(set(expected) == set(delivery.FAILURE_REASON_CODES), "failure reason code inventory changed")
    for code, text in expected.items():
        actual = delivery.failure_reason_text(code)
        require(actual == text, f"failure reason text changed for {code}")
    require(delivery.failure_reason_text("new-code") == expected["failed"], "unknown reason codes should use failed text")


def test_delivery_note_text_pins_supported_kinds_and_reason_codes():
    expected = {
        delivery.KIND_FAILED: "`Daily digest` failed: it reached its time limit.",
        delivery.KIND_CANCELLED: "`Daily digest` was cancelled.",
        delivery.KIND_STATUS: "`Daily digest` finished. Open the run to see its results.",
        delivery.KIND_CONTENT_BLOCKED: "`Daily digest` finished, but its results can't be shown here. Open the run to see them.",
        delivery.KIND_ANALYSIS: "`Daily digest` finished with a saved analysis. Ask a follow-up question about it here.",
        delivery.KIND_SKIPPED: "`Daily digest` didn't run: no new or changed files were detected.",
    }
    for kind, text in expected.items():
        reason = delivery.REASON_DEADLINE_EXCEEDED if kind == delivery.KIND_FAILED else None
        actual = delivery.delivery_note_text(kind, "Daily digest", reason_code=reason)
        require(actual == text, f"delivery note text changed for {kind}")
        require(bool(actual), f"delivery note text should not be empty for {kind}")


def test_delivery_note_text_rejects_unsupported_expired_kind():
    with pytest.raises(ValueError, match="unsupported delivery note kind"):
        delivery.delivery_note_text(delivery.KIND_EXPIRED, "Daily digest")


def test_build_delivery_metadata_shape_and_values_are_pinned():
    metadata = delivery.build_delivery_metadata(
        kind=delivery.KIND_RESULT,
        workflow_id=WORKFLOW_ID,
        run_id=RUN_ID,
        generation=5,
        run_status="completed",
        orchestration_run_id="orchestration-run-1",
        step_id=STEP_ID,
        requested_at=REQUESTED_AT,
    )
    expected = {
        "version": delivery.CHAT_DELIVERY_VERSION,
        "kind": delivery.KIND_RESULT,
        "workflow_id": WORKFLOW_ID,
        "workflow_scope": delivery.WORKFLOW_SCOPE,
        "run_id": RUN_ID,
        "generation": 5,
        "run_status": "completed",
        "orchestration_run_id": "orchestration-run-1",
        "step_id": STEP_ID,
        "requested_at": REQUESTED_AT,
    }
    require(metadata == expected, "delivery metadata snapshot shape changed")


def test_notice_metadata_shape_and_values_are_pinned():
    metadata = delivery.notice_metadata(WORKFLOW_ID, RUN_ID, delivery.STATUS_UNDELIVERABLE)
    require(metadata == {
        "workflow_id": WORKFLOW_ID,
        "run_id": RUN_ID,
        "workflow_scope": delivery.WORKFLOW_SCOPE,
        "delivery_status": delivery.STATUS_UNDELIVERABLE,
    }, "notice metadata shape changed")


def test_workflow_run_notice_link_url_encodes_odd_ids():
    link = delivery.workflow_run_notice_link("workflow id/&?", "run id/&?")
    require(
        link == "/workflow-activity?workflowId=workflow+id%2F%26%3F&runId=run+id%2F%26%3F&scope=personal",
        "workflow run notice link encoding changed",
    )


def test_workflow_delivery_refusal_payloads_are_pinned():
    retry_payload, retry_status = delivery.workflow_delivery_refusal_payload(delivery.DELIVERY_RETRY_UNSUPPORTED)
    edit_payload, edit_status = delivery.workflow_delivery_refusal_payload(delivery.DELIVERY_EDIT_UNSUPPORTED)
    require(retry_status == 400 and edit_status == 400, "refusal status should stay 400")
    require(retry_payload == {
        "error": "A workflow run posted this message, so it can't be retried here. To run the workflow again, open the run in Workflows.",
        "code": delivery.DELIVERY_RETRY_UNSUPPORTED,
    }, "retry refusal payload changed")
    require(edit_payload == {
        "error": "A workflow run posted this message, so it can't be edited. Ask a new question instead.",
        "code": delivery.DELIVERY_EDIT_UNSUPPORTED,
    }, "edit refusal payload changed")
    payload, status = delivery.workflow_delivery_refusal_payload("bogus")
    require(status == 400, "unknown refusal status should stay 400")
    require(payload["code"] == delivery.DELIVERY_RETRY_UNSUPPORTED, "unknown refusal code should fall back to retry")


def test_next_backoff_seconds_follows_table_and_clamps_edges():
    attempts = [-10, 0, 1, 2, 3, 4, 5, 6, 7, 8, 99, "2"]
    expected = [30, 30, 30, 60, 120, 240, 480, 900, 900, 900, 900, 30]
    actual = [delivery.next_backoff_seconds(value) for value in attempts]
    require(actual == expected, "backoff table or clamping changed")


def test_normalize_requester_roles_dedupes_preserves_order_and_drops_bad_values():
    roles = ["User", "", None, "Admin", "User", "x" * 65, "Approver"]
    normalized = delivery.normalize_requester_roles(roles)
    require(normalized == ["User", "Admin", "Approver"], "role normalization should drop invalid roles and dedupe in order")
    require(delivery.normalize_requester_roles("User") == [], "non-list roles should normalize to empty")
    many_roles = [f"role-{index}" for index in range(delivery.MAX_ROLES + 3)]
    capped = delivery.normalize_requester_roles(many_roles)
    require(len(capped) == delivery.MAX_ROLES, "role normalization should cap the number of roles")
    require(capped[-1] == f"role-{delivery.MAX_ROLES - 1}", "role normalization should preserve first MAX_ROLES entries")


def test_normalize_model_selection_keeps_valid_model_reasoning_and_groups():
    seeds = {
        "model": {
            "model_deployment": " gpt-4o ",
            "model_id": "model-1",
            "model_endpoint_id": "endpoint-1",
            "model_provider": "aoai",
        },
        "reasoning_effort": " high ",
        "active_group_ids": [" group-1 ", "group-2", "group-1", ""],
    }
    normalized = delivery.normalize_model_selection(seeds)
    require(normalized == {
        "model": {
            "model_deployment": "gpt-4o",
            "model_id": "model-1",
            "model_endpoint_id": "endpoint-1",
            "model_provider": "aoai",
        },
        "reasoning_effort": "high",
        "active_group_ids": ["group-1", "group-2"],
    }, "model selection normalization changed for valid seeds")


def test_normalize_model_selection_drops_invalid_model_and_uses_fallback_groups():
    seeds = {"model": {"model_deployment": 123}, "reasoning_effort": "x" * 40}
    normalized = delivery.normalize_model_selection(seeds, active_group_ids=["g1", "g1", "g2"])
    require(normalized == {"model": {}, "reasoning_effort": "", "active_group_ids": ["g1", "g2"]}, "invalid model fields should clear model and use fallback groups")
    groups = [f"g-{index}" for index in range(delivery.MAX_GROUPS + 3)]
    capped = delivery.normalize_model_selection({}, active_group_ids=groups)
    require(capped["active_group_ids"] == groups[:delivery.MAX_GROUPS], "active groups should cap at MAX_GROUPS")


def test_normalize_time_zone_keeps_valid_names_and_rejects_junk():
    require(delivery.normalize_time_zone("America/New_York") == "America/New_York", "valid IANA-looking zone should be kept")
    for zone in (None, "", "Europe/Paris;drop", "A" * 65, "America New_York", "Etc/UTC<script>"):
        normalized = delivery.normalize_time_zone(zone)
        require(normalized == "UTC", f"invalid time zone should fall back to UTC: {zone!r}")


def test_build_chat_delivery_seed_shape_and_defaults_are_pinned():
    seed = delivery.build_chat_delivery_seed(
        time_zone="Bad Zone!",
        model_selection={"model": {"model_deployment": "gpt-4o"}},
        requester_roles=["User", "User", "Admin"],
        now=NOW,
    )
    expected_keys = {
        "version", "status", "generation", "expires_at", "time_zone", "model_selection", "requester_roles",
        "lease_id", "lease_expires_at", "attempts", "next_attempt_at", "first_deferred_at", "phase", "message_id",
        "planned_at", "kind", "notice_kind", "outcome_reason", "run_status", "delivered_at", "created_at", "updated_at", "history",
    }
    require(set(seed) == expected_keys, "chat delivery seed key set changed")
    require(seed["version"] == delivery.CHAT_DELIVERY_VERSION, "seed version changed")
    require(seed["status"] == delivery.STATUS_PENDING, "seed status should start pending")
    require(seed["time_zone"] == "UTC", "seed should normalize invalid time zones")
    require(seed["requester_roles"] == ["User", "Admin"], "seed should normalize requester roles")
    require(seed["created_at"] == NOW_TEXT and seed["updated_at"] == NOW_TEXT, "seed timestamps should use the provided now")


def test_compute_expires_at_deadline_at_wins_over_seconds():
    expires = delivery.compute_expires_at(
        deadline_at="2026-05-05T00:00:00Z",
        deadline_seconds=1,
        base="2026-05-04T15:00:00Z",
    )
    require(expires == "2026-05-06T00:00:00.000000Z", "deadline_at should win and add delivery grace")


def test_compute_expires_at_caps_deadline_seconds_and_uses_default():
    base = "2026-05-04T15:00:00Z"
    capped = delivery.compute_expires_at(deadline_seconds=delivery.MAX_DEADLINE_SECONDS + 99, base=base)
    defaulted = delivery.compute_expires_at(deadline_seconds=-1, base=base)
    expected = "2026-05-06T15:00:00.000000Z"
    require(capped == expected, "deadline seconds should cap at MAX_DEADLINE_SECONDS plus grace")
    require(defaulted == expected, "non-positive deadline seconds should use default plus grace")


def test_finalize_chat_delivery_seed_sets_expires_at_from_control():
    seed = delivery.build_chat_delivery_seed(time_zone="UTC", model_selection={}, requester_roles=[], now=NOW)
    finalized = delivery.finalize_chat_delivery_seed(seed, {"limits": {"deadline_seconds": 60}})
    require(finalized["expires_at"] == "2026-05-05T15:01:00.000000Z", "finalize should compute expiry from control deadline seconds")
    require(seed["expires_at"] is None, "finalize should not mutate the input seed")
    require(delivery.finalize_chat_delivery_seed(None, {}) is None, "non-mapping seeds should return None")


def test_chat_delivery_applies_requires_matching_contract_and_conversation():
    run = {
        delivery.CHAT_DELIVERY_KEY: {"version": delivery.CHAT_DELIVERY_VERSION},
        "chat_invocation": {"conversation_id": CONVERSATION_ID},
    }
    require(delivery.chat_delivery_applies(run, CONVERSATION_ID) is True, "valid run should apply to its conversation")
    require(delivery.chat_delivery_applies(run, "other") is False, "conversation mismatch should not apply")
    run[delivery.CHAT_DELIVERY_KEY]["version"] = 99
    require(delivery.chat_delivery_applies(run, CONVERSATION_ID) is False, "version mismatch should not apply")
    require(delivery.chat_delivery_applies(None, CONVERSATION_ID) is False, "non-mapping run should not apply")


def test_needs_guarded_run_save_contract_is_pinned():
    require(delivery.needs_guarded_run_save({delivery.CHAT_DELIVERY_KEY: {}}) is True, "runs with delivery records need guarded saves")
    require(delivery.needs_guarded_run_save({"trigger_source": delivery.CHAT_TRIGGER_SOURCE}) is True, "chat-triggered runs missing invocation need guarded saves")
    require(delivery.needs_guarded_run_save({"trigger_source": delivery.CHAT_TRIGGER_SOURCE, "chat_invocation": {}}) is False, "chat-triggered runs with invocation should not need guard")
    require(delivery.needs_guarded_run_save(None) is False, "non-mapping run should not need guard")


def test_merge_stored_run_fields_preserves_stored_delivery_invocation_and_strips_cosmos_keys():
    incoming = {"id": RUN_ID, "status": "completed", "_etag": "incoming", delivery.CHAT_DELIVERY_KEY: {"status": "pending"}}
    stored = {delivery.CHAT_DELIVERY_KEY: {"status": "delivered"}, "chat_invocation": {"conversation_id": CONVERSATION_ID}}
    merged = delivery.merge_stored_run_fields(incoming, stored)
    require("_etag" not in merged, "Cosmos metadata should be stripped from merged run")
    require(merged[delivery.CHAT_DELIVERY_KEY] == {"status": "delivered"}, "stored delivery record should win")
    require(merged["chat_invocation"] == {"conversation_id": CONVERSATION_ID}, "stored invocation should be restored")


def test_merge_stored_run_fields_preserves_cancellation_state():
    incoming = {"id": RUN_ID, "status": "running"}
    stored = {"status": "cancelling", "cancellation_requested_at": NOW_TEXT, "cancellation_requested_by": USER}
    merged = delivery.merge_stored_run_fields(incoming, stored)
    require(merged["status"] == "cancelling", "stored cancellation should force incoming status to cancelling")
    require(merged["cancellation_requested_by"] == USER, "cancellation requester should be preserved")
    stored["status"] = "cancelled"
    merged = delivery.merge_stored_run_fields(incoming, stored)
    require(merged["status"] == "cancelled", "stored cancelled state should win")


def test_control_summary_pins_none_and_not_found_shape():
    summary = delivery.control_summary(None)
    require(summary == {
        "exists": False,
        "deleted": False,
        "version": None,
        "state": None,
        "phase": None,
        "gate_reason_code": None,
        "deadline_at": None,
        "deadline_seconds": None,
        "schema_version": None,
    }, "missing control summary shape changed")


def test_control_summary_reads_schema_v2_deadline_and_lowercases_state_phase_gate():
    control = {
        "deleted": 1,
        "version": 7,
        "schema_version": 2,
        "control_state": "FAILED",
        "phase": "DEADLINE_EXCEEDED",
        "gate": {"reason_code": "AUTHORIZATION"},
        "limits": {"deadline_at": "2026-05-05T00:00:00Z", "deadline_seconds": 123},
    }
    summary = delivery.control_summary(control)
    require(summary == {
        "exists": True,
        "deleted": True,
        "version": 7,
        "state": "failed",
        "phase": "deadline_exceeded",
        "gate_reason_code": "authorization",
        "deadline_at": "2026-05-05T00:00:00Z",
        "deadline_seconds": 123,
        "schema_version": 2,
    }, "control summary should normalize schema v2 controls")


def test_reconcile_pending_terminal_states_become_ready_with_expected_kinds():
    for state, kind in delivery.KIND_BY_TERMINAL_STATE.items():
        updated, changed, ready = _reconcile(_record(), _summary(state=state, version=8))
        require(changed is True, f"pending {state} should change")
        require(ready is True, f"pending {state} should be ready")
        require(updated["status"] == delivery.STATUS_READY, f"pending {state} should become ready")
        require(updated["generation"] == 8, f"pending {state} should use control version")
        require(updated["kind"] == kind, f"pending {state} should map to {kind}")
        require(updated["run_status"] == state, f"pending {state} should pin run_status")


def test_reconcile_pending_non_terminal_states_stay_pending():
    for state in ["queued", "running", "cancelling", "waiting_approval", "waiting_output", "waiting_recovery", "paused"]:
        updated, changed, ready = _reconcile(_record(), _summary(state=state, version=8))
        require(changed is False, f"pending {state} should not change")
        require(ready is False, f"pending {state} should not be ready")
        require(updated["status"] == delivery.STATUS_PENDING, f"pending {state} should stay pending")


def test_reconcile_deleted_control_closes_open_record_silently_without_attempt():
    record = _record(status=delivery.STATUS_READY, generation=5, attempts=3, kind=delivery.KIND_RESULT)
    updated, changed, ready = _reconcile(record, _summary(state="cancelled", version=6, deleted=True))
    require(changed is True and ready is False, "deleted control should close open delivery without becoming ready")
    require(updated["status"] == delivery.STATUS_UNDELIVERABLE, "deleted control should mark open record undeliverable")
    require(updated["outcome_reason"] == delivery.REASON_WORKFLOW_DELETED, "deleted control should pin workflow_deleted reason")
    require(updated["notice_kind"] == delivery.NOTICE_NONE, "deleted control should close silently")
    require(updated["attempts"] == 3, "deleted control should not count as an attempt")


def test_reconcile_deleted_control_does_not_reopen_delivered_even_with_newer_version():
    record = _record(
        status=delivery.STATUS_DELIVERED,
        generation=5,
        phase=delivery.PHASE_MESSAGE_CREATED,
        message_id="message-5",
        delivered_at=NOW_TEXT,
    )
    updated, changed, ready = _reconcile(record, _summary(state="cancelled", version=99, deleted=True))
    require(changed is False and ready is False, "deleted newer control must not reopen delivered records")
    require(updated == record, "delivered record should remain unchanged after deleted control")


def test_reconcile_delivered_reopens_only_when_control_version_is_greater():
    record = _record(status=delivery.STATUS_DELIVERED, generation=5, kind=delivery.KIND_RESULT, message_id="m5", delivered_at=NOW_TEXT)
    equal, equal_changed, _ready = _reconcile(copy.deepcopy(record), _summary(state="completed", version=5))
    lower, lower_changed, _ready = _reconcile(copy.deepcopy(record), _summary(state="completed", version=4))
    higher, higher_changed, higher_ready = _reconcile(copy.deepcopy(record), _summary(state="running", version=6))
    require(equal_changed is False and equal["status"] == delivery.STATUS_DELIVERED, "equal version must not reopen delivered records")
    require(lower_changed is False and lower["status"] == delivery.STATUS_DELIVERED, "lower version must not reopen delivered records")
    require(higher_changed is True and higher_ready is False, "higher version should reopen but wait for terminal state")
    require(higher["status"] == delivery.STATUS_PENDING, "reopened delivered record should return to pending")
    require(higher["generation"] is None, "reopened delivered record should clear generation")
    require(higher["history"][-1]["generation"] == 5, "reopened delivered record should archive previous generation")


def test_reconcile_undeliverable_reopens_for_newer_control_version():
    record = _record(status=delivery.STATUS_UNDELIVERABLE, generation=5, kind=delivery.KIND_FAILED, outcome_reason=delivery.REASON_DELIVERY_FAILED)
    updated, changed, ready = _reconcile(record, _summary(state="running", version=6))
    require(changed is True and ready is False, "newer control should reopen undeliverable records")
    require(updated["status"] == delivery.STATUS_PENDING, "undeliverable record should reopen as pending")
    require(updated["generation"] is None, "reopened undeliverable should clear generation")
    require(updated["history"][-1]["outcome_reason"] == delivery.REASON_DELIVERY_FAILED, "history should preserve prior reason")


def test_reconcile_expired_never_reopens():
    record = _record(status=delivery.STATUS_EXPIRED, generation=5, kind=delivery.KIND_EXPIRED)
    updated, changed, ready = _reconcile(record, _summary(state="completed", version=99))
    require(changed is False and ready is False, "expired records should never reopen")
    require(updated == record, "expired record should remain unchanged")


def test_reconcile_missing_control_closes_open_record_with_runtime_missing_reason():
    record = _record(status=delivery.STATUS_PENDING, attempts=2)
    updated, changed, ready = _reconcile(record, delivery.control_summary(None))
    require(changed is True and ready is False, "missing control should close open delivery")
    require(updated["status"] == delivery.STATUS_UNDELIVERABLE, "missing control should be undeliverable")
    require(updated["outcome_reason"] == delivery.REASON_RUNTIME_MISSING, "missing control reason should be runtime_missing")
    require(updated["notice_kind"] == delivery.NOTICE_NONE, "missing control should close silently")
    require(updated["attempts"] == 2, "missing control closure should not count as an attempt")
    second, second_changed, second_ready = _reconcile(updated, delivery.control_summary(None))
    require(second_changed is False and second_ready is False, "missing-control closure should be stable")
    require(second == updated, "second missing-control reconcile should not mutate closed record")


def test_reconcile_ready_generation_reverts_to_pending_when_run_moves_back_to_active():
    record = _record(status=delivery.STATUS_READY, generation=5, kind=delivery.KIND_RESULT, run_status="completed")
    updated, changed, ready = _reconcile(record, _summary(state="running", version=5))
    require(changed is True and ready is False, "ready record should leave ready when control is no longer terminal")
    require(updated["status"] == delivery.STATUS_PENDING, "ready active record should return to pending")
    require(updated["generation"] is None and updated["kind"] is None and updated["run_status"] is None, "ready active record should clear generation fields")


def test_reconcile_ready_generation_archives_message_created_generation_when_replaced():
    record = _record(
        status=delivery.STATUS_READY,
        generation=5,
        kind=delivery.KIND_RESULT,
        phase=delivery.PHASE_MESSAGE_CREATED,
        message_id="m5",
        delivered_at=NOW_TEXT,
        history=[],
    )
    updated, changed, ready = _reconcile(record, _summary(state="failed", version=6))
    require(changed is True and ready is True, "replaced ready generation should stay ready for new terminal generation")
    require(updated["generation"] == 6 and updated["kind"] == delivery.KIND_FAILED, "new generation should replace ready fields")
    require(updated["history"][-1]["status"] == delivery.STATUS_DELIVERED, "message-created abandoned generation should be archived as delivered")
    require(updated["phase"] is None and updated["message_id"] is None, "abandoned generation should clear per-generation message fields")


def test_reconcile_expired_by_paused_deadline_reason_becomes_expired_kind():
    summary = _summary(state="paused", version=9, gate_reason_code=delivery.REASON_DEADLINE_EXCEEDED)
    updated, changed, ready = _reconcile(_record(), summary)
    require(changed is True and ready is True, "paused deadline-exceeded summary should be ready")
    require(updated["kind"] == delivery.KIND_EXPIRED, "paused deadline-exceeded summary should become expired kind")


def test_reconcile_expired_by_timestamp_becomes_expired_kind():
    past = delivery.format_delivery_timestamp(NOW - timedelta(seconds=1))
    updated, changed, ready = _reconcile(_record(expires_at=past), _summary(state="running", version=4))
    require(changed is True and ready is True, "past expiry should make pending active record ready")
    require(updated["kind"] == delivery.KIND_EXPIRED, "past expiry should produce expired kind")


def test_reconcile_history_is_capped_across_reopen_cycles():
    record = _record(status=delivery.STATUS_DELIVERED, generation=0, kind=delivery.KIND_RESULT, message_id="m0")
    for version in range(1, delivery.HISTORY_MAX + 4):
        reopened, changed, _ready = _reconcile(record, _summary(state="running", version=version))
        require(changed is True, f"version {version} should reopen closed record")
        record = reopened
        record.update({
            "status": delivery.STATUS_DELIVERED,
            "generation": version,
            "kind": delivery.KIND_RESULT,
            "message_id": f"m{version}",
            "delivered_at": NOW_TEXT,
        })
    require(len(record["history"]) == delivery.HISTORY_MAX, "history should be capped at HISTORY_MAX")
    require(record["history"][0]["generation"] == 3, "history cap should retain the newest entries")


def test_reconcile_ignores_invalid_records_and_delivering_records():
    invalid = {"version": delivery.CHAT_DELIVERY_VERSION, "status": "bogus"}
    invalid_updated, invalid_changed, invalid_ready = _reconcile(invalid, _summary())
    delivering = _record(status=delivery.STATUS_DELIVERING, generation=5)
    delivering_updated, delivering_changed, delivering_ready = _reconcile(delivering, _summary(state="completed", version=6))
    require(invalid_updated == invalid and invalid_changed is False and invalid_ready is False, "invalid record should be ignored")
    require(delivering_updated == delivering and delivering_changed is False and delivering_ready is False, "delivering record should not reconcile")


def test_phase_at_least_orders_known_phases():
    require(delivery.phase_at_least(delivery.PHASE_CLAIMED, delivery.PHASE_CLAIMED), "claimed should be at least claimed")
    require(delivery.phase_at_least(delivery.PHASE_MESSAGE_CREATED, delivery.PHASE_PUBLISHING), "message_created should be after publishing")
    require(delivery.phase_at_least(delivery.PHASE_NOTIFIED, delivery.PHASE_MESSAGE_CREATED), "notified should be after message_created")
    require(delivery.phase_at_least(delivery.PHASE_CLAIMED, delivery.PHASE_NOTIFIED) is False, "claimed should not be at least notified")
    require(delivery.phase_at_least("unknown", delivery.PHASE_CLAIMED) is False, "unknown phase should be false")
    require(delivery.phase_at_least(delivery.PHASE_CLAIMED, "unknown") is False, "unknown wanted phase should be false")
    require(delivery.phase_at_least(None, delivery.PHASE_CLAIMED) is False, "None phase should be false")


def test_signal_workflow_chat_delivery_dedupes_same_user_and_run():
    first = delivery.signal_workflow_chat_delivery(USER, RUN_ID)
    second = delivery.signal_workflow_chat_delivery(USER, RUN_ID)
    drained = delivery.drain_workflow_chat_delivery_hints()
    require(first is True and second is True, "duplicate hints should report success")
    require(drained == [(USER, RUN_ID)], "duplicate hints should drain only once")


def test_signal_workflow_chat_delivery_rejects_bad_inputs():
    cases = [("", RUN_ID), (USER, ""), (None, RUN_ID), (USER, None)]
    for user_id, run_id in cases:
        result = delivery.signal_workflow_chat_delivery(user_id, run_id)
        require(result is False, f"bad hint input should be rejected: {user_id!r}, {run_id!r}")
    require(delivery.drain_workflow_chat_delivery_hints() == [], "bad hint inputs should not enqueue")


def test_drain_workflow_chat_delivery_hints_returns_fifo_and_respects_limit():
    for index in range(3):
        delivery.signal_workflow_chat_delivery(USER, f"run-{index}")
    first = delivery.drain_workflow_chat_delivery_hints(2)
    second = delivery.drain_workflow_chat_delivery_hints(2)
    require(first == [(USER, "run-0"), (USER, "run-1")], "hint drain should return FIFO entries up to limit")
    require(second == [(USER, "run-2")], "hint drain should retain entries beyond the limit")


def test_drain_workflow_chat_delivery_hints_negative_or_non_int_limit_drains_all():
    delivery.signal_workflow_chat_delivery(USER, "run-a")
    delivery.signal_workflow_chat_delivery(USER, "run-b")
    drained = delivery.drain_workflow_chat_delivery_hints("all")
    require(drained == [(USER, "run-a"), (USER, "run-b")], "non-int limit should drain all hints")
    delivery.signal_workflow_chat_delivery(USER, "run-c")
    drained = delivery.drain_workflow_chat_delivery_hints(-1)
    require(drained == [(USER, "run-c")], "negative limit should drain all hints")


def test_hint_queue_is_bounded_and_rejects_entries_past_max():
    successes = []
    for index in range(delivery.HINT_QUEUE_MAX):
        success = delivery.signal_workflow_chat_delivery(USER, f"run-{index}")
        successes.append(success)
    overflow = delivery.signal_workflow_chat_delivery(USER, "run-overflow")
    drained = delivery.drain_workflow_chat_delivery_hints()
    require(all(successes), "all hints up to HINT_QUEUE_MAX should enqueue")
    require(overflow is False, "hint beyond HINT_QUEUE_MAX should be rejected")
    require(len(drained) == delivery.HINT_QUEUE_MAX, "bounded queue should hold exactly HINT_QUEUE_MAX entries")
    require((USER, "run-overflow") not in drained, "overflow hint should not be silently enqueued")


def test_clear_workflow_chat_delivery_hints_empties_queue():
    delivery.signal_workflow_chat_delivery(USER, RUN_ID)
    delivery.clear_workflow_chat_delivery_hints()
    drained = delivery.drain_workflow_chat_delivery_hints()
    require(drained == [], "clear should empty pending delivery hints")


def test_wait_for_workflow_chat_delivery_hint_returns_quickly_when_pending():
    delivery.signal_workflow_chat_delivery(USER, RUN_ID)
    result = delivery.wait_for_workflow_chat_delivery_hint(0.2)
    require(result is True, "wait should return True when a hint is already pending")
    delivery.clear_workflow_chat_delivery_hints()
    result = delivery.wait_for_workflow_chat_delivery_hint(0)
    require(result is False, "wait should return False immediately for an empty queue with zero timeout")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
