# test_ask_ai_debug_diagnostics.py
"""
Functional regressions for debug-gated Ask AI diagnostics.
Version: 0.261.362
Implemented in: 0.261.329
Operation error container fix: 0.261.331
Workflow operation coverage and chat-execution rules: 0.261.362

Exercises real editor/workflow cores, model adapter, and log_event serialization
with offline providers. Synthetic replies prove rule visibility and privacy,
not the unknown historical SQL-agent response.
"""

import copy
import hashlib
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import openai
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'application' / 'single_app'))
sys.path.insert(0, str(ROOT / 'functional_tests'))

import functions_appinsights as telemetry  # noqa: E402
import functions_editor_assist as editor  # noqa: E402
import functions_editor_assist_runtime as editor_runtime  # noqa: E402
import functions_workflow_assist as workflow  # noqa: E402
import functions_workflow_assist_runtime as runtime  # noqa: E402
from functions_assist_diagnostics import (  # noqa: E402
    ASSIST_DIAGNOSTIC_LIMIT, AssistDiagnostics, safe_assist_diagnostics,
)
from functions_workflow_assist_operations import OPERATION_SCHEMAS  # noqa: E402
from test_editor_assist_core import FakeLimiter, ScriptedModel, agent_body, SUBMISSION_ID  # noqa: E402
from test_support import workflow_assist as wa  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


PRIVATE = 'PRIVATE_PROMPT_PASSWORD_DRAFT_RESPONSE'
UNKNOWN_PATH = '/additionalFields/private_field'
REQUEST = httpx.Request('POST', 'https://model.example.invalid/chat/completions')


@pytest.fixture
def diagnostic_logger(monkeypatch):
    logger = logging.getLogger('test.ask_ai.diagnostics')
    monkeypatch.setattr(telemetry, 'get_appinsights_logger', lambda: logger)
    settings = {'enable_debug_logging': True}
    monkeypatch.setattr(telemetry, '_load_logging_settings', lambda: settings)
    return settings, logger


def records(caplog):
    return [
        record for record in caplog.records
        if getattr(record, 'sc_message', '') in {
            '[EDITOR_ASSIST] Ask AI diagnostic', '[WORKFLOW_ASSIST] Ask AI diagnostic',
        }
    ]


def emitted_text(caplog, capsys):
    properties = [
        {key: value for key, value in record.__dict__.items() if key.startswith('sc_')}
        for record in records(caplog)
    ]
    console = capsys.readouterr()
    return json.dumps(properties) + console.out + console.err


def run_editor(model, *, kind='agent', body=None, diagnostics=None, limiter=None):
    services = editor.EditorAssistServices(
        limiter=limiter or FakeLimiter(), call_model=model,
        diagnostics=diagnostics or AssistDiagnostics(telemetry.log_assist_debug),
    )
    return editor.run_editor_assist(
        body if body is not None else agent_body(instruction=PRIVATE),
        kind=kind, scope='personal', user_id=PRIVATE, services=services,
    )


def changed(path='/display_name'):
    return {'reply': PRIVATE, 'operations': [{'op': 'set', 'path': path, 'value': PRIVATE}]}


@pytest.mark.parametrize('debug', [False, True])
@pytest.mark.parametrize('surface', ['agent', 'action', 'workflow'])
def test_debug_gate_covers_both_sinks_and_every_surface(diagnostic_logger, caplog, capsys, debug, surface):
    settings, logger = diagnostic_logger
    settings['enable_debug_logging'] = debug
    with caplog.at_level(logging.INFO, logger=logger.name):
        if surface == 'workflow':
            bundle = wa.services(wa.ScriptedModel(wa.reply('explained', PRIVATE)))
            bundle.diagnostics = AssistDiagnostics(telemetry.log_assist_debug)
            result = wa.run(wa.request_body(instruction=PRIVATE), bundle)
        else:
            body = agent_body(instruction=PRIVATE)
            if surface == 'action':
                body = {
                    'submission_id': SUBMISSION_ID, 'instruction': PRIVATE,
                    'fields': [{'path': '/displayName', 'label': PRIVATE, 'kind': 'text'}],
                    'values': {'/displayName': PRIVATE},
                }
            result = run_editor(ScriptedModel({'reply': PRIVATE, 'operations': []}), kind=surface, body=body)
    assert result['outcome'] == 'explained'
    events = records(caplog)
    assert bool(events) is debug
    if debug:
        assert {record.sc_assist_surface for record in events} == {surface}
        assert {record.sc_assist_event for record in events} == {'model_started', 'model_finished', 'request_finished'}
        expected_id = 'submission-0001' if surface == 'workflow' else SUBMISSION_ID
        assert all(record.sc_turn_id_hash == hashlib.sha256(expected_id.encode()).hexdigest() for record in events)
    output = emitted_text(caplog, capsys)
    assert PRIVATE not in output
    assert SUBMISSION_ID not in output
    assert ('Ask AI diagnostic' in output) is debug


