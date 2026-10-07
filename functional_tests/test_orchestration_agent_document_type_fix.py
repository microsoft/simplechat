#!/usr/bin/env python3
# test_orchestration_agent_document_type_fix.py
"""
Functional test for Ask an agent steps refused because of the stored agent's type.
Version: 0.261.291
Implemented in: 0.261.291

The pinned azure-cosmos 4.9.0 returns a stored agent from a point read as CosmosDict, a
dict subclass that deepcopy keeps. The external-source provider required the agent that
resolve_delegation_agent returned to be exactly a dict, so it refused every orchestrated
Ask an agent step before the agent ran, with result_external_source_unavailable
(microsoft/simplechat#1699). This test ensures the resolver returns a plain dict, the
provider accepts any dict while still matching the exact scoped reference, agents the
user can't reach are still refused, and each refusal logs the check that failed without
logging identifiers.
"""

from copy import deepcopy
import logging
import os
import sys
import types
from unittest.mock import Mock, patch

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_orchestration_external_sources import ExternalSourceWorld  # noqa: E402
from functions_appinsights import _build_logger_extra, workflow_log_context  # noqa: E402
from functions_orchestration_context import CatalogResolutionError, resolve_agent_catalog  # noqa: E402
from functions_orchestration_results import ResultUnavailableError  # noqa: E402
from test_support.agent_delegation import (  # noqa: E402
    CosmosDictLike,
    DelegationServices,
    delegation_environment,
    reference,
)
from test_support.orchestration_research import _definitions  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX_DOC = os.path.join(
    REPO_ROOT, "docs", "explanation", "fixes", "ORCHESTRATION_AGENT_DOCUMENT_TYPE_FIX.md",
)
ADMIN_DOC = os.path.join(REPO_ROOT, "docs", "admin", "orchestration.md")
LOGGING_DOC = os.path.join(REPO_ROOT, "docs", "reference", "logging-tags.md")

LOG_EVENT = "functions_orchestration_external_sources.log_event"
REFUSAL_MESSAGE = "[ORCHESTRATION_EXTERNAL_SOURCES] A step's source was refused."
SOURCE_UNAVAILABLE = "result_external_source_unavailable"
CAPABILITY_UNAVAILABLE = "result_external_capability_unavailable"
# Raw identifiers from the fixture. None of them may reach a refusal event.
RAW_IDENTIFIERS = (
    "owner", "conversation-1", "external-run", "agent-1", "owner_m365", "m365", "Lookup",
    "group-a", "intruder",
)

PERSONAL_SELECTION = {
    "name": "m365", "id": "owner_m365", "is_global": False, "is_group": False, "group_id": None,
}
GROUP_SELECTION = {"name": "Lookup", "id": "agent-1", "is_group": True, "group_id": "group-a"}


def production_catalog(world):
    """Run the real resolve_agent_catalog over the fixture's agents."""
    module = types.ModuleType("functions_agent_catalog")
    module.build_accessible_agent_catalog = Mock(
        side_effect=lambda user_id, *, settings, user_groups: world.catalog(user_id, settings=settings),
    )
    module.build_agent_catalog_key = _definitions(
        "functions_agent_catalog.py", names={"build_agent_catalog_key"},
    )["build_agent_catalog_key"]
    world.stack.enter_context(patch.dict(sys.modules, {"functions_agent_catalog": module}))


def production_provider(world, **overrides):
    return world.provider(agent_catalog_reader=resolve_agent_catalog, **overrides)


def use_personal_m365(world):
    """The reported agent: the user's personal m365 agent, picked in the composer."""
    world.services.add_agent("owner_m365", scope="personal", scope_id="owner", name="m365")
    world.run["plan"]["steps"][0]["arguments"] = {"agent_name": "m365"}
    world.agent_selector = "personal:owner:owner_m365"
    world.run["seeds"] = {"agent": deepcopy(PERSONAL_SELECTION)}


