# test_guided_user_input_routes.py
"""Functional tests for actor-private question routes and conditional continuation.

Version: 0.261.411
Implemented in: 0.261.411
Real route/state owners use SDK-default conditional documents; providers are local.
"""

import asyncio
from copy import deepcopy
from functools import wraps
import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from threading import Event, Thread

from flask import Blueprint, Flask, Response, session
import pytest

from test_action_personal_credentials import CredentialContainer
from test_guided_user_input import input_runtime, runtime, continuation_services  # noqa: F401


class InputContainer(CredentialContainer):
    """Keep installed CosmosDict point/write responses; query projections are plain."""

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        parameters = {item["name"]: item["value"] for item in parameters or []}
        return [
            {"id": row["id"]} for (partition, _key), row in self.items.items()
            if partition == partition_key and row.get("record_type") == "user_input_request"
            and row["conversation_id"] == parameters["@conversation"]
            and row["status"] in {"pending", "answered", "continuing"}
            and row["expires_at"] > parameters["@now"]
        ]


def module(name, **values):
    result = ModuleType(name)
    result.__dict__.update(values)
    return result


@pytest.fixture
def routes(input_runtime, monkeypatch):
    env = input_runtime
    with pytest.raises(env.stop) as stopped:
        asyncio.run(env.invoke())
    store = InputContainer("user_id")
    store.items = deepcopy(env.store.items)
    monkeypatch.setattr(env.state, "_container", store)

    def login(function):
        @wraps(function)
        def guarded(*args, **kwargs):
            if not session.get("user"):
                return {"error": "Sign in."}, 401
            return function(*args, **kwargs)
        return guarded

    def csrf():
        session["action_credentials_csrf_token"] = "fixture-token"
        return "fixture-token"

    with patch.dict(sys.modules):
        sys.modules["functions_authentication"] = module(
            "functions_authentication", get_current_user_id=lambda: session["user"]["oid"],
            login_required=login, user_required=login,
        )
        sys.modules["swagger_wrapper"] = module(
            "swagger_wrapper", swagger_route=lambda **kwargs: lambda function: function, get_auth_security=lambda: [],
        )
        sys.modules["route_backend_action_credentials"] = module(
            "route_backend_action_credentials", _csrf_token=csrf,
            _orchestration_continue=lambda *args: (_ for _ in ()).throw(AssertionError("Not an orchestration request.")),
        )
        sys.modules.pop("route_backend_user_input", None)
        owner = importlib.import_module("route_backend_user_input")
        real_continue = owner._chat_continue
        calls = []

        def continue_chat(item, user_id):
            calls.append(item["id"])
            env.owner.finish_request(user_id, item["id"], item["continuation_claim"], "completed", {"done": True})
            return Response('data: {"done":true}\n\n', mimetype="text/event-stream")

        monkeypatch.setattr(owner, "_chat_continue", continue_chat)
        app = Flask("user-input-test")
        app.secret_key = "local-test-only"
        bp = Blueprint("input-test", __name__)
        owner.register_route_backend_user_input(bp)
        app.register_blueprint(bp)
        client = app.test_client()
        yield SimpleNamespace(
            env=env, client=client, calls=calls, request=stopped.value.input_request, store=store,
            owner=owner, real_continue=real_continue,
        )


def sign_in(client, actor="actor"):
    with client.session_transaction() as current:
        current["user"] = {"oid": actor}
        current["action_credentials_csrf_token"] = "fixture-token"


def answer_body():
    return {
        "revision": 1, "submission_id": "answer-once", "context": {},
        "response": {"action": "accept", "content": {
            "audience": "Partners", "focus": ["Costs"], "format": "brief",
        }},
    }


def test_routes_authorize_claim_and_do_not_replay_identical_continue(routes):
    env = routes
    sign_in(env.client)
    pending = env.client.get("/api/v2/user-input/pending?conversation_id=conversation")
    assert pending.status_code == 200
    request = pending.json["requests"][0]
    assert "continuation" not in request and "budget" not in request
    assert "PRIVATE_CONFIG" not in pending.get_data(as_text=True)
    path = "/api/v2/user-input/" + request["id"]
    headers = {"X-CSRFToken": pending.json["csrf_token"]}
    rejected = env.client.post(path + "/answer", json=answer_body())
    assert rejected.status_code == 403
    invalid = env.client.post(path + "/answer", json={**answer_body(), "revision": 2}, headers=headers)
    assert invalid.status_code == 400
    saved = env.client.post(path + "/answer", json=answer_body(), headers=headers)
    assert saved.status_code == 200 and saved.json["input_request"]["status"] == "answered"
    repeated = env.client.post(path + "/answer", json=answer_body(), headers=headers)
    assert repeated.status_code == 200
    body = {"submission_id": "answer-once"}
    continued = env.client.post(path + "/continue", json=body, headers=headers)
    assert continued.status_code == 200
    retry = env.client.post(path + "/continue", json=body, headers=headers)
    assert retry.status_code == 200
    assert env.calls == [request["id"]]
    sign_in(env.client, "peer")
    foreign = env.client.post(path + "/answer", json=answer_body(), headers=headers)
    assert foreign.status_code == 404


