// PendingActionCard.tsx
// One saved Microsoft 365 email or calendar invitation that is waiting for its owner.
//
// The same card is drawn in two places: the Approvals detail ("detail") and inline in the chat
// under the reply that saved it ("inline"). Both read the store of their nearest provider, so a
// card follows the same rules wherever it is: Send and Cancel always carry the version that was
// reviewed, the server's answer is authoritative, and nothing is ever sent automatically by the
// browser.

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ExternalLink, Loader2, RefreshCw, Send, X } from 'lucide-react';
import {
    formatDateTime,
    pendingActionHeading,
    pendingActionNeedsFullReview,
    pendingActionSendRoute,
    pendingActionStatusText,
    textList,
} from '../../lib/approvalsApi';
import { chatHrefForPendingAction } from '../../lib/conversationUrl';
import { M365_CHAT_CONNECTION_HREF, M365_CONNECT_HREF } from '../../lib/m365Links';
import {
    actionSubject,
    countdownText,
    isActionableStatus,
    needsTicking,
    safeApprovalDecisionHref,
    safeWebLinkUrl,
} from '../../lib/m365PendingActions';
import { canChangeEntry, usePendingActions, usePendingActionsStoreApi } from '../../stores/m365PendingActionsStore';
import { GlassButton } from '../ui/primitives';
import { DetailShell, Fact, Facts, Notice, StatusBadge } from './ApprovalParts';

export type PendingActionCardVariant = 'detail' | 'inline';

const LINK_CLASS = 'inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm text-accent hover:bg-accent-soft';

