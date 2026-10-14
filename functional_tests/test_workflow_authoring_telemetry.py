# test_workflow_authoring_telemetry.py
"""
Real logging-sink tests for Ask AI diagnostics.
Version: 0.261.329
Implemented in: 0.261.329

Uses the existing blocked-network application bootstrap and synthetic model
responses to prove categories/counts survive sanitization without private text.
"""

import importlib
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'application' / 'single_app'))
# The shared offline bootstrap imports real application owners from this path.
from test_orchestration_harness_execution import initialized_application
from test_support import workflow_assist as wa


@pytest.mark.parametrize('debug', [False, True])
def test_real_logger_retains_codes_and_numeric_usage_without_raw_identifiers(
    initialized_application, monkeypatch, caplog, capsys, debug,
):
    telemetry = importlib.import_module('functions_appinsights')
    runtime = importlib.import_module('functions_workflow_assist_runtime')
    logger = logging.getLogger('test.workflow.authoring.telemetry')
    monkeypatch.setattr(telemetry, 'get_appinsights_logger', lambda: logger)
    monkeypatch.setattr(telemetry, '_load_logging_settings', lambda: {'enable_debug_logging': debug})
    response = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=wa.reply('changed', 'PRIVATE_REPLY', [
                {'op': 'set_name', 'name': 'PRIVATE_DRAFT_NAME'},
            ]), refusal=None),
            finish_reason='stop',
        )],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=25, total_tokens=125),
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_kwargs: response)),
    )
    client.with_options = lambda **_kwargs: client
    model = runtime.WorkflowAssistModel(lambda: (client, 'synthetic-deployment'), clock=wa.FakeClock())
    bundle = wa.services(model)
    bundle.log = lambda message, extra, level: telemetry.log_event(message, extra=extra, level=level)
    with caplog.at_level(logging.INFO, logger=logger.name):
        result = wa.run(wa.request_body(instruction='PRIVATE_PROMPT'), bundle)
    assert result['outcome'] == 'changed'
    [finished] = [record for record in caplog.records
                  if getattr(record, 'sc_message', '') == '[WORKFLOW_ASSIST] Assist request finished']
    assert finished.sc_output_code == 'changed'
    assert finished.sc_execution_code == 'response'
    assert finished.sc_validation_code == 'not_required'
    assert len(finished.sc_turn_id_hash) == 64
    [usage] = [record for record in caplog.records
               if getattr(record, 'sc_message', '') == '[WORKFLOW_ASSIST] Model response received']
    assert (usage.sc_input_count, usage.sc_output_count, usage.sc_total_count) == (100, 25, 125)
    properties = [{key: value for key, value in record.__dict__.items() if key.startswith('sc_')}
                  for record in caplog.records]
    output = capsys.readouterr()
    encoded = json.dumps(properties) + output.out + output.err
    for private in ('PRIVATE_', wa.USER_ID, 'submission-0001'):
        assert private not in encoded
