# test_orchestration_research_pre_effect.py
"""
Functional tests for deterministic research admission before acquisition.
Version: 0.261.127
Implemented in: 0.261.127

Canonical Source Review settings determine whether a captured research profile
can make unattested LLM planner requests. Check current and actual settings
without changing either, before metadata/provider/page/model work. Existing
constructor evidence, observed Foundry runs and current-only reads stay distinct.
Refs microsoft/simplechat#1509.
"""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_orchestration_external_configuration_capture import capture_runtime, gather_modules, run_gather
from test_orchestration_external_metadata import metadata_world, new_attestor, producer
from test_orchestration_external_pre_effect import pre_effect_world
from test_orchestration_research_capture import research


@pytest.mark.parametrize("settings,expected", [
    pytest.param({}, False, id="existing-defaults-use-link-planning"),
    pytest.param({"enable_deep_source_review": False}, True, id="no-web-or-deep-review"),
    pytest.param({
        "enable_web_search": True, "enable_deep_source_review": False,
    }, False, id="existing-query-planning-default"),
    pytest.param({
        "enable_web_search": True, "enable_deep_source_review": False,
        "deep_research_max_search_queries_per_turn": 1,
    }, True, id="one-query-never-needs-query-planner"),
    pytest.param({
        "enable_web_search": True, "enable_deep_source_review": False,
        "deep_research_max_search_queries_per_turn": 0,
    }, True, id="query-count-clamped-to-one"),
    pytest.param({
        "enable_web_search": True, "enable_deep_source_review": False,
        "deep_research_max_search_queries_per_turn": "1",
    }, True, id="normalized-one-query"),
    pytest.param({
        "enable_web_search": True, "enable_deep_source_review": False,
        "deep_research_max_search_queries_per_turn": 2,
    }, False, id="multiple-queries-can-use-model"),
    pytest.param({
        "enable_web_search": True, "enable_deep_source_review": False,
        "deep_research_max_search_queries_per_turn": "invalid",
    }, False, id="invalid-query-count-keeps-existing-default"),
    pytest.param({
        "enable_web_search": True, "enable_deep_source_review": False,
        "deep_research_max_search_queries_per_turn": None,
    }, False, id="missing-query-count-keeps-existing-default"),
    pytest.param({
        "enable_web_search": True, "enable_deep_source_review": False,
        "deep_research_max_search_queries_per_turn": 99,
        "deep_research_enable_query_planning": False,
    }, True, id="bounded-deterministic-multiple-queries"),
    pytest.param({
        "enable_web_search": True, "enable_deep_source_review": "off",
        "deep_research_enable_query_planning": "false",
    }, True, id="false-strings-use-canonical-normalization"),
    pytest.param({
        "enable_web_search": True, "enable_deep_source_review": "off",
        "deep_research_enable_query_planning": "true",
    }, False, id="true-query-planning-string"),
    pytest.param({
        "enable_web_search": False, "enable_deep_source_review": False,
        "deep_research_enable_query_planning": True,
    }, True, id="query-planning-inactive-without-web"),
    pytest.param({
        "enable_web_search": False, "enable_deep_source_review": True,
        "source_review_enable_llm_planning": False,
    }, True, id="deterministic-deep-link-selection"),
    pytest.param({
        "enable_web_search": False, "enable_deep_source_review": True,
        "source_review_enable_llm_planning": "false",
    }, True, id="normalized-deterministic-link-selection"),
    pytest.param({
        "enable_web_search": False, "enable_deep_source_review": True,
        "source_review_enable_llm_planning": True, "source_review_max_depth": 0,
    }, False, id="zero-depth-does-not-relax-profile-boundary"),
    pytest.param({
        "enable_web_search": False, "enable_deep_source_review": True,
        "source_review_enable_llm_planning": True, "source_review_max_pages_per_turn": 1,
    }, False, id="one-page-does-not-relax-profile-boundary"),
    pytest.param({
        "enable_web_search": False, "enable_deep_source_review": "false",
        "source_review_enable_llm_planning": "true",
    }, True, id="link-planning-inactive-without-deep-review"),
])
def test_shared_profile_uses_existing_normalization_without_mutation_or_io(
    metadata_world, settings, expected,
):
    world = metadata_world
    before = deepcopy(settings)
    supported = world.modules.configuration.is_research_acquisition_profile_supported(settings)
    assert supported is expected
    assert settings == before
    assert world.requests == world.credentials == world.run_store.reads == []


@pytest.mark.parametrize("web_enabled", [None, 0, 1, "false", "true"])
def test_profile_rejects_invalid_web_flags_without_boolean_coercion(metadata_world, web_enabled):
    world = metadata_world
    settings = {"enable_web_search": web_enabled, "enable_deep_source_review": False}
    before = deepcopy(settings)
    with pytest.raises(world.modules.configuration.ExternalConfigurationServiceError) as raised:
        world.modules.configuration.is_research_acquisition_profile_supported(settings)
    assert raised.value.code == "external_configuration_metadata_invalid"
    assert raised.value.retryable is False
    assert settings == before
    assert world.requests == world.credentials == []


