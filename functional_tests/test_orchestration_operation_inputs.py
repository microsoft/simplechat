# test_orchestration_operation_inputs.py
"""Complete authorized integration input and source-lineage regressions.

Version: 0.261.321
Implemented in: 0.261.321
"""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from functions_orchestration_operations import IntegrationInputError, integration_inputs, integration_task
from functions_orchestration_results import NamedOutput
from test_support.orchestration_results import ResultFixture, complete
from test_orchestration_action_planning import modules


def input_world(text='Complete prepared email, including every detail.'):
    fixture = ResultFixture()
    saved = fixture.save(outputs=[NamedOutput('content', 'markdown-v1', text, complete(1))])
    consumer = replace(
        fixture.consumer(), step_id='operate', capability_id='action_invoke',
        contract_version='orchestration-gathered-content-v1',
    )
    fixture.add_producer(consumer)
    context = SimpleNamespace(
        result_service=fixture.service, result_producer=lambda step: consumer,
        task_results={saved.producer.step_id: saved}, result_aliases={}, notes=['UNBOUND_SECRET'],
    )
    step = {
        'step_id': 'operate', 'capability_id': 'action_invoke',
        'inputs': {'content': {'binding': {
            'version': 'orchestration-input-binding-v1', 'step_id': saved.producer.step_id,
            'output_name': 'content', 'existing_result': None,
        }, 'allow_partial': False}},
    }
    return fixture, context, step


def test_bound_input_is_complete_and_incidental_notes_do_not_reach_task(modules):
    _fixture, context, step = input_world()
    values = integration_inputs(step, context)
    task = integration_task('Send to the requested recipient.', values, 'operate')
    assert values['content'] == 'Complete prepared email, including every detail.'
    assert 'UNBOUND_SECRET' not in task
    assert context.integration_input_readers['content'].reference.kind == 'markdown-v1'


@pytest.mark.parametrize('boundary', ['conversation', 'run'])
def test_revoked_retained_result_access_is_not_forwarded(modules, boundary):
    fixture, context, step = input_world()
    if boundary == 'conversation':
        fixture.conversation['user_id'] = 'another-user'
    else:
        fixture.runs[fixture.producer.run_id]['user_id'] = 'another-user'
    with pytest.raises(IntegrationInputError):
        integration_inputs(step, context)
    assert not hasattr(context, 'integration_input_readers')


def test_document_revision_preserves_prepared_snapshot_instead_of_rereading(modules):
    fixture, context, step = input_world('Reviewed version of the complete content.')
    fixture.sources['document-1']['source_version'] += 1
    values = integration_inputs(step, context)
    assert values['content'] == 'Reviewed version of the complete content.'


def test_oversized_prepared_body_is_rejected_not_truncated(modules):
    _fixture, context, step = input_world('x' * 64001)
    with pytest.raises(IntegrationInputError):
        integration_inputs(step, context)
    assert not hasattr(context, 'integration_input_readers')
