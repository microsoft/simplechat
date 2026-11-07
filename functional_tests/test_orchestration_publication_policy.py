# test_orchestration_publication_policy.py
"""
Functional tests for scoped publication, approval and reconciliation denial.
Version: 0.261.127
Implemented in: 0.261.127

Real publication functions use external storage/notification/queue doubles.
Cold normal/optimized probes import real operations, web and scheduler modules.
No provider calls or real user artifacts are created.
"""

from contextlib import ExitStack, nullcontext
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from test_analysis_artifact_publication import publication, publish  # noqa: F401
from test_orchestration_file_policy import run_probe
from test_workflow_publication_completion import (
    document as destination_document,
    receipt as saved_receipt,
    request as publication_request,
    submit,
)
from functions_orchestration_execution_policy import (
    OrchestrationFilePolicyError,
    orchestration_file_policy,
)


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"


def effect_snapshot(fixture):
    containers = {"messages": fixture.messages, "notifications": fixture.notifications, **fixture.destinations}
    return {
        "records": {name: deepcopy(container.records) for name, container in containers.items()},
        "writes": {name: container.writes for name, container in containers.items()},
        "calls": {name: deepcopy(fixture.calls[name]) for name in ("create", "update", "queue", "notify")},
    }


@pytest.mark.parametrize("scope", ["personal", "group", "public"])
@pytest.mark.parametrize("private", [False, True])
def test_denied_publication_has_no_destination_receipt_notification_or_queue_effect(publication, scope, private):
    before = effect_snapshot(publication)
    destination = {"workspace_scope": scope}
    if scope != "personal":
        destination["group_id" if scope == "group" else "public_workspace_id"] = f"fixed-{scope}"
    with orchestration_file_policy(allow_generated_files=False), ExitStack() as resources:
        target = (
            publication.module._publish_generated_chat_artifact_for_user if private
            else publication.module.publish_generated_chat_artifact_for_user
        )
        with pytest.raises(OrchestrationFilePolicyError):
            target(
                "actor", conversation_id="conversation-1", message_id="artifact-1",
                destination=destination, request_id="explicit-request",
                **({"resources": resources} if private else {}),
            )
    after = effect_snapshot(publication)
    assert after == before
    assert publication.messages.reads == 0
    assert publication.calls["download"] == []


@pytest.mark.parametrize("entry", ["publish_workflow_artifact", "publish_workflow_analysis_artifact"])
def test_denied_workflow_publication_fails_before_access_or_effects(publication, entry):
    before = effect_snapshot(publication)
    with orchestration_file_policy(allow_generated_files=False):
        with pytest.raises(OrchestrationFilePolicyError):
            getattr(publication.module, entry)(
                "actor", publication={"artifact_format": "md", "workspace_scope": "personal"},
                artifact_reference={"conversation_id": "conversation-1", "artifact_message_id": "artifact-1"},
                request_id="workflow-request",
            )
    after = effect_snapshot(publication)
    assert after == before
    assert publication.messages.reads == 0


@pytest.mark.parametrize("entry", ["publish_workflow_artifact", "publish_workflow_analysis_artifact"])
def test_absent_publication_intent_remains_a_noop_inside_denied_scope(publication, entry):
    before = effect_snapshot(publication)
    with orchestration_file_policy(allow_generated_files=False):
        result = getattr(publication.module, entry)(
            "actor", publication=None, artifact_reference=None, request_id=None,
        )
    after = effect_snapshot(publication)
    assert result["execution_status"] == "skipped"
    assert result["publication"]["state"] == "not_requested"
    assert after == before
    assert publication.messages.reads == 0


@pytest.mark.parametrize("scope", ["group", "public"])
@pytest.mark.parametrize("choice", ["approved", "rejected", "cancelled"])
@pytest.mark.parametrize("entry", [
    "decide_artifact_publication", "_decide_artifact_publication", "_decide_artifact_publication_with_content",
])
def test_denied_workspace_decisions_leave_receipts_destinations_and_notices_unchanged(
    publication, scope, choice, entry,
):
    result = submit(publication, "approved", scope)
    publication.state["group_role"] = "DocumentManager"
    target = destination_document(publication, result)
    before = effect_snapshot(publication)
    with orchestration_file_policy(allow_generated_files=False), ExitStack() as resources:
        with pytest.raises(OrchestrationFilePolicyError):
            getattr(publication.module, entry)(
                "actor" if choice == "cancelled" else "reviewer", target, choice,
                **({"resources": resources} if entry.endswith("_with_content") else {}),
            )
    after = effect_snapshot(publication)
    assert after == before


