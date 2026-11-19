// idleSession.ts
// The browser half of the idle-session timeout: when to warn, when the server will have signed
// the user out, and when to tell it the user is still here.
//
// The server enforces the timeout (`enforce_idle_session_timeout` in app.py). A session is
// ended when nothing has refreshed it for `timeout_minutes`, and only a page load or a call to
// the heartbeat route refreshes it: API calls do not count. V2 is one page load followed by
// nothing but API calls, so without a heartbeat an active user would be signed out
// `timeout_minutes` after opening the app, with no warning. This module decides when that
// heartbeat is sent and when the warning opens, using the thresholds the classic page
// (static/js/idle-logout-warning.js) uses:
//
// - the warning opens `warning_minutes` after the last activity, and the user is signed out
//   `timeout_minutes` after it; a warning time equal to the timeout means no warning;
// - activity is counted at most once a second;
// - the heartbeat goes out at most every minute (or every half timeout, if that is shorter).
//
// Two things differ from classic on purpose. While the warning is open, passing input does not
// dismiss it: someone using the keyboard to reach "Logout now" would otherwise cancel the
// warning with the Tab key, so only "Stay signed in" continues the session. And tabs share
// their last activity through localStorage, so an idle background tab cannot sign out the
// shared session while another tab is in use. Every decision is made from wall-clock time
// rather than from a timer's own count, so a sleeping laptop or a throttled background tab
// cannot leave the page believing less time has passed than the server does.
//
// Nothing here touches the DOM, React or the network: the page supplies a host (clock,
// timers, heartbeat, sign-out, shared storage), which is what lets the thresholds be run
// against a fake clock.

import type { IdleTimeoutBootstrap } from './types';

/** The heartbeat route in app.py (`session_heartbeat`). */
export const IDLE_HEARTBEAT_ENDPOINT = '/api/session/heartbeat';

/** The local sign-out the server redirects an expired page to, and classic's warning uses. */
export const IDLE_SIGN_OUT_PATH = '/logout/local';

/** localStorage key tabs use to share the time of the last activity. */
export const SHARED_ACTIVITY_KEY = 'simplechat.v2.idleActivity';

/** Input is counted once per this long, as in classic. */
export const ACTIVITY_THROTTLE_MS = 1000;

/** What the warning says when the administrator has not set a sentence of their own. */
export const DEFAULT_WARNING_MESSAGE = "You've been inactive for a while.";

/** The administrator's sentence is capped where the admin setting caps it. */
export const WARNING_MESSAGE_MAX_LENGTH = 200;

/** Shown when "Stay signed in" could not reach the server. The countdown keeps running. */
export const STAY_SIGNED_IN_FAILED_MESSAGE =
    "We couldn't confirm your session. Check your connection and try again before the countdown ends.";

const HEARTBEAT_MAX_INTERVAL_MS = 60_000;

/** How far ahead of now a shared activity time may be and still count as activity just now. */
const SHARED_ACTIVITY_FUTURE_TOLERANCE_MS = 5000;

/** The longest delay a browser timer accepts; anything longer fires at once. */
const MAX_TIMER_MS = 2_147_483_647;

/** Seconds remaining at which the countdown is announced to assistive technology. */
const ANNOUNCE_AT_SECONDS = [60, 30, 10] as const;

export interface IdlePolicy {
    /** Inactivity after which the server ends the session. */
    timeoutMs: number;
    /** Inactivity after which the warning opens. */
    warningMs: number;
    /** False when the warning time equals the timeout: the user is signed out with no dialog. */
    warningEnabled: boolean;
    /** Shortest gap between two heartbeats sent because the user was active. */
    heartbeatIntervalMs: number;
    warningMessage: string;
}

/**
 * The policy bootstrap describes, or null when there is nothing to run.
 *
 * Null for a disabled timeout and for values the classic page also refuses to act on: the
 * server enforces the timeout either way, and a page that cannot read the numbers is better
 * silent than wrong.
 */
