# test_model_endpoint_secret_reference_hardening.py
"""
Functional test for endpoint-keyed model endpoint secret references.
Version: 0.261.140
Implemented in: 0.261.140

Group and user model endpoint secrets are named ``{endpoint_id}--model-endpoint--
{scope}--...``, with no group or user id. Before this change the save helper
accepted any client-supplied reference that matched that context and wrote new
plaintext under the deterministic ``model-endpoint-<field>`` name. So the Owner
of any group who learned another group's endpoint id could:

- inject: create an endpoint with the same id whose ``auth.api_key`` is the
  victim's reference, so test-model, fetch and the runtime hydrate the victim's key
  and send it to the attacker's URL;
- overwrite: create the same id with a plaintext key, stored under the victim's
  deterministic name, replacing the victim's key.

The real ``functions_keyvault`` helper and the real legacy routes run unchanged
(``test_support/group_endpoint_harness.py``), with Key Vault enabled in the
settings the helpers read, so every assertion observes a real vault write, read or
delete by exact name. It pins that in the ``group`` and ``user`` scopes a reference
is accepted only when it is the endpoint's own stored one and new values get fresh
staged names; that both legacy callers answer a refusal with a stable 400; that
the classic round trip is unchanged; that the runtime resolves the fresh names;
that superseded names are cleaned up; and that global callers are unchanged.
"""

import re

import pytest

from test_support.group_endpoint_harness import (
    GROUP_A,
    GROUP_B,
    aoai_endpoint,
    group_endpoint_environment,
)


REFUSED = {"error": "A model endpoint credential could not be saved. Re-enter the secret value and try again."}


def deterministic(endpoint_id, scope="group"):
    return f"{endpoint_id}--model-endpoint--{scope}--model-endpoint-api-key"


def staged_pattern(endpoint_id, scope="group"):
    return re.compile(rf"^{re.escape(endpoint_id)}--model-endpoint--{scope}--s-[0-9a-f]{{16,}}$")


@pytest.fixture(scope="module")
def module_env():
    with group_endpoint_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    # The victim group A holds a V1-created endpoint under the deterministic name;
    # the attacker owns group B, which is the attacker's active group.
    module_env.seed_group_with_legacy_endpoints(GROUP_A, [aoai_endpoint("ep-a", api_key="victim-key")])
    module_env.seed_group_with_legacy_endpoints(GROUP_B, [aoai_endpoint("ep-b", url="https://group-b.openai.azure.com", api_key="own-key")])
    module_env.active_group = GROUP_B
    module_env.vault.writes.clear()
    yield module_env
    module_env.reset()


def legacy_group_save(env, endpoints):
    return env.call("POST", "/api/group/model-endpoints", {"endpoints": endpoints})


def classic_copy(env, group_id, endpoint_id):
    """What the classic interface sends back: the sanitized endpoint, no secrets."""
    listing = env.client.get(f"/api/groups/{group_id}/model-endpoints").get_json()["endpoints"]
    endpoint = next(item for item in listing if item["id"] == endpoint_id)
    return {key: value for key, value in endpoint.items() if key not in ("revision", "endpoint_actions")}


# --------------------------------------------------------------------------
# The helper itself
# --------------------------------------------------------------------------

@pytest.mark.parametrize("scope", ["group", "user"])
def test_a_reference_that_is_not_the_endpoints_own_is_refused(env, scope):
    helper = env.modules.keyvault.keyvault_model_endpoint_save_helper
    foreign = deterministic("ep-a", scope)
    # The foreign name matches the context the old check compared: same id, scope, source.
    assert env.modules.keyvault.secret_reference_matches_context(
        foreign, scope_value="ep-a", scope=scope, allowed_sources={"model-endpoint"},
    )
    with pytest.raises(ValueError):
        helper({"id": "ep-a", "auth": {"type": "api_key", "api_key": foreign}}, "ep-a", scope=scope)
    with pytest.raises(ValueError):
        helper(
            {"id": "ep-a", "auth": {"type": "api_key", "api_key": foreign}}, "ep-a", scope=scope,
            existing_endpoint={"id": "ep-a", "auth": {"type": "api_key", "api_key": f"{foreign}-other"}},
        )
    assert env.vault.writes == []


@pytest.mark.parametrize("scope", ["group", "user"])
def test_the_endpoints_own_stored_reference_is_kept(env, scope):
    helper = env.modules.keyvault.keyvault_model_endpoint_save_helper
    own = deterministic("ep-a", scope)
    stored = {"id": "ep-a", "auth": {"type": "api_key", "api_key": own}}
    kept = helper(dict(stored), "ep-a", scope=scope, existing_endpoint=stored)
    assert kept["auth"]["api_key"] == own
    assert env.vault.writes == []


