# test_group_document_etag_guard.py
"""
Functional test for the conditional group-document writer.
Version: 0.261.140
Implemented in: 0.261.140

``update_group_document_with_etag_guard`` is the group-document equivalent of the
File Sync ``_write_with_etag_guard`` (``fae9d6ef``). The real ``functions_group``
module runs against the ``FakeContainer`` from
``test_file_sync_concurrent_write_safety.py``, which refuses a stale etag with 412
and a missing record with 404 and never creates. Concurrent writers are landed
deterministically between the guarded read and its replace.

It pins that a concurrent membership change is re-read and kept (no conflict), that
a deleted group is reported as missing and never recreated, that a writer which
keeps losing gets a conflict with nothing written, that a lost-response commit is
recognised, and that the legacy ``update_group_model_endpoints`` is still the
unconditional upsert it was.
"""

import pytest
from azure.cosmos.exceptions import CosmosAccessConditionFailedError

from test_support.group_endpoint_harness import GROUP_A, group_endpoint_environment


@pytest.fixture(scope="module")
def module_env():
    with group_endpoint_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def add_description(document):
    document["description"] = "Edited by the guarded writer"
    return document


def land_membership_change(env):
    def concurrent():
        record = env.stored_group(GROUP_A)
        record["users"].append({"userId": "late-member", "email": "", "displayName": "Late"})
        env.groups.seed(record)
    return concurrent


def test_a_concurrent_membership_change_is_kept_and_the_change_applied(env):
    env.seed_group(GROUP_A)
    env.groups.before_replace.append(land_membership_change(env))
    applied = []

    def apply(document):
        applied.append([user["userId"] for user in document["users"]])
        return add_description(document)

    written = env.modules.group.update_group_document_with_etag_guard(GROUP_A, apply, cache_reason="test_reason")
    stored = env.stored_group(GROUP_A)
    assert stored["description"] == "Edited by the guarded writer"
    assert "late-member" in [user["userId"] for user in stored["users"]]
    assert written["description"] == stored["description"]
    # The change was applied twice: once to the stale copy and once to the re-read one.
    assert len(applied) == 2 and "late-member" not in applied[0] and "late-member" in applied[1]
    assert [call[0] for call in env.write_calls()] == ["replace_item", "replace_item"]
    assert env.bumps == ["test_reason"]


def test_a_group_deleted_mid_write_is_reported_missing_and_never_recreated(env):
    env.seed_group(GROUP_A)
    env.groups.before_replace.append(lambda: env.groups.records.clear())
    written = env.modules.group.update_group_document_with_etag_guard(GROUP_A, add_description, cache_reason="test_reason")
    assert written is None
    assert env.stored_group(GROUP_A) is None
    assert not [call for call in env.groups.calls if call[0] in ("create_item", "upsert_item")]
    assert env.bumps == []


def test_a_missing_group_is_never_created(env):
    written = env.modules.group.update_group_document_with_etag_guard(GROUP_A, add_description, cache_reason="test_reason")
    assert written is None
    assert env.write_calls() == []


def test_a_writer_that_keeps_losing_gets_a_conflict_with_nothing_written(env):
    env.seed_group(GROUP_A)
    attempts = env.modules.group.GROUP_DOCUMENT_WRITE_ATTEMPTS
    env.groups.before_replace.extend([land_membership_change(env)] * attempts)
    with pytest.raises(env.modules.group.GroupDocumentWriteConflict):
        env.modules.group.update_group_document_with_etag_guard(GROUP_A, add_description, cache_reason="test_reason")
    stored = env.stored_group(GROUP_A)
    assert stored["description"] == "Shared connections"
    assert len([call for call in env.groups.calls if call[0] == "replace_item"]) == attempts
    assert env.bumps == []


def test_an_apply_that_raises_writes_nothing(env):
    env.seed_group(GROUP_A)

    def refuse(document):
        raise ValueError("refused by the change itself")

    with pytest.raises(ValueError):
        env.modules.group.update_group_document_with_etag_guard(GROUP_A, refuse, cache_reason="test_reason")
    assert env.write_calls() == []
    assert env.bumps == []


def test_a_lost_response_commit_is_recognised_rather_than_retried(env, monkeypatch):
    """A transport retry of a committed replace fails its own precondition (412)."""
    env.seed_group(GROUP_A)
    original = env.groups.replace_item
    committed = []

    def replace_then_lose_the_response(item, body, etag=None, match_condition=None, **kwargs):
        stored = original(item, body, etag=etag, match_condition=match_condition, **kwargs)
        committed.append(stored)
        raise CosmosAccessConditionFailedError(status_code=412, message="Precondition failed")

    monkeypatch.setattr(env.groups, "replace_item", replace_then_lose_the_response)
    applied = []

    def apply(document):
        applied.append(True)
        return add_description(document)

    written = env.modules.group.update_group_document_with_etag_guard(GROUP_A, apply, cache_reason="test_reason")
    assert len(applied) == 1, "the committed change must not be re-applied"
    assert written["description"] == "Edited by the guarded writer"
    assert written["_etag"] == committed[0]["_etag"]
    assert env.bumps == ["test_reason"]


def test_the_legacy_collection_writer_is_still_an_unconditional_upsert(env):
    """Recorded, not changed: M7B moves the legacy writers onto the guarded helper."""
    env.seed_group(GROUP_A)
    env.modules.group.update_group_model_endpoints(GROUP_A, [])
    assert [call[0] for call in env.write_calls()] == ["upsert_item"]
    assert env.bumps == ["group_model_endpoints_updated"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
