#!/usr/bin/env python3
# test_orchestration_session_trusted_sources.py
"""
Functional test for session-trusted agent and action orchestration steps.
Version: 0.261.269
Implemented in: 0.261.269

Agent and action steps trust the signed-in session the way classic chat does. Their
admission and retained reads recheck the user's current access to the conversation, the
run's step and the exact agent or action, but never read, capture or compare the agent's
or action's configuration. Results admitted while that configuration was still attested
stay readable. Fixes microsoft/simplechat#1660 and refs #1661.
"""

from dataclasses import replace
import os
import sys
from unittest.mock import Mock

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_orchestration_external_sources import ExternalSourceWorld  # noqa: E402
from functions_orchestration_result_contracts import ResultContractError, canonical_digest  # noqa: E402
from functions_orchestration_results import ResultUnavailableError  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


INTEGRATIONS = ("agent_invoke", "action_invoke")
SOURCE_TYPES = {"agent_invoke": "agent", "action_invoke": "action"}
RECORDS = {
    "agent_invoke": (("agents", "group"), ("group-a", "agent-1")),
    "action_invoke": (("actions", "group"), ("group-a", "action-1")),
}


def unused_configuration():
    return Mock(side_effect=AssertionError("Session-trusted sources never read their configuration."))


def configuration_free_provider(world):
    unused = unused_configuration()
    provider = world.provider(
        read_configuration=unused, configuration_admitter=unused, acquisition_validator=unused,
    )
    return provider, unused


def read(world, provider, reference):
    return world.service(provider).open_result(reference, require_current_sources=True).read_value()


def test_version_includes_session_trusted_sources():
    assert_app_version_at_least("0.261.269")


@pytest.mark.parametrize("capability", INTEGRATIONS)
def test_admission_rechecks_access_without_reading_configuration(capability):
    with ExternalSourceWorld(capability) as world:
        provider, unused = configuration_free_provider(world)
        world.preflight(provider)
        provider.preflight_session_acquisition(
            SOURCE_TYPES[capability], producer=world.fixture.producer, selector=world.selected_integration(),
        )
        catalog = world.admit(provider)
        assert len(catalog) == 1
        reference = next(iter(catalog.values()))
        assert reference.source_type == SOURCE_TYPES[capability]
        assert reference.capability_id == capability
        assert reference.source_revision.startswith("configuration:")
        assert world.admit(provider) == catalog
        assert world.identity_reads >= 2 and world.catalog_reads >= 2
        unused.assert_not_called()


@pytest.mark.parametrize("capability", INTEGRATIONS)
def test_retained_results_survive_configuration_edits_until_access_is_revoked(capability):
    with ExternalSourceWorld(capability) as world:
        _provider, _catalog, output = world.save()
        reader, unused = configuration_free_provider(world)
        assert read(world, reader, output) == world.prepared

        collection, key = RECORDS[capability]
        record = world.services.records[collection][key]
        record["description"] = "Edited after the result was saved."
        record["endpoint"] = "https://changed.invalid"
        assert read(world, reader, output) == world.prepared

        world.services.roles.clear()
        with pytest.raises(ResultUnavailableError):
            read(world, reader, output)
        unused.assert_not_called()


@pytest.mark.parametrize("capability", INTEGRATIONS)
def test_references_admitted_under_configuration_attestation_stay_readable(capability):
    with ExternalSourceWorld(capability) as world:
        provider = world.provider()
        current = next(iter(world.admit(provider).values()))
        prefix = current.reference_id.rsplit(":", 1)[0]
        attested = replace(
            current,
            reference_id=f"{prefix}:{canonical_digest('attested-configuration-identity')}",
            source_revision="configuration:" + canonical_digest({"identity": "attested", "revision": "hmac"}),
        )
        catalog = {"external_" + canonical_digest(attested.to_dict())[:48]: attested}
        task = world.persist(world.service(provider, catalog), catalog)
        reader, unused = configuration_free_provider(world)
        assert read(world, reader, task.output("prepared")) == world.prepared

        world.services.roles.clear()
        with pytest.raises(ResultUnavailableError):
            read(world, reader, task.output("prepared"))
        unused.assert_not_called()


@pytest.mark.parametrize("capability", INTEGRATIONS)
def test_session_preflight_requires_current_access_to_the_exact_selection(capability):
    with ExternalSourceWorld(capability) as world:
        provider, unused = configuration_free_provider(world)
        producer = world.fixture.producer
        source_type = SOURCE_TYPES[capability]
        selector = world.selected_integration()
        assert provider.preflight_session_acquisition(source_type, producer=producer, selector=selector) is None

        with pytest.raises(ResultUnavailableError) as raised:
            provider.preflight_session_acquisition(source_type, producer=producer, selector="other-selection")
        assert raised.value.code == "result_external_source_unavailable"

        other = "action" if source_type == "agent" else "agent"
        for wrong in (other, "web", "url"):
            with pytest.raises(ResultContractError):
                provider.preflight_session_acquisition(wrong, producer=producer, selector=selector)

        world.roles = ()
        with pytest.raises(ResultUnavailableError) as raised:
            provider.preflight_session_acquisition(source_type, producer=producer, selector=selector)
        assert raised.value.code == "result_external_identity_unavailable"

        world.roles = ("User",)
        world.services.roles.clear()
        with pytest.raises(ResultUnavailableError):
            provider.preflight_session_acquisition(source_type, producer=producer, selector=selector)
        unused.assert_not_called()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
