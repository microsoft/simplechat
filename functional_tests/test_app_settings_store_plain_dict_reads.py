# test_app_settings_store_plain_dict_reads.py
"""
Regression tests for the type of the settings that orchestration access checks receive.
Version: 0.261.235
Implemented in: 0.261.235

azure-cosmos returns the settings document as ``CosmosDict``, a ``dict`` subclass, and
``copy.deepcopy`` keeps that subclass. Orchestration's retained-result access checks
require exactly ``dict``. Before this fix, a settings read that Cosmos served instead of
the shared Redis copy made web search, linked-page, deep research, agent, action and
memory results fail with "A required retained result is unavailable or changed." That
was every read with Redis disabled, and with Redis enabled any read that overlapped
another worker's settings save, a cache repair or a Redis fallback. In production a
Cosmos throughput autoscale save made an email run fail this way at finalization,
after every step had completed.

The Cosmos fake returns the real SDK response type, the real settings store and getter
serve the reads, and the real orchestration access checks consume them. Network access
is blocked by the reused fixtures.
"""

import copy
import json
from pathlib import Path
import sys
import time

import pytest
from azure.core.utils import CaseInsensitiveDict
from azure.cosmos._cosmos_responses import CosmosDict

# The reused modules below put the application and this directory on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_app_settings_store_consistency import (  # noqa: E402 - shared store fakes and real getter harness
    FakeCosmos,
    FakeRedis,
    change,
    load_get_settings,
    store_module,
)
from test_orchestration_external_sources import ExternalSourceWorld  # noqa: E402
from functions_orchestration_results import ResultUnavailableError  # noqa: E402


AppSettingsStore = store_module.AppSettingsStore
GATHER_CAPABILITIES = ("web_search", "url_fetch", "deep_research", "agent_invoke", "action_invoke")


class SdkCosmos(FakeCosmos):
    """The shared settings fake, answering with the response type azure-cosmos returns."""

    def __init__(self, document=None):
        super().__init__()
        if document is not None:
            self.document = copy.deepcopy(document)
        self.document["nested"] = {"items": [1, 2]}

    def _response(self, response_hook=None):
        return CosmosDict(
            super()._response(response_hook),
            response_headers=CaseInsensitiveDict({"x-ms-session-token": f"token-{self.etag}"}),
        )


def save_marker(deadline):
    """Another worker's in-progress save, as the store writes it to Redis."""
    return json.dumps({
        "state": "pending", "owner": "another-worker", "deadline": deadline, "session_token": None,
    }).encode()


def published_store(cosmos, redis):
    store = AppSettingsStore(cosmos, redis, redis_required=True)
    store.write(change(enabled=True))
    assert json.loads(redis.raw)["state"] == "ready"
    return store


def read_without_redis(cosmos, _redis):
    return AppSettingsStore(cosmos).read()


def read_shared_copy(cosmos, redis):
    return published_store(cosmos, redis).read()


def read_forced_cosmos(cosmos, redis):
    return published_store(cosmos, redis).read(use_cosmos=True)


def read_during_another_save(cosmos, redis):
    store = published_store(cosmos, redis)
    redis.raw = save_marker(time.time() + 60)
    return store.read()


def read_after_abandoned_save(cosmos, redis):
    store = published_store(cosmos, redis)
    redis.raw = save_marker(time.time() - 1)
    return store.read()


def read_after_cache_miss(cosmos, redis):
    redis.raw = None
    return AppSettingsStore(cosmos, redis, redis_required=True).read()


def read_with_redis_unavailable(cosmos, redis):
    redis.failed = True
    return AppSettingsStore(cosmos, redis, redis_required=True).read()


READ_PATHS = {
    "redis disabled": read_without_redis,
    "shared copy": read_shared_copy,
    "forced Cosmos read": read_forced_cosmos,
    "another worker's save in progress": read_during_another_save,
    "abandoned save repaired": read_after_abandoned_save,
    "cache miss repaired": read_after_cache_miss,
    "Redis unavailable": read_with_redis_unavailable,
}


def assert_plain_independent_copy(value, cosmos):
    assert type(value) is dict
    assert value["_etag"] == cosmos.document["_etag"]
    assert type(value["nested"]) is dict
    value["nested"]["items"].append(3)
    assert cosmos.document["nested"]["items"] == [1, 2]


