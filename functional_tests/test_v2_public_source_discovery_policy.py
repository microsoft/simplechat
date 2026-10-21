# test_v2_public_source_discovery_policy.py
"""
Functional regressions for V2 public source discovery.
Version: 0.261.372
Implemented in: 0.261.372

V2 ignores classic curation without becoming public-only or widening selected
sources. Request, worker and legacy policies stay isolated without storage writes.
"""

import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from test_v2_public_chat_scope import APP, USER, world
from test_support.agent_delegation import execute_functions


@pytest.mark.parametrize("preferences", [
    {},
    {"publicDirectorySettings": {}},
    {"publicDirectorySettings": {"shown": True}},
    {"publicDirectorySettings": {"shown": True, "hidden": False}},
    {"publicDirectorySettings": {"hidden": True}},
    {"visiblePublicWorkspaceIds": []},
    {"visiblePublicWorkspaceIds": ["shown"]},
])
def test_v2_ignores_classic_curation_without_writing(world, preferences):
    world.preferences["settings"] = preferences
    original = deepcopy(world.preferences)
    with world.app.test_request_context(headers={"X-SimpleChat-UI": "v2"}):
        ids = world.public.get_public_source_workspace_ids(USER)
        aggregate = world.scope.current_public_chat_scope(USER)
    assert ids == ["shown", "hidden", "uploads-off"]
    assert aggregate is None
    assert world.preferences == original


def test_classic_and_v2_requests_keep_independent_policies(world):
    with world.app.test_request_context():
        classic = world.public.get_public_source_workspace_ids(USER)
    with world.app.test_request_context("/api/v2/scope"):
        native = world.public.get_public_source_workspace_ids(USER)
    with world.app.test_request_context("/api/document?ui_version=v2"):
        navigation = world.public.get_public_source_workspace_ids(USER)
    assert classic == ["shown"]
    assert native == navigation == ["shown", "hidden", "uploads-off"]


def test_native_scope_route_uses_eligibility_not_classic_curation(world):
    from flask import Blueprint, jsonify

    world.preferences["settings"]["activePublicWorkspaceOid"] = "hidden"
    bp = Blueprint("v2_policy_scope", __name__)
    namespace = {
        "bp": bp, "jsonify": jsonify,
        "swagger_route": lambda **kwargs: lambda function: function,
        "get_auth_security": lambda: [],
        "login_required": lambda function: function,
        "user_required": lambda function: function,
        "get_current_user_id": lambda: USER,
        "get_user_settings": lambda user_id: world.preferences,
        "get_user_groups": lambda user_id: [],
        "get_optional_active_group": lambda user_id: None,
        "get_public_source_workspace_ids": world.public.get_public_source_workspace_ids,
        "find_public_workspace_by_id": lambda workspace_id: next(
            (row for row in world.workspaces if row["id"] == workspace_id), None,
        ),
    }
    execute_functions("route_backend_v2.py", {"_resolve_active_scope"}, namespace)
    path = APP / "route_backend_v2.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    route = next(node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name == "v2_scope")
    exec(compile(ast.Module(body=[route], type_ignores=[]), str(path), "exec"), namespace)
    world.app.register_blueprint(bp)
    client = world.app.test_client()
    available = client.get("/api/v2/scope")
    world.workspaces[1]["status"] = "inactive"
    revoked = client.get("/api/v2/scope")
    assert available.status_code == revoked.status_code == 200
    assert available.get_json()["scope"]["active_public_workspace_id"] == "hidden"
    assert revoked.get_json()["scope"]["active_public_workspace_id"] is None


