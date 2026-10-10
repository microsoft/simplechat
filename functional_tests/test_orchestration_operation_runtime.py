# test_orchestration_operation_runtime.py
"""Policy-governed M365 effects and claimed recovery through the real action runner.

Version: 0.261.321
Implemented in: 0.261.321
Storage, Graph, tokens and the model are doubled; external network access is blocked.
"""

import importlib
from copy import deepcopy
import sys

import pytest
import requests
from flask import session

from test_orchestration_m365_actions import (
    ACTION_REF, CONVERSATION, ROOT_RUN, STEP, TENANT, USER,
    env, mail_agent, module, run_step, tool_call, world,
)
from test_support.m365 import CosmosContainer


@pytest.fixture
def operations(env, world, monkeypatch):
    runtime = importlib.import_module('functions_orchestration_operations')
    delivery = importlib.import_module('functions_m365_pending_delivery')
    cards = importlib.import_module('functions_msgraph_pending_actions')
    pending = CosmosContainer('user_id')
    journal_store = CosmosContainer('run_id')
    world.plan = {
        'id': 'run-2', 'user_id': USER, 'conversation_id': CONVERSATION, 'status': 'running',
        'plan': {'steps': [{
            'step_id': STEP, 'capability_id': 'action_invoke', 'enabled': True,
            'arguments': {'action_ref': ACTION_REF, 'execution_intent': 'operate'},
        }]},
    }

    def read_run(run_id, user_id, *, conversation_id, strict):
        if run_id != 'run-2' or user_id != USER or conversation_id != CONVERSATION:
            return None
        return deepcopy(world.plan)

    monkeypatch.setitem(sys.modules, 'functions_orchestration_runs', module(
        'functions_orchestration_runs', get_orchestration_run=read_run,
    ))
    monkeypatch.setitem(sys.modules, 'functions_notifications', module(
        'functions_notifications', create_notification=lambda **kwargs: {'id': 'notice'},
    ))
    monkeypatch.setattr(cards, 'cosmos_msgraph_pending_actions_container', pending)
    monkeypatch.setattr(sys.modules['config'], 'cosmos_msgraph_pending_actions_container', pending)
    monkeypatch.setattr(delivery, '_dependencies', {})
    env.runtime.configure_m365_pending_delivery_runtime(
        lambda path: world.app.test_request_context(path, base_url='https://simplechat.example'),
    )
    world.journal = lambda: runtime.OperationJournal(
        journal_store, ROOT_RUN, STEP, USER, CONVERSATION,
        fingerprint='a' * 64, authorize=lambda: None,
    )
    world.pending, world.journal_store = pending, journal_store
    return runtime, delivery, cards


def send_call():
    return tool_call(
        'm365_email-send_mail', to_recipients='recipient@example.test',
        subject='Verified event details', body_content='The complete researched content.',
    )


@pytest.mark.parametrize('mode', ['draft_manual', 'draft_delayed', 'auto_send'])
def test_email_delivery_modes_and_retry_keep_one_effect(env, world, operations, monkeypatch, mode):
    runtime, _delivery, _cards = operations
    plugin = importlib.import_module('semantic_kernel_plugins.msgraph_plugin')
    scheduled = []
    monkeypatch.setattr(plugin, 'schedule_msgraph_pending_action_auto_commit',
                        lambda action, token: scheduled.append(action['id']))
    world.action['additionalFields']['msgraph_mail_send_mode'] = mode
    world.graph_response = (200, {'id': 'draft-1', 'changeKey': 'draft-v1', 'webLink': 'https://outlook.example.test/draft'})
    world.replies = [send_call()]
    first, _ = run_step(env, world, execution_intent='operate', journal=world.journal())
    assert len(world.graph_calls) == 1
    assert 'send_mail' in world.loaded_functions[0]
    assert first['operation_receipts']
    assert runtime.operation_summary(first['operation_receipts'], '') == (
        'Microsoft 365 accepted the send.' if mode == 'auto_send'
        else 'Delivery scheduled; not yet sent.' if mode == 'draft_delayed'
        else 'Draft prepared; awaiting review.'
    )
    if mode != 'auto_send':
        action = next(iter(world.pending.items.values()))
        assert action['m365_execution']['kind'] == 'orchestration'
        assert action['m365_execution']['step_ref']['selection']['action_ref'] == ACTION_REF
        assert action['status'] == ('scheduled' if mode == 'draft_delayed' else 'pending')
    world.replies = [send_call()]
    recovered, _ = run_step(env, world, execution_intent='operate', journal=world.journal())
    assert len(world.graph_calls) == 1
    assert recovered['operation_receipts'] == first['operation_receipts']
    assert len(scheduled) == (1 if mode == 'draft_delayed' else 0)


