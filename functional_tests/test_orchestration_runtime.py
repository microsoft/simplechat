#!/usr/bin/env python3
# test_orchestration_runtime.py
"""
Functional test for the request-scoped orchestration runtime.
Version: 0.250.066
Implemented in: 0.250.063

This test ensures direct and coordinated plans execute through one bounded graph
with dependency ordering, safe parallelism, cancellation, failure policy,
replanning, finalizer isolation, runtime-node evidence provenance, and bounded
structured progress for the chat UI.
"""

import json
import sys
import threading
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
ROUTE_BACKEND_CHATS = SINGLE_APP_ROOT / 'route_backend_chats.py'
sys.path.insert(0, str(SINGLE_APP_ROOT))

from functions_chat_orchestration import build_turn_orchestration_plan  # noqa: E402
from functions_evidence_ledger import (  # noqa: E402
    add_evidence_source,
    add_fact,
    create_evidence_ledger_from_plan,
)
from functions_orchestration_runtime import (  # noqa: E402
    OrchestrationNodeAdapter,
    OrchestrationNodeResult,
    OrchestrationRun,
    complete_orchestration_node,
    execute_orchestration_run,
    finish_orchestration_run,
    reconcile_orchestration_run_from_ledger,
    resolve_orchestration_evidence_discovery,
    start_orchestration_node,
)


def _build_run(run_id, message, **plan_options):
    plan = build_turn_orchestration_plan(message, run_id=run_id, **plan_options)
    ledger = create_evidence_ledger_from_plan(
        plan,
        user_message_id=f'{run_id}-message',
    )
    return plan, ledger, OrchestrationRun.from_plan(plan, ledger)


def _collector_result(source_type, fact_text, *, fact_id, status='succeeded'):
    return {
        'source_type': source_type,
        'status': status,
        'summary': f'{source_type} completed.',
        'facts': [{
            'id': fact_id,
            'text': fact_text,
            'confidence': 'source_supported',
        }],
        'citations': [],
        'artifacts': [],
        'missing_or_failed': [],
        'metadata': {'authorization_status': 'authorized'},
        'raw_executor_payload': 'must-not-reach-finalizer',
    }


def _node(run, node_id):
    return next(node for node in run.nodes if node.id == node_id)


def test_direct_and_coordinated_turns_share_run_contract():
    _plan, ledger, run = _build_run(
        'runtime-direct',
        'Explain dependency graphs in one paragraph.',
    )
    progress_events = []

    execute_orchestration_run(
        run,
        {'response': lambda _context: OrchestrationNodeResult(status='succeeded')},
        original_request='Explain dependency graphs in one paragraph.',
        progress_callback=progress_events.append,
    )

    assert run.status == 'succeeded'
    assert ledger['status'] == 'completed'
    assert run.to_metadata()['mode'] == 'direct'
    assert _node(run, 'finalize_response').status == 'succeeded'
    assert [event['status'] for event in progress_events] == ['running', 'succeeded']
    assert all(event['required'] is True for event in progress_events)
    assert [event['node_index'] for event in progress_events] == [0, 0]
    assert [event['node_count'] for event in progress_events] == [1, 1]


def test_chat_streams_preserve_structured_orchestration_progress():
    """Validate both stream paths retain bounded node progress and approval state."""
    route_source = ROUTE_BACKEND_CHATS.read_text(encoding='utf-8')

    assert "'kind': 'orchestration_node'" in route_source
    assert "'step_type': 'orchestration_progress'" in route_source
    assert "'capability': capability" in route_source
    assert "'node_index': node_index" in route_source
    assert "'node_count': visible_node_count" in route_source
    assert "'required': bool(event.get('required'))" in route_source
    assert "'step_type': 'approval_required'" in route_source
    assert "'capability': 'approval_required'" in route_source
    assert route_source.count(
        'for thought_payload in _build_orchestration_stream_thought_payloads(event):'
    ) == 2
    assert 'thought_tracker.add_thought(step_type, content, detail, activity=activity)' in route_source


