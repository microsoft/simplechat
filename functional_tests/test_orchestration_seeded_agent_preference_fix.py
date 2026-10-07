#!/usr/bin/env python3
# test_orchestration_seeded_agent_preference_fix.py
"""
Functional test for an agent the user picked running while their agent preference is off.
Version: 0.261.282
Implemented in: 0.261.282

Picking an agent in the composer is itself the permission to use that agent, so planning
and execution run it even while the user's general "Enable Agents" preference is off. The
external-source provider that rechecks each agent step before it runs ignored the pick, so
the step the planner had just produced was refused with
result_external_capability_unavailable. This test ensures the provider honours the pick for
that agent only: the catalog is narrowed to the run's selection, current scope, membership,
governance and enabled state are still rechecked, and an unpicked, unresolvable or
malformed selection still fails closed.
"""

from copy import deepcopy
import os
import sys
import types
from unittest.mock import Mock, patch

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_orchestration_external_sources import ExternalSourceWorld  # noqa: E402
from functions_orchestration_context import CatalogResolutionError, resolve_agent_catalog  # noqa: E402
from functions_orchestration_results import ResultUnavailableError  # noqa: E402
from test_support.orchestration_research import _definitions  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX_DOC = os.path.join(
    REPO_ROOT, "docs", "explanation", "fixes",
    "ORCHESTRATION_SELECTED_AGENT_DISABLED_PREFERENCE_FIX.md",
)
ADMIN_DOC = os.path.join(REPO_ROOT, "docs", "admin", "orchestration.md")

# The composer's selection as the client sends it. It narrows the catalog; it never proves access.
SELECTION = {"name": "Lookup", "id": "agent-1", "is_group": True, "group_id": "group-a"}
PERSONAL_SELECTION = {
    "name": "m365", "id": "owner_m365", "is_global": False, "is_group": False, "group_id": None,
}


def select_agent(world, agent=None):
    world.run["seeds"] = {"agent": deepcopy(SELECTION if agent is None else agent)}


def production_catalog(world):
    """Run the real resolve_agent_catalog over the fixture's agents, recording each lookup."""
    builder = Mock(side_effect=lambda user_id, *, settings, user_groups: world.catalog(
        user_id, settings=settings,
    ))
    module = types.ModuleType("functions_agent_catalog")
    module.build_accessible_agent_catalog = builder
    module.build_agent_catalog_key = _definitions(
        "functions_agent_catalog.py", names={"build_agent_catalog_key"},
    )["build_agent_catalog_key"]
    world.stack.enter_context(patch.dict(sys.modules, {"functions_agent_catalog": module}))
    return builder


def provider(world):
    return world.provider(agent_catalog_reader=resolve_agent_catalog)


def save(world, current):
    catalog = world.admit(current)
    assert len(catalog) == 1
    assert next(iter(catalog.values())).source_type == "agent"
    return world.persist(world.service(current, catalog), catalog).output("prepared")


def read(world, reader, output):
    return world.service(reader).open_result(output, require_current_sources=True).read_value()


def test_version_includes_seeded_agent_preference_fix():
    assert_app_version_at_least("0.261.282")


def test_fix_and_troubleshooting_docs_describe_the_fix():
    with open(FIX_DOC, encoding="utf-8") as handle:
        fix_doc = handle.read()
    with open(ADMIN_DOC, encoding="utf-8") as handle:
        admin_doc = handle.read()
    assert "Fixed in version: **0.261.282**" in fix_doc
    assert "result_external_capability_unavailable" in fix_doc
    assert "| Before 0.261.282, an Ask an agent step" in admin_doc
    assert "ORCHESTRATION_SELECTED_AGENT_DISABLED_PREFERENCE_FIX" in admin_doc


def test_the_reported_personal_agent_runs_while_agents_are_off():
    """The incident: a personal agent picked in the composer while Enable Agents was off."""
    with ExternalSourceWorld("agent_invoke") as world:
        production_catalog(world)
        world.services.add_agent("owner_m365", scope="personal", scope_id="owner", name="m365")
        world.run["plan"]["steps"][0]["arguments"] = {"agent_name": "m365"}
        world.agent_selector = "personal:owner:owner_m365"
        select_agent(world, PERSONAL_SELECTION)
        world.user_enable_agents = False

        current = provider(world)
        current.preflight_session_acquisition(
            "agent", producer=world.fixture.producer, selector=world.agent_selector,
        )
        output = save(world, current)
        assert read(world, provider(world), output) == world.prepared


@pytest.mark.parametrize("preference", (False, True))
def test_a_picked_agent_runs_and_stays_readable_whatever_the_preference(preference):
    with ExternalSourceWorld("agent_invoke") as world:
        builder = production_catalog(world)
        select_agent(world)
        world.user_enable_agents = preference

        current = provider(world)
        world.preflight(current)
        current.preflight_session_acquisition(
            "agent", producer=world.fixture.producer, selector=world.agent_selector,
        )
        output = save(world, current)
        assert read(world, provider(world), output) == world.prepared
        assert builder.call_count >= 4
        assert all(call.kwargs["user_groups"] == ["group-a"] for call in builder.call_args_list)


