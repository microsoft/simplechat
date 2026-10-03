#!/usr/bin/env python3
# test_m365_run_as_self_authored.py
"""
Functional test for Microsoft 365 workflow Run as approval when the Run as user saved the revision.
Version: 0.261.229
Implemented in: 0.261.229
Refs: microsoft/simplechat#1621

This test ensures that a workflow revision saved by its own Run as user runs as them without a
pending approval: the real approval service records an approved, audited, self-authored binding
for that exact revision and connection, and sends no notification. A revision someone else saved,
a later edit by someone else to the workflow or to an agent or action it runs, a missing
``modified_by``, or a changed Microsoft 365 connection still asks the Run as user. An audience
change never asks again. A denial or cancellation recorded for a run still stops that run, and a
revoked self-authored binding is never silently re-created. Every save path records the
authenticated actor as ``modified_by``, never the payload, and a raw administrator edit names
the administrator.

The approval service and execution boundary are the real modules over the conditional Cosmos
fakes in ``test_support.m365``. The runtime manifest test loads the real
``functions_m365_runtime`` with its cloud dependencies stubbed, and the save tests run the real
workflow stores and save routes through the save parity harness.
"""

import copy
import importlib.util
import os
import sys
import types
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask, g

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Application imports follow the test-only source-path setup.
import functions_m365_approvals as approvals  # noqa: E402
import functions_m365_connections as connections  # noqa: E402
import functions_m365_execution as execution  # noqa: E402
from functions_m365_data_lifecycle import (  # noqa: E402
    M365_AUTHORED_RECORD_CONTAINERS,
    RAW_EDITOR_AUTHOR,
    attribute_raw_authored_record_edit,
)
from functions_m365_workflow_binding import (  # noqa: E402
    M365_REVISION_AUTHORSHIP_FIELD,
    workflow_execution_fingerprint,
    workflow_revision_self_authored,
)
from test_support.m365 import Clock, CosmosContainer, Notifications, WORKFLOW_REVIEW  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


RUN_AS = "run-as-user"
EDITOR = "group-editor"
OWNER = "workflow-owner"
ADMIN = "app-admin"
TENANT = "tenant-a"
WORKFLOW_ID = "workflow-a"
CONVERSATION = "conversation-a"
# Workflow stores write aware UTC times; agent and action stores write naive UTC times.
SAVED_AT = "2026-03-08T04:00:00+00:00"
BEFORE_SAVE = "2026-03-08T03:00:00.000000"
AFTER_SAVE = "2026-03-08T04:30:00.000000"
EDITED_AT = datetime(2026, 3, 9, tzinfo=timezone.utc)


def manifest(**changes):
    value = {
        "id": "mail", "name": "mail", "type": "m365_email", "enabled_functions": ["get_my_messages"],
        "additionalFields": {"maximum_sharing_acknowledgement": "always"},
    }
    value.update(changes)
    return value


def authored(kind, modified_by, modified_at):
    return {"kind": kind, "id": f"{kind}-1", "modified_by": modified_by, "modified_at": modified_at}


def workflow(*, modified_by=RUN_AS, modified_at=SAVED_AT, prompt="Summarize my mail.", authorship=None):
    """The stored workflow as the runtime hands it to the binding, with its components' authorship."""
    value = {
        "id": WORKFLOW_ID, "user_id": OWNER, "task_prompt": prompt, "m365_run_as_user_id": RUN_AS,
        "modified_by": modified_by, "modified_at": modified_at,
        M365_REVISION_AUTHORSHIP_FIELD: authorship if authorship is not None else [
            authored("agent", RUN_AS, BEFORE_SAVE), authored("action", OWNER, BEFORE_SAVE),
        ],
    }
    if modified_by is None:
        value.pop("modified_by")
    return value


