// PublicDirectoryPage.tsx
//
// The V2 public workspace directory: a browse-and-curate surface over every public workspace
// the caller may discover. It is not a workspace shell -- there is no active handshake and no
// per-workspace context load. It reads one route, GET /api/public_workspaces/directory, keeps
// the view, search and page in the URL so back, forward and a shared link reopen the same view,
// and offers three writes beyond curation: creating a public workspace (the classic route), and
// asking to manage a workspace's documents or cancelling that request (the M10A request routes).
// Each membership write returns the server's fresh row, which replaces the row in place, so the
// affordance is gated purely on the server-computed membership and never a client role check.
//
// Its one write is the per-user "visible for chat" preference, which curates which public
// workspaces appear in the aggregate public chat. That preference lives in publicDirectorySettings
// and is shared verbatim with the classic interface. Every rule about it lives in publicVisibility:
// with no custom map every workspace is visible, and a toggle writes only the one workspace's
// entry, so opening or hiding one never rewrites another. Opening a workspace never hides the rest,
// unlike the classic "Set active".

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Globe, Loader2, Plus } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { EmptyState, GlassButton, Skeleton } from '../components/ui/primitives';
import { SectionSearch } from '../components/workspace/primitives';
import { PublicDirectoryList } from '../components/workspace/PublicDirectoryList';
import { PublicDirectoryVisibilityTools } from '../components/workspace/PublicDirectoryVisibilityTools';
import { CreatePublicWorkspaceDialog } from '../components/workspace/CreatePublicWorkspaceDialog';
import { ApiError } from '../lib/apiClient';
import {
    DIRECTORY_PAGE_SIZE, DIRECTORY_MAX_PAGE, DIRECTORY_SEARCH_MAX_LENGTH, PUBLIC_DIRECTORY,
    DirectoryBulkTooLargeError,
    codePointLength, publicDirectoryErrorCode,
    type PublicDirectoryPage as PublicDirectoryPageData, type PublicDirectoryView,
} from '../lib/publicDirectory';
import {
    hasCustomVisibility, isVisibleForChat, setChatVisibility,
    markEvery, mapForSavedList, visibleIdsFromMap, chattableIds,
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
const SAVED_LISTS_KEY = 'publicDirectorySavedLists';

// The aggregate public chat lives only in the classic interface: V2 chat scopes are strictly
// per-workspace (chatContext.ts), with no "all visible public workspaces" scope. So the two chat
// entry points hand off to the classic aggregate route, the one place the whole visibility map is
// consumed, rather than a V2 route that cannot express the aggregate.
const CHAT_PUBLIC_HREF = '/chats?openSearch=1&scope=public';

// A membership refusal that means the client's row is stale: the only way to learn the true state
// is to re-read the directory. A write conflict keeps the row for a plain retry, so it is omitted.
const RELOAD_CODES = new Set(['already_member', 'request_pending', 'no_pending_request', 'workspace_not_found']);

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

function countLabel(count: number): string {
    return `${count} ${count === 1 ? 'workspace' : 'workspaces'}`;
}

function unavailableLabel(count: number): string {
    return `${count} unavailable ${count === 1 ? 'workspace' : 'workspaces'}`;
}

// A bulk "show all" only ever makes *available* workspaces visible, so it reports both what it made
// visible and how many it skipped -- never implying it touched the ones it deliberately left alone.
function bulkVisibleNotice(visible: number, skipped: number): string {
    const base = `Made ${countLabel(visible)} visible in chat.`;
    if (skipped === 0) return base;
    return `${base} ${unavailableLabel(skipped)} ${skipped === 1 ? 'was' : 'were'} skipped because `
        + `${skipped === 1 ? 'it is' : 'they are'} not available for chat.`;
}

// Applying a saved list leaves an unavailable member hidden rather than claiming it for chat, so
// its notice reports the visible count and, honestly, how many named workspaces stayed hidden.
function useListNotice(visible: number, skipped: number): string {
    const base = `${countLabel(visible)} now visible in chat; the rest are hidden.`;
    if (skipped === 0) return base;
    return `${base} ${unavailableLabel(skipped)} in the list stayed hidden because `
        + `${skipped === 1 ? 'it is' : 'they are'} not available for chat.`;
}

// A bulk action either covers the whole directory or refuses; it never writes a partial set. The
// too-large refusal carries its own count-bearing sentence, and any transport failure during the
// page walk means nothing was written, so a plain retry message is safe.
function bulkErrorMessage(cause: unknown): string {
    if (cause instanceof DirectoryBulkTooLargeError) return cause.message;
    return cause instanceof Error ? cause.message : 'The change could not be completed. Please retry.';
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
    const savedLists = useUserSetting<Record<string, string[]>>(SAVED_LISTS_KEY, {});
    const saveError = useUserSettingsStore((state) => state.saveError);
    const customVisibility = hasCustomVisibility(visibilityMap);
    const savedListNames = useMemo(
        () => Object.keys(savedLists).sort((left, right) => left.localeCompare(right)),
        [savedLists],
    );

    const [searchInput, setSearchInput] = useState(urlSearch);
    const [searchError, setSearchError] = useState('');
    const [result, setResult] = useState<PublicDirectoryPageData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');
    const [retry, setRetry] = useState(0);
    const [createOpen, setCreateOpen] = useState(false);
    const [creating, setCreating] = useState(false);
    const [createError, setCreateError] = useState('');
    const [busyId, setBusyId] = useState<string | null>(null);
    const [bulkBusy, setBulkBusy] = useState(false);

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

    const readVisibilityMap = useCallback(
        () => (useUserSettingsStore.getState().settings[VISIBILITY_KEY] as ChatVisibilityMap | undefined) ?? {},
        [],
    );

    // Show or hide every workspace in the directory. The workspaces are walked across the server's
    // pages (bounded), then merged onto the live map so entries the walk did not name are preserved
    // per the R2 additive rule. Showing marks only *available* workspaces -- making an unavailable
    // one visible would claim it for chat when its status forbids it (decision 32) -- and reports
    // both the count it made visible and the count it skipped. Hiding covers every workspace, since
    // hiding one a reader cannot currently use is always a valid choice.
    const runBulkVisibility = useCallback(async (visible: boolean) => {
        setBulkBusy(true);
        setNotice('');
        try {
            const workspaces = await adapter.listAllWorkspaces();
            const targets = visible ? chattableIds(workspaces) : workspaces.map((workspace) => workspace.id);
            useUserSettingsStore.getState().update({ [VISIBILITY_KEY]: markEvery(readVisibilityMap(), targets, visible) });
            setNotice(visible
                ? bulkVisibleNotice(targets.length, workspaces.length - targets.length)
                : `Hid ${countLabel(targets.length)} from chat.`);
        } catch (cause: unknown) {
            setNotice(bulkErrorMessage(cause));
        } finally {
            setBulkBusy(false);
        }
    }, [adapter, readVisibilityMap]);

    // Open the classic public chat over the workspaces already visible, writing nothing. V2 chat has
    // no all-visible public scope, so this hands off to classic (recorded exception, decision 31).
    // Any pending debounced write is still flushed first so the chat sees the latest curation, and a
    // failed save is surfaced rather than masked by leaving the page.
    const chatWithVisible = useCallback(async () => {
        setBulkBusy(true);
        try {
            await useUserSettingsStore.getState().flush();
            if (useUserSettingsStore.getState().saveError) {
                setNotice('Your visibility changes could not be saved, so chat was not opened. Please retry.');
                return;
            }
            window.location.href = CHAT_PUBLIC_HREF;
        } finally {
            setBulkBusy(false);
        }
    }, []);

    // Snapshot the workspaces visible across the whole directory into a named list, applying the
    // empty-map fallback (no map means every workspace is visible) so the snapshot is the real set.
    const saveList = useCallback(async (name: string) => {
        setBulkBusy(true);
        setNotice('');
        try {
            const allIds = await adapter.listAllWorkspaceIds();
            const visibleIds = visibleIdsFromMap(readVisibilityMap(), allIds);
            const lists = (useUserSettingsStore.getState().settings[SAVED_LISTS_KEY] as Record<string, string[]> | undefined) ?? {};
            useUserSettingsStore.getState().update({ [SAVED_LISTS_KEY]: { ...lists, [name]: visibleIds } });
            setNotice(`Saved "${name}" with ${countLabel(visibleIds.length)}.`);
        } catch (cause: unknown) {
            setNotice(bulkErrorMessage(cause));
        } finally {
            setBulkBusy(false);
        }
    }, [adapter, readVisibilityMap]);

    // Replace the whole visibility map with a saved list: exactly its *available* workspaces are
    // visible and the rest hidden. The list is walked against the directory so an unavailable member
    // is left hidden rather than claimed for chat (decision 32); the rest hide because any custom map
    // hides everything absent. An empty list, or a list whose members are all unavailable, hides
    // every id, so it builds an explicit all-hidden map (an empty map would instead mean "all
    // visible"). The count reported is exactly the available members made visible.
    const useList = useCallback(async (name: string) => {
        const lists = (useUserSettingsStore.getState().settings[SAVED_LISTS_KEY] as Record<string, string[]> | undefined) ?? {};
        const listIds = lists[name];
        if (!Array.isArray(listIds)) {
            setNotice('That saved list is no longer available.');
            return;
        }
        setBulkBusy(true);
        setNotice('');
        try {
            const workspaces = await adapter.listAllWorkspaces();
            if (listIds.length === 0) {
                useUserSettingsStore.getState().update({ [VISIBILITY_KEY]: markEvery({}, workspaces.map((workspace) => workspace.id), false) });
                setNotice('All workspaces are now hidden from chat.');
                return;
            }
            const available = new Set(chattableIds(workspaces));
            const inDirectory = new Set(workspaces.map((workspace) => workspace.id));
            const visibleIds = listIds.filter((id) => available.has(id));
            const skipped = listIds.filter((id) => inDirectory.has(id) && !available.has(id)).length;
            const nextMap = visibleIds.length > 0
                ? mapForSavedList(visibleIds)
                : markEvery({}, workspaces.map((workspace) => workspace.id), false);
            useUserSettingsStore.getState().update({ [VISIBILITY_KEY]: nextMap });
            setNotice(useListNotice(visibleIds.length, skipped));
        } catch (cause: unknown) {
            setNotice(bulkErrorMessage(cause));
        } finally {
            setBulkBusy(false);
        }
    }, [adapter]);

    const deleteList = useCallback((name: string) => {
        const lists = (useUserSettingsStore.getState().settings[SAVED_LISTS_KEY] as Record<string, string[]> | undefined) ?? {};
        if (!(name in lists)) return;
        const next = { ...lists };
        delete next[name];
        useUserSettingsStore.getState().update({ [SAVED_LISTS_KEY]: next });
        setNotice(`Deleted the saved list "${name}".`);
    }, []);

    const runRequestAction = useCallback(async (id: string, kind: 'request' | 'cancel') => {
        // The server's fresh row is the single source of truth: a request or cancel replaces the row
        // in place, so its membership -- and thus the affordance -- always reflects what the server
        // just committed, never an optimistic guess.
        setBusyId(id);
        setNotice('');
        try {
            const workspace = kind === 'request' ? await adapter.requestAccess(id) : await adapter.cancelRequest(id);
            setResult((prev) => (prev
                ? { ...prev, workspaces: prev.workspaces.map((row) => (row.id === id ? workspace : row)) }
                : prev));
            setNotice(kind === 'request'
                ? `Your request to manage ${workspace.name} was sent.`
                : `Your request to manage ${workspace.name} was cancelled.`);
        } catch (cause: unknown) {
            const code = publicDirectoryErrorCode(cause);
            setNotice(cause instanceof Error ? cause.message : 'The request could not be completed. Please retry.');
            if (code && RELOAD_CODES.has(code)) reload();
        } finally {
            setBusyId(null);
        }
    }, [adapter, reload]);

    const submitCreate = useCallback(async (name: string, description: string) => {
        setCreating(true);
        setCreateError('');
        try {
            const created = await adapter.create(name, description);
            navigate(adapter.openPath(created.id));
        } catch (cause: unknown) {
            // The classic route's refusals carry no error_code and its 400 exception path can echo an
            // internal message, so the reader is shown a safe, status-derived sentence rather than the
            // raw body. A 403 or a feature-off 400 can only mean the create hint went stale, so the
            // directory is re-read to hide the control if it is no longer allowed.
            const status = cause instanceof ApiError ? cause.status : 0;
            if (status === 403) {
                setCreateError(`You do not have permission to create a ${labels.lower_singular}.`);
            } else {
                setCreateError(`The ${labels.lower_singular} could not be created. Please retry.`);
            }
            if (status === 403 || status === 400) reload();
        } finally {
            setCreating(false);
        }
    }, [adapter, navigate, reload, labels]);

    const openCreate = useCallback(() => { setCreateError(''); setCreateOpen(true); }, []);
    const closeCreate = useCallback(() => { setCreateError(''); setCreateOpen(false); }, []);

    const workspaces = result?.workspaces ?? [];
    const totalCount = result?.totalCount ?? 0;
    const totalPages = Math.max(1, Math.ceil(totalCount / DIRECTORY_PAGE_SIZE));
    const canCreate = Boolean(result?.hints?.canCreate);
    // The curation tools act on the whole directory, so they show whenever there is something to
    // curate: a populated directory, an existing custom list, or saved lists to reuse. They stay
    // hidden on a genuinely empty directory where every action would be a no-op.
    const showTools = !error && (totalCount > 0 || customVisibility || savedListNames.length > 0);

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
            actions={(
                <>
                    <GlassButton size="sm" onClick={() => navigate('/public')}><ArrowLeft size={14} />{labels.plural}</GlassButton>
                    {canCreate ? (
                        <GlassButton size="sm" variant="primary" aria-label={`Create ${labels.lower_singular}`} onClick={openCreate}>
                            <Plus size={14} />
                            <span className="hidden sm:inline">Create {labels.lower_singular}</span>
                            <span className="sm:hidden">Create</span>
                        </GlassButton>
                    ) : null}
                </>
            )} />
    );

    return (
        <div className="flex h-full flex-col">
            {header}
            <div className="shrink-0 space-y-3 border-b border-edge px-4 py-3">
                <div role="group" aria-label="Directory view" className="inline-flex max-w-full flex-wrap rounded-xl border border-edge bg-surface-1 p-0.5">
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
                    {showTools ? (
                        <PublicDirectoryVisibilityTools
                            lowerSingular={labels.lower_singular} lowerPlural={labels.lower_plural}
                            customVisibility={customVisibility} savedListNames={savedListNames}
                            busy={bulkBusy} disabled={loading}
                            onAllVisible={() => void runBulkVisibility(true)}
                            onAllHidden={() => void runBulkVisibility(false)}
                            onChatWithVisible={() => void chatWithVisible()}
                            onSaveList={(name) => void saveList(name)}
                            onUseList={(name) => void useList(name)}
                            onDeleteList={deleteList} />
                    ) : null}
                    {loading ? (
                        <div role="status" className="space-y-2">
                            <p className="flex items-center gap-2 text-sm text-text-2"><Loader2 size={16} className="animate-spin" />Loading {labels.lower_plural}...</p>
                            <Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" />
                        </div>
                    ) : !error && workspaces.length === 0 ? (
                        <EmptyState icon={<Globe size={28} />} title={`No ${labels.lower_plural} to show`} description={emptyDescription}
                            action={canCreate && !urlSearch
                                ? <GlassButton size="sm" variant="primary" onClick={openCreate}><Plus size={14} />Create {labels.lower_singular}</GlassButton>
                                : undefined} />
                    ) : !error ? (
                        <>
                            <p role="status" className="text-xs text-text-3">
                                Showing {workspaces.length} of {totalCount} {totalCount === 1 ? 'workspace' : 'workspaces'}.
                            </p>
                            <PublicDirectoryList workspaces={workspaces} busyId={busyId} disabled={busyId !== null}
                                visibleFor={(workspace) => isVisibleForChat(visibilityMap, workspace.id)}
                                logoUrlFor={(workspace) => adapter.logoUrl(workspace)}
                                onOpen={(id) => navigate(adapter.openPath(id))}
                                onToggleVisibility={toggleVisibility}
                                onRequestAccess={(id) => void runRequestAction(id, 'request')}
                                onCancelRequest={(id) => void runRequestAction(id, 'cancel')} />
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
            {createOpen ? (
                <CreatePublicWorkspaceDialog submitting={creating} serverError={createError}
                    singular={labels.singular} lowerSingular={labels.lower_singular}
                    onSubmit={(name, description) => void submitCreate(name, description)} onClose={closeCreate} />
            ) : null}
        </div>
    );
}
