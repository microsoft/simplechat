# test_m365_pending_authorization.py
"""
Confirmation authorization with the real M365 runtime owner and transport.
Version: 0.261.038
Implemented in: 0.261.038

Saved catalogs, membership and cloud I/O are isolated. The real runtime restores
the selected agent, resolves current capabilities, binds the signed-in subject,
checks the destination, and restores request state before any Graph write.
"""

from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

from flask import g, session
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent))

# Repository test helpers initialize application paths before these imports.
from test_m365_action_card_api import APP, cards, load_module, module_stub
from test_m365_provider_core import FakeResponse
from test_support.m365 import CosmosContainer
import functions_m365_approvals as approvals
import functions_m365_execution as execution
import functions_m365_pending_delivery as delivery
import functions_m365_transport as transport


@pytest.fixture
def authorized_delivery(cards, monkeypatch):
    conversations = CosmosContainer("id")
    conversations.create_item(body={"id": "conversation", "user_id": "owner"})
    jobs = CosmosContainer("user_id")
    jobs.create_item(body={
        "id": "request", "user_id": "owner", "actor_user_id": "owner",
        "conversation_id": "conversation", "status": "completed",
    })
    state = SimpleNamespace(
        members={"owner"},
        actions=[{
            "id": "source-action", "name": "calendar", "type": "m365_calendar",
            "additionalFields": {"m365_capabilities": {"create_calendar_invite": True}},
        }],
        agents=[{"id": "agent", "name": "agent", "actions_to_load": ["source-action"]}],
        endpoint="https://graph.microsoft.com", writes=[], jobs=jobs,
    )
    created = cards.create()

    def participation(user_id, conversation):
        if user_id not in state.members or conversation["id"] != "conversation":
            raise PermissionError("Current membership is required.")
        return {}

    seams = {
        "config": module_stub(
            "config", TENANT_ID="tenant", cosmos_conversations_container=conversations,
            cosmos_m365_execution_runs_container=jobs,
            cosmos_msgraph_pending_actions_container=cards.container,
        ),
        "functions_appinsights": module_stub("functions_appinsights", log_event=cards.log),
        "functions_collaboration": module_stub(
            "functions_collaboration", build_conversation_participation_context=participation,
            get_collaboration_conversation=lambda conversation_id: None,
            assert_user_can_participate_in_collaboration_conversation=lambda *args: None,
        ),
        "functions_notifications": module_stub("functions_notifications", create_notification=lambda **kwargs: {"id": "notice"}),
        "functions_personal_actions": module_stub("functions_personal_actions", get_personal_actions=lambda *args, **kwargs: deepcopy(state.actions)),
        "functions_personal_agents": module_stub("functions_personal_agents", get_personal_agents=lambda user_id: deepcopy(state.agents)),
        "functions_global_actions": module_stub("functions_global_actions", get_global_actions=lambda **kwargs: []),
        "functions_global_agents": module_stub("functions_global_agents", get_global_agents=lambda: []),
        "functions_group_actions": module_stub(
            "functions_group_actions", get_group_actions=lambda *args, **kwargs: [],
            get_governed_group_actions=lambda *args, **kwargs: [],
        ),
        "functions_group_agents": module_stub("functions_group_agents", get_group_agents=lambda *args: []),
        "functions_group": module_stub("functions_group", get_user_groups=lambda user_id: [], assert_group_role=lambda *args: None),
        "functions_governance": module_stub(
            "functions_governance",
            filter_actions_by_action_type_access=lambda user_id, actions, *args: actions,
            filter_governed_global_actions_for_user=lambda user_id, actions: actions,
        ),
        "functions_keyvault": module_stub("functions_keyvault", SecretReturnType=SimpleNamespace(NAME="name")),
        "functions_settings": module_stub("functions_settings", get_settings=lambda: {}),
    }

    def cloud():
        return transport.M365CloudConfig(
            state.endpoint + "/v1.0", "https://login.example.test/tenant",
        )

    def graph_request(method, url, **kwargs):
        state.writes.append((method, url, deepcopy(kwargs["json"])))
        return FakeResponse({"id": "created-event", "webLink": "https://outlook.example.test/event"}, status=201)

    monkeypatch.setattr(transport, "get_m365_cloud_config", cloud)
    monkeypatch.setattr(approvals, "_service", approvals.M365ApprovalService(
        container_factory=lambda: CosmosContainer(),
    ))
    with patch.dict(sys.modules, seams):
        runtime = load_module("test_pending_runtime", APP / "functions_m365_runtime.py")
        runtime.configure_m365_pending_delivery_runtime(cards.app.test_request_context)
        monkeypatch.setattr(execution, "_action_config_resolver", runtime.resolve_m365_action_config)
        monkeypatch.setattr(execution, "_action_selection_resolver", runtime.resolve_m365_action_selection)
        monkeypatch.setitem(
            delivery._dependencies, "transport_factory",
            lambda source, action_id, **kwargs: transport.M365Transport(
                source, action_id, cloud=cloud(), request=graph_request,
                token_provider=kwargs.get("token_provider", lambda scopes, context: {"access_token": "offline"}),
            ),
        )
        action = cards.container.read_item(created["id"], "owner")
        action["m365_execution"]["context"]["audience_version"] = runtime._audience_version(
            conversations.read_item("conversation", "conversation"), None,
        )
        action["material_fingerprint"] = delivery.pending_delivery_fingerprint(action)
        saved = cards.container.upsert_item(body=action)
        state.action = saved
        state.runtime = runtime
        state.conversations = conversations
        yield state


