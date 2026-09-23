# test_orchestration_file_outcome_projection.py
"""Runtime file outcomes come only from current authorized rendering-service projections.

Version: 0.261.127
Implemented in: 0.261.127
Real renderer, result store, artifact transport and commit readers use isolated external I/O.
"""

import pytest

from functions_orchestration_executor import RunContext, _dependency_file_outcomes
from functions_orchestration_output_store import OutputStorageError
from test_orchestration_output_lifecycle import lifecycle, production_modules


def context_for(lifecycle):
    return RunContext(
        run_id='run-1', user_id='owner', conversation_id='conversation-1',
        plan_contract_version=2, result_service=lifecycle.service.results,
        rendering_service=lifecycle.service,
    )


def test_file_projection_uses_current_service_states_and_only_committed_cards(lifecycle):
    csv_file = lifecycle.prepare('csv')
    json_file = lifecycle.prepare('json')
    completed = lifecycle.run(csv_file)
    assert completed['state'] == 'completed'
    context = context_for(lifecycle)
    context.artifacts = [{'id': 'untrusted-incidental-artifact'}]
    expected_outputs = lifecycle.service.list_public_outputs('run-1')
    expected_cards = lifecycle.service.committed_artifacts('run-1')
    before = list(lifecycle.render_calls)

    outputs, artifacts = _dependency_file_outcomes(context, settings={}, user_id='owner')
    assert outputs == expected_outputs and artifacts == expected_cards
    assert len(outputs) == 2 and len(artifacts) == 1
    by_id = {output['output_id']: output for output in outputs}
    assert by_id[csv_file['output_id']]['state'] == 'completed'
    assert by_id[json_file['output_id']]['state'] == 'waiting'
    assert all('reference' not in output and 'source_ref' not in output for output in outputs)
    assert lifecycle.render_calls == before


def test_denied_file_stays_visible_without_hiding_its_authorized_sibling(lifecycle):
    restricted_source = lifecycle.retain_source('restricted')
    allowed_source = lifecycle.retain_source('allowed')
    restricted = lifecycle.prepare('json', step_id='restricted_file', reference=restricted_source)
    allowed = lifecycle.prepare('json', step_id='allowed_file', reference=allowed_source)
    lifecycle.run(restricted)
    lifecycle.run(allowed)
    lifecycle.results.held.add('restricted')
    before = list(lifecycle.render_calls)

    outputs, artifacts = _dependency_file_outcomes(context_for(lifecycle), settings={}, user_id='owner')
    by_id = {output['output_id']: output for output in outputs}
    assert by_id[restricted['output_id']]['available'] is False
    assert by_id[allowed['output_id']]['available'] is True
    assert len(artifacts) == 1 and lifecycle.render_calls == before


def test_projection_storage_failure_is_not_an_empty_success(lifecycle):
    lifecycle.prepare('json')
    lifecycle.runs.fail_reads = True
    with pytest.raises(OutputStorageError):
        _dependency_file_outcomes(context_for(lifecycle), settings={}, user_id='owner')


def test_no_bound_file_service_never_promotes_incidental_artifacts():
    context = RunContext(
        run_id='run-1', user_id='owner', conversation_id='conversation-1', plan_contract_version=2,
    )
    context.artifacts = [{'id': 'not-a-committed-file'}]
    outputs, artifacts = _dependency_file_outcomes(context, settings={}, user_id='owner')
    assert outputs == artifacts == []
