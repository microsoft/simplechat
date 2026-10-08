// FeedbackDashboard.tsx
// The Feedback section's dashboard: what users are saying about AI responses over the last
// 7, 30 or 90 days, and what is still waiting for a reviewer.
//
// Every figure opens the feedback workbench filtered to the records it counts. Figures for
// the window count archived feedback too, so their links include archived records; what
// waits for review is active feedback only, as the workbench lists it by default.

import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { TriangleAlert } from 'lucide-react';
import {
    ChartDataTable,
    ChartPanel,
    makeDatasets,
    stackedBarOptions,
    StatTile,
    WindowSelect,
    type ChartColor,
} from '../../components/dashboard/DashboardParts';
import { StatsChart, type StatsChartConfigBuilder } from '../../components/settings/StatsChart';
import { Skeleton } from '../../components/ui/primitives';
import {
    DEFAULT_FEEDBACK_FILTERS,
    FEEDBACK_RATINGS,
    feedbackFilterParams,
    formatReviewDate,
    readReviewWindow,
    REVIEW_WINDOWS,
    reviewExcerpt,
    safeFeedbackQueueHref,
    safeReviewRecordHref,
    type ReviewWindow,
} from '../../lib/reviewCenter';
import { errorText, fetchFeedbackStats, type FeedbackStats } from '../../lib/reviewCenterApi';

const RATING_COLORS: Readonly<Record<string, ChartColor>> = {
    Positive: 'green',
    Negative: 'rose',
    Neutral: 'blue',
    Unknown: 'purple',
};