export function resolveIdlePolicy(raw: Partial<IdleTimeoutBootstrap> | null | undefined): IdlePolicy | null {
    if (!raw || raw.enabled !== true) {
        return null;
    }
    const timeoutMinutes = raw.timeout_minutes;
    const warningMinutes = raw.warning_minutes;
    if (typeof timeoutMinutes !== 'number' || !Number.isFinite(timeoutMinutes) || timeoutMinutes <= 0) {
        return null;
    }
    if (
        typeof warningMinutes !== 'number' || !Number.isFinite(warningMinutes)
        || warningMinutes < 0 || warningMinutes > timeoutMinutes
    ) {
        return null;
    }
    const timeoutMs = timeoutMinutes * 60_000;
    const message = typeof raw.warning_message === 'string'
        ? raw.warning_message.trim().slice(0, WARNING_MESSAGE_MAX_LENGTH).trim()
        : '';
    return {
        timeoutMs,
        warningMs: warningMinutes * 60_000,
        warningEnabled: warningMinutes < timeoutMinutes,
        heartbeatIntervalMs: Math.min(HEARTBEAT_MAX_INTERVAL_MS, timeoutMs / 2),
        warningMessage: message || DEFAULT_WARNING_MESSAGE,
    };
}

export type IdlePhase = 'active' | 'warning' | 'expired';

/** Where a session that has been idle for `idleMs` stands. */
export function idlePhase(policy: IdlePolicy, idleMs: number): IdlePhase {
    if (idleMs >= policy.timeoutMs) {
        return 'expired';
    }
    if (policy.warningEnabled && idleMs >= policy.warningMs) {
        return 'warning';
    }
    return 'active';
}

/** Whole seconds left before sign-out, rounded up as classic's countdown is. */
export function secondsUntilSignOut(policy: IdlePolicy, idleMs: number): number {
    return Math.max(0, Math.ceil((policy.timeoutMs - idleMs) / 1000));
}

/** "2 minutes", "1 minute 5 seconds" or "45 seconds": the countdown in words. */
export function formatRemaining(totalSeconds: number): string {
    const seconds = Math.max(0, Math.floor(totalSeconds));
    const minutes = Math.floor(seconds / 60);
    const rest = seconds % 60;
    const unit = (count: number, word: string) => `${count} ${word}${count === 1 ? '' : 's'}`;
    if (minutes === 0) {
        return unit(rest, 'second');
    }
    return rest === 0 ? unit(minutes, 'minute') : `${unit(minutes, 'minute')} ${unit(rest, 'second')}`;
}

/**
 * What to announce when the countdown moves from `previousSeconds` to `seconds`, or null.
 *
 * A live region that spoke every second would make the dialog unusable with a screen reader,
 * so the countdown is announced as it crosses a minute, half a minute and ten seconds. The
 * dialog's own description already carries the figure at the moment it opens.
 */
export function countdownAnnouncement(previousSeconds: number | null, seconds: number): string | null {
    if (previousSeconds === null || seconds >= previousSeconds) {
        return null;
    }
    const crossed = ANNOUNCE_AT_SECONDS.find((mark) => previousSeconds > mark && seconds <= mark);
    return crossed === undefined ? null : `You will be signed out in ${formatRemaining(seconds)}.`;
}

/**
 * The shared last-activity time another tab wrote, or null when it is absent or unreadable.
 *
 * A time slightly ahead of now is treated as now. One further ahead is ignored: tabs share a
 * clock, so such a value can only come from the clock being set back or from a stray write,
 * and honouring it would hold the session open until that future time arrived.
 */
export function parseSharedActivity(raw: string | null | undefined, now: number): number | null {
    if (!raw) {
        return null;
    }
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0 || value - now > SHARED_ACTIVITY_FUTURE_TOLERANCE_MS) {
        return null;
    }
    return Math.min(value, now);
}

