# test_m365_chat_action_cards.py
"""
Functional integration tests for Microsoft 365 chat action-card transport.
Version: 0.261.038
Implemented in: 0.261.038
Date: 2026-09-19

Fresh-process tests execute real typed Calendar/Email tools, Semantic Kernel,
Flask chat/stream/history routes, and the authoritative card resolver. Only
external storage, model, Graph, and token-acquisition I/O is replaced.
"""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def run_offline_scenarios(*, lifecycle_only=False, emit_ui_transcript=False):
    # Real application imports occur only after external I/O is isolated.
    import builtins
    from contextlib import ExitStack
    from copy import deepcopy
    from datetime import datetime, timezone
    import json
    import os
    import re
    import shutil
    import socket
    from threading import Event
    from types import SimpleNamespace
    from unittest.mock import patch
    from urllib.parse import urlsplit
    from uuid import uuid4

    from azure.cosmos.exceptions import CosmosResourceNotFoundError
    from pydantic import Field
    from semantic_kernel import Kernel
    from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
    from semantic_kernel.contents import AuthorRole, ChatMessageContent, FunctionCallContent, StreamingChatMessageContent
    from test_support.m365 import Query
    from test_support.offline_bootstrap import OfflineContainer, OfflineCosmos, OfflineDatabase

    class Container(OfflineContainer):
        def __init__(self, partition_field="id"):
            super().__init__()
            self.partition_field = partition_field
            self.unavailable = False
            self.unavailable_queries = False
            self.fail_queries_on_create = False
            self.reads = []

        def create_item(self, body, **kwargs):
            saved = super().create_item(body=body, **kwargs)
            if self.fail_queries_on_create and body.get("type") == "msgraph_pending_action":
                self.unavailable_queries = True
            return saved

        def read_item(self, item, partition_key, **kwargs):
            self.reads.append((item, partition_key))
            if self.unavailable:
                raise RuntimeError("private storage detail must not reach a browser")
            saved = super().read_item(item, partition_key, **kwargs)
            if saved.get(self.partition_field) != partition_key:
                raise CosmosResourceNotFoundError(status_code=404)
            return saved

        def replace_item(self, item, body, **kwargs):
            self.read_item(item, body[self.partition_field])
            return super().replace_item(item, body, **kwargs)

        def query_items(self, query, parameters=None, partition_key=None, max_item_count=100, **kwargs):
            if self.unavailable or self.unavailable_queries:
                raise RuntimeError("private storage detail must not reach a browser")
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
            rows.sort(key=lambda row: (row.get("timestamp") or row.get("created_at") or "", row["id"]), reverse="DESC" in query)
            if "COUNT(" in query:
                return [len(rows)]
            return Query(rows, max_item_count or 100)

    class Database(OfflineDatabase):
        def create_container_if_not_exists(self, id, **kwargs):
            partition = kwargs.get("partition_key") or {"paths": ["/id"]}
            field = partition["paths"][0].lstrip("/")
            return self.containers.setdefault(id, Container(field))

        get_container_client = create_container_if_not_exists

    class Cosmos(OfflineCosmos):
        def __init__(self, *args, **kwargs):
            self.database = Database()

    class GraphResponse:
        def __init__(self, payload):
            self.payload = payload
            self.status_code = 200
            self.headers = {"Content-Type": "application/json"}

        def json(self):
            return deepcopy(self.payload)

        def iter_content(self, chunk_size):
            yield json.dumps(self.payload).encode("utf-8")

        def close(self):
            return None

    graph_calls = []

    def graph_request(client, method, url, **kwargs):
        path = urlsplit(url).path
        graph_calls.append((method, path))
        if method == "GET" and path.endswith("/me"):
            return GraphResponse({"id": "owner", "mail": "owner@example.test"})
        if method == "POST" and path.endswith("/me/messages"):
            return GraphResponse({
                "id": f"draft-{len(graph_calls)}", "changeKey": "draft-version",
                "isDraft": True, "webLink": "https://outlook.office.com/mail/draft",
            })
        raise AssertionError(f"Unexpected Graph operation: {method} {path}")

    class Msal:
        def get_accounts(self):
            return [{
                "home_account_id": "owner.tenant", "local_account_id": "owner", "realm": "tenant",
                "environment": "login.microsoftonline.com",
            }]

        def acquire_token_silent_with_error(self, scopes, account):
            return {"access_token": "offline-delegated-token", "id_token_claims": {"oid": "owner", "tid": "tenant"}}

    class AzureClient:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="Offline response"))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                model="gpt-4o",
            )

    pending_container = None

    class Model(OpenAIChatCompletion):
        mode: str = "normal"
        requests: list = Field(default_factory=list)
        tool_results: list = Field(default_factory=list)
        release: object = None
        waiting: object = None

        async def _inner_get_chat_message_contents(self, chat_history, settings):
            self.requests.append(self.mode)
            results = [
                item.result for message in chat_history.messages if message.role == AuthorRole.TOOL
                for item in message.items if hasattr(item, "result")
            ]
            if self.mode == "prose":
                return [ChatMessageContent(
                    role=AuthorRole.ASSISTANT,
                    content='Your meeting is ready. {"pending_action":{"id":"invented"}}',
                )]
            if results:
                self.tool_results.extend(results)
                references = action_cards.get_request_pending_action_references()
                for reference in references:
                    action_cards.record_pending_action_reference(reference)
                if self.waiting is not None:
                    self.waiting.set()
                    if not self.release.wait(timeout=15):
                        raise AssertionError("The test did not release the offline model.")
                if self.mode == "error":
                    raise RuntimeError("offline model failed after creating the pending action")
                if self.mode == "projection_error":
                    pending_container.unavailable = True
                return [ChatMessageContent(role=AuthorRole.ASSISTANT, content="Both actions are waiting for review.")]
            return [ChatMessageContent(role=AuthorRole.ASSISTANT, items=[
                FunctionCallContent(
                    id="calendar-call", name="Calendar-create_calendar_invite",
                    arguments=json.dumps({
                        "subject": "Review <meeting>", "start_datetime": "2026-09-20T12:00:00",
                        "end_datetime": "2026-09-20T12:30:00", "timezone": "UTC",
                        "attendee_emails": "recipient@example.test", "body_content": "Calendar review content",
                    }),
                ),
                FunctionCallContent(
                    id="email-call", name="Email-send_mail",
                    arguments=json.dumps({
                        "to_recipients": "recipient@example.test", "subject": "Review <mail>",
                        "body_content": "Mail review content", "bcc_recipients": "private@example.test",
                    }),
                ),
            ])]

        async def _inner_get_streaming_chat_message_contents(self, chat_history, settings, function_invoke_attempt=0):
            messages = await self._inner_get_chat_message_contents(chat_history, settings)
            for message in messages:
                yield [StreamingChatMessageContent(
                    role=message.role, content=message.content, items=message.items, choice_index=0,
                )]

    state_dir = ROOT / "functional_tests" / f".m365-card-test-state-{uuid4().hex}"
    state_dir.mkdir()
    network_attempts = []
    original_connect = socket.socket.connect

    def no_network(connection, address):
        # asyncio's Windows selector builds a local wake-up socket pair.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(connection, address)
        network_attempts.append(address)
        raise AssertionError("Chat action-card regression attempted network access.")

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
            stack.enter_context(patch("requests.sessions.Session.request", graph_request))

            import app
            import config
            import functions_m365_action_cards as action_cards
            import functions_m365_agent_continuation as continuation
            import functions_m365_connections as connections
            import functions_msgraph_pending_actions as pending
            import route_backend_chats as chats
            from agent_logging_chat_completion import LoggingChatCompletionAgent
            from functions_m365_operations import normalize_m365_action_config
            from functions_settings import update_settings
            from semantic_kernel_plugins.m365_calendar_plugin import M365CalendarPlugin
            from semantic_kernel_plugins.m365_email_plugin import M365EmailPlugin
            from test_m365_agent_continuation import Memory

            require(callable(getattr(pending, "get_chat_pending_action_cards", None)), "Parent card resolver contract is not implemented.")
            pending_container = config.cosmos_msgraph_pending_actions_container
            settings = {
                "enable_semantic_kernel": True, "per_user_semantic_kernel": False,
                "enable_multi_agent_orchestration": False, "enable_fact_memory_plugin": False,
                "enable_content_safety": False, "enable_thoughts": False,
                "enable_key_vault_secret_storage": False,
                "azure_openai_gpt_authentication_type": "api_key",
                "azure_openai_gpt_endpoint": "https://model.invalid",
                "azure_openai_gpt_api_version": "2024-10-21",
                "azure_openai_gpt_key": "offline-model-key",
                "gpt_model": {"selected": [{"deploymentName": "gpt-4o"}]},
                "conversation_history_limit": 20,
            }
            app.configure_application_cache(
                settings, None, redis_client_factory=app.functions_redis_client.create_redis_client,
            )
            settings_saved = update_settings(settings)
            require(settings_saved, "Offline settings were not saved through the real settings owner.")
            stack.enter_context(patch.object(chats, "AzureOpenAI", AzureClient))
            stack.enter_context(patch.object(
                connections.get_m365_connection_service(), "msal_factory", lambda cache, configuration: Msal(),
            ))
            app.initialize_application(force=True)

            for user_id in ("owner", "other"):
                config.cosmos_user_settings_container.upsert_item({
                    "id": user_id, "user_id": user_id,
                    "settings": {"profileImage": None, "enable_agents": True, "enable_thoughts": False},
                })
            manifests = [
                normalize_m365_action_config("m365_calendar", {
                    "id": "calendar-action", "user_id": "owner", "name": "Calendar", "type": "m365_calendar",
                    "m365_capabilities": {"create_calendar_invite": True},
                    "msgraph_calendar_send_mode": "draft_manual",
                }),
                normalize_m365_action_config("m365_email", {
                    "id": "email-action", "user_id": "owner", "name": "Email", "type": "m365_email",
                    "m365_capabilities": {"send_mail": True},
                    "msgraph_mail_send_mode": "draft_manual",
                }),
            ]
            for manifest in manifests:
                config.cosmos_personal_actions_container.upsert_item(manifest)
            agent_config = {
                "id": "card-agent", "user_id": "owner", "name": "card_agent",
                "instructions": "Prepare outgoing actions for review.",
                "actions_to_load": [manifest["id"] for manifest in manifests],
            }
            config.cosmos_personal_agents_container.upsert_item(agent_config)
            kernel = Kernel()
            kernel.add_plugin(M365CalendarPlugin(manifests[0]).get_kernel_plugin("Calendar"))
            kernel.add_plugin(M365EmailPlugin(manifests[1]).get_kernel_plugin("Email"))
            model = Model(ai_model_id="gpt-4o", api_key="offline")
            agent = LoggingChatCompletionAgent(
                id="card-agent", name="card_agent", kernel=kernel, service=model,
                instructions=agent_config["instructions"], deployment_name="gpt-4o",
            )
            stack.enter_context(patch.object(builtins, "kernel", kernel, create=True))
            stack.enter_context(patch.object(builtins, "kernel_agents", {"card_agent": agent}, create=True))
            continuation.configure_m365_agent_continuation(
                memory_resolver=lambda context: (Memory(), object()),
                jobs_factory=lambda: config.cosmos_m365_execution_runs_container,
                model_context_setter=lambda *args, **kwargs: None,
            )
            web = app.app
            web.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
            client = web.test_client()
            with client.session_transaction() as session:
                session["user"] = {
                    "oid": "owner", "tid": "tenant", "roles": ["User"],
                    "preferred_username": "owner@example.test", "name": "Test Owner",
                }
                session["token_cache"] = "{}"

            def prepare(name):
                model.mode = "normal"
                model.release = model.waiting = None
                pending_container.unavailable = False
                pending_container.unavailable_queries = False
                pending_container.fail_queries_on_create = False
                now = datetime.now(timezone.utc).isoformat()
                config.cosmos_conversations_container.upsert_item({
                    "id": name, "user_id": "owner", "title": "Action-card regression",
                    "created_at": now, "last_updated": now, "chat_type": "personal_single_user",
                })
                return {
                    "conversation_id": name, "message": "Prepare the meeting and email.",
                    "agent_info": {"id": "card-agent", "name": "card_agent", "is_global": False},
                    "hybrid_search": False,
                }

            def records(conversation_id):
                return [
                    deepcopy(row) for row in pending_container.items.values()
                    if row.get("conversation_id") == conversation_id
                ]

            def check_cards(payload, conversation_id, expected=2):
                cards = payload.get("m365_pending_actions", [])
                require(
                    len(cards) == expected,
                    f"Expected {expected} cards, got {len(cards)}. "
                    f"Error: {payload.get('error')}; tool results: {model.tool_results[-2:]}",
                )
                require(len({card["id"] for card in cards}) == expected, "Duplicate pending IDs reached the browser.")
                for card in cards:
                    require(card["conversation_id"] == conversation_id, "Cross-conversation action disclosure.")
                    require(card["type"] == "msgraph_pending_action", "The card lost its typed contract.")
                    require("graph_payload" not in card and "user_id" not in card, "Raw delivery material reached the browser.")
                    require("offline-delegated-token" not in json.dumps(card), "A card exposed a credential.")
                return cards

            if emit_ui_transcript:
                response = client.post("/api/chat/stream", json=prepare("visible-conversation"))
                events = [
                    chats._extract_sse_event_payload(block)
                    for block in response.get_data(as_text=True).split("\n\n")
                ]
                events = [event for event in events if event is not None]
                final = next(event for event in reversed(events) if event.get("done"))
                projected = check_cards(final, "visible-conversation")
                require(len(records("visible-conversation")) == 2, "Typed tools did not save both review actions.")
                require(not any(path.endswith(("/send", "/sendMail", "/events")) for _, path in graph_calls), "Preparation sent an outgoing action.")
                require(not network_attempts, "The UI transcript contacted an external service.")
                print("M365_UI_TRANSCRIPT=" + json.dumps({"events": events, "cards": projected}))
                return

            if lifecycle_only:
                # Reuse the real-app bootstrap; the lifecycle suite supplies only
                # records and assertions, not replacement routes or dispatchers.
                from test_conversation_fork import FakeBlobService
                from test_m365_conversation_lifecycle import run_lifecycle_scenarios

                stack.enter_context(patch.dict(config.CLIENTS, {
                    "storage_account_office_docs_client": FakeBlobService(),
                }))
                run_lifecycle_scenarios(SimpleNamespace(
                    web=web, client=client, config=config, prepare=prepare,
                    pending=pending_container, records=records, graph_calls=graph_calls,
                    model=model, chats=chats,
                ))
                require(not network_attempts, "Lifecycle cleanup attempted external network access.")
                return

            response = client.post("/api/chat", json=prepare("normal"))
            payload = response.get_json()
            require(response.status_code == 200, f"Non-streamed chat failed: {response.status_code} {payload}")
            require(payload.get("thoughts_enabled") is False, "The regression did not disable thought output.")
            cards = check_cards(payload, "normal")
            require(all(card["status"] == "pending" and card["can_approve"] for card in cards), "Manual actions were classified as delivered.")
            saved = config.cosmos_messages_container.read_item(payload["message_id"], "normal")
            require(set(saved["metadata"]["m365_pending_action_ids"]) == {card["id"] for card in cards}, "Assistant persistence lost references.")
            require("m365_pending_actions" not in saved, "A stale executable DTO was persisted instead of IDs.")
            require(len(records("normal")) == 2, "The model or transport repeated a write.")

            config.cosmos_messages_container.upsert_item({
                "id": "legacy", "conversation_id": "normal", "role": "assistant", "content": "Legacy result",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": {"existing": "preserved"},
                "m365_pending_actions": [{"id": "untrusted-snapshot", "graph_payload": {"secret": True}}],
            })
            config.cosmos_messages_container.upsert_item({
                "id": "foreign-reference", "conversation_id": "normal", "role": "assistant", "content": "Forged binding",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": {"m365_pending_action_ids": ["foreign-action"]},
            })
            pending_container.upsert_item({
                "id": "foreign-action", "user_id": "other", "conversation_id": "foreign-conversation",
                "type": "msgraph_pending_action", "status": "pending", "summary": {"subject": "Private foreign data"},
            })
            changed = pending_container.read_item(cards[0]["id"], "owner")
            changed["status"] = "cancelled"
            pending_container.upsert_item(changed)
            history = client.get("/api/get_messages", query_string={"conversation_id": "normal"})
            require(history.status_code == 200, f"History projection failed: {history.get_json()}")
            answer = next(message for message in history.get_json()["messages"] if message["id"] == saved["id"])
            refreshed = check_cards(answer, "normal")
            require(next(card for card in refreshed if card["id"] == changed["id"])["status"] == "cancelled", "History trusted an obsolete card snapshot.")
            legacy = next(message for message in history.get_json()["messages"] if message["id"] == "legacy")
            foreign = next(message for message in history.get_json()["messages"] if message["id"] == "foreign-reference")
            require("m365_pending_actions" not in legacy and legacy["metadata"] == {"existing": "preserved"}, "Legacy prose/snapshots were assigned executable cards.")
            require(foreign["m365_pending_actions"] == [], "A stored ID bypassed conversation/record authorization.")
            require("Private foreign data" not in history.get_data(as_text=True), "A foreign pending record leaked through history.")

            request_payload = prepare("stream")
            model.release, model.waiting = Event(), Event()
            response = client.post("/api/chat/stream", json=request_payload, buffered=False)
            events = []
            replay = None
            try:
                for chunk in response.response:
                    event = chats._extract_sse_event_payload(chunk.decode() if isinstance(chunk, bytes) else chunk)
                    if event is not None:
                        events.append(event)
                    if sum(event.get("type") == "m365_pending_action" for event in events) == 2:
                        break
                live = [event for event in events if event.get("type") == "m365_pending_action"]
                require(len(live) == 2 and not model.release.is_set(), "Cards waited for model completion or thought output.")
                require(all(event.get("request_id") and event.get("conversation_id") == "stream" for event in live), "Live event binding was lost.")
                require(all("user_id" not in event for event in live), "An event serialized its owner reference.")
                changed = pending_container.read_item(live[0]["pending_action"]["id"], "owner")
                changed["status"] = "cancelled"
                pending_container.upsert_item(changed)
                replay = client.get("/api/chat/stream/reattach/stream", buffered=False)
                require(replay.status_code == 200, "A running card stream could not reconnect.")
                replayed = []
                for chunk in replay.response:
                    event = chats._extract_sse_event_payload(chunk.decode() if isinstance(chunk, bytes) else chunk)
                    if event and event.get("type") == "m365_pending_action":
                        replayed.append(event)
                    if len(replayed) == 2:
                        break
                require([event["pending_action"]["id"] for event in replayed] == [event["pending_action"]["id"] for event in live], "Replay lost or regenerated card IDs.")
                require(replayed[0]["pending_action"]["status"] == "cancelled", "Reconnect trusted a cached delivery snapshot.")
                replay.close()
                replay = None
                pending_container.unavailable_queries = True
                unavailable_replay = client.get("/api/chat/stream/reattach/stream", buffered=False)
                try:
                    failure_events = [
                        chats._extract_sse_event_payload(chunk.decode() if isinstance(chunk, bytes) else chunk)
                        for chunk in unavailable_replay.response
                    ]
                    replay_failure = next(event for event in failure_events if event and event.get("error"))
                    require(replay_failure.get("m365_pending_actions_error"), "Replay hid an action-card storage failure.")
                    require("m365_pending_actions" not in replay_failure and "pending_action" not in replay_failure, "Replay exposed a stale card after authorization/storage failed.")
                finally:
                    unavailable_replay.close()
                    pending_container.unavailable_queries = False
            finally:
                if replay is not None:
                    replay.close()
                model.release.set()
                for chunk in response.response:
                    event = chats._extract_sse_event_payload(chunk.decode() if isinstance(chunk, bytes) else chunk)
                    if event is not None:
                        events.append(event)
                response.close()
            final = next(event for event in reversed(events) if event.get("done"))
            require(final.get("thoughts_enabled") is False, "Streaming card delivery depended on enabled thoughts.")
            streamed_cards = check_cards(final, "stream")
            require({card["id"] for card in streamed_cards} == {event["pending_action"]["id"] for event in live}, "Final SSE used different cards.")
            require(len(records("stream")) == 2, "Reconnect repeated a tool call.")

            request_payload = prepare("cancelled-stream")
            model.release, model.waiting = Event(), Event()
            response = client.post("/api/chat/stream", json=request_payload, buffered=False)
            events = []
            try:
                for chunk in response.response:
                    event = chats._extract_sse_event_payload(chunk.decode() if isinstance(chunk, bytes) else chunk)
                    if event is not None:
                        events.append(event)
                    if sum(event.get("type") == "m365_pending_action" for event in events) == 2:
                        break
                cancel = client.post("/api/chat/stream/cancel/cancelled-stream", json={"reason": "user_requested"})
                require(cancel.status_code == 200, f"Stream cancellation failed: {cancel.get_json()}")
            finally:
                model.release.set()
                for chunk in response.response:
                    event = chats._extract_sse_event_payload(chunk.decode() if isinstance(chunk, bytes) else chunk)
                    if event is not None:
                        events.append(event)
                response.close()
            cancelled = next(event for event in reversed(events) if event.get("cancelled") or event.get("canceled"))
            cancelled_cards = check_cards(cancelled, "cancelled-stream")
            require(all(card["status"] == "pending" for card in cancelled_cards), "Stopping the model changed delivery state.")
            require(len(records("cancelled-stream")) == 2, "Stream cancellation repeated or discarded pending writes.")

            request_payload = prepare("model-error")
            model.mode = "error"
            response = client.post("/api/chat/stream", json=request_payload)
            events = [
                chats._extract_sse_event_payload(block) for block in response.get_data(as_text=True).split("\n\n")
            ]
            events = [event for event in events if event is not None]
            failed = next(event for event in reversed(events) if event.get("error"))
            recovered_cards = check_cards(failed, "model-error")
            require(len(records("model-error")) == 2, "A model failure replayed the producing tools.")
            require(all(card["status"] == "pending" for card in recovered_cards), "A failed model changed pending delivery state.")

            request_payload = prepare("callback-error")
            pending_container.fail_queries_on_create = True
            response = client.post("/api/chat/stream", json=request_payload)
            events = [
                chats._extract_sse_event_payload(block) for block in response.get_data(as_text=True).split("\n\n")
            ]
            events = [event for event in events if event is not None]
            failed = next(event for event in reversed(events) if event.get("m365_pending_actions_error"))
            require("m365_pending_actions" not in failed, "A failed creation callback became an empty inbox.")
            require(len(records("callback-error")) == 2, "A live projection failure repeated or lost the producing tool calls.")
            pending_container.unavailable_queries = False
            callback_history = client.get("/api/get_messages", query_string={"conversation_id": "callback-error"})
            require(callback_history.status_code == 200, "Cards were unrecoverable after the callback storage outage ended.")
            callback_answer = next(message for message in callback_history.get_json()["messages"] if message.get("role") == "assistant")
            check_cards(callback_answer, "callback-error")

            request_payload = prepare("projection-error")
            model.mode = "projection_error"
            response = client.post("/api/chat", json=request_payload)
            failure = response.get_json()
            require(response.status_code == 503, f"Card storage failure was hidden: {failure}")
            require(failure.get("m365_pending_actions_error", {}).get("error") == "m365_pending_actions_unavailable", "No actionable card-projection error.")
            require("private storage detail" not in json.dumps(failure), "Storage exception text was exposed.")
            require("m365_pending_actions" not in failure, "Unavailable storage became an empty inbox.")
            history = client.get("/api/get_messages", query_string={"conversation_id": "projection-error"})
            require(history.status_code == 503, "History concealed pending-action storage failure.")
            pending_container.unavailable = False

            request_payload = prepare("prose")
            model.mode = "prose"
            response = client.post("/api/chat", json=request_payload)
            prose = response.get_json()
            require(response.status_code == 200, f"Ordinary assistant prose failed: {prose}")
            require(not prose.get("m365_pending_actions") and records("prose") == [], "Assistant text synthesized an executable card.")

            other = web.test_client()
            with other.session_transaction() as session:
                session["user"] = {"oid": "other", "tid": "tenant", "roles": ["User"]}
            before_reads = len(pending_container.reads)
            denied = other.get("/api/get_messages", query_string={"conversation_id": "normal"})
            require(denied.status_code == 403, "A stranger could project another user's history.")
            require(len(pending_container.reads) == before_reads, "Card hydration ran before conversation authorization.")

            require(not any(path.endswith("/send") or path.endswith("/sendMail") or path.endswith("/events") for method, path in graph_calls), "Review or history initiated Graph delivery.")
            require(not network_attempts, "The application swallowed a blocked external network attempt.")
    finally:
        shutil.rmtree(state_dir)


def test_real_typed_tools_reach_json_live_sse_replay_and_authorized_history():
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--offline"],
        cwd=ROOT, capture_output=True, text=True, timeout=150,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-6000:]


if __name__ == "__main__":
    if "--offline" in sys.argv:
        sys.path.insert(0, str(APP))
        sys.path.insert(0, str(TESTS))
        run_offline_scenarios(
            lifecycle_only="--lifecycle" in sys.argv, emit_ui_transcript="--ui-transcript" in sys.argv,
        )
    else:
        sys.exit(pytest.main([str(Path(__file__).resolve())]))
