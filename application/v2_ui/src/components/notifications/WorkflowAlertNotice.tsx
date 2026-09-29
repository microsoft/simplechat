// WorkflowAlertNotice.tsx
// The small notice a workflow alert first appears as, before it is opened into the card.
//
// Two entrance styles are built, to be compared in the alert lab (dev/AlertLabPage.tsx):
//
// - A, the callout: it drops from under My Workspace in the rail, where workflows live, with
//   a notch pointing at the item. It overlays the items below rather than pushing them, so
//   the conversation list never jumps. With the rail collapsed to its icon strip, including
//   mobile's, it flies out to the right of the My Workspace icon instead.
// - B, the pill: it slides down from the top of the content column.
//
// Either way it shows one entry at a time, the loudest waiting, and says how many more are
// behind it. It never takes focus, so typing is not interrupted, but it sits in the tab order
// beside what it is anchored to. Info, low and medium alerts tuck into the bell after eight
// seconds unless the pointer is over the notice or focus is inside it; high and critical stay
// until they are opened or closed. Closing tucks it into the bell straight away. Either way
// the alert stays unread there.
//
// Everything shown is the alert's own text, rendered as text.

import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { clsx } from 'clsx';
import { BellRing, X } from 'lucide-react';
import {
    WORKFLOW_ALERT_PRIORITY_LABELS,
    describeWorkflowAlertGroup,
    workflowAlertStays,
    type WorkflowAlertEntry,
} from '../../lib/workflowAlertNotices';
import { useReducedMotion } from '../../lib/workflowAlertMotion';
import {
    useWorkflowAlertStore,
    workflowAlertReturnFocusTarget,
    type WorkflowAlertPhase,
} from '../../stores/workflowAlertStore';
import { workflowAlertTone } from './workflowAlertTone';
import './WorkflowAlertNotice.css';

/** How long an info, low or medium alert stays before it tucks into the bell. */
export const WORKFLOW_ALERT_NOTICE_MS = 8_000;

/**
 * A paused timer resumes with at least this long, so a notice the pointer rested on until
 * its last moment does not vanish the instant the pointer leaves.
 */
const RESUME_MIN_MS = 2_500;

export type WorkflowAlertNoticePlacement = 'below' | 'flyout' | 'pill';

const ENTRANCE: Record<WorkflowAlertNoticePlacement, string> = {
    below: 'wf-alert-enter-drop',
    flyout: 'wf-alert-enter-flyout',
    pill: 'wf-alert-enter-slide',
};

/** Whether the notice is on screen, or on its way into the bell. */
function useNoticeShown(): boolean {
    return useWorkflowAlertStore(
        (state) => state.entries.length > 0 && (state.phase === 'notice' || state.phase === 'tucking'),
    );
}

/**
 * Tuck the notice away once its time is up. `resetKey` starts the time again: a different
 * alert at the front, or new alerts joining.
 */
function useTuckTimer(active: boolean, paused: boolean, resetKey: string, onElapsed: () => void): void {
    const remaining = useRef(WORKFLOW_ALERT_NOTICE_MS);
    const elapsed = useRef(onElapsed);

    useEffect(() => {
        elapsed.current = onElapsed;
    }, [onElapsed]);

    useEffect(() => {
        remaining.current = WORKFLOW_ALERT_NOTICE_MS;
    }, [resetKey]);

    useEffect(() => {
        if (!active || paused) {
            return undefined;
        }
        const started = Date.now();
        const timer = setTimeout(() => elapsed.current(), remaining.current);
        return () => {
            clearTimeout(timer);
            remaining.current = Math.max(RESUME_MIN_MS, remaining.current - (Date.now() - started));
        };
    }, [active, paused, resetKey]);
}

