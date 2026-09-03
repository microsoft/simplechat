// StatsTab.tsx
// The user's own activity: lifetime totals, day-by-day trends, storage, and their account.
//
// Two different kinds of number share this tab, and the distinction matters. The four cards
// at the top are *lifetime* totals from the cached metrics block, which is recalculated
// periodically — hence the note saying when. Everything below them describes a chosen window
// and is computed per request. Presenting them together without saying which is which would
// invite the reader to subtract one from the other.
//
// Charts are drawn with the vendored Chart.js, loaded on demand (see lib/chartRuntime.ts).
// The shapes are the classic profile page's: created-versus-deleted only reads as a
// comparison when the two are bars side by side, and a share of storage only reads as a share
// when it is a ring. Every byte the browser executes here is served from the app's own origin.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { clsx } from 'clsx';
import { CalendarRange, Download } from 'lucide-react';
import { api } from '../../lib/apiClient';
import { GlassButton, GlassPanel, Skeleton } from '../ui/primitives';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import {
    DEFAULT_STATS_WINDOW,
    STATS_WINDOWS,
    alignSeries,
    formatBytes,
    formatCompactNumber,
    formatRelativeTime,
    formatShortDate,
    isCustomWindow,
    resolveDateRange,
    statsWindowLabel,
    statsWindowQuery,
    sumSeries,
    validateCustomRange,
    type ActivityTrends,
    type StatsWindow,
    type UserMetrics,
    type UserSettingsWithMetrics,
} from '../../lib/userStats';
import {
    SERIES_COLORS,
    StatsChart,
    barDataset,
    cartesianOptions,
    lineDataset,
} from './StatsChart';
import { StatsExportDialog } from './StatsExportDialog';

function StatCard({ label, value, caption }: { label: string; value: string; caption?: string }) {
    return (
        <GlassPanel className="p-4">
            <p className="text-xs text-text-3">{label}</p>
            <p className="mt-1 text-2xl font-semibold text-text-1">{value}</p>
            {caption ? <p className="mt-0.5 text-[11px] text-text-3">{caption}</p> : null}
        </GlassPanel>
    );
}

function ChartCard({
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
            <div className="flex items-baseline justify-between gap-3">
                <h3 className="text-sm font-semibold text-text-1">{title}</h3>
                <span className="text-sm font-medium text-text-2">{value}</span>
            </div>
            <div className="mt-3">{children}</div>
        </GlassPanel>
    );
}

