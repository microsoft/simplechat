// PendingActionsPanel.tsx
// Outgoing Microsoft 365 email and calendar invitations waiting to be sent.
//
// Ports the classic m365-pending-actions card into the list/detail layout. Send and Cancel
// always carry the version the user reviewed; the server rejects a stale version, and the
// detail then shows the server's current state instead of retrying anything.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ExternalLink, Loader2, RefreshCw, Send, X } from 'lucide-react';
import { ApiError } from '../../lib/apiClient';
import {
    ACTIONABLE_PENDING_STATUSES,
    canChangePendingAction,
    errorMessage,
    fetchPendingAction,
    fetchPendingActions,
    formatDateTime,
    isPendingAction,
    m365ErrorPayload,
    mutatePendingAction,
    pendingActionHeading,
    pendingActionNeedsFullReview,
    pendingActionSendRoute,
    pendingActionStatusText,
    textList,
    type PendingAction,
} from '../../lib/approvalsApi';
import { chatHrefForConversation } from '../../lib/conversationUrl';
import { connectMicrosoft365, m365Sources } from '../../lib/m365Connect';
import { M365_CHAT_CONNECTION_HREF, M365_CONNECT_HREF } from '../../lib/m365Links';
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

type Tone = 'info' | 'warn' | 'danger' | 'ok';

function safeWebLinkUrl(value: unknown): string {
    if (typeof value !== 'string' || !value) return '';
    try {
        const url = new URL(value);
        return url.protocol === 'https:' && !url.username && !url.password ? url.href : '';
    } catch {
        return '';
    }
}

function safeApprovalDecisionHref(value: unknown): string {
    return typeof value === 'string' && value
        ? `/approvals/m365/${encodeURIComponent(value)}`
        : '/approvals/m365';
}

function countdownText(action: PendingAction): string {
    const due = Date.parse(action.auto_send_at_utc ?? '');
    if (!Number.isFinite(due)) return 'The scheduled time is unavailable. Refresh status to check it.';
    const seconds = Math.max(0, Math.ceil((due - Date.now()) / 1000));
    return seconds
        ? `Scheduled in ${Math.floor(seconds / 60)}m ${seconds % 60}s.`
        : 'Scheduled time reached. Waiting for the server delivery status.';
}