class Harness:
    """The real approval service and execution boundary for one Run as user's runs."""

    def __init__(self):
        self.clock = Clock()
        self.container = CosmosContainer()
        self.notifications = Notifications()
        self.service = approvals.M365ApprovalService(
            container_factory=lambda: self.container, notification_sender=self.notifications,
            decision_validator=lambda approval: True, clock=self.clock,
        )
        self.connection = {
            "id": "connection-a", "user_id": RUN_AS, "tenant_id": TENANT,
            "generation": 1, "status": "connected", "sources": ["email"],
        }
        self.runs = 0

    def current_connection(self, user_id, tenant_id):
        assert (user_id, tenant_id) == (RUN_AS, TENANT)
        return copy.deepcopy(self.connection)

    def context(self, run_id, audience):
        return execution.M365ExecutionContext(
            actor_user_id=OWNER, data_user_id=RUN_AS, tenant_id=TENANT,
            conversation_id=CONVERSATION, shared=True, request_id=run_id,
            workflow_id=WORKFLOW_ID, run_id=run_id, audience_version=audience,
        )

    def prepare(self, stored, *, run_id=None, audience="audience-1", manifests=None):
        """Bind one run, as the workflow runtime does before any Microsoft 365 operation."""
        self.runs += 1
        context = self.context(run_id or f"run-{self.runs}", audience)
        return execution.prepare_m365_workflow_binding(
            context, stored, manifests if manifests is not None else [manifest()], review=WORKFLOW_REVIEW,
        )

    def validate(self, prepared):
        """The check every Microsoft 365 operation of the run makes."""
        return self.service.validate_workflow_binding(prepared, copy.deepcopy(self.connection), "email")

    def run(self, stored, **options):
        prepared = self.prepare(stored, **options)
        return prepared, self.validate(prepared)

    def waits(self, stored, **options):
        """Run once and return, as the approvals UI sees it, the pending approval the run waits for."""
        prepared = self.prepare(stored, **options)
        with pytest.raises(approvals.M365ApprovalRequired) as raised:
            self.validate(prepared)
        assert raised.value.request_type == approvals.TYPE_WORKFLOW_RUN_AS
        return prepared, approvals.sanitize_m365_approval(
            self.service.get_approval(raised.value.approval_id, RUN_AS),
        )

    def approve(self, approval_id):
        return self.service.decide(approval_id, RUN_AS, {"choice": "approve"})

    def bindings(self, **fields):
        return [
            item for item in self.container.items.values()
            if item.get("record_kind") == "m365_approval"
            and item.get("request_type") == approvals.TYPE_WORKFLOW_RUN_AS
            and all(item.get(key) == value for key, value in fields.items())
        ]

    def audit(self, event_type):
        return [
            item for item in self.container.items.values()
            if item.get("record_kind") == "m365_audit" and item.get("event_type") == event_type
        ]


@pytest.fixture
def harness():
    value = Harness()
    connection_service = types.SimpleNamespace(current_connection=value.current_connection)
    with patch.object(approvals, "_service", value.service), \
            patch.object(connections, "_service", connection_service), \
            patch.object(execution, "_workflow_validator", lambda context: True):
        yield value


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.229")


# ---------------------------------------------------------------------------------------------
# A revision its Run as user saved
# ---------------------------------------------------------------------------------------------

def test_a_self_authored_first_run_is_approved_audited_and_silent(harness):
    prepared, allowed = harness.run(workflow())

    record = harness.service.get_approval(prepared.binding_id, RUN_AS)
    assert allowed["status"] == "approved" and allowed["self_authored"] is True
    assert record["status"] == "approved" and record["self_authored"] is True
    assert record["approved_by_id"] == RUN_AS and record["requester_id"] == OWNER
    assert record["binding"]["workflow_fingerprint"] == prepared.workflow_fingerprint
    assert record["binding"]["connection_id"] == "connection-a"
    assert record["binding"]["connection_generation"] == 1
    assert record["binding"]["review"] == WORKFLOW_REVIEW
    assert "expires_at" not in record
    assert record["execution_status"] == "not_required"
    assert record["continuation_status"] == "delivered"
    # No notification, and nothing is ever pending or queued for continuation.
    continuations = harness.service.list_pending_continuations()["items"]
    assert harness.notifications.calls == []
    assert harness.bindings(status="pending") == []
    assert continuations == []
    [event] = harness.audit("self_authored_approved")
    assert event["approval_id"] == prepared.binding_id
    assert event["id"] == record["decision_event_id"]
    assert event["context"]["workflow_fingerprint"] == prepared.workflow_fingerprint
    assert (event["connection_generation"], event["sources"]) == (1, ["email"])
    # The bindings route lists it, approved, with a reason the user can read and no decision to make.
    [listed] = harness.service.list_records(RUN_AS, request_type=approvals.TYPE_WORKFLOW_RUN_AS)["items"]
    assert (listed["id"], listed["status"], listed["self_authored"]) == (prepared.binding_id, "approved", True)
    assert listed["can_approve"] is False and listed["can_deny"] is False
    assert "You saved this workflow revision yourself" in listed["reason"]


