// inlineChartSpec.ts
// Parses the ```simplechart payload the built-in chart action emits.
//
// The payload grammar, sanitisation limits and colour palette are taken from
// static/js/chat/chat-inline-charts.js so both interfaces draw the same chart from the same
// message. The colour-editing half of that module is deliberately not ported: it rewrites the
// stored message markdown, which is a separate feature from rendering.
//
// Nothing here trusts the payload. Every string is length-capped, every number is checked for
// finiteness, every colour is matched against a known form, and series and row counts are
// bounded, because the payload is model output.

/** Fence language the chart action writes, from functions_chart_operations.py. */
export const INLINE_CHART_LANGUAGE = 'simplechart';

const ALLOWED_KINDS = new Set([
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
]);

/** Series colours, matching chat-inline-charts.js so a chart looks the same in both clients. */
const DEFAULT_PALETTE = [
    { background: 'rgba(28, 110, 164, 0.18)', border: '#1c6ea4' },
    { background: 'rgba(215, 91, 53, 0.18)', border: '#d75b35' },
    { background: 'rgba(39, 123, 84, 0.18)', border: '#277b54' },
    { background: 'rgba(153, 92, 32, 0.18)', border: '#995c20' },
    { background: 'rgba(126, 77, 140, 0.18)', border: '#7e4d8c' },
    { background: 'rgba(191, 66, 112, 0.18)', border: '#bf4270' },
    { background: 'rgba(58, 141, 121, 0.18)', border: '#3a8d79' },
    { background: 'rgba(101, 120, 48, 0.18)', border: '#657830' },
];

const NAMED_CHART_COLORS: Record<string, string> = {
    apple: '#c2410c',
    apples: '#c2410c',
    red: '#dc2626',
    orange: '#ea580c',
    oranges: '#ea580c',
    pear: '#16a34a',
    pears: '#16a34a',
    green: '#16a34a',
    blue: '#2563eb',
    purple: '#7c3aed',
    yellow: '#ca8a04',
    gold: '#ca8a04',
    brown: '#92400e',
    gray: '#64748b',
    grey: '#64748b',
    black: '#111827',
    white: '#f8fafc',
};

export interface ChartPoint {
    x: number;
    y: number;
    r?: number;
}

export interface ChartDataset {
    label: string;
    borderColor: string | string[];
    backgroundColor: string | string[];
    borderWidth: number;
    data: (number | null)[] | ChartPoint[];
    fill?: boolean;
    tension?: number;
    type?: 'line' | 'bar';
}

export interface ChartTable {
    columns: string[];
    rows: unknown[][];
}

export interface ChartSpecOptions {
    legendPosition: 'top' | 'bottom' | 'left' | 'right';
    showLegend: boolean;
    showDataTable: boolean;
    beginAtZero: boolean;
    horizontal: boolean;
    fill: boolean;
    smooth: boolean;
    stacked: boolean;
    xAxisLabel: string;
    yAxisLabel: string;
    cutout: string;
}

export interface ChartSpec {
    version: number;
    chartId: string;
    kind: string;
    chartType: string;
    title: string;
    subtitle: string;
    description: string;
    summary: string;
    data: { labels: string[]; datasets: ChartDataset[] };
    options: ChartSpecOptions;
    table: ChartTable | null;
}

type LooseRecord = Record<string, unknown>;

function getPalette(index: number) {
    return DEFAULT_PALETTE[index % DEFAULT_PALETTE.length];
}

function sanitizeText(value: unknown, maxLength = 240): string {
    return String(value ?? '')
        .trim()
        .slice(0, maxLength);
}

