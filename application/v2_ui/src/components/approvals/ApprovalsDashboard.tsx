// ApprovalsDashboard.tsx
// The Approvals page's Dashboard category: what is waiting on you, what you asked for, and
// what was decided recently, counted over the requests you can see.
//
// Every figure opens the list it counts, filtered through the address the same way a reviewer
// would filter it by hand. The server counts only requests the caller can see, through the
// same visibility rules as the request list.

import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { TriangleAlert } from 'lucide-react';
import {
    CHART_COLORS,
    ChartDataTable,
    ChartPanel,
    StatTile,
    WindowSelect,
    makeDatasets,
} from '../dashboard/DashboardParts';
import { cartesianOptions, StatsChart, type StatsChartConfigBuilder } from '../settings/StatsChart';
import { Skeleton } from '../ui/primitives';
import {
    errorMessage,
    fetchApprovalStats,
    formatDateTime,
    requestTypeLabel,
    type ApprovalStats,
} from '../../lib/approvalsApi';
import { readReviewWindow, REVIEW_WINDOWS, safeApprovalRequestHref, type ReviewWindow } from '../../lib/reviewCenter';

const OUTCOMES = [
    { key: 'approved', label: 'Approved', status: 'approved', color: 'blue' },
    { key: 'executed', label: 'Executed', status: 'executed', color: 'green' },
    { key: 'denied', label: 'Denied', status: 'denied', color: 'rose' },
    { key: 'failed', label: 'Failed', status: 'all', color: 'amber' },
    { key: 'expired', label: 'Expired', status: 'all', color: 'purple' },
] as const;

