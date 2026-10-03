#!/usr/bin/env python3
# test_workflow_alert_acknowledgment.py
"""
Functional test for must-acknowledge workflow alerts, sound, size and team delivery.
Version: 0.261.234
Implemented in: 0.261.234

This test ensures that alert rules accept and validate the new pop-up options with reviewed
messages; that a run's decision takes the strongest option any matched rule asked for and
forces a pop-up when an option needs one; that the runner raises one shared group alert only
for a group workflow; that only an alert's recipients can acknowledge it, the first
acknowledgment wins and read, dismiss and mark-all-read never acknowledge; that concurrent
writes to a shared alert can't drop an acknowledgment; that group members other than the
workflow's owner never receive the run's output; and that must-acknowledge alerts keep
popping up regardless of age or read state. Storage is an in-memory stand-in, so no Azure
service is used.
"""

import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import logging
from pathlib import Path
import sys
import types
from unittest.mock import Mock, patch

import pytest
from azure.cosmos import exceptions as cosmos_exceptions

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

from functions_workflow_alerts import (  # noqa: E402
    build_workflow_alert_facts,
    evaluate_workflow_alert_rules,
    normalize_alert_rules,
    normalize_workflow_alert_settings,
)
from functions_workflow_definitions import WorkflowAlertValidationError  # noqa: E402


FAILED_RULE = {
    "name": "Run failed",
    "severity": "high",
    "delivery": "popup",
    "condition": {"type": "run_status", "statuses": ["failed"]},
}


def rule(**overrides):
    value = deepcopy(FAILED_RULE)
    value.update(overrides)
    return value


def save(rules, scope=None, existing=None):
    return normalize_workflow_alert_settings(
        {"alert_mode": "rules", "alert_rules": rules},
        existing_workflow=existing,
        task_ids=[],
        workflow_scope=scope,
    )


def refusal(rules, scope=None):
    with pytest.raises(WorkflowAlertValidationError) as caught:
        save(rules, scope=scope)
    return str(caught.value)


# --- Rule options -------------------------------------------------------------------------


def test_default_options_are_not_stored_so_existing_rules_keep_their_shape():
    assert_app_version_at_least("0.261.234")
    stored = save([rule(require_acknowledgment=False, sound="off", size="small", audience="owner")], scope="group")

    assert set(stored["alert_rules"][0]) == {
        "id", "name", "enabled", "severity", "delivery", "scope", "condition", "order",
    }


def test_non_default_options_are_stored_normalized():
    stored = save(
        [rule(require_acknowledgment=" Yes ", sound=" REPEAT ", size="Large", audience="group")],
        scope="group",
    )["alert_rules"][0]

    assert stored["require_acknowledgment"] is True
    assert stored["sound"] == "repeat"
    assert stored["size"] == "large"
    assert stored["audience"] == "group"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), ("on", True), ("1", True), (" TRUE ", True), ("no", False), ("0", False), (0, False), (None, False)],
)
def test_acknowledgment_flag_reads_like_enabled(value, expected):
    stored = save([rule(require_acknowledgment=value)])["alert_rules"][0]

    assert stored.get("require_acknowledgment", False) is expected


@pytest.mark.parametrize(
    ("overrides", "scope", "message"),
    [
        ({"sound": "siren"}, None, "Alert rule 1 sound must be off, once or repeat."),
        ({"size": "huge"}, None, "Alert rule 1 size must be small, medium or large."),
        ({"audience": "everyone"}, None, "Alert rule 1 audience must be owner or group."),
        ({"audience": "group"}, "personal", "Alert rule 1 can alert the whole group only in a group workflow."),
        (
            {"delivery": "notify_only", "require_acknowledgment": True},
            None,
            "Alert rule 1 must pop up to require acknowledgment, play a sound or change its size.",
        ),
        (
            {"severity": "info", "delivery": "default", "sound": "once"},
            None,
            "Alert rule 1 must pop up to require acknowledgment, play a sound or change its size.",
        ),
        (
            {"severity": "low", "delivery": "default", "size": "medium"},
            None,
            "Alert rule 1 must pop up to require acknowledgment, play a sound or change its size.",
        ),
        ({"sound": "repeat"}, None, "Alert rule 1 can repeat its sound only when it requires acknowledgment."),
    ],
)
def test_each_invalid_option_is_refused_with_its_reviewed_message(overrides, scope, message):
    refused = refusal([rule(**overrides)], scope=scope)

    assert refused == message


