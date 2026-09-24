# test_group_agent_apis.py
"""
Functional tests for the immutable-target group agent APIs.
Version: 0.261.157
Implemented in: 0.261.138
Backend harness extracted to test_support/group_agent_harness.py: 0.261.157

The real policy, access, projection and route modules run against the real
personal-editor authoring engine (``functions_workspace_authoring``), executed
unchanged over an in-memory Cosmos stub that honours ETag conditional writes.
Group membership, status and settings are local test seams; the group is always
taken from the path, so a stale active group can never redirect or widen a
request. Key Vault storage is disabled, so no live secret backend is required,
and network access is prohibited.
"""

import importlib.util
import itertools

import pytest

from test_support.agent_delegation import APP_ROOT, execute_functions
from test_support.group_agent_harness import (  # noqa: F401  (environment is a pytest fixture)
    KNOWLEDGE_PATH,
    LIST_PATH,
    MASK,
    NON_WRITER_ROLES,
    OPTIONS_PATH,
    READER_ROLES,
    ROLE_USER,
    WRITER_ROLES,
    as_user,
    create_body,
    environment,
    seed_agent,
    write_body,
)
from test_support.versioning import assert_app_version_at_least


def _load_real_submission_predicate():
    """Load only the real agent-template submission predicate, no heavy imports."""
    namespace = {}
    execute_functions(
        "functions_agent_templates.py",
        {"agent_template_submission_decision"},
        namespace,
    )
    return namespace["agent_template_submission_decision"]




# --------------------------------------------------------------------------
# Versioning
# --------------------------------------------------------------------------

def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.138")


# --------------------------------------------------------------------------
# Reads: role and status
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", READER_ROLES)
def test_every_member_role_can_list_and_read(environment, role):
    seed_agent(environment.group_container, "a1")
    as_user(environment, ROLE_USER[role])
    listing = environment.client.get(LIST_PATH)
    assert listing.status_code == 200
    body = listing.get_json()
    assert [item["id"] for item in body["agents"]] == ["a1"]
    single = environment.client.get(f"{LIST_PATH}/a1")
    assert single.status_code == 200
    assert single.get_json()["record"]["id"] == "a1"


def test_list_envelope_and_single_resource_shape(environment):
    seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    body = environment.client.get(LIST_PATH).get_json()
    assert set(body) == {"agents"}
    item = body["agents"][0]
    assert item["id"] == "a1" and item["group_id"] == "group-a" and item["is_group"] is True
    assert "_rid" not in item and "_etag" not in item
    single = environment.client.get(f"{LIST_PATH}/a1").get_json()
    assert set(single) == {"record", "revision", "secret_paths", "read_only"}
    assert single["record"]["id"] == "a1"
    assert single["revision"]


def test_unknown_group_is_404_and_unknown_agent_is_404(environment):
    as_user(environment, "owner")
    assert environment.client.get("/api/groups/no-such-group/agents").status_code == 404
    assert environment.client.get(f"{LIST_PATH}/ghost").status_code == 404


@pytest.mark.parametrize("group_id", ["locked-grp", "upload-disabled-grp"])
def test_read_only_statuses_are_readable(environment, group_id):
    environment.groups[group_id]  # ensure fixture present
    seed_agent(environment.group_container, "a1", group_id=group_id)
    as_user(environment, "owner")
    listing = environment.client.get(f"/api/groups/{group_id}/agents")
    assert listing.status_code == 200
    single = environment.client.get(f"/api/groups/{group_id}/agents/a1")
    assert single.status_code == 200
    # A read-only status advertises no management operations and marks read-only,
    # but chat (a catalogue property, not an edit right) remains.
    assert single.get_json()["record"]["agent_actions"] == ["chat"]
    assert single.get_json()["read_only"] is True


@pytest.mark.parametrize("group_id", ["inactive-grp", "haunted-grp"])
def test_inactive_and_unknown_statuses_are_denied(environment, group_id):
    seed_agent(environment.group_container, "a1", group_id=group_id)
    as_user(environment, "owner")
    assert environment.client.get(f"/api/groups/{group_id}/agents").status_code == 403
    assert environment.client.get(f"/api/groups/{group_id}/agents/a1").status_code == 403


