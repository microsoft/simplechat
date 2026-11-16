// DashboardParts.tsx
// The pieces V2 dashboards draw with: tiles that open what they count, chart panels, the data
// table every chart offers in place of reading the chart, and the window picker.
//
// Moved out of the Control Center dashboard so the Review center and the Approvals dashboard
// draw the same way. The Control Center passes its own link check to MetricTile, so its tiles
// behave exactly as before.

import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { safeSameOriginUrl } from '../../lib/apiClient';
import type { ChartThemeColors } from '../../lib/chartRuntime';
import { KpiCard } from '../controlCenter/ControlCenterPrimitives';
import { cartesianOptions } from '../settings/StatsChart';

export type DashboardMetric = {
    value: number | null;
    delta: number | null;
    percent_change?: number | null;
    previous?: number;
    available?: boolean;
};

/** Series colours shared by the dashboards, so a series keeps its colour from one to the next. */
export const CHART_COLORS = {
    blue: { border: '#4f8cff', fill: 'rgba(79, 140, 255, 0.24)' },
    cyan: { border: '#22b8cf', fill: 'rgba(34, 184, 207, 0.30)' },
    green: { border: '#37b679', fill: 'rgba(55, 182, 121, 0.28)' },
    amber: { border: '#e8a23a', fill: 'rgba(232, 162, 58, 0.28)' },
    purple: { border: '#a78bfa', fill: 'rgba(167, 139, 250, 0.28)' },
    rose: { border: '#f472b6', fill: 'rgba(244, 114, 182, 0.28)' },
};

export type ChartColor = keyof typeof CHART_COLORS;
export const CHART_COLOR_ORDER = Object.keys(CHART_COLORS) as ChartColor[];

export function makeDatasets(series: { label: string; values: number[]; color: ChartColor }[]) {
    return series.map(({ label, values, color }) => ({
        label,
        data: values,
        borderColor: CHART_COLORS[color].border,
        backgroundColor: CHART_COLORS[color].fill,
        borderWidth: 2,
        borderRadius: 3,
        pointRadius: 1,
        tension: 0.3,
    }));
}

/** The shared cartesian styling with the series stacked, for counts split into parts. */
export function stackedBarOptions(theme: ChartThemeColors) {
    const options = cartesianOptions(theme, true);
    return {
        ...options,
        scales: {
            x: { ...options.scales.x, stacked: true },
            y: { ...options.scales.y, stacked: true },
        },
    };
}

export function metricDetail(metric: DashboardMetric, days: number): string {
    if (metric.value === null || metric.available === false) {
        return 'Not available for this period';
    }
    if (metric.delta === null) {
        return 'Current status; historical status snapshots are not recorded';
    }
    if (metric.delta === 0) {
        return `No change vs the previous ${days}-day period`;
    }
    const direction = metric.delta > 0 ? '↑' : '↓';
    const percentage = metric.percent_change === null || metric.percent_change === undefined
        ? ''
        : ` (${Math.abs(metric.percent_change)}%)`;
    return `${direction} ${Math.abs(metric.delta).toLocaleString()} vs previous period${percentage}`;
}

function safeSameOriginHref(value: string): string {
    return safeSameOriginUrl(value, '/');
}

const TILE_LINK_CLASS = 'block rounded-2xl focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent';

export function MetricTile({
    label,
    metric,
    to,
    days,
    valueLabel,
    safeHref = safeSameOriginHref,
}: {
    label: string;
    metric: DashboardMetric;
    to: string;
    days: number;
    valueLabel?: string;
    /** Narrows where the tile may lead; any same-origin path by default. */
    safeHref?: (value: string) => string;
}) {
    const value = metric.value === null || metric.available === false
        ? 'Not tracked'
        : valueLabel ?? metric.value.toLocaleString();
    return (
        <Link to={safeHref(to)} className={TILE_LINK_CLASS}>
            <KpiCard label={label} value={value} detail={metricDetail(metric, days)} />
        </Link>
    );
}

/**
 * A count that opens the records it counts. Without a destination it is a plain tile, for a
 * figure there is no list of.
 */
export function StatTile({
    label,
    value,
    detail,
    to,
    testId,
}: {
    label: string;
    value: ReactNode;
    detail?: string;
    to?: string | null;
    testId?: string;
}) {
    if (!to) {
        return <div data-testid={testId}><KpiCard label={label} value={value} detail={detail} /></div>;
    }
    return (
        <Link to={safeSameOriginHref(to)} className={TILE_LINK_CLASS} data-testid={testId}>
            <KpiCard label={label} value={value} detail={detail} />
        </Link>
    );
}

export function ChartDataTable({
    title,
    dates,
    series,
    rowHeader = 'Date',
}: {
    title: string;
    /** The row labels: days for a daily chart, or the categories of a breakdown. */
    dates: string[];
    series: { label: string; values: number[] }[];
    rowHeader?: string;
}) {
    return (
        <details className="mt-3 text-xs text-text-2">
            <summary className="cursor-pointer font-medium">View {title.toLowerCase()} as a data table</summary>
            <div className="mt-2 max-h-56 overflow-auto rounded-lg border border-edge">
                <table className="w-full text-left">
                    <caption className="sr-only">
                        {title} chart data by {rowHeader === 'Date' ? 'day' : rowHeader.toLowerCase()}
                    </caption>
                    <thead className="bg-surface-2">
                        <tr>
                            <th scope="col" className="px-2 py-1">{rowHeader}</th>
                            {series.map((item) => <th key={item.label} scope="col" className="px-2 py-1">{item.label}</th>)}
                        </tr>
                    </thead>
                    <tbody>
                        {dates.map((date, index) => (
                            <tr key={date} className="border-t border-edge">
                                <th scope="row" className="px-2 py-1 font-normal">{date}</th>
                                {series.map((item) => <td key={item.label} className="px-2 py-1">{item.values[index] ?? 0}</td>)}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </details>
    );
}

export function ChartPanel({
    title,
    description,
    headingLevel = 3,
    children,
}: {
    title: string;
    description?: string;
    /** Where the panel sits in the page outline; h4 for panels inside a titled dashboard section. */
    headingLevel?: 3 | 4;
    children: ReactNode;
}) {
    const Heading = headingLevel === 4 ? 'h4' : 'h3';
    return (
        <section className="min-w-0 rounded-2xl border border-edge bg-surface-1 p-4">
            <Heading className="mb-3 text-sm font-semibold text-text-1">{title}</Heading>
            {description ? <p className="-mt-2 mb-3 text-xs text-text-3">{description}</p> : null}
            {children}
        </section>
    );
}

export function WindowSelect<T extends string>({
    id,
    value,
    options,
    onChange,
    label = 'Period',
}: {
    id: string;
    value: T;
    options: readonly T[];
    onChange: (value: T) => void;
    label?: string;
}) {
    return (
        <label htmlFor={id} className="text-xs text-text-3">
            {label}
            <select
                id={id}
                value={value}
                onChange={(event) => onChange(event.target.value as T)}
                className="mt-1 block rounded-lg border border-edge bg-surface-1 px-3 py-2 text-sm text-text-1"
            >
                {options.map((option) => <option key={option} value={option}>Last {option} days</option>)}
            </select>
        </label>
    );
}
