# chart_plugin.py
"""Semantic Kernel plugin for inline Chart.js visualizations in chat."""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from semantic_kernel.functions import kernel_function
from semantic_kernel.functions.kernel_plugin import KernelPlugin

from functions_appinsights import log_event
from functions_chart_operations import (
    CHART_CAPABILITY_DEFINITIONS,
    CHART_PLUGIN_TYPE,
    build_inline_chart_markdown,
    get_enabled_chart_type_keys,
    normalize_chart_capabilities,
    normalize_chart_kind,
)
from semantic_kernel_plugins.base_plugin import BasePlugin
from semantic_kernel_plugins.plugin_invocation_logger import plugin_function_logger


DEFAULT_COLORS = [
    {'background': 'rgba(28, 110, 164, 0.18)', 'border': '#1c6ea4'},
    {'background': 'rgba(215, 91, 53, 0.18)', 'border': '#d75b35'},
    {'background': 'rgba(39, 123, 84, 0.18)', 'border': '#277b54'},
    {'background': 'rgba(153, 92, 32, 0.18)', 'border': '#995c20'},
    {'background': 'rgba(126, 77, 140, 0.18)', 'border': '#7e4d8c'},
    {'background': 'rgba(191, 66, 112, 0.18)', 'border': '#bf4270'},
    {'background': 'rgba(58, 141, 121, 0.18)', 'border': '#3a8d79'},
    {'background': 'rgba(101, 120, 48, 0.18)', 'border': '#657830'},
]

SAFE_COLOR_PREFIXES = ('#', 'rgb(', 'rgba(', 'hsl(', 'hsla(')
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


