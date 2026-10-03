// WorkflowAlertCard.tsx
// The full workflow alert, grown out of the notice when the reader opens it.
//
// It sits in the shared Modal shell, so Escape, the backdrop and focus behave as in every other
// V2 dialog: focus moves in when it opens, stays inside while it is open, and goes back where
// the reader was when it closes. The control that opened it -- the notice -- is gone by then,
// so the host below hands focus back itself.
//
// The card shows one entry at a time: an alert, or every alert one workflow raised together.
// "1 of 3" and Next step through what is waiting. Open and Dismiss act on the entry shown,
// and Mark all read on every entry, one alert at a time -- never the bell's own Mark all read,
// which would also clear notices the card never showed.
//
// It says just enough to decide: why the alert came, its summary, and one Open button to the
// place the workflow made. The detail, the facts and every other way in wait under Show more.
//
// Every word here is the alert's own text, rendered as text. Its links are checked by the
// bell's resolver and followed by the bell's navigation, so only this site's pages open.

import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { clsx } from 'clsx';
import { ArrowRight, ChevronDown, ChevronRight, X } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';
import { resolveNotificationLink, type NotificationTarget } from '../../lib/notificationLinks';
import { formatRelativeTime } from '../../lib/userStats';
import { growFromRect } from '../../lib/workflowAlertMotion';
import { openWorkflowResultInChat } from '../../lib/workflowResultFollowUp';
import {
    WORKFLOW_ALERT_CREATED_LINK_LABEL,
    WORKFLOW_ALERT_PRIORITY_LABELS,
    describeWorkflowAlertGroup,
    describeWorkflowAlertReason,
    formatWorkflowAlertClock,
    workflowAlertFollowUpAction,
    workflowAlertOpenRunPath,
    workflowAlertServerReason,
    workflowAlertWorkflowPath,
    type WorkflowAlert,
    type WorkflowAlertEntry,
} from '../../lib/workflowAlertNotices';
import { WORKFLOW_ALERT_SEVERITIES, type WorkflowAlertSeverity } from '../../lib/workflowAlerts';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import {
    WORKFLOW_ALERT_UI_ATTRIBUTE,
    useWorkflowAlertStore,
    workflowAlertReturnFocusTarget,
} from '../../stores/workflowAlertStore';
import { workflowAlertIcon, workflowAlertKindLabel, workflowAlertTone } from './workflowAlertTone';

/** Busy buttons stay focusable, so a keyboard user's place survives the request. */
const BUSY_CLASS = 'aria-disabled:cursor-not-allowed aria-disabled:opacity-50';

function severityLabel(value: string): string {
    return (WORKFLOW_ALERT_SEVERITIES as readonly string[]).includes(value)
        ? WORKFLOW_ALERT_PRIORITY_LABELS[value as WorkflowAlertSeverity]
        : value.charAt(0).toUpperCase() + value.slice(1);
}

