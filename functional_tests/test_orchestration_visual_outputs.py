#!/usr/bin/env python3
# test_orchestration_visual_outputs.py
"""
Functional test for charts, Mermaid diagrams, and image proposals in orchestrated answers.
Version: 0.261.132
Implemented in: 0.261.132

This test ensures orchestration detects requested visuals the way ordinary chat does,
gives the answer step chart, Mermaid, and image-proposal guidance that defers to saved
instruction memories, charts exact tool rows within the 200-point display limit, carries
charts created during gathering into the final answer untruncated, and tells the planner
which visual outputs are available. No Azure resources, models, or credentials are used.
"""

import asyncio
import importlib
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from test_support.app_stubs import APP_ROOT, stubbed_app_imports, stubbed_config
from test_support.orchestration_research import document_action_policy_module
from test_support.versioning import assert_app_version_at_least


if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import functions_chart_operations as charts  # noqa: E402
import functions_orchestration_visuals as visuals  # noqa: E402


IMPLEMENTED_IN = '0.261.132'
PLOT_REQUEST = 'Plot BatteryVoltage1 over the last 15 minutes, provide high granularity'


def fake_module(name, **values):
    result = types.ModuleType(name)
    result.__dict__.update(values)
    return result


def telemetry_rows(count=900, newest_first=True):
    """One-second telemetry samples, newest first like Yamcs archive history."""
    start = datetime(2026, 9, 23, 19, 58, 31, 269000, tzinfo=timezone.utc)
    rows = [
        {
            'generation_time': (start + timedelta(seconds=index)).isoformat().replace('+00:00', 'Z'),
            'eng_value': 27 + index % 5,
            'monitoring_result': 'CRITICAL',
        }
        for index in range(count)
    ]
    if count > 452:
        rows[450]['eng_value'] = 35.5
        rows[451]['eng_value'] = 20.25
    return list(reversed(rows)) if newest_first else rows


def chart_markdown(chart_id='abc123', title='Voltage', points=2):
    return charts.build_inline_chart_markdown({
        'version': 1, 'kind': 'line', 'chartType': 'line', 'chartId': chart_id, 'title': title,
        'subtitle': 'All points shown.',
        'data': {
            'labels': [f'L{index}' for index in range(points)],
            'datasets': [{'label': 'Voltage', 'data': list(range(points))}],
        },
    })


def chart_citation(markdown=None, chart_id='abc123'):
    return {
        'tool_name': 'Chart', 'plugin_name': 'ChartPlugin', 'function_name': 'create_chart',
        'function_result': {
            'success': True,
            'chart_payload': {'chartId': chart_id},
            'chart_markdown': markdown or chart_markdown(chart_id),
        },
    }


@pytest.fixture(scope='module')
def modules():
    with stubbed_config(cognitive_services_scope='https://cognitiveservices.azure.com/.default'), patch.dict(
        sys.modules, {'functions_document_actions': document_action_policy_module()},
    ):
        yield SimpleNamespace(**{
            name: importlib.import_module(f'functions_orchestration_{name}')
            for name in ('registry', 'context', 'schema', 'planner', 'adapters', 'executor', 'memory')
        })


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least(IMPLEMENTED_IN)


# --------------------------------------------------------------------------------------
# Exact-row series charts
# --------------------------------------------------------------------------------------

def test_series_is_sorted_and_reduced_to_the_display_limit_keeping_extremes():
    data = charts.build_series_chart_data(telemetry_rows(), 'generation_time', ['eng_value'])
    values = data['datasets'][0]['data']
    assert data['source_points'] == 900
    assert data['plotted_points'] == len(data['labels']) == len(values) <= charts.INLINE_CHART_MAX_POINTS
    assert data['downsampled'] is True
    assert data['labels'][0] == '19:58:31' and data['labels'][-1] == '20:13:30'
    assert data['labels'] == sorted(data['labels'])
    assert 35.5 in values and 20.25 in values
    assert data['x_axis_label'] == 'Time (UTC, 2026-09-23)'
    assert data['x_kind'] == 'time'
    assert data['begin_at_zero'] is False
    assert data['sampling_note'].startswith(f"{data['plotted_points']} of 900 points shown")


