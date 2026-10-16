# test_action_credentials_bootstrap.py
"""Fresh-process application bootstrap and actual chat SDK mapping ownership.

Version: 0.261.341
Implemented in: 0.261.333
Runtime catalog reference regression added in: 0.261.341

Normal/optimized Python imports real modules in both orders with network blocked.
The initialized web app owns private state; backup/transfer inventories exclude it.
"""

import ast
from pathlib import Path

import pytest

from test_orchestration_result_imports import run_probe


PROBE = r'''
import sys
import tempfile
from pathlib import Path
Path("artifacts").mkdir(exist_ok=True)
tempfile.tempdir = str(Path("artifacts").resolve())
sys.path[:0] = sys.argv[1:3]
from azure.cosmos._cosmos_responses import CosmosDict
from test_support.offline_bootstrap import offline_app_imports

def check(value, message):
    if not value:
        raise AssertionError(message)

with offline_app_imports() as environment:
    if sys.argv[3].startswith("early"):
        import action_credential_contracts
        import functions_action_credential_state as state
        if sys.argv[3] == "early-continuation":
            import functions_action_credential_continuation as continuation
            import functions_action_credentials as credentials
        else:
            import functions_action_credentials as credentials
            import functions_action_credential_continuation as continuation
        check("config" not in sys.modules, "Pure credential discovery bootstrapped Azure.")
        for getter in (credentials.credential_services, continuation.continuation_services):
            try:
                getter()
            except action_credential_contracts.ActionCredentialError as error:
                check(error.code == "credential_runtime_unavailable", "Unexpected uninitialized runtime failure.")
            else:
                raise AssertionError("Uninitialized credential runtime silently supplied authority.")
    import app as web
    import config
    import route_backend_chats as chats
    import functions_action_credential_state as state
    import functions_data_management as data
    import functions_authentication as authentication
    authentication.get_user_profile_image = lambda: None
    check(state.is_configured(), "Application bootstrap did not configure private state.")
    import functions_action_credentials as credentials
    import functions_action_credential_continuation as continuation
    check(callable(credentials.credential_services().authorize_conversation), "Web authorization callbacks are missing.")
    check(callable(continuation.continuation_services().authorize_source), "Web retained-source authorization is missing.")
    private = state.create("owner", {
        "id": "credential-bootstrap", "record_type": "credential_checkpoint",
        "conversation_id": "credential-chat", "value": {},
    })
    sdk = config.cosmos_action_credential_state_container.read_item("credential-bootstrap", "owner")
    check(type(sdk) is CosmosDict, "Credential point storage must use the real SDK wrapper.")
    check(type(private) is dict and private["_etag"] == sdk["_etag"], "Credential owner lost normalized ETag.")
    check("cosmos_action_credential_state_container" not in repr(data.DATA_MANAGEMENT_COSMOS_ARTIFACTS),
          "Backups must never restore pending credential interactions or bindings.")
    check("cosmos_action_credential_state_container" not in repr(data.DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS),
          "An identity transfer must not transfer credential interaction authority.")
    restore_artifact = data._get_restore_cosmos_artifact_by_resource("cosmos:action_credential_state")
    check(restore_artifact is None, "Restore admitted an active credential challenge/checkpoint resource.")
    # Bootstrap's generic offline client intentionally has empty queries. The
    # lifecycle slice supplies the conditional, partition-aware SDK state fake.
    from test_action_personal_credentials import CredentialContainer
    state.configure_action_credential_state(CredentialContainer("user_id"))
    state.create("owner", private)
    with web.app.test_request_context():
        from flask import session
        session["user"] = {"oid": "owner", "roles": ["User"]}
        created = chats._create_personal_conversation("owner", "credential-chat")
        check(created["user_id"] == "owner", "Real conversation owner changed.")
        owned = chats._authorize_personal_conversation_access("owner", "credential-chat")
        check(type(owned) is CosmosDict, "Chat owner must authorize real SDK point responses.")
        check(owned["_etag"], "Conversation ownership lost its ETag.")
        try:
            chats._authorize_personal_conversation_access("other", "credential-chat")
        except PermissionError:
            pass
        else:
            raise AssertionError("Private credentials bypassed actual conversation ownership.")
        from flask import g
        from unittest.mock import patch
        from functions_action_manifest import bind_action_origin
        from action_credential_contracts import ActionCredentialsRequired
        import functions_settings
        catalog_settings = {
            **functions_settings.get_settings(), "enable_semantic_kernel": True,
            "allow_user_plugins": True, "enable_user_workspace": True,
            "allow_group_plugins": True, "enable_group_workspaces": True,
            "per_user_semantic_kernel": False,
        }
        g.conversation_id = "credential-chat"
        with patch.object(functions_settings, "get_settings", return_value=catalog_settings):
            for scope_type, scope_id in (("global", "global"), ("personal", "owner")):
                action_id = f"credential-{scope_type}:mission"
                action = {
                    "id": action_id, "name": "mission", "type": "yamcs", "is_enabled": True,
                    "endpoint": "https://mission.example.invalid", "metadata": {},
                    "auth": {"type": "NoAuth"},
                    "additionalFields": {
                        "instance": "sim", "auth_method": "none", "enable_basic_auth": True,
                    },
                    "credential_requirements": {"version": 1, "slots": {
                        "proxy": {"source": "personal", "auth_type": "username_password"},
                    }},
                }
                if scope_type == "personal":
                    action["user_id"] = scope_id
                action_container = getattr(config, f"cosmos_{scope_type}_actions_container")
                action_container.upsert_item(action)
                bound = bind_action_origin(action, scope_type, scope_id)
                reference = credentials.manifest_reference(bound)
                resolved = credentials.credential_services().resolve_manifest("owner", reference)
                check(resolved["id"] == action_id, "Credential runtime resolved the wrong catalog action.")
                with credentials.credential_continuation({"mode": "chat", "checkpoint_id": action_id}):
                    try:
                        credentials.resolve_personal_credentials(bound)
                    except ActionCredentialsRequired as error:
                        check(error.credential_request["status"] == "pending", "Credential challenge was not pending.")
                        requirements = error.credential_request["requirements"]
                        check(len(requirements) == 1 and requirements[0]["slot"] == "proxy",
                              "Proxy-only YAMCS requested the wrong credentials.")
                    else:
                        raise AssertionError("Missing personal proxy credentials did not create a challenge.")
            for forbidden_reference in ("personal:other:mission", "group:unjoined:mission"):
                try:
                    credentials.credential_services().resolve_manifest("owner", forbidden_reference)
                except PermissionError:
                    pass
                else:
                    raise AssertionError("Credential reference translation bypassed catalog authorization.")
        saved = chats._persist_screened_assistant({
            "id": "credential-answer", "conversation_id": "credential-chat",
            "user_id": "owner", "role": "assistant", "content": "The retained answer.",
        }, "owner", settings={"enable_content_safety": False})
        check(saved["content"] == "The retained answer.", "Actual screened persistence changed the answer.")
        stored = chats.cosmos_messages_container.read_item("credential-answer", "credential-chat")
        check(type(stored) is CosmosDict and stored["_etag"], "Assistant point write lost its SDK mapping.")
        chats._create_personal_conversation("owner", "credential-bulk")
        state.create("owner", {
            "id": "credential-bulk-state", "record_type": "credential_checkpoint",
            "conversation_id": "credential-bulk", "value": {},
        })
        state.create("owner", {"id": "keep-binding", "record_type": "credential_binding"})
        state.create("other", {
            "id": "foreign-credential", "record_type": "credential_checkpoint",
            "conversation_id": "credential-chat", "value": {},
        })
    client = web.app.test_client()
    with client.session_transaction() as browser:
        browser["user"] = {"oid": "owner", "roles": ["User"]}
    deleted = client.delete("/api/conversations/credential-chat")
    check(deleted.status_code == 200, "Owned credential conversation delete failed: " + str(deleted.json))
    bulk = client.post("/api/delete_multiple_conversations", json={"conversation_ids": ["credential-bulk"]})
    check(bulk.status_code == 200 and bulk.json["deleted_count"] == 1,
          "Owned credential bulk delete failed: " + str(bulk.json))
    for item_id in ("credential-bootstrap", "credential-bulk-state"):
        try:
            state.read("owner", item_id)
        except LookupError:
            pass
        else:
            raise AssertionError("Conversation deletion retained private credential history.")
    check(state.read("owner", "keep-binding")["id"] == "keep-binding", "Conversation deletion removed a persistent binding.")
    check(state.read("other", "foreign-credential")["user_id"] == "other", "Conversation deletion crossed a private partition.")
    check(not environment.network_attempts, "Credential bootstrap or chat owners attempted external I/O.")
print("PASS: real credential bootstrap and chat SDK boundaries")
'''

