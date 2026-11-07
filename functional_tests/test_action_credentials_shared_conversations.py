# test_action_credentials_shared_conversations.py
"""Credential routing and private ownership across visible/source conversation IDs.

Version: 0.261.348
Implemented in: 0.261.348

Uses real credential storage, SDK point responses and Flask interaction routes.
Membership callbacks are explicit policy seams; real policies and real agents are
also exercised by test_action_credentials_chat_reconstruction.py.
"""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

from azure.cosmos.exceptions import CosmosHttpResponseError
import pytest

from test_action_personal_credentials import (
    CredentialContainer, challenge, entry, environment,
)


@pytest.fixture
def shared_environment(environment, monkeypatch):
    from functions_action_credential_conversations import CredentialConversations

    env = environment
    personal, shared, messages = CredentialContainer("id"), CredentialContainer("id"), CredentialContainer("conversation_id")
    members = {"alice", "bob"}
    personal.upsert_item({"id": "chat", "user_id": "alice"})
    shared.upsert_item({
        "id": "visible", "conversation_kind": "collaborative", "created_by_user_id": "alice",
        "source_conversation_id": "source", "status": "active",
    })
    personal.upsert_item({
        "id": "source", "user_id": "alice", "conversation_kind": "collaboration_source",
        "collaboration_conversation_id": "visible",
    })

    def authorize_shared(actor, conversation):
        if actor not in members or conversation.get("status") != "active":
            raise PermissionError("Participation revoked.")

    def authorize_orchestration(conversation, actor):
        authorize_shared(actor, conversation)
        if actor != conversation["created_by_user_id"]:
            raise PermissionError("Creator only.")

    resolver = CredentialConversations(
        personal_container=personal, shared_container=shared, message_container=messages,
        authorize_personal=env.credentials.authorize_conversation,
        authorize_shared=authorize_shared, authorize_orchestration=authorize_orchestration,
    )
    monkeypatch.setattr(env.credentials, "authorize_conversation", resolver.resolve)
    monkeypatch.setattr(env.routes, "authorize_conversation", resolver.resolve)
    monkeypatch.setattr(env.credentials, "_services", replace(
        env.credentials.credential_services(), authorize_request_context=resolver.authorize_request,
    ))

    def resolve_manifest(actor, reference):
        if actor not in members or reference != env.credentials.manifest_reference(env.current):
            raise PermissionError()
        return deepcopy(env.current)

    monkeypatch.setattr(env.credentials, "authorized_manifest", resolve_manifest)

    def select_actor(actor):
        env.auth.user = actor
        with env.client.session_transaction() as browser:
            browser["user"] = {"oid": actor}
        message_id = "question-" + actor
        messages.upsert_item({
            "id": message_id, "conversation_id": "visible", "message_kind": "ai_request",
            "metadata": {"sender": {"user_id": actor}, "source_conversation_id": "source"},
        })
        monkeypatch.setattr(env.credentials, "actor_context", lambda: (actor, "source", None))
        env.descriptor.update(
            visible_conversation_id="visible", collaboration_message_id=message_id,
        )

    select_actor("alice")
    return SimpleNamespace(
        env=env, resolver=resolver, personal=personal, shared=shared, messages=messages,
        members=members, select_actor=select_actor,
    )


def test_empty_accessible_lists_are_read_only_for_personal_and_shared(shared_environment):
    fixture, env = shared_environment, shared_environment.env
    before = (fixture.personal.revision, fixture.shared.revision, fixture.messages.revision, env.store.revision)
    for conversation_id in ("chat", "visible", "source"):
        response = env.client.get("/api/action-credentials/pending", query_string={"conversation_id": conversation_id})
        assert response.status_code == 200
        assert response.json["requests"] == []
        assert response.headers["Cache-Control"] == "no-store"
    fixture.select_actor("bob")
    response = env.client.get("/api/action-credentials/pending?conversation_id=visible")
    assert response.status_code == 200 and response.json["requests"] == []
    assert (fixture.personal.revision, fixture.shared.revision, env.store.revision) == (before[0], before[1], before[3])
    missing = env.client.get("/api/action-credentials/pending?conversation_id=missing")
    assert missing.status_code == 404


