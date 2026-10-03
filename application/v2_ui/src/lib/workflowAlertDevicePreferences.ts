// workflowAlertDevicePreferences.ts
// Per-browser workflow alert switches shared by V2, classic and the alert sound helper.

import { useSyncExternalStore } from 'react';

export const WORKFLOW_ALERT_PLAY_SOUNDS_KEY = 'simplechat.workflowAlerts.playSounds';
export const WORKFLOW_ALERT_MONITOR_KEY = 'simplechat.workflowAlerts.monitor';

type Listener = () => void;

const listeners = new Set<Listener>();

function readBoolean(key: string, fallback: boolean): boolean {
    try {
        const value = localStorage.getItem(key);
        if (value === null) {
            return fallback;
        }
        return value === 'true';
    } catch {
        return fallback;
    }
}

function writeBoolean(key: string, value: boolean): void {
    try {
        localStorage.setItem(key, value ? 'true' : 'false');
    } catch {
        /* A locked-down browser simply keeps the in-memory default. */
    }
    notifyWorkflowAlertPreferenceListeners();
}

function subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
}

function notifyWorkflowAlertPreferenceListeners(): void {
    for (const listener of [...listeners]) {
        listener();
    }
}

if (typeof window !== 'undefined') {
    window.addEventListener('storage', (event) => {
        if (event.key === WORKFLOW_ALERT_PLAY_SOUNDS_KEY || event.key === WORKFLOW_ALERT_MONITOR_KEY) {
            notifyWorkflowAlertPreferenceListeners();
        }
    });
}

export function workflowAlertSoundsDeviceEnabled(): boolean {
    return readBoolean(WORKFLOW_ALERT_PLAY_SOUNDS_KEY, true);
}

export function setWorkflowAlertSoundsDeviceEnabled(enabled: boolean): void {
    writeBoolean(WORKFLOW_ALERT_PLAY_SOUNDS_KEY, enabled);
}

export function workflowAlertMonitorEnabled(): boolean {
    return readBoolean(WORKFLOW_ALERT_MONITOR_KEY, false);
}

export function setWorkflowAlertMonitorEnabled(enabled: boolean): void {
    writeBoolean(WORKFLOW_ALERT_MONITOR_KEY, enabled);
}

export function subscribeWorkflowAlertDevicePreferences(listener: Listener): () => void {
    return subscribe(listener);
}

export function useWorkflowAlertDevicePreference(key: 'sound' | 'monitor'): boolean {
    return useSyncExternalStore(
        subscribe,
        () => (key === 'sound' ? workflowAlertSoundsDeviceEnabled() : workflowAlertMonitorEnabled()),
        () => (key === 'sound'),
    );
}
