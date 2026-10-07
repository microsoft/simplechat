// PausedRequestsPanel.tsx
// Microsoft 365 chat requests that paused for an approval or a sign-in.
//
// Resuming only queues the saved request again; its answer appears in the original
// conversation. Requests that need recovery cannot be resumed from here, and workflow
// requests are fixed by reconnecting the workflow's account in Profile.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Loader2, Play, PlugZap } from 'lucide-react';
import {
    PAUSED_STATUS_LABELS,
    errorMessage,
    fetchPausedRequests,
    formatDateTime,
    resumePausedRequest,
    type PausedRequest,
} from '../../lib/approvalsApi';
import { chatHrefForConversation } from '../../lib/conversationUrl';
import { M365_PROFILE_CONNECTION_HREF, connectMicrosoft365, m365Sources } from '../../lib/m365Connect';
import { GlassButton, Skeleton } from '../ui/primitives';
import {
    ApprovalSplit,
    DetailEmpty,
    DetailShell,
    Fact,
    Facts,
    ListMessage,
    ListRow,
    ListToolbar,
    Notice,
    StatusBadge,
} from './ApprovalParts';

function statusLabel(status: string): string {
    return PAUSED_STATUS_LABELS[status] ?? status.replace(/_/g, ' ');
}

function requestTitle(item: PausedRequest): string {
    return item.workflow_id ? `Workflow: ${item.workflow_id}` : `Conversation: ${item.conversation_id ?? 'unknown'}`;
}

export function PausedRequestsPanel({
    selectedId,
    reloadKey,
    onCountChange,
}: {
    selectedId?: string;
    reloadKey: number;
    onCountChange?: (count: number) => void;
}) {
    const navigate = useNavigate();
    const [items, setItems] = useState<PausedRequest[]>([]);
    const [token, setToken] = useState('');
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [loadError, setLoadError] = useState('');
    const [search, setSearch] = useState('');

    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setLoadError('');
        fetchPausedRequests('', controller.signal)
            .then((page) => {
                setItems(page.items);
                setToken(page.continuationToken);
            })
            .catch((error) => {
                if (controller.signal.aborted) return;
                setItems([]);
                setToken('');
                setLoadError(errorMessage(error, 'Waiting Microsoft 365 requests could not be loaded.'));
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoading(false);
            });
        return () => controller.abort();
    }, [reloadKey]);

    useEffect(() => {
        onCountChange?.(items.length);
    }, [items, onCountChange]);

    const loadMore = async () => {
        if (!token) return;
        setLoadingMore(true);
        try {
            const page = await fetchPausedRequests(token);
            setItems((current) => {
                const seen = new Set(current.map((item) => item.id));
                return [...current, ...page.items.filter((item) => !seen.has(item.id))];
            });
            setToken(page.continuationToken);
        } catch (error) {
            setLoadError(errorMessage(error, 'More waiting requests could not be loaded.'));
        } finally {
            setLoadingMore(false);
        }
    };

    const filtered = useMemo(() => {
        const query = search.trim().toLowerCase();
        if (!query) return items;
        return items.filter((item) => `${requestTitle(item)} ${statusLabel(item.status)}`.toLowerCase().includes(query));
    }, [items, search]);

    const selected = selectedId ? items.find((item) => item.id === selectedId) : undefined;

    const list = (
        <>
            <ListToolbar search={search} onSearch={setSearch} searchLabel="Search waiting requests" />
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
                        {filtered.map((item) => (
                            <ListRow
                                key={item.id}
                                active={item.id === selectedId}
                                onSelect={() => navigate(`/approvals/paused/${encodeURIComponent(item.id)}`)}
                                title={requestTitle(item)}
                                testId={`v2-paused-request-row-${item.id}`}
                                meta={formatDateTime(item.updated_at || item.created_at)}
                                badge={<StatusBadge status={item.status} label={statusLabel(item.status)} />}
                            />
                        ))}
                    </ul>
                    {token ? (
                        <div className="p-3 text-center">
                            <GlassButton size="sm" variant="ghost" onClick={() => void loadMore()} disabled={loadingMore}>
                                {loadingMore ? <Loader2 size={14} className="animate-spin" /> : null}
                                More waiting requests
                            </GlassButton>
                        </div>
                    ) : null}
                </>
            ) : (
                <ListMessage>{search ? 'No waiting requests match this search.' : 'No Microsoft 365 requests are waiting.'}</ListMessage>
            )}
        </>
    );

    let detail;
    if (!selectedId) {
        detail = <DetailEmpty title="Select a waiting request" description="Resume it, or connect Microsoft 365 so it can continue." />;
    } else if (!selected) {
        detail = loading ? (
            <div className="p-6">
                <Skeleton className="h-24 w-full" />
            </div>
        ) : (
            <DetailEmpty title="This request is no longer waiting" description="It may have resumed or been removed. Refresh the list to check." />
        );
    } else {
        detail = <PausedRequestDetail key={selected.id} item={selected} />;
    }

    return (
        <ApprovalSplit
            listLabel="Waiting Microsoft 365 requests"
            hasSelection={Boolean(selectedId)}
            onBack={() => navigate('/approvals/paused')}
            list={list}
            detail={detail}
        />
    );
}

