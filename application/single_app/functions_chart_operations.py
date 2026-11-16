# functions_chart_operations.py
"""Shared configuration helpers for the built-in chart action."""

import json
import math
import re
from datetime import datetime, timezone


CHART_PLUGIN_TYPE = 'chart'
CORE_CHART_PLUGIN_NAME = 'conversation_charts'
CHART_DEFAULT_ENDPOINT = 'chart://internal'
INLINE_CHART_BLOCK_LANGUAGE = 'simplechart'
INLINE_CHART_ID_PATTERN_TEMPLATE = '"chartId":"{}"'
PROACTIVE_CHART_GUIDANCE_MARKER = '[PROACTIVE_ANALYTICAL_CHART_GUIDANCE]'

# Both chat clients draw at most this many points per series (`inlineChartSpec.ts` and
# `chat-inline-charts.js`), so a longer series has to be reduced before it is charted
# rather than silently cut off after its first 200 values.
INLINE_CHART_MAX_POINTS = 200
SERIES_CHART_MAX_SOURCE_ROWS = 20000
SERIES_CHART_MAX_SERIES = 6
RESULT_ROW_KEYS = ('rows', 'data', 'values', 'items', 'results', 'records')
_ISO_TIMESTAMP_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}')

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


def user_requested_chart_visualization(user_message):
    """Return True when the user is explicitly asking for a plotted visualization."""
    normalized_message = re.sub(r'\s+', ' ', str(user_message or '').strip().lower())
    if not normalized_message:
        return False

    non_visual_patterns = (
        'chart of accounts',
        'org chart',
        'organization chart',
        'organizational chart',
        'chart out ',
    )
    if any(pattern in normalized_message for pattern in non_visual_patterns):
        return False

    if re.search(
        r'\b(?:bar|line|pie|doughnut|scatter|bubble|radar|histogram|heatmap|area|stacked(?:\s+bar|\s+line)?)\s+chart\b',
        normalized_message,
    ):
        return True

    if 'table and chart' in normalized_message or 'chart and table' in normalized_message:
        return True

    if re.search(r'\b(?:graph|plot|visuali[sz]e?|visuali[sz]ation)\b', normalized_message):
        return True

    return bool(
        re.search(
            r'\b(?:include|with|show|create|generate|render|make|build|draw|produce)\b[^.!?\n]{0,80}\bchart\b',
            normalized_message,
        )
    )


def normalize_inline_chart_markdown(chart_markdown):
    """Return a SimpleChat inline chart fence, or None when the value is not one."""
    block = str(chart_markdown or '').strip()
    if not block.startswith(f'```{INLINE_CHART_BLOCK_LANGUAGE}'):
        return None
    return block


def collect_inline_chart_blocks(candidate, chart_blocks):
    """Append every chart fence found in a tool result or citation tree to ``chart_blocks``."""
    if isinstance(candidate, dict):
        normalized_chart_markdown = normalize_inline_chart_markdown(candidate.get('chart_markdown'))
        if normalized_chart_markdown:
            chart_blocks.append({
                'chart_id': candidate.get('chart_payload', {}).get('chartId') if isinstance(candidate.get('chart_payload'), dict) else None,
                'chart_markdown': normalized_chart_markdown,
            })

        for value in candidate.values():
            collect_inline_chart_blocks(value, chart_blocks)
        return chart_blocks

    if isinstance(candidate, list):
        for item in candidate:
            collect_inline_chart_blocks(item, chart_blocks)
    return chart_blocks


def append_inline_chart_blocks_to_message(message_content, agent_citations):
    """Append chart fences produced by tools that the message does not already contain."""
    chart_blocks = []
    collect_inline_chart_blocks(agent_citations, chart_blocks)

    if not chart_blocks:
        return message_content

    existing_content = str(message_content or '').strip()
    appended_blocks = []
    seen_chart_ids = set()

    for chart_block in chart_blocks:
        chart_id = str(chart_block.get('chart_id') or '').strip()
        chart_markdown = chart_block.get('chart_markdown')
        if not chart_markdown:
            continue

        if chart_id:
            if chart_id in seen_chart_ids:
                continue
            if INLINE_CHART_ID_PATTERN_TEMPLATE.format(chart_id) in existing_content:
                seen_chart_ids.add(chart_id)
                continue
            seen_chart_ids.add(chart_id)

        if chart_markdown in existing_content:
            continue

        appended_blocks.append(chart_markdown)

    if not appended_blocks:
        return message_content

    separator = '\n\n' if existing_content else ''
    return f"{existing_content}{separator}{'\n\n'.join(appended_blocks)}"


def _json_value(value):
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None
    return value


