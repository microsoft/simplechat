// StatsTab.tsx
// The user's own activity over a chosen window.
//
// The classic page draws these with Chart.js. Here they are plain SVG bars instead: the data
// is a flat series of daily counts, which needs no axis machinery, no interaction model and
// no animation loop. Adding a charting dependency for it would grow the bundle for everyone
// to draw a shape a <rect> already makes, and the repository's browser assets must be
// locally served in any case.

import { useCallback, useEffect, useState } from 'react';
import { api } from '../../lib/apiClient';
import { GlassPanel, Skeleton } from '../ui/primitives';

interface DayCount {
    date: string;
    count?: number;
    tokens?: number;
}

interface ActivityTrends {
    success?: boolean;
    logins?: DayCount[];
    conversations?: { creates?: DayCount[]; deletes?: DayCount[] };
    documents?: { uploads?: DayCount[]; deletes?: DayCount[] };
    tokens?: DayCount[];
    storage?: Record<string, number>;
    dateRange?: string[];
}

/** Windows the stats endpoint accepts, as day counts. */
const WINDOWS = [
    { days: 7, label: '7 days' },
    { days: 30, label: '30 days' },
    { days: 90, label: '90 days' },
];

function total(series: DayCount[] | undefined, key: 'count' | 'tokens' = 'count'): number {
    return (series ?? []).reduce((sum, day) => sum + (day[key] ?? 0), 0);
}

/**
 * A daily series as bars.
 *
 * Rendered as a fixed viewBox with the series scaled into it, so it stays sharp at any
 * width without measuring the container.
 */
function BarSeries({
    series,
    valueKey = 'count',
    label,
}: {
    series: DayCount[] | undefined;
    valueKey?: 'count' | 'tokens';
    label: string;
}) {
    const days = series ?? [];
    if (days.length === 0) {
        return <p className="text-xs text-text-3">No activity recorded.</p>;
    }

    const values = days.map((day) => day[valueKey] ?? 0);
    const peak = Math.max(...values, 1);
    const slot = 100 / days.length;
    // Leaves a hairline between bars without letting them vanish on a long window.
    const width = Math.max(slot * 0.7, 0.4);

    return (
        <svg
            viewBox="0 0 100 30"
            preserveAspectRatio="none"
            role="img"
            aria-label={`${label}: ${total(days, valueKey)} over ${days.length} days`}
            className="h-16 w-full"
        >
            {days.map((day, index) => {
                const value = day[valueKey] ?? 0;
                const height = value === 0 ? 0 : Math.max((value / peak) * 28, 0.8);
                return (
                    <rect
                        key={day.date}
                        x={index * slot + (slot - width) / 2}
                        y={30 - height}
                        width={width}
                        height={height}
                        className="fill-accent"
                    >
                        <title>{`${day.date}: ${value.toLocaleString()}`}</title>
                    </rect>
                );
            })}
        </svg>
    );
}

function TrendCard({
    title,
    value,
    children,
}: {
    title: string;
    value: string;
    children: React.ReactNode;
}) {
    return (
        <GlassPanel className="p-4">
            <div className="flex items-baseline justify-between">
                <h2 className="text-sm font-semibold text-text-1">{title}</h2>
                <span className="text-sm font-medium text-text-2">{value}</span>
            </div>
            <div className="mt-2">{children}</div>
        </GlassPanel>
    );
}

export function StatsTab() {
    const [days, setDays] = useState(30);
    const [data, setData] = useState<ActivityTrends | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const load = useCallback(async (windowDays: number) => {
        setLoading(true);
        setError(null);
        try {
            const response = await api.get<ActivityTrends>(
                `/api/user/activity-trends?days=${windowDays}`,
            );
            setData(response);
        } catch (caught) {
            setError(
                caught instanceof Error ? caught.message : 'Failed to load your activity.',
            );
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        void load(days);
    }, [load, days]);

    return (
        <div className="space-y-3">
            <div className="flex gap-1.5">
                {WINDOWS.map((window) => (
                    <button
                        key={window.days}
                        type="button"
                        onClick={() => setDays(window.days)}
                        aria-pressed={days === window.days}
                        className={
                            days === window.days
                                ? 'rounded-lg border border-accent bg-accent-soft px-3 py-1.5 text-xs font-medium text-accent'
                                : 'rounded-lg border border-edge px-3 py-1.5 text-xs text-text-2 hover:bg-surface-2'
                        }
                    >
                        {window.label}
                    </button>
                ))}
            </div>

            {error ? (
                <p className="rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
                    {error}
                </p>
            ) : loading ? (
                <div className="space-y-2">
                    <Skeleton className="h-28 w-full" />
                    <Skeleton className="h-28 w-full" />
                    <Skeleton className="h-28 w-full" />
                </div>
            ) : (
                <>
                    <TrendCard
                        title="Conversations started"
                        value={total(data?.conversations?.creates).toLocaleString()}
                    >
                        <BarSeries
                            series={data?.conversations?.creates}
                            label="Conversations started"
                        />
                    </TrendCard>

                    <TrendCard
                        title="Documents uploaded"
                        value={total(data?.documents?.uploads).toLocaleString()}
                    >
                        <BarSeries
                            series={data?.documents?.uploads}
                            label="Documents uploaded"
                        />
                    </TrendCard>

                    <TrendCard
                        title="Tokens used"
                        value={total(data?.tokens, 'tokens').toLocaleString()}
                    >
                        <BarSeries series={data?.tokens} valueKey="tokens" label="Tokens used" />
                    </TrendCard>

                    <TrendCard title="Sign-ins" value={total(data?.logins).toLocaleString()}>
                        <BarSeries series={data?.logins} label="Sign-ins" />
                    </TrendCard>
                </>
            )}
        </div>
    );
}
