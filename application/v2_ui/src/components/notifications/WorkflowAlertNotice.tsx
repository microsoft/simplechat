// WorkflowAlertNotice.tsx
// The small notice a workflow alert first appears as, before it is opened into the card.
//
// It is a callout from the bell in the rail, the place every notice can be found again, with a
// notch pointing at the bell. In the full rail it drops down from the bell the way the bell's
// own panel does, hanging past the rail's edge over the page. It overlays what is under it
// rather than pushing it, so the conversation list never jumps, and most of New chat stays
// clickable beside it. With the rail collapsed to its icon strip, including mobile's, it flies
// out to the right of the bell instead.
//
// It used to hang from My Workspace, where workflows live. It moved to the bell (0.261.236)
// because the chat page's rail scrolls its navigation out of view as the conversation list is
// read, which could carry the item, and the notice with it, off screen; the bell never
// scrolls. (A top-centre pill was also built and compared in the alert lab; the callout was
// chosen because the pill covered the page's own header and actions on a phone.)
//
// It shows one entry at a time, the loudest waiting, and says how many more are behind it. It
// never takes focus, so typing is not interrupted, but it sits in the tab order beside what it
// is anchored to. Info, low and medium alerts tuck into the bell after eight seconds unless
// the pointer is over the notice or focus is inside it; high and critical stay until they are
// opened or closed. Closing tucks it into the bell straight away. Either way the alert stays
// unread there.
//
// An alert that needs acknowledgment never tucks away, so it must never cover anything for
// long: in the full rail it takes a row of its own under the rail's header, still pointing at
// the bell, and pushes New chat and the navigation down; as a flyout it steps aside --
// invisible, out of the pointer's way -- when focus moves onto something it would cover, and
// comes back when focus moves on. A new alert taking the lead is shown, whatever focus did
// before it arrived.
//
// Everything shown is the alert's own text, rendered as text.

import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';
import { clsx } from 'clsx';
import { BellRing, X } from 'lucide-react';
import {
    WORKFLOW_ALERT_PRIORITY_LABELS,
    describeWorkflowAlertGroup,
    workflowAlertStays,
    type WorkflowAlertEntry,
} from '../../lib/workflowAlertNotices';
import { useReducedMotion } from '../../lib/workflowAlertMotion';
import { retryWorkflowAlertSound, useWorkflowAlertSoundBlocked } from '../../lib/workflowAlertSound';
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

export type WorkflowAlertNoticePlacement = 'below' | 'flyout';

const ENTRANCE: Record<WorkflowAlertNoticePlacement, string> = {
    below: 'wf-alert-enter-drop',
    flyout: 'wf-alert-enter-flyout',
};

/** Whether the notice is on screen, or on its way into the bell. */
function useNoticeShown(): boolean {
    return useWorkflowAlertStore(
        (state) => state.entries.length > 0 && (state.phase === 'notice' || state.phase === 'tucking'),
    );
}

/** Whether an alert waiting to be shown needs acknowledgment, and so never tucks away. */
function useMustAcknowledge(): boolean {
    return useWorkflowAlertStore((state) => state.entries.some((entry) => entry.requireAcknowledgment));
}