def test_two_participants_have_independent_private_requests_and_identities(shared_environment):
    fixture, env = shared_environment, shared_environment.env
    alice = challenge(env)
    assert alice["conversation_id"] == "visible" and alice["conversation_kind"] == "collaborative"
    fixture.select_actor("bob")
    empty = env.client.get("/api/action-credentials/pending?conversation_id=visible")
    assert empty.status_code == 200 and empty.json["requests"] == []
    denied = env.client.get("/api/action-credentials/" + alice["id"])
    assert denied.status_code == 404
    bob = challenge(env)
    assert alice["id"] != bob["id"]
    recovered = env.client.get("/api/action-credentials/pending?conversation_id=visible")
    assert [item["id"] for item in recovered.json["requests"]] == [bob["id"]]
    token = recovered.json["csrf_token"]
    stolen = env.client.post("/api/action-credentials/" + alice["id"] + "/submit", json={
        "expected_etag": alice["etag"], "slots": [entry()],
    }, headers={"X-CSRFToken": token})
    assert stolen.status_code == 404 and not env.identities.items
    saved = env.client.post("/api/action-credentials/" + bob["id"] + "/submit", json={
        "expected_etag": bob["etag"], "slots": [entry(secret="BOB_PRIVATE_SECRET")],
    }, headers={"X-CSRFToken": token})
    assert saved.status_code == 200 and saved.json["credential_request"]["status"] == "ready"
    fixture.select_actor("alice")
    recovered = env.client.get("/api/action-credentials/pending?conversation_id=visible")
    assert [item["id"] for item in recovered.json["requests"]] == [alice["id"]]
    assert recovered.json["requests"][0]["identities"] == []
    assert env.state.read("alice", alice["id"])["conversation_id"] == "source"
    assert env.state.read("bob", bob["id"])["continuation"]["collaboration_message_id"] == "question-bob"


@pytest.mark.parametrize("change", ["membership", "status", "source", "question", "sender", "origin", "expiry"])
def test_changed_access_or_unproven_origin_cannot_read_submit_or_continue(shared_environment, change):
    fixture, env = shared_environment, shared_environment.env
    dto = challenge(env)
    path = "/api/action-credentials/" + dto["id"]
    info = env.client.get(path)
    token = info.json["csrf_token"]
    if change == "membership":
        fixture.members.remove("alice")
    elif change == "status":
        fixture.shared.items[("visible", "visible")]["status"] = "deleted"
    elif change == "source":
        fixture.personal.items[("source", "source")]["user_id"] = "other"
    elif change == "question":
        fixture.messages.items[("visible", "question-alice")]["metadata"]["is_deleted"] = True
    elif change == "sender":
        fixture.messages.items[("visible", "question-alice")]["metadata"]["sender"]["user_id"] = "bob"
    elif change == "origin":
        env.store.items[("alice", dto["id"])]["continuation"].pop("visible_conversation_id")
    else:
        env.store.items[("alice", dto["id"])]["expires_at"] = 0
    denied = env.client.get(path)
    assert denied.status_code in {404, 409, 410}
    for operation, body in (
        ("submit", {"expected_etag": dto["etag"], "slots": [entry()]}),
        ("continue", {"expected_etag": dto["etag"]}),
    ):
        response = env.client.post(path + "/" + operation, json=body, headers={"X-CSRFToken": token})
        assert response.status_code in {404, 409, 410}
    assert not env.identities.items


def test_shared_orchestration_backing_keeps_creator_only_policy(shared_environment):
    fixture = shared_environment
    fixture.personal.upsert_item({
        "id": "visible", "user_id": "alice", "conversation_kind": "collaboration_source",
        "collaboration_conversation_id": "visible",
    })
    item = {
        "conversation_id": "visible", "continuation": {"mode": "orchestration"},
    }
    context = fixture.resolver.authorize_request("alice", item)
    assert context["credential_execution_ids"] == ("source", "visible")
    with pytest.raises(LookupError):
        fixture.resolver.authorize_request("bob", item)
    fixture.members.remove("alice")
    with pytest.raises(PermissionError):
        fixture.resolver.authorize_request("alice", item)


def test_storage_failure_remains_explicit_and_safe(shared_environment, monkeypatch):
    fixture, env = shared_environment, shared_environment.env

    def unavailable(*args, **kwargs):
        raise CosmosHttpResponseError(status_code=503, message="PRIVATE_STORAGE_DETAIL")

    monkeypatch.setattr(fixture.shared, "read_item", unavailable)
    response = env.client.get("/api/action-credentials/pending?conversation_id=visible")
    assert response.status_code == 503
    assert response.json["code"] == "credentials_unavailable"
    assert "PRIVATE_STORAGE_DETAIL" not in response.get_data(as_text=True)
    assert response.headers["Cache-Control"] == "no-store"


