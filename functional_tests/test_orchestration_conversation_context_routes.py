# test_orchestration_conversation_context_routes.py
"""
Functional tests for conversation context across current orchestration HTTP/SSE routes.
Version: 0.261.139
Implemented in: 0.261.096
Prompt attachment integration: 0.261.097
Direct action integration: 0.261.098
Resolver response compatibility and bounded recovery: 0.261.103
Authorized model routing and completion metadata: 0.261.103
Atomic plan revision persistence: 0.261.102
Single orchestration contract updated in: 0.261.139

Uses the production Flask orchestration Blueprint through the initialized offline
Gather / Reason / Render harness. The tests keep the route-level conversation
context guarantees that still apply after legacy plan execution was removed.
"""

import json
import importlib
import sys
import unittest
from types import ModuleType
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from azure.core.exceptions import AzureError
from flask import Blueprint, Flask, has_request_context
from werkzeug.test import Client
from werkzeug.wrappers import Response

from test_orchestration_conversation_context import LATEST, RESOLVED, fake_module, load_modules, message, winery_history
from test_orchestration_model_selection import TERRA_SELECTION, endpoint_runtime, model_endpoint
from test_orchestration_harness_routes import modules, real_http_harness  # noqa: F401
from test_support.app_stubs import stubbed_config
from test_support.orchestration_harness_execution import compose_step, input_binding
from test_support.orchestration_revisions import AtomicMemoryContainer
from test_support.versioning import assert_app_version_at_least


ANSWER = "You mean the wineries near Grants Pass. I do not have verified Wednesday hours."


class ModelBoundary:
    def __init__(self, modules):
        self.modules = modules
        self.calls = []
        self.resolution_override = None
        self.resolution_responses = []
        self.plan_override = None
        self.answer_response = None
        self.answer_error = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs, default=str)))
        system = kwargs["messages"][0]["content"]
        if system == self.modules.planner.RESOLUTION_SYSTEM_PROMPT:
            payload = self.resolution_responses.pop(0) if self.resolution_responses else self.resolution_override
            text = json.dumps(payload if payload is not None else {
                "relationship": "follow_up", "resolved_message": RESOLVED,
                "message_ids": ["u1", "u2", "a2"], "requires_retrieval": True,
                "clarification": "",
            })
        elif self.modules.planner.PLAN_EDIT_INSTRUCTIONS in system:
            raise AssertionError("Plan edit calls are handled by the plan revision fixture.")
        elif system == self.modules.planner.PLANNER_SYSTEM_PROMPT:
            request_text = json.loads(kwargs["messages"][1]["content"])["message"]
            text = json.dumps(self.plan_override or json.loads(_search_then_answer_plan(request_text)))
        else:
            if self.answer_error is not None:
                raise self.answer_error
            if self.answer_response is not None:
                return self.answer_response
            text = ANSWER
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=text, refusal=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


class ConversationRouteModel:
    def __init__(self, client, deployment, *, provider="aoai", endpoint_id="", model_id="",
                 behavior_name="", reasoning_effort="", source="legacy", answer_selection=None):
        self.client = client
        self.deployment = deployment
        self.provider = provider
        self.endpoint_id = endpoint_id
        self.model_id = model_id
        self.behavior_name = behavior_name or deployment
        self.response_length = None
        self.reasoning_effort = reasoning_effort
        self.source = source
        self.model_metadata = {"deploymentName": deployment, "modelName": self.behavior_name}
        self.reasoning_resolution = {
            "requested_effort": reasoning_effort or None,
            "effective_effort": (None if reasoning_effort == "none" else reasoning_effort) or None,
            "mode": "explicit" if reasoning_effort else "model_default",
            "adjustment_reason": None,
        }
        self._answer_selection = answer_selection
        self.closed = False

    def answer_model_selection(self):
        if self._answer_selection is not None:
            return dict(self._answer_selection)
        return {
            key: value for key, value in {
                "model_deployment": self.deployment, "model_provider": self.provider,
                "model_endpoint_id": self.endpoint_id, "model_id": self.model_id,
            }.items() if value
        }

    def metadata(self):
        return {
            key: value for key, value in {
                "model_deployment_name": self.deployment, "model_provider": self.provider,
                "model_endpoint_id": self.endpoint_id, "model_id": self.model_id,
            }.items() if value
        }

    def as_planner_client(self):
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self.create_completion)))

    def create_completion(self, **kwargs):
        parameters = dict(kwargs)
        parameters.pop("use_model_response_length", None)
        if "max_tokens" in parameters and "max_completion_tokens" not in parameters:
            parameters["max_completion_tokens"] = parameters.pop("max_tokens")
        if self.behavior_name.startswith("gpt-5") or self.behavior_name.startswith("gpt-6"):
            parameters.pop("temperature", None)
        if self.reasoning_effort:
            if self.reasoning_effort == "minimal" and "luna" in self.behavior_name:
                parameters["reasoning_effort"] = "low"
                self.reasoning_resolution = {
                    "requested_effort": "minimal", "effective_effort": "low",
                    "mode": "explicit", "adjustment_reason": "unsupported_reasoning_effort",
                }
            else:
                parameters["reasoning_effort"] = self.reasoning_effort
        parameters.setdefault("model", self.deployment)
        return self.client.chat.completions.create(**parameters)

    def close(self):
        self.closed = True
        close = getattr(self.client, "close", None)
        if callable(close):
            close()


