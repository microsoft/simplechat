# test_agent_delegation_auth_handoff.py
"""
HTTP-level regression for durable Foundry consent after streaming headers.
Version: 0.261.093
Implemented in: 0.261.093

Uses Flask's real RedisSessionInterface with an in-memory Redis substitute.
The real target executor, authenticated auth-initiation route, scope helpers and
session persistence execute; only external Cosmos/MSAL/model services are mocked.
"""

import asyncio
import json
import sys
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, Dict
from urllib.parse import parse_qs, urlencode, urlparse
from unittest.mock import AsyncMock, Mock

import pytest
from flask import Response, jsonify, redirect, session, stream_with_context
from flask_session.redis import RedisSessionInterface
from redis import Redis

from test_agent_delegation_runtime import module, runtime
from test_support.agent_delegation import delegation_environment, delegation_route_app, execute_functions


SCOPE = "https://ai.azure.com/.default"


class MemoryRedis(Redis):
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value, **kwargs):
        self.values[name] = value
        return True

    def delete(self, name):
        return int(self.values.pop(name, None) is not None)

    def close(self):
        pass


class FoundryAgentUserAuthenticationRequired(RuntimeError):
    def __init__(self, message, auth_response=None):
        super().__init__(message)
        self.auth_response = auth_response or {}


@pytest.fixture
def auth_environment(runtime, monkeypatch):
    with delegation_environment() as (helper, services):
        target = services.add_agent(
            "remote", agent_type="new_foundry",
            other_settings={"new_foundry": {"authentication_type": "delegated_user", "foundry_scope": SCOPE}},
        )
        msal = Mock()
        msal.get_authorization_request_url.side_effect = lambda scopes, **kwargs: (
            f"https://login.example/authorize?{urlencode({'scope': ' '.join(scopes), 'redirect_uri': kwargs['redirect_uri']})}"
        )
        config_resolver = Mock(side_effect=lambda agent, settings, **kwargs: deepcopy(agent))

        def configure(namespace):
            namespace.update({
                "Any": Any, "Dict": Dict, "redirect": redirect,
                "resolve_delegation_agent": helper.resolve_delegation_agent,
                "resolve_agent_config": config_resolver,
                "_build_msal_app": Mock(return_value=msal), "_load_cache": Mock(return_value=None),
                "get_graph_authority": lambda: "https://login.example/tenant",
                "REQUESTED_SCOPES_SESSION_KEY": "requested_oauth_scopes",
                "SCOPE": ["original.scope"], "REDIRECT_PATH": "/callback-probe",
            })
            execute_functions("functions_authentication.py", {
                "_normalize_scopes", "set_requested_oauth_scopes", "get_requested_oauth_scopes",
                "_build_redirect_url", "get_consent_url", "_build_plugin_auth_response",
            }, namespace)
            execute_functions("foundry_agent_runtime.py", {
                "_resolve_foundry_authentication_type", "_resolve_foundry_scope",
            }, namespace)
            execute_functions("route_backend_agents.py", {"initiate_delegated_foundry_auth"}, namespace)

        app, namespace = delegation_route_app(helper, services, configure=configure)
        app.session_interface = RedisSessionInterface(app, client=MemoryRedis(), key_prefix="test:")

        async def require_consent(**kwargs):
            raise FoundryAgentUserAuthenticationRequired(
                "Sign in to Foundry.",
                {"scopes": [SCOPE], "auth_url": "https://login.example/stale", "consent_url": "https://login.example/stale"},
            )

        monkeypatch.setitem(sys.modules, "semantic_kernel_loader", module(
            "semantic_kernel_loader", resolve_agent_config=config_resolver,
        ))
        monkeypatch.setitem(sys.modules, "foundry_agent_runtime", module(
            "foundry_agent_runtime",
            execute_foundry_agent=require_consent,
            execute_new_foundry_agent=require_consent,
            execute_foundry_workflow_agent=require_consent,
        ))
        monkeypatch.setattr(runtime, "_target_messages", AsyncMock(return_value=([SimpleNamespace(content="task")], [])))

        def stream():
            identity = runtime.capture_execution_identity("actor", "conversation")
            budget = runtime.contexts.DelegationBudget()
            frame = runtime.contexts.AgentExecutionFrame(identity, target, budget, depth=1)

            def events():
                yield 'data: {"started":true}\n\n'
                try:
                    asyncio.run(runtime.execute_target(target, "task", "", frame))
                except FoundryAgentUserAuthenticationRequired as error:
                    budget.require_authentication(error)
                try:
                    budget.raise_authentication_requirement(identity)
                except FoundryAgentUserAuthenticationRequired as error:
                    yield f"data: {json.dumps(error.auth_response)}\n\n"

            return Response(stream_with_context(events()), mimetype="text/event-stream")

        def probe():
            return jsonify({"scopes": session.get("requested_oauth_scopes"), "user": session.get("user")})

        app.add_url_rule("/stream", view_func=stream)
        app.add_url_rule("/probe", view_func=probe)
        app.add_url_rule(
            "/callback-probe",
            view_func=lambda: jsonify({"scopes": namespace["get_requested_oauth_scopes"](clear_after_read=True)}),
        )
        yield app, namespace, services, msal, config_resolver, target


