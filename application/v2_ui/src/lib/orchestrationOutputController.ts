// orchestrationOutputController.ts

import { ApiError } from './apiClient';
import { legacyPlanErrorMessage } from './orchestrationErrors';
import {
    fetchOrchestrationRun, normalizeOrchestrationAttempt, retryOrchestrationFile,
} from './orchestration';
import { readGeneratedArtifacts } from './generatedArtifacts';
import {
    hasPendingOrchestrationOutputs, mergeOrchestrationOutputs, normalizeOrchestrationOutputs,
    type OrchestrationOutput, type OrchestrationOutputRetry,
} from './orchestrationOutputs';
import { defaultRunStorage, useOrchestrationStore } from '../stores/orchestrationStore';

const POLL_MS = 5000;
const REQUEST_TIMEOUT_MS = 20000;
const RETRY_STORAGE_PREFIX = 'simplechat.orchestration.output-retry.v1:';
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const reads = new Map<string, Promise<boolean>>();
const retryLocks = new Set<string>();
const observers = new Map<string, {
    conversationId: string;
    runId: string;
    readers: number;
    unsubscribe: () => void;
    timer?: ReturnType<typeof setTimeout>;
}>();

function keyFor(conversationId: string, runId: string, outputId?: string): string {
    return JSON.stringify([conversationId, runId, ...(outputId ? [outputId] : [])]);
}

function updateRetry(runId: string, outputId: string, patch: OrchestrationOutputRetry): void {
    const store = useOrchestrationStore.getState();
    const retries = store.runRecovery[runId]?.outputRetries ?? {};
    store.updateRunRecovery(runId, {
        outputRetries: { ...retries, [outputId]: { ...retries[outputId], ...patch } },
    });
}