def test_dependencies_parallel_collectors_and_node_provenance():
    _plan, ledger, run = _build_run(
        'runtime-ordering',
        'Use the selected agent, action, and public web evidence.',
        selected_agent={'id': 'agent-1'},
        selected_action={'type': 'analysis'},
        web_search_enabled=True,
    )
    parallel_barrier = threading.Barrier(2)
    execution_events = []

    def collect_agent(_context):
        execution_events.append('agent_started')
        parallel_barrier.wait(timeout=2)
        execution_events.append('agent_finished')
        return _collector_result(
            'selected_agent',
            'The selected agent returned an authorized profile fact.',
            fact_id='fact-agent',
        )

    def collect_web(_context):
        execution_events.append('web_started')
        parallel_barrier.wait(timeout=2)
        execution_events.append('web_finished')
        return _collector_result(
            'web_search',
            'The public source returned a supported market fact.',
            fact_id='fact-web',
        )

    def execute_action(context):
        assert any(fact.get('id') == 'fact-agent' for fact in context.evidence_ledger['facts'])
        execution_events.append('action_started')
        return _collector_result(
            'selected_action',
            'The selected action computed an authorized result.',
            fact_id='fact-action',
        )

    def finalize(context):
        serialized_ledger = json.dumps(context.evidence_ledger)
        assert context.evidence_ledger['status'] == 'ready'
        assert 'must-not-reach-finalizer' not in serialized_ledger
        assert all(
            fact.get('step_id')
            for fact in context.evidence_ledger.get('facts', [])
        )
        execution_events.append('finalizer_started')
        return OrchestrationNodeResult(status='succeeded')

    execute_orchestration_run(
        run,
        {
            'selected_agent': OrchestrationNodeAdapter(
                execute=collect_agent,
                parallel_safe=True,
            ),
            'web_search': OrchestrationNodeAdapter(
                execute=collect_web,
                parallel_safe=True,
            ),
            'selected_action': OrchestrationNodeAdapter(
                execute=execute_action,
                read_only=False,
            ),
            'response': OrchestrationNodeAdapter(
                execute=finalize,
                read_only=False,
            ),
        },
        original_request='Use the selected agent, action, and public web evidence.',
        max_parallel_nodes=2,
    )

    assert run.status == 'succeeded'
    assert execution_events.index('agent_started') < execution_events.index('agent_finished')
    assert execution_events.index('web_started') < execution_events.index('web_finished')
    assert execution_events.index('action_started') > execution_events.index('agent_finished')
    assert execution_events.index('action_started') > execution_events.index('web_finished')
    assert execution_events[-1] == 'finalizer_started'
    assert {fact['id']: fact['step_id'] for fact in ledger['facts']} == {
        'fact-agent': 'collect_selected_agent',
        'fact-web': 'collect_web_search',
        'fact-action': 'execute_selected_action',
    }


def test_optional_failure_allows_partial_finalization_without_secret_leakage():
    plan, ledger, _run = _build_run(
        'runtime-optional-failure',
        'Use the selected agent and public web evidence.',
        selected_agent={'id': 'agent-1'},
        web_search_enabled=True,
    )
    next(source for source in plan['sources'] if source['id'] == 'web_search')['required'] = False
    next(step for step in plan['steps'] if step['id'] == 'collect_web_search')['required'] = False
    run = OrchestrationRun.from_plan(plan, ledger)
    finalizer_called = []

    def fail_web(_context):
        raise RuntimeError('secret-token-value')

    def finalize(context):
        finalizer_called.append(True)
        assert context.evidence_ledger['status'] == 'partial'
        assert 'secret-token-value' not in json.dumps(context.evidence_ledger)
        return OrchestrationNodeResult(status='succeeded')

    execute_orchestration_run(
        run,
        {
            'selected_agent': lambda _context: _collector_result(
                'selected_agent',
                'The agent supplied supported evidence.',
                fact_id='fact-agent-optional',
            ),
            'web_search': fail_web,
            'response': finalize,
        },
        original_request='Use the selected agent and public web evidence.',
    )

    assert finalizer_called == [True]
    assert run.status == 'partial'
    assert _node(run, 'collect_web_search').status == 'failed'
    assert next(
        gap for gap in ledger['missing_or_failed']
        if gap.get('step_id') == 'collect_web_search'
    )['error_type'] == 'runtimeerror'
    assert 'secret-token-value' not in json.dumps(run.to_metadata())