def spy_point_reads(world, kind, scope):
    """Record what the fixture's Cosmos point reads return to the code under test."""
    container = world.services.containers[kind, scope]
    original = container.read_item.side_effect
    returned = []

    def read_item(**kwargs):
        record = original(**kwargs)
        returned.append(record)
        return record

    container.read_item.side_effect = read_item
    return returned


def run_step(world, current, source_type):
    world.preflight(current)
    current.preflight_session_acquisition(
        source_type, producer=world.fixture.producer, selector=world.selected_integration(),
    )


def save(world, current, source_type):
    catalog = world.admit(current)
    assert len(catalog) == 1
    assert next(iter(catalog.values())).source_type == source_type
    return world.persist(world.service(current, catalog), catalog).output("prepared")


def read(world, reader, output):
    return world.service(reader).open_result(output, require_current_sources=True).read_value()


def refusal_events(log_event):
    return [call for call in log_event.call_args_list if call.args and call.args[0] == REFUSAL_MESSAGE]


def only_refusal(log_event):
    events = refusal_events(log_event)
    assert len(events) == 1, events
    assert not any(identifier in repr(events[0]) for identifier in RAW_IDENTIFIERS), events[0]
    return events[0]


def expected_correlation():
    return workflow_log_context(conversation_id="conversation-1", run_id="external-run", step_id="gather")


def test_version_includes_agent_document_type_fix():
    assert_app_version_at_least("0.261.291")


def test_fake_point_reads_return_a_dict_subclass_like_the_sdk():
    services = DelegationServices()
    services.add_agent("agent-1", scope="group", scope_id="group-a")
    container = services.containers["agents", "group"]

    record = container.read_item(item="agent-1", partition_key="group-a")
    assert isinstance(record, dict)
    assert type(record) is CosmosDictLike
    assert type(deepcopy(record)) is CosmosDictLike

    rows = container.query_items(
        query="SELECT * FROM c WHERE c.group_id = @scope_id",
        parameters=[{"name": "@scope_id", "value": "group-a"}], partition_key="group-a",
    )
    assert rows
    assert all(type(row) is dict for row in rows)


def test_the_pinned_sdk_point_read_type_behaves_like_the_fake():
    responses = pytest.importorskip("azure.cosmos._cosmos_responses")
    utils = pytest.importorskip("azure.core.utils")
    sdk_record = responses.CosmosDict({"id": "agent-1"}, response_headers=utils.CaseInsensitiveDict())
    for record in (sdk_record, CosmosDictLike({"id": "agent-1"})):
        assert isinstance(record, dict)
        assert type(record) is not dict
        assert type(deepcopy(record)) is type(record)
        assert type(dict(record)) is dict
        assert dict(record) == {"id": "agent-1"}


@pytest.mark.parametrize("scope_type, scope_id", (
    ("personal", "actor"), ("group", "group-a"), ("global", "global"),
))
def test_the_resolver_returns_a_plain_dict_for_every_scope(scope_type, scope_id):
    with delegation_environment() as (helper, services):
        services.add_agent("target-id", scope=scope_type, scope_id=scope_id)
        resolved = helper.resolve_delegation_agent(
            reference("target-id", scope_type, scope_id), user_id="actor", settings=services.settings,
        )
    assert type(resolved) is dict
    assert (resolved["id"], resolved["scope_type"], resolved["scope_id"]) == ("target-id", scope_type, scope_id)
    # The document's own fields survive, including the ETag that conditional writes need.
    assert resolved["_etag"] == '"stored-etag"'


@pytest.mark.parametrize("preference", (False, True))
def test_the_reported_personal_agent_runs_and_stays_readable(preference):
    """The incident: a personal m365 agent picked in the composer, read back from Cosmos."""
    with ExternalSourceWorld("agent_invoke") as world:
        production_catalog(world)
        use_personal_m365(world)
        world.user_enable_agents = preference
        reads = spy_point_reads(world, "agents", "personal")

        current = production_provider(world)
        run_step(world, current, "agent")
        output = save(world, current, "agent")
        value = read(world, production_provider(world), output)
        assert value == world.prepared
        assert reads
        assert all(type(record) is CosmosDictLike for record in reads)