def test_the_same_revision_reuses_one_binding_and_one_audit_event(harness):
    first, _allowed = harness.run(workflow())
    second, _allowed = harness.run(workflow(modified_at="2026-03-08T04:10:00+00:00"))

    assert second.binding_id == first.binding_id
    assert len(harness.bindings()) == 1
    assert len(harness.audit("self_authored_approved")) == 1
    assert harness.notifications.calls == []


def test_the_run_as_users_own_edits_never_wait(harness):
    ids = []
    for prompt in ("Summarize my mail.", "Summarize my mail by sender.", "Summarize only unread mail."):
        prepared, allowed = harness.run(workflow(prompt=prompt))
        assert allowed["status"] == "approved"
        ids.append(prepared.binding_id)

    assert len(set(ids)) == 3
    assert {item["status"] for item in harness.bindings()} == {"approved"}
    assert all(item["self_authored"] is True for item in harness.bindings())
    assert len(harness.audit("self_authored_approved")) == 3
    assert harness.notifications.calls == []


def test_a_run_as_save_reviews_earlier_edits_by_others(harness):
    edited = workflow(modified_by=EDITOR, prompt="Forward my mail to the team.")
    _prepared, pending = harness.waits(edited)
    assert pending["status"] == "pending" and "self_authored" not in pending

    # The Run as user saves the same revision; their save counts as their review of it.
    resaved = workflow(prompt="Forward my mail to the team.", modified_at="2026-03-08T04:20:00+00:00")
    prepared, allowed = harness.run(resaved)
    assert allowed["status"] == "approved" and allowed["self_authored"] is True
    assert prepared.workflow_fingerprint == pending["binding"]["workflow_fingerprint"]


# ---------------------------------------------------------------------------------------------
# Someone else's revision
# ---------------------------------------------------------------------------------------------

def test_a_revision_someone_else_saved_needs_the_run_as_users_approval(harness):
    stored = workflow(modified_by=EDITOR)
    prepared, pending = harness.waits(stored)

    assert pending["status"] == "pending" and pending["can_approve"] is True
    assert [call["status"] for call in harness.notifications.calls] == ["pending"]
    assert harness.audit("self_authored_approved") == []
    harness.approve(pending["id"])
    allowed = harness.validate(prepared)
    assert allowed["status"] == "approved" and "self_authored" not in allowed
    next_run, _allowed = harness.run(stored)
    assert next_run.binding_id == pending["id"]


def test_a_missing_modified_by_needs_approval(harness):
    _prepared, pending = harness.waits(workflow(modified_by=None))

    assert pending["status"] == "pending"
    assert harness.bindings(self_authored=True) == []


def test_a_later_edit_by_someone_else_asks_again(harness):
    first, allowed = harness.run(workflow())
    assert allowed["self_authored"] is True

    _prepared, pending = harness.waits(workflow(modified_by=EDITOR, prompt="Send my mail to an outside address."))
    assert pending["binding"]["workflow_fingerprint"] != first.workflow_fingerprint
    harness.approve(pending["id"])
    _prepared, again = harness.waits(workflow(modified_by=EDITOR, prompt="Delete my mail after reading it."))
    assert again["id"] != pending["id"]


@pytest.mark.parametrize("kind,author,changed_at,asks", [
    ("agent", EDITOR, BEFORE_SAVE, False),
    ("agent", EDITOR, AFTER_SAVE, True),
    ("action", EDITOR, AFTER_SAVE, True),
    ("action", ADMIN, "2026-03-08T04:00:00.000001", True),
    ("agent", RUN_AS, AFTER_SAVE, False),
    ("agent", None, BEFORE_SAVE, False),
    ("agent", None, AFTER_SAVE, True),
    ("agent", EDITOR, "not a time", True),
], ids=[
    "agent edited by someone else before the save", "agent edited by someone else after the save",
    "action edited by someone else after the save", "action edited a microsecond after the save",
    "agent edited by the Run as user after the save", "unattributed agent edit before the save",
    "unattributed agent edit after the save", "unreadable agent edit time",
])
def test_an_agent_or_action_someone_else_changed_after_the_save_asks(harness, kind, author, changed_at, asks):
    other = "action" if kind == "agent" else "agent"
    stored = workflow(authorship=[authored(kind, author, changed_at), authored(other, RUN_AS, BEFORE_SAVE)])
    if asks:
        _prepared, pending = harness.waits(stored)
        assert pending["status"] == "pending"
    else:
        _prepared, allowed = harness.run(stored)
        assert allowed["self_authored"] is True


