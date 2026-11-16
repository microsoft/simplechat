# test_model_endpoint_app_identity_rule.py
"""
Functional test for the application identity rule on group and personal model endpoints.
Version: 0.261.140
Implemented in: 0.261.140

Group and personal (``user`` scope) model endpoints are configured by
non-administrators. When an endpoint's authentication resolves to the application's
own credential, one rule (``functions_model_endpoint_app_identity``) applies:

- the host must be an Azure AI service host of the configured cloud;
- a stored or request-supplied token audience or authority override is refused;
- a caller-supplied or stored ``managed_identity_client_id`` is not honoured.

It runs at save time (native create and PATCH, the legacy group and personal saves:
a stable 400) and at use time, from the Key Vault hydration every stored
configuration consumer goes through (fetch, test-model, Foundry discovery, chat,
the Semantic Kernel loader, workflows and summaries), where a record stored before
the rule fails closed. Global (admin) endpoints are unchanged.

The real modules run unchanged (``test_support/group_endpoint_harness.py``); the
credential factory, HTTP client, chat client and Foundry listing are recording fakes,
so each refusal can be shown to happen before any application token is requested.
"""

import ast
from pathlib import Path

import pytest

from test_support.group_endpoint_harness import (
    GROUP_A,
    GROUP_B,
    aoai_endpoint,
    foundry_endpoint,
    group_endpoint_environment,
)


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
AZURE_OPENAI_URL = "https://contoso.openai.azure.com"
AZURE_FOUNDRY_URL = "https://contoso.services.ai.azure.com/api/projects/proj"
ATTACKER_URL = "https://attacker.example.com"
ENDPOINT_REFUSED = {
    "error": (
        "The application identity can be used only with an Azure AI endpoint in this cloud. "
        "Use an API key or a service principal for other endpoints."
    ),
    "code": "server_credential_endpoint_refused",
}
OVERRIDE_REFUSED = {
    "error": (
        "The application identity uses this deployment's own token audience and authority. "
        "Remove the Foundry scope, custom authority and custom cloud, or use an API key or a service principal."
    ),
    "code": "server_credential_override_refused",
}
SELECTION_REFUSED = {
    "error": (
        "The application identity is selected by this deployment. "
        "Remove the managed identity client ID, or use an API key or a service principal."
    ),
    "code": "server_credential_identity_refused",
}


def mi_endpoint(endpoint_id, url=AZURE_OPENAI_URL, **auth):
    return aoai_endpoint(endpoint_id, url=url, auth={"type": "managed_identity", **auth})


def mi_foundry(endpoint_id, url=AZURE_FOUNDRY_URL, **auth):
    endpoint = foundry_endpoint(endpoint_id, url=url)
    endpoint["auth"] = {"type": "managed_identity", **auth}
    return endpoint


@pytest.fixture(scope="module")
def module_env():
    with group_endpoint_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    module_env.seed_group(GROUP_A)
    module_env.seed_group(GROUP_B)
    module_env.active_group = GROUP_A
    yield module_env
    module_env.reset()


@pytest.fixture
def rule(env):
    import functions_model_endpoint_app_identity as module
    return module


def seed_legacy(env, group_id, *endpoints):
    """Store records exactly as a save before the rule would have (no rule applied)."""
    env.seed_group(group_id, endpoints=env.legacy_stored_endpoints(group_id, list(endpoints)))


def assert_no_application_token(env):
    assert env.credentials == [] and env.chat_clients == [] and env.http_calls == [] and env.foundry_calls == []


def refusal_logs(env, stage):
    return [
        entry for entry in env.logs
        if entry[0] == "[MODELS] Refused the application identity for a group or personal model endpoint."
        and entry[2].get("stage") == stage
    ]


# --------------------------------------------------------------------------
# The one predicate
# --------------------------------------------------------------------------

@pytest.mark.parametrize("auth,provider,expected", [
    ({"type": "managed_identity"}, "aoai", True),
    ({}, "aoai", True),
    ({"type": "key"}, "aoai", True),
    ({"type": "bearer"}, "aifoundry", True),
    ({"type": "api_key"}, "aoai", False),
    ({"type": "service_principal"}, "aifoundry", False),
    ({"type": "managed_identity"}, "custom", False),
    ({"type": "managed_identity"}, "openai_compatible", False),
])
def test_which_endpoints_use_the_application_identity(rule, auth, provider, expected):
    assert rule.uses_application_identity({"provider": provider, "auth": auth}) is expected