class ConversationRouteTests(unittest.TestCase):
    def setUp(self):
        self.conversations = AtomicMemoryContainer("id")
        self.messages = AtomicMemoryContainer("conversation_id")
        self.runs = AtomicMemoryContainer("conversation_id")
        self.steps = AtomicMemoryContainer("run_id")
        self.results = AtomicMemoryContainer("run_id")
        self.conversations.upsert_item({"id": "conv1", "user_id": "user1", "title": "Wineries"})
        for row in winery_history():
            self.messages.upsert_item(row)
        self.settings = {
            "enable_chat_orchestration": True,
            "enable_user_workspace": True,
            "conversation_history_limit": 6,
            "gpt_model": {"selected": [{"deploymentName": "answer", "modelName": "gpt-4o"}]},
            "azure_openai_gpt_endpoint": "https://offline.invalid",
            "azure_openai_gpt_api_version": "2024-10-21",
            "azure_openai_gpt_key": "offline-fixture-not-a-credential",
        }
        config = {
            "cosmos_conversations_container": self.conversations,
            "cosmos_messages_container": self.messages,
            "cosmos_orchestration_runs_container": self.runs,
            "cosmos_orchestration_run_steps_container": self.steps,
            "cosmos_personal_workflow_run_items_container": self.results,
            "cognitive_services_scope": "https://cognitiveservices.azure.com/.default",
        }
        identity = lambda function: function
        dependencies = {
            "functions_authentication": fake_module(
                "functions_authentication",
                get_current_user_id=lambda: "user1",
                get_current_user_info=lambda: {"email": "test@example.test"},
                login_required=identity, user_required=identity,
                user_required_blueprint=lambda: identity,
            ),
            "swagger_wrapper": fake_module(
                "swagger_wrapper", get_auth_security=lambda: [],
                swagger_route=lambda **kwargs: identity,
            ),
            "functions_conversation_cache": fake_module(
                "functions_conversation_cache",
                invalidate_conversation_cache_for_item=lambda *args, **kwargs: None,
            ),
        }
        with stubbed_config(**config):
            self.modules = load_modules()
            with patch.dict(sys.modules, dependencies):
                import route_backend_orchestration as route
                import functions_orchestration_runs as store
                import functions_orchestration_plan_editing as editing
                import functions_orchestration_recovery as recovery
                self.route = route
                self.store = store
                self.editing = editing
                self.recovery = recovery
        self.model = ModelBoundary(self.modules)
        self.search_queries = []
        self.after_search = None

        def search(query, *args, **kwargs):
            self.search_queries.append(query)
            if self.after_search:
                self.after_search()
            return []

        def model_resolver(settings, *, user_id, seeds=None, planner=False, identity_context=None):
            seeds = seeds or {}
            selection = seeds.get("model") or {}
            deployment = selection.get("model_deployment") or "answer"
            provider = selection.get("model_provider") or "aoai"
            endpoint_id = selection.get("model_endpoint_id") or ""
            model_id = selection.get("model_id") or ""
            if settings.get("enable_multi_model_endpoints") and endpoint_id:
                resolved = self.model_runtime.resolve_model_endpoint_from_context(
                    settings, {
                        "endpoint_id": endpoint_id, "model_id": model_id,
                        "model_deployment": deployment, "provider": provider,
                        "user_id": user_id, "active_group_ids": seeds.get("active_group_ids") or [],
                    }, authorize=True,
                )
                if resolved is None:
                    raise PermissionError("selected model is unavailable")
            behavior = deployment
            source = "request" if selection else "legacy"
            answer_selection = None
            if planner and settings.get("chat_orchestration_planner_model_id") == "luna-model":
                answer_selection = {
                    "model_deployment": "gpt-5.6-terra", "model_provider": "aoai",
                    "model_endpoint_id": "selected-endpoint", "model_id": "terra-model",
                }
                deployment = "gpt-5.6-luna"
                endpoint_id = "selected-endpoint"
                model_id = "luna-model"
                behavior = "gpt-5.6-luna"
                source = "planner_override"
            elif settings.get("enable_multi_model_endpoints") and not selection:
                default = settings.get("default_model_selection") or {}
                endpoint = self.endpoint if hasattr(self, "endpoint") else model_endpoint()
                resolved = self.model_runtime.resolve_model_endpoint_from_context(
                    settings, {
                        "endpoint_id": default.get("endpoint_id", "selected-endpoint"),
                        "model_id": default.get("model_id", "terra-model"),
                        "model_deployment": "", "provider": default.get("provider", "aoai"),
                        "user_id": user_id, "active_group_ids": seeds.get("active_group_ids") or [],
                    }, authorize=True,
                )
                if resolved is None:
                    raise PermissionError("selected model is unavailable")
                selected_model = next(
                    item for item in endpoint["models"] if item["id"] == default.get("model_id", "terra-model")
                )
                client, _protocol = self.model_runtime.build_model_endpoint_sync_chat_client(
                    endpoint["auth"], endpoint["provider"], endpoint["connection"]["endpoint"],
                    endpoint["connection"]["openai_api_version"], selected_model["deploymentName"],
                    settings=settings, endpoint_config=endpoint, identity_context={**(identity_context or {}), "user_id": user_id},
                )
                return ConversationRouteModel(
                    SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=self.model.create)),
                                    close=client.close),
                    selected_model["deploymentName"], endpoint_id=endpoint["id"], model_id=selected_model["id"],
                    behavior_name=selected_model["modelName"], reasoning_effort=seeds.get("reasoning_effort", ""),
                    source="default",
                )
            return ConversationRouteModel(
                self.model, deployment, provider=provider, endpoint_id=endpoint_id, model_id=model_id,
                behavior_name=behavior, reasoning_effort=seeds.get("reasoning_effort", ""), source=source,
                answer_selection=answer_selection,
            )

        def prepare_execution(record, data, user_id, settings, snapshot, identity, execution_identity, services):
            try:
                claimed = self.route.claim_plan_run(
                    record["id"], user_id, record["conversation_id"], plan_id=data.get("plan_id"),
                    expected_version=data.get("expected_version"), edits=data.get("edits"),
                    conversation_context=snapshot, result_alias_resolver=lambda current: {},
                    export_catalog=[], composition_profiles={},
                    settings=settings,
                )
            except (self.route.PlanRevisionError, AzureError) as exc:
                if isinstance(exc, self.route.PlanRevisionError):
                    payload, status = self.route._plan_edit_error(exc)
                    return self.route.jsonify(payload), status
                return self.route.jsonify({"error": "The saved plan is unavailable. Please retry."}), 503
            plan = claimed["plan"]
            for step in plan.get("steps") or []:
                if step.get("capability_id") == "document_search" and step.get("enabled", True):
                    search((step.get("arguments") or {}).get("query") or claimed.get("resolved_message"))
                if step.get("capability_id") == "web_search" and step.get("enabled", True):
                    augmentation = []
                    try:
                        import route_backend_chats
                        route_backend_chats.perform_web_search(
                            web_search_query_text=(step.get("arguments") or {}).get("query") or claimed.get("resolved_message"),
                            system_messages_for_augmentation=augmentation,
                        )
                    except Exception:
                        pass
                    if augmentation:
                        claimed["resolved_message"] = (
                            f"{claimed.get('resolved_message')}\n"
                            + "\n".join(item.get("content", "") for item in augmentation)
                        )
            answer_model = model_resolver(
                settings, user_id=user_id,
                seeds=self.route.answer_selection(plan, claimed.get("seeds") or {}),
                identity_context=identity,
            )
            response = answer_model.create_completion(messages=[{
                "role": "user",
                "content": json.dumps({
                    "request": claimed.get("resolved_message") or claimed.get("user_message"),
                    "conversation": snapshot.get("messages", []),
                }),
            }])
            content = response.choices[0].message.content
            message_id = f"assistant-{claimed['id']}"
            self.messages.upsert_item({
                "id": message_id, "conversation_id": claimed["conversation_id"], "role": "assistant",
                "content": content, "metadata": {
                    "orchestration": {"run_id": claimed["id"]},
                    "reasoning_effort": answer_model.reasoning_resolution.get("effective_effort"),
                    "requested_reasoning_effort": answer_model.reasoning_resolution.get("requested_effort"),
                    "reasoning_adjustments": [
                        {**answer_model.reasoning_resolution, "stage": "planner"},
                        {**answer_model.reasoning_resolution, "stage": "answer"},
                    ] if answer_model.reasoning_resolution.get("adjustment_reason") else [],
                },
            })
            saved = self.runs.read_item(claimed["id"], claimed["conversation_id"])
            saved.update({
                "status": "completed", "assistant_message_id": message_id,
                "started_at": saved.get("started_at") or "2026-09-01T13:00:00+00:00",
                "completed_at": "2026-09-01T13:00:01+00:00",
                "token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            })
            self.runs.upsert_item(saved)
            terminal = {
                "type": "orchestration_done", "status": "completed", "message_id": message_id,
                **answer_model.metadata(),
            }
            return Response(f"data: {json.dumps(terminal)}\n\ndata: [DONE]\n\n", mimetype="text/event-stream")

        patches = [
            patch.object(self.store, "cosmos_orchestration_runs_container", self.runs),
            patch.object(self.store, "cosmos_orchestration_run_steps_container", self.steps),
            patch.object(self.route, "cosmos_conversations_container", self.conversations),
            patch.object(self.route, "cosmos_messages_container", self.messages),
            patch.object(self.route, "get_settings", lambda: dict(self.settings)),
            patch.object(self.route, "_now_iso", lambda: "2026-09-01T13:00:00+00:00"),
            patch.object(self.route, "resolve_orchestration_model", model_resolver),
            patch.object(self.editing, "resolve_orchestration_model", model_resolver),
            patch.object(self.route, "_prepare_execution_stream", prepare_execution),
            patch.object(self.route, "resolve_agent_catalog", lambda *args, **kwargs: []),
            patch.object(self.route, "capture_execution_identity", lambda *args: None),
            patch.object(self.route, "resolve_candidate_documents", lambda *args, **kwargs: ([], [])),
            patch.object(self.route, "_admitted_export_catalog", lambda *args, **kwargs: []),
            patch.object(self.route, "_orchestration_services", lambda *args, **kwargs: SimpleNamespace(
                results=SimpleNamespace(
                    access=SimpleNamespace(user_id="user1", conversation_id="conv1"),
                    open_result=lambda *a, **k: None,
                ),
                rendering=SimpleNamespace(
                    list_public_outputs=lambda run_id: [],
                    committed_artifacts=lambda run_id: [],
                ),
                external_source_admission=lambda *a, **k: None,
                external_source_preflight=lambda *a, **k: None,
                capture_external_source_configuration=lambda *a, **k: None,
                native_bridge_for_step=None,
                export_catalog=lambda: [],
                capability_request_bindings=lambda: {
                    "external_source_preflight": lambda *a, **k: None,
                    "external_source_admission": lambda *a, **k: None,
                    "external_source_authorizer": lambda *a, **k: True,
                    "capture_external_source_configuration": lambda *a, **k: None,
                },
            )),
            patch.dict(sys.modules, {
                "functions_search": fake_module("functions_search", hybrid_search=search),
                "config": fake_module(
                    "config",
                    cosmos_orchestration_runs_container=self.runs,
                    cosmos_orchestration_run_steps_container=self.steps,
                    cosmos_conversations_container=self.conversations,
                    cosmos_messages_container=self.messages,
                    cosmos_personal_workflow_run_items_container=self.results,
                    CLIENTS={}, SECRET_KEY="x" * 64,
                    storage_account_personal_chat_container_name="test-chat",
                ),
            }),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="orchestration-context-test-only")
        blueprint = Blueprint("context_test", __name__)
        self.route.register_route_backend_orchestration(blueprint)
        self.app.register_blueprint(blueprint)
        self.client = Client(self.app, Response)

    def plan(self, **overrides):
        body = {"message": LATEST, "conversation_id": "conv1", "turn_id": "turn1", "approval_mode": "manual"}
        body.update(overrides)
        response = self.client.post("/api/v2/orchestration/plan", json=body, buffered=True)
        return response, frames(response)

    def planned(self, **overrides):
        response, events = self.plan(**overrides)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertFalse(any(event.get("error") for event in events), events)
        return next(event["plan"] for event in events if event.get("type") == "orchestration_plan")

    def run_plan(self, plan):
        return self.client.post("/api/v2/orchestration/run", json={
            "run_id": plan["run_id"], "conversation_id": "conv1",
        }, buffered=True)

    def use_modern_models(self):
        self.endpoint = model_endpoint()
        self.model_clients = []
        self.model_runtime = endpoint_runtime(self.endpoint, None)

        class CloseOnce:
            def __init__(self):
                self.calls = []

            def __call__(self, *args, **kwargs):
                if not self.calls:
                    self.calls.append((args, kwargs))

            def assert_called_once_with(self, *args, **kwargs):
                self.assert_called_once()
                assert self.calls[0] == (args, kwargs)

            def assert_called_once(self):
                assert len(self.calls) == 1

            def assert_not_called(self):
                assert self.calls == []

        def build_client(*args, **kwargs):
            self.assertTrue(has_request_context(), "Model authorization must stay on the request thread.")
            client = SimpleNamespace(chat=self.model.chat, close=CloseOnce())
            self.model_clients.append(client)
            return client, "azure_openai"

        self.model_runtime.build_model_endpoint_sync_chat_client.side_effect = build_client
        self.settings.update({
            "enable_multi_model_endpoints": True,
            "default_model_selection": {
                "endpoint_id": "selected-endpoint", "model_id": "terra-model", "provider": "aoai",
            },
            "gpt_model": {"selected": [{"deploymentName": "gpt-4o"}]},
        })
        return dict(TERRA_SELECTION)


@pytest.fixture(autouse=True)
def no_candidate_document_probe(monkeypatch, modules):
    monkeypatch.setattr(modules.route, "resolve_candidate_documents", lambda *args, **kwargs: ([], []))


def frames(response):
    return [
        json.loads(line[5:].strip())
        for line in response.get_data(as_text=True).splitlines()
        if line.startswith("data:") and line[5:].strip() != "[DONE]"
    ]


def _conversation_row(row):
    return {**row, "conversation_id": "conversation-1"}


def _replace_history(harness, rows=None):
    harness.messages.items.clear()
    for row in rows if rows is not None else winery_history():
        harness.messages.create_item(_conversation_row(row))


def _search_then_answer_plan(query=RESOLVED):
    return json.dumps({
        "kind": "plan",
        "steps": [
            {"step_id": "search", "capability_id": "document_search", "arguments": {"query": query}},
            compose_step("answer", inputs={
                "findings": {"binding": input_binding("search", "prepared"), "allow_partial": False},
            }),
        ],
        "final_response": input_binding("answer"),
    })


def _compose_only_plan(instruction="Prepare the complete requested content."):
    step = compose_step("answer")
    step["arguments"]["instruction"] = instruction
    return json.dumps({"kind": "plan", "steps": [step], "final_response": input_binding("answer")})


def _resolution(**overrides):
    payload = {
        "relationship": "follow_up", "resolved_message": RESOLVED,
        "message_ids": ["u1", "u2", "a2"], "requires_retrieval": True,
        "clarification": "",
    }
    payload.update(overrides)
    return json.dumps(payload)


def _new_topic(message_text=LATEST):
    return _resolution(
        relationship="new_topic", resolved_message=message_text,
        message_ids=[], requires_retrieval=False, clarification=None,
    )


def _plan(runtime, message_text=LATEST, **overrides):
    body = {
        "conversation_id": "conversation-1", "turn_id": "turn-1",
        "message": message_text, "approval_mode": "manual",
    }
    body.update(overrides)
    response = runtime.client.post("/api/v2/orchestration/plan", json=body, buffered=True)
    events = frames(response)
    assert response.status_code == 200, events
    return events


def _planned(runtime, *args, **kwargs):
    events = _plan(runtime, *args, **kwargs)
    assert not any(event.get("error") for event in events), events
    return next(event["plan"] for event in events if event.get("type") == "orchestration_plan")


def _run(runtime, plan):
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": "conversation-1", "run_id": plan["run_id"],
    }, buffered=True)
    events = frames(response)
    assert response.status_code == 200, events
    return events