def test_worker_policy_is_bound_to_user_and_reset_after_failure(world):
    from public_source_policy import public_source_policy_context

    def worker(policy):
        with public_source_policy_context(USER, policy):
            ids = world.public.get_public_source_workspace_ids(USER)
            other = world.public.get_public_source_workspace_ids("other")
            other_visible = world.public.resolve_public_chat_workspace_ids("other", "visible")
            assert other_visible == ["shown"]
        clean = world.public.get_public_source_workspace_ids(USER)
        return ids, other, clean

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ["all_available", "legacy_visible"]))
    assert results == [
        (["shown", "hidden", "uploads-off"], ["shown"], ["shown"]),
        (["shown"], ["shown"], ["shown"]),
    ]
    with pytest.raises(RuntimeError):
        with public_source_policy_context(USER, "all_available"):
            raise RuntimeError("interrupted")
    clean = world.public.get_public_source_workspace_ids(USER)
    assert clean == ["shown"]


def test_v2_legacy_visible_mode_normalizes_without_changing_classic(world):
    with world.app.test_request_context(headers={"X-SimpleChat-UI": "v2"}):
        v2 = world.public.resolve_public_chat_workspace_ids(USER, "visible")
    with world.app.test_request_context():
        classic = world.public.resolve_public_chat_workspace_ids(USER, "visible")
    assert v2 == ["shown", "hidden", "uploads-off"]
    assert classic == ["shown"]


def test_shared_consumers_cannot_widen_an_admitted_public_only_turn(world):
    with world.app.test_request_context(headers={"X-SimpleChat-UI": "v2"}):
        with world.scope.public_chat_scope_context(
            USER, "all", ["hidden"], world.public.resolve_public_chat_workspace_ids,
        ):
            ids = world.public.get_public_source_workspace_ids(USER)
            world.workspaces.append({"id": "new", "status": "active"})
            rechecked = world.public.get_public_source_workspace_ids(USER)
            world.workspaces[1]["status"] = "inactive"
            with pytest.raises(world.scope.PublicChatScopeError, match="No public"):
                world.public.get_public_source_workspace_ids(USER)
    assert ids == rechecked == ["hidden"]


@pytest.mark.parametrize("index_ready", [False, True])
def test_ordinary_picker_and_tags_use_v2_policy_before_paging(world, index_ready):
    from test_public_chat_document_list_pending_artifacts import (
        WORKSPACES, answer, chat_routes, pending_documents, released_documents,
    )

    world.workspaces[:] = [{"id": value, "status": "active"} for value in WORKSPACES]
    world.preferences["settings"] = {"publicDirectorySettings": {"public-a": True, "public-b": False}}
    with chat_routes(released_documents() + pending_documents(), index_ready=index_ready) as env:
        env.list.__globals__["resolve_public_chat_workspace_ids"] = world.public.resolve_public_chat_workspace_ids
        env.list.__globals__["PublicChatScopeError"] = world.scope.PublicChatScopeError
        env.args.update(page="2", page_size="2")
        with world.app.test_request_context(headers={"X-SimpleChat-UI": "v2"}):
            documents = answer(env.list)
            tags = answer(env.tags)
        with world.app.test_request_context():
            classic = answer(env.list)
    assert [item["id"] for item in documents["documents"]] == ["released-b"]
    assert documents["total_count"] == 3
    assert classic["documents"] == []
    assert classic["total_count"] == 2
    assert {tag["name"]: tag["count"] for tag in tags["tags"] if tag["count"]} == {
        "finance": 2, "team": 2,
    }


def test_worker_scope_restores_mixed_policy_without_aggregate_mode(world):
    from types import SimpleNamespace

    context = SimpleNamespace(seeds={
        "public_source_policy": "all_available",
        "public_workspace_selection": None,
        "active_group_ids": ["group-a"],
        "active_public_workspace_ids": ["hidden"],
    })
    with world.scope.public_chat_execution_scope(context, USER, world.settings):
        ids = world.public.get_public_source_workspace_ids(USER)
        aggregate = world.scope.current_public_chat_scope(USER)
    assert ids == ["shown", "hidden", "uploads-off"]
    assert aggregate is None
    assert context.seeds["active_group_ids"] == ["group-a"]
    assert context.seeds["active_public_workspace_ids"] == ["hidden"]