@pytest.mark.parametrize('reply,rule', [
    ('', 'empty_reply'), ('not JSON', 'invalid_json'), ('[]', 'reply_not_object'),
    ({'reply': PRIVATE, 'extra': PRIVATE}, 'unexpected_reply_field'),
    ({'reply': ''}, 'reply_required'),
    ({'reply': PRIVATE, 'operations': PRIVATE}, 'operations_not_array'),
    ({'reply': PRIVATE, 'operations': [{'op': PRIVATE}]}, 'operation_shape'),
    ({'reply': PRIVATE, 'operations': [{'op': 'set', 'path': PRIVATE, 'value': PRIVATE}]}, 'field_unknown'),
    ({'reply': PRIVATE, 'operations': [{'op': 'set', 'path': '/max_completion_tokens', 'value': 99999}]}, 'number_above_maximum'),
    ({'reply': PRIVATE, 'operations': [{'op': 'set', 'path': '/actions', 'value': [PRIVATE]}]}, 'choice_handle_invalid'),
])
def test_terminal_rejections_retain_each_attempts_rule_without_content(diagnostic_logger, caplog, capsys, reply, rule):
    _settings, logger = diagnostic_logger
    with caplog.at_level(logging.INFO, logger=logger.name):
        with pytest.raises(editor.EditorAssistError) as caught:
            run_editor(ScriptedModel(reply, reply))
    assert caught.value.code == 'assistant_output_invalid'
    rejected = [record for record in records(caplog) if record.sc_assist_event == 'validation_rejected']
    assert [record.sc_attempt for record in rejected] == [1, 2]
    assert all(record.sc_assist_rule == rule for record in rejected)
    terminal = records(caplog)[-1]
    assert terminal.sc_assist_code == 'assistant_output_invalid'
    assert terminal.sc_model_calls == 2 and terminal.sc_correction_count == 1
    assert PRIVATE not in emitted_text(caplog, capsys)


def test_new_sql_action_failure_is_specific_and_successful_correction_is_atomic(diagnostic_logger, caplog, capsys):
    _settings, logger = diagnostic_logger
    body = agent_body(instruction='i want to connect to a sql database', new_items={
        'target': '/actions', 'types': [{'value': 'sql_query', 'label': PRIVATE}],
        'common': [{'path': '/displayName', 'label': PRIVATE, 'kind': 'text', 'required': True}],
        'variants': {'sql_query': [
            {'path': '/additionalFields/server', 'label': PRIVATE, 'kind': 'text', 'required': True},
        ]},
    })
    invalid = {'reply': PRIVATE, 'operations': [{
        'op': 'create_item', 'handle': 'N1', 'type': 'sql_query',
        'values': {'/displayName': 'SQL lookup', '/additionalFields/server': ''},
    }]}
    corrected = copy.deepcopy(invalid)
    del corrected['operations'][0]['values']['/additionalFields/server']
    before = copy.deepcopy(body)
    with caplog.at_level(logging.INFO, logger=logger.name):
        result = run_editor(ScriptedModel(invalid, corrected), body=body)
    assert result['outcome'] == 'changed'
    assert result['candidate']['new_items'][0]['values'] == {'/displayName': 'SQL lookup'}
    assert body == before
    rejected = next(record for record in records(caplog) if record.sc_assist_event == 'validation_rejected')
    assert rejected.sc_assist_rule == 'required_value'
    assert rejected.sc_assist_field == '/additionalFields/server'
    assert rejected.sc_assist_operation == 'create_item' and rejected.sc_operation_index == 1
    assert records(caplog)[-1].sc_assist_outcome == 'changed'
    assert PRIVATE not in emitted_text(caplog, capsys)


