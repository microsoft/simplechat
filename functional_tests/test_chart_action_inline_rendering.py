# test_chart_action_inline_rendering.py
"""
Functional test for inline chart action rendering.
Version: 0.241.139
Implemented in: 0.241.139

This test ensures that the built-in chart action returns validated inline chart markdown
preserves explicit chart colors, and enforces action-level chart type restrictions.
"""

import json
import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PROJECT_ROOT / 'application' / 'single_app'
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
sys.modules.setdefault(
    'olefile',
    types.SimpleNamespace(isOleFile=lambda *_args, **_kwargs: False, OleFileIO=None),
)

from semantic_kernel_plugins.chart_plugin import ChartPlugin


def test_chart_plugin_generates_inline_chart_markdown():
    """Validate chart payload generation for a multi-series line chart."""
    plugin = ChartPlugin({'chart_capabilities': {'line': True}})
    result = plugin.create_chart(
        chart_type='line',
        chart_data_json=json.dumps({
            'rows': [
                {'month': 'Jan', 'revenue': 120, 'target': 110},
                {'month': 'Feb', 'revenue': 146, 'target': 128},
                {'month': 'Mar', 'revenue': 159, 'target': 140},
            ],
            'xField': 'month',
            'yFields': ['revenue', 'target'],
        }),
        title='Quarterly Revenue Trend',
        subtitle='Actual versus target',
        options_json=json.dumps({'smooth': True, 'showDataTable': True}),
    )

    assert result['success'] is True, result
    assert result['chart_markdown'].startswith('```simplechart')
    assert result['chart_markdown'].endswith('```')

    payload = result['chart_payload']
    assert payload['kind'] == 'line'
    assert payload['chartType'] == 'line'
    assert payload['title'] == 'Quarterly Revenue Trend'
    assert payload['subtitle'] == 'Actual versus target'
    assert payload['chartId']
    assert payload['data']['labels'] == ['Jan', 'Feb', 'Mar']
    assert len(payload['data']['datasets']) == 2
    assert payload['table']['columns'] == ['Label', 'Revenue', 'Target']
    assert payload['summary'] == 'Line with 2 series across 3 categories.'


def test_chart_plugin_blocks_disabled_chart_types():
    """Validate that disabled chart types return a validation error instead of a payload."""
    plugin = ChartPlugin({'chart_capabilities': {'line': True, 'pie': False}})
    result = plugin.create_chart(
        chart_type='pie',
        chart_data_json=json.dumps({
            'rows': [
                {'category': 'Search', 'value': 42},
                {'category': 'Chat', 'value': 58},
            ],
            'labelField': 'category',
            'valueField': 'value',
        }),
        title='Usage Mix',
    )

    assert result['success'] is False
    assert result['error_type'] == 'validation'
    assert 'not enabled for this action' in result['error']


def test_chart_plugin_preserves_semantic_pie_slice_colors():
    """Validate pie slice colors can follow user/model color requests."""
    plugin = ChartPlugin({'chart_capabilities': {'pie': True}})
    result = plugin.create_chart(
        chart_type='pie',
        chart_data_json=json.dumps({
            'labels': ['Apples', 'Oranges', 'Pears'],
            'datasets': [{
                'label': 'Share',
                'data': [33, 33, 34],
                'backgroundColor': ['red', 'orange', 'green'],
                'borderColor': ['apple', 'oranges', 'pears'],
            }],
        }),
        title='Fruit Distribution',
    )

    assert result['success'] is True, result
    dataset = result['chart_payload']['data']['datasets'][0]
    assert dataset['backgroundColor'] == ['#dc2626', '#ea580c', '#16a34a']
    assert dataset['borderColor'] == ['#c2410c', '#ea580c', '#16a34a']


if __name__ == '__main__':
    tests = [
        test_chart_plugin_generates_inline_chart_markdown,
        test_chart_plugin_blocks_disabled_chart_types,
        test_chart_plugin_preserves_semantic_pie_slice_colors,
    ]
    results = []

    for test in tests:
        print(f'Running {test.__name__}...')
        try:
            test()
            print('PASS')
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {exc}')
            results.append(False)

    sys.exit(0 if all(results) else 1)