/** "schedule" or "agent_run" as the chips say it. */
function readable(value: string): string {
    const spaced = value.replace(/[_-]+/g, ' ').trim();
    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function chipsFor(alert: WorkflowAlert): string[] {
    return [
        ...alert.enrichments,
        alert.triggerSource ? `Trigger: ${readable(alert.triggerSource)}` : '',
        alert.runnerType ? `Runner: ${readable(alert.runnerType)}` : '',
        alert.agentName ? `Agent: ${alert.agentName}` : '',
    ].filter(Boolean);
}

interface CardLink {
    label: string;
    target: NotificationTarget;
}

/** A way into what the alert is about, with the data attribute that names which kind it is. */
interface CardAction extends CardLink {
    marker: 'data-workflow-alert-link' | 'data-workflow-alert-open-run' | 'data-workflow-alert-open-workflow';
}

function CardBanner({ entry, onClose }: { entry: WorkflowAlertEntry; onClose: () => void }) {
    const alert = entry.lead;
    const tone = workflowAlertTone(entry.priority);
    const Icon = workflowAlertIcon(entry.priority, alert.category);
    const group = describeWorkflowAlertGroup(entry);
    const when = alert.createdMs !== null
        ? `${formatRelativeTime(alert.createdAt)} · ${formatWorkflowAlertClock(alert.createdMs)}`
        : null;

    return (
        <div
            data-workflow-alert-band=""
            className={clsx('flex items-start gap-3 rounded-t-[15px] border-b border-edge px-4 py-3', tone.band)}
        >
            <Icon size={20} aria-hidden="true" className={clsx('mt-0.5 shrink-0', tone.bandIcon)} />
            <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold">
                    {WORKFLOW_ALERT_PRIORITY_LABELS[entry.priority]} priority · {workflowAlertKindLabel(alert.category)}
                </p>
                <h2 className="mt-0.5 text-base leading-snug font-semibold break-words">{alert.title}</h2>
                <p className={clsx('mt-1 text-xs break-words', tone.bandMuted)}>
                    <span>{alert.workflowName}</span>
                    {when && (
                        <>
                            {' · '}
                            <time dateTime={alert.createdAt}>{when}</time>
                        </>
                    )}
                </p>
                {group && (
                    <p data-workflow-alert-group="" className={clsx('mt-0.5 text-xs font-medium', tone.bandMuted)}>
                        {group}
                    </p>
                )}
            </div>
            <button
                type="button"
                data-workflow-alert-card-close=""
                onClick={onClose}
                aria-label="Close alert"
                title="Close"
                className={clsx(
                    'shrink-0 rounded-lg p-1 transition-colors hover:bg-surface-2',
                    tone.bandMuted,
                )}
            >
                <X size={16} aria-hidden="true" />
            </button>
        </div>
    );
}

function CardBody({ alert, more }: { alert: WorkflowAlert; more: ReactNode }) {
    const [expanded, setExpanded] = useState(false);
    const moreId = useId();
    const whyId = useId();
    const chips = chipsFor(alert);
    const serverReason = workflowAlertServerReason(alert);
    const hasMore = Boolean(alert.detail) || chips.length > 0 || Boolean(more);

    return (
        <div className="space-y-4">
            <section aria-labelledby={whyId} data-workflow-alert-why="">
                <h3 id={whyId} className="text-xs font-semibold text-text-2">Why you&apos;re seeing this</h3>
                <p className="mt-1 text-sm break-words text-text-1">{describeWorkflowAlertReason(alert)}</p>
                {serverReason && (
                    <p data-workflow-alert-server-reason="" className="mt-1 text-xs break-words text-text-2">{serverReason}</p>
                )}
                {alert.matchedRules.length > 0 && (
                    <ul className="mt-2 space-y-1.5" aria-label="Rules that matched">
                        {alert.matchedRules.map((rule, index) => (
                            <li
                                key={`${rule.name}-${index}`}
                                data-workflow-alert-rule=""
                                className="rounded-lg bg-surface-sunken px-2.5 py-1.5 text-xs"
                            >
                                <span className="font-medium break-words text-text-1">{rule.name}</span>
                                {rule.severity && (
                                    <span className="text-text-2"> · {severityLabel(rule.severity)}</span>
                                )}
                                {rule.reason && <span className="mt-0.5 block break-words text-text-2">{rule.reason}</span>}
                            </li>
                        ))}
                    </ul>
                )}
            </section>

            <section aria-label="Summary">
                <p data-workflow-alert-summary="" className="text-sm break-words text-text-1">{alert.summary}</p>
            </section>

            {alert.error && (
                <section
                    aria-label="What went wrong"
                    data-workflow-alert-error=""
                    className="rounded-lg border border-danger/30 bg-danger-soft px-3 py-2"
                >
                    <h3 className="text-xs font-semibold text-text-1">What went wrong</h3>
                    <p className="mt-1 text-sm whitespace-pre-wrap break-words text-text-1">{alert.error}</p>
                </section>
            )}

            {hasMore && (
                <div>
                    <button
                        type="button"
                        data-workflow-alert-show-more=""
                        aria-expanded={expanded}
                        aria-controls={moreId}
                        onClick={() => setExpanded((open) => !open)}
                        className="inline-flex items-center gap-1 rounded-md text-xs font-medium text-text-2 hover:text-text-1"
                    >
                        <ChevronDown
                            size={14}
                            aria-hidden="true"
                            className={clsx('transition-transform', expanded && 'rotate-180')}
                        />
                        {expanded ? 'Show less' : 'Show more'}
                    </button>
                    <div id={moreId} hidden={!expanded} data-workflow-alert-more-details="" className="mt-2 space-y-3">
                        {alert.detail && (
                            <div
                                data-workflow-alert-detail=""
                                className="rounded-lg bg-surface-sunken px-3 py-2 text-sm whitespace-pre-wrap break-words text-text-1"
                            >
                                {alert.detail}
                            </div>
                        )}
                        {chips.length > 0 && (
                            <ul aria-label="About this alert" className="flex flex-wrap gap-1.5">
                                {chips.map((chip) => (
                                    <li
                                        key={chip}
                                        data-workflow-alert-chip=""
                                        className="rounded-full border border-edge-strong px-2 py-0.5 text-xs break-words text-text-2"
                                    >
                                        {chip}
                                    </li>
                                ))}
                            </ul>
                        )}
                        {more}
                    </div>
                </div>
            )}
        </div>
    );
}

function WorkflowAlertCard({ onOpened }: { onOpened: () => void }) {
    const navigate = useNavigate();
    const { pathname } = useLocation();
    const entries = useWorkflowAlertStore((state) => state.entries);
    const cardIndex = useWorkflowAlertStore((state) => state.cardIndex);
    const busy = useWorkflowAlertStore((state) => state.busy);
    const closeCard = useWorkflowAlertStore((state) => state.closeCard);
    const nextEntry = useWorkflowAlertStore((state) => state.nextEntry);
    const markEntryRead = useWorkflowAlertStore((state) => state.markEntryRead);
    const dismissEntry = useWorkflowAlertStore((state) => state.dismissEntry);
    const markAllRead = useWorkflowAlertStore((state) => state.markAllRead);
    const openFromCard = useWorkflowAlertStore((state) => state.openFromCard);
    const workflowResultsEnabled = useBootstrapStore((state) =>
        state.data?.features?.enable_chat_workflow_results === true);
    const panelRef = useRef<HTMLDivElement>(null);

    const entry = entries[cardIndex] ?? entries[0];
    const alert = entry.lead;
    const total = entries.length;

    // The dialog belongs to the alert UI: the gate that holds notices back for dialogs, and
    // the focus tracking that remembers where the reader was, both pass over it. Then it grows
    // out of the notice it was opened from.
    useLayoutEffect(() => {
        const panel = panelRef.current;
        const dialog = panel?.parentElement;
        dialog?.setAttribute(WORKFLOW_ALERT_UI_ATTRIBUTE, '');
        dialog?.setAttribute('data-workflow-alert-card', '');
        void growFromRect(panel, useWorkflowAlertStore.getState().growFrom);
    }, []);

    const { links, refusedMessage } = useMemo(() => {
        const origin = window.location.origin;
        const openable: CardLink[] = [];
        let refused: string | null = null;
        for (const link of alert.links) {
            const resolved = resolveNotificationLink(link.notification, origin);
            if (resolved.target) {
                openable.push({ label: link.label, target: resolved.target });
            } else if (resolved.error && !refused) {
                refused = resolved.error;
            }
        }
        return { links: openable, refusedMessage: refused };
    }, [alert]);

    const runPath = workflowAlertOpenRunPath(alert);
    const workflowPath = workflowAlertWorkflowPath(alert);
    const followUp = workflowAlertFollowUpAction(alert, {
        enabled: workflowResultsEnabled,
        open: (workflowId, runId) => openWorkflowResultInChat(workflowId, runId, { navigate, pathname }),
    });

    // Open goes to the conversation the workflow created, else to where it posted, its run, or itself.
    const primaryLink = links.find((link) => link.label === WORKFLOW_ALERT_CREATED_LINK_LABEL) ?? links[0];
    const routeAction: CardAction | null = runPath
        ? { label: 'Open run', target: { kind: 'route', path: runPath }, marker: 'data-workflow-alert-open-run' }
        : workflowPath
            ? { label: 'Open workflow', target: { kind: 'route', path: workflowPath }, marker: 'data-workflow-alert-open-workflow' }
            : null;
    const primary: CardAction | null = primaryLink
        ? { ...primaryLink, marker: 'data-workflow-alert-link' }
        : routeAction;
    const otherActions: CardAction[] = [
        ...links.filter((link) => link !== primaryLink).map((link): CardAction => ({ ...link, marker: 'data-workflow-alert-link' })),
        ...(routeAction && routeAction !== primary ? [routeAction] : []),
    ];

    const open = (target: NotificationTarget) => {
        if (busy) {
            return;
        }
        onOpened();
        void openFromCard(target, { navigate, pathname });
    };

    const runFollowUp = () => {
        if (busy || !followUp) {
            return;
        }
        onOpened();
        closeCard();
        void followUp.run();
    };

    const label = WORKFLOW_ALERT_PRIORITY_LABELS[entry.priority];
    const groupNote = entry.count > 1 ? `Acts on all ${entry.count} alerts from this workflow.` : undefined;
    const more = otherActions.length > 0 || followUp || refusedMessage ? (
        <div className="space-y-2">
            {(otherActions.length > 0 || followUp) && (
                <div className="flex flex-wrap items-center gap-2" data-workflow-alert-links="">
                    {otherActions.map((action, index) => (
                        <GlassButton
                            key={`${action.label}-${index}`}
                            type="button"
                            variant="subtle"
                            size="sm"
                            {...{ [action.marker]: '' }}
                            aria-disabled={busy || undefined}
                            onClick={() => open(action.target)}
                            className={BUSY_CLASS}
                        >
                            {action.label}
                            <ArrowRight size={14} aria-hidden="true" />
                        </GlassButton>
                    ))}
                    {followUp && (
                        <GlassButton
                            type="button"
                            variant="subtle"
                            size="sm"
                            data-workflow-alert-follow-up=""
                            aria-disabled={busy || undefined}
                            onClick={runFollowUp}
                            className={BUSY_CLASS}
                        >
                            {followUp.label}
                        </GlassButton>
                    )}
                </div>
            )}
            {refusedMessage && (
                <p data-workflow-alert-link-note="" className="text-xs text-text-3">{refusedMessage}</p>
            )}
        </div>
    ) : null;

    return (
        <Modal
            title={`${label} priority ${alert.category === 'failure' ? 'workflow run failed' : 'workflow alert'}: ${alert.title}`}
            onClose={closeCard}
            panelRef={panelRef}
            banner={<CardBanner entry={entry} onClose={closeCard} />}
            footer={(
                <div
                    className="flex w-full flex-wrap items-center justify-end gap-2"
                    data-priority={entry.priority}
                    data-category={alert.category}
                >
                    {total > 1 && (
                        <>
                            <span
                                data-workflow-alert-position=""
                                aria-live="polite"
                                aria-atomic="true"
                                className="mr-auto text-xs text-text-3"
                            >
                                {cardIndex + 1} of {total}
                                <span className="sr-only">: {alert.title}</span>
                            </span>
                            <GlassButton
                                type="button"
                                variant="ghost"
                                size="sm"
                                data-workflow-alert-next=""
                                aria-disabled={busy || undefined}
                                onClick={() => {
                                    if (!busy) {
                                        nextEntry();
                                    }
                                }}
                                className={BUSY_CLASS}
                            >
                                Next
                                <ChevronRight size={14} aria-hidden="true" />
                            </GlassButton>
                            <GlassButton
                                type="button"
                                variant="ghost"
                                size="sm"
                                data-workflow-alert-mark-all=""
                                aria-disabled={busy || undefined}
                                onClick={() => void markAllRead()}
                                className={BUSY_CLASS}
                            >
                                Mark all read
                            </GlassButton>
                        </>
                    )}
                    <GlassButton
                        type="button"
                        variant="ghost"
                        size="lg"
                        data-workflow-alert-dismiss=""
                        aria-disabled={busy || undefined}
                        title={groupNote}
                        onClick={() => void dismissEntry()}
                        className={BUSY_CLASS}
                    >
                        Dismiss
                    </GlassButton>
                    {primary ? (
                        <GlassButton
                            type="button"
                            variant="success"
                            size="lg"
                            data-workflow-alert-primary=""
                            {...{ [primary.marker]: '' }}
                            aria-label={primary.label}
                            aria-disabled={busy || undefined}
                            title={groupNote ?? primary.label}
                            onClick={() => open(primary.target)}
                            className={clsx('min-w-36 justify-center', BUSY_CLASS)}
                        >
                            Open
                            <ArrowRight size={18} aria-hidden="true" />
                        </GlassButton>
                    ) : (
                        // Nothing to open, so reading it is the way to settle it.
                        <GlassButton
                            type="button"
                            variant="primary"
                            size="lg"
                            data-workflow-alert-primary=""
                            data-workflow-alert-mark-read=""
                            aria-disabled={busy || undefined}
                            title={groupNote}
                            onClick={() => void markEntryRead()}
                            className={clsx('min-w-36 justify-center', BUSY_CLASS)}
                        >
                            Mark read
                        </GlassButton>
                    )}
                </div>
            )}
        >
            {/* Keyed on the entry, so Show more starts closed for each one. */}
            <CardBody key={entry.key} alert={alert} more={more} />
        </Modal>
    );
}

/**
 * The card, while one is open. When it closes without sending the reader somewhere, focus
 * goes back where they were before the alert, or to the bell, where the alert still is.
 */
export function WorkflowAlertCardHost() {
    const open = useWorkflowAlertStore((state) => state.phase === 'card' && state.entries.length > 0);
    const wasOpen = useRef(false);
    const leftForTarget = useRef(false);

    useEffect(() => {
        if (open) {
            leftForTarget.current = false;
        } else if (wasOpen.current && !leftForTarget.current) {
            const active = document.activeElement;
            if (!active || active === document.body) {
                workflowAlertReturnFocusTarget()?.focus({ preventScroll: true });
            }
        }
        wasOpen.current = open;
    }, [open]);

    if (!open) {
        return null;
    }
    return <WorkflowAlertCard onOpened={() => { leftForTarget.current = true; }} />;
}