@pytest.mark.parametrize("picked", (False, True))
def test_a_group_agent_runs_and_stays_readable(picked):
    with ExternalSourceWorld("agent_invoke") as world:
        production_catalog(world)
        if picked:
            world.run["seeds"] = {"agent": deepcopy(GROUP_SELECTION)}
        reads = spy_point_reads(world, "agents", "group")

        current = production_provider(world)
        run_step(world, current, "agent")
        output = save(world, current, "agent")
        value = read(world, production_provider(world), output)
        assert value == world.prepared
        assert reads
        assert all(type(record) is CosmosDictLike for record in reads)


def test_the_provider_accepts_a_dict_subclass_from_its_resolver():
    """Defence in depth: the provider doesn't depend on the resolver unwrapping the SDK type."""
    def resolver(agent, *, user_id, settings):
        return CosmosDictLike({**agent, "name": "Lookup", "agent_type": "local", "is_enabled": True})

    with ExternalSourceWorld("agent_invoke") as world:
        current = world.provider(agent_resolver=resolver)
        run_step(world, current, "agent")
        output = save(world, current, "agent")
        value = read(world, world.provider(agent_resolver=resolver), output)
        assert value == world.prepared


@pytest.mark.parametrize("returned, check", (
    (["agent-1"], "integration_not_mapping"),
    ("group:group-a:agent-1", "integration_not_mapping"),
    (None, "integration_not_mapping"),
    (CosmosDictLike({"id": "agent-2", "scope_type": "group", "scope_id": "group-a"}), "integration_reference_mismatch"),
    ({"id": "agent-1", "scope_type": "group", "scope_id": "group-b"}, "integration_reference_mismatch"),
))
def test_a_resolver_result_that_is_not_the_exact_agent_is_refused(returned, check):
    with ExternalSourceWorld("agent_invoke") as world:
        current = world.provider(agent_resolver=lambda agent, *, user_id, settings: deepcopy(returned))
        with patch(LOG_EVENT) as log_event, pytest.raises(ResultUnavailableError) as raised:
            world.preflight(current)
        assert raised.value.code == SOURCE_UNAVAILABLE
        reason = only_refusal(log_event).kwargs["extra"]["reason"]
        assert reason == check


def _revoke(world, revoke):
    if revoke == "disabled":
        world.services.records["agents", "group"]["group-a", "agent-1"]["is_enabled"] = False
    elif revoke == "membership":
        world.services.roles.clear()
    elif revoke == "governance":
        world.services.denied_features.add("governance_group_agents")
    elif revoke == "scope":
        world.settings["allow_group_agents"] = False
    elif revoke == "owner":
        world.services.add_agent("owner_m365", scope="personal", scope_id="owner", name="m365", user_id="intruder")
        world.run["plan"]["steps"][0]["arguments"] = {"agent_name": "m365"}
        world.agent_selector = "personal:owner:owner_m365"
    elif revoke == "missing":
        world.agent_selector = "group:group-a:agent-missing"


@pytest.mark.parametrize("revoke, check", (
    ("disabled", "integration_not_found"),
    ("membership", "integration_access_denied"),
    ("governance", "integration_access_denied"),
    ("scope", "integration_access_denied"),
    ("owner", "integration_access_denied"),
    ("missing", "selection_not_in_catalog"),
))
def test_agents_the_user_cannot_reach_are_still_refused_with_their_check(revoke, check):
    with ExternalSourceWorld("agent_invoke") as world:
        _revoke(world, revoke)
        with patch(LOG_EVENT) as log_event, pytest.raises(ResultUnavailableError) as raised:
            world.preflight(world.provider())
        assert raised.value.code == SOURCE_UNAVAILABLE
        event = only_refusal(log_event)
        assert event.kwargs["level"] == logging.WARNING
        assert event.kwargs["extra"] == {
            **expected_correlation(), "capability_id": "agent_invoke",
            "stage": "external_source_preflight", "authority_reason": SOURCE_UNAVAILABLE, "reason": check,
        }