def test_live_shared_stream_keeps_both_credential_event_formats_private():
    from test_orchestration_result_imports import run_probe

    run_probe(r'''
import json
import sys
from copy import deepcopy
from dataclasses import replace
from flask import Response, request
import pytest
sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

def check(value, message):
    if not value:
        raise AssertionError(message)

with offline_app_imports(), pytest.MonkeyPatch.context() as patch:
    import app
    import functions_action_credentials as credentials
    import functions_action_credential_state as state
    import route_backend_collaboration as routes
    from action_credential_contracts import ActionCredentialsRequired, credential_fingerprint
    from functions_action_credential_conversations import CredentialConversations
    from test_action_personal_credentials import CredentialContainer, manifest
    from test_collaboration_group_agent_stream_fix import build_group_agent_stream_test_app

    web, registry, restore = build_group_agent_stream_test_app()
    try:
        actor = {"user_id": "alice", "display_name": "Actor", "email": ""}
        patch.setattr(routes, "_get_current_collaboration_user", lambda: deepcopy(actor))
        visible, source = "shared-agent-conversation-001", "source-group-agent-conversation-001"
        personal, shared, messages = CredentialContainer("id"), CredentialContainer("id"), CredentialContainer("conversation_id")
        shared.upsert_item({"id": visible, "status": "active", "conversation_kind": "collaborative",
                            "created_by_user_id": "alice", "source_conversation_id": source})
        personal.upsert_item({"id": source, "user_id": "alice", "conversation_kind": "collaboration_source",
                              "collaboration_conversation_id": visible})
        resolver = CredentialConversations(
            personal_container=personal, shared_container=shared, message_container=messages,
            authorize_personal=lambda *args: None, authorize_shared=lambda *args: None,
            authorize_orchestration=lambda *args: None,
        )
        patch.setattr(credentials, "_services", replace(
            credentials.credential_services(), authorize_conversation=resolver.resolve,
            authorize_request_context=resolver.authorize_request,
        ))
        action = manifest()
        patch.setattr(credentials, "authorized_manifest", lambda *args: action)
        state.configure_action_credential_state(CredentialContainer("user_id"))
        pending_ids = []
        for named in (False, True):
            def internal_stream():
                payload = request.get_json()
                question = payload["m365_collaboration_message_id"]
                messages.upsert_item({"id": question, "conversation_id": visible, "message_kind": "ai_request",
                                      "metadata": {"sender": actor, "source_conversation_id": source}})
                item = state.request_for(
                    "alice", source, credentials.manifest_reference(action), credential_fingerprint(action),
                    {"service": "api_key"}, reason="setup_required",
                    continuation={"mode": "chat", "checkpoint_id": "live-checkpoint-" + str(named),
                                  "agent_reference": {"id": "agent"}, "visible_conversation_id": visible,
                                  "collaboration_message_id": question},
                )
                pending_ids.append(item["id"])
                event = ActionCredentialsRequired(credentials.safe_request(item, action)).event
                prefix = "event: action_credentials_required\n" if named else ""
                return Response(prefix + "data: " + json.dumps(event) + "\n\n", mimetype="text/event-stream")

            web.view_functions["chat_stream_api"] = internal_stream
            response = web.test_client().post(
                "/api/collaboration/conversations/" + visible + "/stream",
                json={"content": "Read mission telemetry."},
            )
            payloads = [json.loads(line[5:]) for line in response.get_data(as_text=True).splitlines()
                        if line.startswith("data:")]
            event = next(value for value in payloads if value.get("type") == "action_credentials_required")
            check(event["credential_request"]["conversation_id"] == visible, "Live prompt used a hidden source ID.")
            check(event["credential_request"]["conversation_kind"] == "collaborative", "Live prompt lost its kind.")
            cached = json.dumps(registry.events)
            check("credential_request" not in cached and pending_ids[-1] not in cached,
                  "A private prompt entered another participant's event cache.")
    finally:
        restore()
print("PASS: live credential events remain private under the visible shared ID")
''', (), False)