@pytest.mark.parametrize("endpoint,expected", [
    (mi_endpoint("e"), None),
    (mi_foundry("e"), None),
    (mi_endpoint("e", url=ATTACKER_URL), "server_credential_endpoint_refused"),
    (mi_endpoint("e", url="https://contoso.azure-api.net"), "server_credential_endpoint_refused"),
    (mi_foundry("e", foundry_scope="https://management.azure.com/.default"), "server_credential_override_refused"),
    (mi_foundry("e", foundry_scope="https://ai.azure.com/.default"), None),
    (mi_endpoint("e", custom_authority="https://login.attacker.example.com"), "server_credential_override_refused"),
    (mi_endpoint("e", management_cloud="custom"), "server_credential_override_refused"),
    (mi_endpoint("e", management_cloud="public"), None),
    (mi_endpoint("e", managed_identity_client_id="other-identity"), "server_credential_identity_refused"),
    (aoai_endpoint("e", url=ATTACKER_URL, api_key="caller-key"), None),
])
def test_the_predicate(rule, endpoint, expected):
    assert rule.application_identity_violation(endpoint) == expected


def test_a_stored_identity_selection_is_dropped_rather_than_refused_at_use(rule):
    endpoint = mi_endpoint("e", managed_identity_client_id="other-identity")
    assert rule.application_identity_violation(endpoint, include_identity_selection=False) is None
    used = rule.resolve_application_identity_for_use(endpoint, "group")
    assert "managed_identity_client_id" not in used["auth"]
    assert used["auth"]["management_cloud"] == "public"


def test_global_scope_is_never_judged(rule):
    hostile = mi_endpoint("g", url=ATTACKER_URL, foundry_scope="https://management.azure.com/.default")
    assert rule.resolve_application_identity_for_use(hostile, "global") == hostile
    assert rule.check_application_identity_request(hostile, "global") == hostile
    rule.check_application_identity_save(hostile, None, "global")


def _calls(filename, function_name, callee):
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == function_name]
    assert functions, f"{filename} no longer defines {function_name}"
    return [
        node for function in functions for node in ast.walk(function)
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == callee
    ]


def test_every_enforcement_point_uses_the_one_module():
    assert _calls("route_backend_models.py", "resolve_request_endpoint_payload", "check_application_identity_request")
    assert _calls("route_backend_models.py", "save_scoped_endpoint_secrets", "check_application_identity_save")
    assert _calls("functions_group_endpoint_access.py", "_write_endpoint_change", "check_application_identity_save")
    assert _calls("functions_keyvault.py", "keyvault_model_endpoint_get_helper", "resolve_application_identity_for_use")
    # Nothing else re-implements the host check.
    for path in APP_DIR.glob("*.py"):
        if path.name in ("functions_model_endpoint_app_identity.py", "functions_azure_endpoint_validation.py"):
            continue
        assert "validate_azure_ai_endpoint_host" not in path.read_text(encoding="utf-8"), path.name


@pytest.mark.parametrize("filename,function_name", [
    ("semantic_kernel_loader.py", "resolve_multi_endpoint_agent_binding"),
    ("semantic_kernel_loader.py", "resolve_foundry_endpoint_config"),
    ("route_backend_chats.py", "resolve_streaming_multi_endpoint_gpt_config"),
    ("route_backend_conversation_export.py", "_resolve_summary_multi_endpoint_client"),
    ("functions_workflow_runner.py", "_build_multi_endpoint_client"),
    ("functions_model_endpoint_runtime.py", "resolve_model_endpoint_from_context"),
])
def test_runtime_consumers_hydrate_group_and_user_endpoints_under_their_own_scope(filename, function_name):
    """The use-time rule lives in the VALUE hydration step, so every runtime consumer of
    a group or user endpoint must hydrate it under its stored scope, never as global."""
    hydrations = _calls(filename, function_name, "keyvault_model_endpoint_get_helper")
    assert hydrations, f"{filename}:{function_name} no longer hydrates model endpoints"
    for call in hydrations:
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        assert isinstance(keywords.get("scope"), ast.Name), (
            f"{filename}:{function_name} hydrates under a fixed scope, which bypasses the group and user rule"
        )
        assert ast.unparse(keywords.get("return_type")) == "SecretReturnType.VALUE"


# --------------------------------------------------------------------------
# (a) Save time
# --------------------------------------------------------------------------

@pytest.mark.parametrize("endpoint,expected", [
    (mi_endpoint("", url=ATTACKER_URL), ENDPOINT_REFUSED),
    (mi_foundry("", foundry_scope="https://management.azure.com/.default"), OVERRIDE_REFUSED),
    (mi_endpoint("", custom_authority="https://login.attacker.example.com"), OVERRIDE_REFUSED),
    (mi_endpoint("", managed_identity_client_id="other-identity"), SELECTION_REFUSED),
])
def test_native_create_refuses_a_breach(env, endpoint, expected):
    endpoint.pop("id")
    response = env.call("POST", f"/api/groups/{GROUP_A}/model-endpoints", endpoint)
    assert response.status_code == 400
    assert response.get_json() == expected
    assert env.write_calls() == [] and env.vault.writes == []
    assert refusal_logs(env, "save")


