// chartEdits.ts
// The changes that can be made to a chart without writing any JSON.
//
// Every function here is a pure source-to-source transform, exactly as mermaidLayout.ts is for
// diagrams. A change made with a control is therefore the same kind of change as one typed in
// the source editor: it becomes a revision, it can be undone, it appears in the history, and it
// is honoured by the server-side export and by the classic client. Nothing is stored out of band
// as "chart settings".
//
// Two rules protect the payload while it is being rewritten:
//
// 1. Transforms mutate the *raw* parsed payload, never the normalised `ChartSpec`. The spec
//    fills in defaults and drops what it does not model, so round-tripping through it would
//    quietly delete anything the chart action wrote that this client does not read.
// 2. The serialised form follows the source it came from. The chart action emits compact
//    single-line JSON, and pretty-printing it on the first control click would inflate a large
//    payload past the size a revision may be stored at.
//
// A hand-written loose payload is the one case where the form does change: it is read with the
// same tolerant parser the renderer uses and written back as JSON, because there is no faithful
// way to edit a format that has no writer.

import {
    CHART_OPTION_DEFAULTS,
    parseInlineChart,
    parseLooseChartSpec,
    type ChartPoint,
    type ChartSpec,
} from './inlineChartSpec';

/** Chart kinds whose data is a list of labels with one value per label. */
export const CATEGORY_CHART_KINDS = [
    'bar',
    'stacked_bar',
    'line',
    'area',
    'stacked_line',
    'radar',
    'pie',
    'doughnut',
    'polar_area',
] as const;

/** Chart kinds whose data is a list of x/y points rather than labelled categories. */
export const POINT_CHART_KINDS = ['scatter', 'bubble'] as const;

/** Chart kinds that draw one series as slices of a whole. */
export const SEGMENT_CHART_KINDS = ['pie', 'doughnut', 'polar_area'] as const;

export const CHART_KIND_LABELS: Record<string, string> = {
    bar: 'Bar',
    stacked_bar: 'Stacked bar',
    line: 'Line',
    area: 'Area',
    stacked_line: 'Stacked area',
    radar: 'Radar',
    pie: 'Pie',
    doughnut: 'Doughnut',
    polar_area: 'Polar area',
    scatter: 'Scatter',
    bubble: 'Bubble',
};

/** Most labels a category chart may carry, matching the renderer's own cap. */
export const MAX_CHART_LABELS = 200;

/** Most series a chart may carry, matching the renderer's own cap. */
export const MAX_CHART_SERIES = 20;

/**
 * Largest chart the data grid will offer to edit.
 *
 * Beyond this the grid is unusable, and — more importantly — showing a truncated grid would
 * delete the rows below the cut the moment it was saved. Oversized charts are sent to the
 * source editor instead, where nothing is hidden.
 */
export const MAX_EDITABLE_ROWS = 200;

type LooseRecord = Record<string, unknown>;

/** A chart payload, with how it was written alongside it. */
export interface ChartPayloadDocument {
    raw: LooseRecord;
    /** True when the payload was a single line, as the chart action writes it. */
    compact: boolean;
}

/**
 * Read a payload into something that can be changed and written back.
 *
 * Strict JSON first, because that is what the chart action produces and what round-trips
 * faithfully. The tolerant parser is the fallback for a fence a model wrote by hand.
 *
 * A payload that opens with a brace is only ever read as JSON. The renderer will happily fall
 * back to the line scanner for one, because showing something beats showing nothing — but this
 * is the reader behind the *writer*, and running a half-typed JSON payload through a scanner
 * that looks for `key: value` lines would produce a confident misreading and then save it over
 * the original.
 */
export function readChartPayload(source: string): ChartPayloadDocument | null {
    const text = String(source ?? '').trim();
    if (!text) {
        return null;
    }

    const looksLikeJson = text.startsWith('{');

    try {
        const parsed = JSON.parse(text);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            return { raw: parsed as LooseRecord, compact: !text.includes('\n') };
        }
        return null;
    } catch {
        if (looksLikeJson) {
            return null;
        }
        const loose = parseLooseChartSpec(text);
        return loose && typeof loose === 'object' ? { raw: loose, compact: false } : null;
    }
}

/** Serialise a payload the way it was written. */
export function writeChartPayload(document: ChartPayloadDocument): string {
    return document.compact
        ? JSON.stringify(document.raw)
        : JSON.stringify(document.raw, null, 2);
}

