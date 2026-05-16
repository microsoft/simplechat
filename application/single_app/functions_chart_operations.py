# functions_chart_operations.py
"""Shared configuration helpers for the built-in chart action."""

import json


CHART_PLUGIN_TYPE = 'chart'
CORE_CHART_PLUGIN_NAME = 'conversation_charts'
CHART_DEFAULT_ENDPOINT = 'chart://internal'
INLINE_CHART_BLOCK_LANGUAGE = 'simplechart'

CHART_KIND_ALIASES = {
    'line': 'line',
    'lines': 'line',
    'bar': 'bar',
    'bars': 'bar',
    'pie': 'pie',
    'doughnut': 'doughnut',
    'donut': 'doughnut',
    'scatter': 'scatter',
    'scatterplot': 'scatter',
    'scatter_plot': 'scatter',
    'bubble': 'bubble',
    'area': 'area',
    'radar': 'radar',
    'polar_area': 'polar_area',
    'polararea': 'polar_area',
    'stacked_bar': 'stacked_bar',
    'stacked bar': 'stacked_bar',
    'stackedbar': 'stacked_bar',
    'stacked_line': 'stacked_line',
    'stacked line': 'stacked_line',
    'stackedline': 'stacked_line',
}

CHART_CAPABILITY_DEFINITIONS = [
    {
        'key': 'line',
        'label': 'Line charts',
        'description': 'Render single-series or multi-series line charts.',
        'chart_kind': 'line',
    },
    {
        'key': 'bar',
        'label': 'Bar charts',
        'description': 'Render categorical bar charts, including grouped multi-series bars.',
        'chart_kind': 'bar',
    },
    {
        'key': 'pie',
        'label': 'Pie charts',
        'description': 'Render proportional pie charts for part-to-whole comparisons.',
        'chart_kind': 'pie',
    },
    {
        'key': 'doughnut',
        'label': 'Doughnut charts',
        'description': 'Render proportional doughnut charts using the existing Chart.js stack.',
        'chart_kind': 'doughnut',
    },
    {
        'key': 'scatter',
        'label': 'Scatter plots',
        'description': 'Render XY scatter plots with optional series grouping.',
        'chart_kind': 'scatter',
    },
    {
        'key': 'area',
        'label': 'Area charts',
        'description': 'Render filled line charts for trend visualization.',
        'chart_kind': 'area',
    },
    {
        'key': 'bubble',
        'label': 'Bubble charts',
        'description': 'Render bubble charts with x, y, and size dimensions.',
        'chart_kind': 'bubble',
    },
    {
        'key': 'radar',
        'label': 'Radar charts',
        'description': 'Render radar charts for multi-axis comparisons.',
        'chart_kind': 'radar',
    },
    {
        'key': 'stacked_bar',
        'label': 'Stacked bar charts',
        'description': 'Render stacked bar charts for cumulative category comparisons.',
        'chart_kind': 'stacked_bar',
    },
    {
        'key': 'stacked_line',
        'label': 'Stacked line charts',
        'description': 'Render stacked line charts for cumulative trends across series.',
        'chart_kind': 'stacked_line',
    },
]


def get_default_chart_capabilities():
    """Return the default enabled chart kinds for built-in chart actions."""
    return {
        definition['key']: True
        for definition in CHART_CAPABILITY_DEFINITIONS
    }


def normalize_chart_capabilities(raw_capabilities):
    """Normalize stored chart capability settings into a complete boolean map."""
    normalized = get_default_chart_capabilities()
    if not isinstance(raw_capabilities, dict):
        return normalized

    for definition in CHART_CAPABILITY_DEFINITIONS:
        key = definition['key']
        if key in raw_capabilities:
            normalized[key] = bool(raw_capabilities.get(key))

    return normalized


def resolve_chart_action_capabilities(
    action_capability_map=None,
    default_capabilities=None,
    action_id=None,
    action_name=None,
):
    """Merge per-agent overrides with action-level default chart capabilities."""
    resolved = normalize_chart_capabilities(default_capabilities)
    if not isinstance(action_capability_map, dict):
        return resolved

    for candidate_key in (str(action_id or '').strip(), str(action_name or '').strip()):
        if candidate_key and candidate_key in action_capability_map:
            return normalize_chart_capabilities(action_capability_map.get(candidate_key))

    return resolved


def get_enabled_chart_type_keys(raw_capabilities=None):
    """Return the enabled chart capability keys in display order."""
    normalized = normalize_chart_capabilities(raw_capabilities)
    return [
        definition['key']
        for definition in CHART_CAPABILITY_DEFINITIONS
        if normalized.get(definition['key'])
    ]


def normalize_chart_kind(chart_kind):
    """Normalize user-supplied chart type aliases to a supported capability key."""
    candidate = str(chart_kind or '').strip().lower().replace('-', '_')
    if not candidate:
        return ''

    candidate = CHART_KIND_ALIASES.get(candidate, candidate)
    for definition in CHART_CAPABILITY_DEFINITIONS:
        if candidate in {definition['key'], definition['chart_kind']}:
            return definition['key']

    return candidate


def build_inline_chart_markdown(chart_payload):
    """Serialize a validated chart payload into an inline chat fence."""
    return (
        f"```{INLINE_CHART_BLOCK_LANGUAGE}\n"
        f"{json.dumps(chart_payload, separators=(',', ':'))}\n"
        f"```"
    )