@pytest.mark.parametrize("authorship", [None, "absent", [{"kind": "agent"}, "not a component"]],
                         ids=["no authorship", "authorship never recorded", "malformed authorship"])
def test_unknown_component_authorship_needs_approval(harness, authorship):
    stored = workflow()
    if authorship == "absent":
        stored.pop(M365_REVISION_AUTHORSHIP_FIELD)
    else:
        stored[M365_REVISION_AUTHORSHIP_FIELD] = authorship
    _prepared, pending = harness.waits(stored)

    assert pending["status"] == "pending"


def test_a_new_connection_or_generation_asks_again_for_someone_elses_revision(harness):
    stored = workflow(modified_by=EDITOR)
    approved_run, pending = harness.waits(stored)
    harness.approve(pending["id"])
    harness.validate(approved_run)

    harness.connection["generation"] = 2
    with pytest.raises(approvals.M365PolicyError) as stale:
        harness.validate(approved_run)
    assert stale.value.code == "m365_run_as_invalid"
    _prepared, regenerated = harness.waits(stored)
    assert regenerated["id"] != pending["id"] and regenerated["binding"]["connection_generation"] == 2

    harness.connection.update(id="connection-b", generation=1)
    _prepared, reconnected = harness.waits(stored)
    assert reconnected["binding"]["connection_id"] == "connection-b"


def test_a_new_connection_generation_records_a_new_self_authored_binding(harness):
    first, _allowed = harness.run(workflow())
    harness.connection["generation"] = 2

    with pytest.raises(approvals.M365PolicyError):
        harness.validate(first)
    second, allowed = harness.run(workflow())
    assert second.binding_id != first.binding_id
    assert allowed["self_authored"] is True and allowed["binding"]["connection_generation"] == 2
    assert harness.notifications.calls == []


# ---------------------------------------------------------------------------------------------
# Audience changes
# ---------------------------------------------------------------------------------------------

def test_an_audience_change_never_asks_again(harness):
    stored = workflow(modified_by=EDITOR)
    _prepared, pending = harness.waits(stored, audience="audience-1")
    harness.approve(pending["id"])
    notified = len(harness.notifications.calls)

    moved, allowed = harness.run(stored, audience="audience-2")
    assert moved.binding_id == pending["id"] and allowed["status"] == "approved"
    assert len(harness.bindings()) == 1
    assert len(harness.notifications.calls) == notified
    # The binding still records the audience it was approved for.
    recorded = harness.service.get_approval(pending["id"], RUN_AS)
    assert recorded["binding"]["audience_version"] == "audience-1"

    own, _allowed = harness.run(workflow(prompt="My own revision."), audience="audience-1")
    shared, _allowed = harness.run(workflow(prompt="My own revision."), audience="audience-3")
    assert shared.binding_id == own.binding_id


# ---------------------------------------------------------------------------------------------
# Explicit decisions still win
# ---------------------------------------------------------------------------------------------

def test_a_denial_recorded_for_a_run_still_blocks_that_run(harness):
    _prepared, pending = harness.waits(workflow(modified_by=EDITOR), run_id="run-denied")
    harness.service.decide(pending["id"], RUN_AS, {"choice": "deny"})

    for stored in (workflow(modified_by=EDITOR), workflow()):
        with pytest.raises(approvals.M365PolicyError) as declined:
            harness.prepare(stored, run_id="run-denied")
        assert declined.value.code == "m365_workflow_declined"
    _prepared, allowed = harness.run(workflow(), run_id="run-next")
    assert allowed["self_authored"] is True


def test_a_cancellation_recorded_for_a_run_still_blocks_that_run(harness):
    _prepared, pending = harness.waits(workflow(modified_by=EDITOR), run_id="run-cancelled")
    harness.service.record_execution_status(pending["id"], RUN_AS, "run-cancelled", "cancelled")

    with pytest.raises(approvals.M365PolicyError) as declined:
        harness.prepare(workflow(), run_id="run-cancelled")
    assert declined.value.code == "m365_workflow_declined"