@pytest.mark.parametrize('operation,rule', [
    ({'op': 'create_item', 'handle': 'N1', 'type': 'sql_query', 'values': {}}, 'new_required_field'),
    ({'op': 'create_item', 'handle': 'N1', 'type': PRIVATE, 'values': {}}, 'new_type_invalid'),
    ({'op': 'create_item', 'handle': PRIVATE, 'type': 'sql_query', 'values': {}}, 'new_handle_invalid'),
    ({'op': 'create_item', 'handle': 'N1', 'type': 'sql_query', 'values': {PRIVATE: PRIVATE}}, 'new_field_unknown'),
])
def test_new_action_contract_rejection_codes(diagnostic_logger, caplog, capsys, operation, rule):
    _settings, logger = diagnostic_logger
    body = agent_body(new_items={
        'target': '/actions', 'types': [{'value': 'sql_query'}],
        'common': [{'path': '/displayName', 'kind': 'text', 'required': True}], 'variants': {},
    })
    reply = {'reply': PRIVATE, 'operations': [operation]}
    with caplog.at_level(logging.INFO, logger=logger.name):
        with pytest.raises(editor.EditorAssistError):
            run_editor(ScriptedModel(reply, reply), body=body)
    assert rule in [getattr(record, 'sc_assist_rule', None) for record in records(caplog)]
    assert PRIVATE not in emitted_text(caplog, capsys)


def test_repeated_and_read_only_fields_and_bounded_reasons(diagnostic_logger, caplog, capsys):
    _settings, logger = diagnostic_logger
    body = agent_body()
    body['fields'][0]['read_only'] = True
    reply = {'reply': PRIVATE, 'operations': [
        {'op': 'set', 'path': '/display_name', 'value': PRIVATE} for _ in range(40)
    ]}
    with caplog.at_level(logging.INFO, logger=logger.name):
        with pytest.raises(editor.EditorAssistError):
            run_editor(ScriptedModel(reply, reply), body=body)
    rejected = [record for record in records(caplog) if record.sc_assist_event == 'validation_rejected']
    assert len(rejected) == 2 * ASSIST_DIAGNOSTIC_LIMIT
    assert all(record.sc_assist_rule == 'field_read_only' for record in rejected)
    assert PRIVATE not in emitted_text(caplog, capsys)


@pytest.mark.parametrize('message_count', [0, 2, ASSIST_DIAGNOSTIC_LIMIT + 1])
def test_operation_error_container_separates_messages_and_bounded_diagnostics(message_count):
    errors = editor._OperationErrors()
    expected_messages = []
    expected_diagnostics = []
    for index in range(1, message_count + 1):
        message = f'Operation {index}: the path is not a field in this draft.'
        expected_messages.append(message)
        errors.reject(message, 'field_unknown', index=index, operation='set')
        if index <= ASSIST_DIAGNOSTIC_LIMIT:
            expected_diagnostics.append({
                'assist_rule': 'field_unknown', 'operation_index': index,
                'assist_operation': 'set', 'assist_field': None,
                'field_known': False, 'assist_field_kind': None,
            })
    assert type(errors.messages) is list
    assert errors.messages == expected_messages
    assert errors.diagnostics == expected_diagnostics


def test_duplicate_fields_and_private_paths_have_separate_safe_reasons(diagnostic_logger, caplog, capsys):
    _settings, logger = diagnostic_logger
    reply = {'reply': PRIVATE, 'operations': [
        {'op': 'set', 'path': '/display_name', 'value': 'SQL helper'},
        {'op': 'set', 'path': '/display_name', 'value': PRIVATE},
        {'op': 'set', 'path': UNKNOWN_PATH, 'value': PRIVATE},
        {'op': 'set', 'path': '/instructions', 'value': PRIVATE + '\r\n\x00FORGED_LOG'},
    ]}
    body = agent_body()
    before = copy.deepcopy(body)
    with caplog.at_level(logging.INFO, logger=logger.name):
        with pytest.raises(editor.EditorAssistError):
            run_editor(ScriptedModel(reply, reply), body=body)
    rejected = [record for record in records(caplog) if record.sc_assist_event == 'validation_rejected']
    assert [record.sc_assist_rule for record in rejected] == [
        'field_repeated', 'field_unknown', 'text_invalid',
    ] * 2
    assert body == before
    unknown = [record for record in rejected if record.sc_assist_rule == 'field_unknown']
    assert all(not hasattr(record, 'sc_assist_field') and record.sc_field_known is False for record in unknown)
    output = emitted_text(caplog, capsys)
    assert PRIVATE not in output and UNKNOWN_PATH not in output and 'FORGED_LOG' not in output


