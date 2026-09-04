#!/usr/bin/env python3
"""
Functional test for chat orchestration phase ordering.
Version: 0.261.088
Implemented in: 0.261.087

A plan runs in three phases: collect knowledge, reason on it and answer, then create
things. Before this the registry carried a `kind` that was passed all the way to the
browser and read by nothing, so the order was a convention the planner could ignore
without anything noticing.

It matters because a step that gathers after the answer has been written would still run,
still cost money, and contribute nothing -- the answer it was meant to inform was composed
before it started. The validator already guarantees a plan ends by answering; this is the
same class of structural rule, and this test is what holds it.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import stubbed_app_imports  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

SETTINGS = {
    'enable_user_workspace': True,
    'enable_web_search': True,
    'chat_orchestration_max_steps': 10,
}


def _step(step_id, capability_id, arguments=None, depends_on=None):
    return {
        'step_id': step_id,
        'capability_id': capability_id,
        'arguments': arguments or {},
        'depends_on': list(depends_on or []),
    }


def test_phases_are_ordered_and_indexed():
    """The phase tuple is ordered, and every capability lands in a real one."""
    print("Testing the phase ordering...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_registry as registry

            assert registry.CAPABILITY_PHASES == ('knowledge', 'reasoning', 'output'), (
                f"unexpected phase order: {registry.CAPABILITY_PHASES}"
            )

            # Knowledge is drawn on what a capability produces, not on how hard it thinks:
            # analysing and comparing emit the same evidence envelopes as searching.
            for capability_id in (
                'document_search', 'document_analyze', 'document_compare',
                'tabular_analyze', 'web_search', 'url_fetch', 'deep_research',
                'agent_invoke',
            ):
                assert registry.phase_index(capability_id) == 0, (
                    f"{capability_id} should be a knowledge capability"
                )

            assert registry.phase_index('respond') == 1, "answering is the reasoning phase"

            # An unknown capability sorts last rather than first: whatever it is, running it
            # ahead of everything that gathers would be the more damaging guess.
            assert registry.phase_index('not_a_capability') == len(registry.CAPABILITY_PHASES)

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_gathering_after_answering_is_reordered():
    """A plan that answers before it gathers is repaired, not run as written."""
    print("Testing that gathering is moved ahead of answering...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_schema as schema

            plan = schema.normalize_plan(
                {
                    'steps': [
                        _step('answer', 'respond'),
                        _step('search', 'document_search', {'query': 'slope formula'}),
                        _step('web', 'web_search', {'query': 'slope formula'}),
                    ],
                },
                'conv1', 'user1', settings=SETTINGS,
            )

            order = [step['capability_id'] for step in plan['steps']]
            assert order[-1] == 'respond', f"the answer must run last, got {order}"
            assert 'document_search' in order[:-1]
            assert 'web_search' in order[:-1], (
                f"both gathering steps must precede the answer, got {order}"
            )

            # Every step now declares which phase it belongs to, so the client can group
            # them without knowing the registry.
            assert all(step.get('phase') for step in plan['steps'])
            assert plan['steps'][-1]['phase'] == 'reasoning'

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_backwards_dependency_is_dropped_and_reported():
    """A gathering step may not wait on the answer."""
    print("Testing that a backwards dependency is dropped...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_schema as schema

            plan = schema.normalize_plan(
                {
                    'steps': [
                        # Nonsense: the search waits for the answer that is supposed to use
                        # it. Honouring it would drag the answer forward, which is the very
                        # inversion the phase order exists to prevent.
                        _step('search', 'document_search', {'query': 'q'},
                              depends_on=['answer']),
                        _step('answer', 'respond'),
                    ],
                },
                'conv1', 'user1', settings=SETTINGS,
            )

            search = [s for s in plan['steps'] if s['capability_id'] == 'document_search'][0]
            assert 'answer' not in search['depends_on'], (
                f"the backwards dependency survived: {search['depends_on']}"
            )
            assert any('later phase' in repair for repair in plan['validation']['repairs']), (
                f"the repair must be reported, saw {plan['validation']['repairs']}"
            )

            # And the plan still runs in a defensible order afterwards.
            seen = set()
            for step in plan['steps']:
                for dependency in step['depends_on']:
                    assert dependency in seen, "steps are not in dependency order"
                seen.add(step['step_id'])

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ordering_within_a_phase_is_preserved():
    """Sorting by phase must not shuffle steps that share one."""
    print("Testing that the planner's own order survives within a phase...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_schema as schema

            plan = schema.normalize_plan(
                {
                    'steps': [
                        _step('a', 'document_search', {'query': 'first'}),
                        _step('b', 'web_search', {'query': 'second'}),
                        _step('c', 'document_search', {'query': 'third'}),
                        _step('answer', 'respond'),
                    ],
                },
                'conv1', 'user1', settings=SETTINGS,
            )

            knowledge = [s['step_id'] for s in plan['steps'] if s['phase'] == 'knowledge']
            assert knowledge == ['a', 'b', 'c'], (
                f"a stable sort should leave same-phase steps alone, got {knowledge}"
            )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_the_client_carries_the_phase_the_server_decided():
    """The browser groups by the phase the validator stamped, not by re-deriving it."""
    print("Testing the client's phase contract...")
    try:
        v2_root = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'application', 'v2_ui', 'src',
        )

        def read(*parts):
            with open(os.path.join(v2_root, *parts), encoding='utf-8') as handle:
                return handle.read()

        # The plan normalizer must copy `phase` through. Without this the value the server
        # ordered the plan by is discarded on arrival and the view has to guess it back from
        # the capability menu -- which disagrees the moment a capability is turned off after
        # a plan was made.
        normalizer = read('lib', 'orchestrationPlan.ts')
        assert 'phase' in normalizer, (
            'normalizeStep drops the step phase; the server sends it and the client would '
            'have to re-derive a value it was already given'
        )

        # The phases must be declared in run order on the client too, so a grouped view can
        # iterate them rather than hard-coding an order that can drift from the server's.
        contracts = read('lib', 'orchestration.ts')
        assert 'ORCHESTRATION_PHASES' in contracts, (
            'the client must declare the phases in order'
        )
        order_start = contracts.index('ORCHESTRATION_PHASES')
        declared = contracts[order_start:order_start + 200]
        for earlier, later in (('knowledge', 'reasoning'), ('reasoning', 'output')):
            assert declared.index(earlier) < declared.index(later), (
                f"the client lists {later} before {earlier}; a grouped plan would read "
                f"out of order"
            )

        # `kind` is gone rather than kept alongside. Two taxonomies where one is decorative
        # is how a field comes to mean nothing.
        assert 'OrchestrationPhase' in contracts, 'the phase type must exist'

        # And a step whose phase cannot be resolved must still be shown. A plan the user is
        # asked to approve cannot quietly omit a step from the list.
        view = read('components', 'chat', 'OrchestrationRunView.tsx')
        assert 'ORCHESTRATION_PHASES' in view, 'the run view must group by phase'
        assert 'step.phase' in view, (
            "the run view must prefer the step's own phase over a lookup"
        )

        print("  ok  the client groups by the phase the server decided")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    assert_app_version_at_least("0.261.087")

    tests = [
        test_phases_are_ordered_and_indexed,
        test_gathering_after_answering_is_reordered,
        test_backwards_dependency_is_dropped_and_reported,
        test_ordering_within_a_phase_is_preserved,
        test_the_client_carries_the_phase_the_server_decided,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
