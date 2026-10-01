// WorkflowAlertCard.tsx
// The full workflow alert, grown out of the notice when the reader opens it.
//
// It sits in the shared Modal shell, so Escape, the backdrop and focus behave as in every other
// V2 dialog: focus moves in when it opens, stays inside while it is open, and goes back where
// the reader was when it closes. The control that opened it -- the notice -- is gone by then,
// so the host below hands focus back itself.
//
// The card shows one entry at a time: an alert, or every alert one workflow raised together.
// "1 of 3" and Next step through what is waiting. Mark read and Dismiss act on the entry
// shown, and Mark all read on every entry, one alert at a time -- never the bell's own Mark
// all read, which would also clear notices the card never showed.
//
// Every word here is the alert's own text, rendered as text. Its links are checked by the
// bell's resolver and followed by the bell's navigation, so only this site's pages open.

import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
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

function CardBody({ alert }: { alert: WorkflowAlert }) {
    const [expanded, setExpanded] = useState(false);
    const detailId = useId();
    const whyId = useId();
    const chips = chipsFor(alert);
    const serverReason = workflowAlertServerReason(alert);

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
                {alert.detail && (
                    <>
                        <button
                            type="button"
                            data-workflow-alert-show-more=""
                            aria-expanded={expanded}
                            aria-controls={detailId}
                            onClick={() => setExpanded((open) => !open)}
                            className="mt-1.5 inline-flex items-center gap-1 rounded-md text-xs font-medium text-text-2 hover:text-text-1"
                        >
                            <ChevronDown
                                size={14}
                                aria-hidden="true"
                                className={clsx('transition-transform', expanded && 'rotate-180')}
                            />
                            {expanded ? 'Show less' : 'Show more'}
                        </button>
                        <div
                            id={detailId}
                            hidden={!expanded}
                            data-workflow-alert-detail=""
                            className="mt-1.5 rounded-lg bg-surface-sunken px-3 py-2 text-sm whitespace-pre-wrap break-words text-text-1"
                        >
                            {alert.detail}
                        </div>
                    </>
                )}
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

    const hasOpenRow = links.length > 0 || Boolean(runPath || workflowPath || followUp);
    const label = WORKFLOW_ALERT_PRIORITY_LABELS[entry.priority];
    const groupNote = entry.count > 1 ? `Acts on all ${entry.count} alerts from this workflow.` : undefined;

    return (
        <Modal
            title={`${label} priority ${alert.category === 'failure' ? 'workflow run failed' : 'workflow alert'}: ${alert.title}`}
            onClose={closeCard}
            panelRef={panelRef}
            banner={<CardBanner entry={entry} onClose={closeCard} />}
            footer={(
                <div className="flex w-full flex-col gap-2" data-priority={entry.priority} data-category={alert.category}>
                    {hasOpenRow && (
                        <div className="flex flex-wrap items-center gap-2" data-workflow-alert-links="">
                            {links.map((link, index) => (
                                <GlassButton
                                    key={`${link.label}-${index}`}
                                    type="button"
                                    variant="subtle"
                                    size="sm"
                                    data-workflow-alert-link=""
                                    aria-disabled={busy || undefined}
                                    onClick={() => open(link.target)}
                                    className={BUSY_CLASS}
                                >
                                    {link.label}
                                    <ArrowRight size={14} aria-hidden="true" />
                                </GlassButton>
                            ))}
                            {runPath ? (
                                <GlassButton
                                    type="button"
                                    variant="subtle"
                                    size="sm"
                                    data-workflow-alert-open-run=""
                                    aria-disabled={busy || undefined}
                                    onClick={() => open({ kind: 'route', path: runPath })}
                                    className={BUSY_CLASS}
                                >
                                    Open run
                                    <ArrowRight size={14} aria-hidden="true" />
                                </GlassButton>
                            ) : workflowPath ? (
                                <GlassButton
                                    type="button"
                                    variant="subtle"
                                    size="sm"
                                    data-workflow-alert-open-workflow=""
                                    aria-disabled={busy || undefined}
                                    onClick={() => open({ kind: 'route', path: workflowPath })}
                                    className={BUSY_CLASS}
                                >
                                    Open workflow
                                    <ArrowRight size={14} aria-hidden="true" />
                                </GlassButton>
                            ) : null}
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
                    <div className="flex flex-wrap items-center justify-end gap-2">
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
                            size="sm"
                            data-workflow-alert-dismiss=""
                            aria-disabled={busy || undefined}
                            title={groupNote}
                            onClick={() => void dismissEntry()}
                            className={BUSY_CLASS}
                        >
                            Dismiss
                        </GlassButton>
                        <GlassButton
                            type="button"
                            variant="primary"
                            size="sm"
                            data-workflow-alert-mark-read=""
                            aria-disabled={busy || undefined}
                            title={groupNote}
                            onClick={() => void markEntryRead()}
                            className={BUSY_CLASS}
                        >
                            Mark read
                        </GlassButton>
                    </div>
                </div>
            )}
        >
            {/* Keyed on the entry, so Show more starts closed for each one. */}
            <CardBody key={entry.key} alert={alert} />
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