def test_short_series_keeps_every_point_and_supports_several_fields():
    rows = [
        {'minute': index, 'cpu': index * 10, 'memory': '1,2%d' % index}
        for index in range(10)
    ]
    data = charts.build_series_chart_data(rows, 'minute', ['cpu', 'memory'], series_labels=['CPU'])
    assert data['plotted_points'] == data['source_points'] == 10
    assert data['downsampled'] is False
    assert data['sampling_note'] == 'All 10 points shown.'
    assert data['x_kind'] == 'number'
    assert [dataset['label'] for dataset in data['datasets']] == ['CPU', 'Memory']
    assert data['datasets'][1]['data'][0] == 120.0
    assert data['begin_at_zero'] is True


@pytest.mark.parametrize('x_field,y_fields,message', [
    ('missing', ['eng_value'], 'Available fields'),
    ('generation_time', ['monitoring_result'], 'no numeric values'),
    ('generation_time', [], 'at least one numeric field'),
    ('', ['eng_value'], 'x axis'),
])
def test_unchartable_requests_explain_themselves(x_field, y_fields, message):
    with pytest.raises(ValueError) as caught:
        charts.build_series_chart_data(telemetry_rows(20), x_field, y_fields)
    assert message in str(caught.value)


@pytest.mark.parametrize('value,expected', [
    ({'rows': [{'a': 1}]}, 1),
    (json.dumps({'data': [{'a': 1}, {'a': 2}]}), 2),
    ([{'a': 1}, 'noise', {'a': 3}], 2),
    ({'result': {'records': [{'a': 1}]}}, 1),
    ({'status': 'ok'}, 0),
    ('not json', 0),
])
def test_result_rows_are_found_in_common_tool_shapes(value, expected):
    assert len(charts.extract_result_rows(value)) == expected


# --------------------------------------------------------------------------------------
# Which visuals a request asks for
# --------------------------------------------------------------------------------------

def test_explicit_planned_and_proactive_chart_intent_are_distinct():
    explicit = visuals.requested_visual_outputs([PLOT_REQUEST])
    assert explicit['explicit_chart'] and explicit['chart'] and not explicit['proactive_chart']

    planned = visuals.requested_visual_outputs(['How is the battery?'], ['Retrieve the samples and chart the values.'])
    assert planned['chart'] and not planned['explicit_chart']

    proactive = visuals.requested_visual_outputs(['Analyze the quarterly metrics report'])
    assert proactive['proactive_chart'] and not proactive['chart']

    for text in ('Show me the chart of accounts for this tenant', 'Draw our org chart'):
        assert not visuals.requested_visual_outputs([], [text])['chart']


def test_diagram_intent_comes_from_the_user_or_the_plan():
    assert visuals.requested_visual_outputs(['Draw a flowchart of the login process'])['diagram']
    assert visuals.requested_visual_outputs(['Explain it'], ['Include a Mermaid sequence of the calls.'])['diagram']
    assert not visuals.requested_visual_outputs(['What is the capital of France?'])['diagram']


def test_image_proposals_need_image_generation_and_follow_the_request_or_image_control():
    enabled = {'enable_image_generation': True}
    selected = {'image_generation': True}
    assert not visuals.requested_visual_outputs(['Create an illustration'], settings={}, seeds=selected)['image']
    assert not visuals.requested_visual_outputs(['What is 2 + 2?'], settings=enabled)['image']
    assert visuals.requested_visual_outputs(['Create an illustration of the launch'], settings=enabled)['image']
    assert visuals.requested_visual_outputs(['Plan it'], ['Propose images of the venue.'], settings=enabled)['image']
    chosen = visuals.requested_visual_outputs(['What is 2 + 2?'], settings=enabled, seeds=selected)
    assert chosen['image'] and chosen['image_required']
    assert visuals.planner_visual_outputs(enabled) == {'charts': True, 'diagrams': True, 'image_proposals': True}
    assert visuals.planner_visual_outputs({})['image_proposals'] is False


# --------------------------------------------------------------------------------------
# Guidance and saved memory precedence
# --------------------------------------------------------------------------------------

def test_answer_guidance_reuses_chat_guidance_and_defers_to_saved_memory():
    assert visuals.build_answer_visual_guidance({}) == []
    requested = visuals.requested_visual_outputs(
        [f'{PLOT_REQUEST} and draw a flowchart of the pipeline'], settings={'enable_image_generation': True},
        seeds={'image_generation': True},
    )
    messages = visuals.build_answer_visual_guidance(requested, has_existing_charts=True)
    policy = messages[0]
    assert policy.startswith(visuals.VISUAL_OUTPUT_POLICY_MARKER)
    assert 'Saved instruction memories about visuals' in policy and 'take precedence' in policy
    assert 'explicitly asks otherwise' in policy
    assert 'never say a chart could not be produced' in policy
    assert 'at least one image proposal' in policy
    joined = '\n'.join(messages)
    assert charts.PROACTIVE_CHART_GUIDANCE_MARKER in joined
    assert '[MERMAID_DIAGRAM_GUIDANCE]' in joined
    assert '[OPT_IN_IMAGE_GENERATION_PROPOSAL_GUIDANCE]' in joined


