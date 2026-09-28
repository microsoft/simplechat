// WorkspaceStatisticsSection.tsx
// The shared native Statistics section: a workspace's totals and day-by-day trends, exported to the
// classic CSV format. The group workspace (M7C, GroupStatisticsSection) reads
// /api/groups/<g>/insights/stats and the public workspace (M10C, PublicStatisticsSection)
// /api/public-workspaces/<w>/insights/stats, each through its own client; the two share one envelope,
// so their wording, export adapter and test ids are the only values on the scope.
//
// The charts and the window controls are the personal statistics tab's, reused directly: the same
// vendored Chart.js canvas, the same preset-and-custom window, and the same export dialog driven by a
// workspace adapter rather than forked. The workspace statistics envelope differs from the personal
// one -- document activity, token usage and a storage split, with no login or conversation history --
// so a small normaliser turns it into the chart inputs, and the export builds the classic
// `exportGroupStats` / `exportWorkspaceStats` CSV column for column. A read the server declines (a 503)
// is a retryable load error, never an empty chart that reads as "you have no activity".

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { BarChart3, CalendarRange, Download } from 'lucide-react';
import { GlassButton, GlassPanel, Skeleton } from '../../components/ui/primitives';
import { EmptyState } from '../../components/ui/primitives';
import { SectionIntro } from '../../components/workspace/primitives';
import { StatsChart } from '../../components/settings/StatsChart';
import { StatsExportDialog } from '../../components/settings/StatsExportDialog';
import {
    DEFAULT_STATS_WINDOW, STATS_WINDOWS, isCustomWindow, statsWindowLabel, statsWindowQuery,
    validateCustomRange, type StatsWindow,
} from '../../lib/userStats';
import {
    documentActivityConfig, groupStatSummaryCards, storageBreakdownConfig, tokenUsageConfig, validateGroupStatsRange,
} from '../../lib/groupStats';
import type { GroupStatsPayload, WorkspaceSettingsAdapter } from '../../lib/groupSettings';
import type { StatsExportAdapter } from '../../lib/userStats';

/**
 * Everything that differs between the group's Statistics section and the public workspace's. Every
 * data-testid is `${testIdPrefix}-<control>`.
 */
export interface WorkspaceStatisticsSectionScope {
    testIdPrefix: string;
    description: string;
    /** The load error when a read fails without a message of its own. */
    loadFailed: string;
    /** The classic CSV export for this workspace, loaded through its own client. */
    createExportAdapter: (adapter: WorkspaceSettingsAdapter) => StatsExportAdapter;
}

function StatCard({ label, value }: { label: string; value: string }) {
    return (
        <GlassPanel className="p-4">
            <p className="text-xs text-text-3">{label}</p>
            <p className="mt-1 text-2xl font-semibold text-text-1">{value}</p>
        </GlassPanel>
    );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
    return (
        <GlassPanel className="p-4">
            <h3 className="text-sm font-semibold text-text-1">{title}</h3>
            <div className="mt-3">{children}</div>
        </GlassPanel>
    );
}