def test_native_create_allows_an_azure_ai_host(env):
    endpoint = mi_endpoint("")
    endpoint.pop("id")
    response = env.call("POST", f"/api/groups/{GROUP_A}/model-endpoints", endpoint)
    assert response.status_code == 201, response.get_json()


def test_native_patch_refuses_a_change_that_breaches(env):
    seed_legacy(env, GROUP_A, aoai_endpoint("keyed", api_key="caller-key"), mi_endpoint("mi"))
    for endpoint_id, change in (
        ("mi", {"connection": {"endpoint": ATTACKER_URL}}),
        ("keyed", {"connection": {"endpoint": ATTACKER_URL}, "auth": {"type": "managed_identity"}}),
        ("mi", {"auth": {"managed_identity_client_id": "other-identity"}}),
    ):
        revision = env.revision_of(GROUP_A, endpoint_id)
        response = env.call("PATCH", f"/api/groups/{GROUP_A}/model-endpoints/{endpoint_id}", {**change, "expected_revision": revision})
        assert response.status_code == 400, (endpoint_id, response.get_json())
        assert response.get_json()["code"].startswith("server_credential_")
    assert env.write_calls() == []


def test_a_legacy_record_stored_before_the_rule_blocks_no_unrelated_edit(env):
    seed_legacy(env, GROUP_A, mi_endpoint("hostile", url=ATTACKER_URL), aoai_endpoint("keyed", api_key="caller-key"))
    revision = env.revision_of(GROUP_A, "keyed")
    edited = env.call("PATCH", f"/api/groups/{GROUP_A}/model-endpoints/keyed", {"name": "Edited", "expected_revision": revision})
    assert edited.status_code == 200, edited.get_json()
    renamed = env.call("PATCH", f"/api/groups/{GROUP_A}/model-endpoints/hostile", {
        "name": "Renamed", "expected_revision": env.revision_of(GROUP_A, "hostile"),
    })
    assert renamed.status_code == 200, renamed.get_json()
    # It is still unusable.
    tested = env.call("POST", f"/api/groups/{GROUP_A}/models/test-model", {"endpoint_id": "hostile", "model": {"id": "chat"}})
    assert tested.status_code == 400 and tested.get_json() == ENDPOINT_REFUSED


def test_the_legacy_group_post_refuses_a_breach(env):
    response = env.call("POST", "/api/group/model-endpoints", {"endpoints": [mi_endpoint("mi-new", url=ATTACKER_URL)]})
    assert response.status_code == 400
    assert response.get_json() == ENDPOINT_REFUSED
    assert [call for call in env.groups.calls if call[0] == "upsert_item"] == []


def test_the_legacy_group_post_resaves_an_unchanged_legacy_record(env):
    seed_legacy(env, GROUP_A, mi_endpoint("hostile", url=ATTACKER_URL))
    listing = env.client.get("/api/group/model-endpoints").get_json()["endpoints"]
    response = env.call("POST", "/api/group/model-endpoints", {"endpoints": listing})
    assert response.status_code == 200, response.get_json()


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/api/user/model-endpoints", mi_endpoint("pe-new", url=ATTACKER_URL)),
    ("POST", "/api/user/model-endpoints", {"endpoints": [mi_endpoint("pe-new", url=ATTACKER_URL)]}),
    ("PATCH", "/api/user/model-endpoints/pe-own", {"connection": {"endpoint": ATTACKER_URL}}),
    ("PATCH", "/api/user/model-endpoints/pe-own", {"auth": {"foundry_scope": "https://management.azure.com/.default"}}),
    ("PATCH", "/api/user/model-endpoints/pe-own", {"auth": {"managed_identity_client_id": "other-identity"}}),
])
def test_the_personal_saves_refuse_a_breach(env, method, path, body):
    env.seed_personal_endpoints("owner", [mi_endpoint("pe-own")])
    response = env.call(method, path, body)
    assert response.status_code == 400
    assert response.get_json()["code"].startswith("server_credential_")
    assert env.personal_endpoint("owner", "pe-own")["connection"]["endpoint"] == AZURE_OPENAI_URL
    assert env.personal_endpoint("owner", "pe-new") is None