def test_a_revoked_self_authored_binding_is_not_silently_recreated(harness):
    stored = workflow()
    revoked_run, _allowed = harness.run(stored)
    harness.service.revoke_workflow_binding(revoked_run.binding_id, RUN_AS)

    with pytest.raises(approvals.M365PolicyError) as invalid:
        harness.validate(revoked_run)
    assert invalid.value.code == "m365_run_as_invalid"
    prepared, pending = harness.waits(stored)
    assert pending["status"] == "pending" and "self_authored" not in pending
    assert [item["status"] for item in harness.bindings(self_authored=True)] == ["revoked"]
    assert len(harness.audit("self_authored_approved")) == 1
    # Approving it explicitly lets the revision run again, and a new save of their own needs nothing.
    harness.approve(pending["id"])
    approved = harness.validate(prepared)
    assert approved["status"] == "approved"
    _prepared, allowed = harness.run(workflow(prompt="A new revision of my own."))
    assert allowed["self_authored"] is True


def test_revoking_a_revision_revokes_every_approved_copy_of_it(harness):
    stored = workflow(modified_by=EDITOR)
    fingerprint = workflow_execution_fingerprint(stored, [manifest()])
    copies = []
    for audience in ("audience-1", "audience-2"):
        context = harness.context(f"legacy-{audience}", audience)
        context = replace(context, workflow_fingerprint=fingerprint, connection_id="connection-a")
        binding = harness.service.create_workflow_binding(
            context, ["email"], copy.deepcopy(harness.connection), review=WORKFLOW_REVIEW,
        )
        harness.approve(binding["id"])
        copies.append(binding["id"])
    assert len(set(copies)) == 2

    harness.service.revoke_workflow_binding(copies[0], RUN_AS)
    statuses = {harness.service.get_approval(item, RUN_AS)["status"] for item in copies}
    assert statuses == {"revoked"}
    _prepared, pending = harness.waits(workflow(), audience="audience-2")
    assert pending["id"] not in copies


# ---------------------------------------------------------------------------------------------
# The runtime records agent and action authorship beside the fingerprint
# ---------------------------------------------------------------------------------------------

def _module(name, **values):
    module = types.ModuleType(name)
    module.__dict__.update(values)
    return module


def _load_runtime():
    spec = importlib.util.spec_from_file_location("test_self_authored_m365_runtime", APP_DIR / "functions_m365_runtime.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "config": _module(
            "config", TENANT_ID=TENANT, cosmos_conversations_container=None,
            cosmos_m365_execution_runs_container=None,
        ),
        "functions_appinsights": _module("functions_appinsights", log_event=lambda *args, **kwargs: None),
        "functions_collaboration": _module(
            "functions_collaboration",
            assert_user_can_participate_in_collaboration_conversation=lambda *args: None,
            build_conversation_participation_context=lambda *args: None,
            get_collaboration_conversation=lambda *args: None,
        ),
    }):
        spec.loader.exec_module(module)
    return module


