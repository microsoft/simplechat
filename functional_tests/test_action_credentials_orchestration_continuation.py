# test_action_credentials_orchestration_continuation.py
"""Real orchestration leases/checkpoints and independent credential waits.

Version: 0.261.343
Implemented in: 0.261.333
Worker authorization and durable outcome regressions added in: 0.261.343

Only external action/model/storage I/O is doubled. Retained completed steps,
conditional continuation admission and immutable execution guards remain real.
"""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
from threading import Barrier, current_thread, main_thread
from types import SimpleNamespace
from flask import Blueprint, Flask, g, has_request_context, session
import pytest

from test_orchestration_continuation import harness, initialized_continuation
from test_orchestration_action_chart_delivery import ACTION, _enable_action, _normalize, _store
from test_action_personal_credentials import CredentialContainer, manifest
from test_support.orchestration_harness_execution import compose_step, input_binding
from test_support.orchestration_revisions import AtomicMemoryContainer


def configure_real_credentials(harness, monkeypatch, raw):
    """Keep runtime, catalog and conversation authorization real; double storage I/O."""
    credentials = importlib.import_module("functions_action_credentials")
    continuation = importlib.import_module("functions_action_credential_continuation")
    runtime = importlib.import_module("functions_action_credential_runtime")
    chats = importlib.import_module("route_backend_chats")
    monkeypatch.setattr(chats, "cosmos_conversations_container", harness.conversations)
    actions = AtomicMemoryContainer("id")
    actions.create_item(dict(raw))
    monkeypatch.setattr(harness.config, "cosmos_global_actions_container", actions)
    monkeypatch.setattr(importlib.import_module("functions_settings"), "get_settings",
                        lambda: deepcopy(harness.settings))
    monkeypatch.setattr(credentials, "_services", credentials._services)
    monkeypatch.setattr(continuation, "_services", continuation._services)
    runtime.configure_action_credential_runtime()
    identity = {"id": "fixture-identity", "_etag": "identity-etag", "name": "Mission",
                "auth": {"auth_type": "api_key"}, "usage_contexts": ["action"],
                "supported_source_types": ["action"], "provider": "generic"}
    monkeypatch.setattr(credentials, "_services", replace(
        credentials.credential_services(),
        read_identity=lambda scope, user, identity_id: deepcopy(identity),
        list_identities=lambda scope, user: [deepcopy(identity)],
    ))
    return credentials


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


