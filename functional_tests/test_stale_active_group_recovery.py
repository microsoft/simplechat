# test_stale_active_group_recovery.py
"""Real-owner regressions for stale active-group chat recovery.

Version: 0.261.371
Implemented in: 0.261.371

Fresh normal/optimized processes import the application with network blocked.
Settings, group authorization and the Semantic Kernel entrypoint remain real.
Cosmos responses use the installed SDK, with conditional writes and partitions.
"""

import pytest

from test_orchestration_result_imports import run_probe


LOADER_PROBE = r'''
from contextlib import ExitStack
from unittest.mock import patch
import sys

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports
from test_support.m365 import CosmosContainer


def check(condition, message):
    if not condition:
        raise AssertionError(message)


with offline_app_imports():
    import app as web
    import functions_group as groups
    import functions_settings as preferences
    import semantic_kernel_loader as loader
    from flask import session
    from semantic_kernel import Kernel

    settings_store = CosmosContainer("id")
    group_store = CosmosContainer("id")
    with ExitStack() as stack:
        stack.enter_context(patch.object(preferences, "cosmos_user_settings_container", settings_store))
        stack.enter_context(patch.object(groups, "cosmos_groups_container", group_store))
        for state in ("removed", "deleted"):
            settings_store.upsert_item({
                "id": "member", "settings": {
                    "activeGroupOid": "former", "enable_agents": True,
                    "selected_agent": {"name": "personal", "is_group": False},
                    "showTutorialButtons": True, "desktopNotificationsEnabled": True,
                    "profileImage": None,
                },
            })
            if state == "removed":
                group_store.upsert_item({
                    "id": "former", "owner": {"id": "other"}, "users": [],
                })
            else:
                group_store.items.clear()
            with web.app.test_request_context("/api/chat/stream"):
                session["user"] = {"oid": "member", "roles": ["User"]}
                kernel = Kernel()
                result = loader.load_user_semantic_kernel(
                    kernel, {"allow_user_agents": True}, "member", None,
                )
                check(result == (kernel, None), "Loader did not finish its no-agent return contract.")
                stored = settings_store.read_item("member", "member")
                check(stored["settings"]["activeGroupOid"] is None, "Stale group was not persisted as null.")
            stored["settings"].update(
                activeGroupOid="former",
                selected_agent={"name": "private", "is_group": True, "group_id": "former"},
            )
            settings_store.upsert_item(stored)
            with web.app.test_request_context("/api/chat/stream"), patch.object(
                loader, "get_group_agent", side_effect=AssertionError("Unauthorized group agent read"),
            ):
                session["user"] = {"oid": "member", "roles": ["User"]}
                kernel = Kernel()
                result = loader.load_user_semantic_kernel(
                    kernel, {"allow_user_agents": True, "allow_group_agents": True}, "member", None,
                )
                check(result == (kernel, None), "Unavailable group agent was not refused.")
    print("PASS: removed and deleted groups do not abort Semantic Kernel loading")
'''