def test_required_failure_blocks_finalizer():
    _plan, ledger, run = _build_run(
        'runtime-required-failure',
        'Use the selected agent and public web evidence.',
        selected_agent={'id': 'agent-1'},
        web_search_enabled=True,
    )
    finalizer_called = []

    execute_orchestration_run(
        run,
        {
            'selected_agent': lambda _context: _collector_result(
                'selected_agent',
                'The agent supplied supported evidence.',
                fact_id='fact-agent-required',
            ),
            'web_search': lambda _context: OrchestrationNodeResult(
                status='failed',
                error_type='tool_unavailable',
                user_message='Public web evidence was unavailable.',
            ),
            'response': lambda _context: finalizer_called.append(True),
        },
        original_request='Use the selected agent and public web evidence.',
    )

    assert finalizer_called == []
    assert run.status == 'failed'
    assert ledger['status'] == 'failed'
    assert _node(run, 'finalize_response').status == 'blocked'
    assert _node(run, 'finalize_response').error_type == 'required_dependency_failed'


def test_read_only_retries_are_bounded_and_writes_remain_single_attempt():
    _plan, _ledger, run = _build_run(
        'runtime-read-retry',
        'Use public web evidence.',
        web_search_enabled=True,
    )
    read_attempts = []

    def retry_web(_context):
        read_attempts.append(len(read_attempts) + 1)
        if len(read_attempts) == 1:
            return OrchestrationNodeResult(
                status='failed',
                error_type='temporary_service_failure',
                user_message='The read-only source was temporarily unavailable.',
                retryable=True,
            )
        return _collector_result(
            'web_search',
            'The retried public source returned supported evidence.',
            fact_id='fact-retried-web',
        )

    execute_orchestration_run(
        run,
        {
            'web_search': OrchestrationNodeAdapter(
                execute=retry_web,
                read_only=True,
                max_attempts=3,
            ),
            'response': lambda _context: OrchestrationNodeResult(status='succeeded'),
        },
        original_request='Use public web evidence.',
    )

    assert read_attempts == [1, 2]
    assert _node(run, 'collect_web_search').attempt_count == 2
    assert run.status == 'succeeded'

    _write_plan, _write_ledger, write_run = _build_run(
        'runtime-write-no-retry',
        'Use the selected action.',
        selected_action={'type': 'analysis'},
    )
    write_attempts = []

    def fail_write(_context):
        write_attempts.append(len(write_attempts) + 1)
        return OrchestrationNodeResult(
            status='failed',
            error_type='temporary_write_failure',
            retryable=True,
        )

    execute_orchestration_run(
        write_run,
        {
            'selected_action': OrchestrationNodeAdapter(
                execute=fail_write,
                read_only=False,
                max_attempts=3,
            ),
            'response': lambda _context: OrchestrationNodeResult(status='succeeded'),
        },
        original_request='Use the selected action.',
    )

    assert write_attempts == [1]
    assert _node(write_run, 'execute_selected_action').attempt_count == 1
    assert write_run.status == 'failed'


def test_cancellation_stops_pending_synthesis():
    _plan, ledger, run = _build_run(
        'runtime-cancellation',
        'Use the selected agent and public web evidence.',
        selected_agent={'id': 'agent-1'},
        web_search_enabled=True,
    )
    cancellation_state = {'requested': False}
    web_called = []
    finalizer_called = []

    def collect_agent(_context):
        cancellation_state['requested'] = True
        return _collector_result(
            'selected_agent',
            'The agent supplied evidence before cancellation.',
            fact_id='fact-agent-cancelled',
        )

    execute_orchestration_run(
        run,
        {
            'selected_agent': collect_agent,
            'web_search': lambda _context: web_called.append(True),
            'response': lambda _context: finalizer_called.append(True),
        },
        original_request='Use the selected agent and public web evidence.',
        cancel_requested=lambda: cancellation_state['requested'],
    )

    assert run.status == 'cancelled'
    assert ledger['status'] == 'cancelled'
    assert web_called == []
    assert finalizer_called == []
    assert _node(run, 'collect_web_search').status == 'cancelled'
    assert _node(run, 'finalize_response').status == 'cancelled'


def test_cancellation_wins_before_aggregate_run_closure():
    _plan, ledger, run = _build_run(
        'runtime-final-cancellation',
        'Explain the final cancellation checkpoint.',
    )
    cancellation_checks = {'count': 0}

    def cancellation_requested():
        cancellation_checks['count'] += 1
        return cancellation_checks['count'] >= 4

    execute_orchestration_run(
        run,
        {'response': lambda _context: OrchestrationNodeResult(status='succeeded')},
        original_request='Explain the final cancellation checkpoint.',
        cancel_requested=cancellation_requested,
    )

    assert run.status == 'cancelled'
    assert ledger['status'] == 'cancelled'