@pytest.mark.parametrize("scope", ["group", "user"])
def test_a_new_value_always_gets_a_fresh_staged_name(env, scope):
    helper = env.modules.keyvault.keyvault_model_endpoint_save_helper
    first = helper({"id": "ep-new", "auth": {"type": "api_key", "api_key": "one"}}, "ep-new", scope=scope)
    second = helper({"id": "ep-new", "auth": {"type": "api_key", "api_key": "two"}}, "ep-new", scope=scope)
    names = [name for name, _value in env.vault.writes]
    assert len(names) == 2 and names[0] != names[1]
    assert all(staged_pattern("ep-new", scope).match(name) for name in names)
    assert deterministic("ep-new", scope) not in names
    assert first["auth"]["api_key"] == names[0] and second["auth"]["api_key"] == names[1]


def test_global_callers_are_unchanged(env):
    helper = env.modules.keyvault.keyvault_model_endpoint_save_helper
    saved = helper({"id": "g1", "auth": {"type": "api_key", "api_key": "global-key"}}, "g1", scope="global")
    assert saved["auth"]["api_key"] == deterministic("g1", "global")
    borrowed = helper(
        {"id": "g1", "auth": {"type": "api_key", "api_key": deterministic("g1", "global")}}, "g1", scope="global",
    )
    assert borrowed["auth"]["api_key"] == deterministic("g1", "global")
    staged = helper({"id": "g1", "auth": {"type": "api_key", "api_key": "k"}}, "g1", scope="global", stage_new_secrets=True)
    assert staged_pattern("g1", "global").match(staged["auth"]["api_key"])


def test_a_foreign_reference_is_refused_even_with_key_vault_off(env):
    env.settings["enable_key_vault_secret_storage"] = False
    helper = env.modules.keyvault.keyvault_model_endpoint_save_helper
    with pytest.raises(ValueError):
        helper({"id": "ep-a", "auth": {"type": "api_key", "api_key": deterministic("ep-a")}}, "ep-a", scope="group")
    inline = helper({"id": "ep-a", "auth": {"type": "api_key", "api_key": "plain"}}, "ep-a", scope="group")
    assert inline["auth"]["api_key"] == "plain"


# --------------------------------------------------------------------------
# The legacy group POST (/api/group/model-endpoints)
# --------------------------------------------------------------------------

def test_injection_is_refused_on_the_legacy_group_post(env):
    response = legacy_group_save(env, [
        classic_copy(env, GROUP_B, "ep-b"),
        {**aoai_endpoint("ep-a", url="https://attacker.example.com", api_key=deterministic("ep-a")), "name": "Borrowed"},
    ])
    assert response.status_code == 400
    assert response.get_json() == REFUSED
    assert [call for call in env.groups.calls if call[0] in ("upsert_item", "replace_item")] == []
    assert env.vault.secrets[deterministic("ep-a")] == "victim-key"
    assert env.vault.deletes == []


def test_plaintext_on_a_colliding_id_leaves_the_other_groups_secret_untouched(env):
    response = legacy_group_save(env, [
        classic_copy(env, GROUP_B, "ep-b"),
        aoai_endpoint("ep-a", url="https://attacker.example.com", api_key="attacker-key"),
    ])
    assert response.status_code == 200
    [(name, value)] = env.vault.writes
    assert staged_pattern("ep-a").match(name) and value == "attacker-key"
    assert env.vault.secrets[deterministic("ep-a")] == "victim-key"
    assert deterministic("ep-a") not in env.vault.deletes
    assert env.stored_endpoint(GROUP_B, "ep-a")["auth"]["api_key"] == name
    assert env.stored_endpoint(GROUP_A, "ep-a")["auth"]["api_key"] == deterministic("ep-a")


def test_the_classic_round_trip_is_unchanged_on_the_legacy_group_post(env):
    own = deterministic("ep-b")
    # A blank or missing key keeps the stored value.
    blank = classic_copy(env, GROUP_B, "ep-b")
    blank["auth"]["api_key"] = ""
    assert legacy_group_save(env, [blank]).status_code == 200
    missing = classic_copy(env, GROUP_B, "ep-b")
    assert "api_key" not in missing["auth"]
    assert legacy_group_save(env, [missing]).status_code == 200
    assert env.stored_endpoint(GROUP_B, "ep-b")["auth"]["api_key"] == own
    # Re-sending the endpoint's own stored reference is accepted.
    resent = classic_copy(env, GROUP_B, "ep-b")
    resent["auth"]["api_key"] = own
    assert legacy_group_save(env, [resent]).status_code == 200
    assert env.vault.writes == [] and env.vault.deletes == []
    # Plaintext replaces it under a fresh name, and the superseded name is removed.
    rotated = classic_copy(env, GROUP_B, "ep-b")
    rotated["auth"]["api_key"] = "rotated-key"
    assert legacy_group_save(env, [rotated]).status_code == 200
    [(name, value)] = env.vault.writes
    assert staged_pattern("ep-b").match(name) and value == "rotated-key"
    assert env.stored_endpoint(GROUP_B, "ep-b")["auth"]["api_key"] == name
    assert env.vault.deletes == [own]