function PausedRequestDetail({ item }: { item: PausedRequest }) {
    const [busy, setBusy] = useState(false);
    const [notice, setNotice] = useState<{ text: string; tone: 'info' | 'warn' } | null>(null);
    const [authSources, setAuthSources] = useState<unknown>(item.status === 'awaiting_sign_in' ? item.sources : null);

    const resume = useCallback(async () => {
        setBusy(true);
        try {
            const result = await resumePausedRequest(item.id);
            if (result.auth_required) {
                setAuthSources(result.sources ?? item.sources ?? []);
                setNotice({ text: result.message || 'Connect Microsoft 365 to continue this saved chat request.', tone: 'warn' });
            } else {
                setAuthSources(null);
                setNotice({ text: 'Request queued. Its result will appear in the original conversation.', tone: 'info' });
            }
        } catch (error) {
            setNotice({ text: errorMessage(error, 'The request could not be resumed.'), tone: 'warn' });
        } finally {
            setBusy(false);
        }
    }, [item.id, item.sources]);

    const connectAndResume = async () => {
        setBusy(true);
        try {
            await connectMicrosoft365(m365Sources(authSources));
        } catch (error) {
            setNotice({ text: errorMessage(error, 'Sign-in was not confirmed.'), tone: 'warn' });
            setBusy(false);
            return;
        }
        await resume();
    };

    const queued = notice?.tone === 'info';

    return (
        <DetailShell
            title={requestTitle(item)}
            subtitle="Waiting Microsoft 365 request"
            badge={<StatusBadge status={item.status} label={statusLabel(item.status)} />}
        >
            <Facts>
                <Fact label="Status">{statusLabel(item.status)}</Fact>
                <Fact label="Workflow">{item.workflow_id}</Fact>
                <Fact label="Conversation">{item.conversation_id}</Fact>
                <Fact label="Updated">{formatDateTime(item.updated_at || item.created_at)}</Fact>
            </Facts>
            {notice ? <Notice tone={notice.tone} testId="v2-paused-request-notice">{notice.text}</Notice> : null}
            {item.status === 'recovery_required' ? (
                <Notice tone="warn">This request needs recovery and cannot be resumed from here.</Notice>
            ) : null}
            <div className="flex flex-wrap gap-2">
                {item.workflow_id ? (
                    <a
                        href={M365_PROFILE_CONNECTION_HREF}
                        className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm text-accent hover:bg-accent-soft"
                    >
                        Review Microsoft 365 connection
                    </a>
                ) : authSources && !queued ? (
                    <GlassButton size="sm" variant="primary" disabled={busy} onClick={() => void connectAndResume()} data-testid="v2-paused-request-connect">
                        {busy ? <Loader2 size={14} className="animate-spin" /> : <PlugZap size={14} />}
                        Connect Microsoft 365 and continue
                    </GlassButton>
                ) : item.status !== 'recovery_required' && !queued ? (
                    <GlassButton size="sm" variant="primary" disabled={busy} onClick={() => void resume()} data-testid="v2-paused-request-resume">
                        {busy ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                        Resume request
                    </GlassButton>
                ) : null}
                {item.conversation_id && !item.workflow_id ? (
                    <Link
                        to={chatHrefForConversation(item.conversation_id)}
                        className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm text-accent hover:bg-accent-soft"
                    >
                        Open conversation
                    </Link>
                ) : null}
            </div>
        </DetailShell>
    );
}
