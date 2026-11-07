// ActivityLogsSection.tsx
// THESIS: The toolbar is the investigation's state, and the log is visible in the first viewport.
// OWN-WORLD: Inherit the Control Center's semantic glass surfaces, blue accent, and workhorse type.
// STORY: Narrow by time, activity, person or workspace with pills; read who did what, where; open a record for its evidence.
// FIRST VIEWPORT: Header with views and export, one row of filter pills, a slim trend strip, then log rows.
// FORM: Operate; Azure-portal filter pills over a dense table where every name is a cross-filter.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Download, RefreshCw } from 'lucide-react';
import { api, apiUrl, CREDENTIALS_MODE } from '../../lib/apiClient';
import {
    apiParams, filterParams, humanize, isDefaultFilters, parseActivityLogPrefs, presetDates, readFilters, todayUtc,
    type ActivityFilterLabels, type ActivityFilters, type ActivityLogPrefs, type ActivityPage, type ActivitySummary,
    type ActivityTypeOption, type ActivityWorkspaceRef, type WorkspaceType,
} from '../../lib/activityLogs';
import {
    legacyActivityViewsKey, mergeImportedActivityViews, parseActivitySavedViews, readLegacyActivityViews,
    removeActivitySavedView, renameActivitySavedView, upsertActivitySavedView,
} from '../../lib/activityLogSavedViews';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { toast } from '../../stores/toastStore';
import { useUserSettingsStore } from '../../stores/userSettingsStore';
import { GlassButton } from '../ui/primitives';
import { ActivityDetailDrawer } from './activityLogs/ActivityDetailDrawer';
import { ActivityFilterBar, type FilterChangeOptions } from './activityLogs/ActivityFilterBar';
import { ActivityTable, fallbackPresentation } from './activityLogs/ActivityTable';
import { ActivityTrendStrip } from './activityLogs/ActivityTrendStrip';
import { ActivityViewsMenu } from './activityLogs/ActivityViewsMenu';

const PAGE_SIZE = 50;

type FilterPillId = 'date' | 'activity' | 'person' | 'workspace';

/**
 * A filter chosen from the log or the drawer replaces the rows it was chosen from, so focus
 * moves to that filter's pill, which stays on screen and now shows the new value.
 */
function focusPill(pill: FilterPillId) {
    requestAnimationFrame(() => {
        const pills = Array.from(document.querySelectorAll<HTMLElement>('[data-filter-pill]'));
        pills.find((element) => element.dataset.filterPill === pill)?.focus();
    });
}

interface KnownNames {
    people: Record<string, { name: string; email: string }>;
    workspaces: Record<string, string>;
}

