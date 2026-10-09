# test_v2_public_chat_scope.py
"""
Functional regressions for aggregate public chat.
Version: 0.261.311
Implemented in: 0.261.310

Real scope and workspace modules run over scoped storage doubles. Admission, empty-set
refusals, locks, per-turn resolution and worker isolation execute without Azure access.
The existing source-execution helper drives the real search request and replay builders.
"""

import importlib.util
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from flask import Flask, g, session

from test_support.agent_delegation import execute_functions


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
USER = "public-reader"


def module(name, **values):
    result = ModuleType(name)
    result.__dict__.update(values)
    return result


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def world(monkeypatch):
    monkeypatch.syspath_prepend(str(APP))
    state = load("public_chat_scope_state", APP / "public_chat_scope_state.py")
    monkeypatch.setitem(sys.modules, "public_chat_scope_state", state)
    scope = load("public_chat_scope", APP / "public_chat_scope.py")
    monkeypatch.setitem(sys.modules, "public_chat_scope", scope)
    settings = {"enable_public_workspaces": True}
    preferences = {"settings": {"publicDirectorySettings": {"shown": True, "hidden": False}}}
    workspaces = [
        {"id": "shown", "status": "active"},
        {"id": "hidden", "status": "locked"},
        {"id": "uploads-off", "status": "upload_disabled"},
        {"id": "inactive", "status": "inactive"},
        {"id": "unknown", "status": "future"},
    ]
    logs = []
    dependencies = {
        "config": module("config", cosmos_public_workspaces_container=SimpleNamespace(
            query_items=lambda **kwargs: list(workspaces),
        )),
        "functions_authentication": module("functions_authentication", get_current_user_id=lambda: USER),
        "functions_settings": module("functions_settings",
            get_settings=lambda: settings, get_user_settings=lambda user_id: preferences),
        "functions_group": module("functions_group"),
        "functions_chat_bootstrap_cache": module("functions_chat_bootstrap_cache",
            bump_chat_bootstrap_global_cache_version=lambda **kwargs: None),
        "functions_workspace_branding": module("functions_workspace_branding",
            DEFAULT_WORKSPACE_HERO_COLOR="#0078d4",
            get_workspace_logo_metadata=lambda value: {},
            normalize_workspace_hero_color=lambda value: value),
        "functions_appinsights": module("functions_appinsights", log_event=lambda *args, **kwargs: logs.append(kwargs)),
    }
    for name, value in dependencies.items():
        monkeypatch.setitem(sys.modules, name, value)
    public = load("functions_public_workspaces", APP / "functions_public_workspaces.py")
    monkeypatch.setitem(sys.modules, "functions_public_workspaces", public)
    return SimpleNamespace(scope=scope, public=public, settings=settings, preferences=preferences,
                           workspaces=workspaces, app=Flask(__name__), logs=logs)


def test_all_ignores_curation_but_preserves_availability_and_preferences(world):
    original = dict(world.preferences["settings"]["publicDirectorySettings"])
    resolved = world.public.resolve_public_chat_workspace_ids(USER, "all")
    assert resolved == ["shown", "hidden", "uploads-off"]
    assert world.preferences["settings"]["publicDirectorySettings"] == original
    visible = world.public.resolve_public_chat_workspace_ids(USER, "visible")
    assert visible == ["shown"]


@pytest.mark.parametrize("preferences, expected", [
    ({}, ["shown", "hidden", "uploads-off"]),
    ({"publicDirectorySettings": {}}, ["shown", "hidden", "uploads-off"]),
    ({"visiblePublicWorkspaceIds": ["hidden", "deleted", "inactive"]}, ["hidden"]),
    ({"publicDirectorySettings": {"shown": False, "hidden": False}}, []),
    ({"visiblePublicWorkspaceIds": []}, []),
])
def test_visible_uses_canonical_fallbacks(world, preferences, expected):
    world.preferences["settings"] = preferences
    resolved = world.public.resolve_public_chat_workspace_ids(USER, "visible")
    assert resolved == expected


@pytest.mark.parametrize("mode", ["", "ALL", "personal", True, [], {}])
def test_malformed_modes_are_refused(world, mode):
    with pytest.raises(world.scope.PublicChatScopeError):
        world.public.resolve_public_chat_workspace_ids(USER, mode)


def test_admission_is_public_only_and_intersects_locks(world):
    data = {"public_workspace_selection": "all", "doc_scope": "all",
            "active_group_ids": ["private-group"], "active_public_workspace_ids": ["forged"]}
    conversation = {"scope_locked": True, "locked_contexts": [
        {"scope": "personal", "id": USER}, {"scope": "public", "id": "hidden"},
    ]}
    with world.app.test_request_context():
        admitted = world.scope.prepare_public_chat_scope(
            data, USER, world.settings, world.public.resolve_public_chat_workspace_ids, conversation,
        )
        assert admitted["workspace_ids"] == ["hidden"]
        assert data["doc_scope"] == "public" and data["hybrid_search"]
        assert data["active_group_ids"] == [] and data["active_group_id"] is None
        assert data["active_public_workspace_ids"] == ["hidden"]
        assert world.scope.current_public_chat_scope("other-user") is None
    assert world.scope.current_public_chat_scope(USER) is None