def test_runtime_manifests_record_authorship_outside_the_fingerprint(harness):
    runtime = _load_runtime()
    agent = {
        "id": "mailer", "name": "Mailer", "instructions": "Summarize mail.", "actions_to_load": ["mail"],
        "modified_by": RUN_AS, "modified_at": BEFORE_SAVE,
    }
    action = {**manifest(id="personal-mail"), "modified_by": RUN_AS, "modified_at": BEFORE_SAVE}
    catalogs = {
        "functions_global_actions": _module("functions_global_actions", get_global_actions=lambda **kwargs: []),
        "functions_global_agents": _module("functions_global_agents", get_global_agents=lambda: []),
        "functions_personal_actions": _module(
            "functions_personal_actions", get_personal_actions=lambda *args, **kwargs: [copy.deepcopy(action)],
        ),
        "functions_personal_agents": _module(
            "functions_personal_agents", get_personal_agents=lambda user_id: [copy.deepcopy(agent)],
        ),
        "functions_group_actions": _module("functions_group_actions", get_group_actions=lambda *args, **kwargs: []),
        "functions_group_agents": _module("functions_group_agents", get_group_agents=lambda *args: []),
        "functions_group": _module("functions_group", assert_group_role=lambda *args: None),
        "functions_keyvault": _module("functions_keyvault", SecretReturnType=types.SimpleNamespace(NAME="name")),
        "functions_settings": _module("functions_settings", get_settings=lambda: {}),
    }
    stored = {
        "id": WORKFLOW_ID, "user_id": RUN_AS, "task_prompt": "Summarize my mail.",
        "selected_agent": {"id": "mailer", "name": "Mailer", "is_global": False},
        "m365_run_as_user_id": RUN_AS, "modified_by": RUN_AS, "modified_at": SAVED_AT,
    }
    app = Flask(__name__)

    def bind():
        manifests, fingerprint_workflow = runtime.workflow_m365_manifests(copy.deepcopy(stored))
        context = harness.context(f"runtime-run-{harness.runs}", "audience-1")
        harness.runs += 1
        with app.test_request_context("/"):
            g.m365_workflow = fingerprint_workflow
            g.m365_workflow_manifests = manifests
            prepared = runtime.resolve_m365_workflow_binding(context, manifests, {"email": "always"})
        return manifests, fingerprint_workflow, prepared

    with patch.dict(sys.modules, catalogs):
        manifests, fingerprint_workflow, prepared = bind()
        assert fingerprint_workflow[M365_REVISION_AUTHORSHIP_FIELD] == [
            {"kind": "agent", "id": "mailer", "modified_by": RUN_AS, "modified_at": BEFORE_SAVE},
            {"kind": "action", "id": "personal-mail", "modified_by": RUN_AS, "modified_at": BEFORE_SAVE},
        ]
        allowed = harness.validate(prepared)
        assert allowed["self_authored"] is True

        # Authorship is not part of the fingerprint: saving the agent unchanged keeps the binding.
        agent.update(modified_by=ADMIN, modified_at=AFTER_SAVE)
        _manifests, unchanged, again = bind()
        assert workflow_execution_fingerprint(unchanged, _manifests) == prepared.workflow_fingerprint
        assert again.binding_id == prepared.binding_id

        # An administrator's later change to what the agent does asks the Run as user.
        agent["instructions"] = "Forward every message to an outside address."
        _manifests, _changed, changed = bind()
        with pytest.raises(approvals.M365ApprovalRequired):
            harness.validate(changed)


def test_the_authorship_check_is_pure_and_fails_closed():
    stored = workflow()
    assert workflow_revision_self_authored(stored, RUN_AS, stored[M365_REVISION_AUTHORSHIP_FIELD]) is True
    assert workflow_revision_self_authored(stored, EDITOR, stored[M365_REVISION_AUTHORSHIP_FIELD]) is False
    assert workflow_revision_self_authored({**stored, "m365_run_as_user_id": EDITOR}, RUN_AS, []) is False
    assert workflow_revision_self_authored({**stored, "modified_at": None}, RUN_AS, [
        authored("agent", EDITOR, BEFORE_SAVE),
    ]) is False
    assert workflow_revision_self_authored(stored, "", []) is False
    assert workflow_revision_self_authored(stored, RUN_AS, None) is False


# ---------------------------------------------------------------------------------------------
# Every save records the authenticated actor
# ---------------------------------------------------------------------------------------------

@pytest.fixture
def save_routes():
    from test_workflow_origin_provenance import OriginRoutes

    return OriginRoutes()


@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize("scope", ["personal", "group"])
def test_save_routes_record_the_signed_in_actor_not_the_payload(save_routes, scope, version):
    from test_workflow_draft_save_parity import OWNER_ID
    from test_workflow_origin_provenance import _definition

    forged = {**_definition(version), "modified_by": "someone-else", "modified_at": "2020-01-01T00:00:00+00:00"}
    created = save_routes.post(scope, forged)
    assert created.status_code == 201, created.get_data(as_text=True)
    workflow_id = created.json["workflow"]["id"]
    assert save_routes.stored(scope, workflow_id)["modified_by"] == OWNER_ID

    update = {**save_routes.load(scope, workflow_id), "description": "Edited", "modified_by": "someone-else"}
    updated = save_routes.post(scope, update)
    assert updated.status_code == 200, updated.get_data(as_text=True)
    stored = save_routes.stored(scope, workflow_id)
    assert stored["modified_by"] == OWNER_ID and stored["modified_at"] != "2020-01-01T00:00:00+00:00"