export function ActivityLogsSection() {
    const [params, setParams] = useSearchParams();
    const paramString = params.toString();
    // Relative ranges ("Last 7 days") end today in UTC. Changing a filter re-reads the clock;
    // `day` makes Refresh, an export or returning to the tab re-read it too, so a page left
    // open past UTC midnight does not keep querying yesterday's window.
    const [day, setDay] = useState(() => todayUtc());
    const filters = useMemo(() => readFilters(new URLSearchParams(paramString)), [paramString, day]);
    const canonical = filterParams(filters).toString();
    const query = apiParams(filters).toString();
    const [paging, setPaging] = useState<{ query: string; cursors: (string | null)[]; index: number }>({ query, cursors: [null], index: 0 });
    const currentPaging = paging.query === query ? paging : { query, cursors: [null], index: 0 };
    const cursor = currentPaging.cursors[currentPaging.index];
    const [data, setData] = useState<ActivityPage | null>(null);
    const [summary, setSummary] = useState<ActivitySummary | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [summaryError, setSummaryError] = useState('');
    const [selected, setSelected] = useState<number | null>(null);
    const [refresh, setRefresh] = useState(0);
    const [exporting, setExporting] = useState(false);
    const [exportError, setExportError] = useState('');
    const [typeCatalog, setTypeCatalog] = useState<ActivityTypeOption[]>([]);
    const [known, setKnown] = useState<KnownNames>({ people: {}, workspaces: {} });
    const userId = useBootstrapStore((state) => state.data?.user.id ?? '');
    const settings = useUserSettingsStore((state) => state.settings);
    const settingsLoading = useUserSettingsStore((state) => state.loading);
    const settingsLoadError = useUserSettingsStore((state) => state.error);
    const saveError = useUserSettingsStore((state) => state.saveError);
    const updateSettings = useUserSettingsStore((state) => state.update);
    const flushSettings = useUserSettingsStore((state) => state.flush);
    const prefs = parseActivityLogPrefs(settings.v2ActivityLogPrefs);
    const savedViews = useMemo(() => parseActivitySavedViews(settings.v2ActivityLogSavedViews), [settings.v2ActivityLogSavedViews]);
    const importStarted = useRef(false);

    // Views saved by the browser-only version move to the account once, then leave this browser.
    useEffect(() => {
        if (importStarted.current || settingsLoading || settingsLoadError || !userId) return;
        let legacy: ReturnType<typeof readLegacyActivityViews> = [];
        try {
            legacy = readLegacyActivityViews(window.localStorage, userId);
        } catch {
            return;
        }
        importStarted.current = true;
        if (!legacy.length) return;
        updateSettings({ v2ActivityLogSavedViews: mergeImportedActivityViews(savedViews, legacy) });
        void flushSettings().then(() => {
            if (useUserSettingsStore.getState().saveError) return;
            try {
                window.localStorage.removeItem(legacyActivityViewsKey(userId));
            } catch {
                // The views are on the account; a leftover local copy is harmless.
            }
        });
    }, [settingsLoading, settingsLoadError, userId, savedViews, updateSettings, flushSettings]);

    useEffect(() => { setSelected(null); }, [query, cursor]);
    useEffect(() => {
        const sync = () => { if (document.visibilityState === 'visible') setDay(todayUtc()); };
        document.addEventListener('visibilitychange', sync);
        return () => document.removeEventListener('visibilitychange', sync);
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError('');
        setData(null);
        const pageQuery = new URLSearchParams(query);
        pageQuery.set('page_size', String(PAGE_SIZE));
        if (cursor) pageQuery.set('cursor', cursor);
        api.get<ActivityPage>(`/api/v2/control-center/activity-logs?${pageQuery}`, controller.signal)
            .then((result) => {
                if (controller.signal.aborted) return;
                setData(result);
                setKnown((previous) => {
                    const next: KnownNames = { people: { ...previous.people }, workspaces: { ...previous.workspaces } };
                    for (const view of result.presentation ?? []) {
                        if (view.actor.id && view.actor.resolved) next.people[view.actor.id] = { name: view.actor.name, email: view.actor.email };
                        if (view.workspace.id && view.workspace.name) next.workspaces[`${view.workspace.type}:${view.workspace.id}`] = view.workspace.name;
                    }
                    const person = result.filter_labels?.person;
                    if (person?.resolved) next.people[person.id] = { name: person.name, email: person.email };
                    const workspace = result.filter_labels?.workspace;
                    if (workspace?.name) next.workspaces[`${workspace.type}:${workspace.id}`] = workspace.name;
                    return next;
                });
            })
            .catch((failure: unknown) => {
                if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Unable to load activity. Retry or narrow the filters.');
            })
            .finally(() => { if (!controller.signal.aborted) setLoading(false); });
        return () => controller.abort();
    }, [query, cursor, refresh]);

    useEffect(() => {
        const controller = new AbortController();
        setSummary(null);
        setSummaryError('');
        api.get<ActivitySummary>(`/api/v2/control-center/activity-logs/summary?${query}`, controller.signal)
            .then((result) => {
                if (controller.signal.aborted) return;
                setSummary(result);
                if (result.type_catalog?.length) setTypeCatalog(result.type_catalog);
            })
            .catch((failure: unknown) => {
                if (!controller.signal.aborted) setSummaryError(failure instanceof Error ? failure.message : 'Unable to load the activity trend. Retry.');
            });
        return () => controller.abort();
    }, [query, refresh]);

    const changeFilters = useCallback((next: ActivityFilters, options?: FilterChangeOptions) => {
        setParams(filterParams(next), { replace: options?.replace });
    }, [setParams]);
    const filterPerson = (id: string) => {
        setSelected(null);
        changeFilters({ ...filters, user_id: id });
        focusPill('person');
    };
    const filterWorkspace = (workspace: ActivityWorkspaceRef) => {
        setSelected(null);
        changeFilters({ ...filters, workspace_type: workspace.type as WorkspaceType, workspace_id: workspace.id });
        focusPill('workspace');
    };
    const toggleType = (type: string) => {
        changeFilters({
            ...filters,
            activity_type: filters.activity_type.includes(type)
                ? filters.activity_type.filter((item) => item !== type)
                : [...filters.activity_type, type],
        });
        focusPill('activity');
    };
    const applyQuery = (value: string) => setParams(filterParams(readFilters(new URLSearchParams(value))));
    const updatePrefs = (partial: Partial<ActivityLogPrefs>) => updateSettings({ v2ActivityLogPrefs: { ...prefs, ...partial } });
    const reload = () => {
        setDay(todayUtc());
        setPaging({ query, cursors: [null], index: 0 });
        setRefresh((value) => value + 1);
    };

    const exportCsv = async () => {
        // Read the clock now, so a relative range exports the window it names today.
        const exportQuery = apiParams(readFilters(new URLSearchParams(paramString))).toString();
        setDay(todayUtc());
        setExporting(true);
        setExportError('');
        try {
            const response = await fetch(apiUrl(`/api/v2/control-center/activity-logs/export.csv?${exportQuery}`), { credentials: CREDENTIALS_MODE });
            if (!response.ok) throw new Error('Activity export failed. Check the filters and retry.');
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            try {
                const anchor = document.createElement('a');
                anchor.href = url;
                anchor.download = 'activity_logs.csv';
                anchor.click();
            } finally {
                URL.revokeObjectURL(url);
            }
        } catch (failure) {
            setExportError(failure instanceof Error ? failure.message : 'Activity export failed. Retry.');
        } finally {
            setExporting(false);
        }
    };

    const records = data?.items ?? [];
    const views = records.map((record, index) => data?.presentation?.[index] ?? fallbackPresentation(record));
    const counts = useMemo(() => new Map((summary?.facets ?? []).map((facet) => [facet.activity_type, facet.count])), [summary]);
    const typeLabels = useMemo(() => new Map(typeCatalog.map((option) => [option.activity_type, option.label])), [typeCatalog]);
    const workspaceKey = filters.workspace_id ? `${filters.workspace_type}:${filters.workspace_id}` : '';
    const labels: ActivityFilterLabels = {
        person: filters.user_id && known.people[filters.user_id]
            ? { id: filters.user_id, ...known.people[filters.user_id], resolved: true } : undefined,
        workspace: workspaceKey && known.workspaces[workspaceKey]
            ? { type: filters.workspace_type, id: filters.workspace_id, name: known.workspaces[workspaceKey], resolved: true } : undefined,
    };
    const selectedRecord = selected !== null ? records[selected] : undefined;

    return (
        <section className="space-y-4 p-4 md:p-6" aria-labelledby="activity-logs-heading">
            <header className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h2 id="activity-logs-heading" className="text-xl font-semibold text-text-1">Activity Logs</h2>
                    <p className="mt-1 max-w-prose text-sm text-text-2">
                        Who did what, where and when. Select a person, activity or workspace in the log to filter by it.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <ActivityViewsMenu
                        views={savedViews}
                        currentQuery={canonical}
                        unavailable={settingsLoadError
                            ? 'Your saved views could not be loaded. Reload the page to see or change them.'
                            : settingsLoading ? 'Loading your saved views…' : undefined}
                        onApply={applyQuery}
                        onSave={(name) => {
                            updateSettings({ v2ActivityLogSavedViews: upsertActivitySavedView(savedViews, name, canonical) });
                            toast.success(`Saved view “${name.trim()}”.`);
                        }}
                        onRename={(id, name) => updateSettings({ v2ActivityLogSavedViews: renameActivitySavedView(savedViews, id, name) })}
                        onDelete={(view) => {
                            updateSettings({ v2ActivityLogSavedViews: removeActivitySavedView(savedViews, view.id) });
                            toast.success(`Deleted saved view “${view.name}”.`);
                        }}
                    />
                    <GlassButton size="sm" disabled={loading} onClick={reload}>
                        <RefreshCw size={14} aria-hidden="true" />Refresh
                    </GlassButton>
                    <GlassButton size="sm" disabled={exporting || loading || Boolean(error)} onClick={() => void exportCsv()}>
                        <Download size={14} aria-hidden="true" />{exporting ? 'Exporting…' : 'Export CSV'}
                    </GlassButton>
                </div>
            </header>
            {saveError ? <p role="alert" className="text-sm text-danger">Your Activity Logs views or preferences could not be saved: {saveError}</p> : null}
            {exportError ? <p role="alert" className="text-sm text-danger">{exportError}</p> : null}

            <ActivityFilterBar
                filters={filters}
                labels={labels}
                typeOptions={typeCatalog}
                counts={counts}
                searchPeople={data?.search_people}
                onChange={changeFilters}
                onReset={() => setParams(new URLSearchParams())}
                onRememberName={(kind, key, name, email) => setKnown((previous) => kind === 'person'
                    ? { ...previous, people: { ...previous.people, [key]: { name, email: email ?? '' } } }
                    : { ...previous, workspaces: { ...previous.workspaces, [key]: name } })}
            />

            <ActivityTrendStrip
                summary={summary}
                error={summaryError}
                filters={filters}
                expanded={prefs.showTrend}
                onToggleExpanded={() => updatePrefs({ showTrend: !prefs.showTrend })}
                onDrill={(start, end) => {
                    changeFilters({ ...filters, range: '', start_date: start, end_date: end });
                    focusPill('date');
                }}
                onToggleType={toggleType}
                typeLabel={(type) => typeLabels.get(type) ?? humanize(type)}
            />

            <ActivityTable
                records={records}
                views={views}
                loading={loading}
                error={error}
                prefs={prefs}
                selectedTypes={filters.activity_type}
                pageNumber={currentPaging.index + 1}
                hasPrevious={currentPaging.index > 0}
                hasNext={Boolean(data?.next_cursor)}
                onPrevious={() => setPaging({ ...currentPaging, index: currentPaging.index - 1 })}
                onNext={() => {
                    if (data?.next_cursor) {
                        setPaging({ query, cursors: [...currentPaging.cursors.slice(0, currentPaging.index + 1), data.next_cursor], index: currentPaging.index + 1 });
                    }
                }}
                onRetry={() => setRefresh((value) => value + 1)}
                onPrefsChange={updatePrefs}
                onOpen={setSelected}
                onFilterPerson={filterPerson}
                onFilterWorkspace={filterWorkspace}
                onToggleType={toggleType}
                emptyActions={<>
                    {filters.range !== '90' ? (
                        <GlassButton size="sm" variant="subtle" onClick={() => changeFilters({ ...filters, range: '90', ...presetDates('90') })}>
                            Widen to the last 90 days
                        </GlassButton>
                    ) : null}
                    {!isDefaultFilters(filters) ? (
                        <GlassButton size="sm" onClick={() => setParams(new URLSearchParams())}>Reset filters</GlassButton>
                    ) : null}
                </>}
            />

            {selectedRecord && selected !== null ? (
                <ActivityDetailDrawer
                    record={selectedRecord}
                    view={views[selected]}
                    index={selected}
                    total={records.length}
                    timeZone={prefs.timeZone}
                    onClose={() => setSelected(null)}
                    onStep={(index) => setSelected(Math.max(0, Math.min(records.length - 1, index)))}
                    onFilterPerson={filterPerson}
                    onFilterWorkspace={filterWorkspace}
                />
            ) : null}
        </section>
    );
}