# --------------------------------------------------------------------------
# Per-item action hints (edit/delete/chat)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", WRITER_ROLES)
def test_writers_see_edit_delete_chat_in_active_group(environment, role):
    seed_agent(environment.group_container, "a1")
    as_user(environment, ROLE_USER[role])
    item = environment.client.get(LIST_PATH).get_json()["agents"][0]
    assert item["agent_actions"] == ["edit", "delete", "chat"]


@pytest.mark.parametrize("role", NON_WRITER_ROLES)
def test_non_writers_see_only_chat(environment, role):
    # chat is a catalogue property independent of edit rights, so every member
    # who may use group agents in chat sees it; non-writers get nothing more.
    seed_agent(environment.group_container, "a1")
    as_user(environment, ROLE_USER[role])
    item = environment.client.get(LIST_PATH).get_json()["agents"][0]
    assert item["agent_actions"] == ["chat"]


def test_chat_hint_disappears_when_governance_denies_it(environment):
    seed_agent(environment.group_container, "a1")
    # Governance now denies group agents for this user: no availability, no chat.
    environment.governance.is_governance_access_allowed.return_value = False
    as_user(environment, "owner")
    # The whole surface is unavailable, so the list itself is refused.
    assert environment.client.get(LIST_PATH).status_code == 403


# --------------------------------------------------------------------------
# Writes: role policy
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", WRITER_ROLES)
def test_writer_roles_can_create(environment, role):
    as_user(environment, ROLE_USER[role])
    response = environment.client.post(LIST_PATH, json=create_body(name="created-by-writer"))
    assert response.status_code == 201
    body = response.get_json()
    assert body["record"]["name"] == "created-by-writer"
    assert body["record"]["is_group"] is True
    assert body["read_only"] is False


@pytest.mark.parametrize("role", NON_WRITER_ROLES)
def test_non_writer_roles_cannot_create_edit_or_delete(environment, role):
    seed = seed_agent(environment.group_container, "a1")
    as_user(environment, ROLE_USER[role])
    create = environment.client.post(LIST_PATH, json=create_body(name="x"))
    assert create.status_code == 403
    update = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(
        seed["_etag"], description="changed",
    ))
    assert update.status_code == 403
    delete = environment.client.delete(f"{LIST_PATH}/a1")
    assert delete.status_code == 403
    # Nothing was written.
    assert environment.group_container.records[("group-a", "a1")]["description"] == "A shared agent."


def test_owner_only_setting_refuses_admin_writes(environment):
    environment.settings["require_owner_for_group_agent_management"] = True
    seed_agent(environment.group_container, "a1")
    as_user(environment, "admin")
    assert environment.client.post(LIST_PATH, json=create_body(name="x")).status_code == 403
    as_user(environment, "owner")
    assert environment.client.post(LIST_PATH, json=create_body(name="owner-write")).status_code == 201


# --------------------------------------------------------------------------
# Writes: status policy
# --------------------------------------------------------------------------

@pytest.mark.parametrize("group_id", ["locked-grp", "upload-disabled-grp", "inactive-grp"])
def test_writes_are_refused_outside_active_status(environment, group_id):
    seed = seed_agent(environment.group_container, "a1", group_id=group_id)
    as_user(environment, "owner")
    path = f"/api/groups/{group_id}/agents"
    assert environment.client.post(path, json=create_body(name="x")).status_code == 403
    update = environment.client.patch(f"{path}/a1", json=write_body(seed["_etag"], description="y"))
    assert update.status_code == 403
    assert environment.client.delete(f"{path}/a1").status_code == 403


# --------------------------------------------------------------------------
# Conditional writes and DELETE shape
# --------------------------------------------------------------------------

def test_update_requires_expected_revision(environment):
    seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json={"updates": {"description": "changed"}})
    assert response.status_code == 400


def test_update_with_stale_revision_conflicts_and_writes_nothing(environment):
    seed = seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    stale = seed["_etag"]
    first = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(stale, description="first"))
    assert first.status_code == 200
    conflict = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(stale, description="second"))
    assert conflict.status_code == 409
    assert environment.group_container.records[("group-a", "a1")]["description"] == "first"


def test_update_success_returns_new_revision_and_persists(environment):
    seed = seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(
        seed["_etag"], description="updated body",
    ))
    assert response.status_code == 200
    body = response.get_json()
    assert body["record"]["description"] == "updated body"
    assert body["revision"] != seed["_etag"]


def test_delete_takes_no_body_or_revision_and_removes_the_record(environment):
    seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.delete(f"{LIST_PATH}/a1")
    assert response.status_code == 200
    assert response.get_json() == {"success": True}
    assert ("group-a", "a1") not in environment.group_container.records