@pytest.mark.parametrize('surface', ['agent', 'workflow'])
@pytest.mark.parametrize('finish,code,calls', [
    ('length', 'assistant_output_invalid', 2),
    ('content_filter', 'assistant_refused', 1),
    (PRIVATE, None, 1),
])
def test_finish_reason_categories_and_terminal_outcomes(diagnostic_logger, caplog, capsys, surface, finish, code, calls):
    _settings, logger = diagnostic_logger
    model = (
        ScriptedModel({'reply': PRIVATE}, {'reply': PRIVATE}, finish=finish)
        if surface == 'agent' else
        wa.ScriptedModel((wa.reply('question', PRIVATE), finish), (wa.reply('question', PRIVATE), finish))
    )
    bundle = wa.services(model) if surface == 'workflow' else None
    if bundle is not None:
        bundle.diagnostics = AssistDiagnostics(telemetry.log_assist_debug)
    with caplog.at_level(logging.INFO, logger=logger.name):
        if code:
            with pytest.raises((editor.EditorAssistError, workflow.WorkflowAssistError)) as caught:
                if bundle is None:
                    run_editor(model)
                else:
                    wa.run(wa.request_body(), bundle)
            assert caught.value.code == code
        else:
            result = run_editor(model) if bundle is None else wa.run(wa.request_body(), bundle)
            assert result['outcome'] == ('explained' if surface == 'agent' else 'question')
    terminal = records(caplog)[-1]
    assert terminal.sc_model_calls == calls
    finished = [record for record in records(caplog) if record.sc_assist_event == 'model_finished']
    assert all(record.sc_assist_finish_reason == ('other' if finish == PRIVATE else finish) for record in finished)
    if finish == 'length':
        rejected = [record for record in records(caplog) if record.sc_assist_event == 'validation_rejected']
        assert [record.sc_assist_rule for record in rejected] == ['output_truncated', 'output_truncated']
    assert PRIVATE not in emitted_text(caplog, capsys)


@pytest.mark.parametrize('operations,rule,stage', [
    ([{'op': 'set_name'}], 'schema_required', 'schema'),
    ([{'op': 'set_task_runner', 'task': 'task_99', 'runner': 'inherit'}], 'handle_invalid', 'apply'),
])
def test_workflow_rejections_are_typed_and_correlated(diagnostic_logger, caplog, capsys, operations, rule, stage):
    _settings, logger = diagnostic_logger
    reply = wa.reply(operations=operations)
    bundle = wa.services(wa.ScriptedModel(reply, reply))
    bundle.diagnostics = AssistDiagnostics(telemetry.log_assist_debug)
    with caplog.at_level(logging.INFO, logger=logger.name):
        with pytest.raises(workflow.WorkflowAssistError) as caught:
            wa.run(wa.request_body(instruction=PRIVATE), bundle)
    assert caught.value.code == 'assistant_output_invalid'
    rejected = [record for record in records(caplog) if record.sc_assist_event == 'validation_rejected']
    assert len(rejected) == 2
    assert all(record.sc_assist_rule == rule and record.sc_assist_stage == stage for record in rejected)
    assert PRIVATE not in emitted_text(caplog, capsys)


@pytest.mark.parametrize('operation', sorted(OPERATION_SCHEMAS))
def test_all_workflow_operation_names_survive_both_diagnostic_sinks(diagnostic_logger, caplog, capsys, operation):
    _settings, logger = diagnostic_logger
    reply = wa.reply(operations=[{'op': operation, 'private_field': PRIVATE}])
    bundle = wa.services(wa.ScriptedModel(reply, reply))
    bundle.diagnostics = AssistDiagnostics(telemetry.log_assist_debug)
    with caplog.at_level(logging.INFO, logger=logger.name):
        with pytest.raises(workflow.WorkflowAssistError) as caught:
            wa.run(wa.request_body(instruction=PRIVATE), bundle)
    assert caught.value.code == 'assistant_output_invalid'
    rejected = [record for record in records(caplog) if record.sc_assist_event == 'validation_rejected']
    assert {record.sc_attempt for record in rejected} == {1, 2}
    assert all(record.sc_assist_operation == operation and record.sc_operation_index == 1 for record in rejected)
    assert all(record.sc_assist_stage == 'schema' for record in rejected)
    assert all(record.sc_turn_id_hash == hashlib.sha256(b'submission-0001').hexdigest() for record in rejected)
    output = emitted_text(caplog, capsys)
    assert f"'assist_operation': '{operation}'" in output
    assert PRIVATE not in output and 'private_field' not in output and 'submission-0001' not in output