def test_manual_draft_does_not_send_under_changed_plan(env, world, operations):
    _runtime, delivery, _cards = operations
    world.graph_response = (200, {'id': 'draft-1', 'changeKey': 'draft-v1'})
    world.replies = [send_call()]
    run_step(env, world, execution_intent='operate', journal=world.journal())
    action = next(iter(world.pending.items.values()))
    world.plan['plan']['steps'][0]['arguments']['execution_intent'] = 'gather'
    with world.app.test_request_context('/api/msgraph/pending-actions/send'):
        session['user'] = {'oid': USER, 'tid': TENANT}
        _saved, error = delivery.dispatch_m365_pending_delivery(USER, action['id'], expected_version=action['_etag'])
    assert error is not None
    assert len(world.graph_calls) == 1


def test_missing_delivery_binding_fails_before_outlook_draft_creation(env, world, operations):
    _runtime, delivery, _cards = operations
    world.plan['plan']['steps'][0]['arguments']['execution_intent'] = 'gather'
    world.replies = [send_call()]
    with pytest.raises(env.orchestration.OrchestrationM365Error):
        run_step(env, world, execution_intent='operate', journal=world.journal())
    assert not world.graph_calls and not world.pending.items


def test_changed_payload_or_unknown_outcome_cannot_be_replayed(env, world, operations):
    runtime, _delivery, _cards = operations
    world.action['additionalFields']['msgraph_mail_send_mode'] = 'auto_send'
    world.replies = [send_call()]
    run_step(env, world, execution_intent='operate', journal=world.journal())
    world.replies = [tool_call(
        'm365_email-send_mail', to_recipients='different@example.test', subject='Changed', body_content='Changed',
    )]
    with pytest.raises(env.actions.ActionExecutionError):
        run_step(env, world, execution_intent='operate', journal=world.journal())
    assert len(world.graph_calls) == 1
    journal = world.journal()
    with pytest.raises(runtime.OperationRecoveryError):
        journal.begin('new-operation', {'subject': 'unrelated'})


def test_revoked_write_is_not_restored_by_operation_intent(env, world, operations):
    world.action['additionalFields']['m365_capabilities']['send_mail'] = False
    world.replies = [send_call()]
    with pytest.raises(env.actions.ActionExecutionError):
        run_step(env, world, execution_intent='operate', journal=world.journal())
    assert not world.graph_calls
    assert 'send_mail' not in world.loaded_functions[0]


def test_claimed_but_unfinished_generic_operation_stays_uncertain(operations, world):
    runtime, _delivery, _cards = operations
    first = world.journal()
    first.begin('ticket.create', {'title': 'Requested ticket'})
    with pytest.raises(runtime.OperationRecoveryError):
        world.journal().begin('ticket.create', {'title': 'Requested ticket'})


def test_operation_receipt_cannot_be_rebound_to_another_user(operations, world):
    runtime, _delivery, _cards = operations
    first = world.journal()
    first.begin('ticket.create', {'title': 'Requested ticket'})
    wrong_owner = runtime.OperationJournal(
        world.journal_store, ROOT_RUN, STEP, 'another-user', CONVERSATION,
        fingerprint='a' * 64, authorize=lambda: None,
    )
    with pytest.raises(runtime.OperationRecoveryError):
        wrong_owner.begin('ticket.create', {'title': 'Requested ticket'})


def test_receipt_sanitization_failure_blocks_later_calls_in_the_same_step(operations, world):
    runtime, _delivery, _cards = operations
    journal = world.journal()

    def refuse_result(_result):
        raise ValueError('Simulated receipt sanitization failure.')

    journal.sanitize = refuse_result
    key, _cached = journal.begin('ticket.create', {'title': 'Requested ticket'})
    with pytest.raises(ValueError):
        journal.finish(key, {'id': 'created-ticket'})
    with pytest.raises(runtime.OperationRecoveryError):
        journal.begin('ticket.create', {'title': 'Another ticket'})