def test_create_requires_a_client_allocated_uuid(environment):
    as_user(environment, "owner")
    bad = environment.client.post(LIST_PATH, json={"updates": {"name": "no-id", "id": "not-a-uuid"}})
    assert bad.status_code == 400
    missing = environment.client.post(LIST_PATH, json={"updates": {"name": "no-id"}})
    assert missing.status_code == 400


# --------------------------------------------------------------------------
# Secret rules (mask keeps stored value, clear removes it)
# --------------------------------------------------------------------------

def test_stored_secret_is_masked_in_projection(environment):
    seed_agent(environment.group_container, "a1", azure_openai_gpt_key="sk-live-123")
    as_user(environment, "owner")
    record = environment.client.get(f"{LIST_PATH}/a1").get_json()
    assert record["record"]["azure_openai_gpt_key"] == MASK
    assert "/azure_openai_gpt_key" in record["secret_paths"]


def test_mask_preserves_stored_secret_on_update(environment):
    # A V1-created agent with a stored key is edited in V2 without re-entering the
    # key: sending the mask keeps the stored value (§2.1 round trip, edit half).
    seed = seed_agent(environment.group_container, "a1", azure_openai_gpt_key="sk-live-123")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(
        seed["_etag"], description="renamed", azure_openai_gpt_key=MASK,
    ))
    assert response.status_code == 200
    assert environment.group_container.records[("group-a", "a1")]["azure_openai_gpt_key"] == "sk-live-123"
    assert environment.group_container.records[("group-a", "a1")]["description"] == "renamed"


def test_clear_secret_paths_removes_the_stored_secret(environment):
    seed = seed_agent(environment.group_container, "a1", azure_openai_gpt_key="sk-live-123")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json={
        "updates": {}, "expected_revision": seed["_etag"], "clear_secret_paths": ["/azure_openai_gpt_key"],
    })
    assert response.status_code == 200
    assert "azure_openai_gpt_key" not in environment.group_container.records[("group-a", "a1")]


def test_editor_cannot_supply_a_secret_reference(environment):
    seed = seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(
        seed["_etag"], azure_openai_gpt_key="https://vault.vault.azure.net/secrets/smuggled",
    ))
    assert response.status_code == 400


# --------------------------------------------------------------------------
# §2.2 cache bump on save and delete
# --------------------------------------------------------------------------

def test_save_and_delete_bump_the_bootstrap_cache(environment):
    as_user(environment, "owner")
    assert environment.cache.global_bumps == []
    created = environment.client.post(LIST_PATH, json=create_body(name="cache-agent"))
    assert created.status_code == 201
    assert len(environment.cache.global_bumps) == 1
    agent_id = created.get_json()["record"]["id"]
    revision = created.get_json()["revision"]
    updated = environment.client.patch(f"{LIST_PATH}/{agent_id}", json=write_body(revision, description="c"))
    assert updated.status_code == 200
    assert len(environment.cache.global_bumps) == 2
    deleted = environment.client.delete(f"{LIST_PATH}/{agent_id}")
    assert deleted.status_code == 200
    assert len(environment.cache.global_bumps) == 3


# --------------------------------------------------------------------------
# Transport hygiene: query parameters and request bodies
# --------------------------------------------------------------------------

def test_list_rejects_query_parameters(environment):
    seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    assert environment.client.get(f"{LIST_PATH}?scope=global").status_code == 400


def test_delete_rejects_expected_revision_as_a_query_parameter(environment):
    seed = seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.delete(f"{LIST_PATH}/a1?expected_revision={seed['_etag']}")
    assert response.status_code == 400
    assert ("group-a", "a1") in environment.group_container.records


def test_read_rejects_a_request_body(environment):
    seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.get(
        f"{LIST_PATH}/a1", data=b"{}", content_type="application/json",
    )
    assert response.status_code == 400


