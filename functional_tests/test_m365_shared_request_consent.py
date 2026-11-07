# test_m365_shared_request_consent.py
#!/usr/bin/env python3
"""
Functional test for Microsoft 365 consent by request in shared conversations.
Version: 0.261.270
Implemented in: 0.261.270

In a shared conversation, an interactive request by the owner of the Microsoft 365 data is
their consent to share the sources it reads with that conversation (microsoft/simplechat#1659).
These tests run the real approval service against a conditional Cosmos double and check that:

* a request flagged ``shared_by_request`` is granted without a pending approval or a
  notification, and records one audit event per request and source;
* the grant has the shape publication of captured evidence needs;
* contexts without the flag (workflow Run as and history publication) still need an approval;
* only an interactive shared request can carry the flag, and it never changes the approval
  fingerprint.
"""

import ast
import sys
from dataclasses import replace
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
APP = TESTS.parent / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(TESTS))

import functions_m365_approvals as approvals  # noqa: E402 - the source path is set above
import functions_m365_execution as execution  # noqa: E402
from test_support.m365 import Clock, CosmosContainer, Notifications  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


def context(**changes):
    values = {
        "actor_user_id": "user-a", "data_user_id": "user-a", "tenant_id": "tenant-a",
        "conversation_id": "shared-conversation", "request_id": "request-a",
        "shared": True, "audience_version": "audience-1", "agent_id": "agent-a",
        "action_configs": {"action-a": {"source": "email", "maximum_sharing_acknowledgement": "always"}},
        "shared_by_request": True,
    }
    values.update(changes)
    return execution.M365ExecutionContext(**values)


@pytest.fixture
def service():
    container = CosmosContainer()
    notifications = Notifications()
    result = approvals.M365ApprovalService(
        container_factory=lambda: container, notification_sender=notifications,
        clock=Clock(), decision_validator=lambda approval: True,
    )
    result.test_container = container
    result.test_notifications = notifications
    return result


def records(service, **match):
    return [
        record for record in service.test_container.items.values()
        if all(record.get(key) == value for key, value in match.items())
    ]


def test_version_includes_consent_by_request():
    assert_app_version_at_least("0.261.270")


def test_a_shared_request_is_its_own_consent_without_an_approval(service):
    grants = service.authorize_sources(context(), {"email": "always"})

    grant = grants["email"]
    assert grant["shared_by_request"] is True and grant["sharing_required"] is False
    assert grant["approval_id"] == grant["audit_id"] == grant["decision_event_id"]
    assert grant["audit_id"].startswith("m365-request-")
    assert grant["effective_duration"] == "request" and grant["expires_at"] is None
    assert grant["acknowledged_at"]
    events = records(service, event_type="shared_by_request")
    assert len(events) == 1 and events[0]["id"] == grant["audit_id"]
    assert events[0]["source"] == "email" and events[0]["subject_user_id"] == "user-a"
    assert events[0]["context"]["request_id"] == "request-a" and events[0]["context"]["shared"] is True
    # Nothing waits for a decision and nobody is notified.
    assert records(service, status="pending") == [] and service.test_notifications.calls == []


def test_a_repeated_request_reuses_its_consent_record(service):
    first = service.authorize_sources(context(), {"email": "always"})["email"]
    second = service.authorize_sources(context(), {"email": "always"})["email"]

    assert second == first
    assert len(records(service, event_type="shared_by_request")) == 1


def test_each_request_and_source_records_its_own_consent(service):
    both = service.authorize_sources(context(), {"email": "always", "calendar": "today"})
    later = service.authorize_sources(context(request_id="request-b"), {"email": "always"})

    assert set(both) == {"email", "calendar"}
    assert len({both["email"]["audit_id"], both["calendar"]["audit_id"], later["email"]["audit_id"]}) == 3
    assert len(records(service, event_type="shared_by_request")) == 3


def test_a_shared_context_without_the_request_flag_still_needs_an_approval(service):
    with pytest.raises(approvals.M365ApprovalRequired) as pending:
        service.authorize_sources(context(shared_by_request=False), {"email": "always"})

    assert records(service, event_type="shared_by_request") == []
    assert service.get_approval(pending.value.approval_id, "user-a")["status"] == "pending"
    assert len(service.test_notifications.calls) == 1


def test_private_conversations_are_unchanged(service):
    grants = service.authorize_sources(
        context(shared=False, shared_by_request=False), {"email": "always"},
    )
    assert grants == {"email": {"source": "email", "sharing_required": False}}
    assert service.test_container.items == {}


@pytest.mark.parametrize(("changes", "message"), [
    ({"shared": False}, "Only an interactive shared request"),
    ({"workflow_id": "workflow-a", "run_id": "run-a", "step_id": "step-a"}, "Only an interactive shared request"),
    ({"shared_by_request": 1}, "Invalid authoritative"),
])
def test_only_an_interactive_shared_request_can_share_by_request(changes, message):
    with pytest.raises(ValueError, match=message):
        context(**changes)


def test_the_request_flag_never_changes_the_approval_fingerprint():
    flagged = context()
    plain = replace(flagged, shared_by_request=False)

    assert approvals.approval_context(flagged) == approvals.approval_context(plain)
    assert approvals.request_scope_fingerprint(flagged) == approvals.request_scope_fingerprint(plain)
    assert approvals.logical_request_fingerprint(flagged) == approvals.logical_request_fingerprint(plain)


def test_a_reviewed_delivery_keeps_its_requests_consent(service, monkeypatch):
    """Sending a reviewed email from a shared conversation needs no approval its request didn't."""
    import functions_m365_pending_delivery as delivery

    monkeypatch.setitem(delivery._dependencies, "capture_agent_reference", lambda context, action_id: {"id": "agent-a"})
    with execution.m365_execution_context(context()):
        captured = delivery.capture_workflow_delivery("user-a", "action-a", None, None)
    restored = execution.M365ExecutionContext(**captured["context"])

    assert captured["kind"] == "chat" and restored.shared_by_request is True
    assert service.authorize_sources(restored, {"email": "always"})["email"]["shared_by_request"] is True
    # A delivery recorded before 0.261.270 has no flag and still asks, as it did then.
    legacy = {key: value for key, value in captured["context"].items() if key != "shared_by_request"}
    with pytest.raises(approvals.M365ApprovalRequired):
        service.authorize_sources(execution.M365ExecutionContext(**legacy), {"email": "always"})


def _context_keywords(path, function_name=None):
    """The keyword names of every M365ExecutionContext(...) call in a module or one function."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    scopes = [
        node for node in ast.walk(tree)
        if function_name is None or (isinstance(node, ast.FunctionDef) and node.name == function_name)
    ]
    calls = []
    for scope in scopes[:1] if function_name else [tree]:
        for node in ast.walk(scope):
            if (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "M365ExecutionContext"
            ):
                calls.append({keyword.arg for keyword in node.keywords})
    return calls


def test_chat_and_plan_step_contexts_share_by_request_and_history_publication_does_not():
    runtime = APP / "functions_m365_runtime.py"
    for function_name in ("initialize_m365_chat_context", "step_m365_context"):
        calls = _context_keywords(runtime, function_name)
        assert calls and all("shared_by_request" in keywords for keywords in calls), function_name
    # Publishing a conversation's earlier answers keeps its own approval.
    history = _context_keywords(APP / "functions_m365_history.py")
    assert history and all("shared_by_request" not in keywords for keywords in history)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
