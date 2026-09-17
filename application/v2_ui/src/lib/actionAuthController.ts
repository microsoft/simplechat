// actionAuthController.ts
// Deliberately not a Zustand/persisted store: only private, non-secret control state lives here.

import {
    actionAuthErrorMessage, actionAuthPreflightBody, cancelActionAuthRequest,
    normalizeActionAuthState, normalizeActionCredentialsControl, preflightActionAuth, readActionAuthRequest,
    type ActionAuthPreflight, type ActionAuthState,
} from './actionAuth';

export type ActionAuthSurface = 'chat' | 'admin-yamcs';
export interface ActionAuthReceipt { requestId: string | null }
export interface ActionAuthInteraction {
    id: number;
    surface: ActionAuthSurface;
    phase: 'checking' | 'waiting' | 'saving';
    state: ActionAuthState | null;
    error: string | null;
    repair: boolean;
    executionStarted: boolean | null;
    repairTargetUnavailable?: boolean;
}
export interface ActionAuthSubmission {
    id: number;
    requestId: string;
    signal: AbortSignal;
}

interface InteractionOptions {
    surface: ActionAuthSurface;
    isCurrent: () => boolean;
}

interface PendingInteraction {
    id: number;
    input: ActionAuthPreflight;
    isCurrent: () => boolean;
    controller: AbortController;
    resolve: (receipt: ActionAuthReceipt | null) => void;
    sharingAccepted: boolean;
}

const transport = {
    preflight: preflightActionAuth,
    read: readActionAuthRequest,
    cancel: cancelActionAuthRequest,
};

export class ActionAuthController {
    private generation = 0;
    private snapshot: ActionAuthInteraction | null = null;
    private pending: PendingInteraction | null = null;
    private listeners = new Set<() => void>();
    private readonly io: typeof transport;
    private readingId: number | null = null;

    constructor(io = transport) {
        this.io = io;
    }

    getSnapshot = (): ActionAuthInteraction | null => this.snapshot;
    subscribe = (listener: () => void): (() => void) => {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    };

    private publish(snapshot: ActionAuthInteraction | null): void {
        this.snapshot = snapshot;
        for (const listener of this.listeners) listener();
    }

    private current(id: number): boolean {
        if (this.pending?.id !== id) return false;
        if (!this.pending.isCurrent()) {
            this.cancel();
            return false;
        }
        return true;
    }

    private acceptState(id: number, value: ActionAuthState): void {
        if (!this.current(id) || !this.snapshot) return;
        const state = normalizeActionAuthState(value);
        this.publish({ ...this.snapshot, phase: 'waiting', state, error: null });
        if (state.status === 'ready' && !this.snapshot?.repair &&
            (!state.uses_personal_credentials || !state.shared_conversation || this.pending?.sharingAccepted)) {
            this.finish();
        }
    }

    private finish(): void {
        const pending = this.pending;
        const state = this.snapshot?.state;
        if (!pending || !state || !this.current(pending.id) || state.status !== 'ready') return;
        this.pending = null;
        this.publish(null);
        pending.controller.abort();
        pending.resolve({ requestId: state.request_id });
    }

    request(input: ActionAuthPreflight, options: InteractionOptions): Promise<ActionAuthReceipt | null> {
        // A second click must not replace the first continuation or claim a second execution.
        if (this.pending || !options.isCurrent()) return Promise.resolve(null);
        return new Promise((resolve) => {
            const id = ++this.generation;
            this.pending = {
                id, input: actionAuthPreflightBody(input), isCurrent: options.isCurrent,
                controller: new AbortController(), resolve, sharingAccepted: false,
            };
            this.publish({ id, surface: options.surface, phase: 'checking', state: null, error: null, repair: false, executionStarted: null });
            void this.checkAgain();
        });
    }

    async checkAgain(): Promise<void> {
        const pending = this.pending;
        if (!pending || !this.snapshot || this.readingId === pending.id || this.snapshot.phase === 'saving' || !this.current(pending.id)) return;
        this.readingId = pending.id;
        const requestId = this.snapshot.state?.request_id;
        this.publish({ ...this.snapshot, phase: 'checking', error: null });
        try {
            const state = requestId
                ? await this.io.read(requestId, pending.controller.signal)
                : await this.io.preflight(pending.input, pending.controller.signal);
            this.acceptState(pending.id, state);
        } catch (error) {
            if (this.current(pending.id) && this.snapshot && !pending.controller.signal.aborted) {
                this.publish({ ...this.snapshot, phase: 'waiting', error: actionAuthErrorMessage(error) });
            }
        } finally {
            if (this.readingId === pending.id) this.readingId = null;
        }
    }