def test_create_rejects_duplicate_fields(environment):
    as_user(environment, "owner")
    response = environment.client.post(
        LIST_PATH, data=b'{"updates": {"name": "a"}, "updates": {"name": "b"}}',
        content_type="application/json",
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------
# Agent options: the group editor's options (a read capability)
# --------------------------------------------------------------------------



@pytest.mark.parametrize("role", READER_ROLES)
def test_agent_options_offered_to_every_member_role(environment, role):
    as_user(environment, ROLE_USER[role])
    response = environment.client.get(OPTIONS_PATH)
    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    body = response.get_json()
    assert set(body) >= {"agent_types", "settings", "model_endpoints", "builtin_actions"}


def test_agent_options_carry_no_personal_keys_or_endpoints(environment):
    as_user(environment, "owner")
    body = environment.client.get(OPTIONS_PATH).get_json()
    # No allow_user_* key anywhere in the settings block.
    assert not any(key.startswith("allow_user_") for key in body["settings"])
    # The group custom-endpoint flag is present (this is the group surface).
    assert "allow_group_custom_endpoints" in body["settings"]
    scopes = {endpoint.get("scope") for endpoint in body["model_endpoints"]}
    # A personal endpoint never appears on a group page.
    assert "user" not in scopes and "personal" not in scopes
    assert scopes <= {"global", "group"}


def test_agent_options_mask_endpoint_secrets(environment):
    as_user(environment, "owner")
    body = environment.client.get(OPTIONS_PATH).get_json()
    for endpoint in body["model_endpoints"]:
        assert endpoint.get("azure_openai_gpt_key") in (MASK, None)


def test_agent_options_non_manager_gets_no_models(environment):
    # A member with no write role gets an empty model list, gpt_model and default
    # selection, exactly as the personal builder does for non-managers.
    as_user(environment, "member")
    body = environment.client.get(OPTIONS_PATH).get_json()
    assert body["model_endpoints"] == []
    assert body["settings"]["gpt_model"] == {}
    assert body["settings"]["default_model_selection"] == {}


def test_agent_options_refused_when_unavailable(environment):
    environment.settings["allow_group_agents"] = False
    as_user(environment, "owner")
    assert environment.client.get(OPTIONS_PATH).status_code == 403


def test_agent_options_rejects_query_and_body(environment):
    as_user(environment, "owner")
    assert environment.client.get(f"{OPTIONS_PATH}?view=editor").status_code == 400
    assert environment.client.get(
        OPTIONS_PATH, data=b"{}", content_type="application/json",
    ).status_code == 400


# --------------------------------------------------------------------------
# B7 (M4C §11): the group templates panel's submit affordance must obey the
# exact gate the submit route enforces. The options flag is pinned against the
# real predicate the route also delegates to, across the full flag matrix.
# --------------------------------------------------------------------------

_SUBMISSION_DECISION = _load_real_submission_predicate()


@pytest.mark.parametrize(
    "gallery,allow_agents,allow_submission,admin",
    list(itertools.product((True, False), repeat=4)),
)
def test_agent_template_submission_flag_pins_the_route_gate(
    environment, gallery, allow_agents, allow_submission, admin,
):
    environment.settings["enable_agent_template_gallery"] = gallery
    environment.settings["allow_user_agents"] = allow_agents
    environment.settings["agent_templates_allow_user_submission"] = allow_submission
    roles = ("User", "Admin") if admin else ("User",)
    as_user(environment, "owner", roles=roles)
    body = environment.client.get(OPTIONS_PATH).get_json()
    expected, _reason = _SUBMISSION_DECISION(environment.settings, admin)
    assert body["settings"]["agent_template_submission_allowed"] is expected


def test_agent_template_submission_flag_matches_route_messages():
    # The predicate's three ordered reasons are exactly the route's 403 strings.
    assert _SUBMISSION_DECISION({}, False) == (False, "Agent template gallery is disabled.")
    assert _SUBMISSION_DECISION(
        {"enable_agent_template_gallery": True}, False,
    ) == (False, "Agent creation is disabled for your workspace.")
    assert _SUBMISSION_DECISION(
        {"enable_agent_template_gallery": True, "allow_user_agents": True,
         "agent_templates_allow_user_submission": False}, False,
    ) == (False, "Template submissions are disabled for users.")
    # Admin bypasses the last two gates but never the gallery switch.
    assert _SUBMISSION_DECISION(
        {"enable_agent_template_gallery": True}, True,
    ) == (True, None)
    assert _SUBMISSION_DECISION({}, True) == (False, "Agent template gallery is disabled.")
    # Submissions default to enabled when the key is absent.
    assert _SUBMISSION_DECISION(
        {"enable_agent_template_gallery": True, "allow_user_agents": True}, False,
    ) == (True, None)


def test_route_and_group_builder_delegate_to_one_submission_predicate():
    # The options flag can only equal the route's gate decision if both surfaces
    # call the same predicate. Pin that shared delegation structurally, so the
    # matrix above cannot silently drift into testing two independent copies.
    route_source = (APP_ROOT / "route_backend_agent_templates.py").read_text(encoding="utf-8")
    builder_source = (APP_ROOT / "functions_workspace_authoring.py").read_text(encoding="utf-8")
    submit = route_source.split("def submit_agent_template", 1)[1].split("\ndef ", 1)[0]
    assert "agent_template_submission_decision(" in submit
    builder = builder_source.split("def build_group_agent_editor_options", 1)[1].split("\ndef ", 1)[0]
    assert "agent_template_submission_decision(" in builder
    assert "agent_template_submission_allowed" in builder
    # The personal builder must stay untouched: no submission flag there.
    personal = builder_source.split("def build_agent_editor_options", 1)[1].split("\ndef ", 1)[0]
    assert "agent_template_submission_allowed" not in personal


# --------------------------------------------------------------------------
# Agent knowledge: assigned-knowledge catalogue for the named group
# --------------------------------------------------------------------------



@pytest.mark.parametrize("role", READER_ROLES)
def test_agent_knowledge_offered_to_every_member_role(environment, role):
    as_user(environment, ROLE_USER[role])
    response = environment.client.get(KNOWLEDGE_PATH)
    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store"
    # The catalogue was resolved for THIS group, never the account's active group.
    body = response.get_json()
    assert body["scope"] == "group" and body["group_id"] == "group-a"


def test_agent_knowledge_ignores_the_active_group(environment):
    # group-b in the path resolves group-b's catalogue regardless of any active group.
    as_user(environment, "owner")
    body = environment.client.get("/api/groups/group-b/agent-knowledge").get_json()
    assert body["group_id"] == "group-b"


def test_agent_knowledge_refused_to_non_members(environment):
    as_user(environment, "stranger")
    assert environment.client.get(KNOWLEDGE_PATH).status_code == 403


def test_agent_knowledge_refused_for_inactive_group(environment):
    as_user(environment, "owner")
    assert environment.client.get("/api/groups/inactive-grp/agent-knowledge").status_code == 403


# --------------------------------------------------------------------------
# Global merge (read-only)
# --------------------------------------------------------------------------

def _seed_global(environment, agent_id="g1"):
    return environment.global_container.create_item({
        "id": agent_id, "name": f"global-{agent_id}", "agent_type": "local", "is_enabled": True,
        "instructions": "Global agent.",
    })


def test_global_agents_are_listed_read_only_when_merge_is_enabled(environment):
    environment.settings["merge_global_semantic_kernel_with_workspace"] = True
    seed_agent(environment.group_container, "a1")
    _seed_global(environment)
    as_user(environment, "owner")
    body = environment.client.get(LIST_PATH).get_json()
    by_id = {item["id"]: item for item in body["agents"]}
    assert by_id["a1"]["is_group"] is True and by_id["a1"]["is_global"] is False
    assert by_id["g1"]["is_global"] is True and by_id["g1"]["is_group"] is False
    # A merged global agent carries no group per-item operations.
    assert by_id["g1"]["agent_actions"] == []


def test_single_read_of_a_merged_global_agent_is_read_only(environment):
    environment.settings["merge_global_semantic_kernel_with_workspace"] = True
    _seed_global(environment)
    as_user(environment, "owner")
    response = environment.client.get(f"{LIST_PATH}/g1")
    assert response.status_code == 200
    body = response.get_json()
    assert body["read_only"] is True
    assert body["record"]["is_global"] is True
    assert body["record"]["agent_actions"] == []


def test_single_read_of_a_global_id_is_404_when_merge_is_off(environment):
    environment.settings["merge_global_semantic_kernel_with_workspace"] = False
    _seed_global(environment)
    as_user(environment, "owner")
    assert environment.client.get(f"{LIST_PATH}/g1").status_code == 404


def test_writes_on_a_global_id_are_refused(environment):
    environment.settings["merge_global_semantic_kernel_with_workspace"] = True
    _seed_global(environment)
    as_user(environment, "owner")
    update = environment.client.patch(f"{LIST_PATH}/g1", json=write_body('"etag-1"', description="x"))
    assert update.status_code == 404
    assert environment.client.delete(f"{LIST_PATH}/g1").status_code == 404
    assert ("g1", "g1") in environment.global_container.records


# --------------------------------------------------------------------------
# Cross-group isolation: the path group, never the active group
# --------------------------------------------------------------------------

def test_a_saved_agent_is_read_from_the_path_group_only(environment):
    seed_agent(environment.group_container, "a1", group_id="group-a")
    as_user(environment, "owner")
    # group-b in the path must not surface group-a's agent.
    assert environment.client.get("/api/groups/group-b/agents/a1").status_code == 404
    assert [item["id"] for item in environment.client.get(
        "/api/groups/group-b/agents").get_json()["agents"]] == []


# --------------------------------------------------------------------------
# Availability predicate: one gate for the section and every route
# --------------------------------------------------------------------------

AVAILABILITY_FLAGS = ["enable_semantic_kernel", "per_user_semantic_kernel", "allow_group_agents"]


@pytest.mark.parametrize("flag", AVAILABILITY_FLAGS)
def test_every_route_refuses_when_an_availability_flag_is_off(environment, flag):
    seed = seed_agent(environment.group_container, "a1")
    environment.settings[flag] = False
    as_user(environment, "owner")
    assert environment.client.get(LIST_PATH).status_code == 403
    assert environment.client.get(f"{LIST_PATH}/a1").status_code == 403
    assert environment.client.get(OPTIONS_PATH).status_code == 403
    assert environment.client.get(KNOWLEDGE_PATH).status_code == 403
    assert environment.client.post(LIST_PATH, json=create_body(name="x")).status_code == 403
    assert environment.client.patch(f"{LIST_PATH}/a1", json=write_body(seed["_etag"], description="y")).status_code == 403
    assert environment.client.delete(f"{LIST_PATH}/a1").status_code == 403


def test_every_route_refuses_when_governance_denies(environment):
    seed = seed_agent(environment.group_container, "a1")
    environment.governance.is_governance_access_allowed.return_value = False
    as_user(environment, "owner")
    assert environment.client.get(LIST_PATH).status_code == 403
    assert environment.client.get(f"{LIST_PATH}/a1").status_code == 403
    assert environment.client.get(OPTIONS_PATH).status_code == 403
    assert environment.client.get(KNOWLEDGE_PATH).status_code == 403
    assert environment.client.post(LIST_PATH, json=create_body(name="x")).status_code == 403
    assert environment.client.patch(f"{LIST_PATH}/a1", json=write_body(seed["_etag"], description="y")).status_code == 403
    assert environment.client.delete(f"{LIST_PATH}/a1").status_code == 403


def test_management_projection_is_empty_when_unavailable(environment):
    from functions_group_agent_policy import group_agent_management_operations
    active = environment.groups["group-a"]
    assert group_agent_management_operations("owner", active, "Owner", environment.settings) == [
        "create", "edit", "delete",
    ]
    environment.settings["allow_group_agents"] = False
    assert group_agent_management_operations("owner", active, "Owner", environment.settings) == []


def test_context_and_routes_call_the_same_availability_predicate():
    # Pin that the context section and the routes both resolve availability through
    # group_agents_available, so the two can never drift. Load the policy module
    # from APP_ROOT rather than a bare import so this passes without
    # application/single_app on sys.path, as the rest of the suite does.
    spec = importlib.util.spec_from_file_location(
        "functions_group_agent_policy", APP_ROOT / "functions_group_agent_policy.py",
    )
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    access_source = (APP_ROOT / "functions_group_agent_access.py").read_text(encoding="utf-8")
    context_source = (APP_ROOT / "functions_workspace_context.py").read_text(encoding="utf-8")
    assert hasattr(policy, "group_agents_available")
    assert "group_agents_available" in access_source
    assert "group_agents_available" in context_source


# --------------------------------------------------------------------------
# B1: activity logging for committed writes
# --------------------------------------------------------------------------

def test_create_logs_agent_creation_with_group_scope(environment):
    as_user(environment, "owner")
    created = environment.client.post(LIST_PATH, json=create_body(name="logged-create"))
    assert created.status_code == 201
    agent_id = created.get_json()["record"]["id"]
    environment.activity.log_agent_creation.assert_called_once()
    kwargs = environment.activity.log_agent_creation.call_args.kwargs
    assert kwargs["scope"] == "group" and kwargs["group_id"] == "group-a"
    assert kwargs["agent_id"] == agent_id and kwargs["agent_name"] == "logged-create"
    environment.activity.log_agent_update.assert_not_called()
    environment.activity.log_agent_deletion.assert_not_called()


def test_update_logs_agent_update_with_group_scope(environment):
    seed = seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(seed["_etag"], description="edited"))
    assert response.status_code == 200
    environment.activity.log_agent_update.assert_called_once()
    kwargs = environment.activity.log_agent_update.call_args.kwargs
    assert kwargs["scope"] == "group" and kwargs["group_id"] == "group-a"
    assert kwargs["agent_id"] == "a1"