def test_disabled_public_sources_do_not_break_personal_discovery(world):
    world.settings["enable_public_workspaces"] = False
    with world.app.test_request_context(headers={"X-SimpleChat-UI": "v2"}):
        ids = world.public.get_public_source_workspace_ids(USER)
        with pytest.raises(world.scope.PublicChatScopeError, match="disabled"):
            world.public.resolve_public_chat_workspace_ids(USER, "all")
    assert ids == []


def test_mixed_chat_admission_retains_selected_public_and_group_scopes(world):
    namespace = {
        "aggregate_public_workspace_ids": world.scope.aggregate_public_workspace_ids,
        "get_public_source_workspace_ids": world.public.get_public_source_workspace_ids,
        "find_group_by_id": lambda group_id: {"id": group_id},
        "get_user_role_in_group": lambda group, user_id: "User",
    }
    execute_functions("route_backend_chats.py", {
        "_normalize_requested_scope_ids", "_get_authorized_chat_scope_context",
    }, namespace)
    with world.app.test_request_context(headers={"X-SimpleChat-UI": "v2"}):
        admitted = namespace["_get_authorized_chat_scope_context"](
            USER, active_group_ids=["group-a"], active_public_workspace_ids=["hidden", "inactive", "forged"],
        )
    assert admitted["active_group_ids"] == ["group-a"]
    assert admitted["active_public_workspace_ids"] == ["hidden"]
    assert world.scope.current_public_chat_scope(USER) is None


def test_search_keeps_all_eligible_public_ids_and_explicit_narrowing(world):
    from public_source_policy import uses_all_public_sources

    namespace = {
        "current_public_chat_scope": world.scope.current_public_chat_scope,
        "aggregate_public_workspace_ids": world.scope.aggregate_public_workspace_ids,
        "get_public_source_workspace_ids": world.public.get_public_source_workspace_ids,
        "uses_all_public_sources": uses_all_public_sources,
        "strict_source_authority_enabled": lambda: True,
        "_resolve_active_group_ids": lambda *args, **kwargs: ["group-a"],
        "SEARCH_DEFAULT_TOP_N": 12, "SEARCH_MAX_TOP_N": 500,
    }
    execute_functions("functions_search.py", {
        "normalize_search_scope", "normalize_search_top_n", "normalize_search_id_list",
    }, namespace)
    namespace["VALID_SEARCH_SCOPES"] = {"all", "personal", "group", "public"}
    execute_functions("functions_search_service.py", {
        "_resolve_public_workspace_ids", "build_search_request",
    }, namespace)
    with world.app.test_request_context(headers={"X-SimpleChat-UI": "v2"}):
        broad = namespace["build_search_request"]("service target", USER)
        narrow = namespace["build_search_request"](
            "service target", USER, document_ids=["selected-guide"],
            active_public_workspace_id=["hidden"],
        )
        snapshot = namespace["_resolve_public_workspace_ids"](
            USER, visible_public_workspace_ids=["shown"],
        )
    assert broad["doc_scope"] == "all"
    assert broad["active_group_ids"] == ["group-a"]
    assert broad["active_public_workspace_id"] == ["shown", "hidden", "uploads-off"]
    assert narrow["document_ids"] == ["selected-guide"]
    assert narrow["active_public_workspace_id"] == ["hidden"]
    assert snapshot == ["shown", "hidden", "uploads-off"]


def test_agent_worker_bridge_retains_mixed_v2_policy(world):
    from agent_execution_context import capture_execution_identity
    from flask import session

    world.app.secret_key = "test-only"
    with world.app.test_request_context(headers={"X-SimpleChat-UI": "v2"}):
        session["user"] = {"oid": USER, "roles": ["User"]}
        identity = capture_execution_identity(USER, "conversation-a")

    def worker():
        with identity.bridge({"name": "Read selected public guide"}):
            ids = world.public.get_public_source_workspace_ids(USER)
            aggregate = world.scope.current_public_chat_scope(USER)
        clean = world.public.get_public_source_workspace_ids(USER)
        return ids, aggregate, clean

    with ThreadPoolExecutor(max_workers=1) as pool:
        ids, aggregate, clean = pool.submit(worker).result()
    assert ids == ["shown", "hidden", "uploads-off"]
    assert aggregate is None
    assert clean == ["shown"]


