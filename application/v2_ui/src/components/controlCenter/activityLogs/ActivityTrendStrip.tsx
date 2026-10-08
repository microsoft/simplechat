// ActivityTrendStrip.tsx
// A slim overview of the filtered range: how much activity there is, when it happened, and
// which types dominate. Every bar and type is a way to narrow the log below it.

import { useRef, useState } from 'react';
import { clsx } from 'clsx';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { formatUtcDay, shiftUtcDate, type ActivityFilters, type ActivitySummary } from '../../../lib/activityLogs';
import { GlassPanel, Skeleton } from '../../ui/primitives';

const TOP_TYPES = 4;

function bucketLabel(start: string, days: number, rangeEnd: string): { label: string; end: string } {
    const end = days > 1 ? shiftUtcDate(start, days - 1) : start;
    const clipped = end > rangeEnd ? rangeEnd : end;
    return {
        label: clipped === start ? formatUtcDay(start, false) : `${formatUtcDay(start, false)} – ${formatUtcDay(clipped, false)}`,
        end: clipped,
    };
}

export function ActivityTrendStrip({ summary, error, filters, expanded, onToggleExpanded, onDrill, onToggleType, typeLabel }: {
    summary: ActivitySummary | null;
    error: string;
    filters: ActivityFilters;
    expanded: boolean;
    onToggleExpanded: () => void;
    onDrill: (start: string, end: string) => void;
    onToggleType: (type: string) => void;
    typeLabel: (type: string) => string;
}) {
    const [focusIndex, setFocusIndex] = useState(0);
    const bars = useRef<(HTMLButtonElement | null)[]>([]);
    const histogram = summary?.histogram ?? [];
    const max = Math.max(1, ...histogram.map((bin) => bin.count));
    const topTypes = [...(summary?.facets ?? [])].sort((a, b) => b.count - a.count || a.activity_type.localeCompare(b.activity_type)).slice(0, TOP_TYPES);
    const typeCount = summary?.facets.length ?? 0;
    const total = summary?.sample_size ?? 0;
    const headline = !summary ? 'Counting activity…'
        : summary.truncated ? `More than ${summary.sample_limit.toLocaleString()} records`
            : `${total.toLocaleString()} ${total === 1 ? 'record' : 'records'}`;

    const moveFocus = (index: number) => {
        const next = Math.max(0, Math.min(histogram.length - 1, index));
        setFocusIndex(next);
        bars.current[next]?.focus();
    };

    return (
        <GlassPanel elevation="flat" className="px-4 py-3" role="region" aria-label="Activity trend">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                <p className="text-sm text-text-2" aria-live="polite">
                    <span className="font-semibold text-text-1">{headline}</span>
                    {summary ? <span className="text-text-3">
                        {' · '}{summary.bucket_days === 1 ? 'by UTC day' : `in ${summary.bucket_days}-day UTC periods`}
                        {summary.truncated ? ` · trend and counts use the newest ${summary.sample_limit.toLocaleString()}` : ''}
                    </span> : null}
                </p>
                <button type="button" onClick={onToggleExpanded} aria-expanded={expanded} aria-controls="activity-trend-body"
                    className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-text-3 hover:bg-surface-2 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-accent">
                    {expanded ? <ChevronUp size={13} aria-hidden="true" /> : <ChevronDown size={13} aria-hidden="true" />}
                    {expanded ? 'Hide trend' : 'Show trend'}
                </button>
            </div>
            {expanded ? (
                <div id="activity-trend-body" className="mt-3 grid gap-x-8 gap-y-4 lg:grid-cols-[minmax(0,1fr)_15rem]">
                    {error ? (
                        <p role="alert" className="text-sm text-danger lg:col-span-2">{error}</p>
                    ) : !summary ? (
                        <>
                            <Skeleton className="h-16" />
                            <Skeleton className="h-16" />
                        </>
                    ) : (
                        <>
                            <div className="min-w-0">
                                <div role="toolbar" aria-label="Activity by UTC date. Use the arrow keys to move between periods and Enter to show one."
                                    className="flex h-14 items-end gap-[3px]">
                                    {histogram.map((bin, index) => {
                                        const { label, end } = bucketLabel(bin.date, summary.bucket_days, filters.end_date);
                                        const description = `${label} (UTC): ${bin.count.toLocaleString()} ${bin.count === 1 ? 'record' : 'records'}`;
                                        return (
                                            <button
                                                key={bin.date}
                                                ref={(element) => { bars.current[index] = element; }}
                                                type="button"
                                                tabIndex={index === Math.min(focusIndex, histogram.length - 1) ? 0 : -1}
                                                aria-label={`${description}. Show only this ${summary.bucket_days === 1 ? 'day' : 'period'}.`}
                                                title={description}
                                                onFocus={() => setFocusIndex(index)}
                                                onClick={() => onDrill(bin.date, end)}
                                                onKeyDown={(event) => {
                                                    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
                                                    if (step) { event.preventDefault(); moveFocus(index + step); }
                                                    if (event.key === 'Home') { event.preventDefault(); moveFocus(0); }
                                                    if (event.key === 'End') { event.preventDefault(); moveFocus(histogram.length - 1); }
                                                }}
                                                className="group flex h-full min-w-0 flex-1 items-end rounded-sm focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
                                            >
                                                <span
                                                    aria-hidden="true"
                                                    style={{ height: bin.count ? `${Math.max(8, (bin.count / max) * 100)}%` : '2px' }}
                                                    className={clsx('block w-full rounded-t-[3px] transition-colors',
                                                        bin.count ? 'bg-accent/45 group-hover:bg-accent group-focus-visible:bg-accent' : 'bg-edge')}
                                                />
                                            </button>
                                        );
                                    })}
                                </div>
                                {histogram.length ? (
                                    <div className="mt-1 flex justify-between text-[11px] text-text-3" aria-hidden="true">
                                        <span>{formatUtcDay(histogram[0].date, false)}</span>
                                        <span>{formatUtcDay(filters.end_date, false)}</span>
                                    </div>
                                ) : null}
                            </div>
                            <div className="hidden min-w-0 sm:block">
                                <h3 className="mb-1 text-xs font-medium text-text-3">Top activity</h3>
                                {topTypes.length ? (
                                    <ul className="space-y-0.5">
                                        {topTypes.map((facet) => {
                                            const selected = filters.activity_type.includes(facet.activity_type);
                                            const label = facet.label || typeLabel(facet.activity_type);
                                            return (
                                                <li key={facet.activity_type}>
                                                    <button type="button" aria-pressed={selected}
                                                        aria-label={`${label}: ${facet.count.toLocaleString()} records. ${selected ? 'Remove this activity filter' : 'Show only this activity'}.`}
                                                        onClick={() => onToggleType(facet.activity_type)}
                                                        className={clsx('flex w-full items-center justify-between gap-3 rounded-md px-2 py-1 text-left text-xs transition-colors focus-visible:outline-2 focus-visible:outline-accent',
                                                            selected ? 'bg-accent-soft text-accent' : 'text-text-2 hover:bg-surface-2 hover:text-text-1')}>
                                                        <span className="truncate">{label}</span>
                                                        <span className="shrink-0 tabular-nums text-text-3">{facet.count.toLocaleString()}</span>
                                                    </button>
                                                </li>
                                            );
                                        })}
                                    </ul>
                                ) : <p className="px-2 text-xs text-text-3">No activity in this range.</p>}
                                {typeCount > TOP_TYPES ? (
                                    <p className="mt-1 px-2 text-[11px] text-text-3">{typeCount - TOP_TYPES} more {typeCount - TOP_TYPES === 1 ? 'type' : 'types'} in the Activity filter.</p>
                                ) : null}
                            </div>
                        </>
                    )}
                </div>
            ) : null}
        </GlassPanel>
    );
}