def test_gathering_and_agent_notes_keep_what_each_visual_needs():
    requested = {'chart': True, 'diagram': True, 'image': True}
    assert 'separate chart step' in visuals.gathering_visual_addendum(requested, charts_follow=True)
    assert 'exact numbers' in visuals.gathering_visual_addendum(requested)
    assert 'entities, relationships' in visuals.gathering_visual_addendum(requested)
    assert visuals.gathering_visual_addendum({}) == ''
    note = visuals.agent_visual_note(requested)
    assert note.startswith('Visual output for this request:') and 'chart tool' in note
    assert visuals.agent_visual_note({}) == ''


def test_only_instruction_memories_reach_visual_preferences():
    instruction = {'role': 'system', 'content': '<Instruction Memory>\n- Never make charts.\n</Instruction Memory>'}
    fact = {'role': 'system', 'content': '<Fact Memory>\n- Private fact.\n</Fact Memory>'}
    assert visuals.instruction_memory_messages({'instruction_messages': [instruction]}) == [instruction['content']]
    assert visuals.instruction_memory_messages({'context_messages': [fact, instruction]}) == [instruction['content']]
    assert visuals.instruction_memory_messages(None) == []


def test_memory_loader_separates_instruction_memories_from_facts(modules):
    instruction = {'role': 'system', 'content': '<Instruction Memory>\n- Use red.\n</Instruction Memory>'}
    fact = {'role': 'system', 'content': '<Fact Memory>\n- Saved fact.\n</Fact Memory>'}
    payload = {
        'context_messages': [instruction, fact], 'citations': [],
        'instruction_payload': {'context_messages': [instruction]},
        'recall_payload': {'search_mode': 'embedding'},
    }
    memory_module = fake_module(
        'functions_fact_memory_context', build_fact_memory_prompt_payload=lambda **kwargs: payload,
    )
    with patch.dict(sys.modules, {'functions_fact_memory_context': memory_module}):
        loaded = modules.memory.load_orchestration_memory(
            'user1', {'id': 'conv1', 'user_id': 'user1'}, 'Plot it', settings={'enable_fact_memory_plugin': True},
        )
    assert loaded['instruction_messages'] == [instruction]
    assert loaded['context_messages'] == [instruction, fact]


# --------------------------------------------------------------------------------------
# Chart carrying and placement
# --------------------------------------------------------------------------------------

def test_run_charts_are_deduplicated_described_and_bounded():
    big = chart_markdown('huge', title='T' * visuals.MAX_CARRIED_CHART_MARKDOWN_LENGTH, points=1)
    found = visuals.collect_run_charts([
        chart_citation(), chart_citation(), {'function_result': {'rows': [{'a': 1}]}},
        chart_citation(big, 'huge'),
    ])
    assert [chart['chart_id'] for chart in found] == ['abc123']
    assert found[0]['title'] == 'Voltage' and found[0]['kind'] == 'line' and found[0]['points'] == 2
    note = visuals.build_existing_charts_note(found)
    assert '[[chart:abc123]] Voltage (line chart, 2 points, All points shown.)' in note
    assert visuals.is_inline_chart_citation(chart_citation())
    assert not visuals.is_inline_chart_citation({'function_result': {'rows': []}})


def test_charts_are_placed_at_their_tokens_or_appended_once():
    found = visuals.collect_run_charts([chart_citation()])
    markdown = found[0]['chart_markdown']

    placed = visuals.place_chart_blocks('Intro\n\n`[[chart:abc123]]`\n\nOutro [[chart:unknown]]', found)
    assert placed.index('Intro') < placed.index(markdown) < placed.index('Outro')
    assert placed.count(markdown) == 1 and '`' not in placed.replace(markdown, '') and '[[chart:' not in placed

    appended = visuals.place_chart_blocks('Only prose.', found)
    assert appended.startswith('Only prose.') and appended.endswith(markdown)
    assert visuals.place_chart_blocks(appended, found) == appended
    assert visuals.place_chart_blocks('No charts here.', []) == 'No charts here.'
    assert visuals.strip_chart_placeholders('Summary [[chart:abc123]]') == 'Summary'