def _row_list(candidate):
    if not isinstance(candidate, list):
        return []
    return [row for row in candidate if isinstance(row, dict)]


def extract_result_rows(value):
    """Return the row objects a tool result carries, or an empty list.

    Tools return rows in a handful of shapes: a bare list of objects, or an object that
    holds the list under ``rows``, ``data``, ``values`` and similar keys, sometimes one
    level down. JSON text is parsed first because Semantic Kernel hands string results
    through unchanged.
    """
    value = _json_value(value)
    rows = _row_list(value)
    if rows:
        return rows
    if not isinstance(value, dict):
        return []
    for key in RESULT_ROW_KEYS:
        rows = _row_list(value.get(key))
        if rows:
            return rows
    for nested in value.values():
        if isinstance(nested, dict):
            for key in RESULT_ROW_KEYS:
                rows = _row_list(nested.get(key))
                if rows:
                    return rows
    return []


def _row_value(row, field):
    if field in row:
        return row[field]
    current = row
    for part in field.split('.'):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _series_number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace(',', '')
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _series_timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or '').strip()
        if not _ISO_TIMESTAMP_PATTERN.match(text):
            return None
        try:
            parsed = datetime.fromisoformat(text.replace(' ', 'T', 1))
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None), True
    return parsed, False


def _field_label(field):
    text = re.sub(r'[_.]+', ' ', str(field or '')).strip()
    return text[:1].upper() + text[1:] if text else 'Value'


def _number_label(number):
    if float(number).is_integer():
        return str(int(number))
    return f'{number:.6g}'


def _time_labels(stamps, aware):
    same_day = len({stamp.date() for stamp in stamps}) == 1
    if same_day:
        labels = [stamp.strftime('%H:%M:%S') for stamp in stamps]
        if len(set(labels)) < len(labels):
            labels = [f"{stamp.strftime('%H:%M:%S')}.{stamp.microsecond // 1000:03d}" for stamp in stamps]
    else:
        labels = [stamp.strftime('%Y-%m-%d %H:%M') for stamp in stamps]
        if len(set(labels)) < len(labels):
            labels = [stamp.strftime('%Y-%m-%d %H:%M:%S') for stamp in stamps]
    details = []
    if aware:
        details.append('UTC')
    if same_day:
        details.append(stamps[0].date().isoformat())
    axis_label = f"Time ({', '.join(details)})" if details else 'Time'
    return labels, axis_label


def _duration_label(seconds):
    if seconds < 1:
        return f'{seconds * 1000:.0f} ms'
    if seconds < 90:
        return f'{seconds:.3g} s'
    if seconds < 5400:
        return f'{seconds / 60:.3g} min'
    return f'{seconds / 3600:.3g} h'


