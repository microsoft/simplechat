// PublicDirectoryPage.tsx
//
// The V2 public workspace directory: a browse-and-curate surface over every public workspace
// the caller may discover. It is not a workspace shell -- there is no active handshake and no
// per-workspace context load -- and it is read-only: unlike the group directory there is no
// create, join or cancel. It reads one route, GET /api/public_workspaces/directory, and keeps
// the view, search and page in the URL so back, forward and a shared link reopen the same view.
//
// Its one write is the per-user "visible for chat" preference, which curates which public
// workspaces appear in the aggregate public chat. That preference lives in publicDirectorySettings
// and is shared verbatim with the classic interface. Every rule about it lives in publicVisibility:
// with no custom map every workspace is visible, and a toggle writes only the one workspace's
// entry, so opening or hiding one never rewrites another. Opening a workspace never hides the rest,
// unlike the classic "Set active".

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Globe, Loader2 } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { EmptyState, GlassButton, Skeleton } from '../components/ui/primitives';
import { SectionSearch } from '../components/workspace/primitives';
import { PublicDirectoryList } from '../components/workspace/PublicDirectoryList';
import {
    DIRECTORY_PAGE_SIZE, DIRECTORY_MAX_PAGE, DIRECTORY_SEARCH_MAX_LENGTH, PUBLIC_DIRECTORY,
    codePointLength,
    type PublicDirectoryPage as PublicDirectoryPageData, type PublicDirectoryView,
} from '../lib/publicDirectory';
import {
    hasCustomVisibility, isVisibleForChat, setChatVisibility,
    type ChatVisibilityMap,
} from '../lib/publicVisibility';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { useUserSetting, useUserSettingsStore } from '../stores/userSettingsStore';
import { usePublicWorkspaceLabels } from '../lib/publicWorkspaceLabels';

const VIEWS: { id: PublicDirectoryView; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'mine', label: 'My workspaces' },
];

const VISIBILITY_KEY = 'publicDirectorySettings';

function readView(value: string | null): PublicDirectoryView {
    return value === 'mine' ? 'mine' : 'all';
}

function readPageNumber(value: string | null): number {
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed < 1) return 1;
    // Clamp into the server's accepted range so a hand-edited or stale URL can't strand the reader
    // on a load error whose Retry would only repeat the same rejected request.
    return Math.min(parsed, DIRECTORY_MAX_PAGE);
}