/** Whether `notice` lies over `target`, so that focus on `target` would be hidden under it. */
function liesOver(notice: Element, target: Element): boolean {
    const box = notice.getBoundingClientRect();
    const landed = target.getBoundingClientRect();
    return landed.width > 0 && landed.height > 0
        && landed.left < box.right && box.left < landed.right
        && landed.top < box.bottom && box.top < landed.bottom;
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
    // Whether focus last landed on something the notice lies over, measured for one lead in one
    // placement. A new lead, or the rail changing shape, starts it shown until focus next moves.
    const [focusCover, setFocusCover] = useState<{ key: string; covered: boolean } | null>(null);
    const soundBlocked = useWorkflowAlertSoundBlocked();

    // Hidden while something else has the page, the pointer and focus cannot be said to have
    // left it; they start fresh when it is back.
    useEffect(() => {
        if (suspended) {
            setHovered(false);
            setFocused(false);
            setFocusCover(null);
        }
    }, [suspended]);

    useTuckTimer(
        phase === 'notice' && !entry.requireAcknowledgment && !workflowAlertStays(entry.priority),
        hovered || focused || suspended,
        `${entry.key}:${entry.priority}:${batchToken}`,
        () => void tuck(),
    );

    // The notice overlays the rail items under the bell, or the page beside the rail, so
    // tabbing on from it can land on something it covers. Focus must never sit hidden under it
    // (WCAG 2.2, 2.4.11), so it tucks into the bell and leaves focus where it went. The alert
    // stays unread there, like any other tuck. One that needs acknowledgment can't tuck away,
    // so as a flyout it steps aside instead, until focus is somewhere it doesn't cover. Every
    // move is measured, whatever leads, so the record never outlives the focus it describes.
    const mustAcknowledge = entry.requireAcknowledgment;
    const coverKey = `${entry.key}:${placement}`;
    useEffect(() => {
        if (phase !== 'notice' || suspended) {
            return undefined;
        }
        const onFocusIn = (event: FocusEvent) => {
            const root = rootRef.current;
            const target = event.target;
            if (!root || !(target instanceof Element)) {
                return;
            }
            const covered = !root.contains(target) && liesOver(root, target);
            setFocusCover({ key: coverKey, covered });
            if (covered && !mustAcknowledge) {
                void tuck();
            }
        };
        // Focus that goes nowhere -- a click on the page's background -- covers nothing.
        const onFocusOut = (event: FocusEvent) => {
            if (event.relatedTarget === null) {
                setFocusCover({ key: coverKey, covered: false });
            }
        };
        document.addEventListener('focusin', onFocusIn);
        document.addEventListener('focusout', onFocusOut);
        return () => {
            document.removeEventListener('focusin', onFocusIn);
            document.removeEventListener('focusout', onFocusOut);
        };
    }, [phase, suspended, tuck, mustAcknowledge, coverKey]);
    // In the full rail it has room of its own and covers nothing, so only the flyout steps aside.
    const asideNow = mustAcknowledge && placement === 'flyout'
        && focusCover?.key === coverKey && focusCover.covered;

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
            if (!entry.requireAcknowledgment) {
                void close();
            }
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
        entry.requireAcknowledgment ? 'Needs acknowledgment.' : '',
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
            data-requires-acknowledgment={entry.requireAcknowledgment ? 'true' : 'false'}
            data-stepped-aside={asideNow ? 'true' : 'false'}
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
                'glass-modal relative w-full rounded-xl text-left',
                tone.outline,
                reduced ? 'wf-alert-enter-fade' : ENTRANCE[placement],
                phase === 'tucking' && 'pointer-events-none',
                asideNow && 'invisible',
                suspended && 'hidden',
            )}
        >
            <span aria-hidden="true" className="wf-alert-notch" />
            <div className="flex items-start gap-2 py-2.5 pr-1.5 pl-3">
                <button
                    type="button"
                    data-workflow-alert-open=""
                    onClick={openCard}
                    aria-label={openLabel}
                    className="min-w-0 flex-1 rounded-lg text-left"
                >
                    {/* The bell sits in the header rather than beside it, so the text has the
                        notice's width. The header wraps, putting the workflow's name on a line of
                        its own when the tags leave too little room; it is only cut short when it
                        is longer than that whole line, and its title and the button's name carry
                        it in full. */}
                    <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1">
                        <span aria-hidden="true" className={clsx('inline-flex shrink-0 rounded-full p-1', tone.chip)}>
                            {/* Keyed on the batch, so the bell rings again when more alerts join. */}
                            <span key={batchToken} className={clsx('inline-flex', !reduced && 'wf-bell-swing')}>
                                <BellRing size={14} />
                            </span>
                        </span>
                        <span
                            data-workflow-alert-priority-tag=""
                            className={clsx('shrink-0 rounded px-1.5 py-0.5 text-[11px] leading-none font-semibold', tone.tag)}
                        >
                            {label}
                        </span>
                        {alert.category === 'failure' && (
                            <span className="shrink-0 text-[11px] font-semibold text-text-2">Run failed</span>
                        )}
                        {entry.requireAcknowledgment && (
                            <span
                                data-workflow-alert-ack-tag=""
                                className="shrink-0 rounded bg-danger-soft px-1.5 py-0.5 text-[11px] font-semibold text-danger"
                            >
                                Needs acknowledgment
                            </span>
                        )}
                        <span
                            data-workflow-alert-workflow=""
                            title={alert.workflowName}
                            className="max-w-full min-w-0 truncate text-xs text-text-2"
                        >
                            {alert.workflowName}
                        </span>
                    </span>
                    <span className="mt-1 line-clamp-2 block text-sm font-medium break-words text-text-1">
                        {alert.title}
                    </span>
                    {(group || more > 0 || entry.audience === 'group') && (
                        <span className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-text-3">
                            {group && <span data-workflow-alert-group="">{group}</span>}
                            {entry.audience === 'group' && <span data-workflow-alert-team="">Sent to everyone in the group</span>}
                            {more > 0 && (
                                <span data-workflow-alert-more="" className="font-semibold text-text-2">
                                    +{more} more
                                </span>
                            )}
                        </span>
                    )}
                </button>
                {/* A control of its own beside the notice, never nested in the notice's button. */}
                {soundBlocked && (
                    <button
                        type="button"
                        data-workflow-alert-enable-sound=""
                        onClick={retryWorkflowAlertSound}
                        className="shrink-0 rounded-lg px-1.5 py-1 text-xs font-semibold text-accent underline transition-colors hover:bg-surface-2"
                    >
                        Enable sound
                    </button>
                )}
                {!entry.requireAcknowledgment && (
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
                )}
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
 * The notice's anchor, inside the bell's wrapper.
 *
 * In the full rail it drops from the bell as the bell's panel does, eight pixels below it, and
 * is shifted left so its notch (18px in, 12px wide, so centred 24px in) sits under the bell's
 * centre. In the collapsed strip, including a phone's, it flies out from the strip's edge with
 * its notch (16px down, centred 22px down) level with the bell, capped so a phone's narrow
 * screen still fits it.
 *
 * An alert that needs acknowledgment stays until it is acknowledged, so in the full rail it must
 * not sit over anything. There WorkflowAlertRowSlot gives it a row of its own, and this slot
 * stands aside.
 */