function retryUuid(): string {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
    // The retry API requires a UUID even on HTTP development hosts.
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function restoreIntent(conversationId: string, runId: string, outputId: string): void {
    const current = useOrchestrationStore.getState().runRecovery[runId]?.outputRetries?.[outputId];
    if (current?.submissionId || current?.blocked) return;
    try {
        const raw = defaultRunStorage()?.getItem(RETRY_STORAGE_PREFIX + keyFor(conversationId, runId, outputId));
        if (!raw) return;
        const value: unknown = JSON.parse(raw);
        if (!value || typeof value !== 'object' || !('submissionId' in value)
            || typeof value.submissionId !== 'string' || !UUID_PATTERN.test(value.submissionId)
            || !('baselineAttemptCount' in value) || typeof value.baselineAttemptCount !== 'number'
            || !Number.isSafeInteger(value.baselineAttemptCount) || value.baselineAttemptCount < 0) {
            throw new Error('Invalid saved retry identity');
        }
        updateRetry(runId, outputId, {
            submissionId: value.submissionId, baselineAttemptCount: value.baselineAttemptCount,
            uncertain: true,
            error: 'A previous file retry was not confirmed in this tab. Check saved status or retry the same request.',
        });
    } catch {
        updateRetry(runId, outputId, {
            blocked: true,
            error: 'The saved retry identity could not be read. No new file retry will be requested from this tab.',
        });
    }
}

function clearIntent(conversationId: string, runId: string, outputId: string): boolean {
    try {
        const storage = defaultRunStorage();
        if (!storage) throw new Error('Tab storage unavailable');
        storage.removeItem(RETRY_STORAGE_PREFIX + keyFor(conversationId, runId, outputId));
        updateRetry(runId, outputId, {
            submissionId: undefined, baselineAttemptCount: undefined, uncertain: false, blocked: false, error: null,
        });
        return true;
    } catch {
        updateRetry(runId, outputId, {
            blocked: true,
            error: 'Saved file status was received, but this tab could not clear its retry identity. Check saved status before another retry.',
        });
        return false;
    }
}

function reconcileIntents(conversationId: string, runId: string, outputs: readonly OrchestrationOutput[]): void {
    for (const output of outputs) {
        if (!output.output_id) continue;
        restoreIntent(conversationId, runId, output.output_id);
        const action = useOrchestrationStore.getState().runRecovery[runId]?.outputRetries?.[output.output_id];
        if (!action?.submissionId || action.submitting) continue;
        if (output.available === false || (output.state && output.state !== 'failed')
            || (output.attempt_count !== null && action.baselineAttemptCount !== undefined
                && output.attempt_count > action.baselineAttemptCount)) {
            clearIntent(conversationId, runId, output.output_id);
        }
    }
}

function schedulePoll(key: string): void {
    const observer = observers.get(key);
    if (!observer) return;
    if (observer.timer) clearTimeout(observer.timer);
    observer.timer = undefined;
    const state = useOrchestrationStore.getState().runRecovery[observer.runId];
    if (state?.outputAccessDenied || (!hasPendingOrchestrationOutputs(state?.outputs)
        && !state?.outputError && !Object.values(state?.outputRetries ?? {}).some((retry) => retry.submissionId))) return;
    observer.timer = setTimeout(() => {
        void refreshOrchestrationOutputs(observer.conversationId, observer.runId);
    }, POLL_MS);
}

/** Snapshot reads are shared by the thread and drawer, and never execute anything. */
export function refreshOrchestrationOutputs(
    conversationId: string,
    runId: string,
    manual = false,
): Promise<boolean> {
    const key = keyFor(conversationId, runId);
    const existing = reads.get(key);
    if (existing) return existing;
    const revision = useOrchestrationStore.getState().runRecovery[runId]?.outputRevision ?? 0;
    useOrchestrationStore.getState().updateRunRecovery(runId, { outputChecking: true });
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    const request = (async () => {
        try {
            const record = await fetchOrchestrationRun(runId, { conversationId, signal: controller.signal });
            if (!record || record.run_id !== runId || record.conversation_id !== conversationId) {
                throw new Error('File status identity unavailable');
            }
            const snapshot = normalizeOrchestrationAttempt(record);
            if (snapshot.outputs === undefined) throw new Error('File status projection unavailable');
            const store = useOrchestrationStore.getState();
            // An older GET must not erase a retry receipt or a newer stream update.
            if ((store.runRecovery[runId]?.outputRevision ?? 0) === revision) {
                store.updateRunRecovery(runId, {
                    ...snapshot, status: record.status, outputError: null, outputAccessDenied: false,
                });
                reconcileIntents(conversationId, runId, snapshot.outputs);
                if (manual) {
                    for (const [outputId, action] of Object.entries(
                        useOrchestrationStore.getState().runRecovery[runId]?.outputRetries ?? {},
                    )) {
                        if (!action.submissionId && !action.submitting) {
                            updateRetry(runId, outputId, { error: null, blocked: false });
                        }
                    }
                }
            }
            return true;
        } catch (error) {
            const legacyMessage = legacyPlanErrorMessage(error);
            const denied = error instanceof ApiError && (error.isAuthError || error.status === 404);
            useOrchestrationStore.getState().updateRunRecovery(runId, {
                outputAccessDenied: denied || useOrchestrationStore.getState().runRecovery[runId]?.outputAccessDenied,
                outputError: legacyMessage || (denied
                    ? 'These files are not currently accessible. Sign in if needed, then check saved file status.'
                    : 'Saved file status could not be refreshed. Previous progress is shown; no work was restarted.'),
            });
            return false;
        } finally {
            clearTimeout(timeout);
            reads.delete(key);
            useOrchestrationStore.getState().updateRunRecovery(runId, { outputChecking: false });
            schedulePoll(key);
        }
    })();
    reads.set(key, request);
    return request;
}

/** Poll while a visible file is pending, even when its run already says partial or failed. */
export function observeOrchestrationOutputs(conversationId: string, runId: string): () => void {
    const key = keyFor(conversationId, runId);
    let observer = observers.get(key);
    if (!observer) {
        const unsubscribe = useOrchestrationStore.subscribe((state, previous) => {
            const currentRun = state.runRecovery[runId];
            const previousRun = previous.runRecovery[runId];
            if (currentRun?.outputs !== previousRun?.outputs
                || currentRun?.outputRetries !== previousRun?.outputRetries) schedulePoll(key);
        });
        observer = { conversationId, runId, readers: 0, unsubscribe };
        observers.set(key, observer);
        reconcileIntents(conversationId, runId, useOrchestrationStore.getState().runRecovery[runId]?.outputs ?? []);
        void refreshOrchestrationOutputs(conversationId, runId);
    }
    observer.readers += 1;
    return () => {
        const current = observers.get(key);
        if (!current || --current.readers > 0) return;
        if (current.timer) clearTimeout(current.timer);
        current.unsubscribe();
        observers.delete(key);
    };
}

/** Only step events are incremental; detail/terminal projections remain whole snapshots. */
export function applyOrchestrationOutputEvent(runId: string, event: unknown): void {
    const snapshot = normalizeOrchestrationAttempt(event);
    if (snapshot.outputs === undefined && snapshot.generated_artifacts === undefined) return;
    const store = useOrchestrationStore.getState();
    const previous = store.runRecovery[runId];
    store.updateRunRecovery(runId, {
        ...(snapshot.outputs !== undefined ? {
            outputs: mergeOrchestrationOutputs(previous?.outputs, snapshot.outputs),
        } : {}),
        ...(snapshot.generated_artifacts !== undefined ? {
            generated_artifacts: readGeneratedArtifacts({
                generated_artifacts: [...snapshot.generated_artifacts, ...(previous?.generated_artifacts ?? [])],
            }),
        } : {}),
    });
}

/** A user action retries one file, never its producer, plan, or siblings. */
export async function retryOrchestrationOutput(
    conversationId: string,
    runId: string,
    outputId: string,
): Promise<void> {
    const key = keyFor(conversationId, runId, outputId);
    if (retryLocks.has(key)) return;
    retryLocks.add(key);
    let requested = false;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    restoreIntent(conversationId, runId, outputId);
    updateRetry(runId, outputId, { submitting: true });
    try {
        const refreshed = await refreshOrchestrationOutputs(conversationId, runId);
        const state = useOrchestrationStore.getState().runRecovery[runId];
        const output = state?.outputs?.find((candidate) => candidate.output_id === outputId);
        const previous = state?.outputRetries?.[outputId];
        if (!refreshed || state?.outputAccessDenied || previous?.blocked || !output?.can_retry
            || output.available === false || output.attempt_count === null) {
            updateRetry(runId, outputId, {
                error: previous?.blocked && previous.error ? previous.error
                    : 'This file is not currently available for retry. Check saved file status; no new retry was requested.',
            });
            return;
        }
        const submissionId = previous?.submissionId ?? retryUuid();
        const baselineAttemptCount = previous?.baselineAttemptCount ?? output.attempt_count;
        const storage = defaultRunStorage();
        if (!storage) throw new Error('Tab storage unavailable');
        storage.setItem(RETRY_STORAGE_PREFIX + key, JSON.stringify({ submissionId, baselineAttemptCount }));
        updateRetry(runId, outputId, {
            submissionId, baselineAttemptCount, uncertain: false, error: null,
        });
        const controller = new AbortController();
        timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
        const outputRevision = useOrchestrationStore.getState().runRecovery[runId]?.outputRevision ?? 0;
        requested = true;
        const receipt = await retryOrchestrationFile(runId, outputId, {
            conversation_id: conversationId, submission_id: submissionId,
        }, controller.signal);
        const returnedOutput = normalizeOrchestrationOutputs([receipt?.output])?.[0];
        if (receipt?.run?.run_id !== runId || receipt.run.conversation_id !== conversationId
            || returnedOutput?.output_id !== outputId || !returnedOutput.state) {
            throw new Error('Unverified file retry receipt');
        }
        const snapshot = normalizeOrchestrationAttempt(receipt.run);
        const outputs = snapshot.outputs?.some((candidate) => candidate.output_id === outputId)
            ? snapshot.outputs : mergeOrchestrationOutputs(snapshot.outputs ?? state?.outputs, [returnedOutput]);
        if ((useOrchestrationStore.getState().runRecovery[runId]?.outputRevision ?? 0) === outputRevision) {
            useOrchestrationStore.getState().updateRunRecovery(runId, {
                ...snapshot, outputs, status: receipt.run.status, outputError: null, outputAccessDenied: false,
            });
        }
        clearIntent(conversationId, runId, outputId);
    } catch (error) {
        const legacyMessage = legacyPlanErrorMessage(error);
        const rejected = requested && error instanceof ApiError && error.status >= 400 && error.status < 500;
        const cleared = rejected ? clearIntent(conversationId, runId, outputId) : true;
        if (cleared) updateRetry(runId, outputId, {
            uncertain: requested && !rejected,
            blocked: Boolean(rejected),
            error: legacyMessage || (!requested
                ? 'The retry identity could not be saved in this tab. Enable browser storage and check saved file status. No new retry was requested.'
                : rejected
                    ? error instanceof ApiError && error.isAuthError
                        ? 'Your sign-in or file access has changed. Sign in if needed, then check saved file status before retrying.'
                        : error instanceof ApiError && error.status === 404
                            ? 'This file was not found or is no longer available.'
                            : 'The server did not accept this file retry. Check saved file status before another request.'
                    : 'The file retry could not be confirmed. Check saved status or retry this same request; other files and producer tasks will not repeat.'),
        });
    } finally {
        if (timeout) clearTimeout(timeout);
        retryLocks.delete(key);
        updateRetry(runId, outputId, { submitting: false });
        reconcileIntents(conversationId, runId, useOrchestrationStore.getState().runRecovery[runId]?.outputs ?? []);
        if (requested) void refreshOrchestrationOutputs(conversationId, runId);
    }
}