def test_failed_or_live_continuations_are_not_restarted(routes):
    sign_in(routes.client)
    request_id = routes.request["id"]
    item = routes.env.owner.answer_request("actor", request_id, answer_body())
    routes.env.state.replace("actor", item, {"status": "continuing", "continuation_claim": "live"}, item["_etag"])
    response = routes.client.post(
        f"/api/v2/user-input/{request_id}/continue", json={"submission_id": "answer-once"},
        headers={"X-CSRFToken": "fixture-token"},
    )
    assert response.status_code == 409
    assert not routes.calls


def test_stopping_saved_answers_cannot_start_the_task(routes):
    sign_in(routes.client)
    path = "/api/v2/user-input/" + routes.request["id"]
    headers = {"X-CSRFToken": "fixture-token"}
    saved = routes.client.post(path + "/answer", json=answer_body(), headers=headers)
    assert saved.status_code == 200
    stopped = routes.client.post(path + "/stop", json={"submission_id": "answer-once"}, headers=headers)
    assert stopped.status_code == 200 and stopped.json == {"cancel_requested": True, "status": "cancelled"}
    continued = routes.client.post(path + "/continue", json={"submission_id": "answer-once"}, headers=headers)
    assert continued.status_code == 409 and not routes.calls
    sign_in(routes.client, "peer")
    foreign = routes.client.post(path + "/stop", json={"submission_id": "answer-once"}, headers=headers)
    assert foreign.status_code == 404


def test_cancellation_is_durable_and_unauthenticated_access_is_rejected(routes):
    path = "/api/v2/user-input/" + routes.request["id"]
    anonymous = routes.client.get("/api/v2/user-input/pending?conversation_id=conversation")
    assert anonymous.status_code == 401
    sign_in(routes.client)
    body = answer_body()
    body["response"] = {"action": "cancel", "content": {"audience": "discard this"}}
    cancelled = routes.client.post(path + "/answer", json=body, headers={"X-CSRFToken": "fixture-token"})
    assert cancelled.status_code == 200
    pending = routes.client.get("/api/v2/user-input/pending?conversation_id=conversation")
    assert pending.status_code == 200 and pending.json["requests"] == []
    assert not routes.calls


@pytest.mark.parametrize("cancelled", [False, True])
def test_real_chat_route_reconstructs_and_continues_the_retained_sk_thread(routes, monkeypatch, cancelled):
    delegation = importlib.import_module("agent_delegation_runtime")
    contexts = importlib.import_module("agent_execution_context")
    agents = importlib.import_module("functions_agent_delegation")
    monkeypatch.setattr(routes.owner, "_chat_continue", routes.real_continue)
    monkeypatch.setattr(contexts, "capture_execution_identity", lambda *args, **kwargs: routes.env.identity)
    monkeypatch.setattr(delegation, "_build_local_agent", lambda *args, **kwargs: routes.env.make_agent())
    monkeypatch.setattr(agents, "resolve_delegation_agent", lambda *args, **kwargs: {"id": "reader", "name": "Reader"})
    persisted = []

    def persist(message, user_id, **kwargs):
        persisted.append(message)
        return message

    monkeypatch.setitem(sys.modules, "route_backend_chats", module("route_backend_chats", _persist_screened_assistant=persist))
    monkeypatch.setitem(sys.modules, "functions_m365_runtime", module(
        "functions_m365_runtime", initialize_m365_chat_context=lambda *args: None,
        record_m365_pending=lambda error: error.payload, record_m365_auth_wait=lambda error: error.payload,
    ))
    sign_in(routes.client)
    path = "/api/v2/user-input/" + routes.request["id"]
    headers = {"X-CSRFToken": "fixture-token"}
    saved = routes.client.post(path + "/answer", json=answer_body(), headers=headers)
    assert saved.status_code == 200
    reached = Event()
    errors = []
    worker = None
    if cancelled:
        async def hold_model(self, history, settings):
            reached.set()
            await asyncio.wait_for(asyncio.Event().wait(), timeout=6)

        monkeypatch.setattr(type(routes.env.runtime.service), "_inner_get_chat_message_contents", hold_model)

        def stop_after_model_started():
            if not reached.wait(timeout=5):
                errors.append("The retained model invocation did not start.")
                return
            try:
                routes.env.owner.stop_request("actor", routes.request["id"], "answer-once")
            except Exception as error:
                errors.append(type(error).__name__)

        worker = Thread(target=stop_after_model_started, daemon=True)
        worker.start()
    response = routes.client.post(path + "/continue", json={"submission_id": "answer-once"}, headers=headers)
    assert response.status_code == 200
    frames = response.get_data(as_text=True)
    if worker:
        worker.join(timeout=5)
        assert not worker.is_alive() and not errors, errors
    if cancelled:
        assert '"cancelled": true' in frames and '"error"' not in frames
        assert routes.env.effects == ["completed-before-question"] and not persisted
        current = routes.env.owner.read_request("actor", routes.request["id"])
        assert current["status"] == "cancelled"
        return
    assert '"done": true' in frames and '"error"' not in frames
    assert routes.env.effects == ["completed-before-question", "after-answers"]
    assert len(persisted) == 1
    assert persisted[0]["metadata"]["user_input_answers"]["Who is this for?"] == "Partners"
    assert persisted[0]["metadata"]["token_usage"]["total_tokens"] >= 3
    repeated = routes.client.post(path + "/continue", json={"submission_id": "answer-once"}, headers=headers)
    assert repeated.status_code == 200
    assert routes.env.effects == ["completed-before-question", "after-answers"] and len(persisted) == 1