# --------------------------------------------------------------------------------------
# Answer step integration
# --------------------------------------------------------------------------------------

def respond(modules, *, user_message, settings=None, seeds=None, citations=(), memory=None, reply='Answer'):
    calls = []
    context = modules.executor.RunContext(
        user_id='user1', conversation_id='conv1', user_message=user_message,
        original_seeds=seeds or {}, memory_context=memory or {},
        invoke_prompt=lambda messages, **kwargs: calls.append(messages) or reply,
    )
    context.citations = list(citations)
    result = modules.adapters.run_respond(
        {'arguments': {}}, context, settings=settings or {}, user_id='user1', emit=None, cancel_requested=None,
    )
    return result, calls[0]


def system_contents(messages):
    return [message['content'] for message in messages if message['role'] == 'system']


def test_answer_places_gathered_charts_after_guidance_and_before_memory(modules):
    memory = {'context_messages': [{
        'role': 'system', 'content': '<Instruction Memory>\n- Keep answers short.\n</Instruction Memory>',
    }]}
    result, messages = respond(
        modules, user_message=PLOT_REQUEST, citations=[chart_citation()], memory=memory,
        reply='BatteryVoltage1 stayed between 27 and 31 V.\n\n[[chart:abc123]]\n\nNo gaps were found.',
    )
    systems = system_contents(messages)
    assert systems[0] == modules.adapters.RESPONSE_CONTEXT_POLICY
    assert systems[1].startswith(visuals.VISUAL_OUTPUT_POLICY_MARKER)
    policy_index = next(i for i, text in enumerate(systems) if text.startswith(visuals.VISUAL_OUTPUT_POLICY_MARKER))
    memory_index = next(i for i, text in enumerate(systems) if '<Instruction Memory>' in text)
    chart_index = next(i for i, text in enumerate(systems) if charts.PROACTIVE_CHART_GUIDANCE_MARKER in text)
    assert policy_index < chart_index < memory_index
    assert '[[chart:abc123]] Voltage' in messages[-1]['content']
    markdown = chart_citation()['function_result']['chart_markdown']
    assert result['message'].count(markdown) == 1
    assert result['message'].index('27 and 31 V') < result['message'].index(markdown) < result['message'].index('No gaps')
    assert result['summary'] == 'BatteryVoltage1 stayed between 27 and 31 V.'


def test_answer_without_visuals_is_unchanged(modules):
    result, messages = respond(modules, user_message='What is the capital of France?', reply='Paris.')
    assert not any(visuals.VISUAL_OUTPUT_POLICY_MARKER in text for text in system_contents(messages))
    assert result['message'] == 'Paris.'


def test_answer_offers_diagrams_and_image_proposals_when_available(modules):
    _, messages = respond(modules, user_message='Draw a flowchart of the approval process')
    assert any('[MERMAID_DIAGRAM_GUIDANCE]' in text for text in system_contents(messages))

    enabled = {'enable_image_generation': True}
    _, messages = respond(modules, user_message='Summarize our launch plan', settings=enabled, seeds={'image_generation': True})
    joined = '\n'.join(system_contents(messages))
    assert '[OPT_IN_IMAGE_GENERATION_PROPOSAL_GUIDANCE]' in joined and 'at least one image proposal' in joined

    _, messages = respond(modules, user_message='Summarize our launch plan', settings={}, seeds={'image_generation': True})
    assert '[OPT_IN_IMAGE_GENERATION_PROPOSAL_GUIDANCE]' not in '\n'.join(system_contents(messages))


