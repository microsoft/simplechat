// workflowAlertSound.ts
// Local workflow alert sounds, coordinated so only one tab in a browser plays them.

import { useSyncExternalStore } from 'react';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { workflowAlertSoundsDeviceEnabled, subscribeWorkflowAlertDevicePreferences } from './workflowAlertDevicePreferences';
import { workflowAlertPriorityRank, type WorkflowAlert, type WorkflowAlertEntry } from './workflowAlertNotices';

export const WORKFLOW_ALERT_SOUND_REPEAT_MS = 5_000;

const LOCK_NAME = 'simplechat.workflowAlertSound';

type Listener = () => void;
type SoundMode = 'once' | 'repeat';

interface SoundRequest {
    ids: string[];
    url: string;
    mode: SoundMode;
}

const listeners = new Set<Listener>();
let blocked = false;
let soundsEnabledOverride: boolean | null = null;
let activeRequest: SoundRequest | null = null;
let blockedRequest: SoundRequest | null = null;
let abortController: AbortController | null = null;
// Alerts whose one-off sound has played on this page. Every read returns a pending alert again,
// and "Play once" must not chime on each of them.
const playedOnceIds = new Set<string>();

function emit(): void {
    for (const listener of [...listeners]) {
        listener();
    }
}

function setBlocked(next: boolean): void {
    if (blocked !== next) {
        blocked = next;
        emit();
    }
}

function adminEnabled(): boolean {
    if (soundsEnabledOverride !== null) {
        return soundsEnabledOverride;
    }
    return useBootstrapStore.getState().data?.features?.enable_workflow_alert_sounds !== false;
}

function canPlay(): boolean {
    return adminEnabled() && workflowAlertSoundsDeviceEnabled();
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

async function playUrl(url: string): Promise<void> {
    const audio = new Audio(url);
    audio.preload = 'auto';
    await audio.play();
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

function strongestSoundEntry(entries: WorkflowAlertEntry[], mustOnly: boolean): SoundRequest | null {
    const candidates = entries
        .flatMap((entry) => entry.alerts)
        .filter((alert) => alert.sound !== 'off' && (!mustOnly || (alert.requireAcknowledgment && !alert.acknowledged)));
    if (!candidates.length) {
        return null;
    }
    candidates.sort((left, right) => {
        const repeat = (right.sound === 'repeat' ? 1 : 0) - (left.sound === 'repeat' ? 1 : 0);
        return repeat || workflowAlertPriorityRank(right.priority) - workflowAlertPriorityRank(left.priority);
    });
    const lead = candidates[0];
    return {
        ids: candidates.map((alert) => alert.id),
        url: soundUrl(lead),
        mode: lead.sound === 'repeat' ? 'repeat' : 'once',
    };
}

function stopLoop(): void {
    abortController?.abort();
    abortController = null;
    activeRequest = null;
}

async function runSound(request: SoundRequest, signal: AbortSignal): Promise<void> {
    do {
        if (!canPlay() || signal.aborted) {
            return;
        }
        try {
            await playUrl(request.url);
            blockedRequest = null;
            setBlocked(false);
        } catch (error) {
            if ((error as DOMException).name !== 'AbortError') {
                blockedRequest = request;
                setBlocked(true);
            }
            return;
        }
        if (request.mode !== 'repeat') {
            return;
        }
        await wait(WORKFLOW_ALERT_SOUND_REPEAT_MS, signal);
    } while (!signal.aborted);
}

async function withSoundLock(task: (signal: AbortSignal) => Promise<void>, signal: AbortSignal): Promise<void> {
    const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
    if (!locks || typeof locks.request !== 'function') {
        await task(signal);
        return;
    }
    await locks.request(LOCK_NAME, { mode: 'exclusive', signal }, async () => {
        if (signal.aborted || !activeRequest) {
            return;
        }
        await task(signal);
    });
}

function startRequest(request: SoundRequest): void {
    if (!canPlay()) {
        stopLoop();
        setBlocked(false);
        return;
    }
    const key = `${request.mode}:${request.url}:${request.ids.join(',')}`;
    const activeKey = activeRequest ? `${activeRequest.mode}:${activeRequest.url}:${activeRequest.ids.join(',')}` : '';
    if (key === activeKey && abortController && !abortController.signal.aborted) {
        return;
    }
    stopLoop();
    activeRequest = request;
    const controller = new AbortController();
    abortController = controller;
    void withSoundLock(async (signal) => {
        await runSound(request, signal);
        if (activeRequest === request) {
            stopLoop();
        }
    }, controller.signal).catch(() => {
        if (!controller.signal.aborted) {
            stopLoop();
        }
    });
}

export function setWorkflowAlertSoundsEnabled(enabled: boolean | null): void {
    soundsEnabledOverride = enabled;
    if (!canPlay()) {
        stopLoop();
        setBlocked(false);
    }
}

export function startWorkflowAlertSoundForEntries(entries: WorkflowAlertEntry[], options: { mustOnly?: boolean } = {}): void {
    const request = strongestSoundEntry(entries, options.mustOnly === true);
    if (!request) {
        return;
    }
    if (request.mode === 'once') {
        if (request.ids.every((id) => playedOnceIds.has(id))) {
            return;
        }
        request.ids.forEach((id) => playedOnceIds.add(id));
    }
    startRequest(request);
}

export function stopWorkflowAlertSound(ids?: Iterable<string>): void {
    if (!ids || !activeRequest) {
        stopLoop();
        return;
    }
    const gone = new Set(ids);
    if (activeRequest.ids.some((id) => gone.has(id))) {
        stopLoop();
    }
}

/** Try a sound the browser refused again; called from a user's click or key press. */
export function retryWorkflowAlertSound(): void {
    // Only a refused sound is retried. Restarting a sound that is playing would add a beep on
    // every click or key press while a repeating alert waits.
    if (!blocked || !blockedRequest) {
        return;
    }
    const request = blockedRequest;
    activeRequest = null;
    startRequest(request);
}

export function workflowAlertSoundBlocked(): boolean {
    return blocked;
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

if (typeof window !== 'undefined') {
    const retry = () => retryWorkflowAlertSound();
    window.addEventListener('pointerdown', retry, true);
    window.addEventListener('keydown', retry, true);
}