@pytest.mark.parametrize('kind,mode,capabilities,visuals,rule', [
    ('modes', 'orchestration', [], [], 'chat_mode_unavailable'),
    ('capabilities', 'selected', ['web_search'], [], 'chat_capability_unavailable'),
    ('visual_requirements', 'selected', [], ['diagram'], 'chat_output_unavailable'),
])
def test_chat_availability_rejections_retain_specific_safe_rules(
    diagnostic_logger, caplog, capsys, kind, mode, capabilities, visuals, rule,
):
    _settings, logger = diagnostic_logger
    reply = wa.reply(operations=[{
        'op': 'set_workflow_chat_execution', 'mode': mode,
        'required_capabilities': capabilities, 'visual_requirements': visuals,
    }])
    choices = {'chat_execution': {
        'modes': [{'id': mode, 'available': kind != 'modes'}],
        'capabilities': [{'id': identity, 'available': kind != 'capabilities'} for identity in capabilities],
        'visual_requirements': [{'id': identity, 'available': kind != 'visual_requirements'} for identity in visuals],
    }}
    bundle = wa.services(wa.ScriptedModel(reply, reply), options=choices)
    bundle.diagnostics = AssistDiagnostics(telemetry.log_assist_debug)
    with caplog.at_level(logging.INFO, logger=logger.name):
        with pytest.raises(workflow.WorkflowAssistError) as caught:
            wa.run(wa.request_body(instruction=PRIVATE), bundle)
    assert caught.value.code == 'assistant_output_invalid'
    rejected = [record for record in records(caplog) if record.sc_assist_event == 'validation_rejected']
    assert len(rejected) == 2
    assert all(record.sc_assist_rule == rule and record.sc_assist_stage == 'apply' for record in rejected)
    assert all(record.sc_assist_operation == 'set_workflow_chat_execution' for record in rejected)
    output = emitted_text(caplog, capsys)
    assert f"'assist_rule': '{rule}'" in output
    assert PRIVATE not in output


@pytest.mark.parametrize('validation_code', ['invalid_workflow', PRIVATE])
def test_workflow_save_validation_drops_private_codes_and_messages(diagnostic_logger, caplog, capsys, validation_code):
    _settings, logger = diagnostic_logger
    def dry_run(_user_id, payload):
        if payload['name'] == 'Rejected SQL workflow':
            return {'ok': False, 'errors': [{'code': validation_code, 'message': PRIVATE, 'path': UNKNOWN_PATH}]}
        return {'ok': True, 'errors': []}
    reply = wa.reply(operations=[{'op': 'set_name', 'name': 'Rejected SQL workflow'}])
    bundle = wa.services(wa.ScriptedModel(reply, reply), dry_run=dry_run)
    bundle.diagnostics = AssistDiagnostics(telemetry.log_assist_debug)
    with caplog.at_level(logging.INFO, logger=logger.name):
        with pytest.raises(workflow.WorkflowAssistError):
            wa.run(wa.request_body(), bundle)
    rejected = [record for record in records(caplog) if record.sc_assist_event == 'validation_rejected']
    assert [record.sc_assist_rule for record in rejected] == ['save_validation', 'save_validation']
    assert all(getattr(record, 'sc_assist_validation_code', None) ==
               ('invalid_workflow' if validation_code != PRIVATE else None) for record in rejected)
    output = emitted_text(caplog, capsys)
    assert PRIVATE not in output and UNKNOWN_PATH not in output


def test_diagnostic_logger_failures_do_not_change_results_or_cleanup():
    def failed_log(_properties):
        raise RuntimeError(PRIVATE)
    limiter = FakeLimiter()
    result = run_editor(ScriptedModel(changed()), limiter=limiter, diagnostics=AssistDiagnostics(failed_log))
    assert result['outcome'] == 'changed'
    assert limiter.events[-1] == ('release', False)