export function WorkflowAlertCalloutSlot({ collapsed }: { collapsed: boolean }) {
    const shown = useNoticeShown();
    const mustAcknowledge = useMustAcknowledge();
    if (!shown || (!collapsed && mustAcknowledge)) {
        return null;
    }
    return (
        <div
            data-workflow-alert-slot="callout"
            data-in-flow="false"
            className={clsx(
                'absolute z-50 w-72',
                collapsed
                    ? 'top-[calc(50%_-_22px)] left-full ml-3 max-w-[calc(100vw_-_68px_-_1rem)]'
                    : 'top-full left-[calc(50%_-_24px)] mt-2',
            )}
        >
            <WorkflowAlertNotice placement={collapsed ? 'flyout' : 'below'} />
        </div>
    );
}

/**
 * The full rail's room for an alert that needs acknowledgment: a row of its own under the rail's
 * header, the row the bell sits in. It hangs from the bell like any other notice but pushes New
 * chat and the navigation down instead of covering them, and, being outside the chat page's
 * scroll region, it can't be scrolled away either.
 *
 * The row spans the rail rather than sitting under the bell, so the slot measures where the
 * bell is and hands the notch that position (`--wf-alert-notch-centre`, from the slot's left).
 */
export function WorkflowAlertRowSlot({ collapsed }: { collapsed: boolean }) {
    const shown = useNoticeShown();
    const mustAcknowledge = useMustAcknowledge();
    const suspended = useWorkflowAlertStore((state) => state.suspended);
    const slotRef = useRef<HTMLDivElement>(null);
    const [notchCentre, setNotchCentre] = useState<number | null>(null);
    const active = shown && !collapsed && mustAcknowledge;

    // Measured before paint, so the notch never shows pointing anywhere but the bell.
    useLayoutEffect(() => {
        const slot = slotRef.current;
        const bell = slot?.closest('nav')?.querySelector('[data-notification-bell]');
        if (!active || !slot || !bell) {
            return undefined;
        }
        const measure = () => {
            const slotBox = slot.getBoundingClientRect();
            const bellBox = bell.getBoundingClientRect();
            setNotchCentre(bellBox.left + bellBox.width / 2 - slotBox.left);
        };
        measure();
        if (typeof ResizeObserver === 'undefined') {
            return undefined;
        }
        const observer = new ResizeObserver(measure);
        observer.observe(slot);
        return () => observer.disconnect();
    }, [active]);

    if (!active) {
        return null;
    }
    const notchStyle = notchCentre === null
        ? undefined
        : ({ '--wf-alert-notch-centre': `${notchCentre}px` } as CSSProperties);
    return (
        <div
            ref={slotRef}
            data-workflow-alert-slot="callout"
            data-in-flow="true"
            style={notchStyle}
            // While something else has the page the notice is hidden, and its gap goes with it.
            className={clsx('relative mx-3', !suspended && 'mb-3')}
        >
            <WorkflowAlertNotice placement="below" />
        </div>
    );
}

/** Whether the callout is on screen, for the rail to lift itself above the page. */
export function useWorkflowAlertCalloutShown(): boolean {
    return useNoticeShown();
}
