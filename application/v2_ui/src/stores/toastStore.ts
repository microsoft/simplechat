// toastStore.ts
// Transient user-facing notifications.
//
// Several actions in the chat page succeed or fail entirely server-side — exports, masking,
// attempt switching. Without somewhere to say so, a failure looks identical to a dead
// button, which is the exact complaint that motivated this work.
//
// Exports needed more than a result. A message export is rendered by the server and a
// PowerPoint additionally asks a model to plan its slides, so it can run for a long time with
// nothing on screen. A `pending` toast stays put until the work finishes and is then settled
// in place, so the answer replaces the progress note rather than stacking underneath it.

import { create } from 'zustand';

export type ToastTone = 'success' | 'error' | 'info' | 'pending';

/**
 * An offer to reverse what the toast is reporting.
 *
 * Exists for actions that are applied immediately and in bulk, where a confirmation dialog
 * beforehand would be worse: it would interrupt every correct use of the gesture to guard
 * against the rare wrong one. Reversing afterwards puts the cost on the mistake instead.
 */
export interface ToastAction {
    label: string;
    onAct: () => void;
}

export interface Toast {
    id: number;
    tone: ToastTone;
    message: string;
    action?: ToastAction;
}

interface ToastState {
    toasts: Toast[];
    push: (tone: ToastTone, message: string, action?: ToastAction) => number;
    settle: (id: number, tone: Exclude<ToastTone, 'pending'>, message: string) => void;
    dismiss: (id: number) => void;
}

/**
 * How long a toast stays before dismissing itself. Errors linger, since they need reading.
 *
 * `pending` has no entry: it is dismissed by whoever raised it, because only the caller knows
 * when the work is done.
 */
const TOAST_TTL: Record<Exclude<ToastTone, 'pending'>, number> = {
    success: 3200,
    info: 3800,
    error: 6500,
};

let nextId = 1;

export const useToastStore = create<ToastState>((set, get) => ({
    toasts: [],

    push: (tone, message, action) => {
        const id = nextId;
        nextId += 1;

        set((state) => ({ toasts: [...state.toasts, { id, tone, message, action }] }));

        if (tone !== 'pending') {
            window.setTimeout(() => {
                get().dismiss(id);
            }, TOAST_TTL[tone]);
        }

        return id;
    },

    /**
     * Turn a pending toast into its result, keeping its place in the stack.
     *
     * A failure is never dropped. If the pending toast is already gone the error is raised
     * as a fresh notification instead, because a silent failure looks exactly like a dead
     * button — the thing this store exists to prevent. A success that arrives after the
     * notice went away is discarded, since the downloaded file already speaks for itself.
     */
    settle: (id, tone, message) => {
        if (!get().toasts.some((item) => item.id === id)) {
            if (tone === 'error') {
                get().push('error', message);
            }
            return;
        }

        set((state) => ({
            toasts: state.toasts.map((item) => (item.id === id ? { ...item, tone, message } : item)),
        }));

        window.setTimeout(() => {
            get().dismiss(id);
        }, TOAST_TTL[tone]);
    },

    dismiss: (id) => {
        set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) }));
    },
}));

/** Convenience for non-component code, which cannot use the hook form. */
export const toast = {
    success: (message: string, action?: ToastAction) =>
        useToastStore.getState().push('success', message, action),
    error: (message: string) => useToastStore.getState().push('error', message),
    info: (message: string, action?: ToastAction) =>
        useToastStore.getState().push('info', message, action),
    /** Raise a notification that stays until `settle` or `dismiss` is called with its id. */
    pending: (message: string) => useToastStore.getState().push('pending', message),
    settle: (id: number, tone: Exclude<ToastTone, 'pending'>, message: string) =>
        useToastStore.getState().settle(id, tone, message),
    dismiss: (id: number) => useToastStore.getState().dismiss(id),
};
