# test_group_bulk_endpoint_save_writer.py
"""
Functional test for the legacy bulk group model endpoint save on the etag guard.
Version: 0.261.160
Implemented in: 0.261.160

``POST /api/group/model-endpoints`` saved the whole endpoint list through
``update_group_model_endpoints``, which read the group and upserted that copy back:
a membership or status change landing in between was undone, a group deleted in
between was recreated, and the caller's role was checked only before the write.
Worse, the route deleted superseded and removed Key Vault credentials before the
write, so a write that then failed left the stored endpoints pointing at deleted
secrets.

Now:

- ``update_group_model_endpoints`` replaces the list on the copy the etag guard
  reads, re-checks the caller's role on it (``user_id=``), reports the endpoints it
  replaced (``outcome=``) and raises ``LookupError`` for a deleted group. The list
  is still last writer wins, as before; the overlap with the per-item routes is
  recorded, not changed.
- The route answers a group that keeps changing with 409 ``group_write_conflict``,
  and a deleted group and a demoted caller with its own 404 and 403.
- Superseded and removed credentials are deleted only after the write commits,
  judged against the endpoints it replaced, and never while the committed endpoints
  still reference them. A definitive failure deletes only the credentials this save
  staged; an uncertain one keeps them.

This test drives the real route, guard and Key Vault helpers in
``test_support/group_endpoint_harness.py``, whose in-memory vault records every
write and delete by name.
"""

import re

import pytest

from test_support.group_endpoint_harness import GROUP_A, aoai_endpoint, group_endpoint_environment


SAVE = "/api/group/model-endpoints"


def deterministic(endpoint_id):
    return f"{endpoint_id}--model-endpoint--group--model-endpoint-api-key"


STAGED = re.compile(r"^ep-1--model-endpoint--group--s-[0-9a-f]{16,}$")


@pytest.fixture(scope="module")
def module_env():
    with group_endpoint_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    module_env.seed_group_with_legacy_endpoints(GROUP_A, [
        aoai_endpoint("ep-1", api_key="key-one"), aoai_endpoint("ep-2", api_key="key-two"),
    ])
    module_env.active_group = GROUP_A
    module_env.vault.writes.clear()
    yield module_env
    module_env.reset()


def classic_copy(env, endpoint_id):
    """What the classic page sends back: the sanitized endpoint, no secrets."""
    listing = env.client.get(f"/api/groups/{GROUP_A}/model-endpoints").get_json()["endpoints"]
    endpoint = next(item for item in listing if item["id"] == endpoint_id)
    return {key: value for key, value in endpoint.items() if key not in ("revision", "endpoint_actions")}


def rotated(env, endpoint_id="ep-1", key="rotated-key"):
    endpoint = classic_copy(env, endpoint_id)
    endpoint["auth"]["api_key"] = key
    return endpoint


def save(env, endpoints):
    return env.call("POST", SAVE, {"endpoints": endpoints})


def staged_name(env):
    [(name, _value)] = env.vault.writes
    assert STAGED.match(name)
    return name


def concurrently(env, change):
    def land():
        stored = env.stored_group(GROUP_A)
        change(stored)
        env.groups.seed(stored)
    env.groups.before_replace.append(land)


def deletes_at_write_time(env):
    """The vault deletes already made when the write reaches the container."""
    seen = []
    env.groups.before_replace.append(lambda: seen.append(list(env.vault.deletes)))
    return seen


def conflict(env):
    return {"error": env.modules.group.GROUP_WRITE_CONFLICT_MESSAGE, "error_code": "group_write_conflict"}


# ---------------------------------------------------------------------------
# Committed saves
# ---------------------------------------------------------------------------

def test_a_superseded_credential_is_deleted_only_after_the_write_commits(env):
    seen = deletes_at_write_time(env)
    response = save(env, [rotated(env), classic_copy(env, "ep-2")])
    assert response.status_code == 200 and response.get_json()["success"] is True
    name = staged_name(env)
    assert seen == [[]], "nothing may be deleted before the write"
    assert env.vault.deletes == [deterministic("ep-1")]
    assert env.stored_endpoint(GROUP_A, "ep-1")["auth"]["api_key"] == name
    assert env.stored_endpoint(GROUP_A, "ep-2")["auth"]["api_key"] == deterministic("ep-2")
    assert env.bumps == ["group_model_endpoints_updated"]


def test_a_removed_endpoints_credential_is_deleted_only_after_the_write_commits(env):
    seen = deletes_at_write_time(env)
    assert save(env, [classic_copy(env, "ep-1")]).status_code == 200
    assert seen == [[]]
    assert env.vault.deletes == [deterministic("ep-2")]
    assert [endpoint["id"] for endpoint in env.stored_group(GROUP_A)["model_endpoints"]] == ["ep-1"]


def test_an_unchanged_endpoint_keeps_its_credential(env):
    assert save(env, [classic_copy(env, "ep-1"), classic_copy(env, "ep-2")]).status_code == 200
    assert env.vault.writes == [] and env.vault.deletes == []
    assert env.stored_endpoint(GROUP_A, "ep-1")["auth"]["api_key"] == deterministic("ep-1")


