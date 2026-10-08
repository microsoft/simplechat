// SafetyDashboard.tsx
// The Safety section's dashboard: violations flagged over the last 7, 30 or 90 days, the
// remediation waiting on a second reviewer, who is restricted now, whether warned users
// have acknowledged their warnings, and chat content still waiting for a check.
//
// Every figure opens the list it counts: the violations workbench filtered through its
// address, the Safety remediation requests on the Approvals page, or the unchecked chat
// content queue. Figures for the window count archived violations too, so their links
// include archived records.

import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { TriangleAlert } from 'lucide-react';
import {
    CHART_COLOR_ORDER,
    CHART_COLORS,
    ChartDataTable,
    ChartPanel,
    makeDatasets,
    stackedBarOptions,
    StatTile,
    WindowSelect,
} from '../../components/dashboard/DashboardParts';
import { cartesianOptions, StatsChart, type StatsChartConfigBuilder } from '../../components/settings/StatsChart';
import { Skeleton } from '../../components/ui/primitives';
import {
    LEGACY_ESCALATE_ACTION,
    LEGACY_ESCALATE_LABEL,
    readReviewWindow,
    REVIEW_WINDOWS,
    safeReviewViewHref,
    safeViolationsHref,
    safetyActionLabel,
    type ReviewWindow,
} from '../../lib/reviewCenter';
import { errorText, fetchSafetyStats, type SafetyStats } from '../../lib/reviewCenterApi';

function countText(value: number | null | undefined): string {
    return value === null || value === undefined ? 'Not available' : value.toLocaleString();
}

function severityLabel(severity: number | null): string {
    return severity === null ? 'Not recorded' : `Severity ${severity}`;
}

/** One bar per category of a breakdown, each with its own colour. */
function breakdownConfig(labels: string[], values: number[], seriesLabel: string): StatsChartConfigBuilder {
    return (theme) => ({
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: seriesLabel,
                data: values,
                backgroundColor: labels.map((_, index) => CHART_COLORS[CHART_COLOR_ORDER[index % CHART_COLOR_ORDER.length]].fill),
                borderColor: labels.map((_, index) => CHART_COLORS[CHART_COLOR_ORDER[index % CHART_COLOR_ORDER.length]].border),
                borderWidth: 2,
                borderRadius: 3,
            }],
        },
        options: cartesianOptions(theme, false),
    });
}

const CHIP_CLASS = 'rounded-full bg-surface-2 px-3 py-1 text-text-2 hover:text-text-1';