def test_empty_disabled_and_saved_result_scopes_fail_before_model_work(world):
    data = {"public_workspace_selection": "visible"}
    world.preferences["settings"] = {"visiblePublicWorkspaceIds": []}
    with world.app.test_request_context():
        with pytest.raises(world.scope.PublicChatScopeError, match="No public"):
            world.scope.prepare_public_chat_scope(data, USER, world.settings, world.public.resolve_public_chat_workspace_ids)
        world.settings["enable_public_workspaces"] = False
        with pytest.raises(world.scope.PublicChatScopeError, match="disabled"):
            world.scope.prepare_public_chat_scope(data, USER, world.settings, world.public.resolve_public_chat_workspace_ids)
        with pytest.raises(world.scope.PublicChatScopeError, match="saved result"):
            world.scope.prepare_public_chat_scope(
                {**data, "analysis_result_context": {}}, USER, world.settings,
                world.public.resolve_public_chat_workspace_ids,
            )


def test_each_turn_resolves_again_and_downstream_reads_cannot_widen(world):
    with world.app.test_request_context():
        first = world.scope.prepare_public_chat_scope(
            {"public_workspace_selection": "all"}, USER, world.settings,
            world.public.resolve_public_chat_workspace_ids,
        )
        world.workspaces.append({"id": "new", "status": "active"})
        world.workspaces[1]["status"] = "inactive"
        current = world.scope.aggregate_public_workspace_ids(USER)
        assert current == ["shown", "uploads-off"]
        second = world.scope.prepare_public_chat_scope(
            {"public_workspace_selection": "all"}, USER, world.settings,
            world.public.resolve_public_chat_workspace_ids,
        )
        assert "new" in second["workspace_ids"] and "new" not in first["workspace_ids"]


def test_revoked_run_scope_is_an_error_and_thread_binding_is_isolated(world):
    context = SimpleNamespace(
        seeds={"public_workspace_selection": "all", "active_public_workspace_ids": ["hidden"]},
        resolve_public_chat_workspace_ids=world.public.resolve_public_chat_workspace_ids,
    )
    def worker():
        with world.scope.public_chat_execution_scope(context, USER, world.settings):
            return world.scope.aggregate_public_workspace_ids(USER)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(worker).result()
        clean = pool.submit(world.scope.current_public_chat_scope, USER).result()
    assert result == ["hidden"] and clean is None
    world.workspaces[1]["status"] = "inactive"
    with pytest.raises(world.scope.PublicChatScopeError, match="No public"):
        worker()


@pytest.mark.parametrize("failure, expected", [(PermissionError(), 403), (LookupError(), 404), (RuntimeError("private"), 503)])
def test_admission_refuses_ownership_and_storage_errors_safely(world, failure, expected):
    calls = []
    def authorize(user_id, conversation_id):
        assert (user_id, conversation_id) == (USER, "someone-elses-chat")
        raise failure
    @world.app.post("/scope")
    @world.scope.public_chat_scope_required(
        authorize, lambda: USER, lambda: world.settings,
        world.public.resolve_public_chat_workspace_ids,
        lambda *args, **kwargs: world.logs.append(kwargs),
    )
    def route():
        calls.append("model")
        return {"ok": True}
    with world.app.test_request_context("/scope", method="POST", json={
        "public_workspace_selection": "all", "conversation_id": "someone-elses-chat",
    }):
        response = world.app.full_dispatch_request()
    assert response.status_code == expected and not calls
    assert "private" not in response.get_data(as_text=True)
    if expected == 503:
        assert world.logs[-1]["level"] == logging.ERROR


def test_search_request_retains_all_public_ids_without_group_scope(world):
    def ids(value):
        return value if isinstance(value, list) else [value] if value else []
    namespace = {
        "current_public_chat_scope": world.scope.current_public_chat_scope,
        "aggregate_public_workspace_ids": world.scope.aggregate_public_workspace_ids,
        "normalize_search_id_list": ids, "normalize_search_scope": lambda value: value,
        "normalize_search_top_n": lambda value, default, maximum: value or default,
        "SEARCH_DEFAULT_TOP_N": 12, "SEARCH_MAX_TOP_N": 500,
        "_resolve_active_group_ids": lambda *args, **kwargs: ["private-group"],
    }
    execute_functions("functions_search_service.py", {"build_search_request", "_resolve_public_workspace_ids"}, namespace)
    with world.scope.public_chat_scope_context(
        USER, "all", ["shown", "hidden"], world.public.resolve_public_chat_workspace_ids,
    ):
        request = namespace["build_search_request"]("policy", USER, doc_scope="personal")
    assert request["doc_scope"] == "public"
    assert request["active_public_workspace_id"] == ["shown", "hidden"]
    assert "active_group_ids" not in request