def test_a_concurrent_membership_change_is_kept(env):
    concurrently(env, lambda group: group["pendingUsers"].append({"userId": "applicant", "email": "applicant@example.test"}))
    assert save(env, [classic_copy(env, "ep-1")]).status_code == 200
    stored = env.stored_group(GROUP_A)
    assert [entry["userId"] for entry in stored["pendingUsers"]] == ["applicant"]
    assert [endpoint["id"] for endpoint in stored["model_endpoints"]] == ["ep-1"]
    assert [call[0] for call in env.write_calls()] == ["replace_item", "replace_item"]


def test_credentials_are_judged_against_the_endpoints_the_write_replaced(env):
    """An endpoint added meanwhile is replaced by the saved list, and its credential goes too."""
    added = env.legacy_stored_endpoints(GROUP_A, [aoai_endpoint("ep-3", api_key="key-three")])
    concurrently(env, lambda group: group["model_endpoints"].extend(added))
    assert save(env, [classic_copy(env, "ep-1"), classic_copy(env, "ep-2")]).status_code == 200
    assert env.vault.deletes == [deterministic("ep-3")]
    assert deterministic("ep-1") in env.vault.secrets and deterministic("ep-2") in env.vault.secrets


# ---------------------------------------------------------------------------
# Failed saves
# ---------------------------------------------------------------------------

def test_a_group_that_keeps_changing_answers_409_and_keeps_the_stored_credentials(env):
    for index in range(env.modules.group.GROUP_DOCUMENT_WRITE_ATTEMPTS):
        concurrently(env, lambda group, index=index: group["pendingUsers"].append({"userId": f"late-{index}"}))
    response = save(env, [rotated(env), classic_copy(env, "ep-2")])
    assert (response.status_code, response.get_json()) == (409, conflict(env))
    name = staged_name(env)
    assert env.vault.deletes == [name], "only the credential this save staged"
    assert env.vault.secrets[deterministic("ep-1")] == "key-one"
    assert env.stored_endpoint(GROUP_A, "ep-1")["auth"]["api_key"] == deterministic("ep-1")
    assert env.bumps == []


def test_a_group_deleted_mid_write_answers_404_and_is_not_recreated(env):
    env.groups.before_replace.append(lambda: env.groups.records.clear())
    response = save(env, [rotated(env)])
    assert (response.status_code, response.get_json()) == (404, {"error": "The selected group could not be found."})
    assert env.groups.records == {}
    assert env.vault.deletes == [staged_name(env)]
    assert env.bumps == []


def test_a_caller_demoted_mid_write_is_refused_on_the_current_copy(env):
    env.as_user("admin")
    concurrently(env, lambda group: group["admins"].remove("admin"))
    response = save(env, [rotated(env)])
    assert (response.status_code, response.get_json()) == (
        403, {"error": "You do not have access to group model endpoint settings."},
    )
    assert env.vault.deletes == [staged_name(env)]
    assert env.stored_endpoint(GROUP_A, "ep-1")["auth"]["api_key"] == deterministic("ep-1")
    assert env.bumps == []


def test_an_uncertain_write_failure_keeps_the_staged_credential(env, monkeypatch):
    def transport_failure(*args, **kwargs):
        raise RuntimeError("The connection was reset.")

    monkeypatch.setattr(env.groups, "replace_item", transport_failure)
    with pytest.raises(RuntimeError):
        save(env, [rotated(env)])
    staged_name(env)
    assert env.vault.deletes == []
    assert (
        "[KEY_VAULT] Kept staged group model endpoint credentials after an uncertain write.",
        30, {"group_id": GROUP_A, "count": 1},
    ) in env.logs


@pytest.mark.parametrize("body,expected", [
    ({"endpoints": "ep-1"}, (400, {"error": "endpoints must be a list."})),
])
def test_the_classic_refusals_are_unchanged(env, body, expected):
    response = env.call("POST", SAVE, body)
    assert (response.status_code, response.get_json()) == expected
    assert env.write_calls() == [] and env.vault.writes == []


def test_a_member_is_still_refused_before_anything_is_staged(env):
    env.as_user("member")
    response = save(env, [rotated(env)])
    assert response.status_code == 403
    assert env.vault.writes == [] and env.write_calls() == []


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------

def test_the_writer_replaces_the_list_on_the_current_copy_and_reports_what_it_replaced(env):
    stored = env.stored_group(GROUP_A)["model_endpoints"]
    concurrently(env, lambda group: group["pendingUsers"].append({"userId": "applicant"}))
    outcome = {}
    committed = env.modules.group.update_group_model_endpoints(GROUP_A, [], user_id="owner", outcome=outcome)
    assert committed["model_endpoints"] == [] and env.stored_group(GROUP_A)["model_endpoints"] == []
    assert [entry["userId"] for entry in committed["pendingUsers"]] == ["applicant"]
    assert outcome == {"previous": stored, "saved": []}
    assert env.bumps == ["group_model_endpoints_updated"]


@pytest.mark.parametrize("arguments,error,message", [
    ((GROUP_A, "ep-1"), ValueError, "^model_endpoints must be a list$"),
    (("group-9", []), LookupError, "^Group not found$"),
    ((GROUP_A, [], "member"), PermissionError, "^Insufficient permissions for this group$"),
    ((GROUP_A, [], "outsider"), PermissionError, "^User is not a member of this group$"),
])
def test_the_writer_refuses_without_writing(env, arguments, error, message):
    group_id, endpoints, *user = arguments
    with pytest.raises(error, match=message):
        env.modules.group.update_group_model_endpoints(group_id, endpoints, user_id=user[0] if user else None)
    assert env.write_calls() == [] and env.bumps == []