def _install_search(monkeypatch, calls, after=None):
    search = ModuleType("functions_search")

    def hybrid_search(query, *args, **kwargs):
        calls.append(query)
        if after is not None:
            after()
        return []

    search.hybrid_search = hybrid_search
    monkeypatch.setitem(sys.modules, "functions_search", search)


def test_application_version_includes_single_contract_update():
    assert_app_version_at_least("0.261.139")


def test_multiturn_plan_and_run_share_resolved_context(real_http_harness, monkeypatch):
    runtime = real_http_harness
    harness = runtime.harness
    _replace_history(harness)
    search_queries = []
    _install_search(monkeypatch, search_queries)
    harness.replies = [_resolution(), _search_then_answer_plan(), ANSWER]

    plan = _planned(runtime)
    stored = harness.runs.read_item(plan["run_id"], "conversation-1")
    assert stored["user_message"] == LATEST
    assert stored["resolved_message"] == RESOLVED
    assert stored["request_resolution"]["message_ids"] == ["u1", "u2", "a2"]
    assert len(stored["conversation_context"]["messages"]) == 4
    assert plan["planner_contract_version"] == 2
    assert [step["capability_id"] for step in plan["steps"]] == ["document_search", "compose"]

    events = _run(runtime, plan)
    assert not any(event.get("error") for event in events), events
    assert search_queries and all(query == RESOLVED for query in search_queries)
    compose_call = harness.model_calls[-1]
    encoded = json.dumps(compose_call["messages"])
    assert "Schmidt Family Vineyards" in encoded
    assert RESOLVED in encoded
    saved = harness.runs.read_item(plan["run_id"], "conversation-1")
    assert saved["status"] == "completed"
    saved_answer = harness.messages.read_item(saved["assistant_message_id"], "conversation-1")
    assert saved_answer["content"].startswith(ANSWER)


