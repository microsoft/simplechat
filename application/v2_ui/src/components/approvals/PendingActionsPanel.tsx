// PendingActionsPanel.tsx
// Outgoing Microsoft 365 email and calendar invitations waiting to be sent.
//
// The list lives here; each action is drawn by the shared PendingActionCard, the same card the
// chat shows under the reply that saved the action. Send and Cancel always carry the version the
// user reviewed; the server rejects a stale version, and the card then shows the server's
// current state instead of retrying anything.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import {
    ACTIONABLE_PENDING_STATUSES,
    errorMessage,
    fetchPendingActions,
    formatDateTime,
    pendingActionHeading,
    textList,
    type PendingAction,
} from '../../lib/approvalsApi';
import { actionSubject, normalizePendingActionId } from '../../lib/m365PendingActions';
import { createPendingActionsStore, PendingActionsProvider, usePendingActions } from '../../stores/m365PendingActionsStore';
import { GlassButton, Skeleton } from '../ui/primitives';
import {
    ApprovalSplit,
    DetailEmpty,
    ListMessage,
    ListRow,
    ListToolbar,
    Notice,
    StatusBadge,
} from './ApprovalParts';
import { PendingActionCard } from './PendingActionCard';
export function PendingActionsPanel({
    selectedId,
    reloadKey,
    onCountChange,
}: {
    selectedId?: string;
    reloadKey: number;
    onCountChange?: (count: number) => void;
}) {
    const navigate = useNavigate();
    const [items, setItems] = useState<PendingAction[]>([]);
    const [token, setToken] = useState('');
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [loadError, setLoadError] = useState('');
    const [search, setSearch] = useState('');

    const loadFirst = useCallback(async (signal?: AbortSignal) => {
        setLoading(true);
        setLoadError('');
        try {
            const page = await fetchPendingActions('', signal);
            setItems(page.items);
            setToken(page.continuationToken);
        } catch (error) {
            if (signal?.aborted) return;
            setItems([]);
            setToken('');
            setLoadError(errorMessage(error, 'Outgoing actions could not be loaded.'));
        } finally {
            if (!signal?.aborted) setLoading(false);
        }
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        void loadFirst(controller.signal);
        return () => controller.abort();
    }, [loadFirst, reloadKey]);

    useEffect(() => {
        onCountChange?.(items.filter((item) => ACTIONABLE_PENDING_STATUSES.has(item.status)).length);
    }, [items, onCountChange]);

    const loadMore = async () => {
        if (!token) return;
        setLoadingMore(true);
        try {
            const page = await fetchPendingActions(token);
            setItems((current) => {
                const seen = new Set(current.map((item) => item.id));
                return [...current, ...page.items.filter((item) => !seen.has(item.id))];
            });
            setToken(page.continuationToken);
        } catch (error) {
            setLoadError(errorMessage(error, 'More outgoing actions could not be loaded.'));
        } finally {
            setLoadingMore(false);
        }
    };

    const replaceItem = useCallback((next: PendingAction) => {
        setItems((current) => current.map((item) => (item.id === next.id ? next : item)));
    }, []);

    const filtered = useMemo(() => {
        const query = search.trim().toLowerCase();
        if (!query) return items;
        return items.filter((item) =>
            [actionSubject(item), pendingActionHeading(item), textList(item.summary?.to_recipients), textList(item.summary?.attendee_recipients)]
                .join(' ')
                .toLowerCase()
                .includes(query),
        );
    }, [items, search]);

    const list = (
        <>
            <ListToolbar search={search} onSearch={setSearch} searchLabel="Search outgoing actions" />
            {loading ? (
                <div className="space-y-2 p-4" aria-busy="true">
                    <Skeleton className="h-12 w-full" />
                    <Skeleton className="h-12 w-full" />
                </div>
            ) : loadError && !items.length ? (
                <div className="p-4">
                    <Notice tone="danger">{loadError}</Notice>
                </div>
            ) : filtered.length ? (
                <>
                    <ul>
                        {filtered.map((action) => (
                            <ListRow
                                key={action.id}
                                active={action.id === selectedId}
                                onSelect={() => navigate(`/approvals/outgoing/${encodeURIComponent(action.id)}`)}
                                title={actionSubject(action)}
                                testId={`v2-pending-action-row-${action.id}`}
                                meta={[pendingActionHeading(action), formatDateTime(action.created_at)].filter(Boolean).join(' · ')}
                                badge={<StatusBadge status={action.status} />}
                            />
                        ))}
                    </ul>
                    {token ? (
                        <div className="p-3 text-center">
                            <GlassButton size="sm" variant="ghost" onClick={() => void loadMore()} disabled={loadingMore}>
                                {loadingMore ? <Loader2 size={14} className="animate-spin" /> : null}
                                Load more
                            </GlassButton>
                        </div>
                    ) : null}
                </>
            ) : (
                <ListMessage>{search ? 'No outgoing actions match this search.' : 'No outgoing email or invitations are waiting.'}</ListMessage>
            )}
        </>
    );

    const summary = selectedId ? items.find((item) => item.id === selectedId) : undefined;
    const detail = selectedId ? (
        <PendingActionDetail key={selectedId} actionId={selectedId} initial={summary} onUpdated={replaceItem} />
    ) : (
        <DetailEmpty title="Select an outgoing action" description="Review its recipients and content before you send or cancel it." />
    );

    return (
        <ApprovalSplit
            listLabel="Outgoing actions"
            hasSelection={Boolean(selectedId)}
            onBack={() => navigate('/approvals/outgoing')}
            list={list}
            detail={detail}
        />
    );
}

function PendingActionDetail({
    actionId,
    initial,
    onUpdated,
}: {
    actionId: string;
    initial?: PendingAction;
    onUpdated: (action: PendingAction) => void;
}) {
    const safeId = normalizePendingActionId(actionId);
    // The detail shows one action, so it keeps a store of its own instead of the chat's.
    const [store] = useState(() => createPendingActionsStore({ scope: 'detail', onUpdated }));

    useEffect(() => {
        if (!safeId) return undefined;
        const api = store.getState();
        // The list row is shown while the server's current copy loads; the copy is what can be sent.
        if (initial && initial.id === safeId) api.remember(initial);
        void api.loadById(safeId);
        return () => store.getState().reset();
        // The seed is only the first paint; a list update must not restart the load.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [safeId, store]);

    if (!safeId) {
        return (
            <div className="p-6">
                <Notice tone="danger">The outgoing action could not be loaded.</Notice>
            </div>
        );
    }

    return (
        <PendingActionsProvider store={store}>
            <PendingActionDetailBody actionId={safeId} />
        </PendingActionsProvider>
    );
}

function PendingActionDetailBody({ actionId }: { actionId: string }) {
    const present = usePendingActions((state) => Boolean(state.entries[actionId]));
    const load = usePendingActions((state) => state.detail[actionId]);

    if (present) return <PendingActionCard id={actionId} variant="detail" />;
    if (load?.status === 'error') {
        return (
            <div className="p-6">
                <Notice tone="danger">{load.message}</Notice>
            </div>
        );
    }
    return (
        <div className="space-y-3 p-6" aria-busy="true">
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-24 w-full" />
        </div>
    );
}