def test_execution_rechecks_live_conversation_lock_and_owner(world):
    conversation = {"user_id": USER, "scope_locked": True, "locked_contexts": [{"scope": "public", "id": "hidden"}]}
    context = SimpleNamespace(conversation_id="saved", seeds={
        "public_workspace_selection": "all", "active_public_workspace_ids": ["shown", "hidden"],
    }, resolve_public_chat_workspace_ids=world.public.resolve_public_chat_workspace_ids,
       read_conversation_for_public_chat=lambda requested: conversation if requested == "saved" else None)
    with world.scope.public_chat_execution_scope(context, USER, world.settings):
        resolved = world.scope.aggregate_public_workspace_ids(USER)
    assert resolved == ["hidden"]
    conversation["locked_contexts"] = [{"scope": "personal", "id": USER}]
    with pytest.raises(world.scope.PublicChatScopeError):
        with world.scope.public_chat_execution_scope(context, USER, world.settings):
            pytest.fail("A changed lock must refuse the run.")
    conversation["user_id"] = "another-user"
    with pytest.raises(PermissionError):
        with world.scope.public_chat_execution_scope(context, USER, world.settings):
            pytest.fail("A changed owner must refuse the run.")


@pytest.mark.parametrize("selection", ["all", "visible"])
def test_retry_and_edit_keep_the_aggregate_intent(selection):
    namespace = {}
    execute_functions("route_backend_conversations.py", {"_build_replayed_document_context"}, namespace)
    replay = namespace["_build_replayed_document_context"]({"workspace_search": {
        "public_workspace_selection": selection, "scope": "public", "tags": ["policy"], "enabled": True,
    }})
    assert replay["public_workspace_selection"] == selection and replay["doc_scope"] == "public"
    assert replay["tags"] == ["policy"]


@pytest.mark.parametrize("selection", ["all", "visible"])
def test_delegated_request_bridge_retains_admission_without_parent_workspace_state(world, selection):
    from agent_execution_context import capture_execution_identity

    world.app.secret_key = "public-scope-test"
    with world.app.test_request_context("/chat"):
        session["user"] = {"oid": USER, "roles": ["User"]}
        g.active_group_id = "parent-private-group"
        admitted = world.scope.prepare_public_chat_scope(
            {"public_workspace_selection": selection}, USER, world.settings,
            world.public.resolve_public_chat_workspace_ids,
        )
        identity = capture_execution_identity(USER, "saved")
    assert world.scope.current_public_chat_scope(USER) is None

    def worker():
        with identity.bridge({"name": "Public search helper"}):
            resolved = world.scope.aggregate_public_workspace_ids(USER)
            assert session["user"]["oid"] == USER
            assert not hasattr(g, "active_group_id") and not hasattr(g, "public_chat_scope")
            assert world.scope.current_public_chat_scope("another-user") is None
        assert world.scope.current_public_chat_scope(USER) is None
        return resolved

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert results == [admitted["workspace_ids"], admitted["workspace_ids"]]


@pytest.mark.parametrize("index_ready", [False, True])
def test_aggregate_picker_routes_share_publication_and_tag_policy(world, index_ready):
    from test_public_chat_document_list_pending_artifacts import (
        WORKSPACES, answer, chat_routes, pending_documents, released_documents,
    )

    world.workspaces[:] = [{"id": value, "status": "active"} for value in WORKSPACES]
    world.preferences["settings"] = {"publicDirectorySettings": {"public-a": True, "public-b": False}}
    with chat_routes(released_documents() + pending_documents(), index_ready=index_ready) as env:
        namespace = env.list.__globals__
        namespace["resolve_public_chat_workspace_ids"] = world.public.resolve_public_chat_workspace_ids
        namespace["PublicChatScopeError"] = world.scope.PublicChatScopeError
        env.args["public_workspace_selection"] = "all"
        all_docs = answer(env.list)
        all_tags = answer(env.tags)
        env.args["public_workspace_selection"] = "visible"
        visible_docs = answer(env.list)
        env.args["workspace_ids"] = "public-b,outside"
        narrowed_tags = answer(env.tags)
    assert [item["id"] for item in all_docs["documents"]] == ["released-a", "approved-a", "released-b"]
    assert [item["id"] for item in visible_docs["documents"]] == ["released-a", "approved-a"]
    assert {tag["name"]: tag["count"] for tag in all_tags["tags"] if tag["count"]} == {"finance": 2, "team": 2}
    assert narrowed_tags["tags"] == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