# --------------------------------------------------------------------------
# (b) Use time: records stored before the rule fail closed
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path,body", [
    (f"/api/groups/{GROUP_A}/models/test-model", {"endpoint_id": "hostile", "model": {"id": "chat"}}),
    (f"/api/groups/{GROUP_A}/models/fetch", {"endpoint_id": "hostile-foundry"}),
    ("/api/group/models/test-model", {"endpoint_id": "hostile", "model": {"id": "chat"}}),
    ("/api/group/models/fetch", {"endpoint_id": "hostile-foundry"}),
    (f"/api/groups/{GROUP_A}/models/foundry/agents", {"endpoint_id": "hostile-foundry"}),
    ("/api/models/foundry/agents", {"endpoint_id": "hostile-foundry", "scope": "group"}),
])
def test_a_legacy_record_fails_closed_on_every_group_use(env, path, body):
    seed_legacy(env, GROUP_A, mi_endpoint("hostile", url=ATTACKER_URL), mi_foundry("hostile-foundry", url=f"{ATTACKER_URL}/api/projects/p"))
    response = env.call("POST", path, body)
    assert response.status_code == 400, response.get_json()
    assert response.get_json() == ENDPOINT_REFUSED
    assert_no_application_token(env)
    assert refusal_logs(env, "use")


def test_a_stored_audience_override_fails_closed(env):
    seed_legacy(env, GROUP_A, mi_foundry("steered", foundry_scope="https://management.azure.com/.default"))
    response = env.call("POST", f"/api/groups/{GROUP_A}/models/fetch", {"endpoint_id": "steered"})
    assert response.status_code == 400
    assert response.get_json() == OVERRIDE_REFUSED
    assert_no_application_token(env)


def test_a_legacy_personal_record_fails_closed(env):
    env.seed_personal_endpoints("owner", [mi_endpoint("pe-hostile", url=ATTACKER_URL)])
    response = env.call("POST", "/api/user/models/test-model", {"endpoint_id": "pe-hostile", "model": {"id": "chat"}})
    assert response.status_code == 400
    assert response.get_json() == ENDPOINT_REFUSED
    assert_no_application_token(env)


def test_a_stored_identity_selection_is_not_honoured(env):
    seed_legacy(env, GROUP_A, mi_endpoint("selected", managed_identity_client_id="other-identity"))
    response = env.call("POST", f"/api/groups/{GROUP_A}/models/test-model", {"endpoint_id": "selected", "model": {"id": "chat"}})
    assert response.status_code == 200, response.get_json()
    [client] = env.chat_clients
    assert "managed_identity_client_id" not in client["auth"]
    assert client["endpoint"] == AZURE_OPENAI_URL


def test_a_compliant_stored_record_still_works(env):
    seed_legacy(env, GROUP_A, mi_foundry("compliant"))
    response = env.call("POST", f"/api/groups/{GROUP_A}/models/fetch", {"endpoint_id": "compliant"})
    assert response.status_code == 200, response.get_json()
    assert env.credentials[0]["scope"] == "https://ai.azure.com/.default"


def test_the_hydration_chokepoint_fails_closed_even_with_key_vault_off(env, rule):
    keyvault = env.modules.keyvault
    hostile = mi_endpoint("hostile", url=ATTACKER_URL)
    for key_vault_on in (True, False):
        env.settings["enable_key_vault_secret_storage"] = key_vault_on
        for scope in ("group", "user"):
            with pytest.raises(rule.ApplicationIdentityPolicyError) as refused:
                keyvault.keyvault_model_endpoint_get_helper(hostile, "hostile", scope=scope, return_type=keyvault.SecretReturnType.VALUE)
            assert refused.value.code == "server_credential_endpoint_refused"
    # Projections for the browser and global endpoints are untouched.
    assert keyvault.keyvault_model_endpoint_get_helper(hostile, "hostile", scope="group", return_type=keyvault.SecretReturnType.TRIGGER) == hostile
    assert keyvault.keyvault_model_endpoint_get_helper(hostile, "hostile", scope="global", return_type=keyvault.SecretReturnType.VALUE) == hostile


# --------------------------------------------------------------------------
# Global endpoints are unchanged
# --------------------------------------------------------------------------

def test_a_global_endpoint_reached_through_a_group_route_is_hydrated_as_global(env):
    normalized, _ = env.modules.settings.normalize_model_endpoints([mi_endpoint("g-mi", url="https://contoso-gateway.azure-api.net")])
    env.settings["model_endpoints"] = normalized
    response = env.call("POST", f"/api/groups/{GROUP_B}/models/test-model", {"endpoint_id": "g-mi", "model": {"id": "chat"}})
    assert response.status_code == 200, response.get_json()
    assert env.chat_clients[0]["endpoint"] == "https://contoso-gateway.azure-api.net"


def test_the_admin_routes_are_unchanged(env):
    normalized, _ = env.modules.settings.normalize_model_endpoints([mi_endpoint("g-mi", url=ATTACKER_URL)])
    env.settings["model_endpoints"] = normalized
    env.as_user("owner", roles=("User", "Admin"))
    response = env.call("POST", "/api/models/test-model", {"endpoint_id": "g-mi", "model": {"id": "chat"}})
    assert response.status_code == 200, response.get_json()
    assert env.chat_clients[0]["endpoint"] == ATTACKER_URL


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
