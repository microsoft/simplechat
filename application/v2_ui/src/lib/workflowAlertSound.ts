// workflowAlertSound.ts
// Workflow alert sounds, played from local files, so that only one tab in a browser sounds.
//
// The sound follows the alerts this tab holds rather than keeping its own list of them: the
// store reports every change (syncWorkflowAlertSound), so an alert acknowledged here, in another
// tab or on another device stops sounding as soon as the store lets it go, however it went.
//
// - Alerts that need acknowledgment and repeat keep one loop going, every five seconds, in the
//   tone of the loudest of them, until none is left. The loop holds the Web Lock
//   `simplechat.workflowAlertSound`, which classic shares, so another tab waits its turn and
//   takes over only when this one stops. Each tick checks the administrator's and the device's
//   switches, so turning sound off silences it at once and turning it on resumes it.
// - "Play once" is a one-off. Alerts asked for together chime once, in the tone of the loudest of
//   them. A chime never interrupts the loop, skips while another sound holds the lock, and is
//   recorded for the whole browser, so another tab doesn't chime for the same alert.
// - A sound the browser refuses (autoplay) is kept, and the next click or key press, or Enable
//   sound, tries it again. A refused loop gives up the lock, so a tab that may play takes over.
//   A sound that is playing is never restarted by a click.

import { useSyncExternalStore } from 'react';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { subscribeWorkflowAlertDevicePreferences, workflowAlertSoundsDeviceEnabled } from './workflowAlertDevicePreferences';
import { workflowAlertPriorityRank, type WorkflowAlert } from './workflowAlertNotices';

export const WORKFLOW_ALERT_SOUND_REPEAT_MS = 5_000;

const LOCK_NAME = 'simplechat.workflowAlertSound';
const SOUNDED_ONCE_KEY = 'simplechat.workflowAlerts.soundedOnce';
const SOUNDED_ONCE_TTL_MS = 25 * 3_600_000;
const SOUNDED_ONCE_MAX = 500;

type Listener = () => void;

const listeners = new Set<Listener>();
let adminOverride: boolean | null = null;
/** The tone the loop plays while one is wanted, kept while a refused loop waits for a retry. */
let loopUrl: string | null = null;
let loopController: AbortController | null = null;
/** The browser refused the loop's tone, and it hasn't played since. */
let loopRefused = false;
/** A retry of refused one-off sounds is on its way. */
let retryingOnce = false;
/** One-off sounds this page has started for, so an alert read again doesn't chime again. */
const triedOnce = new Set<string>();
/** One-off sounds the browser refused, tried again on the next click or key press. */
const refusedOnce = new Map<string, WorkflowAlert>();
/** One-off sounds asked for in this task, which chime together once it ends. */
const pendingOnce = new Map<string, WorkflowAlert>();
let chimeQueued = false;

function emit(): void {
    for (const listener of [...listeners]) {
        listener();
    }
}

function adminEnabled(): boolean {
    if (adminOverride !== null) {
        return adminOverride;
    }
    return useBootstrapStore.getState().data?.features?.enable_workflow_alert_sounds !== false;
}

function canPlay(): boolean {
    return adminEnabled() && workflowAlertSoundsDeviceEnabled();
}

function needsAcknowledgment(alert: WorkflowAlert): boolean {
    return alert.requireAcknowledgment && !alert.acknowledged && alert.delivery === 'popup';
}

function soundUrl(alert: WorkflowAlert): string {
    if (alert.priority === 'critical') {
        return '/static/audio/workflow-alerts/alarm.wav';
    }
    if (workflowAlertPriorityRank(alert.priority) >= workflowAlertPriorityRank('medium')) {
        return '/static/audio/workflow-alerts/urgent.wav';
    }
    return '/static/audio/workflow-alerts/chime.wav';
}

function loudest(alerts: WorkflowAlert[]): WorkflowAlert {
    return [...alerts].sort((left, right) => workflowAlertPriorityRank(right.priority) - workflowAlertPriorityRank(left.priority))[0];
}

function isRefusal(error: unknown): boolean {
    return error instanceof DOMException && error.name === 'NotAllowedError';
}

/** Start a tone. Resolves once it plays; rejects only when the browser refuses to play it. */
async function startPlayback(url: string): Promise<void> {
    try {
        await new Audio(url).play();
    } catch (error) {
        if (isRefusal(error)) {
            throw error;
        }
        // A file that can't be played is not a refusal: there is nothing to enable or retry.
    }
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(resolve, ms);
        signal.addEventListener('abort', () => {
            clearTimeout(timer);
            reject(new DOMException('Aborted', 'AbortError'));
        }, { once: true });
    });
}