def signed_in_client(app, user_id="actor"):
    client = app.test_client()
    with client.session_transaction() as values:
        values["user"] = {"oid": user_id, "roles": ["User"], "preferred_username": f"{user_id}@example.test"}
        values["requested_oauth_scopes"] = ["original.scope"]
    return client


def test_streamed_consent_persists_server_derived_scopes_before_oauth_redirect(auth_environment):
    app, _, _, msal, _, _ = auth_environment
    client = signed_in_client(app)
    response = client.get("/stream", buffered=False)
    events = [json.loads(block.removeprefix("data: ")) for block in response.get_data(as_text=True).strip().split("\n\n")]
    auth = events[-1]
    response.close()
    assert auth["auth_url"] == auth["consent_url"]
    assert auth["auth_url"].startswith("/api/agents/foundry-auth?")
    assert parse_qs(urlparse(auth["auth_url"]).query) == {
        "id": ["remote"], "scope_type": ["personal"], "scope_id": ["actor"],
    }

    # The closed stream cannot save its later in-memory session edits.
    assert client.get("/probe").json["scopes"] == ["original.scope"]
    initiation = client.get(auth["auth_url"])
    assert initiation.status_code == 302
    assert initiation.headers["Cache-Control"] == "no-store"
    assert parse_qs(urlparse(initiation.headers["Location"]).query)["scope"] == [SCOPE]
    msal.get_authorization_request_url.assert_called_once()
    assert client.get("/probe").json["scopes"] == [SCOPE]
    assert client.get("/callback-probe").json["scopes"] == [SCOPE]
    assert client.get("/probe").json["scopes"] is None


@pytest.mark.parametrize("query,status", [
    ("id=remote&scope_type=personal&scope_id=actor&scopes=attacker.scope", 400),
    ("id=remote&scope_type=personal&scope_id=actor&auth_url=https://attacker.invalid", 400),
    ("id=remote&scope_type=personal&scope_id=other-user", 403),
    ("id=missing&scope_type=personal&scope_id=actor", 404),
])
def test_auth_initiation_rejects_scope_and_identity_overrides(auth_environment, query, status):
    app, _, _, msal, _, _ = auth_environment
    client = signed_in_client(app)
    response = client.get(f"/api/agents/foundry-auth?{query}")
    assert response.status_code == status
    msal.get_authorization_request_url.assert_not_called()
    assert client.get("/probe").json["scopes"] == ["original.scope"]