def test_caught_post_write_failure_cannot_continue_with_another_m365_effect(env, world, operations):
    runtime, _delivery, _cards = operations
    world.action['additionalFields']['msgraph_mail_send_mode'] = 'auto_send'
    journal = world.journal()

    def refuse_result(_result):
        raise ValueError('Simulated receipt sanitization failure.')

    journal.sanitize = refuse_result
    with world.app.test_request_context('/internal/agent-execution'):
        session['user'] = {'oid': USER, 'tid': TENANT}
        with runtime.operation_journal_scope(journal), env.orchestration.action_step_scope(
            ACTION_REF, user_id=USER, conversation_id=CONVERSATION, request_key=f'{ROOT_RUN}\x00{STEP}',
            origin={'run_id': 'run-2', 'attempt_index': 2, 'step_id': STEP}, execution_intent='operate',
        ):
            plugin = env.email.M365EmailPlugin(deepcopy(world.action))
            with pytest.raises(ValueError):
                plugin.send_mail('recipient@example.test', 'Requested email', 'Prepared content.')
            with pytest.raises(runtime.OperationRecoveryError):
                plugin.send_mail('recipient@example.test', 'Another email', 'Do not send.')
    assert len(world.graph_calls) == 1


def test_manual_draft_send_reauthorizes_its_step_and_is_not_repeated(env, world, operations):
    _runtime, delivery, _cards = operations
    world.graph_response = (200, {'id': 'draft-1', 'changeKey': 'draft-v1', 'isDraft': True})
    world.replies = [send_call()]
    run_step(env, world, execution_intent='operate', journal=world.journal())
    action = next(iter(world.pending.items.values()))
    world.plan['status'] = 'completed'
    with world.app.test_request_context('/api/msgraph/pending-actions/send'):
        session['user'] = {'oid': USER, 'tid': TENANT}
        sent, error = delivery.dispatch_m365_pending_delivery(USER, action['id'], expected_version=action['_etag'])
        again, repeated_error = delivery.dispatch_m365_pending_delivery(USER, action['id'])
    assert error is None and repeated_error is None
    assert sent['status'] == again['status'] == 'sent'
    assert len(world.graph_calls) == 3


@pytest.mark.parametrize('mode', ['draft_manual', 'draft_delayed', 'auto_send'])
def test_calendar_modes_keep_configured_behavior(env, world, operations, monkeypatch, mode):
    runtime, _delivery, _cards = operations
    calendar = importlib.import_module('semantic_kernel_plugins.m365_calendar_plugin')
    plugin = importlib.import_module('semantic_kernel_plugins.msgraph_plugin')
    monkeypatch.setattr(plugin, 'schedule_msgraph_pending_action_auto_commit', lambda action, token: None)
    world.action.update(type='m365_calendar', name='m365_calendar')
    world.action['additionalFields'] = {
        'm365_capabilities': {'create_calendar_invite': True},
        'msgraph_calendar_send_mode': mode,
    }

    class Loader:
        def __init__(self, kernel):
            self.kernel = kernel
            self.plugin_instances = []

        def load_plugin_from_manifest(self, manifest, user_id):
            instance = calendar.M365CalendarPlugin(deepcopy(manifest))
            world.loaded_functions.append(sorted(instance.get_functions()))
            self.plugin_instances.append(instance)
            self.kernel.add_plugin(instance.get_kernel_plugin('m365_calendar'))
            return True

    monkeypatch.setattr(importlib.import_module('semantic_kernel_plugins.logged_plugin_loader'),
                        'create_logged_plugin_loader', Loader)
    world.graph_response = (200, {'id': 'event-1'})
    world.replies = [tool_call(
        'm365_calendar-create_calendar_invite', subject='Requested event',
        start_datetime='2026-10-20T14:00:00', end_datetime='2026-10-20T15:00:00',
        timezone='UTC', attendee_emails='recipient@example.test',
    )]
    result, _ = run_step(env, world, execution_intent='operate', journal=world.journal())
    assert len(world.graph_calls) == (1 if mode == 'auto_send' else 0)
    assert runtime.operation_summary(result['operation_receipts'], '') == (
        'Microsoft 365 created the calendar event.' if mode == 'auto_send'
        else 'Delivery scheduled; not yet sent.' if mode == 'draft_delayed'
        else 'Draft prepared; awaiting review.'
    )


def test_read_state_write_runs_only_with_operation_intent(env, world, operations):
    runtime, _delivery, _cards = operations
    world.action['additionalFields']['m365_capabilities']['mark_message_as_read'] = True
    world.graph_response = (200, {'id': 'message-1', 'isRead': True})
    world.replies = [tool_call(
        'm365_email-mark_message_as_read', message_id='message-1', is_read=True,
    )]
    result, _ = run_step(env, world, execution_intent='operate', journal=world.journal())
    assert len(world.graph_calls) == 1 and world.graph_calls[0]['method'] == 'PATCH'
    assert runtime.operation_summary(result['operation_receipts'], '') == 'Microsoft 365 updated the message read state.'