def test_bounded_replanning_adds_read_only_work_before_finalizer():
    _plan, ledger, run = _build_run(
        'runtime-replanning',
        'Create a summary grounded in whatever evidence is needed.',
    )
    finalizer_contexts = []

    def plan_evidence(_context):
        return OrchestrationNodeResult(
            status='succeeded',
            additional_nodes=({
                'id': 'collect_source_review',
                'type': 'collect',
                'capability': 'source_review',
                'origin': 'replan',
                'required': False,
                'status': 'pending',
                'depends_on': ['plan_evidence_discovery'],
            },),
        )

    def collect_source_review(_context):
        result = _collector_result(
            'source_review',
            'The follow-up source review returned supported evidence.',
            fact_id='fact-source-review',
        )
        return OrchestrationNodeResult(
            status='succeeded',
            collector_result=result,
            additional_nodes=({
                'id': 'collect_unbounded_followup',
                'type': 'collect',
                'capability': 'web_search',
                'origin': 'replan',
                'required': False,
                'status': 'pending',
                'depends_on': ['collect_source_review'],
            },),
        )

    def finalize(context):
        finalizer_contexts.append(context)
        assert context.evidence_ledger['status'] == 'partial'
        assert any(
            fact.get('id') == 'fact-source-review'
            for fact in context.evidence_ledger['facts']
        )
        return OrchestrationNodeResult(status='succeeded')

    execute_orchestration_run(
        run,
        {
            'evidence_discovery': plan_evidence,
            'source_review': collect_source_review,
            'response': finalize,
        },
        original_request='Create a summary grounded in whatever evidence is needed.',
    )

    assert len(finalizer_contexts) == 1
    assert run.replan_count == 1
    assert run.status == 'partial'
    assert 'replan_budget_exhausted' in run.warnings
    assert _node(run, 'collect_source_review').status == 'partial'
    assert all(node.id != 'collect_unbounded_followup' for node in run.nodes)
    assert 'collect_source_review' in _node(run, 'finalize_response').depends_on


def test_cycles_are_rejected_before_execution():
    plan, ledger, _run = _build_run(
        'runtime-cycle',
        'Use public web evidence.',
        web_search_enabled=True,
    )
    plan['steps'][0]['depends_on'] = ['finalize_response']
    try:
        OrchestrationRun.from_plan(plan, ledger)
    except ValueError as ex:
        assert 'cycle' in str(ex)
    else:
        raise AssertionError('Expected cyclic orchestration graph to be rejected')


def test_replanning_cannot_create_a_finalizer_cycle():
    _plan, _ledger, run = _build_run(
        'runtime-replan-cycle',
        'Create a summary grounded in whatever evidence is needed.',
    )

    execute_orchestration_run(
        run,
        {
            'evidence_discovery': lambda _context: OrchestrationNodeResult(
                status='succeeded',
                additional_nodes=({
                    'id': 'collect_invalid_followup',
                    'type': 'collect',
                    'capability': 'source_review',
                    'origin': 'replan',
                    'required': False,
                    'status': 'pending',
                    'depends_on': ['finalize_response'],
                },),
            ),
            'response': lambda _context: OrchestrationNodeResult(status='succeeded'),
        },
        original_request='Create a summary grounded in whatever evidence is needed.',
    )

    assert run.status == 'partial'
    assert run.replan_count == 0
    assert 'invalid_replan_graph' in run.warnings
    assert all(node.id != 'collect_invalid_followup' for node in run.nodes)


def test_evidence_discovery_resolves_only_from_usable_authorized_evidence():
    _plan, ledger, run = _build_run(
        'runtime-discovery-success',
        'Create a summary grounded in whatever evidence is available.',
    )
    add_evidence_source(
        ledger,
        'conversation_history',
        'succeeded',
        source_id='conversation_history',
        required=False,
        authorization_status='authorized',
    )
    add_fact(
        ledger,
        'The user previously supplied an authorized project constraint.',
        ['conversation_history'],
        confidence='user_provided',
        fact_id='fact-discovered-history',
    )

    resolve_orchestration_evidence_discovery(run)

    assert _node(run, 'plan_evidence_discovery').status == 'succeeded'
    discovery_source = next(
        source for source in ledger['sources'] if source['id'] == 'evidence_discovery'
    )
    assert discovery_source['status'] == 'succeeded'
    assert discovery_source['metadata']['discovered_source_ids'] == ['conversation_history']

    _empty_plan, empty_ledger, empty_run = _build_run(
        'runtime-discovery-empty',
        'Create a summary grounded in whatever evidence is available.',
    )
    resolve_orchestration_evidence_discovery(empty_run)
    reconcile_orchestration_run_from_ledger(empty_run)

    assert _node(empty_run, 'plan_evidence_discovery').status == 'failed'
    assert _node(empty_run, 'finalize_response').status == 'blocked'
    assert empty_ledger['missing_or_failed'][0]['step_id'] == 'plan_evidence_discovery'


