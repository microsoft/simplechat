# functions_chart_export.py
"""Helpers for rendering inline chart markdown blocks into export-friendly images."""

import base64
import csv
import io
import json
import math
import re
from functools import lru_cache
from html import escape as escape_html
from typing import Any, Dict, List, Optional, Sequence, Tuple

from functions_chart_operations import INLINE_CHART_BLOCK_LANGUAGE


INLINE_CHART_EXPORT_REGEX = re.compile(
    rf"```{re.escape(INLINE_CHART_BLOCK_LANGUAGE)}\s*([\s\S]*?)```",
    re.IGNORECASE,
)
CSS_RGB_COLOR_REGEX = re.compile(
    r"rgba?\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)(?:\s*,\s*([0-9.]+))?\s*\)",
    re.IGNORECASE,
)
EXPORT_CHART_DPI = 144
EXPORT_CHART_SIZE_INCHES = (8.2, 4.8)
ALLOWED_CHART_KINDS = {
    'line',
    'bar',
    'pie',
    'doughnut',
    'scatter',
    'area',
    'bubble',
    'radar',
    'stacked_bar',
    'stacked_line',
    'polar_area',
}
CHART_KIND_ALIASES = {
    'lines': 'line',
    'bars': 'bar',
    'donut': 'doughnut',
    'polararea': 'polar_area',
    'polar area': 'polar_area',
    'stacked bar': 'stacked_bar',
    'stackedbar': 'stacked_bar',
    'stacked line': 'stacked_line',
    'stackedline': 'stacked_line',
}
DEFAULT_PALETTE = [
    {'background': 'rgba(28, 110, 164, 0.18)', 'border': '#1c6ea4'},
    {'background': 'rgba(215, 91, 53, 0.18)', 'border': '#d75b35'},
    {'background': 'rgba(39, 123, 84, 0.18)', 'border': '#277b54'},
    {'background': 'rgba(153, 92, 32, 0.18)', 'border': '#995c20'},
    {'background': 'rgba(126, 77, 140, 0.18)', 'border': '#7e4d8c'},
    {'background': 'rgba(191, 66, 112, 0.18)', 'border': '#bf4270'},
    {'background': 'rgba(58, 141, 121, 0.18)', 'border': '#3a8d79'},
    {'background': 'rgba(101, 120, 48, 0.18)', 'border': '#657830'},
]
NAMED_CHART_COLORS = {
    'apple': '#c2410c',
    'apples': '#c2410c',
    'red': '#dc2626',
    'orange': '#ea580c',
    'oranges': '#ea580c',
    'pear': '#16a34a',
    'pears': '#16a34a',
    'green': '#16a34a',
    'blue': '#2563eb',
    'purple': '#7c3aed',
    'yellow': '#ca8a04',
    'gold': '#ca8a04',
    'brown': '#92400e',
    'gray': '#64748b',
    'grey': '#64748b',
    'black': '#111827',
    'white': '#f8fafc',
}


def replace_inline_chart_blocks_with_export_html(content: str) -> str:
    """Replace simplechart fences with embeddable PNG-backed HTML blocks."""
    rendered_content = str(content or '')
    if not rendered_content or INLINE_CHART_EXPORT_REGEX.search(rendered_content) is None:
        return rendered_content

    def replace_match(match: re.Match[str]) -> str:
        export_html = _build_export_chart_html_from_payload(match.group(1) or '')
        return export_html or match.group(0)

    return INLINE_CHART_EXPORT_REGEX.sub(replace_match, rendered_content)


def decode_base64_image_data_uri(data_uri: str) -> Optional[bytes]:
    """Decode a base64 image data URI into bytes for DOCX embedding."""
    candidate = str(data_uri or '').strip()
    if not candidate.startswith('data:image/') or ';base64,' not in candidate:
        return None

    try:
        _, encoded_payload = candidate.split(',', 1)
        return base64.b64decode(encoded_payload)
    except (ValueError, TypeError, base64.binascii.Error):
        return None


def _build_export_chart_html_from_payload(payload_text: str) -> str:
    payload_json = str(payload_text or '').strip()
    if not payload_json:
        return ''

    image_data_uri, chart_spec = _render_chart_payload_to_data_uri(payload_json)
    if not image_data_uri or not isinstance(chart_spec, dict):
        return ''

    alt_text = _build_chart_alt_text(chart_spec)
    caption_text = _build_chart_caption_text(chart_spec)
    caption_html = ''
    if caption_text:
        caption_html = (
            '<p class="export-inline-chart-caption">'
            f'<em>{escape_html(caption_text)}</em>'
            '</p>'
        )

    return (
        '\n\n'
        '<div class="export-inline-chart">'
        f'<p><img src="{escape_html(image_data_uri)}" alt="{escape_html(alt_text)}" /></p>'
        f'{caption_html}'
        '</div>'
        '\n\n'
    )