@pytest.mark.parametrize("outcome", [
    "success", "action_failure", "renewed_challenge", "downstream_failure", "authorization_failure",
])
def test_owned_continue_consumes_only_selected_wait_and_never_replays_completed_steps(harness, monkeypatch, outcome):
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
    configure_real_credentials(harness, monkeypatch, raw)
    waits = {}

    def action(step, context, **kwargs):
        descriptor = adapters._credential_step_continuation(step, context)
        pending = state.request_for(
            "owner", "conversation-1", credentials.manifest_reference(raw), fingerprint, {"service": "api_key"},
            reason="setup_required", continuation=descriptor,
        ) if step["step_id"] not in waits else state.read("owner", waits[step["step_id"]])
        waits[step["step_id"]] = pending["id"]
        if pending["status"] == "continuing":
            if outcome == "action_failure":
                return harness.schema.build_step_result(
                    status="failed", failure=harness.schema.build_failure("step_failed"),
                )
            if outcome == "renewed_challenge":
                pending = state.request_for(
                    "owner", "conversation-1", credentials.manifest_reference(raw), fingerprint,
                    {"service": "api_key"}, reason="credentials_rejected", continuation=descriptor,
                )
                return adapters._credential_wait_result(
                    contracts.ActionCredentialsRequired(credentials.safe_request(pending, raw)), kwargs.get("emit"),
                )
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

    def continue_wait(name, expected="completed"):
        item = state.read("owner", waits[name])
        path = f"/api/action-credentials/{item['id']}"
        info = client.get(path)
        assert info.status_code == 200
        submitted = client.post(
            path + "/submit", headers={"X-CSRFToken": info.json["csrf_token"]},
            json={"expected_etag": item["_etag"], "slots": [{"slot": "service", "identity_id": "fixture-identity"}]},
        )
        assert submitted.status_code == 200, submitted.json
        ready = submitted.json["credential_request"]
        if outcome == "authorization_failure":
            actions = harness.config.cosmos_global_actions_container
            original_read = actions.read_item
            def unavailable(*args, **kwargs):
                if current_thread() is not main_thread():
                    raise RuntimeError("PRIVATE_AUTHORIZATION_SENTINEL")
                return original_read(*args, **kwargs)
            monkeypatch.setattr(actions, "read_item", unavailable)
        response = client.post(
            path + "/continue", headers={"X-CSRFToken": info.json["csrf_token"]},
            json={"expected_etag": ready["etag"]},
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        frames = response.get_data(as_text=True)
        assert "PRIVATE_AUTHORIZATION_SENTINEL" not in frames
        assert response.mimetype == "text/event-stream"
        completed = state.read("owner", ready["id"])
        assert completed["status"] == expected
        repeated = client.post(
            path + "/continue", headers={"X-CSRFToken": info.json["csrf_token"]},
            json={"expected_etag": ready["etag"]},
        )
        assert repeated.status_code == 409
        return frames

    continue_wait("one", {
        "action_failure": "failed", "authorization_failure": "failed", "renewed_challenge": "superseded",
    }.get(outcome, "completed"))
    midway = harness.read()
    if outcome == "authorization_failure":
        assert midway["status"] == "failed"
        assert completed_calls == []
        assert midway["task_results"]["before"] == original_before
        return
    if outcome in {"action_failure", "renewed_challenge"}:
        assert midway["status"] == "waiting"
        if outcome == "action_failure":
            selected = next(row for row in midway["execution_steps"] if row["step_id"] == "one")
            assert selected["status"] == "failed"
        assert completed_calls == []
        assert midway["task_results"]["before"] == original_before
        assert midway["pending_results"]["two"]["request_id"] == waits["two"]
        if outcome == "renewed_challenge":
            renewed = state.read("owner", midway["pending_results"]["one"]["request_id"])
            assert renewed["id"] != waits["one"]
            assert renewed["status"] == "pending"
        return
    assert midway["status"] == "waiting"
    assert completed_calls == ["one"]
    assert midway["task_results"]["before"] == original_before
    assert midway["pending_results"]["two"]["request_id"] == waits["two"]
    assert midway["execution_deadline_at"] == original_deadline
    if outcome == "downstream_failure":
        def fail_answer(*args, **kwargs):
            return harness.schema.build_step_result(status="failed", failure=harness.schema.build_failure("step_failed"))
        monkeypatch.setattr(executor, "_dependency_adapter", lambda capability_id:
                            action if capability_id == "action_invoke" else fail_answer)
    continue_wait("two")
    done = harness.read()
    assert done["status"] == ("failed" if outcome == "downstream_failure" else "completed")
    assert completed_calls == ["one", "two"]
    assert done["task_results"]["before"] == original_before
    assert done["execution_deadline_at"] == original_deadline
    assert len(harness.model_calls) == (1 if outcome == "downstream_failure" else 2)


@pytest.mark.parametrize("capability", ["action_invoke", "agent_invoke"])
@pytest.mark.parametrize("access", [
    "allowed", "missing_identity", "wrong_user", "wrong_conversation", "revoked", "changed", "storage_failure",
])
def test_saved_wait_authorization_uses_real_isolated_identity(harness, monkeypatch, capability, access):
    state = importlib.import_module("functions_action_credential_state")
    contracts = importlib.import_module("action_credential_contracts")
    adapters = importlib.import_module("functions_orchestration_adapters")
    executor = importlib.import_module("functions_orchestration_executor")
    identity_owner = importlib.import_module("agent_execution_context")
    monkeypatch.setattr(state, "_container", CredentialContainer("user_id"))
    harness.settings["enable_semantic_kernel"] = True
    raw = manifest()
    credentials = configure_real_credentials(harness, monkeypatch, raw)
    events = []
    monkeypatch.setattr(executor, "log_event", lambda message, **kwargs: events.append((message, kwargs)))
    app = Flask("credential-worker-isolation")
    app.secret_key = "local-test-only"

    def prepare(user, conversation):
        context = SimpleNamespace(
            user_id=user, conversation_id=conversation, run_id=f"run-{user}", turn_id="turn",
            pending_results={}, task_results={"step": None},
        )
        step = {"step_id": "step", "capability_id": capability}
        descriptor = adapters._credential_step_continuation(step, context)
        item = state.request_for(user, conversation, credentials.manifest_reference(raw),
                                 contracts.credential_fingerprint(raw), {"service": "api_key"},
                                 reason="setup_required", continuation=descriptor)
        context.pending_results["step"] = {"kind": "action_credentials", "request_id": item["id"]}
        with app.test_request_context():
            session["user"] = {"oid": user, "roles": ["User"]}
            context.agent_execution_identity = identity_owner.capture_execution_identity(user, conversation)
        return step, context

    step, context = prepare("owner", "conversation-1")
    if access == "missing_identity":
        context.agent_execution_identity = None
    elif access in {"wrong_user", "wrong_conversation"}:
        context.agent_execution_identity = replace(
            context.agent_execution_identity,
            **({"user_id": "other"} if access == "wrong_user" else {"conversation_id": "foreign"}),
        )
    elif access in {"revoked", "changed"}:
        actions = harness.config.cosmos_global_actions_container
        stored = actions.read_item("mission", "mission")
        stored.update({"is_enabled": False} if access == "revoked" else {"endpoint": "https://changed.invalid"})
        actions.upsert_item(stored)
    elif access == "storage_failure":
        def unavailable(*args, **kwargs):
            raise RuntimeError("PRIVATE_STORAGE_SENTINEL")
        monkeypatch.setattr(harness.config.cosmos_global_actions_container, "read_item", unavailable)

    def resume(selected, current):
        assert not has_request_context()
        try:
            return executor.resume_waiting_dependency_step(
                selected, current, settings=harness.settings, user_id=current.user_id,
                input_fingerprint="fixture",
            )
        finally:
            assert not has_request_context()

    with ThreadPoolExecutor(max_workers=2) as workers:
        if access == "allowed":
            harness.conversations.create_item({"id": "conversation-2", "user_id": "other"})
            other_step, other = prepare("other", "conversation-2")
            actions = harness.config.cosmos_global_actions_container
            original_read = actions.read_item
            barrier, observed = Barrier(2), []
            def read_with_overlapping_contexts(*args, **kwargs):
                observed.append((session["user"]["oid"], g.conversation_id))
                barrier.wait(timeout=10)
                return original_read(*args, **kwargs)
            monkeypatch.setattr(actions, "read_item", read_with_overlapping_contexts)
            futures = [workers.submit(resume, step, context), workers.submit(resume, other_step, other)]
            results = [future.result() for future in futures]
            assert all(result["status"] == "waiting" for result in results)
            assert sorted(observed) == [("other", "conversation-2"), ("owner", "conversation-1")]
        else:
            failure = (contracts.ActionCredentialError if access == "changed"
                       else RuntimeError if access == "storage_failure" else PermissionError)
            future = workers.submit(resume, step, context)
            with pytest.raises(failure):
                future.result()
            assert events[-1][1]["extra"]["stage"] == "credential_resume_authorization"
            assert events[-1][1]["extra"]["error_type"] == failure.__name__
            assert len(events[-1][1]["extra"]["run_id_hash"]) == 64
            assert "run-owner" not in repr(events)
            assert "PRIVATE_STORAGE_SENTINEL" not in repr(events)


@pytest.mark.parametrize("status,step_status,wait_id,expected", [
    ("completed", "completed", None, "completed"),
    ("failed", "completed", None, "completed"),
    ("waiting", "partial", None, "completed"),
    ("waiting", "failed", None, "failed"),
    ("cancelled", "waiting", "request", "failed"),
    ("failed", "waiting", "request", "failed"),
    ("waiting", "waiting", "new-request", "superseded"),
    ("waiting", "waiting", "request", None),
    ("running", "running", None, None),
])
def test_credential_outcome_uses_selected_durable_step(initialized_continuation, status, step_status, wait_id, expected):
    execution = importlib.import_module("functions_orchestration_execution")
    record = {"id": "run", "user_id": "owner", "conversation_id": "conversation"}
    runner = execution.HarnessExecution(record, None)
    item = {**record, "id": "request", "continuation": {"run_id": "run", "step_id": "selected"}}
    row = {"step_id": "selected", "status": step_status}
    if wait_id:
        row["wait"] = {"kind": "action_credentials", "request_id": wait_id}
    runner._final_record = {**record, "status": status, "execution_steps": [row]}
    if expected is None:
        with pytest.raises(execution.HarnessExecutionError):
            runner.credential_continuation_status(item)
    else:
        result = runner.credential_continuation_status(item)
        assert result == expected
    runner._final_record = None
    with pytest.raises(execution.HarnessExecutionError):
        runner.credential_continuation_status(item)


@pytest.mark.parametrize("current_status,claim", [("continuing", "new-claim"), ("pending", "old-claim")])
def test_credential_finalization_cannot_close_newer_interaction(harness, monkeypatch, current_status, claim):
    routes = importlib.import_module("route_backend_action_credentials")
    state = importlib.import_module("functions_action_credential_state")
    monkeypatch.setattr(state, "_container", CredentialContainer("user_id"))
    item = state.create("owner", {
        "id": "request", "record_type": "credential_request", "conversation_id": "conversation-1",
        "status": current_status, "continuation_claim": claim,
    })
    routes._finish_request("owner", item["id"], "old-claim", "completed")
    current = state.read("owner", item["id"])
    assert current["status"] == current_status
    assert current["_etag"] == item["_etag"]


def test_unconfirmed_execution_keeps_claim_and_logs_no_private_text(harness, monkeypatch):
    routes = importlib.import_module("route_backend_action_credentials")
    state = importlib.import_module("functions_action_credential_state")
    monkeypatch.setattr(state, "_container", CredentialContainer("user_id"))
    item = state.create("owner", {
        "id": "request", "record_type": "credential_request", "conversation_id": "conversation-1",
        "status": "continuing", "continuation_claim": "claim",
        "continuation": {"run_id": "run", "step_id": "selected"},
    })
    events = []
    monkeypatch.setattr(routes, "log_event", lambda message, **kwargs: events.append((message, kwargs)))

    class UnknownExecution:
        def execute(self):
            return []

        def credential_continuation_status(self, _item):
            raise RuntimeError("PRIVATE_PASSWORD_SENTINEL")

    wrapped = routes._CredentialExecution(UnknownExecution(), item, "owner")
    with pytest.raises(RuntimeError):
        list(wrapped.execute())
    current = state.read("owner", item["id"])
    assert current["status"] == "continuing"
    assert current["_etag"] == item["_etag"]
    assert events[0][1]["extra"]["stage"] == "credential_continuation_finalization"
    assert "PRIVATE_PASSWORD_SENTINEL" not in repr(events)