def test_external_stream_lifecycle_uses_same_graph_and_provenance():
    _plan, ledger, run = _build_run(
        'runtime-external-stream',
        'Use the selected agent and public web evidence.',
        selected_agent={'id': 'agent-1'},
        web_search_enabled=True,
    )
    for source_id, fact_id in (
        ('selected_agent', 'fact-external-agent'),
        ('web_search', 'fact-external-web'),
    ):
        source = next(item for item in ledger['sources'] if item['id'] == source_id)
        add_evidence_source(
            ledger,
            source_id,
            'succeeded',
            source_id=source_id,
            summary=f'{source_id} completed in the existing request path.',
            requirement_ids=source.get('requirement_ids'),
            authorization_status='authorized',
        )
        add_fact(
            ledger,
            f'{source_id} returned externally collected evidence.',
            [source_id],
            requirement_ids=source.get('requirement_ids'),
            fact_id=fact_id,
        )

    progress_events = []
    reconcile_orchestration_run_from_ledger(run, progress_callback=progress_events.append)
    start_orchestration_node(
        run,
        'finalize_response',
        progress_callback=progress_events.append,
    )
    assert ledger['status'] == 'ready'
    complete_orchestration_node(
        run,
        'finalize_response',
        OrchestrationNodeResult(status='succeeded'),
        progress_callback=progress_events.append,
    )
    finish_orchestration_run(run)

    assert run.status == 'succeeded'
    assert ledger['status'] == 'completed'
    assert _node(run, 'collect_selected_agent').status == 'succeeded'
    assert _node(run, 'collect_web_search').status == 'succeeded'
    assert {fact['id']: fact['step_id'] for fact in ledger['facts']} == {
        'fact-external-agent': 'collect_selected_agent',
        'fact-external-web': 'collect_web_search',
    }
    assert progress_events[-1]['node_id'] == 'finalize_response'
    assert progress_events[-1]['status'] == 'succeeded'


def test_initial_adapter_categories_share_image_finalizer_graph():
    plan, ledger, run = _build_run(
        'runtime-initial-adapters',
        'Create an image grounded in conversation history, selected documents, '
        'the selected image, workspace documents, and public web sources.',
        selected_agent={'id': 'agent-1'},
        selected_action={'type': 'analysis'},
        selected_document_ids=['document-1'],
        hybrid_search_enabled=True,
        web_search_enabled=True,
        source_review_enabled=True,
        selected_image_reference_count=1,
        image_generation_available=True,
    )
    expected_capabilities = {
        'conversation_evidence',
        'selected_documents',
        'selected_images',
        'workspace_search',
        'web_search',
        'source_review',
        'selected_agent',
        'selected_action',
    }
    assert expected_capabilities.issubset({node.capability for node in run.nodes})

    for source in plan['sources']:
        source_id = source['id']
        ledger_source = next(item for item in ledger['sources'] if item['id'] == source_id)
        add_evidence_source(
            ledger,
            source_id,
            'succeeded',
            source_id=source_id,
            origin=source.get('origin'),
            required=source.get('required', True),
            requirement_ids=ledger_source.get('requirement_ids'),
            authorization_status='authorized',
        )
        add_fact(
            ledger,
            f'{source_id} supplied authorized runtime evidence.',
            [source_id],
            requirement_ids=ledger_source.get('requirement_ids'),
            fact_id=f'fact-{source_id}',
        )

    reconcile_orchestration_run_from_ledger(run)
    start_orchestration_node(run, 'finalize_image_proposal')
    complete_orchestration_node(
        run,
        'finalize_image_proposal',
        OrchestrationNodeResult(status='succeeded'),
    )
    finish_orchestration_run(run)

    assert run.status == 'succeeded'
    assert all(
        node.status == 'succeeded'
        for node in run.nodes
        if node.capability in expected_capabilities
    )
    assert _node(run, 'finalize_image_proposal').status == 'succeeded'
    assert ledger['status'] == 'completed'