export interface IdleSessionView {
    /** The warning is on screen. */
    open: boolean;
    secondsRemaining: number;
    /** "Stay signed in" is waiting on the server. */
    staying: boolean;
    error: string | null;
}

export const CLOSED_VIEW: IdleSessionView = {
    open: false,
    secondsRemaining: 0,
    staying: false,
    error: null,
};

/** What the page lends the controller: a clock, timers, the network and the exits. */
export interface IdleSessionHost {
    now(): number;
    setTimer(callback: () => void, delayMs: number): unknown;
    clearTimer(handle: unknown): void;
    /** Resolves when the server has refreshed the session; rejects when it has not. */
    sendHeartbeat(): Promise<void>;
    /** True once the page has been told the session is over, so the sign-in notice owns it. */
    sessionEnded(): boolean;
    /** Leave for the local sign-out. */
    signOut(): void;
    readSharedActivity(): string | null;
    writeSharedActivity(value: string): void;
}

export interface IdleSessionController {
    start(): void;
    stop(): void;
    /** The page reports the session over: close the warning and stop counting. */
    pause(): void;
    /** The user signed in again: count from now. */
    resume(): void;
    /** A pointer, key, touch or scroll event, which may be one of thousands. */
    activity(): void;
    /** The tab came back to the front. */
    visible(): void;
    /** Another tab recorded activity. */
    sharedActivityChanged(): void;
    stay(): Promise<void>;
    signOutNow(): void;
    getView(): IdleSessionView;
}

function sameView(a: IdleSessionView, b: IdleSessionView): boolean {
    return a.open === b.open && a.secondsRemaining === b.secondsRemaining
        && a.staying === b.staying && a.error === b.error;
}

