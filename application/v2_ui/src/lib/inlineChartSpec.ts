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
//
// Colours the reader chose are applied on top at configuration time rather than being written
// back into the parsed spec, so the payload the model produced stays the payload the model
// produced and a style can be removed by simply not applying it.

import {
    hexToRgba,
    isDefaultVisualStyle,
    mixHex,
    readableTextColor,
    seriesColor,
    type VisualStyle,
} from './visualPalettes';

/** Fence language the chart action writes, from functions_chart_operations.py. */
export const INLINE_CHART_LANGUAGE = 'simplechart';

/** Chart kinds this client can draw, in the order the type picker offers them. */
export const CHART_KINDS = [
    'bar',
    'stacked_bar',
    'line',
    'area',
    'stacked_line',
    'radar',
    'pie',
    'doughnut',
    'polar_area',
    'scatter',
    'bubble',
] as const;

const ALLOWED_KINDS = new Set<string>(CHART_KINDS);

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
    pointRadius?: number;
    type?: 'line' | 'bar';
}

export interface ChartTable {
    columns: string[];
    rows: unknown[][];
}

/**
 * Everything about a chart that is not its numbers.
 *
 * The first eleven come from the chart action's own payload and are shared with the classic
 * client and the server-side export renderer. The rest were added for the chart editor, are
 * absent from every chart generated before it, and therefore all default to what those charts
 * already did.
 *
 * `yMin`, `yMax`, `yScale` and `beginAtZero` describe the *value* axis rather than literally the
 * y axis, because a horizontal bar chart draws its values along the bottom. The same is true of
 * `yAxisLabel`, which the server-side export has always swapped for horizontal bars.
 */
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
    /** Explicit value-axis bounds, or null to let the chart choose them from the data. */
    yMin: number | null;
    yMax: number | null;
    yScale: 'linear' | 'logarithmic';
    /** Category label rotation in degrees, for axes too crowded to read straight. */
    xTickRotation: number;
    /** Most category ticks to draw before thinning them out, or null for all of them. */
    xTickLimit: number | null;
    /** Share of its slot a bar fills, matching Chart.js `barPercentage`. */
    barWidth: number;
    /** Series stroke width. */
    lineWidth: number;
    /** Point marker radius on line, area and scatter charts. */
    pointRadius: number;
    showGridX: boolean;
    showGridY: boolean;
}

/** Value-axis scales a chart may use. */
export const CHART_SCALE_TYPES = ['linear', 'logarithmic'] as const;

/** What each added option means when the payload does not mention it. */
export const CHART_OPTION_DEFAULTS = {
    yMin: null,
    yMax: null,
    yScale: 'linear',
    xTickRotation: 0,
    xTickLimit: null,
    barWidth: 0.9,
    lineWidth: 2,
    pointRadius: 3,
    showGridX: true,
    showGridY: true,
} as const;

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