function lockManager(): LockManager | null {
    const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
    return locks && typeof locks.request === 'function' ? locks : null;
}

function readSoundedOnce(): Record<string, number> {
    try {
        const parsed: unknown = JSON.parse(localStorage.getItem(SOUNDED_ONCE_KEY) || '{}');
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as Record<string, number> : {};
    } catch {
        return {};
    }
}

function soundedOnce(id: string): boolean {
    const at = readSoundedOnce()[id];
    return typeof at === 'number' && Date.now() - at < SOUNDED_ONCE_TTL_MS;
}

function markSoundedOnce(ids: string[]): void {
    try {
        const now = Date.now();
        const marking = new Set(ids);
        const kept = Object.entries(readSoundedOnce())
            .filter(([id, at]) => !marking.has(id) && typeof at === 'number' && now - at < SOUNDED_ONCE_TTL_MS)
            .sort((left, right) => right[1] - left[1])
            .slice(0, Math.max(0, SOUNDED_ONCE_MAX - marking.size));
        const marked = [...marking].map((id) => [id, now] as const);
        localStorage.setItem(SOUNDED_ONCE_KEY, JSON.stringify(Object.fromEntries([...marked, ...kept])));
    } catch {
        /* Without storage, this page's own record still keeps it to one chime here. */
    }
}

/**
 * Chime once for alerts asked for together: in the tone of the loudest that hasn't chimed in this
 * browser yet, recording every one of them. One lock request for the whole batch, so the batch
 * makes one sound, rather than whichever alert asked first winning and the rest being dropped.
 */
async function chime(batch: WorkflowAlert[]): Promise<void> {
    if (!batch.length || !canPlay()) {
        return;
    }
    // Refusals the batch no longer needs: chimed in another tab, or covered by another sound.
    const forget = (alerts: WorkflowAlert[]): void => {
        let changed = false;
        for (const alert of alerts) {
            changed = refusedOnce.delete(alert.id) || changed;
        }
        if (changed) {
            emit();
        }
    };
    const run = async (): Promise<void> => {
        const fresh = batch.filter((alert) => !soundedOnce(alert.id));
        forget(batch.filter((alert) => !fresh.includes(alert)));
        if (!fresh.length) {
            return;
        }
        try {
            await startPlayback(soundUrl(loudest(fresh)));
        } catch {
            fresh.forEach((alert) => refusedOnce.set(alert.id, alert));
            emit();
            return;
        }
        markSoundedOnce(fresh.map((alert) => alert.id));
        forget(fresh);
    };
    const locks = lockManager();
    if (!locks) {
        await run();
        return;
    }
    // Checked and recorded under the lock, so two tabs can't both decide to chime. While another
    // sound holds it the browser is already sounding, and a chime would only talk over it.
    await locks.request(LOCK_NAME, { ifAvailable: true }, async (lock) => {
        if (lock) {
            await run();
        } else {
            forget(batch);
        }
    });
}

/** Chime for these alerts, together with any others asked for before this task ends. */
function queueChime(alerts: WorkflowAlert[]): void {
    for (const alert of alerts) {
        if (!triedOnce.has(alert.id)) {
            triedOnce.add(alert.id);
            pendingOnce.set(alert.id, alert);
        }
    }
    if (!pendingOnce.size || chimeQueued) {
        return;
    }
    chimeQueued = true;
    void Promise.resolve()
        .then(() => {
            chimeQueued = false;
            const batch = [...pendingOnce.values()];
            pendingOnce.clear();
            return chime(batch);
        })
        .catch(() => undefined);
}

async function runLoop(url: string, signal: AbortSignal): Promise<void> {
    const body = async (): Promise<void> => {
        while (!signal.aborted) {
            const startedAt = Date.now();
            if (canPlay()) {
                try {
                    await startPlayback(url);
                } catch {
                    // Refused: let go of the lock, so a tab that may play takes over.
                    loopRefused = true;
                    emit();
                    return;
                }
                if (loopRefused) {
                    loopRefused = false;
                    emit();
                }
            }
            await wait(Math.max(0, WORKFLOW_ALERT_SOUND_REPEAT_MS - (Date.now() - startedAt)), signal);
        }
    };
    const locks = lockManager();
    if (!locks) {
        await body();
        return;
    }
    await locks.request(LOCK_NAME, { mode: 'exclusive', signal }, async () => {
        if (!signal.aborted) {
            await body();
        }
    });
}

