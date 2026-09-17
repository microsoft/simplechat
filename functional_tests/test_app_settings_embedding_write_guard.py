# test_app_settings_embedding_write_guard.py
"""
Regression tests for embedding activation around authoritative settings writes.
Version: 0.261.122
Implemented in: 0.261.122

The domain fence must cover Cosmos CAS and shared publication, retry against the
latest document, and never activate a failed or superseded embedding selection.
"""

from contextlib import contextmanager
import json
import sys
from types import SimpleNamespace

import pytest
from azure.cosmos.exceptions import CosmosAccessConditionFailedError

from test_app_settings_store_consistency import (
    AppSettingsStore,
    SettingsConflictError,
    SettingsUnavailableError,
    change,
    load_update_settings,
    store_module,
    world as world,
)


def test_guard_covers_cas_and_shared_publication(world, monkeypatch):
    events = []
    active = []
    replace_item = world.cosmos.replace_item
    redis_eval = world.redis.eval

    @contextmanager
    def guard(current, candidate):
        assert json.loads(world.redis.raw)["state"] == "pending"
        current[store_module.SETTINGS_REVISION_FIELD] = 999
        candidate.update({
            "embedding_vector_profile": {"id": "new-space"},
            "id": "not-the-settings-document",
            "_etag": "not-a-cosmos-etag",
            store_module.SETTINGS_REVISION_FIELD: 999,
        })
        active.append(True)
        events.append("guard-enter")
        try:
            yield
            assert json.loads(world.redis.raw)["state"] == "ready"
            events.append("activate")
        finally:
            active.pop()

    def guarded_replace(*args, **kwargs):
        assert active
        assert kwargs["body"]["id"] == "app_settings"
        assert "_etag" not in kwargs["body"]
        assert kwargs["body"][store_module.SETTINGS_REVISION_FIELD] == 1
        events.append("cosmos")
        return replace_item(*args, **kwargs)

    def guarded_publish(*args):
        if json.loads(args[-1])["state"] == "ready":
            assert active
            events.append("publish")
        return redis_eval(*args)

    monkeypatch.setattr(world.cosmos, "replace_item", guarded_replace)
    monkeypatch.setattr(world.redis, "eval", guarded_publish)
    stored = world.a.write(change(enabled=True), write_guard=guard)

    assert events == ["guard-enter", "cosmos", "publish", "activate"]
    assert stored["embedding_vector_profile"] == {"id": "new-space"}
    assert world.b.read() == stored
    assert not active


def test_conflict_retries_guard_against_fresh_settings(world):
    store = AppSettingsStore(world.cosmos)
    events = []

    @contextmanager
    def guard(current, candidate):
        etag = current["_etag"]
        events.append(("enter", etag))
        candidate["checked_etag"] = etag
        try:
            yield
        except CosmosAccessConditionFailedError:
            events.append(("abort", etag))
            raise
        else:
            events.append(("activate", etag))

    world.cosmos.before_replace = lambda: store.write(change(concurrent="preserved"))
    stored = store.write(change(enabled=True), write_guard=guard)

    assert events == [("enter", "1"), ("abort", "1"), ("enter", "2"), ("activate", "2")]
    assert stored["concurrent"] == "preserved"
    assert stored["checked_etag"] == "2"
    assert stored[store_module.SETTINGS_REVISION_FIELD] == 2
    assert world.cosmos.writes == 2


def test_guard_rejection_prevents_database_write(world):
    @contextmanager
    def reject(current, candidate):
        if candidate["enabled"]:
            raise ValueError("Incompatible embedding space")
        yield

    with pytest.raises(ValueError, match="Incompatible embedding space"):
        world.a.write(change(enabled=True), write_guard=reject)

    assert world.cosmos.writes == 0
    assert world.b.read()["enabled"] is False


def test_guard_activation_error_is_not_retried_as_a_settings_conflict(world):
    attempts = []
    error = CosmosAccessConditionFailedError(status_code=412, message="Activation failed")

    @contextmanager
    def guard(current, candidate):
        attempts.append(current["_etag"])
        yield
        raise error

    with pytest.raises(CosmosAccessConditionFailedError) as raised:
        AppSettingsStore(world.cosmos).write(change(enabled=True), write_guard=guard)

    assert raised.value is error
    assert attempts == ["1"]
    assert world.cosmos.writes == 1
    assert world.cosmos.document["enabled"] is True


def test_guard_wait_cannot_outlive_shared_write_ownership(world):
    activated = []

    @contextmanager
    def guard(current, candidate):
        world.now[0] += store_module.WRITE_LEASE_SECONDS + 1
        world.b.write(change(concurrent="newer"))
        yield
        activated.append(True)

    with pytest.raises(SettingsConflictError, match="ownership expired"):
        world.a.write(change(enabled=True), write_guard=guard)

    assert world.cosmos.writes == 1
    assert world.c.read()["enabled"] is False
    assert world.c.read()["concurrent"] == "newer"
    assert not activated


def test_publication_failure_does_not_activate_the_guard(world):
    activated = []

    @contextmanager
    def guard(current, candidate):
        yield
        activated.append(True)

    world.redis.fail_publication = True
    with pytest.raises(SettingsUnavailableError):
        world.a.write(change(enabled=True), write_guard=guard)

    assert world.cosmos.writes == 1
    assert json.loads(world.redis.raw)["state"] == "pending"
    assert world.b.read()["enabled"] is True
    assert not activated


def test_stale_etag_does_not_acquire_domain_fence(world):
    entered = []

    @contextmanager
    def guard(current, candidate):
        entered.append(True)
        yield

    world.b.write(change(concurrent="newer"))
    shared_state = world.redis.raw
    with pytest.raises(SettingsConflictError):
        world.a.write(change(enabled=True), expected_etag="1", write_guard=guard)

    assert not entered
    assert world.redis.raw == shared_state
    assert world.cosmos.writes == 1


def test_real_update_settings_routes_embedding_selection_through_guard(world, monkeypatch):
    update = load_update_settings(world.a)
    selection_key = update.__globals__["EMBEDDING_SELECTION_KEY"]
    events = []

    @contextmanager
    def guard(current, candidate, *, force_check):
        assert force_check is True
        events.append(current["_etag"])
        candidate["embedding_vector_profile"] = {"id": "validated-space"}
        yield
        assert world.cosmos.document["embedding_vector_profile"]["id"] == "validated-space"
        events.append("activated")

    monkeypatch.setitem(sys.modules, "functions_embedding_compatibility", SimpleNamespace(
        embedding_settings_write_guard=guard,
    ))
    assert update({selection_key: {"endpoint_id": "connection", "model_id": "model"}}) is True
    assert events == ["1", "activated"]
    assert world.b.read()["embedding_vector_profile"] == {"id": "validated-space"}


def test_real_update_settings_preserves_user_safe_guard_rejection(world, monkeypatch):
    update = load_update_settings(world.a)
    error_type = update.__globals__["AIConnectionError"]
    error = error_type("Rebuild the vector space before switching.", "embedding_rebuild_required")

    @contextmanager
    def guard(current, candidate, *, force_check):
        if candidate["enabled"]:
            raise error
        yield

    monkeypatch.setitem(sys.modules, "functions_embedding_compatibility", SimpleNamespace(
        embedding_settings_write_guard=guard,
    ))
    with pytest.raises(error_type) as raised:
        update({"enabled": True})

    assert raised.value is error
    assert world.cosmos.writes == 0