function actionSubject(action: PendingAction): string {
    return action.subject || action.summary?.subject || '(No subject)';
}

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
    const [action, setAction] = useState<PendingAction | null>(initial ?? null);
    const [loading, setLoading] = useState(!initial);
    const [busy, setBusy] = useState(false);
    const [notice, setNotice] = useState<{ text: string; tone: Tone } | null>(null);
    const [needsRefresh, setNeedsRefresh] = useState(false);
    const [denied, setDenied] = useState(false);
    const [authRequired, setAuthRequired] = useState<Record<string, unknown> | null>(null);
    const [approvalRequired, setApprovalRequired] = useState<Record<string, unknown> | null>(null);
    const [bodyOpen, setBodyOpen] = useState(false);
    const [, setNow] = useState(0);

    const remember = useCallback(
        (next: PendingAction) => {
            setAction(next);
            onUpdated(next);
        },
        [onUpdated],
    );

    const refresh = useCallback(
        async (options: { clearNotice?: boolean; signal?: AbortSignal } = {}): Promise<PendingAction | null> => {
            setLoading(true);
            try {
                const next = await fetchPendingAction(actionId, options.signal);
                remember(next);
                setNeedsRefresh(false);
                setDenied(false);
                if (options.clearNotice) {
                    setNotice({ text: 'Current server status loaded. Review the saved action before choosing Send or Cancel.', tone: 'info' });
                }
                return next;
            } catch (error) {
                if (options.signal?.aborted) return null;
                const status = error instanceof ApiError ? error.status : 0;
                setNeedsRefresh(true);
                setDenied(status === 403 || status === 404);
                setNotice({
                    text:
                        status === 403
                            ? 'You do not have permission to access this action. No action was sent.'
                            : 'The current action status could not be checked. Refresh status before trying again.',
                    tone: 'warn',
                });
                if (status === 401 || m365ErrorPayload(error).auth_required === true) {
                    setAuthRequired(m365ErrorPayload(error));
                }
                return null;
            } finally {
                if (!options.signal?.aborted) setLoading(false);
            }
        },
        [actionId, remember],
    );

    useEffect(() => {
        const controller = new AbortController();
        void refresh({ signal: controller.signal });
        return () => controller.abort();
    }, [refresh]);

    const scheduled =
        action?.will_auto_send === true &&
        ACTIONABLE_PENDING_STATUSES.has(action.status) &&
        Number.isFinite(Date.parse(action.auto_send_at_utc ?? ''));
    useEffect(() => {
        if (!scheduled && action?.status !== 'sending') return undefined;
        const timer = window.setInterval(() => setNow(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, [scheduled, action?.status]);

    if (!action) {
        return loading ? (
            <div className="space-y-3 p-6" aria-busy="true">
                <Skeleton className="h-6 w-1/2" />
                <Skeleton className="h-24 w-full" />
            </div>
        ) : (
            <div className="p-6">
                <Notice tone="danger">{notice?.text ?? 'The outgoing action could not be loaded.'}</Notice>
            </div>
        );
    }

    const summary = action.summary ?? {};
    const fullReview = pendingActionNeedsFullReview(action);
    const route = pendingActionSendRoute(action);
    const actionable = ACTIONABLE_PENDING_STATUSES.has(action.status);
    const canChange = !busy && !loading && !needsRefresh && !denied && canChangePendingAction(action);
    const webLink = safeWebLinkUrl(action.web_link);
    const approvalId = (() => {
        const approvals = approvalRequired?.approvals;
        const first = Array.isArray(approvals) ? (approvals[0] as { id?: unknown } | undefined)?.id : undefined;
        const id = typeof first === 'string' ? first : approvalRequired?.approval_id;
        return typeof id === 'string' ? id : '';
    })();

    const reviewFull = async () => {
        setNotice({ text: 'Loading the complete saved content for review. This review does not send the action.', tone: 'info' });
        const next = await refresh();
        if (!next) return;
        if (!pendingActionNeedsFullReview(next) && typeof next.summary?.body_preview === 'string') {
            setBodyOpen(true);
            setNotice({ text: 'Complete saved content loaded. Review the recipients and full content before sending.', tone: 'info' });
        } else {
            setNeedsRefresh(true);
            setNotice({ text: 'The complete saved content could not be verified. Review full details again before sending.', tone: 'warn' });
        }
    };

    const submit = async (operation: 'send-now' | 'approve' | 'cancel') => {
        const allowed = operation === 'cancel' ? action.can_cancel === true : Boolean(route) && !authRequired && !approvalRequired;
        if (!canChange || !allowed || !action.version) return;
        setBusy(true);
        setNotice({ text: operation === 'cancel' ? 'Cancelling this saved action…' : 'Submitting this saved action…', tone: 'info' });
        try {
            const next = await mutatePendingAction(action.id, operation, action.version);
            remember(next);
            setAuthRequired(null);
            setDenied(false);
            setNotice({
                text:
                    operation === 'cancel'
                        ? 'Cancellation checked. The server status below is authoritative; this does not recall an already sent item.'
                        : 'Send request checked. Review the server status and delivery note below.',
                tone: 'info',
            });
        } catch (error) {
            const payload = m365ErrorPayload(error);
            const status = error instanceof ApiError ? error.status : 0;
            if (isPendingAction(payload.pending_action) && payload.pending_action.id === action.id) {
                remember(payload.pending_action);
            }
            if (payload.approval_required === true) {
                setApprovalRequired(payload);
                setNotice({
                    text: 'Review the saved Microsoft 365 sharing decision before sending. Approving it does not send this action; return here and select Send again.',
                    tone: 'warn',
                });
            } else if (status === 401 || payload.auth_required === true) {
                setAuthRequired(payload);
                setNotice({
                    text: 'Microsoft 365 sign-in is required. Reconnect, review this same saved action, then select Send again. Signing in does not send it.',
                    tone: 'warn',
                });
            } else if (status === 403) {
                setDenied(true);
                setNotice({ text: 'You do not have permission to change this action. Refresh status to check your current access.', tone: 'warn' });
            } else if (status === 409) {
                setNotice({
                    text: 'This action changed or is already being processed. Review its current status and details before making another choice.',
                    tone: 'warn',
                });
                if (!isPendingAction(payload.pending_action)) await refresh();
            } else {
                const refreshed = await refresh();
                setNotice({
                    text: refreshed
                        ? 'The response was not confirmed. Current server status has been refreshed. Review it before making another choice; no send was retried automatically.'
                        : 'The response was not confirmed. Checking the current server status; the send will not be retried automatically.',
                    tone: 'warn',
                });
            }
        } finally {
            setBusy(false);
        }
    };

    const reconnect = async () => {
        if (busy) return;
        setBusy(true);
        const reviewedVersion = action.version;
        setNotice({ text: 'Opening sign-in for this saved action. No chat request will be resumed and nothing will be sent.', tone: 'info' });
        try {
            const fromPayload = m365Sources(authRequired?.sources);
            await connectMicrosoft365(fromPayload.length ? fromPayload : [action.graph_resource_type === 'calendar' ? 'calendar' : 'email']);
            const next = await refresh({ clearNotice: true });
            if (next && next.version === reviewedVersion) setAuthRequired(null);
        } catch (error) {
            setNotice({ text: errorMessage(error, 'Sign-in was not confirmed. No action was sent.'), tone: 'warn' });
        } finally {
            setBusy(false);
        }
    };

    const ownerOnlyNote =
        actionable &&
        !route &&
        (action.can_cancel !== true || action.viewer_is_owner === false) &&
        !action.requires_recreation &&
        !fullReview;

    return (
        <DetailShell
            title={actionSubject(action)}
            subtitle={pendingActionHeading(action)}
            badge={<StatusBadge status={action.status} />}
        >
            <p role="status" aria-live="polite" className="text-sm text-text-2" data-testid="v2-pending-action-status">
                {pendingActionStatusText(action)}
            </p>
            <Facts>
                <Fact label="To">{textList(summary.to_recipients)}</Fact>
                <Fact label="CC">{textList(summary.cc_recipients)}</Fact>
                <Fact label="BCC">{textList(summary.bcc_recipients)}</Fact>
                <Fact label="Attendees">{textList(summary.attendee_recipients)}</Fact>
                <Fact label="Start">{summary.start_datetime}</Fact>
                <Fact label="End">{summary.end_datetime}</Fact>
                <Fact label="Time zone">{summary.timezone}</Fact>
                <Fact label="Location">{summary.location}</Fact>
                <Fact label="Teams meeting">
                    {typeof summary.teams_meeting_requested === 'boolean' ? (summary.teams_meeting_requested ? 'Requested' : 'Not requested') : ''}
                </Fact>
            </Facts>

            {typeof summary.body_preview === 'string' ? (
                <details
                    open={bodyOpen}
                    onToggle={(event) => setBodyOpen((event.target as HTMLDetailsElement).open)}
                    className="rounded-xl border border-edge p-3"
                >
                    <summary className="cursor-pointer text-sm font-medium text-text-1">
                        {fullReview ? 'Message preview' : 'Review message body'}
                    </summary>
                    <pre className="mt-2 text-sm break-words whitespace-pre-wrap text-text-1" data-testid="v2-pending-action-body">
                        {summary.body_preview}
                    </pre>
                    {String(summary.content_type ?? '').toLowerCase() === 'html' ? (
                        <p className="mt-1 text-xs text-text-3">HTML content is displayed as text, not executed.</p>
                    ) : null}
                </details>
            ) : null}

            {fullReview ? (
                <Notice tone="info">
                    {`This is a shortened preview${
                        Number.isSafeInteger(summary.body_length) && (summary.body_length ?? -1) >= 0
                            ? ` (${(summary.body_length as number).toLocaleString()} characters total)`
                            : ''
                    }. Review the complete saved content before sending.`}
                </Notice>
            ) : null}
            {(actionable && (action.requires_recreation === true || action.requires_review === true)) || action.review_message ? (
                <Notice tone="warn">
                    {action.review_message ||
                        (action.requires_recreation
                            ? 'This legacy action cannot be safely sent. Review and recreate it if still needed, or cancel it.'
                            : 'Review the refreshed action details before sending.')}
                </Notice>
            ) : null}
            {action.error ? <Notice tone="warn">{action.error}</Notice> : null}
            {action.delivery_note ? <Notice tone="info">{action.delivery_note}</Notice> : null}
            {action.will_auto_send === true && actionable ? (
                <div className="text-sm">
                    <p className="text-text-1">{`Server-scheduled delivery: ${formatDateTime(action.auto_send_at_utc)}.`}</p>
                    <p className="text-text-3" data-testid="v2-pending-action-countdown">{countdownText(action)}</p>
                </div>
            ) : null}
            {notice ? <Notice tone={notice.tone} testId="v2-pending-action-notice">{notice.text}</Notice> : null}
            {ownerOnlyNote ? (
                <p className="text-sm text-text-3">
                    {action.workflow_id
                        ? 'Only the selected Run as user can send or cancel this action.'
                        : 'Only the action owner can send or cancel this action. This view is read-only.'}
                </p>
            ) : null}

            <div className="flex flex-wrap gap-2" data-testid="v2-pending-action-controls">
                {fullReview ? (
                    <GlassButton size="sm" variant="ghost" disabled={busy || loading} onClick={() => void reviewFull()}>
                        {action.graph_resource_type === 'calendar' ? 'Review full invitation' : 'Review full message'}
                    </GlassButton>
                ) : null}
                {actionable && route ? (
                    <GlassButton
                        size="sm"
                        variant="primary"
                        disabled={!canChange || Boolean(authRequired) || Boolean(approvalRequired)}
                        onClick={() => void submit(route)}
                        data-testid="v2-pending-action-send"
                    >
                        {busy ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                        {action.action_mode === 'delayed' ? 'Send now' : 'Send'}
                    </GlassButton>
                ) : null}
                {actionable && action.can_cancel === true && action.viewer_is_owner !== false ? (
                    <GlassButton
                        size="sm"
                        variant="ghost"
                        disabled={!canChange}
                        onClick={() => void submit('cancel')}
                        data-testid="v2-pending-action-cancel"
                    >
                        <X size={14} />
                        Cancel
                    </GlassButton>
                ) : null}
                {approvalRequired && actionable ? (
                    <Link
                        to={safeApprovalDecisionHref(approvalId)}
                        className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm text-accent hover:bg-accent-soft"
                    >
                        Review sharing decision
                    </Link>
                ) : null}
                {authRequired && action.viewer_is_owner !== false ? (
                    <>
                        {!action.workflow_id ? (
                            <GlassButton size="sm" variant="ghost" disabled={busy} onClick={() => void reconnect()}>
                                Reconnect Microsoft 365
                            </GlassButton>
                        ) : null}
                        <Link
                            to={action.workflow_id ? M365_CONNECT_HREF : M365_CHAT_CONNECTION_HREF}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm text-accent hover:bg-accent-soft"
                        >
                            {action.workflow_id ? 'Reconnect workflow account in Settings' : 'Open Microsoft 365 settings'}
                        </Link>
                    </>
                ) : null}
                <GlassButton size="sm" variant="ghost" disabled={busy || loading} onClick={() => void refresh({ clearNotice: true })}>
                    {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                    Refresh status
                </GlassButton>
                {webLink ? (
                    <a
                        href={safeWebLinkUrl(action.web_link)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm text-accent hover:bg-accent-soft"
                    >
                        <ExternalLink size={14} />
                        Open in Microsoft 365
                    </a>
                ) : null}
                {action.conversation_id ? (
                    <Link
                        to={chatHrefForConversation(action.conversation_id)}
                        className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm text-accent hover:bg-accent-soft"
                    >
                        Open conversation
                    </Link>
                ) : null}
            </div>
        </DetailShell>
    );
}