export function PendingActionCard({ id, variant = 'detail' }: { id: string; variant?: PendingActionCardVariant }) {
    const store = usePendingActionsStoreApi();
    const entry = usePendingActions((state) => state.entries[id]);
    const [, setNow] = useState(0);
    const ticking = entry ? needsTicking(entry.action) : false;
    const inline = variant === 'inline';

    // A scheduled or sending action repaints its countdown each second and asks the server again
    // when its status is due; the store decides whether a request is actually needed.
    useEffect(() => {
        if (!ticking) return undefined;
        const timer = window.setInterval(() => {
            setNow(Date.now());
            store.getState().pollIfDue(id);
        }, 1000);
        return () => window.clearInterval(timer);
    }, [id, store, ticking]);

    if (!entry) return null;

    const { action, busy, notice, auth, approvalRequired, bodyOpen } = entry;
    const loading = entry.refreshing;
    const api = store.getState();
    const summary = action.summary ?? {};
    const fullReview = pendingActionNeedsFullReview(action);
    const route = pendingActionSendRoute(action);
    const actionable = isActionableStatus(action.status);
    const canChange = canChangeEntry(entry);
    const webLink = safeWebLinkUrl(action.web_link);
    const approvalId = (() => {
        const approvals = approvalRequired?.approvals;
        const first = Array.isArray(approvals) ? (approvals[0] as { id?: unknown } | undefined)?.id : undefined;
        const value = typeof first === 'string' ? first : approvalRequired?.approval_id;
        return typeof value === 'string' ? value : '';
    })();
    const ownerOnlyNote =
        actionable &&
        !route &&
        (action.can_cancel !== true || action.viewer_is_owner === false) &&
        !action.requires_recreation &&
        !fullReview;

    const content = (
        <>
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
                    onToggle={(event) => api.setBodyOpen(id, (event.target as HTMLDetailsElement).open)}
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
                    {/* The countdown changes every second, so inline (inside the chat's live region) it stays out of the accessibility tree. */}
                    <p className="text-text-3" data-testid="v2-pending-action-countdown" aria-hidden={inline ? 'true' : undefined}>
                        {countdownText(action)}
                    </p>
                </div>
            ) : null}
            {notice ? (
                <Notice tone={notice.tone} testId="v2-pending-action-notice">
                    {notice.text}
                </Notice>
            ) : null}
            {ownerOnlyNote ? (
                <p className="text-sm text-text-3">
                    {action.workflow_id
                        ? 'Only the selected Run as user can send or cancel this action.'
                        : 'Only the action owner can send or cancel this action. This view is read-only.'}
                </p>
            ) : null}

            <div className="flex flex-wrap gap-2" data-testid="v2-pending-action-controls">
                {fullReview ? (
                    <GlassButton
                        size="sm"
                        variant="ghost"
                        disabled={busy || loading || entry.reviewing}
                        onClick={() => void api.reviewFull(id)}
                    >
                        {action.graph_resource_type === 'calendar' ? 'Review full invitation' : 'Review full message'}
                    </GlassButton>
                ) : null}
                {actionable && route ? (
                    <GlassButton
                        size="sm"
                        variant="primary"
                        disabled={!canChange || Boolean(auth) || Boolean(approvalRequired)}
                        onClick={() => void api.submit(id, route)}
                        data-testid="v2-pending-action-send"
                    >
                        {busy ? <Loader2 size={14} className="animate-spin motion-reduce:animate-none" /> : <Send size={14} />}
                        {action.action_mode === 'delayed' ? 'Send now' : 'Send'}
                    </GlassButton>
                ) : null}
                {actionable && action.can_cancel === true && action.viewer_is_owner !== false ? (
                    <GlassButton
                        size="sm"
                        variant="ghost"
                        disabled={!canChange}
                        onClick={() => void api.submit(id, 'cancel')}
                        data-testid="v2-pending-action-cancel"
                    >
                        <X size={14} />
                        Cancel
                    </GlassButton>
                ) : null}
                {approvalRequired && actionable ? (
                    <Link to={safeApprovalDecisionHref(approvalId)} className={LINK_CLASS}>
                        Review sharing decision
                    </Link>
                ) : null}
                {auth && action.viewer_is_owner !== false ? (
                    <>
                        {!action.workflow_id ? (
                            <GlassButton size="sm" variant="ghost" disabled={busy} onClick={() => void api.reconnect(id)}>
                                Reconnect Microsoft 365
                            </GlassButton>
                        ) : null}
                        <Link
                            to={action.workflow_id ? M365_CONNECT_HREF : M365_CHAT_CONNECTION_HREF}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={LINK_CLASS}
                        >
                            {action.workflow_id ? 'Reconnect workflow account in Settings' : 'Open Microsoft 365 settings'}
                        </Link>
                    </>
                ) : null}
                <GlassButton
                    size="sm"
                    variant="ghost"
                    disabled={busy || loading}
                    onClick={() => void api.refresh(id, { clearNotice: true })}
                >
                    {loading ? <Loader2 size={14} className="animate-spin motion-reduce:animate-none" /> : <RefreshCw size={14} />}
                    Refresh status
                </GlassButton>
                {webLink ? (
                    <a href={webLink} target="_blank" rel="noopener noreferrer" className={LINK_CLASS}>
                        <ExternalLink size={14} />
                        Open in Microsoft 365
                    </a>
                ) : null}
                {!inline && action.conversation_id ? (
                    <Link to={chatHrefForPendingAction(action.conversation_id, action.id)} className={LINK_CLASS}>
                        Open conversation
                    </Link>
                ) : null}
            </div>
        </>
    );

    if (!inline) {
        return (
            <DetailShell
                title={actionSubject(action)}
                subtitle={pendingActionHeading(action)}
                badge={<StatusBadge status={action.status} />}
            >
                {content}
            </DetailShell>
        );
    }

    return (
        <article
            data-pending-action-id={id}
            data-testid="v2-pending-action-card"
            tabIndex={-1}
            aria-label={`${pendingActionHeading(action)}: ${actionSubject(action)}`}
            className="space-y-3 rounded-2xl border border-edge bg-surface-1 p-4 text-left transition-shadow motion-reduce:transition-none data-[highlighted=true]:ring-2 data-[highlighted=true]:ring-accent"
        >
            <header className="flex flex-wrap items-start gap-3">
                <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold break-words text-text-1">{actionSubject(action)}</p>
                    <p className="mt-0.5 text-xs text-text-3">{pendingActionHeading(action)}</p>
                </div>
                <StatusBadge status={action.status} />
            </header>
            {content}
        </article>
    );
}