/** A number clamped into a range, falling back when the payload did not give a usable one. */
function sanitizeBoundedNumber(
    value: unknown,
    minimum: number,
    maximum: number,
    fallback: number,
): number {
    const parsed = sanitizeNumber(value);
    if (parsed === null) {
        return fallback;
    }
    return Math.min(Math.max(parsed, minimum), maximum);
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
 *
 * Exported for the editor, which has to be able to read a hand-written payload before it can
 * offer to change anything in it.
 */
export function parseLooseChartSpec(payloadText: string): LooseRecord {
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

/**
 * Turn the payload's datasets into ones a chart can be built from.
 *
 * `options` is passed in because three of its entries describe the series rather than the
 * chart — smoothing, fill and stroke width — and a chart-wide choice has to be reconciled with
 * whatever the individual dataset asked for. The chart-wide value wins where it was set
 * deliberately, which is what makes those controls do anything at all.
 */
function normalizeDatasets(
    kind: string,
    rawDatasets: unknown,
    labels: string[],
    options: ChartSpecOptions,
): ChartDataset[] {
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
                borderWidth: options.lineWidth,
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
                dataset.fill = source.fill === true || options.fill || kind === 'area';
                // Smoothing off is a deliberate chart-wide choice and overrides the dataset;
                // smoothing on leaves a dataset that asked for straight segments alone.
                dataset.tension = !options.smooth || source.tension === 0 ? 0 : 0.35;
            }

            if (kind === 'radar') {
                dataset.fill = source.fill === true || options.fill;
            }

            // Bubbles are sized by each point's own radius, so a marker size would fight it.
            if (kind !== 'bubble' && kind !== 'bar' && kind !== 'stacked_bar') {
                dataset.pointRadius = options.pointRadius;
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
    const scaleType = sanitizeText(rawOptions.yScale, 20).toLowerCase();
    const tickLimit = sanitizeNumber(rawOptions.xTickLimit);

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
        yMin: sanitizeNumber(rawOptions.yMin),
        yMax: sanitizeNumber(rawOptions.yMax),
        yScale: scaleType === 'logarithmic' ? 'logarithmic' : 'linear',
        xTickRotation: sanitizeBoundedNumber(rawOptions.xTickRotation, 0, 90, 0),
        // A limit below two would leave an axis with nothing readable on it.
        xTickLimit: tickLimit === null ? null : Math.min(Math.max(Math.round(tickLimit), 2), 200),
        barWidth: sanitizeBoundedNumber(rawOptions.barWidth, 0.1, 1, 0.9),
        lineWidth: sanitizeBoundedNumber(rawOptions.lineWidth, 0, 10, 2),
        pointRadius: sanitizeBoundedNumber(rawOptions.pointRadius, 0, 20, 3),
        showGridX: rawOptions.showGridX !== false,
        showGridY: rawOptions.showGridY !== false,
    };

    const datasets = normalizeDatasets(kind, dataSource.datasets, labels, options);
    if (!datasets.length) {
        return null;
    }

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

/** True when a chart kind colours each slice rather than each series. */
export function isSegmentChart(kind: string): boolean {
    return kind === 'pie' || kind === 'doughnut' || kind === 'polar_area';
}

/** Matches CHART_COLOR_MAX_EDIT_TARGETS in the classic client. */
const MAX_COLOR_TARGETS = 12;

export interface ChartColorTarget {
    /** Index into the palette, and the key an override is stored under. */
    index: number;
    label: string;
    /** The colour currently in effect, for the swatch shown next to the label. */
    color: string;
}

/**
 * The series or slices a reader can recolour, with their current colours.
 *
 * Capped so a chart with fifty series does not produce fifty colour inputs; the classic
 * client caps at the same number for the same reason.
 */
export function chartColorTargets(spec: ChartSpec, style: VisualStyle): ChartColorTarget[] {
    const names = isSegmentChart(spec.kind)
        ? spec.data.labels.map((label, index) => label || `Slice ${index + 1}`)
        : spec.data.datasets.map((dataset, index) => dataset.label || `Series ${index + 1}`);

    return names.slice(0, MAX_COLOR_TARGETS).map((label, index) => ({
        index,
        label,
        color: seriesColor(style, index),
    }));
}

/**
 * Apply the reader's colours to a copy of the spec's datasets.
 *
 * A preset replaces every colour. An individual pick replaces only its own, which is why the
 * palette is applied first and the explicit entries are read through `seriesColor` afterwards:
 * a chart left on the Default palette keeps whatever colours its payload asked for, except for
 * the one series someone deliberately changed.
 */
function styleDatasets(spec: ChartSpec, style: VisualStyle): ChartDataset[] {
    const datasets = spec.data.datasets.map((dataset) => ({ ...dataset }));
    const usePalette = style.palette !== 'default';

    if (isSegmentChart(spec.kind)) {
        const length = spec.data.labels.length || datasets[0]?.data.length || 0;
        if (!length) {
            return datasets;
        }

        return datasets.map((dataset) => {
            const backgrounds = toColorArray(dataset.backgroundColor, length);
            const borders = toColorArray(dataset.borderColor, length);

            for (let index = 0; index < length; index += 1) {
                const explicit = style.colors[String(index)];
                if (!usePalette && !explicit) {
                    continue;
                }
                // A styled slice is filled solid: a pale wash is hard to tell apart from its
                // neighbour once someone has gone to the trouble of choosing the colour.
                const color = seriesColor(style, index);
                backgrounds[index] = color;
                borders[index] = color;
            }

            return { ...dataset, backgroundColor: backgrounds, borderColor: borders };
        });
    }

    return datasets.map((dataset, index) => {
        const explicit = style.colors[String(index)];
        if (!usePalette && !explicit) {
            return dataset;
        }
        const color = seriesColor(style, index);
        return { ...dataset, borderColor: color, backgroundColor: hexToRgba(color) };
    });
}

function toColorArray(value: string | string[], length: number): string[] {
    if (Array.isArray(value)) {
        const colors = value.slice(0, length);
        while (colors.length < length) {
            colors.push(value[colors.length % value.length] ?? '#1c6ea4');
        }
        return colors;
    }
    return Array.from({ length }, () => value);
}

/**
 * Fills the canvas before anything is drawn on it.
 *
 * Registered per chart rather than globally, so only a chart whose background someone actually
 * chose is affected. It also means the fill is part of the canvas itself and therefore part of
 * the downloaded PNG, rather than something the export has to reproduce separately.
 */
function backgroundPlugin(color: string) {
    return {
        id: 'simplechatBackground',
        beforeDraw(chart: {
            ctx: CanvasRenderingContext2D;
            canvas: HTMLCanvasElement;
        }) {
            const { ctx, canvas } = chart;
            ctx.save();
            ctx.globalCompositeOperation = 'destination-over';
            ctx.fillStyle = color;
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            ctx.restore();
        },
    };
}

/**
 * Build the Chart.js configuration for a spec.
 *
 * The chart's own title and subtitle plugins are left off: V2 renders those as text above the
 * canvas so they use the application's typography, stay selectable, and are readable by a
 * screen reader rather than being baked into the bitmap.
 *
 * `background` is the colour the reader picked, or null to leave the canvas transparent as it
 * has always been. When one is given, axis and legend colours are recomputed from it rather
 * than taken from the app theme, because a dark background chosen in light mode would
 * otherwise be labelled in dark grey on dark.
 */
export function buildChartConfig(
    spec: ChartSpec,
    theme: { text: string; grid: string },
    style?: VisualStyle | null,
    background?: string | null,
): Record<string, unknown> {
    const baseType = getBaseChartType(spec.kind);
    const text = background ? readableTextColor(background) : theme.text;
    const grid = background ? mixHex(text, background, 0.18) : theme.grid;

    const datasets =
        style && !isDefaultVisualStyle(style)
            ? styleDatasets(spec, style)
            : spec.data.datasets.map((dataset) => ({ ...dataset }));

    const config: Record<string, unknown> = {
        type: baseType,
        data: {
            datasets,
            ...(spec.data.labels.length ? { labels: [...spec.data.labels] } : {}),
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            // Animation is disabled because a chart can be re-created while a reply is still
            // streaming, and replaying the entry animation on each pass is distracting.
            animation: false,
            interaction: { mode: 'nearest', intersect: false },
            color: text,
            plugins: {
                legend: {
                    display: spec.options.showLegend,
                    position: spec.options.legendPosition,
                    labels: { color: text },
                },
                title: { display: false },
                subtitle: { display: false },
            },
        },
        ...(background ? { plugins: [backgroundPlugin(background)] } : {}),
    };

    const options = config.options as Record<string, unknown>;

    if (['bar', 'line', 'scatter', 'bubble'].includes(baseType)) {
        const horizontal = spec.options.horizontal && baseType === 'bar';
        // A horizontal bar chart draws its values along the bottom, so the axis the value
        // options describe is x rather than y. The server-side export has always swapped the
        // axis titles for this case; everything else about the value axis is swapped here too,
        // so a range or a log scale lands on the axis that actually carries the numbers.
        const valueAxis = horizontal ? 'x' : 'y';
        const categoryAxis = horizontal ? 'y' : 'x';

        // A logarithmic axis cannot show zero, so the "start at zero" request is dropped rather
        // than producing an axis Chart.js refuses to draw.
        const logarithmic = spec.options.yScale === 'logarithmic';

        const valueScale: Record<string, unknown> = {
            stacked: spec.options.stacked,
            beginAtZero: !logarithmic && spec.options.beginAtZero,
            ticks: { color: text },
            grid: {
                color: grid,
                display: horizontal ? spec.options.showGridX : spec.options.showGridY,
            },
            title: {
                display: Boolean(spec.options.yAxisLabel),
                text: spec.options.yAxisLabel,
                color: text,
            },
        };
        if (logarithmic) {
            valueScale.type = 'logarithmic';
        }
        if (spec.options.yMin !== null && (!logarithmic || spec.options.yMin > 0)) {
            valueScale.min = spec.options.yMin;
        }
        if (spec.options.yMax !== null) {
            valueScale.max = spec.options.yMax;
        }

        const categoryTicks: Record<string, unknown> = { color: text };
        if (spec.options.xTickRotation > 0) {
            categoryTicks.minRotation = spec.options.xTickRotation;
            categoryTicks.maxRotation = spec.options.xTickRotation;
        }
        if (spec.options.xTickLimit !== null) {
            categoryTicks.maxTicksLimit = spec.options.xTickLimit;
        }

        const categoryScale: Record<string, unknown> = {
            stacked: spec.options.stacked,
            ticks: categoryTicks,
            grid: {
                color: grid,
                display: horizontal ? spec.options.showGridY : spec.options.showGridX,
            },
            title: {
                display: Boolean(spec.options.xAxisLabel),
                text: spec.options.xAxisLabel,
                color: text,
            },
        };

        options.scales = { [valueAxis]: valueScale, [categoryAxis]: categoryScale };

        if (horizontal) {
            options.indexAxis = 'y';
        }

        if (baseType === 'bar') {
            options.barPercentage = spec.options.barWidth;
        }
    }

    if (baseType === 'doughnut') {
        options.cutout = spec.options.cutout || '60%';
    }

    if (baseType === 'radar') {
        options.scales = {
            r: {
                beginAtZero: spec.options.beginAtZero,
                ...(spec.options.yMin !== null ? { min: spec.options.yMin } : {}),
                ...(spec.options.yMax !== null ? { max: spec.options.yMax } : {}),
                ticks: { color: text, backdropColor: 'transparent' },
                grid: { color: grid, display: spec.options.showGridY },
                angleLines: { color: grid, display: spec.options.showGridX },
                pointLabels: { color: text },
            },
        };
    }

    return config;
}