class ChartPlugin(BasePlugin):
    def __init__(self, manifest: Optional[Dict[str, Any]] = None):
        super().__init__(manifest)
        self.manifest = manifest or {}
        self._metadata = self.manifest.get('metadata', {})
        self._capabilities = normalize_chart_capabilities(
            self.manifest.get('chart_capabilities')
        )
        self._enabled_chart_types = get_enabled_chart_type_keys(self._capabilities)

    @property
    def display_name(self) -> str:
        return 'Interactive Charts'

    @property
    def metadata(self) -> Dict[str, Any]:
        enabled_chart_types = set(self._enabled_chart_types)
        return {
            'name': self.manifest.get('name', CHART_PLUGIN_TYPE),
            'type': CHART_PLUGIN_TYPE,
            'description': (
                'Generate validated inline Chart.js payloads for the chat experience. '
                'Supports line, bar, pie, doughnut, scatter, area, bubble, radar, '
                'stacked bar, and stacked line charts.'
            ),
            'methods': [
                {
                    'name': 'describe_available_chart_types',
                    'description': 'List the chart types currently enabled for this action.',
                    'parameters': [],
                    'returns': {'type': 'dict', 'description': 'Enabled chart types and examples.'},
                },
                {
                    'name': 'create_chart',
                    'description': 'Build a validated inline chart payload and markdown block.',
                    'parameters': [
                        {'name': 'chart_type', 'type': 'string', 'description': 'Requested chart type.', 'required': True},
                        {'name': 'chart_data_json', 'type': 'string', 'description': 'Chart data as JSON.', 'required': True},
                        {'name': 'title', 'type': 'string', 'description': 'Chart title.', 'required': False},
                        {'name': 'subtitle', 'type': 'string', 'description': 'Chart subtitle.', 'required': False},
                        {'name': 'description', 'type': 'string', 'description': 'Supporting chart description.', 'required': False},
                        {'name': 'x_axis_label', 'type': 'string', 'description': 'X axis label.', 'required': False},
                        {'name': 'y_axis_label', 'type': 'string', 'description': 'Y axis label.', 'required': False},
                        {'name': 'options_json', 'type': 'string', 'description': 'Optional chart display settings as JSON.', 'required': False},
                    ],
                    'returns': {'type': 'dict', 'description': 'Validated chart payload and inline markdown.'},
                },
            ],
            'enabled_chart_types': [
                definition['key']
                for definition in CHART_CAPABILITY_DEFINITIONS
                if definition['key'] in enabled_chart_types
            ],
        }

    def get_functions(self) -> List[str]:
        return ['describe_available_chart_types', 'create_chart']

    def get_kernel_plugin(self, plugin_name: str = CHART_PLUGIN_TYPE) -> KernelPlugin:
        functions = {}
        for function_name in self.get_functions():
            bound_method = getattr(self, function_name, None)
            if callable(bound_method) and hasattr(bound_method, '__kernel_function__'):
                functions[function_name] = bound_method

        return KernelPlugin.from_object(
            plugin_name,
            functions,
            description=self.metadata.get('description'),
        )

    @plugin_function_logger('ChartPlugin')
    @kernel_function(
        description='List the chart types currently enabled for this built-in chart action.'
    )
    def describe_available_chart_types(self) -> Dict[str, Any]:
        """Return the enabled chart types and expected payload shapes."""
        enabled_definitions = [
            definition
            for definition in CHART_CAPABILITY_DEFINITIONS
            if definition['key'] in set(self._enabled_chart_types)
        ]
        return {
            'success': True,
            'enabled_chart_types': enabled_definitions,
            'recommended_payload_shapes': {
                'label_series': {
                    'rows': [
                        {'month': 'Jan', 'revenue': 120, 'cost': 84},
                        {'month': 'Feb', 'revenue': 146, 'cost': 91},
                    ],
                    'xField': 'month',
                    'yFields': ['revenue', 'cost'],
                },
                'pivot_series': {
                    'rows': [
                        {'month': 'Jan', 'team': 'North', 'value': 120},
                        {'month': 'Jan', 'team': 'South', 'value': 98},
                        {'month': 'Feb', 'team': 'North', 'value': 136},
                    ],
                    'xField': 'month',
                    'seriesField': 'team',
                    'valueField': 'value',
                },
                'scatter': {
                    'rows': [
                        {'latency_ms': 120, 'tokens': 820, 'region': 'East US'},
                        {'latency_ms': 95, 'tokens': 640, 'region': 'West Europe'},
                    ],
                    'xField': 'latency_ms',
                    'yField': 'tokens',
                    'seriesField': 'region',
                },
                'bubble': {
                    'rows': [
                        {'impact': 12, 'confidence': 78, 'volume': 18, 'team': 'A'},
                        {'impact': 19, 'confidence': 61, 'volume': 10, 'team': 'B'},
                    ],
                    'xField': 'impact',
                    'yField': 'confidence',
                    'sizeField': 'volume',
                    'seriesField': 'team',
                },
                'explicit_datasets': {
                    'labels': ['Q1', 'Q2', 'Q3', 'Q4'],
                    'datasets': [
                        {
                            'label': 'Revenue',
                            'data': [120, 132, 141, 168],
                            'backgroundColor': '#1c6ea4',
                            'borderColor': '#1c6ea4',
                        },
                        {'label': 'Target', 'data': [110, 128, 139, 160], 'type': 'line'},
                    ],
                },
                'pie_with_slice_colors': {
                    'labels': ['Apples', 'Oranges', 'Pears'],
                    'datasets': [
                        {
                            'label': 'Share',
                            'data': [33, 33, 34],
                            'backgroundColor': ['red', 'orange', 'green'],
                            'borderColor': ['apple', 'oranges', 'pears'],
                        },
                    ],
                },
            },
        }

    @plugin_function_logger('ChartPlugin')
    @kernel_function(
        description='Build a validated inline chart payload for Chart.js and return markdown that can be embedded directly in the assistant response.'
    )
    def create_chart(
        self,
        chart_type: str,
        chart_data_json: str,
        title: str = '',
        subtitle: str = '',
        description: str = '',
        x_axis_label: str = '',
        y_axis_label: str = '',
        options_json: str = '',
    ) -> Dict[str, Any]:
        """Build a validated inline chart payload and markdown fence."""
        try:
            chart_kind = normalize_chart_kind(chart_type)
            if chart_kind not in set(self._enabled_chart_types):
                raise ValueError(
                    f"Chart type '{chart_type}' is not enabled for this action. "
                    f"Enabled types: {', '.join(self._enabled_chart_types)}"
                )

            chart_data = self._parse_json_argument(chart_data_json, 'chart_data_json')
            options = self._parse_json_argument(options_json, 'options_json', allow_empty=True)

            payload = self._build_chart_payload(
                chart_kind=chart_kind,
                chart_data=chart_data,
                options=options,
                title=title,
                subtitle=subtitle,
                description=description,
                x_axis_label=x_axis_label,
                y_axis_label=y_axis_label,
            )
            chart_markdown = build_inline_chart_markdown(payload)

            return {
                'success': True,
                'chart_type': chart_kind,
                'chart_payload': payload,
                'chart_markdown': chart_markdown,
                'summary': payload.get('summary', ''),
                'enabled_chart_types': self._enabled_chart_types,
            }
        except ValueError as exc:
            return {'success': False, 'error': str(exc), 'error_type': 'validation'}
        except Exception as exc:
            log_event(
                f"[ChartPlugin] create_chart failed: {exc}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return {
                'success': False,
                'error': 'Failed to build chart payload.',
                'error_type': 'unexpected',
                'details': str(exc),
            }

    def _parse_json_argument(
        self,
        raw_value: Any,
        field_name: str,
        allow_empty: bool = False,
    ) -> Dict[str, Any]:
        if raw_value in (None, ''):
            if allow_empty:
                return {}
            raise ValueError(f'{field_name} is required.')

        if isinstance(raw_value, dict):
            return raw_value

        if not isinstance(raw_value, str):
            raise ValueError(f'{field_name} must be a JSON object string.')

        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise ValueError(f'{field_name} must be valid JSON: {exc.msg}') from exc

        if not isinstance(parsed, dict):
            raise ValueError(f'{field_name} must deserialize into a JSON object.')

        return parsed

    def _sanitize_text(self, value: Any, max_length: int = 160) -> str:
        return str(value or '').strip()[:max_length]

    def _coerce_number(self, value: Any, field_name: str) -> Optional[float]:
        if value in (None, ''):
            return None
        if isinstance(value, bool):
            raise ValueError(f'{field_name} must be numeric.')
        if isinstance(value, (int, float)):
            return float(value)

        candidate = str(value).strip().replace(',', '')
        if not candidate:
            return None

        try:
            return float(candidate)
        except ValueError as exc:
            raise ValueError(f'{field_name} must be numeric.') from exc

    def _coerce_rows(self, chart_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = chart_data.get('rows')
        if not isinstance(rows, list) or not rows:
            raise ValueError('chart_data_json.rows must be a non-empty array of objects.')
        if len(rows) > 500:
            raise ValueError('chart_data_json.rows supports up to 500 rows per chart.')
        normalized_rows = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f'Row {index + 1} must be an object.')
            normalized_rows.append(row)
        return normalized_rows

    def _coerce_labels(self, labels: Any) -> List[str]:
        if not isinstance(labels, list) or not labels:
            raise ValueError('labels must be a non-empty array.')
        if len(labels) > 200:
            raise ValueError('labels supports up to 200 items per chart.')
        return [self._sanitize_text(label, 80) or f'Item {index + 1}' for index, label in enumerate(labels)]

    def _sanitize_color(self, value: Any) -> Optional[str]:
        candidate = str(value or '').strip()
        if not candidate:
            return None
        if len(candidate) > 40:
            return None
        named_color = NAMED_CHART_COLORS.get(candidate.lower())
        if named_color:
            return named_color
        if candidate.startswith(SAFE_COLOR_PREFIXES):
            return candidate
        return None

    def _get_palette(self, index: int) -> Dict[str, str]:
        return DEFAULT_COLORS[index % len(DEFAULT_COLORS)]

    def _get_chart_js_type(self, chart_kind: str) -> str:
        type_map = {
            'area': 'line',
            'stacked_bar': 'bar',
            'stacked_line': 'line',
            'polar_area': 'polarArea',
        }
        return type_map.get(chart_kind, chart_kind)

    def _sanitize_options(
        self,
        chart_kind: str,
        options: Dict[str, Any],
        x_axis_label: str,
        y_axis_label: str,
    ) -> Dict[str, Any]:
        normalized = {
            'legendPosition': self._sanitize_text(options.get('legendPosition') or 'top', 20) or 'top',
            'showLegend': bool(options.get('showLegend', True)),
            'showDataTable': bool(options.get('showDataTable', True)),
            'beginAtZero': bool(options.get('beginAtZero', True)),
            'horizontal': bool(options.get('horizontal', False)) if chart_kind in {'bar', 'stacked_bar'} else False,
            'fill': bool(options.get('fill', chart_kind == 'area')),
            'smooth': bool(options.get('smooth', chart_kind in {'line', 'area', 'stacked_line'})),
            'stacked': bool(options.get('stacked', chart_kind in {'stacked_bar', 'stacked_line'})),
            'cutout': self._sanitize_text(options.get('cutout') or '60%', 20) if chart_kind == 'doughnut' else '',
            'xAxisLabel': self._sanitize_text(x_axis_label or options.get('xAxisLabel'), 80),
            'yAxisLabel': self._sanitize_text(y_axis_label or options.get('yAxisLabel'), 80),
        }
        if normalized['legendPosition'] not in {'top', 'bottom', 'left', 'right'}:
            normalized['legendPosition'] = 'top'
        if chart_kind != 'doughnut':
            normalized.pop('cutout', None)
        return normalized

    def _build_chart_payload(
        self,
        chart_kind: str,
        chart_data: Dict[str, Any],
        options: Dict[str, Any],
        title: str,
        subtitle: str,
        description: str,
        x_axis_label: str,
        y_axis_label: str,
    ) -> Dict[str, Any]:
        if isinstance(chart_data.get('datasets'), list):
            data_payload = self._build_explicit_dataset_payload(chart_kind, chart_data)
        else:
            data_payload = self._build_rows_payload(chart_kind, chart_data)

        chart_options = self._sanitize_options(chart_kind, options, x_axis_label, y_axis_label)
        payload = {
            'version': 1,
            'kind': chart_kind,
            'chartType': self._get_chart_js_type(chart_kind),
            'title': self._sanitize_text(title),
            'subtitle': self._sanitize_text(subtitle),
            'description': self._sanitize_text(description, 240),
            'data': data_payload['data'],
            'table': data_payload.get('table'),
            'options': chart_options,
            'summary': data_payload.get('summary'),
        }

        chart_hash_source = json.dumps(
            {
                'kind': payload['kind'],
                'title': payload['title'],
                'subtitle': payload['subtitle'],
                'data': payload['data'],
                'options': payload['options'],
            },
            sort_keys=True,
            separators=(',', ':'),
        )
        payload['chartId'] = hashlib.sha256(chart_hash_source.encode('utf-8')).hexdigest()[:12]
        return payload

    def _build_explicit_dataset_payload(
        self,
        chart_kind: str,
        chart_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        datasets = chart_data.get('datasets')
        if not isinstance(datasets, list) or not datasets:
            raise ValueError('datasets must be a non-empty array.')
        if len(datasets) > 20:
            raise ValueError('datasets supports up to 20 series per chart.')

        labels = chart_data.get('labels')
        normalized_labels = self._coerce_labels(labels) if labels is not None else []
        normalized_datasets = []

        for index, dataset in enumerate(datasets):
            if not isinstance(dataset, dict):
                raise ValueError(f'Dataset {index + 1} must be an object.')
            normalized_datasets.append(
                self._normalize_dataset(
                    chart_kind=chart_kind,
                    dataset=dataset,
                    dataset_index=index,
                    labels=normalized_labels,
                )
            )

        if chart_kind not in {'scatter', 'bubble'} and not normalized_labels:
            max_points = max(len(dataset['data']) for dataset in normalized_datasets)
            normalized_labels = [f'Item {index + 1}' for index in range(max_points)]

        data = {'datasets': normalized_datasets}
        if normalized_labels:
            data['labels'] = normalized_labels

        summary = self._build_summary(chart_kind, normalized_datasets, normalized_labels)
        table = self._build_table(chart_kind, data)
        return {'data': data, 'summary': summary, 'table': table}

    def _normalize_dataset(
        self,
        chart_kind: str,
        dataset: Dict[str, Any],
        dataset_index: int,
        labels: List[str],
    ) -> Dict[str, Any]:
        raw_points = dataset.get('data')
        if not isinstance(raw_points, list) or not raw_points:
            raise ValueError(f"Dataset {dataset_index + 1} must include a non-empty 'data' array.")
        if len(raw_points) > 200:
            raise ValueError('Each dataset supports up to 200 points.')

        palette = self._get_palette(dataset_index)
        normalized = {
            'label': self._sanitize_text(dataset.get('label') or f'Series {dataset_index + 1}', 80),
            'borderColor': self._sanitize_color(dataset.get('borderColor')) or palette['border'],
            'backgroundColor': self._sanitize_color(dataset.get('backgroundColor')) or palette['background'],
            'borderWidth': 2,
        }

        if chart_kind in {'scatter', 'bubble'}:
            normalized['data'] = [
                self._normalize_xy_point(point, chart_kind, dataset_index)
                for point in raw_points
            ]
        else:
            normalized['data'] = [
                self._coerce_number(point, f'dataset {dataset_index + 1} value')
                for point in raw_points
            ]
            if labels and len(normalized['data']) != len(labels):
                raise ValueError(
                    f"Dataset '{normalized['label']}' must contain the same number of values as labels."
                )

        if chart_kind in {'line', 'area', 'stacked_line'}:
            normalized['fill'] = bool(dataset.get('fill', chart_kind == 'area'))
            normalized['tension'] = 0.35 if bool(dataset.get('smooth', chart_kind != 'stacked_line')) else 0.0
        if chart_kind == 'radar':
            normalized['fill'] = bool(dataset.get('fill', False))
        if chart_kind in {'bar', 'stacked_bar'}:
            normalized['borderSkipped'] = False

        dataset_type = str(dataset.get('type') or '').strip().lower()
        if dataset_type in {'line', 'bar'}:
            normalized['type'] = dataset_type

        if isinstance(dataset.get('backgroundColor'), list):
            normalized_colors = [
                self._sanitize_color(color) or self._get_palette(color_index)['background']
                for color_index, color in enumerate(dataset.get('backgroundColor'))
            ]
            normalized['backgroundColor'] = normalized_colors
            if isinstance(dataset.get('borderColor'), list):
                normalized['borderColor'] = [
                    self._sanitize_color(color) or self._get_palette(color_index)['border']
                    for color_index, color in enumerate(dataset.get('borderColor'))
                ]
        elif chart_kind in {'pie', 'doughnut', 'polar_area'}:
            normalized['backgroundColor'] = [
                self._get_palette(color_index)['background']
                for color_index, _ in enumerate(normalized['data'])
            ]
            normalized['borderColor'] = [
                self._get_palette(color_index)['border']
                for color_index, _ in enumerate(normalized['data'])
            ]

        return normalized

    def _normalize_xy_point(
        self,
        point: Any,
        chart_kind: str,
        dataset_index: int,
    ) -> Dict[str, Any]:
        if not isinstance(point, dict):
            raise ValueError(
                f'Points for {chart_kind} datasets must be objects with x and y values. '
                f'Dataset {dataset_index + 1} contains an invalid point.'
            )

        normalized_point = {
            'x': self._coerce_number(point.get('x'), 'x'),
            'y': self._coerce_number(point.get('y'), 'y'),
        }
        if normalized_point['x'] is None or normalized_point['y'] is None:
            raise ValueError('Scatter and bubble points require both x and y values.')

        if chart_kind == 'bubble':
            normalized_point['r'] = self._coerce_number(point.get('r'), 'r')
            if normalized_point['r'] is None:
                raise ValueError('Bubble chart points require an r (radius) value.')

        return normalized_point

    def _build_rows_payload(
        self,
        chart_kind: str,
        chart_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        rows = self._coerce_rows(chart_data)

        if chart_kind in {'pie', 'doughnut', 'polar_area'}:
            return self._build_rows_pie_payload(chart_kind, rows, chart_data)
        if chart_kind == 'scatter':
            return self._build_rows_scatter_payload(chart_kind, rows, chart_data)
        if chart_kind == 'bubble':
            return self._build_rows_bubble_payload(chart_kind, rows, chart_data)

        x_field = self._sanitize_text(chart_data.get('xField'), 80)
        if not x_field:
            raise ValueError('rows payloads for this chart type require xField.')

        series_field = self._sanitize_text(chart_data.get('seriesField'), 80)
        value_field = self._sanitize_text(chart_data.get('valueField'), 80)
        y_fields = chart_data.get('yFields') if isinstance(chart_data.get('yFields'), list) else None

        if series_field and y_fields:
            raise ValueError('Use either seriesField/valueField or yFields, not both.')

        if series_field:
            if not value_field:
                raise ValueError('seriesField payloads also require valueField.')
            return self._build_rows_pivot_payload(chart_kind, rows, x_field, series_field, value_field)

        value_fields = []
        if y_fields:
            value_fields = [self._sanitize_text(field, 80) for field in y_fields if self._sanitize_text(field, 80)]
        elif value_field:
            value_fields = [value_field]
        else:
            sample_row = rows[0]
            value_fields = [
                key for key, value in sample_row.items()
                if key != x_field and isinstance(value, (int, float, str))
            ]

        value_fields = value_fields[:12]
        if not value_fields:
            raise ValueError('Unable to determine value fields from rows payload.')

        labels = [self._sanitize_text(row.get(x_field), 80) or f'Item {index + 1}' for index, row in enumerate(rows)]
        datasets = []
        for dataset_index, field_name in enumerate(value_fields):
            palette = self._get_palette(dataset_index)
            values = [
                self._coerce_number(row.get(field_name), field_name)
                for row in rows
            ]
            dataset = {
                'label': field_name.replace('_', ' ').title(),
                'data': values,
                'borderColor': palette['border'],
                'backgroundColor': palette['background'],
                'borderWidth': 2,
            }
            if chart_kind in {'line', 'area', 'stacked_line'}:
                dataset['fill'] = chart_kind == 'area'
                dataset['tension'] = 0.35 if chart_kind != 'stacked_line' else 0.0
            if chart_kind == 'radar':
                dataset['fill'] = False
            if chart_kind in {'bar', 'stacked_bar'}:
                dataset['borderSkipped'] = False
            datasets.append(dataset)

        data = {'labels': labels, 'datasets': datasets}
        summary = self._build_summary(chart_kind, datasets, labels)
        table = self._build_table(chart_kind, data)
        return {'data': data, 'summary': summary, 'table': table}

    def _build_rows_pivot_payload(
        self,
        chart_kind: str,
        rows: List[Dict[str, Any]],
        x_field: str,
        series_field: str,
        value_field: str,
    ) -> Dict[str, Any]:
        labels = []
        series_names = []
        lookup = {}
        for row in rows:
            label = self._sanitize_text(row.get(x_field), 80)
            series_name = self._sanitize_text(row.get(series_field), 80)
            if not label or not series_name:
                raise ValueError('rows payload contains blank xField or seriesField values.')
            if label not in labels:
                labels.append(label)
            if series_name not in series_names:
                series_names.append(series_name)
            lookup[(label, series_name)] = self._coerce_number(row.get(value_field), value_field)

        datasets = []
        for dataset_index, series_name in enumerate(series_names[:12]):
            palette = self._get_palette(dataset_index)
            dataset = {
                'label': series_name,
                'data': [lookup.get((label, series_name)) for label in labels],
                'borderColor': palette['border'],
                'backgroundColor': palette['background'],
                'borderWidth': 2,
            }
            if chart_kind in {'line', 'area', 'stacked_line'}:
                dataset['fill'] = chart_kind == 'area'
                dataset['tension'] = 0.35 if chart_kind != 'stacked_line' else 0.0
            if chart_kind in {'bar', 'stacked_bar'}:
                dataset['borderSkipped'] = False
            datasets.append(dataset)

        data = {'labels': labels, 'datasets': datasets}
        summary = self._build_summary(chart_kind, datasets, labels)
        table = self._build_table(chart_kind, data)
        return {'data': data, 'summary': summary, 'table': table}

    def _build_rows_pie_payload(
        self,
        chart_kind: str,
        rows: List[Dict[str, Any]],
        chart_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        label_field = self._sanitize_text(chart_data.get('labelField') or chart_data.get('xField'), 80)
        value_field = self._sanitize_text(chart_data.get('valueField') or chart_data.get('yField'), 80)
        if not label_field or not value_field:
            raise ValueError('Pie and doughnut row payloads require labelField and valueField.')

        labels = [self._sanitize_text(row.get(label_field), 80) or f'Item {index + 1}' for index, row in enumerate(rows)]
        values = [self._coerce_number(row.get(value_field), value_field) for row in rows]
        dataset = {
            'label': value_field.replace('_', ' ').title(),
            'data': values,
            'backgroundColor': [self._get_palette(index)['background'] for index in range(len(values))],
            'borderColor': [self._get_palette(index)['border'] for index in range(len(values))],
            'borderWidth': 2,
        }
        data = {'labels': labels, 'datasets': [dataset]}
        summary = self._build_summary(chart_kind, [dataset], labels)
        table = self._build_table(chart_kind, data)
        return {'data': data, 'summary': summary, 'table': table}

    def _build_rows_scatter_payload(
        self,
        chart_kind: str,
        rows: List[Dict[str, Any]],
        chart_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        x_field = self._sanitize_text(chart_data.get('xField'), 80)
        y_field = self._sanitize_text(chart_data.get('yField'), 80)
        series_field = self._sanitize_text(chart_data.get('seriesField'), 80)
        if not x_field or not y_field:
            raise ValueError('Scatter row payloads require xField and yField.')

        datasets = []
        if series_field:
            grouped_rows = {}
            for row in rows:
                series_name = self._sanitize_text(row.get(series_field), 80) or 'Series 1'
                grouped_rows.setdefault(series_name, []).append(row)
            for dataset_index, (series_name, series_rows) in enumerate(grouped_rows.items()):
                palette = self._get_palette(dataset_index)
                datasets.append({
                    'label': series_name,
                    'data': [
                        {
                            'x': self._coerce_number(row.get(x_field), x_field),
                            'y': self._coerce_number(row.get(y_field), y_field),
                        }
                        for row in series_rows
                    ],
                    'borderColor': palette['border'],
                    'backgroundColor': palette['background'],
                    'borderWidth': 2,
                })
        else:
            palette = self._get_palette(0)
            datasets.append({
                'label': self._sanitize_text(chart_data.get('datasetLabel') or 'Series 1', 80),
                'data': [
                    {
                        'x': self._coerce_number(row.get(x_field), x_field),
                        'y': self._coerce_number(row.get(y_field), y_field),
                    }
                    for row in rows
                ],
                'borderColor': palette['border'],
                'backgroundColor': palette['background'],
                'borderWidth': 2,
            })

        data = {'datasets': datasets}
        summary = self._build_summary(chart_kind, datasets, [])
        table = self._build_table(chart_kind, data)
        return {'data': data, 'summary': summary, 'table': table}

    def _build_rows_bubble_payload(
        self,
        chart_kind: str,
        rows: List[Dict[str, Any]],
        chart_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        x_field = self._sanitize_text(chart_data.get('xField'), 80)
        y_field = self._sanitize_text(chart_data.get('yField'), 80)
        size_field = self._sanitize_text(chart_data.get('sizeField'), 80)
        series_field = self._sanitize_text(chart_data.get('seriesField'), 80)
        if not x_field or not y_field or not size_field:
            raise ValueError('Bubble row payloads require xField, yField, and sizeField.')

        datasets = []
        if series_field:
            grouped_rows = {}
            for row in rows:
                series_name = self._sanitize_text(row.get(series_field), 80) or 'Series 1'
                grouped_rows.setdefault(series_name, []).append(row)
            for dataset_index, (series_name, series_rows) in enumerate(grouped_rows.items()):
                palette = self._get_palette(dataset_index)
                datasets.append({
                    'label': series_name,
                    'data': [
                        {
                            'x': self._coerce_number(row.get(x_field), x_field),
                            'y': self._coerce_number(row.get(y_field), y_field),
                            'r': self._coerce_number(row.get(size_field), size_field),
                        }
                        for row in series_rows
                    ],
                    'borderColor': palette['border'],
                    'backgroundColor': palette['background'],
                    'borderWidth': 2,
                })
        else:
            palette = self._get_palette(0)
            datasets.append({
                'label': self._sanitize_text(chart_data.get('datasetLabel') or 'Series 1', 80),
                'data': [
                    {
                        'x': self._coerce_number(row.get(x_field), x_field),
                        'y': self._coerce_number(row.get(y_field), y_field),
                        'r': self._coerce_number(row.get(size_field), size_field),
                    }
                    for row in rows
                ],
                'borderColor': palette['border'],
                'backgroundColor': palette['background'],
                'borderWidth': 2,
            })

        data = {'datasets': datasets}
        summary = self._build_summary(chart_kind, datasets, [])
        table = self._build_table(chart_kind, data)
        return {'data': data, 'summary': summary, 'table': table}

    def _build_summary(
        self,
        chart_kind: str,
        datasets: List[Dict[str, Any]],
        labels: List[str],
    ) -> str:
        point_count = sum(len(dataset.get('data', [])) for dataset in datasets)
        series_count = len(datasets)
        label_count = len(labels)
        if chart_kind in {'scatter', 'bubble'}:
            return f'{chart_kind.replace("_", " ").title()} with {series_count} series and {point_count} plotted points.'
        if chart_kind in {'pie', 'doughnut', 'polar_area'}:
            return f'{chart_kind.replace("_", " ").title()} with {label_count or point_count} segments.'
        return (
            f'{chart_kind.replace("_", " ").title()} with {series_count} series '
            f'across {label_count or point_count} categories.'
        )

    def _build_table(self, chart_kind: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        datasets = data.get('datasets') or []
        if not datasets:
            return None

        if chart_kind in {'scatter', 'bubble'}:
            columns = ['Series', 'X', 'Y']
            if chart_kind == 'bubble':
                columns.append('Radius')
            rows = []
            for dataset in datasets:
                for point in dataset.get('data', []):
                    row = [dataset.get('label', 'Series'), point.get('x'), point.get('y')]
                    if chart_kind == 'bubble':
                        row.append(point.get('r'))
                    rows.append(row)
            return {'columns': columns, 'rows': rows[:500]}

        labels = data.get('labels') or []
        columns = ['Label'] + [dataset.get('label', 'Series') for dataset in datasets]
        rows = []
        for index, label in enumerate(labels):
            row = [label]
            for dataset in datasets:
                dataset_values = dataset.get('data') or []
                row.append(dataset_values[index] if index < len(dataset_values) else None)
            rows.append(row)
        return {'columns': columns, 'rows': rows[:500]}