export function PublicDirectoryPage() {
    const bootstrap = useBootstrapStore((state) => state.data);
    const enabled = Boolean(bootstrap?.features?.enable_public_workspaces);
    const labels = usePublicWorkspaceLabels();
    const navigate = useNavigate();
    const adapter = PUBLIC_DIRECTORY;
    const [searchParams, setSearchParams] = useSearchParams();

    const view = readView(searchParams.get('view'));
    const urlSearch = searchParams.get('search') ?? '';
    const page = readPageNumber(searchParams.get('page'));

    const visibilityMap = useUserSetting<ChatVisibilityMap>(VISIBILITY_KEY, {});
    const saveError = useUserSettingsStore((state) => state.saveError);
    const customVisibility = hasCustomVisibility(visibilityMap);

    const [searchInput, setSearchInput] = useState(urlSearch);
    const [searchError, setSearchError] = useState('');
    const [result, setResult] = useState<PublicDirectoryPageData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');
    const [retry, setRetry] = useState(0);

    const reload = useCallback(() => setRetry((value) => value + 1), []);

    // Keep the search box in step with the URL so back and forward restore the typed term.
    useEffect(() => { setSearchInput(urlSearch); }, [urlSearch]);

    // A debounced commit of the typed term. A new search resets to the first page. A term longer
    // than the server's limit is never sent -- it would only earn a 400 -- so it holds the current
    // list and shows a message beside the box until the reader shortens it.
    useEffect(() => {
        const handle = window.setTimeout(() => {
            const trimmed = searchInput.trim();
            if (codePointLength(trimmed) > DIRECTORY_SEARCH_MAX_LENGTH) {
                setSearchError(`Search terms can be at most ${DIRECTORY_SEARCH_MAX_LENGTH} characters.`);
                return;
            }
            setSearchError('');
            if (trimmed === urlSearch) return;
            const next = new URLSearchParams(searchParams);
            if (trimmed) next.set('search', trimmed); else next.delete('search');
            next.set('page', '1');
            setSearchParams(next, { replace: true });
        }, 300);
        return () => window.clearTimeout(handle);
    }, [searchInput, urlSearch, searchParams, setSearchParams]);

    useEffect(() => {
        if (!enabled) return;
        const controller = new AbortController();
        setLoading(true);
        setError('');
        void adapter.list(view, urlSearch, page, DIRECTORY_PAGE_SIZE, controller.signal).then((next) => {
            if (!controller.signal.aborted) setResult(next);
        }).catch((cause: unknown) => {
            if (!controller.signal.aborted) {
                setResult(null);
                setError(cause instanceof Error ? cause.message : 'Could not load the public directory. Please retry.');
            }
        }).finally(() => {
            if (!controller.signal.aborted) setLoading(false);
        });
        return () => controller.abort();
    }, [enabled, adapter, view, urlSearch, page, retry]);

    const changeView = useCallback((next: PublicDirectoryView) => {
        if (next === view) return;
        const params = new URLSearchParams(searchParams);
        params.set('view', next);
        params.set('page', '1');
        setSearchParams(params);
    }, [searchParams, setSearchParams, view]);

    const changePage = useCallback((next: number) => {
        const params = new URLSearchParams(searchParams);
        params.set('page', String(next));
        setSearchParams(params);
    }, [searchParams, setSearchParams]);

    const toggleVisibility = useCallback((id: string, next: boolean) => {
        // Read the store directly, not the closed-over render value, so rapid toggles compose on the
        // latest map. Writing only this one entry keeps the change additive per the R2 ruling.
        const current = (useUserSettingsStore.getState().settings[VISIBILITY_KEY] as ChatVisibilityMap | undefined) ?? {};
        const nextMap = setChatVisibility(current, id, next);
        useUserSettingsStore.getState().update({ [VISIBILITY_KEY]: nextMap });
        setNotice(next ? 'This workspace will appear in public chat.' : 'This workspace is hidden from public chat.');
    }, []);

    const workspaces = result?.workspaces ?? [];
    const totalCount = result?.totalCount ?? 0;
    const totalPages = Math.max(1, Math.ceil(totalCount / DIRECTORY_PAGE_SIZE));

    const emptyDescription = useMemo(() => {
        if (urlSearch) return `No ${labels.lower_plural} match your search.`;
        if (view === 'mine') return `You do not manage any ${labels.lower_singular} yet.`;
        return `No ${labels.lower_plural} have been published yet.`;
    }, [urlSearch, view, labels]);

    if (!enabled) {
        return (
            <div className="flex h-full flex-col">
                <PageHeader title="Public directory" leading={<Globe size={20} className="text-accent" />} />
                <div className="p-4">
                    <EmptyState icon={<Globe size={28} />} title={`${labels.plural} are not enabled`}
                        description={`Your administrator has not enabled ${labels.lower_plural} for this deployment.`} />
                </div>
            </div>
        );
    }

    const header = (
        <PageHeader title="Public directory" description={`Browse ${labels.lower_plural} and choose which appear in chat`}
            leading={<Globe size={20} className="text-accent" />}
            actions={<GlassButton size="sm" onClick={() => navigate('/public')}><ArrowLeft size={14} />{labels.plural}</GlassButton>} />
    );

    return (
        <div className="flex h-full flex-col">
            {header}
            <div className="shrink-0 space-y-3 border-b border-edge px-4 py-3">
                <div role="group" aria-label="Directory view" className="inline-flex rounded-xl border border-edge bg-surface-1 p-0.5">
                    {VIEWS.map((entry) => (
                        <button key={entry.id} type="button" aria-pressed={view === entry.id}
                            onClick={() => changeView(entry.id)}
                            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${view === entry.id ? 'bg-accent text-on-accent' : 'text-text-2 hover:text-text-1'}`}>
                            {entry.label}
                        </button>
                    ))}
                </div>
                <SectionSearch value={searchInput} onChange={setSearchInput} placeholder={`Search ${labels.lower_plural} by name or description`} />
                {searchError ? <p role="alert" className="text-xs text-danger">{searchError}</p> : null}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
                <div className="mx-auto max-w-3xl space-y-4">
                    {error ? (
                        <div role="alert" className="space-y-2 rounded-xl border border-danger/30 bg-danger-soft p-3 text-sm text-danger">
                            <p>{error}</p>
                            <GlassButton size="sm" disabled={loading} onClick={reload}>Retry directory</GlassButton>
                        </div>
                    ) : null}
                    {saveError ? (
                        <p role="alert" className="rounded-xl border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">{saveError}</p>
                    ) : null}
                    {notice ? <p role="status" className="rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-2">{notice}</p> : null}
                    {!customVisibility && !loading && !error && workspaces.length > 0 ? (
                        <p className="rounded-xl border border-edge bg-surface-1 px-3 py-2 text-xs text-text-3">
                            Every {labels.lower_singular} appears in chat by default. Hiding one starts a custom list, and only the workspaces left visible will appear.
                        </p>
                    ) : null}
                    {loading ? (
                        <div role="status" className="space-y-2">
                            <p className="flex items-center gap-2 text-sm text-text-2"><Loader2 size={16} className="animate-spin" />Loading {labels.lower_plural}...</p>
                            <Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" />
                        </div>
                    ) : !error && workspaces.length === 0 ? (
                        <EmptyState icon={<Globe size={28} />} title={`No ${labels.lower_plural} to show`} description={emptyDescription} />
                    ) : !error ? (
                        <>
                            <p role="status" className="text-xs text-text-3">
                                Showing {workspaces.length} of {totalCount} {totalCount === 1 ? 'workspace' : 'workspaces'}.
                            </p>
                            <PublicDirectoryList workspaces={workspaces} busyId={null} disabled={false}
                                visibleFor={(workspace) => isVisibleForChat(visibilityMap, workspace.id)}
                                logoUrlFor={(workspace) => adapter.logoUrl(workspace)}
                                onOpen={(id) => navigate(adapter.openPath(id))}
                                onToggleVisibility={toggleVisibility} />
                            {totalCount > DIRECTORY_PAGE_SIZE || page > 1 ? (
                                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-3">
                                    <span>Page {page} of {totalPages}</span>
                                    <div className="flex gap-2">
                                        <GlassButton size="sm" disabled={loading || page <= 1} onClick={() => changePage(page - 1)}>Previous workspaces</GlassButton>
                                        <GlassButton size="sm" disabled={loading || page * DIRECTORY_PAGE_SIZE >= totalCount} onClick={() => changePage(page + 1)}>Next workspaces</GlassButton>
                                    </div>
                                </div>
                            ) : null}
                        </>
                    ) : null}
                </div>
            </div>
        </div>
    );
}