@pytest.mark.parametrize("revoke", ("membership", "governance", "scope", "disabled"))
def test_a_picked_agent_still_needs_current_access(revoke):
    with ExternalSourceWorld("agent_invoke") as world:
        production_catalog(world)
        select_agent(world)
        world.user_enable_agents = False
        output = save(world, provider(world))
        assert read(world, provider(world), output) == world.prepared

        if revoke == "membership":
            world.services.roles.clear()
        elif revoke == "governance":
            world.services.denied_features.add("governance_group_agents")
        elif revoke == "scope":
            world.settings["allow_group_agents"] = False
        else:
            world.services.records["agents", "group"]["group-a", "agent-1"]["is_enabled"] = False
        with pytest.raises(ResultUnavailableError):
            read(world, provider(world), output)
        with pytest.raises(ResultUnavailableError):
            world.preflight(provider(world))


def test_an_agent_the_user_did_not_pick_still_follows_the_preference():
    with ExternalSourceWorld("agent_invoke") as world:
        builder = production_catalog(world)
        output = save(world, provider(world))

        world.user_enable_agents = False
        with pytest.raises(ResultUnavailableError) as raised:
            world.preflight(provider(world))
        assert raised.value.code == "result_external_capability_unavailable"
        with pytest.raises(ResultUnavailableError):
            read(world, provider(world), output)
        assert all(call.kwargs["user_groups"] is None for call in builder.call_args_list)


def test_the_pick_lifts_the_preference_for_that_agent_only():
    with ExternalSourceWorld("agent_invoke") as world:
        production_catalog(world)
        world.services.add_agent("agent-2", scope="group", scope_id="group-a", name="Other")
        world.run["plan"]["steps"][0]["arguments"] = {"agent_name": "Other"}
        world.agent_selector = "group:group-a:agent-2"
        select_agent(world)
        world.user_enable_agents = False

        current = provider(world)
        for attempt in (world.preflight, world.admit):
            with pytest.raises(ResultUnavailableError) as raised:
                attempt(current)
            assert raised.value.code == "result_external_source_unavailable"

        # The same step runs once agents are on and nothing was picked.
        del world.run["seeds"]
        world.user_enable_agents = True
        world.preflight(current)


@pytest.mark.parametrize("preference", (False, True))
@pytest.mark.parametrize("selection", (
    {**SELECTION, "id": "agent-removed"},
    {**SELECTION, "group_id": "group-b"},
    {"name": "Lookup"},
))
def test_a_pick_that_no_longer_resolves_is_unavailable(selection, preference):
    with ExternalSourceWorld("agent_invoke") as world:
        production_catalog(world)
        select_agent(world, selection)
        world.user_enable_agents = preference
        with pytest.raises(ResultUnavailableError) as raised:
            world.preflight(provider(world))
        assert raised.value.code == "result_external_source_unavailable"
        assert isinstance(raised.value.__cause__, CatalogResolutionError)
        assert raised.value.__cause__.code == "selected_agent_unavailable"


@pytest.mark.parametrize("preference", (False, True))
def test_a_narrowed_catalog_wider_than_the_pick_is_refused(preference):
    with ExternalSourceWorld("agent_invoke") as world:
        world.services.add_agent("agent-2", scope="group", scope_id="group-a", name="Other")
        select_agent(world)
        world.user_enable_agents = preference
        reader = Mock(side_effect=lambda user_id, *, seeds, settings: world.catalog(
            user_id, settings=settings,
        ))
        with pytest.raises(ResultUnavailableError) as raised:
            world.preflight(world.provider(agent_catalog_reader=reader))
        assert raised.value.code == "result_external_source_unavailable"
        assert reader.call_args.kwargs["seeds"] == {"agent": SELECTION}


def test_a_catalog_outage_is_not_reported_as_a_missing_pick():
    with ExternalSourceWorld("agent_invoke") as world:
        builder = production_catalog(world)
        builder.side_effect = RuntimeError("private storage diagnostic")
        select_agent(world)
        world.user_enable_agents = False
        with pytest.raises(CatalogResolutionError) as raised:
            world.preflight(provider(world))
        assert raised.value.code == "catalog_unavailable"


@pytest.mark.parametrize("seeds", (
    {"agent": {**SELECTION, "name": "   "}},
    {"agent": {**SELECTION, "name": None}},
    {"agent": {**SELECTION, "name": ["Lookup"]}},
    {"agent": "Lookup"},
    {"agent": None},
    {},
    ["agent"],
    None,
))
def test_a_malformed_pick_does_not_lift_the_preference(seeds):
    with ExternalSourceWorld("agent_invoke") as world:
        world.run["seeds"] = deepcopy(seeds)
        reader = Mock(side_effect=world.catalog)
        current = world.provider(agent_catalog_reader=reader)
        world.preflight(current)

        world.user_enable_agents = False
        with pytest.raises(ResultUnavailableError) as raised:
            world.preflight(current)
        assert raised.value.code == "result_external_capability_unavailable"
        assert reader.call_count == 2
        assert all(set(call.kwargs) == {"settings"} for call in reader.call_args_list)


def test_action_sources_never_receive_the_agent_pick():
    with ExternalSourceWorld("action_invoke") as world:
        select_agent(world)
        world.user_enable_agents = False
        reader = Mock(side_effect=world.catalog)
        current = world.provider(action_catalog_reader=reader)
        world.preflight(current)
        current.preflight_session_acquisition(
            "action", producer=world.fixture.producer, selector=world.action_selector,
        )
        assert len(world.admit(current)) == 1
        assert reader.call_count >= 3
        assert all(set(call.kwargs) == {"settings"} for call in reader.call_args_list)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