SCHEDULER_PROBE = r'''
import sys
import tempfile
from pathlib import Path
Path("artifacts").mkdir(exist_ok=True)
tempfile.tempdir = str(Path("artifacts").resolve())
sys.path[:0] = sys.argv[1:3]
from azure.cosmos._cosmos_responses import CosmosDict
from test_support.offline_bootstrap import offline_app_imports

def check(value, message):
    if not value:
        raise AssertionError(message)

with offline_app_imports() as environment:
    import functions_action_credential_state as state
    import functions_action_credentials as credentials
    import functions_action_credential_continuation as continuation
    check("config" not in sys.modules, "Pure state discovery initialized Azure.")
    import simplechat_scheduler
    simplechat_scheduler.initialize_scheduler_runtime()
    check(state.is_configured(), "Dedicated scheduler did not configure credential state.")
    check(callable(credentials.credential_services().resolve_manifest), "Scheduler action authorization is missing.")
    check(callable(continuation.continuation_services().resolve_agent), "Scheduler canonical-agent authorization is missing.")
    saved = state.create("owner", {
        "id": "scheduler-credential", "record_type": "credential_checkpoint",
        "conversation_id": "conversation", "value": {},
    })
    raw = simplechat_scheduler.cosmos_action_credential_state_container.read_item("scheduler-credential", "owner")
    check(type(raw) is CosmosDict, "Dedicated scheduler private storage lost the SDK transport.")
    check(type(saved) is dict and saved["_etag"] == raw["_etag"], "Dedicated scheduler private owner lost its ETag.")
    check(not environment.network_attempts, "Dedicated scheduler bootstrap attempted external I/O.")
print("PASS: real dedicated scheduler credential bootstrap")
'''


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", ["early", "early-continuation", "web", "scheduler"])
def test_real_credential_bootstrap_and_chat_owner_boundaries(optimized, order):
    run_probe(SCHEDULER_PROBE if order == "scheduler" else PROBE, (order,), optimized)


def test_credential_modules_have_no_transitive_import_cycle_including_local_imports():
    root = Path(__file__).resolve().parents[1] / "application" / "single_app"
    graph = {}
    for path in root.rglob("*.py"):
        name = ".".join(path.relative_to(root).with_suffix("").parts)
        imports = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    module = ".".join([*name.split(".")[:-node.level], module]).rstrip(".")
                imports.add(module)
                imports.update(f"{module}.{alias.name}" for alias in node.names)
        graph[name] = imports
    for name in ("functions_action_credentials", "functions_action_credential_continuation", "functions_action_credential_runtime"):
        pending = [(dependency, [name, dependency]) for dependency in graph[name]]
        visited = set()
        while pending:
            dependency, chain = pending.pop()
            assert dependency != name, f"Credential import cycle: {' -> '.join(chain)}"
            if dependency in visited:
                continue
            visited.add(dependency)
            pending.extend((item, [*chain, item]) for item in graph.get(dependency, ()))