def _extreme_indices(values, max_points):
    """Keep the first and last points and each segment's lowest and highest value.

    Plain every-nth sampling can step straight over a spike. Keeping both extremes of each
    segment means the reduced line still reaches every peak and trough the full series has.
    """
    count = len(values)
    if count <= max_points:
        return list(range(count)), 0
    keep = {0, count - 1}
    interior = count - 2
    segments = max(1, (max_points - 2) // 2)
    for segment in range(segments):
        start = 1 + (segment * interior) // segments
        end = 1 + ((segment + 1) * interior) // segments
        if start >= end:
            continue
        candidates = [index for index in range(start, end) if values[index] is not None]
        if not candidates:
            keep.add(start)
            continue
        keep.add(min(candidates, key=lambda index: values[index]))
        keep.add(max(candidates, key=lambda index: values[index]))
    return sorted(keep)[:max_points], segments


def build_series_chart_data(rows, x_field, y_fields, *, max_points=INLINE_CHART_MAX_POINTS, series_labels=None):
    """Turn exact tool rows into chart labels and datasets that fit the display limit.

    Time and numeric x values are sorted ascending, because tools commonly return newest
    first. When a series has more points than a chart can show, it is reduced by keeping
    every segment's highest and lowest value of the first series, and the same rows are
    used for any other series so the lines stay aligned. Raises ``ValueError`` with a
    message safe to return to the model when the rows cannot be charted as asked.
    """
    if not isinstance(rows, list) or not rows:
        raise ValueError('The selected result has no rows to chart.')
    if len(rows) > SERIES_CHART_MAX_SOURCE_ROWS:
        raise ValueError(
            f'The selected result has more than {SERIES_CHART_MAX_SOURCE_ROWS} rows; narrow the request before charting it.'
        )
    x_field = str(x_field or '').strip()
    fields = [str(field or '').strip() for field in (y_fields or ()) if str(field or '').strip()]
    available = ', '.join(sorted(str(key) for key in rows[0].keys())[:20]) if isinstance(rows[0], dict) else ''
    if not x_field:
        raise ValueError(f'Choose the field for the x axis. Available fields: {available}')
    if not fields:
        raise ValueError(f'Choose at least one numeric field to plot. Available fields: {available}')
    if len(fields) > SERIES_CHART_MAX_SERIES:
        raise ValueError(f'Chart at most {SERIES_CHART_MAX_SERIES} series at once.')
    max_points = max(2, min(int(max_points or INLINE_CHART_MAX_POINTS), INLINE_CHART_MAX_POINTS))

    raw_x = [_row_value(row, x_field) for row in rows]
    present_x = [value for value in raw_x if value not in (None, '')]
    if not present_x:
        raise ValueError(f"No row has a value for '{x_field}'. Available fields: {available}")
    parsed_times = [_series_timestamp(value) for value in present_x]
    if sum(parsed is not None for parsed in parsed_times) >= max(1, int(len(present_x) * 0.9)):
        x_kind = 'time'
    elif sum(_series_number(value) is not None for value in present_x) >= max(1, int(len(present_x) * 0.9)):
        x_kind = 'number'
    else:
        x_kind = 'category'

    points = []
    aware = False
    for index, row in enumerate(rows):
        values = [_series_number(_row_value(row, field)) for field in fields]
        if all(value is None for value in values):
            continue
        if x_kind == 'time':
            parsed = _series_timestamp(raw_x[index])
            if parsed is None:
                continue
            key, is_aware = parsed
            aware = aware or is_aware
        elif x_kind == 'number':
            key = _series_number(raw_x[index])
            if key is None:
                continue
        else:
            if raw_x[index] in (None, ''):
                continue
            key = index
        points.append((key, raw_x[index], values))

    for position, field in enumerate(fields):
        if not any(point[2][position] is not None for point in points):
            raise ValueError(f"'{field}' has no numeric values to plot. Available fields: {available}")
    if x_kind in ('time', 'number'):
        points.sort(key=lambda point: point[0])

    total = len(points)
    kept, segments = _extreme_indices([point[2][0] for point in points], max_points)
    plotted = [points[index] for index in kept]

    if x_kind == 'time':
        labels, axis_label = _time_labels([point[0] for point in plotted], aware)
    elif x_kind == 'number':
        labels, axis_label = [_number_label(point[0]) for point in plotted], _field_label(x_field)
    else:
        labels, axis_label = [str(point[1])[:80] for point in plotted], _field_label(x_field)

    names = [str(label or '').strip() for label in (series_labels or ())]
    datasets = [
        {
            'label': (names[position] if position < len(names) and names[position] else _field_label(field))[:80],
            'data': [point[2][position] for point in plotted],
        }
        for position, field in enumerate(fields)
    ]

    plotted_values = [value for point in plotted for value in point[2] if value is not None]
    low, high = min(plotted_values), max(plotted_values)
    begin_at_zero = not (
        (low > 0 and high - low <= 0.5 * high) or (high < 0 and high - low <= 0.5 * abs(low))
    )

    if segments:
        detail = ''
        if x_kind == 'time' and total > 1:
            span = (points[-1][0] - points[0][0]).total_seconds() / segments
            detail = f' in {_duration_label(span)} segments' if span > 0 else ''
        sampling_note = (
            f'{len(plotted)} of {total} points shown; the highest and lowest '
            f'{datasets[0]["label"]} value{detail} are kept.'
        )
    else:
        sampling_note = f'All {total} points shown.'

    return {
        'labels': labels,
        'datasets': datasets,
        'x_axis_label': axis_label,
        'x_kind': x_kind,
        'source_points': total,
        'plotted_points': len(plotted),
        'downsampled': bool(segments),
        'sampling_note': sampling_note,
        'begin_at_zero': begin_at_zero,
    }


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
        "Set options that make the chart readable rather than leaving the reader to fix it: xAxisLabel and yAxisLabel whenever the axes are not self-explanatory, beginAtZero false only when the differences would otherwise be invisible, "
        "yScale 'logarithmic' when the values span orders of magnitude, yMin and yMax when a fixed range is what makes two charts comparable, xTickRotation and xTickLimit when the category names are long or numerous, and barWidth, lineWidth or pointRadius when the default weight obscures the data. "
        "Do not output matplotlib/Python, Vega, Mermaid, or other plotting code blocks as the visual chart response unless the user explicitly asks for source code instead of an inline chart. "
        "Mermaid is not a substitute for a data chart, but it is still the correct format for structural pictures: when the same answer also needs a process flow, architecture, sequence, state, or entity-relationship diagram, use a ```mermaid``` block for that diagram alongside the inline charts."
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