@pytest.mark.parametrize("mode,settings_key", [
    ("aifoundry", "azure_ai_foundry"), ("new_foundry", "new_foundry"), ("foundry_workflow", "foundry_workflow"),
])
def test_auth_initiation_uses_each_saved_foundry_mode_and_current_cloud(auth_environment, mode, settings_key):
    app, _, services, msal, _, target = auth_environment
    target["agent_type"] = mode
    target["other_settings"] = {settings_key: {"authentication_type": "delegated_user", "cloud": "usgov"}}
    client = signed_in_client(app)
    response = client.get("/api/agents/foundry-auth?id=remote&scope_type=personal&scope_id=actor")
    assert response.status_code == 302
    assert msal.get_authorization_request_url.call_args.args[0] == ["https://ai.azure.us/.default"]
    assert client.get("/callback-probe").json["scopes"] == ["https://ai.azure.us/.default"]


@pytest.mark.parametrize("auth_type", ["api_key", "managed_identity", "service_principal"])
def test_auth_initiation_does_not_replace_non_user_credentials(auth_environment, auth_type):
    app, _, _, msal, _, target = auth_environment
    target["other_settings"]["new_foundry"]["authentication_type"] = auth_type
    response = signed_in_client(app).get("/api/agents/foundry-auth?id=remote&scope_type=personal&scope_id=actor")
    assert response.status_code == 400
    msal.get_authorization_request_url.assert_not_called()


def test_auth_initiation_rechecks_governance_after_streaming(auth_environment):
    app, _, services, msal, _, _ = auth_environment
    client = signed_in_client(app)
    services.denied_features.add("governance_user_agents")
    response = client.get("/api/agents/foundry-auth?id=remote&scope_type=personal&scope_id=actor")
    assert response.status_code == 403
    msal.get_authorization_request_url.assert_not_called()


def test_a_different_user_cannot_reuse_a_personal_target_handoff(auth_environment):
    app, _, _, msal, _, _ = auth_environment
    client = signed_in_client(app, user_id="other-user")
    response = client.get("/api/agents/foundry-auth?id=remote&scope_type=personal&scope_id=actor")
    assert response.status_code == 403
    msal.get_authorization_request_url.assert_not_called()
    assert client.get("/probe").json["scopes"] == ["original.scope"]


def test_local_and_disabled_targets_cannot_start_consent(auth_environment):
    app, _, _, msal, _, target = auth_environment
    client = signed_in_client(app)
    url = "/api/agents/foundry-auth?id=remote&scope_type=personal&scope_id=actor"
    target["agent_type"] = "local"
    assert client.get(url).status_code == 400
    target["agent_type"] = "new_foundry"
    target["is_enabled"] = False
    assert client.get(url).status_code == 404
    msal.get_authorization_request_url.assert_not_called()


def test_nested_local_parent_preserves_the_foundry_leaf_handoff(auth_environment, runtime, monkeypatch):
    _, _, _, _, _, target = auth_environment
    identity = runtime.contexts.ExecutionIdentity("actor", "conversation")
    frame = runtime.contexts.AgentExecutionFrame(identity, target, runtime.contexts.DelegationBudget(), depth=2)

    async def run():
        with pytest.raises(FoundryAgentUserAuthenticationRequired) as captured:
            await runtime.execute_target(target, "task", "", frame)
        leaf_error = captured.value
        leaf_url = leaf_error.auth_response["auth_url"]

        class LocalParent:
            async def invoke(self, messages):
                raise leaf_error

        monkeypatch.setattr(runtime, "_build_local_agent", lambda *args: (SimpleNamespace(services={}), LocalParent()))
        local_target = {**target, "id": "local-parent", "agent_type": "local"}
        with pytest.raises(FoundryAgentUserAuthenticationRequired) as parent_error:
            await runtime.execute_target(local_target, "task", "", frame)
        assert parent_error.value.auth_response["auth_url"] == leaf_url
        assert parse_qs(urlparse(leaf_url).query)["id"] == ["remote"]

    asyncio.run(run())