export function FeedbackDashboard({ reloadKey }: { reloadKey: number }) {
    const [searchParams, setSearchParams] = useSearchParams();
    const days = readReviewWindow(searchParams.get('days'));
    const [stats, setStats] = useState<FeedbackStats | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError('');
        fetchFeedbackStats(days, controller.signal)
            .then((next) => setStats(next))
            .catch((cause) => {
                if (!controller.signal.aborted) setError(errorText(cause, 'The feedback summary could not be loaded.'));
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoading(false);
            });
        return () => controller.abort();
    }, [days, reloadKey]);

    const setDays = (value: ReviewWindow) => {
        const next = new URLSearchParams(searchParams);
        next.set('days', value);
        setSearchParams(next, { replace: true });
    };

    const daily = stats?.daily_by_rating;
    const series = (daily?.series ?? []).map((entry, index) => ({
        label: entry.key,
        values: entry.counts,
        color: RATING_COLORS[entry.key] ?? (['amber', 'cyan'] as ChartColor[])[index % 2],
    }));
    const dailyConfig: StatsChartConfigBuilder = (theme) => ({
        type: 'bar',
        data: { labels: daily?.dates ?? [], datasets: makeDatasets(series) },
        options: stackedBarOptions(theme),
    });
    const totals = series.map((entry) => ({ label: entry.label, total: entry.values.reduce((sum, value) => sum + value, 0) }));
    const rate = stats?.acknowledgement_rate;

    return (
        <div className="h-full overflow-y-auto" data-testid="v2-feedback-dashboard">
            <div className="mx-auto max-w-6xl space-y-5 p-4 lg:p-6">
                <div className="flex flex-wrap items-end justify-between gap-3">
                    <p className="max-w-2xl text-sm text-text-2">
                        Select a figure to open the feedback it counts in the workbench.
                    </p>
                    <WindowSelect id="feedback-dashboard-window" value={days} options={REVIEW_WINDOWS} onChange={setDays} />
                </div>

                {error ? (
                    <p role="alert" className="flex items-start gap-2 rounded-xl bg-danger-soft p-3 text-sm text-danger">
                        <TriangleAlert size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
                        {error}
                    </p>
                ) : null}

                {loading && !stats ? (
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-busy="true">
                        {Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-24 w-full" />)}
                        <span className="sr-only">Loading the feedback summary</span>
                    </div>
                ) : stats ? (
                    <>
                        <section aria-label="Feedback figures" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                            <StatTile
                                label="Awaiting review"
                                value={(stats.awaiting_review_count ?? 0).toLocaleString()}
                                detail="Active feedback no reviewer has acknowledged"
                                to={safeFeedbackQueueHref({ ack: 'false' })}
                                testId="v2-feedback-dashboard-awaiting"
                            />
                            <StatTile
                                label={`Negative in the last ${days} days`}
                                value={(stats.negative_count_in_window ?? 0).toLocaleString()}
                                detail={`Of ${(stats.received_count ?? 0).toLocaleString()} received in the period`}
                                to={safeFeedbackQueueHref({ type: 'Negative', days, archive: 'all' })}
                                testId="v2-feedback-dashboard-negative"
                            />
                            <StatTile
                                label="Acknowledgement rate"
                                value={rate === null || rate === undefined ? 'None received' : `${Math.round(rate * 100)}%`}
                                detail={`${(stats.acknowledged_count_in_window ?? 0).toLocaleString()} of ${(stats.received_count ?? 0).toLocaleString()} from the last ${days} days acknowledged`}
                                to={safeFeedbackQueueHref({ ack: 'true', days, archive: 'all' })}
                                testId="v2-feedback-dashboard-rate"
                            />
                            <StatTile
                                label="Archived"
                                value={(stats.archived_count ?? 0).toLocaleString()}
                                detail="Reviewed feedback kept out of the active list"
                                to={safeFeedbackQueueHref({ archive: 'archived' })}
                                testId="v2-feedback-dashboard-archived"
                            />
                        </section>

                        <ChartPanel
                            title={`Feedback received in the last ${days} days`}
                            description="Each day's feedback by rating, archived feedback included."
                        >
                            <StatsChart
                                buildConfig={dailyConfig}
                                signature={`feedback-daily-${days}-${series.map((entry) => `${entry.label}:${entry.values.join(',')}`).join('|')}`}
                                ariaLabel={`Feedback received per day over the last ${days} days by rating: ${totals.map((entry) => `${entry.label} ${entry.total}`).join(', ') || 'none'}.`}
                            />
                            <ChartDataTable
                                title="Feedback received"
                                dates={daily?.dates ?? []}
                                series={series.map((entry) => ({ label: entry.label, values: entry.values }))}
                            />
                            {totals.length ? (
                                <ul className="mt-3 flex flex-wrap gap-2 text-xs" aria-label="Open feedback by rating">
                                    {totals.map((entry) => {
                                        const rating = FEEDBACK_RATINGS.find((value) => value === entry.label);
                                        const text = `${entry.label}: ${entry.total.toLocaleString()}`;
                                        return (
                                            <li key={entry.label}>
                                                {rating ? (
                                                    <Link
                                                        to={safeFeedbackQueueHref({ type: rating, days, archive: 'all' })}
                                                        className="rounded-full bg-surface-2 px-3 py-1 text-text-2 hover:text-text-1"
                                                    >
                                                        {text}
                                                    </Link>
                                                ) : (
                                                    <span className="rounded-full bg-surface-2 px-3 py-1 text-text-3">{text}</span>
                                                )}
                                            </li>
                                        );
                                    })}
                                </ul>
                            ) : null}
                        </ChartPanel>

                        <ChartPanel title="Oldest awaiting review" description="Active feedback waiting the longest for a reviewer.">
                            {stats.oldest_awaiting?.length ? (
                                <ol className="divide-y divide-edge text-sm" data-testid="v2-feedback-dashboard-oldest">
                                    {stats.oldest_awaiting.map((entry) => (
                                        <li key={entry.id}>
                                            <Link
                                                to={safeReviewRecordHref(
                                                    'feedback',
                                                    entry.id,
                                                    feedbackFilterParams({ ...DEFAULT_FEEDBACK_FILTERS, ack: 'false' }),
                                                )}
                                                className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 py-2 hover:text-accent"
                                            >
                                                <span className="min-w-0 font-medium text-text-1">
                                                    {reviewExcerpt(entry.promptExcerpt, 90) || 'No prompt captured'}
                                                </span>
                                                <span className="text-xs text-text-3">
                                                    {[entry.feedbackType || 'Unrated', entry.userDisplayName || entry.userId || 'Unknown user', formatReviewDate(entry.timestamp)].join(' · ')}
                                                </span>
                                            </Link>
                                        </li>
                                    ))}
                                </ol>
                            ) : (
                                <p className="py-6 text-center text-sm text-text-3">Nothing is waiting for review.</p>
                            )}
                        </ChartPanel>
                    </>
                ) : null}
            </div>
        </div>
    );
}
