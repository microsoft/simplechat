# test_orchestration_research_pre_effect.py
"""
Functional tests for deterministic research admission before acquisition.
Version: 0.261.205
Implemented in: 0.261.127
Single orchestration contract updated in: 0.261.139
Research planner profile restriction removed in: 0.261.205

Deep research with the default Source Review settings plans its searches and
links with the run's own attested planner model, as classic chat does. Current
and actual settings are compared without changing either, before any provider,
page or model effect; only a difference between them stops the step. Existing
constructor evidence, observed Foundry runs and current-only reads stay distinct.
Refs microsoft/simplechat#1509.
"""

from copy import deepcopy

import pytest

from test_orchestration_external_configuration_capture import capture_runtime, gather_modules, run_gather
from test_orchestration_external_metadata import metadata_world, new_attestor, producer
from test_orchestration_external_pre_effect import pre_effect_world
from test_orchestration_research_capture import (
    CHILD_LINKS, PLANNED_QUERY, answer_planner, research, serve_linked_pages,
)
from test_support.versioning import assert_app_version_at_least


PLANNER_FLAGS = (
    "enable_deep_source_review", "source_review_enable_llm_planning",
    "deep_research_enable_query_planning", "deep_research_max_search_queries_per_turn",
)
PROFILES = ["query-planning", "link-planning", "existing-defaults"]


def apply_profile(settings, profile):
    if profile == "query-planning":
        settings.update(deep_research_enable_query_planning=True, deep_research_max_search_queries_per_turn=2)
    elif profile == "link-planning":
        settings.update(enable_deep_source_review=True, source_review_enable_llm_planning=True)
    else:
        for name in PLANNER_FLAGS:
            settings.pop(name, None)


def assert_no_paid_effects(world):
    assert world.runtime.state.web == world.runtime.state.pages == world.runtime.state.invocations == []
    assert all(method == "GET" and "/assistants/" in url for method, url, _ in world.requests)


def test_research_planner_profile_gate_is_removed(metadata_world):
    """Version 0.261.205: no settings profile refuses deep research on its own."""
    assert_app_version_at_least("0.261.205")
    configuration = metadata_world.modules.configuration
    assert not hasattr(configuration, "is_research_acquisition_profile_supported")


@pytest.mark.parametrize("profile", PROFILES)
def test_pre_effect_admits_matching_planner_profiles_without_captures(pre_effect_world, profile):
    world = pre_effect_world
    owner = world.configure("deep_research")
    apply_profile(world.settings, profile)
    actual = deepcopy(world.settings)
    before_current, before_actual = deepcopy(world.settings), deepcopy(actual)
    checked = world.provider.preflight_gather_acquisition("deep_research", producer=owner, settings=actual)
    assert checked is None
    assert world.identity_reads == [("owner", "conversation")]
    assert world.attestor._captures == {}
    assert world.settings == before_current and actual == before_actual
    assert_no_paid_effects(world)


@pytest.mark.parametrize("changed_side", ["current", "actual"])
@pytest.mark.parametrize("profile", PROFILES)
def test_pre_effect_refuses_a_planner_profile_changed_on_one_side(pre_effect_world, changed_side, profile):
    world = pre_effect_world
    owner = world.configure("deep_research")
    actual = deepcopy(world.settings)
    apply_profile(world.settings if changed_side == "current" else actual, profile)
    before_current, before_actual = deepcopy(world.settings), deepcopy(actual)
    with pytest.raises(world.modules.configuration.ResultUnavailableError) as raised:
        world.provider.preflight_gather_acquisition("deep_research", producer=owner, settings=actual)
    assert raised.value.code == "external_configuration_changed"
    assert world.attestor._captures == {}
    assert world.settings == before_current and actual == before_actual
    assert_no_paid_effects(world)


@pytest.mark.parametrize("changed_side", ["current", "actual"])
@pytest.mark.parametrize("switch", ["deep_research_enable_query_planning", "source_review_enable_llm_planning"])
def test_pre_effect_refuses_a_planner_switch_changed_alone(pre_effect_world, changed_side, switch):
    """Version 0.261.205: each planner switch is compared on its own, now that planners run."""
    world = pre_effect_world
    owner = world.configure("deep_research")
    apply_profile(world.settings, "existing-defaults")
    actual = deepcopy(world.settings)
    (world.settings if changed_side == "current" else actual)[switch] = False
    before_current, before_actual = deepcopy(world.settings), deepcopy(actual)
    with pytest.raises(world.modules.configuration.ResultUnavailableError) as raised:
        world.provider.preflight_gather_acquisition("deep_research", producer=owner, settings=actual)
    assert raised.value.code == "external_configuration_changed"
    assert world.attestor._captures == {}
    assert world.settings == before_current and actual == before_actual
    assert_no_paid_effects(world)


@pytest.mark.parametrize("web_enabled", [None, 0, 1, "false", "true"])
def test_pre_effect_rejects_invalid_web_flags_without_boolean_coercion(pre_effect_world, web_enabled):
    world = pre_effect_world
    owner = world.configure("deep_research")
    world.settings["enable_web_search"] = web_enabled
    actual = deepcopy(world.settings)
    with pytest.raises(world.modules.configuration.ExternalConfigurationServiceError) as raised:
        world.provider.preflight_gather_acquisition("deep_research", producer=owner, settings=actual)
    assert raised.value.code == "external_configuration_metadata_invalid"
    assert raised.value.retryable is False
    assert world.settings["enable_web_search"] == actual["enable_web_search"] == web_enabled
    assert world.attestor._captures == {}
    assert_no_paid_effects(world)


