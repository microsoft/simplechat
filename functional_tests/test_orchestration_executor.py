#!/usr/bin/env python3
"""
Functional test for the chat orchestration step executor.
Version: 0.261.085
Implemented in: 0.261.085

The executor is what turns a validated plan into an answer. Its job is almost entirely
about what it refuses to do: run a step whose dependency failed, run past a cancellation,
run more steps than the deployment allows, or compose an answer from evidence the user is
no longer allowed to see.

Every one of those is tested here with fake adapters, because the real ones need Cosmos,
Azure OpenAI and Azure AI Search. The engine's decisions are what this covers; the
adapters' own call shapes are not exercised on a developer machine.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.app_stubs import stubbed_app_imports  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402

SETTINGS = {
    'enable_user_workspace': True,
    'enable_web_search': True,
    'chat_orchestration_max_steps': 8,
    'chat_orchestration_max_replans': 2,
}


def _plan(steps):
    """A plan already shaped as the validator would leave it."""
    return {
        'plan_id': 'plan_1',
        'run_id': 'run_1',
        'turn_id': 'turn_1',
        'conversation_id': 'conv_1',
        'user_id': 'user_1',
        'steps': steps,
        'status': 'approved',
    }


def _step(step_id, capability_id, depends_on=None, enabled=True, optional=False):
    return {
        'step_id': step_id,
        'capability_id': capability_id,
        'title': step_id,
        'rationale': '',
        'arguments': {},
        'depends_on': list(depends_on or []),
        'enabled': enabled,
        'optional': optional,
        'estimated_cost': 'low',
        'status': 'pending',
    }


def _recording_adapters(schema, order, failures=(), cancel_on=None, replan_on=()):
    """Fake adapters that record execution order and can fail or cancel on cue."""

    def make(capability_id):
        def adapter(step, context, *, settings, user_id, emit, cancel_requested):
            order.append(step['step_id'])
            if cancel_on and step['step_id'] == cancel_on:
                return schema.build_step_result(status=schema.STEP_STATUS_CANCELLED,
                                                summary='cancelled')
            if step['step_id'] in failures:
                return schema.build_step_result(status=schema.STEP_STATUS_FAILED,
                                                summary='failed', error='boom')
            return schema.build_step_result(
                status=schema.STEP_STATUS_COMPLETED,
                summary=f"did {step['step_id']}",
                message='ANSWER' if capability_id == 'respond' else None,
                replan_hint='look again' if step['step_id'] in replan_on else None,
            )
        return adapter

    return lambda capability_id: make(capability_id)


def test_steps_run_in_dependency_order():
    """A step never runs before something it depends on."""
    print("Testing orchestration executor ordering...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_executor as executor
            import functions_orchestration_schema as schema

            order = []
            plan = _plan([
                _step('c', 'web_search', depends_on=['b']),
                _step('a', 'document_search'),
                _step('b', 'document_search', depends_on=['a']),
                _step('answer', 'respond', depends_on=['c']),
            ])
            context = executor.RunContext(run_id='run_1', conversation_id='conv_1',
                                          user_id='user_1')

            result = executor.execute_plan(
                plan, context, settings=SETTINGS, user_id='user_1',
                get_adapter=_recording_adapters(schema, order),
            )

            assert order == ['a', 'b', 'c', 'answer'], f"Ran out of order: {order}"
            assert result['status'] == schema.PLAN_STATUS_COMPLETED
            assert result['message'] == 'ANSWER'
            # The answering step is always last, whatever order it was proposed in.
            assert order[-1] == 'answer'

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_disabled_and_dependent_steps_are_skipped():
    """A disabled step does not run, and nor does one that needed it."""
    print("Testing orchestration executor skipping...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_executor as executor
            import functions_orchestration_schema as schema

            order = []
            plan = _plan([
                _step('a', 'document_search', enabled=False),
                _step('b', 'document_search', depends_on=['a']),
                _step('answer', 'respond', depends_on=['b']),
            ])
            context = executor.RunContext(run_id='run_1', conversation_id='conv_1',
                                          user_id='user_1')

            result = executor.execute_plan(
                plan, context, settings=SETTINGS, user_id='user_1',
                get_adapter=_recording_adapters(schema, order),
            )

            assert 'a' not in order, "A disabled step ran"
            assert 'b' not in order, "A step whose dependency was skipped still ran"
            # The answer is still produced. A plan that gathered nothing can still reply.
            assert 'answer' in order
            assert result['message'] == 'ANSWER'

            # A failed dependency stops a required dependant but not an optional one.
            order2 = []
            plan2 = _plan([
                _step('a', 'document_search'),
                _step('needs_a', 'document_search', depends_on=['a']),
                _step('optional_a', 'web_search', depends_on=['a'], optional=True),
                _step('answer', 'respond'),
            ])
            context2 = executor.RunContext(run_id='run_2', conversation_id='conv_1',
                                           user_id='user_1')
            executor.execute_plan(
                plan2, context2, settings=SETTINGS, user_id='user_1',
                get_adapter=_recording_adapters(schema, order2, failures={'a'}),
            )
            assert 'needs_a' not in order2, "A required dependant ran after its dependency failed"
            assert 'optional_a' in order2, "An optional step should survive a failed dependency"
            assert 'answer' in order2

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_cancellation_stops_the_run():
    """Cancellation is honoured between steps and when an adapter reports it."""
    print("Testing orchestration executor cancellation...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_executor as executor
            import functions_orchestration_schema as schema

            # Cancelled by the probe, before anything runs.
            order = []
            plan = _plan([
                _step('a', 'document_search'),
                _step('answer', 'respond'),
            ])
            context = executor.RunContext(run_id='run_1', conversation_id='conv_1',
                                          user_id='user_1')
            result = executor.execute_plan(
                plan, context, settings=SETTINGS, user_id='user_1',
                cancel_requested=lambda: True,
                get_adapter=_recording_adapters(schema, order),
            )
            assert order == [], f"Steps ran after cancellation: {order}"
            assert result['status'] == schema.PLAN_STATUS_CANCELLED

            # Cancelled by an adapter mid-run.
            order2 = []
            plan2 = _plan([
                _step('a', 'document_search'),
                _step('b', 'web_search'),
                _step('answer', 'respond'),
            ])
            context2 = executor.RunContext(run_id='run_2', conversation_id='conv_1',
                                           user_id='user_1')
            result2 = executor.execute_plan(
                plan2, context2, settings=SETTINGS, user_id='user_1',
                get_adapter=_recording_adapters(schema, order2, cancel_on='a'),
            )
            assert result2['status'] == schema.PLAN_STATUS_CANCELLED, (
                "An adapter reporting cancellation must cancel the run"
            )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_budgets_are_enforced():
    """The step cap and the replan cap bound a run regardless of the plan."""
    print("Testing orchestration executor budgets...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_executor as executor
            import functions_orchestration_schema as schema

            order = []
            plan = _plan(
                [_step(f's{i}', 'document_search') for i in range(10)]
                + [_step('answer', 'respond')]
            )
            context = executor.RunContext(run_id='run_1', conversation_id='conv_1',
                                          user_id='user_1')
            result = executor.execute_plan(
                plan, context, settings={**SETTINGS, 'chat_orchestration_max_steps': 3},
                user_id='user_1',
                get_adapter=_recording_adapters(schema, order),
            )
            gathering = [step for step in order if step != 'answer']
            assert len(gathering) <= 3, f"Step budget not enforced: {gathering}"
            assert 'answer' in order, (
                "The budget must not consume the step that produces the answer"
            )
            assert result['message'] == 'ANSWER'

            # Replan hints are collected but bounded, and the executor never re-plans
            # itself -- the route owns that loop.
            order2 = []
            plan2 = _plan([
                _step('a', 'document_search'),
                _step('b', 'document_search'),
                _step('c', 'document_search'),
                _step('answer', 'respond'),
            ])
            context2 = executor.RunContext(run_id='run_2', conversation_id='conv_1',
                                           user_id='user_1')
            result2 = executor.execute_plan(
                plan2, context2,
                settings={**SETTINGS, 'chat_orchestration_max_replans': 1},
                user_id='user_1',
                get_adapter=_recording_adapters(
                    schema, order2, replan_on={'a', 'b', 'c'}
                ),
            )
            assert len(result2['replan_hints']) <= 1, (
                f"Replan budget not enforced: {result2['replan_hints']}"
            )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_reauthorization_before_answering():
    """Evidence for a document the user may no longer read is dropped before the answer."""
    print("Testing orchestration executor re-authorization...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_executor as executor
            import functions_orchestration_schema as schema

            def gathering_adapter(capability_id):
                def adapter(step, context, *, settings, user_id, emit, cancel_requested):
                    if capability_id == 'respond':
                        return schema.build_step_result(
                            status=schema.STEP_STATUS_COMPLETED, message='ANSWER'
                        )
                    return schema.build_step_result(
                        status=schema.STEP_STATUS_COMPLETED,
                        summary='gathered',
                        evidence=[
                            {'document_id': 'allowed', 'source_kind': 'narrative',
                             'engine': 'hybrid_search', 'status': 'completed',
                             'summary': 'kept', 'evidence': [], 'citations': [],
                             'generated_artifacts': [], 'coverage': {}, 'error': None},
                            {'document_id': 'revoked', 'source_kind': 'narrative',
                             'engine': 'hybrid_search', 'status': 'completed',
                             'summary': 'dropped', 'evidence': [], 'citations': [],
                             'generated_artifacts': [], 'coverage': {}, 'error': None},
                        ],
                    )
                return adapter

            # Access is re-resolved before the answer, and by then only one document is
            # still authorized. Plan-time authorization is not execution-time authorization.
            def resolve_source_manifest(document_ids, **kwargs):
                return [
                    {'document_id': document_id, 'authorization_status': 'authorized'}
                    for document_id in document_ids if document_id == 'allowed'
                ]

            plan = _plan([
                _step('gather', 'document_search'),
                _step('answer', 'respond', depends_on=['gather']),
            ])
            context = executor.RunContext(
                run_id='run_1', conversation_id='conv_1', user_id='user_1',
                resolve_source_manifest=resolve_source_manifest,
            )

            result = executor.execute_plan(
                plan, context, settings=SETTINGS, user_id='user_1',
                get_adapter=gathering_adapter,
            )

            surviving = {
                envelope.get('document_id') for envelope in result.get('evidence') or ()
            }
            assert 'revoked' not in surviving, (
                f"Evidence for a revoked document reached the answer: {surviving}"
            )
            assert 'allowed' in surviving, "Authorized evidence was dropped"

            reauth = result.get('reauthorization') or {}
            assert 'revoked' in (reauth.get('dropped_document_ids') or []), (
                "A dropped document must be reported, not silently removed"
            )

        print("Test passed!")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_unknown_capability_fails_the_step_not_the_run():
    """A step with no adapter fails on its own rather than taking the run down."""
    print("Testing orchestration executor unknown capability...")
    try:
        with stubbed_app_imports():
            import functions_orchestration_executor as executor
            import functions_orchestration_schema as schema

            def only_respond(capability_id):
                if capability_id != 'respond':
                    return None
                def adapter(step, context, *, settings, user_id, emit, cancel_requested):
                    return schema.build_step_result(
                        status=schema.STEP_STATUS_COMPLETED, message='ANSWER'
                    )
                return adapter

            plan = _plan([
                _step('ghost', 'document_search'),
                _step('answer', 'respond'),
            ])
            context = executor.RunContext(run_id='run_1', conversation_id='conv_1',
                                          user_id='user_1')
            result = executor.execute_plan(
                plan, context, settings=SETTINGS, user_id='user_1',
                get_adapter=only_respond,
            )

            statuses = {record['step_id']: record['status'] for record in result['steps']}
            assert statuses['ghost'] == schema.STEP_STATUS_FAILED
            assert result['message'] == 'ANSWER', (
                "One unrunnable step must not stop the user getting an answer"
            )

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
        test_steps_run_in_dependency_order,
        test_disabled_and_dependent_steps_are_skipped,
        test_cancellation_stops_the_run,
        test_budgets_are_enforced,
        test_reauthorization_before_answering,
        test_unknown_capability_fails_the_step_not_the_run,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