/**
 * Start the loop. A loop the browser refused stays refused -- Enable sound stays up -- until a
 * tone of the new one plays, so the control never flickers while the browser still says no.
 */
function startLoop(url: string, refused: boolean): void {
    const controller = new AbortController();
    loopController = controller;
    loopUrl = url;
    loopRefused = refused;
    void runLoop(url, controller.signal)
        .catch(() => undefined)
        .finally(() => {
            if (loopController === controller) {
                loopController = null;
                if (!loopRefused) {
                    // Ended some other way; the next report from the store starts it again.
                    loopUrl = null;
                }
            }
        });
}

function stopLoop(): void {
    loopController?.abort();
    loopController = null;
    loopUrl = null;
    loopRefused = false;
}

/**
 * Make the sound match the alerts this tab holds: everything waiting and everything shown. The
 * store calls this on every change, so a sound stops with the last alert that wanted it.
 */
export function syncWorkflowAlertSound(alerts: WorkflowAlert[]): void {
    const held = new Set(alerts.map((alert) => alert.id));
    for (const id of [...refusedOnce.keys()]) {
        if (!held.has(id)) {
            refusedOnce.delete(id);
        }
    }

    const waiting = alerts.filter((alert) => needsAcknowledgment(alert) && alert.sound !== 'off');
    const repeating = waiting.filter((alert) => alert.sound === 'repeat');
    const url = repeating.length ? soundUrl(loudest(repeating)) : null;
    if (url === null) {
        if (loopUrl !== null) {
            stopLoop();
        }
    } else if (url !== loopUrl) {
        const refused = loopRefused;
        stopLoop();
        startLoop(url, refused);
    }

    queueChime(waiting.filter((alert) => alert.sound === 'once'));
    emit();
}

/** Chime once for alerts this tab has just shown that don't need acknowledgment. */
export function playWorkflowAlertOnce(alerts: WorkflowAlert[]): void {
    queueChime(alerts.filter((alert) => alert.sound === 'once' && !needsAcknowledgment(alert)));
}

/** The administrator's setting, from the latest alerts read; null falls back to the bootstrap. */
export function setWorkflowAlertSoundsEnabled(enabled: boolean | null): void {
    if (adminOverride !== enabled) {
        adminOverride = enabled;
        emit();
    }
}

/**
 * Try the sounds the browser refused again. Called from a click or key press. Enable sound stays
 * up until one of them plays, so it never vanishes under the pointer or flickers on a refusal.
 */
export function retryWorkflowAlertSound(): void {
    if (!workflowAlertSoundBlocked()) {
        return;
    }
    if (loopRefused && loopUrl !== null && loopController === null) {
        startLoop(loopUrl, true);
    }
    if (refusedOnce.size && !retryingOnce) {
        retryingOnce = true;
        // The refused chimes are tried again together, as one, in the loudest tone.
        void chime([...refusedOnce.values()])
            .catch(() => undefined)
            .finally(() => {
                retryingOnce = false;
            });
    }
}

/** Whether a sound waits for a click or key press: "Enable sound" shows while it does. */
export function workflowAlertSoundBlocked(): boolean {
    return canPlay() && (loopRefused || refusedOnce.size > 0);
}

export function subscribeWorkflowAlertSound(listener: Listener): () => void {
    listeners.add(listener);
    const unsubscribePrefs = subscribeWorkflowAlertDevicePreferences(listener);
    return () => {
        listeners.delete(listener);
        unsubscribePrefs();
    };
}

export function useWorkflowAlertSoundBlocked(): boolean {
    return useSyncExternalStore(subscribeWorkflowAlertSound, workflowAlertSoundBlocked, () => false);
}

/** Silence everything and forget what has played. Only the alert lab and tests call this. */
export function resetWorkflowAlertSoundForLab(): void {
    stopLoop();
    triedOnce.clear();
    refusedOnce.clear();
    pendingOnce.clear();
    retryingOnce = false;
    try {
        localStorage.removeItem(SOUNDED_ONCE_KEY);
    } catch {
        /* Nothing recorded to forget. */
    }
    emit();
}

if (typeof window !== 'undefined') {
    const retry = () => retryWorkflowAlertSound();
    window.addEventListener('pointerdown', retry, true);
    window.addEventListener('keydown', retry, true);
}