def test_chat_routes_persist_and_gate_request_scoped_runtime():
    route_source = ROUTE_BACKEND_CHATS.read_text(encoding='utf-8')

    assert route_source.count('turn_orchestration_run = OrchestrationRun.from_plan(') >= 2
    assert "user_metadata['orchestration_runtime'] = turn_orchestration_run.to_metadata()" in route_source
    assert "'orchestration_runtime': turn_orchestration_run.to_metadata()," in route_source
    assert 'resolve_orchestration_evidence_discovery(' in route_source
    assert 'reconcile_orchestration_run_from_ledger(' in route_source
    assert 'start_orchestration_node(' in route_source
    assert 'complete_orchestration_node(' in route_source
    assert 'finish_orchestration_run(turn_orchestration_run)' in route_source
    assert 'cancel_orchestration_run(' in route_source
    assert 'fail_orchestration_run(' in route_source
    assert 'stream_session.is_cancel_requested if stream_session else None' in route_source
    assert "error_type='stream_ended_before_runtime_completion'" in route_source
    assert 'and not active_runtime.completed_at' in route_source
    assert "and not locals().get('orchestration_waiting_for_choice')" in route_source
    assert "turn_orchestration_run.status = 'awaiting_user_choice'" in route_source
    assert "'partial_content': document_action_reply," in route_source
    assert "}, 409" in route_source
    assert route_source.count("user_message_doc['metadata'] = user_metadata") >= 8
    cancel_runtime_index = route_source.index(
        'cancel_orchestration_run(',
        route_source.index('def finalize_cancelled_stream_response():'),
    )
    cancel_persist_index = route_source.index(
        'cosmos_messages_container.upsert_item(user_message_doc)',
        cancel_runtime_index,
    )
    stream_failure_index = route_source.index(
        "error_type='stream_execution_failed'",
        cancel_persist_index,
    )
    stream_failure_persist_index = route_source.index(
        'cosmos_messages_container.upsert_item(user_message_doc)',
        stream_failure_index,
    )
    assert cancel_runtime_index < cancel_persist_index < stream_failure_index
    assert stream_failure_index < stream_failure_persist_index

    streaming_plan_index = route_source.rindex(
        'turn_orchestration_plan = build_turn_orchestration_plan('
    )
    streaming_ledger_index = route_source.index(
        'turn_evidence_ledger = create_evidence_ledger_from_plan(',
        streaming_plan_index,
    )
    streaming_runtime_index = route_source.index(
        'turn_orchestration_run = OrchestrationRun.from_plan(',
        streaming_ledger_index,
    )
    collector_index = route_source.index(
        'populate_evidence_ledger_from_chat_sources(',
        streaming_runtime_index,
    )
    discovery_index = route_source.index(
        'resolve_orchestration_evidence_discovery(',
        collector_index,
    )
    reconcile_index = route_source.index(
        'reconcile_orchestration_run_from_ledger(',
        discovery_index,
    )
    finalizer_start_index = route_source.index(
        'start_orchestration_node(',
        reconcile_index,
    )
    finalizer_finish_index = route_source.index(
        'finish_orchestration_run(turn_orchestration_run)',
        finalizer_start_index,
    )
    assert (
        streaming_plan_index
        < streaming_ledger_index
        < streaming_runtime_index
        < collector_index
        < discovery_index
        < reconcile_index
        < finalizer_start_index
        < finalizer_finish_index
    )


if __name__ == '__main__':
    tests = [
        test_direct_and_coordinated_turns_share_run_contract,
        test_dependencies_parallel_collectors_and_node_provenance,
        test_optional_failure_allows_partial_finalization_without_secret_leakage,
        test_required_failure_blocks_finalizer,
        test_read_only_retries_are_bounded_and_writes_remain_single_attempt,
        test_cancellation_stops_pending_synthesis,
        test_cancellation_wins_before_aggregate_run_closure,
        test_bounded_replanning_adds_read_only_work_before_finalizer,
        test_cycles_are_rejected_before_execution,
        test_replanning_cannot_create_a_finalizer_cycle,
        test_evidence_discovery_resolves_only_from_usable_authorized_evidence,
        test_external_stream_lifecycle_uses_same_graph_and_provenance,
        test_initial_adapter_categories_share_image_finalizer_graph,
        test_chat_routes_persist_and_gate_request_scoped_runtime,
    ]
    for test in tests:
        test()
    print(f'Orchestration runtime checks passed: {len(tests)}/{len(tests)}')