@pytest.mark.parametrize("endpoint", [
    "https://graph.microsoft.com", "https://graph.microsoft.us", "https://graph.microsoft.scloud",
])
def test_reviewed_send_uses_current_cloud_and_restores_request_context(cards, authorized_delivery, endpoint):
    state = authorized_delivery
    state.endpoint = endpoint
    state.action["graph_endpoint"] = endpoint
    state.action["material_fingerprint"] = delivery.pending_delivery_fingerprint(state.action)
    saved = cards.container.upsert_item(body=state.action)
    with cards.app.test_request_context():
        session["user"] = {"oid": "owner", "tid": "tenant"}
        g.m365_selected_agent_ref = {"id": "unrelated-active-request"}
        completed, error = delivery.dispatch_m365_pending_delivery(
            "owner", saved["id"], expected_version=saved["_etag"],
        )
        restored = deepcopy(g.m365_selected_agent_ref)
        current_context = execution.get_m365_execution_context()
    assert completed["status"] == "sent" and error is None
    assert state.writes[0][1] == endpoint + "/v1.0/me/events"
    assert restored == {"id": "unrelated-active-request"} and current_context is None


@pytest.mark.parametrize("change,expected_code", [
    ("member", "delivery_not_authorized"),
    ("action", "m365_action_not_authorized"),
    ("capability", "m365_action_not_selected"),
    ("agent", "m365_agent_unavailable"),
    ("audience", "m365_context_changed"),
    ("cloud", "m365_context_changed"),
    ("tenant", "m365_principal_mismatch"),
    ("actor", "m365_principal_mismatch"),
])
def test_current_access_and_material_bindings_precede_remote_delivery(cards, authorized_delivery, change, expected_code):
    state = authorized_delivery
    if change == "member":
        state.members.clear()
    elif change == "action":
        state.actions.clear()
    elif change == "capability":
        state.actions[0]["additionalFields"]["m365_capabilities"]["create_calendar_invite"] = False
        state.actions[0]["enabled_functions"] = []
    elif change == "agent":
        state.agents.clear()
    elif change == "audience":
        state.conversations.upsert_item(body={"id": "conversation", "user_id": "different-owner"})
    elif change == "cloud":
        state.endpoint = "https://graph.microsoft.us"
    with cards.app.test_request_context():
        session["user"] = {
            "oid": "other" if change == "actor" else "owner",
            "tid": "other" if change == "tenant" else "tenant",
        }
        saved, error = delivery.dispatch_m365_pending_delivery("owner", state.action["id"])
    assert error["error"] == expected_code
    assert saved["status"] == "review_required"
    assert state.writes == []


def test_timer_rechecks_execution_cancellation_without_borrowing_session(cards, authorized_delivery):
    state = authorized_delivery
    state.jobs.upsert_item(body={
        "id": "request", "user_id": "owner", "actor_user_id": "owner",
        "conversation_id": "conversation", "status": "cancelled",
    })
    state.action.update(
        action_mode="delayed", status="scheduled", auto_send_at_utc=cards.service._utc_now_iso(), delay_seconds=5,
    )
    state.action["material_fingerprint"] = delivery.pending_delivery_fingerprint(state.action)
    cards.container.upsert_item(body=state.action)
    saved, error = cards.service._commit_msgraph_pending_action_with_token(
        "owner", state.action["id"], "ephemeral-offline-token",
    )
    assert error["error"] == "m365_execution_stopped"
    assert saved["status"] == "review_required" and state.writes == []


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