def test_default_research_settings_plan_searches_and_links_with_the_attested_planner(research, monkeypatch):
    """The settings that were refused before 0.261.205 now complete, retain and recover."""
    state = research
    for name in PLANNER_FLAGS:
        state.runtime.settings.pop(name, None)
    fetched = serve_linked_pages(state, monkeypatch)
    calls = answer_planner(state)
    before = deepcopy(state.runtime.settings)
    _, result = run_gather(state.runtime, "deep_research")
    assert result["status"] == "completed", result
    assert [call["kind"] for call in calls] == ["query", "link"]
    assert all(call["attested"] > 0 and call["model"] == state.binding.deployment for call in calls)
    assert calls[0]["request"]["max_total_queries"] == 8
    assert 1 < len(state.runtime.state.web) <= 8
    assert any(PLANNED_QUERY in repr(invocation["messages"]) for invocation in state.runtime.state.invocations)
    assert fetched[-1] == CHILD_LINKS[-1] and CHILD_LINKS[0] not in fetched
    assert state.runtime.settings == before
    task = state.retention.retain_gather_result(state.step, state.context, result, source_manifest=[])
    fresh = state.make_attestor()
    reader = state.world.provider(read_configuration=fresh.current, configuration_admitter=None)
    recovered = state.world.service(reader).recover_task_result(
        producer=state.context.result_producer(state.step), input_fingerprint=state.fingerprint,
    )
    assert recovered == task
    assert fresh._captures == {}
    assert state.planner_calls.call_count == 2


@pytest.mark.parametrize("overrides,expected_queries", [
    ({
        "enable_web_search": False, "deep_research_enable_query_planning": True,
        "deep_research_max_search_queries_per_turn": 3,
        "enable_deep_source_review": False, "source_review_enable_llm_planning": True,
    }, 0),
    ({
        "enable_web_search": True, "deep_research_enable_query_planning": True,
        "deep_research_max_search_queries_per_turn": 1,
        "enable_deep_source_review": False, "source_review_enable_llm_planning": True,
    }, 1),
    ({
        "enable_web_search": True, "deep_research_enable_query_planning": "false",
        "deep_research_max_search_queries_per_turn": 3,
        "enable_deep_source_review": True, "source_review_enable_llm_planning": "false",
    }, 3),
])
def test_profiles_without_an_active_planner_never_call_the_model(research, overrides, expected_queries):
    state = research
    state.runtime.settings.update(overrides)
    before = deepcopy(state.runtime.settings)
    _, result = run_gather(state.runtime, "deep_research")
    assert result["status"] == "completed", result
    assert state.runtime.settings == before
    assert state.events[0] == ("deep_research", None)
    assert all(source_type == "deep_research" for source_type, _ in state.events)
    actual_runs = [
        source for _, source in state.events if source and source["kind"] == "foundry" and source["phase"] == "run"
    ]
    assert len(actual_runs) == len(state.runtime.state.web) == expected_queries
    assert state.runtime.state.pages
    state.planner_calls.assert_not_called()
    task = state.retention.retain_gather_result(
        state.step, state.context, result, source_manifest=[],
    )
    fresh = state.make_attestor()
    reader = state.world.provider(read_configuration=fresh.current, configuration_admitter=None)
    recovered = state.world.service(reader).recover_task_result(
        producer=state.context.result_producer(state.step), input_fingerprint=state.fingerprint,
    )
    assert recovered == task
    assert fresh._captures == {}
    assert len(state.runtime.state.web) == expected_queries
    state.planner_calls.assert_not_called()


def test_current_only_read_does_not_rewrite_planner_settings(pre_effect_world):
    world = pre_effect_world
    owner = world.configure("deep_research")
    world.settings.update(
        deep_research_enable_query_planning=True, deep_research_max_search_queries_per_turn=2,
    )
    fresh = new_attestor(world)
    before = deepcopy(world.settings)
    current = fresh.current("deep_research", producer=owner, settings=world.settings)
    assert current.identity and current.revision
    assert fresh._captures == {}
    assert world.settings == before
    checked = world.provider.preflight_gather_acquisition(
        "deep_research", producer=producer(world, "deep_research"), settings=world.settings,
    )
    assert checked is None
    assert world.settings == before
    assert world.attestor._captures == {}
    assert_no_paid_effects(world)


def test_current_profile_change_after_preparation_stops_before_search(research):
    state = research
    state.runtime.settings = deepcopy(state.world.settings)
    capture = state.context.capture_external_source_configuration

    def change_current_profile(source_type, **kwargs):
        capture(source_type, **kwargs)
        if kwargs["source"] is None:
            state.world.settings.update(
                deep_research_enable_query_planning=True, deep_research_max_search_queries_per_turn=2,
            )

    state.context.capture_external_source_configuration = change_current_profile
    with pytest.raises(PermissionError) as raised:
        run_gather(state.runtime, "deep_research")
    assert raised.value.code == "result_unavailable"
    assert raised.value.authority_reason == "external_configuration_changed"
    assert state.events == [("deep_research", None)]
    assert all(method == "GET" and "/assistants/" in url for method, url, _ in state.metadata.requests)
    assert state.admissions == []
    assert state.runtime.state.web == state.runtime.state.pages == state.runtime.state.invocations == []
    state.planner_calls.assert_not_called()
