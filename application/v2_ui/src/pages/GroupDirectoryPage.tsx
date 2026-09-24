// GroupDirectoryPage.tsx
//
// The V2 group directory: a browse-and-join surface for every group the caller may discover.
// It is not a workspace shell -- there is no active-group handshake and no per-group context
// load. It reads one route, GET /api/groups/directory, keeps the view, search and page in the
// URL so back, forward and a shared link all reopen the same view, and drives a presentational
// list that the public directory (M9A) will reuse.
//
// Every membership action takes its truth from the server: a join or cancel replaces exactly
// the affected row with the response's {group}, and a refusal reloads the page or keeps the
// state to retry, so the badge and the offered action never drift from what the server holds.
// Create is offered only when the server's hint allows it, never on the raw feature flag.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Loader2, Plus, Users } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { EmptyState, GlassButton, Skeleton } from '../components/ui/primitives';
import { SectionSearch } from '../components/workspace/primitives';
import { DirectoryList } from '../components/workspace/DirectoryList';
import { CreateGroupDialog } from '../components/workspace/CreateGroupDialog';
import {
    DIRECTORY_PAGE_SIZE, DIRECTORY_MAX_PAGE, DIRECTORY_SEARCH_MAX_LENGTH, GROUP_DIRECTORY,
    codePointLength, directoryErrorCode,
    type DirectoryPage, type DirectoryView,
} from '../lib/groupDirectory';
import { useBootstrapStore } from '../stores/bootstrapStore';

const VIEWS: { id: DirectoryView; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'mine', label: 'My groups' },
    { id: 'discover', label: 'Discover' },
];

// The 409/404 codes whose truth is only knowable by re-reading the current page.
const RELOAD_CODES = new Set(['already_member', 'request_pending', 'no_pending_request', 'group_not_found']);

function readView(value: string | null): DirectoryView {
    return value === 'mine' || value === 'discover' ? value : 'all';
}

function readPageNumber(value: string | null): number {
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed < 1) return 1;
    // Clamp into the server's accepted range so a hand-edited or stale URL can't strand the reader
    // on a load error whose Retry would only repeat the same rejected request.
    return Math.min(parsed, DIRECTORY_MAX_PAGE);
}