def test_retry_context_retains_policy_and_exact_document_selection(world):
    namespace = {}
    execute_functions("route_backend_conversations.py", {"_build_replayed_document_context"}, namespace)
    restored = namespace["_build_replayed_document_context"]({"workspace_search": {
        "public_source_policy": "all_available",
        "document_scope": "all",
        "requested_document_ids": ["personal-a", "group-a", "guide-a"],
        "active_group_ids": ["group-a"],
        "active_public_workspace_ids": ["hidden"],
    }})
    assert restored["public_source_policy"] == "all_available"
    assert restored["selected_document_ids"] == ["personal-a", "group-a", "guide-a"]
    assert restored["doc_scope"] == "all"
    assert restored["active_group_ids"] == ["group-a"]
    assert restored["active_public_workspace_ids"] == ["hidden"]


def test_v2_admission_cannot_reintroduce_classic_curation_from_payload(world):
    from public_source_policy import (
        ALL_AVAILABLE, current_public_source_policy, normalize_public_source_policy,
    )

    namespace = {
        "ALL_AVAILABLE": ALL_AVAILABLE,
        "current_public_source_policy": current_public_source_policy,
        "normalize_public_source_policy": normalize_public_source_policy,
        "normalize_public_workspace_selection": world.scope.normalize_public_workspace_selection,
    }
    execute_functions("functions_orchestration_context.py", {
        "_text", "_string_list", "resolve_seeds",
    }, namespace)
    with world.app.test_request_context(headers={"X-SimpleChat-UI": "v2"}):
        seeds = namespace["resolve_seeds"]({
            "public_source_policy": "legacy_visible",
            "selected_document_ids": ["personal-a", "guide-a"],
            "active_group_ids": ["group-a"],
            "active_public_workspace_ids": ["hidden"],
        })
        with pytest.raises(ValueError, match="Invalid public source policy"):
            namespace["resolve_seeds"]({"public_source_policy": "unknown"})
    assert seeds["public_source_policy"] == "all_available"
    assert seeds["public_workspace_selection"] is None
    assert seeds["document_ids"] == ["personal-a", "guide-a"]
    assert seeds["active_group_ids"] == ["group-a"]


def test_workflow_seeds_keep_saved_policy_and_selected_sources_without_request(world):
    from public_source_policy import current_public_source_policy

    namespace = {
        "deepcopy": deepcopy,
        "current_public_source_policy": current_public_source_policy,
    }
    execute_functions("functions_workflow_chat_execution.py", {"build_workflow_chat_seeds"}, namespace)
    workflow = {
        "user_id": USER,
        "public_source_policy": "all_available",
        "document_action": {
            "type": "search", "doc_scope": "all",
            "document_ids": ["personal-a", "public-a"],
            "active_group_ids": ["group-a"],
            "active_public_workspace_id": ["hidden"],
        },
    }
    seeds = namespace["build_workflow_chat_seeds"](workflow, {})
    assert seeds["public_source_policy"] == "all_available"
    assert seeds["public_workspace_selection"] is None
    assert seeds["document_ids"] == ["personal-a", "public-a"]
    assert seeds["active_public_workspace_ids"] == ["hidden"]
    assert seeds["active_group_ids"] == ["group-a"]


@pytest.mark.parametrize("policy", ["all_available", "legacy_visible"])
def test_source_policy_rebinds_restored_mixed_seeds(world, policy):
    from types import SimpleNamespace
    from public_source_policy import current_public_source_policy

    original = {
        "public_source_policy": policy,
        "public_workspace_selection": None,
        "document_ids": ["guide-a"],
        "active_public_workspace_ids": ["hidden"],
    }
    context = SimpleNamespace(seeds=deepcopy(original), original_seeds=deepcopy(original))
    with world.scope.public_chat_execution_scope(context, USER, world.settings):
        effective = current_public_source_policy(USER)
    assert effective == policy
    assert context.original_seeds == original