@pytest.mark.parametrize("effect", ["receipt", "stage", "destination", "notification"])
def test_direct_effect_helpers_cannot_bypass_publication_policy(publication, effect):
    result = submit(publication, "approved", "group")
    saved = saved_receipt(publication, result)
    callback = Mock(return_value={"id": "not-created"})
    before = effect_snapshot(publication)
    with orchestration_file_policy(allow_generated_files=False):
        with pytest.raises(OrchestrationFilePolicyError):
            if effect == "receipt":
                publication.module._receipt_change(
                    publication.artifact, saved["id"], lambda current: {**current, "new_state": "forbidden"},
                )
            elif effect == "stage":
                publication.module._stage(publication.artifact, saved, "forbidden_stage")
            elif effect == "destination":
                publication.module._replace_publication_destination(
                    publication.destinations["group"], saved, {"generated_artifact_promotion_status": "approved"},
                )
            else:
                publication.module._notify_once(
                    publication.artifact, saved, "forbidden_notice", "approval_request_approved", callback,
                )
    after = effect_snapshot(publication)
    assert after == before
    assert callback.call_count == 0


@pytest.mark.parametrize("allowed", [None, True])
def test_read_only_observation_stays_available_but_write_reconciliation_is_guarded(publication, allowed):
    result = submit(publication)
    artifact = deepcopy(publication.messages.records["artifact-1"])
    artifact["metadata"][publication.module.RECEIPTS_FIELD][result["publication"]["id"]]["stages"]["create"] = "started"
    publication.messages.put(artifact)
    request = publication_request(publication, result)
    before = effect_snapshot(publication)
    owned = Mock()

    with orchestration_file_policy(allow_generated_files=False):
        with pytest.raises(OrchestrationFilePolicyError):
            publication.module.read_workflow_artifact_publication(
                "actor", request, reconcile=True, execution_check=owned,
            )
        observed = publication.module.read_workflow_artifact_publication("actor", request)
        authorized = publication.module.read_workflow_artifact_publication("actor", request, authorization_only=True)
        publication.module.authorize_publication_status_read("actor", observed["publication"], actor_user_id="actor")
        receipt_read, changed = publication.module._receipt_change(
            publication.artifact, result["publication"]["id"], lambda current: None,
        )

    after_read = effect_snapshot(publication)
    assert observed["publication"]["state"] == "uncertain"
    assert authorized is None and changed is False
    assert receipt_read["stages"]["create"] == "started"
    assert after_read == before
    assert owned.call_count == 0

    with nullcontext() if allowed is None else orchestration_file_policy(allow_generated_files=allowed):
        reconciled = publication.module.read_workflow_artifact_publication(
            "actor", request, reconcile=True, execution_check=owned,
        )
    saved = saved_receipt(publication, result)
    after_reconciliation = effect_snapshot(publication)
    assert saved["stages"]["create"] == "complete"
    assert reconciled["publication"]["state"] == "submitted"
    assert after_reconciliation["writes"]["messages"] == before["writes"]["messages"] + 1
    assert after_reconciliation["calls"] == before["calls"]
    assert owned.call_count > 0


def test_read_only_observation_still_rechecks_source_authority(publication):
    result = submit(publication)
    request = publication_request(publication, result)
    before = effect_snapshot(publication)
    publication.state["source_allowed"] = False
    with orchestration_file_policy(allow_generated_files=False):
        with pytest.raises(PermissionError) as rejected:
            publication.module.read_workflow_artifact_publication("actor", request)
    after = effect_snapshot(publication)
    assert not isinstance(rejected.value, OrchestrationFilePolicyError)
    assert after == before


