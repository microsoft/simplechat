#!/usr/bin/env python3
"""
Functional test for the chat orchestration plan contract and validator.
Version: 0.261.085
Implemented in: 0.261.085

Planner output is untrusted input. A plan arrives as JSON written by a language model, and
naming a capability that does not exist, using one an administrator disabled, referencing
a document the user cannot read, or producing a dependency cycle are all within the normal
range of a generative system rather than exceptional.

This test ensures every one of those is caught before an adapter could be reached, that
repairs are recorded rather than applied silently, and that a plan always ends by
answering.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import stubbed_app_imports  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

SETTINGS = {
    'enable_user_workspace': True,
    'enable_web_search': True,
    'chat_orchestration_max_steps': 6,
}


def test_rejects_unknown_and_disabled_capabilities():
    """A step naming something unavailable is dropped and reported."""
    print("Testing orchestration plan capability rejection...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_schema as schema

            plan = schema.normalize_plan(
                {
                    'intent': {'summary': 'test', 'complexity': 'simple'},
                    'steps': [
                        {'step_id': 's1', 'capability_id': 'web_search',
                         'arguments': {'query': 'weather'}},
                        {'step_id': 's2', 'capability_id': 'not_a_capability',
                         'arguments': {}},
                        # Real capability, but its document-action gate is off here.
                        {'step_id': 's3', 'capability_id': 'document_analyze',
                         'arguments': {'analysis_prompt': 'x', 'document_ids': ['d1']}},
                    ],
                },
                'conv1', 'user1', settings=SETTINGS,
            )

            capability_ids = [step['capability_id'] for step in plan['steps']]
            assert 'not_a_capability' not in capability_ids
            assert 'document_analyze' not in capability_ids
            assert 'web_search' in capability_ids

            errors = ' '.join(plan['validation']['errors'])
            assert 'not_a_capability' in errors, "An unknown capability must be reported"
            assert 'document_analyze' in errors, "A disabled capability must be reported"
            assert plan['validation']['ok'] is False

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_enforces_document_authorization():
    """A plan may only reference documents this user can actually read."""
    print("Testing orchestration plan document authorization...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_schema as schema

            plan = schema.normalize_plan(
                {
                    'steps': [
                        {'step_id': 's1', 'capability_id': 'document_search',
                         'arguments': {'query': 'q', 'document_ids': ['ok1', 'stolen']}},
                    ],
                },
                'conv1', 'user1', settings=SETTINGS,
                authorized_document_ids={'ok1'},
            )

            search = [s for s in plan['steps'] if s['capability_id'] == 'document_search'][0]
            assert search['arguments']['document_ids'] == ['ok1'], (
                f"Unauthorized document survived: {search['arguments']['document_ids']}"
            )
            assert any('cannot read' in repair for repair in plan['validation']['repairs']), (
                "Removing a document must be reported, never silent"
            )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_coerces_and_bounds_arguments():
    """Schema-declared bounds are applied; undeclared arguments never survive."""
    print("Testing orchestration plan argument handling...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_schema as schema

            plan = schema.normalize_plan(
                {
                    'steps': [
                        {'step_id': 's1', 'capability_id': 'document_search',
                         'arguments': {
                             'query': 'q',
                             # A model routinely quotes an integer; that is a habit rather
                             # than a reason to discard an otherwise good plan.
                             'top_n': '9999',
                             'doc_scope': 'not_a_scope',
                             'smuggled': 'should not survive',
                         }},
                    ],
                },
                'conv1', 'user1', settings=SETTINGS,
            )

            arguments = plan['steps'][0]['arguments']
            assert arguments['top_n'] == 50, f"top_n was not clamped: {arguments['top_n']}"
            assert arguments['doc_scope'] == 'all', "An out-of-range enum falls back"
            assert 'smuggled' not in arguments, (
                "An argument the schema never declared reached the adapter"
            )

            # A missing required argument invalidates the step rather than the run.
            plan2 = schema.normalize_plan(
                {'steps': [{'step_id': 's1', 'capability_id': 'web_search', 'arguments': {}}]},
                'conv1', 'user1', settings=SETTINGS,
            )
            assert [s['capability_id'] for s in plan2['steps']] == ['respond']
            assert any("'query' is required" in e for e in plan2['validation']['errors'])

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_repairs_structure():
    """Cycles, missing terminal steps and over-long plans are repaired."""
    print("Testing orchestration plan structural repair...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_schema as schema

            cyclic = schema.normalize_plan(
                {
                    'steps': [
                        {'step_id': 'a', 'capability_id': 'web_search',
                         'arguments': {'query': 'one'}, 'depends_on': ['b']},
                        {'step_id': 'b', 'capability_id': 'web_search',
                         'arguments': {'query': 'two'}, 'depends_on': ['a']},
                    ],
                },
                'conv1', 'user1', settings=SETTINGS,
            )
            assert any('circular' in r for r in cyclic['validation']['repairs'])
            # A repaired plan must still be orderable.
            seen = set()
            for step in cyclic['steps']:
                for dependency in step['depends_on']:
                    assert dependency in seen, "Steps are not in dependency order"
                seen.add(step['step_id'])

            # Every plan ends by answering, even one that forgot to say so.
            assert cyclic['steps'][-1]['capability_id'] == 'respond'
            assert any('answering step' in r for r in cyclic['validation']['repairs'])

            # The step cap is enforced regardless of what the plan asked for.
            long_plan = schema.normalize_plan(
                {
                    'steps': [
                        {'step_id': f's{i}', 'capability_id': 'document_search',
                         'arguments': {'query': f'q{i}'}}
                        for i in range(12)
                    ],
                },
                'conv1', 'user1',
                settings={**SETTINGS, 'chat_orchestration_max_steps': 3},
            )
            assert len(long_plan['steps']) <= 3, (
                f"Step cap not enforced: {len(long_plan['steps'])} steps"
            )
            assert long_plan['steps'][-1]['capability_id'] == 'respond'

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_edits_narrow_only():
    """A user may disable a step or drop a document, never add either."""
    print("Testing orchestration plan edits...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_schema as schema

            plan = schema.normalize_plan(
                {
                    'steps': [
                        {'step_id': 's1', 'capability_id': 'document_search',
                         'arguments': {'query': 'q', 'document_ids': ['d1', 'd2']}},
                    ],
                },
                'conv1', 'user1', settings=SETTINGS,
                authorized_document_ids={'d1', 'd2'},
            )

            edited = schema.apply_plan_edits(plan, {
                'disabled_step_ids': ['s1'],
                'removed_document_ids': {'s1': ['d2']},
            })

            search = [s for s in edited['steps'] if s['step_id'] == 's1'][0]
            assert search['enabled'] is False
            assert search['arguments']['document_ids'] == ['d1']
            assert edited['approval']['edited'] is True

            # The answering step cannot be switched off; a plan has to end.
            terminal = edited['steps'][-1]
            schema.apply_plan_edits(edited, {'disabled_step_ids': [terminal['step_id']]})
            assert terminal['enabled'] is True, "The answering step must not be disableable"

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_approval_mode_decides_initial_status():
    """Auto-approval runs on arrival; timed and manual both wait."""
    print("Testing orchestration plan approval states...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_schema as schema

            body = {'steps': [{'step_id': 's1', 'capability_id': 'web_search',
                               'arguments': {'query': 'q'}}]}

            auto = schema.normalize_plan(dict(body), 'c', 'u', settings=SETTINGS,
                                         approval_mode='auto')
            assert auto['status'] == schema.PLAN_STATUS_APPROVED
            assert auto['approval']['state'] == schema.APPROVAL_STATE_APPROVED

            for mode in ('manual', 'timed'):
                waiting = schema.normalize_plan(dict(body), 'c', 'u', settings=SETTINGS,
                                                approval_mode=mode)
                assert waiting['status'] == schema.PLAN_STATUS_AWAITING_APPROVAL, (
                    f"{mode} mode must wait; the countdown belongs to the browser, and a "
                    f"server that pre-approved it would leave an unstoppable countdown"
                )
                assert waiting['approval']['state'] == schema.APPROVAL_STATE_PENDING

            unknown = schema.normalize_plan(dict(body), 'c', 'u', settings=SETTINGS,
                                            approval_mode='nonsense')
            assert unknown['approval']['mode'] == 'manual', "An unknown mode must fail safe"

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
        test_rejects_unknown_and_disabled_capabilities,
        test_enforces_document_authorization,
        test_coerces_and_bounds_arguments,
        test_repairs_structure,
        test_edits_narrow_only,
        test_approval_mode_decides_initial_status,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