def test_delete_logs_agent_deletion_with_group_scope(environment):
    seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    assert environment.client.delete(f"{LIST_PATH}/a1").status_code == 200
    environment.activity.log_agent_deletion.assert_called_once()
    kwargs = environment.activity.log_agent_deletion.call_args.kwargs
    assert kwargs["scope"] == "group" and kwargs["group_id"] == "group-a"
    assert kwargs["agent_id"] == "a1"


def test_a_raising_logger_never_fails_a_committed_write(environment):
    # The write has already committed; a logging failure is downgraded to a
    # WARNING and the response is unaffected (mirrors personal_editor_response).
    environment.activity.log_agent_creation.side_effect = RuntimeError("logger down")
    as_user(environment, "owner")
    created = environment.client.post(LIST_PATH, json=create_body(name="still-created"))
    assert created.status_code == 201
    agent_id = created.get_json()["record"]["id"]
    assert ("group-a", agent_id) in environment.group_container.records
    warning = [
        call for call in environment.appinsights.log_event.call_args_list
        if call.args and "[WORKSPACE_ACTIVITY]" in str(call.args[0])
    ]
    assert warning, "A logging failure must emit the WORKSPACE_ACTIVITY warning."


@pytest.mark.parametrize("role", NON_WRITER_ROLES)
def test_a_refused_write_logs_nothing(environment, role):
    seed = seed_agent(environment.group_container, "a1")
    # 403 (role), 409 (stale) and 400 (bad create) must each record no activity.
    as_user(environment, ROLE_USER[role])
    assert environment.client.post(LIST_PATH, json=create_body(name="x")).status_code == 403
    assert environment.client.delete(f"{LIST_PATH}/a1").status_code == 403
    as_user(environment, "owner")
    environment.client.patch(f"{LIST_PATH}/a1", json=write_body(seed["_etag"], description="first"))
    conflict = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(seed["_etag"], description="second"))
    assert conflict.status_code == 409
    assert environment.client.post(LIST_PATH, json={"updates": {"name": "no-id"}}).status_code == 400
    environment.activity.log_agent_creation.assert_not_called()
    environment.activity.log_agent_deletion.assert_not_called()
    # Exactly one committed update (the first PATCH) was logged.
    assert environment.activity.log_agent_update.call_count == 1