/**
 * Apply a change to a payload, returning the source unchanged when it cannot be read.
 *
 * Returning the original rather than throwing keeps a control from destroying a payload it did
 * not understand; the editor separately refuses to enable controls for a source it cannot parse,
 * so this is the second line of defence rather than the first.
 */
export function editChartPayload(source: string, mutate: (raw: LooseRecord) => void): string {
    const document = readChartPayload(source);
    if (!document) {
        return source;
    }
    mutate(document.raw);
    return writeChartPayload(document);
}

/** Re-serialise a payload across several lines, for reading and hand-editing. */
export function formatChartSource(source: string): string {
    const document = readChartPayload(source);
    return document ? JSON.stringify(document.raw, null, 2) : source;
}

/** The `options` object on a payload, created if the payload has none. */
function optionsOf(raw: LooseRecord): LooseRecord {
    const existing = raw.options;
    if (existing && typeof existing === 'object' && !Array.isArray(existing)) {
        return existing as LooseRecord;
    }
    const created: LooseRecord = {};
    raw.options = created;
    return created;
}

/**
 * Options whose absence means exactly one thing, whatever kind of chart it is.
 *
 * Writing one of these back at its default removes the key instead, so a chart that was never
 * touched and one explicitly set back to the default produce the same payload — the same rule
 * the diagram spacing control follows.
 */
const REMOVABLE_DEFAULTS: Record<string, unknown> = {
    showLegend: true,
    legendPosition: 'top',
    beginAtZero: true,
    smooth: true,
    showDataTable: true,
    horizontal: false,
    cutout: '60%',
    yScale: CHART_OPTION_DEFAULTS.yScale,
    xTickRotation: CHART_OPTION_DEFAULTS.xTickRotation,
    barWidth: CHART_OPTION_DEFAULTS.barWidth,
    lineWidth: CHART_OPTION_DEFAULTS.lineWidth,
    pointRadius: CHART_OPTION_DEFAULTS.pointRadius,
    showGridX: CHART_OPTION_DEFAULTS.showGridX,
    showGridY: CHART_OPTION_DEFAULTS.showGridY,
};

/**
 * Set one entry in a chart's options.
 *
 * `null` removes the key, which is how "no explicit maximum" and "no tick limit" are expressed.
 * `stacked` and `fill` are never removed even at their default, because the renderer forces them
 * on for stacked and area charts and an absent key would read as "whatever the kind implies"
 * rather than as the choice that was made.
 */
export function setChartOption(source: string, key: string, value: unknown): string {
    return editChartPayload(source, (raw) => {
        const options = optionsOf(raw);
        const removable = Object.prototype.hasOwnProperty.call(REMOVABLE_DEFAULTS, key);
        if (value === null || value === '' || (removable && value === REMOVABLE_DEFAULTS[key])) {
            delete options[key];
            return;
        }
        options[key] = value;
    });
}

/**
 * Set the chart's title, subtitle or description.
 *
 * These sit at the top level of the payload rather than inside `options`, which is why they do
 * not go through `setChartOption`.
 */
export function setChartText(
    source: string,
    key: 'title' | 'subtitle' | 'description',
    value: string,
): string {
    return editChartPayload(source, (raw) => {
        const trimmed = String(value ?? '').trim();
        if (!trimmed) {
            delete raw[key];
            return;
        }
        raw[key] = trimmed;
    });
}

/**
 * Change what kind of chart this is.
 *
 * `chartType` is written alongside `kind` because the payload carries both and the renderer
 * falls back to `chartType` when `kind` is not one it knows — leaving a stale `chartType` behind
 * would make the two disagree about the same chart.
 *
 * The stacked and area kinds imply options that the renderer would otherwise keep forcing on
 * after a switch away from them, so those are cleared here rather than being left to confuse
 * whoever next opens the Design tab.
 */
export function setChartKind(source: string, kind: string): string {
    return editChartPayload(source, (raw) => {
        raw.kind = kind;
        raw.chartType = baseTypeFor(kind);

        const options = optionsOf(raw);
        if (kind === 'stacked_bar' || kind === 'stacked_line') {
            options.stacked = true;
        } else if (options.stacked === true) {
            delete options.stacked;
        }

        if (kind === 'area') {
            options.fill = true;
        } else if (kind !== 'radar' && options.fill === true) {
            delete options.fill;
        }

        // Only bars can be laid on their side, and only doughnuts have a hole.
        if (kind !== 'bar' && kind !== 'stacked_bar') {
            delete options.horizontal;
        }
        if (kind !== 'doughnut') {
            delete options.cutout;
        }
    });
}