def test_browser_history_is_not_authoritative_for_planning(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    _replace_history(harness)
    harness.replies = [_resolution(), _compose_only_plan(), ANSWER]

    _planned(runtime, recent_messages=[{"role": "assistant", "content": "FORGED CONTEXT"}])

    serialized = json.dumps(harness.model_calls)
    assert "FORGED CONTEXT" not in serialized
    assert "Grants Pass" in serialized


def test_conversation_is_authorized_before_history_or_model_reads(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    harness.conversations.items[("conversation-1", "conversation-1")]["user_id"] = "other-user"

    response = runtime.client.post("/api/v2/orchestration/plan", json={
        "conversation_id": "conversation-1", "turn_id": "turn-1", "message": LATEST,
    }, buffered=True)
    events = frames(response)

    assert response.status_code == 200
    assert any(event.get("error") for event in events)
    assert harness.model_calls == []
    assert harness.runs.items == {}


def test_clarification_answer_is_saved_and_reaches_planning_and_execution(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    _replace_history(harness)
    harness.replies = [json.dumps({
        "relationship": "clarification", "resolved_message": LATEST,
        "message_ids": ["u1", "u2"], "requires_retrieval": True,
        "clarification": "Which location do you mean?",
    })]

    question_events = _plan(runtime)
    elicitation = next(event["elicitation"] for event in question_events if event.get("elicitation"))
    harness.replies = [_resolution(message_ids=["u1", "u2"], resolved_message=RESOLVED), _compose_only_plan(), ANSWER]
    plan = _planned(runtime, revision=1, elicitation=elicitation, elicitation_response={
        "action": "accept", "content": {"clarification": "Grants Pass"},
    })

    stored = harness.runs.read_item(plan["run_id"], "conversation-1")
    assert stored["answered_questions"][0]["answer"] == {"clarification": "Grants Pass"}
    planner_payload = json.loads(harness.model_calls[-1]["messages"][1]["content"])
    assert planner_payload["answered_now"][0]["answer"] == {"clarification": "Grants Pass"}
    _run(runtime, plan)
    assert harness.runs.read_item(plan["run_id"], "conversation-1")["status"] == "completed"


def test_replanning_reuses_user_message_and_history_cutoff(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    _replace_history(harness)
    harness.replies = [_resolution(), _compose_only_plan(), _resolution(), _compose_only_plan()]

    first = _planned(runtime)
    second = _planned(runtime, revision=1)
    first_run = harness.runs.read_item(first["run_id"], "conversation-1")
    second_run = harness.runs.read_item(second["run_id"], "conversation-1")

    assert first_run["user_message_id"] == second_run["user_message_id"]
    assert first_run["conversation_context"] == second_run["conversation_context"]
    assert second["revision"] == 1
    assert sum(row.get("content") == LATEST for row in harness.messages.items.values()) == 1


def test_run_list_does_not_expose_internal_history_snapshot(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    _replace_history(harness)
    harness.replies = [_new_topic(), _compose_only_plan()]
    _planned(runtime)

    response = runtime.client.get("/api/v2/orchestration/runs", query_string={
        "conversation_id": "conversation-1",
    })

    assert response.status_code == 200
    for record in response.get_json()["runs"]:
        assert "conversation_context" not in record
        assert "request_resolution" not in record
        assert "user_message_fingerprint" not in record


def test_prompt_snapshot_and_fingerprint_survive_replanning(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    harness.settings["enable_user_workspace"] = False
    _replace_history(harness, rows=[])
    prompt_text = "Use the winery context."
    content = f"{prompt_text}\n\n{LATEST}"
    prompt_info = {
        "id": "winery-prompt", "name": "Winery hours", "content": prompt_text,
        "template_content": prompt_text, "original_content": prompt_text,
        "composer_text": LATEST, "composer_embedded": False, "user_text": LATEST,
    }
    harness.replies = [_compose_only_plan(), _compose_only_plan()]

    first = _planned(runtime, message_text=content, prompt_info=prompt_info)
    first_run = harness.runs.read_item(first["run_id"], "conversation-1")
    stored_message = harness.messages.read_item(first_run["user_message_id"], "conversation-1")
    second = _planned(runtime, message_text=content, revision=1)
    second_run = harness.runs.read_item(second["run_id"], "conversation-1")

    assert "winery-prompt" in json.dumps(stored_message["metadata"]["prompt_selection"])
    assert second_run["user_message_id"] == first_run["user_message_id"]
    assert second_run["user_message_fingerprint"] == first_run["user_message_fingerprint"]
    assert sum(row.get("content") == content for row in harness.messages.items.values()) == 1


def test_malformed_model_step_lists_never_publish_an_executable_plan(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    _replace_history(harness)
    for proposal in ({"kind": "plan"}, {"kind": "plan", "steps": []}, {"kind": "plan", "steps": "bad"}):
        harness.runs.items.clear()
        harness.replies = [_resolution(), json.dumps(proposal)]
        events = _plan(runtime, turn_id=f"malformed-{len(harness.model_calls)}")
        assert any(event.get("error") for event in events), events
        assert not any(event.get("type") == "orchestration_plan" for event in events)
        assert harness.runs.items == {}


def test_unavailable_default_model_fails_planning_without_creating_a_run(real_http_harness, monkeypatch, modules):
    runtime = real_http_harness
    harness = runtime.harness
    monkeypatch.setattr(modules.route, "resolve_orchestration_model", lambda *args, **kwargs: (_ for _ in ()).throw(
        PermissionError("private model detail"),
    ))

    events = _plan(runtime)

    assert any("selected model is unavailable" in event.get("error", "") for event in events)
    assert harness.runs.items == {}
    assert harness.model_calls == []


def test_model_failure_releases_clarification_submission_for_retry(real_http_harness, monkeypatch, modules):
    runtime = real_http_harness
    harness = runtime.harness
    harness.replies = [json.dumps({
        "relationship": "clarification", "resolved_message": LATEST,
        "message_ids": [], "requires_retrieval": True, "clarification": "Which place?",
    })]
    elicitation = next(event["elicitation"] for event in _plan(runtime) if event.get("elicitation"))
    original = modules.route.resolve_orchestration_model
    monkeypatch.setattr(modules.route, "resolve_orchestration_model", lambda *args, **kwargs: (_ for _ in ()).throw(
        PermissionError("private unavailable"),
    ))
    failed = _plan(runtime, revision=1, elicitation=elicitation, elicitation_response={
        "action": "accept", "content": {"clarification": "Grants Pass"},
    })
    assert any("selected model is unavailable" in event.get("error", "") for event in failed)
    monkeypatch.setattr(modules.route, "resolve_orchestration_model", original)
    harness.replies = [_new_topic(), _compose_only_plan()]

    plan = _planned(runtime, revision=1, elicitation=elicitation, elicitation_response={
        "action": "accept", "content": {"clarification": "Grants Pass"},
    })

    assert harness.runs.read_item(plan["run_id"], "conversation-1")["answered_questions"][0]["answer"] == {
        "clarification": "Grants Pass",
    }


def test_persistent_resolution_failure_has_safe_diagnostics_and_no_writes(real_http_harness, monkeypatch, modules):
    runtime = real_http_harness
    harness = runtime.harness
    bad = json.dumps({
        "relationship": "follow_up", "resolved_message": "PRIVATE_MODEL_TEXT",
        "message_ids": ["user-turn-1"], "requires_retrieval": "false", "clarification": "",
    })
    harness.replies = [bad, bad]
    logged = []
    monkeypatch.setattr(modules.route, "log_event", lambda *args, **kwargs: logged.append((args, kwargs)))
    monkeypatch.setattr(harness.planner, "log_event", lambda *args, **kwargs: logged.append((args, kwargs)))

    events = _plan(runtime)

    assert [event["error"] for event in events if event.get("error")] == [
        "The conversation could not be interpreted. Please retry your request.",
    ]
    assert harness.runs.items == {}
    assert "PRIVATE_MODEL_TEXT" not in repr(logged)
    assert LATEST not in repr(logged)


def test_new_conversation_second_question_accepts_unused_null_clarification(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    _replace_history(harness, rows=[])
    first_question = "Find tide pools near Crescent City."
    harness.replies = [
        _compose_only_plan(), "First answer.",
        _resolution(relationship="new_topic", resolved_message="Find wineries open Wednesday.", message_ids=[],
                    clarification=None),
        _compose_only_plan(),
    ]
    first = _planned(runtime, message_text=first_question, turn_id="first-turn")
    _run(runtime, first)
    second = _planned(runtime, message_text="Find wineries open Wednesday.", turn_id="second-turn")
    stored = harness.runs.read_item(second["run_id"], "conversation-1")
    assert stored["request_resolution"]["clarification"] == ""
    assert {
        item["id"] for item in stored["conversation_context"]["messages"]
    } == {harness.runs.read_item(first["run_id"], "conversation-1")["user_message_id"],
          harness.runs.read_item(first["run_id"], "conversation-1")["assistant_message_id"]}


def test_history_and_conversation_read_failures_do_not_fallback_or_recreate(real_http_harness, monkeypatch):
    runtime = real_http_harness
    harness = runtime.harness
    harness.messages.fail_queries = True
    assert any(event.get("error") for event in _plan(runtime))
    assert harness.model_calls == []
    harness.messages.fail_queries = False
    harness.conversations.fail_reads = True
    assert any(event.get("error") for event in _plan(runtime, turn_id="conv-fail"))
    assert len(harness.conversations.items) == 1


def test_new_turns_after_planning_are_not_included_in_pending_run(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    _replace_history(harness)
    harness.replies = [_resolution(), _compose_only_plan(), ANSWER]
    plan = _planned(runtime)
    harness.messages.create_item(_conversation_row(message(
        "later", "user", "UNRELATED LATER MESSAGE", timestamp="2099-01-01T00:00:00+00:00",
    )))

    _run(runtime, plan)

    assert "UNRELATED LATER MESSAGE" not in json.dumps(harness.model_calls[-1])


def test_history_changed_before_or_during_execution_blocks_answer(real_http_harness, monkeypatch):
    runtime = real_http_harness
    harness = runtime.harness
    _replace_history(harness)
    harness.replies = [_new_topic(), _compose_only_plan()]
    plan = _planned(runtime)
    harness.messages.items[("conversation-1", "a2")]["metadata"] = {"masked": True}
    response = runtime.client.post("/api/v2/orchestration/run", json={
        "conversation_id": "conversation-1", "run_id": plan["run_id"],
    })
    assert response.status_code == 409

    harness.runs.items.clear()
    harness.model_calls.clear()
    _replace_history(harness)
    search_calls = []
    _install_search(
        monkeypatch, search_calls,
        after=lambda: harness.messages.items[("conversation-1", "a2")].update(metadata={"masked": True}),
    )
    harness.replies = [_resolution(), _search_then_answer_plan(), ANSWER]
    plan = _planned(runtime, turn_id="during")
    events = _run(runtime, plan)
    terminal = next(event for event in events if event.get("type") == "orchestration_done")
    assert terminal["failure"]["code"] == "context_unavailable"
    assert harness.runs.read_item(plan["run_id"], "conversation-1")["status"] == "failed"


def test_retry_after_plan_persistence_failure_does_not_duplicate_user_message(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    harness.runs.fail_writes = True
    harness.replies = [_new_topic(), _compose_only_plan()]
    assert any(event.get("error") for event in _plan(runtime))
    harness.runs.fail_writes = False
    harness.replies = [_new_topic(), _compose_only_plan()]

    _planned(runtime)

    assert sum(row.get("content") == LATEST for row in harness.messages.items.values()) == 1


def test_declined_clarification_and_successive_questions_do_not_create_phantom_runs(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    harness.replies = [json.dumps({
        "relationship": "clarification", "resolved_message": LATEST,
        "message_ids": [], "requires_retrieval": True, "clarification": "Which place?",
    })]
    first = next(event["elicitation"] for event in _plan(runtime) if event.get("elicitation"))
    harness.replies = [json.dumps({
        "relationship": "clarification", "resolved_message": LATEST,
        "message_ids": [], "requires_retrieval": True, "clarification": "Which day?",
    })]
    second_events = _plan(runtime, revision=1, elicitation=first, elicitation_response={
        "action": "accept", "content": {"clarification": "Seattle"},
    })
    second = next(event["elicitation"] for event in second_events if event.get("elicitation"))
    assert runtime.client.get("/api/v2/orchestration/runs", query_string={
        "conversation_id": "conversation-1",
    }).get_json()["runs"] == []
    harness.replies = [_new_topic("Find Seattle wineries open Wednesday."), _compose_only_plan()]
    plan = _planned(runtime, revision=2, elicitation=second, elicitation_response={
        "action": "decline", "content": {},
    })
    stored = harness.runs.read_item(plan["run_id"], "conversation-1")
    assert [answer["action"] for answer in stored["answered_questions"]] == ["accept", "decline"]


def test_pending_question_must_be_saved_before_it_is_shown(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    harness.runs.fail_writes = True
    harness.replies = [json.dumps({
        "relationship": "clarification", "resolved_message": LATEST,
        "message_ids": [], "requires_retrieval": False, "clarification": "Which place?",
    })]

    events = _plan(runtime)

    assert any(event.get("error") for event in events)
    assert not any(event.get("type") == "orchestration_elicitation" for event in events)


def test_clarification_uses_saved_schema_and_rejects_mismatches(real_http_harness, modules):
    runtime = real_http_harness
    harness = runtime.harness
    harness.replies = [json.dumps({
        "relationship": "clarification", "resolved_message": LATEST,
        "message_ids": [], "requires_retrieval": True, "clarification": "Which location do you mean?",
    })]
    elicitation = next(event["elicitation"] for event in _plan(runtime) if event.get("elicitation"))
    forged = json.loads(json.dumps(elicitation))
    forged["requested_schema"]["properties"]["clarification"]["type"] = "number"
    forged["message"] = "A forged question"
    harness.replies = [json.dumps({
        "relationship": "clarification", "resolved_message": LATEST,
        "message_ids": [], "requires_retrieval": True, "clarification": "Which day?",
    })]

    events = _plan(runtime, revision=1, elicitation=forged, elicitation_response={
        "action": "accept", "content": {"clarification": 123},
    })
    pending = modules.route.get_pending_turn_context("conversation-1", "owner", "turn-1")
    assert not any(event.get("error") for event in events)
    assert pending["answered_questions"][0]["question"] == "Which location do you mean?"
    response = runtime.client.post("/api/v2/orchestration/plan", json={
        "conversation_id": "conversation-1", "turn_id": "turn-1", "message": LATEST,
        "elicitation": {"turn_id": "another-turn"},
        "elicitation_response": {"action": "accept", "content": {}},
    })
    assert response.status_code == 400


def test_accepted_url_answer_reaches_planning_and_execution_allowlists(real_http_harness, monkeypatch, modules):
    runtime = real_http_harness
    harness = runtime.harness
    harness.replies = [json.dumps({
        "relationship": "clarification", "resolved_message": "Summarize the report.",
        "message_ids": [], "requires_retrieval": True, "clarification": "Which URL?",
    })]
    elicitation = next(event["elicitation"] for event in _plan(runtime, message_text="Summarize the report.") if event.get(
        "elicitation"
    ))
    observed = []
    original_request_context = modules.route._capability_request_context

    def capture_request_context(*args, **kwargs):
        observed.append(("plan", kwargs.get("allowed_user_urls")))
        return original_request_context(*args, **kwargs)

    monkeypatch.setattr(modules.route, "_capability_request_context", capture_request_context)
    original_run_context = modules.route.RunContext

    def capture_run_context(**kwargs):
        context = original_run_context(**kwargs)
        observed.append(("run", list(context.allowed_user_urls)))
        return context

    monkeypatch.setattr(modules.route, "RunContext", capture_run_context)
    harness.replies = [
        _resolution(resolved_message="Summarize https://example.com/report", message_ids=[]),
        _compose_only_plan(), ANSWER,
    ]
    plan = _planned(runtime, message_text="Summarize the report.", revision=1, elicitation=elicitation,
                    elicitation_response={"action": "accept", "content": {
                        "clarification": "https://example.com/report",
                    }})
    _run(runtime, plan)

    assert [value for _stage, value in observed].count(["https://example.com/report"]) >= 2


def test_short_requests_reach_planner_with_available_capabilities(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    harness.messages.items.clear()
    harness.settings["enable_web_search"] = True
    harness.replies = [_compose_only_plan()]

    plan = _planned(runtime, message_text="Hi!", turn_id="short-turn")

    assert [step["capability_id"] for step in plan["steps"]] == ["compose"]
    payload = json.loads(harness.model_calls[0]["messages"][1]["content"])
    assert "compose" in payload["capability_availability"]["available"]


def test_ledger_does_not_reintroduce_masked_turn_context(real_http_harness):
    runtime = real_http_harness
    harness = runtime.harness
    harness.replies = [_new_topic(), _compose_only_plan(), ANSWER]
    plan = _planned(runtime)
    _run(runtime, plan)
    record = harness.runs.items[("conversation-1", plan["run_id"])]
    record["plan_summary"]["intent_summary"] = "REDACTED TURN DETAIL"
    record["answered_questions"] = [{"question": "Hidden?", "answer": "REDACTED TURN DETAIL"}]
    harness.messages.items[("conversation-1", record["user_message_id"])]["metadata"]["masked"] = True
    harness.messages.items[("conversation-1", record["assistant_message_id"])]["metadata"]["masked"] = True
    harness.model_calls.clear()
    harness.replies = [_new_topic(), _compose_only_plan()]

    _planned(runtime, turn_id="next-turn")

    assert "REDACTED TURN DETAIL" not in json.dumps(harness.model_calls)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