def test_action_step_keeps_chart_citations_whole_and_reports_the_chart(modules, monkeypatch):
    long_chart = chart_markdown('longchart', title='T' * 25000, points=2)
    invocations = [
        SimpleNamespace(
            plugin_name='ChartPlugin', function_name='create_chart', parameters={},
            result={'success': True, 'chart_payload': {'chartId': 'longchart'}, 'chart_markdown': long_chart},
            success=True, provenance={'root_id': 'root'}, timestamp=None, duration_ms=1, user_id='user1',
        ),
        SimpleNamespace(
            plugin_name='YamcsPlugin', function_name='list_parameter_history', parameters={},
            result={'rows': [{'note': 'x' * 25000}]}, success=True, provenance={'root_id': 'root'},
            timestamp=None, duration_ms=1, user_id='user1',
        ),
    ]
    requests = []

    async def invoke_action(action_ref, task, context, **kwargs):
        requests.append((task, kwargs))
        return {'findings': 'Retrieved 900 samples.', 'artifacts': [], 'invocations': invocations,
                'root_id': 'root', 'calls': 3, 'charts': 1}

    def sanitize(value, max_string_length=20000, _depth=0):
        if isinstance(value, str):
            return value[:max_string_length] + '... [truncated]' if max_string_length and len(value) > max_string_length else value
        if isinstance(value, dict):
            return {key: sanitize(item, max_string_length) for key, item in value.items()}
        if isinstance(value, list):
            return [sanitize(item, max_string_length) for item in value]
        return value

    action = {'action_ref': 'global:global:sim', 'id': 'sim', 'name': 'sim', 'display_name': 'Simulation', 'type': 'yamcs'}
    context = modules.executor.RunContext(
        user_id='user1', conversation_id='conv1', user_message=PLOT_REQUEST, action_catalog=[action],
    )
    stubs = {
        'functions_orchestration_actions': fake_module('functions_orchestration_actions', invoke_action=invoke_action),
        'semantic_kernel_plugins.plugin_invocation_logger': fake_module(
            'semantic_kernel_plugins.plugin_invocation_logger', sanitize_plugin_invocation_value=sanitize,
        ),
        'functions_message_artifacts': fake_module(
            'functions_message_artifacts',
            build_agent_citation_tool_label=lambda plugin, function, *args: f'{plugin}.{function}',
            make_json_serializable=lambda value: value,
        ),
    }
    with patch.dict(sys.modules, stubs):
        result = modules.adapters.run_action_invoke(
            {'arguments': {'action_ref': action['action_ref'], 'task': 'Retrieve BatteryVoltage1 samples.'}},
            context, settings={}, user_id='user1', emit=None, cancel_requested=None,
        )
    assert requests[0][1]['visual_request']['explicit_chart'] is True
    assert result['summary'] == 'Used Simulation (3 function calls) and created 1 chart.'
    chart, telemetry = result['citations']
    assert chart['function_result']['chart_markdown'] == long_chart
    assert telemetry['function_result']['rows'][0]['note'].endswith('[truncated]')


# --------------------------------------------------------------------------------------
# Planner and composer seeds
# --------------------------------------------------------------------------------------

def test_planner_prompt_describes_visual_outputs_only_for_the_legacy_contract(modules):
    legacy = ' '.join(modules.planner.build_planner_messages({}, contract_version=1)[0]['content'].split())
    assert 'image proposal cards' in legacy
    assert 'Charting the values an action retrieves is part of that knowledge step' in legacy
    assert 'Saved instructions in "memory" about visuals' in legacy
    assert 'the respond instruction must ask for at least one image proposal' in legacy
    dependency = ' '.join(modules.planner.build_planner_messages({}, contract_version=2)[0]['content'].split())
    assert 'image proposal cards' not in dependency
    respond_capability = modules.registry.get_capability('respond')
    assert 'Mermaid diagrams' in respond_capability['when_to_use']


@pytest.mark.parametrize('image_enabled', [True, False])
def test_planner_context_reports_visual_outputs_and_the_image_selection(modules, monkeypatch, image_enabled):
    supplied = []
    plan = {'kind': 'plan', 'steps': [{
        'capability_id': 'respond', 'step_id': 'answer', 'arguments': {'instruction': 'Include a line chart.'},
    }]}

    def complete(_client, _deployment, messages, *args, **kwargs):
        supplied.append(json.loads(messages[1]['content']))
        return json.dumps(plan), None

    monkeypatch.setattr(modules.planner, 'resolve_planner_client', lambda settings: (None, 'planner'))
    monkeypatch.setattr(modules.planner, '_call_planner', complete)
    settings = {'enable_chat_orchestration': True, 'enable_image_generation': image_enabled}
    context = modules.context.build_planner_context(PLOT_REQUEST)
    kind, _ = modules.planner.plan_request(
        PLOT_REQUEST, context, 'conversation', 'user1', settings=settings,
        seeds={'image_generation': True}, request_context={},
    )
    assert kind == 'plan'
    availability = supplied[0]['capability_availability']
    assert availability['visual_outputs'] == {'charts': True, 'diagrams': True, 'image_proposals': image_enabled}
    assert supplied[0]['user_selected'].get('image_proposals') is (True if image_enabled else None)


def test_image_seed_is_a_strict_boolean(modules):
    assert modules.context.resolve_seeds({'image_generation_enabled': True})['image_generation'] is True
    assert modules.context.resolve_seeds({'image_generation_enabled': 'true'})['image_generation'] is False
    assert modules.context.resolve_seeds({})['image_generation'] is False


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