@pytest.mark.parametrize("settings", [None, [], False])
def test_profile_rejects_non_settings_objects(metadata_world, settings):
    with pytest.raises(metadata_world.modules.contracts.ResultContractError):
        metadata_world.modules.configuration.is_research_acquisition_profile_supported(settings)


@pytest.mark.parametrize("changed_side", ["current", "actual"])
@pytest.mark.parametrize("profile", ["query-planning", "link-planning", "existing-defaults"])
def test_pre_effect_rejects_either_unattested_profile_before_metadata(
    pre_effect_world, changed_side, profile,
):
    world = pre_effect_world
    owner = world.configure("deep_research")
    actual = deepcopy(world.settings)
    changed = world.settings if changed_side == "current" else actual
    if profile == "query-planning":
        changed.update(deep_research_enable_query_planning=True, deep_research_max_search_queries_per_turn=2)
    elif profile == "link-planning":
        changed.update(enable_deep_source_review=True, source_review_enable_llm_planning=True)
    else:
        for name in (
            "enable_deep_source_review", "source_review_enable_llm_planning",
            "deep_research_enable_query_planning", "deep_research_max_search_queries_per_turn",
        ):
            changed.pop(name, None)
    metadata = Mock(side_effect=AssertionError("Unsupported profiles must stop before metadata acquisition."))
    world.attestor.read_current_source = metadata
    before_current, before_actual = deepcopy(world.settings), deepcopy(actual)
    with pytest.raises(world.modules.configuration.ResultUnavailableError) as raised:
        world.provider.preflight_gather_acquisition(
            "deep_research", producer=owner, settings=actual,
        )
    assert raised.value.code == "external_configuration_research_profile_unsupported"
    metadata.assert_not_called()
    assert world.identity_reads == [("owner", "conversation")]
    assert world.attestor._captures == {}
    assert world.requests == world.credentials == world.run_store.reads == []
    assert world.settings == before_current and actual == before_actual
    assert world.runtime.state.web == world.runtime.state.pages == world.runtime.state.invocations == []


@pytest.mark.parametrize("changed_side", ["current", "actual"])
@pytest.mark.parametrize("overrides", [
    {"deep_research_enable_query_planning": True, "deep_research_max_search_queries_per_turn": 2},
    {"enable_deep_source_review": True, "source_review_enable_llm_planning": True},
])
def test_real_research_refuses_profiles_before_constructor_capture_or_paid_effects(
    research, monkeypatch, changed_side, overrides,
):
    state = research
    state.runtime.settings = deepcopy(state.world.settings)
    changed = state.world.settings if changed_side == "current" else state.runtime.settings
    changed.update(overrides)
    before_current, before_actual = deepcopy(state.world.settings), deepcopy(state.runtime.settings)
    getter = Mock(wraps=state.metadata.modules.models.planner_client_construction_source)
    monkeypatch.setattr(state.metadata.modules.models, "planner_client_construction_source", getter)
    with pytest.raises(PermissionError) as raised:
        run_gather(state.runtime, "deep_research")
    assert raised.value.code == "result_unavailable"
    assert raised.value.retryable is False
    getter.assert_not_called()
    state.planner_calls.assert_not_called()
    assert state.events == state.admissions == []
    assert state.attestor._captures == {}
    assert state.metadata.requests == state.runtime.state.web == state.runtime.state.pages == []
    assert state.runtime.state.invocations == state.runtime.state.clients == state.runtime.state.credentials == []
    assert state.world.settings == before_current and state.runtime.settings == before_actual


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
def test_supported_profiles_use_real_research_without_changing_flags_or_request_controls(
    research, overrides, expected_queries,
):
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


def test_new_acquisition_profile_check_does_not_rewrite_current_only_configuration(pre_effect_world):
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
    with pytest.raises(world.modules.configuration.ResultUnavailableError):
        world.provider.preflight_gather_acquisition(
            "deep_research", producer=producer(world, "deep_research"), settings=world.settings,
        )
    assert world.runtime.state.web == world.runtime.state.pages == []


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
    with pytest.raises(PermissionError):
        run_gather(state.runtime, "deep_research")
    assert state.events == [("deep_research", None)]
    assert len(state.metadata.requests) == 1
    assert state.admissions == []
    assert state.runtime.state.web == state.runtime.state.pages == state.runtime.state.invocations == []
    state.planner_calls.assert_not_called()


def test_v1_keeps_existing_llm_query_planning_without_new_capture_checks(research):
    state = research
    state.context.plan_contract_version = 1
    state.runtime.settings.update(
        enable_web_search=True, deep_research_enable_query_planning=True,
        deep_research_max_search_queries_per_turn=2, enable_deep_source_review=False,
    )
    state.planner_calls.side_effect = None
    state.planner_calls.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=json.dumps({"queries": [{"query": "Current source details", "reason": "Related facts"}]}),
    ))])
    forbidden = Mock(side_effect=AssertionError("V1 must not use v2 acquisition gates."))
    state.context.capture_external_source_configuration = forbidden
    before = deepcopy(state.runtime.settings)
    _, result = run_gather(state.runtime, "deep_research")
    assert result["status"] == "completed", result
    assert state.planner_calls.call_count > 0
    assert state.runtime.settings == before
    assert state.events == state.captures == state.admissions == []
    forbidden.assert_not_called()