function sanitizeNumber(value: unknown): number | null {
    if (value === null || value === undefined || value === '') {
        return null;
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
}

function sanitizeColor(value: unknown, fallback: string): string {
    if (typeof value !== 'string') {
        return fallback;
    }

    const trimmed = value.trim();
    if (!trimmed || trimmed.length > 40) {
        return fallback;
    }

    const named = NAMED_CHART_COLORS[trimmed.toLowerCase()];
    if (named) {
        return named;
    }

    // Only the CSS colour forms are accepted, so a payload cannot smuggle a url() or an
    // arbitrary token into a style the chart writes.
    if (/^(#|rgb\(|rgba\(|hsl\(|hsla\()/.test(trimmed)) {
        return trimmed;
    }

    return fallback;
}

function sanitizeColorList(
    value: unknown,
    targetLength: number,
    fallbackFor: (index: number) => string,
): string[] {
    if (!Array.isArray(value) || value.length === 0) {
        return [];
    }

    const colors = value
        .slice(0, targetLength)
        .map((item, index) => sanitizeColor(item, fallbackFor(index)));
    while (colors.length < targetLength) {
        colors.push(fallbackFor(colors.length));
    }
    return colors;
}

/** Map a SimpleChat chart kind onto the Chart.js type that draws it. */
export function getBaseChartType(kind: string): string {
    if (kind === 'area' || kind === 'stacked_line') {
        return 'line';
    }
    if (kind === 'stacked_bar') {
        return 'bar';
    }
    if (kind === 'polar_area') {
        return 'polarArea';
    }
    return kind;
}

function normalizeChartKindValue(value: unknown): string {
    const normalized = sanitizeText(value, 40).toLowerCase().replace(/[\s-]+/g, '_');
    if (!normalized || normalized === 'chart') {
        return '';
    }
    if (normalized === 'polararea') {
        return 'polar_area';
    }
    if (normalized === 'donut') {
        return 'doughnut';
    }
    return normalized;
}

/* -------------------------------------------------------------------------- */
/* Loose payload parsing                                                       */
/* -------------------------------------------------------------------------- */

function parseInlineArray(value: unknown): unknown[] | null {
    const trimmed = String(value ?? '').trim();
    if (!trimmed.startsWith('[') || !trimmed.endsWith(']')) {
        return null;
    }

    const inner = trimmed.slice(1, -1).trim();
    if (!inner) {
        return [];
    }
    return inner.split(',').map((item) => parseLooseScalarValue(item));
}

function parseLooseScalarValue(value: unknown): unknown {
    const trimmed = String(value ?? '').trim();
    if (!trimmed) {
        return '';
    }

    const asArray = parseInlineArray(trimmed);
    if (asArray) {
        return asArray;
    }

    if (
        (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
        (trimmed.startsWith("'") && trimmed.endsWith("'"))
    ) {
        return trimmed.slice(1, -1);
    }

    const lowered = trimmed.toLowerCase();
    if (lowered === 'true') {
        return true;
    }
    if (lowered === 'false') {
        return false;
    }
    if (lowered === 'null') {
        return null;
    }

    const numeric = Number(trimmed.replace(/,/g, ''));
    if (Number.isFinite(numeric) && /^-?[0-9][0-9,]*(\.[0-9]+)?$/.test(trimmed)) {
        return numeric;
    }

    return trimmed;
}

function parseLooseKeyValue(line: string): { key: string; value: string } | null {
    const separator = line.indexOf(':');
    if (separator < 0) {
        return null;
    }
    return { key: line.slice(0, separator).trim(), value: line.slice(separator + 1).trim() };
}

function assignLooseChartOption(
    options: LooseRecord,
    key: string,
    value: string,
    optionPath: string[],
) {
    const normalizedKey = String(key || '').trim();
    const parsed = parseLooseScalarValue(value);

    if (optionPath.includes('legend') && (normalizedKey === 'display' || normalizedKey === 'position')) {
        const plugins = (options.plugins as LooseRecord | undefined) ?? {};
        const legend = (plugins.legend as LooseRecord | undefined) ?? {};
        legend[normalizedKey] = parsed;
        plugins.legend = legend;
        options.plugins = plugins;
        return;
    }

    options[normalizedKey] = parsed;
}

/**
 * Parse the indented key/value form a model writes when it authors a fence by hand.
 *
 * The chart action always emits strict JSON, so this only matters for hand-written blocks —
 * but without it those render as a wall of raw text, which is the problem being solved.
 */
function parseLooseChartSpec(payloadText: string): LooseRecord {
    const data: LooseRecord = { datasets: [] as LooseRecord[] };
    const options: LooseRecord = {};
    const spec: LooseRecord = { data, options };

    let section = '';
    let currentDataset: LooseRecord | null = null;
    let optionPath: string[] = [];

    for (const rawLine of String(payloadText || '').replace(/\r/g, '').split('\n')) {
        const line = rawLine.replace(/\t/g, '    ');
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#')) {
            continue;
        }

        const indent = line.length - line.trimStart().length;
        const listItemText = trimmed.startsWith('- ') ? trimmed.slice(2).trim() : '';

        if (listItemText && section === 'data') {
            currentDataset = {};
            (data.datasets as LooseRecord[]).push(currentDataset);
            const listKeyValue = parseLooseKeyValue(listItemText);
            if (listKeyValue) {
                currentDataset[listKeyValue.key] = parseLooseScalarValue(listKeyValue.value);
            }
            continue;
        }

        const keyValue = parseLooseKeyValue(trimmed);
        if (!keyValue) {
            continue;
        }

        const { key, value } = keyValue;

        if (indent === 0) {
            optionPath = [];
            currentDataset = null;
            if (!value && (key === 'data' || key === 'options')) {
                section = key;
                continue;
            }
            section = '';
            spec[key] = parseLooseScalarValue(value);
            continue;
        }

        if (section === 'data') {
            if (key === 'datasets' && !value) {
                currentDataset = null;
                continue;
            }
            if (currentDataset) {
                currentDataset[key] = parseLooseScalarValue(value);
                continue;
            }
            data[key] = parseLooseScalarValue(value);
            continue;
        }

        if (section === 'options') {
            if (!value) {
                if (key === 'plugins') {
                    optionPath = ['plugins'];
                } else if (key === 'legend') {
                    optionPath = ['plugins', 'legend'];
                }
                continue;
            }
            assignLooseChartOption(options, key, value, optionPath);
        }
    }

    return spec;
}

/* -------------------------------------------------------------------------- */
/* Normalisation                                                               */
/* -------------------------------------------------------------------------- */

function normalizePoint(point: unknown, kind: string): ChartPoint | null {
    if (!point || typeof point !== 'object') {
        return null;
    }

    const source = point as LooseRecord;
    const x = sanitizeNumber(source.x);
    const y = sanitizeNumber(source.y);
    if (x === null || y === null) {
        return null;
    }

    if (kind === 'bubble') {
        const r = sanitizeNumber(source.r);
        if (r === null) {
            return null;
        }
        return { x, y, r };
    }

    return { x, y };
}

function normalizeDatasets(kind: string, rawDatasets: unknown, labels: string[]): ChartDataset[] {
    if (!Array.isArray(rawDatasets) || rawDatasets.length === 0) {
        return [];
    }

    return rawDatasets
        .slice(0, 20)
        .map((entry, index) => {
            const source = (entry ?? {}) as LooseRecord;
            const palette = getPalette(index);

            const dataset: ChartDataset = {
                label: sanitizeText(source.label || `Series ${index + 1}`, 80),
                borderColor: sanitizeColor(source.borderColor, palette.border),
                backgroundColor: sanitizeColor(source.backgroundColor, palette.background),
                borderWidth: 2,
                data: [],
            };

            if (kind === 'scatter' || kind === 'bubble') {
                dataset.data = Array.isArray(source.data)
                    ? (source.data
                          .map((point) => normalizePoint(point, kind))
                          .filter((point): point is ChartPoint => point !== null) as ChartPoint[])
                    : [];
            } else {
                dataset.data = Array.isArray(source.data)
                    ? source.data.slice(0, 200).map((value) => sanitizeNumber(value))
                    : [];
            }

            if (kind === 'line' || kind === 'area' || kind === 'stacked_line') {
                dataset.fill = source.fill === true || kind === 'area';
                dataset.tension = source.tension === 0 ? 0 : 0.35;
            }

            if (kind === 'radar') {
                dataset.fill = source.fill === true;
            }

            // Part-to-whole charts colour each slice rather than each series.
            if ((kind === 'pie' || kind === 'doughnut' || kind === 'polar_area') && labels.length) {
                const backgrounds = sanitizeColorList(
                    source.backgroundColor,
                    labels.length,
                    (index) => getPalette(index).background,
                );
                const borders = sanitizeColorList(
                    source.borderColor,
                    labels.length,
                    (index) => getPalette(index).border,
                );
                if (backgrounds.length) {
                    dataset.backgroundColor = backgrounds;
                }
                if (borders.length) {
                    dataset.borderColor = borders;
                }
            }

            if (source.type === 'line' || source.type === 'bar') {
                dataset.type = source.type;
            }

            return dataset;
        })
        .filter((dataset) => Array.isArray(dataset.data) && dataset.data.length > 0);
}

function normalizeTable(rawTable: unknown): ChartTable | null {
    if (!rawTable || typeof rawTable !== 'object' || Array.isArray(rawTable)) {
        return null;
    }

    const source = rawTable as LooseRecord;
    const columns = Array.isArray(source.columns)
        ? source.columns
              .slice(0, 12)
              .map((column) => sanitizeText(column, 80))
              .filter(Boolean)
        : [];
    const rows = Array.isArray(source.rows)
        ? source.rows
              .slice(0, 500)
              .map((row) => (Array.isArray(row) ? row.slice(0, columns.length || 12) : []))
              .filter((row) => row.length > 0)
        : [];

    if (!columns.length || !rows.length) {
        return null;
    }

    return { columns, rows };
}

function normalizeChartSpec(rawSpec: unknown): ChartSpec | null {
    if (!rawSpec || typeof rawSpec !== 'object' || Array.isArray(rawSpec)) {
        return null;
    }

    const source = rawSpec as LooseRecord;

    let kind = normalizeChartKindValue(source.kind);
    if (!ALLOWED_KINDS.has(kind)) {
        kind = normalizeChartKindValue(source.chartType);
    }
    if (!ALLOWED_KINDS.has(kind)) {
        return null;
    }

    const rawData = source.data;
    if (!rawData || typeof rawData !== 'object' || Array.isArray(rawData)) {
        return null;
    }

    const dataSource = rawData as LooseRecord;
    const labels = Array.isArray(dataSource.labels)
        ? dataSource.labels.slice(0, 200).map((label) => sanitizeText(label, 80))
        : [];
    const datasets = normalizeDatasets(kind, dataSource.datasets, labels);
    if (!datasets.length) {
        return null;
    }

    const rawOptions =
        source.options && typeof source.options === 'object' && !Array.isArray(source.options)
            ? (source.options as LooseRecord)
            : {};

    const rawPlugins =
        rawOptions.plugins && typeof rawOptions.plugins === 'object' && !Array.isArray(rawOptions.plugins)
            ? (rawOptions.plugins as LooseRecord)
            : {};
    const rawLegend =
        rawPlugins.legend && typeof rawPlugins.legend === 'object' && !Array.isArray(rawPlugins.legend)
            ? (rawPlugins.legend as LooseRecord)
            : {};

    const legendPosition = sanitizeText(
        rawOptions.legendPosition || rawLegend.position || 'top',
        10,
    ).toLowerCase();

    const options: ChartSpecOptions = {
        legendPosition: (['top', 'bottom', 'left', 'right'] as const).includes(
            legendPosition as 'top',
        )
            ? (legendPosition as ChartSpecOptions['legendPosition'])
            : 'top',
        showLegend: rawOptions.showLegend !== false && rawLegend.display !== false,
        showDataTable: rawOptions.showDataTable !== false,
        beginAtZero: rawOptions.beginAtZero !== false,
        horizontal: Boolean(rawOptions.horizontal) && (kind === 'bar' || kind === 'stacked_bar'),
        fill: Boolean(rawOptions.fill) || kind === 'area',
        smooth: rawOptions.smooth !== false,
        stacked: Boolean(rawOptions.stacked) || kind === 'stacked_bar' || kind === 'stacked_line',
        xAxisLabel: sanitizeText(rawOptions.xAxisLabel, 80),
        yAxisLabel: sanitizeText(rawOptions.yAxisLabel, 80),
        cutout: sanitizeText(rawOptions.cutout || '60%', 20),
    };

    return {
        version: Number(source.version) || 1,
        chartId: sanitizeText(source.chartId || '', 40),
        kind,
        chartType: getBaseChartType(kind),
        title: sanitizeText(source.title, 160),
        subtitle: sanitizeText(source.subtitle, 160),
        description: sanitizeText(source.description, 320),
        summary: sanitizeText(source.summary, 220),
        data: { labels, datasets },
        options,
        table: normalizeTable(source.table),
    };
}

/**
 * Turn the text inside a ```simplechart fence into a validated spec.
 *
 * Returns null when the payload is not a chart this client can draw, which the caller shows
 * as the original code block rather than an error.
 */
export function parseInlineChart(payloadText: string): ChartSpec | null {
    const payload = String(payloadText || '').trim();
    if (!payload) {
        return null;
    }

    let raw: unknown;
    try {
        raw = JSON.parse(payload);
    } catch {
        raw = parseLooseChartSpec(payload);
    }

    return normalizeChartSpec(raw);
}

/**
 * The data behind a chart, as a table.
 *
 * The chart action includes a `table` in its payload, but a hand-written fence has none, and
 * a chart without its numbers is much harder to check. For those, one is derived from the
 * labels and series so the disclosure is useful either way. Point-based charts are derived
 * from their x/y pairs instead of labels.
 */
export function resolveChartTable(spec: ChartSpec): ChartTable | null {
    if (spec.table) {
        return spec.table;
    }

    const { labels, datasets } = spec.data;
    if (datasets.length === 0) {
        return null;
    }

    if (spec.kind === 'scatter' || spec.kind === 'bubble') {
        const columns = ['Series', 'X', 'Y', ...(spec.kind === 'bubble' ? ['Size'] : [])];
        const rows: unknown[][] = [];
        for (const dataset of datasets) {
            for (const point of dataset.data as ChartPoint[]) {
                if (!point || typeof point !== 'object') {
                    continue;
                }
                rows.push(
                    spec.kind === 'bubble'
                        ? [dataset.label, point.x, point.y, point.r ?? '']
                        : [dataset.label, point.x, point.y],
                );
                if (rows.length >= 500) {
                    break;
                }
            }
        }
        return rows.length ? { columns, rows } : null;
    }

    if (labels.length === 0) {
        return null;
    }

    const columns = ['Label', ...datasets.map((dataset) => dataset.label)];
    const rows = labels.slice(0, 500).map((label, index) => [
        label,
        ...datasets.map((dataset) => (dataset.data as (number | null)[])[index] ?? ''),
    ]);

    return rows.length ? { columns, rows } : null;
}

/**
 * Build the Chart.js configuration for a spec.
 *
 * The chart's own title and subtitle plugins are left off: V2 renders those as text above the
 * canvas so they use the application's typography, stay selectable, and are readable by a
 * screen reader rather than being baked into the bitmap.
 */
export function buildChartConfig(
    spec: ChartSpec,
    theme: { text: string; grid: string },
): Record<string, unknown> {
    const baseType = getBaseChartType(spec.kind);

    const config: Record<string, unknown> = {
        type: baseType,
        data: {
            datasets: spec.data.datasets.map((dataset) => ({ ...dataset })),
            ...(spec.data.labels.length ? { labels: [...spec.data.labels] } : {}),
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            // Animation is disabled because a chart can be re-created while a reply is still
            // streaming, and replaying the entry animation on each pass is distracting.
            animation: false,
            interaction: { mode: 'nearest', intersect: false },
            color: theme.text,
            plugins: {
                legend: {
                    display: spec.options.showLegend,
                    position: spec.options.legendPosition,
                    labels: { color: theme.text },
                },
                title: { display: false },
                subtitle: { display: false },
            },
        },
    };

    const options = config.options as Record<string, unknown>;

    if (['bar', 'line', 'scatter', 'bubble'].includes(baseType)) {
        options.scales = {
            x: {
                stacked: spec.options.stacked,
                ticks: { color: theme.text },
                grid: { color: theme.grid },
                title: {
                    display: Boolean(spec.options.xAxisLabel),
                    text: spec.options.xAxisLabel,
                    color: theme.text,
                },
            },
            y: {
                stacked: spec.options.stacked,
                beginAtZero: spec.options.beginAtZero,
                ticks: { color: theme.text },
                grid: { color: theme.grid },
                title: {
                    display: Boolean(spec.options.yAxisLabel),
                    text: spec.options.yAxisLabel,
                    color: theme.text,
                },
            },
        };

        if (spec.options.horizontal && baseType === 'bar') {
            options.indexAxis = 'y';
        }
    }

    if (baseType === 'doughnut') {
        options.cutout = spec.options.cutout || '60%';
    }

    if (baseType === 'radar') {
        options.scales = {
            r: {
                beginAtZero: spec.options.beginAtZero,
                ticks: { color: theme.text, backdropColor: 'transparent' },
                grid: { color: theme.grid },
                angleLines: { color: theme.grid },
                pointLabels: { color: theme.text },
            },
        };
    }

    return config;
}