@pytest.mark.parametrize("allowed", [None, True])
@pytest.mark.parametrize("scope", ["personal", "group", "public"])
def test_standalone_and_explicit_render_publication_defaults_are_unchanged(publication, allowed, scope):
    with nullcontext() if allowed is None else orchestration_file_policy(allow_generated_files=allowed):
        first = publish(publication, scope)
        repeated = publish(publication, scope)
    assert first["publication"] == repeated["publication"]
    assert first["publication"]["state"] == ("queued" if scope == "personal" else "pending_approval")
    assert len(publication.calls["create"]) == 1
    assert len(publication.calls["queue"]) == (1 if scope == "personal" else 0)
    assert len(publication.calls["notify"]) == (0 if scope == "personal" else 2)


@pytest.mark.parametrize("allowed", [None, True])
def test_standalone_and_explicit_render_approval_defaults_are_unchanged(publication, allowed):
    result = submit(publication, "approved", "group")
    publication.state["group_role"] = "DocumentManager"
    target = destination_document(publication, result)
    with nullcontext() if allowed is None else orchestration_file_policy(allow_generated_files=allowed):
        decision = publication.module.decide_artifact_publication("reviewer", target, "approved")
    saved = saved_receipt(publication, result)
    assert decision["message"] == "Publication approved."
    assert saved["decision"]["choice"] == "approved"
    assert len(publication.calls["queue"]) == 1
    assert len(publication.calls["notify"]) == 3


@pytest.mark.parametrize("effect", [
    "create_document", "update_document", "queue_generated_document_processing", "create_group_notification",
])
def test_policy_denial_from_an_effect_is_not_swallowed_as_uncertain_publication(publication, monkeypatch, effect):
    rejected = Mock(side_effect=OrchestrationFilePolicyError)
    log = Mock()
    monkeypatch.setattr(publication.module, effect, rejected)
    monkeypatch.setattr(publication.module, "_log_uncertain", log)
    with pytest.raises(OrchestrationFilePolicyError):
        publish(publication, "group" if effect == "create_group_notification" else "personal")
    assert rejected.call_count == 1
    assert log.call_count == 0


def test_approval_queue_policy_denial_does_not_record_a_false_processing_failure(publication, monkeypatch):
    result = submit(publication, "approved", "group")
    publication.state["group_role"] = "DocumentManager"
    snapshots = []

    def denied_queue(**kwargs):
        snapshots.append(effect_snapshot(publication))
        raise OrchestrationFilePolicyError()

    monkeypatch.setattr(publication.module, "queue_generated_document_processing", denied_queue)
    target = destination_document(publication, result)
    with pytest.raises(OrchestrationFilePolicyError):
        publication.module.decide_artifact_publication("reviewer", target, "approved")
    after = effect_snapshot(publication)
    assert len(snapshots) == 1
    assert after == snapshots[0]