function NoticeBody({
    placement,
    entry,
    more,
    phase,
    suspended,
    batchToken,
}: {
    placement: WorkflowAlertNoticePlacement;
    entry: WorkflowAlertEntry;
    more: number;
    phase: WorkflowAlertPhase;
    suspended: boolean;
    batchToken: number;
}) {
    const openCard = useWorkflowAlertStore((state) => state.openCard);
    const tuck = useWorkflowAlertStore((state) => state.tuck);
    const reduced = useReducedMotion();
    const rootRef = useRef<HTMLDivElement>(null);
    const [hovered, setHovered] = useState(false);
    const [focused, setFocused] = useState(false);

    // Hidden while something else has the page, the pointer and focus cannot be said to have
    // left it; they start fresh when it is back.
    useEffect(() => {
        if (suspended) {
            setHovered(false);
            setFocused(false);
        }
    }, [suspended]);

    useTuckTimer(
        phase === 'notice' && !workflowAlertStays(entry.priority),
        hovered || focused || suspended,
        `${entry.key}:${entry.priority}:${batchToken}`,
        () => void tuck(),
    );

    const close = async () => {
        const hadFocus = rootRef.current?.contains(document.activeElement) ?? false;
        await tuck();
        // The notice is gone with focus inside it; put focus back where the reader came from.
        if (hadFocus && (!document.activeElement || document.activeElement === document.body)) {
            workflowAlertReturnFocusTarget()?.focus({ preventScroll: true });
        }
    };

    const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
        if (event.key === 'Escape') {
            event.stopPropagation();
            void close();
        }
    };

    const alert = entry.lead;
    const label = WORKFLOW_ALERT_PRIORITY_LABELS[entry.priority];
    const tone = workflowAlertTone(entry.priority);
    const group = describeWorkflowAlertGroup(entry);
    const kind = alert.category === 'failure' ? 'workflow run failed' : 'workflow alert';
    const openLabel = [
        `Open ${label.toLowerCase()} priority ${kind}: ${alert.title}, from ${alert.workflowName}.`,
        group ? `${group}.` : '',
        more > 0 ? `${more} more waiting.` : '',
    ].filter(Boolean).join(' ');

    return (
        <div
            ref={rootRef}
            role="group"
            aria-label="Workflow alert"
            data-workflow-alert-ui=""
            data-workflow-alert-notice=""
            data-placement={placement}
            data-priority={entry.priority}
            data-category={alert.category}
            data-state={phase}
            data-count={entry.count}
            onPointerEnter={() => setHovered(true)}
            onPointerLeave={() => setHovered(false)}
            onFocus={() => setFocused(true)}
            onBlur={(event) => {
                if (!(event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget))) {
                    setFocused(false);
                }
            }}
            onKeyDown={onKeyDown}
            className={clsx(
                'glass-modal relative rounded-xl text-left',
                tone.outline,
                placement === 'pill' ? 'pointer-events-auto w-full max-w-md' : 'w-full',
                reduced ? 'wf-alert-enter-fade' : ENTRANCE[placement],
                phase === 'tucking' && 'pointer-events-none',
                suspended && 'hidden',
            )}
        >
            {placement !== 'pill' && <span aria-hidden="true" className="wf-alert-notch" />}
            <div className="flex items-start gap-2.5 py-2.5 pr-1.5 pl-2.5">
                <span aria-hidden="true" className={clsx('inline-flex shrink-0 rounded-full p-1.5', tone.chip)}>
                    {/* Keyed on the batch, so the bell rings again when more alerts join. */}
                    <span key={batchToken} className={clsx('inline-flex', !reduced && 'wf-bell-swing')}>
                        <BellRing size={16} />
                    </span>
                </span>
                <button
                    type="button"
                    data-workflow-alert-open=""
                    onClick={openCard}
                    aria-label={openLabel}
                    className="min-w-0 flex-1 rounded-lg text-left"
                >
                    <span className="flex min-w-0 items-center gap-1.5">
                        <span
                            data-workflow-alert-priority-tag=""
                            className={clsx('shrink-0 rounded px-1.5 py-0.5 text-[11px] leading-none font-semibold', tone.tag)}
                        >
                            {label}
                        </span>
                        {alert.category === 'failure' && (
                            <span className="shrink-0 text-[11px] font-semibold text-text-2">Run failed</span>
                        )}
                        <span className="min-w-0 truncate text-xs text-text-2">{alert.workflowName}</span>
                    </span>
                    <span className="mt-1 line-clamp-2 block text-sm font-medium break-words text-text-1">
                        {alert.title}
                    </span>
                    {(group || more > 0) && (
                        <span className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-text-3">
                            {group && <span data-workflow-alert-group="">{group}</span>}
                            {more > 0 && (
                                <span data-workflow-alert-more="" className="font-semibold text-text-2">
                                    +{more} more
                                </span>
                            )}
                        </span>
                    )}
                </button>
                <button
                    type="button"
                    data-workflow-alert-close=""
                    onClick={() => void close()}
                    aria-label="Close alert notice"
                    title="Close"
                    className="shrink-0 rounded-lg p-1 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                >
                    <X size={15} aria-hidden="true" />
                </button>
            </div>
        </div>
    );
}

export function WorkflowAlertNotice({ placement }: { placement: WorkflowAlertNoticePlacement }) {
    const entry = useWorkflowAlertStore((state) => state.entries[0]);
    const more = useWorkflowAlertStore((state) => Math.max(0, state.entries.length - 1));
    const phase = useWorkflowAlertStore((state) => state.phase);
    const suspended = useWorkflowAlertStore((state) => state.suspended);
    const batchToken = useWorkflowAlertStore((state) => state.batchToken);
    const shown = useNoticeShown();

    if (!shown || !entry) {
        return null;
    }
    return (
        <NoticeBody
            placement={placement}
            entry={entry}
            more={more}
            phase={phase}
            suspended={suspended}
            batchToken={batchToken}
        />
    );
}

/**
 * Style A's anchor, inside the My Workspace item. Below the item in the full rail; beside its
 * icon when the rail is a strip, capped so a phone's narrow screen still fits it.
 */
export function WorkflowAlertCalloutSlot({ collapsed }: { collapsed: boolean }) {
    const style = useWorkflowAlertStore((state) => state.style);
    const shown = useNoticeShown();
    if (style !== 'callout' || !shown) {
        return null;
    }
    return (
        <div
            data-workflow-alert-slot="callout"
            className={clsx(
                'absolute z-50',
                collapsed
                    ? 'top-0 left-full ml-3 w-72 max-w-[calc(100vw_-_68px_-_1rem)]'
                    : 'top-full right-0 left-0 mt-2',
            )}
        >
            <WorkflowAlertNotice placement={collapsed ? 'flyout' : 'below'} />
        </div>
    );
}

/** Whether style A's callout is on screen, for the rail to lift itself above the page. */
export function useWorkflowAlertCalloutShown(): boolean {
    const style = useWorkflowAlertStore((state) => state.style);
    const shown = useNoticeShown();
    return style === 'callout' && shown;
}

/**
 * Style B's anchor, at the top of the content column. It takes no room: the pill overlays
 * the page, and only the pill itself takes the pointer.
 */
export function WorkflowAlertPillSlot() {
    const style = useWorkflowAlertStore((state) => state.style);
    const shown = useNoticeShown();
    if (style !== 'pill' || !shown) {
        return null;
    }
    return (
        <div data-workflow-alert-slot="pill" className="pointer-events-none relative z-40 h-0 shrink-0">
            <div className="absolute inset-x-0 top-3 flex justify-center px-3">
                <WorkflowAlertNotice placement="pill" />
            </div>
        </div>
    );
}