    acknowledgeSharing(accepted: boolean): void {
        if (this.pending) this.pending.sharingAccepted = accepted;
    }

    continue(): void {
        if (!this.snapshot || this.snapshot.phase !== 'waiting') return;
        const state = this.snapshot.state;
        if (state?.uses_personal_credentials && state.shared_conversation && !this.pending?.sharingAccepted) return;
        this.finish();
    }

    /** The form owns the HTTP credential body; this controller only allocates a lifecycle token. */
    startSubmission(): ActionAuthSubmission | null {
        const pending = this.pending;
        if (!pending || !this.current(pending.id) || !this.snapshot ||
            this.snapshot.phase !== 'waiting' || this.snapshot.state?.status !== 'credentials_required') return null;
        const requestId = this.snapshot.state.request_id;
        if (!requestId || this.snapshot.state.shared_conversation && !pending.sharingAccepted) return null;
        this.publish({ ...this.snapshot, phase: 'saving', error: null });
        return { id: pending.id, requestId, signal: pending.controller.signal };
    }

    completeSubmission(submission: ActionAuthSubmission, state: ActionAuthState): void {
        this.acceptState(submission.id, state);
    }

    failSubmission(submission: ActionAuthSubmission, error: unknown): void {
        if (this.current(submission.id) && this.snapshot && !submission.signal.aborted) {
            this.publish({ ...this.snapshot, phase: 'waiting', error: actionAuthErrorMessage(error) });
        }
    }

    cancel(surface?: ActionAuthSurface): void {
        if (surface && this.snapshot?.surface !== surface) return;
        const pending = this.pending;
        const requestId = this.snapshot?.state?.request_id;
        this.pending = null;
        this.readingId = null;
        this.publish(null);
        if (!pending) return;
        pending.controller.abort();
        pending.resolve(null);
        if (requestId) void this.io.cancel(requestId).catch(() => {
            // Local cancellation is final even if the server cannot be reached; its request expires.
        });
    }

    cancelForRun(runId: string | undefined): void {
        if (runId && this.pending?.input.run_id === runId) this.cancel('chat');
    }

    /** A started turn is never replayed after repair, even when saving makes the identity ready. */
    repair(value: unknown, input: ActionAuthPreflight, options: InteractionOptions): void {
        if (!options.isCurrent()) return;
        this.cancel();
        const control = normalizeActionCredentialsControl(value);
        const id = ++this.generation;
        if (control?.execution_started === true && !control.action_ref) {
            this.publish({
                id, surface: options.surface, phase: 'waiting', state: null,
                error: 'The affected action could not be identified. Reopen its saved configuration or contact its administrator before retrying.',
                repair: true, executionStarted: true, repairTargetUnavailable: true,
            });
            return;
        }
        const repairInput = control?.execution_started === true
            ? {
                action_ref: control.action_ref,
                conversation_id: input.conversation_id,
                conversation_kind: input.conversation_kind,
            } : input;
        const controller = new AbortController();
        this.pending = {
            id, input: actionAuthPreflightBody(repairInput), isCurrent: options.isCurrent,
            controller, resolve: () => {}, sharingAccepted: false,
        };
        this.publish({
            id, surface: options.surface, phase: 'checking', state: null, error: null,
            repair: true, executionStarted: control?.execution_started ?? null,
        });
        // Started runs may already be finished and their receipts consumed. Repair only
        // the affected action with a fresh request, never the old plan or root agent.
        const requestId = control?.execution_started === true ? undefined : control?.request_id;
        if (!requestId) {
            void this.checkAgain();
            return;
        }
        void this.io.read(requestId, controller.signal).then((state) => this.acceptState(id, state)).catch((error) => {
            if (this.current(id) && this.snapshot) {
                this.publish({ ...this.snapshot, phase: 'waiting', error: actionAuthErrorMessage(error) });
            }
        });
    }
}

export const actionAuthController = new ActionAuthController();