/** The Chart.js type behind a kind, mirroring `getBaseChartType`. */
function baseTypeFor(kind: string): string {
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

/** True when a chart's data is x/y points rather than labelled categories. */
export function isPointChart(kind: string): boolean {
    return (POINT_CHART_KINDS as readonly string[]).includes(kind);
}

/** True when a chart draws one series as slices of a whole. */
export function isSegmentChartKind(kind: string): boolean {
    return (SEGMENT_CHART_KINDS as readonly string[]).includes(kind);
}

export interface ChartKindChoices {
    kinds: string[];
    /** Why some kinds are missing, or null when they all are offered. */
    note: string | null;
}

/**
 * The kinds this chart could become, and why the rest are not offered.
 *
 * A scatter chart's data is a list of x/y points and a bar chart's is a value per category;
 * neither can be read as the other, so offering the switch would produce an empty chart. Slices
 * are held back for a different reason: a pie of five series is five concentric rings, which
 * answers no question anyone has.
 */
export function chartKindChoices(spec: ChartSpec): ChartKindChoices {
    if (isPointChart(spec.kind)) {
        return {
            kinds: [...POINT_CHART_KINDS],
            note: 'A scatter or bubble chart plots x and y pairs, so it cannot be redrawn as a chart of labelled categories.',
        };
    }

    const multipleSeries = spec.data.datasets.length > 1;
    const kinds = (CATEGORY_CHART_KINDS as readonly string[]).filter(
        (kind) => !multipleSeries || !isSegmentChartKind(kind),
    );

    return {
        kinds,
        note: multipleSeries
            ? 'Pie, doughnut and polar area show one series as slices of a whole, so they are offered once a chart has a single series.'
            : null,
    };
}

/* -------------------------------------------------------------------------- */
/* The numbers                                                                 */
/* -------------------------------------------------------------------------- */

export interface ChartSeriesDraft {
    label: string;
    /** One value per label on a category chart. Null is a gap rather than a zero. */
    values: (number | null)[];
    /** The plotted pairs on a scatter or bubble chart. */
    points: ChartPoint[];
}

export interface ChartDataDraft {
    labels: string[];
    series: ChartSeriesDraft[];
}

/** The chart's numbers, in the shape the data grid edits them in. */
export function readChartDataDraft(spec: ChartSpec): ChartDataDraft {
    const pointBased = isPointChart(spec.kind);
    const labels = pointBased ? [] : [...spec.data.labels];

    const series = spec.data.datasets.map((dataset, index) => {
        const name = dataset.label || `Series ${index + 1}`;
        if (pointBased) {
            return {
                label: name,
                values: [],
                points: (dataset.data as ChartPoint[]).map((point) => ({ ...point })),
            };
        }

        const values = dataset.data as (number | null)[];
        return {
            label: name,
            // Padded to the label count so the grid is rectangular: a series that stops early
            // would otherwise have no cell to type the missing value into.
            values: labels.map((_, position) => values[position] ?? null),
            points: [],
        };
    });

    return { labels, series };
}

/**
 * Whether a chart's numbers are small enough to edit in a grid.
 *
 * A chart past the limit is not refused — it is sent to the source editor, which shows all of
 * it. What is refused is a grid that would show part of the data and delete the rest on save.
 */
export function isEditableAsGrid(spec: ChartSpec): boolean {
    if (spec.data.datasets.length > MAX_CHART_SERIES) {
        return false;
    }
    if (isPointChart(spec.kind)) {
        return spec.data.datasets.every(
            (dataset) => (dataset.data as ChartPoint[]).length <= MAX_EDITABLE_ROWS,
        );
    }
    return spec.data.labels.length <= MAX_EDITABLE_ROWS;
}

/**
 * Write edited numbers back into a payload.
 *
 * The payload's own `table` is removed. It is a copy of the same numbers written for the data
 * disclosure, and leaving a stale one behind would show a table that disagrees with the chart
 * above it. Nothing is lost: `resolveChartTable` derives the disclosure from the labels and
 * series whenever the payload has no table of its own.
 *
 * Series colours are carried across by position so recolouring and then editing a value does
 * not silently reset the chart's appearance.
 */
export function setChartData(
    source: string,
    draft: ChartDataDraft,
    kind: string,
): string {
    return editChartPayload(source, (raw) => {
        const pointBased = isPointChart(kind);
        const bubble = kind === 'bubble';

        const labels = draft.labels
            .slice(0, MAX_CHART_LABELS)
            // Trimmed on the way in because the parser trims on the way out. Storing "North "
            // would leave the payload holding a space that can never be read back, so what is
            // stored and what the grid shows would permanently disagree.
            .map((label) => String(label ?? '').trim());
        const previous = Array.isArray((raw.data as LooseRecord | undefined)?.datasets)
            ? (((raw.data as LooseRecord).datasets as unknown[]) ?? [])
            : [];

        const datasets = draft.series.slice(0, MAX_CHART_SERIES).map((series, index) => {
            const existing =
                previous[index] && typeof previous[index] === 'object'
                    ? { ...(previous[index] as LooseRecord) }
                    : ({} as LooseRecord);

            existing.label = String(series.label ?? '').trim();
            existing.data = pointBased
                ? series.points.map((point) =>
                      bubble ? { x: point.x, y: point.y, r: point.r ?? 1 } : { x: point.x, y: point.y },
                  )
                : labels.map((_, position) => series.values[position] ?? null);

            return existing;
        });

        raw.data = pointBased ? { datasets } : { labels, datasets };
        delete raw.table;
    });
}

/* -------------------------------------------------------------------------- */
/* Validation                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Whether a source is a chart this client can draw, and why not when it is not.
 *
 * Reported separately from the generic block checks in blockRevisions.ts because a chart can be
 * perfectly storable — the right length, no fence in it — and still be unreadable as a chart,
 * which the editor has to say before the change is saved rather than after.
 */
export function describeChartProblem(source: string): string | null {
    const text = String(source ?? '').trim();
    if (!text) {
        return null;
    }

    if (!readChartPayload(text)) {
        return 'The chart data is not valid JSON.';
    }
    if (!parseInlineChart(text)) {
        return 'This is not a chart that can be drawn. A chart needs a known kind and at least one series with data in it.';
    }
    return null;
}

/**
 * A short account of what changed between two payloads, for the history entry.
 *
 * The alternative — one entry per control, or a bare "Edited" — makes the history list useless
 * exactly when it matters, which is when several things were changed at once and a reader is
 * trying to find the version from before one of them.
 */
export function describeChartChanges(before: string, after: string): string {
    const from = parseInlineChart(before);
    const to = parseInlineChart(after);
    if (!from || !to) {
        return '';
    }

    const changes: string[] = [];

    if (from.kind !== to.kind) {
        changes.push(`Type: ${CHART_KIND_LABELS[to.kind] ?? to.kind}`);
    }
    if (from.title !== to.title || from.subtitle !== to.subtitle) {
        changes.push('Titles');
    }
    if (from.description !== to.description) {
        changes.push('Description');
    }
    if (from.options.xAxisLabel !== to.options.xAxisLabel || from.options.yAxisLabel !== to.options.yAxisLabel) {
        changes.push('Axis names');
    }
    if (
        from.options.yMin !== to.options.yMin ||
        from.options.yMax !== to.options.yMax ||
        from.options.beginAtZero !== to.options.beginAtZero ||
        from.options.yScale !== to.options.yScale
    ) {
        changes.push('Value axis');
    }
    if (
        from.options.xTickRotation !== to.options.xTickRotation ||
        from.options.xTickLimit !== to.options.xTickLimit
    ) {
        changes.push('Category labels');
    }
    if (from.options.barWidth !== to.options.barWidth) {
        changes.push('Bar width');
    }
    if (
        from.options.lineWidth !== to.options.lineWidth ||
        from.options.pointRadius !== to.options.pointRadius ||
        from.options.smooth !== to.options.smooth ||
        from.options.fill !== to.options.fill
    ) {
        changes.push('Series style');
    }
    if (from.options.showLegend !== to.options.showLegend || from.options.legendPosition !== to.options.legendPosition) {
        changes.push('Legend');
    }
    if (from.options.showGridX !== to.options.showGridX || from.options.showGridY !== to.options.showGridY) {
        changes.push('Gridlines');
    }
    if (from.options.horizontal !== to.options.horizontal || from.options.stacked !== to.options.stacked) {
        changes.push('Layout');
    }
    if (from.options.cutout !== to.options.cutout) {
        changes.push('Hole size');
    }
    if (dataSignature(from) !== dataSignature(to)) {
        changes.push('Data');
    }

    return changes.join(', ');
}

/** Everything about a chart's numbers, flattened so two charts can be compared. */
function dataSignature(spec: ChartSpec): string {
    return JSON.stringify([
        spec.data.labels,
        spec.data.datasets.map((dataset) => [dataset.label, dataset.data]),
    ]);
}