def test_group_saves_and_server_creates_record_their_own_actor():
    from test_workflow_draft_save_parity import EDITOR_ID, GROUP_ID, OWNER_ID, SaveParityHarness, _task, _v2

    stores = SaveParityHarness()
    payload = _v2("Inbox digest", tasks=[_task("read", "Read", "Read my email.")])
    created = stores.save_group("create", payload, actor_user_id=OWNER_ID)
    edited = stores.save_group("edit", {
        **stores.load_group(created["id"]), "description": "Edited by an admin", "modified_by": OWNER_ID,
    }, actor_user_id=EDITOR_ID)
    assert stores.containers["group_workflows"].items[(GROUP_ID, edited["id"])]["modified_by"] == EDITOR_ID
    with stores.active():
        server, made = stores.personal.create_personal_workflow_if_absent(
            OWNER_ID, {**payload, "modified_by": "someone-else"},
            workflow_id="0e552320-f2b4-5149-8742-51fe78301563",
            origin={
                "source": "orchestration", "conversation_id": "conv-chat", "orchestration_run_id": "run-1",
                "proposal_id": "proposal-1", "created_at": "2026-09-28T12:00:00+00:00",
            },
            actor_user_id=OWNER_ID,
        )
    assert made is True and server["modified_by"] == OWNER_ID


# ---------------------------------------------------------------------------------------------
# Raw administrator edits
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("container", sorted(M365_AUTHORED_RECORD_CONTAINERS))
def test_a_raw_edit_names_the_administrator(container):
    document = {"id": "record-1", "instructions": "Forward my mail.", "modified_by": RUN_AS, "modified_at": BEFORE_SAVE}
    stamped = attribute_raw_authored_record_edit(container, document, ADMIN, EDITED_AT)

    # Each store keeps its own time format: aware for workflows, naive UTC for agents and actions.
    expected = "2026-03-09T00:00:00+00:00" if container.endswith("_workflows") else "2026-03-09T00:00:00"
    assert (stamped["modified_by"], stamped["modified_at"]) == (ADMIN, expected)
    assert document["modified_by"] == RUN_AS
    anonymous = attribute_raw_authored_record_edit(container, document, None, EDITED_AT)
    assert anonymous["modified_by"] == RAW_EDITOR_AUTHOR


def test_a_raw_workflow_edit_is_never_self_authored():
    edited = attribute_raw_authored_record_edit(
        "personal_workflows", workflow(prompt="Forward my mail."), ADMIN, EDITED_AT,
    )
    assert workflow_revision_self_authored(edited, RUN_AS, edited[M365_REVISION_AUTHORSHIP_FIELD]) is False
    # An agent a raw edit changed after the Run as user's save asks them too.
    agent = attribute_raw_authored_record_edit("group_agents", {"id": "agent-1"}, ADMIN, EDITED_AT)
    stored = workflow(authorship=[{"kind": "agent", "id": "agent-1", **{
        key: agent[key] for key in ("modified_by", "modified_at")
    }}])
    assert workflow_revision_self_authored(stored, RUN_AS, stored[M365_REVISION_AUTHORSHIP_FIELD]) is False
    # Records nothing runs keep exactly what the administrator typed.
    conversation = {"id": "conversation-1", "modified_by": RUN_AS}
    assert attribute_raw_authored_record_edit("conversations", conversation, ADMIN, EDITED_AT) is conversation


def test_the_cosmos_editor_attributes_changed_records_before_saving():
    source = (APP_DIR / "functions_data_management.py").read_text(encoding="utf-8")
    start = source.index("def save_data_management_cosmos_editor_document")
    body = source[start:source.index("\ndef ", start + 1)]
    summary = body.index("change_summary = _summarize_cosmos_editor_changes(original_document, document)")
    attribute = body.index("clean_document = attribute_raw_authored_record_edit(")
    replace_call = body.index("saved_document = container.replace_item(")
    assert summary < attribute < replace_call
    assert 'if change_summary["changed_count"]:' in body[summary:attribute]
    assert 'container_metadata["logical_name"], clean_document, admin_user_id,' in body


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", *os.environ.get("PYTEST_ADDOPTS", "").split()]))
