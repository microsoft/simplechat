"""Helpers for rendering inline chart markdown blocks into export-friendly images."""

import base64
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
    try:
        parsed_payload = json.loads(payload_json)
    except (TypeError, ValueError):
        return '', None

    if not isinstance(parsed_payload, dict):
        return '', None

    try:
        png_bytes = _render_chart_spec_to_png_bytes(parsed_payload)
    except Exception:
        return '', parsed_payload

    encoded_payload = base64.b64encode(png_bytes).decode('ascii')
    return f'data:image/png;base64,{encoded_payload}', parsed_payload


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