def test_messages_name_the_rule_position_and_follow_the_documented_order():
    # The sound is checked before the size, and both before the cross-field checks.
    second_rule = refusal([rule(), rule(sound="loud", size="huge")])
    bell_only_repeat = refusal([rule(delivery="notify_only", sound="repeat")])

    assert second_rule == "Alert rule 2 sound must be off, once or repeat."
    assert bell_only_repeat == (
        "Alert rule 1 must pop up to require acknowledgment, play a sound or change its size."
    )


def test_group_audience_is_accepted_in_a_group_workflow_and_unchecked_without_a_scope():
    in_group = save([rule(audience="group")], scope="group")
    unscoped = save([rule(audience="group")], scope=None)

    assert in_group["alert_rules"][0]["audience"] == "group"
    assert unscoped["alert_rules"][0]["audience"] == "group"


def test_stored_rules_that_were_not_sent_are_carried_over_without_the_scope_check():
    existing = {"alert_mode": "rules", "alert_rules": [rule(id="kept", audience="group")]}

    stored = normalize_workflow_alert_settings({}, existing_workflow=existing, workflow_scope="personal")

    assert stored["alert_rules"][0]["audience"] == "group"


def test_medium_and_above_pop_up_by_default_so_they_accept_options():
    stored = save([rule(severity="medium", delivery="default", require_acknowledgment=True, sound="repeat")])

    assert stored["alert_rules"][0]["sound"] == "repeat"


def test_both_save_paths_pass_their_scope():
    personal = (APP / "functions_personal_workflows.py").read_text(encoding="utf-8")
    group = (APP / "functions_group_workflows.py").read_text(encoding="utf-8")

    assert "workflow_scope='personal'," in personal
    assert "workflow_scope='group'," in group


# --- Decision ---------------------------------------------------------------------------


def decide(rules, status="failed"):
    workflow = {
        "id": "wf-1",
        "name": "Watch",
        "user_id": "owner",
        "alert_mode": "rules",
        "alert_rules": normalize_alert_rules(rules),
    }
    facts = build_workflow_alert_facts(workflow, {"id": "run-1", "status": status}, {})
    return evaluate_workflow_alert_rules(workflow, facts)


def test_the_strongest_option_wins_while_severity_follows_the_winning_rule():
    decision = decide([
        rule(name="Loud", severity="critical", delivery="popup"),
        rule(name="Must see", severity="medium", require_acknowledgment=True, sound="repeat", size="medium",
             audience="group"),
        rule(name="Big", severity="low", delivery="popup", size="large"),
    ])

    assert decision["should_alert"] is True
    assert decision["severity"] == "critical"
    assert decision["winning_rule_name"] == "Loud"
    assert decision["require_acknowledgment"] is True
    assert decision["sound"] == "repeat"
    assert decision["size"] == "large"
    assert decision["audience"] == "group"
    assert decision["delivery"] == "popup"


def test_an_option_forces_a_pop_up_even_when_the_winning_rule_only_notifies():
    decision = decide([
        rule(name="Quiet", severity="critical", delivery="notify_only"),
        rule(name="Ring", severity="medium", sound="once"),
    ])

    assert decision["severity"] == "critical"
    assert decision["delivery"] == "popup"
    assert decision["sound"] == "once"


def test_rules_without_options_keep_todays_decision():
    decision = decide([rule(severity="info", delivery="default")])

    assert decision["delivery"] == "notify_only"
    assert decision["require_acknowledgment"] is False
    assert (decision["sound"], decision["size"], decision["audience"]) == ("off", "small", "owner")


def test_a_run_that_matches_nothing_reports_default_options():
    decision = decide([rule()], status="completed")

    assert decision["should_alert"] is False
    assert decision["require_acknowledgment"] is False
    assert decision["sound"] == "off"


def test_every_run_mode_is_unchanged():
    workflow = {"id": "wf-1", "user_id": "owner", "alert_mode": "every_run", "alert_priority": "high"}
    facts = build_workflow_alert_facts(workflow, {"id": "run-1", "status": "completed"}, {})

    decision = evaluate_workflow_alert_rules(workflow, facts)

    assert decision["delivery"] == "popup"
    assert decision["require_acknowledgment"] is False
    assert decision["audience"] == "owner"