PERSISTENCE_PROBE = r'''
from contextlib import ExitStack
from copy import deepcopy
from unittest.mock import Mock, patch
import sys

sys.path[:0] = sys.argv[1:3]
from azure.cosmos.exceptions import CosmosHttpResponseError
from azure.cosmos._cosmos_responses import CosmosDict
from test_support.offline_bootstrap import offline_app_imports
from test_support.m365 import CosmosContainer


def check(condition, message):
    if not condition:
        raise AssertionError(message)


with offline_app_imports():
    import app as web
    import functions_group as groups
    import functions_settings as preferences
    from flask import session

    settings_store = CosmosContainer("id")
    group_store = CosmosContainer("id")
    baseline = {
        "id": "member", "display_name": "Member", "custom": {"unchanged": True},
        "settings": {
            "activeGroupOid": "former", "enable_agents": False,
            "selected_agent": None, "agents": [], "plugins": [],
            "layoutPreference": "split", "showTutorialButtons": True,
            "desktopNotificationsEnabled": True, "profileImage": None,
        },
    }
    def seed(group_id="former"):
        document = deepcopy(baseline)
        document["settings"]["activeGroupOid"] = group_id
        settings_store.upsert_item(document)

    def resolve():
        with web.app.test_request_context("/chats"):
            session["user"] = {"oid": "member", "roles": ["User"]}
            value = groups.get_optional_active_group("member")
            snapshot = preferences.get_user_settings("member")
            return value, snapshot

    with ExitStack() as stack:
        stack.enter_context(patch.object(preferences, "cosmos_user_settings_container", settings_store))
        stack.enter_context(patch.object(groups, "cosmos_groups_container", group_store))
        logs = stack.enter_context(patch.object(preferences, "log_event"))
        cache_delete = stack.enter_context(patch.object(preferences, "_delete_user_ui_settings_cache"))

        seed()
        value, snapshot = resolve()
        stored = settings_store.read_item("member", "member")
        check(isinstance(stored, CosmosDict), "SDK-shaped storage seam was bypassed.")
        check(value is None and stored["settings"]["activeGroupOid"] is None, "Deleted group not cleared.")
        for key, expected in baseline["settings"].items():
            if key != "activeGroupOid":
                check(stored["settings"][key] == expected, "Repair changed unrelated setting: " + key)
        check(stored["custom"] == baseline["custom"], "Repair changed unrelated profile data.")
        check(snapshot["settings"]["activeGroupOid"] is None, "Request cache retained revoked scope.")
        check(snapshot["_etag"] == stored["_etag"], "Request cache retained the pre-repair ETag.")
        check(cache_delete.call_count > 0, "UI cache was not invalidated.")
        revision = settings_store.revision
        resolve()
        check(settings_store.revision == revision, "Repeat no-group request wrote again.")

        for empty in (None, ""):
            seed(empty)
            revision = settings_store.revision
            value, _ = resolve()
            check(value is None and settings_store.revision == revision, "Empty selection caused a write.")

        for role in ("Owner", "Admin", "DocumentManager", "User"):
            group = {"id": "former", "owner": {"id": "other"}, "users": []}
            if role == "Owner":
                group["owner"]["id"] = "member"
            elif role == "Admin":
                group["admins"] = ["member"]
            elif role == "DocumentManager":
                group["documentManagers"] = ["member"]
            else:
                group["users"] = [{"userId": "member"}]
            group_store.upsert_item(group)
            seed()
            revision = settings_store.revision
            value, _ = resolve()
            check(value == "former" and settings_store.revision == revision, "Valid role was cleared: " + role)

        group_store.upsert_item({"id": "former", "owner": {"id": "other"}, "users": []})
        group_store.upsert_item({"id": "remaining", "owner": {"id": "member"}, "users": []})
        seed()
        value, _ = resolve()
        check(value is None, "Recovery auto-selected a remaining group.")
        with web.app.test_request_context("/api/group_documents"):
            session["user"] = {"oid": "member", "roles": ["User"]}
            try:
                groups.assert_group_role("member", "former", allowed_roles=("Owner", "Admin", "DocumentManager", "User"))
            except PermissionError:
                pass
            else:
                raise AssertionError("Revoked group access was allowed.")
            try:
                groups.require_active_group("member")
            except ValueError:
                pass
            else:
                raise AssertionError("Strict required-group operation allowed no group.")

        seed()
        with patch.object(group_store, "read_item", side_effect=CosmosHttpResponseError(status_code=503)):
            try:
                resolve()
            except CosmosHttpResponseError:
                pass
            else:
                raise AssertionError("Indeterminate membership lookup was silently accepted.")
        check(settings_store.read_item("member", "member")["settings"]["activeGroupOid"] == "former",
              "Lookup failure erased a preference.")

        original_replace = settings_store.replace_item
        def select_concurrently(item, body, **kwargs):
            current = settings_store.read_item("member", "member")
            current["settings"].update(activeGroupOid="remaining", layoutPreference="new-layout")
            settings_store.upsert_item(current)
            return original_replace(item, body, **kwargs)
        seed()
        with patch.object(settings_store, "replace_item", side_effect=select_concurrently) as writes:
            resolve()
            check(writes.call_count == 1, "Recovery kept writing after a concurrent selection.")
        current = settings_store.read_item("member", "member")["settings"]
        check(current["activeGroupOid"] == "remaining" and current["layoutPreference"] == "new-layout",
              "Repair overwrote a newer preference.")

        for status in (412, 503):
            seed()
            with patch.object(settings_store, "replace_item", side_effect=CosmosHttpResponseError(status_code=status)) as writes:
                value, snapshot = resolve()
            check(value is None and snapshot["settings"]["activeGroupOid"] is None,
                  "Failed repair left a revoked preference effective in this request.")
            check(writes.call_count == (3 if status == 412 else 1), "Repair retry was unbounded.")
            current = settings_store.read_item("member", "member")["settings"]
            check(current["activeGroupOid"] == "former", "Failed write unexpectedly changed storage.")
            check(logs.call_count > 0, "Repair failure was not logged.")
            resolve()
            check(settings_store.read_item("member", "member")["settings"]["activeGroupOid"] is None,
                  "A later request did not retry the repair.")

        seed()
        with web.app.test_request_context("/chats"):
            session["user"] = {"oid": "intruder", "roles": ["User"]}
            try:
                groups.get_optional_active_group("member")
            except PermissionError:
                pass
            else:
                raise AssertionError("Recovery bypassed user-settings ownership.")
        check(settings_store.read_item("member", "member")["settings"]["activeGroupOid"] == "former",
              "Unauthorized caller changed another user's preference.")

        seed()
        original_read = settings_store.read_item
        reads = []
        def fail_repair_read(item, partition_key):
            reads.append(item)
            if len(reads) == 2:
                raise CosmosHttpResponseError(status_code=503)
            return original_read(item, partition_key)
        with patch.object(settings_store, "read_item", side_effect=fail_repair_read):
            value, snapshot = resolve()
        check(value is None and snapshot["settings"]["activeGroupOid"] is None,
              "Repair read failure broke confirmed-stale recovery.")
        check(original_read("member", "member")["settings"]["activeGroupOid"] == "former",
              "Repair read failure changed storage.")

        seed()
        settings_store.items[("member", "member")].pop("_etag")
        with patch.object(settings_store, "replace_item", wraps=original_replace) as writes:
            value, snapshot = resolve()
        check(value is None and snapshot["settings"]["activeGroupOid"] is None,
              "Missing ETag did not retain safe effective state.")
        check(writes.call_count == 0, "Missing ETag caused an unconditional write.")
    print("PASS: SDK-shaped conditional recovery, roles, caches, races and failures")
'''