export function StatsTab() {
    const user = useBootstrapStore((state) => state.data?.user);

    const [statsWindow, setStatsWindow] = useState<StatsWindow>(DEFAULT_STATS_WINDOW);
    const [rangeOpen, setRangeOpen] = useState(false);
    const [draftStart, setDraftStart] = useState('');
    const [draftEnd, setDraftEnd] = useState('');
    const [rangeError, setRangeError] = useState<string | null>(null);

    const [data, setData] = useState<ActivityTrends | null>(null);
    const [metrics, setMetrics] = useState<UserMetrics | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [exporting, setExporting] = useState(false);

    const load = useCallback(async (selected: StatsWindow, signal: AbortSignal) => {
        setLoading(true);
        setError(null);
        try {
            // Requested together because the tab is misleading with only one of them: the
            // lifetime totals and the window's trends are read against each other.
            const [trends, settings] = await Promise.all([
                api.get<ActivityTrends>(
                    `/api/user/activity-trends?${statsWindowQuery(selected)}`,
                    signal,
                ),
                api.get<UserSettingsWithMetrics>('/api/user/settings', signal),
            ]);
            if (signal.aborted) {
                return;
            }
            setData(trends);
            setMetrics(settings?.settings?.metrics ?? {});
        } catch (caught) {
            if (signal.aborted) {
                return;
            }
            setError(caught instanceof Error ? caught.message : 'Failed to load your activity.');
        } finally {
            if (!signal.aborted) {
                setLoading(false);
            }
        }
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        void load(statsWindow, controller.signal);
        return () => controller.abort();
    }, [load, statsWindow]);

    const applyCustomRange = () => {
        const validation = validateCustomRange(draftStart, draftEnd);
        if (!validation.ok) {
            setRangeError(validation.error);
            return;
        }
        setRangeError(null);
        setStatsWindow(validation.window);
    };

    // The server's own description of what it resolved, which is the honest label for a
    // custom range it may have interpreted differently.
    const windowLabel = data?.window?.label || statsWindowLabel(statsWindow);
    const dateRange = useMemo(() => resolveDateRange(data, statsWindow), [data, statsWindow]);
    const labels = useMemo(() => dateRange.map(formatShortDate), [dateRange]);

    const logins = useMemo(() => alignSeries(data?.logins, dateRange), [data, dateRange]);
    const conversationCreates = useMemo(
        () => alignSeries(data?.conversations?.creates, dateRange),
        [data, dateRange],
    );
    const conversationDeletes = useMemo(
        () => alignSeries(data?.conversations?.deletes, dateRange),
        [data, dateRange],
    );
    const documentUploads = useMemo(
        () => alignSeries(data?.documents?.uploads, dateRange),
        [data, dateRange],
    );
    const documentDeletes = useMemo(
        () => alignSeries(data?.documents?.deletes, dateRange),
        [data, dateRange],
    );
    // Raw counts run into the millions over a 90-day window, which leaves the axis unreadable.
    const tokenMillions = useMemo(
        () => alignSeries(data?.tokens, dateRange, 'tokens').map((value) => value / 1000000),
        [data, dateRange],
    );

    const aiSearchSize = data?.storage?.ai_search_size ?? 0;
    const blobStorageSize = data?.storage?.storage_account_size ?? 0;
    const hasStorage = aiSearchSize > 0 || blobStorageSize > 0;

    // Charts rebuild on this rather than on array identity, which changes every render.
    const signature = useMemo(
        () => `${windowLabel}:${dateRange.length}:${dateRange[0] ?? ''}:${dateRange.at(-1) ?? ''}`,
        [windowLabel, dateRange],
    );

    const loginMetrics = metrics?.login_metrics ?? {};
    const chatMetrics = metrics?.chat_metrics ?? {};
    const documentMetrics = metrics?.document_metrics ?? {};

    return (
        <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap gap-1.5">
                    {STATS_WINDOWS.map((preset) => {
                        const active = !isCustomWindow(statsWindow) && statsWindow.days === preset.days;
                        return (
                            <button
                                key={preset.days}
                                type="button"
                                onClick={() => {
                                    setRangeError(null);
                                    setStatsWindow({ days: preset.days, startDate: '', endDate: '' });
                                }}
                                aria-pressed={active}
                                className={clsx(
                                    'rounded-lg border px-3 py-1.5 text-xs transition-colors',
                                    active
                                        ? 'border-accent bg-accent-soft font-medium text-accent'
                                        : 'border-edge text-text-2 hover:bg-surface-2',
                                )}
                            >
                                {preset.label}
                            </button>
                        );
                    })}
                    <button
                        type="button"
                        onClick={() => setRangeOpen((open) => !open)}
                        aria-expanded={rangeOpen}
                        aria-pressed={isCustomWindow(statsWindow)}
                        className={clsx(
                            'inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors',
                            isCustomWindow(statsWindow)
                                ? 'border-accent bg-accent-soft font-medium text-accent'
                                : 'border-edge text-text-2 hover:bg-surface-2',
                        )}
                    >
                        <CalendarRange size={13} />
                        Custom
                    </button>
                </div>

                <GlassButton type="button" size="sm" onClick={() => setExporting(true)} aria-haspopup="dialog">
                    <Download size={14} />
                    Export
                </GlassButton>
            </div>

            {rangeOpen && (
                <GlassPanel className="p-3">
                    <div className="flex flex-wrap items-end gap-2">
                        <label className="text-xs text-text-2">
                            Start
                            <input
                                type="date"
                                value={draftStart}
                                onChange={(event) => {
                                    setRangeError(null);
                                    setDraftStart(event.target.value);
                                }}
                                className="mt-1 block rounded-lg border border-edge bg-surface-sunken px-2 py-1.5 text-sm text-text-1"
                            />
                        </label>
                        <label className="text-xs text-text-2">
                            End
                            <input
                                type="date"
                                value={draftEnd}
                                onChange={(event) => {
                                    setRangeError(null);
                                    setDraftEnd(event.target.value);
                                }}
                                className="mt-1 block rounded-lg border border-edge bg-surface-sunken px-2 py-1.5 text-sm text-text-1"
                            />
                        </label>
                        <GlassButton type="button" variant="primary" size="sm" onClick={applyCustomRange}>
                            Apply
                        </GlassButton>
                    </div>
                    {rangeError && (
                        <p role="alert" className="mt-2 text-xs text-danger">
                            {rangeError}
                        </p>
                    )}
                </GlassPanel>
            )}

            {error ? (
                <p className="rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
                    {error}
                </p>
            ) : loading ? (
                <div className="space-y-2">
                    <Skeleton className="h-20 w-full" />
                    <Skeleton className="h-56 w-full" />
                    <Skeleton className="h-56 w-full" />
                </div>
            ) : (
                <>
                    <p className="text-xs text-text-3">
                        The four totals are cached figures,{' '}
                        {metrics?.calculated_at
                            ? `last worked out ${formatRelativeTime(metrics.calculated_at)}`
                            : 'not yet calculated for your account'}
                        . Everything below them covers {windowLabel.toLowerCase()}.
                    </p>

                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                        <StatCard
                            label="Total conversations"
                            value={formatCompactNumber(chatMetrics.total_conversations ?? 0)}
                        />
                        <StatCard
                            label="Total messages"
                            value={formatCompactNumber(chatMetrics.total_messages ?? 0)}
                        />
                        <StatCard
                            label="Total documents"
                            value={formatCompactNumber(documentMetrics.total_documents ?? 0)}
                        />
                        <StatCard
                            label="Total sign-ins"
                            value={formatCompactNumber(loginMetrics.total_logins ?? 0)}
                            caption={
                                loginMetrics.last_login
                                    ? `Last sign-in ${formatRelativeTime(loginMetrics.last_login)}`
                                    : 'No sign-in recorded'
                            }
                        />
                    </div>

                    <ChartCard title="Sign-in activity" value={sumSeries(data?.logins).toLocaleString()}>
                        <StatsChart
                            signature={`logins:${signature}`}
                            ariaLabel={`Sign-ins per day over ${windowLabel}`}
                            buildConfig={(theme) => ({
                                type: 'line',
                                data: {
                                    labels,
                                    datasets: [
                                        lineDataset(
                                            'Sign-ins',
                                            logins,
                                            SERIES_COLORS.logins.line,
                                            SERIES_COLORS.logins.fill,
                                        ),
                                    ],
                                },
                                options: cartesianOptions(theme, false),
                            })}
                        />
                    </ChartCard>

                    <ChartCard
                        title="Conversation activity"
                        value={`${sumSeries(data?.conversations?.creates).toLocaleString()} created`}
                    >
                        <StatsChart
                            signature={`conversations:${signature}`}
                            ariaLabel={`Conversations created and deleted per day over ${windowLabel}`}
                            buildConfig={(theme) => ({
                                type: 'bar',
                                data: {
                                    labels,
                                    datasets: [
                                        barDataset(
                                            'Created',
                                            conversationCreates,
                                            SERIES_COLORS.created.line,
                                            SERIES_COLORS.created.fill,
                                        ),
                                        barDataset(
                                            'Deleted',
                                            conversationDeletes,
                                            SERIES_COLORS.deleted.line,
                                            SERIES_COLORS.deleted.fill,
                                        ),
                                    ],
                                },
                                options: cartesianOptions(theme, true),
                            })}
                        />
                    </ChartCard>

                    <ChartCard
                        title="Document activity"
                        value={`${sumSeries(data?.documents?.uploads).toLocaleString()} uploaded`}
                    >
                        <StatsChart
                            signature={`documents:${signature}`}
                            ariaLabel={`Documents uploaded and deleted per day over ${windowLabel}`}
                            buildConfig={(theme) => ({
                                type: 'bar',
                                data: {
                                    labels,
                                    datasets: [
                                        barDataset(
                                            'Uploaded',
                                            documentUploads,
                                            SERIES_COLORS.uploaded.line,
                                            SERIES_COLORS.uploaded.fill,
                                        ),
                                        barDataset(
                                            'Deleted',
                                            documentDeletes,
                                            SERIES_COLORS.deleted.line,
                                            SERIES_COLORS.deleted.fill,
                                        ),
                                    ],
                                },
                                options: cartesianOptions(theme, true),
                            })}
                        />
                    </ChartCard>

                    <ChartCard title="Token usage" value={sumSeries(data?.tokens, 'tokens').toLocaleString()}>
                        <StatsChart
                            signature={`tokens:${signature}`}
                            ariaLabel={`Tokens used per day over ${windowLabel}, in millions`}
                            buildConfig={(theme) => {
                                const options = cartesianOptions(theme, false);
                                return {
                                    type: 'line',
                                    data: {
                                        labels,
                                        datasets: [
                                            lineDataset(
                                                'Tokens (millions)',
                                                tokenMillions,
                                                SERIES_COLORS.tokens.line,
                                                SERIES_COLORS.tokens.fill,
                                            ),
                                        ],
                                    },
                                    options: {
                                        ...options,
                                        scales: {
                                            ...options.scales,
                                            // Fractions of a million are the normal case, so
                                            // the shared integer ticks are dropped here, and
                                            // the axis has to name its unit or "0.5" means
                                            // nothing beside a total in the millions.
                                            y: {
                                                ...options.scales.y,
                                                ticks: { color: theme.text },
                                                title: {
                                                    display: true,
                                                    text: 'Millions of tokens',
                                                    color: theme.text,
                                                },
                                            },
                                        },
                                    },
                                };
                            }}
                        />
                    </ChartCard>

                    <GlassPanel className="p-4">
                        <div className="flex items-baseline justify-between gap-3">
                            <h3 className="text-sm font-semibold text-text-1">Storage used</h3>
                            <span className="text-sm font-medium text-text-2">
                                {formatBytes(aiSearchSize + blobStorageSize)}
                            </span>
                        </div>
                        {hasStorage ? (
                            <div className="mt-3">
                                <StatsChart
                                    signature={`storage:${aiSearchSize}:${blobStorageSize}`}
                                    ariaLabel={`Storage used: ${formatBytes(aiSearchSize)} in AI Search and ${formatBytes(blobStorageSize)} in blob storage`}
                                    buildConfig={(theme) => ({
                                        type: 'doughnut',
                                        data: {
                                            labels: ['AI Search', 'Blob storage'],
                                            datasets: [
                                                {
                                                    data: [aiSearchSize, blobStorageSize],
                                                    backgroundColor: [
                                                        SERIES_COLORS.aiSearch,
                                                        SERIES_COLORS.blobStorage,
                                                    ],
                                                    borderColor: theme.surface,
                                                    borderWidth: 2,
                                                },
                                            ],
                                        },
                                        options: {
                                            responsive: true,
                                            maintainAspectRatio: false,
                                            plugins: {
                                                legend: {
                                                    position: 'bottom',
                                                    labels: {
                                                        color: theme.text,
                                                        boxWidth: 10,
                                                        boxHeight: 10,
                                                        usePointStyle: true,
                                                    },
                                                },
                                            },
                                        },
                                    })}
                                />
                            </div>
                        ) : (
                            <p className="mt-2 text-xs text-text-3">
                                Nothing stored yet. Documents you upload to your workspace are counted
                                here.
                            </p>
                        )}
                    </GlassPanel>

                    <GlassPanel className="p-4">
                        <h3 className="text-sm font-semibold text-text-1">Account</h3>
                        <dl className="mt-3 grid gap-3 sm:grid-cols-2">
                            <div>
                                <dt className="text-xs text-text-3">Name</dt>
                                <dd className="text-sm font-medium text-text-1">
                                    {user?.display_name || 'Not available'}
                                </dd>
                            </div>
                            <div>
                                <dt className="text-xs text-text-3">Email</dt>
                                <dd className="text-sm font-medium text-text-1">
                                    {user?.email || 'Not available'}
                                </dd>
                            </div>
                            <div className="sm:col-span-2">
                                <dt className="text-xs text-text-3">User ID</dt>
                                <dd className="font-mono text-xs break-all text-text-2">
                                    {user?.id || 'Not available'}
                                </dd>
                            </div>
                        </dl>
                    </GlassPanel>
                </>
            )}

            {exporting && (
                <StatsExportDialog
                    initialWindow={statsWindow}
                    userName={user?.display_name || 'User'}
                    userEmail={user?.email || 'N/A'}
                    onClose={() => setExporting(false)}
                />
            )}
        </div>
    );
}