def test_allowlist_rejects_unknown_fields_categories_and_non_finite_measurements():
    safe = safe_assist_diagnostics({
        'assist_rule': 'private_prompt', 'assist_field': UNKNOWN_PATH,
        'assist_operation': PRIVATE,
        'assist_finish_reason': PRIVATE, 'prompt': PRIVATE, 'password': PRIVATE,
        'elapsed_ms': float('nan'), 'provider_status': float('inf'), 'attempt': True,
        'output_length': 10 ** 1000, 'turn_id_hash': PRIVATE, 'assist_stage': 'operations',
    })
    assert safe == {'output_length': 1_000_000_000, 'assist_stage': 'operations'}


class Client:
    def __init__(self, *answers):
        self.answers = iter(answers)
        self.calls = []

    def with_options(self, **options):
        def create(**parameters):
            self.calls.append((options, parameters))
            answer = next(self.answers)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def completion(finish='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=json.dumps(changed()), refusal=None), finish_reason=finish,
    )])


@pytest.mark.parametrize('debug', [False, True])
@pytest.mark.parametrize('failure,code', [
    (openai.APITimeoutError(request=REQUEST), 'assistant_timeout'),
    (openai.AuthenticationError(PRIVATE, response=httpx.Response(401, request=REQUEST), body=None), 'assistant_unavailable'),
    (openai.RateLimitError(PRIVATE, response=httpx.Response(429, request=REQUEST), body=None), 'assistant_unavailable'),
])
def test_provider_failures_keep_only_safe_status_and_code(diagnostic_logger, caplog, capsys, failure, code, debug):
    settings, logger = diagnostic_logger
    settings['enable_debug_logging'] = debug
    diagnostics = AssistDiagnostics(telemetry.log_assist_debug)
    client = Client(failure)
    services = editor_runtime.build_editor_assist_services(
        client_factory=lambda: (client, 'gpt-4o'), limiter=FakeLimiter(),
    )
    services.diagnostics = diagnostics
    services.call_model = editor_runtime._ConvertingModel(runtime.WorkflowAssistModel(
        lambda: (client, 'gpt-4o'), diagnostics=diagnostics,
    ))
    with caplog.at_level(logging.INFO, logger=logger.name):
        with pytest.raises(editor.EditorAssistError) as caught:
            editor.run_editor_assist(agent_body(instruction=PRIVATE), kind='agent', scope='personal',
                                     user_id='user', services=services)
    assert caught.value.code == code
    if debug:
        failed = next(record for record in records(caplog) if record.sc_assist_event == 'provider_failed')
        assert failed.sc_assist_code == code and failed.sc_provider_attempt == 1
        assert getattr(failed, 'sc_provider_status', None) == getattr(failure, 'status_code', None)
    else:
        assert records(caplog) == []
    assert len(client.calls) == 1
    assert PRIVATE not in emitted_text(caplog, capsys)


@pytest.mark.parametrize('debug', [False, True])
def test_json_mode_fallback_is_debug_visible_without_provider_message(diagnostic_logger, caplog, capsys, debug):
    settings, logger = diagnostic_logger
    settings['enable_debug_logging'] = debug
    failure = openai.BadRequestError(
        PRIVATE, response=httpx.Response(400, request=REQUEST),
        body={'code': 'unsupported_parameter', 'param': 'response_format',
              'message': 'response_format is not supported with this model.'},
    )
    client = Client(failure, completion())
    services = editor_runtime.build_editor_assist_services(
        client_factory=lambda: (client, 'gpt-4o'), limiter=FakeLimiter(),
    )
    with caplog.at_level(logging.INFO, logger=logger.name):
        result = editor.run_editor_assist(agent_body(), kind='agent', scope='personal', user_id='user',
                                         services=services)
    assert result['outcome'] == 'changed'
    if debug:
        fallback = next(record for record in records(caplog) if record.sc_assist_event == 'json_mode_fallback')
        assert fallback.sc_provider_status == 400 and fallback.sc_json_mode is True and fallback.sc_provider_attempt == 1
        finished = next(record for record in records(caplog) if record.sc_assist_event == 'provider_finished')
        assert finished.sc_provider_attempt == 2 and finished.sc_json_mode is False and finished.sc_provider_duration_ms >= 0
    else:
        assert records(caplog) == []
    assert 'response_format' in client.calls[0][1] and 'response_format' not in client.calls[1][1]
    assert PRIVATE not in emitted_text(caplog, capsys)


def test_implementation_version():
    assert_app_version_at_least('0.261.362')


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
