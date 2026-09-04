#!/usr/bin/env python3
"""
Functional test for the chat orchestration capability registry.
Version: 0.261.085
Implemented in: 0.261.085

The registry is the only capability information the planner model ever sees, and it is
also what the validator checks a plan against. Those two roles have to stay in agreement:
a capability that is describable but not executable produces plans that always fail
validation, and one that is executable but not gated can run work an administrator
switched off.

This test ensures every descriptor is well formed, that gating actually withholds
capabilities, that the terminal capability survives an administrator's narrowing, and that
internal fields never leak into what the planner is shown.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import stubbed_app_imports  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


def test_descriptors_are_well_formed():
    """Every descriptor carries the fields the planner and validator both rely on."""
    print("Testing orchestration capability descriptors...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_registry as registry

            required_fields = (
                'id', 'label', 'kind', 'summary', 'when_to_use', 'settings_gates',
                'settings_gates_any', 'gate', 'requires_scope', 'inputs', 'produces',
                'cost_class', 'max_per_plan', 'adapter', 'terminal',
            )

            seen_ids = set()
            for capability in registry.CAPABILITY_REGISTRY:
                for field in required_fields:
                    assert field in capability, (
                        f"{capability.get('id')} is missing '{field}'"
                    )

                assert capability['id'] not in seen_ids, (
                    f"Duplicate capability id {capability['id']}"
                )
                seen_ids.add(capability['id'])

                assert capability['kind'] in registry.CAPABILITY_KINDS, (
                    f"{capability['id']} has an unknown kind {capability['kind']}"
                )
                assert capability['cost_class'] in registry.COST_CLASSES, (
                    f"{capability['id']} has an unknown cost class"
                )

                schema = capability['inputs']
                assert schema.get('type') == 'object', (
                    f"{capability['id']} inputs must be an object schema"
                )
                assert schema.get('additionalProperties') is False, (
                    f"{capability['id']} must refuse undeclared arguments; otherwise a "
                    f"planner-invented argument reaches an adapter"
                )
                for name in schema.get('required') or ():
                    assert name in (schema.get('properties') or {}), (
                        f"{capability['id']} requires '{name}' but never declares it"
                    )

            terminal = [c for c in registry.CAPABILITY_REGISTRY if c.get('terminal')]
            assert len(terminal) == 1, "Exactly one capability may end a plan"
            assert terminal[0]['id'] == registry.TERMINAL_CAPABILITY_ID

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_gates_withhold_capabilities():
    """A capability whose settings gate is off must not be offered."""
    print("Testing orchestration capability gating...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_registry as registry

            # Nothing enabled: only the terminal capability survives, because a plan has
            # to be able to end even in a deployment with everything switched off.
            bare = registry.resolve_available_capability_ids({})
            assert bare == [registry.TERMINAL_CAPABILITY_ID], (
                f"An empty deployment offered {bare}"
            )

            with_web = registry.resolve_available_capability_ids({'enable_web_search': True})
            assert registry.CAPABILITY_WEB_SEARCH in with_web
            assert registry.CAPABILITY_DOCUMENT_SEARCH not in with_web, (
                "Document search must need a workspace to search"
            )

            # Any one workspace is enough; the gate is an OR rather than an AND.
            for workspace_key in (
                'enable_user_workspace', 'enable_group_workspaces', 'enable_public_workspaces'
            ):
                ids = registry.resolve_available_capability_ids({workspace_key: True})
                assert registry.CAPABILITY_DOCUMENT_SEARCH in ids, (
                    f"{workspace_key} alone should permit document search"
                )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_administrator_narrowing():
    """The enabled-capability list narrows the registry without breaking plans."""
    print("Testing orchestration capability narrowing...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_registry as registry

            settings = {'enable_user_workspace': True, 'enable_web_search': True}
            full = registry.resolve_available_capability_ids(settings)

            # No opinion means everything, not nothing. An administrator who has never
            # touched the list must not thereby disable the feature.
            assert registry.resolve_available_capability_ids(settings, allowed_ids=[]) == full
            assert registry.resolve_available_capability_ids(settings, allowed_ids=None) == full

            narrowed = registry.resolve_available_capability_ids(
                settings, allowed_ids=[registry.CAPABILITY_WEB_SEARCH]
            )
            assert registry.CAPABILITY_WEB_SEARCH in narrowed
            assert registry.CAPABILITY_DOCUMENT_SEARCH not in narrowed
            assert registry.TERMINAL_CAPABILITY_ID in narrowed, (
                "Narrowing must never remove the step that ends a plan"
            )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_planner_projection_hides_internals():
    """Gates, adapters and caps are the application's business, not the model's."""
    print("Testing orchestration planner projection...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_registry as registry

            settings = {'enable_user_workspace': True, 'enable_web_search': True}
            available = registry.resolve_available_capabilities(settings)
            projection = registry.build_planner_capability_projection(available)

            assert projection, "The projection was empty"
            leaked = {'gate', 'settings_gates', 'settings_gates_any', 'adapter',
                      'max_per_plan', 'document_action_type', 'requires_scope'}
            for entry in projection:
                overlap = leaked & set(entry.keys())
                assert not overlap, f"Planner projection leaked {sorted(overlap)}"
                assert entry['when_to_use'], "Guidance is what the planner chooses on"

            client = registry.build_capability_client_projection(available)
            for entry in client:
                assert 'when_to_use' not in entry, (
                    "The card renders a chosen step and does not need the guidance that "
                    "drove the choice"
                )
                assert {'id', 'label', 'cost'} <= set(entry.keys())

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    assert_app_version_at_least("0.261.085")

    tests = [
        test_descriptors_are_well_formed,
        test_gates_withhold_capabilities,
        test_administrator_narrowing,
        test_planner_projection_hides_internals,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
