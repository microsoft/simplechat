# test_azure_billing_dynamic_charts.py
#!/usr/bin/env python3
"""
Functional test for Azure Billing dynamic chart output.
Version: 0.250.001
Implemented in: 0.242.074

This test ensures the Azure Billing action returns SimpleChat simplechart
markdown instead of matplotlib PNG image payloads.
"""

import sys
import types
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PROJECT_ROOT / 'application' / 'single_app'
PLUGIN_ROOT = PROJECT_ROOT / 'application' / 'community_customizations' / 'actions' / 'azure_billing_retriever'

for path in (APP_ROOT, PLUGIN_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

sys.modules.setdefault(
    'functions_appinsights',
    types.SimpleNamespace(
        log_event=lambda *_args, **_kwargs: None,
        get_appinsights_logger=lambda: None,
    ),
)
sys.modules.setdefault(
    'functions_authentication',
    types.SimpleNamespace(
        get_current_user_id=lambda: 'test-user',
        get_valid_access_token_for_plugins=lambda *_args, **_kwargs: {'error': 'not used'},
    ),
)
sys.modules.setdefault(
    'functions_debug',
    types.SimpleNamespace(debug_print=lambda *_args, **_kwargs: None),
)

from azure_billing_plugin import AzureBillingPlugin


def _build_plugin():
    return AzureBillingPlugin({
        'metadata': {'name': 'azure_billing_dynamic_chart_test'},
        'additionalFields': {'apiVersion': '2023-03-01'},
        'auth': {'type': 'user'},
        'endpoint': 'https://management.azure.com',
    })


def test_plot_chart_returns_stacked_simplechart_markdown():
    """Validate stacked billing charts use dynamic simplechart output."""
    print('Testing Azure Billing stacked dynamic chart output...')
    plugin = _build_plugin()
    rows = [
        {'BillingMonth': '2026-01', 'ResourceType': 'Virtual Machines', 'PreTaxCost': 100},
        {'BillingMonth': '2026-01', 'ResourceType': 'Virtual Machines', 'PreTaxCost': 75},
        {'BillingMonth': '2026-01', 'ResourceType': 'Disks', 'PreTaxCost': 50},
        {'BillingMonth': '2026-02', 'ResourceType': 'Virtual Machines', 'PreTaxCost': 125},
    ]

    result = plugin.plot_chart(
        conversation_id='conversation-123',
        data=rows,
        x_keys=['BillingMonth', 'ResourceType'],
        y_keys=['PreTaxCost'],
        graph_type='column_stacked',
        title='Monthly Cost by Resource Type',
        xlabel='Billing Month',
        ylabel='Pre-tax Cost',
    )

    assert result['status'] == 'ok', result
    assert result['type'] == 'inline_chart', result
    assert result['chart_markdown'].startswith('```simplechart\n'), result['chart_markdown']
    assert 'image_url' not in result, result
    assert 'requires_message_reload' not in result, result

    payload = result['chart_payload']
    assert payload['kind'] == 'stacked_bar', payload
    assert payload['chartType'] == 'bar', payload
    assert payload['options']['stacked'] is True, payload
    assert payload['data']['labels'] == ['2026-01', '2026-02'], payload

    datasets = {dataset['label']: dataset['data'] for dataset in payload['data']['datasets']}
    assert datasets['Virtual Machines'] == [175.0, 125.0], datasets
    assert datasets['Disks'] == [50.0, None], datasets
    print('PASS: Azure Billing stacked dynamic chart output')


def test_plot_chart_accepts_csv_for_pie_simplechart():
    """Validate CSV input can produce pie simplechart markdown."""
    print('Testing Azure Billing CSV pie dynamic chart output...')
    plugin = _build_plugin()
    csv_data = 'ResourceType,PreTaxCost\nVirtual Machines,100\nDisks,50\nStorage,25\n'

    result = plugin.plot_chart(
        conversation_id='conversation-123',
        data=csv_data,
        x_keys=['ResourceType'],
        y_keys=['PreTaxCost'],
        graph_type='pie',
        title='Cost Share by Resource Type',
    )

    assert result['status'] == 'ok', result
    assert result['chart_payload']['kind'] == 'pie', result
    assert result['chart_payload']['data']['labels'] == ['Virtual Machines', 'Disks', 'Storage'], result
    assert result['chart_markdown'].startswith('```simplechart\n'), result['chart_markdown']
    assert 'data:image/png;base64' not in result['chart_markdown'], result['chart_markdown']
    print('PASS: Azure Billing CSV pie dynamic chart output')


def test_plugin_no_longer_uses_matplotlib_png_path():
    """Validate the Azure Billing chart path no longer depends on matplotlib image output."""
    print('Testing Azure Billing source no longer uses matplotlib PNG charting...')
    source = (PLUGIN_ROOT / 'azure_billing_plugin.py').read_text(encoding='utf-8')

    disallowed_markers = [
        'matplotlib',
        'plt.',
        '_fig_to_base64_dict',
        'upload_cosmos_message',
        'data:image/png;base64',
    ]
    for marker in disallowed_markers:
        assert marker not in source, f'Found stale marker: {marker}'

    assert 'ChartPlugin' in source
    assert 'chart_markdown' in source
    print('PASS: Azure Billing source no longer uses matplotlib PNG charting')


if __name__ == '__main__':
    tests = [
        test_plot_chart_returns_stacked_simplechart_markdown,
        test_plot_chart_accepts_csv_for_pie_simplechart,
        test_plugin_no_longer_uses_matplotlib_png_path,
    ]
    results = []

    for test in tests:
        print(f'Running {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)