def test_agent_operation_uses_its_own_selection_and_rechecks_revocation(env, world, operations):
    runtime, delivery, _cards = operations
    agent = mail_agent()
    world.agents = [agent]
    world.plan['plan']['steps'][0].update(
        capability_id='agent_invoke', arguments={'agent_name': agent['name'], 'execution_intent': 'operate'},
    )
    world.graph_response = (200, {'id': 'draft-1', 'changeKey': 'draft-v1', 'isDraft': True})
    with world.app.test_request_context('/internal/agent-execution'):
        session['user'] = {'oid': USER, 'tid': TENANT}
        with runtime.operation_journal_scope(world.journal()), env.orchestration.agent_step_scope(
            agent, user_id=USER, conversation_id=CONVERSATION, request_key=f'{ROOT_RUN}\x00{STEP}',
            origin={'run_id': 'run-2', 'attempt_index': 2, 'step_id': STEP}, execution_intent='operate',
        ):
            plugin = env.email.M365EmailPlugin(deepcopy(world.action))
            result = plugin.send_mail('recipient@example.test', 'Requested email', 'Prepared content.')
        action = next(iter(world.pending.items.values()))
        assert result['mail_send_status'] == 'pending'
        assert action['m365_execution']['step_ref']['selection']['kind'] == 'agent'
        world.agents = []
        _saved, error = delivery.dispatch_m365_pending_delivery(USER, action['id'])
    assert error is not None and len(world.graph_calls) == 1


def test_unknown_graph_write_outcome_is_not_replayed(env, world, operations):
    world.action['additionalFields']['msgraph_mail_send_mode'] = 'auto_send'
    world.graph_error = requests.Timeout('simulated lost write response')
    world.replies = [send_call()]
    with pytest.raises(env.actions.ActionExecutionError):
        run_step(env, world, execution_intent='operate', journal=world.journal())
    assert len(world.graph_calls) == 1
    world.graph_error = None
    world.replies = [send_call()]
    with pytest.raises(env.actions.ActionExecutionError):
        run_step(env, world, execution_intent='operate', journal=world.journal())
    assert len(world.graph_calls) == 1


def test_sign_in_repair_before_effect_allows_same_request_to_continue(env, world, operations):
    world.action['additionalFields']['msgraph_mail_send_mode'] = 'auto_send'
    world.token_error = 'interactive_auth_required'
    world.replies = [send_call()]
    with pytest.raises(env.orchestration.OrchestrationM365Error):
        run_step(env, world, execution_intent='operate', journal=world.journal())
    assert not world.graph_calls and not world.journal_store.items
    world.token_error = None
    result, _ = run_step(env, world, execution_intent='operate', journal=world.journal())
    assert len(world.graph_calls) == 1 and result['operation_receipts']


@pytest.mark.parametrize('input_limit', [128000, 1024])
def test_complete_named_content_respects_actual_model_budget(env, world, operations, monkeypatch, input_limit):
    runtime, _delivery, _cards = operations
    from functions_model_capabilities import ModelTokenBudget

    budget = ModelTokenBudget(
        model_id='test-model', input_limit=input_limit, output_limit=4096,
        output_accounting='total_generation',
    )
    monkeypatch.setattr(env.actions, '_build_file_action_model', lambda *args, **kwargs: (
        world.service, {'provider': 'aoai'}, budget,
    ))
    body = 'Complete event details. ' * 300
    world.action['additionalFields']['msgraph_mail_send_mode'] = 'auto_send'
    world.replies = [tool_call(
        'm365_email-send_mail', to_recipients='recipient@example.test', subject='Event', body_content=body,
    )]
    inputs = {'email': {'subject': 'Event', 'body': body}}
    if input_limit == 1024:
        with pytest.raises(runtime.IntegrationInputError):
            run_step(env, world, execution_intent='operate', journal=world.journal(), named_inputs=inputs)
        assert not world.graph_calls and not world.requests
    else:
        result, _ = run_step(
            env, world, execution_intent='operate', journal=world.journal(), named_inputs=inputs,
        )
        assert result['operation_receipts'] and len(world.graph_calls) == 1
        assert body in world.requests[0]