def decide_with_model(rules, status="failed"):
    """Evaluate with a model that judges every condition it is asked about as met."""
    workflow = {
        "id": "wf-2",
        "name": "Team watch",
        "user_id": "owner",
        "group_id": "group-7",
        "alert_mode": "rules",
        "alert_rules": normalize_alert_rules(rules, workflow_scope="group"),
    }
    prompts = []

    def evaluator(prompt):
        prompts.append(prompt)
        model_rules = [rule for rule in workflow["alert_rules"] if rule["condition"]["type"] == "model_evaluation"]
        return json.dumps({"results": [
            {"rule_id": rule["id"], "matched": True, "reason": "The condition is met."} for rule in model_rules
        ]})

    facts = build_workflow_alert_facts(workflow, {"id": "run-1", "status": status}, {})
    return evaluate_workflow_alert_rules(workflow, facts, model_evaluator=evaluator), prompts


MODEL_RULE = {
    "id": "customer-impact",
    "name": "Customer impact",
    "severity": "medium",
    "delivery": "popup",
    "condition": {"type": "model_evaluation", "prompt": "Customers are affected."},
}


def test_a_lower_severity_model_rule_still_contributes_its_options():
    """A failing run must not alert more weakly than a completed one because a model rule was skipped."""
    model_rule = {**MODEL_RULE, "require_acknowledgment": True, "sound": "repeat", "audience": "group"}

    failed, failed_prompts = decide_with_model([rule(id="run-failed"), model_rule], status="failed")
    completed, _ = decide_with_model([rule(id="run-failed"), model_rule], status="completed")

    assert len(failed_prompts) == 1
    assert failed["model_evaluation"]["skipped_rule_ids"] == []
    assert failed["severity"] == "high"
    assert failed["require_acknowledgment"] is True
    assert (failed["sound"], failed["audience"]) == ("repeat", "group")
    assert (completed["require_acknowledgment"], completed["sound"], completed["audience"]) == (True, "repeat", "group")


def test_a_model_rule_that_cannot_change_the_alert_is_still_skipped():
    model_rule = {**MODEL_RULE, "sound": "once"}
    louder_rule = rule(id="run-failed", require_acknowledgment=True, sound="repeat")

    decision, prompts = decide_with_model([louder_rule, model_rule], status="failed")

    assert prompts == []
    assert decision["model_evaluation"]["skipped_rule_ids"] == ["customer-impact"]
    assert decision["sound"] == "repeat"


# --- Runner -----------------------------------------------------------------------------


