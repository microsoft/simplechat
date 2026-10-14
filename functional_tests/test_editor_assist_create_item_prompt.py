# test_editor_assist_create_item_prompt.py
"""
Regression coverage for the live-reproduced SQL-agent creation contract failure.
Version: 0.261.329
Implemented in: 0.261.329

The configured Azure model used unprefixed action names and blank connection
details on a real browser-generated request. Offline cases preserve strict
validation and verify the prompt distinguishes set paths from new-item paths.
"""

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'application' / 'single_app'))
sys.path.insert(0, str(ROOT / 'functional_tests'))

import functions_editor_assist as core  # noqa: E402
from functions_assist_diagnostics import AssistDiagnostics  # noqa: E402
from test_editor_assist_core import FakeLimiter, ScriptedModel, agent_body  # noqa: E402


def sql_body():
    return agent_body(instruction='i want to connect to a sql database', new_items={
        'target': '/actions', 'types': [{'value': 'sql_query', 'label': 'SQL query'}],
        'common': [
            {'path': '/displayName', 'kind': 'text', 'required': True},
            {'path': '/description', 'kind': 'textarea'},
        ],
        'variants': {'sql_query': [
            {'path': '/additionalFields/server', 'kind': 'text', 'required': True},
            {'path': '/additionalFields/database', 'kind': 'text', 'required': True},
        ]},
    })


def test_prompt_separates_set_paths_from_new_action_paths_and_missing_details():
    request = core.parse_editor_assist_request(sql_body(), kind='agent', scope='personal')
    prompt = core.system_prompt(request)
    assert 'For set operations, use only paths listed in draft.fields' in prompt
    assert 'including the leading "/"' in prompt
    assert '"/displayName"' in prompt and '"displayName"' in prompt
    assert 'omit that field from "values"' in prompt
    assert 'blank placeholders' in prompt


def test_live_observed_unprefixed_fields_remain_rejected_instead_of_silently_repaired():
    bad = {'reply': 'Drafted.', 'operations': [{
        'op': 'create_item', 'handle': 'N1', 'type': 'sql_query', 'values': {
            'displayName': 'SQL lookup', 'description': 'Read rows.',
            '/additionalFields/server': '', '/additionalFields/database': '',
        },
    }]}
    corrected_but_still_invalid = copy.deepcopy(bad)
    del corrected_but_still_invalid['operations'][0]['values']['/additionalFields/server']
    del corrected_but_still_invalid['operations'][0]['values']['/additionalFields/database']
    events = []
    services = core.EditorAssistServices(
        limiter=FakeLimiter(), call_model=ScriptedModel(bad, corrected_but_still_invalid),
        diagnostics=AssistDiagnostics(events.append),
    )
    body = sql_body()
    before = copy.deepcopy(body)
    with pytest.raises(core.EditorAssistError) as caught:
        core.run_editor_assist(body, kind='agent', scope='personal', user_id='test-user', services=services)
    assert caught.value.code == 'assistant_output_invalid'
    assert body == before
    rejected = [event for event in events if event['assist_event'] == 'validation_rejected']
    assert [event['assist_rule'] for event in rejected] == [
        'new_field_unknown', 'new_field_unknown', 'required_value', 'required_value', 'new_required_field',
        'new_field_unknown', 'new_field_unknown', 'new_required_field',
    ]


def test_exact_action_paths_and_omitted_unknown_connection_details_make_a_valid_draft():
    reply = {'reply': 'Enter the connection details before saving.', 'operations': [{
        'op': 'create_item', 'handle': 'N1', 'type': 'sql_query',
        'values': {'/displayName': 'SQL lookup', '/description': 'Read rows.'},
    }]}
    services = core.EditorAssistServices(limiter=FakeLimiter(), call_model=ScriptedModel(reply))
    result = core.run_editor_assist(sql_body(), kind='agent', scope='personal', user_id='test-user', services=services)
    assert result['outcome'] == 'changed'
    assert result['candidate']['new_items'][0]['values'] == reply['operations'][0]['values']
    assert 'new:N1' in result['candidate']['values']['/actions']


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