def test_fake_reproduces_the_sdk_response_type():
    """The reproduction depends on the SDK subclass surviving deepcopy."""
    response = SdkCosmos().read_item("app_settings", "app_settings")
    assert type(response) is CosmosDict
    assert type(copy.deepcopy(response)) is CosmosDict
    assert isinstance(response, dict)


@pytest.mark.parametrize("read", READ_PATHS.values(), ids=READ_PATHS.keys())
def test_every_store_read_path_returns_a_plain_dict(read):
    cosmos = SdkCosmos()
    value = read(cosmos, FakeRedis())
    assert_plain_independent_copy(value, cosmos)


@pytest.mark.parametrize("redis_required", (False, True), ids=("redis disabled", "redis enabled"))
def test_store_writes_return_a_plain_dict(redis_required):
    cosmos = SdkCosmos()
    store = AppSettingsStore(cosmos, FakeRedis() if redis_required else None, redis_required=redis_required)
    saved = store.write(change(enabled=True))
    assert saved["enabled"] is True
    assert_plain_independent_copy(saved, cosmos)


def test_creating_missing_settings_returns_a_plain_dict():
    cosmos = SdkCosmos()
    cosmos.document = None
    created = AppSettingsStore(cosmos).write(
        lambda document: document, defaults={"id": "app_settings", "nested": {"items": [1, 2]}},
    )
    assert_plain_independent_copy(created, cosmos)


@pytest.mark.parametrize(
    "state", ("redis disabled", "another worker's save in progress", "Redis unavailable"),
)
def test_real_get_settings_returns_a_plain_dict(state):
    cosmos, redis = SdkCosmos(), FakeRedis()
    if state == "redis disabled":
        store = AppSettingsStore(cosmos)
    else:
        store = published_store(cosmos, redis)
        if state == "Redis unavailable":
            redis.failed = True
        else:
            redis.raw = save_marker(time.time() + 60)
    settings = load_get_settings(store)()
    assert type(settings) is dict
    assert type(settings["nested"]) is dict


def settings_store_during_another_save(world):
    """Serve the world's settings from Cosmos while another worker's save is in progress."""
    cosmos, redis = SdkCosmos({**world.settings, "id": "app_settings", "_etag": "1"}), FakeRedis()
    redis.raw = save_marker(time.time() + 600)
    return cosmos, AppSettingsStore(cosmos, redis, redis_required=True)


@pytest.mark.parametrize("capability_id", GATHER_CAPABILITIES)
def test_retained_results_are_usable_while_another_worker_saves_settings(capability_id):
    """Step preflight, admission and the finalization recheck all read settings mid-save."""
    with ExternalSourceWorld(capability_id) as world:
        world.run["user_message"] = "Read https://public.example/page."
        cosmos, store = settings_store_during_another_save(world)
        read_settings = load_get_settings(store)
        provider = world.provider(read_settings=read_settings)
        world.preflight(provider)
        catalog = world.admit(provider)
        task = world.persist(world.service(provider, catalog), catalog)
        reference = task.output("prepared")
        finalizer = world.service(world.provider(read_settings=read_settings))
        reader = finalizer.open_result(reference, allow_partial=True, require_current_sources=True)
        reader.recheck()
        assert reader.read_value() == world.prepared
        # Cosmos served every settings read, the path that used to return CosmosDict.
        assert cosmos.tokens
        assert json.loads(store.redis.raw)["state"] == "pending"


@pytest.mark.parametrize("capability_id", ("web_search", "action_invoke"))
def test_access_checks_still_require_exactly_dict(capability_id):
    """The fix belongs to the store: a dict subclass is still refused, as in production."""
    with ExternalSourceWorld(capability_id) as world:
        _provider, _catalog, reference = world.save()
        sdk_settings = CosmosDict(copy.deepcopy(world.settings), response_headers=CaseInsensitiveDict())
        provider = world.provider(read_settings=lambda: copy.deepcopy(sdk_settings))
        with pytest.raises(ResultUnavailableError) as preflight:
            world.preflight(provider)
        assert preflight.value.code == "result_external_context_unavailable"
        with pytest.raises(ResultUnavailableError) as finalization:
            world.service(provider).open_result(
                reference, allow_partial=True, require_current_sources=True,
            ).recheck()
        assert finalization.value.code == "result_external_context_unavailable"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