def test_a_refused_save_removes_what_it_staged_for_earlier_endpoints(env):
    response = legacy_group_save(env, [
        aoai_endpoint("ep-first", api_key="first-key"),
        aoai_endpoint("ep-a", api_key=deterministic("ep-a")),
    ])
    assert response.status_code == 400
    [(name, _value)] = env.vault.writes
    assert staged_pattern("ep-first").match(name)
    assert env.vault.deletes == [name]
    assert env.vault.secrets[deterministic("ep-a")] == "victim-key"


def test_the_runtime_resolves_the_fresh_names(env):
    rotated = classic_copy(env, GROUP_B, "ep-b")
    rotated["auth"]["api_key"] = "rotated-key"
    assert legacy_group_save(env, [rotated]).status_code == 200
    stored = env.stored_endpoint(GROUP_B, "ep-b")
    assert staged_pattern("ep-b").match(stored["auth"]["api_key"])
    hydrated = env.modules.keyvault.keyvault_model_endpoint_get_helper(
        stored, "ep-b", scope="group", return_type=env.modules.keyvault.SecretReturnType.VALUE,
    )
    assert hydrated["auth"]["api_key"] == "rotated-key"
    for path in ("/api/group/models/test-model", f"/api/groups/{GROUP_B}/models/test-model"):
        env.chat_clients.clear()
        response = env.call("POST", path, {"endpoint_id": "ep-b", "model": {"id": "chat"}})
        assert response.status_code == 200, (path, response.get_json())
        assert [client["auth"]["api_key"] for client in env.chat_clients] == ["rotated-key"]


def test_injection_is_refused_on_the_native_create(env):
    response = env.call("POST", f"/api/groups/{GROUP_B}/model-endpoints", {
        **aoai_endpoint("ep-a", url="https://attacker.example.com", api_key=deterministic("ep-a")),
    })
    assert response.status_code == 400
    assert env.vault.writes == [] and env.vault.secrets[deterministic("ep-a")] == "victim-key"


# --------------------------------------------------------------------------
# The personal routes (/api/user/model-endpoints)
# --------------------------------------------------------------------------

@pytest.fixture
def personal(env):
    env.seed_personal_endpoints("victim", [aoai_endpoint("pe-1", api_key="victim-personal-key")])
    env.seed_personal_endpoints("owner", [aoai_endpoint("pe-own", api_key="own-personal-key")])
    env.vault.writes.clear()
    return env


def test_injection_is_refused_on_the_personal_create_and_collection_post(personal):
    foreign = deterministic("pe-1", "user")
    single = personal.call("POST", "/api/user/model-endpoints", aoai_endpoint("pe-1", api_key=foreign))
    assert single.status_code == 400 and single.get_json() == REFUSED
    collection = personal.call("POST", "/api/user/model-endpoints", {
        "endpoints": [aoai_endpoint("pe-own", api_key=""), aoai_endpoint("pe-1", api_key=foreign)],
    })
    assert collection.status_code == 400 and collection.get_json() == REFUSED
    assert personal.personal_endpoint("owner", "pe-1") is None
    assert personal.vault.secrets[foreign] == "victim-personal-key"


def test_injection_is_refused_on_the_personal_patch(personal):
    foreign = deterministic("pe-1", "user")
    response = personal.call("PATCH", "/api/user/model-endpoints/pe-own", {"auth": {"api_key": foreign}})
    assert response.status_code == 400 and response.get_json() == REFUSED
    assert personal.personal_endpoint("owner", "pe-own")["auth"]["api_key"] == deterministic("pe-own", "user")


def test_the_classic_round_trip_is_unchanged_on_the_personal_routes(personal):
    own = deterministic("pe-own", "user")
    assert personal.call("PATCH", "/api/user/model-endpoints/pe-own", {"name": "Renamed"}).status_code == 200
    assert personal.call("PATCH", "/api/user/model-endpoints/pe-own", {"auth": {"api_key": own}}).status_code == 200
    assert personal.personal_endpoint("owner", "pe-own")["auth"]["api_key"] == own
    assert personal.vault.writes == [] and personal.vault.deletes == []
    rotated = personal.call("PATCH", "/api/user/model-endpoints/pe-own", {"auth": {"api_key": "rotated"}})
    assert rotated.status_code == 200
    [(name, value)] = personal.vault.writes
    assert staged_pattern("pe-own", "user").match(name) and value == "rotated"
    assert personal.personal_endpoint("owner", "pe-own")["auth"]["api_key"] == name
    assert personal.vault.deletes == [own]
    # Deleting the endpoint removes its fresh name too.
    assert personal.call("DELETE", "/api/user/model-endpoints/pe-own").status_code == 200
    assert personal.vault.deletes == [own, name]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