# --------------------------------------------------------------------------
# B4: stored document carries the group agent flags
# --------------------------------------------------------------------------

def test_created_group_agent_document_stores_is_group_flags(environment):
    as_user(environment, "owner")
    created = environment.client.post(LIST_PATH, json=create_body(name="shaped"))
    assert created.status_code == 201
    agent_id = created.get_json()["record"]["id"]
    stored = environment.group_container.records[("group-a", agent_id)]
    assert stored["is_global"] is False and stored["is_group"] is True


def test_updated_group_agent_document_keeps_is_group_flags(environment):
    seed = seed_agent(environment.group_container, "a1")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(seed["_etag"], description="edited"))
    assert response.status_code == 200
    stored = environment.group_container.records[("group-a", "a1")]
    assert stored["is_global"] is False and stored["is_group"] is True


def test_v1_shaped_group_agent_keeps_flags_through_the_first_v2_edit(environment):
    # The legacy save_group_agent writes is_group True / is_global False. The first
    # V2 edit does a whole-document replace_item and save_group_editor_record builds
    # its body without the managed fields, so without B4 that first save would strip
    # the flags the runtime consumers branch on. Seed the exact V1 shape and confirm
    # the edit preserves both flags rather than dropping them.
    seed = seed_agent(environment.group_container, "a1", is_group=True, is_global=False)
    assert seed["is_group"] is True and seed["is_global"] is False
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/a1", json=write_body(seed["_etag"], description="edited"))
    assert response.status_code == 200
    stored = environment.group_container.records[("group-a", "a1")]
    assert stored["is_group"] is True and stored["is_global"] is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