export function createIdleSessionController(
    policy: IdlePolicy,
    host: IdleSessionHost,
    onView: (view: IdleSessionView) => void,
): IdleSessionController {
    let running = false;
    let paused = false;
    let signedOut = false;
    let lastActivityAt = 0;
    let lastActivityCountedAt = 0;
    // Zero until the first heartbeat succeeds, so the first activity is reported at once.
    let lastHeartbeatAt = 0;
    let heartbeatInFlight = false;
    let phaseTimer: unknown = null;
    let heartbeatTimer: unknown = null;
    let view: IdleSessionView = CLOSED_VIEW;

    const publish = (next: IdleSessionView) => {
        if (!sameView(view, next)) {
            view = next;
            onView(view);
        }
    };

    const clearPhaseTimer = () => {
        if (phaseTimer !== null) {
            host.clearTimer(phaseTimer);
            phaseTimer = null;
        }
    };

    const clearTimers = () => {
        clearPhaseTimer();
        if (heartbeatTimer !== null) {
            host.clearTimer(heartbeatTimer);
            heartbeatTimer = null;
        }
    };

    const inert = () => !running || paused || signedOut;

    // The latest activity in any tab. Never later than now.
    const mergeSharedActivity = (now: number) => {
        const shared = parseSharedActivity(host.readSharedActivity(), now);
        if (shared !== null && shared > lastActivityAt) {
            lastActivityAt = shared;
        }
    };

    const stampActivity = (now: number) => {
        lastActivityAt = now;
        host.writeSharedActivity(String(now));
    };

    const schedulePhaseCheck = (delayMs: number) => {
        phaseTimer = host.setTimer(evaluate, Math.min(MAX_TIMER_MS, Math.max(1, Math.ceil(delayMs))));
    };

    function signOutNow(): void {
        if (signedOut) {
            return;
        }
        signedOut = true;
        clearTimers();
        host.signOut();
    }

    // Decide where the session stands now and arrange to look again when that will change.
    function evaluate(): void {
        clearPhaseTimer();
        if (inert()) {
            return;
        }
        const now = host.now();
        mergeSharedActivity(now);
        const idleMs = Math.max(0, now - lastActivityAt);
        const phase = idlePhase(policy, idleMs);
        if (phase === 'expired') {
            if (view.open) {
                publish({ ...view, secondsRemaining: 0 });
            }
            signOutNow();
            return;
        }
        if (phase === 'warning') {
            publish({
                open: true,
                secondsRemaining: secondsUntilSignOut(policy, idleMs),
                staying: view.staying,
                error: view.error,
            });
            schedulePhaseCheck(Math.min(1000, policy.timeoutMs - idleMs));
            return;
        }
        publish(CLOSED_VIEW);
        schedulePhaseCheck((policy.warningEnabled ? policy.warningMs : policy.timeoutMs) - idleMs);
    }

    async function sendActivityHeartbeat(): Promise<void> {
        heartbeatInFlight = true;
        try {
            await host.sendHeartbeat();
            lastHeartbeatAt = host.now();
        } catch {
            // The sign-in notice owns an ended session, and the next activity tries again.
            if (host.sessionEnded()) {
                pause();
            }
        } finally {
            heartbeatInFlight = false;
        }
    }

    // Report activity now if a heartbeat is due. If one was sent a moment ago, report it as
    // soon as one is due, so the server's clock never runs behind the user's by more than the
    // interval and a user who stops moving is not signed out before the warning they are owed.
    function requestHeartbeat(now: number): void {
        if (heartbeatInFlight) {
            return;
        }
        const due = lastHeartbeatAt + policy.heartbeatIntervalMs;
        if (now >= due) {
            void sendActivityHeartbeat();
        } else if (heartbeatTimer === null) {
            heartbeatTimer = host.setTimer(() => {
                heartbeatTimer = null;
                if (inert()) {
                    return;
                }
                const later = host.now();
                mergeSharedActivity(later);
                if (idlePhase(policy, Math.max(0, later - lastActivityAt)) === 'active') {
                    requestHeartbeat(later);
                }
            }, due - now);
        }
    }

    function markActive(now: number): void {
        stampActivity(now);
        requestHeartbeat(now);
        evaluate();
    }

    function currentPhase(now: number): IdlePhase {
        mergeSharedActivity(now);
        return idlePhase(policy, Math.max(0, now - lastActivityAt));
    }

    function pause(): void {
        paused = true;
        clearTimers();
        publish(CLOSED_VIEW);
    }

    return {
        start() {
            running = true;
            paused = false;
            signedOut = false;
            const now = host.now();
            stampActivity(now);
            evaluate();
        },
        stop() {
            running = false;
            clearTimers();
        },
        pause,
        resume() {
            if (!running || !paused) {
                return;
            }
            paused = false;
            stampActivity(host.now());
            evaluate();
        },
        activity() {
            if (inert()) {
                return;
            }
            const now = host.now();
            if (now - lastActivityCountedAt < ACTIVITY_THROTTLE_MS) {
                return;
            }
            lastActivityCountedAt = now;
            // Input that arrives after the warning was due, with the timer not yet run, must
            // not quietly extend a session that has already crossed into the warning.
            if (currentPhase(now) !== 'active') {
                evaluate();
                return;
            }
            markActive(now);
        },
        visible() {
            if (inert()) {
                return;
            }
            const now = host.now();
            if (currentPhase(now) === 'active') {
                markActive(now);
            } else {
                evaluate();
            }
        },
        sharedActivityChanged() {
            evaluate();
        },
        async stay() {
            if (inert() || !view.open || view.staying) {
                return;
            }
            publish({ ...view, staying: true, error: null });
            try {
                await host.sendHeartbeat();
            } catch {
                if (inert()) {
                    return;
                }
                if (host.sessionEnded()) {
                    pause();
                    return;
                }
                publish({ ...view, staying: false, error: STAY_SIGNED_IN_FAILED_MESSAGE });
                return;
            }
            if (inert()) {
                return;
            }
            const now = host.now();
            lastHeartbeatAt = now;
            stampActivity(now);
            publish(CLOSED_VIEW);
            evaluate();
        },
        signOutNow,
        getView: () => view,
    };
}