APPROVAL_PROBE = r'''
from contextlib import ExitStack
from copy import deepcopy
import importlib
import sys
from unittest.mock import Mock, patch

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports
from functions_orchestration_execution_policy import (
    OrchestrationFilePolicyError, orchestration_file_policy,
)

def check(value, message):
    if not value:
        raise AssertionError(message)

with offline_app_imports() as environment:
    for name in sys.argv[3:]:
        importlib.import_module(name)
    if "app" in sys.argv[3:]:
        check(hasattr(importlib.import_module("app"), "app"), "Web bootstrap did not complete")
    check(callable(importlib.import_module("background_tasks").check_m365_workflow_continuations_once),
          "Scheduler bootstrap did not complete")
    publication = importlib.import_module("functions_artifact_publication")
    operations = importlib.import_module("functions_simplechat_operations")
    pending = {
        "id": "artifact", "conversation_id": "conversation", "role": "file",
        "metadata": {
            "is_generated_chat_artifact": True, "generated_artifact_approval_required": True,
            "generated_artifact_approval_state": operations.APPROVAL_STATE_PENDING,
            "generated_artifact_approval_requested_by_id": "requester",
        },
    }
    effects = {"apply": [], "delete": [], "write": [], "clear": [], "notify": [], "list": []}
    apply_decision = operations.apply_generated_file_approval_decision

    class Messages:
        reads = 0
        def read_item(self, **kwargs):
            self.reads += 1
            return deepcopy(pending)
        def upsert_item(self, value):
            effects["write"].append(deepcopy(value))

    def apply(message, decision, **kwargs):
        effects["apply"].append(decision)
        return apply_decision(message, decision, **kwargs)

    def expired():
        effects["list"].append(True)
        return [deepcopy(pending)]

    messages = Messages()
    replacements = {
        "cosmos_messages_container": messages,
        "user_can_approve_generated_file": lambda *args: True,
        "_get_current_user_summary_or_none": lambda *args: {"user_id": "owner", "display_name": "Owner"},
        "apply_generated_file_approval_decision": apply,
        "delete_blob_backed_chat_message_files": lambda value: effects["delete"].append(deepcopy(value)),
        "_clear_generated_file_approval_notifications": lambda value: effects["clear"].append(value),
        "_notify_generated_file_approval_resolved": lambda *args, **kwargs: effects["notify"].append(args[1]),
        "list_expired_pending_generated_file_artifacts": expired,
        "log_event": lambda *args, **kwargs: None,
    }
    with ExitStack() as resources:
        for name, value in replacements.items():
            resources.enter_context(patch.object(operations, name, value))
        forbidden_effect = Mock(side_effect=AssertionError("Denied publication attempted an effect."))
        for name in ("create_document", "update_document", "create_notification", "queue_generated_document_processing"):
            resources.enter_context(patch.object(publication, name, forbidden_effect))
        with orchestration_file_policy(allow_generated_files=False):
            denied = [
                lambda: publication.publish_generated_chat_artifact_for_user(
                    "owner", conversation_id="conversation", message_id="artifact",
                    destination={"workspace_scope": "personal"}, request_id="request",
                ),
                lambda: publication.decide_artifact_publication("owner", {}, "approved"),
                lambda: publication.read_workflow_artifact_publication("owner", {}, reconcile=True),
                lambda: operations.resolve_generated_file_approval_for_user("owner", "conversation", "artifact", "approved"),
                lambda: operations.resolve_generated_file_approval_for_user("owner", "conversation", "artifact", "denied"),
                operations.auto_deny_expired_generated_file_approvals,
            ]
            for action in denied:
                try:
                    action()
                except OrchestrationFilePolicyError:
                    continue
                raise AssertionError("An effect boundary escaped its denied scope.")
        check(not any(effects.values()), "Denied approval mutated state or queried the expiry queue")
        check(messages.reads == 0, "Denied approval read the target before the entry guard")
        check(forbidden_effect.call_count == 0, "Denied publication created a destination or notification")
        approved = operations.resolve_generated_file_approval_for_user("owner", "conversation", "artifact", "approved")
        denied = operations.resolve_generated_file_approval_for_user("owner", "conversation", "artifact", "denied")
        expired_count = operations.auto_deny_expired_generated_file_approvals()
        check(approved["metadata"]["generated_artifact_approval_state"] == "approved", "Default approval changed")
        check(denied["metadata"]["generated_artifact_approval_state"] == "denied", "Default denial changed")
        check(expired_count == 1, "Default automatic expiry changed")
        check(effects["apply"] == ["approved", "denied", "auto_denied"], "Approval transitions changed")
        check(len(effects["write"]) == len(effects["clear"]) == len(effects["notify"]) == 3,
              "Default approval persistence/notifications changed")
        check(len(effects["delete"]) == 2, "Default denial/expiry no longer releases blobs")
    check(not environment.network_attempts, "Cold policy checks attempted external I/O")
print("PASS: real publication/approval guards, default effects, web/scheduler imports")
'''


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("functions_artifact_publication", "app", "background_tasks"),
    ("app", "functions_artifact_publication", "background_tasks"),
    ("background_tasks", "functions_artifact_publication"),
])
def test_real_approval_guards_and_cold_imports(order, optimized):
    run_probe(APPROVAL_PROBE, [str(APP), str(TESTS), *order], optimized)
