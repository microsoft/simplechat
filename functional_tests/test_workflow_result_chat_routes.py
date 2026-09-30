# test_workflow_result_chat_routes.py
"""
Functional test for the chat routes' workflow-result Follow up wiring.
Version: 0.261.213
Implemented in: 0.261.213

This test ensures that every chat entry point sends a request carrying a
workflow_result_context to the Follow up executor before saved analysis and
before any source, conversation or stream work, and that the streaming routes
refuse a disabled, conflicting or retried request before a conversation exists.
A fresh offline process then boots the real application and checks, through the
real JSON, SSE and history routes, that questions are answered only from the
selected run's stored result with the disclosure, that a later question keeps
the run's lineage, and that a changed result, a chat that isn't private,
another user or a disabled setting gets its closed reason with nothing saved and
no model call. Only storage, the model and the network are faked.
"""

import ast
import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(TESTS))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


TREE = ast.parse((APP / "route_backend_chats.py").read_text(encoding="utf-8"))
# Names other tests' exec'd route slices don't define; only a workflow-result request may reach them.
NEW_NAMES = {
    "FollowUpServices", "run_workflow_result_follow_up", "workflow_result_request_precheck",
    "execute_workflow_result_chat_request", "is_chat_workflow_results_enabled_for_user",
}
EXPECTED_SERVICES = {
    "messages": "cosmos_messages_container",
    "conversation_id": "getattr(g, 'conversation_id', None)",
    "load_conversation": "_load_or_create_analyze_conversation",
    "check_chat_content": "check_chat_content",
    "reject_chat_submission": "_reject_chat_submission",
    "attach_chat_check": "attach_chat_check",
    "initialize_response_tracking": "_initialize_assistant_response_tracking",
    "sanitize_history": "_sanitize_saved_analysis_history",
    "history_metadata": "_analysis_history_metadata",
    "build_history_segments": "build_conversation_history_segments",
    "persist_assistant": "_persist_screened_assistant",
    "set_initial_title": "_set_initial_conversation_title",
    "update_conversation": "update_analysis_conversation",
    "invalidate_conversation": "invalidate_conversation_cache_for_item",
    "gate": "is_chat_workflow_results_enabled_for_user",
    "cancel_errors": "(AgentExecutionCancelled,)",
    "unsupported_errors": "(SavedAnalysisFollowupUnsupported,)",
}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def function(name):
    found = [
        node for node in ast.walk(TREE)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    require(len(found) == 1, f"Expected exactly one {name}, found {len(found)}.")
    return found[0]


def first_line(scope, predicate, description):
    lines = sorted(node.lineno for node in ast.walk(scope) if predicate(node))
    require(lines, f"{description} was not found in {scope.name}.")
    return lines[0]


def call_to(name):
    return lambda node: isinstance(node, ast.Call) and name in (
        getattr(node.func, "id", None), getattr(node.func, "attr", None),
    )


def assignment_to(name):
    return lambda node: isinstance(node, ast.Assign) and any(
        getattr(target, "id", None) == name for target in node.targets
    )


def definition_of(name):
    return lambda node: isinstance(node, ast.FunctionDef) and node.name == name


def workflow_branch(node):
    return isinstance(node, ast.If) and "workflow_result_context" in ast.unparse(node.test)


def precheck_call(scope):
    branches = [
        node for node in ast.walk(scope)
        if workflow_branch(node) and any(call_to("workflow_result_request_precheck")(child) for child in ast.walk(node))
    ]
    require(len(branches) == 1, f"{scope.name} needs exactly one workflow-result precheck branch.")
    require(
        any(isinstance(child, ast.Return) for child in ast.walk(branches[0])),
        f"{scope.name}'s precheck doesn't return its refusal.",
    )
    return next(child for child in ast.walk(branches[0]) if call_to("workflow_result_request_precheck")(child))


def test_version_is_at_least_the_workflow_results_release():
    assert_app_version_at_least("0.261.213")


def test_the_chat_stream_refuses_a_workflow_result_request_before_any_other_work():
    stream = function("chat_stream_api")
    call = precheck_call(stream)
    roles = ast.unparse(call.args[2])
    later = {
        description: first_line(stream, predicate, description)
        for predicate, description in (
            (assignment_to("retry_user_message_id"), "The retry fields"),
            (call_to("_authorize_personal_conversation_access"), "The conversation check"),
            (call_to("_get_authorized_chat_scope_context"), "The scope check"),
            (call_to("check_chat_content"), "Input screening"),
            (assignment_to("finalized_conversation_id"), "Conversation creation"),
            (call_to("start_session"), "The stream session"),
        )
    }

    assert "roles" in roles
    assert [description for description, line in later.items() if line <= call.lineno] == []


@pytest.mark.parametrize("name", ["chat_document_action_stream_api", "chat_analyze_stream_api"])
def test_the_document_streams_refuse_before_a_conversation_or_stream_exists(name):
    route = function(name)
    call = precheck_call(route)
    roles = ast.unparse(call.args[2])
    creation = first_line(route, call_to("_load_or_create_analyze_conversation"), "Conversation creation")
    stream = first_line(route, call_to("start_session"), "The stream session")

    assert "roles" in roles
    assert call.lineno < creation and call.lineno < stream


@pytest.mark.parametrize(("name", "source_work"), [
    ("execute_document_action_chat_request", "selected_document_ids"),
    ("chat_api", "request_agent_info"),
])
def test_workflow_results_are_dispatched_before_saved_analysis_and_any_source_work(name, source_work):
    route = function(name)
    workflow = first_line(route, call_to("execute_workflow_result_chat_request"), "The workflow dispatch")
    analysis = first_line(route, call_to("execute_saved_analysis_chat_request"), "The analysis dispatch")
    sources = first_line(route, assignment_to(source_work), "The first source work")

    assert workflow < analysis and workflow < sources


def test_the_chat_stream_answers_workflow_results_before_saved_analysis_and_normal_chat():
    stream = function("chat_stream_api")
    workflow = first_line(stream, definition_of("generate_workflow_result_response"), "The workflow generator")
    analysis = first_line(stream, definition_of("generate_saved_analysis_response"), "The analysis generator")
    normal = first_line(stream, definition_of("generate"), "The normal generator")
    branch = next(
        node for node in ast.walk(stream)
        if workflow_branch(node) and any(definition_of("generate_workflow_result_response")(child) for child in node.body)
    )

    assert workflow < analysis < normal
    assert isinstance(branch.body[-1], ast.Return)
    assert "generate_workflow_result_response" in ast.unparse(branch.body[-1])


@pytest.mark.parametrize("name", ["chat_document_action_stream_api", "chat_analyze_stream_api"])
def test_no_analysis_message_id_is_reserved_for_a_workflow_result_request(name):
    route = function(name)
    assignment = next(node for node in ast.walk(route) if assignment_to("analysis_message_id")(node))

    assert isinstance(assignment.value, ast.IfExp)
    assert "data.get('workflow_result_context') is None" in ast.unparse(assignment.value.test)


def test_the_wrapper_supplies_every_required_service_from_the_route():
    from functions_workflow_result_followup import FollowUpServices

    wrapper = function("execute_workflow_result_chat_request")
    calls = [node for node in ast.walk(wrapper) if call_to("FollowUpServices")(node)]
    require(len(calls) == 1, "The wrapper builds its services once.")
    supplied = {keyword.arg: ast.unparse(keyword.value) for keyword in calls[0].keywords}
    fields = {field.name: field for field in dataclasses.fields(FollowUpServices)}
    required = {
        name for name, field in fields.items()
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
    }

    lambdas = {
        name: supplied.get(name, "")
        for name in ("invoke_reply", "authorize_analysis_context", "bind_conversation", "user_roles")
    }

    assert not calls[0].args and None not in supplied
    assert required <= set(supplied) and set(supplied) <= set(fields)
    assert {name: supplied.get(name) for name in EXPECTED_SERVICES} == EXPECTED_SERVICES
    assert "_invoke_saved_analysis_chat_reply(data, settings, user_id, conversation_id, messages, **options)" in (
        lambdas["invoke_reply"]
    )
    assert "load_saved_analysis(user_id, context)" in lambdas["authorize_analysis_context"]
    assert "setattr(g, 'conversation_id', conversation_id)" in lambdas["bind_conversation"]
    assert "roles" in lambdas["user_roles"]


def test_the_new_names_are_reached_only_on_workflow_result_paths():
    parents = {child: node for node in ast.walk(TREE) for child in ast.iter_child_nodes(node)}
    offenders = []
    for node in ast.walk(TREE):
        if not (isinstance(node, ast.Name) and node.id in NEW_NAMES):
            continue
        previous, current, guarded = node, parents.get(node), False
        while current is not None and not guarded:
            if isinstance(current, ast.FunctionDef) and current.name == "execute_workflow_result_chat_request":
                guarded = True
            elif workflow_branch(current) and any(previous is statement for statement in current.body):
                guarded = True
            previous, current = current, parents.get(current)
        if not guarded:
            offenders.append((node.id, node.lineno))

    assert offenders == []


def run_offline_scenarios():
    # Real application imports occur only after external I/O is isolated.
    from contextlib import ExitStack
    from copy import deepcopy
    import json
    import os
    import re
    import shutil
    import socket
    import time
    from types import SimpleNamespace
    from unittest.mock import patch
    from uuid import uuid4

    from azure.cosmos.exceptions import CosmosResourceNotFoundError
    from test_support.m365 import Query
    from test_support.offline_bootstrap import OfflineContainer, OfflineCosmos, OfflineDatabase

    class Container(OfflineContainer):
        """Partition-aware offline storage that answers the queries these routes issue."""

        def __init__(self, partition_field="id"):
            super().__init__()
            self.partition_field = partition_field

        def read_item(self, item, partition_key, **kwargs):
            saved = super().read_item(item, partition_key, **kwargs)
            if saved.get(self.partition_field) != partition_key:
                raise CosmosResourceNotFoundError(status_code=404)
            return saved

        def replace_item(self, item, body, **kwargs):
            self.read_item(item, body[self.partition_field])
            return super().replace_item(item, body, **kwargs)

        def query_items(self, query, parameters=None, partition_key=None, max_item_count=100, **kwargs):
            values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
            rows = deepcopy(list(self.items.values()))
            if partition_key is not None:
                rows = [row for row in rows if row.get(self.partition_field) == partition_key]
            for field, parameter in re.findall(r"c\.([A-Za-z_]\w*)\s*=\s*(@\w+)", query):
                if parameter in values:
                    rows = [row for row in rows if row.get(field) == values[parameter]]
            for field, value in re.findall(r"c\.([A-Za-z_]\w*)\s*=\s*'([^']*)'", query):
                rows = [row for row in rows if row.get(field) == value]
            for parameter, field in re.findall(r"ARRAY_CONTAINS\(\s*(@\w+)\s*,\s*c\.(\w+)\s*\)", query):
                rows = [row for row in rows if row.get(field) in values.get(parameter, [])]
            rows.sort(
                key=lambda row: (row.get("timestamp") or row.get("created_at") or "", row["id"]),
                reverse="DESC" in query,
            )
            if "COUNT(" in query:
                return [len(rows)]
            top = re.search(r"SELECT TOP (\d+)", query)
            if top:
                rows = rows[:int(top.group(1))]
            if "c.metadata.thread_info.thread_id as thread_id" in query:
                rows = [
                    {"thread_id": ((row.get("metadata") or {}).get("thread_info") or {}).get("thread_id")}
                    for row in rows
                ]
            return Query(rows, max_item_count or 100)

    class Database(OfflineDatabase):
        def create_container_if_not_exists(self, id, **kwargs):
            partition = kwargs.get("partition_key") or {"paths": ["/id"]}
            return self.containers.setdefault(id, Container(partition["paths"][0].lstrip("/")))

        get_container_client = create_container_if_not_exists

    class Cosmos(OfflineCosmos):
        def __init__(self, *args, **kwargs):
            self.database = Database()

    class Model:
        """The selected chat model; records exactly what the route sent it."""

        def __init__(self):
            self.requests = []
            self.reply = "The digest says markets rose."
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, *, model, messages, **kwargs):
            self.requests.append(deepcopy(messages))
            # Windows clocks tick about once a millisecond; the answer must sort after its question.
            time.sleep(0.003)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15), model="gpt-4o",
            )

    normal_chat_clients = []

    class NormalChatClient:
        def __init__(self, *args, **kwargs):
            normal_chat_clients.append(True)
            raise AssertionError("A workflow-result question reached the normal chat model.")

    state_dir = TESTS / f".workflow-result-chat-state-{uuid4().hex}"
    state_dir.mkdir()
    network_attempts = []
    original_connect = socket.socket.connect

    def no_network(connection, address):
        # asyncio's Windows selector builds a local wake-up socket pair.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(connection, address)
        network_attempts.append(address)
        raise AssertionError("The workflow result chat test attempted network access.")

    def no_http(*args, **kwargs):
        network_attempts.append("http")
        raise AssertionError("The workflow result chat test attempted an HTTP request.")

    try:
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {
                "SESSION_FILE_DIR": str(state_dir), "SIMPLECHAT_RUN_BACKGROUND_TASKS": "0",
                "DISABLE_FLASK_INSTRUMENTATION": "1", "TENANT_ID": "tenant", "CLIENT_ID": "client",
                "MICROSOFT_PROVIDER_AUTHENTICATION_SECRET": "offline-client-secret",
                "APPLICATIONINSIGHTS_CONNECTION_STRING": "",
            }))
            stack.enter_context(patch("azure.cosmos.CosmosClient", Cosmos))
            stack.enter_context(patch.object(socket.socket, "connect", no_network))
            stack.enter_context(patch("requests.sessions.Session.request", no_http))

            import app
            import config
            import functions_workflow_result_reader as reader
            import route_backend_chats as chats
            from collaboration_models import PERSONAL_MULTI_USER_CHAT_TYPE
            from functions_chat_stream_events import USER_MESSAGE_PERSISTED_EVENT_TYPE
            from functions_settings import update_settings
            from functions_workflow_result_followup import FENCE_END, FENCE_START, RESULT_SYSTEM_MESSAGE
            from test_support.workflow_result_chat import OTHER_USER, RUN_ID, USER, WORKFLOW_ID, RunFixture, two_text_tasks

            settings = {
                "enable_chat_workflow_results": True, "allow_user_workflows": True,
                "require_member_of_workflow_user": False,
                "enable_semantic_kernel": False, "per_user_semantic_kernel": False,
                "enable_content_safety": False, "enable_thoughts": False,
                "enable_key_vault_secret_storage": False, "conversation_history_limit": 20,
                "azure_openai_gpt_authentication_type": "api_key",
                "azure_openai_gpt_endpoint": "https://model.invalid",
                "azure_openai_gpt_api_version": "2024-10-21",
                "azure_openai_gpt_key": "offline-model-key",
                "gpt_model": {"selected": [{"deploymentName": "gpt-4o"}]},
            }
            app.configure_application_cache(
                settings, None, redis_client_factory=app.functions_redis_client.create_redis_client,
            )
            require(update_settings(settings), "Offline settings were not saved through the real settings owner.")
            app.initialize_application(force=True)

            model = Model()
            fixture = RunFixture()
            two_text_tasks(fixture)
            stack.enter_context(patch.object(
                chats, "_resolve_model_workflow_client", lambda binding, current: (model, "gpt-4o", "aoai"),
            ))
            stack.enter_context(patch.object(chats, "AzureOpenAI", NormalChatClient))
            stack.enter_context(patch.object(reader, "_default_containers", lambda: fixture.containers))
            stack.enter_context(patch.object(reader, "load_workflow_task_result", fixture.store.load))
            stack.enter_context(patch.object(reader, "read_workflow_task_result_page", fixture.store.read_page))

            for user_id in (USER, OTHER_USER):
                config.cosmos_user_settings_container.upsert_item({
                    "id": user_id, "user_id": user_id, "settings": {"profileImage": None, "enable_thoughts": False},
                })
            web = app.app
            web.config.update(TESTING=True, WTF_CSRF_ENABLED=False)

            def signed_in(user_id, name):
                client = web.test_client()
                with client.session_transaction() as session:
                    session["user"] = {
                        "oid": user_id, "tid": "tenant", "roles": ["User"],
                        "preferred_username": f"{name.lower()}@example.test", "name": name,
                    }
                    session["token_cache"] = "{}"
                return client

            owner, stranger = signed_in(USER, "Owner"), signed_in(OTHER_USER, "Stranger")
            context = {
                "workflow_id": WORKFLOW_ID, "run_id": RUN_ID,
                "result_sha256": fixture.read()["descriptor"]["result_sha256"],
            }
            question = "What did the digest find?"
            disclosure = (
                "_This answer uses the stored result of the Weekly digest run of Mon Jan 5, 2026, 9:02 AM EST. "
                "The workflow was not re-run._"
            )
            public_keys = {
                "version", "workflow_id", "run_id", "workflow_name", "status", "completed_at",
                "result_sha256", "available",
            }

            def ask(client, route="/api/chat", **fields):
                # Every other source is requested too; none of them may be used.
                body = {
                    "message": question, "workflow_result_context": context, "time_zone": "America/New_York",
                    "hybrid_search": True, "web_search_enabled": True, "url_access_enabled": True,
                    "selected_document_ids": ["doc-elsewhere"], "doc_scope": "all", **fields,
                }
                return client.post(route, json=body)

            def events(response):
                blocks = response.get_data(as_text=True).split("\n\n")
                return [event for event in map(chats._extract_sse_event_payload, blocks) if isinstance(event, dict)]

            def messages_of(conversation_id):
                return sorted(
                    (deepcopy(row) for row in config.cosmos_messages_container.items.values()
                     if row.get("conversation_id") == conversation_id),
                    key=lambda row: row["timestamp"],
                )

            def counts():
                return (
                    len(config.cosmos_conversations_container.items), len(config.cosmos_messages_container.items),
                    len(model.requests),
                )

            def no_store_reference(text, where):
                require("result_ref" not in text, f"{where} carried a result reference.")
                require(not any(digest in text for digest in fixture.store.contents), f"{where} carried a store digest.")

            # A new chat over JSON: the answer comes from the stored result only, with the disclosure.
            response = ask(owner)
            payload = response.get_json()
            require(response.status_code == 200, f"JSON Follow up failed: {response.status_code} {payload}")
            conversation_id = payload["conversation_id"]
            require(payload["reply"] == f"{model.reply}\n\n{disclosure}", f"Unexpected reply: {payload['reply']!r}")
            no_store_reference(response.get_data(as_text=True), "The JSON answer")
            conversation = config.cosmos_conversations_container.read_item(conversation_id, conversation_id)
            require(conversation["user_id"] == USER, "The new chat isn't the requester's.")
            require(conversation["title"] == chats.derive_conversation_title_from_message(question), "Not titled.")
            require(
                conversation["has_unread_assistant_response"] is True
                and conversation["last_unread_assistant_message_id"] == payload["message_id"],
                "The answer wasn't marked unread.",
            )
            saved = messages_of(conversation_id)
            require([row["role"] for row in saved] == ["user", "assistant"], f"Unexpected history: {saved}")
            require(saved[0]["metadata"]["workflow_result_context"] == context, "The question lost its context.")
            answer = saved[1]
            require(answer["id"] == payload["message_id"] and answer["content"] == payload["reply"], "Answer mismatch.")
            require(set(answer["metadata"]["workflow_result"]) == public_keys, "The descriptor isn't the public one.")
            require(
                answer["metadata"]["workflow_result"]["result_sha256"] == context["result_sha256"]
                and answer["metadata"]["workflow_result"]["available"] is True,
                "The descriptor isn't bound to the selected result.",
            )
            require(answer["metadata"]["workflow_result_contexts"] == [context], "The answer lost its lineage.")
            require(
                answer["augmented"] is False and answer["hybrid_citations"] == []
                and answer["web_search_citations"] == [] and answer["agent_citations"] == [],
                "Another source reached the answer.",
            )
            require(payload["metadata"]["workflow_result"] == answer["metadata"]["workflow_result"], "No descriptor sent.")
            require(len(model.requests) == 1, f"Expected one model request, got {len(model.requests)}.")
            sent = model.requests[0]
            require([item["role"] for item in sent] == ["system", "user", "user"], f"Unexpected prompt: {sent}")
            require(sent[0]["content"] == RESULT_SYSTEM_MESSAGE, "The fixed system message wasn't used.")
            fence = sent[1]["content"]
            require(fence.startswith(FENCE_START) and fence.endswith(FENCE_END), "The run output isn't fenced.")
            require("The digest: markets rose." in fence and "Collected three headlines." in fence, "Output missing.")
            require("PREVIEW-TEXT" not in json.dumps(sent), "A preview was used instead of the stored result.")
            require(sent[2] == {"role": "user", "content": question}, "The question isn't last.")

            # The next question in that chat keeps the same result and passes its lineage on once.
            model.reply = "It also collected three headlines."
            follow = ask(owner, conversation_id=conversation_id, message="And the headlines?")
            require(follow.status_code == 200, f"The second question failed: {follow.get_json()}")
            second = model.requests[-1]
            require(
                [item["role"] for item in second] == ["system", "user", "user", "assistant", "user"],
                f"The earlier turn wasn't in the history: {second}",
            )
            require("The digest says markets rose." in second[3]["content"], "The earlier answer is missing.")
            require(messages_of(conversation_id)[-1]["metadata"]["workflow_result_contexts"] == [context], "Lineage.")

            # The streamed route answers the same way and reports the saved question first.
            model.reply = "The digest says markets rose."
            streamed = ask(owner, "/api/chat/stream", conversation_id=conversation_id)
            require(streamed.status_code == 200 and streamed.mimetype == "text/event-stream", "No stream.")
            stream_events = events(streamed)
            no_store_reference(streamed.get_data(as_text=True), "The streamed answer")
            persisted = [event for event in stream_events if event.get("type") == USER_MESSAGE_PERSISTED_EVENT_TYPE]
            final = [event for event in stream_events if event.get("done")]
            require(len(persisted) == 1 and len(final) == 1, f"Unexpected events: {stream_events}")
            require(stream_events.index(persisted[0]) < stream_events.index(final[0]), "Events out of order.")
            require(final[0]["full_content"] == f"{model.reply}\n\n{disclosure}", "The stream lost the disclosure.")
            require(final[0]["metadata"]["workflow_result_contexts"] == [context], "The stream lost the lineage.")
            require(not any(event.get("error") for event in stream_events), f"Stream error: {stream_events}")
            require(len(messages_of(conversation_id)) == 6, "The streamed turn wasn't saved.")

            # A new streamed chat is created as the requester's own private chat.
            fresh = events(ask(owner, "/api/chat/stream"))
            fresh_final = next(event for event in fresh if event.get("done"))
            fresh_id = fresh_final["conversation_id"]
            fresh_conversation = config.cosmos_conversations_container.read_item(fresh_id, fresh_id)
            require(fresh_id != conversation_id and fresh_conversation["user_id"] == USER, "Wrong new chat.")
            require(fresh_final["conversation_title"] == fresh_conversation["title"] != "New Conversation", "Title.")
            require([row["role"] for row in messages_of(fresh_id)] == ["user", "assistant"], "New chat not saved.")

            # The document-action entry point answers from the same executor.
            analyzed = ask(owner, "/api/chat/analyze", conversation_id=fresh_id)
            require(analyzed.status_code == 200, f"The analyze route refused: {analyzed.get_json()}")
            require(analyzed.get_json()["reply"].endswith(disclosure), "The analyze route answered differently.")

            # History shows the answers while the result is readable.
            def reloaded(chat_id):
                loaded = owner.get("/api/get_messages", query_string={"conversation_id": chat_id})
                require(loaded.status_code == 200, f"History failed: {loaded.status_code} {loaded.get_json()}")
                return loaded

            readable = {chat_id: reloaded(chat_id).get_json()["messages"] for chat_id in (conversation_id, fresh_id)}
            shown = [item for item in readable[conversation_id] if item.get("role") == "assistant"]
            require(len(shown) == 3 and all(item["content"].endswith(disclosure) for item in shown), "History.")
            require(
                [item["role"] for item in readable[fresh_id]] == ["user", "assistant"] * 2,
                f"Unexpected new-chat history: {readable[fresh_id]}",
            )

            def require_withheld(chat_id, why):
                loaded = reloaded(chat_id)
                body = loaded.get_data(as_text=True)
                items, earlier = loaded.get_json()["messages"], readable[chat_id]
                require(
                    [(item["id"], item["role"]) for item in items] == [(item["id"], item["role"]) for item in earlier],
                    f"{why}: the history changed shape.",
                )
                for item, before_item in zip(items, earlier):
                    if item["role"] == "assistant":
                        require(
                            item["content"] == reader.WORKFLOW_RESULT_UNAVAILABLE_MESSAGE
                            and item["metadata"]["workflow_result"] == {
                                "version": reader.WORKFLOW_RESULT_VERSION, "available": False,
                            }
                            and "workflow_result_contexts" not in item["metadata"],
                            f"{why}: an answer wasn't withheld: {item}",
                        )
                    else:
                        require(
                            item["content"] == before_item["content"]
                            and "workflow_result_context" not in item["metadata"],
                            f"{why}: a question lost its text or kept its context: {item}",
                        )
                for text in ("markets rose", "headlines.", "Weekly digest", WORKFLOW_ID, RUN_ID, context["result_sha256"]):
                    require(text not in body, f"{why}: the history still carried {text!r}.")

            def search_hits(term):
                found = owner.post("/api/search_conversations", json={"search_term": term})
                require(found.status_code == 200, f"Search failed: {found.status_code} {found.get_data(as_text=True)[:300]}")
                return {
                    item["conversation"]["id"]: len(item["messages"]) for item in found.get_json()["results"]
                    if item["messages"]
                }

            require(
                search_hits("markets rose") == {conversation_id: 2, fresh_id: 2},
                f"Search didn't find the readable answers: {search_hits('markets rose')}",
            )

            # The stream routes refuse a disabled, conflicting, retried or malformed request up front.
            before = counts()
            conflict = {"conversation_id": "conv-analysis", "message_id": "msg-analysis", "result_sha256": "d" * 64}
            for route in ("/api/chat/stream", "/api/chat/document-action/stream", "/api/chat/analyze/stream"):
                for fields, status, code in (
                    ({"analysis_result_context": conflict}, 400, "workflow_result_context_conflict"),
                    ({"retry_user_message_id": "msg-1"}, 400, "workflow_result_retry_unsupported"),
                    ({"edited_user_message_id": "msg-1"}, 400, "workflow_result_retry_unsupported"),
                    ({"workflow_result_context": {"workflow_id": WORKFLOW_ID}}, 400, "workflow_result_invalid_context"),
                ):
                    refused = ask(owner, route, **fields)
                    require(
                        refused.status_code == status and refused.get_json().get("code") == code,
                        f"{route} {fields}: {refused.status_code} {refused.get_data(as_text=True)[:300]}",
                    )
            require(update_settings({"enable_chat_workflow_results": False}), "The setting wasn't turned off.")
            for route in (
                "/api/chat", "/api/chat/stream", "/api/chat/document-action/stream", "/api/chat/analyze/stream",
            ):
                refused = ask(owner, route)
                require(
                    refused.status_code == 403 and refused.get_json().get("code") == "workflow_results_disabled",
                    f"{route} with the setting off: {refused.status_code} {refused.get_data(as_text=True)[:300]}",
                )
                require("Weekly digest" not in refused.get_data(as_text=True), "A refusal named the workflow.")
            require(update_settings({"enable_chat_workflow_results": True}), "The setting wasn't turned back on.")
            require(counts() == before, "A refused request created a chat, saved a message or called the model.")

            # Shared, collaborative and converted chats never read a workflow result.
            for shared_id, fields in (
                ("conv-converted-1", {"converted_to_collaboration_at": "2026-01-06T09:00:00"}),
                ("conv-collaborative-1", {"chat_type": PERSONAL_MULTI_USER_CHAT_TYPE}),
            ):
                config.cosmos_conversations_container.upsert_item({
                    "id": shared_id, "user_id": USER, "title": "Shared chat", "chat_type": "new",
                    "last_updated": "2026-01-06T09:00:00", **fields,
                })
                requests_before = len(model.requests)
                refused = ask(owner, conversation_id=shared_id)
                require(
                    refused.status_code == 403 and refused.get_json().get("code") == "workflow_result_private_only",
                    f"{shared_id}: {refused.status_code} {refused.get_json()}",
                )
                streamed_refusal = ask(owner, "/api/chat/stream", conversation_id=shared_id)
                if streamed_refusal.mimetype == "text/event-stream":
                    error = next(event for event in events(streamed_refusal) if event.get("error"))
                    require(error.get("error_code") == "workflow_result_private_only", f"{shared_id}: {error}")
                else:
                    require(streamed_refusal.status_code in (403, 404), f"{shared_id}: {streamed_refusal.status_code}")
                require(messages_of(shared_id) == [] and len(model.requests) == requests_before, "A shared chat read it.")

            # Another user can't read the run, from a new chat or from the owner's chat.
            requests_before = len(model.requests)
            foreign = ask(stranger)
            require(
                foreign.status_code == 404 and foreign.get_json().get("code") == "workflow_result_not_found",
                f"A stranger got {foreign.status_code} {foreign.get_json()}",
            )
            require("Weekly digest" not in foreign.get_data(as_text=True), "The refusal named the workflow.")
            stranger_chats = [
                row["id"] for row in config.cosmos_conversations_container.items.values() if row.get("user_id") == OTHER_USER
            ]
            require(all(messages_of(chat_id) == [] for chat_id in stranger_chats), "A stranger's question was kept.")
            foreign_stream = ask(stranger, "/api/chat/stream", conversation_id=conversation_id)
            require(foreign_stream.status_code in (403, 404), f"The owner's chat opened: {foreign_stream.status_code}")
            require(len(model.requests) == requests_before, "A stranger's question reached the model.")

            # After resume-failed changes the result, the old selection answers nothing.
            fixture.add_task("task-summary-72", {"reply": "A revised digest."}, order=2, label="Write the digest")
            before = counts()
            changed = ask(owner, "/api/chat/stream", conversation_id=conversation_id)
            changed_events = events(changed)
            error = next((event for event in changed_events if event.get("error")), None)
            require(
                error is not None and error.get("error_code") == "workflow_result_changed"
                and error.get("status_code") == 409 and error.get("warning_type") == "workflow_result_unavailable",
                f"The changed result wasn't refused: {changed_events}",
            )
            require("A revised digest." not in changed.get_data(as_text=True), "The new result was used.")
            changed_json = ask(owner, conversation_id=conversation_id)
            require(
                changed_json.status_code == 409 and changed_json.get_json().get("code") == "workflow_result_changed",
                f"JSON: {changed_json.status_code} {changed_json.get_json()}",
            )
            require(counts() == before, "A changed result saved a message or reached the model.")

            # Every earlier answer is withheld on reload and in search while the result differs.
            stored = {chat_id: messages_of(chat_id) for chat_id in (conversation_id, fresh_id)}
            for chat_id in (conversation_id, fresh_id):
                require_withheld(chat_id, "After the result changed")
            require(search_hits("markets rose") == {}, "Search still showed an answer from a changed result.")
            require(
                {chat_id: messages_of(chat_id) for chat_id in stored} == stored,
                "Withholding an answer changed what was stored.",
            )

            # Restoring the original result shows the same answers again.
            fixture.add_task("task-summary-72", {"reply": "The digest: markets rose."}, order=2, label="Write the digest")
            for chat_id in (conversation_id, fresh_id):
                require(reloaded(chat_id).get_json()["messages"] == readable[chat_id], "The answers didn't return.")
            require(search_hits("markets rose") == {conversation_id: 2, fresh_id: 2}, "Search didn't recover.")

            # Deleting the run withholds them again, and a stranger never sees the owner's history.
            fixture.containers["runs"].documents.clear()
            for chat_id in (conversation_id, fresh_id):
                require_withheld(chat_id, "After the run was deleted")
            require(search_hits("markets rose") == {}, "Search still showed an answer from a deleted run.")
            foreign_history = stranger.get("/api/get_messages", query_string={"conversation_id": conversation_id})
            require(foreign_history.status_code == 403, f"A stranger read the history: {foreign_history.status_code}")

            require(not normal_chat_clients, "The normal chat model was used.")
            require(not network_attempts, f"The routes attempted network access: {network_attempts}")
            print(SCENARIOS_FINISHED)
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


SCENARIOS_FINISHED = "WORKFLOW_RESULT_CHAT_ROUTE_SCENARIOS_FINISHED"


def test_the_real_routes_answer_only_from_the_selected_stored_result():
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--offline"],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )
    output = result.stdout[-3000:] + result.stderr[-6000:]

    assert result.returncode == 0, output
    assert SCENARIOS_FINISHED in result.stdout.splitlines(), output


if __name__ == "__main__":
    if "--offline" in sys.argv:
        run_offline_scenarios()
    else:
        raise SystemExit(pytest.main([__file__, "-q"]))