export function GroupDirectoryPage() {
    const bootstrap = useBootstrapStore((state) => state.data);
    const enabled = Boolean(bootstrap?.features?.enable_group_workspaces);
    const navigate = useNavigate();
    const adapter = GROUP_DIRECTORY;
    const [searchParams, setSearchParams] = useSearchParams();

    const view = readView(searchParams.get('view'));
    const urlSearch = searchParams.get('search') ?? '';
    const page = readPageNumber(searchParams.get('page'));

    const [searchInput, setSearchInput] = useState(urlSearch);
    const [searchError, setSearchError] = useState('');
    const [result, setResult] = useState<DirectoryPage | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');
    const [retry, setRetry] = useState(0);
    const [busyId, setBusyId] = useState<string | null>(null);
    const [createOpen, setCreateOpen] = useState(false);
    const [creating, setCreating] = useState(false);
    const [createError, setCreateError] = useState('');

    const reload = useCallback(() => setRetry((value) => value + 1), []);

    // Keep the search box in step with the URL so back and forward restore the typed term.
    useEffect(() => { setSearchInput(urlSearch); }, [urlSearch]);

    // A debounced commit of the typed term. A new search resets to the first page. A term longer
    // than the server's limit is never sent -- it would only earn a 400 -- so it holds the current
    // list and shows the server's message beside the box until the reader shortens it.
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
                setError(cause instanceof Error ? cause.message : 'Could not load the group directory. Please retry.');
            }
        }).finally(() => {
            if (!controller.signal.aborted) setLoading(false);
        });
        return () => controller.abort();
    }, [enabled, adapter, view, urlSearch, page, retry]);

    const changeView = useCallback((next: DirectoryView) => {
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

    const runAction = useCallback(async (id: string, kind: 'join' | 'cancel') => {
        setBusyId(id);
        setNotice('');
        try {
            const group = kind === 'join' ? await adapter.join(id) : await adapter.cancel(id);
            setResult((prev) => (prev ? { ...prev, groups: prev.groups.map((row) => (row.id === id ? group : row)) } : prev));
            setNotice(kind === 'join' ? `Your request to join ${group.name} was sent.` : `Your request to join ${group.name} was cancelled.`);
        } catch (cause: unknown) {
            const code = directoryErrorCode(cause);
            setNotice(cause instanceof Error ? cause.message : 'The request could not be completed. Please retry.');
            // A stale row is only knowable by re-reading; a group_write_conflict keeps the state
            // for a plain retry, and anything else simply surfaces its message.
            if (code && RELOAD_CODES.has(code)) reload();
        } finally {
            setBusyId(null);
        }
    }, [adapter, reload]);

    const submitCreate = useCallback(async (name: string, description: string) => {
        setCreating(true);
        setCreateError('');
        try {
            const group = await adapter.create(name, description);
            navigate(adapter.openPath(group.id));
        } catch (cause: unknown) {
            const code = directoryErrorCode(cause);
            setCreateError(cause instanceof Error ? cause.message : 'The group could not be created. Please retry.');
            // A policy refusal can only have changed the hint, so re-read it.
            if (code === 'group_creation_disabled' || code === 'create_groups_role_required') reload();
        } finally {
            setCreating(false);
        }
    }, [adapter, navigate, reload]);

    const openCreate = useCallback(() => { setCreateError(''); setCreateOpen(true); }, []);
    const closeCreate = useCallback(() => { setCreateError(''); setCreateOpen(false); }, []);

    const hints = result?.hints;
    const groups = result?.groups ?? [];
    const totalCount = result?.totalCount ?? 0;
    const totalPages = Math.max(1, Math.ceil(totalCount / DIRECTORY_PAGE_SIZE));
    const canCreate = Boolean(hints?.canCreate);

    const emptyDescription = useMemo(() => {
        if (urlSearch) return 'No groups match your search.';
        if (view === 'mine') return 'You are not a member of any group yet.';
        if (view === 'discover') return 'There are no other groups to discover right now.';
        return 'No groups have been created yet.';
    }, [urlSearch, view]);

    if (!enabled) {
        return (
            <div className="flex h-full flex-col">
                <PageHeader title="Group directory" leading={<Users size={20} className="text-accent" />} />
                <div className="p-4">
                    <EmptyState icon={<Users size={28} />} title="Group workspaces are not enabled"
                        description="Your administrator has not enabled group workspaces for this deployment." />
                </div>
            </div>
        );
    }

    const header = (
        <PageHeader title="Group directory" description="Find, join and create group workspaces"
            leading={<Users size={20} className="text-accent" />}
            actions={(
                <>
                    <GlassButton size="sm" onClick={() => navigate('/groups')}><ArrowLeft size={14} />Your groups</GlassButton>
                    {canCreate ? (
                        <GlassButton size="sm" variant="primary" onClick={openCreate}><Plus size={14} />Create group</GlassButton>
                    ) : null}
                </>
            )} />
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
                <SectionSearch value={searchInput} onChange={setSearchInput} placeholder="Search groups by name or description" />
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
                    {notice ? <p role="status" className="rounded-xl border border-edge bg-surface-1 px-3 py-2 text-sm text-text-2">{notice}</p> : null}
                    {loading ? (
                        <div role="status" className="space-y-2">
                            <p className="flex items-center gap-2 text-sm text-text-2"><Loader2 size={16} className="animate-spin" />Loading groups...</p>
                            <Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" />
                        </div>
                    ) : !error && groups.length === 0 ? (
                        <EmptyState icon={<Users size={28} />} title="No groups to show" description={emptyDescription}
                            action={canCreate && !urlSearch && view !== 'discover'
                                ? <GlassButton size="sm" variant="primary" onClick={openCreate}><Plus size={14} />Create group</GlassButton>
                                : undefined} />
                    ) : hints ? (
                        <>
                            <p role="status" className="text-xs text-text-3">
                                Showing {groups.length} of {totalCount} {totalCount === 1 ? 'group' : 'groups'}.
                            </p>
                            <DirectoryList groups={groups} hints={hints} busyId={busyId} disabled={busyId !== null}
                                logoUrlFor={(group) => adapter.logoUrl(group)}
                                onOpen={(id) => navigate(adapter.openPath(id))}
                                onJoin={(id) => void runAction(id, 'join')}
                                onCancel={(id) => void runAction(id, 'cancel')} />
                            {totalCount > DIRECTORY_PAGE_SIZE || page > 1 ? (
                                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-text-3">
                                    <span>Page {page} of {totalPages}</span>
                                    <div className="flex gap-2">
                                        <GlassButton size="sm" disabled={loading || page <= 1} onClick={() => changePage(page - 1)}>Previous groups</GlassButton>
                                        <GlassButton size="sm" disabled={loading || page * DIRECTORY_PAGE_SIZE >= totalCount} onClick={() => changePage(page + 1)}>Next groups</GlassButton>
                                    </div>
                                </div>
                            ) : null}
                        </>
                    ) : null}
                </div>
            </div>
            {createOpen ? (
                <CreateGroupDialog submitting={creating} serverError={createError}
                    onSubmit={(name, description) => void submitCreate(name, description)} onClose={closeCreate} />
            ) : null}
        </div>
    );
}