export function ApprovalsDashboard({ reloadKey }: { reloadKey: number }) {
    const [searchParams, setSearchParams] = useSearchParams();
    const days = readReviewWindow(searchParams.get('days'));
    const [stats, setStats] = useState<ApprovalStats | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError('');
        fetchApprovalStats(days, controller.signal)
            .then((next) => setStats(next))
            .catch((cause) => {
                if (!controller.signal.aborted) setError(errorMessage(cause, 'The approvals summary could not be loaded.'));
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

    const decided = stats?.decided_in_window ?? {};
    const decidedValues = OUTCOMES.map((outcome) => Number(decided[outcome.key] ?? 0));
    const outcomeConfig: StatsChartConfigBuilder = (theme) => ({
        type: 'bar',
        data: {
            labels: OUTCOMES.map((outcome) => outcome.label),
            datasets: makeDatasets([{ label: 'Requests', values: decidedValues, color: 'blue' }]).map((dataset) => ({
                ...dataset,
                backgroundColor: OUTCOMES.map((outcome) => CHART_COLORS[outcome.color].fill),
                borderColor: OUTCOMES.map((outcome) => CHART_COLORS[outcome.color].border),
            })),
        },
        options: cartesianOptions(theme, false),
    });

    return (
        <div className="h-full overflow-y-auto" data-testid="v2-approvals-dashboard">
            <div className="mx-auto max-w-6xl space-y-5 p-4 lg:p-6">
                <div className="flex flex-wrap items-end justify-between gap-3">
                    <p className="max-w-2xl text-sm text-text-2">
                        Counted over the requests you can see. Select a figure to open the requests it counts.
                    </p>
                    <WindowSelect id="approvals-dashboard-window" value={days} options={REVIEW_WINDOWS} onChange={setDays} />
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
                        <span className="sr-only">Loading the approvals summary</span>
                    </div>
                ) : stats ? (
                    <>
                        <section aria-label="Approval figures" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                            <StatTile
                                label="Waiting on me"
                                value={(stats.waiting_on_me ?? 0).toLocaleString()}
                                detail="Pending requests you can approve"
                                to="/approvals/all?show=mine"
                                testId="v2-approvals-dashboard-waiting"
                            />
                            <StatTile
                                label="Expiring within 24 hours"
                                value={(stats.expiring_within_24h ?? 0).toLocaleString()}
                                detail="Waiting on you, and denied automatically if nobody decides"
                                to="/approvals/all?show=mine&expiring=1"
                                testId="v2-approvals-dashboard-expiring"
                            />
                            <StatTile
                                label="My pending requests"
                                value={(stats.my_pending_requests ?? 0).toLocaleString()}
                                detail="Requests you raised that are still waiting"
                                to="/approvals/all?show=requested"
                                testId="v2-approvals-dashboard-mine"
                            />
                            <StatTile
                                label="Pending that you can see"
                                value={(stats.pending_visible ?? 0).toLocaleString()}
                                detail="Every pending request, including ones for other reviewers"
                                to="/approvals/all"
                                testId="v2-approvals-dashboard-pending"
                            />
                        </section>

                        <section className="grid gap-4 lg:grid-cols-2" aria-label="Approval breakdowns">
                            <ChartPanel title={`Decided in the last ${days} days`} description="Requests you can see, by outcome.">
                                <StatsChart
                                    buildConfig={outcomeConfig}
                                    signature={`approvals-outcomes-${days}-${decidedValues.join(',')}`}
                                    ariaLabel={`Requests decided in the last ${days} days by outcome: ${OUTCOMES.map((outcome, index) => `${outcome.label} ${decidedValues[index]}`).join(', ')}.`}
                                />
                                <ChartDataTable
                                    title="Decided requests"
                                    rowHeader="Outcome"
                                    dates={OUTCOMES.map((outcome) => outcome.label)}
                                    series={[{ label: 'Requests', values: decidedValues }]}
                                />
                                <ul className="mt-3 flex flex-wrap gap-2 text-xs">
                                    {OUTCOMES.filter((outcome) => outcome.status !== 'all').map((outcome) => (
                                        <li key={outcome.key}>
                                            <Link
                                                to={`/approvals/all?status=${outcome.status}`}
                                                className="rounded-full bg-surface-2 px-3 py-1 text-text-2 hover:text-text-1"
                                            >
                                                {outcome.label}: {Number(decided[outcome.key] ?? 0).toLocaleString()}
                                            </Link>
                                        </li>
                                    ))}
                                </ul>
                            </ChartPanel>

                            <ChartPanel title="Pending by type" description="Pending requests you can see.">
                                {stats.pending_by_type?.length ? (
                                    <ul className="divide-y divide-edge text-sm" data-testid="v2-approvals-dashboard-types">
                                        {stats.pending_by_type.map((entry) => (
                                            <li key={entry.request_type}>
                                                <Link
                                                    to={`/approvals/all?type=${encodeURIComponent(entry.request_type)}`}
                                                    className="flex items-center justify-between gap-3 py-2 text-text-1 hover:text-accent"
                                                >
                                                    <span>{requestTypeLabel(entry.request_type)}</span>
                                                    <span className="tabular-nums text-text-2">{entry.count.toLocaleString()}</span>
                                                </Link>
                                            </li>
                                        ))}
                                    </ul>
                                ) : (
                                    <p className="py-6 text-center text-sm text-text-3">Nothing is pending.</p>
                                )}
                            </ChartPanel>
                        </section>

                        <ChartPanel title="Oldest waiting on me" description="Pending the longest among requests you can approve.">
                            {stats.oldest_actionable?.length ? (
                                <ol className="divide-y divide-edge text-sm" data-testid="v2-approvals-dashboard-oldest">
                                    {stats.oldest_actionable.map((entry) => (
                                        <li key={entry.id}>
                                            <Link
                                                to={safeApprovalRequestHref(entry.id, entry.group_id)}
                                                className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 py-2 hover:text-accent"
                                            >
                                                <span className="font-medium text-text-1">
                                                    {requestTypeLabel(entry.request_type)}
                                                    {entry.group_name ? <span className="font-normal text-text-3"> · {entry.group_name}</span> : null}
                                                </span>
                                                <span className="text-xs text-text-3">
                                                    Requested {formatDateTime(entry.created_at)} · expires {formatDateTime(entry.expires_at)}
                                                </span>
                                            </Link>
                                        </li>
                                    ))}
                                </ol>
                            ) : (
                                <p className="py-6 text-center text-sm text-text-3">Nothing is waiting on you.</p>
                            )}
                        </ChartPanel>
                    </>
                ) : null}
            </div>
        </div>
    );
}