CHAT_PROBE = r'''
from contextlib import ExitStack
from copy import deepcopy
import base64
import json
import os
import sys
from unittest.mock import patch

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports
from test_support.m365 import CosmosContainer


def check(condition, message):
    if not condition:
        raise AssertionError(message)


with patch.dict(os.environ, {"TENANT_ID": "fixture-tenant"}), offline_app_imports() as environment:
    import app as web
    import app_settings_cache
    import config
    import functions_authentication as authentication
    import functions_settings as preferences
    import route_backend_chats as chats
    import route_backend_v2 as v2
    import route_frontend_chats as classic
    import semantic_kernel_loader as loader
    from openai.resources.chat.completions import Completions
    from openai.types.chat import ChatCompletion, ChatCompletionChunk
    from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
    from semantic_kernel.contents import ChatMessageContent, StreamingChatMessageContent, FinishReason

    # Bootstrap configures cache accessors once; install the synthetic service
    # settings afterward so the first request cannot replace the test binding.
    with web.app.app_context():
        web.initialize_application()

    settings = {
        **preferences.get_settings(), "enable_group_workspaces": True,
        "enable_user_workspace": True, "enable_semantic_kernel": True,
        "per_user_semantic_kernel": True, "allow_user_agents": True,
        "allow_group_agents": True, "merge_global_semantic_kernel_with_workspace": True,
        "enable_user_agreement": False, "enable_idle_timeout": False,
        "enable_content_safety": False, "enable_content_screening": False,
        "enable_multi_model_endpoints": False, "enable_gpt_apim": False,
        "enable_default_embedding_model_plugin": False,
        "enable_fact_memory_plugin": False, "enable_tabular_processing": False,
        "enable_chat_orchestration": False, "enable_key_vault_secret_storage": False,
        "gpt_model": {"selected": [{"deploymentName": "test-model", "modelName": "gpt-4o"}]},
        "azure_openai_gpt_endpoint": "https://model.example.invalid",
        "azure_openai_gpt_api_version": "2024-10-21",
        "azure_openai_gpt_key": "private-model-key",
        "azure_openai_gpt_authentication_type": "key",
        "azure_openai_gpt_deployment": "test-model",
    }
    target = {
        "id": "personal-agent", "name": "personal", "display_name": "Personal assistant",
        "user_id": "member", "agent_type": "local", "is_global": False,
        "instructions": "Answer the user.", "actions_to_load": [], "is_enabled": True,
    }
    global_target = {**target, "id": "global-agent", "name": "global", "is_global": True}
    global_target.pop("user_id")
    group_target = {
        **target, "id": "group-agent", "name": "group", "is_group": True, "group_id": "remaining",
    }
    group_target.pop("user_id")
    config.cosmos_group_agents_container.upsert_item(group_target)
    store = CosmosContainer("id")
    def seed(selected=None, enabled=True, member=False):
        store.upsert_item({
            "id": "member", "display_name": "Member",
            "settings": {
                "activeGroupOid": "former", "enable_agents": enabled,
                "selected_agent": deepcopy(selected), "agents": [], "plugins": [],
                "showTutorialButtons": True, "desktopNotificationsEnabled": True,
                "profileImage": None,
            },
        })
        config.cosmos_groups_container.upsert_item({
            "id": "former", "name": "Former group", "owner": {"id": "other"},
            "users": [{"userId": "member"}] if member else [],
        })

    calls = []
    answer = "Chat still works without a group."
    def complete(*args, **kwargs):
        calls.append("model")
        if kwargs.get("stream"):
            return iter([
                ChatCompletionChunk(id="reply", created=0, model="gpt-4o", object="chat.completion.chunk",
                    choices=[{"index": 0, "delta": {"content": answer}, "finish_reason": None}]),
                ChatCompletionChunk(id="reply", created=0, model="gpt-4o", object="chat.completion.chunk",
                    choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}]),
            ])
        return ChatCompletion(id="reply", created=0, model="gpt-4o", object="chat.completion",
            choices=[{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
            usage={"prompt_tokens": 5, "completion_tokens": 8, "total_tokens": 13})

    async def agent_reply(service, history, execution_settings):
        calls.append("agent")
        return [ChatMessageContent(role="assistant", content=answer)]

    async def agent_stream(service, history, execution_settings, function_invoke_attempt=0):
        calls.append("agent")
        yield [StreamingChatMessageContent(role="assistant", choice_index=0, content=answer,
                                          finish_reason=FinishReason.STOP)]

    with ExitStack() as stack:
        for owner, name, value in (
            (preferences, "cosmos_user_settings_container", store),
            (preferences, "get_settings", lambda: settings),
            (app_settings_cache, "get_settings_cache", lambda *args, **kwargs: settings),
            (web, "get_request_settings", lambda: settings),
            (chats, "get_settings", lambda: settings),
            (classic, "get_settings", lambda: settings),
            (v2, "get_settings", lambda: settings),
            (authentication, "get_user_profile_image", lambda: None),
        ):
            stack.enter_context(patch.object(owner, name, value))
        stack.enter_context(patch.object(config.cosmos_personal_agents_container, "query_items",
                                        side_effect=lambda **kwargs: [deepcopy(target)]))
        stack.enter_context(patch.object(config.cosmos_global_agents_container, "query_items",
                                        side_effect=lambda **kwargs: [deepcopy(global_target)]))
        stack.enter_context(patch.object(config.cosmos_group_agents_container, "query_items",
            side_effect=lambda **kwargs: [deepcopy(group_target)]
            if kwargs.get("partition_key") == "remaining" else []))
        stack.enter_context(patch.object(config.cosmos_groups_container, "query_items",
            side_effect=lambda **kwargs: [
                deepcopy(row) for row in config.cosmos_groups_container.items.values()
                if any(user["userId"] == "member" for user in row.get("users", []))
            ]))
        stack.enter_context(patch.object(Completions, "create", side_effect=complete))
        stack.enter_context(patch.object(AzureChatCompletion, "_inner_get_chat_message_contents", agent_reply))
        stack.enter_context(patch.object(AzureChatCompletion, "_inner_get_streaming_chat_message_contents", agent_stream))
        # The offline loop was created before blocking external sockets.
        stack.enter_context(patch.object(chats.asyncio, "run", side_effect=environment.loop.run_until_complete))
        stack.enter_context(patch.object(chats.asyncio, "get_event_loop", return_value=environment.loop))
        web.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        client = web.app.test_client()
        with client.session_transaction() as state:
            state["user"] = {"oid": "member", "roles": ["User"], "name": "Member"}

        if "--bridge" in sys.argv:
            seed(enabled=False)
            print("BRIDGE:" + json.dumps({"ready": True}), flush=True)
            for line in sys.stdin:
                command = json.loads(line)
                if command.get("seed"):
                    seed(enabled=False, member=command.get("member", False))
                    print("BRIDGE:" + json.dumps({"seeded": True}), flush=True)
                    continue
                if command.get("inspect"):
                    value = store.read_item("member", "member")["settings"]["activeGroupOid"]
                    print("BRIDGE:" + json.dumps({"active_group": value, "calls": calls}), flush=True)
                    continue
                response = client.open(command["path"], method=command.get("method", "GET"),
                                       json=command.get("json"))
                print("BRIDGE:" + json.dumps({
                    "status": response.status_code,
                    "body": base64.b64encode(response.get_data()).decode("ascii"),
                    "content_type": response.content_type,
                }), flush=True)
        else:
            for path in ("/chats", "/api/v2/bootstrap", "/api/v2/scope"):
                seed()
                response = client.get(path)
                check(response.status_code == 200, path + ": " + response.get_data(as_text=True)[-1200:])
                body = response.get_data(as_text=True)
                check("private-model-key" not in body, "Settings secret reached bootstrap.")
                if path != "/chats":
                    check(response.get_json()["scope"]["active_group_id"] is None, "V2 retained a stale badge.")
                check(store.read_item("member", "member")["settings"]["activeGroupOid"] is None,
                      path + " did not repair storage.")

            for mode in ("model", "disabled", "personal", "global", "group"):
                if mode == "group":
                    config.cosmos_groups_container.upsert_item({
                        "id": "remaining", "name": "Remaining group",
                        "owner": {"id": "member"}, "users": [{"userId": "member"}],
                    })
                for path in ("/api/chat", "/api/chat/stream"):
                    selected = {"personal": target, "global": global_target, "group": group_target}.get(mode)
                    seed(selected, enabled=mode != "disabled")
                    created = client.post("/api/create_conversation", json={})
                    check(created.status_code == 200, "Fixture conversation creation failed.")
                    body = {
                        "message": "Hello", "model_deployment": "test-model",
                        "conversation_id": created.get_json()["conversation_id"],
                    }
                    if selected:
                        body["agent_info"] = selected
                    before = len(calls)
                    response = client.post(path, json=body)
                    text = response.get_data(as_text=True)
                    check(response.status_code == 200 and answer in text, mode + path + ": " + text[-2000:])
                    check(len(calls) > before, "Chat did not invoke the mocked external model.")
                    check(calls[-1] == ("agent" if selected else "model"),
                          mode + path + ": chat silently replaced its selected agent.")
                    check(store.read_item("member", "member")["settings"]["activeGroupOid"] is None,
                          mode + path + " did not persist repair.")
            print("PASS: real legacy/V2 bootstrap, model-only and agent chat transports")
'''


@pytest.mark.parametrize("optimized", [False, True])
def test_stale_group_does_not_abort_real_semantic_kernel(optimized):
    run_probe(LOADER_PROBE, (), optimized)


@pytest.mark.parametrize("optimized", [False, True])
def test_stale_group_repair_preserves_settings_and_authorization(optimized):
    run_probe(PERSISTENCE_PROBE, (), optimized)


@pytest.mark.parametrize("optimized", [False, True])
def test_stale_group_recovers_in_real_pages_and_chat_transports(optimized):
    run_probe(CHAT_PROBE, (), optimized)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
