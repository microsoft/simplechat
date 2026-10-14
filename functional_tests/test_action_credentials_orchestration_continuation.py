# test_action_credentials_orchestration_continuation.py
"""Real orchestration leases/checkpoints and independent credential waits.

Version: 0.261.335
Implemented in: 0.261.333

Only external action/model/storage I/O is doubled. Retained completed steps,
conditional continuation admission and immutable execution guards remain real.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
from flask import Blueprint, Flask

from test_orchestration_continuation import harness, initialized_continuation
from test_orchestration_action_chart_delivery import ACTION, _enable_action, _normalize, _store
from test_action_personal_credentials import CredentialContainer, manifest
from test_support.orchestration_harness_execution import compose_step, input_binding


def test_human_wait_budget_is_bounded_and_original_deadline_is_immutable():
    clock = importlib.import_module("action_credential_deadline")
    now = datetime.now(timezone.utc)
    original = (now + timedelta(seconds=20)).isoformat()
    record = {
        "execution_deadline_at": original, "status": "waiting",
        "credential_wait_started_at": now.isoformat(),
        "pending_results": {"action": {"kind": "action_credentials", "request_id": "request"}},
    }
    continued = clock.finish_human_wait(record, now=now + timedelta(minutes=30))
    assert continued["credential_wait_seconds"] == 1800
    assert continued["credential_wait_started_at"] is None
    assert record["execution_deadline_at"] == original
    running = {**record, **continued, "status": "running"}
    assert clock.execution_deadline(running) == now + timedelta(seconds=1820)
    exhausted = clock.execution_deadline(record, now=now + timedelta(days=2))
    assert exhausted == datetime.fromisoformat(original) + timedelta(days=1)


def test_owned_continue_consumes_only_selected_wait_and_never_replays_completed_steps(harness, monkeypatch):
    state = importlib.import_module("functions_action_credential_state")
    credentials = importlib.import_module("functions_action_credentials")
    adapters = importlib.import_module("functions_orchestration_adapters")
    contracts = importlib.import_module("action_credential_contracts")
    executor = importlib.import_module("functions_orchestration_executor")
    monkeypatch.setattr(state, "_container", CredentialContainer("user_id"))
    completed_calls = _enable_action(harness, monkeypatch, with_chart=False)
    original_action = executor._dependency_adapter("action_invoke")
    original_resolver = executor._dependency_adapter
    raw = manifest()
    fingerprint = contracts.credential_fingerprint(raw)
    monkeypatch.setattr(credentials, "authorized_manifest", lambda user_id, reference: deepcopy(raw))
    monkeypatch.setattr(credentials, "authorize_conversation", lambda user_id, conversation_id:
                        harness.bootstrap.read_owned_conversation(user_id, conversation_id))
    waits = {}

    def action(step, context, **kwargs):
        descriptor = adapters._credential_step_continuation(step, context)
        pending = state.request_for(
            "owner", "conversation-1", ACTION["action_ref"], fingerprint, {"service": "api_key"},
            reason="setup_required", continuation=descriptor,
        ) if step["step_id"] not in waits else state.read("owner", waits[step["step_id"]])
        waits[step["step_id"]] = pending["id"]
        if pending["status"] == "continuing":
            return original_action(step, context, **kwargs)
        return adapters._credential_wait_result(
            contracts.ActionCredentialsRequired(credentials.safe_request(pending, raw)), kwargs.get("emit"),
        )

    monkeypatch.setattr(executor, "_dependency_adapter",
                        lambda capability_id: action if capability_id == "action_invoke" else original_resolver(capability_id))
    steps = [compose_step("before")]
    for name in ("one", "two"):
        steps.append({
            "step_id": name, "capability_id": "action_invoke",
            "arguments": {"action_ref": ACTION["action_ref"], "task": f"Read {name}"},
        })
    steps.append(compose_step("answer", inputs={
        name: {"binding": input_binding(name, "prepared"), "allow_partial": False} for name in ("one", "two")
    }))
    plan = _normalize(harness, {"steps": steps, "final_response": input_binding("answer")})
    _store(harness, plan, replies=["Completed before connecting.", "The action results are ready."])
    execution = harness.prepare()
    progress = []
    initial_frames = list(execution.execute(emit=progress.append))
    waiting_run = harness.read()
    assert waiting_run["status"] == "waiting"
    assert len(waits) == 2
    assert waiting_run["credential_wait_started_at"]
    assert "action_credentials_required" in "".join([*progress, *initial_frames])
    original_deadline = waiting_run["execution_deadline_at"]
    original_before = deepcopy(waiting_run["task_results"]["before"])
    scheduled = harness.continuation.claim_run_continuation(
        "run-1", "owner", "conversation-1",
        authorize=lambda: harness.bootstrap.read_owned_conversation("owner", "conversation-1"),
        message_container=harness.messages,
    )
    assert scheduled is None
    routes = importlib.import_module("route_backend_action_credentials")
    orchestration_routes = importlib.import_module("route_backend_orchestration")
    monkeypatch.setattr(routes, "get_current_user_id", lambda: "owner")
    monkeypatch.setattr(routes, "login_required", lambda function: function)
    monkeypatch.setattr(routes, "user_required", lambda function: function)
    monkeypatch.setattr(routes, "authorize_conversation", credentials.authorize_conversation)
    monkeypatch.setattr(orchestration_routes, "cosmos_conversations_container", harness.conversations)
    monkeypatch.setattr(orchestration_routes, "cosmos_messages_container", harness.messages)
    monkeypatch.setattr(importlib.import_module("functions_settings"), "get_settings", lambda: deepcopy(harness.settings))
    monkeypatch.setattr(importlib.import_module("functions_authentication"), "get_user_profile_image", lambda: None)
    app = Flask("credential-orchestration")
    app.secret_key = "local-test-only"
    bp = Blueprint("credential-orchestration", __name__)
    routes.register_route_backend_action_credentials(bp)
    app.register_blueprint(bp)
    client = app.test_client()
    with client.session_transaction() as browser:
        browser["user"] = {"oid": "owner", "roles": ["User"]}

    def continue_wait(name):
        item = state.read("owner", waits[name])
        ready = state.replace("owner", item, {"status": "ready"}, item["_etag"])
        path = f"/api/action-credentials/{ready['id']}"
        info = client.get(path)
        assert info.status_code == 200
        response = client.post(
            path + "/continue", headers={"X-CSRFToken": info.json["csrf_token"]},
            json={"expected_etag": ready["_etag"]},
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        frames = response.get_data(as_text=True)
        assert response.mimetype == "text/event-stream"
        completed = state.read("owner", ready["id"])
        assert completed["status"] == "completed"
        repeated = client.post(
            path + "/continue", headers={"X-CSRFToken": info.json["csrf_token"]},
            json={"expected_etag": ready["_etag"]},
        )
        assert repeated.status_code == 409
        return frames

    continue_wait("one")
    midway = harness.read()
    assert midway["status"] == "waiting"
    assert completed_calls == ["one"]
    assert midway["task_results"]["before"] == original_before
    assert midway["pending_results"]["two"]["request_id"] == waits["two"]
    assert midway["execution_deadline_at"] == original_deadline
    continue_wait("two")
    done = harness.read()
    assert done["status"] == "completed"
    assert completed_calls == ["one", "two"]
    assert done["task_results"]["before"] == original_before
    assert done["execution_deadline_at"] == original_deadline
    assert len(harness.model_calls) == 2