def load_alert_creator(captured, decision, log_event):
    """Exec the runner's real alert builder with its collaborators replaced."""
    runner = APP / "functions_workflow_runner.py"
    names = {"_create_workflow_priority_alert", "_get_workflow_scope", "_get_workflow_group_id"}
    tree = ast.parse(runner.read_text(encoding="utf-8-sig"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(functions) == len(names)
    namespace = {
        "logging": logging,
        "log_event": log_event,
        "get_workflow_alert_signals": lambda: [],
        "resolve_workflow_alert_config": lambda workflow: {"alert_mode": "rules"},
        "build_workflow_alert_facts": lambda *args: {},
        "_workflow_alert_rules_need_model_evaluation": lambda *args: False,
        "_build_workflow_alert_model_evaluator": Mock(),
        "evaluate_workflow_alert_rules": lambda *args, **kwargs: dict(decision),
        "sanitize_workflow_alert_decision": lambda value: value,
        "_record_workflow_alert_decision": Mock(),
        "summarize_alert_decision": lambda value: "A rule matched.",
        "normalize_alert_severity": lambda value: value,
        "_normalize_workflow_alert_title_text": lambda value: value,
        "_build_workflow_alert_target_from_conversation": lambda conversation, default_label: None,
        "_select_preferred_workflow_alert_targets": lambda targets: targets,
        "_build_workflow_alert_content": lambda *args, **kwargs: {"alert_title": "Title"},
        "_summarize_workflow_alert_text": lambda value: value,
        "create_workflow_priority_notification": lambda **kwargs: captured.append(kwargs) or {"id": "n1"},
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(runner), "exec"), namespace)
    return namespace["_create_workflow_priority_alert"]


TEAM_DECISION = {
    "should_alert": True, "severity": "high", "category": "alert", "delivery": "popup", "mode": "rules",
    "matched_rules": [], "require_acknowledgment": True, "sound": "repeat", "size": "large", "audience": "group",
}


def test_a_group_audience_raises_one_shared_alert_for_a_group_workflow():
    captured = []
    create_alert = load_alert_creator(captured, TEAM_DECISION, Mock())
    workflow = {"id": "wf-2", "user_id": "owner", "name": "Team", "group_id": "group-7"}

    create_alert(workflow, {"id": "run-1", "status": "failed"}, {"id": "conversation-1"})

    call = captured[0]
    assert call["group_id"] == "group-7"
    metadata = call["metadata"]
    assert metadata["audience"] == "group"
    assert metadata["owner_user_id"] == "owner"
    assert metadata["require_acknowledgment"] is True
    assert (metadata["sound"], metadata["size"]) == ("repeat", "large")
    assert "group_id" not in metadata


def test_a_group_audience_falls_back_to_the_owner_outside_a_group():
    captured = []
    log_event = Mock()
    create_alert = load_alert_creator(captured, TEAM_DECISION, log_event)

    create_alert({"id": "wf-1", "user_id": "owner", "name": "Mine"}, {"id": "run-1"}, {"id": "c1"})

    call = captured[0]
    assert call["group_id"] is None
    assert call["user_id"] == "owner"
    assert call["metadata"]["audience"] == "owner"
    assert "owner_user_id" not in call["metadata"]
    assert any("Group audience ignored" in str(args[0]) for args, _ in log_event.call_args_list)


# --- Notifications ----------------------------------------------------------------------


def classify(query):
    if "ARRAY_CONTAINS(@group_ids" in query:
        return "team_pending" if "c.metadata.require_acknowledgment = true" in query else "team_unread"
    if "c.metadata.require_acknowledgment = true" in query:
        return "personal_pending"
    if query.startswith("SELECT TOP @limit") and "c.user_id = @user_id" in query:
        return "personal_unread"
    if "WHERE c.user_id = @user_id" in query:
        return "personal_all"
    if "WHERE c.group_id = @group_id" in query:
        return "group_all"
    return "other"


class FakeContainer:
    """An in-memory notifications container with ETag-conditional replace."""

    def __init__(self):
        self.docs = {}
        self.pages = {}
        self.calls = []
        self.writes = []
        self.before_replace = []
        self.version = 0

    def put(self, document):
        self.version += 1
        stored = deepcopy(document)
        stored["_etag"] = f"etag-{self.version}"
        self.docs[stored["id"]] = stored
        return deepcopy(stored)

    def query_items(self, query, parameters=None, partition_key=None, enable_cross_partition_query=False, **kwargs):
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        self.calls.append({
            "kind": classify(query), "query": query, "parameters": values,
            "partition_key": partition_key, "cross_partition": enable_cross_partition_query,
        })
        if "WHERE c.id = @notification_id" in query:
            document = self.docs.get(values["@notification_id"])
            return [deepcopy(document)] if document else []
        page = self.pages.get(classify(query), [])
        if partition_key is not None:
            # A single-partition read only ever sees that partition's documents.
            page = [document for document in page if document.get("user_id") == partition_key]
        return deepcopy(page)

    def replace_item(self, item, body, etag=None, match_condition=None, **kwargs):
        if self.before_replace:
            self.before_replace.pop(0)(self)
        stored = self.docs[item]
        if etag != stored["_etag"]:
            raise cosmos_exceptions.CosmosAccessConditionFailedError(status_code=412, message="changed")
        self.writes.append(item)
        return self.put(body)

    def upsert_item(self, body):
        self.writes.append(body["id"])
        return self.put(body)


MEMBERS = {"group-7": {"owner": "Owner", "member-1": "User", "member-2": "Admin"}}


def assert_group_role(user_id, group_id, allowed_roles=("Owner", "Admin")):
    assert_group_role.calls.append((user_id, group_id, tuple(allowed_roles)))
    if group_id not in MEMBERS:
        raise LookupError("Group not found")
    role = MEMBERS[group_id].get(user_id)
    if not role:
        raise PermissionError("User is not a member of this group")
    if role.lower() not in {value.lower() for value in allowed_roles}:
        raise PermissionError("Insufficient permissions for this group")
    return role


def stub_modules(container, log_event):
    replacements = {}
    for name, values in {
        "config": {"cosmos_notifications_container": container},
        "functions_appinsights": {"log_event": log_event},
        "functions_debug": {"debug_print": Mock()},
        "functions_group": {
            "assert_group_role": assert_group_role,
            "find_group_by_id": Mock(),
            "get_user_groups": lambda user: [{"id": group_id} for group_id, members in MEMBERS.items() if user in members],
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


def load_notifications(container):
    assert_group_role.calls = []
    log_event = Mock()
    spec = importlib.util.spec_from_file_location("test_ack_notifications", APP / "functions_notifications.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stub_modules(container, log_event)):
        spec.loader.exec_module(module)
    return module, log_event


def now(offset_hours=0):
    return (datetime.now(timezone.utc) - timedelta(hours=offset_hours)).isoformat()


def personal_alert(alert_id="p1", require_ack=True, **overrides):
    record = {
        "id": alert_id,
        "user_id": "owner",
        "group_id": None,
        "scope": "personal",
        "notification_type": "workflow_priority_alert",
        "title": "Ledger totals do not match",
        "message": "Payments run found 3 mismatched rows",
        "created_at": now(),
        "read_by": [],
        "dismissed_by": [],
        "metadata": {
            "priority": "critical", "category": "alert", "delivery": "popup",
            "require_acknowledgment": require_ack, "sound": "repeat" if require_ack else "off",
            "size": "large", "audience": "owner", "workflow_id": "wf-1", "workflow_name": "Payments",
        },
    }
    record.update(overrides)
    return record


def team_alert(alert_id="t1", require_ack=True, **overrides):
    record = {
        "id": alert_id,
        "user_id": None,
        "group_id": "group-7",
        "scope": "group",
        "notification_type": "workflow_priority_alert",
        "title": "Customer list exported to SECRET-PARTNER",
        "message": "The run read the private HR folder and found 4 records",
        "created_at": now(),
        "read_by": ["member-2"],
        "dismissed_by": [],
        "link_url": "/chats?conversationId=workflow-conversation",
        "link_context": {"workspace_type": "group", "conversation_id": "workflow-conversation"},
        "metadata": {
            "priority": "high", "category": "failure", "delivery": "popup",
            "require_acknowledgment": require_ack, "sound": "repeat" if require_ack else "off",
            "size": "medium", "audience": "group", "owner_user_id": "owner",
            "workflow_id": "wf-2", "workflow_name": "Nightly scan", "workflow_scope": "group",
            "workflow_group_id": "group-7", "run_id": "run-9", "status": "failed",
            "trigger_reason": "HIGH alert triggered by: Run failed, Leak found",
            "matched_rules": [
                {"rule_id": "r1", "rule_name": "Run failed", "severity": "high", "condition_type": "run_status",
                 "reason": "Workflow run failed"},
                {"rule_id": "r2", "rule_name": "Leak found", "severity": "medium",
                 "condition_type": "model_evaluation", "reason": "The output names SECRET-PARTNER"},
            ],
            "response_preview": "SECRET-PARTNER received 4 HR records",
            "error": "Traceback: SECRET-PARTNER",
            "event_title": "SECRET-PARTNER export",
            "alert_title": "SECRET-PARTNER export",
            "alert_summary": "4 HR records went to SECRET-PARTNER",
            "alert_detail": "Full detail about SECRET-PARTNER",
            "alert_enrichments": ["HR folder"],
            "agent_name": "hr-agent",
            "conversation_id": "workflow-conversation",
            "link_targets": [
                {"label": "Open created conversation", "link_url": "/chats?conversationId=team-room",
                 "conversation_id": "team-room",
                 "link_context": {"workspace_type": "group", "group_id": "group-7", "chat_type": "group-multi-user",
                                  "conversation_id": "team-room"}},
                {"label": "Open created conversation", "link_url": "/chats?conversationId=owner-private",
                 "conversation_id": "owner-private",
                 "link_context": {"workspace_type": "personal", "chat_type": "personal",
                                  "conversation_id": "owner-private"}},
                {"label": "Open created conversation", "link_url": "/chats?conversationId=other-group-room",
                 "conversation_id": "other-group-room",
                 "link_context": {"workspace_type": "group", "group_id": "group-8", "chat_type": "group-multi-user",
                                  "conversation_id": "other-group-room"}},
                {"label": "Open workflow", "link_url": "/chats?conversationId=workflow-conversation",
                 "conversation_id": "workflow-conversation",
                 "link_context": {"workspace_type": "group", "group_id": "group-7", "chat_type": "workflow",
                                  "conversation_id": "workflow-conversation"}},
            ],
        },
    }
    record.update(overrides)
    return record


def test_the_owner_acknowledges_a_personal_alert_and_it_records_who_and_when():
    container = FakeContainer()
    container.put(personal_alert())
    notifications, log_event = load_notifications(container)

    status, alert = notifications.acknowledge_workflow_alert("p1", "owner", display_name="  Pat   Owner ")

    assert status == "acknowledged"
    stored = container.docs["p1"]
    assert datetime.fromisoformat(stored["acknowledged_at"])
    assert stored["acknowledged_by"] == {"user_id": "owner", "display_name": "Pat Owner"}
    assert stored["read_by"] == ["owner"]
    assert alert["acknowledged"] is True
    assert alert["acknowledged_by_name"] == "Pat Owner"
    assert "acknowledged_by" not in alert
    assert any("[NOTIFICATIONS] Workflow alert acknowledged." == args[0] for args, _ in log_event.call_args_list)


def test_someone_else_cannot_acknowledge_a_personal_alert_or_learn_it_exists():
    container = FakeContainer()
    container.put(personal_alert())
    notifications, _ = load_notifications(container)

    other_user = notifications.acknowledge_workflow_alert("p1", "member-1")
    missing = notifications.acknowledge_workflow_alert("missing", "owner")
    blank = notifications.acknowledge_workflow_alert("", "owner")

    assert other_user == ("not_found", None)
    assert missing == ("not_found", None)
    assert blank == ("not_found", None)
    assert "acknowledged_at" not in container.docs["p1"]
    assert container.writes == []


def test_any_current_member_acknowledges_a_team_alert_for_everyone():
    container = FakeContainer()
    container.put(team_alert())
    notifications, _ = load_notifications(container)

    status, alert = notifications.acknowledge_workflow_alert("t1", "member-1", display_name="Jane")

    assert status == "acknowledged"
    assert assert_group_role.calls == [("member-1", "group-7", ("Owner", "Admin", "DocumentManager", "User"))]
    assert container.docs["t1"]["acknowledged_by"]["display_name"] == "Jane"
    # The acknowledging member reads the reduced alert, and only their own read state.
    assert alert["content_scope"] == "member"
    assert alert["read_by"] == ["member-1"]


@pytest.mark.parametrize("user_id", ["stranger", "", None])
def test_a_non_member_cannot_acknowledge_a_team_alert(user_id):
    container = FakeContainer()
    container.put(team_alert())
    notifications, _ = load_notifications(container)

    result = notifications.acknowledge_workflow_alert("t1", user_id)

    assert result == ("not_found", None)
    assert "acknowledged_at" not in container.docs["t1"]


def test_a_team_alert_from_a_deleted_group_cannot_be_acknowledged():
    container = FakeContainer()
    container.put(team_alert(group_id="group-gone"))
    notifications, _ = load_notifications(container)

    result = notifications.acknowledge_workflow_alert("t1", "member-1")

    assert result == ("not_found", None)


def test_an_alert_that_needs_no_acknowledgment_is_refused():
    container = FakeContainer()
    container.put(personal_alert(require_ack=False))
    container.put({"id": "chat", "user_id": "owner", "scope": "personal", "notification_type": "chat_response_complete"})
    notifications, _ = load_notifications(container)

    quiet_alert = notifications.acknowledge_workflow_alert("p1", "owner")
    other_type = notifications.acknowledge_workflow_alert("chat", "owner")

    assert quiet_alert == ("not_required", None)
    assert other_type == ("not_found", None)
    assert container.writes == []


def test_the_first_acknowledgment_wins():
    container = FakeContainer()
    container.put(team_alert(acknowledged_at="2026-10-03T10:42:00+00:00",
                             acknowledged_by={"user_id": "member-2", "display_name": "Jane"}))
    notifications, _ = load_notifications(container)

    status, alert = notifications.acknowledge_workflow_alert("t1", "member-1", display_name="Bob")

    assert status == "already_acknowledged"
    assert container.docs["t1"]["acknowledged_by"] == {"user_id": "member-2", "display_name": "Jane"}
    assert alert["acknowledged_by_name"] == "Jane"
    # The caller's own read state is still recorded.
    assert "member-1" in container.docs["t1"]["read_by"]


def test_an_acknowledgment_that_loses_a_race_keeps_the_winner():
    container = FakeContainer()
    container.put(team_alert())
    notifications, _ = load_notifications(container)

    def jane_acknowledges_first(store):
        winner = deepcopy(store.docs["t1"])
        winner["acknowledged_at"] = "2026-10-03T10:42:00+00:00"
        winner["acknowledged_by"] = {"user_id": "member-2", "display_name": "Jane"}
        store.put(winner)

    container.before_replace.append(jane_acknowledges_first)

    status, _ = notifications.acknowledge_workflow_alert("t1", "member-1", display_name="Bob")

    assert status == "already_acknowledged"
    assert container.docs["t1"]["acknowledged_by"]["display_name"] == "Jane"


def test_a_stale_read_or_dismissal_cannot_undo_an_acknowledgment():
    container = FakeContainer()
    container.put(team_alert())
    notifications, _ = load_notifications(container)

    def someone_acknowledges(store):
        acknowledged = deepcopy(store.docs["t1"])
        acknowledged["acknowledged_at"] = "2026-10-03T10:42:00+00:00"
        acknowledged["acknowledged_by"] = {"user_id": "member-2", "display_name": "Jane"}
        store.put(acknowledged)

    container.before_replace.append(someone_acknowledges)
    read = notifications.mark_notification_read("t1", "member-1")
    container.before_replace.append(someone_acknowledges)
    dismissed = notifications.dismiss_notification("t1", "owner")

    assert read is True
    assert dismissed is True
    stored = container.docs["t1"]
    assert stored["acknowledged_at"] == "2026-10-03T10:42:00+00:00"
    assert "member-1" in stored["read_by"]
    assert "owner" in stored["dismissed_by"]


def test_reading_dismissing_and_marking_all_read_never_acknowledge():
    container = FakeContainer()
    container.put(personal_alert())
    container.pages["personal_all"] = [deepcopy(container.docs["p1"])]
    notifications, log_event = load_notifications(container)

    with patch.dict(sys.modules, stub_modules(container, log_event)):
        marked_all = notifications.mark_all_read("owner")
    read = notifications.mark_notification_read("p1", "owner")
    dismissed = notifications.dismiss_notification("p1", "owner")

    assert marked_all == 1
    assert read is True
    assert dismissed is True
    stored = container.docs["p1"]
    assert stored["read_by"] == ["owner"]
    assert stored["dismissed_by"] == ["owner"]
    assert "acknowledged_at" not in stored


def test_a_write_that_keeps_conflicting_gives_up_without_overwriting():
    container = FakeContainer()
    container.put(personal_alert())
    notifications, _ = load_notifications(container)

    def touch(store):
        store.put(deepcopy(store.docs["p1"]))

    container.before_replace.extend([touch, touch, touch])

    read = notifications.mark_notification_read("p1", "owner")

    assert read is False
    assert container.docs["p1"]["read_by"] == []


def test_members_other_than_the_owner_never_receive_the_runs_output():
    container = FakeContainer()
    notifications, _ = load_notifications(container)

    member = notifications._decorate_workflow_alert(team_alert(), "member-1")
    owner = notifications._decorate_workflow_alert(team_alert(), "owner")

    assert member["content_scope"] == "member"
    assert member["title"] == "High priority workflow alert: Nightly scan"
    assert member["message"] == "Matched Run failed and Leak found. Open it for details."
    assert "SECRET-PARTNER" not in repr(member)
    assert "HR" not in repr({key: value for key, value in member.items() if key not in {"read_by", "dismissed_by"}})
    assert member["metadata"]["matched_rules"] == [
        {"rule_id": "r1", "rule_name": "Run failed", "severity": "high", "condition_type": "run_status"},
        {"rule_id": "r2", "rule_name": "Leak found", "severity": "medium", "condition_type": "model_evaluation"},
    ]
    # Only the group conversation the run created in this group survives.
    assert [target["conversation_id"] for target in member["metadata"]["link_targets"]] == ["team-room"]
    assert member["link_url"] == "/chats?conversationId=team-room"
    assert "owner_user_id" not in member["metadata"]
    # A member sees only their own read state, never other members' ids.
    assert member["read_by"] == []
    assert member["require_acknowledgment"] is True
    assert (member["sound"], member["size"], member["audience"]) == ("repeat", "medium", "group")

    assert owner["content_scope"] == "full"
    assert owner["metadata"]["alert_summary"] == "4 HR records went to SECRET-PARTNER"
    assert owner["title"] == "Customer list exported to SECRET-PARTNER"


def test_a_team_alert_without_a_recorded_owner_is_reduced_for_everyone():
    alert = team_alert()
    del alert["metadata"]["owner_user_id"]
    notifications, _ = load_notifications(FakeContainer())

    decorated = notifications._decorate_workflow_alert(alert, "owner")

    assert decorated["content_scope"] == "member"


def test_the_bell_list_reduces_team_alerts_for_members():
    container = FakeContainer()
    container.pages["group_all"] = [team_alert()]
    notifications, log_event = load_notifications(container)

    # The bell list imports its group and workspace lookups when it runs.
    with patch.dict(sys.modules, stub_modules(container, log_event)):
        page = notifications.get_user_notifications("member-1")

    assert [item["id"] for item in page["notifications"]] == ["t1"]
    item = page["notifications"][0]
    assert item["content_scope"] == "member"
    assert "SECRET-PARTNER" not in repr(item)
    assert item["is_read"] is False


def test_must_acknowledge_alerts_pop_up_whatever_their_age_or_read_state():
    container = FakeContainer()
    old_and_read = personal_alert("p-old", created_at=now(72), read_by=["owner"], dismissed_by=["owner"])
    container.pages["personal_unread"] = [personal_alert("p-new", require_ack=False)]
    container.pages["personal_pending"] = [
        old_and_read,
        personal_alert("p-done", acknowledged_at="2026-10-01T00:00:00+00:00"),
    ]
    container.pages["team_unread"] = [team_alert("t-regular", require_ack=False, read_by=[])]
    container.pages["team_pending"] = [team_alert("t-pending")]
    notifications, _ = load_notifications(container)

    result = notifications.get_workflow_alert_popups("member-1", limit=10, since_hours=24)

    ids = [item["id"] for item in result["notifications"]]
    assert sorted(ids) == ["t-pending", "t-regular"]
    assert result["complete"] is True

    owner_result = notifications.get_workflow_alert_popups("owner", limit=10, since_hours=24)
    owner_ids = [item["id"] for item in owner_result["notifications"]]
    assert "p-old" in owner_ids and "p-new" in owner_ids
    assert "p-done" not in owner_ids
    old = next(item for item in owner_result["notifications"] if item["id"] == "p-old")
    assert old["is_read"] is True and old["require_acknowledgment"] is True


def test_popup_reads_are_bounded_scoped_and_only_the_unread_reads_take_the_window():
    container = FakeContainer()
    notifications, _ = load_notifications(container)

    notifications.get_workflow_alert_popups("member-1", limit=4, since_hours=24)

    by_kind = {call["kind"]: call for call in container.calls}
    assert set(by_kind) == {"personal_unread", "personal_pending", "team_unread", "team_pending"}
    for call in by_kind.values():
        assert call["parameters"]["@limit"] == 4
        assert "member-1" not in call["query"]
    assert by_kind["personal_pending"]["partition_key"] == "member-1"
    assert "@created_after" in by_kind["personal_unread"]["parameters"]
    assert "@created_after" in by_kind["team_unread"]["parameters"]
    assert "@created_after" not in by_kind["personal_pending"]["parameters"]
    assert "@created_after" not in by_kind["team_pending"]["parameters"]
    # Group alerts come only from the groups the server resolves for the caller.
    assert by_kind["team_pending"]["parameters"]["@group_ids"] == ["group-7"]
    assert by_kind["team_pending"]["cross_partition"] is True


def test_a_full_bounded_read_marks_the_answer_incomplete():
    container = FakeContainer()
    container.pages["team_pending"] = [team_alert(f"t{index}") for index in range(2)]
    notifications, _ = load_notifications(container)

    result = notifications.get_workflow_alert_popups("member-1", limit=2)

    assert result["complete"] is False


def test_a_user_in_no_group_runs_no_group_reads():
    container = FakeContainer()
    notifications, _ = load_notifications(container)

    notifications.get_workflow_alert_popups("loner", limit=5)

    assert {call["kind"] for call in container.calls} == {"personal_unread", "personal_pending"}


def test_a_team_alert_is_created_in_the_group_scope():
    created = []
    container = FakeContainer()
    container.create_item = lambda document: created.append(document) or document
    notifications, _ = load_notifications(container)

    notifications.create_workflow_priority_notification(
        user_id="owner", workflow_id="wf-2", workflow_name="Nightly scan", priority="high",
        title="t", message="m", metadata={"run_id": "run-1"}, group_id=" group-7 ",
    )
    notifications.create_workflow_priority_notification(
        user_id="owner", workflow_id="wf-1", workflow_name="Mine", priority="high", title="t", message="m",
    )

    team, personal = created
    assert (team["scope"], team["group_id"], team["user_id"]) == ("group", "group-7", None)
    assert team["metadata"]["owner_user_id"] == "owner"
    assert team["metadata"]["audience"] == "group"
    assert (personal["scope"], personal["user_id"]) == ("personal", "owner")
    assert "owner_user_id" not in personal["metadata"]


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-q"]))