def test_an_admission_refusal_logs_its_stage():
    with ExternalSourceWorld("agent_invoke") as world:
        current = world.provider()
        run_step(world, current, "agent")
        _revoke(world, "disabled")
        with patch(LOG_EVENT) as log_event, pytest.raises(ResultUnavailableError):
            world.admit(current)
        event = only_refusal(log_event)
        assert event.kwargs["level"] == logging.WARNING
        assert event.kwargs["extra"]["stage"] == "external_source_admission"
        assert event.kwargs["extra"]["reason"] == "integration_not_found"


def test_a_read_refusal_logs_its_stage_at_information_level():
    with ExternalSourceWorld("agent_invoke") as world:
        current = world.provider()
        run_step(world, current, "agent")
        output = save(world, current, "agent")
        _revoke(world, "disabled")
        with patch(LOG_EVENT) as log_event, pytest.raises(ResultUnavailableError):
            read(world, world.provider(), output)
        event = only_refusal(log_event)
        assert event.kwargs["level"] == logging.INFO
        assert event.kwargs["extra"] == {
            **expected_correlation(), "capability_id": "agent_invoke",
            "stage": "external_source_read", "authority_reason": SOURCE_UNAVAILABLE,
            "reason": "integration_not_found",
        }


def test_read_references_name_their_check():
    with ExternalSourceWorld("agent_invoke") as world:
        _provider, catalog, output = world.save()
        saved = next(iter(catalog.values()))

        with patch(LOG_EVENT) as log_event, pytest.raises(ResultUnavailableError):
            world.provider().authorize(
                saved, producer=world.fixture.producer, user_id="intruder", conversation_id="conversation-1",
            )
        reason = only_refusal(log_event).kwargs["extra"]["reason"]
        assert reason == "reference_binding_mismatch"

        # The catalog still has an agent, so the capability is offered, but not this one.
        world.catalog_override = [{
            "id": "agent-2", "name": "Other", "scope_type": "group", "scope_id": "group-a",
            "is_global": False, "is_group": True, "group_id": "group-a",
            "catalog_key": "group:group-a:agent-2",
        }]
        with patch(LOG_EVENT) as log_event, pytest.raises(ResultUnavailableError):
            read(world, world.provider(), output)
        reason = only_refusal(log_event).kwargs["extra"]["reason"]
        assert reason == "reference_not_in_catalog"


def test_capability_refusals_name_their_check():
    with ExternalSourceWorld("agent_invoke") as world:
        world.settings["enable_semantic_kernel"] = False
        with patch(LOG_EVENT) as log_event, pytest.raises(ResultUnavailableError) as raised:
            world.preflight(world.provider())
        assert raised.value.code == CAPABILITY_UNAVAILABLE
        reason = only_refusal(log_event).kwargs["extra"]["reason"]
        assert reason == "required_setting_off"

    with ExternalSourceWorld("agent_invoke") as world:
        world.settings["chat_orchestration_enabled_capabilities"] = "agent_invoke"
        with patch(LOG_EVENT) as log_event, pytest.raises(ResultUnavailableError):
            world.preflight(world.provider())
        reason = only_refusal(log_event).kwargs["extra"]["reason"]
        assert reason == "capability_allowlist_invalid"

    with ExternalSourceWorld("agent_invoke") as world:
        world.user_enable_agents = False
        with patch(LOG_EVENT) as log_event, pytest.raises(ResultUnavailableError):
            world.preflight(world.provider())
        reason = only_refusal(log_event).kwargs["extra"]["reason"]
        assert reason == "capability_not_available"

    with ExternalSourceWorld("url_fetch") as world:
        _provider, _catalog, output = world.save()
        world.roles = ("User",)
        with patch(LOG_EVENT) as log_event, pytest.raises(ResultUnavailableError):
            read(world, world.provider(), output)
        event = only_refusal(log_event)
        assert event.kwargs["extra"]["capability_id"] == "url_fetch"
        assert event.kwargs["extra"]["reason"] == "url_access_not_permitted"


