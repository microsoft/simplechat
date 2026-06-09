# functions_chart_operations.py
"""Shared configuration helpers for the built-in chart action."""

import json
import re


CHART_PLUGIN_TYPE = 'chart'
CORE_CHART_PLUGIN_NAME = 'conversation_charts'
CHART_DEFAULT_ENDPOINT = 'chart://internal'
INLINE_CHART_BLOCK_LANGUAGE = 'simplechart'
PROACTIVE_CHART_GUIDANCE_MARKER = '[Proactive Analytical Chart Guidance]'

PROACTIVE_CHART_REQUEST_MARKERS = (
    'analyze',
    'analysis',
    'compare',
    'comparison',
    'review',
    'report',
    'presentation',
    'powerpoint',
    'slide deck',
    'deck',
    'markdown',
    'executive summary',
    'dashboard',
    'insights',
    'trend',
    'trends',
    'metrics',
    'dataset',
    'data set',
    'workbook',
    'spreadsheet',
    'csv',
)

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


def user_request_supports_proactive_charts(user_message):
    """Return True when an analytical output request should consider charts proactively."""
    normalized_message = re.sub(r'\s+', ' ', str(user_message or '').strip().lower())
    if not normalized_message:
        return False

    if any(marker in normalized_message for marker in PROACTIVE_CHART_REQUEST_MARKERS):
        return True

    return bool(
        re.search(
            r'\b(?:summari[sz]e|evaluate|assess|explain|find|identify)\b[^.!?\n]{0,120}'
            r'\b(?:data|numbers|totals|counts|revenue|cost|spend|volume|rate|percentage|percent|variance)\b',
            normalized_message,
        )
    )


def build_proactive_chart_guidance_message():
    """Build reusable guidance for proactive, inline analytical chart creation."""
    return (
        f"{PROACTIVE_CHART_GUIDANCE_MARKER}\n"
        "When chart-worthy numeric or categorical data is present, proactively include inline charts as part of the answer, "
        "generated Markdown, report, workflow output, or presentation-ready content. The user does not need to explicitly ask for charts. "
        "For comprehensive analysis, comparison, reporting, or slide-deck style output, include multiple high-value charts when the data supports multiple distinct patterns. "
        "Use 2 to 5 charts for broad reviews, one chart for narrow findings, and no charts when the available evidence is too thin or purely textual. "
        "Place each chart immediately after the paragraph, table, section, or finding it supports; do not collect charts only at the end unless the user asks for an appendix. "
        "Choose chart types from the discovered data shape: line or area for time trends; bar for category comparisons; stacked bar or stacked line for category composition over groups or time; "
        "doughnut or pie only for small part-to-whole splits; scatter or bubble for relationships between numeric measures; radar for compact multi-metric profiles. "
        "When the user asks for specific colors, or when labels have obvious semantic colors, set dataset backgroundColor and borderColor explicitly; for pie, doughnut, and polar-area charts use one color per slice in array order. "
        "Use tool-backed tabular results, computed aggregates, or explicitly cited source values as chart data. Do not invent values, and summarize omitted categories when charting top-N slices. "
        "When a chart action/tool is available, call it for each useful chart and insert the returned chart_markdown exactly where the visual belongs in the generated content. "
        f"Use SimpleChat inline chart blocks only: emit compact ```{INLINE_CHART_BLOCK_LANGUAGE}``` blocks with version 1, kind, chartType, title, data.labels, data.datasets, options, and summary fields when a tool call cannot return chart_markdown. "
        "Do not output Mermaid, matplotlib/Python, Vega, or other chart code blocks as the visual chart response unless the user explicitly asks for source code instead of an inline chart."
    )


def append_proactive_chart_guidance(prompt_text, force=False):
    """Append proactive chart guidance to analytical prompts when appropriate."""
    normalized_prompt = str(prompt_text or '').strip()
    if not normalized_prompt:
        return build_proactive_chart_guidance_message() if force else normalized_prompt

    if PROACTIVE_CHART_GUIDANCE_MARKER in normalized_prompt:
        return normalized_prompt

    if not force and not user_request_supports_proactive_charts(normalized_prompt):
        return normalized_prompt

    return f"{normalized_prompt}\n\n{build_proactive_chart_guidance_message()}"