export function WorkspaceStatisticsSection({
    scope, adapter,
}: {
    scope: WorkspaceStatisticsSectionScope;
    adapter: WorkspaceSettingsAdapter;
}) {
    const [statsWindow, setStatsWindow] = useState<StatsWindow>(DEFAULT_STATS_WINDOW);
    const [rangeOpen, setRangeOpen] = useState(false);
    const [draftStart, setDraftStart] = useState('');
    const [draftEnd, setDraftEnd] = useState('');
    const [rangeError, setRangeError] = useState<string | null>(null);

    const [stats, setStats] = useState<GroupStatsPayload | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [reloadToken, setReloadToken] = useState(0);
    const [exporting, setExporting] = useState(false);

    const exportAdapter = useMemo(() => scope.createExportAdapter(adapter), [scope, adapter]);
    // The loader keeps its original dependencies, so it reads the scope's fallback through a ref.
    const loadFailedRef = useRef(scope.loadFailed);
    loadFailedRef.current = scope.loadFailed;

    const load = useCallback(async (selected: StatsWindow, signal: AbortSignal) => {
        setLoading(true);
        setError('');
        try {
            const next = await adapter.readStats(statsWindowQuery(selected), signal);
            if (!signal.aborted) setStats(next);
        } catch (caught) {
            if (signal.aborted) return;
            setStats(null);
            setError(caught instanceof Error ? caught.message : loadFailedRef.current);
        } finally {
            if (!signal.aborted) setLoading(false);
        }
    }, [adapter]);

    useEffect(() => {
        const controller = new AbortController();
        void load(statsWindow, controller.signal);
        return () => controller.abort();
    }, [load, statsWindow, reloadToken]);

    const applyCustomRange = () => {
        const validation = validateCustomRange(draftStart, draftEnd);
        if (!validation.ok) {
            setRangeError(validation.error);
            return;
        }
        // Both workspace scopes also cap a custom range at 366 days between 2000 and 9998, so a request
        // that could only 400 is refused here with the server's own message.
        const bounded = validateGroupStatsRange(validation.window);
        if (bounded) {
            setRangeError(bounded);
            return;
        }
        setRangeError(null);
        setStatsWindow(validation.window);
    };

    const windowLabel = stats?.window?.label || statsWindowLabel(statsWindow);
    const signature = useMemo(
        () => `${windowLabel}:${stats?.documentActivity.labels.length ?? 0}:${stats?.tokenUsage.labels.length ?? 0}`,
        [windowLabel, stats],
    );
    const cards = useMemo(() => (stats ? groupStatSummaryCards(stats) : []), [stats]);

    return (
        <div className="space-y-3" data-testid={`${scope.testIdPrefix}-section`}>
            <SectionIntro title="Statistics"
                description={scope.description} />

            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap gap-1.5">
                    {STATS_WINDOWS.map((preset) => {
                        const active = !isCustomWindow(statsWindow) && statsWindow.days === preset.days;
                        return (
                            <button key={preset.days} type="button" aria-pressed={active}
                                data-testid={`${scope.testIdPrefix}-window-${preset.days}`}
                                onClick={() => { setRangeError(null); setStatsWindow({ days: preset.days, startDate: '', endDate: '' }); }}
                                className={clsx(
                                    'rounded-lg border px-3 py-1.5 text-xs transition-colors',
                                    active ? 'border-accent bg-accent-soft font-medium text-accent'
                                        : 'border-edge text-text-2 hover:bg-surface-2',
                                )}>
                                {preset.label}
                            </button>
                        );
                    })}
                    <button type="button" onClick={() => setRangeOpen((open) => !open)}
                        aria-expanded={rangeOpen} aria-pressed={isCustomWindow(statsWindow)}
                        data-testid={`${scope.testIdPrefix}-window-custom`}
                        className={clsx(
                            'inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors',
                            isCustomWindow(statsWindow) ? 'border-accent bg-accent-soft font-medium text-accent'
                                : 'border-edge text-text-2 hover:bg-surface-2',
                        )}>
                        <CalendarRange size={13} />Custom
                    </button>
                </div>
                <GlassButton type="button" size="sm" onClick={() => setExporting(true)} aria-haspopup="dialog"
                    data-testid={`${scope.testIdPrefix}-export`}>
                    <Download size={14} />Export
                </GlassButton>
            </div>

            {rangeOpen ? (
                <GlassPanel className="p-3">
                    <div className="flex flex-wrap items-end gap-2">
                        <label className="text-xs text-text-2">
                            Start
                            <input type="date" value={draftStart} data-testid={`${scope.testIdPrefix}-start`}
                                onChange={(event) => { setRangeError(null); setDraftStart(event.target.value); }}
                                className="mt-1 block rounded-lg border border-edge bg-surface-sunken px-2 py-1.5 text-sm text-text-1" />
                        </label>
                        <label className="text-xs text-text-2">
                            End
                            <input type="date" value={draftEnd} data-testid={`${scope.testIdPrefix}-end`}
                                onChange={(event) => { setRangeError(null); setDraftEnd(event.target.value); }}
                                className="mt-1 block rounded-lg border border-edge bg-surface-sunken px-2 py-1.5 text-sm text-text-1" />
                        </label>
                        <GlassButton type="button" variant="primary" size="sm" onClick={applyCustomRange}
                            data-testid={`${scope.testIdPrefix}-apply`}>Apply</GlassButton>
                    </div>
                    {rangeError ? <p role="alert" className="mt-2 text-xs text-danger">{rangeError}</p> : null}
                </GlassPanel>
            ) : null}

            {error ? (
                <EmptyState icon={<BarChart3 size={28} />} title="Statistics unavailable" description={error}
                    action={<GlassButton size="sm" onClick={() => setReloadToken((value) => value + 1)}>Retry</GlassButton>} />
            ) : loading ? (
                <div className="space-y-2" aria-busy="true">
                    <Skeleton className="h-20 w-full" /><Skeleton className="h-56 w-full" /><Skeleton className="h-56 w-full" />
                </div>
            ) : stats ? (
                <>
                    <p className="text-xs text-text-3">Covering {windowLabel.toLowerCase()}.</p>
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                        {cards.map((card) => <StatCard key={card.key} label={card.label} value={card.value} />)}
                    </div>
                    <ChartCard title="Document activity">
                        <StatsChart buildConfig={documentActivityConfig(stats)} signature={`docs:${signature}`}
                            ariaLabel="Documents uploaded and deleted per day" />
                    </ChartCard>
                    <ChartCard title="Token usage">
                        <StatsChart buildConfig={tokenUsageConfig(stats)} signature={`tokens:${signature}`}
                            ariaLabel="Total tokens used per day" />
                    </ChartCard>
                    <ChartCard title="Storage">
                        <StatsChart buildConfig={storageBreakdownConfig(stats)} signature={`storage:${signature}`}
                            ariaLabel="Storage split between AI Search and blob storage" className="h-56" />
                    </ChartCard>
                </>
            ) : null}

            {exporting ? (
                <StatsExportDialog initialWindow={statsWindow} userName="" userEmail="" adapter={exportAdapter}
                    onClose={() => setExporting(false)} />
            ) : null}
        </div>
    );
}