def test_picked_agent_refusals_name_their_check():
    with ExternalSourceWorld("agent_invoke") as world:
        production_catalog(world)
        world.run["seeds"] = {"agent": {**GROUP_SELECTION, "id": "agent-removed"}}
        with patch(LOG_EVENT) as log_event, pytest.raises(ResultUnavailableError) as raised:
            world.preflight(production_provider(world))
        assert isinstance(raised.value.__cause__, CatalogResolutionError)
        reason = only_refusal(log_event).kwargs["extra"]["reason"]
        assert reason == "selected_agent_unavailable"

    with ExternalSourceWorld("agent_invoke") as world:
        world.services.add_agent("agent-2", scope="group", scope_id="group-a", name="Other")
        world.run["seeds"] = {"agent": deepcopy(GROUP_SELECTION)}
        reader = Mock(side_effect=lambda user_id, *, seeds, settings: world.catalog(user_id, settings=settings))
        with patch(LOG_EVENT) as log_event, pytest.raises(ResultUnavailableError):
            world.preflight(world.provider(agent_catalog_reader=reader))
        reason = only_refusal(log_event).kwargs["extra"]["reason"]
        assert reason == "selected_agent_ambiguous"


def test_refusal_properties_survive_the_log_allowlist():
    with ExternalSourceWorld("agent_invoke") as world:
        _revoke(world, "disabled")
        with patch(LOG_EVENT) as log_event, pytest.raises(ResultUnavailableError):
            world.preflight(world.provider())
    event = only_refusal(log_event)
    properties = _build_logger_extra(event.args[0], event.kwargs["extra"])
    correlation = expected_correlation()
    assert properties["sc_message"] == REFUSAL_MESSAGE
    assert properties["sc_stage"] == "external_source_preflight"
    assert properties["sc_reason"] == "integration_not_found"
    assert properties["sc_authority_reason"] == SOURCE_UNAVAILABLE
    assert properties["sc_capability_id"] == "agent_invoke"
    assert properties["sc_run_id_hash"] == correlation["run_id_hash"]
    assert properties["sc_step_id_hash"] == correlation["step_id_hash"]
    assert properties["sc_conversation_id_hash"] == correlation["conversation_id_hash"]


def test_successful_steps_log_no_refusal():
    with ExternalSourceWorld("agent_invoke") as world, patch(LOG_EVENT) as log_event:
        current = world.provider()
        run_step(world, current, "agent")
        output = save(world, current, "agent")
        value = read(world, world.provider(), output)
        assert value == world.prepared
    assert refusal_events(log_event) == []


def test_action_steps_are_unchanged_with_sdk_typed_reads():
    with ExternalSourceWorld("action_invoke") as world:
        reads = spy_point_reads(world, "actions", "group")
        current = world.provider()
        run_step(world, current, "action")
        output = save(world, current, "action")
        value = read(world, world.provider(), output)
        assert value == world.prepared
        assert reads
        assert all(type(record) is CosmosDictLike for record in reads)


def test_fix_admin_and_logging_docs_describe_the_fix():
    with open(FIX_DOC, encoding="utf-8") as handle:
        fix_doc = handle.read()
    with open(ADMIN_DOC, encoding="utf-8") as handle:
        admin_doc = handle.read()
    with open(LOGGING_DOC, encoding="utf-8") as handle:
        logging_doc = handle.read()
    assert "Fixed in version: **0.261.291**" in fix_doc
    assert "#1699" in fix_doc
    assert "result_external_source_unavailable" in fix_doc
    assert "| Before 0.261.291, every Ask an agent step" in admin_doc
    assert "ORCHESTRATION_AGENT_DOCUMENT_TYPE_FIX" in admin_doc
    assert "- `[ORCHESTRATION_EXTERNAL_SOURCES]`" in logging_doc
    assert f"| `{REFUSAL_MESSAGE}` |" in logging_doc


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