export function SafetyDashboard({ reloadKey }: { reloadKey: number }) {
    const [searchParams, setSearchParams] = useSearchParams();
    const days = readReviewWindow(searchParams.get('days'));
    const [stats, setStats] = useState<SafetyStats | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError('');
        fetchSafetyStats(days, controller.signal)
            .then((next) => setStats(next))
            .catch((cause) => {
                if (!controller.signal.aborted) setError(errorText(cause, 'The safety summary could not be loaded.'));
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

    const daily = stats?.daily_by_category;
    const categorySeries = (daily?.series ?? []).map((entry, index) => ({
        label: entry.key,
        values: entry.counts,
        color: CHART_COLOR_ORDER[index % CHART_COLOR_ORDER.length],
    }));
    const categoryTotals = categorySeries.map((entry) => ({
        label: entry.label,
        total: entry.values.reduce((sum, value) => sum + value, 0),
    }));
    const dailyConfig: StatsChartConfigBuilder = (theme) => ({
        type: 'bar',
        data: { labels: daily?.dates ?? [], datasets: makeDatasets(categorySeries) },
        options: stackedBarOptions(theme),
    });
    const severities = stats?.severity_mix ?? [];
    const actions = stats?.action_mix ?? [];
    const legacyEscalations = stats?.escalate_count ?? 0;

    return (
        <div className="h-full overflow-y-auto" data-testid="v2-safety-dashboard">
            <div className="mx-auto max-w-6xl space-y-5 p-4 lg:p-6">
                <div className="flex flex-wrap items-end justify-between gap-3">
                    <p className="max-w-2xl text-sm text-text-2">
                        Select a figure to open what it counts.
                    </p>
                    <WindowSelect id="safety-dashboard-window" value={days} options={REVIEW_WINDOWS} onChange={setDays} />
                </div>

                {error ? (
                    <p role="alert" className="flex items-start gap-2 rounded-xl bg-danger-soft p-3 text-sm text-danger">
                        <TriangleAlert size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
                        {error}
                    </p>
                ) : null}

                {loading && !stats ? (
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true">
                        {Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-24 w-full" />)}
                        <span className="sr-only">Loading the safety summary</span>
                    </div>
                ) : stats ? (
                    <>
                        <section aria-label="Safety figures" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                            <StatTile
                                label="Open violations"
                                value={countText(stats.open_count)}
                                detail="New or in review, not archived"
                                to={safeViolationsHref({ status: 'open' })}
                                testId="v2-safety-dashboard-open"
                            />
                            <StatTile
                                label="Remediation awaiting approval"
                                value={countText(stats.pending_remediation_count)}
                                detail="Suspensions and blocks waiting for another eligible reviewer"
                                to="/approvals/safety-remediation"
                                testId="v2-safety-dashboard-pending"
                            />
                            <StatTile
                                label="Users restricted now"
                                value={countText(stats.restricted_user_count)}
                                detail="Suspended or blocked through a violation review"
                                to={safeViolationsHref({ restricted: true, archive: 'all' })}
                                testId="v2-safety-dashboard-restricted"
                            />
                            <StatTile
                                label={`Warnings sent in the last ${days} days`}
                                value={countText(stats.warnings_sent_count)}
                                detail={`${(stats.warnings_acknowledged_count ?? 0).toLocaleString()} acknowledged · ${(stats.warnings_pending_count ?? 0).toLocaleString()} awaiting acknowledgment in all`}
                                to={safeViolationsHref({ warning: 'pending', archive: 'all' })}
                                testId="v2-safety-dashboard-warnings"
                            />
                            <StatTile
                                label="Unchecked chat content"
                                value={countText(stats.unchecked_chat_count)}
                                detail="Messages whose required checks could not finish"
                                to={safeReviewViewHref('safety', 'unchecked')}
                                testId="v2-safety-dashboard-unchecked"
                            />
                            <StatTile
                                label={`Flagged in the last ${days} days`}
                                value={countText(stats.received_count)}
                                detail="Every violation recorded in the period"
                                to={safeViolationsHref({ days, archive: 'all' })}
                                testId="v2-safety-dashboard-received"
                            />
                        </section>

                        <ChartPanel
                            title={`Violations per day by category, last ${days} days`}
                            description="A violation that triggered several categories counts once in each."
                        >
                            <StatsChart
                                buildConfig={dailyConfig}
                                signature={`safety-daily-${days}-${categorySeries.map((entry) => `${entry.label}:${entry.values.join(',')}`).join('|')}`}
                                ariaLabel={`Violations per day over the last ${days} days by category: ${categoryTotals.map((entry) => `${entry.label} ${entry.total}`).join(', ') || 'none'}.`}
                            />
                            <ChartDataTable
                                title="Violations by category"
                                dates={daily?.dates ?? []}
                                series={categorySeries.map((entry) => ({ label: entry.label, values: entry.values }))}
                            />
                            {categoryTotals.length ? (
                                <ul className="mt-3 flex flex-wrap gap-2 text-xs" aria-label="Open violations by category">
                                    {categoryTotals.map((entry) => (
                                        <li key={entry.label}>
                                            {entry.label === 'Uncategorized' ? (
                                                <span className="rounded-full bg-surface-2 px-3 py-1 text-text-3">
                                                    {entry.label}: {entry.total.toLocaleString()}
                                                </span>
                                            ) : (
                                                <Link to={safeViolationsHref({ category: entry.label, days, archive: 'all' })} className={CHIP_CLASS}>
                                                    {entry.label}: {entry.total.toLocaleString()}
                                                </Link>
                                            )}
                                        </li>
                                    ))}
                                </ul>
                            ) : null}
                        </ChartPanel>

                        <section className="grid gap-4 lg:grid-cols-2" aria-label="Safety breakdowns">
                            <ChartPanel title="Severity" description={`The highest severity of each violation in the last ${days} days.`}>
                                <StatsChart
                                    buildConfig={breakdownConfig(
                                        severities.map((entry) => severityLabel(entry.severity)),
                                        severities.map((entry) => entry.count),
                                        'Violations',
                                    )}
                                    signature={`safety-severity-${days}-${severities.map((entry) => `${entry.severity}:${entry.count}`).join(',')}`}
                                    ariaLabel={`Violations by highest severity: ${severities.map((entry) => `${severityLabel(entry.severity)} ${entry.count}`).join(', ') || 'none'}.`}
                                />
                                <ChartDataTable
                                    title="Severity"
                                    rowHeader="Severity"
                                    dates={severities.map((entry) => severityLabel(entry.severity))}
                                    series={[{ label: 'Violations', values: severities.map((entry) => entry.count) }]}
                                />
                                {severities.some((entry) => entry.severity !== null) ? (
                                    <ul className="mt-3 flex flex-wrap gap-2 text-xs" aria-label="Open violations by severity">
                                        {severities.filter((entry) => entry.severity !== null).map((entry) => (
                                            <li key={String(entry.severity)}>
                                                <Link to={safeViolationsHref({ severity: String(entry.severity), days, archive: 'all' })} className={CHIP_CLASS}>
                                                    {severityLabel(entry.severity)}: {entry.count.toLocaleString()}
                                                </Link>
                                            </li>
                                        ))}
                                    </ul>
                                ) : null}
                            </ChartPanel>

                            <ChartPanel title="Action taken" description={`The action recorded on each violation in the last ${days} days.`}>
                                <StatsChart
                                    buildConfig={breakdownConfig(
                                        actions.map((entry) => safetyActionLabel(entry.action)),
                                        actions.map((entry) => entry.count),
                                        'Violations',
                                    )}
                                    signature={`safety-actions-${days}-${actions.map((entry) => `${entry.action}:${entry.count}`).join(',')}`}
                                    ariaLabel={`Violations by action: ${actions.map((entry) => `${safetyActionLabel(entry.action)} ${entry.count}`).join(', ') || 'none'}.`}
                                />
                                <ChartDataTable
                                    title="Action taken"
                                    rowHeader="Action"
                                    dates={actions.map((entry) => safetyActionLabel(entry.action))}
                                    series={[{ label: 'Violations', values: actions.map((entry) => entry.count) }]}
                                />
                                {actions.length ? (
                                    <ul className="mt-3 flex flex-wrap gap-2 text-xs" aria-label="Open violations by action">
                                        {actions.map((entry) => (
                                            <li key={entry.action}>
                                                <Link to={safeViolationsHref({ action: entry.action, days, archive: 'all' })} className={CHIP_CLASS}>
                                                    {safetyActionLabel(entry.action)}: {entry.count.toLocaleString()}
                                                </Link>
                                            </li>
                                        ))}
                                    </ul>
                                ) : null}
                                {legacyEscalations > 0 ? (
                                    <p className="mt-3 text-xs text-text-3" data-testid="v2-safety-dashboard-legacy-escalate">
                                        <Link to={safeViolationsHref({ action: LEGACY_ESCALATE_ACTION })} className="text-accent underline underline-offset-2">
                                            {legacyEscalations.toLocaleString()} active {legacyEscalations === 1 ? 'violation is' : 'violations are'} {LEGACY_ESCALATE_LABEL.toLowerCase()}
                                        </Link>
                                        . Escalate can no longer be chosen; those records keep it until a reviewer changes the action.
                                    </p>
                                ) : null}
                            </ChartPanel>
                        </section>

                        <ChartPanel title="Repeat users" description={`Users with two or more violations in the last ${days} days.`}>
                            {stats.repeat_users?.length ? (
                                <ol className="divide-y divide-edge text-sm" data-testid="v2-safety-dashboard-repeat">
                                    {stats.repeat_users.map((entry) => (
                                        <li key={entry.user_id}>
                                            <Link
                                                to={safeViolationsHref({ userId: entry.user_id, days, archive: 'all' })}
                                                className="flex items-center justify-between gap-3 py-2 text-text-1 hover:text-accent"
                                            >
                                                <span className="min-w-0 truncate">
                                                    {entry.display_name || entry.email || entry.user_id}
                                                    {entry.display_name && entry.email ? <span className="text-text-3"> · {entry.email}</span> : null}
                                                </span>
                                                <span className="shrink-0 tabular-nums text-text-2">{entry.count.toLocaleString()} violations</span>
                                            </Link>
                                        </li>
                                    ))}
                                </ol>
                            ) : (
                                <p className="py-6 text-center text-sm text-text-3">No user has more than one violation in this period.</p>
                            )}
                        </ChartPanel>
                    </>
                ) : null}
            </div>
        </div>
    );
}