@lru_cache(maxsize=128)
def _render_chart_payload_to_data_uri(payload_json: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    parsed_payload = _parse_chart_payload(payload_json)
    if not isinstance(parsed_payload, dict):
        return '', None

    chart_spec = _normalize_export_chart_spec(parsed_payload)
    if not chart_spec:
        return '', parsed_payload

    try:
        png_bytes = _render_chart_spec_to_png_bytes(chart_spec)
    except Exception:
        return '', chart_spec

    encoded_payload = base64.b64encode(png_bytes).decode('ascii')
    return f'data:image/png;base64,{encoded_payload}', chart_spec


def _parse_chart_payload(payload_text: str) -> Optional[Dict[str, Any]]:
    normalized_payload = str(payload_text or '').strip()
    if not normalized_payload:
        return None

    try:
        parsed_payload = json.loads(normalized_payload)
        return parsed_payload if isinstance(parsed_payload, dict) else None
    except (TypeError, ValueError):
        return _parse_loose_chart_spec(normalized_payload)


def _parse_loose_chart_spec(payload_text: str) -> Dict[str, Any]:
    spec: Dict[str, Any] = {'data': {'datasets': []}, 'options': {}}
    section = ''
    current_dataset: Optional[Dict[str, Any]] = None
    option_path: List[str] = []

    for raw_line in str(payload_text or '').replace('\r', '').split('\n'):
        normalized_line = raw_line.replace('\t', '    ')
        trimmed = normalized_line.strip()
        if not trimmed or trimmed.startswith('#'):
            continue

        indent = len(normalized_line) - len(normalized_line.lstrip(' '))
        list_item_text = trimmed[2:].strip() if trimmed.startswith('- ') else ''
        if list_item_text and section == 'data':
            current_dataset = {}
            spec['data']['datasets'].append(current_dataset)
            list_key_value = _parse_loose_key_value(list_item_text)
            if list_key_value:
                current_dataset[list_key_value[0]] = _parse_loose_scalar_value(list_key_value[1])
            continue

        key_value = _parse_loose_key_value(trimmed)
        if not key_value:
            continue

        key, value = key_value
        if indent == 0:
            option_path = []
            current_dataset = None
            if not value and key in {'data', 'options'}:
                section = key
                spec.setdefault(key, {} if key == 'options' else {'datasets': []})
                continue
            section = ''
            spec[key] = _parse_loose_scalar_value(value)
            continue

        if section == 'data':
            if key == 'datasets' and not value:
                current_dataset = None
                continue

            if current_dataset is not None:
                current_dataset[key] = _parse_loose_scalar_value(value)
                continue

            spec['data'][key] = _parse_loose_scalar_value(value)
            continue

        if section == 'options':
            if not value:
                if key == 'plugins':
                    option_path = ['plugins']
                elif key == 'legend':
                    option_path = ['plugins', 'legend']
                continue

            _assign_loose_chart_option(spec, key, value, option_path)

    return spec


def _parse_loose_key_value(line: str) -> Optional[Tuple[str, str]]:
    separator_index = str(line or '').find(':')
    if separator_index < 0:
        return None

    return line[:separator_index].strip(), line[separator_index + 1:].strip()


def _parse_loose_scalar_value(value: Any) -> Any:
    trimmed = str(value or '').strip()
    if not trimmed:
        return ''

    array_value = _parse_inline_array(trimmed)
    if array_value is not None:
        return array_value

    if (trimmed.startswith('"') and trimmed.endswith('"')) or (trimmed.startswith("'") and trimmed.endswith("'")):
        return trimmed[1:-1]

    lowered = trimmed.lower()
    if lowered == 'true':
        return True
    if lowered == 'false':
        return False
    if lowered == 'null':
        return None

    numeric_candidate = trimmed.replace(',', '')
    if re.fullmatch(r'-?[0-9][0-9,]*(\.[0-9]+)?', trimmed):
        numeric_value = float(numeric_candidate)
        return int(numeric_value) if numeric_value.is_integer() else numeric_value

    return trimmed


def _parse_inline_array(value: str) -> Optional[List[Any]]:
    trimmed = str(value or '').strip()
    if not trimmed.startswith('[') or not trimmed.endswith(']'):
        return None

    inner = trimmed[1:-1].strip()
    if not inner:
        return []

    try:
        row = next(csv.reader([inner], skipinitialspace=True))
    except (csv.Error, StopIteration):
        row = inner.split(',')

    return [_parse_loose_scalar_value(item) for item in row]


def _assign_loose_chart_option(spec: Dict[str, Any], key: str, value: Any, option_path: Sequence[str]):
    options = spec.setdefault('options', {})
    parsed_value = _parse_loose_scalar_value(value)
    if 'legend' in option_path and key in {'display', 'position'}:
        plugins = options.setdefault('plugins', {})
        legend = plugins.setdefault('legend', {})
        legend[key] = parsed_value
        return

    options[key] = parsed_value


def _normalize_export_chart_spec(raw_spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw_spec, dict):
        return None

    chart_kind = _normalize_chart_kind_value(raw_spec.get('kind'))
    if chart_kind not in ALLOWED_CHART_KINDS:
        chart_kind = _normalize_chart_kind_value(raw_spec.get('chartType'))
    if chart_kind not in ALLOWED_CHART_KINDS:
        return None

    raw_data = raw_spec.get('data') if isinstance(raw_spec.get('data'), dict) else {}
    labels = [
        _sanitize_text(label, 80)
        for label in raw_data.get('labels', [])[:200]
    ] if isinstance(raw_data.get('labels'), list) else []
    datasets = _normalize_export_datasets(chart_kind, raw_data.get('datasets'), labels)
    if not datasets:
        return None

    raw_options = raw_spec.get('options') if isinstance(raw_spec.get('options'), dict) else {}
    raw_plugins = raw_options.get('plugins') if isinstance(raw_options.get('plugins'), dict) else {}
    raw_legend_options = raw_plugins.get('legend') if isinstance(raw_plugins.get('legend'), dict) else {}
    legend_position = _sanitize_text(
        raw_options.get('legendPosition') or raw_legend_options.get('position') or 'top',
        10,
    ).lower()
    if legend_position not in {'top', 'bottom', 'left', 'right'}:
        legend_position = 'top'

    normalized_options = {
        'legendPosition': legend_position,
        'showLegend': raw_options.get('showLegend') is not False and raw_legend_options.get('display') is not False,
        'showDataTable': raw_options.get('showDataTable') is not False,
        'beginAtZero': raw_options.get('beginAtZero') is not False,
        'horizontal': bool(raw_options.get('horizontal')) and chart_kind in {'bar', 'stacked_bar'},
        'fill': bool(raw_options.get('fill')) or chart_kind == 'area',
        'smooth': raw_options.get('smooth') is not False,
        'stacked': bool(raw_options.get('stacked')) or chart_kind in {'stacked_bar', 'stacked_line'},
        'xAxisLabel': _sanitize_text(raw_options.get('xAxisLabel'), 80),
        'yAxisLabel': _sanitize_text(raw_options.get('yAxisLabel'), 80),
        'cutout': _sanitize_text(raw_options.get('cutout') or '60%', 20),
    }

    return {
        'version': _coerce_int(raw_spec.get('version'), 1),
        'chartId': _sanitize_text(raw_spec.get('chartId'), 40),
        'kind': chart_kind,
        'chartType': _get_base_chart_type(chart_kind),
        'title': _sanitize_text(raw_spec.get('title'), 160),
        'subtitle': _sanitize_text(raw_spec.get('subtitle'), 160),
        'description': _sanitize_text(raw_spec.get('description'), 320),
        'summary': _sanitize_text(raw_spec.get('summary'), 220),
        'data': {
            'labels': labels,
            'datasets': datasets,
        },
        'options': normalized_options,
        'table': _normalize_export_table(raw_spec.get('table')),
    }


def _normalize_export_datasets(chart_kind: str, raw_datasets: Any, labels: Sequence[str]) -> List[Dict[str, Any]]:
    if not isinstance(raw_datasets, list):
        return []

    normalized_datasets: List[Dict[str, Any]] = []
    for dataset_index, raw_dataset in enumerate(raw_datasets[:20]):
        if not isinstance(raw_dataset, dict):
            continue

        palette = DEFAULT_PALETTE[dataset_index % len(DEFAULT_PALETTE)]
        normalized_dataset: Dict[str, Any] = {
            'label': _sanitize_text(raw_dataset.get('label') or f'Series {dataset_index + 1}', 80),
            'borderColor': _sanitize_color(raw_dataset.get('borderColor'), palette['border']),
            'backgroundColor': _sanitize_color(raw_dataset.get('backgroundColor'), palette['background']),
            'borderWidth': 2,
        }

        raw_data = raw_dataset.get('data') if isinstance(raw_dataset.get('data'), list) else []
        if chart_kind in {'scatter', 'bubble'}:
            normalized_dataset['data'] = [
                normalized_point
                for point in raw_data[:200]
                if (normalized_point := _normalize_export_point(point, chart_kind)) is not None
            ]
        else:
            normalized_dataset['data'] = raw_data[:200]

        if chart_kind in {'line', 'area', 'stacked_line'}:
            normalized_dataset['fill'] = raw_dataset.get('fill') is True or chart_kind == 'area'
            normalized_dataset['tension'] = 0 if raw_dataset.get('tension') == 0 else 0.35

        if chart_kind == 'radar':
            normalized_dataset['fill'] = raw_dataset.get('fill') is True

        if chart_kind in {'pie', 'doughnut', 'polar_area'} and labels:
            normalized_dataset['backgroundColor'] = _sanitize_color_list(
                raw_dataset.get('backgroundColor'),
                len(labels),
                lambda color_index: DEFAULT_PALETTE[color_index % len(DEFAULT_PALETTE)]['background'],
            )
            normalized_dataset['borderColor'] = _sanitize_color_list(
                raw_dataset.get('borderColor'),
                len(labels),
                lambda color_index: DEFAULT_PALETTE[color_index % len(DEFAULT_PALETTE)]['border'],
            )

        if raw_dataset.get('type') in {'line', 'bar'}:
            normalized_dataset['type'] = raw_dataset.get('type')

        if normalized_dataset['data']:
            normalized_datasets.append(normalized_dataset)

    return normalized_datasets


def _normalize_export_point(point: Any, chart_kind: str) -> Optional[Dict[str, float]]:
    if not isinstance(point, dict):
        return None

    x_value = _coerce_float(point.get('x'))
    y_value = _coerce_float(point.get('y'))
    if x_value is None or y_value is None:
        return None

    normalized_point = {'x': x_value, 'y': y_value}
    if chart_kind == 'bubble':
        radius = _coerce_float(point.get('r'))
        if radius is None:
            return None
        normalized_point['r'] = radius

    return normalized_point


def _normalize_export_table(raw_table: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw_table, dict):
        return None

    columns = [
        _sanitize_text(column, 80)
        for column in raw_table.get('columns', [])[:12]
    ] if isinstance(raw_table.get('columns'), list) else []
    rows = [
        row[:len(columns) or 12]
        for row in raw_table.get('rows', [])[:500]
        if isinstance(row, list) and row
    ] if isinstance(raw_table.get('rows'), list) else []
    if not columns or not rows:
        return None
    return {'columns': columns, 'rows': rows}


def _normalize_chart_kind_value(value: Any) -> str:
    normalized_value = _sanitize_text(value, 40).lower().replace('-', '_')
    normalized_value = re.sub(r'\s+', '_', normalized_value)
    if normalized_value in {'', 'chart'}:
        return ''
    return CHART_KIND_ALIASES.get(normalized_value, normalized_value)


def _get_base_chart_type(chart_kind: str) -> str:
    if chart_kind in {'area', 'stacked_line'}:
        return 'line'
    if chart_kind == 'stacked_bar':
        return 'bar'
    if chart_kind == 'polar_area':
        return 'polarArea'
    return chart_kind


def _sanitize_text(value: Any, max_length: int) -> str:
    return str(value or '').strip()[:max_length]


def _sanitize_color(value: Any, fallback: str) -> Any:
    if isinstance(value, list):
        return [_sanitize_color(item, fallback) for item in value]
    if not isinstance(value, str):
        return fallback

    trimmed = value.strip()
    if not trimmed or len(trimmed) > 40:
        return fallback
    named_color = NAMED_CHART_COLORS.get(trimmed.lower())
    if named_color:
        return named_color
    if trimmed.startswith(('#', 'rgb(', 'rgba(', 'hsl(', 'hsla(')):
        return trimmed
    return fallback


def _sanitize_color_list(value: Any, target_length: int, fallback_resolver) -> List[Any]:
    if not isinstance(value, list) or not value:
        return [fallback_resolver(index) for index in range(target_length)]

    colors = [
        _sanitize_color(item, fallback_resolver(index))
        for index, item in enumerate(value[:target_length])
    ]
    while len(colors) < target_length:
        colors.append(fallback_resolver(len(colors)))
    return colors


def _coerce_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _build_chart_alt_text(chart_spec: Dict[str, Any]) -> str:
    for field_name in ('title', 'subtitle', 'summary', 'description'):
        value = str(chart_spec.get(field_name) or '').strip()
        if value:
            return value[:240]

    kind = str(chart_spec.get('kind') or chart_spec.get('chartType') or 'chart').strip()
    return f'{kind.title()} chart'


def _build_chart_caption_text(chart_spec: Dict[str, Any]) -> str:
    caption_parts: List[str] = []
    title = str(chart_spec.get('title') or '').strip()
    subtitle = str(chart_spec.get('subtitle') or '').strip()
    summary = str(chart_spec.get('summary') or '').strip()
    description = str(chart_spec.get('description') or '').strip()

    if title:
        caption_parts.append(title)
    if subtitle:
        caption_parts.append(subtitle)
    if summary and summary not in caption_parts:
        caption_parts.append(summary)
    elif description and description not in caption_parts:
        caption_parts.append(description)

    if not caption_parts:
        return ''
    return ' - '.join(caption_parts[:3])


def _render_chart_spec_to_png_bytes(chart_spec: Dict[str, Any]) -> bytes:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    chart_kind = str(chart_spec.get('kind') or chart_spec.get('chartType') or 'bar').strip().lower()
    if not chart_kind:
        raise ValueError('Chart specification is missing kind.')

    figure = Figure(figsize=EXPORT_CHART_SIZE_INCHES, dpi=EXPORT_CHART_DPI, facecolor='white')
    if chart_kind in {'radar', 'polar_area'}:
        axis = figure.add_subplot(111, projection='polar')
    else:
        axis = figure.add_subplot(111)

    options = chart_spec.get('options') if isinstance(chart_spec.get('options'), dict) else {}
    datasets = chart_spec.get('data', {}).get('datasets') if isinstance(chart_spec.get('data'), dict) else []
    labels = chart_spec.get('data', {}).get('labels') if isinstance(chart_spec.get('data'), dict) else []

    datasets = datasets if isinstance(datasets, list) else []
    labels = labels if isinstance(labels, list) else []

    if chart_kind in {'pie', 'doughnut'}:
        _render_pie_like_chart(axis, chart_spec, chart_kind)
    elif chart_kind == 'polar_area':
        _render_polar_area_chart(axis, chart_spec)
    elif chart_kind == 'radar':
        _render_radar_chart(axis, chart_spec)
    elif chart_kind in {'scatter', 'bubble'}:
        _render_scatter_like_chart(axis, chart_spec, chart_kind)
    else:
        _render_cartesian_chart(axis, chart_spec, chart_kind)

    if chart_kind not in {'pie', 'doughnut'}:
        axis.grid(True, alpha=0.25)
    _apply_chart_titles(figure, axis, chart_spec)
    _apply_axis_labels(axis, options, chart_kind)
    _apply_legend(axis, options, datasets, chart_kind, labels)

    if chart_kind not in {'pie', 'doughnut', 'polar_area'} and bool(options.get('beginAtZero', True)):
        try:
            _, current_upper = axis.get_ylim()
            lower_bound = 0 if current_upper >= 0 else current_upper
            axis.set_ylim(bottom=lower_bound)
        except Exception:
            pass

    figure.tight_layout(rect=(0, 0, 1, 0.94))
    canvas = FigureCanvasAgg(figure)
    buffer = io.BytesIO()
    canvas.print_png(buffer)
    buffer.seek(0)
    return buffer.read()


def _render_cartesian_chart(axis, chart_spec: Dict[str, Any], chart_kind: str):
    chart_data = chart_spec.get('data') if isinstance(chart_spec.get('data'), dict) else {}
    datasets = chart_data.get('datasets') if isinstance(chart_data.get('datasets'), list) else []
    labels = chart_data.get('labels') if isinstance(chart_data.get('labels'), list) else []
    options = chart_spec.get('options') if isinstance(chart_spec.get('options'), dict) else {}

    if not datasets:
        raise ValueError('Chart specification does not contain datasets.')

    max_points = max(len(dataset.get('data') or []) for dataset in datasets)
    if not labels:
        labels = [f'Item {index + 1}' for index in range(max_points)]

    x_positions = list(range(len(labels)))
    is_horizontal = bool(options.get('horizontal', False)) and chart_kind in {'bar', 'stacked_bar'}
    is_stacked = bool(options.get('stacked', False)) or chart_kind in {'stacked_bar', 'stacked_line'}

    if chart_kind == 'stacked_line':
        cumulative_values = [0.0] * len(labels)
        stackplot_values = []
        fill_colors = []
        legend_labels = []

        for dataset in datasets:
            series_values = _coerce_series(dataset.get('data'), len(labels), fill_none_with_zero=True)
            stackplot_values.append(series_values)
            fill_colors.append(_resolve_chart_color(dataset.get('backgroundColor'), 'rgba(28, 110, 164, 0.18)'))
            legend_labels.append(str(dataset.get('label') or 'Series').strip() or 'Series')

        axis.stackplot(x_positions, *stackplot_values, colors=fill_colors, alpha=0.55)

        for dataset_index, dataset in enumerate(datasets):
            series_values = stackplot_values[dataset_index]
            cumulative_values = [
                current_total + current_value
                for current_total, current_value in zip(cumulative_values, series_values)
            ]
            axis.plot(
                x_positions,
                cumulative_values,
                label=legend_labels[dataset_index],
                color=_resolve_chart_color(dataset.get('borderColor'), '#1c6ea4'),
                linewidth=2,
                marker='o',
                markersize=3,
            )
    else:
        stack_offsets = [0.0] * len(labels)
        for dataset_index, dataset in enumerate(datasets):
            dataset_type = str(dataset.get('type') or '').strip().lower()
            if chart_kind in {'bar', 'stacked_bar'} and dataset_type not in {'line', 'bar'}:
                dataset_type = 'bar'
            elif chart_kind in {'line', 'area'} and dataset_type not in {'line', 'bar'}:
                dataset_type = 'line'
            elif dataset_type not in {'line', 'bar'}:
                dataset_type = 'line'

            border_color = _resolve_chart_color(dataset.get('borderColor'), '#1c6ea4')
            background_color = _resolve_chart_color(dataset.get('backgroundColor'), 'rgba(28, 110, 164, 0.18)')
            label = str(dataset.get('label') or f'Series {dataset_index + 1}').strip() or f'Series {dataset_index + 1}'

            if dataset_type == 'bar':
                values = _coerce_series(dataset.get('data'), len(labels), fill_none_with_zero=True)
                if is_horizontal:
                    axis.barh(
                        x_positions,
                        values,
                        left=stack_offsets if is_stacked else None,
                        label=label,
                        color=background_color,
                        edgecolor=border_color,
                        linewidth=1.0,
                    )
                else:
                    axis.bar(
                        x_positions,
                        values,
                        bottom=stack_offsets if is_stacked else None,
                        label=label,
                        color=background_color,
                        edgecolor=border_color,
                        linewidth=1.0,
                    )
                if is_stacked:
                    stack_offsets = [current_total + current_value for current_total, current_value in zip(stack_offsets, values)]
            else:
                values = _coerce_series(dataset.get('data'), len(labels), fill_none_with_zero=False)
                axis.plot(
                    x_positions,
                    values,
                    label=label,
                    color=border_color,
                    linewidth=2,
                    marker='o',
                    markersize=3,
                )
                if chart_kind == 'area' or bool(dataset.get('fill')):
                    fill_values = [0.0 if _is_nan(value) else value for value in values]
                    axis.fill_between(x_positions, fill_values, color=background_color, alpha=0.35)

    should_rotate_labels = _should_rotate_axis_labels(labels)
    if is_horizontal:
        axis.set_yticks(x_positions)
        axis.set_yticklabels([str(label) for label in labels])
    else:
        axis.set_xticks(x_positions)
        axis.set_xticklabels(
            [str(label) for label in labels],
            rotation=30 if should_rotate_labels else 0,
            ha='right' if should_rotate_labels else 'center',
        )


def _render_pie_like_chart(axis, chart_spec: Dict[str, Any], chart_kind: str):
    from matplotlib.patches import Circle

    chart_data = chart_spec.get('data') if isinstance(chart_spec.get('data'), dict) else {}
    datasets = chart_data.get('datasets') if isinstance(chart_data.get('datasets'), list) else []
    labels = chart_data.get('labels') if isinstance(chart_data.get('labels'), list) else []
    if not datasets:
        raise ValueError('Chart specification does not contain datasets.')

    dataset = datasets[0]
    values = [max(0.0, value) for value in _coerce_series(dataset.get('data'), len(labels), fill_none_with_zero=True)]
    if sum(values) <= 0:
        values = [1.0 for _ in values] or [1.0]

    colors = _resolve_color_list(dataset.get('backgroundColor'), len(values), default_color='rgba(28, 110, 164, 0.18)')
    axis.pie(
        values,
        labels=[str(label) for label in labels] if labels else None,
        colors=colors,
        startangle=90,
        autopct='%1.1f%%' if sum(values) > 0 else None,
        wedgeprops={'linewidth': 1.0, 'edgecolor': '#ffffff'},
    )
    axis.axis('equal')

    if chart_kind == 'doughnut':
        center_circle = Circle((0, 0), 0.6, fc='white')
        axis.add_artist(center_circle)


def _render_polar_area_chart(axis, chart_spec: Dict[str, Any]):
    chart_data = chart_spec.get('data') if isinstance(chart_spec.get('data'), dict) else {}
    datasets = chart_data.get('datasets') if isinstance(chart_data.get('datasets'), list) else []
    labels = chart_data.get('labels') if isinstance(chart_data.get('labels'), list) else []
    if not datasets:
        raise ValueError('Chart specification does not contain datasets.')

    dataset = datasets[0]
    values = [max(0.0, value) for value in _coerce_series(dataset.get('data'), len(labels), fill_none_with_zero=True)]
    if not values:
        raise ValueError('Polar area chart does not contain values.')

    bar_count = len(values)
    theta_positions = [2 * math.pi * index / bar_count for index in range(bar_count)]
    widths = [(2 * math.pi) / bar_count for _ in range(bar_count)]
    colors = _resolve_color_list(dataset.get('backgroundColor'), bar_count, default_color='rgba(28, 110, 164, 0.18)')
    edge_colors = _resolve_color_list(dataset.get('borderColor'), bar_count, default_color='#1c6ea4')

    axis.bar(theta_positions, values, width=widths, color=colors, edgecolor=edge_colors, linewidth=1.0, alpha=0.85)
    axis.set_xticks(theta_positions)
    axis.set_xticklabels([str(label) for label in labels] if labels else [f'Item {index + 1}' for index in range(bar_count)])


def _render_radar_chart(axis, chart_spec: Dict[str, Any]):
    chart_data = chart_spec.get('data') if isinstance(chart_spec.get('data'), dict) else {}
    datasets = chart_data.get('datasets') if isinstance(chart_data.get('datasets'), list) else []
    labels = chart_data.get('labels') if isinstance(chart_data.get('labels'), list) else []
    if not datasets:
        raise ValueError('Chart specification does not contain datasets.')

    label_count = len(labels) or max(len(dataset.get('data') or []) for dataset in datasets)
    if label_count == 0:
        raise ValueError('Radar chart does not contain labels or values.')

    if not labels:
        labels = [f'Item {index + 1}' for index in range(label_count)]

    angles = [2 * math.pi * index / label_count for index in range(label_count)]
    angles.append(angles[0])

    for dataset_index, dataset in enumerate(datasets):
        values = _coerce_series(dataset.get('data'), label_count, fill_none_with_zero=True)
        values.append(values[0])
        border_color = _resolve_chart_color(dataset.get('borderColor'), '#1c6ea4')
        background_color = _resolve_chart_color(dataset.get('backgroundColor'), 'rgba(28, 110, 164, 0.18)')
        label = str(dataset.get('label') or f'Series {dataset_index + 1}').strip() or f'Series {dataset_index + 1}'

        axis.plot(angles, values, color=border_color, linewidth=2, label=label)
        axis.fill(angles, values, color=background_color, alpha=0.25)

    axis.set_xticks(angles[:-1])
    axis.set_xticklabels([str(label) for label in labels])


def _render_scatter_like_chart(axis, chart_spec: Dict[str, Any], chart_kind: str):
    chart_data = chart_spec.get('data') if isinstance(chart_spec.get('data'), dict) else {}
    datasets = chart_data.get('datasets') if isinstance(chart_data.get('datasets'), list) else []
    if not datasets:
        raise ValueError('Chart specification does not contain datasets.')

    for dataset_index, dataset in enumerate(datasets):
        points = dataset.get('data') if isinstance(dataset.get('data'), list) else []
        x_values = []
        y_values = []
        point_sizes = []
        for point in points:
            if not isinstance(point, dict):
                continue
            x_value = _coerce_float(point.get('x'))
            y_value = _coerce_float(point.get('y'))
            if x_value is None or y_value is None:
                continue
            x_values.append(x_value)
            y_values.append(y_value)
            radius = _coerce_float(point.get('r')) if chart_kind == 'bubble' else None
            point_sizes.append(max(24.0, (radius or 6.0) * 18.0))

        if not x_values:
            continue

        border_color = _resolve_chart_color(dataset.get('borderColor'), '#1c6ea4')
        background_color = _resolve_chart_color(dataset.get('backgroundColor'), 'rgba(28, 110, 164, 0.18)')
        label = str(dataset.get('label') or f'Series {dataset_index + 1}').strip() or f'Series {dataset_index + 1}'
        axis.scatter(
            x_values,
            y_values,
            s=point_sizes,
            label=label,
            color=background_color,
            edgecolors=border_color,
            linewidths=1.0,
            alpha=0.85,
        )


def _apply_chart_titles(figure, axis, chart_spec: Dict[str, Any]):
    title = str(chart_spec.get('title') or '').strip()
    subtitle = str(chart_spec.get('subtitle') or '').strip()
    if title:
        figure.suptitle(title, fontsize=14, y=0.98)
    if subtitle:
        axis.set_title(subtitle, fontsize=10, loc='left', pad=12)


def _apply_axis_labels(axis, options: Dict[str, Any], chart_kind: str):
    if chart_kind in {'pie', 'doughnut', 'radar', 'polar_area'}:
        return

    x_axis_label = str(options.get('xAxisLabel') or '').strip()
    y_axis_label = str(options.get('yAxisLabel') or '').strip()
    horizontal = bool(options.get('horizontal', False)) and chart_kind in {'bar', 'stacked_bar'}

    if horizontal:
        if y_axis_label:
            axis.set_xlabel(y_axis_label)
        if x_axis_label:
            axis.set_ylabel(x_axis_label)
        return

    if x_axis_label:
        axis.set_xlabel(x_axis_label)
    if y_axis_label:
        axis.set_ylabel(y_axis_label)


def _apply_legend(axis, options: Dict[str, Any], datasets: Sequence[Dict[str, Any]], chart_kind: str, labels: Sequence[Any]):
    if not bool(options.get('showLegend', True)):
        return
    if chart_kind in {'pie', 'doughnut'} and len(labels) <= 1:
        return
    if len(datasets) <= 1 and chart_kind not in {'pie', 'doughnut', 'polar_area'}:
        return

    legend_position = str(options.get('legendPosition') or 'top').strip().lower()
    legend_locations = {
        'top': 'upper center',
        'bottom': 'lower center',
        'left': 'center left',
        'right': 'center right',
    }
    axis.legend(loc=legend_locations.get(legend_position, 'upper center'), frameon=False)


def _resolve_chart_color(value: Any, default_color: str):
    candidate = value[0] if isinstance(value, list) and value else value
    if not isinstance(candidate, str):
        candidate = default_color

    parsed_color = _parse_css_rgb_color(candidate)
    if parsed_color is not None:
        return parsed_color

    return str(candidate or default_color).strip() or default_color


def _resolve_color_list(value: Any, count: int, default_color: str) -> List[Any]:
    if isinstance(value, list) and value:
        colors = [_resolve_chart_color(item, default_color) for item in value[:count]]
        while len(colors) < count:
            colors.append(_resolve_chart_color(default_color, default_color))
        return colors

    return [_resolve_chart_color(value, default_color) for _ in range(count)]


def _parse_css_rgb_color(color_value: str) -> Optional[Tuple[float, float, float, float]]:
    match = CSS_RGB_COLOR_REGEX.fullmatch(str(color_value or '').strip())
    if not match:
        return None

    red = max(0.0, min(255.0, float(match.group(1)))) / 255.0
    green = max(0.0, min(255.0, float(match.group(2)))) / 255.0
    blue = max(0.0, min(255.0, float(match.group(3)))) / 255.0
    alpha = match.group(4)
    alpha_value = max(0.0, min(1.0, float(alpha))) if alpha is not None else 1.0
    return (red, green, blue, alpha_value)


def _coerce_series(values: Any, target_length: int, fill_none_with_zero: bool) -> List[float]:
    series = list(values) if isinstance(values, list) else []
    coerced_values: List[float] = []
    for index in range(target_length):
        value = _coerce_float(series[index] if index < len(series) else None)
        if value is None:
            coerced_values.append(0.0 if fill_none_with_zero else float('nan'))
        else:
            coerced_values.append(value)
    return coerced_values


def _coerce_float(value: Any) -> Optional[float]:
    if value in (None, ''):
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)

    try:
        candidate = str(value).strip().replace(',', '')
        if not candidate:
            return None
        numeric_value = float(candidate)
        return None if math.isnan(numeric_value) else numeric_value
    except (TypeError, ValueError):
        return None


def _should_rotate_axis_labels(labels: Sequence[Any]) -> bool:
    return any(len(str(label or '')) > 12 for label in labels)


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)